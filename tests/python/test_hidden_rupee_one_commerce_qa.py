"""The unlisted Rs1 SKU uses the existing isolated internal QA pricing path."""
from pathlib import Path

import pytest

from lambda_utils.ecommerce import express_policy


def test_existing_and_new_internal_qa_identities_are_distinct():
    legacy = (express_policy.INTERNAL_QA_PRODUCT_ID, express_policy.INTERNAL_QA_VARIANT_ID, 1)
    new = (express_policy.INTERNAL_QA_ONE_PRODUCT_ID, express_policy.INTERNAL_QA_ONE_VARIANT_ID, 1)
    assert legacy != new
    assert express_policy.is_internal_qa_cart([legacy])
    assert express_policy.is_internal_qa_cart([new])
    assert express_policy.expected_express_paise(*new[:2]) == 0
    assert express_policy.expected_express_paise(*legacy[:2]) == 0


def test_one_rupee_test_is_standalone_and_single_quantity():
    product = express_policy.INTERNAL_QA_ONE_PRODUCT_ID
    variant = express_policy.INTERNAL_QA_ONE_VARIANT_ID
    assert not express_policy.is_internal_qa_cart([(product, variant, 2)])
    assert not express_policy.is_internal_qa_cart([(product, variant, 1), ("regular", "other", 1)])
    assert not express_policy.is_internal_qa_cart([(product, express_policy.INTERNAL_QA_VARIANT_ID, 1)])
    with pytest.raises(ValueError, match="INTERNAL_QA_VARIANT_UNVERIFIED"):
        express_policy.expected_express_paise(product, "other")
    assert express_policy.expected_express_paise("ordinary", "ordinary") == 4500


def test_hidden_test_has_no_public_catalogue_entry():
    root = Path(__file__).resolve().parents[2]
    for relative in ("src/content/shopProducts.ts", "src/content/catalogSnapshot.ts"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "native:commerce-test-1" not in text
        assert "WCTEST1R26" not in text
    cart = (root / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
    assert "COMMERCE_ONE_RUPEE_TEST_VARIANT_ID = 'WCTEST1R26'" in cart
    assert "native:commerce-test-1" in cart
