"""
DLQ Replay Lambda Function

Purpose: Retry failed messages from Dead Letter Queues
Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7

Replays messages from DLQ with deduplication, retry limits,
and original processing logic.
"""

import os
import json
import time
import logging
import boto3
from typing import Dict, Any, List, Set
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils import wa_internal_event  # owns the inbound DLQ URL

# Configure logging
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
DLQ_MESSAGES_TABLE = os.environ.get('DLQ_MESSAGES_TABLE', 'stack-wecare-digital-DLQMessagesTable')
# Live configuration names this queue `DLQ_URL`; reading only `INBOUND_DLQ_URL` left it ''.
INBOUND_DLQ_URL = wa_internal_event.inbound_dlq_url()
#: `stack-wecare-digital-bulk-queue` redrives a job chunk here after three failed receives.
#: Nothing sets `BULK_DLQ_URL` live, so replay answered "Queue URL not configured" for it.
BULK_DLQ_DEFAULT_URL = 'https://sqs.us-east-1.amazonaws.com/775261844268/stack-wecare-digital-bulk-dlq'
BULK_DLQ_URL = os.environ.get('BULK_DLQ_URL') or BULK_DLQ_DEFAULT_URL

# Constants
MAX_RETRIES = 5  # Requirement 9.7
BATCH_SIZE = 100  # Requirement 9.3
DLQ_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Queue URL mapping
DLQ_URLS = {
    'inbound-dlq': INBOUND_DLQ_URL,
    'bulk-dlq': BULK_DLQ_URL,
}

# Handler function mapping. The deployed names, on the `live` alias. The old defaults were the
# source folder names ('inbound-whatsapp-handler', 'bulk-worker'), which are not functions, and
# neither variable is set live, so every replay failed with ResourceNotFound.
HANDLERS = {
    'inbound-dlq': os.environ.get('INBOUND_HANDLER_FUNCTION', 'wecare-inbound-whatsapp:live'),
    'bulk-dlq': os.environ.get('BULK_WORKER_FUNCTION', 'wecare-bulk-worker:live'),
}


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    DLQ operations: GET to list, POST to replay.
    Requirements: 9.1-9.7
    """
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    # Handle both HTTP API v2 and REST API event formats
    http_method = str(
        event.get('requestContext', {}).get('http', {}).get('method') or
        event.get('httpMethod') or
        'GET'
    ).upper()

    # A preflight is answered here and does nothing else. require_auth lets OPTIONS through
    # unauthenticated precisely so a handler can answer it, and the routing below used to send
    # every method that was not GET to the replay, so an OPTIONS call received, re-ran and
    # deleted DLQ messages.
    if http_method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    logger.info(json.dumps({
        'event': 'dlq_handler_start',
        'method': http_method,
        'requestId': request_id
    }))
    
    # GET /dlq - List DLQ messages
    if http_method == 'GET':
        return _list_dlq_messages(request_id)
    
    # POST /dlq/replay - Replay messages
    if http_method == 'POST':
        return _replay_dlq_messages(event, request_id)

    # Default deny: no other method means anything here, least of all a replay.
    return _error_response(405, 'Method not allowed')


def _list_dlq_messages(request_id: str) -> Dict[str, Any]:
    """List all DLQ messages from tracking table (paginated)."""
    try:
        dlq_table = dynamodb.Table(DLQ_MESSAGES_TABLE)
        all_items = []
        scan_kwargs = {}
        while True:
            response = dlq_table.scan(**scan_kwargs)
            all_items.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        messages = []
        for item in all_items:
            messages.append({
                'id': item.get('dlqMessageId'),
                'queueName': item.get('queueName'),
                'retryCount': int(item.get('retryCount', 0)),
                'lastAttemptAt': int(item.get('lastAttemptAt', 0)),
                'error': item.get('error', 'Unknown error'),
            })
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'messages': messages,
                'count': len(messages)
            })
        }
    except Exception as e:
        logger.error(f"List DLQ error: {str(e)}")
        return _error_response(500, 'Failed to list DLQ messages')


def _replay_dlq_messages(event: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """Replay messages from DLQ."""
    logger.info(json.dumps({
        'event': 'dlq_replay_start',
        'requestId': request_id
    }))
    
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        queue_name = body.get('queueName', 'inbound-dlq')
        batch_size = min(int(body.get('batchSize', BATCH_SIZE)), BATCH_SIZE)  # Requirement 9.3
        
        # Validate queue name
        if queue_name not in DLQ_URLS:
            return _error_response(400, f'Invalid queue name. Must be one of: {list(DLQ_URLS.keys())}')
        
        queue_url = DLQ_URLS.get(queue_name)
        if not queue_url:
            return _error_response(400, f'Queue URL not configured for {queue_name}')
        
        # Receive messages from DLQ
        messages = _receive_messages(queue_url, batch_size)
        
        if not messages:
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({
                    'queueName': queue_name,
                    'processed': 0,
                    'succeeded': 0,
                    'failed': 0,
                    'skipped': 0,
                    'message': 'No messages in DLQ'
                })
            }
        
        # Track processed message IDs for deduplication
        processed_ids: Set[str] = set()
        
        stats = {
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0
        }
        
        for message in messages:
            receipt_handle = message.get('ReceiptHandle')
            message_body = json.loads(message.get('Body', '{}'))
            message_id = message.get('MessageId')
            
            # Requirement 9.2: Deduplicate using messageId
            original_message_id = message_body.get('originalMessageId', message_id)
            if original_message_id in processed_ids:
                logger.info(f"Skipping duplicate message: {original_message_id}")
                _delete_message(queue_url, receipt_handle)
                stats['skipped'] += 1
                continue
            
            processed_ids.add(original_message_id)
            
            # Get or create DLQ tracking record
            dlq_record = _get_or_create_dlq_record(original_message_id, queue_name, message_body)
            retry_count = int(dlq_record.get('retryCount', 0))
            
            # Requirement 9.7: Skip messages exceeding max retries
            if retry_count >= MAX_RETRIES:
                logger.warning(json.dumps({
                    'event': 'max_retries_exceeded',
                    'messageId': original_message_id,
                    'retryCount': retry_count,
                    'requestId': request_id
                }))
                _delete_message(queue_url, receipt_handle)
                stats['skipped'] += 1
                continue
            
            stats['processed'] += 1
            
            # Requirement 9.4: Apply original processing logic
            success = _replay_message(queue_name, message_body, request_id)
            
            if success:
                # Requirement 9.5: Delete from DLQ on success
                _delete_message(queue_url, receipt_handle)
                _delete_dlq_record(original_message_id)
                stats['succeeded'] += 1
                
                logger.info(json.dumps({
                    'event': 'replay_success',
                    'messageId': original_message_id,
                    'requestId': request_id
                }))
            else:
                # Requirement 9.6: Increment retryCount on failure
                _increment_retry_count(original_message_id, queue_name, message_body)
                stats['failed'] += 1
                
                logger.warning(json.dumps({
                    'event': 'replay_failed',
                    'messageId': original_message_id,
                    'retryCount': retry_count + 1,
                    'requestId': request_id
                }))
        
        logger.info(json.dumps({
            'event': 'dlq_replay_complete',
            'queueName': queue_name,
            'stats': stats,
            'requestId': request_id
        }))
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'queueName': queue_name,
                **stats
            })
        }
        
    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'dlq_replay_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _error_response(500, 'Internal server error')


def _receive_messages(queue_url: str, batch_size: int) -> List[Dict]:
    """Receive messages from SQS DLQ."""
    try:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=min(batch_size, 10),  # SQS max is 10
            WaitTimeSeconds=1,
            VisibilityTimeout=300  # 5 minutes
        )
        return response.get('Messages', [])
    except Exception as e:
        logger.error(f"Receive messages error: {str(e)}")
        return []


def _delete_message(queue_url: str, receipt_handle: str) -> None:
    """Delete message from SQS."""
    try:
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle
        )
    except Exception as e:
        logger.error(f"Delete message error: {str(e)}")


def _get_or_create_dlq_record(message_id: str, queue_name: str, payload: Dict) -> Dict:
    """Get or create DLQ tracking record."""
    try:
        dlq_table = dynamodb.Table(DLQ_MESSAGES_TABLE)
        response = dlq_table.get_item(Key={'id': message_id})
        
        if response.get('Item'):
            return response['Item']
        
        # Create new record
        now = int(time.time())
        record = {
            'id': message_id,
            'dlqMessageId': message_id,
            'originalMessageId': message_id,
            'queueName': queue_name,
            'retryCount': 0,
            'lastAttemptAt': Decimal(str(now)),
            'payload': json.dumps(payload, default=str),
            'expiresAt': Decimal(str(now + DLQ_TTL_SECONDS)),  # TTL: 7 days
        }
        
        dlq_table.put_item(Item=record)
        return record
        
    except Exception as e:
        logger.error(f"Get/create DLQ record error: {str(e)}")
        return {'retryCount': 0}


def _increment_retry_count(message_id: str, queue_name: str, payload: Dict) -> None:
    """Increment retry count for DLQ message."""
    try:
        dlq_table = dynamodb.Table(DLQ_MESSAGES_TABLE)
        now = int(time.time())
        
        dlq_table.update_item(
            Key={'id': message_id},
            UpdateExpression='SET retryCount = if_not_exists(retryCount, :zero) + :inc, lastAttemptAt = :now',
            ExpressionAttributeValues={
                ':zero': Decimal('0'),
                ':inc': Decimal('1'),
                ':now': Decimal(str(now))
            }
        )
    except Exception as e:
        logger.error(f"Increment retry count error: {str(e)}")


def _delete_dlq_record(message_id: str) -> None:
    """Delete DLQ tracking record on success."""
    try:
        dlq_table = dynamodb.Table(DLQ_MESSAGES_TABLE)
        dlq_table.delete_item(Key={'id': message_id})
    except Exception as e:
        logger.error(f"Delete DLQ record error: {str(e)}")


def _replay_message(queue_name: str, message_body: Dict, request_id: str) -> bool:
    """Replay message using original handler."""
    try:
        handler_function = HANDLERS.get(queue_name)
        if not handler_function:
            logger.error(f"No handler configured for queue: {queue_name}")
            return False
        
        # Extract original record/payload
        original_record = message_body.get('originalRecord', message_body)
        
        # Invoke original handler
        response = lambda_client.invoke(
            FunctionName=handler_function,
            InvocationType='RequestResponse',
            Payload=json.dumps(original_record, default=str)
        )
        
        result = json.loads(response['Payload'].read())
        if response.get('FunctionError'):
            return False
        if queue_name == 'bulk-dlq':
            # bulk-worker answers a direct invoke with the job outcome, not an HTTP response:
            # {'jobId', 'status', ...} or {'error': ...}. Reading `statusCode` counted every
            # replay as failed, re-ran the job on each retry and dropped it after MAX_RETRIES.
            return (isinstance(result, dict) and 'error' not in result
                    and bool(result.get('status')))
        status_code = result.get('statusCode', 500)
        
        return status_code in [200, 201]
        
    except Exception as e:
        logger.error(f"Replay message error: {str(e)}")
        return False


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }
