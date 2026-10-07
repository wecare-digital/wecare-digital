"""Every payment DECISION must survive the word `paid`.

`lambda_utils/payment_status.py` established one vocabulary and measured five spellings of
it live, of which `paid` and `captured` denote the same real-world state. What it could not
do on its own is make the callers use it: the handlers kept comparing raw strings, so the
module was correct and unconsulted.

These tests pin the decision points, not the renderers. The distinction is deliberate and
the tests would be wrong without it:

  A DECISION changes what happens - whether a paid invoice can be voided, whether a capture
  is rejected as a mismatch, whether a customer is told their payment failed, whether money
  lands in a revenue total. Those must be canonical, and each one below failed in the
  dangerous direction before this landed.

  A DOCUMENT LIFECYCLE is a different axis. `InvoicesTable.status` genuinely moves
  created -> sent -> paid -> cancelled, and `payment_status` says explicitly that it does
  not own that field. `inv.get('status') != 'paid'` is therefore CORRECT and is not touched
  by these tests. Canonicalising it would collapse two different facts about one row.

  A RENDERER (a badge colour, a PDF stamp) reads an already-decided value. A wrong spelling
  there shows a wrong badge, not a wrong money outcome.

The source-level assertions use `ast` rather than grep, because the docstrings in these
handlers legitimately quote the string literals being forbidden.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "amplify" / "functions" / "shared"
FUNCTIONS = ROOT / "amplify" / "functions"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import payment_status as ps  # noqa: E402


# ── the property the whole exercise rests on ──────────────────────────────────

def test_paid_and_captured_are_one_state():
    """If this ever stops holding, every test below is testing the wrong thing."""
    assert ps.canonical("paid") == ps.CAPTURED
    assert ps.canonical("captured") == ps.CAPTURED
    assert ps.canonical("PAID") == ps.CAPTURED
    assert ps.canonical(" Paid ") == ps.CAPTURED


def test_the_order_records_own_word_is_on_the_ladder():
    """`PAYMENT_PAID` is what an order row actually holds, and it used to map to nothing.

    `ecommerce/finalization.accept_paid` writes `paymentStatus: 'PAYMENT_PAID'` onto every order
    it creates. Before the `payment_paid` alias, `canonical()` returned `''` and `rank()` returned
    0 for that value - so the one word the order table really stores was the one word the
    vocabulary could not read, and a rank comparison would have let a later `pending` overwrite a
    confirmed capture.
    """
    assert ps.canonical("PAYMENT_PAID") == ps.CAPTURED
    assert ps.rank("PAYMENT_PAID") == 50
    # Same state, so the rank matches every other spelling of it.
    assert ps.rank("PAYMENT_PAID") == ps.rank("captured") == ps.rank("paid")


def test_payment_paid_is_also_writable_and_that_is_intended():
    """`for_storage('PAYMENT_PAID')` now returns 'captured' instead of raising. Deliberate.

    Widening `for_storage` is normally the cost of an alias rather than its benefit, and here it
    is acceptable for a specific reason: PAYMENT_PAID and `captured` are the SAME state on one
    ladder, so accepting the write collapses nothing. The attempt vocabulary's other `PAYMENT_*`
    words are not like that - `payment_attempt._RANK` separates PAYMENT_EXPIRED, PAYMENT_CANCELLED
    and PAYMENT_FAILED as three distinct attempt states - which is why only this one is mapped.
    """
    assert ps.for_storage("PAYMENT_PAID") == ps.CAPTURED
    for not_mapped in ("PAYMENT_CANCELLED", "PAYMENT_EXPIRED"):
        assert ps.canonical(not_mapped) == ""
        assert ps.rank(not_mapped) == 0
        with pytest.raises(ValueError):
            ps.for_storage(not_mapped)


def test_an_unmappable_word_denies_rather_than_permits():
    """Every guard below relies on this: '' is not CAPTURED and not PENDING, so an
    unrecognised provider word fails closed at each decision point."""
    for unknown in ("settled", "processing", "weird", None, "", "none"):
        assert ps.canonical(unknown) != ps.CAPTURED
        assert ps.canonical(unknown) != ps.PENDING


# ── decision 1: cancelling an invoice whose money already moved ───────────────

MONEY_MOVED_RANK = ps.STATUS_RANK[ps.CAPTURED]


def _cancel_is_blocked(stored_status: str) -> bool:
    """The exact expression `invoice-engine.cancel_invoice` now uses."""
    return ps.rank(stored_status) >= MONEY_MOVED_RANK


@pytest.mark.parametrize("stored", ["captured", "paid", "success", "successful", "completed"])
def test_a_paid_invoice_cannot_be_cancelled_whatever_it_is_called(stored):
    """The guard used to be `== 'captured'`, so an invoice stored as `paid` - which is what
    `InvoicesTable` and `OrderTable` were measured writing - was voidable. Voiding a paid
    invoice destroys the record that the customer was charged."""
    assert _cancel_is_blocked(stored), f"{stored!r} would have been cancellable"


@pytest.mark.parametrize("stored", ["refunded", "partially_refunded", "disputed", "chargeback"])
def test_a_refunded_or_disputed_invoice_cannot_be_cancelled_either(stored):
    """Ranked rather than equality-compared, which widens the guard on purpose. Cancelling a
    refunded invoice erases the record that money was taken and given back; cancelling a
    disputed one destroys the evidence while the dispute is still live."""
    assert _cancel_is_blocked(stored)


@pytest.mark.parametrize("stored", ["pending", "pending_payment", "created", "authorized",
                                    "failed", "cancelled", "none", ""])
def test_an_unpaid_invoice_is_still_cancellable(stored):
    """The fix must not seize up the ordinary path. `authorized` is the interesting one: a
    hold is not a receipt, so an authorised-but-uncaptured invoice may still be voided."""
    assert not _cancel_is_blocked(stored)


# ── decision 2: the Meta payment lookup that can REJECT a real payment ────────

def _lookup_is_rejected(lookup_status: str) -> bool:
    """The expression `inbound-whatsapp-handler` now uses for REJECTED_MISMATCH."""
    return ps.canonical(lookup_status) != ps.CAPTURED


@pytest.mark.parametrize("answered", ["captured", "paid", "success", "completed"])
def test_meta_answering_paid_is_not_a_mismatch(answered):
    """This is the sharpest one. Meta's raw vocabulary is not ours - `payment_status`
    measured `FlowSubmission.paymentStatus` already holding Meta's `paid` - and the check
    was `!= 'captured'`. So Meta confirming the payment in its own words was recorded as
    REJECTED_MISMATCH: the customer paid and we refused it."""
    assert not _lookup_is_rejected(answered)


@pytest.mark.parametrize("answered", ["pending", "failed", "authorized", "", "gibberish"])
def test_a_lookup_that_does_not_confirm_capture_is_still_rejected(answered):
    """Widening the accepted set must not make the verification vacuous. `authorized` must
    still reject: funds held are not funds received."""
    assert _lookup_is_rejected(answered)


# ── decision 3: which message a paying customer receives ──────────────────────

def _customer_sees_success(order_status: str) -> bool:
    """The branch `outbound-whatsapp` now takes for the success message."""
    return ps.canonical(order_status) == ps.CAPTURED


@pytest.mark.parametrize("reported", ["captured", "completed", "paid", "success"])
def test_a_paying_customer_is_never_told_the_payment_failed(reported):
    """The original test was `== 'completed' or == 'captured'` - itself an admission that one
    state has several words, listing two of the five. `paid` fell through to the failure
    branch, so the message sent to someone who had just paid was 'Payment failed'."""
    assert _customer_sees_success(reported)


@pytest.mark.parametrize("reported", ["failed", "pending", "authorized", ""])
def test_a_customer_who_has_not_paid_is_not_thanked(reported):
    assert not _customer_sees_success(reported)


# ── decision 4: money totals that must reconcile ──────────────────────────────

def test_captured_plus_pending_reconciles_to_the_total():
    """`capturedAmount` and `pendingAmount` were bucketed on raw strings while
    `totalPaymentAmount` summed everything, so a `paid` row landed in the total and in
    neither bucket. The shortfall read as missing data rather than a vocabulary mismatch."""
    rows = [
        {"paymentStatus": "captured", "paymentAmount": 10000},
        {"paymentStatus": "paid", "paymentAmount": 25000},      # the row that used to vanish
        {"paymentStatus": "success", "paymentAmount": 500},
        {"paymentStatus": "pending", "paymentAmount": 7000},
        {"paymentStatus": "pending_payment", "paymentAmount": 300},
    ]
    captured = sum(r["paymentAmount"] for r in rows
                   if ps.canonical(r["paymentStatus"]) == ps.CAPTURED)
    pending = sum(r["paymentAmount"] for r in rows
                  if ps.canonical(r["paymentStatus"]) == ps.PENDING)
    total = sum(r["paymentAmount"] for r in rows)

    assert captured == 35500
    assert pending == 7300
    assert captured + pending == total, "the buckets must account for every row"


def test_a_failed_row_is_in_neither_bucket_but_still_in_the_total():
    """Reconciliation is not the same as counting everything as one or the other - a failed
    attempt is real money nobody owes. The buckets are allowed to under-sum the total here,
    and that is why the reconciliation test above uses only paid and pending rows."""
    rows = [{"paymentStatus": "failed", "paymentAmount": 900}]
    assert sum(r["paymentAmount"] for r in rows
               if ps.canonical(r["paymentStatus"]) in (ps.CAPTURED, ps.PENDING)) == 0


# ── decision 5: granting file access on a Razorpay readback ───────────────────

def test_file_access_is_granted_on_any_spelling_of_captured():
    """`razorpay_orders.order_is_paid` decides whether a paying customer may download what
    they bought. Razorpay's own word is `captured`, so this is hardening rather than a bug
    fix - but pinning an access decision to a single provider spelling means a rename on
    their side starts denying paid customers, silently."""
    for spelling in ("captured", "paid"):
        assert ps.canonical(spelling) == ps.CAPTURED
    for denied in ("authorized", "failed", "created", "refunded"):
        assert ps.canonical(denied) != ps.CAPTURED


# ── the callers really do consult the module ──────────────────────────────────

#: (path, the local alias the module is bound to in that file)
CONSULTING_FILES = [
    ("payments/invoice-engine/handler.py", "pay_status"),
    ("payments/razorpay-webhook/handler.py", "payment_status"),
    ("messaging/inbound-whatsapp-handler/handler.py", "pay_status"),
    ("messaging/outbound-whatsapp/handler.py", "pay_status"),
    ("messaging/whatsapp-business-api/handler.py", "pay_status"),
    ("messaging/whatsapp-business-api/flows/track_request.py", "pay_status"),
    # The customer order-history read. It makes no payment decision of its own - it reports a
    # canonical value and a rank and lets the browser choose the sentence - but it is the one
    # reader of `OrderTable.paymentStatus` on the customer surface, and that column was measured
    # holding `pending`, `none`, `paid` and arbitrary admin input. Listing it brings both gates:
    # the import assertion, and the AST walk that forbids a raw comparison.
    ("ecommerce/customer-orders/handler.py", "payment_status"),
    # The locker's Razorpay readback, which decides whether a paying customer may download what
    # they bought. `test_file_access_is_granted_on_any_spelling_of_captured` above already
    # reasons about this exact function, but it asserted the property against `payment_status`
    # in the abstract and never pinned the file - so the one decision site that could drift was
    # the one the gate described rather than guarded. The import is function-local
    # (`order_is_paid` imports lazily, so a cold start pays nothing for it), which `ast.walk`
    # finds regardless of nesting.
    ("core/secure-files/razorpay_orders.py", "payment_status"),
]

#: Files with no payment-status decision of their own, which must still never compare a payment
#: word raw. They are not in CONSULTING_FILES because they have nothing to consult: the coupon
#: handler decides eligibility, the gift-card handler decides issuance, and the gift-card
#: settlement ladder is its own module (gift_card_settlement) with its own ranks. Forcing an
#: unused `payment_status` import to pass the import assertion would make that assertion mean
#: less, and the import would not survive the first tidy-up.
RAW_SCAN_ONLY_FILES = [
    ("ecommerce/coupons/handler.py", None),
    ("ecommerce/gift-cards/handler.py", None),
    ("ecommerce/wix-giftcard-spi/handler.py", None),
    # Phase O-1 services. None of them decides payment state: a request is created only when the
    # `PAYMENTATTEMPT#` claim exists, so paid-ness is the existence of a row, never a word. They
    # are scanned so that stays true.
    ("ecommerce/service-requests/handler.py", None),
    ("shared/lambda_utils/ecommerce/service_request_store.py", None),
    ("shared/lambda_utils/ecommerce/service_requests.py", None),
    ("shared/lambda_utils/ecommerce/service_request_dispatch.py", None),
    # Phase O-2 Drop Docs storage. It decides whether an object is PRIVATE, never whether it
    # is paid - the gate it owns is `media_paths.is_gated`, and paid-ness is still the
    # existence of the `PAYMENTATTEMPT#` claim. Scanned so a payment word never creeps into a
    # storage decision.
    ("shared/lambda_utils/ecommerce/dropdocs_storage.py", None),
    # The locker itself, which is where that separation is actually under pressure. Unlike the
    # three files above, this one genuinely contains a payment path - `_payment_enabled`,
    # `_create_order` and the grant readback - and Phase O-2 added the Drop Docs attach arm
    # directly beside it. So it is the one file where a payment word and a storage decision are
    # neighbours, and it is scanned to keep them from meeting. It consults nothing itself: the
    # capture question is delegated to `razorpay_orders.order_is_paid`, which is listed above
    # as a consulting file, so an unused import here would weaken that assertion rather than
    # add anything.
    ("core/secure-files/handler.py", None),
]


def _module_aliases(tree: ast.Module) -> set[str]:
    """Names that `lambda_utils.payment_status` is bound to anywhere in the file."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("lambda_utils"):
            for alias in node.names:
                if alias.name == "payment_status":
                    found.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("lambda_utils.payment_status"):
                    found.add(alias.asname or alias.name)
    return found


@pytest.mark.parametrize("relative,alias", CONSULTING_FILES)
def test_the_handler_imports_the_vocabulary_module(relative, alias):
    """A module nobody imports cannot be the single vocabulary. Before this change, four of
    these six files compared raw strings and imported nothing."""
    tree = ast.parse((FUNCTIONS / relative).read_text(encoding="utf-8"))
    assert alias in _module_aliases(tree), (
        f"{relative} does not bind lambda_utils.payment_status as {alias!r}")


# The one word that must never be compared raw. Deliberately just `captured`, and the two
# exclusions are the whole reason this test is trustworthy rather than noisy:
#
#   `captured` belongs EXCLUSIVELY to the payment vocabulary. No other axis in this codebase
#   uses the word, so any raw comparison against it is a payment decision pinned to a single
#   spelling - which is exactly the defect class. And it catches the dangerous direction:
#   comparing `== 'captured'` is what MISSES a row stored as `paid`.
#
#   `paid` is excluded because it is genuinely shared. It is both a payment spelling and a
#   legitimate value of the `InvoicesTable.status` document lifecycle
#   (created -> sent -> paid -> cancelled), which `payment_status` says explicitly it does not
#   own. Banning it would fail on correct code, and every heuristic for telling the two axes
#   apart from the AST alone was more fragile than the bug it would catch.
#
#   `pending` is excluded because it is compared raw in several non-payment senses here - a
#   bulk-job recipient, a submit-request lifecycle - and a test that cannot distinguish those
#   is noise. A noisy gate gets switched off.
FORBIDDEN_RAW = {"captured"}


@pytest.mark.parametrize("relative,alias", CONSULTING_FILES + RAW_SCAN_ONLY_FILES)
def test_no_decision_compares_a_payment_word_raw(relative, alias):
    """Walk the AST for `<anything> == 'captured'` and friends.

    Uses `ast`, not grep, for a concrete reason: the docstrings and comments these handlers
    now carry quote `'captured'` and `'paid'` while explaining why not to compare them. A
    textual search flags its own explanation.

    Comparisons guarded by a `canonical(...)` call on either side are fine - that is the
    fix, not a violation.
    """
    source = (FUNCTIONS / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def is_canonicalised(node: ast.expr) -> bool:
        """True when this operand already went through the module."""
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("canonical", "for_storage", "rank")) or (
            # A name holding a canonical value, by convention in these handlers.
            isinstance(node, ast.Name) and node.id in ("payment_state", "pay"))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue
        operands = [node.left, *node.comparators]
        literals = {o.value for o in operands
                    if isinstance(o, ast.Constant) and isinstance(o.value, str)}
        if not (literals & FORBIDDEN_RAW):
            continue
        if any(is_canonicalised(o) for o in operands):
            continue
        offenders.append(f"line {node.lineno}: compares {sorted(literals & FORBIDDEN_RAW)} raw")

    assert not offenders, (
        f"{relative} decides on a raw payment word:\n  " + "\n  ".join(offenders)
        + "\n\nRoute it through payment_status.canonical() - `paid` and `captured` are one "
          "state, and five spellings were measured live."
    )


def test_paid_is_deliberately_not_in_the_forbidden_set():
    """Pins the scope of the gate above, so a later "tighten it up" reads the reason first.

    Adding `paid` to `FORBIDDEN_RAW` would fail on correct code: `InvoicesTable.status` is a
    document lifecycle whose vocabulary genuinely includes `paid`, and `payment_status` does
    not own that field. `captured` is safe to ban outright because no other axis uses it.
    """
    assert FORBIDDEN_RAW == {"captured"}
    assert "paid" not in FORBIDDEN_RAW
    # And the reason it is safe to leave out: banning `captured` already catches the
    # dangerous direction, because `== 'captured'` is the comparison that misses `paid`.
    assert ps.canonical("paid") == ps.canonical("captured")


def test_the_invoice_document_lifecycle_is_deliberately_left_raw():
    """Guards the boundary of this whole change.

    `InvoicesTable.status` is a document lifecycle (created -> sent -> paid -> cancelled), a
    different axis from whether money moved, and `payment_status.for_storage` says in its own
    docstring that it does not apply to it. So `inv.get('status') != 'paid'` is correct, and
    a future cleanup that "finishes the job" by canonicalising it would lose information.

    This test exists so that intent is executable rather than a comment.
    """
    source = (FUNCTIONS / "payments/razorpay-webhook/handler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    lifecycle_comparisons = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # `inv.get('status') != 'paid'`
        left, comparators = node.left, node.comparators
        if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute)
                and left.func.attr == "get"):
            continue
        if not (left.args and isinstance(left.args[0], ast.Constant)
                and left.args[0].value == "status"):
            continue
        if any(isinstance(c, ast.Constant) and c.value == "paid" for c in comparators):
            lifecycle_comparisons += 1

    assert lifecycle_comparisons >= 1, (
        "the invoice document-lifecycle comparison has gone; if that was deliberate, this "
        "test and the reasoning in payment_status.for_storage need updating together")
