"""
Messages Read Lambda Function

Purpose: Read messages from WhatsApp Inbound/Outbound tables
Returns combined inbound and outbound messages for dashboard/messaging views.
Supports filtering by contactId, channel, and direction.
Generates pre-signed URLs for media files.

DynamoDB Tables (actual names):
- stack-wecare-digital-WhatsAppInboundTable
- stack-wecare-digital-WhatsAppOutboundTable
"""

import os
import json
import logging
import boto3
from typing import Dict, Any, List, Optional
from decimal import Decimal

from lambda_utils.response import cors_response, options_response, extract_origin
from lambda_utils.logging import get_logger, log_event
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# DynamoDB client
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# DynamoDB table names - actual tables used by the system
INBOUND_TABLE = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
# Other-channel message stores for the Unified Inbox (read-time aggregation).
# SMS_AWS_TABLE removed 2026-09-24. It named
# `stack-wecare-digital-SmsAwsTable`, which does not exist in the account, and it
# was referenced exactly once - by its own definition. SMS lives in the canonical
# MessagesTable under channel='sms'; see messaging/sms-aws/handler.py, whose
# _store_message writes there and nowhere else.
VOICE_AWS_TABLE = os.environ.get('VOICE_AWS_TABLE', 'stack-wecare-digital-VoiceAwsTable')
# RCS_TABLE removed 2026-09-21: unused constant naming a table that does not
# exist. RCS reads come from the canonical MessagesTable.
EMAIL_MESSAGES_TABLE = os.environ.get('EMAIL_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
# Canonical unified message table (all channels). The single source the inbox reads.
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
MEDIA_CDN_DOMAIN = os.environ.get('MEDIA_CDN_DOMAIN', media_paths.CDN_DOMAIN)  # CloudFront host + path

# Pagination defaults
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000
PRESIGNED_URL_EXPIRY = 3600  # 1 hour


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Read messages from DynamoDB Messages table.
    Supports filtering by contactId, channel, and direction.
    """
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    
    # Handle OPTIONS
    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()
    if method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    try:
        # Exact item routes use the canonical MessagesTable and never share the delete handler.
        path_params = event.get('pathParameters', {}) or {}
        message_id = path_params.get('messageId')
        if message_id:
            if method == 'GET':
                return _read_one_message(message_id, request_id, origin)
            if method == 'PUT':
                return _update_payment_message(message_id, event, request_id, origin)
            return cors_response(405, {'error': f'Method {method} not allowed'}, origin)

        params = event.get('queryStringParameters', {}) or {}

        # GET /messages?stats=count — lightweight count-only (no full scan)
        if params.get('stats') == 'count':
            return _count_messages(request_id, origin)

        contact_id = params.get('contactId')
        channel = params.get('channel', '').upper()
        direction = params.get('direction', '').upper()
        limit = min(int(params.get('limit', DEFAULT_LIMIT)), MAX_LIMIT)
        
        # Build filter expression
        filter_parts = []
        expression_values = {}
        
        if contact_id:
            filter_parts.append('contactId = :cid')
            expression_values[':cid'] = contact_id
        
        # VOICE included: `message_store.VALID_CHANNELS` has held it since calls began
        # writing a breadcrumb row, and `[retired public path]/inbox?channel=voice` is now the Calls
        # destination. Its absence here was invisible because the filter built below is
        # not what reads the table - `_read_from_messages_table` queries the GSI and
        # does not consult this whitelist - but a list that silently disagrees with the
        # canonical channel set is the kind of thing that bites the first time somebody
        # does start using it.
        if channel and channel in ['WHATSAPP', 'SMS', 'EMAIL', 'RCS', 'VOICE']:
            filter_parts.append('channel = :ch')
            expression_values[':ch'] = channel.lower()
        
        if direction and direction in ['INBOUND', 'OUTBOUND']:
            filter_parts.append('direction = :dir')
            expression_values[':dir'] = direction.lower()
        
        # Single canonical table read — every channel now lives in MessagesTable
        # (WhatsApp/SMS/RCS/Email via dual-write + backfill). Uses GSIs so reads are
        # bounded Query calls, never full-table scans (anti-overload).
        messages = _read_from_messages_table(contact_id, channel, direction, limit)

        # Sort by timestamp descending
        messages.sort(key=lambda x: float(x.get('timestamp', x.get('createdAt', 0)) or 0), reverse=True)
        
        # Limit results
        messages = messages[:limit]
        
        # Convert for JSON serialization
        messages = [_convert_from_dynamodb(m) for m in messages]
        
        log_event(logger, 'messages_read', count=len(messages), contactId=contact_id, channel=channel, requestId=request_id)
        
        return cors_response(200, {
            'messages': messages,
            'count': len(messages)
        }, origin)
        
    except Exception as e:
        log_event(logger, 'messages_read_error', level='error', error=str(e), requestId=request_id)
        return cors_response(500, {'error': 'Internal server error'}, origin)


def _read_one_message(message_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    result = dynamodb.Table(MESSAGES_TABLE).get_item(Key={'id': message_id})
    item = result.get('Item')
    if not item:
        return cors_response(404, {'error': 'Message not found'}, origin)
    message = _convert_from_dynamodb(item)
    log_event(logger, 'message_read_one', messageId=message_id, requestId=request_id)
    return cors_response(200, {'message': message}, origin)


def _update_payment_message(message_id: str, event: Dict[str, Any], request_id: str, origin: str = '') -> Dict[str, Any]:
    from lambda_utils.middleware import require_auth
    auth_result = require_auth(event, required_role='Admin')
    if auth_result is not None:
        return auth_result
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return cors_response(400, {'error': 'Invalid JSON in request body'}, origin)
    allowed = {
        'paymentItemName', 'paymentQuantity', 'paymentGstRate', 'paymentPurpose',
        'paymentDueRef', 'status', 'paymentDiscount', 'paymentShipping',
        'paymentOrderId', 'paymentCustomerName', 'paymentCustomerPhone',
        'paymentCustomerEmail', 'paymentShippingAddress', 'paymentBillingAddress',
        'paymentPayFor',
    }
    updates = {key: value for key, value in body.items() if key in allowed}
    if not updates:
        return cors_response(400, {'error': 'No valid fields to update'}, origin)
    names, values, parts = {}, {}, []
    for index, (key, value) in enumerate(updates.items()):
        name, val = f'#f{index}', f':v{index}'
        names[name], values[val] = key, value
        parts.append(f'{name} = {val}')
    dynamodb.Table(MESSAGES_TABLE).update_item(
        Key={'id': message_id},
        UpdateExpression='SET ' + ', '.join(parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression='attribute_exists(id)',
    )
    log_event(logger, 'message_payment_updated', messageId=message_id, fields=sorted(updates), requestId=request_id)
    return cors_response(200, {'success': True, 'messageId': message_id, 'updated': sorted(updates)}, origin)


def _count_messages(request_id: str, origin: str = '') -> Dict[str, Any]:
    """Return message counts using Select='COUNT' — no full data scan.
    Counts inbound and outbound separately, also counts today/week via timestamp filter."""
    import time
    from decimal import Decimal as D
    now = int(time.time())
    today_start = now - (now % 86400)  # midnight UTC
    week_start = today_start - 7 * 86400

    totals = {'inbound': 0, 'outbound': 0, 'today': 0, 'week': 0,
              'delivered': 0, 'outboundTotal': 0}

    # Count the single canonical MessagesTable (all channels). Select='COUNT' (no data).
    table = dynamodb.Table(MESSAGES_TABLE)

    def _count(filter_expr=None, names=None, values=None):
        kw: Dict[str, Any] = {'Select': 'COUNT'}
        if filter_expr:
            kw['FilterExpression'] = filter_expr
            if names:
                kw['ExpressionAttributeNames'] = names
            if values:
                kw['ExpressionAttributeValues'] = values
        n = 0
        while True:
            resp = table.scan(**kw)
            n += resp.get('Count', 0)
            if 'LastEvaluatedKey' not in resp:
                break
            kw['ExclusiveStartKey'] = resp['LastEvaluatedKey']
        return n

    try:
        totals['inbound'] = _count('direction = :din', None, {':din': 'inbound'})
        totals['outbound'] = _count('direction = :dout', None, {':dout': 'outbound'})
        totals['today'] = _count('#ts >= :today', {'#ts': 'timestamp'}, {':today': D(str(today_start))})
        totals['week'] = _count('#ts >= :week', {'#ts': 'timestamp'}, {':week': D(str(week_start))})
        totals['outboundTotal'] = totals['outbound']
        totals['delivered'] = _count(
            '#st IN (:dl, :rd, :st) AND direction = :dout',
            {'#st': 'status'},
            {':dl': 'delivered', ':rd': 'read', ':st': 'sent', ':dout': 'outbound'},
        )
    except Exception as e:
        logger.warning(f"Count error on MessagesTable: {e}")

    delivery_rate = (
        round((totals['delivered'] / totals['outboundTotal']) * 100)
        if totals['outboundTotal'] > 0 else 100
    )

    log_event(logger, 'messages_count', **totals, requestId=request_id)
    return cors_response(200, {
        'messagesToday': totals['today'],
        'messagesWeek': totals['week'],
        'totalMessages': totals['inbound'] + totals['outbound'],
        'deliveryRate': delivery_rate,
    }, origin)


def _read_from_messages_table(contact_id: str, channel: str, direction: str, limit: int) -> List[Dict]:
    """Read messages from the canonical MessagesTable using GSIs (bounded queries).

    - contactId given  -> query contactId-index (one conversation, newest first)
    - specific channel -> query channel-index
    - ALL / unspecified -> query channel-index per message channel and merge
    Falls back to a bounded scan if an index isn't available yet. Applies an optional
    direction filter in-memory.
    """
    from boto3.dynamodb.conditions import Key
    table = dynamodb.Table(MESSAGES_TABLE)
    items: List[Dict] = []

    def _page_query(query_kwargs: Dict) -> List[Dict]:
        out: List[Dict] = []
        resp = table.query(**query_kwargs)
        out.extend(resp.get('Items', []))
        while 'LastEvaluatedKey' in resp and len(out) < limit:
            query_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            resp = table.query(**query_kwargs)
            out.extend(resp.get('Items', []))
        return out

    try:
        if contact_id:
            items = _page_query({
                'IndexName': 'contactId-index',
                'KeyConditionExpression': Key('contactId').eq(contact_id),
                'ScanIndexForward': False,
                'Limit': limit,
            })
        elif channel and channel not in ('', 'ALL'):
            items = _page_query({
                'IndexName': 'channel-index',
                'KeyConditionExpression': Key('channel').eq(channel.lower()),
                'ScanIndexForward': False,
                'Limit': limit,
            })
        else:
            for ch in ('whatsapp', 'sms', 'rcs', 'email', 'voice'):
                try:
                    items.extend(_page_query({
                        'IndexName': 'channel-index',
                        'KeyConditionExpression': Key('channel').eq(ch),
                        'ScanIndexForward': False,
                        'Limit': limit,
                    }))
                except Exception as ce:
                    logger.warning(json.dumps({'event': 'channel_query_failed', 'channel': ch, 'error': str(ce)}))
    except Exception as e:
        # Index not ready or query error — fall back to a bounded scan so the inbox
        # still works. TTL keeps the table small, so this stays cheap.
        logger.warning(json.dumps({'event': 'messages_read_query_fallback', 'error': str(e)}))
        items = _scan_messages_table_fallback(contact_id, channel, limit)

    # Optional direction filter (in-memory — cheap on a bounded result set)
    if direction in ('INBOUND', 'OUTBOUND'):
        items = [i for i in items if str(i.get('direction', '')).upper() == direction]

    return items


def _scan_messages_table_fallback(contact_id: str, channel: str, limit: int) -> List[Dict]:
    """Bounded scan of MessagesTable when a GSI isn't usable yet."""
    table = dynamodb.Table(MESSAGES_TABLE)
    kwargs: Dict[str, Any] = {'Limit': max(limit, 1000)}
    filt = []
    vals: Dict[str, Any] = {}
    names: Dict[str, str] = {}
    if contact_id:
        filt.append('contactId = :cid')
        vals[':cid'] = contact_id
    if channel and channel not in ('', 'ALL'):
        filt.append('#ch = :ch')
        names['#ch'] = 'channel'
        vals[':ch'] = channel.lower()
    if filt:
        kwargs['FilterExpression'] = ' AND '.join(filt)
        kwargs['ExpressionAttributeValues'] = vals
        if names:
            kwargs['ExpressionAttributeNames'] = names
    out: List[Dict] = []
    resp = table.scan(**kwargs)
    out.extend(resp.get('Items', []))
    pages = 1
    while 'LastEvaluatedKey' in resp and pages < 20 and len(out) < limit * 2:
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
        resp = table.scan(**kwargs)
        out.extend(resp.get('Items', []))
        pages += 1
    return out


def _convert_from_dynamodb(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB types to Python types and generate pre-signed URLs for media."""
    result = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            result[key] = int(value) if value % 1 == 0 else float(value)
        else:
            result[key] = value
    
    # Normalize field names for frontend
    if 'id' in result and 'messageId' not in result:
        result['messageId'] = result['id']
    
    # Normalize channel and direction to uppercase for frontend
    if 'channel' in result:
        result['channel'] = result['channel'].upper()
    if 'direction' in result:
        result['direction'] = result['direction'].upper()
    
    # Ensure sender name is included for inbound messages
    # Use senderName from DB, fall back to senderPhone, then 'Unknown'
    if result.get('direction') == 'INBOUND':
        if not result.get('senderName'):
            result['senderName'] = result.get('senderPhone', 'Unknown')
    
    # Ensure messageType is included
    if 'messageType' not in result:
        result['messageType'] = 'text'
    
    # Generate pre-signed URL for media files if s3Key exists
    if result.get('s3Key'):
        try:
            s3_key = media_paths.canonical(result['s3Key'])
            media_id = result.get('mediaId')
            message_id = result.get('messageId') or result.get('id')
            message_type = result.get('messageType', 'document')
            
            logger.info(json.dumps({
                'event': 'generating_presigned_url',
                's3Key': s3_key,
                'mediaId': media_id,
                'bucket': MEDIA_BUCKET,
                'messageId': message_id
            }))
            
            # WhatsApp media ID may be appended to the S3 key
            # The stored s3Key might not match the actual file in S3
            # Search S3 with prefix to find the actual file
            actual_s3_key = _find_actual_s3_key(s3_key, message_id)
            
            if actual_s3_key:
                # Use CloudFront CDN URL instead of pre-signed S3 URL
                cdn_url = (s3_client.generate_presigned_url('get_object',
                    Params={'Bucket': MEDIA_BUCKET, 'Key': actual_s3_key}, ExpiresIn=300)
                    if media_paths.is_gated(actual_s3_key)
                    else f"https://{MEDIA_CDN_DOMAIN}/{actual_s3_key}")
                result['mediaUrl'] = cdn_url
                result['actualS3Key'] = actual_s3_key
                
                # Generate clean display filename: wecare-digital-{8chars}.ext
                display_filename = _get_display_filename(actual_s3_key, message_id, message_type)
                result['displayFilename'] = display_filename
                
                logger.info(json.dumps({
                    'event': 'cdn_url_generated',
                    'storedS3Key': s3_key,
                    'actualS3Key': actual_s3_key,
                    'displayFilename': display_filename,
                    'mediaId': media_id,
                    'messageId': message_id,
                    'private': media_paths.is_gated(actual_s3_key)
                }))
            else:
                logger.warning(json.dumps({
                    'event': 'media_file_not_found_in_s3',
                    's3Key': s3_key,
                    'mediaId': media_id,
                    'messageId': message_id
                }))
                result['mediaUrl'] = None
            
        except Exception as e:
            logger.error(json.dumps({
                'event': 'presigned_url_generation_failed',
                's3Key': result.get('s3Key'),
                'mediaId': result.get('mediaId'),
                'messageId': result.get('messageId'),
                'error': str(e),
                'errorType': type(e).__name__
            }))
            result['mediaUrl'] = None
    
    return result


def _get_display_filename(s3_key: str, message_id: str, message_type: str) -> str:
    """
    Generate clean display filename: wecare-digital-{8chars}.ext
    Extracts extension from actual S3 key.
    Handles both old pattern (wecare-digital-{8chars}.jpeg{mediaId}.jpeg)
    and new pattern (wecare-digital-{8chars}/{mediaId}.jpeg).
    """
    # Get extension from actual S3 key
    ext = '.bin'
    if '.' in s3_key:
        # Get the last extension (e.g., .jpeg from ...1234567890.jpeg)
        ext = '.' + s3_key.rsplit('.', 1)[-1]
    
    # Use first 8 chars of message_id
    short_id = (message_id or 'unknown')[:8]
    
    return f"wecare-digital-{short_id}{ext}"


def _find_actual_s3_key(stored_key: str, message_id: str) -> Optional[str]:
    # Root the persisted key before any lookup: rows predating the bucket merge
    # store `stack/...` while the object is at `o/stack/...`.
    """
    Find the actual S3 key by searching with prefix.
    
    The stored s3Key might use the key as a PREFIX with the WhatsApp mediaId appended.
    
    Old pattern: key="...wecare-digital-{8chars}.jpeg" → file="...wecare-digital-{8chars}.jpeg{mediaId}.jpeg"
    New pattern: key="...wecare-digital-{8chars}/"     → file="...wecare-digital-{8chars}/{mediaId}.jpeg"
    
    Both patterns are handled by prefix search.
    """
    try:
        # First try the exact key
        try:
            s3_client.head_object(Bucket=MEDIA_BUCKET, Key=stored_key)
            return stored_key  # Exact key exists
        except s3_client.exceptions.ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise
            # Key doesn't exist, search with prefix
        
        # Extract base prefix for search
        # For old pattern: remove extension to get "...wecare-digital-{8chars}"
        # For new pattern (ends with /): use as-is since it's already a prefix
        if stored_key.endswith('/'):
            base_prefix = stored_key
        elif '.' in stored_key:
            base_prefix = stored_key.rsplit('.', 1)[0]
        else:
            base_prefix = stored_key
        
        logger.info(json.dumps({
            'event': 's3_prefix_search',
            'storedKey': stored_key,
            'searchPrefix': base_prefix,
            'bucket': MEDIA_BUCKET
        }))
        
        # List objects with prefix
        response = s3_client.list_objects_v2(
            Bucket=MEDIA_BUCKET,
            Prefix=base_prefix,
            MaxKeys=5
        )
        
        contents = response.get('Contents', [])
        # Filter out zero-byte folder markers
        real_files = [c for c in contents if c.get('Size', 0) > 0]
        if real_files:
            # Return the first matching file (should be only one)
            actual_key = real_files[0]['Key']
            logger.info(json.dumps({
                'event': 's3_key_found',
                'storedKey': stored_key,
                'actualKey': actual_key,
                'matchCount': len(real_files)
            }))
            return actual_key
        
        # If no match with base prefix, try the full stored key as prefix
        # (in case the file has additional suffix)
        response = s3_client.list_objects_v2(
            Bucket=MEDIA_BUCKET,
            Prefix=stored_key,
            MaxKeys=5
        )
        
        contents = response.get('Contents', [])
        real_files = [c for c in contents if c.get('Size', 0) > 0]
        if real_files:
            actual_key = real_files[0]['Key']
            logger.info(json.dumps({
                'event': 's3_key_found_with_full_prefix',
                'storedKey': stored_key,
                'actualKey': actual_key
            }))
            return actual_key
        
        logger.warning(json.dumps({
            'event': 's3_key_not_found',
            'storedKey': stored_key,
            'searchPrefix': base_prefix
        }))
        return None
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 's3_key_search_error',
            'storedKey': stored_key,
            'error': str(e)
        }))
        return None
