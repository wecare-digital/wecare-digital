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
    # Owned phone-only profiles need a name-only editor, never a new account form.
    assert "profile?.name ? 'address' : profile ? 'name' : 'create'" in cart
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


def test_orders_profile_feedback_is_a_transient_brand_toast():
    orders = (ROOT / "src/components/orders/OrdersPage.tsx").read_text()
    assert "'Sent on WhatsApp'" in orders
    assert "'Couldn’t send. Try again.'" in orders
    assert "window.setTimeout( () => setProfileAction( 'idle' ), 4000 )" in orders
    assert "profileAction === 'failed' ? 'alert' : 'status'" in orders
    assert "onClick={ () => setProfileAction( 'idle' ) }" in orders
    assert ".ord-profile-toast{" in orders
    assert "background:var(--public-brand-lime);color:var(--public-brand-green)" in orders
    assert "Profile update sent on WhatsApp." not in orders


def test_website_profile_template_uses_data_exchange_for_optional_prefill():
    templates = (ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py").read_text()
    sender = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text()
    media = (ROOT / "amplify/functions/shared/lambda_utils/template_media.py").read_text()
    f001 = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/subscribe_profile.py").read_text()
    flow_path = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/published/subscribe.json"

    # The original Meta template is edited in place, never swapped to a new name.
    # Meta's button action must be verified independently after its review.
    assert 'PROFILE_DETAILS = Template(name="service_details"' in templates
    assert '"service_details": SHARED_TEMPLATE_HEADER' in media
    assert '"wecare_profile_update_f001": SHARED_TEMPLATE_HEADER' not in media
    assert "WA_PROFILE_UPDATE_TEMPLATE" not in templates
    send = sender.split("def _customer_profile_update_template(", 1)[1].split("\ndef handler(", 1)[0]
    assert "action = {'flow_token': token}" in send
    assert "action['flow_action_data'] = subscribe_profile._screen_values(contact_row, phone)" in send
    assert "template = whatsapp_templates.PROFILE_DETAILS" in send
    assert "return handle_init(payload, flow_token, request_id)" in f001
    assert "values = _screen_values(row, session.phone)" in f001

    import json
    flow = json.loads(flow_path.read_text())
    screens = {screen["id"]: screen for screen in flow["screens"]}
    profile_form = next(c for c in screens["PROFILE"]["layout"]["children"] if c["type"] == "Form")
    address_form = next(c for c in screens["ADDRESS"]["layout"]["children"] if c["type"] == "Form")
    for field in ("full_name", "username", "company_name", "designation"):
        assert profile_form["init-values"][field] == "${data." + field + "}"
    for field in ("address_line1", "address_line2", "locality", "city", "state", "postal_code", "country"):
        assert address_form["init-values"][field] == "${data." + field + "}"
