"""
Bulk Job Create Lambda Function

Purpose: Create and manage bulk messaging jobs
Supports: WhatsApp, SMS, Email bulk campaigns
"""

import os
import json
import uuid
import time
import logging
import boto3
from typing import Dict, Any, List
from decimal import Decimal

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils import contact_key, contact_store, direct_send, template_status
from lambda_utils.identity import consent
from lambda_utils.meta_client import MetaGraphClient

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
BULK_JOBS_TABLE = os.environ.get('BULK_JOBS_TABLE', 'stack-wecare-digital-BulkJobsTable')
BULK_RECIPIENTS_TABLE = os.environ.get('BULK_RECIPIENTS_TABLE', 'stack-wecare-digital-BulkRecipientsTable')
BULK_QUEUE_URL = os.environ.get('BULK_QUEUE_URL', '')
CHUNK_SIZE = 100  # Recipients per SQS message
# Same default sender as bulk-worker.
DEFAULT_PHONE_NUMBER_ID = os.environ.get('DEFAULT_PHONE_NUMBER_ID', 'phone-number-id-waba1-direct-1016149501586345')
# bulk-worker sends every template with language code 'en'.
TEMPLATE_LANGUAGE = 'en'
# Consent purpose per Meta template category, as outbound-whatsapp maps it.
_CATEGORY_PURPOSE = {
    'MARKETING': consent.MARKETING,
    'UTILITY': consent.TRANSACTIONAL,
    'AUTHENTICATION': consent.SERVICE,
}

_meta_client = None


class TemplateUnverifiable(RuntimeError):
    """Meta could not be read, so the template's approval is unknown."""


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle bulk job creation and listing."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event, required_role='Admin')
    if _auth is not None:
        return _auth

    # Handle both HTTP API v2 and REST API event formats
    http_method = (
        event.get('requestContext', {}).get('http', {}).get('method') or
        event.get('httpMethod') or
        'GET'
    )
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}
    
    logger.info(json.dumps({
        'event': 'bulk_job_handler',
        'method': http_method,
        'path_params': path_params,
        'requestId': request_id
    }))
    
    try:
        # GET /bulk/jobs - List jobs
        if http_method == 'GET' and not path_params.get('jobId'):
            return _list_jobs(query_params, request_id)
        
        # GET /bulk/jobs/{jobId} - Get single job
        if http_method == 'GET' and path_params.get('jobId'):
            return _get_job(path_params['jobId'], request_id)
        
        # POST /bulk/jobs - Create job
        if http_method == 'POST':
            body = json.loads(event.get('body', '{}'))
            return _create_job(body, request_id, _actor(event))
        
        return _response(405, {'error': 'Method not allowed'})
        
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})
    except Exception as e:
        logger.error(json.dumps({
            'event': 'bulk_job_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _response(500, {'error': 'Internal server error'})


def _list_jobs(params: Dict, request_id: str) -> Dict[str, Any]:
    """List bulk jobs with optional filters."""
    try:
        table = dynamodb.Table(BULK_JOBS_TABLE)
        
        scan_kwargs = {}
        filter_expressions = []
        
        from boto3.dynamodb.conditions import Attr
        
        if params.get('channel'):
            filter_expressions.append(Attr('channel').eq(params['channel'].upper()))
        if params.get('status'):
            filter_expressions.append(Attr('status').eq(params['status'].lower()))
        if params.get('createdBy'):
            filter_expressions.append(Attr('createdBy').eq(params['createdBy']))
        
        if filter_expressions:
            combined = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined = combined & expr
            scan_kwargs['FilterExpression'] = combined
        
        result = table.scan(**scan_kwargs)
        jobs = result.get('Items', [])
        # Paginate through all results
        while 'LastEvaluatedKey' in result:
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
            result = table.scan(**scan_kwargs)
            jobs.extend(result.get('Items', []))
        
        # Sort by createdAt descending
        jobs.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)
        
        return _response(200, {
            'jobs': [_normalize_job(j) for j in jobs],
            'count': len(jobs)
        })
        
    except Exception as e:
        logger.error(f"List jobs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _get_job(job_id: str, request_id: str) -> Dict[str, Any]:
    """Get a single bulk job with recipient stats."""
    try:
        table = dynamodb.Table(BULK_JOBS_TABLE)
        result = table.get_item(Key={'id': job_id})
        job = result.get('Item')
        
        if job:
            # Get recipient stats
            stats = _get_recipient_stats(job_id)
            job_data = _normalize_job(job)
            job_data.update(stats)
            return _response(200, {'job': job_data})
        
        return _response(404, {'error': 'Job not found'})
        
    except Exception as e:
        logger.error(f"Get job error: {str(e)}")
        return _response(500, {'error': str(e)})


def _create_job(body: Dict, request_id: str, created_by: str) -> Dict[str, Any]:
    """Create a new bulk job. `created_by` comes from the verified token, never the body."""
    channel = str(body.get('channel', 'WHATSAPP')).upper()
    recipients = body.get('recipients', [])
    content = body.get('content', '')
    template_name = str(body.get('templateName') or '').strip()
    template_params = body.get('templateParams', [])
    scheduled_at = body.get('scheduledAt')
    phone_number_id = body.get('phoneNumberId') or DEFAULT_PHONE_NUMBER_ID
    
    if not recipients or not isinstance(recipients, list):
        return _response(400, {'error': 'recipients array is required'})
    
    # Approved WhatsApp templates only. SMS and EMAIL bulk jobs carry free text.
    if channel != 'WHATSAPP':
        return _response(400, {'error': 'Bulk jobs send approved WhatsApp templates only'})

    if content or not template_name:
        return _response(400, {'error': 'templateName is required; free-text content is not accepted'})
    
    waba_id = _sender_waba(phone_number_id)
    if not waba_id:
        return _response(400, {'error': 'phoneNumberId is not a known WhatsApp sender'})
    try:
        template = _approved_template(template_name, waba_id)
    except TemplateUnverifiable:
        return _response(503, {'error': 'Template approval could not be verified. Nothing was created.'})
    if not template:
        return _response(400, {'error': f"Template '{template_name}' ({TEMPLATE_LANGUAGE}) is not "
                                        'APPROVED for this sender'})

    purpose = _CATEGORY_PURPOSE.get(template['category'], consent.MARKETING)
    recipients, dropped = _eligible_recipients(recipients, channel, purpose)
    if not recipients:
        return _response(400, {'error': 'No eligible recipients', **dropped})
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    now = int(time.time())
    
    # Create job record
    job = {
        'id': job_id,
        'jobId': job_id,
        'channel': channel,
        'totalRecipients': len(recipients),
        'sentCount': 0,
        'failedCount': 0,
        'status': 'pending',
        'content': content,
        'templateName': template_name,
        'templateCategory': template['category'],
        'templateLanguage': TEMPLATE_LANGUAGE,
        'templateParams': template_params,
        'phoneNumberId': phone_number_id,
        'createdBy': created_by,
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
    }
    
    if scheduled_at:
        job['scheduledAt'] = Decimal(str(scheduled_at))
        job['status'] = 'scheduled'
    
    # Store job
    jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
    jobs_table.put_item(Item=job)
    
    # Store recipients
    _store_recipients(job_id, recipients)
    
    # Enqueue for processing (if not scheduled)
    if not scheduled_at and BULK_QUEUE_URL:
        _enqueue_job(job_id, channel, content, template_name, template_params, 
                     phone_number_id, recipients)
    
    logger.info(json.dumps({
        'event': 'bulk_job_created',
        'jobId': job_id,
        'channel': channel,
        'totalRecipients': len(recipients),
        **dropped,
        'scheduled': bool(scheduled_at),
        'createdBy': created_by,
        'requestId': request_id
    }))
    
    return _response(201, {
        'jobId': job_id,
        'status': job['status'],
        'totalRecipients': len(recipients),
        **dropped,
        'message': 'Job created successfully'
    })


def _actor(event: Dict[str, Any]) -> str:
    """The caller's username (else Cognito sub) from the verified token; 'internal' without one."""
    auth = event.get('_auth') or {}
    return str(auth.get('username') or (auth.get('attributes') or {}).get('sub') or 'internal')


def _sender_waba(phone_number_id: str) -> str:
    """The WABA that owns our sender id, or '' when it cannot be resolved. Never guesses."""
    value = str(phone_number_id or '').strip()
    meta_phone_id = value.rsplit('-direct-', 1)[-1] if '-direct-' in value else value
    return direct_send.waba_for_meta_phone(meta_phone_id) if meta_phone_id.isdigit() else ''


def _approved_template(template_name: str, waba_id: str) -> Dict[str, str]:
    """{'category'} of the WABA's APPROVED template in TEMPLATE_LANGUAGE, or {} when there is none.

    Raises TemplateUnverifiable when Meta cannot be read: approval is never assumed.
    """
    global _meta_client
    try:
        if _meta_client is None:
            _meta_client = MetaGraphClient()
        result = _meta_client.get(
            f'{waba_id}/message_templates',
            params={'name': template_name, 'fields': 'name,status,category,language', 'limit': 100},
            token_context={'waba_id': waba_id})
    except Exception:  # noqa: BLE001 - e.g. the token secret could not be read
        result = None
    rows = result.get('data') if isinstance(result, dict) else None
    if MetaGraphClient.is_error(result) or not isinstance(rows, list):
        logger.warning(json.dumps({'event': 'bulk_template_read_failed', 'wabaId': waba_id}))
        raise TemplateUnverifiable(template_name)
    for row in rows:
        if (isinstance(row, dict) and row.get('name') == template_name
                and row.get('language') == TEMPLATE_LANGUAGE
                and template_status.is_sendable(row.get('status'))):
            return {'category': str(row.get('category') or '').upper()}
    return {}


def _eligible_recipients(recipients: List[Any], channel: str, purpose: str):
    """Recipients that resolve to a live contact and are not opted out on `channel`.

    A recipient is opted out when the consent ledger's latest record for the channel, or
    for the template's purpose, is OPTED_OUT. Returns (kept, dropped counts).
    """
    table = dynamodb.Table(contact_store.table_name())
    now = int(time.time())
    kept: List[Dict] = []
    opted_out = unknown = 0
    for recipient in recipients:
        contact_id = str(recipient.get('contactId') or '').strip() if isinstance(recipient, dict) else ''
        contact = contact_store.lookup(table, contact_id=contact_id) if contact_id else None
        if not contact:
            unknown += 1
            continue
        if consent.OPTED_OUT in (consent.current_state(contact, channel, now=now),
                                 consent.current_state(contact, channel, now=now, purpose=purpose)):
            opted_out += 1
            continue
        kept.append({**recipient, 'contactId': contact_key.resolve(contact)})
    return kept, {'droppedOptedOut': opted_out, 'droppedUnknownContacts': unknown}


def _store_recipients(job_id: str, recipients: List[Dict]) -> None:
    """Store recipient records in DynamoDB."""
    try:
        table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
        now = Decimal(str(int(time.time())))
        
        with table.batch_writer() as batch:
            for idx, recipient in enumerate(recipients):
                item = {
                    'id': f"{job_id}-{idx}",
                    'jobId': job_id,
                    'recipientId': f"{job_id}-{idx}",
                    'contactId': recipient.get('contactId', ''),
                    'phone': recipient.get('phone', ''),
                    'email': recipient.get('email', ''),
                    'name': recipient.get('name', ''),
                    'status': 'pending',
                    'createdAt': now,
                    'updatedAt': now,
                }
                batch.put_item(Item=item)
                
    except Exception as e:
        logger.error(f"Store recipients error: {str(e)}")


def _enqueue_job(job_id: str, channel: str, content: str, template_name: str,
                 template_params: List, phone_number_id: str, recipients: List[Dict]) -> None:
    """Enqueue job chunks to SQS for processing."""
    try:
        # Chunk recipients
        chunks = [recipients[i:i+CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]
        enqueued = 0
        
        for chunk_idx, chunk in enumerate(chunks):
            message = {
                'jobId': job_id,
                'chunkIndex': chunk_idx,
                'channel': channel,
                'content': content,
                'templateName': template_name,
                'templateParams': template_params,
                'phoneNumberId': phone_number_id,
                'recipients': chunk,
            }
            
            try:
                send_kwargs = {
                    'QueueUrl': BULK_QUEUE_URL,
                    'MessageBody': json.dumps(message, default=str),
                }
                if '.fifo' in BULK_QUEUE_URL:
                    send_kwargs['MessageGroupId'] = job_id
                sqs.send_message(**send_kwargs)
                enqueued += 1
            except Exception as chunk_err:
                logger.error(f"Failed to enqueue chunk {chunk_idx} for job {job_id}: {str(chunk_err)}")
        
        # Update job status to in_progress
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #status = :status, updatedAt = :now',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'in_progress',
                ':now': Decimal(str(int(time.time())))
            }
        )
        
        logger.info(f"Enqueued {enqueued}/{len(chunks)} chunks for job {job_id}")
        
    except Exception as e:
        logger.error(f"Enqueue job error: {str(e)}")


def _get_recipient_stats(job_id: str) -> Dict[str, int]:
    """Get recipient statistics for a job."""
    try:
        table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
        from boto3.dynamodb.conditions import Attr
        # Use scan with filter since jobId is not the PK (PK is 'id')
        all_items = []
        scan_kwargs = {
            'FilterExpression': Attr('jobId').eq(job_id),
            'ProjectionExpression': '#s',
            'ExpressionAttributeNames': {'#s': 'status'},
        }
        while True:
            response = table.scan(**scan_kwargs)
            all_items.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        recipients = all_items
        
        stats = {
            'pendingCount': 0,
            'sentCount': 0,
            'failedCount': 0,
            'deliveredCount': 0,
        }
        
        for r in recipients:
            status = r.get('status', 'pending')
            if status == 'pending':
                stats['pendingCount'] += 1
            elif status == 'sent':
                stats['sentCount'] += 1
            elif status == 'failed':
                stats['failedCount'] += 1
            elif status == 'delivered':
                stats['deliveredCount'] += 1
        
        return stats
        
    except Exception:
        return {}


def _normalize_job(item: Dict) -> Dict:
    """Normalize job record for API response."""
    return {
        'id': item.get('jobId', ''),
        'jobId': item.get('jobId', ''),
        'channel': item.get('channel', 'WHATSAPP'),
        'status': item.get('status', 'pending').upper(),
        'totalRecipients': int(item.get('totalRecipients', 0)),
        'sentCount': int(item.get('sentCount', 0)),
        'failedCount': int(item.get('failedCount', 0)),
        'content': item.get('content', ''),
        'templateName': item.get('templateName'),
        'createdBy': item.get('createdBy', ''),
        'createdAt': str(item.get('createdAt', '')),
        'updatedAt': str(item.get('updatedAt', '')),
        'scheduledAt': str(item.get('scheduledAt', '')) if item.get('scheduledAt') else None,
    }


def _response(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str)
    }
