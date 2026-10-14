"""Native service pricing returns the SAME contract as the Wix service_pricing,
reading priceMinor from an injected ProductsTable reader. Fail-closed per slug.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import service_pricing_native as sp  # noqa: E402
from lambda_utils.ecommerce import service_requests  # noqa: E402


def _reader(prices_by_variant):
    return lambda variant: prices_by_variant.get(variant)


def test_contract_shape_matches_wix_module():
    # every offered variant priced
    by_variant = {v: {"priceMinor": 9900, "currency": "INR", "status": "active"}
                  for v in service_requests.SERVICE_VARIANT_BY_KIND.values()}
    out = sp.resolve_all(_reader(by_variant))
    assert out["currency"] == "INR"
    assert set(out["prices"]) == set(service_requests.SERVICE_KIND_BY_SLUG)
    for row in out["prices"].values():
        assert row["available"] is True and isinstance(row["paise"], int)


def test_missing_variant_is_unavailable_with_no_paise_key():
    out = sp.resolve_all(_reader({}))  # reader returns None for everything
    for row in out["prices"].values():
        assert row == {"available": False}
        assert "paise" not in row


def test_one_slug_failing_leaves_others_priced():
    variants = list(service_requests.SERVICE_VARIANT_BY_KIND.values())
    good = {v: {"priceMinor": 4900, "currency": "INR", "status": "active"} for v in variants[1:]}
    out = sp.resolve_all(_reader(good))  # first variant absent
    available = [r for r in out["prices"].values() if r["available"]]
    unavailable = [r for r in out["prices"].values() if not r["available"]]
    assert available and unavailable  # mixed, not all-or-nothing


def test_non_inr_and_inactive_and_zero_are_refused():
    variants = list(service_requests.SERVICE_VARIANT_BY_KIND.values())
    rows = {
        variants[0]: {"priceMinor": 9900, "currency": "USD", "status": "active"},
        variants[1]: {"priceMinor": 9900, "currency": "INR", "status": "archived"},
        variants[2]: {"priceMinor": 0, "currency": "INR", "status": "active"},
    }
    out = sp.resolve_all(_reader(rows))
    for v in variants[:3]:
        slug = next(s for s, k in service_requests.SERVICE_KIND_BY_SLUG.items()
                    if service_requests.SERVICE_VARIANT_BY_KIND.get(k) == v)
        assert out["prices"][slug] == {"available": False}
