/**
 * Customer preference, 1 November 2026: one tiny, mobile-safe lime action toast
 * at the top-right for BOTH public/customer and authenticated Workspace.
 *
 * The global .wc-action-toast/.wc-action-toast-host rules are the design source.
 * Source-only regressions: no WhatsApp sends or payment API calls.
 * Run: node --test tests/public_toast_before_style_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('one compact toast vocabulary in global tokens', () => {
  const tokens = read('src/styles/tokens.css');
  for (const [name, value] of [
    ['wc-toast-surface', '#f6fce4'],
    ['wc-toast-stripe', '#d8f382'],
    ['wc-toast-ink', '#1a1a1a'],
    ['wc-toast-radius', '8px'],
    ['wc-toast-stripe-width', '3px'],
    ['wc-toast-padding', '6px 10px'],
    ['wc-toast-type-size', '13px'],
    ['wc-toast-max-width', '288px'],
    ['wc-toast-edge-gap', '12px'],
    ['wc-toast-mobile-radius', '8px'],
    ['wc-toast-mobile-stripe-width', '3px'],
    ['wc-toast-mobile-padding', '6px 10px'],
    ['wc-toast-mobile-type-size', '13px'],
  ]) assert.ok(tokens.includes('--' + name + ': ' + value + ';'), name);
});

test('public and Workspace render the SAME one-source toast CSS class', () => {
  const css = read('src/styles/inner-ux.css');
  const publicNotice = read('src/components/public/PublicNotice.tsx');
  const workspaceToast = read('src/components/Toast.tsx');
  const app = read('src/pages/_app.tsx');

  assert.match(css, /\.wc-action-toast\s*\{/);
  assert.match(css, /\.wc-action-toast-host\s*\{/);
  assert.match(css, /padding:\s*var\(--wc-toast-padding\)/);
  assert.match(css, /border-inline-start:\s*var\(--wc-toast-stripe-width\) solid var\(--wc-toast-stripe\)/);
  assert.match(css, /border-radius:\s*var\(--wc-toast-radius\)/);
  assert.match(css, /font-size:\s*var\(--wc-toast-type-size\)/);
  assert.match(css, /max-width:\s*min\(var\(--wc-toast-max-width\),\s*calc\(100vw - 24px\)\)/);

  assert.ok(publicNotice.includes("mode === 'toast' ? ' wc-action-toast' : ''"));
  assert.ok(workspaceToast.includes('toast wc-action-toast toast-'));
  assert.doesNotMatch(publicNotice, /\.wc-public-notice\.is-toast\s*\{[\s\S]*?background:/);
  assert.match(app, /<PublicToastProvider>/);
  assert.match(app, /<ToastProvider>/);
});

test('both toast hosts stay at top-right below site navigation', () => {
  const css = read('src/styles/inner-ux.css');
  const publicHost = read('src/components/public/PublicToastProvider.tsx');
  const workspaceToast = read('src/components/Toast.tsx');

  assert.ok(publicHost.includes('className="wc-public-toast-host wc-action-toast-host"'));
  assert.ok(workspaceToast.includes('className="toast-container wc-action-toast-host wc-action-toast-host--workspace"'));
  assert.match(css, /right:\s*max\(var\(--wc-toast-edge-gap\), env\(safe-area-inset-right, 0px\)\)/);
  assert.match(css, /top:\s*max\(/);
  assert.match(css, /--wc-toast-action-band-height:\s*64px/);
  assert.match(css, /--wc-toast-action-band-height:\s*58px/);
  assert.match(css, /--wc-toast-header-height:\s*96px/);
  assert.doesNotMatch(publicHost, /position:fixed;z-index:1350|top:calc\(108px \+ 12px\)/);
  assert.doesNotMatch(css, /bottom:\s*max\(20px, env\(safe-area-inset-bottom\)\)/);
});

test('narrow mobile, notches, RTL and long text wrap instead of clipping', () => {
  const css = read('src/styles/inner-ux.css');
  assert.match(css, /@media \(max-width: 767px\)/);
  assert.match(css, /left:\s*max\(var\(--wc-toast-edge-gap\), env\(safe-area-inset-left, 0px\)\)/);
  assert.match(css, /right:\s*max\(var\(--wc-toast-edge-gap\), env\(safe-area-inset-right, 0px\)\)/);
  assert.match(css, /max-width:\s*100%/);
  assert.match(css, /overflow-wrap:\s*anywhere/);
  assert.match(css, /max-height:\s*min\(180px, 40dvh/);
  assert.match(css, /overflow-y:\s*auto/);
  assert.match(css, /@media \(max-width: 279px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /@media \(forced-colors: active\)/);
});

test('one toast replaces older toasts, without glyphs or fake sends', () => {
  const host = read('src/components/public/PublicToastProvider.tsx');
  const workspaceToast = read('src/components/Toast.tsx');
  const ctx = read('src/contexts/ToastContext.tsx');
  const customerNotices = read('src/lib/customerMenuNotices.ts');

  assert.match(host, /const \[ active, setActive \] = useState<PublicToast \| null>\( null \)/);
  assert.match(host, /setActive\( \{ id, message, tone \} \)/);
  assert.match(ctx, /setToasts\(\[\{ id, type, message \}\]\)/);
  assert.match(workspaceToast, /setToasts\(\[\{ id, type, message, duration \}\]\)/);
  assert.doesNotMatch(workspaceToast, /toast-icon|const icons =/);
  assert.match(workspaceToast, /aria-label="Dismiss notification"/);
  assert.match(workspaceToast, /role=\{toast\.type === 'error' \|\| toast\.type === 'warning' \? 'alert' : 'status'\}/);
  assert.ok(customerNotices.includes("message: 'Contribute on WhatsApp is unavailable.'"));
  assert.ok(customerNotices.includes("message: 'Sent to WhatsApp.'"));
});

test('PublicShare uses each one-at-a-time host and critical errors stay inline', () => {
  const share = read('src/components/PublicShare.tsx');
  const ctx = read('src/contexts/ToastContext.tsx');
  const orders = read('src/components/orders/OrdersPage.tsx');
  const cart = read('src/components/cart/CartPage.tsx');
  const vault = read('src/components/get/GetPage.tsx');

  assert.ok(ctx.includes('export const useOptionalToastContext'));
  assert.ok(share.includes('const workspaceToast = useOptionalToastContext()'));
  assert.ok(share.includes("else workspaceSuccess?.( 'Link copied.' )"));
  assert.ok(share.includes("else workspaceError?.( \"Couldn't copy link.\" )"));
  assert.ok(share.includes('!publicToast && !workspaceToast && ('));
  assert.ok(orders.includes("showToast( notice.message"));
  assert.ok(orders.includes('<PublicNotice mode="inline" tone="error"'));
  assert.ok(cart.includes('<PublicNotice mode="inline" tone="error"'));
  assert.ok(vault.includes('<PublicNotice mode="inline" tone="error"'));
});
