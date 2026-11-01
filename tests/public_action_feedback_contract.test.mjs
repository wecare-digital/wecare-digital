/**
 * Final public action feedback policy, 1 November 2026.
 * Source-level contract: no live API, WhatsApp sends, payments or browser.
 * Run: node --test tests/public_action_feedback_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('one public text for each action outcome; only accepted WhatsApp uses Sent', () => {
  const copy = read('src/lib/publicActionNotices.ts');
  const literal = [
    "processing: 'Processing…'",
    "success: 'Done.'",
    "failure: \"Couldn't complete. Try again.\"",
    "blocked: 'This action is unavailable right now.'",
    "whatsappAccepted: 'Sent to WhatsApp.'",
    "whatsappFailed: \"Couldn't confirm. Check WhatsApp.\"",
  ];
  for (const value of literal) assert.ok(copy.includes(value), value);
  assert.match(copy, /export function publicApiFailureKind/);
  assert.match(copy, /case 429:/);
  assert.match(copy, /case 503:/);
  assert.match(copy, /return 'blocked'/);
  assert.match(copy, /return 'failure'/);
});

test('public toast host cannot show arbitrary API text or unconfirmed WhatsApp sends', () => {
  const host = read('src/components/public/PublicToastProvider.tsx');
  assert.match(host, /showToast: \( kind: PublicToastKind, options\?: PublicToastOptions \) => number/);
  assert.match(host, /type PublicToastKind = Exclude<PublicActionNoticeKind, 'whatsappFailed'>/);
  assert.match(host, /if \( String\( kind \) === 'whatsappFailed' \) return 0/);
  assert.match(host, /const message = publicActionText\( kind \)/);
  assert.match(host, /if \( !message \) return 0/);
  assert.match(host, /setActive\( \{ id, message, tone \} \)/);
  assert.doesNotMatch(host, /showToast: \( message: string/);
});

test('public action call sites send approved keys, never raw API messages', () => {
  const orders = read('src/components/orders/OrdersPage.tsx');
  const share = read('src/components/PublicShare.tsx');
  const valid = new Set(['processing', 'success', 'failure', 'blocked', 'whatsappAccepted']);
  for (const source of [orders, share]) {
    const keys = [...source.matchAll(/\bshowToast\(\s*'([^']+)'/g)].map(m => m[1]);
    assert.ok(keys.length >= 2, 'expected direct actions to reuse the public host');
    for (const key of keys) assert.ok(valid.has(key), 'unexpected public toast key: ' + key);
    assert.doesNotMatch(source, /showToast\( (?:data|response|result|notice)\.(?:status|message|error)/);
  }
  assert.ok(orders.includes("showToast( 'whatsappAccepted'"));
  assert.ok(orders.includes("showToast( 'processing'"));
  assert.ok(share.includes("showToast( 'success'"));
  assert.ok(share.includes("showToast( 'failure'"));
  assert.ok(share.includes("else workspaceSuccess?.( publicActionText( 'success' ) )"));
  assert.ok(orders.includes("setOrdersAlert( { source: 'service', message: notice.message } )"));
});

test('API failure strings are converted to approved customer text at boundaries', () => {
  const auth = read('src/pages/auth.tsx');
  const profile = read('src/components/CheckoutProfile.tsx');
  const vault = read('src/components/get/GetPage.tsx');
  assert.match(auth, /SECTION_6_MESSAGES\.find\( text => text === next\.message\.trim\(\) \)/);
  assert.doesNotMatch(auth, /setError\( next\.message \)/);
  assert.ok(auth.includes("setError( publicApiFailureText( response.status ) )"));
  assert.ok(auth.includes("setError( publicActionText( 'failure' ) )"));
  assert.ok(profile.includes("setMessage( publicActionText( 'failure' ) )"));
  assert.ok(vault.includes("setError( publicApiFailureText( result.failure.status ) )"));
  assert.ok(vault.includes("feedback( 'error', publicActionText( 'failure' ) )"));
  assert.doesNotMatch(vault, /setError\( result\.failure\.message/);
  assert.doesNotMatch(vault, /message:\s*result\.failure\.message/);
  assert.doesNotMatch(vault, /message:\s*result\.data\.message/);
  assert.doesNotMatch(vault, /err\?\.message \|\| 'Could not prepare/);
});

test('Vault HTTP 202/unconfirmed is NOT a WhatsApp send success and stays inline', () => {
  const vault = read('src/components/get/GetPage.tsx');
  assert.ok(vault.includes("result.data.outcome === 'PAYMENT_REQUEST_SENT'"));
  assert.ok(vault.includes("kind: accepted ? 'status' : 'error'"));
  assert.ok(vault.includes("publicActionText( accepted ? 'whatsappAccepted' : 'whatsappFailed' )"));
  assert.ok(vault.includes("setPaymentWaiting( current => ( { ...current, [ file.fileId ]: true } ) )"));
  assert.ok(vault.includes("role={ feedback?.kind === 'error' ? 'alert' : 'status' }"));
  assert.ok(vault.includes("feedback?.kind === 'error' && !waitingForPayment && ("));
  assert.ok(vault.includes("Payment recorded. Confirming access. Do not pay again."));
});

test('generic copy remains brief; safety-critical messages stay contextual', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  const auth = read('src/pages/auth.tsx');
  const vault = read('src/components/get/GetPage.tsx');
  const blog = read('src/components/ProductBlogPanel.tsx');
  const travel = read('src/components/ElsewhereTravelAssistant.tsx');
  const profile = read('src/components/CheckoutProfile.tsx');
  assert.ok(cart.includes('Payment was not completed. Check your orders before trying again.'));
  assert.ok(cart.includes('We could not confirm checkout. Check your orders before trying again.'));
  assert.ok(cart.includes('<PublicNotice mode="inline" tone="error"'));
  assert.ok(auth.includes('Enter the 6-digit code.'));
  assert.ok(profile.includes('Please check your delivery address.'));
  assert.ok(vault.includes('We could not confirm paid access for this file. If you already paid, do not pay again.'));
  assert.ok(blog.includes("publicActionText( 'failure' )"));
  assert.ok(blog.includes("publicActionText( 'processing' )"));
  assert.ok(travel.includes("publicActionText( 'blocked' )"));
  assert.ok(travel.includes('No booking or payment started.'));
});
