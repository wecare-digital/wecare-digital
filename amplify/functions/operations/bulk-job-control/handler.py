"""
Bulk Job Control Lambda Function

Purpose: Handle pause/resume/cancel operations for bulk jobs
Requirements: 8.7

Allows operators to control bulk job execution.
"""

import os
import json
import time
import logging
import boto3
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
sqs = boto3.client('sqs', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
BULK_JOBS_TABLE = os.environ.get('BULK_JOBS_TABLE', 'stack-wecare-digital-BulkJobsTable')
BULK_RECIPIENTS_TABLE = os.environ.get('BULK_RECIPIENTS_TABLE', 'stack-wecare-digital-BulkRecipientsTable')
BULK_QUEUE_URL = os.environ.get('BULK_QUEUE_URL', '')
REPORT_BUCKET = os.environ.get('REPORT_BUCKET', media_paths.BUCKET)
REPORT_PREFIX = os.environ.get('REPORT_PREFIX', media_paths.PUBLIC_STREAM_MEDIA_REPORTS_PREFIX)


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle bulk job control operations.
    Requirement 8.7: Implement pause, resume, and cancel operations
    """
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'PUT')
    path_params = event.get('pathParameters') or {}
    job_id = path_params.get('jobId')
    
    # Handle GET request - get single job
    if http_method == 'GET':
        if not job_id:
            return _error_response(400, 'jobId is required')
        job = _get_job(job_id)
        if not job:
            return _error_response(404, 'Job not found')
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'id': job.get('jobId'),
                'jobId': job.get('jobId'),
                'channel': job.get('channel', 'WHATSAPP').upper(),
                'status': job.get('status', 'PENDING').upper(),
                'totalRecipients': int(job.get('totalRecipients', 0)),
                'sentCount': int(job.get('sentCount', 0)),
                'failedCount': int(job.get('failedCount', 0)),
                'createdAt': str(job.get('createdAt', '')),
                'updatedAt': str(job.get('updatedAt', '')),
            })
        }
    
    # Handle DELETE request - delete job
    if http_method == 'DELETE':
        if not job_id:
            return _error_response(400, 'jobId is required')
        job = _get_job(job_id)
        if not job:
            return _error_response(404, 'Job not found')
        result = _delete_job(job_id, request_id)
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'jobId': job_id,
                'deleted': result.get('deleted', False),
                'message': result.get('message')
            })
        }
    
    try:
        # Parse request body for PUT
        body = json.loads(event.get('body', '{}'))
        job_id = job_id or body.get('jobId')
        action = body.get('action') or body.get('status', '').lower()
        
        # Map status to action
        if action in ['paused', 'pause']:
            action = 'pause'
        elif action in ['in_progress', 'pending', 'resume']:
            action = 'resume'
        elif action in ['cancelled', 'cancel']:
            action = 'cancel'
        
        if not job_id:
            return _error_response(400, 'jobId is required')
        
        if action not in ['pause', 'resume', 'cancel']:
            return _error_response(400, 'Invalid action. Must be pause, resume, or cancel')
        
        # Get current job
        job = _get_job(job_id)
        if not job:
            return _error_response(404, 'Job not found')
        
        current_status = job.get('status')
        
        # Validate state transitions
        if action == 'pause' and current_status not in ['pending', 'in_progress']:
            return _error_response(400, 'Can only pause pending or in-progress jobs')
        
        if action == 'resume' and current_status != 'paused':
            return _error_response(400, 'Can only resume paused jobs')
        
        if action == 'cancel' and current_status in ['completed', 'cancelled']:
            return _error_response(400, 'Job already completed or cancelled')
        
        # Execute action
        if action == 'pause':
            result = _pause_job(job_id, request_id)
        elif action == 'resume':
            result = _resume_job(job_id, job, request_id)
        else:  # cancel
            result = _cancel_job(job_id, job, request_id)
        
        logger.info(json.dumps({
            'event': 'bulk_job_control',
            'jobId': job_id,
            'action': action,
            'result': result,
            'requestId': request_id
        }))
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'jobId': job_id,
                'action': action,
                'status': result.get('status'),
                'message': result.get('message')
            })
        }
        
    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'bulk_job_control_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _error_response(500, 'Internal server error')


def _get_job(job_id: str) -> Dict[str, Any]:
    """Get bulk job record."""
    try:
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        response = jobs_table.get_item(Key={'id': job_id})
        return response.get('Item', {})
    except Exception:
        return {}


def _pause_job(job_id: str, request_id: str) -> Dict[str, Any]:
    """Pause a bulk job."""
    try:
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #status = :status, pausedAt = :now, updatedAt = :now',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'paused',
                ':now': Decimal(str(int(time.time())))
            }
        )
        
        return {'status': 'paused', 'message': 'Job paused successfully'}
        
    except Exception as e:
        logger.error(f"Pause job error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def _resume_job(job_id: str, job: Dict, request_id: str) -> Dict[str, Any]:
    """Resume a paused bulk job."""
    try:
        # Update status to pending
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #status = :status, resumedAt = :now, updatedAt = :now',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'pending',
                ':now': Decimal(str(int(time.time())))
            }
        )
        
        # Re-enqueue unprocessed recipients
        pending_recipients = _get_pending_recipients(job_id)
        
        if pending_recipients and BULK_QUEUE_URL:
            # Chunk and re-enqueue
            chunk_size = 100
            chunks = [pending_recipients[i:i+chunk_size] for i in range(0, len(pending_recipients), chunk_size)]
            
            for chunk_index, chunk in enumerate(chunks):
                message = {
                    'jobId': job_id,
                    'chunkIndex': f"resume-{chunk_index}",
                    'recipients': chunk,
                    'channel': job.get('channel'),
                    'content': job.get('content', ''),
                    'templateName': job.get('templateName'),
                    'templateParams': job.get('templateParams', []),
                }
                
                sqs.send_message(
                    QueueUrl=BULK_QUEUE_URL,
                    MessageBody=json.dumps(message, default=str)
                )
        
        return {
            'status': 'pending',
            'message': f'Job resumed with {len(pending_recipients)} pending recipients'
        }
        
    except Exception as e:
        logger.error(f"Resume job error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def _cancel_job(job_id: str, job: Dict, request_id: str) -> Dict[str, Any]:
    """Cancel a bulk job."""
    try:
        now = int(time.time())
        
        # Update status to cancelled
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET #status = :status, cancelledAt = :now, updatedAt = :now',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'cancelled',
                ':now': Decimal(str(now))
            }
        )
        
        # Update pending recipients to cancelled
        _cancel_pending_recipients(job_id)
        
        # Generate partial report
        _generate_partial_report(job_id, job, request_id)
        
        return {'status': 'cancelled', 'message': 'Job cancelled. Partial report generated.'}
        
    except Exception as e:
        logger.error(f"Cancel job error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def _get_pending_recipients(job_id: str) -> list:
    """Get list of pending recipients for a job."""
    try:
        recipients_table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
        response = recipients_table.query(
            KeyConditionExpression='jobId = :jid',
            FilterExpression='#status = :pending',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':jid': job_id,
                ':pending': 'pending'
            }
        )
        
        return [
            {'contactId': r.get('contactId'), 'recipientId': r.get('recipientId')}
            for r in response.get('Items', [])
        ]
    except Exception:
        return []


def _cancel_pending_recipients(job_id: str) -> None:
    """Update all pending recipients to cancelled status."""
    try:
        recipients_table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
        response = recipients_table.query(
            KeyConditionExpression='jobId = :jid',
            FilterExpression='#status = :pending',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':jid': job_id,
                ':pending': 'pending'
            }
        )
        
        now = Decimal(str(int(time.time())))
        
        for item in response.get('Items', []):
            recipients_table.update_item(
                Key={'id': item.get('id', item.get('recipientId'))},
                UpdateExpression='SET #status = :status, updatedAt = :now',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'cancelled',
                    ':now': now
                }
            )
    except Exception as e:
        logger.error(f"Cancel pending recipients error: {str(e)}")


def _generate_partial_report(job_id: str, job: Dict, request_id: str) -> None:
    """Generate partial report for cancelled job."""
    try:
        # Get recipient details
        recipients_table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
        response = recipients_table.query(
            KeyConditionExpression='jobId = :jid',
            ExpressionAttributeValues={':jid': job_id}
        )
        
        recipients = response.get('Items', [])
        sent_count = sum(1 for r in recipients if r.get('status') == 'sent')
        failed_count = sum(1 for r in recipients if r.get('status') == 'failed')
        cancelled_count = sum(1 for r in recipients if r.get('status') == 'cancelled')
        
        report = {
            'jobId': job_id,
            'channel': job.get('channel'),
            'totalRecipients': int(job.get('totalRecipients', 0)),
            'sentCount': sent_count,
            'failedCount': failed_count,
            'cancelledCount': cancelled_count,
            'status': 'cancelled',
            'createdAt': str(job.get('createdAt')),
            'cancelledAt': int(time.time()),
            'createdBy': job.get('createdBy'),
            'recipients': [
                {
                    'contactId': r.get('contactId'),
                    'status': r.get('status'),
                    'error': r.get('errorDetails'),
                }
                for r in recipients
            ]
        }
        
        # Store in S3
        report_key = f"{REPORT_PREFIX}wecare-digital-{job_id}-partial.json"
        s3.put_object(
            Bucket=REPORT_BUCKET,
            Key=report_key,
            Body=json.dumps(report, indent=2, default=str),
            ContentType='application/json'
        )
        
        # Update job with report location
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.update_item(
            Key={'id': job_id},
            UpdateExpression='SET reportS3Key = :key',
            ExpressionAttributeValues={':key': report_key}
        )
        
        logger.info(json.dumps({
            'event': 'partial_report_generated',
            'jobId': job_id,
            'reportKey': report_key,
            'requestId': request_id
        }))
        
    except Exception as e:
        logger.error(f"Generate partial report error: {str(e)}")


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }


def _delete_job(job_id: str, request_id: str) -> Dict[str, Any]:
    """Delete a bulk job and its recipients."""
    try:
        # Delete job record
        jobs_table = dynamodb.Table(BULK_JOBS_TABLE)
        jobs_table.delete_item(Key={'id': job_id})
        
        # Delete recipients (optional - could be expensive for large jobs)
        try:
            recipients_table = dynamodb.Table(BULK_RECIPIENTS_TABLE)
            response = recipients_table.query(
                KeyConditionExpression='jobId = :jid',
                ExpressionAttributeValues={':jid': job_id}
            )
            
            with recipients_table.batch_writer() as batch:
                for item in response.get('Items', []):
                    batch.delete_item(Key={
                        'id': item.get('id', item.get('recipientId'))
                    })
        except Exception as e:
            logger.warning(f"Failed to delete recipients: {str(e)}")
        
        logger.info(json.dumps({
            'event': 'bulk_job_deleted',
            'jobId': job_id,
            'requestId': request_id
        }))
        
        return {'deleted': True, 'message': 'Job deleted successfully'}
        
    except Exception as e:
        logger.error(f"Delete job error: {str(e)}")
        return {'deleted': False, 'message': str(e)}
