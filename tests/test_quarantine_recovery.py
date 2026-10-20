"""R3/N3 + N2: durable, recoverable quarantine intake and bound, idempotent wallet top-ups.

Two gaps the audit left OPEN in section 5, both closed here as additive hardening on a webhook
that already re-verifies every capture against Razorpay's API and dedups with a lease.

R3/N3 - durable quarantine intake
    `_quarantine_unverified_capture` used to emit a staff alert LOG and nothing else. A log
    disappears when CloudWatch retention lapses and is useless once Razorpay stops retrying.
    It now persists a durable, recoverable intake row to the commerce-keys table (reference_id,
    payment_id, outcome category, created_at, acknowledgement fields) using the same
    conditional-write pattern order creation uses, and writes NOTHING financial. An acknowledged
    event stays in the table, so it remains recoverable after provider retries stop.

N2 - wallet top-up binding + idempotency
    The wallet top-up branch used to credit `partner_billing.topup` with the amount and WABA read
    straight from the event notes, before any provider readback. It now requires a STORED top-up
    intent, verifies the captured amount against Razorpay's API, binds the credit to the stored
    intent, and guards it with an idempotency marker so one capture credits exactly once and a
    duplicate delivery does not double-credit.

These drive the real handler against the honest DynamoDB fake used by the rest of the suite, so
the conditional writes are evaluated for real rather than mocked away.
"""

import importlib
import json
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
INVOICES_TABLE = 'stack-wecare-digital-InvoicesTable'
PAYMENTS_TABLE = 'stack-wecare-digital-PaymentsTable'
PAYMENT_ATTEMPTS_TABLE = 'stack-wecare-digital-PaymentAttemptsTable'
WEBHOOK_LOG_TABLE = 'stack-wecare-digital-RazorpayWebhookLogTable'

REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
TXN = 'pay_LIVE0000000001'
WABA = '2094615664435155'
AMOUNT = 50000  # paise = ₹500.00


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
def fake_ddb():
    return FakeDynamo(
        keys={KEYS_TABLE: 'orderId', INVOICES_TABLE: 'invoiceId',
              PAYMENTS_TABLE: 'id', PAYMENT_ATTEMPTS_TABLE: 'paymentAttemptId',
              WEBHOOK_LOG_TABLE: 'id'},
        indexes={INVOICES_TABLE: {'referenceId-index': ('referenceId', None)},
                 WEBHOOK_LOG_TABLE: {'paymentId-index': ('paymentId', None)}},
    )


def _commerce_event(*, notes=None, amount=59900, payment_id=TXN, order_id='order_ABC'):
    return {'payment': {'entity': {
        'id': payment_id, 'order_id': order_id, 'amount': amount,
        'currency': 'INR', 'status': 'captured', 'method': 'upi',
        'contact': '+919876543210', 'email': 'buyer@example.com',
        'description': 'order', 'notes': notes if notes is not None
        else {'referenceId': REFERENCE},
    }}}


def _topup_event(*, waba=WABA, reference_id=REFERENCE, amount=AMOUNT, payment_id=TXN):
    notes = {'purpose': 'wallet_topup'}
    if waba is not None:
        notes['wabaId'] = waba
    if reference_id is not None:
        notes['referenceId'] = reference_id
    return {'payment': {'entity': {
        'id': payment_id, 'order_id': 'order_TOPUP', 'amount': amount,
        'currency': 'INR', 'status': 'captured', 'method': 'upi',
        'contact': '+919876543210', 'email': '', 'description': 'top-up',
        'notes': notes,
    }}}


class _InvoiceRawQueryTable:
    """Translates the handler's raw-string referenceId query for the FakeTable (see gating test)."""

    def __init__(self, fake_table):
        self._t = fake_table

    def query(self, IndexName=None, KeyConditionExpression=None,
              ExpressionAttributeValues=None, Limit=None, **_):
        self._t._fail_if_armed('query')
        self._t.parent.calls.append((self._t.name, f'query:{IndexName}'))
        if isinstance(KeyConditionExpression, str) and 'referenceId' in KeyConditionExpression:
            ref = (ExpressionAttributeValues or {}).get(':ref')
            items = [dict(r) for r in self._t.rows.values() if r.get('referenceId') == ref]
            if Limit:
                items = items[:Limit]
            return {'Items': items, 'Count': len(items)}
        return self._t.query(IndexName=IndexName, KeyConditionExpression=KeyConditionExpression,
                             ExpressionAttributeValues=ExpressionAttributeValues, Limit=Limit)

    def __getattr__(self, name):
        return getattr(self._t, name)


class _HybridDynamo:
    def __init__(self, fake):
        self._fake = fake
        self.tables = fake.tables
        self.calls = fake.calls

    def Table(self, name):  # noqa: N802 - boto3's spelling
        table = self._fake.Table(name)
        if name == INVOICES_TABLE:
            return _InvoiceRawQueryTable(table)
        return table

    def arm_failure(self, *a, **k):
        return self._fake.arm_failure(*a, **k)


def _quarantine_rows(ddb):
    keys = ddb.tables.get(KEYS_TABLE, {})
    return [v for k, v in keys.items()
            if str(k).startswith(order_keys.QUARANTINE_PREFIX)]


# ══════════════════════════════════════════════════════════════════════════════
# (a) a rejected/unknown commerce outcome writes a durable quarantine row + NO side effect
# ══════════════════════════════════════════════════════════════════════════════

def test_unknown_commerce_capture_writes_durable_quarantine_and_no_financial_write(webhook, fake_ddb):
    """No attempt, no invoice: absence is not evidence. A durable intake row is written, and no
    invoice is marked paid, no payment record stored, no order status sent."""
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                  return_value=lambda _r: (True, TXN, 59900, 'INR')), \
            patch.object(webhook, '_store_payment_record') as store, \
            patch.object(webhook, '_mark_invoice_paid_by_reference') as mark, \
            patch.object(webhook, '_post_payment_handler') as post, \
            patch.object(webhook, 'lambda_client', MagicMock()):
        webhook._handle_payment_captured(_commerce_event(), 'req-1')

    rows = _quarantine_rows(fake_ddb)
    assert len(rows) == 1
    row = rows[0]
    assert row['paymentId'] == TXN
    assert row['referenceId'] == REFERENCE
    assert row['status'] == 'UNRESOLVED'
    assert row['acknowledged'] is False
    assert row['outcome']           # a category is recorded
    assert isinstance(row['createdAt'], int)
    # Nothing financial ran.
    store.assert_not_called()
    mark.assert_not_called()
    post.assert_not_called()


def test_quarantine_row_is_idempotent_across_redeliveries(webhook, fake_ddb):
    """A redelivery of the same unverified capture does not pile up rows or reset the intake."""
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                  return_value=lambda _r: (True, TXN, 59900, 'INR')), \
            patch.object(webhook, '_store_payment_record'), \
            patch.object(webhook, '_mark_invoice_paid_by_reference'), \
            patch.object(webhook, '_post_payment_handler'), \
            patch.object(webhook, 'lambda_client', MagicMock()):
        webhook._handle_payment_captured(_commerce_event(), 'req-1')
        webhook._handle_payment_captured(_commerce_event(), 'req-2')

    assert len(_quarantine_rows(fake_ddb)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# (b) an acknowledged event stays recoverable after provider retries stop
# ══════════════════════════════════════════════════════════════════════════════

def test_acknowledged_quarantine_row_is_retained_and_recoverable(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.record_capture_quarantine(
        table, payment_id=TXN, reference_id=REFERENCE, outcome='NEEDS_RECONCILIATION')

    updated = order_keys.acknowledge_capture_quarantine(table, payment_id=TXN, actor='alice')
    assert updated['acknowledged'] is True
    assert updated['acknowledgedBy'] == 'alice'

    # Still present and resolvable AFTER acknowledgement - the row is never deleted, so the
    # capture remains recoverable even once Razorpay has stopped retrying the event.
    again = order_keys.resolve_capture_quarantine(table, TXN)
    assert again is not None
    assert again['acknowledged'] is True
    assert again['createdAt'] == updated['createdAt']   # intake preserved, not reset


def test_acknowledge_missing_quarantine_returns_none(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    assert order_keys.acknowledge_capture_quarantine(table, payment_id='pay_NONE') is None


def test_acknowledge_advances_status_from_unresolved_to_acknowledged(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    parked = order_keys.record_capture_quarantine(
        table, payment_id=TXN, reference_id=REFERENCE, outcome='NEEDS_RECONCILIATION')
    assert parked['status'] == 'UNRESOLVED'
    updated = order_keys.acknowledge_capture_quarantine(table, payment_id=TXN, actor='alice')
    # The status no longer reads UNRESOLVED once a human has seen it.
    assert updated['status'] == 'ACKNOWLEDGED'
    assert updated['acknowledged'] is True


def test_resolve_moves_to_a_terminal_resolved_state_and_keeps_the_row(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.record_capture_quarantine(
        table, payment_id=TXN, reference_id=REFERENCE, outcome='PAID_ORDER_PROJECTION_FAILED')
    resolved = order_keys.mark_capture_quarantine_resolved(
        table, payment_id=TXN, resolution='reconciled into WD-ORD-TJMG7G4N',
        actor='bob', order_id='ord-9')
    assert resolved['status'] == 'RESOLVED'
    assert resolved['resolution'] == 'reconciled into WD-ORD-TJMG7G4N'
    assert resolved['resolvedBy'] == 'bob'
    assert resolved['resolvedOrderId'] == 'ord-9'
    assert resolved['acknowledged'] is True
    # Retained, not deleted - still readable for audit.
    assert order_keys.resolve_capture_quarantine(table, TXN)['status'] == 'RESOLVED'


def test_status_is_monotonic_acknowledge_cannot_downgrade_a_resolved_row(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.record_capture_quarantine(table, payment_id=TXN, reference_id=REFERENCE)
    order_keys.mark_capture_quarantine_resolved(
        table, payment_id=TXN, resolution='done', actor='bob')
    # Acknowledging after resolution must NOT drag the status back to ACKNOWLEDGED.
    after = order_keys.acknowledge_capture_quarantine(table, payment_id=TXN, actor='carol')
    assert after['status'] == 'RESOLVED'


def test_resolve_is_idempotent_and_requires_a_note(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.record_capture_quarantine(table, payment_id=TXN, reference_id=REFERENCE)
    first = order_keys.mark_capture_quarantine_resolved(
        table, payment_id=TXN, resolution='first', actor='bob')
    # A second resolve is a no-op that does not rewrite the first resolution's evidence.
    second = order_keys.mark_capture_quarantine_resolved(
        table, payment_id=TXN, resolution='second', actor='carol')
    assert second['resolution'] == 'first'
    assert second['resolvedBy'] == 'bob'
    with pytest.raises(ValueError):
        order_keys.mark_capture_quarantine_resolved(table, payment_id=TXN, resolution='')


def test_resolve_missing_quarantine_returns_none(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    assert order_keys.mark_capture_quarantine_resolved(
        table, payment_id='pay_NONE', resolution='x') is None


# ══════════════════════════════════════════════════════════════════════════════
# (c) a wallet top-up WITHOUT a stored intent is NOT credited
# ══════════════════════════════════════════════════════════════════════════════

def test_wallet_topup_without_intent_is_not_credited(webhook, fake_ddb):
    """No reserved intent: the event notes are not evidence, so nothing is credited and the
    capture is parked durably instead."""
    topup = MagicMock()
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.partner_billing.topup', topup), \
            patch('lambda_utils.integrations.razorpay_verify.payment_is_captured',
                  return_value=(True, AMOUNT, 'INR')):
        webhook._handle_payment_captured(_topup_event(), 'req-1')

    topup.assert_not_called()
    assert len(_quarantine_rows(fake_ddb)) == 1


def test_wallet_topup_with_intent_but_provider_amount_mismatch_is_not_credited(webhook, fake_ddb):
    """Intent exists, but Razorpay captured a different amount than the intent. Do not credit."""
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.reserve_topup_intent(table, reference_id=REFERENCE, waba_id=WABA,
                                    amount_paise=AMOUNT, currency='INR')
    topup = MagicMock()
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.partner_billing.topup', topup), \
            patch('lambda_utils.integrations.razorpay_verify.payment_is_captured',
                  return_value=(True, AMOUNT + 100, 'INR')):
        webhook._handle_payment_captured(_topup_event(), 'req-1')

    topup.assert_not_called()


def test_wallet_topup_ignores_event_amount_and_credits_stored_intent(webhook, fake_ddb):
    """The event claims a larger amount than the intent; the provider confirms the intent amount.
    The credit must be the stored/provider-verified amount, never the event body's figure."""
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.reserve_topup_intent(table, reference_id=REFERENCE, waba_id=WABA,
                                    amount_paise=AMOUNT, currency='INR')
    topup = MagicMock(return_value={'balance': 5.0})
    inflated = _topup_event(amount=AMOUNT * 10)  # a forged, inflated event body
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.partner_billing.topup', topup), \
            patch('lambda_utils.integrations.razorpay_verify.payment_is_captured',
                  return_value=(True, AMOUNT, 'INR')):
        webhook._handle_payment_captured(inflated, 'req-1')

    topup.assert_called_once()
    # topup(waba_id, amount_rupees, ...) - credited amount is from the intent (₹500.00), exact.
    assert topup.call_args.args[0] == WABA
    assert topup.call_args.args[1] == Decimal(AMOUNT) / 100


# ══════════════════════════════════════════════════════════════════════════════
# (d) a provider-verified top-up credits exactly once; a duplicate does not double-credit
# ══════════════════════════════════════════════════════════════════════════════

def test_wallet_topup_credits_once_and_duplicate_delivery_does_not_double_credit(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.reserve_topup_intent(table, reference_id=REFERENCE, waba_id=WABA,
                                    amount_paise=AMOUNT, currency='INR')
    topup = MagicMock(return_value={'balance': 5.0})
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.partner_billing.topup', topup), \
            patch('lambda_utils.integrations.razorpay_verify.payment_is_captured',
                  return_value=(True, AMOUNT, 'INR')):
        webhook._handle_payment_captured(_topup_event(), 'req-1')
        webhook._handle_payment_captured(_topup_event(), 'req-2')  # duplicate delivery

    assert topup.call_count == 1
    # The idempotency marker is durable.
    credit = table.get_item(Key={'orderId': order_keys.TOPUP_CREDIT_PREFIX + TXN}).get('Item')
    assert credit is not None
    assert credit['wabaId'] == WABA


def test_wallet_topup_not_captured_by_provider_is_not_credited(webhook, fake_ddb):
    table = fake_ddb.Table(KEYS_TABLE)
    order_keys.reserve_topup_intent(table, reference_id=REFERENCE, waba_id=WABA,
                                    amount_paise=AMOUNT, currency='INR')
    topup = MagicMock()
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)), \
            patch('lambda_utils.partner_billing.topup', topup), \
            patch('lambda_utils.integrations.razorpay_verify.payment_is_captured',
                  return_value=(False, 0, '')):
        webhook._handle_payment_captured(_topup_event(), 'req-1')

    topup.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# (e) quarantined native captures can be safely redriven from stored signed audit evidence
# ══════════════════════════════════════════════════════════════════════════════

def _seed_redrive(fake_ddb):
    keys = fake_ddb.Table(KEYS_TABLE)
    keys.put_item(Item={
        'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE,
        'kind': 'PAYMENT_REFERENCE',
        'referenceId': REFERENCE,
        'paymentAttemptId': 'attempt-redrive',
        'invoiceId': 'invoice-redrive',
        'customerId': 'customer-redrive',
        'amountPaise': AMOUNT,
        'currency': 'INR',
        'checkoutMode': 'WHATSAPP_NATIVE_PG',
    })
    order_keys.record_capture_quarantine(
        keys, payment_id=TXN, reference_id=REFERENCE, outcome='PROVIDER_UNAVAILABLE')
    fake_ddb.Table(PAYMENT_ATTEMPTS_TABLE).put_item(Item={
        'paymentAttemptId': 'attempt-redrive',
        'referenceId': REFERENCE,
        'status': 'PAYMENT_REQUEST_SENT',
    })
    fake_ddb.Table(INVOICES_TABLE).put_item(Item={
        'invoiceId': 'invoice-redrive',
        'referenceId': REFERENCE,
        'paymentStatus': 'failed',
    })
    fake_ddb.Table(WEBHOOK_LOG_TABLE).put_item(Item={
        'id': 'audit-redrive',
        'paymentId': TXN,
        'eventType': 'payment.captured',
        'processedAt': 123,
        'rawPayload': json.dumps(_commerce_event()),
    })


def test_redrive_requires_existing_quarantine(webhook, fake_ddb):
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)):
        result = webhook._redrive_quarantined_capture(REFERENCE, TXN, 'req-redrive')
    assert result == {'status': 'REFUSED', 'reason': 'QUARANTINE_NOT_FOUND'}


def test_redrive_uses_stored_audit_and_resolves_only_after_paid_state(webhook, fake_ddb):
    _seed_redrive(fake_ddb)
    hybrid = _HybridDynamo(fake_ddb)

    def replay(_event_data, _request_id):
        keys = fake_ddb.Table(KEYS_TABLE)
        keys.put_item(Item={
            'orderId': order_keys.PROVIDER_PAYMENT_PREFIX + TXN,
            'kind': 'PROVIDER_PAYMENT_CLAIM',
            'providerTransactionId': TXN,
            'paymentAttemptId': 'attempt-redrive',
            'orderIdRef': 'order-redrive',
        })
        keys.put_item(Item={
            'orderId': order_keys.PAYMENT_ATTEMPT_PREFIX + 'attempt-redrive',
            'kind': 'PAYMENT_ATTEMPT_ORDER',
            'paymentAttemptId': 'attempt-redrive',
            'orderIdRef': 'order-redrive',
            'orderNumber': 'WD-ORD-23456789',
        })
        fake_ddb.Table(PAYMENT_ATTEMPTS_TABLE).update_item(
            Key={'paymentAttemptId': 'attempt-redrive'},
            UpdateExpression='SET #s = :paid, providerPaymentId = :pid',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':paid': 'PAYMENT_PAID', ':pid': TXN},
        )
        fake_ddb.Table(INVOICES_TABLE).update_item(
            Key={'invoiceId': 'invoice-redrive'},
            UpdateExpression='SET paymentStatus = :paid',
            ExpressionAttributeValues={':paid': 'paid'},
        )

    with patch.object(webhook, 'dynamodb', hybrid), \
            patch.object(webhook, '_handle_payment_captured', side_effect=replay) as drive:
        result = webhook._redrive_quarantined_capture(REFERENCE, TXN, 'req-redrive')

    assert result['status'] == 'RESOLVED'
    assert result['orderId'] == 'order-redrive'
    drive.assert_called_once()
    parked = order_keys.resolve_capture_quarantine(fake_ddb.Table(KEYS_TABLE), TXN)
    assert parked['status'] == 'RESOLVED'
    assert parked['resolvedOrderId'] == 'order-redrive'


def test_redrive_internal_action_is_not_reachable_from_http(webhook):
    response = webhook.handler({
        'internalAction': 'redriveQuarantinedCapture',
        'referenceId': REFERENCE,
        'paymentId': TXN,
        'requestContext': {},
    }, None)
    assert response['statusCode'] == 403
