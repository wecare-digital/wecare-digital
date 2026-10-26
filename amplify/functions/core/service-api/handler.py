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
  /sehat-appointments                GET (list), POST (create)
  /sehat-appointments/{id}           PUT
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
from lambda_utils.audit import record_audit
from lambda_utils.ecommerce import order_patch, order_record, service_request_input

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

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
INVOICE_ENGINE_FUNCTION = os.environ.get('INVOICE_ENGINE_FUNCTION', 'wecare-commerce:live')

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
DOCUMENT_UPLOAD_MAX_BYTES = int(os.environ.get('DOCUMENT_UPLOAD_MAX_BYTES', str(200 * 1024 * 1024)))
DOCUMENT_UPLOAD_URL_TTL = int(os.environ.get('DOCUMENT_UPLOAD_URL_TTL_SECONDS', '900'))

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
        item = order_record.staff_order(body, short=_gen_id(), now=now,
                                        contact_id=contact_id, customer_phone=phone)
        try:
            table.put_item(Item=item, ConditionExpression='attribute_not_exists(orderId)')
            return _resp(201, order_record.view(item))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                raise
            # Collision. Regenerate rather than overwrite.

    # Fail closed. A caller that gets no order is a visible error someone fixes; a caller that
    # gets a 201 for an order that replaced another one is not.
    return _resp(503, {'error': 'Could not allocate a unique order id', 'retryable': True})



def _cancel_linked_invoice(invoice_id: str, reason: str, request_id: str):
    """Void a linked unpaid invoice before cancelling its order.

    The invoice engine owns invoice/payment race handling. This internal invoke deliberately
    has no API Gateway identity, so its own require_auth treats it as Lambda-to-Lambda while
    the staff actor was already authenticated here.
    """
    try:
        response = lambda_client.invoke(
            FunctionName=INVOICE_ENGINE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'rawPath': f'/invoices/{invoice_id}/cancel',
                'requestContext': {'http': {'method': 'POST'}},
                'pathParameters': {'invoiceId': invoice_id},
                'body': json.dumps({'invoiceId': invoice_id, 'reason': reason}),
            }).encode(),
        )
        if response.get('FunctionError'):
            return False, 503, {'error': 'Invoice cancellation could not be confirmed',
                                'errorCode': 'ORDER_CANCEL_INVOICE_UNAVAILABLE'}
        payload = json.loads(response['Payload'].read())
        status = int(payload.get('statusCode', 500))
        try:
            body = json.loads(payload.get('body') or '{}')
        except (json.JSONDecodeError, TypeError, ValueError):
            body = {}
        if 200 <= status < 300:
            return True, status, body
        code = str(body.get('errorCode') or '')
        if code in {'INVOICE_CANCEL_MONEY_MOVED', 'INVOICE_CANCEL_PAYMENT_CHANGED'}:
            return False, 409, {
                'error': 'Linked invoice cannot be voided because payment state changed',
                'errorCode': 'ORDER_CANCEL_MONEY_MOVED',
            }
        return False, 409 if status == 409 else 503, {
            'error': 'Linked invoice must be safely voided before order cancellation',
            'errorCode': code or 'ORDER_CANCEL_INVOICE_FAILED',
        }
    except Exception as exc:  # noqa: BLE001 - fail closed on orchestration ambiguity
        logger.warning(json.dumps({
            'event': 'order_cancel_invoice_invoke_failed',
            'requestId': request_id,
            'error': type(exc).__name__,
        }))
        return False, 503, {
            'error': 'Linked invoice cancellation outcome is unavailable; retry safely',
            'errorCode': 'ORDER_CANCEL_INVOICE_UNAVAILABLE',
            'retryable': True,
        }


def _write_cancellation_history(order_id: str, old_status: str, actor: str,
                                reason: str, changed_at: int) -> bool:
    """Durable, idempotent cancellation history. Same order => same history key."""
    try:
        dynamodb.Table(STATUS_HISTORY_TABLE).put_item(
            Item={
                'historyId': f'ORDER_CANCEL#{order_id}',
                'submissionId': '',
                'orderId': order_id,
                'oldStatus': old_status,
                'newStatus': 'canceled',
                'changedBy': actor,
                'notes': reason,
                'changedAt': changed_at,
            },
            ConditionExpression='attribute_not_exists(historyId)',
        )
        return True
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return True
        logger.warning(json.dumps({
            'event': 'order_cancel_history_failed',
            'orderId': order_id,
            'error': type(exc).__name__,
        }))
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            'event': 'order_cancel_history_failed',
            'orderId': order_id,
            'error': type(exc).__name__,
        }))
        return False


def _cancel_order(order_id: str, body: Dict, auth: Optional[Dict], request_id: str) -> Dict:
    """Explicit audited cancellation. Generic status PATCH remains unable to cancel."""
    table = dynamodb.Table(ORDERS_TABLE)
    current = table.get_item(Key={'orderId': order_id}, ConsistentRead=True).get('Item')
    if not current:
        return _resp(404, {'error': 'Order not found'})

    decision, error = order_patch.validate_order_cancellation(current, body.get('reason'))
    if error:
        status = 400 if error.get('errorCode') in {
            'ORDER_CANCEL_REASON_REQUIRED', 'ORDER_CANCEL_REASON_INVALID',
        } else 409
        return _resp(status, error)
    assert decision is not None

    actor_info = auth or {}
    actor = str(actor_info.get('username') or actor_info.get('email') or '').strip()
    if not actor:
        return _resp(403, {'error': 'Authenticated staff actor required',
                           'errorCode': 'ORDER_CANCEL_ACTOR_REQUIRED'})

    reason = decision['reason']
    previous_status = str(current.get('cancellationPreviousStatus')
                          or decision['currentStatus'] or 'pending')
    canceled_at = int(current.get('canceledAt') or _now())

    if not decision['idempotent']:
        invoice_id = str(current.get('invoiceId') or '').strip()
        if invoice_id:
            ok, status, invoice_result = _cancel_linked_invoice(
                invoice_id, reason, request_id)
            if not ok:
                return _resp(status, invoice_result)

        names = {
            '#orderStatus': 'orderStatus',
            '#status': 'status',
        }
        values = {
            ':canceled': 'canceled',
            ':reason': reason,
            ':actor': actor,
            ':now': canceled_at,
            ':previous': previous_status,
        }
        sets = [
            '#orderStatus = :canceled',
            '#status = :canceled',
            'cancellationReason = :reason',
            'canceledBy = :actor',
            'canceledAt = :now',
            'cancellationPreviousStatus = :previous',
            'updatedAt = :now',
        ]
        conditions = ['attribute_exists(orderId)']
        for guard_name, field in (
            ('order_status', 'orderStatus'),
            ('status_alias', 'status'),
            ('fulfillment_status', 'fulfillmentStatus'),
            ('payment', 'paymentStatus'),
        ):
            alias = f'#guard_{guard_name}'
            names[alias] = field
            if field in current:
                value_alias = f':guard_{guard_name}'
                values[value_alias] = current.get(field)
                conditions.append(f'{alias} = {value_alias}')
            else:
                conditions.append(f'attribute_not_exists({alias})')
        if 'fulfillmentStatus' in current:
            names['#fulfillmentStatus'] = 'fulfillmentStatus'
            sets.append('#fulfillmentStatus = :canceled')

        try:
            table.update_item(
                Key={'orderId': order_id},
                UpdateExpression='SET ' + ', '.join(sets),
                ConditionExpression=' AND '.join(conditions),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return _resp(409, {
                    'error': 'Order changed while cancellation was being committed; reload and retry',
                    'errorCode': 'ORDER_CANCEL_STALE',
                })
            raise

    if not _write_cancellation_history(
            order_id, previous_status, actor, reason, canceled_at):
        return _resp(503, {
            'error': 'Order is cancelled but its durable history needs repair; retry this cancellation',
            'errorCode': 'ORDER_CANCEL_AUDIT_RETRY',
            'canceled': True,
            'retryable': True,
        })

    try:
        record_audit(
            action='order.cancel',
            actor=actor,
            resource_type='order',
            resource_id=order_id,
            details={
                'previousStatus': previous_status,
                'linkedInvoice': bool(current.get('invoiceId')),
                'requestId': request_id,
            },
        )
    except Exception as exc:  # audit helper is supplementary to strict status history
        logger.warning(json.dumps({
            'event': 'order_cancel_secondary_audit_failed',
            'orderId': order_id,
            'error': type(exc).__name__,
        }))

    return _resp(200, {
        'canceled': True,
        'orderId': order_id,
        'status': 'canceled',
        'idempotent': bool(decision['idempotent']),
    })



def _update_order(order_id: str, body: Dict, auth: Optional[Dict] = None,
                  request_id: str = 'local') -> Dict:
    if str(body.get('action') or '').strip().lower() == 'cancel':
        return _cancel_order(order_id, body, auth, request_id)
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
            'ORDER_CANCEL_REQUIRES_WORKFLOW',
        }
        return _resp(409 if error.get('errorCode') in conflict_codes else 400, error)

    assert updates is not None
    status_mutation = 'orderStatus' in updates
    tracking_mutation = 'trackingSource' in updates
    now = _now()
    updates['updatedAt'] = now
    if tracking_mutation:
        updates['trackingUpdatedAt'] = now

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

    if tracking_mutation:
        for guard_name, field in (
            ('carrier_name', 'carrierName'),
            ('tracking_number', 'trackingNumber'),
            ('tracking_url', 'trackingUrl'),
            ('tracking_source', 'trackingSource'),
            ('tracking_updated_at', 'trackingUpdatedAt'),
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
    """Create an order-linked service case. This path never changes money state."""
    cleaned, validation_error = service_request_input.validate(body)
    if validation_error:
        return _resp(400, validation_error)
    assert cleaned is not None

    order_id = cleaned['orderId']
    try:
        order_row = dynamodb.Table(ORDERS_TABLE).get_item(
            Key={'orderId': order_id}, ConsistentRead=True
        ).get('Item')
    except Exception as exc:  # noqa: BLE001 - storage failure is retryable, not "not found"
        logger.warning(f'Linked order lookup failed: {type(exc).__name__}')
        return _resp(503, {
            'error': 'Linked order could not be verified',
            'errorCode': 'SERVICE_ORDER_LOOKUP_FAILED',
            'retryable': True,
        })
    if not order_row:
        return _resp(404, {
            'error': 'Linked order not found',
            'errorCode': 'SERVICE_ORDER_NOT_FOUND',
        })

    customer_phone = str(order_row.get('customerPhone') or '')
    contact_id = str(order_row.get('contactId') or '') or _contact_id_for_phone(customer_phone)
    for _ in range(5):
        short = _gen_id('WD-SR-')
        result = flow_completion.claim_completion(
            flow_token=short, screen='STAFF', flow_code='01.WD_SR', flow_type='form_submit',
            phone=contact_store.digits(customer_phone), contact_id=contact_id,
            form_data=cleaned,
            reference_prefix='WD-SR', submission_id=short, status='open',
            extra={
                'flowId': flow_completion.WEB_SUBMIT_FLOW_ID,
                'orderId': order_id,
                'requestType': cleaned['requestType'],
                'subject': cleaned['subject'],
                'description': cleaned['description'],
                # A staff/web case is not the paid WhatsApp service product. It must not
                # create a charge/refund state by accepting a browser-supplied flag.
                'paymentRequired': False,
            },
            ttl_seconds=0, channel=flow_completion.CHANNEL_STAFF)
        if result.created:
            history_note = (
                'Return/refund request opened; no refund or cancellation initiated'
                if cleaned['requestType'] == 'Return / Refund'
                else 'Service request submitted via workspace'
            )
            _log_status_history(short, order_id, '', 'open', 'system', history_note)
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
    # Historical inbound code mirrored every WhatsApp image/document into DocumentTable.
    # Those rows are conversation attachments, not Drop Docs business records. Keep an
    # explicit source=whatsapp diagnostic query, but exclude them from the normal workspace.
    if not source:
        items = [i for i in items if i.get('sourceType') != 'whatsapp']
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
    # while historical rows may still name a retired WhatsApp media key. Normalise on
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


def _document_record(body: Dict, *, doc_id: str, storage_key: str = '',
                     status: str = 'uploaded') -> Dict:
    """Build one staff-created DocumentTable row in the same shape as inbound documents."""
    now = _now()
    phone = str(body.get('customerPhone') or '').strip()
    if phone:
        try:
            phone = contact_store.canonical_phone(phone)
        except Exception:
            # Keep the operator's input visible rather than silently guessing a country.
            phone = str(body.get('customerPhone') or '').strip()

    item = {
        'documentId': doc_id,
        'contactId': str(body.get('contactId') or '').strip(),
        'customerPhone': phone,
        'customerName': str(body.get('customerName') or '').strip(),
        'orderId': body.get('orderId'),
        'sourceType': 'manual',
        'documentType': body.get('type', body.get('documentType', 'other')),
        'documentTypeLabel': str(body.get('typeLabel') or body.get('documentTypeLabel') or '').strip(),
        'fileName': str(body.get('fileName') or '').strip(),
        'mimeType': str(body.get('mimeType') or body.get('contentType') or '').strip(),
        'fileSize': int(body.get('fileSize') or body.get('sizeBytes') or 0),
        'storageKey': storage_key,
        's3Bucket': DOCS_S3_BUCKET if storage_key else '',
        'verificationStatus': status,
        'remarks': body.get('notes', body.get('remarks', '')),
        'createdAt': now,
        'updatedAt': now,
    }
    if status == 'uploaded':
        item['uploadedAt'] = now
    return {k: v for k, v in item.items() if v is not None and v != ''}


def _normalise_document(item: Dict) -> Dict:
    """Frontend projection without mutating the row held by the caller."""
    out = dict(item)
    out['source'] = out.get('sourceType', out.get('source', 'manual'))
    out['type'] = out.get('documentType', out.get('type', 'other'))
    out['typeLabel'] = out.get('documentTypeLabel', out.get('typeLabel', ''))
    out['status'] = out.get('verificationStatus', out.get('status', 'uploaded'))
    out['notes'] = out.get('remarks', out.get('notes', ''))
    out['fileSize'] = int(out.get('fileSize') or 0)
    return out


def _create_document(body: Dict) -> Dict:
    """Create a metadata-only document record (legacy/manual fallback)."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    doc_id = f'WD-DOC-{_gen_id()}'
    item = _document_record(body, doc_id=doc_id, status='uploaded')
    table.put_item(Item=item)
    return _resp(201, _normalise_document(item))


def _init_document_upload(body: Dict) -> Dict:
    """Create a pending manual document and return a private presigned PUT URL."""
    file_name = str(body.get('fileName') or '').strip()
    content_type = str(body.get('mimeType') or body.get('contentType') or 'application/octet-stream').strip()
    try:
        size = int(body.get('fileSize') or body.get('sizeBytes') or 0)
    except (TypeError, ValueError):
        size = 0

    if not file_name:
        return _resp(400, {'error': 'FILE_NAME_REQUIRED', 'message': 'Choose a file to upload.'})
    if size <= 0:
        return _resp(400, {'error': 'FILE_SIZE_REQUIRED', 'message': 'The selected file is empty.'})
    if size > DOCUMENT_UPLOAD_MAX_BYTES:
        return _resp(413, {
            'error': 'FILE_TOO_LARGE',
            'message': f'The selected file is larger than {DOCUMENT_UPLOAD_MAX_BYTES} bytes.',
        })
    if not (str(body.get('customerPhone') or '').strip() or str(body.get('contactId') or '').strip()):
        return _resp(400, {
            'error': 'CUSTOMER_REQUIRED',
            'message': 'Select a customer or enter their mobile number.',
        })

    doc_id = f'WD-DOC-{_gen_id()}'
    # Opaque key: customer names and original filenames never become S3 paths.
    storage_key = media_paths.DROP_DOCS_UPLOAD_PREFIX + 'manual/' + uuid.uuid4().hex
    item = _document_record(body, doc_id=doc_id, storage_key=storage_key, status='pending')
    item['fileSize'] = size
    item['mimeType'] = content_type
    dynamodb.Table(DOCUMENTS_TABLE).put_item(Item=item)

    try:
        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': DOCS_S3_BUCKET, 'Key': storage_key, 'ContentType': content_type},
            ExpiresIn=DOCUMENT_UPLOAD_URL_TTL,
        )
    except Exception:
        logger.exception('Could not create document upload URL')
        return _resp(503, {'error': 'UPLOAD_URL_UNAVAILABLE', 'message': 'Could not start the upload.'})

    return _resp(201, {
        'documentId': doc_id,
        'uploadUrl': upload_url,
        'expiresInSeconds': DOCUMENT_UPLOAD_URL_TTL,
        'contentType': content_type,
    })


def _confirm_document_upload(doc_id: str) -> Dict:
    """Activate a pending manual document only after S3 proves the bytes exist."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    item = table.get_item(Key={'documentId': doc_id}, ConsistentRead=True).get('Item')
    if not item:
        return _resp(404, {'error': 'Document not found'})
    if item.get('sourceType') != 'manual' or not item.get('storageKey'):
        return _resp(409, {'error': 'DOCUMENT_NOT_UPLOADABLE',
                           'message': 'This document was not created by the manual upload flow.'})
    if item.get('verificationStatus') == 'uploaded':
        return _resp(200, _normalise_document(item))
    if item.get('verificationStatus') != 'pending':
        return _resp(409, {'error': 'DOCUMENT_NOT_PENDING',
                           'message': 'This document is not awaiting an upload.'})

    storage_key = media_paths.canonical(item['storageKey'])
    try:
        head = s3_client.head_object(Bucket=DOCS_S3_BUCKET, Key=storage_key)
    except ClientError:
        return _resp(409, {'error': 'UPLOAD_NOT_FOUND',
                           'message': 'The uploaded file was not found. Please upload it again.'})

    size = int(head.get('ContentLength') or 0)
    if size <= 0 or size > DOCUMENT_UPLOAD_MAX_BYTES:
        return _resp(413, {'error': 'FILE_TOO_LARGE',
                           'message': 'The stored file is empty or exceeds the upload limit.'})
    mime_type = str(head.get('ContentType') or item.get('mimeType') or 'application/octet-stream')
    now = _now()
    table.update_item(
        Key={'documentId': doc_id},
        UpdateExpression='SET verificationStatus=:uploaded, fileSize=:size, mimeType=:mime, uploadedAt=:now, updatedAt=:now',
        ConditionExpression='verificationStatus=:pending',
        ExpressionAttributeValues={
            ':uploaded': 'uploaded', ':pending': 'pending', ':size': size, ':mime': mime_type,
            ':now': now,
        },
    )
    item.update({
        'verificationStatus': 'uploaded',
        'fileSize': size,
        'mimeType': mime_type,
        'uploadedAt': now,
        'updatedAt': now,
    })
    return _resp(200, _normalise_document(item))


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
# shape and the list filters. This is the only implementation of these routes: the copy that
# lived in whatsapp-business-api/service_api.py was retired on 2026-10-22 (d8e197d2).

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


def _list_sehat_appointments(params: Dict) -> Dict:
    items = flow_records.list_sehat_appointments(_flow_table(), params)
    return _resp(200, {'slots': items, 'count': len(items)})


def _create_sehat_appointment(body: Dict) -> Dict:
    fields = flow_records.sehat_appointment_fields(body)
    return _create_record(flow_records.SEHAT_APPOINTMENT, body, fields, fields['customerPhone'],
                          flow_records.sehat_appointment_view, status=body.get('status') or 'available')


def _update_sehat_appointment(slot_id: str, body: Dict) -> Dict:
    updates = {f: body[f] for f in flow_records.SEHAT_APPOINTMENT_UPDATE_FIELDS if f in body}
    return _update_record(flow_records.SEHAT_APPOINTMENT, slot_id, updates)


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
    """F002 Leave Review rows plus historical WD_IDEA/WD_REV rows, every channel, every page."""
    items = flow_records.list_reviews(_flow_table(), params)
    return _resp(200, {'reviews': items, 'count': len(items)})


def _create_review(body: Dict) -> Dict:
    return _create_record(flow_records.REVIEW, body, flow_records.review_fields(body),
                          body.get('customerPhone', ''), flow_records.review_view)


def _update_review(review_id: str, body: Dict) -> Dict:
    response = _update_record(flow_records.REVIEW, review_id,
                              flow_records.review_updates(body, _now()))
    if int(response.get('statusCode') or 0) < 300 and 'status' in body:
        _sync_review_inbox_status(review_id, str(body.get('status') or ''))
    return response


def _sync_review_inbox_status(review_id: str, status: str) -> None:
    """Mirror a staff review decision onto the review's Inbox item. Best-effort, never fatal.

    The FlowSubmission row is the record and the Inbox shows a projection of it, so without this
    the Inbox kept showing "Feedback status: pending" after staff moderated a review. The retired
    whatsapp-business-api copy of this API did the mirror; the consolidated one had lost it.

    Two projection shapes exist. Historical endpoint reviews were projected as the MessagesTable
    row `flow:<reviewId>`. F002 reviews are projected onto the inbound message itself, found via
    the `whatsappMessageId` the submission row stores. Every write is conditional on the message
    existing AND naming this review, so the mirror can never create or relabel another message.
    """
    from lambda_utils import message_store

    messages = dynamodb.Table(message_store.MESSAGES_TABLE)
    candidates = [f'flow:{review_id}']
    try:
        row = _flow_table().get_item(Key={'submissionId': review_id}).get('Item') or {}
        wamid = str(row.get('whatsappMessageId') or '').strip()
        if wamid:
            page = messages.query(IndexName='whatsappMessageId-index',
                                  KeyConditionExpression=Key('whatsappMessageId').eq(wamid),
                                  Limit=5)
            candidates.extend(str(item.get('id') or '') for item in page.get('Items') or [])
    except Exception as exc:  # noqa: BLE001 - the review decision is already saved
        logger.warning(json.dumps({'event': 'review_inbox_lookup_failed', 'reviewId': review_id,
                                   'errorType': type(exc).__name__}))
    for message_id in dict.fromkeys(c for c in candidates if c):
        try:
            messages.update_item(
                Key={'id': message_id}, UpdateExpression='SET reviewStatus = :s',
                ConditionExpression='attribute_exists(id) AND reviewId = :rid',
                ExpressionAttributeValues={':s': status, ':rid': review_id})
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                logger.warning(json.dumps({'event': 'review_inbox_status_sync_failed',
                                           'reviewId': review_id,
                                           'errorType': type(exc).__name__}))
        except Exception as exc:  # noqa: BLE001 - best-effort projection
            logger.warning(json.dumps({'event': 'review_inbox_status_sync_failed',
                                       'reviewId': review_id, 'errorType': type(exc).__name__}))


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

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    from lambda_utils.middleware import require_auth
    is_cancel_command = (
        method in ('PATCH', 'PUT')
        and str(body.get('action') or '').strip().lower() == 'cancel'
    )
    _auth = require_auth(event, required_role='Admin' if is_cancel_command else None)
    if _auth is not None:
        return _auth

    logger.info(f'[{request_id}] {method} {path}')

    try:
        # ── ORDERS ──
        # POST /orders/sync is gone with the Wix store sync it served (4ee023cc deleted
        # `_sync_orders` and left this call behind, so the live route answered a NameError 500).
        # It now falls through to the 404 below; the API Gateway route itself can be removed.
        if '/orders/' in path and '/submissions' in path:
            order_id = _extract_path_param(path, 'orders')
            return _get_order_submissions(order_id)
        elif '/orders/' in path:
            order_id = _extract_path_param(path, 'orders')
            if method == 'GET':
                return _get_order(order_id)
            elif method in ('PATCH', 'PUT'):
                return _update_order(order_id, body, auth=event.get('_auth'), request_id=request_id)
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
                if str(body.get('_action') or '').strip().lower() == 'confirm_upload':
                    return _confirm_document_upload(doc_id)
                return _update_document(doc_id, body)
        elif '/documents' in path:
            if method == 'GET':
                return _list_documents(params)
            elif method == 'POST':
                if str(body.get('_action') or '').strip().lower() == 'upload_init':
                    return _init_document_upload(body)
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
        elif '/sehat-appointments/' in path:
            slot_id = _extract_path_param(path, 'sehat-appointments')
            if method in ('PUT', 'PATCH'):
                return _update_sehat_appointment(slot_id, body)
        elif '/sehat-appointments' in path:
            if method == 'GET':
                return _list_sehat_appointments(params)
            elif method == 'POST':
                return _create_sehat_appointment(body)

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
