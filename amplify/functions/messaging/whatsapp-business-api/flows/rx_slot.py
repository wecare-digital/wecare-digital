"""
RX Slot Flow — Prescription, lab test, and medical visit booking.
Screens: SLOT_FORM → REVIEW → CONFIRM (terminal)
Saves ONE row to FlowSubmissionTable (flowCode WD_RX) carrying the slot's fields.
RxSlotTable was folded into the flow-response table; see `lambda_utils.flow_records`.
"""
import logging
from typing import Dict

from flows.common import (
    get_phone_from_token, find_contact_by_phone,
    get_contact_name, record_completion,
)

logger = logging.getLogger(__name__)

FLOW_CODE = 'WD_RX'


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT → show SLOT_FORM with slot type options."""
    return {
        'screen': 'SLOT_FORM',
        'data': {
            'slot_types': [
                {'id': 'prescription', 'title': 'Prescription Pickup'},
                {'id': 'medical_tourism', 'title': 'Medical Tourism'},
                {'id': 'lab_test', 'title': 'Lab Test'},
                {'id': 'pharmacy', 'title': 'Pharmacy Visit'},
            ],
        }
    }


def handle_slot_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    """SLOT_FORM → REVIEW with collected data."""
    return {
        'screen': 'REVIEW',
        'data': {
            'slot_type': data.get('slot_type', ''),
            'slot_date': data.get('slot_date', ''),
            'slot_time': data.get('slot_time', ''),
            'facility_name': data.get('facility_name', '') or '—',
            'prescription_notes': data.get('prescription_notes', '') or '—',
        }
    }


def handle_review(data: Dict, flow_token: str, request_id: str) -> Dict:
    """REVIEW → save RX slot, return CONFIRM."""
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    name = get_contact_name(contact_id)
    # Derived from the completion key rather than random. A Meta retry of this data_exchange
    # recomputes the same id, and the conditional put inside record_completion refuses the
    # duplicate, so one completion is one Rx slot row.
    from lambda_utils import flow_completion as _fc
    rx_id = _fc.reference_for(
        _fc.completion_key(flow_token, 'REVIEW', data)[0], 'WD-RX')

    # ONE row: the flow response IS the Rx slot booking, with no `ttl`.
    rx_fields = {k: v for k, v in {
        'rxSlotId': rx_id,
        'customerPhone': phone,
        'customerName': name,
        'slotType': data.get('slot_type', ''),
        'slotDate': data.get('slot_date', ''),
        'slotTime': data.get('slot_time', ''),
        'facilityName': data.get('facility_name', ''),
        'prescriptionNotes': data.get('prescription_notes', ''),
    }.items() if v is not None and v != ''}
    result = record_completion(
        flow_code=FLOW_CODE, flow_type='rx_booking', phone=phone,
        contact_id=contact_id, sender_name=name,
        form_data=data, flow_token=flow_token, request_id=request_id,
        screen='REVIEW', submission_number=rx_id, requires_payment=False, status='booked',
        extra=rx_fields, ttl_seconds=0,
    )

    # Only a fresh claim may message the customer. Without this guard a Meta
    # retry of the same completion sent a second confirmation for one submission.
    if result.should_fire_side_effects:
        try:
            from flows.common import send_simple_confirmation
            send_simple_confirmation(phone, flow_token, 'RX Slot Booking', rx_id,
                f'*Type:* {data.get("slot_type", "")}\n*Date:* {data.get("slot_date", "")} at {data.get("slot_time", "")}')
        except Exception:
            pass

    return {
        'screen': 'CONFIRM',
        'data': {
            'rx_slot_id': rx_id,
            'message': f'Your {data.get("slot_type", "RX slot")} on {data.get("slot_date", "")} at {data.get("slot_time", "")} has been booked. We will confirm shortly.',
        }
    }
