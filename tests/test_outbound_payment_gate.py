"""Every in-WhatsApp payment send crosses ONE boundary, and that boundary refuses.

Why this file exists
--------------------
`wecare-outbound-whatsapp` is the only function in this repository that composes a Meta
`review_and_pay` message — `review_and_pay` appears in exactly one file. So every payment
surface reaches Meta through it: the invoice engine, the native catalog service leg, the
secure-files paid download, the staff inbox composer and the staff commerce "send bill" tool.

Gating each CALLER was the previous approach and it failed on contact with the evidence: a
surface nobody had enumerated was found ungated, and two more turned up behind it. Callers can be
added by anyone; the Meta boundary cannot, and two of the live callers are browser code that must
not be trusted with a gate at all.

The properties under test, in the order the gate evaluates them:

  1. a non-payment send pays NOTHING — including `isOrderStatus`, which is a post-payment
     NOTIFICATION and must never be refused on readiness: that would leave a customer who has
     already paid without a confirmation;
  2. the KILL SWITCH outranks everything, and is checked before any provider read;
  3. only WABA1 may take a payment, refused by name before any provider read;
  4. the two non-resolver envelopes are refused by name — this is the one that closes a real
     hole, see `TestTheNonResolverEnvelopesAreRefused`;
  5. an absent or empty `order_details` is refused;
  6. an unresolvable configuration is refused;
  7. a configuration this deployment cannot PROVE is refused by name, before the provider read;
  8. and only then is readiness evaluated against a live readback, with every blocking state
     mapped to 409 or 503.

Steps 2-7 make NO provider call, and every one of them asserts `fetches == 0` rather than
trusting the ordering. The Meta reads sit behind a module-level seam, so all of it runs offline.
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

from lambda_utils import payment_readiness  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

OUTBOUND_DIR = os.path.join(REPO, 'amplify', 'functions', 'messaging', 'outbound-whatsapp')

WABA1 = wpr.PHONE_NUMBER_ID_1
WABA2 = 'phone-number-id-waba-t-direct-1055232054343117'
WABA1_ID = wpr.PHONE_ID_TO_WABA[WABA1]

TEST_CONFIG = 'WECAREDIGITAL'
TEST_MID = 'acc_TESTMID'
TEMPLATE = 'wecarepay_wa'

ORDER_DETAILS = {'reference_id': 'WD-PAY-GATE0001', 'type': 'digital-goods',
                 'currency': 'INR', 'total_amount': {'value': 59900, 'offset': 100}}


@pytest.fixture
def outbound():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, OUTBOUND_DIR)
    # The two expectations are read at import time and have NO literal default — an empty value
    # makes `evaluate` answer CONFIGURATION_UNVERIFIED, which blocks. So they have to be set
    # around the import, and `TestAnUnconfiguredDeploymentRefuses` imports without them.
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1',
                                 'EXPECTED_CONFIGURATION_NAME': TEST_CONFIG,
                                 'EXPECTED_PROVIDER_MID': TEST_MID}):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    module.origin = 'http://localhost:3000'
    return module


def _import_outbound(**env):
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, OUTBOUND_DIR)
    base = {k: v for k, v in os.environ.items()
            if k not in ('EXPECTED_CONFIGURATION_NAME', 'EXPECTED_PROVIDER_MID')}
    base['AWS_REGION'] = 'us-east-1'
    base.update(env)
    with patch.dict(os.environ, base, clear=True):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    module.origin = 'http://localhost:3000'
    return module


class _Reads:
    """The injected Meta reads, counted and scriptable. Counting is the point.

    `configurations` and `templates` may each be a dict (returned), an Exception (raised, so
    META_UNAVAILABLE is reachable) or None (a ready answer is synthesised).
    """

    def __init__(self, configurations=None, templates=None):
        self.configurations = configurations
        self.templates = templates
        self.config_calls = 0
        self.template_calls = 0
        self.waba_ids = []

    @property
    def fetches(self):
        return self.config_calls + self.template_calls

    def fetch_configurations(self, waba_id):
        self.config_calls += 1
        self.waba_ids.append(waba_id)
        if isinstance(self.configurations, Exception):
            raise self.configurations
        if self.configurations is not None:
            return self.configurations
        return {'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                          'provider_name': 'Razorpay', 'provider_mid': TEST_MID,
                          'waba_id': waba_id}]}

    def fetch_templates(self, waba_id):
        self.template_calls += 1
        self.waba_ids.append(waba_id)
        if isinstance(self.templates, Exception):
            raise self.templates
        if self.templates is not None:
            return self.templates
        return {'data': [{'name': TEMPLATE, 'status': 'APPROVED', 'language': 'en'}]}


def _gate(outbound, body, *, phone_id=WABA1, reads=None):
    """Run the gate with both Meta reads stubbed. Returns `(refusal_or_None, reads)`."""
    reads = reads or _Reads()
    with patch.object(outbound, '_fetch_payment_configurations', reads.fetch_configurations), \
            patch.object(outbound, '_fetch_approved_templates', reads.fetch_templates):
        return outbound._refuse_unless_payment_ready(body, phone_id, 'req-gate'), reads


def _payment_body(**over):
    body = {'isCheckoutTemplate': True, 'isTemplate': True, 'templateName': TEMPLATE,
            'checkoutOrderDetails': dict(ORDER_DETAILS)}
    body.update(over)
    return body


def _error(refusal):
    return json.loads(refusal['body'])


# ══════════════════════════════════════════════════════════════════════════════
# 1. the gate is free for everything that is not a payment request
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('body', [
    {'content': 'hello'},
    {'isTemplate': True, 'templateName': 'wecare_otp', 'templateParams': ['1234']},
    {'mediaFile': 'o/x.png', 'mediaType': 'image'},
    {'isOtpTemplate': True, 'otpCode': '123456'},
    {'isInteractive': True, 'interactiveType': 'catalog_message'},
])
def test_a_non_payment_send_is_not_gated(outbound, body):
    """The gate returns on its first line, so ordinary traffic pays nothing — no Lambda round
    trip, no Graph read, no latency."""
    refusal, reads = _gate(outbound, body)
    assert refusal is None
    assert reads.fetches == 0


def test_an_order_status_notification_is_never_gated(outbound):
    """DELIBERATE, and asserted explicitly rather than left to the key list.

    An `order_status` message is a post-payment NOTIFICATION, which requirements statement 10
    still permits. Refusing one on readiness would leave a customer who has ALREADY PAID without
    a confirmation — the opposite of fail-closed. `isOrderStatus` is therefore absent from the
    arming keys, even though it is present in the handler's `payment_action` check, which answers
    a different question (does this need Admin?) and for which order_status does.
    """
    refusal, reads = _gate(outbound, {'isOrderStatus': True, 'orderStatus': 'shipped'})
    assert refusal is None
    assert reads.fetches == 0
    assert 'isOrderStatus' not in outbound._PAYMENT_REQUEST_KEYS


def test_the_arming_keys_are_exactly_the_three_payment_request_shapes(outbound):
    assert set(outbound._PAYMENT_REQUEST_KEYS) == {
        'isCheckoutTemplate', 'isPaymentTemplate', 'isInteractivePayment'}


# ══════════════════════════════════════════════════════════════════════════════
# 2. the kill switch, first and by itself
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'yes', 'on'])
@pytest.mark.parametrize('envelope', ['isCheckoutTemplate', 'isPaymentTemplate',
                                      'isInteractivePayment'])
def test_the_kill_switch_refuses_every_envelope_before_any_provider_read(outbound, value,
                                                                        envelope):
    """THE HARD-CONSTRAINT TEST, across every gated path.

    `payments_disabled()` is the ONE reader implementation; the gate calls it and does not
    re-read the env. It is checked BEFORE readiness because `payment_readiness.evaluate` also
    reads the flag and reports it as CONFIGURATION_UNVERIFIED — so without the explicit check
    first, a pulled brake would surface as a readiness verdict and lose its code, its 503 and its
    operator wording.
    """
    body = {envelope: True, 'templateName': TEMPLATE, 'orderDetails': dict(ORDER_DETAILS),
            'checkoutOrderDetails': dict(ORDER_DETAILS)}
    with patch.dict(os.environ, {'WA_PAYMENTS_DISABLED': value}):
        refusal, reads = _gate(outbound, body)

    assert refusal is not None
    assert refusal['statusCode'] == 503
    assert _error(refusal)['error'] == wpr.WA_PAY_DISABLED
    assert _error(refusal)['message'] == wpr.REFUSAL_MESSAGES[wpr.WA_PAY_DISABLED]
    assert 'Nothing has been charged.' in _error(refusal)['message']
    # The brake outranks the provider read, not merely the send.
    assert reads.fetches == 0


def test_the_kill_switch_outranks_a_blocking_readiness_verdict(outbound):
    """With the brake pulled AND a readback that would also block, the answer is the brake's."""
    reads = _Reads(configurations={'data': []})
    with patch.dict(os.environ, {'WA_PAYMENTS_DISABLED': 'true'}):
        refusal, reads = _gate(outbound, _payment_body(), reads=reads)
    assert _error(refusal)['error'] == wpr.WA_PAY_DISABLED
    assert reads.fetches == 0


def test_the_kill_switch_outranks_a_forbidden_sender_and_a_refused_envelope(outbound):
    """Ordering, asserted rather than assumed: the brake is step 2, ahead of both named
    refusals, so a pulled brake always reads as a pulled brake."""
    with patch.dict(os.environ, {'WA_PAYMENTS_DISABLED': 'true'}):
        refusal, _ = _gate(outbound, _payment_body(isPaymentTemplate=True), phone_id=WABA2)
    assert refusal['statusCode'] == 503
    assert _error(refusal)['error'] == wpr.WA_PAY_DISABLED


def test_the_gate_calls_the_one_kill_switch_reader_and_does_not_re_read_the_env(outbound):
    """No second implementation of the env read, and therefore no way for the two to disagree."""
    import inspect
    source = inspect.getsource(outbound._refuse_unless_payment_ready)
    assert 'wa_payment_request.payments_disabled()' in source
    assert 'WA_PAYMENTS_DISABLED' not in source
    # And the module imports the reader rather than copying it.
    assert outbound.wa_payment_request.payments_disabled is wpr.payments_disabled


# ══════════════════════════════════════════════════════════════════════════════
# 3. only WABA1 may take a payment  (review HIGH-2)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('config', [None, TEST_CONFIG, 'WECAREUPI'])
def test_waba2_fails_closed_at_the_gate_before_any_provider_read(outbound, config):
    """HIGH-2, and the hole a WABA map edit alone would not have closed.

    `_waba_for_sender` resolves WABA2 SUCCESSFULLY — `direct_send.META_PHONE_TO_WABA` holds both
    — and both WABAs carry an identical `WECAREDIGITAL` configuration with the same
    `provider_mid`. So without this check a payment request from WABA2 naming that configuration
    would resolve a valid name, equal the expectation, derive WABA2's id and come back
    PAYMENT_READY: the gate would say yes, and would log `payment_readiness_ready` for a sender
    that may never collect.

    Parametrised over the explicit-configuration override, because naming a configuration is a
    CHOICE OF CONFIGURATION and not a grant of permission.
    """
    details = dict(ORDER_DETAILS)
    if config:
        details['payment_configuration'] = config
    refusal, reads = _gate(outbound, _payment_body(checkoutOrderDetails=details),
                           phone_id=WABA2)

    assert refusal is not None
    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
    assert 'Nothing has been charged.' in _error(refusal)['message']
    assert reads.fetches == 0


def test_waba2_resolves_a_waba_id_which_is_why_the_check_is_not_redundant(outbound):
    """The premise of HIGH-2, pinned. If `_waba_for_sender` ever starts failing closed for WABA2
    this stops being load-bearing — but it does not today, and the gate must not depend on it."""
    assert outbound._waba_for_sender(WABA2)
    assert outbound._waba_for_sender(WABA2) != outbound._waba_for_sender(WABA1)


def test_the_gate_and_the_resolver_share_one_sender_allow_set(outbound):
    assert outbound.PAYMENT_SENDERS == wpr.PAYMENT_SENDERS == frozenset({WABA1})


def test_a_sender_that_resolves_to_no_waba_at_all_is_refused(outbound):
    refusal, reads = _gate(outbound, _payment_body(), phone_id='1016149501586345')
    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == wpr.WA_PAY_SENDER_NOT_PERMITTED
    assert reads.fetches == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. the two non-resolver envelopes are refused by name  (review HIGH-1)
# ══════════════════════════════════════════════════════════════════════════════

class TestTheNonResolverEnvelopesAreRefused:
    """The hole this closes is specific, and it is the reason "template-only" was not yet true.

    `_build_payment_settings` has two call sites: the `isCheckoutTemplate` branch and the
    `isInteractivePayment` branch. The `isPaymentTemplate` branch calls it NEVER — it attaches
    the caller's `order_details` dict VERBATIM as the button action. So an `isPaymentTemplate`
    request carrying a raw `payment_settings` with a `payment_link` would pass an account-level
    readiness check and be sent to Meta INSIDE the approved template, with none of the resolver's
    three controls applying: not the WABA1-only refusal, not the `payment_link_uri` /
    `upi_intent_link` refusals, not the `VALID_PAYMENT_CONFIGS` membership check.

    `isInteractivePayment` is refused for a different reason: it is a free-form interactive
    message rather than the approved template, so "payments are template-only" was true of the
    LINK and never of the MESSAGE TYPE.

    Both have zero callers in this repository, so refusing them costs nothing.
    """

    @pytest.mark.parametrize('envelope', ['isPaymentTemplate', 'isInteractivePayment'])
    def test_the_envelope_is_refused_before_any_provider_read(self, outbound, envelope):
        refusal, reads = _gate(outbound, {envelope: True, 'templateName': TEMPLATE,
                                          'orderDetails': dict(ORDER_DETAILS)})
        assert refusal is not None
        assert refusal['statusCode'] == 409
        assert _error(refusal)['error'] == 'WA_PAY_ENVELOPE_NOT_PERMITTED'
        assert _error(refusal)['message'] == (
            'WhatsApp payments must travel in the approved order_details template through the '
            'resolver. Nothing has been charged.')
        assert reads.fetches == 0

    def test_a_raw_payment_link_inside_the_template_envelope_never_reaches_meta(self, outbound):
        """The exploit shape, stated as a test. This payload would otherwise have been sent."""
        refusal, reads = _gate(outbound, {
            'isPaymentTemplate': True, 'isTemplate': True, 'templateName': TEMPLATE,
            'orderDetails': {
                'reference_id': 'WD-PAY-GATE0001',
                'payment_configuration': TEST_CONFIG,
                'payment_settings': [{'type': 'payment_link',
                                      'payment_link': {'uri': 'https://rzp.io/i/attacker'}}]}})
        assert _error(refusal)['error'] == 'WA_PAY_ENVELOPE_NOT_PERMITTED'
        assert reads.fetches == 0

    def test_both_envelopes_have_no_caller_left_in_the_repository(self):
        """Refusing them is free only because nothing sends them. Measured, not assumed."""
        import pathlib
        offenders = []
        for root in ('amplify', 'src'):
            for path in (pathlib.Path(REPO) / root).rglob('*'):
                if path.suffix not in ('.py', '.ts', '.tsx') or not path.is_file():
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                for key in ('isPaymentTemplate', 'isInteractivePayment'):
                    for lineno, line in enumerate(text.splitlines(), start=1):
                        if key not in line:
                            continue
                        stripped = line.strip()
                        # A comment or a docstring line explaining the refusal is not a caller,
                        # and the gate's own refusal list necessarily names both keys.
                        if stripped.startswith(('#', '*', '//', '/*', '"""', "'''", "#:")):
                            continue
                        if 'outbound-whatsapp/handler.py' in str(path):
                            continue
                        offenders.append(f'{path.relative_to(REPO)}:{lineno}')
        assert not offenders, (
            'a caller of a non-resolver payment envelope appeared: ' + ', '.join(offenders))

    def test_the_envelope_refusal_follows_the_brake_and_the_sender_check(self, outbound):
        import inspect
        source = inspect.getsource(outbound._refuse_unless_payment_ready)
        assert (source.index('payments_disabled()')
                < source.index('PAYMENT_SENDERS')
                < source.index('_REFUSED_PAYMENT_ENVELOPES')
                < source.index('_resolve_payment_config_name')
                < source.index('evaluate_for_delivery'))


# ══════════════════════════════════════════════════════════════════════════════
# 5. the order_details shape
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('details', [None, {}, [], 'not-a-dict', 0])
def test_an_absent_or_empty_order_details_is_refused(outbound, details):
    """An EMPTY dict is refused too, and that is not pedantry: `{}` would fall through to the
    sender's phone map, let the gate prove a configuration, and arrive at the send as a payment
    request that names no order at all."""
    body = {'isCheckoutTemplate': True, 'templateName': TEMPLATE}
    if details is not None:
        body['checkoutOrderDetails'] = details
    refusal, reads = _gate(outbound, body)

    assert refusal is not None
    assert refusal['statusCode'] == 400
    assert _error(refusal)['error'] == 'ORDER_DETAILS_INVALID'
    assert _error(refusal)['message'] == 'Nothing has been charged.'
    assert reads.fetches == 0


def test_either_order_details_key_satisfies_the_shape_check(outbound):
    """`checkoutOrderDetails` is the checkout-template key and `orderDetails` the other two's, so
    the gate reads both — otherwise an envelope could arm the gate and then be judged on an empty
    dict."""
    refusal, _ = _gate(outbound, {'isCheckoutTemplate': True, 'templateName': TEMPLATE,
                                  'orderDetails': dict(ORDER_DETAILS)})
    assert refusal is None


# ══════════════════════════════════════════════════════════════════════════════
# 6-7. the configuration name: ONE resolver, and only a provable name
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unprovable_configuration_is_refused_by_name_before_the_provider_read(outbound):
    """`WECAREUPI` is a `upi` configuration with a VPA and NO Razorpay merchant id, so
    `evaluate` — which compares a merchant id and nothing else — could only ever report it as
    CONFIGURATION_UNVERIFIED or RAZORPAY_MID_MISMATCH. Both read as "something is misconfigured"
    and would send an operator looking for a configuration error that does not exist.

    Refusing UPI OUTSIDE a provable configuration is not refusing UPI: collecting it INSIDE the
    approved template through `configuration_name: 'WECAREUPI'` stays a legitimate capability
    this business does not currently use, and enabling it is an owner decision that needs
    `payment_readiness` to learn a per-configuration expectation.
    """
    details = dict(ORDER_DETAILS, payment_configuration='WECAREUPI')
    refusal, reads = _gate(outbound, _payment_body(checkoutOrderDetails=details))

    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == 'WA_PAY_CONFIG_NOT_PROVABLE'
    assert 'Nothing has been charged.' in _error(refusal)['message']
    assert reads.fetches == 0


def test_an_unrecognised_configuration_is_refused_rather_than_substituted(outbound):
    details = dict(ORDER_DETAILS, payment_configuration='WECARE-RAZOR-PAY')
    refusal, reads = _gate(outbound, _payment_body(checkoutOrderDetails=details))

    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == wpr.WA_PAY_CONFIG_UNRESOLVED
    assert reads.fetches == 0


def test_the_proven_configuration_and_the_sent_configuration_come_from_one_resolver(outbound):
    """THE identity that makes the gate meaningful.

    Across the whole matrix — explicit configuration, mapped sender, unknown name — the gate's
    resolver and the sender's resolver give the same answer, because they are the SAME FUNCTION.
    Two copies of the resolution expression is how a proven name and a sent name diverge.
    """
    cases = [
        (WABA1, {}, TEST_CONFIG),
        (WABA1, {'payment_configuration': TEST_CONFIG}, TEST_CONFIG),
        (WABA1, {'payment_configuration': 'WECAREUPI'}, 'WECAREUPI'),
    ]
    for phone_id, extra, expected in cases:
        details = dict(ORDER_DETAILS, **extra)
        assert outbound._resolve_payment_config_name(phone_id, details) == expected
        settings = outbound._build_payment_settings(phone_id, details)
        assert settings[0]['payment_gateway']['configuration_name'] == expected

    for phone_id, details in ((WABA1, {'payment_configuration': 'NOPE'}),
                              ('phone-number-id-unmapped', {})):
        with pytest.raises(outbound.PaymentConfigurationUnresolved):
            outbound._resolve_payment_config_name(phone_id, dict(ORDER_DETAILS, **details))
        with pytest.raises(outbound.PaymentConfigurationUnresolved):
            outbound._build_payment_settings(phone_id, dict(ORDER_DETAILS, **details))


def test_the_resolver_extraction_did_not_move_the_senders_refusal(outbound):
    """The refactor's one invariant: `_build_payment_settings` keeps every refusal it had, in the
    order it had them, and the extracted call runs LAST of the three."""
    import inspect
    source = inspect.getsource(outbound._build_payment_settings)
    assert (source.index('PAYMENT_SENDERS')
            < source.index("'payment_link_uri', 'upi_intent_link'")
            < source.index('_resolve_payment_config_name'))


# ══════════════════════════════════════════════════════════════════════════════
# 8. the live readback, per blocking state
# ══════════════════════════════════════════════════════════════════════════════

def test_a_proven_configuration_and_an_approved_template_let_the_send_proceed(outbound):
    refusal, reads = _gate(outbound, _payment_body())
    assert refusal is None
    assert reads.config_calls == 1
    assert reads.template_calls == 1
    # The WABA id is derived from the SENDER, never read from the request body: a
    # caller-supplied WABA id on a money path is a caller-supplied routing decision.
    assert set(reads.waba_ids) == {WABA1_ID}


def test_a_waba_id_in_the_request_body_is_ignored(outbound):
    _, reads = _gate(outbound, _payment_body(wabaId='2513394156072604'))
    assert set(reads.waba_ids) == {WABA1_ID}


@pytest.mark.parametrize('configurations,state,status', [
    ({'data': []}, payment_readiness.PAYMENT_CONFIG_MISSING, 409),
    ({'data': [{'configuration_name': 'SOMETHINGELSE', 'status': 'active',
                'provider_name': 'Razorpay', 'provider_mid': TEST_MID}]},
     payment_readiness.PAYMENT_CONFIG_NAME_UNKNOWN, 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'inactive',
                'provider_name': 'Razorpay', 'provider_mid': TEST_MID}]},
     payment_readiness.PAYMENT_CONFIG_INACTIVE, 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                'provider_name': 'PayU', 'provider_mid': TEST_MID}]},
     payment_readiness.PAYMENT_CONFIG_INACTIVE, 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                'provider_name': 'Razorpay', 'provider_mid': 'acc_SOMEONEELSE'}]},
     payment_readiness.RAZORPAY_MID_MISMATCH, 409),
    ({'data': [{'configuration_name': TEST_CONFIG, 'status': 'active',
                'provider_name': 'Razorpay', 'provider_mid': ''}]},
     payment_readiness.CONFIGURATION_UNVERIFIED, 409),
    ({}, payment_readiness.META_UNAVAILABLE, 503),
    ({'error': {'message': 'nope'}}, payment_readiness.META_UNAVAILABLE, 503),
    (RuntimeError('provider unreachable'), payment_readiness.META_UNAVAILABLE, 503),
])
def test_each_blocking_configuration_state_refuses_with_the_right_status(
        outbound, configurations, state, status):
    """503 for the two availability states, 409 for the other eight.

    A 409 tells the staff UI "this will not succeed"; META_UNAVAILABLE and RAZORPAY_UNAVAILABLE
    will. An absent `data` key is META_UNAVAILABLE and NOT "none": one means Meta did not answer
    the question, the other means it answered "none", and reporting a missing key as MISSING
    would claim knowledge we do not have.
    """
    reads = _Reads(configurations=configurations)
    refusal, _ = _gate(outbound, _payment_body(), reads=reads)

    assert refusal is not None
    assert refusal['statusCode'] == status
    assert _error(refusal)['error'] == 'WA_PAY_NOT_READY'
    assert 'Nothing has been charged.' in _error(refusal)['message']
    # The verdict is logged, never returned: `as_dict()` is the operator projection and names our
    # WABA id, our configuration and our merchant id.
    assert state not in json.dumps(_error(refusal))


def test_a_meta_outage_blocks_rather_than_sends(outbound):
    """The accepted consequence, asserted so it is a decision and not a surprise. An unreachable
    provider and a misconfigured one are indistinguishable from the module's position, and both
    must block. The compensating control is the `wa_payment_readiness_refused` alarm."""
    reads = _Reads(configurations=TimeoutError('read timed out'))
    refusal, _ = _gate(outbound, _payment_body(), reads=reads)
    assert refusal['statusCode'] == 503


# ── the approved template, proven and not assumed (A3.1) ──────────────────────

@pytest.mark.parametrize('templates', [
    {'data': []},
    {'data': [{'name': TEMPLATE, 'status': 'PENDING', 'language': 'en'}]},
    {'data': [{'name': TEMPLATE, 'status': 'REJECTED', 'language': 'en'}]},
    {'data': [{'name': TEMPLATE, 'status': 'PAUSED', 'language': 'en'}]},
    {'data': [{'name': TEMPLATE, 'status': 'DISABLED', 'language': 'en'}]},
    {'data': [{'name': 'wecare_otp', 'status': 'APPROVED', 'language': 'en'}]},
])
def test_a_template_meta_has_not_approved_blocks_the_send(outbound, templates):
    """Only APPROVED counts. PENDING, REJECTED, PAUSED and DISABLED are names that EXIST and
    cannot be sent, and treating "the name came back" as "the template works" is the same class
    of error as treating a local constant as provider state."""
    reads = _Reads(templates=templates)
    refusal, _ = _gate(outbound, _payment_body(), reads=reads)

    assert refusal is not None
    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == 'WA_PAY_NOT_READY'


def test_an_empty_template_name_on_a_payment_request_blocks(outbound):
    refusal, _ = _gate(outbound, _payment_body(templateName=''))
    assert refusal['statusCode'] == 409
    assert _error(refusal)['error'] == 'WA_PAY_NOT_READY'


def test_the_template_checked_is_the_template_the_send_will_use(outbound):
    """Not a constant. A gate that checks a different string from the one the send uses can pass
    while the send fails."""
    reads = _Reads(templates={'data': [{'name': 'some_other_template', 'status': 'APPROVED'}]})
    refusal, _ = _gate(outbound, _payment_body(templateName='some_other_template'), reads=reads)
    assert refusal is None


def test_the_template_readback_is_waba_scoped(outbound):
    """Why the `catalogServiceReadiness` action is NOT used for this: it takes no `wabaId` and
    reads three hardcoded template ids, so it would prove one WABA's templates for a request
    from another — over-permissive, on a money path, and it would have hidden HIGH-2."""
    _, reads = _gate(outbound, _payment_body())
    assert reads.template_calls == 1
    assert set(reads.waba_ids) == {WABA1_ID}


def test_the_template_read_does_not_use_the_auto_generated_route(outbound):
    """`/direct-send/templates` filters `source=AUTO_GENERATED`, and `wecarepay_wa` is manually
    created and manually approved — so reading it there would block EVERY payment send on
    PAYMENT_TEMPLATE_MISSING. The gate uses an unfiltered WABA-scoped arm instead."""
    import inspect
    source = inspect.getsource(outbound._fetch_approved_templates)
    assert '/wa-business/payment-templates/list' in source
    assert 'direct-send' not in source.split('"""')[2] if '"""' in source else True


def test_the_business_api_serves_the_unfiltered_payment_template_route():
    """The route the gate depends on EXISTS, and it is unfiltered. Source-level, because the arm
    is a dispatch branch rather than a function: an assumed mechanism is how A3.1 would have
    shipped blocking every payment."""
    import pathlib
    source = (pathlib.Path(REPO) / 'amplify' / 'functions' / 'messaging'
              / 'whatsapp-business-api' / 'handler.py').read_text(encoding='utf-8')
    assert "'/payment-templates/list' in path" in source
    arm = source[source.index("'/payment-templates/list' in path"):][:2600]
    # COMMENTS STRIPPED, for the reason this file states elsewhere: the comment explaining why
    # the auto-generated filter is wrong necessarily names it, so an unstripped search flags its
    # own explanation.
    code = '\n'.join(line for line in arm.splitlines()
                     if not line.strip().startswith('#'))
    assert 'message_templates' in code
    assert 'wabaId' in code
    # Unfiltered: narrowed FIELDS are fine, a `source` filter is not.
    assert "'source'" not in code
    assert 'AUTO_GENERATED' not in code
    # "Could not read" must not read the same as "nothing is approved".
    assert '502' in code


# ══════════════════════════════════════════════════════════════════════════════
# an unconfigured deployment refuses, and no literal can make it ready
# ══════════════════════════════════════════════════════════════════════════════

class TestAnUnconfiguredDeploymentRefuses:

    def test_both_expectations_default_to_empty(self):
        module = _import_outbound()
        assert module.EXPECTED_CONFIGURATION_NAME == ''
        assert module.EXPECTED_PROVIDER_MID == ''

    def test_an_unset_configuration_name_refuses(self):
        module = _import_outbound(EXPECTED_PROVIDER_MID=TEST_MID)
        module.origin = 'http://localhost:3000'
        refusal, reads = _gate(module, _payment_body())
        assert refusal['statusCode'] == 409
        assert _error(refusal)['error'] == 'WA_PAY_CONFIG_NOT_PROVABLE'
        assert reads.fetches == 0

    def test_an_unset_provider_mid_refuses(self):
        module = _import_outbound(EXPECTED_CONFIGURATION_NAME=TEST_CONFIG)
        module.origin = 'http://localhost:3000'
        refusal, _ = _gate(module, _payment_body())
        assert refusal['statusCode'] == 409
        assert _error(refusal)['error'] == 'WA_PAY_NOT_READY'

    def test_neither_hardcoded_literal_survives_as_an_env_default(self):
        """AST, and scoped to `os.environ.get` DEFAULTS, because the comments explaining this rule
        necessarily contain both values — a textual search flags its own explanation."""
        import ast
        import pathlib
        source = (pathlib.Path(REPO) / 'amplify' / 'functions' / 'messaging'
                  / 'outbound-whatsapp' / 'handler.py').read_text(encoding='utf-8')
        defaults = set()
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get'
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == 'environ'
                    and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)):
                defaults.add(node.args[1].value)
        assert 'WECAREDIGITAL' not in defaults
        assert 'acc_TTFSyolquKEZEy' not in defaults

    def test_no_env_var_introduced_here_can_force_enable_a_payment(self, outbound):
        """The asymmetry is the whole point of the kill switch. The gate reads exactly two new
        variables, both EXPECTATIONS compared against a live readback: setting them wrongly
        produces a refusal, and the only route to PAYMENT_READY is a successful live read."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(outbound._refuse_unless_payment_ready).lstrip())
        env_reads = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Attribute) and n.attr == 'environ']
        assert env_reads == [], (
            'the gate must not read the environment directly; expectations are module constants '
            'and the kill switch has one reader')


# ══════════════════════════════════════════════════════════════════════════════
# the gate never raises, and that is enforced rather than argued
# ══════════════════════════════════════════════════════════════════════════════

def test_a_gate_that_cannot_answer_refuses(outbound):
    """The call site wraps the gate, so an unexpected escape is a 503 refusal rather than a
    Lambda 500 — fail-closed either way, but a named refusal is readable."""
    import inspect
    source = inspect.getsource(outbound.handler)
    gate = source[source.index('_refuse_unless_payment_ready'):][:900]
    assert 'except Exception' in gate
    assert 'wa_payment_gate_error' in gate
    assert 'WA_PAY_NOT_READY' in gate


def test_the_gate_runs_before_every_write_and_every_send(outbound):
    """POSITION is what makes "a refusal writes nothing and sends nothing" true. The sender read
    is hoisted above the gate so the gate and the send read ONE expression, not two copies of the
    same default."""
    import inspect
    source = inspect.getsource(outbound.handler)
    assert (source.index('require_auth')
            < source.index("phone_number_id = body.get('phoneNumberId'")
            < source.index('_refuse_unless_payment_ready')
            < source.index("body.get('contactId')"))
    # And there is exactly ONE read of the sender in the handler.
    assert source.count("body.get('phoneNumberId'") == 1


def test_the_resolver_refuses_caller_supplied_payment_settings(outbound):
    """A3.8. The checkout-template branch used to PREFER a caller's `payment_settings` block and
    only build them when absent, which made the resolver's three refusals optional for any caller
    that supplied its own. No caller supplies them; this closes the door so a future one cannot.

    It raises the EXISTING exception, so every caller is fail-closed on day one.
    """
    import inspect
    source = inspect.getsource(outbound._handle_checkout_template_send)
    branch = source[source.index("get('payment_settings')"):][:600]
    assert 'PaymentConfigurationUnresolved' in branch
    assert 'resolver owns Mode 3' in branch
    # And the build is unconditional afterwards.
    assert source.index("get('payment_settings')") < source.index('_build_payment_settings(')
