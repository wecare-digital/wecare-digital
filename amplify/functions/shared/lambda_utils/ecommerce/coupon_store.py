"""Coupon issuance, usage counters and eligibility holds. The discount ARITHMETIC is not here.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md`, sections
4 (data model), 5.2 (commit), 5.4 (validation) and 5.5 (invariants).

Two authorities, and the split is the whole point
-------------------------------------------------
This table owns **issuance**: what discount was promised, who may use it, how many times it has
been used, and the audit trail. On the WEBSITE, Wix's `Calculate Cart` owns the **arithmetic**:
what a given cart is actually reduced by. A coupon reaches a customer's total there only by being
mirrored into Wix and applied to a Wix cart, where Wix reduces `summary.priceSummary.discount` and
the smaller total arrives back through the existing `cart_v2.calculate` path.

That is why `evaluate()` answers with a VERDICT from a closed vocabulary and never a figure. A
validate endpoint that returned a discount would be a number a browser could quote.

**One narrowing, added deliberately: `discount_paise`.** An earlier revision of this paragraph said
nothing here returns or computes a discount amount, full stop. That is no longer true, and the
exception is the invoice surface, which has no Wix cart and therefore no `Calculate Cart` to defer
to. `discount_paise` answers that one question, from the definition this module already owns, and it
reads exactly the `KIND_AMOUNT_ATTRIBUTE` attributes `wix_coupons.specification` sends - so it is a
second RENDERING of one definition, not a second engine. Its own docstring carries the reasoning
and the alternative that was rejected. `evaluate` is unchanged and still returns no figure.

One partition attribute, four row types
---------------------------------------
    COUPON#<codeUpper>                      the definition
    COUPONUSE#<codeUpper>#<customerId>      per-customer usage counter
    COUPONHOLD#<codeUpper>#<cartId>         a short-lived eligibility reservation (audit)
    COUPONREDEEM#<codeUpper>#<orderId>      idempotent terminal redemption record

Namespaced rows on a single partition key, the same shape `order_keys` uses, because the
uniqueness guarantee has to be a conditional write **on the partition key**. A GSI is eventually
consistent and therefore cannot enforce a constraint.

`codeUpper` is NFKC-normalised and upper-cased. Wix says the code must be unique on the site but
does not say the comparison is case-insensitive, so we normalise for *our* key and store the exact
`code` we sent to Wix separately. Normalising is what stops `SAVE10` and `save10` becoming two
coupons that look like one to a customer.

A coupon code is NOT bearer value
---------------------------------
It is broadcast marketing material, printed in campaigns and shared deliberately, so it may be
logged in full and is safe as a partition key. This is the exact opposite of a gift-card code,
where the same position is occupied by an HMAC, and the asymmetry is deliberate rather than an
oversight - `tests/test_coupon_logging_and_vocabulary.py` pins it so a later "hardening" pass
cannot quietly mask the one correlation id this path has.

Every access is an exact-key operation
--------------------------------------
`get_item` / `put_item` / `update_item` / `delete_item` on a fully specified partition key, plus
the staff `status-index` `Query`. There is no `scan`, no prefix query and no second index, and
`tests/test_coupon_store.py` enumerates the call sites to keep it that way. The existence of a
hold is therefore read off the definition row (`activeHoldCartId` / `activeHoldExpiresAtMs`)
rather than discovered by looking for `COUPONHOLD#` rows: a decision that gates money cannot be
made from a scan.

No float, no read-modify-write
------------------------------
Money is integer paise and rates are integer basis points, with `money.positive_paise` reused
rather than reimplemented. Counters move with an atomic `ADD` under a `ConditionExpression`; a
read-then-write would let two concurrent checkouts both pass the same single-use coupon.

TTL is disabled on this table, deliberately. A coupon row is the record of what was promised and
how often it was used; an expired coupon must still be readable long after it stops being
applicable, because a settled order references it. Expiry is a field, never a deletion. The one
row type permitted to vanish is `COUPONHOLD#`, and it goes by explicit delete on release so that
expiry is never silent.
"""
from __future__ import annotations

import re
import time
import unicodedata
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from . import checkout_pricing, money
from .. import identifiers

#: Physical table. Follows `check_data_model_drift.expected_table`'s default rule
#: (pluralise + `Table`), so no explicit-map entry is needed for it.
DEFAULT_TABLE_NAME = "stack-wecare-digital-CouponsTable"
TABLE_ENV_KEY = "COUPONS_TABLE"

KEY_ATTRIBUTE = "couponKey"
STATUS_ATTRIBUTE = "status"
STATUS_INDEX = "status-index"

PREFIX_DEFINITION = "COUPON#"
PREFIX_USE = "COUPONUSE#"
PREFIX_HOLD = "COUPONHOLD#"
PREFIX_REDEEM = "COUPONREDEEM#"

CURRENCY = "INR"
POLICY_VERSION = "coupon-policy-2026-10-01"

STATUS_ACTIVE = "ACTIVE"
STATUS_INACTIVE = "INACTIVE"
STATUS_EXHAUSTED = "EXHAUSTED"
STATUSES = (STATUS_ACTIVE, STATUS_INACTIVE, STATUS_EXHAUSTED)

MIRROR_PENDING = "PENDING_WIX"
MIRROR_DONE = "MIRRORED"
MIRROR_DELETED = "WIX_DELETED"
MIRROR_STATES = (MIRROR_PENDING, MIRROR_DONE, MIRROR_DELETED)

#: Exactly one of these defines a coupon, matching Wix's `Specification` oneOf.
MONEY_OFF = "MONEY_OFF"
PERCENT_OFF = "PERCENT_OFF"
FIXED_PRICE = "FIXED_PRICE"
FREE_SHIPPING = "FREE_SHIPPING"
BUY_X_GET_Y = "BUY_X_GET_Y"
DISCOUNT_KINDS = (MONEY_OFF, PERCENT_OFF, FIXED_PRICE, FREE_SHIPPING, BUY_X_GET_Y)

#: Which stored attribute carries the magnitude for each kind. `FREE_SHIPPING` has none.
KIND_AMOUNT_ATTRIBUTE = {
    MONEY_OFF: "moneyOffPaise",
    PERCENT_OFF: "percentOffBps",
    FIXED_PRICE: "fixedPricePaise",
}

#: Wix documents `Specification.code` as "Max: 20 characters", so a coupon we issue can never
#: hit the wider bound the cart adapter applies to a hand-typed code.
MAX_CODE_LENGTH = 20
CODE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

MAX_NAME_LENGTH = 100
MAX_TAGS = 100
MAX_TAG_LENGTH = 255

#: Wix's own documented minimum for `startTime` / `expirationTime`, both epoch milliseconds.
WIX_MIN_TIME_MS = 1_000_000_000_000

#: `money.py`'s ceiling, reused rather than restated.
MAX_PAISE = 9007199254740991

#: 100% in basis points.
MAX_PERCENT_OFF_BPS = 10000

#: Paise in one rupee. Every Wix-bound amount is a whole multiple of this, because the Wix
#: coupon service's money fields are JSON `number` in decimal rupees and nothing documents a
#: string being accepted there - see coupons section 4.2.
PAISE_PER_RUPEE = 100

#: A hold is advisory and short-lived: it prevents the ordinary double-spend race while a
#: customer finishes paying. The authoritative single-use guarantee is the conditional
#: `COUPONREDEEM#` put, so a hold expiring early costs a race, never a double redemption.
HOLD_TTL_SECONDS = 900

SCOPE_NAMESPACE = "stores"
SCOPE_GROUPS = ("product", "collection")

#: The closed verdict vocabulary `POST /coupons/validate` answers with. A verdict, never an
#: amount, and `UNKNOWN_CODE` is deliberately the same SHAPE of answer as `EXPIRED` so the
#: endpoint cannot be ground into a code enumerator.
ELIGIBLE = "ELIGIBLE"
UNKNOWN_CODE = "UNKNOWN_CODE"
NOT_ACTIVE = "NOT_ACTIVE"
NOT_STARTED = "NOT_STARTED"
EXPIRED = "EXPIRED"
USAGE_LIMIT_REACHED = "USAGE_LIMIT_REACHED"
CUSTOMER_LIMIT_REACHED = "CUSTOMER_LIMIT_REACHED"
HELD_BY_ANOTHER_CART = "HELD_BY_ANOTHER_CART"
WIX_MIRROR_INCOMPLETE = "WIX_MIRROR_INCOMPLETE"
VERDICTS = (ELIGIBLE, UNKNOWN_CODE, NOT_ACTIVE, NOT_STARTED, EXPIRED, USAGE_LIMIT_REACHED,
            CUSTOMER_LIMIT_REACHED, HELD_BY_ANOTHER_CART, WIX_MIRROR_INCOMPLETE)

#: DECISION 5. The existence of a hold lives on the row whose key is already known, so the
#: check is a `GetItem`/`UpdateItem` rather than a search. These two attributes and this one
#: condition are what remove the last non-exact-key access from the store.
HOLD_CART_ATTRIBUTE = "activeHoldCartId"
HOLD_EXPIRY_ATTRIBUTE = "activeHoldExpiresAtMs"
HOLD_CONDITION = ("attribute_not_exists(activeHoldCartId) "
                  "OR activeHoldCartId = :me "
                  "OR activeHoldExpiresAtMs < :now")

#: Every attribute a definition row may carry, per coupons section 4.2. Enumerated because
#: `wix_coupons` reads from this shape and a test discriminates our own attribute names from
#: Wix's response keys by comparing against this set.
DEFINITION_ATTRIBUTES = (
    KEY_ATTRIBUTE, "couponId", "code", "wixCouponId", "wixMirrorState", "name", STATUS_ATTRIBUTE,
    "discountKind", "moneyOffPaise", "percentOffBps", "fixedPricePaise", "buyX", "buyY",
    "minimumSubtotalPaise", "scopeNamespace", "scopeGroupName", "scopeEntityId", "startTimeMs",
    "expirationTimeMs", "usageLimit", "limitPerCustomer", "usageCount", "limitedToOneItem",
    "currency", "policyVersion", "createdAt", "updatedAt", "createdBy", "tags",
    HOLD_CART_ATTRIBUTE, HOLD_EXPIRY_ATTRIBUTE,
)

#: Accepted on the create payload. Anything else is a caller mistake, refused rather than
#: dropped, so a misspelled `expirationTimeMS` cannot issue a coupon that never expires.
CREATE_FIELDS = (
    "code", "name", "discountKind", "moneyOffPaise", "percentOffBps", "fixedPricePaise",
    "buyX", "buyY", "minimumSubtotalPaise", "scopeNamespace", "scopeGroupName", "scopeEntityId",
    "startTimeMs", "expirationTimeMs", "usageLimit", "limitPerCustomer", "limitedToOneItem",
    "currency", "tags",
)


class CouponError(ValueError):
    """Base. Carries a machine-readable `code` so a handler never parses a message."""

    status = 400

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class CouponValidationError(CouponError):
    """An external input was refused. Nothing reached Wix and nothing was written."""


class CouponConflict(CouponError):
    """The normalised code is already issued. The database refused the second write."""

    status = 409

    def __init__(self, code: str = "CODE_ALREADY_EXISTS", message: str = ""):
        super().__init__(code, message)


class CouponHeldByAnotherCart(CouponError):
    """Another cart holds this coupon and its hold has not expired."""

    status = 409

    def __init__(self, message: str = ""):
        super().__init__(HELD_BY_ANOTHER_CART, message)


class CouponStoreUnavailable(RuntimeError):
    """Storage failed for a reason that is not a lost race.

    Its own type so a throttle or an outage can never be mistaken for "already claimed" or for
    "no such coupon" - a read failure reported as absence is how a live coupon gets refused and
    a duplicate gets issued.
    """


def _default_clock() -> int:
    """Epoch SECONDS as an `int`.

    An int rather than `time.time()`'s float, so no float is constructed anywhere this module
    runs - including the timestamp path, which is otherwise the one place a float would sneak
    into a row that is compared for exact equality later.
    """
    return int(time.time())


Clock = Callable[[], int]


def _now_seconds(clock: Clock) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int):
        raise CouponStoreUnavailable("clock must return integer epoch seconds")
    return value


def _is_conditional_failure(error: BaseException) -> bool:
    """True only for DynamoDB's conditional-check failure, however the client spells it."""
    name = type(error).__name__
    if name == "ConditionalCheckFailedException":
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    return False


# ── keys ──────────────────────────────────────────────────────────────────────

def normalise_code(value: Any) -> str:
    """NFKC-normalise, strip and upper-case a coupon code, or refuse it.

    NFKC first so a fullwidth `ＳＡＶＥ１０` collapses onto `SAVE10` instead of becoming a second
    coupon that looks identical to a customer. The charset check runs AFTER normalisation, so a
    code that only becomes legal by being normalised is still legal, and one that is illegal
    either way is refused before it can reach Wix.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise CouponValidationError("INVALID_CODE", "a coupon code string is required")
    text = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(text) <= MAX_CODE_LENGTH or not CODE_PATTERN.match(text):
        raise CouponValidationError(
            "INVALID_CODE",
            f"a coupon code must be 1 to {MAX_CODE_LENGTH} characters of [A-Za-z0-9._-]")
    return text.upper()


def _identifier(value: Any, code: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise CouponValidationError(code, f"{code.lower()} is required")
    text = value.strip()
    if len(text) > 128 or "#" in text:
        raise CouponValidationError(code, f"{code.lower()} is not a usable identifier")
    return text


def definition_key(code: Any) -> str:
    return PREFIX_DEFINITION + normalise_code(code)


def use_key(code: Any, customer_id: Any) -> str:
    return (PREFIX_USE + normalise_code(code) + "#"
            + _identifier(customer_id, "INVALID_CUSTOMER_ID"))


def hold_key(code: Any, cart_id: Any) -> str:
    return PREFIX_HOLD + normalise_code(code) + "#" + _identifier(cart_id, "INVALID_CART_ID")


def redeem_key(code: Any, order_id: Any) -> str:
    return PREFIX_REDEEM + normalise_code(code) + "#" + _identifier(order_id, "INVALID_ORDER_ID")


# ── validation (coupons section 5.4) ──────────────────────────────────────────

def _whole_rupee_paise(value: Any, *, field: str, allow_zero: bool = False) -> int:
    """An integer-paise amount that is a whole number of rupees, or refuse it.

    Two separate refusals, and the second is the interesting one:

    * a float, a bool or a fractional `Decimal` is refused BY TYPE through
      `money.positive_paise` - never coerced, never rounded;
    * a value that is not a whole multiple of 100 paise is refused as
      `SUB_RUPEE_DISCOUNT_NOT_SUPPORTED`, because the Wix coupon service's money fields are
      JSON `number` in decimal rupees and this release emits a whole-rupee `int` at that
      boundary. Rounding would silently change what a customer was promised, and `2500` basis
      points rounded to `25` is a different coupon from 2.5%.
    """
    if allow_zero and value == 0 and type(value) is int:
        return 0
    try:
        paise = money.positive_paise(value)
    except ValueError as error:
        raise CouponValidationError(field, "amount must be positive integer paise") from error
    if paise % PAISE_PER_RUPEE:
        raise CouponValidationError(
            "SUB_RUPEE_DISCOUNT_NOT_SUPPORTED",
            f"{field} must be a whole number of rupees in this release")
    return paise


def _positive_int(value: Any, *, field: str, minimum: int = 1,
                  maximum: int = MAX_PAISE) -> int:
    if isinstance(value, bool) or type(value) is not int or not minimum <= value <= maximum:
        raise CouponValidationError(field, f"{field} must be an integer >= {minimum}")
    return value


def _epoch_ms(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or type(value) is not int or value < WIX_MIN_TIME_MS:
        raise CouponValidationError(
            field, f"{field} must be epoch milliseconds >= {WIX_MIN_TIME_MS}")
    return value


def _text(value: Any, *, field: str, maximum: int) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise CouponValidationError(field, f"{field} must be a string")
    text = value.strip()
    if not 1 <= len(text) <= maximum:
        raise CouponValidationError(field, f"{field} must be 1 to {maximum} characters")
    return text


def _scope(payload: Dict[str, Any], item: Dict[str, Any]) -> bool:
    """Validate the scope triple onto `item`. Returns True when a scope was supplied.

    The rule is transcribed from Wix's own prose rather than inferred: `namespace` is `stores`
    on this release, a `group` name requires an `entityId`, and site-wide means no group at all.
    """
    namespace = payload.get("scopeNamespace")
    group = payload.get("scopeGroupName")
    entity = payload.get("scopeEntityId")
    if namespace is None and group is None and entity is None:
        return False
    if namespace != SCOPE_NAMESPACE:
        raise CouponValidationError("INVALID_SCOPE",
                                    f"scopeNamespace must be {SCOPE_NAMESPACE!r}")
    item["scopeNamespace"] = SCOPE_NAMESPACE
    if group is None:
        if entity is not None:
            raise CouponValidationError("INVALID_SCOPE",
                                        "scopeEntityId needs a scopeGroupName")
        return True
    if group not in SCOPE_GROUPS:
        raise CouponValidationError("INVALID_SCOPE",
                                    f"scopeGroupName must be one of {SCOPE_GROUPS}")
    item["scopeGroupName"] = group
    item["scopeEntityId"] = _text(entity, field="INVALID_SCOPE", maximum=128)
    return True


def _behaviour(payload: Dict[str, Any], item: Dict[str, Any]) -> str:
    """Validate exactly one discount kind onto `item`, and return it.

    Exactly one, refused here rather than at Wix, because Wix's `Specification.type` is
    read-only and derived from whichever discount field was set - so a payload carrying two
    would be accepted by the schema and mean something nobody chose.
    """
    kind = payload.get("discountKind")
    if kind not in DISCOUNT_KINDS:
        raise CouponValidationError("INVALID_DISCOUNT_KIND",
                                    f"discountKind must be one of {DISCOUNT_KINDS}")
    supplied = [attribute for attribute in ("moneyOffPaise", "percentOffBps", "fixedPricePaise",
                                            "buyX", "buyY")
                if payload.get(attribute) is not None]
    expected = {MONEY_OFF: ["moneyOffPaise"], PERCENT_OFF: ["percentOffBps"],
                FIXED_PRICE: ["fixedPricePaise"], FREE_SHIPPING: [],
                BUY_X_GET_Y: ["buyX", "buyY"]}[kind]
    if sorted(supplied) != sorted(expected):
        raise CouponValidationError(
            "INVALID_DISCOUNT_KIND",
            f"{kind} requires exactly {expected or 'no amount field'}")
    if kind == MONEY_OFF:
        item["moneyOffPaise"] = _whole_rupee_paise(payload["moneyOffPaise"],
                                                  field="INVALID_AMOUNT")
    elif kind == FIXED_PRICE:
        item["fixedPricePaise"] = _whole_rupee_paise(payload["fixedPricePaise"],
                                                    field="INVALID_AMOUNT")
    elif kind == PERCENT_OFF:
        bps = _positive_int(payload["percentOffBps"], field="INVALID_PERCENT",
                            maximum=MAX_PERCENT_OFF_BPS)
        if bps % PAISE_PER_RUPEE:
            raise CouponValidationError(
                "SUB_RUPEE_DISCOUNT_NOT_SUPPORTED",
                "percentOffBps must be a whole percent in this release")
        item["percentOffBps"] = bps
    elif kind == BUY_X_GET_Y:
        item["buyX"] = _positive_int(payload["buyX"], field="INVALID_BUY_X_GET_Y")
        item["buyY"] = _positive_int(payload["buyY"], field="INVALID_BUY_X_GET_Y")
    item["discountKind"] = kind
    return kind


def validate_definition(payload: Any, *, created_by: Any = None,
                        clock: Clock = _default_clock) -> Dict[str, Any]:
    """Turn an external create payload into a storable definition row, or refuse it.

    Nothing here touches Wix and nothing here writes. A refusal therefore means no coupon was
    created on either side, which is what makes the local claim the first line of defence and
    Wix's own uniqueness rule the second.
    """
    if not isinstance(payload, dict):
        raise CouponValidationError("INVALID_PAYLOAD", "a coupon payload object is required")
    if payload.get("discountedCycleCount") is not None:
        raise CouponValidationError(
            "DISCOUNTED_CYCLE_COUNT_NOT_SUPPORTED",
            "discountedCycleCount applies to the pricingPlans scope, and this scope is stores")
    unknown = sorted(set(payload) - set(CREATE_FIELDS))
    if unknown:
        raise CouponValidationError("UNSUPPORTED_FIELD",
                                    f"unsupported coupon fields: {', '.join(unknown)}")

    currency = payload.get("currency", CURRENCY)
    # Compared explicitly, never inferred from an amount. An amount tells you a magnitude, not
    # which currency it is in, and a wrong currency here is a wrong price charged.
    if currency != CURRENCY:
        raise CouponValidationError("INVALID_CURRENCY", f"currency must be {CURRENCY!r}")

    code_upper = normalise_code(payload.get("code"))
    now = _now_seconds(clock)
    item: Dict[str, Any] = {
        KEY_ATTRIBUTE: PREFIX_DEFINITION + code_upper,
        "couponId": identifiers.new_uuid7(now_ms=now * 1000),
        "code": unicodedata.normalize("NFKC", payload["code"]).strip(),
        "name": _text(payload.get("name"), field="INVALID_NAME", maximum=MAX_NAME_LENGTH),
        "wixMirrorState": MIRROR_PENDING,
        STATUS_ATTRIBUTE: STATUS_ACTIVE,
        "usageCount": 0,
        "limitedToOneItem": bool(payload.get("limitedToOneItem", False)),
        "currency": CURRENCY,
        "policyVersion": POLICY_VERSION,
        "createdAt": now,
        "updatedAt": now,
    }
    if created_by is not None:
        item["createdBy"] = _identifier(created_by, "INVALID_CREATED_BY")

    kind = _behaviour(payload, item)
    has_scope = _scope(payload, item)

    minimum = payload.get("minimumSubtotalPaise")
    if minimum is not None:
        item["minimumSubtotalPaise"] = _whole_rupee_paise(
            minimum, field="INVALID_MINIMUM_SUBTOTAL", allow_zero=True)

    # The one documented exception, enforced in BOTH directions: free shipping cannot carry a
    # scope, and its minimum subtotal is optional. Every other kind needs one or the other, or
    # the coupon applies to everything with no floor.
    if kind == FREE_SHIPPING:
        if has_scope:
            raise CouponValidationError("FREE_SHIPPING_CANNOT_CARRY_SCOPE",
                                       "a freeShipping coupon may not carry a scope")
    elif not has_scope and minimum is None:
        raise CouponValidationError(
            "SCOPE_OR_MINIMUM_SUBTOTAL_REQUIRED",
            "every kind except FREE_SHIPPING needs a scope or a minimum subtotal")

    item["startTimeMs"] = _epoch_ms(payload.get("startTimeMs"), field="INVALID_START_TIME")
    expiry = payload.get("expirationTimeMs")
    if expiry is not None:
        item["expirationTimeMs"] = _epoch_ms(expiry, field="INVALID_EXPIRATION_TIME")
        if item["expirationTimeMs"] <= item["startTimeMs"]:
            raise CouponValidationError("INVALID_EXPIRATION_TIME",
                                        "expirationTimeMs must be after startTimeMs")

    for field in ("usageLimit", "limitPerCustomer"):
        value = payload.get(field)
        if value is not None:
            item[field] = _positive_int(value, field="INVALID_" + (
                "USAGE_LIMIT" if field == "usageLimit" else "LIMIT_PER_CUSTOMER"))

    tags = payload.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or len(tags) > MAX_TAGS:
            raise CouponValidationError("INVALID_TAGS",
                                        f"tags must be a list of at most {MAX_TAGS} strings")
        item["tags"] = [_text(tag, field="INVALID_TAGS", maximum=MAX_TAG_LENGTH)
                        for tag in tags]
    return item


# ── writes ────────────────────────────────────────────────────────────────────

def claim(table: Any, definition: Dict[str, Any]) -> bool:
    """Conditionally write the definition row. True if won, False if the code is already issued.

    This conditional put IS the uniqueness guarantee: the partition key is the normalised code,
    so concurrent creates serialise in the database rather than in our code. Wix's own
    site-level uniqueness rule is the second line of defence, never the first.
    """
    key = definition.get(KEY_ATTRIBUTE)
    if not isinstance(key, str) or not key.startswith(PREFIX_DEFINITION):
        raise CouponValidationError("INVALID_PAYLOAD", "claim needs a definition row")
    try:
        table.put_item(Item=dict(definition),
                       ConditionExpression=f"attribute_not_exists({KEY_ATTRIBUTE})")
        return True
    except Exception as error:  # noqa: BLE001 - re-raised below unless it is a lost race
        if _is_conditional_failure(error):
            return False
        raise CouponStoreUnavailable(
            f"could not claim a coupon: {type(error).__name__}") from error


def create(table: Any, payload: Any, *, created_by: Any = None,
           clock: Clock = _default_clock) -> Dict[str, Any]:
    """Validate, then claim. Raises `CouponConflict` when the normalised code already exists."""
    definition = validate_definition(payload, created_by=created_by, clock=clock)
    if not claim(table, definition):
        raise CouponConflict(message="this coupon code is already issued")
    return definition


def _get(table: Any, key: str) -> Optional[Dict[str, Any]]:
    """One exact-key read. A storage failure raises rather than answering "absent".

    Absence is a decision input here - `evaluate` turns it into `UNKNOWN_CODE` - so a throttle
    allowed to look like absence would refuse a live coupon, and worse, would let a duplicate
    be issued on the create path.
    """
    try:
        return table.get_item(Key={KEY_ATTRIBUTE: key}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise CouponStoreUnavailable(
            f"could not read a coupon row: {type(error).__name__}") from error


def get_definition(table: Any, code: Any) -> Optional[Dict[str, Any]]:
    return _get(table, definition_key(code))


def customer_uses(table: Any, code: Any, customer_id: Any) -> int:
    row = _get(table, use_key(code, customer_id))
    return int((row or {}).get("uses") or 0)


def redemption(table: Any, code: Any, order_id: Any) -> Optional[Dict[str, Any]]:
    return _get(table, redeem_key(code, order_id))


def list_by_status(table: Any, status: Any, *, limit: int = 50,
                   start_key: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The staff list, through `status-index`. The only non-exact-key access in this module.

    Sparse by construction: only definition rows carry `status`, so counters, holds and
    redemption records never enter the index. `createdAt` is the range key so a query stays
    bounded to a window instead of reading a whole low-cardinality status partition.
    """
    if status not in STATUSES:
        raise CouponValidationError("INVALID_STATUS", f"status must be one of {STATUSES}")
    request: Dict[str, Any] = {
        "IndexName": STATUS_INDEX,
        "KeyConditionExpression": "#status = :status",
        "ExpressionAttributeNames": {"#status": STATUS_ATTRIBUTE},
        "ExpressionAttributeValues": {":status": status},
        "ScanIndexForward": False,
        "Limit": _positive_int(limit, field="INVALID_LIMIT", maximum=200),
    }
    if start_key:
        request["ExclusiveStartKey"] = start_key
    try:
        return table.query(**request)
    except Exception as error:  # noqa: BLE001
        raise CouponStoreUnavailable(
            f"could not list coupons: {type(error).__name__}") from error


def mark_mirrored(table: Any, code: Any, wix_coupon_id: Any, *,
                  clock: Clock = _default_clock) -> Dict[str, Any]:
    """Record the Wix id and flip the mirror state. One conditional `UpdateItem`.

    Conditional on the row existing, so a mirror state can never be written for a coupon we
    never claimed.
    """
    identifier = _identifier(wix_coupon_id, "INVALID_WIX_COUPON_ID")
    return _update(
        table, definition_key(code),
        update="SET wixCouponId = :id, wixMirrorState = :state, updatedAt = :now",
        condition=f"attribute_exists({KEY_ATTRIBUTE})",
        values={":id": identifier, ":state": MIRROR_DONE, ":now": _now_seconds(clock)},
        failure="UNKNOWN_CODE")


def deactivate(table: Any, code: Any, *, clock: Clock = _default_clock) -> Dict[str, Any]:
    """Mark the coupon `INACTIVE` locally. Never a delete.

    Applied LOCALLY FIRST and only then asked of Wix, which is the opposite order from
    creation and deliberately so: a coupon that is INACTIVE with us and still active in Wix is
    refused by `evaluate` before `Add Coupon` is ever called, so the local state binds. The
    reverse order would leave a window in which we believe a coupon is live and Wix has already
    switched it off.

    There is no delete anywhere in this module for a definition or a redemption record.
    Deactivation is reversible and preserves the audit trail; deletion destroys the definition
    a settled order references.
    """
    return _update(
        table, definition_key(code),
        update="SET #status = :status, updatedAt = :now",
        condition=f"attribute_exists({KEY_ATTRIBUTE})",
        values={":status": STATUS_INACTIVE, ":now": _now_seconds(clock)},
        names={"#status": STATUS_ATTRIBUTE},
        failure="UNKNOWN_CODE")


def _update(table: Any, key: str, *, update: str, condition: str,
            values: Dict[str, Any], names: Optional[Dict[str, str]] = None,
            failure: str = "CONDITION_FAILED") -> Dict[str, Any]:
    """One conditional `UpdateItem` on an exact key, returning the updated attributes."""
    request: Dict[str, Any] = {
        "Key": {KEY_ATTRIBUTE: key},
        "UpdateExpression": update,
        "ConditionExpression": condition,
        "ExpressionAttributeValues": values,
        "ReturnValues": "ALL_NEW",
    }
    if names:
        request["ExpressionAttributeNames"] = names
    try:
        return table.update_item(**request).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise CouponError(failure, "the coupon row did not meet the required condition") \
                from None
        raise CouponStoreUnavailable(
            f"could not update a coupon row: {type(error).__name__}") from error


def hold(table: Any, *, code: Any, cart_id: Any, ttl_seconds: int = HOLD_TTL_SECONDS,
         clock: Clock = _default_clock) -> Dict[str, Any]:
    """Reserve a coupon for one cart. ONE conditional `UpdateItem`, no preceding read.

    DECISION 5. The existence of a hold is an attribute of the definition row, so taking a hold
    is a conditional write on a key we already know:

        attribute_not_exists(activeHoldCartId)   nobody holds it
        OR activeHoldCartId = :me                this cart already holds it, so re-taking is
                                                 idempotent rather than a conflict
        OR activeHoldExpiresAtMs < :now          the previous hold lapsed

    The alternative - looking for `COUPONHOLD#` rows - needs a prefix query or a scan, and a
    money decision must not be made from either. A `GetItem` first would be worse than useless:
    it would be a read-modify-write, and two carts reading "free" at the same moment would both
    proceed.

    The `COUPONHOLD#` row written afterwards is an AUDIT record and is never read to make a
    decision. It is written second on purpose: if it fails, the authoritative hold still stands
    and the only loss is a log line.
    """
    code_upper = normalise_code(code)
    cart = _identifier(cart_id, "INVALID_CART_ID")
    now = _now_seconds(clock)
    expires_at_ms = (now + _positive_int(ttl_seconds, field="INVALID_TTL",
                                         maximum=86400)) * 1000
    try:
        updated = table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_DEFINITION + code_upper},
            UpdateExpression=("SET activeHoldCartId = :me, activeHoldExpiresAtMs = :expires, "
                              "updatedAt = :at"),
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) AND (" + HOLD_CONDITION
                                 + ")"),
            # `:now` is epoch MILLISECONDS, because `activeHoldExpiresAtMs` is, and comparing a
            # millisecond field against a second value would treat every live hold as lapsed.
            ExpressionAttributeValues={":me": cart, ":expires": expires_at_ms,
                                       ":now": now * 1000, ":at": now},
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise CouponHeldByAnotherCart(
                "another cart holds this coupon") from None
        raise CouponStoreUnavailable(
            f"could not hold a coupon: {type(error).__name__}") from error

    table.put_item(Item={KEY_ATTRIBUTE: PREFIX_HOLD + code_upper + "#" + cart,
                         "kind": "COUPON_HOLD", "code": code_upper, "cartId": cart,
                         "expiresAtEpoch": now + ttl_seconds, "heldAt": now})
    return {"held": True, "cartId": cart, "expiresAtMs": expires_at_ms,
            "coupon": updated}


def release(table: Any, *, code: Any, cart_id: Any,
            clock: Clock = _default_clock) -> Dict[str, Any]:
    """Drop this cart's hold. One conditional `UpdateItem`, then delete the audit row.

    The same condition as `hold`, so a cart can only clear a hold it owns or one that has
    already lapsed - releasing another live cart's hold would hand a single-use coupon to
    whoever asked second.
    """
    code_upper = normalise_code(code)
    cart = _identifier(cart_id, "INVALID_CART_ID")
    now = _now_seconds(clock)
    try:
        table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_DEFINITION + code_upper},
            UpdateExpression=("REMOVE activeHoldCartId, activeHoldExpiresAtMs "
                              "SET updatedAt = :at"),
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) AND (" + HOLD_CONDITION
                                 + ")"),
            ExpressionAttributeValues={":me": cart, ":now": now * 1000, ":at": now},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise CouponHeldByAnotherCart("another cart holds this coupon") from None
        raise CouponStoreUnavailable(
            f"could not release a coupon: {type(error).__name__}") from error
    _delete_hold(table, code_upper, cart)
    return {"released": True, "cartId": cart}


def _delete_hold(table: Any, code_upper: str, cart_id: str) -> None:
    """Delete one `COUPONHOLD#` audit row. The ONLY delete in this module.

    By explicit delete, never by TTL: a hold is released when the cart is paid or abandoned,
    and a TTL would make that expiry silent. There is deliberately no function here that can
    delete a `COUPON#` or a `COUPONREDEEM#` row.
    """
    try:
        table.delete_item(Key={KEY_ATTRIBUTE: PREFIX_HOLD + code_upper + "#" + cart_id})
    except Exception as error:  # noqa: BLE001
        raise CouponStoreUnavailable(
            f"could not delete a coupon hold: {type(error).__name__}") from error


def _add_counter(table: Any, key: str, attribute: str, *, limit: Optional[int],
                 extra: Dict[str, Any]) -> bool:
    """Atomic `ADD` of one, guarded by the limit when there is one. True if counted.

    Atomic rather than read-then-write, because a read-then-write loses a concurrent race and
    the whole point of a usage limit is that it holds under concurrency.

    `limit is None` means NO condition is applied and the row is still incremented, which is
    the no-limit branch stated in the design: a coupon without a per-customer limit still keeps
    an audit count of who used it. Omitting the increment there would make "unlimited" and
    "never used" indistinguishable in the data.
    """
    update = "ADD #counter :one"
    values: Dict[str, Any] = {":one": 1}
    names: Dict[str, str] = {"#counter": attribute}
    if extra:
        update += " SET " + ", ".join(f"#{name} = :{name}" for name in extra)
        names.update({f"#{name}": name for name in extra})
        values.update({f":{name}": value for name, value in extra.items()})
    request: Dict[str, Any] = {
        "Key": {KEY_ATTRIBUTE: key},
        "UpdateExpression": update,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }
    if limit is not None:
        request["ConditionExpression"] = ("attribute_not_exists(#counter) "
                                         "OR #counter < :limit")
        values[":limit"] = limit
    try:
        table.update_item(**request)
        return True
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return False
        raise CouponStoreUnavailable(
            f"could not move a coupon counter: {type(error).__name__}") from error


def commit_redemption(table: Any, *, code: Any, cart_id: Any, order_id: Any,
                      customer_id: Any, clock: Clock = _default_clock) -> Dict[str, Any]:
    """Record one terminal redemption. Idempotent on `(code, order_id)`.

    Called AFTER capture is verified, from whichever function performs the internal-order write
    - `order_keys` only mints an `orderId` once a provider readback has confirmed the capture,
    so an `orderId` existing is itself the evidence that money moved.

    `cart_id` is a parameter rather than a second read. The caller already asserts the
    purchased snapshot's cart is present before reaching this point, so one argument costs
    nothing where an extra `GetItem` would cost a round trip on the finalization path.

    ORDER IS LOAD-BEARING: claim, then counters, then the hold delete.

    The claim is irreversible and the counters are not. A crash between them leaves a coupon
    correctly marked used for this order with an undercounted total, which a replay repairs
    because the claim is idempotent and the `ADD`s only run when the claim was newly won. The
    reverse order would double-count on every replay.

    A counter that the limit refuses is REPORTED, not raised. Capture is already verified by
    the time this runs, so refusing here would leave a paid order with no redemption record -
    the one outcome this path must never produce. Eligibility is refused earlier, by `evaluate`
    and by `hold`.
    """
    code_upper = normalise_code(code)
    cart = _identifier(cart_id, "INVALID_CART_ID")
    order = _identifier(order_id, "INVALID_ORDER_ID")
    customer = _identifier(customer_id, "INVALID_CUSTOMER_ID")
    now = _now_seconds(clock)

    record = {
        KEY_ATTRIBUTE: PREFIX_REDEEM + code_upper + "#" + order,
        "kind": "COUPON_REDEMPTION", "code": code_upper, "cartId": cart,
        "orderId": order, "customerId": customer, "redeemedAt": now,
        "policyVersion": POLICY_VERSION,
    }
    try:
        table.put_item(Item=record,
                       ConditionExpression=f"attribute_not_exists({KEY_ATTRIBUTE})")
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            # The idempotency contract: already redeemed for this order, so nothing moves.
            return {"committed": False, "code": code_upper, "orderId": order}
        raise CouponStoreUnavailable(
            f"could not claim a coupon redemption: {type(error).__name__}") from error

    definition = _get(table, PREFIX_DEFINITION + code_upper) or {}
    usage_limit = definition.get("usageLimit")
    per_customer = definition.get("limitPerCustomer")

    counted = _add_counter(table, PREFIX_DEFINITION + code_upper, "usageCount",
                           limit=None if usage_limit is None else int(usage_limit),
                           extra={"updatedAt": now})
    customer_counted = _add_counter(
        table, PREFIX_USE + code_upper + "#" + customer, "uses",
        limit=None if per_customer is None else int(per_customer),
        extra={"code": code_upper, "customerId": customer, "updatedAt": now})

    _delete_hold(table, code_upper, cart)
    return {"committed": True, "code": code_upper, "orderId": order, "cartId": cart,
            "customerId": customer, "usageCounted": counted,
            "customerUsageCounted": customer_counted}


# ── eligibility ───────────────────────────────────────────────────────────────

def evaluate(definition: Optional[Dict[str, Any]], *, cart_id: Any = None,
             customer_uses_count: int = 0, clock: Clock = _default_clock) -> str:
    """The eligibility verdict for one coupon, one cart and one customer. Never an amount.

    Pure: it takes rows that have already been read by exact key and returns one of `VERDICTS`.
    Keeping it pure is what lets the handler answer without a second round trip and what lets a
    test enumerate every refusal without a table at all.

    Order matters for the answer a customer sees. `WIX_MIRROR_INCOMPLETE` comes before the
    time checks because a coupon Wix does not know about would be accepted by us and refused by
    `Add Coupon`, and the customer would watch a discount appear and then vanish. Refusing it
    here is the fail-closed answer.
    """
    if not definition:
        return UNKNOWN_CODE
    if definition.get(STATUS_ATTRIBUTE) != STATUS_ACTIVE:
        return NOT_ACTIVE
    if definition.get("wixMirrorState") != MIRROR_DONE:
        return WIX_MIRROR_INCOMPLETE

    now_ms = _now_seconds(clock) * 1000
    start = definition.get("startTimeMs")
    if start is not None and now_ms < int(start):
        return NOT_STARTED
    expiry = definition.get("expirationTimeMs")
    if expiry is not None and now_ms >= int(expiry):
        return EXPIRED

    usage_limit = definition.get("usageLimit")
    if usage_limit is not None and int(definition.get("usageCount") or 0) >= int(usage_limit):
        return USAGE_LIMIT_REACHED
    per_customer = definition.get("limitPerCustomer")
    if per_customer is not None and int(customer_uses_count) >= int(per_customer):
        return CUSTOMER_LIMIT_REACHED

    holder = definition.get(HOLD_CART_ATTRIBUTE)
    if holder:
        held_until = int(definition.get(HOLD_EXPIRY_ATTRIBUTE) or 0)
        if held_until > now_ms and (cart_id is None or holder != cart_id):
            return HELD_BY_ANOTHER_CART
    return ELIGIBLE


# ── the amount, for the one surface that has no Wix cart to ask ───────────────

def _amount_paise(value: Any, *, field: str, allow_zero: bool = True,
                  maximum: int = MAX_PAISE) -> int:
    """An integer-paise amount, refused BY TYPE rather than coerced.

    Separate from `_whole_rupee_paise`, and the difference is the whole reason this one exists:
    that helper additionally demands a whole number of rupees, because what it validates is
    bound for Wix's decimal-rupee money fields. A COLLECTION is not bound for Wix - it is a
    total we already hold - and `₹123.45` is an ordinary invoice, so applying the whole-rupee
    rule to it would refuse most real inputs.

    A DynamoDB number arrives as `Decimal`, so an integral `Decimal` is accepted and converted
    through `int(Decimal(str(value)))`; a fractional one is refused rather than rounded. `bool`
    is refused first, before any numeric test, because `True == 1` and a flag read as one paise
    is a wrong price nobody would spot.
    """
    if isinstance(value, bool):
        raise CouponValidationError(field, f"{field} must be integer paise, not a bool")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise CouponValidationError(
                field, f"{field} must be an exact integer number of paise")
        value = int(Decimal(str(value)))
    if type(value) is not int:
        raise CouponValidationError(field, f"{field} must be integer paise")
    if value < 0 or (value == 0 and not allow_zero):
        raise CouponValidationError(field, f"{field} must be a positive integer paise amount")
    if value > maximum:
        raise CouponValidationError(field, f"{field} must not exceed {maximum}")
    return value


def discount_paise(definition: Optional[Dict[str, Any]], *, collection_paise: Any) -> int:
    """The discount in integer paise this definition applies to one collection total.

    Why this exists at all, given everything above says the amount is not ours
    -------------------------------------------------------------------------
    `evaluate` deliberately returns a verdict and never a figure, and that remains correct for
    the WEBSITE: there, a coupon reaches a customer's total by being mirrored into Wix and
    applied to a Wix cart, and the amount is Wix's answer to `Calculate Cart`. Two authorities,
    one of them Wix's, and this module is not it.

    A Pay Flow invoice is NOT a Wix cart. There is no cart id, no catalogue line items and
    therefore no `Calculate Cart` to ask - so on that surface the question "what is this coupon
    worth" has no Wix answer to defer to. Minting a throwaway Wix cart per invoice was
    considered and rejected: it needs line items an invoice does not have, it would invent
    catalogue entries to carry an arbitrary staff-entered amount, and it would put a
    third-party network call inside the GST invoice-numbering path, where a timeout burns a
    sequence number on an invoice that was never raised.

    So the amount is computed here, from the definition this module already owns, and NOWHERE
    else. That is the point of the location: the attributes read below are exactly
    `KIND_AMOUNT_ATTRIBUTE`'s values, the same ones `wix_coupons.specification` sends, and
    `tests/test_wix_coupons_contract.py` pins the two to the same attributes kind for kind. One
    coupon definition, one reading of it, two renderings - not two discount engines.

    What it refuses, and why refusing is the correct answer
    ------------------------------------------------------
    `FREE_SHIPPING` and `BUY_X_GET_Y` raise `COUPON_KIND_UNSUPPORTED`. Both need context an
    invoice-level collection cannot supply - a shipping charge to waive, or line items to count
    - so there is no honest number to return. Returning zero would be worse than refusing: the
    customer was promised a discount, the staff member would see the coupon accepted, and the
    invoice would collect the full amount. A refusal is visible; a silent zero is not.

    `minimumSubtotalPaise` is enforced here too, as `MINIMUM_SUBTOTAL`, for the same reason: a
    coupon whose floor is not met has not been earned, and quietly discounting nothing would
    report success for a coupon that did not apply.

    Pure: no table, no network, no clock. Eligibility (`evaluate`) is a separate question asked
    separately; this answers only the arithmetic, and only for an already-eligible definition.
    """
    if not isinstance(definition, dict):
        raise CouponValidationError("UNKNOWN_CODE", "a coupon definition row is required")
    collection = _amount_paise(collection_paise, field="INVALID_COLLECTION")

    minimum = definition.get("minimumSubtotalPaise")
    if minimum is not None and collection < _amount_paise(
            minimum, field="INVALID_MINIMUM_SUBTOTAL"):
        raise CouponValidationError(
            "MINIMUM_SUBTOTAL",
            "this coupon requires a larger subtotal than the amount it was applied to")

    kind = definition.get("discountKind")
    if kind == MONEY_OFF:
        # Clamped at the collection: a coupon cannot make a total negative, and `₹500 off` on a
        # `₹300` invoice is `₹300` off, not a `₹200` credit note.
        return min(_amount_paise(definition.get("moneyOffPaise"), field="INVALID_AMOUNT",
                                 allow_zero=False), collection)
    if kind == PERCENT_OFF:
        bps = _amount_paise(definition.get("percentOffBps"), field="INVALID_PERCENT",
                            allow_zero=False, maximum=MAX_PERCENT_OFF_BPS)
        # `round_half_up` on integer paise and integer basis points, never `* rate / 100`. At
        # 10000 bps this is the whole collection, so the clamp is an identity rather than a cap
        # - it is there because the clamp must not depend on the rate being well-formed.
        return min(checkout_pricing.round_half_up(collection, bps), collection)
    if kind == FIXED_PRICE:
        # `FIXED_PRICE` names the price that remains, so the discount is the difference. A fixed
        # price above the collection discounts nothing rather than inflating the invoice.
        return max(0, collection - _amount_paise(definition.get("fixedPricePaise"),
                                                 field="INVALID_AMOUNT", allow_zero=False))
    if kind in (FREE_SHIPPING, BUY_X_GET_Y):
        raise CouponValidationError(
            "COUPON_KIND_UNSUPPORTED",
            f"{kind} needs line-item or shipping context that a collection total cannot supply")
    raise CouponValidationError("INVALID_DISCOUNT_KIND",
                                f"discountKind must be one of {DISCOUNT_KINDS}")


__all__ = [
    "BUY_X_GET_Y", "CODE_PATTERN", "CREATE_FIELDS", "CURRENCY", "CouponConflict", "CouponError",
    "CouponHeldByAnotherCart", "CouponStoreUnavailable", "CouponValidationError",
    "CUSTOMER_LIMIT_REACHED", "DEFAULT_TABLE_NAME", "DEFINITION_ATTRIBUTES", "DISCOUNT_KINDS",
    "ELIGIBLE", "EXPIRED", "FIXED_PRICE", "FREE_SHIPPING", "HELD_BY_ANOTHER_CART",
    "HOLD_CART_ATTRIBUTE", "HOLD_CONDITION", "HOLD_EXPIRY_ATTRIBUTE", "HOLD_TTL_SECONDS",
    "KEY_ATTRIBUTE", "KIND_AMOUNT_ATTRIBUTE", "MAX_CODE_LENGTH", "MAX_PERCENT_OFF_BPS",
    "MIRROR_DELETED", "MIRROR_DONE", "MIRROR_PENDING", "MIRROR_STATES", "MONEY_OFF",
    "NOT_ACTIVE", "NOT_STARTED", "PAISE_PER_RUPEE", "PERCENT_OFF", "POLICY_VERSION",
    "PREFIX_DEFINITION", "PREFIX_HOLD", "PREFIX_REDEEM", "PREFIX_USE", "SCOPE_GROUPS",
    "SCOPE_NAMESPACE", "STATUSES", "STATUS_ACTIVE", "STATUS_ATTRIBUTE", "STATUS_EXHAUSTED",
    "STATUS_INACTIVE", "STATUS_INDEX", "TABLE_ENV_KEY", "UNKNOWN_CODE", "USAGE_LIMIT_REACHED",
    "VERDICTS", "WIX_MIN_TIME_MS", "WIX_MIRROR_INCOMPLETE", "claim", "commit_redemption",
    "create", "customer_uses", "deactivate", "definition_key", "discount_paise", "evaluate",
    "get_definition",
    "hold", "hold_key", "list_by_status", "mark_mirrored", "normalise_code", "redeem_key",
    "redemption", "release", "use_key", "validate_definition",
]
