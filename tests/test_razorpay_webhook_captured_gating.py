"""C1 + A17: the reconciliation verdict gates every financial-success side effect.

Before this fix, `_handle_payment_captured` resolved a referenceId and then ran EVERY
commerce financial-success effect on `if reference_id:` truthiness alone: it stored a
money-confirmed 'captured' payment record, marked the invoice paid, generated the receipt,
attributed the purchase to the ad platform, and sent the customer an order_status
'completed' confirmation - none of which ever consulted whether the payment actually
verified as PAID. The typed reconciliation outcome returned by
`_create_order_for_captured_payment` was discarded.

These tests drive the WHOLE callback (not the reconciler in isolation) and assert that the
verdict, not the event body, decides. They also assert the A17 log sanitisation: the
payment_captured log carries only correlation ids and stage, never contact/notes/description/
email/full phone, and the invoice image log no longer emits the image URL.
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

KEYS_TABLE = 'stack-wecare-digital-WixOrderIds'
INVOICES_TABLE = 'stack-wecare-digital-InvoicesTable'
PAYMENTS_TABLE = 'stack-wecare-digital-PaymentsTable'

REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
ATTEMPT = '01930000-0000-7000-8000-000000000001'
TXN = 'pay_LIVE0000000001'
AMOUNT = 59900  # paise
CONTACT = '+919876543210'
FULL_PHONE = '9876543210'


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
    """A DynamoDB fake covering every table the callback touches, with the one index it queries."""
    return FakeDynamo(
        keys={KEYS_TABLE: 'orderId', INVOICES_TABLE: 'invoiceId',
              PAYMENTS_TABLE: 'id'},
        indexes={INVOICES_TABLE: {'referenceId-index': ('referenceId', None)}},
    )


def _seed_attempt(ddb, *, amount=AMOUNT, currency='INR'):
    """A PAYREF# row as the payment-request builder would have written it (commerce path)."""
    table = ddb.Table(KEYS_TABLE)
    order_keys.reserve_payment_reference(
        table, reference_id=REFERENCE, payment_attempt_id=ATTEMPT,
        extra={'customerId': 'CUS_01J0000000000000000000000',
               'amountPaise': amount, 'currency': currency,
               'providerPaymentId': TXN})


PROVIDER_ORDER = 'order_ABC'


def _seed_invoice(ddb, *, reference_id=REFERENCE, total='599.00', status='sent',
                  invoice_id='INV-LEGACY-1', provider_order_id=PROVIDER_ORDER):
    """A legacy invoice row keyed by referenceId, with NO PaymentAttempt.

    R2: a genuine legacy invoice carries a stored provider binding (providerOrderId) so a capture
    can be positively tied to it. Pass provider_order_id='' to seed an UNBOUND invoice.
    """
    item = {
        'invoiceId': invoice_id, 'referenceId': reference_id,
        'total': Decimal(total), 'status': status,
        'customerPhone': CONTACT, 'invoiceNumber': 'WD/2627/00001',
    }
    if provider_order_id:
        item['providerOrderId'] = provider_order_id
    ddb.Table(INVOICES_TABLE).put_item(Item=item)


def _event(*, notes=None, amount=AMOUNT, payment_id=TXN, order_id='order_ABC',
           contact=CONTACT):
    return {'payment': {'entity': {
        'id': payment_id, 'order_id': order_id, 'amount': amount,
        'currency': 'INR', 'status': 'captured', 'method': 'upi',
        'contact': contact, 'email': 'buyer@example.com',
        'description': 'Sensitive order description',
        'notes': notes if notes is not None else {'referenceId': REFERENCE,
                                                   'secretField': 'do-not-log-me'},
    }}}


class _Spies:
    """Records which financial-success side effects the callback performed."""

    def __init__(self, webhook):
        self.webhook = webhook
        self.lambda_client = MagicMock()
        # Post-payment invoice-engine returns a fresh (non-dedup) invoice so the image
        # step runs and its A17 log line is exercised.
        self.lambda_client.invoke.return_value = {
            'Payload': _payload_stream({'body': json.dumps({
                'invoiceId': 'INV-CREATED-1', 'invoiceNumber': 'WD/2627/00002',
                'deduplicated': False, 'imageUrl': 'https://signed.example/receipt.png'})})}

    def __enter__(self):
        self._patchers = [
            patch.object(self.webhook, 'lambda_client', self.lambda_client),
            patch.object(self.webhook, '_mark_invoice_paid_by_reference'),
            patch.object(self.webhook, '_mark_invoice_paid_by_phone_and_amount'),
            patch.object(self.webhook, '_post_payment_handler'),
            patch.object(self.webhook, '_log_ctwa_purchase'),
            patch.object(self.webhook, '_store_payment_record'),
        ]
        self._patchers[0].start()
        self.mark_by_ref = self._patchers[1].start()
        self.mark_by_phone = self._patchers[2].start()
        self.post_payment = self._patchers[3].start()
        self.ctwa = self._patchers[4].start()
        self.store = self._patchers[5].start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()

    @property
    def order_status_sends(self):
        """Count of order_status WhatsApp confirmations sent to the customer."""
        n = 0
        for call in self.lambda_client.invoke.call_args_list:
            payload = call.kwargs.get('Payload') or (call.args[0] if call.args else '')
            if 'isOrderStatus' in str(payload) or 'order_status' in str(payload):
                n += 1
        return n


def _payload_stream(obj):
    stream = MagicMock()
    stream.read.return_value = json.dumps(obj).encode('utf-8')
    return stream


class _InvoiceRawQueryTable:
    """Wraps a FakeTable so the handler's raw-string `referenceId = :ref` query resolves.

    The production handler queries InvoicesTable with a raw KeyConditionExpression string,
    while FakeDynamo only understands boto3 `Key(...).eq(...)` objects. This shim translates
    the one query shape the callback uses so the legacy-invoice path can be exercised
    end-to-end, and otherwise delegates to the underlying fake (which still enforces
    ConditionExpressions and armed failures).
    """

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
        return self._t.query(IndexName=IndexName,
                             KeyConditionExpression=KeyConditionExpression,
                             ExpressionAttributeValues=ExpressionAttributeValues,
                             Limit=Limit)

    def __getattr__(self, name):
        return getattr(self._t, name)


class _HybridDynamo:
    """A dynamodb resource whose InvoicesTable understands the callback's raw-string query."""

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


def _drive(webhook, ddb, event, *, verifier):
    with patch.object(webhook, 'dynamodb', _HybridDynamo(ddb)):
        with patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier):
            webhook._handle_payment_captured(event, 'req-1')


def _order_count(ddb):
    keys = ddb.tables.get(KEYS_TABLE, {})
    return len([k for k in keys if str(k).startswith(order_keys.ORDER_NUMBER_PREFIX)])


# ══════════════════════════════════════════════════════════════════════════════
# (a) an unverified commerce capture produces ZERO financial-success effects
# ══════════════════════════════════════════════════════════════════════════════

def test_not_paid_commerce_capture_fires_no_side_effects(webhook, fake_ddb):
    """The provider says NOT captured (a forged, signature-valid event). Nothing runs."""
    _seed_attempt(fake_ddb)
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (False, '', 0, ''))

        assert _order_count(fake_ddb) == 0
        spies.mark_by_ref.assert_not_called()
        spies.mark_by_phone.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.ctwa.assert_not_called()
        spies.store.assert_not_called()          # no money-confirmed 'captured' record
        assert spies.order_status_sends == 0


def test_amount_mismatch_commerce_capture_fires_no_side_effects(webhook, fake_ddb):
    """Money moved but not for the attempt's amount: paid-but-blocked, never a success effect."""
    _seed_attempt(fake_ddb, amount=AMOUNT)
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT + 1, 'INR'))

        assert _order_count(fake_ddb) == 0
        spies.mark_by_ref.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.ctwa.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


def test_currency_mismatch_commerce_capture_fires_no_side_effects(webhook, fake_ddb):
    _seed_attempt(fake_ddb)
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'USD'))

        spies.mark_by_ref.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.ctwa.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


def test_unknown_reference_with_no_invoice_fires_no_side_effects(webhook, fake_ddb):
    """No PaymentAttempt AND no invoice row. Absence is not evidence: quarantine, run nothing."""
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        assert _order_count(fake_ddb) == 0
        spies.mark_by_ref.assert_not_called()
        spies.mark_by_phone.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.ctwa.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


# ══════════════════════════════════════════════════════════════════════════════
# (b) an authoritatively verified PAID capture produces exactly the intended effects, once
# ══════════════════════════════════════════════════════════════════════════════

def test_verified_paid_commerce_capture_fires_each_effect_exactly_once(webhook, fake_ddb):
    _seed_attempt(fake_ddb)
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        assert _order_count(fake_ddb) == 1
        assert spies.store.call_count == 1
        assert spies.store.call_args.args[1] == 'captured'
        assert spies.mark_by_ref.call_count == 1
        assert spies.post_payment.call_count == 1
        assert spies.ctwa.call_count == 1
        assert spies.order_status_sends == 1


# ══════════════════════════════════════════════════════════════════════════════
# (c) a provider-verified legacy invoice-only capture still marks paid + runs post-payment
# ══════════════════════════════════════════════════════════════════════════════

def test_verified_legacy_invoice_marks_paid_and_runs_post_payment(webhook, fake_ddb):
    """No PaymentAttempt, but a BOUND invoice row exists AND the provider confirms the amount."""
    _seed_invoice(fake_ddb, total='599.00')
    with _Spies(webhook) as spies:
        with patch('lambda_utils.integrations.razorpay_verify.payment_capture_details',
                   return_value=(True, AMOUNT, 'INR', PROVIDER_ORDER)):
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        # No commerce order (no attempt), but the legacy invoice is honoured.
        assert _order_count(fake_ddb) == 0
        assert spies.mark_by_ref.call_count == 1
        assert spies.post_payment.call_count == 1
        assert spies.store.call_count == 1
        assert spies.order_status_sends == 1


def test_legacy_invoice_with_provider_amount_mismatch_quarantines(webhook, fake_ddb):
    """Invoice exists, but the provider captured a different amount. Do not mark it paid."""
    _seed_invoice(fake_ddb, total='599.00')
    with _Spies(webhook) as spies:
        with patch('lambda_utils.integrations.razorpay_verify.payment_capture_details',
                   return_value=(True, AMOUNT + 100, 'INR', PROVIDER_ORDER)):
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        spies.mark_by_ref.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


def test_legacy_invoice_not_captured_by_provider_quarantines(webhook, fake_ddb):
    """Invoice exists, but the provider says the payment is NOT captured. Nothing runs."""
    _seed_invoice(fake_ddb, total='599.00')
    with _Spies(webhook) as spies:
        with patch('lambda_utils.integrations.razorpay_verify.payment_capture_details',
                   return_value=(False, 0, '', '')):
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        spies.mark_by_ref.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


# ══════════════════════════════════════════════════════════════════════════════
# (d) storage / reconciliation failure enters a bounded NEEDS_RECONCILIATION quarantine
# ══════════════════════════════════════════════════════════════════════════════

def test_reconciliation_error_quarantines_without_side_effects(webhook, fake_ddb):
    """The reconciler raised internally (swallowed to RECONCILIATION_ERROR). Nothing runs."""
    _seed_attempt(fake_ddb)

    def explode(_ref):
        raise RuntimeError('provider unreachable')

    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(), verifier=explode)

        spies.mark_by_ref.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.ctwa.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


def test_unknown_reference_with_invoice_query_failure_quarantines(webhook, fake_ddb):
    """No attempt; the invoice lookup itself fails. Quarantine, and do not double-write."""
    fake_ddb.arm_failure(INVOICES_TABLE, 'query', RuntimeError('invoices unavailable'))
    with _Spies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

        spies.mark_by_ref.assert_not_called()
        spies.mark_by_phone.assert_not_called()
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()
        assert spies.order_status_sends == 0


def test_quarantine_emits_a_single_staff_alert(webhook, fake_ddb, caplog):
    """The quarantine path must leave exactly one alert log for staff, and no double-write."""
    with _Spies(webhook):
        with caplog.at_level('ERROR'):
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

    alerts = [r for r in caplog.records
              if 'capture_needs_reconciliation' in r.getMessage()]
    assert len(alerts) == 1
    assert 'NEEDS_RECONCILIATION' in alerts[0].getMessage()


# ══════════════════════════════════════════════════════════════════════════════
# A17: the touched log lines carry no sensitive payment/customer metadata
# ══════════════════════════════════════════════════════════════════════════════

def test_payment_captured_log_omits_contact_notes_description_email(webhook, fake_ddb, caplog):
    _seed_attempt(fake_ddb)
    with _Spies(webhook):
        with caplog.at_level('INFO'):
            _drive(webhook, fake_ddb,
                   _event(notes={'referenceId': REFERENCE, 'secretField': 'do-not-log-me'}),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'))

    lines = [r.getMessage() for r in caplog.records if '"payment_captured"' in r.getMessage()]
    assert lines, 'the payment_captured receipt log should still be emitted'
    blob = '\n'.join(lines)
    # referenceId as a correlation id is retained; everything sensitive is gone.
    assert REFERENCE in blob
    assert CONTACT not in blob
    assert FULL_PHONE not in blob
    assert 'do-not-log-me' not in blob
    assert 'secretField' not in blob
    assert 'buyer@example.com' not in blob
    assert 'Sensitive order description' not in blob


def test_invoice_image_log_omits_the_image_url(webhook, fake_ddb, caplog):
    """_post_payment_handler logs invoice image generation; the signed URL must not appear."""
    image_url = 'https://signed.example/receipt-should-not-be-logged.png'
    lambda_client = MagicMock()

    def _invoke(**kwargs):
        payload = kwargs.get('Payload', '')
        if 'generate-image' in str(payload):
            return {'Payload': _payload_stream({'body': json.dumps({'imageUrl': image_url})})}
        # from-payment create call
        return {'Payload': _payload_stream({'body': json.dumps({
            'invoiceId': 'INV-CREATED-1', 'invoiceNumber': 'WD/2627/00002',
            'deduplicated': False})})}

    lambda_client.invoke.side_effect = _invoke
    with patch.object(webhook, 'lambda_client', lambda_client):
        with caplog.at_level('INFO'):
            # `amount` and `currency` are gone from this signature: measured, neither name
            # occurred in the body after the signature, so they were dead parameters carrying a
            # float on a money path and are deleted rather than retyped.
            webhook._post_payment_handler(
                TXN, CONTACT, 'buyer@example.com', 'desc', {}, 'req-1')

    lines = [r.getMessage() for r in caplog.records
             if 'invoice_image_generated' in r.getMessage()]
    assert lines, 'the invoice_image_generated log should still be emitted'
    blob = '\n'.join(lines)
    assert image_url not in blob
    assert 'INV-CREATED-1' in blob  # the invoice id (a safe correlation id) is retained
