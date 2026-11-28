"""
Rate limiting utility backed by the DynamoDB RateLimit table.

Usage:
    from lambda_utils.rate_limit import check_rate_limit

    if not check_rate_limit('whatsapp', phone_number_id, max_per_second=80):
        return cors_response(429, {'error': 'Rate limit exceeded'})

Key schema
----------
``stack-wecare-digital-RateLimitTable`` has a SINGLE partition key, ``id``. It has
no ``channel``/``windowStart`` key, and no sort key at all.

This module used to call ``update_item`` with ``Key={'channel': ..., 'windowStart':
...}`` and a docstring asserting that shape "match[ed] the DynamoDB schema". It did
not. DynamoDB answers a key that does not match the table with
``ValidationException: The provided key element does not match the schema``, the
``except Exception`` below caught it, and the function returned True - so every
caller was told it was under its limit and no rate limit was ever applied.
Confirmed against the live table on 2026-09-25 by a read-only ``GetItem``: the
composite shape is rejected, ``{'id': ...}`` is accepted.

The two real callers were ``operations/bulk-worker`` and
``messaging/partner-onboarding`` - a bulk sender and the partner control plane, i.e.
the two places a throughput limit matters most.

The unit tests did not catch it because they mock ``dynamodb`` wholesale, so
``update_item`` accepted any key. ``test_the_key_matches_the_live_table_schema``
now pins the shape.

``messaging/outbound-whatsapp._check_rate_limit`` already wrote the correct shape
and is what produced the rows in the table; this module is now aligned with it, so
both share one key layout and one set of attributes.
"""

import os
import time
from decimal import Decimal
from typing import Optional

import boto3

from lambda_utils.client_ip import client_ip
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
RATE_LIMIT_TABLE = os.environ.get('RATE_LIMIT_TABLE', 'stack-wecare-digital-RateLimitTable')
TTL_SECONDS = 86400  # 24 hours


def check_rate_limit(
    channel: str,
    resource_id: str,
    max_per_second: int = 80,
    table_name: Optional[str] = None,
) -> bool:
    """
    Atomic increment-and-check against the RateLimit table.

    Returns True if under the limit, False if exceeded.
    Fails open (returns True) on errors, to avoid blocking traffic.

    Keys on ``id`` only - see the module docstring for why that matters.
    """
    try:
        table = dynamodb.Table(table_name or RATE_LIMIT_TABLE)
        now = int(time.time())
        window_key = f"{channel}:{resource_id}"
        window_start = str(now)

        response = table.update_item(
            # `id` is the table's only key attribute. channel and windowStart are
            # written as plain attributes so the row stays readable/queryable,
            # which is also what outbound-whatsapp does.
            Key={'id': f"{window_key}:{window_start}"},
            UpdateExpression=(
                'SET messageCount = if_not_exists(messageCount, :zero) + :inc, '
                'channel = :ch, windowStart = :ws, lastUpdatedAt = :ttl'
            ),
            ExpressionAttributeValues={
                ':zero': Decimal('0'),
                ':inc': Decimal('1'),
                ':ch': window_key,
                ':ws': window_start,
                # An absolute expiry, not a "last touched" stamp: TTL is ENABLED on
                # lastUpdatedAt on the live table, so this must be a future time or
                # the row would be eligible for deletion the moment it is written.
                ':ttl': Decimal(str(now + TTL_SECONDS)),
            },
            ReturnValues='UPDATED_NEW',
        )

        count = int(response.get('Attributes', {}).get('messageCount', 0))
        return count <= max_per_second

    except Exception as e:
        # Fail open deliberately. But a key-schema or missing-table error is a
        # permanent defect that fails open on EVERY call, which is how the broken
        # key above stayed invisible - it looked identical to a transient blip.
        # Log those at error level so "rate limiting is off" is greppable.
        permanent = type(e).__name__ == 'ClientError' and any(
            code in str(e) for code in ('ValidationException', 'ResourceNotFoundException')
        )
        logger.log(
            40 if permanent else 30,  # ERROR : WARNING
            '{"event":"rate_limit_%s","channel":"%s","error_type":"%s"}'
            % (
                'disabled_permanent_error' if permanent else 'error',
                channel,
                type(e).__name__,
            ),
        )
        return True


def check_client_rate_limit(
    channel: str,
    event: dict,
    max_per_second: int = 80,
    table_name: Optional[str] = None,
) -> bool:
    """`check_rate_limit` keyed on the caller's IP, resolved by `lambda_utils.client_ip`.

    Use this rather than reading `sourceIp` directly, so callers behind the Amplify `/api`
    proxy are counted per client once `TRUSTED_PROXY_CIDRS` is set.
    """
    return check_rate_limit(channel, client_ip(event) or 'unknown',
                            max_per_second=max_per_second, table_name=table_name)
