"""Delight default coupon policy.

The customer-facing surface may show only the coupon name and rupee saving. The rate is stored
server-side as integer basis points so no browser arithmetic can change the payable amount.

The policy is 0.5% off, capped at ₹100. 0.5% == 50 basis points: an earlier revision stored it as
5 bps (0.05%), a tenfold under-discount, so these assertions pin the rupee outcomes rather than
only the stored unit. The definition comes from the ONE runtime source
(`lambda_utils.ecommerce.default_coupon`), which `scripts/seed_delight_coupon.py` also writes, so
the durable row and this policy cannot drift.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import default_coupon as dc  # noqa: E402


def _delight():
    # Validate the seed payload exactly as the durable CouponsTable row is created, so this test
    # exercises the same definition the seeder writes and the runtime default prices.
    return cs.validate_definition(dc.seed_payload(), created_by="system",
                                  clock=lambda: 1792230000)


def test_delight_is_half_a_percent_capped_at_100_rupees():
    d = _delight()
    # 0.5% is 50 basis points, not 5. The rupee outcome is what the customer sees.
    assert d["percentOffBps"] == 50
    assert d["maximumDiscountPaise"] == 10000
    # 0.5% of ₹1,000 == ₹5 == 500 paise (below the ₹100 cap).
    assert cs.discount_paise(d, collection_paise=100000) == 500
    # 0.5% of ₹5,00,000 would be ₹2,500, so the ₹100 cap bites.
    assert cs.discount_paise(d, collection_paise=50000000) == 10000


def test_delight_never_discounts_more_than_collection():
    d = _delight()
    assert cs.discount_paise(d, collection_paise=1) <= 1


def test_the_runtime_default_matches_the_seeded_row():
    # The in-memory definition the pricing paths use must price identically to the durable row.
    seeded = _delight()
    assert dc.delight_paise(100000) == cs.discount_paise(seeded, collection_paise=100000)
    assert dc.delight_paise(50000000) == cs.discount_paise(seeded, collection_paise=50000000)


def test_the_label_hides_the_rate():
    # The only customer-facing string names the discount, never the 0.5% or the ₹100 cap.
    assert dc.DISPLAY_LABEL == "Delight discount"
    assert "%" not in dc.DISPLAY_LABEL and "0.5" not in dc.DISPLAY_LABEL


def test_choose_prefers_a_better_explicit_coupon_but_never_stacks():
    # No explicit coupon -> Delight.
    assert dc.choose_definition(None, collection_paise=100000)["code"] == dc.DELIGHT_CODE
    # A ₹50-off coupon beats Delight's ₹5 at ₹1,000, so it wins.
    better = {"discountKind": cs.MONEY_OFF, "moneyOffPaise": 5000}
    chosen = dc.choose_definition(better, collection_paise=100000)
    assert chosen.get("moneyOffPaise") == 5000 and chosen.get("code") != dc.DELIGHT_CODE
    # At ₹30,00,000 the ₹100 Delight cap beats the ₹50 coupon, so Delight wins.
    assert dc.choose_definition(better, collection_paise=300000000)["code"] == dc.DELIGHT_CODE
