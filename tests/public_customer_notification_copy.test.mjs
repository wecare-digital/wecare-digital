/**
 * Customer-facing WhatsApp notice contract.
 * Run: node --test tests/public_customer_notification_copy.test.mjs
 *
 * Source-only: no WhatsApp requests, Meta calls, or payment attempts.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('Contribute refusal and uncertain WhatsApp sends use exactly one public text', () => {
  const mapping = read('src/lib/customerMenuNotices.ts');
  const vocabulary = read('src/lib/publicActionNotices.ts');
  assert.ok(vocabulary.includes('whatsappFailed: "Couldn\'t confirm. Check WhatsApp."'));
  assert.match(mapping, /blocked:\s*\{\s*message: publicActionText\( 'whatsappFailed' \),\s*error: true/);
  assert.match(mapping, /failed:\s*\{\s*message: publicActionText\( 'whatsappFailed' \),\s*error: true/);
  assert.match(mapping, /accepted:\s*\{\s*message: publicActionText\( 'whatsappAccepted' \),\s*error: false/);
  assert.match(mapping, /pending:\s*\{\s*message: publicActionText\( 'processing' \),\s*error: false/);
  assert.doesNotMatch(mapping, /message:\s*['"][^'"\n]*(?:template|configur|backend|Lambda|WABA|HTTP \d+|Graph API)/i);
  assert.doesNotMatch(mapping, /Contribute on WhatsApp is unavailable\./);
});

test('blocked Contribute never announces success, never auto-retries', () => {
  const actions = read('src/lib/customerMenuActions.ts');
  const orders = read('src/components/orders/OrdersPage.tsx');
  const provider = read('src/components/public/PublicToastProvider.tsx');

  // Current Contribute is a native payment request: acceptance is qualified by
  // the exact sender outcome, fixed amount/currency, and a payment-attempt ID.
  assert.ok(actions.includes("data.status === 'PAYMENT_REQUEST_SENT'"));
  assert.ok(actions.includes("data.amountPaise === 30000"));
  assert.ok(actions.includes("data.currency === 'INR'"));
  assert.ok(actions.includes("typeof data.paymentAttemptId === 'string'"));
  assert.ok(actions.includes("data.error === 'AMOUNT_NOT_SETTLED'"));
  assert.ok(actions.includes("data.error === 'CONTRIBUTION_TAXABLE_NOT_RELEASED'"));
  assert.ok(actions.includes("return { kind: 'blocked' }"));
  assert.match(orders, /const notice = customerMenuNotice\( kind \)/);
  assert.match(orders, /if \( notice\.error \) \{/);
  assert.match(orders, /hideToast\( inviteToastId\.current \)/);
  assert.match(orders, /setOrdersAlert\( \{ source: 'service', message: notice\.message \} \)/);
  assert.ok(orders.includes("showToast( 'whatsappAccepted'"));
  assert.ok(orders.includes("showToast( 'processing'"));
  assert.doesNotMatch(orders, /showToast\( (?:data|result|notice)\.(?:status|error|message)/);
  assert.doesNotMatch(orders, /if \( kind === 'blocked' \)/);
  assert.match(orders, /<PublicNotice mode="inline" tone="error" message=\{ ordersAlert\.message \}/);
  assert.ok(provider.includes("if ( kind === 'whatsappFailed' ) return 0;"));
});

test('Vault only reports a sent payment request on explicit sender acceptance', () => {
  const vault = read('src/components/get/GetPage.tsx');
  assert.ok(vault.includes("result.data.outcome === 'PAYMENT_REQUEST_SENT'"));
  assert.ok(vault.includes("accepted ? 'whatsappAccepted' : 'whatsappFailed'"));
  assert.ok(vault.includes("kind: accepted ? 'status' : 'error'"));
  assert.doesNotMatch(vault, /message: result\.data\.message/);
  assert.doesNotMatch(vault, /message: result\.failure\.message/);
  assert.ok(vault.includes("!waitingForPayment && ("));
});
