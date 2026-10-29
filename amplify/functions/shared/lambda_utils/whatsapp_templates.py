"""The WhatsApp templates this platform sends, in one place.

Meta is the authority on approval. This module is the source of truth for which approved
template each business step uses and for the send-time component shape. In particular, the
customer-service Flow launchers all use the same variable-free body:

    ✅ Your service is ready. Tap below to continue.

The service is identified by the FLOW button/Flow id, not by a body variable. That lets the
payment rail send one consistent launcher after the invoice without repeating an order number,
price or payment wording in the template body.

The five current service launchers are approved UTILITY templates with IMAGE headers and a
FLOW button at index 0:

    SUBMIT_REQUEST_FLOW     submit_request_flow
    REQUEST_AMENDMENT_FLOW request_amendment_flow
    DROP_DOCS_FLOW          _dropdoc_flow
    REQUEST_PICKUP_FLOW     pickup_request_flow
    TRACK_SHIPPING_FLOW     track_ship_flow

Request Pickup is registered here so inventory/readiness cannot drift, but its post-payment
runtime launch remains fail-closed until the published Flow carries the pickup-specific schema.
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
    automated: bool = True


PAY = Template(
    name=os.environ.get("WA_PAY_TEMPLATE", "wecare_whatapp_native_pay_template"),
    language="en", category="UTILITY", header="image", buttons=("order_details",))

INVOICE = Template(
    name=os.environ.get("WA_INVOICE_TEMPLATE", "wecare_default_invoice_image_template"),
    language="en", category="UTILITY", header="image", buttons=("flow",))

ORDER_STATUS = Template(
    name=os.environ.get("WA_ORDER_STATUS_TEMPLATE", "wecare_order_status_v3"),
    language="en", category="UTILITY", sub_category="ORDER_STATUS")

OTP = Template(name=os.environ.get("OTP_TEMPLATE_NAME", "wecare_otp"),
               language="en", category="AUTHENTICATION", buttons=("url",))

LEAVE_REVIEW = Template(name="wecare_leave_review", language="en", category="UTILITY",
                        header="image", buttons=("flow",), automated=False)
DOWNLOAD = Template(name="wecare_default_download", language="en", category="UTILITY",
                    header="image", buttons=("url",))
LOCATION_PIN = Template(name="wecare_location_share_pin", language="en", category="UTILITY",
                        header="location", automated=False)
VAULT_OFFER = Template(name="wecare_vault_request_ready", language="en", category="UTILITY",
                       header="image", buttons=("quick_reply",))

# Common-body customer-service Flow launchers. The body has zero parameters; only the
# server-issued Flow token is supplied at send time.
SUBMIT_REQUEST_FLOW = Template(
    name="submit_request_flow", language="en", category="UTILITY",
    header="image", buttons=("flow",))
REQUEST_AMENDMENT_FLOW = Template(
    name="request_amendment_flow", language="en", category="UTILITY",
    header="image", buttons=("flow",))
DROP_DOCS_FLOW = Template(
    name="_dropdoc_flow", language="en", category="UTILITY",
    header="image", buttons=("flow",))
REQUEST_PICKUP_FLOW = Template(
    name="pickup_request_flow", language="en", category="UTILITY",
    header="image", buttons=("flow",))
TRACK_SHIPPING_FLOW = Template(
    name="track_ship_flow", language="en", category="UTILITY",
    header="image", buttons=("flow",))

SERVICE_FLOW_TEMPLATES: Mapping[str, Template] = {
    "SUBMIT_REQUEST": SUBMIT_REQUEST_FLOW,
    "REQUEST_AMENDMENT": REQUEST_AMENDMENT_FLOW,
    "DROP_DOCS": DROP_DOCS_FLOW,
    "REQUEST_PICKUP": REQUEST_PICKUP_FLOW,
    "TRACK_SHIPPING": TRACK_SHIPPING_FLOW,
}

ALL: Tuple[Template, ...] = (
    PAY, INVOICE, ORDER_STATUS, OTP, LEAVE_REVIEW, DOWNLOAD, LOCATION_PIN, VAULT_OFFER,
    SUBMIT_REQUEST_FLOW, REQUEST_AMENDMENT_FLOW, DROP_DOCS_FLOW, REQUEST_PICKUP_FLOW,
    TRACK_SHIPPING_FLOW,
)

POST_PAYMENT_FORBIDDEN: FrozenSet[str] = frozenset({LEAVE_REVIEW.name})


def by_name(name: str) -> Optional[Template]:
    wanted = str(name or "").strip()
    return next((template for template in ALL if template.name == wanted), None)


def service_flow_template(service_code: object) -> Optional[Template]:
    """Approved common-body launcher registered for one service code."""
    return SERVICE_FLOW_TEMPLATES.get(str(service_code or "").strip().upper())


VAULT_HEADER_IMAGE = "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
FLOW_HEADER_IMAGE = VAULT_HEADER_IMAGE


def download_send_fields(file_id: str) -> dict:
    return {"isTemplate": True, "templateName": DOWNLOAD.name, "templateParams": [],
            "templateHeaderMedia": VAULT_HEADER_IMAGE, "templateHeaderType": "image",
            "templateUrlButton": {"index": 0, "suffix": file_id}}


VAULT_OFFER_PAYLOAD_PREFIX = "vaultoffer:"


def vault_offer_document_name(raw: object) -> str:
    text = "".join(ch if ch.isprintable() else " " for ch in str(raw or ""))
    text = " ".join(text.replace("*", "").replace("_", " ").replace("~", "").split())
    return text[:60].rstrip() or "Your document"


def service_flow_send_fields(service_code: object, flow_token: str) -> dict:
    """Outbound fields for a common-body service Flow launcher.

    There are deliberately no body variables. templateParams contains only the language
    selector consumed by outbound-whatsapp; the customer-specific authorization travels solely
    in the server-issued Flow token.
    """
    template = service_flow_template(service_code)
    token = str(flow_token or "").strip()
    if template is None:
        raise ValueError("Service Flow template is not registered")
    if not token:
        raise ValueError("Service Flow token required")
    return {
        "isTemplate": True,
        "templateName": template.name,
        "templateParams": [template.language],
        "templateHeaderMedia": FLOW_HEADER_IMAGE,
        "templateHeaderType": "image",
        "templateFlowButton": {"index": 0, "flowToken": token},
    }


def drop_docs_flow_send_fields(flow_token: str) -> dict:
    """Backward-compatible wrapper for the canonical Drop Docs launcher."""
    return service_flow_send_fields("DROP_DOCS", flow_token)


def vault_offer_send_fields(document_name: str, offer_token: str) -> dict:
    return {"isTemplate": True, "templateName": VAULT_OFFER.name,
            "templateParams": [VAULT_OFFER.language, vault_offer_document_name(document_name)],
            "templateHeaderMedia": VAULT_HEADER_IMAGE, "templateHeaderType": "image",
            "templateQuickReplyButton": {"index": 0,
                                         "payload": VAULT_OFFER_PAYLOAD_PREFIX + offer_token}}


__all__ = [
    "Template", "PAY", "INVOICE", "ORDER_STATUS", "OTP", "LEAVE_REVIEW", "DOWNLOAD",
    "LOCATION_PIN", "VAULT_OFFER", "SUBMIT_REQUEST_FLOW", "REQUEST_AMENDMENT_FLOW",
    "DROP_DOCS_FLOW", "REQUEST_PICKUP_FLOW", "TRACK_SHIPPING_FLOW",
    "SERVICE_FLOW_TEMPLATES", "ALL", "POST_PAYMENT_FORBIDDEN", "by_name",
    "service_flow_template", "VAULT_HEADER_IMAGE", "FLOW_HEADER_IMAGE",
    "VAULT_OFFER_PAYLOAD_PREFIX", "download_send_fields", "service_flow_send_fields",
    "drop_docs_flow_send_fields", "vault_offer_document_name", "vault_offer_send_fields",
]
