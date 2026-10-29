"""F006 Track Shipping completion parser and durable saver.

The published F006 asset was cloned from Submit Request and therefore still returns
flow_key=wd_f004_submit_request.  Meta does not include a Flow ID in nfm_reply, so this
module identifies F006 only when that clone marker is paired with the server-issued
shipments-* flow_token.  The Submit Request parser carries the reciprocal guard.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from lambda_utils import (
    canonical_flows,
    contact_store,
    customer_auth,
    flow_completion,
    flow_sessions,
    shared_tables,
)
from lambda_utils.ecommerce import order_keys, service_request_store
from lambda_utils.privacy import mask_contact_id

logger = logging.getLogger(__name__)

CAPABILITY = 'shipments'
FLOW_KEY = 'wd_f006_track_shipping'
PUBLISHED_CLONE_FLOW_KEY = 'wd_f004_submit_request'
TOKEN_PREFIX = 'shipments-'
FLOW_CODE = 'shipments'
FLOW_NAME = 'WD-F006-Track-Shipping'
FLOW_VERSION = '7.3'
FLOW_ID = canonical_flows.canonical_flow_id(CAPABILITY) or '1804165164183485'
REJECTED = 'This Track Shipping form session is no longer valid.'


def _clean_text(data: Dict[str, Any], key: str, *, required: bool = False,
                limit: int = 2000) -> str:
    value = str(data.get(key) or '').strip()
    if required and not value:
        raise ValueError(f'{key} is required')
    return value[:limit]


def _target_parts(raw: str) -> Tuple[str, str]:
    target = str(raw or '').strip()
    if ':' in target:
        kind, ref = target.split(':', 1)
        kind = kind.strip().lower()
        ref = ref.strip()
        if kind in ('order', 'request') and ref:
            return kind, ref
    if target.startswith('WD-ORD-'):
        return 'order', target
    if target.startswith(('WD-SR-', 'WD-REQ-')):
        return 'request', target
    return 'unknown', target


def tracking_payload(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return only an F006 terminal nfm_reply; never consume another Flow's clone payload."""
    if not isinstance(message, dict) or message.get('type') != 'interactive':
        return None
    interactive = message.get('interactive') or {}
    if interactive.get('type') != 'nfm_reply':
        return None
    nfm = interactive.get('nfm_reply') or {}
    raw = nfm.get('response_json')
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get('flow_key') or '').strip() != PUBLISHED_CLONE_FLOW_KEY:
        return None
    token = str(data.get('flow_token') or '').strip()
    if not token.startswith(TOKEN_PREFIX):
        return None
    return data


def _session(db: Any, data: Dict[str, Any], *, phone: str):
    token = _clean_text(data, 'flow_token', required=True, limit=512)
    session = flow_sessions.verify_session(
        db.Table(shared_tables.flow_drafts_table_name()),
        capability=CAPABILITY,
        token=token,
        rejected_message=REJECTED,
    )
    if contact_store.digits(phone) != session.phone:
        raise ValueError(REJECTED)
    return session


def _contact_identity(db: Any, *, contact_id: str, phone: str):
    try:
        row = db.Table(shared_tables.contacts_table_name()).get_item(
            Key={'id': contact_id}, ConsistentRead=True
        ).get('Item') or {}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('Track Shipping customer identity could not be verified') from exc
    owner = str(row.get('checkoutCustomerId') or '').strip()
    canonical = contact_store.canonical_phone(phone)
    if not owner or not customer_auth.is_cognito_subject(owner) or not canonical:
        return None
    return customer_auth.CustomerIdentity(
        customer_id=owner,
        subject=owner,
        phone=canonical,
        phone_verified=True,
    )


def _verified_target(db: Any, raw: str, *, contact_id: str, phone: str) -> Dict[str, Any]:
    """Re-read the chosen target and prove it belongs to the sender before linking it."""
    kind, ref = _target_parts(raw)
    if kind not in ('order', 'request') or not ref or ref == 'unavailable':
        raise ValueError('Choose a valid order or request.')

    if kind == 'order':
        try:
            order_id = ref
            if order_keys.is_public_order_number(ref):
                reservation = db.Table(shared_tables.commerce_keys_table_name()).get_item(
                    Key={'orderId': order_keys.ORDER_NUMBER_PREFIX + ref},
                    ConsistentRead=True,
                ).get('Item') or {}
                order_id = str(reservation.get('orderIdRef') or '')
            row = (
                db.Table(shared_tables.orders_table_name()).get_item(
                    Key={'orderId': order_id}, ConsistentRead=True
                ).get('Item') or {}
                if order_id else {}
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError('Track Shipping order ownership could not be verified') from exc

        row_contact = str(row.get('contactId') or '')
        same_contact = bool(row_contact and contact_id and row_contact == contact_id)
        wanted = contact_store.digits(phone)
        same_phone = bool(wanted and any(
            contact_store.digits(row.get(field)) == wanted
            for field in ('phone', 'customerPhone', 'senderPhone')
        ))
        if not row or not (same_contact or same_phone):
            raise ValueError('The selected order is not available for this account.')
        return {
            'targetType': 'order',
            'targetReference': ref,
            'orderId': order_id,
            'orderNumber': str(row.get('orderNumber') or ref),
        }

    identity = _contact_identity(db, contact_id=contact_id, phone=phone)
    if identity is None:
        raise ValueError('The selected request cannot be verified for this account.')
    try:
        rows, _cursor = service_request_store.list_for_customer(
            db.Table(service_request_store.DEFAULT_TABLE_NAME), identity, limit=20
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('Track Shipping request ownership could not be verified') from exc
    owned = next((row for row in rows if str(row.get('requestId') or '') == ref), None)
    if not owned:
        raise ValueError('The selected request is not available for this account.')
    return {
        'targetType': 'request',
        'targetReference': ref,
        'targetRequestId': ref,
    }


def response_answers(data: Dict[str, Any], result: flow_completion.CompletionResult) -> list:
    """Readable Inbox fields for F006 without changing the customer Flow asset."""
    _kind, ref = _target_parts(_clean_text(data, 'reference_number', limit=240))
    note = _clean_text(data, 'note', limit=2000)
    rows = []
    if ref:
        rows.append({'question': 'Linked to', 'answer': ref})
    if note:
        rows.append({'question': 'Note', 'answer': note})
    if result and result.reference:
        rows.append({'question': 'Tracking request ID', 'answer': result.reference})
    return rows


def save_tracking(data: Dict[str, Any], *, contact_id: str, phone: str, sender_name: str,
                  message_id: str, dynamodb: Any, request_id: str = ''):
    """Persist exactly one F006 FlowSubmission after session and target ownership checks."""
    if not contact_id or not phone or not message_id:
        raise ValueError('Track Shipping requires a sender and Meta message id')

    session = _session(dynamodb, data, phone=phone)
    target = _clean_text(data, 'reference_number', required=True, limit=240)
    note = _clean_text(data, 'note', required=True, limit=2000)
    schema_version = _clean_text(data, 'schema_version', limit=20) or '1'
    target_extra = _verified_target(
        dynamodb, target, contact_id=contact_id, phone=phone
    )

    form = {
        'selected_target': target,
        'note': note,
        'subject': 'Track Shipping',
        'description': note,
    }
    if target_extra.get('orderId'):
        form['order_id'] = target_extra['orderId']

    result = flow_completion.claim_completion(
        # The Meta inbound message id is stable across webhook retries and server-authenticated.
        flow_token=message_id,
        screen='CONFIRMATION',
        flow_code=FLOW_CODE,
        flow_type='form_submit',
        phone=contact_store.digits(phone),
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        requires_payment=False,
        payment_amount=0,
        status='open',
        extra={
            'flowId': FLOW_ID,
            'flowName': FLOW_NAME,
            'flowVersion': FLOW_VERSION,
            'schemaVersion': schema_version,
            'backendFlowKey': FLOW_KEY,
            'subject': 'Track Shipping',
            'description': note,
            'source': 'whatsapp',
            'customerPhone': contact_store.digits(phone),
            'customerName': sender_name,
            'whatsappDisplayName': sender_name,
            'whatsappMessageId': message_id,
            **target_extra,
        },
        ttl_seconds=0,
        request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
    )
    if result.status == 'error':
        raise RuntimeError('Track Shipping completion could not be saved')

    flow_sessions.mark_consumed(
        dynamodb.Table(shared_tables.flow_drafts_table_name()),
        token=str(data.get('flow_token') or ''),
    )

    # Repairable contact projection only; Track Shipping does not create a second business record.
    try:
        import time
        now = int(time.time())
        dynamodb.Table(shared_tables.contacts_table_name()).update_item(
            Key={'id': contact_id},
            UpdateExpression='SET lastFlowSubmissionId=:sid, updatedAt=:now',
            ExpressionAttributeValues={':sid': result.submission_id, ':now': now},
            ConditionExpression='attribute_exists(id)',
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            '{"event":"f006_contact_projection_failed","contactId":"%s","error":"%s"}',
            mask_contact_id(contact_id), type(exc).__name__,
        )

    return result
