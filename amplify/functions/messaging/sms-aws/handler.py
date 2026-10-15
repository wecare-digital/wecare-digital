"""
AWS SMS Lambda Function

Purpose: Send SMS via AWS End User Messaging (pinpoint-sms-voice-v2),
us-east-1 and ap-south-1. This is the ONLY SMS sender in the account.

Endpoints:
  GET  /sms-aws/messages          - List SMS messages
  GET  /sms-aws/messages/{id}     - Get single message
  POST /sms-aws/send              - Send SMS
  DELETE /sms-aws/messages/{id}   - Delete message
  DELETE /sms-aws/clear-logs      - Clear all logs

Removed 2026-09-19: the `/templates` CRUD routes and their classic-Pinpoint
client. Those managed legacy Pinpoint SMS templates, which are a different thing
from TRAI DLT content templates and cannot satisfy DLT - the handler already said
so in a comment while the UI still offered the tab. India DLT templates are
registered on the DLT portal and recorded in the DLTTemplates registry, which
`lambda_utils.comms.dlt` reads.

Regulatory identity (entity id, sender id, approved template ids) is NOT defined
here. It lives in `lambda_utils.comms.dlt`, and the module-level names below are
thin re-exports so there is one source of truth rather than a copy per Lambda.
"""

import os
import json
import uuid
import time
import logging
import boto3
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.comms import dlt as dlt_mod
from lambda_utils.comms import numbers
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.validation import normalize_phone
from lambda_utils.message_store import put_message  # canonical MessagesTable writer

logger = get_logger(__name__)

REGION = 'us-east-1'
INDIA_REGION = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=REGION)
pinpoint_sms = boto3.client('pinpoint-sms-voice-v2', region_name=REGION)

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
# SMS rows live only in the canonical MessagesTable (channel='sms'): every read,
# write and delete in this function targets it.
UNIFIED_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
# Non-India origination identity. MUST be pinned to a real number.
#
# The account also owns +14255556333, which is NumberType SIMULATOR. Simulator
# numbers accept a send and return a MessageId WITHOUT delivering anything - they
# exist to exercise delivery-status handling. Both numbers sit in the same pool,
# so pinning the pool would not exclude the simulator. With this unset, AWS picks
# an identity from the account and international traffic can silently vanish
# while the API reports success.
#
# +18444891209 is the registered toll-free number with
# InternationalSendingEnabled=true (AWS enabled this for US toll-free in Aug
# 2025). Rate limit is 3 SMS/sec.
ORIGINATION_IDENTITY = os.environ.get('ORIGINATION_IDENTITY', '+18444891209')
SENDER_ID = os.environ.get('SENDER_ID', 'WECARE')
MESSAGE_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days

# --- India DLT (TRAI) -------------------------------------------------------
# Re-exported from lambda_utils.comms.dlt, which is the single source of truth.
# These names are kept because callers and tests already reference them, but the
# VALUES are no longer defined here. The identical map previously lived in five
# places - this module, outbound-sms, whatsapp-calling and the
# data model defaults - and five copies of a regulatory identifier is five
# chances to send unregistered content under a registered sender.
INDIA_ENTITY_ID = dlt_mod.ENTITY_ID
INDIA_SENDER_ID = os.environ.get('INDIA_SENDER_ID', '') or dlt_mod.SENDER_ID
INDIA_DLT_TEMPLATES = dlt_mod.TEMPLATES
INDIA_DEFAULT_DLT_TEMPLATE = dlt_mod.DEFAULT_TEMPLATE_KEY


def _is_indian_msisdn(phone_e164: str) -> bool:
    """True for +91XXXXXXXXXX (12 digits including the 91 country code)."""
    return numbers.is_india(phone_e164)


def _resolve_dlt_template(template_key: str) -> Dict[str, Any]:
    """Map a template key to an approved DLT template id.

    Returns {'templateId': ..., 'templateKey': ...} on success, or {'error': ...}
    when no approved mapping exists. Callers MUST NOT send to an Indian number
    without one - silently sending unregistered content risks operator blocking
    and DLT penalties, so this is a hard failure by design.

    Delegates to comms.dlt, which also consults the operator-managed DLTTemplates
    registry for keys outside the built-in map.
    """
    resolution = dlt_mod.resolve(template_key)
    if not resolution.ok:
        return {'error': resolution.error}
    return {'templateId': resolution.template_id,
            'templateKey': resolution.template_key}


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle AWS SMS operations."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    path = event.get('rawPath', event.get('path', ''))
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'sms_aws_handler', 'method': http_method,
        'path': path, 'requestId': request_id
    }))

    try:
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'}, origin)

        # Authenticate anything that arrived through API Gateway. require_auth
        # exempts internal Lambda-to-Lambda invokes by testing for an API Gateway
        # request context (apiId / domainName / http.sourceIp - injected by the
        # gateway, not settable by a caller), so the synthetic events built by
        # lambda_utils.comms.notify keep working while the public route stops
        # being anonymous. This endpoint had NO auth at either layer.
        from lambda_utils.middleware import require_auth
        _auth = require_auth(event)
        if _auth is not None:
            return _auth

        # TRAI DLT template registry. This is regulatory application data and is
        # independent of the transport used to deliver SMS.
        if '/dlt-templates' in path:
            return _dlt_templates_route(http_method, event, query_params,
                                        path_params, request_id)

        # /sms-aws/templates is GONE. It managed classic Pinpoint SMS templates,
        # which cannot satisfy TRAI DLT. Answer explicitly rather than falling
        # through to the send or list handler, so a stale client gets a usable
        # error instead of an unrelated 200.
        if '/templates' in path:
            return _response(410, {
                'error': 'Pinpoint SMS template management has been removed.',
                'errorCode': 'ENDPOINT_REMOVED',
                'detail': ('Classic Pinpoint templates are not TRAI DLT content '
                           'templates and cannot be used for Indian A2P SMS. '
                           'DLT templates are registered on the DLT portal and '
                           'recorded in the DLTTemplates registry, served at '
                           '/sms-aws/dlt-templates.'),
                'approvedTemplateKeys': dlt_mod.known_keys(),
            }, origin)

        # DELETE /sms-aws/clear-logs
        if http_method == 'DELETE' and 'clear-logs' in path:
            return _clear_logs(request_id)

        # DELETE /sms-aws/messages/{id}
        if http_method == 'DELETE' and path_params.get('messageId'):
            return _delete_message(path_params['messageId'], request_id)

        # GET /sms-aws/messages/{id}
        if http_method == 'GET' and path_params.get('messageId'):
            return _get_message(path_params['messageId'], request_id)

        # GET /sms-aws/messages
        if http_method == 'GET':
            return _list_messages(query_params, request_id)

        # POST /sms-aws/send
        if http_method == 'POST':
            body = json.loads(event.get('body', '{}'))
            return _send_sms(body, request_id)

        return _response(405, {'error': 'Method not allowed'}, origin)

    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'}, origin)
    except Exception as e:
        logger.error(f"SMS AWS error: {str(e)}", exc_info=True)
        return _response(500, {'error': 'Internal server error'}, origin)


def _list_messages(params: Dict, request_id: str) -> Dict[str, Any]:
    """List SMS messages from the canonical MessagesTable (channel=sms).
    Reads via channel-index (bounded Query, no scan). Response shape unchanged."""
    try:
        from boto3.dynamodb.conditions import Key
        table = dynamodb.Table(UNIFIED_TABLE)
        limit = int(params.get('limit', 200))
        resp = table.query(
            IndexName='channel-index',
            KeyConditionExpression=Key('channel').eq('sms'),
            ScanIndexForward=False,  # newest first
            Limit=max(limit, 200),
        )
        messages = resp.get('Items', [])
        # In-memory filters (SMS volume is small; keeps the query simple).
        cid = params.get('contactId')
        st = params.get('status')
        dirn = params.get('direction')
        if cid:
            messages = [m for m in messages if m.get('contactId') == cid]
        if st:
            messages = [m for m in messages if str(m.get('status', '')).lower() == st.lower()]
        if dirn:
            messages = [m for m in messages if str(m.get('direction', '')).lower() == dirn.lower()]
        messages.sort(key=lambda x: float(x.get('timestamp', x.get('createdAt', 0)) or 0), reverse=True)
        messages = messages[:limit]
        return _response(200, {
            'messages': [_normalize(m) for m in messages],
            'count': len(messages)
        })
    except Exception as e:
        logger.error(f"List messages error: {str(e)}")
        return _response(500, {'error': str(e)})


def _get_message(message_id: str, request_id: str) -> Dict[str, Any]:
    """Get a single SMS message from the canonical MessagesTable."""
    try:
        table = dynamodb.Table(UNIFIED_TABLE)
        result = table.get_item(Key={'id': message_id})
        item = result.get('Item')
        if item:
            return _response(200, {'message': _normalize(item)})
        return _response(404, {'error': 'Message not found'})
    except Exception as e:
        logger.error(f"Get message error: {str(e)}")
        return _response(500, {'error': str(e)})


def _delete_message(message_id: str, request_id: str) -> Dict[str, Any]:
    """Delete a single SMS message from the canonical table."""
    try:
        dynamodb.Table(UNIFIED_TABLE).delete_item(Key={'id': message_id})
        return _response(200, {'success': True, 'deleted': message_id})
    except Exception as e:
        logger.error(f"Delete message error: {str(e)}")
        return _response(500, {'error': str(e)})


def _clear_logs(request_id: str) -> Dict[str, Any]:
    """Clear SMS logs — deletes ONLY channel=sms rows from the canonical table
    (scoped via channel-index, so other channels are never touched)."""
    try:
        from boto3.dynamodb.conditions import Key
        table = dynamodb.Table(UNIFIED_TABLE)
        deleted = 0
        last_key = None
        while True:
            q = {
                'IndexName': 'channel-index',
                'KeyConditionExpression': Key('channel').eq('sms'),
                'ProjectionExpression': 'id',
            }
            if last_key:
                q['ExclusiveStartKey'] = last_key
            result = table.query(**q)
            items = result.get('Items', [])
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'id': item['id']})
                    deleted += 1
            last_key = result.get('LastEvaluatedKey')
            if not last_key:
                break
        return _response(200, {'success': True, 'deletedCount': deleted})
    except Exception as e:
        logger.error(f"Clear logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _send_sms(body: Dict, request_id: str) -> Dict[str, Any]:
    """Send SMS via Amazon Pinpoint SMS v2."""
    contact_id = body.get('contactId', '')
    phone_number = body.get('phoneNumber') or body.get('phone')
    content = body.get('content', '')
    message_type = body.get('messageType', 'TRANSACTIONAL')
    campaign_id = body.get('campaignId', '')
    campaign_name = body.get('campaignName', '')
    target_region = body.get('region', '')  # Optional: 'ap-south-1' for India fallback

    # Normalize to digits, but PRESERVE whether the caller supplied a country
    # code. normalize_phone() strips the '+', so unconditionally re-adding it
    # would turn a bare local number like 9903300044 into '+9903300044', where
    # '990' is not a country code. _format_e164() then has no way to tell a
    # supplied country code from an invented one.
    if phone_number:
        had_country_code = str(phone_number).strip().startswith('+')
        normalized = normalize_phone(phone_number)
        if normalized:
            phone_number = f'+{normalized}' if had_country_code else normalized

    if not phone_number and contact_id:
        contact = _get_contact(contact_id)
        phone_number = contact.get('phone') if contact else None

    if not phone_number:
        return _response(400, {'error': 'phoneNumber is required'})
    if not content:
        return _response(400, {'error': 'content is required'})

    phone_e164 = _format_e164(phone_number)
    if not phone_e164:
        return _response(400, {'error': 'Invalid phone number format'})

    message_id = str(uuid.uuid4())

    # Route by destination country, not by caller opt-in.
    # Previously this block detected an Indian number and then did nothing
    # (literally `pass`), so +91 traffic went out via us-east-1 with no DLT
    # parameters. Indian A2P requires ap-south-1 + WDBEEP + entity/template ids.
    use_india_region = _is_indian_msisdn(phone_e164) or target_region == 'ap-south-1'

    dlt: Dict[str, Any] = {}
    if use_india_region:
        dlt = _resolve_dlt_template(body.get('dltTemplateKey') or body.get('templateKey'))
        if dlt.get('error'):
            # Fail loudly rather than send unregistered content to an Indian number.
            logger.error(json.dumps({
                'event': 'sms_missing_dlt_template',
                'phone': phone_e164[-4:],
                'requestedKey': body.get('dltTemplateKey') or body.get('templateKey') or '(none)',
                'requestId': request_id,
            }))
            return _response(422, {
                'error': 'MISSING_DLT_TEMPLATE',
                'detail': dlt['error'],
                'destination': 'IN',
            })

    # DryRun validates origination identity, DLT parameters and destination
    # without delivering anything. Used for pre-cutover verification.
    dry_run = bool(body.get('dryRun') or body.get('dry_run'))

    # Send via Pinpoint SMS v2
    result = _send_pinpoint_sms(phone_e164, content, message_type, request_id,
                                use_india_region=use_india_region,
                                dlt_template_id=dlt.get('templateId'),
                                dry_run=dry_run)

    if dry_run:
        # Nothing was delivered, so do not write a message record.
        if not result.get('success'):
            return _response(400, {'dryRun': True, 'valid': False,
                                   'error': result.get('error', 'validation failed')})
        return _response(200, {
            'dryRun': True,
            'valid': True,
            'route': INDIA_REGION if use_india_region else REGION,
            'originationIdentity': INDIA_SENDER_ID if use_india_region else ORIGINATION_IDENTITY,
            'dltEntityId': INDIA_ENTITY_ID if use_india_region else None,
            'dltTemplateId': dlt.get('templateId') if use_india_region else None,
            'dltTemplateKey': dlt.get('templateKey') if use_india_region else None,
        })

    now = int(time.time())
    _store_message({
        'id': message_id,
        'messageId': message_id,
        'contactId': contact_id,
        'phoneNumber': phone_e164,
        'content': content,
        'direction': 'OUTBOUND',
        'status': 'SENT' if result.get('success') else 'FAILED',
        'messageType': message_type,
        'senderId': SENDER_ID,
        'providerMessageId': result.get('providerMessageId', ''),
        'campaignId': campaign_id,
        'campaignName': campaign_name,
        'errorDetails': result.get('error', ''),
        'createdAt': Decimal(str(now)),
        'expiresAt': Decimal(str(now + MESSAGE_TTL_SECONDS)),
    })

    if not result.get('success'):
        return _response(500, {
            'error': result.get('error', 'Failed to send SMS'),
            'messageId': message_id
        })

    return _response(200, {
        'success': True,
        'messageId': message_id,
        'status': 'sent',
        'providerMessageId': result.get('providerMessageId')
    })


def _send_pinpoint_sms(phone: str, content: str, message_type: str,
                       request_id: str, use_india_region: bool = False,
                       dlt_template_id: str = None,
                       dry_run: bool = False) -> Dict[str, Any]:
    """Send SMS via Pinpoint SMS Voice v2 API.

    Routing is by destination country:
    - ap-south-1 for +91: OriginationIdentity=WDBEEP (registered sender id) plus
      DestinationCountryParameters IN_ENTITY_ID / IN_TEMPLATE_ID, which TRAI DLT
      requires. Without these the operator rejects the message.
    - us-east-1 for everything else: existing international/toll-free origination
      identity, and NO Indian DLT fields (they are invalid outside India).
    """
    try:
        if use_india_region:
            # Use ap-south-1 Pinpoint SMS v2 client for India
            india_sms_client = boto3.client('pinpoint-sms-voice-v2', region_name=INDIA_REGION)
            params: Dict[str, Any] = {
                'DestinationPhoneNumber': phone,
                'MessageBody': content,
                'MessageType': message_type,
            }
            # Use India sender ID if available
            if INDIA_SENDER_ID:
                params['OriginationIdentity'] = INDIA_SENDER_ID

            # --- TRAI DLT: mandatory for Indian A2P traffic ---
            country_params: Dict[str, str] = {}
            if INDIA_ENTITY_ID:
                country_params['IN_ENTITY_ID'] = INDIA_ENTITY_ID
            if dlt_template_id:
                country_params['IN_TEMPLATE_ID'] = dlt_template_id
            if country_params:
                params['DestinationCountryParameters'] = country_params

            if dry_run:
                params['DryRun'] = True

            response = india_sms_client.send_text_message(**params)
            logger.info(json.dumps({
                'event': 'aws_sms_india_sent',
                'phone': phone[-4:],
                'region': INDIA_REGION,
                'senderId': INDIA_SENDER_ID,
                'dltEntityId': INDIA_ENTITY_ID,
                'dltTemplateId': dlt_template_id or '',
                'dryRun': dry_run,
                'messageId': response.get('MessageId', ''),
                'requestId': request_id,
            }))
            return {
                'success': True,
                'providerMessageId': response.get('MessageId', ''),
                'region': INDIA_REGION,
                'dltTemplateId': dlt_template_id or '',
            }
        else:
            params: Dict[str, Any] = {
                'DestinationPhoneNumber': phone,
                'MessageBody': content,
                'MessageType': message_type,
            }

            # Only set origination identity if it's an SMS-capable resource
            if ORIGINATION_IDENTITY:
                params['OriginationIdentity'] = ORIGINATION_IDENTITY

            response = pinpoint_sms.send_text_message(**params)

            return {
                'success': True,
                'providerMessageId': response.get('MessageId', '')
            }

    except pinpoint_sms.exceptions.ConflictException as e:
        logger.error(f"Pinpoint conflict: {str(e)}")
        return {'success': False, 'error': f'Conflict: {str(e)}'}
    except pinpoint_sms.exceptions.ValidationException as e:
        logger.error(f"Pinpoint validation: {str(e)}")
        return {'success': False, 'error': f'Validation: {str(e)}'}
    except pinpoint_sms.exceptions.ThrottlingException as e:
        logger.error(f"Pinpoint throttled: {str(e)}")
        return {'success': False, 'error': 'Rate limited, try again'}
    except Exception as e:
        logger.error(f"Pinpoint SMS error ({INDIA_REGION if use_india_region else REGION}): {str(e)}")
        return {'success': False, 'error': str(e)}


def _format_e164(phone: str) -> str:
    """Format a phone number to E.164.

    An explicit leading '+' means the caller already supplied a country code, so
    it is honoured as-is. Only a BARE 10-digit number is assumed to be an Indian
    local number.

    This distinction matters: the previous version applied the +91 default to any
    10-digit string, including numbers that already carried a country code. A
    Singapore number such as +6581234567 is exactly 10 digits, so it became
    +916581234567 - a different, unrelated Indian subscriber - and was then
    routed to ap-south-1 with a DLT template attached. That is a misdelivery,
    not just a misroute. The same applied to Hong Kong, Denmark, Norway and
    Portugal, all of which are 10 digits in full E.164 form.
    """
    if not phone:
        return ''
    raw = str(phone).strip()
    digits = ''.join(c for c in raw if c.isdigit())
    if not digits:
        return ''
    if raw.startswith('+'):
        # Country code already present - never re-prefix.
        return f'+{digits}'
    if len(digits) == 10:
        # Bare local number with no country code: India.
        return f'+91{digits}'
    return f'+{digits}'


def _get_contact(contact_id: str) -> Dict[str, Any]:
    """Get contact from DynamoDB."""
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        response = table.get_item(Key={'id': contact_id})
        return response.get('Item', {})
    except Exception as e:
        logger.error(f"Get contact error: {str(e)}")
        return {}


def _store_message(item: Dict) -> None:
    """Store an SMS message in the canonical MessagesTable (channel='sms').

    That table is the only SMS store; every reader queries it.
    """
    # Ensure 'id' is present for the canonical messageId.
    if 'id' not in item and 'messageId' in item:
        item['id'] = item['messageId']

    # Canonical write (single source of truth for the unified inbox).
    direction = str(item.get('direction', 'OUTBOUND')).lower()
    phone = item.get('phoneNumber', '')
    put_message(
        channel='sms',
        direction=direction if direction in ('inbound', 'outbound') else 'outbound',
        contact_id=item.get('contactId', ''),
        content=item.get('content', ''),
        status=item.get('status', 'sent'),
        message_id=item.get('messageId') or item.get('id'),
        message_type=item.get('messageType') or 'text',
        provider_message_id=item.get('providerMessageId') or None,
        error_details=item.get('errorDetails') or None,
        sender_phone=phone if direction == 'inbound' else None,
        receiving_phone=phone if direction != 'inbound' else None,
    )


def _normalize(item: Dict) -> Dict:
    """Normalize message for API response. Maps canonical fields (receivingPhone/
    senderPhone, timestamp) back to the SMS page's expected shape."""
    ts = item.get('timestamp', item.get('createdAt', 0))
    return {
        'id': item.get('id', item.get('messageId', '')),
        'messageId': item.get('messageId', item.get('id', '')),
        'contactId': item.get('contactId', ''),
        'phoneNumber': item.get('phoneNumber') or item.get('receivingPhone') or item.get('senderPhone') or '',
        'content': item.get('content', ''),
        'direction': str(item.get('direction', 'OUTBOUND')).upper(),
        'status': item.get('status', ''),
        'messageType': item.get('messageType', ''),
        'senderId': item.get('senderId', ''),
        'providerMessageId': item.get('providerMessageId', ''),
        'campaignId': item.get('campaignId', ''),
        'campaignName': item.get('campaignName', ''),
        'channel': 'SMS',
        'provider': 'aws',
        'timestamp': int(float(ts or 0)),
        'createdAt': int(float(item.get('createdAt', ts or 0) or 0)),
    }


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, default=str)
    }


# ─── TRAI DLT template registry ──────────────────────────────────────────────
# GET    /sms-aws/dlt-templates          list registered templates
# GET    /sms-aws/dlt-templates/{id}     one template
# POST   /sms-aws/dlt-templates          record a portal-approved template
# PUT    /sms-aws/dlt-templates          patch a registered template
# DELETE /sms-aws/dlt-templates?templateId=...
#
# The registry CRUD lives beside the only SMS sender. The logic is in
# lambda_utils/comms/dlt_registry.py so it is unit-testable without a Lambda
# event, and so it sits beside comms/dlt.py, which reads what this writes.
def _dlt_templates_route(method: str, event: Dict, query_params: Dict,
                         path_params: Dict, request_id: str) -> Dict[str, Any]:
    from lambda_utils.comms import dlt_registry

    try:
        if method == 'GET':
            template_id = path_params.get('templateId') or query_params.get('templateId')
            if template_id:
                found = dlt_registry.get_template(template_id)
                if not found:
                    return _response(404, {'error': 'Template not found'})
                return _response(200, {'template': found})
            return _response(200, dlt_registry.list_templates(
                limit=int(query_params.get('limit', 100) or 100)))

        if method == 'POST':
            body = json.loads(event.get('body', '{}') or '{}')
            return _response(200, {'success': True,
                                   'template': dlt_registry.create_template(body)})

        if method == 'PUT':
            body = json.loads(event.get('body', '{}') or '{}')
            return _response(200, {'success': True,
                                   'template': dlt_registry.update_template(body)})

        if method == 'DELETE':
            template_id = (path_params.get('templateId')
                           or query_params.get('templateId'))
            return _response(200, {'success': True,
                                   **dlt_registry.delete_template(template_id)})

        return _response(405, {'error': 'Method not allowed'})

    except dlt_registry.RegistryError as exc:
        # A caller-correctable problem. 404 for a missing row, 409 for the
        # built-in protection, 400 otherwise - never 500, which would send a
        # client into retrying a request that can never succeed.
        status = {'NOT_FOUND': 404, 'BUILTIN_TEMPLATE_PROTECTED': 409}.get(exc.code, 400)
        logger.warning(json.dumps({
            'event': 'dlt_registry_rejected', 'code': exc.code,
            'requestId': request_id,
        }))
        return _response(status, {'error': str(exc), 'errorCode': exc.code})
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            'event': 'dlt_registry_error',
            'error': f'{type(exc).__name__}: {str(exc)[:200]}',
            'requestId': request_id,
        }))
        return _response(500, {'error': 'Internal server error'})
