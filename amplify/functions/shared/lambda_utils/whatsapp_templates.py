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

The live set (WABA1 `2094615664435155`, verified by the owner and the 2026-10-25 readback; all
seven APPROVED, `en`). `scripts/check_whatsapp_template_payloads_live.py` builds each send with
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

`wecare_whatapp_native_pay_template` is the real approved spelling ("whatapp"); do not "fix" it.

The post-payment contract
-------------------------
After a verified payment the customer receives, in order and nothing else:

    1. Meta order_status `processing` (WhatsApp-rail orders only; interactive inside the 24-hour
       window, the ORDER_STATUS template outside it, otherwise deferred). Bounded and
       best-effort: the invoice never depends on it succeeding.
    2. INVOICE, once, with the paid-invoice PNG in its header and an order-bound review token on
       its FLOW button.

    That is the owner-approved order (audit plan T7/D2). Later fulfilment updates are
    staff-driven.

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

ALL: Tuple[Template, ...] = (PAY, INVOICE, ORDER_STATUS, OTP, LEAVE_REVIEW, DOWNLOAD,
                             LOCATION_PIN)

#: Templates no post-payment automation may send. The invoice's own FLOW button is the only
#: review entry point, and there is no separate confirmation or review follow-up.
POST_PAYMENT_FORBIDDEN: FrozenSet[str] = frozenset({LEAVE_REVIEW.name})


def by_name(name: str) -> Optional[Template]:
    """The registered template with this exact name, or None."""
    wanted = str(name or "").strip()
    return next((template for template in ALL if template.name == wanted), None)


#: The brand image the Vault templates carry in their IMAGE header, served publicly.
VAULT_HEADER_IMAGE = "https://wecare.digital/get/o/stream/media/m/wecare-digital.png"


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


__all__ = ["Template", "PAY", "INVOICE", "ORDER_STATUS", "OTP", "LEAVE_REVIEW", "DOWNLOAD",
           "LOCATION_PIN", "ALL", "POST_PAYMENT_FORBIDDEN", "by_name", "VAULT_HEADER_IMAGE",
           "download_send_fields"]
