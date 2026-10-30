"""Regression tests for shared Flow screens, paid target INIT and Pickup saves."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(ROOT / "amplify/functions/messaging/whatsapp-business-api"))

from lambda_utils import pickup_request_response as pickup  # noqa: E402
from flows import paid_service_targets as targets  # noqa: E402


def _published(name):
    path = (ROOT / "amplify/functions/messaging/whatsapp-business-api/flows"
            / "published" / name)
    return json.loads(path.read_text())


def test_shared_screen_contract_and_pickup_specific_fields():
    common = ["submit-request.json", "request-amendment.json",
              "request-pickup.json", "shipments.json"]
    for name in common:
        flow = _published(name)
        assert [screen["id"] for screen in flow["screens"]] == [
            "SELECT_TARGET", "NOTE", "CONFIRMATION"]
        assert flow["screens"][0]["data"]["targets"]["type"] == "array"

    form = next(c for c in _published("request-pickup.json")["screens"][1]
                ["layout"]["children"] if c["type"] == "Form")
    required = {"pickup_address", "preferred_date",
                "pickup_window", "package_description"}
    assert required.issubset({c.get("name") for c in form["children"]})
    pay = next(c for c in form["children"]
               if c["type"] == "Footer")["on-click-action"]["payload"]
    for name in required:
        assert pay[name] == "${form." + name + "}"

    done = _published("request-pickup.json")["screens"][-1]
    complete = next(c for c in done["layout"]["children"]
                    if c["type"] == "Footer")["on-click-action"]["payload"]
    assert complete["flow_key"] == pickup.FLOW_KEY
    assert complete["design_service"] == "request-pickup"
    for name in required:
        assert complete[name] == "${data." + name + "}"
        assert name in done["data"]
    assert "wd_f004_submit_request" not in json.dumps(_published("request-pickup.json"))


def _reply(marker, token, *, full=True):
    fields = {
        "flow_key": marker,
        "flow_token": token,
        "reference_number": "order:WD-ORD-ABCDEFGH",
        "schema_version": "2",
    }
    if full:
        fields.update({
            "pickup_address": "12 Main Road, Kolkata",
            "preferred_date": "2026-11-04",
            "pickup_window": "morning",
            "package_description": "One packed box",
        })
    return {"type": "interactive", "interactive": {
        "type": "nfm_reply", "nfm_reply": {"response_json": json.dumps(fields)}}}


def test_pickup_only_recognises_full_payload_with_pickup_session():
    tok = "request_pickup-abcd-waba-1-ph-919999999999"
    assert pickup.pickup_payload(_reply(pickup.FLOW_KEY, tok)) is not None
    assert pickup.pickup_payload(_reply(pickup.CLONED_FLOW_KEY, tok)) is not None
    assert pickup.pickup_payload(_reply(pickup.CLONED_FLOW_KEY, tok, full=False)) is None
    assert pickup.pickup_payload(_reply(pickup.FLOW_KEY, "srpaid-abcd-ph-9")) is None
    assert pickup.pickup_payload(_reply("wd_f005_request_amendment", tok)) is None


def _binding():
    return SimpleNamespace(
        payment_attempt_id="paid-attempt-1",
        order_id="order-owned-1",
        order_number="WD-ORD-ABCDEFGH",
        customer_id="cognito-owner-1",
    )


def test_pickup_rejects_foreign_order_before_business_write():
    data = pickup.pickup_payload(
        _reply(pickup.FLOW_KEY, "request_pickup-abcd-waba-1-ph-919999999999"))
    data["reference_number"] = "order:WD-ORD-FOREIGN"
    db = Mock()
    session = SimpleNamespace(phone="919999999999")
    with patch.object(pickup.flow_sessions, "verify_session", return_value=session), \
         patch.object(pickup.single_order_flow, "verify_paid_session", return_value=_binding()), \
         patch.object(pickup.flow_completion, "claim_completion") as claim:
        try:
            pickup.save_pickup(
                data, contact_id="wa919999999999", phone="919999999999",
                sender_name="Tester", message_id="wamid.1", dynamodb=db)
        except ValueError as exc:
            assert "paid order" in str(exc)
        else:
            raise AssertionError("A different order was accepted")
        claim.assert_not_called()


def test_pickup_claims_once_per_paid_attempt_without_charging_again():
    data = pickup.pickup_payload(
        _reply(pickup.FLOW_KEY, "request_pickup-abcd-waba-1-ph-919999999999"))
    db = Mock()
    session = SimpleNamespace(phone="919999999999")
    result = SimpleNamespace(status="created", submission_id="WD-PU-TEST",
                             reference="WD-PU-TEST", item={"status": "pending_confirmation"})
    with patch.object(pickup.flow_sessions, "verify_session", return_value=session), \
         patch.object(pickup.single_order_flow, "verify_paid_session", return_value=_binding()), \
         patch.object(pickup.flow_completion, "claim_completion", return_value=result) as claim, \
         patch.object(pickup.flow_sessions, "mark_consumed") as consume:
        actual = pickup.save_pickup(
            data, contact_id="wa919999999999", phone="919999999999",
            sender_name="Tester", message_id="wamid.1", dynamodb=db)
    assert actual is result
    kwargs = claim.call_args.kwargs
    assert kwargs["flow_token"] == "paid-attempt-1"
    assert kwargs["status"] == "pending_confirmation"
    assert kwargs["requires_payment"] is False
    assert kwargs["form_data"]["pickup_address"] == "12 Main Road, Kolkata"
    assert kwargs["form_data"]["preferred_date"] == "2026-11-04"
    assert kwargs["extra"]["paymentAttemptId"] == "paid-attempt-1"
    consume.assert_called_once()


def test_paid_shared_target_init_never_accepts_client_order_list():
    session = SimpleNamespace(phone="919999999999", consumed_at=0)
    db = Mock()
    with patch.object(targets.boto3, "resource", return_value=db), \
         patch.object(targets.flow_sessions, "verify_session", return_value=session), \
         patch.object(targets.single_order_flow, "verify_paid_session", return_value=_binding()) as proof:
        data = targets.handle_init("request_pickup-abcd-waba-1-ph-919999999999")
    assert data == {"screen": "SELECT_TARGET", "data": {"targets": [
        {"id": "order:WD-ORD-ABCDEFGH", "title": "Order · WD-ORD-ABCDEFGH"}
    ]}}
    assert proof.call_args.kwargs["capability"] == "request_pickup"
    assert proof.call_args.kwargs["service_code"] == "REQUEST_PICKUP"


def test_bad_paid_session_returns_only_an_unavailable_picker():
    with patch.object(targets.flow_sessions, "verify_session",
                      side_effect=targets.flow_sessions.FlowSessionRejected("missing", "bad")):
        data = targets.handle_init("request_pickup-abcd-waba-1-ph-919999999999")
    assert data["screen"] == "SELECT_TARGET"
    assert data["data"]["targets"][0]["id"] == "unavailable"


def test_router_and_inbound_use_dedicated_safe_paths():
    router = (ROOT / "amplify/functions/messaging/whatsapp-business-api"
              / "flows/router.py").read_text()
    inbound = (ROOT / "amplify/functions/messaging/inbound-whatsapp-handler"
               / "handler.py").read_text()
    assert "paid_service_targets.handle_init(flow_token)" in router
    assert "review_token.is_review_token(flow_token)" in router
    assert "pickup_request_response.pickup_payload(message)" in inbound
    assert "pickup_request_response.save_pickup(" in inbound
    assert "_pickup_inbox" in inbound
    assert inbound.index("_pickup_data = pickup_request_response.pickup_payload(message)") < \
           inbound.index("_submit_request_data = submit_request_response.request_payload(message)")
