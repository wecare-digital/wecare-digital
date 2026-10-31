"""Prevent generation of per-order public URLs anywhere in the customer purchase journey.

The public Orders page is /orders/ for all channels. Old incoming ?o= links
stay readable, but new WhatsApp, RCS, checkout and menu links must not mint one.
No live payment/message/database calls: these are source and template contracts.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
ORDERS_URL = "https://wecare.digital/orders/"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_no_new_per_order_urls_in_active_public_and_backend_sources():
    # Scan application runtime source, not legacy dated docs or authored test fixtures.
    runtime_roots = (ROOT / "src", ROOT / "amplify" / "functions")
    forbidden = re.compile(
        r"(?:https?://wecare\.digital)?/orders/?\?(?:o|order|orderNumber|orderId)=",
        re.IGNORECASE,
    )
    offenders = []
    for root in runtime_roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".json"}:
                continue
            if path.is_file() and forbidden.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Public per-order URL found: {offenders}"


def test_post_payment_invoice_never_creates_a_free_form_orders_url_message():
    # The canonical Orders URL still exists on authenticated website pages.
    # WhatsApp post-payment automation is template-only: no extra cta_url.
    source = read("amplify/functions/payments/invoice-engine/handler.py")
    beginning = source.index("def _send_order_page_link(")
    end = source.index("def _resolve_order_id(", beginning)
    send = source[beginning:end]
    assert "_ORDER_PAGE_URL = 'https://wecare.digital/orders/'" in source
    assert "return 'template_only_policy'" in send
    assert "'interactiveType': 'cta_url'" not in send
    assert "'isInteractive': True" not in send
    assert "'buttonText': 'View your order'" not in send
    assert "'url': _ORDER_PAGE_URL" not in send
    assert "lambda_client.invoke(" not in send
    assert "claim_invoice_delivery(" not in send

def test_whatsapp_command_and_rcs_template_link_to_order_history():
    command = read(
        "amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py"
    )
    assert f"ORDERS_URL = '{ORDERS_URL}'" in command
    assert "'\\n\\nView orders and download receipts:\\n' + ORDERS_URL" in command

    template = json.loads(read("rcs/templates/source/wecare_order_update.json"))
    body = template["component"]["text"]
    assert ORDERS_URL in body
    assert "order_id" in body  # Separate text variable, never URL interpolation.
    assert not re.search(r"/orders/\?", body)


def test_checkout_and_request_menus_use_only_orders_page():
    helper = read("src/lib/orderPage.ts")
    checkout = read("src/pages/checkout/status.tsx")
    header = read("src/components/Header.tsx")
    menu = read("src/components/orders/OrderActionsMenu.tsx")
    assert "return '/orders/';" in helper
    assert "stashPendingOrder" not in checkout
    assert "router.replace( orderPagePath( orderNumber ) )" in checkout
    assert "href={ orderPagePath( orderNumber ) }" in checkout
    request_section = header.split("heading: 'Request',", 1)[1].split(
        "heading: 'Refer & Earn',", 1
    )[0]
    for label in (
        "Submit Request", "Request Amendment", "Drop Docs",
        "Vault", "Track", "Pickup Request",
    ):
        assert f"label: '{label}', href: '/orders/'" in request_section
        assert f"label: '{label}', subtitle:" in menu
    assert menu.count("href: '/orders/'") == 6
    assert "stashPendingOrder" not in menu


def test_order_history_retires_detail_exposure_at_ui_and_backend():
    pages = ROOT / "src/pages"
    assert (pages / "orders.tsx").is_file()
    assert not (pages / "orders").exists()
    assert not (pages / "order.tsx").exists()
    assert not (pages / "order").exists()

    orders = read("src/components/orders/OrdersPage.tsx")
    helper = read("src/lib/orderPage.ts")
    backend = read("amplify/functions/ecommerce/checkout/handler.py")
    assert not (ROOT / "src/components/orders/OrderDetail.tsx").exists()
    assert "OrderDetail" not in orders
    assert "setOpenRows" not in orders
    assert "aria-expanded={ isOpen }" not in orders
    assert 'colSpan={ 5 }' not in orders
    assert 'className="ord-detailrow' not in orders
    assert 'className="ord-compact-facts"' not in orders
    assert "invoiceNumber" not in orders
    assert "charges.supplyGstPaise" not in orders
    assert "Via WhatsApp" not in orders
    assert "orderNumberFromUrl" not in orders
    assert "takePendingOrder" not in orders
    assert "stashPendingOrder" not in orders
    assert "window.history.replaceState( window.history.state, '', '/orders/' );" in orders
    assert "window.sessionStorage.removeItem( 'wecare.pendingOrderView' );" in orders
    assert "orderPagePath ( _orderNumber: string )" in helper
    assert "return '/orders/';" in helper
    assert "orderNumberFromUrl" not in helper
    assert "stashPendingOrder" not in helper

    # Old action=order is rejected BEFORE any payable fallback, without exposing
    # GST lines, invoice numbering, delivery address, or payment attempt details.
    assert 'if action == "order":' in backend
    assert 'return _hardened(cors_response(410, {"error": "ORDER_DETAILS_RETIRED"}, origin))' in backend
    assert "_order_detail(" not in backend
    assert "_order_view(" not in backend
    assert "_order_lines(" not in backend
    assert "_send_order_details(" in backend  # native WhatsApp payment rail remains
    assert "customer_auth.require_customer(event)" in backend
