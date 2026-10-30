"""No-send contract tests for exact entitlement-to-invoice WhatsApp evidence joins."""
import ast
from pathlib import Path
import os
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/core/secure-files/handler.py"


class Table:
    def __init__(self, items=None, rows=None):
        self.items = items or {}
        self.rows = rows or []
        self.calls = []

    def get_item(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"Item": self.items.get(tuple(kwargs["Key"].items())[0][1], {})}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {"Items": self.rows[:kwargs.get("Limit", 100)]}


def engine(tables):
    module = ast.parse(HANDLER.read_text(encoding="utf-8"))
    wanted = {"_logged_send_evidence", "_verified_vault_payment_evidence"}
    funcs = [f for f in module.body if isinstance(f, ast.FunctionDef) and f.name in wanted]
    assert len(funcs) == len(wanted)
    namespace = {
        "Any": Any, "Dict": Dict, "os": os,
        "GRANTS_TABLE": "stack-wecare-digital-DownloadGrantsTable",
        "SERVICE_REQUESTS_TABLE": "stack-wecare-digital-ServiceRequestsTable",
        "_table": lambda name: tables[name],
        "_message_status_for_verified_send": lambda wamid: {
            "status": "DELIVERED" if wamid == "wamid.processing" else "READ",
            "observedAt": 1900001234,
        },
    }
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(HANDLER), "exec"), namespace)
    return namespace["_verified_vault_payment_evidence"]


def fixtures():
    file_row = {"fileId": "file-1", "ownerCustomerId": "customer-1",
                "ownerPhone": "919999999999", "vaultEntitlementId": "ent-1"}
    ent = {"grantId": "ent-1", "recordType": "VAULT_ENTITLEMENT",
           "entitlementState": "ACTIVE", "customerId": "customer-1",
           "ownerPhone": "919999999999", "fileId": "file-1",
           "sourceGrantId": "grant-1"}
    grant = {"grantId": "grant-1", "paid": True,
             "customerId": "customer-1", "ownerPhone": "919999999999",
             "fileId": "file-1", "entitlementId": "ent-1", "reference": "ref-1"}
    tables = {
        "stack-wecare-digital-DownloadGrantsTable": Table({"ent-1": ent, "grant-1": grant}),
        # GSI has INCLUDE projection; only the ID is present until base GetItem.
        "stack-wecare-digital-WhatsAppOutboundTable": Table(
            items={"m-1": {"id": "m-1", "direction": "outbound", "messageType": "template",
                           "paymentReferenceId": "ref-1", "whatsappMessageId": "wamid.native",
                           "createdAt": 1900000001}},
            rows=[{"id": "m-1", "paymentReferenceId": "ref-1"}]),
        "stack-wecare-digital-InvoicesTable": Table(rows=[
            {"invoiceId": "invoice-1", "paymentStatus": "paid", "referenceId": "ref-1"}]),
        "stack-wecare-digital-InvoiceDeliveryLogTable": Table(rows=[
            {"invoiceId": "invoice-1", "timestamp": 1900000009, "channel": "whatsapp",
             "status": "accepted", "waMessageId": "wamid.invoice"},
            {"invoiceId": "invoice-1", "timestamp": 1900000007, "channel": "whatsapp_order_status",
             "status": "completed", "waMessageId": "wamid.completed"},
            {"invoiceId": "invoice-1", "timestamp": 1900000005, "channel": "whatsapp_order_status",
             "status": "processing", "waMessageId": "wamid.processing"},
        ]),
    }
    return file_row, tables


def test_all_five_templates_and_two_order_updates_have_bound_status_times():
    row, tables = fixtures()
    evidence = engine(tables)(row)
    assert set(evidence) == {"nativePay", "processing", "completed", "invoice"}
    assert evidence["nativePay"]["status"] == "READ"
    assert evidence["processing"]["status"] == "DELIVERED"
    assert evidence["completed"]["status"] == "READ"
    assert evidence["invoice"]["status"] == "READ"
    assert all(e["observedAt"] == 1900001234 for e in evidence.values())
    projection = tables["stack-wecare-digital-WhatsAppOutboundTable"].calls
    assert projection[0][1]["IndexName"] == "paymentReferenceId-index"
    assert projection[1][1]["Key"] == {"id": "m-1"}


def test_mismatched_owner_never_reads_payment_or_invoice_logs():
    row, tables = fixtures()
    row["ownerCustomerId"] = "another-customer"
    evidence = engine(tables)(row)
    assert all(e["status"] == "NOT_TRACKED" for e in evidence.values())
    assert not tables["stack-wecare-digital-WhatsAppOutboundTable"].calls
    assert not tables["stack-wecare-digital-InvoicesTable"].calls


def test_ambiguous_invoice_does_not_link_invoice_or_order_status_messages():
    row, tables = fixtures()
    tables["stack-wecare-digital-InvoicesTable"].rows.append(
        {"invoiceId": "invoice-2", "paymentStatus": "paid", "referenceId": "ref-1"})
    evidence = engine(tables)(row)
    assert evidence["nativePay"]["status"] == "READ"
    for key in ("processing", "completed", "invoice"):
        assert evidence[key]["status"] == "NOT_TRACKED"
    assert not tables["stack-wecare-digital-InvoiceDeliveryLogTable"].calls
