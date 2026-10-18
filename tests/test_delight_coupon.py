"""The standalone Delight discount policy.

Delight is the ONE always-on discount: 0.5% of the collection, capped at ₹50, auto-applied on
both the website/WhatsApp native checkout and the Pay Flow invoice. There is no coupon system and
no gift-card system any more, so the figure is pure integer arithmetic in
`lambda_utils.ecommerce.default_coupon` — no table row, no coupon engine, nothing a browser or
staff member can change.

0.5% == 50 basis points. An earlier revision stored 5 bps (0.05%), a tenfold under-discount, so
these assertions pin the rupee outcomes rather than only the stored unit. The cap is ₹50
(5000 paise) — lowered from an earlier ₹100.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import default_coupon as dc  # noqa: E402


def test_delight_is_half_a_percent_capped_at_50_rupees():
    # 0.5% is 50 basis points, not 5. The rupee outcome is what the customer sees.
    assert dc.DELIGHT_PERCENT_OFF_BPS == 50
    assert dc.DELIGHT_MAXIMUM_DISCOUNT_PAISE == 5000
    # 0.5% of ₹1,000 == ₹5 == 500 paise (below the ₹50 cap).
    assert dc.delight_paise(100000) == 500
    # 0.5% of ₹5,00,000 would be ₹2,500, so the ₹50 cap bites.
    assert dc.delight_paise(50000000) == 5000


def test_delight_is_zero_for_an_empty_or_negative_collection():
    assert dc.delight_paise(0) == 0
    assert dc.delight_paise(-100) == 0


def test_delight_never_discounts_more_than_the_collection():
    # A discount can never exceed what is being bought, so it can never make a total negative.
    assert dc.delight_paise(1) <= 1
    assert dc.delight_paise(1) == 0  # 0.5% of 1 paise floors to 0


def test_the_cap_bites_exactly_at_one_lakh_rupees():
    # 0.5% of ₹10,000 == ₹50 == the cap, reached at a ₹10,000 collection.
    assert dc.delight_paise(1000000) == 5000
    # Just under the cap at ₹9,998: 0.5% == ₹49.99 == 4999 paise.
    assert dc.delight_paise(999800) == 4999


def test_the_label_hides_the_rate():
    # The only customer-facing string names the discount, never the 0.5% or the ₹50 cap.
    assert dc.DISPLAY_LABEL == "Delight"
    assert "%" not in dc.DISPLAY_LABEL and "0.5" not in dc.DISPLAY_LABEL


def test_the_definition_carries_the_label_and_policy_figures():
    d = dc.delight_definition()
    assert d["code"] == dc.DELIGHT_CODE
    assert d["name"] == dc.DISPLAY_LABEL
    assert d["percentOffBps"] == 50
    assert d["maximumDiscountPaise"] == 5000


def test_the_definition_is_a_fresh_copy_each_call():
    # A caller that mutates its copy cannot poison the next quote.
    a = dc.delight_definition()
    a["maximumDiscountPaise"] = 999999
    b = dc.delight_definition()
    assert b["maximumDiscountPaise"] == 5000
