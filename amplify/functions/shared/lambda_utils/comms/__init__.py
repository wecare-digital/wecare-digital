"""Provider-neutral communications layer.

The seam between business code and messaging providers. Spec §37: business code
resolves a destination, a channel and a template, and this layer decides the
provider, the region and the fallback.

    numbers   E.164 normalisation and country resolution
    region    SmsRegionResolver - India -> ap-south-1, else us-east-1
    dlt       India TRAI DLT: the single source of truth for entity/sender/templates
    sms       SmsService contract + AwsSmsProvider (the only SMS provider)

Provider rules this layer exists to make unbreakable:

    SMS, every country        -> AWS End User Messaging   ONLY
    RCS India                 -> Sinch      -> fallback AWS SMS ap-south-1
    RCS non-India (eligible)   -> AWS RCS    -> fallback AWS SMS
    PSTN voice / SIP / IVR    -> Plivo
    WhatsApp                  -> Meta

Import the facade, not the SDK:

    from lambda_utils.comms import get_sms_service
    result = get_sms_service().send_transactional_sms(
        phone, body, dlt_template_key='ivr-default')
"""
from .sms import (  # noqa: F401
    AwsSmsProvider,
    MESSAGE_TYPE_PROMOTIONAL,
    MESSAGE_TYPE_TRANSACTIONAL,
    SmsResult,
    SmsService,
    get_sms_service,
)

__all__ = [
    "AwsSmsProvider",
    "MESSAGE_TYPE_PROMOTIONAL",
    "MESSAGE_TYPE_TRANSACTIONAL",
    "SmsResult",
    "SmsService",
    "get_sms_service",
]
