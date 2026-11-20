// Historical standby events must not permanently lock staff replies.
// Valid customer identity is still required before an actual send.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const page = readSource('src/pages/workspace/communications/index.tsx');
const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('Communications Inbox embeds canonical composer', () => {
  assert.ok(page.includes("import( '../engage/inbox' )"));
  assert.ok(page.includes("view === 'inbox'"));
});

test('historical AI, handover banner and routing prompts do not block staff', () => {
  for (const marker of [
    'ui-handover-notice', 'ui-handover-links', 'WhatsApp handover pending',
    'WhatsApp handover required', 'Check Meta Conversation Routing',
    'AI-controlled · read-only', 'agentRolloutByAccount', 'api.aiAgentApi.getSettings',
    'standbyReadOnly', 'handoverPending', 'api.getMessage( ownershipMessageId )',
  ]) assert.ok(!inbox.includes(marker), marker);
});

test('normal composer is visible on historical standby threads', () => {
  const start = inbox.indexOf('<div className="ui-reply">');
  const end = inbox.indexOf('<textarea', start);
  assert.ok(start > 0 && end > start);
  const composer = inbox.slice(start, end);
  assert.ok(composer.includes("replyChannel === 'voice' ? ("));
  assert.ok(!composer.includes('standbyReadOnly ? ('));
  assert.ok(inbox.includes('value={ replyText }'));
});

test('verified sender and saved recipient, not historical standby, gate sending', () => {
  for (const marker of [
    'threadSenderAccount', 'matchesSavedPhone', 'matchesKnownBsuid',
    'm.senderBsuid === selectedContact.bsuid', '!!replyTarget.contactId',
    'const hasVerifiedRecipient',
    "if ( replyChannel === 'whatsapp' && !hasVerifiedRecipient )",
    "disabled={ sending || ( replyChannel === 'whatsapp' && !hasVerifiedRecipient )",
  ]) assert.ok(inbox.includes(marker), marker);
  assert.ok(!inbox.includes('liveOwnership?.tracked === true'));
});

test('rich WhatsApp actions and templates unlock for verified recipient', () => {
  assert.ok(inbox.includes('disabled={ !hasVerifiedRecipient } onClick={ () => setShowTemplateSender( true ) }'));
  assert.ok(inbox.includes("{ hasVerifiedRecipient && showTemplateSender && replyChannel === 'whatsapp' && ("));
  assert.ok(inbox.includes("{ hasVerifiedRecipient && composer && replyTarget.contactId && ("));
  assert.ok(inbox.includes("{ replyChannel === 'whatsapp' && hasVerifiedRecipient && ("));
});

test('reply UI does not delete records', () => {
  assert.ok(!inbox.includes('deleteMessage('));
  assert.ok(!inbox.includes('deleteContact('));
});
