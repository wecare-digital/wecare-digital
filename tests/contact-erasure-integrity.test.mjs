// Contact deletion integrity: deletion cannot claim to erase all dependent customer data
// until the entire versioned S3/DynamoDB/Cognito graph is reconciled.
// Source-contract tests are offline and MUST NEVER mutate customer data.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const contacts = readSource('amplify/functions/core/contacts/handler.py');
const messageDelete = readSource('amplify/functions/core/messages-delete/handler.py');
const actions = readSource('src/components/ws/customers/CustomerActionsSheet.tsx');
const oldCustomers = readSource('src/pages/workspace/customers/index.tsx');
const manifest = readSource('docs/ops/contact-erasure-integrity-2026-11-04.md');

test('contact DELETE refuses incomplete erasure without mutating any customer data', () => {
  const start = contacts.indexOf('def _delete(contact_id: str, hard: bool,');
  const end = contacts.indexOf('def _lock_contact(', start);
  const source = contacts.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.ok(source.includes("'CONTACT_ERASURE_NOT_READY'"));
  assert.ok(source.includes("'archiveInstead': True"));
  assert.ok(source.includes('_locked_delete_refusal('), 'retention protection remains');
  assert.ok(source.includes('_hard_delete_refusal('), 'financial linkage remains protected');
  assert.ok(!source.includes('return _soft_delete('));
  assert.ok(!source.includes('return _hard_delete('));
  assert.ok(!contacts.includes('def _soft_delete('), 'do not resurrect partial tombstones');
  assert.ok(!contacts.includes('def _hard_delete('), 'do not resurrect incomplete best-effort cascade');
  assert.ok(!contacts.includes('def _delete_s3('), 'dangerous prefix fallback removed');
});

test('customer UIs no longer offer an incomplete deletion action', () => {
  assert.ok(actions.includes('Delete all customer data — unavailable'));
  assert.ok(actions.includes('Delete messages and media — unavailable'));
  assert.ok(actions.includes('api.archiveContact('));
  assert.ok(!actions.includes('api.softDeleteContactResult('));
  assert.ok(!actions.includes('api.deleteContactMessages('));
  assert.ok(oldCustomers.includes('Delete all data — unavailable'));
  assert.ok(!oldCustomers.includes('api.softDeleteContactResult('));
  assert.ok(oldCustomers.includes('handleArchive'));
});

test('single-message delete never guesses prefix or reports DynamoDB failure as success', () => {
  const start = messageDelete.indexOf('def _find_and_delete_s3_file(');
  const end = messageDelete.indexOf('def _handle_update(', start);
  const helper = messageDelete.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.ok(helper.includes('media_paths.canonical(stored_key)'));
  assert.ok(helper.includes('key.startswith(MESSAGE_MEDIA_PREFIXES)'));
  assert.ok(helper.includes('s3_client.head_object('));
  assert.ok(helper.includes('s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=key)'));
  assert.ok(!helper.includes('list_objects_v2'));
  assert.ok(!helper.includes('base_prefix'));
  assert.ok(!helper.includes("['Contents'][0]"));
  assert.ok(messageDelete.includes("ConditionExpression='attribute_exists(#pk)'"));
  assert.ok(messageDelete.includes("'error': 'MESSAGE_DELETE_UNCONFIRMED'"));
  assert.ok(messageDelete.includes("'mediaPermanentlyErased': False"));
  assert.ok(messageDelete.includes("'success': True"));
});

test('deletion manifest covers linked identities, payments, auth and S3 versions', () => {
  for (const marker of [
    'ContactsTable', 'IdentityClaimsTable', 'CustomerSessionsTable',
    'WhatsAppInboundTable', 'WhatsAppOutboundTable', 'MessagesTable',
    'FlowSubmissionTable', 'CrmActivities', 'DocumentTable',
    'OrderTable', 'InvoicesTable', 'PaymentAttemptsTable',
    'Cognito', 'Versioning', 'delete marker', 'ListObjectVersions',
    'audited', 'idempotent', 'retention', 'payment',
  ]) assert.ok(manifest.toLowerCase().includes(marker.toLowerCase()), marker);
});
