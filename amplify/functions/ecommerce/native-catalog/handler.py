"""Staff-only AWS ProductsTable editor for /native-catalog/products.

Do not expose through API Gateway without staff Cognito auth and a dedicated
least-privilege IAM role. No Wix runtime dependencies or product hard-deletes.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3

from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_response, extract_origin, options_response

TABLE = os.environ.get("PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable")
REGION = os.environ.get("AWS_REGION", "us-east-1")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PRICE = 100_000_000
ALLOWED_STATUS = {"draft", "active", "archived"}


class Refused(ValueError):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def _body(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        raise Refused(400, "INVALID_JSON") from None
    if not isinstance(body, dict):
        raise Refused(400, "INVALID_BODY")
    return body


def _text(value, label, limit=5000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Refused(400, "INVALID_" + label)
    return value.strip()


def _price(value):
    if type(value) is not int or not 0 <= value <= MAX_PRICE:
        raise Refused(400, "INVALID_PRICE")
    return value


def _version(body):
    return _text(body.get("expectedUpdatedAt"), "VERSION", 80)


def _ddb_json(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return str(value)
    if isinstance(value, dict):
        return {k: _ddb_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ddb_json(x) for x in value]
    return value


def _get(table, pid):
    return table.get_item(Key={"id": pid}, ConsistentRead=True).get("Item")


def _get_or_404(table, pid):
    item = _get(table, pid)
    if item is None:
        raise Refused(404, "PRODUCT_NOT_FOUND")
    return item


def _scan(table):
    items = []
    kwargs = {"ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if len(items) > 10000:
            raise Refused(503, "CATALOG_TOO_LARGE")
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(items, key=lambda p: (str(p.get("title", "")).lower(), str(p.get("id", ""))))


def _check_unique_slug(table, slug):
    # 10 products today; strong full scan avoids eventually consistent GSI lookup.
    if any(x.get("slug") == slug for x in _scan(table)):
        raise Refused(409, "SLUG_IN_USE")


def _create(table, body):
    title = _text(body.get("title"), "TITLE", 200)
    slug = _text(body.get("slug"), "SLUG", 150)
    if not SLUG.fullmatch(slug):
        raise Refused(400, "INVALID_SLUG")
    if body.get("currency", "INR") != "INR":
        raise Refused(400, "INVALID_CURRENCY")
    raw = body.get("variants")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise Refused(400, "ONE_INITIAL_VARIANT_REQUIRED")
    p = _price(raw[0].get("priceMinor"))
    if type(raw[0].get("inventory")) is not int or raw[0]["inventory"] != 0:
        raise Refused(400, "NEW_PRODUCT_MUST_START_WITH_ZERO_STOCK")
    _check_unique_slug(table, slug)
    ts = _now()
    variant = {"sku": str(uuid.uuid4()), "label": _text(raw[0].get("label", "Standard"),
               "VARIANT_LABEL", 120), "priceMinor": p, "inventory": 0}
    item = {
        "id": str(uuid.uuid4()), "title": title, "slug": slug, "status": "draft",
        "currency": "INR", "priceMinor": p, "inventory": 0,
        "descriptionHtml": str(body.get("descriptionHtml") or "")[:20000],
        "tagline": "", "variants": [variant], "imageRefs": [],
        "categories": [], "createdAt": ts, "updatedAt": ts,
    }
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
    return item


def _update_product(table, pid, body):
    old = _get_or_404(table, pid)
    version = _version(body)
    changes = {}
    for name in ("title", "tagline", "descriptionHtml"):
        if name in body:
            changes[name] = _text(body[name], name.upper(), 200 if name == "title" else 20000) if name == "title" else str(body[name])[:20000]
    if "status" in body:
        if body["status"] not in ALLOWED_STATUS:
            raise Refused(400, "INVALID_STATUS")
        changes["status"] = body["status"]
    if not changes:
        raise Refused(400, "NO_CHANGES")
    return _conditional_update(table, pid, version, changes)


def _conditional_update(table, pid, version, changes):
    ts = _now()
    if ts == version:
        ts = ts[:-1] + "1Z"
    names = {"#u": "updatedAt", "#id": "id"}
    values = {":old": version, ":next": ts}
    assignments = ["#u = :next"]
    for i, (key, value) in enumerate(changes.items()):
        names[f"#f{i}"] = key
        values[f":v{i}"] = value
        assignments.append(f"#f{i} = :v{i}")
    try:
        result = table.update_item(
            Key={"id": pid},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="attribute_exists(#id) AND #u = :old",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return result["Attributes"]
    except Exception as error:
        if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise Refused(409, "STALE_PRODUCT_VERSION") from None
        raise


def _variant_update(table, pid, sku, body):
    old = _get_or_404(table, pid)
    version = _version(body)
    variants = old.get("variants") or []
    index = next((i for i, v in enumerate(variants) if v.get("sku") == sku), None)
    if index is None:
        raise Refused(404, "VARIANT_NOT_FOUND")
    old_variant = variants[index]
    delta = body.get("stockDelta", 0)
    if type(delta) is not int or abs(delta) > 1_000_000:
        raise Refused(400, "INVALID_STOCK_ADJUSTMENT")
    existing_stock = old_variant.get("inventory", 0)
    if type(existing_stock) not in (int, Decimal):
        raise Refused(409, "STOCK_CORRUPT")
    new_stock = int(existing_stock) + delta
    if not 0 <= new_stock <= 1_000_000_000:
        raise Refused(409, "INSUFFICIENT_STOCK")
    new_variants = [dict(v) for v in variants]
    new_variants[index]["inventory"] = new_stock
    if "priceMinor" in body:
        new_variants[index]["priceMinor"] = _price(body["priceMinor"])
    if "label" in body:
        new_variants[index]["label"] = _text(body["label"], "VARIANT_LABEL", 120)
    # Full-array replacement is guarded by the exact previous updatedAt. Concurrent
    # reservations *must also update the product version* or a lost update is possible.
    return _conditional_update(table, pid, version, {"variants": new_variants})


def _archive(table, pid, body):
    _get_or_404(table, pid)
    return _conditional_update(table, pid, _version(body), {"status": "archived"})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    origin = extract_origin(event)
    http = event.get("requestContext", {}).get("http", {})
    method = str(http.get("method") or event.get("httpMethod") or "GET").upper()
    if method == "OPTIONS":
        return options_response(origin)
    # Explicitly reject non-Gateway invokes even though shared middleware
    # exempts them as internal Lambda-to-Lambda operations.
    rc = event.get("requestContext") or {}
    if not (rc.get("apiId") or rc.get("domainName")):
        return cors_response(403, {"error": "GATEWAY_REQUIRED"}, origin)
    auth = require_auth(event, required_role="Operator")
    if auth is not None:
        return auth
    path = str(http.get("path") or event.get("rawPath") or "")
    segments = path.split("/native-catalog/products", 1)
    if len(segments) != 2:
        return cors_response(404, {"error": "NOT_FOUND"}, origin)
    suffix = segments[1].strip("/")
    parts = suffix.split("/") if suffix else []
    try:
        table = _table()
        if method == "GET" and not parts:
            data = _scan(table)
            return cors_response(200, {"ok": True, "products": _ddb_json(data)}, origin)
        if method == "POST" and not parts:
            product = _create(table, _body(event))
        elif method == "PATCH" and len(parts) == 1:
            product = _update_product(table, parts[0], _body(event))
        elif method == "PATCH" and len(parts) == 3 and parts[1] == "variants":
            product = _variant_update(table, parts[0], parts[2], _body(event))
        elif method == "DELETE" and len(parts) == 1:
            product = _archive(table, parts[0], _body(event))
        else:
            raise Refused(404, "NOT_FOUND")
        return cors_response(200, {"ok": True, "product": _ddb_json(product)}, origin)
    except Refused as exc:
        return cors_response(exc.status, {"error": exc.code}, origin)
    except Exception:
        # Do not reflect exceptions, AWS metadata or customer information.
        return cors_response(503, {"error": "CATALOG_TEMPORARILY_UNAVAILABLE"}, origin)
