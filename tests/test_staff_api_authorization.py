"""Authorization regression tests for the staff APIs closed on 2026-10-26.

Real handler code with a role-aware stand-in for `require_auth` and in-process fakes: no
network, no AWS account. Each write that used to sit at the Viewer floor is driven as Viewer
(refused, nothing written or sent) and as the role that now owns it (allowed).

* service-api: every write needs Operator; reads keep the Viewer floor; cancel needs Admin.
* whatsapp-template-management: every Meta-account write and test send needs Admin; template
  ids must be numeric, so no caller can point the system-user token at another Graph edge.
* ai-config-management: settings writes need Operator and only the Workspace settings rows are
  readable or writable; clear-logs needs Admin and has no body-flag side door.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_commerce_audit_hardening import (  # noqa: E402 - shared in-process fakes
    FUNCTIONS, FakeResource, api_event, fake_require_auth, _load)

import lambda_utils.middleware as middleware  # noqa: E402 - path set by the shared module


def _status(result) -> int:
    return int(result.get("statusCode") or 0)


class ServiceApiWriteFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("service_api_authz_under_test", FUNCTIONS / "core" / "service-api" / "handler.py")

    def setUp(self):
        self.tables: dict = {}
        for p in (patch.object(middleware, "require_auth", fake_require_auth),
                  patch.object(self.api, "dynamodb", FakeResource(self.tables), create=True)):
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, role, body=None):
        return _status(self.api.handler(api_event(method, path, role=role, body=body),
                                        SimpleNamespace(aws_request_id="test")))

    def writes(self) -> list:
        return [w for table in self.tables.values() for w in table.writes]

    WRITES = [
        ("POST", "/service/orders", {"customerName": "Test"}),
        ("PATCH", "/service/orders/ord-1", {"status": "processing"}),
        ("POST", "/service/faq", {"question": "Q", "answer": "A"}),
        ("PUT", "/service/faq/faq-1", {"answer": "B"}),
        ("DELETE", "/service/faq/faq-1", None),
        ("POST", "/service/documents", {"title": "Doc"}),
        ("POST", "/service/appointments", {"name": "Test"}),
        ("POST", "/service/reviews", {"rating": 5}),
        ("POST", "/service/drafts", {"flowCode": "X"}),
        ("DELETE", "/service/drafts/X", None),
    ]

    def test_viewer_cannot_write(self):
        for method, path, body in self.WRITES:
            self.assertEqual(self.call(method, path, "Viewer", body), 403, (method, path))
        self.assertEqual(self.writes(), [])

    def test_operator_passes_the_write_gate(self):
        for method, path, body in self.WRITES:
            self.assertNotEqual(self.call(method, path, "Operator", body), 403, (method, path))

    def test_reads_keep_the_viewer_floor(self):
        for path in ("/service/orders", "/service/faq", "/service/reviews"):
            self.assertNotEqual(self.call("GET", path, "Viewer"), 403, path)

    def test_cancel_still_needs_admin(self):
        self.assertEqual(self.call("PATCH", "/service/orders/ord-1", "Operator",
                                   {"action": "cancel"}), 403)


class TemplateManagementWriteFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("template_mgmt_authz_under_test",
                        FUNCTIONS / "messaging" / "whatsapp-template-management" / "handler.py")

    def setUp(self):
        self.meta_calls: list = []

        def meta_request(url, method="GET", data=None, headers=None):
            self.meta_calls.append((method, url))
            return {"id": "1754227779211208", "success": True, "data": []}

        for p in (patch.object(self.api, "require_auth", fake_require_auth),
                  patch.object(self.api, "_meta_request", meta_request),
                  patch.object(self.api, "_resolve_meta_waba_id", lambda _w: "2094615664435155")):
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, role, body=None, query=None):
        return _status(self.api.handler(api_event(method, path, role=role, body=body, query=query),
                                        SimpleNamespace(aws_request_id="test")))

    DEFINITION = {"templateDefinition": {"components": []}}

    def test_viewer_and_operator_cannot_write_to_the_meta_account(self):
        writes = [
            ("POST", "/whatsapp/templates", {"name": "x", "language": "en_US", "category": "UTILITY"}),
            ("PUT", "/whatsapp/templates/1754227779211208", self.DEFINITION),
            ("DELETE", "/whatsapp/templates/x", None),
            ("POST", "/whatsapp/templates/media", {"fileName": "a.png"}),
            ("POST", "/whatsapp/templates/carousel", {"name": "x"}),
            ("POST", "/whatsapp/templates/1754227779211208/send-test", {"to": "919999900001"}),
        ]
        for role in ("Viewer", "Operator"):
            for method, path, body in writes:
                self.assertEqual(self.call(method, path, role, body,
                                           {"templateName": "x"} if method == "DELETE" else None),
                                 403, (role, method, path))
        self.assertEqual(self.meta_calls, [])

    def test_reads_validation_and_refresh_keep_the_staff_floor(self):
        self.assertEqual(self.call("GET", "/whatsapp/templates", "Viewer"), 200)
        self.assertEqual(self.call("GET", "/whatsapp/templates/1754227779211208", "Viewer"), 200)
        self.assertEqual(self.call("POST", "/whatsapp/templates/1754227779211208/refresh", "Viewer"), 200)
        self.assertNotEqual(self.call("POST", "/whatsapp/templates/validate", "Viewer", {}), 403)

    def test_admin_update_accepts_only_a_numeric_template_id(self):
        for body in ({**self.DEFINITION, "metaTemplateId": "2094615664435155/subscribed_apps"},
                     {**self.DEFINITION, "metaTemplateId": "me"}):
            self.assertEqual(self.call("PUT", "/whatsapp/templates", "Admin", body), 400, body)
        self.assertEqual(self.call("GET", "/whatsapp/templates/me", "Viewer"), 400)
        self.assertEqual(self.meta_calls, [])
        self.assertEqual(self.call("PUT", "/whatsapp/templates/1754227779211208", "Admin",
                                   self.DEFINITION), 200)
        self.assertEqual(self.meta_calls[-1][0], "POST")
        self.assertTrue(self.meta_calls[-1][1].endswith("/1754227779211208"))

    def test_admin_write_is_audit_logged(self):
        with self.assertLogs(self.api.logger, level="INFO") as logs:
            self.call("PUT", "/whatsapp/templates/1754227779211208", "Admin", self.DEFINITION)
        audit = [json.loads(line.split(":", 2)[-1]) for line in logs.output
                 if "template_write_audit" in line]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["method"], "PUT")
        self.assertNotIn("staff-admin", json.dumps(audit[0]))


class AiConfigWriteFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("ai_config_authz_under_test",
                        FUNCTIONS / "ai" / "ai-config-management" / "handler.py")

    def setUp(self):
        self.tables: dict = {}
        self.cleared: list = []
        self.botflow: list = []
        for p in (patch.object(middleware, "require_auth", fake_require_auth),
                  patch.object(self.api, "dynamodb", FakeResource(self.tables)),
                  patch.object(self.api, "_clear_ai_logs",
                               lambda rid: self.cleared.append(rid) or {"statusCode": 200, "body": "{}"}),
                  patch.object(self.api, "_update_botflow_config",
                               lambda body, rid: self.botflow.append("put") or {"statusCode": 200, "body": "{}"}),
                  patch.object(self.api, "_delete_botflow_configs",
                               lambda rid: self.botflow.append("delete") or {"statusCode": 200, "body": "{}"})):
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, role, body=None, query=None):
        return _status(self.api.handler(api_event(method, path, role=role, body=body, query=query),
                                        SimpleNamespace(aws_request_id="test")))

    def config_rows(self) -> dict:
        return self.tables.get(self.api.SYSTEM_CONFIG_TABLE).rows \
            if self.api.SYSTEM_CONFIG_TABLE in self.tables else {}

    def test_settings_writes_need_operator(self):
        for key in ("ai_config", "welcome_message", "wa_auto_response", "flow_triggers_config"):
            body = {"key": key, "config": {"enabled": True}}
            self.assertEqual(self.call("PUT", "/ai/config", "Viewer", body), 403, key)
            self.assertNotIn(key, self.config_rows())
            self.assertEqual(self.call("PUT", "/ai/config", "Operator", body), 200, key)
        for path in ("/ai/prompts/en", "/ai/fallbacks/en"):
            self.assertEqual(self.call("PUT", path, "Viewer", {"prompt": "x", "fallback": "x"}), 403, path)

    def test_only_settings_rows_are_reachable(self):
        for key in ("catalog_flow_map", "cleanup_confirm_test", "whatsapp_events_history"):
            self.assertEqual(self.call("PUT", "/ai/config", "Admin", {"key": key, "config": {"x": 1}}),
                             400, key)
            self.assertEqual(self.call("GET", "/ai/config", "Admin", query={"key": key}), 400, key)
        self.assertNotIn("catalog_flow_map", self.config_rows())
        self.assertNotEqual(self.call("GET", "/ai/config", "Viewer",
                                      query={"key": "welcome_message"}), 403)

    def test_clear_logs_needs_admin_and_has_no_body_flag(self):
        for method, path in (("PUT", "/ai/config"), ("POST", "/ai/test"), ("PUT", "/ai/prompts/en")):
            self.call(method, path, "Operator", {"_action": "clear-logs", "message": "hi"})
        self.assertEqual(self.cleared, [])
        self.assertEqual(self.call("POST", "/ai/clear-logs", "Operator"), 403)
        self.assertEqual(self.call("DELETE", "/ai/clear-logs", "Operator"), 403)
        self.assertEqual(self.cleared, [])
        self.assertEqual(self.call("DELETE", "/ai/clear-logs", "Admin"), 200)
        self.assertEqual(len(self.cleared), 1)

    def test_bot_flow_writes(self):
        self.assertEqual(self.call("PUT", "/ai/botflow", "Viewer", {"flows": []}), 403)
        self.assertEqual(self.call("DELETE", "/ai/botflow", "Operator"), 403)
        self.assertEqual(self.botflow, [])
        self.assertEqual(self.call("PUT", "/ai/botflow", "Operator", {"flows": []}), 200)
        self.assertEqual(self.call("DELETE", "/ai/botflow", "Admin"), 200)
        self.assertEqual(self.botflow, ["put", "delete"])

    def test_internal_agent_config_write_needs_admin(self):
        self.assertEqual(self.call("PUT", "/ai/internal/config", "Operator", {"enabled": True}), 403)


if __name__ == "__main__":
    unittest.main()
