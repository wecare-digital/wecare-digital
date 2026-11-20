"""
AWS Voice Lambda Function

Purpose: Make voice calls via Amazon Pinpoint Voice v2 (us-east-1)
Supports: TTS calls via Polly, SSML
Table: stack-wecare-digital-VoiceAwsTable (dedicated)

Endpoints:
  GET  /voice-aws/calls          - List voice calls
  GET  /voice-aws/calls/{id}     - Get single call
  POST /voice-aws/call           - Make a call
  DELETE /voice-aws/calls/{id}   - Delete call record
  DELETE /voice-aws/clear-logs   - Clear all logs
"""

import os
import json
import uuid
import time
import logging
import boto3
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.validation import normalize_phone
from lambda_utils.message_store import put_call_breadcrumb  # unified timeline breadcrumb

logger = get_logger(__name__)

REGION = 'us-east-1'
dynamodb = boto3.resource('dynamodb', region_name=REGION)
pinpoint_voice = boto3.client('pinpoint-sms-voice-v2', region_name=REGION)

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
VOICE_TABLE = os.environ.get('VOICE_AWS_TABLE', 'stack-wecare-digital-VoiceAwsTable')
ORIGINATION_IDENTITY = os.environ.get('VOICE_ORIGINATION_IDENTITY', '')
VOICE_ID = os.environ.get('VOICE_ID', 'RAVEENA')  # Polly voice (RAVEENA = Indian English)
CALL_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle AWS voice call operations."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    path = event.get('rawPath', event.get('path', ''))
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'voice_aws_handler', 'method': http_method,
        'path': path, 'requestId': request_id
    }))

    try:
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'})

        # Authenticate anything that arrived through API Gateway. require_auth
        # exempts internal Lambda-to-Lambda invokes by testing for an API Gateway
        # request context (apiId / domainName / http.sourceIp - injected by the
        # gateway, not settable by a caller), so the synthetic events built by
        # lambda_utils.comms.notify keep working while the public route stops
        # being anonymous. This endpoint had NO auth at either layer.
        from lambda_utils.middleware import require_auth
        required_role = 'Admin' if http_method == 'DELETE' else None
        _auth = require_auth(event, required_role=required_role)
        if _auth is not None:
            return _auth

        # DELETE /voice-aws/clear-logs
        if http_method == 'DELETE' and 'clear-logs' in path:
            return _clear_logs(request_id)

        # DELETE /voice-aws/calls/{id}
        if http_method == 'DELETE' and path_params.get('callId'):
            return _delete_call(path_params['callId'], request_id)

        # GET /voice-aws/calls/{id}
        if http_method == 'GET' and path_params.get('callId'):
            return _get_call(path_params['callId'], request_id)

        # GET /voice-aws/calls
        if http_method == 'GET':
            return _list_calls(query_params, request_id)

        # POST /voice-aws/call
        if http_method == 'POST':
            body = json.loads(event.get('body', '{}'))
            return _make_call(body, request_id)

        return _response(405, {'error': 'Method not allowed'})

    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})
    except Exception as e:
        logger.error(f"Voice AWS error: {str(e)}", exc_info=True)
        return _response(500, {'error': 'Internal server error'})


def _list_calls(params: Dict, request_id: str) -> Dict[str, Any]:
    """List voice calls from dedicated table."""
    try:
        table = dynamodb.Table(VOICE_TABLE)
        scan_kwargs = {'Limit': int(params.get('limit', 200))}

        from boto3.dynamodb.conditions import Attr
        filters = []
        if params.get('contactId'):
            filters.append(Attr('contactId').eq(params['contactId']))
        if params.get('status'):
            filters.append(Attr('status').eq(params['status']))

        if filters:
            combined = filters[0]
            for f in filters[1:]:
                combined = combined & f
            scan_kwargs['FilterExpression'] = combined

        result = table.scan(**scan_kwargs)
        calls = result.get('Items', [])
        calls.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)

        return _response(200, {
            'calls': [_normalize(c) for c in calls],
            'count': len(calls)
        })
    except Exception as e:
        logger.error(f"List calls error: {str(e)}")
        return _response(500, {'error': str(e)})


def _get_call(call_id: str, request_id: str) -> Dict[str, Any]:
    """Get a single voice call."""
    try:
        table = dynamodb.Table(VOICE_TABLE)
        result = table.get_item(Key={'id': call_id})
        item = result.get('Item')
        if item:
            return _response(200, {'call': _normalize(item)})
        return _response(404, {'error': 'Call not found'})
    except Exception as e:
        logger.error(f"Get call error: {str(e)}")
        return _response(500, {'error': str(e)})


def _delete_call(call_id: str, request_id: str) -> Dict[str, Any]:
    """Delete a single call record."""
    try:
        table = dynamodb.Table(VOICE_TABLE)
        table.delete_item(Key={'id': call_id})
        return _response(200, {'success': True, 'deleted': call_id})
    except Exception as e:
        logger.error(f"Delete call error: {str(e)}")
        return _response(500, {'error': str(e)})


def _clear_logs(request_id: str) -> Dict[str, Any]:
    """Clear all voice call logs (paginated to handle large tables)."""
    try:
        table = dynamodb.Table(VOICE_TABLE)
        deleted = 0
        scan_kwargs = {'ProjectionExpression': 'id, callId'}
        while True:
            result = table.scan(**scan_kwargs)
            items = result.get('Items', [])
            if not items:
                break
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'id': item.get('id', item.get('callId'))})
                    deleted += 1
            if 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return _response(200, {'success': True, 'deletedCount': deleted})
    except Exception as e:
        logger.error(f"Clear logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _make_call(body: Dict, request_id: str) -> Dict[str, Any]:
    """Make a voice call via Pinpoint Voice v2."""
    contact_id = body.get('contactId', '')
    phone_number = body.get('phoneNumber') or body.get('phone')
    message = body.get('message') or body.get('messageText', '')
    voice_id = (body.get('voiceId') or VOICE_ID).upper()
    campaign_id = body.get('campaignId', '')
    campaign_name = body.get('campaignName', '')

    # Normalize phone input to consistent digits-only format
    if phone_number:
        normalized = normalize_phone(phone_number)
        if normalized:
            phone_number = f'+{normalized}'

    if not phone_number and contact_id:
        contact = _get_contact(contact_id)
        phone_number = contact.get('phone') if contact else None

    if not phone_number:
        return _response(400, {'error': 'phoneNumber is required'})

    phone_e164 = _format_e164(phone_number)
    if not phone_e164:
        return _response(400, {'error': 'Invalid phone number format'})

    if not message:
        message = 'Hello, this is a call from WECARE Digital.'

    call_id = str(uuid.uuid4())

    # Build SSML for TTS
    ssml = f'<speak><prosody rate="medium">{message}</prosody></speak>'

    result = _send_voice_message(phone_e164, ssml, voice_id, request_id)

    now = int(time.time())
    _store_call({
        'id': call_id,
        'callId': call_id,
        'contactId': contact_id,
        'phoneNumber': phone_e164,
        'direction': 'OUTBOUND',
        'callType': 'tts',
        'status': 'initiated' if result.get('success') else 'failed',
        'duration': 0,
        'voiceId': voice_id,
        'messageText': message[:500],
        'providerCallId': result.get('providerMessageId', ''),
        'campaignId': campaign_id,
        'campaignName': campaign_name,
        'errorDetails': result.get('error', ''),
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
        'expiresAt': Decimal(str(now + CALL_TTL_SECONDS)),
    })

    if not result.get('success'):
        return _response(500, {
            'error': result.get('error', 'Failed to initiate call'),
            'callId': call_id
        })

    return _response(200, {
        'success': True,
        'callId': call_id,
        'status': 'initiated',
        'providerCallId': result.get('providerMessageId')
    })


def _send_voice_message(phone: str, ssml: str, voice_id: str,
                        request_id: str) -> Dict[str, Any]:
    """Send voice message via Pinpoint SMS Voice v2."""
    try:
        if not ORIGINATION_IDENTITY:
            return {
                'success': False,
                'error': 'Voice origination identity not configured. Set VOICE_ORIGINATION_IDENTITY env var.'
            }

        response = pinpoint_voice.send_voice_message(
            DestinationPhoneNumber=phone,
            OriginationIdentity=ORIGINATION_IDENTITY,
            MessageBody=ssml,
            MessageBodyTextType='SSML',
            VoiceId=voice_id,
        )

        return {
            'success': True,
            'providerMessageId': response.get('MessageId', '')
        }

    except pinpoint_voice.exceptions.ConflictException as e:
        logger.error(f"Pinpoint voice conflict: {str(e)}")
        return {'success': False, 'error': f'Conflict: {str(e)}'}
    except pinpoint_voice.exceptions.ValidationException as e:
        logger.error(f"Pinpoint voice validation: {str(e)}")
        return {'success': False, 'error': f'Validation: {str(e)}'}
    except pinpoint_voice.exceptions.ThrottlingException as e:
        logger.error(f"Pinpoint voice throttled: {str(e)}")
        return {'success': False, 'error': 'Rate limited, try again'}
    except Exception as e:
        logger.error(f"Pinpoint voice error: {str(e)}")
        return {'success': False, 'error': str(e)}


def _format_e164(phone: str) -> str:
    """Format phone number to E.164."""
    if not phone:
        return ''
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        return f'+91{digits}'  # India default
    if len(digits) >= 11 and not phone.startswith('+'):
        return f'+{digits}'
    if phone.startswith('+'):
        return phone
    return f'+{digits}' if digits else ''


def _get_contact(contact_id: str) -> Dict[str, Any]:
    """Get contact from DynamoDB."""
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        response = table.get_item(Key={'id': contact_id})
        return response.get('Item', {})
    except Exception as e:
        logger.error(f"Get contact error: {str(e)}")
        return {}


def _store_call(item: Dict) -> None:
    """Store call record in dedicated voice table."""
    try:
        table = dynamodb.Table(VOICE_TABLE)
        clean = {k: v for k, v in item.items() if v is not None and v != ''}
        table.put_item(Item=clean)
    except Exception as e:
        logger.error(f"Store call error: {str(e)}")

    # Unified timeline breadcrumb — thin 'call' row in MessagesTable (full record stays
    # here in VoiceAwsTable). Idempotent on callId; error-swallowed.
    try:
        dur = item.get('duration')
        put_call_breadcrumb(
            call_id=item.get('callId') or item.get('id'),
            direction=str(item.get('direction', 'OUTBOUND')),
            contact_id=item.get('contactId', ''),
            status=str(item.get('status', '')),
            duration=int(dur) if dur not in (None, '') else None,
            call_type=item.get('callType'),
            phone=item.get('phoneNumber'),
        )
    except Exception as e:
        logger.warning(f"call breadcrumb skipped: {e}")


def _normalize(item: Dict) -> Dict:
    """Normalize call record for API response."""
    return {
        'id': item.get('callId', ''),
        'callId': item.get('callId', ''),
        'contactId': item.get('contactId', ''),
        'phoneNumber': item.get('phoneNumber', ''),
        'provider': 'aws',
        'callType': item.get('callType', 'tts'),
        'status': item.get('status', ''),
        'direction': item.get('direction', 'OUTBOUND'),
        'duration': int(item.get('duration', 0)),
        'voiceId': item.get('voiceId', ''),
        'messageText': item.get('messageText', ''),
        'providerCallId': item.get('providerCallId', ''),
        'campaignId': item.get('campaignId', ''),
        'campaignName': item.get('campaignName', ''),
        'recordingUrl': item.get('recordingUrl', ''),
        'createdAt': int(float(item.get('createdAt', 0))),
        'updatedAt': int(float(item.get('updatedAt', 0))),
    }


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, default=str)
    }
