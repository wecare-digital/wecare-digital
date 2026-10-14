"""The gift-card liability ledger. A balance we OWE, keyed on an HMAC of bearer value.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md`
sections 3.4 (idempotency), 4.1 (the split and the cap), 6 (data model), 7.4 (error handling) and
7.5 (validation).

The code is BEARER VALUE, so it is never the key
------------------------------------------------
    giftCardKey = "GIFTCARD#" + HMAC-SHA256(pepper, NFKC(code).upper()).hexdigest()

An HMAC with a pepper, not a bare SHA-256, and the reason is the measured contract: the SPI bounds
a code at `minLength 8, maxLength 20`. An 8-character code over a small alphabet is inside
brute-force range for a plain hash, so a leaked table would expose live balances. The pepper lives
in Secrets Manager (`wecare/wix/giftcard-spi` -> `code_pepper`), is referenced by secret id, and is
read LAZILY at request time through an INJECTED reader - never at module scope, because a
module-scope read is cached for the life of the execution environment and a rotation would not take
effect until every warm sandbox recycled.

This is the deliberate OPPOSITE of `coupon_store`, where the code *is* the partition key because a
coupon code is broadcast marketing material. `tests/test_gift_card_store.py` and
`tests/test_coupon_logging_and_vocabulary.py` pin the asymmetry from both sides so neither gets
"harmonised" into the other.

Logs carry `codeLast4` only, rendered `****1234` by `masked()`. The code never appears in full - not
in a log, not in an exception message, not in a URL. Correlation uses `giftCardId` (ours, a UUIDv7),
`paymentAttemptId` (ours, a UUIDv7) and the SPI's `metadata.requestId`, all of which are loggable.

Every balance move is a CONDITIONAL WRITE
-----------------------------------------
    ADD balancePaise :neg      under      ConditionExpression balancePaise >= :amount

A read-then-write would let two concurrent redemptions both pass a `balance >= amount` check and
overdraw the card. The `GCORDER#<codeHash>#<paymentAttemptId>` claim is a conditional put written
BEFORE the decrement, so a replay loses the put, reads the winning row and returns that same
`transactionId` with the balance untouched.

The claim row carries `settled`. It is written unsettled, then marked settled by the decrement, and
that ordering is what makes an insufficient-balance failure RECOVERABLE: a retry finds an unsettled
claim and re-attempts the decrement rather than reporting a redemption that never moved money.
Nothing here deletes a claim, a transaction, a card or a pointer row - only a `GCHOLD#` audit row.

The void path carries the SAME device under a different name, deliberately rather than a second
mechanism: the `voidedBy` latch is written `credited: False` and only the credit sets it true, so a
throttled credit leaves a void a retry can COMPLETE instead of a customer's balance stranded behind
a permanent `AlreadyVoided` with no operator path back. Both strands of the ledger therefore fail
and recover identically, which is the same reason payment status lives behind one module rather
than being compared string by string in each handler.

A recoverable move must also be a move that cannot happen twice, and a flag on a SECOND item
cannot supply that on its own. `settled` is on the claim row and `credited` is on the transaction
row, so both used to be written after the money had already moved. Failing just that second write
left a state - unsettled claim, or `credited: False` - that a retry could not distinguish from
"the move never ran", and re-driving on the strength of that read debited or credited the card a
second time.

So each money move and the flag that records it are **one `TransactWriteItems` with two `Update`
items**:

    redeem   card:  ADD balancePaise :neg   under  balancePaise >= :amount AND #status = :active
             claim: SET settled = :true     under  settled = :false

    void     card:  ADD balancePaise :amount  under  balancePaise <= :ceiling
             txn:   SET credited = :true      under  attribute_exists(credited) AND credited = :false

One commit, so the balance and the record of having moved it cannot diverge no matter where a
process dies, and no interleaving exists in which the money has moved and the flag has not. The
flags remain what make the recovery REACHABLE; the transaction is what makes it SAFE. There are
no applied-move markers any more and nothing to clean up, so a card row's size is bounded by
construction rather than by a best-effort delete.

Every access is an exact-key operation
--------------------------------------
`get_item` / `put_item` / `update_item` on a fully specified partition key, plus the staff
`status-index` `Query`. No `scan`, no prefix query, no second index. DECISION 5 is what makes that
possible: the existence of a hold or a claim is an ATTRIBUTE of the card row
(`activeHoldAttemptId` / `activeClaimAttemptId`), so the `/v1/redeem` refusal is one `GetItem`
rather than a search. A decision that gates money cannot be made from a scan, and it cannot be made
from a GSI either - a GSI is eventually consistent.

No float, and the ceiling is the SPI's
--------------------------------------
Money is integer paise. The value ceiling is `99_999_999_999` paise (== `999999999.99`, the SPI's
documented `maximum`), asserted on issuance AND on every credit - a balance we cannot report to Wix
is a balance we cannot honour. `money.py`'s `9007199254740991` remains the outer type bound;
the binding constraint is the SPI's.

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

#: Secret NAME, never a value. Carries `public_key`, `app_id`, `instance_id` and `code_pepper`.
SECRET_ID = "wecare/wix/giftcard-spi"
SECRET_ENV_KEY = "WIX_GIFTCARD_SPI_SECRET"
PEPPER_FIELD = "code_pepper"

#: THE PEPPER IS NOT A WIX CREDENTIAL — it is the HMAC key for EVERY gift-card row
#: lookup, and it must OUTLIVE the Wix integration. During the Wix exit the pepper
#: VALUE is copied verbatim into a non-Wix secret (`wecare/prod/security/giftcard-pepper`)
#: and the handlers' secret-id resolution (where env reads legitimately live) is
#: pointed at it via PEPPER_SECRET_ENV_KEY. Because the value is identical, every
#: existing card key still recomputes — nothing is re-keyed. Only AFTER that flip is
#: the Wix SPI secret safe to retire.
#:
#: This name is DEFINED here (one place) but READ by the handlers, never by this
#: module: `test_gift_card_store.py` forbids an `os` import here, because an env read
#: in the store would be ambient configuration. The store takes the resolved secret
#: id by injection (`read_pepper(..., secret_id=...)`); the handlers resolve it.
PEPPER_SECRET_ENV_KEY = "GIFTCARD_PEPPER_SECRET"


def resolve_pepper_secret_id(env: Mapping[str, str]) -> str:
    """Resolve the pepper's secret id from an INJECTED env mapping (never os.environ
    here — the store holds no ambient config). Preference order, so the migration is
    a config flip with no code change and no re-keying:
      1. `GIFTCARD_PEPPER_SECRET` — the non-Wix home the pepper moves to.
      2. `WIX_GIFTCARD_SPI_SECRET` — an explicit override of the Wix secret.
      3. `SECRET_ID` — the original Wix SPI secret (current default).
    The pepper VALUE under (1) must be byte-identical to (3) or existing cards stop
    resolving — that identity is the whole point of copying rather than regenerating.
    """
    return (env.get(PEPPER_SECRET_ENV_KEY)
            or env.get(SECRET_ENV_KEY)
            or SECRET_ID)

KEY_ATTRIBUTE = "giftCardKey"
STATUS_ATTRIBUTE = "status"
STATUS_INDEX = "status-index"

PREFIX_CARD = "GIFTCARD#"
PREFIX_CLAIM = "GCORDER#"
PREFIX_WIX_ORDER = "GCWIXORDER#"
PREFIX_TRANSACTION = "GCTXN#"
PREFIX_TRANSACTION_ID = "GCTXNID#"
PREFIX_HOLD = "GCHOLD#"
#: Not in the design's section 6.3 row list, and added deliberately: `GET /gift-cards/{giftCardId}`
#: (section 7.2) has to resolve a card by OUR id, and the only alternatives are a `Scan` or a
#: second GSI. A pointer row is the same device `GCTXNID#` already is, and it keeps every access an
#: exact-key operation.
PREFIX_CARD_ID = "GCID#"

CURRENCY = "INR"
POLICY_VERSION = "giftcard-policy-2026-10-01"

STATUS_ACTIVE = "ACTIVE"
STATUS_DISABLED = "DISABLED"
STATUSES = (STATUS_ACTIVE, STATUS_DISABLED)

KIND_REDEEM = "REDEEM"
KIND_VOID = "VOID"
TRANSACTION_KINDS = (KIND_REDEEM, KIND_VOID)

SOURCE_OURS = "OURS"
SOURCE_WIX_SPI = "WIX_SPI"
SOURCES = (SOURCE_OURS, SOURCE_WIX_SPI)

#: `GetBalanceResponse.balance` and `RedeemResponse.remainingBalance` are both documented
#: `maximum: 999999999.99`, so a card issued above this could not be REPORTED to Wix at all
#: without violating the schema the plugin must match exactly.
MAX_VALUE_PAISE = 99_999_999_999

#: `money.py`'s outer type bound, restated only so the relationship is explicit: nothing may
#: exceed it, but the SPI maximum above is the constraint that actually binds.
MONEY_CEILING_PAISE = 9007199254740991

#: Razorpay's documented minimum order amount. Orders Create answers
#: `BAD_REQUEST_ERROR` / "The amount must be at least INR 1.00" below it, at
#: `step: payment_initiation` - i.e. AFTER a hold would have been taken and the quote frozen,
#: which is the worst possible place for it. https://razorpay.com/docs/api/orders/create/
RAZORPAY_MIN_LEG_PAISE = 100

#: Crockford base32: no I, L, O or U, so a handwritten code cannot be transcribed into a
#: different one. 16 characters, inside the SPI's 8-20 bound.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 16
MIN_CODE_LENGTH = 8
MAX_CODE_LENGTH = 20
#: The SPI's own charset for `code`.
CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")

MAX_PIN_LENGTH = 50
#: `transactionId` is `minLength 1, maxLength 100` per the schema. 26 Crockford symbols.
TRANSACTION_ID_SYMBOLS = 26

#: DECISION 5. The existence of a hold or a claim lives on the row whose key is already known, so
#: the `/v1/redeem` refusal is ONE `GetItem` on `GIFTCARD#<codeHash>` rather than a prefix scan.
HOLD_ATTEMPT_ATTRIBUTE = "activeHoldAttemptId"
HOLD_PAISE_ATTRIBUTE = "activeHoldPaise"
HOLD_EXPIRY_ATTRIBUTE = "activeHoldExpiresAtMs"
#: A claim never lapses, which is why it is a separate attribute from the hold rather than a hold
#: with a far expiry: an expiry that must never be reached is an expiry somebody will shorten.
CLAIM_ATTEMPT_ATTRIBUTE = "activeClaimAttemptId"

HOLD_CONDITION = ("attribute_not_exists(activeHoldAttemptId) "
                  "OR activeHoldAttemptId = :me "
                  "OR activeHoldExpiresAtMs < :now")

#: A hold is advisory and short-lived: it stops the ordinary double-spend race while a customer
#: finishes paying. The authoritative single-redemption guarantee is the conditional claim put.
HOLD_TTL_SECONDS = 900

#: Bounded retry for a transaction the database cancelled for CONTENTION rather than for a
#: condition. Two retries, three attempts, worst case roughly 200 ms added - well inside any
#: Lambda timeout on this path.
TRANSACTION_ATTEMPTS = 3

#: Cancellation reason codes that mean *try again*, as opposed to *the condition decided*.
RETRYABLE_CANCELLATION_REASONS = frozenset(
    {"TransactionConflict", "ThrottlingError", "ProvisionedThroughputExceeded"})

#: Every attribute a card row may carry, per section 6.4 plus DECISION 5's three. Enumerated so a
#: test can assert the code itself is not among them. There are no applied-move markers any more:
#: the balance move and the flag that records it commit in ONE `TransactWriteItems`, so a marker
#: whose whole job was to make the money its own idempotency record on one item has nothing left
#: to do. That also bounds a card row's size by construction rather than by a cleanup step.
CARD_ATTRIBUTES = (
    KEY_ATTRIBUTE, "giftCardId", "codeLast4", "pinHash", "initialValuePaise", "balancePaise",
    "currency", STATUS_ATTRIBUTE, "issuedAtMs", "expiresAtMs", "issuedToContactId",
    "sourceOrderId", "policyVersion", "createdAt", "updatedAt", "createdBy",
    HOLD_ATTEMPT_ATTRIBUTE, HOLD_PAISE_ATTRIBUTE, HOLD_EXPIRY_ATTRIBUTE,
    CLAIM_ATTEMPT_ATTRIBUTE,
)

#: The nine documented SPI errors, read from each method's own `errors[]` array:
#: name -> (applicationCode, httpCode). `AlreadyVoided`'s application code is `ALREADY_VOIDED`,
#: transcribed from the Void page. Note the OUTER Wix error class is `AlreadyVoidedWixError` and
#: `spiErrorData.name` is `AlreadyVoided` - we return the latter, and confusing them puts the
#: wrong string in the right place.
SPI_ERRORS: Dict[str, tuple] = {
    "GiftCardNotFound": ("GIFT_CARD_NOT_FOUND", 404),
    "GiftCardDisabled": ("GIFT_CARD_DISABLED", 428),
    "GiftCardExpired": ("GIFT_CARD_EXPIRED", 428),
    "MissingCurrency": ("MISSING_CURRENCY", 428),
    "InsufficientFunds": ("INSUFFICIENT_FUNDS", 428),
    "AlreadyRedeemed": ("ALREADY_REDEEMED", 409),
    "CurrencyNotSupported": ("CURRENCY_NOT_SUPPORTED", 400),
    "TransactionNotFound": ("TRANSACTION_NOT_FOUND", 404),
    "AlreadyVoided": ("ALREADY_VOIDED", 409),
}


# ── errors ────────────────────────────────────────────────────────────────────

class GiftCardError(ValueError):
    """Base. Carries a machine-readable `code` so a handler never parses a message.

    `spi_name` is the `spiErrorData.name` the SPI answers with, or `""` for a refusal that has no
    documented SPI counterpart (our own routes and the pre-hold validation table).
    """

    status = 400
    spi_name = ""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code

    @property
    def application_code(self) -> str:
        return SPI_ERRORS.get(self.spi_name, (self.code, self.status))[0]


class GiftCardValidationError(GiftCardError):
    """An external input was refused. Nothing was written and no balance moved."""


class GiftCardNotFound(GiftCardError):
    """Unknown code, malformed code, or a wrong PIN.

    One answer for all three, deliberately: three distinct answers would turn the endpoint into a
    code-validity oracle, and a gift-card code is bearer value.
    """

    status = 404
    spi_name = "GiftCardNotFound"

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_NOT_FOUND", message)


class GiftCardDisabled(GiftCardError):
    status = 428
    spi_name = "GiftCardDisabled"

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_DISABLED", message)


class GiftCardExpired(GiftCardError):
    status = 428
    spi_name = "GiftCardExpired"

    def __init__(self, message: str = ""):
        super().__init__("GIFT_CARD_EXPIRED", message)


class MissingCurrency(GiftCardError):
    status = 428
    spi_name = "MissingCurrency"

    def __init__(self, message: str = ""):
        super().__init__("MISSING_CURRENCY", message)


class CurrencyNotSupported(GiftCardError):
    status = 400
    spi_name = "CurrencyNotSupported"

    def __init__(self, message: str = ""):
        super().__init__("CURRENCY_NOT_SUPPORTED", message)


class InsufficientFunds(GiftCardError):
    status = 428
    spi_name = "InsufficientFunds"

    def __init__(self, message: str = ""):
        super().__init__("INSUFFICIENT_FUNDS", message)


class AlreadyRedeemed(GiftCardError):
    """A Wix `/v1/redeem` arrived for a card that already holds a hold or a claim.

    Stricter than idempotency and deliberately so: our `orderId` namespace and
    `RedeemRequest.orderId`'s are different, so a shared claim key cannot be the guard under any
    naming. The guard has to be the existence check, keyed on the CARD - the one thing both sides
    agree on. Section 1.3 predicts Wix never calls this endpoint, so refusing costs nothing real
    and removes the two-namespace double-spend entirely.
    """

    status = 409
    spi_name = "AlreadyRedeemed"

    def __init__(self, message: str = ""):
        super().__init__("ALREADY_REDEEMED", message)


class TransactionNotFound(GiftCardError):
    status = 404
    spi_name = "TransactionNotFound"

    def __init__(self, message: str = ""):
        super().__init__("TRANSACTION_NOT_FOUND", message)


class AlreadyVoided(GiftCardError):
    status = 409
    spi_name = "AlreadyVoided"

    def __init__(self, message: str = ""):
        super().__init__("ALREADY_VOIDED", message)


class GiftCardHeldByAnotherPurchase(GiftCardError):
    status = 409

    def __init__(self, message: str = ""):
        super().__init__("HELD_BY_ANOTHER_PURCHASE", message)


class GiftCardStoreUnavailable(RuntimeError):
    """Storage failed for a reason that is not a lost race.

    Its own type so a throttle or an outage can never be mistaken for "no such card" or "already
    claimed". A read failure reported as absence would refuse a live card; worse, on the redeem
    path it would look like an unclaimed one.
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

    Left EXACTLY as it was by the transaction change. It is consulted by `_put`, `hold`,
    `credit`, `disable`, `release` and `_delete_hold`, none of which opens a transaction, so
    broadening it to also recognise a cancellation would only ever be correct there by accident.
    `_is_transaction_cancellation` answers that question instead.
    """
    if type(error).__name__ == "ConditionalCheckFailedException":
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    return False


def _is_transaction_cancellation(error: BaseException) -> bool:
    """True only for a `TransactWriteItems` cancellation, however the client spells it."""
    if type(error).__name__ == "TransactionCanceledException":
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "TransactionCanceledException"
    return False


def _cancellation_reason_codes(error: BaseException) -> list:
    """The documented `CancellationReasons[].Code` list, or `[]` if the shape is absent.

    botocore puts this list at the TOP LEVEL of the response, a sibling of `"Error"` - NOT
    inside it. Reading it from `response["Error"]` yields `[]` on every real cancellation and
    converts the main path of the transaction fix into a 5xx.

    Reading a structured response field is not the banned pattern. The ban is on parsing an
    exception's MESSAGE; `CancellationReasons[].Code` is in the same class as
    `response["Error"]["Code"]`, which `_is_conditional_failure` already reads.
    """
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return []
    return [str((reason or {}).get("Code") or "")
            for reason in (response.get("CancellationReasons") or [])]


def _marshal(value: Any) -> Dict[str, Any]:
    """The AttributeValue form of the three types this module's transactions carry.

    Hand-written because `boto3.dynamodb.types` may not be imported here - see
    `test_the_store_holds_no_boto3_client_and_reads_no_secret_itself`, which walks every
    `ast.Import`/`ast.ImportFrom` in this module, so moving the import inside a function body
    would not help either. That gate is the structural form of this module's central claim, and
    weakening a gate to land a change is not available. Pinned byte-for-byte against
    `TypeSerializer` by a test in `tests/`, where botocore is already a dependency.

    The float refusal is the point rather than a side effect: `TypeSerializer` refuses a float
    with `TypeError`, and `type(value) is int` additionally refuses a `Decimal` and a
    `bool`-as-amount, which `TypeSerializer` would accept and quietly convert.
    """
    if isinstance(value, bool):          # BEFORE int: bool IS an int in Python
        return {"BOOL": value}
    if type(value) is int:               # exact type, so Decimal/float cannot slip through
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    # `GiftCardValidationError`, NOT `GiftCardStoreUnavailable`: an unmarshalable value is a
    # programming error that recurs identically on every retry, so labelling it retriable turns
    # one defect into a retry storm against a money path. A constant code plus prose, because
    # `.code` is the field handlers branch on and the SPI maps through `SPI_ERRORS` - an
    # interpolated code is unbranchable.
    raise GiftCardValidationError(
        "UNMARSHALABLE_VALUE", f"cannot marshal {type(value).__name__}")


#: Module-level alias so the transaction item expressions stay readable.
_ser = _marshal


def _transact_with_retry(table: Any, items: list, *,
                         sleep: Callable[[float], None] = time.sleep) -> None:
    """The ONLY call site of `transact_write_items` in this module.

    Both committers route through here, so the bounded retry, the jitter and the injected
    sleeper exist once. A cancellation that is not a retryable conflict is re-raised UNCHANGED,
    so the caller's decide-from-data branch is unaffected by this wrapper.

    `secrets` rather than `random` for the jitter, because `random`'s PRNG state is a documented
    SnapStart hazard in this fleet - a snapshot freezes it and every restored environment
    produces the same sequence. The sleeper is injected so the covering test runs at full speed.
    """
    for attempt in range(TRANSACTION_ATTEMPTS):
        try:
            table.meta.client.transact_write_items(TransactItems=items)
            return
        except Exception as error:  # noqa: BLE001
            if not _is_transaction_cancellation(error):
                raise
            reasons = set(_cancellation_reason_codes(error))
            if not reasons & RETRYABLE_CANCELLATION_REASONS:
                # Either a condition decided it, or the reason set is empty/unrecognised. A
                # cancellation is by definition a condition outcome unless a reason says
                # otherwise, so it goes back to the caller's decide-from-data branch - never
                # reported as an outage.
                raise
            if attempt == TRANSACTION_ATTEMPTS - 1:
                raise GiftCardStoreUnavailable(
                    f"a gift-card transaction kept losing to contention after "
                    f"{TRANSACTION_ATTEMPTS} attempts: {type(error).__name__}") from error
            sleep(0.05 * 2 ** attempt + _secrets.randbelow(25) / 1000)


# ── the pepper, read by reference and lazily ───────────────────────────────────

def read_pepper(reader: SecretReader, *, secret_id: str = SECRET_ID) -> str:
    """The HMAC pepper, through an INJECTED reader, at the moment it is needed.

    `reader` is a callable taking a secret ID and returning the parsed secret mapping. This module
    holds no boto3 client, so it cannot read a secret at import even by accident - which is the
    structural version of the lazy-read rule rather than a promise to remember it.

    `secret_id` is resolved by the CALLER (via `resolve_pepper_secret_id(os.environ)`),
    which is where env reads legitimately live; this module takes it by injection so
    the pepper can migrate out of the Wix SPI secret by configuration alone.

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

    Refuses by raising `GiftCardNotFound`, not a validation error: section 7.5 requires a
    malformed code to answer exactly as an unknown one does, so the endpoint cannot be ground into
    a validity oracle.
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


def claim_key(hash_hex: Any, attempt_id: Any) -> str:
    return PREFIX_CLAIM + _hash_hex(hash_hex) + "#" + _identifier(attempt_id, "INVALID_ATTEMPT_ID")


def hold_key(hash_hex: Any, attempt_id: Any) -> str:
    return PREFIX_HOLD + _hash_hex(hash_hex) + "#" + _identifier(attempt_id, "INVALID_ATTEMPT_ID")


def transaction_key(hash_hex: Any, transaction_id: Any) -> str:
    return (PREFIX_TRANSACTION + _hash_hex(hash_hex) + "#"
            + _transaction_id(transaction_id))


def transaction_pointer_key(transaction_id: Any) -> str:
    return PREFIX_TRANSACTION_ID + _transaction_id(transaction_id)


def wix_order_key(wix_order_id: Any) -> str:
    return PREFIX_WIX_ORDER + _identifier(wix_order_id, "INVALID_WIX_ORDER_ID")


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


def _transaction_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise GiftCardValidationError("INVALID_TRANSACTION_ID", "a transaction id is required")
    text = value.strip()
    if not 1 <= len(text) <= 100 or "#" in text:
        raise GiftCardValidationError("INVALID_TRANSACTION_ID",
                                      "a transaction id must be 1 to 100 characters")
    return text


def new_transaction_id() -> str:
    """Ours, generated with `secrets` through `identifiers.new_ulid`, 1-100 chars per the schema."""
    return identifiers.new_ulid()


def value_paise(value: Any, *, field: str = "INVALID_AMOUNT") -> int:
    """Positive integer paise within the SPI's ceiling. Floats and bools refused BY TYPE.

    The ceiling is asserted here rather than only at issuance, so every credit goes through it -
    a balance above `999999999.99` could not be reported to Wix at all, and a balance we cannot
    report is a balance we cannot honour.
    """
    try:
        paise = money.positive_paise(value)
    except ValueError as error:
        raise GiftCardValidationError(field, "amount must be positive integer paise") from error
    if paise > MAX_VALUE_PAISE:
        raise GiftCardValidationError(
            field, f"amount must not exceed {MAX_VALUE_PAISE} paise, the SPI maximum")
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


# ── the cap, defined exactly ONCE (DECISION 10 / HIGH-4) ───────────────────────

def redeem_cap(*, balance_paise: int, wix_collection_paise: int) -> int:
    """The most a gift card may fund on one purchase.

    DEFINED ONCE. Both the section 7.5 validation table (`validate_redeem_request`) and the
    section 4.1 split (`split_payment`) call THIS function, which is the whole of HIGH-4's
    resolution: revision 2 had the cap written twice against two different totals, and the second
    copy admitted a request the reconciliation identity then refused.

    The cap is against the WIX COLLECTION total, not our payable, because Wix is the only thing
    that can apply the card and the convenience fee does not exist on the Wix cart - it reaches
    Wix only at `Create Order`, as `additionalFees[]`. So the gift card funds the SUPPLY only; the
    convenience fee and its GST are always on the Razorpay leg. That is what makes
    `redeemAmount == giftCardRedeemPaise` an exact equality worth failing closed on rather than a
    `min(...)` whose two sides are allowed to differ.

    `- RAZORPAY_MIN_LEG_PAISE` keeps the remaining Razorpay leg chargeable. Without it a card
    could leave a 1-paise leg the gateway rejects at `payment_initiation`, AFTER the hold was
    taken and the quote frozen.

    May return zero or negative for a cart smaller than the floor; callers compare against it
    rather than clamping to it, because a cap that clamps silently changes what the customer
    agreed to.
    """
    balance = value_paise(balance_paise, field="INVALID_BALANCE")
    collection = value_paise(wix_collection_paise, field="INVALID_WIX_COLLECTION")
    return min(balance, collection - RAZORPAY_MIN_LEG_PAISE)


def validate_redeem_request(*, requested_paise: Any, balance_paise: int,
                            wix_collection_paise: int, total_payable_paise: int) -> int:
    """The section 7.5 validation table for a customer's requested redemption. Returns paise.

    Refuses, never clamps. Silently clamping means the figure the customer agreed to is not the
    figure applied.
    """
    requested = value_paise(requested_paise, field="GIFT_CARD_REDEEM_INVALID")
    payable = value_paise(total_payable_paise, field="INVALID_TOTAL_PAYABLE")
    cap = redeem_cap(balance_paise=balance_paise,
                     wix_collection_paise=wix_collection_paise)
    if requested >= payable:
        # Refused BEFORE the cap check so the reason a customer sees names the real objection.
        # There is no Razorpay capture at all here, and the entire authoritative verification
        # path this system has is Razorpay's: an order settled wholly on our own ledger, verified
        # only by our own write, is a different trust model and is out of scope (section 4.4).
        raise GiftCardValidationError(
            "GIFT_CARD_COVERS_FULL_TOTAL",
            "a gift card may not cover the whole payable total in this release")
    if requested > cap:
        raise GiftCardValidationError(
            "GIFT_CARD_REDEEM_ABOVE_CAP",
            "the requested redemption exceeds what this card may fund")
    remainder = payable - requested
    if 0 < remainder < RAZORPAY_MIN_LEG_PAISE:
        raise GiftCardValidationError(
            "GIFT_CARD_LEAVES_UNCHARGEABLE_REMAINDER",
            f"the remaining Razorpay leg must be at least {RAZORPAY_MIN_LEG_PAISE} paise")
    return requested


def split_payment(*, balance_paise: int, wix_collection_paise: int, total_payable_paise: int,
                  requested_paise: Any = None) -> Dict[str, int]:
    """The section 4.1 split: how much the card funds and how much Razorpay collects.

    Calls `redeem_cap` and `validate_redeem_request` rather than re-deriving either, so the cap
    that admits a request is the same expression as the cap that refuses one.

    The returned identity holds exactly:
        payNowPaise + giftCardRedeemPaise == total_payable_paise
    """
    cap = redeem_cap(balance_paise=balance_paise,
                     wix_collection_paise=wix_collection_paise)
    if requested_paise is None:
        if cap <= 0:
            raise GiftCardValidationError(
                "GIFT_CARD_LEAVES_UNCHARGEABLE_REMAINDER",
                "this cart is too small for a gift card to fund any of it")
        requested_paise = cap
    redeem = validate_redeem_request(requested_paise=requested_paise,
                                     balance_paise=balance_paise,
                                     wix_collection_paise=wix_collection_paise,
                                     total_payable_paise=total_payable_paise)
    pay_now = int(total_payable_paise) - redeem
    return {"giftCardRedeemPaise": redeem, "payNowPaise": pay_now,
            "redeemCapPaise": cap, "wixCollectionPaise": int(wix_collection_paise)}


def reconcile_with_wix(cart_summary: Mapping[str, Any], *, gift_card_redeem_paise: int,
                       pay_now_paise: int, quote) -> Dict[str, int]:
    """The six section 4.2 identities, in integer paise, through `Money.from_wix` on every Wix term.

    Every Wix amount is a decimal STRING (`format: DECIMAL_VALUE`), so applying the converter is
    also what proves the field was a string rather than a number somebody compared against an int.
    Revision 2 compared a `ConvertedMoney` object against an `int` twice - always-false, so it
    would have failed ALWAYS rather than failing closed.

    A disagreement on any identity FAILS CLOSED, per R6.2: a one-paise mismatch against the
    authoritative total must refuse the order rather than charge an amount nobody computed.
    """
    payment = (cart_summary or {}).get("paymentSummary") or {}
    prices = (cart_summary or {}).get("priceSummary") or {}

    collection = money.Money.from_wix((prices.get("total") or {}).get("amount")).paise
    cards = payment.get("giftCards") or []
    if len(cards) != 1:
        # Wix: "Carts currently support a single coupon and a single gift card at a time."
        # Enforced by us rather than discovered at runtime.
        raise GiftCardValidationError("GIFT_CARD_COUNT_UNSUPPORTED",
                                      "exactly one gift card is supported")
    applied = money.Money.from_wix(
        ((cards[0] or {}).get("redeemAmount") or {}).get("amount")).paise
    wix_pay_now = money.Money.from_wix((payment.get("payNow") or {}).get("amount")).paise

    # 3. Absence is treated as False and therefore REFUSES. A cart summary that does not carry
    #    the field has not told us there is a Razorpay leg, and inferring one from `payNow` alone
    #    would be exactly the guess R6.2 forbids.
    if payment.get("requiresPaymentAfterGiftCard") is not True:
        raise GiftCardValidationError(
            "GIFT_CARD_COVERS_FULL_TOTAL",
            "Wix does not report that a further payment is required")

    identities = (
        ("WIX_APPLIED_MISMATCH", applied == gift_card_redeem_paise),
        ("WIX_TOTAL_MISMATCH", wix_pay_now + gift_card_redeem_paise == collection),
        ("WIX_PAY_NOW_MISMATCH", wix_pay_now == collection - gift_card_redeem_paise),
        ("PAYABLE_MISMATCH", pay_now_paise + gift_card_redeem_paise
         == quote.total_payable_paise),
        ("RAZORPAY_LEG_UNCHARGEABLE", pay_now_paise >= RAZORPAY_MIN_LEG_PAISE),
        ("FEE_NOT_ON_RAZORPAY_LEG", pay_now_paise - wix_pay_now
         == quote.convenience_fee_paise + quote.convenience_gst_paise),
    )
    for code, holds in identities:
        if not holds:
            raise GiftCardValidationError(code, "the gift-card split does not reconcile")
    return {"wixCollectionPaise": collection, "wixAppliedPaise": applied,
            "wixPayNowPaise": wix_pay_now, "payNowPaise": pay_now_paise,
            "giftCardRedeemPaise": gift_card_redeem_paise}


# ── reads ─────────────────────────────────────────────────────────────────────

def _get(table: Any, key: str) -> Optional[Dict[str, Any]]:
    """One exact-key, strongly consistent read. A storage failure RAISES, never answers absent.

    Absence is a decision input here, so a throttle allowed to look like absence would report an
    unclaimed card and admit a second deduction.
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


def get_claim(table: Any, *, code_hash: Any, attempt_id: Any) -> Optional[Dict[str, Any]]:
    return _get(table, claim_key(code_hash, attempt_id))


def get_transaction(table: Any, *, code_hash: Any, transaction_id: Any) \
        -> Optional[Dict[str, Any]]:
    return _get(table, transaction_key(code_hash, transaction_id))


def resolve_transaction(table: Any, *, transaction_id: Any) -> Dict[str, str]:
    """`GCTXNID#<transactionId>` -> `{codeHash, paymentAttemptId}`.

    This row exists because `VoidRequest` carries NO code: without it a documented request would
    be unanswerable. DECISION 9 adds `paymentAttemptId` to it, which is what makes `GC_VOIDED`
    reachable - the SPI can compose the attempt write because it can resolve the attempt.
    """
    pointer = _get(table, transaction_pointer_key(transaction_id))
    if not pointer:
        raise TransactionNotFound("no such gift-card transaction")
    return {"codeHash": str(pointer.get("codeHash") or ""),
            "paymentAttemptId": str(pointer.get("paymentAttemptId") or "")}


def resolve_attempt(table: Any, *, wix_order_id: Any) -> str:
    """`GCWIXORDER#<wixOrderId>` -> `paymentAttemptId`, for a Wix-originated call."""
    pointer = _get(table, wix_order_key(wix_order_id))
    if not pointer:
        raise TransactionNotFound("no such Wix order on this ledger")
    return str(pointer.get("paymentAttemptId") or "")


def reserved_by(card: Optional[Mapping[str, Any]], *, now_ms: int) -> str:
    """The attempt id holding this card, or `""`. ONE row, already read by exact key.

    DECISION 5: this is what lets `/v1/redeem` refuse an already-spoken-for card without a prefix
    query. A CLAIM never lapses, so it reserves unconditionally; a HOLD reserves only until its
    expiry, which is what lets an abandoned checkout stop blocking the next one.
    """
    if not card:
        return ""
    claim = card.get(CLAIM_ATTEMPT_ATTRIBUTE)
    if claim:
        return str(claim)
    holder = card.get(HOLD_ATTEMPT_ATTRIBUTE)
    if holder and int(card.get(HOLD_EXPIRY_ATTRIBUTE) or 0) > int(now_ms):
        return str(holder)
    return ""


def list_by_status(table: Any, status: Any, *, limit: int = 50,
                   start_key: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The staff list, through `status-index`. The ONLY non-exact-key access in this module.

    Sparse by construction: only card rows carry `status`, so transactions, claims, holds and
    pointer rows never enter the index. `createdAt` is the range key so a query stays bounded to a
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

    Only `wecare-gift-cards` reaches this function. The SPI handler has no code path to it, which
    is the structural guarantee behind "the SPI role cannot issue a card" - IAM cannot distinguish
    issuance from a transaction record, because both are a `PutItem` on the same table.
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
    """Add to a balance, with the SPI ceiling asserted IN THE CONDITION.

    The ceiling is a condition rather than a pre-read check for the same reason the floor is: two
    concurrent credits that each pass a read-time check can together exceed it.

    A PLAIN ADDITION, and that is the only correct shape for this function. It used to take an
    `once_key` that made the credit idempotent on one item, for the void path's benefit. That
    parameter is gone: a genuine top-up must NOT be idempotent, because two top-ups of the same
    size are two different events and nothing should collapse them. The void path's idempotency
    now lives where it belongs - in `_commit_void`'s `credited = :false` condition, committed in
    the same transaction as the money.

    SO A CALLER MUST BRING ITS OWN IDEMPOTENCY, AND HERE IS WHERE IT GOES. There is no
    production caller today, which is what made removing `once_key` safe; a future top-up route
    inherits a non-idempotent money function, so state the obligation rather than leave it to be
    rediscovered. The guard belongs in the SAME `TransactWriteItems` as the balance move, as a
    second `Update` item on a row keyed by the top-up's own event id and conditioned on
    `attribute_not_exists` - the shape `_commit_redemption` and `_commit_void` already use, and
    the only shape where a replay cannot move money and then fail to record that it did. A
    pre-read "has this already happened" check in the caller is not a substitute: two concurrent
    replays both pass it.
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
                f"a balance may not exceed {MAX_VALUE_PAISE} paise, the SPI maximum") from None
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

    Keyed on `paymentAttemptId` and not `referenceId`, because section 3.3 requires the hold to
    precede the gateway and on the website path `attempt["referenceId"]` IS the Razorpay order
    id - which does not exist until after. `paymentAttemptId` is minted first on both producers.

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
                                 "AND attribute_not_exists(activeClaimAttemptId) "
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
                                 "AND attribute_not_exists(activeClaimAttemptId) "
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
    TTL would make that silent. There is deliberately no function here that can delete a card, a
    transaction, a claim or a pointer row.
    """
    try:
        table.delete_item(Key={KEY_ATTRIBUTE: PREFIX_HOLD + digest + "#" + attempt_id})
    except Exception as error:  # noqa: BLE001
        raise GiftCardStoreUnavailable(
            f"could not delete a gift-card hold: {type(error).__name__}") from error


def bind_wix_order(table: Any, *, wix_order_id: Any, attempt_id: Any,
                   clock: Clock = _default_clock) -> Dict[str, Any]:
    """`GCWIXORDER#<wixOrderId>` -> `paymentAttemptId`, written when `wixOrderId` first exists.

    The second pointer row. It is what lets a Wix-originated call about a Wix order GUID resolve
    to the purchase our claim is keyed on, and it is written at writeback time (SEAM-G10) rather
    than guessed at.
    """
    key = wix_order_key(wix_order_id)
    attempt = _identifier(attempt_id, "INVALID_ATTEMPT_ID")
    now = _now_seconds(clock)
    item = {KEY_ATTRIBUTE: key, "kind": "GIFT_CARD_WIX_ORDER", "paymentAttemptId": attempt,
            "createdAt": now}
    if not _put(table, item, condition=f"attribute_not_exists({KEY_ATTRIBUTE})"):
        existing = _get(table, key) or {}
        return {"bound": False, "paymentAttemptId": str(existing.get("paymentAttemptId") or "")}
    return {"bound": True, "paymentAttemptId": attempt}


def redeem(table: Any, *, code_hash: Any, attempt_id: Any, amount_paise: Any,
           source: str = SOURCE_OURS, reference_id: str = "", wix_order_id: str = "",
           clock: Clock = _default_clock,
           sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Move balance, exactly once per `(codeHash, paymentAttemptId)`.

    ORDER IS LOAD-BEARING: claim, then ONE TRANSACTION that moves the balance and settles the
    claim together, then the ledger records.

    1. `GCORDER#<codeHash>#<paymentAttemptId>` is a conditional put with
       `attribute_not_exists(giftCardKey)`, written BEFORE the balance moves and carrying the
       `transactionId` of the redemption that won. A replay loses the put, reads the winning row
       and returns that same `transactionId` with the balance untouched.
    2. The balance move and the claim's `settled` flag are **two `Update` items in one
       `TransactWriteItems`**: the card under `balancePaise >= :amount AND #status = :active`,
       the claim under `settled = :false`. A read-then-write would let two concurrent
       redemptions both pass a `balance >= amount` check and overdraw the card; two separate
       writes would leave a window in which the money has moved and the claim is unsettled, and
       a retry arriving in that window used to debit the card a second time for one
       `paymentAttemptId`.

    `settled = :false` IS the idempotency guard, and it now commits with the money. A racing
    second redemption fails that condition, the whole transaction is cancelled, nothing moves,
    and it takes the replay branch. The guarantee no longer depends on any marker's lifetime, so
    there is no `appliedClaim#` and nothing to clean up.

    The ordinary duplicate is answered EARLIER and more cheaply, by the pre-read: the conditional
    claim put loses, the existing claim is read, and a `settled` claim returns the replay answer
    with no transaction opened at all. The transaction's conditions are the CONCURRENCY
    RE-CHECK, not the primary decision.

    INVARIANT, because this figure is customer-visible - the SPI emits it as
    `remainingBalance`, which is what Wix shows and settles against:

        `remainingBalancePaise` and `GCTXN#.balanceAfterPaise` are the card's balance **as at
        the read that followed the commit**, which may already include a later interleaved move.
        They are observations, not the result of this transaction. `TransactWriteItems` returns
        no `ALL_NEW`, so an exact post-this-transaction figure is not obtainable. The figure
        that IS exact is `amountPaise`, and the authoritative balance is always a fresh
        consistent read of the card row.

    `source` records whether this was ours or a Wix `/v1/redeem`. Section 1.3 predicts `WIX_SPI`
    never appears, so its appearance is the detector for that prediction being wrong, and
    `wecare-gift-card-wix-spi-redemption` alarms on a single occurrence.

    `sleep` is injected for the bounded retry inside `_transact_with_retry`, exactly as `clock`
    is injected, so the covering test runs at full speed. No production caller passes it.
    """
    digest = _hash_hex(code_hash)
    attempt = _identifier(attempt_id, "INVALID_ATTEMPT_ID")
    amount = value_paise(amount_paise)
    if source not in SOURCES:
        raise GiftCardValidationError("INVALID_SOURCE", f"source must be one of {SOURCES}")
    now = _now_seconds(clock)
    claim_row_key = PREFIX_CLAIM + digest + "#" + attempt
    transaction_id = new_transaction_id()

    claim: Dict[str, Any] = {
        KEY_ATTRIBUTE: claim_row_key, "kind": "GIFT_CARD_CLAIM", "codeHash": digest,
        "paymentAttemptId": attempt, "transactionId": transaction_id, "amountPaise": amount,
        "claimedAt": now, "settled": False, "source": source,
    }
    # `referenceId` is recorded for CORRELATION and is never used as a key: it is two different
    # things depending on which producer built the attempt (a `WD-PAY-` reference on the
    # in-WhatsApp path, the Razorpay order id on the website path).
    if reference_id:
        claim["referenceId"] = _identifier(reference_id, "INVALID_REFERENCE_ID")
    if wix_order_id:
        claim["wixOrderId"] = _identifier(wix_order_id, "INVALID_WIX_ORDER_ID")

    won = _put(table, claim, condition=f"attribute_not_exists({KEY_ATTRIBUTE})")
    if not won:
        existing = _get(table, claim_row_key) or {}
        transaction_id = str(existing.get("transactionId") or "")
        if int(existing.get("amountPaise") or 0) != amount:
            # Same claim key, different amount. That is not a replay, it is two different requests
            # wearing one identity, and silently honouring either one would move a figure nobody
            # agreed to. Surfaced rather than reconciled, because only the caller knows which is
            # authoritative.
            raise GiftCardValidationError(
                "REDEEM_AMOUNT_CONFLICT",
                "this purchase already claims a different redemption amount")
        if existing.get("settled"):
            card = get_card(table, code_hash=digest) or {}
            return {"committed": False, "transactionId": transaction_id,
                    "remainingBalancePaise": int(card.get("balancePaise") or 0),
                    "codeLast4": str(card.get("codeLast4") or ""),
                    "paymentAttemptId": attempt}
        # An unsettled claim means a previous attempt reached the claim and not the decrement.
        # Re-driven under the SAME transaction id, so a retry cannot mint a second one. The amount
        # is already known to match, by the conflict check above.

    balance_after, committed = _commit_redemption(
        table, digest=digest, claim_row_key=claim_row_key, amount=amount, attempt=attempt,
        now=now, sleep=sleep)
    if not committed:
        # A concurrent redemption under this same attempt won. It owns the ledger rows; writing
        # them from here would be a second `GCTXN#` for one money move. Answered exactly as the
        # ordinary settled replay is, from the claim row the winner settled.
        settled_claim = _get(table, claim_row_key) or {}
        card = get_card(table, code_hash=digest) or {}
        return {"committed": False,
                "transactionId": str(settled_claim.get("transactionId") or transaction_id),
                "remainingBalancePaise": balance_after,
                "codeLast4": str(card.get("codeLast4") or ""),
                "paymentAttemptId": attempt}
    _record_balance_after(table, claim_row_key, balance_after=balance_after, now=now)

    record = {
        KEY_ATTRIBUTE: PREFIX_TRANSACTION + digest + "#" + transaction_id,
        "kind": KIND_REDEEM, "codeHash": digest, "transactionId": transaction_id,
        "paymentAttemptId": attempt, "amountPaise": amount,
        "balanceAfterPaise": balance_after, "source": source, "createdAt": now,
    }
    if reference_id:
        record["referenceId"] = reference_id
    if wix_order_id:
        record["wixOrderId"] = wix_order_id
    _put(table, record)
    _put(table, {KEY_ATTRIBUTE: PREFIX_TRANSACTION_ID + transaction_id,
                 "kind": "GIFT_CARD_TRANSACTION_POINTER", "codeHash": digest,
                 # DECISION 9: the pointer carries the attempt too, so a void arriving by
                 # transaction id alone can resolve BOTH the card and the payment attempt - which
                 # is what makes the SPI's `GC_VOIDED` write composable rather than theoretical.
                 "paymentAttemptId": attempt, "createdAt": now})
    return {"committed": True, "transactionId": transaction_id,
            "remainingBalancePaise": balance_after, "paymentAttemptId": attempt,
            "amountPaise": amount, "source": source}


def _commit_redemption(table: Any, *, digest: str, claim_row_key: str, amount: int,
                       attempt: str, now: int,
                       sleep: Callable[[float], None] = time.sleep) -> tuple:
    """The balance move and the claim's settle, as ONE `TransactWriteItems`. Two `Update` items.

    Returns `(balance_after, committed)`. `committed` is `False` when this call lost the race to
    a CONCURRENT redemption under the same `paymentAttemptId` - the transaction was cancelled on
    `settled = :false` and the money moved exactly once, but it was not moved by us. Returning a
    bare balance here would let both racing callers answer `committed: True`, which is two
    callers each believing they moved money that moved once: a self-consistent ledger saying
    something false, which is the failure class this whole section exists to remove.

    The card item gates on the BALANCE rather than on the claim, deliberately: a second,
    genuinely different purchase of the same card SHOULD deduct again, and the claim row is what
    makes a REPLAY idempotent. The `AlreadyRedeemed` refusal is a different rule with a
    different owner - it applies only to a WIX-originated `/v1/redeem`, is decided in the SPI
    handler through `reserved_by`, and exists because our `paymentAttemptId` and Wix's `orderId`
    are not comparable. Folding it in here would make a customer's second purchase refuse.

    `activeHoldAttemptId` is set through `if_not_exists` so a Wix-originated redemption with no
    prior hold still leaves the card reading as spoken-for to the NEXT `/v1/redeem` - which is
    what makes that refusal a single `GetItem` rather than a prefix query.

    The claim item's `settled = :false` is the money's idempotency guard, and it commits in the
    same transaction as the balance. `balancePaise >= :amount` stops an OVERDRAW; `settled =
    :false` stops a SECOND DEDUCTION for one `paymentAttemptId`. Before they were one
    transaction the second guard lived on a second item, so it could only be written after the
    money had already moved, and a retry arriving in that window debited twice.

    `TransactWriteItems` is a CLIENT operation, so this is the real boto3 shape:
    AttributeValue-typed maps through `_marshal`, with `TableName=table.name`. There is no
    fake-shaped branch - the test fake supplies `.name` and `.meta.client`.
    """
    card_item = {"Update": {
        "TableName": table.name,
        "Key": {KEY_ATTRIBUTE: _ser(PREFIX_CARD + digest)},
        "UpdateExpression": ("ADD balancePaise :neg SET updatedAt = :at, "
                             "activeClaimAttemptId = :me, "
                             "activeHoldAttemptId = if_not_exists(activeHoldAttemptId, :me)"),
        "ConditionExpression": (f"attribute_exists({KEY_ATTRIBUTE}) AND balancePaise >= :amount "
                                "AND #status = :active"),
        "ExpressionAttributeNames": {"#status": STATUS_ATTRIBUTE},
        "ExpressionAttributeValues": {":neg": _ser(-amount), ":amount": _ser(amount),
                                      ":me": _ser(attempt), ":at": _ser(now),
                                      ":active": _ser(STATUS_ACTIVE)},
    }}
    claim_item = {"Update": {
        "TableName": table.name,
        "Key": {KEY_ATTRIBUTE: _ser(claim_row_key)},
        "UpdateExpression": "SET settled = :true, settledAt = :at",
        "ConditionExpression": f"attribute_exists({KEY_ATTRIBUTE}) AND settled = :false",
        "ExpressionAttributeValues": {":true": _ser(True), ":false": _ser(False),
                                      ":at": _ser(now)},
    }}
    try:
        _transact_with_retry(table, [card_item, claim_item], sleep=sleep)
    except GiftCardStoreUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        if _is_transaction_cancellation(error):
            # Decide from the data, by exact key. A cancellation whose reasons are empty or
            # unrecognised arrives here too, by `_transact_with_retry`'s own fallback rule: a
            # cancellation is a condition outcome unless a reason says otherwise, and reporting
            # a successful replay detection as an outage is the wrong failure.
            claim = _get(table, claim_row_key) or {}
            card = get_card(table, code_hash=digest)
            if claim.get("settled"):
                # Lost the race to a concurrent redemption under the SAME attempt. The money
                # moved exactly once and it was not us, so this is the replay answer.
                return int((card or {}).get("balancePaise") or 0), False
            assert_spendable(card, now_ms=now * 1000)
            raise InsufficientFunds("this gift card does not hold that much") from None
        raise GiftCardStoreUnavailable(
            f"could not move a gift-card balance: {type(error).__name__}") from error
    card = get_card(table, code_hash=digest) or {}
    return int(card.get("balancePaise") or 0), True


def _commit_void(table: Any, *, digest: str, transaction_key: str, amount: int, now: int,
                 sleep: Callable[[float], None] = time.sleep) -> int:
    """The void twin of `_commit_redemption`. The credit and its flag, as ONE transaction.

    `attribute_exists(credited)` is written EXPLICITLY and is not redundant. A bare
    `credited = :false` already fails when the attribute is absent, so the two conditions accept
    the same set - but they are not diagnosable the same way. With `attribute_exists` named, the
    post-cancellation read can distinguish *absent* from *`True`* and answer each correctly;
    without it, "absent" matches no row, falls through to `GiftCardStoreUnavailable`, and every
    retry cancels again - so a card whose void predates the flag becomes PERMANENTLY
    UN-VOIDABLE. That is the mirror image of the irreversibility the uncredited-latch retry
    exists to prevent.
    """
    card_item = {"Update": {
        "TableName": table.name,
        "Key": {KEY_ATTRIBUTE: _ser(PREFIX_CARD + digest)},
        "UpdateExpression": "ADD balancePaise :amount SET updatedAt = :at",
        "ConditionExpression": (f"attribute_exists({KEY_ATTRIBUTE}) "
                                "AND balancePaise <= :ceiling"),
        "ExpressionAttributeValues": {":amount": _ser(amount), ":at": _ser(now),
                                      ":ceiling": _ser(MAX_VALUE_PAISE - amount)},
    }}
    transaction_item = {"Update": {
        "TableName": table.name,
        "Key": {KEY_ATTRIBUTE: _ser(transaction_key)},
        "UpdateExpression": "SET credited = :true, creditedAt = :at",
        "ConditionExpression": (f"attribute_exists({KEY_ATTRIBUTE}) "
                                "AND attribute_exists(credited) AND credited = :false"),
        "ExpressionAttributeValues": {":true": _ser(True), ":false": _ser(False),
                                      ":at": _ser(now)},
    }}
    try:
        _transact_with_retry(table, [card_item, transaction_item], sleep=sleep)
    except GiftCardStoreUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        if _is_transaction_cancellation(error):
            original = _get(table, transaction_key) or {}
            card = get_card(table, code_hash=digest)
            if card is None:
                raise GiftCardNotFound("no such gift card") from None
            if original.get("credited") is not False:
                # Either already credited, or latched by code predating the flag. Reachable here
                # only through a race, since the pre-read answers the ordinary duplicate.
                raise AlreadyVoided("this transaction was already voided") from None
            raise GiftCardValidationError(
                "BALANCE_CEILING_EXCEEDED",
                f"a balance may not exceed {MAX_VALUE_PAISE} paise, the SPI maximum") from None
        raise GiftCardStoreUnavailable(
            f"could not return a gift-card balance: {type(error).__name__}") from error
    card = get_card(table, code_hash=digest) or {}
    return int(card.get("balancePaise") or 0)


def _record_balance_after(table: Any, row_key: str, *, balance_after: int, now: int,
                          attribute: str = "balanceAfterPaise") -> None:
    """The post-commit balance, as a BEST-EFFORT follow-up `UpdateItem`.

    It cannot go inside the transaction, because `TransactWriteItems` has no
    `ReturnValues: ALL_NEW`. Nothing reads it to make a decision - every site that touches
    `balanceAfterPaise` is a write - so if this fails the claim is still settled and the money
    has still moved exactly once. Swallowed deliberately: the alternative is reporting a money
    move that succeeded as a failure.
    """
    try:
        table.update_item(
            Key={KEY_ATTRIBUTE: row_key},
            UpdateExpression="SET #observed = :balance, observedAt = :at",
            ConditionExpression=f"attribute_exists({KEY_ATTRIBUTE})",
            ExpressionAttributeNames={"#observed": attribute},
            ExpressionAttributeValues={":balance": balance_after, ":at": now},
        )
    except Exception:  # noqa: BLE001
        return


def void(table: Any, *, transaction_id: Any, clock: Clock = _default_clock,
         sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Reverse one redemption, resolved from the transaction id ALONE.

    `VoidRequest` carries no `code`, so this walks `GCTXNID#<transactionId>` to the card and - per
    DECISION 9 - to the payment attempt, which is what lets the SPI write `GC_VOIDED` through
    `advance()` rather than having no attempt id to write against.

    The `voidedBy` guard is written BEFORE the credit, for the same reason the claim precedes the
    decrement: if the credit went first and the guard then lost its race, the card would be
    credited twice.

    The guard carries `credited`, and that is what makes the ordering SURVIVABLE as well as safe.
    It is the same device `redeem` uses with the claim row's `settled`: the guard is latched
    `credited = False` and only the credit marks it `True`, so a credit that fails - a throttle
    surfacing as `GiftCardStoreUnavailable`, or a top-up between the redemption and the void
    pushing the return over the SPI ceiling - leaves a void a retry can COMPLETE. Without the
    flag, every retry read the latched `voidedBy` and refused, so the redemption stayed marked
    voided with the balance never returned and no way to return it.

    A retry re-drives the credit under the SAME `void_id`, read back off the latch, so it cannot
    mint a second void transaction. `credited` ABSENT is treated as complete rather than as
    pending: a latch written before this flag existed cannot be distinguished from one whose
    credit landed, and re-driving a credit that already happened would hand the balance back
    twice. Only an explicit `False` - which only this function writes - re-drives.

    And the re-drive is safe to take at face value because the credit and the `credited` flag
    commit in ONE `TransactWriteItems` (`_commit_void`), under `credited = :false`. The flag
    alone is sound in one direction only - it can never claim a credit landed when it did not -
    so `credited: False` used to cover both "the credit never ran" and "the credit ran and this
    write failed", and a retry on the strength of that read handed the balance back twice. With
    both in one transaction there is no second state to distinguish: either the money came back
    and the flag is `True`, or neither happened.

    The ordinary duplicate is answered by the PRE-READ below, with no transaction opened - one
    condition cheaper than opening a conditional transaction only to cancel it. The
    transaction's conditions are the concurrency re-check for a second `void()` that commits
    between this one's pre-read and its transaction.
    """
    pointer = resolve_transaction(table, transaction_id=transaction_id)
    digest = _hash_hex(pointer["codeHash"])
    original = get_transaction(table, code_hash=digest, transaction_id=transaction_id)
    if not original:
        raise TransactionNotFound("no such gift-card transaction")
    if original.get("kind") != KIND_REDEEM:
        raise TransactionNotFound("only a redemption can be voided")

    now = _now_seconds(clock)
    original_key = PREFIX_TRANSACTION + digest + "#" + _transaction_id(transaction_id)
    latched = original.get("voidedBy")
    if latched:
        if original.get("credited") is not False:
            raise AlreadyVoided("this transaction was already voided")
        # An uncredited latch. Re-drive below under the void id that already exists.
        void_id = _transaction_id(latched)
    else:
        void_id = new_transaction_id()
        try:
            table.update_item(
                Key={KEY_ATTRIBUTE: original_key},
                UpdateExpression="SET voidedBy = :void, voidedAt = :at, credited = :false",
                ConditionExpression="attribute_not_exists(voidedBy)",
                ExpressionAttributeValues={":void": void_id, ":at": now, ":false": False},
            )
        except Exception as error:  # noqa: BLE001
            if _is_conditional_failure(error):
                # Lost the latch to a CONCURRENT void, which is still mid-flight. Refusing is
                # correct here and re-driving would not be: the winner is about to credit, so a
                # second credit in this window is the double-credit the ordering exists to
                # prevent. A later retry reads the latch above and completes it if it stalled.
                raise AlreadyVoided("this transaction was already voided") from None
            raise GiftCardStoreUnavailable(
                f"could not void a gift-card transaction: {type(error).__name__}") from error

    amount = int(original.get("amountPaise") or 0)
    # One transaction: the balance comes back and `credited` flips together, so there is no
    # window in which the money has returned and the flag still reads `False`.
    balance_after = _commit_void(table, digest=digest, transaction_key=original_key,
                                 amount=amount, now=now, sleep=sleep)
    _record_balance_after(table, original_key, balance_after=balance_after, now=now,
                          attribute="voidBalanceAfterPaise")
    _put(table, {KEY_ATTRIBUTE: PREFIX_TRANSACTION + digest + "#" + void_id,
                 "kind": KIND_VOID, "codeHash": digest, "transactionId": void_id,
                 "paymentAttemptId": pointer["paymentAttemptId"], "amountPaise": amount,
                 "balanceAfterPaise": balance_after, "voids": str(transaction_id),
                 "source": str(original.get("source") or SOURCE_OURS), "createdAt": now})
    _put(table, {KEY_ATTRIBUTE: PREFIX_TRANSACTION_ID + void_id,
                 "kind": "GIFT_CARD_TRANSACTION_POINTER", "codeHash": digest,
                 "paymentAttemptId": pointer["paymentAttemptId"], "createdAt": now})
    card = get_card(table, code_hash=digest) or {}
    return {"transactionId": void_id, "voided": str(transaction_id),
            "remainingBalancePaise": balance_after, "codeHash": digest,
            "paymentAttemptId": pointer["paymentAttemptId"],
            "codeLast4": str(card.get("codeLast4") or "")}


__all__ = [
    "AlreadyRedeemed", "AlreadyVoided", "CARD_ATTRIBUTES", "CLAIM_ATTEMPT_ATTRIBUTE",
    "CODE_ALPHABET", "CODE_LENGTH", "CODE_PATTERN", "CURRENCY", "CurrencyNotSupported",
    "DEFAULT_TABLE_NAME", "GiftCardDisabled", "GiftCardError", "GiftCardExpired",
    "GiftCardHeldByAnotherPurchase", "GiftCardNotFound", "GiftCardStoreUnavailable",
    "GiftCardValidationError", "HOLD_ATTEMPT_ATTRIBUTE", "HOLD_CONDITION",
    "HOLD_EXPIRY_ATTRIBUTE", "HOLD_PAISE_ATTRIBUTE", "HOLD_TTL_SECONDS", "InsufficientFunds",
    "KEY_ATTRIBUTE", "KIND_REDEEM", "KIND_VOID", "MAX_CODE_LENGTH", "MAX_PIN_LENGTH",
    "MAX_VALUE_PAISE", "MIN_CODE_LENGTH", "MissingCurrency", "MONEY_CEILING_PAISE",
    "PEPPER_FIELD", "PEPPER_SECRET_ENV_KEY", "resolve_pepper_secret_id",
    "POLICY_VERSION", "PREFIX_CARD", "PREFIX_CARD_ID", "PREFIX_CLAIM",
    "PREFIX_HOLD", "PREFIX_TRANSACTION", "PREFIX_TRANSACTION_ID", "PREFIX_WIX_ORDER",
    "RAZORPAY_MIN_LEG_PAISE", "SECRET_ENV_KEY", "SECRET_ID", "SOURCES", "SOURCE_OURS",
    "SOURCE_WIX_SPI", "SPI_ERRORS", "STATUSES", "STATUS_ACTIVE", "STATUS_ATTRIBUTE",
    "STATUS_DISABLED", "STATUS_INDEX", "TABLE_ENV_KEY", "TRANSACTION_KINDS",
    "TransactionNotFound", "assert_currency", "assert_spendable", "bind_wix_order", "card_id_key",
    "card_key", "card_key_from_hash", "claim_key", "code_hash", "code_last4", "credit",
    "disable", "generate_code", "get_card", "get_card_by_id", "get_claim", "get_transaction",
    "hold", "hold_key", "issue", "list_by_status", "masked", "new_transaction_id",
    "normalise_code", "pin_hash", "read_pepper", "reconcile_with_wix", "redeem", "redeem_cap",
    "release", "reserved_by", "resolve_attempt", "resolve_transaction", "split_payment",
    "transaction_key", "transaction_pointer_key", "validate_redeem_request", "value_paise",
    "verify_pin", "wix_order_key",
]
