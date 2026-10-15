"""Outbound SMS - AWS End User Messaging only.

    POST /sms/send    send one SMS

AWS End User Messaging is the only SMS transport, in every country. Every send
resolves through `lambda_utils.comms` (`get_sms_service().send_sms`), which owns
E.164 normalisation, region selection and the India TRAI DLT gate. This function
contains no transport of its own, and there is no fallback: a failed send is
reported as a failure (422 for a missing or unapproved DLT template, 502 for a
transport error) and is never retried through anything else.

`scripts/check-provider-policy.sh` is the CI gate that keeps it that way.

The `provider` request field
----------------------------
Accepted and validated, never honoured as a choice. Absent, `'aws'` and
`'aws-end-user-messaging'` proceed. Any other value is refused with 422
`UNSUPPORTED_PROVIDER` and nothing is sent, so a caller can never believe it
selected a different carrier while silently getting AWS.
"""

import json
import os
import uuid
from typing import Any, Dict

import boto3

from lambda_utils.comms import dlt as dlt_mod
from lambda_utils.comms import get_sms_service
from lambda_utils.logging import get_logger, log_event
from lambda_utils.message_store import put_message  # canonical MessagesTable writer
from lambda_utils.response import cors_headers, extract_origin

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')

# Values a caller may pass for `provider`. AWS End User Messaging is the only
# transport; '' means "no preference". Anything else is refused, not a routing hint.
_ALLOWED_PROVIDERS = {'', 'aws', 'aws-end-user-messaging'}
PROVIDER_POLICY_MESSAGE = (
    'SMS is sent exclusively through AWS End User Messaging. '
    'Omit "provider" or pass "aws".'
)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Send one SMS through AWS End User Messaging."""
    request_id = getattr(context, 'aws_request_id', 'local') if context else 'local'
    global origin
    origin = extract_origin(event)

    method = (event.get('requestContext', {}).get('http', {}) or {}).get('method', 'POST')
    if method == 'OPTIONS':
        return _response(200, {'message': 'OK'})
    # Authenticate anything that arrived through API Gateway. require_auth
    # exempts internal Lambda-to-Lambda invokes by testing for an API Gateway
    # request context (apiId / domainName / http.sourceIp - injected by the
    # gateway, not settable by a caller), so synthetic internal events keep
    # working while the public route stops being anonymous. This endpoint had
    # NO auth at either layer.
    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    log_event(logger, 'outbound_sms_start', requestId=request_id)

    try:
        body = json.loads(event.get('body', '{}') or '{}')
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})

    try:
        requested_provider = str(body.get('provider', '') or '').strip().lower()
        if requested_provider not in _ALLOWED_PROVIDERS:
            log_event(logger, 'outbound_sms_unsupported_provider', level='warning',
                      provider=requested_provider, requestId=request_id)
            return _response(422, {
                'error': PROVIDER_POLICY_MESSAGE,
                'errorCode': 'UNSUPPORTED_PROVIDER',
                'requestedProvider': requested_provider,
            })

        contact_id = body.get('contactId')
        phone_number = body.get('phoneNumber')
        content = body.get('content', '')

        if not contact_id and not phone_number:
            return _response(400, {'error': 'contactId or phoneNumber is required'})
        if not content:
            return _response(400, {'error': 'content is required'})

        phone = phone_number
        if contact_id:
            contact = _get_contact(contact_id)
            if not contact:
                return _response(404, {'error': 'Contact not found'})
            phone = contact.get('phone', '') or phone_number

        template_key, template_error = _resolve_template_key(body)
        if template_error:
            return _response(422, {
                'error': template_error,
                'errorCode': 'UNAPPROVED_DLT_TEMPLATE',
            })

        message_id = str(uuid.uuid4())
        message_type = str(body.get('messageType') or 'TRANSACTIONAL').strip().upper()
        # EUM v2 accepts TRANSACTIONAL or PROMOTIONAL. Normalize any older
        # caller vocabulary rather than letting it select a transport.
        if message_type not in ('TRANSACTIONAL', 'PROMOTIONAL'):
            message_type = 'TRANSACTIONAL'

        result = get_sms_service().send_sms(
            phone,
            content,
            message_type=message_type,
            dlt_template_key=template_key,
            override_region=str(body.get('region') or '').strip(),
            dry_run=bool(body.get('dryRun')),
            message_id=message_id,
        )

        if not result.success:
            _store_message(message_id, contact_id or '', content, 'FAILED',
                           error=result.error)
            log_event(logger, 'outbound_sms_failed', level='warning',
                      messageId=message_id, errorCode=result.error_code,
                      requestId=request_id)
            # A missing or unapproved DLT template is a client-correctable
            # request problem, not a server fault. 500 sent callers into retry
            # loops against a condition that could never clear.
            status = 422 if result.error_code == 'MISSING_DLT_TEMPLATE' else 502
            return _response(status, {
                'error': result.error,
                'errorCode': result.error_code,
                'messageId': message_id,
            })

        _store_message(
            message_id, contact_id or '', content, 'SENT', error=None,
            provider_message_id=result.provider_message_id,
            extra_data={
                'provider': result.provider,
                'messageType': message_type,
                'dltTemplateId': (result.dlt.template_id if result.dlt else ''),
                'sourceAddress': (result.dlt.sender_id if result.dlt
                                  and result.route and result.route.is_india else ''),
                'region': result.route.region if result.route else '',
            },
        )

        log_event(logger, 'sms_sent', messageId=message_id, contactId=contact_id,
                  provider=result.provider,
                  region=result.route.region if result.route else '',
                  isIndia=result.route.is_india if result.route else None,
                  templateKey=template_key or None,
                  dryRun=result.dry_run, requestId=request_id)

        return _response(200, {
            'messageId': message_id,
            'status': 'sent',
            'providerMessageId': result.provider_message_id,
            **result.as_dict(),
        })

    except Exception as exc:  # noqa: BLE001
        log_event(logger, 'outbound_sms_error', level='error',
                  error=f'{type(exc).__name__}: {str(exc)[:200]}',
                  requestId=request_id)
        return _response(500, {'error': 'Internal server error'})


def _resolve_template_key(body: Dict[str, Any]) -> tuple:
    """(template_key, error). Accepts a key, or validates a legacy raw id.

    `dltTemplateKey` is the supported field. `dltTemplateId` is accepted from
    callers that predate the shared DLT module, but it is checked against the
    approved map rather than trusted: an id we have not registered is refused so
    no caller can assert arbitrary content under our registered entity.
    """
    key = str(body.get('dltTemplateKey') or '').strip()
    if key:
        return key, ''

    raw_id = str(body.get('dltTemplateId') or '').strip()
    if not raw_id:
        return '', ''

    mapped = dlt_mod.key_for_template_id(raw_id)
    if mapped:
        return mapped, ''
    return '', (
        f"dltTemplateId '{raw_id}' is not an approved DLT template. "
        f"Approved template keys: {', '.join(dlt_mod.known_keys())}. "
        'Pass dltTemplateKey instead of a raw template id.'
    )


def _get_contact(contact_id: str) -> Dict[str, Any]:
    """Get contact from DynamoDB."""
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        response = table.get_item(Key={'id': contact_id})
        return response.get('Item', {})
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 'outbound_sms_contact_lookup_failed', level='error',
                  error=f'{type(exc).__name__}: {str(exc)[:160]}')
        return {}


def _store_message(message_id: str, contact_id: str, content: str, status: str,
                   error: str = None, provider_message_id: str = None,
                   extra_data: Dict = None) -> None:
    """Store the SMS record in the canonical MessagesTable via the shared writer."""
    extras = {}
    if extra_data:
        for key, value in extra_data.items():
            if value:
                extras[key] = value
    put_message(
        channel='sms',
        direction='outbound',
        contact_id=contact_id or '',
        content=content or '',
        status=(status or 'sent').lower(),
        message_id=message_id,
        message_type=extras.pop('messageType', 'text'),
        provider_message_id=provider_message_id or None,
        error_details=error or None,
        **extras,
    )


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body),
    }
