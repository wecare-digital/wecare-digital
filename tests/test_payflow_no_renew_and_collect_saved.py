"""Regression: never renew a paid Vault file; Collect Create can send saved invoices.

Run: python3 -m unittest discover -s tests -p 'test_payflow_no_renew_and_collect_saved.py' -v
No AWS, Meta, S3, WhatsApp customer sends, or payment attempts are made.
"""
import ast
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
import time
import typing
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "amplify/functions/core/secure-files/handler.py"
STORE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_request_store.py"
CATALOG = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py"
VAULT_UI = ROOT / "src/components/workspace/service/SecureFiles.tsx"
VAULT_PREVIEW = ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx"
COLLECT_UI = ROOT / "src/components/workspace/pay/PayFlow.tsx"
PAYMENTS = ROOT / "src/pages/workspace/payments/index.tsx"

class Refused(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def extract_function(path, name, env):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(functions) != 1:
        raise AssertionError("Expected one production function " + name)
    scope = {"Dict": typing.Dict, "Any": typing.Any,
             "Optional": typing.Optional, "Tuple": typing.Tuple,
             "Callable": typing.Callable}
    scope.update(env)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), scope)
    return scope[name]

def response(code, body, origin):
    return {"statusCode": code, "body": json.dumps(body)}
def no_store(resp):
    return {**resp, "headers": {"Cache-Control": "no-store"}}
def paid_marks(item):
    return bool(item.get("vaultPaymentStatus") == "PAID"
                or item.get("vaultEntitlementId") or item.get("vaultAccessGrantId"))
def catalog_stub():
    return SimpleNamespace(VAULT_ITEM_DESCRIPTION_DEFAULT="Vault Access - Secure document download (24 hours)",
                           valid_vault_item_description=lambda _: True)

class NoRenewTests(unittest.TestCase):
    def test_native_payment_guards_expired_before_s3_or_lambda(self):
        invoked = []
        fn = extract_function(SECURE, "_start_native_vault_payment", {
            "catalog_service_checkout": catalog_stub(),
            "_paid_marks": paid_marks, "_no_store": no_store,
            "cors_response": response, "_vault_file_storage_ready": lambda _: invoked.append("s3"),
            "_lambda_client": lambda: invoked.append("lambda"),
        })
        for state in ("EXPIRED", "READY", "OPEN", "PAID_UNVERIFIED"):
            with self.subTest(state=state):
                res = fn({"fileId": "file1", "vaultPaymentStatus": "PAID"}, state,
                         "*", requested_by="staff")
                self.assertEqual(res["statusCode"], 409)
                self.assertEqual(json.loads(res["body"])["error"], "VAULT_ALREADY_PAID")
        self.assertEqual(invoked, [])

    def test_no_new_native_payment_from_inconsistent_paid_pointer(self):
        fn = extract_function(SECURE, "_start_native_vault_payment", {
            "catalog_service_checkout": catalog_stub(),
            "_paid_marks": paid_marks, "_no_store": no_store,
            "cors_response": response, "_vault_file_storage_ready": lambda _: True,
            "_lambda_client": lambda: self.fail("must not invoke payment"),
        })
        res = fn({"fileId": "x", "vaultEntitlementId": "grant"}, "UNPAID",
                 "*", requested_by="staff")
        self.assertEqual(res["statusCode"], 409)

    def test_new_unpaid_file_still_uses_the_existing_native_sender(self):
        calls = []
        class Lambda:
            def invoke(self, **kwargs):
                calls.append(kwargs)
                return {"Payload": io.BytesIO(b'{"outcome":"PAYMENT_REQUEST_SENT"}')}
        class Table:
            def update_item(self, **kwargs):
                calls.append({"audit": kwargs})
        fn = extract_function(SECURE, "_start_native_vault_payment", {
            "catalog_service_checkout": catalog_stub(),
            "_paid_marks": paid_marks, "_no_store": no_store,
            "cors_response": response, "_vault_file_storage_ready": lambda _: True,
            "_lambda_client": lambda: Lambda(), "BUSINESS_API_FUNCTION": "test-business-api",
            "_table": lambda _: Table(), "FILES_TABLE": "test", "json": json, "time": time,
            "logger": SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
            "_PAYMENT_REQUEST_REPLIES": {"PAYMENT_REQUEST_SENT": (200, "Accepted")},
        })
        res = fn({"fileId": "unpaid", "ownerPhone": "910000000000",
                  "ownerCustomerId": "customer"}, "UNPAID", "*", requested_by="staff")
        self.assertEqual(res["statusCode"], 200)
        sends = [r for r in calls if "FunctionName" in r]
        self.assertEqual(len(sends), 1)
        request = json.loads(sends[0]["Payload"])
        self.assertEqual(request["action"], "sendPayment")
        self.assertEqual(request["fileId"], "unpaid")
        self.assertEqual(res["headers"] if "headers" in res else {}, {})

    def test_customer_expired_file_never_calls_sender(self):
        fn = extract_function(SECURE, "_customer_request_payment", {
            "_owned_active_file": lambda *_: {"fileId": "x", "vaultPaymentStatus": "PAID"},
            "_file_access_state": lambda *_: "EXPIRED", "_paid_marks": paid_marks,
            "cors_response": response, "_no_store": no_store, "time": time,
            "_start_native_vault_payment": lambda *_a, **_k: self.fail("no renewal send"),
        })
        res = fn("x", {}, {}, "*")
        self.assertEqual(res["statusCode"], 409)

    def test_staff_expired_file_never_calls_sender(self):
        fn = extract_function(SECURE, "_admin_request_payment", {
            "_owned_file_for_admin": lambda *_: ({"fileId": "x", "vaultPaymentStatus": "PAID"}, None),
            "_file_access_state": lambda *_: "EXPIRED", "_paid_marks": paid_marks,
            "catalog_service_checkout": catalog_stub(), "cors_response": response,
            "_no_store": no_store, "time": time, "json": json,
            "_start_native_vault_payment": lambda *_a, **_k: self.fail("no renewal send"),
        })
        res = fn("x", {"body": "{}"}, "*")
        self.assertEqual(res["statusCode"], 409)

    def test_intent_store_blocks_second_purchase_before_new_intent(self):
        env = {
            "customer_auth": SimpleNamespace(CustomerIdentity=object,
                CustomerNotAuthorized=Refused),
            "ServiceRejected": Refused, "new_uuid7": lambda: "uuid7",
            "NOT_OFFERED_KINDS": set(), "SERVICE_VARIANT_BY_KIND": {"VAULT": "v49"},
            "SERVICE_UNKNOWN_CHOICE": "INVALID", "SUBMIT_REQUEST": "SUBMIT_REQUEST",
            "VAULT": "VAULT", "DROP_DOCS": "DROP_DOCS",
        }
        fn = extract_function(STORE, "request_intent", env)
        identity = SimpleNamespace(customer_id="owner")
        for evidence in ({"vaultPaymentStatus": "PAID"},
                         {"vaultEntitlementId": "grant"},
                         {"vaultAccessGrantId": "legacy-grant"}):
            with self.subTest(evidence=evidence):
                row = {"ownerCustomerId": "owner", "status": "active",
                       "fileId": "x", **evidence}
                with self.assertRaises(Refused) as err:
                    fn(None, identity, "VAULT", vault_file=row)
                self.assertEqual(err.exception.code, "VAULT_ALREADY_PAID")

    def test_schedule_creation_and_dispatch_block_expired(self):
        src = SECURE.read_text(encoding="utf-8")
        self.assertIn('state != "UNPAID" or _paid_marks(item)', src)
        self.assertIn('state != "UNPAID" or _paid_marks(file_row)', src)
        self.assertNotIn('state not in ("UNPAID", "EXPIRED")', src)

    def test_historical_entitlement_capture_is_not_deleted(self):
        src = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/vault_access.py").read_text(encoding="utf-8")
        self.assertIn("def grant_access(", src)
        self.assertIn("if renewal:", src)  # Valid legacy captured payments still fulfil.
        self.assertIn("paidWindowCount", src)

    def test_wa_payment_preparation_refuses_paid_file(self):
        src = CATALOG.read_text(encoding="utf-8")
        self.assertIn("if state != 'UNPAID' or file.get('vaultPaymentStatus') == 'PAID'", src)
        self.assertNotIn("if state not in ('UNPAID', 'EXPIRED'):", src)
        self.assertIn("if state in ('OPEN', 'READY'):", src)
        self.assertIn("'renewal': False", src)

    def test_no_staff_renewal_offer_or_customer_renewal_response(self):
        ui = VAULT_UI.read_text(encoding="utf-8")
        backend = SECURE.read_text(encoding="utf-8")
        preview = VAULT_PREVIEW.read_text(encoding="utf-8")
        self.assertNotIn("Review renewal payment", ui)
        self.assertNotIn("'UNPAID', 'EXPIRED'", ui)
        self.assertIn("Renewal is not offered", ui)
        self.assertIn('"renewable": False', backend)
        self.assertIn("access ends at expiry, no renewal", preview)

    def test_collect_saved_invoice_has_an_explicit_create_path(self):
        page = PAYMENTS.read_text(encoding="utf-8")
        ui = COLLECT_UI.read_text(encoding="utf-8")
        self.assertIn('view=collect&tab=create&invoices=saved', page)
        self.assertIn('mode="invoices" allowSendInInvoices', page)
        self.assertIn("'pay_flow' ) : invoices", ui)
        self.assertIn('mode === \'invoices\' && ( !allowSendInInvoices', ui)
        self.assertIn("const approved = await confirm( {", ui)
        self.assertIn("invoices: 'saved', invoice: redemption.invoiceId", ui)
        self.assertIn('mode !== \'invoices\' || ( allowSendInInvoices', ui)


if __name__ == "__main__":
    unittest.main()
