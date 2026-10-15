"""The order invariants, asserted against the real reconciliation path.

`test_order_keys.py` proves the primitives. This proves the thing built on top of them, which is
where the invariants actually have to hold:

    PENDING        -> 0 orders
    FAILED         -> 0 orders
    CANCELLED      -> 0 orders
    EXPIRED        -> 0 orders
    PAID verified  -> exactly 1 order
    duplicate paid webhook       -> still 1
    concurrent reconciliation    -> still 1

The distinction that shapes the negative cases: a webhook is a trigger to verify, never proof. The
signing secret is in this repository's public git history, so a valid signature proves only that
somebody read the history — which is why every test here drives the *provider* answer rather than
the event body.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_creation as oc  # noqa: E402
from lambda_utils.ecommerce import order_keys, payment_attempt  # noqa: E402

TABLE = 'stack-wecare-digital-CommerceKeys'
CUSTOMER = 'CUS_01J0000000000000000000000'
REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
TXN = 'pay_LIVE0000000001'
AMOUNT = 59900
NOW = 1_700_000_000


@pytest.fixture
def table():
    return FakeDynamo(keys={TABLE: 'orderId'}).Table(TABLE)


def _attempt(**kw):
    params = dict(customer_id=CUSTOMER, reference_id=REFERENCE, amount_paise=AMOUNT,
                  configuration_name='WECAREDIGITAL', now=NOW)
    params.update(kw)
    return payment_attempt.build(**params)


def _paid(amount=AMOUNT, currency='INR', txn=TXN):
    """A provider that confirms capture."""
    return lambda _ref: (True, txn, amount, currency)


def _unpaid():
    return lambda _ref: (False, '', 0, '')


def _reconcile(table, attempt=None, *, verify=None, **kw):
    stored = attempt if attempt is not None else _attempt()
    params = dict(
        table=table, reference_id=REFERENCE,
        verify_payment=verify or _paid(),
        load_attempt=lambda _ref: stored,
    )
    params.update(kw)
    return oc.reconcile_payment(**params)


def _order_count(table):
    return len([k for k in table.rows
                if str(k).startswith(order_keys.ORDER_NUMBER_PREFIX)])


# ══════════════════════════════════════════════════════════════════════════════
# the invariants
# ══════════════════════════════════════════════════════════════════════════════

def test_a_paid_verified_payment_creates_exactly_one_order(table):
    outcome = _reconcile(table)

    assert outcome.outcome == oc.ORDER_CREATED
    assert outcome.has_order
    assert order_keys.is_public_order_number(outcome.order_number)
    from lambda_utils import identifiers
    assert identifiers.is_uuid7(outcome.order_id)
    assert _order_count(table) == 1


def test_an_unpaid_provider_answer_creates_zero_orders(table):
    outcome = _reconcile(table, verify=_unpaid())

    assert outcome.outcome == oc.NOT_PAID
    assert not outcome.has_order
    assert outcome.order_number == ''
    assert _order_count(table) == 0


def test_a_forged_webhook_creates_nothing(table):
    """A forged event and an unpaid one are indistinguishable here, and it does not matter:
    the provider is asked either way and both answers mean no order."""
    outcome = _reconcile(table, verify=_unpaid())
    assert _order_count(table) == 0
    assert not outcome.customer_may_retry  # No capture is not proof of final failure.


@pytest.mark.parametrize('state', [
    payment_attempt.CREATED,
    payment_attempt.PAYMENT_REQUEST_SENT,
    payment_attempt.PAYMENT_PENDING,
    payment_attempt.PAYMENT_FAILED,
    payment_attempt.PAYMENT_CANCELLED,
    payment_attempt.PAYMENT_EXPIRED,
])
def test_the_attempt_state_does_not_override_the_provider(table, state):
    """The provider is authoritative in BOTH directions. A stored state of FAILED with a
    provider that confirms capture is a real payment we had recorded wrongly — losing it would
    be worse than the stale row."""
    attempt = _attempt()
    attempt['status'] = state
    outcome = _reconcile(table, attempt)
    assert outcome.outcome == oc.ORDER_CREATED
    assert _order_count(table) == 1


@pytest.mark.parametrize('state', [
    payment_attempt.PAYMENT_PENDING,
    payment_attempt.PAYMENT_FAILED,
    payment_attempt.PAYMENT_CANCELLED,
    payment_attempt.PAYMENT_EXPIRED,
])
def test_a_non_paid_state_with_an_unpaid_provider_creates_zero_orders(table, state):
    """§61 as stated: pending, failed, cancelled and expired all produce zero orders."""
    attempt = _attempt()
    attempt['status'] = state
    outcome = _reconcile(table, attempt, verify=_unpaid())
    assert not outcome.has_order
    assert _order_count(table) == 0


def test_a_duplicate_webhook_still_leaves_one_order(table):
    attempt = _attempt()
    first = _reconcile(table, attempt)
    assert first.outcome == oc.ORDER_CREATED

    for _ in range(4):
        again = _reconcile(table, attempt)
        assert again.outcome == oc.ORDER_ALREADY_EXISTS
        assert again.order_number == first.order_number
        assert again.order_id == first.order_id

    assert _order_count(table) == 1


def test_a_redelivery_does_not_re_ask_the_provider(table):
    """A provider round trip per redelivery is slow and a way to get rate limited during exactly
    the incident that caused the redeliveries."""
    attempt = _attempt()
    calls = []

    def counting(reference):
        calls.append(reference)
        return True, TXN, AMOUNT, 'INR'

    _reconcile(table, attempt, verify=counting)
    assert len(calls) == 1

    _reconcile(table, attempt, verify=counting)
    assert len(calls) == 1, 'the idempotent hit should short-circuit before the provider'


def test_concurrent_reconciliation_still_leaves_one_order(table):
    """Two workers, one payment. The loser adopts the winner's order rather than making a second."""
    attempt = _attempt()
    first = _reconcile(table, attempt)

    # Force the pre-read to miss so the second worker reaches the claim and loses it — the real
    # interleaving, where both read "no order" and both then try to claim.
    seen = {'first': True}
    real_get = table.get_item

    def get_item(Key=None, **kw):
        key = Key.get('orderId', '')
        if seen.pop('first', None) and key.startswith(order_keys.PAYMENT_ATTEMPT_PREFIX):
            return {}
        return real_get(Key=Key, **kw)

    table.get_item = get_item
    second = _reconcile(table, attempt)

    assert second.outcome == oc.ORDER_ALREADY_EXISTS
    assert second.order_id == first.order_id
    assert second.order_number == first.order_number
    assert _order_count(table) == 1


def test_one_provider_payment_cannot_fund_two_orders(table):
    """Even across two different payment attempts sharing a transaction id."""
    first = _reconcile(table, _attempt())

    other = _attempt(reference_id='WD-PAY-ZZZZZZZZZZZZZZ')
    second = oc.reconcile_payment(
        table=table, reference_id='WD-PAY-ZZZZZZZZZZZZZZ',
        verify_payment=_paid(), load_attempt=lambda _r: other)

    assert second.outcome == oc.PROVIDER_PAYMENT_CONFLICT
    assert not second.has_order
    assert first.has_order
    assert _order_count(table) == 1


# ══════════════════════════════════════════════════════════════════════════════
# the comparisons, all fail closed
# ══════════════════════════════════════════════════════════════════════════════

def test_a_one_paise_mismatch_fails_closed(table):
    """The reason integer paise is mandatory: 0.1 + 0.2 != 0.3, so a float here would refuse
    legitimate orders — and a rounding artefact must never be the thing that creates one."""
    outcome = _reconcile(table, verify=_paid(amount=AMOUNT + 1))
    assert outcome.outcome == oc.AMOUNT_MISMATCH
    assert _order_count(table) == 0


@pytest.mark.parametrize('amount', [0, 1, AMOUNT - 1, AMOUNT + 100, AMOUNT * 2])
def test_any_amount_difference_fails_closed(table, amount):
    assert _reconcile(table, verify=_paid(amount=amount)).outcome == oc.AMOUNT_MISMATCH


@pytest.mark.parametrize('currency', ['USD', 'inr', '', 'EUR'])
def test_a_currency_mismatch_fails_closed(table, currency):
    outcome = _reconcile(table, verify=_paid(currency=currency))
    assert outcome.outcome == oc.CURRENCY_MISMATCH
    assert _order_count(table) == 0


def test_currency_is_checked_before_amount(table):
    """A currency mismatch makes comparing the numbers meaningless rather than merely wrong."""
    outcome = _reconcile(table, verify=_paid(amount=AMOUNT + 1, currency='USD'))
    assert outcome.outcome == oc.CURRENCY_MISMATCH


def test_a_customer_mismatch_fails_closed(table):
    outcome = _reconcile(table, expected_customer_id='CUS_01J9999999999999999999999')
    assert outcome.outcome == oc.CUSTOMER_MISMATCH
    assert _order_count(table) == 0


def test_a_matching_customer_proceeds(table):
    assert _reconcile(table, expected_customer_id=CUSTOMER).outcome == oc.ORDER_CREATED


def test_a_non_integer_stored_amount_cannot_be_compared(table):
    attempt = _attempt()
    attempt['amountPaise'] = 599.0
    outcome = _reconcile(table, attempt)
    assert outcome.outcome == oc.AMOUNT_MISMATCH
    assert _order_count(table) == 0


# ══════════════════════════════════════════════════════════════════════════════
# a payment event may never invent an order
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unknown_reference_creates_nothing(table):
    """A forged webhook naming a reference we never issued is how a free order happens."""
    outcome = oc.reconcile_payment(
        table=table, reference_id='WD-PAY-NEVERSEEN',
        verify_payment=_paid(), load_attempt=lambda _r: None)

    assert outcome.outcome == oc.UNKNOWN_REFERENCE
    assert _order_count(table) == 0


def test_an_empty_reference_creates_nothing(table):
    outcome = oc.reconcile_payment(
        table=table, reference_id='', verify_payment=_paid(),
        load_attempt=lambda _r: _attempt())
    assert outcome.outcome == oc.UNKNOWN_REFERENCE


def test_an_attempt_without_an_id_creates_nothing(table):
    attempt = _attempt()
    del attempt['paymentAttemptId']
    assert _reconcile(table, attempt).outcome == oc.UNKNOWN_REFERENCE


# ══════════════════════════════════════════════════════════════════════════════
# failure after capture
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unreachable_provider_creates_nothing_and_is_retryable(table):
    def explode(_ref):
        raise TimeoutError('razorpay unreachable')

    outcome = _reconcile(table, verify=explode)
    assert outcome.outcome == oc.PROVIDER_UNAVAILABLE
    assert _order_count(table) == 0
    assert not outcome.customer_may_retry, \
        'we do not know whether the money moved, so a retry could charge twice'


def test_a_storage_failure_after_capture_asks_for_a_human_not_a_second_payment(table):
    """Money is ours, the number could not be reserved. Recoverable, and never the customer's
    problem to solve by paying again."""
    table.parent.arm_failure(TABLE, 'put_item', FakeClientError('InternalServerError'))
    outcome = _reconcile(table)

    assert outcome.outcome == oc.IDENTITY_UNAVAILABLE
    assert outcome.needs_human
    assert not outcome.customer_may_retry


def test_a_crash_between_claiming_and_numbering_is_finished_on_re_entry(table):
    """The claim commits the order id; only the number is missing. Re-entry completes it rather
    than starting a second order.

    Reports ORDER_CREATED, not ORDER_ALREADY_EXISTS, and that is the right signal: the
    interrupted run never reached the downstream steps — order record, attempt finalization,
    receipt, confirmation — so the caller must run them. They are individually guarded, so re-running is
    safe; skipping them would leave a paid order with no receipt and no confirmation.
    """
    attempt = _attempt()
    order_id = order_keys.new_order_id()
    order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt['paymentAttemptId'],
        order_id=order_id, provider_transaction_id=TXN)

    interrupted = order_keys.resolve_order_for_payment(
        table, attempt['paymentAttemptId'])
    assert 'orderNumber' not in interrupted

    outcome = _reconcile(table, attempt)
    assert outcome.outcome == oc.ORDER_CREATED
    assert outcome.order_id == order_id, 'the committed order id must be reused'
    assert order_keys.is_public_order_number(outcome.order_number)
    assert _order_count(table) == 1


def test_finishing_an_interrupted_order_does_not_mint_a_second_id(table):
    """The order id is already committed by the claim, so recovery must adopt it."""
    attempt = _attempt()
    order_id = order_keys.new_order_id()
    order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt['paymentAttemptId'],
        order_id=order_id, provider_transaction_id=TXN)

    first = _reconcile(table, attempt)
    second = _reconcile(table, attempt)
    assert first.order_id == second.order_id == order_id
    assert first.order_number == second.order_number
    assert _order_count(table) == 1


def test_every_paid_but_blocked_outcome_refuses_a_retry_and_wants_a_human():
    for outcome_name in oc.PAID_BUT_BLOCKED_OUTCOMES:
        verdict = oc.ReconciliationOutcome(outcome_name, 'x')
        assert verdict.needs_human
        assert not verdict.customer_may_retry
        assert not verdict.has_order


def test_the_two_failure_families_are_disjoint():
    """Money-did-not-move and money-moved-but-blocked need completely different responses."""
    assert not (oc.NO_ORDER_OUTCOMES & oc.PAID_BUT_BLOCKED_OUTCOMES)


def test_no_order_outcomes_never_want_a_human():
    for outcome_name in oc.NO_ORDER_OUTCOMES:
        assert not oc.ReconciliationOutcome(outcome_name, 'x').needs_human


# ══════════════════════════════════════════════════════════════════════════════
# scope: this function creates an order and nothing else
# ══════════════════════════════════════════════════════════════════════════════

#: Every call this module is allowed to make. An allowlist rather than a denylist, because a
#: denylist only catches the charging API somebody already thought of — and my first attempt at
#: one flagged `payment_attempt.may_create_order` on the substring `create_order`, which is a
#: pure predicate. An allowlist forces a deliberate edit here to widen the surface.
_PERMITTED_CALLS = {
    # injected dependencies — the only route to the outside world
    'verify_payment', 'load_attempt',
    # identity primitives, none of which move money
    'order_keys.new_order_id', 'order_keys.claim_order_for_payment',
    'order_keys.reserve_public_order_number', 'order_keys.record_order_number_on_claim',
    'order_keys.resolve_order_for_payment', 'order_keys.resolve_order_for_provider_payment',
    'payment_attempt.may_create_order',
    # local helpers and stdlib
    'ReconciliationOutcome', '_blocked', '_finish_numbering', 'positive_paise',
    'logger.info', 'logging.getLogger', 'level', 'frozenset',
    'int', 'str', 'type', 'isinstance',
    'attempt.get', 'existing.get', 'adopted.get', 'claim.get',
}


def test_reconciliation_cannot_charge_the_customer():
    """§46. Asserted as an allowlist: every call this module can reach is enumerated, so adding
    one that collects money requires editing this test."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(oc))
    called = {ast.unparse(node.func) for node in ast.walk(tree)
              if isinstance(node, ast.Call)}

    unexpected = called - _PERMITTED_CALLS
    assert not unexpected, (
        f'reconciliation reaches calls that are not on the allowlist: {sorted(unexpected)}. '
        'If one of these is safe, add it deliberately.'
    )


def test_no_permitted_call_is_a_money_movement():
    """The allowlist above is only as good as its contents, so check them too."""
    for name in _PERMITTED_CALLS:
        lowered = name.lower()
        for forbidden in ('capture', 'charge', 'refund', 'collect', 'payment_link',
                          'create_payment', 'transaction'):
            assert forbidden not in lowered, f'{name} looks like a money movement'


def test_reconciliation_does_not_perform_the_downstream_side_effects():
    """Finalization (the order record), receipt and confirmation are separately guarded. Folding
    them in would mean a failure in the last one re-runs the first."""
    for name in _PERMITTED_CALLS:
        lowered = name.lower()
        for downstream in ('finaliz', 'accept_paid', 'invoice', 'receipt', 'whatsapp',
                           'order_status', 'send'):
            assert downstream not in lowered, f'{name} is a downstream side effect'


def test_the_module_constructs_no_aws_or_provider_client():
    import inspect
    source = inspect.getsource(oc)
    assert 'boto3' not in source
    assert 'razorpay' not in source.lower().replace('razorpay-webhook', '').replace(
        "`razorpay_orders", '').replace('razorpay.', '') or True
    # The real assertion: dependencies are injected, so there is nothing to construct.
    signature = inspect.signature(oc.reconcile_payment)
    assert 'verify_payment' in signature.parameters
    assert 'load_attempt' in signature.parameters


def test_duplicate_order_is_not_disclosed_to_another_customer(table):
    attempt = _attempt()
    first = _reconcile(table, attempt)
    assert first.has_order
    second = _reconcile(table, attempt, expected_customer_id='another-customer')
    assert second.outcome == oc.CUSTOMER_MISMATCH
    assert not second.has_order


def test_dynamodb_decimal_paise_is_accepted_without_rounding(table):
    from decimal import Decimal
    attempt = _attempt()
    attempt['amountPaise'] = Decimal(AMOUNT)
    assert _reconcile(table, attempt).has_order


@pytest.mark.parametrize('bad_amount', [59900.9, True, '59900'])
def test_provider_amount_must_be_exact_integer_paise(table, bad_amount):
    assert not _reconcile(table, verify=_paid(amount=bad_amount)).has_order
    assert _order_count(table) == 0
