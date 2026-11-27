#!/usr/bin/env node
// Read-only public commerce browser acceptance on an approved preview/site.
// No login, payment, submission or private Vault access. The allowlisted
// local QA basket does not initiate payment. All POSTs and cross-origin
// requests are blocked by the browser context.
import assert from 'node:assert/strict';
assert.ok(process.env.PUBLIC_QA_BASE, 'Set PUBLIC_QA_BASE to an approved preview or site');
const origin = new URL(process.env.PUBLIC_QA_BASE);
assert.ok(['http:', 'https:'].includes(origin.protocol));
const { chromium } = await import('playwright');
const browser = await chromium.launch();
const marker = '[data-public-auth-button-theme="active"]';
const scenarios = [
  ['/', '.home-close-cta'],
  ['/auth/', '.phone-control'],
  ['/checkout/?test=WCTEST2R26', '.cart-row'],
  ['/checkout/?contribute=1', '.cart-contribution-review'],
  ['/checkout/status/', '.co-card'],
  ['/orders/', '.phone-control'], // guest Orders must hand off to Auth
];
const failures = [];
try {
  for (const width of [1440, 768, 390, 280, 160]) {
    for (const [path, selector] of scenarios) {
      const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce', serviceWorkers: 'block'});
      await context.route('**/*', route => {
        const r = route.request();
        if (r.method() !== 'GET' || new URL(r.url()).origin !== origin.origin || r.resourceType() === 'font') return route.abort();
        return route.continue();
      });
      const page = await context.newPage();
      try {
        const response = await page.goto(new URL(path, origin).href, {waitUntil:'domcontentloaded',timeout:30000});
        assert.ok(response?.ok(), path);
        await page.locator(selector).first().waitFor({state:'visible'});
        assert.equal(await page.locator(marker).count(), path === '/' ? 0 : 1, path + ' marker');
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2), path + ' document overflow');
        if (path === '/orders/') {
          const url = new URL(page.url());
          assert.equal(url.pathname.replace(/\/$/, ''), '/auth');
          assert.equal(url.searchParams.get('return'), '/orders/');
        }
        if (path === '/auth/' || path === '/orders/') {
          const field = page.locator('.phone-control > input');
          await field.focus();
          const style = await page.locator('.phone-control').evaluate(el => ({radius:getComputedStyle(el).borderRadius,shadow:getComputedStyle(el).boxShadow}));
          assert.equal(style.radius, '0px');
          assert.notEqual(style.shadow, 'none');
          assert.equal(await page.locator('.country-trigger').evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)');
        }
        if (path.includes('test=')) {
          const rows = await page.locator('.cart-row').evaluateAll(els => els.every(el => {
            const a = el.getBoundingClientRect(), b = el.parentElement.getBoundingClientRect();
            return a.left >= b.left - 2 && a.right <= b.right + 2;
          }));
          assert.ok(rows);
        }
        if (path === '/checkout/status/') {
          const card = await page.locator('.co-card').evaluate(el => ({shadow:getComputedStyle(el).boxShadow,radius:getComputedStyle(el).borderRadius}));
          assert.equal(card.shadow,'none');
          assert.equal(card.radius,'14px');
        }
        console.log('PASS',width,path);
      } catch (error) {
        failures.push({width,path,error:String(error)});
      } finally { await context.close(); }
    }
  }
} finally { await browser.close(); }
console.log(JSON.stringify({failures},null,2));
if (failures.length) process.exitCode = 1;
