"""Channel-aware payability for a stored delivery address — the tax/settlement rules that
used to live inside `contact_address.normalize_for_storage`, moved to PAYMENT TIME.

WHY THIS MODULE EXISTS
----------------------
`contact_address` owns the ONE stored address shape and now validates only *structure*
(FEAT-003): required fields, lengths, a real country code, a resolvable owned-address.
Storage is international — any valid address is accepted and kept.

Whether that stored address can actually take money is a *channel* question, answered here,
at the moment a payment is attempted:

- **Website / Razorpay** (`WEBSITE_RAZORPAY`): the address must map to the normalized delivery shape
  (`india_address.to_delivery_address`), which for India requires a resolvable subdivision and for
  every other country requires an ISO 3166-2 state. India additionally requires a six-digit
  PIN, because the delivery address is the place of supply and decides the CGST/SGST split on
  an invoice carrying a real GSTIN — a wrong split is a silently-wrong total, not a loud error.
- **WhatsApp order_details** (`WHATSAPP_ORDER_DETAILS`): India only. Meta's India payment
  configuration settles INR against MCC 7392 / purpose code 03, so a non-India beneficiary
  cannot settle on that surface and is refused outright rather than sent and bounced at Meta.

Moving the rules here is what lets the CRM accept an international address while a payment
fails closed if the stored address does not meet the PAYING channel's rule. There is exactly
one exception type a caller must handle — `UnpayableAddress` — mirroring
`contact_address.UnusableAddress` so a form can still mark one input.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from lambda_utils.ecommerce import india_address as india_address  # neutral home; alias keeps call sites
from lambda_utils.identity import address as owned_address

#: The website Razorpay checkout surface.
WEBSITE_RAZORPAY = "website_razorpay"
#: The WhatsApp order_details / native-payment surface (India only).
WHATSAPP_ORDER_DETAILS = "whatsapp_order_details"

#: India's six-digit PIN, moved here from `contact_address` (it is a payment rule, not a
#: storage rule). First digit 1-9, five more digits.
import re as _re  # local, so the module's public surface stays the two channels + functions
_INDIA_PIN_RE = _re.compile(r"^[1-9][0-9]{5}$")

#: Meta beneficiary length bounds, matching the block in outbound-whatsapp.
_META_NAME_MAX = 200
_META_LINE_MAX = 100
_META_POSTAL_MAX = 6


class UnpayableAddress(ValueError):
    """A structurally-valid stored address that cannot take money on the given channel.

    Mirrors `contact_address.UnusableAddress`: carries a machine `code` and, when one is
    attributable, the `field` that failed, so a caller has ONE exception type to catch and a
    form can mark one input. Raised `from None` at every site so no botocore/other text leaks.
    """

    def __init__(self, code: str, field: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.field = field


def _country_code(address: Dict[str, Any]) -> str:
    return (address.get("countryCode") or owned_address.DEFAULT_COUNTRY_CODE).upper()[:2]


def assert_payable(address: Dict[str, Any], *, channel: str) -> None:
    """Raise `UnpayableAddress` if `address` cannot take money on `channel`. Else return None.

    `address` is the stored, structurally-valid owned-address shape
    (`contact_address.normalize_for_storage`'s output). This asks only the channel/tax
    question; it does not re-validate structure.
    """
    if not isinstance(channel, str) or channel not in {WEBSITE_RAZORPAY, WHATSAPP_ORDER_DETAILS}:
        raise UnpayableAddress("UNKNOWN_CHANNEL", "")

    cc = _country_code(address)

    if cc == owned_address.DEFAULT_COUNTRY_CODE:
        # India, on EITHER channel: six-digit PIN and a resolvable subdivision.
        if not _INDIA_PIN_RE.match(str(address.get("postalCode") or "")):
            raise UnpayableAddress("INVALID_PIN", "postalCode")
        try:
            india_address.india_subdivision(address.get("state"))
        except india_address.UnmappableAddress:
            raise UnpayableAddress("UNMAPPABLE_STATE", "state") from None
        return

    # Non-India below.
    if channel == WHATSAPP_ORDER_DETAILS:
        # Meta's India payment configuration settles INR against MCC 7392 / purpose code 03,
        # so a non-India beneficiary cannot settle on this surface — refuse outright.
        raise UnpayableAddress("COUNTRY_NOT_PAYABLE_ON_CHANNEL", "country")

    if channel == WEBSITE_RAZORPAY:
        # Website: a non-India address must still map to the normalized delivery shape, which demands
        # an ISO 3166-2 state. Re-raise the mapping refusal as the one caller-facing type.
        try:
            india_address.to_delivery_address(address)
        except india_address.UnmappableAddress:
            raise UnpayableAddress("UNMAPPABLE_STATE", "state") from None
        return

    # An unknown channel is a programming error, not a customer error.
    raise UnpayableAddress("UNKNOWN_CHANNEL", "")


def for_meta_beneficiary(address: Dict[str, Any], *, recipient_name: str) -> Dict[str, Any]:
    """Assert WhatsApp-payability (India only), then emit Meta's `beneficiaries[0]` shape.

    Exactly seven keys, with the length bounds outbound-whatsapp already applies.
    """
    assert_payable(address, channel=WHATSAPP_ORDER_DETAILS)
    return {
        "name": str(recipient_name or "")[:_META_NAME_MAX],
        "address_line1": str(address.get("addressLine1") or "")[:_META_LINE_MAX],
        "address_line2": str(address.get("addressLine2") or "")[:_META_LINE_MAX],
        "city": str(address.get("city") or "")[:_META_LINE_MAX],
        "state": str(address.get("state") or "")[:_META_LINE_MAX],
        "country": "India",
        "postal_code": str(address.get("postalCode") or "")[:_META_POSTAL_MAX],
    }


#: Fields Meta REQUIRES on every `order_details.shipping_info.addresses[0]`. A missing or empty
#: one makes Meta reject the ENTIRE payment send with HTTP 400 metaCode 100 ("violated 'required'
#: for ...shipping_info.addresses.0"), which the native Vault rail surfaced to staff as the opaque
#: PAYMENT_REQUEST_NOT_SENT. It cost a live cross-function trace to pin to a single missing
#: `phone_number`, because the two independent shipping builders (invoice-engine
#: `_payment_delivery_info` and checkout `_payment_shipping_info`) each hand-built this dict and
#: one had drifted from the other. This set is the one contract both must satisfy.
META_SHIPPING_ADDRESS_REQUIRED_FIELDS = (
    "name", "phone_number", "address", "city", "state", "in_pin_code")


def assert_meta_shipping_info(shipping_info: Any) -> None:
    """Fail fast, server-side, if a BUILT Meta `shipping_info` block is missing a required field.

    `shipping_info` is the `{"country": ..., "addresses": [ {...} ]}` dict a shipping builder
    returns, about to be placed on an `order_details` payment send. This does NOT re-validate the
    stored address (that is `assert_payable`); it validates the OUTGOING Meta shape so a builder
    that forgets a Meta-required field (the `phone_number` class of bug) refuses the payment here,
    with a named `UnpayableAddress`, instead of shipping a payload Meta rejects at the live send.

    Both shipping builders call this before returning, so the two cannot silently drift apart
    again. Raises `UnpayableAddress('META_SHIPPING_FIELD_MISSING', <field>)` on the first gap.
    """
    if not isinstance(shipping_info, dict):
        raise UnpayableAddress("META_SHIPPING_INFO_INVALID", "")
    if not str(shipping_info.get("country") or "").strip():
        raise UnpayableAddress("META_SHIPPING_FIELD_MISSING", "country")
    addresses = shipping_info.get("addresses")
    if not isinstance(addresses, list) or not addresses or not isinstance(addresses[0], dict):
        raise UnpayableAddress("META_SHIPPING_FIELD_MISSING", "addresses")
    first = addresses[0]
    for field in META_SHIPPING_ADDRESS_REQUIRED_FIELDS:
        if not str(first.get(field) or "").strip():
            raise UnpayableAddress("META_SHIPPING_FIELD_MISSING", field)


__all__ = [
    "WEBSITE_RAZORPAY",
    "WHATSAPP_ORDER_DETAILS",
    "UnpayableAddress",
    "assert_payable",
    "for_meta_beneficiary",
    "assert_meta_shipping_info",
    "META_SHIPPING_ADDRESS_REQUIRED_FIELDS",
]
