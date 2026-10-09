"""A verified customer's existing invoice copy. Never creates financial records."""
import hashlib
import re
import time
import boto3
from botocore.exceptions import ClientError
from lambda_utils import customer_auth, media_paths, receipt_links
from lambda_utils.identity import customer_uuid
from flows import customer_orders, paid_vault

TEMPLATE = 'wecare_share_pdf'


def resolve(db, identity, order_id):
    order = db.Table('stack-wecare-digital-OrderTable').get_item(
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
    expected_key = media_paths.secure('stack/invoices/wecare-digital-' + reference + '.png')
    if asset.get('s3Key') != expected_key:
        return order, None
    return order, {'invoiceId': invoice_id, 's3Key': expected_key}


def template_ready(response):
    rows = response.get('data') or []
    eligible = [t for t in rows if t.get('name') == TEMPLATE and t.get('language') == 'en'
                and t.get('status') == 'APPROVED']
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
    table = db.Table('stack-wecare-digital-FlowSubmissionTable')
    key = {'submissionId': reference}
    row = {**key, 'submissionNumber': reference, 'flowCode': 'WD_Orders', 'flowType': 'invoice_copy',
        'subject': 'Invoice copy', 'customerId': identity.customer_id, 'contactId': session['contactId'],
        'customerUuid': customer_uuid.from_contact(contact) or '', 'phone': identity.phone,
        'orderId': order['orderId'], 'orderNumber': order['orderNumber'], 'paymentStatus': 'none',
        'invoiceId': asset['invoiceId'] if asset else '',
        'status': 'open', 'tags': ['Orders', 'Invoice copy'], 'createdAt': int(time.time())}
    try:
        table.put_item(Item=row, ConditionExpression='attribute_not_exists(submissionId)')
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
    current = table.get_item(Key=key, ConsistentRead=True).get('Item') or {}
    if current.get('customerId') != identity.customer_id or current.get('orderId') != order['orderId']:
        raise customer_auth.CustomerNotAuthorized('invoice unavailable')
    if not asset or not template_ready(get_template(TEMPLATE)):
        return {'reference': reference, 'message': 'Your invoice copy request is saved. Delivery is pending preparation. You can also check invoices on the website Orders page.'}
    link = receipt_links.signed_url(s3_client, bucket='wecare-digital-get', key=asset['s3Key'], ttl_seconds=300)
    body = {'contactId': session['contactId'], 'recipientPhone': identity.phone,
        'phoneNumberId': '1016149501586345', 'isTemplate': True, 'templateName': TEMPLATE,
        'templateParams': [], 'headerImageUrl': link}
    accepted = paid_vault._send_once(table, {}, 'invoiceDeliveryStatus', lambda_client, body, record_key=key)
    if accepted:
        table.update_item(Key=key, UpdateExpression='SET #status=:progress',
            ExpressionAttributeNames={'#status': 'status'}, ExpressionAttributeValues={':progress': 'in_progress'})
    return {'reference': reference, 'message': 'Your invoice copy was accepted for WhatsApp delivery. PDF downloads remain available on the website Orders page.' if accepted
        else 'Your invoice copy request is saved. Delivery needs verification; no payment has been requested.'}
