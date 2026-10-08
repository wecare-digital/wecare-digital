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


def test_the_template_name_is_not_duplicated_a_fourth_time():
    """T-P8. The approved name belongs to the SENDERS. A gate that checks a different string
    from the one the send uses can pass while the send fails, so there is one home per sender and
    no literal anywhere else."""
    def string_constants(source, within=None):
        """Every string LITERAL in the source, by AST.

        AST and not a text search, for the reason the vocabulary gate states outright: the
        comments explaining this rule necessarily contain the template name, so a textual search
        flags its own explanation.
        """
        tree = ast.parse(source)
        if within:
            tree = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == within)
        return {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}

    assert 'wecarepay_wa' not in string_constants(inspect.getsource(wpr))

    outbound_source = (FUNCTIONS / 'messaging' / 'outbound-whatsapp' / 'handler.py').read_text(
        encoding='utf-8')
    assert 'wecarepay_wa' not in string_constants(
        outbound_source, within='_build_payment_settings')


def test_every_whatsapp_payment_sender_composes_the_order_details_template():
    """T-P7. Parametrised over the measured senders, by source inspection: each one sets
    `isCheckoutTemplate` and `checkoutOrderDetails`."""
    senders = [
        FUNCTIONS / 'payments' / 'invoice-engine' / 'handler.py',
        FUNCTIONS / 'core' / 'secure-files' / 'whatsapp_delivery.py',
    ]
    for path in senders:
        source = path.read_text(encoding='utf-8')
        assert 'isCheckoutTemplate' in source, path
        assert 'checkoutOrderDetails' in source, path
