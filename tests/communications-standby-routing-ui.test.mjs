// Standby WhatsApp events indicate routing control, not an enabled AI product.
// The canonical /workspace/communications?view=inbox embeds this exact inbox.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const page = readSource('src/pages/workspace/communications/index.tsx');
const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('Communications Inbox uses the canonical message view', () => {
  assert.ok(page.includes("import( '../engage/inbox' )"));
  assert.ok(page.includes("view === 'inbox'"));
});

test('standby status reports a routing handover, never claims AI is enabled', () => {
  assert.ok(inbox.includes('WhatsApp handover pending'));
  assert.ok(inbox.includes('WhatsApp handover required'));
  assert.ok(inbox.includes('Check Meta Conversation Routing'));
  assert.ok(!inbox.includes('AI-controlled · read-only'));
  assert.ok(!inbox.includes('AI off · handover pending'));
  assert.ok(!inbox.includes('Check AI settings'));
  assert.ok(!inbox.includes('agentRolloutByAccount'));
  assert.ok(!inbox.includes('api.aiAgentApi.getSettings'));
});

test('reply block still honors the latest inbound signal on the exact WABA', () => {
  const from = inbox.indexOf('const standbyReadOnly = useMemo');
  const to = inbox.indexOf('const metaRoutingUrl = ', from);
  assert.ok(from > 0 && to > from, 'inbox owns the sender-specific guard');
  const ownership = inbox.slice(from, to);
  assert.ok(ownership.includes("( m.direction || '' ).toLowerCase() === 'inbound'"));
  assert.ok(ownership.includes('messageWabaId( m ) === senderAccount'));
  assert.ok(ownership.includes('newest?.standbySourced === true || newest?.replyAllowed === false'));
  assert.ok(inbox.includes("if ( standbyReadOnly ) { toast.error( 'WhatsApp has not handed this thread"));
});

test('Meta routing link selects the verified business for each WhatsApp number', () => {
  assert.ok(inbox.includes('conversation_routing?business_id=125951953587391'));
  assert.ok(inbox.includes('conversation_routing?business_id=382642103987922'));
});
