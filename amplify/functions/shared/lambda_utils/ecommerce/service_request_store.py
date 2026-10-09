"""The Phase O-1 request store: one single-table design, resolve-before-generate, conditional writes.

Handler-free on purpose. The table resource, the commerce-keys table and the clock are all
injected, and this module imports no boto3 -- transactions go through
``table.meta.client.transact_write_items`` with a hand-written marshaller, the shape
``gift_card_store`` uses -- so every race below is testable offline against a fake that
evaluates conditions and refuses any expression it does not understand.

THE ONE RULE: A REQUEST EXISTS ONLY AFTER A PAID ORDER EXISTS
-------------------------------------------------------------
Two row families live before payment and carry no public id: ``INTENT#`` (what the customer is
about to buy, and -- for every kind in ``TARGET_REQUIRED_KINDS`` (amendment, Drop Docs, Vault) --
which of THEIR requests it is against, checked BEFORE money
moves, because a refund is not something this system may automate) and ``OPEN#`` (the one open
intent per customer per service, so a reload resumes rather than multiplies). Neither appears on
/orders and neither grants anything.

The ``REQ#`` record and its copyable ``WD-REQ-XXXXXXXX`` id are minted ONLY by ``activate``, and
``activate`` refuses unless the ``PAYMENTATTEMPT#<attemptId>`` claim exists with an order id. That
claim is written by ``order_keys.claim_order_for_payment`` only after ``razorpay_verify`` read an
authenticated capture back from Razorpay, so "no request without a paid order" holds by
construction rather than by a check someone has to remember.

ONE ORDER, ONE REQUEST
----------------------
``ORDER#<internalOrderId>`` is a uniqueness constraint written in the SAME transaction as the
``REQ#`` row. A replayed webhook, a concurrent verify-callback, the /orders self-heal and the
operator script all converge on it: whoever loses the conditional put reads the winner's request
back. No path can create a second request for one order, and nothing here can move money.

HIGH-4: AN OPEN# CLAIM CAN NEVER LOCK A CUSTOMER OUT
---------------------------------------------------
Mint and supersede move ``INTENT#`` and ``OPEN#`` together in ONE ``TransactWriteItems``.
Activation deliberately does NOT include ``OPEN#`` in its transaction -- ``OPEN#`` may since have
moved to a newer intent (a supersede in another tab), and a failed ``OPEN#`` condition would cancel
the activation of a PAID service. So activation consumes ``OPEN#`` as a separate best-effort
conditional write, and the READ side self-heals a missed consume: ``request_intent`` re-reads the
claim's target with ``ConsistentRead=True``, and if it is missing or not ``statusRank == 0`` the
claim is STALE -- conditionally consumed (tied to that stale target, so a claim that has since
moved is left alone), logged as ``STALE_OPEN_CLAIM``, and a fresh intent is minted. Only a target
at rank 0 resolves to the existing intent. No DeleteItem, no TTL.

Logs carry ids only: ``referenceId``, ``orderId``, ``intentId`` and ``publicRequestId`` are our own
identifiers and not secrets, so they are logged in full as correlation ids. Never a phone, and an
exception is logged by type name only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from lambda_utils import customer_auth, media_paths
from lambda_utils.ecommerce import order_keys
from lambda_utils.ecommerce.document_errors import (
    DocumentLimitReached, DocumentNotPrivate, DocumentRejected)
from lambda_utils.ecommerce.service_requests import (
    DROP_DOCS, INTENT_ID_RE, NOT_OFFERED_KINDS, PUBLIC_REQUEST_ID_ALPHABET,
    PUBLIC_REQUEST_ID_ENTROPY, PUBLIC_REQUEST_ID_PREFIX, PUBLIC_REQUEST_ID_RE,
    REQUEST_AMENDMENT, SERVICE_CURRENCY, SERVICE_KIND_BY_VARIANT, SERVICE_LINE_MAX_PAISE,
    SERVICE_LINE_MIN_PAISE, SERVICE_NOT_OFFERED, SERVICE_UNKNOWN_CHOICE,
    SERVICE_VARIANT_BY_KIND, SUBMIT_REQUEST, TARGET_REQUIRED_KINDS, VAULT, ServiceRejected)
from lambda_utils.identifiers import new_uuid7

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "stack-wecare-digital-ServiceRequestsTable"
KEY_ATTR = "requestId"
CUSTOMER_INDEX = "customerId-createdAt-index"
ORDER_INDEX = "orderId-index"

INTENT_PREFIX = "INTENT#"
OPEN_PREFIX = "OPEN#"
REQUEST_PREFIX = "REQ#"
ORDER_PREFIX = "ORDER#"
REQNO_PREFIX = "REQNO#"
#: A document attached to a paid Drop Docs request: ``DOC#<reqInternal>#<sha256>``. The
#: content hash is the key, so a replayed attach converges on the row that already exists
#: instead of registering the same bytes twice. See `attach_document`.
DOC_PREFIX = "DOC#"

#: A sha256 hex digest, and nothing else. A malformed digest would produce a ``DOC#`` key
#: that no replay could ever converge on, which is the one property this family exists for.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: How many documents one Drop Docs request may hold.
#:
#: There IS a hard ceiling whether or not we choose one: ``documentSha256s`` is an attribute
#: on the ``REQ#`` row, and at roughly 70 marshalled bytes per digest the 400 KB DynamoDB
#: item limit arrives somewhere near five thousand. Past that, every further attach fails
#: with a validation error nobody can read. 200 is far below it, well above any plausible
#: set of documents for one request, and keeps `list_documents` -- one ``GetItem`` per
#: digest, deliberately not a Query -- bounded at a readable cost.
#:
#: Enforced on the read side, so the refusal is legible. A burst of concurrent attaches can
#: therefore overshoot by the number in flight, which is bounded and nowhere near the item
#: limit; the alternative is a transaction condition whose failure is indistinguishable from
#: an ownership failure, and answering "not yours" to a cap is worse than overshooting by a
#: handful.
MAX_DOCUMENTS_PER_REQUEST = 200

#: Intent lifecycle. A rank, so "only rank 0 is resumable" is one integer comparison.
INTENT_OPEN, INTENT_OPEN_RANK = "OPEN", 0
INTENT_ABANDONED, INTENT_ABANDONED_RANK = "ABANDONED", 5
INTENT_CONSUMED, INTENT_CONSUMED_RANK = "CONSUMED", 10

#: The request lifecycle. NOT payment vocabulary: paid-ness is the existence of the paid-order
#: claim, never a word stored here.
REQUEST_SUBMITTED, REQUEST_SUBMITTED_RANK = "SUBMITTED", 10

#: Activation outcomes.
ACTIVATED = "ACTIVATED"
ALREADY_ACTIVE = "ALREADY_ACTIVE"
NOT_A_SERVICE_ORDER = "NOT_A_SERVICE_ORDER"
NOT_PAID = "NOT_PAID"
UNMATCHED = "UNMATCHED"

RESOLVE_ATTEMPTS = 4
ACTIVATE_ATTEMPTS = 5
LIST_MAX = 20
CURSOR_MAX_CHARS = 512


class ServiceIdentityUnavailable(RuntimeError):
    """A read or a write this store depends on failed. 503, never a pass and never a guess."""


@dataclass(frozen=True)
class ActivationOutcome:
    outcome: str
    request_public_id: str = ""
    order_number: str = ""
    kind: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"outcome": self.outcome, "requestId": self.request_public_id or None,
                "orderNumber": self.order_number or None, "kind": self.kind or None}


# ── low-level helpers ─────────────────────────────────────────────────────────

def _error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return str((response.get("Error") or {}).get("Code") or "")
    return ""


def _is_conditional(error: BaseException) -> bool:
    return _error_code(error) == "ConditionalCheckFailedException"


def _is_cancellation(error: BaseException) -> bool:
    return (type(error).__name__ == "TransactionCanceledException"
            or _error_code(error) == "TransactionCanceledException")


def _reason_codes(error: BaseException) -> List[str]:
    """``CancellationReasons[].Code``. A TOP-LEVEL sibling of ``Error`` in botocore's response."""
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return []
    return [str((reason or {}).get("Code") or "")
            for reason in (response.get("CancellationReasons") or [])]


def _marshal(value: Any) -> Dict[str, Any]:
    """AttributeValue for the four types these transactions carry. A float is refused outright."""
    if isinstance(value, bool):                 # BEFORE int: bool IS an int
        return {"BOOL": value}
    if type(value) is int:
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
        return {"L": [{"S": entry} for entry in value]}
    raise TypeError(f"cannot marshal {type(value).__name__}")


def _marshal_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _marshal(value) for key, value in item.items()}


def _int(value: Any) -> Optional[int]:
    """An exact integer from a stored number, or None. ``Decimal(str(v))``, never ``float``."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001 - anything unparseable is simply not a number
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def _get(table: Any, key: str) -> Optional[Dict[str, Any]]:
    try:
        return table.get_item(Key={KEY_ATTR: key}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001
        raise ServiceIdentityUnavailable(
            f"could not read a request row: {type(error).__name__}") from error


def _transact(table: Any, items: List[Dict[str, Any]]) -> None:
    table.meta.client.transact_write_items(TransactItems=items)


def _put(table_name: str, item: Dict[str, Any], condition: str,
         values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"TableName": table_name, "Item": _marshal_item(item),
                             "ConditionExpression": condition}
    if values:
        entry["ExpressionAttributeValues"] = _marshal_item(values)
    return {"Put": entry}


def _now(clock: Optional[Callable[[], float]]) -> int:
    return int((clock or time.time)())


def mint_public_request_id() -> str:
    """``WD-REQ-`` + 8 symbols, from ``secrets`` (never ``random``: SnapStart freezes its state)."""
    tail = "".join(secrets.choice(PUBLIC_REQUEST_ID_ALPHABET)
                   for _ in range(PUBLIC_REQUEST_ID_ENTROPY))
    return PUBLIC_REQUEST_ID_PREFIX + tail


def _fingerprint(kind: str, variant_id: str, target_request_id: str,
                 original_order_id: str = "") -> str:
    """What makes two intents for the same thing the same intent.

    NO AMOUNT, since 2026-10-08. Wix owns the price now, so an amount in here would mean a Wix
    price edit between two visits produced a DIFFERENT fingerprint for the same request -- and
    the customer's one open intent would be superseded by an identical one for no reason the
    customer caused. The identity of an intent is what service it is and what it is for.
    """
    material = "|".join([
        kind, variant_id, SERVICE_CURRENCY, target_request_id, original_order_id
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _intent_view(intent: Dict[str, Any]) -> Dict[str, Any]:
    """The intent on the wire. ``amountPaise`` is ``None``: PRICED AT CHECKOUT, by Wix.

    The key stays in the payload rather than being dropped, so the shape remains a superset of
    what `src/lib/serviceRequests.ts` reads, and ``None`` says "not priced yet" where a ``0``
    would have claimed the service is free.
    """
    return {"intentId": str(intent[KEY_ATTR])[len(INTENT_PREFIX):],
            "kind": str(intent.get("kind") or ""),
            "variantId": str(intent.get("variantId") or ""),
            "amountPaise": None,
            "currency": str(intent.get("currency") or ""),
            "targetRequestId": str(intent.get("targetPublicRequestId") or "") or None,
            "originalOrderReferenceId": str(intent.get("parentOrderReferenceId") or "") or None,
            "originalOrderNumber": str(intent.get("parentOrderNumber") or "") or None}


# ── public ids ────────────────────────────────────────────────────────────────

def resolve_public(table: Any, identity: customer_auth.CustomerIdentity,
                   public_id: Any) -> Dict[str, Any]:
    """The caller's own ``REQ#`` row for a public id, or raise ``CustomerNotAuthorized``.

    A bad shape, no pointer, no row and somebody else's row all raise the SAME exception, so the
    endpoint is not an existence oracle for request ids.
    """
    value = str(public_id or "").strip().upper()
    if not PUBLIC_REQUEST_ID_RE.match(value):
        raise customer_auth.CustomerNotAuthorized("resource does not exist or is not yours")
    pointer = _get(table, REQNO_PREFIX + value)
    target = str((pointer or {}).get("targetRequestId") or "")
    row = _get(table, target) if target.startswith(REQUEST_PREFIX) else None
    return customer_auth.authorize_resource(identity, row, owner_field="customerId")


# ── before payment: the intent ────────────────────────────────────────────────

def _mint_items(table_name: str, *, intent: Dict[str, Any], open_key: str,
                owner: str, fingerprint: str, now: int) -> List[Dict[str, Any]]:
    claim = {KEY_ATTR: open_key, "ownerCustomerId": owner,
             "targetIntentId": intent[KEY_ATTR][len(INTENT_PREFIX):],
             "intentFingerprint": fingerprint, "isConsumed": False, "claimedAt": now}
    return [
        _put(table_name, intent, f"attribute_not_exists({KEY_ATTR})"),
        _put(table_name, claim, f"attribute_not_exists({KEY_ATTR}) OR isConsumed = :t",
             {":t": True}),
    ]


def _new_intent(*, intent_id: str, owner: str, kind: str, variant_id: str,
                target: Optional[Dict[str, Any]], original_order: Optional[Dict[str, Any]],
                fingerprint: str, now: int) -> Dict[str, Any]:
    """The stored intent. NO ``amountPaise``: an intent is pre-payment and Wix prices the line.

    Storing a figure here would be storing a guess, and a guess on a money row is the thing that
    later gets compared against reality and refuses an honest payment.
    """
    intent: Dict[str, Any] = {
        KEY_ATTR: INTENT_PREFIX + intent_id, "ownerCustomerId": owner, "kind": kind,
        "variantId": variant_id, "currency": SERVICE_CURRENCY,
        "intentFingerprint": fingerprint, "status": INTENT_OPEN, "statusRank": INTENT_OPEN_RANK,
        "consumedOrderIds": [], "createdAt": now, "updatedAt": now,
    }
    if target is not None:
        intent["targetRequestId"] = str(target[KEY_ATTR])
        intent["targetPublicRequestId"] = str(target.get("publicRequestId") or "")
    if target is not None and target.get('vaultFileId'):
        intent.update({k: target[k] for k in ('vaultFileId', 'vaultFileName', 'vaultOwnerPhone')})
    if original_order is not None:
        intent["parentOrderId"] = str(original_order.get("orderId") or "")
        intent["parentOrderNumber"] = str(original_order.get("orderNumber") or "")
        intent["parentOrderReferenceId"] = str(original_order.get("referenceId") or "")
    return intent


def request_intent(table: Any, identity: customer_auth.CustomerIdentity, kind: Any,
                   target_public_id: Any = None, *,
                   clock: Optional[Callable[[], float]] = None,
                   new_id: Callable[[], str] = new_uuid7,
                   vault_file: Optional[Dict[str, Any]] = None,
                   original_order: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve the caller's one open intent for this service, or mint one. Never charges anything.

    Raises ``ServiceRejected`` (unknown or not-offered kind, or a missing/unexpected target),
    ``CustomerNotAuthorized`` (a target that is missing, not the caller's, or not a Submit
    Request -- one identical refusal), or ``ServiceIdentityUnavailable``.

    Every kind in ``TARGET_REQUIRED_KINDS`` -- amendment, Drop Docs and Vault -- takes a target
    through the SAME branch, so none of them can acquire a different ownership rule by accident.
    """
    kind = str(kind or "").strip().upper()
    if kind in NOT_OFFERED_KINDS:
        raise ServiceRejected(SERVICE_NOT_OFFERED)
    variant_id = SERVICE_VARIANT_BY_KIND.get(kind)
    if not variant_id:
        raise ServiceRejected(SERVICE_UNKNOWN_CHOICE)
    owner = identity.customer_id
    if not owner:
        raise customer_auth.CustomerNotAuthorized("session carries no customer id")

    target: Optional[Dict[str, Any]] = None
    if kind == SUBMIT_REQUEST:
        if target_public_id or vault_file is not None:
            raise ServiceRejected("SERVICE_TARGET_UNEXPECTED")
        if (not isinstance(original_order, dict)
                or str(original_order.get("customerId") or "") != owner
                or not str(original_order.get("orderId") or "")
                or not str(original_order.get("referenceId") or "")):
            raise ServiceRejected("SERVICE_ORIGINAL_ORDER_REQUIRED")
    elif original_order is not None:
        raise ServiceRejected("SERVICE_TARGET_UNEXPECTED")

    if vault_file is not None:
        if (kind != VAULT or target_public_id or vault_file.get('ownerCustomerId') != owner
                or vault_file.get('status') != 'active' or not vault_file.get('fileId')):
            raise customer_auth.CustomerNotAuthorized('resource does not exist or is not yours')
        if vault_file.get('vaultPaymentStatus') == 'PAID' or vault_file.get('vaultAccessGrantId'):
            raise ServiceRejected('VAULT_ALREADY_PAID')
        target = {KEY_ATTR: 'FILE#' + str(vault_file['fileId']),
                  'vaultFileId': str(vault_file['fileId']),
                  'vaultFileName': str(vault_file.get('displayName') or 'Document'),
                  'vaultOwnerPhone': str(vault_file.get('ownerPhone') or '')}
    elif kind in TARGET_REQUIRED_KINDS:
        if not target_public_id:
            raise ServiceRejected("SERVICE_TARGET_REQUIRED")
        target = resolve_public(table, identity, target_public_id)
        if str(target.get("kind") or "") != SUBMIT_REQUEST:
            raise customer_auth.CustomerNotAuthorized("resource does not exist or is not yours")
    elif target_public_id:
        raise ServiceRejected("SERVICE_TARGET_UNEXPECTED")

    target_internal = str(target[KEY_ATTR]) if target is not None else ""
    original_order_internal = (
        str(original_order.get("orderId") or "") if original_order is not None else ""
    )
    fingerprint = _fingerprint(
        kind, variant_id, target_internal, original_order_internal
    )
    open_key = f"{OPEN_PREFIX}{owner}#{variant_id}"
    table_name = table.name

    for _attempt in range(RESOLVE_ATTEMPTS):
        now = _now(clock)
        claim = _get(table, open_key)
        try:
            if claim is None or claim.get("isConsumed") is True:
                intent = _new_intent(intent_id=new_id(), owner=owner, kind=kind,
                                     variant_id=variant_id, target=target,
                                     original_order=original_order,
                                     fingerprint=fingerprint, now=now)
                _transact(table, _mint_items(table_name, intent=intent, open_key=open_key,
                                             owner=owner, fingerprint=fingerprint, now=now))
                logger.info(json.dumps({"event": "service_intent_minted",
                                        "intentId": _intent_view(intent)["intentId"],
                                        "kind": kind}))
                return _intent_view(intent)

            stale_id = str(claim.get("targetIntentId") or "")
            existing = _get(table, INTENT_PREFIX + stale_id) if stale_id else None
            rank = _int((existing or {}).get("statusRank"))
            if (existing is None or rank != INTENT_OPEN_RANK
                    or str(existing.get("ownerCustomerId") or "") != owner):
                # STALE. Consume it -- tied to THIS stale target, so a claim another request has
                # since moved is left alone -- then mint on the next pass. A lost condition means
                # the claim moved under us: re-read rather than guess.
                try:
                    table.put_item(
                        Item={KEY_ATTR: open_key, "ownerCustomerId": owner,
                              "targetIntentId": stale_id, "isConsumed": True,
                              "claimedAt": _int(claim.get("claimedAt")) or now,
                              "staleRepairedAt": now},
                        ConditionExpression="targetIntentId = :stale AND isConsumed = :f",
                        ExpressionAttributeValues={":stale": stale_id, ":f": False})
                except Exception as error:  # noqa: BLE001
                    if _is_conditional(error):
                        continue
                    raise ServiceIdentityUnavailable(
                        f"could not repair a stale claim: {type(error).__name__}") from error
                logger.warning(json.dumps({
                    "event": "stale_open_claim", "alert": "STALE_OPEN_CLAIM",
                    "staleIntentId": stale_id, "targetPresent": existing is not None,
                    "targetRank": rank}))
                continue

            if str(existing.get("intentFingerprint") or "") == fingerprint:
                return _intent_view(existing)

            # A different target request: SUPERSEDE, in ONE transaction. The frozen original
            # order must be carried onto the superseding intent exactly as the mint path does
            # (see line ~398); _new_intent made original_order a required keyword-only arg, so
            # omitting it here raised TypeError -> ServiceIdentityUnavailable (a live 503 on every
            # intent supersede). `original_order` is in scope as the request_intent parameter.
            intent = _new_intent(intent_id=new_id(), owner=owner, kind=kind,
                                 variant_id=variant_id, target=target,
                                 original_order=original_order,
                                 fingerprint=fingerprint, now=now)
            new_claim = {KEY_ATTR: open_key, "ownerCustomerId": owner,
                         "targetIntentId": intent[KEY_ATTR][len(INTENT_PREFIX):],
                         "intentFingerprint": fingerprint, "isConsumed": False, "claimedAt": now}
            _transact(table, [
                {"Update": {
                    "TableName": table_name,
                    "Key": _marshal_item({KEY_ATTR: INTENT_PREFIX + stale_id}),
                    "UpdateExpression": "SET #s = :ab, statusRank = :abr, updatedAt = :now",
                    "ConditionExpression": "statusRank = :zero",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": _marshal_item({
                        ":ab": INTENT_ABANDONED, ":abr": INTENT_ABANDONED_RANK,
                        ":now": now, ":zero": INTENT_OPEN_RANK}),
                }},
                _put(table_name, intent, f"attribute_not_exists({KEY_ATTR})"),
                _put(table_name, new_claim, "targetIntentId = :old", {":old": stale_id}),
            ])
            logger.info(json.dumps({"event": "service_intent_superseded",
                                    "abandonedIntentId": stale_id,
                                    "intentId": _intent_view(intent)["intentId"]}))
            return _intent_view(intent)
        except ServiceIdentityUnavailable:
            raise
        except Exception as error:  # noqa: BLE001
            if _is_cancellation(error):
                logger.info(json.dumps({"event": "service_intent_race",
                                        "reasons": _reason_codes(error)}))
                continue
            raise ServiceIdentityUnavailable(
                f"could not record a service intent: {type(error).__name__}") from error
    raise ServiceIdentityUnavailable("service intent resolution kept losing races")


# ── after payment: activation ─────────────────────────────────────────────────

def _unmatched(reason: str, *, reference_id: str, order_id: str) -> ActivationOutcome:
    logger.error(json.dumps({"event": "service_activation_refused",
                             "alert": "PAID_SERVICE_UNMATCHED", "reason": reason,
                             "referenceId": reference_id, "orderId": order_id}))
    return ActivationOutcome(UNMATCHED)


def _existing_activation(table: Any, order_id: str) -> Optional[ActivationOutcome]:
    pointer = _get(table, ORDER_PREFIX + order_id)
    if not pointer:
        return None
    return ActivationOutcome(ALREADY_ACTIVE,
                             request_public_id=str(pointer.get("publicRequestId") or ""),
                             order_number=str(pointer.get("orderNumber") or ""),
                             kind=str(pointer.get("kind") or ""))


def _consume_open(table: Any, *, owner: str, variant_id: str, intent_id: str, now: int) -> None:
    """Best effort. ANY failure is swallowed: ``request_intent``'s HIGH-4 gate repairs it."""
    try:
        table.put_item(
            Item={KEY_ATTR: f"{OPEN_PREFIX}{owner}#{variant_id}", "ownerCustomerId": owner,
                  "targetIntentId": intent_id, "isConsumed": True, "claimedAt": now,
                  "consumedAt": now},
            ConditionExpression="targetIntentId = :iid",
            ExpressionAttributeValues={":iid": intent_id})
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({"event": "service_open_claim_consume_skipped",
                                   "intentId": intent_id, "error": type(error).__name__}))


def activate(table: Any, keys_table: Any, *, reference_id: str = "",
             payment_attempt_id: str = "", caller_customer_id: Optional[str] = None,
             clock: Optional[Callable[[], float]] = None,
             mint_public_id: Callable[[], str] = mint_public_request_id,
             new_id: Callable[[], str] = new_uuid7) -> ActivationOutcome:
    """Create the ONE request for a paid services order, or say why not. Idempotent. Never charges.

    Every link is re-read and must agree: ``PAYREF#<ref>`` (customer, ``serviceLine``, attempt)
    -> ``PAYMENTATTEMPT#<attempt>`` claim (order id, order number) -> ``INTENT#`` (owner, variant,
    committed paise, INR). Anything that disagrees AFTER the money moved is ``UNMATCHED`` with a
    ``PAID_SERVICE_UNMATCHED`` alert for a human, never a guess and never a refund.
    """
    try:
        if not reference_id and payment_attempt_id:
            claim_by_attempt = order_keys.resolve_order_for_payment(keys_table, payment_attempt_id)
            reference_id = str((claim_by_attempt or {}).get("referenceId") or "")
            if not reference_id:
                return ActivationOutcome(NOT_PAID if not claim_by_attempt else NOT_A_SERVICE_ORDER)
        payref = order_keys.resolve_payment_reference(keys_table, reference_id) if reference_id \
            else None
        line = (payref or {}).get("serviceLine")
        if not isinstance(line, dict):
            return ActivationOutcome(NOT_A_SERVICE_ORDER)
        owner = str(payref.get("customerId") or "")
        if caller_customer_id is not None and (not owner or owner != caller_customer_id):
            return ActivationOutcome(NOT_A_SERVICE_ORDER)
        attempt_id = str(payref.get("paymentAttemptId") or "")
        if payment_attempt_id and payment_attempt_id != attempt_id:
            return ActivationOutcome(NOT_A_SERVICE_ORDER)
        claim = order_keys.resolve_order_for_payment(keys_table, attempt_id) if attempt_id \
            else None
    except order_keys.OrderIdentityUnavailable as error:
        raise ServiceIdentityUnavailable(
            f"could not read the paid-order claim: {type(error).__name__}") from error

    order_id = str((claim or {}).get("orderIdRef") or "")
    if not order_id:
        # No order exists for this attempt, so no request may exist either.
        logger.info(json.dumps({"event": "service_activation_not_paid",
                                "referenceId": reference_id}))
        return ActivationOutcome(NOT_PAID)
    claimed_reference = str(claim.get("referenceId") or "")
    if claimed_reference and claimed_reference != reference_id:
        return _unmatched("CLAIM_REFERENCE_MISMATCH", reference_id=reference_id, order_id=order_id)
    order_number = str(claim.get("orderNumber") or "")

    already = _existing_activation(table, order_id)
    if already is not None:
        return already

    intent_id = str(line.get("intentId") or "")
    variant_id = str(line.get("variantId") or "")
    kind = SERVICE_KIND_BY_VARIANT.get(variant_id)
    if not INTENT_ID_RE.match(intent_id) or kind is None:
        return _unmatched("SERVICE_LINE_INVALID", reference_id=reference_id, order_id=order_id)
    intent = _get(table, INTENT_PREFIX + intent_id)
    if intent is None:
        return _unmatched("INTENT_MISSING", reference_id=reference_id, order_id=order_id)
    if str(intent.get("ownerCustomerId") or "") != owner:
        return _unmatched("CUSTOMER_MISMATCH", reference_id=reference_id, order_id=order_id)
    if (str(intent.get("variantId") or "") != variant_id
            or str(intent.get("kind") or "") != kind or str(line.get("kind") or "") != kind):
        return _unmatched("VARIANT_MISMATCH", reference_id=reference_id, order_id=order_id)
    # WHAT WAS CHARGED IS WHAT WIX PRICED, so there is no committed figure left to agree with.
    # The check is therefore on the SHAPE of the recorded amount, not on its value: a positive
    # integer inside the same catastrophe rail `assert_service_line_price` applied at checkout.
    # ``AMOUNT_MISMATCH`` is kept verbatim as the reason code -- every historical
    # PAID_SERVICE_UNMATCHED alert and any operator runbook already matches that string, and a
    # rename would silently stop matching them.
    paid_paise = _int(line.get("paise"))
    if paid_paise is None or not SERVICE_LINE_MIN_PAISE <= paid_paise <= SERVICE_LINE_MAX_PAISE:
        return _unmatched("AMOUNT_MISMATCH", reference_id=reference_id, order_id=order_id)
    if str(intent.get("currency") or "") != SERVICE_CURRENCY:
        return _unmatched("CURRENCY_MISMATCH", reference_id=reference_id, order_id=order_id)
    target_internal = str(intent.get("targetRequestId") or "")
    file_bound_vault = kind == VAULT and bool(intent.get('vaultFileId')) and target_internal == 'FILE#' + str(intent['vaultFileId'])
    if kind == SUBMIT_REQUEST and not str(intent.get("parentOrderId") or ""):
        return _unmatched("ORIGINAL_ORDER_MISSING", reference_id=reference_id, order_id=order_id)
    if kind in TARGET_REQUIRED_KINDS and not file_bound_vault and not target_internal.startswith(REQUEST_PREFIX):
        # The condition is generic across `TARGET_REQUIRED_KINDS`; the reason code is not,
        # and must not be. ``AMENDMENT_TARGET_MISSING`` is kept verbatim for an amendment
        # because it is what every historical PAID_SERVICE_UNMATCHED alert and any operator
        # runbook already says, and a renamed code would silently stop matching them. A Drop
        # Docs or Vault payment reports ``TARGET_MISSING`` instead -- telling whoever reads a
        # stuck Vault payment that an *amendment* target is missing sends them looking for a
        # service the customer never bought.
        return _unmatched(
            "AMENDMENT_TARGET_MISSING" if kind == REQUEST_AMENDMENT else "TARGET_MISSING",
            reference_id=reference_id, order_id=order_id)

    previously = [str(entry) for entry in (intent.get("consumedOrderIds") or [])]
    if previously and order_id not in previously:
        # Two paid attempts on one intent: the customer paid twice and gets two requests. Loud.
        logger.error(json.dumps({"event": "service_intent_paid_twice",
                                 "alert": "DUPLICATE_PAID_INTENT", "intentId": intent_id,
                                 "orderId": order_id, "referenceId": reference_id}))

    table_name = table.name
    request_internal = REQUEST_PREFIX + new_id()
    for _attempt in range(ACTIVATE_ATTEMPTS):
        now = _now(clock)
        public_id = mint_public_id()
        request = {
            KEY_ATTR: request_internal, "kind": kind, "publicRequestId": public_id,
            "customerId": owner, "createdAt": now, "updatedAt": now,
            "status": REQUEST_SUBMITTED, "statusRank": REQUEST_SUBMITTED_RANK,
            "serviceVariantId": variant_id, "amountPaise": paid_paise,
            "currency": SERVICE_CURRENCY, "orderId": order_id, "orderNumber": order_number,
            "paymentAttemptId": attempt_id, "referenceId": reference_id, "intentId": intent_id,
            "paidAt": now,
        }
        if kind == SUBMIT_REQUEST:
            request["parentOrderId"] = str(intent.get("parentOrderId") or "")
            request["parentOrderNumber"] = str(intent.get("parentOrderNumber") or "")
            request["parentOrderReferenceId"] = str(intent.get("parentOrderReferenceId") or "")
        if kind in TARGET_REQUIRED_KINDS:
            request["targetRequestId"] = target_internal
            request["targetPublicRequestId"] = str(intent.get("targetPublicRequestId") or "")
        if file_bound_vault:
            request.update({k: intent[k] for k in ('vaultFileId', 'vaultFileName', 'vaultOwnerPhone')})
            request['vaultStatus'] = 'AWAITING_ACCESS'
        pointer = {KEY_ATTR: ORDER_PREFIX + order_id, "ownerCustomerId": owner,
                   "targetRequestId": request_internal, "publicRequestId": public_id,
                   "orderNumber": order_number, "kind": kind, "boundAt": now}
        reserved = {KEY_ATTR: REQNO_PREFIX + public_id, "ownerCustomerId": owner,
                    "targetRequestId": request_internal, "reservedAt": now}
        items = [
            _put(table_name, request, f"attribute_not_exists({KEY_ATTR})"),
            _put(table_name, pointer, f"attribute_not_exists({KEY_ATTR})"),
            _put(table_name, reserved, f"attribute_not_exists({KEY_ATTR})"),
            {"Update": {
                "TableName": table_name,
                "Key": _marshal_item({KEY_ATTR: INTENT_PREFIX + intent_id}),
                "UpdateExpression": ("SET #s = :c, statusRank = :cr, updatedAt = :now, "
                                     "consumedOrderIds = list_append("
                                     "if_not_exists(consumedOrderIds, :empty), :oid)"),
                "ConditionExpression": "ownerCustomerId = :sub",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": _marshal_item({
                    ":c": INTENT_CONSUMED, ":cr": INTENT_CONSUMED_RANK, ":now": now,
                    ":empty": [], ":oid": [order_id], ":sub": owner}),
            }},
        ]
        if kind in TARGET_REQUIRED_KINDS and not file_bound_vault:
            items.append({"ConditionCheck": {
                "TableName": table_name,
                "Key": _marshal_item({KEY_ATTR: target_internal}),
                "ConditionExpression": "customerId = :sub AND kind = :submit",
                "ExpressionAttributeValues": _marshal_item({":sub": owner,
                                                            ":submit": SUBMIT_REQUEST}),
            }})
        try:
            _transact(table, items)
        except Exception as error:  # noqa: BLE001
            if not _is_cancellation(error):
                raise ServiceIdentityUnavailable(
                    f"could not activate a request: {type(error).__name__}") from error
            reasons = _reason_codes(error)
            failed = {index for index, code in enumerate(reasons)
                      if code == "ConditionalCheckFailed"}
            if 1 in failed:
                # A concurrent activation won the order pointer. Adopt its request.
                winner = _existing_activation(table, order_id)
                if winner is not None:
                    return winner
                continue
            if failed & {3, 4}:
                return _unmatched("INTENT_OR_TARGET_CONDITION", reference_id=reference_id,
                                  order_id=order_id)
            if 0 in failed:
                request_internal = REQUEST_PREFIX + new_id()
            # 2 (public id collision), or a transient conflict: mint again and retry.
            logger.info(json.dumps({"event": "service_activation_retry", "reasons": reasons}))
            continue

        logger.info(json.dumps({"event": "service_request_created", "publicRequestId": public_id,
                                "kind": kind, "orderId": order_id, "referenceId": reference_id,
                                "intentId": intent_id}))
        _consume_open(table, owner=owner, variant_id=variant_id, intent_id=intent_id, now=now)
        return ActivationOutcome(ACTIVATED, request_public_id=public_id,
                                 order_number=order_number, kind=kind)
    raise ServiceIdentityUnavailable("request activation kept losing races")


# ── the customer's own list ───────────────────────────────────────────────────

def _encode_cursor(last_key: Optional[Dict[str, Any]]) -> str:
    if not isinstance(last_key, dict):
        return ""
    request_id = str(last_key.get(KEY_ATTR) or "")
    created_at = _int(last_key.get("createdAt"))
    if not request_id.startswith(REQUEST_PREFIX) or created_at is None:
        return ""
    raw = json.dumps({"r": request_id, "c": created_at}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(raw: Any) -> Dict[str, Any]:
    """``{requestId, createdAt}`` from an opaque cursor, or raise ``ValueError``."""
    value = str(raw or "")
    if not value or len(value) > CURSOR_MAX_CHARS:
        raise ValueError("cursor is not one of ours")
    try:
        decoded = json.loads(base64.urlsafe_b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii")).decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        raise ValueError("cursor does not decode") from error
    request_id = str((decoded or {}).get("r") or "") if isinstance(decoded, dict) else ""
    created_at = _int((decoded or {}).get("c")) if isinstance(decoded, dict) else None
    if not request_id.startswith(REQUEST_PREFIX) or created_at is None:
        raise ValueError("cursor carries no usable position")
    return {KEY_ATTR: request_id, "createdAt": created_at}


def _project(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"requestId": str(row.get("publicRequestId") or ""),
            "kind": str(row.get("kind") or ""),
            "status": str(row.get("status") or ""),
            "createdAt": _int(row.get("createdAt")),
            "orderNumber": str(row.get("orderNumber") or ""),
            "targetRequestId": str(row.get("targetPublicRequestId") or "") or None,
            "fileId": str(row.get('vaultFileId') or '') or None,
            "fileName": str(row.get('vaultFileName') or '') or None,
            "deliveryStatus": str(row.get('vaultStatus') or '') or None}


def list_for_customer(table: Any, identity: customer_auth.CustomerIdentity, *,
                      limit: int = LIST_MAX,
                      cursor: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], str]:
    """One ``Query`` on the caller's OWN partition of GSI-1. Another customer's rows are unreachable.

    The partition is the proven Cognito ``sub`` and nothing the request supplies; a cursor can at
    worst name a position inside the caller's own partition.
    """
    bounded = max(1, min(int(limit or LIST_MAX), LIST_MAX))
    kwargs: Dict[str, Any] = {
        "IndexName": CUSTOMER_INDEX,
        "KeyConditionExpression": "#c = :c",
        "ExpressionAttributeNames": {"#c": "customerId"},
        "ExpressionAttributeValues": {":c": identity.customer_id},
        "ScanIndexForward": False,
        "Limit": bounded,
    }
    if cursor:
        kwargs["ExclusiveStartKey"] = {"customerId": identity.customer_id,
                                       "createdAt": cursor["createdAt"],
                                       KEY_ATTR: cursor[KEY_ATTR]}
    try:
        result = table.query(**kwargs) or {}
    except Exception as error:  # noqa: BLE001
        raise ServiceIdentityUnavailable(
            f"could not list requests: {type(error).__name__}") from error
    rows = [_project(row) for row in (result.get("Items") or [])
            if isinstance(row, dict) and str(row.get(KEY_ATTR) or "").startswith(REQUEST_PREFIX)]
    return rows, _encode_cursor(result.get("LastEvaluatedKey"))


# ── documents attached to a paid Drop Docs request ────────────────────────────
#
# THE GATE IS HERE, NOT AT ARRIVAL. A WhatsApp upload lands under ``o/``, which CloudFront
# serves unauthenticated, so nothing may be registered as a customer document until its
# object is proven to live under ``secure/``. `attach_document` therefore checks ownership,
# then kind, then gatedness, and only then writes -- in that order, so a non-gated key can
# never leave a row behind. `dropdocs_storage.promote_to_secure` does the copying and HEADs
# the destination; this function refuses to trust its answer without re-checking the key.
#
# A ``storageKey`` IS NOT AN ENTITLEMENT, AND CANNOT BECOME ONE. The destination key is a
# pure function of the bytes (``secure/u/dropdocs/wecare-digital-<sha256><ext>``), which is
# what makes a replay converge instead of duplicating -- but it also means two different
# customers who attach identical bytes land on ONE shared S3 object, reachable from both of
# their ``DOC#`` rows. Authorization is therefore on the ROW and never on the key: both
# `attach_document` and `list_documents` go through `_resolve_dropdocs_request` and
# `list_documents` re-checks ``ownerCustomerId`` on every row it returns. Nothing in this
# phase can download a ``DOC#`` (D7 keeps Vault release out of scope); when a release path
# is built it must look the row up and compare its owner. "The caller knows the key" is not
# a statement about who the document belongs to.


def _document_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """The client-facing shape of a document row.

    ``sourceKey`` is deliberately ABSENT. The row keeps it as provenance -- a WhatsApp
    arrival's public key is how an operator traces where a document came from -- but
    handing a key under ``o/`` back to a browser would publish the very URL the promotion
    exists to stop mattering. Nothing in this module returns it.
    """
    return {"documentId": str(row.get("sha256") or ""),
            "storageKey": str(row.get("storageKey") or ""),
            "contentType": str(row.get("contentType") or ""),
            "sizeBytes": _int(row.get("sizeBytes")),
            "attachedAt": _int(row.get("attachedAt")),
            "publicSourceRetained": bool(row.get("publicSourceRetained"))}


def _resolve_dropdocs_request(table: Any, identity: customer_auth.CustomerIdentity,
                              public_request_id: Any) -> Dict[str, Any]:
    """The caller's own paid Drop Docs request, or the ONE identical refusal.

    A bad id, a missing request, somebody else's request and a request of the wrong kind
    all raise the same ``CustomerNotAuthorized``, so this is not an existence oracle for
    request ids or for which of a customer's services were bought.
    """
    request = resolve_public(table, identity, public_request_id)
    if str(request.get("kind") or "") != DROP_DOCS:
        raise customer_auth.CustomerNotAuthorized("resource does not exist or is not yours")
    return request


def resolve_dropdocs_request(table: Any, identity: customer_auth.CustomerIdentity,
                             public_request_id: Any) -> Dict[str, Any]:
    """`_resolve_dropdocs_request`, exposed so a caller can refuse BEFORE it moves bytes.

    Exists for exactly one reason. `attach_document` resolves the target itself and always
    will -- that re-check inside the transaction is the authority, and nothing here replaces
    it. But a caller that copies a document into ``secure/`` and only then discovers the
    request is missing, foreign or the wrong kind has already written an object that no
    ``DOC#`` row references, that no role may delete (`s3:DeleteObject` is granted nowhere,
    deliberately) and that no ``system-cleanup`` TTL covers -- a permanent orphan of up to
    100 MB produced by a refusal.

    So the locker calls this first and promotes nothing if it raises. Two reads instead of
    one is the whole cost; the refusal is identical, because it is the same function.
    """
    return _resolve_dropdocs_request(table, identity, public_request_id)


def attach_document(table: Any, identity: customer_auth.CustomerIdentity,
                    public_request_id: Any, *, storage_key: str, sha256: str,
                    content_type: str, size_bytes: Any, source_key: str,
                    public_source_retained: bool,
                    clock: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """Register one document against the caller's paid Drop Docs request. Idempotent.

    Raises ``CustomerNotAuthorized`` (missing, not the caller's, or not a Drop Docs
    request), ``DocumentRejected`` (the digest is not a sha256, or the byte count is absent
    or negative -- permanently invalid input, not a privacy failure),
    ``DocumentNotPrivate`` (``storage_key`` is not under the gated root),
    ``DocumentLimitReached`` (the request already holds `MAX_DOCUMENTS_PER_REQUEST`) or
    ``ServiceIdentityUnavailable``. Every one of them leaves the table untouched: there is
    no partial state in which a row exists for an object that is still only reachable under
    ``o/``.

    The write is a two-item transaction rather than a bare put, so the row and the request's
    index of it land together or not at all. Item 0 is the ``DOC#`` row under
    ``attribute_not_exists`` -- a replay of the same bytes loses it and reads the winner
    back, which is resolve-before-generate. Item 1 re-asserts ownership AND kind on the
    ``REQ#`` row inside the transaction, the same discipline `activate` uses for its target,
    so a request that changed hands between the read and the write cannot be written to.
    """
    request = _resolve_dropdocs_request(table, identity, public_request_id)

    digest = str(sha256 or "").strip().lower()
    if not SHA256_RE.match(digest):
        # Shape, not privacy. Separate exceptions because the HTTP layer answers 400 here
        # and 503 below, and "please try again" on a malformed digest is a lie.
        raise DocumentRejected("a document must be identified by its sha256")
    if not media_paths.is_gated(storage_key):
        # The fail-closed gate. Checked here, after ownership and kind and BEFORE any write,
        # because a row pointing at a public object is worse than no row at all.
        raise DocumentNotPrivate("a document key must live under the gated root")

    owner = identity.customer_id
    request_internal = str(request[KEY_ATTR])
    document_key = f"{DOC_PREFIX}{request_internal}#{digest}"
    size = _int(size_bytes)
    if size is None or size < 0:
        raise DocumentRejected("a document must carry an exact byte count")

    held = [str(entry or "").strip().lower() for entry in (request.get("documentSha256s")
                                                           or [])]
    if digest not in held and len(held) >= MAX_DOCUMENTS_PER_REQUEST:
        # A replay of a digest already held still goes through, so idempotency survives at
        # the ceiling rather than turning into a refusal the caller cannot resolve.
        raise DocumentLimitReached(
            f"a request may hold at most {MAX_DOCUMENTS_PER_REQUEST} documents")

    now = _now(clock)
    document = {
        KEY_ATTR: document_key, "ownerCustomerId": owner,
        "targetRequestId": request_internal,
        "targetPublicRequestId": str(request.get("publicRequestId") or ""),
        "storageKey": media_paths.canonical(storage_key), "sha256": digest,
        "contentType": str(content_type or ""), "sizeBytes": size,
        # Provenance only, never returned to a client. See `_document_view`.
        "sourceKey": media_paths.canonical(source_key),
        "publicSourceRetained": bool(public_source_retained), "attachedAt": now,
    }
    items = [
        _put(table.name, document, f"attribute_not_exists({KEY_ATTR})"),
        {"Update": {
            "TableName": table.name,
            "Key": _marshal_item({KEY_ATTR: request_internal}),
            "UpdateExpression": ("SET updatedAt = :now, documentSha256s = list_append("
                                 "if_not_exists(documentSha256s, :empty), :digest)"),
            "ConditionExpression": "customerId = :sub AND kind = :dropdocs",
            "ExpressionAttributeValues": _marshal_item({
                ":now": now, ":empty": [], ":digest": [digest], ":sub": owner,
                ":dropdocs": DROP_DOCS}),
        }},
    ]
    try:
        _transact(table, items)
    except Exception as error:  # noqa: BLE001
        if not _is_cancellation(error):
            raise ServiceIdentityUnavailable(
                f"could not attach a document: {type(error).__name__}") from error
        failed = {index for index, code in enumerate(_reason_codes(error))
                  if code == "ConditionalCheckFailed"}
        if 1 in failed:
            # The request stopped being the caller's Drop Docs request between the read and
            # the write. Same refusal as every other ownership failure.
            raise customer_auth.CustomerNotAuthorized(
                "resource does not exist or is not yours") from error
        if 0 in failed:
            existing = _get(table, document_key)
            if existing is not None:
                logger.info(json.dumps({"event": "dropdocs_document_already_attached",
                                        "publicRequestId": str(request.get("publicRequestId")
                                                               or ""),
                                        "sha256": digest}))
                return _document_view(existing)
        raise ServiceIdentityUnavailable("document attach kept losing races") from error

    logger.info(json.dumps({"event": "dropdocs_document_attached",
                            "publicRequestId": str(request.get("publicRequestId") or ""),
                            "sha256": digest, "storageKey": document["storageKey"],
                            "sizeBytes": size}))
    return _document_view(document)


def list_documents(table: Any, identity: customer_auth.CustomerIdentity,
                   public_request_id: Any) -> List[Dict[str, Any]]:
    """The caller's own documents for one Drop Docs request.

    Read through the digest index on the request row rather than a scan, and rather than a
    GSI: putting ``DOC#`` rows into ``customerId-createdAt-index`` would make them compete
    with ``REQ#`` rows for the page limit in `list_for_customer`, so a customer with enough
    documents would see an empty request list. Each row's owner is re-checked, so a digest
    that somehow named another customer's row yields nothing.

    One ``GetItem`` per digest, which is affordable only because the digest list is capped
    at `MAX_DOCUMENTS_PER_REQUEST`. The cap is read here too, so a row that overshot it in a
    concurrent burst still reads back at a bounded cost instead of growing the page without
    limit.
    """
    request = _resolve_dropdocs_request(table, identity, public_request_id)
    request_internal = str(request[KEY_ATTR])
    documents: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in (request.get("documentSha256s") or [])[:MAX_DOCUMENTS_PER_REQUEST]:
        digest = str(entry or "").strip().lower()
        if not SHA256_RE.match(digest) or digest in seen:
            continue
        seen.add(digest)
        row = _get(table, f"{DOC_PREFIX}{request_internal}#{digest}")
        if row and str(row.get("ownerCustomerId") or "") == identity.customer_id:
            documents.append(_document_view(row))
    return documents
