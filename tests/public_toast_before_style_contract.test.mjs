/**
 * Updated customer requirement (1 November 2026): slim pale-lime action
 * toast with dark 14px text and a 4px stripe at the top-right corner.
 * No checkmark or icon. One actionable toast at a time.
 *
 * Source-only checks: never send WhatsApp messages or process payments here.
 * Run: node --test tests/public_toast_before_style_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('shared toast tokens keep lime colors with slim 14px sizing', () => {
  const tokens = read('src/styles/tokens.css');
  for (const [name, value] of [
    ['wc-toast-surface', '#f6fce4'],
    ['wc-toast-stripe', '#d8f382'],
    ['wc-toast-ink', '#1a1a1a'],
    ['wc-toast-radius', '10px'],
    ['wc-toast-stripe-width', '4px'],
    ['wc-toast-padding', '8px 12px'],
    ['wc-toast-type-size', '14px'],
    ['wc-toast-mobile-radius', '10px'],
    ['wc-toast-mobile-stripe-width', '4px'],
    ['wc-toast-mobile-padding', '8px 12px'],
    ['wc-toast-mobile-type-size', '14px'],
  ]) assert.ok(tokens.includes('--' + name + ': ' + value + ';'), name + ' must match screenshot');
});

test('public action toast uses screenshot tokens without changing inline errors', () => {
  const notice = read('src/components/public/PublicNotice.tsx');
  assert.match(notice, /border-inline-start:4px solid var\(--public-brand-lime\);border-radius:10px;/);
  assert.match(notice, /\.wc-public-notice\.is-inline\{inline-size:min\(100%,560px\)\}/);
  assert.match(notice, /\.wc-public-notice\.is-toast\{/);
  assert.match(notice, /border-inline-start:var\(--wc-toast-stripe-width\) solid var\(--wc-toast-stripe\)/);
  assert.match(notice, /border-radius:var\(--wc-toast-radius\)/);
  assert.match(notice, /background:var\(--wc-toast-surface\);color:var\(--wc-toast-ink\)/);
  assert.match(notice, /font-size:var\(--wc-toast-type-size\);font-weight:600;line-height:1\.4/);
  assert.match(notice, /--wc-toast-mobile-type-size/);
});

test('one public toast sits at top-right below the header on desktop and mobile', () => {
  const host = read('src/components/public/PublicToastProvider.tsx');
  assert.match(host, /top:calc\(108px \+ 12px\)/);
  assert.match(host, /inset-inline-end:max\(16px,env\(safe-area-inset-right\)\)/);
  assert.match(host, /top:calc\(96px \+ 10px\)/);
  assert.match(host, /max-inline-size:min\(100%,340px\)/);
  assert.match(host, /const \[ active, setActive \] = useState<PublicToast \| null>\( null \)/);
  assert.match(host, /setActive\( \{ id, message, tone \} \)/);
  assert.match(host, /<PublicNotice key=\{ active\.id \} mode="toast"/);
  assert.doesNotMatch(host, /bottom:max\(20px,env\(safe-area-inset-bottom\)\)/);
});

test('Workspace toasts use same tokens with no status glyph, but keep dismissal', () => {
  const css = read('src/styles/inner-ux.css');
  const toast = read('src/components/Toast.tsx');
  const ctx = read('src/contexts/ToastContext.tsx');
  for (const token of ['wc-toast-padding', 'wc-toast-surface', 'wc-toast-ink',
    'wc-toast-stripe', 'wc-toast-radius', 'wc-toast-type-size']) {
    assert.ok(css.includes('var(--' + token + ')'), 'Workspace must reuse ' + token);
  }
  assert.match(css, /top: max\(16px, env\(safe-area-inset-top\)\)/);
  assert.match(css, /max-width: min\(100%, 340px\)/);
  assert.doesNotMatch(css, /bottom: max\(20px, env\(safe-area-inset-bottom\)\)/);
  assert.match(css, /opacity: 0;/);
  assert.match(css, /\.toast:hover \.toast-close/);
  assert.match(toast, /aria-label="Dismiss notification"/);
  assert.match(toast, /role=\{toast\.type === 'error' \|\| toast\.type === 'warning' \? 'alert' : 'status'\}/);
  assert.doesNotMatch(toast, /toast-icon|const icons =/);
  assert.match(ctx, /setToasts\(\[\{ id, type, message \}\]\)/);
  assert.match(toast, /setToasts\(\[\{ id, type, message, duration \}\]\)/);
  assert.match(ctx, /String\(\+\+nextToastId\.current\)/);
  assert.match(toast, /String\(\+\+nextToastId\.current\)/);
});

test('Orders and PublicShare route their feedback through the common toast', () => {
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
