"""Prices must reach the workspace as JSON numbers, not strings.

DynamoDB returns numeric attributes as Decimal. cors_response serializes with
json.dumps(..., default=str), which would turn Decimal(9900) into the STRING "9900".
The workspace reads priceMinor back with a strict `!== 9900`, so a stringified price
fails the readback ("VayuLok Rs 99.00 price readback failed") and every variant price
reaches the UI as a string. handle_request must normalize Decimals to numbers first.

This test seeds the fake table with Decimal prices (what live DynamoDB actually hands
back) - the other native-catalog tests seed plain ints, which is why the live bug did
not surface there.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "native_catalog_admin_price",
    ROOT / "amplify" / "functions" / "ecommerce" / "native-catalog-admin" / "handler.py",
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def seeded_decimal():
    # Exactly what boto3 resource API returns from DynamoDB: numbers as Decimal.
    return {
        "id": "product-123", "title": "Existing Product", "slug": "existing-product",
        "status": "active", "updatedAt": "2026-10-14T00:00:00.000Z",
        "createdAt": "2026-10-01T00:00:00.000Z",
        "priceMinor": Decimal(9900), "inventory": Decimal(0), "currency": "INR",
        "variants": [
            {"sku": "std", "label": "Standard", "priceMinor": Decimal(9900), "inventory": Decimal(2)},
        ],
        "imageRefs": ["https://wecare.digital/api/catalog-media/existing-4096.png"],
    }


class Table:
    def __init__(self):
        self.items = {seeded_decimal()["id"]: seeded_decimal()}

    def scan(self, **_):
        return {"Items": copy.deepcopy(list(self.items.values()))}

    def get_item(self, Key, **_):
        v = self.items.get(Key["id"])
        return {"Item": copy.deepcopy(v)} if v else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeNames, ExpressionAttributeValues):
        row = self.items[Key["id"]]
        names, vals = ExpressionAttributeNames, ExpressionAttributeValues
        if row["updatedAt"] != vals[":expected"]:
            raise AssertionError("unexpected version")
        for item in UpdateExpression.removeprefix("SET ").split(", "):
            left, right = item.split(" = ")
            if left.startswith("#vs["):
                index = int(re.match(r"#vs\[(\d+)\]", left).group(1))
                field = names[left.split("].")[-1]]
                row["variants"][index][field] = vals[right]
            else:
                row[names[left]] = vals[right]


def event(path="/native-catalog/products", *, method="GET", body=None):
    return {
        "rawPath": path,
        "requestContext": {"apiId": "abc",
                           "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"}},
        "body": json.dumps(body or {}),
        "headers": {"origin": "https://wecare.digital"},
    }


@pytest.fixture(autouse=True)
def staff_auth(monkeypatch):
    def auth(evt, required_role=None):
        evt["_auth"] = {"username": "verified-admin", "role": "Admin"}
        return None
    monkeypatch.setattr(mod, "require_auth", auth)


def _variant(resp):
    body = json.loads(resp["body"])
    product = body.get("product") or (body.get("products") or [{}])[0]
    return product["variants"][0]


def test_list_serializes_variant_price_as_number_not_string():
    resp = mod.handle_request(event(), Table())
    body = json.loads(resp["body"])
    variant = body["products"][0]["variants"][0]
    assert variant["priceMinor"] == 9900
    assert isinstance(variant["priceMinor"], (int, float))
    assert not isinstance(variant["priceMinor"], str)
    # the raw JSON must contain the number, never the quoted string
    assert '"priceMinor": 9900' in resp["body"] or '"priceMinor":9900' in resp["body"]
    assert '"priceMinor": "9900"' not in resp["body"]


def test_variant_price_patch_reads_back_as_number():
    # Set the price to 9900 (idempotent here) and confirm the readback is a NUMBER, which is
    # exactly the check the workspace runs after 'Setting VayuLok Standard price to Rs 99.00'.
    body = {"expectedUpdatedAt": "2026-10-14T00:00:00.000Z", "priceMinor": 12900}
    resp = mod.handle_request(
        event("/native-catalog/products/product-123/variants/std", method="PATCH", body=body),
        Table())
    assert resp["statusCode"] == 200
    variant = _variant(resp)
    assert variant["priceMinor"] == 12900
    assert isinstance(variant["priceMinor"], (int, float)) and not isinstance(variant["priceMinor"], str)
