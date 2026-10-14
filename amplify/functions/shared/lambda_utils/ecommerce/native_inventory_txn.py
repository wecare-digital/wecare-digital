"""Atomic DynamoDB reservation for AWS-native checkout.

The previous native_inventory reserve/release used 2 independent writes and
could lose or double-credit inventory across retries. Here the commerce-keys
claim(s) and product decrement(s) happen in ONE TransactWriteItems call.

Important DynamoDB restriction: a transaction may not contain two operations
targeting one item. Group all variants of a product into ONE update expression.
No gateway call occurs in this module. The checkout adapter passes a proven
PaymentAttempt ID and frozen server-priced basket; never a client price.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from boto3.dynamodb.types import TypeSerializer

MAX_LINES = 40
SERIALIZER = TypeSerializer()


class ReservationConflict(ValueError):
    """Duplicate, unavailable, ambiguous or mismatched stock reservation."""


class ReservationUnavailable(RuntimeError):
    """DynamoDB could not prove its atomic reservation outcome."""


def _val(v):
    return SERIALIZER.serialize(v)


def _map(mapping):
    return {str(k): _val(v) for k, v in mapping.items()}


def _integer(value, name: str, *, minimum: int = 0):
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ReservationConflict(name + " must be whole")
        value = int(value)
    if type(value) is not int or value < minimum:
        raise ReservationConflict(name + " is invalid")
    return value


def key_of(attempt_id: str, variant_id: str) -> str:
    if (not isinstance(attempt_id, str) or not attempt_id or
            len(attempt_id) > 100 or not isinstance(variant_id, str) or
            not variant_id or len(variant_id) > 150):
        raise ReservationConflict("invalid attempt or variant identity")
    return "INVRES#" + attempt_id + "#" + variant_id


def _when() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _parse(
    items: Sequence[Mapping[str, Any]],
    read_product: Callable[[str], Mapping[str, Any] | None],
    *, require_stock: bool,
):
    if (not isinstance(items, (list, tuple)) or
            not 1 <= len(items) <= MAX_LINES):
        raise ReservationConflict("basket must contain 1..40 variants")
    seen = set()
    parsed = []
    cache: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise ReservationConflict("invalid item")
        pid, vid = str(item.get("productId") or ""), str(item.get("variantId") or "")
        qty = _integer(item.get("quantity"), "quantity", minimum=1)
        if qty > 100000 or not pid or not vid or (pid, vid) in seen:
            raise ReservationConflict("invalid or duplicate variant")
        seen.add((pid, vid))
        if pid not in cache:
            cache[pid] = read_product(pid)
        product = cache[pid]
        if not isinstance(product, Mapping):
            raise ReservationConflict("product missing")
        if require_stock and str(product.get("status") or "active") != "active":
            raise ReservationConflict("product not active")
        matches = [(idx, variant) for idx, variant in enumerate(product.get("variants") or [])
                   if str(variant.get("sku") or variant.get("id") or "") == vid]
        if len(matches) != 1:
            raise ReservationConflict("variant missing or duplicated")
        idx, variant = matches[0]
        available = _integer(variant.get("inventory"), "inventory")
        if require_stock and available < qty:
            raise ReservationConflict("insufficient stock")
        parsed.append((pid, vid, qty, idx))
    return parsed


def _claim(attempt_id, pid, vid, qty, status):
    return {
        "orderId": key_of(attempt_id, vid),
        "kind": "AWS_NATIVE_STOCK_RESERVATION",
        "paymentAttemptId": attempt_id,
        "productId": pid,
        "variantId": vid,
        "quantity": qty,
        "status": status,
    }


def _state(read_key, attempt_id, parsed, expected):
    return all(
        isinstance((row := read_key(key_of(attempt_id, vid))), Mapping)
        and all(row.get(k) == v for k, v in
                _claim(attempt_id, pid, vid, qty, expected).items())
        for pid, vid, qty, _ in parsed
    )


def _product_updates(parsed, *, products_table: str, operation: str,
                     require_active: bool):
    grouped = defaultdict(list)
    for pid, vid, qty, index in parsed:
        grouped[pid].append((vid, qty, index))
    updates = []
    for pid, group in grouped.items():
        names = {
            "#variants": "variants",
            "#inventory": "inventory",
            "#sku": "sku",
            "#updated": "updatedAt",
        }
        values = {":newUpdate": _when()}
        sets = ["#updated = :newUpdate"]
        guards = ["attribute_exists(id)"]
        if require_active:
            names["#status"] = "status"
            values[":active"] = "active"
            guards.append("#status = :active")
        for ordinal, (vid, qty, index) in enumerate(group):
            var_path = f"#variants[{index}]"
            qty_arg, sku_arg = f":q{ordinal}", f":sku{ordinal}"
            values[qty_arg] = qty
            values[sku_arg] = vid
            arithmetic = "-" if operation == "reserve" else "+"
            sets.append(
                f"{var_path}.#inventory = {var_path}.#inventory {arithmetic} {qty_arg}"
            )
            guards.append(f"{var_path}.#sku = {sku_arg}")
            if operation == "reserve":
                guards.append(f"{var_path}.#inventory >= {qty_arg}")
        updates.append({"Update": {
            "TableName": products_table,
            "Key": _map({"id": pid}),
            "UpdateExpression": "SET " + ", ".join(sets),
            "ConditionExpression": " AND ".join(guards),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": _map(values),
        }})
    return updates


def reserve_basket(
    client: Any,
    read_product: Callable[[str], Mapping[str, Any] | None],
    read_key: Callable[[str], Mapping[str, Any] | None],
    *,
    products_table: str,
    keys_table: str,
    attempt_id: str,
    items: Sequence[Mapping[str, Any]],
):
    # Check an already-established reservation BEFORE checking currently
    # available stock: successful reservation itself reduced availability.
    # A retry with the same attempt must not look sold out after its own debit.
    parsed = _parse(items, read_product, require_stock=False)
    if _state(read_key, attempt_id, parsed, "RESERVED"):
        return {"reserved": True, "existing": True, "lines": len(parsed)}
    parsed = _parse(items, read_product, require_stock=True)
    tx = []
    for pid, vid, qty, _idx in parsed:
        tx.append({"Put": {
            "TableName": keys_table,
            "Item": _map(_claim(attempt_id, pid, vid, qty, "RESERVED")),
            "ConditionExpression": "attribute_not_exists(orderId)",
        }})
    tx.extend(_product_updates(parsed, products_table=products_table,
                               operation="reserve", require_active=True))
    if len(tx) > 100:
        raise ReservationConflict("basket exceeds transaction operation limit")
    content_hash = hashlib.sha256(json.dumps(
        [[pid, vid, qty] for pid, vid, qty, _ in parsed],
        separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    token = hashlib.sha256((attempt_id + ":reserve:" + content_hash).encode()).hexdigest()[:36]
    try:
        client.transact_write_items(TransactItems=tx, ClientRequestToken=token)
    except Exception as error:
        # A lost response is NOT a failure. Check all reservation rows before
        # admitting a retry; a partial or unknown result requires reconciliation.
        if _state(read_key, attempt_id, parsed, "RESERVED"):
            return {"reserved": True, "existing": True, "lines": len(parsed)}
        raise ReservationUnavailable("inventory reserve outcome not confirmed") from error
    return {"reserved": True, "existing": False, "lines": len(parsed)}


def release_basket(
    client: Any,
    read_product: Callable[[str], Mapping[str, Any] | None],
    read_key: Callable[[str], Mapping[str, Any] | None],
    *,
    products_table: str,
    keys_table: str,
    attempt_id: str,
    items: Sequence[Mapping[str, Any]],
    payment_terminal_confirmed: bool = False,
):
    # Never release for an ambiguous order, temporary provider timeout,
    # pending payment, or customer-return redirect.
    if payment_terminal_confirmed is not True:
        raise ReservationConflict("terminal payment failure not verified")
    parsed = _parse(items, read_product, require_stock=False)
    if _state(read_key, attempt_id, parsed, "RELEASED"):
        return {"released": True, "existing": True, "lines": len(parsed)}
    if not _state(read_key, attempt_id, parsed, "RESERVED"):
        raise ReservationConflict("stock reservation state is not fully RESERVED")
    tx = []
    for pid, vid, qty, _idx in parsed:
        tx.append({"Update": {
            "TableName": keys_table,
            "Key": _map({"orderId": key_of(attempt_id, vid)}),
            "UpdateExpression": "SET #status = :released",
            "ConditionExpression": (
                "#status = :reserved AND productId = :pid AND quantity = :qty"
            ),
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": _map({
                ":released": "RELEASED", ":reserved": "RESERVED",
                ":pid": pid, ":qty": qty,
            }),
        }})
    tx.extend(_product_updates(parsed, products_table=products_table,
                               operation="release", require_active=False))
    if len(tx) > 100:
        raise ReservationConflict("basket exceeds transaction operation limit")
    content_hash = hashlib.sha256(json.dumps(
        [[pid, vid, qty] for pid, vid, qty, _ in parsed],
        separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    token = hashlib.sha256((attempt_id + ":release:" + content_hash).encode()).hexdigest()[:36]
    try:
        client.transact_write_items(TransactItems=tx, ClientRequestToken=token)
    except Exception as error:
        if _state(read_key, attempt_id, parsed, "RELEASED"):
            return {"released": True, "existing": True, "lines": len(parsed)}
        raise ReservationUnavailable("stock release outcome not confirmed") from error
    return {"released": True, "existing": False, "lines": len(parsed)}
