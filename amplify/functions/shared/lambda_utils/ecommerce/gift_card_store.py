"""The gift-card liability ledger. A balance we OWE, keyed on an HMAC of bearer value.

The code is BEARER VALUE, so it is never the key
------------------------------------------------
    giftCardKey = "GIFTCARD#" + HMAC-SHA256(pepper, NFKC(code).upper()).hexdigest()

An HMAC with a pepper, not a bare SHA-256: a code is 8 to 20 characters, and an 8-character code
over a small alphabet is inside brute-force range for a plain hash, so a leaked table would expose
live balances. The pepper lives in Secrets Manager (`GIFTCARD_PEPPER_SECRET`, by default
`wecare/prod/security/giftcard-pepper`), is referenced by secret id, and is read LAZILY at request
time through an INJECTED reader - never at module scope, because a module-scope read is cached for
the life of the execution environment and a rotation would not take effect until every warm
sandbox recycled.

This is the deliberate OPPOSITE of `coupon_store`, where the code *is* the partition key because a
coupon code is broadcast marketing material. `tests/test_gift_card_store.py` and
`tests/test_coupon_logging_and_vocabulary.py` pin the asymmetry from both sides so neither gets
"harmonised" into the other.

Logs carry `codeLast4` only, rendered `****1234` by `masked()`. The code never appears in full - not
in a log, not in an exception message, not in a URL. Correlation uses `giftCardId` (ours, a UUIDv7)
and `paymentAttemptId` (ours, a UUIDv7), both of which are loggable.

Every balance check is a CONDITION, never a read-then-write
------------------------------------------------------------
    hold     SET activeHold*        under  balancePaise >= :amount AND #status = :active
    credit   ADD balancePaise :amt  under  balancePaise <= :ceiling

A read-then-write would let two concurrent writers both pass a check they read a moment earlier,
so the floor and the ceiling are evaluated by DynamoDB inside the write itself. Nothing here
deletes a card or a pointer row - only a `GCHOLD#` audit row.

Every access is an exact-key operation
--------------------------------------
`get_item` / `put_item` / `update_item` on a fully specified partition key, plus the staff
`status-index` `Query`. No `scan`, no prefix query, no second index. DECISION 5 is what makes that
possible: the existence of a hold is an ATTRIBUTE of the card row (`activeHoldAttemptId`), so
taking or checking a hold is one operation on a known key rather than a search. A decision that
gates money cannot be made from a scan, and it cannot be made from a GSI either - a GSI is
eventually consistent.

No float, and one value ceiling
-------------------------------
Money is integer paise. The value ceiling is `MAX_VALUE_PAISE`, `99_999_999_999` paise
(`₹999,999,999.99`), asserted on issuance AND on every credit. `money.py`'s `9007199254740991`
remains the outer type bound; the binding constraint is ours.

TTL is disabled on this table and that is stronger than a convention. A gift-card row is a
liability. An expiring row is a disappearing debt. `expiresAtMs` changes what is PERMITTED; it never
removes what is OWED.
"""
from __future__ import annotations

import hmac
import re
import secrets as _secrets
import time
import unicodedata
from hashlib import sha256
from typing import Any, Callable, Dict, Mapping, Optional

from . import money
from .. import identifiers

#: Physical table. `GiftCard` -> `GiftCardsTable` under `check_data_model_drift.expected_table`'s
#: default pluralise-and-append rule, so no explicit-map entry is needed.
DEFAULT_TABLE_NAME = "stack-wecare-digital-GiftCardsTable"
TABLE_ENV_KEY = "GIFT_CARDS_TABLE"

#: Secret NAME, never a value. The secret holds the gift-card HMAC pepper under `PEPPER_FIELD`.
SECRET_ID = "wecare/prod/security/giftcard-pepper"
PEPPER_FIELD = "code_pepper"

#: The env var that may name a different pepper secret. The pepper is the HMAC key for EVERY
#: gift-card row lookup, so whichever secret this names must hold the value the cards were
#: issued under.
#:
#: This name is DEFINED here (one place) but READ by the handlers, never by this
#: module: `test_gift_card_store.py` forbids an `os` import here, because an env read
#: in the store would be ambient configuration. The store takes the resolved secret
#: id by injection (`read_pepper(..., secret_id=...)`); the handlers resolve it.
PEPPER_SECRET_ENV_KEY = "GIFTCARD_PEPPER_SECRET"


def resolve_pepper_secret_id(env: Mapping[str, str]) -> str:
    """Resolve the pepper's secret id from an INJECTED env mapping (never `os.environ` here -
    the store holds no ambient config):

      1. `GIFTCARD_PEPPER_SECRET`, when it is set;
      2. otherwise `SECRET_ID`, `wecare/prod/security/giftcard-pepper`.

    There is no other source. Every existing card key is an HMAC under the pepper VALUE, so the
    resolved secret must hold that byte-identical value; any other value makes every card
    unfindable.
    """
    return env.get(PEPPER_SECRET_ENV_KEY) or SECRET_ID

KEY_ATTRIBUTE = "giftCardKey"
STATUS_ATTRIBUTE = "status"
STATUS_INDEX = "status-index"

PREFIX_CARD = "GIFTCARD#"
PREFIX_HOLD = "GCHOLD#"
#: `GET /gift-cards/{giftCardId}` has to resolve a card by OUR id, and the only alternatives are a
#: `Scan` or a second GSI. A pointer row keeps every access an exact-key operation.
PREFIX_CARD_ID = "GCID#"

CURRENCY = "INR"
POLICY_VERSION = "giftcard-policy-2026-10-01"

STATUS_ACTIVE = "ACTIVE"
STATUS_DISABLED = "DISABLED"
STATUSES = (STATUS_ACTIVE, STATUS_DISABLED)

#: The most a card may hold: `₹999,999,999.99`. Asserted on issuance and, as a condition, on
#: every credit.
MAX_VALUE_PAISE = 99_999_999_999

#: `money.py`'s outer type bound, restated only so the relationship is explicit: nothing may
#: exceed it, but `MAX_VALUE_PAISE` above is the constraint that actually binds.
MONEY_CEILING_PAISE = 9007199254740991

#: Razorpay's documented minimum order amount. Orders Create answers
#: `BAD_REQUEST_ERROR` / "The amount must be at least INR 1.00" below it, at
#: `step: payment_initiation` - i.e. AFTER a hold would have been taken and the quote frozen,
#: which is the worst possible place for it. https://razorpay.com/docs/api/orders/create/
RAZORPAY_MIN_LEG_PAISE = 100

#: Crockford base32: no I, L, O or U, so a handwritten code cannot be transcribed into a
#: different one. 16 characters, inside the 8-20 bound below.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 16
#: A presented code must be 8 to 20 characters of `CODE_PATTERN`; anything else answers exactly
#: as an unknown code does.
MIN_CODE_LENGTH = 8
MAX_CODE_LENGTH = 20
CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")

MAX_PIN_LENGTH = 50

#: DECISION 5. The existence of a hold lives on the row whose key is already known, so taking or
#: checking one is ONE operation on `GIFTCARD#<codeHash>` rather than a prefix scan.
HOLD_ATTEMPT_ATTRIBUTE = "activeHoldAttemptId"
HOLD_PAISE_ATTRIBUTE = "activeHoldPaise"
HOLD_EXPIRY_ATTRIBUTE = "activeHoldExpiresAtMs"

HOLD_CONDITION = ("attribute_not_exists(activeHoldAttemptId) "
                  "OR activeHoldAttemptId = :me "
                  "OR activeHoldExpiresAtMs < :now")

#: A hold is advisory and short-lived: it reserves balance for one payment attempt while a
#: customer finishes paying, and an abandoned hold lapses instead of blocking the card.
HOLD_TTL_SECONDS = 900

#: Every attribute a card row may carry, DECISION 5's three hold attributes included. Enumerated
#: so a test can assert the code itself is not among them.
CARD_ATTRIBUTES = (
    KEY_ATTRIBUTE, "giftCardId", "codeLast4", "pinHash", "initialValuePaise", "balancePaise",
    "currency", STATUS_ATTRIBUTE, "issuedAtMs", "expiresAtMs", "issuedToContactId",
    "sourceOrderId", "policyVersion", "createdAt", "updatedAt", "createdBy",
    HOLD_ATTEMPT_ATTRIBUTE, HOLD_PAISE_ATTRIBUTE, HOLD_EXPIRY_ATTRIBUTE,
)


# ── errors ────────────────────────────────────────────────────────────────────

class GiftCardError(ValueError):
    """Base. Carries a machine-readable `code` so a handler never parses a message, and the HTTP
    `status` the gift-cards handler answers with."""

    status = 400

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class GiftCardValidationError(GiftCardError):
    """An external input was refused. Nothing was written and no balance moved."""


class GiftCardNotFound(GiftCardError):
    """Unknown code, malformed code, or a wrong PIN.

    One answer for all three, deliberately: three distinct answers would turn the endpoint into a
    code-validity oracle, and a gift-card code is bearer value.
    """

    status = 404

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_NOT_FOUND", message)


class GiftCardDisabled(GiftCardError):
    status = 428

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_DISABLED", message)


class GiftCardExpired(GiftCardError):
    status = 428

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_EXPIRED", message)


class MissingCurrency(GiftCardError):
    status = 428

    def __init__(self, message: str = ""):
        super().__init__("MISSING_CURRENCY", message)


class CurrencyNotSupported(GiftCardError):
    status = 400

    def __init__(self, message: str = ""):
        super().__init__("CURRENCY_NOT_SUPPORTED", message)


class InsufficientFunds(GiftCardError):
    status = 428

    def __init__(self, message: str = ""):
        super().__init__("INSUFFICIENT_FUNDS", message)


class GiftCardHeldByAnotherPurchase(GiftCardError):
    status = 409

    def __init__(self, message: str = ""):
        super().__init__("HELD_BY_ANOTHER_PURCHASE", message)


class GiftCardStoreUnavailable(RuntimeError):
    """Storage failed for a reason that is not a lost race.

    Its own type so a throttle or an outage can never be mistaken for "no such card" or "held by
    another purchase". A read failure reported as absence would refuse a live card.
    """


# ── clock ─────────────────────────────────────────────────────────────────────

def _default_clock() -> int:
    """Epoch SECONDS as an `int`, never `time.time()`'s float.

    The one place a float would otherwise reach a row that is later compared for exact equality.
    """
    return int(time.time())


Clock = Callable[[], int]
SecretReader = Callable[[str], Mapping[str, Any]]


def _now_seconds(clock: Clock) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int):
        raise GiftCardStoreUnavailable("clock must return integer epoch seconds")
    return value


def _is_conditional_failure(error: BaseException) -> bool:
    """True only for DynamoDB's conditional-check failure, however the client spells it.

    Consulted by `_put`, `hold`, `credit`, `disable` and `release`: the outcome of a condition
    is a decision input, while any other failure is `GiftCardStoreUnavailable`.
    """
    if type(error).__name__ == "ConditionalCheckFailedException":
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    return False


# ── the pepper, read by reference and lazily ───────────────────────────────────

def read_pepper(reader: SecretReader, *, secret_id: str = SECRET_ID) -> str:
    """The HMAC pepper, through an INJECTED reader, at the moment it is needed.

    `reader` is a callable taking a secret ID and returning the parsed secret mapping. This module
    holds no boto3 client, so it cannot read a secret at import even by accident - which is the
    structural version of the lazy-read rule rather than a promise to remember it.

    `secret_id` is resolved by the CALLER (via `resolve_pepper_secret_id(os.environ)`),
    which is where env reads legitimately live; this module takes it by injection, so pointing
    the pepper at a different secret is a configuration change alone.

    The returned value is never logged, never put in an exception message, and never appears in a
    logging expression - not even reduced to a bool. CodeQL's
    `py/clear-text-logging-sensitive-data` tracks taint across function boundaries and has already
    failed this build twice on a ternary over a key's truthiness.
    """
    secret = reader(secret_id)
    value = (secret or {}).get(PEPPER_FIELD)
    if not isinstance(value, str) or not value:
        raise GiftCardStoreUnavailable(
            f"{secret_id} carries no usable {PEPPER_FIELD}")
    return value


# ── codes ─────────────────────────────────────────────────────────────────────

def normalise_code(value: Any) -> str:
    """NFKC-normalise, strip and upper-case a gift-card code, or refuse it.

    Refuses by raising `GiftCardNotFound`, not a validation error: a malformed code must answer
    exactly as an unknown one does, so the endpoint cannot be ground into a validity oracle.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise GiftCardNotFound("a gift-card code string is required")
    text = unicodedata.normalize("NFKC", value).strip()
    if not MIN_CODE_LENGTH <= len(text) <= MAX_CODE_LENGTH or not CODE_PATTERN.match(text):
        raise GiftCardNotFound("the code is outside the documented shape")
    return text.upper()


def generate_code(*, length: int = CODE_LENGTH) -> str:
    """A fresh code from the Crockford alphabet, using `secrets` and never `random`.

    `lambda-snapstart-deploy.md` records why: with SnapStart on, the snapshot freezes the `random`
    PRNG state and every restored environment produces the same sequence. SnapStart is currently
    off on all 65 functions, but a gift-card code is exactly the class of value that must never
    repeat, and `core/url-shortener/handler.py` already sets the precedent.
    """
    if isinstance(length, bool) or type(length) is not int \
            or not MIN_CODE_LENGTH <= length <= MAX_CODE_LENGTH:
        raise GiftCardValidationError(
            "INVALID_CODE_LENGTH",
            f"a generated code must be {MIN_CODE_LENGTH} to {MAX_CODE_LENGTH} characters")
    return "".join(_secrets.choice(CODE_ALPHABET) for _ in range(length))


def code_hash(code: Any, *, pepper: str) -> str:
    """`HMAC-SHA256(pepper, NFKC(code).upper()).hexdigest()`. Never the code itself."""
    if not isinstance(pepper, str) or not pepper:
        raise GiftCardStoreUnavailable("a pepper is required to derive a card key")
    normalised = normalise_code(code)
    return hmac.new(pepper.encode("utf-8"), normalised.encode("utf-8"), sha256).hexdigest()


def code_last4(code: Any) -> str:
    """The only part of a code that is ever stored in clear or logged."""
    return normalise_code(code)[-4:]


def masked(last4: Any) -> str:
    """`****1234`, the one rendering of a code permitted in a log line.

    Takes the LAST FOUR, not the code, so a caller cannot pass a full code by mistake and have it
    silently truncated inside a logging expression.
    """
    text = str(last4 or "")
    if len(text) > 4:
        raise GiftCardValidationError(
            "CODE_IN_LOG",
            "masked() takes codeLast4, never a code; a full code must not reach a log line")
    return "****" + text


def card_key(code: Any, *, pepper: str) -> str:
    return PREFIX_CARD + code_hash(code, pepper=pepper)


def card_key_from_hash(hash_hex: Any) -> str:
    return PREFIX_CARD + _hash_hex(hash_hex)


def hold_key(hash_hex: Any, attempt_id: Any) -> str:
    return PREFIX_HOLD + _hash_hex(hash_hex) + "#" + _identifier(attempt_id, "INVALID_ATTEMPT_ID")


def card_id_key(gift_card_id: Any) -> str:
    return PREFIX_CARD_ID + _identifier(gift_card_id, "INVALID_GIFT_CARD_ID")


# ── validation ────────────────────────────────────────────────────────────────

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _hash_hex(value: Any) -> str:
    """A 64-character lowercase hex digest, or refuse.

    Validated rather than trusted so a caller cannot pass a raw code where a hash belongs - which
    is the one mistake that would put bearer value into a key.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not _HASH_PATTERN.match(value):
        raise GiftCardValidationError("INVALID_CODE_HASH",
                                      "a code hash must be 64 lowercase hex characters")
    return value


def _identifier(value: Any, code: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise GiftCardValidationError(code, f"{code.lower()} is required")
    text = value.strip()
    if len(text) > 128 or "#" in text:
        raise GiftCardValidationError(code, f"{code.lower()} is not a usable identifier")
    return text


def value_paise(value: Any, *, field: str = "INVALID_AMOUNT") -> int:
    """Positive integer paise within `MAX_VALUE_PAISE`. Floats and bools refused BY TYPE.

    The ceiling is asserted here rather than only at issuance, so every amount that reaches the
    ledger - an issued value, a hold, a credit - goes through it.
    """
    try:
        paise = money.positive_paise(value)
    except ValueError as error:
        raise GiftCardValidationError(field, "amount must be positive integer paise") from error
    if paise > MAX_VALUE_PAISE:
        raise GiftCardValidationError(
            field, f"amount must not exceed {MAX_VALUE_PAISE} paise")
    return paise


def _epoch_ms(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or type(value) is not int or value <= 0:
        raise GiftCardValidationError(field, f"{field} must be positive epoch milliseconds")
    return value


def assert_currency(value: Any, *, required: bool = True) -> str:
    """`INR`, compared EXPLICITLY. An amount tells you a magnitude, never a currency."""
    if value in (None, ""):
        if required:
            raise MissingCurrency("a currencyCode is required")
        return CURRENCY
    if not isinstance(value, str) or value.strip().upper() != CURRENCY:
        raise CurrencyNotSupported(f"only {CURRENCY} is supported")
    return CURRENCY


# ── reads ─────────────────────────────────────────────────────────────────────

def _get(table: Any, key: str) -> Optional[Dict[str, Any]]:
    """One exact-key, strongly consistent read. A storage failure RAISES, never answers absent.

    Absence is a decision input here, so a throttle allowed to look like absence would refuse a
    live card as unknown.
    """
    try:
        return table.get_item(Key={KEY_ATTRIBUTE: key}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise GiftCardStoreUnavailable(
            f"could not read a gift-card row: {type(error).__name__}") from error


def get_card(table: Any, *, code_hash: Any) -> Optional[Dict[str, Any]]:
    return _get(table, card_key_from_hash(code_hash))


def get_card_by_id(table: Any, *, gift_card_id: Any) -> Optional[Dict[str, Any]]:
    """Resolve our own `giftCardId` to the card, through the `GCID#` pointer row.

    Two exact-key reads rather than a `Scan` or a GSI. A GSI would be eventually consistent, and
    a staff read that lags is a staff read that reports a balance that has already moved.
    """
    pointer = _get(table, card_id_key(gift_card_id))
    if not pointer:
        return None
    return get_card(table, code_hash=pointer.get("codeHash"))


def list_by_status(table: Any, status: Any, *, limit: int = 50,
                   start_key: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The staff list, through `status-index`. The ONLY non-exact-key access in this module.

    Sparse by construction: only card rows carry `status`, so hold and pointer rows never enter
    the index. `createdAt` is the range key so a query stays bounded to a
    window rather than reading a whole low-cardinality status partition.
    """
    if status not in STATUSES:
        raise GiftCardValidationError("INVALID_STATUS", f"status must be one of {STATUSES}")
    if isinstance(limit, bool) or type(limit) is not int or not 1 <= limit <= 200:
        raise GiftCardValidationError("INVALID_LIMIT", "limit must be 1 to 200")
    request: Dict[str, Any] = {
        "IndexName": STATUS_INDEX,
        "KeyConditionExpression": "#status = :status",
        "ExpressionAttributeNames": {"#status": STATUS_ATTRIBUTE},
        "ExpressionAttributeValues": {":status": status},
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        request["ExclusiveStartKey"] = start_key
    try:
        return table.query(**request)
    except Exception as error:  # noqa: BLE001
        raise GiftCardStoreUnavailable(
            f"could not list gift cards: {type(error).__name__}") from error


def assert_spendable(card: Optional[Mapping[str, Any]], *, now_ms: int) -> Dict[str, Any]:
    """Refuse a card that is unknown, disabled or past its expiry, in that order.

    Order is deliberate: an unknown code and a wrong PIN already answer alike, and status comes
    before expiry so a card that is both disabled and expired reports the state an operator can
    act on.
    """
    if not card:
        raise GiftCardNotFound("no such gift card")
    if card.get(STATUS_ATTRIBUTE) != STATUS_ACTIVE:
        raise GiftCardDisabled("this gift card is disabled")
    expiry = card.get("expiresAtMs")
    if expiry is not None and int(now_ms) >= int(expiry):
        raise GiftCardExpired("this gift card has expired")
    return dict(card)


def verify_pin(card: Optional[Mapping[str, Any]], pin: Any, *, pepper: str) -> None:
    """Constant-time PIN comparison. A wrong PIN answers exactly as an unknown code does.

    `hmac.compare_digest`, never `==`: a short-circuiting comparison leaks the matching prefix
    length through timing, and a PIN is short enough for that to matter.
    """
    stored = (card or {}).get("pinHash")
    if not stored:
        if pin in (None, ""):
            return
        # A PIN presented for a card that has none is refused rather than ignored, so a caller
        # cannot discover which cards are PIN-protected.
        raise GiftCardNotFound("no such gift card")
    if pin in (None, ""):
        raise GiftCardNotFound("no such gift card")
    if not hmac.compare_digest(str(stored), pin_hash(pin, pepper=pepper)):
        raise GiftCardNotFound("no such gift card")


def pin_hash(pin: Any, *, pepper: str) -> str:
    """HMAC of the PIN. The PIN itself is never stored and never logged."""
    if isinstance(pin, bool) or not isinstance(pin, str) or not pin \
            or len(pin) > MAX_PIN_LENGTH:
        raise GiftCardValidationError("INVALID_PIN",
                                      f"a PIN must be 1 to {MAX_PIN_LENGTH} characters")
    if not isinstance(pepper, str) or not pepper:
        raise GiftCardStoreUnavailable("a pepper is required to hash a PIN")
    return hmac.new(pepper.encode("utf-8"), ("pin:" + pin).encode("utf-8"), sha256).hexdigest()


# ── writes ────────────────────────────────────────────────────────────────────

def _put(table: Any, item: Dict[str, Any], *, condition: Optional[str] = None,
         failure: str = "ALREADY_EXISTS") -> bool:
    try:
        # Spelled out rather than built as a kwargs dict, so the access-pattern enumeration test
        # can read the key off the call site. A `**request` splat is invisible to an AST walk.
        if condition:
            table.put_item(Item=dict(item), ConditionExpression=condition)
        else:
            table.put_item(Item=dict(item))
        return True
    except Exception as error:  # noqa: BLE001
        if condition and _is_conditional_failure(error):
            return False
        raise GiftCardStoreUnavailable(
            f"could not write a gift-card row ({failure}): {type(error).__name__}") from error


def issue(table: Any, *, initial_value_paise: Any, pepper: str, code: Optional[str] = None,
          pin: Optional[str] = None, expires_at_ms: Optional[int] = None,
          issued_to_contact_id: Optional[str] = None, source_order_id: Optional[str] = None,
          created_by: Optional[str] = None, currency: Any = CURRENCY,
          clock: Clock = _default_clock) -> Dict[str, Any]:
    """Issue one card and return the row plus the code, ONCE.

    The returned dict carries `code` so the staff route can show it exactly once; the stored row
    carries only `codeLast4`. Separating the two is what makes "the code is never stored in clear"
    a property of this function rather than a rule a caller has to remember.

    Only `wecare-gift-cards` calls this function, behind its Operator check: issuing a card
    creates a liability, so it is a staff action and no customer route reaches it.
    """
    assert_currency(currency)
    value = value_paise(initial_value_paise, field="INVALID_INITIAL_VALUE")
    now = _now_seconds(clock)
    issued_at_ms = now * 1000
    plain = normalise_code(code) if code is not None else generate_code()
    digest = code_hash(plain, pepper=pepper)

    item: Dict[str, Any] = {
        KEY_ATTRIBUTE: PREFIX_CARD + digest,
        "giftCardId": identifiers.new_uuid7(now_ms=issued_at_ms),
        "codeLast4": plain[-4:],
        "initialValuePaise": value,
        "balancePaise": value,
        "currency": CURRENCY,
        STATUS_ATTRIBUTE: STATUS_ACTIVE,
        "issuedAtMs": issued_at_ms,
        "policyVersion": POLICY_VERSION,
        "createdAt": now,
        "updatedAt": now,
    }
    if pin is not None:
        item["pinHash"] = pin_hash(pin, pepper=pepper)
    if expires_at_ms is not None:
        item["expiresAtMs"] = _epoch_ms(expires_at_ms, field="INVALID_EXPIRES_AT")
        if item["expiresAtMs"] <= issued_at_ms:
            raise GiftCardValidationError("INVALID_EXPIRES_AT",
                                          "expiresAtMs must be after issuedAtMs")
    for attribute, supplied, failure in (
            ("issuedToContactId", issued_to_contact_id, "INVALID_CONTACT_ID"),
            ("sourceOrderId", source_order_id, "INVALID_SOURCE_ORDER_ID"),
            ("createdBy", created_by, "INVALID_CREATED_BY")):
        if supplied is not None:
            item[attribute] = _identifier(supplied, failure)

    if not _put(table, item, condition=f"attribute_not_exists({KEY_ATTRIBUTE})"):
        raise GiftCardValidationError("CODE_ALREADY_ISSUED",
                                      "this gift-card code is already issued")
    # The `GCID#` pointer, so a staff read by our own id is an exact-key operation.
    _put(table, {KEY_ATTRIBUTE: PREFIX_CARD_ID + item["giftCardId"],
                 "kind": "GIFT_CARD_ID_POINTER", "codeHash": digest,
                 "codeLast4": item["codeLast4"], "createdAt": now})
    return {"card": item, "code": plain, "codeHash": digest}


def credit(table: Any, *, code_hash: Any, amount_paise: Any,
           clock: Clock = _default_clock) -> int:
    """Add to a balance, with `MAX_VALUE_PAISE` asserted IN THE CONDITION.

    The ceiling is a condition rather than a pre-read check for the same reason the hold's floor
    is: two concurrent credits that each pass a read-time check can together exceed it.

    A PLAIN ADDITION, and that is the only correct shape for this function: a genuine top-up must
    NOT be idempotent, because two top-ups of the same size are two different events and nothing
    should collapse them.

    SO A CALLER MUST BRING ITS OWN IDEMPOTENCY, AND HERE IS WHERE IT GOES. There is no
    production caller today; a future top-up route inherits a non-idempotent money function, so
    state the obligation rather than leave it to be rediscovered. The guard belongs in the SAME
    `TransactWriteItems` as the balance move, as a second `Update` item on a row keyed by the
    top-up's own event id and conditioned on `attribute_not_exists` - the only shape where a
    replay cannot move money and then fail to record that it did. A pre-read "has this already
    happened" check in the caller is not a substitute: two concurrent replays both pass it.
    """
    digest = _hash_hex(code_hash)
    amount = value_paise(amount_paise)
    now = _now_seconds(clock)
    try:
        updated = table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_CARD + digest},
            UpdateExpression="ADD balancePaise :amount SET updatedAt = :at",
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) "
                                 "AND balancePaise <= :ceiling"),
            ExpressionAttributeValues={":amount": amount, ":at": now,
                                       ":ceiling": MAX_VALUE_PAISE - amount},
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise GiftCardValidationError(
                "BALANCE_CEILING_EXCEEDED",
                f"a balance may not exceed {MAX_VALUE_PAISE} paise") from None
        raise GiftCardStoreUnavailable(
            f"could not credit a gift card: {type(error).__name__}") from error
    return int(updated.get("balancePaise") or 0)


def disable(table: Any, *, code_hash: Any, clock: Clock = _default_clock) -> Dict[str, Any]:
    """`status = DISABLED`. NEVER a delete - a disabled card retains its liability record."""
    digest = _hash_hex(code_hash)
    now = _now_seconds(clock)
    try:
        return table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_CARD + digest},
            UpdateExpression="SET #status = :disabled, updatedAt = :at",
            ConditionExpression=f"attribute_exists({KEY_ATTRIBUTE})",
            ExpressionAttributeNames={"#status": STATUS_ATTRIBUTE},
            ExpressionAttributeValues={":disabled": STATUS_DISABLED, ":at": now},
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise GiftCardNotFound("no such gift card") from None
        raise GiftCardStoreUnavailable(
            f"could not disable a gift card: {type(error).__name__}") from error


def hold(table: Any, *, code_hash: Any, attempt_id: Any, amount_paise: Any,
         ttl_seconds: int = HOLD_TTL_SECONDS, clock: Clock = _default_clock) -> Dict[str, Any]:
    """Reserve balance for one payment attempt. ONE conditional `UpdateItem`, no preceding read.

    DECISION 5's condition, with the balance floor folded into the same expression so a hold can
    never reserve money the card does not have:

        attribute_not_exists(activeHoldAttemptId)   nobody holds it
        OR activeHoldAttemptId = :me                this attempt already holds it, so re-taking
                                                    is idempotent rather than a conflict
        OR activeHoldExpiresAtMs < :now             the previous hold lapsed

    A `GetItem` first would be WORSE than useless: it would be a read-modify-write, and two
    attempts reading "free" in the same moment would both proceed.

    Keyed on `paymentAttemptId` and not `referenceId`, because the hold must precede the gateway
    and on the website path `attempt["referenceId"]` IS the Razorpay order id - which does not
    exist until after. `paymentAttemptId` is minted first on both producers.

    The `GCHOLD#` row written afterwards is an AUDIT record and is never read to make a decision.
    It is written second on purpose: if it fails, the authoritative hold still stands and the only
    loss is a log line.
    """
    digest = _hash_hex(code_hash)
    attempt = _identifier(attempt_id, "INVALID_ATTEMPT_ID")
    amount = value_paise(amount_paise)
    now = _now_seconds(clock)
    if isinstance(ttl_seconds, bool) or type(ttl_seconds) is not int \
            or not 1 <= ttl_seconds <= 86400:
        raise GiftCardValidationError("INVALID_TTL", "a hold TTL must be 1 to 86400 seconds")
    expires_at_ms = (now + ttl_seconds) * 1000
    try:
        updated = table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_CARD + digest},
            UpdateExpression=("SET activeHoldAttemptId = :me, activeHoldPaise = :amount, "
                              "activeHoldExpiresAtMs = :expires, updatedAt = :at"),
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) "
                                 "AND #status = :active "
                                 "AND balancePaise >= :amount "
                                 "AND (" + HOLD_CONDITION + ")"),
            ExpressionAttributeNames={"#status": STATUS_ATTRIBUTE},
            # `:now` is epoch MILLISECONDS because `activeHoldExpiresAtMs` is. Comparing a
            # millisecond field against a second value would treat every live hold as lapsed.
            ExpressionAttributeValues={":me": attempt, ":amount": amount,
                                       ":expires": expires_at_ms, ":now": now * 1000,
                                       ":at": now, ":active": STATUS_ACTIVE},
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            # One refusal covers three causes, and the caller disambiguates with the read it
            # already has rather than this function performing a second one.
            card = get_card(table, code_hash=digest)
            assert_spendable(card, now_ms=now * 1000)
            if int((card or {}).get("balancePaise") or 0) < amount:
                raise InsufficientFunds("this gift card does not hold that much") from None
            raise GiftCardHeldByAnotherPurchase(
                "another purchase holds this gift card") from None
        raise GiftCardStoreUnavailable(
            f"could not hold a gift card: {type(error).__name__}") from error

    _put(table, {KEY_ATTRIBUTE: PREFIX_HOLD + digest + "#" + attempt,
                 "kind": "GIFT_CARD_HOLD", "codeHash": digest, "paymentAttemptId": attempt,
                 "amountPaise": amount, "expiresAtMs": expires_at_ms, "heldAt": now})
    return {"held": True, "paymentAttemptId": attempt, "amountPaise": amount,
            "expiresAtMs": expires_at_ms, "balancePaise": int(updated.get("balancePaise") or 0),
            "codeLast4": str(updated.get("codeLast4") or "")}


def release(table: Any, *, code_hash: Any, attempt_id: Any,
            clock: Clock = _default_clock) -> Dict[str, Any]:
    """Drop this attempt's hold. One conditional `UpdateItem`, then delete the audit row.

    The same condition as `hold`, so an attempt can only clear a hold it owns or one that has
    already lapsed. Releasing another live attempt's hold would hand the balance to whoever asked
    second.
    """
    digest = _hash_hex(code_hash)
    attempt = _identifier(attempt_id, "INVALID_ATTEMPT_ID")
    now = _now_seconds(clock)
    try:
        table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_CARD + digest},
            UpdateExpression=("REMOVE activeHoldAttemptId, activeHoldPaise, "
                              "activeHoldExpiresAtMs SET updatedAt = :at"),
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) "
                                 "AND (" + HOLD_CONDITION + ")"),
            ExpressionAttributeValues={":me": attempt, ":now": now * 1000, ":at": now},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            raise GiftCardHeldByAnotherPurchase(
                "another purchase holds this gift card") from None
        raise GiftCardStoreUnavailable(
            f"could not release a gift card: {type(error).__name__}") from error
    _delete_hold(table, digest, attempt)
    return {"released": True, "paymentAttemptId": attempt}


def _delete_hold(table: Any, digest: str, attempt_id: str) -> None:
    """Delete one `GCHOLD#` audit row. The ONLY delete in this module.

    By explicit delete, never by TTL: a hold ends when the purchase settles or is abandoned, and a
    TTL would make that silent. There is deliberately no function here that can delete a card or
    a pointer row.
    """
    try:
        table.delete_item(Key={KEY_ATTRIBUTE: PREFIX_HOLD + digest + "#" + attempt_id})
    except Exception as error:  # noqa: BLE001
        raise GiftCardStoreUnavailable(
            f"could not delete a gift-card hold: {type(error).__name__}") from error


def redeem(table: Any, *, code_hash: Any, attempt_id: Any, amount_paise: Any,
           clock: Clock = _default_clock) -> Dict[str, Any]:
    """DEBIT the held balance for one settled payment attempt. The money-moving spend primitive.

    The one function in this module that DECREMENTS `balancePaise`. Called only when a payment
    that reserved this card has been VERIFIED captured — the balance leaves the ledger exactly
    once per attempt, which is why every guard below keys on `activeHoldAttemptId = :me`.

    ONE conditional `UpdateItem`, no preceding read (the same discipline as `hold`/`credit`): the
    debit and the hold-clear happen in one expression, conditioned on
        card exists AND status ACTIVE AND this attempt holds it AND balancePaise >= amount
    so a concurrent writer, a replay, or a card that was disabled or drained between hold and
    settle cannot double-debit or go negative. On success the three `activeHold*` attributes are
    REMOVEd — the reservation becomes a receipt, atomically with the money leaving.

    IDEMPOTENCY. A redelivered capture re-calls this; the second call fails the
    `activeHoldAttemptId = :me` condition (the hold is already gone) and is reported as an
    idempotent no-op (`{"redeemed": False, "alreadyRedeemed": True, ...}`) rather than raising, so
    a webhook retry does not debit twice and does not alarm. A genuinely insufficient balance or a
    disabled card — distinguishable only by a follow-up read — raises `InsufficientFunds` /
    `GiftCardDisabled` so the caller can reconcile. The `GCHOLD#` audit row is deleted last; its
    loss costs only a log line because the authoritative debit already committed.
    """
    digest = _hash_hex(code_hash)
    attempt = _identifier(attempt_id, "INVALID_ATTEMPT_ID")
    amount = value_paise(amount_paise)
    now = _now_seconds(clock)
    try:
        updated = table.update_item(
            Key={KEY_ATTRIBUTE: PREFIX_CARD + digest},
            UpdateExpression=("SET updatedAt = :at REMOVE activeHoldAttemptId, "
                              "activeHoldPaise, activeHoldExpiresAtMs "
                              "ADD balancePaise :debit"),
            ConditionExpression=(f"attribute_exists({KEY_ATTRIBUTE}) "
                                 "AND #status = :active "
                                 "AND activeHoldAttemptId = :me "
                                 "AND balancePaise >= :amount"),
            ExpressionAttributeNames={"#status": STATUS_ATTRIBUTE},
            # ADD a NEGATIVE amount to debit: DynamoDB has no SET-minus for an atomic read-free
            # decrement, and a negative ADD under the `balancePaise >= :amount` floor can never
            # take the balance below zero.
            ExpressionAttributeValues={":debit": -amount, ":amount": amount, ":me": attempt,
                                       ":active": STATUS_ACTIVE, ":at": now},
            ReturnValues="ALL_NEW",
        ).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            # The condition covers four causes; one read disambiguates the two that are faults
            # from the two that are idempotent no-ops.
            card = get_card(table, code_hash=digest)
            if not card:
                raise GiftCardNotFound("no such gift card") from None
            if card.get(STATUS_ATTRIBUTE) != STATUS_ACTIVE:
                raise GiftCardDisabled("this gift card is disabled") from None
            if card.get(HOLD_ATTEMPT_ATTRIBUTE) != attempt:
                # No live hold for THIS attempt. Either the hold lapsed/was released (nothing to
                # redeem — a fault to surface) or we already redeemed it (an idempotent replay).
                # They are indistinguishable from the card row alone; the caller's own
                # redemption-commit ledger (`redemption.commit_redemption`) is the exactly-once
                # authority, so this reports a no-op and lets that ledger decide.
                return {"redeemed": False, "alreadyRedeemed": True, "paymentAttemptId": attempt,
                        "amountPaise": amount,
                        "balancePaise": int((card or {}).get("balancePaise") or 0)}
            if int(card.get("balancePaise") or 0) < amount:
                raise InsufficientFunds(
                    "this gift card no longer holds that much") from None
            # The guard failed for a reason the follow-up read cannot see (a race that resolved
            # between the write and the read). Treated as retryable rather than a silent success.
            raise GiftCardStoreUnavailable("could not redeem a gift card: state changed") from None
        raise GiftCardStoreUnavailable(
            f"could not redeem a gift card: {type(error).__name__}") from error
    _delete_hold(table, digest, attempt)
    return {"redeemed": True, "paymentAttemptId": attempt, "amountPaise": amount,
            "balancePaise": int(updated.get("balancePaise") or 0),
            "codeLast4": str(updated.get("codeLast4") or "")}


__all__ = [
    "CARD_ATTRIBUTES", "CODE_ALPHABET", "CODE_LENGTH", "CODE_PATTERN", "CURRENCY",
    "CurrencyNotSupported", "DEFAULT_TABLE_NAME", "GiftCardDisabled", "GiftCardError",
    "GiftCardExpired", "GiftCardHeldByAnotherPurchase", "GiftCardNotFound",
    "GiftCardStoreUnavailable", "GiftCardValidationError", "HOLD_ATTEMPT_ATTRIBUTE",
    "HOLD_CONDITION", "HOLD_EXPIRY_ATTRIBUTE", "HOLD_PAISE_ATTRIBUTE", "HOLD_TTL_SECONDS",
    "InsufficientFunds", "KEY_ATTRIBUTE", "MAX_CODE_LENGTH", "MAX_PIN_LENGTH",
    "MAX_VALUE_PAISE", "MIN_CODE_LENGTH", "MissingCurrency", "MONEY_CEILING_PAISE",
    "PEPPER_FIELD", "PEPPER_SECRET_ENV_KEY", "resolve_pepper_secret_id",
    "POLICY_VERSION", "PREFIX_CARD", "PREFIX_CARD_ID", "PREFIX_HOLD",
    "RAZORPAY_MIN_LEG_PAISE", "SECRET_ID", "STATUSES", "STATUS_ACTIVE", "STATUS_ATTRIBUTE",
    "STATUS_DISABLED", "STATUS_INDEX", "TABLE_ENV_KEY",
    "assert_currency", "assert_spendable", "card_id_key",
    "card_key", "card_key_from_hash", "code_hash", "code_last4", "credit",
    "disable", "generate_code", "get_card", "get_card_by_id",
    "hold", "hold_key", "issue", "list_by_status", "masked",
    "normalise_code", "pin_hash", "read_pepper",
    "redeem", "release", "value_paise", "verify_pin",
]
