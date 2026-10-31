"""No-network regression: an HTTP 2xx does not prove WhatsApp Flow delivery.

Execute the exact production outcome classifiers for both the modern
one-order service launcher and legacy paid F003 Drop Docs. No AWS, Meta,
Razorpay, customer, invoice or WhatsApp operation is made.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "shared": (
        "amplify/functions/messaging/whatsapp-business-api/flows/service_flow_launcher.py",
        "_send_outcome",
    ),
    "legacy-drop-docs": (
        "amplify/functions/messaging/whatsapp-business-api/flows/paid_drop_docs.py",
        "_outcome",
    ),
}


def _actual_classifier(path, symbol):
    source = ROOT / path
    root = ast.parse(source.read_text(encoding="utf-8"))
    func = next((x for x in root.body
                 if isinstance(x, ast.FunctionDef) and x.name == symbol), None)
    if func is None:
        raise AssertionError(f"Required production classifier {symbol!r} missing in {source}")
    namespace = {"json": json}
    exec(compile(ast.Module(body=[func], type_ignores=[]),
                 str(source), "exec"), namespace)
    return namespace[symbol]


def test_both_paid_flow_senders_need_meta_issued_message_id():
    for label, (path, function) in SOURCES.items():
        classify = _actual_classifier(path, function)
        for code in (200, 201, 202, 204):
            for body in (None, {}, "{}", {"status": "queued"},
                         {"whatsappMessageId": ""},
                         "{malformed-json"):
                result = classify({"statusCode": code, "body": body})
                assert result == "SEND_UNKNOWN", (label, code, body, result)
            for body in ({"whatsappMessageId": "wamid.synthetic.123"},
                         json.dumps({"whatsappMessageId": "wamid.synthetic.123"})):
                result = classify({"statusCode": code, "body": body})
                assert result == "ACCEPTED", (label, code, body, result)


def test_declined_vs_ambiguous_outcomes_are_not_conflated():
    for label, (path, function) in SOURCES.items():
        classify = _actual_classifier(path, function)
        for response in (None, "200", [], {}, {"statusCode": "not-integer"},
                         {"statusCode": 503}, {"statusCode": 429},
                         {"statusCode": 502}, {"statusCode": 200, "body": None}):
            assert classify(response) == "SEND_UNKNOWN", (label, response)
        for code in (400, 401, 403, 404, 413, 415, 422):
            assert classify({"statusCode": code}) == "SEND_REJECTED", (label, code)


def test_paid_flow_callers_reconcile_unknown_not_blindly_retry():
    shared = (ROOT / SOURCES["shared"][0]).read_text(encoding="utf-8")
    legacy = (ROOT / SOURCES["legacy-drop-docs"][0]).read_text(encoding="utf-8")
    assert 'if current in ("SENDING", "SEND_UNKNOWN"):' in shared
    assert 'if current in ("SENDING", "SEND_UNKNOWN"):' in legacy
    assert '"SEND_REJECTED"' in shared and '"SEND_REJECTED"' in legacy
    assert "ConditionExpression" in shared and "ConditionExpression" in legacy
    assert '"SERVICE_FLOW_SENT" if status == "ACCEPTED"' in shared
    assert '"DROP_DOCS_FLOW_SENT" if status == "ACCEPTED"' in legacy
