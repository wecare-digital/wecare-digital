"""A payment attempt is not an order, and a failed one must never look like a purchase.

Most payment attempts never become orders — abandoned checkouts, timed-out mandates, declined
cards — and that is normal. So the tests here weigh the negative cases at least as heavily as the
happy path: what a failed attempt must NOT have, and which retries must be refused.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils import identifiers  # noqa: E402
from lambda_utils.ecommerce import payment_attempt as pa  # noqa: E402

NOW = 1_700_000_000


def _attempt(**kw):
    params = dict(customer_id='CUS_01J0000000000000000000000',
                  reference_id='WD-PAY-ABCDEFGHJKMNPQ',
                  amount_paise=59900, configuration_name='WECAREDIGITAL', now=NOW)
    params.update(kw)
    return pa.build(**params)


# ── the entity ─────────────────────────────────────────────────────────────────

def test_a_new_attempt_has_no_order_fields_at_all():
    """The central rule, expressed in the data. There is nowhere to put an order number."""
    attempt = _attempt()
    for forbidden in ('orderId', 'orderNumber', 'receiptId', 'invoiceId'):
        assert forbidden not in attempt


def test_the_attempt_id_is_a_uuid7():
    assert identifiers.is_uuid7(_attempt()['paymentAttemptId'])


def test_a_new_attempt_starts_in_created():
    attempt = _attempt()
    assert attempt['status'] == pa.CREATED
    assert attempt[pa.RANK_ATTRIBUTE] == pa.rank(pa.CREATED)
    assert not pa.may_create_order(attempt)
    assert not pa.may_retry(attempt)
    assert pa.is_in_flight(attempt)


def test_optional_fields_are_omitted_rather_than_none():
    """Absence is what lets a conditional write assert attribute_not_exists later."""
    attempt = _attempt()
    for optional in ('cartId', 'retryOf', 'customerUuid'):
        assert optional not in attempt


def test_supplied_optional_fields_are_kept():
    attempt = _attempt(cart_id='cart-1', retry_of='attempt-0', customer_uuid='WD-CUS-1')
    assert attempt['cartId'] == 'cart-1'
    assert attempt['retryOf'] == 'attempt-0'
    assert attempt['customerUuid'] == 'WD-CUS-1'


def test_a_new_attempt_carries_exactly_the_documented_fields():
    """The record's whole key set, so a field added to `build` is a decision this test names."""
    assert set(_attempt(cart_id='cart-1')) == {
        'paymentAttemptId', 'customerId', 'referenceId', 'amountPaise', 'currency',
        'configurationName', 'provider', 'status', pa.RANK_ATTRIBUTE, 'attemptNumber',
        'createdAt', 'updatedAt', 'cartId'}


# ── money ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', [599.0, 599.5, '599', None, True])
def test_a_non_integer_amount_is_refused(bad):
    """A one-paise difference must fail the payment closed, and 0.1 + 0.2 != 0.3 in binary
    floating point — so a rounding artefact would refuse a legitimate order."""
    with pytest.raises((TypeError, ValueError)):
        _attempt(amount_paise=bad)


@pytest.mark.parametrize('bad', [0, -1, -59900])
def test_a_non_positive_amount_is_refused(bad):
    with pytest.raises(ValueError):
        _attempt(amount_paise=bad)


@pytest.mark.parametrize('bad', ['USD', 'inr', '', 'EUR'])
def test_currency_is_compared_explicitly(bad):
    with pytest.raises(ValueError):
        _attempt(currency=bad)


def test_a_missing_configuration_name_is_refused():
    """There is no default. Substituting one is what the readiness gate exists to prevent."""
    with pytest.raises(ValueError):
        _attempt(configuration_name='')


@pytest.mark.parametrize('field', ['customer_id', 'reference_id'])
def test_required_identifiers_are_refused_when_empty(field):
    with pytest.raises(ValueError):
        _attempt(**{field: ''})


# ── only PAID may create an order ──────────────────────────────────────────────

@pytest.mark.parametrize('state', [
    pa.CREATED, pa.PAYMENT_READINESS_CHECKED, pa.PAYMENT_REQUEST_SENT,
    pa.PAYMENT_PENDING, pa.PAYMENT_FAILED, pa.PAYMENT_CANCELLED, pa.PAYMENT_EXPIRED,
])
def test_no_state_except_paid_may_create_an_order(state):
    assert not pa.may_create_order({'status': state})


def test_paid_may_create_an_order():
    assert pa.may_create_order({'status': pa.PAYMENT_PAID})


def test_the_eligible_set_is_exactly_one_state():
    """A set rather than an `or`, so the rule is greppable and cannot be widened by an edit."""
    assert pa.ORDER_ELIGIBLE_STATES == frozenset({pa.PAYMENT_PAID})


def test_every_state_is_classified():
    assert pa.ALL_STATES == pa.IN_FLIGHT_STATES | pa.TERMINAL_STATES
    assert not (pa.IN_FLIGHT_STATES & pa.TERMINAL_STATES)
    assert pa.RETRYABLE_STATES.isdisjoint(pa.ORDER_ELIGIBLE_STATES)


# ── transitions are monotonic ──────────────────────────────────────────────────

def test_a_forward_transition_is_allowed():
    attempt = _attempt()
    sent = pa.transition(attempt, pa.PAYMENT_REQUEST_SENT, now=NOW + 1)
    assert sent['status'] == pa.PAYMENT_REQUEST_SENT
    assert sent['updatedAt'] == NOW + 1


def test_a_late_failure_cannot_unpay_a_captured_payment():
    """The transition that would tell a paying customer their payment did not work."""
    paid = pa.transition(_attempt(), pa.PAYMENT_PAID, now=NOW + 5)
    for late in (pa.PAYMENT_FAILED, pa.PAYMENT_CANCELLED, pa.PAYMENT_EXPIRED,
                 pa.PAYMENT_PENDING):
        with pytest.raises(pa.IllegalTransition):
            pa.transition(paid, late, now=NOW + 6)


def test_paid_outranks_every_failure():
    assert pa.rank(pa.PAYMENT_PAID) > max(
        pa.rank(s) for s in pa.RETRYABLE_STATES | pa.IN_FLIGHT_STATES)


def test_an_unknown_state_ranks_zero_and_overwrites_nothing():
    assert pa.rank('PROBABLY_FINE') == 0
    with pytest.raises(pa.IllegalTransition):
        pa.transition({'status': pa.PAYMENT_PENDING}, 'PROBABLY_FINE')


def test_transition_is_pure():
    """It returns a new dict so a caller cannot apply a local change then persist it without
    the conditional write."""
    attempt = _attempt()
    pa.transition(attempt, pa.PAYMENT_PAID, now=NOW + 1)
    assert attempt['status'] == pa.CREATED


def test_paid_records_paid_at_and_failure_records_failed_at():
    paid = pa.transition(_attempt(), pa.PAYMENT_PAID, now=NOW + 3)
    assert paid['paidAt'] == NOW + 3 and 'failedAt' not in paid

    failed = pa.transition(_attempt(), pa.PAYMENT_FAILED, now=NOW + 4,
                           failure_code='BAD_CARD', failure_reason='Declined')
    assert failed['failedAt'] == NOW + 4
    assert failed['failureCode'] == 'BAD_CARD'
    assert 'paidAt' not in failed


def test_the_condition_expression_refuses_a_backward_write():
    expr = pa.condition_expression()
    assert pa.RANK_ATTRIBUTE in expr
    assert 'attribute_not_exists' in expr and '<=' in expr


# ── retry ──────────────────────────────────────────────────────────────────────

def test_a_retry_of_a_failed_attempt_carries_lineage_and_a_new_reference():
    first = pa.transition(_attempt(), pa.PAYMENT_FAILED, now=NOW + 1)
    second = pa.next_retry(first, reference_id='WD-PAY-ZZZZZZZZZZZZZZ',
                           amount_paise=60900, configuration_name='WECAREDIGITAL',
                           now=NOW + 2)

    assert second['retryOf'] == first['paymentAttemptId']
    assert second['attemptNumber'] == 2
    assert second['paymentAttemptId'] != first['paymentAttemptId']
    assert second['referenceId'] != first['referenceId']
    assert second['status'] == pa.CREATED


def test_a_retry_must_not_reuse_the_reference():
    """Reusing it makes the two attempts indistinguishable to Meta and Razorpay."""
    failed = pa.transition(_attempt(), pa.PAYMENT_FAILED, now=NOW + 1)
    with pytest.raises(ValueError):
        pa.next_retry(failed, reference_id=failed['referenceId'],
                      amount_paise=59900, configuration_name='WECAREDIGITAL')


def test_a_retry_recalculates_the_amount_rather_than_copying_it():
    """Prices, stock and shipping may have moved; reusing a stale total charges yesterday's
    price for today's basket."""
    failed = pa.transition(_attempt(amount_paise=59900), pa.PAYMENT_FAILED, now=NOW + 1)
    retried = pa.next_retry(failed, reference_id='WD-PAY-NEWNEWNEWNEWN',
                            amount_paise=64900, configuration_name='WECAREDIGITAL')
    assert retried['amountPaise'] == 64900


@pytest.mark.parametrize('state', sorted(pa.IN_FLIGHT_STATES))
def test_an_in_flight_attempt_cannot_be_retried(state):
    """A retry here produces a second payable request for one basket."""
    with pytest.raises(pa.IllegalTransition):
        pa.next_retry({'status': state, 'paymentAttemptId': 'a', 'customerId': 'CUS_x',
                       'referenceId': 'WD-PAY-1'},
                      reference_id='WD-PAY-2', amount_paise=1,
                      configuration_name='WECAREDIGITAL')


def test_a_paid_attempt_cannot_be_retried():
    """This one asks a customer to pay twice."""
    paid = pa.transition(_attempt(), pa.PAYMENT_PAID, now=NOW + 1)
    assert not pa.may_retry(paid)
    with pytest.raises(pa.IllegalTransition):
        pa.next_retry(paid, reference_id='WD-PAY-2', amount_paise=1,
                      configuration_name='WECAREDIGITAL')


@pytest.mark.parametrize('state', sorted(pa.RETRYABLE_STATES))
def test_every_definitely_over_state_may_retry(state):
    assert pa.may_retry({'status': state})


# ── payment history vs order history ───────────────────────────────────────────

@pytest.mark.parametrize('state', sorted(pa.RETRYABLE_STATES))
def test_a_failed_entry_has_no_order_number_and_says_so(state):
    entry = pa.payment_history_entry(
        pa.transition(_attempt(), state, now=NOW + 1))
    assert entry['orderNumber'] is None
    assert entry['label'] == pa.FAILED_LABEL
    assert 'no order created' in entry['label'].lower()
    assert entry['canRetry'] is True


def test_an_order_number_passed_for_a_failed_attempt_is_stripped():
    """Belt and braces: this is the row a customer reads, and an order number on it is the
    exact confusion the view exists to prevent."""
    failed = pa.transition(_attempt(), pa.PAYMENT_FAILED, now=NOW + 1)
    entry = pa.payment_history_entry(failed, order_number='7KMP4X9Q2DTR')
    assert entry['orderNumber'] is None


def test_a_paid_entry_carries_its_order_number():
    paid = pa.transition(_attempt(), pa.PAYMENT_PAID, now=NOW + 1)
    entry = pa.payment_history_entry(paid, order_number='7KMP4X9Q2DTR')
    assert entry['orderNumber'] == '7KMP4X9Q2DTR'
    assert entry['label'] is None
    assert entry['canRetry'] is False


@pytest.mark.parametrize('state', sorted(pa.IN_FLIGHT_STATES))
def test_an_in_flight_entry_offers_no_retry_and_no_order_number(state):
    entry = pa.payment_history_entry({'status': state})
    assert entry['orderNumber'] is None
    assert entry['canRetry'] is False


def test_order_history_contains_only_paid_attempts():
    attempts = [
        _attempt(),
        pa.transition(_attempt(), pa.PAYMENT_PENDING, now=NOW + 1),
        pa.transition(_attempt(), pa.PAYMENT_FAILED, now=NOW + 1),
        pa.transition(_attempt(), pa.PAYMENT_CANCELLED, now=NOW + 1),
        pa.transition(_attempt(), pa.PAYMENT_EXPIRED, now=NOW + 1),
        pa.transition(_attempt(), pa.PAYMENT_PAID, now=NOW + 1),
    ]
    kept = pa.filter_order_history(attempts)
    assert len(kept) == 1
    assert kept[0]['status'] == pa.PAYMENT_PAID


def test_payment_history_keeps_every_attempt():
    """Failed attempts must remain visible — that is the whole point of the separate view."""
    attempts = [pa.transition(_attempt(), s, now=NOW + 1)
                for s in sorted(pa.RETRYABLE_STATES)]
    entries = [pa.payment_history_entry(a) for a in attempts]
    assert len(entries) == len(attempts)
    assert all(e['paymentAttemptId'] for e in entries)
