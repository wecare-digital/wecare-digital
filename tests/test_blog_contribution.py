"""Clean-slate contribution configuration tests.

The retired contribution catalog identities and preset amounts were wiped. A fresh Contribute
item will be added later with a new SKU and catalog identity.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import blog_contribution as bc  # noqa: E402


def test_no_retired_contribution_product_is_recognized():
    assert bc.CONTRIBUTION_PRODUCT_IDS == frozenset()


def test_no_retired_contribution_variant_is_recognized():
    assert dict(bc.CONTRIBUTION_CHOICES_PAISE) == {}
    assert bc.CONTRIBUTION_VARIANT_IDS == frozenset()


def test_no_old_contribution_amount_presets_remain():
    assert bc.CONTRIBUTION_PRESETS_PAISE == ()


def test_contribution_currency_and_purpose_vocabulary_remain_for_fresh_rebuild():
    assert bc.CONTRIBUTION_CURRENCY == "INR"
    assert bc.CONTRIBUTION_PURPOSE == "BLOG_CONTRIBUTION"
