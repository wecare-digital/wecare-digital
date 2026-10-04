"""Section 5 voluntary blog contributions (BLOG_CONTRIBUTION), built but gated OFF.

These drive the ACTUAL contribution functions (``prepare_contribution`` /
``verify_contribution_callback`` / ``settle_contribution_capture``) and the real webhook handler
against the honest in-memory DynamoDB fake the rest of the suite uses, with the Razorpay client
fully stubbed - no live provider call. They mirror ``test_razorpay_binding.py`` (website checkout),
which is the closest precedent.

Two REVERT-CHECKS are called out in their docstrings:
  * ``test_disabled_gate_creates_no_gateway_order`` fails if the initiation gate is reverted.
  * ``test_webhook_notes_amount_is_not_authority`` fails if the notes-not-authority guard is
    reverted (amount re-derived from the stored record, not from payment.notes).
"""
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import blog_contribution as bc  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.integrations import razorpay_orders as ro  # noqa: E402

KEYS_TABLE = 'stack-wecare-digital-WixOrderIds'
POST_ID = 'post_abc123'
SLUG = 'how-to-do-the-thing'


def _keys():
    return FakeDynamo({KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)


def _mode_of(key_id):
    return ro.account_mode(key_id)


def _ok_create(order_id='order_CONTRIB1', key_id='rzp_live_TESTKEY'):
    created = {}

    def create_order(*, amount_paise, receipt, notes):
        created['amount_paise'] = amount_paise
        created['receipt'] = receipt
        created['notes'] = dict(notes)
        return {'id': order_id, 'amount': amount_paise, 'currency': 'INR',
                'status': 'created', 'receipt': receipt, 'key_id': key_id}

    return create_order, created


def _prepare(table, *, request_key, amount=10000, currency='INR', enabled=True,
             create_order=None, customer_id='CUS_1', find=None):
    if create_order is None:
        create_order, _ = _ok_create()
    return bc.prepare_contribution(
        post_id=POST_ID, slug=SLUG, requested_amount_paise=amount, currency=currency,
        request_key=request_key, now=int(time.time()), keys_table=table,
        create_order=create_order, find_order_by_receipt=find or (lambda r: None),
        account_mode_of=_mode_of, initiation_enabled=enabled, customer_id=customer_id)


# ── amount validation (server authority) ────────────────────────────────────────

@pytest.mark.parametrize('preset', list(bc.CONTRIBUTION_PRESETS_PAISE))
def test_each_preset_amount_is_accepted(preset):
    assert bc.validate_contribution_amount(preset) == preset


def test_server_presets_mirror_the_frontend_contract():
    # The three common amounts: Rs.100 / Rs.250 / Rs.500, as integer paise. The server copy is
    # intentionally separate so the browser cannot widen the trusted amount.
    #
    # THIS IS THE RETIRED OWN-MONEY PATH's copy of those amounts. `validate_contribution_amount`
    # and `prepare_contribution` still use it, and the figures still agree with the three live
    # choices, but src/config/contribution.ts no longer declares a matching
    # `CONTRIBUTION_PRESETS_PAISE` -- the 2026-10-04 owner model change replaced the
    # preset-plus-custom-amount model with three fixed-price Wix variants, so there is no
    # browser-proposed amount left to widen. The guard on the LIVE contract is
    # `test_server_choices_mirror_the_frontend_contract` below.
    assert bc.CONTRIBUTION_PRESETS_PAISE == (10000, 25000, 50000)


def test_server_choices_mirror_the_frontend_contract():
    """The THREE FIXED CHOICES, declared in Python and in TypeScript, held equal here.

    Declared twice on purpose: the browser must not be able to widen the trusted set, so the
    server cannot import the browser's copy. That makes drift the hazard, and this is the guard.
    Parsed out of the TS source rather than transpiled, which is the same move
    `test_server_presets_mirror_the_frontend_contract` made for the retired presets.

    The GUIDs are MEASURED values, read off the live `Contribute` product's
    `GET /stores/v3/products/{id}` on 2026-10-04 -- one product, PHYSICAL, three visible in-stock
    variants priced Rs.100 / Rs.250 / Rs.500.
    """
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    config = (root / "src/config/contribution.ts").read_text(encoding="utf-8")

    # Matched on the DECLARATION, not on the `|| 'default'` fallback it used to carry. The
    # `NEXT_PUBLIC_CONTRIBUTION_PRODUCT_ID` override was removed in review pass 3 (CR3-4): set
    # alone it made the browser name a product the server does not recognise, which prices the
    # line as an ordinary purchase with the convenience fee, the GST and an address demand, with
    # no guard firing. A regex anchored on `||` would have gone quietly green against a file that
    # no longer declares an id at all, so it is anchored on the name instead.
    product = re.search(r"CONTRIBUTION_PRODUCT_ID[^=]*=\s*'([0-9a-f-]{36})'", config)
    assert product, "src/config/contribution.ts must declare the contribution product id"
    assert bc.CONTRIBUTION_PRODUCT_IDS == frozenset({product.group(1)})
    # And the override stays gone. Asserted on `process.env` rather than on the key's name, which
    # is deliberate: the file's own docstring has to be able to explain which override was removed
    # and why, and a text ban on the name would make that explanation fail the test. What must not
    # come back is a READ.
    assert "process.env" not in config, \
        "no build-time env override belongs in the contribution config (CR3-4)"

    declared = re.findall(
        r"variantId:\s*'([0-9a-f-]{36})',\s*rupees:\s*(\d+),\s*paise:\s*(\d+)", config)
    assert len(declared) == 3, f"expected three choices in the TS config, found {len(declared)}"
    assert {variant: int(paise) for variant, _rupees, paise in declared} \
        == dict(bc.CONTRIBUTION_CHOICES_PAISE)
    # Each TS choice's rupee label and paise value agree, so neither side can carry a typo that
    # the other happens to repeat.
    for _variant, rupees, paise in declared:
        assert int(rupees) * 100 == int(paise)
    assert bc.CONTRIBUTION_VARIANT_IDS == frozenset(bc.CONTRIBUTION_CHOICES_PAISE)


# `validate_contribution_amount` is PRESET-ONLY, and the bounds constants it used to carry
# (`CONTRIBUTION_MIN_PAISE` / `CONTRIBUTION_MAX_PAISE`) are gone, so the old
# in-bounds-custom-amount case has no subject any more. The former presets 20000 / 40000 / 60000
# are among the rejected values below, which is what pins that the retired path narrowed rather
# than merely moved.
@pytest.mark.parametrize('bad', [999, 0, -10000, 20000, 40000, 60000, 12345, 10_000_000])
def test_non_preset_amount_is_rejected(bad):
    with pytest.raises(bc.ContributionRejected) as exc:
        bc.validate_contribution_amount(bad)
    assert exc.value.reason in ('AMOUNT_NOT_ALLOWED', 'INVALID_AMOUNT')


@pytest.mark.parametrize('bad', [10000.5, 100.0, True, '10000', None, '₹100'])
def test_fractional_or_nonint_amount_is_rejected(bad):
    with pytest.raises(bc.ContributionRejected) as exc:
        bc.validate_contribution_amount(bad)
    assert exc.value.reason == 'INVALID_AMOUNT'


def test_non_inr_currency_is_rejected():
    with pytest.raises(bc.ContributionRejected) as exc:
        bc.validate_contribution_amount(10000, currency='USD')
    assert exc.value.reason == 'UNSUPPORTED_CURRENCY'


def test_amount_is_exact_integer_paise_never_rupees():
    assert bc.validate_contribution_amount(10000) == 10000
    with pytest.raises(bc.ContributionRejected) as exc:
        bc.validate_contribution_amount(100)
    assert exc.value.reason == 'AMOUNT_NOT_ALLOWED'


# ── initiation gate (REVERT-CHECK) ──────────────────────────────────────────────

def test_disabled_gate_creates_no_gateway_order():
    """REVERT-CHECK: fails if the initiation gate is reverted.

    With the gate OFF (the default), prepare_contribution must return PAYMENT_INITIATION_DISABLED,
    create NO gateway order, and expose NO payable options. If someone deletes the gate check, the
    create_order below fires and this test fails on the pytest.fail.
    """
    table = _keys()

    def must_not_create(**_):
        pytest.fail('a disabled gate must not create a gateway order')

    result = _prepare(table, request_key='rk-off', enabled=False, create_order=must_not_create)

    assert result.status == bc.PAYMENT_INITIATION_DISABLED
    assert result.gateway_order_id == ''
    assert result.options is None
    assert order_keys.resolve_gateway_order(table, 'order_CONTRIB1') is None
    # The contribution record exists (reserved pre-create) but is still INITIATED, not payable.
    record = order_keys.resolve_contribution(table, result.contribution_id)
    assert record is not None
    assert record['state'] == 'INITIATED'
    assert record['amountPaise'] == 10000
    assert record['gatewayOrderId'] == ''


def test_disabled_gate_rejects_a_widened_amount_before_the_gate():
    # Even gated off, an amount the browser widened past the server's max is refused outright - the
    # validator runs before the gate, so a disabled gate never launders a bad amount.
    table = _keys()
    with pytest.raises(bc.ContributionRejected) as exc:
        _prepare(table, request_key='rk-wide', amount=50_000_000, enabled=False,
                 create_order=lambda **_: pytest.fail('must not create'))
    assert exc.value.reason == 'AMOUNT_NOT_ALLOWED'


# ── enabled initiation (the gated-ON seam) ──────────────────────────────────────

def test_enabled_creates_bound_order_with_browser_safe_options_only():
    table = _keys()
    create_order, created = _ok_create()
    result = _prepare(table, request_key='rk-on', amount=25000, create_order=create_order)

    assert result.status == bc.CHECKOUT_OPTIONS_READY
    # The amount charged is EXACTLY the chosen contribution - no convenience fee/GST added on top.
    assert created['amount_paise'] == 25000
    assert result.options['amountPaise'] == 25000
    # Only the browser-safe projection is exposed.
    assert set(result.options) == {
        'keyId', 'orderId', 'amountPaise', 'currency', 'prefill', 'paymentAttemptId'}
    assert result.options['keyId'] == 'rzp_live_TESTKEY'
    # The binding is persisted with account/mode/amount and the contribution purpose.
    binding = order_keys.resolve_gateway_order(table, 'order_CONTRIB1')
    assert binding['amountPaise'] == 25000
    assert binding['accountMode'] == 'live'
    assert binding['purpose'] == 'BLOG_CONTRIBUTION'
    # notes carry opaque ids + purpose only, NEVER a trusted amount authority downstream.
    assert created['notes']['purpose'] == 'BLOG_CONTRIBUTION'
    assert created['notes']['contributionId'] == result.contribution_id
    # The contribution record now links the gateway order.
    record = order_keys.resolve_contribution(table, result.contribution_id)
    assert record['gatewayOrderId'] == 'order_CONTRIB1'


def test_anonymous_contribution_is_allowed_and_still_server_amount():
    table = _keys()
    create_order, created = _ok_create()
    result = bc.prepare_contribution(
        post_id=POST_ID, slug=SLUG, requested_amount_paise=50000, currency='INR',
        request_key='rk-anon', now=int(time.time()), keys_table=table,
        create_order=create_order, find_order_by_receipt=lambda r: None,
        account_mode_of=_mode_of, initiation_enabled=True, customer_id='')
    assert result.status == bc.CHECKOUT_OPTIONS_READY
    assert created['amount_paise'] == 50000


def test_changed_intent_on_resumed_request_key_is_rejected():
    table = _keys()
    create_order, _ = _ok_create()
    first = _prepare(table, request_key='rk-dup', amount=10000, create_order=create_order)
    assert first.status == bc.CHECKOUT_OPTIONS_READY
    # Same key, DIFFERENT amount -> different fingerprint -> rejected, no second order.
    with pytest.raises(bc.ContributionRejected) as exc:
        _prepare(table, request_key='rk-dup', amount=25000,
                 create_order=lambda **_: pytest.fail('must not create a second order'))
    assert exc.value.reason == 'INTENT_CHANGED'


def test_concurrent_same_intent_clicks_coordinate_on_one_order():
    table = _keys()
    creates = []

    def create_order(*, amount_paise, receipt, notes):
        creates.append(receipt)
        return {'id': 'order_ONCE', 'amount': amount_paise, 'currency': 'INR',
                'status': 'created', 'receipt': receipt, 'key_id': 'rzp_live_K'}

    first = _prepare(table, request_key='rk-cc', create_order=create_order)
    second = _prepare(table, request_key='rk-cc', create_order=create_order)
    assert first.status == second.status == bc.CHECKOUT_OPTIONS_READY
    assert first.gateway_order_id == second.gateway_order_id == 'order_ONCE'
    assert len(creates) == 1


def test_provider_timeout_does_not_blindly_create_second_order():
    table = _keys()
    attempts = {'n': 0}

    def timing_out(*, amount_paise, receipt, notes):
        attempts['n'] += 1
        raise ro.RazorpayUnavailable('timed out')

    result = _prepare(table, request_key='rk-to', create_order=timing_out)
    assert result.status == bc.CHECKOUT_AMBIGUOUS
    assert attempts['n'] == 1


def test_missing_post_is_rejected_without_creating():
    table = _keys()
    with pytest.raises(bc.ContributionRejected) as exc:
        bc.prepare_contribution(
            post_id='', slug=SLUG, requested_amount_paise=10000, currency='INR',
            request_key='rk-nopost', now=int(time.time()), keys_table=table,
            create_order=lambda **_: pytest.fail('must not create'),
            find_order_by_receipt=lambda r: None, account_mode_of=_mode_of,
            initiation_enabled=True)
    assert exc.value.reason == 'MISSING_POST'


# ── callback verification ───────────────────────────────────────────────────────

def _bind(table, *, order_id='order_CB', amount=10000, key_id='rzp_live_K', mode='live',
          contribution_id='contrib_1'):
    order_keys.reserve_contribution(
        table, contribution_id=contribution_id, post_id=POST_ID, slug=SLUG,
        amount_paise=amount, payment_attempt_id='att_CB')
    order_keys.bind_gateway_order(
        table, gateway_order_id=order_id, payment_attempt_id='att_CB', request_key='rk-cb',
        amount_paise=amount, account_key_id=key_id, account_mode=mode, currency='INR',
        extra={'purpose': 'BLOG_CONTRIBUTION', 'contributionId': contribution_id})


def test_signature_alone_is_not_proof_requires_capture_readback():
    """A valid HMAC is only a trigger; without an authoritative capture there is no paid state."""
    table = _keys()
    _bind(table, amount=10000)
    result = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='valid', keys_table=table,
        verify_signature=lambda **_: True, verify_capture=lambda _: (False, '', 0, ''))
    assert result.status == bc.CALLBACK_NOT_CAPTURED


def test_bad_signature_against_stored_order_is_rejected_before_capture():
    table = _keys()
    _bind(table, amount=10000)
    result = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='forged', keys_table=table,
        verify_signature=lambda **_: False,
        verify_capture=lambda _: pytest.fail('capture must not be checked on a bad signature'))
    assert result.status == bc.CALLBACK_SIGNATURE_INVALID


def test_unknown_stored_order_is_a_binding_mismatch():
    table = _keys()
    result = bc.verify_contribution_callback(
        presented_order_id='order_UNKNOWN', payment_id='pay_1', signature='x', keys_table=table,
        verify_signature=lambda **_: True, verify_capture=lambda _: (True, 'pay_1', 1, 'INR'))
    assert result.status == bc.CALLBACK_BINDING_MISMATCH


def test_capture_amount_mismatch_does_not_settle():
    table = _keys()
    _bind(table, amount=10000)
    result = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='valid', keys_table=table,
        verify_signature=lambda **_: True, verify_capture=lambda _: (True, 'pay_real', 25000, 'INR'))
    assert result.status == bc.CALLBACK_BINDING_MISMATCH


def test_capture_currency_mismatch_does_not_settle():
    table = _keys()
    _bind(table, amount=10000)
    result = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='valid', keys_table=table,
        verify_signature=lambda **_: True, verify_capture=lambda _: (True, 'pay_real', 10000, 'USD'))
    assert result.status == bc.CALLBACK_BINDING_MISMATCH


def test_test_mode_binding_cannot_settle_live():
    # A binding whose stored mode ('test') disagrees with the mode its own stored key ('rzp_live_')
    # resolves to must not settle, even with a valid signature and a matching capture.
    table = _keys()
    _bind(table, amount=10000, key_id='rzp_live_K', mode='test')
    result = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='valid', keys_table=table,
        verify_signature=lambda **_: True,
        verify_capture=lambda _: pytest.fail('a mode mismatch must not reach the capture readback'),
        account_mode_of=_mode_of)
    assert result.status == bc.CALLBACK_BINDING_MISMATCH


def test_matching_signature_and_capture_settles():
    table = _keys()
    _bind(table, amount=10000, key_id='rzp_live_K', mode='live')
    paid = bc.verify_contribution_callback(
        presented_order_id='order_CB', payment_id='pay_1', signature='valid', keys_table=table,
        verify_signature=lambda **_: True,
        verify_capture=lambda _: (True, 'pay_real', 10000, 'INR'), account_mode_of=_mode_of)
    assert paid.status == bc.CALLBACK_VERIFIED_PAID
    assert paid.payment_id == 'pay_real'
    assert paid.amount_paise == 10000
    assert paid.contribution_id == 'contrib_1'


# ── webhook settlement: idempotency, notes-not-authority, quarantine, no Wix order ──

def _settle(table, *, payment, provider):
    quarantined = []

    def quarantine(ref, pay_id):
        quarantined.append((ref, pay_id))

    result = bc.settle_contribution_capture(
        payment=payment, keys_table=table, verify_capture=lambda pid: provider,
        quarantine=quarantine)
    return result, quarantined


def test_webhook_settles_once_and_replay_settles_nothing():
    table = _keys()
    order_keys.reserve_contribution(
        table, contribution_id='c_set', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_set')
    payment = {'id': 'pay_set', 'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_set'}}

    first, q1 = _settle(table, payment=payment, provider=(True, 10000, 'INR'))
    assert first.status == bc.SETTLE_SETTLED
    assert first.amount_paise == 10000
    assert q1 == []
    record = order_keys.resolve_contribution(table, 'c_set')
    assert record['state'] == 'CAPTURED'
    assert record['providerPaymentId'] == 'pay_set'

    # Replay of the SAME payment id settles exactly once more: a duplicate, not a second credit.
    second, _ = _settle(table, payment=payment, provider=(True, 10000, 'INR'))
    assert second.status == bc.SETTLE_DUPLICATE


def test_webhook_notes_amount_is_not_authority():
    """REVERT-CHECK: fails if the notes-not-authority guard is reverted.

    The event notes carry a FORGED amount (990000 paise = ₹9900) but the stored contribution is
    10000 paise (₹100). The settlement must re-derive the amount from the STORED record and verify
    the provider's captured amount against THAT - so a provider capture of 10000 settles, and the
    forged notes amount is ignored. If someone reverts to trusting notes['amount'], the provider's
    10000 would mismatch the forged 990000 and this settle would quarantine instead of settling.
    """
    table = _keys()
    order_keys.reserve_contribution(
        table, contribution_id='c_forge', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_forge')
    payment = {'id': 'pay_forge', 'amount': 990000,  # forged event-body amount
               'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_forge',
                         'amount': 990000, 'amountPaise': 990000}}
    # The authoritative provider readback reports the REAL captured amount: 10000 paise.
    result, quarantined = _settle(table, payment=payment, provider=(True, 10000, 'INR'))
    assert result.status == bc.SETTLE_SETTLED
    assert result.amount_paise == 10000  # from the stored record, not the forged notes
    assert quarantined == []
    assert order_keys.resolve_contribution(table, 'c_forge')['settledAmountPaise'] == 10000


def test_webhook_provider_amount_mismatch_quarantines():
    table = _keys()
    order_keys.reserve_contribution(
        table, contribution_id='c_mm', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_mm')
    payment = {'id': 'pay_mm', 'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_mm'}}
    # Money moved, but for a different amount than the stored record -> quarantine, do not settle.
    result, quarantined = _settle(table, payment=payment, provider=(True, 25000, 'INR'))
    assert result.status == bc.SETTLE_QUARANTINED
    assert quarantined == [('c_mm', 'pay_mm')]
    assert order_keys.resolve_contribution(table, 'c_mm')['state'] == 'INITIATED'


def test_webhook_unknown_contribution_quarantines():
    table = _keys()
    payment = {'id': 'pay_unk', 'notes': {'purpose': 'BLOG_CONTRIBUTION',
                                          'contributionId': 'c_does_not_exist'}}
    result, quarantined = _settle(table, payment=payment, provider=(True, 10000, 'INR'))
    assert result.status == bc.SETTLE_QUARANTINED
    assert quarantined == [('c_does_not_exist', 'pay_unk')]


def test_webhook_not_captured_quarantines():
    table = _keys()
    order_keys.reserve_contribution(
        table, contribution_id='c_nc', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_nc')
    payment = {'id': 'pay_nc', 'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_nc'}}
    result, quarantined = _settle(table, payment=payment, provider=(False, 0, ''))
    assert result.status == bc.SETTLE_QUARANTINED
    assert quarantined == [('c_nc', 'pay_nc')]


def test_webhook_settlement_creates_no_order_identity():
    # A contribution capture must NOT create a Wix Store product/order or mint a public order
    # number. Settling writes ONLY the contribution record and the settlement claim - no
    # PAYMENTATTEMPT# order claim, no ORDERNO# reservation.
    table = _keys()
    order_keys.reserve_contribution(
        table, contribution_id='c_noorder', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_noorder')
    payment = {'id': 'pay_noorder',
               'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_noorder'}}
    result, _ = _settle(table, payment=payment, provider=(True, 10000, 'INR'))
    assert result.status == bc.SETTLE_SETTLED
    # No order identity of any kind was minted for this contribution.
    assert order_keys.resolve_order_for_payment(table, 'att_noorder') is None
    keys = list(getattr(table, 'rows', {}).keys())
    assert not any(k.startswith(order_keys.PAYMENT_ATTEMPT_PREFIX) for k in keys)
    assert not any(k.startswith(order_keys.ORDER_NUMBER_PREFIX) for k in keys)


# ── the real webhook handler routes a contribution capture ──────────────────────

def test_real_webhook_handler_routes_blog_contribution_and_settles():
    """Drive the ACTUAL razorpay-webhook handler: a captured BLOG_CONTRIBUTION settles the record
    and creates no invoice/order side effect."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                          / 'amplify/functions/payments/razorpay-webhook'))
    import handler as webhook  # noqa: E402

    fake = FakeDynamo({KEYS_TABLE: 'orderId'})
    table = fake.Table(KEYS_TABLE)
    order_keys.reserve_contribution(
        table, contribution_id='c_handler', post_id=POST_ID, slug=SLUG, amount_paise=10000,
        payment_attempt_id='att_handler')

    # Point the handler's dynamodb + commerce-keys table at our fake, and stub the capture readback.
    webhook.dynamodb = fake
    import lambda_utils.ecommerce.order_keys as ok
    original_table_name = ok.commerce_keys_table_name
    ok.commerce_keys_table_name = lambda: KEYS_TABLE
    from lambda_utils.integrations import razorpay_verify
    original_pic = razorpay_verify.payment_is_captured
    razorpay_verify.payment_is_captured = lambda pid: (True, 10000, 'INR')
    try:
        payment = {'id': 'pay_handler', 'amount': 990000,  # forged body amount, ignored
                   'notes': {'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'c_handler'}}
        webhook._handle_payment_captured({'payment': {'entity': payment}}, 'req-1')
    finally:
        ok.commerce_keys_table_name = original_table_name
        razorpay_verify.payment_is_captured = original_pic

    record = order_keys.resolve_contribution(table, 'c_handler')
    assert record['state'] == 'CAPTURED'
    assert record['settledAmountPaise'] == 10000  # from the stored record, not the forged body
