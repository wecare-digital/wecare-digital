"""Atomic native inventory transactions; no provider, no AWS credentials."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import native_inventory_txn as inventory  # noqa: E402


PROD_TABLE = "test-ProductsTable"
KEYS_TABLE = "test-CommerceKeys"
ATTEMPT = "payattempt-1"


def item(pid="product-1", vid="variant-1", qty=1):
    return {"productId": pid, "variantId": vid, "quantity": qty}


class Writer:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def transact_write_items(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("simulation: no confirmation")
        return {}


def sources(*, stock=3):
    products = {
        "product-1": {"id": "product-1", "status": "active", "variants": [
            {"sku": "variant-1", "inventory": Decimal(stock)},
            {"sku": "variant-2", "inventory": Decimal(stock)},
        ]}
    }
    keys = {}
    return products, keys, (lambda pid: products.get(pid)), (lambda key: keys.get(key))


def test_multi_variant_same_product_has_one_update_and_two_claim_puts():
    _, _, read_product, read_key = sources()
    writer = Writer()
    result = inventory.reserve_basket(
        writer, read_product, read_key, products_table=PROD_TABLE,
        keys_table=KEYS_TABLE, attempt_id=ATTEMPT,
        items=[item(), item(vid="variant-2", qty=2)],
    )
    assert result["reserved"] is True
    actions = writer.calls[0]["TransactItems"]
    assert len(actions) == 3
    assert sum("Update" in x for x in actions) == 1
    assert sum("Put" in x for x in actions) == 2
    expression = actions[-1]["Update"]["UpdateExpression"]
    assert "#variants[0].#inventory" in expression
    assert "#variants[1].#inventory" in expression
    assert " - :q0" in expression and " - :q1" in expression
    assert actions[-1]["Update"]["ConditionExpression"].count(">= :q") == 2


def test_claim_and_stock_update_are_in_single_transaction():
    _, _, read_product, read_key = sources()
    writer = Writer()
    inventory.reserve_basket(
        writer, read_product, read_key, products_table=PROD_TABLE,
        keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
    )
    assert len(writer.calls) == 1
    assert "Put" in writer.calls[0]["TransactItems"][0]
    assert "Update" in writer.calls[0]["TransactItems"][1]


def test_existing_idempotent_reservation_succeeds_even_after_stock_decreases():
    products, keys, read_product, read_key = sources(stock=0)
    keys[inventory.key_of(ATTEMPT, "variant-1")] = inventory._claim(
        ATTEMPT, "product-1", "variant-1", 1, "RESERVED"
    )
    writer = Writer()
    result = inventory.reserve_basket(
        writer, read_product, read_key, products_table=PROD_TABLE,
        keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
    )
    assert result["existing"] is True
    assert writer.calls == []


def test_insufficient_stock_rejected_before_transaction():
    _, _, read_product, read_key = sources(stock=0)
    writer = Writer()
    with pytest.raises(inventory.ReservationConflict, match="insufficient"):
        inventory.reserve_basket(
            writer, read_product, read_key, products_table=PROD_TABLE,
            keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
        )
    assert writer.calls == []


def test_ambiguous_transaction_is_not_assumed_failed_or_released():
    _, _, read_product, read_key = sources()
    writer = Writer(fail=True)
    with pytest.raises(inventory.ReservationUnavailable, match="not confirmed"):
        inventory.reserve_basket(
            writer, read_product, read_key, products_table=PROD_TABLE,
            keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
        )


def test_release_requires_explicit_payment_failure_proof():
    _, _, read_product, read_key = sources()
    writer = Writer()
    with pytest.raises(inventory.ReservationConflict, match="terminal"):
        inventory.release_basket(
            writer, read_product, read_key, products_table=PROD_TABLE,
            keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
        )
    assert writer.calls == []


def test_release_is_one_transaction_and_conditioned_on_reserved_rows():
    _, keys, read_product, read_key = sources()
    for variant in ("variant-1", "variant-2"):
        keys[inventory.key_of(ATTEMPT, variant)] = inventory._claim(
            ATTEMPT, "product-1", variant, 1, "RESERVED"
        )
    writer = Writer()
    result = inventory.release_basket(
        writer, read_product, read_key, products_table=PROD_TABLE,
        keys_table=KEYS_TABLE, attempt_id=ATTEMPT,
        items=[item(), item(vid="variant-2")],
        payment_terminal_confirmed=True,
    )
    assert result["released"] is True
    actions = writer.calls[0]["TransactItems"]
    assert len(actions) == 3
    assert sum("Update" in x and x["Update"]["TableName"] == PROD_TABLE
               for x in actions) == 1
    assert "+ :q0" in actions[-1]["Update"]["UpdateExpression"]


def test_already_released_does_not_credit_stock_twice():
    _, keys, read_product, read_key = sources()
    keys[inventory.key_of(ATTEMPT, "variant-1")] = inventory._claim(
        ATTEMPT, "product-1", "variant-1", 1, "RELEASED"
    )
    writer = Writer()
    result = inventory.release_basket(
        writer, read_product, read_key, products_table=PROD_TABLE,
        keys_table=KEYS_TABLE, attempt_id=ATTEMPT, items=[item()],
        payment_terminal_confirmed=True,
    )
    assert result["existing"] is True
    assert writer.calls == []


def test_partial_release_refused_without_stock_credit():
    _, keys, read_product, read_key = sources()
    keys[inventory.key_of(ATTEMPT, "variant-1")] = inventory._claim(
        ATTEMPT, "product-1", "variant-1", 1, "RELEASED"
    )
    keys[inventory.key_of(ATTEMPT, "variant-2")] = inventory._claim(
        ATTEMPT, "product-1", "variant-2", 1, "RESERVED"
    )
    with pytest.raises(inventory.ReservationConflict):
        inventory.release_basket(
            Writer(), read_product, read_key, products_table=PROD_TABLE,
            keys_table=KEYS_TABLE, attempt_id=ATTEMPT,
            items=[item(), item(vid="variant-2")],
            payment_terminal_confirmed=True,
        )
