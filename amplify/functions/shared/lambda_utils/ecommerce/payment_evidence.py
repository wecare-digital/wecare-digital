"""Read-only, invoice-scoped evidence chronology.

No database access, provider calls, credential handling, or writes. Callers must
load the authoritative invoice by its PK and delivery rows by invoiceId before
passing them here. A provider WAMID proves accepted submission, NOT delivery.
A paid invoice projection is not itself a fresh provider verification.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional


def _epoch(value: Any) -> Optional[int]:
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if n > 1_000_000_000_000:
        n //= 1000
    return n if 946684800 <= n <= 4102444800 else None


def _fragment(value: Any) -> str:
    raw = str(value) if value is not None else ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12] if raw else ""


def _event(role: str, label: str, at: int, *, source: str, actor: str,
           verification: str, record_id: Any) -> Dict[str, Any]:
    return {
        "role": role,
        "label": label,
        "at": at,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at)),
        "source": source,
        "actor": actor,
        "verificationClass": verification,
        "recordFragment": _fragment(record_id),
    }


def invoice_evidence_timeline(invoice: Dict[str, Any],
                              delivery_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Safely project exact-invoice records; absent stages remain unverified.

    The delivery table's timestamp reflects a recorded send attempt/acceptance,
    never the handset's receipt time. Only a durable provider WAMID and a
    non-failed send row can support the provider_accepted class.
    """
    invoice_id = str(invoice.get("invoiceId") or "")
    if not invoice_id:
        raise ValueError("Authoritative invoiceId is required")
    events: List[Dict[str, Any]] = []
    created = _epoch(invoice.get("createdAt"))
    if created:
        events.append(_event("invoice_created", "Invoice issued", created,
                             source="InvoicesTable", actor="invoice-engine",
                             verification="invoice_recorded", record_id=invoice_id))

    paid = str(invoice.get("paymentStatus") or "").strip().lower()
    paid_at = _epoch(invoice.get("paidAt"))
    if paid in ("paid", "captured") and paid_at:
        events.append(_event(
            "payment_projection", "Paid invoice recorded", paid_at,
            source="InvoicesTable", actor="payment reconciliation",
            verification="invoice_paid_projection", record_id=invoice_id,
        ))

    for row in delivery_rows[:100]:
        if str(row.get("invoiceId") or "") != invoice_id:
            continue  # Never combine a different invoice's delivery evidence.
        at = _epoch(row.get("timestamp"))
        if not at:
            continue
        channel = str(row.get("channel") or "").strip().lower()
        status = str(row.get("status") or "").strip().lower()
        message_id = str(row.get("waMessageId") or "")
        has_provider_id = message_id.startswith("wamid.") and len(message_id) <= 512
        failed = status in ("failed", "rejected")
        verification = ("send_failed" if failed else
                        "provider_accepted" if has_provider_id else "unverified")
        if channel == "whatsapp_order_status" and status in ("processing", "completed"):
            role = status
            label = ("Processing status" if status == "processing"
                     else "Completed status")
        elif channel in ("whatsapp", "whatsapp_invoice", "invoice_whatsapp"):
            role, label = "invoice_message", "Invoice image message"
        else:
            role, label = "other_message", "Message send log"
        events.append(_event(
            role, label, at, source="InvoiceDeliveryLogTable",
            actor="backend message sender", verification=verification,
            record_id=message_id if has_provider_id else invoice_id,
        ))

    refund_at = _epoch(invoice.get("refundAt"))
    if refund_at and invoice.get("refundId"):
        events.append(_event(
            "refund", "Provider refund recorded", refund_at,
            source="InvoicesTable", actor="refund reconciliation",
            verification="refund_recorded", record_id=invoice.get("refundId"),
        ))
    cancelled_at = _epoch(invoice.get("cancelledAt"))
    if cancelled_at and str(invoice.get("status") or "").lower() == "cancelled":
        events.append(_event(
            "cancelled", "Invoice cancellation recorded", cancelled_at,
            source="InvoicesTable", actor="invoice-engine",
            verification="invoice_cancelled", record_id=invoice_id,
        ))
    events.sort(key=lambda row: (row["at"], row["role"]))

    # Compare only the recorded send/acceptance timestamps of the SAME invoice.
    # Provider delivery/read and the customer's tap are NOT observed here.
    accepted: Dict[str, int] = {}
    for event in events:
        if event["verificationClass"] != "provider_accepted":
            continue
        if event["role"] in ("processing", "completed", "invoice_message"):
            accepted.setdefault(event["role"], event["at"])

    gaps: List[Dict[str, Any]] = []
    pairs = [
        ("Processing → Completed", "processing", "completed"),
        ("Completed → Invoice", "completed", "invoice_message"),
        ("Invoice → Access Vault", "invoice_message", "access_vault"),
        ("Link click → first authenticated download", "link_click", "first_download"),
    ]
    for name, start, end in pairs:
        a, b = accepted.get(start), accepted.get(end)
        seconds = b - a if a is not None and b is not None and b >= a else None
        gaps.append({
            "label": name,
            "seconds": seconds,
            "status": "measured" if seconds is not None else "unverified",
            "basis": "Provider-accepted message log times" if seconds is not None
                     else "No exact-invoice event pair",
        })

    return {
        "scope": "authoritative_invoice_id",
        "invoiceFragment": _fragment(invoice_id),
        "events": events,
        "gaps": gaps,
        "note": ("No inferred payment, handset-delivery, link-click or download event. "
                 "A paid invoice projection is not a provider readback."),
    }
