"""
Scheduled Messages Lambda Function
Manages scheduled template messages with CRUD operations and scheduled sending

Routes:
- GET /scheduled - List scheduled messages
- POST /scheduled - Create scheduled message
- PUT /scheduled/{scheduledId} - Update scheduled message
- DELETE /scheduled/{scheduledId} - Cancel scheduled message - Cancel scheduled message

Also handles CloudWatch Events trigger for sending due messages.
"""

import os
import json
import logging
import uuid
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin

from lambda_utils.logging import get_logger
from lambda_utils.middleware import require_auth

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
# RequestResponse is a side effect: retrying an ambiguous transport can duplicate delivery.
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'),
    config=Config(retries={'mode': 'standard', 'total_max_attempts': 1}))

SCHEDULED_TABLE = os.environ.get('SCHEDULED_TABLE', 'stack-wecare-digital-ScheduledMessagesTable')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
OUTBOUND_LAMBDA = os.environ.get('OUTBOUND_LAMBDA', 'wecare-outbound-whatsapp')

# CORS headers provided by lambda_utils.response.cors_headers(origin)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main handler for scheduled messages."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    
    # Check if this is a CloudWatch Events trigger (scheduled execution)
    if event.get('source') == 'aws.events' or event.get('detail-type') == 'Scheduled Event':
        return _process_due_messages(request_id)
    
    # Handle API Gateway requests
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        http_method = request_context.get('http', {}).get('method', 'GET')
        path = request_context.get('http', {}).get('path', '') or event.get('rawPath', '')
    else:
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '')
    
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}
    
    logger.info(json.dumps({'event': 'scheduled_request', 'method': http_method, 'path': path}))
    
    if http_method == 'OPTIONS':
        return options_response(origin)

    auth_result = require_auth(event, required_role='Admin')
    if auth_result is not None:
        return auth_result

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return _error_response(400, 'Invalid JSON request body')
    if not isinstance(body, dict):
        return _error_response(400, 'Request body must be a JSON object')

    try:
        if http_method == 'GET':
            return _list_scheduled(query_params, request_id)
        
        elif http_method == 'POST':
            return _create_scheduled(body, request_id)
        
        elif http_method == 'PUT':
            scheduled_id = path_params.get('scheduledId') or body.get('scheduledId') or query_params.get('scheduledId') or path.split('/')[-1]
            return _update_scheduled(scheduled_id, body, request_id)
        
        elif http_method == 'DELETE':
            scheduled_id = path_params.get('scheduledId') or body.get('scheduledId') or query_params.get('scheduledId') or path.split('/')[-1]
            return _cancel_scheduled(scheduled_id, request_id)
        
        return _error_response(400, 'Invalid request method')
    except Exception as e:
        logger.error(f'Scheduled messages error: {str(e)}')
        return _error_response(500, str(e))


def _list_scheduled(query_params: Dict[str, str], request_id: str) -> Dict[str, Any]:
    """List scheduled messages, optionally filtered by status."""
    table = dynamodb.Table(SCHEDULED_TABLE)
    status_filter = query_params.get('status', 'PENDING')
    
    try:
        if status_filter:
            # Query by status using GSI — paginate fully
            items = []
            query_kwargs = {
                'IndexName': 'status-scheduledAt-index',
                'KeyConditionExpression': '#status = :status',
                'ExpressionAttributeNames': {'#status': 'status'},
                'ExpressionAttributeValues': {':status': status_filter},
                'ScanIndexForward': True  # Oldest first
            }
            while True:
                response = table.query(**query_kwargs)
                items.extend(response.get('Items', []))
                if 'LastEvaluatedKey' not in response:
                    break
                query_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        else:
            # Scan all — paginate fully
            items = []
            scan_kwargs = {}
            while True:
                response = table.scan(**scan_kwargs)
                items.extend(response.get('Items', []))
                if 'LastEvaluatedKey' not in response:
                    break
                scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Convert Decimal to int/float for JSON serialization
        scheduled_messages = []
        for item in items:
            scheduled_messages.append(_normalize_item(item))
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'scheduledMessages': scheduled_messages,
                'count': len(scheduled_messages)
            })
        }
    except Exception as e:
        logger.error(f'List scheduled error: {str(e)}')
        return _error_response(500, f'Failed to list scheduled messages: {str(e)}')


def _scheduled_at_utc(value: Any) -> str:
    """Validate an explicit future instant and canonicalise it for lexical due queries."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Invalid scheduledAt format. Use timezone-aware ISO 8601.')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('Timezone required')
        instant = instant.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Invalid scheduledAt format. Use timezone-aware ISO 8601.') from None
    if instant <= datetime.now(timezone.utc):
        raise ValueError('scheduledAt must be in the future')
    return instant.isoformat(timespec='microseconds')


def _create_scheduled(body: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """Create a new scheduled message."""
    table = dynamodb.Table(SCHEDULED_TABLE)
    contacts_table = dynamodb.Table(CONTACTS_TABLE)
    
    # Validate required fields
    contact_id = body.get('contactId')
    template_name = body.get('templateName')
    scheduled_at = body.get('scheduledAt')
    
    if not contact_id:
        return _error_response(400, 'contactId is required')
    if not template_name:
        return _error_response(400, 'templateName is required')
    if not scheduled_at:
        return _error_response(400, 'scheduledAt is required')
    
    # Validate scheduled time is in the future
    try:
        scheduled_at = _scheduled_at_utc(scheduled_at)
    except ValueError as exc:
        return _error_response(400, str(exc))
    
    # Get contact details
    contact_name = None
    contact_phone = None
    try:
        contact_response = contacts_table.get_item(Key={'id': contact_id})
        if 'Item' in contact_response:
            contact = contact_response['Item']
            contact_name = contact.get('name', '')
            contact_phone = contact.get('phone', '')
    except Exception as e:
        logger.warning(f'Could not fetch contact: {str(e)}')
    
    # Create scheduled message
    scheduled_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    item = {
        'id': scheduled_id,
        'scheduledId': scheduled_id,
        'contactId': contact_id,
        'contactName': contact_name or '',
        'contactPhone': contact_phone or '',
        'recipientBsuid': body.get('recipientBsuid', ''),
        'templateName': template_name,
        'templateParams': body.get('templateParams', []),
        'phoneNumberId': body.get('phoneNumberId', ''),
        'scheduledAt': scheduled_at,
        'status': 'PENDING',
        'createdAt': now,
        'updatedAt': now
    }
    
    try:
        table.put_item(Item=item)
        logger.info(f'Created scheduled message: {scheduled_id}')
        
        return {
            'statusCode': 201,
            'headers': cors_headers(origin),
            'body': json.dumps(_normalize_item(item))
        }
    except Exception as e:
        logger.error(f'Create scheduled error: {str(e)}')
        return _error_response(500, f'Failed to create scheduled message: {str(e)}')


def _update_scheduled(scheduled_id: str, body: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """Update a scheduled message (only PENDING messages can be updated)."""
    table = dynamodb.Table(SCHEDULED_TABLE)
    
    if not scheduled_id:
        return _error_response(400, 'scheduledId is required')
    
    # Get existing item
    try:
        response = table.get_item(Key={'id': scheduled_id})
        if 'Item' not in response:
            return _error_response(404, 'Scheduled message not found')
        
        existing = response['Item']
        if existing.get('status') != 'PENDING':
            return _error_response(400, 'Only PENDING messages can be updated')
    except Exception as e:
        return _error_response(500, f'Failed to fetch scheduled message: {str(e)}')
    
    # Build update expression
    update_parts = []
    expr_names = {}
    expr_values = {}
    
    if 'scheduledAt' in body:
        # Validate new scheduled time
        try:
            scheduled_at = _scheduled_at_utc(body['scheduledAt'])
        except ValueError as exc:
            return _error_response(400, str(exc))
        
        update_parts.append('#scheduledAt = :scheduledAt')
        expr_names['#scheduledAt'] = 'scheduledAt'
        expr_values[':scheduledAt'] = scheduled_at
    
    if 'templateParams' in body:
        update_parts.append('#templateParams = :templateParams')
        expr_names['#templateParams'] = 'templateParams'
        expr_values[':templateParams'] = body['templateParams']
    
    if not update_parts:
        return _error_response(400, 'No valid fields to update')
    
    # Add updatedAt
    update_parts.append('#updatedAt = :updatedAt')
    expr_names['#updatedAt'] = 'updatedAt'
    expr_values[':updatedAt'] = datetime.now(timezone.utc).isoformat()
    
    condition = _pending_snapshot_condition(existing, expr_names, expr_values)
    try:
        response = table.update_item(
            Key={'id': scheduled_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ConditionExpression=condition,
            ReturnValues='ALL_NEW'
        )
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps(_normalize_item(response['Attributes']))
        }
    except Exception as e:
        if _conditional_conflict(e):
            return _error_response(409, 'Scheduled message changed; refresh and retry')
        logger.error(f'Update scheduled error: {str(e)}')
        return _error_response(500, f'Failed to update scheduled message: {str(e)}')


def _cancel_scheduled(scheduled_id: str, request_id: str) -> Dict[str, Any]:
    """Cancel a scheduled message."""
    table = dynamodb.Table(SCHEDULED_TABLE)
    
    if not scheduled_id:
        return _error_response(400, 'scheduledId is required')
    
    try:
        # Get existing item
        response = table.get_item(Key={'id': scheduled_id})
        if 'Item' not in response:
            return _error_response(404, 'Scheduled message not found')
        
        existing = response['Item']
        if existing.get('status') != 'PENDING':
            return _error_response(400, 'Only PENDING messages can be cancelled')
        
        # Update status to CANCELLED
        now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        names = {'#status': 'status', '#updatedAt': 'updatedAt'}
        values = {':status': 'CANCELLED', ':updatedAt': now}
        condition = _pending_snapshot_condition(existing, names, values)
        table.update_item(
            Key={'id': scheduled_id},
            UpdateExpression='SET #status = :status, #updatedAt = :updatedAt',
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values
        )
        
        logger.info(f'Cancelled scheduled message: {scheduled_id}')
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'scheduledId': scheduled_id, 'status': 'CANCELLED'})
        }
    except Exception as e:
        if _conditional_conflict(e):
            return _error_response(409, 'Scheduled message changed; refresh and retry')
        logger.error(f'Cancel scheduled error: {str(e)}')
        return _error_response(500, f'Failed to cancel scheduled message: {str(e)}')


def _pending_snapshot_condition(existing, names, values):
    """Only mutate the exact pending row read; legacy absent fields stay absent."""
    names['#status'] = 'status'
    values[':pending'] = 'PENDING'
    parts = ['#status = :pending']
    for field in ('scheduledAt', 'updatedAt'):
        alias = '#' + field
        names[alias] = field
        if field in existing:
            value = ':expected_' + field
            values[value] = existing[field]
            parts.append(alias + ' = ' + value)
        else:
            parts.append('attribute_not_exists(' + alias + ')')
    return ' AND '.join(parts)


def _conditional_conflict(exc):
    return isinstance(exc, ClientError) and exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException'


def _dispatch_outcome(response):
    """Submission evidence only; ambiguous results never certify sending or retry safety."""
    if response.get('StatusCode') != 200 or response.get('FunctionError'):
        return 'DISPATCH_UNKNOWN', 'OUTBOUND_INVOCATION_UNRESOLVED'
    try:
        result = json.loads(response['Payload'].read())
        if not isinstance(result, dict):
            raise ValueError()
        code = result.get('statusCode')
        if type(code) is not int:
            raise ValueError()
        body = json.loads(result.get('body', '{}'))
        if not isinstance(body, dict):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        return 'DISPATCH_UNKNOWN', 'OUTBOUND_RESPONSE_UNRESOLVED'
    if code in (200, 201):
        if body.get('status') == 'dry_run' or body.get('mode') == 'DRY_RUN':
            return 'FAILED', 'OUTBOUND_DRY_RUN_NOT_SENT'
        provider_id = body.get('whatsappMessageId')
        if isinstance(provider_id, str) and provider_id.strip() and (
                (body.get('status') == 'sent' and body.get('mode') == 'LIVE')
                or body.get('idempotent') is True):
            return 'SENT', ''
        return 'DISPATCH_UNKNOWN', 'OUTBOUND_SEND_NOT_CONFIRMED'
    if 400 <= code < 500 and code != 408:
        return 'FAILED', 'OUTBOUND_REQUEST_REFUSED'
    return 'DISPATCH_UNKNOWN', 'OUTBOUND_SEND_UNRESOLVED'


def _process_due_messages(request_id: str) -> Dict[str, Any]:
    """Claim pending rows once; an interrupted/ambiguous dispatch requires staff review."""
    table = dynamodb.Table(SCHEDULED_TABLE)
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    counts = {'processed': 0, 'sent': 0, 'failed': 0, 'unknown': 0, 'skipped': 0}
    try:
        items = []
        kwargs = {
            'IndexName': 'status-scheduledAt-index',
            'KeyConditionExpression': '#status = :status AND #scheduledAt <= :now',
            'ExpressionAttributeNames': {'#status': 'status', '#scheduledAt': 'scheduledAt'},
            'ExpressionAttributeValues': {':status': 'PENDING', ':now': now},
        }
        while len(items) < 50:
            kwargs['Limit'] = 50 - len(items)
            page = table.query(**kwargs)
            items.extend(page.get('Items', [])[:kwargs['Limit']])
            if not page.get('LastEvaluatedKey') or len(items) >= 50:
                break
            kwargs['ExclusiveStartKey'] = page['LastEvaluatedKey']
        for item in items:
            scheduled_id = item.get('id') or item.get('scheduledId')
            if not scheduled_id or not item.get('scheduledAt'):
                counts['skipped'] += 1
                continue
            token = str(uuid.uuid4())
            names = {'#dispatchToken': 'dispatchToken', '#dispatchStartedAt': 'dispatchStartedAt'}
            values = {':dispatching': 'DISPATCHING', ':token': token, ':now': now}
            condition = _pending_snapshot_condition(item, names, values)
            try:
                table.update_item(
                    Key={'id': scheduled_id},
                    UpdateExpression='SET #status = :dispatching, #dispatchToken = :token, #dispatchStartedAt = :now, #updatedAt = :now',
                    ConditionExpression=condition,
                    ExpressionAttributeNames=names, ExpressionAttributeValues=values,
                )
            except ClientError as exc:
                if _conditional_conflict(exc):
                    counts['skipped'] += 1
                    continue
                raise
            counts['processed'] += 1
            if not item.get('contactId') or not item.get('templateName'):
                outcome, reason = 'FAILED', 'MISSING_RECIPIENT_OR_TEMPLATE'
            else:
                payload = {'body': json.dumps({
                    'contactId': item['contactId'], 'isTemplate': True,
                    'templateName': item['templateName'],
                    'templateParams': item.get('templateParams', []),
                    'phoneNumberId': item.get('phoneNumberId', ''),
                    'recipientBsuid': item.get('recipientBsuid', ''),
                })}
                try:
                    response = lambda_client.invoke(FunctionName=OUTBOUND_LAMBDA,
                        InvocationType='RequestResponse', Payload=json.dumps(payload))
                    outcome, reason = _dispatch_outcome(response)
                except Exception:
                    outcome, reason = 'DISPATCH_UNKNOWN', 'OUTBOUND_INVOCATION_UNRESOLVED'
            final_names = {'#status': 'status', '#dispatchToken': 'dispatchToken',
                '#updatedAt': 'updatedAt', '#errorMessage': 'errorMessage'}
            final_values = {':status': outcome, ':dispatching': 'DISPATCHING', ':token': token,
                ':now': now, ':error': reason}
            expression = 'SET #status = :status, #updatedAt = :now, #errorMessage = :error'
            if outcome == 'SENT':
                final_names['#sentAt'] = 'sentAt'
                expression += ', #sentAt = :now'
            try:
                table.update_item(Key={'id': scheduled_id}, UpdateExpression=expression,
                    ConditionExpression='#status = :dispatching AND #dispatchToken = :token',
                    ExpressionAttributeNames=final_names, ExpressionAttributeValues=final_values)
            except Exception:
                # Keep the claim excluded from future PENDING queries even if finalisation
                # fails. A staff member must reconcile outbound/provider evidence before retry.
                outcome = 'DISPATCH_UNKNOWN'
                try:
                    table.update_item(Key={'id': scheduled_id},
                        UpdateExpression='SET #status = :status, #updatedAt = :now, #errorMessage = :error',
                        ConditionExpression='#status = :dispatching AND #dispatchToken = :token',
                        ExpressionAttributeNames={k: v for k, v in final_names.items() if k != '#sentAt'},
                        ExpressionAttributeValues={**final_values, ':status': outcome, ':error': 'DISPATCH_RESULT_PERSISTENCE_UNRESOLVED'})
                except Exception:
                    logger.error(json.dumps({'event': 'scheduled_dispatch_review_required', 'requestId': request_id}))
            counts[{'SENT': 'sent', 'FAILED': 'failed', 'DISPATCH_UNKNOWN': 'unknown'}[outcome]] += 1
        return {'statusCode': 200, 'body': json.dumps(counts)}
    except Exception:
        logger.error(json.dumps({'event': 'scheduled_dispatch_store_unavailable', 'requestId': request_id}))
        return _error_response(503, 'Scheduled dispatch unavailable; review any claimed dispatch before retry')


def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB item to JSON-serializable format."""
    result = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            result[key] = int(value) if value % 1 == 0 else float(value)
        else:
            result[key] = value
    
    # Ensure id field exists for frontend compatibility
    if 'scheduledId' in result and 'id' not in result:
        result['id'] = result['scheduledId']
    
    return result


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }
