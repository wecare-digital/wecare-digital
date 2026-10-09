"""ONE coupon authority, ONE gift-card authority, and NO discount arithmetic in a browser.

WHAT THIS FILE IS FOR
---------------------
The owner's instruction was "one system only" and "remove what is not working". Exploration found
that neither of the two half-built stacks was old and neither was wired: `redemption.py` held the
money arithmetic and the apply order with no concrete provider anywhere, and
`coupon_store`/`gift_card_store` held real tables, Wix mirrors and routes with no caller in any
money path. So the work was to BIND them, not to pick one and delete the other - and the risk a
binding carries is that a second one grows beside it later, quietly, in a handler nobody is
reading. These tests are the thing that notices.

Every assertion here is STRUCTURAL and mostly NEGATIVE, which is deliberate: a positive
end-to-end coupon test proves a stub works, while these prove there is only one implementation to
get wrong.

THE STEP-13 LEGACY-SURFACE AUDIT, recorded here rather than claimed in a plan
----------------------------------------------------------------------------
Measured across `src/` and `amplify/`, and re-verified by the tests below rather than by reading:

  * `src/pages/cart.tsx`'s `RedemptionPanel` - THE REFERENCE. Kept, untouched, not repointed.
    `tests/test_whatsapp_order_coupon_parity.py` pins `REDEMPTION_URL` present and declared
    exactly once; `POST /ecommerce/redemption` stays the one customer-facing apply endpoint.
  * `src/pages/perks.tsx` - no coupon mechanism. Its line 172 already reads that an eligible
    coupon applies at checkout and not there. CORRECT ALREADY, left alone.
  * `src/pages/get.tsx`, `src/pages/workspace/pay/records.tsx`,
    `src/pages/workspace/commerce/*` - grepped: no coupon, gift-card or discount mechanism.
    NOTHING TO REMOVE.
  * `src/pages/workspace/pay/flow/index.tsx` - its manual rupee field is CONVERGED, not removed
    (decision D4): relabelled "Manual adjustment", defaulted to 0 where it used to default to 15,
    and previewed on its own row. A goodwill credit a staff member decides on is a different fact
    from a coupon the store issued; what made them look like one mechanism was the silent default.
  * `src/pages/workspace/engage/inbox/index.tsx` - carries the SAME manual staff discount field,
    already defaulting to '0'. Audited and kept for the same reason. It converts the typed rupee
    figure to paise, which is a unit conversion of a staff decision and not a coupon computation.
  * `redemption.py`'s abstract seam - RETAINED and now bound. It owns the money arithmetic and the
    apply order.
  * the `/coupons/*` and `/gift-cards/*` routes - RETAINED. They are issuance, verdict and
    balance, and the invoice path now reads the same tables through the same modules.

The legacy checkout-button callback no longer advertises hardcoded offers or changes
coupon amounts without a reservation/settlement linkage. Coupon edits must be made
through the cart/invoice authority before requesting payment.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
AMPLIFY = ROOT / "amplify"
SRC = ROOT / "src"

COUPON_STORE = AMPLIFY / "functions/shared/lambda_utils/ecommerce/coupon_store.py"
REDEMPTION = AMPLIFY / "functions/shared/lambda_utils/ecommerce/redemption.py"
PROVIDER = AMPLIFY / "functions/shared/lambda_utils/ecommerce/store_redemption_provider.py"
CART_PAGE = SRC / "pages/cart.tsx"
WA_BUSINESS = AMPLIFY / "functions/messaging/whatsapp-business-api/handler.py"

#: The two methods `redemption.RedemptionProvider` declares. A class carrying BOTH is a provider.
PROVIDER_METHODS = {"validate_coupon", "read_gift_card"}


def _python_sources():
    """Every tracked `.py` file under `amplify/`, skipping build artefacts.

    `node_modules` is excluded for the same reason `_frontend_sources` excludes it:
    `amplify/node_modules` is untracked, so reading it contradicts "tracked" above. It
    holds 15 `aws-cdk-lib` custom-resource handlers, and letting them into this walk
    makes a dependency able to fail one of our gates — a vendored file defining both
    provider methods would read as a second implementation of ours.
    """
    for path in sorted(AMPLIFY.rglob("*.py")):
        if ("__pycache__" in path.parts or ".aws-sam" in path.parts
                or "node_modules" in path.parts):
            continue
        yield path


def _frontend_sources(root: pathlib.Path):
    for pattern in ("*.ts", "*.tsx"):
        for path in sorted(root.rglob(pattern)):
            if "node_modules" in path.parts:
                continue
            yield path


def _code_lines(text: str):
    """Source lines with the obvious comment forms dropped.

    Not a parser, and it does not need to be: it exists so a paragraph EXPLAINING a forbidden
    shape does not read as the shape itself, which is the same failure mode
    `test_payment_vocabulary_at_decision_points.py` solves by walking the AST. A JSX comment
    (`{ /* … */ }`), a block-comment continuation (`* …`) and a `//` line all start their line
    here, so matching on the line's first non-space characters is sufficient for this repo.
    """
    out = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if line.startswith("/*") or line.startswith("{ /*") or line.startswith("{/*"):
            if "*/" not in line:
                in_block = True
            continue
        if line.startswith("//") or line.startswith("*"):
            continue
        out.append(raw)
    return out


# ── one concrete provider ─────────────────────────────────────────────────────


def test_exactly_one_concrete_redemption_provider_exists_under_amplify():
    """A second provider is how two authorities get two different answers for one code.

    The Protocol in `redemption.py` is excluded by path, not by name: it is the seam, and the
    whole point of the seam is that exactly one thing implements it.
    """
    implementations = []
    for path in _python_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a genuinely broken file fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {child.name for child in node.body
                       if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if PROVIDER_METHODS <= methods and path != REDEMPTION:
                implementations.append((path.relative_to(ROOT).as_posix(), node.name))

    assert len(implementations) == 1, f"expected one concrete provider, found {implementations}"
    assert implementations[0][0] == PROVIDER.relative_to(ROOT).as_posix()


#: Identifiers that make an expression a MONEY expression. A multiplication or division touching
#: one of these is discount arithmetic; `self._clock() * 1000` is a seconds-to-milliseconds unit
#: conversion and is not. Blanket-banning every `*` in the provider caught exactly that clock
#: line, which is why the rule names the money vocabulary instead of the operator alone.
MONEY_WORDS = ("paise", "balance", "amount", "discount", "percent", "collection", "bps", "price")


def _mentions_money(node: ast.AST) -> bool:
    return any(
        any(word in part.lower() for word in MONEY_WORDS)
        for child in ast.walk(node)
        for part in ([child.id] if isinstance(child, ast.Name) else
                     [child.attr] if isinstance(child, ast.Attribute) else [])
    )


def test_the_provider_holds_no_discount_arithmetic_of_its_own():
    """Its emptiness is the point: every amount comes from `coupon_store.discount_paise` or from
    the card's stored `balancePaise`. A provider that computed anything would be a second
    authority wearing the seam's clothes."""
    source = PROVIDER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        if not isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv)):
            continue
        assert not _mentions_money(node), (
            f"{PROVIDER.name} performs money arithmetic at line {node.lineno}")
    # A float anywhere in this module would be a second rounding rule beside the integer-paise one.
    assert "float(" not in source


# ── one coupon-amount authority ───────────────────────────────────────────────


def test_the_coupon_amount_is_computed_in_exactly_one_place():
    """Only the store computes coupon amounts; handlers must consume its verdict."""
    known = {(COUPON_STORE.relative_to(ROOT).as_posix(), "discount_paise")}
    found = set()
    for path in _python_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name.lower()
            if "coupon" in name and ("discount" in name or "amount" in name):
                found.add((path.relative_to(ROOT).as_posix(), node.name))
            elif name == "discount_paise":
                found.add((path.relative_to(ROOT).as_posix(), node.name))

    assert found == known, f"coupon-amount functions changed: {found ^ known}"


def test_no_hardcoded_checkout_coupon_engine_remains():
    holders = [path.relative_to(ROOT).as_posix() for path in _python_sources()
               if "CHECKOUT_COUPONS" in path.read_text(encoding="utf-8")]
    assert holders == [], holders


def test_the_invoice_and_cart_paths_import_the_same_authority():
    """Both money paths reach the coupon amount through `coupon_store`, via the one provider."""
    provider_source = PROVIDER.read_text(encoding="utf-8")
    assert "coupon_store" in provider_source
    assert "discount_paise" in provider_source

    invoice = (AMPLIFY / "functions/payments/invoice-engine/handler.py").read_text(encoding="utf-8")
    assert "store_redemption_provider" in invoice
    assert "redemption" in invoice


# ── the browser computes nothing ──────────────────────────────────────────────


def test_src_declares_exactly_one_redemption_url_and_it_is_the_cart_page():
    """The cart panel is the reference surface. A second declaration anywhere in `src/` would be a
    second customer-facing apply path, which is the thing "one system" rules out."""
    declarations = []
    for path in _frontend_sources(SRC):
        text = path.read_text(encoding="utf-8")
        if "REDEMPTION_URL" in text and "test" not in path.name.lower():
            declarations.append((path.relative_to(ROOT).as_posix(),
                                 text.count("const REDEMPTION_URL")))

    assert declarations == [(CART_PAGE.relative_to(ROOT).as_posix(), 1)], declarations


def test_no_second_fetch_to_a_coupon_or_gift_card_endpoint_exists_in_src():
    """Exactly one page talks to a redemption endpoint directly. Everything else goes through the
    typed API client, which is how the staff invoice form reaches the same authority: it sends a
    CODE on `createInvoiceEngine` and the server applies it."""
    endpoint = re.compile(r"(ecommerce/redemption|/coupons/|/gift-cards/)")
    offenders = []
    for path in _frontend_sources(SRC / "pages"):
        for number, line in enumerate(_code_lines(path.read_text(encoding="utf-8")), 1):
            if endpoint.search(line):
                offenders.append((path.relative_to(ROOT).as_posix(), number, line.strip()))

    assert [o[0] for o in offenders] == [CART_PAGE.relative_to(ROOT).as_posix()], offenders


def test_no_page_computes_a_coupon_or_gift_card_amount_in_the_browser():
    """THE RULE, stated precisely: a browser must never DERIVE a redemption figure.

    Multiplication and division are what that looks like - a rate applied to a price, or a paise
    figure converted by dividing. Both are forbidden on any line naming a coupon or a gift card.

    Subtraction is NOT forbidden, and the distinction is real rather than convenient:
    `invoice.discount - invoice.couponDiscount` splits two figures the SERVER stored into the two
    lines the invoice renderers already print. It derives nothing; it reads one stored number out
    of another. Deriving `subtotal * rate` would be inventing a number the ledger never agreed to,
    and that is the failure this test exists for.
    """
    redemption_word = re.compile(r"coupon|giftcard|gift_card", re.IGNORECASE)
    #: `* <number|rate>` or `<number|rate> *`, and the same for `/`. Anchored on a numeric or
    #: rate-shaped operand rather than on the bare operator, because `</label>` and a trailing
    #: `// comment` both contain a `/` and neither is arithmetic - the first run of this test
    #: reported seventeen JSX closing tags.
    arithmetic = re.compile(
        r"(?:[*/]\s*(?:\d|percent|rate|bps|100\b))|(?:(?:\d|percent|rate|bps)\s*[*/])",
        re.IGNORECASE)
    offenders = []
    for path in _frontend_sources(SRC / "pages"):
        for number, line in enumerate(_code_lines(path.read_text(encoding="utf-8")), 1):
            code = line.split("//")[0]
            if redemption_word.search(code) and arithmetic.search(code):
                offenders.append((path.relative_to(ROOT).as_posix(), number, line.strip()))

    assert offenders == [], offenders


def test_the_cart_reference_surface_is_still_the_cart_reference_surface():
    """A belt-and-braces restatement of what `test_whatsapp_order_coupon_parity.py` already pins,
    here because THIS file is the one an implementer reads when they decide to "unify" the
    surfaces and reach for the cart panel first."""
    text = CART_PAGE.read_text(encoding="utf-8")
    assert text.count("const REDEMPTION_URL") == 1
    assert "/ecommerce/redemption" in text
    # The panel renders the server's reasons; it does not hold a coupon table of its own.
    assert "COUPON_MESSAGES" in text
    assert "CHECKOUT_COUPONS" not in text


def test_the_staff_forms_share_one_address_composition_helper():
    """One format is enforced by there being one function, not by two forms agreeing.

    Both staff forms import `ADDRESS_FIELDS` and `formatAddress` from `src/lib/address-format.ts`,
    so neither holds a field list of its own to drift from `contact_address._RULES`.
    """
    helper = SRC / "lib/address-format.ts"
    assert helper.exists()
    for page in ("pages/workspace/pay/flow/index.tsx", "pages/workspace/contacts/index.tsx"):
        text = (SRC / page).read_text(encoding="utf-8")
        assert "address-format" in text, page
        assert "ADDRESS_FIELDS" in text, page
        assert "formatAddress" in text, page


def test_the_address_helper_covers_exactly_the_eight_server_rule_fields():
    """`ADDRESS_FIELDS` and `contact_address._RULES` must name the same eight keys. A field in one
    and not the other is a field a form collects and the server discards, or the reverse."""
    import sys
    sys.path.insert(0, str(AMPLIFY / "functions/shared"))
    from lambda_utils.ecommerce import contact_address

    helper = (SRC / "lib/address-format.ts").read_text(encoding="utf-8")
    declared = set(re.findall(r"\{ key: '(\w+)'", helper))
    assert declared == set(contact_address._RULES), declared ^ set(contact_address._RULES)
