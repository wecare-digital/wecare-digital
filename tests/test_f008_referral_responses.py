"""F008 Referral acceptance tests: published identity, private storage, UI projection."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import canonical_flows, flow_launch, referral_response as referral  # noqa: E402

META_ID = "1933489271340286"
PAYLOAD = {
    "flow_key": "wd_f008_referral",
    "schema_version": "1",
    "referred_name": "Example Person",
    "referred_whatsapp": "+919876543210",
    "referral_details": "Asked for help with an enquiry.",
    "permission_confirmed": True,
}


def test_published_identity_in_backend_and_frontend():
    assert canonical_flows.canonical_flow_id("referral") == META_ID
    assert canonical_flows.published_flow_by_id(META_ID)["capability"] == "referral"
    ts = (ROOT / "src/lib/canonicalFlows.ts").read_text(encoding="utf-8")
    assert "capability: 'referral'" in ts
    assert "flowId: '1933489271340286'" in ts
    assert "status: 'PUBLISHED', metaName: 'WD-F008- Referal'" in ts



def test_customer_initiated_referral_launch_contract_enforces_published_unpaid_registry():
    contract = canonical_flows.canonical_contract("referral")
    assert contract["flowCode"] == "WD-F008-REFERRAL"
    assert contract["entryMode"] == "none"
    assert contract["entryTemplateName"] == ""
    assert contract["requiresPayment"] is False
    assert contract["defaultKeywords"] == ()
    assert contract["submissionPrefix"] == "WD-REF"
    row = {
        "flowId": META_ID,
        "flowCode": contract["flowCode"],
        "flowName": "WD-F008- Referal",
        "flowType": contract["flowType"],
        "wabaId": contract["wabaId"],
        "entryMode": "none",
        "entryTemplateName": "",
        "requiresPayment": False,
        "submissionPrefix": "WD-REF",
        "status": "PUBLISHED",
        "metaStatus": "PUBLISHED",
    }
    assert flow_launch.publication_decision(
        capability="referral", registry_row=row).allowed is True
    for change in (
        {"status": "DRAFT"},
        {"metaStatus": "DEPRECATED"},
        {"requiresPayment": True},
        {"entryMode": "payment_template"},
        {"flowCode": "WD-OTHER"},
    ):
        decision = flow_launch.publication_decision(
            capability="referral", registry_row={**row, **change})
        assert decision.allowed is False



def test_only_f008_terminal_nfm_reply_matches():
    message = {
        "type": "interactive",
        "interactive": {"type": "nfm_reply", "nfm_reply": {
            "name": "flow",
            "response_json": json.dumps(PAYLOAD),
        }},
    }
    assert referral.referral_payload(message) == PAYLOAD
    for other in (
        {"type": "referral", "referral": PAYLOAD},
        {"type": "interactive", "interactive": {"type": "button_reply"}},
        {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
            "response_json": json.dumps({**PAYLOAD, "flow_key": "other_flow"}),
        }}},
        {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
            "name": "address_message", "response_json": json.dumps(PAYLOAD),
        }}},
        {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
            "response_json": "{bad-json",
        }}},
    ):
        assert referral.referral_payload(other) is None


def test_required_values_and_consent():
    form = referral.clean_referral(PAYLOAD)
    assert form["permission_confirmed"] is True
    assert form["referred_whatsapp"] == "+919876543210"
    assert len(referral.response_answers(form)) == 4
    assert referral.clean_referral({**PAYLOAD, "permission_confirmed": "true"})["permission_confirmed"]
    for broken in (
        {"permission_confirmed": False},
        {"permission_confirmed": "false"},
        {"referred_name": ""},
        {"referred_whatsapp": "abc"},
        {"referred_whatsapp": "1"},
        {"referral_details": ""},
        {"referral_details": "x" * 301},
    ):
        with pytest.raises(ValueError):
            referral.clean_referral({**PAYLOAD, **broken})


def test_saves_one_sender_owned_unpaid_private_flow_submission(monkeypatch):
    captured = []
    fake = SimpleNamespace(status="created", submission_id="WD-REF-EXAMPLE", reference="WD-REF-EXAMPLE")
    monkeypatch.setattr(referral.flow_completion, "claim_completion", lambda **kw: captured.append(kw) or fake)
    result = referral.save_referral(
        PAYLOAD, contact_id="sender-contact", phone="+919999999999",
        sender_name="Sender", message_id="wamid.source-123", request_id="req-xyz",
        customer_uuid_value="sender-uuid",
    )
    assert result is fake
    assert len(captured) == 1
    saved = captured[0]
    assert saved["flow_token"] == "wamid.source-123"  # Meta ID drives dedup, never the referred number.
    assert saved["screen"] == "CONFIRMATION"
    assert saved["flow_code"] == "WD-F008-REFERRAL"
    assert saved["flow_type"] == "referral"
    assert saved["phone"] == "+919999999999"  # Referrer, not the referred person's number.
    assert saved["contact_id"] == "sender-contact"
    assert saved["status"] == "open"
    assert saved["reference_prefix"] == "WD-REF"
    assert saved["requires_payment"] is False
    assert saved["channel"] == "whatsapp"
    assert saved["extra"]["flowId"] == META_ID
    assert saved["extra"]["customerUuid"] == "sender-uuid"
    assert saved["extra"]["marketingOptIn"] is False
    assert saved["form_data"]["referred_whatsapp"] == "+919876543210"


def test_saving_failure_retries_instead_of_losing_submission(monkeypatch):
    monkeypatch.setattr(referral.flow_completion, "claim_completion", lambda **kw:
                        SimpleNamespace(status="error"))
    with pytest.raises(RuntimeError):
        referral.save_referral(
            PAYLOAD, contact_id="sender-contact", phone="+919999999999",
            sender_name="Sender", message_id="wamid.some-123",
        )


def test_published_json_markers_match_backend_schema():
    data = json.loads((ROOT / "docs/whatsapp/drafts/f008-referral-preview.json").read_text(encoding="utf-8"))
    assert data["version"] == "7.3"
    assert [s["id"] for s in data["screens"]] == ["REFER", "REVIEW", "CONFIRMATION"]
    form = next(c for c in data["screens"][0]["layout"]["children"] if c["type"] == "Form")
    fields = [c for c in form["children"] if c["type"] in ("TextInput", "TextArea")]
    assert [c["name"] for c in fields] == ["referred_name", "referred_whatsapp", "referral_details"]
    assert all(c["required"] for c in fields)
    review = next(c for c in data["screens"][1]["layout"]["children"] if c["type"] == "Form")
    assert next(c for c in review["children"] if c["type"] == "OptIn")["required"] is True
    done = data["screens"][-1]
    footer = next(c for c in done["layout"]["children"] if c["type"] == "Footer")
    assert footer["on-click-action"]["payload"]["flow_key"] == referral.FLOW_KEY
    assert footer["on-click-action"]["name"] == "complete"


def test_inbound_saver_before_message_dedup_and_both_inbox_stores():
    src = (ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py").read_text(encoding="utf-8")
    assert src.index("referral_response.save_referral(") < src.index("claim_event(whatsapp_message_id")
    assert "if _referral_inbox:" in src
    assert "**(_referral_inbox or {})," in src
    assert "if _referral_data is not None:" in src
    assert "referral_response.response_answers(" in src
    assert "Flow response — Referral" in src


def test_staff_response_surfaces_referral_without_automated_outreach():
    form_ui = (ROOT / "src/components/workspace/whatsapp/flow-responses.tsx").read_text(encoding="utf-8")
    queue_ui = (ROOT / "src/components/service/ResponsesQueue.tsx").read_text(encoding="utf-8")
    assert "F008ReferralDetails" in form_ui
    assert "Their WhatsApp number" in form_ui
    assert "WD-F008-REFERRAL" in queue_ui
    assert "ReferralDetails" in queue_ui
    src = (ROOT / "amplify/functions/shared/lambda_utils/referral_response.py").read_text(encoding="utf-8")
    assert "send_message(" not in src
    assert "create_contact(" not in src
