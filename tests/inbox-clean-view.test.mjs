// The workspace inbox always displays full stored history. Message deletion is
// a separate, confirmed Admin/MFA backend action; no view filter can hide rows.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const fresh = readSource('src/components/ws/inbox/InboxView.tsx');
const legacy = readSource('src/pages/workspace/engage/inbox/index.tsx');
const backend = readSource('amplify/functions/core/messages-delete/handler.py');
const checker = readSource('amplify/functions/shared/lambda_utils/erasure/inbox_delete.py');
const api = readSource('src/api/domains/messaging.ts');

test('both inbox screens show all messages without an old-message filter', () => {
  for (const inbox of [ fresh, legacy ]) {
    assert.ok(inbox.includes('api.listMessages( undefined, \'ALL\', 2000 )'));
    for (const old of [
      'Hide old messages', 'Show all old messages', 'todayOnly',
      'toggleTodayOnly', 'filterInboxCleanView', 'wc-inbox-today-view',
      'retainedKeys', 'setRetainedKeys', 'setTodayOnly',
    ]) assert.ok(!inbox.includes(old), old);
  }
});

test('each message has an explicit confirmed delete control', () => {
  for (const inbox of [ fresh, legacy ]) {
    assert.ok(inbox.includes('useConfirm'));
    assert.ok(inbox.includes('api.deleteInboxMessage( message.id )') ||
      inbox.includes('api.deleteInboxMessage( m.id )'));
    assert.ok(inbox.includes("'retention-hold'"));
    assert.ok(inbox.includes('Delete message'));
    assert.ok(inbox.includes('Meta/provider copies') ||
      inbox.includes('provider copies'));
  }
});

test('the actual server deletes canonical and exact matching source, not an arbitrary table', () => {
  assert.ok(backend.includes('delete_visible_message('));
  assert.ok(backend.includes("staff.get('mfaEnrolled') is not True"));
  assert.ok(checker.includes('canonical_table.delete_item('));
  assert.ok(checker.includes('source_table.delete_item('));
  assert.ok(checker.includes('contact_payment_links.has_payment_links('));
  assert.ok(checker.includes('"retention-hold"'));
  assert.ok(checker.includes('erasureComplete'));
  assert.ok(api.includes('deleteInboxMessage'));
  assert.ok(api.includes("0, 15000, false"), 'do not retry destructive sends');
});
