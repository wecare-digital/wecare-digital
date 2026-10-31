"""Offline regression gates for Vault website/WhatsApp checkout readiness.

No payment, WhatsApp send, DynamoDB write, or customer data is used.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
REQUESTS = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_requests.py"
CART = ROOT / "src/components/cart/CartPage.tsx"
VAULT = ROOT / "src/components/get/GetPage.tsx"
IDENTITY_CARD = ROOT / "src/components/CheckoutIdentityCard.tsx"
STAFF = ROOT / "src/components/workspace/service/SecureFiles.tsx"


def _read_checkout_profile(rows):
    """Execute just the pure contact-selection seam with an in-memory table."""
    parsed = ast.parse(CHECKOUT.read_text(encoding="utf-8"))
    node = next(part for part in parsed.body
                if isinstance(part, ast.FunctionDef) and part.name == "_checkout_profile")

    class Key:
        def __init__(self, field):
            self.field = field

        def eq(self, value):
            return (self.field, value)

    class Table:
        def query(self, **kwargs):
            assert kwargs["IndexName"] == "phone-index"
            assert kwargs["KeyConditionExpression"] == ("phone", "+911111111111")
            return {"Items": rows}

    namespace = {
        "customer_auth": SimpleNamespace(CustomerIdentity=object),
        "Dict": Dict, "Any": Any, "Optional": Optional,
        "_table": lambda name: Table(),
        "CONTACTS_TABLE": "synthetic-contacts",
        "Key": Key,
        "_profile_phone": lambda identity: identity.phone,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 str(CHECKOUT), "exec"), namespace)
    identity = SimpleNamespace(customer_id="customer-a", phone="+911111111111")
    return namespace["_checkout_profile"](identity)


def test_verified_phone_owner_can_load_profile_without_optional_email():
    row = {"id": "synthetic-contact", "phone": "+911111111111",
           "checkoutCustomerId": "customer-a", "name": "Example Customer",
           "email": "", "deletedAt": None}
    assert _read_checkout_profile([row]) == row


def test_foreign_owner_and_ownerless_contacts_never_become_checkout_identity():
    foreign = {"phone": "+911111111111", "checkoutCustomerId": "customer-b",
               "email": "example@example.invalid", "deletedAt": None}
    ownerless = {"phone": "+911111111111", "name": "Unclaimed",
                 "email": "example@example.invalid", "deletedAt": None}
    assert _read_checkout_profile([foreign]) is None
    assert _read_checkout_profile([ownerless]) is None


def test_deleted_contact_cannot_be_used_even_with_matching_owner():
    deleted = {"phone": "+911111111111", "checkoutCustomerId": "customer-a",
               "email": "", "deletedAt": 123456789}
    assert _read_checkout_profile([deleted]) is None


def test_checkout_requires_name_but_not_email_before_payment():
    source = CHECKOUT.read_text(encoding="utf-8")
    segment = source[source.index("def _website_prepare("):
                     source.index("def _request_service_start(")]
    assert "profile = _checkout_profile(identity)" in segment
    assert '"message": "Add your name to continue checkout."' in segment
    assert "Verify your email and save your checkout details first." not in segment


def test_vault_and_drop_docs_pricing_refuses_mixed_cart_before_payment():
    source = REQUESTS.read_text(encoding="utf-8")
    segment = source[source.index("def checkout_preflight("):
                     source.index("def native_service_line_paise(")]
    assert "line.kind in (VAULT, DROP_DOCS) and len(line_items) != 1" in segment
    assert "SERVICE_SEPARATE_CHECKOUT" in segment
    vault_source = VAULT.read_text(encoding="utf-8")
    assert "readCart().some(" in vault_source
    assert "Your shopping cart has not been changed." in vault_source


def test_cart_restores_session_and_shows_name_for_digital_orders():
    cart = CART.read_text(encoding="utf-8")
    card = IDENTITY_CARD.read_text(encoding="utf-8")
    assert "getSession() || await restoreSession()" in cart
    assert "mode === 'name'" in cart
    assert "profile?.name ? 'address' : profile ? 'name' : 'create'" in cart
    assert "showAddress={ cartRequiresDelivery() }" in cart
    assert "showAddress?: boolean;" in card
    assert "{ showAddress &&" in card


def test_whatsapp_payment_does_not_depend_on_display_price_preview():
    src = VAULT.read_text(encoding="utf-8")
    action = src[src.index("const handleVaultPayment = async"):
                 src.index("    return (", src.index("const handleVaultPayment = async"))]
    assert "requestMySecureFilePayment( file.fileId )" in action
    assert "payablePrice === null" not in action
    assert "disabled={ working === file.fileId }" in src


def test_vault_staff_selection_uses_home_lime_and_shared_font():
    src = STAFF.read_text(encoding="utf-8")
    assert "font-family:var(--font-sans)" in src
    assert "background:var(--public-brand-lime)" in src
    assert "background:var(--public-lime-tint)" in src
    assert "font-size:var(--public-supporting-size)" in src

def test_vault_paid_download_filename_has_all_required_module_imports():
    """A paid and stored Vault file must issue a signed URL, not crash on re.sub."""
    source = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    imported_re = any(
        isinstance(node, ast.Import) and any(alias.name == "re" for alias in node.names)
        for node in module.body
    )
    helper = next(node for node in module.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_safe_download_filename")
    assert imported_re
    assert "re.sub(" in ast.get_source_segment(source, helper)
    assert "_safe_download_filename(item)" in source
