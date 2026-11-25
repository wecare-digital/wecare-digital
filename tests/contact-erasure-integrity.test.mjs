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
const dispatcher = readSource('amplify/functions/shared/lambda_utils/erasure/dispatch.py');
const preview = readSource('amplify/functions/shared/lambda_utils/erasure/selective_preview.py');
const livePreview = readSource('amplify/functions/shared/lambda_utils/erasure/live_preview.py');

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
  const rowDelete = single.slice(single.indexOf('def delete_visible_message('), single.indexOf('def _remove_content_fields('));
  assert.match(messageDelete, /operation = \(redact_visible_message_content if scope == 'content-only'\s+else delete_visible_message\)\s+outcome = operation\(/);
  assert.ok(messageDelete.includes("require_auth(event, required_role='Admin')"));
  assert.ok(messageDelete.includes("staff.get('mfaEnrolled') is not True"));
  assert.ok(single.includes('canonical_table.get_item('));
  assert.ok(single.includes('source_table.get_item('));
  assert.ok(single.includes('canonical_table.delete_item('));
  assert.ok(single.includes('source_table.delete_item('));
  const audit = rowDelete.indexOf('audit_id = audit(');
  const sourceWrite = rowDelete.indexOf('source_table.delete_item(');
  const canonicalWrite = rowDelete.indexOf('canonical_table.delete_item(');
  assert.ok(audit >= 0 && sourceWrite > audit && canonicalWrite > audit);
  assert.match(rowDelete.slice(audit, Math.min(sourceWrite, canonicalWrite)), /if not audit_id:\s+return _refuse\(/);
  assert.ok(single.includes('contact_payment_links.has_payment_links('));
  assert.ok(single.includes('"retention-hold"'));
  assert.ok(single.includes('MESSAGE_FINANCIAL_RETENTION'));
  assert.ok(single.includes('MESSAGE_MEDIA_REVIEW_REQUIRED'));
  assert.ok(single.includes('"erasureComplete": False'));
  assert.ok(dispatcher.includes('identityClaimsReleased'));
  assert.ok(dispatcher.includes('contactRecreatable'));
  assert.ok(!single.includes('.batch_writer('));
  assert.ok(!single.includes('DeleteObjects'));
});

// Read executable safeguards rather than archived operations prose. Synthetic
// behavior coverage also lives in test_selective_erasure_preview.py and
// test_erasure_dispatch.py.
test('the scoped preview retains protected, financial and legally locked contacts', () => {
  assert.match(livePreview, /if isinstance\(row, dict\) and "retention-hold" in/);
  assert.match(livePreview, /protected_contact_ids=protected/);
  assert.match(preview, /if cid in protected:\s+contact_results\[cid\] = RETAIN_PROTECTED/);
  assert.match(preview, /if _connected_financial_records\(.*\):\s+contact_results\[cid\] = RETAIN_FINANCIAL/);
  assert.match(preview, /contact_results\[cid\] = RETAIN_LEGAL_LOCK/);
  assert.match(preview, /parent_status = contact_results\.get\(cid\)/);
  for (const marker of [
    'PaymentsTable', 'PaymentAttemptsTable', 'InvoicesTable', 'OrderTable',
    'MessagesTable', 'WhatsAppInboundTable', 'WhatsAppOutboundTable',
  ]) assert.ok(livePreview.includes(marker), marker);
});

test('preview is never deletion approval and dispatch requires reconciled retention evidence', () => {
  assert.match(livePreview, /dependency_inventory_complete=False/);
  assert.match(preview, /or not dependency_inventory_complete\):\s+contact_results\[cid\] = REVIEW_REQUIRED/);
  assert.match(preview, /"executionAuthorized": False/);
  assert.match(dispatcher, /if not coordinator_function:\s+return _refuse\(\s*"ERASURE_COORDINATOR_UNAVAILABLE"/);
  assert.match(dispatcher, /approval_token or ""\)\s*<\s*24\):\s+return _refuse\(\s*"ERASURE_APPROVAL_REQUIRED"/);
  for (const marker of ['reconciliationComplete', 'protectedContactsVerified', 'financialEvidencePreserved']) {
    assert.ok(dispatcher.includes(`body.get("${marker}") is True`), marker);
  }
  assert.match(dispatcher, /and bool\(body.get\("auditId"\)\)\):/);
});
