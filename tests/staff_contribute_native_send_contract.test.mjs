/** Static integration boundaries: no real Meta, payment, AWS or customer actions. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const file = p => readFileSync(p, 'utf8');
const checkout = file('amplify/functions/ecommerce/checkout/handler.py');
const guard = file('amplify/functions/shared/lambda_utils/ecommerce/staff_contribution.py');
const api = file('src/api/client.ts');
const staff = file('src/components/workspace/pay/ContributeStaffControls.tsx');

test('staff checkout is a separate Admin+MFA-gated HTTP route before customer auth', () => {
  const dispatcher = checkout.indexOf('if str(staff_candidate.get("action")');
  const customer = checkout.indexOf('identity, denied = customer_auth.require_customer(event)');
  assert.ok(dispatcher > 0 && customer > dispatcher);
  const piece = checkout.slice(dispatcher, customer);
  assert.match(piece, /require_auth\(event, required_role="Admin"\)/);
  assert.match(piece, /api_gateway/);
  assert.match(piece, /method != "POST"/);
  assert.match(piece, /staff_path\.endswith\("\/ecommerce\/checkout"\)/);
  assert.match(piece, /get\("role"\) != "Admin"/);
});

test('no staff-controlled amount or Meta send parameters reach the server', () => {
  const send = checkout.slice(checkout.indexOf('def _staff_contribution_send('),
                              checkout.indexOf('# ── request plumbing'));
  assert.ok(send.length > 2000);
  assert.match(send, /set\(body\) != \{"action", "contactId"\}/);
  assert.match(send, /Key=\{"id": body\["contactId"\]\}, ConsistentRead=True/);
  assert.match(send, /_native_whatsapp_identity\(/);
  assert.match(send, /sender_id = wa_payment_request\.PHONE_NUMBER_ID_1/);
  assert.match(send, /"sourceMessageId"|sender_id, ""/);
  assert.match(send, /_native_quote\(identity, lines/);
  assert.match(send, /valid_staff_contribution_snapshot/);
  assert.match(send, /_claim_wa_cart\(/);
  assert.match(send, /_take_over_settled_wa_cart\(/);
  assert.match(send, /required_staff_contribution=True/);
  assert.match(send, /_record_wa_cart\(/);
  assert.match(send, /_release_wa_cart\(/);
  for (const forbidden of ['body["amount"', 'body["phone"', 'body["template"',
      'body["product"', 'body["sender"', 'body["express"']) {
    assert.ok(!send.includes(forbidden), 'browser param could override payment: ' + forbidden);
  }
});

test('second frozen snapshot check precedes all attempt/reference reservations', () => {
  const create = checkout.slice(checkout.indexOf('def _create('), checkout.indexOf('def _status('));
  const guardAt = create.indexOf('if required_staff_contribution:');
  const reserveAt = create.indexOf('reference_id = order_keys.allocate_payment_reference(');
  const attemptAt = create.indexOf('attempt = payment_attempt.build(');
  assert.ok(guardAt > 0 && reserveAt > guardAt && attemptAt > guardAt);
  assert.match(create.slice(guardAt, reserveAt), /valid_staff_contribution_snapshot/);
  assert.match(create, /attempt\["staffContribute"\] = True/);
  assert.doesNotMatch(create, /notes\["purpose"\]\s*=\s*["']BLOG_CONTRIBUTION/);
});

test('browser performs exactly one POST and never uses automatic API retries', () => {
  const send = api.slice(api.indexOf('export async function sendStaffContributionPaymentOnce'),
                         api.indexOf('// createInvoice() removed'));
  assert.ok(send.length > 400);
  assert.match(send, /await authFetch\(/);
  assert.match(send, /action: 'staff-contribute-send', contactId/);
  assert.doesNotMatch(send, /apiCallResult|retryCount|while\s*\(|setTimeout\(/);
  assert.match(send, /NETWORK_UNCONFIRMED/);
  assert.match(send, /data\.amountPaise === 30000/);
  assert.match(staff, /api\.sendStaffContributionPaymentOnce\(selected\.id\)/);
  assert.match(staff, /setSendLocked\(true\)/);
  assert.match(staff, /approval === 'approved'/);
  assert.match(staff, /useConfirm\(\)/);
});

test('voluntary contribution does not acquire Vault fees or a file entitlement', () => {
  assert.match(guard, /STAFF_CONTRIBUTION_TOTAL_PAISE = 30000/);
  assert.match(guard, /STAFF_CONTRIBUTION_POLICY = "contribution-exempt-2026-10-30"/);
  assert.match(guard, /convenience_fee_paise != 0/);
  assert.match(guard, /convenience_gst_paise != 0/);
  assert.match(guard, /delivery\.get\("paise"\) != 0/);
  assert.match(guard, /metadata\.get\("discountPaise"\)/);
  assert.match(guard, /metadata\.get\("supplyGstPaise"\)/);
  const send = checkout.slice(checkout.indexOf('def _staff_contribution_send('),
                              checkout.indexOf('# ── request plumbing'));
  assert.doesNotMatch(send, /requestSecureFilePayment|VAULT|invoice_engine|sendWhatsAppTemplateMessage/);
});
