"""
Shared helpers for all flow modules.
Phone resolution, contact lookup, payment, confirmation, submission save.
Every flow imports from here — no flow-specific logic lives here.
"""
import os
import json
import time
import uuid
import boto3
import logging
from decimal import Decimal
from typing import Dict, Optional

logger = logging.getLogger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
SUBMIT_REQUESTS_TABLE = os.environ.get('SUBMIT_REQUESTS_TABLE', 'stack-wecare-digital-SubmitRequestsTable')
FLOW_SUBMISSIONS_TABLE = os.environ.get('FLOW_SUBMISSIONS_TABLE', 'stack-wecare-digital-FlowSubmissionTable')
FLOW_LOGS_TABLE = os.environ.get('FLOW_LOGS_TABLE', 'stack-wecare-digital-FlowLogTable')
OUTBOUND_WHATSAPP_FUNCTION = os.environ.get('OUTBOUND_WHATSAPP_FUNCTION', 'wecare-outbound-whatsapp')
INVOICE_ENGINE_FUNCTION = os.environ.get('INVOICE_ENGINE_FUNCTION', 'wecare-invoice-engine')
DRAFTS_TABLE = os.environ.get('DRAFTS_TABLE', 'stack-wecare-digital-FlowDraftTable')
STATUS_HISTORY_TABLE = os.environ.get('STATUS_HISTORY_TABLE', 'stack-wecare-digital-RequestStatusHistoryTable')

PHONE1_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')
PHONE2_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2', 'phone-number-id-waba-t-direct-1055232054343117')


# ── Phone resolution ──

def get_phone_from_token(flow_token: str) -> str:
    """Extract customer phone from flow_token."""
    if flow_token and '-ph-' in flow_token:
        return flow_token.split('-ph-', 1)[1]
    return ''


def get_phone_number_id_for_flow(flow_token: str) -> str:
    """Determine which WABA phone (Phone 1 or Phone 2) sent this flow.
    Token format: {prefix}-{uuid}-waba-{1|2}-ph-{phone}
    """
    if not flow_token:
        return PHONE1_ID
    if '-waba-' in flow_token:
        try:
            waba_part = flow_token.split('-waba-')[1].split('-')[0]
            return PHONE2_ID if waba_part == '2' else PHONE1_ID
        except (IndexError, ValueError):
            pass
    return PHONE1_ID


# ── Contact lookup ──

def find_contact_by_phone(phone: str) -> str:
    """Look up contactId from Contacts table by phone."""
    if not phone:
        return ''
    try:
        clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        with_plus = f'+{clean}'
        table = dynamodb.Table(CONTACTS_TABLE)
        for variant in [with_plus, clean]:
            try:
                resp = table.query(
                    IndexName='phone-index',
                    KeyConditionExpression='phone = :p',
                    ExpressionAttributeValues={':p': variant},
                    Limit=1, ProjectionExpression='id',
                )
                items = resp.get('Items', [])
                if items:
                    return items[0].get('id', '')
            except Exception:
                pass
    except Exception as e:
        logger.warning(f'Contact lookup failed: {e}')
    return ''


def get_contact_name(contact_id: str) -> str:
    """Get contact name by ID."""
    if not contact_id:
        return ''
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        resp = table.get_item(Key={'id': contact_id}, ProjectionExpression='#n',
                              ExpressionAttributeNames={'#n': 'name'})
        return resp.get('Item', {}).get('name', '')
    except Exception:
        return ''


# ── Submission save ──

def record_completion(flow_code: str, flow_type: str, phone: str,
                      contact_id: str, sender_name: str, form_data: Dict,
                      flow_token: str, request_id: str,
                      screen: str = '',
                      submission_number: str = '',
                      requires_payment: bool = False,
                      payment_amount: int = 0,
                      payment_ref_id: str = '',
                      status: str = 'open',
                      reference_prefix: str = ''):
    """Claim this completion once, and say whether THIS caller won.

    The single writer, shared with the inbound Lambda:
    `lambda_utils.flow_completion.claim_completion`. Callers must branch on
    `result.should_fire_side_effects` before sending a message, creating an invoice or
    charging anything.

    `submission_number` is now an override, not the norm. Every caller used to mint a
    fresh random one, which is precisely why a retry produced a second row - and a second
    request number shown to the same customer for the same request. The derived default is
    a function of the flow token, so a retry lands on the row that already exists.

    **This function never raises.** Every caller assigns its result inside a `try:` and then
    branches on it afterwards, so an exception here would leave `result` unbound and turn a
    claim failure into a NameError - an error screen for the customer instead of their
    confirmation. Returning an `error` result keeps the flow's terminal screen intact while
    still refusing the side effects.
    """
    from lambda_utils import flow_completion

    try:
        return _record_completion(
            flow_completion, flow_code=flow_code, flow_type=flow_type, phone=phone,
            contact_id=contact_id, sender_name=sender_name, form_data=form_data,
            flow_token=flow_token, request_id=request_id, screen=screen,
            submission_number=submission_number, requires_payment=requires_payment,
            payment_amount=payment_amount, payment_ref_id=payment_ref_id,
            status=status, reference_prefix=reference_prefix)
    except Exception as e:  # noqa: BLE001 - a claim failure must not become a NameError
        logger.error(json.dumps({
            'event': 'flow_completion_unexpected_error',
            'flowCode': flow_code, 'error': str(e)[:200], 'requestId': request_id,
        }))
        return flow_completion.CompletionResult(
            status='error', submission_id='', reference='', key='', error=str(e)[:200])


def _record_completion(flow_completion, *, flow_code, flow_type, phone, contact_id,
                       sender_name, form_data, flow_token, request_id, screen,
                       submission_number, requires_payment, payment_amount,
                       payment_ref_id, status, reference_prefix):
    """The body of `record_completion`. Split out so the wrapper above stays total."""
    result = flow_completion.claim_completion(
        flow_token=flow_token,
        screen=screen,
        flow_code=flow_code,
        flow_type=flow_type,
        phone=phone,
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=form_data if isinstance(form_data, dict) else {},
        reference_prefix=reference_prefix or f'WD-{(flow_code or "")[:6]}',
        submission_id=submission_number or None,
        requires_payment=requires_payment,
        payment_amount=payment_amount,
        payment_ref_id=payment_ref_id,
        status=status,
        request_id=request_id,
    )

    # Mirror a fresh completion into the CRM. Best-effort: the FlowSubmission row is the
    # system of record for the submission, the lead is a projection of it.
    if result.created and contact_id:
        fd = form_data if isinstance(form_data, dict) else {}
        flow_completion.capture_crm_lead(
            result,
            contact_id=contact_id,
            flow_token=flow_token,
            subject=fd.get('subject', ''),
            detail=fd.get('description', ''),
            phone=phone,
            name=sender_name,
            email=fd.get('email', ''),
            amount_paise=payment_amount if requires_payment else None,
            request_id=request_id,
        )
    return result


def save_flow_submission(flow_code: str, flow_type: str, phone: str,
                         contact_id: str, sender_name: str, form_data: Dict,
                         flow_token: str, request_id: str,
                         submission_number: str = '',
                         requires_payment: bool = False,
                         payment_amount: int = 0,
                         payment_ref_id: str = '',
                         status: str = 'open',
                         screen: str = '') -> Dict:
    """Backwards-compatible wrapper. Prefer `record_completion`.

    Kept because nine flow modules call it. It now goes through the idempotent writer, so
    every one of those nine gets the conditional put without being edited - but it still
    returns a bare dict, so a caller using this form **cannot tell a duplicate from a fresh
    claim**. That is the exact blindness that let a retry send a second payment link.

    Any caller with a side effect must use `record_completion` and check
    `should_fire_side_effects`. This wrapper returns `{}` for both duplicate and error so
    the legacy `if not item: return` checks keep behaving as they did.
    """
    result = record_completion(
        flow_code=flow_code, flow_type=flow_type, phone=phone, contact_id=contact_id,
        sender_name=sender_name, form_data=form_data, flow_token=flow_token,
        request_id=request_id, screen=screen, submission_number=submission_number,
        requires_payment=requires_payment, payment_amount=payment_amount,
        payment_ref_id=payment_ref_id, status=status,
    )
    return result.item if result.created else {}


# ── Payment ──

def send_payment(phone: str, phone_number_id: str, order_id: str, subject: str,
                 request_id: str, request_number: str, payment_ref_id: str,
                 payment_amount_paise: int, flow_name: str = 'Service Request',
                 preferred_gateway: str = '', payment_config_name: str = '') -> str:
    """Create invoice + send payment link. Returns invoice number or empty string.
    ONLY call this for flows that require payment. Amount comes from flow config.
    """
    if not payment_amount_paise or not phone:
        logger.error(json.dumps({
            'event': 'payment_skipped_no_amount_or_phone',
            'paymentAmount': payment_amount_paise, 'phone': bool(phone),
            'requestId': request_id,
        }))
        return ''

    ref_id = payment_ref_id or f'WD-PAY-{uuid.uuid4().hex[:8].upper()}'
    contact_id = find_contact_by_phone(phone)
    sender_name = get_contact_name(contact_id)
    amount_rupees = payment_amount_paise / 100

    invoice_body = {
        'referenceId': ref_id,
        'customerPhone': phone,
        'customerName': sender_name,
        'contactId': contact_id or '',
        'orderId': order_id,
        'entryPoint': 'flow_payment',
        'purpose': f'{flow_name}: {subject}' if subject else flow_name,
        'notes': f'Request #{request_number}' if request_number else '',
        'gstin': '19AAFFW7196L1Z8',
        'gstRate': 18,
        'items': [{'name': flow_name, 'amount': amount_rupees, 'quantity': 1, 'gstRate': 18}],
    }
    if preferred_gateway:
        invoice_body['preferredGateway'] = preferred_gateway
    if payment_config_name:
        invoice_body['paymentConfiguration'] = payment_config_name

    try:
        resp = lambda_client.invoke(
            FunctionName=INVOICE_ENGINE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'requestContext': {'http': {'method': 'POST'}},
                'rawPath': '/invoices',
                'body': json.dumps(invoice_body),
            })
        )
        result = json.loads(resp['Payload'].read())
        body = json.loads(result.get('body', '{}'))
        invoice_id = body.get('invoiceId', '')
        invoice_number = body.get('invoiceNumber', '')

        if not invoice_id:
            logger.error(json.dumps({'event': 'invoice_create_failed', 'response': body, 'requestId': request_id}))
            return ''

        # Send payment link
        send_phone_id = phone_number_id or PHONE1_ID
        send_resp = lambda_client.invoke(
            FunctionName=INVOICE_ENGINE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'requestContext': {'http': {'method': 'POST'}},
                'rawPath': '/invoices/send-payment-link',
                'body': json.dumps({'invoiceId': invoice_id, 'phoneNumberId': send_phone_id}),
            })
        )
        # The status is READ, not discarded. This used to log `payment_link_sent` after a
        # RequestResponse invoke whose status it never inspected, so a readiness refusal was
        # recorded as a successful send — and the invoice path is readiness-gated now, which
        # makes a refusal a legitimate and expected outcome rather than an anomaly.
        send_result = json.loads(send_resp['Payload'].read())
        send_status = int(send_result.get('statusCode') or 0)
        if 200 <= send_status < 300:
            logger.info(json.dumps({
                'event': 'payment_link_sent', 'invoiceNumber': invoice_number,
                'phoneNumberId': send_phone_id, 'amount': payment_amount_paise,
                'statusCode': send_status, 'requestId': request_id,
            }))
        else:
            send_body = send_result.get('body')
            if isinstance(send_body, str):
                try:
                    send_body = json.loads(send_body)
                except (ValueError, TypeError):
                    send_body = {}
            logger.error(json.dumps({
                'event': 'payment_link_refused', 'invoiceNumber': invoice_number,
                'phoneNumberId': send_phone_id, 'statusCode': send_status,
                # A stable refusal code only, never a provider or request-body string.
                'code': str((send_body or {}).get('code')
                            or (send_body or {}).get('error') or '')[:64],
                'requestId': request_id,
            }))
        return invoice_number
    except Exception as e:
        logger.error(json.dumps({'event': 'payment_error', 'error': str(e), 'requestId': request_id}))
        return ''


# ── Confirmation message ──

def send_confirmation(phone: str, phone_number_id: str, request_id: str,
                      flow_name: str, request_number: str,
                      requires_payment: bool = False, payment_amount: int = 0,
                      payment_ref_id: str = '', invoice_number: str = '',
                      order_id: str = '', subject: str = ''):
    """Send WhatsApp text confirmation after flow completes."""
    if not phone:
        return
    send_phone_id = phone_number_id or PHONE1_ID
    if not phone_number_id:
        logger.error(json.dumps({
            'event': 'confirmation_no_phone_id', 'requestId': request_id,
        }))

    if requires_payment and payment_amount:
        amt = f'₹{payment_amount / 100:.0f}' if payment_amount >= 100 else f'₹{payment_amount}'
        inv = f'*Invoice:* {invoice_number}\n' if invoice_number else ''
        msg = (
            f'✅ *{flow_name} Submitted Successfully*\n\n'
            f'*Request No:* {request_number}\n{inv}'
            f'*Payment Ref:* {payment_ref_id}\n*Amount:* {amt}\n'
            f'*Order:* {order_id}\n*Subject:* {subject}\n\n'
            'Please complete the payment using the payment link sent above ⬆️\n'
            'Our team will review your request within 24 hours.\n\n'
            '_Thank you for choosing WECARE.DIGITAL_'
        )
    else:
        msg = (
            f'✅ *{flow_name} Submitted Successfully*\n\n'
            f'*Reference:* {request_number}\n*Subject:* {subject}\n\n'
            'Our team will review your submission within 24 hours.\n\n'
            '_Thank you for choosing WECARE.DIGITAL_'
        )

    try:
        lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'body': json.dumps({
                'recipientPhone': phone, 'phoneNumberId': send_phone_id, 'content': msg,
            })})
        )
        logger.info(json.dumps({
            'event': 'confirmation_sent', 'flowName': flow_name,
            'phoneNumberId': send_phone_id, 'requestId': request_id,
        }))
    except Exception as e:
        logger.error(f'Confirmation send failed: {e}')


def send_simple_confirmation(phone: str, flow_token: str, flow_name: str,
                             reference: str, details: str = ''):
    """Send a simple WhatsApp text confirmation for free flows (no payment)."""
    if not phone:
        return
    from flows.common import get_phone_number_id_for_flow
    phone_id = get_phone_number_id_for_flow(flow_token) if flow_token else PHONE1_ID
    detail_line = f'\n{details}' if details else ''
    msg = (
        f'✅ *{flow_name} — Confirmed*\n\n'
        f'*Reference:* {reference}{detail_line}\n\n'
        'Our team will follow up if needed.\n\n'
        '_Thank you for choosing WECARE.DIGITAL_'
    )
    try:
        lambda_client.invoke(
            FunctionName=OUTBOUND_WHATSAPP_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'body': json.dumps({
                'recipientPhone': phone, 'phoneNumberId': phone_id, 'content': msg,
            })})
        )
    except Exception as e:
        logger.warning(f'Simple confirmation failed: {e}')


# ── Flow log ──

def log_flow_event(flow_token: str, phone: str, action: str, screen: str,
                   data: dict, request_id: str):
    """Log a flow interaction for audit trail."""
    try:
        now = int(time.time())
        table = dynamodb.Table(SUBMIT_REQUESTS_TABLE)
        item = {
            'id': f'flog-{uuid.uuid4().hex[:12]}',
            'type': 'flow_log',
            'flowToken': flow_token,
            'phone': phone,
            'action': action,
            'screen': screen,
            'dataKeys': list(data.keys()) if data else [],
            'requestId': request_id,
            'createdAt': Decimal(str(now)),
        }
        if data:
            try:
                item['flowData'] = json.dumps(data, default=str)
            except Exception:
                pass
        table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
    except Exception as e:
        logger.warning(f'Flow log write failed: {e}')


# ── Draft save / restore ──

def save_draft(phone: str, flow_code: str, screen: str, form_data: Dict) -> bool:
    """Save flow draft so user can resume later. Key: {phone}#{flowCode}. TTL: 7 days."""
    try:
        now = int(time.time())
        table = dynamodb.Table(DRAFTS_TABLE)
        table.put_item(Item={
            'draftKey': f'{phone}#{flow_code}',
            'phone': phone,
            'flowCode': flow_code,
            'screen': screen,
            'formData': json.dumps(form_data) if isinstance(form_data, dict) else str(form_data),
            'updatedAt': Decimal(str(now)),
            'ttl': now + (7 * 86400),
        })
        return True
    except Exception as e:
        logger.warning(f'Draft save failed: {e}')
        return False


def restore_draft(phone: str, flow_code: str) -> Optional[Dict]:
    """Restore a saved draft. Returns {screen, formData} or None."""
    try:
        table = dynamodb.Table(DRAFTS_TABLE)
        resp = table.get_item(Key={'draftKey': f'{phone}#{flow_code}'})
        item = resp.get('Item')
        if not item:
            return None
        form_data = item.get('formData', '{}')
        try:
            form_data = json.loads(form_data) if isinstance(form_data, str) else form_data
        except Exception:
            form_data = {}
        return {'screen': item.get('screen', ''), 'formData': form_data}
    except Exception as e:
        logger.warning(f'Draft restore failed: {e}')
        return None


def clear_draft(phone: str, flow_code: str) -> bool:
    """Delete a draft after successful submission."""
    try:
        table = dynamodb.Table(DRAFTS_TABLE)
        table.delete_item(Key={'draftKey': f'{phone}#{flow_code}'})
        return True
    except Exception:
        return False


# ── Status history ──

def append_status_history(submission_id: str, order_id: str,
                          old_status: str, new_status: str,
                          changed_by: str = 'system', notes: str = '') -> bool:
    """Append a status change to RequestStatusHistoryTable for audit trail."""
    try:
        now = int(time.time())
        table = dynamodb.Table(STATUS_HISTORY_TABLE)
        table.put_item(Item={
            'historyId': f'hist-{uuid.uuid4().hex[:12]}',
            'submissionId': submission_id,
            'orderId': order_id,
            'oldStatus': old_status,
            'newStatus': new_status,
            'changedBy': changed_by,
            'notes': notes,
            'changedAt': Decimal(str(now)),
        })
        return True
    except Exception as e:
        logger.warning(f'Status history write failed: {e}')
        return False
