"""A capture without `notes.referenceId` is attributed by an EXACT stored binding, or not at all.

`_handle_payment_captured` used to recover a missing referenceId through
`_lookup_reference_id_from_meta`, which never called Meta: it scanned InvoicesTable filtered only
by status and returned the FIRST pending invoice whose `customerPhone` matched the payment's
`contact`. A customer with two pending invoices could have a payment attributed to the other one,
and that reference then drove order reconciliation, the invoice-paid write and the customer's
confirmation.

These tests drive the WHOLE callback, in the style of `test_razorpay_webhook_captured_gating.py`,
and read the outcome off stored rows rather than off mocks:

  * two pending invoices for the paying phone, no binding  -> nothing is guessed;
  * a guess landing on an already-ordered reference        -> the wrong invoice is NOT settled;
  * the order id names our `GATEWAYORDER#` binding          -> exactly that invoice is paid;
  * no binding at all                                       -> unattributed, but recorded;
  * Razorpay's `"notes": []`                                -> the same recorded path, not a 500.
"""

import importlib
import json
import os
import re
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_creation, order_keys  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

#: Read from the resolver rather than retyped (see `test_payment_key_table_is_one_name.py`).
KEYS_TABLE = order_keys.commerce_keys_table_name()

REF_A = 'WD-PAY-AAAAAAAAAAAAAA'   # the customer's OTHER pending invoice
REF_B = 'WD-PAY-BBBBBBBBBBBBBB'   # the purchase this payment is actually for
ATTEMPT_A = '01930000-0000-7000-8000-00000000000a'
ATTEMPT_B = '01930000-0000-7000-8000-00000000000b'
CUSTOMER = 'CUS_01J0000000000000000000000'
GATEWAY_ORDER = 'order_EXACTBIND0001'
TXN = 'pay_EXACTBIND00001'
AMOUNT = 59900  # paise. BOTH invoices carry it: the ordinary repeat order.
CONTACT = '+919876543210'
FULL_PHONE = '9876543210'
EMAIL = 'buyer@example.com'
BUYER_NAME = 'Test Buyer'
#: The notes shape of the one Meta-originated Razorpay payment on record: a business phone id and
#: no referenceId - which is exactly the capture that reaches recovery.
META_NOTES = {'wa_business_pid': '1016149501586345'}


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
def fake(webhook):
    return FakeDynamo(
        keys={KEYS_TABLE: 'orderId', webhook.INVOICES_TABLE: 'invoiceId',
              webhook.PAYMENTS_TABLE: 'id', webhook.WEBHOOK_LOG_TABLE: 'id'},
        indexes={webhook.INVOICES_TABLE: {'referenceId-index': ('referenceId', None)}},
    )


class _InvoicesTable:
    """InvoicesTable as the callback addresses it: raw-string GSI queries, and a RECORDED scan.

    FakeDynamo understands boto3 `Key(...).eq(...)` objects while the handler queries this table
    with a raw `referenceId = :ref` string, so that one shape is translated here, as in
    `test_razorpay_webhook_captured_gating.py`. The scan is modelled for one reason: run against
    the pre-fix handler, the old phone-matching scan must really return the pending invoices, so
    these tests fail there on a GUESSED attribution rather than on a missing fake method. Every
    scan is recorded, so a test can also assert that recovery no longer scans this table at all.
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
        return self._t.query(IndexName=IndexName, KeyConditionExpression=KeyConditionExpression,
                             ExpressionAttributeValues=ExpressionAttributeValues, Limit=Limit)

    def scan(self, FilterExpression=None, ExpressionAttributeNames=None,
             ExpressionAttributeValues=None, **_):
        self._t.parent.calls.append((self._t.name, 'scan'))
        match = re.fullmatch(r'\s*(#\w+)\s+IN\s+\(([^)]*)\)\s*', FilterExpression or '')
        if not match:
            raise AssertionError(f'unmodelled scan filter: {FilterExpression!r}')
        attr = (ExpressionAttributeNames or {})[match.group(1)]
        allowed = {(ExpressionAttributeValues or {})[token.strip()]
                   for token in match.group(2).split(',')}
        items = [dict(r) for r in self._t.rows.values() if r.get(attr) in allowed]
        return {'Items': items, 'Count': len(items)}

    def __getattr__(self, name):
        return getattr(self._t, name)


class _Dynamo:
    """A dynamodb resource whose InvoicesTable speaks the callback's raw-string dialect."""

    def __init__(self, fake, invoices_table):
        self._fake = fake
        self._invoices = invoices_table

    def Table(self, name):  # noqa: N802 - boto3's spelling
        table = self._fake.Table(name)
        return _InvoicesTable(table) if name == self._invoices else table


class _Effects:
    """Patches the side effects that leave this process, and records them.

    `_mark_invoice_paid_by_reference`, `_store_payment_record`, reconciliation and the quarantine
    all run FOR REAL against the fake, so "which invoice was settled" and "what was recorded" are
    read off stored rows. `_create_order_for_captured_payment` is wrapped, not replaced, so the
    reference it was handed is observable while it still does its work.
    """

    def __init__(self, webhook):
        self.webhook = webhook
        self.lambda_client = MagicMock()

    def __enter__(self):
        self._patchers = [
            patch.object(self.webhook, 'lambda_client', self.lambda_client),
            patch.object(self.webhook, '_post_payment_handler'),
            patch.object(self.webhook, '_log_ctwa_purchase'),
            patch.object(self.webhook, '_create_order_for_captured_payment',
                         wraps=self.webhook._create_order_for_captured_payment),
        ]
        started = [p.start() for p in self._patchers]
        _, self.post_payment, self.ctwa, self.post_pay_flow, self.reconcile = started
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()

    def confirmed_references(self):
        """The reference ids the customer was sent a paid-invoice confirmation for.

        The single confirmation is now the approved `wecare_default_invoice_image_template`,
        delivered INSIDE `_post_payment_handler` (patched here), replacing the removed free-form
        `isOrderStatus` message the webhook used to build inline. The attribution this test pins -
        a capture confirms exactly its own reference, to a real recipient - is read off the
        `_post_payment_handler` call: it receives the resolved billed-customer `contact`
        (positional arg 1) and the `reference_id` (kwarg). A call with an empty contact delivered
        nothing (the gate inside is `contact and invoice_id`), so it is not a confirmation."""
        refs = []
        for call in self.post_payment.call_args_list:
            contact = call.args[1] if len(call.args) > 1 else ''
            reference_id = call.kwargs.get('reference_id', '')
            if contact and reference_id:
                refs.append(reference_id)
        return refs


def _capture(*, notes):
    """A `payment.captured` entity in Razorpay's shape. `description` is empty, as on the
    Meta-originated payment on record, so the legacy `WD...` description fallback cannot fire."""
    return {'payment': {'entity': {
        'id': TXN, 'entity': 'payment', 'order_id': GATEWAY_ORDER, 'invoice_id': None,
        'amount': AMOUNT, 'currency': 'INR', 'status': 'captured', 'method': 'upi',
        'captured': True, 'contact': CONTACT, 'email': EMAIL, 'description': '',
        'notes': notes,
    }}}


def _drive(webhook, fake, event):
    """`_handle_payment_captured` alone, with the provider verifier answering PAID."""
    with patch.object(webhook, 'dynamodb', _Dynamo(fake, webhook.INVOICES_TABLE)), \
         patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
               return_value=lambda _ref: (True, TXN, AMOUNT, 'INR')):
        webhook._handle_payment_captured(event, 'req-attr')


def _deliver(webhook, fake, event):
    """The real Lambda entry point: audit row, dispatch, lease. Signature and dedup stubbed."""
    body = json.dumps({'entity': 'event', 'account_id': 'acc_TEST', 'event': 'payment.captured',
                       'contains': ['payment'], 'payload': event, 'created_at': 1770000000})
    with patch.object(webhook, 'dynamodb', _Dynamo(fake, webhook.INVOICES_TABLE)), \
         patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
               return_value=lambda _ref: (False, '', 0, '')), \
         patch.object(webhook, '_verify_signature', return_value=True), \
         patch.object(webhook, '_is_duplicate_event', return_value=False), \
         patch.object(webhook, '_complete_event') as complete:
        response = webhook.handler(
            {'headers': {'x-razorpay-signature': 'test-signature'}, 'body': body},
            MagicMock(aws_request_id='req-deliver'))
    return response, complete


def _seed_pending_invoice(fake, webhook, *, invoice_id, reference_id, invoice_number):
    fake.Table(webhook.INVOICES_TABLE).put_item(Item={
        'invoiceId': invoice_id, 'referenceId': reference_id, 'invoiceNumber': invoice_number,
        'total': Decimal('599.00'), 'status': 'sent', 'paymentStatus': 'pending',
        'customerPhone': CONTACT, 'customerName': BUYER_NAME})


def _seed_two_pending_invoices(fake, webhook):
    """Same phone, same total. INV-A is written first, so a first-match scan returns IT."""
    _seed_pending_invoice(fake, webhook, invoice_id='INV-A', reference_id=REF_A,
                          invoice_number='WD/2627/00011')
    _seed_pending_invoice(fake, webhook, invoice_id='INV-B', reference_id=REF_B,
                          invoice_number='WD/2627/00012')


def _seed_attempt(fake, *, reference_id, attempt_id, provider_order_id):
    """A `PAYREF#` row as the payment-request builder writes it."""
    order_keys.reserve_payment_reference(
        fake.Table(KEYS_TABLE), reference_id=reference_id, payment_attempt_id=attempt_id,
        extra={'customerId': CUSTOMER, 'amountPaise': AMOUNT, 'currency': 'INR',
               'providerOrderId': provider_order_id})


def _seed_binding(fake, *, extra):
    """The `GATEWAYORDER#` row, through the same writer `website_checkout._bind_and_ready` uses."""
    order_keys.bind_gateway_order(
        fake.Table(KEYS_TABLE), gateway_order_id=GATEWAY_ORDER, payment_attempt_id=ATTEMPT_B,
        request_key='rk-exact-1', amount_paise=AMOUNT, account_key_id='rzp_test_key',
        account_mode='test', currency='INR', extra=extra)


def _invoice(fake, webhook, invoice_id):
    return fake.tables[webhook.INVOICES_TABLE][invoice_id]


def _parked(fake):
    """The durable quarantine intake row for this payment, as `reconcile_captures.py` reads it."""
    return order_keys.resolve_capture_quarantine(fake.Table(KEYS_TABLE), TXN)


def _order_claims(fake):
    """`PAYMENTATTEMPT#` order claims: which attempts have an order."""
    return {k: v for k, v in fake.tables.get(KEYS_TABLE, {}).items()
            if str(k).startswith(order_keys.PAYMENT_ATTEMPT_PREFIX)}


def _events(caplog, name):
    return [json.loads(r.getMessage()) for r in caplog.records
            if f'"event": "{name}"' in r.getMessage()]


# ══════════════════════════════════════════════════════════════════════════════
# two pending invoices for the paying phone: nothing is guessed
# ══════════════════════════════════════════════════════════════════════════════

def test_two_pending_invoices_for_the_paying_phone_are_never_guessed_between(
        webhook, fake, caplog):
    """No referenceId in the notes, no binding, two pending invoices at the paying phone and the
    paying amount. No reference is attributed: nothing reconciles, no invoice is touched, nothing
    is confirmed, and the capture is parked with NO reference rather than with somebody's."""
    _seed_two_pending_invoices(fake, webhook)
    with _Effects(webhook) as fx, caplog.at_level('INFO'):
        _drive(webhook, fake, _capture(notes=dict(META_NOTES)))

    fx.reconcile.assert_not_called()
    assert _invoice(fake, webhook, 'INV-A')['status'] == 'sent'
    assert _invoice(fake, webhook, 'INV-B')['status'] == 'sent'
    fx.post_payment.assert_not_called()
    fx.ctwa.assert_not_called()
    fx.post_pay_flow.assert_not_called()
    assert fx.confirmed_references() == []
    assert fake.count(webhook.PAYMENTS_TABLE) == 0
    parked = _parked(fake)
    assert parked is not None
    assert parked['referenceId'] == ''
    assert parked['status'] == 'UNRESOLVED'
    # Not a narrower scan: recovery no longer reads InvoicesTable at all.
    assert (webhook.INVOICES_TABLE, 'scan') not in fake.calls

    [unattributed] = _events(caplog, 'reference_id_unattributed')
    assert unattributed['reason'] == 'no_stored_binding'
    assert unattributed['paymentId'] == TXN
    assert unattributed['razorpayOrderId'] == GATEWAY_ORDER
    # PII-free: provider ids and a reason only - on this line and on every other one.
    blob = '\n'.join(r.getMessage() for r in caplog.records)
    for secret in (CONTACT, FULL_PHONE, EMAIL, BUYER_NAME):
        assert secret not in blob


def test_a_guess_onto_an_already_ordered_reference_cannot_settle_the_wrong_invoice(webhook, fake):
    """Why a guess was not merely untidy. REF_A was paid and ordered EARLIER, but its invoice row
    still reads `sent` (the invoice-paid write is a secondary projection and can fail).
    `reconcile_payment` answers ORDER_ALREADY_EXISTS for that attempt BEFORE it contacts the
    provider, so a phone-matched guess of REF_A read as a verified success: INV-A marked paid by
    THIS payment, REF_A confirmed to the customer, REF_B never settled, nothing parked."""
    _seed_two_pending_invoices(fake, webhook)
    keys = fake.Table(KEYS_TABLE)
    _seed_attempt(fake, reference_id=REF_A, attempt_id=ATTEMPT_A,
                  provider_order_id='order_EARLIER_A')
    order_keys.claim_order_for_payment(
        keys, payment_attempt_id=ATTEMPT_A, order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_EARLIER_A', extra={'referenceId': REF_A})
    order_keys.record_order_number_on_claim(
        keys, payment_attempt_id=ATTEMPT_A, order_number=order_keys.mint_public_order_number())

    with _Effects(webhook) as fx:
        _drive(webhook, fake, _capture(notes={}))

    inv_a = _invoice(fake, webhook, 'INV-A')
    assert inv_a['status'] == 'sent'
    assert 'providerPaymentId' not in inv_a
    assert fx.confirmed_references() == []
    fx.post_payment.assert_not_called()
    assert fake.count(webhook.PAYMENTS_TABLE) == 0
    assert _parked(fake)['referenceId'] == ''


# ══════════════════════════════════════════════════════════════════════════════
# an exact stored identifier: exactly the right invoice
# ══════════════════════════════════════════════════════════════════════════════

def test_the_gateway_order_binding_settles_exactly_the_invoice_it_names(webhook, fake, caplog):
    """The capture's Razorpay order id names the `GATEWAYORDER#` binding our checkout wrote for
    REF_B. Same phone, same amount, and INV-A sits FIRST - the one a first-match scan returned.
    The binding decides: REF_B gets the order, INV-B is paid by this payment, INV-A is untouched,
    and every downstream step names REF_B."""
    _seed_two_pending_invoices(fake, webhook)
    _seed_attempt(fake, reference_id=REF_B, attempt_id=ATTEMPT_B,
                  provider_order_id=GATEWAY_ORDER)
    _seed_binding(fake, extra={'referenceId': REF_B, 'customerId': CUSTOMER})

    with _Effects(webhook) as fx, caplog.at_level('INFO'):
        _drive(webhook, fake, _capture(notes={}))

    assert [c.args[1] for c in fx.reconcile.call_args_list] == [REF_B]
    claims = _order_claims(fake)
    assert set(claims) == {order_keys.PAYMENT_ATTEMPT_PREFIX + ATTEMPT_B}
    assert claims[order_keys.PAYMENT_ATTEMPT_PREFIX + ATTEMPT_B]['referenceId'] == REF_B

    inv_b = _invoice(fake, webhook, 'INV-B')
    assert inv_b['status'] == 'paid'
    assert inv_b['providerPaymentId'] == TXN
    inv_a = _invoice(fake, webhook, 'INV-A')
    assert inv_a['status'] == 'sent'
    assert 'providerPaymentId' not in inv_a

    assert fake.tables[webhook.PAYMENTS_TABLE][TXN]['status'] == 'captured'
    assert fx.post_payment.call_args.kwargs['reference_id'] == REF_B
    assert fx.post_pay_flow.call_args.args[2] == REF_B
    assert fx.confirmed_references() == [REF_B]
    assert _parked(fake) is None

    [recovered] = _events(caplog, 'reference_id_recovered')
    assert recovered['source'] == 'gateway_order_binding'
    assert recovered['referenceId'] == REF_B
    assert _events(caplog, 'reference_id_unattributed') == []


# ══════════════════════════════════════════════════════════════════════════════
# no exact match: unattributed, but recorded and recoverable
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unattributable_capture_is_recorded_and_parked_not_lost(webhook, fake):
    """No referenceId and no binding, with ONE pending invoice for the paying phone - the case the
    old scan happily "recovered". Through the real entry point: a 200 and a closed lease (so
    Razorpay stops retrying), the RazorpayWebhookLogTable audit row, and a durable
    CAPTUREQUARANTINE# row with NO reference for `scripts/reconcile_captures.py`. PaymentsTable
    stays empty by design: a money-confirmed record is written only for a verified settlement."""
    _seed_pending_invoice(fake, webhook, invoice_id='INV-A', reference_id=REF_A,
                          invoice_number='WD/2627/00011')
    with _Effects(webhook) as fx:
        response, complete = _deliver(webhook, fake, _capture(notes={}))

    assert response['statusCode'] == 200
    complete.assert_called_once()
    [audit] = fake.all_rows(webhook.WEBHOOK_LOG_TABLE)
    assert audit['eventType'] == 'payment.captured'
    assert audit['paymentId'] == TXN
    assert audit['orderId'] == GATEWAY_ORDER
    assert audit['amountPaise'] == AMOUNT

    parked = _parked(fake)
    assert parked['referenceId'] == ''
    assert parked['outcome'] == order_creation.NEEDS_RECONCILIATION
    assert parked['status'] == 'UNRESOLVED'
    assert parked['acknowledged'] is False

    fx.reconcile.assert_not_called()
    assert _invoice(fake, webhook, 'INV-A')['status'] == 'sent'
    assert fake.count(webhook.PAYMENTS_TABLE) == 0
    assert fx.confirmed_references() == []


def test_razorpays_empty_notes_array_reaches_the_same_recorded_path(webhook, fake):
    """Razorpay serialises empty notes as `[]`, as its own sample payloads do. That raised
    AttributeError at `notes.get('referenceId')`: a 500 on every retry, and no quarantine row."""
    with _Effects(webhook):
        response, complete = _deliver(webhook, fake, _capture(notes=[]))

    assert response['statusCode'] == 200
    complete.assert_called_once()
    assert len(fake.all_rows(webhook.WEBHOOK_LOG_TABLE)) == 1
    assert _parked(fake)['referenceId'] == ''


def test_a_binding_that_names_no_reference_is_not_widened_into_a_guess(webhook, fake, caplog):
    """A blog contribution's `GATEWAYORDER#` row carries `contributionId`, not `referenceId`. It
    is ours, but it is not a reference: unattributed, with no weaker source consulted."""
    _seed_pending_invoice(fake, webhook, invoice_id='INV-A', reference_id=REF_A,
                          invoice_number='WD/2627/00011')
    _seed_binding(fake, extra={'purpose': 'BLOG_CONTRIBUTION', 'contributionId': 'contrib-1'})

    with _Effects(webhook) as fx, caplog.at_level('INFO'):
        _drive(webhook, fake, _capture(notes={}))

    fx.reconcile.assert_not_called()
    [unattributed] = _events(caplog, 'reference_id_unattributed')
    assert unattributed['reason'] == 'binding_has_no_reference'
    assert _parked(fake)['referenceId'] == ''
    assert (webhook.INVOICES_TABLE, 'scan') not in fake.calls


def test_an_unreadable_binding_leaves_the_capture_unattributed(webhook, fake, caplog):
    """A failed binding read means "we do not know". It is neither absence nor a licence to ask the
    paying phone instead, and it never escapes as an exception. The type is logged, never the
    message."""
    _seed_pending_invoice(fake, webhook, invoice_id='INV-A', reference_id=REF_A,
                          invoice_number='WD/2627/00011')
    fake.arm_failure(KEYS_TABLE, 'get_item', RuntimeError('throttled: do-not-log-me'))

    with _Effects(webhook) as fx, caplog.at_level('INFO'):
        _drive(webhook, fake, _capture(notes={}))

    fx.reconcile.assert_not_called()
    [unattributed] = _events(caplog, 'reference_id_unattributed')
    assert unattributed['reason'] == 'binding_unavailable'
    assert unattributed['error'] == 'OrderIdentityUnavailable'
    assert 'do-not-log-me' not in json.dumps(unattributed)
    assert _parked(fake)['referenceId'] == ''
    assert (webhook.INVOICES_TABLE, 'scan') not in fake.calls
