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
  assert.ok(!helper.includes('s3_client.list_objects_v2('), 'no prefix-based S3 search calls');
  assert.ok(!helper.includes('base_prefix'));
  assert.ok(!helper.includes("['Contents'][0]"));
  // Scope the assertions to the actual single-message delete path; clear-all has
  // its own separate success result and must not make these tests pass accidentally.
  const dbDeleteStart = messageDelete.indexOf('            table.delete_item(', messageDelete.indexOf('def handler('));
  const dbDeleteEnd = messageDelete.indexOf("    except ClientError as e:\\n        return cors_response(500", dbDeleteStart);
  const dbDelete = messageDelete.slice(dbDeleteStart, dbDeleteEnd);
  assert.ok(dbDeleteStart > 0 && dbDeleteEnd > dbDeleteStart);
  assert.ok(dbDelete.includes("ConditionExpression='attribute_exists(#pk)'"));
  assert.match(dbDelete, /except ClientError as exc:[\\s\\S]*?return cors_response\\(503,[\\s\\S]*?'MESSAGE_DELETE_UNCONFIRMED'/);
  assert.match(dbDelete, /except Exception:[\\s\\S]*?return cors_response\\(503,[\\s\\S]*?'MESSAGE_DELETE_UNCONFIRMED'/);
  assert.ok(dbDelete.includes("'rowDeleted': True"), 'legacy success must specify message row outcome');
  assert.ok(dbDelete.includes("'erasureComplete': False"), 'S3 object versions are not erased');
  assert.ok(dbDelete.includes("'mediaPermanentlyErased': False"));
  assert.ok(dbDelete.includes("'success': True"), 'legacy single-row API stays compatible');
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
