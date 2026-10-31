"""Regression contract for the single customer Orders screen.

Only /orders/ is generated for new order links. Historical ?o= links keep
working after OTP sign-in but never render a second full-page order screen.
These tests are read-only: they do not contact payment or WhatsApp providers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_orders_history_is_the_only_customer_orders_screen() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert "type View = 'loading' | 'ready' | 'empty' | 'error';" in orders
    assert "view === 'focus'" not in orders
    assert "focusOrder" not in orders
    assert '<table className="ord-table">' in orders
    assert 'className="ord-detail-full"' in orders
    assert "orderNumber={ order.orderNumber }" in orders
    assert "href={ orderPagePath( order.orderNumber ) }" not in orders


def test_legacy_link_reopens_an_inline_order_after_sign_in() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    helpers = source("src/lib/orderPage.ts")
    assert "const fromUrl = orderNumberFromUrl();" in orders
    assert "const pending = takePendingOrder();" in orders
    assert "if ( requested ) stashPendingOrder( requested );" in orders
    assert "window.history.replaceState( window.history.state, '', '/orders/' );" in orders
    assert "orders.findIndex( item => item.orderNumber === requestedOrder )" in orders
    assert "setOpenRows" in orders
    assert "!orders.some( item => item.orderNumber === requestedOrder )" in orders
    assert "export function orderNumberFromUrl" in helpers
    assert "return isPublicOrderNumber( trimmed ) ? trimmed : '';" in helpers


def test_new_checkout_and_whatsapp_links_use_only_orders() -> None:
    helpers = source("src/lib/orderPage.ts")
    checkout = source("src/pages/checkout/status.tsx")
    invoice = source("amplify/functions/payments/invoice-engine/handler.py")
    assert "export function orderPagePath ( _orderNumber: string ): string {\n  return '/orders/';" in helpers
    assert "stashPendingOrder( orderNumber );" in checkout
    assert "router.replace( orderPagePath( orderNumber ) )" in checkout
    assert "'url': _ORDER_PAGE_URL," in invoice
    assert "'url': f'{_ORDER_PAGE_URL}?o={order_number}'" not in invoice


def test_inline_order_details_are_owned_and_accessible() -> None:
    details = source("src/components/orders/OrderDetail.tsx")
    backend = source("amplify/functions/ecommerce/checkout/handler.py")
    for element in ("odt-title", "odt-items", "odt-delivery", "odt-facts-title"):
        assert "id={ `" + element + "-${ orderNumber }` }" in details
    assert "See all your orders" not in details
    assert "stashPendingOrder( orderNumber );" in details
    assert 'Key={"orderId": order_id}, ConsistentRead=True' in backend
    assert 'str(order.get("customerId") or "") != identity.customer_id' in backend

def test_order_actions_stay_inside_the_existing_five_column_table() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    menu = source("src/components/orders/OrderActionsMenu.tsx")
    assert "import OrderActionsMenu from './OrderActionsMenu';" in orders
    assert '<td className="ord-td ord-invoice-cell">' in orders
    assert '<span className="ord-invoice-actions">' in orders
    assert '<OrderActionsMenu orderNumber={ order.orderNumber } />' in orders
    assert orders.index('<OrderActionIcon name="download" />') < orders.index(
        '<OrderActionsMenu orderNumber={ order.orderNumber } />'
    )
    assert 'colSpan={ 5 }' in orders
    assert '<th scope="col" className="ord-th">Invoice</th>' in orders
    assert "featureFlags.invoiceDownload" in orders
    assert 'createPortal(' in menu
    assert "window.addEventListener( 'scroll', onScroll, true )" in menu
    assert 'aria-expanded={ open }' in menu
    assert "event.key !== 'Escape'" in menu
    assert "document.addEventListener( 'pointerdown', onPointerDown )" in menu
    assert ".orm-more:hover,.orm-more[aria-expanded='true']{" in menu
    assert "background:var(--lime-hover);border:0;box-shadow:none;outline:none;" in menu


def test_order_action_destinations_and_icons_match_homepage() -> None:
    header = source("src/components/Header.tsx")
    menu = source("src/components/orders/OrderActionsMenu.tsx")
    header_icons = header.split("const NAV_ICON_PATHS:", 1)[1].split("};", 1)[0]

    # These are the actual source paths, not approximate icon-library substitutions.
    for label in ("Submit Request", "Drop Docs", "Vault", "Shipments",
                  "Leave Review", "Subscribe"):
        marker = f"'{label}': '" if " " in label else f"{label}: '"
        assert marker in header_icons
        path = header_icons.split(marker, 1)[1].split("'", 1)[0]
        assert f"path: '{path}'" in menu, f"{label} icon differs from homepage"

    subnav_path = header.split("const SUBNAV_ICON_PATH = '", 1)[1].split("'", 1)[0]
    assert f"path: '{subnav_path}'" in menu
    for route in ("/submit-request/", "/drop-docs/", "/vault/",
                  "/shipments/track/", "/request-pickup/"):
        assert f"href: '{route}'" in menu
    assert "import { REVIEW_ENTRY_URL } from '../../lib/reviewEntry';" in menu
    assert "import { SUBSCRIBE_CTA_HREF } from '../../content/subscribe';" in menu
    for title in ("Submit Request", "Drop Docs", "Vault", "Track",
                  "Pickup Request", "Leave Review", "Subscribe"):
        assert f"label: '{title}'" in menu
    assert "Request Amendment" not in menu
    assert "Coming soon" not in menu
    assert "?o=" not in menu
