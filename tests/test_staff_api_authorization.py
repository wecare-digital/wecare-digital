"""Authorization regression tests for the staff APIs closed on 2026-10-26.

Real handler code with a role-aware stand-in for `require_auth` and in-process fakes: no
network, no AWS account. Each write that used to sit at the Viewer floor is driven as Viewer
(refused, nothing written or sent) and as the role that now owns it (allowed).

* service-api: every write needs Operator; reads keep the Viewer floor; cancel needs Admin.
* whatsapp-template-management: every Meta-account write and test send needs Admin; template
  ids must be numeric, so no caller can point the system-user token at another Graph edge.
* ai-config-management: settings writes need Operator and only the Workspace settings rows are
  readable or writable; clear-logs needs Admin and has no body-flag side door.
* outbound-whatsapp: every customer message, reaction, typing indicator, block change and
  upload URL needs Operator; listing blocked users stays a Viewer read; payment stays Admin.
* waba-management CORS apply: no wildcard, exact origins only, only on its own route, audited.
* whatsapp-calling: terminate and config changes are audited; clear-logs refuses unaudited.
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

        def meta_request(url, method="GET", data=None, headers=None, timeout=None):
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

    def test_prompt_and_fallback_writes_accept_only_supported_languages(self):
        # The Workspace sends the language in the body as well as the path.
        for path, body in (("/ai/prompts/config", {"language": "config", "prompt": "x"}),
                           ("/ai/fallbacks/config", {"language": "config", "fallback": "x"})):
            self.assertEqual(self.call("PUT", path, "Operator", body), 400, path)
        self.assertEqual(self.config_rows(), {})
        self.assertEqual(self.call("PUT", "/ai/prompts/en", "Operator",
                                   {"language": "en", "prompt": "x"}), 200)
        self.assertIn("ai_prompt_en", self.config_rows())


class _RoleRecorder:
    """Stand-in for `require_auth` that records the role asked for and stops the request."""

    def __init__(self):
        self.roles: list = []

    def __call__(self, event, required_role=None):
        self.roles.append(required_role)
        return {"statusCode": 499, "body": "{}"}


class OutboundSendFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("outbound_floor_under_test",
                        FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py")

    def role_for(self, body):
        recorder = _RoleRecorder()
        with patch.object(self.api, "require_auth", recorder):
            result = self.api.handler(api_event("POST", "/whatsapp/send", role="Viewer", body=body),
                                      SimpleNamespace(aws_request_id="test"))
        self.assertEqual(_status(result), 499, body)
        return recorder.roles[-1]

    def test_customer_messages_need_operator(self):
        for body in ({"contactId": "c1", "content": "hello"},
                     {"contactId": "c1", "isTemplate": True, "templateName": "wecare_leave_review"},
                     {"isReaction": True, "reactionMessageId": "wamid.X", "reactionEmoji": "👍"},
                     {"isTypingIndicator": True, "messageId": "wamid.X"},
                     {"blockAction": "block", "blockUsers": ["919999900001"]},
                     {"action": "getUploadUrl", "mediaType": "image", "filename": "a.png"}):
            self.assertEqual(self.role_for(body), "Operator", body)

    def test_listing_blocked_users_keeps_the_viewer_floor(self):
        self.assertIsNone(self.role_for({"blockAction": "list"}))

    def test_payment_request_still_needs_admin(self):
        self.assertEqual(self.role_for({"isCheckoutTemplate": True}), "Admin")


class CorsApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("waba_management_cors_under_test",
                        FUNCTIONS / "messaging" / "waba-management" / "handler.py")

    def setUp(self):
        self.updates: list = []
        self.audits: list = []
        test = self

        class FakeApiGateway:
            def update_api(self, ApiId, CorsConfiguration):  # noqa: N803 - boto3 spelling
                test.updates.append((ApiId, CorsConfiguration["AllowOrigins"]))
                return {}

        for p in (patch.object(self.api, "require_auth", fake_require_auth),
                  patch.object(self.api, "apigw_client", FakeApiGateway()),
                  patch.object(self.api, "record_audit",
                               lambda **kw: self.audits.append(kw) or "log-1")):
            p.start()
            self.addCleanup(p.stop)

    def call(self, path, body):
        return self.api.handler(api_event("POST", path, role="Admin", body=body),
                                SimpleNamespace(aws_request_id="test"))

    def test_wildcards_and_inexact_origins_are_refused(self):
        for body in ({"action": "cors-apply", "allowAll": True},
                     {"action": "cors-apply", "origins": ["*"]},
                     {"action": "cors-apply", "origins": ["https://partner.example/app"]},
                     {"action": "cors-apply", "origins": ["http://partner.example"]},
                     {"action": "cors-apply", "origins": ["https://*.example"]}):
            self.assertEqual(_status(self.call("/waba", body)), 400, body)
        self.assertEqual(self.updates, [])
        self.assertEqual(self.audits, [])

    def test_exact_origins_apply_with_core_origins_and_an_audit_record(self):
        result = self.call("/waba", {"action": "cors-apply", "origins": ["https://partner.example"]})
        self.assertEqual(_status(result), 200)
        self.assertTrue(self.updates)
        origins = self.updates[0][1]
        self.assertIn("https://partner.example", origins)
        self.assertIn("https://wecare.digital", origins)
        self.assertNotIn("*", origins)
        self.assertEqual([a["action"] for a in self.audits], ["cors.apply"])
        self.assertEqual(self.audits[0]["actor"], "staff-admin")

    def test_the_action_flag_on_another_route_changes_nothing(self):
        self.call("/waba/media", {"action": "cors-apply", "origins": ["https://partner.example"]})
        self.assertEqual(self.updates, [])


class CallingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("calling_audit_under_test",
                        FUNCTIONS / "messaging" / "whatsapp-calling" / "handler.py")

    def event(self, body=None):
        return {"_auth": {"username": "staff-admin", "groups": ["Admin"]},
                "body": json.dumps(body or {})}

    def test_clear_logs_refuses_when_the_audit_record_cannot_be_written(self):
        deleted: list = []

        class FakeTable:
            def scan(self, **_kw):
                return {"Items": [{"id": "call-1"}]}

            def batch_writer(self):
                class Writer:
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        return False

                    def delete_item(self, Key):  # noqa: N803 - boto3 spelling
                        deleted.append(Key)
                return Writer()

        fake = SimpleNamespace(Table=lambda _name: FakeTable())
        with patch.object(self.api, "dynamodb", fake), \
                patch.object(self.api, "record_audit", lambda **_kw: None):
            refused = self.api._clear_logs(self.event(), "req-test")
        self.assertEqual(_status(refused), 503)
        self.assertEqual(deleted, [])
        audits: list = []
        with patch.object(self.api, "dynamodb", fake), \
                patch.object(self.api, "record_audit", lambda **kw: audits.append(kw) or "log-1"):
            done = self.api._clear_logs(self.event(), "req-test")
        self.assertEqual(_status(done), 200)
        self.assertEqual(deleted, [{"id": "call-1"}])
        self.assertEqual((audits[0]["action"], audits[0]["actor"]), ("calling.clear_logs", "staff-admin"))

    def test_terminate_and_config_changes_are_audited(self):
        audits: list = []
        with patch.object(self.api, "_meta_api_call", lambda *_a, **_k: {"success": True}), \
                patch.object(self.api, "_update_call_status", lambda *_a, **_k: None), \
                patch.object(self.api, "record_audit", lambda **kw: audits.append(kw) or "log-1"):
            self.api._terminate_call(self.event({"callId": "wacid.X", "phoneNumberId": "1016149501586345"}),
                                     "req-test")
        with patch.object(self.api, "dynamodb", FakeResource({})), \
                patch.object(self.api, "record_audit", lambda **kw: audits.append(kw) or "log-1"):
            self.api._update_config(self.event({"autoPickup": False}), "req-test")
        self.assertEqual([a["action"] for a in audits], ["calling.terminate", "calling.config_update"])
        self.assertEqual(audits[1]["details"], {"autoPickup": False})


if __name__ == "__main__":
    unittest.main()
