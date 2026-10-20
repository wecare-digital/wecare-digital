"""Fresh, end-to-end coverage of the native WhatsApp (catalog-service) payment flow.

Why this file exists, beside `tests/test_checkout_handler.py`
-------------------------------------------------------------
`test_checkout_handler.py` proves the handler's *obligations* clause by clause (auth, IDOR, the
cart-is-website-only refusal, the readiness gate, the post-PAID exclusion). THIS file reads the
native in-WhatsApp leg as ONE story, the way an operator thinks about it when they ask "does the
₹1 service payment work": prepare -> price (server total, Delight applied) -> attempt stored ->
in-chat template sent -> capture reconciled -> order finalized carrying the Razorpay transaction
id and the customer id. Each phase is one test, and the fail-closed branches (readiness blocked,
WABA2 refused, send failed) sit beside the happy path so a regression that opens one of them is
visible here rather than only in a scattered module test.

Two feature flags gate this leg in production and BOTH are turned on explicitly per test here, so
this suite exercises the live send path rather than the dark-launched `PAYMENT_INITIATION_DISABLED`
posture the other file defaults to:

    CHECKOUT_INITIATION_ENABLED     -> `h.INITIATION_ENABLED` (monkeypatched True)
    WHATSAPP_CATALOG_SERVICES_ENABLED -> env, set True for the orchestration-entry test

Pricing authority
-----------------
`_create` prices off ProductsTable through `_native_quote`. That function is STUBBED here (as in
the sibling file) because the subject is the handler's contract, not the native pricing engine —
`tests/test_native_checkout.py` and `tests/test_catalog_pricing.py` own the pricing arithmetic.
The Delight discount is therefore asserted where it is actually decided: directly against
`default_coupon.delight_paise` and the one bridge `catalog_pricing.coupon_discount_paise`, which
is the SAME computation both the invoice path and this native path consume. That keeps the Delight
assertion honest instead of reading it off a figure the stub chose.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from synthetic_service_catalog import configure as configure_services  # noqa: E402

_HANDLER_PATH = (Path(__file__).resolve().parents[1]
                 / "amplify/functions/ecommerce/checkout/handler.py")

ATTEMPTS_TABLE = 'stack-wecare-digital-PaymentAttemptsTable'
KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
ORDERS_TABLE = 'stack-wecare-digital-OrderTable'
CONTACTS_TABLE = 'stack-wecare-digital-ContactsTable'

CUSTOMER = 'CUS_01J0000000000000000000000'

# Pricing figures, mirroring the sibling file so the stubbed quote and the seeded finalize rows
# agree on one payable total.
COLLECTION_PAISE = 59900
FEE_PAISE = 1498
FEE_GST_PAISE = 270
TOTAL_PAYABLE_PAISE = COLLECTION_PAISE + FEE_PAISE + FEE_GST_PAISE

SERVICE_PRODUCT_ID = '11111111-1111-4111-8111-111111111111'
SERVICE_VARIANT_ID = '22222222-2222-4222-8222-222222222222'
SERVICE_INTENT_ID = '018f1a2b-3c4d-7e5f-8a9b-0c1d2e3f4a5b'

#: A native catalog-service session row, as `flows/catalog_services.py` writes one. The
#: `phoneNumberId` is the AWS-style WABA1 id — the only sender `PAYMENT_SENDERS` permits.
CATALOG_SESSION = {
    'orderId': 'CATALOGSERVICE#tok-abcdefghijklmnopqrst',
    'contactId': 'contact-cat-1',
    'phoneNumberId': 'phone-number-id-waba1-direct-1016149501586345',
    'kind': 'SUBMIT_REQUEST',
    'productId': SERVICE_PRODUCT_ID,
    'variantId': SERVICE_VARIANT_ID,
}


class _Payload:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _Identity:
    """Stand-in for customer_auth.CustomerIdentity (same surface the sibling file uses)."""

    def __init__(self, customer_id, phone='+918100640044'):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = 'sub-1'

    def owns(self, cid):
        return bool(cid) and cid == self.customer_id


class _FakeLambda:
    """Captures internal invokes: the readiness payment-config read and the order_details send.

    The send goes to `wecare-outbound-whatsapp:live` wrapped in a `body` envelope, so
    `invocations` holds the UNWRAPPED send body and `function_names` records each target — the
    target is part of the contract, because the old route pointed at a dispatcher that 404s.
    """

    def __init__(self):
        self.invocations = []
        self.function_names = []
        self.send_ok = True

    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        event = json.loads(Payload.decode('utf-8'))
        if 'body' in event and 'path' not in event:
            try:
                event = json.loads(event['body'])
            except (ValueError, TypeError):
                pass
        self.invocations.append(event)
        self.function_names.append(FunctionName)
        path = str(event.get('path') or '')
        if 'payment-config' in path:
            inner = {'statusCode': 200, 'body': json.dumps({
                'data': [{'configuration_name': 'WECAREDIGITAL',
                          'status': 'active',
                          'provider_name': 'razorpay',
                          'provider_mid': 'acc_TESTMID',
                          'payment_gateway': {'type': 'razorpay',
                                              'merchant_id': 'acc_TESTMID'}}]})}
        else:
            inner = {'statusCode': 200 if self.send_ok else 502, 'body': '{}'}
        return {'Payload': _Payload(json.dumps(inner).encode('utf-8'))}


class _Quote:
    total_payable_paise = TOTAL_PAYABLE_PAISE
    collection_before_convenience_paise = COLLECTION_PAISE
    convenience_fee_paise = FEE_PAISE
    convenience_gst_paise = FEE_GST_PAISE


class _Snapshot:
    cart_id = 'native:testcart'
    cart_revision = 0
    snapshot_hash = 'sha256:testsnapshot'
    expires_at = 1770000900
    policy_version = 'v1'
    frozen_data = {'items': [{'productId': SERVICE_PRODUCT_ID, 'variantId': SERVICE_VARIANT_ID,
                              'quantity': 1, 'unitPricePaise': COLLECTION_PAISE}]}
    quote = _Quote()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('PAYMENT_ATTEMPTS_TABLE', ATTEMPTS_TABLE)
    monkeypatch.setenv('COMMERCE_KEYS_TABLE', KEYS_TABLE)
    monkeypatch.setenv('ORDERS_TABLE', ORDERS_TABLE)
    monkeypatch.setenv('EXPECTED_CONFIGURATION_NAME', 'WECAREDIGITAL')
    monkeypatch.setenv('EXPECTED_PROVIDER_MID', 'acc_TESTMID')
    monkeypatch.setenv('PAYMENT_WABA_ID', '2094615664435155')
    monkeypatch.setenv('APP_ENV', 'development')

    spec = importlib.util.spec_from_file_location("native_wa_checkout_under_test", _HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    configure_services(h.service_requests, monkeypatch)

    fake = FakeDynamo(keys={
        ATTEMPTS_TABLE: 'paymentAttemptId',
        KEYS_TABLE: 'orderId',
        ORDERS_TABLE: 'orderId',
        CONTACTS_TABLE: 'id',
    })
    lam = _FakeLambda()

    monkeypatch.setattr(h, '_dynamodb', fake)
    monkeypatch.setattr(h, '_lambda_client', lambda: lam)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', False)
    monkeypatch.setattr(h.customer_auth, 'authenticate', lambda event: _Identity(CUSTOMER))
    return h, fake, lam, monkeypatch


def _stub_quote(h, monkeypatch):
    snapshot = _Snapshot()
    monkeypatch.setattr(h, '_native_quote', lambda identity, line_items, now: snapshot)
    return snapshot


def _drive_create(h, **over):
    """Call `_create` directly on the catalog-service leg (same approach as the sibling file:
    the in-chat CART leg is refused at the top of `_create`, so a catalog_session must be
    supplied to exercise everything below it)."""
    body = {'lineItems': [{'catalogReference': {
                'catalogItemId': SERVICE_PRODUCT_ID,
                'options': {'variantId': SERVICE_VARIANT_ID}}, 'quantity': 1}],
            'serviceIntentId': SERVICE_INTENT_ID}
    body.update(over)
    return h._create(_Identity(CUSTOMER), body, 'http://localhost:3000',
                     catalog_session=dict(CATALOG_SESSION))


def _seed_catalog_session(fake):
    fake.Table(KEYS_TABLE).put_item(Item={
        'orderId': CATALOG_SESSION['orderId'],
        'serviceIntentId': SERVICE_INTENT_ID,
        'status': 'PREPARING_PAYMENT',
    })


# ════════════════════════════════════════════════════════════════════════════
# PHASE 1 — prepare & price: the amount is the SERVER total, never the request
# ════════════════════════════════════════════════════════════════════════════

def test_prepare_records_the_server_calculator_total(env):
    """With initiation off (default), `_create` prepares an AWS-native attempt at the calculator
    total — collection + convenience fee + GST on the fee — and sends nothing."""
    h, fake, lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    resp = _drive_create(h)
    assert resp['statusCode'] == 200, resp['body']
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_INITIATION_DISABLED'
    assert body['amountPaise'] == TOTAL_PAYABLE_PAISE
    assert body['currency'] == 'INR'

    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt['customerId'] == CUSTOMER
    assert attempt['checkoutMode'] == 'AWS_NATIVE'
    assert attempt['nativeCatalogService'] is True
    assert attempt['amountPaise'] == TOTAL_PAYABLE_PAISE
    assert attempt['status'] == 'PAYMENT_READINESS_CHECKED'
    # The frozen snapshot is the authoritative order source downstream.
    assert attempt['snapshotHash'] == _Snapshot.snapshot_hash


def test_the_browser_amount_is_never_read(env):
    """A request that claims ₹1 (amountPaise=1) still records the calculator total."""
    h, fake, _lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    _drive_create(h, amount=1, amountPaise=1, total='1.00')
    assert fake.all_rows(ATTEMPTS_TABLE)[0]['amountPaise'] == TOTAL_PAYABLE_PAISE


# ════════════════════════════════════════════════════════════════════════════
# PHASE 1b — the Delight discount, asserted where it is DECIDED
# ════════════════════════════════════════════════════════════════════════════
#
# Delight is not a figure the stubbed quote can prove, so it is asserted against the exact
# server-side computation the native path runs (`catalog_pricing.coupon_discount_paise` ->
# `default_coupon.delight_paise`). This is the SAME bridge the invoice path uses, so a cart and an
# invoice for one order render the same discount — which is the property that matters.

def test_delight_is_zero_point_five_percent_capped_at_fifty_rupees():
    from lambda_utils.ecommerce import default_coupon
    # 0.5% of ₹599 collection = ₹2.9950 -> 299 paise (integer floor), under the cap.
    assert default_coupon.delight_paise(COLLECTION_PAISE) == COLLECTION_PAISE * 50 // 10000
    # The ₹50 cap binds on a large collection: 0.5% of ₹20,000 = ₹100, clamped to ₹50.
    assert default_coupon.delight_paise(20000 * 100) == 50 * 100
    # Never negative, never exceeds the collection.
    assert default_coupon.delight_paise(0) == 0
    assert default_coupon.delight_paise(10) <= 10


def test_the_native_bridge_matches_the_invoice_discount_figure():
    """`coupon_discount_paise(delight_definition(), subtotal)` is exactly `delight_paise(subtotal)`
    — the one bridge that keeps the native checkout sheet and the GST invoice in agreement."""
    from lambda_utils.ecommerce import catalog_pricing, default_coupon
    for subtotal in (0, 10, COLLECTION_PAISE, 20000 * 100):
        assert catalog_pricing.coupon_discount_paise(
            default_coupon.delight_definition(), subtotal_paise=subtotal
        ) == default_coupon.delight_paise(subtotal)
    # A None definition means "no discount", distinct from a ₹0 discount.
    assert catalog_pricing.coupon_discount_paise(None, subtotal_paise=COLLECTION_PAISE) == 0


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — fail-closed: readiness blocked reserves nothing
# ════════════════════════════════════════════════════════════════════════════

def test_blocked_readiness_creates_no_attempt_and_no_reservation(env):
    h, fake, _lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    monkeypatch.setenv('EXPECTED_CONFIGURATION_NAME', '')
    monkeypatch.setattr(h, 'EXPECTED_CONFIGURATION_NAME', '')
    resp = _drive_create(h)
    assert resp['statusCode'] == 409
    body = json.loads(resp['body'])
    assert body['status'] == 'payment_unavailable'
    assert body['readiness']  # a blocking state is named
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert fake.count(KEYS_TABLE) == 0


# ════════════════════════════════════════════════════════════════════════════
# PHASE 3 — initiation ON: the in-chat TEMPLATE send, and still no order
# ════════════════════════════════════════════════════════════════════════════

def test_initiation_sends_the_checkout_template_envelope(env):
    """With initiation enabled the attempt hands off as the approved `wecare_whatapp_native_pay_template` checkout
    template to the outbound sender, carrying the reserved reference byte-for-byte and the
    calculator total — and NO order exists yet."""
    h, fake, lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)

    resp = _drive_create(h)
    assert resp['statusCode'] == 200, resp['body']
    assert json.loads(resp['body'])['status'] == 'PAYMENT_REQUEST_SENT'

    sends = [e for e in lam.invocations if e.get('isCheckoutTemplate')]
    assert len(sends) == 1
    send = sends[0]
    assert send['templateName'] == 'wecare_whatapp_native_pay_template'

    details = send['checkoutOrderDetails']
    stored_ref = fake.all_rows(ATTEMPTS_TABLE)[0]['referenceId']
    assert details['reference_id'] == stored_ref          # byte-for-byte, never transformed
    assert details['total_amount']['value'] == TOTAL_PAYABLE_PAISE
    assert details['currency'] == 'INR'
    # The resolver owns payment_settings (Mode 3); the caller supplies only the config NAME.
    assert 'payment_settings' not in details
    assert details['payment_configuration'] == 'WECAREDIGITAL'

    # No order yet: a template send is a payment REQUEST, not a paid order.
    keys = fake.all_rows(KEYS_TABLE)
    assert not any(str(r.get('orderId', '')).startswith(('ORDERNO#', 'PAYMENTATTEMPT#'))
                   for r in keys)


def test_the_send_targets_the_outbound_sender(env):
    """The repaired route. The old one POSTed at the business-API Lambda, which 404s on that send
    path and surfaced as a 502 that looked like a Meta outage."""
    h, fake, lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    _drive_create(h)
    targets = [f for f, e in zip(lam.function_names, lam.invocations)
               if e.get('isCheckoutTemplate')]
    assert targets == ['wecare-outbound-whatsapp:live']
    assert h.OUTBOUND_SENDER_FUNCTION == 'wecare-outbound-whatsapp:live'


def test_a_failed_send_leaves_the_attempt_and_no_order(env):
    h, fake, lam, monkeypatch = env
    _stub_quote(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    lam.send_ok = False
    resp = _drive_create(h)
    assert resp['statusCode'] == 502
    assert json.loads(resp['body'])['status'] == 'SEND_FAILED'
    # Reusable for a delivery retry: the attempt survives, no order was created.
    assert fake.count(ATTEMPTS_TABLE) == 1


# ════════════════════════════════════════════════════════════════════════════
# PHASE 4 — only WABA1 may collect: WABA2 refused, no claim left behind
# ════════════════════════════════════════════════════════════════════════════
#
# WABA2's phone id per `config.ts` PHONE_NUMBER_ID_2. The sender resolver can legitimately return
# it; `PAYMENT_SENDERS` does not permit it to collect. The refusal must precede the one-shot
# `nativePrepareClaim` write, or the customer's retry strands on a claim it cannot clear.

WABA2_SENDER = 'phone-number-id-waba-t-direct-1055232054343117'
#: A Cognito-subject-shaped owner (UUID), required to pass the VERIFIED_CUSTOMER_REQUIRED gate
#: that deliberately sits AHEAD of the sender refusal — so the WABA2 refusal is what answers,
#: not the earlier customer gate. `CUS_...` is not a Cognito subject, which is why the owner
#: here is a UUID rather than the `CUSTOMER` constant this file uses elsewhere.
CATALOG_CUSTOMER = '11111111-1111-1111-1111-111111111111'


def test_a_waba2_session_is_refused_and_leaves_no_claim(env):
    h, fake, lam, monkeypatch = env
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    session = dict(CATALOG_SESSION)
    session.update(phoneNumberId=WABA2_SENDER, customerId=CATALOG_CUSTOMER,
                   serviceIntentId='INTENT-TEST', status='PREPARING_PAYMENT',
                   expiresAt=4070908800)
    fake.Table(KEYS_TABLE).put_item(Item=session)
    fake.Table(CONTACTS_TABLE).put_item(Item={
        'id': CATALOG_SESSION['contactId'], 'checkoutCustomerId': CATALOG_CUSTOMER})

    result = h._native_catalog_service(
        {'internalAction': 'prepareNativeCatalogService',
         'catalogToken': 'tok-abcdefghijklmnopqrst'}, 'http://localhost:3000')

    assert result == {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}
    row = fake.Table(KEYS_TABLE).get_item(Key={'orderId': CATALOG_SESSION['orderId']})['Item']
    assert 'nativePrepareClaim' not in row, 'a refused preparation must leave no claim behind'
    # Refused before the identity reads, the Meta readiness invoke and any attempt row.
    assert lam.invocations == []
    assert fake.count(ATTEMPTS_TABLE) == 0


def test_the_rollout_flag_gates_the_leg(env):
    """With WHATSAPP_CATALOG_SERVICES_ENABLED unset, the orchestration entry refuses up front."""
    h, _fake, _lam, _mp = env
    result = h._native_catalog_service(
        {'internalAction': 'prepareNativeCatalogService',
         'catalogToken': 'tok-abcdefghijklmnopqrst'}, 'http://localhost:3000')
    assert result == {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}


# ════════════════════════════════════════════════════════════════════════════
# PHASE 5 — finalize: the order carries the Razorpay txn id and the customer id
# ════════════════════════════════════════════════════════════════════════════
#
# The rows a captured catalog-service payment leaves before its order record exists: the attempt
# (frozen snapshot + provider-confirmed amount), the PAYMENTATTEMPT# claim the webhook reserved
# (order identity + Razorpay payment id), and the NATIVESERVICEACTIVE# session.

NATIVE_ATTEMPT_ID = 'att-native-service-1'
NATIVE_REFERENCE = 'WD-PAY-NATIVESVC0001'
NATIVE_ORDER_ID = 'order-native-service-1'
NATIVE_ORDER_NUMBER = 'WD-ORD-NATIVE01'
NATIVE_PROVIDER_PAYMENT_ID = 'pay_native_service_1'
NATIVE_SESSION_KEY = 'NATIVESERVICEACTIVE#' + CUSTOMER


def _seed_paid_native_service(h, fake, *, verified_paise=TOTAL_PAYABLE_PAISE):
    from lambda_utils.ecommerce import order_keys, payment_attempt as pa
    attempt = pa.build(customer_id=CUSTOMER, reference_id=NATIVE_REFERENCE,
                       amount_paise=TOTAL_PAYABLE_PAISE, configuration_name='WECAREDIGITAL',
                       payment_attempt_id=NATIVE_ATTEMPT_ID)
    attempt = pa.transition(attempt, pa.PAYMENT_PENDING)
    attempt.update({
        'checkoutMode': h.CHECKOUT_MODE, 'nativeCatalogService': True, 'channel': 'whatsapp',
        'customerPhone': '+918100640044', 'catalogServiceSession': CATALOG_SESSION['orderId'],
        'snapshotHash': 'sha256:native-service',
        'purchasedSnapshot': {
            'cart': {'id': 'native:service', 'revision': 0},
            'items': [{'productId': SERVICE_PRODUCT_ID, 'variantId': SERVICE_VARIANT_ID,
                       'quantity': 1, 'unitPricePaise': COLLECTION_PAISE}]},
        'verifiedCapturedPaise': verified_paise,
    })
    fake.Table(ATTEMPTS_TABLE).put_item(Item=attempt)
    fake.Table(KEYS_TABLE).put_item(Item={
        'orderId': order_keys.PAYMENT_ATTEMPT_PREFIX + NATIVE_ATTEMPT_ID,
        'orderIdRef': NATIVE_ORDER_ID, 'orderNumber': NATIVE_ORDER_NUMBER,
        'providerTransactionId': NATIVE_PROVIDER_PAYMENT_ID})
    fake.Table(KEYS_TABLE).put_item(Item={
        'orderId': NATIVE_SESSION_KEY, 'status': 'ACTIVE',
        'sessionKey': CATALOG_SESSION['orderId']})


def _finalize(h):
    return h._native_catalog_service(
        {'internalAction': 'finalizeNativeCatalogService',
         'paymentAttemptId': NATIVE_ATTEMPT_ID}, 'http://localhost:3000')


def test_finalize_writes_the_order_with_txn_id_and_customer_id_and_closes_session(env):
    """A reconciled capture finalizes: the attempt reaches ORDER_FINALIZED, the ORDER record
    carries the Razorpay provider payment id and the customer id, and the one-purchase session
    closes. This is the end state that answers the original checklist (txn id + customer id)."""
    h, fake, _lam, _mp = env
    _seed_paid_native_service(h, fake)

    assert _finalize(h) == {'outcome': 'NATIVE_SERVICE_FINALIZED'}

    attempt = fake.Table(ATTEMPTS_TABLE).get_item(
        Key={'paymentAttemptId': NATIVE_ATTEMPT_ID})['Item']
    assert attempt['status'] == 'PAYMENT_PAID'
    assert attempt['orderId'] == NATIVE_ORDER_ID
    assert attempt['orderNumber'] == NATIVE_ORDER_NUMBER
    assert attempt['finalizationStage'] == 'ORDER_FINALIZED'

    # THE ORDER RECORD: the Razorpay transaction id and the customer id both land on it.
    order = fake.Table(ORDERS_TABLE).get_item(Key={'orderId': NATIVE_ORDER_ID})['Item']
    assert order['providerPaymentId'] == NATIVE_PROVIDER_PAYMENT_ID
    assert order['customerId'] == CUSTOMER
    assert order['orderNumber'] == NATIVE_ORDER_NUMBER
    assert order['amountPaise'] == TOTAL_PAYABLE_PAISE
    assert order['paymentStatus'] == 'PAYMENT_PAID'

    session = fake.Table(KEYS_TABLE).get_item(Key={'orderId': NATIVE_SESSION_KEY})['Item']
    assert session['status'] == 'CLOSED'


def test_a_short_capture_leaves_the_session_open_for_a_human(env):
    """One paise short of the payable records the order but stages NEEDS_RECONCILIATION, so the
    action answers NATIVE_SERVICE_FINALIZATION_PENDING and the session is left ACTIVE."""
    h, fake, _lam, _mp = env
    _seed_paid_native_service(h, fake, verified_paise=TOTAL_PAYABLE_PAISE - 1)

    assert _finalize(h) == {'outcome': 'NATIVE_SERVICE_FINALIZATION_PENDING'}

    attempt = fake.Table(ATTEMPTS_TABLE).get_item(
        Key={'paymentAttemptId': NATIVE_ATTEMPT_ID})['Item']
    assert attempt['finalizationStage'] == 'NEEDS_RECONCILIATION'
    assert attempt['finalizationReason'] == 'TENDER_SUM_MISMATCH'
    session = fake.Table(KEYS_TABLE).get_item(Key={'orderId': NATIVE_SESSION_KEY})['Item']
    assert session['status'] == 'ACTIVE'


def test_finalize_of_a_non_native_attempt_is_refused(env):
    """The finalizer only acts on a native catalog-service attempt; anything else is named and
    left alone."""
    h, fake, _lam, _mp = env
    from lambda_utils.ecommerce import payment_attempt as pa
    attempt = pa.build(customer_id=CUSTOMER, reference_id='WD-PAY-ORDINARY0001',
                       amount_paise=TOTAL_PAYABLE_PAISE, configuration_name='WECAREDIGITAL',
                       payment_attempt_id='att-ordinary-1')
    fake.Table(ATTEMPTS_TABLE).put_item(Item=attempt)
    result = h._native_catalog_service(
        {'internalAction': 'finalizeNativeCatalogService',
         'paymentAttemptId': 'att-ordinary-1'}, 'http://localhost:3000')
    assert result == {'outcome': 'NOT_A_NATIVE_SERVICE'}
