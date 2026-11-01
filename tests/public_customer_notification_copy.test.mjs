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

test('Contribute refusal and uncertain WhatsApp sends use identical public failure text', () => {
  const noticeSource = read('src/lib/customerMenuNotices.ts');
  const genericFailure = '"Couldn\'t confirm. Check WhatsApp."';
  assert.ok(noticeSource.includes("'awaiting-template': {\n    message: " + genericFailure + ",\n    error: true,"));
  assert.ok(noticeSource.includes("failed: {\n    message: " + genericFailure + ",\n    error: true,"));
  assert.doesNotMatch(noticeSource, /message:\s*['"][^'"\n]*(?:template|configur|backend|Lambda|WABA|HTTP \d+|Graph API)/i);
  assert.doesNotMatch(noticeSource, /Contribute on WhatsApp is unavailable\./);
  assert.match(noticeSource, /accepted:\s*\{\s*message:\s*'Sent to WhatsApp\.'\s*,/);
});

test('blocked Contribute cannot report a successful send or show a fleeting success toast', () => {
  const actions = read('src/lib/customerMenuActions.ts');
  const orders = read('src/components/orders/OrdersPage.tsx');
  assert.match(actions, /data\.status === 'CONTRIBUTE_TEMPLATE_NOT_CONFIGURED'\s*\)\s*return \{ kind: 'awaiting-template' \}/);
  assert.match(orders, /const notice = customerMenuNotice\( kind \)/);
  assert.match(orders, /if \( notice\.error \) \{/);
  assert.match(orders, /hideToast\( inviteToastId\.current \)/);
  assert.match(orders, /setOrdersAlert\( \{ source: 'service', message: notice\.message \} \)/);
  assert.doesNotMatch(orders, /if \( kind === 'awaiting-template' \)/);
  assert.doesNotMatch(orders, /showToast\( data\.(?:status|error|message)/);
  assert.match(orders, /<PublicNotice mode="inline" tone="error" message=\{ ordersAlert\.message \}/);
});
