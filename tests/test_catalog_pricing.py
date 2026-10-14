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
