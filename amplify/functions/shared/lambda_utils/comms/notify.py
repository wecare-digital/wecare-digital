"""send_notification_sms - the one way a Lambda triggers a customer SMS.

Several call paths used to hand-roll this behavior. Each copy inlined its own
Indian-number test, DLT template id, sender id and target selection. Centralizing
the send removes transport selection from business code and gives DLT one source of truth.
reintroduced.

This module replaces all four with one call:

    from lambda_utils.comms.notify import send_notification_sms

    send_notification_sms(phone, body, dlt_template_key='ivr-default',
                          campaign='c2c-cdr', request_id=request_id)

Why invoke a Lambda rather than call AwsSmsProvider directly
------------------------------------------------------------
`AwsSmsProvider` is the real sender and `wecare-sms-aws` is the only function
that runs it. Calling the provider in-process from four more functions would mean
granting `sms-voice:SendTextMessage` to four more execution roles and giving four
more functions a direct path to the SMS API. Keeping the send behind one function
keeps least privilege intact and keeps one audit point.

This mirrors what `plivo-answer` already does, which is the reference
implementation for a compliant caller.

Asynchronous by default
-----------------------
`InvocationType='Event'`. A notification SMS is a side effect of a call or an
order; it must never extend the latency of, or fail, the thing that triggered it.
The previous synchronous path used `RequestResponse` with a 2-second sleep between two
retries, so a slow provider stalled the caller for up to 4 seconds inside a
webhook handler.

Callers that genuinely need the provider message id pass `wait=True`.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from lambda_utils.logging import get_logger, log_event

from . import numbers

logger = get_logger(__name__)

# The only SMS function. Pinned to the `live` alias: 53 of 62 functions sit
# behind one, and invoking $LATEST would bypass the published version the alias
# points at. See .kiro/steering/lambda-snapstart-deploy.md.
SMS_FUNCTION = os.environ.get("SMS_FUNCTION", "wecare-sms-aws:live")

# The route `wecare-sms-aws` dispatches on.
SMS_PATH = "/sms-aws/send"

MESSAGE_TYPE_TRANSACTIONAL = "TRANSACTIONAL"


class NotificationResult:
    """Outcome of one dispatch attempt. Never raises at the call site."""

    __slots__ = ("queued", "skipped_reason", "provider_message_id", "error", "wait")

    def __init__(self, *, queued: bool, skipped_reason: str = "",
                 provider_message_id: str = "", error: str = "",
                 wait: bool = False) -> None:
        self.queued = queued
        self.skipped_reason = skipped_reason
        self.provider_message_id = provider_message_id
        self.error = error
        self.wait = wait

    @property
    def ok(self) -> bool:
        return self.queued

    def as_dict(self) -> Dict[str, Any]:
        return {
            "queued": self.queued,
            "skippedReason": self.skipped_reason or None,
            "providerMessageId": self.provider_message_id or None,
            "error": self.error or None,
        }


def _lambda_client():
    import boto3
    return boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def build_payload(phone_e164: str, content: str, *,
                  dlt_template_key: str = "",
                  message_type: str = MESSAGE_TYPE_TRANSACTIONAL,
                  campaign: str = "",
                  override_region: str = "") -> Dict[str, Any]:
    """The synthetic API Gateway event `wecare-sms-aws` expects.

    Exposed separately so a test can assert the contract without patching boto3,
    and so there is exactly one definition of the payload shape.

    Note what is deliberately absent: `dltTemplateId`, `entityId`,
    `sourceAddress` and `apiVersion`. Callers pass a template *key*; resolving it
    to a registered template id, and attaching the entity and sender, is
    `comms.dlt`'s job. A caller that could pass a raw template id could pass an
    unapproved one.
    """
    body: Dict[str, Any] = {
        "phoneNumber": phone_e164,
        "content": content,
        "messageType": message_type,
    }
    if dlt_template_key:
        body["dltTemplateKey"] = dlt_template_key
    if campaign:
        body["campaignName"] = campaign
    if override_region:
        body["region"] = override_region
    return {
        "rawPath": SMS_PATH,
        "requestContext": {"http": {"method": "POST", "path": SMS_PATH}},
        "headers": {"origin": "https://wecare.digital"},
        "body": json.dumps(body),
    }


def send_notification_sms(phone: str, content: str, *,
                          dlt_template_key: str = "",
                          message_type: str = MESSAGE_TYPE_TRANSACTIONAL,
                          campaign: str = "",
                          override_region: str = "",
                          request_id: str = "",
                          wait: bool = False,
                          function_name: str = "") -> NotificationResult:
    """Dispatch one notification SMS through AWS End User Messaging.

    Returns a result rather than raising: every caller is a webhook or CDR handler
    where the SMS is a side effect, and none of them should fail because a
    notification could not be queued.

    An Indian destination with no `dlt_template_key` is still dispatched — the
    DLT gate lives in `comms.dlt` and refuses there, with the correct
    `MISSING_DLT_TEMPLATE` error and no send. Guessing a template here to be
    helpful is exactly the failure mode the single source of truth exists to
    prevent.
    """
    phone_e164 = numbers.to_e164(phone)
    if not phone_e164:
        log_event(logger, "notification_sms_skipped", level="warning",
                  reason="invalid_phone", requestId=request_id)
        return NotificationResult(queued=False, skipped_reason="invalid_phone")
    if not content:
        return NotificationResult(queued=False, skipped_reason="empty_content")

    target = function_name or SMS_FUNCTION
    payload = build_payload(phone_e164, content,
                            dlt_template_key=dlt_template_key,
                            message_type=message_type,
                            campaign=campaign,
                            override_region=override_region)

    try:
        response = _lambda_client().invoke(
            FunctionName=target,
            InvocationType="RequestResponse" if wait else "Event",
            Payload=json.dumps(payload).encode(),
        )
    except Exception as exc:  # noqa: BLE001 - notification must not break the caller
        log_event(logger, "notification_sms_failed", level="warning",
                  phone=phone_e164[-4:], via=target,
                  error=f"{type(exc).__name__}: {str(exc)[:160]}",
                  requestId=request_id)
        return NotificationResult(queued=False,
                                  error=f"{type(exc).__name__}: {str(exc)[:160]}")

    provider_message_id = ""
    if wait:
        provider_message_id, error = _read_sync_response(response)
        if error:
            log_event(logger, "notification_sms_rejected", level="warning",
                      phone=phone_e164[-4:], via=target, error=error[:200],
                      requestId=request_id)
            return NotificationResult(queued=False, error=error, wait=True)

    log_event(logger, "notification_sms_queued",
              phone=phone_e164[-4:], via=target,
              templateKey=dlt_template_key or None,
              campaign=campaign or None,
              isIndia=numbers.is_india(phone_e164),
              synchronous=wait, requestId=request_id)
    return NotificationResult(queued=True,
                              provider_message_id=provider_message_id, wait=wait)


def _read_sync_response(response: Dict[str, Any]) -> tuple:
    """(provider_message_id, error) from a RequestResponse invoke."""
    try:
        raw = response["Payload"].read()
        outer = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return "", f"unreadable response: {type(exc).__name__}"

    status = int(outer.get("statusCode", 0) or 0)
    try:
        body = json.loads(outer.get("body") or "{}")
    except (ValueError, TypeError):
        body = {}

    if status != 200:
        # Surface the sender's own error - notably MISSING_DLT_TEMPLATE, which a
        # caller must be able to distinguish from a transport failure.
        return "", (body.get("error") or f"sms function returned {status}")
    return str(body.get("providerMessageId") or body.get("messageId") or ""), ""


def resolve_target_function() -> str:
    """The SMS function this process will invoke. For diagnostics pages."""
    return SMS_FUNCTION
