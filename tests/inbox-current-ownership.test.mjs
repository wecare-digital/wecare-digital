import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');
const messagingApi = readSource('src/api/domains/messaging.ts');
const messageReader = readSource('amplify/functions/core/messages-read/handler.py');

test('standby history cannot send until current ownership and recipient are verified', () => {
  for (const marker of [
    'ownershipMessageId', 'api.getMessage( ownershipMessageId )',
    'liveOwnership?.tracked === true', 'liveOwnership.owned === true',
    'liveOwnership.idle !== true', 'hasVerifiedRecipient',
    'const recipientUnresolved = !!standbyHistory && !handoverPending',
    'const standbyReadOnly = handoverPending || recipientUnresolved',
  ]) assert.ok(inbox.includes(marker), marker);
  // The user no longer sees a large AI/routing warning. Send authorization
  // remains at the button, handler, and backend boundaries.
  assert.ok(!inbox.includes('ui-handover-notice'));
  assert.ok(!inbox.includes('WhatsApp handover pending'));
  assert.ok(inbox.includes("if ( replyChannel === 'whatsapp' && ( standbyReadOnly || !hasVerifiedRecipient ) )"));
  assert.ok(inbox.includes("disabled={ sending || ( replyChannel === 'whatsapp' && ( standbyReadOnly || !hasVerifiedRecipient ) )"));
  assert.ok(inbox.includes('Nothing was sent.'));
  assert.ok(messagingApi.includes('threadOwnership?: { tracked: boolean'));
  assert.ok(messageReader.includes('ConsistentRead=True'));
  assert.ok(messageReader.includes('THREAD_OWNERSHIP_TABLE'));
});
