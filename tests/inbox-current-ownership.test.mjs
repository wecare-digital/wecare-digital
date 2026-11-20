import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');
const messagingApi = readSource('src/api/domains/messaging.ts');
const messageReader = readSource('amplify/functions/core/messages-read/handler.py');

test('standby badge is history, reply requires current ownership and a verified recipient', () => {
  for (const marker of [
    'ownershipMessageId', 'api.getMessage( ownershipMessageId )',
    'liveOwnership?.tracked === true', 'liveOwnership.owned === true',
    'liveOwnership.idle !== true', 'hasVerifiedRecipient',
    'const recipientUnresolved = !!standbyHistory && !handoverPending',
    'const standbyReadOnly = handoverPending || recipientUnresolved',
  ]) assert.ok(inbox.includes(marker), marker);
  assert.ok(inbox.includes('WhatsApp has not handed this thread to our inbox'));
  assert.ok(inbox.includes('Verify and link this customer'));
  assert.ok(messagingApi.includes('threadOwnership?: { tracked: boolean'));
  assert.ok(messageReader.includes('ConsistentRead=True'));
  assert.ok(messageReader.includes('THREAD_OWNERSHIP_TABLE'));
});
