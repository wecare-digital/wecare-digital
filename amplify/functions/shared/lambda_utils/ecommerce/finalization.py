"""Verified money persists separately from recoverable order finalization.

No blind retries of external effects. Wix adapters retain PENDING markers for
uncertain writes. Initiation and writeback gates remain independent.

The Razorpay leg is the amount the PROVIDER confirmed
-----------------------------------------------------
Everything about money here turns on one distinction. `attempt['amountPaise']` is the frozen
PAYABLE - what the customer agreed to. `verified_captured_paise` is what Razorpay's own
authenticated readback said it took. On a 100%-Razorpay order the two are equal, and
`order_creation.reconcile_payment` proves it with an exact integer comparison. Under SPLIT TENDER
they are not equal, and recording the payable as the Razorpay capture over-reports the charge and
breaks Wix payment reconciliation. So the verified amount is a REQUIRED argument rather than a
derived one: it is never computed as the payable minus another tender, because comparing two
numbers written by the same code in the same request proves the split was internally consistent,
which is arithmetic rather than evidence. `gift_card_settlement.is_fully_settled` states that rule
and this module honours it.
"""
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from . import order_channel, payment_attempt, wix_writeback

#: Modes whose attempts may become an internal order. 'WEBSITE_RAZORPAY_STANDARD' mirrors
#: `website_checkout.CHECKOUT_MODE_WEBSITE`; the literal avoids an import cycle between two
#: sibling ecommerce modules and is pinned to that constant by a test. Membership rather than
#: equality because the single-mode check refused every direct-Razorpay order.
ACCEPTED_CHECKOUT_MODES = frozenset({'WIX_HEADLESS', 'WEBSITE_RAZORPAY_STANDARD'})

#: SEAM-G13: the amount Razorpay's own readback confirmed, written here and nowhere else.
#: `gift_card_settlement` declares this obligation as `RAZORPAY_VERIFIED_PAISE_ATTR` and
#: deliberately EXCLUDES the attribute from its own closed evidence set, because it belongs to the
#: Razorpay leg's writer - which is this module. A LITERAL rather than an import: `finalization`
#: is inside `ecommerce/checkout/handler.py`'s import closure and importing
#: `gift_card_settlement` here would break the closure assertion that keeps the gift-card modules
#: out of checkout. A test pins the two equal, which is the same discipline
#: `ACCEPTED_CHECKOUT_MODES` and the handler's `_TWO_LEG_ATTR` already use.
VERIFIED_CAPTURED_PAISE_ATTR = 'verifiedCapturedPaise'

#: Every OTHER tender leg's recorded paise, as attribute names on the attempt row. This module is
#: deliberately tender-SOURCE-agnostic: it takes the Razorpay leg as its amount and reconciles it
#: against the frozen payable using whatever of these are present, performing the identical
#: arithmetic for each, so a second tender is one entry here and no new branch. The gift-card
#: entry is a literal for the same import-closure reason as above, and a test pins it to
#: `gift_card_settlement.REDEEMED_PAISE_ATTR`.
#:
#: BOTH gift-card systems are listed, and listing only the first is a live defect rather than an
#: omission:
#:
#:   giftCardRedeemedPaise  - gift_card_settlement.REDEEMED_PAISE_ATTR, the WECARE store's card.
#:   wixGiftCardRedeemPaise - the Wix-NATIVE card, which is the tender the WEBSITE checkout
#:                            actually uses. `website_checkout._bind_and_ready` writes it
#:                            UNCONDITIONALLY, including the value 0.
#:
#: With only the first listed, a 150000-paise basket with 50000 redeemed and 100000 captured finds
#: no listed leg, computes 100000 != 150000 and stages NEEDS_RECONCILIATION for EVERY split-tender
#: website order - the one shape this graft exists for.
#:
#: Because `wixGiftCardRedeemPaise` is written unconditionally, PRESENCE IS NOT EVIDENCE of a
#: second leg; a non-zero VALUE is. Every consumer here tests the value, never the key.
#:
#: Summing both is correct because they are two different systems with two different writers. If
#: some future path ever wrote both for one redemption the sum would double-count and the order
#: would fail closed, which is the right direction for a disagreement about how money arrived.
OTHER_TENDER_PAISE_ATTRS = ('giftCardRedeemedPaise', 'wixGiftCardRedeemPaise')


def _conditional(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException'


def integer_paise(value):
    """Integer paise from a stored or passed value, or `None` when it is not exactly that.

    Rejects `bool` (a `bool` is an `int` in Python and `True` would read as one paise), rejects
    `float` outright, and accepts a `Decimal` only when it is integral - which is how DynamoDB
    hands back a number. Fractional paise do not exist.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        try:
            if value.is_finite() and value == value.to_integral_value():
                return int(value)
        except (InvalidOperation, ValueError):
            return None
        return None
    if isinstance(value, str):
        # DynamoDB never returns a number as a string, but a hand-written fixture might.
        try:
            return integer_paise(Decimal(value))
        except (InvalidOperation, ValueError):
            return None
    return None


def other_tender_paise(attempt):
    """Total paise on this attempt funded by a tender `accept_paid` does not settle.

    `None` when any listed leg is present but not readable as integer paise - a value we cannot
    read is not the same as zero, and the caller must fail closed on it.

    Public because the handler's `_finalize` asks the same question before calling `accept_paid`,
    and it must ask it of the same list `_tenders_reconcile` uses. A handler re-listing the
    attributes is how a two-leg guard comes to name an attribute production never writes.
    """
    total = 0
    for name in OTHER_TENDER_PAISE_ATTRS:
        if name not in attempt:
            continue
        leg = integer_paise(attempt.get(name))
        if leg is None:
            return None
        total += leg
    return total


def record_paid(attempts, attempt, provider_payment_id, verified_captured_paise):
    """Monotonic, binding-conditional paid state before order-number allocation.

    Writes the provider payment id and the VERIFIED CAPTURED AMOUNT in one conditional expression,
    because they are the same fact recorded at the same instant: the readback that proved the
    money moved said both. A replay carrying the same pair is idempotent; a replay carrying a
    different amount is refused by the DATABASE rather than overwriting the evidence.

    Zero is accepted. That is not laxity - a fully gift-card-funded order has no Razorpay leg, and
    `gift_card_settlement.is_fully_settled` requires the term to be PRESENT (`if verified is None:
    return False`) to close `verified + redeemed == payable`. `money.positive_paise`, which
    refuses zero, is applied at the Wix call instead, which `accept_paid` skips entirely when
    there is no leg to record.
    """
    verified = integer_paise(verified_captured_paise)
    if verified is None or verified < 0:
        raise ValueError('verified captured amount must be non-negative integer paise')
    now = int(time.time())
    attempts.update_item(Key={'paymentAttemptId': attempt['paymentAttemptId']},
        UpdateExpression='SET #s = :paid, attemptRank = :rank, paidAt = if_not_exists(paidAt, :now), '
                         'updatedAt = :now, verifiedProviderPaymentId = :provider, '
                         + VERIFIED_CAPTURED_PAISE_ATTR + ' = :verifiedPaise',
        # The two evidence fields move together or not at all. Nested rather than two sibling OR
        # groups so a second delivery that agrees on the provider id but NOT on the amount is
        # refused: with two independent groups, a matching amount alone would satisfy the
        # condition.
        ConditionExpression='attribute_exists(paymentAttemptId) AND referenceId = :ref AND '
                            '(attribute_not_exists(verifiedProviderPaymentId) OR '
                            '(verifiedProviderPaymentId = :provider AND '
                            + VERIFIED_CAPTURED_PAISE_ATTR + ' = :verifiedPaise))',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':paid': payment_attempt.PAYMENT_PAID, ':rank': 100,
            ':now': now, ':provider': provider_payment_id, ':ref': attempt['referenceId'],
            ':verifiedPaise': verified})


def _stage(attempts, attempt_id, stage, **fields):
    names = {'#stage': 'finalizationStage'}
    values = {':stage': stage, ':paid': payment_attempt.PAYMENT_PAID}
    update = ['#stage = :stage']
    for index, (key, value) in enumerate(fields.items()):
        names[f'#f{index}'], values[f':v{index}'] = key, value
        update.append(f'#f{index} = :v{index}')
    attempts.update_item(Key={'paymentAttemptId': attempt_id},
        UpdateExpression='SET ' + ', '.join(update),
        ConditionExpression='#s = :paid',
        ExpressionAttributeNames={**names, '#s': 'status'}, ExpressionAttributeValues=values)


def _tenders_reconcile(attempt, razorpay_paise):
    """True when the Razorpay leg plus every other recorded tender equals the frozen payable.

    EXACT integer equality, no tolerance. A one-paise discrepancy means two writers disagree
    about how much of one basket was funded by what, and the safe answer is to write nothing
    external and leave a human a paid attempt to look at.
    """
    payable = integer_paise(attempt.get('amountPaise'))
    if payable is None:
        return False
    other = other_tender_paise(attempt)
    if other is None:
        return False
    return razorpay_paise + other == payable


def wix_cart_id(attempt, snapshot):
    """The Cart V2 cart behind this attempt, or `''`.

    MEASURED: the attempt row does NOT carry `wixCartId` - `payment_attempt.build` writes
    `cartId` only when a caller supplies one, and the direct-Razorpay create does not. The cart id
    IS on the frozen snapshot as `cart.id`, which `website_checkout._bounded_snapshot` retains
    even in its reduced projection. Both are read, in that order; neither is guessed, and an
    absent id stages for reconciliation rather than inventing a cart to close.
    """
    direct = str(attempt.get('wixCartId') or attempt.get('cartId') or '')
    if direct:
        return direct
    cart = snapshot.get('cart') if isinstance(snapshot, dict) else None
    return str(cart.get('id') or '') if isinstance(cart, dict) else ''


def accept_paid(*, attempts, orders, keys, attempt, outcome, verified_captured_paise):
    """Create the complete internal order and resume only documented writes.

    This never creates a payable invoice. Receipts/notifications have their own
    guarded adapters and must be enabled only after their contracts are attested.

    `verified_captured_paise` is REQUIRED and is the provider's own confirmed capture - on the
    browser leg, `website_checkout.verify_callback`'s `CallbackResult.amount_paise`. It is what
    reaches Wix as the Razorpay payment record, and it is what `record_paid` stores as SEAM-G13's
    evidence. It is never the order total and never a subtraction.
    """
    if not outcome.get('hasOrder') or attempt.get('checkoutMode') not in ACCEPTED_CHECKOUT_MODES:
        raise ValueError('verified standalone order identity required')
    provider_id = outcome.get('providerPaymentId') or attempt.get('verifiedProviderPaymentId')
    if not provider_id:
        raise ValueError('verified provider payment id required')
    # Validated BEFORE `record_paid` writes anything: `_stage` is conditional on the attempt
    # already being PAYMENT_PAID, so there is no stage to write until `record_paid` has run, and a
    # verified amount we cannot read is a fault to raise rather than a state to record. The
    # handler's wrapper alarms on it and still returns the already-reserved order number.
    razorpay_paise = integer_paise(verified_captured_paise)
    if razorpay_paise is None or razorpay_paise < 0:
        raise ValueError('verified captured amount must be non-negative integer paise')
    record_paid(attempts, attempt, provider_id, razorpay_paise)
    snapshot = attempt.get('purchasedSnapshot')
    if not isinstance(snapshot, dict) or not snapshot.get('cart') or not attempt.get('snapshotHash'):
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='PURCHASED_SNAPSHOT_MISSING')
        return
    order = {'orderId': outcome['orderId'], 'orderNumber': outcome['orderNumber'],
             'customerId': attempt['customerId'], 'paymentAttemptId': attempt['paymentAttemptId'],
             'referenceId': attempt['referenceId'], 'providerPaymentId': provider_id,
             'amountPaise': attempt['amountPaise'], 'currency': attempt['currency'],
             'purchasedSnapshot': deepcopy(snapshot), 'snapshotHash': attempt['snapshotHash'],
             # The record says which flow produced it, rather than hard-coding one of them.
             'checkoutMode': attempt['checkoutMode'], 'paymentStatus': 'PAYMENT_PAID',
             # WHERE the order came from, beside HOW it settled, and deliberately a SECOND field
             # rather than a third `checkoutMode`: `checkoutMode` gates finalisation through
             # `ACCEPTED_CHECKOUT_MODES` above, so a channel spelled into it would be a new
             # settlement path instead of a label. `order_channel.canonical` is total, so an
             # attempt row with no channel - which is every attempt written before this landed -
             # reads as `website`. That default is TRUE and not a guess: no WhatsApp order can
             # exist, because the hand-off that would create one is gated off.
             'channel': order_channel.canonical(attempt.get('channel')),
             'finalizationStage': 'INTERNAL_ORDER_CREATED', 'createdAt': int(time.time())}
    try:
        orders.put_item(Item=order, ConditionExpression='attribute_not_exists(orderId)')
    except Exception as error:
        if not _conditional(error):
            raise
        current = orders.get_item(Key={'orderId': outcome['orderId']}, ConsistentRead=True).get('Item') or {}
        if any(current.get(key) != order[key] for key in
               ('customerId', 'paymentAttemptId', 'providerPaymentId', 'snapshotHash', 'orderNumber')):
            raise ValueError('internal order association conflict')
    # A public number may now be returned. Its order record has actually committed.
    _stage(attempts, attempt['paymentAttemptId'], 'INTERNAL_ORDER_CREATED',
           orderId=order['orderId'], orderNumber=order['orderNumber'])
    # The tender identity, checked BEFORE the writeback gate rather than inside it: a tender sum
    # that does not close is a fact about money, not a fact about Wix, and it must be recorded
    # whether or not writeback is ever enabled.
    if not _tenders_reconcile(attempt, razorpay_paise):
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='TENDER_SUM_MISMATCH')
        return
    # Retain paid state even when the site-bound write contract is unavailable.
    # The payload must come from an attested mapping; never guess Wix stock effects.
    wix_payload = attempt.get('wixOrderPayload')
    if not wix_writeback.is_enabled() or not wix_payload:
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='WIX_WRITE_CONTRACT_REQUIRED')
        return
    if isinstance(wix_payload, dict) and wix_payload.get(wix_writeback.PAYLOAD_REDUCED_FLAG):
        # A payload trimmed to fit the attempt row has lost its catalog references. Sending it
        # would create a Wix order that names no products, so it fails closed.
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='WIX_PAYLOAD_REDUCED')
        return
    from lambda_utils import wix_ecom
    try:
        wix = wix_writeback.create_wix_order(keys, wix_ecom._request,
            order_id=order['orderId'], order_payload=wix_payload)
        _stage(attempts, attempt['paymentAttemptId'], 'WIX_ORDER_CREATED', wixOrderId=wix['wixOrderId'])
        if razorpay_paise:
            wix_writeback.record_external_payment(keys, wix_ecom._request,
                order_id=order['orderId'], wix_order_id=wix['wixOrderId'],
                provider_transaction_id=provider_id,
                # THE RAZORPAY LEG, not the order total. Under split tender these differ, and
                # recording the total here over-reports the capture to Wix.
                amount_paise=razorpay_paise)
            _stage(attempts, attempt['paymentAttemptId'], 'EXTERNAL_PAYMENT_RECORDED')
        else:
            # A fully gift-card-funded order has no Razorpay leg. `money.positive_paise` refuses
            # zero, so calling the writeback would raise INSIDE it rather than record nothing;
            # the other tender's own writer records its leg.
            _stage(attempts, attempt['paymentAttemptId'], 'EXTERNAL_PAYMENT_NOT_APPLICABLE')
        # ── GRAFT 5, INSIDE the outer try, so `wix` is provably bound ──────────────────
        # The THIRD step of the external-order sequence, which this repo did the first two of and
        # not the third - so a paid cart was never closed and stayed live for the customer.
        # `mark_cart_completed` cannot charge: it sets `orderPlaced` and attaches the order id.
        #
        # INSIDE, and the placement is load-bearing rather than stylistic. At function-body level
        # - i.e. after the outer `except`, which stages and does not return - a
        # `WixWritebackPending` from `create_wix_order` leaves `wix` UNBOUND, so the first call
        # here raises `UnboundLocalError`. That is a `NameError`, so the nested except tuple below
        # would NOT catch it: it would escape `accept_paid`, the handler's wrapper would alarm
        # PAID_BUT_NO_ORDER_RECORD, and a correct recoverable WIX_READBACK_REQUIRED stage would
        # become an alarm. Nesting puts the step where its precondition is provable by reading
        # upward.
        cart_id = wix_cart_id(attempt, snapshot)
        if not cart_id:
            _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
                   finalizationReason='WIX_CART_ID_REQUIRED')
            return
        try:
            wix_writeback.mark_cart_completed(keys, wix_ecom._request,
                order_id=order['orderId'], cart_id=cart_id, wix_order_id=wix['wixOrderId'])
            _stage(attempts, attempt['paymentAttemptId'], 'WIX_CART_COMPLETED')
        except (wix_writeback.WixWritebackPending, wix_writeback.WixWritebackDisabled,
                ValueError):
            # Its OWN nested try, deliberately. The order and the external payment record have
            # already committed, and a failure to close the cart must not look like a failure to
            # record the payment. `ValueError` is in the tuple because `mark_cart_completed`
            # refuses a cart id it cannot parse as a UUID. An unclosed cart is recoverable by
            # readback; it is never a reason to repeat the order or the payment record above it.
            _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
                   finalizationReason='WIX_CART_READBACK_REQUIRED')
    except (wix_writeback.WixWritebackPending, wix_writeback.WixWritebackDisabled):
        # UNCHANGED, and it still does not need a `return`: it is the last statement either way.
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='WIX_READBACK_REQUIRED')
