"""Payment-attempt identity before payment, order identity only after payment.

The rule this module enforces
-----------------------------
**An order does not exist until a payment has been authoritatively verified as paid.** A cart
is not an order, a checkout is not an order, and a payment attempt is not an order. So the
identifiers split in two, and the split is the whole point of this file:

    before payment      paymentAttemptId (UUIDv7)  +  Meta reference_id
    after PAID          orderId (UUIDv7)           +  orderNumber (12 chars, public)

Nothing here will mint an order number as a side effect of starting a payment. An earlier
version of this module did exactly that - `allocate_order_identity` bound a Meta reference to a
freshly reserved order number at payment-request time - and it is gone rather than deprecated,
because a deprecated function that reserves an order number is a function someone calls.

Why reference_id and orderNumber cannot be the same string
----------------------------------------------------------
Meta's Payments (India) reference requires `reference_id` to be at most **35 characters** drawn
from letters, numbers, underscores, dashes and dots. The legacy WD order number is 46
characters and contains spaces and colons, so deriving one from the other meant stripping and
then truncating - and truncating a join key is how two orders quietly become one payment. They
are different identifiers with different consumers:

    reference_id   machine join key. Meta, Razorpay and our reconciliation agree on it.
                   Unordered, minted from `secrets`, never shown to a customer.
    orderNumber    human display string. Read aloud on the phone, typed into a tracking box.
                   12 characters, unambiguous alphabet, and deliberately NOT time-ordered.

`orderNumber` uses an alphabet without `0 O 1 I L` because it gets read aloud. `paymentAttemptId`
and `orderId` are UUIDv7 and *are* time-ordered, which is safe precisely because they are
internal - a time-ordered public number would leak order volume.

The key space
-------------
Namespaced rows on one partition attribute. Nothing here may ever carry a TTL: a uniqueness
reservation that expires is an identifier that gets reissued, which defeats the entire purpose.
The table this writes to has TTL `DISABLED`; keep it that way.

    PAYREF#<referenceId>            -> paymentAttemptId      before payment
    PAYMENTATTEMPT#<attemptId>      -> orderId, orderNumber   after PAID, the idempotency anchor
    PROVIDERPAYMENT#<transactionId> -> orderId                after PAID, provider uniqueness
    ORDERNO#<orderNumber>           -> reservation            after PAID
    REFERENCE#<referenceId>          legacy, read-only compatibility

Ordering matters and is not arbitrary. `orderId` is minted locally and costs nothing, so it is
minted *first* and used to claim both post-paid markers. Only the claim winner then reserves an
order number. A loser therefore never burns a number, and a crash between claiming and reserving
is recoverable because re-entry resolves the same claim and finds the number missing.

Failure posture
---------------
Everything fails **closed**. A `ConditionalCheckFailedException` is a normal race and is retried
with a fresh candidate. Any other storage error raises `OrderIdentityUnavailable` and yields no
identifier, because an unreserved identifier handed to a caller is a duplicate waiting to happen.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from typing import Any, Callable, Dict, Optional, Tuple

from lambda_utils.identifiers import new_uuid7

logger = logging.getLogger(__name__)

# ── Meta Payments (India) constraints ───────────────────────────────────────────
# Source: Meta for Developers, "Receive payments via payment gateways on WhatsApp",
# Parameters Object -> reference_id (updated 2026-05-21). Paraphrased: required, case
# sensitive, non-empty, only English letters, numbers, underscores, dashes or dots, and not
# more than 35 characters.
# https://developers.facebook.com/docs/whatsapp/cloud-api/payments-api/payments-in/pg
META_REFERENCE_ID_MAX_LENGTH = 35
_META_REFERENCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,%d}$" % META_REFERENCE_ID_MAX_LENGTH)

#: Razorpay's `receipt` tolerates 40 characters, so a valid reference_id always fits.
RAZORPAY_RECEIPT_MAX_LENGTH = 40

# ── key prefixes ───────────────────────────────────────────────────────────────
PAYMENT_REFERENCE_PREFIX = "PAYREF#"
PAYMENT_ATTEMPT_PREFIX = "PAYMENTATTEMPT#"
PROVIDER_PAYMENT_PREFIX = "PROVIDERPAYMENT#"
ORDER_NUMBER_PREFIX = "ORDERNO#"

#: Superseded by PAYMENT_REFERENCE_PREFIX. Retained read-only so rows written before the
#: order-after-payment rule remain resolvable; nothing writes it.
LEGACY_REFERENCE_PREFIX = "REFERENCE#"

# ── reference_id minting ───────────────────────────────────────────────────────
REFERENCE_ID_PREFIX = "WD-PAY-"

#: Crockford-style base32 without I, L, O, U. Inside Meta's permitted charset.
_REFERENCE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: 14 symbols over 32 is 70 bits. The conditional write is what guarantees uniqueness; this
#: only has to make a collision rare enough that the retry loop is never the hot path.
_REFERENCE_ENTROPY_SYMBOLS = 14

# ── public order number ────────────────────────────────────────────────────────
#: The customer-facing number carries a readable prefix, e.g. `WD-ORD-K4M7PQR9`.
#:
#: The prefix is not decoration. This string is read aloud to support, pasted into a tracking
#: box and quoted in WhatsApp, and a bare `K4M7PQR9` is indistinguishable from a coupon, a
#: tracking id or a payment reference. `WD-ORD-` says what it is.
PUBLIC_ORDER_NUMBER_PREFIX = "WD-ORD-"

#: Random symbols after the prefix. EIGHT, and the number was chosen by measurement.
#:
#: The alphabet below is 30 symbols, so with a conditional-write reservation:
#:
#:     6 symbols  ~29.4 bits   729,000,000   50% chance of a collision by ~33,800 orders
#:     8 symbols  ~39.3 bits   656.1 billion 50% chance of a collision by ~1,015,000 orders
#:    12 symbols  ~58.9 bits   5.31e17       50% chance of a collision by ~914,000,000 orders
#:
#: A collision is never *wrong* - `reserve_public_order_number` refuses it and regenerates - so
#: the question is only whether the retry loop becomes the hot path, and whether the number is
#: guessable. At six symbols a blind guess against a 100,000-order corpus hits 1 in 7,290, which
#: is enumerable by anything that can make requests. At eight it is 1 in 6,561,000, and the retry
#: loop stays theoretical past a million orders. Twelve was the previous value and is more than
#: this business needs; eight keeps the number short enough to read aloud.
#:
#: Guessability still must not be the only thing protecting anything. A receipt is authorised by
#: a signed link or a session, never by knowing an order number - see `receipt_links.py`.
PUBLIC_ORDER_NUMBER_ENTROPY = 8

#: Total minted length: 7 characters of prefix plus 8 of entropy.
PUBLIC_ORDER_NUMBER_LENGTH = len(PUBLIC_ORDER_NUMBER_PREFIX) + PUBLIC_ORDER_NUMBER_ENTROPY

#: THIRTY symbols, and the exclusions are the point: 0, 1, I, L, O and U are gone, because they
#: are where transcription errors come from when a number is read down a phone line. The comment
#: here previously said "27 symbols ... ~57 bits" and both figures were wrong - the alphabet has
#: always been 30 characters, which over the old 12 positions was ~58.9 bits rather than 57.
PUBLIC_ORDER_NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"

_PUBLIC_ORDER_NUMBER_RE = re.compile(
    r"^%s[%s]{%d}$" % (re.escape(PUBLIC_ORDER_NUMBER_PREFIX),
                       PUBLIC_ORDER_NUMBER_ALPHABET,
                       PUBLIC_ORDER_NUMBER_ENTROPY)
)

#: The bare 12-character form minted before the prefix existed.
#:
#: STILL VALID FOR LOOKUP, and that is not optional. Numbers already issued are printed on
#: receipts, sitting in customers' WhatsApp history and quoted to support. A validator that
#: stopped recognising them would break tracking and receipt resolution for every order placed
#: before this change, which is the one thing `never reused` was written to prevent.
#:
#: Nothing MINTS this form any more - `mint_public_order_number` only produces the prefixed one.
LEGACY_PUBLIC_ORDER_NUMBER_LENGTH = 12

_LEGACY_PUBLIC_ORDER_NUMBER_RE = re.compile(
    r"^[%s]{%d}$" % (PUBLIC_ORDER_NUMBER_ALPHABET, LEGACY_PUBLIC_ORDER_NUMBER_LENGTH)
)

_DEFAULT_ATTEMPTS = 5

# Accepts every `WD-ORD` spelling this system has ever written. THREE, and the third was
# added when the Wix minter moved to the current format:
#
#   1. the spaced display form the Wix sync used to generate ('WD-ORD - A1B2C3D4 - ...'),
#   2. the compact form the Order table's `orderId` uses ('WD-ORD-A1B2C3D4'), both 8 HEX, and
#   3. the CURRENT public form, whose tail is 8 symbols of PUBLIC_ORDER_NUMBER_ALPHABET.
#
# One pattern deliberately - the bug this replaced was a `startswith` that silently
# recognised only one of them. Branch 3 exists because the alphabet runs past F, so a
# hex-only pattern did not match a number the Wix path had just minted. Two live sites ask
# this question and BOTH fail in the dangerous direction when the answer is wrongly False:
# `wix-store._get_or_create_wd_order_number` reuses a stored mapping only if it matches, and
# `outbound-whatsapp._sanitize_reference_id` refuses to send an order number to Meta as a
# payment reference only if it matches.
#
# WIDENING ONLY. Every legacy value this accepted before is still accepted.
_WD_ORDER_NUMBER_RE = re.compile(
    r"^WD-ORD\s*-\s*(?:[0-9A-F]{8}|[%s]{%d})\b"
    % (PUBLIC_ORDER_NUMBER_ALPHABET, PUBLIC_ORDER_NUMBER_ENTROPY),
    re.IGNORECASE,
)


class OrderIdentityUnavailable(RuntimeError):
    """An identifier could not be durably reserved.

    Callers MUST propagate this. Falling back to an unreserved identifier is the defect this
    module exists to remove, so there is deliberately no "best effort" variant.
    """


def is_conditional_failure(error: Exception) -> bool:
    """A DynamoDB ConditionalCheckFailedException, as opposed to any other failure.

    Public because a caller outside this module needs it: `website_checkout`'s create-right claim
    must tell "somebody else holds it" from "storage is broken", and those two answers differ by
    whether a second payable order may be created. The tree already held three inline copies of
    this check, so a fourth in the one function whose whole point is "this is not best-effort"
    was the worst possible place for a copy to drift.
    """
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


#: The private name the six internal call sites in this module already use. Kept as an alias
#: rather than renamed at every site, because that is churn with no benefit.
_is_conditional_failure = is_conditional_failure


# ── validation ─────────────────────────────────────────────────────────────────

def is_valid_meta_reference_id(value: Any) -> bool:
    """True when `value` satisfies Meta's documented charset and 35-character limit."""
    return isinstance(value, str) and bool(_META_REFERENCE_ID_RE.match(value))


def assert_valid_meta_reference_id(value: Any) -> str:
    """Return `value` if Meta would accept it, else raise `ValueError`.

    Called before a send rather than after a rejection. An invalid `reference_id` surfaces at
    Meta as a generic failure that reads like an outage, and the customer simply cannot pay.

    Note what this deliberately does NOT do: truncate. The previous `_sanitize_reference_id`
    cut over-long values to 35 characters, which silently maps two distinct identifiers onto
    one and joins two orders to a single payment. Rejecting is the only safe response.
    """
    if not is_valid_meta_reference_id(value):
        raise ValueError(
            "reference_id must be 1-%d characters of [A-Za-z0-9._-] and is never truncated; "
            "got %r (length %d)"
            % (META_REFERENCE_ID_MAX_LENGTH, value,
               len(value) if isinstance(value, str) else -1)
        )
    return value


def is_public_order_number(value: Any) -> bool:
    """True for any public order number this system has ever issued.

    Accepts BOTH the current `WD-ORD-XXXXXXXX` form and the bare 12-character form minted before
    the prefix existed. Use this wherever a customer-supplied number is being resolved - tracking,
    receipt lookup, support - because refusing a historical number would break every order placed
    before the change.

    Use `is_current_public_order_number` where the question is "did we just mint this correctly".
    """
    if not isinstance(value, str):
        return False
    return bool(_PUBLIC_ORDER_NUMBER_RE.match(value)
                or _LEGACY_PUBLIC_ORDER_NUMBER_RE.match(value))


def is_current_public_order_number(value: Any) -> bool:
    """True only for the current `WD-ORD-` + 8 form.

    Separate from `is_public_order_number` on purpose. A test that asserts the minter produces the
    current format must not pass just because the legacy shape is still accepted for lookup, which
    is exactly how a format migration quietly fails to happen.
    """
    return isinstance(value, str) and bool(_PUBLIC_ORDER_NUMBER_RE.match(value))


def is_wd_order_number(value: Any) -> bool:
    """True for a `WD-ORD` order number in any format this system has written.

    Both legacy spellings - spaced and compact, 8 hex - and the current `WD-ORD-` + 8 form.
    Replaces `startswith('WD-ORD-')`, which never matched the spaced format the generator
    used to produce and so made the reuse check dead code.

    Not the same question as `is_public_order_number`. This one asks "is this string one of
    our order numbers", including the hex-tailed legacy values that fall outside the public
    alphabet; that one asks "is this a number a customer may quote back to us for lookup".
    """
    return isinstance(value, str) and bool(_WD_ORDER_NUMBER_RE.match(value.strip()))


# ── minting ────────────────────────────────────────────────────────────────────

def new_payment_attempt_id() -> str:
    """A fresh internal payment-attempt identifier. Never shown to a customer."""
    return new_uuid7()


def new_order_id() -> str:
    """A fresh internal order identifier.

    Minted locally and used to claim the post-paid markers, so it must cost nothing and touch
    no storage. Never derived from the public order number, and never the other way round.
    """
    return new_uuid7()


def mint_payment_reference(prefix: str = REFERENCE_ID_PREFIX,
                           symbols: int = _REFERENCE_ENTROPY_SYMBOLS) -> str:
    """Mint a fresh Meta-safe `reference_id` for one payment attempt.

    Uses `secrets`, never `random`: `random` is seeded per execution environment and a
    SnapStart snapshot freezes that seed, so every restored sandbox would replay the same
    sequence. SnapStart is off across the fleet today, but a payment join key is the last place
    to depend on that remaining true.
    """
    candidate = prefix + "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(symbols))
    return assert_valid_meta_reference_id(candidate)


def mint_public_order_number() -> str:
    """Mint a candidate public order number: `WD-ORD-` plus 8 CSPRNG symbols.

    Unordered and carrying no timestamp, unlike `orderId`. Two reasons: a time-ordered public
    number leaks order volume to anyone holding two of them, and a customer-facing number must
    not imply anything about when the business is busy. It encodes no phone number, no email
    and no customer id - the tail is 8 symbols of CSPRNG output and nothing else.

    The ENTROPY is generated, the prefix is a constant. A reader should never have to wonder
    whether `WD-ORD-` came out of the random source.

    A candidate is not an order number until `reserve_public_order_number` has committed it.
    """
    tail = "".join(
        secrets.choice(PUBLIC_ORDER_NUMBER_ALPHABET)
        for _ in range(PUBLIC_ORDER_NUMBER_ENTROPY)
    )
    return PUBLIC_ORDER_NUMBER_PREFIX + tail


#: Superseded name, kept so existing callers on the send path keep working.
mint_reference_id = mint_payment_reference


# ── reservation primitive ──────────────────────────────────────────────────────

def _claim_row(table: Any, key_attr: str, key: str,
               item: Dict[str, Any]) -> bool:
    """Conditionally write one reservation row. True if won, False if already taken.

    Raises `OrderIdentityUnavailable` on anything that is not a lost race, so a throttle or an
    outage can never be mistaken for "already claimed".
    """
    payload = dict(item)
    payload[key_attr] = key
    try:
        table.put_item(
            Item=payload,
            ConditionExpression="attribute_not_exists(%s)" % key_attr,
        )
        return True
    except Exception as error:  # noqa: BLE001 - re-raised below unless it is a lost race
        if _is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not claim %r: %s" % (key, type(error).__name__)
        ) from error


def _read_row(table: Any, key_attr: str, key: str) -> Optional[Dict[str, Any]]:
    """Read one reservation row, or None. Raises on a storage error.

    A read failure must not be reported as absence: callers treat absence as "no order exists
    for this reference", and a throttle answering "absent" would let a payment event be
    discarded as unknown.
    """
    try:
        return table.get_item(Key={key_attr: key}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise OrderIdentityUnavailable(
            "could not read %r: %s" % (key, type(error).__name__)
        ) from error


# ── before payment: the payment reference ──────────────────────────────────────

def reserve_payment_reference(table: Any,
                              *,
                              reference_id: str,
                              payment_attempt_id: str,
                              key_attr: str = "orderId",
                              extra: Optional[Dict[str, Any]] = None) -> bool:
    """Bind `reference_id` to one payment attempt. True if claimed, False if already bound.

    Note what this row does NOT contain: an order, an order number, or any hint that one will
    exist. That is the order-after-payment rule expressed in the data rather than in a comment.
    """
    assert_valid_meta_reference_id(reference_id)
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")

    item = {
        "kind": "PAYMENT_REFERENCE",
        "referenceId": reference_id,
        "paymentAttemptId": payment_attempt_id,
        "reservedAt": int(time.time()),
    }
    if extra:
        item.update(extra)
    return _claim_row(
        table, key_attr, PAYMENT_REFERENCE_PREFIX + reference_id, item
    )


def resolve_payment_reference(table: Any, reference_id: str, *,
                              key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The payment-attempt row for `reference_id`, or None.

    None means **no payment attempt exists for this reference**. A payment event must not
    create one: an event naming an unknown reference is either a forgery or a lost write, and
    both call for staff attention rather than a new attempt.

    Falls back to the legacy `REFERENCE#` prefix so rows written before the split still
    resolve. Nothing writes that prefix any more.
    """
    if not reference_id:
        return None
    row = _read_row(table, key_attr, PAYMENT_REFERENCE_PREFIX + reference_id)
    if row is not None:
        return row
    return _read_row(table, key_attr, LEGACY_REFERENCE_PREFIX + reference_id)


def allocate_payment_reference(table: Any,
                               *,
                               payment_attempt_id: str,
                               key_attr: str = "orderId",
                               attempts: int = _DEFAULT_ATTEMPTS,
                               extra: Optional[Dict[str, Any]] = None) -> str:
    """Mint and durably bind a fresh reference for a payment attempt, or raise.

    Reserves before returning, so no caller can hold a reference that storage has not
    committed to. Creates **no order identity of any kind**.
    """
    for attempt in range(1, max(1, attempts) + 1):
        candidate = mint_payment_reference()
        if reserve_payment_reference(
            table, reference_id=candidate, payment_attempt_id=payment_attempt_id,
            key_attr=key_attr, extra=extra,
        ):
            return candidate
        logger.warning(
            "payment reference collision on attempt %d/%d; regenerating", attempt, attempts
        )
    raise OrderIdentityUnavailable(
        "exhausted %d attempts allocating a payment reference" % attempts
    )


# ── after PAID: order identity ─────────────────────────────────────────────────

def reserve_public_order_number(table: Any,
                                *,
                                order_id: str,
                                key_attr: str = "orderId",
                                generate: Optional[Callable[[], str]] = None,
                                attempts: int = _DEFAULT_ATTEMPTS,
                                extra: Optional[Dict[str, Any]] = None) -> str:
    """Generate and durably reserve a unique 12-character public order number, or raise.

    Call this only after a payment has been authoritatively verified as paid. The reservation
    row is written **before** the number is returned, so no caller can ever hold a number that
    storage has not committed to; that ordering is the whole contract.
    """
    generate = generate or mint_public_order_number
    now = int(time.time())

    for attempt in range(1, max(1, attempts) + 1):
        candidate = generate()
        item = {
            "kind": "ORDER_NUMBER_RESERVATION",
            "orderNumber": candidate,
            # `orderIdRef`, not `orderId`: on this table `orderId` IS the partition attribute,
            # so a business field of the same name would be overwritten by the key and the
            # link back to the order would vanish silently.
            "orderIdRef": order_id,
            "reservedAt": now,
        }
        if extra:
            item.update(extra)
        if _claim_row(table, key_attr, ORDER_NUMBER_PREFIX + candidate, item):
            return candidate
        logger.warning(
            "public order number collision on attempt %d/%d; regenerating",
            attempt, attempts,
        )

    raise OrderIdentityUnavailable(
        "exhausted %d attempts reserving a public order number" % attempts
    )


def claim_order_for_payment(table: Any,
                            *,
                            payment_attempt_id: str,
                            order_id: str,
                            provider_transaction_id: str = "",
                            key_attr: str = "orderId",
                            extra: Optional[Dict[str, Any]] = None
                            ) -> Tuple[str, bool]:
    """Claim the right to create exactly one order for one paid payment. Idempotent.

    Returns `(orderId, won)`. `won` is False when an order already exists, and the returned
    `orderId` is then the existing one - which is what makes a redelivered `payment.captured`,
    a concurrent reconciliation and a staff-triggered retry all converge on one order.

    Two markers, claimed in this order and for different reasons:

      `PROVIDERPAYMENT#<txn>`   one Razorpay payment may fund at most one order. Claimed
                                first, because it is the constraint an attacker or a provider
                                retry would attack.
      `PAYMENTATTEMPT#<id>`     one attempt yields at most one order. The anchor every
                                downstream step re-reads.

    Losing either claim returns the winner's `orderId` rather than raising, because two workers
    reconciling the same payment is expected, not exceptional.
    """
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    if not order_id:
        raise ValueError("order_id is required")

    now = int(time.time())
    base = {"orderIdRef": order_id, "claimedAt": now,
            "paymentAttemptId": payment_attempt_id,
            "providerTransactionId": provider_transaction_id}
    if extra:
        base.update(extra)

    if provider_transaction_id:
        item = dict(base, kind="PROVIDER_PAYMENT_CLAIM",
                    providerTransactionId=provider_transaction_id)
        if not _claim_row(table, key_attr,
                          PROVIDER_PAYMENT_PREFIX + provider_transaction_id, item):
            existing = _read_row(
                table, key_attr, PROVIDER_PAYMENT_PREFIX + provider_transaction_id
            ) or {}
            winner = existing.get("orderIdRef") or ""
            if not winner:
                raise OrderIdentityUnavailable(
                    "provider payment %r is claimed but names no order"
                    % provider_transaction_id
                )
            if existing.get("paymentAttemptId") != payment_attempt_id:
                return winner, False
            # Recover a crash between provider and attempt claims using the
            # committed identity. Never mint a second order for that payment.
            order_id = winner
            base["orderIdRef"] = winner

    item = dict(base, kind="PAYMENT_ATTEMPT_ORDER")
    if _claim_row(table, key_attr,
                  PAYMENT_ATTEMPT_PREFIX + payment_attempt_id, item):
        return order_id, True

    existing = _read_row(
        table, key_attr, PAYMENT_ATTEMPT_PREFIX + payment_attempt_id
    ) or {}
    winner = existing.get("orderIdRef") or ""
    if not winner:
        raise OrderIdentityUnavailable(
            "payment attempt %r is claimed but names no order" % payment_attempt_id
        )
    return winner, False


def record_order_number_on_claim(table: Any,
                                 *,
                                 payment_attempt_id: str,
                                 order_number: str,
                                 key_attr: str = "orderId") -> str:
    """Write the reserved order number onto the attempt's claim row.

    Separate from `claim_order_for_payment` because the number does not exist yet at claim
    time, and that sequence is deliberate: the claim decides who may create the order, and only
    the winner then reserves a number, so a loser never burns one.

    The gap between the two is what makes re-entry necessary rather than optional - a crash in
    between leaves a claim with no number, and `resolve_order_for_payment` reports exactly that
    so the caller reserves one and calls this again.
    """
    if not is_public_order_number(order_number):
        raise ValueError("order_number is not a valid 12-character public order number")
    try:
        table.update_item(
            Key={key_attr: PAYMENT_ATTEMPT_PREFIX + payment_attempt_id},
            UpdateExpression="SET orderNumber = :n, numberedAt = :t",
            ConditionExpression="attribute_exists(%s) AND attribute_not_exists(orderNumber)" % key_attr,
            ExpressionAttributeValues={":n": order_number, ":t": int(time.time())},
        )
        return order_number
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            existing = resolve_order_for_payment(table, payment_attempt_id, key_attr=key_attr) or {}
            canonical = existing.get("orderNumber")
            if is_public_order_number(canonical):
                return canonical
        raise OrderIdentityUnavailable(
            "could not record the order number for attempt %r: %s"
            % (payment_attempt_id, type(error).__name__)
        ) from error


def resolve_order_for_provider_payment(table: Any, provider_transaction_id: str, *,
                                       key_attr: str = "orderId"
                                       ) -> Optional[Dict[str, Any]]:
    """The order claim for a provider transaction, or None.

    Needed because a caller that loses the `PROVIDERPAYMENT#` claim holds the *wrong* attempt id
    to look up: the order belongs to whichever attempt won, not to the one asking. Without this,
    that caller sees "the provider claim is taken, but there is no order for my attempt" and
    reasonably concludes it should finish the job — reserving a **second** public order number
    for an order that already has one.

    Found by the test asserting that one provider payment cannot fund two orders across two
    attempts, which is exactly the case this resolves.
    """
    if not provider_transaction_id:
        return None
    claim = _read_row(
        table, key_attr, PROVIDER_PAYMENT_PREFIX + provider_transaction_id)
    if not claim:
        return None
    winner_attempt = str(claim.get("paymentAttemptId") or "")
    if not winner_attempt:
        return claim
    # The attempt row is the one carrying `orderNumber`; the provider row only names the order.
    return _read_row(
        table, key_attr, PAYMENT_ATTEMPT_PREFIX + winner_attempt) or claim


def resolve_order_for_payment(table: Any, payment_attempt_id: str, *,
                              key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The order claim for a payment attempt, or None when no order exists yet.

    None is the expected answer for every attempt that is pending, failed, cancelled or
    expired. It is not an error, and it must never be turned into one - "this attempt has no
    order" is the normal state for most attempts.
    """
    if not payment_attempt_id:
        return None
    return _read_row(table, key_attr, PAYMENT_ATTEMPT_PREFIX + payment_attempt_id)


def commerce_keys_table_name() -> str:
    """The provisioned table holding these rows. TTL must stay disabled on it.

    Indirected through an env var so the rows can move to a dedicated table without a code
    change. It currently defaults to the order-id mapping table, which was chosen because it is
    already provisioned, is keyed on a single string partition (`orderId`, measured - note the
    Amplify model in `amplify/data/resource.ts` declares `wixOrderId`, which the physical table
    does not use), has TTL disabled, and held zero items.
    """
    return os.environ.get(
        "COMMERCE_KEYS_TABLE",
        os.environ.get("WIX_ORDER_IDS_TABLE", "stack-wecare-digital-WixOrderIds"),
    )


#: Superseded name, kept for the Wix sync path.
order_ids_table_name = commerce_keys_table_name


# ── legacy: WD order numbers for orders synced from Wix ─────────────────────────

def reserve_order_number(table: Any,
                         order_date: str = "",
                         *,
                         key_attr: str = "orderId",
                         generate: Optional[Callable[[str], str]] = None,
                         attempts: int = _DEFAULT_ATTEMPTS,
                         extra: Optional[Dict[str, Any]] = None) -> str:
    """Reserve a legacy WD-ORD number for an order that already exists in Wix.

    This is NOT the checkout path. It serves `wix-store`'s sync and backfill, which assign a
    display number to orders Wix already holds and has already collected payment for - so no
    order is being created here and the order-after-payment rule is not in play.

    New orders created by our own checkout get `reserve_public_order_number` instead.
    """
    if generate is None:
        from lambda_utils.ecommerce.wix_domain import _generate_wd_order_number
        generate = _generate_wd_order_number

    now = int(time.time())
    for attempt in range(1, max(1, attempts) + 1):
        candidate = generate(order_date)
        item = {
            "kind": "ORDER_NUMBER_RESERVATION",
            "orderNumber": candidate,
            "reservedAt": now,
        }
        if extra:
            item.update(extra)
        if _claim_row(table, key_attr, ORDER_NUMBER_PREFIX + candidate, item):
            return candidate
        logger.warning(
            "order number collision on attempt %d/%d; regenerating", attempt, attempts
        )

    raise OrderIdentityUnavailable(
        "exhausted %d attempts reserving an order number" % attempts
    )


# ── durable capture quarantine: a recoverable intake row, not an alert ──────────
#: A capture the webhook could not authoritatively clear. Parked as a DURABLE row so it
#: survives after Razorpay stops retrying - an alert log does not. One row per payment id,
#: so a redelivery of the same unverified capture updates the same intake rather than piling
#: up duplicates. Writes NOTHING financial: it only records that a human must look.
QUARANTINE_PREFIX = "CAPTUREQUARANTINE#"

#: A stored wallet top-up intent. The customer-service top-up flow reserves one of these BEFORE
#: the payment link is created, so a `payment.captured` for a wallet top-up can be bound to a
#: customer/amount the business actually asked for - rather than trusting the event notes.
TOPUP_INTENT_PREFIX = "TOPUPINTENT#"

#: The idempotency marker that makes one captured payment credit a wallet exactly once. Claimed
#: conditionally before `partner_billing.topup`, so a duplicate webhook delivery loses the claim
#: and credits nothing.
TOPUP_CREDIT_PREFIX = "TOPUPCREDIT#"


def record_capture_quarantine(table: Any,
                              *,
                              payment_id: str,
                              reference_id: str = "",
                              outcome: str = "",
                              key_attr: str = "orderId",
                              extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Durably park an unverified capture for a human. Returns the stored/known row.

    Idempotent and recoverable, which is the whole reason it exists. The money may or may not
    have moved and the webhook could not tell, so this records the fact rather than guessing.
    Keyed by payment id, because that is the one identifier a capture always carries and the one
    a human reconciling it will search by. A redelivery of the same unverified capture finds the
    row already present and leaves it untouched (its `acknowledged` state and `createdAt` are
    preserved), so acknowledging an event does not make it reappear and re-alert.

    Writes NOTHING financial: no invoice is marked paid, no wallet is credited, no order is
    created. On a storage error it raises `OrderIdentityUnavailable` - the caller must not treat
    a failed park as a successful one, because that would silently drop the only recovery record.
    """
    if not payment_id:
        raise ValueError("payment_id is required to quarantine a capture")
    now = int(time.time())
    item = {
        "kind": "CAPTURE_QUARANTINE",
        "paymentId": payment_id,
        "referenceId": reference_id or "",
        "outcome": outcome or "",
        "status": "UNRESOLVED",
        "acknowledged": False,
        "createdAt": now,
    }
    if extra:
        item.update(extra)
    key = QUARANTINE_PREFIX + payment_id
    if _claim_row(table, key_attr, key, item):
        return item
    # Already parked by an earlier delivery. Return the existing row so the caller can see it is
    # recoverable; never overwrite it, so an acknowledgement is not undone by a retry.
    existing = _read_row(table, key_attr, key)
    return existing or item


def resolve_capture_quarantine(table: Any, payment_id: str, *,
                               key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The quarantine intake row for a payment id, or None. Raises only on a storage error."""
    if not payment_id:
        return None
    return _read_row(table, key_attr, QUARANTINE_PREFIX + payment_id)


def acknowledge_capture_quarantine(table: Any,
                                   *,
                                   payment_id: str,
                                   actor: str = "staff",
                                   key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """Mark a parked capture acknowledged WITHOUT deleting it, so it stays recoverable.

    Acknowledgement records that a human has seen the intake; it does not resolve or discharge
    it. The row is retained (never TTL'd, never deleted) precisely so that an acknowledged event
    remains recoverable after Razorpay has stopped retrying - the alert log it replaced could not
    offer that. Returns the updated row, or None if there is nothing parked under this id.
    """
    if not payment_id:
        return None
    key = QUARANTINE_PREFIX + payment_id
    try:
        table.update_item(
            Key={key_attr: key},
            UpdateExpression="SET acknowledged = :a, acknowledgedBy = :who, acknowledgedAt = :t",
            ConditionExpression="attribute_exists(%s)" % key_attr,
            ExpressionAttributeValues={":a": True, ":who": actor or "staff",
                                       ":t": int(time.time())},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return None
        raise OrderIdentityUnavailable(
            "could not acknowledge quarantine %r: %s" % (payment_id, type(error).__name__)
        ) from error
    return resolve_capture_quarantine(table, payment_id, key_attr=key_attr)


def claim_legacy_invoice_payment(table: Any,
                                 *,
                                 payment_id: str,
                                 invoice_id: str,
                                 reference_id: str = "",
                                 key_attr: str = "orderId",
                                 extra: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Claim the right to settle exactly one legacy invoice for one Razorpay payment. Idempotent.

    Returns `(won, invoiceIdRef)`. `won` is True only when THIS call wrote the claim. When the
    marker already exists, `won` is False and `invoiceIdRef` is the invoice the claim is already
    bound to - which is what defeats a replay: a second signature-valid `payment.captured`
    carrying the SAME `payment_id` under a DIFFERENT referenceId finds the claim already held for
    the first invoice and settles nothing.

    Shares the `PROVIDERPAYMENT#<payment_id>` namespace with `claim_order_for_payment`, so a single
    provider payment can fund at most one thing across BOTH the commerce and the legacy paths: if
    the commerce reconciler already claimed this payment for an order, the legacy claim loses, and
    vice-versa. The marker is claimed BEFORE any invoice write, so one payment settles one invoice.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    if not invoice_id:
        raise ValueError("invoice_id is required")
    now = int(time.time())
    item = {
        "kind": "LEGACY_INVOICE_PAYMENT_CLAIM",
        "invoiceIdRef": invoice_id,
        "providerTransactionId": payment_id,
        "referenceId": reference_id or "",
        "claimedAt": now,
    }
    if extra:
        item.update(extra)
    key = PROVIDER_PAYMENT_PREFIX + payment_id
    if _claim_row(table, key_attr, key, item):
        return True, invoice_id
    existing = _read_row(table, key_attr, key) or {}
    return False, str(existing.get("invoiceIdRef") or "")


def release_legacy_invoice_payment_claim(table: Any,
                                         *,
                                         payment_id: str,
                                         invoice_id: str,
                                         key_attr: str = "orderId") -> bool:
    """Release a legacy one-time payment claim that settled NO invoice row. Returns True if deleted.

    The companion to `claim_legacy_invoice_payment`. The legacy settle on the Razorpay webhook is a
    second, independent query against the referenceId GSI run AFTER this claim is taken, so a settle
    that then no-ops (the row vanished, a duplicate made it ambiguous, or the write errored) would
    otherwise strand the payment: the irreversible claim is held with no paid row behind it, and no
    redelivery can ever settle. The caller detects "nothing settled" and calls this to release the
    claim so a legitimate redelivery can re-claim and re-attempt.

    Money-safety rests on the DELETE being CONDITIONAL, never unconditional:

      * `kind = LEGACY_INVOICE_PAYMENT_CLAIM`  - never remove a commerce `PROVIDER_PAYMENT_CLAIM`
        that happens to share the `PROVIDERPAYMENT#<payment_id>` namespace. A commerce order claim
        must stay irrevocable.
      * `invoiceIdRef = <invoice_id>`          - only release the claim THIS legacy settlement took,
        not one another worker has since re-bound to a different invoice.
      * `providerTransactionId = <payment_id>` - belt and braces that the row is for this payment.

    If the row no longer matches (already released, re-bound, or a commerce claim), the conditional
    delete loses and this returns False - a no-op, which is correct: there is nothing of ours to
    release. A conditional-check failure is the only tolerated error; anything else raises
    `OrderIdentityUnavailable` so a throttle is never mistaken for "released".

    The caller invokes this ONLY after confirming no invoice row was settled for this payment, so at
    release time no invoice is paid anywhere for it: releasing the claim cannot enable a double
    settle, it only lets the one legitimate settlement happen on a later delivery.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    if not invoice_id:
        raise ValueError("invoice_id is required")
    key = PROVIDER_PAYMENT_PREFIX + payment_id
    try:
        table.delete_item(
            Key={key_attr: key},
            ConditionExpression=(
                "#k = :kind AND invoiceIdRef = :inv AND providerTransactionId = :pid"
            ),
            ExpressionAttributeNames={"#k": "kind"},
            ExpressionAttributeValues={
                ":kind": "LEGACY_INVOICE_PAYMENT_CLAIM",
                ":inv": invoice_id,
                ":pid": payment_id,
            },
        )
        return True
    except Exception as error:  # noqa: BLE001 - re-raised below unless it is a lost condition
        if _is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not release %r: %s" % (key, type(error).__name__)
        ) from error


def reserve_topup_intent(table: Any,
                         *,
                         reference_id: str,
                         waba_id: str,
                         amount_paise: int,
                         currency: str = "INR",
                         key_attr: str = "orderId",
                         extra: Optional[Dict[str, Any]] = None) -> bool:
    """Record a wallet top-up the business actually asked for. True if reserved, False if bound.

    Written at top-up-initiation time, before the payment link exists, so the later
    `payment.captured` has a stored customer (`waba_id`) and amount to bind the credit to. The
    webhook never invents these from the event notes - absence of this row means the capture is
    not an authorised top-up and must not credit anything.
    """
    if not reference_id:
        raise ValueError("reference_id is required")
    if not waba_id:
        raise ValueError("waba_id is required")
    from lambda_utils.ecommerce.money import positive_paise
    amount_paise = positive_paise(amount_paise)
    item = {
        "kind": "TOPUP_INTENT",
        "referenceId": reference_id,
        "wabaId": waba_id,
        "amountPaise": amount_paise,
        "currency": currency or "INR",
        "reservedAt": int(time.time()),
    }
    if extra:
        item.update(extra)
    return _claim_row(table, key_attr, TOPUP_INTENT_PREFIX + reference_id, item)


def resolve_topup_intent(table: Any, reference_id: str, *,
                         key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The stored top-up intent for a reference, or None when no top-up was authorised."""
    if not reference_id:
        return None
    return _read_row(table, key_attr, TOPUP_INTENT_PREFIX + reference_id)


def claim_topup_credit(table: Any,
                       *,
                       payment_id: str,
                       reference_id: str = "",
                       waba_id: str = "",
                       amount_paise: int = 0,
                       key_attr: str = "orderId") -> bool:
    """Claim the right to credit a wallet for one captured payment. Idempotent.

    True on the first delivery (the caller may credit), False on every redelivery (already
    credited). Keyed by payment id, so one Razorpay capture credits a wallet exactly once no
    matter how many times the webhook is delivered. The claim is written BEFORE the credit, so
    even a crash between claim and credit cannot double-credit - a redelivery sees the claim and
    stops.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    item = {
        "kind": "TOPUP_CREDIT",
        "paymentId": payment_id,
        "referenceId": reference_id or "",
        "wabaId": waba_id or "",
        "amountPaise": int(amount_paise or 0),
        "creditedAt": int(time.time()),
    }
    return _claim_row(table, key_attr, TOPUP_CREDIT_PREFIX + payment_id, item)


# ── website Standard Checkout: request key + gateway-order binding (section 8) ──
#: A customer-scoped, intent-fingerprinted request key reserved BEFORE the external order-create
#: call. Two rapid clicks on "Pay" with the SAME intent must coordinate onto ONE gateway order,
#: and a changed intent (different amount, cart revision or snapshot hash) under a resumed key
#: must be refused rather than silently paying the old amount. The key names the attempt; the
#: fingerprint pins the intent, and the two are checked together.
REQUEST_KEY_PREFIX = "REQUESTKEY#"

#: The persisted binding of a created Razorpay gateway order to the attempt/account/mode/amount
#: it was created for. Written BEFORE checkout options are exposed to the browser, so a callback
#: can be checked against the stored order id/account/mode/amount rather than anything the browser
#: relayed. A Razorpay GATEWAY order is NOT an internal/Wix purchase order and carries no public
#: order number — that exists only after an authoritative capture. These are different objects.
GATEWAY_ORDER_PREFIX = "GATEWAYORDER#"


def reserve_checkout_request_key(table: Any,
                                 *,
                                 customer_id: str,
                                 request_key: str,
                                 intent_fingerprint: str,
                                 payment_attempt_id: str,
                                 key_attr: str = "orderId",
                                 extra: Optional[Dict[str, Any]] = None
                                 ) -> Tuple[Dict[str, Any], bool]:
    """Reserve a customer-scoped request key before any external order-create. Idempotent.

    Returns `(row, won)`:

      won is True   this click is the first with this key; the caller proceeds to create the
                    gateway order. The row records the intent fingerprint so a later resume can
                    be checked against it.
      won is False  this key already exists. The returned row is the EXISTING reservation. The
                    caller MUST compare `intentFingerprint` before resuming: the same intent
                    resumes onto the already-created order (concurrent clicks coordinate), and a
                    DIFFERENT intent must be rejected rather than charged.

    The key is namespaced by customer so one customer cannot reserve or resume another's request
    key. The fingerprint is the caller's hash over the frozen intent (amount, currency, cart
    revision, snapshot hash); this module stores and returns it but does not interpret it.
    """
    if not customer_id:
        raise ValueError("customer_id is required")
    if not request_key:
        raise ValueError("request_key is required")
    if not intent_fingerprint:
        raise ValueError("intent_fingerprint is required")
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    now = int(time.time())
    item = {
        "kind": "CHECKOUT_REQUEST_KEY",
        "customerId": customer_id,
        "requestKey": request_key,
        "intentFingerprint": intent_fingerprint,
        "paymentAttemptId": payment_attempt_id,
        "reservedAt": now,
    }
    if extra:
        item.update(extra)
    key = REQUEST_KEY_PREFIX + customer_id + "#" + request_key
    if _claim_row(table, key_attr, key, item):
        return item, True
    existing = _read_row(table, key_attr, key)
    if existing is None:
        # A lost race whose winner's row we then could not read is an outage, not a resume.
        raise OrderIdentityUnavailable(
            "request key %r is claimed but could not be read" % request_key)
    return existing, False


def bind_gateway_order(table: Any,
                       *,
                       gateway_order_id: str,
                       payment_attempt_id: str,
                       request_key: str,
                       amount_paise: int,
                       account_key_id: str,
                       account_mode: str,
                       currency: str = "INR",
                       key_attr: str = "orderId",
                       extra: Optional[Dict[str, Any]] = None) -> bool:
    """Durably persist a created gateway order's id/account/mode/amount BEFORE exposing options.

    True if this binding was written, False if the gateway order id was already bound (a resumed
    create landing on the same provider order). The binding is what a callback is verified
    against: the stored order id selects the HMAC input, and the stored account/mode/amount/currency
    are what a result must match. Writes NOTHING financial and mints NO public order number — a
    gateway order is only an intent to pay.
    """
    if not gateway_order_id:
        raise ValueError("gateway_order_id is required")
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    from lambda_utils.ecommerce.money import positive_paise
    amount_paise = positive_paise(amount_paise)
    item = {
        "kind": "GATEWAY_ORDER_BINDING",
        "gatewayOrderId": gateway_order_id,
        "paymentAttemptId": payment_attempt_id,
        "requestKey": request_key or "",
        "amountPaise": amount_paise,
        "currency": currency or "INR",
        "accountKeyId": account_key_id or "",
        "accountMode": account_mode or "",
        "boundAt": int(time.time()),
    }
    if extra:
        item.update(extra)
    return _claim_row(table, key_attr, GATEWAY_ORDER_PREFIX + gateway_order_id, item)


def resolve_checkout_request_key(table: Any, *, customer_id: str, request_key: str,
                                 key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The stored reservation for one customer's request key, or None.

    A reader for a row `reserve_checkout_request_key` already writes. `website_checkout`'s
    create-right claim needs to read back the reference that row carries, and reading it through
    `_read_row` is what makes a storage failure raise rather than answer "no reservation".
    """
    if not customer_id or not request_key:
        return None
    return _read_row(table, key_attr, REQUEST_KEY_PREFIX + customer_id + "#" + request_key)


def resolve_gateway_order(table: Any, gateway_order_id: str, *,
                          key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The stored binding for a gateway order id, or None.

    None means we never created this order — a callback naming an unknown gateway order id is
    either a forgery or a lost write, and either way must not settle anything.
    """
    if not gateway_order_id:
        return None
    return _read_row(table, key_attr, GATEWAY_ORDER_PREFIX + gateway_order_id)


# ── native WhatsApp collection: one live collection per invoice ────────────────

#: At most one live WhatsApp payment collection per invoice. Written as a `Put` entry INSIDE
#: `wa_payment_request.reserve`'s transaction, so a reservation and its collection claim cannot
#: disagree. Five independent callers can reach `invoice-engine.send_payment_link` (the operator
#: UI, the business-API route, a Flow completion, the inbound auto-send and the auto-send chain),
#: and without this one invoice can receive two payment requests, producing two references, two
#: captures and two orders.
#:
#: NOTE there is deliberately no `claim_invoice_collection` writer here. Per the design's H3
#: finding, `_claim_row` issues its own `put_item` and therefore cannot be a `TransactItems`
#: entry, so the claim is composed in `reserve` from this prefix. An unused second writer in this
#: module would be a future second writer, so only the prefix, the resolver and the release live
#: here.
INVOICE_COLLECT_PREFIX = "INVOICECOLLECT#"
INVOICE_COLLECT_KIND = "INVOICE_COLLECTION"

#: The collection SEQUENCE recorded on the invoice row, which is what makes a cancelled
#: collection re-raisable without ever deleting a uniqueness reservation.
#:
#: The problem it solves: the `REQUESTKEY#` anchor is keyed on the invoice and carries no TTL
#: (correctly - a uniqueness reservation that expires is an identifier that gets reissued). It
#: also fingerprints the amount, so an invoice edited after a collection was sent refuses with
#: `WA_PAY_INTENT_CHANGED`. With nothing carrying a sequence, "cancel and re-raise" is
#: unreachable: the old anchor survives the cancel, the new amount mismatches it, and the invoice
#: becomes permanently uncollectable over WhatsApp.
#:
#: So `cancel_invoice` records `collectionSeq = seq + 1` and the next collection composes
#: `INVPAY#<invoiceId>#<seq>` - a DIFFERENT request key. The old reservation stays immutable,
#: nothing is deleted, nothing is reissued, and the old `PAYREF#` row remains resolvable, which
#: matters: a customer who pays the message they already hold still settles against the
#: reservation that message named.
INVOICE_COLLECT_SEQ_ATTR = "collectionSeq"


def resolve_invoice_collection(table: Any, invoice_id: str, *,
                               key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The live collection claim for an invoice, or None.

    None means no collection is in flight. Read through `_read_row`, so a storage failure raises
    rather than answering "nothing is in flight" - which would let a second payment request go
    out for an invoice that already has one.
    """
    if not invoice_id:
        return None
    return _read_row(table, key_attr, INVOICE_COLLECT_PREFIX + invoice_id)


def release_invoice_collection(table: Any, *, invoice_id: str,
                               key_attr: str = "orderId") -> bool:
    """Release an invoice's collection claim. True when a claim was released.

    The ONE permitted delete in this key space, and it is permitted only because a cancelled
    invoice has no live collection: the row says "a payment request is outstanding", and once the
    invoice is cancelled that statement is false. Conditional on the row actually being a
    collection claim, so a key collision can never delete something else.

    This does NOT release the `REQUESTKEY#` anchor, and must not: that row is the identity
    reservation, and deleting one is how an identifier gets reissued. The sequence bump
    (`INVOICE_COLLECT_SEQ_ATTR`) is what makes the next collection reachable.
    """
    if not invoice_id:
        return False
    try:
        table.delete_item(
            Key={key_attr: INVOICE_COLLECT_PREFIX + invoice_id},
            ConditionExpression="attribute_exists(%s) AND kind = :kind" % key_attr,
            ExpressionAttributeValues={":kind": INVOICE_COLLECT_KIND},
        )
        return True
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not release the collection claim for %r: %s"
            % (invoice_id, type(error).__name__)
        ) from error


# ── one WhatsApp invoice delivery per invoice ───────────────────────────────────

#: One delivery of one invoice per channel. Claimed INSIDE `invoice-engine.send_invoice_whatsapp`
#: rather than at any call site, so the webhook, the operator button and any future caller all
#: pass through it - a claim written only by the webhook would leave the live operator route able
#: to send a second GST invoice for one payment, which is a compliance artifact rather than
#: merely untidy.
#:
#: Unlike the reservation rows in `wa_payment_request.reserve` this is a single row with a single
#: writer, so `_claim_row` is exactly the right primitive and no transaction is needed. No TTL.
INVOICE_DELIVERY_PREFIX = "INVOICEDELIVERY#"
INVOICE_DELIVERY_KIND = "INVOICE_DELIVERY"

#: The claim is taken BEFORE the render and the send, so it starts as an INTENT and is only
#: evidence of delivery once confirmed. That distinction is load-bearing: `send_invoice_whatsapp`
#: swallows a Meta failure into `wa_status='failed'` and returns 200, so a claim that was never
#: released on failure would consume the only slot and every non-forced caller thereafter would
#: get `already_delivered` - silently losing a GST invoice.
DELIVERY_CLAIMED = "CLAIMED"
DELIVERY_CONFIRMED = "DELIVERED"


def _invoice_delivery_key(invoice_id: str, channel: str) -> str:
    return INVOICE_DELIVERY_PREFIX + invoice_id + "#" + (channel or "whatsapp")


def claim_invoice_delivery(table: Any, *, invoice_id: str, channel: str = "whatsapp",
                           key_attr: str = "orderId",
                           extra: Optional[Dict[str, Any]] = None) -> bool:
    """True when this caller may deliver this invoice on this channel. False when one already did.

    `False` only on a lost race; a throttle raises `OrderIdentityUnavailable`, so the caller fails
    closed toward NOT sending rather than mistaking an outage for a delivery.
    """
    if not invoice_id:
        raise ValueError("invoice_id is required")
    item = {
        "kind": INVOICE_DELIVERY_KIND,
        "invoiceId": invoice_id,
        "channel": channel or "whatsapp",
        "deliveryStatus": DELIVERY_CLAIMED,
        "claimedAt": int(time.time()),
    }
    if extra:
        item.update(extra)
    return _claim_row(table, key_attr, _invoice_delivery_key(invoice_id, channel), item)


def confirm_invoice_delivery(table: Any, *, invoice_id: str, channel: str = "whatsapp",
                             wa_message_id: str = "",
                             key_attr: str = "orderId") -> None:
    """Advance a delivery claim from CLAIMED to DELIVERED. Never raises.

    The claim becomes evidence only here. Conditional on the row existing, so it cannot create
    one, and idempotent: a confirmed row re-confirmed is the same row.
    """
    if not invoice_id:
        return
    try:
        table.update_item(
            Key={key_attr: _invoice_delivery_key(invoice_id, channel)},
            UpdateExpression="SET deliveryStatus = :done, deliveredAt = if_not_exists("
                             "deliveredAt, :now), waMessageId = :mid",
            ConditionExpression="attribute_exists(%s)" % key_attr,
            ExpressionAttributeValues={":done": DELIVERY_CONFIRMED, ":now": int(time.time()),
                                       ":mid": wa_message_id or ""},
        )
    except Exception as error:  # noqa: BLE001
        # A confirmed delivery that failed to record is a reporting gap, never a money fault: the
        # document is already in the customer's hands. Logged by type, never raised.
        logger.info('{"event":"invoice_delivery_confirm_skipped","error":"%s"}',
                    type(error).__name__)


def release_invoice_delivery(table: Any, *, invoice_id: str, channel: str = "whatsapp",
                             key_attr: str = "orderId") -> bool:
    """Release a delivery claim that produced no delivery. True when released.

    Conditional on `deliveryStatus = CLAIMED`, so it can NEVER undo a confirmed delivery - which
    is what stops the release being usable to duplicate a GST invoice. Returns False (rather than
    raising) when the row is already DELIVERED or absent, because both mean "there is nothing
    here to take back".
    """
    if not invoice_id:
        return False
    try:
        table.delete_item(
            Key={key_attr: _invoice_delivery_key(invoice_id, channel)},
            ConditionExpression="attribute_exists(%s) AND deliveryStatus = :claimed" % key_attr,
            ExpressionAttributeValues={":claimed": DELIVERY_CLAIMED},
        )
        return True
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not release the delivery claim for %r: %s"
            % (invoice_id, type(error).__name__)
        ) from error


def resolve_invoice_delivery(table: Any, invoice_id: str, *, channel: str = "whatsapp",
                             key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The delivery claim row for an invoice/channel, or None."""
    if not invoice_id:
        return None
    return _read_row(table, key_attr, _invoice_delivery_key(invoice_id, channel))


# ── one live payable attempt per cart, and durable per-basket paid memory ───────

#: The customer's most recent PAYABLE attempt for one Cart V2 cart, so a create can resolve
#: before it generates a second gateway order for a basket that already has one.
#:
#: WHY A POINTER ROW AND NOT A QUERY. PaymentAttemptsTable is keyed on `paymentAttemptId` alone
#: and carries no index on the customer or the cart, so the only way to ask "does this cart
#: already have a live payment?" without a table scan is to write the question's answer down when
#: the payable attempt is reserved. Same discipline as `REQUESTKEY#`, `PAYREF#` and `ORDERNO#`:
#: resolve before generate, on a stored key.
#:
#: Namespaced by customer FIRST, so one customer can never resolve or block another's cart.
CART_PAYMENT_PREFIX = "CARTPAYMENT#"
CART_PAYMENT_KIND = "CART_PAYMENT_POINTER"

#: Per-BASKET paid memory. SEPARATE from CART_PAYMENT_PREFIX, and the separation is the fix.
#: `CARTPAYMENT#` is a single slot per cart and is deliberately upserted when a later attempt
#: opens on the same cart — which destroys the only record that an EARLIER basket was paid. A
#: cart has ONE live attempt and may have MANY paid baskets over its 30-day lifetime, so "which
#: attempt is live" and "has this basket been paid" are different cardinalities and cannot share
#: a row.
#:
#: Customer FIRST, then cart, then basket, so one customer can never resolve another's basket and
#: so the row is diagnosable by prefix for one cart when a human reconciles a refusal.
CART_BASKET_PREFIX = "CARTBASKET#"
CART_BASKET_KIND = "CART_BASKET_PAID_POINTER"

#: The NARROW per-basket paid row. The SAME question as CART_BASKET_PREFIX, keyed on the identity
#: we can PROVE is stable rather than the one we cannot. `checkout_pricing.basket_hash` is
#: subtractive and may carry a per-calculate field, so a lookup keyed on it can MISS for an
#: unedited basket — and the cart pointer's narrow veto cannot cover that, because the veto only
#: runs when the POINTER names a paid attempt, and the pointer is a single slot a later attempt
#: upserts. Two keys, two chances, and the narrow one cannot be polluted by a field Wix controls.
CART_NARROW_BASKET_PREFIX = "CARTNARROW#"
CART_NARROW_BASKET_KIND = "CART_NARROW_BASKET_PAID_POINTER"

#: How long a per-basket create claim is honoured before a later click may take it over. Mirrors
#: `website_checkout.CREATE_CLAIM_STALE_SECONDS`; a test pins the two equal. A claim that never
#: became an attempt means a create FAILED, which is a different fact from a capture still
#: settling, and 1200s of friction for a provider timeout is the wrong answer.
CART_CREATE_CLAIM_STALE_SECONDS = 120

#: Written by a claim, replaced by a record. Evidence, never a decision: the decision is taken on
#: the PRESENCE of `recordedAt`, so a stage value that drifts cannot change behaviour.
CART_CLAIM_STAGE_CREATED = "CREATE_CLAIMED"


def _cart_payment_key(customer_id: str, wix_cart_id: str) -> str:
    if not customer_id:
        raise ValueError("customer_id is required")
    if not wix_cart_id:
        raise ValueError("wix_cart_id is required")
    return CART_PAYMENT_PREFIX + customer_id + "#" + wix_cart_id


def _cart_basket_key(customer_id: str, wix_cart_id: str, basket_hash: str) -> str:
    """`CARTBASKET#<customer>#<cart>#<basketHash>`. ValueError on ANY empty part.

    Mirrors `_cart_payment_key`'s refusal rather than silently composing a key with an empty
    segment, because two different baskets must never collide onto one key.
    """
    if not customer_id:
        raise ValueError("customer_id is required")
    if not wix_cart_id:
        raise ValueError("wix_cart_id is required")
    if not basket_hash:
        raise ValueError("basket_hash is required")
    return CART_BASKET_PREFIX + customer_id + "#" + wix_cart_id + "#" + basket_hash


def _cart_narrow_basket_key(customer_id: str, wix_cart_id: str, narrow_hash: str) -> str:
    """`CARTNARROW#<customer>#<cart>#<narrowBasketHash>`. ValueError on ANY empty part."""
    if not customer_id:
        raise ValueError("customer_id is required")
    if not wix_cart_id:
        raise ValueError("wix_cart_id is required")
    if not narrow_hash:
        raise ValueError("narrow_hash is required")
    return CART_NARROW_BASKET_PREFIX + customer_id + "#" + wix_cart_id + "#" + narrow_hash


def resolve_cart_payment(table: Any, *, customer_id: str, wix_cart_id: str,
                         key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The last payable attempt recorded for this customer's cart, or None. Consistent read.

    A read failure raises `OrderIdentityUnavailable` rather than answering None, for the usual
    reason in this module and a sharper one here: the caller acts on absence by creating a NEW
    payable gateway order, so a throttle answering "no attempt" is how one basket acquires two.
    """
    return _read_row(table, key_attr, _cart_payment_key(customer_id, wix_cart_id))


def resolve_cart_basket(table: Any, *, customer_id: str, wix_cart_id: str, basket_hash: str,
                        key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The attempt recorded against THIS BASKET on this cart, or None. Consistent read.

    Absence is the dangerous answer, so a read failure raises rather than returning None.
    """
    return _read_row(table, key_attr,
                     _cart_basket_key(customer_id, wix_cart_id, basket_hash))


def resolve_cart_narrow_basket(table: Any, *, customer_id: str, wix_cart_id: str,
                               narrow_hash: str,
                               key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The same question as `resolve_cart_basket`, keyed on the narrow identity."""
    return _read_row(table, key_attr,
                     _cart_narrow_basket_key(customer_id, wix_cart_id, narrow_hash))


def _write_cart_row(table: Any, item: Dict[str, Any], what: str) -> Dict[str, Any]:
    """One unconditional upsert, raising `OrderIdentityUnavailable` on any failure.

    These writes are NOT best-effort. A silently lost row re-opens the exact double-order path
    the rows exist to close, so the caller refuses to expose checkout options instead.
    """
    try:
        table.put_item(Item=item)
    except Exception as error:  # noqa: BLE001
        raise OrderIdentityUnavailable(
            "could not record %s: %s" % (what, type(error).__name__)) from error
    return item


def record_cart_payment(table: Any,
                        *,
                        customer_id: str,
                        wix_cart_id: str,
                        payment_attempt_id: str,
                        request_key: str = "",
                        basket_hash: str = "",
                        narrow_basket_hash: str = "",
                        snapshot_hash: str = "",
                        now: Optional[int] = None,
                        key_attr: str = "orderId") -> Dict[str, Any]:
    """Point this cart at the payable attempt that was just reserved for it. Returns the row.

    An UPSERT, deliberately, where most rows in this module are one-shot claims: a cart may
    legitimately acquire a second payable attempt later (the first was abandoned, and nothing in
    the payment vocabulary ever moves an abandoned attempt to a terminal state), and the caller
    decides whether that is allowed BEFORE it gets here. The guard is the read, not this write.

    `basketHash` is what the paid arm DECIDES on, `narrowBasketHash` is what it may additionally
    VETO on, and `snapshotHash` is EVIDENCE ONLY — no decision reads it. Writing all three and
    deciding on two is deliberate: a human reading the row can tell "same basket, newer quote"
    from "same items, different tender" from "different basket" without inferring any of them.

    Neither the request key nor the cart id is a secret or a phone number.
    """
    payment_attempt_id = str(payment_attempt_id or "").strip()
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    moment = int(time.time()) if now is None else int(now)
    item: Dict[str, Any] = {
        key_attr: _cart_payment_key(customer_id, wix_cart_id),
        "kind": CART_PAYMENT_KIND,
        "customerId": customer_id,
        "wixCartId": wix_cart_id,
        "paymentAttemptId": payment_attempt_id,
        "requestKey": str(request_key or ""),
        "basketHash": str(basket_hash or ""),
        "narrowBasketHash": str(narrow_basket_hash or ""),
        "snapshotHash": str(snapshot_hash or ""),
        "recordedAt": moment,
    }
    return _write_cart_row(table, item, "the cart payment pointer")


def record_cart_basket(table: Any,
                       *,
                       customer_id: str,
                       wix_cart_id: str,
                       basket_hash: str,
                       payment_attempt_id: str,
                       request_key: str = "",
                       narrow_basket_hash: str = "",
                       snapshot_hash: str = "",
                       now: Optional[int] = None,
                       key_attr: str = "orderId") -> Dict[str, Any]:
    """Record that THIS BASKET has a payable attempt, keyed on the fine identity.

    An upsert like its sibling, and safe here for a reason the cart row cannot claim: the key
    CONTAINS the basket identity, so the only request that can rewrite the row is one presenting
    the same basket — and the guard refuses exactly that request when the named attempt is paid.
    The upsert therefore only ever re-points a basket whose previous attempt was NOT paid, which
    is the legitimate retry.

    Writes `recordedAt`, which is what promotes a `CREATE_CLAIMED` row to `RECORDED` and so moves
    it out of the create-staleness window and under the rule that a claim can never take it over.
    """
    payment_attempt_id = str(payment_attempt_id or "").strip()
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    moment = int(time.time()) if now is None else int(now)
    item: Dict[str, Any] = {
        key_attr: _cart_basket_key(customer_id, wix_cart_id, basket_hash),
        "kind": CART_BASKET_KIND,
        "customerId": customer_id,
        "wixCartId": wix_cart_id,
        "basketHash": basket_hash,
        "narrowBasketHash": str(narrow_basket_hash or ""),
        "snapshotHash": str(snapshot_hash or ""),
        "paymentAttemptId": payment_attempt_id,
        "requestKey": str(request_key or ""),
        "recordedAt": moment,
    }
    return _write_cart_row(table, item, "the paid basket pointer")


def record_cart_narrow_basket(table: Any,
                              *,
                              customer_id: str,
                              wix_cart_id: str,
                              narrow_hash: str,
                              payment_attempt_id: str,
                              request_key: str = "",
                              basket_hash: str = "",
                              snapshot_hash: str = "",
                              now: Optional[int] = None,
                              key_attr: str = "orderId") -> Dict[str, Any]:
    """The same fact as `record_cart_basket`, keyed on the identity we can prove is stable."""
    payment_attempt_id = str(payment_attempt_id or "").strip()
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    moment = int(time.time()) if now is None else int(now)
    item: Dict[str, Any] = {
        key_attr: _cart_narrow_basket_key(customer_id, wix_cart_id, narrow_hash),
        "kind": CART_NARROW_BASKET_KIND,
        "customerId": customer_id,
        "wixCartId": wix_cart_id,
        "narrowBasketHash": narrow_hash,
        "basketHash": str(basket_hash or ""),
        "snapshotHash": str(snapshot_hash or ""),
        "paymentAttemptId": payment_attempt_id,
        "requestKey": str(request_key or ""),
        "recordedAt": moment,
    }
    return _write_cart_row(table, item, "the narrow paid basket pointer")


def _claim_basket_slot(table: Any, key_attr: str, key: str, kind: str, *,
                       customer_id: str, wix_cart_id: str, payment_attempt_id: str,
                       prior_payment_attempt_id: str, request_key: str,
                       now: Optional[int]) -> bool:
    """Take the per-basket create slot BEFORE the provider create. True if won.

    ONE conditional `put_item`, which REPLACES the item. Never an `update_item`: under an update
    a stale `recordedAt` would SURVIVE and the row would keep the settling horizon, when what a
    retaken claim means is that a create is in progress — a different fact with a different
    window. Replacing is what demotes a retried RECORDED row to `CREATE_CLAIMED` and moves it
    onto the create horizon.

    `prior_payment_attempt_id` is a COMPARE-AND-SWAP basis supplied by the caller — the attempt
    id its own guard read off this row — and not re-read here. What the condition guarantees,
    stated as what it does: the claim FAILS when ANOTHER request re-pointed this row between the
    guard's read and now, which is the case that would otherwise let two prepares both believe
    they hold the basket. It does NOT detect a capture landing on the SAME attempt in that gap:
    the row is unchanged, so the condition holds. That window is bounded by the guard having
    already passed an in-flight attempt, and the attempt STATE is deliberately re-read nowhere
    here — whether an attempt is paid belongs to `payment_attempt`'s vocabulary, and splitting
    that decision across two modules is how it drifts.

    The staleness escape covers a claimer that died before writing its attempt. It is keyed on
    `claimedAt` and guarded by `attribute_not_exists(recordedAt)`, so a RECORDED row — one whose
    attempt really exists — can NEVER be taken over by a claim, however old it is.

    Raises `OrderIdentityUnavailable` on any failure that is not a lost condition: a throttle
    must never be mistaken for "the slot is free", because the caller acts on True by creating a
    payable order.
    """
    payment_attempt_id = str(payment_attempt_id or "").strip()
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    moment = int(time.time()) if now is None else int(now)
    item = {
        key_attr: key,
        "kind": kind,
        "customerId": customer_id,
        "wixCartId": wix_cart_id,
        "paymentAttemptId": payment_attempt_id,
        # Carried so the guard's same-request-key resume exemption can recognise the claimer's
        # OWN later click. Without it a retry on the same key reads its own claim as a foreign
        # in-flight attempt and is refused for the whole settling window -- which would make the
        # resume exit unreachable and the payable-modal choke point inert on that path. It
        # changes no horizon: the discrimination is the ABSENCE of `recordedAt`, not this field.
        "requestKey": str(request_key or ""),
        "claimStage": CART_CLAIM_STAGE_CREATED,
        "claimedAt": moment,
    }
    prior = str(prior_payment_attempt_id or "")
    if prior:
        condition = "paymentAttemptId = :prior"
        values = {":prior": prior}
    else:
        condition = ("attribute_not_exists(%s) OR "
                     "(attribute_not_exists(recordedAt) AND claimedAt < :stale)" % key_attr)
        values = {":stale": moment - CART_CREATE_CLAIM_STALE_SECONDS}
    try:
        table.put_item(Item=item, ConditionExpression=condition,
                       ExpressionAttributeValues=values)
        return True
    except Exception as error:  # noqa: BLE001 - classified, never swallowed
        if is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not claim the basket slot %r: %s" % (key, type(error).__name__)) from error


def claim_cart_basket(table: Any, *, customer_id: str, wix_cart_id: str, basket_hash: str,
                      payment_attempt_id: str, prior_payment_attempt_id: str = "",
                      request_key: str = "", now: Optional[int] = None,
                      key_attr: str = "orderId") -> bool:
    """Take the fine per-basket create slot. True if won. See `_claim_basket_slot`."""
    return _claim_basket_slot(
        table, key_attr, _cart_basket_key(customer_id, wix_cart_id, basket_hash),
        CART_BASKET_KIND, customer_id=customer_id, wix_cart_id=wix_cart_id,
        payment_attempt_id=payment_attempt_id,
        prior_payment_attempt_id=prior_payment_attempt_id, request_key=request_key, now=now)


def claim_cart_narrow_basket(table: Any, *, customer_id: str, wix_cart_id: str,
                             narrow_hash: str, payment_attempt_id: str,
                             prior_payment_attempt_id: str = "", request_key: str = "",
                             now: Optional[int] = None, key_attr: str = "orderId") -> bool:
    """The same claim on the NARROW slot. Both delegate to one private `_claim_basket_slot`."""
    return _claim_basket_slot(
        table, key_attr, _cart_narrow_basket_key(customer_id, wix_cart_id, narrow_hash),
        CART_NARROW_BASKET_KIND, customer_id=customer_id, wix_cart_id=wix_cart_id,
        payment_attempt_id=payment_attempt_id,
        prior_payment_attempt_id=prior_payment_attempt_id, request_key=request_key, now=now)


# ── Section 5 blog contributions (BLOG_CONTRIBUTION) ────────────────────────────
#: The authoritative record of ONE voluntary blog contribution. Written at initiation time (before
#: the gateway order is created, so a later `payment.captured` has a stored amount/post to bind
#: the credit to) and advanced to a settled state only after an authoritative capture readback.
#: It is NOT an order and mints NO public order number: a contribution never becomes a Wix Store
#: product or purchase order. It carries ONLY the authoritative fields Section 5 requires -
#: opaque ids, the blog post id/slug, integer paise, currency, the attempt/gateway/payment ids,
#: the verified/captured state, timestamps and a refund-state slot. No customer PII.
CONTRIBUTION_PREFIX = "BLOGCONTRIB#"

#: The idempotency marker that makes one captured contribution settle a contribution exactly once.
#: Claimed conditionally (keyed by payment id) BEFORE any settle write, so a duplicate webhook
#: delivery loses the claim and settles nothing - the same shape as `TOPUP_CREDIT_PREFIX`.
CONTRIBUTION_SETTLE_PREFIX = "BLOGCONTRIBSETTLE#"


def reserve_contribution(table: Any,
                         *,
                         contribution_id: str,
                         post_id: str,
                         slug: str,
                         amount_paise: int,
                         payment_attempt_id: str,
                         currency: str = "INR",
                         key_attr: str = "orderId",
                         extra: Optional[Dict[str, Any]] = None) -> bool:
    """Record a voluntary blog contribution the server authorised. True if reserved, False if bound.

    Written at initiation time, before the gateway order exists, so the later `payment.captured`
    has a stored amount to re-derive the settlement from - the event notes are never the authority
    for how much. The server has already validated `amount_paise` against its own authoritative
    presets/bounds; this only persists it. Stores ONLY the required authoritative fields and no
    customer PII. Mints no order number: a contribution is not an order.
    """
    if not contribution_id:
        raise ValueError("contribution_id is required")
    if not post_id:
        raise ValueError("post_id is required")
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    from lambda_utils.ecommerce.money import positive_paise
    amount_paise = positive_paise(amount_paise)
    now = int(time.time())
    item = {
        "kind": "BLOG_CONTRIBUTION",
        "contributionId": contribution_id,
        "postId": post_id,
        "slug": slug or "",
        "amountPaise": amount_paise,
        "currency": currency or "INR",
        "paymentAttemptId": payment_attempt_id,
        "gatewayOrderId": "",
        "providerPaymentId": "",
        "state": "INITIATED",
        "refundState": "NONE",
        "createdAt": now,
        "updatedAt": now,
    }
    if extra:
        item.update(extra)
    return _claim_row(table, key_attr, CONTRIBUTION_PREFIX + contribution_id, item)


def resolve_contribution(table: Any, contribution_id: str, *,
                         key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The stored contribution record for a contribution id, or None.

    None means no contribution was authorised under this id - a capture naming an unknown
    contribution is either a forgery or a lost write and must not settle anything.
    """
    if not contribution_id:
        return None
    return _read_row(table, key_attr, CONTRIBUTION_PREFIX + contribution_id)


def bind_contribution_gateway_order(table: Any,
                                    *,
                                    contribution_id: str,
                                    gateway_order_id: str,
                                    key_attr: str = "orderId") -> None:
    """Record the created gateway order id on the contribution record. Best-effort link.

    The authoritative verify/settle paths resolve the binding via `resolve_gateway_order` and the
    contribution via `resolve_contribution`; this only cross-links the two for reconciliation and
    never raises into the caller (a missing link falls back to the receipt/binding correlation).
    """
    if not contribution_id or not gateway_order_id:
        return
    try:
        table.update_item(
            Key={key_attr: CONTRIBUTION_PREFIX + contribution_id},
            UpdateExpression="SET gatewayOrderId = :g, updatedAt = :t",
            ConditionExpression="attribute_exists(%s)" % key_attr,
            ExpressionAttributeValues={":g": gateway_order_id, ":t": int(time.time())},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"blog_contribution_gateway_link_skipped","error":"%s"}',
                    type(error).__name__)


def claim_contribution_settlement(table: Any,
                                  *,
                                  payment_id: str,
                                  contribution_id: str = "",
                                  gateway_order_id: str = "",
                                  amount_paise: int = 0,
                                  key_attr: str = "orderId") -> bool:
    """Claim the right to settle a contribution for one captured payment. Idempotent.

    True on the first delivery (the caller may settle), False on every redelivery (already
    settled). Keyed by payment id, so one Razorpay capture settles a contribution exactly once no
    matter how many times the webhook is delivered. The claim is written BEFORE the settle, so
    even a crash between claim and settle cannot double-settle - a redelivery sees the claim and
    stops. Shares nothing with the commerce `PROVIDERPAYMENT#` namespace deliberately: a
    contribution is a distinct purpose and must not collide with an order claim.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    item = {
        "kind": "BLOG_CONTRIBUTION_SETTLE",
        "paymentId": payment_id,
        "contributionId": contribution_id or "",
        "gatewayOrderId": gateway_order_id or "",
        "amountPaise": int(amount_paise or 0),
        "settledAt": int(time.time()),
    }
    return _claim_row(table, key_attr, CONTRIBUTION_SETTLE_PREFIX + payment_id, item)


def mark_contribution_settled(table: Any,
                              *,
                              contribution_id: str,
                              provider_payment_id: str,
                              amount_paise: int,
                              key_attr: str = "orderId") -> None:
    """Advance a contribution record to CAPTURED with the authoritative payment id and amount.

    Called only after the single-settlement claim has been won and an authoritative capture
    readback confirmed the amount against the stored record. Never raises into the webhook (a
    non-2xx makes Razorpay retry the whole event); a failed state write is logged by type and the
    settlement claim already guarantees exactly-once.
    """
    if not contribution_id or not provider_payment_id:
        return
    try:
        table.update_item(
            Key={key_attr: CONTRIBUTION_PREFIX + contribution_id},
            UpdateExpression=("SET #st = :captured, providerPaymentId = :p, "
                              "settledAmountPaise = :a, settledAt = :t, updatedAt = :t"),
            ConditionExpression="attribute_exists(%s)" % key_attr,
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={":captured": "CAPTURED", ":p": provider_payment_id,
                                       ":a": int(amount_paise), ":t": int(time.time())},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"blog_contribution_settle_mark_skipped","error":"%s"}',
                    type(error).__name__)


# ── Section 2 gift-card redemption (GIFTCARD#) ──────────────────────────────────
#: An ATOMIC reservation of a verified gift-card redemption against ONE checkout attempt. This is
#: the money-safety heart of the gift-card path: two rapid "Apply" clicks, or two concurrent
#: prepare calls, must NOT both subtract the same gift-card balance (a double-spend). The row is
#: keyed by (card fingerprint + attempt) and claimed CONDITIONALLY, so the loser of the race
#: reserves nothing. A second reservation of the SAME card against a DIFFERENT live attempt is
#: refused while the first is still held - a card funds at most one in-flight checkout at a time.
#:
#: It carries the authoritative integer-paise figures the server computed (the verified redemption
#: amount and the resulting Razorpay payable) so a callback/webhook can re-derive them from the
#: STORED row rather than from anything the browser relayed. It mints NO order number and marks
#: NOTHING paid: a reservation is an intent to redeem, not a redemption.
GIFTCARD_RESERVATION_PREFIX = "GIFTCARD#"

#: A one-time, payment-id-keyed claim that a reserved gift-card redemption has been COMMITTED
#: (the Razorpay leg settled, or a zero-remaining order verified). Claimed BEFORE the commit
#: write, so a duplicate webhook/callback delivery commits a redemption exactly once. Shares
#: nothing with the commerce PROVIDERPAYMENT# namespace: a redemption is a distinct purpose.
GIFTCARD_COMMIT_PREFIX = "GIFTCARDCOMMIT#"

#: A card-level EXCLUSIVE lock, keyed by the card fingerprint ALONE (not the attempt). It is the
#: cross-attempt guard that stops ONE card funding TWO different live checkouts at once: a card
#: holds at most one lock, so a second attempt that tries to redeem the same card while the first
#: is still live loses the conditional claim and is refused. Held for exactly as long as a live
#: reservation exists for that card; released when the reservation is released/refunded. A direct
#: conditional claim rather than a table scan, so the guard is a single O(1) write that is correct
#: under concurrency and never walks the whole namespace.
GIFTCARD_LOCK_PREFIX = "GIFTCARDLOCK#"


def _giftcard_reservation_key(card_fingerprint: str, payment_attempt_id: str) -> str:
    return GIFTCARD_RESERVATION_PREFIX + card_fingerprint + "#" + payment_attempt_id


def _giftcard_lock_key(card_fingerprint: str) -> str:
    return GIFTCARD_LOCK_PREFIX + card_fingerprint


def reserve_gift_card_redemption(table: Any,
                                 *,
                                 card_fingerprint: str,
                                 payment_attempt_id: str,
                                 authoritative_total_paise: int,
                                 redemption_paise: int,
                                 razorpay_payable_paise: int,
                                 currency: str = "INR",
                                 key_attr: str = "orderId",
                                 extra: Optional[Dict[str, Any]] = None
                                 ) -> Tuple[Dict[str, Any], bool]:
    """Atomically reserve a verified gift-card redemption for one attempt. Idempotent per attempt.

    Returns ``(row, won)``:

      won is True   this attempt is the first to reserve this card; the caller holds the
                    reservation and may proceed to compute/charge the reduced Razorpay payable.
      won is False  a reservation ALREADY exists for this (card, attempt). The returned row is the
                    EXISTING one, so a retried/concurrent click for the SAME attempt resumes onto
                    the same reserved figures rather than subtracting the balance twice.

    Two concurrent "Apply" clicks for one attempt race on the conditional write and exactly one
    wins; the loser reads back the winner's row. The cross-attempt rule is enforced HERE by an
    exclusive card-level lock (``GIFTCARDLOCK#``): the same card cannot hold two live reservations
    for two different attempts, because the second attempt loses the lock claim and gets
    ``(existing_lock_row, False)`` with ``state == "LOCKED_ELSEWHERE"`` so the caller refuses it.

    All three amounts are stored as validated non-negative integer paise. ``razorpay_payable_paise``
    MAY be zero (a fully gift-card-covered order); the reservation is still recorded so the
    zero-remaining settlement runs through the authoritative verification path, never auto-complete.
    """
    if not card_fingerprint:
        raise ValueError("card_fingerprint is required")
    if not payment_attempt_id:
        raise ValueError("payment_attempt_id is required")
    for name, v in (("authoritative_total_paise", authoritative_total_paise),
                    ("redemption_paise", redemption_paise),
                    ("razorpay_payable_paise", razorpay_payable_paise)):
        if isinstance(v, bool) or type(v) is not int or v < 0:
            raise ValueError("%s must be a non-negative integer paise" % name)
    if redemption_paise + razorpay_payable_paise != authoritative_total_paise:
        raise ValueError("redemption + payable must reconcile to the authoritative total")
    now = int(time.time())
    key = _giftcard_reservation_key(card_fingerprint, payment_attempt_id)

    # Resume path: this exact (card, attempt) already reserved -> return the existing row, not won,
    # so a retried/concurrent click for the SAME attempt resumes onto the same figures.
    existing_reservation = _read_row(table, key_attr, key)
    if existing_reservation is not None:
        return existing_reservation, False

    # Cross-attempt guard: claim the exclusive card-level lock BEFORE the per-attempt reservation.
    # A card holds at most one live lock; a different live attempt loses this conditional claim.
    lock_key = _giftcard_lock_key(card_fingerprint)
    lock_item = {
        "kind": "GIFT_CARD_LOCK",
        "cardFingerprint": card_fingerprint,
        "paymentAttemptId": payment_attempt_id,
        "lockedAt": now,
    }
    if not _claim_row(table, key_attr, lock_key, lock_item):
        held = _read_row(table, key_attr, lock_key) or {}
        if str(held.get("paymentAttemptId") or "") != payment_attempt_id:
            # The card is locked by a DIFFERENT live attempt. Refuse without reserving.
            held = dict(held)
            held["state"] = "LOCKED_ELSEWHERE"
            return held, False
        # The lock is already ours (a prior partial reserve for this attempt); proceed to reserve.

    item = {
        "kind": "GIFT_CARD_RESERVATION",
        "cardFingerprint": card_fingerprint,
        "paymentAttemptId": payment_attempt_id,
        "authoritativeTotalPaise": authoritative_total_paise,
        "redemptionPaise": redemption_paise,
        "razorpayPayablePaise": razorpay_payable_paise,
        "currency": currency or "INR",
        "state": "RESERVED",
        "reservedAt": now,
    }
    if extra:
        item.update(extra)
    if _claim_row(table, key_attr, key, item):
        return item, True
    existing = _read_row(table, key_attr, key)
    if existing is None:
        raise OrderIdentityUnavailable(
            "gift-card reservation %r is claimed but could not be read" % key)
    return existing, False


def resolve_gift_card_redemption(table: Any, *, card_fingerprint: str,
                                 payment_attempt_id: str,
                                 key_attr: str = "orderId") -> Optional[Dict[str, Any]]:
    """The reservation row for one (card, attempt), or None when none exists."""
    if not card_fingerprint or not payment_attempt_id:
        return None
    return _read_row(table, key_attr,
                     _giftcard_reservation_key(card_fingerprint, payment_attempt_id))


def gift_card_is_reserved_elsewhere(table: Any, *, card_fingerprint: str,
                                    payment_attempt_id: str,
                                    key_attr: str = "orderId") -> bool:
    """True if this card holds a LIVE exclusive lock for a DIFFERENT attempt.

    The guard that stops one card from funding two concurrent checkouts, read in O(1) from the
    card-level ``GIFTCARDLOCK#`` row rather than by scanning the reservation namespace. A lock held
    by THIS attempt (or no lock at all) is not "elsewhere". The lock is released when the
    reservation is released/refunded, so a card freed by a rollback is immediately redeemable
    again. Only a storage error raises; an absent lock is a clean "no other reservation".
    """
    if not card_fingerprint:
        return False
    held = _read_row(table, key_attr, _giftcard_lock_key(card_fingerprint))
    if not held:
        return False
    return str(held.get("paymentAttemptId") or "") != payment_attempt_id


def release_gift_card_redemption(table: Any, *, card_fingerprint: str,
                                 payment_attempt_id: str, reason: str = "RELEASED",
                                 key_attr: str = "orderId") -> bool:
    """Release a reservation so the balance is NOT stranded. Returns True if a live row was released.

    This is the ROLLBACK the gift-card path needs for: a shopper removing the card, a failed
    Razorpay payment after the reservation was taken, an expired/abandoned attempt, or a refund.
    The update is CONDITIONAL on the row still being RESERVED, so a committed redemption is never
    silently undone and a double release is a harmless no-op (returns False).
    """
    if not card_fingerprint or not payment_attempt_id:
        return False
    key = _giftcard_reservation_key(card_fingerprint, payment_attempt_id)
    try:
        table.update_item(
            Key={key_attr: key},
            UpdateExpression="SET #st = :released, releaseReason = :r, releasedAt = :t",
            ConditionExpression="attribute_exists(%s) AND #st = :reserved" % key_attr,
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={":released": "RELEASED", ":reserved": "RESERVED",
                                       ":r": reason or "RELEASED", ":t": int(time.time())},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return False
        raise OrderIdentityUnavailable(
            "could not release gift-card reservation %r: %s" % (key, type(error).__name__)
        ) from error
    # Free the exclusive card lock so the card is redeemable again, but only if THIS attempt still
    # holds it (a committed reservation keeps its lock). Best-effort: a stranded lock is cleared by
    # reconciliation, never a double-charge.
    _release_gift_card_lock(table, card_fingerprint, payment_attempt_id, key_attr=key_attr)
    return True


def _release_gift_card_lock(table: Any, card_fingerprint: str, payment_attempt_id: str,
                            *, key_attr: str = "orderId") -> None:
    """Delete the card-level lock if it belongs to this attempt. Never raises into the caller."""
    lock_key = _giftcard_lock_key(card_fingerprint)
    try:
        table.delete_item(
            Key={key_attr: lock_key},
            ConditionExpression="attribute_exists(%s) AND paymentAttemptId = :a" % key_attr,
            ExpressionAttributeValues={":a": payment_attempt_id},
        )
    except Exception as error:  # noqa: BLE001
        if _is_conditional_failure(error):
            return
        logger.info('{"event":"gift_card_lock_release_skipped","error":"%s"}',
                    type(error).__name__)


def claim_gift_card_commit(table: Any,
                           *,
                           payment_id: str,
                           card_fingerprint: str = "",
                           payment_attempt_id: str = "",
                           redemption_paise: int = 0,
                           key_attr: str = "orderId") -> bool:
    """Claim the right to COMMIT a reserved gift-card redemption for one captured payment. Idempotent.

    True on the first delivery (the caller may commit), False on every redelivery (already
    committed). Keyed by payment id, so one Razorpay capture commits a redemption exactly once no
    matter how many times the webhook/callback is delivered. For a ZERO-remaining order there is no
    Razorpay payment id, so the caller keys the commit on the attempt-derived marker instead; the
    guarantee is the same conditional-write exactly-once.
    """
    marker = payment_id or ("attempt:" + payment_attempt_id)
    if not marker or marker == "attempt:":
        raise ValueError("a payment_id or payment_attempt_id is required to commit")
    item = {
        "kind": "GIFT_CARD_COMMIT",
        "paymentId": payment_id or "",
        "cardFingerprint": card_fingerprint or "",
        "paymentAttemptId": payment_attempt_id or "",
        "redemptionPaise": int(redemption_paise or 0),
        "committedAt": int(time.time()),
    }
    return _claim_row(table, key_attr, GIFTCARD_COMMIT_PREFIX + marker, item)


def mark_gift_card_committed(table: Any, *, card_fingerprint: str,
                             payment_attempt_id: str, provider_payment_id: str = "",
                             key_attr: str = "orderId") -> None:
    """Advance a reservation row to COMMITTED after its single-commit claim is won. Never raises."""
    if not card_fingerprint or not payment_attempt_id:
        return
    key = _giftcard_reservation_key(card_fingerprint, payment_attempt_id)
    try:
        table.update_item(
            Key={key_attr: key},
            UpdateExpression=("SET #st = :committed, providerPaymentId = :p, committedAt = :t"),
            ConditionExpression="attribute_exists(%s) AND #st = :reserved" % key_attr,
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={":committed": "COMMITTED", ":reserved": "RESERVED",
                                       ":p": provider_payment_id or "", ":t": int(time.time())},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"gift_card_commit_mark_skipped","error":"%s"}',
                    type(error).__name__)


__all__ = [
    "META_REFERENCE_ID_MAX_LENGTH",
    "RAZORPAY_RECEIPT_MAX_LENGTH",
    "PUBLIC_ORDER_NUMBER_PREFIX",
    "PUBLIC_ORDER_NUMBER_ENTROPY",
    "PUBLIC_ORDER_NUMBER_LENGTH",
    "PUBLIC_ORDER_NUMBER_ALPHABET",
    "LEGACY_PUBLIC_ORDER_NUMBER_LENGTH",
    "PAYMENT_REFERENCE_PREFIX",
    "PAYMENT_ATTEMPT_PREFIX",
    "PROVIDER_PAYMENT_PREFIX",
    "ORDER_NUMBER_PREFIX",
    "LEGACY_REFERENCE_PREFIX",
    "REFERENCE_ID_PREFIX",
    "OrderIdentityUnavailable",
    "is_conditional_failure",
    "is_valid_meta_reference_id",
    "assert_valid_meta_reference_id",
    "is_public_order_number",
    "is_current_public_order_number",
    "is_wd_order_number",
    "new_payment_attempt_id",
    "new_order_id",
    "mint_payment_reference",
    "mint_reference_id",
    "mint_public_order_number",
    "reserve_payment_reference",
    "resolve_payment_reference",
    "allocate_payment_reference",
    "reserve_public_order_number",
    "claim_order_for_payment",
    "record_order_number_on_claim",
    "resolve_order_for_payment",
    "resolve_order_for_provider_payment",
    "reserve_order_number",
    "commerce_keys_table_name",
    "order_ids_table_name",
    "QUARANTINE_PREFIX",
    "TOPUP_INTENT_PREFIX",
    "TOPUP_CREDIT_PREFIX",
    "record_capture_quarantine",
    "resolve_capture_quarantine",
    "acknowledge_capture_quarantine",
    "reserve_topup_intent",
    "resolve_topup_intent",
    "claim_topup_credit",
    "REQUEST_KEY_PREFIX",
    "GATEWAY_ORDER_PREFIX",
    "INVOICE_COLLECT_PREFIX",
    "INVOICE_COLLECT_KIND",
    "INVOICE_COLLECT_SEQ_ATTR",
    "resolve_invoice_collection",
    "release_invoice_collection",
    "INVOICE_DELIVERY_PREFIX",
    "INVOICE_DELIVERY_KIND",
    "DELIVERY_CLAIMED",
    "DELIVERY_CONFIRMED",
    "claim_invoice_delivery",
    "confirm_invoice_delivery",
    "release_invoice_delivery",
    "resolve_invoice_delivery",
    "reserve_checkout_request_key",
    "resolve_checkout_request_key",
    "bind_gateway_order",
    "resolve_gateway_order",
    "CART_PAYMENT_PREFIX",
    "CART_PAYMENT_KIND",
    "CART_BASKET_PREFIX",
    "CART_BASKET_KIND",
    "CART_NARROW_BASKET_PREFIX",
    "CART_NARROW_BASKET_KIND",
    "CART_CREATE_CLAIM_STALE_SECONDS",
    "CART_CLAIM_STAGE_CREATED",
    "resolve_cart_payment",
    "record_cart_payment",
    "resolve_cart_basket",
    "record_cart_basket",
    "claim_cart_basket",
    "resolve_cart_narrow_basket",
    "record_cart_narrow_basket",
    "claim_cart_narrow_basket",
    "CONTRIBUTION_PREFIX",
    "CONTRIBUTION_SETTLE_PREFIX",
    "reserve_contribution",
    "resolve_contribution",
    "bind_contribution_gateway_order",
    "claim_contribution_settlement",
    "mark_contribution_settled",
    "GIFTCARD_RESERVATION_PREFIX",
    "GIFTCARD_COMMIT_PREFIX",
    "GIFTCARD_LOCK_PREFIX",
    "reserve_gift_card_redemption",
    "resolve_gift_card_redemption",
    "gift_card_is_reserved_elsewhere",
    "release_gift_card_redemption",
    "claim_gift_card_commit",
    "mark_gift_card_committed",
]
