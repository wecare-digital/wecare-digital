"""Exact-file Vault contract: no 100-row scan before authenticated download.

These checks extract the production functions from source and exercise their
authorization/privacy logic using in-memory table fakes. No AWS API calls,
WhatsApp messages, payments or live customer documents.
"""
import ast
import json
from pathlib import Path
import re
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "amplify/functions/core/secure-files/handler.py"
FRONTEND = ROOT / "src/components/get/GetPage.tsx"
CLIENT = ROOT / "src/api/client.ts"
ACTIVITY = ROOT / "src/components/workspace/pay/PaymentsActivity.tsx"

PHONE = "919000000001"
OWNER = "owned-customer-subject"
IDENTITY = {"phone": PHONE, "subject": OWNER}


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.gets = []
        self.query_count = 0

    def get_item(self, **kwargs):
        self.gets.append(kwargs)
        return {"Item": self.rows.get(kwargs["Key"]["fileId"], {})}

    def query(self, **kwargs):
        self.query_count += 1
        raise AssertionError("exact-file access must not Query owner-created-index")


def runtime_for(rows):
    source = BACKEND.read_text(encoding="utf-8")
    ast_root = ast.parse(source)
    names = {"_customer_file_view", "_customer_exact_file", "_owned_active_file"}
    functions = [node for node in ast_root.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in names]
    if len(functions) != 3:
        raise AssertionError("Missing production exact-file functions")
    table = FakeTable(rows)
    def cors_response(code, body, origin):
        return {"statusCode": code, "body": json.dumps(body),
                "headers": {"Access-Control-Allow-Origin": origin}}
    def no_store(response):
        response["headers"]["Cache-Control"] = "no-store"
        return response
    env = {
        "Dict": dict, "Any": object, "Optional": __import__("typing").Optional,
        "re": re, "time": time,
        "_table": lambda _: table, "FILES_TABLE": "TEST",
        "_no_store": no_store, "cors_response": cors_response,
        "_active_entitlement": lambda grant_id, file_id, identity: None,
        "_paid_marks": lambda file: file.get("vaultPaymentStatus") == "PAID",
        "_entitlement_for_file": lambda subject, file_id: None,
        "_public_file": lambda file, **kw: {
            "fileId": file["fileId"], "status": file["status"],
            "displayName": file.get("displayName", "Document"),
        },
    }
    code = compile(ast.Module(body=functions, type_ignores=[]),
                   str(BACKEND), "exec")
    exec(code, env)
    return env, table


def row(file_id, *, phone=PHONE, owner=OWNER, active=True):
    return {"fileId": file_id, "ownerPhone": phone,
            "ownerCustomerId": owner,
            "status": "active" if active else "revoked"}


class ExactFileTests(unittest.TestCase):
    def test_oldest_file_is_reachable_by_its_unique_id(self):
        # No index traversal occurs, regardless of number of historical files.
        item = row("file-older-than-100")
        env, table = runtime_for({item["fileId"]: item})
        response = env["_customer_exact_file"](item["fileId"], IDENTITY, "*")
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["files"][0]["fileId"],
                         item["fileId"])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")
        self.assertEqual(table.query_count, 0)
        self.assertEqual(table.gets[0]["ConsistentRead"], True)

    def test_unauthorised_revoked_and_missing_files_are_identical(self):
        cases = [
            ("other", row("other", owner="different-customer")),
            ("other", row("other", phone="919999999999")),
            ("other", row("other", active=False)),
            ("missing", None),
            ("bad*id", None),
        ]
        bodies = set()
        for file_id, item in cases:
            env, _ = runtime_for({file_id: item} if item else {})
            res = env["_customer_exact_file"](file_id, IDENTITY, "*")
            self.assertEqual(res["statusCode"], 404)
            self.assertEqual(res["headers"]["Cache-Control"], "no-store")
            bodies.add(res["body"])
        self.assertEqual(len(bodies), 1)

    def test_invalid_type_is_refused_without_server_error(self):
        env, _ = runtime_for({})
        for value in (None, 12, {}, [], ""):
            self.assertEqual(env["_customer_exact_file"](value, IDENTITY, "*")
                             ["statusCode"], 404)

    def test_paid_state_uses_durable_entitlement_fallback(self):
        item = {**row("paid"), "vaultPaymentStatus": "PAID"}
        env, _ = runtime_for({"paid": item})
        env["_entitlement_for_file"] = lambda subject, file_id: {
            "grantId": "paid-grant", "ownerPhone": PHONE,
        }
        res = env["_customer_exact_file"]("paid", IDENTITY, "*")
        self.assertEqual(json.loads(res["body"])["files"][0]
                         ["paidEntitlementId"], "paid-grant")

    def test_client_and_page_never_use_capped_list_for_direct_link(self):
        client = CLIENT.read_text(encoding="utf-8")
        page = FRONTEND.read_text(encoding="utf-8")
        backend = BACKEND.read_text(encoding="utf-8")
        self.assertIn("export async function getMySecureFile", client)
        self.assertIn("/secure-files/mine?file=", client)
        self.assertEqual(page.count("api.getMySecureFile( targetFileId )"), 2)
        self.assertNotIn("api.listMySecureFiles()", page)
        self.assertIn('if tail == ["mine"] and method == "GET":', backend)
        self.assertIn('return _customer_exact_file(query.get("file"), identity, origin)', backend)

    def test_refund_activity_is_not_reported_as_a_new_capture(self):
        src = ACTIVITY.read_text(encoding="utf-8")
        refund = src.index("if ( payment === 'refunded'")
        captured = src.index("else if ( [ 'captured', 'paid' ]")
        self.assertLess(refund, captured)
        self.assertIn("epochMs( invoice.refundAt ) || epochMs( invoice.paidAt )", src)
        self.assertIn("This is not a complete event history.", src)


if __name__ == "__main__":
    unittest.main()
