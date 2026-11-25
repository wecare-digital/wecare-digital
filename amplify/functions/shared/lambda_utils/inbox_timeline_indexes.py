"""Provisioning and runtime contract for the manually managed MessagesTable."""
from __future__ import annotations

INDEXES = {
    "channel": "inbox-channel-timestamp-index",
    "contactId": "inbox-contact-timestamp-index",
}
TIME_KEY = "timestamp"


def key_schema(partition: str) -> list[dict]:
    return [{"AttributeName": partition, "KeyType": "HASH"},
            {"AttributeName": TIME_KEY, "KeyType": "RANGE"}]


def index_definition(partition: str) -> dict:
    return {"IndexName": INDEXES[partition], "KeySchema": key_schema(partition),
            "Projection": {"ProjectionType": "ALL"}}


def require_canonical_table(table: dict) -> None:
    attrs = {d["AttributeName"]: d["AttributeType"] for d in table.get("AttributeDefinitions", [])}
    keys = {(k["AttributeName"], k["KeyType"]) for k in table.get("KeySchema", [])}
    if keys != {("id", "HASH")} or attrs.get("id") != "S":
        raise ValueError("Expected canonical MessagesTable with string id primary key.")
    for attr, expected in {"channel": "S", "contactId": "S", TIME_KEY: "N"}.items():
        if attr in attrs and attrs[attr] != expected:
            raise ValueError(f"Canonical timeline field {attr} must have type {expected}.")


def timeline_indexes(table: dict) -> dict[str, dict]:
    """Index metadata by partition, refusing any named index with schema drift."""
    require_canonical_table(table)
    existing = {g["IndexName"]: g for g in table.get("GlobalSecondaryIndexes") or []}
    found = {}
    for partition, name in INDEXES.items():
        if name not in existing:
            continue
        index = existing[name]
        schema = {(k["AttributeName"], k["KeyType"]) for k in index.get("KeySchema", [])}
        expected = {(k["AttributeName"], k["KeyType"]) for k in key_schema(partition)}
        attrs = {d["AttributeName"]: d["AttributeType"] for d in table.get("AttributeDefinitions", [])}
        if (schema != expected
                or attrs.get(partition) != "S" or attrs.get(TIME_KEY) != "N"
                or (index.get("Projection") or {}).get("ProjectionType") != "ALL"):
            raise ValueError(f"Won't use or replace {name}: the live schema differs.")
        found[partition] = index
    return found


def all_active(table: dict) -> bool:
    found = timeline_indexes(table)
    return len(found) == len(INDEXES) and all(
        idx.get("IndexStatus") == "ACTIVE" and not idx.get("Backfilling") for idx in found.values()
    )
