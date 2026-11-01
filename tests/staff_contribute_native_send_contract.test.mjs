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
  const dispatcher = checkout.indexOf('staff_action = str(staff_candidate.get("action")');
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
  assert.doesNotMatch(send, /await\s+apiCallResult\(|retryCount\s*[=+]|while\s*\(|setTimeout\(/);
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

test('production release defaults off and Admin readiness probes are side-effect-free', () => {
  const release = checkout.slice(checkout.indexOf('def _staff_contribution_release_enabled('),
                                 checkout.indexOf('def _staff_contribution_send('));
  assert.match(release, /os\.environ\.get\("STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED", ""\)/);
  assert.match(release, /def _staff_contribution_readiness\(/);
  assert.match(release, /service_pricing_native\.resolve_all\(/);
  assert.match(release, /"sendEnabled": available/);
  assert.match(release, /"amountPaise": staff_contribution\.STAFF_CONTRIBUTION_TOTAL_PAISE/);
  for (const forbidden of ['_send_order_details(', '_create(', 'payment_attempt.build(', 'allocate_payment_reference(']) {
    assert.ok(!release.includes(forbidden), 'readiness must not initiate payment: ' + forbidden);
  }
  const send = checkout.slice(checkout.indexOf('def _staff_contribution_send('),
                              checkout.indexOf('# ── request plumbing'));
  assert.match(send, /if not _staff_contribution_release_enabled\(\)/);
  const dispatcher = checkout.slice(checkout.indexOf('staff_action = str(staff_candidate.get("action")'),
                                    checkout.indexOf('identity, denied = customer_auth.require_customer(event)'));
  assert.match(dispatcher, /if staff_action == _STAFF_CONTRIBUTION_READINESS:/);
  assert.match(dispatcher, /require_auth\(event, required_role="Admin"\)/);
  assert.match(dispatcher, /_staff_contribution_readiness\(origin\)/);

  const read = api.slice(api.indexOf('export async function getStaffContributionSendReadiness'),
                         api.indexOf('export async function sendStaffContributionPaymentOnce'));
  assert.match(read, /await authFetch\(/);
  assert.match(read, /action: 'staff-contribute-readiness'/);
  assert.match(read, /row\.sendEnabled === true && row\.amountPaise === 30000/);
  assert.match(read, /row\.status === 'STAFF_CONTRIBUTE_READY'/);
  assert.doesNotMatch(read, /await\s+apiCallResult\(/);
  assert.match(staff, /backendReady === 'enabled'/);
  assert.match(staff, /api\.getStaffContributionSendReadiness\(\)/);
});

test('fraud boundary: exact price is strongly reread before reference reservation', () => {
  const check = checkout.slice(checkout.indexOf('def _staff_contribution_catalog_is_current('),
    checkout.indexOf('def _staff_contribution_readiness('));
  assert.match(check, /ConsistentRead=True/);
  assert.match(check, /valid_staff_contribution_catalog_record/);
  const start = checkout.indexOf('def _create(');
  const reserve = checkout.indexOf('reference_id = order_keys.allocate_payment_reference(', start);
  const before = checkout.slice(start, reserve);
  assert.match(before, /if required_staff_contribution:[\s\S]*_staff_contribution_catalog_is_current\(/);
  assert.ok(before.lastIndexOf('_staff_contribution_catalog_is_current(') > before.indexOf('readiness = _readiness()'));
  assert.match(checkout, /_staff_contribution_catalog_is_current\(product_id, variant_id\)/);
  assert.match(checkout, /if not _staff_contribution_catalog_is_current\(product_id, variant_id\)/);
});

test('fraud boundary: conflicting contact IDs cannot be treated as verified identity', () => {
  const start = checkout.indexOf('def _staff_contribution_send(');
  const end = checkout.indexOf('# ── request plumbing', start);
  const send = checkout.slice(start,end);
  assert.match(send, /contact_key\.assert_consistent\(contact\)/);
  assert.match(send, /contact_key\.assert_consistent\(proven\)/);
  assert.match(send, /CONTACT_IDENTITY_CONFLICT/);
  assert.match(send, /str\(contact\.get\("checkoutCustomerId"\)/);
  assert.match(send, /_native_whatsapp_identity\(/);
});

test('fraud boundary: Admin attribution comes only from verified staff session', () => {
  const start = checkout.indexOf('staff_action = str(staff_candidate.get("action")');
  const end = checkout.indexOf('# THE ONE PRE-AUTH ARM', start);
  const auth = checkout.slice(start,end);
  assert.match(auth, /require_auth\(event, required_role="Admin"\)/);
  assert.match(auth, /event\.get\("_auth"\)/);
  assert.match(auth, /"username"/);
  assert.match(auth, /hashlib\.sha256\(/);
  const create = checkout.slice(checkout.indexOf('def _create('), checkout.indexOf('def _status('));
  assert.match(create, /staff_actor_hash/);
  assert.match(create, /extra\["staffActorHash"\] = staff_actor_hash/);
  assert.match(create, /attempt\["staffActorHash"\] = staff_actor_hash/);
  assert.doesNotMatch(auth, /staff_candidate\.get\(["']staffActorHash/);
});
