"""Reserve the identity of a native WhatsApp payment collection, BEFORE anything is sent.

What this module is for
-----------------------
On the native leg the customer pays inside WhatsApp: Meta creates the Razorpay gateway order when
they tap Pay, and we only ever see the result. So the one thing we control is the identity the
payment will arrive under, and it has to be reserved before the message leaves - because a
`reference_id` minted per send is a `reference_id` that differs on a retry, and two references for
one invoice is two captures and two orders.

This module therefore does exactly one job: it RESERVES. It does not send, it does not resolve a
payment configuration, and it does not decide payment state.

What it deliberately does NOT do
--------------------------------
**It never resolves a payment configuration.** `configuration_name` is a required INPUT. Carrying
a name is not resolving one: the authority on which configuration a given sender may use is
`outbound-whatsapp._build_payment_settings`, which owns `PHONE_PAYMENT_CONFIG`,
`PHONE_PAYMENT_GATEWAYS`, `VALID_PAYMENT_CONFIGS` and `DEFAULT_PAYMENT_CONFIG`. A test bans those
four names from this file by AST walk, so the boundary keeps meaning what it says.

**It decides no payment STATE.** Paid-ness on this leg is the existence of the `PAYMENTATTEMPT#`
claim, never a word, so this module has nothing to consult in `payment_status` and deliberately
imports none of it.

**It composes no key by hand.** Every reservation key is built from an `order_keys.*_PREFIX`
constant, so the prefixes keep one home even though the WRITER moved here: per the design's H3
finding, `order_keys._claim_row` and friends each issue their own `put_item` and therefore cannot
be `TransactItems` entries, so the four `Put`s are composed here and the prefixes, item shapes and
resolvers are reused.

Why one transaction and not four writes
---------------------------------------
A `PAYREF#` row written without its `REQUESTKEY#` anchor is a reference the webhook will
reconcile on and that no retry can resolve to - so a second send mints a second reference against
one invoice, which is the whole defect this exists to close, reopened by a crash rather than by a
bug. A transaction removes that window instead of documenting it.
"""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from boto3.dynamodb.types import TypeSerializer

from . import initiation, order_channel, order_keys, payment_attempt

logger = logging.getLogger(__name__)

#: MECHANICS, beside the channel rather than inside it. `order_channel` is explicit that
#: attribution ("which surface did the customer use") and mechanics ("how does the money settle")
#: are different questions, and that conflating them is how a new settlement branch gets opened by
#: something that only wanted to print a word on a page.
#:
#: A catalogue WhatsApp order is `channel=whatsapp` and settles through the WEBSITE leg, so its
#: mode stays `WEBSITE_RAZORPAY_STANDARD`. The native leg genuinely settles differently - Meta
#: creates the gateway order - so it gets its own label, and that label is read in exactly two
#: places: as a BINDING-SOURCE selector in the webhook, and as the invoice-delivery gate.
#:
#: It is deliberately NOT added to `finalization.ACCEPTED_CHECKOUT_MODES`. The native leg settles
#: through `order_creation.reconcile_payment`, which never reads the field; keeping it out means
#: that if anyone later routes a native attempt into `finalization.accept_paid` it raises
#: 'verified standalone order identity required' rather than running the Wix write-back sequence
#: against an attempt that has no Wix cart. The exclusion is a guard, not an omission.
WA_NATIVE_CHECKOUT_MODE = 'WHATSAPP_NATIVE_PG'

#: WABA1's phone id, and the ONLY sender permitted to take a payment.
#:
#: Checked here as the caller-side control. The resolver-level control lives inside
#: `_build_payment_settings`, ahead of its explicit-configuration override, because an internal
#: caller that bypasses this module must still be refused - and `send_payment_link` has three
#: internal callers that are exactly such callers today.
PHONE_NUMBER_ID_1 = 'phone-number-id-waba1-direct-1016149501586345'
PAYMENT_SENDERS = frozenset({PHONE_NUMBER_ID_1})

#: WABA id per permitted sender. Derived from the sender, never read from a request body: a
#: caller-supplied WABA id on a money path is a caller-supplied routing decision.
PHONE_ID_TO_WABA = {
    PHONE_NUMBER_ID_1: '2094615664435155',
}

#: ₹5,00,000, mirroring the point at which `outbound-whatsapp` switches
#: `enabled_payment_options` to 'web' because UPI is capped there. A request above this is
#: refused outright on this path and the operator sends a website checkout link instead.
#:
#: Refusing rather than silently switching: the alternative is that the customer's payment
#: options change at the Meta boundary, so the amount they see and the method they get are
#: decided in different places.
MAX_AMOUNT_PAISE = 50_000_000

#: Meta's own limit on an order_details item name.
MAX_ITEM_NAME_LENGTH = 60

#: Business numbers, which must never be a payment RECIPIENT. Mirrors
#: `lambda_utils.notifications.events._DEFAULT_BUSINESS_NUMBERS`; duplicated as a literal rather
#: than imported because `notifications` is not in every consumer's import closure, and a test
#: pins the two equal.
BUSINESS_NUMBERS = frozenset({'+919330994400', '+919903300044', '+918031830030'})

_E164_IN = re.compile(r'^\+91\d{10}$')

# ── refusal codes ──────────────────────────────────────────────────────────────
# Stable codes, never a provider or request-body string. Each operator-facing message ends
# "Nothing has been charged.", mirroring `service_requests.SERVICE_MESSAGES`.
WA_PAY_SENDER_NOT_PERMITTED = 'WA_PAY_SENDER_NOT_PERMITTED'
WA_PAY_CONFIG_NAME_REQUIRED = 'WA_PAY_CONFIG_NAME_REQUIRED'
WA_PAY_CONFIG_UNRESOLVED = 'WA_PAY_CONFIG_UNRESOLVED'
WA_PAY_PROVIDER_MID_REQUIRED = 'WA_PAY_PROVIDER_MID_REQUIRED'
WA_PAY_AMOUNT_INVALID = 'WA_PAY_AMOUNT_INVALID'
WA_PAY_CURRENCY_UNSUPPORTED = 'WA_PAY_CURRENCY_UNSUPPORTED'
WA_PAY_RECIPIENT_INVALID = 'WA_PAY_RECIPIENT_INVALID'
WA_PAY_CUSTOMER_UNRESOLVED = 'WA_PAY_CUSTOMER_UNRESOLVED'
WA_PAY_ITEM_INVALID = 'WA_PAY_ITEM_INVALID'
WA_PAY_INTENT_CHANGED = 'WA_PAY_INTENT_CHANGED'
WA_PAY_REFERENCE_INVALID = 'WA_PAY_REFERENCE_INVALID'
WA_PAY_REFERENCE_ALREADY_RESERVED = 'WA_PAY_REFERENCE_ALREADY_RESERVED'
WA_PAY_ALREADY_IN_FLIGHT = 'WA_PAY_ALREADY_IN_FLIGHT'
WA_PAY_LINK_NOT_PERMITTED = 'WA_PAY_LINK_NOT_PERMITTED'
WA_PAY_IDENTITY_UNAVAILABLE = 'WA_PAY_IDENTITY_UNAVAILABLE'

REFUSAL_MESSAGES = {
    WA_PAY_SENDER_NOT_PERMITTED: 'This business number may not take payments. Nothing has been charged.',
    WA_PAY_CONFIG_NAME_REQUIRED: 'No payment configuration was named. Nothing has been charged.',
    WA_PAY_CONFIG_UNRESOLVED: 'The payment configuration could not be resolved. Nothing has been charged.',
    WA_PAY_PROVIDER_MID_REQUIRED: 'No merchant id was supplied. Nothing has been charged.',
    WA_PAY_AMOUNT_INVALID: 'The invoice total is not a payable amount. Nothing has been charged.',
    WA_PAY_CURRENCY_UNSUPPORTED: 'Only INR payments are supported. Nothing has been charged.',
    WA_PAY_RECIPIENT_INVALID: 'The recipient number is not a payable destination. Nothing has been charged.',
    WA_PAY_CUSTOMER_UNRESOLVED: 'This invoice has no customer on it. Nothing has been charged.',
    WA_PAY_ITEM_INVALID: 'The invoice line name is not usable. Nothing has been charged.',
    WA_PAY_INTENT_CHANGED: 'This invoice changed after its payment request was sent. Cancel it and raise a new collection. Nothing has been charged.',
    WA_PAY_REFERENCE_INVALID: 'The invoice carries an unusable payment reference. Nothing has been charged.',
    WA_PAY_REFERENCE_ALREADY_RESERVED: 'This payment reference is already reserved elsewhere. Nothing has been charged.',
    WA_PAY_ALREADY_IN_FLIGHT: 'A payment request for this invoice is already in flight. Nothing has been charged.',
    WA_PAY_LINK_NOT_PERMITTED: 'WhatsApp payments must travel in the approved template, not a link. Nothing has been charged.',
    WA_PAY_IDENTITY_UNAVAILABLE: 'The payment reservation could not be stored. Nothing has been charged.',
}

#: HTTP status per refusal, so the caller maps once rather than per branch. 503 for the two that
#: are a retry rather than a refusal.
REFUSAL_STATUS = {
    WA_PAY_IDENTITY_UNAVAILABLE: 503,
}


class PaymentRequestRefused(ValueError):
    """Carries a stable `.code`, never a provider or request-body string."""

    def __init__(self, code: str, detail: str = '') -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)

    @property
    def message(self) -> str:
        return REFUSAL_MESSAGES.get(self.code, 'Nothing has been charged.')

    @property
    def status_code(self) -> int:
        return REFUSAL_STATUS.get(self.code, 409)


def exact_paise(value: Any) -> int:
    """Exact integer paise from a rupee figure, or raise. No `round()`, no float, no epsilon.

    A total carrying sub-paise noise cannot be compared exactly, so it fails CLOSED rather than
    truncating 599.999 to 59999 and matching a rounded-down expectation. That matters because the
    reserved amount is what a capture is compared against with exact integer equality: a
    one-paise disagreement must mean the provider disagrees, not that we rounded.
    """
    try:
        minor = Decimal(str(value if value is not None else 0)) * 100
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PaymentRequestRefused(WA_PAY_AMOUNT_INVALID, 'unparseable money') from exc
    if minor != minor.to_integral_value():
        raise PaymentRequestRefused(WA_PAY_AMOUNT_INVALID, 'sub-paise precision')
    return int(minor)


def collection_request_key(invoice_id: str, collection_seq: int = 0) -> str:
    """The resolve-before-generate request key for one invoice's Nth collection.

    The SEQUENCE is what makes a cancelled collection re-raisable. The anchor fingerprints the
    amount, so an edited invoice refuses with `WA_PAY_INTENT_CHANGED`; without a sequence the
    design's own "cancel and re-raise" remedy is unreachable, because the old anchor survives the
    cancel and the new amount mismatches it forever.

    `cancel_invoice` records `collectionSeq + 1`, so the next collection composes a DIFFERENT key:
    the old reservation stays immutable, nothing is deleted, nothing is reissued, and the old
    `PAYREF#` row remains resolvable so a customer paying the message they already hold still
    settles against the reservation that message named.
    """
    return 'INVPAY#%s#%d' % (invoice_id, int(collection_seq or 0))


def _require(condition: bool, code: str, detail: str = '') -> None:
    if not condition:
        raise PaymentRequestRefused(code, detail)


def build_request(*,
                  invoice_id: str,
                  customer_id: str,
                  phone_e164: str,
                  phone_number_id: str,
                  amount_paise: int,
                  configuration_name: str,
                  provider_mid: str,
                  item_name: str,
                  now: int,
                  waba_id: str = '',
                  customer_uuid: str = '',
                  currency: str = 'INR',
                  collection_seq: int = 0,
                  order_details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate every external input and return the reservation request. Writes nothing.

    Every rule runs here, BEFORE any write and before any Lambda invoke, so a refusal leaves no
    partial state behind. `now` is required rather than defaulted so a reservation is
    deterministic under test.

    `order_details`, when supplied, is inspected for the two forbidden link keys only. A WhatsApp
    payment travels in the approved `order_details` template or it does not travel: a link path
    bypasses `configuration_name`, and with it the merchant-id verification that proves where the
    money lands.
    """
    if order_details:
        for forbidden in ('payment_link_uri', 'upi_intent_link'):
            _require(not order_details.get(forbidden), WA_PAY_LINK_NOT_PERMITTED, forbidden)

    _require(bool(invoice_id), WA_PAY_CUSTOMER_UNRESOLVED, 'invoice_id')
    _require(bool(customer_id), WA_PAY_CUSTOMER_UNRESOLVED, 'customer_id')

    phone = str(phone_e164 or '').strip()
    _require(bool(_E164_IN.match(phone)), WA_PAY_RECIPIENT_INVALID, 'format')
    # Our own numbers are never a payment recipient. This is the backstop that stops us
    # messaging ourselves; a collection addressed to a business line is a configuration mistake,
    # not a customer.
    _require(phone not in BUSINESS_NUMBERS, WA_PAY_RECIPIENT_INVALID, 'business number')

    _require(phone_number_id in PAYMENT_SENDERS, WA_PAY_SENDER_NOT_PERMITTED, 'sender')
    resolved_waba = waba_id or PHONE_ID_TO_WABA.get(phone_number_id, '')
    _require(bool(resolved_waba), WA_PAY_SENDER_NOT_PERMITTED, 'waba')

    # `bool` is excluded explicitly: `isinstance(True, int)` is True in Python, so `True` would
    # otherwise pass as one paise.
    _require(not isinstance(amount_paise, bool) and isinstance(amount_paise, int),
             WA_PAY_AMOUNT_INVALID, 'type')
    _require(amount_paise > 0, WA_PAY_AMOUNT_INVALID, 'non-positive')
    _require(amount_paise <= MAX_AMOUNT_PAISE, WA_PAY_AMOUNT_INVALID, 'above ceiling')

    # Compared explicitly, never inferred from the amount.
    _require(currency == 'INR', WA_PAY_CURRENCY_UNSUPPORTED, 'currency')

    # Non-empty only. Membership is NOT checked here: the authority on whether a name is valid is
    # `_build_payment_settings`, which owns the set, and ultimately `payment_readiness.evaluate`,
    # which proves it against a live Meta read.
    _require(bool(str(configuration_name or '').strip()), WA_PAY_CONFIG_NAME_REQUIRED)

    # Required for the reason `payment_readiness.evaluate` gives in its own words: passing an
    # empty value yields CONFIGURATION_UNVERIFIED rather than skipping the check, because "we did
    # not compare the merchant id" must never read the same as "the merchant id matched".
    _require(bool(str(provider_mid or '').strip()), WA_PAY_PROVIDER_MID_REQUIRED)

    name = str(item_name or '').strip()
    _require(bool(name) and len(name) <= MAX_ITEM_NAME_LENGTH, WA_PAY_ITEM_INVALID)

    if isinstance(now, bool) or not isinstance(now, int):
        raise ValueError('now must be an int epoch seconds')

    return {
        'invoiceId': str(invoice_id),
        'customerId': str(customer_id),
        'customerUuid': str(customer_uuid or ''),
        'phoneE164': phone,
        'phoneNumberId': phone_number_id,
        'wabaId': resolved_waba,
        'amountPaise': amount_paise,
        'currency': currency,
        'configurationName': str(configuration_name).strip(),
        'providerMid': str(provider_mid).strip(),
        'itemName': name,
        'collectionSeq': int(collection_seq or 0),
        'requestKey': collection_request_key(invoice_id, collection_seq),
        'now': now,
    }


def intent_fingerprint(request: Dict[str, Any]) -> str:
    """The pinned intent: invoice, amount, currency, configuration.

    The AMOUNT is in it deliberately, so an invoice edited after a collection was sent cannot
    resume the old reservation. A customer holding a payment request for ₹99 must not have it
    silently become ₹350.
    """
    return initiation.fingerprint([request['invoiceId'], request['amountPaise'],
                                   request['currency'], request['configurationName']])


def _reference_row(request: Dict[str, Any], reference_id: str,
                   attempt_id: str) -> Dict[str, Any]:
    """The `PAYREF#` row: what the webhook reconciles on.

    Note what is ABSENT and why it is load-bearing. `order_creation` computes
    `expected_amount = positive_paise(attempt.get('razorpayChargedPaise') or
    attempt.get('amountPaise'))`, so the full `amountPaise` is the expectation ONLY because
    `razorpayChargedPaise` is absent - and `finalization.OTHER_TENDER_PAISE_ATTRS` is likewise
    absent. The native leg is single-tender BY CONSTRUCTION: the invoice total is the one figure
    collected, there is no gift card on this path and no cart to redeem against.
    `payablePaise == amountPaise` is written explicitly so the equality is visible on the row
    rather than inferred from a missing field, and a test asserts none of the three split-tender
    attributes exists - so a later split-tender feature cannot silently make a PARTIAL capture
    compare equal to the full total.
    """
    row = {
        'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + reference_id,
        'kind': 'PAYMENT_REFERENCE',
        'referenceId': reference_id,
        'paymentAttemptId': attempt_id,
        'customerId': request['customerId'],
        'amountPaise': request['amountPaise'],
        'payablePaise': request['amountPaise'],
        'currency': request['currency'],
        'checkoutMode': WA_NATIVE_CHECKOUT_MODE,
        'channel': order_channel.CHANNEL_WHATSAPP,
        # The binding's configuration source. On this row rather than on the attempt, because
        # the webhook's `_load_attempt` already reads here and adding an attempts-table read to
        # fetch one string would create a second home for the field the verifier keys on.
        'configurationName': request['configurationName'],
        'phoneId': request['phoneNumberId'],
        'wabaId': request['wabaId'],
        'invoiceId': request['invoiceId'],
        'reservedAt': request['now'],
        'createdAt': request['now'],
    }
    if request.get('customerUuid'):
        row['customerUuid'] = request['customerUuid']
    return row


def _resolve_reference(keys_table: Any, invoice_reference_id: str,
                       collection_seq: int = 0) -> Tuple[str, bool]:
    """`(reference_id, minted)` - ADOPT the invoice's reference, mint only when it cannot be used.

    Adopting rather than replacing, and the difference is not cosmetic. `create_invoice` mints a
    `referenceId` for EVERY invoice and `send_payment_link` hard-refuses one without it, so on the
    live path the id already exists before collection is raised. Replacing it on an ORDINARY send
    strands every payment request already in a customer's hands: their tap produces a capture
    whose reference resolves nowhere on either settlement route, so it quarantines as
    PAID_BUT_NO_ORDER - the exact symptom this feature exists to remove.

    **The one case where a fresh reference is REQUIRED rather than merely permitted** is a
    re-raise after a cancel (`collection_seq > 0`). The old `PAYREF#` row is deliberately NOT
    deleted - a customer who pays the message they already hold must still settle, against the
    OLD amount that row records - so the old reference is taken, and reserving it twice is not
    possible. Reusing it would also be wrong even if it were: the row carries the pre-edit
    `amountPaise`, so a capture at the new amount would compare unequal and quarantine.

    So the two arms are not a policy choice between adopt and replace. At sequence 0 adopting is
    the only safe answer; past sequence 0 minting is the only possible one, and the operator's
    explicit cancel is what declares the old request dead.
    """
    existing = str(invoice_reference_id or '')
    if not existing:
        return order_keys.mint_payment_reference(), True
    if not order_keys.is_valid_meta_reference_id(existing):
        # Refused rather than silently re-minted, because silently re-minting on an ordinary send
        # is what produces two live references for one invoice.
        raise PaymentRequestRefused(WA_PAY_REFERENCE_INVALID)
    if order_keys.resolve_payment_reference(keys_table, existing) is not None:
        if int(collection_seq or 0) > 0:
            # A re-raise after a cancel. Mint, and leave the superseded row untouched.
            return order_keys.mint_payment_reference(), True
        # Sequence 0 and already reserved. The `REQUESTKEY#` resolution above has already
        # returned its attempt for a genuine retry, so reaching here means the anchor and the
        # reference disagree - a reconciliation incident, not a retry.
        raise PaymentRequestRefused(WA_PAY_REFERENCE_ALREADY_RESERVED)
    return existing, False


def _cancellation_is_request_key_conflict(error: Exception) -> bool:
    """True when a cancelled transaction was lost on the FIRST item - the `REQUESTKEY#` row.

    Per-item reasons rather than the top-level code, so a throttle or an outage can never be
    mistaken for "already claimed". Anything that is not a conditional failure on that one item
    raises `OrderIdentityUnavailable` at the call site.
    """
    reasons = getattr(error, 'cancellation_reasons', None)
    if reasons is None:
        reasons = (getattr(error, 'response', {}) or {}).get('CancellationReasons')
    if not reasons:
        return False
    first = reasons[0] if isinstance(reasons, (list, tuple)) and reasons else {}
    return str((first or {}).get('Code') or '') == 'ConditionalCheckFailed'


def _is_transaction_cancelled(error: Exception) -> bool:
    code = (getattr(error, 'response', {}) or {}).get('Error', {}).get('Code', '')
    return code == 'TransactionCanceledException'


def reserve(client: Any, keys_table: Any, attempts_table: Any, *,
            keys_name: str, attempts_name: str,
            request: Dict[str, Any],
            invoice_reference_id: str = '') -> Tuple[Dict[str, Any], bool]:
    """Reserve the collection identity in ONE transaction. Returns `(attempt, freshly_reserved)`.

    Resolve before generate: the `REQUESTKEY#` anchor is read first, outside the transaction. A
    matching fingerprint returns the EXISTING attempt and its existing `referenceId`, so a retried
    send re-sends the same message. A differing fingerprint refuses - honouring it would send the
    customer a payment request for one amount against a reservation for another.

    The read-then-transact pair is not a race: the read is an optimisation for the common retry,
    and `attribute_not_exists(orderId)` is the authority. A racer that slips between them loses
    the transaction and is handled as the lost-race case.
    """
    customer_id = request['customerId']
    request_key = request['requestKey']

    existing = order_keys.resolve_checkout_request_key(
        keys_table, customer_id=customer_id, request_key=request_key)
    if existing:
        return _resume(attempts_table, existing, request)

    reference_id, _minted = _resolve_reference(
        keys_table, invoice_reference_id, request['collectionSeq'])
    attempt_id = payment_attempt.new_payment_attempt_id()

    attempt = payment_attempt.build(
        customer_id=customer_id, reference_id=reference_id,
        amount_paise=request['amountPaise'], currency=request['currency'],
        configuration_name=request['configurationName'],
        payment_attempt_id=attempt_id, customer_uuid=request.get('customerUuid', ''),
        now=request['now'])
    attempt = payment_attempt.transition(
        attempt, payment_attempt.PAYMENT_READINESS_CHECKED, now=request['now'])
    # `cartId` is deliberately omitted - there is no Wix cart on this leg, and
    # `payment_attempt.build` already defaults it away.
    attempt.update(checkoutMode=WA_NATIVE_CHECKOUT_MODE,
                   channel=order_channel.CHANNEL_WHATSAPP,
                   providerMid=request['providerMid'],
                   phoneId=request['phoneNumberId'], wabaId=request['wabaId'],
                   invoiceId=request['invoiceId'],
                   collectionSeq=request['collectionSeq'],
                   sendStatus='NOT_STARTED', finalizationStage='NOT_STARTED')

    anchor = {
        'orderId': order_keys.REQUEST_KEY_PREFIX + customer_id + '#' + request_key,
        # The same attribute set `order_keys.reserve_checkout_request_key` writes, so
        # `resolve_checkout_request_key` reads it back unmodified. That compatibility is the
        # point of reusing the prefix rather than the function.
        'kind': 'CHECKOUT_REQUEST_KEY',
        'customerId': customer_id,
        'requestKey': request_key,
        'intentFingerprint': intent_fingerprint(request),
        'paymentAttemptId': attempt_id,
        'reservedAt': request['now'],
        'invoiceId': request['invoiceId'],
        'referenceId': reference_id,
    }
    collection = {
        'orderId': order_keys.INVOICE_COLLECT_PREFIX + request['invoiceId'],
        'kind': order_keys.INVOICE_COLLECT_KIND,
        'invoiceId': request['invoiceId'],
        'paymentAttemptId': attempt_id,
        'referenceId': reference_id,
        'collectionSeq': request['collectionSeq'],
        'claimedAt': request['now'],
    }
    reference = _reference_row(request, reference_id, attempt_id)

    serializer = TypeSerializer()

    def item(row: Dict[str, Any]) -> Dict[str, Any]:
        return {key: serializer.serialize(value) for key, value in row.items()}

    try:
        client.transact_write_items(TransactItems=[
            {'Put': {'TableName': keys_name, 'Item': item(anchor),
                     'ConditionExpression': 'attribute_not_exists(orderId)'}},
            {'Put': {'TableName': keys_name, 'Item': item(reference),
                     'ConditionExpression': 'attribute_not_exists(orderId)'}},
            {'Put': {'TableName': keys_name, 'Item': item(collection),
                     'ConditionExpression': 'attribute_not_exists(orderId)'}},
            {'Put': {'TableName': attempts_name, 'Item': item(attempt),
                     'ConditionExpression': 'attribute_not_exists(paymentAttemptId)'}},
        ])
    except Exception as error:  # noqa: BLE001
        if _is_transaction_cancelled(error) and _cancellation_is_request_key_conflict(error):
            # Lost the anchor to a concurrent racer. Re-resolve once and adopt its reservation.
            rival = order_keys.resolve_checkout_request_key(
                keys_table, customer_id=customer_id, request_key=request_key)
            if rival:
                return _resume(attempts_table, rival, request)
        if isinstance(error, PaymentRequestRefused):
            raise
        if _is_transaction_cancelled(error):
            # A cancellation on any OTHER item is a genuine conflict we must not interpret: the
            # collection claim is held by a different attempt, or the reference is taken.
            raise PaymentRequestRefused(WA_PAY_ALREADY_IN_FLIGHT,
                                        type(error).__name__) from error
        raise PaymentRequestRefused(WA_PAY_IDENTITY_UNAVAILABLE,
                                    type(error).__name__) from error

    logger.info('{"event":"wa_payment_request_reserved","referenceId":"%s","invoiceId":"%s"}',
                reference_id, request['invoiceId'])
    return attempt, True


def _resume(attempts_table: Any, anchor: Dict[str, Any],
            request: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Resolve an existing reservation, or refuse because the intent changed."""
    if str(anchor.get('intentFingerprint') or '') != intent_fingerprint(request):
        raise PaymentRequestRefused(WA_PAY_INTENT_CHANGED)
    attempt_id = str(anchor.get('paymentAttemptId') or '')
    if not attempt_id:
        raise PaymentRequestRefused(WA_PAY_IDENTITY_UNAVAILABLE, 'anchor carries no attempt')
    try:
        stored = attempts_table.get_item(
            Key={'paymentAttemptId': attempt_id}, ConsistentRead=True).get('Item')
    except Exception as error:  # noqa: BLE001
        raise PaymentRequestRefused(WA_PAY_IDENTITY_UNAVAILABLE,
                                    type(error).__name__) from error
    if not stored:
        # The anchor names an attempt that is not there. Not a retry and not a race: a lost
        # write, which a human has to look at rather than a second reservation papering over.
        raise PaymentRequestRefused(WA_PAY_IDENTITY_UNAVAILABLE, 'attempt missing')
    logger.info('{"event":"wa_payment_request_idempotent_hit","referenceId":"%s"}',
                str(stored.get('referenceId') or ''))
    return stored, False


def claim_send(attempts_table: Any, *, payment_attempt_id: str) -> bool:
    """The durable boundary BEFORE the sender is invoked. Losing workers never send.

    A conditional `sendStatus NOT_STARTED -> PENDING`, reusing `initiation.claim_send`'s pattern:
    a second `order_details` message for one reservation would show the customer two payment
    requests.
    """
    if not payment_attempt_id:
        return False
    try:
        attempts_table.update_item(
            Key={'paymentAttemptId': payment_attempt_id},
            UpdateExpression='SET sendStatus = :pending',
            ConditionExpression='attribute_exists(paymentAttemptId) AND sendStatus = :new',
            ExpressionAttributeValues={':pending': 'PENDING', ':new': 'NOT_STARTED'})
        return True
    except Exception as error:  # noqa: BLE001
        if order_keys.is_conditional_failure(error):
            return False
        raise PaymentRequestRefused(WA_PAY_IDENTITY_UNAVAILABLE,
                                    type(error).__name__) from error


def record_sent(attempts_table: Any, *, payment_attempt_id: str, now: int) -> bool:
    """Advance a sent attempt to `PAYMENT_REQUEST_SENT`. Never raises.

    Monotonic by condition rather than by read-then-write. A failure to advance is logged and
    swallowed: the customer already has the message, so the authoritative record of that fact is
    the OutboundTable row and the `sendStatus` claim, not the attempt's display state.
    """
    if not payment_attempt_id:
        return False
    rank = payment_attempt.rank(payment_attempt.PAYMENT_REQUEST_SENT)
    try:
        attempts_table.update_item(
            Key={'paymentAttemptId': payment_attempt_id},
            UpdateExpression='SET #s = :sent, attemptRank = :rank, updatedAt = :now, '
                             'sendStatus = :done',
            ConditionExpression='attribute_exists(paymentAttemptId) AND ('
                                'attribute_not_exists(attemptRank) OR attemptRank <= :rank)',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':sent': payment_attempt.PAYMENT_REQUEST_SENT,
                                       ':rank': rank, ':now': int(now), ':done': 'SENT'})
        return True
    except Exception as error:  # noqa: BLE001
        logger.error('{"event":"wa_payment_attempt_sent_advance_failed","error":"%s"}',
                     type(error).__name__)
        return False


__all__ = [
    'WA_NATIVE_CHECKOUT_MODE',
    'PAYMENT_SENDERS',
    'PHONE_NUMBER_ID_1',
    'PHONE_ID_TO_WABA',
    'MAX_AMOUNT_PAISE',
    'MAX_ITEM_NAME_LENGTH',
    'BUSINESS_NUMBERS',
    'REFUSAL_MESSAGES',
    'REFUSAL_STATUS',
    'PaymentRequestRefused',
    'exact_paise',
    'collection_request_key',
    'build_request',
    'intent_fingerprint',
    'reserve',
    'claim_send',
    'record_sent',
    'WA_PAY_SENDER_NOT_PERMITTED',
    'WA_PAY_CONFIG_NAME_REQUIRED',
    'WA_PAY_CONFIG_UNRESOLVED',
    'WA_PAY_PROVIDER_MID_REQUIRED',
    'WA_PAY_AMOUNT_INVALID',
    'WA_PAY_CURRENCY_UNSUPPORTED',
    'WA_PAY_RECIPIENT_INVALID',
    'WA_PAY_CUSTOMER_UNRESOLVED',
    'WA_PAY_ITEM_INVALID',
    'WA_PAY_INTENT_CHANGED',
    'WA_PAY_REFERENCE_INVALID',
    'WA_PAY_REFERENCE_ALREADY_RESERVED',
    'WA_PAY_ALREADY_IN_FLIGHT',
    'WA_PAY_LINK_NOT_PERMITTED',
    'WA_PAY_IDENTITY_UNAVAILABLE',
]
