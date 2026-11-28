"""
Media Cleanup Lambda Function

Purpose: Delete expired WhatsApp media IDs from Meta servers.
WhatsApp media IDs expire after 30 days, but calling DELETE explicitly
frees storage sooner and is good hygiene.

Triggered on schedule (EventBridge daily) or manually.
Scans MediaFilesTable for records older than 25 days and calls
Meta Graph API DELETE /{media_id} for each.
"""

import os
import json
import time
import logging
import hmac
import hashlib
import boto3
import urllib.request
import urllib.error
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.middleware import require_auth
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

MEDIA_FILES_TABLE = os.environ.get('MEDIA_FILES_TABLE', 'stack-wecare-digital-MediaFilesTable')
PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
CLEANUP_AGE_DAYS = int(os.environ.get('CLEANUP_AGE_DAYS', '25'))
MAX_DELETIONS = int(os.environ.get('MAX_DELETIONS', '50'))
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import

_token_cache = {}

def _load_token():
    if 'token' in _token_cache:
        return
    resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
    data = json.loads(resp['SecretString'])
    _token_cache['token'] = (data.get('access_token') or '').strip()
    _token_cache['app_secret'] = (data.get('app_secret') or '').strip()

def _delete_media_from_meta(media_id: str) -> bool:
    """Delete media from Meta via Graph API: DELETE /{media_id}."""
    _load_token()
    token = _token_cache['token']
    app_secret = _token_cache.get('app_secret', '')
    url = f"https://graph.facebook.com/{META_API_VERSION}/{media_id}"
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
    }, method='DELETE')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True  # Already deleted
        raise


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete expired WhatsApp media from Meta servers."""
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)

    # ── Authenticate API Gateway callers ──
    # POST /media/cleanup was public with no handler check, and this function
    # DELETES media from Meta. Anonymous, destructive, and irreversible.
    # The legitimate callers are the schedule and the dashboard: a scheduled or
    # internal invoke carries no API Gateway context, so require_auth passes it
    # through untouched and only the public route is gated. Deleting media is Admin-only.
    auth_failure = require_auth(event, required_role='Admin')
    if auth_failure is not None:
        return auth_failure

    deleted = 0
    failed = 0
    skipped = 0
    candidates = 0
    scan_failed = False

    cutoff = int(time.time()) - (CLEANUP_AGE_DAYS * 86400)

    logger.info(json.dumps({
        'event': 'media_cleanup_start',
        'cutoffTimestamp': cutoff,
        'cutoffDays': CLEANUP_AGE_DAYS,
        'maxDeletions': MAX_DELETIONS,
        'requestId': request_id
    }))

    try:
        table = dynamodb.Table(MEDIA_FILES_TABLE)
        items = []
        # Cleaned rows are excluded here; otherwise the first MAX_DELETIONS cleaned rows
        # fill every run and newer media is never reached.
        scan_kwargs = {
            'FilterExpression': ('uploadedAt < :cutoff AND attribute_exists(whatsappMediaId) '
                                 'AND attribute_not_exists(cleanedUp)'),
            'ExpressionAttributeValues': {':cutoff': Decimal(str(cutoff))},
        }
        while True:
            response = table.scan(**scan_kwargs)
            items.extend(response.get('Items', []))
            if len(items) >= MAX_DELETIONS or 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        logger.info(json.dumps({
            'event': 'media_cleanup_scan',
            'foundCount': len(items),
            'requestId': request_id
        }))

        candidates = len(items[:MAX_DELETIONS])
        for item in items[:MAX_DELETIONS]:
            media_id = item.get('whatsappMediaId', '')
            # `id` is the table's hash key; `fileId` is a copy that older rows may lack.
            file_id = item.get('id', '')

            if not media_id or not file_id:
                skipped += 1
                continue

            if item.get('cleanedUp'):
                skipped += 1
                continue

            try:
                _delete_media_from_meta(media_id)

                table.update_item(
                    Key={'id': file_id},
                    UpdateExpression='SET cleanedUp = :t, cleanedUpAt = :now',
                    ExpressionAttributeValues={
                        ':t': True,
                        ':now': Decimal(str(int(time.time())))
                    }
                )

                deleted += 1
                logger.info(json.dumps({
                    'event': 'media_deleted',
                    'mediaId': media_id,
                    'fileId': file_id,
                    'requestId': request_id
                }))

            except Exception as e:
                failed += 1
                logger.warning(json.dumps({
                    'event': 'media_delete_error',
                    'mediaId': media_id,
                    'fileId': file_id,
                    'error': str(e),
                    'requestId': request_id
                }))

    except Exception as e:
        scan_failed = True
        logger.error(json.dumps({
            'event': 'media_cleanup_error',
            'error': str(e),
            'requestId': request_id
        }))

    summary = {
        'event': 'media_cleanup_complete',
        'candidates': candidates,
        'deleted': deleted,
        'failed': failed,
        'skipped': skipped,
        'requestId': request_id
    }
    if scan_failed or (candidates and not deleted):
        # Nothing could be processed: a metric filter on this key is what notices.
        summary['alert'] = 'MEDIA_CLEANUP_NOTHING_PROCESSED'
        logger.error(json.dumps(summary))
    else:
        logger.info(json.dumps(summary))

    return {
        'statusCode': 200,
        'body': json.dumps({
            'deleted': deleted,
            'failed': failed,
            'skipped': skipped
        })
    }
