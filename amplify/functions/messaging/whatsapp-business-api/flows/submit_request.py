"""
Submit Request Flow — PAID (amount from FlowRegistry).
Collects: order, request type, subject, description.
Saves submission, creates invoice, sends payment link + confirmation.
"""
import json
import os
import uuid
import logging
from typing import Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError

from flows.common import (
    PHONE1_ID,
    get_phone_from_token, get_phone_number_id_for_flow,
    find_contact_by_phone, get_contact_name,
    record_completion, send_payment, send_confirmation,
    save_draft, restore_draft, clear_draft,
)
from lambda_utils.flow_launch import parse_bool

logger = logging.getLogger(__name__)

#: The post-submit work runs on this function's own published alias. It used to name
#: `lambda_client._endpoint.host.split('/')[-1]`, the regional endpoint
#: (`lambda.us-east-1.amazonaws.com`), never a function, so every invoke failed and the
#: synchronous fallback ran inside Meta's data_exchange request.
SELF_FUNCTION = f"{os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'wecare-whatsapp-business-api')}:live"
#: One attempt only: a retried Event invoke can queue the post-submit work twice.
_post_submit_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'),
                                   config=Config(retries={'total_max_attempts': 1}))

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

    # Payment comes only from the PUBLISHED FlowRegistry row (`_get_flow_registry_by_code`).
    # The REVIEW screen's own `payment_required`/`service_fee_amount` used to switch payment on
    # and set the amount when the registry had no row: a price supplied by the customer's
    # client. Paid requests are pay-first now (`paidsr:` tokens, flows/paid_submit_request.py).
    cfg = flow_config or {}
    requires_payment = parse_bool(cfg.get('requiresPayment', DEFAULT_REQUIRES_PAYMENT))
    try:
        payment_amount = (int(cfg.get('paymentAmount') or DEFAULT_PAYMENT_AMOUNT)
                          if requires_payment else 0)
    except (TypeError, ValueError):
        payment_amount = 0  # an unreadable registry amount charges nothing

    flow_name = cfg.get('flowName', FLOW_NAME)
    prefix = cfg.get('submissionPrefix', SUBMISSION_PREFIX)

    logger.info(json.dumps({
        'event': 'sr_review_submit', 'order_id': order_id,
        'subjectLength': len(subject or ''),
        'requiresPayment': requires_payment, 'paymentAmount': payment_amount,
        # Diagnostic only: the screen's own payment flag is never acted on.
        'clientPaymentFlag': data.get('payment_required') == 'true',
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
    # Handed to this function's `live` alias so THANK_YOU returns inside Meta's data_exchange
    # budget. Both branches act on the values computed above and reach the same invoice-engine
    # gates, and the invoice and payment request are deduplicated by `payment_ref_id`.
    try:
        _post_submit_client.invoke(
            FunctionName=SELF_FUNCTION,
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
        return response_payload
    except (ClientError, EndpointConnectionError, ConnectTimeoutError) as e:
        # Refused, or never connected: nothing was queued, so the work runs here instead.
        logger.error(json.dumps({'event': 'sr_post_submit_invoke_failed',
                                 'error': type(e).__name__, 'requestId': request_id}))
    except Exception as e:  # noqa: BLE001 - e.g. a read timeout, after which it may be queued
        # Running the fallback now could confirm (and invoice) twice; leave it to the queue.
        logger.error(json.dumps({'event': 'sr_post_submit_invoke_uncertain',
                                 'error': type(e).__name__, 'requestId': request_id}))
        return response_payload

    # Synchronous fallback, only when the hand-off provably did not happen.
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
    except Exception as e2:  # noqa: BLE001 - the customer already has THANK_YOU
        logger.error(json.dumps({'event': 'sr_post_submit_fallback_failed',
                                 'error': type(e2).__name__, 'requestId': request_id}))

    return response_payload
