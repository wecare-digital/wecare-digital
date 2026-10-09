"""The payment join key is never shortened, on either side of the wire.

Why this file exists
--------------------
`_sanitize_reference_id` existed twice, once in `outbound-whatsapp` and once in
`inbound-whatsapp-handler`, and the outbound copy ended with:

    if len(result) > 35:
        result = result[:35]

That is the most dangerous line that can appear on a payment path. `reference_id` is the join
key tying a WhatsApp payment to an order, so truncation maps two distinct identifiers onto one
string and two orders reconcile against a single payment - the one failure this domain cannot
undo after the fact.

It was reachable, not theoretical. The legacy WD order number is 46 characters, so feeding one
in produced exactly 35 characters - safe only by arithmetic accident, because the embedded date
and time are fixed width. Any other over-long input collided silently.

The outbound copy now raises. The inbound copy is the read side and must not raise (a webhook
that 500s is retried forever), so it returns the value unshortened and logs, which makes the
lookup miss rather than match the wrong order.
"""

import importlib
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SHARED = os.path.join(REPO, 'amplify', 'functions', 'shared')
OUTBOUND = os.path.join(REPO, 'amplify', 'functions', 'messaging', 'outbound-whatsapp')
INBOUND = os.path.join(REPO, 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler')

sys.path.insert(0, SHARED)

from lambda_utils.ecommerce import order_keys  # noqa: E402

LIMIT = order_keys.META_REFERENCE_ID_MAX_LENGTH


def _load(directory):
    """Import the handler at `directory` in isolation, per the suite's convention."""
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, directory)
    try:
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                return importlib.import_module('handler')
    finally:
        pass


@pytest.fixture
def outbound():
    return _load(OUTBOUND)


@pytest.fixture
def inbound():
    return _load(INBOUND)


# ── the source-level guarantee ─────────────────────────────────────────────────

@pytest.mark.parametrize('path', [
    os.path.join(OUTBOUND, 'handler.py'),
    os.path.join(INBOUND, 'handler.py'),
])
def test_no_handler_slices_a_value_to_the_reference_limit(path):
    """A structural assertion, because the behavioural tests below can only cover the inputs
    someone thought of. This catches the line shape itself coming back.

    Parsed with `ast` rather than grepped: the fix is *documented* in a docstring that quotes
    the removed `result[:35]`, and a text search cannot tell the difference between a slice and
    a description of one. An AST walk sees only real code.
    """
    import ast
    with open(path, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
            continue
        upper = node.slice.upper
        if isinstance(upper, ast.Constant) and upper.value == LIMIT:
            offenders.append(node.lineno)

    assert not offenders, (
        f'{os.path.basename(os.path.dirname(path))} slices a value to {LIMIT} characters at '
        f'line(s) {offenders}; a reference_id must be rejected, never truncated'
    )


# ── outbound: the send path rejects ────────────────────────────────────────────

def test_outbound_rejects_an_over_length_reference(outbound):
    over = 'WD-PAY-' + 'A' * 40
    assert len(over) > LIMIT
    with pytest.raises(outbound.ReferenceIdTooLong):
        outbound._sanitize_reference_id(over)


def test_outbound_refuses_to_turn_an_order_number_into_a_reference(outbound):
    """R2.9, and the reason it is a *refusal* rather than a conversion.

    Stripping the legacy number's spaces, dashes and colons produced
    `WD-PAY-ORD<8hex><8date><6time>IST` at exactly 35 characters - inside the limit purely
    because the date and time are fixed width. So the old code looked safe on this input and
    would have truncated silently on a format one character longer.

    All THREE spellings are refused. The spaced legacy value is a literal because the
    generator no longer emits it (FEAT-005); the current form is the one that matters most,
    because at 15 characters of permitted charset it is Meta-valid as a string - nothing about
    its length would have stopped it being sent as a payment reference.
    """
    spaced = 'WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST'
    assert len(spaced) > LIMIT

    from lambda_utils.ecommerce.wix_domain import _generate_wd_order_number
    current = _generate_wd_order_number('2026-02-22T18:00:00Z')
    assert len(current) <= LIMIT

    for number in (spaced, 'WD-ORD-A1B2C3D4', current, 'WD-ORD-K4M7PQR9'):
        with pytest.raises(outbound.ReferenceIdTooLong):
            outbound._sanitize_reference_id(number)


def test_outbound_never_returns_a_value_over_the_limit(outbound):
    """Whatever it returns, Meta must accept. Anything else fails before the send."""
    candidates = [
        'WD-PAY-ABC12345',
        'WD_41BA3534',
        'WDABC12345',
        'WD-PAY-WD-PAY-ABC',
        '',
        '   ',
        'WD+41BA3534',
        'x' * 20,
    ]
    for value in candidates:
        try:
            result = outbound._sanitize_reference_id(value)
        except outbound.ReferenceIdTooLong:
            continue
        assert len(result) <= LIMIT, f'{value!r} produced {len(result)} characters'
        assert order_keys.is_valid_meta_reference_id(result), \
            f'{value!r} produced {result!r}, which Meta would reject'


def test_outbound_mints_from_secrets_when_given_nothing(outbound):
    first = outbound._sanitize_reference_id('')
    second = outbound._sanitize_reference_id('   ')
    assert first != second
    assert all(order_keys.is_valid_meta_reference_id(v) for v in (first, second))


def test_outbound_preserves_an_already_valid_reference(outbound):
    minted = order_keys.mint_payment_reference()
    assert outbound._sanitize_reference_id(minted) == minted


# ── §35/§36: the reserved reference reaches Meta byte-for-byte ─────────────────

@pytest.mark.parametrize('canonical', [
    'WD-PAY-0123456789ABCD',
    'WD-PAY-abcdefghijklmn',          # lower case
    'WD-PAY-MiXeDcAsE1234',           # mixed case
    'WD-PAY-with.dots_and-dashes',    # every permitted punctuation
    'A',                              # minimal
    'A' * 35,                         # maximal
])
def test_a_canonical_reference_is_never_transformed(outbound, canonical):
    """§35. Once reserved under PAYREF# the value is a stored fact, not a candidate to tidy.

    Case is the one that matters: Meta's reference_id is case SENSITIVE, and the old code
    upper-cased every value before its pass-through checks ran. That is a no-op for our current
    all-uppercase alphabet, which is exactly why it survived — an invisible correctness bug that
    would start breaking joins the moment the alphabet changed.
    """
    assert outbound._sanitize_reference_id(canonical) == canonical


def test_a_minted_reference_survives_the_payload_builder_unchanged(outbound):
    """§36. The assertion that matters: what the payment-send function puts on the wire is the
    exact value stored on the PaymentAttempt."""
    stored = order_keys.mint_payment_reference()
    order = {
        'reference_id': stored,
        'type': 'digital-goods',
        'currency': 'INR',
        'order': {
            'items': [{'name': 'Service', 'amount': {'value': 4900}, 'quantity': 1}],
            'subtotal': {'value': 4900}, 'discount': {'value': 0},
            'shipping': {'value': 0}, 'tax': {'value': 0},
        },
    }
    payload = outbound._build_message_payload(
        '+919330994400', '', None, None, False, None, [],
        is_interactive_payment=True, order_details=order,
        phone_number_id='phone-number-id-waba1-direct-1016149501586345',
    )
    parameters = payload['interactive']['action']['parameters']
    assert parameters['reference_id'] == stored

    # And the same value reaches Razorpay, since that is the other half of the join.
    razorpay = parameters['payment_settings'][0]['payment_gateway']['razorpay']
    assert razorpay['receipt'] == stored
    assert razorpay['notes']['referenceId'] == stored


def test_a_mixed_case_reference_survives_the_payload_builder(outbound):
    """The regression the pass-through ordering exists to prevent."""
    stored = 'WD-PAY-MiXeDcAsE1234'
    order = {
        'reference_id': stored, 'currency': 'INR',
        'order': {'items': [{'name': 'X', 'amount': {'value': 100}, 'quantity': 1}],
                  'subtotal': {'value': 100}, 'discount': {'value': 0},
                  'shipping': {'value': 0}, 'tax': {'value': 0}},
    }
    payload = outbound._build_message_payload(
        '+919330994400', '', None, None, False, None, [],
        is_interactive_payment=True, order_details=order,
        phone_number_id='phone-number-id-waba1-direct-1016149501586345',
    )
    assert payload['interactive']['action']['parameters']['reference_id'] == stored


def test_an_order_number_is_still_refused_despite_the_pass_through(outbound):
    """The compact order id is 15 characters of permitted charset, so it IS a Meta-valid
    string — a pass-through placed before the order-number check would hand it to Meta."""
    assert order_keys.is_valid_meta_reference_id('WD-ORD-A1B2C3D4')
    with pytest.raises(outbound.ReferenceIdTooLong):
        outbound._sanitize_reference_id('WD-ORD-A1B2C3D4')


def test_outbound_collapses_a_duplicated_prefix(outbound):
    assert outbound._sanitize_reference_id('WD-PAY-WD-PAY-ABC') == 'WD-PAY-ABC'


def test_outbound_mints_references_from_secrets_not_uuid4(outbound):
    """AST again, not a text search: the docstring mentions uuid4 to explain why it is gone."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(outbound._sanitize_reference_id)))
    called = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert 'secrets.token_hex' in called
    assert not any('uuid4' in name for name in called), \
        f'a sliced uuid4 is not a CSPRNG choice for a payment join key; calls: {called}'


# ── inbound: the read path preserves ───────────────────────────────────────────

def test_inbound_returns_a_valid_reference_byte_for_byte(inbound):
    """The read side resolves an attempt we created, so any normalisation is a chance to break
    the join. Meta's reference_id is case SENSITIVE and permits dots."""
    for value in ('WD-PAY-ABC12345', 'WD-PAY-a.b_c-9', 'wd-pay-lowercase', 'A.B.C'):
        assert inbound._sanitize_reference_id(value) == value


def test_inbound_no_longer_uppercases_a_valid_reference(inbound):
    """The specific regression: upper-casing is a mutation that can break a case-sensitive
    join, and it used to happen to every value before the pass-through checks ran."""
    assert inbound._sanitize_reference_id('WD-PAY-abcdef') == 'WD-PAY-abcdef'


def test_inbound_upgrades_only_what_meta_would_have_rejected(inbound):
    """The new contract, and it is narrower than the old one on purpose.

    `WD+41BA3534` contains a plus, which is outside Meta's charset, so we could never have
    minted it and rewriting it is safe. `WD_41BA3534` uses an underscore, which Meta *permits* -
    so it is a value we might have sent, and the only safe thing to do with it is nothing.
    Rewriting it to `WD-PAY-41BA3534` would look tidier and miss the attempt that owns it.
    """
    assert inbound._sanitize_reference_id('WD+41BA3534') == 'WD-PAY-41BA3534'
    assert inbound._sanitize_reference_id('WD_41BA3534') == 'WD_41BA3534'


def test_inbound_still_collapses_a_duplicated_prefix(inbound):
    assert inbound._sanitize_reference_id('WD-PAY-WD-PAY-ABC') == 'WD-PAY-ABC'


def test_inbound_does_not_shorten_an_over_length_upgrade(inbound):
    """It must not raise - a webhook that 500s is retried forever - and it must not truncate.
    Returning it long means the lookup misses, which surfaces for staff."""
    result = inbound._sanitize_reference_id('WD' + '9' * 60)
    assert len(result) > LIMIT
    assert result.startswith('WD-PAY-')


def test_inbound_passes_empty_through_unchanged(inbound):
    assert inbound._sanitize_reference_id('') == ''
    assert inbound._sanitize_reference_id(None) is None
