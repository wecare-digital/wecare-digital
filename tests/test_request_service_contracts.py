from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/request_service_contracts.py"


def _load():
    spec = importlib.util.spec_from_file_location("request_service_contracts", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_five_request_services_use_single_order_contract():
    m = _load()
    assert set(m.REQUEST_SERVICE_CONTRACTS) == {
        "SUBMIT_REQUEST", "REQUEST_AMENDMENT", "DROP_DOCS", "VAULT", "REQUEST_PICKUP"
    }
    for contract in m.REQUEST_SERVICE_CONTRACTS.values():
        assert contract.requires_existing_order is True
        assert contract.one_payment_one_fulfillment is True
        assert contract.catalog_visible is False
        assert contract.pay_template == "wecare_whatapp_native_pay_template"
        assert contract.invoice_template == "wecare_default_invoice_image_template"
        assert contract.order_details_thumbnail_key.endswith(
            "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
        )


def test_vault_is_secure_download_not_meta_flow():
    m = _load()
    vault = m.REQUEST_SERVICE_CONTRACTS["VAULT"]
    assert vault.fulfillment_kind == "secure_download"
    assert vault.flow_capability == ""

    flow_backed = {
        code for code, contract in m.REQUEST_SERVICE_CONTRACTS.items()
        if contract.fulfillment_kind == "flow"
    }
    assert flow_backed == {
        "SUBMIT_REQUEST", "REQUEST_AMENDMENT", "DROP_DOCS", "REQUEST_PICKUP"
    }


def test_vault_and_drop_docs_keep_the_special_pricing_contract_only():
    m = _load()
    special = {
        code for code, contract in m.REQUEST_SERVICE_CONTRACTS.items()
        if contract.supply_gst_bps or contract.express_paise
    }
    assert special == {"DROP_DOCS", "VAULT"}
    for code in special:
        assert m.REQUEST_SERVICE_CONTRACTS[code].supply_gst_bps == 1800
        assert m.REQUEST_SERVICE_CONTRACTS[code].express_paise == 2500


def test_browser_contract_mirrors_backend_stable_ids():
    m = _load()
    source = (ROOT / "src/config/requestServiceContracts.ts").read_text()
    for contract in m.REQUEST_SERVICE_CONTRACTS.values():
        assert contract.service_code in source
        assert contract.product_id in source
        assert contract.sku in source
        assert contract.fulfillment_kind in source
        if contract.flow_capability:
            assert contract.flow_capability in source


def test_payment_binding_contains_no_public_request_id():
    m = _load()
    binding = m.payment_binding("VAULT", "WD-ORD-82K4M7")
    assert binding["selectedOrderNumber"] == "WD-ORD-82K4M7"
    assert binding["serviceCode"] == "VAULT"
    assert binding["fulfillmentKind"] == "secure_download"
    assert binding["flowCapability"] == ""
    assert "requestId" not in binding
    assert all("WD-REQ-" not in str(value) for value in binding.values())



def test_checkout_public_boundary_is_ids_only_and_server_verifies_order():
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    start = source.index("def _request_service_start")
    end = source.index("\ndef _create(", start)
    block = source[start:end]
    assert '"serviceCode"' in block
    assert '"selectedOrderNumber"' in block
    assert "ORDER_NUMBER_PREFIX + selected_order_number" in block
    assert "customerId" in block
    assert "payment_status.CAPTURED" in block
    assert "verified_service_context=verified_context" in block
    assert "SERVICE_REQUIRES_SECURE_FILE" in block
    assert 'body.get("price")' not in block
    assert 'body.get("amount")' not in block
    assert 'body.get("customerId")' not in block
    assert 'body.get("orderId")' not in block
    assert "WD-REQ-" not in block


def test_native_request_payment_order_details_are_not_meta_catalog_items():
    source = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text()
    start = source.index("def _cart_order_details")
    end = source.index("\ndef _native_invoice_lines", start)
    block = source[start:end]
    # ProductsTable is pricing authority upstream, but the Meta payment wire is non-catalog:
    # item name/amount/quantity only. Outbound adds the India compliance fields.
    assert '"catalog_id"' not in block
    assert '"retailer_id"' not in block
    assert '"name": name[:60]' in block
    assert '"amount": {"value": unit_paise, "offset": 100}' in block

    outbound = (ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py").read_text()
    assert "country_of_origin" in outbound
    assert "business_identity.meta_importer_fields()" in outbound


def test_single_order_capture_reuses_number_instead_of_reserving_another():
    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/order_creation.py").read_text()
    start = source.index('if attempt.get("singleOrderService") is True:')
    end = source.index("# ── ordinary purchase", start)
    block = source[start:end]
    assert "selectedOrderId" in block
    assert "selectedOrderNumber" in block
    assert "claim_order_for_payment" in block
    assert "record_order_number_on_claim" in block
    assert "reserve_public_order_number" not in block
    assert "new_order_id" not in block


def test_single_order_finalization_appends_activity_without_putting_new_order():
    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/finalization.py").read_text()
    start = source.index("def _accept_paid_single_order_service")
    end = source.index("\ndef accept_paid", start)
    block = source[start:end]
    assert "serviceActivities" in block
    assert "serviceActivityPaymentIds" in block
    assert "orders.update_item" in block
    assert "orders.put_item" not in block
    assert "ORDER_FINALIZED" in block


def test_legacy_request_activator_cannot_mint_request_for_single_order_payment():
    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_request_store.py").read_text()
    marker = 'if line.get("singleOrder") is True:'
    assert marker in source
    block = source[source.index(marker):source.index(marker) + 500]
    assert "NOT_A_SERVICE_ORDER" in block


def test_request_services_are_structurally_excluded_from_meta_catalog():
    source = (ROOT / "amplify/functions/ecommerce/meta-catalog-sync/handler.py").read_text()
    assert "request_service_contracts.REQUEST_SERVICE_PRODUCT_IDS" in source
    product_guard = source.index("if product_id in request_service_contracts.REQUEST_SERVICE_PRODUCT_IDS:")
    meta_guard = source.index('if item.get("metaEnabled") is not True:', product_guard)
    assert product_guard < meta_guard


def test_single_order_vault_never_enters_flow_wiring():
    source = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py").read_text()
    start = source.index("if line.get('singleOrder') is True:")
    block = source[start:start + 5000]
    secure = block.index("if contract.fulfillment_kind == 'secure_download':")
    refused = block.index("VAULT_SECURE_FILE_BINDING_REQUIRED", secure)
    launch = block.index("return launch_single_order_service(", refused)
    assert secure < refused < launch
    assert "SERVICE_FLOW_PENDING_WIRING" not in block


def test_customer_flow_hint_occurs_after_confirmed_invoice_not_during_activation_hint():
    dispatch = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_request_dispatch.py").read_text()
    assert "preparePaidSubmitRequest" not in dispatch

    webhook = (ROOT / "amplify/functions/payments/razorpay-webhook/handler.py").read_text()
    call = webhook.index("invoice_delivered = _post_payment_handler")
    guard = webhook.index("if invoice_delivered and reference_id:", call)
    send = webhook.index("_dispatch_post_invoice_service_flow(", guard)
    assert call < guard < send


def test_browser_skips_legacy_intent_and_cart_for_request_services():
    source = (ROOT / "src/components/ServiceBuyBox.tsx").read_text()
    assert "fetchCustomerOrders" in source
    assert "startRequestService" in source
    assert "postRequestIntent" not in source
    assert "setServiceLine" not in source
    assert "CHECKOUT_PATH" not in source
    assert "Payment request sent to your registered WhatsApp number." in source


def test_vault_browser_uses_owner_bound_website_cart_and_native_whatsapp():
    source = (ROOT / "src/components/get/GetPage.tsx").read_text()
    assert "requestMySecureFilePayment" in source
    assert "Sending to WhatsApp…" in source
    assert "registered WhatsApp number" in source
    assert "postRequestIntent(" in source
    assert "session.accessToken, 'VAULT', undefined, file.fileId" in source
    assert "setServiceLine( service.variantId, response.intent.intentId, vaultLinePrice )" in source
    assert "serviceIntentFor( lineItems ) === response.intent.intentId" in source
    assert "Add 24-hour renewal to cart" in source
    assert "window.location.assign( '/checkout/' )" in source
    assert "router.push" not in source
    assert "sf-note-bad" not in source


def test_vault_uses_one_customer_sign_in_surface_and_auth_card():
    source = (ROOT / "src/components/get/GetPage.tsx").read_text()
    assert "/auth?return=" in source
    assert "requestOtp" not in source
    assert "submitOtp" not in source
    assert "Opening your Vault…" in source
    assert "border-top:4px solid var(--public-brand-lime)" in source
    for retired_css in (".sf-label{", ".sf-hint{", ".sf-input{", ".sf-resend{", ".sf-quiet{"):
        assert retired_css not in source


def test_exact_file_vault_design_prioritizes_secure_status_without_changing_payment_gates():
    page = (ROOT / "src/components/get/GetPage.tsx").read_text()
    route = (ROOT / "src/pages/vault.tsx").read_text()

    # One purpose-specific hero and accessible document hierarchy, inside the
    # existing shared chrome. No new public file browsing surface.
    assert 'frame="Your secure"' in page
    assert "word: 'document'" in page
    assert "mobileFoundation\n                compact" in page
    assert '<h2 className="sf-card-title">Your file access</h2>' in page
    assert '<h3 className="sf-file-name">{ file.displayName }</h3>' in page
    assert "fileStatusLabel( state )" in page
    assert "case 'OPEN': return 'Ready to download'" in page
    assert "case 'READY': return 'Payment verified'" in page
    assert "case 'PAID_UNVERIFIED': return 'Verifying payment'" in page
    assert "case 'EXPIRED': return 'Access expired'" in page
    assert "sf-download-button" in page
    assert "Download securely" in page
    assert "sf-choice-tag" in page
    assert "Estimated total:" in page
    assert "Final total and tax are calculated at checkout." in page

    # A cosmetic treatment must not accidentally turn a paid-but-unverified
    # entitlement into a download, or generate a new payment while confirming.
    assert "const isPaid = state === 'OPEN' || state === 'READY';" in page
    assert "state === 'PAID_UNVERIFIED' ? (" in page
    assert "Do not pay again." in page
    assert "api.redeemSecureFileDownload( file.fileId, accessId )" in page
    assert "requestMySecureFilePayment( file.fileId )" in page
    assert "postRequestIntent(" in page
    assert "targetFileId" in route and "<GetPage targetFileId={ targetFileId } />" in route
    assert "noindex" in page
    assert "VAULT_AUTH_RETURN_FILE_KEY" in route


def test_public_vault_inherits_the_shared_public_chrome():
    app = (ROOT / "src/pages/_app.tsx").read_text()
    customer_routes = app[
        app.index("const CUSTOMER_SERVICE_ROUTES"):
        app.index("export default function App")
    ]
    public_branch = app[app.index("if ( isPublic )"):]
    assert "'/vault'" in customer_routes
    for shared in ("<Header />", "<PublicShare />", "<Footer />", "<SupportWidget />"):
        assert shared in public_branch


def test_workspace_vault_upload_uses_document_intake_not_retired_direct_upload():
    page = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()
    client = (ROOT / "src/api/client.ts").read_text()
    for call in (
        "initDocumentUpload",
        "uploadDocumentBytes",
        "confirmDocumentUpload",
        "publishDocumentToVault",
    ):
        assert call in page
    for retired in (
        "initSecureUpload",
        "uploadSecureFileBytes",
        "confirmSecureUpload",
    ):
        assert retired not in page
        assert f"function {retired}" not in client
    assert "Direct Vault upload is retired." in page
    assert "@media(max-width:760px)" in page
    assert ".sf-field{min-width:0}\\n" not in page


def test_customer_vault_payment_reproves_file_and_uses_native_payment_sender():
    source = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text()
    customer = source[source.index("def _customer_request_payment"):
                      source.index("\ndef _admin_request_payment")]
    native = source[source.index("def _start_native_vault_payment"):
                    source.index("\ndef _customer_request_payment")]
    assert "_owned_active_file(file_id, identity)" in customer
    assert 'state in ("OPEN", "READY")' in customer
    assert 'state == "PAID_UNVERIFIED"' in customer
    assert '"action": "sendPayment"' in native
    assert '"ownerCustomerId": str(item["ownerCustomerId"])' in native
    assert '"ownerPhone": str(item["ownerPhone"])' in native
    assert "no website cart" in native
    assert "no Meta Flow" in native


def test_secure_files_provisioner_pins_native_vault_payment_invoke():
    source = (ROOT / "scripts/provision_secure_files_api.py").read_text()
    assert 'VAULT_PAYMENT_FUNCTION = "wecare-whatsapp-business-api"' in source
    assert 'function:{VAULT_PAYMENT_FUNCTION}:*' in source
    assert '"VAULT_PAYMENT_FUNCTION": f"{VAULT_PAYMENT_FUNCTION}:live"' in source


def test_vault_payment_bootstraps_authenticated_customer_contact_before_send():
    profile = (ROOT / "amplify/functions/auth/customer-profile/handler.py").read_text()
    assert "bootstrap_only = creating and not body" in profile
    assert "if creating and not bootstrap_only:" in profile
    assert "if creating and not bootstrap_only and address is None:" in profile

    api = (ROOT / "src/api/client.ts").read_text()
    assert "ensureCustomerPaymentIdentity" in api
    assert "/customer/profile" in api

    page = (ROOT / "src/components/get/GetPage.tsx").read_text()
    ensure = page.index("ensureCustomerPaymentIdentity")
    pay = page.index("requestMySecureFilePayment", ensure)
    assert ensure < pay


def test_native_vault_sender_tolerates_fresh_contact_index_lag_without_creating_identity():
    source = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py"
    ).read_text()
    start = source.index("def _send_native_payment")
    block = source[start:start + 6500]
    assert "contact_store.find_by_phone" in block
    assert "uuid.uuid5" in block
    assert "ConsistentRead=True" in block
    assert "customer-profile owns creation/linking" in block
    assert "contacts.put_item" not in block


def test_whatsapp_identity_bridge_tolerates_fresh_contact_index_lag():
    source = (
        ROOT
        / "amplify/functions/auth/customer-registration/handler.py"
    ).read_text()
    start = source.index("def _ensure_whatsapp_identity")
    block = source[start:start + 7000]
    assert "contact_store.find_by_phone" in block
    assert "strongly consistent exact-id fallback" in block
    assert 'Key={"id": contact_id}, ConsistentRead=True' in block
    assert "contact_store.is_live(direct)" in block
    assert "contact_store.canonical_phone(direct.get(\"phone\")) == phone" in block
    assert "_cognito_user_for_sub(existing_owner, phone)" in block


def test_fresh_capture_evidence_finalizes_even_when_existing_order_is_reused():
    source = (ROOT / "amplify/functions/payments/razorpay-webhook/handler.py").read_text()
    native = source.index("# Product/cart native checkout carries the frozen cart snapshot")
    block = source[native:native + 7000]
    assert "outcome.verified_captured_paise > 0 and outcome.provider_payment_id" in block
    assert "outcome.outcome == order_creation.ORDER_CREATED" not in block.split(
        "elif attempt.get('finalizationStage')", 1
    )[0]


def test_workspace_vault_hides_legacy_rows_and_moves_them_to_logs():
    handler = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text()
    assert "WORKSPACE_VAULT_RECORD_VERSION = 2" in handler
    assert '"workspaceRecordVersion": WORKSPACE_VAULT_RECORD_VERSION' in handler
    assert 'view = str(params.get("view") or "documents")' in handler
    assert 'if view == "documents":' in handler
    assert 'item.get("status") == "active"' in handler
    assert 'int(item.get("workspaceRecordVersion") or 0) >= WORKSPACE_VAULT_RECORD_VERSION' in handler
    assert 'if view == "logs":' in handler
    assert '"storageOriginalPresent"' in handler
    assert "_storage_object_present" in handler


def test_workspace_vault_removes_document_type_and_shows_real_uploader():
    page = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()
    assert "Document type" not in page
    assert "setDocumentType" not in page
    assert "type: 'other'" in page
    assert "'Uploaded by'" in page
    assert "row.uploadedBy" in page
    assert "'Tag'" not in page


def test_vault_logs_show_storage_truth_and_real_send_actors():
    logs = (ROOT / "src/components/workspace/service/VaultLogs.tsx").read_text()
    client = (ROOT / "src/api/client.ts").read_text()
    handler = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text()

    assert "listSecureFileLogs" in logs
    assert "S3 source" in logs
    assert "S3 delivery" in logs
    assert "lastPaymentRequestedBy" in logs
    assert "lastAccessSentBy" in logs
    assert "view: 'logs'" in client

    for field in (
        "lastPaymentRequestedBy",
        "lastPaymentRequestedAt",
        "lastPaymentRequestOutcome",
        "lastAccessSentBy",
        "lastAccessSentAt",
        "lastAccessSendOutcome",
    ):
        assert field in handler


def test_vault_logs_are_fresh_and_missing_object_probe_permission_is_durable():
    logs = (ROOT / "src/components/workspace/service/VaultLogs.tsx").read_text()
    client = (ROOT / "src/api/client.ts").read_text()
    provisioner = (ROOT / "scripts/provision_secure_files_api.py").read_text()

    assert "window.addEventListener( 'focus', refresh )" in logs
    assert "document.addEventListener( 'visibilitychange', refresh )" in logs
    assert "window.removeEventListener( 'focus', refresh )" in logs
    assert "document.removeEventListener( 'visibilitychange', refresh )" in logs

    secure_listing = client[client.index("export async function listSecureFiles"):
                            client.index("/** Revoke rather than delete")]
    # Two list endpoints plus a third file-bound read-only delivery-status endpoint.
    assert secure_listing.count("cache: 'no-store'") == 3
    assert "readVaultMessageDeliveryLog" in secure_listing

    assert '"Sid": "SecureBucketExistenceProbe"' in provisioner
    assert '"Action": ["s3:ListBucket"]' in provisioner
    assert '"s3:prefix": [f"{SECURE_PREFIX}*"]' in provisioner
    assert '"Resource": f"arn:aws:s3:::{BUCKET}"' in provisioner


def test_service_workspace_shows_all_services_without_reopening_retired_customer_pages():
    page = (ROOT / "src/pages/workspace/service/index.tsx").read_text()
    routes = (ROOT / "src/lib/serviceWorkspaceRoutes.ts").read_text()
    assert "SERVICE_WORKSPACE_VIEWS.map" in page
    for slug in ("submit-request", "request-amendment", "drop-docs",
                 "vault", "shipments", "contribute"):
        assert slug in routes
    assert "VaultLogs" in page and "SecureFiles" in page
    assert "Documents" in page and "<Documents" in page
    assert "serviceLedger('VAULT')" in page
    assert "serviceLedger('DROP_DOCS')" in page
    assert "serviceLedger('REQUEST_PICKUP')" in page
    assert 'href="/orders/' not in page
    assert "/workspace/commerce?view=orders" in page
    # Exposing a staff-priced operations view is NOT reopening the five
    # retired standalone public service pages or launching an unpaid Flow.
    assert "api.requestSecureFilePayment(" not in page
    assert "startRequestService(" not in page


def test_manual_workspace_vault_offer_precedes_customer_payment():
    page = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()
    documents = (ROOT / "src/components/workspace/service/Documents.tsx").read_text()
    api = (ROOT / "src/api/client.ts").read_text()
    handler = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text()
    catalog = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py").read_text()
    registry = (ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py").read_text()
    media = (ROOT / "amplify/functions/shared/lambda_utils/template_media.py").read_text()

    assert "wecare_vault_request_ready" in page
    assert "Unlock Vault" in page
    preview = (ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx").read_text()
    assert preview.index("name: 'Vault ready'") < preview.index("name: 'Review & Pay'")
    assert preview.index("name: 'Order updates'") < preview.index("name: 'Paid invoice'")
    assert preview.index("name: 'Paid invoice'") < preview.index("name: 'Access Vault'")
    assert page.count("api.sendSecureFileOffer(") == 1
    assert documents.count("api.sendSecureFileOffer(") == 3
    # Direct staff payment is an explicitly confirmed action, never automatic on upload.
    assert "api.requestSecureFilePayment( target.fileId )" in page
    assert "Send Review & Pay now" in page
    assert "Send payment request" in page
    upload = page.split("const handleUpload = async () => {", 1)[1].split("const handleRevoke", 1)[0]
    assert "requestSecureFilePayment" not in upload
    assert "api.requestSecureFilePayment(" not in documents
    assert "secureFileAction( fileId, 'send-offer' )" in api
    assert "secureFileAction( fileId, 'request-payment' )" in api
    assert 'tail[1] == "send-offer"' in handler
    assert '"action": "sendVaultOffer"' in handler
    assert "if action == 'sendVaultOffer':" in catalog
    assert "return _send_offer(event, client, db, keys, contacts, now)" in catalog
    assert "def _unlock(" in catalog and "OFFER_FILE_PREFIX" in catalog
    assert "whatsappMessageId" in catalog
    assert 'VAULT_OFFER = Template(name="wecare_vault_request_ready"' in registry
    assert "whatsapp-header.png" in media
    assert "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png" in media


def test_vault_offer_preflight_uses_approved_template_and_idempotent_send():
    catalog = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py").read_text()
    outbound = (ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py").read_text()
    delivery = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py").read_text()
    ui = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()
    template_registry = (ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py").read_text()

    assert "'wecare_vault_request_ready': '29124703577146420'" in catalog
    assert "idempotencyKey='vault-offer:' + token" in catalog
    assert "'offerTemplate': whatsapp_templates.VAULT_OFFER.name" in catalog
    assert "if not _offer_whatsapp_message_id(response):" in catalog
    assert "whatsappMessageId=:wamid" in catalog
    assert "if action == 'sendVaultOffer':" in catalog
    assert "if action in ('sendPayment', 'sendOffer'):" in catalog
    assert "_claim_keyed_outbound_send(message_id, request_id)" in outbound
    assert "status = 'ACCEPTED' if whatsapp_message_id else 'SEND_UNKNOWN'" in delivery
    assert "_POST_RECEIPT_ACCESS_GAP_SECONDS = 4" in delivery
    assert "Send Unlock Vault now" in ui
    assert "Send Unlock Vault on WhatsApp?" in ui
    assert "validOfferBodyText" in ui
    assert "api.sendSecureFileOffer( target.fileId, variable )" in ui
    assert "Manual Vault stage 1" in template_registry


def test_workspace_vault_shows_download_template_variable_mapping():
    page = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()
    preview = (ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx").read_text()
    assert "wecare_default_download" in preview
    assert "URL {'{{1}}'}" in preview
    assert "offerBodyText" in page
    assert "Body {'{{1}}'}" in preview
    assert "handleCopyId( reviewFile )" in page
    assert "Server-created file ID after publish" in preview


def test_request_services_remain_visible_in_public_menu_but_use_orders_only():
    # Preserve every Request menu label and icon. The old marketing pages are now
    # retired and 301 to Orders; only exact-file Vault still needs a noindex route.
    header = (ROOT / "src/components/Header.tsx").read_text()
    menu = header.split("const COLUMNS: NavColumn[] = [", 1)[1].split(
        "\nconst flattenMenuLinks", 1
    )[0]
    assert "heading: 'Request'" in menu
    for label in (
        "Orders", "Submit Request", "Request Amendment", "Drop Docs",
        "Vault", "Shipments", "Track", "Pickup Request", "Leave Review", "Subscribe",
    ):
        assert f"label: '{label}'" in menu
    # No request/tracking item opens a standalone public service page.
    # Existing links are caught by explicit 301 rules without touching service APIs.
    for label in ("Submit Request", "Request Amendment", "Drop Docs",
                  "Vault", "Track", "Pickup Request"):
        assert f"label: '{label}', href: '/orders/'" in menu
    assert menu.count("href: '/orders/'") == 7  # Orders row plus six service links
    for route in (
        "/submit-request/", "/request-amendment/", "/drop-docs/",
        "/vault/", "/shipments/track/", "/request-pickup/",
    ):
        assert f"href: '{route}'" not in menu
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in header
    assert "const MENU_SEARCH_LINKS = flattenMenuLinks();" in header

    app = (ROOT / "src/pages/_app.tsx").read_text()
    service_routes = app.split("const CUSTOMER_SERVICE_ROUTES = new Set( [", 1)[1].split(
        "] );", 1
    )[0]
    assert "'/vault'" in service_routes
    for path in ("/submit-request", "/request-amendment", "/drop-docs",
                 "/request-pickup", "/shipments/track"):
        assert f"'{path}'" not in service_routes
    assert "'noindex, nofollow'" in app


def test_drop_docs_web_snapshot_price_matches_live_product_authority():
    # ProductsTable verified on 2026-10-30: variant RDD9P3M7.priceMinor = 19900.
    shop = (ROOT / "src/content/shopProducts.ts").read_text()
    snapshot = (ROOT / "src/content/catalogSnapshot.ts").read_text()
    listing = next(line for line in shop.splitlines() if "sku:'RDD9P3M7'" in line)
    assert "formattedPrice:'₹199.00'" in listing
    product = snapshot.split("name:'Request · Drop Docs', slug:'drop-docs',", 1)[1].split(
        "\n  },", 1
    )[0]
    assert "formattedPrice:'₹199.00', price:'199.00'" in product


def test_pickup_payment_requires_matching_meta_asset_release_on_all_rails():
    launcher = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/service_flow_launcher.py").read_text()
    assert '"REQUEST_PICKUP": LaunchSpec(' in launcher
    assert 'enabled=pickup_activation.enabled(),' in launcher
    assert 'blocked_outcome="PICKUP_FLOW_ASSET_MISMATCH"' in launcher

    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_requests.py").read_text()
    preflight = source.split("def checkout_preflight(", 1)[1].split(
        "\ndef native_service_line_paise(", 1
    )[0]
    assert "if line.kind == REQUEST_PICKUP and not pickup_activation.enabled():" in preflight
    assert "return 409, refusal(SERVICE_NOT_PAYABLE)" in preflight
    assert preflight.index("if line.kind == REQUEST_PICKUP and not pickup_activation.enabled():") < preflight.index(
        "if _single_order_context("
    )

    buybox = (ROOT / "src/components/ServiceBuyBox.tsx").read_text()
    assert "if ( service.kind === 'REQUEST_PICKUP' && !PICKUP_CHECKOUT_ACTIVE )" in buybox
    assert "Pickup checkout is temporarily unavailable" in buybox


def test_workspace_vault_exposes_authoritative_private_storage_location():
    handler = (ROOT / "amplify/functions/core/secure-files/handler.py").read_text()
    client = (ROOT / "src/api/client.ts").read_text()
    page = (ROOT / "src/components/workspace/service/SecureFiles.tsx").read_text()

    assert '"bucket": BUCKET' in handler
    assert '"sourcePrefix": DROPDOCS_PREFIX' in handler
    assert '"deliveryPrefix": DELIVER_PREFIX' in handler
    assert "export interface SecureFileStorage" in client
    assert "storage?: SecureFileStorage" in client

    # Source prefixes stay server-only; the client sees just the system UUID filename.
    preview = (ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx").read_text()
    assert "wecare-digital-<uuid>" in preview
    assert "Generated stored filename" in preview
    assert "s3Key={ " not in page
    assert "storage.sourcePrefix" not in page
