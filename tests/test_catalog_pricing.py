"""Native supply pricing (catalog_pricing) — pure, synthetic, no I/O.

Proves the AWS-native supply total reproduces the Wix priceSummary contract: the
identity subtotal - discount + delivery + additionalFees + tax == total, the
per-line sum == subtotal, integer-paise discipline (no float), and that the
rendered Wix shape round-trips through wix_ecom.authoritative_total_paise so the
native path is a drop-in for the Wix one.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions"))
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce.catalog_pricing import (  # noqa: E402
    CatalogLine, CatalogPricingError, PriceSummary,
    authoritative_total_paise, build_price_summary,
)


def _line(qty=1, price=59900, **kw):
    return CatalogLine(product_id="p1", variant_id="v1", quantity=qty,
                       unit_price_paise=price, **kw)


def test_subtotal_is_sum_of_line_totals():
    s = build_price_summary([_line(qty=2, price=59900), _line(qty=1, price=10000)])
    assert s.subtotal_paise == 2 * 59900 + 10000
    assert s.total_paise == s.subtotal_paise  # no adjustments


def test_identity_holds_with_all_components():
    s = build_price_summary(
        [_line(qty=3, price=10000)],  # subtotal 30000
        discount_paise=5000, delivery_paise=4000,
        additional_fees_paise=100, tax_paise=4500,
    )
    assert s.total_paise == 30000 - 5000 + 4000 + 100 + 4500 == 33600


def test_discount_cannot_exceed_subtotal():
    with pytest.raises(CatalogPricingError):
        build_price_summary([_line(price=1000)], discount_paise=2000)


def test_zero_total_is_legitimate():
    s = build_price_summary([_line(price=1000)], discount_paise=1000)
    assert s.total_paise == 0
    assert authoritative_total_paise(s) == 0


def test_empty_cart_rejected():
    with pytest.raises(CatalogPricingError):
        build_price_summary([])


@pytest.mark.parametrize("bad", [True, 1.5, -1, "100"])
def test_float_bool_negative_and_string_prices_rejected(bad):
    with pytest.raises((CatalogPricingError, Exception)):
        CatalogLine(product_id="p", variant_id="v", quantity=1, unit_price_paise=bad)


@pytest.mark.parametrize("qty", [0, -1, 100001, 1.0])
def test_quantity_bounds(qty):
    with pytest.raises(CatalogPricingError):
        CatalogLine(product_id="p", variant_id="v", quantity=qty, unit_price_paise=100)


def test_wix_shape_roundtrips_through_wix_ecom():
    """The native priceSummary, rendered as Wix's shape, must be readable by the
    existing Wix total reader — proving drop-in compatibility."""
    from lambda_utils import wix_ecom
    s = build_price_summary([_line(qty=2, price=59900)], tax_paise=0)
    checkout = {"priceSummary": s.as_wix_shape()}
    assert wix_ecom.authoritative_total_paise(checkout) == s.total_paise == 119800


def test_wix_shape_total_matches_identity_with_adjustments():
    from lambda_utils import wix_ecom
    s = build_price_summary([_line(qty=1, price=100000)],
                            discount_paise=10000, delivery_paise=5000, tax_paise=1700)
    checkout = {"priceSummary": s.as_wix_shape()}
    assert wix_ecom.authoritative_total_paise(checkout) == 96700


# ── native coupon pricing (replaces Wix Calculate Cart for the website) ──────

from lambda_utils.ecommerce.catalog_pricing import coupon_discount_paise, price_cart  # noqa: E402


def test_no_coupon_is_zero_discount():
    assert coupon_discount_paise(None, subtotal_paise=50000) == 0


def test_money_off_coupon_discount():
    coupon = {"discountKind": "MONEY_OFF", "moneyOffPaise": 10000}
    assert coupon_discount_paise(coupon, subtotal_paise=50000) == 10000


def test_percent_off_coupon_discount():
    coupon = {"discountKind": "PERCENT_OFF", "percentOffBps": 1000}  # 10%
    assert coupon_discount_paise(coupon, subtotal_paise=50000) == 5000


def test_money_off_clamped_at_subtotal():
    coupon = {"discountKind": "MONEY_OFF", "moneyOffPaise": 90000}
    # cannot discount more than the cart is worth -> no negative total
    assert coupon_discount_paise(coupon, subtotal_paise=50000) == 50000


def test_price_cart_end_to_end_feeds_compute_quote():
    """price_cart -> authoritative_total_paise -> checkout_pricing.compute_quote.
    This is the full native checkout chain the Wix path currently owns."""
    from lambda_utils.ecommerce import checkout_pricing
    lines = [_line(qty=2, price=50000)]  # subtotal 100000
    coupon = {"discountKind": "PERCENT_OFF", "percentOffBps": 1000}  # 10% -> 10000 off
    summary = price_cart(lines, coupon_definition=coupon, delivery_paise=4000, tax_paise=0)
    assert summary.subtotal_paise == 100000
    assert summary.discount_paise == 10000
    assert summary.total_paise == 100000 - 10000 + 4000 == 94000
    collection = __import__(
        "lambda_utils.ecommerce.catalog_pricing", fromlist=["authoritative_total_paise"]
    ).authoritative_total_paise(summary)
    quote = checkout_pricing.compute_quote(collection)
    # fee = round_half_up(94000 * 250/10000) = 2350; gst = round_half_up(2350*1800/10000)=423
    assert quote.convenience_fee_paise == 2350
    assert quote.convenience_gst_paise == 423
    assert quote.total_payable_paise == 94000 + 2350 + 423 == 96773


def test_unsupported_coupon_kind_raises():
    coupon = {"discountKind": "FREE_SHIPPING"}
    with pytest.raises(Exception):
        coupon_discount_paise(coupon, subtotal_paise=50000)


# ── native supply tax (reuses checkout_pricing.round_half_up + split_gst) ────

from lambda_utils.ecommerce.catalog_pricing import supply_tax_paise, SupplyTax  # noqa: E402


def test_supply_tax_intra_state_splits_cgst_sgst():
    # 18% GST on 100000 paise = 18000; intra-state -> 9000 + 9000
    t = supply_tax_paise(100000, gst_bps=1800, intra_state=True)
    assert t.gst_paise == 18000
    assert t.cgst_paise == 9000 and t.sgst_paise == 9000 and t.igst_paise == 0


def test_supply_tax_inter_state_is_igst():
    t = supply_tax_paise(100000, gst_bps=1800, intra_state=False)
    assert t.igst_paise == 18000 and t.cgst_paise == 0 and t.sgst_paise == 0


def test_supply_tax_odd_paise_reconciles():
    # a GST that is odd must still split to the exact total
    t = supply_tax_paise(5, gst_bps=1800, intra_state=True)  # round_half_up(5*1800/10000)=1
    assert t.gst_paise == t.cgst_paise + t.sgst_paise + t.igst_paise


def test_zero_gst_bps_is_zero_tax_inclusive_price_case():
    # GST-inclusive catalog prices -> pass gst_bps=0 so no tax is added (no double-tax)
    t = supply_tax_paise(100000, gst_bps=0, intra_state=True)
    assert t.gst_paise == 0


def test_supply_tax_feeds_price_cart_total():
    from lambda_utils.ecommerce import checkout_pricing
    lines = [_line(qty=1, price=100000)]
    tax = supply_tax_paise(100000, gst_bps=1800, intra_state=True)
    summary = price_cart(lines, tax_paise=tax.gst_paise)
    assert summary.total_paise == 100000 + 18000 == 118000
    quote = checkout_pricing.compute_quote(summary.total_paise)
    assert quote.total_payable_paise > 118000  # fee + fee-GST added on the taxed collection


@pytest.mark.parametrize("bad_bps", [-1, 10001, 1.5, True])
def test_supply_tax_rejects_bad_bps(bad_bps):
    with pytest.raises(Exception):
        supply_tax_paise(100000, gst_bps=bad_bps, intra_state=True)
