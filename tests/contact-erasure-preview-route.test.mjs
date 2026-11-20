// A PREVIEW is not DELETE. It uses staff Admin MFA and returns aggregate-only
// evidence from the full currently selected financial/message sources.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const contacts = readSource('amplify/functions/core/contacts/handler.py');
const preview = readSource('amplify/functions/shared/lambda_utils/erasure/live_preview.py');

test('contacts GET exposes read-only preview only for Admin with enrolled MFA', () => {
  assert.ok(contacts.includes("if method == 'GET' and query_params.get('erasurePreview') == '1':"));
  const start = contacts.indexOf("if method == 'GET' and query_params.get('erasurePreview')");
  const end = contacts.indexOf("# GET [retired public path]?consent=", start);
  const path = contacts.slice(start, end);
  assert.ok(path.includes("require_auth(event, required_role='Admin')"));
  assert.ok(path.includes("staff.get('role') != 'Admin'"));
  assert.ok(path.includes("staff.get('mfaEnrolled') is not True"));
  assert.ok(path.includes("required_protected_contacts=2"));
  assert.ok(path.includes("errorCode': 'ERASURE_PREVIEW_UNAVAILABLE'"));
  assert.ok(!path.includes('.delete_item('));
  assert.ok(!path.includes('.update_item('));
  assert.ok(!path.includes('.put_item('));
});

test('preview inventories all payment evidence and three message tables', () => {
  for (const marker of [
    "MessagesTable", "WhatsAppInboundTable", "WhatsAppOutboundTable",
    "PaymentsTable", "PaymentAttemptsTable", "InvoicesTable", "OrderTable",
    "ContactsTable", "ConversationMetaTable",
  ]) assert.ok(contacts.includes(marker), marker);

  assert.ok(preview.includes('ConsistentRead'));
  assert.ok(preview.includes('dependency_inventory_complete=False'));
  assert.ok(preview.includes('"retention-hold"'));
  assert.ok(preview.includes('"eligibleForExecution": 0'));
  assert.ok(preview.includes('"readOnly": True'));
});

test('direct DELETE delegates to a separate approved coordinator', () => {
  assert.ok(!contacts.includes('CONTACT_ERASURE_NOT_READY'));
  assert.ok(contacts.includes('dispatch_approved_erasure('));
  assert.ok(!preview.includes('.delete_item('));
  assert.ok(!preview.includes('.batch_writer('));
  assert.ok(!preview.includes('.update_item('));
});
