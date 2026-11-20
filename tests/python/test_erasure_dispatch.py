"""A missing or unverified erasure executor never becomes a successful deletion."""
import io
import json

from lambda_utils.erasure.dispatch import dispatch_approved_erasure


BASE = dict(
    contact_id="customer-synthetic-1",
    actor="staff-admin-synthetic",
    case_id="case-12345",
    approval_token="synthetic-single-use-approval-token-98765",
    manifest_sha256="a" * 64,
    request_id="request-123",
)
FUNCTION = "synthetic-erasure-coordinator"


class FakeInvoke:
    def __init__(self, body, *, function_error=False, raises=False):
        self.body = body
        self.function_error = function_error
        self.raises = raises
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("transport lost")
        return {
            "StatusCode": 200,
            "FunctionError": "Unhandled" if self.function_error else None,
            "Payload": io.BytesIO(json.dumps(self.body).encode("utf-8")),
        }


def run(fake, **overrides):
    return dispatch_approved_erasure(
        coordinator_function=overrides.pop("coordinator_function", FUNCTION),
        invoke=fake,
        **(BASE | overrides),
    )


def verified_body(**overrides):
    return {
        "caseId": BASE["case_id"],
        "contactId": BASE["contact_id"],
        "manifestSha256": BASE["manifest_sha256"],
        "erasureComplete": True,
        "reconciliationComplete": True,
        "protectedContactsVerified": True,
        "financialEvidencePreserved": True,
        "auditId": "audit-synthetic-1",
    } | overrides


def test_missing_coordinator_returns_explicit_unavailable_without_invocation():
    fake = FakeInvoke(verified_body())
    result = run(fake, coordinator_function="")
    assert result.status == 503
    assert result.payload["errorCode"] == "ERASURE_COORDINATOR_UNAVAILABLE"
    assert result.payload["erasureComplete"] is False
    assert fake.calls == []


def test_missing_or_bad_approval_never_invokes():
    fake = FakeInvoke(verified_body())
    for change in [
        {"case_id": ""},
        {"approval_token": ""},
        {"approval_token": "short"},
        {"manifest_sha256": "bad"},
        {"actor": ""},
        {"contact_id": ""},
    ]:
        result = run(fake, **change)
        assert result.status in (403, 409)
        assert result.payload["erasureComplete"] is False
    assert fake.calls == []


def test_delegation_includes_exact_actor_case_and_manifest():
    fake = FakeInvoke(verified_body())
    result = run(fake)
    assert result.status == 200
    assert result.payload["erasureComplete"] is True
    assert result.payload["reconciliationComplete"] is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["FunctionName"] == FUNCTION
    assert call["InvocationType"] == "RequestResponse"
    request = json.loads(call["Payload"])
    assert request["contactId"] == BASE["contact_id"]
    assert request["requestedBy"] == BASE["actor"]
    assert request["caseId"] == BASE["case_id"]
    assert request["manifestSha256"] == BASE["manifest_sha256"]
    assert request["approvalToken"] == BASE["approval_token"]
    assert "overrideLocks" not in request
    assert "deleteAll" not in request


def test_api_gateway_style_worker_envelope_is_supported():
    fake = FakeInvoke({"statusCode": 200, "body": json.dumps(verified_body())})
    assert run(fake).status == 200


def test_false_completion_signal_cannot_claim_erasure():
    for change in [
        {"erasureComplete": False},
        {"reconciliationComplete": False},
        {"protectedContactsVerified": False},
        {"financialEvidencePreserved": False},
        {"auditId": ""},
        {"manifestSha256": "b" * 64},
        {"caseId": "other-case"},
        {"contactId": "other-contact"},
    ]:
        fake = FakeInvoke(verified_body(**change))
        result = run(fake)
        assert result.status == 502
        assert result.payload["erasureComplete"] is False
        assert result.payload["errorCode"] == "ERASURE_OUTCOME_UNVERIFIED"


def test_async_pending_status_does_not_claim_deletion():
    fake = FakeInvoke({
        "caseId": BASE["case_id"], "erasureComplete": False,
        "status": "PENDING", "auditId": "audit-123",
    })
    result = run(fake)
    assert result.status == 202
    assert result.payload["erasureComplete"] is False


def test_invocation_errors_have_indeterminate_outcome_not_fake_success():
    for kwargs in ({"function_error": True}, {"raises": True}):
        fake = FakeInvoke(verified_body(), **kwargs)
        result = run(fake)
        assert result.status == 502
        assert result.payload["errorCode"] == "ERASURE_OUTCOME_UNVERIFIED"
        assert result.payload["erasureComplete"] is False


def test_malformed_worker_response_is_unverified():
    fake = FakeInvoke({"statusCode": 200, "body": "not-json"})
    result = run(fake)
    assert result.status == 502
    assert result.payload["erasureComplete"] is False
