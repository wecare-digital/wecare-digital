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
const manifest = readSource('docs/ops/scoped-whatsapp-contact-payment-retention-2026-11-20.md');

test('contact DELETE delegates only approved erasure without direct destructive writes', () => {
  const start = contacts.indexOf('def _delete(contact_id: str, hard: bool,');
  const end = contacts.indexOf('def _lock_contact(', start);
  const source = contacts.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.ok(source.includes('dispatch_approved_erasure('));
  assert.ok(source.includes("os.environ.get('ERASURE_COORDINATOR_FUNCTION'"));
  assert.ok(source.includes("staff.get('mfaEnrolled') is not True"));
  assert.ok(source.includes("'archiveInstead': True"));
  assert.ok(source.includes('_locked_delete_refusal('), 'retention protection remains');
  assert.ok(source.includes('_hard_delete_refusal('), 'financial linkage remains protected');
  assert.ok(!source.includes('return _soft_delete('));
  assert.ok(!source.includes('return _hard_delete('));
  assert.ok(!contacts.includes('def _soft_delete('), 'do not resurrect partial tombstones');
  assert.ok(!contacts.includes('def _hard_delete('), 'do not resurrect incomplete best-effort cascade');
  assert.ok(!contacts.includes('def _delete_s3('), 'dangerous prefix fallback removed');
});

test('customer actions allow message management and an approved erasure request', () => {
  assert.ok(actions.includes('View and delete messages'));
  assert.ok(actions.includes('Delete contact and release identity'));
  assert.ok(actions.includes('api.requestApprovedContactErasure('));
  assert.ok(actions.includes('result.data.erasureComplete'));
  assert.ok(actions.includes('result.data.identityClaimsReleased === true'));
  assert.ok(actions.includes('result.data.contactRecreatable === true'));
  assert.ok(actions.includes('useConfirm()'));
  assert.ok(!actions.includes('api.softDeleteContactResult('));
  assert.ok(oldCustomers.includes('handleArchive'));
});

test('single-message deletion is canonical, audit-first, and retains financial/media evidence', () => {
  const single = readSource('amplify/functions/shared/lambda_utils/erasure/inbox_delete.py');
  const sharedDispatcher = readSource('amplify/functions/shared/lambda_utils/erasure/dispatch.py');
  assert.ok(messageDelete.includes('delete_visible_message('));
  assert.ok(messageDelete.includes("require_auth(event, required_role='Admin')"));
  assert.ok(messageDelete.includes("staff.get('mfaEnrolled') is not True"));
  assert.ok(single.includes('canonical_table.get_item('));
  assert.ok(single.includes('source_table.get_item('));
  assert.ok(single.includes('canonical_table.delete_item('));
  assert.ok(single.includes('source_table.delete_item('));
  assert.ok(single.includes('audit_id = audit('));
  assert.ok(single.includes('contact_payment_links.has_payment_links('));
  assert.ok(single.includes('"retention-hold"'));
  assert.ok(single.includes('MESSAGE_FINANCIAL_RETENTION'));
  assert.ok(single.includes('MESSAGE_MEDIA_REVIEW_REQUIRED'));
  assert.ok(single.includes('"erasureComplete": False'));
  assert.ok(sharedDispatcher.includes('identityClaimsReleased'));
  assert.ok(sharedDispatcher.includes('contactRecreatable'));
  assert.ok(!single.includes('.batch_writer('));
  assert.ok(!single.includes('DeleteObjects'));
});

test('active scoped policy protects exact retained contacts, transaction evidence and provider copies', () => {
  for (const marker of [
    'ContactsTable', 'canonical', 'BSUID', 'same-name', 'Razorpay',
    'payment attempts', 'captured payments', 'refunds', 'invoices',
    'payment requests', 'webhook evidence', 'reconciliation',
    'Transaction-related communications', 'MessagesTable', 'WhatsApp',
    'S3 versions', 'Meta WhatsApp', 'backups', 'exports',
  ]) assert.ok(manifest.toLowerCase().includes(marker.toLowerCase()), marker);
});

test('scoped deletion must respect locked identities, operator approval and TTL evidence retention', () => {
  for (const marker of [
    'ERASURE_COORDINATOR_UNAVAILABLE', 'legal/financial retention checks',
    'do not bypass locks', 'reviewed retention/legal decision',
    'operator approval with MFA', 'audited', 'resumable deletion',
    'reconciliation', 'REVIEW_REQUIRED', 'idempotency',
    'TTL is **enabled**', 'expiresAt', 'approved non-expiring evidence store',
    'do not globally disable chat retention limits',
  ]) assert.ok(manifest.toLowerCase().includes(marker.toLowerCase()), marker);
  assert.match(manifest, /bulk delete-all-except-one/);
  assert.match(manifest, /This document alone triggers no mutation or rollout/);
  assert.ok(contacts.includes('dispatch_approved_erasure('), 'server delegates to independent coordinator');
});
