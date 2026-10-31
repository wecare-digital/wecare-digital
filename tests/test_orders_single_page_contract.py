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
    for label in ("Submit Request", "Request Amendment", "Drop Docs", "Vault", "Shipments",
                  "Leave Review", "Subscribe"):
        marker = f"'{label}': '" if " " in label else f"{label}: '"
        assert marker in header_icons
        path = header_icons.split(marker, 1)[1].split("'", 1)[0]
        assert f"path: '{path}'" in menu, f"{label} icon differs from homepage"

    subnav_path = header.split("const SUBNAV_ICON_PATH = '", 1)[1].split("'", 1)[0]
    assert f"path: '{subnav_path}'" in menu
    # Service-specific controls will be added inside /orders/, not public product pages.
    assert menu.count("href: '/orders/'") == 6
    for path in ("/submit-request/", "/request-amendment/", "/drop-docs/",
                 "/vault/", "/shipments/track/", "/request-pickup/"):
        assert f"href: '{path}'" not in menu
    assert "stashPendingOrder( orderNumber );" in menu
    # The click guard moved to a shared helper. Keep modifier/new-tab actions
    # navigation-only so a menu click cannot queue an unintended WhatsApp send.
    assert "isPrimaryMenuActivation( event )" in menu
    menu_actions = source("src/lib/customerMenuActions.ts")
    for guard in ("event.button === 0", "!event.metaKey", "!event.ctrlKey",
                  "!event.shiftKey", "!event.altKey"):
        assert guard in menu_actions
    assert "CUSTOMER_MENU_HREFS" in menu
    assert "href: CUSTOMER_MENU_HREFS['leave-review']" in menu
    assert "href: CUSTOMER_MENU_HREFS.subscribe" in menu
    for title in ("Submit Request", "Request Amendment", "Drop Docs", "Vault", "Track",
                  "Pickup Request", "Leave Review", "Subscribe"):
        assert f"label: '{title}'" in menu
    assert "Coming soon" not in menu
    assert "?o=" not in menu


def test_orders_table_stays_compact_and_signout_is_inside_card() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert ".ord-th:last-child,.ord-invoice-cell{inline-size:1%;white-space:nowrap}" in orders
    assert ".ord-invoice-actions{display:inline-flex;align-items:center;gap:16px}" in orders
    assert "padding:4px 12px;vertical-align:middle;" in orders
    assert ".ord-td{padding:5px 8px}" in orders
    assert ".ord-list-head,.ord-empty-head{display:flex;align-items:center;justify-content:space-between;gap:12px}" in orders
    assert ".ord-list-head{padding:10px 14px}" in orders
    assert ".ord-empty-head{inline-size:100%}" in orders
    assert orders.count('className="ord-account-action ord-signout"') == 2
    assert orders.count('<OrderActionIcon name="logout" />') == 2
    assert 'OrderActionIcon name="person"' not in orders
    assert "sendProfileUpdate" not in orders
    assert "fetch( PROFILE_URL" in orders
    assert "featureFlags.invoiceDownload" in orders
    assert 'colSpan={ 5 }' in orders


def test_orders_backend_failures_render_once_above_table() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    detail = source("src/components/orders/OrderDetail.tsx")

    # The source stays a client-only status, never included in public static output or a query URL.
    assert "const [ ordersAlert, setOrdersAlert ] = useState<OrdersAlert | null>( null );" in orders
    assert 'className="ord-toast-rail"' in orders
    assert 'className="ord-backend-toast" role="alert" aria-atomic="true"' in orders
    assert orders.index('className="ord-toast-rail"') < orders.index('className="ord-shell"')
    assert orders.count('className="ord-backend-toast"') == 1  # Backend error banner
    assert orders.count('className="ord-backend-toast ord-copy-toast"') == 1  # Compact copy toast
    assert "role=\"status\"" in orders  # Non-error clipboard feedback remains separate.

    # Covers backend history errors (including rate limits), pagination, profile linking,
    # invoice failures (including unavailable) and the authorized inline-detail read.
    assert "setOrdersAlert( { source: 'orders', message: kind === 'rate'" in orders
    assert "setOrdersAlert( { source: 'pagination', message: outcome.kind === 'rate'" in orders
    assert "setOrdersAlert( { source: 'link'," in orders
    for message in (
        "An invoice is not available for this order yet.",
        "Too many invoice requests. Wait a moment and try again.",
        "Invoice download failed. Please try again.",
    ):
        assert message in orders
    assert "onNotice={ detailNotice }" in orders
    assert orders.count("onNotice={ detailNotice }") == 2
    assert "onNotice?: (orderNumber: string, message: string | null) => void;" in detail
    assert "noticeRef.current?.( orderNumber," in detail
    assert "noticeRef.current?.( orderNumber, null );" in detail
    assert "result === 'rate'" in detail and "result === 'unavailable'" in detail

    # The alert is stable until the relevant retry succeeds; another order cannot
    # accidentally clear a concurrent invoice or order-details error.
    assert "dismissAlertFor( 'orders' );" in orders
    assert "dismissAlertFor( 'pagination' );" in orders
    assert "dismissAlertFor( 'invoice', invoiceKey );" in orders
    assert "dismissAlertFor( 'detail', orderNumber );" in orders
    assert "current?.source === source && ( !key || current.key === key )" in orders
    assert "moreFailed" not in orders
    assert 'className="ord-notice"' not in orders


def test_orders_alert_matches_auth_error_pixel_values() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    auth = source("src/pages/auth.tsx")
    assert ".auth-error{" in auth
    auth_rule = auth.split(".auth-error{", 1)[1].split("}", 1)[0]
    assert ".ord-backend-toast{" in orders
    orders_rule = orders.split(".ord-backend-toast{", 1)[1].split("}", 1)[0]

    # Same exact banner treatment as /auth (not the fixed workspace toast).
    for declaration in (
        "margin:14px 0 0",
        "padding:11px 13px",
        "border-inline-start:4px solid var(--public-brand-lime)",
        "border-radius:10px",
        "background:var(--public-lime-tint)",
        "color:var(--public-text)",
        "font-size:var(--public-supporting-size)",
        "font-weight:600",
        "line-height:1.4",
    ):
        assert declaration in auth_rule
        assert declaration in orders_rule, declaration

    assert ".ord-toast-rail{display:flex;flex-direction:column;align-items:flex-end;gap:8px;inline-size:100%;min-inline-size:0}" in orders
    assert "inline-size:min(100%,560px)" in orders_rule
    assert "overflow-wrap:anywhere" in orders_rule
    assert "position:fixed" not in orders_rule
    assert "box-shadow" not in orders_rule
    assert 'colSpan={ 5 }' in orders
    assert ".ord-invoice-actions{display:inline-flex;align-items:center;gap:16px}" in orders

def test_request_menu_routes_via_orders_customer_auth_gate() -> None:
    header = source("src/components/Header.tsx")
    orders = source("src/components/orders/OrdersPage.tsx")
    auth = source("src/pages/auth.tsx")
    paths = source("src/lib/safeReturnPath.ts")
    section = header.split("heading: 'Request',", 1)[1].split("heading: 'Refer & Earn',", 1)[0]

    for label in ("Submit Request", "Request Amendment", "Drop Docs", "Vault",
                  "Track", "Pickup Request"):
        assert f"label: '{label}', href: '/orders/'" in section

    assert "link.href === '/orders/' && link.label !== 'Orders'" in header
    assert "const MENU_SEARCH_LINKS = flattenMenuLinks();" in header
    assert "label: 'Leave Review', href: CUSTOMER_MENU_HREFS['leave-review']" in section
    assert "label: 'Subscribe', href: CUSTOMER_MENU_HREFS.subscribe" in section
    assert "let session = getSession();" in orders
    assert "session = await restoreSession();" in orders
    assert "window.location.replace( '/auth?return=/orders/' );" in orders
    assert "if ( !session )" in orders
    assert "window.location.assign( next.redirect );" in auth
    assert "'/orders/'," in paths
    assert "return isPublicOrderNumber( value ) ? value : '';" in source("src/lib/orderPage.ts")


def test_copy_status_uses_same_right_aligned_toast_instead_of_row_hint() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert "const [ copyNotice, setCopyNotice ] = useState<CopyNotice | null>( null );" in orders
    assert "await navigator.clipboard.writeText( value );" in orders
    assert "setCopyNotice( { kind: 'success', message: 'Copied' } );" in orders
    assert "restartTimer( () => setCopyNotice( null ), 2500 );" in orders
    assert "selectText( document.getElementById(" in orders
    assert "message: 'Order ID selected. Copy it with your keyboard.'" in orders
    assert "{ ( ordersAlert || copyNotice ) && (" in orders
    assert "role={ copyNotice.kind === 'fallback' ? 'alert' : 'status' }" in orders
    assert 'aria-atomic="true"' in orders
    assert 'onClick={ () => copyId( copyValue, index ) }' in orders
    assert "ord-feedback" not in orders
    assert "ord-live" not in orders
    assert "copyFailedKey" not in orders
    assert "copiedKey" not in orders
    assert "setLiveMessage" not in orders
    assert ".ord-th:last-child,.ord-invoice-cell{inline-size:1%;white-space:nowrap}" in orders
