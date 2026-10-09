"""
Flow Router — routes decrypted flow data to the correct flow module.
Each flow is fully isolated. No cross-flow logic leakage.
"""
import json
import logging
from typing import Dict, Callable

from flows import subscribe, submit_request, track_request, amend_request, appointment, rx_slot, drop_docs, enterprise_assist, leave_review, order_notes, generic, postpay
from flows.common import get_phone_from_token, log_flow_event
from flows.orders import fetch_orders_for_flow as _orders_fetch

logger = logging.getLogger(__name__)

# Token prefix → flow key mapping
TOKEN_PREFIX_TO_FLOW_CODE = {
    'sr': '01.WD_SR',
    'submit_re': '01.WD_SR',
}

# Flow keys that use the generic handler
GENERIC_FLOW_PREFIXES = set()  # All modules now have dedicated handlers


def _extract_flow_key(flow_token: str) -> str:
    """Extract flow_key from token: {flow_key}-{uuid}-waba-{1|2}-ph-{phone}"""
    if not flow_token or '-ph-' not in flow_token:
        return ''
    prefix = flow_token.split('-ph-', 1)[0]
    parts = prefix.split('-')
    key_parts = []
    for p in parts:
        if len(p) > 10:  # UUID segment
            break
        key_parts.append(p)
    return '_'.join(key_parts) if key_parts else parts[0]


def route_flow(action: str, screen: str, data: Dict, flow_token: str,
               request_id: str, get_flow_registry_fn: Callable = None,
               fetch_orders_fn: Callable = None) -> Dict:
    """Route a flow action to the correct flow module.
    Returns the response_payload dict to be encrypted and returned to Meta.
    """
    if flow_token and flow_token.startswith('orders:'):
        from flows import customer_orders
        return customer_orders.route(action, screen, data, flow_token)

    if flow_token and flow_token.startswith('paidsr:'):
        from flows import paid_submit_request
        return paid_submit_request.route(action, screen, data, flow_token)

    flow_key = _extract_flow_key(flow_token)
    phone = get_phone_from_token(flow_token)

    # Log every non-ping interaction
    if action != 'ping':
        try:
            log_flow_event(flow_token, phone, action, screen, data, request_id)
        except Exception:
            pass

    logger.info(json.dumps({
        'event': 'flow_route', 'action': action, 'screen': screen,
        'flow_key': flow_key, 'phone_suffix': phone[-4:] if phone else '',
        'requestId': request_id,
    }))

    # ── Ping ──
    if action == 'ping':
        return {'data': {'status': 'active'}}

    # ── POST-PAYMENT DETAILS FLOW (data_exchange) ──
    if flow_token and flow_token.startswith('postpay'):
        if action == 'INIT':
            return postpay.handle_init(data, flow_token, request_id)
        if screen in ('THANK_YOU', 'SUCCESS', 'COMPLETE'):
            return _terminal_response(flow_token)
        if screen == 'DETAILS':
            return postpay.handle_submit(data, flow_token, request_id)
        # Any other data_exchange (e.g. THANK_YOU footer) completes the flow
        return _terminal_response(flow_token)

    # ── SUBSCRIBE FLOW ──
    if flow_token and flow_token.startswith('subscribe'):
        if action == 'INIT':
            return subscribe.handle_init(data, flow_token, request_id)
        if screen == 'REVIEW':
            return subscribe.handle_review(data, flow_token, request_id)
        if screen in ('THANK_YOU', 'SUCCESS', 'COMPLETE'):
            return _terminal_response(flow_token)
        # Pass-through for intermediate screens
        return {'data': data}

    # ── SUBMIT REQUEST FLOW ──
    if flow_key in ('sr', 'submit_re') or flow_key.startswith('sr'):
        flow_config = {}
        flow_code = TOKEN_PREFIX_TO_FLOW_CODE.get(flow_key, '01.WD_SR')
        if get_flow_registry_fn:
            flow_config = get_flow_registry_fn(flow_code) or {}

        if action == 'INIT':
            return submit_request.handle_init(data, flow_token, request_id,
                                              fetch_orders_fn=fetch_orders_fn)
        if screen == 'ORDER_SELECT':
            return submit_request.handle_order_select(data, flow_token, request_id)
        if screen in ('SUBMIT_REQUEST_FORM', 'REQUEST_FORM'):
            return submit_request.handle_request_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return submit_request.handle_review(data, flow_token, request_id,
                                                flow_config=flow_config)
        if screen in ('THANK_YOU', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── AMEND REQUEST FLOW ──
    if flow_key in ('amend_requ',) or flow_key.startswith('amend'):
        if action == 'INIT':
            return amend_request.handle_init(data, flow_token, request_id)
        if screen == 'ORDER_SELECT':
            return amend_request.handle_order_select(data, flow_token, request_id)
        if screen == 'SELECT_REQUEST':
            return amend_request.handle_select_request(data, flow_token, request_id)
        if screen == 'AMEND_FORM':
            return amend_request.handle_amend_form(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── TRACK REQUEST FLOW ──
    if flow_key in ('track_requ',) or flow_key.startswith('track'):
        if action == 'INIT':
            return track_request.handle_init(data, flow_token, request_id)
        if screen == 'ORDER_SELECT':
            return track_request.handle_order_select(data, flow_token, request_id)
        if screen in ('STATUS', 'THANK_YOU', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── APPOINTMENT FLOW ──
    if flow_key in ('schedule_a',) or flow_key.startswith('schedule') or flow_key.startswith('appoint'):
        if action == 'INIT':
            return appointment.handle_init(data, flow_token, request_id)
        if screen == 'BOOKING_FORM':
            return appointment.handle_booking_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return appointment.handle_review(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── RX SLOT FLOW ──
    if flow_key in ('rx_slot',) or flow_key.startswith('rx'):
        if action == 'INIT':
            return rx_slot.handle_init(data, flow_token, request_id)
        if screen == 'SLOT_FORM':
            return rx_slot.handle_slot_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return rx_slot.handle_review(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── DROP DOCS FLOW ──
    if flow_key in ('drop_docs',) or flow_key.startswith('drop'):
        if action == 'INIT':
            return drop_docs.handle_init(data, flow_token, request_id)
        if screen == 'DOC_FORM':
            return drop_docs.handle_doc_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return drop_docs.handle_review(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── ENTERPRISE ASSIST FLOW ──
    if flow_key in ('enterprise',) or flow_key.startswith('enterprise'):
        if action == 'INIT':
            return enterprise_assist.handle_init(data, flow_token, request_id)
        if screen == 'INTAKE_FORM':
            return enterprise_assist.handle_intake_form(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── LEAVE REVIEW FLOW ──
    if flow_key in ('leave_revi',) or flow_key.startswith('leave'):
        if action == 'INIT':
            return leave_review.handle_init(data, flow_token, request_id)
        if screen == 'REVIEW_FORM':
            return leave_review.handle_review_form(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── ORDER NOTES FLOW ──
    if flow_key in ('order_note',) or flow_key.startswith('order_n'):
        if action == 'INIT':
            return order_notes.handle_init(data, flow_token, request_id)
        if screen == 'ORDER_SELECT':
            return order_notes.handle_order_select(data, flow_token, request_id)
        if screen == 'NOTES_FORM':
            return order_notes.handle_notes_form(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── GENERIC FLOWS (fallback only) ──
    is_generic = any(flow_key.startswith(k) for k in GENERIC_FLOW_PREFIXES)
    if is_generic:
        if screen == 'WELCOME':
            return generic.handle_welcome(data, flow_token, request_id)
        if screen == 'FORM':
            return generic.handle_form(data, flow_token, request_id, flow_key=flow_key)
        return generic.handle_any_screen(data, flow_token, request_id)

    # ── INIT for non-subscribe flows (order fetch) ──
    if action == 'INIT':
        orders = []
        if fetch_orders_fn:
            try:
                orders = fetch_orders_fn(phone, data.get('email', ''))
            except Exception:
                pass
        if not orders:
            orders = [{'id': 'none', 'title': 'No orders found'}]
        return {'screen': 'ORDER_SELECT' if flow_key in ('sr', 'submit_re') else 'WELCOME',
                'data': {'orders': orders}}

    # ── Terminal screens ──
    if screen in ('THANK_YOU', 'SUCCESS'):
        return _terminal_response(flow_token)

    # ── Fallback ──
    if data.get('error'):
        return {'data': {'acknowledged': True}}

    return {'data': {'error': f'Unhandled: action={action} screen={screen}'}}


def _terminal_response(flow_token: str) -> Dict:
    return {
        'screen': 'SUCCESS',
        'data': {
            'extension_message_response': {
                'params': {'flow_token': flow_token, 'status': 'completed'}
            }
        }
    }
