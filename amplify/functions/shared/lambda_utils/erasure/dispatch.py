"""Delegate an explicitly approved contact erasure to a dedicated coordinator.

This adapter intentionally has *no* DynamoDB/S3/Cognito delete calls. It
removes the legacy unconditional contact-delete refusal from the API routing
path without pretending that a reviewed cross-service executor exists.

The eventual coordinator is independently responsible for checking protected
contact IDs, payment dependencies, legal holds, a fresh approved manifest,
second-reviewer approval, write fences, idempotency and reconciliation.
An arbitrary response from the coordinator cannot be called "erased".
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, NamedTuple

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{5,127}$")


class ErasureDispatchResult(NamedTuple):
    status: int
    payload: dict[str, Any]


def _refuse(code: str, status: int, message: str) -> ErasureDispatchResult:
    return ErasureDispatchResult(status, {
        "errorCode": code, "error": message,
        "erasureComplete": False,
    })


def dispatch_approved_erasure(
    *,
    coordinator_function: str,
    contact_id: str,
    actor: str,
    case_id: str,
    approval_token: str,
    manifest_sha256: str,
    request_id: str,
    invoke: Callable[..., Mapping[str, Any]],
) -> ErasureDispatchResult:
    """Send an exact request to a separately deployed, trusted coordinator.

    The token is an opaque grant validated by the coordinator, never minted by
    this handler or used to override locked/financial records. The manifest
    must be bound by the coordinator to an approved, writer-fenced snapshot.
    """
    if not coordinator_function:
        return _refuse(
            "ERASURE_COORDINATOR_UNAVAILABLE", 503,
            "An approved selective-erasure coordinator is not configured. No deletion was started.",
        )

    if not actor or not contact_id:
        return _refuse(
            "ERASURE_ACTOR_UNVERIFIED", 403,
            "A verified staff actor and exact customer identity are required.",
        )

    if (not _CASE_ID.fullmatch(case_id or "")
            or not _SHA256.fullmatch(manifest_sha256 or "")
            or len(approval_token or "") < 24):
        return _refuse(
            "ERASURE_APPROVAL_REQUIRED", 409,
            "An approved case, single-use authorization and reviewed manifest are required.",
        )

    invocation = {
        "schemaVersion": 1,
        "action": "execute_approved_contact_erasure",
        "contactId": contact_id,
        "caseId": case_id,
        "manifestSha256": manifest_sha256,
        "approvalToken": approval_token,
        "requestedBy": actor,
        "requestId": request_id,
    }
    try:
        response = invoke(
            FunctionName=coordinator_function,
            InvocationType="RequestResponse",
            Payload=json.dumps(invocation).encode("utf-8"),
        )
        if response.get("StatusCode") != 200 or response.get("FunctionError"):
            return _refuse(
                "ERASURE_OUTCOME_UNVERIFIED", 502,
                "Coordinator returned an error. Reconcile the approved case before retrying.",
            )
        body_stream = response.get("Payload")
        output = json.loads(body_stream.read() if hasattr(body_stream, "read") else body_stream)
        if not isinstance(output, dict):
            raise ValueError("invalid coordinator envelope")
        if "statusCode" in output and output["statusCode"] not in (200, 202):
            return _refuse(
                "ERASURE_OUTCOME_UNVERIFIED", 502,
                "Coordinator refused or could not confirm the approved erasure.",
            )
        # API Gateway-style handler bodies have a nested JSON object.
        if "body" in output:
            raw_body = output["body"]
            body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
        else:
            body = output
        if not isinstance(body, dict):
            raise ValueError("invalid coordinator payload")
    except Exception:
        # An invocation may have started irreversible work before transport
        # or response decoding failed. Never claim "nothing was deleted" here.
        return _refuse(
            "ERASURE_OUTCOME_UNVERIFIED", 502,
            "Coordinator result could not be verified. Reconcile the case before retrying.",
        )

    # Require positive, independently checked evidence from the coordinator.
    # No response can claim full erasure with only a DynamoDB row deletion.
    if (body.get("caseId") == case_id
            and body.get("contactId") == contact_id
            and body.get("manifestSha256") == manifest_sha256
            and body.get("erasureComplete") is True
            and body.get("reconciliationComplete") is True
            and body.get("protectedContactsVerified") is True
            and body.get("financialEvidencePreserved") is True
            and body.get("identityClaimsReleased") is True
            and body.get("contactRecreatable") is True
            and isinstance(body.get("auditId"), str)
            and bool(body.get("auditId"))):
        return ErasureDispatchResult(200, {
            "success": True, "erasureComplete": True,
            "caseId": case_id,
            "auditId": body["auditId"],
            "reconciliationComplete": True,
            "identityClaimsReleased": True,
            "contactRecreatable": True,
        })

    if (body.get("caseId") == case_id
            and body.get("erasureComplete") is False
            and body.get("status") == "PENDING"
            and body.get("auditId")):
        return ErasureDispatchResult(202, {
            "success": False, "erasureComplete": False,
            "caseId": case_id, "status": "PENDING",
            "auditId": body["auditId"],
        })

    return _refuse(
        "ERASURE_OUTCOME_UNVERIFIED", 502,
        "The coordinator did not provide complete preservation and reconciliation proof.",
    )
