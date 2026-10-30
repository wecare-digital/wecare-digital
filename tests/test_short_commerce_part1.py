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


def test_legacy_checkout_url_only_redirects_to_cart_not_payment():
    assert "router.replace( CHECKOUT_PATH )" in METHOD
    assert "Continue to cart" in METHOD
    assert 'noindex,nofollow' in METHOD
    assert "Pay on WhatsApp" not in METHOD
    assert "goToServiceAction" not in METHOD
    assert "checkout.razorpay.com" not in METHOD
    assert "export const CHECKOUT_PATH = '/cart/';" in SERVICE
    assert "export const SIGN_IN_PATH = '/auth';" in SERVICE

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


def test_display_catalogue_price_never_replaces_authoritative_payable():
    page = PAGE
    assert "Catalog price shown above." in page
    assert "The final amount after applicable discounts," in page
    assert "WhatsApp" in page and "Review and Pay" in page
    assert "options.amountPaise" in page
    assert "amount: options.amountPaise" in page
    assert "action: channel === 'whatsapp' ? 'create' : 'prepare'" in page
