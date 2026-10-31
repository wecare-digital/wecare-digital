"""Hermetic proof: after a PAID service invoice the next WhatsApp CTA is the
verified service action, not an unrelated generic Orders link.

Execute the ACTUAL invoice-engine _send_order_page_link function with synthetic
DynamoDB/Meta responses. No AWS connection, live customer, provider or send.
"""
import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
SHARED = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_invoice_ledger.py"


class FakeInvoiceDB:
    def __init__(self, invoice):
        self.invoice = invoice
        self.reads = []

    def Table(self, table_name):
        self.reads.append(table_name)
        assert table_name == "synthetic-invoices"
        return self

    def get_item(self, *, Key, ConsistentRead):
        assert Key == {"invoiceId": "synthetic-invoice"}
        assert ConsistentRead is True
        return {"Item": self.invoice}


class FakeOrderKeys:
    class OrderIdentityUnavailable(Exception):
        pass

    def __init__(self, payref):
        self.payref = payref
        self.claims = []
        self.confirmations = []

    @staticmethod
    def is_public_order_number(value):
        return value == "WD-ORD-22222222"

    def resolve_payment_reference(self, keys, ref):
        assert keys == "synthetic-keys"
        assert ref == "WD-PAY-SYNTHETIC"
        return self.payref

    def claim_invoice_delivery(self, keys, *, invoice_id, channel, extra):
        self.claims.append((invoice_id, channel, extra))
        return len(self.claims) == 1

    def confirm_invoice_delivery(self, keys, *, invoice_id, channel, wa_message_id):
        self.confirmations.append((invoice_id, channel, wa_message_id))


class FakeLambda:
    def __init__(self):
        self.sends = []

    def invoke(self, *, FunctionName, InvocationType, Payload):
        assert FunctionName == "wecare-outbound-whatsapp:live"
        assert InvocationType == "RequestResponse"
        self.sends.append(json.loads(Payload)["body"])
        body = json.dumps({
            "statusCode": 200,
            "body": json.dumps({"whatsappMessageId": "wamid.synthetic.order"}),
        }).encode()
        return {"Payload": io.BytesIO(body)}


def _load(payref, *, paid=True):
    invoice = {
        "invoiceId": "synthetic-invoice",
        "orderNumber": "WD-ORD-22222222",
        "referenceId": "WD-PAY-SYNTHETIC",
        "status": "paid" if paid else "pending_payment",
    }
    db = FakeInvoiceDB(invoice)
    keys = FakeOrderKeys(payref)
    lam = FakeLambda()
    tree = ast.parse(SOURCE.read_text())
    fn = next(node for node in tree.body
              if isinstance(node, ast.FunctionDef)
              and node.name == "_send_order_page_link")
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "json": json,
        "dynamodb": db,
        "INVOICES_TABLE": "synthetic-invoices",
        "order_keys": keys,
        "service_invoice_ledger": SimpleNamespace(
            SERVICE_KINDS=frozenset({
                "SUBMIT_REQUEST", "REQUEST_AMENDMENT",
                "DROP_DOCS", "VAULT", "REQUEST_PICKUP",
            })),
        "_ORDER_PAGE_LINK_CHECKOUT_MODES": frozenset({"WHATSAPP_NATIVE_CART", "AWS_NATIVE"}),
        "_ORDER_PAGE_LINK_CHANNEL": "order-page-link",
        "_ORDER_PAGE_URL": "https://wecare.digital/orders/",
        "lambda_client": lam,
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), "exec"), namespace)
    send = namespace["_send_order_page_link"]

    def call():
        return send("synthetic-invoice", "synthetic-contact",
                    "+919000000000", "synthetic-sender",
                    "synthetic-keys", "test-internal")
    return call, keys, lam, db


def test_service_action_takes_next_message_slot_with_no_generic_send_or_claim():
    for kind in ("SUBMIT_REQUEST", "REQUEST_AMENDMENT", "DROP_DOCS",
                 "VAULT", "REQUEST_PICKUP"):
        payref = {
            "checkoutMode": "AWS_NATIVE",
            "serviceLine": {"kind": kind, "paise": 4900},
        }
        call, keys, lam, db = _load(payref)
        assert call() == "service_next_action_priority"
        assert call() == "service_next_action_priority"
        assert keys.claims == []
        assert keys.confirmations == []
        assert lam.sends == []
        assert db.reads == ["synthetic-invoices", "synthetic-invoices"]


def test_native_vault_session_also_avoids_unrelated_generic_order_link():
    call, keys, lam, _db = _load({
        "checkoutMode": "AWS_NATIVE",
        "nativeCatalogService": True,
    })
    assert call() == "service_next_action_priority"
    assert not keys.claims
    assert not lam.sends


def test_ordinary_whatsapp_cart_keeps_one_order_page_cta_with_durable_claim():
    call, keys, lam, _db = _load({"checkoutMode": "WHATSAPP_NATIVE_CART"})
    assert call() == "sent"
    assert call() == "already_sent"
    assert len(keys.claims) == 2
    assert keys.confirmations == [("synthetic-invoice", "order-page-link",
                                   "wamid.synthetic.order")]
    assert len(lam.sends) == 1
    data = json.loads(lam.sends[0])
    assert data["idempotencyKey"] == "order-page-link:synthetic-invoice"
    assert data["interactiveData"]["buttonText"] == "View your order"
    assert data["interactiveData"]["url"] == "https://wecare.digital/orders/"


def test_no_service_priority_for_unpaid_or_unrecognized_payment_reference():
    for paid, kind in ((False, "DROP_DOCS"), (True, "NOT_A_SERVICE")):
        call, _keys, lam, _db = _load({
            "checkoutMode": "AWS_NATIVE",
            "serviceLine": {"kind": kind},
        }, paid=paid)
        assert call() == "sent"
        assert len(lam.sends) == 1


def test_approved_money_and_invoice_messages_remain_separate_and_untouched():
    source = SOURCE.read_text()
    assert "if delivered and not force:" in source
    assert "service_next_action_priority" in source
    assert "wa_status in ('accepted', 'sent', 'delivered', 'read')" in source
    assert "order_keys.confirm_invoice_delivery(" in source
    assert "WA_INVOICE_TEMPLATE" in source
    assert "'templateFlowButton': {'index': 0, 'flowToken': review_flow_token}" in source
    assert "return 'service_next_action_priority'" in source
    assert "_ORDER_PAGE_LINK_CHECKOUT_MODES" in source
    assert "verified_service_kind" in SHARED.read_text()
