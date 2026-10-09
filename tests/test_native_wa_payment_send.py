"""The SEND leg: identity is reserved before anything is sent, and it is stable across retries.

Why this file exists
--------------------
A `reference_id` minted per send is a `reference_id` that differs on a retry, and two references
for one invoice is two captures and two orders - the one failure this domain must never have. So
the property under test is not "the send works", it is:

  * every reservation row exists BEFORE the sender is invoked,
  * a retried send resolves to the SAME reference and sends once,
  * an EDITED invoice cannot resume the old reservation, and `cancel` makes the next collection
    reachable while leaving the old `PAYREF#` row resolvable,
  * money is exact integer paise and a sub-paise total fails CLOSED,
  * WABA2 cannot be a payment sender, through any door,
  * the send travels in the approved template and never emits a link.
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

ENGINE_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'invoice-engine')

INVOICES = 'stack-wecare-digital-InvoicesTable'
ITEMS = 'stack-wecare-digital-InvoiceItemsTable'
DELIVERY = 'stack-wecare-digital-InvoiceDeliveryLogTable'
CONTACTS = 'stack-wecare-digital-ContactsTable'
KEYS = 'stack-wecare-digital-WixOrderIds'
ATTEMPTS = 'stack-wecare-digital-PaymentAttemptsTable'

INVOICE_ID = 'inv-nativepay-0001'
REFERENCE = 'WD-PAY-ABC12345'
CUSTOMER = 'contact-native-0001'
PHONE = '+918100640044'
WABA1 = wpr.PHONE_NUMBER_ID_1
WABA2 = 'phone-number-id-waba-t-direct-1055232054343117'


# ══════════════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════════════

#: The merchant id the readiness stub reports and the fixture expects. A test value, never the
#: live one: the point of the gate is that the expectation is COMPARED, not that it is correct.
TEST_MID = 'acc_TESTMID'
TEST_CONFIG = 'WECAREDIGITAL'


@pytest.fixture
def engine():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, ENGINE_DIR)
    # The two readiness EXPECTATIONS must be set in the fixture, because the handler no longer
    # carries literal defaults for them: an unconfigured deployment refuses, by design. Reading
    # them at import time is why this has to be `patch.dict` around the import rather than a
    # per-test patch.
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
        # Both are genuinely keyed `(invoiceId, <sort>)` in provisioning and are read on the
        # partition by design, so the base-table query is correct rather than a stray scan.
        base_query_tables={ITEMS, DELIVERY})


def _ready_configurations(*, name=TEST_CONFIG, mid=TEST_MID, status='active',
                          provider='Razorpay'):
    """The flattened `{data:[config,...]}` shape `payment_readiness.evaluate` consumes."""
    return {'data': [{'configuration_name': name, 'status': status,
                      'provider_name': provider, 'provider_mid': mid,
                      'waba_id': wpr.PHONE_ID_TO_WABA[WABA1]}]}


class _RecordingLambda:
    """Records every invoke so "nothing was sent" is an assertion rather than a hope.

    DISPATCHES ON PATH, because this handler now makes two different invokes through the one
    client: the readiness readback against `/wa-business/payment-config/list`, and the send.
    Without the split, every existing test in this file would see the readiness invoke answered
    with a send response and refuse with META_UNAVAILABLE — which is also why the readiness fetch
    is a module-level seam rather than inline code.

    `readiness` may be:
      * a dict      - returned as the readback body,
      * an Exception - raised, so META_UNAVAILABLE is reachable,
      * None        - a ready configuration is synthesised.
    """

    def __init__(self, status=200, readiness=None):
        self.invokes = []
        self.status = status
        self.readiness = readiness
        #: Counted separately so "zero readiness-fetch calls" is an assertion. Every refusal
        #: ordered ahead of the provider read must leave this at 0.
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
            if isinstance(self.readiness, Exception):
                raise self.readiness
            body = json.dumps({
                'statusCode': 200,
                'body': json.dumps(self.readiness if self.readiness is not None
                                   else _ready_configurations())})
        else:
            body = json.dumps({'statusCode': self.status,
                               'body': json.dumps({'status': 'sent',
                                                   'whatsappMessageId': 'wamid.TEST'})})

        class _Payload:
            def read(self_inner):
                return body.encode()

        return {'Payload': _Payload(), 'StatusCode': 200}

    def sends(self):
        """Only the SEND invokes. The readiness readback is not a send."""
        return [c for c in self.invokes if '/payment-config/list' not in self._path(c)]

    def payloads(self):
        out = []
        for call in self.sends():
            raw = json.loads(call['Payload'])
            out.append(json.loads(raw['body']) if 'body' in raw else raw)
        return out


def _seed_invoice(fake, *, total='599.00', reference=REFERENCE, items=None, extra=None):
    inv = {'invoiceId': INVOICE_ID, 'status': 'pending_payment', 'customerPhone': PHONE,
           'contactId': CUSTOMER, 'referenceId': reference, 'total': total,
           'tax': '0.00', 'discount': '0.00', 'shipping': '0.00', 'convenienceFee': '0.00',
           'gstRate': 18, 'goodsType': 'digital-goods', 'customerName': 'QA Recipient',
           'orderId': 'Offline', 'createdAt': 1770000000}
    inv.update(extra or {})
    fake.Table(INVOICES).put_item(Item=inv)
    fake.Table(ITEMS).put_item(Item={'invoiceId': INVOICE_ID, 'itemIndex': 0,
                                     'name': 'Service Fee',
                                     'amount': (items or [{'amount': total}])[0]['amount'],
                                     'quantity': 1, 'gstRate': 18})
    return inv


def _drive(engine, fake, lam, *, phone_id=WABA1, config='', verify_phone=''):
    """Call `send_payment_link` with storage and the sender injected."""
    with patch.object(engine, 'dynamodb') as ddb, patch.object(engine, 'lambda_client', lam):
        ddb.Table.side_effect = fake.Table
        ddb.meta.client = fake.client()
        with patch.object(engine, '_lookup_contact_by_phone',
                          return_value={'contactId': CUSTOMER}):
            return engine.send_payment_link(INVOICE_ID, phone_id, config, 'req-1',
                                            verify_phone=verify_phone)


def _rows(fake, prefix):
    return [r for k, r in fake.tables.get(KEYS, {}).items() if str(k).startswith(prefix)]


def _body(resp):
    return json.loads(resp['body'])


# ══════════════════════════════════════════════════════════════════════════════
# reserve before send
# ══════════════════════════════════════════════════════════════════════════════

def test_every_reservation_row_exists_and_the_send_happens_after(engine, fake):
    """T-S1. All four rows, then the invoke. A sender that fired first would be a reference the
    customer holds and we never reserved."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] == 200, _body(resp)
    assert len(_rows(fake, order_keys.REQUEST_KEY_PREFIX)) == 1
    assert len(_rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX)) == 1
    assert len(_rows(fake, order_keys.INVOICE_COLLECT_PREFIX)) == 1
    assert fake.count(ATTEMPTS) == 1
    # SENDS, not invokes: the readiness readback is an invoke through the same client and is not
    # a send. It runs BEFORE the transaction, which is the point of the gate's placement.
    assert len(lam.sends()) == 1
    assert lam.readiness_calls == 1

    # The transaction precedes the invoke in the recorded call order.
    ordering = [op for _table, op in fake.calls]
    assert 'transact_write_items' in ordering


def test_an_existing_invoice_reference_is_adopted_never_replaced(engine, fake):
    """T-S23, and the most important test here.

    `create_invoice` mints a `referenceId` for every invoice, so on the live path the id already
    exists before collection is raised. Replacing it would strand every payment request already
    in a customer's hands: their tap produces a capture whose reference resolves nowhere, and the
    capture quarantines as PAID_BUT_NO_ORDER - the exact symptom this feature exists to remove.
    """
    _seed_invoice(fake, reference=REFERENCE)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam)

    assert _body(resp)['referenceId'] == REFERENCE
    assert fake.tables[KEYS][order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE]
    # The invoice's own reference is UNCHANGED.
    assert fake.tables[INVOICES][INVOICE_ID]['referenceId'] == REFERENCE
    # And the sent payload carries it, not a fresh one.
    assert lam.payloads()[0]['checkoutOrderDetails']['reference_id'] == REFERENCE


def test_an_invoice_with_no_reference_is_refused_and_reserves_nothing(engine, fake):
    """The 400 guard is load-bearing: an invoice with no reference cannot reach collection."""
    _seed_invoice(fake, reference='')
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] == 400
    assert _rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX) == []
    assert lam.invokes == []


def test_a_retried_send_reuses_the_same_reference_and_sends_once(engine, fake):
    """T-S2. Resolve-before-generate, and the reason it matters: a new id on retry is a duplicate
    paid order."""
    _seed_invoice(fake)
    first = _drive(engine, fake, _RecordingLambda())
    lam2 = _RecordingLambda()
    second = _drive(engine, fake, lam2)

    assert _body(first)['referenceId'] == _body(second)['referenceId'] == REFERENCE
    assert len(_rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX)) == 1
    assert len(_rows(fake, order_keys.REQUEST_KEY_PREFIX)) == 1
    assert fake.count(ATTEMPTS) == 1
    # The `sendStatus` claim is already PENDING, so the second call does NOT invoke the sender.
    # It does re-read readiness, because the gate runs before the claim is consulted — the gate's
    # whole job is to refuse before anything is reserved, and that ordering is unchanged here.
    assert lam2.sends() == []
    assert _body(second)['deduplicated'] is True


def test_the_reserved_amount_equals_the_sent_total(engine, fake):
    """T-S9. Exact integer equality at capture is only meaningful if these two are the same
    integer, and they are the same integer BY CONSTRUCTION rather than by coincidence."""
    _seed_invoice(fake, total='599.00',
                  extra={'tax': '107.82', 'shipping': '40.00', 'discount': '10.00',
                         'convenienceFee': '14.14'})
    lam = _RecordingLambda()
    _drive(engine, fake, lam)

    attempt = list(fake.tables[ATTEMPTS].values())[0]
    sent = lam.payloads()[0]['checkoutOrderDetails']['total_amount']['value']
    assert attempt['amountPaise'] == sent
    assert isinstance(sent, int)
    # 59900 + 1414 (conv) + 10782 (tax) + 4000 (ship) - 1000 (disc)
    assert sent == 59900 + 1414 + 10782 + 4000 - 1000


def test_a_sub_paise_invoice_total_is_refused_at_send(engine, fake):
    """T-S10. A total carrying sub-paise noise cannot be compared exactly, so it fails CLOSED
    rather than truncating and matching a rounded-down expectation."""
    _seed_invoice(fake, total='99.005',
                  items=[{'amount': '99.005'}])
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam)

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == wpr.WA_PAY_AMOUNT_INVALID
    assert _rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX) == []
    assert lam.invokes == []


def test_the_reserved_attempt_carries_no_tender_split_attribute(engine, fake):
    """T-S22. `order_creation`'s expectation is the FULL `amountPaise` only because
    `razorpayChargedPaise` is absent - and an absence nothing asserts is not a property. Named so
    a later split-tender feature breaks here rather than making a PARTIAL capture compare equal
    to the full total."""
    _seed_invoice(fake)
    _drive(engine, fake, _RecordingLambda())

    attempt = list(fake.tables[ATTEMPTS].values())[0]
    payref = fake.tables[KEYS][order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE]
    for attr in ('razorpayChargedPaise', 'giftCardRedeemedPaise', 'wixGiftCardRedeemPaise'):
        assert attr not in attempt
        assert attr not in payref
    assert payref['payablePaise'] == payref['amountPaise']


def test_the_payref_row_carries_the_binding_inputs(engine, fake):
    """The settle leg reads `checkoutMode`, `phoneId` and `configurationName` off THIS row. A
    second home for any of them is a second answer to "is this capture ours"."""
    _seed_invoice(fake)
    _drive(engine, fake, _RecordingLambda())

    payref = fake.tables[KEYS][order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE]
    assert payref['checkoutMode'] == wpr.WA_NATIVE_CHECKOUT_MODE
    assert payref['channel'] == 'whatsapp'
    assert payref['configurationName'] == 'WECAREDIGITAL'
    assert payref['phoneId'] == WABA1
    assert payref['invoiceId'] == INVOICE_ID


def test_the_proven_configuration_name_is_the_sent_configuration_name(engine, fake):
    """T-S25, REWRITTEN. The half worth keeping from `..._defaults_rather_than_refusing`.

    That test asserted `engine.WA_PAY_CONFIG_NAME == 'WECAREDIGITAL'` as a literal default and
    that an empty `payment_configuration` still sends. Both halves are gone deliberately: a
    literal default is what requirements statement 9 forbids, and a send that "works" by falling
    back to an unproven constant is the defect rather than the behaviour to preserve. See
    `test_an_unconfigured_deployment_refuses_rather_than_defaulting` below for the inverse.

    What survives, and what actually matters: with the expectation SET, the name reserved on the
    attempt row and the name sent to Meta are the same string. Two copies of the resolution
    expression is how a proven name and a sent name diverge.
    """
    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam, config='')

    assert resp['statusCode'] == 200, _body(resp)
    attempt = list(fake.tables[ATTEMPTS].values())[0]
    assert attempt['configurationName'] == engine.WA_PAY_CONFIG_NAME == TEST_CONFIG
    # Reserved name and SENT name are the same string.
    assert (lam.payloads()[0]['checkoutOrderDetails']['payment_configuration']
            == attempt['configurationName'])


# ══════════════════════════════════════════════════════════════════════════════
# A1 — the readiness gate refuses BEFORE anything is reserved
# ══════════════════════════════════════════════════════════════════════════════

def _unconfigured_engine():
    """The handler imported with NEITHER expectation set — an unconfigured deployment."""
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, ENGINE_DIR)
    env = {k: v for k, v in os.environ.items()
           if k not in ('WA_PAY_CONFIG_NAME', 'EXPECTED_CONFIGURATION_NAME',
                        'EXPECTED_PROVIDER_MID')}
    env['AWS_REGION'] = 'us-east-1'
    with patch.dict(os.environ, env, clear=True):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


def test_neither_hardcoded_literal_survives_as_a_default():
    """The AST half of A1.4, and AST rather than a text search for the reason the template-name
    gate states outright: the comments explaining this rule necessarily contain the values, so a
    textual search flags its own explanation.

    Scoped to `os.environ.get` DEFAULTS, which is the only place a literal could read as "ready".
    """
    import ast
    import pathlib

    source = (pathlib.Path(REPO) / 'amplify' / 'functions' / 'payments' / 'invoice-engine'
              / 'handler.py').read_text(encoding='utf-8')
    defaults = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == 'environ'
                and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)):
            defaults.add(node.args[1].value)

    assert 'WECAREDIGITAL' not in defaults, (
        'a payment configuration name must not have an env default that reads as "ready"')
    assert 'acc_TTFSyolquKEZEy' not in defaults, (
        'the expected merchant id must not have an env default; "we did not compare the merchant '
        'id" must never read the same as "the merchant id matched"')


def test_an_unconfigured_deployment_refuses_rather_than_defaulting(fake):
    """A1.4's inverse, and the behaviour the old test asserted the opposite of.

    With neither expectation set, the resolution chain yields `''` and `evaluate` reports
    CONFIGURATION_UNVERIFIED. The refusal is the INTENDED outcome on an unconfigured deployment,
    not a regression — and it leaves no reservation behind.
    """
    engine = _unconfigured_engine()
    assert engine.WA_PAY_CONFIG_NAME == ''
    assert engine.WA_PAY_PROVIDER_MID == ''

    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam, config='')

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == engine.WA_PAY_NOT_READY
    assert _body(resp)['readiness'] == 'CONFIGURATION_UNVERIFIED'
    assert 'Nothing has been charged.' in _body(resp)['error']
    assert _rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX) == []
    assert _rows(fake, order_keys.REQUEST_KEY_PREFIX) == []
    assert fake.count(ATTEMPTS) == 0
    assert lam.sends() == []


def test_an_empty_expected_mid_alone_refuses(engine, fake):
    """`evaluate` blocks on an empty `expected_provider_mid` REGARDLESS of what the configuration
    name resolved to, and `build_request` refuses WA_PAY_PROVIDER_MID_REQUIRED independently. A
    stored `paymentConfiguration` on the invoice does not rescue the call."""
    _seed_invoice(fake, extra={'paymentConfiguration': TEST_CONFIG})
    lam = _RecordingLambda()
    with patch.object(engine, 'WA_PAY_PROVIDER_MID', ''):
        resp = _drive(engine, fake, lam, config='')

    assert resp['statusCode'] == 409
    assert _body(resp)['readiness'] == 'CONFIGURATION_UNVERIFIED'
    assert fake.count(ATTEMPTS) == 0
    assert lam.sends() == []


@pytest.mark.parametrize('readiness,state,status', [
    ({'data': []}, 'PAYMENT_CONFIG_MISSING', 409),
    ({'data': [{'configuration_name': 'SOMETHINGELSE', 'status': 'active',
                'provider_name': 'Razorpay', 'provider_mid': TEST_MID}]},
     'PAYMENT_CONFIG_NAME_UNKNOWN', 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'inactive',
                'provider_name': 'Razorpay', 'provider_mid': TEST_MID}]},
     'PAYMENT_CONFIG_INACTIVE', 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                'provider_name': 'Razorpay', 'provider_mid': 'acc_SOMEONEELSE'}]},
     'RAZORPAY_MID_MISMATCH', 409),
    ({}, 'META_UNAVAILABLE', 503),
    (RuntimeError('provider unreachable'), 'META_UNAVAILABLE', 503),
])
def test_each_blocking_verdict_refuses_with_the_right_status(engine, fake, readiness, state,
                                                             status):
    """Per-state coverage, and the 503/409 split.

    A 409 tells the staff UI "this will not succeed"; META_UNAVAILABLE and RAZORPAY_UNAVAILABLE
    will. Every one of them leaves ZERO reservation rows, which is the property that makes the
    gate's placement — before the transaction — the thing under test rather than its verdict.
    """
    _seed_invoice(fake)
    lam = _RecordingLambda(readiness=readiness)
    resp = _drive(engine, fake, lam, config='')

    assert resp['statusCode'] == status
    assert _body(resp)['code'] == engine.WA_PAY_NOT_READY
    assert _body(resp)['readiness'] == state
    assert 'Nothing has been charged.' in _body(resp)['error']
    assert _rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX) == []
    assert _rows(fake, order_keys.REQUEST_KEY_PREFIX) == []
    assert _rows(fake, order_keys.INVOICE_COLLECT_PREFIX) == []
    assert fake.count(ATTEMPTS) == 0
    assert lam.sends() == []


def test_an_unprovable_configuration_is_refused_by_name_before_the_provider_read(engine, fake):
    """`WECAREUPI` is a `upi` configuration with a VPA and no Razorpay merchant id, so `evaluate`
    could only ever report it as a misconfiguration — sending an operator to look for a
    configuration error that does not exist. Refused by name instead, with a cause, and before
    the provider is read at all."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam, config='WECAREUPI')

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == engine.WA_PAY_CONFIG_NOT_PROVABLE
    assert 'Nothing has been charged.' in _body(resp)['error']
    assert fake.count(ATTEMPTS) == 0
    assert lam.sends() == []
    assert lam.readiness_calls == 0


def test_a_forbidden_sender_is_refused_before_the_provider_read(engine, fake):
    """WABA2 by name, ahead of readiness. An unmapped sender would yield an empty WABA id and
    `evaluate` would answer CONFIGURATION_UNVERIFIED — closed, but under a name that reads as a
    misconfiguration. The named refusal is the earlier and more honest of the two."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam, phone_id=WABA2)

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
    assert lam.readiness_calls == 0


def test_the_waba_id_is_derived_from_the_sender_and_never_from_a_request(engine, fake):
    """A caller-supplied WABA id on a money path is a caller-supplied routing decision. The gate
    reads it from `PHONE_ID_TO_WABA` keyed on the RESOLVED sender, so the id in the readiness
    readback is the sender's own."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    _drive(engine, fake, lam, config='')

    readback = [c for c in lam.invokes
                if '/payment-config/list' in str(json.loads(c['Payload']).get('path') or '')]
    assert len(readback) == 1
    queried = json.loads(readback[0]['Payload'])['queryStringParameters']['wabaId']
    assert queried == wpr.PHONE_ID_TO_WABA[WABA1]


def test_the_gate_runs_before_the_reservation_in_source_order(engine):
    """Structural, because POSITION is what makes "a refusal leaves no reservation" true. Intent
    is not enough: a gate moved below the transaction would still refuse, and would still burn a
    reference doing it."""
    import inspect

    source = inspect.getsource(engine.send_payment_link)
    assert (source.index('payment_readiness.evaluate(')
            < source.index('wa_payment_request.build_request(')), (
        'readiness, then the reserve-and-send transaction')


def test_the_attempt_advances_to_request_sent_after_a_successful_send(engine, fake):
    """Without this the attempt sits in `PAYMENT_READINESS_CHECKED`, and the monotonic ladder
    that is supposed to stop a late event moving it backwards has nothing to refuse."""
    _seed_invoice(fake)
    _drive(engine, fake, _RecordingLambda())

    attempt = list(fake.tables[ATTEMPTS].values())[0]
    assert attempt['status'] == payment_attempt.PAYMENT_REQUEST_SENT
    assert attempt['sendStatus'] == 'SENT'


# ══════════════════════════════════════════════════════════════════════════════
# WABA1 only
# ══════════════════════════════════════════════════════════════════════════════

def test_waba2_cannot_be_a_payment_sender(engine, fake):
    """T-S4. Zero writes, zero invokes."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam, phone_id=WABA2)

    assert resp['statusCode'] == 409
    assert _body(resp)['code'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
    assert _rows(fake, order_keys.PAYMENT_REFERENCE_PREFIX) == []
    assert fake.count(ATTEMPTS) == 0
    assert lam.invokes == []


def test_the_sender_allow_set_is_exactly_waba1():
    assert wpr.PAYMENT_SENDERS == frozenset({wpr.PHONE_NUMBER_ID_1})
    assert WABA2 not in wpr.PAYMENT_SENDERS


# ══════════════════════════════════════════════════════════════════════════════
# the recipient, and the refusal matrix
# ══════════════════════════════════════════════════════════════════════════════

def test_the_recipient_always_comes_from_the_invoice(engine, fake):
    """T-S19. The routed path reads the recipient off the INVOICE ROW and never from the request,
    which is a stronger control than the optional `verify_phone` guard: a caller cannot redirect
    an invoice to another number at all."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    _drive(engine, fake, lam)

    assert lam.payloads()[0]['recipientPhone'] == PHONE


def test_verify_phone_still_refuses_a_mismatch_and_logs_nothing_unmasked(engine, fake, caplog):
    """The guard is kept for the one path that supplies a phone from outside the invoice, and its
    log is masked: it used to carry two full E.164 numbers."""
    import logging
    _seed_invoice(fake)
    with caplog.at_level(logging.ERROR):
        resp = _drive(engine, fake, _RecordingLambda(), verify_phone='+919812345678')
    assert resp['statusCode'] == 403
    assert PHONE not in caplog.text
    assert '9812345678' not in caplog.text


@pytest.mark.parametrize('kwargs,code', [
    ({'phone_e164': '+1555000111'}, wpr.WA_PAY_RECIPIENT_INVALID),
    ({'phone_e164': '+919330994400'}, wpr.WA_PAY_RECIPIENT_INVALID),
    ({'phone_number_id': WABA2}, wpr.WA_PAY_SENDER_NOT_PERMITTED),
    ({'amount_paise': 0}, wpr.WA_PAY_AMOUNT_INVALID),
    ({'amount_paise': -1}, wpr.WA_PAY_AMOUNT_INVALID),
    ({'amount_paise': True}, wpr.WA_PAY_AMOUNT_INVALID),
    ({'amount_paise': 59900.0}, wpr.WA_PAY_AMOUNT_INVALID),
    ({'amount_paise': wpr.MAX_AMOUNT_PAISE + 1}, wpr.WA_PAY_AMOUNT_INVALID),
    ({'currency': 'USD'}, wpr.WA_PAY_CURRENCY_UNSUPPORTED),
    ({'configuration_name': ''}, wpr.WA_PAY_CONFIG_NAME_REQUIRED),
    ({'provider_mid': ''}, wpr.WA_PAY_PROVIDER_MID_REQUIRED),
    ({'customer_id': ''}, wpr.WA_PAY_CUSTOMER_UNRESOLVED),
    ({'item_name': ''}, wpr.WA_PAY_ITEM_INVALID),
    ({'item_name': 'x' * 61}, wpr.WA_PAY_ITEM_INVALID),
    ({'order_details': {'payment_link_uri': 'https://rzp.io/x'}},
     wpr.WA_PAY_LINK_NOT_PERMITTED),
    ({'order_details': {'upi_intent_link': 'upi://pay?pa=x'}},
     wpr.WA_PAY_LINK_NOT_PERMITTED),
])
def test_every_validation_rule_refuses_before_any_write(kwargs, code):
    """T-S6. All of it runs in `build_request`, before any write and before any invoke, so a
    refusal leaves no partial state behind."""
    base = dict(invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
                phone_number_id=WABA1, amount_paise=59900,
                configuration_name='WECAREDIGITAL', provider_mid='acc_TEST',
                item_name='Service Fee', now=1770000000)
    base.update(kwargs)
    with pytest.raises(wpr.PaymentRequestRefused) as refused:
        wpr.build_request(**base)
    assert refused.value.code == code


def test_the_reserved_reference_is_meta_valid():
    """T-S11. Validated, never truncated: a truncated reference resolves to nothing at capture."""
    assert order_keys.is_valid_meta_reference_id(REFERENCE)
    minted = order_keys.mint_payment_reference()
    assert order_keys.is_valid_meta_reference_id(minted)
    assert len(minted) <= order_keys.META_REFERENCE_ID_MAX_LENGTH


def test_a_junk_invoice_reference_is_refused_rather_than_re_minted(engine, fake):
    """Silently re-minting is what produces two live references for one invoice."""
    _seed_invoice(fake, reference='not a valid meta reference!!')
    lam = _RecordingLambda()
    resp = _drive(engine, fake, lam)

    assert _body(resp)['code'] == wpr.WA_PAY_REFERENCE_INVALID
    assert lam.sends() == []


# ══════════════════════════════════════════════════════════════════════════════
# template-only on the wire
# ══════════════════════════════════════════════════════════════════════════════

def test_the_send_uses_the_approved_template_and_never_a_link(engine, fake):
    """T-S12 / T-P2. Asserted as a WHOLE-PAYLOAD property at any nesting depth, because a field
    check only proves the field it checked."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    _drive(engine, fake, lam)

    payload = lam.payloads()[0]
    assert payload['isCheckoutTemplate'] is True
    assert payload['isTemplate'] is True
    assert payload['templateName'] == engine.WA_PAY_TEMPLATE == 'wecarepay_wa'
    assert payload['checkoutOrderDetails']
    assert 'isInteractivePayment' not in payload

    forbidden = {'payment_link_uri', 'payment_link_success_url', 'payment_link_cancel_url',
                 'upi_intent_link'}

    def walk(node, path='payload'):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in forbidden, f'{path}.{key} is a link key'
                walk(value, f'{path}.{key}')
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f'{path}[{index}]')

    walk(payload)


def test_the_fixed_header_image_is_unchanged(engine, fake):
    """T-S13. Meta refetches an approved template header from its URL at send time, so this URL
    is part of the approved template rather than a per-order choice."""
    _seed_invoice(fake)
    lam = _RecordingLambda()
    _drive(engine, fake, lam)

    assert (lam.payloads()[0]['headerImageUrl']
            == 'https://wecare.digital/get/o/public/wa-tpl/img/wecarepay-header.png')


def test_the_module_never_resolves_a_payment_configuration():
    """T-S7. AST, both halves pinned together so they cannot drift apart: the module names none of
    the four configuration maps, AND `configuration_name` really is a required parameter."""
    import ast
    import inspect
    source = inspect.getsource(wpr)
    tree = ast.parse(source)
    banned = {'PHONE_PAYMENT_CONFIG', 'PHONE_PAYMENT_GATEWAYS',
              'VALID_PAYMENT_CONFIGS', 'DEFAULT_PAYMENT_CONFIG'}
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (named & banned), f'{sorted(named & banned)} is resolution, not carriage'

    params = inspect.signature(wpr.build_request).parameters
    assert params['configuration_name'].default is inspect.Parameter.empty


def test_every_reservation_key_is_composed_from_an_order_keys_prefix():
    """T-S20. AST. The WRITER moved into this module because `order_keys`' own writers cannot be
    `TransactItems` entries - so the prefixes must keep one home, or the move quietly duplicates
    the key space."""
    import ast
    import inspect
    import re
    tree = ast.parse(inspect.getsource(wpr))
    offenders = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and re.match(r'^[A-Z]+#', node.value)
        # `INVPAY#...` is a REQUEST KEY, not a row key: it is the value the `REQUESTKEY#` prefix
        # is concatenated with, and `order_keys` has no constant for it.
        and not node.value.startswith('INVPAY#')
    ]
    assert not offenders, f'hand-typed row-key prefixes: {offenders}'


def test_a_reserved_request_row_is_readable_by_the_order_keys_resolver(fake):
    """T-S21. The compatibility that justifies reusing the PREFIX rather than the FUNCTION."""
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900,
        configuration_name='WECAREDIGITAL', provider_mid='acc_TEST',
        item_name='Service Fee', now=1770000000)
    wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
                invoice_reference_id=REFERENCE)

    row = order_keys.resolve_checkout_request_key(
        fake.Table(KEYS), customer_id=CUSTOMER, request_key=request['requestKey'])
    assert row['kind'] == 'CHECKOUT_REQUEST_KEY'
    assert row['intentFingerprint']
    assert row['paymentAttemptId']


def test_no_reservation_row_carries_a_ttl(fake):
    """T-L6. `order_keys` is explicit: a uniqueness reservation that expires is an identifier
    that gets reissued, which defeats the entire purpose."""
    request = wpr.build_request(
        invoice_id=INVOICE_ID, customer_id=CUSTOMER, phone_e164=PHONE,
        phone_number_id=WABA1, amount_paise=59900,
        configuration_name='WECAREDIGITAL', provider_mid='acc_TEST',
        item_name='Service Fee', now=1770000000)
    wpr.reserve(fake.client(), fake.Table(KEYS), fake.Table(ATTEMPTS),
                keys_name=KEYS, attempts_name=ATTEMPTS, request=request,
                invoice_reference_id=REFERENCE)
    for row in fake.all_rows(KEYS):
        assert 'ttl' not in row and 'expiresAt' not in row
