"""
Unified Contacts Lambda Function

Purpose: All contact CRUD + search in a single handler
Routes by HTTP method:
  GET    /contacts              → list all contacts
  GET    /contacts/{contactId}  → get single contact
  GET    /contacts/search?q=... → search contacts
  POST   /contacts              → create contact
  PUT    /contacts/{contactId}  → update contact
  DELETE /contacts/{contactId}  → soft/hard delete contact

DynamoDB Table: stack-wecare-digital-ContactsTable
"""

import os
import json
import uuid
import time
import logging
import re
import base64
import boto3
from typing import Dict, Any, List, Optional
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from lambda_utils.response import cors_response, options_response, extract_origin
from lambda_utils.logging import get_logger, log_event
from lambda_utils.validation import sanitize_html, sanitize_dict, normalize_phone
from lambda_utils import contact_key  # `id` is the physical key; `contactId` is its alias
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
INBOUND_TABLE = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)

# The checkout delivery address, READ-ONLY on this handler.
#
# `auth/customer-profile` writes `checkoutDeliveryAddress` (a Map) and
# `checkoutAddressUpdatedAt` (epoch seconds) via `lambda_utils.ecommerce.contact_address`, on the
# same ContactsTable row the CRM displays. The CRM renders `shippingAddress`, so an address a
# customer typed at checkout was invisible here - two vocabularies for one fact, and nothing
# reconciling them.
#
# The fix is for the CRM to READ the checkout attribute, not for checkout to write the CRM's
# fields: that keeps a checkout-captured address distinguishable from a hand-curated one, needs
# no migration, and removes the risk of a checkout save overwriting what a human typed.
#
# Deliberately NOT in `ALLOWED_UPDATE_FIELDS`. Hand-editing it in the CRM could produce a map
# `contact_address.from_contact` re-validates to None, which demotes a payable customer to
# `409 DELIVERY_DETAILS_REQUIRED` at checkout. One writer, and it is the checkout path.
#
# THIS CONSTANT IS A TEST ANCHOR, NOT PROJECTION CONFIGURATION. No handler code reads it, and
# that is deliberate rather than an oversight: `_list_all`, `_read_one` and `_search` return the
# whole item through `_from_dynamo`, so the two attributes already reach the client and there is
# nothing for a list of names to switch on. Narrowing the reads to this tuple would be strictly
# worse - it would turn every attribute NOT named here into a silent omission.
#
# What it buys is a rename trip-wire. `test_crm_contact_claim_and_checkout_address.py` asserts
# this tuple equals `contact_address.ATTRIBUTE` / `UPDATED_ATTRIBUTE`, so renaming either on the
# write side fails a test instead of silently blanking a CRM column; a second test forbids a
# `ProjectionExpression` appearing on any of the three readers, which is the obvious next
# optimisation on a full-table scan and would drop both attributes without naming them.
CHECKOUT_ADDRESS_READ_FIELDS = ('checkoutDeliveryAddress', 'checkoutAddressUpdatedAt')

ALLOWED_UPDATE_FIELDS = {
    'name', 'phone', 'email', 'shippingAddress', 'billingAddress',
    'shippingAddressJson', 'billingAddressJson', 'gstin',
    'optInWhatsApp', 'optInSms', 'optInEmail',
    'allowlistWhatsApp', 'allowlistSms', 'allowlistEmail',
    'tags', 'bsuid', 'parentBsuid', 'username', 'contactBookName',
    'addressLine1', 'addressLine2', 'city', 'state', 'postalCode', 'pincode',
    'houseNumber', 'buildingName', 'towerNumber', 'floorNumber',
    'landmark', 'country', 'companyName', 'designation', 'preferredLanguage',
    'satisfactionScore', 'isPep', 'pepDetails', 'paidBy',
}
OPT_IN_FIELDS = {
    'optInWhatsApp', 'optInSms', 'optInEmail',
    'allowlistWhatsApp', 'allowlistSms', 'allowlistEmail',
}

DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100

# Fix #14: Simple in-memory rate limiting for create operations
# Note: In a multi-Lambda environment, consider using DynamoDB or ElastiCache for distributed rate limiting
_rate_limit_store: Dict[str, list] = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_CREATES = 30  # max creates per window per IP


def _check_rate_limit(source_ip: str) -> bool:
    """Returns True if rate limit exceeded."""
    now = time.time()
    if source_ip not in _rate_limit_store:
        _rate_limit_store[source_ip] = []
    # Clean old entries
    _rate_limit_store[source_ip] = [t for t in _rate_limit_store[source_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[source_ip]) >= RATE_LIMIT_MAX_CREATES:
        return True
    _rate_limit_store[source_ip].append(now)
    return False


# ─── Main Router ────────────────────────────────────────────────────────────

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route by HTTP method to the appropriate action."""
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'GET')).upper()

    if method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    path_params = event.get('pathParameters', {}) or {}
    query_params = event.get('queryStringParameters', {}) or {}
    contact_id = path_params.get('contactId') or path_params.get('proxy')
    resource = event.get('resource', event.get('rawPath', ''))

    try:
        # GET [retired public path]/search?q=...
        if method == 'GET' and ('search' in resource or query_params.get('q')):
            return _search(query_params, request_id, origin)

        # GET [retired public path]?stats=count — lightweight count-only (no full scan)
        if method == 'GET' and query_params.get('stats') == 'count':
            return _count_active(request_id, origin)

        # GET [retired public path] or GET [retired public path]/{id}
        if method == 'GET':
            if contact_id:
                return _read_one(contact_id, request_id, origin)
            return _list_all(query_params, request_id, origin)

        # POST [retired public path] — Fix #14: rate limited
        if method == 'POST':
            source_ip = (event.get('requestContext', {}).get('identity', {}) or {}).get('sourceIp', 'unknown')
            if _check_rate_limit(source_ip):
                return cors_response(429, {'error': 'Too many requests. Please try again later.'}, origin)
            body = json.loads(event.get('body', '{}'))
            return _create(body, request_id, origin)

        # PUT [retired public path]/{id}
        if method == 'PUT':
            if not contact_id:
                return cors_response(400, {'error': 'contactId is required'}, origin)
            body = json.loads(event.get('body', '{}'))
            return _update(contact_id, body, request_id, origin)

        # DELETE [retired public path]/{id}
        if method == 'DELETE':
            if not contact_id:
                return cors_response(400, {'error': 'contactId is required'}, origin)
            hard = query_params.get('hard', 'false').lower() == 'true'
            return _delete(contact_id, hard, request_id, origin)

        return cors_response(405, {'error': f'Method {method} not allowed'}, origin)

    except json.JSONDecodeError:
        return cors_response(400, {'error': 'Invalid JSON in request body'}, origin)
    except Exception as e:
        log_event(logger, 'contacts_error', level='error', error=str(e), method=method, requestId=request_id)
        return cors_response(500, {'error': 'Internal server error'}, origin)


# ─── CREATE ─────────────────────────────────────────────────────────────────

def _create(body: Dict[str, Any], request_id: str, origin: str = '') -> Dict[str, Any]:
    # Sanitize user-provided string fields to prevent XSS
    body = sanitize_dict(body, ['name', 'shippingAddress', 'billingAddress'], max_length=500)

    phone = body.get('phone', '').strip() if body.get('phone') else None
    email = body.get('email', '').strip().lower() if body.get('email') else None

    # Normalize phone to digits-only E.164 before validation/storage
    if phone:
        normalized = normalize_phone(phone)
        if normalized:
            phone = f'+{normalized}'

    if not phone and not email:
        return cors_response(400, {'error': 'At least one of phone or email is required'}, origin)
    if phone and not _validate_phone(phone):
        return cors_response(400, {'error': 'Invalid phone number format'}, origin)
    if email and not _validate_email(email):
        return cors_response(400, {'error': 'Invalid email format'}, origin)

    # Fix #4: Server-side duplicate detection
    dup = _check_duplicate(phone, email)
    if dup:
        return cors_response(409, {'error': dup}, origin)

    contact_id = str(uuid.uuid4())
    now = int(time.time())

    contact = {
        **contact_key.contact_item_keys(contact_id),
        'name': body.get('name', '').strip(),
        'phone': phone,
        'email': email,
        'bsuid': body.get('bsuid', '').strip() if body.get('bsuid') else None,
        'parentBsuid': body.get('parentBsuid', '').strip() if body.get('parentBsuid') else None,
        'username': body.get('username', '').strip() if body.get('username') else None,
        'contactBookName': body.get('contactBookName', '').strip() if body.get('contactBookName') else None,
        'shippingAddress': body.get('shippingAddress', '').strip() if body.get('shippingAddress') else None,
        'billingAddress': body.get('billingAddress', '').strip() if body.get('billingAddress') else None,
        'shippingAddressJson': body.get('shippingAddressJson', '').strip() if body.get('shippingAddressJson') else None,
        'billingAddressJson': body.get('billingAddressJson', '').strip() if body.get('billingAddressJson') else None,
        'gstin': body.get('gstin', '').strip() if body.get('gstin') else None,
        'addressLine1': body.get('addressLine1', '').strip() if body.get('addressLine1') else None,
        'addressLine2': body.get('addressLine2', '').strip() if body.get('addressLine2') else None,
        'city': body.get('city', '').strip() if body.get('city') else None,
        'state': body.get('state', '').strip() if body.get('state') else None,
        'postalCode': body.get('postalCode', '').strip() if body.get('postalCode') else None,
        'pincode': body.get('pincode', '').strip() if body.get('pincode') else body.get('postalCode', '').strip() if body.get('postalCode') else None,
        'houseNumber': body.get('houseNumber', '').strip() if body.get('houseNumber') else None,
        'buildingName': body.get('buildingName', '').strip() if body.get('buildingName') else None,
        'towerNumber': body.get('towerNumber', '').strip() if body.get('towerNumber') else None,
        'floorNumber': body.get('floorNumber', '').strip() if body.get('floorNumber') else None,
        'landmark': body.get('landmark', '').strip() if body.get('landmark') else None,
        'country': body.get('country', '').strip() if body.get('country') else 'IN',
        'companyName': body.get('companyName', '').strip() if body.get('companyName') else None,
        'designation': body.get('designation', '').strip() if body.get('designation') else None,
        'preferredLanguage': body.get('preferredLanguage', '').strip() if body.get('preferredLanguage') else None,
        'optInWhatsApp': body.get('optInWhatsApp', True) if isinstance(body.get('optInWhatsApp'), bool) else True,
        'optInSms': body.get('optInSms', True) if isinstance(body.get('optInSms'), bool) else True,
        'optInEmail': body.get('optInEmail', True) if isinstance(body.get('optInEmail'), bool) else True,
        'allowlistWhatsApp': body.get('allowlistWhatsApp', True) if isinstance(body.get('allowlistWhatsApp'), bool) else True,
        'allowlistSms': body.get('allowlistSms', True) if isinstance(body.get('allowlistSms'), bool) else True,
        'allowlistEmail': body.get('allowlistEmail', True) if isinstance(body.get('allowlistEmail'), bool) else True,
        'lastInboundMessageAt': None,
        'tags': body.get('tags', []),
        'createdAt': now,
        'updatedAt': now,
        'deletedAt': None,
    }

    table = dynamodb.Table(CONTACTS_TABLE)
    table.put_item(Item=_to_dynamo(contact))

    log_event(logger, 'contact_created', contactId=contact_id, requestId=request_id)
    return cors_response(201, _from_dynamo(contact), origin)


# ─── READ ONE ───────────────────────────────────────────────────────────────

def _read_one(contact_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    table = dynamodb.Table(CONTACTS_TABLE)
    resp = table.get_item(Key={'id': contact_id})
    item = resp.get('Item')

    if not item or item.get('deletedAt') is not None:
        return cors_response(404, {'error': 'Contact not found'}, origin)

    log_event(logger, 'contact_read', contactId=contact_id, requestId=request_id)
    return cors_response(200, _from_dynamo(item), origin)


# ─── COUNT (lightweight stats) ──────────────────────────────────────────────

def _count_active(request_id: str, origin: str = '') -> Dict[str, Any]:
    """Return active contact count using Select='COUNT' — no full scan."""
    table = dynamodb.Table(CONTACTS_TABLE)
    total = 0
    scan_kwargs: Dict[str, Any] = {
        'Select': 'COUNT',
        'FilterExpression': Attr('deletedAt').not_exists() | Attr('deletedAt').eq(None),
    }
    while True:
        resp = table.scan(**scan_kwargs)
        total += resp.get('Count', 0)
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

    log_event(logger, 'contacts_count', count=total, requestId=request_id)
    return cors_response(200, {'activeContacts': total}, origin)


# ─── LIST ALL ───────────────────────────────────────────────────────────────

def _list_all(params: Dict[str, str], request_id: str, origin: str = '') -> Dict[str, Any]:
    """Fix #2: Paginate through ALL DynamoDB results so the frontend gets the complete list."""
    table = dynamodb.Table(CONTACTS_TABLE)
    filt = Attr('deletedAt').not_exists() | Attr('deletedAt').eq(None)

    scan_kwargs: Dict[str, Any] = {'FilterExpression': filt}

    all_items: List[Dict] = []
    while True:
        resp = table.scan(**scan_kwargs)
        all_items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

    contacts = [_from_dynamo(i) for i in all_items]

    log_event(logger, 'contacts_list', count=len(contacts), requestId=request_id)
    # Removed Cache-Control: frontend calls loadContacts() after every mutation,
    # so caching could serve stale data. Let the browser/CDN handle caching naturally.
    return cors_response(200, {'contacts': contacts}, origin)


# ─── SEARCH ─────────────────────────────────────────────────────────────────

def _search(params: Dict[str, str], request_id: str, origin: str = '') -> Dict[str, Any]:
    """Fix #3: Scan all pages so search doesn't miss results from later pages."""
    query = (params.get('q') or '').strip().lower()
    limit = min(int(params.get('limit', DEFAULT_SEARCH_LIMIT)), MAX_SEARCH_LIMIT)

    table = dynamodb.Table(CONTACTS_TABLE)
    filt = Attr('deletedAt').not_exists() | Attr('deletedAt').eq(None)

    scan_kwargs: Dict[str, Any] = {'FilterExpression': filt}

    all_items: List[Dict] = []
    while True:
        resp = table.scan(**scan_kwargs)
        all_items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

    if query:
        all_items = [i for i in all_items if _matches(i, query)]

    items = all_items[:limit]
    contacts = [_from_dynamo(i) for i in items]

    log_event(logger, 'contacts_search', query=query, count=len(contacts), requestId=request_id)
    return cors_response(200, {'contacts': contacts, 'count': len(contacts)}, origin)


# ─── UPDATE ─────────────────────────────────────────────────────────────────

def _update(contact_id: str, body: Dict[str, Any], request_id: str, origin: str = '') -> Dict[str, Any]:
    # Sanitize user-provided string fields
    body = sanitize_dict(body, ['name', 'shippingAddress', 'billingAddress'], max_length=500)

    updates = {k: v for k, v in body.items() if k in ALLOWED_UPDATE_FIELDS and k not in ('id', 'contactId')}
    if not updates:
        return cors_response(400, {'error': 'No valid fields to update'}, origin)

    for f in OPT_IN_FIELDS:
        if f in updates and not isinstance(updates[f], bool):
            return cors_response(400, {'error': f'{f} must be a boolean value'}, origin)

    if 'phone' in updates and updates['phone']:
        normalized = normalize_phone(updates['phone'])
        if normalized:
            updates['phone'] = f'+{normalized}'
        if not _validate_phone(updates['phone']):
            return cors_response(400, {'error': 'Invalid phone number format'}, origin)
    if 'email' in updates and updates['email']:
        updates['email'] = updates['email'].strip().lower()
        if not _validate_email(updates['email']):
            return cors_response(400, {'error': 'Invalid email format'}, origin)

    # Duplicate check on phone/email changes
    check_phone = updates.get('phone')
    check_email = updates.get('email')
    if check_phone or check_email:
        dup = _check_duplicate(check_phone, check_email, exclude_id=contact_id)
        if dup:
            return cors_response(409, {'error': dup}, origin)

    updates['updatedAt'] = int(time.time())

    set_parts, names, values = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        set_parts.append(f'#n{i} = :v{i}')
        names[f'#n{i}'] = k
        values[f':v{i}'] = Decimal(str(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    table = dynamodb.Table(CONTACTS_TABLE)
    try:
        resp = table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET ' + ', '.join(set_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression='attribute_exists(id)',
            ReturnValues='ALL_NEW',
        )
    except Exception as e:
        if 'ConditionalCheckFailedException' in str(e):
            return cors_response(404, {'error': 'Contact not found'}, origin)
        raise

    log_event(logger, 'contact_updated', contactId=contact_id, fields=list(updates.keys()), requestId=request_id)
    return cors_response(200, _from_dynamo(resp.get('Attributes', {})), origin)


# ─── DELETE (soft / hard) ───────────────────────────────────────────────────

def _delete(contact_id: str, hard: bool, request_id: str, origin: str = '') -> Dict[str, Any]:
    if hard:
        return _hard_delete(contact_id, request_id, origin)
    return _soft_delete(contact_id, request_id, origin)


def _soft_delete(contact_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    table = dynamodb.Table(CONTACTS_TABLE)
    # Check exists
    resp = table.get_item(Key={'id': contact_id})
    item = resp.get('Item')
    if not item:
        # Try scanning by contactId field — paginate to handle large tables
        scan_kwargs: Dict[str, Any] = {
            'FilterExpression': 'contactId = :cid AND (attribute_not_exists(deletedAt) OR deletedAt = :null)',
            'ExpressionAttributeValues': {':cid': contact_id, ':null': None},
            'Limit': 50,
        }
        item = None
        while True:
            scan_resp = table.scan(**scan_kwargs)
            items = scan_resp.get('Items', [])
            if items:
                item = items[0]
                contact_id = item.get('id', contact_id)
                break
            if 'LastEvaluatedKey' not in scan_resp:
                break
            scan_kwargs['ExclusiveStartKey'] = scan_resp['LastEvaluatedKey']
        if not item:
            return cors_response(404, {'error': 'Contact not found'}, origin)

    if item.get('deletedAt') is not None:
        return cors_response(404, {'error': 'Contact already deleted'}, origin)

    now = Decimal(str(int(time.time())))
    table.update_item(
        Key={'id': contact_id},
        UpdateExpression='SET #d = :d, #u = :u',
        ExpressionAttributeNames={'#d': 'deletedAt', '#u': 'updatedAt'},
        ExpressionAttributeValues={':d': now, ':u': now},
    )

    log_event(logger, 'contact_soft_deleted', contactId=contact_id, requestId=request_id)
    return cors_response(200, {'success': True, 'contactId': contact_id, 'deleteType': 'soft'}, origin)


def _hard_delete(contact_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    # Verify contact exists before scanning message tables
    table = dynamodb.Table(CONTACTS_TABLE)
    resp = table.get_item(Key={'id': contact_id})
    if not resp.get('Item'):
        return cors_response(404, {'error': 'Contact not found'}, origin)

    msgs_deleted = 0
    media_deleted = 0

    # Delete messages from both tables (paginate to handle large datasets)
    for tbl_name in (INBOUND_TABLE, OUTBOUND_TABLE):
        try:
            tbl = dynamodb.Table(tbl_name)
            scan_kwargs: Dict[str, Any] = {
                'FilterExpression': 'contactId = :cid',
                'ExpressionAttributeValues': {':cid': contact_id},
            }
            while True:
                resp = tbl.scan(**scan_kwargs)
                for msg in resp.get('Items', []):
                    s3_key = msg.get('s3Key')
                    if s3_key:
                        try:
                            _delete_s3(s3_key)
                            media_deleted += 1
                        except Exception as e:
                            logger.warning(f"S3 media delete failed for {s3_key}: {e}")
                    try:
                        tbl.delete_item(Key={'id': msg.get('id') or msg.get('messageId')})
                        msgs_deleted += 1
                    except Exception as e:
                        logger.warning(f"Message delete failed: {e}")
                if 'LastEvaluatedKey' not in resp:
                    break
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
        except Exception as e:
            logger.warning(f"Error scanning {tbl_name}: {e}")

    # Delete contact
    try:
        dynamodb.Table(CONTACTS_TABLE).delete_item(Key={'id': contact_id})
    except Exception as e:
        logger.warning(f"Failed to delete contact {contact_id}: {e}")

    log_event(logger, 'contact_hard_deleted', contactId=contact_id, msgs=msgs_deleted, media=media_deleted, requestId=request_id)
    return cors_response(200, {
        'success': True, 'contactId': contact_id, 'deleteType': 'hard',
        'messagesDeleted': msgs_deleted, 'mediaDeleted': media_deleted,
    }, origin)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _validate_phone(phone: str) -> bool:
    pattern = r'^[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,9}[-\s\.]?[0-9]{0,9}$'
    return bool(re.match(pattern, phone.replace(' ', '')))


def _validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def _check_duplicate(phone: Optional[str], email: Optional[str], exclude_id: Optional[str] = None) -> Optional[str]:
    """Server-side duplicate detection by phone or email.
    Uses GSIs on phone and email for efficient O(1) lookups.
    """
    if not phone and not email:
        return None
    table = dynamodb.Table(CONTACTS_TABLE)
    
    # Check phone duplicate using GSI
    if phone:
        try:
            resp = table.query(
                IndexName='phone-index',
                KeyConditionExpression='phone = :ph',
                ExpressionAttributeValues={':ph': phone},
                Limit=5,
            )
            for item in resp.get('Items', []):
                item_id = item.get('id') or item.get('contactId')
                if exclude_id and item_id == exclude_id:
                    continue
                if item.get('deletedAt') is not None:
                    continue
                return f"Phone {phone} already exists ({item.get('name', 'unnamed')})"
        except Exception as e:
            # GSI may not exist yet — fall through to scan
            logger.warning(f"Phone GSI query failed, falling back to scan: {e}")
            return _check_duplicate_scan(phone, email, exclude_id)
    
    # Check email duplicate using GSI
    if email:
        try:
            resp = table.query(
                IndexName='email-index',
                KeyConditionExpression='email = :em',
                ExpressionAttributeValues={':em': email.lower()},
                Limit=5,
            )
            for item in resp.get('Items', []):
                item_id = item.get('id') or item.get('contactId')
                if exclude_id and item_id == exclude_id:
                    continue
                if item.get('deletedAt') is not None:
                    continue
                return f"Email {email} already exists ({item.get('name', 'unnamed')})"
        except Exception as e:
            logger.warning(f"Email GSI query failed, falling back to scan: {e}")
            return _check_duplicate_scan(phone, email, exclude_id)
    
    return None


def _check_duplicate_scan(phone: Optional[str], email: Optional[str], exclude_id: Optional[str] = None) -> Optional[str]:
    """Fallback duplicate detection using scan (for when GSIs are not available)."""
    if not phone and not email:
        return None
    table = dynamodb.Table(CONTACTS_TABLE)
    filt = Attr('deletedAt').not_exists() | Attr('deletedAt').eq(None)
    scan_kwargs: Dict[str, Any] = {
        'FilterExpression': filt,
        'ProjectionExpression': '#id, #cid, #ph, #em, #nm',
        'ExpressionAttributeNames': {
            '#id': 'id', '#cid': 'contactId', '#ph': 'phone', '#em': 'email', '#nm': 'name'
        },
    }
    all_items: List[Dict] = []
    while True:
        resp = table.scan(**scan_kwargs)
        all_items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    for item in all_items:
        item_id = item.get('id') or item.get('contactId')
        if exclude_id and item_id == exclude_id:
            continue
        if phone and item.get('phone') == phone:
            return f"Phone {phone} already exists ({item.get('name', 'unnamed')})"
        if email and item.get('email', '').lower() == email.lower():
            return f"Email {email} already exists ({item.get('name', 'unnamed')})"
    return None


def _matches(item: Dict[str, Any], query: str) -> bool:
    name = str(item.get('name', '')).lower()
    phone = str(item.get('phone', '')).lower()
    email = str(item.get('email', '')).lower()
    bsuid = str(item.get('bsuid', '')).lower()
    username = str(item.get('username', '')).lower()
    contact_book_name = str(item.get('contactBookName', '')).lower()
    tags = [str(t).lower() for t in (item.get('tags') or [])]
    clean_q = query.lstrip('+')
    clean_p = phone.lstrip('+')
    return (query in name or query in phone or query in email or clean_q in clean_p
            or query in bsuid or query in username or query in contact_book_name
            or any(query in t for t in tags))


def _delete_s3(stored_key: str):
    # Root the persisted key before deleting; see lambda_utils/media_paths.
    stored_key = media_paths.canonical(stored_key)
    try:
        s3_client.head_object(Bucket=MEDIA_BUCKET, Key=stored_key)
        s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=stored_key)
        return
    except ClientError as e:
        if e.response['Error']['Code'] != '404':
            raise
    # Prefix search fallback
    prefix = stored_key.rsplit('.', 1)[0] if '.' in stored_key else stored_key
    resp = s3_client.list_objects_v2(Bucket=MEDIA_BUCKET, Prefix=prefix, MaxKeys=5)
    for obj in resp.get('Contents', []):
        s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=obj['Key'])


def _to_dynamo(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (Decimal(str(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in item.items() if v is not None}


def _from_dynamo(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (int(v) if isinstance(v, Decimal) and v % 1 == 0 else float(v) if isinstance(v, Decimal) else v)
            for k, v in item.items()}
