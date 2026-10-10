"""A rejected payment request is never reported as sent.

Why this file exists
--------------------
Measured live on 2026-10-07, three times out of three: `send_payment_link` invoked
`outbound-whatsapp`, the outbound Lambda refused the send, the refusal was LOGGED, and execution
carried on - the invoice moved to `pending_payment`, the delivery log recorded the word `sent`
with an empty `waMessageId`, and the function answered `200 {'status': 'payment_link_sent'}`. The
send claim taken before the invoke was never released, so the staff retry answered
`200 'send_in_progress'`, deduplicated, and never re-sent. Nothing in the system said the customer
had received nothing.

So the property under test is not "the send works". It is that the three outcomes stay DISTINCT:

  * DEFINITE REJECTION - the invoice is untouched, the delivery row reads `rejected`, the claim is
    released so a retry genuinely re-invokes, and the answer is never 200 `payment_link_sent`;
  * AMBIGUOUS - a 502 carrying `PENDING`, a delivery row reading `unknown` so the send is visible
    at all, and NO auto-resend, because acceptance cannot be inferred from a timeout;
  * ACCEPTANCE - `accepted` (never `sent`, never `delivered`) carrying the real `waMessageId`.

And the sender: only WABA1 may take a payment, so a send from WABA2 is refused with nothing
written and nothing sent.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys, payment_attempt  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ITEMS = 'stack-wecare-digital-InvoiceItemsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
CONTACTS = 'stack-wecare-digital-ContactsTable'
KEYS = 'stack-wecare-digital-WixOrderIds'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'

INVOICE_ID = 'inv-sendtruth-0001'
REFERENCE = 'WD-PAY-TRUTH001'
CUSTOMER = 'contact-sendtruth-0001'
#: A PLACEHOLDER recipient. The 10-digit local number is what the recipient validation reads.
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1
WABA2 = 'phone-number-id-waba-t-direct-1055232054343117'

#: Test values, never the live ones: the point of the readiness gate is that the expectation is
#: COMPARED, not that it is correct.
TEST_MID = 'acc_TESTMID'
TEST_CONFIG = 'WECAREDIGITAL'

#: The id the outbound Lambda reports on an accepted send. Non-empty is the whole point: every
#: row this path wrote used to carry `''`.
ACCEPTED_WAMID = 'wamid.ACCEPTEDTRUTH001'


# ══════════════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, ENGINE_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1',
                                 'WA_PAY_CONFIG_NAME': TEST_CONFIG,
                                 'EXPECTED_PROVIDER_MID': TEST_MID}):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    return module


@pytest.fixture
def fake():
    return FakeDynamo(
        keys={INVOICES: 'invoiceId', ITEMS: 'invoiceId', DELIVERY: 'invoiceId',
              CONTACTS: 'contactId', KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'},
        base_query_tables={ITEMS, DELIVERY})


def _ready_configurations():
    """The flattened `{data:[config,...]}` shape `payment_readiness.evaluate` consumes."""
    return {'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                      'provider_name': 'Razorpay', 'provider_mid': TEST_MID,
                      'waba_id': wpr.PHONE_ID_TO_WABA[WABA1]}]}


class _Outbound:
    """The outbound Lambda, answering the SEND however the test asks.

    Dispatches on path, because this handler makes two invokes through the one client: the
    readiness readback against `/wa-business/payment-config/list`, which must always succeed here
    so the test is about the SEND, and the send itself.

    `raises` makes the send invoke raise, which is the AMBIGUOUS outcome - the one case where the
    network cannot tell us whether Meta took the message.
    """

    def __init__(self, *, send_status=200, send_body=None, raises=None):
        self.invokes = []
        self.send_status = send_status
        self.send_body = send_body
        self.raises = raises
        self.readiness_calls = 0

    @staticmethod
    def _path(kwargs):
        try:
            return str(json.loads(kwargs.get('Payload') or '{}').get('path') or '')
        except (ValueError, TypeError):
            return ''

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        if '/payment-config/list' in self._path(kwargs):
            self.readiness_calls += 1
            body = json.dumps({'statusCode': 200,
                               'body': json.dumps(_ready_configurations())})
        else:
            if self.raises is not None:
                raise self.raises
            payload = {'statusCode': self.send_status}
            if self.send_body is not None:
                payload['body'] = json.dumps(self.send_body)
            else:
                payload['body'] = json.dumps({'status': 'sent',
                                              'whatsappMessageId': ACCEPTED_WAMID})
            body = json.dumps(payload)

        class _Payload:
            def read(self_inner):
                return body.encode()

        return {'Payload': _Payload(), 'StatusCode': 200}

    def sends(self):
        """Only the SEND invokes. The readiness readback is not a send."""
        return [c for c in self.invokes if '/payment-config/list' not in self._path(c)]


def _refused_outbound(code):
    """The refusal shape `outbound-whatsapp._error_response` actually returns."""
    return {'error': code, 'message': 'Nothing has been charged.'}


def _seed_invoice(fake, *, status='created'):
    """An invoice ready to collect against, seeded NOT in `pending_payment`.

    `created` on purpose: `pending_payment` is what the acceptance path writes, so seeding it
    would make "the invoice status is unchanged" unobservable - the assertion that matters most
    on the rejection path.
    """
    fake.Table(INVOICES).put_item(Item={
        'invoiceId': INVOICE_ID, 'status': status, 'customerPhone': PHONE,
        'contactId': CUSTOMER, 'referenceId': REFERENCE, 'total': '599.00',
        'tax': '0.00', 'discount': '0.00', 'shipping': '0.00', 'convenienceFee': '0.00',
        'gstRate': 18, 'goodsType': 'digital-goods', 'customerName': 'QA Recipient',
        'orderId': 'Offline', 'createdAt': 1770000000})
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee', 'amount': '599.00',
                                     'quantity': 1, 'gstRate': 18})


def _drive(engine, fake, lam, *, phone_id=WABA1):
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', lam):
        ddb.Table.side_effect = fake.Table
        ddb.meta.client = fake.client()
        with patch.object(engine, '_lookup_contact_by_phone',
                          return_value={'contactId': CUSTOMER}):
            return engine.send_payment_link(INVOICE_ID, phone_id, '', 'req-truth')


def _body(resp):
    return json.loads(resp['body'])


def _invoice(fake):
    return fake.tables[INVOICES][INVOICE_ID]


def _attempt(fake):
    return list(fake.tables[ATTEMPTS].values())[0]


def _delivery(fake):
    rows = fake.all_rows(DELIVERY)
    assert len(rows) == 1, f'expected one delivery row, got {rows}'
    return rows[0]


# ══════════════════════════════════════════════════════════════════════════════
# definite rejection
# ══════════════════════════════════════════════════════════════════════════════

def test_a_definite_rejection_is_never_reported_as_sent(engine, fake):
    """The whole feature in one test: a parsed `statusCode: 400` from the sender.

    The invoice is untouched, the row says `rejected`, the claim is released, and the answer is a
    non-200 carrying `sendStatus: 'REJECTED'`. The old code logged this and returned 200
    `payment_link_sent`.
    """
    _seed_invoice(fake)
    lam = _Outbound(send_status=400, send_body=_refused_outbound('ORDER_DETAILS_INVALID'))
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] != 200
    body = _body(resp)
    assert body['status'] == 'payment_link_rejected'
    assert body['sendStatus'] == 'REJECTED'
    assert body['status'] != 'payment_link_sent'
    assert 'Nothing has been charged.' in body['error']
    # The invoice is EXACTLY as it was. No `pending_payment`, no `updatedAt` churn.
    assert _invoice(fake)['status'] == 'created'
    # The row reads `rejected` and carries the downstream cause.
    row = _delivery(fake)
    assert row['status'] == 'rejected'
    assert 'ORDER_DETAILS_INVALID' in row['error']
    assert row['channel'] == 'whatsapp_payment'
    # The claim is released, so a retry is genuinely possible.
    assert _attempt(fake)['sendStatus'] == 'NOT_STARTED'
    assert _attempt(fake)['status'] != payment_attempt.PAYMENT_REQUEST_SENT
    assert len(lam.sends()) == 1


def test_a_released_claim_lets_a_retry_actually_re_invoke_the_sender(engine, fake):
    """The half that the live incident turned on. A claim taken and never released meant the
    second call answered 200 `send_in_progress` and sent nothing, forever."""
    _seed_invoice(fake)
    first = _drive(engine, fake, _Outbound(send_status=400,
                                           send_body=_refused_outbound('WA_PAY_NOT_READY')))
    assert first['statusCode'] != 200

    retry = _Outbound()
    second = _drive(engine, fake, retry)

    assert second['statusCode'] == 200, _body(second)
    assert _body(second)['status'] == 'payment_link_sent'
    # The SAME reservation re-sends: a fresh reference on a retry is two captures for one invoice.
    assert _body(second)['referenceId'] == REFERENCE
    assert len(retry.sends()) == 1
    assert len(fake.all_rows(ATTEMPTS)) == 1
    assert _delivery(fake)['status'] == 'accepted'
    assert _invoice(fake)['status'] == 'pending_payment'


def test_a_downstream_refusal_that_will_not_succeed_holds_the_claim_as_rejected(engine, fake):
    """A downstream 409 is that layer's own "this will not succeed" - a forbidden sender, an
    unprovable configuration, a refused envelope. Re-invoking the identical request would be
    refused identically, so the claim stays HELD under a name that says why, and the retry is
    told to raise the collection again rather than answered `send_in_progress`."""
    _seed_invoice(fake)
    lam = _Outbound(send_status=409,
                    send_body=_refused_outbound(wpr.WA_PAY_SENDER_NOT_PERMITTED))
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] == 409
    assert _body(resp)['sendStatus'] == 'REJECTED'
    assert _body(resp)['retryable'] is False
    assert _attempt(fake)['sendStatus'] == 'REJECTED'
    assert _delivery(fake)['status'] == 'rejected'
    assert _invoice(fake)['status'] == 'created'

    # And the retry is honest about it: 409 `payment_link_rejected`, not 200 `send_in_progress`.
    retry = _Outbound()
    again = _drive(engine, fake, retry)
    assert again['statusCode'] == 409
    assert _body(again)['status'] == 'payment_link_rejected'
    assert _body(again)['sendStatus'] == 'REJECTED'
    assert retry.sends() == []


def test_a_rejection_is_still_returned_when_the_delivery_log_write_fails(engine, fake):
    """The row is the staff-visible record, not the authority. A storage error writing it must not
    replace a truthful rejection with a 500 - that is the one answer that sends an operator
    looking in the wrong place."""
    _seed_invoice(fake)
    fake.arm_failure(DELIVERY, 'put_item', RuntimeError('delivery log unavailable'))
    resp = _drive(engine, fake, _Outbound(send_status=400,
                                          send_body=_refused_outbound('ORDER_DETAILS_INVALID')))

    assert resp['statusCode'] == 502
    assert _body(resp)['sendStatus'] == 'REJECTED'
    assert _invoice(fake)['status'] == 'created'
    assert _attempt(fake)['sendStatus'] == 'NOT_STARTED'


# ══════════════════════════════════════════════════════════════════════════════
# ambiguous
# ══════════════════════════════════════════════════════════════════════════════

def test_an_ambiguous_send_is_recorded_as_unknown_and_never_auto_resent(engine, fake):
    """A timeout cannot tell us whether Meta took the message, so the claim is NOT released and
    nothing is replayed: a second `order_details` message would show the customer two payment
    requests. What is new is the row - an ambiguous send used to leave no record at all, which
    reads exactly like a send that never happened, and the two need opposite actions."""
    _seed_invoice(fake)
    lam = _Outbound(raises=TimeoutError('outbound timed out'))
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] == 502
    assert _body(resp)['sendStatus'] == 'PENDING'
    # Reconcile, not resend. The words matter: a resend here is the double-send.
    assert 'Reconcile' in _body(resp)['error']
    row = _delivery(fake)
    assert row['status'] == 'unknown'
    assert row['error']
    assert _invoice(fake)['status'] == 'created'
    assert _attempt(fake)['sendStatus'] == 'PENDING'

    # A second call does NOT re-invoke the sender.
    retry = _Outbound()
    second = _drive(engine, fake, retry)
    assert retry.sends() == []
    assert _body(second)['status'] == 'send_in_progress'
    assert _body(second)['deduplicated'] is True


def test_an_unreadable_outbound_status_is_ambiguous_rather_than_success(engine, fake):
    """Neither a rejection nor a 2xx: a response this function cannot read as acceptance. The old
    code fell through and wrote `pending_payment` plus a `failed` delivery row - a contradiction
    inside one invoice."""
    _seed_invoice(fake)
    resp = _drive(engine, fake, _Outbound(send_status=0))

    assert resp['statusCode'] == 502
    assert _body(resp)['sendStatus'] == 'PENDING'
    assert _delivery(fake)['status'] == 'unknown'
    assert _invoice(fake)['status'] == 'created'


# ══════════════════════════════════════════════════════════════════════════════
# acceptance
# ══════════════════════════════════════════════════════════════════════════════

def test_an_accepted_send_stores_the_real_message_id_and_labels_the_row_accepted(engine, fake):
    """`accepted`, never `sent` and never `delivered`: Meta accepting an `order_details` message
    is not the customer receiving it. And the id is the REAL one - every row on this path used to
    carry `''`, which left the delivery log unjoinable to the message it records."""
    _seed_invoice(fake)
    resp = _drive(engine, fake, _Outbound(send_status=200))

    assert resp['statusCode'] == 200, _body(resp)
    assert _body(resp)['status'] == 'payment_link_sent'
    row = _delivery(fake)
    assert row['status'] == 'accepted'
    assert row['status'] not in ('sent', 'delivered')
    assert row['waMessageId'] == ACCEPTED_WAMID
    assert row['error'] == ''
    assert _invoice(fake)['status'] == 'pending_payment'
    attempt = _attempt(fake)
    assert attempt['status'] == payment_attempt.PAYMENT_REQUEST_SENT
    assert attempt['sendStatus'] == 'SENT'


@pytest.mark.parametrize('accepted_status', [200, 202])
def test_both_accepted_statuses_advance_the_attempt(engine, fake, accepted_status):
    """202 is an acceptance too, and it took the same `pending_payment` branch before. Named so
    the acceptance set stays exactly these two rather than "not a rejection"."""
    _seed_invoice(fake)
    resp = _drive(engine, fake, _Outbound(send_status=accepted_status))

    assert resp['statusCode'] == 200, _body(resp)
    assert _delivery(fake)['status'] == 'accepted'
    assert _attempt(fake)['sendStatus'] == 'SENT'


def test_an_accepted_send_with_an_unreadable_body_is_still_accepted(engine, fake):
    """An id we cannot read is an empty id, never a failed send: the send WAS accepted, and
    answering a rejection here would be the mirror image of the bug this file is about."""
    _seed_invoice(fake)
    resp = _drive(engine, fake, _Outbound(send_status=200, send_body={'status': 'sent'}))

    assert resp['statusCode'] == 200, _body(resp)
    assert _delivery(fake)['status'] == 'accepted'
    assert _delivery(fake)['waMessageId'] == ''
    assert _attempt(fake)['sendStatus'] == 'SENT'


# ══════════════════════════════════════════════════════════════════════════════
# WABA1 only
# ══════════════════════════════════════════════════════════════════════════════

def test_a_payment_send_from_waba2_is_refused_with_nothing_written_and_nothing_sent(engine,
                                                                                   fake):
    """The refusal the staff UI used to walk into on every page load, because `sendPhone`
    defaulted to this id while the server permits exactly one - WABA1."""
    _seed_invoice(fake)
    lam = _Outbound()
    resp = _drive(engine, fake, lam, phone_id=WABA2)

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
    assert fake.count(ATTEMPTS) == 0
    assert fake.count(DELIVERY) == 0
    assert [k for k in fake.tables.get(KEYS, {})
            if str(k).startswith(order_keys.PAYMENT_REFERENCE_PREFIX)] == []
    assert lam.invokes == []


def test_the_staff_flow_page_defaults_to_and_offers_only_the_payment_capable_sender():
    """The UI half of the fix, pinned to the server's allowlist rather than to a retyped string.

    A selector offering WABA2 is a selector offering a guaranteed refusal, and a default of WABA2
    is a page that refuses before the operator touches anything.
    """
    import pathlib
    import re

    source = (pathlib.Path(REPO) / 'src' / 'pages' / 'workspace' / 'pay' / 'flow'
              / 'index.tsx').read_text(encoding='utf-8')
    sender_ids = set(re.findall(r"'(phone-number-id-[a-z0-9-]+)'", source))
    assert sender_ids == {wpr.PHONE_NUMBER_ID_1}, (
        'the flow page must name only the payment-capable sender; '
        f'found {sorted(sender_ids)}')
    # The Select itself stays: one option still states which number the customer will see.
    assert 'phoneSelectOptions' in source


# ══════════════════════════════════════════════════════════════════════════════
# the claim primitives
# ══════════════════════════════════════════════════════════════════════════════

class _RaisingTable:
    """Storage that is simply down. Both new functions must degrade, not raise."""

    def update_item(self, **_):
        raise RuntimeError('DynamoDB unavailable')


def test_release_send_claim_is_the_exact_inverse_of_claim_send(fake):
    table = fake.Table(ATTEMPTS)
    table.put_item(Item={'paymentAttemptId': 'pa-1', 'sendStatus': 'NOT_STARTED'})

    assert wpr.claim_send(table, payment_attempt_id='pa-1') is True
    assert fake.tables[ATTEMPTS]['pa-1']['sendStatus'] == 'PENDING'
    assert wpr.release_send_claim(table, payment_attempt_id='pa-1') is True
    assert fake.tables[ATTEMPTS]['pa-1']['sendStatus'] == 'NOT_STARTED'
    # And the claim can be taken again, which is what "staff can retry" means.
    assert wpr.claim_send(table, payment_attempt_id='pa-1') is True


def test_release_send_claim_can_never_release_a_sent_row(fake):
    """The condition gives this for free, and it matters: releasing a delivered message's claim
    invites the second payment request the claim exists to prevent."""
    table = fake.Table(ATTEMPTS)
    table.put_item(Item={'paymentAttemptId': 'pa-2', 'sendStatus': 'SENT'})

    assert wpr.release_send_claim(table, payment_attempt_id='pa-2') is False
    assert fake.tables[ATTEMPTS]['pa-2']['sendStatus'] == 'SENT'


def test_neither_new_function_raises_on_a_storage_error():
    """A failed release degrades to "staff cannot retry yet", which is visible and recoverable.
    Raising would replace the real send failure in the response with a storage error."""
    assert wpr.release_send_claim(_RaisingTable(), payment_attempt_id='pa-3') is False
    assert wpr.record_send_rejected(_RaisingTable(), payment_attempt_id='pa-3',
                                    now=1770000000) is False
    # An empty id is not a write.
    assert wpr.release_send_claim(_RaisingTable(), payment_attempt_id='') is False
    assert wpr.record_send_rejected(_RaisingTable(), payment_attempt_id='',
                                    now=1770000000) is False


def test_record_send_rejected_is_terminal_and_cannot_overwrite_sent(fake):
    table = fake.Table(ATTEMPTS)
    table.put_item(Item={'paymentAttemptId': 'pa-4', 'sendStatus': 'PENDING'})
    assert wpr.record_send_rejected(table, payment_attempt_id='pa-4',
                                    now=1770000000) is True
    assert fake.tables[ATTEMPTS]['pa-4']['sendStatus'] == 'REJECTED'

    table.put_item(Item={'paymentAttemptId': 'pa-5', 'sendStatus': 'SENT'})
    assert wpr.record_send_rejected(table, payment_attempt_id='pa-5',
                                    now=1770000000) is False
    assert fake.tables[ATTEMPTS]['pa-5']['sendStatus'] == 'SENT'


def test_a_lost_condition_is_not_an_error(fake):
    """A conditional failure means the row is not PENDING - already sent, or already released.
    Reported as False, never as a raise, and never as a storage failure."""
    table = fake.Table(ATTEMPTS)
    assert wpr.release_send_claim(table, payment_attempt_id='pa-missing') is False
    assert order_keys.is_conditional_failure(
        FakeClientError('ConditionalCheckFailedException')) is True


def test_both_new_functions_are_exported():
    """`__all__` is the module's statement of its surface; a helper the invoice engine calls and
    the module does not export is a private function with a public caller."""
    assert 'release_send_claim' in wpr.__all__
    assert 'record_send_rejected' in wpr.__all__
