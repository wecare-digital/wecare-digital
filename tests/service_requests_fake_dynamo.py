"""An in-memory request table for the Phase O-1 service-request store.

A SUBCLASS of `tests/coupon_fake_dynamo.FakeTable`, not a copy, so it inherits that fake's
discipline unchanged: **any expression form it does not understand raises rather than being
assumed to succeed**, `calls` is the attempt log and `applied` the outcome log, and every request
is one indivisible evaluate-then-apply under the lock.

What it adds, and only this:

* `TransactWriteItems` with `Put`, `Update` and `ConditionCheck` items, all-or-nothing, with
  `CancellationReasons` carrying `{"Code": "ConditionalCheckFailed"}` per failed item and
  `{"Code": "None"}` for the rest -- the shape `service_request_store` branches on by index;
* `list_append(if_not_exists(X, :empty), :v)` in an update, which the request store uses to
  record every order an intent paid for;
* `ExclusiveStartKey` / `LastEvaluatedKey` on a GSI query, so the list cursor is exercised;
* `arm_transaction_override(fn)`: a hook a test uses to inject an interleaving (a concurrent
  activation landing between a read and the transaction) at a precise point.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from coupon_fake_dynamo import (  # noqa: F401 - FakeClientError is re-exported for the tests
    FakeClientError, FakeTable, UnsupportedFakeOperation, _apply_update, _deserialise,
    _deserialise_map, _evaluate_condition)

_LIST_APPEND = re.compile(
    r"([#\w]+)\s*=\s*list_append\(\s*if_not_exists\(\s*([#\w]+)\s*,\s*(:\w+)\s*\)\s*,\s*(:\w+)\s*\)",
    re.IGNORECASE)


def apply_update(expression: str, row: Dict[str, Any], values: Dict[str, Any],
                 names: Dict[str, str]) -> Dict[str, Any]:
    """The coupon fake's updater plus `list_append(if_not_exists(...))`, applied first."""
    out = dict(row)
    remaining = expression
    for match in list(_LIST_APPEND.finditer(expression)):
        target = names.get(match.group(1), match.group(1))
        guard = names.get(match.group(2), match.group(2))
        base = out.get(guard, values[match.group(3)])
        out[target] = list(base) + list(values[match.group(4)])
        remaining = remaining.replace(match.group(0), "")
    remaining = re.sub(r",\s*,", ",", remaining)
    remaining = re.sub(r",\s*$", "", remaining.strip())
    remaining = re.sub(r"SET\s*,", "SET ", remaining)
    if remaining.strip().upper() in ("", "SET"):
        return out
    return _apply_update(remaining, out, values, names)


class RequestTable(FakeTable):
    """`stack-wecare-digital-ServiceRequestsTable`, keyed on `requestId`, with the two GSIs."""

    def __init__(self, name: str = "stack-wecare-digital-ServiceRequestsTable") -> None:
        super().__init__(key_attr="requestId", name=name, indexes={
            "customerId-createdAt-index": ("customerId", "createdAt"),
            "orderId-index": ("orderId", None),
        })
        self.transaction_hook: Optional[Callable[[List[Dict[str, Any]]], None]] = None

    def arm_transaction_override(self, hook: Callable[[List[Dict[str, Any]]], None]) -> None:
        """Run `hook(items)` once, inside the next transaction, BEFORE its conditions are read."""
        self.transaction_hook = hook

    def update_item(self, Key=None, UpdateExpression="", ConditionExpression=None,
                    ExpressionAttributeValues=None, ExpressionAttributeNames=None,
                    ReturnValues=None, **kwargs):
        if "list_append" in str(UpdateExpression):
            raise UnsupportedFakeOperation("list_append is only used inside a transaction")
        return super().update_item(Key=Key, UpdateExpression=UpdateExpression,
                                   ConditionExpression=ConditionExpression,
                                   ExpressionAttributeValues=ExpressionAttributeValues,
                                   ExpressionAttributeNames=ExpressionAttributeNames,
                                   ReturnValues=ReturnValues, **kwargs)

    def transact_write_items(self, TransactItems=None, **_):
        hook, self.transaction_hook = self.transaction_hook, None
        if hook is not None:
            hook(list(TransactItems or []))
        with self._lock:
            items = list(TransactItems or [])
            self.calls.append(("transact_write_items", {"TransactItems": items}))
            self._fail_if_armed("transact_write_items")
            if not items:
                raise UnsupportedFakeOperation("a transaction needs at least one item")
            plan: List[Tuple[str, Any, Dict[str, Any]]] = []
            outcomes: List[bool] = []
            seen_keys = set()
            for index, entry in enumerate(items):
                where = f"TransactItems[{index}]"
                if not isinstance(entry, dict) or len(entry) != 1:
                    raise UnsupportedFakeOperation(f"{where}: one operation per item")
                (operation, body), = entry.items()
                if operation not in ("Put", "Update", "ConditionCheck"):
                    raise UnsupportedFakeOperation(f"{where}: {operation} is not implemented")
                if body.get("TableName") != self.name:
                    raise UnsupportedFakeOperation(
                        f"{where}: TableName {body.get('TableName')!r} is not {self.name!r}")
                condition = body.get("ConditionExpression")
                if not condition:
                    raise UnsupportedFakeOperation(
                        f"{where}: every item in this design carries a ConditionExpression")
                values = _deserialise_map(body.get("ExpressionAttributeValues") or {},
                                          where=f"{where}.ExpressionAttributeValues")
                names = {str(k): str(v) for k, v in
                         (body.get("ExpressionAttributeNames") or {}).items()}
                if operation == "Put":
                    item = _deserialise_map(body.get("Item"), where=f"{where}.Item")
                    key = item[self.key_attr]
                    payload: Dict[str, Any] = {"item": item}
                else:
                    key_map = _deserialise_map(body.get("Key"), where=f"{where}.Key")
                    key = key_map[self.key_attr]
                    payload = {"expression": str(body.get("UpdateExpression") or ""),
                               "values": values, "names": names}
                if key in seen_keys:
                    raise UnsupportedFakeOperation(
                        f"{where}: DynamoDB refuses two operations on one item in a transaction")
                seen_keys.add(key)
                plan.append((operation, key, payload))
                outcomes.append(_evaluate_condition(condition, self.rows.get(key), values, names))
            if not all(outcomes):
                raise FakeClientError(
                    "TransactionCanceledException",
                    cancellation_reasons=[
                        {"Code": "None"} if held else {"Code": "ConditionalCheckFailed"}
                        for held in outcomes])
            for operation, key, payload in plan:
                if operation == "Put":
                    self.rows[key] = dict(payload["item"])
                elif operation == "Update":
                    base = dict(self.rows[key]) if key in self.rows else {self.key_attr: key}
                    self.rows[key] = apply_update(payload["expression"], base,
                                                  payload["values"], payload["names"])
            self.applied.append(("transact_write_items", {"TransactItems": items}))
            return {}

    def query(self, IndexName=None, KeyConditionExpression=None,
              ExpressionAttributeValues=None, ExpressionAttributeNames=None,
              Limit=None, ScanIndexForward=True, ExclusiveStartKey=None, **kwargs):
        everything = super().query(IndexName=IndexName,
                                   KeyConditionExpression=KeyConditionExpression,
                                   ExpressionAttributeValues=ExpressionAttributeValues,
                                   ExpressionAttributeNames=ExpressionAttributeNames,
                                   Limit=None, ScanIndexForward=ScanIndexForward)
        self.calls[-1][1].update({"Limit": Limit, "ExclusiveStartKey": ExclusiveStartKey,
                                  "ExpressionAttributeValues": ExpressionAttributeValues})
        items = everything["Items"]
        if ExclusiveStartKey:
            keys = [row[self.key_attr] for row in items]
            start = ExclusiveStartKey.get(self.key_attr)
            items = items[keys.index(start) + 1:] if start in keys else []
        result: Dict[str, Any] = {}
        if Limit and len(items) > Limit:
            items = items[:Limit]
            last = items[-1]
            result["LastEvaluatedKey"] = {self.key_attr: last[self.key_attr],
                                          "customerId": last.get("customerId"),
                                          "createdAt": last.get("createdAt")}
        result.update({"Items": items, "Count": len(items)})
        return result


class KeysTable(FakeTable):
    """The commerce-keys table (`orderId` partition), READ-ONLY to the service-requests Lambda."""

    def __init__(self) -> None:
        super().__init__(key_attr="orderId", name="stack-wecare-digital-WixOrderIds")

    def writes(self) -> List[str]:
        return [name for name, _ in self.calls if name != "get_item"]
