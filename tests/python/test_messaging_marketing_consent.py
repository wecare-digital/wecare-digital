"""MSG-5: marketing sends obey the consent ledger, and Meta stop/resume reaches it.

whatsapp-business-api needs `cryptography` at import time, so its send gate is compiled
from the real source (AST) with fakes for Meta and DynamoDB. The inbound worker is loaded
with fake AWS credentials and in-memory tables.
"""
import ast
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import mock

import pytest
from botocore.exceptions import ClientError

from lambda_utils import contact_store, direct_send, template_status, whatsapp_templates
from lambda_utils.identity import consent as consent_evidence

ROOT = Path(__file__).resolve().parents[2]
BUSINESS_API = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
INBOUND = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"
PHONE = "919800000003"
WABA1_PHONE = "1016149501586345"


def opted(*states):
    now = int(time.time()) - 100
    return [consent_evidence.build_record(channel="WHATSAPP", state=s, source="WEB_FORM"
                                          if s == "OPTED_IN" else "CUSTOMER_REQUEST",
                                          at=now + i, purpose="MARKETING")
            for i, s in enumerate(states)]


# ── whatsapp-business-api send gate ──────────────────────────────────────────

def business_api(templates=None, list_status=200):
    names = {"_TEMPLATE_CATEGORY_TTL", "_template_categories", "TemplateCategoryUnavailable",
             "_live_template_category", "_template_send_purpose", "_marketing_consent_refusal",
             "_send_message", "_send_marketing_message"}
    tree = ast.parse(BUSINESS_API.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
             or (isinstance(n, (ast.Assign, ast.AnnAssign)) and any(
                 getattr(t, "id", None) in names
                 for t in (n.targets if isinstance(n, ast.Assign) else [n.target])))]
    sent, listed = [], []

    def list_templates(waba_id):
        listed.append(waba_id)
        return {"statusCode": list_status, "body": json.dumps({"data": templates or []})}

    env = {
        "__builtins__": __builtins__, "Dict": Dict, "Any": Any, "Optional": Optional,
        "json": json, "time": time, "logger": mock.Mock(),
        "consent_evidence": consent_evidence, "template_status": template_status,
        "whatsapp_templates": whatsapp_templates, "direct_send_util": direct_send,
        "mask_contact_id": lambda v: "***", "CONTACTS_TABLE": "Contacts",
        "dynamodb": SimpleNamespace(Table=lambda name: name),
        "_list_payment_templates": list_templates,
        "_resp": lambda code, body: {"statusCode": code, "body": json.dumps(body)},
        "_graph_api": lambda path, **kw: sent.append((path, kw.get("payload"))) or {
            "messages": [{"id": "wamid.OUT"}]},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUSINESS_API), "exec"), env)
    return SimpleNamespace(env=env, sent=sent, listed=listed)


@pytest.fixture
def api(monkeypatch):
    def make(ledger=None, templates=None, list_status=200):
        row = ({"id": f"wa{PHONE}", "phone": "+" + PHONE, "consentLedger": ledger}
               if ledger is not None else None)
        monkeypatch.setattr(contact_store, "lookup",
                            lambda table, phone: row if row and str(phone).lstrip("+") == PHONE else None)
        monkeypatch.setattr(contact_store, "find_by_bsuid", lambda table, bsuid: None)
        return business_api(templates, list_status)
    return make


PROMO = [{"name": "diwali_offer", "status": "APPROVED", "category": "MARKETING"}]


def template_message(name):
    return {"type": "template", "template": {"name": name, "language": {"code": "en"}}}


@pytest.mark.parametrize("ledger", [None, [], opted("OPTED_IN", "OPTED_OUT"), opted("PENDING")])
def test_marketing_template_refused_without_current_opt_in(api, ledger):
    made = api(ledger=ledger, templates=PROMO)
    result = made.env["_send_message"](WABA1_PHONE, template_message("diwali_offer"), {"to": PHONE})
    assert result["statusCode"] == 403
    assert json.loads(result["body"])["error"] == "WHATSAPP_MARKETING_CONSENT_REQUIRED"
    assert made.sent == []


def test_marketing_template_sent_to_opted_in_customer(api):
    made = api(ledger=opted("OPTED_OUT", "OPTED_IN"), templates=PROMO)
    result = made.env["_send_message"](WABA1_PHONE, template_message("diwali_offer"), {"to": PHONE})
    assert result["statusCode"] == 200 and len(made.sent) == 1


def test_caller_cannot_downgrade_a_marketing_template(api):
    made = api(ledger=None, templates=PROMO)
    body = {"to": PHONE, "messagePurpose": "SERVICE"}
    assert made.env["_send_message"](WABA1_PHONE, template_message("diwali_offer"), body)["statusCode"] == 403


def test_explicit_marketing_purpose_is_honoured_for_any_template(api):
    made = api(ledger=None)
    body = {"to": PHONE, "messagePurpose": "MARKETING"}
    assert made.env["_send_message"](WABA1_PHONE, template_message("service_details"), body)["statusCode"] == 403


def test_registered_utility_and_sign_in_templates_need_no_meta_read(api):
    made = api(ledger=None, list_status=502)
    for name in ("wecare_otp", "service_details", "wecare_leave_review"):
        result = made.env["_send_message"](WABA1_PHONE, template_message(name), {"to": PHONE})
        assert result["statusCode"] == 200, name
    assert made.listed == []


def test_internal_invoke_of_an_unregistered_template_skips_the_meta_read(api):
    made = api(ledger=None, list_status=502)
    result = made.env["_send_message"](WABA1_PHONE, template_message("custom_otp_v2"),
                                       {"to": PHONE}, internal=True)
    assert result["statusCode"] == 200 and made.listed == []


def test_unprovable_category_fails_closed(api):
    made = api(ledger=opted("OPTED_IN"), list_status=502)
    result = made.env["_send_message"](WABA1_PHONE, template_message("diwali_offer"), {"to": PHONE})
    assert result["statusCode"] == 503 and made.sent == []


def test_text_messages_are_not_gated(api):
    made = api(ledger=None, list_status=502)
    text = {"type": "text", "text": {"body": "hi"}}
    assert made.env["_send_message"](WABA1_PHONE, text, {"to": PHONE})["statusCode"] == 200


def test_marketing_messages_api_requires_opt_in(api):
    made = api(ledger=None)
    result = made.env["_send_marketing_message"](WABA1_PHONE, {"to": PHONE, "templateName": "diwali_offer"})
    assert result["statusCode"] == 403 and made.sent == []
    made = api(ledger=opted("OPTED_IN"))
    ok = made.env["_send_marketing_message"](WABA1_PHONE, {"to": PHONE, "templateName": "diwali_offer"})
    assert ok["statusCode"] == 200 and made.sent[0][0] == f"{WABA1_PHONE}/marketing_messages"


# ── inbound: Meta user_preferences -> ledger ─────────────────────────────────

@pytest.fixture(scope="module")
def inbound():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    sys.path.insert(0, str(INBOUND.parent))
    spec = importlib.util.spec_from_file_location("inbound_consent_under_test", INBOUND)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(INBOUND.parent))
        sys.modules.pop(spec.name, None)


class ContactTable:
    def __init__(self, row, conflicts=0):
        self.row = row
        self.conflicts = conflicts
        self.updates = []

    def get_item(self, Key, ConsistentRead=False):
        return {"Item": dict(self.row)}

    def update_item(self, **kwargs):
        if self.conflicts:
            self.conflicts -= 1
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        self.updates.append(kwargs)
        self.row["consentLedger"] = kwargs["ExpressionAttributeValues"][":ledger"]


def preference(value, ts=1731705721, category="marketing_messages"):
    return {"user_preferences": [{"wa_id": PHONE, "category": category, "value": value,
                                  "timestamp": ts, "detail": "User requested"}]}


def run_preference(inbound, table, value, **kw):
    with mock.patch.object(inbound, "dynamodb", SimpleNamespace(Table=lambda name: table)), \
            mock.patch.object(inbound.contact_store, "lookup",
                              lambda t, phone: dict(table.row) if phone == PHONE else None):
        inbound._record_marketing_preferences(preference(value, **kw), {}, ["waba-1"], "req")


def state_of(row):
    return consent_evidence.current_state(row, "WHATSAPP", now=int(time.time()), purpose="MARKETING")


def test_stop_writes_opted_out_and_resume_opted_in(inbound):
    table = ContactTable({"id": f"wa{PHONE}", "consentLedger": opted("OPTED_IN")})
    run_preference(inbound, table, "stop", ts=int(time.time()))
    assert state_of(table.row) == "OPTED_OUT"
    record = table.row["consentLedger"][-1]
    assert record["source"] == "CUSTOMER_REQUEST" and record["purpose"] == "MARKETING"
    run_preference(inbound, table, "resume", ts=int(time.time()) + 1)
    assert state_of(table.row) == "OPTED_IN"
    assert len(table.row["consentLedger"]) == 3  # history is kept


def test_redelivered_stop_is_not_written_twice(inbound):
    table = ContactTable({"id": f"wa{PHONE}"})
    run_preference(inbound, table, "stop")
    run_preference(inbound, table, "stop")
    assert len(table.updates) == 1
    assert "attribute_not_exists(#ledger)" in table.updates[0]["ConditionExpression"]


def test_concurrent_ledger_append_is_retried_not_lost(inbound):
    table = ContactTable({"id": f"wa{PHONE}", "consentLedger": opted("OPTED_IN")}, conflicts=1)
    run_preference(inbound, table, "stop", ts=int(time.time()))
    assert len(table.updates) == 1 and state_of(table.row) == "OPTED_OUT"


@pytest.mark.parametrize("value,category", [("stop", "offers"), ("interested", "marketing_messages")])
def test_other_preferences_write_nothing(inbound, value, category):
    table = ContactTable({"id": f"wa{PHONE}"})
    run_preference(inbound, table, value, category=category)
    assert table.updates == []


def _user_preferences_event():
    entry = {"id": "waba-1", "changes": [{"field": "user_preferences", "value": {
        "metadata": {"phone_number_id": "111"}, **preference("stop")}}]}
    return {"source": "meta-direct", "version": 1, "entry": entry, "wabaId": "waba-1",
            "metaPhoneNumberIds": ["111"], "requestId": "req-1"}


def _ctx():
    ctx = mock.Mock()
    ctx.get_remaining_time_in_millis.return_value = 120000
    ctx.aws_request_id = "req-1"
    return ctx


@pytest.mark.parametrize("parked", [True, False])
def test_failed_consent_write_is_parked_not_dropped(inbound, parked):
    with mock.patch.object(inbound, "_store_system_event"), \
            mock.patch.object(inbound, "_record_marketing_preferences",
                              side_effect=RuntimeError("throttled")), \
            mock.patch.object(inbound, "_send_to_dlq", return_value=parked) as dlq:
        if parked:
            assert inbound.handler(_user_preferences_event(), _ctx())["statusCode"] == 200
        else:
            with pytest.raises(RuntimeError):
                inbound.handler(_user_preferences_event(), _ctx())
    record, reason, _ = dlq.call_args_list[0].args
    assert record["entry"]["changes"][0]["field"] == "user_preferences"
    assert reason == "user_preferences_consent:RuntimeError"
