"""Exact-key local inbox message deletion; never full customer erasure.

The visible inbox reads MessagesTable, not the legacy WhatsApp source tables.
For an eligible, nonfinancial, text-only message, remove a matching source row
first and the canonical message second. On partial failure the canonical row
remains available for reconciliation/retry. No S3 versions, payment records,
identity claims or contact data are deleted here.

All data access dependencies are injected to make safety tests executable
without connecting to production DynamoDB.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, NamedTuple

from lambda_utils.ecommerce import contact_payment_links

MAX_CONVERSATION_SCAN = 5000
_PAYMENT_PATTERN = re.compile(
    r"razorpay|\bpayment\b|\bpaid\b|\brefund\b|\breceipt\b|"
    r"\binvoice\b|\btransaction\b|\bupi\b|\bchargeback\b|"
    r"\bdispute\b|\bpay\b|\bcheckout\b|\bbooking\b|\bfee\b|\bamount\b|payment link|\binr\b|₹",
    re.IGNORECASE,
)
_PAYMENT_FIELDS = (
    "paymentReferenceId", "paymentId", "paymentOrderId", "paymentDueRef",
    "invoiceId", "orderId", "paymentAmount", "paymentOffset",
    "paymentPurpose", "providerPaymentId", "referenceId",
)
_MEDIA_FIELDS = ("s3Key", "mediaId", "mediaUrl", "flowAttachments", "recordingUrl")


class DeleteDecision(NamedTuple):
    status: int
    body: dict[str, Any]


def _refuse(code: str, reason: str, status: int = 409) -> DeleteDecision:
    return DeleteDecision(status, {
        "errorCode": code, "error": reason, "rowDeleted": False,
        "erasureComplete": False,
    })


def _is_financial(row: Mapping[str, Any]) -> bool:
    if any(row.get(f) not in (None, "", [], {}) for f in _PAYMENT_FIELDS):
        return True
    return bool(_PAYMENT_PATTERN.search(" ".join(
        str(row.get(f) or "") for f in ("content", "messageType", "templateName", "caption")
    )))


def _has_media(row: Mapping[str, Any]) -> bool:
    if any(row.get(f) not in (None, "", [], {}) for f in _MEDIA_FIELDS):
        return True
    return str(row.get("messageType") or "text").strip().lower() in (
        "audio", "image", "video", "document", "sticker", "voice",
        "flow_response", "contacts",
    )


def _scan_conversation(table: Any, contact_id: str) -> list[dict]:
    """Read all pages and refuse huge/incomplete inventories rather than truncate."""
    rows: list[dict] = []
    params: dict[str, Any] = {
        "FilterExpression": "contactId = :cid",
        "ExpressionAttributeValues": {":cid": contact_id},
        "ConsistentRead": True,
    }
    while True:
        page = table.scan(**params)
        chunk = page.get("Items")
        if not isinstance(chunk, list):
            raise ValueError("unreadable canonical history")
        rows.extend(chunk)
        if len(rows) > MAX_CONVERSATION_SCAN:
            raise ValueError("conversation exceeds verified deletion limit")
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return rows
        params["ExclusiveStartKey"] = cursor


def _guard(
    contact: Mapping[str, Any],
    meta: Mapping[str, Any],
    row: Mapping[str, Any],
    source: Mapping[str, Any] | None,
    conversation: list[dict],
    invoices: Any,
    orders: Any,
) -> DeleteDecision | None:
    if not contact or not contact.get("id"):
        return _refuse("MESSAGE_IDENTITY_UNVERIFIED",
                       "The saved customer identity is missing.")
    if "retention-hold" in (meta.get("tags") or []):
        return _refuse("MESSAGE_RETENTION_HOLD",
                       "This conversation has a retention hold.")
    if bool(contact.get("locked")) and str(contact.get("lockedReason") or "").lower() != "created":
        return _refuse("MESSAGE_CONTACT_LOCKED",
                       "This customer is locked for legal or payment retention.")
    if "retention-hold" in (contact.get("tags") or []):
        return _refuse("MESSAGE_RETENTION_HOLD",
                       "This contact has a retention hold.")
    try:
        linked = contact_payment_links.has_payment_links(
            invoices_table=invoices,
            orders_table=orders,
            contact_row=contact,
        )
    except Exception:
        return _refuse("MESSAGE_FINANCIAL_REVIEW_REQUIRED",
                       "Payment linkage could not be verified.")
    if linked.blocked:
        return _refuse("MESSAGE_FINANCIAL_RETENTION",
                       "This customer has linked financial history.")
    if any(_is_financial(m) for m in [row, *(conversation or []), *( [source] if source else [] )]):
        return _refuse("MESSAGE_FINANCIAL_RETENTION",
                       "Payment-related conversations must be retained.")
    if _has_media(row) or (source and _has_media(source)):
        return _refuse("MESSAGE_MEDIA_REVIEW_REQUIRED",
                       "Media and attachment versions need exact-object review.")
    return None


def delete_visible_message(
    *,
    message_id: str,
    actor: str,
    canonical_table: Any,
    inbound_table: Any,
    outbound_table: Any,
    contacts_table: Any,
    meta_table: Any,
    invoices_table: Any,
    orders_table: Any,
    audit: Callable[..., Any],
) -> DeleteDecision:
    """Remove only an eligible canonical text message and its exact source row.

    Protected/money-linked conversations are never deleted by this operation.
    No success is returned until an exact readback confirms both stored rows
    absent. Source-first order leaves a canonical retry point on partial errors.
    """
    if not message_id or len(message_id) > 250 or not actor:
        return _refuse("MESSAGE_DELETE_REQUEST_INVALID",
                       "A verified actor and exact message ID are required.", 400)
    try:
        canonical = canonical_table.get_item(
            Key={"id": message_id}, ConsistentRead=True).get("Item") or {}
        if not canonical:
            return _refuse("MESSAGE_NOT_FOUND",
                           "The message is no longer in the inbox.", 404)
        contact_id = str(canonical.get("contactId") or "").strip()
        if not contact_id:
            return _refuse("MESSAGE_IDENTITY_UNVERIFIED",
                           "The conversation has no verified saved customer.")
        contact = contacts_table.get_item(
            Key={"id": contact_id}, ConsistentRead=True).get("Item") or {}
        meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        direction = str(canonical.get("direction") or "").upper()
        if direction not in ("INBOUND", "OUTBOUND"):
            return _refuse("MESSAGE_DIRECTION_UNVERIFIED",
                           "The source direction is not verified.")
        source_table = outbound_table if direction == "OUTBOUND" else inbound_table
        source = source_table.get_item(
            Key={"id": message_id}, ConsistentRead=True).get("Item")
        if source and str(source.get("contactId") or "") != contact_id:
            return _refuse("MESSAGE_SOURCE_IDENTITY_CONFLICT",
                           "The source message belongs to a different identity.")
        conversation = _scan_conversation(canonical_table, contact_id)
        guard = _guard(contact, meta, canonical, source, conversation,
                       invoices_table, orders_table)
        if guard:
            return guard
    except Exception:
        return _refuse("MESSAGE_DELETE_INVENTORY_UNAVAILABLE",
                       "Message, identity or payment inventory could not be verified.", 503)

    # This durable audit is recorded before any mutation. When the audit sink
    # is unavailable, refuse instead of performing unlogged deletion.
    try:
        audit_id = audit(
            action="messages.delete_local_inbox",
            actor=actor,
            resource_type="message",
            resource_id=message_id,
            details={"source": direction, "hasSourceCopy": bool(source),
                     "mediaExcluded": True, "erasureComplete": False},
        )
        if not audit_id:
            return _refuse("MESSAGE_DELETE_AUDIT_UNAVAILABLE",
                           "A required audit record could not be written.", 503)

        # Recheck the hold at execution time; this is not a full writer-fenced
        # customer erasure, and we never claim it is.
        latest = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        if "retention-hold" in (latest.get("tags") or []):
            return _refuse("MESSAGE_RETENTION_HOLD",
                           "A retention hold was added before deletion.")
        if source:
            source_table.delete_item(
                Key={"id": message_id},
                ConditionExpression="attribute_exists(#id) AND #cid = :cid",
                ExpressionAttributeNames={"#id": "id", "#cid": "contactId"},
                ExpressionAttributeValues={":cid": contact_id},
            )
        canonical_table.delete_item(
            Key={"id": message_id},
            ConditionExpression="attribute_exists(#id) AND #cid = :cid",
            ExpressionAttributeNames={"#id": "id", "#cid": "contactId"},
            ExpressionAttributeValues={":cid": contact_id},
        )
        canonical_remains = canonical_table.get_item(
            Key={"id": message_id}, ConsistentRead=True).get("Item")
        source_remains = source_table.get_item(
            Key={"id": message_id}, ConsistentRead=True).get("Item")
        if canonical_remains or source_remains:
            return _refuse("MESSAGE_DELETE_RECONCILIATION_REQUIRED",
                           "Stored rows could not be verified as removed.", 503)
    except Exception:
        # A source deletion might have succeeded before a later failure.
        # Never say 'nothing was deleted' in an indeterminate result.
        return _refuse("MESSAGE_DELETE_RECONCILIATION_REQUIRED",
                       "Delete result is incomplete. Refresh and review before retrying.", 503)

    return DeleteDecision(200, {
        "success": True,
        "rowDeleted": True,
        "sourceRowDeleted": bool(source),
        "messageId": message_id,
        "auditId": str(audit_id),
        "erasureComplete": False,
        "mediaPermanentlyErased": False,
        "warning": "Local inbox rows removed. External providers and backups are not erased.",
    })


# Content-only removal is separate from row deletion and customer erasure.
# A thread-level retention hold still takes precedence until independently
# released; this function does not create any hold bypass.
_CONTENT_KEYS = (
    "content", "body", "caption", "text", "messageText", "transcription",
)


def _remove_content_fields(table: Any, message: Mapping[str, Any], contact_id: str) -> None:
    """Conditional, exact-message redaction; never touch identity or money fields."""
    names = {"#pk": "id", "#cid": "contactId"}
    for index, field in enumerate(_CONTENT_KEYS):
        names[f"#payload{index}"] = field
    condition = "attribute_exists(#pk) AND #cid = :cid"
    values: dict[str, Any] = {":cid": contact_id}
    if "content" in message:
        names["#expectedContent"] = "content"
        condition += " AND #expectedContent = :expectedContent"
        values[":expectedContent"] = message["content"]
    else:
        names["#expectedContent"] = "content"
        condition += " AND attribute_not_exists(#expectedContent)"
    table.update_item(
        Key={"id": message["id"]},
        UpdateExpression="REMOVE " + ", ".join(
            f"#payload{index}" for index in range(len(_CONTENT_KEYS))
        ),
        ConditionExpression=condition,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def _content_absent(message: Mapping[str, Any] | None) -> bool:
    return not message or all(field not in message for field in _CONTENT_KEYS)


def redact_visible_message_content(
    *,
    message_id: str,
    actor: str,
    canonical_table: Any,
    inbound_table: Any,
    outbound_table: Any,
    contacts_table: Any,
    meta_table: Any,
    invoices_table: Any,
    orders_table: Any,
    audit: Callable[..., Any],
) -> DeleteDecision:
    """Remove ONLY eligible text payload, keeping the message row and all finance.

    This is not a retention-hold release, provider erasure, media deletion or
    full-contact erasure. It retains the original saved message identity and
    message timeline for accountability, and refuses financial/media messages.
    """
    if not message_id or len(message_id) > 250 or not actor:
        return _refuse("MESSAGE_DELETE_REQUEST_INVALID",
                       "A verified actor and exact message ID are required.", 400)
    try:
        canonical = canonical_table.get_item(
            Key={"id": message_id}, ConsistentRead=True
        ).get("Item") or {}
        if not canonical:
            return _refuse("MESSAGE_NOT_FOUND",
                           "The message is no longer in the inbox.", 404)
        if _content_absent(canonical):
            return _refuse("MESSAGE_CONTENT_ALREADY_REMOVED",
                           "This message has no stored content to delete.")
        contact_id = str(canonical.get("contactId") or "").strip()
        if not contact_id:
            return _refuse("MESSAGE_IDENTITY_UNVERIFIED",
                           "The conversation has no verified saved customer.")
        contact = contacts_table.get_item(
            Key={"id": contact_id}, ConsistentRead=True
        ).get("Item") or {}
        meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True
        ).get("Item") or {}
        direction = str(canonical.get("direction") or "").upper()
        if direction not in ("INBOUND", "OUTBOUND"):
            return _refuse("MESSAGE_DIRECTION_UNVERIFIED",
                           "The source direction is not verified.")
        source_table = outbound_table if direction == "OUTBOUND" else inbound_table
        source = source_table.get_item(
            Key={"id": message_id}, ConsistentRead=True
        ).get("Item")
        if source and str(source.get("contactId") or "") != contact_id:
            return _refuse("MESSAGE_SOURCE_IDENTITY_CONFLICT",
                           "The source message belongs to a different identity.")
        # Check complete inbox inventory but decide content-only eligibility
        # for the exact message: money-related neighboring messages are retained.
        _scan_conversation(canonical_table, contact_id)
        guard = _guard(contact, meta, canonical, source, [canonical],
                       invoices_table, orders_table)
        if guard:
            return guard
    except Exception:
        return _refuse("MESSAGE_DELETE_INVENTORY_UNAVAILABLE",
                       "Message, identity or payment inventory could not be verified.", 503)

    # The durable audit must be written BEFORE the first mutation.
    try:
        audit_id = audit(
            action="messages.delete_content_only",
            actor=actor,
            resource_type="message",
            resource_id=message_id,
            details={"source": direction, "hasSourceCopy": bool(source),
                     "messageRowRetained": True, "mediaExcluded": True,
                     "erasureComplete": False},
        )
        if not audit_id:
            return _refuse("MESSAGE_DELETE_AUDIT_UNAVAILABLE",
                           "A required audit record could not be written.", 503)
        latest = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True
        ).get("Item") or {}
        if "retention-hold" in (latest.get("tags") or []):
            return _refuse("MESSAGE_RETENTION_HOLD",
                           "The conversation still has an active retention hold.")

        # Source first; a partial failure keeps the canonical copy for review.
        if source:
            _remove_content_fields(source_table, source, contact_id)
        _remove_content_fields(canonical_table, canonical, contact_id)
        current = canonical_table.get_item(
            Key={"id": message_id}, ConsistentRead=True
        ).get("Item")
        latest_source = source_table.get_item(
            Key={"id": message_id}, ConsistentRead=True
        ).get("Item")
        if not current or not _content_absent(current) or not _content_absent(latest_source):
            return _refuse("MESSAGE_DELETE_RECONCILIATION_REQUIRED",
                           "Content removal could not be verified.", 503)
    except Exception:
        return _refuse("MESSAGE_DELETE_RECONCILIATION_REQUIRED",
                       "Content removal is incomplete. Verify before retrying.", 503)

    return DeleteDecision(200, {
        "success": True, "contentDeleted": True, "rowDeleted": False,
        "sourceContentDeleted": bool(source), "messageId": message_id,
        "auditId": str(audit_id), "contactDeleted": False,
        "erasureComplete": False, "mediaPermanentlyErased": False,
        "warning": "Only local text fields removed; retained metadata, providers and backups remain.",
    })
