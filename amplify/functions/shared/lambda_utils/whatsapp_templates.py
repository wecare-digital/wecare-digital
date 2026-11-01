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

The WABA1 live set has 15 approved `en` templates as of 2026-11-01. The retired Vault offer has no current Meta approval.
`scripts/check_whatsapp_template_payloads_live.py` builds each send with
the production code and checks it against these live definitions:

    PAY            wecare_whatapp_native_pay_template     UTILITY, IMAGE header, ORDER_DETAILS button
    INVOICE        wecare_default_invoice_image_template  UTILITY, IMAGE header, FLOW button index 0
                                                          (DATA_EXCHANGE -> static FEEDBACK INIT, F002 Flow 993862443003108)
    ORDER_STATUS   wecare_order_status_v3                 UTILITY / ORDER_STATUS, order_status component
    OTP            wecare_otp                             AUTHENTICATION, copy-code URL button index 0
    LEAVE_REVIEW   wecare_leave_review                    IMAGE header, FLOW button index 0 (same Flow);
                                                          manual only: never sent by automation
    REFERRAL       wecare_referal_update                  IMAGE header, FLOW button index 0 (F008);
                                                          customer-initiated only
    DOWNLOAD       wecare_default_download                IMAGE header, URL button index 0
                                                          (`/vault/?file={{1}}`, Vault digital delivery)
    LOCATION_PIN   wecare_location_share_pin              LOCATION header, manual only
    PDF_DOWNLOAD   wecare_pdf_direct_download             DOCUMENT header, FLOW button index 0; manual only
    SUBMIT_REQUEST_FLOW     submit_request_flow           UTILITY, IMAGE header, FLOW button index 0
    REQUEST_AMENDMENT_FLOW request_amendment_flow          UTILITY, IMAGE header, FLOW button index 0
    DROP_DOCS_FLOW          _dropdoc_flow                  UTILITY, IMAGE header, FLOW button index 0
    REQUEST_PICKUP_FLOW     pickup_request_flow            UTILITY, IMAGE header, FLOW button index 0
    TRACK_SHIPPING_FLOW     track_ship_flow                UTILITY, IMAGE header, FLOW button index 0

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
from typing import FrozenSet, Mapping, Optional, Tuple


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
REFERRAL = Template(name="wecare_referal_update", language="en", category="UTILITY",
                    header="image", buttons=("flow",), automated=False)
DOWNLOAD = Template(name="wecare_default_download", language="en", category="UTILITY",
                    header="image", buttons=("url",))
LOCATION_PIN = Template(name="wecare_location_share_pin", language="en", category="UTILITY",
                        header="location", automated=False)
PDF_DOWNLOAD = Template(name="wecare_pdf_direct_download", language="en", category="UTILITY",
                        header="document", buttons=("flow",), automated=False)
PROFILE_DETAILS = Template(name="service_details", language="en", category="UTILITY",
                           header="image", buttons=("flow",))
#: Historical signed-tap definition only. Do not send new Vault offers.
VAULT_OFFER = Template(name="wecare_vault_request_ready", language="en", category="UTILITY",
                       header="image", buttons=("quick_reply",), automated=False)
SUBMIT_REQUEST_FLOW = Template(name="submit_request_flow", language="en", category="UTILITY",
                               header="image", buttons=("flow",))
REQUEST_AMENDMENT_FLOW = Template(name="request_amendment_flow", language="en", category="UTILITY",
                                  header="image", buttons=("flow",))
DROP_DOCS_FLOW = Template(name="_dropdoc_flow", language="en", category="UTILITY",
                          header="image", buttons=("flow",))
REQUEST_PICKUP_FLOW = Template(name="pickup_request_flow", language="en", category="UTILITY",
                               header="image", buttons=("flow",))
TRACK_SHIPPING_FLOW = Template(name="track_ship_flow", language="en", category="UTILITY",
                               header="image", buttons=("flow",))

SERVICE_FLOW_TEMPLATES: Mapping[str, Template] = {
    "SUBMIT_REQUEST": SUBMIT_REQUEST_FLOW,
    "REQUEST_AMENDMENT": REQUEST_AMENDMENT_FLOW,
    "DROP_DOCS": DROP_DOCS_FLOW,
    "REQUEST_PICKUP": REQUEST_PICKUP_FLOW,
    "TRACK_SHIPPING": TRACK_SHIPPING_FLOW,
}

ALL: Tuple[Template, ...] = (
    PAY, INVOICE, ORDER_STATUS, OTP, LEAVE_REVIEW, REFERRAL, DOWNLOAD, LOCATION_PIN, PDF_DOWNLOAD, PROFILE_DETAILS,
    SUBMIT_REQUEST_FLOW, REQUEST_AMENDMENT_FLOW, DROP_DOCS_FLOW, REQUEST_PICKUP_FLOW,
    TRACK_SHIPPING_FLOW,
)

#: Meta-approved WABA1 / en template-version IDs, verified 2026-10-30. These
#: are lookup/audit metadata: senders must use the template name and required
#: components; a stored ID is not proof that Meta still permits sending.
APPROVED_TEMPLATE_IDS: Mapping[str, str] = {
    "track_ship_flow": "1107523855531222",
    "pickup_request_flow": "1449099850671553",
    "_dropdoc_flow": "1041974032198332",
    "request_amendment_flow": "4034771700165582",
    "submit_request_flow": "30181571061431980",
    "service_details": "2419125382263851",
    "wecare_pdf_direct_download": "1428669922724280",
    "wecare_location_share_pin": "1628859001974131",
    "wecare_default_download": "1410998911012572",
    "wecare_whatapp_native_pay_template": "2714938845570815",
    "wecare_leave_review": "1801972550682516",
    "wecare_referal_update": "1596216325046969",
    "wecare_default_invoice_image_template": "1782246473079550",
    "wecare_order_status_v3": "1754227779211208",
    "wecare_otp": "1292079089453029",
}


#: Templates no post-payment automation may send. The invoice's own FLOW button is the only
#: review entry point, and there is no separate confirmation or review follow-up.
POST_PAYMENT_FORBIDDEN: FrozenSet[str] = frozenset({LEAVE_REVIEW.name, REFERRAL.name})


def by_name(name: str) -> Optional[Template]:
    """The registered template with this exact name, or None."""
    wanted = str(name or "").strip()
    return next((template for template in ALL if template.name == wanted), None)


def service_flow_template(service_code: object) -> Optional[Template]:
    """The common-body Flow launcher registered for one service code."""
    return SERVICE_FLOW_TEMPLATES.get(str(service_code or "").strip().upper())


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


def service_flow_send_fields(service_code: object, flow_token: str,
                             flow_action_data: Optional[dict] = None) -> dict:
    """Outbound fields for a common-body service Flow launcher.

    The approved body has zero customer variables. Authorization stays in the server-issued
    Flow token. When a paid service already has one verified existing order, flow_action_data
    supplies only that server-derived order context so the Flow can open after the redundant
    target-picker screen. No browser-supplied value is forwarded here.
    """
    template = service_flow_template(service_code)
    token = str(flow_token or '').strip()
    if template is None:
        raise ValueError("Service Flow template is not registered")
    if not token:
        raise ValueError("Service Flow token required")
    button = {"index": 0, "flowToken": token}
    if flow_action_data:
        button["flowActionData"] = dict(flow_action_data)
    return {"isTemplate": True, "templateName": template.name,
            "templateParams": [template.language],
            "templateHeaderMedia": VAULT_HEADER_IMAGE, "templateHeaderType": "image",
            "templateFlowButton": button}
def drop_docs_flow_send_fields(flow_token: str) -> dict:
    """Backward-compatible wrapper for the canonical paid F003 launcher."""
    return service_flow_send_fields("DROP_DOCS", flow_token)


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


__all__ = ["Template", "PAY", "INVOICE", "ORDER_STATUS", "OTP", "LEAVE_REVIEW", "REFERRAL", "DOWNLOAD",
           "LOCATION_PIN", "PDF_DOWNLOAD", "PROFILE_DETAILS", "VAULT_OFFER", "SUBMIT_REQUEST_FLOW", "REQUEST_AMENDMENT_FLOW",
           "DROP_DOCS_FLOW", "REQUEST_PICKUP_FLOW", "TRACK_SHIPPING_FLOW",
           "SERVICE_FLOW_TEMPLATES", "ALL", "APPROVED_TEMPLATE_IDS", "POST_PAYMENT_FORBIDDEN", "by_name",
           "service_flow_template", "VAULT_HEADER_IMAGE", "VAULT_OFFER_PAYLOAD_PREFIX",
           "download_send_fields", "service_flow_send_fields", "drop_docs_flow_send_fields",
           "vault_offer_document_name", "vault_offer_send_fields"]
