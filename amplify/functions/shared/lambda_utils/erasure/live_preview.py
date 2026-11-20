"""Authenticated read-only inventory adapter for selective erasure.

All external IO is supplied as boto3 Table-like objects. The only supported
method on each table is scan(); this module has no delete/update/unlock APIs.
A DynamoDB Scan is NOT an atomic snapshot. Its fingerprint must never be
accepted as a delete authorization without a writer-fenced recheck.
"""
from __future__ import annotations

from typing import Any, Mapping

from lambda_utils.erasure.selective_preview import (
    build_preview, ErasurePreviewError,
)

MAX_ROWS_PER_TABLE = 20_000

TABLE_FIELDS = {
    "contacts": "ContactsTable",
    "conversation_meta": "ConversationMetaTable",
    "message": "MessagesTable",
    "inbound": "WhatsAppInboundTable",
    "outbound": "WhatsAppOutboundTable",
    "payments": "PaymentsTable",
    "attempts": "PaymentAttemptsTable",
    "invoices": "InvoicesTable",
    "orders": "OrderTable",
}


def _scan_complete(table: Any, *, max_rows: int = MAX_ROWS_PER_TABLE) -> list[dict]:
    """Consistent per-item reads; incomplete scans, limits and failures refuse."""
    items: list[dict] = []
    start = None
    while True:
        kwargs = {"ConsistentRead": True}
        if start is not None:
            kwargs["ExclusiveStartKey"] = start
        page = table.scan(**kwargs)
        chunk = page.get("Items")
        if not isinstance(chunk, list):
            raise ErasurePreviewError("Incomplete table scan")
        items.extend(chunk)
        if len(items) > max_rows:
            raise ErasurePreviewError("Inventory exceeds read-only safety limit")
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def inspect_tables(
    tables: Mapping[str, Any],
    *,
    required_protected_contacts: int = 2,
) -> dict:
    """Return aggregate-only preview after verifying private retention holds.

    The caller must enforce Admin, MFA and tenancy before invoking. Two held
    contacts are required for this scoped request, but more valid holds are
    preserved if present. This function does not infer identity from names.
    """
    if required_protected_contacts < 1:
        raise ErasurePreviewError("Invalid hold count")

    missing = set(TABLE_FIELDS) - set(tables)
    if missing:
        raise ErasurePreviewError("Unavailable inventory source")

    read = {kind: _scan_complete(tables[kind]) for kind in TABLE_FIELDS}
    protected = {
        str(row.get("conversationId") or "").strip()
        for row in read["conversation_meta"]
        if isinstance(row, dict) and "retention-hold" in (row.get("tags") or [])
    }
    protected.discard("")
    if len(protected) < required_protected_contacts:
        raise ErasurePreviewError("Required protected contacts not found")

    preview = build_preview(
        contacts=read["contacts"],
        protected_contact_ids=protected,
        messages={
            "MessagesTable": read["message"],
            "WhatsAppInboundTable": read["inbound"],
            "WhatsAppOutboundTable": read["outbound"],
        },
        financial={
            "payments": read["payments"],
            "payment_attempts": read["attempts"],
            "invoices": read["invoices"],
            "orders": read["orders"],
        },
        # No IdentityClaims/Cognito/S3/provider or atomic snapshot here.
        dependency_inventory_complete=False,
    )
    return {
        "readOnly": True,
        "eligibleForExecution": 0,
        "requiresSecondReviewer": True,
        "snapshotAtomic": False,
        **preview.summary,
    }
