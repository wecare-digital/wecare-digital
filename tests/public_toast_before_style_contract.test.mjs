/**
 * Regressions for the original WECARE.DIGITAL public toast presentation.
 * Source-only: no browser, WhatsApp sends, or payment API calls.
 *
 * Run: node --test tests/public_toast_before_style_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('all public toasts inherit the original lime notice styling', () => {
  const notice = read('src/components/public/PublicNotice.tsx');
  assert.match(notice, /border-inline-start:4px solid var\(--public-brand-lime\);border-radius:10px;/);
  assert.match(notice, /background:var\(--public-lime-tint\);color:var\(--public-text\);/);
  assert.match(notice, /\.wc-public-notice\.is-toast\{inline-size:fit-content;margin:0;padding:8px 12px\}/);
  assert.doesNotMatch(notice, /border-radius:12px;background:var\(--public-brand-green\);color:#fff;/);
});

test('shared public toast sits at top-right below the existing header', () => {
  const host = read('src/components/public/PublicToastProvider.tsx');
  assert.match(host, /top:calc\(108px \+ 12px\)/);
  assert.match(host, /top:calc\(96px \+ 12px\)/);
  assert.match(host, /inset-inline-end:max\(16px,env\(safe-area-inset-right\)\)/);
  assert.match(host, /justify-content:flex-end;align-items:flex-start/);
  assert.doesNotMatch(host, /bottom:max\(24px,env\(safe-area-inset-bottom\)\)/);
  assert.match(host, /const \[ active, setActive \] = useState<PublicToast \| null>\( null \)/);
  assert.match(host, /<PublicNotice key=\{ active\.id \} mode="toast"/);
});

test('all public action toasts share the same design, while inline errors remain', () => {
  const orders = read('src/components/orders/OrdersPage.tsx');
  const share = read('src/components/PublicShare.tsx');
  const app = read('src/pages/_app.tsx');
  const checkout = read('src/components/cart/CartPage.tsx');

  assert.match(app, /<PublicToastProvider>/);
  assert.match(orders, /usePublicToast\(\)/);
  assert.match(orders, /showToast\( notice\.message/);
  assert.match(share, /useOptionalPublicToast\(\)/);
  assert.match(share, /showToast\?\.\( 'Link copied\.'/);
  assert.match(orders, /<PublicNotice mode="inline" tone="error"/);
  assert.match(checkout, /<PublicNotice mode="inline" tone="error"/);
  assert.doesNotMatch(orders, /ord-toast-rail/);
});
