"""Source contracts for the staff customer form derived from F001 Subscribe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _customer_source() -> str:
    return (ROOT / "src/pages/workspace/customers/index.tsx").read_text()


def test_staff_customer_form_matches_subscribe_profile_fields():
    source = _customer_source()
    start = source.index("const renderContactForm")
    end = source.index("\n\n  return (", start)
    form = source[start:end]

    for label in (
        "Full name *",
        "Linked WhatsApp number *",
        "WhatsApp username",
        "Organization",
        "Job title",
        "Address",
    ):
        assert label in form

    assert "contact-email" not in form
    assert "Contact &amp; system identity" not in form


def test_staff_customer_form_uses_only_canonical_subscribe_address_fields():
    source = _customer_source()
    address_source = (ROOT / "src/lib/address-format.ts").read_text()

    for label in (
        "Street address",
        "Apartment / suite / unit",
        "Landmark / neighborhood",
        "City",
        "State / region",
        "Postal code",
        "Country",
    ):
        assert label in address_source

    assert "ADDRESS_FIELDS.map" in source
    assert "addressComplete(formAddress)" in source


def test_duplicate_whatsapp_customer_becomes_an_actionable_existing_record():
    source = _customer_source()

    assert "checkDuplicate(formPhone, '')" in source
    assert "resolveDuplicateContact(formPhone, '')" in source
    assert "Open existing customer" in source
    assert "Use for payment" in source
    assert "Restore customer" in source
    assert "HTTP 409" not in source
    assert "This WhatsApp customer already exists" in source
    assert "Search by number to open it" not in source
    assert "setSearchQuery(fullPhone)" in source
    assert "setShowModal(false)" in source


def test_create_form_does_not_submit_a_new_email_identity():
    source = _customer_source()
    create_start = source.index("const handleCreate")
    create_end = source.index("const handleEdit", create_start)
    create = source[create_start:create_end]

    assert "email: formEmail" not in create
    assert "Enter the linked WhatsApp phone number" in create
    assert "Enter the full name" in create


def test_customer_modal_phone_uses_one_auth_style_combined_field():
    source = _customer_source()
    css = (ROOT / "src/styles/workspace.css").read_text()

    form_start = source.index("const renderContactForm")
    form_end = source.index("const duplicateContactCard", form_start)
    form = source[form_start:form_end]

    assert 'className="contacts-phone-control"' in form
    assert 'id="contact-country-code"' in form
    assert 'id="contact-phone"' in form
    assert "F001 Subscribe profile" not in form

    phone_start = css.index(".workspace-shell .contacts-auth-modal .contacts-phone-control {")
    phone_css = css[phone_start:phone_start + 2400]
    assert "border-bottom: 1px solid var(--public-hairline" in phone_css
    assert "border-radius: 0" in phone_css
    assert "background: transparent" in phone_css
    assert ".contacts-phone-control:focus-within" in phone_css
    assert "border: 0 !important" in phone_css
