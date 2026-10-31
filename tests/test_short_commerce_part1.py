"""Source-bound website checkout contracts. No AWS, provider or customer traffic."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CART = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
CHECKOUT = (ROOT / "src/pages/checkout/index.tsx").read_text(encoding="utf-8")
CART_COMPAT = (ROOT / "src/pages/cart.tsx").read_text(encoding="utf-8")
WHATSAPP = (ROOT / "src/pages/checkout/whatsapp.tsx").read_text(encoding="utf-8")
HANDLER = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
ORDER = (ROOT / "src/components/orders/OrderDetail.tsx").read_text(encoding="utf-8")
INVOICE = (ROOT / "src/lib/customerInvoice.ts").read_text(encoding="utf-8")
STATUS_PAGE = (ROOT / "src/pages/checkout/status.tsx").read_text(encoding="utf-8")
SERVICE = (ROOT / "src/lib/serviceEntry.ts").read_text(encoding="utf-8")


def between(source, begin, end):
    assert begin in source and end in source
    return source.split(begin, 1)[1].split(end, 1)[0]


def test_canonical_checkout_is_not_a_redirect_and_cart_is_compatible():
    assert "import CartPage" in CHECKOUT and "export default CartPage" in CHECKOUT
    assert "window.location.replace" in CART_COMPAT
    assert "/checkout/" in CART_COMPAT
    assert "basketTokenFromUrl" in CART_COMPAT
    assert "export const CHECKOUT_PATH = '/checkout/';" in SERVICE
    assert "href=\"/checkout/\"" in STATUS_PAGE


def test_full_website_cart_preserves_all_lines_and_selected_quantities():
    writer = between(CART, "export function addItem (", "export function availableVariantsForItem")
    assert "writeCart( result )" in writer
    assert "[ ...current, selected ]" in writer
    lines = between(CART, "export function toLineItems (", "/* ── Phase O-1 services:")
    assert "quantity: item.quantity" in lines
    assert "catalogReference:" in lines
    assert "formattedPrice" not in lines
    assert "amountPaise" not in lines


def test_quote_is_read_only_and_does_not_create_payment_attempt():
    quote = between(HANDLER, "def _website_quote(", "def _website_prepare(")
    assert 'action == "quote"' in HANDLER
    assert "_website_snapshot(identity, line_items" in quote
    assert "_website_invoice_lines(snapshot)" in quote
    assert "_order_charges(spec, items" in quote
    for forbidden in ("_reserve_website_attempt(", "create_order(", "prepare_checkout(",
                      "new_payment_attempt_id(", "_send_order_details("):
        assert forbidden not in quote
    assert '"QUOTE_READY"' in quote
    assert "return _hardened(cors_response(" not in quote or "_hardened(cors_response(code, data, origin))" in quote


def test_website_allows_full_basket_but_native_policy_stays_separate():
    website = between(HANDLER, "def _website_prepare(", "def _load_attempt_via(")
    assert "short_purchase.one_unit_lines(line_items)" not in website
    native = between(HANDLER, "def _create(", "def _status(")
    assert "short_purchase.one_unit_lines" in native
    assert "/checkout/whatsapp/" in PAGE
    assert "no payment or message" in WHATSAPP.lower()
    assert "fetch(" not in WHATSAPP and "Razorpay" not in WHATSAPP


def test_payment_matches_reviewed_quote_before_opening_razorpay():
    assert "parseCheckoutQuote( body )" in PAGE
    assert "options.amountPaise !== expectedTotalPaise" in PAGE
    # Prior live Lambda falls back to a CREATE for unknown actions. Never post
    # action:quote before the version-pinned backend is activated.
    assert "NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED" in PAGE
    assert "if ( !WEBSITE_FULL_CART_QUOTE_ENABLED )" in PAGE
    assert "return { kind: 'QUOTE_CHANGED' };" in PAGE
    assert "const expectedTotalPaise = quote.charges.totalPaise" in PAGE
    assert "quoteFor !== basketFingerprint( lineItems )" in PAGE
    assert "disabled={ busy || !quoteReady }" in PAGE
    assert "action: 'prepare'" in PAGE
    assert "proceed( 'whatsapp' )" not in PAGE
    assert "SHORT_COMMERCE_ONE_PRODUCT_MESSAGE" not in PAGE


def test_no_paid_order_claim_before_server_capture():
    assert "VERIFIED_PAID" in PAGE
    assert "clearCart();" in PAGE
    assert "goToCheckoutStatus(" in PAGE
    assert "isPaid( status )" in STATUS_PAGE
    assert "settlePaidCheckout( attemptId )" in STATUS_PAGE
    assert "Do not pay again." in STATUS_PAGE


def test_authenticated_order_table_and_real_invoice_download():
    assert '<table className="odt-items-table">' in ORDER
    assert "order.orderNumber" in ORDER
    assert "order.invoiceNumber" in ORDER
    assert "charges.supplyGstPaise" in ORDER
    assert "Download GST invoice" in ORDER
    assert "downloadOrderInvoice(" in ORDER
    assert "format: 'png'" in INVOICE
    assert "isSignedInvoiceUrl" in INVOICE
    assert "X-Amz-Signature" in INVOICE
    assert "paymentStatus === 'captured'" in ORDER
