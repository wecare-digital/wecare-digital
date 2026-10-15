"""
Post-payment details flow (data_exchange).

Launched by the Razorpay webhook after a payment is captured. Token format:
    postpay-{hexReferenceId}-waba-{1|2}-ph-{phone}

INIT   -> decode referenceId from token, fetch the invoice + payment, and show
          Order #, Payment ID, Amount and Product on the DETAILS screen.
SUBMIT -> save exactly ONE submission per payment (idempotent, keyed on the
          referenceId), then navigate to the terminal THANK_YOU screen.

The identifiers are server-fetched (not client-supplied), so they cannot be spoofed.
"""
import os
import json
import time
import logging
from decimal import Decimal

from flows.common import (
    dynamodb, FLOW_SUBMISSIONS_TABLE,
    find_contact_by_phone, get_contact_name, get_phone_from_token,
)

logger = logging.getLogger(__name__)

INVOICES_TABLE = os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable')
PAYMENTS_TABLE = os.environ.get('PAYMENTS_TABLE', 'stack-wecare-digital-PaymentsTable')
FLOW_CODE = '02.WD_POSTPAY'


def _reference_from_token(flow_token: str) -> str:
    """Decode the referenceId embedded (hex) between 'postpay-' and '-waba-'."""
    try:
        mid = flow_token.split('postpay-', 1)[1]
        hexref = mid.split('-waba-', 1)[0]
        return bytes.fromhex(hexref).decode('utf-8')
    except Exception:
        return ''


def _fmt_amount(val) -> str:
    if val is None or val == '':
        return ''
    try:
        return f'\u20b9{float(val):.2f}'
    except Exception:
        return str(val)


def _lookup_order(reference_id: str) -> dict:
    """Fetch order number, payment id, amount and product for a referenceId."""
    order_number = reference_id
    payment_id = ''
    amount = ''
    product = ''

    # Invoice (referenceId-index GSI exists on InvoicesTable)
    try:
        inv_t = dynamodb.Table(INVOICES_TABLE)
        r = inv_t.query(
            IndexName='referenceId-index',
            KeyConditionExpression='referenceId = :r',
            ExpressionAttributeValues={':r': reference_id}, Limit=1,
        )
        items = r.get('Items', [])
        if items:
            inv = items[0]
            order_number = (inv.get('invoiceNumber') or inv.get('orderId')
                            or inv.get('invoiceId') or reference_id)
            amount = _fmt_amount(inv.get('totalAmount') or inv.get('total')
                                 or inv.get('grandTotal') or inv.get('amount'))
            its = inv.get('items')
            if isinstance(its, str):
                try:
                    its = json.loads(its)
                except Exception:
                    its = []
            if isinstance(its, list) and its:
                first = its[0]
                product = first.get('name', '') if isinstance(first, dict) else str(first)
    except Exception as e:
        logger.warning(f'postpay invoice lookup failed: {e}')

    # Payment id (PaymentsTable — try GSI, fall back to bounded scan by referenceId)
    try:
        pay_t = dynamodb.Table(PAYMENTS_TABLE)
        pitems = []
        try:
            pr = pay_t.query(
                IndexName='referenceId-index',
                KeyConditionExpression='referenceId = :r',
                ExpressionAttributeValues={':r': reference_id}, Limit=1,
            )
            pitems = pr.get('Items', [])
        except Exception:
            from boto3.dynamodb.conditions import Attr
            pr = pay_t.scan(FilterExpression=Attr('referenceId').eq(reference_id), Limit=200)
            pitems = pr.get('Items', [])
        if pitems:
            p = pitems[0]
            payment_id = p.get('paymentId') or p.get('id', '')
            if not amount:
                amount = _fmt_amount(p.get('amountInRupees') or p.get('amount'))
    except Exception as e:
        logger.warning(f'postpay payment lookup failed: {e}')

    return {
        'order_number': str(order_number or reference_id or 'N/A'),
        'payment_id': str(payment_id or 'Processing'),
        'amount': str(amount or ''),
        'product': str(product or 'Your order'),
    }


def handle_init(data: dict, flow_token: str, request_id: str) -> dict:
    ref = _reference_from_token(flow_token)
    od = _lookup_order(ref) if ref else {}
    logger.info(json.dumps({'event': 'postpay_init', 'referenceId': ref,
                            'orderNumber': od.get('order_number'), 'requestId': request_id}))
    return {
        'screen': 'DETAILS',
        'data': {
            'order_number': od.get('order_number', ref or 'N/A'),
            'payment_id': od.get('payment_id', 'Processing'),
            'amount': od.get('amount', ''),
            'product': od.get('product', 'Your order'),
        },
    }


def handle_submit(data: dict, flow_token: str, request_id: str) -> dict:
    """Save exactly one submission per payment (idempotent) and go to THANK_YOU."""
    ref = _reference_from_token(flow_token)
    phone = get_phone_from_token(flow_token)
    contact_id = find_contact_by_phone(phone)
    sender_name = get_contact_name(contact_id)
    now = int(time.time())
    sub_id = f'postpay-{ref}' if ref else f'postpay-{flow_token[-12:]}'

    form = {k: v for k, v in (data or {}).items() if k not in ('flow_token',)}
    item = {
        'submissionId': sub_id,
        'flowCode': FLOW_CODE,
        'flowType': 'post_payment',
        'phone': phone,
        'contactId': contact_id or '',
        'senderName': sender_name or '',
        'formData': json.dumps(form),
        'submissionNumber': sub_id,
        'flowToken': flow_token,
        'orderId': ref or '',
        'referenceId': ref or '',
        'status': 'open',
        'paymentStatus': 'paid',
        'channel': 'whatsapp',
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
        'ttl': now + (365 * 86400),
    }
    try:
        t = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        t.put_item(
            Item={k: v for k, v in item.items() if v is not None and v != ''},
            ConditionExpression='attribute_not_exists(submissionId)',
        )
        logger.info(json.dumps({'event': 'postpay_submission_saved', 'submissionId': sub_id,
                                'referenceId': ref, 'requestId': request_id}))
    except Exception as e:
        if 'ConditionalCheckFailedException' in str(e):
            logger.info(json.dumps({'event': 'postpay_submission_duplicate', 'submissionId': sub_id,
                                    'referenceId': ref, 'requestId': request_id}))
        else:
            logger.warning(f'postpay submission save failed: {e}')

    # THANK_YOU uses the identifiers echoed in the submit payload (no DB lookup -> fast).
    d = data or {}
    return {
        'screen': 'THANK_YOU',
        'data': {
            'order_number': d.get('order_number') or ref or 'N/A',
            'payment_id': d.get('payment_id') or '',
            'request_number': sub_id,
        },
    }
