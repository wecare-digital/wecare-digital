"""SmsService - the provider-neutral SMS contract, and its one AWS implementation.

Spec §4 and §38. The rule is absolute:

    channel = SMS  ->  ALWAYS AWS End User Messaging

    India      -> ap-south-1
    everything -> us-east-1 by default, explicit override supported

SMS has one canonical transport: AWS End User Messaging.
`scripts/check-provider-policy.sh` enforces that in CI.

Why an interface at all, when there is only one provider
--------------------------------------------------------
Not for future provider-swapping - the spec forbids other SMS providers. The
interface exists because business code currently calls the AWS SDK directly from
six places, each with its own inlined country test, its own DLT handling and its
own idea of what "sent" means. §4 requires that business code no longer touch the
SDK. One seam gives one place to enforce the DLT gate, one place to pick a region,
one place to record a message, and one place a policy check can inspect.

AWS End User Messaging only
---------------------------
`pinpoint-sms-voice-v2` exclusively. Deliberately NOT supported:

  * SNS `publish` for SMS - no DLT, no delivery receipts, no origination control
  * classic Pinpoint `send_messages` - superseded, and not DLT-capable for India

Both exist in `outbound-sms/handler.py` today and both are removed by Stage 3 of
docs/migration-plan.md.

Delivery status
---------------
`get_delivery_status` and `process_delivery_receipt` are part of the contract, but
the account has **no delivery-receipt ingestion** yet: `sms-aws/handler.py` writes
`status='SENT'` optimistically and nothing updates it. Rather than pretend, the
implementation reports `UNKNOWN_NO_RECEIPTS` so a caller - or a dashboard - can
tell "we never heard" apart from "delivered". Building the event destination is
tracked as a Stage 2 gap.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional

from . import dlt as dlt_mod
from . import numbers, region as region_mod

MESSAGE_TYPE_TRANSACTIONAL = "TRANSACTIONAL"
MESSAGE_TYPE_PROMOTIONAL = "PROMOTIONAL"

# Non-India origination identity. MUST stay pinned.
#
# The account owns +14255556333, NumberType SIMULATOR, in the SAME pool as the
# real toll-free number. A simulator accepts a send and returns a MessageId
# WITHOUT delivering anything. With no explicit identity AWS may choose it, so
# international traffic silently vanishes while the API reports success. Pinning
# the pool would not help - both numbers are in it. Verified live 2026-09-19.
ORIGINATION_IDENTITY = os.environ.get(
    "AWS_SMS_DEFAULT_ORIGINATION_IDENTITY", "+18444891209")

_clients: Dict[str, Any] = {}


def _client(region: str):
    """One EUM v2 client per region, cached for the life of the sandbox."""
    if region not in _clients:
        import boto3
        _clients[region] = boto3.client("pinpoint-sms-voice-v2", region_name=region)
    return _clients[region]


class SmsResult:
    """Outcome of one send attempt."""

    __slots__ = ("success", "message_id", "provider_message_id", "provider",
                 "route", "dlt", "error", "error_code", "dry_run")

    def __init__(self, *, success: bool, message_id: str = "",
                 provider_message_id: str = "", provider: str = "aws-end-user-messaging",
                 route: Optional[region_mod.SmsRoute] = None,
                 dlt: Optional[dlt_mod.DltResolution] = None,
                 error: str = "", error_code: str = "", dry_run: bool = False) -> None:
        self.success = success
        self.message_id = message_id
        self.provider_message_id = provider_message_id
        self.provider = provider
        self.route = route
        self.dlt = dlt
        self.error = error
        self.error_code = error_code
        self.dry_run = dry_run

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "success": self.success,
            "provider": self.provider,
            "messageId": self.message_id or None,
            "providerMessageId": self.provider_message_id or None,
            "dryRun": self.dry_run,
        }
        if self.route is not None:
            out["route"] = self.route.as_dict()
        if self.dlt is not None and (self.dlt.ok or self.dlt.error):
            out["dlt"] = self.dlt.as_dict()
        if self.error:
            out["error"] = self.error
            out["errorCode"] = self.error_code or "SEND_FAILED"
        return out


class SmsService:
    """The provider-neutral contract from §4. Business code depends on this."""

    def send_sms(self, phone: str, content: str, **kwargs) -> SmsResult:
        raise NotImplementedError

    def send_transactional_sms(self, phone: str, content: str, **kwargs) -> SmsResult:
        kwargs["message_type"] = MESSAGE_TYPE_TRANSACTIONAL
        return self.send_sms(phone, content, **kwargs)

    def send_otp_sms(self, phone: str, content: str, **kwargs) -> SmsResult:
        # OTP is transactional for routing and billing. It is called out separately
        # in §4 because it must never be downgraded to promotional, which is
        # DND-scrubbed in India and would drop the OTP.
        kwargs["message_type"] = MESSAGE_TYPE_TRANSACTIONAL
        return self.send_sms(phone, content, **kwargs)

    def send_template_sms(self, phone: str, template_key: str,
                          content: str, **kwargs) -> SmsResult:
        kwargs["dlt_template_key"] = template_key
        return self.send_sms(phone, content, **kwargs)

    def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def process_delivery_receipt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class AwsSmsProvider(SmsService):
    """AWS End User Messaging (`pinpoint-sms-voice-v2`). The only SMS provider."""

    provider_name = "aws-end-user-messaging"

    def send_sms(self, phone: str, content: str, *,
                 message_type: str = MESSAGE_TYPE_TRANSACTIONAL,
                 dlt_template_key: str = "",
                 override_region: str = "",
                 dry_run: bool = False,
                 message_id: str = "",
                 **_ignored) -> SmsResult:
        phone_e164 = numbers.to_e164(phone)
        if not phone_e164:
            return SmsResult(success=False, error="invalid phone number",
                             error_code="INVALID_PHONE")
        if not content:
            return SmsResult(success=False, error="content is required",
                             error_code="MISSING_CONTENT")

        route = region_mod.resolve(phone_e164, override_region=override_region)
        message_id = message_id or str(uuid.uuid4())

        resolution = dlt_mod.DltResolution()
        if route.requires_dlt:
            resolution = dlt_mod.resolve(dlt_template_key)
            if not resolution.ok:
                # Hard stop. §6: fail safely rather than send unregistered content.
                return SmsResult(success=False, message_id=message_id, route=route,
                                 dlt=resolution, error=resolution.error,
                                 error_code="MISSING_DLT_TEMPLATE")

        params: Dict[str, Any] = {
            "DestinationPhoneNumber": phone_e164,
            "MessageBody": content,
            "MessageType": message_type,
        }
        if route.is_india:
            params["OriginationIdentity"] = dlt_mod.SENDER_ID
            country_params = resolution.country_parameters()
            if country_params:
                params["DestinationCountryParameters"] = country_params
        elif ORIGINATION_IDENTITY:
            params["OriginationIdentity"] = ORIGINATION_IDENTITY

        if dry_run:
            # Validates identity, DLT parameters and destination without delivering.
            params["DryRun"] = True

        try:
            response = _client(route.region).send_text_message(**params)
        except Exception as exc:  # noqa: BLE001
            return SmsResult(success=False, message_id=message_id, route=route,
                             dlt=resolution, dry_run=dry_run,
                             error=f"{type(exc).__name__}: {exc}",
                             error_code=type(exc).__name__)

        return SmsResult(success=True, message_id=message_id,
                         provider_message_id=response.get("MessageId", ""),
                         route=route, dlt=resolution, dry_run=dry_run)

    def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Report honestly that delivery state is not yet observable.

        There is no event destination, no SNS subscriber and no CloudWatch-logs
        consumer for pinpoint-sms-voice-v2 anywhere in this account, so nothing
        ever updates a message past 'SENT'. Returning 'DELIVERED' here, or reading
        back the optimistic row, would manufacture a fact.
        """
        return {
            "messageId": message_id,
            "status": "UNKNOWN_NO_RECEIPTS",
            "detail": (
                "AWS End User Messaging delivery receipts are not ingested in this "
                "account yet. Submission succeeded; delivery is unobserved. See "
                "docs/migration-plan.md Stage 2."
            ),
        }

    def process_delivery_receipt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise an EUM v2 delivery event into a channel-neutral status.

        Wired up once an event destination exists. Implemented now so the consumer
        has a contract to target, and so the mapping lives beside the sender rather
        than in whichever Lambda happens to receive the event.
        """
        event_type = str(payload.get("eventType") or payload.get("EventType") or "").upper()
        mapping = {
            "TEXT_DELIVERED": "delivered",
            "TEXT_SUCCESSFUL": "sent",
            "TEXT_QUEUED": "sent",
            "TEXT_PENDING": "sent",
            "TEXT_BLOCKED": "failed",
            "TEXT_CARRIER_BLOCKED": "failed",
            "TEXT_CARRIER_UNREACHABLE": "failed",
            "TEXT_INVALID": "failed",
            "TEXT_INVALID_MESSAGE": "failed",
            "TEXT_SPAM": "failed",
            "TEXT_UNREACHABLE": "failed",
            "TEXT_TTL_EXPIRED": "failed",
            "TEXT_UNKNOWN": "unknown",
        }
        return {
            "providerMessageId": (payload.get("messageId")
                                  or payload.get("MessageId") or ""),
            "status": mapping.get(event_type, "unknown"),
            "providerStatus": event_type or "UNKNOWN",
            "isoCountry": payload.get("isoCountryCode") or payload.get("IsoCountryCode"),
            "raw": event_type,
        }


_default: Optional[AwsSmsProvider] = None


def get_sms_service() -> SmsService:
    """The process-wide SmsService.

    Business code calls this rather than constructing a provider, so that no caller
    is in a position to choose a non-AWS provider even by accident.
    """
    global _default
    if _default is None:
        _default = AwsSmsProvider()
    return _default
