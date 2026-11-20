import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');
const messagingApi = readSource('src/api/domains/messaging.ts');
const messageReader = readSource('amplify/functions/core/messages-read/handler.py');

test('inbox does not wait for historical handover before verified reply', () => {
  for (const marker of [
    'const matchesSavedPhone', 'const matchesKnownBsuid',
    'const hasVerifiedRecipient', '!!threadSenderAccount',
    "if ( replyChannel === 'whatsapp' && !hasVerifiedRecipient )",
    "disabled={ sending || ( replyChannel === 'whatsapp' && !hasVerifiedRecipient )",
    'Nothing was sent.',
  ]) assert.ok(inbox.includes(marker), marker);
  for (const obsolete of [
    'ownershipMessageId', 'liveOwnership', 'handoverPending', 'standbyReadOnly',
    'recipientUnresolved', 'ui-handover-notice'
  ]) assert.ok(!inbox.includes(obsolete), obsolete);
});

test('backend ownership visibility remains read-only and historical messages are retained', () => {
  assert.ok(messagingApi.includes('threadOwnership?: { tracked: boolean'));
  assert.ok(messageReader.includes('ConsistentRead=True'));
  assert.ok(messageReader.includes('THREAD_OWNERSHIP_TABLE'));
  assert.ok(!inbox.includes('deleteMessage('));
  assert.ok(!inbox.includes('deleteContact('));
  assert.ok(inbox.includes('api.sendWhatsAppStaffReplyOnce( {'));
  assert.ok(messagingApi.includes('export async function sendWhatsAppStaffReplyOnce'));
  assert.ok(messagingApi.includes('0, 15000, false'));
});
