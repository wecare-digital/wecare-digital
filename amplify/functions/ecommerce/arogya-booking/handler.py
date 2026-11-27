"""WhatsApp-verified customer appointment draft API. No provider writes or charges."""
from __future__ import annotations

import base64
import json
import os
import time

import boto3

from lambda_utils.customer_auth import require_customer
from lambda_utils.arogya import booking_store as store
from lambda_utils.arogya import provider_runtime as catalog
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
    try:
        if action == 'catalog':
            return _response(200, catalog.read_catalog(body, now=now))
        if action == 'quote':
            return _response(200, {'pricing': price_components(55000), 'currency': 'INR',
                'providerFeesIncluded': False, 'appointmentConfirmed': False})
        if action == 'save':
            draft = store.save_draft(_table(), identity.subject, body.get('draftId'),
                body.get('plan'), revision=body.get('revision'), now=now)
            return _response(200, {'draft': draft, 'appointmentConfirmed': False})
        if action == 'get':
            draft = store.get_draft(_table(), identity.subject, body.get('draftId'), now=now)
            return _response(200, {'draft': draft}) if draft else _response(404, {'error': 'Draft not found.'})
        if action == 'list':
            return _response(200, {'drafts': store.list_drafts(_table(), identity.subject, now=now)})
        if action == 'delete':
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
