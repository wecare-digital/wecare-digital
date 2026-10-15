"""
Appointment Flow — Book consultations and service visits.
Screens: BOOKING_FORM → REVIEW → CONFIRM (terminal)
Saves ONE row to FlowSubmissionTable (flowCode WD_APPT) carrying the appointment's fields.
AppointmentTable was folded into the flow-response table; see `lambda_utils.flow_records`.
"""
import logging
from typing import Dict

from flows.common import (
    get_phone_from_token, find_contact_by_phone,
    get_contact_name, record_completion,
)

logger = logging.getLogger(__name__)

FLOW_CODE = 'WD_APPT'


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT → show BOOKING_FORM with type/location options."""
    return {
        'screen': 'BOOKING_FORM',
        'data': {
            'appointment_types': [
                {'id': 'consultation', 'title': 'Consultation'},
                {'id': 'service_visit', 'title': 'Service Visit'},
                {'id': 'follow_up', 'title': 'Follow-up'},
                {'id': 'other', 'title': 'Other'},
            ],
            'locations': [
                {'id': 'office', 'title': 'Office'},
                {'id': 'virtual', 'title': 'Virtual (Online)'},
                {'id': 'home_visit', 'title': 'Home Visit'},
            ],
        }
    }


def handle_booking_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    """BOOKING_FORM → REVIEW with collected data."""
    return {
        'screen': 'REVIEW',
        'data': {
            'appointment_type': data.get('appointment_type', ''),
            'location': data.get('location', ''),
            'slot_date': data.get('slot_date', ''),
            'slot_time': data.get('slot_time', ''),
            'notes': data.get('notes', '') or '—',
        }
    }


def handle_review(data: Dict, flow_token: str, request_id: str) -> Dict:
    """REVIEW → save appointment, return CONFIRM."""
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    name = get_contact_name(contact_id)
    # Derived from the completion key rather than random. A Meta retry of this data_exchange
    # recomputes the same id, and the conditional put inside record_completion refuses the
    # duplicate, so one completion is one appointment row.
    from lambda_utils import flow_completion as _fc
    apt_id = _fc.reference_for(
        _fc.completion_key(flow_token, 'REVIEW', data)[0], 'WD-APT')

    # ONE row: the flow response IS the appointment. No `ttl` - a booking is a business
    # record the staff appointments page and the SLA no-show sweep both read.
    appointment_fields = {k: v for k, v in {
        'appointmentId': apt_id,
        'customerPhone': phone,
        'customerName': name,
        'appointmentType': data.get('appointment_type', ''),
        'location': data.get('location', ''),
        'slotDate': data.get('slot_date', ''),
        'slotTime': data.get('slot_time', ''),
        'notes': data.get('notes', ''),
    }.items() if v is not None and v != ''}
    result = record_completion(
        flow_code=FLOW_CODE, flow_type='booking', phone=phone,
        contact_id=contact_id, sender_name=name,
        form_data=data, flow_token=flow_token, request_id=request_id,
        screen='REVIEW', submission_number=apt_id, requires_payment=False, status='booked',
        extra=appointment_fields, ttl_seconds=0,
    )

    # Send WhatsApp confirmation
    # Only a fresh claim may message the customer. Without this guard a Meta
    # retry of the same completion sent a second confirmation for one submission.
    if result.should_fire_side_effects:
        try:
            from flows.common import send_simple_confirmation
            send_simple_confirmation(phone, flow_token, 'Appointment Booking', apt_id,
                f'*Type:* {data.get("appointment_type", "")}\n*Date:* {data.get("slot_date", "")} at {data.get("slot_time", "")}')
        except Exception:
            pass

    return {
        'screen': 'CONFIRM',
        'data': {
            'appointment_id': apt_id,
            'message': f'Your {data.get("appointment_type", "appointment")} on {data.get("slot_date", "")} at {data.get("slot_time", "")} has been booked. We will confirm shortly.',
        }
    }
