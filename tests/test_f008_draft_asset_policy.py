"""Security and review-contract tests for F008 Meta draft asset uploads."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/f008_draft_policy.py"
HANDLER = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"
PREVIEW = ROOT / "docs/whatsapp/drafts/f008-referral-preview.json"

spec = importlib.util.spec_from_file_location("f008_draft_policy", POLICY)
assert spec is not None and spec.loader is not None
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

WABA = "2094615664435155"
APP = "2238810740192680"


def fresh_meta_flow():
    return {
        "id": policy.F008_FLOW_ID,
        "name": policy.F008_META_NAME,
        "status": "DRAFT",
        "whatsapp_business_account": {"id": WABA},
        "application": {"id": APP},
    }


def test_only_existing_f008_draft_is_authorized():
    assert policy.is_f008_draft(policy.F008_FLOW_ID, fresh_meta_flow(), WABA, APP)


def test_other_id_cannot_be_edited():
    assert not policy.is_f008_draft("1804165164183485", fresh_meta_flow(), WABA, APP)


def test_published_flow_cannot_be_edited():
    flow = fresh_meta_flow()
    flow["status"] = "PUBLISHED"
    assert not policy.is_f008_draft(policy.F008_FLOW_ID, flow, WABA, APP)


def test_wrong_account_is_denied():
    flow = fresh_meta_flow()
    flow["whatsapp_business_account"] = {"id": "123"}
    assert not policy.is_f008_draft(policy.F008_FLOW_ID, flow, WABA, APP)


def test_wrong_meta_application_is_denied():
    flow = fresh_meta_flow()
    flow["application"] = {"id": "123"}
    assert not policy.is_f008_draft(policy.F008_FLOW_ID, flow, WABA, APP)


def test_missing_provider_fields_fail_closed():
    for removed in ("id", "name", "status", "whatsapp_business_account", "application"):
        flow = fresh_meta_flow()
        del flow[removed]
        assert not policy.is_f008_draft(policy.F008_FLOW_ID, flow, WABA, APP)


def test_untrusted_types_fail_closed():
    for flow in (None, "", [], {"id": policy.F008_FLOW_ID}):
        assert not policy.is_f008_draft(policy.F008_FLOW_ID, flow, WABA, APP)


def test_admin_gate_is_separate_from_published_inventory():
    content = HANDLER.read_text(encoding="utf-8")
    section = content.split("elif '/flows/assets' in path:", 1)[1].split(
        "elif '/flows/migrate' in path:", 1
    )[0]
    assert "canonical = _is_retained_customer_flow(flow_id)" in section
    assert "require_auth(event, required_role='Admin')" in section
    assert "is_f008_draft(flow_id, meta_flow, str(WABA1_ID), str(META_APP_ID))" in section
    assert "return _resp(404, {'error': 'Not a retained customer Flow'})" in section
    assert "'status' == 'DRAFT'" not in section  # Meta state is validated by policy
    assert "_publish_flow" not in section


def test_review_json_is_three_screens_with_no_optional_fields_or_reference():
    flow = json.loads(PREVIEW.read_text(encoding="utf-8"))
    assert flow["version"] == "7.3"
    assert [s["id"] for s in flow["screens"]] == ["REFER", "REVIEW", "CONFIRMATION"]
    assert flow["routing_model"] == {
        "REFER": ["REVIEW"],
        "REVIEW": ["CONFIRMATION"],
        "CONFIRMATION": [],
    }
    first = next(x for x in flow["screens"][0]["layout"]["children"] if x["type"] == "Form")
    fields = [x for x in first["children"] if x["type"] in ("TextInput", "TextArea")]
    assert [x["name"] for x in fields] == [
        "referred_name", "referred_whatsapp", "referral_details"
    ]
    assert all(field["required"] is True for field in fields)
    review = next(x for x in flow["screens"][1]["layout"]["children"] if x["type"] == "Form")
    consents = [x for x in review["children"] if x["type"] == "OptIn"]
    assert len(consents) == 1 and consents[0]["required"] is True
    assert all(sum(x["type"] == "Image" for x in s["layout"]["children"]) == 2
               for s in flow["screens"])
    assert flow["screens"][-1]["terminal"] is True
    assert all("reference_number" not in json.dumps(s)
               and '"Dropdown"' not in json.dumps(s) for s in flow["screens"])
