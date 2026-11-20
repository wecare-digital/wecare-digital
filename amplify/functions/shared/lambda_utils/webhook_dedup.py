"""
Shared webhook idempotency helper.

Backed by the existing `WebhookDedup` DynamoDB model (PK: eventId; fields: source,
processedAt, expiresAt, ttl). Lets every webhook consumer (WhatsApp, Razorpay)
atomically claim an event id so retries / duplicate deliveries are processed once.

Usage:
    from lambda_utils.webhook_dedup import claim_event
    if not claim_event(message_id, source="whatsapp"):
        return  # duplicate — already processed, skip

`claim_event` returns True when the caller newly claimed the event (process it),
False when the event was already seen (skip). Fails OPEN on infra errors (returns True)
so a transient DynamoDB problem never silently drops a real event.

Two claim styles, and the difference matters on the payment path
---------------------------------------------------------------
`claim_event` claims **permanently**. That is correct for the majority of callers, where the
side effect is idempotent or cheap to repeat: an inbound WhatsApp message row, a Plivo call
leg, a partner metering charge. A Meta redelivery hours later must not re-insert the message,
so the claim has to outlive the handler.

But it has a failure mode that is invisible and expensive on a payment:

    claim -> handler raises -> claim remains -> provider retries -> "duplicate" -> DROPPED

The claim is taken *before* the work and never released, so an exception anywhere in the
handler makes the provider's retry look like a duplicate. On `payment.captured` that means a
captured payment is silently discarded, and Razorpay's retry — the mechanism that exists
precisely to recover from this — is what gets thrown away.

`claim_event_with_lease` fixes that for callers who opt in. The claim carries an expiry, and a
lease that expires **without** `complete_event` having been called is re-claimable. So a crashed
handler releases its claim by doing nothing, while a successful one closes it permanently.

Opt-in rather than a change to `claim_event`, deliberately: every existing caller would
otherwise start re-processing events after the lease window, which is a regression for exactly
the cases where a permanent claim is right. `lambda_utils/pstn/__init__.py` and
`lambda_utils/flow_completion.py` both document their reliance on the current behaviour.

Legacy rows are never re-claimable. A row written before leases existed, or by plain
`claim_event`, carries no `leaseExpiresAt`, and the re-claim path requires one — so the 271 rows
already in the table cannot be reprocessed by this change.
"""
import os
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

WEBHOOK_DEDUP_TABLE = os.environ.get('WEBHOOK_DEDUP_TABLE', 'stack-wecare-digital-WebhookDedup')
DEFAULT_TTL_DAYS = int(os.environ.get('WEBHOOK_DEDUP_TTL_DAYS', '7'))

_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def _table():
    return _dynamodb.Table(WEBHOOK_DEDUP_TABLE)


def claim_event(event_id: Optional[str], source: str = 'whatsapp', ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
    """Atomically claim an event id.

    Returns:
        True  -> newly claimed (caller SHOULD process the event)
        False -> already processed (caller SHOULD skip)
    Fails open (returns True) on missing id or DynamoDB errors so real events are never dropped.
    """
    if not event_id:
        return True
    now = int(time.time())
    expires_at = now + ttl_days * 24 * 60 * 60
    try:
        _table().put_item(
            Item={
                'eventId': str(event_id),
                'source': source,
                'processedAt': now,
                'expiresAt': expires_at,
                'ttl': expires_at,
            },
            ConditionExpression='attribute_not_exists(eventId)',
        )
        return True
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            logger.info('{"event":"webhook_duplicate_skipped","source":"%s","eventId":"%s"}' % (source, str(event_id)[:64]))
            return False
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}' % (source, str(e)[:160]))
        return True  # fail open
    except Exception as e:  # noqa: BLE001 — never let dedup infra drop a real event
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}' % (source, str(e)[:160]))
        return True


def is_duplicate(event_id: Optional[str], source: str = 'whatsapp', ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
    """Convenience inverse of claim_event(): True when the event is a duplicate to skip."""
    return not claim_event(event_id, source=source, ttl_days=ttl_days)


#: How long a handler may hold a leased claim before another delivery may take it. Long enough to
#: cover a Lambda timeout plus a provider verification round trip; short enough that a crash does
#: not stall recovery until the 7-day TTL.
DEFAULT_LEASE_SECONDS = int(os.environ.get('WEBHOOK_LEASE_SECONDS', '900'))


def claim_event_with_lease(event_id: Optional[str], source: str = 'razorpay',
                           lease_seconds: int = DEFAULT_LEASE_SECONDS,
                           ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
    """Claim an event for `lease_seconds`, releasing it automatically if never completed.

    Returns True when the caller may process. The caller MUST call `complete_event` on success;
    if it does not, the claim lapses and a later delivery reprocesses — which is the entire point.

    Implemented as a compare-and-swap rather than one conditional put with an `OR`:

        1. try a fresh claim on `attribute_not_exists(eventId)`
        2. on failure, read the row. Re-claim only when it carries a lease, has no `completedAt`,
           and that lease has expired — conditional on the lease value we just read.

    Step 2's condition is the observed `leaseExpiresAt`, so two workers racing to salvage the same
    abandoned lease cannot both win. Doing it this way also keeps the expression to equality and
    `attribute_not_exists`, which is what the rest of this codebase's conditions use.

    Fails OPEN, for the same reason `claim_event` does — and it is safer here than it used to be:
    order creation is now guarded by its own conditional markers in
    `lambda_utils/ecommerce/order_keys`, so processing a payment event twice converges on one
    order instead of making two.
    """
    if not event_id:
        return True

    now = int(time.time())
    lease_until = now + max(1, int(lease_seconds))
    expires_at = now + ttl_days * 24 * 60 * 60
    item = {
        'eventId': str(event_id),
        'source': source,
        'processedAt': now,
        'leaseExpiresAt': lease_until,
        'expiresAt': expires_at,
        'ttl': expires_at,
    }

    try:
        _table().put_item(Item=item,
                          ConditionExpression='attribute_not_exists(eventId)')
        return True
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}'
                           % (source, str(error)[:160]))
            return True  # fail open
    except Exception as error:  # noqa: BLE001
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}'
                       % (source, str(error)[:160]))
        return True

    # Someone holds it. Salvage only an expired, uncompleted lease.
    try:
        existing = _table().get_item(Key={'eventId': str(event_id)}).get('Item') or {}
    except Exception as error:  # noqa: BLE001
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}'
                       % (source, str(error)[:160]))
        return True

    if existing.get('completedAt'):
        logger.info('{"event":"webhook_duplicate_skipped","source":"%s","reason":"completed"}'
                    % source)
        return False

    held_until = existing.get('leaseExpiresAt')
    if held_until is None:
        # No lease: written by plain `claim_event` or before leases existed. Treated as a
        # permanent claim, so legacy rows can never be reprocessed by this path.
        logger.info('{"event":"webhook_duplicate_skipped","source":"%s","reason":"no_lease"}'
                    % source)
        return False

    if now < int(held_until):
        logger.info('{"event":"webhook_duplicate_skipped","source":"%s","reason":"lease_held"}'
                    % source)
        return False

    try:
        _table().put_item(
            Item=item,
            # Compare-and-swap on the lease we just observed, so two workers salvaging the same
            # abandoned lease cannot both win.
            ConditionExpression='leaseExpiresAt = :seen',
            ExpressionAttributeValues={':seen': held_until},
        )
        logger.warning('{"event":"webhook_lease_salvaged","source":"%s"}' % source)
        return True
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return False
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}'
                       % (source, str(error)[:160]))
        return True
    except Exception as error:  # noqa: BLE001
        logger.warning('{"event":"webhook_dedup_error","source":"%s","error":"%s"}'
                       % (source, str(error)[:160]))
        return True


def complete_event(event_id: Optional[str], ttl_days: int = DEFAULT_TTL_DAYS) -> None:
    """Close a leased claim permanently. Call this only after the work actually succeeded.

    Not calling it is how a crashed handler releases its claim, so this must be the **last** thing
    a successful path does. Calling it early converts a lease back into the
    claim-before-work-and-never-release behaviour this replaced.

    Never raises. A failure here leaves the lease to expire, which costs one reprocess — and
    reprocessing is safe, because order creation is guarded by its own conditional markers.
    """
    if not event_id:
        return
    now = int(time.time())
    try:
        _table().update_item(
            Key={'eventId': str(event_id)},
            UpdateExpression='SET completedAt = :now',
            ExpressionAttributeValues={':now': now},
        )
    except Exception as error:  # noqa: BLE001
        logger.warning('{"event":"webhook_complete_failed","error":"%s"}'
                       % str(error)[:160])
