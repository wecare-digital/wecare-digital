"""Published F004 Submit Request completion -> one durable FlowSubmission + Inbox projection.

F004 is an endpointless-style published Flow. Meta returns its terminal complete payload through
interactive.nfm_reply.response_json; the client payload contains a placeholder submission_id, so
that value is never trusted. The server derives the real WD-SR reference from the signed Meta
message id through flow_completion.claim_completion.

The selected target is advisory until ownership is verified against the sender's contact. A
verified order/request is linked into the FlowSubmission row; an unknown or mismatched target is
kept as a customer reference and filed awaiting_order_verification instead of being attached to
another customer's record.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from lambda_utils import canonical_flows, contact_store, flow_completion, flow_sessions, shared_tables
from lambda_utils.ecommerce import order_keys, single_order_flow
from lambda_utils.privacy import mask_contact_id

logger = logging.getLogger(__name__)

FLOW_KEY = 'wd_f004_submit_request'
FLOW_ID = canonical_flows.canonical_flow_id('submit_request') or '993516553092471'
FLOW_CODE = '01.WD_SR'
FLOW_NAME = 'WD-F004-Submit-Request'
FLOW_VERSION = '7.3'
SUBMISSION_PREFIX = 'WD-SR'

# The published Pickup Flow was cloned from F004 and still carries FLOW_KEY below.
# Our generic sender mints request_pickup tokens as `request_pi-...`; keep those
# completions out of the Submit Request saver rather than silently misfiling them.
PICKUP_TOKEN_PREFIXES = ('request_pi-', 'request_pickup-')
PAID_TOKEN_PREFIXES = ('srpaid-',)


def request_payload(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recognise only the published F004 completion; leave every other nfm_reply alone."""
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
    if not isinstance(data, dict) or data.get('flow_key') != FLOW_KEY:
        return None
    flow_token = str(data.get('flow_token') or '').strip()
    if flow_token.startswith(PICKUP_TOKEN_PREFIXES):
        return None
    return data


def _clean_text(data: Dict[str, Any], key: str, *, required: bool = False,
                limit: int = 2000) -> str:
    value = data.get(key, '')
    if not isinstance(value, str):
        value = ''
    value = value.strip()
    if required and not value:
        raise ValueError(f'{key} is required')
    if len(value) > limit:
        raise ValueError(f'{key} is too long')
    return value


def _same_customer(row: Dict[str, Any], *, contact_id: str, phone: str) -> bool:
    if not row:
        return False
    row_contact = str(row.get('contactId') or '')
    if row_contact and contact_id and row_contact == contact_id:
        return True
    wanted = contact_store.digits(phone)
    if not wanted:
        return False
    for field in ('phone', 'customerPhone', 'senderPhone'):
        if contact_store.digits(row.get(field)) == wanted:
            return True
    return False


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


def _verified_target(db: Any, raw: str, *, contact_id: str, phone: str) -> Tuple[Dict[str, Any], str]:
    """Return (extra fields, submission status) after sender ownership verification."""
    kind, ref = _target_parts(raw)
    base: Dict[str, Any] = {'targetType': kind, 'targetReference': ref or raw}

    if kind == 'order' and ref:
        try:
            order_id = ref
            # New public Order Numbers are display identifiers, never OrderTable partition keys.
            # Resolve through the immutable CommerceKeys ORDERNO# reservation first. Legacy
            # internal ids remain readable for historical Flow submissions.
            if order_keys.is_public_order_number(ref):
                reservation = db.Table(shared_tables.commerce_keys_table_name()).get_item(
                    Key={'orderId': order_keys.ORDER_NUMBER_PREFIX + ref},
                    ConsistentRead=True,
                ).get('Item') or {}
                order_id = str(reservation.get('orderIdRef') or '')
            row = (
                db.Table(shared_tables.orders_table_name()).get_item(
                    Key={'orderId': order_id}, ConsistentRead=True).get('Item') or {}
                if order_id else {}
            )
        except Exception as exc:  # storage uncertainty is not an ownership proof
            logger.warning('{"event":"f004_order_lookup_failed","error":"%s"}',
                           type(exc).__name__)
            order_id, row = '', {}
        if _same_customer(row, contact_id=contact_id, phone=phone):
            return {
                **base,
                'orderId': order_id,
                'orderNumber': str(row.get('orderNumber') or ref),
            }, 'open'
        return {**base, 'orderReference': ref}, 'awaiting_order_verification'

    if kind == 'request' and ref:
        try:
            row = db.Table(shared_tables.flow_submissions_table_name()).get_item(
                Key={'submissionId': ref}, ConsistentRead=True).get('Item') or {}
        except Exception as exc:
            logger.warning('{"event":"f004_request_lookup_failed","error":"%s"}',
                           type(exc).__name__)
            row = {}
        if _same_customer(row, contact_id=contact_id, phone=phone):
            extra = {**base, 'parentSubmissionId': ref}
            if row.get('orderId'):
                extra['orderId'] = row['orderId']
            return extra, 'open'
        return {**base, 'orderReference': ref}, 'awaiting_order_verification'

    return base, 'awaiting_order_verification'


def _paid_binding(db: Any, data: Dict[str, Any], *, phone: str):
    """Verify a new single-order paid launcher. Legacy/unpaid entries return None."""
    token = str(data.get('flow_token') or '').strip()
    if not token.startswith(PAID_TOKEN_PREFIXES):
        return None
    try:
        session = flow_sessions.verify_session(
            db.Table(shared_tables.flow_drafts_table_name()),
            capability='submit_request',
            token=token,
            rejected_message='This Submit Request form is no longer available.',
        )
        binding = single_order_flow.verify_paid_session(
            session=session,
            attempts=db.Table(shared_tables.payment_attempts_table_name()),
            orders=db.Table(shared_tables.orders_table_name()),
            capability='submit_request',
            service_code='SUBMIT_REQUEST',
            phone=phone,
        )
    except (flow_sessions.FlowSessionRejected, flow_sessions.FlowSessionUnavailable,
            single_order_flow.PaidFlowBindingError) as exc:
        raise ValueError('This Submit Request payment could not be verified.') from exc

    kind, reference = _target_parts(_clean_text(data, 'reference_number', limit=240))
    if kind != 'order' or reference.upper() != binding.order_number.upper():
        raise ValueError('Submit Request order does not match the paid order.')
    return session, binding


def response_answers(data: Dict[str, Any], result: flow_completion.CompletionResult) -> list:
    """Readable Inbox answers for the published three-screen F004."""
    _, ref = _target_parts(_clean_text(data, 'reference_number', limit=240))
    note = _clean_text(data, 'note', limit=2000)
    rows = []
    if ref:
        rows.append({'question': 'Linked to', 'answer': ref})
    if note:
        rows.append({'question': 'Note', 'answer': note})
    if result and result.reference:
        rows.append({'question': 'Request ID', 'answer': result.reference})
    return rows


def save_request(data: Dict[str, Any], *, contact_id: str, phone: str, sender_name: str,
                 message_id: str, dynamodb: Any, request_id: str = ''):
    """Claim one F004 request, verify its target, and expose it for follow-up attachments."""
    if not contact_id or not phone or not message_id:
        raise ValueError('Submit Request requires a sender and Meta message id')

    target = _clean_text(data, 'reference_number', required=True, limit=240)
    note = _clean_text(data, 'note', required=True, limit=2000)
    schema_version = _clean_text(data, 'schema_version', limit=20) or '1'
    paid = _paid_binding(dynamodb, data, phone=phone)
    if paid is not None:
        paid_session, binding = paid
        target_extra, status = ({
            'targetType': 'order',
            'targetReference': binding.order_number,
            'orderId': binding.order_id,
            'orderNumber': binding.order_number,
            'paymentAttemptId': binding.payment_attempt_id,
            'singleOrderService': True,
        }, 'open')
    else:
        paid_session = None
        target_extra, status = _verified_target(
            dynamodb, target, contact_id=contact_id, phone=phone)

    form = {
        'selected_target': target,
        'note': note,
        'subject': 'Submit Request',
        'description': note,
    }
    if target_extra.get('orderId'):
        form['order_id'] = target_extra['orderId']

    result = flow_completion.claim_completion(
        # Meta's inbound message id is server-authenticated and stable across webhook retries.
        flow_token=message_id,
        screen='CONFIRMATION',
        flow_code=FLOW_CODE,
        flow_type='form_submit',
        phone=contact_store.digits(phone),
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form,
        reference_prefix=SUBMISSION_PREFIX,
        requires_payment=False,
        payment_amount=0,
        status=status,
        extra={
            'flowId': FLOW_ID,
            'flowName': FLOW_NAME,
            'flowVersion': FLOW_VERSION,
            'schemaVersion': schema_version,
            'subject': 'Submit Request',
            'description': note,
            'source': 'whatsapp',
            'customerPhone': contact_store.digits(phone),
            'customerName': sender_name,
            'whatsappDisplayName': sender_name,
            'whatsappMessageId': message_id,
            **target_extra,
        },
        # A service case is a business record, not a transport log.
        ttl_seconds=0,
        request_id=request_id,
        channel=flow_completion.CHANNEL_WHATSAPP,
    )
    if result.status == 'error':
        raise RuntimeError('Submit Request completion could not be saved')

    if paid_session is not None:
        now = int(time.time())
        try:
            dynamodb.Table(shared_tables.payment_attempts_table_name()).update_item(
                Key={'paymentAttemptId': binding.payment_attempt_id},
                UpdateExpression=(
                    'SET fulfillmentCompletedAt=:now, flowSubmissionId=:sid, '
                    'serviceFlowCompletionStatus=:done, updatedAt=:now'),
                ConditionExpression=(
                    '#status=:paid AND singleOrderService=:true AND serviceCode=:service '
                    'AND selectedOrderId=:order AND '
                    '(attribute_not_exists(fulfillmentCompletedAt) OR flowSubmissionId=:sid)'),
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':now': now,
                    ':sid': result.submission_id,
                    ':done': 'COMPLETED',
                    ':paid': 'PAYMENT_PAID',
                    ':true': True,
                    ':service': 'SUBMIT_REQUEST',
                    ':order': binding.order_id,
                },
            )
        except Exception as exc:
            logger.warning(
                '{"event":"f004_paid_fulfillment_projection_failed","error":"%s"}',
                type(exc).__name__)
            raise RuntimeError('Submit Request paid fulfilment could not be finalized') from exc
        flow_sessions.mark_consumed(
            dynamodb.Table(shared_tables.flow_drafts_table_name()),
            token=str(data.get('flow_token') or ''))

    # Repairable projection used by inbound media linking: photos/documents sent after this
    # Flow attach to the same service case for 14 days. A webhook retry may safely rewrite
    # the same pointer; it never creates a second FlowSubmission.
    try:
        import time
        now = int(time.time())
        dynamodb.Table(shared_tables.contacts_table_name()).update_item(
            Key={'id': contact_id},
            UpdateExpression=(
                'SET openServiceRequestId=:sid, openServiceRequestAt=:now, '
                'lastFlowSubmissionId=:sid, updatedAt=:now'),
            ExpressionAttributeValues={':sid': result.submission_id, ':now': now},
            ConditionExpression='attribute_exists(id)',
        )
    except Exception as exc:  # durable FlowSubmission already exists; projection is repairable
        logger.warning(
            '{"event":"f004_contact_projection_failed","contactId":"%s","error":"%s"}',
            mask_contact_id(contact_id), type(exc).__name__)

    return result
