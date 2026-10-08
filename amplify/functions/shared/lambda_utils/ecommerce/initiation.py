"""Atomic customer-scoped initiation and immutable Cart V2 snapshots.

No expiry on financial/idempotency records. A PENDING/UNKNOWN send is never
replayed automatically: network acceptance cannot be inferred from a timeout.
"""
import hashlib
import json
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer
from lambda_utils.customer_auth import authorize_resource
from . import order_keys, payment_attempt


class InitiationConflict(ValueError):
    pass


class InitiationUnavailable(RuntimeError):
    pass


def fingerprint(value):
    def encode(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(type(obj).__name__)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=encode).encode()).hexdigest()


def request_key(customer_id, request_id):
    if not isinstance(request_id, str) or not 16 <= len(request_id) <= 100:
        raise ValueError('requestId of 16 to 100 characters required')
    return 'CHECKOUTREQUEST#' + fingerprint([customer_id, request_id])


def existing(keys, attempts, identity, request_id, intent):
    row = keys.get_item(Key={'orderId': request_key(identity.customer_id, request_id)},
                        ConsistentRead=True).get('Item')
    if not row:
        return None
    authorize_resource(identity, row)
    if row['fingerprint'] != fingerprint(intent):
        raise InitiationConflict('requestId already used for another checkout')
    attempt = attempts.get_item(Key={'paymentAttemptId': row['paymentAttemptId']},
                                ConsistentRead=True).get('Item')
    if not attempt:
        raise InitiationUnavailable('atomic initiation state unavailable')
    return authorize_resource(identity, attempt)


def reserve(client, *, keys_name, attempts_name, identity, request_id, intent,
            snapshot, configuration_name, provider_mid, phone_id, waba_id,
            now, intent_version=1, customer_uuid=''):
    """Three conditional writes in one DynamoDB transaction, before any send.

    An uncertain transaction response must be read back by request key. Retrying
    this function is safe only through that same key and intent fingerprint.

    `customer_uuid` is the public customer id, read off the contact row by the caller. Defaulted
    and last, so every existing call site is unaffected, and emitted by `payment_attempt.build`
    only when non-empty - it is attribution the invoice prints, never an input to a money
    decision.
    """
    attempt_id = payment_attempt.new_payment_attempt_id()
    reference_id = order_keys.mint_payment_reference()
    attempt = payment_attempt.build(
        customer_id=identity.customer_id, reference_id=reference_id,
        amount_paise=int(snapshot['amountPaise']), configuration_name=configuration_name,
        payment_attempt_id=attempt_id, cart_id=snapshot['wixCartId'],
        customer_uuid=customer_uuid, now=now)
    attempt = payment_attempt.transition(attempt, payment_attempt.PAYMENT_READINESS_CHECKED, now=now)
    attempt.update(schemaVersion=intent_version, checkoutMode='WIX_HEADLESS',
                   purchasedSnapshot=snapshot, snapshotHash=fingerprint(snapshot),
                   providerMid=provider_mid, phoneId=phone_id, wabaId=waba_id,
                   sendStatus='NOT_STARTED', finalizationStage='NOT_STARTED')
    request = {'orderId': request_key(identity.customer_id, request_id),
               'customerId': identity.customer_id, 'paymentAttemptId': attempt_id,
               'fingerprint': fingerprint(intent), 'createdAt': now}
    # PAYREF is an index only; all authoritative financial fields live on the attempt.
    reference = {'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + reference_id,
                 'referenceId': reference_id, 'paymentAttemptId': attempt_id,
                 'customerId': identity.customer_id, 'checkoutMode': 'WIX_HEADLESS', 'createdAt': now}
    serializer = TypeSerializer()
    def item(row):
        return {key: serializer.serialize(value) for key, value in row.items()}
    client.transact_write_items(TransactItems=[
        {'Put': {'TableName': keys_name, 'Item': item(request),
                 'ConditionExpression': 'attribute_not_exists(orderId)'}},
        {'Put': {'TableName': keys_name, 'Item': item(reference),
                 'ConditionExpression': 'attribute_not_exists(orderId)'}},
        {'Put': {'TableName': attempts_name, 'Item': item(attempt),
                 'ConditionExpression': 'attribute_not_exists(paymentAttemptId)'}}])
    return attempt


def claim_send(attempts, attempt_id):
    """Durable boundary BEFORE invoking sender. Losing workers never send."""
    try:
        attempts.update_item(Key={'paymentAttemptId': attempt_id},
            UpdateExpression='SET sendStatus = :pending',
            ConditionExpression='attribute_exists(paymentAttemptId) AND sendStatus = :new',
            ExpressionAttributeValues={':pending': 'PENDING', ':new': 'NOT_STARTED'})
        return True
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return False
        raise InitiationUnavailable('send claim unavailable') from error
