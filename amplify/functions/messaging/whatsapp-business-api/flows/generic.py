"""
Generic Flow Handler — catch-all for flows without a dedicated module.
Handles: amend_request, track_request, schedule_appointment, rx_slot,
         drop_docs, enterprise_assist, leave_review, order_notes.
Each uses the same WELCOME → FORM → SUCCESS pattern.
Payment config comes from FlowRegistry (most are FREE).
"""
import json
import uuid
import logging
from decimal import Decimal
from typing import Dict

from flows.common import (
    dynamodb, FLOW_SUBMISSIONS_TABLE,
    require_session, get_phone_number_id_for_flow,
    find_contact_by_phone, record_completion,
)

logger = logging.getLogger(__name__)


def handle_welcome(data: Dict, flow_token: str, request_id: str) -> Dict:
    """WELCOME → FORM: pass data forward."""
    return {'screen': 'FORM', 'data': data}


def handle_form(data: Dict, flow_token: str, request_id: str,
                flow_key: str = '') -> Dict:
    """FORM → SUCCESS: save submission and close flow.
    response_payload is set FIRST. The customer comes from a session issued for `flow_key`.
    """
    phone = require_session(flow_token, flow_key).phone
    submission_id = f'WD-{flow_key[:6].upper()}-{uuid.uuid4().hex[:8].upper()}'

    # ── SET SUCCESS RESPONSE FIRST ──
    response_payload = {
        'screen': 'SUCCESS',
        'data': {
            'submission_id': submission_id,
            'message': f'Your {flow_key.replace("_", " ").title()} has been submitted. Reference: {submission_id}',
        }
    }

    # ── Save (non-blocking) ──
    try:
        contact_id = find_contact_by_phone(phone) if phone else ''
        result = record_completion(
            flow_code=flow_key, flow_type='generic_form', phone=phone,
            contact_id=contact_id, sender_name=data.get('name', ''),
            form_data=data, flow_token=flow_token, request_id=request_id,
            submission_number=submission_id,
            requires_payment=False, payment_amount=0, status='submitted',
        )
    except Exception as e:
        logger.warning(f'Generic flow save failed: {e}')

    return response_payload


def handle_any_screen(data: Dict, flow_token: str, request_id: str) -> Dict:
    """Fallback for unknown screens — pass data to SUCCESS."""
    return {'screen': 'SUCCESS', 'data': data}
