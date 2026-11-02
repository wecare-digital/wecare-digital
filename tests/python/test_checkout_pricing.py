"""Behavioural tests for lambda_utils.ecommerce.checkout_pricing.

These pin the exact rounding rule (Decimal ROUND_HALF_UP at the .5 boundary),
the GST split reconciliation (cgst + sgst + igst == gst for intra- and
inter-state) and the buyer-GSTIN boundary validator (canonicalisation, None
pass-through, malformed rejection, seller-GSTIN rejection).

Fixtures are synthetic: the seller GSTIN is read from the module's own
SELLER_GSTIN constant rather than hardcoded, and the buyer GSTINs are
obviously-fake but format-valid values.
"""

from decimal import Decimal, ROUND_HALF_UP

import pytest

from lambda_utils.ecommerce import checkout_pricing
from lambda_utils.ecommerce.checkout_pricing import (
    PricingError,
    SELLER_GSTIN,
    round_half_up,
    split_gst,
    validate_buyer_gstin,
)

# A format-valid buyer GSTIN that is NOT the seller's. Same state code as the
# seller (19) so inferred intra-state logic stays comparable; different PAN so it
# can never collide with SELLER_GSTIN.
FAKE_BUYER_GSTIN_SAME_STATE = "19AAAAA0000A1Z5"
# A different state code (27) — an inter-state buyer.
FAKE_BUYER_GSTIN_OTHER_STATE = "27AAAAA0000A1Z5"


def _reference_round(numerator, bps):
    exact = (Decimal(numerator) * Decimal(bps)) / Decimal(10000)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def test_round_half_up_matches_decimal_reference():
    for numerator, bps in [(100, 250), (12345, 1800), (1, 10000), (0, 250)]:
        assert round_half_up(numerator, bps) == _reference_round(numerator, bps)


def test_round_half_up_rounds_the_half_boundary_away_from_zero():
    # numerator * bps / 10000 == exactly .5 => rounds up.
    # 20 * 2500 / 10000 = 5.0 ; 2 * 2500 / 10000 = 0.5 -> 1
    assert round_half_up(2, 2500) == 1
    # 6 * 2500 / 10000 = 1.5 -> 2 (not 1, which bankers' rounding would give)
    assert round_half_up(6, 2500) == 2


def test_round_half_up_rejects_non_int_and_negative():
    with pytest.raises(PricingError):
        round_half_up(1.0, 250)  # type: ignore[arg-type]
    with pytest.raises(PricingError):
        round_half_up(-1, 250)
    with pytest.raises(PricingError):
        round_half_up(100, -1)


def test_split_gst_intra_state_reconciles_and_puts_odd_paise_on_cgst():
    for gst in [0, 1, 2, 3, 100, 101, 12345]:
        split = split_gst(gst, intra_state=True)
        assert split.cgst_paise + split.sgst_paise + split.igst_paise == gst
        assert split.igst_paise == 0
        assert split.intra_state is True
        # The odd paise goes to CGST, so CGST >= SGST and they differ by at most 1.
        assert split.cgst_paise >= split.sgst_paise
        assert split.cgst_paise - split.sgst_paise == gst % 2


def test_split_gst_inter_state_is_all_igst():
    for gst in [0, 1, 101, 12345]:
        split = split_gst(gst, intra_state=False)
        assert split.cgst_paise == 0
        assert split.sgst_paise == 0
        assert split.igst_paise == gst
        assert split.intra_state is False


def test_split_gst_rejects_negative():
    with pytest.raises(PricingError):
        split_gst(-1, intra_state=True)


def test_validate_buyer_gstin_canonicalises_case():
    assert validate_buyer_gstin(FAKE_BUYER_GSTIN_SAME_STATE.lower()) == FAKE_BUYER_GSTIN_SAME_STATE


def test_validate_buyer_gstin_none_passes_through():
    assert validate_buyer_gstin(None) is None


def test_validate_buyer_gstin_rejects_malformed():
    with pytest.raises(PricingError):
        validate_buyer_gstin("NOT-A-GSTIN")


def test_validate_buyer_gstin_rejects_the_seller_gstin():
    # The seller's own GSTIN must never be accepted as a buyer (self-dealing invoice).
    with pytest.raises(PricingError):
        validate_buyer_gstin(SELLER_GSTIN)


def test_compute_quote_total_reconciles_to_collection_plus_fee_plus_gst():
    quote = checkout_pricing.compute_quote(100000)
    assert quote.total_payable_paise == (
        quote.collection_before_convenience_paise
        + quote.convenience_fee_paise
        + quote.convenience_gst_paise
    )
    # Fee is 2.5% of the collection, GST is 18% of the fee, both ROUND_HALF_UP.
    assert quote.convenience_fee_paise == round_half_up(100000, 250)
    assert quote.convenience_gst_paise == round_half_up(quote.convenience_fee_paise, 1800)
    assert quote.convenience_gst_split.total_paise == quote.convenience_gst_paise
