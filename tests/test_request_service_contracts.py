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
    flow = block.index("SERVICE_FLOW_PENDING_WIRING", refused)
    assert secure < refused < flow


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


def test_vault_browser_uses_native_whatsapp_and_never_seeds_cart():
    source = (ROOT / "src/components/get/GetPage.tsx").read_text()
    assert "requestMySecureFilePayment" in source
    assert "Sending to WhatsApp…" in source
    assert "registered WhatsApp number" in source
    assert "postRequestIntent" not in source
    assert "setServiceLine" not in source
    assert "CHECKOUT_PATH" not in source
    assert "router.push" not in source
    assert "Review this document in your cart" not in source
    assert "sf-note-bad" not in source


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


def test_fresh_capture_evidence_finalizes_even_when_existing_order_is_reused():
    source = (ROOT / "amplify/functions/payments/razorpay-webhook/handler.py").read_text()
    native = source.index("# Product/cart native checkout carries the frozen cart snapshot")
    block = source[native:native + 7000]
    assert "outcome.verified_captured_paise > 0 and outcome.provider_payment_id" in block
    assert "outcome.outcome == order_creation.ORDER_CREATED" not in block.split(
        "elif attempt.get('finalizationStage')", 1
    )[0]
