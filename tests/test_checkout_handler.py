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
    """Captures internal invokes: the payment-config read and the order_details send."""

    def __init__(self):
        self.invocations = []
        self.send_ok = True

    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        event = json.loads(Payload.decode('utf-8'))
        self.invocations.append(event)
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


# ── authentication ───────────────────────────────────────────────────────────

def test_no_session_is_refused(env):
    h, _fake, _lam, monkeypatch = env
    from lambda_utils import customer_auth
    monkeypatch.setattr(h.customer_auth, 'authenticate',
                        lambda event: (_ for _ in ()).throw(
                            customer_auth.CustomerNotAuthenticated('no token')))
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 401


# ── create, initiation disabled (the default posture) ─────────────────────────

def test_create_disabled_prepares_attempt_but_sends_nothing_and_makes_no_order(env):
    h, fake, lam, _mp = env
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_INITIATION_DISABLED'
    assert body['amountPaise'] == 59900          # Wix authoritative 599.00 -> paise
    assert body['currency'] == 'INR'

    # An attempt exists, in the readiness-checked state, marked WIX_HEADLESS, bound to the customer.
    attempts = fake.all_rows(ATTEMPTS_TABLE)
    assert len(attempts) == 1
    assert attempts[0]['customerId'] == CUSTOMER
    assert attempts[0]['checkoutMode'] == 'WIX_HEADLESS'
    assert attempts[0]['amountPaise'] == 59900
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
    assert not any('send' in p for p in paths)


def test_amount_is_wix_authoritative_not_the_request(env):
    h, fake, _lam, monkeypatch = env
    # Wix says 599.00; the browser tries to claim a tiny amount in the body. The handler must
    # ignore the body and price from Wix.
    monkeypatch.setattr(h.wix_ecom, 'create_checkout',
                        lambda items, **k: _fake_checkout(total='599.00'))
    resp = h.handler(_create_event(amount=1, amountPaise=1, total='1.00'), None)
    assert json.loads(resp['body'])['amountPaise'] == 59900
    assert fake.all_rows(ATTEMPTS_TABLE)[0]['amountPaise'] == 59900


# ── fail-closed money and readiness ────────────────────────────────────────────

def test_non_inr_is_refused_with_no_attempt(env):
    h, fake, _lam, monkeypatch = env
    monkeypatch.setattr(h.wix_ecom, 'create_checkout',
                        lambda items, **k: _fake_checkout(currency='USD'))
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 409
    assert json.loads(resp['body'])['error'] == 'UNSUPPORTED_CURRENCY'
    assert fake.count(ATTEMPTS_TABLE) == 0


def test_non_whole_paise_total_fails_closed(env):
    h, fake, _lam, monkeypatch = env
    monkeypatch.setattr(h.wix_ecom, 'create_checkout',
                        lambda items, **k: _fake_checkout(total='599.005'))
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 409
    assert json.loads(resp['body'])['error'] == 'AMOUNT_NOT_SETTLED'
    assert fake.count(ATTEMPTS_TABLE) == 0


def test_blocked_readiness_creates_no_attempt_and_no_order(env):
    h, fake, _lam, monkeypatch = env
    # Empty expected configuration -> payment_readiness returns CONFIGURATION_UNVERIFIED (blocks),
    # without any live read. The CTA is refused and nothing is reserved.
    monkeypatch.setenv('EXPECTED_CONFIGURATION_NAME', '')
    monkeypatch.setattr(h, 'EXPECTED_CONFIGURATION_NAME', '')
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 409
    body = json.loads(resp['body'])
    assert body['status'] == 'payment_unavailable'
    assert body['readiness']  # a blocking state is named
    assert fake.count(ATTEMPTS_TABLE) == 0
    assert fake.count(KEYS_TABLE) == 0


def test_empty_cart_is_refused(env):
    h, fake, _lam, _mp = env
    resp = h.handler(_create_event(lineItems=[]), None)
    assert resp['statusCode'] == 400
    assert fake.count(ATTEMPTS_TABLE) == 0


# ── create, initiation ENABLED: hands off, still no order ─────────────────────

def test_create_enabled_sends_order_details_and_still_creates_no_order(env):
    h, fake, lam, monkeypatch = env
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    resp = h.handler(_create_event(), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'PAYMENT_REQUEST_SENT'

    # The order_details send was invoked, carrying the reserved reference byte-for-byte and the
    # authoritative amount — but no order exists.
    send = [e for e in lam.invocations if 'send' in str(e.get('path') or '')]
    assert len(send) == 1
    sent = json.loads(send[0]['body'])
    stored_ref = fake.all_rows(ATTEMPTS_TABLE)[0]['referenceId']
    assert sent['reference_id'] == stored_ref     # byte-for-byte, not transformed
    assert sent['amount_paise'] == 59900
    assert sent['currency'] == 'INR'
    keys = fake.all_rows(KEYS_TABLE)
    assert not any(str(r.get('orderId', '')).startswith(('ORDERNO#', 'PAYMENTATTEMPT#')) for r in keys)


def test_send_failure_leaves_attempt_and_no_order(env):
    h, fake, lam, monkeypatch = env
    monkeypatch.setattr(h, 'INITIATION_ENABLED', True)
    lam.send_ok = False
    resp = h.handler(_create_event(), None)
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
