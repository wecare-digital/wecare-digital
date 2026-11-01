"""
Flow Router — routes decrypted flow data to the correct flow module.
Each flow is fully isolated. No cross-flow logic leakage.
"""
import json
import logging
from typing import Dict, Callable

# Import a Flow handler only when this request is actually routed to it.
# The previous eager import pulled every service/checkout module into cold
# INIT and Meta ping requests, including static Review/Referral opening screens.
from flows.common import get_phone_from_token, log_flow_event

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

    # ── POST-PAYMENT DETAILS FLOW: retired ──
    # flows/postpay.py was removed on 2026-10-25. Nothing mints a `postpay-` token any more (the
    # paid invoice template is the only post-payment message) and both post-payment Flows are
    # DEPRECATED on Meta. Its INIT answered invoice and payment details for whatever reference a
    # token named, so a stale or forged postpay token gets a data-free refusal here instead of
    # falling through to the order-fetch INIT below.
    if flow_token and flow_token.startswith('postpay'):
        return {'data': {'error': 'This form is no longer available.'}}

    # ── F001 SUBSCRIBE (WD-F001-SUBSCRIBE-PROFILE) ──
    # One handler owns every subscribe-token request, including Meta error notifications.
    # It verifies the server-issued session first and never answers with a terminal
    # SUCCESS screen, so no request can finish the Flow without a confirmed save.
    if flow_token and flow_token.startswith('subscribe'):
        from flows import subscribe_profile
        return subscribe_profile.route(action, screen, data, flow_token, request_id)

    # Approved invoice and manual Leave Review templates now use DATA_EXCHANGE,
    # despite F002 remaining endpointless at completion. Its FEEDBACK screen has
    # no private initial data; its signed nfm_reply is saved by customer_ideas.
    # Never use the general order-list fallback for an invoice-bound review token.
    if flow_token and flow_token.startswith('review-'):
        from lambda_utils.ecommerce import review_token
        if action == 'INIT' and review_token.is_review_token(flow_token):
            return {'screen': 'FEEDBACK', 'data': {}}
        return {'data': {'error': 'This review link is unavailable.'}}

    # Shared SELECT_TARGET -> NOTE -> CONFIRMATION assets for paid single-order
    # services. The retired handlers below return ORDER_SELECT/AMENDMENT screens,
    # which do not exist in the approved customer-visible JSON. INIT must verify
    # the issued session, captured payment and one bound order before any prefill.
    if flow_token and flow_token.startswith(('srpaid-', 'amendpaid-', 'request_pickup-')):
        if action == 'INIT':
            from flows import paid_service_targets
            return paid_service_targets.handle_init(flow_token)
        return {'data': {'error': 'Unsupported paid service Flow action.'}}

    # ── SUBMIT REQUEST FLOW ──
    if flow_key in ('sr', 'submit_re') or flow_key.startswith('sr'):
        from flows import submit_request
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
        from flows import amend_request
        # F005 keeps the cloned SELECT_ORDER -> AMENDMENT -> REVIEW UI. INIT supplies the
        # sender-owned orders; SELECT_ORDER data_exchange supplies requests for that order.
        if action == 'INIT':
            return amend_request.handle_f005_init(data, flow_token, request_id)
        if screen == 'SELECT_ORDER' and action == 'data_exchange':
            return amend_request.handle_f005_select_order(data, flow_token, request_id)

        # Legacy/deprecated amendment assets used these older screen ids. Keep the handlers
        # readable for historical replay without changing F005's three-screen contract.
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
        from flows import track_request
        if action == 'INIT':
            return track_request.handle_init(data, flow_token, request_id)
        if screen == 'ORDER_SELECT':
            return track_request.handle_order_select(data, flow_token, request_id)
        if screen in ('STATUS', 'THANK_YOU', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── F006 TRACK SHIPPING FLOW ──
    if flow_key == 'shipments' or flow_key.startswith('shipments'):
        from flows import shipments
        if action == 'INIT':
            return shipments.handle_init(data, flow_token, request_id)
        if screen in ('CONFIRMATION', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── APPOINTMENT FLOW ──
    if flow_key in ('schedule_a',) or flow_key.startswith('schedule') or flow_key.startswith('appoint'):
        from flows import appointment
        if action == 'INIT':
            return appointment.handle_init(data, flow_token, request_id)
        if screen == 'BOOKING_FORM':
            return appointment.handle_booking_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return appointment.handle_review(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── SEHAT APPOINTMENT FLOW ──
    if flow_key in ('sehat_appointment', 'rx_slot') or flow_key.startswith('sehat') or flow_key.startswith('rx'):
        from flows import sehat_appointment
        if action == 'INIT':
            return sehat_appointment.handle_init(data, flow_token, request_id)
        if screen == 'SLOT_FORM':
            return sehat_appointment.handle_slot_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return sehat_appointment.handle_review(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── DROP DOCS FLOW ──
    if flow_key in ('drop_docs',) or flow_key.startswith('drop'):
        from flows import drop_docs
        if action == 'INIT':
            return drop_docs.handle_init(data, flow_token, request_id)
        if screen == 'UPLOAD' and action == 'data_exchange':
            return drop_docs.handle_upload(data, flow_token, request_id)
        if screen == 'DOC_FORM':
            return drop_docs.handle_doc_form(data, flow_token, request_id)
        if screen == 'REVIEW':
            return drop_docs.handle_review(data, flow_token, request_id)
        if screen in ('COMPLETE', 'CONFIRM', 'CONFIRMATION', 'SUCCESS'):
            return _terminal_response(flow_token)

    # ── ENTERPRISE ASSIST FLOW ──
    if flow_key in ('enterprise',) or flow_key.startswith('enterprise'):
        from flows import enterprise_assist
        if action == 'INIT':
            return enterprise_assist.handle_init(data, flow_token, request_id)
        if screen == 'INTAKE_FORM':
            return enterprise_assist.handle_intake_form(data, flow_token, request_id)
        if screen in ('CONFIRM', 'SUCCESS'):
            return _terminal_response(flow_token)

    # F008's approved referral template uses DATA_EXCHANGE to open its static
    # REFER screen. The terminal signed nfm_reply owns persistence and consent;
    # the endpoint must never create a submission or message the referred person.
    if flow_key == 'referral':
        if action == 'INIT':
            return {'screen': 'REFER', 'data': {}}
        return {'data': {'error': 'Unsupported referral Flow action.'}}

    # The existing manual Leave Review template uses DATA_EXCHANGE. Its routed
    # leave-* token can open only FEEDBACK (no private data is returned); the
    # signed nfm_reply still belongs to customer_ideas and the actual sender.
    # Invoice review-* tokens are handled earlier with their order binding.
    if flow_key.startswith('leave'):
        if action == 'INIT':
            return {'screen': 'FEEDBACK', 'data': {}}
        return {'data': {'error': 'Unsupported review Flow action.'}}

    # ── ORDER NOTES FLOW ──
    if flow_key in ('order_note',) or flow_key.startswith('order_n'):
        from flows import order_notes
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
        from flows import generic
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
