/**
 * Customer-facing copy contract.
 * Run: node --test tests/public_customer_notification_copy.test.mjs
 *
 * Source-only: no WhatsApp requests, Meta calls or payment attempts.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('public Contribute notice never exposes template/configuration internals', () => {
  const noticeSource = read('src/lib/customerMenuNotices.ts');
  const expected = "'awaiting-template': {\n    message: 'Contribute on WhatsApp is unavailable.'";
  assert.ok(noticeSource.includes(expected), 'show concise, user-safe unavailable text');
  assert.doesNotMatch(noticeSource, /message:\s*['"][^'"\n]*(?:template|configur|backend|Lambda|WABA|HTTP \d+|Graph API)/i);
  assert.match(noticeSource, /accepted:\s*\{\s*message:\s*'Sent to WhatsApp\.'\s*,/);
  assert.match(noticeSource, /failed:\s*\{\s*message:\s*"Couldn't confirm\. Check WhatsApp\."\s*,/);
});

test('an unavailable Contribute template never presents WhatsApp acceptance', () => {
  const actions = read('src/lib/customerMenuActions.ts');
  const orders = read('src/components/orders/OrdersPage.tsx');
  assert.match(actions, /data\.status === 'CONTRIBUTE_TEMPLATE_NOT_CONFIGURED'\s*\)\s*return \{ kind: 'awaiting-template' \}/);
  assert.match(orders, /const notice = customerMenuNotice\( kind \)/);
  assert.match(orders, /if \( kind === 'awaiting-template' \)\s*\{\s*hideToast/);
  assert.match(orders, /showToast\( notice\.message/);
  assert.doesNotMatch(orders, /showToast\( data\.(?:status|error|message)/);
});
