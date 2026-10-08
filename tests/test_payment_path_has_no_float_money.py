"""No float money on the payment path, asserted by AST rather than by grep.

Why it matters here specifically, rather than as a style rule
------------------------------------------------------------
`0.1 + 0.2` is not `0.3` in binary floating point, and a capture is compared against the reserved
amount with EXACT integer equality that fails CLOSED on a one-paise difference. So a rounding
artefact is not cosmetic: it refuses a legitimate payment. The discipline is therefore integer
paise for anything compared, summed or stored, and `payment_status.rupees_str` - which returns a
STRING - for anything displayed. A string cannot be arithmetic'd by accident, which is the point.

Why AST and not a text search
-----------------------------
The docstrings and comments in these handlers legitimately contain the forbidden patterns while
explaining them, so a textual gate flags its own explanation. This is the same reason
`test_payment_vocabulary_at_decision_points.py` walks the AST, which its own header states.

Why there is an allowlist, and why it is keyed on SYMBOL NAMES
-------------------------------------------------------------
The invoice RENDER path is deliberately out of scope: it draws a document from an invoice row
that is already final, nothing it computes is compared against a capture, and changing it was
explicitly not part of this work. An allowlist is the part of a gate that rots, so it is a
written-out set of function names (not line numbers), every entry is asserted to still exist, and
a separate test asserts it contains only render and listing functions - an allowlist that
silently absorbs a new function is the failure mode this guards against.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / 'amplify' / 'functions'

GATED_FILES = [
    'payments/razorpay-webhook/handler.py',
    'payments/invoice-engine/handler.py',
    'messaging/outbound-whatsapp/handler.py',
]

#: Money-shaped `.get(...)` keys. A `float()` of one of these on the payment path is the defect.
MONEY_KEYS = {
    'amount', 'total', 'subtotal', 'discount', 'shipping', 'tax', 'handling',
    'convenienceFee', 'gstRate', 'amountInRupees', 'refundAmount', 'creditNoteAmount',
    'greenPacking', 'notificationFee',
}

#: Functions where float money is DELIBERATELY out of scope, by symbol name.
#:
#: Every one of these renders or lists a document from an invoice row that is already final.
#: None of them computes a figure that is compared against a provider capture, and none of them
#: writes a money field that a reconciliation reads. `create_invoice` is here because it is the
#: invoice CALCULATOR - converting it is a separate change with its own migration, and its output
#: is the row the payment path then reads in exact paise.
RENDER_ALLOWLIST = {
    # invoice-engine
    '_build_invoice_html',
    '_generate_receipt_png',
    '_amount_in_words',
    '_normalize_invoice',
    '_normalize_item',
    '_dec',
    'create_invoice',
    'create_invoice_from_payment',
    'send_pending_by_phone',
    # razorpay-webhook: the LEGACY invoice matcher, which compares a rupee figure against
    # pre-commerce invoice rows. Narrowed to UNKNOWN_REFERENCE only, so a native or website
    # capture never reaches it.
    '_mark_invoice_paid_by_phone_and_amount',
    '_verified_legacy_invoice',
    # outbound-whatsapp: the native-interactive branch's own display assembly.
    '_handle_live_send',
}


def _tree(relative):
    return ast.parse((FUNCTIONS / relative).read_text(encoding='utf-8'))


def _enclosing_functions(tree):
    """`{lineno: function name}` for every line inside a function body."""
    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                # The INNERMOST function wins, so a nested helper is attributed to itself.
                owner[line] = node.name
    return owner


def _money_get_call(node):
    """True when `node` is a `.get('<money key>'...)` call."""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'get'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in MONEY_KEYS)


@pytest.mark.parametrize('relative', GATED_FILES)
def test_no_float_call_on_a_money_value(relative):
    """T-F2. `float(x.get('amount'))` and friends, outside the render allowlist."""
    tree = _tree(relative)
    owner = _enclosing_functions(tree)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'float'):
            continue
        if not node.args:
            continue
        if not _money_get_call(node.args[0]):
            continue
        if owner.get(node.lineno) in RENDER_ALLOWLIST:
            continue
        offenders.append(f'line {node.lineno} in {owner.get(node.lineno)!r}')
    assert not offenders, (
        f'{relative} coerces money with float():\n  ' + '\n  '.join(offenders)
        + '\n\nUse exact integer paise (Decimal(str(x)) * 100) for anything compared, summed '
          'or stored, and payment_status.rupees_str() for anything displayed.')


@pytest.mark.parametrize('relative', GATED_FILES)
def test_no_round_float_times_100_anywhere_in_the_payment_path(relative):
    """T-F4. `int(round(float(x) * 100))` is the exact pattern the exact-paise comparison was
    written to replace: it truncates sub-paise noise into a figure that then compares equal to a
    rounded-down expectation."""
    tree = _tree(relative)
    owner = _enclosing_functions(tree)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'round'):
            continue
        has_float = any(isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                        and inner.func.id == 'float'
                        for inner in ast.walk(node))
        if has_float and owner.get(node.lineno) not in RENDER_ALLOWLIST:
            offenders.append(f'line {node.lineno} in {owner.get(node.lineno)!r}')
    assert not offenders, f'{relative}: round(float(...)) on money: {offenders}'


def test_the_send_leg_divides_no_money_by_one_hundred():
    """T-F1, narrowed to the one function that reserves the figure a capture is compared against.

    A division by 100 is how a paise figure becomes a rupee float. `send_payment_link` computes
    the reserved amount, so it must contain none.
    """
    tree = _tree('payments/invoice-engine/handler.py')
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == 'send_payment_link')
    offenders = [node.lineno for node in ast.walk(func)
                 if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                 and isinstance(node.right, ast.Constant) and node.right.value == 100]
    assert not offenders, f'send_payment_link divides money by 100 at {offenders}'


def test_the_render_allowlist_is_explicit_and_every_entry_exists():
    """T-F3. An allowlist naming a function that no longer exists is an allowlist nobody is
    maintaining, and it would silently widen as the code moves."""
    defined = set()
    for relative in GATED_FILES:
        for node in ast.walk(_tree(relative)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
    missing = RENDER_ALLOWLIST - defined
    assert not missing, f'allowlist names functions that do not exist: {sorted(missing)}'


def test_the_allowlist_contains_only_render_calculate_and_legacy_functions():
    """T-F3's second half. The allowlist must not absorb a function that computes a figure a
    capture is compared against - which is what would make this whole gate decorative."""
    for name in RENDER_ALLOWLIST:
        assert any(token in name for token in (
            # render / display
            'render', 'html', 'png', 'words', 'normalize', 'dec',
            # the invoice calculator and the listing
            'create_invoice', 'send_pending',
            # the legacy rupee matcher, reachable only for UNKNOWN_REFERENCE
            'legacy', 'mark_invoice_paid_by_phone_and_amount',
            # the native-interactive display branch
            'live_send')), name
    # The three functions that decide or reserve money are NOT in it, and must never be.
    for forbidden in ('send_payment_link', '_create_order_for_captured_payment',
                      '_post_payment_handler', '_handle_settlement', '_handle_payout_event',
                      '_store_payment_record', '_build_payment_settings',
                      '_store_message_record', '_handle_order_status_send'):
        assert forbidden not in RENDER_ALLOWLIST, forbidden


def test_the_settlement_and_payout_handlers_report_integer_paise():
    """T-F5. Both log `amountPaise` as an integer and the rupee figure as a string."""
    source = (FUNCTIONS / 'payments/razorpay-webhook/handler.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    for name in ('_handle_settlement', '_handle_payout_event'):
        func = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == name)
        keys = {node.value for node in ast.walk(func)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        assert 'amountPaise' in keys, name
        # and the division that used to be the whole body is gone.
        assert not [n for n in ast.walk(func)
                    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)], name


def test_the_post_payment_payload_reads_no_money_from_notes():
    """T-F7. Razorpay `notes` are REQUEST CONTENT a caller can set, so four caller-settable money
    figures used to travel into a GST invoice. They are dropped, not re-derived: the
    authoritative values are on the reservation row for a native payment and on the invoice for a
    legacy one."""
    tree = _tree('payments/razorpay-webhook/handler.py')
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == '_post_payment_handler')
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'notes'
                and node.args and isinstance(node.args[0], ast.Constant)):
            assert node.args[0].value not in {
                'gstRate', 'shipping', 'discount', 'convenienceFee'}, node.args[0].value


def test_rupees_str_returns_a_string():
    """T-F8. The kept-in-place property, asserted rather than assumed: a string cannot be
    arithmetic'd by accident, which is why every display figure on this path is one."""
    import sys
    sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))
    from lambda_utils import payment_status

    assert payment_status.rupees_str(59900) == '599.00'
    assert isinstance(payment_status.rupees_str(59900), str)
    assert payment_status.rupees_str(1) == '0.01'
    with pytest.raises(ValueError):
        payment_status.paise(True)       # a bool is not an amount


def test_exact_paise_refuses_what_cannot_be_compared():
    """The reservation's own money reader. Sub-paise fails CLOSED, because a figure that cannot
    be compared exactly must never be collected against."""
    import sys
    sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))
    from lambda_utils.ecommerce import wa_payment_request as wpr

    assert wpr.exact_paise('599.00') == 59900
    assert wpr.exact_paise('0.01') == 1
    assert wpr.exact_paise(0) == 0
    for bad in ('99.005', '0.001', 'nonsense'):
        with pytest.raises(wpr.PaymentRequestRefused):
            wpr.exact_paise(bad)


def test_paid_state_is_monotonic_by_condition_not_by_read_then_write():
    """The condition is the authority because two webhook deliveries can be processed
    concurrently, and a read-then-write lets both through."""
    import sys
    sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))
    from lambda_utils import payment_status
    from lambda_utils.ecommerce import payment_attempt

    expression = payment_status.condition_expression()
    assert 'attribute_not_exists' in expression and '<' in expression

    assert payment_status.rank('captured') == payment_status.rank('paid')
    assert payment_status.rank('authorized') < payment_status.rank('captured')
    assert payment_attempt.rank(payment_attempt.PAYMENT_PAID) > payment_attempt.rank(
        payment_attempt.PAYMENT_FAILED)
    assert payment_attempt.rank(payment_attempt.PAYMENT_PAID) > payment_attempt.rank(
        payment_attempt.PAYMENT_REQUEST_SENT)
