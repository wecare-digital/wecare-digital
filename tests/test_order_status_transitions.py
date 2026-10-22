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
              CONTACTS: 'contactId', KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'},
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
    inv = {'invoiceId': INVOICE_ID, 'customerPhone': phone, 'referenceId': reference,
           'status': 'paid' if paid else 'pending_payment',
           'paymentStatus': 'captured' if paid else 'pending',
           'customerName': 'QA Recipient', 'createdAt': 1770000000}
    if order_status is not None:
        inv['orderStatus'] = order_status
    fake.Table(INVOICES).put_item(Item=inv)
    return inv


def _send(engine, fake, lam, *, target, phone_id=WABA1, description='', invoice_result=None):
    if invoice_result is None:
        invoice_result = {'statusCode': 200, 'body': json.dumps({'status': 'sent'})}
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', lam), \
            patch.object(engine, 'send_invoice_whatsapp', return_value=invoice_result) as invoice_send:
        ddb.Table.side_effect = fake.Table
        with patch.object(engine, '_lookup_contact_by_phone',
                          return_value={'contactId': 'contact-ost'}):
            response = engine.send_order_status(INVOICE_ID, target, description, phone_id, 'req-ost')
    return response, invoice_send


def _status(resp):
    return resp['statusCode']


def _body(resp):
    return json.loads(resp['body'])


class TestTheGuardedRoute:
    def test_shipped_on_a_paid_processing_order_sends_and_records(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=200)
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 200, resp
        assert _body(resp)['orderStatus'] == 'shipped'
        # No separate Meta order-status message is sent. The customer-facing message is the
        # approved invoice-image template sent by send_invoice_whatsapp below.
        assert lam.invokes == []
        # The local fulfilment row advances before invoice-template delivery.
        row = fake.Table(INVOICES).get_item(Key={'invoiceId': INVOICE_ID})['Item']
        assert row['orderStatus'] == 'shipped'
        invoice_send.assert_called_once_with(INVOICE_ID, PHONE, WABA1, 'req-ost', force=True)
        assert _body(resp)['invoiceTemplate'] == 'wecare_default_invoice_image_template'

    def test_a_row_with_no_recorded_status_defaults_to_processing(self, engine, fake):
        # Capture set processing even if the attribute was never written; shipped is legal.
        _seed(fake, order_status=None)
        lam = _RecordingLambda(status=200)
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 200, resp

    def test_an_unpaid_order_cannot_be_fulfilled(self, engine, fake):
        _seed(fake, paid=False)
        lam = _RecordingLambda()
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 400
        assert _body(resp)['code'] == 'ORDER_NOT_PAID'
        assert lam.invokes == []  # nothing sent

    def test_an_illegal_transition_is_refused_with_a_named_reason(self, engine, fake):
        _seed(fake, order_status='completed')
        lam = _RecordingLambda()
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 409
        assert _body(resp)['code'] == 'ORDER_STATUS_TRANSITION_INVALID'
        assert lam.invokes == []

    def test_resending_the_same_status_is_refused(self, engine, fake):
        _seed(fake, order_status='shipped')
        lam = _RecordingLambda()
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 409
        assert _body(resp)['code'] == 'ORDER_STATUS_UNCHANGED'
        assert lam.invokes == []

    def test_a_non_staff_target_is_refused(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda()
        for bad in ('pending', 'canceled', 'nonsense'):
            resp, invoice_send = _send(engine, fake, lam, target=bad)
            assert _status(resp) == 400, bad
            assert _body(resp)['code'] == 'ORDER_STATUS_NOT_ALLOWED', bad
        assert lam.invokes == []

    def test_only_a_payment_waba_may_send(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda()
        resp, invoice_send = _send(engine, fake, lam, target='shipped', phone_id=WABA2)
        assert _status(resp) == 409
        assert _body(resp)['code'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
        assert lam.invokes == []

    def test_no_separate_meta_order_status_message_is_sent(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=400)
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 200
        assert lam.invokes == []
        invoice_send.assert_called_once_with(INVOICE_ID, PHONE, WABA1, 'req-ost', force=True)

    def test_description_does_not_create_a_second_customer_message(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=200)
        _response, invoice_send = _send(engine, fake, lam, target='shipped',
              description='Shipped via BlueDart, AWB 12345.')
        assert lam.invokes == []
        invoice_send.assert_called_once_with(INVOICE_ID, PHONE, WABA1, 'req-ost', force=True)

    def test_invoice_failure_reports_partial_success_after_status_applied(self, engine, fake):
        _seed(fake, order_status='processing')
        lam = _RecordingLambda(status=200)
        resp, invoice_send = _send(engine, fake, lam, target='shipped', invoice_result={
            'statusCode': 500, 'body': json.dumps({'status': 'failed'})})
        assert _status(resp) == 502
        body = _body(resp)
        assert body['code'] == 'ORDER_STATUS_INVOICE_SEND_FAILED'
        assert body['orderStatusApplied'] is True
        assert body['orderStatus'] == 'shipped'
        invoice_send.assert_called_once_with(INVOICE_ID, PHONE, WABA1, 'req-ost', force=True)

    def test_a_missing_invoice_is_404(self, engine, fake):
        lam = _RecordingLambda()
        resp, invoice_send = _send(engine, fake, lam, target='shipped')
        assert _status(resp) == 404
        assert lam.invokes == []
