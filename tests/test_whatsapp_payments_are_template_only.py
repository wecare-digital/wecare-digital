"""A WhatsApp payment travels in the approved template, or it does not travel.

`_build_payment_settings` supports three modes and evaluates them in order. Modes 1 and 2 -
Enhanced Payment Links and UPI Intent - both `return` BEFORE the PG deep-integration mode, so a
caller setting either key bypasses `configuration_name` entirely, and with it the payment
configuration, the readiness verdict and the approved template. A link path collects money
outside the configuration whose merchant id we verify, which is the whole point of verifying it.

Measured, NOTHING in this repository sets either key - so this is a pure tightening with zero
behavioural change today, which is the best possible time to add it: before a producer exists.

The two refusals here are tested as a PAIR with two separate properties:

  * the resolver refuses a link key (so the send is clean), and
  * no module in the tree PRODUCES a link key (so nothing upstream could dirty it).

A single test of either kind leaves the other direction open.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from lambda_utils.ecommerce import wa_payment_request as wpr  # noqa: E402

OUTBOUND_DIR = os.path.join(REPO, 'amplify', 'functions', 'messaging', 'outbound-whatsapp')
FUNCTIONS = pathlib.Path(REPO) / 'amplify' / 'functions'

WABA1 = wpr.PHONE_NUMBER_ID_1
WABA2 = 'phone-number-id-waba-t-direct-1055232054343117'


@pytest.fixture
def outbound():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, OUTBOUND_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return importlib.import_module('handler')


# ══════════════════════════════════════════════════════════════════════════════
# the resolver refuses a link, on the sender that may take payments
# ══════════════════════════════════════════════════════════════════════════════

def test_the_happy_path_resolves_a_razorpay_configuration(outbound):
    """T-P1. Mode 3, which is the only mode a WhatsApp payment may take."""
    settings = outbound._build_payment_settings(
        WABA1, {'reference_id': 'WD-PAY-TPLONLY1', 'payment_configuration': 'WECAREDIGITAL'})
    assert settings[0]['type'] == 'payment_gateway'
    assert settings[0]['payment_gateway']['type'] == 'razorpay'
    assert settings[0]['payment_gateway']['configuration_name'] == 'WECAREDIGITAL'


def test_payment_link_uri_is_refused_by_the_resolver(outbound):
    """T-P3. It does NOT return a `payment_link` setting - it refuses."""
    with pytest.raises(outbound.PaymentConfigurationUnresolved) as refused:
        outbound._build_payment_settings(
            WABA1, {'reference_id': 'WD-PAY-TPLONLY1',
                    'payment_link_uri': 'https://rzp.io/i/abc'})
    assert 'payment_link_uri' in str(refused.value)


def test_upi_intent_link_is_refused_by_the_resolver(outbound):
    """T-P4, and the half whose reasoning has to be stated.

    Refusing the UPI *mode* is not refusing UPI. `WECAREUPI` stays reachable exactly as it
    should be - as a `configuration_name` through Mode 3, where Meta owns the UPI collection
    inside the `order_details` template. Mode 2 is a different mechanism: a RAW UPI deep link
    that bypasses `configuration_name`, and therefore bypasses the merchant-id verification that
    proves the money lands in our Razorpay account.
    """
    with pytest.raises(outbound.PaymentConfigurationUnresolved):
        outbound._build_payment_settings(
            WABA1, {'reference_id': 'WD-PAY-TPLONLY1',
                    'upi_intent_link': 'upi://pay?pa=someone@bank'})

    # WECAREUPI through the configuration name is still fine.
    settings = outbound._build_payment_settings(
        WABA1, {'reference_id': 'WD-PAY-TPLONLY1', 'payment_configuration': 'WECAREUPI'})
    assert settings[0]['payment_gateway']['configuration_name'] == 'WECAREUPI'


def test_the_refusal_precedes_both_link_branches(outbound):
    """T-P5. AST ordering, so the placement cannot regress.

    The ordering IS the control: both link modes `return` before Mode 3, so a refusal placed
    after them would never run.
    """
    source = inspect.getsource(outbound._build_payment_settings)
    tree = ast.parse(source.lstrip())
    func = tree.body[0]

    def line_of_first(predicate):
        for node in ast.walk(func):
            if predicate(node):
                return node.lineno
        return None

    guard_line = line_of_first(
        lambda n: isinstance(n, ast.Constant) and n.value == 'payment_link_uri')
    link_read_line = line_of_first(
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == 'get'
        and n.args and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == 'payment_link_uri')
    assert guard_line is not None and link_read_line is not None
    assert guard_line < link_read_line, (
        'the template-only refusal must precede the Mode 1 link read, or it never runs')


# ══════════════════════════════════════════════════════════════════════════════
# WABA1 only, through every door
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('override', [None, 'WECAREDIGITAL', 'WECAREUPI'])
def test_build_payment_settings_refuses_waba2_through_every_door(outbound, override):
    """T-S5, and the hole a map edit alone would not have closed.

    `explicit_config` is read BEFORE `config_name` is computed, and both WABAs expose the
    IDENTICAL pair WECAREDIGITAL/WECAREUPI - so a caller naming one would resolve for either
    sender. Removing WABA2 from `PHONE_PAYMENT_GATEWAYS` is agreement; the guard AHEAD of the
    override is the control.
    """
    details = {'reference_id': 'WD-PAY-TPLONLY1'}
    if override:
        details['payment_configuration'] = override
    with pytest.raises(outbound.PaymentConfigurationUnresolved) as refused:
        outbound._build_payment_settings(WABA2, details)
    assert 'may not take payments' in str(refused.value)


def test_the_waba2_entry_is_gone_from_the_gateway_map(outbound):
    """The map and the guard must agree, or the next reader concludes WABA2 is permitted."""
    assert WABA2 not in outbound.PHONE_PAYMENT_GATEWAYS
    assert WABA1 in outbound.PHONE_PAYMENT_GATEWAYS


def test_the_two_sender_allow_sets_are_equal(outbound):
    """N-2. The set is defined in two modules by design - the resolver must not import from
    `ecommerce` - so a test pins them equal rather than letting them drift."""
    assert outbound.PAYMENT_SENDERS == wpr.PAYMENT_SENDERS


def test_the_sender_guard_precedes_the_explicit_override(outbound):
    """The same ordering discipline as the link refusal. An explicit `payment_configuration` is a
    CHOICE OF CONFIGURATION, not a grant of permission."""
    source = inspect.getsource(outbound._build_payment_settings)
    assert source.index('PAYMENT_SENDERS') < source.index("get('payment_link_uri'")


# ══════════════════════════════════════════════════════════════════════════════
# nothing upstream can dirty the payload
# ══════════════════════════════════════════════════════════════════════════════

_LINK_KEYS = ('payment_link_uri', 'upi_intent_link')


def test_no_module_in_the_tree_produces_a_link_key():
    """T-P6, the mirror of the resolver refusal.

    Pins the measured "no producer exists", so the hole cannot be reopened from the other end.
    An ASSIGNMENT or a dict literal naming either key is a producer; a `.get()` read is not.
    """
    producers = []
    for path in FUNCTIONS.rglob('*.py'):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:  # pragma: no cover - a file we do not own
            continue

        # `_build_payment_settings` is EXCLUDED, and that is not a loophole. It is the one
        # function that legitimately names these keys: it reads them in order to refuse them,
        # and the response shape of its own (now unreachable) Mode 2 arm happens to reuse the
        # name. Scoping the scan to everything else is what keeps "no producer exists" a claim
        # about CALLERS, which is where a producer would actually appear.
        excluded = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == '_build_payment_settings'):
                excluded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))

        for node in ast.walk(tree):
            if getattr(node, 'lineno', -1) in excluded:
                continue
            # `{'payment_link_uri': ...}`
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value in _LINK_KEYS:
                        producers.append(f'{path.relative_to(FUNCTIONS)}:{node.lineno}')
            # `details['payment_link_uri'] = ...`
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and target.slice.value in _LINK_KEYS):
                        producers.append(f'{path.relative_to(FUNCTIONS)}:{node.lineno}')
    assert not producers, (
        'a producer of a WhatsApp payment LINK key appeared: ' + ', '.join(producers)
        + '. Payments must travel in the approved order_details template.')


def test_the_reservation_module_refuses_a_link_before_any_write():
    """The caller-side half. `build_request` runs before any write and before any invoke, so a
    link-shaped request leaves no partial state behind."""
    base = dict(invoice_id='inv-1', customer_id='c-1', phone_e164='+918100640044',
                phone_number_id=WABA1, amount_paise=59900,
                configuration_name='WECAREDIGITAL', provider_mid='acc_TEST',
                item_name='Service Fee', now=1770000000)
    for key in _LINK_KEYS:
        with pytest.raises(wpr.PaymentRequestRefused) as refused:
            wpr.build_request(**base, order_details={key: 'x'})
        assert refused.value.code == wpr.WA_PAY_LINK_NOT_PERMITTED


def _string_constants(source, within=None):
    """Every string LITERAL in the source, by AST.

    AST and not a text search, for the reason the vocabulary gate states outright: the comments
    explaining this rule necessarily contain the template name, so a textual search flags its own
    explanation.
    """
    tree = ast.parse(source)
    if within:
        tree = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == within)
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


#: Every file that composes a WhatsApp payment send. Measured by grepping `amplify/` for
#: `isCheckoutTemplate`, `checkoutOrderDetails`, `isPaymentTemplate`, `isInteractivePayment`,
#: `order_details` and `review_and_pay`, then reading each hit.
PAYMENT_SENDER_FILES = [
    FUNCTIONS / 'payments' / 'invoice-engine' / 'handler.py',
    FUNCTIONS / 'core' / 'secure-files' / 'whatsapp_delivery.py',
    FUNCTIONS / 'ecommerce' / 'checkout' / 'handler.py',
]


def test_the_template_name_is_not_duplicated_a_fourth_time():
    """T-P8. The approved name belongs to the SENDERS. A gate that checks a different string
    from the one the send uses can pass while the send fails, so there is one home per sender and
    no literal anywhere else.

    EXTENDED to the three senders. The previous version inspected only `wa_payment_request` and
    `_build_payment_settings`, which was true but vacuous: neither has ever carried the name, and
    nothing guarded the count in the files that actually send. `checkout/handler.py` carries it
    exactly once, inside `_send_order_details`, which is now the one in-chat sender in that file.
    """
    assert 'wecarepay_wa' not in _string_constants(inspect.getsource(wpr))

    outbound_source = (FUNCTIONS / 'messaging' / 'outbound-whatsapp' / 'handler.py').read_text(
        encoding='utf-8')
    assert 'wecarepay_wa' not in _string_constants(
        outbound_source, within='_build_payment_settings')

    for path in PAYMENT_SENDER_FILES:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        occurrences = [node for node in ast.walk(tree)
                       if isinstance(node, ast.Constant) and node.value == 'wecarepay_wa']
        assert len(occurrences) <= 1, (
            f'{path.relative_to(FUNCTIONS)} carries the approved template name '
            f'{len(occurrences)} times; one home per sender')


def test_every_whatsapp_payment_sender_composes_the_order_details_template():
    """T-P7. Parametrised over the measured senders, by source inspection: each one sets
    `isCheckoutTemplate` and `checkoutOrderDetails`.

    `ecommerce/checkout/handler.py` joins the list because its in-chat sender was repaired onto
    that envelope. Before the repair it POSTed `/wa-business/messages/send/interactive-payment`
    at the business-API Lambda, whose send dispatcher 404s on that path — so it could never have
    sent anything, and the 404 surfaced as a 502 `SEND_FAILED` that looked like a Meta problem.
    """
    for path in PAYMENT_SENDER_FILES:
        source = path.read_text(encoding='utf-8')
        assert 'isCheckoutTemplate' in source, path
        assert 'checkoutOrderDetails' in source, path


def test_no_sender_supplies_its_own_payment_settings():
    """The resolver owns Mode 3. A caller-supplied `payment_settings` block would bypass the
    WABA1-only refusal, the raw-link refusals and the `VALID_PAYMENT_CONFIGS` membership check —
    which is exactly what `catalog_service_checkout.payment_details` used to do."""
    producers = []
    for path in PAYMENT_SENDER_FILES + [FUNCTIONS / 'shared' / 'lambda_utils' / 'ecommerce'
                                        / 'catalog_service_checkout.py']:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == 'payment_settings':
                        producers.append(f'{path.relative_to(FUNCTIONS)}:{node.lineno}')
    assert not producers, (
        'a sender composed its own payment_settings: ' + ', '.join(producers))


def test_no_payment_is_composed_in_a_browser():
    """The regression guard for the two staff surfaces, and the reason a ninth browser composer
    cannot appear quietly.

    A client-minted `reference_id` has no `PAYREF#` row, so a capture against it resolves to
    nothing and quarantines as PAID_BUT_NO_ORDER — the exact failure `wa_payment_request` exists
    to prevent. A client-side fallback configuration name is what requirements statement 9 forbids
    in as many words. Both are now impossible to reintroduce without failing here.
    """
    import pathlib
    keys = ('checkoutOrderDetails', 'isCheckoutTemplate', 'isPaymentTemplate',
            'isInteractivePayment')
    offenders = []
    src = pathlib.Path(REPO) / 'src'
    for path in src.rglob('*'):
        if path.suffix not in ('.ts', '.tsx') or not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding='utf-8',
                                                     errors='ignore').splitlines(), start=1):
            stripped = line.strip()
            # A comment recording WHY the composer was removed is not a composer.
            if stripped.startswith(('//', '*', '/*')):
                continue
            for key in keys:
                if key in line:
                    offenders.append(f'{path.relative_to(src)}:{lineno} ({key})')
    assert not offenders, (
        'a WhatsApp payment composer appeared under src/: ' + ', '.join(offenders)
        + '. Payment identity is reserved server-side; a browser must raise an invoice instead.')


def test_the_two_payment_gates_expect_the_same_configuration_and_mid():
    """One logical expectation, two key names, pinned equal.

    The drift mode is specific and bad: the invoice engine would prove and reserve against X,
    send `payment_configuration: X`, and the boundary gate would then refuse because its own
    expectation is Y — a guaranteed reserve-then-refuse on every invoice collection, surfacing as
    an outbound error with the reservation already written.

    `wecare-checkout` is DELIBERATELY excluded: it holds the same keys but declares them empty
    while the native service leg is gated off, so including it would pin an empty expectation
    onto the two live gates.
    """
    import json as _json
    import pathlib
    manifest = _json.loads((pathlib.Path(REPO) / 'config' / 'lambda-env-manifest.json')
                           .read_text(encoding='utf-8'))['functions']
    invoice = manifest['wecare-invoice-engine']
    outbound_env = manifest['wecare-outbound-whatsapp']
    assert invoice['WA_PAY_CONFIG_NAME'] == outbound_env['EXPECTED_CONFIGURATION_NAME']
    assert invoice['EXPECTED_PROVIDER_MID'] == outbound_env['EXPECTED_PROVIDER_MID']
    assert manifest['wecare-checkout']['EXPECTED_CONFIGURATION_NAME'] == ''
    assert manifest['wecare-checkout']['EXPECTED_PROVIDER_MID'] == ''


def test_the_two_free_form_payment_composers_are_gone():
    """A3.2 and A3.3 step 1, by AST so a comment naming either does not pass the test.

    `whatsapp-business-api._send_payment_direct_fallback` fired exactly when the invoice-engine
    invoke RAISED — which, now that the invoice path is readiness-gated, is when a refusal is the
    legitimate answer. It was the one path that could have taken money while every gate said no:
    free-form interactive, float GST, no reservation, no interlock, no readiness.

    `inbound-whatsapp-handler._send_payment_request` had zero callers and the same defects.
    """
    gone = {
        FUNCTIONS / 'messaging' / 'whatsapp-business-api' / 'handler.py':
            '_send_payment_direct_fallback',
        FUNCTIONS / 'messaging' / 'inbound-whatsapp-handler' / 'handler.py':
            '_send_payment_request',
    }
    for path, name in gone.items():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert name not in defined, f'{name} is still defined in {path.name}'
        assert name not in called, f'{name} is still called in {path.name}'


def test_a_payment_send_is_only_logged_as_sent_on_a_2xx():
    """A readiness refusal recorded as a successful send is the worst available log line on a
    money path — and after the gates, a refusal is an expected outcome rather than an anomaly."""
    for path, sent_event in (
            (FUNCTIONS / 'messaging' / 'whatsapp-business-api' / 'handler.py',
             'flow_payment_link_sent'),
            (FUNCTIONS / 'messaging' / 'whatsapp-business-api' / 'flows' / 'common.py',
             'payment_link_sent')):
        source = path.read_text(encoding='utf-8')
        # The EMITTED key, not any mention: the comment recording the old unconditional log
        # necessarily names the event.
        emitted = f"'event': '{sent_event}'"
        assert emitted in source
        window = source[max(0, source.index(emitted) - 600):source.index(emitted)]
        assert '200 <= send_status < 300' in window, (
            f'{sent_event} in {path.name} must be conditional on a 2xx')
        assert f"'event': '{sent_event.replace('_sent', '_refused')}'" in source, (
            f'{path.name} must log a refusal line too, carrying the status and the code')


def test_the_secure_files_sends_carry_a_sender_the_resolver_accepts():
    """A3.5. Every WhatsApp send from secure-files was structurally broken: all three passed the
    BARE Meta phone id as `phoneNumberId`, which `_resolve_meta_phone_id` refuses outright rather
    than falling back to another WABA, and `PAYMENT_SENDERS` refused the payment one again.

    This makes the surface CORRECT, not ENABLED: `SECURE_FILES_PAYMENT_ENABLED` stays "false".
    """
    import json as _json
    import pathlib
    path = FUNCTIONS / 'core' / 'secure-files' / 'whatsapp_delivery.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    senders = [node.value.id for node in ast.walk(tree)
               if isinstance(node, ast.Dict)
               for key, node.value in zip(node.keys, node.values)
               if isinstance(key, ast.Constant) and key.value == 'phoneNumberId'
               and isinstance(node.value, ast.Name)]
    assert senders and set(senders) == {'WA_SEND_PHONE_ID'}

    namespace = {}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.Assign)],
                            type_ignores=[]), str(path), 'exec'),
         {'os': os}, namespace)
    assert namespace['WA_SEND_PHONE_ID'] in wpr.PAYMENT_SENDERS
    assert namespace['META_PHONE_NUMBER_ID'] not in wpr.PAYMENT_SENDERS

    manifest = _json.loads((pathlib.Path(REPO) / 'config' / 'lambda-env-manifest.json')
                           .read_text(encoding='utf-8'))['functions']['wecare-secure-files']
    assert manifest['WA_SEND_PHONE_ID'] == namespace['WA_SEND_PHONE_ID']
    # The capability stays OFF. This item makes it correct, not live.
    assert manifest['SECURE_FILES_PAYMENT_ENABLED'] == 'false'


def test_the_two_waba_derivations_cannot_drift(outbound):
    """The gate derives the WABA from `_waba_for_sender`; the invoice engine derives it from
    `PHONE_ID_TO_WABA`. Two derivations of one fact, pinned equal."""
    assert outbound._waba_for_sender(WABA1) == wpr.PHONE_ID_TO_WABA[WABA1]


# ══════════════════════════════════════════════════════════════════════════════
# the native catalog leg composes through the resolver, and the NAME still travels
# ══════════════════════════════════════════════════════════════════════════════

class _Quote:
    collection_before_convenience_paise = 59900
    convenience_fee_paise = 1498
    convenience_gst_paise = 270
    total_payable_paise = 59900 + 1498 + 270


_SESSION = {'kind': 'SUBMIT_REQUEST', 'productId': 'prod-1', 'variantId': 'var-1'}


def _payment_details(configuration='WECAREDIGITAL', reference='WD-PAY-CATALOG1'):
    from lambda_utils.ecommerce.catalog_service_checkout import payment_details
    return payment_details(dict(_SESSION), _Quote(), reference, configuration, 1770000000)


def test_payment_details_leaves_mode_3_to_the_resolver_and_still_carries_the_name():
    """The inline `payment_settings` block this function used to build was the ONLY use of its
    `configuration` argument. Removing the block alone would have made that argument dead, the
    resolver would have fallen back to the sender's phone map, and the system could have proven
    one configuration against Meta while telling Meta to use another — with no refusal anywhere.
    """
    details = _payment_details()
    assert 'payment_settings' not in details
    assert details['payment_configuration'] == 'WECAREDIGITAL'
    assert 'payment_link_uri' not in details and 'upi_intent_link' not in details


def test_the_configuration_the_caller_names_is_the_configuration_the_payload_sends(outbound):
    """Asserted as an IDENTITY against a non-default name, deliberately.

    Asserting `'WECAREDIGITAL'` would pass by accident of `PHONE_PAYMENT_GATEWAYS` and would not
    catch the divergence this change exists to prevent.
    """
    details = _payment_details(configuration='WECAREUPI')
    settings = outbound._build_payment_settings(WABA1, details)
    assert settings[0]['payment_gateway']['configuration_name'] == 'WECAREUPI'


def test_the_composed_order_adds_up_to_the_total_it_charges():
    """Arithmetic identity, against the keys `payment_details` actually emits — `status`, `items`,
    `subtotal`, `tax`, `expiration`, with no `shipping` and no `discount`. The absent terms are
    explicitly zero so the assertion neither raises `KeyError` nor silently degenerates.

    The quote is authoritative; a disagreement here is a build bug, not a retryable Meta
    rejection.
    """
    details = _payment_details()
    order = details['order']
    assert details['total_amount']['value'] == (
        order['subtotal']['value'] + order['tax']['value']
        + order.get('shipping', {}).get('value', 0)
        - order.get('discount', {}).get('value', 0))
    assert details['total_amount']['value'] == _Quote.total_payable_paise
    assert set(order) == {'status', 'items', 'subtotal', 'tax', 'expiration'}
    # Every figure an integer number of paise; no float anywhere.
    for value in (details['total_amount']['value'], order['subtotal']['value'],
                  order['tax']['value']):
        assert isinstance(value, int) and not isinstance(value, bool)


def test_the_razorpay_receipt_slice_never_truncates_a_real_reference(outbound):
    """`ref_id[:40]` is in the resolver. Reference ids are well under 40 characters — the Meta
    contract caps them and `payment_details` additionally enforces `[A-Za-z0-9._-]{1,35}` — so
    the slice never fires. Pinned rather than assumed."""
    from lambda_utils.ecommerce import order_keys
    reference = order_keys.mint_payment_reference()
    details = _payment_details(reference=reference)
    settings = outbound._build_payment_settings(WABA1, details)
    assert settings[0]['payment_gateway']['razorpay']['receipt'] == reference
    assert len(reference) <= 40


def test_payment_details_still_refuses_an_unusable_reference_or_an_empty_configuration():
    for reference, configuration in (('', 'WECAREDIGITAL'),
                                     ('not a reference!!', 'WECAREDIGITAL'),
                                     ('WD-PAY-CATALOG1', '')):
        with pytest.raises(ValueError):
            _payment_details(configuration=configuration, reference=reference)
