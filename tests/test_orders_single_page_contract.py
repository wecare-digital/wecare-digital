"""Customer Orders must be one compact history, never a second order receipt.

Only /orders/ is generated. Old ?o= links are sanitized without expanding
items/GST/fulfilment/address, and the old checkout order-read action is
explicitly retired without ever falling through into a payable action.
All tests are local source contracts; no live customer/payment data is read.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_orders_history_is_only_customer_orders_screen() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert "type View = 'loading' | 'ready' | 'empty' | 'error';" in orders
    assert "view === 'focus'" not in orders
    assert "focusOrder" not in orders
    assert '<table className="ord-table">' in orders
    assert '<th scope="col" className="ord-th">Invoice</th>' in orders
    assert '<tr key={ rowId } className="ord-tr">' in orders
    assert 'className="ord-ordno"' in orders
    assert 'aria-expanded={ isOpen }' not in orders
    assert "setOpenRows" not in orders
    assert "toggleRow(" not in orders
    assert "requestedOrder" not in orders
    assert "OrderDetail" not in orders
    assert "Via WhatsApp" not in orders
    assert "invoiceNumber" not in orders
    assert "charges.supplyGstPaise" not in orders
    assert 'colSpan={ 5 }' not in orders
    assert "ord-detailcell" not in orders
    assert "ord-detail-inline" not in orders
    assert not (ROOT / "src/components/orders/OrderDetail.tsx").exists()


def test_historical_order_links_never_expand_or_fetch_detail() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    helpers = source("src/lib/orderPage.ts")
    checkout = source("src/pages/checkout/status.tsx")
    menu = source("src/components/orders/OrderActionsMenu.tsx")
    assert "params.has( 'o' ) || params.has( 'service' )" in orders
    assert "window.history.replaceState( window.history.state, '', '/orders/' );" in orders
    assert "window.sessionStorage.removeItem( 'wecare.pendingOrderView' );" in orders
    assert "orderNumberFromUrl" not in orders
    assert "takePendingOrder" not in orders
    assert "stashPendingOrder" not in orders
    assert "stashPendingOrder" not in checkout
    assert "stashPendingOrder" not in menu
    assert "export function orderPagePath ( _orderNumber: string ): string {" in helpers
    assert "return '/orders/';" in helpers
    assert "orderNumberFromUrl" not in helpers
    assert "stashPendingOrder" not in helpers
    assert "router.replace( orderPagePath( orderNumber ) )" in checkout
    assert "View orders</Link>" in checkout


def test_retired_detail_api_has_no_order_or_gst_projection() -> None:
    backend = source("amplify/functions/ecommerce/checkout/handler.py")
    assert 'if action == "order":' in backend
    assert 'return _hardened(cors_response(410, {"error": "ORDER_DETAILS_RETIRED"}, origin))' in backend
    assert "_order_detail(" not in backend
    assert "_order_view(" not in backend
    assert "_order_lines(" not in backend
    assert "customer_auth.require_customer(event)" in backend
    # The *real* checkout/receipt and invoice workflows must remain intact.
    assert 'if action == "status":' in backend
    assert 'if action == "prepare":' in backend
    assert 'if action == "quote":' in backend
    assert 'if action == "create":' in backend
    assert 'if action == "request-service-start":' in backend
    assert "def _display_lines(" in backend
    assert "def _order_charges(" in backend
    assert "_send_order_details(" in backend


def test_checkout_and_whatsapp_links_use_only_orders() -> None:
    helpers = source("src/lib/orderPage.ts")
    checkout = source("src/pages/checkout/status.tsx")
    invoice = source("amplify/functions/payments/invoice-engine/handler.py")
    assert "return '/orders/';" in helpers
    assert "router.replace( orderPagePath( orderNumber ) )" in checkout
    assert "_ORDER_PAGE_URL = 'https://wecare.digital/orders/'" in invoice
    assert "return 'template_only_policy'" in invoice
    assert "'url': _ORDER_PAGE_URL," not in invoice
    assert "'url': f'{_ORDER_PAGE_URL}?o={order_number}'" not in invoice


def test_order_actions_stay_inside_existing_five_column_table() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    menu = source("src/components/orders/OrderActionsMenu.tsx")
    assert "import OrderActionsMenu from './OrderActionsMenu';" in orders
    assert '<td className="ord-td ord-invoice-cell">' in orders
    assert '<span className="ord-invoice-actions">' in orders
    assert '<OrderActionsMenu orderNumber={ order.orderNumber } />' in orders
    assert orders.index('<OrderActionIcon name="download" />') < orders.index(
        '<OrderActionsMenu orderNumber={ order.orderNumber } />'
    )
    assert "featureFlags.invoiceDownload" in orders
    assert "createPortal(" in menu
    assert "window.addEventListener( 'scroll', onScroll, true )" in menu
    assert "event.key !== 'Escape'" in menu
    assert "document.addEventListener( 'pointerdown', onPointerDown )" in menu
    assert "aria-expanded={ open }" in menu
    assert ".orm-more:hover,.orm-more[aria-expanded='true']{" in menu
    assert "background:var(--lime-hover);border:0;box-shadow:none;outline:none;" in menu
    assert 'colSpan={ 5 }' not in orders


def test_order_actions_and_icons_match_homepage() -> None:
    header = source("src/components/Header.tsx")
    menu = source("src/components/orders/OrderActionsMenu.tsx")
    header_icons = header.split("const NAV_ICON_PATHS:", 1)[1].split("};", 1)[0]
    for label in ("Submit Request", "Request Amendment", "Drop Docs", "Vault",
                  "Shipments", "Leave Review", "Subscribe"):
        marker = f"'{label}': '" if " " in label else f"{label}: '"
        assert marker in header_icons
        path = header_icons.split(marker, 1)[1].split("'", 1)[0]
        assert f"path: '{path}'" in menu, f"{label} icon differs from homepage"
    subnav_path = header.split("const SUBNAV_ICON_PATH = '", 1)[1].split("'", 1)[0]
    assert f"path: '{subnav_path}'" in menu
    assert menu.count("href: '/orders/'") == 6
    for path in ("/submit-request/", "/request-amendment/", "/drop-docs/",
                 "/vault/", "/shipments/track/", "/request-pickup/"):
        assert f"href: '{path}'" not in menu
    for title in ("Submit Request", "Request Amendment", "Drop Docs", "Vault",
                  "Track", "Pickup Request", "Leave Review", "Subscribe"):
        assert f"label: '{title}'" in menu
    assert "Coming soon" not in menu
    assert "?o=" not in menu
    assert "isPrimaryMenuActivation( event )" in menu
    assert "stashCustomerMenuAction( sendAction );" in menu
    assert "stashPendingOrder" not in menu


def test_orders_table_remains_compact_and_signout_inside_card() -> None:
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
    assert "ord-ordbtn" not in orders
    assert "ord-caret" not in orders


def test_backend_errors_stay_in_top_alert_without_detail_fetches() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert "const [ ordersAlert, setOrdersAlert ] = useState<OrdersAlert | null>( null );" in orders
    assert 'className="ord-toast-rail"' in orders
    assert 'className="ord-backend-toast" role="alert" aria-atomic="true"' in orders
    assert orders.index('className="ord-toast-rail"') < orders.index('className="ord-shell"')
    assert orders.count('className="ord-backend-toast"') == 1
    assert orders.count('className="ord-backend-toast ord-copy-toast"') == 1
    assert "setOrdersAlert( { source: 'orders', message: kind === 'rate'" in orders
    assert "setOrdersAlert( { source: 'pagination', message: outcome.kind === 'rate'" in orders
    assert "setOrdersAlert( { source: 'link'," in orders
    for message in (
        "An invoice is not available for this order yet.",
        "Too many invoice requests. Wait a moment and try again.",
        "Invoice download failed. Please try again.",
    ):
        assert message in orders
    assert "onNotice={ detailNotice }" not in orders
    assert "dismissAlertFor( 'invoice', invoiceKey );" in orders
    assert "dismissAlertFor( 'orders' );" in orders
    assert "dismissAlertFor( 'pagination' );" in orders


def test_auth_alert_and_copy_toast_match_shared_design() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    auth = source("src/pages/auth.tsx")
    auth_rule = auth.split(".auth-error{", 1)[1].split("}", 1)[0]
    orders_rule = orders.split(".ord-backend-toast{", 1)[1].split("}", 1)[0]
    for declaration in (
        "margin:14px 0 0", "padding:11px 13px",
        "border-inline-start:4px solid var(--public-brand-lime)",
        "border-radius:10px", "background:var(--public-lime-tint)",
        "color:var(--public-text)", "font-size:var(--public-supporting-size)",
        "font-weight:600", "line-height:1.4",
    ):
        assert declaration in auth_rule
        assert declaration in orders_rule, declaration
    assert ".ord-toast-rail{display:flex;flex-direction:column;align-items:flex-end;gap:8px;inline-size:100%;min-inline-size:0}" in orders
    assert "inline-size:min(100%,560px)" in orders_rule
    assert "overflow-wrap:anywhere" in orders_rule
    assert "position:fixed" not in orders_rule
    assert "box-shadow" not in orders_rule


def test_requests_still_pass_through_canonical_customer_auth_gate() -> None:
    header = source("src/components/Header.tsx")
    orders = source("src/components/orders/OrdersPage.tsx")
    auth = source("src/pages/auth.tsx")
    paths = source("src/lib/safeReturnPath.ts")
    section = header.split("heading: 'Request',", 1)[1].split(
        "heading: 'Refer & Earn',", 1
    )[0]
    for label in ("Submit Request", "Request Amendment", "Drop Docs", "Vault",
                  "Track", "Pickup Request"):
        assert f"label: '{label}', href: '/orders/'" in section
    assert "link.href === '/orders/' && link.label !== 'Orders'" in header
    assert "const MENU_SEARCH_LINKS = flattenMenuLinks();" in header
    assert "let session = getSession();" in orders
    assert "session = await restoreSession();" in orders
    assert "window.location.replace( '/auth?return=/orders/' );" in orders
    assert "window.location.assign( next.redirect );" in auth
    assert "'/orders/'," in paths


def test_copy_status_in_right_aligned_toast() -> None:
    orders = source("src/components/orders/OrdersPage.tsx")
    assert "const [ copyNotice, setCopyNotice ] = useState<CopyNotice | null>( null );" in orders
    assert "await navigator.clipboard.writeText( value );" in orders
    assert "setCopyNotice( { kind: 'success', message: 'Copied' } );" in orders
    assert "restartTimer( () => setCopyNotice( null ), 2500 );" in orders
    assert "selectText( document.getElementById(" in orders
    assert "message: 'Order ID selected. Copy it with your keyboard.'" in orders
    assert "{ ( ordersAlert || copyNotice ) && (" in orders
    assert "role={ copyNotice.kind === 'fallback' ? 'alert' : 'status' }" in orders
    assert 'onClick={ () => copyId( copyValue, index ) }' in orders
    assert "ord-feedback" not in orders
    assert "ord-live" not in orders
