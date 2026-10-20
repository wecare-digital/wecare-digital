"""N1 / website-only ruling: the in-WhatsApp payment CAPTURED branch is retired.

The owner's 2026-10-01 ruling is website-only checkout ("yes no whatsapp all in the
website"). The Meta/WhatsApp payment-status producer in
``amplify/functions/messaging/inbound-whatsapp-handler/handler.py`` used to accept an
UNVERIFIED capture fail-open (the Meta Payment Lookup is advisory and
``PAYMENT_LOOKUP_REQUIRED`` defaults off) and then mint paid state:
``_mark_invoice_paid_by_reference``, a 'completed' ``_send_order_status_message``,
``_generate_invoice_for_captured_payment`` and ``_check_and_notify_balance_due``.

These tests drive the REAL ``_process_payment_status`` against an in-memory DynamoDB
fake with a forged (unverified) 'captured' event and assert it creates NO paid invoice
and NO receipt/order — no financial mutation at all — while a non-payment status event
still processes normally.

The dead inbound paid-state writers (``_mark_invoice_paid_by_reference``,
``_generate_invoice_for_captured_payment``, ``_check_and_notify_balance_due`` and its
``_auto_next_due_enabled`` toggle) were DELETED from this handler (FINDING 6 + FINDING 7),
not merely left uncalled — the Razorpay webhook is the single authoritative paid-state
setter and this handler holds no parallel writer. So these tests additionally assert the
writers no longer EXIST on the module (``not hasattr``), which proves the retirement
cannot be reverted by a one-line re-wire, while still proving a forged capture settles
nothing.

No AWS and no network: ``boto3`` is patched at import and ``urllib`` is never allowed to
reach out (the forged event carries no ``paymentConfigName``, so the Payment Lookup API is
never addressed — the outcome is ``unverified_no_payment_config``, the exact fail-open path
that previously settled).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest
from unittest.mock import patch

INBOUND_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler')
INBOUND_HANDLER_PATH = os.path.join(INBOUND_HANDLER_DIR, 'handler.py')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, INBOUND_HANDLER_DIR)
sys.path.insert(0, os.path.join(INBOUND_HANDLER_DIR, 'modules'))


REFERENCE_ID = 'WD-PAY-SUPERSEDED-1'
INVOICE_ID = 'inv-superseded-1'


class _RecordingTable:
    """A per-table fake that records every write and answers the one query the handler makes.

    Only the handful of operations ``_process_payment_status`` performs are supported;
    anything else raises so a silent behaviour change surfaces as a test failure rather
    than a false pass. Items are matched by the ``referenceId-index`` GSI the real
    ``_mark_invoice_paid_by_reference`` uses.
    """

    def __init__(self, name, store):
        self.name = name
        self._items = store  # list of item dicts, shared view for assertions
        self.update_calls = []
        self.put_calls = []

    # -- reads -----------------------------------------------------------
    def query(self, **kwargs):
        index = kwargs.get('IndexName', '')
        values = kwargs.get('ExpressionAttributeValues', {})
        ref = values.get(':ref')
        if index in ('referenceId-index', 'paymentReferenceId-index'):
            matched = [i for i in self._items
                       if i.get('referenceId') == ref or i.get('paymentReferenceId') == ref]
            return {'Items': matched}
        # Outbound phone-id / config lookup: nothing seeded, so nothing found.
        return {'Items': []}

    def scan(self, **kwargs):
        return {'Items': []}

    def get_item(self, **kwargs):
        return {}

    # -- writes (the thing under test must NOT touch invoices) -----------
    def update_item(self, **kwargs):
        self.update_calls.append(kwargs)
        return {}

    def put_item(self, **kwargs):
        self.put_calls.append(kwargs)
        return {}


class _Dynamo:
    """``dynamodb.Table(name)`` -> a stable per-name recording table."""

    def __init__(self):
        self.tables = {}
        self.stores = {}

    def seed(self, name, items):
        self.stores.setdefault(name, []).extend(items)

    def Table(self, name):
        if name not in self.tables:
            store = self.stores.setdefault(name, [])
            self.tables[name] = _RecordingTable(name, store)
        return self.tables[name]


def _load_inbound_handler():
    """Load the inbound-whatsapp-handler's handler.py from its absolute path.

    A bare ``import handler`` here is fragile: another test (the FEAT-002 webhook test) also
    inserts its own razorpay-webhook directory at the front of ``sys.path`` and imports the bare
    name ``handler``, so collection order could resolve ``handler`` to the WEBHOOK module (which has
    no ``_process_payment_status``). Evicting any stale ``handler`` from ``sys.modules`` and loading
    this exact file by path makes the import deterministic regardless of collection order, mirroring
    ``tests/test_seo_engine.py``'s ``_load`` and the webhook fixture's stale-eviction pattern.
    """
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, os.path.join(INBOUND_HANDLER_DIR, 'modules'))
    sys.path.insert(0, INBOUND_HANDLER_DIR)
    spec = importlib.util.spec_from_file_location('handler', INBOUND_HANDLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['handler'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def handler_env():
    """Import the real handler with boto3 patched, wire a recording DynamoDB, seed an invoice."""
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            h = _load_inbound_handler()

    dynamo = _Dynamo()
    # An UNPAID invoice that matches the reference exactly as the fail-open path would have settled.
    dynamo.seed(h.INVOICES_TABLE, [{
        'invoiceId': INVOICE_ID,
        'referenceId': REFERENCE_ID,
        'status': 'pending',
    }])

    with patch.object(h, 'dynamodb', dynamo):
        yield h, dynamo


def _captured_event(reference_id=REFERENCE_ID):
    """A forged WhatsApp 'captured' payment status webhook — nothing verifies it."""
    return {
        'id': 'wamid.superseded',
        'recipient_id': '919876543210',
        'type': 'payment',
        'status': 'captured',
        'payment': {
            'reference_id': reference_id,
            'amount': {'value': 10000, 'offset': 100},
            'currency': 'INR',
            'transaction': {'id': 'txn_forged', 'type': 'upi', 'status': 'success'},
        },
        'timestamp': '1790068200',
    }


def _live_plural_captured_event(reference_id=REFERENCE_ID):
    """The live Meta ORDER_DETAILS shape: plural transactions with gateway ids."""
    return {
        'id': 'wamid.live-shape',
        'recipient_id': '919876543210',
        'type': 'payment',
        'status': 'captured',
        'payment': {
            'reference_id': reference_id,
            'amount': {'value': 224, 'offset': 100},
            'currency': 'INR',
            'transactions': [{
                'id': 'order_Tq0ZgogHP8upGD',
                'pg_transaction_id': 'pay_Tq0awsJn5nCvE8',
                'type': 'razorpay',
                'status': 'success',
                'method': {'type': 'card'},
            }],
        },
        'timestamp': '1790068200',
    }


def _invoice_rows(dynamo, h):
    return dynamo.Table(h.INVOICES_TABLE)


def _paid_update_calls(table):
    """update_item calls that would flip an invoice to paid."""
    out = []
    for call in table.update_calls:
        vals = call.get('ExpressionAttributeValues', {})
        if vals.get(':st') == 'paid' or 'paid' in {str(v) for v in vals.values()}:
            out.append(call)
    return out


class TestCapturedBranchIsRetired:
    def test_forged_capture_creates_no_paid_invoice(self, handler_env):
        """The core N1 assertion: an unverified capture settles NOTHING."""
        h, dynamo = handler_env
        h._process_payment_status(_captured_event(), 'req-superseded')

        invoices = _invoice_rows(dynamo, h)
        assert _paid_update_calls(invoices) == [], (
            'the retired CAPTURED branch must not mark any invoice paid')
        # The seeded invoice is still unpaid.
        assert dynamo.stores[h.INVOICES_TABLE][0]['status'] == 'pending'

    def test_capture_does_not_call_the_financial_side_effects(self, handler_env):
        """The retired writers are DELETED (not just uncalled) and no completed order ships.

        Asserting ``not hasattr`` is stronger than patch-and-assert-not-called: the capture
        branch cannot settle an invoice because the functions that could do so no longer
        exist on the module, so the retirement cannot be reverted by a one-line re-wire.
        """
        h, dynamo = handler_env
        for gone in ('_mark_invoice_paid_by_reference',
                     '_generate_invoice_for_captured_payment',
                     '_check_and_notify_balance_due',
                     '_auto_next_due_enabled'):
            assert not hasattr(h, gone), (
                f'{gone} must be DELETED from the inbound handler, not merely uncalled')

        with patch.object(h, '_send_order_status_message') as order_status:
            h._process_payment_status(_captured_event(), 'req-superseded')

        # Still no paid-state mutation on the recording DynamoDB.
        assert _paid_update_calls(_invoice_rows(dynamo, h)) == []
        # No 'completed' order_status message is minted on capture either.
        for call in order_status.call_args_list:
            assert call.kwargs.get('order_status') != 'completed', (
                'the retired CAPTURED branch must not send a completed order_status')

    def test_capture_emits_a_superseded_audit_record(self, handler_env):
        """A clearly-labelled, type-only SUPERSEDED record keeps the event auditable."""
        h, dynamo = handler_env
        events = []

        def capture_error(msg, *a, **k):
            try:
                events.append(json.loads(msg))
            except (ValueError, TypeError):
                events.append({'raw': msg})

        with patch.object(h.logger, 'error', side_effect=capture_error):
            h._process_payment_status(_captured_event(), 'req-superseded')

        superseded = [e for e in events
                      if e.get('event') == 'in_whatsapp_payment_capture_superseded']
        assert len(superseded) == 1, 'exactly one SUPERSEDED audit record expected'
        record = superseded[0]
        # Type-only / correlation-id only — no event body, no secret, no amount/contact.
        rendered = json.dumps(record)
        assert '919876543210' not in rendered  # recipient id / contact
        assert 'txn_forged' not in rendered     # transaction id
        assert 'amount' not in record
        assert record['referenceId'] == REFERENCE_ID
        assert record['requestId'] == 'req-superseded'

    def test_capture_remains_retired_even_when_lookup_required_is_on(self, handler_env):
        """PAYMENT_LOOKUP_REQUIRED is dead on the financial path: no value re-enables settlement."""
        h, dynamo = handler_env
        # The settlement writers do not exist to be re-enabled, regardless of the toggle.
        assert not hasattr(h, '_mark_invoice_paid_by_reference')
        assert not hasattr(h, '_generate_invoice_for_captured_payment')
        with patch.dict(os.environ, {'PAYMENT_LOOKUP_REQUIRED': 'true'}):
            h._process_payment_status(_captured_event(), 'req-superseded')
        assert _paid_update_calls(_invoice_rows(dynamo, h)) == []
        assert dynamo.stores[h.INVOICES_TABLE][0]['status'] == 'pending'


class TestLivePluralTransactionShape:
    def test_plural_capture_preserves_gateway_evidence_in_message_record(self, handler_env):
        h, dynamo = handler_env
        h._process_payment_status(_live_plural_captured_event(), 'req-live-shape')

        writes = dynamo.Table(h.MESSAGES_TABLE).put_calls
        assert writes, 'payment event should still be stored for audit'
        item = writes[-1]['Item']
        assert item['transactionId'] == 'order_Tq0ZgogHP8upGD'
        assert item['pgTransactionId'] == 'pay_Tq0awsJn5nCvE8'
        assert item['transactionType'] == 'razorpay'
        assert item['transactionStatus'] == 'success'
        assert item['paymentMethodType'] == 'card'

    def test_plural_failed_transaction_drives_effective_failure(self, handler_env):
        h, dynamo = handler_env
        event = _live_plural_captured_event()
        event['status'] = 'pending'
        event['payment']['transactions'][0]['status'] = 'failed'

        with patch.object(h, '_send_order_status_message') as order_status:
            h._process_payment_status(event, 'req-live-failed')

        assert order_status.called
        assert order_status.call_args.kwargs.get('order_status') == 'canceled'


class TestNonFinancialPathsStillWork:
    def test_a_failed_payment_still_notifies_without_settling(self, handler_env):
        """The 'canceled' notification on failure is non-financial and must survive."""
        h, dynamo = handler_env
        event = _captured_event()
        event['status'] = 'failed'
        # The paid-state writer is gone, so failure cannot settle anything either.
        assert not hasattr(h, '_mark_invoice_paid_by_reference')
        with patch.object(h, '_send_order_status_message') as order_status:
            h._process_payment_status(event, 'req-failed')
        # Still notifies the customer their payment failed...
        assert order_status.called
        assert order_status.call_args.kwargs.get('order_status') == 'canceled'
        # ...but settles nothing.
        assert _paid_update_calls(_invoice_rows(dynamo, h)) == []
        assert dynamo.stores[h.INVOICES_TABLE][0]['status'] == 'pending'

    def test_a_delivered_status_update_processes_normally(self, handler_env):
        """A non-payment status webhook (delivery receipt) is untouched by the retirement."""
        h, dynamo = handler_env
        status = {
            'id': 'wamid.delivery',
            'status': 'delivered',
            'timestamp': '1790068200',
            'recipient_id': '919876543210',
        }
        # Must not raise and must not settle any invoice.
        with patch.object(h, '_meter_partner_usage'):
            h._process_status(status, 'req-delivered', waba_id='waba-1')
        invoices = _invoice_rows(dynamo, h)
        assert _paid_update_calls(invoices) == []
        assert dynamo.stores[h.INVOICES_TABLE][0]['status'] == 'pending'
