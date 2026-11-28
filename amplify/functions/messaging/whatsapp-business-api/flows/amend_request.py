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
    dynamodb, FLOW_SUBMISSIONS_TABLE, order_belongs_to,
)
from flows.common import require_session, reject, find_contact_by_phone
from lambda_utils import contact_store, shared_tables

logger = logging.getLogger(__name__)

HISTORY_TABLE = shared_tables.status_history_table_name()
#: Server-issued session capability; the customer comes from the session, not the token.
CAPABILITY = 'amend_request'


def _require_owned_order(order_id: str, phone: str) -> None:
    """Refuse (HTTP 427) an order id the session customer does not own. '' and 'none' pass."""
    if order_id and order_id != 'none' and not order_belongs_to(order_id, phone):
        reject('order_not_owned')


def _customer_owns_request(row: Dict, phone: str) -> bool:
    """A request this customer filed, or one linked to an order they own."""
    wanted = contact_store.digits(phone)
    if wanted and any(contact_store.digits(row.get(field)) == wanted
                      for field in ('phone', 'customerPhone', 'senderPhone')):
        return True
    return order_belongs_to(str(row.get('orderId') or ''), phone)


# F005 (1421471529574569) keeps the cloned three-screen design:
# SELECT_ORDER -> AMENDMENT -> REVIEW. The endpoint is used only for the customer-owned
# order/request pickers; the terminal REVIEW completion arrives later as nfm_reply.
def handle_f005_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT -> SELECT_ORDER with the session customer's real orders."""
    session = require_session(flow_token, CAPABILITY, allow_consumed=False)
    orders = fetch_orders_for_flow(session.phone, '')
    if not orders:
        orders = [{'id': 'none', 'title': 'No orders found'}]
    return {'screen': 'SELECT_ORDER', 'data': {'orders': orders}}


def _f005_request_choices(order_id: str) -> list:
    """Real service requests for one order; exclude reviews/docs/amendments and other responses."""
    if not order_id or order_id == 'none':
        return []
    requests = []
    for sub in get_submissions_for_order(order_id):
        # Submit Request rows (including staff-created requests) share this canonical code/type.
        if sub.get('flowCode') != '01.WD_SR' and sub.get('flowType') != 'form_submit':
            continue
        sub_num = sub.get('submissionNumber') or sub.get('submissionId') or ''
        if not sub_num:
            continue
        subject = (sub.get('subject') or sub.get('requestType') or 'Request')[:30]
        status = (sub.get('status') or 'open').replace('_', ' ').title()
        requests.append({'id': sub_num, 'title': f'{sub_num} — {subject} — {status}'})
    return requests


def handle_f005_select_order(data: Dict, flow_token: str, request_id: str) -> Dict:
    """SELECT_ORDER data_exchange -> same AMENDMENT screen populated with existing requests."""
    session = require_session(flow_token, CAPABILITY)
    order_id = str(data.get('parent_order') or '').strip()
    _require_owned_order(order_id, session.phone)
    requests = _f005_request_choices(order_id)
    if not requests:
        requests = [{'id': 'none', 'title': 'No existing requests found for this order'}]
    return {
        'screen': 'AMENDMENT',
        'data': {
            'parent_order': order_id,
            'requests': requests,
        },
    }


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT → the session customer's orders."""
    session = require_session(flow_token, CAPABILITY, allow_consumed=False)
    orders = fetch_orders_for_flow(session.phone, '')
    if not orders:
        orders = [{'id': 'none', 'title': 'No orders found'}]
    return {'screen': 'ORDER_SELECT', 'data': {'orders': orders}}


def handle_order_select(data: Dict, flow_token: str, request_id: str) -> Dict:
    """ORDER_SELECT → fetch requests for this order → SELECT_REQUEST."""
    session = require_session(flow_token, CAPABILITY)
    order_id = data.get('order_id', '')
    _require_owned_order(order_id, session.phone)
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


def _customer_request(req_id: str, phone: str) -> Dict:
    """The request row for `req_id` ({} when absent or unreadable); 427 if not this customer's."""
    if not req_id or req_id == 'none':
        return {}
    try:
        resp = dynamodb.Table(FLOW_SUBMISSIONS_TABLE).query(
            IndexName='submissionNumber',
            KeyConditionExpression='submissionNumber = :sn',
            ExpressionAttributeValues={':sn': req_id},
            Limit=1,
        )
        items = resp.get('Items', [])
    except Exception:
        return {}
    if items and not _customer_owns_request(items[0], phone):
        reject('request_not_owned')
    return items[0] if items else {}


def handle_select_request(data: Dict, flow_token: str, request_id: str) -> Dict:
    """SELECT_REQUEST → show AMEND_FORM with original subject."""
    session = require_session(flow_token, CAPABILITY)
    order_id = data.get('order_id', '')
    req_id = data.get('request_id', '')
    _require_owned_order(order_id, session.phone)

    # Look up original subject
    original_subject = 'Request'
    sub = _customer_request(req_id, session.phone)
    if sub:
        original_subject = sub.get('subject', '') or sub.get('requestType', 'Request')

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
    phone = require_session(flow_token, CAPABILITY).phone
    order_id = data.get('order_id', '')
    req_id = data.get('request_id', '')
    amendment = data.get('amendment', '')
    _require_owned_order(order_id, phone)
    sub = _customer_request(req_id, phone)

    # Save amendment as a note on the submission + log history
    now = int(time.time())
    try:
        if sub:
            table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
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
