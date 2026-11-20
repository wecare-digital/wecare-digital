import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');
const messagingApi = readSource('src/api/domains/messaging.ts');
const sendBackend = readSource('amplify/functions/messaging/outbound-whatsapp/handler.py');

test('historic standby ownership cannot block verified manual replies in UI', () => {
  assert.ok(!inbox.includes('standbyReadOnly'));
  assert.ok(!inbox.includes('ownershipMessageId'));
  assert.ok(!inbox.includes('handoverPending'));
  assert.ok(inbox.includes('const canReplyWhatsApp ='));
  assert.ok(inbox.includes("if ( replyChannel === 'whatsapp' && !canReplyWhatsApp )"));
  assert.ok(inbox.includes('recipientBsuid: bsuid'));
});

test('sender recipient validation and Meta enforcement remain authoritative', () => {
  assert.ok(inbox.includes('WABAS.some( w => w.id === sendWaba )'));
  assert.ok(inbox.includes('replyTarget.waba || wabaOverridden'));
  assert.ok(messagingApi.includes('sendWhatsAppMessage'));
  assert.ok(sendBackend.includes("_resolve_meta_phone_id"));
  assert.ok(sendBackend.includes('contactId or recipientPhone is required'));
  assert.ok(sendBackend.includes('_marketing_consent_refusal'));
});
