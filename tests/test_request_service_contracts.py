from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/request_service_contracts.py"


def _load():
    spec = importlib.util.spec_from_file_location("request_service_contracts", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_all_five_request_services_use_single_order_contract():
    m = _load()
    assert set(m.REQUEST_SERVICE_CONTRACTS) == {
        "SUBMIT_REQUEST", "REQUEST_AMENDMENT", "DROP_DOCS", "VAULT", "REQUEST_PICKUP"
    }
    for contract in m.REQUEST_SERVICE_CONTRACTS.values():
        assert contract.requires_existing_order is True
        assert contract.one_payment_one_flow is True
        assert contract.pay_template == "wecare_whatapp_native_pay_template"
        assert contract.invoice_template == "wecare_default_invoice_image_template"
        assert contract.order_details_thumbnail_key.endswith(
            "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
        )


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
        assert contract.flow_capability in source


def test_payment_binding_contains_no_public_request_id():
    m = _load()
    binding = m.payment_binding("VAULT", "WD-ORD-82K4M7")
    assert binding["selectedOrderNumber"] == "WD-ORD-82K4M7"
    assert binding["serviceCode"] == "VAULT"
    assert "requestId" not in binding
    assert all("WD-REQ-" not in str(value) for value in binding.values())
