"""Contract for the one path a Lambda uses to trigger a customer SMS.

Every notification SMS goes to `wecare-sms-aws`, which sends through AWS End User
Messaging. These tests pin the properties that keep it the only path:

  * the target is always the AWS SMS function, for every destination country
  * the payload is exactly the documented shape, so no caller can steer transport
  * the caller passes a template KEY, never a raw DLT template id
  * dispatch is asynchronous unless the caller explicitly needs the message id
  * a transport failure returns a result, it does not raise into a webhook handler
  * an Indian number with no template key is NOT silently given one here
"""
import json
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.comms import notify as notify_mod  # noqa: E402


class _FakePayload:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw


class _FakeLambda:
    """Records invoke() calls. Optionally returns a synchronous response."""

    def __init__(self, sync_status=200, sync_body=None, raise_with=None):
        self.calls = []
        self.sync_status = sync_status
        self.sync_body = sync_body if sync_body is not None else {"providerMessageId": "prov-1"}
        self.raise_with = raise_with

    def invoke(self, **kwargs):
        if self.raise_with:
            raise self.raise_with
        self.calls.append(kwargs)
        outer = {"statusCode": self.sync_status, "body": json.dumps(self.sync_body)}
        return {"Payload": _FakePayload(json.dumps(outer).encode())}


@pytest.fixture
def fake_lambda(monkeypatch):
    client = _FakeLambda()
    monkeypatch.setattr(notify_mod, "_lambda_client", lambda: client)
    return client


def _body_of(call):
    return json.loads(call["Payload"].decode())["body"]


def _parsed_body(call):
    return json.loads(_body_of(call))


# --------------------------------------------------------------------------
# the target is AWS, always
# --------------------------------------------------------------------------
def test_target_is_the_aws_sms_function(fake_lambda):
    notify_mod.send_notification_sms("+919903300044", "hello",
                                     dlt_template_key="ivr-default")
    assert len(fake_lambda.calls) == 1
    assert fake_lambda.calls[0]["FunctionName"] == "wecare-sms-aws:live"


def test_every_destination_country_targets_the_same_aws_function(fake_lambda):
    """India is not routed anywhere else: one SMS function for every country."""
    notify_mod.send_notification_sms("+919903300044", "hi", dlt_template_key="ivr-default")
    notify_mod.send_notification_sms("+18444891209", "hi")
    notify_mod.send_notification_sms("+6581234567", "hi")
    targets = {c["FunctionName"] for c in fake_lambda.calls}
    assert targets == {"wecare-sms-aws:live"}


def test_the_payload_is_exactly_the_documented_shape(fake_lambda):
    """Nothing beyond the sms-aws send contract travels with the message."""
    notify_mod.send_notification_sms("+919903300044", "hello",
                                     dlt_template_key="ivr-default",
                                     campaign="post-call")
    payload = json.loads(fake_lambda.calls[0]["Payload"].decode())
    assert set(payload) == {"rawPath", "requestContext", "headers", "body"}
    assert payload["requestContext"] == {"http": {"method": "POST", "path": "/sms-aws/send"}}
    assert payload["headers"] == {"origin": "https://wecare.digital"}
    assert json.loads(payload["body"]) == {
        "phoneNumber": "+919903300044",
        "content": "hello",
        "messageType": "TRANSACTIONAL",
        "dltTemplateKey": "ivr-default",
        "campaignName": "post-call",
    }


def test_route_is_the_sms_aws_send_path(fake_lambda):
    notify_mod.send_notification_sms("+18444891209", "hello")
    payload = json.loads(fake_lambda.calls[0]["Payload"].decode())
    assert payload["rawPath"] == "/sms-aws/send"
    assert payload["requestContext"]["http"]["method"] == "POST"


# --------------------------------------------------------------------------
# template KEY, not template id
# --------------------------------------------------------------------------
def test_caller_passes_a_template_key_not_an_id(fake_lambda):
    notify_mod.send_notification_sms("+919903300044", "hello",
                                     dlt_template_key="ivr-default")
    body = _parsed_body(fake_lambda.calls[0])
    assert body["dltTemplateKey"] == "ivr-default"
    # The caller must NOT be able to name a raw template id, entity or sender:
    # resolving those is comms.dlt's job, and a caller that could pass one could
    # pass an unapproved one.
    for forbidden in ("dltTemplateId", "entityId", "sourceAddress", "apiVersion"):
        assert forbidden not in body


def test_india_without_template_key_is_not_given_one_here(fake_lambda):
    """The DLT gate lives in comms.dlt and must be the thing that refuses.

    Guessing a default template here would defeat the single source of truth.
    """
    result = notify_mod.send_notification_sms("+919903300044", "hello")
    assert result.queued is True
    assert "dltTemplateKey" not in _parsed_body(fake_lambda.calls[0])


def test_build_payload_is_stable_without_boto3():
    payload = notify_mod.build_payload("+919903300044", "hi",
                                       dlt_template_key="wd_order",
                                       campaign="order-confirm")
    body = json.loads(payload["body"])
    assert body == {
        "phoneNumber": "+919903300044",
        "content": "hi",
        "messageType": "TRANSACTIONAL",
        "dltTemplateKey": "wd_order",
        "campaignName": "order-confirm",
    }


# --------------------------------------------------------------------------
# asynchronous by default
# --------------------------------------------------------------------------
def test_dispatch_is_async_by_default(fake_lambda):
    notify_mod.send_notification_sms("+18444891209", "hello")
    assert fake_lambda.calls[0]["InvocationType"] == "Event"


def test_wait_uses_request_response_and_returns_provider_id(fake_lambda):
    result = notify_mod.send_notification_sms("+18444891209", "hello", wait=True)
    assert fake_lambda.calls[0]["InvocationType"] == "RequestResponse"
    assert result.queued is True
    assert result.provider_message_id == "prov-1"


def test_wait_surfaces_the_senders_own_error(monkeypatch):
    client = _FakeLambda(sync_status=422,
                         sync_body={"error": "MISSING_DLT_TEMPLATE", "errorCode": "MISSING_DLT_TEMPLATE"})
    monkeypatch.setattr(notify_mod, "_lambda_client", lambda: client)
    result = notify_mod.send_notification_sms("+919903300044", "hello", wait=True)
    assert result.queued is False
    assert "MISSING_DLT_TEMPLATE" in result.error


# --------------------------------------------------------------------------
# never raise into a webhook handler
# --------------------------------------------------------------------------
def test_transport_failure_returns_a_result_and_does_not_raise(monkeypatch):
    client = _FakeLambda(raise_with=RuntimeError("lambda unavailable"))
    monkeypatch.setattr(notify_mod, "_lambda_client", lambda: client)
    result = notify_mod.send_notification_sms("+18444891209", "hello")
    assert result.queued is False
    assert "RuntimeError" in result.error


@pytest.mark.parametrize("phone", ["", "abc", None])
def test_invalid_destination_is_skipped_without_invoking(fake_lambda, phone):
    result = notify_mod.send_notification_sms(phone, "hello")
    assert result.queued is False
    assert result.skipped_reason == "invalid_phone"
    assert fake_lambda.calls == []


def test_empty_content_is_skipped_without_invoking(fake_lambda):
    result = notify_mod.send_notification_sms("+18444891209", "")
    assert result.queued is False
    assert result.skipped_reason == "empty_content"
    assert fake_lambda.calls == []


# --------------------------------------------------------------------------
# region override is passed through, not decided here
# --------------------------------------------------------------------------
def test_region_override_is_forwarded(fake_lambda):
    notify_mod.send_notification_sms("+919903300044", "hi",
                                     dlt_template_key="ivr-default",
                                     override_region="ap-south-1")
    assert _parsed_body(fake_lambda.calls[0])["region"] == "ap-south-1"


def test_no_region_is_asserted_by_default(fake_lambda):
    """Region selection belongs to SmsRegionResolver, not to the caller."""
    notify_mod.send_notification_sms("+919903300044", "hi", dlt_template_key="ivr-default")
    assert "region" not in _parsed_body(fake_lambda.calls[0])
