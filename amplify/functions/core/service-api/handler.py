"""
Service Module API — Unified REST handler for all service modules.

Routes:
  /orders                  GET (list), POST (create)
  /orders/{id}             GET, PATCH
  /orders/{id}/submissions GET
  /orders/sync             POST
  /service/submit          POST
  /service/amend           POST
  /service/track/{orderId} GET
  /service/history         GET
  /service/drafts          POST, GET, DELETE
  /documents               GET (list)
  /documents/{id}          GET, PUT
  /documents/{id}/download GET
  /faq                     GET (list), POST (create)
  /faq/{id}                PUT, DELETE
  /appointments            GET (list), POST (create)
  /appointments/{id}       PUT
  /rx-slots                GET (list), POST (create)
  /rx-slots/{id}           PUT
  /enterprise-assist       GET (list), POST (create)
  /enterprise-assist/{id}  PUT
  /reviews                 GET (list), POST (create)
  /reviews/{id}            PUT
"""
import json
import os
import time
import uuid
import logging
import hashlib
from typing import Dict, Any, Optional
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from lambda_utils import media_paths

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Table names
TABLE_PREFIX = os.environ.get('TABLE_PREFIX', 'stack-wecare-digital')
ORDERS_TABLE = f'{TABLE_PREFIX}-OrderTable'
FLOW_SUBMISSIONS_TABLE = f'{TABLE_PREFIX}-FlowSubmissionTable'
FLOW_DRAFTS_TABLE = f'{TABLE_PREFIX}-FlowDraftTable'
STATUS_HISTORY_TABLE = f'{TABLE_PREFIX}-RequestStatusHistoryTable'
DOCUMENTS_TABLE = f'{TABLE_PREFIX}-DocumentTable'
DOCUMENT_HISTORY_TABLE = f'{TABLE_PREFIX}-DocumentHistoryTable'
FAQ_TABLE = f'{TABLE_PREFIX}-FaqTable'
APPOINTMENTS_TABLE = f'{TABLE_PREFIX}-AppointmentTable'
RX_SLOTS_TABLE = f'{TABLE_PREFIX}-RxSlotTable'
ENTERPRISE_TABLE = f'{TABLE_PREFIX}-EnterpriseAssistTable'
REVIEWS_TABLE = f'{TABLE_PREFIX}-ReviewTable'
AMENDMENT_HISTORY_TABLE = f'{TABLE_PREFIX}-AmendmentHistoryTable'
AUDIT_LOG_TABLE = f'{TABLE_PREFIX}-AuditLogsTable'

# Documents ARE WhatsApp media: inbound-whatsapp writes the object and then records its
# key as DocumentTable.storageKey, so both live in the one media bucket. There has never
# been a separate documents bucket. The old default named `wecare-digital-documents` and
# the deployed value named `wecare-digital-media` — measured 2026-09-28, NEITHER EXISTS
# in this account.
#
# That failed silently, which is why it survived: generate_presigned_url signs locally
# and never contacts S3, so this endpoint kept returning 200 with a URL that only broke
# when the browser followed it.
DOCS_S3_BUCKET = os.environ.get('DOCS_S3_BUCKET', media_paths.BUCKET)

origin = '*'

def _resp(status: int, body: Any) -> Dict:
    return {
        'statusCode': status,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }

def _gen_id(prefix: str = '') -> str:
    short = hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:8].upper()
    return f'{prefix}{short}' if prefix else short

def _now() -> int:
    return int(time.time())

def _extract_origin(event: Dict) -> str:
    headers = event.get('headers', {}) or {}
    return headers.get('origin', headers.get('Origin', '*'))


# ============================================================================
# ORDERS
# ============================================================================

def _list_orders(params: Dict) -> Dict:
    table = dynamodb.Table(ORDERS_TABLE)
    kwargs: Dict[str, Any] = {}
    status = params.get('status')
    source = params.get('source')
    phone = params.get('phone')
    search = params.get('search')

    if phone:
        kwargs['IndexName'] = 'customerPhone'
        kwargs['KeyConditionExpression'] = Key('customerPhone').eq(phone)
        resp = table.query(**kwargs)
    elif status:
        kwargs['IndexName'] = 'orderStatus'
        kwargs['KeyConditionExpression'] = Key('orderStatus').eq(status)
        resp = table.query(**kwargs)
    elif source:
        kwargs['IndexName'] = 'source'
        kwargs['KeyConditionExpression'] = Key('source').eq(source)
        resp = table.query(**kwargs)
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    while resp.get('LastEvaluatedKey'):
        query = dict(kwargs, ExclusiveStartKey=resp['LastEvaluatedKey'])
        resp = table.query(**query) if kwargs else table.scan(**query)
        items.extend(resp.get('Items', []))
    for item in items:
        if item.get('paymentStatus') == 'PAYMENT_PAID':
            item['paymentStatus'] = 'paid'
        item.setdefault('status', item.get('orderStatus', 'active'))
    if search:
        q = search.lower()
        items = [i for i in items if q in (str(i.get('orderId', '')) + str(i.get('orderNumber', '')) + str(i.get('wixOrderId', '')) + str(i.get('customerName', '')) + str(i.get('customerPhone', ''))).lower()]

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    limit = int(params.get('limit', 200))
    items = items[:limit]

    # Attach request counts
    sub_table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    for order in items:
        try:
            sub_resp = sub_table.query(
                IndexName='orderId',
                KeyConditionExpression=Key('orderId').eq(order['orderId']),
                Select='COUNT',
            )
            order['requestCount'] = sub_resp.get('Count', 0)
        except Exception:
            order['requestCount'] = 0

    return _resp(200, {'orders': items, 'count': len(items)})


def _get_order(order_id: str) -> Dict:
    table = dynamodb.Table(ORDERS_TABLE)
    resp = table.get_item(Key={'orderId': order_id})
    item = resp.get('Item')
    if not item:
        return _resp(404, {'error': 'Order not found'})
    return _resp(200, item)


def _create_order(body: Dict) -> Dict:
    table = dynamodb.Table(ORDERS_TABLE)
    now = _now()

    # Conditional, and retried on collision.
    #
    # This was a bare `put_item`, which on a duplicate `orderId` silently REPLACES the existing
    # order — a staff-visible record of a real order, gone, with a 201 returned. `shortId` is
    # `sha256(uuid4)[:8]`, so 32 bits: the birthday bound puts a first collision around 77,000
    # orders, which is not imminent but is also not the point. The failure mode is silent
    # destruction of somebody's order, and the fix is one argument.
    #
    # Same discipline as `lambda_utils/ecommerce/order_keys.py`: the database enforces
    # uniqueness, not the improbability of the generator.
    for attempt in range(5):
        short = _gen_id()
        order_id = f'WD-ORD-{short}'
        item = {
            'orderId': order_id,
            'shortId': short,
            'source': body.get('source', 'manual'),
            'customerPhone': body.get('customerPhone', ''),
            'customerName': body.get('customerName', ''),
            'customerEmail': body.get('customerEmail', ''),
            'itemsSummary': body.get('itemsSummary', ''),
            'totalAmount': body.get('totalAmount'),
            'currency': body.get('currency', 'INR'),
            'orderStatus': body.get('status', 'active'),
            'paymentStatus': body.get('paymentStatus', 'pending'),
            'adminNotes': body.get('notes', ''),
            'createdAt': now,
            'updatedAt': now,
        }
        item = {k: v for k, v in item.items() if v is not None and v != ''}
        try:
            table.put_item(Item=item, ConditionExpression='attribute_not_exists(orderId)')
            return _resp(201, item)
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
            # Collision. Regenerate rather than overwrite.

    # Fail closed. A caller that gets no order is a visible error someone fixes; a caller that
    # gets a 201 for an order that replaced another one is not.
    return _resp(503, {'error': 'Could not allocate a unique order id', 'retryable': True})


def _update_order(order_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(ORDERS_TABLE)
    updates = {}
    for field in ['orderStatus', 'status', 'paymentStatus', 'adminNotes', 'notes', 'fulfillmentStatus']:
        if field in body:
            key = 'orderStatus' if field == 'status' else ('adminNotes' if field == 'notes' else field)
            updates[key] = body[field]
    updates['updatedAt'] = _now()

    expr_parts = []
    expr_values = {}
    expr_names = {}
    for i, (k, v) in enumerate(updates.items()):
        alias = f'#f{i}'
        val_alias = f':v{i}'
        expr_parts.append(f'{alias} = {val_alias}')
        expr_names[alias] = k
        expr_values[val_alias] = v

    table.update_item(
        Key={'orderId': order_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True, 'orderId': order_id})


def _get_order_submissions(order_id: str) -> Dict:
    table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    resp = table.query(
        IndexName='orderId',
        KeyConditionExpression=Key('orderId').eq(order_id),
    )
    items = sorted(resp.get('Items', []), key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'submissions': items})


def _sync_orders() -> Dict:
    # Trigger Wix order sync via existing wix-store Lambda
    try:
        lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        lambda_client.invoke(
            # The deployed function is `wecare-wix-store`. The previous default,
            # `stack-wecare-digital-wix-store`, named nothing in the account: that
            # prefix belongs to DynamoDB tables, not Lambda functions. Confirmed
            # against the live config on 2026-09-24 - neither this function nor
            # wecare-whatsapp-business-api sets WIX_STORE_FUNCTION, so the default
            # was always what ran, and every invoke raised
            # ResourceNotFoundException.
            FunctionName=os.environ.get('WIX_STORE_FUNCTION', 'wecare-wix-store'),
            InvocationType='Event',
            Payload=json.dumps({'action': 'sync_orders'}),
        )
        return _resp(200, {'message': 'Sync triggered', 'synced': 0})
    except Exception as e:
        return _resp(500, {'error': str(e)})


# ============================================================================
# SERVICE: SUBMIT / AMEND / TRACK / DRAFTS
# ============================================================================

def _submit_request(body: Dict) -> Dict:
    order_id = body.get('orderId', '')
    if not order_id:
        return _resp(400, {'error': 'orderId required'})

    table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    sub_id = str(uuid.uuid4())
    short = _gen_id('WD-SR-')
    now = _now()

    item = {
        'submissionId': sub_id,
        'flowId': 'web-submit',
        'flowCode': '01.WD_SR',
        'flowType': 'form_submit',
        'orderId': order_id,
        'requestType': body.get('requestType', ''),
        'subject': body.get('subject', ''),
        'description': body.get('description', ''),
        'submissionNumber': short,
        'status': 'open',
        'paymentRequired': body.get('paymentRequired', False),
        'paymentStatus': 'none',
        'formData': json.dumps(body),
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)

    # Log status history
    _log_status_history(sub_id, order_id, '', 'open', 'system', 'Request submitted via web')

    return _resp(201, {'submissionId': sub_id, 'submissionNumber': short})


def _amend_request(body: Dict) -> Dict:
    sub_id = body.get('submissionId', '')
    order_id = body.get('orderId', '')
    if not sub_id:
        return _resp(400, {'error': 'submissionId required'})

    table = dynamodb.Table(AMENDMENT_HISTORY_TABLE)
    amend_id = str(uuid.uuid4())
    now = _now()

    item = {
        'amendmentId': amend_id,
        'submissionId': sub_id,
        'orderId': order_id,
        'amendmentType': body.get('amendmentType', ''),
        'description': body.get('description', ''),
        'status': 'submitted',
        'createdAt': now,
        'updatedAt': now,
    }
    table.put_item(Item=item)

    # Log status history
    _log_status_history(sub_id, order_id, '', 'amendment_submitted', 'system', f'Amendment: {body.get("amendmentType", "")}')

    return _resp(201, {'success': True, 'amendmentId': amend_id})


def _track_order(order_id: str) -> Dict:
    # Get order
    order_table = dynamodb.Table(ORDERS_TABLE)
    order_resp = order_table.get_item(Key={'orderId': order_id})
    order = order_resp.get('Item')
    if not order:
        return _resp(404, {'error': 'Order not found'})

    # Get submissions
    sub_table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    sub_resp = sub_table.query(IndexName='orderId', KeyConditionExpression=Key('orderId').eq(order_id))
    submissions = sorted(sub_resp.get('Items', []), key=lambda x: x.get('createdAt', 0), reverse=True)

    # Get status history
    hist_table = dynamodb.Table(STATUS_HISTORY_TABLE)
    hist_resp = hist_table.query(IndexName='orderId', KeyConditionExpression=Key('orderId').eq(order_id))
    history = sorted(hist_resp.get('Items', []), key=lambda x: x.get('changedAt', 0), reverse=True)

    # Get documents
    doc_table = dynamodb.Table(DOCUMENTS_TABLE)
    doc_resp = doc_table.query(IndexName='orderId', KeyConditionExpression=Key('orderId').eq(order_id))
    documents = sorted(doc_resp.get('Items', []), key=lambda x: x.get('createdAt', 0), reverse=True)

    return _resp(200, {
        'order': order,
        'submissions': submissions,
        'statusHistory': history,
        'documents': documents,
    })


def _get_status_history(params: Dict) -> Dict:
    table = dynamodb.Table(STATUS_HISTORY_TABLE)
    order_id = params.get('orderId')
    sub_id = params.get('submissionId')

    if sub_id:
        resp = table.query(IndexName='submissionId', KeyConditionExpression=Key('submissionId').eq(sub_id))
    elif order_id:
        resp = table.query(IndexName='orderId', KeyConditionExpression=Key('orderId').eq(order_id))
    else:
        resp = table.scan(Limit=100)

    items = sorted(resp.get('Items', []), key=lambda x: x.get('changedAt', 0), reverse=True)
    return _resp(200, {'history': items})


def _log_status_history(sub_id: str, order_id: str, old_status: str, new_status: str, changed_by: str, notes: str = ''):
    try:
        table = dynamodb.Table(STATUS_HISTORY_TABLE)
        table.put_item(Item={
            'historyId': str(uuid.uuid4()),
            'submissionId': sub_id,
            'orderId': order_id,
            'oldStatus': old_status,
            'newStatus': new_status,
            'changedBy': changed_by,
            'notes': notes,
            'changedAt': _now(),
        })
    except Exception as e:
        logger.warning(f'Status history log failed: {e}')


def _save_draft(body: Dict) -> Dict:
    table = dynamodb.Table(FLOW_DRAFTS_TABLE)
    phone = body.get('phone', 'web-user')
    flow_code = body.get('flowCode', '')
    draft_key = f'{phone}#{flow_code}'
    now = _now()
    ttl = now + (7 * 86400)  # 7 days

    table.put_item(Item={
        'draftKey': draft_key,
        'phone': phone,
        'flowCode': flow_code,
        'screen': body.get('screen', ''),
        'formData': body.get('formData', '{}'),
        'updatedAt': now,
        'ttl': ttl,
    })
    return _resp(200, {'saved': True, 'draftKey': draft_key})


def _get_draft(flow_code: str, phone: str = 'web-user') -> Dict:
    table = dynamodb.Table(FLOW_DRAFTS_TABLE)
    draft_key = f'{phone}#{flow_code}'
    resp = table.get_item(Key={'draftKey': draft_key})
    item = resp.get('Item')
    if not item:
        return _resp(404, {'error': 'No draft found'})
    return _resp(200, item)


def _delete_draft(flow_code: str, phone: str = 'web-user') -> Dict:
    table = dynamodb.Table(FLOW_DRAFTS_TABLE)
    draft_key = f'{phone}#{flow_code}'
    table.delete_item(Key={'draftKey': draft_key})
    return _resp(200, {'deleted': True})


# ============================================================================
# DOCUMENTS
# ============================================================================

def _list_documents(params: Dict) -> Dict:
    table = dynamodb.Table(DOCUMENTS_TABLE)
    status = params.get('status')
    source = params.get('source')
    doc_type = params.get('type')

    if status:
        resp = table.query(IndexName='verificationStatus', KeyConditionExpression=Key('verificationStatus').eq(status))
    elif source:
        resp = table.query(IndexName='sourceType', KeyConditionExpression=Key('sourceType').eq(source))
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    if doc_type:
        items = [i for i in items if i.get('documentType') == doc_type]

    # Normalize field names for frontend
    for item in items:
        item['source'] = item.pop('sourceType', item.get('source', ''))
        item['type'] = item.pop('documentType', item.get('type', ''))
        item['status'] = item.pop('verificationStatus', item.get('status', ''))
        item['notes'] = item.get('remarks', item.get('notes', ''))
        item['fileSize'] = item.get('fileSize', 0)

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'documents': items, 'count': len(items)})


def _get_document(doc_id: str) -> Dict:
    table = dynamodb.Table(DOCUMENTS_TABLE)
    resp = table.get_item(Key={'documentId': doc_id})
    item = resp.get('Item')
    if not item:
        return _resp(404, {'error': 'Document not found'})
    return _resp(200, item)


def _update_document(doc_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(DOCUMENTS_TABLE)
    now = _now()
    updates = {'updatedAt': now}

    if 'status' in body:
        updates['verificationStatus'] = body['status']
    if 'notes' in body or 'remarks' in body:
        updates['remarks'] = body.get('notes', body.get('remarks', ''))
    if 'reviewedBy' in body:
        updates['reviewedBy'] = body['reviewedBy']
        updates['reviewedAt'] = now

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'documentId': doc_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    # Log document history
    try:
        hist_table = dynamodb.Table(DOCUMENT_HISTORY_TABLE)
        hist_table.put_item(Item={
            'historyId': str(uuid.uuid4()),
            'documentId': doc_id,
            'action': body.get('status', 'updated'),
            'actorType': 'admin',
            'actorId': body.get('reviewedBy', 'admin'),
            'remarks': body.get('notes', body.get('remarks', '')),
            'createdAt': now,
        })
    except Exception:
        pass

    return _resp(200, {'updated': True})


def _get_document_download_url(doc_id: str) -> Dict:
    table = dynamodb.Table(DOCUMENTS_TABLE)
    resp = table.get_item(Key={'documentId': doc_id})
    item = resp.get('Item')
    if not item:
        return _resp(404, {'error': 'Document not found'})

    storage_key = item.get('storageKey') or item.get('fileUrl', '')
    if not storage_key:
        return _resp(404, {'error': 'No file available'})

    if storage_key.startswith('http'):
        return _resp(200, {'url': storage_key})

    # Rows written before the bucket merge store `stack/whatsapp-media/incoming/<file>`
    # while the object sits at `o/stack/whatsapp-media/incoming/<file>`. Normalise on
    # read so legacy and current rows both resolve; canonical() is idempotent and never
    # moves a key between the public and gated roots.
    storage_key = media_paths.canonical(storage_key)

    try:
        url = s3_client.generate_presigned_url('get_object',
            Params={'Bucket': DOCS_S3_BUCKET, 'Key': storage_key},
            ExpiresIn=3600)
        return _resp(200, {'url': url})
    except Exception as e:
        return _resp(500, {'error': str(e)})


def _create_document(body: Dict) -> Dict:
    """Create a document record for admin manual upload."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    doc_id = f'WD-DOC-{_gen_id()}'
    now = _now()
    item = {
        'documentId': doc_id,
        'customerPhone': body.get('customerPhone', ''),
        'customerName': body.get('customerName', ''),
        'orderId': body.get('orderId'),
        'sourceType': 'manual',
        'documentType': body.get('type', body.get('documentType', 'other')),
        'fileName': body.get('fileName', ''),
        'verificationStatus': body.get('status', 'uploaded'),
        'remarks': body.get('notes', body.get('remarks', '')),
        'uploadedAt': now,
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None and v != ''}
    item.setdefault('verificationStatus', 'uploaded')
    item.setdefault('sourceType', 'manual')
    table.put_item(Item=item)

    # Normalize for response
    item['source'] = item.get('sourceType', 'manual')
    item['type'] = item.get('documentType', 'other')
    item['status'] = item.get('verificationStatus', 'uploaded')
    return _resp(201, item)


# ============================================================================
# FAQ
# ============================================================================

def _list_faqs(params: Dict) -> Dict:
    table = dynamodb.Table(FAQ_TABLE)
    category = params.get('category')
    active = params.get('active')

    if category:
        resp = table.query(IndexName='category', KeyConditionExpression=Key('category').eq(category))
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    if active is not None:
        is_active = active.lower() == 'true'
        items = [i for i in items if i.get('isActive', True) == is_active]

    # Normalize for frontend
    for item in items:
        item['active'] = item.pop('isActive', True)

    items.sort(key=lambda x: x.get('sortOrder', 0))
    return _resp(200, {'faqs': items, 'count': len(items)})


def _create_faq(body: Dict) -> Dict:
    table = dynamodb.Table(FAQ_TABLE)
    faq_id = str(uuid.uuid4())
    now = _now()
    item = {
        'faqId': faq_id,
        'category': body.get('category', 'General'),
        'question': body.get('question', ''),
        'answer': body.get('answer', ''),
        'sortOrder': int(body.get('sortOrder', 0)),
        'isActive': body.get('active', True),
        'createdAt': now,
        'updatedAt': now,
    }
    table.put_item(Item=item)
    item['active'] = item.pop('isActive')
    return _resp(201, item)


def _update_faq(faq_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(FAQ_TABLE)
    now = _now()
    updates = {'updatedAt': now}
    for field in ['question', 'answer', 'category', 'sortOrder']:
        if field in body:
            updates[field] = body[field]
    if 'active' in body:
        updates['isActive'] = body['active']

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'faqId': faq_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True})


def _delete_faq(faq_id: str) -> Dict:
    table = dynamodb.Table(FAQ_TABLE)
    table.delete_item(Key={'faqId': faq_id})
    return _resp(200, {'deleted': True})


# ============================================================================
# APPOINTMENTS
# ============================================================================

def _list_appointments(params: Dict) -> Dict:
    table = dynamodb.Table(APPOINTMENTS_TABLE)
    status = params.get('status')
    apt_type = params.get('type')

    if status:
        resp = table.query(IndexName='status', KeyConditionExpression=Key('status').eq(status))
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    if apt_type:
        items = [i for i in items if i.get('appointmentType') == apt_type]

    # Normalize for frontend
    for item in items:
        item['type'] = item.pop('appointmentType', item.get('type', ''))
        # Build scheduledAt from slotDate + slotTime
        if 'slotDate' in item and not item.get('scheduledAt'):
            try:
                from datetime import datetime
                dt_str = f"{item['slotDate']} {item.get('slotTime', '00:00')}"
                for fmt in ['%Y-%m-%d %I:%M %p', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S']:
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        item['scheduledAt'] = int(dt.timestamp())
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        item['provider'] = item.get('assignedTo', item.get('provider', ''))
        item['location'] = item.get('location', '')

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'appointments': items, 'count': len(items)})


def _create_appointment(body: Dict) -> Dict:
    table = dynamodb.Table(APPOINTMENTS_TABLE)
    apt_id = f'WD-APT-{_gen_id()}'
    now = _now()
    item = {
        'appointmentId': apt_id,
        'customerPhone': body.get('customerPhone', ''),
        'customerName': body.get('customerName', ''),
        'orderId': body.get('orderId'),
        'appointmentType': body.get('type', body.get('appointmentType', 'consultation')),
        'slotDate': body.get('slotDate', body.get('date', '')),
        'slotTime': body.get('slotTime', body.get('time', '')),
        'duration': body.get('duration', ''),
        'location': body.get('location', ''),
        'status': body.get('status', 'scheduled'),
        'notes': body.get('notes', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None and v != ''}
    table.put_item(Item=item)
    # Normalize for response
    item['type'] = item.pop('appointmentType', '')
    return _resp(201, item)


def _update_appointment(apt_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(APPOINTMENTS_TABLE)
    now = _now()
    updates = {'updatedAt': now}
    for field in ['status', 'notes', 'adminNotes', 'assignedTo', 'location', 'slotDate', 'slotTime']:
        if field in body:
            updates[field] = body[field]

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'appointmentId': apt_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True})


# ============================================================================
# RX SLOTS
# ============================================================================

def _list_rx_slots(params: Dict) -> Dict:
    table = dynamodb.Table(RX_SLOTS_TABLE)
    status = params.get('status')
    date = params.get('date')

    if status:
        resp = table.query(IndexName='status', KeyConditionExpression=Key('status').eq(status))
    elif date:
        resp = table.query(IndexName='slotDate', KeyConditionExpression=Key('slotDate').eq(date))
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    # Normalize for frontend
    for item in items:
        item['slotId'] = item.get('rxSlotId', item.get('slotId', ''))
        item['date'] = item.get('slotDate', '')
        item['time'] = item.get('slotTime', '')
        item['provider'] = item.get('doctorName', item.get('facilityName', ''))
        item['patientName'] = item.get('customerName', '')
        item['patientPhone'] = item.get('customerPhone', '')

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'slots': items, 'count': len(items)})


def _create_rx_slot(body: Dict) -> Dict:
    table = dynamodb.Table(RX_SLOTS_TABLE)
    slot_id = f'WD-RX-{_gen_id()}'
    now = _now()
    item = {
        'rxSlotId': slot_id,
        'customerPhone': body.get('patientPhone', body.get('customerPhone', '')),
        'customerName': body.get('patientName', body.get('customerName', '')),
        'orderId': body.get('orderId'),
        'slotType': body.get('slotType', 'prescription'),
        'slotDate': body.get('date', body.get('slotDate', '')),
        'slotTime': body.get('time', body.get('slotTime', '')),
        'facilityName': body.get('provider', body.get('facilityName', '')),
        'status': body.get('status', 'available'),
        'prescriptionNotes': body.get('notes', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None and v != ''}
    table.put_item(Item=item)
    # Normalize for response
    item['slotId'] = slot_id
    item['date'] = item.get('slotDate', '')
    item['time'] = item.get('slotTime', '')
    return _resp(201, item)


def _update_rx_slot(slot_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(RX_SLOTS_TABLE)
    now = _now()
    updates = {'updatedAt': now}
    for field in ['status', 'prescriptionNotes', 'adminNotes', 'customerName', 'customerPhone']:
        if field in body:
            updates[field] = body[field]

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'rxSlotId': slot_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True})


# ============================================================================
# ENTERPRISE ASSIST
# ============================================================================

def _list_enterprise_cases(params: Dict) -> Dict:
    table = dynamodb.Table(ENTERPRISE_TABLE)
    status = params.get('status')
    priority = params.get('priority')

    if status:
        resp = table.query(IndexName='status', KeyConditionExpression=Key('status').eq(status))
    else:
        resp = table.scan()

    items = resp.get('Items', [])
    if priority:
        items = [i for i in items if i.get('priority') == priority]

    # Normalize for frontend
    for item in items:
        item['customerName'] = item.get('contactName', item.get('customerName', ''))
        item['customerPhone'] = item.get('contactPhone', item.get('customerPhone', ''))
        item['category'] = item.get('category', '')

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'cases': items, 'count': len(items)})


def _create_enterprise_case(body: Dict) -> Dict:
    table = dynamodb.Table(ENTERPRISE_TABLE)
    case_id = f'WD-ENT-{_gen_id()}'
    now = _now()
    item = {
        'caseId': case_id,
        'contactPhone': body.get('customerPhone', body.get('contactPhone', '')),
        'contactName': body.get('customerName', body.get('contactName', '')),
        'contactEmail': body.get('contactEmail', ''),
        'accountName': body.get('accountName', ''),
        'subject': body.get('subject', ''),
        'description': body.get('description', ''),
        'priority': body.get('priority', 'normal'),
        'status': body.get('status', 'open'),
        'assignedTo': body.get('assignedTo', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None and v != ''}
    table.put_item(Item=item)
    item['customerName'] = item.get('contactName', '')
    item['customerPhone'] = item.get('contactPhone', '')
    return _resp(201, item)


def _update_enterprise_case(case_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(ENTERPRISE_TABLE)
    now = _now()
    updates = {'updatedAt': now}
    for field in ['status', 'priority', 'assignedTo', 'notes', 'resolution']:
        if field in body:
            updates[field] = body[field]

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'caseId': case_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True})


# ============================================================================
# REVIEWS
# ============================================================================

def _list_reviews(params: Dict) -> Dict:
    table = dynamodb.Table(REVIEWS_TABLE)
    status = params.get('status')
    if status == 'pending':
        status = 'submitted'
    phone = params.get('customerPhone', '').replace('+', '').replace(' ', '')
    contact_id = params.get('contactId')
    if phone:
        operation = table.query
        kwargs = {'IndexName': 'customerPhone', 'KeyConditionExpression': Key('customerPhone').eq(phone)}
    elif status:
        operation = table.query
        kwargs = {'IndexName': 'status', 'KeyConditionExpression': Key('status').eq(status)}
    else:
        operation = table.scan
        kwargs = {}
    items = []
    while True:
        page = operation(**kwargs)
        items.extend(page.get('Items', []))
        if not page.get('LastEvaluatedKey'):
            break
        kwargs['ExclusiveStartKey'] = page['LastEvaluatedKey']
    if contact_id:
        items = [i for i in items if i.get('contactId') == contact_id]
    if status:
        items = [i for i in items if i.get('status') == status]
    source = params.get('source')
    min_rating = params.get('minRating')
    if source:
        items = [i for i in items if i.get('source', i.get('category', '')) == source]
    if min_rating:
        items = [i for i in items if (i.get('rating', 0) or 0) >= int(min_rating)]

    # Normalize for frontend
    for item in items:
        item['comment'] = item.get('reviewText', item.get('comment', ''))
        item['source'] = item.get('source', item.get('category', 'web'))
        item['status'] = item.get('status', 'submitted')
        # Map submitted -> pending for frontend
        if item['status'] == 'submitted':
            item['status'] = 'pending'

    items.sort(key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'reviews': items, 'count': len(items)})


def _create_review(body: Dict) -> Dict:
    table = dynamodb.Table(REVIEWS_TABLE)
    review_id = f'WD-REV-{_gen_id()}'
    now = _now()
    item = {
        'reviewId': review_id,
        'customerPhone': body.get('customerPhone', ''),
        'customerName': body.get('customerName', ''),
        'orderId': body.get('orderId'),
        'rating': int(body.get('rating', 5)),
        'reviewText': body.get('comment', body.get('reviewText', '')),
        'category': body.get('source', body.get('category', 'web')),
        'status': 'submitted',
        'createdAt': now,
        'updatedAt': now,
    }
    item = {k: v for k, v in item.items() if v is not None and v != ''}
    table.put_item(Item=item)
    return _resp(201, item)


def _update_review(review_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(REVIEWS_TABLE)
    now = _now()
    updates = {'updatedAt': now}
    for field in ['status', 'response', 'respondedAt']:
        if field in body:
            updates[field] = body[field]
    if 'response' in body and 'respondedAt' not in body:
        updates['respondedAt'] = now

    # Map frontend status back to DB
    if updates.get('status') == 'pending':
        updates['status'] = 'submitted'

    expr_parts, expr_values, expr_names = [], {}, {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f'#f{i} = :v{i}')
        expr_names[f'#f{i}'] = k
        expr_values[f':v{i}'] = v

    table.update_item(
        Key={'reviewId': review_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return _resp(200, {'updated': True})


# ============================================================================
# MAIN HANDLER — ROUTER
# ============================================================================

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    global origin
    origin = _extract_origin(event)
    request_id = context.aws_request_id if context else 'local'

    rc = event.get('requestContext', {})
    http = rc.get('http', {})
    method = http.get('method', event.get('httpMethod', 'GET'))
    path = http.get('path', '') or event.get('rawPath', '') or event.get('path', '')
    params = event.get('queryStringParameters') or {}

    if method == 'OPTIONS':
        return _resp(200, {})

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    logger.info(f'[{request_id}] {method} {path}')

    try:
        # ── ORDERS ──
        if '/orders/sync' in path and method == 'POST':
            return _sync_orders()
        elif '/orders/' in path and '/submissions' in path:
            order_id = _extract_path_param(path, 'orders')
            return _get_order_submissions(order_id)
        elif '/orders/' in path:
            order_id = _extract_path_param(path, 'orders')
            if method == 'GET':
                return _get_order(order_id)
            elif method in ('PATCH', 'PUT'):
                return _update_order(order_id, body)
        elif '/orders' in path:
            if method == 'GET':
                return _list_orders(params)
            elif method == 'POST':
                return _create_order(body)

        # ── SERVICE ──
        elif '/service/submit' in path and method == 'POST':
            return _submit_request(body)
        elif '/service/amend' in path and method == 'POST':
            return _amend_request(body)
        elif '/service/track/' in path:
            order_id = path.split('/service/track/')[-1].split('?')[0]
            return _track_order(order_id)
        elif '/service/history' in path:
            return _get_status_history(params)
        elif '/service/drafts' in path:
            if method == 'POST':
                return _save_draft(body)
            elif method == 'GET':
                flow_code = params.get('flowCode', path.split('/service/drafts/')[-1].split('?')[0])
                return _get_draft(flow_code)
            elif method == 'DELETE':
                flow_code = path.split('/service/drafts/')[-1].split('?')[0]
                return _delete_draft(flow_code)

        # ── DOCUMENTS ──
        elif '/documents/' in path and '/download' in path:
            doc_id = _extract_path_param(path, 'documents')
            return _get_document_download_url(doc_id)
        elif '/documents/' in path:
            doc_id = _extract_path_param(path, 'documents')
            if method == 'GET':
                return _get_document(doc_id)
            elif method in ('PUT', 'PATCH'):
                return _update_document(doc_id, body)
        elif '/documents' in path:
            if method == 'GET':
                return _list_documents(params)
            elif method == 'POST':
                return _create_document(body)

        # ── FAQ ──
        elif '/faq/' in path:
            faq_id = _extract_path_param(path, 'faq')
            if method in ('PUT', 'PATCH'):
                return _update_faq(faq_id, body)
            elif method == 'DELETE':
                return _delete_faq(faq_id)
        elif '/faq' in path:
            if method == 'GET':
                return _list_faqs(params)
            elif method == 'POST':
                return _create_faq(body)

        # ── APPOINTMENTS ──
        elif '/appointments/' in path:
            apt_id = _extract_path_param(path, 'appointments')
            if method in ('PUT', 'PATCH'):
                return _update_appointment(apt_id, body)
        elif '/appointments' in path:
            if method == 'GET':
                return _list_appointments(params)
            elif method == 'POST':
                return _create_appointment(body)

        # ── RX SLOTS ──
        elif '/rx-slots/' in path:
            slot_id = _extract_path_param(path, 'rx-slots')
            if method in ('PUT', 'PATCH'):
                return _update_rx_slot(slot_id, body)
        elif '/rx-slots' in path:
            if method == 'GET':
                return _list_rx_slots(params)
            elif method == 'POST':
                return _create_rx_slot(body)

        # ── ENTERPRISE ASSIST ──
        elif '/enterprise-assist/' in path:
            case_id = _extract_path_param(path, 'enterprise-assist')
            if method in ('PUT', 'PATCH'):
                return _update_enterprise_case(case_id, body)
        elif '/enterprise-assist' in path:
            if method == 'GET':
                return _list_enterprise_cases(params)
            elif method == 'POST':
                return _create_enterprise_case(body)

        # ── REVIEWS ──
        elif '/reviews/' in path:
            review_id = _extract_path_param(path, 'reviews')
            if method in ('PUT', 'PATCH'):
                return _update_review(review_id, body)
        elif '/reviews' in path:
            if method == 'GET':
                return _list_reviews(params)
            elif method == 'POST':
                return _create_review(body)

        return _resp(404, {'error': f'Unknown path: {path}'})

    except Exception as e:
        logger.exception(f'[{request_id}] Error: {e}')
        return _resp(500, {'error': str(e)})


def _extract_path_param(path: str, resource: str) -> str:
    """Extract ID from path like /orders/{id} or /orders/{id}/submissions."""
    parts = path.split(f'/{resource}/')
    if len(parts) < 2:
        return ''
    remainder = parts[1]
    return remainder.split('/')[0].split('?')[0]
