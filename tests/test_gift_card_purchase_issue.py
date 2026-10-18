"""The gift-card BUY side: detect a gift-card purchase and issue a card per unit, exactly once.

`gift_card_product` recognises a gift-card SKU (config-driven, empty by default) and reads the
paid face value out of the frozen snapshot. `gift_card_issuance.issue_for_paid_order` mints one
card per purchased unit, idempotently keyed on the order so a webhook replay mints nothing new.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import gift_card_issuance as gci  # noqa: E402
from lambda_utils.ecommerce import gift_card_product as gcp  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402

PEPPER = "pepper-for-tests-only"
GC_SKU = "prod-gift-card-1"
ENV = {"GIFT_CARD_PRODUCT_IDS": GC_SKU}
NOW = 1_700_000_000


def _cards_table() -> FakeTable:
    return FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                     indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})


def _snapshot(*lines) -> dict:
    return {"cart": {"id": "cart-1", "revision": 1}, "items": list(lines)}


def _line(product_id, unit, qty=1):
    return {"lineItemId": product_id, "productId": product_id, "variantId": product_id,
            "quantity": qty, "unitPricePaise": unit}


# ── detection ───────────────────────────────────────────────────────────────────

def test_no_sku_configured_means_no_gift_card_is_ever_detected():
    snap = _snapshot(_line(GC_SKU, 50000))
    assert gcp.gift_card_purchases(snap, env={}) == []
    assert gcp.is_gift_card_product(GC_SKU, env={}) is False


def test_a_configured_sku_is_detected_and_priced_from_the_frozen_quote():
    # One gift card per purchase: quantity is capped to 1 by the extractor even if the frozen
    # line said more (the preflight is the gate; this is the backstop).
    snap = _snapshot(_line(GC_SKU, 50000, qty=1), _line("other-product", 9900))
    purchases = gcp.gift_card_purchases(snap, env=ENV)
    assert purchases == [{"productId": GC_SKU, "faceValuePaise": 50000, "quantity": 1}]


def test_a_gift_card_line_with_no_usable_frozen_price_is_skipped():
    snap = _snapshot({"productId": GC_SKU, "quantity": 1})  # no unitPricePaise
    assert gcp.gift_card_purchases(snap, env=ENV) == []


# ── issue-on-paid ─────────────────────────────────────────────────────────────

def test_issuing_mints_exactly_one_card_at_the_paid_face_value():
    cards = _cards_table()
    snap = _snapshot(_line(GC_SKU, 50000, qty=1))
    issued = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC01",
                                      purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                      clock=lambda: NOW)
    # One gift card per purchase.
    assert len(issued) == 1
    card = issued[0]
    assert card["faceValuePaise"] == 50000
    assert len(card["code"]) >= gc.MIN_CODE_LENGTH
    # The minted card row carries the paid balance and the source order.
    row = gc.get_card(cards, code_hash=gc.code_hash(card["code"], pepper=PEPPER))
    assert int(row["balancePaise"]) == 50000
    assert row["sourceOrderId"] == "WD-ORD-GC01"


def test_issuing_is_idempotent_a_replay_mints_nothing_new():
    cards = _cards_table()
    snap = _snapshot(_line(GC_SKU, 50000, qty=1))
    first = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC02",
                                     purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                     clock=lambda: NOW)
    assert len(first) == 1
    replay = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC02",
                                      purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                      clock=lambda: NOW)
    assert replay == []
    # Still exactly one minted card in the ledger — the replay added no second.
    minted = [r for r in cards.rows.values() if r.get("kind") is None and "balancePaise" in r]
    assert len(minted) == 1


def test_a_non_gift_card_order_issues_nothing():
    cards = _cards_table()
    snap = _snapshot(_line("other-product", 9900))
    assert gci.issue_for_paid_order(cards, order_id="WD-ORD-GC03",
                                    purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                    clock=lambda: NOW) == []


def test_with_no_sku_configured_a_gift_card_looking_line_issues_nothing():
    cards = _cards_table()
    snap = _snapshot(_line(GC_SKU, 50000))
    assert gci.issue_for_paid_order(cards, order_id="WD-ORD-GC04",
                                    purchased_snapshot=snap, pepper=PEPPER, env={},
                                    clock=lambda: NOW) == []


# ── one gift card per purchase, no multiples ────────────────────────────────────

def _ref_line(product_id, qty=1):
    """A browser cart line (catalogReference shape), as checkout_preflight reads it."""
    return {"catalogReference": {"catalogItemId": product_id}, "quantity": qty}


def test_preflight_passes_a_single_gift_card_at_quantity_one():
    assert gcp.checkout_preflight([_ref_line(GC_SKU, 1)], env=ENV) is None
    # Non-gift-card basket is always fine.
    assert gcp.checkout_preflight([_ref_line("other", 3)], env=ENV) is None
    # Inert when no SKU is configured.
    assert gcp.checkout_preflight([_ref_line(GC_SKU, 5)], env={}) is None


def test_preflight_refuses_a_gift_card_quantity_above_one():
    status, payload = gcp.checkout_preflight([_ref_line(GC_SKU, 2)], env=ENV)
    assert status == 409
    assert payload["error"] == gcp.GIFT_CARD_INVALID_QUANTITY
    assert "Nothing has been charged" in payload["message"]


def test_preflight_refuses_a_boolean_quantity():
    # isinstance(True, int) is True, so a boolean must still be refused as not-a-count.
    status, payload = gcp.checkout_preflight([_ref_line(GC_SKU, True)], env=ENV)
    assert status == 409
    assert payload["error"] == gcp.GIFT_CARD_INVALID_QUANTITY


def test_preflight_refuses_two_gift_card_lines():
    status, payload = gcp.checkout_preflight(
        [_ref_line(GC_SKU, 1), _ref_line(GC_SKU, 1)], env=ENV)
    assert status == 409
    assert payload["error"] == gcp.GIFT_CARD_ONE_PER_ORDER


def test_the_issue_backstop_caps_a_bypassed_snapshot_to_one_card():
    """Even if a multi-unit / multi-line snapshot slipped past the preflight, issuance mints
    exactly one card — never a windfall."""
    cards = _cards_table()
    # A snapshot that should have been refused: quantity 3 AND a second gift-card line.
    snap = _snapshot(_line(GC_SKU, 50000, qty=3), _line(GC_SKU + "-b", 20000, qty=1))
    env = {"GIFT_CARD_PRODUCT_IDS": f"{GC_SKU},{GC_SKU}-b"}
    purchases = gcp.gift_card_purchases(snap, env=env)
    # Exactly one entry, quantity capped to 1.
    assert len(purchases) == 1
    assert purchases[0]["quantity"] == 1
    issued = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC-CAP",
                                      purchased_snapshot=snap, pepper=PEPPER, env=env,
                                      clock=lambda: NOW)
    assert len(issued) == 1
