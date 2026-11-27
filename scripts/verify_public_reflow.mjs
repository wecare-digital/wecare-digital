#!/usr/bin/env node
/**
 * Browser acceptance for the nine routes that overflowed at high zoom.
 * Use Playwright with an approved built preview: PUBLIC_QA_BASE=https://...
 * node scripts/verify_public_reflow.mjs
 * No WebFont, cross-origin network requests, sign-in, messages, or payments.
 */
import assert from 'node:assert/strict';

assert.ok(process.env.PUBLIC_QA_BASE, 'Set PUBLIC_QA_BASE to an approved preview or website URL');
const base = new URL(process.env.PUBLIC_QA_BASE);
assert.ok(['http:', 'https:'].includes(base.protocol), 'Expected an HTTP(S) preview');
const { chromium } = await import('playwright').catch(() => {
  throw new Error('Install Playwright and Chromium in the QA environment');
});

const productRoutes = [
  '/elsewhere/trip/', '/elsewhere/visa/', '/elsewhere/arogya-yatra/',
  '/hunar/kaushal/', '/hunar/prastuti/', '/expo-week/', '/anew/',
];
const routes = [
  ...productRoutes,
  '/atmos/nano-climate/',
  '/checkout/',
  '/checkout/?test=WCTEST2R26', // allowlisted local cart prefill, no payment initiation
  '/checkout/?contribute=1', // opens review without selecting or paying
];

const browser = await chromium.launch({headless: true});
const failures = [];
try {
  for (const width of [160, 320]) {
    for (const path of routes) {
      // Fresh browser storage for each scenario; a test cart cannot leak.
      const context = await browser.newContext({
        viewport: {width, height: 640},
        hasTouch: true,
        reducedMotion: 'reduce',
        serviceWorkers: 'block',
      });
      await context.route('**/*', route => {
        const request = route.request();
        if (new URL(request.url()).origin !== base.origin
          || request.method() !== 'GET'
          || request.resourceType() === 'font') return route.abort();
        return route.continue();
      });

      try {
        const page = await context.newPage();
        const name = `${width}px ${path}`;
        try {
          const target = new URL(path, base);
          const response = await page.goto(target.href, {waitUntil: 'domcontentloaded', timeout: 30000});
          assert.ok(response?.ok(), `${name}: non-success page response`);
          assert.equal(new URL(page.url()).pathname, target.pathname, `${name}: wrong route`);
          const content = target.searchParams.has('test') ? '.cart-row'
            : target.searchParams.has('contribute') ? '.cart-contribution-review'
            : target.pathname === '/atmos/nano-climate/' ? '.vl-live-air-context'
            : productRoutes.includes(path) ? '.pbb .checkout-action' : '.cart-progress';
          await page.locator(content).first().waitFor({state: 'visible'});
          const metrics = await page.evaluate(() => {
            const inside = (node, parent = node.parentElement) => {
              const a = node.getBoundingClientRect();
              const b = parent.getBoundingClientRect();
              return a.width > 0 && a.left >= b.left - 2 && a.right <= b.right + 2;
            };
            return {
              documentWidth: document.documentElement.clientWidth,
              scrollWidth: document.documentElement.scrollWidth,
              icons: [...document.querySelectorAll('.pbb .checkout-action-icon')].map(icon => {
                const w = icon.getBoundingClientRect().width;
                return icon.tagName.toLowerCase() === 'svg' && w >= 19 && w <= 21 && inside(icon);
              }),
              cartSteps: [...document.querySelectorAll('.cart-progress > span')].map(step => inside(step)),
              cartControls: [...document.querySelectorAll('.cart-row-controls button')].map(control =>
                inside(control, control.closest('.cart-row-controls'))),
              localClock: [...document.querySelectorAll('.vl-live-air-context-item svg,.vl-live-local-datetime')]
                .map(control => inside(control, control.closest('.vl-live-air-context-item'))),
              clockRowsOverlap: (() => {
                const [location, time] = document.querySelectorAll('.vl-live-air-context-item');
                if (!location || !time) return false;
                return location.getBoundingClientRect().bottom > time.getBoundingClientRect().top + 2;
              })(),
            };
          });
          assert.equal(metrics.documentWidth, width, `${name}: viewport mismatch`);
          assert.ok(metrics.scrollWidth <= width + 2, `${name}: document is ${metrics.scrollWidth}px wide`);
          if (productRoutes.includes(path)) assert.ok(metrics.icons.length && metrics.icons.every(Boolean),
            `${name}: missing or out-of-bounds Checkout icon with fonts disabled`);
          if (path.startsWith('/checkout/')) assert.ok(metrics.cartSteps.length === 3 && metrics.cartSteps.every(Boolean),
            `${name}: checkout steps do not fit`);
          if (target.searchParams.has('test')) assert.ok(metrics.cartControls.length && metrics.cartControls.every(Boolean),
            `${name}: checkout item controls do not fit`);
          if (path === '/atmos/nano-climate/') assert.ok(metrics.localClock.length === 3 && metrics.localClock.every(Boolean)
            && !metrics.clockRowsOverlap, `${name}: location or time is clipped or overlapping`);
          console.log(`PASS ${name}`);
        } catch (error) {
          failures.push(`${name}: ${error.message}`);
        }
      } finally {
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
}
assert.equal(failures.length, 0, failures.join('\n'));
