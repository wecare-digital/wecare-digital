from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAID = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py"
OUTBOUND = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"
WA_ORDER_STATUS = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wa_order_status.py"
ROUTE = ROOT / "scripts/provision_invoice_order_status_route.py"


def test_paid_submit_request_uses_the_one_flow_completion_writer():
    source = PAID.read_text(encoding="utf-8")
    assert "flow_completion.claim_completion(" in source
    assert "table.put_item(" not in source


def test_paid_submit_request_sends_no_post_payment_interactive_flow():
    source = PAID.read_text(encoding="utf-8")
    assert "'isInteractive': True" not in source
    assert '"isInteractive": True' not in source
    assert "Payment received. Complete the details" not in source
    assert "SERVICE_ACTIVATED_NO_POSTPAY_FLOW" in source


def test_order_status_is_template_only():
    source = OUTBOUND.read_text(encoding="utf-8")
    shared = WA_ORDER_STATUS.read_text(encoding="utf-8")
    assert "wecare_order_status_v2" in source
    assert "'type': 'interactive',\n                'interactive': {\n                    'type': 'order_status'" not in source
    assert "ORDER_STATUS_TEMPLATE_NOT_READY" in source
    assert "build_template_component(" in shared
    assert "_wa_os.build_template_component(" in source
    assert "body.get('isOrderStatus'" not in source


def test_commerce_callers_use_canonical_order_status_contract():
    callers = [
        ROOT / "amplify/functions/payments/invoice-engine/handler.py",
        ROOT / "amplify/functions/ecommerce/checkout/invoice_engine.py",
        ROOT / "amplify/functions/payments/razorpay-webhook/handler.py",
    ]
    for path in callers:
        source = path.read_text(encoding="utf-8")
        assert "'orderStatusDetails':" in source
        assert "'isOrderStatus': True" not in source


def test_invoice_order_status_route_is_declared():
    source = ROUTE.read_text(encoding="utf-8")
    assert 'POST /invoices/{invoiceId}/order-status' in source
    assert 'wecare-invoice-engine:live' in source


def test_commerce_callers_pin_the_outbound_live_alias():
    callers = [
        ROOT / "amplify/functions/payments/invoice-engine/handler.py",
        ROOT / "amplify/functions/ecommerce/checkout/invoice_engine.py",
        ROOT / "amplify/functions/payments/razorpay-webhook/handler.py",
    ]
    for path in callers:
        source = path.read_text(encoding="utf-8")
        assert "os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp:live')" in source
        assert "os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp')" not in source


def test_canonical_s3_path_catalogue_and_runtime_defaults():
    paths = (ROOT / "amplify/functions/shared/lambda_utils/media_paths.py").read_text(encoding="utf-8")
    assert 'DROP_DOCS_UPLOAD_PREFIX = SECURE_UPLOAD_ROOT + "dropdocs/"' in paths
    assert 'INVOICE_CUSTOMER_IMAGE_PREFIX = PUBLIC_DELIVERABLE_ROOT + "Invoice/customer_invoice/"' in paths
    assert 'INVOICE_FONT_PREFIX = PUBLIC_DELIVERABLE_ROOT + "Invoice/fonts/"' in paths
    assert 'WHATSAPP_ROOT = PUBLIC_DELIVERABLE_ROOT + "whatsapp/"' in paths
    assert 'BLOG_ROOT = PUBLIC_DELIVERABLE_ROOT + "blog/"' in paths
    assert 'CATALOG_DEPLOY_ROOT = PUBLIC_DELIVERABLE_ROOT + "catalog-deploy/"' in paths
    assert 'PUBLIC_STREAM_MEDIA_ROOT = PUBLIC_ROOT + "stream/media/"' in paths

    runtime_files = [
        ROOT / "amplify/functions/payments/invoice-engine/handler.py",
        ROOT / "amplify/functions/ecommerce/checkout/invoice_engine.py",
        ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py",
        ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py",
        ROOT / "amplify/functions/messaging/whatsapp-template-management/handler.py",
        ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py",
        ROOT / "amplify/functions/core/secure-files/handler.py",
        ROOT / "amplify/functions/shared/lambda_utils/ecommerce/dropdocs_storage.py",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    assert "media_paths.secure('Invoice/customer_invoice/')" not in joined
    assert "media_paths.public('stack/whatsapp-media" not in joined
    assert 'media_paths.public("stack/whatsapp-media' not in joined


def test_legacy_s3_prefixes_are_read_compatible_but_write_denied_in_iam_source():
    source = (ROOT / "amplify/iam-policies.ts").read_text(encoding="utf-8")
    assert "Sid: 'DenyLegacyMediaWrites'" in source
    for prefix in (
        "secure/Invoice/customer_invoice/*",
        "secure/Invoice/fonts/*",
        "o/stack/whatsapp-media/*",
        "stack/whatsapp-media/*",
    ):
        assert prefix in source
    assert "'s3:PutObject'" in source
    assert "'s3:DeleteObject'" in source
