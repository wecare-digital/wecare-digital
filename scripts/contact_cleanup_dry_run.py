#!/usr/bin/env python3
"""READ-ONLY dry run: which contacts could be cleaned up, and which must be kept.

Governing policy: docs/ops/scoped-whatsapp-contact-payment-retention-2026-11-20.md
Usage notes:      docs/ops/contact-cleanup-dry-run.md

This script NEVER archives, deletes, updates or writes anything in AWS. Every table is wrapped in a
proxy that only allows scan, query and get_item, and the TTL check only calls
describe_time_to_live. Cleanup, if the operator decides to do it, is the existing reversible
Archive in the contacts API, run by the operator with Admin + MFA.

Each contact gets exactly one label, highest precedence first:

  OPERATOR_HOLD                 the operator selected it (id, exact phone, BSUID or merge link)
  FINANCIAL_RETENTION           invoice, order, payment, attempt or payment-related message found
  LEGAL_OR_IDENTITY_LOCK        the contact row is locked
  REVIEW_REQUIRED               anything unknown, unreadable, ambiguous or truncated
  ELIGIBLE_FOR_APPROVED_ACTION  everything was read and nothing protects it

Selection is by identifier only. A display name is never read as a selector, and two contacts
that share a name stay distinct. The selection is supplied at run time (private JSON file or CLI
arguments) and is never stored in this repository.

Exit codes:
  0  report produced, all inventory complete, expectations (if any) met
  2  inventory incomplete (a read failed): nothing is reported as eligible
  3  selection problem or expectation mismatch: nothing is reported as eligible
  64 usage error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(os.path.dirname(_HERE), "amplify", "functions", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from lambda_utils import contact_key  # noqa: E402
from lambda_utils.ecommerce import contact_lock  # noqa: E402
from lambda_utils.ecommerce.contact_payment_links import (  # noqa: E402
    PaymentLinkageUnknown,
    has_payment_links,
)

OPERATOR_HOLD = "OPERATOR_HOLD"
FINANCIAL_RETENTION = "FINANCIAL_RETENTION"
LEGAL_OR_IDENTITY_LOCK = "LEGAL_OR_IDENTITY_LOCK"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
ELIGIBLE = "ELIGIBLE_FOR_APPROVED_ACTION"
ALREADY_ARCHIVED = "ALREADY_ARCHIVED"

PRECEDENCE = (OPERATOR_HOLD, FINANCIAL_RETENTION, LEGAL_OR_IDENTITY_LOCK, REVIEW_REQUIRED, ELIGIBLE)

DEFAULT_PREFIX = "stack-wecare-digital"
#: logical name -> physical suffix (see lambda_utils/shared_tables.py and amplify/data/resource.ts)
TABLE_SUFFIXES = {
    "contacts": "ContactsTable",
    "messages": "MessagesTable",
    "inbound": "WhatsAppInboundTable",
    "outbound": "WhatsAppOutboundTable",
    "payments": "PaymentsTable",
    "attempts": "PaymentAttemptsTable",
    "invoices": "InvoicesTable",
    "orders": "OrderTable",
}
MESSAGE_TABLES = ("messages", "inbound", "outbound")
PAYMENT_TABLES = ("payments", "attempts", "invoices")
#: Per policy: TTL is enabled on the message tables, disabled on the payment tables.
TTL_ATTRIBUTE = "expiresAt"

READ_ONLY_METHODS = frozenset({"scan", "query", "get_item"})
MAX_PAGES = 100000

#: Attribute names on a message that carry a payment reference. Any non-empty value protects it.
PAYMENT_REF_ATTRIBUTES = frozenset({
    "paymentreferenceid", "referenceid", "invoiceid", "orderid", "paymentid", "providerpaymentid",
    "providerorderid", "razorpaypaymentid", "razorpayorderid", "refundid", "disputeid",
    "paymentattemptid", "receiptid",
})
PAYMENT_NAME_FRAGMENTS = ("payment", "razorpay", "invoice", "refund", "dispute", "receipt")
PAYMENT_WORDS = (
    "payment", "pay_", "razorpay", "rzp", "invoice", "receipt", "refund", "dispute", "order",
    "paid", "upi", "checkout", "chargeback",
)
PROVIDER_ID_RE = re.compile(r"\b(pay|order|rfnd|refund|inv|dispute|dsp)_[A-Za-z0-9]{6,}")

CONTACT_ID_FIELDS = ("id", "contactId")
MESSAGE_PHONE_FIELDS = ("phone", "senderPhone")
MESSAGE_BSUID_FIELDS = ("senderBsuid", "senderParentBsuid", "recipientBsuid",
                        "parentRecipientBsuid", "bsuid")


class InventoryIncomplete(RuntimeError):
    """A read failed or was truncated, so the inventory cannot be trusted."""


# ── Read-only access ─────────────────────────────────────────────────────────────────────────


class ReadOnlyTable:
    """Proxy that exposes only read APIs. Any other attribute raises, so a write cannot happen."""

    def __init__(self, table: Any, label: str = "table") -> None:
        object.__setattr__(self, "_table", table)
        object.__setattr__(self, "_label", label)

    def __getattr__(self, name: str) -> Any:
        if name not in READ_ONLY_METHODS:
            raise PermissionError(f"{name} is not permitted: this tool is read-only")
        return getattr(self._table, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise PermissionError("read-only proxy")


def scan_all(table: Any, label: str) -> List[Any]:
    """Scan every page. Raises InventoryIncomplete on any error or non-advancing pagination."""
    items: List[Any] = []
    kwargs: Dict[str, Any] = {}
    seen_keys: Set[str] = set()
    for _ in range(MAX_PAGES):
        try:
            response = table.scan(**kwargs)
        except Exception as exc:  # noqa: BLE001 - any failure means the inventory is unknown
            raise InventoryIncomplete(f"{label}: scan failed ({type(exc).__name__})") from None
        items.extend(response.get("Items") or [])
        last = response.get("LastEvaluatedKey")
        if not last:
            return items
        token = json.dumps(last, sort_keys=True, default=str)
        if token in seen_keys:
            raise InventoryIncomplete(f"{label}: pagination did not advance")
        seen_keys.add(token)
        kwargs["ExclusiveStartKey"] = last
    raise InventoryIncomplete(f"{label}: pagination limit reached")


# ── Identifiers ──────────────────────────────────────────────────────────────────────────────


def phone_digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def mask_phone(value: Any) -> str:
    digits = phone_digits(value)
    return ("****" + digits[-4:]) if len(digits) >= 4 else ("****" if digits else "")


def opaque(value: str) -> str:
    return "c_" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def contact_identity(row: Any) -> str:
    return contact_key.resolve(row) if isinstance(row, dict) else ""


def row_id_conflict(row: Mapping[str, Any]) -> bool:
    primary, alias = _text(row.get("id")), _text(row.get("contactId"))
    return bool(primary and alias and primary != alias)


# ── Selection ────────────────────────────────────────────────────────────────────────────────


class Selection:
    """Identifier-only selection. There is deliberately no name field."""

    def __init__(self, contact_ids: Iterable[str] = (), phones: Iterable[str] = (),
                 bsuids: Iterable[str] = ()) -> None:
        self.contact_ids = sorted({_text(v) for v in contact_ids if _text(v)})
        self.phones = sorted({phone_digits(v) for v in phones if phone_digits(v)})
        self.bsuids = sorted({_text(v) for v in bsuids if _text(v)})

    def empty(self) -> bool:
        return not (self.contact_ids or self.phones or self.bsuids)


ALLOWED_CONFIG_KEYS = {"contactIds", "phones", "bsuids"}


def load_selection_file(path: str) -> Selection:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("selection file must be a JSON object")
    unknown = set(data) - ALLOWED_CONFIG_KEYS
    if unknown:
        # Fail loudly: a "name" key would otherwise look like it works. Names are never selectors.
        raise ValueError("unsupported selection keys (only contactIds, phones, bsuids): "
                         + ", ".join(sorted(unknown)))
    for key in ALLOWED_CONFIG_KEYS:
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"{key} must be a list")
    return Selection(data.get("contactIds") or [], data.get("phones") or [], data.get("bsuids") or [])


def resolve_selection(rows: List[Dict[str, Any]], selection: Selection) -> Tuple[
        Set[str], List[str], List[str]]:
    """Return (selected contact ids, unmatched selector labels, ambiguous selector labels)."""
    by_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_phone: Dict[str, List[str]] = defaultdict(list)
    by_bsuid: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        cid = contact_identity(row)
        if not cid:
            continue
        by_id[cid].append(row)
        phone = phone_digits(row.get("phone"))
        if phone:
            by_phone[phone].append(cid)
        for field in ("bsuid", "parentBsuid"):
            if _text(row.get(field)):
                by_bsuid[_text(row.get(field))].append(cid)

    selected: Set[str] = set()
    unmatched: List[str] = []
    ambiguous: List[str] = []

    for n, value in enumerate(selection.contact_ids, 1):
        matches = by_id.get(value, [])
        if len(matches) == 1:
            selected.add(value)
        elif not matches:
            unmatched.append(f"contact-id#{n}")
        else:
            ambiguous.append(f"contact-id#{n}")
    for n, value in enumerate(selection.phones, 1):
        matches = sorted(set(by_phone.get(value, [])))
        if len(matches) == 1:
            selected.add(matches[0])
        elif not matches:
            unmatched.append(f"phone#{n}")
        else:
            selected.update(matches)  # keep them all, but refuse to proceed
            ambiguous.append(f"phone#{n}")
    for n, value in enumerate(selection.bsuids, 1):
        matches = sorted(set(by_bsuid.get(value, [])))
        if len(matches) == 1:
            selected.add(matches[0])
        elif not matches:
            unmatched.append(f"bsuid#{n}")
        else:
            selected.update(matches)
            ambiguous.append(f"bsuid#{n}")

    # Merge linkage: rows merged into a selected contact, and the rows a selected contact absorbed.
    changed = True
    while changed:
        changed = False
        for row in rows:
            cid = contact_identity(row)
            if not cid:
                continue
            target = _text(row.get("mergedIntoContactId"))
            if cid not in selected and target in selected:
                selected.add(cid)
                changed = True
            if cid in selected:
                for alias in row.get("mergedContactIds") or []:
                    alias = _text(alias)
                    if alias and alias in by_id and alias not in selected:
                        selected.add(alias)
                        changed = True
                if target and target in by_id and target not in selected:
                    selected.add(target)
                    changed = True
    return selected, unmatched, ambiguous


# ── Payment evidence ─────────────────────────────────────────────────────────────────────────


class PaymentIndex:
    """In-memory view of PaymentsTable, PaymentAttemptsTable and InvoicesTable."""

    def __init__(self) -> None:
        self.phones: Set[str] = set()          # digits, last 10
        self.emails: Set[str] = set()
        self.customer_ids: Set[str] = set()
        self.contact_ids: Set[str] = set()
        self.reference_ids: Set[str] = set()   # any provider/reference id usable to link a message

    @staticmethod
    def _last10(value: Any) -> str:
        digits = phone_digits(value)
        return digits[-10:] if len(digits) >= 10 else digits

    def add(self, kind: str, row: Any) -> None:
        if not isinstance(row, dict):
            return
        for field in ("contact", "contactPhone", "customerPhone", "paidByPhone", "phone"):
            digits = self._last10(row.get(field))
            if digits:
                self.phones.add(digits)
        email = _text(row.get("email") or row.get("contactEmail") or row.get("customerEmail")).lower()
        if email:
            self.emails.add(email)
        for field in ("customerId", "customerUuid", "checkoutCustomerId"):
            if _text(row.get(field)):
                self.customer_ids.add(_text(row.get(field)))
        if _text(row.get("contactId")):
            self.contact_ids.add(_text(row.get("contactId")))
        notes = row.get("notes")
        if isinstance(notes, str) and notes.strip().startswith("{"):
            try:
                parsed = json.loads(notes)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                for field in ("contactId", "contact_id"):
                    if _text(parsed.get(field)):
                        self.contact_ids.add(_text(parsed.get(field)))
        for field in ("paymentId", "orderId", "referenceId", "providerPaymentId", "providerOrderId",
                      "invoiceId", "paymentAttemptId"):
            if _text(row.get(field)):
                self.reference_ids.add(_text(row.get(field)))

    def contact_reasons(self, row: Mapping[str, Any], cid: str) -> List[str]:
        reasons: List[str] = []
        if cid in self.contact_ids:
            reasons.append("payment record names this contact id")
        digits = self._last10(row.get("phone"))
        if digits and digits in self.phones:
            reasons.append("payment, attempt or invoice record carries this phone")
        email = _text(row.get("email")).lower()
        if email and email in self.emails:
            reasons.append("payment, attempt or invoice record carries this email")
        for field in ("checkoutCustomerId", "customerUuid"):
            if _text(row.get(field)) in self.customer_ids and _text(row.get(field)):
                reasons.append("payment attempt or invoice names this customer id")
                break
        return reasons


def message_id(item: Mapping[str, Any]) -> str:
    return _text(item.get("messageId") or item.get("id"))


def message_financial_signals(item: Mapping[str, Any], index: PaymentIndex) -> List[str]:
    """Reasons a message must be kept as payment evidence. Keyword hits only ADD protection."""
    reasons: List[str] = []
    for name, value in item.items():
        lowered = str(name).lower()
        if value in (None, "", [], {}):
            continue
        if lowered in PAYMENT_REF_ATTRIBUTES:
            reasons.append(f"carries {name}")
        elif any(frag in lowered for frag in PAYMENT_NAME_FRAGMENTS):
            reasons.append(f"attribute {name} present")
    for field in ("messageType", "templateName", "templateCategory", "type"):
        val = _text(item.get(field)).lower()
        if val and any(word in val for word in PAYMENT_WORDS):
            reasons.append(f"{field} suggests payment")
    content = _text(item.get("content")).lower()
    if content and any(word in content for word in PAYMENT_WORDS):
        reasons.append("content mentions payment terms")
    blob = " ".join(str(item.get(f) or "") for f in ("content", "templateParams", "notes"))
    if PROVIDER_ID_RE.search(blob):
        reasons.append("content carries a provider id")
    for name, value in item.items():
        if isinstance(value, str) and value in index.reference_ids and str(name).lower() not in (
                "id", "messageid", "contactid"):
            reasons.append(f"{name} matches a payment record id")
            break
    # de-duplicate, keep order
    return list(dict.fromkeys(reasons))


# ── Core ─────────────────────────────────────────────────────────────────────────────────────


def _message_owner(item: Mapping[str, Any], known_ids: Set[str], phone_map: Mapping[str, List[str]],
                   bsuid_map: Mapping[str, List[str]]) -> Tuple[Optional[str], List[str]]:
    """Return (owner contact id or None, other contact ids the message is also linked to)."""
    cid = _text(item.get("contactId"))
    linked: Set[str] = set()
    for field in MESSAGE_PHONE_FIELDS:
        digits = phone_digits(item.get(field))
        if digits:
            linked.update(phone_map.get(digits, []))
    for field in MESSAGE_BSUID_FIELDS:
        value = _text(item.get(field))
        if value:
            linked.update(bsuid_map.get(value, []))
    if cid and cid in known_ids:
        return cid, sorted(linked - {cid})
    if cid:
        return None, sorted(linked)
    return None, sorted(linked)


def _empty_counts() -> Dict[str, Dict[str, int]]:
    return {t: {"total": 0, "financial": 0, "uncertain": 0} for t in MESSAGE_TABLES}


def classify(tables: Mapping[str, Any], selection: Selection, *, now: Optional[int] = None,
             ttl_warn_days: int = 90, ttl_client: Any = None, table_names: Optional[Mapping[str, str]] = None,
             expect_keep_contacts: Optional[int] = None,
             expect_keep_messages: Optional[int] = None) -> Dict[str, Any]:
    """Build the report. Never writes. `tables` maps logical names to read-capable tables."""
    now = int(now if now is not None else time.time())
    ro = {name: ReadOnlyTable(tbl, name) for name, tbl in tables.items()}
    global_problems: List[str] = []

    # Contacts must be readable, otherwise there is nothing trustworthy to report.
    try:
        contact_rows = scan_all(ro["contacts"], "contacts")
    except InventoryIncomplete as exc:
        return {"status": "INCOMPLETE", "problems": [str(exc)], "contacts": [], "eligible": [],
                "totals": {}, "ttl": {}, "selection": {}}

    valid_rows = [r for r in contact_rows if isinstance(r, dict)]
    id_counts: Dict[str, int] = defaultdict(int)
    for row in valid_rows:
        id_counts[contact_identity(row)] += 1

    selected, unmatched, ambiguous = resolve_selection(valid_rows, selection)
    selection_problems: List[str] = []
    if selection.empty():
        selection_problems.append("no selector supplied")
    if unmatched:
        selection_problems.append("selectors matched no contact: " + ", ".join(unmatched))
    if ambiguous:
        selection_problems.append("selectors matched more than one contact: " + ", ".join(ambiguous))

    # Payment evidence, read once. A failure here means no contact can be proven free of payments.
    index = PaymentIndex()
    for name in PAYMENT_TABLES:
        try:
            for row in scan_all(ro[name], name):
                index.add(name, row)
        except InventoryIncomplete as exc:
            global_problems.append(str(exc))

    # Messages, read once per table.
    messages: Dict[str, List[Any]] = {}
    for name in MESSAGE_TABLES:
        try:
            messages[name] = scan_all(ro[name], name)
        except InventoryIncomplete as exc:
            global_problems.append(str(exc))
            messages[name] = []
    failed_message_tables = {n for n in MESSAGE_TABLES if any(p.startswith(n + ":") for p in global_problems)}

    known_ids = {contact_identity(r) for r in valid_rows if contact_identity(r)}
    phone_map: Dict[str, List[str]] = defaultdict(list)
    bsuid_map: Dict[str, List[str]] = defaultdict(list)
    for row in valid_rows:
        cid = contact_identity(row)
        if not cid:
            continue
        if phone_digits(row.get("phone")):
            phone_map[phone_digits(row.get("phone"))].append(cid)
        for field in ("bsuid", "parentBsuid"):
            if _text(row.get(field)):
                bsuid_map[_text(row.get(field))].append(cid)

    counts: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(_empty_counts)
    msg_reasons: Dict[str, Set[str]] = defaultdict(set)  # contact -> review reasons from messages
    fin_reasons: Dict[str, Set[str]] = defaultdict(set)
    msg_records: List[Dict[str, Any]] = []  # for TTL: every message with owner and flags
    orphans = {t: {"total": 0, "financial": 0} for t in MESSAGE_TABLES}

    for table_name in MESSAGE_TABLES:
        for item in messages[table_name]:
            if not isinstance(item, dict):
                msg_reasons["__unreadable__"].add(f"{table_name}: unreadable message item")
                orphans[table_name]["total"] += 1
                continue
            mid = message_id(item)
            signals = message_financial_signals(item, index)
            owner, others = _message_owner(item, known_ids, phone_map, bsuid_map)
            targets = [owner] if owner else []
            if not owner and others:
                # No usable contactId but an exact phone/BSUID link: attach, and flag for review.
                targets = others
                for t in targets:
                    msg_reasons[t].add("message linked only by phone or BSUID, not contactId")
            elif owner and others:
                for t in others:
                    msg_reasons[t].add("message also matches this contact by phone or BSUID "
                                       "but is stored under another contactId")
            if not targets:
                orphans[table_name]["total"] += 1
                if signals:
                    orphans[table_name]["financial"] += 1
                    msg_records.append({"table": table_name, "id": mid, "owner": None,
                                        "financial": True, "expiresAt": item.get(TTL_ATTRIBUTE)})
                continue
            for t in targets:
                c = counts[t][table_name]
                c["total"] += 1
                if signals:
                    c["financial"] += 1
                    fin_reasons[t].add("payment-related message")
                if not mid:
                    c["uncertain"] += 1
                    msg_reasons[t].add("message without an id")
                msg_records.append({"table": table_name, "id": mid, "owner": t,
                                    "financial": bool(signals), "expiresAt": item.get(TTL_ATTRIBUTE)})

    contacts_out: List[Dict[str, Any]] = []
    invoices_t = ro["invoices"]
    orders_t = ro["orders"]

    # Rows with no usable id cannot be addressed at all.
    for row in contact_rows:
        if not isinstance(row, dict) or not contact_identity(row):
            contacts_out.append({
                "contactId": None, "label": "unidentified", "maskedPhone": mask_phone(
                    row.get("phone") if isinstance(row, dict) else ""),
                "classification": REVIEW_REQUIRED, "reasons": ["contact row has no usable id"],
                "messageCounts": _empty_counts(), "financialMessages": 0, "uncertainMessages": 0,
                "alreadyArchived": False})

    for row in valid_rows:
        cid = contact_identity(row)
        if not cid:
            continue
        reasons: Dict[str, List[str]] = {k: [] for k in PRECEDENCE}
        if cid in selected:
            reasons[OPERATOR_HOLD].append("selected by operator identifier or merge linkage")

        # Financial
        try:
            linkage = has_payment_links(invoices_table=invoices_t, orders_table=orders_t,
                                        contact_row=row)
            if linkage.blocked:
                reasons[FINANCIAL_RETENTION].append(linkage.reason)
        except PaymentLinkageUnknown as exc:
            reasons[REVIEW_REQUIRED].append(str(exc))
        reasons[FINANCIAL_RETENTION].extend(index.contact_reasons(row, cid))
        reasons[FINANCIAL_RETENTION].extend(sorted(fin_reasons.get(cid, [])))

        # Lock
        if contact_lock.is_locked(row):
            reasons[LEGAL_OR_IDENTITY_LOCK].append("contact is locked")

        # Review
        if id_counts[cid] > 1:
            reasons[REVIEW_REQUIRED].append("duplicate contact id in scan")
        if row_id_conflict(row):
            reasons[REVIEW_REQUIRED].append("id and contactId disagree")
        if _text(row.get("mergedIntoContactId")) or _text(row.get("mergeState")):
            reasons[REVIEW_REQUIRED].append("merge state present on a contact that was not selected")
        if row.get("deletedAt") is not None and row.get("deletedAt") != "":
            reasons[REVIEW_REQUIRED].append("contact carries deletedAt")
        if not phone_digits(row.get("phone")) and not _text(row.get("bsuid")):
            reasons[REVIEW_REQUIRED].append("no phone or BSUID, identity cannot be checked")
        for t in sorted(failed_message_tables):
            reasons[REVIEW_REQUIRED].append(f"{t} could not be fully read")
        for p in global_problems:
            if p.split(":")[0] in PAYMENT_TABLES:
                reasons[REVIEW_REQUIRED].append(f"payment inventory incomplete ({p.split(':')[0]})")
        if selection_problems:
            reasons[REVIEW_REQUIRED].append("selection not resolved cleanly")
        reasons[REVIEW_REQUIRED].extend(sorted(msg_reasons.get(cid, [])))
        if "__unreadable__" in msg_reasons:
            reasons[REVIEW_REQUIRED].append("an unreadable message item exists")

        label = next((k for k in PRECEDENCE[:-1] if reasons[k]), ELIGIBLE)
        c = counts[cid]
        fin = sum(c[t]["financial"] for t in MESSAGE_TABLES)
        unc = sum(c[t]["uncertain"] for t in MESSAGE_TABLES)
        archived = bool(_text(row.get("archivedAt")))
        out_reasons = list(dict.fromkeys(reasons[label] if label != ELIGIBLE else
                                         ["all reads succeeded and nothing protects this contact"]))
        # Show every protective reason, not only the winning label's.
        extra = [f"{k}: {r}" for k in PRECEDENCE[:-1] if k != label for r in reasons[k]]
        contacts_out.append({
            "contactId": cid, "label": opaque(cid), "maskedPhone": mask_phone(row.get("phone")),
            "classification": label, "reasons": out_reasons, "alsoProtectedBy": extra,
            "messageCounts": {t: dict(c[t]) for t in MESSAGE_TABLES},
            "messageTotal": sum(c[t]["total"] for t in MESSAGE_TABLES),
            "financialMessages": fin, "uncertainMessages": unc,
            "alreadyArchived": archived,
        })

    # Keep expectations
    keep_contacts = [c for c in contacts_out if c["contactId"] in selected]
    keep_messages = sum(c["messageTotal"] for c in keep_contacts)
    expectation_problems: List[str] = []
    if expect_keep_contacts is not None and len(keep_contacts) != expect_keep_contacts:
        expectation_problems.append(
            f"expected {expect_keep_contacts} kept contacts, resolved {len(keep_contacts)}")
    if expect_keep_messages is not None and keep_messages != expect_keep_messages:
        expectation_problems.append(
            f"expected {expect_keep_messages} kept messages, resolved {keep_messages}")

    blocked_reasons = selection_problems + expectation_problems
    if expectation_problems or selection_problems:
        status = "BLOCKED_SELECTION_MISMATCH"
    elif global_problems:
        status = "INCOMPLETE"
    else:
        status = "OK"
    if status != "OK":
        # Nothing may be reported as eligible when the inventory or selection is not trusted.
        for c in contacts_out:
            if c["classification"] == ELIGIBLE:
                c["classification"] = REVIEW_REQUIRED
                c["reasons"] = ["run blocked: " + "; ".join(blocked_reasons + global_problems)]

    eligible = [c for c in contacts_out
                if c["classification"] == ELIGIBLE and not c["alreadyArchived"]]
    archived_done = [c for c in contacts_out
                     if c["classification"] == ELIGIBLE and c["alreadyArchived"]]

    ttl = _ttl_report(msg_records, selected, ro_names=table_names or {}, ttl_client=ttl_client,
                      now=now, warn_days=ttl_warn_days)

    by_label: Dict[str, int] = defaultdict(int)
    for c in contacts_out:
        by_label[c["classification"]] += 1
    eligible_ids = {c["contactId"] for c in eligible}
    msg_total = sum(c.get("messageTotal", 0) for c in contacts_out)
    msg_eligible = sum(c.get("messageTotal", 0) for c in eligible)
    totals = {
        "contactsScanned": len(contact_rows),
        "byClassification": {k: by_label.get(k, 0) for k in PRECEDENCE},
        "contactsRetained": len(contacts_out) - len(eligible) - len(archived_done),
        "contactsEligible": len(eligible),
        "contactsAlreadyArchived": len(archived_done),
        "messagesAttributedToContacts": msg_total,
        "messagesRetained": msg_total - msg_eligible,
        "messagesEligible": msg_eligible,
        "keptSelectedContacts": len(keep_contacts),
        "keptSelectedMessages": keep_messages,
        "unattributedMessages": {t: dict(v) for t, v in orphans.items()},
    }
    return {
        "status": status,
        "problems": blocked_reasons + global_problems,
        "selection": {"resolvedContacts": len(keep_contacts), "resolvedMessages": keep_messages,
                      "unmatchedSelectors": unmatched, "ambiguousSelectors": ambiguous},
        "totals": totals,
        "contacts": contacts_out,
        "eligible": [{"contactId": c["contactId"], "label": c["label"],
                      "maskedPhone": c["maskedPhone"], "messageTotal": c["messageTotal"],
                      "messageCounts": c["messageCounts"]} for c in eligible
                     if c["contactId"] in eligible_ids],
        "ttl": ttl,
        "followUp": ("Cleanup is Archive only: archive each listed contact through the existing "
                     "contacts API (Admin + MFA, with an operator reason). This script never "
                     "archives, deletes or writes."),
    }


def _ttl_report(msg_records: List[Dict[str, Any]], selected: Set[str], *, ro_names: Mapping[str, str],
                ttl_client: Any, now: int, warn_days: int) -> Dict[str, Any]:
    state: Dict[str, str] = {}
    for logical in MESSAGE_TABLES + PAYMENT_TABLES:
        name = ro_names.get(logical)
        if ttl_client is None or not name:
            state[logical] = "NOT_CHECKED"
            continue
        try:
            desc = ttl_client.describe_time_to_live(TableName=name)
            spec = desc.get("TimeToLiveDescription") or {}
            status = spec.get("TimeToLiveStatus", "UNKNOWN")
            attr = spec.get("AttributeName")
            state[logical] = f"{status}:{attr}" if attr else str(status)
        except Exception as exc:  # noqa: BLE001
            state[logical] = f"UNKNOWN ({type(exc).__name__})"

    horizon = now + warn_days * 86400
    per_table: Dict[str, Dict[str, int]] = {
        t: {"protectedMessages": 0, "withExpiry": 0, "expiringSoon": 0, "alreadyExpired": 0}
        for t in MESSAGE_TABLES}
    at_risk: List[Dict[str, Any]] = []
    for rec in msg_records:
        if not (rec["financial"] or rec["owner"] in selected):
            continue
        row = per_table[rec["table"]]
        row["protectedMessages"] += 1
        try:
            expires = int(rec["expiresAt"]) if rec["expiresAt"] not in (None, "") else None
        except (TypeError, ValueError):
            expires = None
        if expires is None:
            continue
        row["withExpiry"] += 1
        if expires <= now:
            row["alreadyExpired"] += 1
            flag = "ALREADY_PAST_EXPIRY"
        elif expires <= horizon:
            row["expiringSoon"] += 1
            flag = "EXPIRES_WITHIN_WINDOW"
        else:
            continue
        at_risk.append({"table": rec["table"], "messageId": rec["id"],
                        "owner": opaque(rec["owner"]) if rec["owner"] else None,
                        "reason": "payment-related" if rec["financial"] else "kept contact",
                        "expiresAt": expires, "flag": flag})
    return {
        "ttlState": state, "warnDays": warn_days, "perTable": per_table, "atRisk": at_risk,
        "remediation": ("Copy the affected messages and necessary media to an approved non-expiring "
                        "evidence store, or get a reviewed, minimized TTL exception, before they "
                        "expire. This script modifies no TTL setting and copies nothing."),
    }


# ── Output ───────────────────────────────────────────────────────────────────────────────────


def render_summary(report: Dict[str, Any]) -> str:
    lines: List[str] = [f"Contact cleanup dry run (read-only). Status: {report['status']}"]
    for problem in report.get("problems", []):
        lines.append(f"  PROBLEM: {problem}")
    totals = report.get("totals") or {}
    if totals:
        lines.append(f"Contacts scanned: {totals['contactsScanned']}")
        for label, n in totals["byClassification"].items():
            lines.append(f"  {label}: {n}")
        lines.append(f"Contacts retained: {totals['contactsRetained']}  eligible: "
                     f"{totals['contactsEligible']}  already archived: {totals['contactsAlreadyArchived']}")
        lines.append(f"Messages retained: {totals['messagesRetained']}  eligible: "
                     f"{totals['messagesEligible']}")
        lines.append(f"Selected contacts kept: {totals['keptSelectedContacts']} with "
                     f"{totals['keptSelectedMessages']} messages")
    lines.append("")
    lines.append("Per contact (hashed label, masked phone, counts only):")
    for c in report.get("contacts", []):
        mc = c["messageCounts"]
        per_table = " ".join(f"{t}={mc[t]['total']}" for t in MESSAGE_TABLES)
        lines.append(f"  {c['label']} {c['maskedPhone'] or '-'} {c['classification']} "
                     f"msgs[{per_table}] financial={c['financialMessages']} "
                     f"uncertain={c['uncertainMessages']}")
    lines.append("")
    eligible = report.get("eligible", [])
    lines.append(f"Eligible for the approved Archive action ({len(eligible)}):")
    for e in eligible:
        lines.append(f"  {e['contactId']} {e['maskedPhone'] or '-'} messages={e['messageTotal']}")
    ttl = report.get("ttl") or {}
    if ttl:
        lines.append("")
        lines.append("TTL gap check:")
        for t, s in ttl["ttlState"].items():
            lines.append(f"  {t}: {s}")
        for t, row in ttl["perTable"].items():
            lines.append(f"  {t}: protected={row['protectedMessages']} withExpiry={row['withExpiry']} "
                         f"expiringWithin{ttl['warnDays']}d={row['expiringSoon']} "
                         f"alreadyPast={row['alreadyExpired']}")
        lines.append(f"  at-risk messages listed in the JSON report: {len(ttl['atRisk'])}")
        lines.append("  " + ttl["remediation"])
    lines.append("")
    lines.append(report.get("followUp", ""))
    return "\n".join(lines)


def _git(args: List[str], cwd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=20)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 128, ""


def refuse_if_tracked_location(path: str) -> Optional[str]:
    """Return an error text if `path` is inside a git work tree and is not gitignored."""
    absolute = os.path.abspath(path)
    directory = os.path.dirname(absolute) or "."
    probe = directory
    while probe and not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    code, top = _git(["rev-parse", "--show-toplevel"], probe or ".")
    if code != 0 or not top:
        return None
    code, _ = _git(["check-ignore", "-q", absolute], probe or ".")
    if code == 0:
        return None
    return (f"refusing to use {os.path.basename(absolute)}: it is inside a git work tree and not "
            "gitignored. Use a path outside the repository.")


def write_report(path: str, report: Dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    os.chmod(path, 0o600)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only contact cleanup dry run.")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--table-prefix", default=os.environ.get("TABLE_PREFIX", DEFAULT_PREFIX),
                   help="prefix for default table names")
    for logical in TABLE_SUFFIXES:
        p.add_argument(f"--{logical}-table", default=None, help=f"override {logical} table name")
    p.add_argument("--keep-config", help="private JSON file: {contactIds, phones, bsuids}")
    p.add_argument("--keep-contact-id", action="append", default=[])
    p.add_argument("--keep-phone", action="append", default=[], help="exact full E.164 phone")
    p.add_argument("--keep-bsuid", action="append", default=[])
    p.add_argument("--expect-keep-contacts", type=int, default=None)
    p.add_argument("--expect-keep-messages", type=int, default=None)
    p.add_argument("--ttl-warn-days", type=int, default=90)
    p.add_argument("--output", help="write the full JSON report here (mode 0600)")
    return p


def table_names_from(args: argparse.Namespace) -> Dict[str, str]:
    return {logical: (getattr(args, f"{logical}_table") or f"{args.table_prefix}-{suffix}")
            for logical, suffix in TABLE_SUFFIXES.items()}


def _default_backend(region: str) -> Tuple[Callable[[str], Any], Any]:
    import boto3  # imported late so tests and --help work without AWS

    resource = boto3.resource("dynamodb", region_name=region)
    client = boto3.client("dynamodb", region_name=region)
    return resource.Table, client


def main(argv: Optional[List[str]] = None,
         backend: Optional[Callable[[str], Tuple[Callable[[str], Any], Any]]] = None) -> int:
    """`backend(region)` returns (table_factory, ttl_client); tests inject fakes."""
    args = build_parser().parse_args(argv)
    try:
        selection = Selection(args.keep_contact_id, args.keep_phone, args.keep_bsuid)
        if args.keep_config:
            problem = refuse_if_tracked_location(args.keep_config)
            if problem:
                print(problem, file=sys.stderr)
                return 64
            from_file = load_selection_file(args.keep_config)
            selection = Selection(selection.contact_ids + from_file.contact_ids,
                                  selection.phones + from_file.phones,
                                  selection.bsuids + from_file.bsuids)
    except (OSError, ValueError) as exc:
        print(f"selection file error: {type(exc).__name__}", file=sys.stderr)
        return 64
    if selection.empty():
        print("supply at least one of --keep-config, --keep-contact-id, --keep-phone, --keep-bsuid",
              file=sys.stderr)
        return 64
    if args.output:
        problem = refuse_if_tracked_location(args.output)
        if problem:
            print(problem, file=sys.stderr)
            return 64

    names = table_names_from(args)
    factory, ttl_client = (backend or _default_backend)(args.region)
    tables = {logical: factory(name) for logical, name in names.items()}
    report = classify(tables, selection, ttl_warn_days=args.ttl_warn_days, ttl_client=ttl_client,
                      table_names=names, expect_keep_contacts=args.expect_keep_contacts,
                      expect_keep_messages=args.expect_keep_messages)
    print(render_summary(report))
    if args.output:
        write_report(args.output, report)
        print(f"Full report written to {os.path.basename(args.output)} (mode 0600).")
    if report["status"] == "BLOCKED_SELECTION_MISMATCH":
        return 3
    if report["status"] == "INCOMPLETE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
