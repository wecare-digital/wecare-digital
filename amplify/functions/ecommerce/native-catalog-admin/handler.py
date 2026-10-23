"""Staff-only AWS-native product catalog CRUD.

Product authority: stack-wecare-digital-ProductsTable, not Meta.
This is deliberately a *new* Lambda/route so the legacy storefront can stay
available for reconciliation until its callers have been moved and verified.

Mutations require the STAFF Cognito Admin group and optimistic concurrency.
Existing UUID product/variant ids are preserved. Deletion only
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
CATALOG_IMAGE_PREFIX = "secure/d/public/catalog-deploy/catalog/products/"  # approved masters, served via catalog-media
CATALOG_IMAGE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-4096[.]png$")
CATALOG_MEDIA_BASE = "https://wecare.digital/api/catalog-media/"


def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(PRODUCTS_TABLE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_numbers(value: Any) -> Any:
    """Convert DynamoDB Decimals to JSON numbers (integral -> int, fractional -> float).

    cors_response serializes with json.dumps(..., default=str), which would turn a Decimal
    priceMinor into the STRING "9900" - and the workspace reads priceMinor back with a strict
    `!== 9900`, so a stringified price fails the readback ("VayuLok ₹99.00 price readback
    failed") and every variant price reaches the UI as a string. Normalize here so prices are
    real numbers before the response is built.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, Mapping):
        return {k: _normalize_numbers(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_numbers(v) for v in value]
    return value


def _resp(status: int, body: Mapping[str, Any], origin: str):
    return cors_response(status, _normalize_numbers(dict(body)), origin)


def _parse_body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raise ValueError("base64 payloads are not accepted")
    body = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    size = len(raw) if isinstance(raw, str) else len(json.dumps(raw))
    if size > 64000:
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



def _catalog_image_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("catalogImageKey must be a string")
    key = value.strip().lstrip("/")
    if not key.startswith(CATALOG_IMAGE_PREFIX):
        raise ValueError("catalogImageKey must use the approved catalog-deploy products prefix")
    name = key[len(CATALOG_IMAGE_PREFIX):]
    if "/" in name or not CATALOG_IMAGE_NAME.fullmatch(name):
        raise ValueError("catalogImageKey must name an approved *-4096.png artwork")
    return key


def _catalog_image_url(key: str) -> str:
    return CATALOG_MEDIA_BASE + key[len(CATALOG_IMAGE_PREFIX):]


def _channel_flag(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(name + " must be a boolean")
    return value


def _canonical_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("canonicalPath must be a string")
    path = value.strip()
    if not path.startswith("/") or "://" in path or len(path) > 220:
        raise ValueError("canonicalPath must be a local absolute path")
    return path if path.endswith("/") else path + "/"


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
    }


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    # No IAM, provider credentials or raw Cognito attributes appear in responses.
    public = {k: row.get(k) for k in (
        "id", "title", "slug", "status", "currency", "priceMinor",
        "variants", "descriptionHtml", "tagline",
        "categories", "imageRefs", "catalogImageKey", "canonicalPath",
        "websiteEnabled", "metaEnabled", "createdAt", "updatedAt",
        "seoTitle", "seoDescription",
    ) if k in row}
    if "variants" in public:
        public["variants"] = [{k: v[k] for k in ("sku", "id", "label", "priceMinor") if k in v}
                              for v in row.get("variants", [])]
    return public


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
    image_key = ""
    if body.get("catalogImageKey") not in (None, ""):
        image_key = _catalog_image_key(body.get("catalogImageKey"))
    website_enabled = _channel_flag(body.get("websiteEnabled", False), "websiteEnabled")
    meta_enabled = _channel_flag(body.get("metaEnabled", False), "metaEnabled")
    if website_enabled or meta_enabled:
        raise ValueError("new products start draft with publication channels disabled")
    row = {
        "id": "native:" + slug,
        "title": title,
        "slug": slug,
        "status": "draft",  # never publish new merchandise automatically
        "currency": "INR",
        "priceMinor": min(v["priceMinor"] for v in rows),
        "variants": rows,
        "descriptionHtml": str(body.get("descriptionHtml") or "")[:10000],
        "tagline": str(body.get("tagline") or "")[:600],
        "categories": [],
        "imageRefs": [_catalog_image_url(image_key)] if image_key else [],
        "catalogImageKey": image_key,
        "canonicalPath": _canonical_path(body.get("canonicalPath") or ("/shop/" + slug + "/")),
        "websiteEnabled": website_enabled,
        "metaEnabled": meta_enabled,
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
    if "catalogImageKey" in body:
        raw_key = body["catalogImageKey"]
        if isinstance(raw_key, str) and not raw_key.strip():
            updates["catalogImageKey"] = ""
            updates["imageRefs"] = []
        else:
            key = _catalog_image_key(raw_key)
            updates["catalogImageKey"] = key
            updates["imageRefs"] = [_catalog_image_url(key)]
    if "canonicalPath" in body:
        updates["canonicalPath"] = _canonical_path(body["canonicalPath"])
    if "websiteEnabled" in body:
        updates["websiteEnabled"] = _channel_flag(body["websiteEnabled"], "websiteEnabled")
    if "metaEnabled" in body:
        updates["metaEnabled"] = _channel_flag(body["metaEnabled"], "metaEnabled")
    target_status = str(updates.get("status", old.get("status") or "draft"))
    target_image = str(updates.get("catalogImageKey", old.get("catalogImageKey") or ""))
    target_website = bool(updates.get("websiteEnabled", old.get("websiteEnabled", False)))
    target_meta = bool(updates.get("metaEnabled", old.get("metaEnabled", False)))
    if (target_website or target_meta) and target_status != "active":
        raise ValueError("channel publication requires status active")
    if (target_website or target_meta) and not target_image:
        raise ValueError("channel publication requires an approved catalogImageKey")
    if not updates:
        return 400, {"error": "NO_EDITABLE_FIELDS"}
    new_updated = _now()
    if new_updated <= expected:
        from datetime import timedelta
        previous = datetime.fromisoformat(expected.replace("Z", "+00:00"))
        new_updated = (previous + timedelta(milliseconds=1)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
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


def _update_variant(table, product_id: str, sku: str,
                    body: dict[str, Any], who: str
                    ) -> tuple[int, dict[str, Any]]:
    """Update only one existing variant via a conditioned atomic DynamoDB update.

    The SKU and product ID never change, preserving all historical retailer IDs.
    Products are always available; stock counters are not editable.
    """
    old = _get(table, product_id)
    if not old:
        return 404, {"error": "PRODUCT_NOT_FOUND"}
    expected = body.get("expectedUpdatedAt")
    if not isinstance(expected, str) or expected != old.get("updatedAt"):
        return 409, {"error": "PRODUCT_VERSION_CONFLICT"}
    variants = old.get("variants") or []
    matches = [(i, v) for i, v in enumerate(variants)
               if str(v.get("sku") or v.get("id") or "") == sku]
    if len(matches) != 1:
        return 404, {"error": "VARIANT_NOT_FOUND"}
    index, prior = matches[0]
    if any(x not in {"expectedUpdatedAt", "priceMinor", "label"}
           for x in body):
        return 400, {"error": "IMMUTABLE_VARIANT_FIELD"}
    if not any(k in body for k in ("priceMinor", "label")):
        return 400, {"error": "NO_EDITABLE_FIELDS"}

    vals: dict[str, Any] = {":expected": expected, ":sku": sku}
    names = {"#id": "id", "#updated": "updatedAt",
             "#vs": "variants", "#sku": "sku",
             "#editor": "lastEditedBy"}
    setters = ["#updated = :now", "#editor = :editor"]
    vals[":now"] = _now()
    vals[":editor"] = who
    condition = ("attribute_exists(#id) AND #updated = :expected "
                 f"AND #vs[{index}].#sku = :sku")
    if "priceMinor" in body:
        price = _minor(body["priceMinor"])
        vals[":price"] = price
        names["#price"] = "priceMinor"
        setters.append(f"#vs[{index}].#price = :price")
        # Product-level price is the displayed floor, not the authority for
        # multi-variant checkout. Re-evaluate against the other variant prices.
        all_prices = [
            price if i == index else int(v.get("priceMinor", old.get("priceMinor", 0)))
            for i, v in enumerate(variants)
        ]
        vals[":floor"] = min(all_prices)
        setters.append("#price = :floor")
    if "label" in body:
        vals[":label"] = _text(body["label"], "label", 100)
        names["#label"] = "label"
        setters.append(f"#vs[{index}].#label = :label")
    try:
        table.update_item(
            Key={"id": product_id},
            UpdateExpression="SET " + ", ".join(setters),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )
    except Exception as error:
        if (getattr(error, "response", {}).get("Error", {}).get("Code") ==
                "ConditionalCheckFailedException"):
            return 409, {"error": "VARIANT_VERSION_OR_STOCK_CONFLICT"}
        raise
    new = _get(table, product_id)
    return 200, {"product": _public_row(new or old)}


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
    from urllib.parse import unquote
    segments = [unquote(s) for s in suffix.split("/") if s]
    if len(segments) > 3 or (len(segments) > 1 and
        not (len(segments) == 3 and segments[1] == "variants")):
        return _resp(404, {"error": "NOT_FOUND"}, origin)
    product_id = segments[0] if segments else ""
    try:
        if method == "GET":
            if len(segments) > 1:
                return _resp(404, {"error": "NOT_FOUND"}, origin)
            if product_id:
                row = _get(table, product_id)
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
        if method == "POST" and not product_id:
            status, data = _create(table, body, who)
        elif method == "PATCH" and len(segments) == 3:
            status, data = _update_variant(table, product_id, segments[2], body, who)
        elif method == "PATCH" and len(segments) == 1:
            status, data = _update(table, product_id, body, who)
        elif method == "DELETE" and len(segments) == 1:
            # Soft archive with the same version lock; never delete an order's product.
            status, data = _update(table, product_id, {
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
