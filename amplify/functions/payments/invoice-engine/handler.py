"""
Invoice Engine Lambda Function

Purpose: Unified invoice service for all 3 payment entry points
- Create invoices from payments
- Generate invoice image (PNG) and PDF
- Internal GST-compliant invoice sequencing
- Admin CRUD operations

DynamoDB Tables:
- stack-wecare-digital-InvoicesTable
- stack-wecare-digital-InvoiceItemsTable
- stack-wecare-digital-InvoiceSequenceTable
- stack-wecare-digital-InvoiceAssetsTable
- stack-wecare-digital-InvoiceDeliveryLogTable

S3 Bucket: wecare-digital-get  (was app.wecare.digital until it was deleted 2026-09-28)
Prefix: secure/stack/invoices/  (GATED - moved off the public `o/` root 2026-09-30, because a
        rendered invoice carries the customer's name, address, amount and GST breakdown.
        Rendered invoices are handed out as short-lived presigned URLs; WhatsApp delivery does
        not use a URL at all, it uploads the bytes to Meta.)
"""

import os
import json
import uuid
import time
import logging
import boto3
import io
from typing import Dict, Any, Optional, List
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.logging import get_logger
from lambda_utils.privacy import mask_phone  # a full number must never reach CloudWatch
from lambda_utils import media_paths
# Aliased: `payment_status` is a local parameter in the invoice renderers below, holding the raw
# stored word. `pay_status` is the module that says what the word means.
from lambda_utils import payment_status as pay_status
# Attribution, not mechanics: which surface the order was placed from. One module owns the two
# literals and the one total coercion, so the three render sites below cannot disagree about what
# `channel` means - the same discipline `pay_status` applies to payment words.
from lambda_utils.ecommerce import order_channel
# The PUBLIC customer id, and the validator that keeps a junk one off a tax invoice. Only
# `is_customer_uuid` and `ATTRIBUTE` are used here: the engine NEVER mints one, the same rule
# that stops a renderer minting an invoice number.
from lambda_utils.identity import customer_uuid

logger = get_logger(__name__)

IST_OFFSET = 5 * 3600 + 30 * 60  # UTC+5:30

def _ist_strftime(fmt: str, epoch) -> str:
    """Format epoch timestamp in IST (UTC+5:30)."""
    return time.strftime(fmt, time.gmtime(int(epoch) + IST_OFFSET))

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')
lambda_client = boto3.client('lambda', region_name='us-east-1')

INVOICES_TABLE = os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable')
INVOICE_ITEMS_TABLE = os.environ.get('INVOICE_ITEMS_TABLE', 'stack-wecare-digital-InvoiceItemsTable')
INVOICE_SEQ_TABLE = os.environ.get('INVOICE_SEQ_TABLE', 'stack-wecare-digital-InvoiceSequenceTable')
INVOICE_ASSETS_TABLE = os.environ.get('INVOICE_ASSETS_TABLE', 'stack-wecare-digital-InvoiceAssetsTable')
INVOICE_DELIVERY_TABLE = os.environ.get('INVOICE_DELIVERY_TABLE', 'stack-wecare-digital-InvoiceDeliveryLogTable')
PAYMENTS_TABLE = os.environ.get('PAYMENTS_TABLE', 'stack-wecare-digital-PaymentsTable')
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
# Keys in this handler are rooted, never bare. See lambda_utils/media_paths: the merge moved
# `<X>` to `o/<X>`, so an un-rooted key read one level above the data and returned NoSuchKey —
# which is exactly what happened to the logo and the font. Those shared assets stay PUBLIC and
# are still composed with `media_paths.public` at their call sites.
#
# The invoice output does not. A rendered invoice carries the customer's name, address, the
# amount and the GST breakdown, and `o/` is served by CloudFront with no authentication — so a
# public key here is an unlisted-but-public disclosure: safe from enumeration, not safe once a
# URL leaks. It moved to the gated root, and the timing is the reason it was cheap: measured at
# the time of the change, `o/stack/invoices/` held **0 objects** and `InvoicesTable` held **0
# rows**, so there was nothing to migrate. Once an invoice URL has been sent, it cannot be
# retracted — the same argument media_paths records for the 61 approved WhatsApp template URLs.
#
# Delivery is unaffected: `send_invoice_whatsapp` passes `mediaFile: s3_key` to
# outbound-whatsapp, which reads the object and uploads the bytes to Meta. Meta never fetches
# an invoice by URL, so the gated prefix costs nothing on the path that matters.
INVOICE_PREFIX = media_paths.secure('stack/invoices/')
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''

# Company details for invoice
# GSTIN/PAN appear on issued tax invoices. The PAN is embedded in the GSTIN at
# characters 3-12, so the two MUST stay consistent:
#   19 AAFFW7196L 1 Z 8  ->  state 19 (West Bengal), PAN AAFFW7196L
# Env vars allow override without a redeploy.
COMPANY = {
    'name': 'WECARE.DIGITAL',
    # The registered legal name printed as the invoice heading (owner mockup 2026-10-07).
    # `name` stays the brand, shown as the fixed "Brand: WECARE.DIGITAL" line beneath it.
    'legal_name': 'WECARE.DIGITAL BHARATWORKS',
    'gstin': os.environ.get('COMPANY_GSTIN', '19AAFFW7196L1Z8'),
    'pan': os.environ.get('COMPANY_PAN', 'AAFFW7196L'),
    'address': 'The W.B.S.I.D.C. Building, Unit 1/20, 81/2/7, Phears Ln, Kolkata, WB 700012',
    'email': 'one@wecare.digital',
    'phone': '+91 93309 94400',
    'website': 'https://wecare.digital',
    'logo_s3_key': media_paths.public('stream/media/m/wecare-digital.png'),
    # `paid_icon_s3_key` was removed on 2026-09-28. It was read by nothing - a repo-wide
    # search found the definition and zero uses - and it named `stream/media/m/paid.png`,
    # which has no object AND no version history in this bucket, so it was never migrated
    # and probably never existed. A config key pointing at a file that cannot be fetched,
    # which nothing fetches, is the exact shape of the drift this audit was chasing; a
    # future PAID stamp should be added back with a reader in the same change.
}


def _load_logo_bytes() -> Optional[bytes]:
    """Load company logo from S3 with /tmp cache for Lambda warm starts."""
    cache_path = '/tmp/_logo_cache.png'
    try:
        with open(cache_path, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        pass
    try:
        obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=COMPANY['logo_s3_key'])
        data = obj['Body'].read()
        try:
            with open(cache_path, 'wb') as f:
                f.write(data)
        except Exception as _e:
            logger.debug(f"Logo cache write failed: {_e}")
        return data
    except Exception as e:
        logger.warning(f"Logo load error: {e}")
        return None


def _load_s3_image(key: str):
    """Load an image from S3 as PIL Image (RGBA) with /tmp cache."""
    import hashlib
    # Defensive: this is the shared read path for every image in the invoice, so rooting
    # here means a caller passing a legacy un-rooted key still finds the object.
    key = media_paths.canonical(key)
    cache_path = f"/tmp/_s3img_{hashlib.md5(key.encode()).hexdigest()}.png"
    try:
        from PIL import Image as PILImage
        return PILImage.open(cache_path).convert('RGBA')
    except Exception as _e:
        logger.debug(f"S3 image cache miss: {_e}")
    try:
        from PIL import Image as PILImage
        obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=key)
        data = obj['Body'].read()
        img = PILImage.open(io.BytesIO(data)).convert('RGBA')
        try:
            img.save(cache_path, 'PNG')
        except Exception as _e:
            logger.debug(f"S3 image cache write failed: {_e}")
        return img
    except Exception as e:
        logger.warning(f"S3 image load error ({key}): {e}")
        return None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route invoice engine requests."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')

    from lambda_utils.middleware import require_auth
    required_role = 'Admin' if method in ('POST', 'PUT', 'DELETE') else None
    _auth = require_auth(event, required_role=required_role)
    if _auth is not None:
        return _auth

    path = event.get('rawPath', event.get('path', ''))
    params = event.get('queryStringParameters') or {}
    path_params = event.get('pathParameters') or {}

    logger.info(json.dumps({'event': 'invoice_engine', 'method': method, 'path': path, 'requestId': request_id}))

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    try:
        # POST /invoices with _action=clear-all — body-based trigger for cleanup via existing route
        if method == 'POST' and body.get('_action') == 'clear-all':
            return clear_all_invoice_data(request_id)

        # POST /invoices/from-payment — create from payment ID (check BEFORE generic POST)
        if method == 'POST' and 'from-payment' in path:
            return create_invoice_from_payment(body, request_id)

        # POST /invoices/send-pending-by-phone — find & send all pending invoices for a phone
        if method == 'POST' and 'send-pending-by-phone' in path:
            return send_pending_by_phone(body, request_id)

        # POST /invoices/next-sequence — get next invoice number (admin)
        if method == 'POST' and 'next-sequence' in path:
            return get_next_sequence_preview(body, request_id)

        # POST /invoices/{id}/generate-image
        if method == 'POST' and 'generate-image' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            return generate_invoice_image(inv_id, request_id)

        # POST /invoices/{id}/generate-pdf
        if method == 'POST' and 'generate-pdf' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            return generate_invoice_pdf(inv_id, request_id)

        # POST /invoices/{id}/send-whatsapp
        if method == 'POST' and 'send-whatsapp' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            phone = body.get('toWhatsAppNumber')
            phone_number_id = body.get('phoneNumberId')
            return send_invoice_whatsapp(inv_id, phone, phone_number_id, request_id)

        # POST /invoices/{id}/send-payment-link — send WhatsApp interactive payment message
        if method == 'POST' and 'send-payment-link' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            phone_number_id = body.get('phoneNumberId')
            payment_configuration = body.get('paymentConfiguration', '')
            return send_payment_link(inv_id, phone_number_id, payment_configuration, request_id)

        # POST /invoices/{id}/cancel — cancel/void an invoice
        if method == 'POST' and 'cancel' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            reason = body.get('reason', '')
            return cancel_invoice(inv_id, reason, request_id)

        # POST /invoices/{id}/remark — add remark/refund/credit note
        if method == 'POST' and 'remark' in path:
            inv_id = path_params.get('invoiceId') or body.get('invoiceId')
            return add_remark(inv_id, body, request_id)

        # DELETE /invoices/clear-all — wipe all invoice-related tables (admin cleanup)
        if method == 'DELETE' and 'clear-all' in path:
            return clear_all_invoice_data(request_id)

        # POST /invoices/clear-all — alternative POST route for clear-all (when DELETE not in API GW)
        if method == 'POST' and 'clear-all' in path:
            return clear_all_invoice_data(request_id)

        # DELETE /invoices/{id} — hard delete invoice + adjust sequence
        if method == 'DELETE' and path_params.get('invoiceId'):
            return delete_invoice(path_params['invoiceId'], body, request_id)

        # POST /invoices — create invoice (generic, must be LAST POST check)
        if method == 'POST':
            return create_invoice(body, request_id)

        # PUT /invoices/{id} — update invoice
        if method == 'PUT' and path_params.get('invoiceId'):
            return update_invoice(path_params['invoiceId'], body, request_id)

        # GET /invoices/{id}/delivery-log
        if method == 'GET' and 'delivery-log' in path:
            inv_id = path_params.get('invoiceId')
            return get_delivery_log(inv_id, request_id)

        # GET /invoices — list
        if method == 'GET' and not path_params.get('invoiceId'):
            return list_invoices(params, request_id)

        # GET /invoices/{id} — get single
        if method == 'GET' and path_params.get('invoiceId'):
            return get_invoice(path_params['invoiceId'], request_id)

        return _resp(405, {'error': 'Method not allowed'})

    except Exception as e:
        logger.error(json.dumps({'event': 'invoice_engine_error', 'error': str(e), 'requestId': request_id}))
        return _resp(500, {'error': str(e)})


# ─── Invoice Sequencing (GST-compliant, internal only) ───

class InvoiceSequenceUnavailable(RuntimeError):
    """The GST invoice sequence could not be advanced.

    Raised instead of returning a substitute number. See _get_next_invoice_number.
    """


def _get_next_invoice_number(fy: str = None) -> str:
    """Generate next sequential invoice number. Format: WD/FY/NNNNN

    Raises InvoiceSequenceUnavailable if the counter cannot be advanced.

    This used to fall back to `WD-PAY-TEMP-<uuid>`, which put a non-sequential
    number into the GST series. Under Rule 46(b) an invoice number has to be part
    of a consecutive series for the financial year; a uuid is not, so the fallback
    did not produce a degraded invoice, it produced an invalid one - and it did so
    silently, at exactly the moment the system had lost the ability to tell what
    the next number should be. Nothing downstream could distinguish it either,
    because it was returned as an ordinary success.

    Failing here is recoverable: the caller returns 503, the client retries, and
    no document is issued. Issuing the wrong number is not recoverable, because a
    GST invoice number cannot be reassigned once it has been sent to a customer.
    """
    if not fy:
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fy = f"{year}-{year+1}" if month >= 4 else f"{year-1}-{year}"

    table = dynamodb.Table(INVOICE_SEQ_TABLE)
    try:
        resp = table.update_item(
            Key={'fy': fy},
            UpdateExpression='SET last_seq = if_not_exists(last_seq, :zero) + :inc, prefix = if_not_exists(prefix, :pfx), updated_at = :now',
            ExpressionAttributeValues={':zero': 0, ':inc': 1, ':pfx': 'WD', ':now': int(time.time())},
            ReturnValues='UPDATED_NEW',
        )
        seq = int(resp['Attributes']['last_seq'])
        prefix = resp['Attributes'].get('prefix', 'WD')
        fy_short = fy.replace('20', '').replace('-', '')
        return f"{prefix}/{fy_short}/{seq:05d}"
    except Exception as e:
        logger.error(json.dumps({
            'event': 'invoice_sequence_unavailable',
            'fy': fy,
            'table': INVOICE_SEQ_TABLE,
            'error': str(e)[:300],
        }))
        raise InvoiceSequenceUnavailable(
            f"Could not advance the invoice sequence for FY {fy}"
        ) from e


def get_next_sequence_preview(body: Dict, request_id: str) -> Dict:
    """Preview next invoice number without incrementing."""
    fy = body.get('fy')
    if not fy:
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fy = f"{year}-{year+1}" if month >= 4 else f"{year-1}-{year}"

    table = dynamodb.Table(INVOICE_SEQ_TABLE)
    try:
        resp = table.get_item(Key={'fy': fy})
        item = resp.get('Item', {})
        last = int(item.get('last_seq', 0))
        prefix = item.get('prefix', 'WD')
        fy_short = fy.replace('20', '').replace('-', '')
        next_num = f"{prefix}/{fy_short}/{last+1:05d}"
        return _resp(200, {'nextInvoiceNumber': next_num, 'fy': fy, 'lastSeq': last})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ─── Create Invoice ───

def create_invoice(body: Dict, request_id: str) -> Dict:
    """Create a new invoice from direct input. Includes deduplication by referenceId/paymentId."""
    now = int(time.time())

    # ── Deduplication: check if invoice already exists for this referenceId or paymentId ──
    reference_id = body.get('referenceId', '')
    payment_id = body.get('paymentId', '')
    table = dynamodb.Table(INVOICES_TABLE)

    if reference_id or payment_id:
        try:
            filter_parts = []
            expr_values = {}
            if reference_id:
                filter_parts.append('referenceId = :ref')
                expr_values[':ref'] = reference_id
            if payment_id:
                filter_parts.append('paymentId = :pid')
                expr_values[':pid'] = payment_id

            filter_expr = ' OR '.join(filter_parts)
            # Full pagination to avoid DynamoDB Limit bug (Limit = items evaluated, not returned)
            existing = []
            scan_kwargs = {'FilterExpression': filter_expr, 'ExpressionAttributeValues': expr_values}
            while True:
                result = table.scan(**scan_kwargs)
                existing.extend(result.get('Items', []))
                if existing or 'LastEvaluatedKey' not in result:
                    break
                scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']

            if existing:
                inv = existing[0]
                existing_id = inv.get('invoiceId', '')

                # If caller says this is now paid, update the existing invoice status.
                #
                # Two axes, and only one of them is the payment vocabulary. `status` is the
                # document lifecycle (created -> sent -> paid -> cancelled) so `'paid'` is its own
                # correct literal; `paymentStatus` is what the money did, so it goes canonical.
                #
                # The original demanded `incoming_ps == 'captured'` exactly, which meant a caller
                # sending the equally valid `paymentStatus='paid'` satisfied neither branch - the
                # invoice stayed unpaid, permanently, with no error anywhere.
                incoming_status = body.get('status', '')
                incoming_ps = body.get('paymentStatus', '')
                if (incoming_status == 'paid'
                        and pay_status.canonical(incoming_ps) == pay_status.CAPTURED
                        and inv.get('status') != 'paid'):
                    try:
                        table.update_item(
                            Key={'invoiceId': existing_id},
                            UpdateExpression='SET #st = :st, #ps = :ps, #pa = :pa, #ua = :now',
                            ExpressionAttributeNames={'#st': 'status', '#ps': 'paymentStatus', '#pa': 'paidAt', '#ua': 'updatedAt'},
                            ExpressionAttributeValues={
                                ':st': 'paid', ':ps': 'captured',
                                ':pa': body.get('paidAt', now), ':now': now,
                            },
                        )
                        logger.info(json.dumps({
                            'event': 'invoice_dedup_status_updated',
                            'invoiceId': existing_id,
                            'newStatus': 'paid',
                            'requestId': request_id,
                        }))
                    except Exception as upd_err:
                        logger.warning(json.dumps({
                            'event': 'invoice_dedup_status_update_error',
                            'invoiceId': existing_id,
                            'error': str(upd_err),
                            'requestId': request_id,
                        }))

                logger.info(json.dumps({
                    'event': 'invoice_dedup_hit',
                    'existingInvoiceId': existing_id,
                    'referenceId': reference_id,
                    'paymentId': payment_id,
                    'requestId': request_id,
                }))
                return _resp(200, {
                    'invoiceId': existing_id,
                    'invoiceNumber': inv.get('invoiceNumber', ''),
                    'total': float(inv.get('total', 0)),
                    'referenceId': inv.get('referenceId', ''),
                    'deduplicated': True,
                })
        except Exception as dedup_err:
            logger.warning(json.dumps({
                'event': 'invoice_dedup_check_error',
                'error': str(dedup_err),
                'requestId': request_id,
            }))

    # ── Atomic claim, so a racing duplicate cannot consume a GST invoice number ──
    #
    # The scan above is the only dedup there was, and a DynamoDB scan is eventually
    # consistent: razorpay-webhook and inbound-whatsapp-handler both invoke this for the
    # same payment, both can scan and miss, and both then insert. `invoiceId` was a fresh
    # uuid4, so the `attribute_not_exists(invoiceId)` on the final put never fired.
    #
    # That mattered more than an ordinary duplicate row, because `_get_next_invoice_number`
    # IS atomic - the loser would have burned a real sequential number out of the GST
    # series. A gap in that series is a compliance artifact, not just untidy data.
    #
    # Deriving `invoiceId` from (referenceId, paymentId) makes the existing condition
    # load-bearing, and claiming a minimal row BEFORE touching the sequence means the
    # loser never increments it. `invoiceId` is opaque to every caller - it is a foreign
    # key in InvoiceItems/InvoiceAssets and an identifier in responses - so deriving it
    # changes no contract.
    dedup_source = reference_id or payment_id
    if dedup_source:
        import hashlib as _hashlib
        invoice_id = 'inv-' + _hashlib.sha256(
            f'invoice\x1f{reference_id}\x1f{payment_id}'.encode('utf-8')
        ).hexdigest()[:32]
        try:
            table.put_item(
                Item={'invoiceId': invoice_id, 'status': 'claiming', 'createdAt': now},
                ConditionExpression='attribute_not_exists(invoiceId)',
            )
        except Exception as claim_err:
            if 'ConditionalCheckFailedException' not in str(claim_err):
                logger.error(json.dumps({
                    'event': 'invoice_claim_error', 'error': str(claim_err),
                    'referenceId': reference_id, 'requestId': request_id}))
                return _resp(500, {'error': 'Could not claim invoice'})
            existing_inv = table.get_item(Key={'invoiceId': invoice_id}).get('Item', {})
            logger.info(json.dumps({
                'event': 'invoice_dedup_hit_atomic',
                'existingInvoiceId': invoice_id,
                'referenceId': reference_id, 'paymentId': payment_id,
                'note': 'lost the claim race; no invoice number consumed',
                'requestId': request_id,
            }))
            return _resp(200, {
                'invoiceId': invoice_id,
                'invoiceNumber': existing_inv.get('invoiceNumber', ''),
                'total': float(existing_inv.get('total', 0)),
                'referenceId': existing_inv.get('referenceId', reference_id),
                'deduplicated': True,
            })
    else:
        # No reference and no payment id: nothing to dedupe on, so a random id is the
        # honest answer rather than a hash of nothing that would collide every time.
        invoice_id = str(uuid.uuid4())

    # Auto-generate referenceId if not provided (WD-PAY- + 8-char hex)
    if not reference_id:
        reference_id = f"WD-PAY-{uuid.uuid4().hex[:8].upper()}"

    # Validate mandatory fields (relaxed for webhook-originated invoices)
    customer_phone = body.get('customerPhone', '')
    paid_by_phone = body.get('paidByPhone', customer_phone)
    customer_email = body.get('customerEmail', '')
    shipping_address = body.get('shippingAddress', '')
    billing_address = body.get('billingAddress', '')
    entry_point = body.get('entryPoint', 'manual')

    if not customer_phone:
        return _resp(400, {'error': 'Missing mandatory field: customerPhone'})

    try:
        invoice_number = _get_next_invoice_number(body.get('fy'))
    except InvoiceSequenceUnavailable as exc:
        # 503, not 500: the request is well-formed and will succeed once the
        # sequence counter is reachable again, so the caller should retry rather
        # than treat the payload as bad. Nothing is written - an invoice with a
        # number outside the GST series is worse than no invoice, because the
        # number cannot be reassigned after it has gone to a customer.
        logger.error(json.dumps({
            'event': 'invoice_not_created_sequence_unavailable',
            'referenceId': reference_id,
            'error': str(exc),
            'requestId': request_id,
        }))
        return _resp(503, {
            'error': 'Invoice numbering is temporarily unavailable',
            'errorCode': 'INVOICE_SEQUENCE_UNAVAILABLE',
            'retryable': True,
        })

    items = body.get('items', [])
    subtotal = sum(float(i.get('amount', 0)) * int(i.get('quantity', 1)) for i in items)
    discount = float(body.get('discount', 0))
    green_packing = float(body.get('greenPacking', 0))
    notification_fee = float(body.get('notificationFee', 0))

    # Detect if Green Packing / Notification Fee are already in items (new frontend sends them inline)
    gp_in_items = 0.0
    nf_in_items = 0.0
    for it in items:
        nm = (it.get('name', '') or '').lower()
        it_total = float(it.get('amount', 0)) * int(it.get('quantity', 1))
        if 'green' in nm and 'pack' in nm:
            gp_in_items = it_total
        elif 'notification' in nm or 'alert' in nm:
            nf_in_items = it_total

    # If charge items are in the items array, they're already in subtotal — don't add again
    # If sent as separate fields (legacy), add them to total
    effective_gp = green_packing if gp_in_items == 0 else 0.0
    effective_nf = notification_fee if nf_in_items == 0 else 0.0

    # shipping field = express only (greenPacking + notificationFee stored as line items)
    shipping = float(body.get('shipping', 0)) - green_packing - notification_fee
    if shipping < 0: shipping = 0.0
    handling = float(body.get('handling', 0))
    gst_rate = float(body.get('gstRate', 18))

    # ── Validate: no negative amounts ──
    if subtotal < 0:
        return _resp(400, {'error': 'Subtotal cannot be negative'})
    if discount < 0:
        return _resp(400, {'error': 'Discount cannot be negative'})
    if gst_rate < 0 or gst_rate > 100:
        return _resp(400, {'error': 'GST rate must be between 0 and 100'})
    for idx_v, it_v in enumerate(items):
        if float(it_v.get('amount', 0)) < 0:
            return _resp(400, {'error': f'Item {idx_v+1} amount cannot be negative'})
        if int(it_v.get('quantity', 1)) < 1:
            return _resp(400, {'error': f'Item {idx_v+1} quantity must be at least 1'})

    tax = sum(
        float(i.get('amount', 0)) * int(i.get('quantity', 1)) * float(i.get('gstRate', gst_rate)) / 100
        for i in items
    )
    tax = round(tax, 2)

    # Convenience fee: 2.5% of total collection + 18% GST on that 2.5%
    # "Total collection" = subtotal - discount + shipping + handling + tax + GP + NF
    # 2.5% on owner instruction. This was 0.02 while src/config/constants.ts said 2.2% and
    # outbound-whatsapp/handler.py defaulted to 0.022 - three copies, three answers. All
    # three are 2.5% now and must move together.
    convenience_fee = float(body.get('convenienceFee', 0))
    if convenience_fee == 0 and entry_point in ('pay_flow', 'manual', 'whatsapp_payment'):
        collection = subtotal - discount + shipping + effective_gp + effective_nf + handling + tax
        conv_base = round(collection * 0.025, 2)
        conv_gst = round(conv_base * 0.18, 2)
        convenience_fee = round(conv_base + conv_gst, 2)

    total = subtotal - discount + shipping + effective_gp + effective_nf + handling + tax + convenience_fee

    # Determine initial status
    status = body.get('status', 'created')
    payment_status = body.get('paymentStatus', 'pending')

    invoice = {
        'invoiceId': invoice_id,
        'invoiceNumber': invoice_number,
        'paymentId': payment_id,
        'orderId': body.get('orderId', ''),
        'referenceId': reference_id,
        'entryPoint': entry_point,
        # Where the customer placed the order, so the invoice can print its own Source line
        # (GST Rule 46 carries no such requirement; this is for the customer and for support).
        # `entryPoint` is NOT a substitute: it records which internal flow minted the invoice
        # (`pay_flow`, `webhook`, `manual`), and a WhatsApp-origin catalogue order is settled by
        # the website leg, so its entryPoint is a website one. Canonicalised on the way in, so the
        # stored word is already one of exactly two and no reader has to coerce it again. Never
        # empty, so the put_item filter below cannot drop it.
        'channel': order_channel.canonical(body.get('channel')),
        'status': status,
        'paymentStatus': payment_status,
        # Customer
        # VALIDATED, not canonicalised, and the difference is the point. `channel` above has a
        # true default so junk degrades to `website`; a customer id has no substitute, so junk
        # must become ABSENT. `is_customer_uuid` refuses a non-canonical spelling and refuses a
        # uuid7 (which would print the customer's record-creation time on the document), so a bad
        # value is dropped here and the renderers draw no Customer ID row - rather than printing
        # whatever arrived on a request body onto a tax invoice.
        customer_uuid.ATTRIBUTE: (
            body.get(customer_uuid.ATTRIBUTE, '')
            if customer_uuid.is_customer_uuid(body.get(customer_uuid.ATTRIBUTE, '')) else ''),
        'contactId': body.get('contactId', ''),
        'customerName': body.get('customerName', ''),
        'customerPhone': customer_phone,
        'paidByPhone': paid_by_phone,
        'customerEmail': customer_email,
        'shippingAddress': shipping_address,
        'billingAddress': billing_address,
        'goodsType': body.get('goodsType', 'digital-goods'),
        # Catalog product id (retailer_id) — used by the post-payment flow resolver
        # to open the flow mapped to THIS product (catalog_flow_map).
        'catalogRetailerId': body.get('catalogRetailerId', '') or body.get('retailerId', ''),
        # Amounts (stored in rupees)
        'subtotal': _dec(subtotal),
        'discount': _dec(discount),
        'shipping': _dec(shipping),
        'handling': _dec(handling),
        'gstRate': _dec(gst_rate),
        'tax': _dec(tax),
        'convenienceFee': _dec(convenience_fee),
        'total': _dec(total),
        'currency': body.get('currency', 'INR'),
        'gstin': body.get('gstin', COMPANY['gstin']),
        'purpose': body.get('purpose', ''),
        'notes': body.get('notes', ''),
        # Payment routing — which PG config to use when customer triggers via keyword
        'preferredGateway': body.get('preferredGateway', ''),  # 'razorpay' only
        'paymentConfiguration': body.get('paymentConfiguration', ''),  # exact Meta config name
        # Structured address for WhatsApp Payments shipping_info
        'addressLine1': body.get('addressLine1', ''),
        'addressLine2': body.get('addressLine2', ''),
        'city': body.get('city', ''),
        'state': body.get('state', ''),
        'postalCode': body.get('postalCode', ''),
        'landmark': body.get('landmark', ''),
        # Timestamps
        'createdAt': now,
        'updatedAt': now,
        'paidAt': body.get('paidAt', 0),
    }

    # Unconditional: the claim above already established exclusivity for the derived id,
    # and this write is what replaces the minimal claim row with the real invoice. A
    # condition here would refuse our own claim. For the no-reference path the id is a
    # fresh uuid4, so there is nothing to collide with either.
    table.put_item(Item={k: v for k, v in invoice.items() if v is not None and v != ''})

    # Store invoice items (including greenPacking + notificationFee as line items)
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    all_items = list(items)

    # Check if Green Packing / Notification Fee already exist as items (new frontend sends them inline)
    existing_names = {(it.get('name', '') or '').lower() for it in all_items}
    has_green = any('green' in n and 'pack' in n for n in existing_names)
    has_notif = any('notification' in n or 'alert' in n for n in existing_names)

    # Legacy support: if sent as separate fields and NOT already in items, append them
    green_packing = float(body.get('greenPacking', 0))
    notification_fee = float(body.get('notificationFee', 0))
    if green_packing > 0 and not has_green:
        all_items.append({'name': 'Green Packing', 'amount': green_packing, 'quantity': 1, 'isCharge': True})
    if notification_fee > 0 and not has_notif:
        all_items.append({'name': 'Notification Fee', 'amount': notification_fee, 'quantity': 1, 'isCharge': True})
    if all_items:
        for idx, item in enumerate(all_items):
            items_table.put_item(Item={
                'invoiceId': invoice_id,
                'itemIndex': idx,
                'name': item.get('name', 'Item'),
                'amount': _dec(float(item.get('amount', 0))),
                'quantity': int(item.get('quantity', 1)),
                'gstRate': _dec(float(item.get('gstRate', gst_rate))),
                'productId': item.get('productId', ''),
                'isCharge': item.get('isCharge', False),
            })

    logger.info(json.dumps({'event': 'invoice_created', 'invoiceId': invoice_id, 'invoiceNumber': invoice_number, 'referenceId': reference_id, 'total': float(total), 'requestId': request_id}))
    return _resp(201, {'invoiceId': invoice_id, 'invoiceNumber': invoice_number, 'referenceId': reference_id, 'total': float(total), 'convenienceFee': float(convenience_fee)})



def create_invoice_from_payment(body: Dict, request_id: str) -> Dict:
    """Create invoice from a Razorpay payment ID. Called by PostPaymentHandler."""
    payment_id = body.get('paymentId')
    if not payment_id:
        return _resp(400, {'error': 'paymentId required'})

    # Fetch payment record (full pagination to avoid DynamoDB Limit bug)
    payments_table = dynamodb.Table(PAYMENTS_TABLE)
    try:
        items = []
        scan_kwargs = {
            'FilterExpression': boto3.dynamodb.conditions.Attr('paymentId').eq(payment_id),
        }
        while True:
            result = payments_table.scan(**scan_kwargs)
            items.extend(result.get('Items', []))
            if items or 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        if not items:
            return _resp(404, {'error': f'Payment {payment_id} not found'})
        payment = items[0]
    except Exception as e:
        return _resp(500, {'error': f'Payment lookup failed: {e}'})

    # Fetch contact if available
    contact_phone = payment.get('contact', '')
    contact = _lookup_contact_by_phone(contact_phone)

    # Build invoice body from payment + contact
    inv_body = {
        'paymentId': payment_id,
        'orderId': payment.get('orderId', ''),
        'referenceId': payment.get('referenceId', ''),
        'entryPoint': body.get('entryPoint', 'webhook'),
        # Pass through, not decide: the caller (razorpay-webhook / the post-payment handler) knows
        # the order's channel because it holds the attempt row that carries it. An absent value
        # reaches `create_invoice` as '' and canonicalises to `website`, which is true of every
        # payment that can exist today - no WhatsApp-origin order is reachable yet.
        'channel': body.get('channel', ''),
        # Pass through on the same terms. Taken off the REQUEST BODY (which the webhook filled
        # from its own `PAYREF#` row) and never from the contact the lookup above returned: a
        # contact read here would answer "who has this phone now", and a ported number would
        # move a paid order's customer id to whoever received it next. `create_invoice`
        # re-validates it before storing.
        customer_uuid.ATTRIBUTE: body.get(customer_uuid.ATTRIBUTE, ''),
        'status': 'paid',
        'paymentStatus': 'captured',
        'paidAt': int(float(payment.get('createdAt', time.time()))),
        'contactId': contact.get('contactId', '') if contact else '',
        'customerName': contact.get('name', '') if contact else '',
        'customerPhone': contact_phone,
        'paidByPhone': contact_phone,
        'customerEmail': contact.get('email', payment.get('email', '')) if contact else payment.get('email', ''),
        'shippingAddress': contact.get('shippingAddress', '') if contact else '',
        'billingAddress': contact.get('billingAddress', '') if contact else '',
        'addressLine1': contact.get('addressLine1', '') if contact else '',
        'addressLine2': contact.get('landmark', '') if contact else '',
        'city': contact.get('city', '') if contact else '',
        'state': contact.get('state', '') if contact else '',
        'postalCode': contact.get('postalCode', '') if contact else '',
        'items': body.get('items', [{'name': body.get('itemName', 'Payment'), 'amount': float(payment.get('amountInRupees', 0)), 'quantity': 1}]),
        'discount': float(body.get('discount', 0)),
        'shipping': float(body.get('shipping', 0)),
        'gstRate': float(body.get('gstRate', 18)),
        'convenienceFee': float(body.get('convenienceFee', 0)),
        'gstin': body.get('gstin', contact.get('gstin', '') if contact else '') or COMPANY['gstin'],
        'purpose': body.get('purpose', ''),
        'currency': payment.get('currency', 'INR'),
    }

    return create_invoice(inv_body, request_id)


# ─── Update / Read / List ───

def update_invoice(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """Update an existing invoice (admin). Blocks amount changes on paid/cancelled invoices."""
    table = dynamodb.Table(INVOICES_TABLE)

    # Status guard: block amount changes on paid/cancelled invoices
    amount_fields = {'subtotal', 'discount', 'shipping', 'handling', 'gstRate', 'tax', 'convenienceFee', 'total'}
    if amount_fields & set(body.keys()):
        try:
            existing = table.get_item(Key={'invoiceId': invoice_id}).get('Item', {})
            ex_status = existing.get('status', '')
            ex_ps = existing.get('paymentStatus', '')
            if ex_status in ('paid', 'cancelled') or ex_ps in ('captured', 'refunded'):
                return _resp(400, {'error': f'Cannot modify amounts on {ex_status} invoice (paymentStatus={ex_ps})'})
        except Exception as e:
            logger.warning(f'Invoice status guard check failed for {invoice_id}: {e}')

    update_parts = []
    values = {}
    names = {}

    allowed = ['customerName', 'customerPhone', 'paidByPhone', 'customerEmail',
               'shippingAddress', 'billingAddress', 'goodsType', 'status', 'paymentStatus',
               'discount', 'shipping', 'handling', 'gstRate', 'tax', 'convenienceFee', 'total',
               'gstin', 'purpose', 'notes', 'subtotal', 'orderId', 'referenceId']

    for key in allowed:
        if key in body:
            attr = f"#{key}"
            val = f":{key}"
            update_parts.append(f"{attr} = {val}")
            names[attr] = key
            v = body[key]
            values[val] = _dec(v) if isinstance(v, (int, float)) else v

    if not update_parts:
        return _resp(400, {'error': 'No fields to update'})

    values[':now'] = int(time.time())
    update_parts.append('#updatedAt = :now')
    names['#updatedAt'] = 'updatedAt'

    try:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

        # Regenerate image if amount/customer fields changed
        regen_fields = {'subtotal', 'discount', 'shipping', 'tax', 'total', 'convenienceFee',
                        'customerName', 'customerPhone', 'paymentStatus', 'gstRate',
                        'shippingAddress', 'billingAddress', 'purpose'}
        if regen_fields & set(body.keys()):
            try:
                generate_invoice_image(invoice_id, request_id)
                logger.info(json.dumps({'event': 'invoice_image_regenerated', 'invoiceId': invoice_id, 'requestId': request_id}))
            except Exception as regen_err:
                logger.warning(f"Image regen after update failed: {regen_err}")

        return _resp(200, {'invoiceId': invoice_id, 'updated': True})
    except Exception as e:
        return _resp(500, {'error': str(e)})


def get_invoice(invoice_id: str, request_id: str) -> Dict:
    """Get a single invoice with items and assets."""
    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Get items
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Get assets
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_resp = assets_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    assets = assets_resp.get('Items', [])

    result = _normalize_invoice(invoice)
    result['items'] = [_normalize_item(i) for i in items]
    result['assets'] = [_normalize_asset(a) for a in assets]

    return _resp(200, {'invoice': result})


def list_invoices(params: Dict, request_id: str) -> Dict:
    """List invoices with optional filters. Full pagination to avoid DynamoDB Limit bug."""
    table = dynamodb.Table(INVOICES_TABLE)
    scan_kwargs = {}

    filters = []
    if params.get('status'):
        filters.append(boto3.dynamodb.conditions.Attr('status').eq(params['status']))
    if params.get('contactId'):
        filters.append(boto3.dynamodb.conditions.Attr('contactId').eq(params['contactId']))
    if params.get('paymentId'):
        filters.append(boto3.dynamodb.conditions.Attr('paymentId').eq(params['paymentId']))

    if filters:
        combined = filters[0]
        for f in filters[1:]:
            combined = combined & f
        scan_kwargs['FilterExpression'] = combined

    invoices = []
    while True:
        result = table.scan(**scan_kwargs)
        invoices.extend(result.get('Items', []))
        if 'LastEvaluatedKey' in result:
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        else:
            break

    invoices.sort(key=lambda x: int(x.get('createdAt', 0)), reverse=True)

    return _resp(200, {'invoices': [_normalize_invoice(i) for i in invoices], 'count': len(invoices)})


# ─── Invoice Rendering (POS Receipt Style Image + PDF) ───


def _source_label(invoice: Dict) -> str:
    """The word the Source line prints: `Website` or `WhatsApp`.

    One function for all three render sites (HTML/PDF, PNG, WhatsApp caption) so a customer
    cannot be shown two different origins for one order - the same reason `/orders` derives its
    table tag and its detail rung from a single local.

    The stored value is already canonical (`create_invoice` coerces on the way in), but this
    coerces again rather than trusting it: a row written before this field existed carries no
    `channel` at all, and `order_channel.canonical` is total, so an absent or junk value prints
    `Website` instead of raising inside a renderer. Title-cased here and canonical in storage,
    because this is prose for a human and the stored word is a key for a machine.
    """
    if order_channel.canonical(invoice.get('channel')) == order_channel.CHANNEL_WHATSAPP:
        return 'WhatsApp'
    return 'Website'


def _customer_id(invoice: Dict) -> str:
    """The public customer id to print, or `''` meaning PRINT NO ROW AT ALL.

    One function for the same three render sites as `_source_label`, for the same reason - but
    note the opposite default. `_source_label` always answers, because every order genuinely has
    an origin and `website` is true of every row written so far. A customer id has NO true
    default: a row that carries none belongs to a contact created before this attribute existed,
    and the honest rendering is silence.

    So every caller must suppress its whole line on `''`. A label with nothing after it reads as
    a broken renderer, and a MINTED substitute would be worse still: it would print an id on a
    document that matches no record anywhere, which is precisely the failure
    `tests/test_invoice_number_is_rendered.py` pins for the invoice number.

    `from_contact` is reused as the validator because it never raises and re-checks the stored
    value, so a uuid7 or a non-canonical spelling written by some future caller is suppressed
    rather than printed. Reusing it also means there is one definition of "a usable customer id"
    across the CRM, the checkout, the webhook and this engine.
    """
    return customer_uuid.from_contact(invoice)


def _build_invoice_html(invoice: Dict, items: List[Dict]) -> str:
    """Build POS receipt style HTML matching the PNG receipt design.
    Single delivery address (billing = same), no Order ID shown,
    QR code, amount in words, paper tear zigzag, GST summary."""
    inv_num = invoice.get('invoiceNumber', '')
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    handling_amt = float(invoice.get('handling', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    purpose = invoice.get('purpose', '') or ''
    if purpose.lower().startswith('menu_'):
        purpose = ''
    paid_at = invoice.get('paidAt', 0)
    created_at = invoice.get('createdAt', 0)
    payment_status = invoice.get('paymentStatus', 'pending')

    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    if paid_at and int(paid_at) > 0:
        paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
    elif pay_status.canonical(payment_status) == pay_status.CAPTURED:
        paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
    else:
        paid_str = ''

    cgst = tax / 2
    sgst = tax / 2

    # Logo as base64 data URI
    logo_html = ''
    try:
        logo_bytes = _load_logo_bytes()
        if logo_bytes:
            import base64
            b64 = base64.b64encode(logo_bytes).decode('ascii')
            logo_html = f'<img src="data:image/png;base64,{b64}" style="width:50px;height:50px;object-fit:contain" alt="Logo">'
    except Exception as _e:
        logger.debug(f"HTML logo embed failed: {_e}")

    # Extract Green Packing and Notification Fee from items
    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # Items rows
    items_html = ''
    total_qty = 0
    for i, item in enumerate(items):
        name = item.get('name', 'Item')
        amt = float(item.get('amount', 0))
        qty = int(item.get('quantity', 1))
        total_qty += qty
        line_total = amt * qty
        items_html += f'<tr><td>{i+1}</td><td>{name}</td><td class="r">{qty}</td><td class="r">{amt:,.2f}</td><td class="r">{line_total:,.2f}</td></tr>'

    # Amount in words
    words = _amount_in_words(total)

    # GST breakdown
    gst_html = ''
    if gst_rate > 0:
        half_rate = gst_rate / 2
        taxable = subtotal - discount
        gst_html = f'''<div class="divider"></div>
        <div class="section-title">GST Summary</div>
        <div class="total-row"><span>Taxable Amount</span><span>{taxable:,.2f}</span></div>
        <div class="total-row"><span>CGST @{half_rate:.1f}%</span><span>{cgst:,.2f}</span></div>
        <div class="total-row"><span>SGST @{half_rate:.1f}%</span><span>{sgst:,.2f}</span></div>
        <div class="total-row b"><span>Total Tax</span><span>{tax:,.2f}</span></div>'''

    reference_id = invoice.get('referenceId', '')
    # Ref line removed from the customer copy (owner decision 2026-10-07): it duplicated the
    # Order id. The reference still lives on the stored invoice record; it is simply not printed.
    ref_id_html = ''

    # GST Rule 46(b): the invoice number is a mandatory particular of a tax invoice. `inv_num` has
    # been assigned at the top of this function since the renderer was written and was printed
    # NOWHERE, so every document this engine has ever produced was missing it. Empty renders no
    # row rather than `Invoice No: ` with nothing after it - an unnumbered invoice should look
    # unnumbered, not look like a rendering fault. Only `_get_next_invoice_number` may mint one;
    # a renderer that invented a substitute would advance the GST series from a read path.
    inv_num_html = f'<div class="info-row"><span>Invoice No: {inv_num}</span></div>' if inv_num else ''
    # Source always renders, because every order has an origin: absent means website, and that is
    # measured rather than assumed (see order_channel - no WhatsApp-origin order exists yet).
    source_html = f'<div class="info-row"><span>Source: {_source_label(invoice)}</span></div>'
    # The public customer id, in the Bill To block rather than the meta block: it identifies the
    # person being billed, so it belongs beside their name and not beside the invoice number.
    # Empty renders NO row - see `_customer_id`. Safe to print IN FULL, unlike the phone on the
    # next line: it is ours, opaque, carries no timestamp and is not a credential, which is what
    # lets a support agent quote it instead of reading a number back.
    cust_id = _customer_id(invoice)
    cust_id_html = (f'<div class="addr">Customer ID: {cust_id}</div>'
                    if cust_id else '')

    # Status
    status_upper = payment_status.upper()
    badge_color = '#059669' if status_upper == 'CAPTURED' else '#d97706' if status_upper == 'PENDING' else '#dc2626'
    badge_bg = '#D1FAE5' if status_upper == 'CAPTURED' else '#FEF3C7' if status_upper == 'PENDING' else '#FEE2E2'

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Courier New',Courier,monospace;color:#000;background:#fff;width:420px;padding:18px;font-size:12px;line-height:1.4}}
.center{{text-align:center}}
.r{{text-align:right}}
.b{{font-weight:bold}}
h1{{font-size:17px;margin:2px 0;letter-spacing:1px}}
.subtitle{{font-size:10px;color:#000;margin:1px 0}}
.divider{{border-top:1px dashed #999;margin:8px 0}}
.divider2{{border-top:2px solid #333;margin:8px 0}}
.section-title{{font-size:11px;font-weight:bold;color:#000;margin:4px 0 2px;text-transform:uppercase;letter-spacing:0.5px}}
table{{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0}}
th{{text-align:left;padding:3px 2px;border-bottom:1px solid #333;font-size:10px;text-transform:uppercase;color:#000;font-weight:bold}}
th.r{{text-align:right}}
td{{padding:3px 2px;vertical-align:top;color:#000}}
.info-row{{display:flex;justify-content:space-between;font-size:11px;margin:2px 0;color:#000}}
.addr{{font-size:10px;color:#000;margin:2px 0 4px;line-height:1.3}}
.total-row{{display:flex;justify-content:space-between;font-size:12px;margin:2px 0;color:#000}}
.grand{{font-size:15px;font-weight:bold;background:#f0fdf4;padding:6px 4px;margin:4px -4px;border-top:2px solid #333;border-bottom:2px solid #333}}
.badge{{display:inline-block;padding:2px 10px;font-size:10px;font-weight:bold;border-radius:3px;color:{badge_color};background:{badge_bg};border:1px solid {badge_color}}}
.footer{{margin-top:10px;text-align:center;font-size:10px;color:#000}}
.paid-stamp{{font-size:18px;font-weight:bold;color:#059669;text-align:center;margin:6px 0;letter-spacing:2px}}
.header-row{{display:flex;align-items:flex-start;gap:12px;margin-bottom:4px}}
.header-logo{{flex-shrink:0}}
.header-text{{flex:1;text-align:center}}
.words{{font-size:10px;color:#000;margin:4px 0;padding:0 4px}}
</style></head><body>
<div class="header-row">
    <div class="header-logo">{logo_html}</div>
    <div class="header-text">
        <h1>{COMPANY['legal_name']}</h1>
        <div class="subtitle">Brand: {COMPANY['name']}</div>
        <div class="subtitle">GSTIN: {COMPANY['gstin']}</div>
        <div class="subtitle">PAN: {COMPANY['pan']}</div>
        <div class="subtitle">The W.B.S.I.D.C. Building, Unit 1/20,</div>
        <div class="subtitle">81/2/7, Phears Ln, Kolkata, WB 700012</div>
        <div class="subtitle">one@wecare.digital | +91 93309 94400</div>
    </div>
</div>
<div class="divider2"></div>
<div class="center" style="margin:4px 0"><span style="font-size:13px;font-weight:bold;letter-spacing:1px">TAX INVOICE</span></div>
<div class="divider"></div>
{inv_num_html}
<div class="info-row"><span>Date: {date_str}</span><span>{time_str}</span></div>
{ref_id_html}
{source_html}
{f'<div class="info-row b"><span>PAID: {paid_str}</span></div>' if status_upper == 'CAPTURED' and paid_str else ''}
<div class="divider"></div>
<div class="section-title">Bill To</div>
<div style="font-size:11px;font-weight:bold;color:#000">{cust_name}</div>
{cust_id_html}
<div class="addr">{cust_phone}{(' | ' + cust_email) if cust_email else ''}</div>
{f'<div class="section-title">Address</div><div class="addr">{ship_addr}</div>' if ship_addr else ''}
<div class="divider"></div>
<table>
    <thead><tr><th>#</th><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr></thead>
    <tbody>{items_html}</tbody>
</table>
<div class="divider"></div>
<div class="total-row"><span>Subtotal</span><span>{subtotal:,.2f}</span></div>
{'<div class="total-row"><span>Promo</span><span>-' + f'{discount:,.2f}' + '</span></div>' if discount else ''}
{'<div class="total-row"><span>Express</span><span>' + f'{shipping_amt:,.2f}' + '</span></div>' if shipping_amt else ''}
{'<div class="total-row"><span>Green Packing</span><span>' + f'{green_packing_amt:,.2f}' + '</span></div>' if green_packing_amt else ''}
{'<div class="total-row"><span>Notification Fee</span><span>' + f'{notification_fee_amt:,.2f}' + '</span></div>' if notification_fee_amt else ''}
{'<div class="total-row"><span>Handling</span><span>' + f'{handling_amt:,.2f}' + '</span></div>' if handling_amt else ''}
<div class="total-row"><span>CGST @{gst_rate/2:.1f}%</span><span>{cgst:,.2f}</span></div>
<div class="total-row"><span>SGST @{gst_rate/2:.1f}%</span><span>{sgst:,.2f}</span></div>
{'<div class="total-row"><span>Conv Fee</span><span>' + f'{conv_fee:,.2f}' + '</span></div>' if conv_fee else ''}
<div class="total-row grand"><span>Total ({total_qty} items)</span><span>&#8377; {total:,.2f}</span></div>
<div class="words">{words}</div>
{gst_html}
<div class="divider2"></div>
{'<div class="paid-stamp">* * *  PAID  * * *</div>' if status_upper == 'CAPTURED' else ''}
{'<div class="center" style="font-size:11px;margin:2px 0">Paid on: ' + paid_str + '</div>' if status_upper == 'CAPTURED' and paid_str else ''}
{'<div class="center b" style="font-size:12px;margin:4px 0">PAYMENT PENDING</div>' if status_upper == 'PENDING' else ''}
<div class="divider2"></div>
<div class="footer">
    <div style="font-size:12px;font-weight:bold;margin:6px 0">Thank You!</div>
    <div>Visit Again!</div>
    <div style="margin-top:2px">wecare.digital/customerservice</div>
</div>
</body></html>'''




# ─── Generate Invoice Image (PNG) ───

def generate_invoice_image(invoice_id: str, request_id: str) -> Dict:
    """Render invoice as POS receipt PNG using PIL, upload to S3."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    # Fetch invoice + items
    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Render to PNG using pure-Python bitmap font (zero dependencies, proven working)
    png_bytes = _generate_receipt_png(invoice, items)

    # S3 key uses WhatsApp payment reference ID (unguessable, unique)
    ref_id = invoice.get('referenceId', invoice_id)
    s3_key = f"{INVOICE_PREFIX}wecare-digital-{ref_id}.png"

    s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=s3_key,
        Body=png_bytes,
        ContentType='image/png',
        CacheControl='max-age=86400',
    )

    # Signed and expiring, not `https://{CDN_DOMAIN}/{s3_key}`. The key is now under the gated
    # root, so a CDN URL would be a dead link rather than a disclosure — but a dead link is its
    # own bug, and the correct answer is the one that works AND expires.
    image_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Store asset record.
    #
    # `s3Key` is the source of truth and `url` is deliberately NOT stored. A presigned URL
    # expires, so persisting one produces a record that is correct when written and quietly
    # broken later — and `send_invoice_whatsapp` reads this row on its second call, so it would
    # have handed out an expired link. The key is permanent; the URL is minted per response.
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_table.put_item(Item={
        'invoiceId': invoice_id,
        'assetType': 'image',
        's3Key': s3_key,
        'contentType': 'image/png',
        'version': int(time.time()),
        'generatedAt': int(time.time()),
    })

    # The URL is a bearer grant, so the key is logged and the URL is not.
    logger.info(json.dumps({'event': 'invoice_image_generated', 'invoiceId': invoice_id,
                            's3Key': s3_key, 'signed': bool(image_url),
                            'requestId': request_id}))
    return _resp(200, {'invoiceId': invoice_id, 'imageUrl': image_url, 's3Key': s3_key})


def _signed_invoice_url(s3_key: str, invoice_id: str, request_id: str) -> str:
    """A short-lived presigned GET for a rendered invoice, or `''`.

    A presigned URL addresses S3 directly, so it works even though CloudFront denies the gated
    root wholesale — which is what makes moving the prefix possible without losing the ability to
    show an invoice to the staff member who asked for it.

    Returns `''` rather than falling back to a CDN URL. `receipt_links` raises instead of
    returning a public fallback for exactly this reason: an invoice that cannot be linked securely
    is an inconvenience, and one served over a permanent public URL is a disclosure.
    """
    if not s3_key:
        return ''
    try:
        from lambda_utils import receipt_links
        return receipt_links.signed_url(s3, bucket=MEDIA_BUCKET, key=s3_key,
                                        filename=f"invoice-{invoice_id}.png")
    except Exception as error:  # noqa: BLE001
        # Type only: a presign failure message can echo the key and the bucket.
        logger.warning(json.dumps({'event': 'invoice_link_sign_failed',
                                   'error': type(error).__name__,
                                   'invoiceId': invoice_id, 'requestId': request_id}))
        return ''


# ─── Receipt PNG Rendering ───
# Uses monospace font, logo + PAID icon from S3, WD reference format.
# Compact POS thermal receipt style for WhatsApp chat visibility.


def _generate_receipt_png(invoice: Dict, items: List[Dict]) -> bytes:
    """Generate POS thermal receipt as PNG image.

    Layout: Logo left + company header, invoice meta, bill/ship to,
    items table, totals, GST summary, PAID icon, footer.
    Monospace font, 2x scaled for WhatsApp readability.
    """
    from PIL import Image, ImageDraw, ImageFont

    # ── Font setup (monospace — download DejaVu Sans Mono from S3 on Lambda) ──
    _font_cache = getattr(_generate_receipt_png, '_font_cache', {})
    _generate_receipt_png._font_cache = _font_cache

    def _get_font_bytes(bold=False):
        key = 'bold' if bold else 'regular'
        if key not in _font_cache:
            s3_key = media_paths.public(
                f"stream/media/fonts/DejaVuSansMono{'-Bold' if bold else ''}.ttf")
            try:
                obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
                _font_cache[key] = obj['Body'].read()
            except Exception as _e:
                logger.debug(f"Font S3 load failed ({s3_key}): {_e}")
                _font_cache[key] = None
        return _font_cache[key]

    def _mono(size, bold=False):
        # 1. Try S3-hosted DejaVu Sans Mono
        fb = _get_font_bytes(bold)
        if fb:
            try:
                return ImageFont.truetype(io.BytesIO(fb), size)
            except Exception as _e:
                logger.debug(f"Font truetype from S3 bytes failed: {_e}")
        # 2. Try system fonts (Windows dev)
        names = ['consolab.ttf', 'courbd.ttf'] if bold else ['consola.ttf', 'cour.ttf']
        for n in names:
            try:
                return ImageFont.truetype(n, size)
            except Exception as _e:
                logger.debug(f"System font {n} not available: {_e}")
                continue
        # 3. Pillow 10.1+ built-in default at requested size
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    FONT_SZ = 14
    F    = _mono(FONT_SZ)           # Body — regular
    FB   = _mono(FONT_SZ, True)     # Labels/headings — bold
    FLG  = _mono(FONT_SZ + 3, True) # Title — bold large
    FSM  = _mono(FONT_SZ - 2)       # Secondary — regular small
    FXS  = _mono(FONT_SZ - 4)       # Extra small — regular

    CHARS  = 48
    LINE_H = 18
    PX     = 14
    PY     = 10

    def _tw(draw, text, font):
        try:
            bb = draw.textbbox((0, 0), text, font=font)
            return bb[2] - bb[0]
        except Exception as _e:
            logger.debug(f"textbbox fallback: {_e}")
            return len(text) * 8

    # ── Build receipt lines ──
    # Each: (content, font, align)  align: L/C/LR/LOGO/PAID_ICON
    lines = []

    def L(t, f=F):    lines.append((t, f, 'L'))
    def C(t, f=F):    lines.append((t, f, 'C'))
    def LR(l, r, f=F): lines.append(((l, r), f, 'LR'))
    def SEP():         lines.append(('-' * CHARS, F, 'C'))
    def DSEP():        lines.append(('=' * CHARS, F, 'C'))
    def BL():          lines.append(('', F, 'L'))

    # ── Extract invoice data ──
    created_at = invoice.get('createdAt', 0)
    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    order_id = invoice.get('orderId', '')
    reference_id = invoice.get('referenceId', '')
    payment_id = invoice.get('paymentId', '')
    purpose = invoice.get('purpose', '') or ''
    # Clean up raw menu action IDs stored as purpose (e.g. "Menu_Pay")
    if purpose.lower().startswith('menu_'):
        purpose = ''
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    bill_addr = invoice.get('billingAddress', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount_val = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    cgst = tax / 2
    sgst = tax / 2
    payment_status = invoice.get('paymentStatus', 'pending').upper()
    paid_at = invoice.get('paidAt', 0)

    # Extract Green Packing and Notification Fee from items (stored as charge line items)
    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # ═══════════════════════════════════════════════
    # ═══ REDESIGNED RECEIPT — consistent design system
    # ═══════════════════════════════════════════════
    # Font tiers: Title=17px, Body=14px, Small=12px (no tiny 10px)
    # Line heights: Title=24, Body=20, Small=17
    # Section gap: 6px extra after separators

    # ── Extract invoice data ──
    created_at = invoice.get('createdAt', 0)
    date_str = _ist_strftime('%d-%m-%Y', int(created_at)) if created_at else ''
    time_str = _ist_strftime('%H:%M IST', int(created_at)) if created_at else ''
    reference_id = invoice.get('referenceId', '')
    purpose = invoice.get('purpose', '') or ''
    if purpose.lower().startswith('menu_'):
        purpose = ''
    cust_name = invoice.get('customerName', 'Customer')
    cust_phone = invoice.get('customerPhone', '')
    cust_email = invoice.get('customerEmail', '')
    ship_addr = invoice.get('shippingAddress', '')
    subtotal = float(invoice.get('subtotal', 0))
    discount_val = float(invoice.get('discount', 0))
    shipping_amt = float(invoice.get('shipping', 0))
    tax = float(invoice.get('tax', 0))
    gst_rate = float(invoice.get('gstRate', 0))
    conv_fee = float(invoice.get('convenienceFee', 0))
    total = float(invoice.get('total', 0))
    cgst = tax / 2
    sgst = tax / 2
    payment_status = invoice.get('paymentStatus', 'pending').upper()
    paid_at = invoice.get('paidAt', 0)

    green_packing_amt = 0.0
    notification_fee_amt = 0.0
    for it in items:
        if it.get('isCharge'):
            nm = (it.get('name', '') or '').lower()
            amt_val = float(it.get('amount', 0)) * int(it.get('quantity', 1))
            if 'green' in nm and 'pack' in nm:
                green_packing_amt = amt_val
            elif 'notification' in nm or 'alert' in nm:
                notification_fee_amt = amt_val

    # ── Calculate canvas width ──
    tmp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    try:
        bb = tmp_draw.textbbox((0, 0), 'M', font=F)
        CW = bb[2] - bb[0]
    except Exception:
        CW = 9

    W = CHARS * CW + PX * 2
    est_h = 1200  # generous estimate, will crop
    img = Image.new('RGB', (W, est_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    logo_bytes = _load_logo_bytes()

    y = PY + 4
    CLR_BLK = (0, 0, 0)
    CLR_GRY = (0, 0, 0)  # All text black — no grey

    def _center(txt, font, color=CLR_BLK):
        nonlocal y
        tw = _tw(draw, txt, font)
        draw.text(((W - tw) // 2, y), txt, fill=color, font=font)

    def _left(txt, font, color=CLR_BLK):
        nonlocal y
        draw.text((PX, y), txt, fill=color, font=font)

    def _lr(lt, rt, font, color=CLR_BLK):
        nonlocal y
        draw.text((PX, y), lt, fill=color, font=font)
        rw = _tw(draw, rt, font)
        draw.text((W - PX - rw, y), rt, fill=color, font=font)

    def _sep():
        nonlocal y
        _center('-' * CHARS, F, CLR_GRY)
        y += LINE_H

    def _dsep():
        nonlocal y
        _center('=' * CHARS, F, CLR_GRY)
        y += LINE_H

    # ═══ HEADER — logo left-aligned, company info centered in remaining space ═══
    LOGO_SZ = 50
    if logo_bytes:
        try:
            logo_img = Image.open(io.BytesIO(logo_bytes)).convert('RGBA')
            logo_img = logo_img.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
            img.paste(logo_img, (PX, y - 2), logo_img)
        except Exception:
            pass

    tx = PX + LOGO_SZ + 12  # text area starts after logo + gap
    avail_w = W - tx - PX   # available width for centered text

    def _hdr_center(txt, font, color=CLR_BLK):
        """Center text within the header area (right of logo)."""
        tw = _tw(draw, txt, font)
        x = tx + max(0, (avail_w - tw) // 2)
        draw.text((x, y), txt, fill=color, font=font)

    # Legal name — centered in header area, bold (owner-approved mockup 2026-10-07)
    _hdr_center(COMPANY['legal_name'], FLG)
    y += 22
    # Fixed brand line, always "WECARE.DIGITAL", never derived from entryPoint.
    _hdr_center(f"Brand: {COMPANY['name']}", FSM)
    y += LINE_H
    # GSTIN — regular, grey
    _hdr_center(f"GSTIN: {COMPANY['gstin']}", FSM, CLR_GRY)
    y += LINE_H
    # PAN — regular, grey (GST Rule / owner mockup: PAN under GSTIN)
    _hdr_center(f"PAN: {COMPANY['pan']}", FSM, CLR_GRY)
    y += LINE_H
    # Address — 2 fixed lines, regular, grey
    _hdr_center("The W.B.S.I.D.C. Building, Unit 1/20,", FSM, CLR_GRY)
    y += LINE_H
    _hdr_center("81/2/7, Phears Ln, Kolkata, WB 700012", FSM, CLR_GRY)
    y += LINE_H
    # Contact — single line, regular, grey
    _hdr_center(f"one@wecare.digital | +91 93309 94400", FSM, CLR_GRY)
    y += LINE_H + 2

    # ═══ INVOICE TITLE ═══
    _dsep()
    _center("TAX INVOICE", FLG)
    y += LINE_H + 4
    _sep()

    # ═══ INVOICE META ═══
    # GST Rule 46(b) first: the invoice number leads the meta block, which is where a reader
    # looks for it. The PNG never read `invoiceNumber` at all before this, so the image sent to
    # the customer on WhatsApp carried no number. Read here rather than in the extraction block
    # above so this line and the two render sites that match it stay in one place.
    # `str(... or '')` because DynamoDB hands back whatever was stored and an f-string would
    # happily print `None`.
    inv_num = str(invoice.get('invoiceNumber', '') or '')
    if inv_num:
        _left(f"Invoice No: {inv_num}", FB)
        y += LINE_H
    _lr(f"Date: {date_str}", time_str, F)
    y += LINE_H
    # Ref line removed (owner decision 2026-10-07): it duplicated the Order id on the customer
    # copy. Order id is shown below; the reference still lives on the stored record.
    # Source per docs/invoice-layout.md section 2. Unconditional: every order has an origin, and
    # `_source_label` is total, so there is no empty-label case to guard.
    _left(f"Source: {_source_label(invoice)}", F)
    y += LINE_H
    # Brand is now the FIXED header line "Brand: WECARE.DIGITAL" (set in the header block),
    # never derived from entryPoint. The old entryPoint-derived Brand line is removed.
    # Note line: show request/submission reference (clean format, no #)
    notes = invoice.get('notes', '')
    if notes:
        # Strip "Request #" prefix → just show the reference number
        clean_note = notes.replace('Request #', '').replace('Request#', '').strip()
        _left(f"Note: {clean_note[:40]}", FSM)
        y += LINE_H
    if payment_status == 'CAPTURED':
        if paid_at and int(paid_at) > 0:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
        else:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
        _left(f"PAID: {paid_str}", FB)
        y += LINE_H
    elif payment_status not in ('PENDING', ''):
        _left(f"Status: {payment_status}", FB)
        y += LINE_H
    _sep()

    # ═══ BILL TO ═══
    _left("Bill To:", FB)
    y += LINE_H
    _left(f"  {cust_name}", F)
    y += LINE_H
    # The public customer id, between the name and the phone, exactly as in the HTML - one
    # layout, two renderers. Skipped entirely when absent (see `_customer_id`), which is why the
    # `y += LINE_H` is inside the branch: advancing the cursor for a line that was never drawn
    # would leave a blank gap in the receipt.
    _cust_id = _customer_id(invoice)
    if _cust_id:
        _left(f"  Customer ID: {_cust_id}", FSM)
        y += LINE_H
    contact_line = f"  {cust_phone}"
    if cust_email:
        contact_line += f" | {cust_email}"
    _left(contact_line[:CHARS], F)
    y += LINE_H

    # Address: try invoice fields first, then shippingAddress string, then contact lookup
    display_addr = ''
    addr_line1 = invoice.get('addressLine1', '')
    addr_city = invoice.get('city', '')
    addr_state = invoice.get('state', '')
    addr_postal = invoice.get('postalCode', '')
    if addr_line1 and addr_city:
        addr_parts = [addr_line1]
        if invoice.get('addressLine2'):
            addr_parts.append(invoice['addressLine2'])
        addr_parts.append(f"{addr_city}, {addr_state or ''} {addr_postal or ''}".strip().rstrip(','))
        display_addr = ', '.join(p for p in addr_parts if p)
    elif ship_addr:
        # Try parsing JSON address
        try:
            import json as _json
            addr_obj = _json.loads(ship_addr) if ship_addr.strip().startswith('{') else {}
            if addr_obj.get('city'):
                parts = [addr_obj.get('address', ''), addr_obj.get('city', ''),
                         addr_obj.get('state', ''), addr_obj.get('in_pin_code', '')]
                display_addr = ', '.join(p for p in parts if p)
        except Exception:
            display_addr = ship_addr
    elif bill_addr:
        display_addr = bill_addr

    # Fallback: look up address from contact record
    if not display_addr and cust_phone:
        try:
            contacts_tbl = dynamodb.Table(CONTACTS_TABLE)
            clean_ph = cust_phone.replace('+', '').replace(' ', '').replace('-', '')
            for variant in [f'+{clean_ph}', clean_ph]:
                try:
                    cr = contacts_tbl.query(
                        IndexName='phone-index',
                        KeyConditionExpression='phone = :p',
                        ExpressionAttributeValues={':p': variant},
                        Limit=1,
                    )
                    c_items = cr.get('Items', [])
                    if c_items:
                        c = c_items[0]
                        c_parts = [c.get('addressLine1', ''), c.get('addressLine2', ''),
                                   c.get('city', ''), c.get('state', ''), c.get('pincode', '')]
                        c_addr = ', '.join(p for p in c_parts if p)
                        if c_addr and len(c_addr) > 5:
                            display_addr = c_addr
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if display_addr:
        _left("Address:", FB)
        y += LINE_H
        for addr_line in _wrap_text(display_addr, CHARS - 2):
            _left(f"  {addr_line}", F)
            y += LINE_H
    _sep()

    # ═══ ITEMS TABLE ═══
    _left(f"{'#':<3}{'Item':<22}{'Qty':>4}{'Rate':>10}{'Amt':>9}", FB)
    y += LINE_H
    _sep()
    total_qty = 0
    for idx, item in enumerate(items):
        name = item.get('name', 'Item')[:20]
        amt = float(item.get('amount', 0))
        qty = int(item.get('quantity', 1))
        total_qty += qty
        line_total = amt * qty
        _left(f"{idx+1:<3}{name:<22}{qty:>4}{amt:>10,.2f}{line_total:>9,.2f}", F)
        y += LINE_H
    _sep()

    # ═══ TOTALS ═══
    _lr("Subtotal", f"{subtotal:,.2f}", F)
    y += LINE_H
    if discount_val:
        _lr("Promo", f"-{discount_val:,.2f}", F)
        y += LINE_H
    if shipping_amt:
        _lr("Express", f"{shipping_amt:,.2f}", F)
        y += LINE_H
    if green_packing_amt:
        _lr("Green Packing", f"{green_packing_amt:,.2f}", F)
        y += LINE_H
    if notification_fee_amt:
        _lr("Notification Fee", f"{notification_fee_amt:,.2f}", F)
        y += LINE_H
    if gst_rate > 0:
        _lr(f"CGST @{gst_rate/2:.0f}%", f"{cgst:,.2f}", F)
        y += LINE_H
        _lr(f"SGST @{gst_rate/2:.0f}%", f"{sgst:,.2f}", F)
        y += LINE_H
    if conv_fee:
        _lr("Conv Fee", f"{conv_fee:,.2f}", F)
        y += LINE_H
    _dsep()

    # ═══ GRAND TOTAL ═══
    # Highlight background
    draw.rectangle([(PX - 4, y - 2), (W - PX + 4, y + LINE_H + 4)], fill=(240, 253, 244))
    _lr(f"TOTAL ({total_qty} items)", f"\u20b9 {total:,.2f}", FLG)
    y += LINE_H + 8

    # Amount in words
    words = _amount_in_words(total)
    for wline in _wrap_text(words, CHARS - 2):
        _left(f"  {wline}", FSM)
        y += LINE_H - 2
    y += 4
    _dsep()

    # ═══ GST SUMMARY ═══
    if gst_rate > 0:
        taxable = subtotal - discount_val
        _center("GST Summary", FB)
        y += LINE_H
        _lr("Taxable Amount", f"{taxable:,.2f}", F)
        y += LINE_H
        _lr(f"CGST @{gst_rate/2:.1f}%", f"{cgst:,.2f}", F)
        y += LINE_H
        _lr(f"SGST @{gst_rate/2:.1f}%", f"{sgst:,.2f}", F)
        y += LINE_H
        _lr("Total Tax", f"{tax:,.2f}", FB)
        y += LINE_H
        _sep()

    # ═══ PAID STAMP + PAYMENT DETAILS ═══
    if payment_status == 'CAPTURED':
        _center("* * *  PAID  * * *", FLG)
        y += LINE_H + 2
        if paid_at and int(paid_at) > 0:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(paid_at))
        else:
            paid_str = _ist_strftime('%d-%m-%Y %H:%M IST', int(time.time()))
        _center(f"Paid on: {paid_str}", F)
        y += LINE_H
    elif payment_status == 'PENDING':
        _center("PAYMENT PENDING", FB)
        y += LINE_H
    elif payment_status:
        _center(f"Status: {payment_status}", FB)
        y += LINE_H

    # ═══ QR CODE — links to customerservice ═══
    #
    # Served from a pre-rendered S3 object, not generated. The runtime `import
    # qrcode` branch that used to lead this block was removed on 2026-09-24:
    #
    #   * `qrcode` was in no requirements file and in no attached layer (the only
    #     layer on this function is pillow-python312), so the import failed on
    #     every single invoice and the code always fell through to here anyway.
    #   * It logged at WARNING each time, for a condition that was permanent and
    #     not actionable. A warning that always fires trains people to ignore
    #     warnings.
    #   * The encoded value is the constant `[retired public path]`.
    #     Every invoice would have produced a byte-identical image, so generating
    #     it per render was work to reproduce a fixed asset.
    #
    # Adding the dependency would have been the wrong repair for the same reason:
    # the right artifact for a constant is a file. `stream/media/m/qr-customerservice.png`
    # is present (459 bytes, image/png, verified 2026-09-24).
    qr_rendered = False
    try:
        qr_s3_img = _load_s3_image(media_paths.public('stream/media/m/qr-customerservice.png'))
        if qr_s3_img:
            qr_s3_img = qr_s3_img.resize((80, 80), Image.LANCZOS).convert('RGB')
            qr_x = (W - 80) // 2
            img.paste(qr_s3_img, (qr_x, y))
            y += 84
            qr_rendered = True
    except Exception as qr_err:
        # Debug, not warning: the text fallback below is a complete substitute, so
        # a missing image degrades the invoice rather than breaking it.
        logger.debug(f"QR image load failed: {qr_err}")

    # If the image is unavailable, the URL in text carries the same information.
    if not qr_rendered:
        _center("Scan QR or visit:", FSM, CLR_GRY)
        y += LINE_H
        _center("wecare.digital/customerservice", F)
        y += LINE_H

    # ═══ FOOTER ═══
    _sep()
    _center("Thank You!", FLG)
    y += LINE_H + 2
    _center("Visit Again!", F, CLR_GRY)
    y += LINE_H
    _center("wecare.digital/customerservice", FSM, CLR_GRY)
    y += LINE_H
    _dsep()

    # ═══ CROP + ZIGZAG + SCALE ═══
    y += PY
    img = img.crop((0, 0, W, y))

    # ── Add paper tear zigzag effect (top and bottom) ──
    ZIGZAG_H = 8  # height of zigzag teeth
    ZIGZAG_W = 12  # width of each tooth
    tear_img = Image.new('RGB', (W, img.height + ZIGZAG_H * 2), (200, 200, 200))  # grey background
    tear_draw = ImageDraw.Draw(tear_img)

    # Top zigzag — white teeth on grey
    for x in range(0, W, ZIGZAG_W):
        tear_draw.polygon([
            (x, ZIGZAG_H),
            (x + ZIGZAG_W // 2, 0),
            (x + ZIGZAG_W, ZIGZAG_H),
        ], fill=(255, 255, 255))

    # Bottom zigzag — white teeth on grey
    bottom_y = img.height + ZIGZAG_H
    for x in range(0, W, ZIGZAG_W):
        tear_draw.polygon([
            (x, bottom_y),
            (x + ZIGZAG_W // 2, bottom_y + ZIGZAG_H),
            (x + ZIGZAG_W, bottom_y),
        ], fill=(255, 255, 255))

    # Paste the receipt content between the zigzag edges
    tear_img.paste(img, (0, ZIGZAG_H))
    img = tear_img

    # Scale 2x for WhatsApp readability
    final_w = W * 2
    final_h = img.height * 2
    img = img.resize((final_w, final_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _amount_in_words(amount: float) -> str:
    """Convert amount to Indian English words. e.g. 628.94 → 'Rupees Six Hundred Twenty-Eight and Ninety-Four Paise Only'"""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two_digits(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + '-' + ones[n % 10]).rstrip('-')

    def _three_digits(n):
        if n == 0:
            return ''
        if n < 100:
            return _two_digits(n)
        return ones[n // 100] + ' Hundred' + (' ' + _two_digits(n % 100) if n % 100 else '')

    def _indian_number(n):
        """Indian numbering: lakhs and crores."""
        if n == 0:
            return 'Zero'
        parts = []
        if n >= 10000000:
            parts.append(_two_digits(n // 10000000) + ' Crore')
            n %= 10000000
        if n >= 100000:
            parts.append(_two_digits(n // 100000) + ' Lakh')
            n %= 100000
        if n >= 1000:
            parts.append(_two_digits(n // 1000) + ' Thousand')
            n %= 1000
        if n > 0:
            parts.append(_three_digits(n))
        return ' '.join(parts)

    rupees = int(amount)
    paise = round((amount - rupees) * 100)

    result = 'Rupees ' + _indian_number(rupees)
    if paise > 0:
        result += ' and ' + _two_digits(paise) + ' Paise'
    result += ' Only'
    return result


def _wrap_text(text, max_chars):
    """Wrap text to max characters per line."""
    words = text.split()
    lines = []
    current = ''
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = current + ' ' + word if current else word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text[:max_chars]]


# ─── Generate Invoice PDF ───

def generate_invoice_pdf(invoice_id: str, request_id: str) -> Dict:
    """Generate invoice PDF and upload to S3."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    html = _build_invoice_html(invoice, items)

    # Primary: render receipt PNG and convert to PDF via PIL
    try:
        from PIL import Image as PILImage
        png_bytes = _generate_receipt_png(invoice, items)
        png_img = PILImage.open(io.BytesIO(png_bytes)).convert('RGB')
        pdf_buf = io.BytesIO()
        png_img.save(pdf_buf, format='PDF', resolution=150)
        pdf_bytes = pdf_buf.getvalue()
    except Exception as e:
        logger.warning(f"PIL PDF render failed: {e}, using fallback")
        try:
            pdf_bytes = _render_html_to_pdf(html)
        except Exception:
            pdf_bytes = _generate_html_pdf_fallback(html)

    ref_id = invoice.get('referenceId', invoice_id)
    s3_key = f"{INVOICE_PREFIX}wecare-digital-{ref_id}.pdf"

    s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=s3_key,
        Body=pdf_bytes,
        ContentType='application/pdf',
        CacheControl='max-age=86400',
    )

    # Signed and expiring, for the same reason as the PNG above: `s3_key` is under
    # `INVOICE_PREFIX`, which is now the gated root, so a CDN URL would be a dead link.
    pdf_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Store asset record. `url` is deliberately not persisted — a presigned URL expires, and a
    # stored one is correct when written and silently broken afterwards.
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    assets_table.put_item(Item={
        'invoiceId': invoice_id,
        'assetType': 'pdf',
        's3Key': s3_key,
        'contentType': 'application/pdf',
        'version': int(time.time()),
        'generatedAt': int(time.time()),
    })

    logger.info(json.dumps({'event': 'invoice_pdf_generated', 'invoiceId': invoice_id, 'url': pdf_url, 'requestId': request_id}))
    return _resp(200, {'invoiceId': invoice_id, 'pdfUrl': pdf_url, 's3Key': s3_key})


def _render_html_to_pdf(html: str) -> bytes:
    """Render HTML to PDF. Uses PIL image-to-PDF as primary approach."""
    raise ImportError("Use image-based PDF approach")


def _generate_html_pdf_fallback(html: str) -> bytes:
    """Generate a minimal placeholder PDF. Real PDF uses image-based approach."""
    html_bytes = html.encode('utf-8')

    # Minimal PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

4 0 obj
<< /Length """ + str(len(b"BT /F1 14 Tf 50 780 Td (INVOICE) Tj ET BT /F1 10 Tf 50 750 Td (Please view the HTML version for full invoice details.) Tj ET BT /F1 10 Tf 50 730 Td (Download the image version for a formatted view.) Tj ET")).encode() + b""" >>
stream
BT /F1 14 Tf 50 780 Td (INVOICE) Tj ET BT /F1 10 Tf 50 750 Td (Please view the HTML version for full invoice details.) Tj ET BT /F1 10 Tf 50 730 Td (Download the image version for a formatted view.) Tj ET
endstream
endobj

xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000206 00000 n 

trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF"""

    return pdf_content


# ─── Send Pending Invoices by Phone (instant pay flow) ───

def send_pending_by_phone(body: Dict, request_id: str) -> Dict:
    """Find all pending invoices for a customer phone.
    Sequential pay: sends payment link for the FIRST (oldest) invoice only.
    Returns the full list so the inbound handler can show a summary.
    After each payment is captured, _check_and_notify_balance_due auto-sends the next one.
    """
    customer_phone = body.get('customerPhone', '')
    phone_number_id = body.get('phoneNumberId', '')
    if not customer_phone:
        return _resp(400, {'error': 'customerPhone required'})

    # Normalize phone for matching — strip everything except digits
    clean = customer_phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
    # For Indian numbers: normalize to 10-digit local number for matching
    # This handles: +919876543210, 919876543210, 09876543210, 9876543210
    if clean.startswith('91') and len(clean) == 12:
        local10 = clean[2:]  # Strip country code
    elif clean.startswith('0') and len(clean) == 11:
        local10 = clean[1:]  # Strip leading 0
    elif len(clean) == 10:
        local10 = clean
    else:
        local10 = clean[-10:] if len(clean) >= 10 else clean

    # Scan InvoicesTable for pending invoices matching this phone
    table = dynamodb.Table(INVOICES_TABLE)
    pending_statuses = ('created', 'pending_payment', 'sent')
    all_pending = []

    try:
        scan_kwargs = {
            'FilterExpression': (
                boto3.dynamodb.conditions.Attr('status').is_in(list(pending_statuses))
            ),
        }
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get('Items', []):
                inv_phone_raw = (item.get('customerPhone', '') or '').replace('+', '').replace(' ', '').replace('-', '')
                # Normalize invoice phone to 10-digit local number
                if inv_phone_raw.startswith('91') and len(inv_phone_raw) == 12:
                    inv_local10 = inv_phone_raw[2:]
                elif inv_phone_raw.startswith('0') and len(inv_phone_raw) == 11:
                    inv_local10 = inv_phone_raw[1:]
                elif len(inv_phone_raw) == 10:
                    inv_local10 = inv_phone_raw
                else:
                    inv_local10 = inv_phone_raw[-10:] if len(inv_phone_raw) >= 10 else inv_phone_raw
                # STRICT match: full 10-digit local number must match exactly
                if inv_local10 == local10 and len(local10) == 10:
                    all_pending.append(item)
            if 'LastEvaluatedKey' in resp:
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            else:
                break
    except Exception as e:
        logger.error(json.dumps({'event': 'send_pending_scan_error', 'error': str(e), 'requestId': request_id}))
        return _resp(500, {'error': f'Failed to query invoices: {e}'})

    if not all_pending:
        return _resp(200, {'sent': 0, 'total': 0, 'message': 'No pending invoices', 'invoices': []})

    # Sort by createdAt ascending (oldest first)
    all_pending.sort(key=lambda x: int(x.get('createdAt', 0)))

    # Build invoice list for summary
    invoice_list = []
    for inv in all_pending:
        purpose = inv.get('purpose', '') or ''
        # Clean up raw menu action IDs stored as purpose
        if purpose.lower().startswith('menu_'):
            purpose = ''
        invoice_list.append({
            'invoiceId': inv.get('invoiceId', ''),
            'referenceId': inv.get('referenceId', ''),
            'total': float(inv.get('total', 0)),
            'purpose': purpose,
            'orderId': inv.get('orderId', ''),
            'status': 'pending',
        })

    # Send payment link for FIRST invoice only (sequential pay)
    first = all_pending[0]
    first_id = first.get('invoiceId', '')
    # Use the PG config stored on the invoice (set by admin at creation time)
    # Falls back to empty string → outbound handler uses phone's default Razorpay
    first_pg_config = first.get('paymentConfiguration', '') or ''
    send_error = ''
    try:
        result = send_payment_link(first_id, phone_number_id, first_pg_config, request_id,
                                   verify_phone=customer_phone)
        result_code = result.get('statusCode', 0)
        if result_code == 200:
            invoice_list[0]['status'] = 'sent'
        else:
            invoice_list[0]['status'] = 'failed'
            # Extract error from response body for debugging
            try:
                err_body = json.loads(result.get('body', '{}'))
                send_error = err_body.get('error', f'statusCode={result_code}')
            except Exception:
                send_error = f'statusCode={result_code}'
            logger.error(json.dumps({'event': 'send_first_link_failed', 'invoiceId': first_id, 'statusCode': result_code, 'error': send_error, 'requestId': request_id}))
    except Exception as e:
        logger.error(json.dumps({'event': 'send_first_link_error', 'invoiceId': first_id, 'error': str(e), 'requestId': request_id}))
        invoice_list[0]['status'] = 'failed'
        send_error = str(e)

    logger.info(json.dumps({'event': 'send_pending_complete', 'phone': mask_phone(customer_phone), 'total': len(all_pending), 'firstSent': first_id, 'sendError': send_error, 'requestId': request_id}))

    return _resp(200, {
        'sent': 1 if invoice_list[0]['status'] == 'sent' else 0,
        'total': len(invoice_list),
        'invoices': invoice_list,
        'error': send_error,
    })


# ─── Send Payment Link (WhatsApp Interactive Payment Message) ───

def send_payment_link(invoice_id: str, phone_number_id: str, payment_configuration: str,
                      request_id: str, verify_phone: str = '') -> Dict:
    """Send WhatsApp interactive payment message for a pending invoice.
    Creates the order_details message with review_and_pay action.
    payment_configuration: optional PG config name ('WECAREDIGITAL' or 'WECAREUPI').
    If empty, outbound handler uses the phone's default Razorpay config.
    verify_phone: if provided, blocks sending if invoice doesn't belong to this phone.
    """
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Don't send payment link for already paid/cancelled invoices
    status = invoice.get('status', '')
    if status in ('paid', 'cancelled'):
        return _resp(400, {'error': f'Invoice is {status}, cannot send payment link'})

    customer_phone = invoice.get('customerPhone', '')
    if not customer_phone:
        return _resp(400, {'error': 'No customer phone on invoice'})

    # SAFETY: Verify the payment link is being sent to the invoice's actual customer
    # This prevents sending customer A's invoice to customer B
    if verify_phone:
        req_clean = verify_phone.replace('+', '').replace(' ', '').replace('-', '')
        inv_clean = customer_phone.replace('+', '').replace(' ', '').replace('-', '')
        # Normalize both to 10-digit local
        req_local = req_clean[2:] if req_clean.startswith('91') and len(req_clean) == 12 else (req_clean[-10:] if len(req_clean) >= 10 else req_clean)
        inv_local = inv_clean[2:] if inv_clean.startswith('91') and len(inv_clean) == 12 else (inv_clean[-10:] if len(inv_clean) >= 10 else inv_clean)
        if req_local != inv_local:
            logger.error(json.dumps({
                'event': 'invoice_phone_mismatch_blocked',
                'invoiceId': invoice_id,
                'invoicePhone': customer_phone,
                'requestedPhone': verify_phone,
                'requestId': request_id,
            }))
            return _resp(403, {'error': 'Invoice does not belong to this customer'})

    reference_id = invoice.get('referenceId', '')
    if not reference_id:
        return _resp(400, {'error': 'No referenceId on invoice'})

    # Get invoice items
    items_table = dynamodb.Table(INVOICE_ITEMS_TABLE)
    items_resp = items_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    items = sorted(items_resp.get('Items', []), key=lambda x: int(x.get('itemIndex', 0)))

    # Build order items for WhatsApp interactive message (amounts in paise)
    # NOTE: Do NOT add convenience fee here — the outbound-whatsapp handler
    # auto-calculates and adds it as a line item (2% + 18% GST).
    # Green Packing & Notification Fee are pushed to the end of the items list.
    CHARGE_ITEM_NAMES = {'green packing', 'notification fee', 'notification/alert fee'}
    regular_items = []
    charge_items = []
    gst_rate = float(invoice.get('gstRate', 18))
    for item in items:
        amt_rupees = float(item.get('amount', 0))
        qty = int(item.get('quantity', 1))
        amt_paise = int(amt_rupees * 100)
        item_gst = float(item.get('gstRate', gst_rate))
        entry = {
            'name': item.get('name', 'Item'),
            'amount': {'value': amt_paise, 'offset': 100},
            'quantity': qty,
        }
        if item.get('name', '').strip().lower() in CHARGE_ITEM_NAMES:
            charge_items.append(entry)
        else:
            regular_items.append(entry)
    # Merge: regular items first, then charge items (Green Packing, Notification Fee) last
    merged_items = regular_items + charge_items
    order_items = []
    subtotal_paise = 0
    for i, entry in enumerate(merged_items):
        entry['retailer_id'] = f'ITEM_{i+1}'
        line_paise = entry['amount']['value'] * entry['quantity']
        subtotal_paise += line_paise
        order_items.append(entry)

    discount_paise = int(round(float(invoice.get('discount', 0)) * 100))
    shipping_paise = int(round(float(invoice.get('shipping', 0)) * 100))
    # GST (tax) and convenience fee are already computed on the invoice. The
    # checkout-template send path does NOT recompute them, so we MUST populate the
    # order_details here — otherwise the customer sees only the bare item price
    # (missing GST + convenience fee, and a total that mismatches the invoice).
    gst_paise = int(round(float(invoice.get('tax', 0)) * 100))
    conv_paise = int(round(float(invoice.get('convenienceFee', 0)) * 100))
    # Meta's order_details has no dedicated fee field, so add the convenience fee as
    # a transparent line item (its own GST is already baked into convenienceFee).
    if conv_paise > 0:
        order_items.append({
            'name': 'Convenience Fee (2% + GST)',
            'amount': {'value': conv_paise, 'offset': 100},
            'quantity': 1,
            'retailer_id': f'ITEM_{len(order_items) + 1}',
        })
        subtotal_paise += conv_paise
    # Internally-consistent total (Meta validates total == subtotal + tax + shipping - discount).
    total_paise = subtotal_paise + gst_paise + shipping_paise - discount_paise

    order_id = invoice.get('orderId', 'Offline')

    # Look up contact
    contact = _lookup_contact_by_phone(customer_phone)
    contact_id = (contact.get('contactId') or contact.get('id', '')) if contact else ''

    # ── Payment messages go from the SAME phone the customer is chatting with ──
    # CRITICAL: Never cross-WABA — WABA 1 configs only work on WABA 1, WABA 2 on WABA 2.
    # If no phone_number_id was passed (e.g. dashboard send without phone selection),
    # we MUST still pick the right phone. Use the invoice's stored config to infer.
    if not phone_number_id:
        # The payment configuration name CANNOT identify the WABA any more. Before
        # 2026-08-23 WABA1 used hyphenated names (WECARE-DIGITAL, WECARE-UPIVPA)
        # and WABA2 used its own, so a 'WECARE-'/'UPIVPA' substring test worked.
        # Meta rebuilt the configs that day and both WABAs now expose the
        # IDENTICAL pair WECAREDIGITAL / WECAREUPI - neither contains a hyphen and
        # neither contains 'UPIVPA', so that test matched nothing and every
        # unresolved invoice fell through to Phone 2 regardless of origin.
        #
        # Use the authoritative record instead: awsPhoneNumberId is written onto
        # the invoice at send time (see the update below), which is the same field
        # razorpay-webhook._resolve_originating_phone trusts first.
        phone_number_id = invoice.get('awsPhoneNumberId') or invoice.get('phoneNumberId') or ''
        if not phone_number_id:
            # Fall back to the PRIMARY identity, not the secondary.
            #
            # This default used to be Phone 2. That was wrong on two counts.
            # Phone 1 (+919330994400, WABA 2094615664435155) is the documented
            # primary business identity. More importantly Phone 2 is marked
            # `paymentProtected: true` in src/config/constants.ts, and the UI
            # gates it behind "Admin authorization required for this number"
            # before an operator may send payments from it. Defaulting to it
            # server-side meant any path that omitted a phone id bypassed that
            # admin check entirely - an authorization inconsistency, not just an
            # odd choice of sender.
            phone_number_id = 'phone-number-id-waba1-direct-1016149501586345'  # Phone 1 (primary)
            logger.warning(json.dumps({
                'event': 'invoice_phone_unresolved_using_primary',
                'invoiceId': invoice.get('invoiceId', ''),
                'paymentConfiguration': payment_configuration or invoice.get('paymentConfiguration', ''),
                'phoneId': phone_number_id,
                'note': 'config name cannot identify a WABA; both expose '
                        'WECAREDIGITAL/WECAREUPI. Defaulting to the primary '
                        'identity; never to the admin-gated secondary.',
            }))

    # Build payload for outbound-whatsapp Lambda
    # Determine goods type: use stored value from invoice creation.
    # Default to digital-goods — physical-goods should only be set explicitly by the admin.
    # IMPORTANT: Do NOT infer physical-goods from shippingAddress existence — that caused
    # invoices to incorrectly trigger address collection flow.
    ship_addr = invoice.get('shippingAddress', '')
    bill_addr = invoice.get('billingAddress', '')
    cust_name = invoice.get('customerName', 'Customer')
    goods_type = invoice.get('goodsType', 'digital-goods')

    # Respect the invoice's goodsType. Services / digital goods (e.g. the ₹2
    # service sample) must NOT prompt for a delivery address — only physical
    # goods collect shipping_info. Forcing physical-goods everywhere made every
    # service checkout demand an address, which is wrong and confusing.
    order_type = 'physical-goods' if goods_type == 'physical-goods' else 'digital-goods'

    order_details_obj = {
        'reference_id': reference_id,
        'type': order_type,
        'payment_configuration': payment_configuration or invoice.get('paymentConfiguration', ''),
        'currency': 'INR',
        'itemName': order_items[0]['name'] if order_items else 'Payment',
        'quantity': 1,
        'gstRate': gst_rate,
        'gstin': invoice.get('gstin', COMPANY['gstin']),
        'orderId': order_id,
        'total_amount': {'value': total_paise, 'offset': 100},
        'order': {
            'status': 'pending',
            'items': order_items,
            'subtotal': {'value': subtotal_paise, 'offset': 100},
            'discount': {'value': discount_paise, 'offset': 100, 'description': 'Promo'},
            'shipping': {'value': shipping_paise, 'offset': 100, 'description': 'Express'},
            'tax': {'value': gst_paise, 'offset': 100, 'description': f'GSTIN: {COMPANY["gstin"]}'},
        },
    }

    # ── Address / shipping_info: physical goods ONLY ──
    if order_type == 'physical-goods':
        # Pre-fill from the invoice first, then the CONTACT's saved structured
        # address (captured on a previous Address Message → _handle_address_submission,
        # which persists addressLine1/city/state/postalCode/landmark on the contact).
        c = contact or {}
        a_name = cust_name or c.get('contactBookName') or c.get('name') or 'Customer'
        a_line1 = invoice.get('addressLine1') or c.get('addressLine1') or ''
        a_city = invoice.get('city') or c.get('city') or ''
        a_state = invoice.get('state') or c.get('state') or ''
        a_postal = str(invoice.get('postalCode') or c.get('postalCode') or '')
        a_land = (invoice.get('addressLine2') or invoice.get('landmark')
                  or c.get('landmark') or '')
        if a_line1 and a_city and a_postal:
            # Known address → pre-fill so the customer can confirm in one tap.
            order_details_obj['shipping_info'] = {
                'country': 'IN',
                'addresses': [{
                    'name': a_name,
                    'phone_number': customer_phone.replace('+', ''),
                    'address': a_line1,
                    'city': a_city,
                    'state': a_state or a_city,
                    'in_pin_code': a_postal[:6],
                    'landmark_area': a_land,
                }],
            }
        else:
            # No address on file → empty array so WhatsApp collects it at checkout
            # (the submitted address is saved back to the contact on nfm_reply).
            order_details_obj['shipping_info'] = {'country': 'IN', 'addresses': []}
    # digital-goods / services: no shipping_info → no address prompt.

    wa_payload = {
        'body': json.dumps({
            'contactId': contact_id,
            'recipientPhone': customer_phone,
            'phoneNumberId': phone_number_id,
            # ALWAYS use checkout button template (wecarepay_wa) for ALL payments.
            # This enables: address display, coupon support, real-time pricing.
            # Meta confirmed checkout endpoint is enabled — no separate linking needed.
            # Set physical-goods to enable shipping_info + address collection.
            'isCheckoutTemplate': True,
            'isTemplate': True,
            'templateName': 'wecarepay_wa',
            'templateParams': [],  # wecarepay_wa has no body variables
            'checkoutOrderDetails': order_details_obj,
            # FIXED company-logo header on EVERY payment. Do not vary per order.
            'headerImageUrl': 'https://wecare.digital/get/o/public/wa-tpl/img/wecarepay-header.png',
        })
    }

    try:
        wa_response = lambda_client.invoke(
            FunctionName='wecare-outbound-whatsapp',
            InvocationType='RequestResponse',
            Payload=json.dumps(wa_payload),
        )
        wa_result = json.loads(wa_response['Payload'].read())
        wa_status_code = wa_result.get('statusCode', wa_response.get('StatusCode', 0))
        if wa_status_code >= 400:
            logger.error(json.dumps({'event': 'payment_link_outbound_error', 'invoiceId': invoice_id, 'statusCode': wa_status_code, 'body': wa_result.get('body', ''), 'requestId': request_id}))
    except Exception as e:
        logger.error(f"Payment link send error: {e}")
        return _resp(500, {'error': f'Failed to send payment link: {e}'})

    # Update invoice status to pending_payment
    try:
        # Persist the sending business phone id on the invoice so the Razorpay
        # webhook can reply + open the post-payment flow from the SAME WABA
        # (never cross-WABA). This is the most reliable phone source.
        _upd_expr = 'SET #st = :st, #ua = :now'
        _upd_names = {'#st': 'status', '#ua': 'updatedAt'}
        _upd_vals = {':st': 'pending_payment', ':now': int(time.time())}
        if phone_number_id:
            _upd_expr += ', awsPhoneNumberId = :ph'
            _upd_vals[':ph'] = phone_number_id
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression=_upd_expr,
            ExpressionAttributeNames=_upd_names,
            ExpressionAttributeValues=_upd_vals,
        )
    except Exception as e:
        logger.error(f'Failed to update invoice {invoice_id} status to pending_payment: {e}')

    # NOTE: Do NOT send invoice image here — receipt with PAID stamp
    # is generated and sent AFTER payment is captured (in inbound handler).

    # Log delivery
    delivery_table = dynamodb.Table(INVOICE_DELIVERY_TABLE)
    delivery_table.put_item(Item={
        'invoiceId': invoice_id,
        'timestamp': int(time.time()),
        'channel': 'whatsapp_payment',
        'toNumber': customer_phone,
        'waMessageId': '',
        'status': 'sent' if wa_status_code in (200, 202) else 'failed',
        'imageUrl': '',
        'phoneNumberId': phone_number_id,
        'contactId': contact_id,
        'error': '',
    })

    logger.info(json.dumps({
        'event': 'payment_link_sent', 'invoiceId': invoice_id,
        'referenceId': reference_id, 'toPhone': mask_phone(customer_phone),
        'total': float(invoice.get('total', 0)), 'requestId': request_id,
    }))

    return _resp(200, {
        'invoiceId': invoice_id,
        'referenceId': reference_id,
        'status': 'payment_link_sent',
        'toPhone': customer_phone,
        'total': float(invoice.get('total', 0)),
    })


# ─── Cancel Invoice ───

def cancel_invoice(invoice_id: str, reason: str, request_id: str) -> Dict:
    """Cancel/void an invoice. Cannot cancel already-paid invoices."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    # Money-moved guard, and it used to fail OPEN. It compared `== 'captured'` against a field
    # that is written with at least two spellings for one state: `payment_status` measured
    # `InvoicesTable.status` and `OrderTable.paymentStatus` saying `paid` where `PaymentsTable`
    # says `captured`. So an invoice stored as `paid` sailed past this check and got cancelled.
    #
    # Ranked rather than compared, so it also catches `refunded` and `disputed`. Cancelling a
    # refunded invoice would erase the record that money was taken and returned, and cancelling a
    # disputed one destroys the evidence while the dispute is live. Anything at or past `captured`
    # means money moved, and none of those may be voided.
    current_status = invoice.get('paymentStatus', '')
    if pay_status.rank(current_status) >= pay_status.STATUS_RANK[pay_status.CAPTURED]:
        return _resp(400, {
            'error': 'Cannot cancel a paid invoice. Use refund instead.',
            'paymentStatus': pay_status.canonical(current_status),
        })

    try:
        # Preserve existing notes, append cancellation reason
        existing_notes = invoice.get('notes', '')
        cancel_note = f"Cancelled: {reason}" if reason else 'Cancelled by admin'
        new_notes = f"{existing_notes}\n{cancel_note}".strip() if existing_notes else cancel_note

        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET #st = :st, #ps = :ps, #ua = :now, #notes = :notes',
            ExpressionAttributeNames={
                '#st': 'status', '#ps': 'paymentStatus',
                '#ua': 'updatedAt', '#notes': 'notes',
            },
            ExpressionAttributeValues={
                ':st': 'cancelled',
                ':ps': 'cancelled',
                ':now': int(time.time()),
                ':notes': new_notes,
            },
        )
    except Exception as e:
        return _resp(500, {'error': str(e)})

    logger.info(json.dumps({
        'event': 'invoice_cancelled', 'invoiceId': invoice_id,
        'reason': reason, 'requestId': request_id,
    }))

    return _resp(200, {'invoiceId': invoice_id, 'status': 'cancelled'})


# ─── Delete Invoice (hard delete + sequence adjustment) ───

def delete_invoice(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """Hard delete an invoice and optionally adjust the sequence counter."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    inv_number = invoice.get('invoiceNumber', '')
    ref_id = invoice.get('referenceId', '')

    # Delete associated S3 assets (images, PDFs)
    try:
        assets_resp = table.query(
            IndexName='invoiceId-index',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id),
        ) if False else {'Items': []}  # Assets are in same table as nested or separate
    except Exception as e:
        logger.warning(f'Invoice asset query failed for {invoice_id}: {e}')

    # Try to delete S3 files for this invoice
    try:
        prefix = f'{INVOICE_PREFIX}wecare-digital-{ref_id or invoice_id}'
        s3_resp = s3.list_objects_v2(Bucket=MEDIA_BUCKET, Prefix=prefix, MaxKeys=20)
        for obj in s3_resp.get('Contents', []):
            s3.delete_object(Bucket=MEDIA_BUCKET, Key=obj['Key'])
            logger.info(json.dumps({'event': 'invoice_s3_deleted', 'key': obj['Key']}))
    except Exception as s3_err:
        logger.warning(json.dumps({'event': 'invoice_s3_delete_error', 'error': str(s3_err)}))

    # Delete the invoice record
    try:
        table.delete_item(Key={'invoiceId': invoice_id})
    except Exception as e:
        return _resp(500, {'error': str(e)})

    # Adjust sequence counter if requested
    adjust_seq = body.get('adjustSequence', False)
    if adjust_seq and inv_number:
        try:
            # Extract FY and sequence from invoice number (format: WD/25-26/000042)
            parts = inv_number.split('/')
            if len(parts) == 3:
                fy = parts[1]
                seq_table = dynamodb.Table(INVOICES_TABLE.replace('InvoicesTable', 'SystemConfigTable'))
                seq_table.update_item(
                    Key={'id': f'invoice_seq_{fy}'},
                    UpdateExpression='SET lastSeq = lastSeq - :one',
                    ConditionExpression='lastSeq > :zero',
                    ExpressionAttributeValues={':one': 1, ':zero': 0},
                )
        except Exception as seq_err:
            logger.warning(json.dumps({'event': 'seq_adjust_error', 'error': str(seq_err)}))

    logger.info(json.dumps({
        'event': 'invoice_deleted', 'invoiceId': invoice_id,
        'invoiceNumber': inv_number, 'requestId': request_id,
    }))

    return _resp(200, {'invoiceId': invoice_id, 'deleted': True, 'invoiceNumber': inv_number})


# ─── Clear All Invoice Data (admin cleanup) ───

def clear_all_invoice_data(request_id: str) -> Dict:
    """Wipe all invoice-related tables: Invoices, InvoiceItems, InvoiceAssets, InvoiceDeliveryLog, InvoiceSequence, Payments, RazorpayWebhookLog. Also clears S3 invoices/ prefix."""
    tables_to_clear = {
        'invoices': (INVOICES_TABLE, 'invoiceId'),
        'invoice_items': (INVOICE_ITEMS_TABLE, None),
        'invoice_assets': (INVOICE_ASSETS_TABLE, None),
        'invoice_delivery_log': (INVOICE_DELIVERY_TABLE, None),
        'invoice_sequence': (INVOICE_SEQ_TABLE, None),
        'payments': (PAYMENTS_TABLE, 'id'),
        'razorpay_webhook_log': ('stack-wecare-digital-RazorpayWebhookLogTable', 'id'),
    }
    results = {}
    total = 0
    ddb_client = boto3.client('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

    for key, (table_name, known_pk) in tables_to_clear.items():
        try:
            # Discover key schema
            desc = ddb_client.describe_table(TableName=table_name)
            key_names = [k['AttributeName'] for k in desc['Table']['KeySchema']]
            table = dynamodb.Table(table_name)
            deleted = 0
            scan_kwargs = {'ProjectionExpression': ', '.join([f'#{chr(97+i)}' for i in range(len(key_names))]),
                           'ExpressionAttributeNames': {f'#{chr(97+i)}': n for i, n in enumerate(key_names)}}
            while True:
                resp = table.scan(**scan_kwargs)
                items = resp.get('Items', [])
                if not items:
                    break
                with table.batch_writer() as batch:
                    for item in items:
                        batch.delete_item(Key={k: item[k] for k in key_names})
                        deleted += 1
                if 'LastEvaluatedKey' not in resp:
                    break
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            results[key] = deleted
            total += deleted
        except Exception as e:
            logger.warning(f"Clear {key} error: {e}")
            results[key] = 0

    # Clear S3 invoices/ prefix
    s3_deleted = 0
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=MEDIA_BUCKET, Prefix=INVOICE_PREFIX):
            objects = page.get('Contents', [])
            if objects:
                s3.delete_objects(Bucket=MEDIA_BUCKET, Delete={'Objects': [{'Key': o['Key']} for o in objects]})
                s3_deleted += len(objects)
        results['s3_invoices'] = s3_deleted
        total += s3_deleted
    except Exception as e:
        logger.warning(f"Clear S3 invoices error: {e}")
        results['s3_invoices'] = 0

    logger.info(json.dumps({'event': 'clear_all_invoice_data', 'results': results, 'total': total, 'requestId': request_id}))
    return _resp(200, {'success': True, 'results': results, 'totalDeleted': total})


# ─── Add Remark / Refund / Credit Note ───

def add_remark(invoice_id: str, body: Dict, request_id: str) -> Dict:
    """Add a remark, refund note, or credit note to an invoice."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    remark_type = body.get('type', 'remark')  # remark | refund | credit_note
    text = body.get('text', '')
    amount = float(body.get('amount', 0))
    author = body.get('author', 'admin')

    if not text and remark_type == 'remark':
        return _resp(400, {'error': 'text required for remarks'})

    table = dynamodb.Table(INVOICES_TABLE)
    resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = resp.get('Item')
    if not invoice:
        return _resp(404, {'error': 'Invoice not found'})

    now = int(time.time())
    remark_entry = {
        'id': str(uuid.uuid4())[:8],
        'type': remark_type,
        'text': text,
        'amount': amount,
        'author': author,
        'createdAt': now,
    }

    # Append to remarks list
    existing_remarks = invoice.get('remarks', [])
    if isinstance(existing_remarks, str):
        existing_remarks = json.loads(existing_remarks) if existing_remarks else []
    existing_remarks.append(remark_entry)

    update_expr = 'SET remarks = :r, updatedAt = :now'
    expr_values = {
        ':r': json.dumps(existing_remarks),
        ':now': now,
    }

    # For refund/credit note, also update status
    if remark_type == 'refund':
        update_expr += ', refundAmount = :ra, refundAt = :rat, paymentStatus = :ps'
        expr_values[':ra'] = _dec(amount)
        expr_values[':rat'] = now
        expr_values[':ps'] = 'refunded'
    elif remark_type == 'credit_note':
        update_expr += ', creditNoteAmount = :cna, creditNoteAt = :cnt'
        expr_values[':cna'] = _dec(amount)
        expr_values[':cnt'] = now

    try:
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
    except Exception as e:
        return _resp(500, {'error': str(e)})

    logger.info(json.dumps({
        'event': f'invoice_{remark_type}_added', 'invoiceId': invoice_id,
        'remarkType': remark_type, 'amount': amount, 'requestId': request_id,
    }))

    return _resp(200, {
        'invoiceId': invoice_id,
        'remark': remark_entry,
        'totalRemarks': len(existing_remarks),
    })


# ─── Send Invoice on WhatsApp ───

def send_invoice_whatsapp(invoice_id: str, to_phone: str, phone_number_id: str, request_id: str) -> Dict:
    """Send invoice image via WhatsApp. Calls outbound-whatsapp Lambda."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})
    if not to_phone:
        return _resp(400, {'error': 'toWhatsAppNumber required'})

    # Ensure image exists, generate if not
    assets_table = dynamodb.Table(INVOICE_ASSETS_TABLE)
    try:
        asset_resp = assets_table.get_item(Key={'invoiceId': invoice_id, 'assetType': 'image'})
        asset = asset_resp.get('Item')
    except Exception:
        asset = None

    if not asset or not asset.get('url'):
        # Generate image first
        gen_result = generate_invoice_image(invoice_id, request_id)
        gen_body = json.loads(gen_result.get('body', '{}'))
        if gen_result.get('statusCode') != 200:
            return _resp(500, {'error': 'Failed to generate invoice image', 'detail': gen_body})
        image_url = gen_body.get('imageUrl', '')
        s3_key = gen_body.get('s3Key', '')
    else:
        # A previously rendered asset. `url` is no longer stored, because a presigned one expires
        # and this is the read that would have served the stale copy - so the link is re-signed
        # from the key on every send.
        s3_key = asset.get('s3Key', '')
        image_url = _signed_invoice_url(s3_key, invoice_id, request_id)

    # Guard on `s3_key`, which is what delivery actually needs. It used to guard on `image_url`
    # and then send `mediaFile: s3_key`, so it tested one variable and used another: a row with a
    # URL but no key passed the check and sent a message with no media, and a row with a key but
    # no URL was refused despite being perfectly deliverable.
    if not s3_key:
        return _resp(500, {'error': 'No invoice image available'})

    # Fetch invoice for caption
    table = dynamodb.Table(INVOICES_TABLE)
    inv_resp = table.get_item(Key={'invoiceId': invoice_id})
    invoice = inv_resp.get('Item', {})
    total = float(invoice.get('total', 0))
    order_id = invoice.get('orderId', '')
    reference_id = invoice.get('referenceId', '')
    invoice_number = str(invoice.get('invoiceNumber', '') or '')
    order_line = f"\nOrder: {order_id}" if order_id and order_id != 'Offline' else ''
    ref_line = f"\nRef: {reference_id}" if reference_id else ''
    # The caption is the only part of this message a customer can search, forward or read without
    # opening the image, so the invoice number belongs in it as well as on the document. Omitted
    # entirely when absent, like the Order and Ref lines above - a label with nothing after it
    # reads as a bug.
    invoice_line = f"\nInvoice: {invoice_number}" if invoice_number else ''
    # Every line here is an identifier or a label. NO PERSONAL DATA: no phone, no name, no
    # address. A WhatsApp caption is rendered in notification previews and in forwards, so it is
    # the least private surface this engine writes to, and the document inside the image already
    # carries the bill-to details for the one recipient entitled to them.
    source_line = f"\nOrdered on: {_source_label(invoice)}"
    # The public customer id belongs here and the phone does not, and that distinction is the
    # whole rule this caption is written to: the id is OURS, opaque, carries no timestamp and
    # identifies nobody to a stranger reading a notification preview, whereas the phone, the name
    # and the address identify the recipient to whoever is holding the handset. So this line is
    # an identifier joining the ones already here, not an exception to the no-personal-data
    # property. Omitted when absent, like the Invoice, Order and Ref lines above.
    customer_id = _customer_id(invoice)
    customer_id_line = f"\nCustomer ID: {customer_id}" if customer_id else ''
    caption = (f"Invoice \u20b9{total:,.2f}{invoice_line}{order_line}{ref_line}{source_line}"
               f"{customer_id_line}"
               f"\nThank you for your payment!")

    # Look up contact by phone
    contact = _lookup_contact_by_phone(to_phone)
    contact_id = (contact.get('contactId') or contact.get('id', '')) if contact else ''

    # Default phone number ID
    if not phone_number_id:
        phone_number_id = 'phone-number-id-waba1-direct-1016149501586345'

    # Call outbound-whatsapp Lambda to send image
    wa_payload = {
        'body': json.dumps({
            'contactId': contact_id,
            'recipientPhone': to_phone,
            'content': caption,
            'phoneNumberId': phone_number_id,
            'mediaFile': s3_key,
            'mediaType': 'image',
        })
    }

    try:
        wa_response = lambda_client.invoke(
            FunctionName='wecare-outbound-whatsapp',
            InvocationType='RequestResponse',
            Payload=json.dumps(wa_payload),
        )
        wa_result = json.loads(wa_response['Payload'].read())
        wa_body = json.loads(wa_result.get('body', '{}'))
        wa_message_id = wa_body.get('whatsappMessageId', wa_body.get('messageId', ''))
        wa_status = wa_body.get('status', 'unknown')
    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        wa_message_id = ''
        wa_status = 'failed'

    # Log delivery
    delivery_table = dynamodb.Table(INVOICE_DELIVERY_TABLE)
    delivery_table.put_item(Item={
        'invoiceId': invoice_id,
        'timestamp': int(time.time()),
        'channel': 'whatsapp',
        'toNumber': to_phone,
        'waMessageId': wa_message_id,
        'status': wa_status,
        'imageUrl': image_url,
        'phoneNumberId': phone_number_id,
        'contactId': contact_id,
        'error': '' if wa_status != 'failed' else 'WhatsApp send failed',
    })

    # Update invoice status
    if wa_status in ('sent', 'delivered'):
        table.update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='SET #st = :st, #ua = :now',
            ExpressionAttributeNames={'#st': 'status', '#ua': 'updatedAt'},
            ExpressionAttributeValues={':st': 'sent', ':now': int(time.time())},
        )

    logger.info(json.dumps({
        'event': 'invoice_whatsapp_sent', 'invoiceId': invoice_id,
        'waMessageId': wa_message_id, 'status': wa_status,
        'toNumber': mask_phone(to_phone), 'requestId': request_id,
    }))

    return _resp(200, {
        'invoiceId': invoice_id,
        'waMessageId': wa_message_id,
        'status': wa_status,
        'imageUrl': image_url,
    })


# ─── Delivery Log ───

def get_delivery_log(invoice_id: str, request_id: str) -> Dict:
    """Get delivery log for an invoice."""
    if not invoice_id:
        return _resp(400, {'error': 'invoiceId required'})

    table = dynamodb.Table(INVOICE_DELIVERY_TABLE)
    resp = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('invoiceId').eq(invoice_id)
    )
    logs = resp.get('Items', [])
    logs.sort(key=lambda x: int(x.get('timestamp', 0)), reverse=True)

    return _resp(200, {
        'invoiceId': invoice_id,
        'deliveryLogs': [{
            'timestamp': int(l.get('timestamp', 0)),
            'channel': l.get('channel', ''),
            'toNumber': l.get('toNumber', ''),
            'waMessageId': l.get('waMessageId', ''),
            'status': l.get('status', ''),
            'error': l.get('error', ''),
            'imageUrl': l.get('imageUrl', ''),
        } for l in logs],
        'count': len(logs),
    })


# ─── Helper Functions ───

def _lookup_contact_by_phone(phone: str) -> Optional[Dict]:
    """Look up a contact by phone number."""
    if not phone:
        return None
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        # Normalize phone
        clean = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not clean.startswith('+'):
            clean = '+' + clean

        # Fast path: exact-match via the phone-index GSI (avoids a table scan).
        try:
            from boto3.dynamodb.conditions import Key
            q = table.query(IndexName='phone-index', KeyConditionExpression=Key('phone').eq(clean))
            if q.get('Items'):
                return q['Items'][0]
        except Exception as e:
            logger.debug(f"phone-index query failed, falling back to scan: {e}")

        # Fallback: paginated fuzzy scan (last-10-digit contains) for numbers
        # not stored in normalized E.164 form.
        scan_kwargs = {'FilterExpression': boto3.dynamodb.conditions.Attr('phone').contains(clean[-10:])}
        items = []
        while True:
            result = table.scan(**scan_kwargs)
            items = result.get('Items', [])
            if items or 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Contact lookup error: {e}")
        return None


def _normalize_invoice(item: Dict) -> Dict:
    """Normalize invoice record for API response."""
    return {
        'invoiceId': item.get('invoiceId', ''),
        'invoiceNumber': item.get('invoiceNumber', ''),
        'paymentId': item.get('paymentId', ''),
        'orderId': item.get('orderId', ''),
        'referenceId': item.get('referenceId', ''),
        'entryPoint': item.get('entryPoint', ''),
        'status': item.get('status', ''),
        'paymentStatus': item.get('paymentStatus', ''),
        'contactId': item.get('contactId', ''),
        'customerName': item.get('customerName', ''),
        'customerPhone': item.get('customerPhone', ''),
        'paidByPhone': item.get('paidByPhone', ''),
        'customerEmail': item.get('customerEmail', ''),
        'shippingAddress': item.get('shippingAddress', ''),
        'billingAddress': item.get('billingAddress', ''),
        'goodsType': item.get('goodsType', 'digital-goods'),
        'subtotal': float(item.get('subtotal', 0)),
        'discount': float(item.get('discount', 0)),
        'shipping': float(item.get('shipping', 0)),
        'handling': float(item.get('handling', 0)),
        'gstRate': float(item.get('gstRate', 0)),
        'tax': float(item.get('tax', 0)),
        'convenienceFee': float(item.get('convenienceFee', 0)),
        'total': float(item.get('total', 0)),
        'currency': item.get('currency', 'INR'),
        'gstin': item.get('gstin', ''),
        'purpose': item.get('purpose', ''),
        'notes': item.get('notes', ''),
        'createdAt': int(item.get('createdAt', 0)),
        'updatedAt': int(item.get('updatedAt', 0)),
        'paidAt': int(item.get('paidAt', 0)),
    }


def _normalize_item(item: Dict) -> Dict:
    """Normalize invoice item for API response."""
    return {
        'invoiceId': item.get('invoiceId', ''),
        'itemIndex': int(item.get('itemIndex', 0)),
        'name': item.get('name', ''),
        'amount': float(item.get('amount', 0)),
        'quantity': int(item.get('quantity', 1)),
        'productId': item.get('productId', ''),
    }


def _normalize_asset(item: Dict) -> Dict:
    """Normalize invoice asset for API response.

    `url` is minted from `s3Key` rather than read from the row. Two reasons, and the first is
    why this function had to change at all: the row no longer carries a `url`, so reading one
    would return `''` for every asset — an API that silently answers "no link" rather than
    erroring. And a stored presigned URL would be worse than absent, since it is correct when
    written and quietly expired afterwards.

    Presigning is a local signature computation, not an S3 call, so doing it per row in a list
    response costs nothing on the wire.
    """
    s3_key = item.get('s3Key', '')
    invoice_id = item.get('invoiceId', '')
    return {
        'invoiceId': invoice_id,
        'assetType': item.get('assetType', ''),
        's3Key': s3_key,
        # Falls back to a legacy stored value only if signing yields nothing, so rows written
        # before the gated move still render. Those legacy URLs point at the public root and
        # will 404 there now, which is the correct failure: a dead link, not a disclosure.
        'url': _signed_invoice_url(s3_key, invoice_id, 'normalize') or item.get('url', ''),
        'contentType': item.get('contentType', ''),
        'version': int(item.get('version', 0)),
        'generatedAt': int(item.get('generatedAt', 0)),
    }


def _dec(value) -> Decimal:
    """Convert to Decimal for DynamoDB storage."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(round(float(value), 2)))


def _resp(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str),
    }
