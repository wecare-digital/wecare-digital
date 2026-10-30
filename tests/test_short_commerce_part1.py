"""Source-bound acceptance gates for Short Commerce Part 1.

These inspect only storefront routing/wiring. The separate JavaScript runtime
test executes the real cart module with an in-memory synthetic browser.
No payment, provider, customer or AWS calls are made in these tests.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CART = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
METHOD = (ROOT / "src/pages/checkout/index.tsx").read_text(encoding="utf-8")
LEGACY_SUCCESS = (ROOT / "src/pages/checkout/success.tsx").read_text(encoding="utf-8")
STATUS_PAGE = (ROOT / "src/pages/checkout/status.tsx").read_text(encoding="utf-8")
SERVICE = (ROOT / "src/lib/serviceEntry.ts").read_text(encoding="utf-8")
LEGACY_CART = (ROOT / "src/pages/cart.tsx").read_text(encoding="utf-8")
QUOTE_COMPONENT = (ROOT / "src/components/cart/CheckoutPriceBreakdown.tsx").read_text(encoding="utf-8")
CHECKOUT_BACKEND = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
ORDERS = (ROOT / "src/components/orders/OrdersPage.tsx").read_text(encoding="utf-8")


def _part(text: str, start: str, end: str) -> str:
    assert start in text and end in text
    return text.split(start, 1)[1].split(end, 1)[0]


def test_one_single_product_writer_for_shop_contribution_and_service():
    assert "writeCart( [ selected ] );" in _part(
        CART, "export function addItem (", "export function availableVariantsForItem")
    assert "writeCart( [ selected ] );" in _part(
        CART, "export function setContribution (", "export function mergeClaimedLines")
    assert "writeCart( [ selected ] );" in _part(
        CART, "export function setServiceLine (", "export function serviceIntentFor")
    assert "const quantity = 1;" in _part(
        CART, "export function mergeClaimedLines (", "export const cartRequiresDelivery"
    )


def test_whatsapp_claim_cannot_silently_truncate_two_lines_or_quantity_two():
    claim = _part(CART, "export function mergeClaimedLines (", "export const cartRequiresDelivery")
    assert "lines.length !== 1" in claim
    assert "lines[ 0 ].quantity !== 1" in claim
    assert claim.index("lines.length !== 1") < claim.index("let merged = 0")
    assert "return { items: readCart(), merged: 0 }" in claim


def test_no_stale_multibag_can_reach_website_price_authority():
    line = _part(CART, "export function toLineItems (", "/* ── Phase O-1 services:")
    assert "items.length > 1" in line
    assert "item.quantity !== 1" in line
    assert "throw new Error( SHORT_COMMERCE_ONE_PRODUCT_MESSAGE )" in line
    assert "catalogReference:" in line
    assert "quantity: 1" in line
    assert "formattedPrice:" not in line
    assert "amountPaise" not in line


def test_cart_directly_preserves_both_existing_checkout_actions():
    assert "CHECKOUT_METHOD_PATH" not in PAGE
    assert "proceed( 'website' )" in PAGE
    assert "proceed( 'whatsapp' )" in PAGE
    assert "const chosenChannel = channel ?? selectedCheckoutChannelRef.current" in PAGE
    assert "?? 'website';" in PAGE
    assert "action: channel === 'whatsapp' ? 'create' : 'prepare'" in PAGE
    assert "getCheckoutRequestKey( lineItems )" in PAGE
    assert "const lineItems = toLineItems( currentItems )" in PAGE
    assert PAGE.index("currentItems.length > 1") < PAGE.index(
        "const lineItems = toLineItems( currentItems )")
    assert "selectedCheckoutChannelRef.current = pending.channel" in PAGE
    assert "await runCheckout( channel )" in PAGE
    assert "proceedInFlightRef.current = true" in PAGE
    assert "CART_RESET_REQUIRED" in PAGE


def test_checkout_is_the_one_review_and_direct_razorpay_page():
    assert "export { default } from '../../components/cart/CartPage';" in METHOD
    assert "router.replace( `/checkout/${ query }` )" in LEGACY_CART
    assert 'href="/checkout/"' in LEGACY_CART
    assert "export const CHECKOUT_PATH = '/checkout/';" in SERVICE
    assert "export const SIGN_IN_PATH = '/auth';" in SERVICE
    assert "proceed( 'website' )" in PAGE
    assert "proceed( 'whatsapp' )" in PAGE
    assert 'const razorpay = new window.Razorpay(' in PAGE
    # The deprecated cart route must not start money or show another choice.
    assert 'new window.Razorpay' not in LEGACY_CART


def test_legacy_success_uses_the_one_verified_payment_status_screen():
    # No independent client-side "payment successful" logic survives on a legacy route.
    assert "export { default } from './status';" in LEGACY_SUCCESS
    assert "STATUS_URL" not in LEGACY_SUCCESS
    assert "isPaid( status )" in STATUS_PAGE
    assert "isRetryable( status )" in STATUS_PAGE
    assert "isInFlight( status )" in STATUS_PAGE
    assert "settlePaidCheckout( attemptId )" in STATUS_PAGE
    assert "view === 'paid'" in STATUS_PAGE
    assert "view === 'failed'" in STATUS_PAGE
    assert "Do not pay again." in STATUS_PAGE


def test_checkout_quote_is_server_owned_and_complete():
    assert '<CheckoutPriceBreakdown' in PAGE
    assert 'websiteQuoteReady' in PAGE
    assert "options.amountPaise" in PAGE
    assert "amount: options.amountPaise" in PAGE
    for key in ('subtotalPaise', 'supplyGstPaise', 'discountPaise',
                'deliveryPaise', 'convenienceFeePaise', 'convenienceGstPaise',
                'totalPayablePaise'):
        assert key in QUOTE_COMPONENT
    assert "action: 'quote'" in QUOTE_COMPONENT
    assert "QUOTE_READY" in QUOTE_COMPONENT
    assert "const line = ( amount: number ) => formatPaiseINR( amount, 'INR' );" in QUOTE_COMPONENT
    assert '"quote"' in CHECKOUT_BACKEND
    preview = CHECKOUT_BACKEND.split('def _website_quote_preview(', 1)[1].split(
        'def _reserve_website_attempt(', 1)[0]
    assert 'short_purchase.one_unit_lines(line_items)' in preview
    assert '_website_snapshot(identity, line_items' in preview
    assert '_website_invoice_lines(snapshot)' in preview
    assert 'merchandise + supply_gst + delivery - discount + convenience + convenience_gst != total' in preview
    assert 'snapshot.quote.total_payable_paise' in preview
    assert 'create_order' not in preview
    assert 'reserve_attempt' not in preview


def test_paid_order_expands_in_existing_orders_table():
    assert "view === 'focus'" not in ORDERS
    assert '<OrderDetail' not in ORDERS
    assert 'setOpenRows( prev => ( { ...prev, [ rowKey( selected, 0 ) ]: true } ) )' in ORDERS
    assert '<table className="ord-table">' in ORDERS
    assert 'Download invoice' in ORDERS
    assert 'router.replace( orderPagePath( orderNumber ) )' in STATUS_PAGE
