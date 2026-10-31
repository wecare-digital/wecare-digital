"""No-network safeguards for a one-off unpublished Rs 2 commerce QA cart link.

This is not a production payment test. The ProductsTable amount and payment
readiness must be checked separately at the server and provider.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")


def test_hidden_qa_item_uses_existing_noindex_checkout_not_a_product_page():
    assert "export default CartPage" in (ROOT / "src/pages/checkout/index.tsx").read_text()
    assert '<meta name="robots" content="noindex,nofollow" />' in PAGE
    assert "id: 'native:commerce-test-2'" in PAGE
    assert "const COMMERCE_TEST_VARIANT_ID = 'WCTEST2R26';" in PAGE
    assert "formattedPrice: '₹2.00'" in PAGE
    assert "slug: ''" in PAGE
    assert "cartFromDirectTestLink()" in PAGE
    assert "COMMERCE_TEST_VARIANT_ID" not in (
        ROOT / "src/content/shopProducts.ts"
    ).read_text(encoding="utf-8")
    assert "native:commerce-test-2" not in (
        ROOT / "src/content/catalogSnapshot.ts"
    ).read_text(encoding="utf-8")


def test_test_link_is_exactly_one_allowlisted_variant_and_idempotent():
    select = PAGE.split("function cartFromDirectTestLink ():", 1)[-1]
    assert "query.get( 'test' ) !== COMMERCE_TEST_VARIANT_ID" in select
    assert "query.has( 'basket' )" in select
    assert "item.productId === COMMERCE_TEST_PRODUCT.id" in select
    assert "item.variantId === COMMERCE_TEST_VARIANT_ID" in select
    assert "present ? existing : addItem( COMMERCE_TEST_PRODUCT, 1, COMMERCE_TEST_VARIANT_ID )" in select
    assert "query.delete( 'test' )" in select
    assert "window.history?.replaceState?" in select
    # Existing payment-path controls are unchanged. The cart holds product refs,
    # and the server's ProductsTable, not this display string, decides the price.
    cart = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
    to_lines = cart.split("export function toLineItems (", 1)[1].split(
        "/* ── Phase O-1 services:", 1
    )[0]
    assert "catalogReference" in to_lines
    assert "formattedPrice" not in to_lines
