"""Behavioural regression tests for the 2026-10-26 production architecture closeout.

Real handler code with in-process fakes: no network, no AWS account, no table outside memory.

* the invoice engine's WhatsApp payment-order route accepts only processing/completed targets;
* the invoice engine releases its `claiming` row when it refuses before consuming a GST number,
  so a retry numbers the invoice instead of answering 200 with an empty number;
* a consumed number keeps its claim, so a retry cannot consume a second number;
* a failed dedup lookup refuses (503) instead of claiming a possible second invoice;
* the Razorpay webhook never renders or sends a receipt for an unnumbered invoice;
* the paid-state alarm covers a missing invoice image and a paid order the sweep found with no
  invoice;
* both customer invoice readers serve the newest (paid) rendition, never the pre-payment one;
* two invoices matching one payment settle neither and consume no number;
* staff 'Send Access Vault' sends only for OPEN or READY access;
* a paid Vault fulfilment that raises is alerted and still retried;
* the two WhatsApp catalogs keep separate sync approvals for the same plan.
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



class PaymentArchitectureDriftTests(unittest.TestCase):
    """Secondary docs/audit tooling must not re-introduce the superseded #1650 contract."""

    def test_live_template_checker_expects_active_order_status_send(self):
        checker = (ROOT / "scripts" / "check_whatsapp_template_payloads_live.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("ORDER_STATUS_DISABLED", checker)
        self.assertIn("Payment-order status is automatic after verified capture", checker)
        self.assertIn("wecare_order_status_v3", checker)
        self.assertIn("must not select an interactive fallback", checker)
        self.assertIn("outbound automatic payment-order status path", checker)

    def test_experience_docs_pin_template_only_processing_completed(self):
        doc = (ROOT / "docs" / "whatsapp-experience-structure.md").read_text(encoding="utf-8")
        self.assertNotIn("WhatsApp order-status messages are disabled", doc)
        self.assertIn("automatically sends exactly two", doc)
        self.assertIn("wecare_order_status_v3", doc)
        self.assertIn("processing", doc)
        self.assertIn("completed", doc)
        self.assertIn("There is no interactive", doc)
        self.assertIn("Workspace has no manual payment-order status sender", doc)

    def test_keyed_whatsapp_send_uses_atomic_claim(self):
        source = (ROOT / "amplify" / "functions" / "messaging" / "outbound-whatsapp" / "handler.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _claim_keyed_outbound_send(", source)
        self.assertIn("ConditionExpression=(", source)
        self.assertIn("attribute_not_exists(id) OR #s = :failed OR #s = :rejected", source)
        self.assertIn("MESSAGE_SEND_IN_FLIGHT", source)
        self.assertNotIn("Idempotency check failed (proceeding)", source)

    def test_keyed_whatsapp_send_never_retries_ambiguous_transport_failure(self):
        source = (ROOT / "amplify" / "functions" / "messaging" / "outbound-whatsapp" / "handler.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("max_retries = 0 if keyed_send else 3", source)
        self.assertIn("retryable_http = (", source)
        self.assertIn("DELIVERY_OUTCOME_UNKNOWN", source)
        self.assertIn("status=stored_status", source)

    def test_payment_ci_triggers_on_template_registry_for_pr_and_push(self):
        workflow = (ROOT / ".github" / "workflows" / "payment-rail-ci.yml").read_text(
            encoding="utf-8"
        )
        path = '      - "amplify/functions/shared/lambda_utils/whatsapp_templates.py"'
        pull_request, remainder = workflow.split("  push:", 1)
        push, _dispatch = remainder.split("  workflow_dispatch:", 1)
        self.assertEqual(
            pull_request.count(path), 1,
            "template registry must trigger Payment Rail CI exactly once for pull_request",
        )
        self.assertEqual(
            push.count(path), 1,
            "template registry must trigger Payment Rail CI exactly once for wecare.digital push",
        )



class OrderStatusTemplateOnlyTransportTests(unittest.TestCase):
    """The automatic payment-order rail never changes transport with the service window."""

    def test_order_status_sender_is_template_only_even_on_failure(self):
        source = (
            FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py"
        ).read_text(encoding="utf-8")
        start = source.index("def _handle_order_status_send(")
        end = source.index("# ═══════════════════════════════════════════════════════════════════════════", start)
        sender = source[start:end]
        self.assertIn("channel = 'template'", sender)
        self.assertIn("_emit_delivery_metric('failed', is_template=True)", sender)
        self.assertNotIn("interactive\n", sender)
        self.assertNotIn("is_template=not within_window", sender)


class MessageHistoryAuditTests(unittest.TestCase):
    """Meta Message History is audit evidence; DynamoDB send claims stay the primary dedup gate."""

    def test_message_history_route_is_read_only_and_bounded(self):
        source = (
            FUNCTIONS / "messaging" / "whatsapp-business-api" / "handler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _get_message_history_events", source)
        self.assertIn("'/message-history/events' in path", source)
        self.assertIn("_MESSAGE_HISTORY_DELIVERY_STATUSES", source)
        self.assertIn("'ACCEPTED', 'SENT', 'DELIVERED', 'READ', 'ERROR'", source)
        self.assertIn("limit must be between 1 and 100", source)
        self.assertIn("'auditOnly': True", source)
        route = source[source.index("elif '/message-history/events' in path"):]
        route = route[:route.index("elif '/template-ttl/rules' in path")]
        self.assertIn("method != 'GET'", route)
        self.assertNotIn("_send_", route)

    def test_payment_duplicate_prevention_stays_claim_first(self):
        engine = (
            FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("claim_channel = f'order-status:{target}'", engine)
        self.assertIn("claim_invoice_delivery(", engine)
        self.assertIn("'code': 'ORDER_STATUS_IN_FLIGHT'", engine)
        self.assertIn("channel='whatsapp'", engine)
        self.assertNotIn("message-history/events", engine)

    def test_payment_messages_carry_stable_outbound_idempotency_keys(self):
        engine = (
            FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
        ).read_text(encoding="utf-8")
        checkout = (
            FUNCTIONS / "ecommerce" / "checkout" / "handler.py"
        ).read_text(encoding="utf-8")
        outbound = (
            FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("f'payment-request:{reference_id}'", engine)
        self.assertIn("f'order-status:{invoice_id}:{target}'", engine)
        self.assertIn("f'invoice-receipt:{invoice_id}'", engine)
        self.assertIn("f'order-page-link:{invoice_id}'", engine)
        self.assertIn('"idempotencyKey": f"payment-request:', checkout)
        self.assertIn("def _stable_outbound_message_id", outbound)
        self.assertIn("'event': 'idempotent_skip'", outbound)
        self.assertIn("'MESSAGE_SEND_IN_FLIGHT'", outbound)
        self.assertIn("def _claim_keyed_outbound_send", outbound)
        self.assertIn("attribute_not_exists(id) OR #s = :failed OR #s = :rejected", outbound)
        self.assertIn("max_retries = 0 if keyed_send else 3", outbound)

    def test_wamid_history_reconciliation_is_read_only_secondary_evidence(self):
        source = (
            FUNCTIONS / "messaging" / "whatsapp-business-api" / "handler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _message_history_for_wamid", source)
        self.assertIn("messageHistoryForWamid", source)
        self.assertIn("message_id", source)
        self.assertIn("metaAcceptedOrDelivered", source)
        helper = source[source.index("def _message_history_for_wamid"):]
        helper = helper[:helper.index("def _emit_event")]
        self.assertNotIn("_send_", helper)
        self.assertIn("business idempotency claim remains the primary duplicate-send guard", helper)


class AutomaticOrderStatusRouteTests(unittest.TestCase):
    """The payment-order route stays active for processing -> completed only."""

    @classmethod
    def setUpClass(cls):
        cls.engine = _load("invoice_engine_order_status_under_test",
                           FUNCTIONS / "payments" / "invoice-engine" / "handler.py")

    def test_payment_order_targets_are_processing_and_completed(self):
        self.assertEqual(
            set(self.engine.wa_order_status.PAYMENT_ORDER_TARGETS),
            {"processing", "completed"},
        )

    def test_shipment_statuses_are_not_payment_order_targets(self):
        for status in ("shipped", "partially-shipped", "canceled"):
            self.assertNotIn(status, self.engine.wa_order_status.PAYMENT_ORDER_TARGETS)



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

    def run_post_payment(self, *engine_bodies: dict):
        quarantined, ensured = [], []
        answers = list(engine_bodies)
        self.invokes = 0
        test = self

        class FakeLambda:
            def invoke(self, **_kw):
                test.invokes += 1
                return {"Payload": _Payload(answers.pop(0) if len(answers) > 1 else answers[0])}

        with patch.object(self.webhook, "lambda_client", FakeLambda()), \
                patch.object(self.webhook, "_IN_FLIGHT_INVOICE_RECHECK_SECONDS", 0), \
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

    CLAIMING = {"invoiceId": "inv-claiming", "invoiceNumber": "", "deduplicated": True}
    NUMBERED = {"invoiceId": "inv-claiming", "invoiceNumber": "WD/2026-27/00042",
                "deduplicated": True}

    def test_unnumbered_invoice_is_quarantined_and_never_rendered(self):
        outcome, _msg, quarantined, ensured = self.run_post_payment(self.CLAIMING)
        self.assertEqual(outcome, "raised")
        self.assertEqual(self.invokes, 2, "one bounded re-ask, then the incident")
        self.assertEqual(ensured, [])
        self.assertEqual(quarantined[0]["outcome"], "INVOICE_CREATE_FAILED")
        self.assertEqual(quarantined[0]["extra"]["stage"], "UNNUMBERED_INVOICE")

    def test_a_create_still_in_flight_is_re_asked_not_quarantined(self):
        outcome, _msg, quarantined, ensured = self.run_post_payment(self.CLAIMING, self.NUMBERED)
        self.assertEqual(outcome, "rendered")
        self.assertEqual(self.invokes, 2)
        self.assertEqual((len(ensured), quarantined), (1, []))

    def test_numbered_invoice_reaches_rendering_without_a_re_ask(self):
        outcome, _msg, quarantined, ensured = self.run_post_payment(self.NUMBERED)
        self.assertEqual(outcome, "rendered")
        self.assertEqual(self.invokes, 1)
        self.assertEqual((len(ensured), quarantined), (1, []))


class PaidStateAlarmTests(unittest.TestCase):
    def test_every_alarm_signal_is_still_emitted_by_the_code(self):
        """An alarm on an event no code emits can never fire; it reads as coverage it is not."""
        import re
        alarms = _load("payment_rail_alarms_emitted", ROOT / "scripts" / "provision_payment_rail_alarms.py")
        source = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                           for p in FUNCTIONS.rglob("*.py"))
        for signal in alarms.SIGNALS:
            tokens = [signal["event"]] if signal.get("event") else re.findall(
                r'\$\.(?:event|alert)\s*=\s*"([^"]+)"', signal.get("pattern", ""))
            self.assertTrue(tokens, signal["alarmName"])
            for token in tokens:
                self.assertTrue(f"'{token}'" in source or f'"{token}"' in source,
                                f"{signal['alarmName']}: {token} is not emitted")

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

    def test_paid_order_without_invoice_raises_the_paid_state_alarm(self):
        alarms = _load("payment_rail_alarms_paid_without_invoice",
                       ROOT / "scripts" / "provision_payment_rail_alarms.py")
        webhook_signal = next(s for s in alarms.SIGNALS
                              if s["logGroup"] == "/aws/lambda/wecare-razorpay-webhook"
                              and s["filterName"] == "payment-paid-state-incomplete")
        self.assertIn('"PAID_WITHOUT_INVOICE"', webhook_signal["pattern"])
        source = (FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py").read_text(
            encoding="utf-8")
        self.assertIn("'alert': 'PAID_WITHOUT_INVOICE'", source)


# ── Newest invoice rendition (D4) and ambiguous dedup (D6) ───────────────────────────────────

class AssetTable:
    """InvoiceAssets fake: composite (invoiceId, assetType) key, get_item only."""

    def __init__(self, rows):
        self.rows = {(r["invoiceId"], r["assetType"]): dict(r) for r in rows}
        self.reads: list = []

    def get_item(self, Key, **_kw):  # noqa: N803 - boto3 spelling
        self.reads.append(Key["assetType"])
        row = self.rows.get((Key["invoiceId"], Key["assetType"]))
        return {"Item": dict(row)} if row else {}


PREFIX = "secure/d/public/Invoice/customer_invoice/"
STEM = PREFIX + "wecare-digital-WD-2026-27-00042__WD-PAY-CLOSEOUT1"
PAID_INVOICE = {"invoiceId": "inv-1", "invoiceNumber": "WD/2026-27/00042",
                "referenceId": "WD-PAY-CLOSEOUT1"}


class NewestInvoiceRenditionTests(unittest.TestCase):
    """The base `image` row is the pre-payment preview; the paid receipt is `image#v2`."""

    ROWS = [{"invoiceId": "inv-1", "assetType": "image", "s3Key": STEM + ".png"},
            {"invoiceId": "inv-1", "assetType": "image#v2", "s3Key": STEM + "-v2.png"}]

    @classmethod
    def setUpClass(cls):
        cls.customer_invoice = _load("customer_invoice_rendition_under_test",
                                     FUNCTIONS / "ecommerce" / "customer-invoice" / "handler.py")
        flows_dir = FUNCTIONS / "messaging" / "whatsapp-business-api"
        if str(flows_dir) not in sys.path:
            sys.path.insert(0, str(flows_dir))
        from flows import customer_invoice as flow_invoice
        cls.flow_invoice = flow_invoice

    def download_key(self, rows):
        table = AssetTable(rows)
        with patch.object(self.customer_invoice, "_table", lambda _name: table):
            return self.customer_invoice._asset_key("inv-1", "png"), table.reads

    def test_customer_download_serves_the_paid_rendition(self):
        key, reads = self.download_key(self.ROWS)
        self.assertEqual(key, STEM + "-v2.png")
        self.assertEqual(reads, ["image", "image#v2", "image#v3"])

    def test_customer_download_with_one_rendition_is_unchanged(self):
        self.assertEqual(self.download_key(self.ROWS[:1])[0], STEM + ".png")
        self.assertEqual(self.download_key([])[0], "")

    def test_whatsapp_invoice_copy_serves_the_paid_rendition(self):
        table = AssetTable(self.ROWS)
        self.assertEqual(self.flow_invoice.newest_invoice_image(
            table, "inv-1", PAID_INVOICE, "WD-PAY-CLOSEOUT1"), STEM + "-v2.png")

    def test_whatsapp_invoice_copy_refuses_a_key_for_another_order(self):
        rows = [self.ROWS[0], {"invoiceId": "inv-1", "assetType": "image#v2",
                               "s3Key": PREFIX + "wecare-digital-SOMEONE-ELSE-v2.png"}]
        self.assertEqual(self.flow_invoice.newest_invoice_image(
            AssetTable(rows), "inv-1", PAID_INVOICE, "WD-PAY-CLOSEOUT1"), STEM + ".png")


class AmbiguousInvoiceDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = _load("invoice_engine_ambiguous_under_test",
                           FUNCTIONS / "payments" / "invoice-engine" / "handler.py")

    def test_two_matching_invoices_settle_neither(self):
        table = InvoiceTable(self.engine.INVOICES_TABLE)
        for invoice_id in ("inv-a", "inv-b"):
            table.rows[invoice_id] = {"invoiceId": invoice_id, "referenceId": "WD-PAY-CLOSEOUT1",
                                      "invoiceNumber": f"WD/2026-27/{invoice_id}", "status": "sent"}
        with patch.object(self.engine, "dynamodb", FakeResource({self.engine.INVOICES_TABLE: table})), \
                patch.object(self.engine, "_get_next_invoice_number",
                             lambda _fy=None: self.fail("a number was consumed")):
            result = self.engine.create_invoice(copy.deepcopy(INVOICE_BODY), "req-test")
        self.assertEqual((int(result["statusCode"]), json.loads(result["body"]).get("errorCode")),
                         (409, "INVOICE_REFERENCE_AMBIGUOUS"))
        self.assertEqual(table.writes, [])
        self.assertTrue(all(row["status"] == "sent" for row in table.rows.values()))

    def test_one_matching_invoice_is_still_adopted(self):
        table = InvoiceTable(self.engine.INVOICES_TABLE)
        table.rows["inv-a"] = {"invoiceId": "inv-a", "referenceId": "WD-PAY-CLOSEOUT1",
                               "invoiceNumber": "WD/2026-27/00042", "status": "paid"}
        with patch.object(self.engine, "dynamodb", FakeResource({self.engine.INVOICES_TABLE: table})), \
                patch.object(self.engine, "_get_next_invoice_number",
                             lambda _fy=None: self.fail("a number was consumed")):
            result = self.engine.create_invoice(copy.deepcopy(INVOICE_BODY), "req-test")
        self.assertNotEqual(int(result["statusCode"]), 409, result.get("body"))
        self.assertIn("inv-a", result.get("body", ""))


# ── Vault access resend, paid Vault failure alert, per-catalog sync approvals ────────────────

class VaultAccessResendTests(unittest.TestCase):
    """Staff 'Send Access Vault' sends only when the link opens the file (OPEN or READY)."""

    @classmethod
    def setUpClass(cls):
        cls.files = _load("secure_files_send_access_under_test",
                          FUNCTIONS / "core" / "secure-files" / "handler.py")

    def send(self, state):
        sent: list = []
        fake_delivery = type(sys)("whatsapp_delivery")
        fake_delivery.send_vault_link = lambda **kw: sent.append(kw) or (True, "")
        item = {"fileId": "vault-1", "ownerPhone": "919999900001", "status": "active"}
        with patch.dict(sys.modules, {"whatsapp_delivery": fake_delivery}), \
                patch.object(self.files, "_owned_file_for_admin", lambda _file_id: (item, None)), \
                patch.object(self.files, "_admin_access_state", lambda _item, _now: state):
            result = self.files._admin_send_access("vault-1", "https://wecare.digital")
        return int(result["statusCode"]), json.loads(result["body"]), sent

    def test_expired_and_unverified_access_get_no_link(self):
        for state, code in (("EXPIRED", "WINDOW_EXPIRED"), ("PAID_UNVERIFIED", "PAID_UNVERIFIED"),
                            ("UNPAID", "NOT_PAID")):
            status, body, sent = self.send(state)
            self.assertEqual((status, body.get("error")), (409, code), state)
            self.assertEqual(sent, [], state)

    def test_open_and_ready_access_still_get_the_link(self):
        for state in ("OPEN", "READY"):
            status, body, sent = self.send(state)
            self.assertEqual((status, body.get("outcome")), (200, "VAULT_LINK_SENT"), state)
            self.assertEqual(len(sent), 1, state)


class PaidVaultFailureAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flows_dir = FUNCTIONS / "messaging" / "whatsapp-business-api"
        if str(flows_dir) not in sys.path:
            sys.path.insert(0, str(flows_dir))
        from flows import paid_vault
        cls.paid_vault = paid_vault

    def test_an_exception_is_alerted_and_still_raised_for_the_retry(self):
        logged: list = []

        def down(*_args, **_kwargs):
            raise RuntimeError("table unavailable")

        event = {"referenceId": "WD-PAY-CLOSEOUT1", "paymentAttemptId": "attempt-1",
                 "orderId": "order-1"}
        with patch.object(self.paid_vault, "_prepare_and_send", down), \
                patch.object(self.paid_vault, "log_event",
                             lambda _logger, name, **fields: logged.append((name, fields))):
            with self.assertRaises(RuntimeError):
                self.paid_vault.prepare_and_send(event, None)
        self.assertEqual([name for name, _ in logged], ["paid_vault_not_delivered"])
        self.assertEqual((logged[0][1]["alert"], logged[0][1]["outcome"]),
                         ("PAID_VAULT_UNFULFILLED", "VAULT_ACCESS_ERROR"))
        self.assertEqual(logged[0][1]["referenceId"], "WD-PAY-CLOSEOUT1")


class CatalogApprovalPerCatalogTests(unittest.TestCase):
    """One ProductsTable change gives both WhatsApp catalogs the same plan fingerprint."""

    WABA1, WABA2 = "1457045652952851", "1317472650427643"

    @classmethod
    def setUpClass(cls):
        cls.sync = _load("meta_catalog_sync_approvals_under_test",
                         FUNCTIONS / "ecommerce" / "meta-catalog-sync" / "handler.py")

    def test_identical_plans_get_independent_approvals(self):
        import boto3
        from moto import mock_aws

        with mock_aws():
            table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
                TableName="approvals", BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": "planHash", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "planHash", "AttributeType": "S"}])
            store = self.sync._DynamoCatalogApprovalStore(table_name="approvals", table=table)
            plan = "ab" * 32
            common = {"plan_hash": plan, "counts": {"update": 1}, "blocked": [],
                      "desired_items": []}
            first = store.propose(catalog_id=self.WABA1, **common)
            second = store.propose(catalog_id=self.WABA2, **common)
            self.assertEqual((first["catalogId"], second["catalogId"]), (self.WABA1, self.WABA2))
            self.assertIsNotNone(store.approve(plan_hash=plan, catalog_id=self.WABA2,
                                               approved_by="staff-admin"))
            self.assertEqual(store.get(plan, self.WABA1)["status"], "PROPOSED")
            self.assertEqual(store.get(plan, self.WABA2)["status"], "APPROVED")
            # An approval on one catalog never lets the other apply.
            self.assertIsNone(store.claim_apply(plan_hash=plan, catalog_id=self.WABA1))
            self.assertIsNotNone(store.claim_apply(plan_hash=plan, catalog_id=self.WABA2))
            store.record_readback(plan_hash=plan, catalog_id=self.WABA2, current_plan_hash=plan,
                                  counts={}, verified=True)
            self.assertEqual(store.get(plan, self.WABA1)["status"], "PROPOSED")
            self.assertEqual(store.get(plan, self.WABA2)["status"], "APPLIED")


if __name__ == "__main__":
    unittest.main()
