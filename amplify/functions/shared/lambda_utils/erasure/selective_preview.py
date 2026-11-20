"""Build an exact-key, non-destructive selective-erasure preview.

A dry-run is the *first* development step toward the missing deletion workflow.
This module takes already-loaded records. It does not import boto3, write,
unlock, delete, archive or modify any customer/transaction.

The caller must load private operator retention holds from an authenticated
store. Never hard-code customer names, phones, BSUIDs or IDs in public source.

Statuses are classifications, NOT deletion authorization. Even an
ELIGIBLE_FOR_APPROVAL record cannot be deleted by this module. Unknown finance,
missing data, changed identity, outstanding locks or incomplete source coverage
must never be inferred to mean safe to erase.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

RETAIN_PROTECTED = "RETAIN_PROTECTED"
RETAIN_FINANCIAL = "RETAIN_FINANCIAL"
RETAIN_LEGAL_LOCK = "RETAIN_LEGAL_LOCK"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
ELIGIBLE_FOR_APPROVAL = "ELIGIBLE_FOR_APPROVAL"

FINANCIAL_SOURCES = ("payments", "payment_attempts", "invoices", "orders")
MESSAGE_SOURCES = ("MessagesTable", "WhatsAppInboundTable", "WhatsAppOutboundTable")
# These sources are only a partial inventory. They must NOT be mistaken for
# the full Cognito / IdentityClaims / S3-version / provider dependency graph.
UNINVENTORIED_DEPENDENCIES = (
    "IdentityClaimsTable", "CustomerSessionsTable", "Cognito",
    "FlowSubmissionTable", "CrmActivities", "ScheduledMessagesTable",
    "DLQMessagesTable", "Meta", "S3 object versions", "refunds",
    "webhook/audit/idempotency records", "additional channel tables",
)

# The text matcher is only an extra reason to RETAIN or REVIEW, never a reason
# to delete a message that lacks these terms.
FINANCIAL_CLUES = re.compile(
    r"razorpay|payment|paid|refund|receipt|invoice|transaction|upi|"
    r"chargeback|dispute|pay now|payment link|order id|\binr\b|₹",
    re.IGNORECASE,
)

IDENTITY_FIELDS = {
    "id": "contact",
    "contactId": "contact",
    "checkoutCustomerId": "customer",
    "customerId": "customer",
    "customerUuid": "customer_uuid",
    "phone": "phone",
    "customerPhone": "phone",
    "paidByPhone": "phone",
    "recipientPhone": "phone",
    "email": "email",
    "customerEmail": "email",
    "phoneNumber": "phone",
    "invoiceId": "invoice",
    "orderId": "order",
    "paymentId": "payment",
    "providerPaymentId": "payment",
    "verifiedProviderPaymentId": "payment",
    "referenceId": "reference",
    "paymentReferenceId": "reference",
    "paymentAttemptId": "attempt",
}

EXPLICIT_MESSAGE_FINANCE_FIELDS = (
    "paymentReferenceId", "paymentId", "paymentOrderId", "paymentDueRef",
    "invoiceId", "orderId", "paymentPurpose", "providerPaymentId",
)
MEDIA_FIELDS = ("s3Key", "mediaId", "mediaUrl", "attachments")


class ErasurePreviewError(ValueError):
    """Unreliable input is not valid deletion evidence."""


@dataclass(frozen=True)
class Preview:
    contacts: dict[str, str]
    messages: dict[tuple[str, str], str]
    summary: dict[str, Any]
    # Deliberately no execute() method or mutation capability.
    executable: bool = False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _token(field: str, value: Any) -> str:
    tag = IDENTITY_FIELDS.get(field)
    raw = _text(value)
    if not tag or not raw:
        return ""
    if tag == "phone":
        raw = "".join(ch for ch in raw if ch.isdigit())
        if len(raw) < 7:
            return ""
        # Keep countries distinct. A 10-digit India number may be written
        # with or without its dial code in old CRM rows.
        if len(raw) == 10:
            raw = "91" + raw
    elif tag == "email":
        raw = raw.lower()
    return f"{tag}:{raw}"


def _tokens(record: Mapping[str, Any]) -> set[str]:
    return {token for field in IDENTITY_FIELDS
            if (token := _token(field, record.get(field)))}


def _financial_conversation(message: Mapping[str, Any]) -> bool:
    if any(_text(message.get(field)) for field in EXPLICIT_MESSAGE_FINANCE_FIELDS):
        return True
    narrative = " ".join(_text(message.get(k)) for k in (
        "content", "transcription", "messageType", "templateName"))
    return bool(FINANCIAL_CLUES.search(narrative))


def _index_financial_evidence(
    financial: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, set[int]], list[set[str]], int]:
    missing = [kind for kind in FINANCIAL_SOURCES if kind not in financial]
    if missing:
        raise ErasurePreviewError("Financial source missing: " + ", ".join(missing))

    groups: dict[str, set[int]] = defaultdict(set)
    records: list[set[str]] = []
    no_link = 0
    for kind in FINANCIAL_SOURCES:
        for row in financial[kind]:
            if not isinstance(row, Mapping):
                raise ErasurePreviewError("Unusable financial record")
            tokens = _tokens(row)
            if not tokens:
                no_link += 1
            rid = len(records)
            records.append(tokens)
            for t in tokens:
                groups[t].add(rid)
    return groups, records, no_link


def _connected_financial_records(
    contact_tokens: set[str],
    groups: Mapping[str, set[int]],
    rows: Sequence[set[str]],
) -> set[int]:
    """Traverse invoice -> order -> payment -> attempt references transitively.

    Matching one exact contactId or payment ID propagates the finance hold
    across the linked graph. An overmatch retains more; it does not authorize
    destruction. Customer names are never identity evidence.
    """
    seen_tokens = set(contact_tokens)
    matched: set[int] = set()
    queue = deque(contact_tokens)
    while queue:
        tok = queue.popleft()
        for idx in groups.get(tok, ()):
            if idx in matched:
                continue
            matched.add(idx)
            for related in rows[idx]:
                if related not in seen_tokens:
                    seen_tokens.add(related)
                    queue.append(related)
    return matched


def build_preview(
    *,
    contacts: Sequence[Mapping[str, Any]],
    messages: Mapping[str, Sequence[Mapping[str, Any]]],
    financial: Mapping[str, Sequence[Mapping[str, Any]]],
    protected_contact_ids: Iterable[str],
    dependency_inventory_complete: bool = False,
) -> Preview:
    """Classify exact keys, including every protected identity.

    'created' is a *reviewable origin*, not proof of a paid/legal lock, but
    it must never be automatically unlocked. Unknown locks remain retained.
    The preview is NOT an authorization to delete and always has executable=False.
    """
    protected = {_text(x) for x in protected_contact_ids if _text(x)}
    if not protected:
        raise ErasurePreviewError("No verified private retention holds")
    missing_sources = [kind for kind in MESSAGE_SOURCES if kind not in messages]
    if missing_sources:
        raise ErasurePreviewError("Message source missing: " + ", ".join(missing_sources))

    contacts_by_id: dict[str, Mapping[str, Any]] = {}
    for contact in contacts:
        if not isinstance(contact, Mapping):
            raise ErasurePreviewError("Unreadable contact record")
        cid = _text(contact.get("id") or contact.get("contactId"))
        if not cid or cid in contacts_by_id:
            raise ErasurePreviewError("Missing or duplicate canonical contact ID")
        contacts_by_id[cid] = contact
    if not protected.issubset(contacts_by_id.keys()):
        raise ErasurePreviewError("At least one protected contact is missing")

    groups, financial_rows, unresolved_finance = _index_financial_evidence(financial)
    raw_message_rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    financially_flagged_conversations: set[str] = set()
    unresolved_message_rows = 0

    for source in MESSAGE_SOURCES:
        for row in messages[source]:
            if not isinstance(row, Mapping):
                raise ErasurePreviewError("Unreadable message")
            mid = _text(row.get("id"))
            if not mid:
                raise ErasurePreviewError("Message without a stable primary key")
            key = (source, mid)
            if key in raw_message_rows:
                raise ErasurePreviewError("Duplicate message primary key")
            raw_message_rows[key] = row
            cid = _text(row.get("contactId"))
            if not cid or cid not in contacts_by_id:
                unresolved_message_rows += 1
            if _financial_conversation(row) and cid:
                financially_flagged_conversations.add(cid)

    contact_results: dict[str, str] = {}
    for cid, contact in contacts_by_id.items():
        if cid in protected:
            contact_results[cid] = RETAIN_PROTECTED
            continue
        if _connected_financial_records(_tokens(contact), groups, financial_rows):
            contact_results[cid] = RETAIN_FINANCIAL
            continue
        if cid in financially_flagged_conversations:
            # A keyword can establish a REVIEW or a hold, never proof that
            # a corresponding finance transaction does not exist.
            contact_results[cid] = RETAIN_FINANCIAL
            continue
        if bool(contact.get("locked")):
            reason = _text(contact.get("lockedReason")).lower()
            if reason not in ("created",):
                contact_results[cid] = RETAIN_LEGAL_LOCK
                continue
        # Even a default 'created' lock is not removed by the planner.
        # Unmatched payment records or missing dependency enumeration block
        # any inference that unrelated history is safe to delete.
        if unresolved_finance or not dependency_inventory_complete:
            contact_results[cid] = REVIEW_REQUIRED
        else:
            contact_results[cid] = ELIGIBLE_FOR_APPROVAL

    message_results: dict[tuple[str, str], str] = {}
    for key, msg in raw_message_rows.items():
        cid = _text(msg.get("contactId"))
        parent_status = contact_results.get(cid)
        if parent_status == RETAIN_PROTECTED:
            status = RETAIN_PROTECTED
        elif parent_status in (RETAIN_FINANCIAL, RETAIN_LEGAL_LOCK):
            status = parent_status
        elif not parent_status or _financial_conversation(msg):
            status = REVIEW_REQUIRED
        elif any(_text(msg.get(k)) for k in MEDIA_FIELDS):
            # Versioned S3 media dependencies need their own exact-version audit.
            status = REVIEW_REQUIRED
        elif parent_status == ELIGIBLE_FOR_APPROVAL:
            status = ELIGIBLE_FOR_APPROVAL
        else:
            status = REVIEW_REQUIRED
        message_results[key] = status

    contacts_status = Counter(contact_results.values())
    message_status = Counter(message_results.values())
    per_table = {kind: {
        "total": len(messages[kind]),
        "protected": sum(v == RETAIN_PROTECTED for (source, _), v in message_results.items()
                         if source == kind),
        "review": sum(v == REVIEW_REQUIRED for (source, _), v in message_results.items()
                      if source == kind),
    } for kind in MESSAGE_SOURCES}

    summary = {
        "contacts": {
            "total": len(contacts_by_id),
            "protected": len(protected),
            "other": len(contacts_by_id) - len(protected),
            "disposition": dict(contacts_status),
        },
        "messages": {
            "byTable": per_table,
            "disposition": dict(message_status),
            "unlinkedOrUnknownContact": unresolved_message_rows,
        },
        "financial": {
            "sourceRecordCounts": {kind: len(financial[kind]) for kind in FINANCIAL_SOURCES},
            "unlinkedEvidence": unresolved_finance,
        },
        "dependencyInventoryComplete": bool(dependency_inventory_complete),
        "notYetInventoried": [] if dependency_inventory_complete
            else list(UNINVENTORIED_DEPENDENCIES),
        "executionAuthorized": False,
        "deletedContacts": 0,
        "deletedMessages": 0,
    }
    return Preview(contact_results, message_results, summary)
