"""Static guards for verified WhatsApp cart checkout and public UI styling.

The guards require neither AWS credentials nor live payment attempts. They do
not replace customer-session, provider sandbox, or visual end-to-end tests.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_customer_profile_read_uses_owned_phone_not_optional_email():
    checkout = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    owned_read = checkout.split("def _checkout_profile(", 1)[1].split(
        "\ndef _load_owned_address(", 1
    )[0]

    assert 'item.get("checkoutCustomerId") != identity.customer_id' in owned_read
    assert 'item.get("email")' not in owned_read

    # Both website and web-initiated WhatsApp need a name, but not an email.
    assert '"Add your name to continue checkout."' in checkout
    assert 'if not cart_profile or not full_name.strip():' in checkout
    assert '"email"' not in checkout.split("full_name = str(", 1)[1].split(").strip()", 1)[0]

    profile_save = (ROOT / "amplify/functions/auth/customer-profile/handler.py").read_text()
    assert "Email OTP is not required." in profile_save


def test_checkout_method_survives_intervening_profile_editor():
    cart = (ROOT / "src/components/cart/CartPage.tsx").read_text()
    assert "channel ?? selectedCheckoutChannelRef.current ?? checkoutChannel" in cart
    assert "profile ? ( profile.name ? 'address' : 'name' ) : 'create'" in cart
    assert 'emptyAddressLabel="Not saved yet"' in cart
    assert 'showAddress={ cartRequiresDelivery() }' in cart
    assert 'profileStatus === \'ready\' || profileStatus === \'required\'' in cart


def test_support_language_dropdown_and_checkout_type_use_home_tokens():
    widget = (ROOT / "src/components/SupportWidget.tsx").read_text()
    assert "gap:10px;font-family:var(--font-sans)" in widget
    assert ".wc-row-code{flex:0 0 auto;font-size:var(--public-meta-size)" in widget
    assert "background:var(--public-lime-tint)" in widget
    assert "border-top:3px solid var(--public-brand-lime)" in widget

    address = (ROOT / "src/components/AddressFields.tsx").read_text()
    profile = (ROOT / "src/components/CheckoutProfile.tsx").read_text()
    identity = (ROOT / "src/components/CheckoutIdentityCard.tsx").read_text()
    assert "font-size:var(--public-supporting-size)" in address
    assert "font-size:var(--public-supporting-size)" in profile
    assert "font-size:var(--public-data-size)" in identity


def test_customer_checkout_dropdown_menu_is_branded_not_workspace_grey():
    select = (ROOT / "src/components/ui/Select.tsx").read_text()
    address = (ROOT / "src/components/AddressFields.tsx").read_text()
    css = (ROOT / "src/styles/form-controls.css").read_text()

    assert "menuClassName?: string;" in select
    assert "className={ menuClassName }" in select
    assert address.count('menuClassName="public-checkout-select"') == 2
    assert ".ui-popover.public-checkout-select .ui-select-option[aria-selected=" in css
    assert "background-color: var(--public-brand-lime);" in css
