"""The one public-facing customer id, as a uuid4 we mint and are willing to print.

WHY THIS IS A MODULE AND NOT A CALL TO `uuid.uuid4()`
----------------------------------------------------
The value is printed on a tax invoice, shown on the customer's order page, shown in the staff
payment records table, and quoted out loud by a support agent instead of a phone number. That
makes three separate questions that must have exactly one answer each:

  * which attribute holds it            -> `ATTRIBUTE`
  * how one is minted                   -> `new_customer_uuid()`
  * whether a stored value is usable    -> `is_customer_uuid()` / `from_contact()`

Spread those across five handlers and the fourth one validates differently from the first. Same
discipline `order_channel.py` applies to the channel word and `payment_status.py` applies to
payment words: the vocabulary lives in one file or it lives in five.

WHY A SEPARATE ATTRIBUTE AND NOT THE CONTACT ROW `id`
-----------------------------------------------------
The contact row already has a uuid, and it cannot be used here. It is minted TWO different ways:

  * `core/contacts._create`            -> `uuid.uuid4()`
  * `auth/customer-profile._upsert_contact` -> `uuid.uuid5(NAMESPACE_URL,
                                               f"wecare:checkout-customer:{customer_id}")`

A uuid5 is a HASH OF ITS INPUT, and that input is the Cognito subject. So publishing `id` on an
invoice would publish a value derived from the Cognito sub of every customer who signed in -
a value that is also a stable cross-system correlator for an identity provider's internal
identifier. A second attribute costs one string per row and removes that entirely.

WHY uuid4 AND EXPLICITLY NOT `identifiers.new_uuid7`
----------------------------------------------------
`identifiers.py` mints time-ordered ids on purpose and its own docstring states the cost: "the
creation time is *visible* in the id - deliberate for an internal identifier, and the reason
neither of these may ever be used as a public order number". This id is MORE public than an order
number: it is printed on a document the customer keeps and forwards. A uuid7 would tell anyone
holding an invoice when that customer's record was created, to the millisecond.

So `is_customer_uuid` tests `version == 4` rather than merely "parses as a UUID". That is what
makes the rule enforceable instead of advisory: a uuid7 accidentally written into this attribute
by some future caller is REJECTED at read time and the invoice renders no customer-id row, rather
than quietly printing a timestamp.

WHY IT MAY BE LOGGED IN FULL
----------------------------
It is not a secret, not a credential, and not a phone number. It is ours, it is opaque, and it
carries no timestamp (see above). So - exactly like `reference_id` - it is the correlation id
that lets a payment log line be traced with NO masked field in it, which is why `contactId` and
`referenceId` already appear together in almost every payment log. The phone beside it still
reaches a log masked to the last four, through `lambda_utils.privacy.mask_phone`.

RESOLVE BEFORE GENERATE, AND WHY NOTHING HERE READS A DATABASE
--------------------------------------------------------------
"An existing customer keeps its UUID" is enforced by DynamoDB, not by this module: the two CRM
write sites and `auth/customer-profile` assign it with `if_not_exists(customerUuid, :vuuid)`, so
a fresh uuid4 is minted locally on every update and DISCARDED when one already exists. That costs
no network call and makes the property atomic instead of a read-then-write race window.

Consequently this module is pure, holds no AWS client, needs no credential, and the payment path
only ever READS through it. Nothing on the money path mints one: an invoice with no customer id
renders no customer-id row, exactly as `invoiceNumber` already behaves when absent.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

#: The contact-row / order-row / invoice-row attribute holding the public customer id. One
#: spelling, so a rename is one edit and a test can anchor on it.
ATTRIBUTE = "customerUuid"

#: The UUID version this attribute accepts, and nothing else. Named rather than inlined so the
#: "not a uuid7" rule is greppable from the test that pins it.
VERSION = 4


def new_customer_uuid() -> str:
    """A fresh public customer id.

    `str(...)` rather than a `uuid.UUID`, for the same reason `identifiers.new_uuid7` returns a
    string: every consumer writes it to DynamoDB or JSON, and a `UUID` object serialises only
    after an explicit `str()` that is easy to forget - and forgetting it on a DynamoDB write is a
    `TypeError` at request time rather than at import time.
    """
    return str(uuid.uuid4())


def is_customer_uuid(value: Any) -> bool:
    """True only for a CANONICAL hyphenated UUID string whose version is 4.

    Two refusals worth stating, because both are load-bearing:

    * **A uuid7 is refused.** `uuid.UUID(...)` parses one happily, so a bare parse would accept
      the one format this attribute must never carry (see the module docstring on timestamps).
    * **A non-canonical spelling is refused** - `{...}` braces, a `urn:uuid:` prefix, or 32 hex
      characters with no hyphens all parse in Python but are a DIFFERENT STRING from what we
      stored. This value is compared, joined on and printed verbatim, so accepting two spellings
      of one id would let an invoice and an order page disagree character for character.
    """
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    # Byte equality, with NO `.strip()` and NO `.lower()` on the way in. Normalising here would
    # be strictly worse than refusing: `is_customer_uuid("AB12-...")` would answer True while
    # every renderer prints `value` VERBATIM, so the document would carry the upper-case spelling
    # and the order row the lower-case one. One id, two strings, and nothing to tell them apart.
    return parsed.version == VERSION and str(parsed) == value


def from_contact(row: Optional[Dict[str, Any]]) -> str:
    """The stored customer id on a row, re-validated, or `''`. **NEVER RAISES.**

    The same contract `ecommerce.contact_address.from_contact` carries, and for the same reason:
    every caller is on a path where raising is worse than degrading. The checkout caller is
    preparing a payment; the renderers run AFTER the money has moved. A junk or absent value must
    therefore become "this invoice has no customer id" - which renders no row - and never an
    exception inside a renderer.

    Returns `''` rather than `None` so the value is directly usable in the conditional-emit
    pattern the attribution fields already use (`if value: record[key] = value`).
    """
    if not isinstance(row, dict):
        return ""
    try:
        value = row.get(ATTRIBUTE)
    except Exception:  # noqa: BLE001 - the never-raises guarantee IS the contract
        # A dict subclass whose `.get` raises is not a contact row, and the answer for an
        # unusable row is the same empty string in every other case. Guarding the READ as well
        # as the validation is what makes the guarantee true for any object, which is the shape
        # `contact_address.from_contact` settled on for the identical reason.
        return ""
    return value if is_customer_uuid(value) else ""


__all__ = [
    "ATTRIBUTE",
    "VERSION",
    "new_customer_uuid",
    "is_customer_uuid",
    "from_contact",
]
