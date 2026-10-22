"""The SETTLE leg: the binding comes from Meta, and paid state actually gets written.

Two defects this file pins, both of which a reader would otherwise have to take on trust.

**The binding.** `razorpay_verify.verifier_for_event` refuses an attempt with no
`providerOrderId`/`providerPaymentId` - "a webhook must not supply its own binding" - and on this
leg Meta creates the gateway order, so there is nothing to bind at send time. The binding
therefore comes from an authenticated Meta lookup, which is a SECOND INDEPENDENT AUTHORITY. The
test that matters is the negative one: an event naming a different gateway order than Meta
reports must not bind. The webhook signing secret is in this repository's git history, so a
signature proves only that somebody read it.

**The paid state.** `reconcile_payment` synthesises `{**attempt, 'status': PAYMENT_PAID}` for its
eligibility check and writes nothing back, so a paid native attempt sat in `IN_FLIGHT_STATES`
forever with no verified-amount evidence - and the monotonic ladder cited as protecting this leg
was vacuous, because nothing moved the row forward for it to refuse.

The subtle part is the GATE. `verified_captured_paise` defaults to 0 and is omitted on three
paths that report `has_order`, so gating on `has_order` alone fires an ERROR-level evidence
conflict on every ordinary redelivery - and can store ZERO as the authoritative verified amount.
Both directions are tested here.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils import payment_status  # noqa: E402
from lambda_utils.ecommerce import order_keys, payment_attempt  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402
from lambda_utils.integrations import meta_payment_binding as mpb  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

KEYS = 'stack-wecare-digital-CommerceKeys'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'

REFERENCE = 'WD-PAY-SETTLE01'
ATTEMPT = '01930000-0000-7000-8000-0000000000aa'
GATEWAY_ORDER = 'order_META_NATIVE_1'
PAYMENT = 'pay_META_NATIVE_1'
AMOUNT = 59900
INVOICE_ID = 'inv-settle-0001'
WABA1 = wpr.PHONE_NUMBER_ID_1


@pytest.fixture
def webhook():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, WEBHOOK_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


@pytest.fixture
def fake():
    return FakeDynamo(keys={KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'})


def _seed_native(fake, *, amount=AMOUNT, mode=None, bound=False):
    """A `PAYREF#` row and attempt as the send leg would have reserved them."""
    row = {'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE,
           'kind': 'PAYMENT_REFERENCE', 'referenceId': REFERENCE,
           'paymentAttemptId': ATTEMPT, 'customerId': 'contact-1',
           'amountPaise': amount, 'payablePaise': amount, 'currency': 'INR',
           'checkoutMode': wpr.WA_NATIVE_CHECKOUT_MODE if mode is None else mode,
           'channel': 'whatsapp', 'configurationName': 'WECAREDIGITAL',
           'phoneId': WABA1, 'wabaId': '2094615664435155', 'invoiceId': INVOICE_ID,
           'reservedAt': 1770000000}
    if bound:
        row['providerOrderId'] = GATEWAY_ORDER
    fake.Table(KEYS).put_item(Item=row)
    attempt = payment_attempt.build(
        customer_id='contact-1', reference_id=REFERENCE, amount_paise=amount,
        configuration_name='WECAREDIGITAL', payment_attempt_id=ATTEMPT, now=1770000000)
    attempt = payment_attempt.transition(
        attempt, payment_attempt.PAYMENT_REQUEST_SENT, now=1770000001)
    attempt.update(checkoutMode=wpr.WA_NATIVE_CHECKOUT_MODE, channel='whatsapp',
                   invoiceId=INVOICE_ID, sendStatus='SENT')
    fake.Table(ATTEMPTS).put_item(Item=attempt)
    return attempt


class _MetaLookup:
    """A recording stand-in for the Graph seam, so "how many lookups" is countable."""

    def __init__(self, payments=None, raises=None):
        self.calls = []
        self.payments = payments if payments is not None else [
            {'status': 'captured', 'provider_order_id': GATEWAY_ORDER,
             'provider_payment_id': PAYMENT}]
        self.raises = raises

    def __call__(self, request, timeout=None):
        self.calls.append(getattr(request, 'full_url', str(request)))
        if self.raises:
            raise self.raises
        body = json.dumps({'payments': self.payments}).encode()

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def read(self_inner):
                return body

        return _Resp()


def _run(webhook, fake, *, verifier, lookup=None, payment=None):
    """Drive `_create_order_for_captured_payment` with storage, the provider and Meta injected."""
    payload = payment or {'id': PAYMENT, 'order_id': GATEWAY_ORDER, 'amount': AMOUNT,
                          'currency': 'INR', 'status': 'captured'}
    lookup = lookup or _MetaLookup()
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.side_effect = fake.Table
        with patch.object(webhook, 'PAYMENT_ATTEMPTS_TABLE', ATTEMPTS), \
             patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS), \
             patch('lambda_utils.ecommerce.order_keys.commerce_keys_table_name',
                   return_value=KEYS), \
             patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier), \
             patch('urllib.request.urlopen', lookup), \
             patch.object(mpb, '_default_load_token', return_value='TOKEN'):
            result = webhook._create_order_for_captured_payment(payload, REFERENCE, 'req-1')
    return result, lookup


def _attempt(fake):
    return fake.tables[ATTEMPTS][ATTEMPT]


def _order_numbers(fake):
    return [k for k in fake.tables[KEYS] if str(k).startswith(order_keys.ORDER_NUMBER_PREFIX)]


# ══════════════════════════════════════════════════════════════════════════════
# the binding
# ══════════════════════════════════════════════════════════════════════════════

def test_a_native_capture_creates_exactly_one_order(webhook, fake):
    """T-T1. The whole drive: an unbound native attempt, bound from Meta, then reconciled."""
    _seed_native(fake)
    result, lookup = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    assert result['outcome'] == 'ORDER_CREATED', result
    assert result['hasOrder'] is True
    assert order_keys.is_public_order_number(result['orderNumber'])
    assert len(_order_numbers(fake)) == 1
    assert len(lookup.calls) == 1


def test_the_binding_lands_on_the_payref_row(webhook, fake):
    """T-T19. On the row `_load_attempt` already reads and the website leg already binds. A
    second home for this field is a second answer to "is this capture ours"."""
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    payref = fake.tables[KEYS][order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE]
    assert payref['providerOrderId'] == GATEWAY_ORDER
    assert payref['bindingSource'] == 'META_LOOKUP'
    # and NOT on the attempt row, which would be the divergent second home.
    assert 'providerOrderId' not in _attempt(fake)


def test_the_reverse_uniqueness_row_is_written(webhook, fake):
    """T-T4's first half. One gateway order may be claimed by exactly one attempt, and only
    `GATEWAYORDER#` can see that direction."""
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    bound = order_keys.resolve_gateway_order(fake.Table(KEYS), GATEWAY_ORDER)
    assert bound['paymentAttemptId'] == ATTEMPT


def test_one_gateway_order_cannot_be_claimed_by_two_attempts(fake):
    """T-T4. The mirror case the reference binding cannot see."""
    order_keys.bind_gateway_order(
        fake.Table(KEYS), gateway_order_id=GATEWAY_ORDER,
        payment_attempt_id='a-different-attempt', request_key='', amount_paise=AMOUNT,
        account_key_id='', account_mode='')
    fake.Table(KEYS).put_item(Item={'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE,
                                    'referenceId': REFERENCE, 'paymentAttemptId': ATTEMPT})
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.bind_attempt(fake.Table(KEYS), reference_id=REFERENCE, phone_number_id=WABA1,
                         config_name='WECAREDIGITAL', payment_attempt_id=ATTEMPT,
                         amount_paise=AMOUNT, now=1770000002,
                         urlopen=_MetaLookup(), load_token=lambda: 'TOKEN')


def test_the_binding_comes_from_meta_not_the_event(webhook, fake):
    """T-T2, and the most important negative test on this leg.

    The event names `order_FORGED`; Meta names `order_META_NATIVE_1`. The binding written is
    Meta's, and the verifier then refuses the event's own id - so a forged, signature-valid
    event cannot name its own gateway order.
    """
    _seed_native(fake)
    result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'),
                     payment={'id': PAYMENT, 'order_id': 'order_FORGED',
                              'amount': AMOUNT, 'currency': 'INR'})
    payref = fake.tables[KEYS][order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE]
    assert payref['providerOrderId'] == GATEWAY_ORDER
    assert payref['providerOrderId'] != 'order_FORGED'


def test_a_redelivery_after_a_successful_bind_makes_no_graph_call(webhook, fake):
    """The external-call count must not grow with redelivery count."""
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    _result, lookup2 = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    assert lookup2.calls == []


def test_the_website_leg_makes_no_meta_lookup(webhook, fake):
    """T-T12. The website leg already has a binding from its own order create; it must not
    acquire a Meta lookup. The gate is on `checkoutMode`, which selects a binding SOURCE."""
    _seed_native(fake, mode='WEBSITE_RAZORPAY_STANDARD', bound=True)
    _result, lookup = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    assert lookup.calls == []


def test_meta_status_is_compared_canonically(fake):
    """T-T10. Meta answering `paid` against a raw `captured` comparison was recorded as
    REJECTED_MISMATCH once already - it rejected real money."""
    for ok in ('captured', 'paid'):
        found = mpb.lookup_payment(
            reference_id=REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
            urlopen=_MetaLookup(payments=[{'status': ok,
                                           'provider_order_id': GATEWAY_ORDER}]),
            load_token=lambda: 'TOKEN')
        assert found['gatewayOrderId'] == GATEWAY_ORDER
    for refused in ('authorized', 'created', 'nonsense', ''):
        with pytest.raises(mpb.MetaBindingUnavailable):
            mpb.lookup_payment(
                reference_id=REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
                urlopen=_MetaLookup(payments=[{'status': refused,
                                               'provider_order_id': GATEWAY_ORDER}]),
                load_token=lambda: 'TOKEN')


def test_meta_nested_transactions_supply_gateway_binding():
    found = mpb.lookup_payment(
        reference_id=REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
        urlopen=_MetaLookup(payments=[{'reference_id': REFERENCE,
            'transactions': [{'status': 'success', 'id': PAYMENT,
                'payment_gateway': {'order_id': GATEWAY_ORDER, 'payment_id': PAYMENT}}]}]),
        load_token=lambda: 'TOKEN')
    assert found['gatewayOrderId'] == GATEWAY_ORDER
    assert found['gatewayPaymentId'] == PAYMENT


# ──────────────────────────────────────────────────────────────────────────────
# The native live shape, captured verbatim from the WD-PAY-C98523E305EE4747 incident.
#
# At 03:08:35Z Razorpay delivered payment.captured correctly, but the parser read neither
# `pg_transaction_id` nor `id` as the Razorpay ORDER id for this shape, extracted no gateway
# order id, and ended PROVIDER_UNAVAILABLE / NEEDS_RECONCILIATION on a REAL, CAPTURED ₹2.24
# payment. Meta's own lookup returned top-level status CAPTURED with transactions[0] carrying the
# order id at `id` (order_ prefix) and the payment id at `pg_transaction_id` (pay_ prefix).
# ──────────────────────────────────────────────────────────────────────────────

LIVE_REFERENCE = 'WD-PAY-C98523E305EE4747'
LIVE_GATEWAY_ORDER = 'order_Tq0ZgogHP8upGD'
LIVE_PAYMENT = 'pay_Tq0awsJn5nCvE8'


def test_meta_native_live_shape_binds_from_prefixed_transaction_fields():
    """The exact owner-confirmed captured response for WD-PAY-C98523E305EE4747. The order id is
    at transactions[0].id (order_ prefix) and the payment id at transactions[0].pg_transaction_id
    (pay_ prefix); the top-level entry status is CAPTURED and the transaction status 'success'."""
    found = mpb.lookup_payment(
        reference_id=LIVE_REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
        urlopen=_MetaLookup(payments=[{'reference_id': LIVE_REFERENCE, 'status': 'CAPTURED',
            'transactions': [{'id': LIVE_GATEWAY_ORDER, 'pg_transaction_id': LIVE_PAYMENT,
                              'status': 'success'}]}]),
        load_token=lambda: 'TOKEN')
    assert found['gatewayOrderId'] == LIVE_GATEWAY_ORDER
    assert found['gatewayPaymentId'] == LIVE_PAYMENT
    assert found['status'] == payment_status.CAPTURED


def test_meta_native_live_shape_with_two_distinct_bindings_still_raises():
    """Two distinct captured bindings is a reconciliation incident; the parser must RAISE rather
    than arbitrarily pick the first - the de-dupe only collapses identical tuples."""
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.lookup_payment(
            reference_id=LIVE_REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
            urlopen=_MetaLookup(payments=[{'reference_id': LIVE_REFERENCE, 'status': 'CAPTURED',
                'transactions': [
                    {'id': LIVE_GATEWAY_ORDER, 'pg_transaction_id': LIVE_PAYMENT,
                     'status': 'success'},
                    {'id': 'order_OTHER9999999999', 'pg_transaction_id': 'pay_OTHER9999999999',
                     'status': 'success'}]}]),
            load_token=lambda: 'TOKEN')


def test_meta_native_live_shape_non_captured_status_still_raises():
    """A non-captured transaction status in the live shape is not a confirmation; refuse."""
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.lookup_payment(
            reference_id=LIVE_REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
            urlopen=_MetaLookup(payments=[{'reference_id': LIVE_REFERENCE, 'status': 'CAPTURED',
                'transactions': [{'id': LIVE_GATEWAY_ORDER, 'pg_transaction_id': LIVE_PAYMENT,
                                  'status': 'pending'}]}]),
            load_token=lambda: 'TOKEN')


def test_meta_does_not_adopt_a_different_reference():
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.lookup_payment(
            reference_id=REFERENCE, phone_number_id=WABA1, config_name='WECAREDIGITAL',
            urlopen=_MetaLookup(payments=[{'reference_id': 'OTHER', 'status': 'captured',
                'provider_order_id': GATEWAY_ORDER}]), load_token=lambda: 'TOKEN')


@pytest.mark.parametrize('payments', [[], [{'status': 'captured'}]])
def test_an_unusable_meta_answer_never_asserts_not_paid(payments, fake):
    """`MetaBindingUnavailable` means WE DO NOT KNOW. `reconcile_payment` turns that into
    PROVIDER_UNAVAILABLE rather than an order, and Razorpay's redelivery is the recovery."""
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.lookup_payment(reference_id=REFERENCE, phone_number_id=WABA1,
                           config_name='WECAREDIGITAL',
                           urlopen=_MetaLookup(payments=payments),
                           load_token=lambda: 'TOKEN')


def test_an_empty_config_name_refuses_before_any_call(fake):
    """A reserved attempt must always carry one, so an absent value is a fault rather than a
    reason to guess."""
    lookup = _MetaLookup()
    with pytest.raises(mpb.MetaBindingUnavailable):
        mpb.lookup_payment(reference_id=REFERENCE, phone_number_id=WABA1, config_name='',
                           urlopen=lookup, load_token=lambda: 'TOKEN')
    assert lookup.calls == []


def test_an_unbound_attempt_fails_closed(webhook, fake):
    """T-T5. Meta unavailable -> no binding -> no order, no invoice."""
    from lambda_utils.integrations import razorpay_verify
    _seed_native(fake)

    def _refuse(_ref):
        raise razorpay_verify.RazorpayUnavailable('no binding')

    result, _ = _run(webhook, fake, verifier=_refuse,
                     lookup=_MetaLookup(raises=OSError('timeout')))
    assert result['hasOrder'] is False
    assert _order_numbers(fake) == []


def test_the_binding_module_only_makes_get_requests():
    """T-C6. AST over the module: nothing here can be a write to a provider."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(mpb))
    methods = [kw.value.value for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               for kw in node.keywords
               if kw.arg == 'method' and isinstance(kw.value, ast.Constant)]
    assert methods, 'no explicit request method found; the gate would be vacuous'
    assert set(methods) == {'GET'}


# ══════════════════════════════════════════════════════════════════════════════
# paid state, and the evidence gate
# ══════════════════════════════════════════════════════════════════════════════

def test_a_paid_native_attempt_is_not_in_flight(webhook, fake):
    """T-T15, and the one that fails without the `record_paid` call.

    `PAYMENT_READINESS_CHECKED` is a member of `IN_FLIGHT_STATES`, whose own comment says what
    that means: "a retry here would produce a second payable request for one basket". A PAID
    attempt reading as in-flight is the state most likely to produce exactly that.
    """
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    attempt = _attempt(fake)
    assert attempt['status'] == payment_attempt.PAYMENT_PAID
    assert attempt['attemptRank'] == 100
    assert payment_attempt.is_in_flight(attempt) is False


def test_the_verified_capture_amount_is_stored_and_is_the_providers_figure(webhook, fake):
    """T-T16. It is the PROVIDER's readback, never `amountPaise`: passing the expectation in
    place of the evidence would make the stored evidence unfalsifiable."""
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    attempt = _attempt(fake)
    assert attempt['verifiedCapturedPaise'] == AMOUNT
    assert isinstance(attempt['verifiedCapturedPaise'], int)
    assert attempt['verifiedProviderPaymentId'] == PAYMENT


def test_an_ordinary_redelivery_logs_no_evidence_conflict(webhook, fake, caplog):
    """THE GATE, and the reason it is not just `has_order`.

    `verified_captured_paise` defaults to 0 and is omitted on the idempotent short-circuit, which
    is what EVERY redelivery takes. Gating on `has_order` alone would call `record_paid` with 0,
    its nested condition would fail against the stored real amount, and we would log at ERROR
    that two verified amounts disagree - when nothing is wrong.
    """
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    before = dict(_attempt(fake))

    with caplog.at_level(logging.INFO):
        result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    assert result['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert 'native_attempt_paid_evidence_conflict' not in caplog.text
    assert 'native_attempt_paid_evidence_already_recorded' in caplog.text
    # The stored evidence is UNCHANGED, and in particular is not zero.
    after = _attempt(fake)
    assert after['verifiedCapturedPaise'] == before['verifiedCapturedPaise'] == AMOUNT


def test_zero_is_never_stored_as_the_authoritative_verified_amount(webhook, fake, caplog):
    """The second half of the same defect, and the worse one.

    `record_paid` ACCEPTS zero deliberately (a fully gift-card-funded order has no Razorpay leg).
    So if the first processed delivery landed on a path reporting `has_order` with no readback,
    zero would become the authoritative evidence and the later CORRECT amount would then be
    refused by the same condition. The gate requires a positive verified figure, so this cannot
    happen.
    """
    _seed_native(fake)
    # An outcome with `has_order` but no provider readback: `ORDER_ALREADY_EXISTS` from a
    # pre-existing claim, which short-circuits before the provider is contacted.
    order_keys.claim_order_for_payment(
        fake.Table(KEYS), payment_attempt_id=ATTEMPT, order_id=order_keys.new_order_id(),
        provider_transaction_id=PAYMENT, extra={'referenceId': REFERENCE})
    order_keys.record_order_number_on_claim(
        fake.Table(KEYS), payment_attempt_id=ATTEMPT, order_number='WD-ORD-ABCD2345')

    with caplog.at_level(logging.INFO):
        result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))

    assert result['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert 'verifiedCapturedPaise' not in _attempt(fake)
    assert 'native_attempt_paid_evidence_conflict' not in caplog.text


def test_a_replay_with_a_different_amount_is_refused_by_record_paid(webhook, fake, caplog):
    """T-T17, restated so it is distinguishable from an ordinary redelivery.

    Two FRESH `ORDER_CREATED` outcomes with two different provider amounts - not a redelivery.
    `record_paid`'s condition nests the two evidence fields deliberately, so a second delivery
    agreeing on the provider id but NOT on the amount is refused by the DATABASE.
    """
    from lambda_utils.ecommerce import finalization
    attempt = _seed_native(fake)
    finalization.record_paid(fake.Table(ATTEMPTS), attempt, PAYMENT, AMOUNT)
    assert _attempt(fake)['verifiedCapturedPaise'] == AMOUNT

    with pytest.raises(Exception):
        finalization.record_paid(fake.Table(ATTEMPTS), attempt, PAYMENT, AMOUNT + 1)
    # The stored evidence did not move.
    assert _attempt(fake)['verifiedCapturedPaise'] == AMOUNT


def test_accept_paid_still_refuses_a_native_attempt(fake):
    """T-T18, H7's boundary. Adding `record_paid` must NOT open the website finalization path: a
    native attempt has no cart, so `accept_paid` has to keep raising."""
    from lambda_utils.ecommerce import finalization
    attempt = _seed_native(fake)
    assert wpr.WA_NATIVE_CHECKOUT_MODE not in finalization.ACCEPTED_CHECKOUT_MODES
    with pytest.raises(ValueError, match='verified standalone order identity required'):
        finalization.accept_paid(
            attempts=fake.Table(ATTEMPTS), orders=fake.Table(KEYS), keys=fake.Table(KEYS),
            attempt=attempt, outcome={'hasOrder': True, 'providerPaymentId': PAYMENT},
            verified_captured_paise=AMOUNT)


# ══════════════════════════════════════════════════════════════════════════════
# money: exact paise, fail closed
# ══════════════════════════════════════════════════════════════════════════════

def test_a_one_paise_mismatch_creates_no_order_and_no_invoice(webhook, fake, caplog):
    """T-T6. Exact integer equality, both sides integers, no tolerance. ONE paise is a mismatch,
    and the customer is never asked to pay again."""
    _seed_native(fake, amount=AMOUNT)
    with caplog.at_level(logging.ERROR):
        result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT + 1, 'INR'))

    assert result['outcome'] == 'AMOUNT_MISMATCH'
    assert result['hasOrder'] is False
    assert result['needsHuman'] is True
    assert _order_numbers(fake) == []
    assert 'PAID_BUT_NO_ORDER' in caplog.text
    # No paid state was written either.
    assert _attempt(fake)['status'] != payment_attempt.PAYMENT_PAID


def test_a_currency_mismatch_is_decided_before_the_amount(webhook, fake):
    """T-T8. A currency mismatch makes the amount comparison meaningless rather than merely
    wrong, so it is decided first and INR is compared explicitly on both sides."""
    _seed_native(fake)
    result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT + 1, 'USD'))
    assert result['outcome'] == 'CURRENCY_MISMATCH'


def test_the_customer_is_never_offered_a_retry_on_a_blocked_outcome(webhook, fake):
    """The money is already taken, so a retry CTA would charge twice."""
    from lambda_utils.ecommerce import order_creation
    _seed_native(fake)
    result, _ = _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT + 1, 'INR'))
    assert result['outcome'] in order_creation.PAID_BUT_BLOCKED_OUTCOMES
    attempt = _attempt(fake)
    with pytest.raises(payment_attempt.IllegalTransition):
        payment_attempt.next_retry(attempt, reference_id='WD-PAY-OTHER01',
                                   amount_paise=AMOUNT, configuration_name='WECAREDIGITAL')


# ══════════════════════════════════════════════════════════════════════════════
# monotonicity
# ══════════════════════════════════════════════════════════════════════════════

def test_a_late_failure_cannot_move_a_paid_attempt_backwards(webhook, fake):
    """`PAYMENT_PAID` outranks every failure deliberately: a late `failed` landing after a
    capture is the transition that would tell a paying customer their payment did not work."""
    _seed_native(fake)
    _run(webhook, fake, verifier=lambda _r: (True, PAYMENT, AMOUNT, 'INR'))
    attempt = _attempt(fake)
    with pytest.raises(payment_attempt.IllegalTransition):
        payment_attempt.transition(attempt, payment_attempt.PAYMENT_FAILED)
    with pytest.raises(payment_attempt.IllegalTransition):
        payment_attempt.transition(attempt, payment_attempt.PAYMENT_REQUEST_SENT)


def test_the_request_sent_advance_is_refused_once_paid(fake):
    """A redelivered send-completion arriving after a capture is refused by the CONDITION, not by
    application logic - which is what makes it correct under concurrency."""
    attempt = _seed_native(fake)
    from lambda_utils.ecommerce import finalization
    finalization.record_paid(fake.Table(ATTEMPTS), attempt, PAYMENT, AMOUNT)
    assert wpr.record_sent(fake.Table(ATTEMPTS), payment_attempt_id=ATTEMPT,
                           now=1770000009) is False
    assert fake.tables[ATTEMPTS][ATTEMPT]['status'] == payment_attempt.PAYMENT_PAID


# ══════════════════════════════════════════════════════════════════════════════
# settlement and payout: integer paise, and they finalize nothing
# ══════════════════════════════════════════════════════════════════════════════

def test_settlement_records_integer_paise_and_finalizes_nothing(webhook, fake, caplog):
    """T-T13. A settlement is the BANK TRANSFER of money already captured. The money became ours
    at `payment.captured`, so this must write a record and touch no order, invoice or message."""
    payments_table = 'stack-wecare-digital-PaymentsTable'
    store = FakeDynamo(keys={payments_table: 'id'})
    with patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'PAYMENTS_TABLE', payments_table):
        ddb.Table.side_effect = store.Table
        with caplog.at_level(logging.INFO):
            webhook._handle_settlement(
                'settlement.processed',
                {'settlement': {'entity': {'id': 'setl_1', 'amount': 1234567,
                                           'currency': 'INR', 'status': 'processed'}}},
                'req-s')

    row = store.tables[payments_table]['SETTLEMENT#setl_1']
    assert int(row['amountPaise']) == 1234567
    assert row['recordType'] == 'SETTLEMENT'
    assert 'customerId' not in row
    assert '"amountPaise": 1234567' in caplog.text
    assert '"amountRupees": "12345.67"' in caplog.text


def test_a_settlement_redelivery_is_a_no_op(webhook):
    payments_table = 'stack-wecare-digital-PaymentsTable'
    store = FakeDynamo(keys={payments_table: 'id'})
    event = {'settlement': {'entity': {'id': 'setl_2', 'amount': 500,
                                       'currency': 'INR', 'status': 'processed'}}}
    with patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'PAYMENTS_TABLE', payments_table):
        ddb.Table.side_effect = store.Table
        webhook._handle_settlement('settlement.processed', event, 'req-1')
        webhook._handle_settlement('settlement.processed', event, 'req-2')
    assert store.count(payments_table) == 1


def test_a_settlement_in_another_currency_writes_nothing(webhook, caplog):
    """T-T14. Compared explicitly, never inferred from the amount."""
    payments_table = 'stack-wecare-digital-PaymentsTable'
    store = FakeDynamo(keys={payments_table: 'id'})
    with patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'PAYMENTS_TABLE', payments_table):
        ddb.Table.side_effect = store.Table
        with caplog.at_level(logging.ERROR):
            webhook._handle_settlement(
                'settlement.processed',
                {'settlement': {'entity': {'id': 'setl_3', 'amount': 100,
                                           'currency': 'USD'}}},
                'req-x')
    assert store.count(payments_table) == 0
    assert 'settlement_currency_unexpected' in caplog.text


def test_payout_reports_integer_paise(webhook, caplog):
    """A payout is money LEAVING the business account. It has no order at all, so the only
    correctness question is the arithmetic."""
    with caplog.at_level(logging.INFO):
        webhook._handle_payout_event(
            'payout.processed',
            {'payout': {'entity': {'id': 'pout_1', 'amount': 9999, 'status': 'processed'}}},
            'req-p')
    assert '"amountPaise": 9999' in caplog.text
    assert '"amountRupees": "99.99"' in caplog.text


def test_recovery_rejects_every_http_envelope_even_empty(webhook, monkeypatch):
    for key in ('requestContext','rawPath','path','httpMethod','headers','body'):
        response=webhook.handler({'internalAction':'recoverPaidInvoiceOrder','referenceId':REFERENCE,key:{}},None)
        assert response['statusCode']==403


def test_private_recovery_uses_saved_projection_only(webhook,monkeypatch):
    from lambda_utils.ecommerce import paid_invoice_order
    called=[]
    def project(**kwargs):
        called.append(kwargs['reference_id'])
        return {'orderId':'existing-order','orderNumber':'WD-ORD-ABCD2345','finalizationStage':'NEEDS_CUSTOMER_LINK'}
    monkeypatch.setattr(paid_invoice_order,'materialize',project)
    result=webhook.handler({'internalAction':'recoverPaidInvoiceOrder','referenceId':REFERENCE},None)
    assert result['orderId']=='existing-order'
    assert called==[REFERENCE]


def test_scheduled_reconciliation_uses_the_saved_contact_linker(webhook, monkeypatch):
    from unittest.mock import Mock

    from lambda_utils.ecommerce import customer_order_link

    metrics = {
        'promoted': 3,
        'pendingRemaining': 2,
        'oldestPendingAgeSeconds': 91,
        'failures': 1,
    }
    reconcile_metrics = Mock(return_value=metrics)
    emit_metrics = Mock()
    webhook.dynamodb.Table.return_value.scan.side_effect = AssertionError(
        'Unexpected DynamoDB scan; stub the reconciliation helper')
    monkeypatch.setattr(customer_order_link, 'reconcile_metrics', reconcile_metrics)
    monkeypatch.setattr(webhook, '_emit_reconciliation_metrics', emit_metrics)

    assert webhook.handler({'internalAction': 'reconcileCustomerOrderLinks'}, None) == {
        'linkedOrders': 3, **metrics,
    }
    reconcile_metrics.assert_called_once_with(
        orders=webhook.dynamodb.Table.return_value,
        contacts=webhook.dynamodb.Table.return_value,
        attempts=webhook.dynamodb.Table.return_value)
    emit_metrics.assert_called_once_with(metrics, 'local')

    assert webhook.handler({
        'internalAction': 'reconcileCustomerOrderLinks', 'requestContext': {},
    }, None)['statusCode'] == 403
    reconcile_metrics.assert_called_once()
    emit_metrics.assert_called_once()
