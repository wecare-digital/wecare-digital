import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const client = readSource('src/api/domains/messaging.ts');
const inbox = readSource('src/pages/workspace/engage/inbox/index.tsx');

test('contact delete client uses the contact marker, scope=contact and no retries', () => {
  assert.ok(client.includes("'__canonical_contact_v1__:' + contactId"));
  assert.ok(client.includes('?scope=contact'));
  assert.ok(client.includes('{ method: \'DELETE\' }, 0, 30000, false'));
});

test('inbox exposes Delete conversation and contact and maps refusal codes', () => {
  assert.ok(inbox.includes('api.deleteInboxContactConversation( contactId )'));
  assert.ok(inbox.includes('title="Delete conversation and contact"'));
  for (const code of ['CONTACT_DELETE_VERIFIED_CUSTOMER', 'CONTACT_DELETE_FINANCIAL_RETENTION', 'CONTACT_DELETE_RETENTION_HOLD', 'CONTACT_DELETE_INCOMPLETE'])
    assert.ok(inbox.includes(code), code);
});
