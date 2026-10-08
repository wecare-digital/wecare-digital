"""The channel has to survive the whole way to the invoice, not just to the orders page.

THE SEAM THIS PINS, and why it was broken when the five Phase W batches first landed.

FEAT-002 put `channel` on the `PAYREF#` row, and said in a comment at `checkout/handler.py` why
it belongs there rather than only on the attempt: *"the webhook reconciles on this row and a
channel it cannot read is a channel a reconciliation cannot report."* FEAT-004 then built three
render sites that print `Source: Website|WhatsApp` from an invoice row's `channel`, and
`create_invoice_from_payment` grew a pass-through for it.

Nothing joined the two. `_create_order_for_captured_payment._load_attempt` narrowed the
`PAYREF#` row to six money/identity keys and dropped the channel, and `_post_payment_handler`
built the `/invoices/from-payment` body without one. So the one path that can actually produce an
invoice for a WhatsApp-origin order - the verified commerce path, which calls
`_post_payment_handler` at the end of `_handle_payment_captured` - would have issued a GST
invoice reading `Source: Website` for an order the customer's own orders page labelled WhatsApp.
Two documents, one order, contradicting each other, with no error anywhere.

Nothing observable changes for any order reachable today: `WA_CATALOG_ORDERS_ENABLED` is off, so
every `PAYREF#` row carries no channel, and `order_channel.canonical('')` is `website` on both
sides of the fix. What changes is that the WhatsApp case now has a value to print.

THREE PROPERTIES, in descending order of how much they would cost to get wrong:

  1. The channel is read from OUR row, never from the event. Razorpay `notes` are request
     content; attribution a request can set is attribution a customer can forge, and the Source
     line is reported back as fact on a tax document.
  2. It takes no part in any money decision. The attempt dict handed to `reconcile_payment` is
     byte-identical to the one it always received - the channel is noted beside that call, not
     added to it - so the currency equality and the exact-paise equality cannot have moved.
  3. It is total. A row with no channel, or a junk one, prints `Website` rather than raising
     inside a renderer - by which point the money has already moved.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_channel, order_keys  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')
ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')

KEYS_TABLE = 'stack-wecare-digital-WixOrderIds'
REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
ATTEMPT = '01930000-0000-7000-8000-000000000001'
TXN = 'pay_LIVE0000000001'
AMOUNT = 59900          # paise, integer, the only spelling this path accepts


def _load(directory):
    """Import a handler module with boto3 stubbed, isolating it from an already-imported one."""
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, directory)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


@pytest.fixture
def webhook():
    module = _load(WEBHOOK_DIR)
    yield module
    sys.modules.pop('handler', None)


@pytest.fixture
def engine():
    module = _load(ENGINE_DIR)
    yield module
    sys.modules.pop('handler', None)


@pytest.fixture
def keys_table():
    return FakeDynamo(keys={KEYS_TABLE: 'orderId'}).Table(KEYS_TABLE)


def _seed_payref(table, *, channel=None, amount=AMOUNT, currency='INR'):
    """A `PAYREF#` row as `checkout._allocate_reference` writes one.

    `channel` omitted means the key is absent, which is every row written before FEAT-002 and
    every row written today - not the empty string, which would be a different fact.
    """
    extra = {'customerId': 'CUS_01J0000000000000000000000',
             'amountPaise': amount, 'currency': currency,
             'checkoutMode': 'WEBSITE_RAZORPAY_STANDARD'}
    if channel is not None:
        extra['channel'] = channel
    order_keys.reserve_payment_reference(
        table, reference_id=REFERENCE, payment_attempt_id=ATTEMPT, extra=extra)


def _reconcile(webhook, keys_table, *, verifier=None, amount=AMOUNT):
    verifier = verifier or (lambda _r: (True, TXN, amount, 'INR'))
    payload = {'id': TXN, 'order_id': 'order_ABC', 'amount': amount,
               'currency': 'INR', 'status': 'captured'}
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.return_value = keys_table
        with patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier):
            return webhook._create_order_for_captured_payment(payload, REFERENCE, 'req-1')


def _commerce_event(*, notes=None):
    return {'payment': {'entity': {
        'id': TXN, 'order_id': 'order_ABC', 'amount': AMOUNT, 'currency': 'INR',
        'status': 'captured', 'method': 'upi', 'contact': '+919876543210',
        'email': 'buyer@example.com', 'description': 'order',
        'notes': notes if notes is not None else {'referenceId': REFERENCE},
    }}}


# ══════════════════════════════════════════════════════════════════════════════
# 1. the reconciliation reports the channel it read off our own row
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('stored,expected', [
    (order_channel.CHANNEL_WHATSAPP, order_channel.CHANNEL_WHATSAPP),
    (order_channel.CHANNEL_WEBSITE, order_channel.CHANNEL_WEBSITE),
    (None, order_channel.CHANNEL_WEBSITE),          # the key is absent, as on every live row
    ('', order_channel.CHANNEL_WEBSITE),
    ('WHATSAPP-ish', order_channel.CHANNEL_WEBSITE),
])
def test_the_outcome_reports_the_payref_rows_channel(webhook, keys_table, stored, expected):
    _seed_payref(keys_table, channel=stored)
    result = _reconcile(webhook, keys_table)

    assert result['outcome'] == 'ORDER_CREATED'
    assert result['channel'] == expected


def test_the_channel_survives_a_redelivery(webhook, keys_table):
    """The second delivery takes the idempotent branch, which returns a different outcome object
    built from a different row. It must still report the same origin, or a retried webhook would
    stamp a WhatsApp order's invoice as a website one."""
    _seed_payref(keys_table, channel=order_channel.CHANNEL_WHATSAPP)
    first = _reconcile(webhook, keys_table)
    second = _reconcile(webhook, keys_table)

    assert second['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert second['orderNumber'] == first['orderNumber']
    assert second['channel'] == first['channel'] == order_channel.CHANNEL_WHATSAPP


# ══════════════════════════════════════════════════════════════════════════════
# 2. it is attribution, so it may not reach a money decision
# ══════════════════════════════════════════════════════════════════════════════

def test_a_whatsapp_channel_does_not_soften_the_amount_equality(webhook, keys_table):
    """One paise is still a mismatch, and a mismatch still creates no order. The channel is a
    label on an order; it is not a reason to accept a different number."""
    _seed_payref(keys_table, channel=order_channel.CHANNEL_WHATSAPP)
    result = _reconcile(webhook, keys_table, amount=AMOUNT - 1)

    assert result['outcome'] == 'AMOUNT_MISMATCH'
    assert result['hasOrder'] is False
    assert not [k for k in keys_table.rows
                if str(k).startswith(order_keys.ORDER_NUMBER_PREFIX)]


def test_the_money_path_still_sees_exactly_the_attempt_it_always_did(webhook, keys_table):
    """The strongest form of property 2, and the reason the channel is noted BESIDE the call
    rather than added to the dict: `reconcile_payment` is handed the same six keys it has always
    been handed, so no amount, currency or eligibility rule can have been reached by this change.
    """
    from lambda_utils.ecommerce import order_creation as oc

    real, seen = oc.reconcile_payment, {}

    def _spy(*, table, reference_id, verify_payment, load_attempt, **kwargs):
        seen['keys'] = set((load_attempt(reference_id) or {}).keys())
        return real(table=table, reference_id=reference_id, verify_payment=verify_payment,
                    load_attempt=load_attempt, **kwargs)

    _seed_payref(keys_table, channel=order_channel.CHANNEL_WHATSAPP)
    with patch.object(oc, 'reconcile_payment', _spy):
        assert _reconcile(webhook, keys_table)['channel'] == order_channel.CHANNEL_WHATSAPP

    assert seen['keys'] == {'paymentAttemptId', 'customerId', 'amountPaise',
                            'providerPaymentId', 'providerOrderId', 'currency'}


def test_a_whatsapp_channel_does_not_soften_the_currency_equality(webhook, keys_table):
    _seed_payref(keys_table, channel=order_channel.CHANNEL_WHATSAPP, currency='USD')
    result = _reconcile(webhook, keys_table,
                        verifier=lambda _r: (True, TXN, AMOUNT, 'USD'))

    assert result['outcome'] == 'CURRENCY_MISMATCH'
    assert result['hasOrder'] is False


# ══════════════════════════════════════════════════════════════════════════════
# 3. the captured-payment path hands it to the invoice, and reads it from nowhere else
# ══════════════════════════════════════════════════════════════════════════════

def _drive_captured(webhook, outcome, *, notes=None):
    """Run the real `_handle_payment_captured` over a stubbed reconciliation, and report what
    `_post_payment_handler` was called with."""
    with patch.object(webhook, '_create_order_for_captured_payment', return_value=outcome), \
            patch.object(webhook, '_store_payment_record'), \
            patch.object(webhook, '_mark_invoice_paid_by_reference', return_value=True), \
            patch.object(webhook, '_post_payment_handler') as post, \
            patch.object(webhook, '_log_ctwa_purchase'), \
            patch.object(webhook, 'lambda_client', MagicMock()), \
            patch.object(webhook, 'dynamodb', MagicMock()):
        webhook._handle_payment_captured(_commerce_event(notes=notes), 'req-1')
    assert post.call_count == 1, 'the verified commerce path must still run post-payment'
    return post.call_args


def test_the_captured_path_hands_the_channel_to_the_invoice(webhook):
    call = _drive_captured(webhook, {
        'outcome': 'ORDER_CREATED', 'hasOrder': True, 'needsHuman': False,
        'channel': order_channel.CHANNEL_WHATSAPP,
    })
    assert call.kwargs['channel'] == order_channel.CHANNEL_WHATSAPP


def test_the_channel_is_never_taken_from_the_event_notes(webhook):
    """The forgery case, and the reason this value is read from the `PAYREF#` row at all. The
    notes claim WhatsApp; our row says website; the invoice must say website."""
    call = _drive_captured(
        webhook,
        {'outcome': 'ORDER_CREATED', 'hasOrder': True, 'needsHuman': False,
         'channel': order_channel.CHANNEL_WEBSITE},
        notes={'referenceId': REFERENCE, 'channel': 'whatsapp',
               'source': 'whatsapp', 'origin': 'whatsapp'},
    )
    assert call.kwargs['channel'] == order_channel.CHANNEL_WEBSITE


def test_an_outcome_with_no_channel_is_not_an_error(webhook):
    """Every outcome dict written before this seam existed - and the two early-return dicts in
    `_create_order_for_captured_payment` - carry no channel. An absent one is '' here and
    `website` at the engine, never a `KeyError` after the money moved."""
    call = _drive_captured(webhook, {
        'outcome': 'ORDER_ALREADY_EXISTS', 'hasOrder': True, 'needsHuman': False,
    })
    assert call.kwargs['channel'] == ''


# ══════════════════════════════════════════════════════════════════════════════
# 4. the invoice body actually carries it, and carries nothing else new
# ══════════════════════════════════════════════════════════════════════════════

def _from_payment_body(webhook, *, channel):
    """Run the real `_post_payment_handler` and return the `/invoices/from-payment` body."""
    seen = []

    def _invoke(**kwargs):
        payload = json.loads(kwargs['Payload'])
        if 'from-payment' in str(payload.get('rawPath', '')):
            seen.append(json.loads(payload['body']))
            return {'Payload': _Stream({'body': json.dumps({
                'invoiceId': 'inv-1', 'invoiceNumber': 'WD/2627/00001',
                'deduplicated': True})})}
        return {'Payload': _Stream({'body': '{}'})}

    client = MagicMock()
    client.invoke.side_effect = _invoke
    with patch.object(webhook, 'lambda_client', client):
        # `amount` and `currency` are GONE from this signature. They were DEAD across the whole
        # body - neither name occurred after the signature - so they are deleted rather than
        # retyped, which removes two float money parameters from a money path.
        webhook._post_payment_handler(
            TXN, '+919876543210', 'buyer@example.com',
            'desc', {}, 'req-1', channel=channel)
    assert len(seen) == 1
    return seen[0]


class _Stream:
    """The `.read()` surface `_post_payment_handler` uses on an invoke response."""

    def __init__(self, obj):
        self._raw = json.dumps(obj).encode()

    def read(self):
        return self._raw


def test_the_from_payment_body_carries_the_channel(webhook):
    assert _from_payment_body(
        webhook, channel=order_channel.CHANNEL_WHATSAPP
    )['channel'] == order_channel.CHANNEL_WHATSAPP


def test_the_channel_is_not_entry_point(webhook):
    """Two different facts. `entryPoint` records which internal flow minted the invoice, and a
    WhatsApp-origin catalogue order is settled by the website leg - so its entryPoint is
    `webhook` while its channel is `whatsapp`. Printing one as the other tells the customer the
    wrong origin."""
    body = _from_payment_body(webhook, channel=order_channel.CHANNEL_WHATSAPP)
    assert body['entryPoint'] == 'webhook'
    assert body['channel'] == order_channel.CHANNEL_WHATSAPP


def test_an_omitted_channel_is_still_a_valid_call(webhook):
    """`channel` is keyword-only with a default, so an omission is a silent `website` rather than
    a `TypeError` on a path where the capture has already happened. The same shape now carries
    `checkoutMode`, where the fail-closed direction matters more: an absent mode closes the
    invoice-delivery gate rather than sending a document we may not owe."""
    seen = []

    def _invoke(**kwargs):
        payload = json.loads(kwargs['Payload'])
        if 'from-payment' in str(payload.get('rawPath', '')):
            seen.append(json.loads(payload['body']))
        return {'Payload': _Stream({'body': json.dumps({
            'invoiceId': 'inv-1', 'deduplicated': True})})}

    client = MagicMock()
    client.invoke.side_effect = _invoke
    with patch.object(webhook, 'lambda_client', client):
        webhook._post_payment_handler(
            TXN, '+919876543210', 'b@example.com', 'desc', {}, 'req-1')

    assert seen[0]['channel'] == ''


# ══════════════════════════════════════════════════════════════════════════════
# 5. end to end: the row's channel is the word the invoice prints
# ══════════════════════════════════════════════════════════════════════════════

ITEMS = [{'name': 'Rs1 test product', 'amount': 1.0, 'quantity': 1}]


def _invoice_row(channel):
    """The invoice row `create_invoice` writes, with `channel` canonicalised on the way in."""
    return {
        'invoiceId': 'inv-1', 'invoiceNumber': 'WD/2627/00001',
        'referenceId': REFERENCE, 'orderId': 'WD-ORD-ABCD1234',
        'channel': order_channel.canonical(channel),
        'status': 'paid', 'paymentStatus': 'captured',
        'customerName': 'A. Customer', 'customerPhone': '+918100640044',
        'subtotal': 101.0, 'discount': 0.0, 'shipping': 0.0, 'handling': 0.0,
        'gstRate': 0.0, 'tax': 0.0, 'convenienceFee': 2.99, 'total': 103.99,
        'currency': 'INR', 'createdAt': 1791000000, 'paidAt': 1791000120,
    }


@pytest.mark.parametrize('stored,printed', [
    (order_channel.CHANNEL_WHATSAPP, 'Source: WhatsApp'),
    (order_channel.CHANNEL_WEBSITE, 'Source: Website'),
    (None, 'Source: Website'),
])
def test_the_word_on_the_payref_row_is_the_word_on_the_invoice(
        webhook, keys_table, engine, stored, printed):
    """The whole seam in one assertion: seed the `PAYREF#` row, reconcile, hand the reported
    channel to the invoice body, and render. What the customer reads on the tax invoice is what
    `checkout` wrote when the payment was prepared."""
    _seed_payref(keys_table, channel=stored)
    reported = _reconcile(webhook, keys_table)['channel']
    body = _from_payment_body(webhook, channel=reported)

    html = engine._build_invoice_html(_invoice_row(body['channel']), ITEMS)
    assert printed in html
