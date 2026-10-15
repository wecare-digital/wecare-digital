"""The webhook now creates an order, and only from a provider-verified capture.

Before this wiring, `payment.captured` produced a payment record, invoice state, a GST invoice and
notifications — but no commerce order. And it trusted the event body, which matters because the
webhook signing secret is in this repository's public git history: a signature-valid
`payment.captured` proves only that somebody read the history.

These tests drive the *provider* answer, not the event, which is the whole point of the change.
"""

import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')
KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
ATTEMPT = '01930000-0000-7000-8000-000000000001'
TXN = 'pay_LIVE0000000001'
AMOUNT = 59900


@pytest.fixture
def webhook():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, WEBHOOK_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    return module


@pytest.fixture
def keys_table():
    fake = FakeDynamo(keys={KEYS_TABLE: 'orderId'})
    return fake.Table(KEYS_TABLE)


def _seed_attempt(table, *, amount=AMOUNT, currency='INR'):
    """A PAYREF# row as the payment-request builder would have written it."""
    order_keys.reserve_payment_reference(
        table, reference_id=REFERENCE, payment_attempt_id=ATTEMPT,
        extra={'customerId': 'CUS_01J0000000000000000000000',
               'amountPaise': amount, 'currency': currency})


def _run(webhook, keys_table, *, verifier, payment=None):
    """Drive _create_order_for_captured_payment with the table and verifier injected."""
    payload = payment or {'id': TXN, 'order_id': 'order_ABC', 'amount': AMOUNT,
                          'currency': 'INR', 'status': 'captured'}
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.return_value = keys_table
        with patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier):
            return webhook._create_order_for_captured_payment(
                payload, REFERENCE, 'req-1')


def _order_count(table):
    return len([k for k in table.rows
                if str(k).startswith(order_keys.ORDER_NUMBER_PREFIX)])


# ══════════════════════════════════════════════════════════════════════════════
# the wiring exists and works
# ══════════════════════════════════════════════════════════════════════════════

def test_a_verified_capture_creates_one_order(webhook, keys_table):
    _seed_attempt(keys_table)
    result = _run(webhook, keys_table,
                  verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

    assert result['outcome'] == 'ORDER_CREATED'
    assert result['hasOrder'] is True
    assert order_keys.is_public_order_number(result['orderNumber'])
    assert _order_count(keys_table) == 1


def test_a_redelivery_does_not_create_a_second_order(webhook, keys_table):
    _seed_attempt(keys_table)
    first = _run(webhook, keys_table, verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))
    second = _run(webhook, keys_table, verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

    assert second['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert second['orderNumber'] == first['orderNumber']
    assert _order_count(keys_table) == 1


def test_the_event_body_is_not_trusted(webhook, keys_table):
    """A forged, signature-valid payment.captured. The provider says no, so nothing is created."""
    _seed_attempt(keys_table)
    result = _run(webhook, keys_table, verifier=lambda _r: (False, '', 0, ''))

    assert result['outcome'] == 'NOT_PAID'
    assert result['hasOrder'] is False
    assert _order_count(keys_table) == 0


def test_an_event_amount_that_disagrees_with_the_provider_is_irrelevant(webhook, keys_table):
    """The comparison is provider-vs-stored-attempt. The event's own amount is never consulted,
    so inflating it in a forged event changes nothing."""
    _seed_attempt(keys_table, amount=AMOUNT)
    result = _run(webhook, keys_table,
                  verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
                  payment={'id': TXN, 'order_id': 'order_ABC',
                           'amount': 99999999, 'currency': 'INR'})
    assert result['outcome'] == 'ORDER_CREATED'


def test_a_provider_amount_mismatch_blocks_and_flags_for_a_human(webhook, keys_table):
    _seed_attempt(keys_table, amount=AMOUNT)
    result = _run(webhook, keys_table,
                  verifier=lambda _r: (True, TXN, AMOUNT + 1, 'INR'))

    assert result['outcome'] == 'AMOUNT_MISMATCH'
    assert result['needsHuman'] is True
    assert _order_count(keys_table) == 0


def test_a_currency_mismatch_blocks(webhook, keys_table):
    _seed_attempt(keys_table)
    result = _run(webhook, keys_table, verifier=lambda _r: (True, TXN, AMOUNT, 'USD'))
    assert result['outcome'] == 'CURRENCY_MISMATCH'
    assert result['needsHuman'] is True


# ══════════════════════════════════════════════════════════════════════════════
# it must not disturb the existing invoice-only flows
# ══════════════════════════════════════════════════════════════════════════════

def test_a_payment_with_no_attempt_creates_nothing_and_does_not_error(webhook, keys_table):
    """Every payment that did not originate from the new checkout has no PAYREF# row. Those must
    pass through untouched, because the invoice paths still depend on them."""
    result = _run(webhook, keys_table, verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

    assert result['outcome'] == 'UNKNOWN_REFERENCE'
    assert result['hasOrder'] is False
    assert _order_count(keys_table) == 0


def test_a_payment_with_no_provider_id_is_skipped(webhook, keys_table):
    _seed_attempt(keys_table)
    result = _run(webhook, keys_table, verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
                  payment={'amount': AMOUNT, 'currency': 'INR'})
    assert result['outcome'] == 'NO_PROVIDER_ID'


def test_reconciliation_never_raises_into_the_webhook(webhook, keys_table):
    """A non-2xx makes Razorpay retry the whole event, and the lease already handles recovery —
    so an internal failure must be swallowed and logged, not propagated."""
    def explode(_ref):
        raise RuntimeError('razorpay unreachable')

    _seed_attempt(keys_table)
    result = _run(webhook, keys_table, verifier=explode)
    assert result['hasOrder'] is False
    assert result['outcome'] in ('PROVIDER_UNAVAILABLE', 'RECONCILIATION_ERROR')


# ══════════════════════════════════════════════════════════════════════════════
# the dedup lease is wired, and closed last
# ══════════════════════════════════════════════════════════════════════════════

def test_the_handler_uses_the_leased_claim_not_the_permanent_one(webhook):
    import inspect
    source = inspect.getsource(webhook._is_duplicate_event)
    assert 'claim_event_with_lease' in source
    assert 'import claim_event\n' not in source


def test_completion_happens_on_the_success_path_only(webhook):
    """Completing early recreates the claim-before-work defect; the except branch must NOT
    complete, because letting the lease lapse is what allows the retry through."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(webhook.handler)))

    completed_in_handler = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == '_complete_event'
    ]
    assert completed_in_handler, '_complete_event is never called on the success path'

    # No completion inside any exception handler.
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        rendered = ast.unparse(node)
        assert '_complete_event' not in rendered, \
            'completing the lease in an except branch would dismiss the provider retry'


def test_complete_event_never_raises(webhook):
    import inspect
    source = inspect.getsource(webhook._complete_event)
    assert 'except Exception' in source
