"""native_inventory: validation + atomic reservation. Offline, with a small fake
DynamoDB that honours attribute_not_exists and `path >= :min` guards.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import native_inventory as inv  # noqa: E402


class _Cond(Exception):
    """Stand-in for ConditionalCheckFailedException."""
    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Minimal DynamoDB double: single string key; supports attribute_not_exists put,
    numeric-guarded SET of a scalar or a variants[i].inventory path, get, delete."""

    def __init__(self, key_attr="orderId", items=None):
        self.key_attr = key_attr
        self.items = {}
        for it in (items or []):
            self.items[it[key_attr]] = dict(it)

    def _key(self, Key):
        return next(iter(Key.values()))

    def put_item(self, Item, ConditionExpression=None):
        k = Item[next(iter(Item)) if self.key_attr not in Item else self.key_attr]
        k = Item[self.key_attr]
        if ConditionExpression and "attribute_not_exists" in ConditionExpression and k in self.items:
            raise _Cond()
        self.items[k] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get(self._key(Key))
        return {"Item": dict(it)} if it else {}

    def delete_item(self, Key):
        self.items.pop(self._key(Key), None)

    def update_item(self, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        k = self._key(Key)
        it = self.items.setdefault(k, {self.key_attr: k})
        names = ExpressionAttributeNames or {}
        vals = ExpressionAttributeValues or {}

        # status SET with condition (release path)
        if "#s" in (names or {}):
            path = names["#s"]
            if ConditionExpression and it.get(path) != vals.get(":reserved"):
                raise _Cond()
            it[path] = vals.get(":released")
            return {}

        # numeric SET of a path = path +/- delta, guarded by path >= :min
        m = re.search(r"SET (.+?) = (.+?) \+ :(\w+)", UpdateExpression)
        assert m, UpdateExpression
        path = m.group(1).strip()
        delta_key = ":" + m.group(3)
        delta = vals[delta_key]
        cur = self._read_path(it, path)
        if ConditionExpression:
            cm = re.search(r"(.+?) >= :min", ConditionExpression)
            if cm and cur < vals[":min"]:
                raise _Cond()
        self._write_path(it, path, cur + delta)
        return {}

    def _read_path(self, it, path):
        m = re.match(r"variants\[(\d+)\]\.inventory", path)
        if m:
            return int(it["variants"][int(m.group(1))]["inventory"])
        return int(it.get(path, 0))

    def _write_path(self, it, path, value):
        m = re.match(r"variants\[(\d+)\]\.inventory", path)
        if m:
            it["variants"][int(m.group(1))]["inventory"] = value
        else:
            it[path] = value


def _products(stock=3):
    return FakeTable(key_attr="id", items=[{
        "id": "prod-1", "status": "active",
        "variants": [{"sku": "V1", "inventory": stock}],
    }])


def _reader(products):
    return lambda pid: products.get_item(Key={"id": pid}).get("Item")


def test_validate_passes_when_in_stock():
    p = _products(stock=5)
    inv.validate_lines(_reader(p), [{"product_id": "prod-1", "variant_id": "V1", "quantity": 3}])


def test_validate_raises_out_of_stock():
    p = _products(stock=2)
    with pytest.raises(inv.OutOfStock):
        inv.validate_lines(_reader(p), [{"product_id": "prod-1", "variant_id": "V1", "quantity": 3}])


def test_reserve_decrements_atomically():
    keys = FakeTable()
    p = _products(stock=3)
    inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 1


def test_reserve_is_idempotent_per_attempt():
    keys = FakeTable()
    p = _products(stock=3)
    inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    # second reserve must NOT decrement again
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 1


def test_reserve_fails_closed_when_insufficient_and_rolls_back_claim():
    keys = FakeTable()
    p = _products(stock=1)
    with pytest.raises(inv.OutOfStock):
        inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    # claim rolled back, stock untouched
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 1
    assert keys.items == {}


def test_release_returns_stock_and_is_idempotent():
    keys = FakeTable()
    p = _products(stock=3)
    inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    assert inv.release(keys, p, variant_id="V1", product_id="prod-1", attempt_id="A1") is True
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 3
    # second release is a no-op
    assert inv.release(keys, p, variant_id="V1", product_id="prod-1", attempt_id="A1") is False
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 3


def test_two_attempts_cannot_oversell():
    keys = FakeTable()
    p = _products(stock=3)
    inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A1")
    with pytest.raises(inv.OutOfStock):
        inv.reserve(keys, p, variant_id="V1", product_id="prod-1", quantity=2, attempt_id="A2")
    assert inv.available_units(p.get_item(Key={"id": "prod-1"})["Item"], "V1") == 1
