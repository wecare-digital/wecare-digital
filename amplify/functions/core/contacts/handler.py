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
# `normalize_phone` is deliberately NOT imported here. It strips non-digits BEFORE it looks for a
# country code, so a ten-digit foreign number arrives looking like an Indian mobile and gets +91
# prepended - measured, `+6591234567` became `+916591234567`. This surface uses
# `customer_identity.normalize_phone_preserving_country` instead; see `_e164_or_error`.
from lambda_utils.validation import sanitize_html, sanitize_dict
from lambda_utils import contact_key  # `id` is the physical key; `contactId` is its alias
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.privacy import mask_phone  # a phone reaches a log masked, or not at all
from lambda_utils.identity import customer as customer_identity
# The PUBLIC customer id. Deliberately not the row `id` - see the module docstring: that one is
# uuid5 of the Cognito sub when `auth/customer-profile` writes it, so publishing it on an invoice
# would publish a value derived from the Cognito subject.
from lambda_utils.identity import customer_uuid
# A contact tied to money is the provenance record for that money, so it may be ARCHIVED and
# never hard-deleted. The policy lives in the shared module - two indexed queries, fail-closed -
# so the word `captured` never has to be compared in this handler.
from lambda_utils.ecommerce import contact_address, contact_lock, contact_payment_links

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
INBOUND_TABLE = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)

# READ-ONLY, and only on the hard-delete path. These two tables answer "does this contact owe
# its existence to a payment", through `contact_payment_links`. The defaults match
# `config/lambda-env-manifest.json` exactly, so the recorded-but-not-yet-deployed variables are
# inert: whichever way round the deploy lands, the guard reads the same two tables.
INVOICES_TABLE = os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable')
ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'stack-wecare-digital-OrderTable')

# The function that ALREADY holds `cognito-idp:AdminCreateUser` on the customer pool
# `us-east-1_46ULYuukt` (`scripts/provision_secure_files_api.py`, Sid `CustomerPoolOnly`). The CRM
# asks IT to provision a login rather than gaining the grant itself - see
# `_provision_customer_login` for why that direction is the whole point.
CUSTOMER_LOGIN_FUNCTION = os.environ.get('CUSTOMER_LOGIN_FUNCTION', 'wecare-secure-files:live')

#: The copy a CRM operator sees when the dial code is missing. A refusal, not a default - see
#: `_e164_or_error`.
PHONE_COUNTRY_CODE_REQUIRED = 'Phone number must include a country code, e.g. +91'

# The error message for a number that carries a country code but still is not reachable. Kept as
# the pre-existing wording so no CRM UI string has to change.
PHONE_INVALID = 'Invalid phone number format'

_lambda_client = None  # built on first use only; see `_provision_customer_login`


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
# The RAW attribute is deliberately NOT in `ALLOWED_UPDATE_FIELDS`: there is no unvalidated path
# to it. But FEAT-003 lets the CRM WRITE it through the shared validator - `_create` and `_update`
# accept a top-level `address` dict, run `contact_address.normalize_for_storage` (structural,
# international), and write `ATTRIBUTE`/`UPDATED_ATTRIBUTE` on success or return 400 naming the
# field on `UnusableAddress`. Storage is structural only now, so a stored address is no longer
# guaranteed Wix-mappable; the place-of-supply / payability question moved to `payment_address`
# and runs at pay time (an unpayable stored address becomes the recoverable
# `409 DELIVERY_DETAILS_REQUIRED` at checkout, via the shared gate). Two writers now - checkout and
# the CRM - but both go through the one validator, so a hand-curated address and a checkout-captured
# one are still structurally identical and still distinguishable by `checkoutAddressUpdatedAt`.
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
    # Viewer is the read floor. Stated explicitly rather than left as None: `require_auth`
    # no longer defaults an ungrouped principal to Viewer, so a call with no
    # `required_role` has nothing to check. The DELETE arm re-gates at Operator.
    _auth = require_auth(event, required_role='Viewer')
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

        # POST .../{id}/lock and .../{id}/unlock — dedicated lock state, before generic create.
        # `locked` is NOT in ALLOWED_UPDATE_FIELDS, so these endpoints are the ONLY way to flip
        # it: a generic update can neither lock nor silently unlock a legally-retained contact.
        if method == 'POST' and resource.rstrip('/').endswith('/lock'):
            if not contact_id:
                return cors_response(400, {'error': 'contactId is required'}, origin)
            body = json.loads(event.get('body', '{}') or '{}')
            return _lock_contact(contact_id, body.get('reason', 'manual'), request_id, origin)
        if method == 'POST' and resource.rstrip('/').endswith('/unlock'):
            if not contact_id:
                return cors_response(400, {'error': 'contactId is required'}, origin)
            return _unlock_contact(contact_id, request_id, origin)

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
            # Re-gated at Operator before any delete work. A Viewer can read a contact
            # and must not be able to remove one.
            #
            # This is a gate on WHO may ask, and it is deliberately the only thing added
            # here. The gate on WHETHER the delete is allowed already exists and is
            # untouched: `_hard_delete_refusal` refuses CONTACT_HAS_PAYMENTS and
            # PAYMENT_LINKAGE_UNKNOWN via
            # `lambda_utils.ecommerce.contact_payment_links.has_payment_links`, and the
            # lock guard refuses CONTACT_LOCKED. An Operator does not outrank those.
            denied = require_auth(event, required_role='Operator')
            if denied is not None:
                return denied
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

    # E.164 that honours the country code the operator actually typed - see `_e164_or_error`.
    if phone:
        phone, phone_error = _e164_or_error(phone)
        if phone_error:
            return cors_response(400, {'error': phone_error}, origin)

    if not phone and not email:
        return cors_response(400, {'error': 'At least one of phone or email is required'}, origin)
    # Belt only, and said so rather than left to be trusted: `_e164_or_error` already guarantees
    # `+` followed by 8-15 ASCII digits, which satisfies this regex by construction. It is kept
    # because it is the shape check this surface has always had, not because it is what makes the
    # stored number correct.
    if phone and not _validate_phone(phone):
        return cors_response(400, {'error': PHONE_INVALID}, origin)
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
        # THE PUBLIC CUSTOMER ID, minted inline and never read back first. This IS the resolve
        # half of resolve-before-generate and it needs no extra read: `_check_duplicate` ran
        # above and returned `None`, so no live row exists on this phone or this email - there is
        # nothing to resolve TO. The update path cannot make that claim and so uses
        # `if_not_exists` instead.
        #
        # Taken from the body is exactly what it is NOT. The client never supplies this: it is
        # absent from `ALLOWED_UPDATE_FIELDS` and never read out of `body` here, so a request
        # carrying `customerUuid` is ignored rather than honoured. A customer-chosen public id
        # would let one customer claim another's identifier on an invoice.
        customer_uuid.ATTRIBUTE: customer_uuid.new_customer_uuid(),
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

    # FEAT-003: a validated structured address may be written through the shared validator. The
    # raw attribute is NOT in ALLOWED_UPDATE_FIELDS - this top-level `address` dict is the only
    # path, and it always goes through normalize_for_storage (structural, international). On a bad
    # address, refuse the whole create with 400 naming the field, writing nothing.
    address_in = body.get('address')
    if address_in is not None:
        try:
            stored_address = contact_address.normalize_for_storage(address_in)
        except contact_address.UnusableAddress as exc:
            return cors_response(400, {'error': 'Invalid address', 'code': exc.code,
                                       'field': exc.field}, origin)
        contact[contact_address.ATTRIBUTE] = stored_address
        contact[contact_address.UPDATED_ATTRIBUTE] = now

    table = dynamodb.Table(CONTACTS_TABLE)
    table.put_item(Item=_to_dynamo(contact))

    # AFTER the row exists, and never before it: the login is an attachment to a contact that is
    # already stored, so a dispatch that fires and then a failed write cannot leave a Cognito user
    # with no row behind it. Off by default, and a no-op when it is off.
    if phone:
        _provision_customer_login(phone, request_id)

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
        # The SAME normalisation as `_create`, deliberately: an update that re-wrote the number
        # in the old `'+' + digits` form would undo the link for a row that was created
        # correctly, which is the defect arriving through the back door.
        updates['phone'], phone_error = _e164_or_error(updates['phone'])
        if phone_error:
            return cors_response(400, {'error': phone_error}, origin)
        if not _validate_phone(updates['phone']):
            return cors_response(400, {'error': PHONE_INVALID}, origin)
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

    # FEAT-003: a validated structured address, written through the shared validator only. The
    # raw attribute is not in ALLOWED_UPDATE_FIELDS, so `updates` never carries it from the client;
    # the top-level `address` dict is the one path and always goes through normalize_for_storage.
    address_in = body.get('address')
    if address_in is not None:
        try:
            stored_address = contact_address.normalize_for_storage(address_in)
        except contact_address.UnusableAddress as exc:
            return cors_response(400, {'error': 'Invalid address', 'code': exc.code,
                                       'field': exc.field}, origin)
        updates[contact_address.ATTRIBUTE] = stored_address
        updates[contact_address.UPDATED_ATTRIBUTE] = int(time.time())

    updates['updatedAt'] = int(time.time())

    set_parts, names, values = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        set_parts.append(f'#n{i} = :v{i}')
        names[f'#n{i}'] = k
        values[f':v{i}'] = Decimal(str(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    # THE PUBLIC CUSTOMER ID, backfilled onto a hand-updated contact. This is the requirement's
    # "a manually updated contact becomes a real customer with an id we can print".
    #
    # Added AFTER the loop and through its own placeholder, deliberately NOT via
    # `ALLOWED_UPDATE_FIELDS`: that set is the list of fields the CLIENT may set, and this one it
    # may not. Routing the mint through `updates` would put a customer-supplied `customerUuid`
    # straight onto the row.
    #
    # `if_not_exists` rather than a read-then-write. A fresh uuid4 is minted locally on every
    # update and DISCARDED by DynamoDB whenever the row already has one - that costs no network
    # call, and it makes "an existing customer keeps its id" an atomic database guarantee instead
    # of a race window between the read and the write. Two concurrent updates therefore cannot
    # issue two ids for one customer.
    set_parts.append(
        f'{customer_uuid.ATTRIBUTE} = if_not_exists({customer_uuid.ATTRIBUTE}, :vcustuuid)')
    values[':vcustuuid'] = customer_uuid.new_customer_uuid()

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

#: The two refusals, distinct on the wire so the UI can say WHICH happened rather than offering
#: one vague "could not delete". Both carry `archiveInstead: True`, because the soft delete is
#: always still available and is what the operator actually wants.
HARD_DELETE_REFUSED_PAYMENTS = 'CONTACT_HAS_PAYMENTS'
HARD_DELETE_REFUSED_UNKNOWN = 'PAYMENT_LINKAGE_UNKNOWN'
#: A LOCKED contact is legally retained: it refuses BOTH hard and soft delete. Unlike the
#: payment guard (which blocks hard delete but still offers archive), a lock blocks archive too,
#: so `archiveInstead` is False here — the record is kept, not archivable.
DELETE_REFUSED_LOCKED = 'CONTACT_LOCKED'


def _delete(contact_id: str, hard: bool, request_id: str, origin: str = '') -> Dict[str, Any]:
    # A lock blocks EVERY delete, hard or soft, before anything else.
    lock_refusal = _locked_delete_refusal(contact_id, hard, request_id, origin)
    if lock_refusal is not None:
        return lock_refusal
    # Payment/order provenance must survive archiving as well as permanent deletion.
    # Otherwise re-adding the phone creates a new identity and strands the old links.
    refusal = _hard_delete_refusal(contact_id, request_id, origin)
    if refusal is not None:
        payload = json.loads(refusal['body'])
        payload['archiveInstead'] = False
        payload['reason'] = 'Payment or order history must be retained. ' + payload.get('reason', '')
        refusal['body'] = json.dumps(payload)
        return refusal
    if hard:
        return _hard_delete(contact_id, request_id, origin)
    return _soft_delete(contact_id, request_id, origin)


def _lock_contact(contact_id: str, reason: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    """Lock a contact for legal retention. Operator-driven; auto-lock-on-pay uses contact_lock.

    Idempotent: locking an already-locked contact succeeds and refreshes the reason/timestamp.
    """
    reason = (str(reason or 'manual').strip().lower() or 'manual')[:40]
    table = dynamodb.Table(CONTACTS_TABLE)
    try:
        resp = table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET #locked = :t, #reason = :r, #at = :ts, #u = :ts',
            ExpressionAttributeNames={
                '#locked': contact_lock.LOCKED_ATTRIBUTE,
                '#reason': contact_lock.LOCKED_REASON_ATTRIBUTE,
                '#at': contact_lock.LOCKED_AT_ATTRIBUTE,
                '#u': 'updatedAt',
            },
            ExpressionAttributeValues={':t': True, ':r': reason, ':ts': int(time.time())},
            ConditionExpression='attribute_exists(id)',
            ReturnValues='ALL_NEW',
        )
    except Exception as e:  # noqa: BLE001
        if 'ConditionalCheckFailedException' in str(e):
            return cors_response(404, {'error': 'Contact not found'}, origin)
        raise
    log_event(logger, 'contact_locked', contactId=contact_id, reason=reason, requestId=request_id)
    return cors_response(200, _from_dynamo(resp.get('Attributes', {})), origin)


def _unlock_contact(contact_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    """Unlock a contact. Staff may unlock even a 'paid' auto-lock, but the paid-contact
    hard-delete guard still prevents destroying a record with payments, so legal retention
    survives an unlock. The unlock is logged with the prior reason for the audit trail.
    """
    table = dynamodb.Table(CONTACTS_TABLE)
    try:
        resp = table.update_item(
            Key={'id': contact_id},
            UpdateExpression='SET #locked = :f, #u = :ts REMOVE #reason, #at',
            ExpressionAttributeNames={
                '#locked': contact_lock.LOCKED_ATTRIBUTE,
                '#reason': contact_lock.LOCKED_REASON_ATTRIBUTE,
                '#at': contact_lock.LOCKED_AT_ATTRIBUTE,
                '#u': 'updatedAt',
            },
            ExpressionAttributeValues={':f': False, ':ts': int(time.time())},
            ConditionExpression='attribute_exists(id)',
            ReturnValues='ALL_OLD',
        )
    except Exception as e:  # noqa: BLE001
        if 'ConditionalCheckFailedException' in str(e):
            return cors_response(404, {'error': 'Contact not found'}, origin)
        raise
    prior = resp.get('Attributes', {})
    log_event(logger, 'contact_unlocked', contactId=contact_id,
              priorReason=str(prior.get(contact_lock.LOCKED_REASON_ATTRIBUTE) or ''),
              requestId=request_id)
    return cors_response(200, {'id': contact_id, 'locked': False}, origin)


def _locked_delete_refusal(contact_id: str, hard: bool, request_id: str, origin: str = '') -> Optional[Dict[str, Any]]:
    """`None` when the contact is not locked (delete may proceed); otherwise the 409 to return.

    A locked contact is retained for legal records and refuses both hard and soft delete.

    On an UNREADABLE row the behaviour differs by delete kind, deliberately, so this guard does
    not change an existing tested contract: for a HARD delete, return None and let
    `_hard_delete_refusal` (which runs next and already fail-closes on an unreadable row with
    `PAYMENT_LINKAGE_UNKNOWN`) own that refusal. For a SOFT delete there is no later guard, so an
    unreadable row fail-closes HERE with `CONTACT_LOCKED`. A missing row returns None so the
    delete paths own their own 404.
    """
    table = dynamodb.Table(CONTACTS_TABLE)
    try:
        row = table.get_item(Key={'id': contact_id}).get('Item')
    except Exception as exc:  # noqa: BLE001 - cannot read, so cannot prove unlocked
        if hard:
            return None  # the payment guard below owns the unreadable-row refusal for hard delete
        return cors_response(409, {
            'error': DELETE_REFUSED_LOCKED, 'archiveInstead': False,
            'reason': f'the contact row could not be read to check its lock: {type(exc).__name__}',
        }, origin)
    if not row:
        return None
    if contact_lock.is_locked(row):
        return cors_response(409, {
            'error': DELETE_REFUSED_LOCKED, 'archiveInstead': False,
            'lockedReason': str(row.get(contact_lock.LOCKED_REASON_ATTRIBUTE) or ''),
            'reason': 'this contact is locked for legal records and cannot be deleted or archived',
        }, origin)
    return None


def _hard_delete_refusal(contact_id: str, request_id: str, origin: str = '') -> Optional[Dict[str, Any]]:
    """`None` when the hard delete may proceed; otherwise the 409 response to return.

    Runs BEFORE `_hard_delete`, which is the only ordering that helps: `_hard_delete` deletes
    every message and every S3 object first and the contact row last, so a check made partway
    through would already have destroyed the history the guard exists to protect.

    Fail-closed in three places, not one. An unreadable contact row, an unreadable index, and a
    row with no usable key all refuse, because none of them is evidence of "no payments".
    """
    table = dynamodb.Table(CONTACTS_TABLE)
    try:
        row = table.get_item(Key={'id': contact_id}).get('Item') or {}
    except Exception as exc:  # noqa: BLE001 - cannot read the row, so cannot read its linkage
        log_event(logger, 'contact_hard_delete_linkage_unknown', contactId=contact_id,
                  reason=f'contact row unreadable: {type(exc).__name__}', requestId=request_id)
        return cors_response(409, {
            'error': HARD_DELETE_REFUSED_UNKNOWN, 'archiveInstead': True,
            'reason': f'the contact row could not be read: {type(exc).__name__}',
        }, origin)

    if not row:
        # Not a refusal. `_hard_delete` owns the 404 and already answers it, and duplicating
        # that answer here would be two places deciding what "not found" looks like.
        return None

    try:
        linkage = contact_payment_links.has_payment_links(
            invoices_table=dynamodb.Table(INVOICES_TABLE),
            orders_table=dynamodb.Table(ORDERS_TABLE),
            contact_row=row,
        )
    except contact_payment_links.PaymentLinkageUnknown as exc:
        # `str(exc)` is safe HERE and only here: the module builds that message itself from a
        # fixed phrase plus `type(exc).__name__`, so it carries no provider text.
        log_event(logger, 'contact_hard_delete_linkage_unknown', contactId=contact_id,
                  reason=str(exc), requestId=request_id)
        return cors_response(409, {
            'error': HARD_DELETE_REFUSED_UNKNOWN, 'archiveInstead': True, 'reason': str(exc),
        }, origin)

    # `contactId` and the signal names are the whole log line. The phone is deliberately absent
    # rather than masked: nothing here needs it, and the contact id is the correlation key.
    if linkage.blocked:
        log_event(logger, 'contact_hard_delete_refused', contactId=contact_id,
                  signals=list(linkage.signals), reason=linkage.reason, requestId=request_id)
        return cors_response(409, {
            'error': HARD_DELETE_REFUSED_PAYMENTS, 'archiveInstead': True,
            'reason': linkage.reason, 'signals': list(linkage.signals),
        }, origin)

    log_event(logger, 'contact_hard_delete_allowed', contactId=contact_id,
              signals=list(linkage.signals), requestId=request_id)
    return None


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

def _e164_or_error(raw: str) -> tuple:
    """`(e164, None)` or `(None, message)`. The CRM's single phone-entry contract.

    THIS IS THE FIX THAT MAKES A CRM ROW VISIBLE TO THE WEBSITE AND TO WHATSAPP. One contact row
    is reached from three directions and the only key all three share is the E.164 phone:
    `phone-index` on `+91...` for a signed-in website session (`auth/customer-profile`,
    `ecommerce/checkout`, `ecommerce/customer-orders`), the same index for an inbound WhatsApp
    `wa_id`, and the Cognito `Username`. Measured before this changed: an operator typing
    `9876543210` produced the stored value `+9876543210`, so the website looked up
    `+919876543210` and WhatsApp looked up `919876543210` and NEITHER found the row. The CRM
    customer was pushed through the entire first-time flow despite already existing.

    A MISSING COUNTRY CODE IS REFUSED, NOT GUESSED. `normalize_phone_preserving_country` raises
    `MissingCountryCode` for input carrying neither `+` nor `00`, and that rejection is carried
    straight through to a 400 here rather than softened. Refusing is correct rather than
    inconvenient on this surface: the CRM form supplies a dial code explicitly, so no real UI
    state produces a bare national number - only a direct API caller does - and the alternative
    is the defect wearing a wrapper. Guessing `+91` for a ten-digit foreign number sends the OTP
    to an unrelated Indian subscriber AND reserves the wrong identity permanently, because
    uniqueness is enforced on the normalised value.

    The duplicate check downstream therefore compares normalised values on both sides, which is
    the second half of the same property: two spellings of one number must collapse to one string
    BEFORE `_check_duplicate` queries `phone-index`, or the same person gets two rows.
    """
    try:
        return customer_identity.normalize_phone_preserving_country(raw), None
    except customer_identity.MissingCountryCode:
        return None, PHONE_COUNTRY_CODE_REQUIRED
    except customer_identity.InvalidPhoneNumber:
        return None, PHONE_INVALID


def _customer_login_enabled() -> bool:
    """`CRM_PROVISION_CUSTOMER_LOGIN`, read at REQUEST time and defaulting to OFF.

    Read per request rather than at import so the flag can be flipped by an environment update
    without waiting for every warm sandbox to recycle. Default off means a CRM create behaves
    exactly as it does today until an owner deliberately turns it on.
    """
    return os.environ.get('CRM_PROVISION_CUSTOMER_LOGIN', 'false').strip().lower() == 'true'


def _provision_customer_login(phone: str, request_id: str) -> None:
    """Ask the function that already holds the grant to create the customer's Cognito login.

    WHY AN ASYNC INVOKE RATHER THAN A CALL FROM HERE. A CRM contact has no Cognito user, so the
    WhatsApp OTP trigger answers `registered=false` and sends nothing - the customer the CRM just
    created cannot sign in. Fixing that needs `cognito-idp:AdminCreateUser` on the customer pool
    `us-east-1_46ULYuukt`, and `core/secure-files` already holds exactly that, scoped to the
    customer pool, for `_ensure_customer_user`. Reaching it by invoke keeps the grant in the one
    role that was provisioned for it instead of widening this role, which is shared.

    USER-LEVEL ADMIN APIS ONLY. Nothing in this path calls `UpdateUserPool`. That API is a FULL
    REPLACE: on 2026-09-28 a partial call returned 200, silently cleared three auth triggers and
    flipped `AllowAdminCreateUserOnly` to false on this very pool - self-signup opened on a
    public, internet-facing pool, with no error and no warning. If a pool-level setting ever has
    to change it goes through `scripts/cognito_pool_safe_update.py --apply` and nothing else.

    THE PAYLOAD CARRIES THE NORMALISED E.164 AND NOTHING ELSE. Not the name, not the email, not
    the contact id. The receiving function needs the phone to key the user and no more, and a
    smaller payload is a smaller thing to get wrong; the phone reaches the log masked.

    Fire-and-forget on purpose. A login is a convenience attached to a contact row that is
    already stored, so a dispatch failure must not fail the create - it is recoverable by
    re-saving the contact once the flag is on.
    """
    if not _customer_login_enabled():
        return
    global _lambda_client
    try:
        if _lambda_client is None:
            # Built here rather than at import: with the flag off, no Lambda client is ever
            # constructed and this handler's cold start is unchanged.
            _lambda_client = boto3.client(
                'lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        _lambda_client.invoke(
            FunctionName=CUSTOMER_LOGIN_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({
                'internalAction': 'provisionCustomerLogin',
                'phone': phone,
            }).encode('utf-8'),
        )
        log_event(logger, 'crm_customer_login_dispatched',
                  phone=mask_phone(phone), requestId=request_id)
    except Exception as exc:  # noqa: BLE001 - a missing login, never a lost contact
        # Type only: a ClientError message can echo the request content, phone included.
        log_event(logger, 'crm_customer_login_dispatch_failed', level='warning',
                  error=type(exc).__name__, requestId=request_id)


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
