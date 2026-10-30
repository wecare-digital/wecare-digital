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
        "Your address",
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


def test_create_form_does_not_submit_a_new_email_identity():
    source = _customer_source()
    create_start = source.index("const handleCreate")
    create_end = source.index("const handleEdit", create_start)
    create = source[create_start:create_end]

    assert "email: formEmail" not in create
    assert "Enter the linked WhatsApp phone number" in create
    assert "Enter the full name" in create
