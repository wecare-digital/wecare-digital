"""Contribution payment helpers.

The SKU-first Contribute catalog item has one ₹300 variant (CNT5Q2M8).
The live ProductsTable remains authoritative when a customer checks out;
these presets identify permitted contribution choices, not browser-set prices.
Generic settlement helpers preserve the payment-purpose contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple

from lambda_utils.ecommerce import order_keys, payment_attempt
from lambda_utils.ecommerce.money import positive_paise
from lambda_utils.identifiers import new_uuid7

logger = logging.getLogger(__name__)

#: The payment purpose, mirroring the frontend's ``CONTRIBUTION_PURPOSE`` in src/config/contribution.ts
#: and the key the webhook routes a captured contribution under.
CONTRIBUTION_PURPOSE = "BLOG_CONTRIBUTION"

#: Checkout-mode marker on the attempt, distinguishing a contribution from the website cart path.
CONTRIBUTION_MODE = "BLOG_CONTRIBUTION_RAZORPAY_STANDARD"

#: The only currency contributions are taken in.
CONTRIBUTION_CURRENCY = "INR"

#: Allowed contribution preset in paise, mirrored in src/config/contribution.ts.
#: The checkout still reads the actual price from live ProductsTable.
CONTRIBUTION_PRESETS_PAISE: Tuple[int, ...] = (30000,)

#: Recognize only the current SKU-first contribution product identity.
CONTRIBUTION_PRODUCT_IDS: FrozenSet[str] = frozenset({
    "24fa0f39-330b-5365-b7eb-9caf27ad37f1",
})

#: Exactly one contribution variant is offered at ₹300.
CONTRIBUTION_CHOICES_PAISE: Mapping[str, int] = MappingProxyType({
    "CNT5Q2M8": 30000,
})

#: The variant ids above as a set, for membership tests that do not need the amount.
CONTRIBUTION_VARIANT_IDS: FrozenSet[str] = frozenset(CONTRIBUTION_CHOICES_PAISE)

# ── outcome states: the SAME documented website-checkout contract the shipped UI binds to ──
PAYMENT_INITIATION_DISABLED = "PAYMENT_INITIATION_DISABLED"
CHECKOUT_OPTIONS_READY = "CHECKOUT_OPTIONS_READY"
CHECKOUT_REJECTED = "CHECKOUT_REJECTED"
CHECKOUT_AMBIGUOUS = "CHECKOUT_AMBIGUOUS"

#: Callback outcomes, matching website_checkout.
CALLBACK_VERIFIED_PAID = "VERIFIED_PAID"
CALLBACK_SIGNATURE_INVALID = "SIGNATURE_INVALID"
CALLBACK_BINDING_MISMATCH = "BINDING_MISMATCH"
CALLBACK_NOT_CAPTURED = "NOT_CAPTURED"

#: Webhook settlement outcomes.
SETTLE_SETTLED = "SETTLED"
SETTLE_DUPLICATE = "DUPLICATE"
SETTLE_QUARANTINED = "QUARANTINED"


class ContributionRejected(ValueError):
    """A pre-create guard failed. Carries a stable ``reason`` code; never a provider/body string.

    BASE CLASS IS ``ValueError``, DELIBERATELY, and it is load-bearing (Phase 2, Sec 2.6).
    ``checkout/handler.py:_contribution_request`` raises this from inside ``_v2_snapshot`` on the
    live checkout function, and ``_v2_snapshot`` has two callers. ``_create`` -- which ``_action``
    reaches for any unrecognised action or path -- ends its except chain with
    ``except ValueError`` => ``409 AMOUNT_NOT_SETTLED``. Derived from bare ``Exception`` this
    would instead reach ``handler``'s outer ``except Exception`` and answer
    ``500 INTERNAL_ERROR`` on that route. ``_website_prepare`` catches it by name and answers
    ``409 CONTRIBUTION_AMOUNT_INVALID``. The precedent is
    ``checkout/handler.py``'s ``DeliveryMethodUnavailable``, whose docstring records the same rule.

    Safe to re-base: every reference outside this module is a ``pytest.raises``, which is
    indifferent to the base class.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PreparedContribution:
    """The result of ``prepare_contribution``. Only the browser-safe projection is in ``options``."""

    status: str
    contribution_id: str = ""
    payment_attempt_id: str = ""
    gateway_order_id: str = ""
    options: Optional[Dict[str, Any]] = None
    reason: str = ""


@dataclass(frozen=True)
class ContributionCallbackResult:
    status: str
    contribution_id: str = ""
    payment_attempt_id: str = ""
    gateway_order_id: str = ""
    payment_id: str = ""
    amount_paise: int = 0
    currency: str = ""


@dataclass(frozen=True)
class ContributionSettlement:
    status: str
    contribution_id: str = ""
    payment_id: str = ""
    amount_paise: int = 0
    reason: str = ""


# ── the server-authoritative amount validator ──────────────────────────────────

def validate_contribution_amount(requested_paise: Any, *, currency: str = CONTRIBUTION_CURRENCY) -> int:
    """Return the authoritative integer-paise amount, or raise ``ContributionRejected``.

    The browser value is ONLY a request. This is the trusted gate:

      * currency must be exactly INR (compared, never inferred from the amount);
      * the amount must be a genuine ``int`` of minor units - a ``bool``, a float (``10000.5`` is
        fractional paise), a string, or anything ``positive_paise`` refuses is rejected;
      * the amount must match the allowed contribution preset.

    A browser cannot widen this: any non-preset, fractional, or non-INR value is refused here
    before any gateway order is ever created.
    """
    if currency != CONTRIBUTION_CURRENCY:
        raise ContributionRejected("UNSUPPORTED_CURRENCY")
    # positive_paise refuses bools, floats, Decimals that are not integral, strings, and <= 0.
    try:
        amount = positive_paise(requested_paise)
    except (ValueError, TypeError):
        raise ContributionRejected("INVALID_AMOUNT")
    if amount not in CONTRIBUTION_PRESETS_PAISE:
        raise ContributionRejected("AMOUNT_NOT_ALLOWED")
    return amount


def new_contribution_id() -> str:
    """A fresh opaque contribution identifier. UUIDv7, internal, never shown to a customer."""
    return new_uuid7()


def _browser_options(*, key_id: str, gateway_order_id: str, amount_paise: int,
                     currency: str, prefill: Mapping[str, Any],
                     payment_attempt_id: str) -> Dict[str, Any]:
    """Exactly the fields the browser is allowed to receive. Nothing else.

    No secret, no customer id, no full binding, no contribution record. The prefill is restricted
    to the name/email/contact Razorpay's checkout documents, and only values the caller passed
    through from a proven session/profile.
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


def prepare_contribution(*,
                         post_id: str,
                         slug: str,
                         requested_amount_paise: Any,
                         currency: str,
                         request_key: str,
                         now: int,
                         keys_table: Any,
                         create_order: Callable[..., Dict[str, Any]],
                         find_order_by_receipt: Callable[[str], Optional[Dict[str, Any]]],
                         account_mode_of: Callable[[str], str],
                         initiation_enabled: bool,
                         customer_id: str = "",
                         prefill: Optional[Mapping[str, Any]] = None,
                         reserve_attempt: Optional[Callable[[Dict[str, Any]], None]] = None,
                         ) -> PreparedContribution:
    """Validate, gate, and (only if enabled) create and bind the contribution gateway order.

    Mirrors ``website_checkout.prepare_checkout``. The Razorpay client is injected as
    ``create_order`` / ``find_order_by_receipt`` / ``account_mode_of`` so this is testable with
    mocks. ``initiation_enabled`` is an injected test/control seam from the handler; this module
    never reads an environment enable/disable flag and has no default that reads as
    ready.

    ``customer_id`` is optional: a contribution may be made by a signed-in customer or
    anonymously. When present it scopes the request key and is recorded on the attempt; when
    absent the request key is scoped under an anonymous marker. Either way the SERVER decides the
    amount, so an anonymous contribution never weakens payment authority.
    """
    prefill = prefill or {}

    # 1. Validate the post attribution and the SERVER-AUTHORITATIVE amount. The browser value is
    #    only a request; a bad post id, a widened amount, a fractional/non-INR amount all reject
    #    WITHOUT creating anything.
    if not post_id:
        raise ContributionRejected("MISSING_POST")
    if not request_key:
        raise ContributionRejected("MISSING_REQUEST_KEY")
    amount_paise = validate_contribution_amount(requested_amount_paise, currency=currency)

    # The request-key owner: the customer when signed in, else a stable anonymous marker so the
    # key namespace is never empty (which reserve_checkout_request_key refuses).
    owner = customer_id or "anon"

    contribution_id = new_contribution_id()
    attempt_id = payment_attempt.new_payment_attempt_id()

    # 2. Reserve the customer/owner-scoped request key BEFORE any external call. The fingerprint
    #    pins the intent (post, amount, currency) so a resumed key with a changed intent is
    #    refused rather than silently charged for a different amount.
    fingerprint = _intent_fingerprint(post_id, slug, amount_paise, currency)
    reservation, won = order_keys.reserve_checkout_request_key(
        keys_table, customer_id=owner, request_key=request_key,
        intent_fingerprint=fingerprint, payment_attempt_id=attempt_id,
        extra={"purpose": CONTRIBUTION_PURPOSE, "postId": post_id, "amountPaise": amount_paise},
    )
    if not won:
        if str(reservation.get("intentFingerprint") or "") != fingerprint:
            raise ContributionRejected("INTENT_CHANGED")
        attempt_id = str(reservation.get("paymentAttemptId") or attempt_id)
        existing_order_id = str(reservation.get("gatewayOrderId") or "")
        if existing_order_id:
            binding = order_keys.resolve_gateway_order(keys_table, existing_order_id) or {}
            return _ready_from_binding(binding, prefill, reservation.get("contributionId") or "")
        contribution_id = str(reservation.get("contributionId") or contribution_id)

    # 3. Record the authoritative contribution BEFORE anything payable exists, so the webhook can
    #    re-derive the amount from it rather than from the event notes. Reserving it is harmless
    #    even if the gate is off: it carries no money and no gateway order.
    order_keys.reserve_contribution(
        keys_table, contribution_id=contribution_id, post_id=post_id, slug=slug,
        amount_paise=amount_paise, payment_attempt_id=attempt_id, currency=currency)

    # 4. The initiation gate. Off (the default): no gateway order, no payable attempt. No constant
    #    here can force it on - only the injected boolean opens the create path below.
    if not initiation_enabled:
        logger.info('{"event":"blog_contribution_initiation_disabled"}')
        return PreparedContribution(
            status=PAYMENT_INITIATION_DISABLED,
            contribution_id=contribution_id,
            payment_attempt_id=attempt_id,
        )

    # 5. Create the gateway order. The receipt is the request key, unique to this attempt and what
    #    the ambiguity-recovery lookup correlates on. notes carry ONLY opaque ids and the purpose -
    #    they are a convenience, NEVER the authority for the amount (the webhook re-derives it).
    receipt = f"bc_{request_key}"[:order_keys.RAZORPAY_RECEIPT_MAX_LENGTH]
    try:
        order = create_order(
            amount_paise=amount_paise, receipt=receipt,
            notes={"purpose": CONTRIBUTION_PURPOSE, "paymentAttemptId": attempt_id,
                   "contributionId": contribution_id, "postId": post_id},
        )
    except Exception as error:  # noqa: BLE001 - the provider client's RazorpayUnavailable, etc.
        return _recover_ambiguous_create(
            keys_table=keys_table, find_order_by_receipt=find_order_by_receipt,
            receipt=receipt, attempt_id=attempt_id, contribution_id=contribution_id,
            request_key=request_key, amount_paise=amount_paise, currency=currency,
            account_mode_of=account_mode_of, prefill=prefill, error=error,
            reserve_attempt=reserve_attempt, owner=owner, post_id=post_id, slug=slug,
        )

    return _bind_and_ready(
        keys_table=keys_table, order=order, attempt_id=attempt_id,
        contribution_id=contribution_id, request_key=request_key, amount_paise=amount_paise,
        currency=currency, account_mode_of=account_mode_of, prefill=prefill,
        reserve_attempt=reserve_attempt, owner=owner, post_id=post_id, slug=slug,
    )


def _intent_fingerprint(post_id: str, slug: str, amount_paise: int, currency: str) -> str:
    import hashlib
    material = "|".join([post_id, slug or "", str(int(amount_paise)), currency])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bind_and_ready(*, keys_table, order, attempt_id, contribution_id, request_key, amount_paise,
                    currency, account_mode_of, prefill, reserve_attempt, owner, post_id,
                    slug) -> PreparedContribution:
    gateway_order_id = str(order.get("id") or "")
    key_id = str(order.get("key_id") or "")
    if not gateway_order_id or not key_id:
        raise ContributionRejected("PROVIDER_INCOMPLETE")

    mode = account_mode_of(key_id)
    try:
        order_keys.bind_gateway_order(
            keys_table, gateway_order_id=gateway_order_id, payment_attempt_id=attempt_id,
            request_key=request_key, amount_paise=amount_paise, account_key_id=key_id,
            account_mode=mode, currency=currency,
            extra={"purpose": CONTRIBUTION_PURPOSE, "contributionId": contribution_id},
        )
    except order_keys.OrderIdentityUnavailable:
        return PreparedContribution(status=CHECKOUT_AMBIGUOUS, contribution_id=contribution_id,
                                    payment_attempt_id=attempt_id,
                                    gateway_order_id=gateway_order_id, reason="BINDING_SAVE_FAILED")

    order_keys.bind_contribution_gateway_order(
        keys_table, contribution_id=contribution_id, gateway_order_id=gateway_order_id)
    _link_request_key_to_order(keys_table, owner, request_key, gateway_order_id, contribution_id)

    if reserve_attempt is not None:
        attempt = payment_attempt.build(
            customer_id=owner, reference_id=gateway_order_id, amount_paise=amount_paise,
            configuration_name=CONTRIBUTION_MODE, payment_attempt_id=attempt_id, currency=currency)
        attempt["checkoutMode"] = CONTRIBUTION_MODE
        attempt["purpose"] = CONTRIBUTION_PURPOSE
        attempt["providerOrderId"] = gateway_order_id
        attempt["contributionId"] = contribution_id
        reserve_attempt(attempt)

    options = _browser_options(
        key_id=key_id, gateway_order_id=gateway_order_id, amount_paise=amount_paise,
        currency=currency, prefill=prefill, payment_attempt_id=attempt_id)
    return PreparedContribution(status=CHECKOUT_OPTIONS_READY, contribution_id=contribution_id,
                                payment_attempt_id=attempt_id, gateway_order_id=gateway_order_id,
                                options=options)


def _ready_from_binding(binding: Dict[str, Any], prefill, contribution_id: str) -> PreparedContribution:
    gateway_order_id = str(binding.get("gatewayOrderId") or "")
    attempt_id = str(binding.get("paymentAttemptId") or "")
    key_id = str(binding.get("accountKeyId") or "")
    options = _browser_options(
        key_id=key_id, gateway_order_id=gateway_order_id,
        amount_paise=int(binding.get("amountPaise") or 0),
        currency=str(binding.get("currency") or CONTRIBUTION_CURRENCY), prefill=prefill,
        payment_attempt_id=attempt_id)
    return PreparedContribution(
        status=CHECKOUT_OPTIONS_READY,
        contribution_id=str(binding.get("contributionId") or contribution_id),
        payment_attempt_id=attempt_id, gateway_order_id=gateway_order_id, options=options)


def _link_request_key_to_order(keys_table, owner, request_key, gateway_order_id,
                               contribution_id) -> None:
    key = order_keys.REQUEST_KEY_PREFIX + owner + "#" + request_key
    try:
        keys_table.update_item(
            Key={"orderId": key},
            UpdateExpression="SET gatewayOrderId = :g, contributionId = :c",
            ConditionExpression="attribute_exists(orderId)",
            ExpressionAttributeValues={":g": gateway_order_id, ":c": contribution_id},
        )
    except Exception as error:  # noqa: BLE001
        logger.info('{"event":"blog_contribution_requestkey_link_skipped","error":"%s"}',
                    type(error).__name__)


def _recover_ambiguous_create(*, keys_table, find_order_by_receipt, receipt, attempt_id,
                              contribution_id, request_key, amount_paise, currency,
                              account_mode_of, prefill, error, reserve_attempt, owner, post_id,
                              slug) -> PreparedContribution:
    logger.warning('{"event":"blog_contribution_create_ambiguous","error":"%s"}',
                   type(error).__name__)
    try:
        landed = find_order_by_receipt(receipt)
    except Exception as lookup_error:  # noqa: BLE001
        logger.warning('{"event":"blog_contribution_correlation_unreachable","error":"%s"}',
                       type(lookup_error).__name__)
        landed = None
    if landed and str(landed.get("id") or ""):
        return _bind_and_ready(
            keys_table=keys_table, order=landed, attempt_id=attempt_id,
            contribution_id=contribution_id, request_key=request_key, amount_paise=amount_paise,
            currency=currency, account_mode_of=account_mode_of, prefill=prefill,
            reserve_attempt=reserve_attempt, owner=owner, post_id=post_id, slug=slug)
    return PreparedContribution(status=CHECKOUT_AMBIGUOUS, contribution_id=contribution_id,
                                payment_attempt_id=attempt_id, reason="CREATE_UNCONFIRMED")


# ── the browser-result callback ────────────────────────────────────────────────

def verify_contribution_callback(*,
                                 presented_order_id: str,
                                 payment_id: str,
                                 signature: str,
                                 keys_table: Any,
                                 verify_signature: Callable[..., bool],
                                 verify_capture: Callable[[str], Tuple[bool, str, int, str]],
                                 account_mode_of: Optional[Callable[[str], str]] = None,
                                 ) -> ContributionCallbackResult:
    """Verify a browser Standard Checkout result against the SERVER-STORED binding, then capture.

    Identical in shape and trust to ``website_checkout.verify_callback``:

      * resolve the binding by the stored gateway order id; an unknown order id is a mismatch;
      * re-check the stored account/mode (a test-mode binding must never settle live, and a mode we
        cannot positively classify must not settle);
      * HMAC over the STORED order id (never the browser's ``presented_order_id``);
      * a valid signature is only a trigger: require an authoritative captured-payment readback,
        and the captured amount/currency to equal the stored binding, before VERIFIED_PAID.
    """
    binding = order_keys.resolve_gateway_order(keys_table, presented_order_id)
    if not binding:
        return ContributionCallbackResult(status=CALLBACK_BINDING_MISMATCH)
    stored_order_id = str(binding.get("gatewayOrderId") or "")
    attempt_id = str(binding.get("paymentAttemptId") or "")
    contribution_id = str(binding.get("contributionId") or "")
    stored_amount = int(binding.get("amountPaise") or 0)
    stored_currency = str(binding.get("currency") or "")
    stored_mode = str(binding.get("accountMode") or "")
    stored_key_id = str(binding.get("accountKeyId") or "")

    if account_mode_of is not None:
        resolved_mode = account_mode_of(stored_key_id)
        if (not stored_mode or stored_mode == "unknown" or resolved_mode != stored_mode):
            return ContributionCallbackResult(
                status=CALLBACK_BINDING_MISMATCH, contribution_id=contribution_id,
                payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)

    if not verify_signature(stored_order_id=stored_order_id, payment_id=payment_id,
                            signature=signature):
        return ContributionCallbackResult(
            status=CALLBACK_SIGNATURE_INVALID, contribution_id=contribution_id,
            payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)

    captured, provider_payment_id, amount_paise, currency = verify_capture(stored_order_id)
    if not captured:
        return ContributionCallbackResult(
            status=CALLBACK_NOT_CAPTURED, contribution_id=contribution_id,
            payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)
    if amount_paise != stored_amount or currency != stored_currency:
        return ContributionCallbackResult(
            status=CALLBACK_BINDING_MISMATCH, contribution_id=contribution_id,
            payment_attempt_id=attempt_id, gateway_order_id=stored_order_id)

    return ContributionCallbackResult(
        status=CALLBACK_VERIFIED_PAID, contribution_id=contribution_id,
        payment_attempt_id=attempt_id, gateway_order_id=stored_order_id,
        payment_id=provider_payment_id, amount_paise=amount_paise, currency=currency)


# ── the webhook settlement (mirrors the partner_billing.topup pattern) ──────────

def settle_contribution_capture(*,
                                payment: Mapping[str, Any],
                                keys_table: Any,
                                verify_capture: Callable[[str], Tuple[bool, int, str]],
                                quarantine: Callable[[str, str], None],
                                ) -> ContributionSettlement:
    """Settle a captured BLOG_CONTRIBUTION exactly once, re-deriving the amount from stored records.

    Mirrors ``_handle_wallet_topup_captured`` and must NEVER raise into the webhook (a non-2xx
    makes Razorpay retry the whole event). Gates, in order:

      1. A STORED contribution record must exist for the ``contributionId`` the notes name. No
         record -> this is not an authorised contribution -> settle nothing, quarantine. The notes
         are a routing hint only.
      2. The amount is RE-DERIVED from the stored contribution record, NEVER read from
         ``payment.notes`` - a forged notes ``amount`` is ignored. The captured amount is VERIFIED
         against Razorpay's API and must equal the stored record's amount in INR to the paise.
      3. A conditional one-time claim keyed by the payment id is made BEFORE the settle write, so a
         redelivery of the same capture settles exactly once and credits nothing twice.

    A captured-but-unresolvable payment (no record, amount mismatch, wrong currency, not captured)
    is QUARANTINED via the injected ``quarantine(reference, payment_id)`` sink. A BLOG_CONTRIBUTION
    settle creates NO catalogue product or order - it only advances the contribution record.
    """
    notes = payment.get("notes", {}) or {}
    payment_id = str(payment.get("id") or "")
    contribution_id = str(notes.get("contributionId") or "")

    if not payment_id:
        logger.error('{"event":"blog_contribution_no_payment_id","stage":"contribution"}')
        return ContributionSettlement(status=SETTLE_QUARANTINED, reason="NO_PAYMENT_ID")

    # Gate 1: a stored contribution the server actually authorised. The notes are not evidence.
    record = order_keys.resolve_contribution(keys_table, contribution_id) if contribution_id else None
    if not record:
        logger.error('{"event":"blog_contribution_no_record","alert":"CONTRIBUTION_WITHOUT_RECORD",'
                     '"stage":"contribution"}')
        quarantine(contribution_id, payment_id)
        return ContributionSettlement(status=SETTLE_QUARANTINED, payment_id=payment_id,
                                      contribution_id=contribution_id, reason="NO_RECORD")

    # The amount is RE-DERIVED from the stored record, never from the event notes.
    try:
        record_paise = positive_paise(record.get("amountPaise"))
    except (ValueError, TypeError):
        quarantine(contribution_id, payment_id)
        return ContributionSettlement(status=SETTLE_QUARANTINED, payment_id=payment_id,
                                      contribution_id=contribution_id, reason="RECORD_AMOUNT_INVALID")

    # Gate 2: authoritative provider verification. Never the event body.
    captured, provider_paise, provider_currency = verify_capture(payment_id)
    if not captured or str(provider_currency or "") != CONTRIBUTION_CURRENCY:
        quarantine(contribution_id, payment_id)
        return ContributionSettlement(status=SETTLE_QUARANTINED, payment_id=payment_id,
                                      contribution_id=contribution_id, reason="NOT_CAPTURED")
    try:
        provider_paise = positive_paise(provider_paise)
    except (ValueError, TypeError):
        quarantine(contribution_id, payment_id)
        return ContributionSettlement(status=SETTLE_QUARANTINED, payment_id=payment_id,
                                      contribution_id=contribution_id, reason="PROVIDER_AMOUNT_INVALID")
    if provider_paise != record_paise:
        # Money moved, but not for the amount the contribution was created for. A human decides.
        logger.error('{"event":"blog_contribution_amount_mismatch",'
                     '"alert":"CONTRIBUTION_AMOUNT_MISMATCH","stage":"contribution"}')
        quarantine(contribution_id, payment_id)
        return ContributionSettlement(status=SETTLE_QUARANTINED, payment_id=payment_id,
                                      contribution_id=contribution_id, reason="AMOUNT_MISMATCH")

    # Gate 3: idempotency. Claim the settlement BEFORE applying it, so a duplicate delivery that
    # loses the claim settles nothing. A lost claim is the normal duplicate case, not an error.
    if not order_keys.claim_contribution_settlement(
            keys_table, payment_id=payment_id, contribution_id=contribution_id,
            gateway_order_id=str(record.get("gatewayOrderId") or ""), amount_paise=record_paise):
        logger.info('{"event":"blog_contribution_duplicate_skipped","stage":"contribution"}')
        return ContributionSettlement(status=SETTLE_DUPLICATE, payment_id=payment_id,
                                      contribution_id=contribution_id, amount_paise=record_paise)

    # Settle exactly once. This advances the contribution record and does NOTHING else - no
    # catalogue product, no purchase order, no public order number.
    order_keys.mark_contribution_settled(
        keys_table, contribution_id=contribution_id, provider_payment_id=payment_id,
        amount_paise=record_paise)
    logger.info('{"event":"blog_contribution_settled","stage":"contribution"}')
    return ContributionSettlement(status=SETTLE_SETTLED, payment_id=payment_id,
                                  contribution_id=contribution_id, amount_paise=record_paise)


__all__ = [
    "CONTRIBUTION_PURPOSE",
    "CONTRIBUTION_MODE",
    "CONTRIBUTION_CURRENCY",
    "CONTRIBUTION_PRESETS_PAISE",
    "PAYMENT_INITIATION_DISABLED",
    "CHECKOUT_OPTIONS_READY",
    "CHECKOUT_REJECTED",
    "CHECKOUT_AMBIGUOUS",
    "CALLBACK_VERIFIED_PAID",
    "CALLBACK_SIGNATURE_INVALID",
    "CALLBACK_BINDING_MISMATCH",
    "CALLBACK_NOT_CAPTURED",
    "SETTLE_SETTLED",
    "SETTLE_DUPLICATE",
    "SETTLE_QUARANTINED",
    "ContributionRejected",
    "PreparedContribution",
    "ContributionCallbackResult",
    "ContributionSettlement",
    "validate_contribution_amount",
    "new_contribution_id",
    "prepare_contribution",
    "verify_contribution_callback",
    "settle_contribution_capture",
]
