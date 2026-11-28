"""WhatsApp-verified customer appointment draft API. No provider writes or charges."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import boto3

from lambda_utils.customer_auth import require_customer
from lambda_utils.arogya import booking_store as store
from lambda_utils.arogya import provider_runtime as catalog
from lambda_utils.arogya import assistance_requests as requests
from lambda_utils.ecommerce.unified_pricing import price_components

_db = None


def _table():
    global _db
    if _db is None:
        _db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return _db.Table(os.environ['AROGYA_BOOKINGS_TABLE'])


def _response(code, value):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json',
        'Cache-Control': 'no-store, private', 'Pragma': 'no-cache',
        'X-Content-Type-Options': 'nosniff'}, 'body': json.dumps(value, default=str)}


def handler(event, context):
    # Operator reads use native IAM Invoke only, never a public HTTP body or
    # customer token. Queue pointers contain no patient details.
    if 'requestContext' not in event and event.get('internalAction') in ('listAssistanceRequests', 'getAssistanceRequest'):
        try:
            now = int(time.time())
            if event['internalAction'] == 'listAssistanceRequests' and not set(event) - {'internalAction', 'after'}:
                return _response(200, requests.operator_queue(_table(), now=now, after=event.get('after')))
            if event['internalAction'] == 'getAssistanceRequest' and set(event) == {'internalAction', 'customerId', 'requestId'}:
                item = requests.operator_request(_table(), event['customerId'], event['requestId'], now=now)
                return _response(200, {'request': item}) if item else _response(404, {'error': 'Request not found.'})
            return _response(400, {'error': 'Invalid request lookup.'})
        except store.InvalidPlan as error:
            return _response(400, {'error': str(error)})
        except Exception:
            return _response(503, {'error': 'Request storage is temporarily unavailable.'})
    # Native SDK Invoke is IAM-authorized. Function URLs always supply
    # requestContext, including for unsigned requests. Keep this operator-only
    # health check outside HTTP and limit it to the existing public catalogue
    # reader; it cannot access customer drafts, patient records or bookings.
    if 'requestContext' not in event and event.get('internalAction') == 'checkProviderCatalogue':
        if (set(event) != {'internalAction', 'catalogue'} or not isinstance(event['catalogue'], dict)
                or event['catalogue'].get('action') != 'catalog'):
            return _response(400, {'error': 'Invalid provider check.'})
        try:
            return _response(200, catalog.read_catalog(event['catalogue'], now=int(time.time())))
        except catalog.InvalidCatalogueRequest as error:
            return _response(400, {'error': str(error)})
        except catalog.CatalogueRenewing as pending:
            return _response(202, {'status': 'renewing', 'retryAfter': pending.retry_after})
        except Exception:
            return _response(503, {'error': 'Live Apollo availability is temporarily unavailable.'})
    method = event.get('requestContext', {}).get('http', {}).get('method', '')
    if method != 'POST':
        return _response(405, {'error': 'Use POST.'})
    identity, denied = require_customer(event)
    if denied:
        return _response(401, {'error': 'Sign in using your WhatsApp verification code.'})
    if not identity.phone_verified:
        return _response(403, {'error': 'Verify your WhatsApp number before saving an appointment.'})
    raw = event.get('body') or ''
    try:
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode('utf-8')
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 12000:
            raise ValueError
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        return _response(400, {'error': 'Invalid appointment request.'})
    now = int(time.time())
    action = body.get('action')
    account_key = hashlib.sha256(('arogya-account:' + identity.subject).encode()).hexdigest()
    try:
        if action == 'catalog':
            return _response(200, catalog.read_catalog(body, now=now))
        if action == 'access' and set(body) == {'action'}:
            return _response(200, {'phoneVerified': True, 'accountKey': account_key, 'appointmentConfirmed': False})
        if action in ('submitRequest', 'myRequests'):
            claimed = body.get('accountKey')
            if (not isinstance(claimed, str) or not claimed.isascii()
                    or not hmac.compare_digest(claimed, account_key)):
                return _response(409, {'code': 'ACCOUNT_CHANGED', 'error': 'Your account changed. Reopen the request form.'})
            allowed = {'action', 'accountKey', 'requestId', 'request'} if action == 'submitRequest' else {'action', 'accountKey'}
            if action == 'myRequests' and 'after' in body:
                allowed.add('after')
            if set(body) != allowed:
                return _response(400, {'error': 'Invalid assistance request.'})
            if action == 'myRequests':
                return _response(200, requests.customer_requests(_table(), identity.subject, now=now, after=body.get('after')))
            return _response(200, {'request': requests.submit(_table(), identity.subject,
                body['requestId'], body['request'], now=now), 'appointmentConfirmed': False})
        if action == 'quote' and set(body) == {'action'}:
            # Formula preview only; live ProductsTable, provider and paid-order
            # binding are not yet activated. Never present this as payable quote.
            return _response(200, {'pricing': price_components(55000), 'currency': 'INR',
                'estimateOnly': True, 'checkoutAvailable': False,
                'providerFeesIncluded': False, 'appointmentConfirmed': False})
        if action in ('save', 'get', 'list', 'delete'):
            # Prevent an old tab's patient details from being saved under a
            # newly signed-in customer. Authentication remains the sole owner
            # authority; this binding can only restrict, never choose the owner.
            claimed = body.get('accountKey')
            if (not isinstance(claimed, str) or len(claimed) != 64 or not claimed.isascii()
                    or not hmac.compare_digest(claimed, account_key)):
                return _response(409, {'code': 'ACCOUNT_CHANGED',
                    'error': 'Your appointment account changed. Reopen the verified form.'})
            allowed = {'action', 'accountKey'}
            required = set(allowed)
            if action == 'save':
                allowed.update(('draftId', 'revision', 'plan'))
                required = set(allowed)
            elif action in ('get', 'delete'):
                allowed.add('draftId')
                required = set(allowed)
            else:
                allowed.add('after')
            if set(body) - allowed or required - set(body):
                return _response(400, {'error': 'Invalid appointment draft request.'})
            if action == 'save':
                draft = store.save_draft(_table(), identity.subject, body.get('draftId'),
                    body.get('plan'), revision=body.get('revision'), now=now)
                return _response(200, {'draft': draft, 'appointmentConfirmed': False})
            if action == 'get':
                draft = store.get_draft(_table(), identity.subject, body.get('draftId'), now=now)
                return _response(200, {'draft': draft}) if draft else _response(404, {'error': 'Draft not found.'})
            if action == 'list':
                return _response(200, store.list_draft_page(_table(), identity.subject,
                    now=now, after=body.get('after')))
            store.delete_draft(_table(), identity.subject, body.get('draftId'))
            return _response(200, {'deleted': True})
        return _response(400, {'error': 'Unknown appointment action.'})
    except catalog.InvalidCatalogueRequest as error:
        return _response(400, {'error': str(error)})
    except catalog.CatalogueRenewing as pending:
        return _response(202, {'status': 'renewing', 'retryAfter': pending.retry_after})
    except catalog.CatalogueUnavailable:
        return _response(503, {'error': 'Live Apollo availability is temporarily unavailable.'})
    except store.InvalidPlan as error:
        return _response(400, {'error': str(error)})
    except store.DraftConflict as error:
        return _response(409, {'error': str(error)})
    except Exception:
        # Never log the event, token, patient details or provider response.
        return _response(503, {'error': 'Appointment storage is temporarily unavailable. Try again later.'})
