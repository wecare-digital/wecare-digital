"""The checkout handler: it consumes the payment core without ever creating an order or a charge.

What these tests defend (Wix-Velo prompt §44, §52, §58, §61)
------------------------------------------------------------
The mechanism (attempt state machine, reference reservation, readiness) is tested elsewhere. This
file tests the *handler's* obligations at the customer boundary:

- authority comes from the session, never the request: no session -> 401; another customer's
  attempt -> the identical opaque 401 (IDOR);
- the amount is Wix's authoritative total in integer paise, not the browser's; non-INR and
  non-whole-paise fail closed;
- payments are readiness-gated: a blocked readback creates NO attempt and NO order;
- with initiation disabled (the default), the attempt is prepared but NO payable message is sent
  and NO order exists;
- the canonical reference is reserved BEFORE the attempt is stored, and the handler never calls a
  post-PAID order_keys function (those belong to the webhook reconciliation, not checkout);
- a non-paid status view never carries an order number.
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

_HANDLER_PATH = (Path(__file__).resolve().parents[1]
                 / "amplify/functions/ecommerce/checkout/handler.py")

ATTEMPTS_TABLE = 'stack-wecare-digital-PaymentAttemptsTable'
KEYS_TABLE = 'stack-wecare-digital-WixOrderIds'
CUSTOMER = 'CUS_01J0000000000000000000000'
OTHER_CUSTOMER = 'CUS_01J9999999999999999999999'


class _FakeLambda:
    """Captures internal invokes: the payment-config read and the order_details send.

    The send no longer carries a `path`: it goes to `wecare-outbound-whatsapp:live` with a
    `body`-wrapped payload, which is the envelope that function's checkout-template branch owns.
    So `invocations` holds the UNWRAPPED send body where there is one, and `function_names`
    records what each invoke was aimed at — the target is part of the contract, because the old
    route pointed at a dispatcher that 404s.
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
            # A ready-looking raw payment_configurations readback for the WABA.
            inner = {'statusCode': 200, 'body': json.dumps({
                'data': [{'configuration_name': 'WECAREDIGITAL',
                          'status': 'active',
                          'payment_gateway': {'type': 'razorpay',
                                              'merchant_id': 'acc_TESTMID'}}]})}
        else:
            inner = {'statusCode': 200 if self.send_ok else 502, 'body': '{}'}
        return {'Payload': _Payload(json.dumps(inner).encode('utf-8'))}


class _Payload:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _Identity:
    """Stand-in for customer_auth.CustomerIdentity."""

    def __init__(self, customer_id, phone='+919330994400'):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = 'sub-1'

    def owns(self, cid):
        return bool(cid) and cid == self.customer_id


def _fake_checkout(total='599.00', currency='INR'):
    return {
        'id': 'wix-checkout-1',
        'currency': currency,
        'priceSummary': {'total': {'amount': total}},
        'lineItems': [{'productName': {'original': 'Viveka'}, 'quantity': 1}],
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('PAYMENT_ATTEMPTS_TABLE', ATTEMPTS_TABLE)
    monkeypatch.setenv('COMMERCE_KEYS_TABLE', KEYS_TABLE)
    monkeypatch.setenv('EXPECTED_CONFIGURATION_NAME', 'WECAREDIGITAL')
    monkeypatch.setenv('EXPECTED_PROVIDER_MID', 'acc_TESTMID')
    monkeypatch.setenv('PAYMENT_WABA_ID', '2094615664435155')
    monkeypatch.setenv('APP_ENV', 'development')

    spec = importlib.util.spec_from_file_location("checkout_under_test", _HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(keys={ATTEMPTS_TABLE: 'paymentAttemptId', KEYS_TABLE: 'orderId'})
    lam = _FakeLambda()

    monkeypatch.setattr(h, '_dynamodb', fake)
    monkeypatch.setattr(h, '_lambda_client', lambda: lam)
    # Default: initiation OFF (matches production default), a valid INR checkout, and an
    # authenticated CUSTOMER identity. Individual tests override.
    monkeypatch.setattr(h, 'INITIATION_ENABLED', False)
    monkeypatch.setattr(h.wix_ecom, 'create_checkout', lambda items, **k: _fake_checkout())
    monkeypatch.setattr(h.customer_auth, 'authenticate', lambda event: _Identity(CUSTOMER))
    # Every test in THIS file exercises the Checkout V1 price authority, which is what serves:
    # Cart V2 is opt-in behind `WIX_CART_V2_ENABLED` and the key is absent on every function.
    # Both keys are cleared rather than one being set, so this file reproduces the deployed
    # configuration instead of pinning a gate. The Cart V2 branch of the same handler is covered
    # by `tests/test_checkout_cart_v2_authority.py`.
    monkeypatch.delenv('WIX_CART_V2_ENABLED', raising=False)
    monkeypatch.delenv('WIX_CART_V2_DISABLED', raising=False)
    return h, fake, lam, monkeypatch


def _event(action='create', **body):
    return {
        'requestContext': {'http': {'method': 'POST', 'sourceIp': '203.0.113.5'}},
        'headers': {'origin': 'http://localhost:3000', 'authorization': 'Bearer tok'},
        'body': json.dumps({'action': action, **body}),
    }


def _create_event(**over):
    body = {'lineItems': [{'catalogReference': {'catalogItemId': 'p1'}, 'quantity': 1}]}
    body.update(over)
    return _event('create', **body)


#: A native catalog-service session row, as `flows/catalog_services.py` writes one. The
#: `phoneNumberId` is the AWS-style WABA1 id, which is what `_get_aws_phone_number_id` produces
#: and what `PAYMENT_SENDERS` permits.
CATALOG_SESSION = {
    'orderId': 'CATALOGSERVICE#tok-abcdefghijklmnopqrst',
    'contactId': 'contact-cat-1',
    'phoneNumberId': 'phone-number-id-waba1-direct-1016149501586345',
    'kind': 'SUBMIT_REQUEST',
    'productId': 'service-product-1',
    'variantId': 'service-variant-1',
}


COLLECTION_PAISE = 59900
FEE_PAISE = 1498
FEE_GST_PAISE = 270
TOTAL_PAYABLE_PAISE = COLLECTION_PAISE + FEE_PAISE + FEE_GST_PAISE


class _Quote:
    """The four figures `_create` and `payment_details` read off a `CheckoutQuote`."""

    total_payable_paise = TOTAL_PAYABLE_PAISE
    collection_before_convenience_paise = COLLECTION_PAISE
    convenience_fee_paise = FEE_PAISE
    convenience_gst_paise = FEE_GST_PAISE


class _Snapshot:
    """The frozen Cart V2 snapshot, with only the attributes `_create` reads."""

    cart_id = 'wix-cart-1'
    cart_revision = '3'
    snapshot_hash = 'sha256:testsnapshot'
    expires_at = 1770000900
    policy_version = 'v1'
    frozen_data = {'cart': {'id': 'wix-cart-1'}}
    quote = _Quote()


def _enable_catalog_leg(h, monkeypatch, *, quote=None):
    """Put the handler on the catalog leg's required Cart V2 branch, with pricing stubbed.

    The catalog leg is V2-only by construction — `snapshot` and `_calculated` exist only on that
    branch, and `_create` now refuses 503 `SERVICE_UNAVAILABLE` with V2 off rather than crashing.
    `_v2_snapshot` is stubbed rather than driven through Wix because the subject here is
    `_create`'s own contract: which figure it records, which refusals it makes, which rows it
    writes and which envelope it sends. Wix PRICING is owned by
    `tests/test_checkout_cart_v2_authority.py` and `tests/test_wix_cart_v2_*.py`.
    """
    monkeypatch.setenv('WIX_CART_V2_ENABLED', 'true')
    snapshot = _Snapshot()
    if quote is not None:
        snapshot.quote = quote
    monkeypatch.setattr(h, '_v2_snapshot',
                        lambda identity, line_items: (snapshot, ['Viveka x1'],
                                                      {'cart': {'lineItems': []}}))
    monkeypatch.setattr(h.wix_writeback, 'build_wix_order_payload',
                        lambda **kw: {'channelInfo': {}, 'lineItems': []})
    monkeypatch.setattr(h.wix_writeback, 'is_enabled', lambda: True)
    return snapshot


def _drive_catalog(h, **over):
    """Call `_create` DIRECTLY on the catalog-service leg.

    Why direct invocation rather than `h.handler(_create_event())`: the in-chat CART leg is
    refused at the top of `_create` (cart purchases are collected on the website), so
    `catalog_session` is never None past that point and the only way to exercise everything below
    it is to supply one. Driving it through `handler` would instead mean satisfying all of
    `_native_catalog_service`'s gates — the rollout flag, writeback, a token, a session row, a
    contacts row, a Cognito `list_users` call, an intent row and a `catalogServiceReadiness`
    invoke — and those gates are covered by `tests/test_native_catalog_orchestration.py`. The
    subject here is `_create`'s own contract, not the catalog orchestration.
    """
    body = {'lineItems': [{'catalogReference': {'catalogItemId': 'p1'}, 'quantity': 1}],
            'serviceIntentId': 'INTENT-TEST'}
    body.update(over)
    return h._create(_Identity(CUSTOMER), body, 'http://localhost:3000',
                     catalog_session=dict(CATALOG_SESSION))


def _seed_catalog_session(fake):
    """The session row the post-attempt conditional update matches on."""
    fake.Table(KEYS_TABLE).put_item(Item={
        'orderId': CATALOG_SESSION['orderId'],
        'serviceIntentId': 'INTENT-TEST',
        'status': 'PREPARING_PAYMENT',
    })


# ── authentication ───────────────────────────────────────────────────────────

def test_no_session_is_refused(env):
    h, _fake, _lam, monkeypatch = env
    from lambda_utils import customer_auth
    monkeypatch.setattr(h.customer_auth, 'authenticate',
                        lambda event: (_ for _ in ()).throw(
                            customer_auth.CustomerNotAuthenticated('no token')))
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 401


# ── A2.6: the in-chat CART leg is refused, before any I/O ─────────────────────
#
# Cart purchases are collected on the website via Razorpay Standard Checkout (requirements
# statement 8). With the dead `_send_order_details` route repaired onto a working envelope, the
# non-catalog leg of `_create` would otherwise have become a working in-chat cart payment, which
# is the opposite of that ruling.
#
# POSITION is what these tests are about, not the status code. The refusal sits at the TOP of
# `_create`, above the Wix call, the readiness gate, the reference reservation and the attempt
# write — so it burns nothing for a payment that can never be sent. The three tests that used to
# measure V1 pricing here (`..._wix_authoritative...`, `..._non_inr...`, `..._non_whole_paise...`)
# are folded in below, because the property is now stronger than the one they asserted: nothing
# is priced at all. Wix's own currency and whole-paise guards keep their coverage in
# `tests/test_wix_cart_v2_*.py` and on the website path.

def test_the_in_chat_cart_leg_is_refused_before_any_io(env):
    h, fake, lam, monkeypatch = env
    wix_calls = []
    monkeypatch.setattr(h.wix_ecom, 'create_checkout',
                        lambda items, **k: wix_calls.append(items) or _fake_checkout())

    resp = h.handler(_create_event(), None)

    # 200, matching the `PAYMENT_INITIATION_DISABLED` sibling: `cart.tsx` answers that shape with
    # the "no charge was made" copy, which is only honest because the server stopped before the
    # payment rail.
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'CART_PAYMENT_IS_WEBSITE_ONLY'
    assert 'Nothing has been charged.' in body['message']
    # No `paymentAttemptId`, because no attempt exists.
    assert 'paymentAttemptId' not in body

    # Zero rows in BOTH tables, no invoke, no Wix call.
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert fake.count(KEYS_TABLE) == 0
    assert lam.invocations == []
    assert wix_calls == []


@pytest.mark.parametrize('override', [
    # The browser claiming its own amount: never even read, because nothing is priced.
    {'amount': 1, 'amountPaise': 1, 'total': '1.00'},
    {},
])
def test_the_cart_refusal_does_not_depend_on_the_request_body(env, override):
    h, fake, _lam, _mp = env
    resp = h.handler(_create_event(**override), None)
    assert json.loads(resp['body'])['status'] == 'CART_PAYMENT_IS_WEBSITE_ONLY'
    assert fake.count(ATTEMPTS_TABLE) == 0


@pytest.mark.parametrize('checkout', [
    _fake_checkout(currency='USD'),       # would have been UNSUPPORTED_CURRENCY
    _fake_checkout(total='599.005'),      # would have been AMOUNT_NOT_SETTLED
])
def test_a_cart_wix_would_have_refused_is_refused_earlier_still(env, checkout):
    """The money guards are not bypassed — they are unreachable, which is stronger.

    A non-INR or sub-paise total used to be refused AFTER the live Wix call. Now the policy
    refusal precedes the call, so there is no total to be wrong about on this leg.
    """
    h, fake, _lam, monkeypatch = env
    monkeypatch.setattr(h.wix_ecom, 'create_checkout', lambda items, **k: checkout)
    resp = h.handler(_create_event(), None)
    assert json.loads(resp['body'])['status'] == 'CART_PAYMENT_IS_WEBSITE_ONLY'
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert fake.count(KEYS_TABLE) == 0


def test_the_cart_refusal_follows_the_service_refusal_in_source_order(env):
    """Structural. Both are pre-I/O policy refusals, and a service basket must keep answering with
    its OWN code rather than being swallowed by the cart one."""
    import inspect
    h, _fake, _lam, _mp = env
    source = inspect.getsource(h._create)
    assert (source.index('SERVICE_WEBSITE_ONLY')
            < source.index('CART_PAYMENT_IS_WEBSITE_ONLY')
            < source.index('cart_v2.is_enabled()'))


def test_a_website_only_service_in_a_cart_still_answers_the_service_code(env):
    h, fake, _lam, _mp = env
    from lambda_utils.ecommerce import service_requests as sr
    product = sorted(sr.SERVICE_PRODUCT_IDS)[0]
    resp = h.handler(_create_event(lineItems=[
        {'catalogReference': {'catalogItemId': product}, 'quantity': 1}]), None)
    assert resp['statusCode'] == 409
    assert json.loads(resp['body'])['error'] == sr.SERVICE_WEBSITE_ONLY
    assert fake.count(ATTEMPTS_TABLE) == 0


# ── create, initiation disabled (the default posture) — the CATALOG leg ────────

def test_create_disabled_prepares_attempt_but_sends_nothing_and_makes_no_order(env):
    h, fake, lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    resp = _drive_catalog(h)
    assert resp['statusCode'] == 200, resp['body']
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_INITIATION_DISABLED'
    # The CALCULATOR total — Wix's collection plus our convenience fee plus the GST on that fee —
    # never the raw collection figure.
    assert body['amountPaise'] == TOTAL_PAYABLE_PAISE
    assert body['currency'] == 'INR'

    # An attempt exists, in the readiness-checked state, marked WIX_HEADLESS, bound to the customer.
    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    assert attempts[0]['customerId'] == CUSTOMER
    assert attempts[0]['checkoutMode'] == 'WIX_HEADLESS'
    assert attempts[0]['amountPaise'] == TOTAL_PAYABLE_PAISE
    assert attempts[0]['status'] == 'PAYMENT_READINESS_CHECKED'

    # A PAYREF# reservation exists (reference reserved), but NO order rows: no ORDERNO#, no
    # PAYMENTATTEMPT# claim, no PROVIDERPAYMENT#.
    keys = fake.all_rows(KEYS_TABLE)
    assert any(str(r.get('orderId', '')).startswith('PAYREF#') for r in keys)
    assert not any(str(r.get('orderId', '')).startswith(('ORDERNO#', 'PAYMENTATTEMPT#',
                                                         'PROVIDERPAYMENT#')) for r in keys)

    # The ONLY internal invoke was the readiness payment-config read. No order_details send went
    # out, because initiation is disabled.
    paths = [str(e.get('path') or '') for e in lam.invocations]
    assert any('payment-config' in p for p in paths)
    assert not any('/whatsapp/send' in p for p in paths)
    assert not any(e.get('isCheckoutTemplate') for e in lam.invocations)


def test_the_amount_recorded_is_the_quote_not_the_request(env):
    """The browser's claim is never read. The figure recorded is the calculator's."""
    h, fake, _lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    _drive_catalog(h, amount=1, amountPaise=1, total='1.00')
    assert fake.all_rows(ATTEMPTS_TABLE)[0]['amountPaise'] == TOTAL_PAYABLE_PAISE


def test_the_catalog_leg_requires_cart_v2_and_refuses_rather_than_crashing(env):
    """`snapshot` and `_calculated` exist only on the V2 branch, so a V2-off deployment used to
    raise `UnboundLocalError` here. Named 503 instead, with the vocabulary
    `checkout_preflight` already uses for the same condition."""
    h, fake, lam, _mp = env
    from lambda_utils.ecommerce import service_requests as sr
    resp = _drive_catalog(h)
    assert resp['statusCode'] == 503
    assert json.loads(resp['body'])['error'] == sr.SERVICE_UNAVAILABLE
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert lam.invocations == []


# ── fail-closed readiness ─────────────────────────────────────────────────────

def test_blocked_readiness_creates_no_attempt_and_no_order(env):
    h, fake, _lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    # Empty expected configuration -> payment_readiness returns CONFIGURATION_UNVERIFIED (blocks),
    # without any live read. The CTA is refused and nothing is reserved.
    monkeypatch.setenv('EXPECTED_CONFIGURATION_NAME', '')
    monkeypatch.setattr(h, 'EXPECTED_CONFIGURATION_NAME', '')
    resp = _drive_catalog(h)
    assert resp['statusCode'] == 409
    body = json.loads(resp['body'])
    assert body['status'] == 'payment_unavailable'
    assert body['readiness']  # a blocking state is named
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert fake.count(KEYS_TABLE) == 0


def test_the_readiness_refusal_is_on_blocking_states_not_on_truthiness(env):
    """`ALL_STATES == {PAYMENT_READY} | BLOCKING_STATES` today, so the two forms agree — but the
    enumerated form is what the module asks for, so a state added later without being classified
    cannot become permissive by omission."""
    import inspect
    h, _fake, _lam, _mp = env
    source = inspect.getsource(h._create)
    assert 'readiness.state in payment_readiness.BLOCKING_STATES' in source
    assert 'if not readiness.ready' not in source


def test_empty_cart_is_refused(env):
    h, fake, _lam, _mp = env
    resp = h.handler(_create_event(lineItems=[]), None)
    assert resp['statusCode'] == 400
    assert fake.count(ATTEMPTS_TABLE) == 0


# ── create, initiation ENABLED: hands off, still no order ─────────────────────

def test_create_enabled_sends_order_details_and_still_creates_no_order(env):
    h, fake, lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    resp = _drive_catalog(h)
    assert resp['statusCode'] == 200, resp['body']
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_REQUEST_SENT'

    # The send went to the OUTBOUND sender on the envelope the resolver owns, carrying the
    # reserved reference byte-for-byte and the calculator's amount — but no order exists.
    send = [e for e in lam.invocations if e.get('isCheckoutTemplate')]
    assert len(send) == 1
    assert send[0]['templateName'] == 'wecarepay_wa'
    details = send[0]['checkoutOrderDetails']
    stored_ref = fake.all_rows(ATTEMPTS_TABLE)[0]['referenceId']
    assert details['reference_id'] == stored_ref     # byte-for-byte, not transformed
    assert details['total_amount']['value'] == TOTAL_PAYABLE_PAISE
    assert details['currency'] == 'INR'
    # The RESOLVER owns Mode 3; the caller supplies no settings and no link.
    assert 'payment_settings' not in details
    assert details['payment_configuration'] == 'WECAREDIGITAL'
    keys = fake.all_rows(KEYS_TABLE)
    assert not any(str(r.get('orderId', '')).startswith(('ORDERNO#', 'PAYMENTATTEMPT#')) for r in keys)


def test_the_send_targets_the_outbound_sender_and_not_the_business_api(env):
    """The repaired route. It used to POST `/wa-business/messages/send/interactive-payment` at the
    business-API Lambda, whose send dispatcher 404s on that path — so the function could never
    have sent anything, and the 404 surfaced as a 502 `SEND_FAILED` that looked like Meta."""
    h, fake, lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    _drive_catalog(h)
    targets = [f for f, e in zip(lam.function_names, lam.invocations)
               if e.get('isCheckoutTemplate')]
    assert targets == ['wecare-outbound-whatsapp:live']
    assert h.OUTBOUND_SENDER_FUNCTION == 'wecare-outbound-whatsapp:live'


def test_send_failure_leaves_attempt_and_no_order(env):
    h, fake, lam, monkeypatch = env
    _enable_catalog_leg(h, monkeypatch)
    _seed_catalog_session(fake)
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    lam.send_ok = False
    resp = _drive_catalog(h)
    assert resp['statusCode'] == 502
    assert json.loads(resp['body'])['status'] == 'SEND_FAILED'
    # The attempt is still there (reusable for a delivery retry); no order was created.
    assert fake.count(ATTEMPTS_TABLE) == 1


# ── status / IDOR ──────────────────────────────────────────────────────────

def _store_attempt(h, fake, customer_id, status='PAYMENT_PENDING', order_number=None,
                   finalization_stage=None, finalization_reason=None):
    from lambda_utils.ecommerce import payment_attempt as pa
    attempt = pa.build(customer_id=customer_id, reference_id='WD-PAY-ABCDEFGHJKMNPQ',
                       amount_paise=59900, configuration_name='WECAREDIGITAL')
    attempt = pa.transition(attempt, status) if status != 'CREATED' else attempt
    if order_number:
        attempt['orderNumber'] = order_number
    if finalization_stage:
        attempt['finalizationStage'] = finalization_stage
    if finalization_reason:
        attempt['finalizationReason'] = finalization_reason
    fake.Table(ATTEMPTS_TABLE).put_item(Item=attempt)
    return attempt


def test_status_returns_the_order_number_of_a_paid_but_unreconciled_attempt(env):
    """A captured payment whose Wix writeback is still pending must still report its order.

    This is the live shape, not a hypothetical: the writeback gate is off, so
    `finalization.accept_paid` commits the internal order, writes `orderNumber` at
    INTERNAL_ORDER_CREATED, then moves the stage to NEEDS_RECONCILIATION with
    WIX_WRITE_CONTRACT_REQUIRED. Order WD-ORD-7ZTSG8X7 sat exactly there.

    `order_number` used to be read only inside the `_finalize_from_claim` arm, which runs only
    while `finalizationStage` is unset -- so an attempt the webhook had already finalized reported
    `orderNumber: None` forever and the paying customer was shown "we are creating your order"
    permanently. The number is evidence the order record committed, and the reconciliation stage
    is bookkeeping against the store; the first must reach the customer and the second must not.
    """
    h, fake, _lam, _mp = env
    attempt = _store_attempt(h, fake, CUSTOMER, status='PAYMENT_PAID',
                             order_number='WD-ORD-7ZTSG8X7',
                             finalization_stage='NEEDS_RECONCILIATION',
                             finalization_reason='WIX_WRITE_CONTRACT_REQUIRED')
    resp = h.handler(_event('status', paymentAttemptId=attempt['paymentAttemptId']), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_PAID'
    assert body['attempt']['orderNumber'] == 'WD-ORD-7ZTSG8X7'
    # The amount the screen prints, in integer paise with the currency named explicitly.
    assert body['attempt']['amountPaise'] == 59900
    assert isinstance(body['attempt']['amountPaise'], int)
    assert body['attempt']['currency'] == 'INR'
    # No retry on a paid attempt, and no internal bookkeeping in a customer-facing payload: the
    # stage and its reason are the words that would turn a completed payment into a worry.
    assert body['attempt']['canRetry'] is False
    assert 'finalizationStage' not in body['attempt']
    assert 'finalizationReason' not in body['attempt']
    assert 'NEEDS_RECONCILIATION' not in resp['body']
    assert 'WIX_WRITE_CONTRACT_REQUIRED' not in resp['body']


def test_status_strips_an_order_number_from_a_non_paid_row(env):
    """The row carries a number and the state does not permit one, so the view drops it.

    Reading `orderNumber` off the attempt row is what makes the test above pass; this is the
    other half of that change. `payment_history_entry` gates on ORDER_ELIGIBLE_STATES, so a
    failed attempt cannot show an order number however it got onto the row.
    """
    h, fake, _lam, _mp = env
    attempt = _store_attempt(h, fake, CUSTOMER, status='PAYMENT_FAILED',
                             order_number='WD-ORD-7ZTSG8X7',
                             finalization_stage='NEEDS_RECONCILIATION')
    resp = h.handler(_event('status', paymentAttemptId=attempt['paymentAttemptId']), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['attempt']['orderNumber'] is None
    assert 'WD-ORD-7ZTSG8X7' not in resp['body']


def test_status_of_own_attempt_returns_no_order_number_when_not_paid(env):
    h, fake, _lam, _mp = env
    attempt = _store_attempt(h, fake, CUSTOMER, status='PAYMENT_PENDING')
    resp = h.handler(_event('status', paymentAttemptId=attempt['paymentAttemptId']), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['attempt']['orderNumber'] is None
    assert body['status'] == 'PAYMENT_PENDING'


def test_status_of_another_customers_attempt_is_opaque_401(env):
    h, fake, _lam, _mp = env
    attempt = _store_attempt(h, fake, OTHER_CUSTOMER, status='PAYMENT_PENDING')
    # The session is CUSTOMER (fixture default); the attempt belongs to OTHER_CUSTOMER.
    resp = h.handler(_event('status', paymentAttemptId=attempt['paymentAttemptId']), None)
    assert resp['statusCode'] == 401          # identical to unauthenticated: no IDOR oracle


def test_status_of_missing_attempt_is_the_same_401(env):
    h, _fake, _lam, _mp = env
    resp = h.handler(_event('status', paymentAttemptId='does-not-exist'), None)
    assert resp['statusCode'] == 401


# ── the handler never touches the post-PAID order path ─────────────────────────

def test_handler_never_calls_post_paid_order_keys(env):
    """Checkout reserves a reference; it must NOT claim an order or reserve a public number —
    those belong to the webhook reconciliation. A static check that the source imports the module
    for the pre-payment primitive only and calls none of the post-PAID functions."""
    source = _HANDLER_PATH.read_text()
    for post_paid in ('claim_order_for_payment', 'reserve_public_order_number',
                      'record_order_number_on_claim', 'mint_public_order_number'):
        assert post_paid not in source, f"checkout must not call {post_paid}"
    # It DOES use the pre-payment reservation.
    assert 'allocate_payment_reference' in source


# ── A2.5: only WABA1 may take a payment on the native catalog-service leg ─────
#
# The refusal is asserted TOGETHER WITH the absence of `nativePrepareClaim`, because the two are
# one guarantee rather than two. `nativePrepareClaim` is written `attribute_not_exists`-
# conditional, so a claim left behind by a refused preparation is not recoverable by the customer
# retrying: the retry answers CATALOG_SERVICE_RECONCILIATION_REQUIRED and needs a human. A test
# that checked only the outcome would still pass with the gate moved below the claim, and that is
# precisely the regression that matters.

#: WABA2's phone id, per `amplify/functions/shared/config.ts` `PHONE_NUMBER_ID_2`. The sender
#: resolver can legitimately return it; `PAYMENT_SENDERS` does not permit it to collect.
WABA2_SENDER = 'phone-number-id-waba-t-direct-1055232054343117'


def _seed_preparing_session(fake, *, phone_number_id):
    """A session row at exactly the state `_native_catalog_service` prepares from.

    `expiresAt` is far future so the staleness branch above the sender check cannot be what
    refuses, and `paymentAttemptId` is absent so the ALREADY_PREPARED branch cannot be either.
    Without both, this test would pass for the wrong reason.
    """
    row = dict(CATALOG_SESSION)
    row.update({'phoneNumberId': phone_number_id,
                'customerId': CUSTOMER,
                'serviceIntentId': 'INTENT-TEST',
                'status': 'PREPARING_PAYMENT',
                'expiresAt': 4070908800})
    fake.Table(KEYS_TABLE).put_item(Item=row)
    return row


def test_waba2_cannot_prepare_a_native_service_payment_and_leaves_no_claim(env):
    """A WABA2 session is refused by name, and the one-shot claim is NOT written.

    `_get_aws_phone_number_id` only ever produces the WABA1 id today, so this shape does not
    occur in production - it guards against WABA2, which the sender resolver can legitimately
    return and which may never collect.
    """
    h, fake, lam, monkeypatch = env
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    monkeypatch.setattr(h.wix_writeback, 'is_enabled', lambda: True)
    _seed_preparing_session(fake, phone_number_id=WABA2_SENDER)

    result = h._native_catalog_service(
        {'internalAction': 'prepareNativeCatalogService',
         'catalogToken': 'tok-abcdefghijklmnopqrst'}, 'http://localhost:3000')

    assert result == {'outcome': 'PAYMENT_SENDER_NOT_PERMITTED'}
    row = fake.Table(KEYS_TABLE).get_item(Key={'orderId': CATALOG_SESSION['orderId']})['Item']
    assert 'nativePrepareClaim' not in row, 'a refused preparation must leave no claim behind'
    # Refused before the identity reads, the Meta readiness invoke and any attempt row.
    assert lam.invocations == []
    assert fake.count(ATTEMPTS_TABLE) == 0


def test_the_sender_refusal_precedes_the_claim_in_source_order():
    """Structural, because POSITION is what makes "no claim on refusal" true rather than
    incidental. A gate moved below the claim would still refuse, and would still strand the
    session on a claim the customer's retry cannot clear.

    Both needles are the executable statements, not the comments that discuss them, so moving the
    check while leaving its rationale comment in place cannot satisfy this.
    """
    source = _HANDLER_PATH.read_text()
    check = source.index('not in wa_payment_request.PAYMENT_SENDERS')
    claim = source.index('SET nativePrepareClaim=:claimed')
    assert check < claim, 'the WABA1-only refusal must come before the one-shot claim write'
