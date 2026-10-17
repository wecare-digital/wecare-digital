"""Fresh Contribute catalog configuration tests."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import blog_contribution as bc  # noqa: E402

FRESH_PRODUCT_ID = "24fa0f39-330b-5365-b7eb-9caf27ad37f1"
FRESH_VARIANT = "CNT5Q2M8"


def test_fresh_contribution_product_is_the_only_recognized_product():
    assert bc.CONTRIBUTION_PRODUCT_IDS == frozenset({FRESH_PRODUCT_ID})


def test_fresh_contribution_variant_is_fixed_at_250_rupees():
    assert dict(bc.CONTRIBUTION_CHOICES_PAISE) == {FRESH_VARIANT: 25000}
    assert bc.CONTRIBUTION_VARIANT_IDS == frozenset({FRESH_VARIANT})


def test_contribution_amount_preset_is_250_rupees_only():
    assert bc.CONTRIBUTION_PRESETS_PAISE == (25000,)


def test_contribution_currency_and_purpose_vocabulary_remain():
    assert bc.CONTRIBUTION_CURRENCY == "INR"
    assert bc.CONTRIBUTION_PURPOSE == "BLOG_CONTRIBUTION"
