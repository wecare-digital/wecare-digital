from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_common_service_flow_templates_are_utility_and_variable_free():
    source = (
        ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py"
    ).read_text()
    for name in (
        "submit_request_flow",
        "request_amendment_flow",
        "_dropdoc_flow",
        "pickup_request_flow",
        "track_ship_flow",
    ):
        assert f'name="{name}"' in source
    assert 'name="drop_docs_flow"' not in source
    assert 'category="MARKETING"' not in source
    assert '"templateParams": [template.language]' in source
    assert '"templateFlowButton": {"index": 0, "flowToken": token}' in source


def test_common_launcher_is_after_payment_and_exactly_once():
    source = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/service_flow_launcher.py"
    ).read_text()
    assert '"PAYMENT_PAID"' in source
    assert '"ORDER_FINALIZED"' in source
    assert "flow_sessions.record_session" in source
    assert "serviceFlowNotificationStatus" in source
    assert '"SENDING", "SEND_UNKNOWN"' in source
    assert '"ACCEPTED"' in source
    assert '"SEND_REJECTED"' in source
    assert 'FunctionName="wecare-outbound-whatsapp:live"' in source


def test_pickup_stays_fail_closed_until_its_asset_is_pickup_specific():
    source = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/service_flow_launcher.py"
    ).read_text()
    assert '"REQUEST_PICKUP": LaunchSpec(' in source
    assert 'enabled=False' in source
    assert 'blocked_outcome="PICKUP_FLOW_ASSET_MISMATCH"' in source


def test_drop_docs_readiness_uses_current_approved_template():
    checkout = (
        ROOT / "amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py"
    ).read_text()
    live = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py"
    ).read_text()
    assert "templates.get('_dropdoc_flow')" in checkout
    assert "launch.get('name') != '_dropdoc_flow'" in checkout
    assert "'_dropdoc_flow': '1041974032198332'" in live


def test_track_shipping_paid_product_uses_same_launcher():
    source = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/service_flow_launcher.py"
    ).read_text()
    dispatch = (
        ROOT
        / "amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py"
    ).read_text()
    assert '"TRACK_SHIPPING": LaunchSpec("TRACK_SHIPPING", "shipments", "shipments")' in source
    assert 'str(line.get("variantId") or "").strip().upper() == "SHT8M5P3"' in source
    assert "def launch_track_shipping_purchase(" in source
    assert "launch_track_shipping_purchase(event, lambda_client)" in dispatch
    assert '"track_ship_flow"' in (
        ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py"
    ).read_text()
