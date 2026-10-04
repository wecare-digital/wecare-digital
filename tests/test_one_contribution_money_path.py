"""There is ONE money path for a contribution, demonstrated rather than asserted.

Phase 2's central claim is that a contribution stops being its own payment feature. The risk in a
claim like that is not that it is false on the day it lands -- it is that a later edit quietly
reintroduces the second implementation, and nothing fails. `blog_contribution.py` still CONTAINS a
complete Razorpay implementation (its own order create, binding, callback verifier and settlement);
it is retained as the settlement net for a hypothetical stray legacy order and because it is the
guard holding the preset amounts equal across the TS/Python boundary. Retained and unreachable is a
state that needs a test, because it is indistinguishable from retained and wired by reading one
file.

So this walks the AST of every handler in the tree and asserts two things:

1. **No handler calls `prepare_contribution`, `verify_contribution_callback` or
   `settle_contribution_capture`**, with one deliberate exception: the Razorpay webhook keeps its
   keyed `BLOG_CONTRIBUTION` net. Nothing mints `notes.purpose == 'BLOG_CONTRIBUTION'` any more, so
   that branch can no longer fire, but deleting a verified settlement path is not this phase's job.
2. **The contribution prepare path cannot charge again.** The Wix endpoints the checkout handler and
   its collaborators can reach are enumerated, and none of them is an order-create, a place-order or
   a charging endpoint. R7.4 asks for "it cannot charge again" to be demonstrated by enumeration
   rather than asserted in prose, and an enumeration is what survives a refactor.

An AST walk rather than a text grep, deliberately: the comments explaining this rule necessarily
contain the very names being banned, and a text search cannot tell a call from an explanation.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The three entry points of `blog_contribution`'s own money path.
RETIRED_MONEY_ENTRY_POINTS = (
    "prepare_contribution",
    "verify_contribution_callback",
    "settle_contribution_capture",
)

#: The one handler allowed to name them, and the reason. Keyed on the path so a NEW handler cannot
#: inherit the exemption by being named similarly.
RETAINED_NET = "amplify/functions/payments/razorpay-webhook/handler.py"

#: Wix endpoint fragments that create, place or charge an order. None of these may appear in the
#: checkout function's package or in the shared modules it reaches on the prepare path.
CHARGING_FRAGMENTS = (
    "/orders/create",
    "/create-order",
    "/ecom/v1/orders",
    "/v1/orders/create",
    "place-order",
    "placeOrder",
    "/checkouts/{checkoutId}/create-order",
    "create-order-from-checkout",
    "/payments/capture",
    "/capture",
    "/refund",
)

#: The modules the contribution prepare path actually reaches, enumerated rather than globbed so
#: adding one to the path means adding it here and having the enumeration apply to it.
PREPARE_PATH_MODULES = (
    "amplify/functions/ecommerce/checkout/handler.py",
    "amplify/functions/shared/lambda_utils/wix_ecom.py",
    "amplify/functions/shared/lambda_utils/ecommerce/cart_v2.py",
    "amplify/functions/shared/lambda_utils/ecommerce/customer_cart.py",
    "amplify/functions/shared/lambda_utils/ecommerce/purchase_intent.py",
    "amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py",
    "amplify/functions/shared/lambda_utils/ecommerce/website_checkout.py",
)


def _handlers():
    for path in sorted((ROOT / "amplify/functions").rglob("handler.py")):
        yield path.relative_to(ROOT).as_posix(), ast.parse(
            path.read_text(encoding="utf-8"))


def _called_names(tree: ast.AST) -> set:
    """Every name that appears in a CALL position, plus every imported name.

    Both halves matter. A call tells you the path runs; an import tells you a module took a
    dependency on it, which is the step before a call and the thing a reviewer should see first.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.name)
                if alias.asname:
                    names.add(alias.asname)
    return names


def test_no_handler_reaches_the_retired_contribution_money_path():
    offenders = []
    for relative, tree in _handlers():
        if relative == RETAINED_NET:
            continue
        used = _called_names(tree)
        for name in RETIRED_MONEY_ENTRY_POINTS:
            if name in used:
                offenders.append((relative, name))
    assert offenders == [], (
        "a handler reaches blog_contribution's retired money path; a contribution is created by "
        "website_checkout.prepare_checkout and nothing else: " + repr(offenders))


def test_the_retained_webhook_net_is_still_there_and_is_the_only_one():
    """The exemption is asserted in both directions, so it cannot rot into a blanket allowance.

    If the webhook ever stops naming the settlement function, this exemption is dead code and the
    list above should shrink -- which is a thing a reviewer wants to be told rather than discover.
    """
    tree = ast.parse((ROOT / RETAINED_NET).read_text(encoding="utf-8"))
    assert "settle_contribution_capture" in _called_names(tree), (
        "the webhook's retained BLOG_CONTRIBUTION net is gone; remove the exemption above")


def test_the_checkout_handler_does_not_import_the_contribution_payment_surface():
    """It imports the recognition set and the three choices, and nothing that moves money.

    The allowance SHRANK with the 2026-10-04 model change rather than growing to accommodate it:
    `CONTRIBUTION_MIN_PAISE`, `CONTRIBUTION_MAX_PAISE`, `CONTRIBUTION_PRESETS_PAISE` and
    `validate_contribution_amount` belong to the retired own-money path and are no longer
    imported, because with three fixed prices there is no customer-proposed amount to validate.
    They stay in `blog_contribution` for that retired path and are listed here as explicitly NOT
    allowed on the live one, so a reinstated bounds check is a failing test rather than a quiet
    return to the old model.
    """
    tree = ast.parse(
        (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "blog_contribution" in (node.module or ""):
            imported.update(alias.name for alias in node.names)
    assert imported, "the handler must import the committed choices rather than re-declare them"
    assert imported <= {
        "CONTRIBUTION_CHOICES_PAISE", "CONTRIBUTION_PRODUCT_IDS", "CONTRIBUTION_VARIANT_IDS",
        "ContributionRejected",
    }, f"the checkout handler imported more than the recognition policy: {sorted(imported)}"
    assert not (imported & set(RETIRED_MONEY_ENTRY_POINTS))
    assert not (imported & {"CONTRIBUTION_MIN_PAISE", "CONTRIBUTION_MAX_PAISE",
                            "CONTRIBUTION_PRESETS_PAISE", "validate_contribution_amount"}), \
        "the retired amount-as-quantity bounds must not return to the live checkout path"


@pytest.mark.parametrize("relative", PREPARE_PATH_MODULES)
def test_the_prepare_path_reaches_no_order_creating_or_charging_wix_endpoint(relative):
    """Enumerated from the AST's string constants, so "it cannot charge again" is demonstrated.

    Every Wix endpoint these modules can reach is a cart read, a cart mutation, a calculate or a
    product read. A contribution's prepare therefore cannot create a Wix order, place one, capture
    a payment or issue a refund -- there is no call site for any of them.
    """
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    literals = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    offenders = sorted({value for value in literals
                        for fragment in CHARGING_FRAGMENTS
                        if fragment in value and value.startswith("/")})
    assert offenders == [], (
        f"{relative} names a Wix order-create, place-order or charging endpoint: {offenders}")


def test_the_enumeration_itself_is_not_vacuous():
    """A guard that can never fire protects nothing, so the detector is proven to detect.

    Without this, a typo in `CHARGING_FRAGMENTS` -- or a future rename of the fragments -- would
    turn the test above into a tautology that passes over a handler that charges twice.
    """
    probe = ast.parse('X = "/ecom/v1/orders"\nY = "/stores/v3/products/1"\n')
    literals = [node.value for node in ast.walk(probe)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    hits = [value for value in literals
            for fragment in CHARGING_FRAGMENTS
            if fragment in value and value.startswith("/")]
    assert hits == ["/ecom/v1/orders"]


def test_no_route_named_contribution_exists_in_the_checkout_handler():
    """`POST /api/ecommerce/contribution` stays 404 and is never built.

    `_action` is the dispatch, and a contribution arm appearing in its tuple would be the first
    visible sign of the second implementation returning.
    """
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    action = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_action")
    actions = {node.value for node in ast.walk(action)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "contribution" not in actions
    assert actions >= {"create", "status", "prepare", "verify", "profile"}
