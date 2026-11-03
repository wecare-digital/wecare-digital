"""Behavioural tests for lambda_utils.ecommerce.catalog_pricing.

Exercises the real CatalogLine / PriceSummary invariants, build_price_summary's
empty-cart and discount>subtotal refusals and total identity, the supply_tax
double-tax guard (gst_bps=0 => zero tax) and its reconciliation via split_gst,
and authoritative_total_paise returning a clean integer. Synthetic fixtures only.
"""

import pytest

from lambda_utils.ecommerce.catalog_pricing import (
    CatalogLine,
    CatalogPricingError,
    PriceSummary,
    authoritative_total_paise,
    build_price_summary,
    supply_tax_paise,
)


def _line(qty=2, unit=1000):
    return CatalogLine(product_id="p1", variant_id="v1", quantity=qty, unit_price_paise=unit)


def test_catalog_line_total_is_unit_times_quantity():
    assert _line(qty=3, unit=1500).total_paise == 4500


def test_catalog_line_rejects_quantity_out_of_range():
    with pytest.raises(CatalogPricingError):
        CatalogLine(product_id="p1", variant_id="v1", quantity=0, unit_price_paise=100)
    with pytest.raises(CatalogPricingError):
        CatalogLine(product_id="p1", variant_id="v1", quantity=100001, unit_price_paise=100)


def test_catalog_line_requires_ids():
    with pytest.raises(CatalogPricingError):
        CatalogLine(product_id="", variant_id="v1", quantity=1, unit_price_paise=100)


def test_build_price_summary_rejects_empty_cart():
    with pytest.raises(CatalogPricingError):
        build_price_summary([])


def test_build_price_summary_rejects_discount_greater_than_subtotal():
    with pytest.raises(CatalogPricingError):
        build_price_summary([_line(qty=1, unit=1000)], discount_paise=1001)


def test_price_summary_total_identity():
    # subtotal = 2 * 1000 = 2000
    summary = build_price_summary(
        [_line(qty=2, unit=1000)],
        discount_paise=200,
        delivery_paise=500,
        additional_fees_paise=50,
        tax_paise=180,
    )
    assert summary.subtotal_paise == 2000
    assert summary.total_paise == 2000 - 200 + 500 + 50 + 180


def test_supply_tax_zero_bps_yields_zero_tax():
    # GST-inclusive catalog prices pass gst_bps=0 so no GST is double-added.
    tax = supply_tax_paise(10000, gst_bps=0, intra_state=True)
    assert tax.gst_paise == 0
    assert tax.cgst_paise == 0
    assert tax.sgst_paise == 0
    assert tax.igst_paise == 0


def test_supply_tax_nonzero_bps_reconciles_via_split():
    tax = supply_tax_paise(10000, gst_bps=1800, intra_state=True)
    assert tax.gst_paise > 0
    assert tax.cgst_paise + tax.sgst_paise + tax.igst_paise == tax.gst_paise
    assert tax.igst_paise == 0


def test_supply_tax_rejects_bps_out_of_range():
    with pytest.raises(CatalogPricingError):
        supply_tax_paise(10000, gst_bps=10001, intra_state=True)


def test_authoritative_total_paise_returns_clean_integer():
    summary = PriceSummary(
        subtotal_paise=2000,
        discount_paise=0,
        delivery_paise=0,
        additional_fees_paise=0,
        tax_paise=0,
    )
    total = authoritative_total_paise(summary)
    assert total == 2000
    assert isinstance(total, int)
