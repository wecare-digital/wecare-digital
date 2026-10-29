"""The WhatsApp templates this platform sends, in one place.

Purpose
-------
Template names used to be string literals scattered across checkout, the invoice engine, outbound
and the Flow modules. A literal that drifts from the approved Meta name fails only at send time,
on a customer's payment. This module is the single home for the names, languages and component
shapes the senders rely on, so a send, a readiness check and a release audit all read the same
values.

Authority
---------
Meta is the authority on whether a template is APPROVED. This module is the authority on which
template each business step uses and what components that step must supply. Senders still prove
approval with a live readback before a money-path send; nothing here can enable a send on its own.

The live set (WABA1 `2094615664435155`, verified by the owner and the 2026-10-25 readback, plus
`wecare_vault_request_ready` read back APPROVED on 2026-10-28; all eight `en`).
`scripts/check_whatsapp_template_payloads_live.py` builds each send with
the production code and checks it against these live definitions:

    PAY            wecare_whatapp_native_pay_template     UTILITY, IMAGE header, ORDER_DETAILS button
    INVOICE        wecare_default_invoice_image_template  UTILITY, IMAGE header, FLOW button index 0
                                                          (NAVIGATE to FEEDBACK of Flow 993862443003108)
    ORDER_STATUS   wecare_order_status_v3                 UTILITY / ORDER_STATUS, order_status component
    OTP            wecare_otp                             AUTHENTICATION, copy-code URL button index 0
    LEAVE_REVIEW   wecare_leave_review                    IMAGE header, FLOW button index 0 (same Flow);
                                                          manual only: never sent by automation
    DOWNLOAD       wecare_default_download                IMAGE header, URL button index 0
                                                          (`/vault/?file={{1}}`, Vault digital delivery)
    LOCATION_PIN   wecare_location_share_pin              LOCATION header, manual only
    VAULT_OFFER    wecare_vault_request_ready             LEGACY compatibility only for already-sent
                                                          QUICK_REPLY "Unlock Vault" messages
    SUBMIT_FLOW    submit_request_flow                    UTILITY, IMAGE header, FLOW button
    AMEND_FLOW     request_amendment_flow                 UTILITY, IMAGE header, FLOW button
    DROP_DOCS_FLOW _dropdoc_flow                          UTILITY, IMAGE header, FLOW button
    PICKUP_FLOW    pickup_request_flow                    UTILITY, IMAGE header, FLOW button
    TRACK_FLOW     track_ship_flow                        UTILITY, IMAGE header, FLOW button

`wecare_whatapp_native_pay_template` is the real approved spelling ("whatapp"); do not "fix" it.

The post-payment contract
-------------------------
After a verified WhatsApp ORDER_DETAILS payment the customer receives, in order:

    1. ORDER_STATUS `processing` ("Payment received.") through the approved
       wecare_order_status_v3 template.
    2. ORDER_STATUS `completed` ("Payment complete.") through the same template, only after
       processing was accepted or already recorded.
    3. INVOICE, once, with the paid-invoice PNG in its header and an order-bound review token on
       its FLOW button.

    There is no interactive order_status fallback. Temporary template unavailability is deferred
    and retried by the payment rail; invoice delivery remains independently idempotent. Workspace
    does not manually send these payment-order states. Shipment/service fulfilment is a separate
    OrderTable / Track Order concern.

`POST_PAYMENT_FORBIDDEN` lists templates no post-payment automation may send.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple


@dataclass(frozen=True)
class Template:
    """One approved template and the shape every send of it must have."""

    name: str
    language: str
    category: str
    header: Optional[str] = None
    buttons: Tuple[str, ...] = field(default_factory=tuple)
    sub_category: str = ""
    #: False for templates staff may send by hand but no automated path may send.
    automated: bool = True


#: The one WhatsApp payment template. Env-overridable with the key the senders already carry, so
#: a re-registration on Meta needs no code deploy and the gate and the send read one value.
PAY = Template(
    name=os.environ.get("WA_PAY_TEMPLATE", "wecare_whatapp_native_pay_template"),
    language="en", category="UTILITY", header="image", buttons=("order_details",))

#: The paid GST invoice. Meta rejects it (131009) when the FLOW button component is missing.
INVOICE = Template(
    name=os.environ.get("WA_INVOICE_TEMPLATE", "wecare_default_invoice_image_template"),
    language="en", category="UTILITY", header="image", buttons=("flow",))

#: Fulfilment updates outside the customer-service window. Inside the window the interactive
#: `order_status` message is used instead and needs no template. `_v3` because Meta still holds
#: the deleted `_v2` name (error_subcode 2388023 refuses new English content under it).
ORDER_STATUS = Template(
    name=os.environ.get("WA_ORDER_STATUS_TEMPLATE", "wecare_order_status_v3"),
    language="en", category="UTILITY", sub_category="ORDER_STATUS")

#: Website sign-in and registration. `customer-whatsapp-auth` is packaged standalone and keeps
#: its own copy of this name; `OTP_TEMPLATE_NAME` is the env key both read.
OTP = Template(name=os.environ.get("OTP_TEMPLATE_NAME", "wecare_otp"),
               language="en", category="AUTHENTICATION", buttons=("url",))

# LEAVE_REVIEW and LOCATION_PIN are manual Inbox sends. DOWNLOAD is sent by Vault delivery
# through `download_send_fields` below; its IMAGE header must travel with every send.
LEAVE_REVIEW = Template(name="wecare_leave_review", language="en", category="UTILITY",
                        header="image", buttons=("flow",), automated=False)
DOWNLOAD = Template(name="wecare_default_download", language="en", category="UTILITY",
                    header="image", buttons=("url",))
LOCATION_PIN = Template(name="wecare_location_share_pin", language="en", category="UTILITY",
                        header="location", automated=False)
#: Legacy compatibility for Vault offers that were sent before direct native Review & Pay became
#: the default staff rail. Existing QUICK_REPLY "Unlock Vault" taps still resolve their bound file,
#: but new staff sends go straight to PAY and do not emit this template. Keep the registry entry
#: while old WhatsApp messages may still be tapped.
VAULT_OFFER = Template(name="wecare_vault_request_ready", language="en", category="UTILITY",
                       header="image", buttons=("quick_reply",))
SUBMIT_FLOW = Template(name="submit_request_flow", language="en", category="UTILITY",
                       header="image", buttons=("flow",))
AMEND_FLOW = Template(name="request_amendment_flow", language="en", category="UTILITY",
                      header="image", buttons=("flow",))
DROP_DOCS_FLOW = Template(name="_dropdoc_flow", language="en", category="UTILITY",
                          header="image", buttons=("flow",))
PICKUP_FLOW = Template(name="pickup_request_flow", language="en", category="UTILITY",
                       header="image", buttons=("flow",))
TRACK_FLOW = Template(name="track_ship_flow", language="en", category="UTILITY",
                      header="image", buttons=("flow",))

PAID_SERVICE_FLOW_TEMPLATES = {
    "submit_request": SUBMIT_FLOW,
    "amend_request": AMEND_FLOW,
    "drop_docs": DROP_DOCS_FLOW,
    "request_pickup": PICKUP_FLOW,
}

ALL: Tuple[Template, ...] = (PAY, INVOICE, ORDER_STATUS, OTP, LEAVE_REVIEW, DOWNLOAD,
                             LOCATION_PIN, VAULT_OFFER, SUBMIT_FLOW, AMEND_FLOW,
                             DROP_DOCS_FLOW, PICKUP_FLOW, TRACK_FLOW)

#: Templates no post-payment automation may send. The invoice's own FLOW button is the only
#: review entry point, and there is no separate confirmation or review follow-up.
POST_PAYMENT_FORBIDDEN: FrozenSet[str] = frozenset({LEAVE_REVIEW.name})


def by_name(name: str) -> Optional[Template]:
    """The registered template with this exact name, or None."""
    wanted = str(name or "").strip()
    return next((template for template in ALL if template.name == wanted), None)


#: The brand image the Vault templates carry in their IMAGE header, served publicly.
VAULT_HEADER_IMAGE = "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"


def download_send_fields(file_id: str) -> dict:
    """The outbound-whatsapp request fields for one DOWNLOAD send of a Vault file.

    The live template has an IMAGE header, a body with no variables and URL button 0
    `https://wecare.digital/vault/?file={{1}}`, so a send carries exactly the header and the file
    id as the button suffix. The header goes in `templateHeaderMedia`/`templateHeaderType`, the
    keys outbound's generic template builder reads: it honours `headerImageUrl` only on the
    ORDER_DETAILS checkout path, and Meta refuses a send that omits a media header.

    Shared by paid delivery and the paid-file refresh, so the two cannot drift apart.
    """
    return {"isTemplate": True, "templateName": DOWNLOAD.name, "templateParams": [],
            "templateHeaderMedia": VAULT_HEADER_IMAGE, "templateHeaderType": "image",
            "templateUrlButton": {"index": 0, "suffix": file_id}}


#: What a tap on the offer's "Unlock Vault" button sends back as `button.payload`. The inbound
#: worker routes only this prefix to `catalogService.unlock`.
VAULT_OFFER_PAYLOAD_PREFIX = "vaultoffer:"


def vault_offer_document_name(raw: object) -> str:
    """The document name as the offer's body {{1}}: one line, at most 60 characters.

    Meta refuses a text parameter holding a newline, a tab or more than four spaces in a row
    (132018), and the body wraps {{1}} in *bold*, so emphasis marks would break it.
    """
    text = "".join(ch if ch.isprintable() else " " for ch in str(raw or ""))
    text = " ".join(text.replace("*", "").replace("_", " ").replace("~", "").split())
    return text[:60].rstrip() or "Your document"


def paid_service_flow_send_fields(capability: str, flow_token: str,
                                  order_number: str) -> dict:
    """Fields for one paid single-order service launcher.

    The visible body value and the Flow action data are derived from the same verified public
    Order Number. The caller must have recorded the Flow session before invoking the sender.
    """
    key = str(capability or "").strip()
    template = PAID_SERVICE_FLOW_TEMPLATES.get(key)
    token = str(flow_token or "").strip()
    order = str(order_number or "").strip().upper()
    if template is None:
        raise ValueError("Unknown paid service Flow capability")
    if not token:
        raise ValueError("Paid service Flow token required")
    if not order.startswith("WD-ORD-"):
        raise ValueError("Paid service Order Number required")

    if key in ("submit_request", "amend_request"):
        action_data = {"selected_target": "order:" + order}
    elif key in ("drop_docs", "request_pickup"):
        action_data = {"parent_order": order, "manual_order_number": ""}
    else:
        raise ValueError("Unsupported paid service Flow capability")

    return {
        "isTemplate": True,
        "templateName": template.name,
        "templateParams": [template.language, order],
        "templateHeaderMedia": VAULT_HEADER_IMAGE,
        "templateHeaderType": "image",
        "templateFlowButton": {
            "index": 0,
            "flowToken": token,
            "flowActionData": action_data,
        },
    }


def drop_docs_flow_send_fields(flow_token: str, order_number: str = "") -> dict:
    """Compatibility wrapper for F003 callers.

    New single-order callers pass the verified Order Number. Legacy ServiceRequests callers still
    launch through SELECT_TARGET and therefore omit it.
    """
    if order_number:
        return paid_service_flow_send_fields("drop_docs", flow_token, order_number)
    token = str(flow_token or "").strip()
    if not token:
        raise ValueError("Drop Docs Flow token required")
    return {
        "isTemplate": True,
        "templateName": DROP_DOCS_FLOW.name,
        "templateParams": [DROP_DOCS_FLOW.language],
        "templateHeaderMedia": VAULT_HEADER_IMAGE,
        "templateHeaderType": "image",
        "templateFlowButton": {"index": 0, "flowToken": token},
    }


def vault_offer_send_fields(document_name: str, offer_token: str) -> dict:
    """The outbound-whatsapp request fields for one VAULT_OFFER send.

    `templateParams` leads with the language because outbound reads a short first parameter as
    the language code: a two-letter document name such as "ID" would otherwise be swallowed.
    The fixed IMAGE header and the quick-reply payload travel with every send.
    """
    return {"isTemplate": True, "templateName": VAULT_OFFER.name,
            "templateParams": [VAULT_OFFER.language, vault_offer_document_name(document_name)],
            "templateHeaderMedia": VAULT_HEADER_IMAGE, "templateHeaderType": "image",
            "templateQuickReplyButton": {"index": 0,
                                         "payload": VAULT_OFFER_PAYLOAD_PREFIX + offer_token}}


__all__ = ["Template", "PAY", "INVOICE", "ORDER_STATUS", "OTP", "LEAVE_REVIEW", "DOWNLOAD",
           "LOCATION_PIN", "VAULT_OFFER", "SUBMIT_FLOW", "AMEND_FLOW", "DROP_DOCS_FLOW",
           "PICKUP_FLOW", "TRACK_FLOW", "PAID_SERVICE_FLOW_TEMPLATES", "ALL",
           "POST_PAYMENT_FORBIDDEN", "by_name", "VAULT_HEADER_IMAGE",
           "VAULT_OFFER_PAYLOAD_PREFIX", "download_send_fields",
           "paid_service_flow_send_fields", "drop_docs_flow_send_fields",
           "vault_offer_document_name", "vault_offer_send_fields"]
