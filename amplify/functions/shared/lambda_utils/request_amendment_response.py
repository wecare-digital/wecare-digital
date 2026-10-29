"""F005 Request Amendment completion -> one linked amendment FlowSubmission + Inbox projection.

The F005 draft is an endpointless-style Flow. Its terminal complete payload carries the
customer-entered existing request number and amendment text. The parent request remains the
system of record: this module never overwrites its subject/description. Instead it creates one
immutable child amendment row (flowCode WD_AMEND) and links it through parentSubmissionId after
verifying that the signed WhatsApp sender owns the parent request.

A stale/incorrect/foreign request number is never attached to another customer's record. It is
still retained as an unverified customer reference so staff can reconcile it safely.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from lambda_utils import contact_store, flow_completion, shared_tables
from lambda_utils.privacy import mask_contact_id

logger = logging.getLogger(__name__)

FLOW_KEY = 'wd_f005_request_amendment'
DESIGN_SERVICE = 'request-amendment'
FLOW_ID = '1421471529574569'
FLOW_CODE = 'WD_AMEND'
FLOW_NAME = 'WD-F005-Request-Amendment'
FLOW_VERSION = '7.3'
SUBMISSION_PREFIX = 'WD-AMD'


def amendment_payload(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recognise only F005-style nfm_reply completions."""
    if not isinstance(message, dict) or message.get('type') != 'interactive':
        return None
    interactive = message.get('interactive') or {}
    if interactive.get('type') != 'nfm_reply':
        return None
    raw = (interactive.get('nfm_reply') or {}).get('response_json', '{}')
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    marker = str(data.get('flow_key') or '').strip()
    service = str(data.get('design_service') or '').strip()
    if marker != FLOW_KEY and service != DESIGN_SERVICE:
        return None
    # Require the two business fields as an extra guard against a future Flow reusing a marker.
    if not str(data.get('request_number') or '').strip() or not str(data.get('amendment') or '').strip():
        return None
    return data


def _text(data: Dict[str, Any], key: str, *, required: bool = False, limit: int = 2000) -> str:
    value = data.get(key, '')
    if not isinstance(value, str):
        value = ''
    value = value.strip()
    if required and not value:
        raise ValueError(f'{key} is required')
    if len(value) > limit:
        raise ValueError(f'{key} is too long')
    return value


def _strip_ref_prefix(value: str) -> str:
    value = str(value or '').strip()
    if ':' in value:
        kind, ref = value.split(':', 1)
        if kind.strip().lower() in ('request', 'order'):
            return ref.strip()
    return value


def _same_customer(row: Dict[str, Any], *, contact_id: str, phone: str) -> bool:
    if not row:
        return False
    row_contact = str(row.get('contactId') or '').strip()
    if row_contact and contact_id and row_contact == contact_id:
        return True
    wanted = contact_store.digits(phone)
    if not wanted:
        return False
    return any(
        contact_store.digits(row.get(field)) == wanted
        for field in ('phone', 'customerPhone', 'senderPhone')
    )


def _find_parent(table: Any, request_number: str) -> Dict[str, Any]:
    """Resolve the customer's request number as primary id first, then submissionNumber GSI."""
    ref = _strip_ref_prefix(request_number)
    if not ref:
        return {}
    try:
        row = table.get_item(Key={'submissionId': ref}, ConsistentRead=True).get('Item') or {}
        if row:
            return row
    except Exception as exc:
        logger.warning('{"event":"f005_parent_get_failed","error":"%s"}', type(exc).__name__)
    try:
        page = table.query(
            IndexName='submissionNumber',
            KeyConditionExpression='submissionNumber = :sn',
            ExpressionAttributeValues={':sn': ref},
            Limit=2,
        )
        items = page.get('Items') or []
        return items[0] if len(items) == 1 else {}
    except Exception as exc:
        logger.warning('{"event":"f005_parent_query_failed","error":"%s"}', type(exc).__name__)
        return {}


def _order_reference(data: Dict[str, Any]) -> str:
    selected = _strip_ref_prefix(_text(data, 'parent_order', limit=240))
    manual = _strip_ref_prefix(_text(data, 'manual_order_number', limit=240))
    return manual if selected in ('', 'none', 'not_found') else selected


def _write_history(db: Any, parent: Dict[str, Any], amendment_id: str,
                   amendment: str, request_id: str) -> None:
    """Append an audit-visible history event to the parent request; best effort."""
    try:
        now = int(time.time())
        db.Table(shared_tables.status_history_table_name()).put_item(Item={
            'historyId': str(uuid.uuid4()),
            'submissionId': str(parent.get('submissionId') or ''),
            'orderId': str(parent.get('orderId') or ''),
            'oldStatus': str(parent.get('status') or ''),
            'newStatus': str(parent.get('status') or ''),
            'changedBy': 'customer:whatsapp',
            'notes': f'Amendment {amendment_id}: {amendment[:500]}',
            'changedAt': Decimal(str(now)),
        })
    except Exception as exc:
        logger.warning('{"event":"f005_history_write_failed","error":"%s","requestId":"%s"}',
                       type(exc).__name__, request_id)


def response_answers(data: Dict[str, Any], result: flow_completion.CompletionResult) -> list:
    """Readable Inbox fields matching the endpointless F005 completion."""
    request_number = _strip_ref_prefix(_text(data, 'request_number', limit=240))
    amendment = _text(data, 'amendment', limit=2000)
    rows = []
    if request_number:
        rows.append({'question': 'Existing request', 'answer': request_number})
    if amendment:
        rows.append({'question': 'Change requested', 'answer': amendment})
    if result and result.reference:
        rows.append({'question': 'Amendment ID', 'answer': result.reference})
    return rows


def save_amendment(data: Dict[str, Any], *, contact_id: str, phone: str, sender_name: str,
                   message_id: str, dynamodb: Any, request_id: str = ''):
    """Save one F005 amendment and link it only to a verified sender-owned parent request."""
    if not contact_id or not phone or not message_id:
        raise ValueError('Request Amendment requires a sender and Meta message id')

    request_number = _strip_ref_prefix(
        _text(data, 'request_number', required=True, limit=240))
    amendment = _text(data, 'amendment', required=True, limit=2000)
    customer_order_ref = _order_reference(data)

    submissions = dynamodb.Table(shared_tables.flow_submissions_table_name())
    candidate = _find_parent(submissions, request_number)
    parent = candidate if _same_customer(candidate, contact_id=contact_id, phone=phone) else {}

    parent_id = str(parent.get('submissionId') or '')
    order_id = str(parent.get('orderId') or '')
    verified = bool(parent_id)
    status = 'submitted' if verified else 'awaiting_order_verification'

    # The order carried by the Flow is only advisory. The parent request's verified order wins.
    order_mismatch = bool(
        verified and customer_order_ref and order_id and customer_order_ref != order_id)
    if order_mismatch:
        status = 'awaiting_order_verification'

    form = {
        'request_number': request_number,
        'amendment': amendment,
        'subject': 'Request Amendment',
        'description': amendment,
    }
    if order_id:
        form['order_id'] = order_id

    extra = {
        'flowId': FLOW_ID,
        'flowName': FLOW_NAME,
        'flowVersion': FLOW_VERSION,
        'subject': 'Request Amendment',
        'description': amendment,
        'amendmentType': 'Customer amendment',
        'source': 'whatsapp',
        'customerPhone': contact_store.digits(phone),
        'customerName': sender_name,
        'whatsappDisplayName': sender_name,
        'whatsappMessageId': message_id,
        'customerRequestReference': request_number,
        'customerOrderReference': customer_order_ref,
        'parentVerification': 'verified' if verified else 'unverified',
    }
    if parent_id:
        extra['parentSubmissionId'] = parent_id
    if order_id:
        extra['orderId'] = order_id
    if parent.get('submissionNumber'):
        extra['parentSubmissionNumber'] = parent.get('submissionNumber')
    if parent.get('subject'):
        extra['parentSubject'] = parent.get('subject')

    result = flow_completion.claim_completion(
        flow_token=message_id,
        screen='REVIEW',
        flow_code=FLOW_CODE,
        flow_type='amendment',
        phone=contact_store.digits(phone),
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        reference_prefix=SUBMISSION_PREFIX,
        requires_payment=False,
        payment_amount=0,
        status=status,
        extra=extra,
        ttl_seconds=0,
        request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
    )
    if result.status == 'error':
        raise RuntimeError('Request Amendment completion could not be saved')

    if result.created and parent:
        _write_history(dynamodb, parent, result.submission_id, amendment, request_id)

    # Keep follow-up media associated with the original service request, not the amendment row.
    if parent_id:
        try:
            now = int(time.time())
            dynamodb.Table(shared_tables.contacts_table_name()).update_item(
                Key={'id': contact_id},
                UpdateExpression=(
                    'SET openServiceRequestId=:parent, openServiceRequestAt=:now, '
                    'lastFlowSubmissionId=:amend, updatedAt=:now'),
                ExpressionAttributeValues={
                    ':parent': parent_id, ':amend': result.submission_id, ':now': now},
                ConditionExpression='attribute_exists(id)',
            )
        except Exception as exc:
            logger.warning(
                '{"event":"f005_contact_projection_failed","contactId":"%s","error":"%s"}',
                mask_contact_id(contact_id), type(exc).__name__)

    return result
