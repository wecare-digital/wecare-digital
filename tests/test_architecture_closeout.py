"""Behavioural regression tests for the 2026-10-26 production architecture closeout.

Real handler code with in-process fakes: no network, no AWS account, no table outside memory.

* outbound-whatsapp sends a payment-order status only as the approved template, whatever the
  24-hour window says, and refuses shipment/cancel states before anything is sent;
* the invoice engine releases its `claiming` row when it refuses before consuming a GST number,
  so a retry numbers the invoice instead of answering 200 with an empty number;
* a consumed number keeps its claim, so a retry cannot consume a second number;
* a failed dedup lookup refuses (503) instead of claiming a possible second invoice;
* the Razorpay webhook never renders or sends a receipt for an unnumbered invoice;
* the paid-state alarm covers a missing invoice image.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_commerce_audit_hardening import (  # noqa: E402 - shared in-process fakes
    FUNCTIONS, ROOT, FakeResource, FakeTable, _conditional_failure, _load)


class InvoiceTable(FakeTable):
    """FakeTable plus the scan and the conditional delete the invoice create path uses."""

    def __init__(self, name: str, *, scan_error: bool = False, fail_numbered_put: bool = False):
        super().__init__("invoiceId", name)
        self.scan_error, self.fail_numbered_put = scan_error, fail_numbered_put

    def scan(self, ExpressionAttributeValues=None, **_kw):
        if self.scan_error:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException",
                                         "Message": "throttled"}}, "Scan")
        values = ExpressionAttributeValues or {}
        ref, pid = values.get(":ref"), values.get(":pid")
        return {"Items": [copy.deepcopy(row) for row in self.rows.values()
                          if (ref and row.get("referenceId") == ref)
                          or (pid and row.get("paymentId") == pid)]}

    def put_item(self, Item, ConditionExpression=None, **kw):
        if self.fail_numbered_put and Item.get("invoiceNumber"):
            raise ClientError({"Error": {"Code": "InternalServerError", "Message": "boom"}},
                              "PutItem")
        return super().put_item(Item, ConditionExpression=ConditionExpression, **kw)

    def delete_item(self, Key, ExpressionAttributeValues=None, **_kw):
        row = self.rows.get(Key[self.key])
        if (row is None or row.get("status") != (ExpressionAttributeValues or {}).get(":claiming")
                or "invoiceNumber" in row):
            raise _conditional_failure()
        del self.rows[Key[self.key]]
        self.writes.append(("delete", Key[self.key]))
        return {}


INVOICE_BODY = {
    "referenceId": "WD-PAY-CLOSEOUT1",
    "paymentId": "pay_CLOSEOUT0001",
    "customerPhone": "+919999900001",
    "customerName": "Closeout Test",
    "entryPoint": "webhook",
    "goodsType": "digital-goods",
    "status": "paid",
    "paymentStatus": "captured",
    "gstRate": 18,
    "items": [{"name": "Service", "amount": 100, "quantity": 1}],
}


class InvoiceClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = _load("invoice_engine_closeout_under_test",
                           FUNCTIONS / "payments" / "invoice-engine" / "handler.py")

    def use_table(self, **kw) -> InvoiceTable:
        table = InvoiceTable(self.engine.INVOICES_TABLE, **kw)
        items = FakeTable("itemIndex", self.engine.INVOICE_ITEMS_TABLE)  # one invoice per test
        p = patch.object(self.engine, "dynamodb", FakeResource({
            self.engine.INVOICES_TABLE: table, self.engine.INVOICE_ITEMS_TABLE: items}))
        p.start()
        self.addCleanup(p.stop)
        return table

    def create(self, body=None, number="WD/2026-27/00042"):
        def next_number(_fy=None):
            if number is None:
                raise self.engine.InvoiceSequenceUnavailable("test outage")
            return number
        with patch.object(self.engine, "_get_next_invoice_number", next_number):
            result = self.engine.create_invoice(copy.deepcopy(body or INVOICE_BODY), "req-test")
        return int(result["statusCode"]), json.loads(result["body"])

    def test_sequence_outage_releases_the_claim_so_the_retry_numbers_the_invoice(self):
        table = self.use_table()
        status, body = self.create(number=None)
        self.assertEqual((status, body.get("errorCode")), (503, "INVOICE_SEQUENCE_UNAVAILABLE"))
        self.assertEqual([op for op, _ in table.writes], ["put", "delete"])
        self.assertEqual(table.rows, {})

        status, body = self.create()
        self.assertEqual(status, 201, body)
        self.assertEqual(body["invoiceNumber"], "WD/2026-27/00042")
        self.assertNotIn("deduplicated", body)
        self.assertEqual(table.rows[body["invoiceId"]]["invoiceNumber"], "WD/2026-27/00042")

    def test_refusal_after_the_claim_leaves_no_claiming_row(self):
        table = self.use_table()
        body = dict(INVOICE_BODY, customerPhone="")
        status, _ = self.create(body)
        self.assertEqual(status, 400)
        self.assertIn("put", [op for op, _ in table.writes], "the refusal must come after the claim")
        self.assertEqual(table.rows, {})

    def test_a_consumed_number_keeps_its_claim(self):
        table = self.use_table(fail_numbered_put=True)
        with self.assertRaises(ClientError):
            self.create()
        self.assertEqual([row["status"] for row in table.rows.values()], ["claiming"])
        self.assertNotIn("delete", [op for op, _ in table.writes])

    def test_dedup_lookup_failure_refuses_before_claiming(self):
        table = self.use_table(scan_error=True)
        status, body = self.create()
        self.assertEqual((status, body.get("errorCode")), (503, "INVOICE_DEDUP_UNAVAILABLE"))
        self.assertEqual(table.writes, [])


class OutboundPaymentOrderStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outbound = _load("outbound_closeout_under_test",
                             FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py")

    def setUp(self):
        self.sent: list = []

        def send(_phone_number_id, payload):
            self.sent.append(payload)
            return {"messageId": "wamid.CLOSEOUT"}

        for p in (patch.object(self.outbound, "_send_message", send),
                  patch.object(self.outbound, "_store_message_record", lambda **_kw: None),
                  patch.object(self.outbound, "_emit_delivery_metric", lambda *_a, **_kw: None)):
            p.start()
            self.addCleanup(p.stop)

    def send_status(self, status, *, template="wecare_order_status_v3", within_window=False):
        result = self.outbound._handle_order_status_send(
            "msg-test", "contact-test", "+919999900001", "1016149501586345",
            {"reference_id": "WD-PAY-CLOSEOUT1", "order_status": status, "description": ""},
            "req-test", template_name=template, within_window=within_window)
        return int(result["statusCode"]), json.loads(result["body"])

    def test_shipment_and_cancel_states_are_refused_before_any_send(self):
        for status in ("shipped", "partially-shipped", "canceled"):
            for window in (True, False):
                code, body = self.send_status(status, within_window=window)
                self.assertEqual((code, body.get("error")), (400, "ORDER_STATUS_NOT_ALLOWED"),
                                 (status, window))
        self.assertEqual(self.sent, [])

    def test_payment_states_travel_as_the_template_whatever_the_window(self):
        for status in ("processing", "completed"):
            for window in (True, False):
                code, body = self.send_status(status, within_window=window)
                self.assertEqual((code, body.get("orderStatusChannel")), (200, "template"))
        self.assertEqual(len(self.sent), 4)
        for payload in self.sent:
            self.assertEqual(payload["type"], "template")
            self.assertNotIn("interactive", payload)
            self.assertEqual(payload["template"]["name"], "wecare_order_status_v3")
        self.assertIn("Payment received.", json.dumps(self.sent[0]))

    def test_an_open_window_without_the_template_defers_instead_of_going_interactive(self):
        code, body = self.send_status("processing", template="", within_window=True)
        self.assertEqual((code, body.get("error")), (409, "ORDER_STATUS_DEFERRED"))
        self.assertEqual(self.sent, [])


class _Payload:
    def __init__(self, body: dict):
        self._raw = json.dumps({"statusCode": 200, "body": json.dumps(body)}).encode("utf-8")

    def read(self) -> bytes:
        return self._raw


class WebhookUnnumberedInvoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.webhook = _load("webhook_closeout_under_test",
                            FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py")

    def run_post_payment(self, engine_body: dict):
        quarantined, ensured = [], []

        class FakeLambda:
            def invoke(self, **_kw):
                return {"Payload": _Payload(engine_body)}

        with patch.object(self.webhook, "lambda_client", FakeLambda()), \
                patch.object(self.webhook, "_native_cart_invoice_fields", lambda *_a, **_k: {}), \
                patch.object(self.webhook, "dynamodb", FakeResource({})), \
                patch.object(self.webhook.order_keys, "record_capture_quarantine",
                             lambda _table, **kw: quarantined.append(kw)), \
                patch.object(self.webhook, "_ensure_invoice_asset",
                             lambda *a, **_k: ensured.append(a) or (_ for _ in ()).throw(
                                 StopIteration("reached rendering"))):
            try:
                self.webhook._post_payment_handler(
                    "pay_CLOSEOUT0001", "+919999900001", "", "closeout", {}, "req-test",
                    checkout_mode="WHATSAPP_NATIVE_PG", originating_phone_id="1016149501586345",
                    reference_id="WD-PAY-CLOSEOUT1")
            except RuntimeError as error:
                return "raised", str(error), quarantined, ensured
            except StopIteration:
                return "rendered", "", quarantined, ensured
        return "returned", "", quarantined, ensured

    def test_unnumbered_invoice_is_quarantined_and_never_rendered(self):
        outcome, _msg, quarantined, ensured = self.run_post_payment(
            {"invoiceId": "inv-claiming", "invoiceNumber": "", "deduplicated": True})
        self.assertEqual(outcome, "raised")
        self.assertEqual(ensured, [])
        self.assertEqual(quarantined[0]["outcome"], "INVOICE_CREATE_FAILED")
        self.assertEqual(quarantined[0]["extra"]["stage"], "UNNUMBERED_INVOICE")

    def test_numbered_invoice_still_reaches_rendering(self):
        outcome, _msg, quarantined, ensured = self.run_post_payment(
            {"invoiceId": "inv-done", "invoiceNumber": "WD/2026-27/00042", "deduplicated": True})
        self.assertEqual(outcome, "rendered")
        self.assertEqual(len(ensured), 1)
        self.assertEqual(quarantined, [])


class PaidStateAlarmTests(unittest.TestCase):
    def test_missing_invoice_image_raises_the_paid_state_alarm(self):
        alarms = _load("payment_rail_alarms_closeout",
                       ROOT / "scripts" / "provision_payment_rail_alarms.py")
        webhook_signal = next(s for s in alarms.SIGNALS
                              if s["logGroup"] == "/aws/lambda/wecare-razorpay-webhook"
                              and s["filterName"] == "payment-paid-state-incomplete")
        self.assertIn('"INVOICE_IMAGE_ENSURE_FAILED"', webhook_signal["pattern"])
        source = (FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py").read_text(
            encoding="utf-8")
        self.assertIn("'alert': 'INVOICE_IMAGE_ENSURE_FAILED'", source)


if __name__ == "__main__":
    unittest.main()
