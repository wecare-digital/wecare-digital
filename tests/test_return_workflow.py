"""Return / Refund cases advance through an audited, non-money lifecycle."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import return_workflow  # noqa: E402


def _case(stage=None):
    item = {
        "submissionId": "WD-SR-1",
        "orderId": "WD-ORD-1",
        "requestType": "Return / Refund",
        "status": "open",
    }
    if stage is not None:
        item["returnStage"] = stage
    return item


def test_requested_can_be_approved_or_rejected_only():
    for target in ("approved", "rejected"):
        decision, error = return_workflow.validate_transition(_case(), target, "reviewed")
        assert error is None
        assert decision["currentStage"] == "requested"
        assert decision["targetStage"] == target

    decision, error = return_workflow.validate_transition(_case(), "refund_eligible", "skip")
    assert decision is None
    assert error["errorCode"] == "RETURN_WORKFLOW_TRANSITION_INVALID"


def test_approved_requires_receipt_or_explicit_waiver_before_refund_eligibility():
    for target in ("item_received", "return_waived"):
        decision, error = return_workflow.validate_transition(
            _case("approved"), target, "Evidence checked"
        )
        assert error is None
        assert decision["targetStage"] == target

    decision, error = return_workflow.validate_transition(
        _case("approved"), "refund_eligible", "too early"
    )
    assert decision is None
    assert error["errorCode"] == "RETURN_WORKFLOW_TRANSITION_INVALID"


def test_received_or_waived_can_become_refund_eligible():
    for stage in ("item_received", "return_waived"):
        decision, error = return_workflow.validate_transition(
            _case(stage), "refund_eligible", "Ready for finance review"
        )
        assert error is None
        assert decision["targetStage"] == "refund_eligible"


def test_rejection_and_waiver_require_a_reason():
    decision, error = return_workflow.validate_transition(_case(), "rejected", "")
    assert decision is None
    assert error["errorCode"] == "RETURN_WORKFLOW_NOTE_REQUIRED"

    decision, error = return_workflow.validate_transition(_case("approved"), "return_waived", "")
    assert decision is None
    assert error["errorCode"] == "RETURN_WORKFLOW_NOTE_REQUIRED"


def test_provider_refund_words_are_not_staff_return_stages():
    for target in ("refund_pending", "refunded", "refund_processed"):
        decision, error = return_workflow.validate_transition(
            _case("refund_eligible"), target, "provider only"
        )
        assert decision is None
        assert error["errorCode"] == "RETURN_WORKFLOW_STAGE_INVALID"


def test_non_return_case_cannot_enter_return_workflow():
    item = _case()
    item["requestType"] = "Delivery Issue"
    decision, error = return_workflow.validate_transition(item, "approved", "n/a")
    assert decision is None
    assert error["errorCode"] == "RETURN_WORKFLOW_REQUEST_TYPE_REQUIRED"


def test_same_stage_is_idempotent():
    decision, error = return_workflow.validate_transition(
        _case("item_received"), "item_received", "retry"
    )
    assert error is None
    assert decision["idempotent"] is True


def test_whatsapp_handler_uses_authenticated_actor_and_admin_gate_for_return_stage():
    source = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text()
    assert "required_role='Admin' if is_return_transition else 'Viewer'" in source
    block = source[source.index("def _update_submission_status"):source.index("def _project_submission_attachments")]
    assert "actor_info.get('username')" in block
    assert "body.get('changedBy'" not in block
    assert "validate_transition(" in block
    assert "ConsistentRead=True" in block
    assert "RETURN_WORKFLOW_STALE" in block
    history = source[source.index("def _return_history"):source.index("def _update_submission_status")]
    assert "RETURN_STAGE#" in history
    assert "refundEligibleAt" in block
    assert "refundId" not in block
    assert "refundAmount" not in block


def test_generic_request_status_write_is_race_guarded():
    source = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text()
    block = source[source.index("def _update_submission_status"):source.index("def _project_submission_attachments")]
    assert "ConditionExpression='#st = :old_status'" in block
    assert "REQUEST_STATUS_STALE" in block
