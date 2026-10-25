"""A verified customer's existing invoice copy. Never creates financial records."""
import hashlib
import re
import time
import boto3
from lambda_utils import customer_auth, media_paths, receipt_links, shared_tables, template_status
from lambda_utils.identity import customer_uuid
from flows import customer_orders, paid_vault

TEMPLATE = 'wecare_share_pdf'


def _key_token(value):
    """Mirror of invoice-engine `_s3_invoice_token`, which composes the stored asset key."""
    token = ''.join(ch if (ch.isalnum() or ch in '-_.') else '-' for ch in str(value or '').strip())
    while '--' in token:
        token = token.replace('--', '-')
    return token.strip('-_.') or 'unknown'


def expected_invoice_keys(invoice, reference):
    """The base `image` keys invoice-engine can have written for this invoice.

    Its stem is `wecare-digital-{reference}` for a draft and
    `wecare-digital-{invoiceNumber}__{reference}` once a number is issued, under
    INVOICE_CUSTOMER_IMAGE_PREFIX. A row first rendered as a draft keeps the draft key on its
    base row after issue, so both stay acceptable. Both embed this order's own reference,
    which is what binds the stored row to the order being served.
    """
    stem = media_paths.INVOICE_CUSTOMER_IMAGE_PREFIX + 'wecare-digital-'
    ref = _key_token(reference)
    keys = {f'{stem}{ref}.png'}
    number = str(invoice.get('invoiceNumber') or '').strip()
    if number:
        keys.add(f'{stem}{_key_token(number)}__{ref}.png')
    return keys


def resolve(db, identity, order_id):
    order = db.Table(shared_tables.orders_table_name()).get_item(
        Key={'orderId': str(order_id)}, ConsistentRead=True).get('Item') or {}
    if order.get('customerId') != identity.customer_id or not order.get('orderNumber'):
        raise customer_auth.CustomerNotAuthorized('invoice unavailable')
    reference = order.get('referenceId', '')
    if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', reference):
        return order, None
    invoices = db.Table('stack-wecare-digital-InvoicesTable')
    page = invoices.query(IndexName='referenceId-index', KeyConditionExpression='referenceId=:reference',
        ExpressionAttributeValues={':reference': reference}, Limit=2)
    entries = page.get('Items') or []
    if len(entries) != 1 or page.get('LastEvaluatedKey'):
        return order, None
    invoice_id = entries[0].get('invoiceId')
    invoice = invoices.get_item(Key={'invoiceId': invoice_id}, ConsistentRead=True).get('Item') or {}
    if invoice.get('referenceId') != reference:
        raise customer_auth.CustomerNotAuthorized('invoice unavailable')
    asset = db.Table('stack-wecare-digital-InvoiceAssetsTable').get_item(
        Key={'invoiceId': invoice_id, 'assetType': 'image'}, ConsistentRead=True).get('Item') or {}
    s3_key = asset.get('s3Key')
    if not isinstance(s3_key, str) or s3_key not in expected_invoice_keys(invoice, reference):
        return order, None
    return order, {'invoiceId': invoice_id, 's3Key': s3_key}


def template_ready(response):
    rows = response.get('data') or []
    eligible = [t for t in rows if t.get('name') == TEMPLATE and t.get('language') == 'en'
                and template_status.is_sendable(t.get('status'))]
    return len(eligible) == 1 and any(c.get('type') == 'HEADER' and c.get('format') == 'IMAGE'
        for c in eligible[0].get('components') or [])


def handle(event, get_template, lambda_client, s3_client):
    if any(k in event for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    db, contact, identity, session = customer_orders._context(event.get('flowToken', ''))
    order, asset = resolve(db, identity, event.get('orderId', ''))
    day = int(time.time()) // 86400
    reference = 'WD-INVCOPY-' + hashlib.sha256(
        f'{identity.customer_id}:{order["orderId"]}:{day}'.encode()).hexdigest()[:24].upper()
    table = db.Table(shared_tables.flow_submissions_table_name())
    key = {'submissionId': reference}
    # Created or already there, the row is re-read below either way, so ownership is checked
    # against what is stored rather than against what this call tried to write.
    customer_orders.claim_request(
        reference, 'DETAILS', identity, session['contactId'], flow_type='invoice_copy', status='open',
        fields={'subject': 'Invoice copy', 'customerUuid': customer_uuid.from_contact(contact) or '',
                'orderId': order['orderId'], 'orderNumber': order['orderNumber'],
                'invoiceId': asset['invoiceId'] if asset else '', 'tags': ['Orders', 'Invoice copy']})
    current = table.get_item(Key=key, ConsistentRead=True).get('Item') or {}
    if current.get('customerId') != identity.customer_id or current.get('orderId') != order['orderId']:
        raise customer_auth.CustomerNotAuthorized('invoice unavailable')
    if not asset or not template_ready(get_template(TEMPLATE)):
        return {'reference': reference, 'message': 'Your invoice copy request is saved. Delivery is pending preparation. You can also check invoices on the website Orders page.'}
    link = receipt_links.signed_url(s3_client, bucket='wecare-digital-get', key=asset['s3Key'], ttl_seconds=300)
    # The invoice image IS the template's IMAGE header, so it travels in the keys outbound's
    # generic builder reads; `headerImageUrl` is honoured only on the checkout path.
    body = {'contactId': session['contactId'], 'recipientPhone': identity.phone,
        'phoneNumberId': paid_vault.WABA1_SENDER, 'isTemplate': True, 'templateName': TEMPLATE,
        'templateParams': [], 'templateHeaderMedia': link, 'templateHeaderType': 'image'}
    accepted = paid_vault._send_once(table, {}, 'invoiceDeliveryStatus', lambda_client, body, record_key=key)
    if accepted:
        table.update_item(Key=key, UpdateExpression='SET #status=:progress',
            ExpressionAttributeNames={'#status': 'status'}, ExpressionAttributeValues={':progress': 'in_progress'})
    return {'reference': reference, 'message': 'Your invoice image was accepted for WhatsApp delivery.' if accepted
        else 'Your invoice image request is saved. Delivery needs verification; no payment has been requested.'}
