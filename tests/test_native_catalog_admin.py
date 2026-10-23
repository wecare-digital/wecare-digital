"""Offline product-manager contract: ProductsTable only, staff roles and safe edits."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
SPEC = importlib.util.spec_from_file_location(
    "native_catalog_admin_test_target",
    ROOT / "amplify/functions/ecommerce/native-catalog-admin/handler.py",
)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class Conditional(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def seeded():
    return {
        "id": "product-123",
        "title": "Existing Product",
        "slug": "existing-product",
        "status": "active",
        "updatedAt": "2026-10-14T00:00:00.000Z",
        "createdAt": "2026-10-01T00:00:00.000Z",
        "priceMinor": 9900,
        "inventory": 0,
        "currency": "INR",
        "variants": [
            {"sku": "sku-a", "label": "Small", "priceMinor": 9900, "inventory": 2},
            {"sku": "sku-b", "label": "Large", "priceMinor": 12900, "inventory": 3},
        ],
        "imageRefs": ["https://wecare.digital/get/o/stack/store/products/existing.png"],
    }


class Table:
    def __init__(self):
        self.items = {seeded()["id"]: seeded()}

    def scan(self, **_):
        return {"Items": copy.deepcopy(list(self.items.values()))}

    def get_item(self, Key, **_):
        value = self.items.get(Key["id"])
        return {"Item": copy.deepcopy(value)} if value else {}

    def put_item(self, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(id)"
        if Item["id"] in self.items:
            raise Conditional()
        self.items[Item["id"]] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeNames, ExpressionAttributeValues):
        row = self.items[Key["id"]]
        names, vals = ExpressionAttributeNames, ExpressionAttributeValues
        if row["updatedAt"] != vals[":expected"]:
            raise Conditional()
        if "#vs" in ConditionExpression:
            index = int(re.search(r"#vs\[(\d+)\]", ConditionExpression).group(1))
            if row["variants"][index]["sku"] != vals[":sku"]:
                raise Conditional()
            if ":min" in vals and row["variants"][index]["inventory"] < vals[":min"]:
                raise Conditional()
        for item in UpdateExpression.removeprefix("SET ").split(", "):
            left, right = item.split(" = ")
            if left.startswith("#vs["):
                index = int(re.match(r"#vs\[(\d+)\]", left).group(1))
                target = row["variants"][index]
                field = names[left.split("].")[-1]]
                if " + :delta" in right:
                    target[field] += vals[":delta"]
                else:
                    target[field] = vals[right]
            else:
                row[names[left]] = vals[right]


def event(path="/native-catalog/products", *, method="GET", body=None):
    return {
        "rawPath": path,
        "requestContext": {"apiId": "abc", "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"}},
        "body": json.dumps(body or {}),
        "headers": {"origin": "https://wecare.digital"},
    }


def payload(response):
    return json.loads(response["body"])


@pytest.fixture(autouse=True)
def staff_auth(monkeypatch):
    def auth(evt, required_role=None):
        assert required_role in {"Viewer", "Admin"}
        evt["_auth"] = {"username": "verified-admin", "role": "Admin"}
        return None
    monkeypatch.setattr(mod, "require_auth", auth)


def test_list_exactly_native_product_rows():
    table = Table()
    response = mod.handle_request(event(), table)
    assert response["statusCode"] == 200
    assert payload(response)["source"] == "AWS_PRODUCTS_TABLE"
    assert payload(response)["total"] == 1


def test_new_item_is_draft_and_never_overwrites_old_product_id():
    table = Table()
    row = {
        "title": "Native Product", "slug": "native-product",
        "variants": [{"sku": "size-small", "priceMinor": 12900, "inventory": 2}],
        "currency": "INR", "descriptionHtml": "<p>Native editorial copy</p>",
    }
    response = mod.handle_request(event(method="POST", body=row), table)
    assert response["statusCode"] == 201
    p = payload(response)["product"]
    assert p["id"] == "native:native-product"
    assert p["status"] == "draft"
    assert p["priceMinor"] == 12900
    assert table.items["product-123"]["slug"] == "existing-product"


def test_duplicate_slug_is_refused_and_old_rows_stay():
    table = Table()
    response = mod.handle_request(event(method="POST", body={
        "title": "Collision", "slug": "existing-product",
        "variants": [{"priceMinor": 1, "inventory": 1}],
    }), table)
    assert response["statusCode"] == 409
    assert len(table.items) == 1


def test_product_edit_preserves_slug_variant_and_id():
    table = Table()
    response = mod.handle_request(event("/native-catalog/products/product-123",
                                        method="PATCH", body={
        "expectedUpdatedAt": seeded()["updatedAt"],
        "title": "Renamed Product",
    }), table)
    assert response["statusCode"] == 200
    assert table.items["product-123"]["slug"] == "existing-product"
    assert table.items["product-123"]["variants"] == seeded()["variants"]


def test_stale_product_update_fails_without_losing_data():
    table = Table()
    response = mod.handle_request(event("/native-catalog/products/product-123",
                                        method="PATCH", body={
        "expectedUpdatedAt": "2020-01-01T00:00:00.000Z",
        "status": "archived",
    }), table)
    assert response["statusCode"] == 409
    assert table.items["product-123"]["status"] == "active"


def test_variant_price_edit_preserves_other_variant_and_legacy_metadata():
    table = Table()
    response = mod.handle_request(
        event("/native-catalog/products/product-123/variants/sku-a", method="PATCH",
              body={"expectedUpdatedAt": seeded()["updatedAt"],
                    "priceMinor": 10500}), table)
    assert response["statusCode"] == 200
    assert table.items["product-123"]["variants"][0]["priceMinor"] == 10500
    assert table.items["product-123"]["variants"][0]["inventory"] == 2
    assert table.items["product-123"]["variants"][1]["inventory"] == 3
    assert table.items["product-123"]["priceMinor"] == 10500


def test_removed_stock_mutation_is_rejected():
    table = Table()
    response = mod.handle_request(
        event("/native-catalog/products/product-123/variants/sku-a", method="PATCH",
              body={"expectedUpdatedAt": seeded()["updatedAt"],
                    "stockDelta": -5}), table)
    assert response["statusCode"] == 400
    assert table.items["product-123"]["variants"][0]["inventory"] == 2


def test_product_id_and_variant_id_are_immutable():
    table = Table()
    response = mod.handle_request(
        event("/native-catalog/products/product-123", method="PATCH",
              body={"expectedUpdatedAt": seeded()["updatedAt"], "variants": []}), table)
    assert response["statusCode"] == 400
    assert table.items["product-123"]["variants"] == seeded()["variants"]


def test_staff_admin_role_required_for_all_mutations(monkeypatch):
    roles = []
    def guard(_event, required_role=None):
        roles.append(required_role)
        return {"statusCode": 403, "body": json.dumps({"error": "DENIED"})}
    monkeypatch.setattr(mod, "require_auth", guard)
    table = Table()
    for method in ("POST", "PATCH", "DELETE"):
        result = mod.handle_request(event(method=method, body={"x": 1}), table)
        assert result["statusCode"] == 403
    assert roles == ["Admin", "Admin", "Admin"]
    assert len(table.items) == 1


def test_new_product_starts_with_both_publication_channels_off():
    table = Table()
    response = mod.handle_request(event(method="POST", body={
        "title": "Draft Artwork Product",
        "slug": "draft-artwork-product",
        "variants": [{"priceMinor": 9900, "inventory": 0}],
        "catalogImageKey": "secure/d/public/catalog-deploy/catalog/products/kiosk-4096.png",
    }), table)
    assert response["statusCode"] == 201
    product = payload(response)["product"]
    assert product["status"] == "draft"
    assert product["websiteEnabled"] is False
    assert product["metaEnabled"] is False
    assert product["catalogImageKey"].endswith("kiosk-4096.png")
    assert product["imageRefs"] == [
        "https://wecare.digital/api/catalog-media/kiosk-4096.png"
    ]


@pytest.mark.parametrize("key", [
    "https://example.com/picture.png",
    "o/catalog/products/kiosk.png",
    "secure/d/public/catalog-deploy/catalog/products/not-4096.jpg",
    "secure/d/public/catalog-deploy/catalog/products/../kiosk-4096.png",
])
def test_catalog_artwork_accepts_only_locked_live_4096_png_keys(key):
    table = Table()
    response = mod.handle_request(event(method="POST", body={
        "title": "Bad Artwork",
        "slug": "bad-artwork-" + str(abs(hash(key)))[:6],
        "variants": [{"priceMinor": 100, "inventory": 0}],
        "catalogImageKey": key,
    }), table)
    assert response["statusCode"] == 400


def test_website_and_meta_publication_require_active_status_and_approved_artwork():
    table = Table()
    response = mod.handle_request(event(
        "/native-catalog/products/product-123", method="PATCH", body={
            "expectedUpdatedAt": seeded()["updatedAt"],
            "catalogImageKey": "secure/d/public/catalog-deploy/catalog/products/kiosk-4096.png",
            "canonicalPath": "/shop/existing-product/",
            "websiteEnabled": True,
            "metaEnabled": True,
        }), table)
    assert response["statusCode"] == 200
    product = payload(response)["product"]
    assert product["websiteEnabled"] is True
    assert product["metaEnabled"] is True
    assert product["canonicalPath"] == "/shop/existing-product/"
    assert product["imageRefs"][0].startswith("https://wecare.digital/api/catalog-media/")


def test_cannot_clear_artwork_while_a_publication_channel_is_enabled():
    table = Table()
    row = table.items["product-123"]
    row["catalogImageKey"] = "secure/d/public/catalog-deploy/catalog/products/kiosk-4096.png"
    row["imageRefs"] = ["https://wecare.digital/api/catalog-media/kiosk-4096.png"]
    row["websiteEnabled"] = True
    response = mod.handle_request(event(
        "/native-catalog/products/product-123", method="PATCH", body={
            "expectedUpdatedAt": seeded()["updatedAt"],
            "catalogImageKey": "",
        }), table)
    assert response["statusCode"] == 400
    assert table.items["product-123"]["catalogImageKey"].endswith("kiosk-4096.png")


def test_can_clear_artwork_after_both_publication_channels_are_off():
    table = Table()
    row = table.items["product-123"]
    row["catalogImageKey"] = "secure/d/public/catalog-deploy/catalog/products/kiosk-4096.png"
    row["imageRefs"] = ["https://wecare.digital/api/catalog-media/kiosk-4096.png"]
    row["websiteEnabled"] = False
    row["metaEnabled"] = False
    response = mod.handle_request(event(
        "/native-catalog/products/product-123", method="PATCH", body={
            "expectedUpdatedAt": seeded()["updatedAt"],
            "catalogImageKey": "",
        }), table)
    assert response["statusCode"] == 200
    product = payload(response)["product"]
    assert product["catalogImageKey"] == ""
    assert product["imageRefs"] == []


@pytest.mark.parametrize("field", ["websiteEnabled", "metaEnabled"])
def test_new_product_cannot_publish_a_channel_before_activation(field):
    table = Table()
    body = {
        "title": "Premature Publish",
        "slug": "premature-publish",
        "variants": [{"priceMinor": 9900, "inventory": 0}],
        "catalogImageKey": "secure/d/public/catalog-deploy/catalog/products/kiosk-4096.png",
        field: True,
    }
    response = mod.handle_request(event(method="POST", body=body), table)
    assert response["statusCode"] == 400
    assert set(table.items) == {"product-123"}
    assert table.items["product-123"] == seeded()


def test_new_variant_has_no_stock_fields():
    variant = mod._validate_variant({"sku": "SKU1", "priceMinor": 9900,
                                    "inventory": 0, "trackInventory": True})
    assert variant == {"sku": "SKU1", "label": "Standard", "priceMinor": 9900}


def test_catalog_response_omits_legacy_stock_metadata():
    row = seeded()
    row["variants"][0]["trackInventory"] = True
    public = mod._public_row(row)
    assert "inventory" not in public
    assert "inventory" not in public["variants"][0]
    assert "trackInventory" not in public["variants"][0]
