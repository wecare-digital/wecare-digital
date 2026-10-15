"""
Enterprise Assist Flow — B2B/corporate support intake.
Screens: INTAKE_FORM → CONFIRM (terminal)
Saves ONE row to FlowSubmissionTable (flowCode WD_ENT) carrying the case's fields.
EnterpriseAssistTable was folded into the flow-response table; see
`lambda_utils.flow_records`.
"""
import logging
from typing import Dict
from flows.common import (
    get_phone_from_token, find_contact_by_phone,
    get_contact_name, record_completion,
)

logger = logging.getLogger(__name__)
FLOW_CODE = 'WD_ENT'


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    return {
        'screen': 'INTAKE_FORM',
        'data': {
            'priorities': [
                {'id': 'normal', 'title': 'Normal'},
                {'id': 'high', 'title': 'High'},
                {'id': 'urgent', 'title': 'Urgent'},
            ],
        }
    }


def handle_intake_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    # Derived from the completion key rather than random. A Meta retry of this data_exchange
    # recomputes the same id, and the conditional put inside record_completion refuses the
    # duplicate, so one completion is one case row.
    from lambda_utils import flow_completion as _fc
    case_id = _fc.reference_for(
        _fc.completion_key(flow_token, 'INTAKE_FORM', data)[0], 'WD-ENT')

    # ONE row: the flow response IS the enterprise case, linked to the shared contact row
    # (the old domain row carried no contactId at all), with no `ttl`.
    case_fields = {k: v for k, v in {
        'caseId': case_id,
        'contactPhone': phone,
        'contactName': data.get('contact_name', ''),
        'contactEmail': data.get('contact_email', ''),
        'accountName': data.get('account_name', ''),
        'subject': data.get('subject', ''),
        'description': data.get('description', ''),
        'priority': data.get('priority', 'normal'),
    }.items() if v is not None and v != ''}
    result = record_completion(
        flow_code=FLOW_CODE, flow_type='enterprise', phone=phone,
        contact_id=contact_id, sender_name=data.get('contact_name', ''),
        form_data=data, flow_token=flow_token, request_id=request_id,
        screen='INTAKE_FORM', submission_number=case_id, requires_payment=False,
        status='open', extra=case_fields, ttl_seconds=0,
    )

    # Only a fresh claim may message the customer. Without this guard a Meta
    # retry of the same completion sent a second confirmation for one submission.
    if result.should_fire_side_effects:
        try:
            from flows.common import send_simple_confirmation
            send_simple_confirmation(phone, flow_token, 'Enterprise Enquiry', case_id,
                f'*Company:* {data.get("account_name", "")}\n*Subject:* {data.get("subject", "")}')
        except Exception:
            pass

    return {
        'screen': 'CONFIRM',
        'data': {
            'case_id': case_id,
            'message': f'Your enterprise enquiry has been submitted. Our team will reach out to {data.get("account_name", "you")} shortly.',
        }
    }
