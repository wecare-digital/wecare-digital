"""One live collection per invoice, and a cancelled one that can actually be re-raised.

The two properties here are different, and only the first is obvious.

**The interlock.** Five independent callers reach `invoice-engine.send_payment_link` - the
operator UI, the business-API route, a Flow completion, the inbound auto-send and the auto-send
chain. Without a claim, one pending invoice can receive a payment request from two of them
concurrently, producing two references, two captures and two orders. The replay counts elsewhere
are scoped WITHIN one `reference_id` and cannot see that at all.

**The release.** The `REQUESTKEY#` anchor fingerprints the AMOUNT and carries no TTL, so an
invoice edited after a collection was sent refuses with `WA_PAY_INTENT_CHANGED`. The stated
remedy is "cancel and re-raise" - and without a collection SEQUENCE that remedy is unreachable,
because the old anchor survives the cancel and the new amount mismatches it forever. So the test
that matters is: edit -> refuse -> cancel -> a fresh collection succeeds, AND the old `PAYREF#`
row is still resolvable, because a customer who pays the message they already hold must still
settle against the reservation that message named.
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
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ITEMS = 'stack-wecare-digital-InvoiceItemsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
KEYS = 'stack-wecare-digital-WixOrderIds'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'

INVOICE_ID = 'inv-interlock-0001'
REFERENCE = 'WD-PAY-DEF67890'
CUSTOMER = 'contact-interlock-1'
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1


@pytest.fixture
def engine():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, ENGINE_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


@pytest.fixture
def fake():
    return FakeDynamo(
        keys={INVOICES: 'invoiceId', ITEMS: 'invoiceId', DELIVERY: 'invoiceId',
              KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'},
        base_query_tables={ITEMS, DELIVERY})


class _RecordingLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        body = json.dumps({'statusCode': 200,
                           'body': json.dumps({'status': 'sent',
                                               'whatsappMessageId': 'wamid.X'})})

        class _P:
            def read(self_inner):
                return body.encode()

        return {'Payload': _P(), 'StatusCode': 200}


def _seed(fake, *, total='599.00', status='pending_payment'):
    fake.Table(INVOICES).put_item(Item={
        'invoiceId': INVOICE_ID, 'status': status, 'customerPhone': PHONE,
        'contactId': CUSTOMER, 'referenceId': REFERENCE, 'total': total,
        'tax': '0.00', 'discount': '0.00', 'shipping': '0.00', 'convenienceFee': '0.00',
        'gstRate': 18, 'goodsType': 'digital-goods', 'orderId': 'Offline',
        'createdAt': 1770000000})
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee', 'amount': total,
                                     'quantity': 1, 'gstRate': 18})


def _drive(engine, fake, lam=None):
    lam = lam or _RecordingLambda()
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', lam):
        ddb.Table.side_effect = fake.Table
        ddb.meta.client = fake.client()
        with patch.object(engine, '_lookup_contact_by_phone', return_value={'contactId': CUSTOMER}):
            return engine.send_payment_link(INVOICE_ID, WABA1, '', 'req-1'), lam


def _cancel(engine, fake):
    with patch.object(engine, 'dynamodb') as ddb:
        ddb.Table.side_effect = fake.Table
        return engine.cancel_invoice(INVOICE_ID, 'operator edit', 'req-cancel')


def _body(resp):
    return json.loads(resp['body'])


def _collect_rows(fake):
    return [k for k in fake.tables.get(KEYS, {})
            if str(k).startswith(order_keys.INVOICE_COLLECT_PREFIX)]


def _payref_rows(fake):
    return [k for k in fake.tables.get(KEYS, {})
            if str(k).startswith(order_keys.PAYMENT_REFERENCE_PREFIX)]


# ══════════════════════════════════════════════════════════════════════════════
# the interlock
# ══════════════════════════════════════════════════════════════════════════════

def test_a_collection_claim_is_written_inside_the_reserve_transaction(engine, fake):
    """It is a `Put` in the same transaction as the reservation, so a reservation and its claim
    cannot disagree - which is what removes the need for any pre-call consult."""
    _seed(fake)
    _drive(engine, fake)
    assert len(_collect_rows(fake)) == 1
    row = fake.tables[KEYS][order_keys.INVOICE_COLLECT_PREFIX + INVOICE_ID]
    assert row['kind'] == order_keys.INVOICE_COLLECT_KIND
    assert row['referenceId'] == REFERENCE


def test_a_rival_attempt_cannot_claim_the_same_invoice(fake):
    """T-L1. A second RESERVATION for one invoice at a different request key loses the collection
    claim and is refused - so the second caller never sends."""
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900, configuration_name='WECAREDIGITAL',
        provider_mid='acc_TEST', item_name='Service Fee', now=1770000000)
    wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
                invoice_reference_id=REFERENCE)

    # A rival arriving at a LATER sequence: a different request key, so the anchor does not
    # resolve - but the collection claim is held, so the transaction is cancelled.
    rival = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900, configuration_name='WECAREDIGITAL',
        provider_mid='acc_TEST', item_name='Service Fee', now=1770000001,
        collection_seq=1)
    with pytest.raises(wpr.PaymentRequestRefused) as refused:
        wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                    keys_name=KEYS, attempts_name=ATTEMPTS, request=rival,
                    invoice_reference_id='')
    assert refused.value.code == wpr.WA_PAY_ALREADY_IN_FLIGHT
    assert len(_collect_rows(fake)) == 1
    assert fake.count(ATTEMPTS) == 1


def test_the_same_attempt_may_resend(engine, fake):
    """T-L3. A claim held by the SAME reservation is a retry and resolves, rather than refusing a
    legitimate resend."""
    _seed(fake)
    first, _ = _drive(engine, fake)
    second, lam2 = _drive(engine, fake)
    assert _body(first)['referenceId'] == _body(second)['referenceId']
    assert second['statusCode'] == 200
    assert len(_collect_rows(fake)) == 1


def test_an_edited_invoice_cannot_resume_the_old_reservation(engine, fake):
    """T-S3. The fingerprint includes the AMOUNT deliberately: a customer holding a payment
    request for ₹599 must not have it silently become ₹3,500."""
    _seed(fake)
    _drive(engine, fake)

    fake.Table(INVOICES).update_item(
        Key={'invoiceId': INVOICE_ID},
        UpdateExpression='SET #t = :t', ExpressionAttributeNames={'#t': 'total'},
        ExpressionAttributeValues={':t': '3500.00'})
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee', 'amount': '3500.00',
                                     'quantity': 1, 'gstRate': 18})

    resp, lam = _drive(engine, fake)
    assert _body(resp)['code'] == wpr.WA_PAY_INTENT_CHANGED
    assert lam.invokes == []
    # Nothing new was reserved.
    assert len(_payref_rows(fake)) == 1


def test_a_throttle_is_not_mistaken_for_a_held_claim(fake):
    """T-L5. `order_keys` is explicit that a throttle or an outage must never be read as "already
    claimed", because the two have opposite remedies."""
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900, configuration_name='WECAREDIGITAL',
        provider_mid='acc_TEST', item_name='Service Fee', now=1770000000)
    fake.arm_failure('__client__', 'transact_write_items',
                     FakeClientError('ProvisionedThroughputExceededException'))
    with pytest.raises(wpr.PaymentRequestRefused) as refused:
        wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                    keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
                    invoice_reference_id=REFERENCE)
    assert refused.value.code == wpr.WA_PAY_IDENTITY_UNAVAILABLE
    assert refused.value.status_code == 503


def test_the_reservation_is_atomic_under_a_cancelled_transaction(fake):
    """T-L7, and the property a sequential implementation could not provide.

    A `PAYREF#` row written without its `REQUESTKEY#` anchor is a reference the webhook will
    reconcile on and that no retry can resolve to - so a second send mints a second reference
    against one invoice. A transaction removes that window rather than documenting it.
    """
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900, configuration_name='WECAREDIGITAL',
        provider_mid='acc_TEST', item_name='Service Fee', now=1770000000)
    # Pre-claim the COLLECTION row only, so the transaction loses on its third item.
    fake.Table(KEYS).put_item(Item={'orderId': order_keys.INVOICE_COLLECT_PREFIX + INVOICE_ID,
                                    'kind': order_keys.INVOICE_COLLECT_KIND,
                                    'paymentAttemptId': 'someone-else'})
    with pytest.raises(wpr.PaymentRequestRefused):
        wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                    keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
                    invoice_reference_id=REFERENCE)

    # ZERO of the other three rows exist. Nothing partial was written.
    assert _payref_rows(fake) == []
    assert [k for k in fake.tables[KEYS] if str(k).startswith(order_keys.REQUEST_KEY_PREFIX)] == []
    assert fake.count(ATTEMPTS) == 0


def test_a_lost_anchor_race_adopts_the_rivals_reservation(fake):
    """A racer that slips between the resolve read and the transaction loses the anchor and must
    ADOPT the winner's reservation - not mint a second reference for the same intent."""
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900, configuration_name='WECAREDIGITAL',
        provider_mid='acc_TEST', item_name='Service Fee', now=1770000000)
    winner, fresh = wpr.reserve(
        fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
        keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
        invoice_reference_id=REFERENCE)
    assert fresh is True

    adopted, fresh2 = wpr.reserve(
        fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
        keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
        invoice_reference_id=REFERENCE)
    assert fresh2 is False
    assert adopted['paymentAttemptId'] == winner['paymentAttemptId']
    assert adopted['referenceId'] == winner['referenceId'] == REFERENCE


# ══════════════════════════════════════════════════════════════════════════════
# T-L4: the release, which is what makes "cancel and re-raise" reachable
# ══════════════════════════════════════════════════════════════════════════════

def test_a_cancelled_invoice_releases_the_collection_claim(engine, fake):
    """T-L4, first half."""
    _seed(fake)
    _drive(engine, fake)
    assert len(_collect_rows(fake)) == 1

    resp = _cancel(engine, fake)
    assert resp['statusCode'] == 200
    assert _collect_rows(fake) == []
    # And the SEQUENCE advanced, which is the half that actually unblocks the next collection.
    assert fake.tables[INVOICES][INVOICE_ID][order_keys.INVOICE_COLLECT_SEQ_ATTR] == 1


def test_after_a_cancel_a_fresh_collection_at_a_new_amount_succeeds(engine, fake):
    """T-L4, and the whole point of the sequence.

    Edit -> `WA_PAY_INTENT_CHANGED` -> cancel -> a fresh collection goes out. Without the
    sequence the old anchor survives the cancel, the new amount mismatches its fingerprint, and
    the invoice is permanently uncollectable over WhatsApp with no stated recovery.
    """
    _seed(fake)
    _drive(engine, fake)
    old_payref = order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE
    assert old_payref in fake.tables[KEYS]

    # The operator edits the amount. The old reservation refuses, correctly.
    fake.Table(INVOICES).update_item(
        Key={'invoiceId': INVOICE_ID},
        UpdateExpression='SET #t = :t', ExpressionAttributeNames={'#t': 'total'},
        ExpressionAttributeValues={':t': '3500.00'})
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee', 'amount': '3500.00',
                                     'quantity': 1, 'gstRate': 18})
    refused, _ = _drive(engine, fake)
    assert _body(refused)['code'] == wpr.WA_PAY_INTENT_CHANGED

    # Cancel, then raise again. The invoice must be reopened for collection - a cancelled
    # invoice is not collectable, so the test reopens it the way a re-raise would.
    _cancel(engine, fake)
    fake.Table(INVOICES).update_item(
        Key={'invoiceId': INVOICE_ID},
        UpdateExpression='SET #s = :s, #ps = :ps',
        ExpressionAttributeNames={'#s': 'status', '#ps': 'paymentStatus'},
        ExpressionAttributeValues={':s': 'pending_payment', ':ps': 'pending'})

    resp, lam = _drive(engine, fake)
    assert resp['statusCode'] == 200, _body(resp)
    assert len(lam.invokes) == 1

    # ── the half that is easy to lose ──
    # The OLD `PAYREF#` row is still resolvable, and still carries the PRE-EDIT amount. A
    # customer who pays the message they already hold settles against the reservation that
    # message named, at the figure that message showed them.
    old_row = order_keys.resolve_payment_reference(fake.Table(KEYS), REFERENCE)
    assert old_row is not None
    assert old_row['amountPaise'] == 59900

    # The re-raise minted a FRESH reference at the new amount. It had to: the old reference is
    # taken by the retained row above, and that row records the old figure - so reusing it would
    # make a capture at ₹3,500 compare unequal and quarantine.
    new_reference = _body(resp)['referenceId']
    assert new_reference != REFERENCE
    new_row = order_keys.resolve_payment_reference(fake.Table(KEYS), new_reference)
    assert new_row['amountPaise'] == 350000

    # The invoice now names the new reference, with the superseded one kept for audit.
    invoice = fake.tables[INVOICES][INVOICE_ID]
    assert invoice['referenceId'] == new_reference
    assert invoice['previousReferenceId'] == REFERENCE

    # The new collection reserved a DIFFERENT request key, and the old anchor was NOT deleted -
    # nothing in this key space is ever reissued.
    anchors = [k for k in fake.tables[KEYS] if str(k).startswith(order_keys.REQUEST_KEY_PREFIX)]
    assert len(anchors) == 2, anchors


def test_the_release_is_conditional_on_the_row_being_a_collection_claim(fake):
    """A key collision must never delete something else. The condition is on `kind`."""
    fake.Table(KEYS).put_item(Item={'orderId': order_keys.INVOICE_COLLECT_PREFIX + INVOICE_ID,
                                    'kind': 'SOMETHING_ELSE'})
    assert order_keys.release_invoice_collection(
        fake.Table(KEYS), invoice_id=INVOICE_ID) is False
    assert order_keys.INVOICE_COLLECT_PREFIX + INVOICE_ID in fake.tables[KEYS]


def test_releasing_an_absent_claim_is_false_not_an_error(fake):
    assert order_keys.release_invoice_collection(
        fake.Table(KEYS), invoice_id='nope') is False


def test_the_request_key_carries_the_sequence():
    """The mechanism, stated as an assertion: a bumped sequence IS a different key."""
    assert wpr.collection_request_key('INV1', 0) == 'INVPAY#INV1#0'
    assert wpr.collection_request_key('INV1', 1) == 'INVPAY#INV1#1'
    assert wpr.collection_request_key('INV1', 0) != wpr.collection_request_key('INV1', 1)
