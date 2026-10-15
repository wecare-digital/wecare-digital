"""A capture is usable only through a previously trusted attempt binding."""
import pathlib
import sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
from lambda_utils.integrations import razorpay_verify as rv


def captured(**overrides):
    return {'id': 'pay_bound', 'order_id': 'order_bound', 'status': 'captured',
            'amount': 59900, 'currency': 'INR', **overrides}


def test_event_alone_cannot_prove_payment_binding(monkeypatch):
    monkeypatch.setattr(rv, '_get', lambda _: pytest.fail('must not fetch event-selected payment'))
    with pytest.raises(rv.RazorpayUnavailable):
        rv.verifier_for_event(payment_id='pay_attacker', load_attempt=lambda _: {})('ref')


def test_matching_amount_from_another_order_is_rejected(monkeypatch):
    monkeypatch.setattr(rv, '_get', lambda _: captured(id='pay_attacker', order_id='order_other'))
    verify = rv.verifier_for_event(payment_id='pay_attacker',
                                   load_attempt=lambda _: {'providerOrderId': 'order_bound'})
    with pytest.raises(rv.RazorpayUnavailable):
        verify('ref')


def test_trusted_order_and_actual_payment_id_are_verified(monkeypatch):
    paths = []
    def get(path):
        paths.append(path)
        return captured()
    monkeypatch.setattr(rv, '_get', get)
    verify = rv.verifier_for_event(payment_id='pay_bound',
                                   load_attempt=lambda _: {'providerOrderId': 'order_bound'})
    assert verify('ref') == (True, 'pay_bound', 59900, 'INR')
    assert paths == ['/payments/pay_bound']


@pytest.mark.parametrize('amount', [59900.1, True, '59900', 0])
def test_provider_amount_is_not_coerced(monkeypatch, amount):
    monkeypatch.setattr(rv, '_get', lambda _: captured(amount=amount))
    verify = rv.verifier_for_event(payment_id='pay_bound',
                                   load_attempt=lambda _: {'providerPaymentId': 'pay_bound'})
    with pytest.raises(ValueError):
        verify('ref')


def test_order_lookup_uses_saved_order_not_webhook_order(monkeypatch):
    paths = []
    def get(path):
        paths.append(path)
        return {'items': [captured()]}
    monkeypatch.setattr(rv, '_get', get)
    verify = rv.verifier_for_event(order_id='order_attacker',
                                   load_attempt=lambda _: {'providerOrderId': 'order_bound'})
    assert verify('ref')[0] is True
    assert paths == ['/orders/order_bound/payments']


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 website Razorpay Standard Checkout: order-create binding + callback.
#
# The website path is ADDITIVE and sits behind the SAME disabled initiation gate as the retained
# in-chat flow. These exercise prepare_checkout / verify_callback against the honest DynamoDB fake
# the rest of the suite uses, with the Razorpay client fully mocked - no live provider call.
# ─────────────────────────────────────────────────────────────────────────────

import time  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import website_checkout as wc  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce.checkout_pricing import compute_quote, build_snapshot  # noqa: E402
from lambda_utils.integrations import razorpay_orders as ro  # noqa: E402

KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
CUSTOMER = 'CUS_website_001'
# The basket's raw collection total; the gateway amount must be the calculator total ON TOP of this.
COLLECTION_PAISE = 100000  # ₹1000.00 before convenience fee + GST


def _keys():
    return FakeDynamo({KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)


def _snapshot(now, *, customer=CUSTOMER, collection=COLLECTION_PAISE, cart_revision=1):
    quote = compute_quote(collection)
    return build_snapshot(
        customer_id=customer, cart_id='CART_1', cart_revision=cart_revision,
        quote=quote, created_at=now, ttl_seconds=900,
        items=[{'sku': 'A', 'qty': 1}])


def _mode_of(key_id):
    return ro.account_mode(key_id)


def _ok_create(order_id='order_WEBSITE1', key_id='rzp_live_TESTKEY'):
    created = {}

    def create_order(*, amount_paise, receipt, notes):
        created['amount_paise'] = amount_paise
        created['receipt'] = receipt
        created['notes'] = dict(notes)
        return {'id': order_id, 'amount': amount_paise, 'currency': 'INR',
                'status': 'created', 'receipt': receipt, 'key_id': key_id}

    return create_order, created


def test_disabled_gate_creates_no_gateway_order():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)

    def must_not_create(**_):
        pytest.fail('a disabled gate must not create a gateway order')

    result = wc.prepare_checkout(
        customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
        request_key='rk-1', now=now, keys_table=table,
        create_order=must_not_create, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=False)

    assert result.status == wc.PAYMENT_INITIATION_DISABLED
    assert result.gateway_order_id == ''
    assert result.options is None
    # No GATEWAYORDER# row exists.
    assert order_keys.resolve_gateway_order(table, 'order_WEBSITE1') is None


def test_gateway_amount_equals_calculator_total_not_raw_collection_total():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)
    create_order, created = _ok_create()

    result = wc.prepare_checkout(
        customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
        request_key='rk-2', now=now, keys_table=table,
        create_order=create_order, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=True)

    assert result.status == wc.CHECKOUT_OPTIONS_READY
    expected_total = snap.quote.total_payable_paise
    assert expected_total > COLLECTION_PAISE  # fee + GST were added on top
    assert created['amount_paise'] == expected_total
    assert result.options['amountPaise'] == expected_total
    # The browser projection carries ONLY the allowed fields.
    assert set(result.options) == {
        'keyId', 'orderId', 'amountPaise', 'currency', 'prefill', 'paymentAttemptId'}
    assert result.options['keyId'] == 'rzp_live_TESTKEY'
    # The binding is persisted with the account/mode/amount.
    binding = order_keys.resolve_gateway_order(table, 'order_WEBSITE1')
    assert binding['amountPaise'] == expected_total
    assert binding['accountMode'] == 'live'
    assert binding['accountKeyId'] == 'rzp_live_TESTKEY'


def test_changed_intent_on_resumed_request_key_is_rejected():
    table = _keys()
    now = int(time.time())
    create_order, _ = _ok_create()

    # First click reserves rk-3 with one intent and creates an order.
    first = wc.prepare_checkout(
        customer_id=CUSTOMER, snapshot=_snapshot(now), presented_snapshot_hash=_snapshot(now).snapshot_hash,
        request_key='rk-3', now=now, keys_table=table,
        create_order=create_order, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=True)
    assert first.status == wc.CHECKOUT_OPTIONS_READY

    # Same request key, DIFFERENT intent (a changed cart revision -> different snapshot hash).
    changed = _snapshot(now, cart_revision=2)
    with pytest.raises(wc.CheckoutRejected) as exc:
        wc.prepare_checkout(
            customer_id=CUSTOMER, snapshot=changed, presented_snapshot_hash=changed.snapshot_hash,
            request_key='rk-3', now=now, keys_table=table,
            create_order=lambda **_: pytest.fail('must not create a second order'),
            find_order_by_receipt=lambda r: None,
            account_mode_of=_mode_of, initiation_enabled=True)
    assert exc.value.reason == 'INTENT_CHANGED'


def test_concurrent_same_intent_clicks_coordinate_on_one_order():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)
    creates = []

    def create_order(*, amount_paise, receipt, notes):
        creates.append(receipt)
        return {'id': 'order_ONCE', 'amount': amount_paise, 'currency': 'INR',
                'status': 'created', 'receipt': receipt, 'key_id': 'rzp_live_K'}

    kwargs = dict(
        customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
        request_key='rk-4', now=now, keys_table=table,
        create_order=create_order, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=True)

    first = wc.prepare_checkout(**kwargs)
    second = wc.prepare_checkout(**kwargs)  # the same key, same intent (a double-click)

    assert first.status == second.status == wc.CHECKOUT_OPTIONS_READY
    assert first.gateway_order_id == second.gateway_order_id == 'order_ONCE'
    assert first.payment_attempt_id == second.payment_attempt_id
    # Exactly ONE payable order was created despite two clicks.
    assert len(creates) == 1


def test_provider_create_timeout_does_not_blindly_create_second_order():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)
    attempts = {'n': 0}

    def timing_out_create(*, amount_paise, receipt, notes):
        attempts['n'] += 1
        raise ro.RazorpayUnavailable('timed out creating order')

    # Correlation lookup cannot confirm a landed order -> ambiguous, NOT a second create.
    result = wc.prepare_checkout(
        customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
        request_key='rk-5', now=now, keys_table=table,
        create_order=timing_out_create, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=True)

    assert result.status == wc.CHECKOUT_AMBIGUOUS
    assert attempts['n'] == 1  # the create was attempted exactly once
    assert order_keys.resolve_gateway_order(table, 'order_ANY') is None


def test_provider_create_timeout_recovers_via_receipt_correlation():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)

    def timing_out_create(*, amount_paise, receipt, notes):
        raise ro.RazorpayUnavailable('timed out, but it may have landed')

    def find(receipt):
        # The first create DID land on Razorpay's side; correlation finds it by receipt.
        return {'id': 'order_LANDED', 'amount': snap.quote.total_payable_paise,
                'currency': 'INR', 'status': 'created', 'receipt': receipt,
                'key_id': 'rzp_live_K', 'notes': {'customerId': CUSTOMER}}

    result = wc.prepare_checkout(
        customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
        request_key='rk-6', now=now, keys_table=table,
        create_order=timing_out_create, find_order_by_receipt=find,
        account_mode_of=_mode_of, initiation_enabled=True)

    assert result.status == wc.CHECKOUT_OPTIONS_READY
    assert result.gateway_order_id == 'order_LANDED'
    # Bound to the recovered order rather than a second one.
    assert order_keys.resolve_gateway_order(table, 'order_LANDED') is not None


def _bind_an_order(table, *, order_id='order_CB', amount, key_id='rzp_live_K', mode='live'):
    order_keys.bind_gateway_order(
        table, gateway_order_id=order_id, payment_attempt_id='att_CB',
        request_key='rk-cb', amount_paise=amount, account_key_id=key_id,
        account_mode=mode, currency='INR')


def test_callback_hmac_failure_against_stored_order_id_is_rejected():
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount)

    def bad_sig(**_):
        return False  # signature does not verify against the stored order id

    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='forged', keys_table=table, verify_signature=bad_sig,
        verify_capture=lambda _: pytest.fail('capture must not be checked on a bad signature'))
    assert result.status == wc.CALLBACK_SIGNATURE_INVALID


def test_callback_unknown_stored_order_is_a_binding_mismatch():
    table = _keys()
    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_UNKNOWN', payment_id='pay_1',
        signature='whatever', keys_table=table,
        verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_1', 1, 'INR'))
    assert result.status == wc.CALLBACK_BINDING_MISMATCH


def test_signed_browser_success_still_requires_provider_verified_capture():
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount)

    # The HMAC is valid, but Razorpay reports no capture: must NOT be paid.
    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: (False, '', 0, ''))
    assert result.status == wc.CALLBACK_NOT_CAPTURED

    # A valid signature AND an authoritative capture that matches the binding -> paid. The stored
    # account/mode cross-check (live key id -> live mode) agrees, so it does not block the settle.
    paid = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_real', amount, 'INR'), account_mode_of=_mode_of)
    assert paid.status == wc.CALLBACK_VERIFIED_PAID
    assert paid.payment_id == 'pay_real'
    assert paid.amount_paise == amount


def test_callback_stored_mode_disagreeing_with_stored_key_does_not_settle():
    # The binding persists accountMode AND accountKeyId expressly so a test-mode success never
    # settles a live-mode order (order_keys.bind_gateway_order / razorpay_orders.account_mode).
    # A binding whose stored mode ('test') disagrees with the mode its own stored key ('rzp_live_')
    # resolves to is a tampered/cross-mode binding and MUST NOT settle, even with a valid signature
    # and an authoritative capture that matches amount+currency.
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount, key_id='rzp_live_K', mode='test')

    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: pytest.fail('a mode mismatch must not reach the capture readback'),
        account_mode_of=_mode_of)
    assert result.status == wc.CALLBACK_BINDING_MISMATCH


def test_callback_unknown_account_mode_does_not_settle():
    # A key id we cannot positively classify resolves to 'unknown', which must not settle a bound
    # order rather than being treated as a match.
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount, key_id='notarealkey', mode='unknown')

    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: pytest.fail('an unknown mode must not reach the capture readback'),
        account_mode_of=_mode_of)
    assert result.status == wc.CALLBACK_BINDING_MISMATCH


def test_callback_matching_mode_settles():
    # The positive control for the account/mode cross-check: a live key id + stored 'live' mode
    # agree, so the check does not block an otherwise-valid settle.
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount, key_id='rzp_live_K', mode='live')

    paid = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_real', amount, 'INR'), account_mode_of=_mode_of)
    assert paid.status == wc.CALLBACK_VERIFIED_PAID


def test_callback_capture_amount_mismatch_does_not_settle():
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount)

    # Signature valid, capture authoritative, but a DIFFERENT amount than we bound.
    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_real', amount + 1, 'INR'))
    assert result.status == wc.CALLBACK_BINDING_MISMATCH


def test_callback_wrong_currency_capture_does_not_settle():
    table = _keys()
    amount = compute_quote(COLLECTION_PAISE).total_payable_paise
    _bind_an_order(table, amount=amount)
    result = wc.verify_callback(
        customer_id=CUSTOMER, presented_order_id='order_CB', payment_id='pay_1',
        signature='valid', keys_table=table, verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_real', amount, 'USD'))
    assert result.status == wc.CALLBACK_BINDING_MISMATCH


def test_ownership_and_snapshot_guards_reject_without_creating():
    table = _keys()
    now = int(time.time())
    snap = _snapshot(now)

    def must_not_create(**_):
        pytest.fail('a rejected checkout must not create an order')

    # Wrong customer.
    with pytest.raises(wc.CheckoutRejected) as exc:
        wc.prepare_checkout(
            customer_id='CUS_other', snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
            request_key='rk-x', now=now, keys_table=table, create_order=must_not_create,
            find_order_by_receipt=lambda r: None, account_mode_of=_mode_of,
            initiation_enabled=True)
    assert exc.value.reason == 'OWNERSHIP'

    # Tampered snapshot hash.
    with pytest.raises(wc.CheckoutRejected) as exc:
        wc.prepare_checkout(
            customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash='deadbeef',
            request_key='rk-y', now=now, keys_table=table, create_order=must_not_create,
            find_order_by_receipt=lambda r: None, account_mode_of=_mode_of,
            initiation_enabled=True)
    assert exc.value.reason == 'SNAPSHOT_MISMATCH'

    # Expired snapshot.
    with pytest.raises(wc.CheckoutRejected) as exc:
        wc.prepare_checkout(
            customer_id=CUSTOMER, snapshot=snap, presented_snapshot_hash=snap.snapshot_hash,
            request_key='rk-z', now=snap.expires_at + 1, keys_table=table,
            create_order=must_not_create, find_order_by_receipt=lambda r: None,
            account_mode_of=_mode_of, initiation_enabled=True)
    assert exc.value.reason == 'SNAPSHOT_EXPIRED'


def test_checkout_signature_matches_razorpay_documented_formula(monkeypatch):
    # order_id|payment_id keyed with key_secret. Verify both the compute and the compare helpers.
    monkeypatch.setattr(ro, '_credentials', lambda: {'key_id': 'rzp_live_K', 'key_secret': 'sek'})
    import hmac
    import hashlib
    expected = hmac.new(b'sek', b'order_CB|pay_1', hashlib.sha256).hexdigest()
    assert ro.checkout_signature('order_CB', 'pay_1') == expected
    assert ro.verify_checkout_signature(
        stored_order_id='order_CB', payment_id='pay_1', signature=expected) is True
    assert ro.verify_checkout_signature(
        stored_order_id='order_CB', payment_id='pay_1', signature='nope') is False
