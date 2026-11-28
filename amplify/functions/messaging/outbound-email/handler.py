"""
Outbound Email Lambda Function

Purpose: Send emails via Amazon SES
"""

import os
import json
import uuid
import time
import logging
import boto3
from typing import Dict, Any
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.privacy import mask_contact_id  # contactId is `wa` + the customer's digits
from lambda_utils.message_store import put_message  # canonical MessagesTable writer

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
ses = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'noreply@wecare.digital')
REPLY_TO_EMAIL = os.environ.get('REPLY_TO_EMAIL', 'support@wecare.digital')
MESSAGE_TTL_SECONDS = 30 * 24 * 60 * 60  # `expiresAt` stamp only; TTL is disabled, rows are kept


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Send email message."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
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
    
    logger.info(json.dumps({
        'event': 'outbound_email_start',
        'requestId': request_id
    }))

    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        contact_id = body.get('contactId')
        subject = body.get('subject', '')
        content = body.get('content', '')
        html_content = body.get('htmlContent')
        
        if not contact_id:
            return _response(400, {'error': 'contactId is required'})
        
        if not subject:
            return _response(400, {'error': 'subject is required'})
        
        if not content and not html_content:
            return _response(400, {'error': 'content or htmlContent is required'})
        
        # Get contact details
        contact = _get_contact(contact_id)
        if not contact:
            return _response(404, {'error': 'Contact not found'})
        
        email = contact.get('email', '')
        if not email:
            return _response(400, {'error': 'Contact has no email address'})
        
        # Check opt-in status
        if not contact.get('optInEmail', False) and not contact.get('allowlistEmail', False):
            return _response(403, {'error': 'Contact has not opted in for email'})
        
        # Generate message ID
        message_id = str(uuid.uuid4())
        
        # Send email
        result = _send_email(email, subject, content, html_content, contact.get('name'), request_id)
        
        if not result.get('success'):
            # Store failed message
            _store_message(message_id, contact_id, subject, content, 'FAILED', result.get('error'))
            return _response(500, {
                'error': result.get('error', 'Failed to send email'),
                'messageId': message_id
            })
        
        # Store successful message
        _store_message(message_id, contact_id, subject, content, 'SENT', None, result.get('sesMessageId'))
        
        logger.info(json.dumps({
            'event': 'email_sent',
            'messageId': message_id,
            'contactId': mask_contact_id(contact_id),
            'sesMessageId': result.get('sesMessageId'),
            'requestId': request_id
        }))
        
        return _response(200, {
            'messageId': message_id,
            'status': 'sent',
            'sesMessageId': result.get('sesMessageId')
        })
        
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})
    except Exception as e:
        logger.error(json.dumps({
            'event': 'outbound_email_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _response(500, {'error': 'Internal server error'})


def _get_contact(contact_id: str) -> Dict[str, Any]:
    """Get contact from DynamoDB."""
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        response = table.get_item(Key={'id': contact_id})
        return response.get('Item', {})
    except Exception as e:
        logger.error(f"Get contact error: {str(e)}")
        return {}


def _send_email(to_email: str, subject: str, text_content: str, 
                html_content: str = None, recipient_name: str = None, 
                request_id: str = None) -> Dict[str, Any]:
    """Send email via Amazon SES."""
    try:
        # Build destination
        destination = {'ToAddresses': [to_email]}
        
        # Build message body
        body = {}
        if text_content:
            body['Text'] = {'Data': text_content, 'Charset': 'UTF-8'}
        if html_content:
            body['Html'] = {'Data': html_content, 'Charset': 'UTF-8'}
        
        # Send email
        response = ses.send_email(
            Source=FROM_EMAIL,
            Destination=destination,
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': body
            },
            ReplyToAddresses=[REPLY_TO_EMAIL],
        )
        
        return {'success': True, 'sesMessageId': response.get('MessageId')}
        
    except ses.exceptions.MessageRejected as e:
        logger.error(f"SES message rejected: {str(e)}")
        return {'success': False, 'error': 'Email rejected by SES'}
    except ses.exceptions.MailFromDomainNotVerifiedException as e:
        logger.error(f"SES domain not verified: {str(e)}")
        return {'success': False, 'error': 'Sender domain not verified'}
    except Exception as e:
        logger.error(f"SES error: {str(e)}")
        return {'success': False, 'error': str(e)}


def _store_message(message_id: str, contact_id: str, subject: str, content: str, 
                   status: str, error: str = None, ses_message_id: str = None) -> None:
    """Store message record in the canonical MessagesTable via the shared writer.
    Ensures consistent lowercase channel + safe (sparse) contactId for the GSIs."""
    put_message(
        channel='email',
        direction='outbound',
        contact_id=contact_id or '',
        content=content or '',
        status=(status or 'sent').lower(),
        message_id=message_id,
        message_type='email',
        subject=subject or None,
        error_details=error or None,
        ses_message_id=ses_message_id or None,
    )


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body)
    }
