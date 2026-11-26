#!/usr/bin/env node
/**
 * Read-only public browser smoke: desktop, tablet, phone, and foldable-like
 * viewport sizes. Requires Playwright + Chromium in the QA environment.
 * Does not submit checkout, payment, login or WhatsApp forms.
 */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const base = process.env.PUBLIC_QA_BASE;
if (!base) throw new Error('Set PUBLIC_QA_BASE to an approved preview or public website URL.');
const origin = new URL(base);
if (!['http:', 'https:'].includes(origin.protocol)) throw new Error('HTTP(S) base required');
const output = process.env.PUBLIC_QA_OUTPUT || join(tmpdir(), 'wecare-public-qa-' + Date.now());
await mkdir(output, {recursive: true});
const { chromium } = await import('playwright').catch(() => {
  throw new Error('Install Playwright and Chromium in the QA environment; no production dependency is required.');
});
const devices = [
  ['desktop', 1440, 900, false],
  ['tablet-portrait', 768, 1024, true],
  ['tablet-landscape', 1024, 768, true],
  ['mobile', 390, 844, true],
  ['fold-cover', 320, 800, true],
  ['fold-unfolded', 720, 900, true],
];
const routes = [
  {path: '/', name: 'home'},
  {path: '/shop/', name: 'shop'},
  {path: '/terms/', name: 'terms', input: 'input[aria-label="Find a legal clause"]', query: 'refund'},
  {path: '/privacy/', name: 'privacy', input: 'input[aria-label="Find a legal clause"]', query: 'personal data'},
  {path: '/blog/', name: 'blog', input: '#blog-q', query: 'integrity'},
  {path: '/anew/', name: 'anew', input: '#pbp-q', query: 'integrity'},
  {path: '/orders/', name: 'orders'},
];
const browser = await chromium.launch({headless: true});
const results = [];
try {
  for (const [device, width, height, touch] of devices) {
    const context = await browser.newContext({viewport: {width, height}, hasTouch: touch, deviceScaleFactor: 1});
    try {
      for (const route of routes) {
        const page = await context.newPage();
        const name = device + '-' + route.name;
        try {
          const response = await page.goto(new URL(route.path, origin).href, {waitUntil: 'domcontentloaded', timeout: 30000});
          assert.ok(response && response.ok(), name + ': non-success response');
          await page.locator('h1').first().waitFor({state: 'attached'});
          await page.evaluate(() => document.fonts.ready);
          const dimensions = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth,
          }));
          assert.ok(dimensions.scroll <= dimensions.width + 2, name + ': horizontal page overflow ' + JSON.stringify(dimensions));
          await page.screenshot({path: join(output, name + '.png')});
          if (route.input) {
            const field = page.locator(route.input);
            const clear = field.locator('..').getByRole('button', {name: 'Clear search', exact: true});
            await field.fill(route.query);
            await clear.waitFor({state: 'visible', timeout: 10000});
            if (route.name === 'terms' || route.name === 'privacy') {
              await page.getByRole('list', {name: 'Matching clauses'}).getByRole('link').first().waitFor({state: 'visible'});
            }
            await page.screenshot({path: join(output, name + '-search.png')});
            const inputBox = await field.boundingBox();
            const clearBox = await clear.boundingBox();
            assert.ok(inputBox && clearBox && clearBox.width >= 44 && clearBox.height >= 44,
              name + ': missing or undersized clear target');
            assert.ok(clearBox.x >= inputBox.x && clearBox.x + clearBox.width <= inputBox.x + inputBox.width + 2,
              name + ': clear control overflows input');
            await clear.click();
            assert.equal(await field.inputValue(), '');
            assert.ok(await field.evaluate(el => el === document.activeElement), name + ': focus not restored');
            await field.fill(route.query);
            await field.press('Escape');
            assert.equal(await field.inputValue(), '');
            await clear.waitFor({state: 'hidden'});
          }
          results.push({device, path: route.path, status: 'pass'});
        } catch (error) {
          results.push({device, path: route.path, status: 'fail', error: String(error)});
          await page.screenshot({path: join(output, name + '-failure.png')}).catch(() => {});
        } finally {
          await page.close();
        }
      }
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({output, results}, null, 2));
if (results.some(result => result.status !== 'pass')) process.exitCode = 1;
