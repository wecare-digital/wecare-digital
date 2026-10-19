"""
Service Module API — Unified REST handler for all service modules.

Routes:
  /orders                  GET (list), POST (create)
  /orders/{id}             GET, PATCH
  /orders/{id}/submissions GET
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

from lambda_utils import contact_store, flow_completion, flow_records, media_paths, shared_tables
from lambda_utils.ecommerce import order_patch, order_record

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Table names. The shared stores (contacts, orders, flow responses, drafts, status history)
# resolve through `lambda_utils.shared_tables`, so this API, the WhatsApp Flows, the inbox and
# the website checkout read and write the same tables. Reviews, appointments, Rx slots,
# enterprise cases and amendments are flow responses: see `lambda_utils.flow_records`.
TABLE_PREFIX = os.environ.get('TABLE_PREFIX', 'stack-wecare-digital')
ORDERS_TABLE = order_record.table_name()
CONTACTS_TABLE = shared_tables.contacts_table_name()
FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()
FLOW_DRAFTS_TABLE = shared_tables.flow_drafts_table_name()
STATUS_HISTORY_TABLE = shared_tables.status_history_table_name()
DOCUMENTS_TABLE = f'{TABLE_PREFIX}-DocumentTable'
DOCUMENT_HISTORY_TABLE = f'{TABLE_PREFIX}-DocumentHistoryTable'
FAQ_TABLE = f'{TABLE_PREFIX}-FaqTable'
AUDIT_LOG_TABLE = f'{TABLE_PREFIX}-AuditLogsTable'

# See core/service-api/handler.py for the full note. Documents ARE WhatsApp media and
# live in the one media bucket; `wecare-digital-documents` and the deployed
# `wecare-digital-media` both name buckets that do not exist in this account.
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

def _drain_orders(table, kwargs: Dict[str, Any]) -> list:
    """Every page of one order query (or a scan when `kwargs` is empty)."""
    resp = table.query(**kwargs) if kwargs else table.scan()
    items = resp.get('Items', [])
    while resp.get('LastEvaluatedKey'):
        query = dict(kwargs, ExclusiveStartKey=resp['LastEvaluatedKey'])
        resp = table.query(**query) if kwargs else table.scan(**query)
        items.extend(resp.get('Items', []))
    return items


def _list_orders(params: Dict) -> Dict:
    """Website and WhatsApp orders from the one order table, in one shape.

    A phone filter matches every stored spelling of the number (`+91...`, `91...`), because
    website orders carry the session's E.164 phone and older rows carry what staff typed.
    """
    table = dynamodb.Table(ORDERS_TABLE)
    status = params.get('status')
    source = params.get('source')
    phone = params.get('phone')
    search = params.get('search')

    if phone:
        items, seen = [], set()
        for variant in contact_store.phone_variants(phone) or [phone]:
            for item in _drain_orders(table, {
                    'IndexName': 'customerPhone',
                    'KeyConditionExpression': Key('customerPhone').eq(variant)}):
                if item.get('orderId') not in seen:
                    seen.add(item.get('orderId'))
                    items.append(item)
    elif status:
        items = _drain_orders(table, {'IndexName': 'orderStatus',
                                      'KeyConditionExpression': Key('orderStatus').eq(status)})
    elif source:
        items = _drain_orders(table, {'IndexName': 'source',
                                      'KeyConditionExpression': Key('source').eq(source)})
    else:
        items = _drain_orders(table, {})

    # One projection for every writer's rows: order number, channel, integer paise and the
    # staff payment word (`PAYMENT_PAID` reads as `paid`).
    items = [order_record.view(item) for item in items]
    if search:
        q = search.lower()
        items = [i for i in items if q in (str(i.get('orderId', '')) + str(i.get('orderNumber', '')) + str(i.get('shortId', '')) + str(i.get('customerName', '')) + str(i.get('customerPhone', ''))).lower()]

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
    return _resp(200, order_record.view(item))


def _contact_id_for_phone(phone: str) -> str:
    """The shared ContactsTable id for a phone, best-effort ('' when unknown or unreadable)."""
    if not phone:
        return ''
    try:
        return contact_store.lookup_id(dynamodb.Table(CONTACTS_TABLE), phone)
    except Exception as exc:  # noqa: BLE001 - attribution must not block the write
        logger.warning(f'Contact lookup skipped: {type(exc).__name__}')
        return ''


def _create_order(body: Dict) -> Dict:
    """A staff-entered order, in the same shape the website and WhatsApp orders use.

    Linked to the customer's ContactsTable row when one exists for the phone, so the order
    shows up wherever that contact's orders are listed, whichever channel created it.
    """
    table = dynamodb.Table(ORDERS_TABLE)
    now = _now()
    phone = contact_store.canonical_phone(body.get('customerPhone'))
    contact_id = str(body.get('contactId') or '').strip() or _contact_id_for_phone(phone)

    # Conditional, and retried on collision. See the identical fix in
    # core/service-api/handler.py — these two files are near-copies of each other, which is
    # precisely why the bare `put_item` had to be fixed in both: a duplicate `orderId` silently
    # REPLACED an existing order and still returned 201. `shortId` is `sha256(uuid4)[:8]`, so
    # 32 bits, and the database should enforce uniqueness rather than the generator's luck.
    for attempt in range(5):
        item = order_record.staff_order(body, short=_gen_id(), now=now,
                                        contact_id=contact_id, customer_phone=phone)
        try:
            table.put_item(Item=item, ConditionExpression='attribute_not_exists(orderId)')
            return _resp(201, order_record.view(item))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise

    return _resp(503, {'error': 'Could not allocate a unique order id', 'retryable': True})


def _update_order(order_id: str, body: Dict) -> Dict:
    table = dynamodb.Table(ORDERS_TABLE)
    current = table.get_item(Key={'orderId': order_id}, ConsistentRead=True).get('Item')
    if not current:
        return _resp(404, {'error': 'Order not found'})

    updates, error = order_patch.validate_order_patch(current, body)
    if error:
        conflict_codes = {
            'ORDER_STATUS_REVIEW_REQUIRED',
            'ORDER_STATUS_TRANSITION_INVALID',
            'ORDER_PAYMENT_NOT_CAPTURED',
            'PAID_ORDER_CANCEL_REQUIRES_WORKFLOW',
        }
        return _resp(409 if error.get('errorCode') in conflict_codes else 400, error)

    assert updates is not None
    status_mutation = 'orderStatus' in updates
    updates['updatedAt'] = _now()

    expr_parts = []
    expr_values = {}
    expr_names = {}
    for i, (key, value) in enumerate(updates.items()):
        alias = f'#f{i}'
        val_alias = f':v{i}'
        expr_parts.append(f'{alias} = {val_alias}')
        expr_names[alias] = key
        expr_values[val_alias] = value

    # A status decision is based on the row read above. Guard both the stored fulfilment word
    # and payment word so a concurrent webhook/capture/refund cannot race this PATCH and leave
    # a transition that was legal only against stale state.
    condition_parts = ['attribute_exists(orderId)']
    if status_mutation:
        for guard_name, field in (
            ('order_status', 'orderStatus'),
            ('fulfilment_status', 'fulfillmentStatus'),
            ('status_alias', 'status'),
            ('payment', 'paymentStatus'),
        ):
            alias = f'#guard_{guard_name}'
            expr_names[alias] = field
            if field in current:
                value_alias = f':guard_{guard_name}'
                expr_values[value_alias] = current.get(field)
                condition_parts.append(f'{alias} = {value_alias}')
            else:
                condition_parts.append(f'attribute_not_exists({alias})')

    try:
        table.update_item(
            Key={'orderId': order_id},
            UpdateExpression='SET ' + ', '.join(expr_parts),
            ConditionExpression=' AND '.join(condition_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return _resp(409, {
                'error': 'Order changed while it was being updated; reload and retry',
                'errorCode': 'ORDER_PATCH_STALE',
            })
        raise
    return _resp(200, {'updated': True, 'orderId': order_id})

def _get_order_submissions(order_id: str) -> Dict:
    table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    resp = table.query(
        IndexName='orderId',
        KeyConditionExpression=Key('orderId').eq(order_id),
    )
    items = sorted(resp.get('Items', []), key=lambda x: x.get('createdAt', 0), reverse=True)
    return _resp(200, {'submissions': items})


# ============================================================================
# SERVICE: SUBMIT / AMEND / TRACK / DRAFTS
# ============================================================================

def _customer_of(table_name: str, key: Dict[str, str], phone_field: str) -> Dict[str, str]:
    """`{phone, contactId}` copied off a linked order or submission. Best-effort."""
    try:
        row = dynamodb.Table(table_name).get_item(Key=key).get('Item') or {}
    except Exception as exc:  # noqa: BLE001 - attribution must not block the write
        logger.warning(f'Linked customer lookup skipped: {type(exc).__name__}')
        return {'phone': '', 'contactId': ''}
    return {'phone': str(row.get(phone_field) or ''), 'contactId': str(row.get('contactId') or '')}


def _submit_request(body: Dict) -> Dict:
    """A staff-entered service request, written by the one flow-response writer.

    Same table, shape and idempotent claim as the WhatsApp Submit Request flow, marked
    `channel=staff`, and linked to the order's customer so it appears on that contact's
    timeline next to their WhatsApp submissions.
    """
    order_id = body.get('orderId', '')
    if not order_id:
        return _resp(400, {'error': 'orderId required'})

    customer = _customer_of(ORDERS_TABLE, {'orderId': order_id}, 'customerPhone')
    contact_id = customer['contactId'] or _contact_id_for_phone(customer['phone'])
    for _ in range(5):
        short = _gen_id('WD-SR-')
        result = flow_completion.claim_completion(
            flow_token=short, screen='STAFF', flow_code='01.WD_SR', flow_type='form_submit',
            phone=contact_store.digits(customer['phone']), contact_id=contact_id,
            form_data=body if isinstance(body, dict) else {},
            reference_prefix='WD-SR', submission_id=short, status='open',
            extra={'flowId': flow_completion.WEB_SUBMIT_FLOW_ID, 'orderId': order_id,
                   'requestType': body.get('requestType', ''),
                   'subject': body.get('subject', ''),
                   'description': body.get('description', ''),
                   'paymentRequired': bool(body.get('paymentRequired', False))},
            ttl_seconds=0, channel=flow_completion.CHANNEL_STAFF)
        if result.created:
            _log_status_history(short, order_id, '', 'open', 'system', 'Request submitted via web')
            return _resp(201, {'submissionId': short, 'submissionNumber': short})
        if result.status == 'error':
            return _resp(503, {'error': 'Request could not be saved', 'retryable': True})
    return _resp(503, {'error': 'Could not allocate a unique request number', 'retryable': True})


def _amend_request(body: Dict) -> Dict:
    """An amendment is a flow response too: one FlowSubmission row (flowCode WD_AMEND).

    It points at the request it amends through `parentSubmissionId` and inherits that
    request's customer, so the amendment, the request and the order share one contact.
    """
    sub_id = body.get('submissionId', '')
    order_id = body.get('orderId', '')
    if not sub_id:
        return _resp(400, {'error': 'submissionId required'})

    parent = _customer_of(FLOW_SUBMISSIONS_TABLE, {'submissionId': sub_id}, 'phone')
    try:
        record = flow_records.create_staff_row(
            flow_records.AMENDMENT, fields=flow_records.amendment_fields(body),
            phone=parent['phone'], contact_id=parent['contactId'],
            form_data=body if isinstance(body, dict) else {})
    except RuntimeError:
        return _resp(503, {'error': 'Amendment could not be saved', 'retryable': True})

    # Log status history
    _log_status_history(sub_id, order_id, '', 'amendment_submitted', 'system', f'Amendment: {body.get("amendmentType", "")}')

    return _resp(201, {'success': True, 'amendmentId': record['amendmentId']})


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
        'order': order_record.view(order),
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

    # Legacy rows store the key without the `o/` root the object actually sits under.
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
# APPOINTMENTS, RX SLOTS, ENTERPRISE ASSIST, REVIEWS
# ============================================================================
#
# All four are flow responses and live in the one flow-response table, next to the WhatsApp
# Flow submissions that create most of them, marked `channel=staff` when entered here. Routes,
# request bodies and response shapes are unchanged. `lambda_utils.flow_records` owns the row
# shape and the list filters, so this file and core/service-api/handler.py cannot drift on it.

def _flow_table():
    return dynamodb.Table(FLOW_SUBMISSIONS_TABLE)


def _create_record(kind, body: Dict, fields: Dict, phone: str, view,
                   status: Optional[str] = None) -> Dict:
    contact_id = (str(body.get('contactId') or '').strip()
                  or _contact_id_for_phone(contact_store.canonical_phone(phone)))
    try:
        record = flow_records.create_staff_row(
            kind, fields=fields, phone=phone, contact_id=contact_id,
            sender_name=str(fields.get('customerName') or fields.get('contactName') or ''),
            status=status)
    except RuntimeError:
        return _resp(503, {'error': f'{kind.name} could not be saved', 'retryable': True})
    return _resp(201, view(record))


def _update_record(kind, record_id: str, updates: Dict) -> Dict:
    if not flow_records.update_row(_flow_table(), kind, record_id, updates, _now()):
        return _resp(404, {'error': 'Not found'})
    return _resp(200, {'updated': True})


def _list_appointments(params: Dict) -> Dict:
    items = flow_records.list_appointments(_flow_table(), params)
    return _resp(200, {'appointments': items, 'count': len(items)})


def _create_appointment(body: Dict) -> Dict:
    return _create_record(flow_records.APPOINTMENT, body, flow_records.appointment_fields(body),
                          body.get('customerPhone', ''), flow_records.appointment_view,
                          status=body.get('status') or 'scheduled')


def _update_appointment(apt_id: str, body: Dict) -> Dict:
    updates = {f: body[f] for f in flow_records.APPOINTMENT_UPDATE_FIELDS if f in body}
    return _update_record(flow_records.APPOINTMENT, apt_id, updates)


def _list_rx_slots(params: Dict) -> Dict:
    items = flow_records.list_rx_slots(_flow_table(), params)
    return _resp(200, {'slots': items, 'count': len(items)})


def _create_rx_slot(body: Dict) -> Dict:
    fields = flow_records.rx_slot_fields(body)
    return _create_record(flow_records.RX_SLOT, body, fields, fields['customerPhone'],
                          flow_records.rx_slot_view, status=body.get('status') or 'available')


def _update_rx_slot(slot_id: str, body: Dict) -> Dict:
    updates = {f: body[f] for f in flow_records.RX_SLOT_UPDATE_FIELDS if f in body}
    return _update_record(flow_records.RX_SLOT, slot_id, updates)


def _list_enterprise_cases(params: Dict) -> Dict:
    items = flow_records.list_enterprise_cases(_flow_table(), params)
    return _resp(200, {'cases': items, 'count': len(items)})


def _create_enterprise_case(body: Dict) -> Dict:
    fields = flow_records.enterprise_fields(body)
    return _create_record(flow_records.ENTERPRISE_CASE, body, fields, fields['contactPhone'],
                          flow_records.enterprise_view, status=body.get('status') or 'open')


def _update_enterprise_case(case_id: str, body: Dict) -> Dict:
    updates = {f: body[f] for f in flow_records.ENTERPRISE_UPDATE_FIELDS if f in body}
    return _update_record(flow_records.ENTERPRISE_CASE, case_id, updates)


def _list_reviews(params: Dict) -> Dict:
    """Ratings (WD_REV) and private ideas (WD_IDEA), every channel, every page."""
    items = flow_records.list_reviews(_flow_table(), params)
    return _resp(200, {'reviews': items, 'count': len(items)})


def _create_review(body: Dict) -> Dict:
    return _create_record(flow_records.REVIEW, body, flow_records.review_fields(body),
                          body.get('customerPhone', ''), flow_records.review_view)


def _update_review(review_id: str, body: Dict) -> Dict:
    return _update_record(flow_records.REVIEW, review_id,
                          flow_records.review_updates(body, _now()))


# ============================================================================
# NO ROUTER HERE, DELIBERATELY
# ============================================================================
#
# This module used to end with its own `handler(event, context)` that duplicated the routing
# in handler.py. It was dead code: this Lambda's configured entry point is `handler.handler`,
# which imports 35 named functions from this module and never its router, and nothing in the
# tree referenced `service_api.handler`.
#
# It was removed rather than fixed, because it was a trap. The near-identical router in
# `core/service-api/handler.py` calls `require_auth` and this one did not, so the two copies
# disagreed on authentication - and a dead function that looks exactly like a live entry point
# is what somebody wires up later, inheriting the gap. The live path is authenticated:
# handler.py calls `require_auth(event)` before dispatching to any of the functions above.
#
# The helper below stays: handler.py imports it as `_svc_path_param`.

def _extract_path_param(path: str, resource: str) -> str:
    """Extract ID from path like /orders/{id} or /orders/{id}/submissions."""
    parts = path.split(f'/{resource}/')
    if len(parts) < 2:
        return ''
    remainder = parts[1]
    return remainder.split('/')[0].split('?')[0]
