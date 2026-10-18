"""native_shipping: policy-driven delivery options + authoritative charge, and the
full native supply chain cart -> shipping -> coupon -> tax -> price_cart -> quote.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import native_shipping as sh  # noqa: E402
from lambda_utils.ecommerce import catalog_pricing as cp  # noqa: E402


def _line(qty=1, price=50000, physical=True):
    return cp.CatalogLine(product_id="p", variant_id="v", quantity=qty,
                          unit_price_paise=price, requires_delivery=physical)


def test_digital_only_cart_ships_free():
    lines = [_line(physical=False)]
    opts = sh.delivery_options(lines, 50000, sh.ShippingPolicy(flat_rate_paise=9900,
                                                               free_above_paise=100000))
    assert opts == [{"id": sh.FREE_OPTION_ID, "title": "No delivery (digital)", "pricePaise": 0}]
    assert sh.resolve_delivery_paise(lines, 50000,
                                     sh.ShippingPolicy(flat_rate_paise=9900)) == 0


def test_flat_rate_below_threshold():
    policy = sh.ShippingPolicy(flat_rate_paise=9900, free_above_paise=100000)
    lines = [_line(price=50000)]
    assert sh.resolve_delivery_paise(lines, 50000, policy) == 9900


def test_free_above_threshold():
    policy = sh.ShippingPolicy(flat_rate_paise=9900, free_above_paise=100000)
    lines = [_line(qty=3, price=50000)]  # subtotal 150000 >= 100000
    assert sh.resolve_delivery_paise(lines, 150000, policy) == 0


def test_client_cannot_name_a_cheaper_option():
    policy = sh.ShippingPolicy(flat_rate_paise=9900, free_above_paise=100000)
    lines = [_line(price=50000)]
    with pytest.raises(sh.ShippingError):
        sh.resolve_delivery_paise(lines, 50000, policy, option_id=sh.FREE_OPTION_ID)


def test_full_native_supply_chain():
    """cart lines -> shipping -> Delight discount -> supply tax -> price_cart ->
    compute_quote. The whole native supply total, end to end.

    The only discount is the always-on Delight (0.5% up to ₹50), computed standalone from the
    subtotal. There is no coupon engine, so the definition's `percentOffBps` is NOT honoured as an
    arbitrary rate; a non-None definition only signals "apply Delight". For a 100000-paise
    subtotal that is `default_coupon.delight_paise(100000)` = 500 (0.5%, under the 5000 cap)."""
    from lambda_utils.ecommerce import checkout_pricing
    policy = sh.ShippingPolicy(flat_rate_paise=9900, free_above_paise=200000)
    lines = [_line(qty=2, price=50000)]              # subtotal 100000
    delivery = sh.resolve_delivery_paise(lines, 100000, policy)   # 9900 (below 200000)
    coupon = {"discountKind": "PERCENT_OFF", "percentOffBps": 1000}
    tax = cp.supply_tax_paise(100000 - 500, gst_bps=0, intra_state=True)  # inclusive prices
    summary = cp.price_cart(lines, coupon_definition=coupon,
                            delivery_paise=delivery, tax_paise=tax.gst_paise)
    assert summary.subtotal_paise == 100000
    assert summary.discount_paise == 500        # Delight, 0.5% of 100000
    assert summary.delivery_paise == 9900
    assert summary.total_paise == 100000 - 500 + 9900 == 109400
    quote = checkout_pricing.compute_quote(summary.total_paise)
    assert quote.total_payable_paise > 109400  # fee + GST added on the collection
