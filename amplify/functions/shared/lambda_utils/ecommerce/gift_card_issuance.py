"""Issue gift cards for a PAID gift-card purchase, exactly once per order.

The BUY side's settlement step. When an order whose cart contained a gift-card SKU is finalised,
each purchased gift card must be ISSUED — a liability we take on, with a fresh secret code the
customer receives. This module is the orchestrator: it reads the FROZEN purchased snapshot (the
authority on what was paid for and at what face value), and for each gift-card unit it claims an
idempotency marker and, only on a won claim, mints the card.

EXACTLY ONCE, THE WAY THE REST OF THE PAYMENT PATH IS
-----------------------------------------------------
`gift_card_store.issue` mints a RANDOM code and is not naturally idempotent — a second call makes
a second liability. So the exactly-once guarantee lives in a conditional claim BEFORE the issue:
`GCISSUE#<orderId>#<index>` is `put` with `attribute_not_exists`, and the issue happens only when
that put wins. A redelivered webhook loses the claim and mints nothing. The claim row records the
`giftCardId` and `codeLast4` of the card it minted, so a crash between the claim and the issue is
recoverable (re-entry resumes the same index) and a human can audit which cards an order produced.
This mirrors `redemption.commit_redemption`'s payment-id-keyed claim: the money/liability move is
gated by a conditional write, never by a pre-read.

NEVER RAISES INTO THE MONEY PATH
--------------------------------
Called after an order is finalised, like `service_request_dispatch`. A failure to issue must not
undo a captured payment, so every failure is logged and swallowed and the result reports what it
managed to do. Recovery is by re-entry (the claim markers make it safe) and by a reconcile script.

The face value and quantity come from the FROZEN snapshot via `gift_card_product`, never a client
field. Integer paise throughout.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from lambda_utils.ecommerce import gift_card_product, gift_card_store

logger = logging.getLogger(__name__)

#: The idempotency-marker key prefix on the GiftCardsTable (the same table the cards live on, so
#: no new store and no new grant). One marker per issued unit: `GCISSUE#<orderId>#<index>`.
ISSUE_MARKER_PREFIX = "GCISSUE#"

#: Who the system records as the issuer of a purchased card, distinct from a staff Operator.
ISSUED_BY_SYSTEM = "SYSTEM:gift-card-purchase"


def _marker_key(order_id: str, index: int) -> str:
    return ISSUE_MARKER_PREFIX + str(order_id) + "#" + str(index)


def _claim(table: Any, key: str, *, order_id: str, now: int) -> bool:
    """Win the right to issue ONE card for this (order, index). False if already claimed."""
    try:
        table.put_item(
            Item={gift_card_store.KEY_ATTRIBUTE: key, "kind": "GIFT_CARD_ISSUE_MARKER",
                  "sourceOrderId": str(order_id), "createdAt": now},
            ConditionExpression=f"attribute_not_exists({gift_card_store.KEY_ATTRIBUTE})")
        return True
    except Exception as error:  # noqa: BLE001
        if gift_card_store._is_conditional_failure(error):
            return False
        raise


def _record_on_marker(table: Any, key: str, *, gift_card_id: str, code_last4: str,
                      now: int) -> None:
    """Record which card this marker minted, for recovery and audit. Best-effort."""
    try:
        table.update_item(
            Key={gift_card_store.KEY_ATTRIBUTE: key},
            UpdateExpression="SET giftCardId = :id, codeLast4 = :l4, issuedAt = :at",
            ExpressionAttributeValues={":id": gift_card_id, ":l4": code_last4, ":at": now})
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({"event": "gift_card_issue_marker_record_failed",
                                   "error": type(error).__name__}))


def issue_for_paid_order(
    cards_table: Any,
    *,
    order_id: str,
    purchased_snapshot: Any,
    pepper: str,
    issued_to_contact_id: str = "",
    env: Optional[Dict[str, str]] = None,
    clock=None,
) -> List[Dict[str, Any]]:
    """Issue every gift card a PAID order bought, exactly once. Returns the newly-issued cards.

    `purchased_snapshot` is the order's frozen `purchasedSnapshot`; `gift_card_product` reads the
    paid gift-card lines and their face values out of it. For a line of quantity N, N separate
    cards are issued (N codes), each at the line's face value, each behind its own claim marker so
    a partial failure resumes cleanly. Returns a list of `{code, giftCardId, codeLast4,
    faceValuePaise}` for the cards THIS call minted (empty on a full replay, or for a non-gift-card
    order, or when no gift-card SKU is configured).

    NEVER RAISES: a failure to issue a particular card is logged and skipped; the caller (a
    finalised order) must not be undone by it.
    """
    purchases = gift_card_product.gift_card_purchases(purchased_snapshot, env=env)
    if not purchases or not order_id:
        return []
    import time as _time
    now = int(clock() if clock else _time.time())
    issued: List[Dict[str, Any]] = []
    index = 0
    for purchase in purchases:
        face = int(purchase["faceValuePaise"])
        for _unit in range(int(purchase["quantity"])):
            marker = _marker_key(order_id, index)
            index += 1
            try:
                if not _claim(cards_table, marker, order_id=order_id, now=now):
                    # Already issued on an earlier delivery — the exactly-once guarantee holding.
                    continue
                card = gift_card_store.issue(
                    cards_table, initial_value_paise=face, pepper=pepper,
                    issued_to_contact_id=issued_to_contact_id or None,
                    source_order_id=order_id, created_by=ISSUED_BY_SYSTEM,
                    clock=(clock or (lambda: now)))
                _record_on_marker(cards_table, marker,
                                  gift_card_id=card["card"]["giftCardId"],
                                  code_last4=card["card"]["codeLast4"], now=now)
                issued.append({"code": card["code"], "giftCardId": card["card"]["giftCardId"],
                               "codeLast4": card["card"]["codeLast4"], "faceValuePaise": face})
                logger.info(json.dumps({"event": "gift_card_issued_for_purchase",
                                        "orderId": order_id, "giftCardId": card["card"]["giftCardId"],
                                        "faceValuePaise": face}))
            except Exception as error:  # noqa: BLE001 — never fail the finalised order
                logger.error(json.dumps({"event": "gift_card_issue_for_order_failed",
                                         "orderId": order_id, "index": index - 1,
                                         "error": type(error).__name__}))
    return issued


__all__ = ["ISSUE_MARKER_PREFIX", "ISSUED_BY_SYSTEM", "issue_for_paid_order"]
