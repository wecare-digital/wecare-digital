"""Atomic AWS-native inventory reservation and release.

The legacy native_inventory.reserve() did a claim Put followed by a separate
product Update, and its release() returned stock before writing the release
status. Both allow lost/duplicate stock under concurrent requests or Lambda
timeouts. THIS module performs all rows of a basket in ONE TransactWriteItems
call, using low-level DynamoDB AttributeValues and conditional stock guards.

Never auto-release a reservation until the Razorpay/payment-attempt ledger has
proved the payment terminal-failed/cancelled and cannot subsequently capture.
An ambiguous gateway outcome retains its stock claim for reconciliation.

No network, secrets, or SDK instantiation here: production injects a boto3
DynamoDB client; unit tests inject a fake that records/validates transactions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from boto3.dynamodb.types import TypeSerializer

MAX_LINES = 40
SERIALIZER = TypeSerializer()


class ReservationConflict(ValueError):
    pass


class ReservationUnavailable(RuntimeError):
    pass


def _val(value: Any) -> dict:
    return SERIALIZER.serialize(value)


def _map(value: Mapping[str, Any]) -> dict:
    return {str(k): _val(v) for k, v in value.items()}


def _identity(item: Mapping[str, Any]) -> tuple[str, str, int]:
    pid = str(item.get("productId") or "")
    vid = str(item.get("variantId") or "")
    qty = item.get("quantity")
    if not pid or not vid or type(qty) is not int or not 1 <= qty <= 100000:
        raise ReservationConflict("invalid inventory line")
    return pid, vid, qty


def key_of(attempt_id: str, variant_id: str) -> str:
    if not attempt_id or len(attempt_id) > 100 or not variant_id:
        raise ReservationConflict("invalid reservation identity")
    return f"INVRES#{attempt_id}#{variant_id}"


def _entries(
    items: Sequence[Mapping[str, Any]],
    product_reader: Callable[[str], Mapping[str, Any] | None],
) -> list[tuple[str, str, int, int]]:
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= MAX_LINES:
        raise ReservationConflict("native reservation must contain 1..40 distinct variants")
    found = set()
    out = []
    for item in items:
        pid, vid, qty = _identity(item)
        if (pid, vid) in found:
            raise ReservationConflict("duplicate variant in native reservation")
        found.add((pid, vid))
        product = product_reader(pid)
        if not isinstance(product, Mapping) or (
            str(product.get("status") or "active") != "active"
        ):
            raise ReservationConflict("product is unavailable")
        matches = [(idx, v) for idx, v in enumerate(product.get("variants") or [])
                   if str(v.get("sku") or v.get("id") or "") == vid]
        if len(matches) != 1:
            raise ReservationConflict("variant is unavailable")
        idx, variant = matches[0]
        available = variant.get("inventory")
        if type(available) is not int or available < qty:
            raise ReservationConflict("variant has insufficient available stock")
        out.append((pid, vid, qty, idx))
    return out


def _reservation_row(attempt_id: str, pid: str, vid: str, qty: int, status: str):
    return {
        "orderId": key_of(attempt_id, vid),
        "kind": "AWS_NATIVE_STOCK_RESERVATION",
        "paymentAttemptId": attempt_id,
        "productId": pid,
        "variantId": vid,
        "quantity": qty,
        "status": status,
    }


def _all_existing(keys_reader, attempt_id, items, status):
    for pid, vid, qty, _idx in items:
        row = keys_reader(key_of(attempt_id, vid))
        expected = _reservation_row(attempt_id, pid, vid, qty, status)
        if not isinstance(row, Mapping) or any(
            row.get(k) != v for k, v in expected.items()
        ):
            return False
    return True


def reserve_basket(
    client: Any,
    product_reader: Callable[[str], Mapping[str, Any] | None],
    keys_reader: Callable[[str], Mapping[str, Any] | None],
    *,
    products_table: str,
    keys_table: str,
    attempt_id: str,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = _entries(items, product_reader)
    if _all_existing(keys_reader, attempt_id, rows, "RESERVED"):
        return {"reserved": True, "existing": True, "lines": len(rows)}
    tx = []
    for pid, vid, qty, idx in rows:
        row = _reservation_row(attempt_id, pid, vid, qty, "RESERVED")
        tx.append({"Put": {
            "TableName": keys_table, "Item": _map(row),
            "ConditionExpression": "attribute_not_exists(orderId)",
        }})
        tx.append({"Update": {
            "TableName": products_table, "Key": _map({"id": pid}),
            "UpdateExpression": (
                f"SET #vs[{idx}].#inventory = #vs[{idx}].#inventory - :qty"
            ),
            "ConditionExpression": (
                f"attribute_exists(id) AND #status = :active "
                f"AND #vs[{idx}].#sku = :sku AND #vs[{idx}].#inventory >= :qty"
            ),
            "ExpressionAttributeNames": {
                "#vs": "variants", "#inventory": "inventory",
                "#status": "status", "#sku": "sku",
            },
            "ExpressionAttributeValues": _map({
                ":qty": qty, ":sku": vid, ":active": "active",
            }),
        }})
    payload_hash = hashlib.sha256(json.dumps(
        [[pid, vid, qty] for pid, vid, qty, _ in rows], sort_keys=True
    ).encode()).hexdigest()
    token = hashlib.sha256((attempt_id + ":" + payload_hash).encode()).hexdigest()[:36]
    try:
        client.transact_write_items(TransactItems=tx, ClientRequestToken=token)
    except Exception as error:
        # Failed/duplicate transactions never cause an individual stock change.
        if _all_existing(keys_reader, attempt_id, rows, "RESERVED"):
            return {"reserved": True, "existing": True, "lines": len(rows)}
        raise ReservationUnavailable("stock transaction not confirmed") from error
    return {"reserved": True, "existing": False, "lines": len(rows)}


def release_basket(
    client: Any,
    keys_reader: Callable[[str], Mapping[str, Any] | None],
    *,
    products_table: str,
    keys_table: str,
    attempt_id: str,
    items: Sequence[Mapping[str, Any]],
    payment_terminal_confirmed: bool = False,
) -> dict[str, Any]:
    # NEVER infer that a gateway error means payment failed. The caller must
    # prove a terminal, unrecoverable failure from the actual payment ledger.
    if payment_terminal_confirmed is not True:
        raise ReservationConflict("terminal payment status not confirmed")
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= MAX_LINES:
        raise ReservationConflict("invalid reservation lines")
    parsed = [_identity(item) for item in items]
    if len({(p, v) for p, v, _ in parsed}) != len(parsed):
        raise ReservationConflict("duplicate reservation variants")
    tx = []
    already_released = 0
    for pid, vid, qty in parsed:
        key = key_of(attempt_id, vid)
        row = keys_reader(key)
        if not isinstance(row, Mapping):
            raise ReservationConflict("reservation row missing; refuse stock credit")
        if row.get("status") == "RELEASED":
            already_released += 1
            continue
        expected = _reservation_row(attempt_id, pid, vid, qty, "RESERVED")
        if any(row.get(k) != v for k, v in expected.items()):
            raise ReservationConflict("reservation identity/status mismatch")
        # Update stock by indexed variant with a checked sku. Any variant
        # reorder or deleted product must cause the entire release to refuse.
        # Production passes pre-read variant indexes through each item.
        idx = items[parsed.index((pid, vid, qty))].get("variantIndex")
        if type(idx) is not int or idx < 0:
            raise ReservationConflict("release requires a verified variantIndex")
        tx.append({"Update": {
            "TableName": keys_table, "Key": _map({"orderId": key}),
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
        tx.append({"Update": {
            "TableName": products_table, "Key": _map({"id": pid}),
            "UpdateExpression": (
                f"SET #vs[{idx}].#inventory = #vs[{idx}].#inventory + :qty"
            ),
            "ConditionExpression": (
                f"attribute_exists(id) AND #vs[{idx}].#sku = :sku"
            ),
            "ExpressionAttributeNames": {
                "#vs": "variants", "#inventory": "inventory", "#sku": "sku",
            },
            "ExpressionAttributeValues": _map({":qty": qty, ":sku": vid}),
        }})
    if already_released == len(parsed):
        return {"released": True, "existing": True, "lines": len(parsed)}
    if already_released:
        raise ReservationConflict("partial release state needs manual reconciliation")
    token = hashlib.sha256(
        (attempt_id + ":release:" + json.dumps(parsed)).encode()
    ).hexdigest()[:36]
    try:
        client.transact_write_items(TransactItems=tx, ClientRequestToken=token)
    except Exception as error:
        if all((keys_reader(key_of(attempt_id, vid)) or {}).get("status") ==
               "RELEASED" for _pid, vid, _qty in parsed):
            return {"released": True, "existing": True, "lines": len(parsed)}
        raise ReservationUnavailable("stock release transaction not confirmed") from error
    return {"released": True, "existing": False, "lines": len(parsed)}
