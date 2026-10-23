"""The staff-driven WhatsApp order_status fulfilment sender and its transition rules.

Capture auto-sends `processing` (razorpay-webhook). This file covers the NEXT step: a staff member
in Pay Flow marking a PAID order `shipped`/`completed`, which `invoice-engine.send_order_status`
validates against WhatsApp's transition rules before invoking the sender. The rules themselves
live in `wa_order_status`; these tests pin both the rules and the guarded route.

No network: the outbound Lambda is a recording stub, and storage is the in-memory FakeDynamo.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(REPO, 'tests'))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import wa_order_status as wos  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ITEMS = 'stack-wecare-digital-InvoiceItemsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
CONTACTS = 'stack-wecare-digital-ContactsTable'
KEYS = 'stack-wecare-digital-CommerceKeys'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'
ORDERS = 'stack-wecare-digital-OrderTable'
ORDER_ID = 'order-orderstatus-0001'

INVOICE_ID = 'inv-orderstatus-0001'
REFERENCE = 'WD-PAY-OST12345'
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1
WABA2 = 'phone-number-id-waba-t-direct-1055232054343117'


# ══════════════════════════════════════════════════════════════════════════════
# the pure transition vocabulary
# ══════════════════════════════════════════════════════════════════════════════

class TestTheVocabulary:
    def test_the_wire_spellings_are_the_meta_set(self):
        assert wos.ALL_STATUSES == {
            'pending', 'processing', 'partially-shipped', 'shipped', 'completed', 'canceled'}

    def test_staff_targets_exclude_pending_and_canceled(self):
        # `pending` is the opening state, and cancelling a PAID order is Meta 2047 — the
        # unpaid-cancel path is the invoice cancel, not this one.
        assert wos.STAFF_FULFILMENT_TARGETS == {
            'processing', 'partially-shipped', 'shipped', 'completed'}
        assert 'pending' not in wos.STAFF_FULFILMENT_TARGETS
        assert 'canceled' not in wos.STAFF_FULFILMENT_TARGETS

    def test_the_underscore_form_of_partially_shipped_is_accepted(self):
        assert wos.normalise('partially_shipped') == 'partially-shipped'
        assert wos.is_valid('partially_shipped')

    def test_forward_transitions_are_legal_and_backward_ones_are_not(self):
        assert wos.can_transition('processing', 'shipped')
        assert wos.can_transition('processing', 'completed')
        assert wos.can_transition('partially-shipped', 'shipped')
        assert wos.can_transition('shipped', 'completed')
        # Backward / skip-back is refused.
        assert not wos.can_transition('shipped', 'processing')
        assert not wos.can_transition('completed', 'shipped')

    def test_a_blank_current_status_is_treated_as_pending(self):
        # Capture left `processing`; a row with nothing recorded is still safe to move forward.
        assert wos.can_transition('', 'processing')
        assert not wos.can_transition('', 'shipped')  # pending -> shipped skips processing

    def test_resending_the_same_status_is_not_a_transition(self):
        assert not wos.can_transition('shipped', 'shipped')

    def test_terminal_states_go_nowhere(self):
        assert not wos.can_transition('completed', 'canceled')
        assert not wos.can_transition('canceled', 'processing')


# ══════════════════════════════════════════════════════════════════════════════
# the guarded route
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, ENGINE_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    return module


@pytest.fixture
def fake():
    return FakeDynamo(
        keys={INVOICES: 'invoiceId', ITEMS: 'invoiceId', DELIVERY: 'invoiceId',
              CONTACTS: 'contactId', KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId',
              ORDERS: 'orderId'},
        base_query_tables={ITEMS, DELIVERY})


class _RecordingLambda:
    """Records every outbound invoke and answers with a configurable status code."""

    def __init__(self, status=200):
        self.invokes = []
        self.status = status

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        body = json.dumps({'statusCode': self.status,
                           'body': json.dumps({'status': 'sent',
                                               'whatsappMessageId': 'wamid.OSTEST'})})

        class _Payload:
            def read(self_inner):
                return body.encode()

        return {'Payload': _Payload(), 'StatusCode': 200}

    def sent_payloads(self):
        out = []
        for call in self.invokes:
            raw = json.loads(call['Payload'])
            out.append(json.loads(raw['body']) if 'body' in raw else raw)
        return out


def _seed(fake, *, paid=True, order_status=None, phone=PHONE, reference=REFERENCE):
    inv = {'invoiceId': INVOICE_ID, 'orderId': ORDER_ID,
           'customerPhone': phone, 'referenceId': reference,
           'status': 'paid' if paid else 'pending_payment',
           'paymentStatus': 'captured' if paid else 'pending',
           'customerName': 'QA Recipient', 'createdAt': 1770000000}
    if order_status is not None:
        inv['orderStatus'] = order_status
    fake.Table(INVOICES).put_item(Item=inv)
    fake.Table(ORDERS).put_item(Item={
        'orderId': ORDER_ID,
        'status': order_status or 'processing',
        'orderStatus': order_status or 'processing',
        'referenceId': reference,
    })
    return inv


def _send(engine, fake, lam, *, target, phone_id=WABA1, description=''):
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', lam):
        ddb.Table.side_effect = fake.Table
        with patch.object(engine, '_lookup_contact_by_phone',
                          return_value={'contactId': 'contact-ost'}):
            return engine.send_order_status(INVOICE_ID, target, description, phone_id, 'req-ost')


def _status(resp):
    return resp['statusCode']


def _body(resp):
    return json.loads(resp['body'])


class TestTheGuardedRoute:
    def test_shipped_on_a_paid_processing_order_sends_and_records(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=200)
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 200, resp
        assert _body(resp)['orderStatus'] == 'shipped'
        # The outbound Lambda receives the canonical orderStatusDetails transport contract.
        payloads = lam.sent_payloads()
        assert len(payloads) == 1
        assert 'isOrderStatus' not in payloads[0]
        assert payloads[0]['orderStatusDetails']['order_status'] == 'shipped'
        assert payloads[0]['orderStatusDetails']['reference_id'] == REFERENCE
        # The row advanced only after the send succeeded.
        row = fake.Table(INVOICES).get_item(Key={'invoiceId': INVOICE_ID})['Item']
        assert row['orderStatus'] == 'shipped'
        order = fake.Table(ORDERS).get_item(Key={'orderId': ORDER_ID})['Item']
        assert order['status'] == 'shipped'
        assert order['orderStatus'] == 'shipped'

    def test_a_row_with_no_recorded_status_defaults_to_processing(self, engine, fake):
        # Capture set processing even if the attribute was never written; shipped is legal.
        _seed(fake, order_status=None)
        lam = _RecordingLambda(status=200)
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 200, resp

    def test_an_unpaid_order_cannot_be_fulfilled(self, engine, fake):
        _seed(fake, paid=False)
        lam = _RecordingLambda()
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 400
        assert _body(resp)['code'] == 'ORDER_NOT_PAID'
        assert lam.invokes == []  # nothing sent

    def test_an_illegal_transition_is_refused_with_a_named_reason(self, engine, fake):
        _seed(fake, order_status='completed')
        lam = _RecordingLambda()
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 409
        assert _body(resp)['code'] == 'ORDER_STATUS_TRANSITION_INVALID'
        assert lam.invokes == []

    def test_resending_the_same_status_is_refused(self, engine, fake):
        _seed(fake, order_status='shipped')
        lam = _RecordingLambda()
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 409
        assert _body(resp)['code'] == 'ORDER_STATUS_UNCHANGED'
        assert lam.invokes == []

    def test_a_non_staff_target_is_refused(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda()
        for bad in ('pending', 'canceled', 'nonsense'):
            resp = _send(engine, fake, lam, target=bad)
            assert _status(resp) == 400, bad
            assert _body(resp)['code'] == 'ORDER_STATUS_NOT_ALLOWED', bad
        assert lam.invokes == []

    def test_only_a_payment_waba_may_send(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda()
        resp = _send(engine, fake, lam, target='shipped', phone_id=WABA2)
        assert _status(resp) == 409
        assert _body(resp)['code'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
        assert lam.invokes == []

    def test_a_meta_rejection_does_not_advance_the_recorded_status(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=400)  # Meta refused (e.g. 2046)
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 502
        assert _body(resp)['code'] == 'ORDER_STATUS_REJECTED'
        # The row still reads `processing`: the wire is the authority.
        row = fake.Table(INVOICES).get_item(Key={'invoiceId': INVOICE_ID})['Item']
        assert row['orderStatus'] == 'processing'
        order = fake.Table(ORDERS).get_item(Key={'orderId': ORDER_ID})['Item']
        assert order['orderStatus'] == 'processing'

    def test_a_custom_description_rides_through_to_the_customer(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=200)
        _send(engine, fake, lam, target='shipped',
              description='Shipped via BlueDart, AWB 12345.')
        detail = lam.sent_payloads()[0]['orderStatusDetails']
        assert detail['description'] == 'Shipped via BlueDart, AWB 12345.'

    def test_a_missing_invoice_is_404(self, engine, fake):
        lam = _RecordingLambda()
        resp = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 404
        assert lam.invokes == []
