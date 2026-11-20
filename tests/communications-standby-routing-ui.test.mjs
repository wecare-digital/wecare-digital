// Human replies use the real sender and saved recipient. Historical standby
// webhooks and AI flags are not an independent UI-level send restriction.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const page = readSource('src/pages/workspace/communications/index.tsx');
const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('Communications Inbox embeds the canonical reply composer', () => {
  assert.ok(page.includes("import( '../engage/inbox' )"));
  assert.ok(page.includes("view === 'inbox'"));
  assert.ok(inbox.includes('<div className="ui-reply">'));
  assert.ok(inbox.includes('value={ replyText }'));
});

test('AI and standby/handover have no UI send veto', () => {
  for (const marker of [
    'standbyReadOnly', 'handoverPending', 'recipientUnresolved',
    'ownershipMessageId', 'ownershipByMessage', 'ui-handover-notice',
    'WhatsApp handover pending', 'Check Meta Conversation Routing',
    'AI-controlled · read-only', 'api.aiAgentApi.getSettings',
  ]) assert.ok(!inbox.includes(marker), marker);
});

test('saved WhatsApp identity and exact sender are still required', () => {
  const segment = inbox.slice(
    inbox.indexOf('const canReplyWhatsApp ='),
    inbox.indexOf('const handleSendRcsTemplate =')
  );
  assert.ok(segment.includes('!!replyTarget.contactId'));
  assert.ok(segment.includes('!!selectedContact'));
  assert.ok(segment.includes('selectedContact.phone || selectedContact.bsuid'));
  assert.ok(segment.includes('WABAS.some( w => w.id === sendWaba )'));
  assert.ok(segment.includes('replyTarget.waba || wabaOverridden'));
  assert.ok(inbox.includes("if ( replyChannel === 'whatsapp' && !canReplyWhatsApp )"));
  assert.ok(inbox.includes("disabled={ sending || ( replyChannel === 'whatsapp' && !canReplyWhatsApp )"));
});

test('reply tools are available for eligible saved contacts', () => {
  assert.ok(inbox.includes('disabled={ !canReplyWhatsApp } onClick={ () => setShowTemplateSender( true ) }'));
  assert.ok(inbox.includes("{ canReplyWhatsApp && showTemplateSender && replyChannel === 'whatsapp' && ("));
  assert.ok(inbox.includes("{ canReplyWhatsApp && composer && replyTarget.contactId && ("));
  assert.ok(inbox.includes("{ replyChannel === 'whatsapp' && canReplyWhatsApp && ("));
});

test('message delete is explicit and does not bypass WhatsApp send API', () => {
  assert.ok(inbox.includes('api.deleteInboxMessageRecord( id )'));
  assert.ok(inbox.includes('await confirm( {'));
  assert.ok(inbox.includes('Delete inbox message'));
  assert.ok(!inbox.includes('api.deleteContact('));
  assert.ok(inbox.includes('api.sendWhatsAppMessage( {'));
});
