"""
Amend Request Flow — ORDER-CENTRIC amendment of existing service requests.
Screens: ORDER_SELECT → SELECT_REQUEST → AMEND_FORM → CONFIRM (terminal)
"""
import json
import time
import uuid
import logging
from decimal import Decimal
from typing import Dict

from flows.orders import (
    fetch_orders_for_flow, get_submissions_for_order, extract_short_id,
    dynamodb, FLOW_SUBMISSIONS_TABLE,
)
from flows.common import get_phone_from_token, find_contact_by_phone
from lambda_utils import shared_tables

logger = logging.getLogger(__name__)

HISTORY_TABLE = shared_tables.status_history_table_name()


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT → fetch orders."""
    phone = get_phone_from_token(flow_token)
    orders = fetch_orders_for_flow(phone, data.get('email', ''))
    if not orders:
        orders = [{'id': 'none', 'title': 'No orders found'}]
    return {'screen': 'ORDER_SELECT', 'data': {'orders': orders}}


def handle_order_select(data: Dict, flow_token: str, request_id: str) -> Dict:
    """ORDER_SELECT → fetch requests for this order → SELECT_REQUEST."""
    order_id = data.get('order_id', '')
    submissions = get_submissions_for_order(order_id) if order_id and order_id != 'none' else []

    requests = []
    for sub in submissions:
        sub_num = sub.get('submissionNumber', sub.get('submissionId', ''))
        subject = sub.get('subject', sub.get('requestType', 'Request'))[:30]
        status = (sub.get('status', 'open') or 'open').replace('_', ' ').title()
        requests.append({
            'id': sub_num,
            'title': f'{sub_num} — {subject} — {status}',
        })

    if not requests:
        requests = [{'id': 'none', 'title': 'No requests found for this order'}]

    return {
        'screen': 'SELECT_REQUEST',
        'data': {
            'order_id': order_id,
            'requests': requests,
        }
    }


def handle_select_request(data: Dict, flow_token: str, request_id: str) -> Dict:
    """SELECT_REQUEST → show AMEND_FORM with original subject."""
    order_id = data.get('order_id', '')
    req_id = data.get('request_id', '')

    # Look up original subject
    original_subject = 'Request'
    if req_id and req_id != 'none':
        try:
            table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
            resp = table.query(
                IndexName='submissionNumber',
                KeyConditionExpression='submissionNumber = :sn',
                ExpressionAttributeValues={':sn': req_id},
                Limit=1,
            )
            items = resp.get('Items', [])
            if items:
                original_subject = items[0].get('subject', '') or items[0].get('requestType', 'Request')
        except Exception:
            pass

    return {
        'screen': 'AMEND_FORM',
        'data': {
            'order_id': order_id,
            'request_id': req_id,
            'original_subject': original_subject[:40],
        }
    }


def handle_amend_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    """AMEND_FORM → save amendment, return CONFIRM."""
    phone = get_phone_from_token(flow_token)
    order_id = data.get('order_id', '')
    req_id = data.get('request_id', '')
    amendment = data.get('amendment', '')

    # Save amendment as a note on the submission + log history
    now = int(time.time())
    try:
        if req_id and req_id != 'none':
            table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
            resp = table.query(
                IndexName='submissionNumber',
                KeyConditionExpression='submissionNumber = :sn',
                ExpressionAttributeValues={':sn': req_id},
                Limit=1,
            )
            items = resp.get('Items', [])
            if items:
                sub = items[0]
                sub_id = sub.get('submissionId', '')
                old_notes = sub.get('notes', '') or ''
                new_notes = f'{old_notes}\n[Amendment {time.strftime("%d %b %Y %H:%M", time.gmtime(now + 19800))}] {amendment}'.strip()
                table.update_item(
                    Key={'submissionId': sub_id},
                    UpdateExpression='SET notes = :n, updatedAt = :u',
                    ExpressionAttributeValues={
                        ':n': new_notes[:2000],
                        ':u': Decimal(str(now)),
                    },
                )
                # Log history
                try:
                    hist_table = dynamodb.Table(HISTORY_TABLE)
                    hist_table.put_item(Item={
                        'historyId': str(uuid.uuid4()),
                        'submissionId': sub_id,
                        'orderId': order_id,
                        'oldStatus': sub.get('status', ''),
                        'newStatus': sub.get('status', ''),
                        'changedBy': f'customer:{phone}',
                        'notes': f'Amendment: {amendment[:500]}',
                        'changedAt': Decimal(str(now)),
                    })
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f'Amendment save failed: {e}')

    try:
        from flows.common import send_simple_confirmation
        send_simple_confirmation(phone, flow_token, 'Amendment Submitted', req_id,
            f'Our team will review your amendment shortly.')
    except Exception:
        pass

    return {
        'screen': 'CONFIRM',
        'data': {
            'request_id': req_id or '—',
            'message': 'Your amendment has been submitted. Our team will review it shortly.',
        }
    }
