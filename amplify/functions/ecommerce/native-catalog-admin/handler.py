"""Staff-only AWS-native product catalog CRUD.

Product authority: stack-wecare-digital-ProductsTable, not Wix or Meta.
This is deliberately a *new* Lambda/route so the legacy storefront can stay
available for reconciliation until its callers have been moved and verified.

Mutations require the STAFF Cognito Admin group and optimistic concurrency.
Existing Wix-derived UUID product/variant ids are preserved. Deletion only
archives the product: historical order records may continue to reference it.

No secrets and no provider-network calls are made in this module.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

import boto3

from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_response, extract_origin

REGION = os.environ.get("AWS_REGION", "us-east-1")
PRODUCTS_TABLE = os.environ.get(
    "PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable"
)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
STAFF_ROLES = {"Viewer", "Operator", "Admin"}
STATUS = {"draft", "active", "archived"}


def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(PRODUCTS_TABLE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    raise TypeError("unsupported product data")


def _resp(status: int, body: Mapping[str, Any], origin: str):
    return cors_response(status, dict(body), origin)


def _parse_body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raise ValueError("base64 payloads are not accepted")
    body = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    if len(raw) > 64000 if isinstance(raw, str) else len(json.dumps(raw)) > 64000:
        raise ValueError("product update too large")
    return body


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(name + " must be a string")
    result = value.strip()
    if not result or len(result) > limit:
        raise ValueError(name + " has invalid length")
    return result


def _minor(value: Any) -> int:
    # Exact integer paise only; do not accept floats, strings or bools.
    if type(value) is not int or value < 0 or value > 100_000_000:
        raise ValueError("priceMinor must be a nonnegative integer in paise")
    return value


def _stock(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10_000_000:
        raise ValueError("inventory must be a nonnegative integer")
    return value


def _validate_variant(variant: Any) -> dict[str, Any]:
    if not isinstance(variant, dict):
        raise ValueError("variant must be an object")
    sku = variant.get("sku") or str(uuid4())
    if not isinstance(sku, str) or not SKU.fullmatch(sku):
        raise ValueError("invalid variant sku")
    return {
        "sku": sku,
        "label": _text(variant.get("label") or "Standard", "variant label", 100),
        "priceMinor": _minor(variant.get("priceMinor")),
        "inventory": _stock(variant.get("inventory", 0)),
    }


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    # No IAM, provider credentials or raw Cognito attributes appear in responses.
    return {k: row.get(k) for k in (
        "id", "title", "slug", "status", "currency", "priceMinor",
        "inventory", "variants", "descriptionHtml", "tagline",
        "categories", "imageRefs", "createdAt", "updatedAt",
        "seoTitle", "seoDescription",
    ) if k in row}


def _scan(table) -> list[dict[str, Any]]:
    rows = []
    kwargs = {"ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return [r for r in rows if r.get("id") and r.get("status") in STATUS]


def _get(table, product_id: str):
    return table.get_item(Key={"id": product_id}, ConsistentRead=True).get("Item")


def _create(table, body: dict[str, Any], who: str) -> tuple[int, dict[str, Any]]:
    title = _text(body.get("title"), "title", 180)
    slug = _text(body.get("slug"), "slug", 100)
    if not SLUG.fullmatch(slug):
        raise ValueError("slug must be lowercase URL-safe text")
    if body.get("currency", "INR") != "INR":
        raise ValueError("INR is the supported currency")
    variants = body.get("variants")
    if not isinstance(variants, list) or not 1 <= len(variants) <= 50:
        raise ValueError("1–50 product variants required")
    rows = [_validate_variant(x) for x in variants]
    if len(set(v["sku"] for v in rows)) != len(rows):
        raise ValueError("variant skus must be unique")
    # New catalog identities are deterministically slug-keyed, preventing two
    # concurrent creators racing on the same new slug. Legacy UUID products are
    # checked first to preserve existing canonical URL identities.
    if any(r.get("slug") == slug for r in _scan(table)):
        return 409, {"error": "SLUG_EXISTS"}
    now = _now()
    row = {
        "id": "native:" + slug,
        "title": title,
        "slug": slug,
        "status": "draft",  # never publish new merchandise automatically
        "currency": "INR",
        "priceMinor": min(v["priceMinor"] for v in rows),
        "inventory": sum(v["inventory"] for v in rows),
        "variants": rows,
        "descriptionHtml": str(body.get("descriptionHtml") or "")[:10000],
        "tagline": str(body.get("tagline") or "")[:600],
        "categories": [],
        "imageRefs": [],
        "createdAt": now,
        "updatedAt": now,
        "lastEditedBy": who,
    }
    try:
        table.put_item(Item=row, ConditionExpression="attribute_not_exists(id)")
    except Exception as error:
        if (getattr(error, "response", {}).get("Error", {}).get("Code") ==
                "ConditionalCheckFailedException"):
            return 409, {"error": "SLUG_EXISTS"}
        raise
    return 201, {"product": _public_row(row)}


def _update(table, product_id: str, body: dict[str, Any], who: str
            ) -> tuple[int, dict[str, Any]]:
    old = _get(table, product_id)
    if not old:
        return 404, {"error": "PRODUCT_NOT_FOUND"}
    expected = body.get("expectedUpdatedAt")
    if not isinstance(expected, str) or expected != old.get("updatedAt"):
        return 409, {"error": "PRODUCT_VERSION_CONFLICT"}
    if any(k in body for k in ("id", "slug", "sourceId", "createdAt", "variants",
                               "inventory", "currency", "imageRefs")):
        return 400, {"error": "IMMUTABLE_OR_INVENTORY_FIELD"}
    updates: dict[str, Any] = {}
    if "title" in body:
        updates["title"] = _text(body["title"], "title", 180)
    if "tagline" in body:
        updates["tagline"] = _text(body["tagline"], "tagline", 600)
    if "descriptionHtml" in body:
        value = body["descriptionHtml"]
        if not isinstance(value, str) or len(value) > 10000:
            raise ValueError("invalid descriptionHtml")
        updates["descriptionHtml"] = value
    if "status" in body:
        if body["status"] not in STATUS:
            raise ValueError("invalid status")
        updates["status"] = body["status"]
    if "seoTitle" in body:
        updates["seoTitle"] = _text(body["seoTitle"], "seoTitle", 180)
    if "seoDescription" in body:
        updates["seoDescription"] = _text(body["seoDescription"], "seoDescription", 600)
    if not updates:
        return 400, {"error": "NO_EDITABLE_FIELDS"}
    new_updated = _now()
    if new_updated == expected:
        new_updated = expected[:-1] + "1Z"  # millisecond counterclock fallback
    updates.update({"updatedAt": new_updated, "lastEditedBy": who})
    names = {"#id": "id", "#updated": "updatedAt"}
    values = {":expected": expected}
    sets = []
    for index, (key, value) in enumerate(updates.items()):
        field, arg = "#f" + str(index), ":v" + str(index)
        names[field] = key
        values[arg] = value
        sets.append(field + " = " + arg)
    try:
        table.update_item(
            Key={"id": product_id},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression="attribute_exists(#id) AND #updated = :expected",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except Exception as error:
        if (getattr(error, "response", {}).get("Error", {}).get("Code") ==
                "ConditionalCheckFailedException"):
            return 409, {"error": "PRODUCT_VERSION_CONFLICT"}
        raise
    fresh = _get(table, product_id)
    return 200, {"product": _public_row(fresh or {**old, **updates})}


def handle_request(event: dict[str, Any], table) -> dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {})
    method = str(rc.get("http", {}).get("method") or event.get("httpMethod") or "GET").upper()
    path = str(event.get("rawPath") or rc.get("http", {}).get("path") or event.get("path") or "")
    if method == "OPTIONS":
        return _resp(200, {"ok": True}, origin)
    if method not in {"GET", "POST", "PATCH", "DELETE"}:
        return _resp(405, {"error": "METHOD_NOT_ALLOWED"}, origin)

    auth = require_auth(event, required_role="Viewer" if method == "GET" else "Admin")
    if auth is not None:
        return auth
    who = str(event.get("_auth", {}).get("username") or "staff")
    if "/native-catalog/products" not in path:
        return _resp(404, {"error": "NOT_FOUND"}, origin)
    suffix = path.split("/native-catalog/products", 1)[1].strip("/")
    if suffix and "/" in suffix:
        return _resp(404, {"error": "NOT_FOUND"}, origin)
    try:
        if method == "GET":
            if suffix:
                row = _get(table, suffix)
                return _resp(200 if row else 404,
                             {"product": _public_row(row)} if row else {"error": "PRODUCT_NOT_FOUND"},
                             origin)
            rows = _scan(table)
            rows.sort(key=lambda r: (str(r.get("title", "")), str(r.get("id", ""))))
            return _resp(200, {
                "products": [_public_row(r) for r in rows],
                "total": len(rows), "source": "AWS_PRODUCTS_TABLE",
            }, origin)
        body = _parse_body(event)
        if method == "POST" and not suffix:
            status, data = _create(table, body, who)
        elif method == "PATCH" and suffix:
            status, data = _update(table, suffix, body, who)
        elif method == "DELETE" and suffix:
            # Soft archive with the same version lock; never delete an order's product.
            status, data = _update(table, suffix, {
                "status": "archived",
                "expectedUpdatedAt": body.get("expectedUpdatedAt"),
            }, who)
        else:
            return _resp(404, {"error": "NOT_FOUND"}, origin)
        return _resp(status, data, origin)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return _resp(400, {"error": "VALIDATION_FAILED", "message": str(error)}, origin)


def handler(event, context):
    try:
        return handle_request(event, _table())
    except Exception:
        # Keep DynamoDB/provider exception details out of the public response.
        origin = extract_origin(event)
        return _resp(503, {"error": "CATALOG_TEMPORARILY_UNAVAILABLE"}, origin)
