#!/usr/bin/env node
// Read-only browser smoke against an approved Amplify preview or production deployment.
// Usage: PUBLIC_QA_BASE=https://wecare.digital node scripts/verify_404_home_handoff.mjs
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.PUBLIC_QA_BASE;
assert.ok(base, 'Set PUBLIC_QA_BASE to an approved website URL');
const origin = new URL(base);
assert.ok(['http:', 'https:'].includes(origin.protocol), 'HTTP(S) base required');
const home = new URL('/', origin).href;
const missing = [
  '/grahak-os/', '/vayulok/', '/sehat/', '/dispatch/', '/niji-setu/', '/shop/niji-setu/',
  '/ritual-guru/', '/aastha/', '/ritual-guru/ritva/', '/ritual-guru/puja-guidance/',
  '/ritual-guru/diy-puja-kit/', '/shop/ritual-guru-puja-guidance/',
  '/shop/ritual-guru-diy-puja-kit/', '/shop/ritual-guru-ritva/',
  '/definitely-not-a-page/', '/definitely-not-a-page/nested/',
  '/vayulok/?utm_source=chatgpt.com', '/definitely-not-a-page?utm_source=qa',
];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ serviceWorkers: 'block' });
const results = [];
try {
  for (const path of missing) {
    const url = new URL(path, origin).href;
    const page = await context.newPage();
    try {
      const raw = await context.request.get(url);
      assert.equal(raw.status(), 404, path + ': preserve actual HTTP 404');
      assert.match(await raw.text(), /name="robots"[^>]*content="noindex, follow"/, path + ': noindex');
      // Register before navigation to catch immediate replacement on hydration.
      await Promise.all([
        page.waitForURL(home, { waitUntil: 'domcontentloaded', timeout: 30000 }),
        page.goto(url, { waitUntil: 'commit', timeout: 30000 }),
      ]);
      assert.equal(page.url(), home, path + ': exact Home, without old query or fragment');
      await page.locator('header.hdr').waitFor({ state: 'visible' });
      results.push({ path, status: 'pass', http: raw.status(), final: page.url() });
    } catch (error) {
      results.push({ path, status: 'fail', error: String(error) });
    } finally { await page.close(); }
  }
  for (const path of ['/', '/terms/', '/shop/', '/atmos/nano-climate/']) {
    const page = await context.newPage();
    try {
      const url = new URL(path, origin).href;
      const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
      assert.equal(response?.status(), 200, path);
      await page.locator('header.hdr').waitFor({ state: 'visible' });
      assert.equal(page.url(), url, path + ': valid page must remain at its own URL');
      results.push({ path, status: 'pass', http: response.status(), final: page.url() });
    } catch (error) {
      results.push({ path, status: 'fail', error: String(error) });
    } finally { await page.close(); }
  }
} finally {
  await context.close();
  await browser.close();
}
console.log(JSON.stringify({ origin: origin.origin, results }, null, 2));
if (results.some(row => row.status !== 'pass')) process.exitCode = 1;
