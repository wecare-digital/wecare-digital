"""Bind a native WhatsApp capture to its Razorpay gateway order, from Meta - never from the event.

The problem this solves
-----------------------
`razorpay_verify.verifier_for_event` refuses an attempt carrying neither `providerOrderId` nor
`providerPaymentId`, and it is right to: "A webhook must not supply its own binding." On the
website leg that is satisfied because WE create the Razorpay order and store its id before the
browser ever sees checkout options. On the native leg Meta creates it when the customer taps Pay,
so at send time there is no gateway order id to store - and a native attempt therefore fails
closed with `PROVIDER_UNAVAILABLE`. Correct behaviour, wrong outcome.

The rejected alternative, stated so nobody re-derives it as a convenience
-------------------------------------------------------------------------
Relaxing `verifier_for_event` to accept the webhook's own `order_id` when the attempt has no
binding. **Never do this.** The Razorpay webhook signing secret is in this repository's git
history, so a signature proves only that somebody read the history. With that relaxation a forged
event could name any Razorpay order and bind it to any reference. This is the single biggest trap
on this leg.

What this module does instead
-----------------------------
It asks Meta, over an authenticated Graph call, for the payment it holds against OUR
`reference_id`. That is a SECOND INDEPENDENT AUTHORITY rather than a restatement of the event -
which is exactly what `razorpay_verify`'s docstring authorises - and the binding it writes is
write-once and conditional, so a replay is idempotent and a disagreement is refused by the
database rather than resolved by last-writer-wins.

`MetaBindingUnavailable` NEVER asserts "not paid". It means we do not know.
`order_creation.reconcile_payment` turns an unavailable provider into `PROVIDER_UNAVAILABLE`
rather than an order, and Razorpay's redelivery provides the recovery.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from lambda_utils import payment_status
from lambda_utils.ecommerce import order_keys
from lambda_utils.meta_version import GRAPH_HOST, META_API_VERSION

logger = logging.getLogger(__name__)

#: The Meta system-user token, read LAZILY at request time. A module-scope read is cached for the
#: life of the execution environment, so a rotation would not take effect until every warm
#: sandbox recycled - the defect fixed in `payments/razorpay-webhook` on 2026-09-19.
META_TOKEN_SECRET = 'wecare/meta-system-user-token'

_TIMEOUT_SECONDS = 10


class MetaBindingUnavailable(RuntimeError):
    """We do not know. NEVER means 'not paid'."""


def _default_load_token() -> str:
    """Read the Meta token at request time, by reference, and return it to the caller only.

    No logging expression anywhere in this module takes the token, not masked and not reduced to
    a boolean: CodeQL tracks taint across function boundaries and has already failed this build
    twice on exactly that pattern. Reducing a secret to a bool does not launder it.
    """
    import boto3
    raw = boto3.client('secretsmanager').get_secret_value(SecretId=META_TOKEN_SECRET)
    body = raw.get('SecretString', '') or ''
    try:
        return str(json.loads(body).get('access_token') or '').strip()
    except (json.JSONDecodeError, TypeError, AttributeError):
        return body.strip()


def meta_phone_id(phone_number_id: str) -> str:
    """Meta's own phone-number id out of our internal `...-direct-<id>` spelling."""
    value = str(phone_number_id or '')
    return value.split('-direct-')[-1] if '-direct-' in value else value


def lookup_payment(*, reference_id: str, phone_number_id: str, config_name: str,
                   urlopen: Optional[Callable] = None,
                   load_token: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Meta's payment record for one of OUR reference ids.

    `urlopen` is injected (defaulting to `urllib.request.urlopen`) so the enumeration recorder can
    be installed AT THE HTTP SEAM. That seam choice is what makes the no-double-charge enumeration
    meaningful rather than a mock asserting itself.

    Returns `{'gatewayOrderId': ..., 'gatewayPaymentId': ..., 'status': ...}` or raises.
    Every refusal below is a `MetaBindingUnavailable`, and none of them says "not paid":

      * a status that does not canonicalise to `captured`  - not a confirmation
      * `200` with no payment entries                      - Meta knows the reference and reports
                                                             nothing, which is not a confirmation
      * a payment entry with no gateway order id           - the shape is unproven; refuse
      * any HTTP error, timeout or unparseable body        - status code only in the log
      * an empty `config_name`                             - a reserved attempt must carry one
    """
    if not reference_id:
        raise MetaBindingUnavailable('no reference id to look up')
    if not config_name:
        raise MetaBindingUnavailable('the reservation carries no configuration name')
    phone = meta_phone_id(phone_number_id)
    if not phone:
        raise MetaBindingUnavailable('the reservation carries no phone id')

    opener = urlopen or urllib.request.urlopen
    token = (load_token or _default_load_token)()
    if not token:
        raise MetaBindingUnavailable('no Meta credential available')

    url = '%s/%s/%s/payments/%s/%s' % (GRAPH_HOST, META_API_VERSION, phone,
                                       config_name, reference_id)
    request = urllib.request.Request(
        url, headers={'Authorization': 'Bearer %s' % token}, method='GET')
    try:
        with opener(request, timeout=_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        # Status code ONLY. A Meta error body echoes request context.
        logger.warning('{"event":"meta_payment_lookup_http_error","status":%d,'
                       '"referenceId":"%s"}', int(getattr(error, 'code', 0) or 0), reference_id)
        raise MetaBindingUnavailable('Meta lookup failed') from error
    except Exception as error:  # noqa: BLE001
        logger.warning('{"event":"meta_payment_lookup_failed","error":"%s","referenceId":"%s"}',
                       type(error).__name__, reference_id)
        raise MetaBindingUnavailable('Meta lookup unavailable') from error

    payments = (body or {}).get('payments') or []
    if not payments:
        raise MetaBindingUnavailable('Meta reports no payment for this reference')
    entry = payments[0] or {}

    # Canonical, never a raw literal. The exact prior defect is on record: Meta answering `paid`
    # against a raw `captured` comparison was recorded as REJECTED_MISMATCH, rejecting real money.
    status = payment_status.canonical(entry.get('status'))
    if status != payment_status.CAPTURED:
        raise MetaBindingUnavailable('Meta does not report a captured payment')

    gateway_order_id = str(entry.get('provider_order_id')
                           or (entry.get('receipt') or {}).get('provider_order_id')
                           or entry.get('order_id') or '')
    if not gateway_order_id:
        raise MetaBindingUnavailable('Meta reports no gateway order id')

    return {
        'gatewayOrderId': gateway_order_id,
        'gatewayPaymentId': str(entry.get('provider_payment_id')
                                or entry.get('payment_id') or ''),
        'status': status,
    }


def bind_attempt(keys_table: Any, *, reference_id: str, phone_number_id: str,
                 config_name: str, now: Optional[int] = None,
                 amount_paise: Optional[int] = None,
                 payment_attempt_id: str = '', invoice_id: str = '',
                 urlopen: Optional[Callable] = None,
                 load_token: Optional[Callable[[], str]] = None) -> str:
    """Write the gateway-order binding onto the `PAYREF#` row. Returns the bound order id.

    Two writes, in this order, each refusing a different half of the same mistake:

      (a) the reference binding, write-once and conditional on the `PAYREF#` row - refuses TWO
          gateway orders claiming ONE reference;
      (b) `order_keys.bind_gateway_order` (`GATEWAYORDER#`) - refuses the mirror case, ONE
          gateway order claimed by TWO references, which (a) cannot see.

    Both land on the keys table, which is the table the webhook already holds a handle to and the
    row `_load_attempt` already reads - so no attempts-table read is added, and there is no second
    home for the field `razorpay_verify.verifier_for_event` keys on.

    These are NOT one transaction, deliberately, and the reason differs from the reservation's:
    the failure window is benign in both directions. (a) without (b) leaves a reference bound to a
    gateway order no other reference has yet claimed, and a later rival is still refused by (b);
    (b) without (a) leaves a gateway-order row whose attempt matches, which the next redelivery
    completes. Neither order can produce a double charge, and the redelivery that recovers it is
    guaranteed by Razorpay rather than hoped for.
    """
    moment = int(time.time()) if now is None else int(now)
    found = lookup_payment(reference_id=reference_id, phone_number_id=phone_number_id,
                           config_name=config_name, urlopen=urlopen, load_token=load_token)
    gateway_order_id = found['gatewayOrderId']

    # (a) write-once on the row the verifier's loader reads.
    try:
        keys_table.update_item(
            Key={'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + reference_id},
            UpdateExpression='SET providerOrderId = :o, boundAt = if_not_exists(boundAt, :now), '
                             'bindingSource = :src',
            ConditionExpression='attribute_exists(orderId) AND '
                                '(attribute_not_exists(providerOrderId) OR '
                                'providerOrderId = :o)',
            ExpressionAttributeValues={':o': gateway_order_id, ':now': moment,
                                       ':src': 'META_LOOKUP'})
    except Exception as error:  # noqa: BLE001
        if order_keys.is_conditional_failure(error):
            # Two different gateway orders claiming one reference is a reconciliation incident,
            # and the binding must not be where it gets resolved by last-writer-wins.
            logger.error('{"event":"meta_binding_conflict","side":"reference",'
                         '"referenceId":"%s"}', reference_id)
            raise MetaBindingUnavailable('reference is bound to another gateway order') from error
        raise MetaBindingUnavailable('could not store the binding: %s'
                                     % type(error).__name__) from error

    # (b) reverse uniqueness. `account_key_id` and `account_mode` are empty deliberately: on this
    # leg we did not create the order and hold no readback of which Razorpay key issued it, and an
    # empty value reads as "not known from this source", which is honest. `razorpay_verify`'s own
    # readback is what proves the payment.
    won = order_keys.bind_gateway_order(
        keys_table, gateway_order_id=gateway_order_id,
        payment_attempt_id=payment_attempt_id or reference_id,
        request_key=invoice_id or '',
        amount_paise=int(amount_paise) if amount_paise else 1,
        account_key_id='', account_mode='', currency='INR',
        extra={'source': 'META_LOOKUP', 'referenceId': reference_id})
    if not won:
        bound = order_keys.resolve_gateway_order(keys_table, gateway_order_id) or {}
        claimed_by = str(bound.get('paymentAttemptId') or '')
        mine = payment_attempt_id or reference_id
        if claimed_by != mine:
            logger.error('{"event":"meta_binding_conflict","side":"gateway_order",'
                         '"referenceId":"%s"}', reference_id)
            raise MetaBindingUnavailable('gateway order is bound to another attempt')

    logger.info('{"event":"meta_binding_written","referenceId":"%s"}', reference_id)
    return gateway_order_id


__all__ = [
    'META_TOKEN_SECRET',
    'MetaBindingUnavailable',
    'meta_phone_id',
    'lookup_payment',
    'bind_attempt',
]
