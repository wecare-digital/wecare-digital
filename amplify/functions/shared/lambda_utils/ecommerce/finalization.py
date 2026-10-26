"""Verified money persists separately from recoverable order finalization.

No blind retries of external effects. The internal order record is the authoritative artifact:
`accept_paid` writes it, stages INTERNAL_ORDER_CREATED, reconciles the tenders and then stages
ORDER_FINALIZED, the only terminal success stage. Initiation stays gated independently.

The Razorpay leg is the amount the PROVIDER confirmed
-----------------------------------------------------
Everything about money here turns on one distinction. `attempt['amountPaise']` is the frozen
PAYABLE - what the customer agreed to. `verified_captured_paise` is what Razorpay's own
authenticated readback said it took. On a 100%-Razorpay order the two are equal, and
`order_creation.reconcile_payment` proves it with an exact integer comparison. Under SPLIT TENDER
they are not equal, and recording the payable as the Razorpay capture over-reports the charge and
breaks payment reconciliation. So the verified amount is a REQUIRED argument rather than a
derived one: it is never computed as the payable minus another tender, because comparing two
numbers written by the same code in the same request proves the split was internally consistent,
which is arithmetic rather than evidence. `retired secondary tender_settlement.is_fully_settled` states that rule
and this module honours it.
"""
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from . import order_channel, order_delivery, order_record, payment_attempt

#: Modes whose attempts may become an internal order. Native checkout and the established
#: website Razorpay settlement marker are the only accepted modes.
ACCEPTED_CHECKOUT_MODES = frozenset({'AWS_NATIVE', 'WEBSITE_RAZORPAY_STANDARD', 'WHATSAPP_NATIVE_CART'})

#: SEAM-G13: the amount Razorpay's own readback confirmed, written here and nowhere else.
#: `retired secondary tender_settlement` declares this obligation as `RAZORPAY_VERIFIED_PAISE_ATTR` and
#: deliberately EXCLUDES the attribute from its own closed evidence set, because it belongs to the
#: Razorpay leg's writer - which is this module. A LITERAL rather than an import: `finalization`
#: is inside `ecommerce/checkout/handler.py`'s import closure and importing
#: `retired secondary tender_settlement` here would break the closure assertion that keeps the retired secondary tender modules
#: out of checkout. A test pins the two equal, which is the same discipline
#: `ACCEPTED_CHECKOUT_MODES` and the handler's `_TWO_LEG_ATTR` already use.
VERIFIED_CAPTURED_PAISE_ATTR = 'verifiedCapturedPaise'

#: Every OTHER tender leg's recorded paise, as attribute names on the attempt row. This module is
#: deliberately tender-SOURCE-agnostic: it takes the Razorpay leg as its amount and reconciles it
#: against the frozen payable using whatever of these are present, performing the identical
#: arithmetic for each, so a second tender is one entry here and no new branch. The retired secondary tender
#: entry is a literal for the same import-closure reason as above, and a test pins it to
#: `retired secondary tender_settlement.REDEEMED_PAISE_ATTR`.
#:
#:   retired secondary tenderRedeemedPaise  - retired secondary tender_settlement.REDEEMED_PAISE_ATTR, the WECARE store's card.
#:
#: PRESENCE IS NOT EVIDENCE of a second leg; a non-zero VALUE is. The retired secondary tender evidence is
#: recorded as 0 until the card is actually debited, so every consumer here tests the value, never
#: the key.
OTHER_TENDER_PAISE_ATTRS = ()


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

    Zero is accepted. That is not laxity - a fully retired secondary tender-funded order has no Razorpay leg, and
    `retired secondary tender_settlement.is_fully_settled` requires the term to be PRESENT (`if verified is None:
    return False`) to close `verified + redeemed == payable`.
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


def cart_id(attempt, snapshot):
    """The cart behind this attempt, or `''`.

    `payment_attempt.build` writes `cartId` only when the caller supplies one: the website prepare
    does, the WhatsApp catalog-service create does not. The cart id is ALSO on the frozen snapshot
    as `cart.id`, which `website_checkout._bounded_snapshot` retains even in its reduced
    projection. Both are read, in that order; neither is guessed.
    """
    direct = str(attempt.get('cartId') or '')
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
    `record_paid` stores as SEAM-G13's evidence and what `_tenders_reconcile` closes against the
    frozen payable. It is never the order total and never a subtraction.
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
             'source': order_channel.canonical(attempt.get('channel')),
             # Capture authorizes fulfilment; it does not complete it. This matches the
             # invoice-payment lineage and the Meta order_status lifecycle.
             'orderStatus': 'processing', 'status': 'processing',
             'totalAmount': Decimal(attempt['amountPaise']) / Decimal(100),
             # WHERE the order came from, beside HOW it settled, and deliberately a SECOND field
             # rather than a third `checkoutMode`: `checkoutMode` gates finalisation through
             # `ACCEPTED_CHECKOUT_MODES` above, so a channel spelled into it would be a new
             # settlement path instead of a label. `order_channel.canonical` is total, so an
             # attempt row with no channel - which is every attempt written before this landed -
             # reads as `website`. That default is TRUE and not a guess: no WhatsApp order can
             # exist, because the hand-off that would create one is gated off.
             'channel': order_channel.canonical(attempt.get('channel')),
             'finalizationStage': 'INTERNAL_ORDER_CREATED', 'createdAt': int(time.time())}
    # WHO the order belongs to, in the one form we are willing to print. Copied off the attempt
    # - never minted here - because this function runs after the money has moved and a write to
    # ContactsTable for a display field is the wrong trade on that path.
    #
    # CONDITIONAL, and that matters twice over. An order row for an attempt with no public id is
    # byte-identical to one written before this landed, and - decisively - the key is NOT added
    # to the five-key association-conflict comparison below. That comparison exists to refuse an
    # idempotent re-entry that would bind one order to different MONEY; the customer id is
    # attribution, so letting it raise `internal order association conflict` would turn a
    # harmless redelivery into a paid-but-no-order alarm over a label.
    if attempt.get('customerUuid'):
        order['customerUuid'] = attempt['customerUuid']
    if attempt.get('customerPhone'):
        # Recorded from the authenticated checkout session, never a browser field.
        order['customerPhone'] = attempt['customerPhone']
    # THE ONE CONTACT ROW this order belongs to - the same ContactsTable row the WhatsApp inbox,
    # the Flows and the website profile use - copied off the attempt, where checkout stamped it
    # from the session-owned contact. Conditional and outside the conflict comparison for the
    # same reason as `customerUuid`: it is attribution, not money.
    if attempt.get('contactId'):
        order['contactId'] = attempt['contactId']
    # WHERE it ships: the address the customer confirmed when checkout prepared this payment,
    # frozen on the attempt by `order_delivery.attempt_fields`. Copied here and never read off the
    # contact, because the contact's one address is overwritten by every later profile save. Same
    # standing as `contactId`: attribution, conditional (a service or contribution attempt carries
    # none and writes a byte-identical row) and outside the conflict comparison below.
    order.update(order_delivery.order_fields(attempt))
    # The short order number, so the `shortId` GSI finds website and WhatsApp orders alike
    # (staff orders always carried it; these did not).
    short = order_record.short_id(outcome['orderNumber'])
    if short:
        order['shortId'] = short
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
    # Identity is a terminal-finalization invariant. Keep the committed order as recoverable
    # evidence that money moved, but never call it finalized until it is attached to the same
    # canonical ContactsTable row used by Inbox/Flows and carries the public customer UUID.
    if not order.get('contactId') or not order.get('customerUuid'):
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='CUSTOMER_IDENTITY_MISSING')
        return
    # The tender identity, checked AFTER the order record committed and BEFORE the terminal
    # stage: a tender sum that does not close is a fact about money, so the order keeps its
    # record and its number but rests at NEEDS_RECONCILIATION and never reaches ORDER_FINALIZED.
    if not _tenders_reconcile(attempt, razorpay_paise):
        _stage(attempts, attempt['paymentAttemptId'], 'NEEDS_RECONCILIATION',
               finalizationReason='TENDER_SUM_MISMATCH')
        return
    # TERMINAL. The internal order IS the authoritative artifact and there is no second ledger to
    # write to: the order record committed above (INTERNAL_ORDER_CREATED) and the tenders
    # reconciled, so the order is now FINALIZED. Native inventory was already reserved at
    # checkout and the order carries the full line detail, so nothing external needs confirming
    # for the order to be complete.
    # The attempt row is the AUTHORITATIVE finalization record (what status polls read); staging
    # it is what makes the order final and idempotent on re-entry. The order row's own
    # `finalizationStage` is mirrored to ORDER_FINALIZED, conditional on THIS attempt so a
    # concurrent re-entry cannot rebind it.
    _stage(attempts, attempt['paymentAttemptId'], 'ORDER_FINALIZED')
    orders.update_item(Key={'orderId': order['orderId']},
        UpdateExpression='SET finalizationStage=:stage',
        ConditionExpression='paymentAttemptId=:attempt',
        ExpressionAttributeValues={':stage': 'ORDER_FINALIZED',
                                   ':attempt': attempt['paymentAttemptId']})
