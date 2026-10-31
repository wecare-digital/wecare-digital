"""Contract tests for the full staff Service workspace.

Only pure AWS-native price resolvers are exercised; every catalog row is a
synthetic fixture. No production payment, WhatsApp, DynamoDB or S3 calls.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils import template_media  # noqa: E402
from lambda_utils.ecommerce import (  # noqa: E402
    blog_contribution, service_pricing_native, service_requests,
)


def _catalog():
    rows = {variant: {"priceMinor": 9900, "currency": "INR", "status": "active"}
            for variant in service_requests.SERVICE_VARIANT_BY_KIND.values()}
    rows[service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]]["priceMinor"] = 4900
    rows[service_requests.SERVICE_VARIANT_BY_KIND[service_requests.DROP_DOCS]]["priceMinor"] = 19900
    rows[service_requests.SERVICE_VARIANT_BY_KIND[service_requests.REQUEST_AMENDMENT]]["priceMinor"] = 19900
    rows[service_requests.SERVICE_VARIANT_BY_KIND[service_requests.REQUEST_PICKUP]]["priceMinor"] = 65000
    rows[service_pricing_native.SHIPMENT_TRACK_SKU] = {
        "priceMinor": 4900, "currency": "INR", "status": "active"}
    for variant in blog_contribution.CONTRIBUTION_VARIANT_IDS:
        rows[variant] = {"priceMinor": 25000, "currency": "INR", "status": "active"}
    return rows


def test_all_five_services_share_approved_media_but_not_fulfilment():
    products = _catalog()
    prices = service_pricing_native.resolve_all(products.get)
    deliveries = {
        "submit-request": "submit_request_flow",
        "request-amendment": "request_amendment_flow",
        "drop-docs": "_dropdoc_flow",
        "vault": "wecare_default_download",
        "request-pickup": "pickup_request_flow",
    }
    assert prices["currency"] == "INR"
    for slug, delivery in deliveries.items():
        row = prices["prices"][slug]
        assert row["available"] is True
        template = row["templates"]
        assert template["nativePay"] == "wecare_whatapp_native_pay_template"
        assert template["delivery"] == delivery
        assert template["headerImage"] == template_media.PAYMENT_TEMPLATE_HEADER
        assert template["itemThumbnail"] == template_media.DEFAULT_ORDER_ITEM_THUMBNAIL
        assert template["headerImage"] != template["itemThumbnail"]
        assert template["orderStatusStates"] == ["processing", "completed"]
    assert prices["prices"]["vault"]["templates"]["delivery"] != prices["prices"]["drop-docs"]["templates"]["delivery"]


def test_track_is_separate_priced_product_not_a_sixth_request_service():
    assert service_pricing_native.SHIPMENT_TRACK_SKU == "SHT8M5P3"
    assert "shipments-track" not in service_requests.SERVICE_KIND_BY_SLUG
    prices = service_pricing_native.resolve_all(_catalog().get)["prices"]
    assert prices["shipments-track"] == {"available": True, "paise": 4900}
    assert "templates" not in prices["shipments-track"]
    assert "breakdown" not in prices["shipments-track"]


def test_contribute_has_distinct_fee_exempt_contract_no_flow():
    prices = service_pricing_native.resolve_all(_catalog().get)["prices"]
    contribution = prices["contribute"]
    assert contribution["available"]
    assert contribution["paise"] == 25000
    assert "templates" not in contribution
    assert contribution["breakdown"]["totalPayablePaise"] == 25000
    assert contribution["breakdown"]["convenienceFeePaise"] == 0
    assert contribution["breakdown"]["supplyGstPaise"] == 0


def test_missing_track_does_not_hide_other_service_prices():
    products = _catalog()
    del products[service_pricing_native.SHIPMENT_TRACK_SKU]
    prices = service_pricing_native.resolve_all(products.get)["prices"]
    assert prices["shipments-track"] == {"available": False}
    assert prices["vault"]["available"] is True
    assert prices["drop-docs"]["available"] is True


def test_workspace_targets_are_distinct_and_read_only():
    page = (ROOT / "src/pages/workspace/service/index.tsx").read_text()
    pricing = (ROOT / "src/components/workspace/service/ServicePriceOverview.tsx").read_text()
    route = (ROOT / "src/lib/serviceWorkspaceRoutes.ts").read_text()
    pay = (ROOT / "src/pages/workspace/payments/index.tsx").read_text()
    for word in ("submit-request", "request-amendment", "drop-docs",
                 "vault", "shipments", "contribute"):
        assert word in route
    assert "serviceWorkspaceQuery(view, nextTab)" in page
    assert "if (tab === 'ledger') return serviceLedger('VAULT')" in page
    assert "return <Documents signOut={signOut} user={user} embedded />" in page
    assert "return <SecureFiles signOut={signOut} user={user} embedded />" in page
    assert "serviceLedger('DROP_DOCS')" in page
    assert "serviceLedger('SUBMIT_REQUEST')" in page
    assert "serviceLedger('REQUEST_AMENDMENT')" in page
    assert "serviceLedger('REQUEST_PICKUP')" in page
    assert "pricePanel('shipments-track')" in page
    assert "<ShipmentTrackingPanel />" in page
    tracking = (ROOT / "src/components/workspace/service/ShipmentTrackingPanel.tsx").read_text()
    assert "api.listOrders({limit: 150})" in tracking
    assert "api.getTrackingData(order.orderId)" in tracking
    assert "api.createOrder(" not in tracking
    assert "api.updateOrder(" not in tracking
    assert "pricePanel('request-pickup')" in page
    assert "<Contribute />" in page
    assert "PaymentTemplateMedia" in pricing
    assert "SERVICE_CHOICES.map" in pay
    for forbidden in ("api.createInvoice", "requestSecureFilePayment", "sendPaymentLink", "issuePayment"):
        assert forbidden not in page
    assert "/workspace/commerce?view=orders" in page
