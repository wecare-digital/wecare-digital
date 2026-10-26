"""The delivery address an order ships to, frozen when the customer prepares the payment.

WHY A SNAPSHOT AND NOT A JOIN
-----------------------------
The CRM contact holds ONE delivery address (`contact_address.ATTRIBUTE`), and every profile save
overwrites it whole. An order that only pointed at the contact would change where it ships, and
what its history says it shipped to, every time the customer edited their profile after paying.
So checkout records the address the customer confirmed on the PaymentAttempt at the moment the
payment is prepared (`attempt_fields`), and `finalization.accept_paid` copies it onto the order row
it writes (`order_fields`). Nothing reads the contact after payment for this.

WHAT IS STORED
--------------
On the attempt: `deliveryAddress` (the normalised `contact_address` Map) and `deliveryRecipient`
(the name the parcel is addressed to). On the order: the same Map under `contact_address.ATTRIBUTE`
and its one-line `fullAddress` under the declared `shippingAddress` column, which are the two names
the post-payment Flow link (`inbound _link_flow_submission_to_order`) already writes, so an order
has one address vocabulary whoever wrote it. `deliveryRecipient` rides beside them.

All of it is ATTRIBUTION beside the frozen money record. It is never inside `purchasedSnapshot`
(it must not move `snapshotHash` or `quoteHash`) and never part of the finalization association
conflict comparison, so a redelivered capture can never fail over an address.

Every reader re-validates through `contact_address.normalize_for_storage` and degrades to "no
address" rather than raising, so a hand-edited or legacy row never breaks a checkout, a
finalization or the order page.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import contact_address

#: The PaymentAttempt attribute holding the confirmed delivery address (a normalised Map).
ATTEMPT_ADDRESS = "deliveryAddress"
#: The attempt AND order attribute holding the recipient's name.
RECIPIENT = "deliveryRecipient"
#: The order attribute holding the structured address. The same name the contact row uses.
ORDER_ADDRESS = contact_address.ATTRIBUTE
#: The order's declared one-line address column.
ORDER_ADDRESS_LINE = "shippingAddress"

#: A courier label line, not a document. Longer values are cut rather than refused.
RECIPIENT_MAX = 120


def _clean(address: Any) -> Optional[Dict[str, Any]]:
    """`address` re-validated to the stored shape, or None. Never raises."""
    if not isinstance(address, dict) or not address:
        return None
    try:
        return contact_address.normalize_for_storage(address)
    except contact_address.UnusableAddress:
        return None


def recipient_name(profile: Any) -> str:
    """Who a delivery is addressed to: the contact's `name`, else `firstName lastName`. '' if none.

    The same precedence the WhatsApp ORDER_DETAILS `shipping_info` uses, so the name Meta shows
    the customer before they pay is the name the order records.
    """
    if not isinstance(profile, dict):
        return ""
    name = " ".join(str(profile.get("name") or "").split())
    if not name:
        name = " ".join(
            f"{profile.get('firstName') or ''} {profile.get('lastName') or ''}".split())
    return name[:RECIPIENT_MAX]


def attempt_fields(address: Any, profile: Any) -> Dict[str, Any]:
    """The attempt attributes for one confirmed delivery address, or `{}` when there is none.

    `{}` keeps an attempt that ships nothing (a service, a contribution) byte-identical to one
    written before this module existed.
    """
    clean = _clean(address)
    if clean is None:
        return {}
    fields: Dict[str, Any] = {ATTEMPT_ADDRESS: clean}
    recipient = recipient_name(profile)
    if recipient:
        fields[RECIPIENT] = recipient
    return fields


def order_fields(attempt: Any) -> Dict[str, Any]:
    """The order-row attributes for the address frozen on `attempt`, or `{}` when it has none."""
    if not isinstance(attempt, dict):
        return {}
    clean = _clean(attempt.get(ATTEMPT_ADDRESS))
    if clean is None:
        return {}
    fields: Dict[str, Any] = {ORDER_ADDRESS: clean,
                              ORDER_ADDRESS_LINE: str(clean.get("fullAddress") or "")}
    recipient = " ".join(str(attempt.get(RECIPIENT) or "").split())[:RECIPIENT_MAX]
    if recipient:
        fields[RECIPIENT] = recipient
    return fields


def from_order(order: Any) -> Optional[Dict[str, Any]]:
    """What an order row says it ships to, for display: `{recipient, address}`, or None."""
    if not isinstance(order, dict):
        return None
    clean = _clean(order.get(ORDER_ADDRESS))
    if clean is None:
        return None
    return {"recipient": " ".join(str(order.get(RECIPIENT) or "").split())[:RECIPIENT_MAX],
            "address": clean}


__all__ = [
    "ATTEMPT_ADDRESS",
    "RECIPIENT",
    "ORDER_ADDRESS",
    "ORDER_ADDRESS_LINE",
    "recipient_name",
    "attempt_fields",
    "order_fields",
    "from_order",
]
