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
    snap = _snapshot(_line(GC_SKU, 50000, qty=2), _line("other-product", 9900))
    purchases = gcp.gift_card_purchases(snap, env=ENV)
    assert purchases == [{"productId": GC_SKU, "faceValuePaise": 50000, "quantity": 2}]


def test_a_gift_card_line_with_no_usable_frozen_price_is_skipped():
    snap = _snapshot({"productId": GC_SKU, "quantity": 1})  # no unitPricePaise
    assert gcp.gift_card_purchases(snap, env=ENV) == []


# ── issue-on-paid ─────────────────────────────────────────────────────────────

def test_issuing_mints_one_card_per_unit_at_the_paid_face_value():
    cards = _cards_table()
    snap = _snapshot(_line(GC_SKU, 50000, qty=2))
    issued = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC01",
                                      purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                      clock=lambda: NOW)
    assert len(issued) == 2
    for card in issued:
        assert card["faceValuePaise"] == 50000
        assert len(card["code"]) >= gc.MIN_CODE_LENGTH
        # The minted card row carries the paid balance and the source order.
        row = gc.get_card(cards, code_hash=gc.code_hash(card["code"], pepper=PEPPER))
        assert int(row["balancePaise"]) == 50000
        assert row["sourceOrderId"] == "WD-ORD-GC01"
    # Two distinct codes.
    assert issued[0]["code"] != issued[1]["code"]


def test_issuing_is_idempotent_a_replay_mints_nothing_new():
    cards = _cards_table()
    snap = _snapshot(_line(GC_SKU, 50000, qty=2))
    first = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC02",
                                     purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                     clock=lambda: NOW)
    assert len(first) == 2
    replay = gci.issue_for_paid_order(cards, order_id="WD-ORD-GC02",
                                      purchased_snapshot=snap, pepper=PEPPER, env=ENV,
                                      clock=lambda: NOW)
    assert replay == []
    # Still exactly two minted cards in the ledger — the replay added no third.
    minted = [r for r in cards.rows.values() if r.get("kind") is None and "balancePaise" in r]
    assert len(minted) == 2


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
