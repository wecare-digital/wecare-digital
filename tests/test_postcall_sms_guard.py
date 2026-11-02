"""No-send regression tests for guarded WhatsApp Calling/Plivo SMS follow-ups.

These tests use AST-isolated helpers. They require no AWS credentials, phone
numbers, SMS sends, customer data, or external imports from Lambda handlers.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLIVO = "amplify/functions/messaging/plivo-answer/handler.py"
CALLING = "amplify/functions/messaging/whatsapp-calling/handler.py"


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def isolated_function(path, name, **bindings):
    tree = ast.parse(source(path), filename=path)
    definition = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    scope = dict(bindings)
    exec(compile(ast.Module(body=[definition], type_ignores=[]), path, "exec"), scope)
    return scope[name]


class PostCallSmsGuardTests(unittest.TestCase):
    def test_plivo_kill_switch_defaults_off_and_honors_explicit_enable(self):
        tree = ast.parse(source(PLIVO), filename=PLIVO)
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "POST_CALL_SMS_ENABLED"
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        flag = compile(ast.Expression(body=assignments[0].value), PLIVO, "eval")
        for config, expected in [
            ({}, False),
            ({"POST_CALL_SMS_ENABLED": "false"}, False),
            ({"POST_CALL_SMS_ENABLED": "TRUE"}, True),
            ({"POST_CALL_SMS_ENABLED": " true "}, True),
            ({"POST_CALL_SMS_ENABLED": "unexpected"}, False),
        ]:
            with self.subTest(config=config):
                fake_os = SimpleNamespace(environ=config)
                self.assertIs(eval(flag, {"os": fake_os}), expected)
        self.assertIn("if not POST_CALL_SMS_ENABLED or not caller:", source(PLIVO))

    def test_whatsapp_call_setting_defaults_off(self):
        class Db:
            def __init__(self, row):
                self.row = row
            def Table(self, name):
                return self
            def get_item(self, **kwargs):
                return {"Item": self.row}
        for row, expected in [({}, False), ({"configValue": "false"}, False),
                              ({"configValue": "true"}, True)]:
            function = isolated_function(CALLING, "_is_sms_on_call_enabled",
                dynamodb=Db(row), SYSTEM_CONFIG_TABLE="unused-test-table",
                logger=SimpleNamespace(warning=lambda *a, **k: None))
            with self.subTest(row=row):
                self.assertIs(function(), expected)

    def test_sender_check_fail_closed_and_requires_registered_india_identity(self):
        fake_rows = [
            [], [{"SenderId": "WDBEEP", "IsoCountryCode": "IN", "Registered": False}],
            [{"SenderId": "WDBEEP", "IsoCountryCode": "US", "Registered": True}],
            [{"SenderId": "OTHER", "IsoCountryCode": "IN", "Registered": True}],
            [{"SenderId": "WDBEEP", "IsoCountryCode": "IN", "Registered": True}],
        ]
        outcomes = []
        requests = []
        for rows in fake_rows:
            client = SimpleNamespace(describe_sender_ids=lambda rows=rows: {"SenderIds": rows})
            function = isolated_function(CALLING, "_sms_sender_registered",
                boto3=SimpleNamespace(client=lambda service, region_name:
                    requests.append((service, region_name)) or client),
                logger=SimpleNamespace(warning=lambda *a, **k: None))
            outcomes.append(function())
        self.assertEqual(outcomes, [False, False, False, False, True])
        self.assertTrue(all(pair == ("pinpoint-sms-voice-v2", "ap-south-1") for pair in requests))

        def unavailable(*a, **kw):
            raise RuntimeError("read unavailable")
        function = isolated_function(CALLING, "_sms_sender_registered",
            boto3=SimpleNamespace(client=unavailable),
            logger=SimpleNamespace(warning=lambda *a, **k: None))
        self.assertIs(function(), False)

    def test_activating_call_sms_requires_sender_readiness_before_write(self):
        handler = source(CALLING)
        start = handler.index("sms_on_call = body.get('smsOnCall')")
        section = handler[start:start + 1100]
        self.assertLess(section.index("if sms_on_call and not _sms_sender_registered():"),
                        section.index("table.put_item(Item={"))
        self.assertIn("SMS_SENDER_NOT_REGISTERED", section)
        self.assertIn("smsOnCall must be a boolean", section)

    def test_release_manifest_keeps_post_call_sms_disabled(self):
        manifest = source("config/lambda-env-manifest.json")
        json.loads(manifest)
        self.assertIn('"POST_CALL_SMS_ENABLED": "false"', manifest)


if __name__ == "__main__":
    unittest.main()
