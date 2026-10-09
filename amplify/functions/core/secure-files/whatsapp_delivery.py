"""Send the payment request and the file itself over WhatsApp, using approved templates.

Both templates already existed and are APPROVED, which is why this path uses them
rather than creating new ones and waiting on Meta:

    wecare_pay      UTILITY  [IMAGE, BODY, FOOTER, BUTTONS(ORDER_DETAILS)]
    01_wecare_doc   UTILITY  [DOCUMENT, BODY, FOOTER, BUTTONS(FLOW)]

Two consequences of reusing them, both accepted deliberately:

* Neither BODY has variables, so neither message can name the file, the amount or the
  customer. The amount reaches the customer through the ORDER_DETAILS payload, not the
  text. The document arrives with generic wording.
* ``01_wecare_doc`` carries a stray FLOW button labelled "Subscribe", left over from
  another use. It is harmless but confusing on a paid delivery. Fixing either point
  means a new template and a Meta approval wait.

Why ORDER_DETAILS and not a Razorpay link
-----------------------------------------
The approved payment template's button is ``ORDER_DETAILS``, which is WhatsApp Pay's
native checkout. A URL button would have been needed for a Razorpay payment link, and
this template does not have one. So the payment path is WhatsApp Pay, which
``payments/invoice-engine`` already builds - the order_details shape here is copied
from it rather than invented.

Why the document goes via a media id
------------------------------------
Meta must be able to fetch what it attaches. The gated objects are private and the
whole ``secure/`` prefix is refused at the edge, so there is no URL to give Meta. The
bytes are therefore uploaded to Meta first, through
``wecare-whatsapp-business-api``'s ``/wa-business/media`` route with ``s3Key`` +
``s3Bucket``, and the resulting media id is what the template header carries.

Passing the bytes inline as base64 would have been simpler and is wrong: a synchronous
Lambda invoke payload is capped at 6MB and base64 adds about a third, so anything over
roughly 4.4MB would fail - well under the 100MB documents Meta accepts.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Optional, Tuple

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")

SENDER_FUNCTION = os.environ.get("WA_SENDER_FUNCTION", "wecare-outbound-whatsapp")
MEDIA_FUNCTION = os.environ.get(
    "WA_MEDIA_FUNCTION", "wecare-whatsapp-business-api:live"
)
PAY_TEMPLATE = os.environ.get("WA_PAY_TEMPLATE", "wecarepay_wa")

# Defaults to the older approved template so delivery never depends on an approval
# that has not landed. `wd_file_delivery` was submitted to replace it - it has BODY
# variables for the customer and file name, and no stray "Subscribe" button - and
# takes over the moment this env var is pointed at it. Nothing else needs changing:
# the body-parameter shape below is chosen from the template name.
DOC_TEMPLATE = os.environ.get("WA_DOC_TEMPLATE", "wd_file_delivery")
# Templates whose BODY carries {{1}} customer name and {{2}} file name. Keyed by name
# rather than by a flag, so pointing WA_DOC_TEMPLATE at one cannot desynchronise from
# the parameters it is sent.
TEMPLATES_WITH_BODY_VARS = {"wd_file_delivery"}
#: Meta's OWN phone-number id. Correct for the business-API `/wa-business/media` route below,
#: which is addressed in Meta's vocabulary — and WRONG for every `phoneNumberId` passed to
#: `wecare-outbound-whatsapp`, which is why `WA_SEND_PHONE_ID` exists beside it.
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1016149501586345")

#: The AWS-style sender id `outbound-whatsapp` requires, for the three sends that go there.
#:
#: Every WhatsApp send from this function was STRUCTURALLY BROKEN before this constant existed:
#: all three passed the bare Meta id above as `phoneNumberId`, and
#: `outbound-whatsapp._resolve_meta_phone_id` accepts only an AWS-style id (its map, or a
#: `-direct-<digits>` suffix) and otherwise raises rather than falling back to another WABA. A
#: bare Meta id matches neither. Independently, the payment one was refused a second time by
#: `PAYMENT_SENDERS`. It went unnoticed because this function records zero invocations and
#: `SECURE_FILES_PAYMENT_ENABLED` is "false".
#:
#: This makes the surface CORRECT, not ENABLED. The payment flag stays "false"; turning it on is
#: an owner action.
WA_SEND_PHONE_ID = os.environ.get(
    "WA_SEND_PHONE_ID", "phone-number-id-waba1-direct-1016149501586345")

BUCKET = os.environ.get("SECURE_FILES_BUCKET", "wecare-digital-get")
# Reused from the invoice flow so the payment card carries the same branding.
HEADER_IMAGE = os.environ.get(
    "WA_PAY_HEADER_IMAGE",
    "https://wecare.digital/get/o/stream/media/m/wecare-digital.png",
)

_lambda = None


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


def _invoke(function_name: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Call another Lambda and return (httpStatus, parsedBody)."""
    response = _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = response["Payload"].read()
    result = json.loads(raw.decode("utf-8")) if raw else {}

    if response.get("FunctionError"):
        return 500, {"error": "invoked function raised"}

    status = int(result.get("statusCode") or 0)
    body = result.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"raw": body[:200]}
    return status, (body if isinstance(body, dict) else {})


def reference_id() -> str:
    """A reference the Razorpay webhook can correlate back to this download.

    `WD-FILE-` rather than the invoice flow's `WD-PAY-`, so a file download is
    distinguishable from an invoice payment in the webhook log without having to look
    anything up.
    """
    return f"WD-FILE-{uuid.uuid4().hex[:8].upper()}"


def send_payment_request(
    *,
    phone: str,
    file_row: Dict[str, Any],
    grant_id: str,
    order_id: str,
    reference: str,
) -> Tuple[bool, str]:
    """Send the wecare_pay template with an ORDER_DETAILS payload. Returns (ok, detail).

    ``type`` is ``digital-goods`` deliberately: physical-goods makes WhatsApp collect a
    delivery address, which is nonsense for a file and was a real bug in the invoice
    flow. digital-goods omits ``shipping_info`` entirely, so no address is requested.
    """
    amount_paise = int(file_row.get("pricePaise") or 0)
    if amount_paise <= 0:
        return False, "no price on this file"

    item_name = str(file_row.get("displayName") or "Document")[:60]

    order_details = {
        "reference_id": reference,
        "type": "digital-goods",
        # payment_configuration is left out on purpose: outbound-whatsapp resolves it
        # per phone number and falls back to DEFAULT_PAYMENT_CONFIG. Hardcoding a name
        # here would silently diverge the moment that mapping changes.
        "currency": "INR",
        "itemName": item_name,
        "quantity": 1,
        "orderId": order_id,
        "total_amount": {"value": amount_paise, "offset": 100},
        "order": {
            "status": "pending",
            "items": [
                {
                    "name": item_name,
                    "quantity": 1,
                    "amount": {"value": amount_paise, "offset": 100},
                }
            ],
            "subtotal": {"value": amount_paise, "offset": 100},
        },
    }

    status, body = _invoke(
        SENDER_FUNCTION,
        {
            "body": json.dumps(
                {
                    "recipientPhone": phone,
                    "phoneNumberId": WA_SEND_PHONE_ID,
                    "isTemplate": True,
                    "isCheckoutTemplate": True,
                    "templateName": PAY_TEMPLATE,
                    # wecare_pay has no body variables; the amount travels in
                    # checkoutOrderDetails, not in the text.
                    "templateParams": [],
                    "checkoutOrderDetails": order_details,
                    "headerImageUrl": HEADER_IMAGE,
                }
            )
        },
    )
    if status >= 300:
        return False, f"sender returned HTTP {status}"
    return True, str(body.get("messageId") or body.get("id") or "sent")


def upload_to_meta(file_row: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Put the deliverable rendition on Meta's media endpoint. Returns (mediaId, detail).

    Reads ``deliveryKey`` (the ``secure/d/`` object), never ``s3Key``. The two differ:
    ``s3Key`` is the original of any type, ``deliveryKey`` is the PDF or image that can
    actually be opened on a handset.
    """
    delivery_key = file_row.get("deliveryKey") or ""
    if not delivery_key:
        return None, "file has no deliverable rendition"

    status, body = _invoke(
        MEDIA_FUNCTION,
        {
            "httpMethod": "POST",
            "path": "/wa-business/media",
            "body": json.dumps(
                {
                    "phoneId": META_PHONE_NUMBER_ID,
                    # By reference, not inline: base64 through an invoke payload caps
                    # near 4.4MB and would break large documents.
                    "s3Bucket": BUCKET,
                    "s3Key": delivery_key,
                    "contentType": file_row.get("contentType") or "application/pdf",
                    "filename": str(file_row.get("originalFilename") or "document.pdf"),
                }
            ),
        },
    )
    if status >= 300:
        return None, f"media upload returned HTTP {status}"
    media_id = str(body.get("mediaId") or "")
    return (media_id, "uploaded") if media_id else (None, "no mediaId returned")


def send_document(*, phone: str, file_row: Dict[str, Any]) -> Tuple[bool, str]:
    """Deliver the file as a WhatsApp document via the approved template."""
    media_id, detail = upload_to_meta(file_row)
    if not media_id:
        return False, detail

    # Only the purpose-built template can say who the customer is and what the file is
    # called. Sending these to a template without the placeholders is rejected by Meta
    # as a parameter mismatch, so the two must move together - hence keying off the
    # template name rather than a separate switch.
    if DOC_TEMPLATE in TEMPLATES_WITH_BODY_VARS:
        template_params = [
            str(file_row.get("ownerName") or "there")[:60],
            str(file_row.get("displayName") or "your file")[:60],
        ]
    else:
        template_params = []

    status, body = _invoke(
        SENDER_FUNCTION,
        {
            "body": json.dumps(
                {
                    "recipientPhone": phone,
                    "phoneNumberId": WA_SEND_PHONE_ID,
                    "isTemplate": True,
                    "templateName": DOC_TEMPLATE,
                    "templateParams": template_params,
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "document",
                                    "document": {
                                        "id": media_id,
                                        "filename": str(
                                            file_row.get("originalFilename")
                                            or "document.pdf"
                                        ),
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        },
    )
    if status >= 300:
        return False, f"sender returned HTTP {status}"
    return True, str(body.get("messageId") or body.get("id") or "sent")


def send_download_link(*, phone: str, file_row: Dict[str, Any], url: str) -> Tuple[bool, str]:
    """Fallback for files WhatsApp cannot show inline.

    A plain text message, which needs an open 24-hour customer service window. Paying
    is a customer interaction, so the window is open immediately after payment - which
    is the only moment this is called.
    """
    name = str(file_row.get("displayName") or "your file")
    status, body = _invoke(
        SENDER_FUNCTION,
        {
            "body": json.dumps(
                {
                    "recipientPhone": phone,
                    "phoneNumberId": WA_SEND_PHONE_ID,
                    "message": (
                        f"Thank you. Your file {name} is ready.\n\n{url}\n\n"
                        "This link is valid for a short time and can be used once."
                    ),
                }
            )
        },
    )
    if status >= 300:
        return False, f"sender returned HTTP {status}"
    return True, str(body.get("messageId") or "sent")
