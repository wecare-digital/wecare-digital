"""The webhook hints `wecare-service-requests` after an order exists, and at no other time.

Uses the harness of tests/test_razorpay_webhook_order_creation.py: the provider answer is
driven, never the event body. The hint is ids only, fire-and-forget, and its failure cannot
change what the webhook returns.
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
from lambda_utils.ecommerce import order_keys, service_request_dispatch  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')
KEYS_TABLE = 'stack-wecare-digital-WixOrderIds'
REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
ATTEMPT = '01930000-0000-7000-8000-000000000001'
TXN = 'pay_LIVE0000000001'
AMOUNT = 10193


class RecordingLambda:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError('lambda down')
        return {'StatusCode': 202}


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
    return FakeDynamo(keys={KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)


def _seed(table, *, currency='INR'):
    order_keys.reserve_payment_reference(
        table, reference_id=REFERENCE, payment_attempt_id=ATTEMPT,
        extra={'customerId': 'sub-1', 'amountPaise': AMOUNT, 'currency': currency,
               'serviceLine': {'kind': 'SUBMIT_REQUEST',
                               'variantId': 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b',
                               'paise': 9900,
                               'intentId': '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f'}})


def _run(webhook, table, recorder, verifier):
    payload = {'id': TXN, 'order_id': 'order_ABC', 'amount': AMOUNT, 'currency': 'INR'}
    with patch.object(webhook, 'dynamodb') as ddb, patch.object(webhook, 'lambda_client',
                                                                recorder):
        ddb.Table.return_value = table
        with patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier):
            return webhook._create_order_for_captured_payment(payload, REFERENCE, 'req-1')


def _hints(recorder):
    return [c for c in recorder.calls if c.get('FunctionName') == 'wecare-service-requests:live']


def test_order_created_dispatches_one_hint_with_exactly_four_keys(webhook, keys_table):
    _seed(keys_table)
    recorder = RecordingLambda()
    result = _run(webhook, keys_table, recorder, lambda _r: (True, TXN, AMOUNT, 'INR'))
    assert result['outcome'] == 'ORDER_CREATED'
    [hint] = _hints(recorder)
    assert hint['InvocationType'] == 'Event'
    payload = json.loads(hint['Payload'].decode('utf-8'))
    assert set(payload) == {'internalAction', 'referenceId', 'paymentAttemptId', 'orderId'}
    assert payload == {'internalAction': 'activateServiceRequest', 'referenceId': REFERENCE,
                       'paymentAttemptId': ATTEMPT, 'orderId': result['orderId']}
    flat = json.dumps(payload)
    assert str(AMOUNT) not in flat and '9900' not in flat and '+91' not in flat


def test_order_already_exists_dispatches_again_and_the_receiver_is_idempotent(webhook,
                                                                              keys_table):
    _seed(keys_table)
    recorder = RecordingLambda()
    _run(webhook, keys_table, recorder, lambda _r: (True, TXN, AMOUNT, 'INR'))
    second = _run(webhook, keys_table, recorder, lambda _r: (True, TXN, AMOUNT, 'INR'))
    assert second['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert len(_hints(recorder)) == 2


@pytest.mark.parametrize('verifier,outcome', [
    (lambda _r: (False, '', 0, ''), 'NOT_PAID'),
    (lambda _r: (True, TXN, AMOUNT + 1, 'INR'), 'AMOUNT_MISMATCH'),
    (lambda _r: (True, TXN, AMOUNT, 'USD'), 'CURRENCY_MISMATCH'),
])
def test_no_hint_without_an_order(webhook, keys_table, verifier, outcome):
    _seed(keys_table)
    recorder = RecordingLambda()
    result = _run(webhook, keys_table, recorder, verifier)
    assert result['outcome'] == outcome and result['hasOrder'] is False
    assert _hints(recorder) == []


def test_no_hint_for_an_unknown_reference(webhook, keys_table):
    recorder = RecordingLambda()
    result = _run(webhook, keys_table, recorder, lambda _r: (True, TXN, AMOUNT, 'INR'))
    assert result['outcome'] == 'UNKNOWN_REFERENCE'
    assert _hints(recorder) == []


def test_no_hint_on_a_reconciliation_error(webhook, keys_table):
    _seed(keys_table)
    recorder = RecordingLambda()
    with patch('lambda_utils.ecommerce.order_creation.reconcile_payment',
               side_effect=RuntimeError('boom')):
        result = _run(webhook, keys_table, recorder, lambda _r: (True, TXN, AMOUNT, 'INR'))
    assert result['outcome'] == 'RECONCILIATION_ERROR'
    assert _hints(recorder) == []


def test_an_invoke_failure_does_not_change_the_webhooks_answer(webhook, keys_table):
    _seed(keys_table)
    healthy = _run(webhook, keys_table, RecordingLambda(),
                   lambda _r: (True, TXN, AMOUNT, 'INR'))
    other = FakeDynamo(keys={KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)
    _seed(other)
    failing = RecordingLambda(fail=True)
    broken = _run(webhook, other, failing, lambda _r: (True, TXN, AMOUNT, 'INR'))
    assert len(_hints(failing)) == 1
    assert broken['outcome'] == healthy['outcome'] == 'ORDER_CREATED'
    assert broken['hasOrder'] is True


def test_dispatch_never_raises_and_names_the_live_alias():
    recorder = RecordingLambda(fail=True)
    service_request_dispatch.dispatch_activation(
        recorder, reference_id='r', payment_attempt_id='a', order_id='o')
    assert recorder.calls[0]['FunctionName'] == 'wecare-service-requests:live'
    assert service_request_dispatch.TARGET_FUNCTION.endswith(':live')
