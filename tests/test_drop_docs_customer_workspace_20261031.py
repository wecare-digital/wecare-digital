"""Drop Docs is a paid CUSTOMER upload, and Vault is STAFF upload.

Static release contracts, no customer data or live payments accessed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def src(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_drop_docs_workspace_never_offers_staff_upload():
    page = src("src/pages/workspace/service/index.tsx")
    customer = src("src/components/workspace/service/CustomerDropDocs.tsx")
    vault = src("src/components/workspace/service/SecureFiles.tsx")

    assert "return <CustomerDropDocs />" in page
    assert "return <SecureFiles signOut={signOut} user={user} embedded />" in page
    assert "Customer uploads" in page
    assert "Upload documents" not in page
    assert "Open staff document uploads" not in page
    assert "api.listDocuments({ source: 'flow' })" in customer
    assert "doc.dropDocsRequestId" in customer
    assert "doc.dropDocsPaymentAttemptId" in customer
    assert "maskedPhone(doc.customerPhone)" in customer
    for forbidden in (
        "initDocumentUpload(", "uploadDocumentBytes(", "confirmDocumentUpload(",
        "publishDocumentToVault(", "sendSecureFileOffer(",
    ):
        assert forbidden not in customer
    assert "api.initDocumentUpload(" in vault
    assert "api.publishDocumentToVault(" in vault


def test_customer_flow_is_the_secure_paid_issuer():
    flow = src("amplify/functions/messaging/whatsapp-business-api/flows/drop_docs.py")
    launcher = src("amplify/functions/messaging/whatsapp-business-api/flows/paid_drop_docs.py")
    assert '"sourceType": "flow"' in flow
    assert '"dropDocsRequestId":' in flow
    assert '"dropDocsPaymentAttemptId":' in flow
    assert "flow_sessions.record_session(" in launcher
    assert "service_request_key=request_key" in launcher
    assert "drop_docs_flow_send_fields(token)" in launcher


def test_live_server_owns_amount_template_ids_images_and_sequence():
    customer = src("src/components/workspace/service/CustomerDropDocs.tsx")
    pricing = src("amplify/functions/shared/lambda_utils/ecommerce/service_pricing_native.py")
    assert "fetchServicePrices()" in customer
    assert "breakdown.totalPayablePaise" in customer
    assert "price.paise" in customer
    assert "templates?.templateIds" in customer
    assert "PaymentTemplateMedia" in customer
    assert "templates={templates}" in customer
    assert "Registered template IDs are read-only audit metadata" in customer
    assert "not a promised number of seconds" in customer
    labels = (
        "Review & Pay", "Order status: processing", "GST invoice image",
        "Customer uploads documents (F003)",
    )
    assert all(x in customer for x in labels)
    assert (customer.index(labels[0]) < customer.index(labels[1]) <
            customer.index(labels[2]) < customer.index(labels[3]))
    for x in ("templateIds", "headerImage", "itemThumbnail"):
        assert x in pricing
    for x in ("WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png", "₹199", "₹49"):
        assert x not in customer


def test_customer_upload_not_relabelled_as_vault_delivery():
    page = src("src/pages/workspace/service/index.tsx")
    assert "'drop-docs': 'Drop Docs'" in page
    assert "if (active === 'drop-docs')" in page
    assert "if (active === 'vault')" in page
    assert "router.replace('/workspace/service?view=vault')" in src("src/pages/workspace/docs/index.tsx")
    assert "customer-upload F003" in page
    assert "staff file intake" in page
