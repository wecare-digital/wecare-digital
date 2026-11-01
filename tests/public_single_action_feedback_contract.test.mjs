/**
 * Public action feedback must have one toast owner, not independent success
 * labels/inline banners on the same action. Source-only safety regression.
 * No browser, customer data, sends, payments or external network.
 *
 * Run: node --test tests/public_single_action_feedback_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('Share copy has only the mounted toast, with an invariant button label', () => {
  const share = read('src/components/PublicShare.tsx');
  assert.match(share, /if \( showToast \) showToast\( 'success'/);
  assert.match(share, /else workspaceSuccess\?\.\( publicActionText\( 'success' \) \)/);
  assert.match(share, /else workspaceError\?\.\( publicActionText\( 'failure' \) \)/);
  assert.match(share, /aria-label="Copy link to this page"/);
  assert.match(share, /<span className="ps-menu-name">Copy link<\/span>/);
  assert.doesNotMatch(share, /setCopied\(|is-copied|copied \? 'Copied'|<PublicNotice/);
});

test('legacy Requests copy uses the public toast; keyboard fallback is contextual only', () => {
  const helper = read('src/lib/useCopyFeedback.ts');
  const panel = read('src/components/orders/RequestsPanel.tsx');
  assert.match(helper, /usePublicToast\(\)/);
  assert.match(helper, /showToast\( 'success'/);
  assert.doesNotMatch(helper, /liveMessage|copiedKey|successMessage|refusedMessage/);
  assert.doesNotMatch(panel, /Request ID copied|Press your copy key|copiedKey|liveMessage|rqp-live/);
  assert.match(panel, /Selected\. Copy with keyboard\./);
  assert.match(panel, /aria-describedby/);
});

test('product checkout uses the common notice surface without hiding no-charge advice', () => {
  const buy = read('src/components/ProductBuyBox.tsx');
  assert.match(buy, /<PublicNotice mode="inline" tone="error" message=\{ error \} \/>/);
  assert.match(buy, /No charge made/);
  assert.doesNotMatch(buy, /className="pbb-error"|\.pbb-error/);
});

test('there is no unused second local Workspace toast state manager', () => {
  const toast = read('src/components/Toast.tsx');
  const ctx = read('src/contexts/ToastContext.tsx');
  assert.doesNotMatch(toast, /export const useToast =/);
  assert.match(ctx, /setToasts\(\[\{ id, type, message \}\]\)/);
});

test('payment, authentication, Vault and copy refusal safeguards remain contextual', () => {
  const orders = read('src/components/orders/OrdersPage.tsx');
  const cart = read('src/components/cart/CartPage.tsx');
  const auth = read('src/pages/auth.tsx');
  const vault = read('src/components/get/GetPage.tsx');
  assert.match(orders, /Selected\. Copy with keyboard\./);
  assert.match(cart, /Payment was not completed\. Check your orders before trying again\./);
  assert.match(auth, /Enter the 6-digit code\./);
  assert.match(vault, /Do not pay again\./);
  assert.match(vault, /PAYMENT_REQUEST_SENT/);
  assert.match(vault, /PAYMENT_REQUEST_UNCONFIRMED/);
});
