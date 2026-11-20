// Staff sees an ordinary reply composer. Historical standby evidence is not AI status.
// The actual send boundary still requires verified recipient and sender ownership.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const page = readSource('src/pages/workspace/communications/index.tsx');
const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('Communications Inbox embeds the modified composer', () => {
  assert.ok(page.includes("import( '../engage/inbox' )"));
  assert.ok(page.includes("view === 'inbox'"));
});

test('no AI, handover banner or external routing prompt in the inbox', () => {
  assert.ok(!inbox.includes('ui-handover-notice'));
  assert.ok(!inbox.includes('ui-handover-links'));
  assert.ok(!inbox.includes('WhatsApp handover pending'));
  assert.ok(!inbox.includes('WhatsApp handover required'));
  assert.ok(!inbox.includes('Check Meta Conversation Routing'));
  assert.ok(!inbox.includes('AI-controlled · read-only'));
  assert.ok(!inbox.includes('agentRolloutByAccount'));
  assert.ok(!inbox.includes('api.aiAgentApi.getSettings'));
});

test('normal composer stays visible for standby history and lets staff draft', () => {
  const start = inbox.indexOf('<div className="ui-reply">');
  const end = inbox.indexOf('<textarea', start);
  assert.ok(start > 0 && end > start);
  const container = inbox.slice(start, end);
  assert.ok(container.includes("replyChannel === 'voice' ? ("));
  assert.ok(!container.includes('standbyReadOnly ? ('));
  assert.ok(inbox.includes('placeholder={ `Reply via ${chMeta( replyChannel ).label}…` }'));
  assert.ok(inbox.includes('value={ replyText }'));
});

test('unverified recipient or sender cannot be sent a real message by accident', () => {
  const start = inbox.indexOf('const latestInboundAccountMessage = useMemo');
  const end = inbox.indexOf('const standbyReadOnly = handoverPending || recipientUnresolved', start);
  assert.ok(start > 0 && end > start);
  const ownership = inbox.slice(start, end + 100);
  assert.ok(ownership.includes("( m.direction || '' ).toLowerCase() === 'inbound'"));
  assert.ok(ownership.includes('messageWabaId( m ) === senderAccount'));
  assert.ok(ownership.includes('latestInboundAccountMessage?.standbySourced === true'));
  assert.ok(ownership.includes('liveOwnership?.tracked === true'));
  assert.ok(ownership.includes('liveOwnership.owned === true'));
  assert.ok(inbox.includes("if ( replyChannel === 'whatsapp' && ( standbyReadOnly || !hasVerifiedRecipient ) )"));
  assert.ok(inbox.includes("disabled={ sending || ( replyChannel === 'whatsapp' && ( standbyReadOnly || !hasVerifiedRecipient ) )"));
  assert.ok(inbox.includes("if ( replyChannel !== 'whatsapp' || !replyText.trim() || !selected\n            || standbyReadOnly || !hasVerifiedRecipient ) return;"));
});

test('rich send actions remain blocked for a standby-only thread', () => {
  assert.ok(inbox.includes('disabled={ standbyReadOnly } onClick={ () => setShowTemplateSender( true ) }'));
  assert.ok(inbox.includes("{ !standbyReadOnly && showTemplateSender && replyChannel === 'whatsapp' && ("));
  assert.ok(inbox.includes("{ !standbyReadOnly && composer && replyTarget.contactId && ("));
  assert.ok(inbox.includes("{ replyChannel === 'whatsapp' && !standbyReadOnly && ("));
});

test('reply UI never deletes a message or contact', () => {
  assert.ok(!inbox.includes('deleteMessage('));
  assert.ok(!inbox.includes('deleteContact('));
});
