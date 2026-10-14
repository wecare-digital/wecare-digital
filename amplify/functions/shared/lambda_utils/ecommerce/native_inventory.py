"""AWS-native inventory validation and atomic stock reservation.

Replaces the inventory half of Wix Cart V2 (`cart_v2.calculate` validates stock
against Wix) with a server-authoritative check against `ProductsTable` and an
atomic reservation on the commerce-keys table, mirroring `order_keys`' idioms
(conditional writes, idempotency, release/rollback).

WHY RESERVATION, NOT JUST A CHECK. A bare "is there stock?" read before payment
is a TOCTOU race: two carts both read 3-in-stock, both pass, both get charged,
and the second cannot be fulfilled. So stock is DECREMENTED under a condition at
reserve time and ADDED BACK on release (abandoned/failed attempt). The decrement
is `available = available - qty` guarded by `available >= qty`, which fails
closed when stock is insufficient — never oversells.

IDEMPOTENT. A reservation is keyed by (variantId + paymentAttemptId), so a retry
of the same attempt does not double-decrement: the second reserve finds the
existing reservation row and returns it unchanged. Release is keyed the same way
and is a no-op if nothing was reserved.

Integer units only. No float. The module holds no boto3 client and reads no
secret — the table is injected — so it is unit-testable offline, matching the
rest of the ecommerce library.

NOT WIRED until checkout runs native (CHECKOUT_MODE=AWS_NATIVE). This is the
inventory primitive the native cart calls; wiring it is a Phase-4 step.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Reservation rows live on the commerce-keys table (same table order_keys uses),
#: namespaced so they cannot collide with payment/order rows.
INVENTORY_RESERVATION_PREFIX = "INVRES#"


class InventoryError(RuntimeError):
    """A stock operation could not be completed for a reason that is not "out of stock"
    (a storage fault). Distinct from OutOfStock so a throttle is never read as sold out."""


class OutOfStock(ValueError):
    """Requested quantity exceeds available stock. Carries the variant for the caller."""

    def __init__(self, variant_id: str, requested: int, available: int) -> None:
        self.variant_id = variant_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient stock for {variant_id}: requested {requested}, available {available}")


def _int(value: Any) -> int:
    if isinstance(value, bool):
        raise InventoryError("inventory must be an integer, not a bool")
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise InventoryError("inventory must be a whole number")
        value = int(value)
    if type(value) is not int or value < 0:
        raise InventoryError("inventory must be a nonnegative integer")
    return value


def _is_conditional_failure(error: BaseException) -> bool:
    name = type(error).__name__
    code = getattr(error, "response", {}).get("Error", {}).get("Code", "") \
        if hasattr(error, "response") else ""
    return name == "ConditionalCheckFailedException" or code == "ConditionalCheckFailedException"


def available_units(product_row: Optional[Mapping[str, Any]], variant_id: str) -> int:
    """Available units for one variant, from a ProductsTable item. 0 if absent."""
    if not isinstance(product_row, Mapping):
        return 0
    for v in product_row.get("variants", []) or []:
        if str(v.get("sku") or v.get("id") or "") == variant_id:
            return _int(v.get("inventory", 0))
    # Single-variant / product-level inventory fallback.
    if str(product_row.get("id") or "") == variant_id or not product_row.get("variants"):
        return _int(product_row.get("inventory", 0))
    return 0


def validate_lines(product_reader, lines: Sequence[Mapping[str, Any]]) -> None:
    """Raise OutOfStock on the FIRST line that cannot be met. `product_reader(product_id)`
    returns the ProductsTable item (or None). Read-only — no reservation taken."""
    for line in lines:
        pid = str(line.get("product_id") or line.get("productId") or "")
        vid = str(line.get("variant_id") or line.get("variantId") or "")
        qty = _int(line.get("quantity", 0))
        if qty < 1:
            raise InventoryError("a cart line must request at least one unit")
        have = available_units(product_reader(pid), vid)
        if qty > have:
            raise OutOfStock(vid, qty, have)


def reserve(table: Any, products_table: Any, *, variant_id: str, product_id: str,
            quantity: int, attempt_id: str, key_attr: str = "orderId") -> Dict[str, Any]:
    """Atomically reserve `quantity` of `variant_id` for `attempt_id`.

    Two atomic steps, both fail-closed:
      1. A reservation CLAIM row keyed by (variant+attempt) — idempotent: a retry
         of the same attempt returns the existing row and does NOT decrement again.
      2. A conditional DECREMENT of the variant's inventory on ProductsTable,
         guarded by `inventory >= quantity`, which raises OutOfStock on a lost race.
    Returns the reservation row. Raises OutOfStock / InventoryError.
    """
    qty = _int(quantity)
    if qty < 1:
        raise InventoryError("reserve requires a positive quantity")
    res_key = f"{INVENTORY_RESERVATION_PREFIX}{variant_id}#{attempt_id}"

    # Step 1: idempotent claim. If it already exists, this attempt already reserved.
    existing = _get(table, key_attr, res_key)
    if existing is not None:
        return existing

    row = {key_attr: res_key, "recordType": "INVENTORY_RESERVATION",
           "variantId": variant_id, "productId": product_id,
           "quantity": qty, "paymentAttemptId": attempt_id, "status": "RESERVED"}
    try:
        table.put_item(Item=row,
                       ConditionExpression="attribute_not_exists(%s)" % key_attr)
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            # A concurrent reserve of the SAME attempt won; read it back.
            return _get(table, key_attr, res_key) or row
        raise InventoryError("could not claim reservation: %s" % type(error).__name__) from error

    # Step 2: atomic decrement guarded by availability. On failure, roll back the claim.
    try:
        _decrement_variant(products_table, product_id, variant_id, qty)
    except OutOfStock:
        _delete(table, key_attr, res_key)  # release the claim so a later restock can succeed
        raise
    except Exception as error:  # noqa: BLE001
        _delete(table, key_attr, res_key)
        raise InventoryError("could not decrement stock: %s" % type(error).__name__) from error
    return row


def release(table: Any, products_table: Any, *, variant_id: str, product_id: str,
            attempt_id: str, key_attr: str = "orderId") -> bool:
    """Release a reservation (abandoned/failed attempt): add the units back and mark the
    row released. Idempotent — returns False if there was nothing to release."""
    res_key = f"{INVENTORY_RESERVATION_PREFIX}{variant_id}#{attempt_id}"
    row = _get(table, key_attr, res_key)
    if row is None or row.get("status") == "RELEASED":
        return False
    qty = _int(row.get("quantity", 0))
    _increment_variant(products_table, product_id, variant_id, qty)
    try:
        table.update_item(
            Key={key_attr: res_key},
            UpdateExpression="SET #s = :released",
            ConditionExpression="#s = :reserved",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":released": "RELEASED", ":reserved": "RESERVED"},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return False  # someone else released concurrently; stock already returned once
        raise InventoryError("could not mark released: %s" % type(error).__name__) from error
    return True


# ── low-level ProductsTable atomic inventory moves ──────────────────────────────

def _decrement_variant(products_table: Any, product_id: str, variant_id: str, qty: int) -> None:
    """Atomic conditional decrement of a variant's inventory. Raises OutOfStock on
    insufficient stock. Uses a DynamoDB list-index update guarded by the current value.

    Variants are a list on the product item, so the update targets the matching index.
    The caller resolves the index; here we re-read to find it, then conditionally update
    guarded by the exact current value to stay atomic against concurrent writers.
    """
    item = _get(products_table, "id", product_id)
    if item is None:
        raise OutOfStock(variant_id, qty, 0)
    variants = item.get("variants") or []
    idx, current = _find_variant_index(variants, variant_id)
    if idx is None:
        # product-level inventory
        _conditional_add(products_table, product_id, "inventory",
                         delta=-qty, guard_min=qty, variant_id=variant_id)
        return
    _conditional_add(products_table, product_id, f"variants[{idx}].inventory",
                     delta=-qty, guard_min=qty, variant_id=variant_id, guard_path=True,
                     current=current)


def _increment_variant(products_table: Any, product_id: str, variant_id: str, qty: int) -> None:
    item = _get(products_table, "id", product_id)
    if item is None:
        return
    variants = item.get("variants") or []
    idx, _cur = _find_variant_index(variants, variant_id)
    path = "inventory" if idx is None else f"variants[{idx}].inventory"
    products_table.update_item(
        Key={"id": product_id},
        UpdateExpression="SET %s = %s + :q" % (path, path),
        ExpressionAttributeValues={":q": qty},
    )


def _conditional_add(products_table: Any, product_id: str, path: str, *, delta: int,
                     guard_min: int, variant_id: str, guard_path: bool = False,
                     current: Optional[int] = None) -> None:
    try:
        products_table.update_item(
            Key={"id": product_id},
            UpdateExpression="SET %s = %s + :d" % (path, path),
            ConditionExpression="%s >= :min" % path,
            ExpressionAttributeValues={":d": delta, ":min": guard_min},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise OutOfStock(variant_id, guard_min, max(0, (current or 0))) from None
        raise


def _find_variant_index(variants: Sequence[Mapping[str, Any]], variant_id: str):
    for i, v in enumerate(variants):
        if str(v.get("sku") or v.get("id") or "") == variant_id:
            return i, _int(v.get("inventory", 0))
    return None, None


def _get(table: Any, key_attr: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        return table.get_item(Key={key_attr: key}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise InventoryError("could not read %r: %s" % (key, type(error).__name__)) from error


def _delete(table: Any, key_attr: str, key: str) -> None:
    try:
        table.delete_item(Key={key_attr: key})
    except Exception as error:  # noqa: BLE001
        raise InventoryError("could not release %r: %s" % (key, type(error).__name__)) from error


__all__ = [
    "INVENTORY_RESERVATION_PREFIX", "InventoryError", "OutOfStock",
    "available_units", "validate_lines", "reserve", "release",
]
