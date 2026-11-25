import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const client = readSource('src/api/domains/messaging.ts');
const handler = readSource('amplify/functions/core/messages-delete/handler.py');

test('canonical message delete IDs are namespaced for safe rollout', () => {
  assert.ok(client.includes("encodeURIComponent( '__canonical_inbox_v1__:' + messageId )"));
  // The two namespaces must remain distinct; the Python rollout tests exercise
  // valid and mismatched markers against the real handler with fake dependencies.
  assert.match(handler, /prefix = \('__canonical_contact_v1__:' if scope == 'contact'\s+else '__canonical_inbox_v1__:'\)/);
  assert.ok(handler.includes("if not message_id.startswith(prefix):"));
  assert.ok(handler.includes("message_id = message_id[len(prefix):]"));
  assert.ok(handler.includes("'MESSAGE_DELETE_MARKER_REQUIRED'"));
});

test('local inbox delete remains non-retrying and Admin MFA gated', () => {
  assert.ok(client.includes("{ method: 'DELETE' }, 0, 15000, false"));
  assert.ok(handler.includes("require_auth(event, required_role='Admin')"));
  assert.ok(handler.includes("staff.get('mfaEnrolled') is not True"));
});
