"""Section 8 website Razorpay Standard Checkout: the order-create and callback-verify logic.

The two coexisting flows, and why this is additive
--------------------------------------------------
`ecommerce/checkout/handler.py` already implements an IN-WHATSAPP Meta/Razorpay flow that reserves
a reference, gates on Meta payment readiness and (when initiation is enabled) sends an in-chat
`order_details` message, returning `PAYMENT_REQUEST_SENT`. That path is RETAINED — callers still
consume `PAYMENT_REQUEST_SENT` — and must not be removed until they are migrated.

This module is the WEBSITE path section 8 asks for: a hosted browser Razorpay Standard Checkout
modal. It is ADDITIVE and is governed by the same authenticated ownership, authoritative pricing,
live provider-readiness and idempotent attempt controls as the retained in-chat path. It is written handler-free —
every external dependency (the keys table, the quote loader, the Razorpay client) is injected — so
it is fully testable offline with the same `FakeDynamo` the other payment tests use.

What `prepare_checkout` guarantees before it ever calls Razorpay
----------------------------------------------------------------
1. Session/profile/cart/quote ownership. The caller passes a proven `customer_id`; the snapshot's
   `customer_id` must equal it, and the client-presented snapshot hash must `matches()` the
   immutable FEAT-001 snapshot. An expired snapshot is refused.
2. The amount is the FEAT-001 CALCULATOR total (`quote.as_payable_money()`), not the raw Wix
   total — a zero-total quote is not payable and never reaches the gateway.
3. INR only, and the account mode is derived from the live key id and persisted on the binding.
4. A customer-scoped request key is reserved BEFORE the external call. Same key + same intent
   resumes onto the one order already created (concurrent clicks coordinate); same key + CHANGED
   intent is rejected.
5. The initiation gate. Off (the default) -> `PAYMENT_INITIATION_DISABLED`, no gateway order, no
   payable attempt.

Only then does it create the Razorpay order, persist the id/account/mode/amount binding BEFORE
exposing options, and return ONLY the public key id, the stored gateway order id, the approved
amount/currency, the allowed prefill and the owned attempt reference.

Ambiguity, not a licence to double-charge
-----------------------------------------
If the order-create times out, or the create may have landed but the binding could not be saved,
the provider client raises `RazorpayUnavailable`. This module does NOT create a second payable
order. It uses the documented receipt-correlation lookup to discover whether the first create
landed, binds to it if so, and otherwise reports an ambiguous-pending state for reconciliation. It
never assumes an undocumented Orders-API idempotency.

What `verify_callback` guarantees
---------------------------------
The browser relays `razorpay_payment_id|razorpay_order_id|razorpay_signature`. This verifies the
HMAC using the SERVER-STORED gateway order id (never the browser's), re-checks the stored
account/mode (a test-mode binding must never settle as live, and vice versa), rejects a result
whose stored order/amount/currency do not match the binding, and — crucially — treats a valid
signature as only a trigger: it STILL requires `razorpay_verify`'s authenticated captured-payment
readback before returning a paid state. Cart/resume data is kept until that verified-paid
finalization.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from lambda_utils.ecommerce import finalization, order_keys, payment_attempt
from lambda_utils.ecommerce.checkout_pricing import (
    PricingError, QuoteSnapshot, basket_hash, narrow_basket_hash)

logger = logging.getLogger(__name__)

#: Checkout mode marker, distinguishing the website path from the retained in-WhatsApp one.
CHECKOUT_MODE_WEBSITE = "WEBSITE_RAZORPAY_STANDARD"

# ── one live payment per basket ────────────────────────────────────────────────

#: How long an in-flight attempt blocks a second payable order for the same basket.
#:
#: Strictly greater than every quote TTL that can serve this path, so a second create always
#: needs a fresh quote before the block lifts:
#:   purchase_intent.QUOTE_TTL_SECONDS             = 300   (Cart V2, the live serving path)
#:   checkout handler WEBSITE_SNAPSHOT_TTL_SECONDS = 900   (the V1 fallback)
#:   CREATE_CLAIM_STALE_SECONDS                    = 120
#: 900 was wrong: it EQUALS the V1 TTL, so on V1 the quote and the block would expire together
#: and the property this constant exists for would not hold. A test pins the inequality.
CART_PAYMENT_IN_FLIGHT_SECONDS = 1200

#: How long a create claim is honoured before a later click may take it over. The provider
#: timeout is 10s; this covers a cold start plus one internal retry and still bounds a dead
#: winner's hold to about two minutes. Used by TWO claims on the same horizon, deliberately:
#: the claim on the REQUEST KEY, and the claim on the BASKET. It also bounds the dangling-row
#: refusal for a per-basket row that is still `CREATE_CLAIMED` — a claim with no attempt behind
#: it means a create FAILED, which is a different fact from a capture still settling and must
#: not inherit `CART_PAYMENT_IN_FLIGHT_SECONDS`.
CREATE_CLAIM_STALE_SECONDS = 120

#: The budget the TWO stored blobs SHARE, because they are two attributes on ONE 400 KB DynamoDB
#: item. Split JOINTLY, never per-blob: a per-blob ceiling of this size permits twice this size
#: on the row, which is how a guard written to bound an item limit comes to exceed it.
_ATTEMPT_BLOB_BUDGET_BYTES = 180_000

#: The floor the Wix payload keeps whatever the snapshot used, so `priceSummary` and
#: `additionalFees` — which are never trimmed at any size — stay representable.
_WIX_PAYLOAD_FLOOR_BYTES = 20_000

#: Mirrors `wix_writeback.PAYLOAD_REDUCED_FLAG` as a LITERAL, for the same reason
#: `finalization.ACCEPTED_CHECKOUT_MODES` mirrors `CHECKOUT_MODE_WEBSITE` as one: this module
#: holds no import of its sibling writeback adapter. A divergence between the two would silently
#: DISABLE `accept_paid`'s reduced-payload refusal, so a test pins them equal.
_WIX_PAYLOAD_REDUCED_FLAG = "lineItemsReduced"

# ── outcome states (the documented website contract, replacing PAYMENT_REQUEST_SENT) ──
#: Initiation gate is off: everything up to the external call ran, but no gateway order was
#: created and no payable attempt exists. The website equivalent of the in-chat
#: `PAYMENT_INITIATION_DISABLED`.
PAYMENT_INITIATION_DISABLED = "PAYMENT_INITIATION_DISABLED"
#: A gateway order exists and the browser may open Standard Checkout. Carries only the public,
#: owner-approved fields.
CHECKOUT_OPTIONS_READY = "CHECKOUT_OPTIONS_READY"
#: Ownership, snapshot or intent did not hold. No order was created.
CHECKOUT_REJECTED = "CHECKOUT_REJECTED"
#: The provider create was ambiguous (timeout / save failure) and correlation could not confirm a
#: landed order. For reconciliation; NEVER a second payable create.
CHECKOUT_AMBIGUOUS = "CHECKOUT_AMBIGUOUS"

#: Callback outcomes.
CALLBACK_VERIFIED_PAID = "VERIFIED_PAID"
CALLBACK_SIGNATURE_INVALID = "SIGNATURE_INVALID"
CALLBACK_BINDING_MISMATCH = "BINDING_MISMATCH"
CALLBACK_NOT_CAPTURED = "NOT_CAPTURED"

# ── refusal reasons, all exported so handler and tests name constants ──────────
#: This exact basket has already been captured. No window makes a second order safe.
CART_ALREADY_PAID = "CART_ALREADY_PAID"
#: A payable attempt for this basket is live, or a concurrent prepare holds its create slot.
CART_PAYMENT_IN_FLIGHT = "CART_PAYMENT_IN_FLIGHT"
#: A gateway order exists but the three cart rows could not be written, so the basket is
#: unguarded. NO options are exposed: the modal never opens, so no money can move, and the
#: unused Razorpay order expires.
CART_POINTER_SAVE_FAILED = "CART_POINTER_SAVE_FAILED"
#: A landed gateway order is already bound to a different customer's attempt.
BINDING_OWNED_ELSEWHERE = "BINDING_OWNED_ELSEWHERE"
#: A create is in flight elsewhere on this request key. Carries no claim about a charge.
CREATE_IN_FLIGHT = "CREATE_IN_FLIGHT"
#: A stored binding resolved to an empty gateway order id or an empty attempt id, so there is
#: nothing the browser could pay and nothing the pointer could name. UNCERTAINTY, not refusal,
#: so it answers 200 like BINDING_SAVE_FAILED and CREATE_UNCONFIRMED.
PAYABLE_MODAL_UNRESOLVED = "PAYABLE_MODAL_UNRESOLVED"

#: Raised as `CheckoutRejected`, not returned as a reason: a pre-create refusal with nothing
#: created and nothing written. The V1 snapshot branch mints a NEW Wix checkout id per prepare,
#: so the cart-keyed guard cannot resolve a pointer on it and the one-live-payment invariant does
#: not exist there.
CART_V2_REQUIRED = "CART_V2_REQUIRED"
#: Also raised as `CheckoutRejected`. The snapshot carries no frozen payload, so no basket
#: identity can be computed and the one-live-payment guard CANNOT RUN. Distinct from
#: AMOUNT_NOT_SETTLED, which means the quote will not settle — a guard that could not run is a
#: different fact and must not be reported as a pricing failure.
BASKET_IDENTITY_REQUIRED = "BASKET_IDENTITY_REQUIRED"
#: Also raised as `CheckoutRejected`. The request key was reserved by an earlier click that has
#: no reference on its row, so the create provably never started. The one refusal on the resume
#: path where "no charge was made" may honestly be said.
CREATE_NOT_STARTED = "CREATE_NOT_STARTED"


class CheckoutRejected(Exception):
    """A pre-create guard failed. Carries a stable `reason` code; never a provider/body string."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PreparedCheckout:
    """The result of `prepare_checkout`. Only the browser-safe projection is in `options`."""

    status: str
    payment_attempt_id: str = ""
    gateway_order_id: str = ""
    options: Optional[Dict[str, Any]] = None
    reason: str = ""


@dataclass(frozen=True)
class _CartGuard:
    """What step 2a decided, and the two CAS bases step 4b needs to act on it.

    `reason` empty means "a payable order may be created for this basket". The two `prior_*`
    fields are the `paymentAttemptId` values read off the two per-basket rows on THIS pass — ''
    when the row was absent — and they are the only values step 4b's claim may condition on.
    Carrying them forward rather than re-reading is the point: a row that changed between step 2a
    and step 4b must make the claim FAIL, and it only can if the condition names the value the
    decision was based on.
    """

    reason: str = ""
    attempt_id: str = ""
    prior_basket_attempt: str = ""
    prior_narrow_attempt: str = ""


def intent_fingerprint(snapshot: QuoteSnapshot) -> str:
    """A stable fingerprint of the purchase intent, for request-key coordination.

    Covers exactly what must not change silently between two clicks: the customer, the cart and
    its revision, the immutable snapshot hash, the payable total and the currency. A changed cart
    produces a new snapshot hash, which changes this fingerprint, which is how a resumed request
    key with a different intent is detected and refused. SHA-256 over a canonical string.
    """
    quote = snapshot.quote
    material = "|".join([
        snapshot.customer_id,
        snapshot.cart_id,
        str(snapshot.cart_revision),
        snapshot.snapshot_hash,
        str(quote.total_payable_paise),
        quote.currency,
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _browser_options(*, key_id: str, gateway_order_id: str, amount_paise: int,
                     currency: str, prefill: Mapping[str, Any],
                     payment_attempt_id: str) -> Dict[str, Any]:
    """Exactly the fields the browser is allowed to receive. Nothing else.

    No secret, no raw Wix total, no customer id, no full binding. The prefill is restricted to the
    name/email/contact Razorpay's checkout documents, and only values the caller passed through
    from the proven session/profile.
    """
    allowed_prefill = {}
    for field in ("name", "email", "contact"):
        value = prefill.get(field) if isinstance(prefill, Mapping) else None
        if value:
            allowed_prefill[field] = value
    return {
        "keyId": key_id,
        "orderId": gateway_order_id,
        "amountPaise": int(amount_paise),
        "currency": currency,
        "prefill": allowed_prefill,
        "paymentAttemptId": payment_attempt_id,
    }


def _receipt_for(reference_id: str, request_key: str) -> str:
    """The Razorpay `receipt`, which is what ambiguity recovery correlates on.

    The reference when there is one, so a recovery recovers onto the reference as well as onto
    the order; the old request-key form otherwise, which is what keeps callers that pass no
    reference behaving exactly as before.

    The slice uses `order_keys.RAZORPAY_RECEIPT_MAX_LENGTH` while `razorpay_orders` compares with
    its own `RECEIPT_MAX_LENGTH`; a divergence between those two constants produces no error, only
    a correlation that silently stops matching, so a test asserts them equal.
    """
    if reference_id:
        return reference_id[:order_keys.RAZORPAY_RECEIPT_MAX_LENGTH]
    return f"wk_{request_key}"[:order_keys.RAZORPAY_RECEIPT_MAX_LENGTH]


def _reference_and_create_right(keys_table: Any, *, customer_id: str, request_key: str,
                                now: int, reference_id: str) -> Tuple[str, bool]:
    """Record the reference and take the exclusive right to call `create_order`.

    Returns `(authoritative_reference, may_create)`. The reference is READ BACK off the row,
    because `if_not_exists` protects the STORED value and nothing else — a caller that threaded
    its own candidate into `notes`, the receipt and the binding while the row held a different
    value would break the one stability property the whole reconciliation pipeline is keyed on.

    ONE conditional update, so a concurrent click cannot also win the right. NOT best-effort: a
    conditional failure means somebody else holds the create right, and the stored reference is
    read and returned with `may_create=False`; ANY other error raises `OrderIdentityUnavailable`,
    never a silent pass, because a silent failure here would let a resumed click mint a second
    reference.
    """
    key = order_keys.REQUEST_KEY_PREFIX + customer_id + "#" + request_key
    try:
        updated = keys_table.update_item(
            Key={"orderId": key},
            UpdateExpression=("SET referenceId = if_not_exists(referenceId, :r), "
                              "createClaimedAt = :now"),
            ConditionExpression=(
                "attribute_exists(orderId) AND "
                "(attribute_not_exists(createClaimedAt) OR createClaimedAt < :stale)"),
            ExpressionAttributeValues={":r": reference_id, ":now": int(now),
                                       ":stale": int(now) - CREATE_CLAIM_STALE_SECONDS},
            # The whole reason this is an update and not a put: ALL_NEW hands back whichever
            # value `if_not_exists` actually kept, in the same round trip that claimed the right.
            ReturnValues="ALL_NEW",
        )
        attributes = (updated or {}).get("Attributes") or {}
    except Exception as error:  # noqa: BLE001 - classified, never swallowed
        # The single public classifier, rather than a fourth inline copy of the same check.
        if order_keys.is_conditional_failure(error):
            logger.info('{"event":"website_checkout_create_right_held"}')
            # Read the row rather than returning our candidate: the holder's reference is the
            # authority, and the receipt correlation downstream must use it to find their order.
            held = order_keys.resolve_checkout_request_key(
                keys_table, customer_id=customer_id, request_key=request_key) or {}
            return str(held.get("referenceId") or reference_id), False
        raise order_keys.OrderIdentityUnavailable(
            "could not record the payment reference: %s" % type(error).__name__) from error
    return str(attributes.get("referenceId") or reference_id), True


def _link_reference_to_provider_order(keys_table, reference_id, gateway_order_id) -> None:
    """Best-effort: record the provider order id on the `PAYREF#` row.

    Deliberately best-effort, and the only write on this path that is. The field exists so a
    capture can be verified against a stored provider binding; without it a capture falls to the
    quarantine path for a human instead of reconciling, which is the safe direction. Logged by
    exception type only.
    """
    if not reference_id:
        return
    try:
        keys_table.update_item(
            Key={"orderId": order_keys.PAYMENT_REFERENCE_PREFIX + reference_id},
            UpdateExpression="SET providerOrderId = :o",
            ConditionExpression="attribute_exists(orderId)",
            ExpressionAttributeValues={":o": gateway_order_id},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"website_checkout_reference_provider_link_skipped","error":"%s"}',
                    type(error).__name__)


def _bounded_snapshot(payload: Mapping[str, Any], ceiling: int) -> Dict[str, Any]:
    """The reviewed snapshot as stored on the attempt, reduced only when it is too large.

    No sanitiser, for a measured reason: `build_snapshot` already hashed this payload, and
    `checkout_pricing._stable_hash` -> `_canonical` RAISES `PricingError` on any float and on any
    fractional `Decimal`. A snapshot that exists is therefore proven free of both, and adding a
    sanitiser would mean a value could reach storage that the hash would have refused.

    What is not bounded by that argument is SIZE. Above `ceiling` a reduced projection is stored,
    with `purchasedSnapshotReduced` beside it so evidence is never mistaken for the whole record.
    `cart` is retained deliberately: `finalization.accept_paid`'s own guard is
    `snapshot.get('cart')`, so dropping it would refuse the order rather than shrink it.
    `snapshotHash` stays the authority for what the customer reviewed either way.
    """
    stored = dict(payload)
    if len(json.dumps(stored, default=str)) <= ceiling:
        return stored
    items = stored.get("items")
    trimmed = [{"name": item.get("name"), "quantity": item.get("quantity")}
               for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []
    logger.info('{"event":"website_checkout_snapshot_reduced"}')
    return {
        "cart": stored.get("cart"),
        "components": stored.get("components"),
        "policyVersion": stored.get("policyVersion"),
        "address": stored.get("address"),
        "delivery": stored.get("delivery"),
        "items": trimmed,
        "purchasedSnapshotReduced": True,
    }


def _bounded_wix_order_payload(payload: Mapping[str, Any], ceiling: int) -> Dict[str, Any]:
    """The Wix order payload as stored on the attempt, reduced only when it is too large.

    What differs from `_bounded_snapshot` is WHAT may be trimmed: A MONEY FIELD IS NEVER THE
    THING THAT GETS TRIMMED. `priceSummary` and `additionalFees` are untouched at any size; only
    the line-item detail is reduced, and the reduction is FLAGGED — `finalization.accept_paid`
    refuses to send a flagged payload, because a payload with no catalog references would create
    a Wix order naming no products.
    """
    stored = dict(payload)
    if len(json.dumps(stored, default=str)) <= ceiling:
        return stored
    items = stored.get("lineItems")
    stored["lineItems"] = [
        {"productName": item.get("productName"), "quantity": item.get("quantity")}
        for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []
    stored[_WIX_PAYLOAD_REDUCED_FLAG] = True
    logger.info('{"event":"website_checkout_wix_payload_reduced"}')
    return stored


# ── the cart guard: one live payment per basket ────────────────────────────────

def _stored_attempt(attempts_table, attempt_id):
    """The attempt row by id, ConsistentRead, or None. Never absence-on-error.

    Consistent because the pointer may have been written on a request that finished milliseconds
    ago and an eventually-consistent read could miss the attempt. Extracted as a helper because
    both the per-basket arm and the cart-pointer arm need it.
    """
    if attempts_table is None:
        return None
    try:
        return attempts_table.get_item(
            Key={"paymentAttemptId": attempt_id}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        # The LIKELIEST read failure on this path, and it must not reach the caller as absence.
        # Converted here so the handler's explicit 503 arm covers it.
        raise order_keys.OrderIdentityUnavailable(
            "could not read the cart's payment attempt: %s" % type(error).__name__) from error


def _paid_basket_refusal(row, attempts_table, customer_id, now,
                         request_key="") -> Tuple[str, str]:
    """One shared decision body for BOTH per-basket rows. `('', '')` means "this row says nothing".

    Extracted so the refusal reason, the customer check and the bounded dangling behaviour stay
    SINGLE-VALUED across the two prefixes. Two copies of this would be two chances to let them
    drift, and the halves that must not drift are exactly the ones a reviewer cannot see at a
    glance: which window bounds a dangling row, and whether a foreign customer blocks.

    `request_key` is the resume exemption, and WHERE it applies is load-bearing. These rows are
    written by `_emit_payable_modal` on every successful prepare, so the row a second click on
    the SAME request key finds is the row its OWN first click wrote. Refusing that would convert
    every legitimate double-click and reload of an UNPAID attempt into `CART_PAYMENT_IN_FLIGHT`,
    when the correct answer is the resume onto the one gateway order that already exists.

    The exemption applies to the IN-FLIGHT and DANGLING arms and DELIBERATELY NOT to the PAID
    arm. A reload in the tab that just paid still holds its request key — `cart.tsx` never clears
    it — so exempting the paid arm would hand that tab a payable modal for a basket that is
    already captured, which is the hole this whole guard exists to close.
    """
    attempt_id = str((row or {}).get("paymentAttemptId") or "")
    if not attempt_id:
        return "", ""
    same_request = bool(request_key) and str((row or {}).get("requestKey") or "") == request_key
    prior = _stored_attempt(attempts_table, attempt_id)
    if prior is None and same_request:
        # Our own earlier click on this very request key, whose attempt we cannot read (either no
        # attempt store was injected, or the row is genuinely unreadable). Step 3's reservation
        # and step 4a's resume are the authority for this case: they resolve back onto the one
        # gateway order and mint nothing. Blocking here would refuse a reload with no escape
        # until the window elapsed, for a request that cannot create a second payable order.
        return "", ""
    if prior is None:
        # Dangling, or no attempt store was injected. BOUNDED fail-closed: blocking forever would
        # brick a basket on an anomaly with no escape, and passing immediately would re-open the
        # door during the interval when a capture can still be landing.
        #
        # TWO WINDOWS, because a dangling row has two causes and they deserve different answers:
        #   * RECORDED (`recordedAt` present) — the attempt existed and cannot be read now. An
        #     anomaly during the settling interval, so it gets CART_PAYMENT_IN_FLIGHT_SECONDS.
        #   * CREATE_CLAIMED (`claimedAt` only, no `recordedAt`) — a claim took the slot and never
        #     reached the attempt put, i.e. a create failed or a sandbox died. That is a FAILED
        #     CREATE, not a settling capture, so it gets CREATE_CLAIM_STALE_SECONDS and the
        #     shopper may retry in two minutes rather than twenty.
        logger.error(json.dumps({"event": "website_checkout_cart_basket_dangling"}))
        recorded = int((row or {}).get("recordedAt") or 0)
        if recorded:
            if now - recorded <= CART_PAYMENT_IN_FLIGHT_SECONDS:
                return CART_PAYMENT_IN_FLIGHT, attempt_id
            return "", ""
        claimed = int((row or {}).get("claimedAt") or 0)
        if claimed and now - claimed <= CREATE_CLAIM_STALE_SECONDS:
            return CART_PAYMENT_IN_FLIGHT, attempt_id
        return "", ""
    if str(prior.get("customerId") or "") != customer_id:
        # The row is an INDEX, not an authority, exactly as the cart pointer is.
        logger.warning(json.dumps({"event": "website_checkout_cart_basket_foreign"}))
        return "", ""
    if payment_attempt.may_create_order(prior):
        # PAID, and this is the same basket by KEY EQUALITY rather than by comparison. No window:
        # re-presenting a basket that was captured is refused for as long as the row and the paid
        # attempt exist, whatever the request key says and whatever Wix's revision counter has
        # done since. NO request-key exemption, deliberately — see the docstring.
        return CART_ALREADY_PAID, attempt_id
    if same_request:
        # A resume of an UNPAID attempt on the key that created it. Below the paid arm, never
        # above it.
        return "", ""
    if payment_attempt.is_in_flight(prior):
        # A live attempt for THIS basket, reached without consulting the single-slot pointer. The
        # pointer arm would answer the same thing when it still names this attempt; this covers
        # the case where a later basket has since taken the slot.
        moved = int(prior.get("updatedAt") or prior.get("createdAt") or 0)
        if now - moved <= CART_PAYMENT_IN_FLIGHT_SECONDS:
            return CART_PAYMENT_IN_FLIGHT, attempt_id
    return "", ""


def _live_cart_payment(*, keys_table, attempts_table, customer_id, wix_cart_id,
                       presented_basket_hash, presented_narrow_hash,
                       request_key, now) -> _CartGuard:
    """A `_CartGuard` whose `reason` is empty when a payable order may be created for this basket.

    Lets `OrderIdentityUnavailable` propagate. The caller answers 503; it must never answer
    "no live payment", because the caller acts on that by creating one.

    THREE ROWS, because the questions have different cardinalities and the paid question has two
    identities:

      * `CARTBASKET#<sub>#<cart>#<basketHash>` — "has THIS BASKET been paid?", keyed on the FINE
        identity. Asked first.
      * `CARTNARROW#<sub>#<cart>#<narrowHash>` — the SAME question keyed on the identity we can
        PROVE is stable. Asked beside it, and it is what answers when `basket_hash` moved on a
        field Wix controls. Either row resolving to a paid attempt is enough.
      * `CARTPAYMENT#<sub>#<cart>` — "which attempt is LIVE on this cart?" One per cart,
        last-writer-wins, which is correct for that question and fatal for the paid one.

    None of them is `snapshot_hash`. A guard whose identifiers change on every call answers
    "no live payment" to every double-submit.
    """
    if not wix_cart_id:
        # Nothing to key on, and nothing is guessed. The request-key reservation and the
        # reference claim remain, so this is a lost backstop rather than an open door.
        return _CartGuard()

    # 0. HAS THIS EXACT BASKET ALREADY BEEN PAID? Asked FIRST, keyed on the basket, asked before
    #    the pointer and before the request key is even looked at, and asked under BOTH
    #    identities. Without these rows, paying B1 then opening and abandoning a different basket
    #    B2 on the same 30-day cart makes B1 payable again — with NO window at all if B2 ended in
    #    a retryable state, because the single-slot cart row no longer names A1. Without the
    #    SECOND row the same thing happens one level down: if any non-enumerated field of Wix's
    #    lineItems / deliveryAddress / deliveryMethod moved between the two calculates,
    #    `basket_hash` differs, the key composes differently, the lookup misses BY KEY, and the
    #    pointer's narrow veto is unreachable because it only runs when the pointer names a paid
    #    attempt.
    #
    #    Written as four statements rather than two conditional expressions on purpose:
    #    `a() or {} if cond else {}` parses as `(a() or {}) if cond else {}`, which is what is
    #    meant and is not what it looks like, and this guard's reading order is the thing that
    #    most needs to be unambiguous.
    paid_basket = {}
    paid_narrow = {}
    if presented_basket_hash:
        paid_basket = order_keys.resolve_cart_basket(
            keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id,
            basket_hash=presented_basket_hash) or {}
    if presented_narrow_hash:
        paid_narrow = order_keys.resolve_cart_narrow_basket(
            keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id,
            narrow_hash=presented_narrow_hash) or {}
    prior_basket_attempt = str(paid_basket.get("paymentAttemptId") or "")
    prior_narrow_attempt = str(paid_narrow.get("paymentAttemptId") or "")
    for row in (paid_basket, paid_narrow):
        reason, blocking = _paid_basket_refusal(
            row, attempts_table, customer_id, now, request_key=request_key)
        if reason:
            return _CartGuard(reason=reason, attempt_id=blocking,
                              prior_basket_attempt=prior_basket_attempt,
                              prior_narrow_attempt=prior_narrow_attempt)

    def _pass() -> _CartGuard:
        """A pass still carries the two CAS bases, because step 4b needs them."""
        return _CartGuard(prior_basket_attempt=prior_basket_attempt,
                          prior_narrow_attempt=prior_narrow_attempt)

    pointer = order_keys.resolve_cart_payment(
        keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id) or {}
    attempt_id = str(pointer.get("paymentAttemptId") or "")
    if not attempt_id:
        return _pass()

    stored = _stored_attempt(attempts_table, attempt_id)
    pointer_same_request = (bool(request_key)
                            and str(pointer.get("requestKey") or "") == request_key)
    if not stored and pointer_same_request:
        # Our own earlier click on this very request key. Same argument as the per-basket arm:
        # step 3's reservation and step 4a's resume resolve onto the one gateway order and mint
        # nothing, so refusing here would turn a reload into a dead end for a request that
        # cannot create a second payable order. The PAID arm below is never exempted this way.
        return _pass()
    if not stored:
        # The pointer names a row we cannot read. The pointer write is must-succeed and ordered
        # AFTER the attempt put, so this is an anomaly rather than a race. It blocks for the
        # pointer's OWN window and then stops.
        logger.error(json.dumps({"event": "website_checkout_cart_pointer_dangling"}))
        recorded = int(pointer.get("recordedAt") or 0)
        if now - recorded <= CART_PAYMENT_IN_FLIGHT_SECONDS:
            return _CartGuard(reason=CART_PAYMENT_IN_FLIGHT, attempt_id=attempt_id,
                              prior_basket_attempt=prior_basket_attempt,
                              prior_narrow_attempt=prior_narrow_attempt)
        return _pass()
    if str(stored.get("customerId") or "") != customer_id:
        # The pointer is an INDEX, not an authority. The keys are customer-scoped already, so one
        # that resolves to another customer's attempt is corrupt: it must not block this customer
        # and must not be trusted.
        logger.warning(json.dumps({"event": "website_checkout_cart_pointer_foreign"}))
        return _pass()
    recorded_cart = finalization.wix_cart_id(stored, stored.get("purchasedSnapshot"))
    if recorded_cart and recorded_cart != wix_cart_id:
        # The pointer is stale against its own attempt. Trust the attempt.
        return _pass()
    if payment_attempt.may_create_order(stored):
        # PAID. ORDERED BEFORE THE SAME-REQUEST-KEY RESUME EXEMPTION, DELIBERATELY. Measured:
        # `cart.tsx` never clears CHECKOUT_REQUEST_KEY, so the tab that just paid still holds its
        # key, and a reload also discards the terminal latch. A Proceed click then presents that
        # key for a PAID basket. With the exemption first, the resume path handed back
        # CHECKOUT_OPTIONS_READY — a payable Razorpay modal on a basket that is already paid.
        #
        # TIER 1 — same basket, already captured. No window makes a second order safe. But "the
        # same cart id" is NOT "the same basket": one persisted wixCartId serves a customer for
        # 30 days, so a windowless block on the cart ALONE would refuse every repeat purchase for
        # a month. The identity compared here is therefore the BASKET, and specifically one that
        # EXCLUDES `cart.revision`.
        stored_basket = str(pointer.get("basketHash") or "")
        stored_narrow = str(pointer.get("narrowBasketHash") or "")
        if (not presented_basket_hash or not stored_basket
                or stored_basket == presented_basket_hash
                or (stored_narrow and presented_narrow_hash
                    and stored_narrow == presented_narrow_hash)):
            # No basket identity on either side is treated as "same basket", not as "different".
            # A pointer written before this field existed must fail CLOSED.
            #
            # The narrow clause is a VETO, never a licence: it can only turn a pass into a
            # refusal. Both sides must be non-empty, so a payload with no narrow identity falls
            # back to `basket_hash` alone rather than matching everything.
            return _CartGuard(reason=CART_ALREADY_PAID, attempt_id=attempt_id,
                              prior_basket_attempt=prior_basket_attempt,
                              prior_narrow_attempt=prior_narrow_attempt)
        # TIER 2 — a DIFFERENT basket, narrowly as well as broadly, on a cart that was paid
        # moments ago. Legitimate a week later; indistinguishable from a double-submit right now.
        paid_at = int(stored.get("paidAt") or stored.get("updatedAt")
                      or pointer.get("recordedAt") or 0)
        if now - paid_at <= CART_PAYMENT_IN_FLIGHT_SECONDS:
            return _CartGuard(reason=CART_PAYMENT_IN_FLIGHT, attempt_id=attempt_id,
                              prior_basket_attempt=prior_basket_attempt,
                              prior_narrow_attempt=prior_narrow_attempt)
        return _pass()
    # A RESUME of an UNPAID attempt is deliberately allowed: the same request key resolves back
    # onto the SAME gateway order at step 3 and mints nothing. A FRESH key is the dangerous
    # shape. BELOW the paid arm, never above it — see the comment there.
    #
    # `intent_fingerprint` carries `cart_revision` AND `snapshot_hash`, so if the prepare's own
    # write really does bump Wix's revision then a same-key second prepare raises INTENT_CHANGED
    # at step 3 and this arm is unreachable on V2 with the gate on. It then serves the gate-off
    # path, the V1 path, and the world where Wix does not bump. It is kept either way: it costs
    # one string comparison, and in the world where the resume IS reachable removing it would
    # turn a legitimate reload into a CART_PAYMENT_IN_FLIGHT refusal. Whichever world holds, the
    # resume it allows cannot reach the browser without the three cart rows, because
    # `_emit_payable_modal` writes them.
    if request_key and str(pointer.get("requestKey") or "") == request_key:
        return _pass()
    if payment_attempt.is_in_flight(stored):
        moved = int(stored.get("updatedAt") or stored.get("createdAt") or 0)
        if now - moved <= CART_PAYMENT_IN_FLIGHT_SECONDS:
            return _CartGuard(reason=CART_PAYMENT_IN_FLIGHT, attempt_id=attempt_id,
                              prior_basket_attempt=prior_basket_attempt,
                              prior_narrow_attempt=prior_narrow_attempt)
    return _pass()


def _record_cart_pointer(keys_table, *, customer_id, snapshot, attempt_id,
                         request_key, gateway_order_id) -> Optional[PreparedCheckout]:
    """Assert ALL THREE cart rows, or return the refusal that must be answered instead of options.

    `None` means "written, carry on", and it is returned on exactly one path: all three writes
    (two, when there is no narrow identity) succeeded. Every other outcome -- an unwritable row
    OR an identity too empty to compose a key from -- is a `CART_POINTER_SAVE_FAILED` refusal.
    Three writes, not one, and none is best-effort:

      * `CARTPAYMENT#<sub>#<cart>`         — which attempt is LIVE on this cart (one slot,
        upserted, correctly last-writer-wins);
      * `CARTBASKET#<sub>#<cart>#<basket>` — that THIS BASKET has a payable attempt, keyed on the
        FINE identity;
      * `CARTNARROW#<sub>#<cart>#<narrow>` — the same fact keyed on the identity we can PROVE is
        stable. SKIPPED, and only skipped, when the narrow identity is `''` — the "no narrow
        identity available" case `narrow_basket_hash` itself defines.

    All three are UPSERTs, so calling this on a resume path costs three idempotent writes and
    cannot leave a basket unguarded merely because an earlier invocation is the one that created
    the binding. Each per-basket write also sets `recordedAt`, which is what promotes a
    `CREATE_CLAIMED` row to `RECORDED` and so moves it out of the create-staleness window and
    under the rule that a claim can never take it over.

    Takes the `snapshot` rather than pre-computed hashes, so both identities are derived HERE from
    the same live, UN-TRUNCATED `frozen_data` the guard will derive its comparison values from.
    Passing `attempt["purchasedSnapshot"]` instead would hash a payload `_bounded_snapshot` may
    have trimmed, and a trimmed payload has a different identity.
    """
    wix_cart_id = snapshot.cart_id
    if not customer_id or not wix_cart_id:
        # A REFUSAL, not a silent pass. Either identity empty means the three keys cannot be
        # composed, so there is no basket to guard and the modal must not open.
        #
        # Unreachable today, and the refusal is here precisely so the invariant does not depend
        # on that remaining true: `build_snapshot` derives `frozen_data['cart']['id']` from the
        # same `cart_id` it puts on `QuoteSnapshot.cart_id`, and step 2a converts a cartless
        # payload into `CheckoutRejected(BASKET_IDENTITY_REQUIRED)` before anything is created,
        # while `customer_id` comes from `customer_auth.require_customer`. Returning `None` here
        # meant "written, carry on" and made the choke point's guarantee rest on a precondition
        # two modules away.
        #
        # Same reason and same vocabulary as the write-failure arm below: the basket is
        # unguarded, so NO options are exposed, the modal never opens, and the unused Razorpay
        # order expires.
        logger.error(json.dumps({"event": "website_checkout_cart_pointer_identity_missing"}))
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                                gateway_order_id=gateway_order_id,
                                reason=CART_POINTER_SAVE_FAILED)
    try:
        presented_basket = basket_hash(snapshot.frozen_data)
        presented_narrow = narrow_basket_hash(snapshot.frozen_data)
        order_keys.record_cart_payment(
            keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id,
            payment_attempt_id=attempt_id, request_key=request_key,
            basket_hash=presented_basket, narrow_basket_hash=presented_narrow,
            snapshot_hash=snapshot.snapshot_hash)
        # SECOND and THIRD, under the same refusal. Ordered after the cart row only so that a
        # partial failure leaves the weaker row written rather than the stronger one; every
        # partial outcome answers CART_POINTER_SAVE_FAILED and exposes no options, so none is a
        # state the browser can pay from.
        order_keys.record_cart_basket(
            keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id,
            basket_hash=presented_basket, payment_attempt_id=attempt_id,
            request_key=request_key, narrow_basket_hash=presented_narrow,
            snapshot_hash=snapshot.snapshot_hash)
        if presented_narrow:
            order_keys.record_cart_narrow_basket(
                keys_table, customer_id=customer_id, wix_cart_id=wix_cart_id,
                narrow_hash=presented_narrow, payment_attempt_id=attempt_id,
                request_key=request_key, basket_hash=presented_basket,
                snapshot_hash=snapshot.snapshot_hash)
    except (order_keys.OrderIdentityUnavailable, ValueError, PricingError):
        # `ValueError` is in the tuple because the three key builders raise it — not
        # `OrderIdentityUnavailable` — for an empty key part. `PricingError` is in it because both
        # identities are computed here and a payload with no cart raises rather than returning a
        # falsy hash; the same fail-closed direction, and it cannot be the silent one.
        #
        # A gateway order exists but the basket is unguarded. Expose NO options: the modal never
        # opens, so no money can move, and the unused Razorpay order expires. Same failure
        # direction and same vocabulary as BINDING_SAVE_FAILED.
        logger.error(json.dumps({"event": "website_checkout_cart_pointer_save_failed"}))
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                                gateway_order_id=gateway_order_id,
                                reason=CART_POINTER_SAVE_FAILED)
    return None


def _emit_payable_modal(*, keys_table, customer_id, snapshot, request_key,
                        attempt_id, gateway_order_id, amount_paise, currency,
                        key_id, prefill) -> PreparedCheckout:
    """THE ONLY function in this module that may construct a CHECKOUT_OPTIONS_READY response.

    Every payable Razorpay modal this service hands a browser is built here, and the three cart
    rows are written HERE, before the construction, so "a payable modal always has paid memory
    behind it" is a property of the CALL GRAPH rather than a list of exits somebody has to keep up
    to date. The previous shape stated the invariant over `_bind_and_ready` and was falsified by
    the reference graft adding a third exit in a different function.

    Returns either the refusal `_record_cart_pointer` produced — CHECKOUT_AMBIGUOUS /
    CART_POINTER_SAVE_FAILED, no `options`, so the modal cannot open — or the ready response.
    There is no third outcome and no argument that suppresses the write.

    `attempt_id` and `gateway_order_id` must BOTH be non-empty. They are the two values the
    browser needs and the two the pointer must name, and a modal carrying either as `''` is
    unpayable and unresolvable: `/checkout/status/` could not find the attempt and
    `verify_callback` would have no binding to verify against.
    """
    if not attempt_id or not gateway_order_id:
        logger.error(json.dumps({"event": "website_checkout_payable_modal_unresolved"}))
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                                reason=PAYABLE_MODAL_UNRESOLVED)
    # The write, on every path, with no caller able to skip it.
    refusal = _record_cart_pointer(
        keys_table, customer_id=customer_id, snapshot=snapshot, attempt_id=attempt_id,
        request_key=request_key, gateway_order_id=gateway_order_id)
    if refusal is not None:
        return refusal
    options = _browser_options(
        key_id=key_id, gateway_order_id=gateway_order_id, amount_paise=int(amount_paise),
        currency=currency, prefill=prefill, payment_attempt_id=attempt_id)
    return PreparedCheckout(status=CHECKOUT_OPTIONS_READY, payment_attempt_id=attempt_id,
                            gateway_order_id=gateway_order_id, options=options)


def _ready_from_binding(binding: Dict[str, Any], prefill, *, create_key_id,
                        keys_table, customer_id, snapshot, request_key,
                        fallback_attempt_id="") -> PreparedCheckout:
    """Unpack a STORED binding into `_emit_payable_modal`'s arguments. Constructs nothing itself.

    The four new parameters are keyword-only with NO default, deliberately: a call site that
    forgets them is a `TypeError` at that line rather than a silently unguarded modal.

    `fallback_attempt_id` exists because the stored binding is read with `... or {}`, so
    `paymentAttemptId` can be `''` when the `GATEWAYORDER#` row is absent. The pointer must name
    the attempt that OWNS the payable order, so the stored value wins and ours is only the
    fallback — never the other way round.
    """
    return _emit_payable_modal(
        keys_table=keys_table, customer_id=customer_id, snapshot=snapshot,
        request_key=request_key,
        attempt_id=str(binding.get("paymentAttemptId") or fallback_attempt_id or ""),
        gateway_order_id=str(binding.get("gatewayOrderId") or ""),
        amount_paise=int(binding.get("amountPaise") or 0),
        currency=str(binding.get("currency") or "INR"),
        key_id=str(binding.get("accountKeyId") or create_key_id or ""),
        prefill=prefill)


def prepare_checkout(*,
                     customer_id: str,
                     snapshot: QuoteSnapshot,
                     presented_snapshot_hash: str,
                     request_key: str,
                     now: int,
                     keys_table: Any,
                     create_order: Callable[..., Dict[str, Any]],
                     find_order_by_receipt: Callable[[str], Optional[Dict[str, Any]]],
                     account_mode_of: Callable[[str], str],
                     initiation_enabled: bool,
                     prefill: Optional[Mapping[str, Any]] = None,
                     configuration_name: str = CHECKOUT_MODE_WEBSITE,
                     reserve_attempt: Optional[Callable[[Dict[str, Any]], None]] = None,
                     attempts_table: Any = None,
                     reference_id: str = "",
                     allocate_reference: Optional[Callable[[str, int, int], str]] = None,
                     purchased_snapshot: Optional[Mapping[str, Any]] = None,
                     wix_order_payload: Optional[Mapping[str, Any]] = None,
                     ) -> PreparedCheckout:
    """Run every pre-create guard, then (only if enabled) create and bind the gateway order.

    The Razorpay client is injected as `create_order`/`find_order_by_receipt`/`account_mode_of`
    so this is testable with mocks exactly as the other payment tests mock the provider. The
    attempt store is `keys_table` plus an optional `reserve_attempt` sink for the PaymentAttempt
    record (the handler supplies the conditional put; tests may omit it).

    Every one of the five new parameters is defaulted, so the existing call sites and tests keep
    their current behaviour byte for byte: with `attempts_table=None` the guard consults the rows
    only, with `allocate_reference=None` and `reference_id=""` no reference is minted and
    `_receipt_for` falls back to the `wk_<requestKey>` form, and with both payload arguments
    `None` the attempt is written exactly as it was before the graft.
    """
    prefill = prefill or {}

    # 1. Ownership + immutable snapshot. The snapshot is the customer's; the browser-presented hash
    #    must match it; it must not be expired. Any failure rejects WITHOUT creating anything.
    if not customer_id or snapshot.customer_id != customer_id:
        raise CheckoutRejected("OWNERSHIP")
    if not snapshot.matches(presented_snapshot_hash):
        raise CheckoutRejected("SNAPSHOT_MISMATCH")
    if snapshot.is_expired(now):
        raise CheckoutRejected("SNAPSHOT_EXPIRED")

    quote = snapshot.quote
    if quote.currency != "INR":
        raise CheckoutRejected("UNSUPPORTED_CURRENCY")
    # 2. The amount is the FEAT-001 calculator total. `as_payable_money` raises for a zero total,
    #    so a non-payable quote never reaches the gateway.
    if not quote.is_payable:
        raise CheckoutRejected("NOT_PAYABLE")
    payable = quote.as_payable_money()
    full_amount_paise = payable.paise

    # Wix-native gift cards are tender, not a discount: the quote remains the full order total.
    # Cart V2 freezes the authoritative redemption into the snapshot, and only that verified leg
    # is subtracted from what Razorpay is asked to collect. The convenience fee/GST therefore
    # remains outside the gift-card-funded Wix collection.
    payment_data = snapshot.frozen_data.get("payment") if isinstance(snapshot.frozen_data, Mapping) else None
    payment_data = payment_data if isinstance(payment_data, Mapping) else {}
    gift_card = payment_data.get("wixGiftCard")
    gift_card = gift_card if isinstance(gift_card, Mapping) else None
    gift_card_redeem_paise = int(payment_data.get("wixGiftCardRedeemPaise") or 0)
    if gift_card_redeem_paise < 0 or gift_card_redeem_paise > quote.collection_before_convenience_paise:
        raise CheckoutRejected("GIFT_CARD_MISMATCH")
    pay_now_paise = full_amount_paise - gift_card_redeem_paise
    if pay_now_paise <= 0:
        # Wix gift cards fund the Wix collection; WECARE's fee/GST still requires the external
        # website gateway on every positive cart. A zero external leg would be a different flow.
        raise CheckoutRejected("NOT_PAYABLE")

    # 2a. ONE LIVE PAYMENT PER BASKET. Keyed on the CART, not on the request key, because a fresh
    #     request key is exactly what a second tab or a cleared sessionStorage mints and the
    #     (customer, request_key) reservation below cannot see it. Resolve before generate.
    #
    #     Placed BEFORE step 3's reservation so a refusal writes NOTHING AT ALL and a fresh key
    #     cannot win the reservation before anything checks the cart.
    #
    #     Both identities are computed HERE, in a try, rather than in argument position.
    #     `basket_hash` raises `PricingError` on a payload with no cart, which in argument position
    #     would surface through `_website_prepare`'s `except (PricingError, AmountNotWhole)` arm as
    #     409 AMOUNT_NOT_SETTLED — fail-closed, but a misleading reason: the quote is fine and the
    #     GUARD is what could not run.
    try:
        presented_basket = basket_hash(snapshot.frozen_data)
        presented_narrow = narrow_basket_hash(snapshot.frozen_data)
    except PricingError:
        logger.error(json.dumps({"event": "website_checkout_basket_identity_unavailable"}))
        raise CheckoutRejected(BASKET_IDENTITY_REQUIRED) from None
    cart_guard = _live_cart_payment(
        keys_table=keys_table, attempts_table=attempts_table,
        customer_id=customer_id, wix_cart_id=snapshot.cart_id,
        # The BASKET identity, not the quote hash. See `_live_cart_payment`'s paid arm.
        presented_basket_hash=presented_basket,
        presented_narrow_hash=presented_narrow,
        request_key=request_key, now=now)
    if cart_guard.reason:
        logger.warning(json.dumps({"event": "website_checkout_cart_payment_live",
                                   "reason": cart_guard.reason}))
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS,
                                payment_attempt_id=cart_guard.attempt_id,
                                reason=cart_guard.reason)

    fingerprint = intent_fingerprint(snapshot)

    # 3. Reserve the customer-scoped request key BEFORE any external call. Coordinate concurrent
    #    clicks and reject a changed intent on a resumed key.
    attempt_id = payment_attempt.new_payment_attempt_id()
    reservation, won = order_keys.reserve_checkout_request_key(
        keys_table, customer_id=customer_id, request_key=request_key,
        intent_fingerprint=fingerprint, payment_attempt_id=attempt_id,
        extra={"snapshotHash": snapshot.snapshot_hash, "amountPaise": full_amount_paise,
               "razorpayChargedPaise": pay_now_paise},
    )
    if not won:
        # A prior click reserved this key. Same intent -> resume; changed intent -> reject.
        if str(reservation.get("intentFingerprint") or "") != fingerprint:
            raise CheckoutRejected("INTENT_CHANGED")
        attempt_id = str(reservation.get("paymentAttemptId") or attempt_id)
        # NO early return here. The gate at step 4 must be evaluated for a loser too, so a
        # rollback cannot hand a browser a payable resume. The resume itself happens at 4a.

    # 4. The initiation gate. Off (default): no gateway order, no payable attempt, no reference
    #    and no basket claim. The request-key reservation above is the only row written, and it is
    #    written before the gate on purpose — it carries no money and no provider, and it is the
    #    anchor a later enabled retry resumes onto.
    if not initiation_enabled:
        logger.info('{"event":"website_checkout_initiation_disabled"}')
        return PreparedCheckout(
            status=PAYMENT_INITIATION_DISABLED,
            payment_attempt_id=attempt_id,
        )

    # 4a. A LOSER RESUMES HERE, after the gate and BEFORE the mint. This is the ordering that
    #     matters: `allocate_payment_reference` mints and durably reserves on every call, so a
    #     loser reaching step 5 writes a second PAYREF# row that `if_not_exists` cannot undo.
    if not won:
        return _resume_lost_request_key(
            reservation=reservation, keys_table=keys_table, customer_id=customer_id,
            request_key=request_key, now=now, attempt_id=attempt_id,
            pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise,
            snapshot=snapshot, prefill=prefill, create_order=create_order,
            find_order_by_receipt=find_order_by_receipt, account_mode_of=account_mode_of,
            reserve_attempt=reserve_attempt, configuration_name=configuration_name,
            gift_card=gift_card, gift_card_redeem_paise=gift_card_redeem_paise,
            purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload)

    # 4b. ONE LIVE CREATE PER BASKET. The arms at 2a are reads and the rows they read are written
    #     after `create_order` returns, so two prepares overlapping in time with DIFFERENT request
    #     keys both passed 2a. Neither the request-key reservation (step 3) nor the create right
    #     (step 5) can see that: both are keyed on the request key, so two distinct keys each win
    #     their own claim. This is the same conditional-claim shape moved onto the BASKET — the
    #     axis this guard claims to protect and the axis a fresh request key cannot bypass.
    #
    #     ONE slot is claimed, not both, and the narrow one is preferred: two prepares of the same
    #     basket are equal on the narrow identity BY CONSTRUCTION, whereas they can differ on the
    #     fine identity if Wix moved a field — exactly the case the claim must still exclude.
    #     Claiming both would need a TransactWriteItems to be atomic and buys nothing: the two
    #     keys are derived from one basket, so winning either is winning the basket.
    if snapshot.cart_id and (presented_narrow or presented_basket):
        if presented_narrow:
            won_basket = order_keys.claim_cart_narrow_basket(
                keys_table, customer_id=customer_id, wix_cart_id=snapshot.cart_id,
                narrow_hash=presented_narrow, payment_attempt_id=attempt_id,
                prior_payment_attempt_id=cart_guard.prior_narrow_attempt,
                request_key=request_key, now=now)
        else:
            # No narrow identity available. Fall back to the fine slot rather than skipping the
            # claim: a weaker exclusion is still an exclusion.
            won_basket = order_keys.claim_cart_basket(
                keys_table, customer_id=customer_id, wix_cart_id=snapshot.cart_id,
                basket_hash=presented_basket, payment_attempt_id=attempt_id,
                prior_payment_attempt_id=cart_guard.prior_basket_attempt,
                request_key=request_key, now=now)
        if not won_basket:
            # A concurrent prepare holds the basket, or a row moved between 2a and here. Either
            # way: refuse, create nothing. FAIL-CLOSED by construction, because `claim_*` raises
            # OrderIdentityUnavailable for anything that is not a lost condition.
            logger.warning(json.dumps({"event": "website_checkout_basket_claim_held"}))
            return PreparedCheckout(status=CHECKOUT_AMBIGUOUS,
                                    # DELIBERATELY NO attempt id. The holder's attempt may not
                                    # EXIST yet — the row we lost to can be a CREATE_CLAIMED slot
                                    # naming an attempt the winner has not written — and handing
                                    # that id to /checkout/status/ would point the status page at
                                    # nothing. An unresolvable attempt id is worse than none.
                                    reason=CART_PAYMENT_IN_FLIGHT)

    # 5. Mint the reference, then take the create right. Both AFTER the gate, so a gate-off
    #    prepare mints no reference and leaves no payable residue, and both BEFORE the external
    #    call, so nothing is created without a reference the webhook can reconcile on.
    #
    #    THE MINT CANNOT MOVE BELOW THE CREATE RIGHT, and the residue that follows is accepted
    #    rather than overlooked. `_reference_and_create_right` claims the right and writes the
    #    reference onto the REQUESTKEY# row in ONE conditional round trip -- that single trip is
    #    what makes the right and the reference agree -- so it has to be handed a value, which
    #    means the value exists before the right is known.
    #
    #    Consequence: a same-key click that won step 3's reservation but LOSES the create right
    #    has already minted and durably reserved a `PAYREF#` row that `if_not_exists` cannot
    #    undo. That row is abandoned, not dangerous: no gateway order is created for it, no
    #    `providerOrderId` is ever linked to it, and the webhook resolves on
    #    `notes.referenceId`, which only ever carries the WINNER's reference. It is garbage, and
    #    the loser correlates on the winner's stored reference below.
    #    `test_a_lost_create_right_correlates_on_the_stored_reference` pins both halves.
    if not reference_id and allocate_reference is not None:
        reference_id = str(allocate_reference(attempt_id, pay_now_paise,
                                              gift_card_redeem_paise) or "")
    if reference_id:
        reference_id, may_create = _reference_and_create_right(
            keys_table, customer_id=customer_id, request_key=request_key, now=now,
            reference_id=reference_id)
        if not may_create:
            # A concurrent click took the create right between our reservation and this update.
            # Correlate on the AUTHORITATIVE reference just read back, never on the one we
            # minted, and never create a second order.
            return _recover_ambiguous_create(
                keys_table=keys_table, find_order_by_receipt=find_order_by_receipt,
                receipt=_receipt_for(reference_id, request_key), attempt_id=attempt_id,
                request_key=request_key, pay_now_paise=pay_now_paise,
                full_amount_paise=full_amount_paise, currency="INR",
                account_mode_of=account_mode_of, prefill=prefill, error=None,
                reserve_attempt=reserve_attempt, snapshot=snapshot, gift_card=gift_card,
                gift_card_redeem_paise=gift_card_redeem_paise, customer_id=customer_id,
                configuration_name=configuration_name, reference_id=reference_id,
                purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload,
                miss_reason=CREATE_IN_FLIGHT)

    # 6. Create the gateway order. The receipt is the reference when there is one, so ambiguity
    #    recovery correlates on the same value the webhook reconciles on.
    receipt = _receipt_for(reference_id, request_key)
    try:
        order = create_order(
            amount_paise=pay_now_paise, receipt=receipt,
            notes={"paymentAttemptId": attempt_id, "customerId": customer_id,
                   "snapshotHash": snapshot.snapshot_hash,
                   # THE field the webhook reads to resolve an attempt. Without it a direct
                   # Razorpay capture reconciles against nothing and quarantines: money taken,
                   # no order.
                   "referenceId": reference_id},
        )
    except Exception as error:  # noqa: BLE001 - the provider client's RazorpayUnavailable, etc.
        return _recover_ambiguous_create(
            keys_table=keys_table, find_order_by_receipt=find_order_by_receipt,
            receipt=receipt, attempt_id=attempt_id, request_key=request_key,
            pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise,
            currency="INR", account_mode_of=account_mode_of,
            prefill=prefill, error=error, reserve_attempt=reserve_attempt,
            snapshot=snapshot, gift_card=gift_card,
            gift_card_redeem_paise=gift_card_redeem_paise, customer_id=customer_id,
            configuration_name=configuration_name, reference_id=reference_id,
            purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload,
        )

    return _bind_and_ready(
        keys_table=keys_table, order=order, attempt_id=attempt_id, request_key=request_key,
        pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise,
        currency="INR", account_mode_of=account_mode_of,
        prefill=prefill, reserve_attempt=reserve_attempt, customer_id=customer_id,
        configuration_name=configuration_name, snapshot=snapshot, gift_card=gift_card,
        gift_card_redeem_paise=gift_card_redeem_paise, reference_id=reference_id,
        purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload,
    )


def _resume_lost_request_key(*, reservation, keys_table, customer_id, request_key, now,
                             attempt_id, pay_now_paise, full_amount_paise, snapshot, prefill,
                             create_order, find_order_by_receipt, account_mode_of,
                             reserve_attempt, configuration_name, gift_card,
                             gift_card_redeem_paise, purchased_snapshot,
                             wix_order_payload) -> PreparedCheckout:
    """A later click on a request key somebody else reserved, with the SAME intent.

    It never calls `allocate_reference`. Three branches, in order:

      an order is already bound     resume onto it, THROUGH `_emit_payable_modal`, which writes
                                    all three cart rows first
      no reference on the row yet   `CREATE_NOT_STARTED`, which is PROVABLY pre-create, because
                                    the reference write is ordered before `create_order` and is
                                    not best-effort. This is the one refusal on this path where
                                    "no charge was made" may honestly be said
      a reference is on the row     try to take the create right with the STORED reference. Won
                                    (a stale claim retaken) -> correlate FIRST, then create on a
                                    miss. Lost -> correlate, and otherwise CHECKOUT_AMBIGUOUS /
                                    CREATE_IN_FLIGHT with NO attempt id, because the payable
                                    attempt belongs to the WINNER and handing this browser our
                                    discarded id would point the status page at nothing
    """
    # Branch 1. A payable modal, and therefore a write. This arm is reachable with NO cart rows
    # written at all: `_link_request_key_to_order` records `gatewayOrderId` on the REQUESTKEY# row
    # BEFORE `_record_cart_pointer` runs, so a pointer-save failure on the first prepare leaves a
    # bound, payable gateway order and a resumable request key with no paid memory behind it.
    # Going through `_emit_payable_modal` is what stops that payment being invisible to the next
    # fresh-key prepare.
    existing_order_id = str(reservation.get("gatewayOrderId") or "")
    if existing_order_id:
        binding = order_keys.resolve_gateway_order(keys_table, existing_order_id) or {}
        return _ready_from_binding(
            binding, prefill, create_key_id=binding.get("accountKeyId"),
            keys_table=keys_table, customer_id=customer_id, snapshot=snapshot,
            request_key=request_key, fallback_attempt_id=attempt_id)

    stored_reference = str(reservation.get("referenceId") or "")
    if not stored_reference:
        raise CheckoutRejected(CREATE_NOT_STARTED)

    stored_reference, retook = _reference_and_create_right(
        keys_table, customer_id=customer_id, request_key=request_key, now=now,
        reference_id=stored_reference)
    landed = _landed_order(find_order_by_receipt, _receipt_for(stored_reference, request_key))
    if landed:
        return _bind_and_ready(
            keys_table=keys_table, order=landed, attempt_id=attempt_id,
            request_key=request_key, pay_now_paise=pay_now_paise,
            full_amount_paise=full_amount_paise, currency="INR",
            account_mode_of=account_mode_of, prefill=prefill,
            reserve_attempt=reserve_attempt, customer_id=customer_id,
            configuration_name=configuration_name, snapshot=snapshot, gift_card=gift_card,
            gift_card_redeem_paise=gift_card_redeem_paise, reference_id=stored_reference,
            purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload)
    if not retook:
        # Somebody holds the create right right now. A create may be in flight, so this carries
        # no claim in either direction, and no attempt id: the payable attempt is the winner's.
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, reason=CREATE_IN_FLIGHT)

    receipt = _receipt_for(stored_reference, request_key)
    try:
        order = create_order(
            amount_paise=pay_now_paise, receipt=receipt,
            notes={"paymentAttemptId": attempt_id, "customerId": customer_id,
                   "snapshotHash": snapshot.snapshot_hash,
                   "referenceId": stored_reference},
        )
    except Exception as error:  # noqa: BLE001
        return _recover_ambiguous_create(
            keys_table=keys_table, find_order_by_receipt=find_order_by_receipt,
            receipt=receipt, attempt_id=attempt_id, request_key=request_key,
            pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise,
            currency="INR", account_mode_of=account_mode_of, prefill=prefill, error=error,
            reserve_attempt=reserve_attempt, snapshot=snapshot, gift_card=gift_card,
            gift_card_redeem_paise=gift_card_redeem_paise, customer_id=customer_id,
            configuration_name=configuration_name, reference_id=stored_reference,
            purchased_snapshot=purchased_snapshot, wix_order_payload=wix_order_payload)

    return _bind_and_ready(
        keys_table=keys_table, order=order, attempt_id=attempt_id, request_key=request_key,
        pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise, currency="INR",
        account_mode_of=account_mode_of, prefill=prefill, reserve_attempt=reserve_attempt,
        customer_id=customer_id, configuration_name=configuration_name, snapshot=snapshot,
        gift_card=gift_card, gift_card_redeem_paise=gift_card_redeem_paise,
        reference_id=stored_reference, purchased_snapshot=purchased_snapshot,
        wix_order_payload=wix_order_payload)


def _landed_order(find_order_by_receipt, receipt) -> Optional[Dict[str, Any]]:
    """The provider order already created for this receipt, or None. Never raises."""
    try:
        landed = find_order_by_receipt(receipt)
    except Exception as lookup_error:  # noqa: BLE001 - the lookup itself is unreachable
        logger.warning('{"event":"website_checkout_correlation_unreachable","error":"%s"}',
                       type(lookup_error).__name__)
        return None
    return landed if landed and str(landed.get("id") or "") else None


def _bind_and_ready(*, keys_table, order, attempt_id, request_key, pay_now_paise,
                    full_amount_paise, currency, account_mode_of, prefill, reserve_attempt,
                    customer_id, configuration_name, snapshot, gift_card,
                    gift_card_redeem_paise, reference_id="", purchased_snapshot=None,
                    wix_order_payload=None) -> PreparedCheckout:
    gateway_order_id = str(order.get("id") or "")
    key_id = str(order.get("key_id") or "")
    if not gateway_order_id or not key_id:
        # A create that returned no id/key is as ambiguous as a timeout: do not expose options,
        # and do not create a second order.
        raise CheckoutRejected("PROVIDER_INCOMPLETE")

    mode = account_mode_of(key_id)
    try:
        bound = order_keys.bind_gateway_order(
            keys_table, gateway_order_id=gateway_order_id, payment_attempt_id=attempt_id,
            request_key=request_key, amount_paise=pay_now_paise, account_key_id=key_id,
            account_mode=mode, currency=currency,
            # The two fields the callback needs: the reference the reconciler is keyed on, and
            # the owner `verify_callback` decides ownership from.
            extra={"referenceId": reference_id, "customerId": customer_id},
        )
    except order_keys.OrderIdentityUnavailable:
        # The order may exist on Razorpay's side but we could not persist the binding: AMBIGUOUS.
        # We cannot expose options without a stored binding to verify a callback against, and we
        # must not create a second order. Report ambiguous for reconciliation via the receipt.
        return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                                gateway_order_id=gateway_order_id, reason="BINDING_SAVE_FAILED")
    if not bound:
        # The gateway order id was ALREADY bound. That was tolerable while a binding carried only
        # amount/account/mode; it is not now that it carries the reference and the owner and that
        # ownership is decided from the stored row. Refusing rather than overwriting is the only
        # safe direction: the stored binding is what a callback will be verified against, so
        # replacing it would invalidate a payment already in flight.
        stored = order_keys.resolve_gateway_order(keys_table, gateway_order_id) or {}
        if str(stored.get("customerId") or "") != customer_id:
            logger.warning('{"event":"website_checkout_binding_owned_elsewhere"}')
            # `gateway_order_id` is deliberately OMITTED, so nothing hands this browser a pointer
            # into another customer's binding. The attempt id is ours, so the status page still
            # resolves.
            return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                                    reason=BINDING_OWNED_ELSEWHERE)
        return _ready_from_binding(
            stored, prefill, create_key_id=key_id, keys_table=keys_table,
            customer_id=customer_id, snapshot=snapshot, request_key=request_key,
            fallback_attempt_id=attempt_id)

    # Link the request key to the created order so a concurrent/retried click resumes onto it.
    _link_request_key_to_order(keys_table, customer_id, request_key, gateway_order_id)
    # Record the provider order id on the PAYREF# row. BEST-EFFORT here and only here: a failure
    # costs reconciliation (a capture quarantines for a human) rather than correctness, which is
    # the safe direction, whereas the reference write itself is not best-effort at all.
    _link_reference_to_provider_order(keys_table, reference_id, gateway_order_id)

    if reserve_attempt is not None:
        attempt = payment_attempt.build(
            # The reference when there is one; the gateway order id otherwise, which is what
            # keeps a caller that threaded no reference behaving as it did before.
            customer_id=customer_id, reference_id=reference_id or gateway_order_id,
            amount_paise=full_amount_paise, configuration_name=configuration_name,
            cart_id=snapshot.cart_id, payment_attempt_id=attempt_id,
        )
        attempt["checkoutMode"] = CHECKOUT_MODE_WEBSITE
        attempt["providerOrderId"] = gateway_order_id
        attempt["razorpayChargedPaise"] = pay_now_paise
        attempt["snapshotHash"] = snapshot.snapshot_hash
        attempt["wixGiftCardRedeemPaise"] = int(gift_card_redeem_paise)
        if gift_card:
            attempt["giftCard"] = dict(gift_card)
        # The two stored blobs SHARE one budget, because they are two attributes on ONE 400 KB
        # DynamoDB item. Split JOINTLY: a per-blob ceiling of the same size permits twice it on
        # the row, which is how a guard written to bound an item limit comes to exceed it.
        stored_snapshot = purchased_snapshot
        if stored_snapshot is None:
            stored_snapshot = snapshot.frozen_data
        attempt["purchasedSnapshot"] = _bounded_snapshot(
            stored_snapshot, _ATTEMPT_BLOB_BUDGET_BYTES)
        if wix_order_payload is not None:
            # WHATEVER THE SNAPSHOT DID NOT USE. The snapshot is measured first, deliberately:
            # `accept_paid` REFUSES a reduced payload and TOLERATES a reduced snapshot, so the
            # blob that must stay whole is the one measured against the remainder. The floor keeps
            # `priceSummary` and `additionalFees` — never trimmed at any size — representable even
            # for an absurd snapshot.
            remaining = _ATTEMPT_BLOB_BUDGET_BYTES - len(
                json.dumps(attempt.get("purchasedSnapshot") or {}, default=str))
            attempt["wixOrderPayload"] = _bounded_wix_order_payload(
                wix_order_payload, max(remaining, _WIX_PAYLOAD_FLOOR_BYTES))
        # `transition` is rank-based (CREATED 10 -> PAYMENT_PENDING 40 is forwards-only) and
        # pure, so the conditional put persists PAYMENT_PENDING as the row's initial state rather
        # than needing a second write for it.
        attempt = payment_attempt.transition(
            attempt, payment_attempt.PAYMENT_PENDING, provider_order_id=gateway_order_id)
        reserve_attempt(attempt)

    # The payable modal, through the one choke point, OUTSIDE the `reserve_attempt` block: a
    # caller that injected no attempt sink still created a payable order and still needs the
    # basket guarded.
    return _emit_payable_modal(
        keys_table=keys_table, customer_id=customer_id, snapshot=snapshot,
        request_key=request_key, attempt_id=attempt_id, gateway_order_id=gateway_order_id,
        amount_paise=pay_now_paise, currency=currency, key_id=key_id, prefill=prefill)


def _link_request_key_to_order(keys_table, customer_id, request_key, gateway_order_id) -> None:
    """Best-effort: record the created order id on the request-key row for resume.

    A failure here does not undo the created order or its binding; a resumed click simply falls
    back to the ambiguity-correlation path keyed on the receipt. Never raises into the caller.
    """
    key = order_keys.REQUEST_KEY_PREFIX + customer_id + "#" + request_key
    try:
        keys_table.update_item(
            Key={"orderId": key},
            UpdateExpression="SET gatewayOrderId = :g",
            ConditionExpression="attribute_exists(orderId)",
            ExpressionAttributeValues={":g": gateway_order_id},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"website_checkout_requestkey_link_skipped","error":"%s"}',
                    type(error).__name__)


def _recover_ambiguous_create(*, keys_table, find_order_by_receipt, receipt, attempt_id,
                              request_key, pay_now_paise, full_amount_paise, currency,
                              account_mode_of, prefill, error, reserve_attempt, snapshot,
                              gift_card, gift_card_redeem_paise, customer_id="",
                              configuration_name=CHECKOUT_MODE_WEBSITE, reference_id="",
                              purchased_snapshot=None, wix_order_payload=None,
                              miss_reason="CREATE_UNCONFIRMED") -> PreparedCheckout:
    """A create raised, or the create right was held. Correlate by receipt; NEVER create a second.

    `customer_id` is the PROVEN session id, threaded in rather than reconstructed from
    `landed["notes"]["customerId"]` — a value we sent to Razorpay and read back, which is a weaker
    authority than the id already in scope. The note stays on the provider order for diagnostics;
    it is not used to decide who owns the binding.

    The reference is threaded for the same reason it exists: without it the recovered attempt
    would be built with `reference_id = gateway_order_id` and no matching `PAYREF#` row, so a
    capture during exactly the provider incident this machinery exists for would quarantine.

    `error=None` is the create-right-held call, which is not a provider fault.
    """
    if error is None:
        logger.warning('{"event":"website_checkout_create_right_held_correlating"}')
    else:
        logger.warning('{"event":"website_checkout_create_ambiguous","error":"%s"}',
                       type(error).__name__)
    landed = _landed_order(find_order_by_receipt, receipt)
    if landed:
        # The first create DID land. Bind to it and expose options; no second order is created.
        return _bind_and_ready(
            keys_table=keys_table, order=landed, attempt_id=attempt_id, request_key=request_key,
            pay_now_paise=pay_now_paise, full_amount_paise=full_amount_paise,
            currency=currency, account_mode_of=account_mode_of,
            prefill=prefill, reserve_attempt=reserve_attempt,
            customer_id=customer_id or str(landed.get("notes", {}).get("customerId") or ""),
            configuration_name=configuration_name, snapshot=snapshot,
            gift_card=gift_card, gift_card_redeem_paise=gift_card_redeem_paise,
            reference_id=reference_id, purchased_snapshot=purchased_snapshot,
            wix_order_payload=wix_order_payload,
        )
    # Could not confirm a landed order. Report ambiguous-pending for reconciliation.
    return PreparedCheckout(status=CHECKOUT_AMBIGUOUS, payment_attempt_id=attempt_id,
                            reason=miss_reason)


# ── the browser-result callback ────────────────────────────────────────────────

@dataclass(frozen=True)
class CallbackResult:
    status: str
    payment_attempt_id: str = ""
    gateway_order_id: str = ""
    payment_id: str = ""
    amount_paise: int = 0
    currency: str = ""


def verify_callback(*,
                    customer_id: str,
                    presented_order_id: str,
                    payment_id: str,
                    signature: str,
                    keys_table: Any,
                    verify_signature: Callable[..., bool],
                    verify_capture: Callable[[str], Tuple[bool, str, int, str]],
                    account_mode_of: Optional[Callable[[str], str]] = None,
                    ) -> CallbackResult:
    """Verify a browser Standard Checkout result against the SERVER-STORED binding, then capture.

    `verify_signature(stored_order_id, payment_id, signature)` is the injected HMAC check (over the
    STORED order id). `verify_capture(reference_id)` is `razorpay_verify.verifier_for_event`'s
    closure, which performs the authenticated captured-payment readback bound to the attempt.
    `account_mode_of(key_id)` is `razorpay_orders.account_mode`'s `test`/`live`/`unknown`
    classifier, injected like the other provider dependencies; defaulting to None keeps the
    account/mode cross-check off only when a caller has no classifier to offer.

    Order of checks, each load-bearing:
      - Resolve the binding by the stored gateway order id. An unknown order id is a mismatch.
      - Ownership: the attempt behind the binding must belong to this customer (checked by the
        caller via the attempt row; here we require the binding to resolve and carry the attempt).
      - Account/mode: the binding persists `accountMode` and `accountKeyId` expressly so "a
        test-mode success must never settle a live-mode order" (see `order_keys.bind_gateway_order`
        and `razorpay_orders.account_mode`). We consult that stored field here rather than leave it
        unenforced: the mode the stored `accountKeyId` resolves to must equal the stored
        `accountMode`, and neither may be `unknown`/empty. A binding whose stored mode disagrees
        with the mode its own stored key resolves to — a tampered or cross-mode binding — must not
        settle. The capture readback itself runs against a single documented account
        (`wecare/razorpay/api`), so a cross-account capture cannot authenticate; this check closes
        the remaining gap at the stored binding, which is where the invariant was recorded.
      - HMAC over the STORED order id (never the browser's `presented_order_id`).
      - A valid signature is still only a trigger: require `verify_capture` to confirm a capture,
        and the captured amount/currency to equal the stored binding, before VERIFIED_PAID.
    """
    binding = order_keys.resolve_gateway_order(keys_table, presented_order_id)
    if not binding:
        return CallbackResult(status=CALLBACK_BINDING_MISMATCH)
    stored_order_id = str(binding.get("gatewayOrderId") or "")
    attempt_id = str(binding.get("paymentAttemptId") or "")
    stored_amount = int(binding.get("amountPaise") or 0)
    stored_currency = str(binding.get("currency") or "")
    stored_mode = str(binding.get("accountMode") or "")
    stored_key_id = str(binding.get("accountKeyId") or "")

    # Account/mode re-check against the stored binding, before anything else can settle it. The
    # mode the stored key resolves to must equal the stored mode, and a result produced under a
    # mode we cannot positively classify (`unknown`/empty) must not settle a bound order.
    if account_mode_of is not None:
        resolved_mode = account_mode_of(stored_key_id)
        if (not stored_mode or stored_mode == "unknown"
                or resolved_mode != stored_mode):
            return CallbackResult(status=CALLBACK_BINDING_MISMATCH,
                                  payment_attempt_id=attempt_id,
                                  gateway_order_id=stored_order_id)

    # HMAC is computed over the STORED order id, not anything the browser relayed.
    if not verify_signature(stored_order_id=stored_order_id, payment_id=payment_id,
                            signature=signature):
        return CallbackResult(status=CALLBACK_SIGNATURE_INVALID,
                              payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)

    # Signed success is only a trigger. Require an authenticated captured-payment readback.
    captured, provider_payment_id, amount_paise, currency = verify_capture(stored_order_id)
    if not captured:
        return CallbackResult(status=CALLBACK_NOT_CAPTURED,
                              payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)
    if amount_paise != stored_amount or currency != stored_currency:
        # A capture for a different amount/currency than the one we bound must not settle.
        return CallbackResult(status=CALLBACK_BINDING_MISMATCH,
                              payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)

    return CallbackResult(status=CALLBACK_VERIFIED_PAID, payment_attempt_id=attempt_id,
                          gateway_order_id=stored_order_id, payment_id=provider_payment_id,
                          amount_paise=amount_paise, currency=currency)


__all__ = [
    "CHECKOUT_MODE_WEBSITE",
    "CART_PAYMENT_IN_FLIGHT_SECONDS",
    "CREATE_CLAIM_STALE_SECONDS",
    "PAYMENT_INITIATION_DISABLED",
    "CHECKOUT_OPTIONS_READY",
    "CHECKOUT_REJECTED",
    "CHECKOUT_AMBIGUOUS",
    "CALLBACK_VERIFIED_PAID",
    "CALLBACK_SIGNATURE_INVALID",
    "CALLBACK_BINDING_MISMATCH",
    "CALLBACK_NOT_CAPTURED",
    "CART_ALREADY_PAID",
    "CART_PAYMENT_IN_FLIGHT",
    "CART_POINTER_SAVE_FAILED",
    "BINDING_OWNED_ELSEWHERE",
    "CREATE_IN_FLIGHT",
    "PAYABLE_MODAL_UNRESOLVED",
    "CART_V2_REQUIRED",
    "BASKET_IDENTITY_REQUIRED",
    "CREATE_NOT_STARTED",
    "CheckoutRejected",
    "PreparedCheckout",
    "CallbackResult",
    "intent_fingerprint",
    "prepare_checkout",
    "verify_callback",
]
