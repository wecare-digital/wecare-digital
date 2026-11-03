#!/usr/bin/env python3
"""Offline evidence contract. No network, DynamoDB, provider calls or customer data.

Runs under scripts/ because the platform's earlier standalone test tree was
retired. Intentional synthetic fixtures test only the pure evidence projection.
"""
import ast
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/payment_evidence.py"
SPEC = importlib.util.spec_from_file_location("payflow_payment_evidence_offline", MODULE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load offline payment evidence from {MODULE}")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def require(ok, reason):
    if not ok:
        raise AssertionError(reason)


invoice = {
    "invoiceId": "invoice-test-opaque-owner-A",
    "createdAt": 1793600000,
    "paidAt": 1793600004,
    "paymentStatus": "captured",
    "refundAt": 1793600099,
    "refundId": "refund-test-opaque-A",
    "customerPhone": "9999999999",
    "referenceId": "secret-reference-A",
}
rows = [
    {"invoiceId": invoice["invoiceId"], "timestamp": 1793600011,
     "channel": "whatsapp_order_status", "status": "completed",
     "waMessageId": "wamid.test-completed-A", "toNumber": "9999999999"},
    {"invoiceId": invoice["invoiceId"], "timestamp": 1793600010,
     "channel": "whatsapp_order_status", "status": "processing",
     "waMessageId": "wamid.test-processing-A"},
    {"invoiceId": invoice["invoiceId"], "timestamp": 1793600014,
     "channel": "whatsapp", "status": "sent", "waMessageId": "wamid.test-invoice-A"},
    {"invoiceId": "invoice-other-owner-B", "timestamp": 1793600020,
     "channel": "whatsapp", "status": "delivered", "waMessageId": "wamid.other-B"},
    {"invoiceId": invoice["invoiceId"], "timestamp": 1793600021,
     "channel": "whatsapp", "status": "failed", "waMessageId": "wamid.test-failure-A"},
    {"invoiceId": invoice["invoiceId"], "timestamp": 1793600030,
     "channel": "whatsapp", "status": "read", "waMessageId": ""},
]
d = m.invoice_evidence_timeline(invoice, rows)
require(d["scope"] == "authoritative_invoice_id", "Server invoice scope lost")
require([g["seconds"] for g in d["gaps"]] == [1, 3, None, None],
        "Gaps must be measured only for ordered, exact-invoice accepted sends")
require([g["status"] for g in d["gaps"]] == ["measured", "measured", "unverified", "unverified"],
        "Do not fill in access/click/download timings")
require(any(e["role"] == "payment_projection" and
            e["verificationClass"] == "invoice_paid_projection" for e in d["events"]),
        "Do not claim provider capture from a paid invoice projection")
require(any(e["role"] == "refund" and e["verificationClass"] == "refund_recorded" for e in d["events"]),
        "Refund must remain visible after capture")
require(any(e["verificationClass"] == "send_failed" for e in d["events"]),
        "Provider refusal cannot become accepted delivery")
require(any(e["verificationClass"] == "unverified" for e in d["events"]),
        "Missing WAMID must remain unverified")
require(all(e["utc"].endswith("Z") and len(e["recordFragment"]) == 12 for e in d["events"]),
        "Events need canonical UTC and opaque record fragments")
rendered = json.dumps(d)
for forbidden in ("9999999999", "secret-reference-A", "wamid.", "invoice-test-opaque-owner-A",
                  "invoice-other-owner-B", "wamid.other-B"):
    require(forbidden not in rendered, "Cross-owner ID or PII leaked: " + forbidden)
require(len(d["events"]) == 8, "A cross-invoice row must be rejected, not merged")
require(len(m._fragment(0)) == 12, "Zero-valued evidence id must have an opaque fragment")

# No fabricated paid state on pending invoices, no unconfirmed message acceptance.
pending = m.invoice_evidence_timeline(
    {"invoiceId": "pending-owner-C", "createdAt": 1793600000,
     "paidAt": 1793600100, "paymentStatus": "pending"},
    [{"invoiceId": "pending-owner-C", "channel": "whatsapp_order_status",
      "status": "processing", "timestamp": 1793600020, "waMessageId": ""}],
)
require(not any(e["role"] == "payment_projection" for e in pending["events"]),
        "Pending is never captured merely because paidAt exists")
require(all(g["status"] == "unverified" for g in pending["gaps"]),
        "Unconfirmed sends do not create measured gaps")

# Out-of-order receipts and incomparable timestamps must never yield a negative delta.
out_of_order = m.invoice_evidence_timeline(
    {"invoiceId": "out-of-order-D", "createdAt": 1793600000},
    [{"invoiceId": "out-of-order-D", "channel": "whatsapp_order_status",
      "status": "processing", "timestamp": 1793600040, "waMessageId": "wamid.p-D"},
     {"invoiceId": "out-of-order-D", "channel": "whatsapp_order_status",
      "status": "completed", "timestamp": 1793600020, "waMessageId": "wamid.c-D"}],
)
require(out_of_order["gaps"][0]["seconds"] is None,
        "Out-of-order timestamps must remain unverified")

invoice_engine = (ROOT / "amplify/functions/payments/invoice-engine/handler.py").read_text()
client = (ROOT / "src/api/domains/commerce.ts").read_text()
view = (ROOT / "src/components/workspace/pay/InvoiceRecords.tsx").read_text()
barrel = (ROOT / "src/api/client.ts").read_text()
require("export * from './domains/commerce'" in barrel,
        "Public API barrel must retain the commerce evidence exports after decomposition")
require("payment_evidence.invoice_evidence_timeline(invoice, logs)" in invoice_engine,
        "Invoice backend must create timeline, never browser compose it")
delivery_body = invoice_engine[invoice_engine.index("def get_delivery_log("):]
require("except Exception as exc:" in delivery_body
        and "measured = None" in delivery_body
        and "invalid_invoice_projection" in delivery_body,
        "Malformed or stale invoice identity must fail closed, not crash the ledger")
require("str(invoice.get('invoiceId') or '') != str(invoice_id)" in delivery_body,
        "A mismatched authoritative invoice PK must never get a projected chronology")

# Execute ONLY the parsed pure FY helper, with a frozen UTC clock. Importing the
# live Lambda module would create AWS clients, and is forbidden in an offline gate.
tree = ast.parse(invoice_engine)
fy_functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "_current_fy"]
require(len(fy_functions) == 1, "Exactly one invoice financial-year helper required")
clock = [0]
namespace = {"IST_OFFSET": 5 * 3600 + 30 * 60,
             "__builtins__": __builtins__,
             "time": SimpleNamespace(time=lambda: clock[0], gmtime=time.gmtime)}
fy_module = ast.Module(body=fy_functions, type_ignores=[])
exec(compile(fy_module, "invoice_fy_helper", "exec"), namespace)
for instant, expected in (
    (datetime(2026, 3, 31, 18, 29, 59, tzinfo=timezone.utc), "2025-2026"),
    (datetime(2026, 3, 31, 18, 30, 0, tzinfo=timezone.utc), "2026-2027"),
    (datetime(2027, 3, 31, 18, 29, 59, tzinfo=timezone.utc), "2026-2027"),
    (datetime(2027, 3, 31, 18, 30, 0, tzinfo=timezone.utc), "2027-2028"),
):
    clock[0] = int(instant.timestamp())
    require(namespace["_current_fy"]() == expected,
            f"India FY boundary mismatch at {instant.isoformat()}")
require("ConsistentRead=True" in invoice_engine[invoice_engine.index("def get_delivery_log("):],
        "Invoice chronology must use a consistent PK read")
require("invoiceId" in invoice_engine and "if str(row.get('invoiceId') or '') == str(invoice_id)" in invoice_engine,
        "Deny cross-invoice delivery rows")
require("evidenceTimeline?.scope === 'authoritative_invoice_id'" in view,
        "UI must reject an old backend or unscoped timeline")
require("request !== logRequest.current" in view and "setEvidenceTimeline( null )" in view,
        "Filter switches must invalidate stale evidence responses")
require("getInvoiceDeliveryLog" in client and "cache: 'no-store'" in client,
        "Avoid cached delivery-status authority")
require("@media(max-width:430px)" in view and ".ir-gaps>div" in view,
        "Narrow 320px / 390px evidence layout needs a single-column fallback")
print("PASS: invoice-scoped evidence, fault tolerance, opaque zero IDs and IST fiscal-year boundary")
