"""The one stored delivery address on a CRM contact row, and the rules that make it payable.

WHY THIS EXISTS ALONGSIDE `identity.address`
--------------------------------------------
`lambda_utils.identity.address` owns the *shape* of a structured address and is deliberately
country-agnostic and loose on postal codes, because "a strict per-country regex rejects real
addresses at the exact moment a customer is trying to pay". That reasoning holds everywhere
except the one market this store serves, and it leaves two questions unanswered that the
checkout path cannot proceed without:

1. **Which field failed?** `InvalidAddress` carries prose, not a field name, and the form has to
   mark one input. So this module keeps its own `_RULES` table and raises `UnusableAddress`
   carrying a machine `code` and, when one is attributable, the `field`.
2. **Can this address actually price the cart?** In India the delivery address *is* the place of
   supply: it decides CGST + SGST versus IGST on an invoice carrying a real GSTIN. That question
   — and India's six-digit PIN — are now PAYMENT rules owned by `payment_address`, which runs them
   at pay time against the paying channel (FEAT-003). This module no longer runs them, so storage
   is international: it validates structure and keeps any valid address, and a payment fails closed
   later if the stored address cannot settle on the channel the customer chose.

It lives under `ecommerce/` rather than `identity/` because it still carries the field-level
`code`/`field` reporting the checkout form needs; the tax rules themselves live in
`payment_address`.

THE TWO ATTRIBUTES, ON THE CONTACT ROW THAT ALREADY HOLDS THE IDENTITY
----------------------------------------------------------------------
`checkoutDeliveryAddress` (Map) and `checkoutAddressUpdatedAt` (Number, epoch seconds) sit on the
same `ContactsTable` row as `firstName`, `lastName`, `email`, `emailVerifiedAt` and
`checkoutCustomerId`. One address per customer, one row, one read. No address list, no `addressId`,
no billing/shipping pair — `identity.address.build_addresses` is therefore not used here, because
Razorpay collects nothing from us and a second address would be unused state that can disagree
with the first.

`recipientName` is derived and never stored: `india_address.to_delivery_address` emits exactly
`{country, subdivision, city, postalCode, addressLine[, addressLine2]}` and
`cart_contract.delivery_address` **refuses unknown fields** outright (its `ADDRESS_FIELDS`
allow-list, the `unknown = set(address) - set(ADDRESS_FIELDS)` check and its raise),
so a `recipientName` could not reach the cart even if it were stored. The
recipient is `firstName + " " + lastName` off the same row.

AUTOCOMPLETE METADATA IS DROPPED, BY CONSTRUCTION RATHER THAN BY A DELETION PASS
--------------------------------------------------------------------------------
`normalize_address` carries `googlePlaceId`/`latitude`/`longitude` through when present, and the
last two are floats. Floats are banned in this path and DynamoDB refuses them anyway (`Decimal`
required). The three keys are simply not in `_RULES`, so they never enter the dict step 4
normalises and `normalize_address` has nothing to carry through. Nothing in the delivery or tax
path reads them.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from lambda_utils.identity import address as owned_address

#: The contact-row attribute holding the structured address.
ATTRIBUTE = "checkoutDeliveryAddress"
#: The contact-row attribute holding the epoch seconds it was last written.
UPDATED_ATTRIBUTE = "checkoutAddressUpdatedAt"

class UnusableAddress(ValueError):
    """Carries a machine code and, when one is attributable, the field that failed.

    Subclasses `ValueError` so it reads naturally at a call site, but note that the
    `customer-profile` handler normalises **before** its main `try` precisely because that `try`
    already has a `ValueError` arm ending in a bare `raise`.
    """

    def __init__(self, code: str, field: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.field = field


def _text(value: Any, *, limit: int) -> str:
    """Coerce one browser-supplied address value to a trimmed string. NEVER raises.

    `raw` is parsed browser JSON, so every value is attacker-chosen in type as well as content.
    A non-scalar (`{"long_name": "Bengaluru"}` from a half-copied Places result, a list, a bool)
    is treated as ABSENT rather than stringified, because `"{'long_name': 'Bengaluru'}"` is not a
    city and storing it would price the wrong place of supply. A number is accepted and
    stringified (`{"postalCode": 560001}` is a real browser shape), which is why the PIN regex at
    step 3 still sees a string. Returns `limit + 1` characters at most so the length rule can
    still FAIL on an over-long value instead of being silently truncated into compliance.
    """
    if isinstance(value, (dict, list, bool)):
        return ""
    return " ".join(str(value if value is not None else "").split())[:limit + 1]


#: Field -> (required?, limit). This module's own table, because the error it raises must name a
#: field and `identity.address.InvalidAddress` cannot.
#:
#: The limits are the same values `identity/address.py:49-50` applies to the same fields
#: (`MAX_LINE_LENGTH` 200 for the address lines, `MAX_FIELD_LENGTH` 100 for the rest), except
#: `countryCode`, which is tightened to 2 because that is what an ISO 3166-1 alpha-2 code is.
_RULES = {
    "addressLine1": (True, 200),
    "addressLine2": (False, 200),
    "locality": (False, 100),
    "city": (True, 100),
    "state": (True, 100),
    "postalCode": (True, 100),
    "country": (False, 100),
    "countryCode": (False, 2),
}


def normalize_for_storage(raw: Any) -> Dict[str, Any]:
    """The address to store, or raise `UnusableAddress` naming the code and (usually) the field.

    Three steps, in this order (FEAT-003 removed the India PIN check and the delivery-mappability
    check — those are PAYMENT rules now, owned by `payment_address` and run at pay time):

    1. `raw` is a non-empty dict                      -> `ADDRESS_REQUIRED`
    2. coerce every `_RULES` field through `_text` ONCE, require the required ones, bound every
       length, THEN default `countryCode`             -> `FIELD_REQUIRED` / `FIELD_TOO_LONG`
    3. `identity.address.normalize_address(cleaned)`  -> `INVALID_ADDRESS`

    Metadata (`googlePlaceId`/`latitude`/`longitude`) is absent by construction — see the module
    docstring. `country` and `countryCode` stay real fields; `state` and `postalCode` stay required
    and length-bounded, but `postalCode` no longer carries India's PIN regex (that moved to
    `payment_address.assert_payable`), so a valid non-India postal code is accepted and stored.

    **Step 3 normalises `cleaned`, never `raw`, and that is the whole point of `_text`.**
    `identity.address._clean` opens `" ".join(str(value or "").split())` and raises only on an
    over-long result: it does not refuse a non-scalar, it **stringifies** it. On a required field
    that is invisible, because step 2 already refused the request. On an optional field it is not —
    handing `raw` down would store `addressLine2 = "{'long_name': 'Flat 3B'}"`, which the
    delivery address would pass straight through and `full_address` would print on the identity
    card. So `_text` coerces every field once, before step 3 sees it.

    Feeding `cleaned` forward is also what makes step 3 unreachable in practice rather than
    hopeful: `normalize_address` requires `addressLine1`, `city` and `postalCode`, all three
    `True` here, and step 2 additionally requires `state`, so this module's required set is a
    strict superset; its only other failure is a length raise, and every `_RULES` limit is at or
    below the limit it applies to the same field.

    **Step 2 defaults the country code locally.** `normalize_address` is the thing that applies the
    `IN` default, but that runs at step *3*. Defaulting here keeps `countryCode` a real, uppercased
    two-letter value for every later reader (including `payment_address`, which branches on it).
    """
    if not isinstance(raw, dict) or not raw:
        raise UnusableAddress("ADDRESS_REQUIRED")

    # Exactly one read of `raw` in the whole function, so no field can be read uncoerced.
    cleaned = {field: _text(raw.get(field), limit=limit)
               for field, (_required, limit) in _RULES.items()}
    for field, (required, limit) in _RULES.items():
        value = cleaned[field]
        if required and not value:
            raise UnusableAddress("FIELD_REQUIRED", field)
        if len(value) > limit:
            raise UnusableAddress("FIELD_TOO_LONG", field)
    cleaned["countryCode"] = (
        cleaned["countryCode"] or owned_address.DEFAULT_COUNTRY_CODE).upper()[:2]

    try:
        out = owned_address.normalize_address(cleaned)
    except owned_address.InvalidAddress:
        raise UnusableAddress("INVALID_ADDRESS") from None

    # Storage is INTERNATIONAL (FEAT-003). The India PIN rule and the delivery-mappability rule that
    # used to live here are PAYMENT rules, not storage rules — they moved to `payment_address`
    # and run at pay time against the paying channel. Keeping them here would make storage
    # India-only and reject a valid international address at save time. `payment_address` is the
    # single owner of the place-of-supply / settlement tax rules now.
    return out


def from_contact(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stored address on a contact row, re-validated for STRUCTURE, or `None`. **Never raises.**

    FEAT-003 weakened this guarantee deliberately: a dict this returns is **structurally valid**
    (required fields present, lengths bounded, a real country code, a normalisable owned-address).
    It is NO LONGER guaranteed to map to the delivery shape — storage is now international and
    the India place-of-supply question moved to `payment_address`. Ask *that* module whether a
    returned address can actually pay on a given channel; see `payable_for` below for a caller that
    wants one answer covering both "no address stored" and "stored but unpayable here".
    """
    if not isinstance(row, dict):
        return None
    try:
        return normalize_for_storage(row.get(ATTRIBUTE))
    except Exception:  # noqa: BLE001 - the never-raises guarantee is the contract
        return None


#: The flat ContactsTable address columns the WhatsApp Address-Message writer and the invoice /
#: receipt readers have historically used. Kept populated ALONGSIDE the canonical
#: `checkoutDeliveryAddress` Map so legacy readers do not break, but DERIVED from the same
#: normalised Map here so the flat columns can never drift from it. `landmark` mirrors the Map's
#: `locality`; the invoice shipping_info pre-fill reads `landmark`, so the two must agree.
_CONTACT_FLAT_FIELDS = ("addressLine1", "addressLine2", "city", "state", "postalCode", "country")


def map_meta_address(values: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a Meta India Address-Message / post-pay flow payload into the eight `_RULES` keys.

    This is the ONE place the WhatsApp address vocabulary (`house_number`, `floor_number`,
    `tower_number`, `building_name`, `address`, `landmark_area`, `in_pin_code`, ...) is translated
    to the canonical field names, so the inbound handler converges on the same shape
    `customer_orders.update_profile` already writes rather than inventing a parallel flat row.

    The street line is `address` when Meta supplies it; otherwise the house/tower/building parts
    are joined so a submission that fills only the structured sub-fields still yields a usable
    `addressLine1` (the required field). The floor/house/unit detail folds into `addressLine2`,
    `landmark_area` into `locality`, and `in_pin_code` (or `pin`) into `postalCode`. Returns a raw
    dict for `normalize_for_storage` to validate — it does NOT itself validate or raise.
    """
    def pick(*keys: str) -> str:
        for key in keys:
            value = values.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        return ""

    house = pick("house_number")
    floor = pick("floor_number")
    tower = pick("tower_number")
    building = pick("building_name")
    street = pick("address")
    # `addressLine1` is required; synthesise it from the structured parts when Meta sends no
    # free-text street line, so a structured-only submission is not refused as FIELD_REQUIRED.
    line1 = street or ", ".join(p for p in (house, building, tower) if p)
    unit = ", ".join(p for p in (house if street else "", f"Floor {floor}" if floor else "",
                                 tower if street else "", building if street else "") if p)
    return {
        "addressLine1": line1,
        "addressLine2": unit,
        "locality": pick("landmark_area", "landmark"),
        "city": pick("city"),
        "state": pick("state"),
        "postalCode": pick("in_pin_code", "pin", "postal_code", "postalCode"),
        "country": pick("country") or owned_address.DEFAULT_COUNTRY,
        "countryCode": pick("country_code", "countryCode"),
    }


#: Which Address Message field shows each stored field: the inverse of `map_meta_address`.
#: `addressLine2` is the unit detail that function folds out of house/floor/tower/building, so it
#: goes back as `house_number`, which `map_meta_address` folds into `addressLine2` again whenever
#: the `address` line is present. A prefilled form sent back unchanged stores the same address.
_META_FIELD_BY_ATTRIBUTE = (
    ("addressLine1", "address"),
    ("addressLine2", "house_number"),
    ("locality", "landmark_area"),
    ("city", "city"),
    ("state", "state"),
    ("postalCode", "in_pin_code"),
)

#: Meta's length limit on the Address Message PIN field. A longer stored value is left out of the
#: prefill rather than sent, so the form never carries a value Meta could refuse.
_META_PIN_MAX = 6

#: Meta sends the India Address Message only to India (+91) WhatsApp numbers. A request to any
#: other number is refused, so no payment step may wait on that form for one.
ADDRESS_MESSAGE_PHONE_PREFIX = "+91"


def address_message_reaches(phone: Any) -> bool:
    """True when Meta's India Address Message can be sent to this E.164 number."""
    return str(phone or "").strip().startswith(ADDRESS_MESSAGE_PHONE_PREFIX)


def to_meta_address_values(address: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """A stored India address as Address Message `values`, so the form opens filled in.

    `{}` for no address or a non-India one: the form is India-only, and a foreign address would
    only prefill fields the customer has to clear. Empty fields are left out, so the form shows
    its own placeholders. Never raises.
    """
    if not isinstance(address, dict):
        return {}
    country_code = str(address.get("countryCode") or owned_address.DEFAULT_COUNTRY_CODE)
    if country_code.strip().upper() != owned_address.DEFAULT_COUNTRY_CODE:
        return {}
    values: Dict[str, str] = {}
    for attribute, meta_field in _META_FIELD_BY_ATTRIBUTE:
        text = _text(address.get(attribute), limit=_RULES[attribute][1])
        if attribute == "postalCode" and len(text) > _META_PIN_MAX:
            continue
        if text:
            values[meta_field] = text
    return values


def contact_write_fields(address: Dict[str, Any], *, now: int) -> Dict[str, Any]:
    """The ContactsTable attributes to write for one normalised address: the canonical Map, its
    timestamp, AND the legacy flat columns derived from the SAME Map.

    A single return so a writer sets `checkoutDeliveryAddress`, `checkoutAddressUpdatedAt` and the
    flat `addressLine1..country`/`landmark`/`shippingAddress` from one source — the flat columns
    can no longer disagree with the Map because they are projected from it here. `address` is the
    output of `normalize_for_storage` (already validated and bounded).
    """
    flat = {field: str(address.get(field) or "") for field in _CONTACT_FLAT_FIELDS}
    # `landmark` is the legacy column name for what the Map calls `locality`.
    flat["landmark"] = str(address.get("locality") or "")
    # The human one-line string the receipt and shipping_info string fields read.
    flat["shippingAddress"] = str(address.get("fullAddress") or "")
    return {ATTRIBUTE: address, UPDATED_ATTRIBUTE: now, **flat}


def payable_for(row: Optional[Dict[str, Any]], channel: str):
    """One return shape for a caller: `(address, None)` or `(None, UnpayableAddress)`.

    Collapses the two "cannot take money" cases — no address stored, and a stored-but-unpayable
    address on this channel — into a single tuple so a checkout/send path has exactly one branch.
    Imported lazily to avoid a module import cycle (payment_address imports from this package).
    """
    from lambda_utils.ecommerce import payment_address

    address = from_contact(row)
    if address is None:
        return None, payment_address.UnpayableAddress("ADDRESS_REQUIRED")
    try:
        payment_address.assert_payable(address, channel=channel)
    except payment_address.UnpayableAddress as exc:
        return None, exc
    return address, None


__all__ = [
    "ATTRIBUTE",
    "UPDATED_ATTRIBUTE",
    "UnusableAddress",
    "normalize_for_storage",
    "from_contact",
    "payable_for",
    "map_meta_address",
    "ADDRESS_MESSAGE_PHONE_PREFIX",
    "address_message_reaches",
    "to_meta_address_values",
    "contact_write_fields",
]
