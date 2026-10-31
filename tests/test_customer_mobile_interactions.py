"""Source-contract regression checks for customer WebView interactions and Collect editing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUSTOMERS = (ROOT / "src/pages/workspace/customers/index.tsx").read_text()
PAY = (ROOT / "src/components/workspace/pay/PayFlow.tsx").read_text()
CSS = (ROOT / "src/styles/workspace.css").read_text()


def test_native_country_picker_replaces_mouse_only_dropdown():
    assert 'select id="contact-country-code"' in CUSTOMERS
    assert 'aria-label="WhatsApp country calling code"' in CUSTOMERS
    assert 'COUNTRY_CODES.map(cc =>' in CUSTOMERS
    assert 'onMouseDown=' not in CUSTOMERS
    assert 'showCountryDropdown' not in CUSTOMERS
    assert 'countrySearch' not in CUSTOMERS
    assert '.contacts-country-code select' in CSS


def test_duplicate_preflight_and_backend_fallback_share_canonical_phone_key():
    assert "contactPhoneE164(formPhone, formCountryCode)" in CUSTOMERS
    assert "contactPhoneMatchKey(contactPhoneE164(phone, formCountryCode))" in CUSTOMERS
    preflight = CUSTOMERS[CUSTOMERS.index("const checkDuplicate"):CUSTOMERS.index("THE ONE ADDRESS PAYLOAD")]
    assert "findDuplicateContact(phone, email, excludeId)" in preflight
    assert "c.phone === fullPhone" not in preflight
    assert "result.failure.details?.existingContactId" in CUSTOMERS
    assert "api.getContact(existingId)" in CUSTOMERS


def test_edit_preserves_hidden_email_and_explains_backend_refusals():
    editor = CUSTOMERS[CUSTOMERS.index("const handleUpdate"):CUSTOMERS.index("// Archive is a distinct")]
    assert "api.updateContactResult(editingContact.contactId" in editor
    assert "result.failure.message" in editor
    assert "result.failure.status === 409" in editor
    assert "setFormError(message)" in editor
    assert "email: formEmail" not in editor
    assert "bsuid: formBsuid" not in editor
    assert "gstin: formGstin" not in editor
    assert CUSTOMERS.count("{duplicateContactCard}") == 2
    edit_modal = CUSTOMERS[CUSTOMERS.index("{showEditModal && editingContact && ("):]
    assert 'role="alert"' in edit_modal


def test_collect_customer_editor_mounts_above_tab_switch():
    render = PAY[PAY.index("const shellContent ="):PAY.index("/* CREATE INVOICE TAB")]
    assert render.index("{ editCust && (") < render.index("activeTab === 'customers'")
    assert "pf-customer-editor" in render
    assert "pf-modal-error" in render
    assert "Edit Customer" in render
    assert "Linked WhatsApp number" in render
    assert '<label>Email</label>' not in render
    edit = PAY[PAY.index("const saveCust ="):PAY.index("useEffect( () => {", PAY.index("const saveCust ="))]
    assert "api.updateContactResult" in edit
    assert "setCustError( message )" in edit
    assert "email: custForm.email" not in edit
    assert '.pf-customer-editor .pf-modal-error' in CSS
    assert 'env(safe-area-inset-bottom' in CSS
