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
from pathlib import Path
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

    def __init__(self, status='sent', raises=None, status_code=200):
        self.invokes = []
        self.status = status
        self.raises = raises
        self.status_code = status_code

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        if self.raises:
            raise self.raises
        body = json.dumps({'statusCode': self.status_code,
                           'body': json.dumps({'status': self.status,
                                               'whatsappMessageId': 'wamid.INV'
                                                   if self.status_code < 400 else ''})})

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
        fake.Table(ASSETS).put_item(Item={'invoiceId': INVOICE_ID, 'assetType': 'image',
                                          's3Key': 'secure/Invoice/customer_invoice/x.png',
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


def test_a_paid_invoice_stays_paid_after_receipt_delivery(engine, fake):
    _seed(fake)
    _send(engine, fake, _Sender())
    assert fake.Table(INVOICES).get_item(Key={'invoiceId': INVOICE_ID})['Item']['status'] == 'paid'


def test_receipt_refuses_a_recipient_other_than_the_saved_customer(engine, fake):
    _seed(fake)
    sender = _Sender()
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', sender):
        ddb.Table.side_effect = fake.Table
        result = engine.send_invoice_whatsapp(INVOICE_ID, '+919903300044', WABA1, 'wrong-recipient')
    assert result['statusCode'] == 403
    assert sender.invokes == []
    assert _claim_rows(fake) == []


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
    failing = _Sender(status='failed')
    with caplog.at_level(logging.ERROR):
        _send(engine, fake, failing)

    assert 'invoice_delivery_failed_claim_released' in caplog.text
    assert _claim_rows(fake) == []

    # And a retry with NO `force` now actually sends.
    retry = _Sender()
    resp = _send(engine, fake, retry)
    assert len(retry.invokes) == 1
    assert _body(resp)['status'] == 'sent'


def test_a_downstream_http_rejection_releases_the_claim(engine, fake, caplog):
    """A parsed non-2xx response is definite rejection, never an ambiguous send outcome."""
    _seed(fake)
    rejected = _Sender(status='unknown', status_code=409)
    with caplog.at_level(logging.ERROR):
        resp = _send(engine, fake, rejected)

    assert resp['statusCode'] == 502
    assert _body(resp)['status'] == 'rejected'
    assert 'invoice_delivery_failed_claim_released' in caplog.text
    assert _claim_rows(fake) == []


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
    with patch.object(engine, 'generate_invoice_image',
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
    with patch.object(engine, 'generate_invoice_image',
                      return_value={'statusCode': 200,
                                    'body': json.dumps({'s3Key': 'secure/x.png',
                                                        'imageUrl': 'https://x'})}) as render:
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
            'deduplicated': self.deduplicated, 'status': 'sent',
            'whatsappMessageId': 'wamid.RECEIPT'})})

        class _P:
            def read(self_inner):
                return body.encode()

        return {'Payload': _P(), 'StatusCode': 202}

    def paths(self):
        return {c for c in self.calls}


def _post_payment(webhook, recorder, keys_fake, *, channel='whatsapp',
                  checkout_mode=wpr.WA_NATIVE_CHECKOUT_MODE, contact='+918100640044'):
    with patch.object(webhook, 'lambda_client', recorder), \
         patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS):
        ddb.Table.side_effect = keys_fake.Table
        webhook._post_payment_handler(
            'pay_X', contact, 'a@b.c', 'Service Fee', {}, 'req-pp',
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


class _FailingDeliveryRecorder(_InvokeRecorder):
    """Like `_InvokeRecorder`, but the send-whatsapp invoke reports a non-accepted delivery,
    so `_deliver_invoice_on_whatsapp` returns False and the retry/cap path is exercised."""

    def invoke(self, **kwargs):
        raw = json.loads(kwargs['Payload'])
        path = raw.get('rawPath', '')
        self.calls.append(kwargs['FunctionName'] + (' POST ' + path if path else ''))
        try:
            self.bodies.append((path, json.loads(raw.get('body') or '{}')))
        except (TypeError, ValueError):
            self.bodies.append((path, {}))
        if 'send-whatsapp' in path:
            body = json.dumps({'statusCode': 200, 'body': json.dumps(
                {'invoiceId': INVOICE_ID, 'status': 'failed', 'waMessageId': ''})})
        else:
            body = json.dumps({'statusCode': 200, 'body': json.dumps(
                {'invoiceId': INVOICE_ID, 'invoiceNumber': 'WD/26-27/0001',
                 'deduplicated': self.deduplicated, 'status': 'sent'})})

        class _P:
            def read(self_inner):
                return body.encode()

        return {'Payload': _P(), 'StatusCode': 202}


def test_a_missed_receipt_raises_to_trigger_a_bounded_replay(webhook, fake):
    """A transient delivery miss raises so Razorpay redelivers the capture - while under the cap."""
    recorder = _FailingDeliveryRecorder()
    with pytest.raises(RuntimeError, match='receipt delivery is pending'):
        _post_payment(webhook, recorder, fake)


def test_a_persistently_undeliverable_receipt_settles_and_quarantines(webhook, fake):
    """Past the attempt cap, the capture must settle (no raise) and the receipt is quarantined,
    so a receipt that can never be delivered cannot replay a finalized payment forever."""
    # Pre-seed the attempt counter at the cap so the next attempt is the exhausting one.
    fake.Table(INVOICES).update_item(
        Key={'invoiceId': INVOICE_ID},
        UpdateExpression='ADD receiptDispatchAttempts :n',
        ExpressionAttributeValues={':n': webhook._RECEIPT_DELIVERY_MAX_ATTEMPTS})
    recorder = _FailingDeliveryRecorder()
    # Must NOT raise now - the capture settles despite the undeliverable receipt.
    _post_payment(webhook, recorder, fake)


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


def test_a_website_origin_capture_sends_the_invoice_template_to_verified_whatsapp(webhook, fake):
    """Website checkout uses WhatsApp OTP identity, so its server-owned phone receives the receipt."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='website',
                  checkout_mode='WEBSITE_RAZORPAY_STANDARD')
    assert any('send-whatsapp' in call for call in recorder.calls)


def test_a_catalogue_origin_capture_also_sends_the_invoice_template(webhook, fake):
    """Channel/mechanics do not suppress a paid receipt once a verified recipient exists."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='whatsapp',
                  checkout_mode='WEBSITE_RAZORPAY_STANDARD')
    assert any('send-whatsapp' in call for call in recorder.calls)


def test_an_absent_checkout_mode_does_not_suppress_a_verified_receipt(webhook, fake):
    """Checkout mode is no longer the delivery gate; the resolved verified recipient is."""
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake, channel='website', checkout_mode='')
    assert any('send-whatsapp' in call for call in recorder.calls)


def test_no_verified_recipient_means_no_whatsapp_receipt(webhook, fake):
    """The universal rule never falls back to a browser/body phone."""
    recorder = _InvokeRecorder()
    with patch.object(webhook, 'lambda_client', recorder),          patch.object(webhook, 'dynamodb') as ddb,          patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS):
        ddb.Table.side_effect = fake.Table
        webhook._post_payment_handler(
            'pay_X', '', 'a@b.c', 'Service Fee', {}, 'req-pp',
            channel='website', customer_uuid='', checkout_mode='WEBSITE_RAZORPAY_STANDARD',
            originating_phone_id=WABA1, reference_id='WD-PAY-DELIV01')
    assert not any('send-whatsapp' in call for call in recorder.calls)


def test_the_post_payment_handler_takes_no_float_amount(webhook):
    """T-F6. `amount` and `currency` were DEAD across the whole body - measured, neither name
    occurred after the signature - so they are deleted rather than retyped."""
    import inspect
    params = inspect.signature(webhook._post_payment_handler).parameters
    assert 'amount' not in params
    assert 'currency' not in params
    assert 'checkout_mode' in params
    assert 'originating_phone_id' in params


# ── review entry point lives inside the invoice template ───────────────────────

def test_post_payment_sends_no_second_review_template(webhook, fake):
    recorder = _InvokeRecorder()
    _post_payment(webhook, recorder, fake)
    assert 'wecare-outbound-whatsapp' not in recorder.calls
    source = Path(webhook.__file__).read_text(encoding='utf-8')
    assert 'wecare_leave_review' not in source
    assert 'WA_REVIEW_TEMPLATE' not in source



def test_payment_notifications_use_the_invoice_recipient(webhook):
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.return_value.query.return_value = {'Items': [
            {'invoiceId': INVOICE_ID, 'customerPhone': PHONE}]}
        assert webhook._notification_recipient('WD-PAY-DELIV01', '+919903300044') == PHONE


def test_unavailable_invoice_binding_does_not_fall_back_to_payer(webhook):
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.return_value.query.side_effect = RuntimeError('unavailable')
        assert webhook._notification_recipient('WD-PAY-DELIV01', '+919903300044') == ''


def test_missing_invoice_does_not_restore_the_payer_as_recipient(webhook):
    with patch.object(webhook, 'dynamodb') as ddb:
        ddb.Table.return_value.query.return_value = {'Items': []}
        assert webhook._notification_recipient('WD-PAY-DELIV01', '+919903300044') == ''


def test_a_claim_with_no_send_evidence_is_pending_not_delivered(engine, fake):
    _seed(fake)
    order_keys.claim_invoice_delivery(fake.Table(KEYS), invoice_id=INVOICE_ID, channel='whatsapp')
    result = _send(engine, fake, _Sender())
    assert result['statusCode'] == 202
    assert _body(result)['status'] == 'delivery_pending'


def test_receipt_timeout_keeps_an_unconfirmed_claim(engine, fake):
    _seed(fake)
    result = _send(engine, fake, _Sender(raises=TimeoutError('provider outcome unknown')))
    assert result['statusCode'] == 202
    assert _body(result)['status'] == 'unknown'
    assert len(_claim_rows(fake)) == 1
    retry = _Sender()
    result = _send(engine, fake, retry)
    assert _body(result)['status'] == 'delivery_pending'
    assert retry.invokes == []


def test_receipt_dispatch_releases_a_definitively_rejected_engine_call(webhook, fake):
    import io
    class Rejects:
        def invoke(self, **kwargs):
            return {'StatusCode':200, 'Payload':io.BytesIO(json.dumps({
                'statusCode':403, 'body':json.dumps({'error':'recipient mismatch'})}).encode())}
    with patch.object(webhook, 'lambda_client', Rejects()), patch.object(webhook, 'dynamodb') as db:
        db.Table.side_effect = fake.Table
        assert webhook._deliver_invoice_on_whatsapp(INVOICE_ID, PHONE, WABA1, 'reject') is False
    assert order_keys.resolve_invoice_delivery(fake.Table(KEYS), INVOICE_ID,
                                               channel='whatsapp-dispatch') is None


def test_sent_word_without_provider_message_id_remains_unconfirmed(engine, fake):
    import io
    class NoProviderMessageId:
        def invoke(self, **kwargs):
            return {'Payload': io.BytesIO(json.dumps({'statusCode': 200,
                'body': json.dumps({'status': 'sent'})}).encode())}
    _seed(fake)
    result = _send(engine, fake, NoProviderMessageId())
    assert result['statusCode'] == 202
    claim = order_keys.resolve_invoice_delivery(fake.Table(KEYS), INVOICE_ID)
    assert claim['deliveryStatus'] != order_keys.DELIVERY_CONFIRMED
