"""Offline fail-closed checks for provider FLOW-button release audit; no AWS or Meta traffic."""
import unittest
from unittest.mock import patch

from scripts import check_whatsapp_templates_live as audit
from lambda_utils import canonical_flows, whatsapp_templates


def definition(name, capability, *, target=None, action="DATA_EXCHANGE", extra_buttons=None):
    spec = whatsapp_templates.by_name(name)
    assert spec is not None
    if target is None:
        target = canonical_flows.canonical_flow_id(capability)
    sections = [
        {"type": "HEADER", "format": "IMAGE"},
        {"type": "BODY", "text": "✅ Your service is ready. Tap below to continue."},
        {"type": "FOOTER", "text": "WECARE.DIGITAL"},
        {"type": "BUTTONS", "buttons": [
            {"type": "FLOW", "text": "Drop Docs" if name == "_dropdoc_flow" else "Continue",
             "flow_id": target, "flow_action": action},
            *(extra_buttons or []),
        ]},
    ]
    return {"name": name, "language": spec.language, "category": spec.category,
            "status": "APPROVED", "id": whatsapp_templates.APPROVED_TEMPLATE_IDS[name],
            "components": sections}


class LiveFlowTemplateAuditTest(unittest.TestCase):
    def setUp(self):
        self.drop = whatsapp_templates.DROP_DOCS_FLOW
        self.definition = definition(self.drop.name, "drop_docs")

    def test_registered_flow_templates_cover_all_live_button_roles(self):
        self.assertEqual(len(audit.FLOW_TARGETS), 9)
        self.assertEqual(audit.FLOW_TARGETS[self.drop.name], "drop_docs")
        for name, capability in audit.FLOW_TARGETS.items():
            self.assertTrue(canonical_flows.published_flow(capability), name)
            self.assertIsNotNone(whatsapp_templates.by_name(name))

    def test_approved_drop_docs_canonical_button_passes(self):
        self.assertEqual(audit.flow_binding_issues(self.drop, [self.definition]), [])

    def test_wrong_button_id_refused_even_when_template_approved(self):
        wrong = definition(self.drop.name, "drop_docs", target="39581903361452880")
        issues = audit.flow_binding_issues(self.drop, [wrong])
        self.assertTrue(any("FLOW target" in issue for issue in issues))

    def test_missing_duplicate_and_wrong_action_are_refused(self):
        self.assertTrue(audit.flow_binding_issues(self.drop, []))
        self.assertTrue(audit.flow_binding_issues(self.drop, [self.definition, self.definition]))
        bad = definition(self.drop.name, "drop_docs", action="NAVIGATE")
        self.assertIn("FLOW action must be DATA_EXCHANGE",
                      audit.flow_binding_issues(self.drop, [bad]))
        missing = definition(self.drop.name, "drop_docs")
        missing["components"][-1]["buttons"] = []
        self.assertTrue(audit.flow_binding_issues(self.drop, [missing]))

    def test_unapproved_replaced_or_modified_drop_docs_never_passes(self):
        bad = definition(self.drop.name, "drop_docs")
        bad["id"] = "00000000000000000"
        bad["status"] = "PENDING"
        bad["components"][0]["format"] = "TEXT"
        bad["components"][1]["text"] = "New unreviewed wording."
        bad["components"][2]["text"] = "Another brand"
        issues = audit.flow_binding_issues(self.drop, [bad])
        self.assertGreaterEqual(len(issues), 5)

    def test_other_canonical_flow_button_target(self):
        template = whatsapp_templates.TRACK_SHIPPING_FLOW
        row = definition(template.name, "shipments")
        self.assertFalse(audit.flow_binding_issues(template, [row]))

    def test_live_reads_are_get_only(self):
        calls = []
        class FakePayload:
            def read(self):
                return b'{"statusCode":200,"body":"{\\"templates\\":[]}"}'
        class FakeClient:
            def invoke(self, **kwargs):
                calls.append(kwargs)
                return {"Payload": FakePayload()}
        class FakeBoto:
            @staticmethod
            def client(*args, **kwargs):
                self_dummy = kwargs
                return FakeClient()
        with patch.dict("sys.modules", {"boto3": FakeBoto}):
            result = audit._invoke_get("read-lambda:live", "/whatsapp/templates",
                                       {"wabaId": audit.WABA_ID})
        self.assertEqual(result, {"templates": []})
        self.assertEqual(len(calls), 1)
        import json
        event = json.loads(calls[0]["Payload"])
        self.assertEqual(event["httpMethod"], "GET")
        self.assertEqual(calls[0]["InvocationType"], "RequestResponse")


if __name__ == "__main__":
    unittest.main()
