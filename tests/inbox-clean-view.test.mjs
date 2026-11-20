// Non-destructive inbox presentation contract, not a payment-retention proof.
// The typecheck/build and runtime review are required before release.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const filter = readSource('src/lib/inbox-clean-view.ts');
const fresh = readSource('src/components/ws/inbox/InboxView.tsx');
const legacy = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('clean view never deletes records and fails open for ambiguous conversation keys', () => {
  assert.ok(filter.includes("key === 'unknown'"));
  assert.ok(filter.includes('retainedConversationIds.has( key )'));
  assert.ok(filter.includes('financialConversations.has( key )'));
  assert.ok(filter.includes('return !Number.isFinite( timestamp ) || timestamp >= todayStartMs'));
  assert.ok(!filter.includes('delete_item'));
  assert.ok(!filter.includes('DeleteItem'));
  assert.ok(!filter.includes('expiresAt'));
});

test('both inboxes load operator hold tags and retain all-history access', () => {
  for (const inbox of [ fresh, legacy ]) {
    assert.ok(inbox.includes('api.listConversationMeta()'));
    assert.ok(inbox.includes("includes( 'retention-hold' )"));
    assert.ok(inbox.includes('filterInboxCleanView( messages'));
    assert.ok(inbox.includes('Show all old messages'));
    assert.ok(inbox.includes('not deleted'));
    assert.ok(inbox.includes("view' ) === 'today'") || inbox.includes("view === 'today'"));
    assert.ok(!filter.includes('deleteMessage('), 'clean-view filter never deletes messages');
  }
});

test('clean view is opt-in per browser, not default for every operator', () => {
  assert.ok(fresh.includes("useState( false )"));
  assert.ok(legacy.includes("useState( false )"));
  assert.ok(fresh.includes("wc-inbox-today-view"));
  assert.ok(legacy.includes("wc-inbox-today-view"));
});

test('missing retention metadata cannot hide messages or blank the inbox', () => {
  for (const inbox of [ fresh, legacy ]) {
    assert.ok(inbox.includes('const [ recordsResult, holdResult ] = await Promise.all'));
    assert.ok(inbox.includes('recordsResult.failures[ 0 ] ?? null'));
    assert.ok(inbox.includes('if ( holdResult.failures.length )'));
    assert.ok(inbox.includes('setTodayOnly( false )'));
    assert.ok(inbox.includes('setRetainedKeys( new Set() )'));
  }
});
