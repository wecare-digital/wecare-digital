"""
Bulk Worker Lambda Function
Purpose: Process bulk messaging jobs from SQS queue
Reads recipients from BulkRecipientsTable and sends messages via WhatsApp/SMS/Email
"""
import os
import json
import logging
import time
import uuid
import boto3
from boto3.dynamodb.conditions import Key, Attr
from typing import Dict, Any, Optional

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.middleware import require_auth
from lambda_utils.privacy import mask_phone
from lambda_utils.rate_limit import check_rate_limit

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

BULK_JOBS_TABLE = os.environ.get('BULK_JOBS_TABLE', 'stack-wecare-digital-BulkJobsTable')
BULK_RECIPIENTS_TABLE = os.environ.get('BULK_RECIPIENTS_TABLE', 'stack-wecare-digital-BulkRecipientsTable')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
SEND_MODE = os.environ.get('SEND_MODE', 'LIVE')
DEFAULT_PHONE_NUMBER_ID = os.environ.get('DEFAULT_PHONE_NUMBER_ID', 'phone-number-id-waba1-direct-1016149501586345')
RATE_LIMIT_PER_SECOND = int(os.environ.get('RATE_LIMIT_PER_SECOND', '80'))

# Direct API phone ID to Meta phone ID mapping
DIRECT_API_META_PHONE_MAP = {
    'phone-number-id-waba1-direct-1016149501586345': '1016149501586345',
    'phone-number-id-waba-t-direct-1055232054343117': '1055232054343117',
}
from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
_direct_api_cache = {}

# CORS headers provided by lambda_utils.response.cors_headers(origin)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event, context):
    """Process SQS messages for bulk sending."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    logger.info(f'[{request_id}] Bulk worker invoked')

    # Handle API Gateway HTTP requests (status check)
    if 'requestContext' in event and 'http' in event.get('requestContext', {}):
        # GET /bulk/worker was public with no handler check. It only reports
        # status, but SEND_MODE is operational detail that should not be readable
        # anonymously. SQS-driven and direct invokes carry no API Gateway context,
        # so require_auth passes them through and only the public route is gated.
        auth_failure = require_auth(event)
        if auth_failure is not None:
            return auth_failure
        return _response(200, {'status': 'bulk-worker-active', 'sendMode': SEND_MODE})

    # Handle SQS event
    records = event.get('Records', [])
    if not records:
        # Direct invocation with job details
        body = event if isinstance(event, dict) else json.loads(event)
        return _process_job(body, request_id)

    results = []
    for record in records:
        try:
            body = json.loads(record.get('body', '{}'))
            result = _process_job(body, request_id)
            results.append(result)
        except Exception as e:
            logger.error(f'[{request_id}] Error processing record: {e}')
            results.append({'error': str(e)})

    return {'statusCode': 200, 'body': json.dumps({'processed': len(results), 'results': results})}


def _process_job(body: Dict, request_id: str) -> Dict:
    """Process a single bulk job."""
    job_id = body.get('jobId')
    if not job_id:
        return {'error': 'jobId required'}

    jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
    recipients_table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
    contacts_table = dynamodb.Table(CONTACTS_TABLE)

    try:
        # Get job details
        job = jobs_table.get_item(Key={'id': job_id}).get('Item')
        if not job:
            return {'error': f'Job {job_id} not found'}

        if job.get('status') in ['CANCELLED', 'COMPLETED']:
            return {'status': 'skipped', 'reason': f'Job is {job["status"]}'}

        # Update job status to IN_PROGRESS
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #s = :s, updatedAt = :u',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'IN_PROGRESS', ':u': int(time.time())}
        )

        # Get pending recipients (with full pagination)
        all_recipients = []
        query_kwargs = {
            'KeyConditionExpression': Key('jobId').eq(job_id),
            'FilterExpression': Attr('status').eq('PENDING'),
        }
        while True:
            response = recipients_table.query(**query_kwargs)
            all_recipients.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            query_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        recipients = all_recipients

        channel = job.get('channel', 'WHATSAPP')
        template_name = body.get('templateName')
        template_params = body.get('templateParams', [])
        content = body.get('content', '')
        phone_number_id = body.get('phoneNumberId', DEFAULT_PHONE_NUMBER_ID)

        sent_count = int(job.get('sentCount', 0))
        failed_count = int(job.get('failedCount', 0))

        for recipient in recipients:
            # Check if job was cancelled
            current_job = jobs_table.get_item(Key={'id': job_id}).get('Item', {})
            if current_job.get('status') == 'CANCELLED':
                break

            contact_id = recipient.get('contactId')
            recipient_id = recipient.get('recipientId')

            try:
                # Get contact phone
                contact = contacts_table.get_item(Key={'id': contact_id}).get('Item', {})
                phone = contact.get('phone', '')
                if not phone:
                    raise ValueError('No phone number')

                if SEND_MODE == 'LIVE':
                    if channel == 'WHATSAPP':
                        # Check DynamoDB-backed rate limit before sending
                        for _retry in range(3):
                            if check_rate_limit('whatsapp', phone_number_id, max_per_second=RATE_LIMIT_PER_SECOND):
                                break
                            logger.warning(f'[{request_id}] Rate limit exceeded for {phone_number_id}, throttling')
                            time.sleep(0.5)
                        _send_whatsapp(phone, phone_number_id, template_name, template_params, content, contact_id, request_id)
                    elif channel == 'SMS':
                        # The `live` alias: the unqualified name would run $LATEST.
                        _send_via_lambda('wecare-outbound-sms:live', {
                            'contactId': contact_id, 'phoneNumber': phone, 'content': content,
                        }, request_id)
                    elif channel == 'EMAIL':
                        email = contact.get('email', '')
                        if not email:
                            raise ValueError('No email address')
                        _send_via_lambda('wecare-outbound-email:live', {
                            'contactId': contact_id, 'subject': body.get('subject', 'Message from WECARE.DIGITAL'),
                            'content': content,
                        }, request_id)
                    else:
                        raise ValueError(f'Unsupported channel: {channel}')

                # Update recipient status
                recipients_table.update_item(
                    Key={'id': recipient_id},
                    UpdateExpression='SET #s = :s, sentAt = :t',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':s': 'SENT', ':t': int(time.time())}
                )
                sent_count += 1
            except Exception as e:
                logger.error(f'[{request_id}] Failed to send to {contact_id}: {e}')
                recipients_table.update_item(
                    Key={'id': recipient_id},
                    UpdateExpression='SET #s = :s, errorDetails = :e',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':s': 'FAILED', ':e': str(e)}
                )
                failed_count += 1

            # Rate limiting
            time.sleep(1.0 / RATE_LIMIT_PER_SECOND)

        # Update job final status
        final_status = 'COMPLETED'
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #s = :s, sentCount = :sc, failedCount = :fc, updatedAt = :u',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': final_status, ':sc': sent_count, ':fc': failed_count, ':u': int(time.time())
            }
        )

        return {'jobId': job_id, 'status': final_status, 'sent': sent_count, 'failed': failed_count}

    except Exception as e:
        logger.error(f'[{request_id}] Job {job_id} error: {e}')
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #s = :s, updatedAt = :u',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'FAILED', ':u': int(time.time())}
        )
        return {'error': str(e)}


def _send_whatsapp(phone: str, phone_number_id: str, template_name: str,
                   template_params: list, content: str, contact_id: str, request_id: str):
    """Send WhatsApp message via Direct Meta API."""
    import hmac as _hmac, hashlib as _hashlib, urllib.request, urllib.error

    formatted_phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if not formatted_phone.startswith('91') and len(formatted_phone) == 10:
        formatted_phone = '91' + formatted_phone

    if template_name:
        message_payload = {
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': 'en'},
                'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': p} for p in template_params]}] if template_params else []
            }
        }
    else:
        message_payload = {'type': 'text', 'text': {'body': content}}

    meta_payload = json.dumps({
        'messaging_product': 'whatsapp',
        'to': formatted_phone,
        **message_payload
    })

    meta_phone_id = DIRECT_API_META_PHONE_MAP.get(phone_number_id, '1016149501586345')

    if 'token' not in _direct_api_cache:
        resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
        data = json.loads(resp['SecretString'])
        _direct_api_cache['token'] = (data.get('access_token') or '').strip()
        _direct_api_cache['app_secret'] = (data.get('app_secret') or '').strip()

    token = _direct_api_cache['token']
    app_secret = _direct_api_cache['app_secret']

    url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/messages"
    if app_secret:
        proof = _hmac.new(app_secret.encode(), token.encode(), _hashlib.sha256).hexdigest()
        url = f"{url}?appsecret_proof={proof}"

    req = urllib.request.Request(url, data=meta_payload.encode('utf-8'), headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.loads(r.read().decode())
    msg_id = result.get('messages', [{}])[0].get('id', '')
    logger.info(f'[{request_id}] Sent to {mask_phone(formatted_phone or "")}: {msg_id}')


def _send_via_lambda(function_name: str, payload: Dict, request_id: str):
    """Invoke another Lambda function for SMS/Email sending."""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'body': json.dumps(payload),
                'requestContext': {'http': {'method': 'POST'}},
                'headers': {},
            }).encode('utf-8'),
        )
        resp_payload = json.loads(response['Payload'].read())
        status = resp_payload.get('statusCode', 500)
        if status >= 400:
            body = json.loads(resp_payload.get('body', '{}'))
            raise ValueError(body.get('error', f'{function_name} returned {status}'))
        logger.info(f'[{request_id}] {function_name} invoked successfully')
    except Exception as e:
        logger.error(f'[{request_id}] {function_name} invoke error: {e}')
        raise


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    return {'statusCode': status_code, 'headers': cors_headers(resp_origin or origin), 'body': json.dumps(body, default=str)}
