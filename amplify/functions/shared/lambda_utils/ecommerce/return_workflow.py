"""Audited lifecycle rules for Return / Refund service cases.

A return case is not itself a refund. Staff may move a verified return request through
review and receipt/waiver stages until it becomes refund-eligible. Provider refund state
is deliberately outside this module and must come from the payment workflow/webhook.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

REQUEST_TYPE = "Return / Refund"
REQUESTED = "requested"
APPROVED = "approved"
REJECTED = "rejected"
ITEM_RECEIVED = "item_received"
RETURN_WAIVED = "return_waived"
REFUND_ELIGIBLE = "refund_eligible"

STAFF_STAGES = frozenset({
    APPROVED,
    REJECTED,
    ITEM_RECEIVED,
    RETURN_WAIVED,
    REFUND_ELIGIBLE,
})

_NEXT = {
    REQUESTED: frozenset({APPROVED, REJECTED}),
    APPROVED: frozenset({ITEM_RECEIVED, RETURN_WAIVED}),
    ITEM_RECEIVED: frozenset({REFUND_ELIGIBLE}),
    RETURN_WAIVED: frozenset({REFUND_ELIGIBLE}),
    REFUND_ELIGIBLE: frozenset(),
    REJECTED: frozenset(),
}


def current_stage(item: Mapping[str, Any]) -> str:
    value = str(item.get("returnStage") or "").strip().lower()
    if value:
        return value
    if str(item.get("requestType") or "").strip() == REQUEST_TYPE:
        return REQUESTED
    return ""


def validate_transition(
    item: Mapping[str, Any], target: Any, note: Any = ""
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    if str(item.get("requestType") or "").strip() != REQUEST_TYPE:
        return None, {
            "error": "Return lifecycle applies only to Return / Refund requests",
            "errorCode": "RETURN_WORKFLOW_REQUEST_TYPE_REQUIRED",
        }

    if not isinstance(target, str):
        return None, {
            "error": "returnStage is required",
            "errorCode": "RETURN_WORKFLOW_STAGE_REQUIRED",
        }
    target_stage = target.strip().lower().replace("-", "_").replace(" ", "_")
    if target_stage not in STAFF_STAGES:
        return None, {
            "error": "Unknown or provider-controlled return stage",
            "errorCode": "RETURN_WORKFLOW_STAGE_INVALID",
        }

    current = current_stage(item)
    if current not in _NEXT:
        return None, {
            "error": "Existing return stage is unknown and needs review",
            "errorCode": "RETURN_WORKFLOW_REVIEW_REQUIRED",
        }

    if not isinstance(note, str):
        return None, {
            "error": "Transition note must be text",
            "errorCode": "RETURN_WORKFLOW_NOTE_INVALID",
        }
    cleaned_note = note.strip()
    invalid_control = any(
        (ord(ch) < 32 and ch not in "\r\n\t") or ord(ch) == 127
        for ch in cleaned_note
    )
    if len(cleaned_note) > 1000 or invalid_control:
        return None, {
            "error": "Transition note is overlong or contains control characters",
            "errorCode": "RETURN_WORKFLOW_NOTE_INVALID",
        }

    if target_stage == current:
        return {
            "currentStage": current,
            "targetStage": target_stage,
            "note": cleaned_note,
            "idempotent": True,
        }, None

    if target_stage not in _NEXT[current]:
        return None, {
            "error": f"Illegal return transition: {current} -> {target_stage}",
            "errorCode": "RETURN_WORKFLOW_TRANSITION_INVALID",
        }

    if target_stage in {REJECTED, RETURN_WAIVED} and not cleaned_note:
        return None, {
            "error": "A reason is required for rejection or return waiver",
            "errorCode": "RETURN_WORKFLOW_NOTE_REQUIRED",
        }

    return {
        "currentStage": current,
        "targetStage": target_stage,
        "note": cleaned_note,
        "idempotent": False,
    }, None


__all__ = [
    "REQUEST_TYPE",
    "REQUESTED",
    "APPROVED",
    "REJECTED",
    "ITEM_RECEIVED",
    "RETURN_WAIVED",
    "REFUND_ELIGIBLE",
    "STAFF_STAGES",
    "current_stage",
    "validate_transition",
]
