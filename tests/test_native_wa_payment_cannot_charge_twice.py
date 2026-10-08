"""Enumerate every external call the native leg can make, and assert the set EQUAL to a constant.

HOW THIS FILE IS BUILT, AND WHY
-------------------------------
"It cannot charge again" is usually asserted as an ABSENCE - no capture, no second create_order -
and an absence is exactly what a NEW call slips past. A test that says "capture was not called"
keeps passing when somebody adds a transfer or a second Wix write.

So this RECORDS every outbound call while driving the whole path and asserts the recorded set
EQUAL to a written-out permitted list, PER DRIVE. Adding any external call fails this file until
the list is edited, which is the point: editing it is a decision somebody has to make on purpose.

Four drives, because one constant genuinely cannot hold:

    SEND                 reserve -> send
    FRESH_CAPTURE        one payment.captured, invoice freshly created
    DEDUPLICATED_CAPTURE the same where the invoice already exists - the COMMON native case
    REPLAY               FRESH_CAPTURE then capture x3

The deduplicated set omits `generate-image`/`generate-pdf` precisely because the dedup shortcut
still skips them, while `send-whatsapp` is PRESENT - which is why one constant could not cover
both.

The recorder sits AT THE HTTP SEAM (`urlopen`) and at the Lambda seam, not over an application
function, which is what makes the enumeration meaningful rather than a mock asserting itself.
`test_the_enumeration_is_not_vacuous` proves the recorder is actually attached.
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

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys, payment_attempt  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402
from lambda_utils.integrations import meta_payment_binding as mpb  # noqa: E402
from lambda_utils.integrations import razorpay_orders, razorpay_verify  # noqa: E402

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')
WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ITEMS = 'stack-wecare-digital-InvoiceItemsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
KEYS = 'stack-wecare-digital-CommerceKeys'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'

INVOICE_ID = 'inv-nocharge-0001'
REFERENCE = 'WD-PAY-NOCHRG1'
ATTEMPT = '01930000-0000-7000-8000-0000000000bb'
GATEWAY_ORDER = 'order_META_NOCHRG'
PAYMENT = 'pay_META_NOCHRG'
AMOUNT = 59900
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1

# ── permitted RAZORPAY calls, per drive ──────────────────────────────────────
#
# `GET /v1/orders/{id}/payments` is UNREACHABLE here and deliberately absent:
# `verifier_for_event` computes `target = bound_payment or payment_id` and takes the orders
# branch only when `target` is empty, and a native `payment.captured` always carries a payment id.
#
# NOT HERE, AND THAT IS THE ASSERTION: no capture, no refund, no transfer, no settlement write,
# no payout, no payment-configuration call. And no `create_order` either - Meta creates the
# gateway order on this leg, which is the one respect in which it makes FEWER Razorpay calls
# than the website leg.
PERMITTED_RAZORPAY_CALLS_SEND = frozenset()
PERMITTED_RAZORPAY_CALLS_FRESH_CAPTURE = frozenset({'GET /v1/payments/{id}'})
PERMITTED_RAZORPAY_CALLS_DEDUPLICATED = frozenset({'GET /v1/payments/{id}'})
#: Count ONE, not four. A redelivery short-circuits in `reconcile_payment` BEFORE the provider
#: is contacted - deliberately, because a provider round trip per redelivery is both slow and a
#: way to get rate limited during exactly the incident that caused the redeliveries.
PERMITTED_RAZORPAY_CALLS_REPLAY = frozenset({'GET /v1/payments/{id}'})

# ── permitted META calls ─────────────────────────────────────────────────────
#
# TWO entries, not three. `_lookup_reference_id_from_meta` makes NO Graph call - read in full it
# is an `InvoicesTable` scan with a misleading docstring - so there is no second Meta lookup site
# to account for.
#
# No `POST`/`DELETE` on `/{waba}/payment_configurations`. Payment-configuration mutation is a
# standing refusal, and this enumeration proves it is ABSENT rather than merely unused.
PERMITTED_META_CALLS_SEND = frozenset({'POST /{phone_id}/messages'})
PERMITTED_META_CALLS_CAPTURE = frozenset({'GET /{phone_id}/payments/{config}/{reference_id}'})

# ── permitted WIX calls ──────────────────────────────────────────────────────
#
# EMPTY, and that is a consequence rather than an accident: the native path takes an `invoiceId`
# and never a basket, so no price is fetched and no cart is calculated. Nothing on this leg
# touches Wix at all.
PERMITTED_WIX_CALLS = frozenset()

#: Reused verbatim from the website-leg enumeration and asserted over the CONSTANT itself, so
#: widening it later to admit `create-order` fails here.
FORBIDDEN_WIX_FRAGMENTS = ('create-order', 'orders', 'checkout', 'payments', '/v1/')

# ── permitted LAMBDA invokes, per drive ──────────────────────────────────────
PERMITTED_LAMBDA_INVOKES_SEND = frozenset({'wecare-outbound-whatsapp'})

#: An EXISTING fire-and-forget hint on any `has_order` outcome: ids only, never raises, and the
#: receiver re-reads every link and no-ops for an ordinary order. Written out rather than
#: filtered, because an unlisted call is exactly what this file exists to catch - including one
#: that was already there.
SERVICE_REQUEST_HINT = 'wecare-service-requests:live'

PERMITTED_LAMBDA_INVOKES_FRESH_CAPTURE = frozenset({
    SERVICE_REQUEST_HINT,
    'wecare-invoice-engine POST /invoices/from-payment',
    'wecare-invoice-engine POST /invoices/{id}/generate-image',
    'wecare-invoice-engine POST /invoices/{id}/generate-pdf',
    'wecare-invoice-engine POST /invoices/{id}/send-whatsapp',
    'wecare-outbound-whatsapp',                      # the review request
})
PERMITTED_LAMBDA_INVOKES_DEDUPLICATED = frozenset({
    SERVICE_REQUEST_HINT,
    'wecare-invoice-engine POST /invoices/from-payment',
    'wecare-invoice-engine POST /invoices/{id}/send-whatsapp',
    'wecare-outbound-whatsapp',
})
#: A FOURTH drive, whose INVOICE behaviour is UNCHANGED by this work - which is exactly why it
#: needs a written-out constant. An unchanged behaviour with no test is the behaviour that
#: changes by accident.
#:
#: It omits `send-whatsapp` entirely, so widening the step-4 gate to the channel alone fails here
#: with a precise diff rather than a live catalogue customer receiving an unexpected GST
#: document. It DOES carry the review request, because step 5 is deliberately gated on
#: confirmed-paid rather than on the channel: a GST document is owed only where we collected the
#: money, but a review request is about the service, which is the same service either way.
PERMITTED_LAMBDA_INVOKES_CATALOGUE_CAPTURE = frozenset({
    SERVICE_REQUEST_HINT,
    'wecare-invoice-engine POST /invoices/from-payment',
    'wecare-invoice-engine POST /invoices/{id}/generate-image',
    'wecare-invoice-engine POST /invoices/{id}/generate-pdf',
    'wecare-outbound-whatsapp',                       # the review request
})

#: ONE global absence assertion across every drive, so a new call cannot hide in a drive nobody
#: wrote a constant for.
FORBIDDEN_CALL_FRAGMENTS = ('capture', 'refund', 'transfer', 'settlement', 'payout',
                            'payment_config', 'payment_configurations')


# ══════════════════════════════════════════════════════════════════════════════
# recorders, at the seams
# ══════════════════════════════════════════════════════════════════════════════

class Recorder:
    def __init__(self):
        self.razorpay = []
        self.meta = []
        self.wix = []
        self.lambdas = []

    # -- the HTTP seam -------------------------------------------------------
    def urlopen(self, request, timeout=None):
        url = getattr(request, 'full_url', str(request))
        method = getattr(request, 'method', 'GET')
        if 'api.razorpay.com' in url:
            self.razorpay.append(f'{method} {_normalise_razorpay(url)}')
            body = json.dumps({'id': PAYMENT, 'order_id': GATEWAY_ORDER, 'amount': AMOUNT,
                               'currency': 'INR', 'status': 'captured'})
        elif 'graph.facebook.com' in url:
            self.meta.append(f'{method} {_normalise_meta(url)}')
            body = json.dumps({'payments': [{'status': 'captured',
                                             'provider_order_id': GATEWAY_ORDER,
                                             'provider_payment_id': PAYMENT}]})
        elif 'wixapis.com' in url or 'www.wixapis' in url:
            self.wix.append(f'{method} {url}')
            body = '{}'
        else:  # pragma: no cover - an unrecognised host is itself a finding
            raise AssertionError(f'unrecognised external host: {url}')

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def read(self_inner):
                return body.encode()

            status = 200

        return _Resp()

    # -- the Lambda seam ----------------------------------------------------
    def lambda_client(self, *, deduplicated=False, invoice_id=INVOICE_ID, send_status='sent'):
        recorder = self

        class _Lambda:
            def invoke(self, **kwargs):
                raw = json.loads(kwargs['Payload'])
                path = raw.get('rawPath', '')
                label = kwargs['FunctionName']
                if path:
                    label += ' POST ' + _normalise_engine_path(path)
                recorder.lambdas.append(label)
                body = json.dumps({'statusCode': 200, 'body': json.dumps({
                    'invoiceId': invoice_id, 'invoiceNumber': 'WD/26-27/0001',
                    'deduplicated': deduplicated, 'status': send_status,
                    'whatsappMessageId': 'wamid.N', 's3Key': 'secure/x.png',
                    'imageUrl': 'https://x'})})

                class _P:
                    def read(self_inner):
                        return body.encode()

                return {'Payload': _P(), 'StatusCode': 202}

        return _Lambda()

    def all_calls(self):
        return set(self.razorpay) | set(self.meta) | set(self.wix) | set(self.lambdas)


def _normalise_razorpay(url):
    tail = url.split('api.razorpay.com', 1)[1]
    parts = [p for p in tail.split('?')[0].split('/') if p]
    if len(parts) >= 3 and parts[1] == 'payments':
        return '/v1/payments/{id}'
    if len(parts) >= 4 and parts[1] == 'orders':
        return '/v1/orders/{id}/' + parts[3]
    return '/' + '/'.join(parts)


def _normalise_meta(url):
    tail = url.split('graph.facebook.com', 1)[1]
    parts = [p for p in tail.split('?')[0].split('/') if p]
    # parts[0] is the API version.
    if len(parts) >= 5 and parts[2] == 'payments':
        return '/{phone_id}/payments/{config}/{reference_id}'
    if len(parts) >= 3 and parts[2] == 'messages':
        return '/{phone_id}/messages'
    return '/' + '/'.join(parts[1:])


def _normalise_engine_path(path):
    parts = [p for p in path.split('/') if p]
    if len(parts) == 3 and parts[0] == 'invoices':
        return f'/invoices/{{id}}/{parts[2]}'
    return path if path.startswith('/') else '/' + path


# ══════════════════════════════════════════════════════════════════════════════
# drives
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
def webhook():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, WEBHOOK_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


@pytest.fixture
def fake():
    return FakeDynamo(
        keys={INVOICES: 'invoiceId', ITEMS: 'invoiceId', DELIVERY: 'invoiceId',
              KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'},
        base_query_tables={ITEMS, DELIVERY})


def _seed_invoice(fake):
    fake.Table(INVOICES).put_item(Item={
        'invoiceId': INVOICE_ID, 'status': 'pending_payment', 'customerPhone': PHONE,
        'contactId': 'contact-nc-1', 'referenceId': REFERENCE, 'total': '599.00',
        'tax': '0.00', 'discount': '0.00', 'shipping': '0.00', 'convenienceFee': '0.00',
        'gstRate': 18, 'goodsType': 'digital-goods', 'orderId': 'Offline',
        'createdAt': 1770000000})
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee', 'amount': '599.00',
                                     'quantity': 1, 'gstRate': 18})


def _seed_reservation(fake, *, mode=None):
    row = {'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE,
           'kind': 'PAYMENT_REFERENCE', 'referenceId': REFERENCE,
           'paymentAttemptId': ATTEMPT, 'customerId': 'contact-nc-1',
           'amountPaise': AMOUNT, 'payablePaise': AMOUNT, 'currency': 'INR',
           'checkoutMode': wpr.WA_NATIVE_CHECKOUT_MODE if mode is None else mode,
           'channel': 'whatsapp', 'configurationName': 'WECAREDIGITAL',
           'phoneId': WABA1, 'wabaId': '2094615664435155', 'invoiceId': INVOICE_ID,
           'reservedAt': 1770000000}
    if mode is not None and mode != wpr.WA_NATIVE_CHECKOUT_MODE:
        # The website leg already has a binding from its own order create.
        row['providerOrderId'] = GATEWAY_ORDER
    fake.Table(KEYS).put_item(Item=row)
    attempt = payment_attempt.build(
        customer_id='contact-nc-1', reference_id=REFERENCE, amount_paise=AMOUNT,
        configuration_name='WECAREDIGITAL', payment_attempt_id=ATTEMPT, now=1770000000)
    attempt = payment_attempt.transition(
        attempt, payment_attempt.PAYMENT_REQUEST_SENT, now=1770000001)
    attempt.update(checkoutMode=row['checkoutMode'], channel='whatsapp',
                   invoiceId=INVOICE_ID, sendStatus='SENT')
    fake.Table(ATTEMPTS).put_item(Item=attempt)


def drive_send(engine, fake, recorder):
    _seed_invoice(fake)
    with patch.object(engine, 'dynamodb') as ddb, \
         patch.object(engine, 'lambda_client', recorder.lambda_client()), \
         patch.object(engine, 'COMMERCE_KEYS_TABLE', KEYS), \
         patch.object(engine, 'PAYMENT_ATTEMPTS_TABLE', ATTEMPTS):
        ddb.Table.side_effect = fake.Table
        ddb.meta.client = fake.client()
        with patch('urllib.request.urlopen', recorder.urlopen), \
             patch.object(engine, '_lookup_contact_by_phone',
                          return_value={'contactId': 'contact-nc-1'}):
            return engine.send_payment_link(INVOICE_ID, WABA1, '', 'req-send')


def drive_capture(webhook, fake, recorder, *, deliveries=1, deduplicated=False, mode=None):
    """A full `payment.captured`: reconcile, bind, record paid, then the post-payment steps."""
    _seed_reservation(fake, mode=mode)
    channel = 'whatsapp'
    checkout_mode = wpr.WA_NATIVE_CHECKOUT_MODE if mode is None else mode
    payload = {'id': PAYMENT, 'order_id': GATEWAY_ORDER, 'amount': AMOUNT,
               'currency': 'INR', 'status': 'captured'}
    lam = recorder.lambda_client(deduplicated=deduplicated)
    with patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'lambda_client', lam), \
         patch.object(webhook, 'PAYMENT_ATTEMPTS_TABLE', ATTEMPTS), \
         patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS), \
         patch('lambda_utils.ecommerce.order_keys.commerce_keys_table_name',
               return_value=KEYS), \
         patch('urllib.request.urlopen', recorder.urlopen), \
         patch.object(mpb, '_default_load_token', return_value='TOKEN'), \
         patch.object(razorpay_verify, '_credentials',
                      return_value={'key_id': 'rzp_test_x', 'key_secret': 'x'}):
        ddb.Table.side_effect = fake.Table
        outcome = None
        for _ in range(deliveries):
            outcome = webhook._create_order_for_captured_payment(payload, REFERENCE, 'req-cap')
            webhook._post_payment_handler(
                PAYMENT, PHONE, 'a@b.c', 'Service Fee', {}, 'req-cap',
                channel=channel,
                customer_uuid=str((outcome or {}).get('customerUuid') or ''),
                checkout_mode=str((outcome or {}).get('checkoutMode') or ''),
                originating_phone_id=WABA1, reference_id=REFERENCE)
        return outcome


# ══════════════════════════════════════════════════════════════════════════════
# set equality, per drive
# ══════════════════════════════════════════════════════════════════════════════

def test_the_send_drive_makes_exactly_the_permitted_calls(engine, fake):
    recorder = Recorder()
    resp = drive_send(engine, fake, recorder)
    assert resp['statusCode'] == 200, resp

    assert set(recorder.razorpay) == PERMITTED_RAZORPAY_CALLS_SEND
    assert set(recorder.wix) == PERMITTED_WIX_CALLS
    assert set(recorder.lambdas) == PERMITTED_LAMBDA_INVOKES_SEND


def test_the_fresh_capture_drive_makes_exactly_the_permitted_calls(webhook, fake):
    recorder = Recorder()
    outcome = drive_capture(webhook, fake, recorder)
    assert outcome['outcome'] == 'ORDER_CREATED', outcome

    assert set(recorder.razorpay) == PERMITTED_RAZORPAY_CALLS_FRESH_CAPTURE
    assert set(recorder.meta) == PERMITTED_META_CALLS_CAPTURE
    assert set(recorder.wix) == PERMITTED_WIX_CALLS
    assert set(recorder.lambdas) == PERMITTED_LAMBDA_INVOKES_FRESH_CAPTURE


def test_the_deduplicated_drive_makes_exactly_the_permitted_calls(webhook, fake):
    """No `generate-image`, no `generate-pdf`, but `send-whatsapp` PRESENT - which is why one
    constant could not cover both drives, and why the dedup shortcut had to be narrowed instead
    of returning early."""
    recorder = Recorder()
    drive_capture(webhook, fake, recorder, deduplicated=True)

    assert set(recorder.lambdas) == PERMITTED_LAMBDA_INVOKES_DEDUPLICATED
    assert set(recorder.wix) == PERMITTED_WIX_CALLS


def test_the_replay_drive_makes_exactly_the_permitted_calls(webhook, fake):
    """`GET /v1/payments/{id}` recorded ONCE despite four deliveries, and ONE Meta lookup."""
    recorder = Recorder()
    drive_capture(webhook, fake, recorder, deliveries=4)

    assert set(recorder.razorpay) == PERMITTED_RAZORPAY_CALLS_REPLAY
    assert len(recorder.razorpay) == 1, recorder.razorpay
    assert len(recorder.meta) == 1, recorder.meta
    assert set(recorder.wix) == PERMITTED_WIX_CALLS


def test_the_catalogue_capture_drive_sends_no_whatsapp_invoice(webhook, fake):
    """T-C11. A `channel=whatsapp`, `checkoutMode=WEBSITE_RAZORPAY_STANDARD` capture behaves
    exactly as it does today: no document, and no Meta lookup either."""
    recorder = Recorder()
    drive_capture(webhook, fake, recorder, mode='WEBSITE_RAZORPAY_STANDARD')

    assert set(recorder.lambdas) == PERMITTED_LAMBDA_INVOKES_CATALOGUE_CAPTURE
    assert 'send-whatsapp' not in ' '.join(recorder.lambdas)
    assert recorder.meta == []


def test_no_call_in_any_drive_matches_a_forbidden_fragment(engine, webhook, fake):
    """The global absence assertion, over the UNION of every recorded set - so a new call cannot
    hide in a drive nobody wrote a constant for."""
    send_recorder = Recorder()
    drive_send(engine, fake, send_recorder)

    cap_fake = FakeDynamo(
        keys={INVOICES: 'invoiceId', ITEMS: 'invoiceId', DELIVERY: 'invoiceId',
              KEYS: 'orderId', ATTEMPTS: 'paymentAttemptId'},
        base_query_tables={ITEMS, DELIVERY})
    cap_recorder = Recorder()
    drive_capture(webhook, cap_fake, cap_recorder)

    union = send_recorder.all_calls() | cap_recorder.all_calls()
    assert union, 'the recorder captured nothing; the assertion below would be vacuous'
    for call in union:
        lowered = call.lower()
        for fragment in FORBIDDEN_CALL_FRAGMENTS:
            # `/invoices/{id}/...` legitimately contains none of these, and the Meta payment
            # LOOKUP path contains `payments` - which is a READ of a payment, not a capture.
            if fragment == 'settlement' and 'payments/' in lowered:
                continue
            assert fragment not in lowered, f'{call} matches {fragment!r}'


def test_the_enumeration_is_not_vacuous(webhook, fake):
    """T-C10, and the test that keeps this file honest.

    An enumeration that passes because the recorder was never attached proves nothing. Inject a
    stray provider call and the fresh-capture equality must FAIL.
    """
    recorder = Recorder()
    drive_capture(webhook, fake, recorder)
    assert set(recorder.razorpay) == PERMITTED_RAZORPAY_CALLS_FRESH_CAPTURE

    recorder.razorpay.append('POST /v1/payments/{id}/capture')
    assert set(recorder.razorpay) != PERMITTED_RAZORPAY_CALLS_FRESH_CAPTURE


def test_the_wix_call_set_is_empty_and_the_forbidden_fragments_hold_over_it():
    """T-C8. Asserted over the CONSTANT itself, so widening it later to admit `create-order`
    fails here rather than passing quietly."""
    assert PERMITTED_WIX_CALLS == frozenset()
    for fragment in FORBIDDEN_WIX_FRAGMENTS:
        assert not any(fragment in call for call in PERMITTED_WIX_CALLS)


def test_no_gateway_order_is_created_on_this_leg():
    """T-C7. Meta creates it. Asserted over all four permitted Razorpay sets."""
    for permitted in (PERMITTED_RAZORPAY_CALLS_SEND,
                      PERMITTED_RAZORPAY_CALLS_FRESH_CAPTURE,
                      PERMITTED_RAZORPAY_CALLS_DEDUPLICATED,
                      PERMITTED_RAZORPAY_CALLS_REPLAY):
        assert not any('orders' in call for call in permitted)


def test_the_razorpay_module_has_no_capture_or_refund_function_to_call():
    """The STRONG form: not "we are careful not to charge twice" but "no code reachable from
    this path can charge at all" - asserted over a module's public surface, because a path
    cannot be proven free of a call whose existence it never checked."""
    surface = {name for name in dir(razorpay_orders) if not name.startswith('_')}
    for forbidden in ('capture', 'refund', 'transfer', 'payout', 'settle'):
        assert not any(forbidden in name.lower() for name in surface), forbidden


def test_the_verify_module_only_makes_get_requests():
    """T-C5. AST: every request `razorpay_verify` builds is a GET, and `_get` is the only
    transport."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(razorpay_verify))
    methods = [kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
               for kw in node.keywords
               if kw.arg == 'method' and isinstance(kw.value, ast.Constant)]
    assert methods
    assert set(methods) == {'GET'}


# ══════════════════════════════════════════════════════════════════════════════
# replay: counts that must not move
# ══════════════════════════════════════════════════════════════════════════════

def test_replaying_everything_moves_no_count(webhook, fake):
    """The replay table, as assertions. Four deliveries, and every quantity stays at one."""
    recorder = Recorder()
    drive_capture(webhook, fake, recorder, deliveries=4)

    def rows(prefix):
        return [k for k in fake.tables[KEYS] if str(k).startswith(prefix)]

    assert len(rows(order_keys.PAYMENT_REFERENCE_PREFIX)) == 1
    assert len(rows(order_keys.GATEWAY_ORDER_PREFIX)) == 1
    assert len(rows(order_keys.PAYMENT_ATTEMPT_PREFIX)) == 1
    assert len(rows(order_keys.ORDER_NUMBER_PREFIX)) == 1
    # TWO rows, and they answer different questions. `#whatsapp-dispatch` is the webhook's
    # "have I already asked the engine?"; `#review` is "have I already asked for feedback?". The
    # engine's own `#whatsapp` send claim is written inside `send_invoice_whatsapp`, which this
    # drive RECORDS rather than executes - `test_invoice_reaches_the_whatsapp_customer.py`
    # drives that side.
    assert sorted(rows(order_keys.INVOICE_DELIVERY_PREFIX)) == sorted([
        order_keys.INVOICE_DELIVERY_PREFIX + INVOICE_ID + '#whatsapp-dispatch',
        order_keys.INVOICE_DELIVERY_PREFIX + INVOICE_ID + '#review'])
    assert fake.count(ATTEMPTS) == 1
    assert len(recorder.razorpay) == 1
    assert len(recorder.meta) == 1
    # Exactly ONE invoice delivery dispatch and ONE review request across four deliveries.
    assert len([c for c in recorder.lambdas if 'send-whatsapp' in c]) == 1
    assert len([c for c in recorder.lambdas if c == 'wecare-outbound-whatsapp']) == 1


def test_a_replayed_settlement_finalizes_once_and_is_a_clean_no_op(webhook, fake):
    """The second half of "idempotent": not merely "does not double", but "the second time is
    SILENT". A redelivery that logs an ERROR is a redelivery somebody has to triage."""
    import logging
    recorder = Recorder()
    first = drive_capture(webhook, fake, recorder)
    assert first['outcome'] == 'ORDER_CREATED'

    second_recorder = Recorder()
    payload = {'id': PAYMENT, 'order_id': GATEWAY_ORDER, 'amount': AMOUNT,
               'currency': 'INR', 'status': 'captured'}
    with patch.object(webhook, 'dynamodb') as ddb, \
         patch.object(webhook, 'PAYMENT_ATTEMPTS_TABLE', ATTEMPTS), \
         patch.object(webhook, 'COMMERCE_KEYS_TABLE', KEYS), \
         patch('lambda_utils.ecommerce.order_keys.commerce_keys_table_name',
               return_value=KEYS), \
         patch('urllib.request.urlopen', second_recorder.urlopen), \
         patch.object(mpb, '_default_load_token', return_value='TOKEN'), \
         patch.object(razorpay_verify, '_credentials',
                      return_value={'key_id': 'rzp_test_x', 'key_secret': 'x'}):
        ddb.Table.side_effect = fake.Table
        import io
        stream = io.StringIO()
        handler_obj = logging.StreamHandler(stream)
        handler_obj.setLevel(logging.ERROR)
        root = logging.getLogger()
        root.addHandler(handler_obj)
        try:
            second = webhook._create_order_for_captured_payment(payload, REFERENCE, 'req-2')
        finally:
            root.removeHandler(handler_obj)

    assert second['outcome'] == 'ORDER_ALREADY_EXISTS'
    assert second['orderNumber'] == first['orderNumber']
    assert 'native_attempt_paid_evidence_conflict' not in stream.getvalue()
    assert second_recorder.razorpay == []   # answered before the provider was contacted
    assert second_recorder.meta == []       # the binding is write-once
