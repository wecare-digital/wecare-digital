"""Regression tests for the 2026-10-26 commerce audit fixes.

Each test drives the real handler code with in-process fakes: no network, no AWS account and no
table outside process memory. Covered:

* the business API's retired Meta refund arm sends nothing for any caller;
* direct Meta catalog, feed, commerce-settings, catalog -> Flow map and WABA user-access writes
  need Admin, while their reads keep the Viewer floor;
* a Drop Docs re-publish after a reference revalidation reuses the Vault row serving the same
  bytes instead of minting a second, unpaid product;
* a captured Vault payment that yields no entitlement, or no Access Vault link, is logged with
  an alert instead of returning silently;
* non-catalog ORDER_DETAILS lines carry no synthetic retailer id;
* the new alarm signals name alerts the code actually emits.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
SHARED = FUNCTIONS / "shared"
BUSINESS_API_DIR = FUNCTIONS / "messaging" / "whatsapp-business-api"
SECURE_FILES_DIR = FUNCTIONS / "core" / "secure-files"

os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
# Client construction only; nothing in these tests may reach AWS.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
for path in (str(SHARED), str(BUSINESS_API_DIR), str(SECURE_FILES_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ── in-memory DynamoDB ───────────────────────────────────────────────────────────────────────

def _conditional_failure() -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException",
                                  "Message": "The conditional request failed"}}, "Op")


class FakeTable:
    """Just enough of a boto3 Table for the paths under test: keyed rows and SET updates."""

    _SET = re.compile(r"(\w+)\s*=\s*(if_not_exists\(\s*\w+\s*,\s*(:\w+)\s*\)|:\w+)")

    def __init__(self, key: str, name: str = "fake"):
        self.key, self.name = key, name
        self.rows: dict = {}
        self.writes: list = []

    def get_item(self, Key, **_kw):
        row = self.rows.get(Key[self.key])
        return {"Item": copy.deepcopy(row)} if row is not None else {}

    def put_item(self, Item, ConditionExpression=None, **_kw):
        if ConditionExpression and "attribute_not_exists" in ConditionExpression \
                and Item[self.key] in self.rows:
            raise _conditional_failure()
        self.rows[Item[self.key]] = copy.deepcopy(Item)
        self.writes.append(("put", Item[self.key]))
        return {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None,
                    ConditionExpression=None, ExpressionAttributeNames=None, **_kw):
        values = ExpressionAttributeValues or {}
        row = self.rows.setdefault(Key[self.key], {self.key: Key[self.key]})
        set_part = UpdateExpression.split("REMOVE")[0].replace("SET", "", 1)
        for field, expr, default in self._SET.findall(set_part):
            field = (ExpressionAttributeNames or {}).get(field, field)
            if expr.startswith("if_not_exists"):
                row.setdefault(field, values[default])
            else:
                row[field] = values[expr]
        self.writes.append(("update", Key[self.key]))
        return {}


class FakeResource:
    def __init__(self, tables: dict):
        self.tables = tables

    def Table(self, name):  # noqa: N802 - boto3 spelling
        return self.tables.setdefault(name, FakeTable("id", name))


# ── a role-aware stand-in for lambda_utils.middleware.require_auth ──────────────────────────

RANK = {"Viewer": 1, "Operator": 2, "Admin": 3}


def fake_require_auth(event, required_role=None):
    rc = event.get("requestContext") or {}
    if not (rc.get("apiId") or rc.get("domainName") or (rc.get("http") or {}).get("sourceIp")):
        return None  # internal invoke, as the real middleware treats it
    role = (event.get("headers") or {}).get("x-test-role", "")
    if RANK.get(role, 0) < RANK.get(required_role or "Viewer", 1):
        return {"statusCode": 403, "body": json.dumps({"error": "Insufficient permissions",
                                                       "requiredRole": required_role})}
    event["_auth"] = {"username": "staff-" + role.lower(), "role": role, "groups": [role]}
    return None


def api_event(method: str, path: str, *, role: str, body=None, query=None):
    return {
        "version": "2.0", "rawPath": path,
        "requestContext": {"apiId": "zllr9lrg7j",
                           "http": {"method": method, "path": path, "sourceIp": "203.0.113.9"}},
        "headers": {"authorization": "Bearer test", "x-test-role": role},
        "queryStringParameters": query or {},
        "body": json.dumps(body or {}),
    }


# ─────────────────────────────────────────────────────────────────────────────────────────────

class BusinessApiWriteGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("business_api_under_test", BUSINESS_API_DIR / "handler.py")
        import lambda_utils.middleware as middleware
        cls.middleware = middleware

    def setUp(self):
        self.graph_calls = []
        self.tables = {}

        def graph(path, method="GET", **kwargs):
            self.graph_calls.append((method, path))
            return {"data": [], "id": "graph-id", "success": True}

        patches = [
            patch.object(self.api, "require_auth", fake_require_auth),
            patch.object(self.middleware, "require_auth", fake_require_auth),
            patch.object(self.api, "_graph_api", graph),
            patch.object(self.api, "dynamodb", FakeResource(self.tables)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, *, role, body=None, query=None):
        result = self.api.handler(api_event(method, path, role=role, body=body, query=query),
                                  SimpleNamespace(aws_request_id="test"))
        return int(result.get("statusCode") or 0)

    def test_refund_arm_is_retired_for_every_caller(self):
        body = {"phoneId": "1016149501586345", "referenceId": "WD-PAY-TEST0001",
                "configName": "WECAREDIGITAL", "amountPaise": 100}
        for role in ("Viewer", "Operator", "Admin"):
            self.assertEqual(self.call("POST", "/wa-business/payment-refund", role=role,
                                       body=body), 410, role)
        internal = self.api.handler({"httpMethod": "POST", "path": "/wa-business/payment-refund",
                                     "body": json.dumps(body)}, None)
        self.assertEqual(internal["statusCode"], 410)
        self.assertFalse(any("payments_refund" in path for _m, path in self.graph_calls))
        self.assertFalse(hasattr(self.api, "_payment_refund"))

    WRITES = [
        ("POST", "/wa-business/catalog-products",
         {"catalogId": "1457045652952851", "retailerId": "X", "name": "Item", "price": 10}, None),
        ("PUT", "/wa-business/catalog-products", {"productId": "123", "name": "Renamed"}, None),
        ("DELETE", "/wa-business/catalog-products", None, {"productId": "123"}),
        ("POST", "/wa-business/catalog-feed",
         {"catalogId": "1457045652952851", "url": "https://example.invalid/feed.csv"}, None),
        ("POST", "/wa-business/catalog-feed/fetch", {"feedId": "1", "url": "https://example.invalid/f"}, None),
        ("POST", "/wa-business/commerce-settings",
         {"phoneId": "1016149501586345", "is_cart_enabled": False}, None),
        ("POST", "/wa-business/assigned-users",
         {"wabaId": "2094615664435155", "user": "42", "tasks": ["MANAGE"]}, None),
        ("DELETE", "/wa-business/assigned-users", {"wabaId": "2094615664435155", "user": "42"},
         {"wabaId": "2094615664435155"}),
    ]

    def test_meta_mutations_refuse_viewer_and_operator(self):
        for method, path, body, query in self.WRITES:
            for role in ("Viewer", "Operator"):
                self.graph_calls.clear()
                status = self.call(method, path, role=role, body=body, query=query)
                self.assertEqual(status, 403, f"{role} {method} {path}")
                self.assertFalse([c for c in self.graph_calls if c[0] != "GET"],
                                 f"{role} {method} {path} reached Meta")

    def test_meta_mutations_still_work_for_admin(self):
        for method, path, body, query in self.WRITES:
            self.graph_calls.clear()
            status = self.call(method, path, role="Admin", body=body, query=query)
            self.assertNotEqual(status, 403, f"Admin {method} {path}")
            self.assertTrue([c for c in self.graph_calls if c[0] in ("POST", "DELETE")],
                            f"Admin {method} {path} did not reach its Meta write")

    def test_retired_catalog_flow_map_route_is_gone(self):
        # Nothing at payment time read the product -> Flow map, so its Workspace editor and API
        # were removed: the route answers 404 for every role and writes nothing.
        entry = {"retailerId": "WECARE.DIGITAL:v2:AAA:BBB", "flowIdWaba1": "993862443003108"}
        self.assertEqual(self.call("POST", "/wa-business/catalog-flow-map", role="Admin",
                                   body=entry), 404)
        self.assertEqual(self.call("GET", "/wa-business/catalog-flow-map", role="Admin"), 404)
        self.assertFalse(any(t.writes for t in self.tables.values()))

    def test_reads_keep_the_viewer_floor(self):
        reads = [
            ("/wa-business/catalog-products", {"catalogId": "1457045652952851"}),
            ("/wa-business/commerce-settings", {"phoneId": "1016149501586345"}),
            ("/wa-business/assigned-users", {"wabaId": "2094615664435155", "business": "1"}),
        ]
        for path, query in reads:
            self.assertNotEqual(self.call("GET", path, role="Viewer", query=query), 403, path)

    def test_internal_invokes_are_unaffected(self):
        event = {"httpMethod": "POST", "path": "/wa-business/commerce-settings",
                 "body": json.dumps({"phoneId": "1016149501586345", "is_catalog_visible": True})}
        self.assertEqual(self.api.handler(event, None)["statusCode"], 200)


class VaultRepublishTests(unittest.TestCase):
    DOC = "WD-DOC-TEST0001"
    SUB = "0b0e2c4e-1111-4222-8333-944455556666"
    PHONE = "919876543210"

    @classmethod
    def setUpClass(cls):
        cls.sf = _load("secure_files_under_test", SECURE_FILES_DIR / "handler.py")

    def setUp(self):
        self.files = FakeTable("fileId", self.sf.FILES_TABLE)
        self.docs = FakeTable("documentId", self.sf.DOCUMENTS_TABLE)
        tables = {self.sf.FILES_TABLE: self.files, self.sf.DOCUMENTS_TABLE: self.docs}
        self.source_key = self.sf.DROPDOCS_PREFIX + "manual/abc123"
        self.v1 = self.sf._vault_file_id_for_document(self.DOC, 1)
        cognito = SimpleNamespace(admin_get_user=lambda **_kw: {
            "Enabled": True,
            "UserAttributes": [{"Name": "sub", "Value": self.SUB},
                               {"Name": "phone_number", "Value": "+" + self.PHONE}]})
        self.s3_heads = []

        def head_object(**kw):
            self.s3_heads.append(kw["Key"])
            return {"ContentLength": 1024, "ContentType": "application/pdf"}

        s3 = SimpleNamespace(head_object=head_object, copy_object=lambda **_kw: {})
        for p in (patch.object(self.sf, "_table", lambda name: tables[name]),
                  patch.object(self.sf, "_ensure_customer_user", lambda phone, name: "cust-user"),
                  patch.object(self.sf, "_cognito_client", lambda: cognito),
                  patch.object(self.sf, "_s3_client", lambda: s3)):
            p.start()
            self.addCleanup(p.stop)

    def seed(self, *, reference_version: int, file_key: str):
        self.docs.rows[self.DOC] = {
            "documentId": self.DOC, "sourceType": "manual", "verificationStatus": "uploaded",
            "storageKey": self.source_key, "customerPhone": "+" + self.PHONE,
            "customerName": "Test Customer", "referenceVersion": reference_version,
            "vaultFileId": self.v1, "fileName": "wecare-digital-000001.pdf",
        }
        self.files.rows[self.v1] = {
            "fileId": self.v1, "sourceDocumentId": self.DOC, "sourceDocumentVersion": 1,
            "ownerCustomerId": self.SUB, "ownerPhone": self.PHONE, "s3Key": file_key,
            "status": "active", "displayName": "Old name",
            "vaultPaymentStatus": "PAID", "vaultEntitlementId": "vault-entitlement#x#y",
        }

    def publish(self, name="New name"):
        event = {"body": json.dumps({"documentId": self.DOC, "displayName": name}),
                 "_auth": {"username": "staff"}}
        response = self.sf._admin_publish_document(event, "https://wecare.digital")
        return response["statusCode"], json.loads(response["body"])

    def test_revalidated_reference_reuses_the_paid_row_for_the_same_bytes(self):
        self.seed(reference_version=2, file_key=self.source_key)
        status, body = self.publish()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["fileId"], self.v1)
        self.assertFalse(body["created"])
        # Filenames are system-owned: the staff-typed name is ignored, nothing reports a rename,
        # and the reused row now carries the generated Drop Docs name.
        self.assertNotIn("renamed", body)
        self.assertEqual(body["displayName"], "wecare-digital-000001.pdf")
        self.assertEqual(self.files.rows[self.v1]["displayName"], "wecare-digital-000001.pdf")
        self.assertEqual(list(self.files.rows), [self.v1])
        self.assertEqual(self.docs.rows[self.DOC]["vaultFileId"], self.v1)
        self.assertEqual(self.files.rows[self.v1]["vaultPaymentStatus"], "PAID")
        self.assertEqual(self.s3_heads, [])

    def test_changed_bytes_still_publish_a_new_version(self):
        self.seed(reference_version=2, file_key=self.sf.DROPDOCS_PREFIX + "manual/old-bytes")
        status, body = self.publish()
        self.assertEqual(status, 201, body)
        self.assertNotEqual(body["fileId"], self.v1)
        self.assertEqual(body["fileId"], self.sf._vault_file_id_for_document(self.DOC, 2))
        self.assertEqual(self.files.rows[body["fileId"]]["s3Key"], self.source_key)

    def test_a_revoked_linked_row_is_never_reused(self):
        self.seed(reference_version=2, file_key=self.source_key)
        self.files.rows[self.v1]["status"] = "revoked"
        status, body = self.publish()
        self.assertEqual(status, 201, body)
        self.assertNotEqual(body["fileId"], self.v1)


class PaidVaultAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pv = _load("paid_vault_under_test", BUSINESS_API_DIR / "flows" / "paid_vault.py")

    def run_outcome(self, outcome):
        event = {"referenceId": "WD-PAY-TEST0001", "paymentAttemptId": "attempt-1",
                 "orderId": "order-1"}
        with patch.object(self.pv, "_prepare_and_send", lambda e, c: {"outcome": outcome}):
            with self.assertLogs(self.pv.logger.name, level="INFO") as captured:
                self.pv.logger.info("sentinel")
                result = self.pv.prepare_and_send(event, None)
        self.assertEqual(result["outcome"], outcome)
        return [json.loads(m.split(":", 2)[2]) for m in captured.output
                if "paid_vault_not_delivered" in m]

    def test_no_entitlement_after_payment_alerts(self):
        lines = self.run_outcome("VAULT_ACCESS_UNAVAILABLE")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["alert"], "PAID_VAULT_UNFULFILLED")
        self.assertEqual(lines[0]["referenceId"], "WD-PAY-TEST0001")

    def test_unsent_access_link_alerts(self):
        for outcome in ("VERIFIED_RECIPIENT_UNAVAILABLE", "CONTACT_LINK_UNAVAILABLE",
                        "VAULT_NOTIFICATION_PENDING"):
            lines = self.run_outcome(outcome)
            self.assertEqual([line["alert"] for line in lines], ["VAULT_DELIVERY_UNSENT"], outcome)

    def test_delivered_outcomes_stay_quiet(self):
        for outcome in ("VAULT_READY", "VAULT_DOCUMENT_PENDING"):
            self.assertEqual(self.run_outcome(outcome), [], outcome)

    def test_real_path_with_no_grant_alerts(self):
        fake_db = FakeResource({})
        with patch.object(self.pv.vault_access, "grant_access", lambda *a, **k: None), \
                patch.object(self.pv.boto3, "resource", lambda *a, **k: fake_db):
            with self.assertLogs(self.pv.logger.name, level="ERROR") as captured:
                result = self.pv.prepare_and_send({"referenceId": "WD-PAY-TEST0002"}, None)
        self.assertEqual(result, {"outcome": "VAULT_ACCESS_UNAVAILABLE"})
        self.assertIn("PAID_VAULT_UNFULFILLED", "\n".join(captured.output))


class OrderDetailsLineTests(unittest.TestCase):
    def test_service_payment_lines_carry_no_synthetic_retailer_id(self):
        from lambda_utils.ecommerce import catalog_service_checkout, meta_catalog_sync
        quote = SimpleNamespace(collection_before_convenience_paise=9900,
                                convenience_fee_paise=248, convenience_gst_paise=45,
                                total_payable_paise=10193)
        row = {"kind": "VAULT", "productId": "d4cfc6e8-10b3-5c47-94c8-3c69f4c1e1a1",
               "variantId": "RVT6K4Q8"}
        details = catalog_service_checkout.payment_details(row, quote, "WD-PAY-TEST0001",
                                                           "WECAREDIGITAL", 1_800_000_000)
        lines = details["order"]["items"]
        self.assertEqual(lines[0]["retailer_id"],
                         meta_catalog_sync.retailer_id(row["productId"], row["variantId"]))
        self.assertEqual(lines[1]["name"], "Convenience fee")
        self.assertNotIn("retailer_id", lines[1])

    def test_no_runtime_mints_the_fee_retailer_id(self):
        for path in (FUNCTIONS / "ecommerce" / "checkout" / "handler.py",
                     SHARED / "lambda_utils" / "ecommerce" / "catalog_service_checkout.py"):
            self.assertNotIn("wecare-convenience-fee", path.read_text(encoding="utf-8"), path)



class PaymentOrderLifecycleTests(unittest.TestCase):
    def test_payment_order_targets_exclude_shipping_states(self):
        from lambda_utils.ecommerce import wa_order_status
        self.assertEqual(
            wa_order_status.PAYMENT_ORDER_TARGETS,
            frozenset({wa_order_status.PROCESSING, wa_order_status.COMPLETED}),
        )
        self.assertTrue(wa_order_status.payment_can_transition("pending", "processing"))
        self.assertTrue(wa_order_status.payment_can_transition("processing", "completed"))
        self.assertFalse(wa_order_status.payment_can_transition("pending", "completed"))
        self.assertFalse(wa_order_status.payment_can_transition("processing", "shipped"))
        self.assertFalse(wa_order_status.payment_can_transition("processing", "partially-shipped"))
        self.assertEqual(wa_order_status.payment_default_body("processing"), "Payment received.")
        self.assertEqual(wa_order_status.payment_default_body("completed"), "Payment complete.")

    def test_payment_order_module_has_no_interactive_status_builder(self):
        from lambda_utils.ecommerce import wa_order_status
        self.assertFalse(hasattr(wa_order_status, "build_interactive_payload"))

    def test_payment_runbook_keeps_brand_header_and_regular_manual_thumbnail(self):
        from lambda_utils import template_media
        runbook = (ROOT / "docs" / "operations" / "whatsapp-payment-collection-stack.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(template_media.PAYMENT_TEMPLATE_HEADER, runbook)
        self.assertIn("Square WECARE payment/catalog icon on regular rows", runbook)
        self.assertIn("fee rows remain image-free", runbook)
        self.assertIn("no synthetic retailer ID", runbook)
        self.assertIn("true catalog checkout", runbook)



class AlarmSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alarms = _load("payment_rail_alarms_under_test",
                           ROOT / "scripts" / "provision_payment_rail_alarms.py")

    def test_new_signals_are_present_and_consistent(self):
        by_alarm: dict = {}
        seen = set()
        for sig in self.alarms.SIGNALS:
            key = (sig["logGroup"], sig["filterName"])
            self.assertNotIn(key, seen, key)
            seen.add(key)
            by_alarm.setdefault(sig["alarmName"], []).append(sig)
        for name in ("wecare-payment-paid-state-incomplete", "wecare-vault-paid-delivery-incomplete",
                     "wecare-payment-readiness-refused", "wecare-catalog-sync-drift"):
            self.assertIn(name, by_alarm)
        for name, sigs in by_alarm.items():
            self.assertEqual(len({s["metricName"] for s in sigs}), 1, name)
            self.assertEqual(len({s["description"] for s in sigs}), 1, name)
            self.assertEqual(len({(s.get("period", 300), s.get("evaluationPeriods", 1))
                                  for s in sigs}), 1, name)
        drift = by_alarm["wecare-catalog-sync-drift"][0]
        self.assertEqual((drift["period"], drift["evaluationPeriods"]), (21600, 2))

    def test_alert_names_are_emitted_by_the_code(self):
        sources = {
            "PAID_VAULT_UNFULFILLED": BUSINESS_API_DIR / "flows" / "paid_vault.py",
            "VAULT_DELIVERY_UNSENT": BUSINESS_API_DIR / "flows" / "paid_vault.py",
            "VAULT_PAID_WINDOW_UNAVAILABLE": BUSINESS_API_DIR / "flows" / "paid_vault.py",
            "NEEDS_RECONCILIATION": SHARED / "lambda_utils" / "ecommerce" / "order_creation.py",
            "INVOICE_CREATE_FAILED": FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py",
            "RECEIPT_DELIVERY_EXHAUSTED": FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py",
            "PAID_BUT_NO_ORDER_RECORD": FUNCTIONS / "ecommerce" / "checkout" / "handler.py",
            "capture_needs_reconciliation": FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py",
            "wa_payment_readiness_refused": FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py",
            "checkout_not_ready": FUNCTIONS / "ecommerce" / "checkout" / "handler.py",
            "meta_catalog_sync_planned": FUNCTIONS / "ecommerce" / "meta-catalog-sync" / "handler.py",
        }
        patterns = "\n".join(s.get("pattern", "") for s in self.alarms.SIGNALS)
        for token, source in sources.items():
            if token in ("capture_needs_reconciliation",):
                continue  # emitted with alert NEEDS_RECONCILIATION, which the filter matches
            self.assertIn(token, patterns, token)
            self.assertIn(token, source.read_text(encoding="utf-8"), f"{token} not in {source}")


if __name__ == "__main__":
    unittest.main()
