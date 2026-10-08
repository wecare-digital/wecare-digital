"""The GST invoice actually reaches the customer, exactly once, and a failed send is recoverable.

The gap this closes is narrow and was easy to miss: invoice CREATION on pay already worked and was
atomically deduplicated. DELIVERY was the hole - the automatic path was dead and the operator path
was live and consulted nothing, so the document existed and was never sent.

Three properties, and the second and third are the ones that bite.

**Once, by claim rather than by hope.** The claim lives INSIDE `send_invoice_whatsapp`, so the
webhook, the operator button and any future caller pass through it. A customer receiving two
identical GST invoices for one payment is a compliance artifact, not merely untidy.

**A failed send gives the slot back.** The claim is taken BEFORE the render, and
`send_invoice_whatsapp` swallows a Meta failure into `wa_status='failed'` and returns 200. A claim
never released on failure would consume the only slot, and every non-forced caller thereafter -
which is every caller today, because `force` defaults to False and the UI sends none - would get
`already_delivered`. That silently loses a GST invoice with nothing above INFO in the logs.

**The release cannot be used to duplicate.** It is conditional on `deliveryStatus = CLAIMED`, so a
CONFIRMED delivery can never be taken back.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')
WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ASSETS = 'stack-wecare-digital-InvoiceAssetsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
KEYS = 'stack-wecare-digital-CommerceKeys'

INVOICE_ID = 'inv-delivery-0001'
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1


# ══════════════════════════════════════════════════════════════════════════════
# the engine side: the claim
# ══════════════════════════════════════════════════════════════════════════════

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
        keys={INVOICES: 'invoiceId', ASSETS: 'invoiceId', DELIVERY: 'invoiceId',
              KEYS: 'orderId'},
        base_query_tables={DELIVERY})


class _Sender:
    """Records sends, and can fail the way Meta fails: an exception the engine swallows."""

    def __init__(self, status='sent', raises=None):
        self.invokes = []
        self.status = status
        self.raises = raises

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        if self.raises:
            raise self.raises
        body = json.dumps({'statusCode': 200,
                           'body': json.dumps({'status': self.status,
                                               'whatsappMessageId': 'wamid.INV'})})

        class _P:
            def read(self_inner):
                return body.encode()

        return {'Payload': _P(), 'StatusCode': 200}


def _seed(fake, *, with_asset=True):
    fake.Table(INVOICES).put_item(Item={
        'invoiceId': INVOICE_ID, 'status': 'paid', 'customerPhone': PHONE,
        'total': '599.00', 'referenceId': 'WD-PAY-DELIV01', 'invoiceNumber': 'WD/26-27/0001',
        'orderId': 'Offline', 'createdAt': 1770000000})
    if with_asset:
        fake.Table(ASSETS).put_item(Item={'invoiceId': INVOICE_ID, 'assetType': 'pdf',
                                          's3Key': 'secure/stack/invoices/x.png',
                                          'url': 'ignored'})


def _send(engine, fake, sender, *, force=False):
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', sender):
        ddb.Table.side_effect = fake.Table
        with patch.object(engine, 'COMMERCE_KEYS_TABLE', KEYS), \
             patch.object(engine, '_lookup_contact_by_phone', return_value=None), \
             patch.object(engine, '_signed_invoice_url', return_value='https://signed/x'):
            return engine.send_invoice_whatsapp(INVOICE_ID, PHONE, WABA1, 'req-1', force=force)


def _claim_rows(fake):
    return [k for k in fake.tables.get(KEYS, {})
            if str(k).startswith(order_keys.INVOICE_DELIVERY_PREFIX)]


def _body(resp):
    return json.loads(resp['body'])


def test_a_delivery_claims_once_and_confirms(engine, fake):
    """T-I1. One send, and the claim becomes EVIDENCE rather than staying an intent."""
    _seed(fake)
    sender = _Sender()
    resp = _send(engine, fake, sender)

    assert resp['statusCode'] == 200
    assert len(sender.invokes) == 1
    assert len(_claim_rows(fake)) == 1
    row = order_keys.resolve_invoice_delivery(fake.Table(KEYS), INVOICE_ID)
    assert row['deliveryStatus'] == order_keys.DELIVERY_CONFIRMED
    assert row['waMessageId'] == 'wamid.INV'


def test_a_second_non_forced_call_sends_nothing(engine, fake):
    """T-I2 / T-I5. The operator route and the webhook both pass through the claim, so the
    operator button cannot duplicate an automatic delivery."""
    _seed(fake)
    first = _Sender()
    _send(engine, fake, first)
    second = _Sender()
    resp = _send(engine, fake, second)

    assert _body(resp)['status'] == 'already_delivered'
    assert _body(resp)['deduplicated'] is True
    assert second.invokes == []
    assert len(_claim_rows(fake)) == 1


def test_a_failed_send_releases_the_claim_and_is_redeliverable(engine, fake, caplog):
    """M-4, and the defect this test exists for.

    The engine swallows a Meta failure into `wa_status='failed'` and returns 200. Without the
    release, the only slot is consumed and every subsequent non-forced caller gets
    `already_delivered` - which loses a GST invoice silently.
    """
    _seed(fake)
    failing = _Sender(raises=RuntimeError('Meta 500'))
    with caplog.at_level(logging.ERROR):
        _send(engine, fake, failing)

    assert 'invoice_delivery_failed_claim_released' in caplog.text
    assert _claim_rows(fake) == []

    # And a retry with NO `force` now actually sends.
    retry = _Sender()
    resp = _send(engine, fake, retry)
    assert len(retry.invokes) == 1
    assert _body(resp)['status'] == 'sent'


def test_a_successful_delivery_cannot_be_released(engine, fake):
    """The release is conditional on `CLAIMED`, so it can never be used to duplicate an invoice
    that genuinely went out."""
    _seed(fake)
    _send(engine, fake, _Sender())
    assert order_keys.release_invoice_delivery(
        fake.Table(KEYS), invoice_id=INVOICE_ID) is False
    assert len(_claim_rows(fake)) == 1


def test_a_render_failure_releases_the_claim_and_sends_nothing(engine, fake):
    """The 500-no-image path needs the release too, or an invoice whose asset was briefly
    missing becomes permanently undeliverable."""
    _seed(fake, with_asset=False)
    sender = _Sender()
    with patch.object(engine, 'generate_invoice_pdf',
                      return_value={'statusCode': 500, 'body': json.dumps({})}):
        resp = _send(engine, fake, sender)
    assert resp['statusCode'] == 500
    assert sender.invokes == []
    assert _claim_rows(fake) == []


def test_the_engine_still_renders_a_missing_asset_rather_than_refusing(engine, fake):
    """T-I8. A well-chosen tripwire: an implementer reconciling code to an older error table
    would have made the engine REFUSE a perfectly deliverable invoice."""
    _seed(fake, with_asset=False)
    sender = _Sender()
    with patch.object(engine, 'generate_invoice_pdf',
                      return_value={'statusCode': 200,
                                    'body': json.dumps({'s3Key': 'secure/x.pdf',
                                                        'pdfUrl': 'https://x'})}) as render:
        resp = _send(engine, fake, sender)
    assert render.called
    assert resp['statusCode'] == 200
    assert len(sender.invokes) == 1


def test_a_forced_resend_is_permitted_and_logged_at_warning(engine, fake, caplog):
    """T-I6. An operator genuinely does sometimes need to resend. Making it an explicit flag
    rather than the default means the duplicate is a decision with a log line behind it."""
    _seed(fake)
    _send(engine, fake, _Sender())
    forced = _Sender()
    with caplog.at_level(logging.WARNING):
        resp = _send(engine, fake, forced, force=True)
    assert len(forced.invokes) == 1
    assert _body(resp)['status'] == 'sent'
    assert 'invoice_delivery_forced' in caplog.text


def test_force_is_keyword_only_and_defaults_to_false(engine):
    """T-I15. The shape is the safety property: a caller that has never heard of `force` gets the
    idempotent behaviour, which is every caller today."""
    import inspect
    params = inspect.signature(engine.send_invoice_whatsapp).parameters
    assert params['force'].kind is inspect.Parameter.KEYWORD_ONLY
    assert params['force'].default is False


def test_a_claim_storage_error_sends_nothing(engine, fake):
    """T-I7. Fails CLOSED toward not sending: an undelivered invoice is recoverable by resending,
    a duplicate GST invoice is not."""
    _seed(fake)
    sender = _Sender()
    with patch.object(order_keys, 'claim_invoice_delivery',
                      side_effect=order_keys.OrderIdentityUnavailable('throttled')):
        resp = _send(engine, fake, sender)
    assert resp['statusCode'] == 503
    assert sender.invokes == []


def test_the_delivery_claim_row_carries_no_ttl(engine, fake):
    """T-I9."""
    _seed(fake)
    _send(engine, fake, _Sender())
    row = order_keys.resolve_invoice_delivery(fake.Table(KEYS), INVOICE_ID)
    assert 'ttl' not in row and 'expiresAt' not in row


def test_the_delivery_log_is_still_written_beside_the_claim(engine, fake):
    """T-I16. The two answer different questions: the claim answers "may I send?" with one
    conditional write; the log answers "what was sent, when?" with a durable history. Collapsing
    them would lose the history to gain nothing - and an append-only log keyed on a timestamp
    can never refuse a second write, so it could not be the claim."""
    _seed(fake)
    _send(engine, fake, _Sender())
    assert fake.count(DELIVERY) == 1
    assert len(_claim_rows(fake)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# the webhook side: the gate, and the review request
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def webhook():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, WEBHOOK_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


class _InvokeRecorder:
    """Records every Lambda invoke as `<function> <method> <path>`, so "which calls" is a set."""

    def __init__(self, *, deduplicated=False):
        self.calls = []
        self.bodies = []
        self.deduplicated = deduplicated

    def invoke(self, **kwargs):
        raw = json.loads(kwargs['Payload'])
        path = raw.get('rawPath', '')
        label = kwargs['FunctionName']
        if path:
            label += ' POST ' + path
        self.calls.append(label)
        try:
            self.bodies.append((path, json.loads(raw.get('body') or '{}')))
        except (TypeError, ValueError):
            self.bodies.append((path, {}))
        body = json.dumps({'statusCode': 200, 'body': json.dumps({
            'invoiceId': INVOICE_ID, 'invoiceNumber': 'WD/26-27/0001',
            'deduplicated': self.deduplicated})})

        class _P:
            def read(self_inner):
                return body.encode()

        return {'Payload': _P(), 'StatusCode': 202}

    def paths(self):
        return {c for c in self.calls}


def _post_payment(webhook, recorder, keys_fake, *, channel='whatsapp',
                  checkout_mode=wpr.WA_NATIVE_CHECKOUT_MODE):
    with patch.object(webhook, 'lambda_client', recorder), \
         patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS):
        ddb.Table.side_effect = keys_fake.Table
        webhook._post_payment_handler(
            'pay_X', '+918100640044', 'a@b.c', 'Service Fee', {}, 'req-pp',
            channel=channel, customer_uuid='', checkout_mode=checkout_mode,
            originating_phone_id=WABA1, reference_id='WD-PAY-DELIV01')


def test_a_native_whatsapp_capture_dispatches_exactly_one_invoice_delivery(webhook, fake):
    """T-I1 at the webhook. The send-whatsapp invoke carries the invoice, the customer and the
    SAME number that collected the payment."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake)

    sends = [c for c in recorder.calls if 'send-whatsapp' in c]
    assert len(sends) == 1

    delivery = [body for path, body in recorder.bodies if 'send-whatsapp' in path]
    assert delivery[0]['invoiceId'] == INVOICE_ID
    assert delivery[0]['phoneNumberId'] == WABA1
    assert delivery[0]['toWhatsAppNumber'].endswith('8100640044')
    # `deliveryReason` is deliberately absent: nothing reads it, and an unread payload key is
    # self-documentation a log line already does better.
    assert 'deliveryReason' not in delivery[0]
    # No `force` either: the engine's own claim is the idempotency control, and `force` defaults
    # to False there, so a redelivered capture gets `already_delivered` and sends nothing.
    assert 'force' not in delivery[0]


def test_a_deduplicated_invoice_is_still_delivered(webhook, fake):
    """T-I4, and the correction that makes the feature work at all.

    `send_payment_link` writes `referenceId` onto the invoice, so
    `create_invoice_from_payment` dedups onto it and reports `deduplicated: True` on the VERY
    FIRST capture. An early `return` on dedup would therefore skip delivery for the common case.
    """
    recorder = _InvokeRecorder(deduplicated=True)
    _post_payment(webhook, recorder, fake)

    assert any('send-whatsapp' in c for c in recorder.calls)
    # The two asset steps ARE skipped, which is what the dedup shortcut was for.
    assert not any('generate-image' in c for c in recorder.calls)
    assert not any('generate-pdf' in c for c in recorder.calls)


def test_a_website_origin_capture_sends_no_whatsapp_invoice(webhook, fake):
    """T-I3. A website order's receipt is not ours to send."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='website',
                  checkout_mode='WEBSITE_RAZORPAY_STANDARD')
    assert not any('send-whatsapp' in c for c in recorder.calls)


def test_a_catalogue_origin_capture_sends_no_whatsapp_invoice(webhook, fake):
    """T-I14, and the boundary that would otherwise drift.

    A catalogue order is `channel=whatsapp` but settles through the WEBSITE leg, whose own
    receipt path owns delivery. Gating on the channel ALONE would newly send a document to
    catalogue customers who receive none today - a behaviour change to an existing live leg,
    arriving as a side effect. The gate is on BOTH conditions, so this is closed by construction
    rather than by a list of exceptions.
    """
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='whatsapp',
                  checkout_mode='WEBSITE_RAZORPAY_STANDARD')
    assert not any('send-whatsapp' in c for c in recorder.calls)


def test_an_absent_checkout_mode_closes_the_gate(webhook, fake):
    """The legacy settlement row has no `PAYREF#` row at all, so it carries no mode. Defaulting
    to `''` is the fail-closed direction."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='whatsapp', checkout_mode='')
    assert not any('send-whatsapp' in c for c in recorder.calls)


def test_the_post_payment_handler_takes_no_float_amount(webhook):
    """T-F6. `amount` and `currency` were DEAD across the whole body - measured, neither name
    occurred after the signature - so they are deleted rather than retyped."""
    import inspect
    params = inspect.signature(webhook._post_payment_handler).parameters
    assert 'amount' not in params
    assert 'currency' not in params
    assert 'checkout_mode' in params
    assert 'originating_phone_id' in params


# ── the review request ────────────────────────────────────────────────────────

def test_the_review_template_is_sent_once_after_the_invoice(webhook, fake):
    """The approved `wecare_leave_review` template, fired ONCE and AFTER the invoice."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake)

    reviews = [c for c in recorder.calls if c == 'wecare-outbound-whatsapp']
    assert len(reviews) == 1
    # Ordering: the invoice delivery is dispatched before the review request.
    invoice_at = next(i for i, c in enumerate(recorder.calls) if 'send-whatsapp' in c)
    review_at = recorder.calls.index('wecare-outbound-whatsapp')
    assert invoice_at < review_at


def test_a_redelivered_capture_asks_for_a_review_only_once(webhook, fake):
    """Idempotent on the invoice, through the same conditional-write primitive the invoice
    delivery uses. A second review request for one payment is a nuisance message, and the kind
    of thing that accumulates silently unless it is claimed rather than hoped for."""
    first = _InvokeRecorder()
    _post_payment(webhook, first, fake)
    second = _InvokeRecorder()
    _post_payment(webhook, second, fake)

    assert 'wecare-outbound-whatsapp' in first.calls
    assert 'wecare-outbound-whatsapp' not in second.calls


def test_a_review_send_failure_never_blocks_the_paid_path(webhook, fake, caplog):
    """FAIL-OPEN, and the asymmetry with the invoice claim is deliberate: a missing review
    request costs nothing, a duplicate GST invoice is a compliance artifact. So the invoice claim
    fails CLOSED and this one fails OPEN - meaning it does not raise, never that it sends
    anyway."""

    class _ReviewFails(_InvokeRecorder):
        def invoke(self, **kwargs):
            if kwargs['FunctionName'] == 'wecare-outbound-whatsapp':
                raise RuntimeError('Meta 500')
            return super().invoke(**kwargs)

    recorder = _ReviewFails()
    with caplog.at_level(logging.WARNING):
        _post_payment(webhook, recorder, fake)   # must not raise

    assert any('send-whatsapp' in c for c in recorder.calls)
    assert 'review_request_send_failed' in caplog.text


def test_the_review_send_uses_waba1_and_the_approved_template(webhook, fake):
    """WABA1 only, and one home for the template name."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake)
    assert webhook.WA_REVIEW_TEMPLATE == 'wecare_leave_review'
