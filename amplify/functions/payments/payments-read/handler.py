"""
Payments Read Lambda Function

Purpose: List and retrieve payment records
"""

import os
import json
import boto3
from typing import Dict, Any
from boto3.dynamodb.conditions import Attr

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.privacy import mask_email, mask_phone

# Configure logging
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
PAYMENTS_TABLE = os.environ.get('PAYMENTS_TABLE', 'stack-wecare-digital-PaymentsTable')


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle payment read operations."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event, required_role='Viewer')
    if _auth is not None:
        return _auth
    # Payer phone and email are customer data: Operator and Admin see them; a Viewer sees them
    # masked and cannot search by them.
    show_contacts = _can_see_contacts(event)

    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')

    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}
    
    logger.info(json.dumps({
        'event': 'payments_handler',
        'method': http_method,
        'requestId': request_id
    }))
    
    try:
        # GET /payments - List payments
        if http_method == 'GET' and not path_params.get('paymentId'):
            return _list_payments(query_params, request_id, show_contacts)
        
        # GET /payments/{paymentId} - Get single payment
        if http_method == 'GET' and path_params.get('paymentId'):
            return _get_payment(path_params['paymentId'], request_id, show_contacts)
        
        return _response(405, {'error': 'Method not allowed'})
        
    except Exception as e:
        logger.error(json.dumps({
            'event': 'payments_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _response(500, {'error': 'Internal server error'})


def _can_see_contacts(event: Dict[str, Any]) -> bool:
    """True for an Operator or Admin. An event without a verified role is treated as a Viewer."""
    from lambda_utils.middleware import ROLE_HIERARCHY
    role = str((event.get('_auth') or {}).get('role') or '')
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY['Operator']


def _list_payments(params: Dict, request_id: str, show_contacts: bool = False) -> Dict[str, Any]:
    """List payments with optional filters."""
    try:
        table = dynamodb.Table(PAYMENTS_TABLE)
        max_results = int(params.get('limit', 100))
        
        scan_kwargs = {}
        filter_expressions = []
        
        if params.get('status'):
            filter_expressions.append(Attr('status').eq(params['status']))
        if params.get('contact'):
            if not show_contacts:
                return _response(403, {'error': 'Operator role required to search by payer contact'})
            filter_expressions.append(Attr('contact').contains(params['contact']))
        if params.get('orderId'):
            filter_expressions.append(Attr('orderId').eq(params['orderId']))
        if params.get('referenceId'):
            filter_expressions.append(Attr('referenceId').eq(params['referenceId']))
        
        if filter_expressions:
            combined = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined = combined & expr
            scan_kwargs['FilterExpression'] = combined
        
        # Every matching row, newest first, THEN the limit. Truncating a scan before sorting
        # returned an arbitrary 100 rather than the newest 100.
        payments = []
        while True:
            result = table.scan(**scan_kwargs)
            payments.extend(result.get('Items', []))
            if 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        
        # Sort by createdAt descending
        payments.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)
        
        # Trim to requested limit
        payments = payments[:max_results]
        
        return _response(200, {
            'payments': [_normalize_payment(p, show_contacts) for p in payments],
            'count': len(payments)
        })
        
    except Exception as e:
        logger.error(f"List payments error: {str(e)}")
        return _response(500, {'error': str(e)})


def _get_payment(payment_id: str, request_id: str, show_contacts: bool = False) -> Dict[str, Any]:
    """Get a single payment."""
    try:
        table = dynamodb.Table(PAYMENTS_TABLE)
        result = table.get_item(Key={'id': payment_id})
        payment = result.get('Item')
        
        if payment:
            return _response(200, {'payment': _normalize_payment(payment, show_contacts)})
        
        # Try by paymentId GSI (Razorpay ID)
        from boto3.dynamodb.conditions import Key as DDBKey
        result = table.query(
            IndexName='paymentId-index',
            KeyConditionExpression=DDBKey('paymentId').eq(payment_id),
            Limit=1,
        )
        items = result.get('Items', [])
        if items:
            return _response(200, {'payment': _normalize_payment(items[0], show_contacts)})
        
        return _response(404, {'error': 'Payment not found'})
        
    except Exception as e:
        logger.error(f"Get payment error: {str(e)}")
        return _response(500, {'error': str(e)})


def _normalize_payment(item: Dict, show_contacts: bool = False) -> Dict:
    """Normalize payment record for API response.

    `amount` is integer paise, as written by razorpay-webhook's `_store_payment_record`.

    This used to guess the unit by magnitude: `amount / 100 if amount > 1000 else amount`.
    That is wrong below ₹10 in both directions - 500 paise (₹5) reported as ₹500, and 999
    paise (₹9.99) reported as ₹999 - and a magnitude test can never recover a unit that
    was not recorded. The value was computed and then never used, so no response was
    actually affected; it is removed rather than left one edit away from being wired in.

    The unit is now explicit via `payment_status.rupees_str`, which returns a string
    precisely so it cannot be summed or compared by accident. Every float-rupee bug in
    this tree started as a display conversion that later got used in arithmetic.
    """
    try:
        from lambda_utils import payment_status
        amount_paise = payment_status.paise(item.get('amount', 0))
        rupees = payment_status.rupees_str(amount_paise)
    except Exception:
        amount_paise, rupees = 0, '0.00'

    return {
        'id': item.get('id', ''),
        'paymentId': item.get('paymentId', ''),
        'orderId': item.get('orderId', ''),
        'referenceId': item.get('referenceId', ''),
        'status': item.get('status', 'unknown'),
        # Kept for the existing consumers of this shape. `amountPaise` is the one to read.
        'amount': float(item.get('amount', 0)),
        'amountPaise': amount_paise,
        # A string, and derived from paise rather than from whatever the stored
        # `amountInRupees` happens to hold - that field was itself built from a float
        # division at write time.
        'amountRupees': rupees,
        # Retained because src/pages/dm/commerce reads it. Now derived from paise here
        # instead of echoing the stored float, so the two cannot disagree. Dropping it
        # would have made that page fall back to `amount` and render paise as rupees -
        # ₹250000 for a ₹2500 payment.
        'amountInRupees': float(rupees),
        'currency': item.get('currency', 'INR'),
        'method': item.get('method', ''),
        'contact': item.get('contact', '') if show_contacts else _masked(item.get('contact'), mask_phone),
        'email': item.get('email', '') if show_contacts else _masked(item.get('email'), mask_email),
        'source': item.get('source', ''),
        'createdAt': int(float(item.get('createdAt', 0))),
    }


def _masked(value: Any, mask) -> str:
    return mask(str(value)) if value else ''


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, default=str)
    }
