'use strict';

/**
 * Orders Copy browser acceptance smoke against a real Next.js page, with
 * SYNTHETIC order data and isolated fake customer session.
 *
 * Requires: playwright-core, Chrome/Chromium, and a running copy of the app.
 * Example:
 *   ORDER_SMOKE_URL=http://127.0.0.1:3187/orders/ CHROME=/usr/bin/google-chrome \
 *     node tools/browser/orders-copy-smoke.cjs
 *
 * Security: intercepts all /api/ calls, refuses any other non-GET network
 * request, and never authenticates to Cognito or sends a WhatsApp message,
 * payment, invoice request, or customer order mutation.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');

const target = process.env.ORDER_SMOKE_URL || 'http://127.0.0.1:3187/orders/';
const id = 'WD-SYNTHETIC-COPY-001';
const data = {
  orders: [{
    orderNumber: id, referenceId: 'SYNTHETIC-REF-001',
    createdAt: 1793520000, amountPaise: 1299, currency: 'INR',
    currencyUnexpected: false, status: 'captured',
  }],
  cursor: '',
};

async function scenario(browser, width, height, allowClipboard) {
  const context = await browser.newContext({
    viewport: { width, height },
    locale: 'en-IN',
    permissions: allowClipboard ? ['clipboard-read', 'clipboard-write'] : [],
  });
  // A synthetic token is never sent to an external API. No actual account,
  // payment, private order, registered phone or Cognito identity is involved.
  await context.addInitScript(({ supported }) => {
    sessionStorage.setItem('wecare.customer.accessToken', 'synthetic-local-browser-smoke');
    sessionStorage.setItem('wecare.customer.expiresAt', String(Date.now() + 900000));
    if (!supported) Object.defineProperty(navigator, 'clipboard', {
      configurable: true, get: () => undefined,
    });
  }, { supported: allowClipboard });

  const intercepted = [];
  await context.route('**/*', async route => {
    const request = route.request();
    const url = request.url();
    const method = request.method();
    if (url.includes('/api/')) {
      intercepted.push(url.split('/api/').pop().split('?')[0]);
      if (url.includes('/ecommerce/my-orders')) {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(data),
        });
      } else if (url.includes('/customer/profile')) {
        await route.fulfill({
          status: 200, contentType: 'application/json', body: '{}',
        });
      } else {
        await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
      }
    } else if (method !== 'GET' && method !== 'HEAD') {
      await route.abort('blockedbyclient');
    } else {
      await route.continue();
    }
  });

  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.message).slice(0, 220)));
  try {
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const button = page.getByRole('button', { name: `Copy order ID ${id}` });
    try {
      await button.waitFor({ state: 'visible', timeout: 45000 });
    } catch {
      const body = await page.locator('body').innerText().catch(() => '');
      throw new Error('Copy button not rendered: ' + body.slice(0, 450) + ' pageErrors=' + errors.join(';'));
    }

    const metrics = await page.evaluate(copyId => {
      const buttonEl = document.querySelector(
        `button[aria-label="Copy order ID ${copyId}"]`);
      const label = document.querySelector('.ord-id-line .ord-ordno');
      const group = document.querySelector('.ord-id-line');
      const box = buttonEl.getBoundingClientRect();
      const textBox = label.getBoundingClientRect();
      const css = getComputedStyle(group);
      return {
        label: buttonEl.innerText.trim(),
        gap: css.gap,
        display: css.display,
        horizontalGap: +(box.left - textBox.right).toFixed(1),
        verticalOffset: +Math.abs(
          box.top + box.height / 2 - textBox.top - textBox.height / 2
        ).toFixed(1),
        buttonHeight: +box.height.toFixed(1),
        buttonWidth: +box.width.toFixed(1),
        documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
        apiAvailable: !!navigator.clipboard,
      };
    }, id);

    assert.equal(metrics.label, 'Copy', 'Copy action must have a visible label');
    assert.equal(metrics.display, 'inline-flex', 'Copy must share a row with order number');
    assert.equal(metrics.gap, '12px');
    assert.ok(Math.abs(metrics.horizontalGap - 12) < 1.5, JSON.stringify(metrics));
    assert.ok(metrics.verticalOffset < 1.5, JSON.stringify(metrics));
    assert.ok(metrics.buttonHeight >= 44 && metrics.buttonWidth >= 44,
      'Copy target must be at least 44px in each dimension');
    assert.ok(metrics.documentOverflow <= 2, 'Page-level horizontal overflow: ' + JSON.stringify(metrics));

    await button.click();
    if (allowClipboard) {
      const actual = await page.evaluate(async () => navigator.clipboard.readText());
      assert.equal(actual, id, 'Clipboard must contain the real displayed ID');
      await page.getByText('Done.', { exact: true })
        .waitFor({ state: 'visible', timeout: 5000 });
    } else {
      await page.getByText('Selected. Copy with keyboard.', { exact: true })
        .waitFor({ state: 'visible', timeout: 5000 });
      const selected = await page.evaluate(() => getSelection()?.toString().trim());
      assert.equal(selected, id, 'Fallback must select only the order ID');
    }
    console.log('ORDERS_COPY_BROWSER_PASS ' + JSON.stringify({
      width, height, mode: allowClipboard ? 'clipboard' : 'missing-api',
      metrics, mockedCalls: intercepted, scriptErrors: errors,
    }));
  } finally {
    await context.close();
  }
}

(async () => {
  const executablePath = process.env.CHROME || '/usr/bin/google-chrome';
  const browser = await chromium.launch({
    executablePath, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    await scenario(browser, 1280, 900, true);
    await scenario(browser, 390, 844, true);
    await scenario(browser, 280, 653, true);
    await scenario(browser, 390, 844, false);
  } finally {
    await browser.close();
  }
})().catch(e => {
  console.error('ORDERS_COPY_BROWSER_FAIL', e.stack || e);
  process.exitCode = 1;
});
