"""
Submit Request Flow — PAID (amount from FlowRegistry).
Collects: order, request type, subject, description.
Saves submission, creates invoice, sends payment link + confirmation.
"""
import json
import uuid
import logging
from typing import Dict

from flows.common import (
    lambda_client, PHONE1_ID,
    get_phone_from_token, get_phone_number_id_for_flow,
    find_contact_by_phone, get_contact_name,
    record_completion, send_payment, send_confirmation,
    save_draft, restore_draft, clear_draft,
)

logger = logging.getLogger(__name__)

# ── Flow config (defaults — overridden by FlowRegistry at runtime) ──
FLOW_CODE = '01.WD_SR'
FLOW_NAME = 'Submit Request'
SUBMISSION_PREFIX = 'WD-SR'
# Payment config comes from FlowRegistry — these are just safe defaults
DEFAULT_REQUIRES_PAYMENT = False
DEFAULT_PAYMENT_AMOUNT = 0


def handle_init(data: Dict, flow_token: str, request_id: str,
                fetch_orders_fn=None) -> Dict:
    """INIT → check for draft, fetch orders, navigate to ORDER_SELECT or resume screen."""
    from flows.orders import fetch_orders_for_flow
    phone = get_phone_from_token(flow_token)
    email = data.get('email', '')

    # Check for existing draft
    draft = restore_draft(phone, FLOW_CODE)

    orders = []
    try:
        orders = fetch_orders_for_flow(phone, email)
    except Exception as e:
        logger.warning(f'Order fetch failed: {e}')
    if not orders:
        orders = [{'id': 'none', 'title': 'No orders found'}]

    # If draft exists and has a valid screen, resume from there
    if draft and draft.get('screen') and draft['screen'] != 'ORDER_SELECT':
        resume_screen = draft['screen']
        resume_data = draft.get('formData', {})
        # Always include orders for potential back-navigation
        resume_data['orders'] = orders
        logger.info(json.dumps({
            'event': 'sr_draft_resume', 'screen': resume_screen,
            'phone_suffix': phone[-4:] if phone else '',
        }))
        return {'screen': resume_screen, 'data': resume_data}

    return {'screen': 'ORDER_SELECT', 'data': {'orders': orders}}


def handle_order_select(data: Dict, flow_token: str, request_id: str) -> Dict:
    """ORDER_SELECT → show SUBMIT_REQUEST_FORM with order context. Save draft."""
    from flows.orders import order_label
    phone = get_phone_from_token(flow_token)
    order_id = data.get('order_id', '')
    short_id = order_label(order_id) if order_id else ''
    # Save draft at this step
    save_draft(phone, FLOW_CODE, 'SUBMIT_REQUEST_FORM', {
        'order_id': order_id, 'order_short_id': short_id,
    })
    return {
        'screen': 'SUBMIT_REQUEST_FORM',
        'data': {
            'order_id': order_id,
            'order_short_id': short_id,
        }
    }


def handle_request_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    """SUBMIT_REQUEST_FORM → show TERMS with collected form data. Save draft."""
    phone = get_phone_from_token(flow_token)
    order_id = data.get('order_id', '')
    subject = data.get('subject', '')
    description = data.get('description', '')
    # Save draft with form data
    save_draft(phone, FLOW_CODE, 'TERMS', {
        'order_id': order_id, 'subject': subject, 'description': description,
    })
    return {
        'screen': 'TERMS',
        'data': {
            'order_id': order_id,
            'subject': subject,
            'description': description,
        }
    }


def handle_review(data: Dict, flow_token: str, request_id: str,
                  flow_config: Dict = None) -> Dict:
    """REVIEW screen → save, pay (if required), confirm, return SUCCESS.
    response_payload is set FIRST, saves happen after.
    Payment config comes from flow_config (FlowRegistry).
    """
    phone = get_phone_from_token(flow_token)
    phone_number_id = get_phone_number_id_for_flow(flow_token)

    order_id = data.get('order_id', '')
    subject = data.get('subject', '')
    description = data.get('description', '')
    request_type = data.get('request_type', '')

    # Payment config from FlowRegistry — NOT hardcoded
    # Fallback: if FlowRegistry has no config, check client-side payload flags
    cfg = flow_config or {}
    requires_payment = bool(cfg.get('requiresPayment', DEFAULT_REQUIRES_PAYMENT))
    payment_amount = int(cfg.get('paymentAmount', DEFAULT_PAYMENT_AMOUNT)) if requires_payment else 0

    # Client-side fallback: REVIEW screen sends payment_required + service_fee_amount
    # This ensures payment works even if FlowRegistry is not yet seeded
    if not requires_payment and data.get('payment_required') == 'true':
        requires_payment = True
        try:
            client_fee = int(data.get('service_fee_amount', '0'))
            payment_amount = client_fee * 100 if client_fee > 0 else 0  # convert rupees to paise
        except (ValueError, TypeError):
            payment_amount = 0

    flow_name = cfg.get('flowName', FLOW_NAME)
    prefix = cfg.get('submissionPrefix', SUBMISSION_PREFIX)

    logger.info(json.dumps({
        'event': 'sr_review_submit', 'order_id': order_id,
        'subjectLength': len(subject or ''),
        'requiresPayment': requires_payment, 'paymentAmount': payment_amount,
        'phoneNumberId': phone_number_id, 'requestId': request_id,
    }))

    # ── Claim the completion BEFORE anything else ──
    # This used to happen after the response was built, with a random request_number, and
    # with no condition on the write. A Meta retry of this data_exchange therefore produced
    # a second submission row, a second invoice, and a second payment link sent to the
    # customer - and gave them a different request number for the same request.
    #
    # The claim is now the first durable action, and `result.reference` is derived from the
    # flow token, so a retry recomputes the same reference and loses the conditional put.
    # It costs one round trip ahead of the response; a duplicate invoice costs money.
    contact_id = find_contact_by_phone(phone)
    sender_name = get_contact_name(contact_id)
    flow_code = cfg.get('flowCode', FLOW_CODE)

    # The payment reference is derived from the same completion key as the request number,
    # so a retry that somehow reached the payment path reuses the reference instead of
    # opening a second one. Previously `WD-PAY-{uuid4[:8]}`, fresh on every delivery.
    from lambda_utils import flow_completion as _fc
    _key, _ = _fc.completion_key(flow_token, 'REVIEW',
                                 {'order_id': order_id, 'subject': subject})
    payment_ref_id = _fc.reference_for(_key, 'WD-PAY') if requires_payment else ''

    result = record_completion(
        flow_code=flow_code, flow_type='form_submit',
        phone=phone, contact_id=contact_id, sender_name=sender_name,
        form_data={'order_id': order_id, 'subject': subject,
                   'description': description, 'request_type': request_type},
        flow_token=flow_token, request_id=request_id, screen='REVIEW',
        reference_prefix=prefix,
        requires_payment=requires_payment, payment_amount=payment_amount,
        payment_ref_id=payment_ref_id,
    )
    request_number = result.reference

    # ── SET SUCCESS RESPONSE ──
    # v3 flow: return THANK_YOU screen with readable short order ID.
    # Returned for a duplicate too: the customer's request *is* recorded, and showing them
    # an error for our own retry would be a lie. What a duplicate does not do is fire the
    # side effects below.
    from flows.orders import order_label
    short_order_id = order_label(order_id)
    response_payload = {
        'screen': 'THANK_YOU',
        'data': {
            'order_id': order_id,
            'order_short_id': short_order_id,
            'request_number': request_number,
            'payment_ref_id': payment_ref_id or 'N/A',
        }
    }

    if not result.should_fire_side_effects:
        logger.info(json.dumps({
            'event': 'sr_review_submit_no_side_effects',
            'status': result.status, 'submissionId': result.submission_id,
            'reason': 'duplicate completion' if result.duplicate else result.error,
            'requestId': request_id,
        }))
        return response_payload

    # Clear draft after successful submission
    try:
        clear_draft(phone, flow_code)
    except Exception:
        pass

    # ── Payment + confirmation (async) ──
    try:
        lambda_client.invoke(
            FunctionName=lambda_client._endpoint.host.split('/')[-1] if hasattr(lambda_client, '_endpoint') else 'wecare-whatsapp-business-api',
            InvocationType='Event',
            Payload=json.dumps({
                '_async_action': 'flow_post_submit',
                'phone': phone, 'phone_number_id': phone_number_id,
                'order_id': order_id, 'subject': subject,
                'request_id': request_id, 'request_number': request_number,
                'payment_ref_id': payment_ref_id,
                'requires_payment': requires_payment,
                'payment_amount': payment_amount,
                'flow_name': flow_name,
                'flow_code': cfg.get('flowCode', FLOW_CODE),
            })
        )
    except Exception as e:
        logger.error(f'Async post-submit invoke failed: {e}')
        # Fallback: sync
        try:
            invoice_number = ''
            if requires_payment and payment_amount:
                invoice_number = send_payment(
                    phone=phone, phone_number_id=phone_number_id,
                    order_id=order_id, subject=subject, request_id=request_id,
                    request_number=request_number, payment_ref_id=payment_ref_id,
                    payment_amount_paise=payment_amount, flow_name=flow_name,
                )
            send_confirmation(
                phone=phone, phone_number_id=phone_number_id, request_id=request_id,
                flow_name=flow_name, request_number=request_number,
                requires_payment=requires_payment, payment_amount=payment_amount,
                payment_ref_id=payment_ref_id, invoice_number=invoice_number,
                order_id=order_id, subject=subject,
            )
        except Exception as e2:
            logger.error(f'Sync fallback failed: {e2}')

    return response_payload
