"""
Messages Delete Lambda Handler
Deletes messages from WhatsAppInboundTable or WhatsAppOutboundTable
Also deletes associated media files from S3
ONLY deletes messages - does NOT delete contacts
"""

import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

from lambda_utils.response import cors_response, options_response, extract_origin
from lambda_utils import destructive_confirm
from lambda_utils.audit import record_audit
from lambda_utils.logging import get_logger, log_event
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
dynamodb_client = boto3.client('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Table names - actual tables used by the system
INBOUND_TABLE = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
OUTBOUND_TABLE = os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
INBOUND_WHATSAPP_FUNCTION = os.environ.get('INBOUND_WHATSAPP_FUNCTION', 'wecare-inbound-whatsapp')

# Cache key schemas to avoid repeated describe_table calls
_key_schema_cache = {}

def _get_key_schema(table_name):
    """Get the key schema for a DynamoDB table (cached)."""
    if table_name not in _key_schema_cache:
        try:
            desc = dynamodb_client.describe_table(TableName=table_name)
            _key_schema_cache[table_name] = desc['Table']['KeySchema']
        except Exception:
            _key_schema_cache[table_name] = [{'AttributeName': 'id', 'KeyType': 'HASH'}]
    return _key_schema_cache[table_name]

def _build_delete_key(table_name, item):
    """Build the correct Key dict for delete_item based on actual table key schema."""
    schema = _get_key_schema(table_name)
    key = {}
    for ks in schema:
        attr = ks['AttributeName']
        if attr in item:
            key[attr] = item[attr]
        elif attr == 'id' and 'messageId' in item:
            key[attr] = item['messageId']
        elif attr == 'messageId' and 'id' in item:
            key[attr] = item['id']
    return key

def handler(event, context):
    """
    Delete a message by ID from the appropriate table.
    Also deletes associated media files from S3.
    ONLY deletes the message - does NOT affect contacts.
    """
    origin = extract_origin(event)
    
    # Handle OPTIONS preflight
    rc = event.get('requestContext', {})
    evt_method = rc.get('http', {}).get('method', event.get('httpMethod', ''))
    if evt_method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    # Operator is the floor for deleting ONE message. `clear-all` re-gates at Admin
    # below, because wiping both tables is a different act from deleting a message
    # somebody asked you to remove.
    _auth = require_auth(event, required_role='Operator')
    if _auth is not None:
        return _auth

    # Support both API Gateway v1 (REST) and v2 (HTTP) event formats
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        http_method = request_context['http'].get('method', 'DELETE').upper()
        path = request_context['http'].get('path', '')
    else:
        http_method = event.get('httpMethod', 'DELETE').upper()
        path = event.get('path', '')
    if not path:
        path = event.get('rawPath', '')

    # ── DELETE|POST /messages/clear-all — bulk wipe both tables ──
    # Both verbs route here; API Gateway does not expose DELETE on every stage, so the
    # POST form exists as an alias. Gating one and not the other would gate neither.
    if 'clear-all' in path and http_method in ('DELETE', 'POST'):
        return _handle_clear_all(event, origin)

    # ── PATCH/PUT: Update payment/invoice fields ──
    if http_method in ('PUT', 'PATCH'):
        return _handle_update(event, origin)

    if http_method == 'POST':
        return _handle_create_invoice(event, origin)
    
    try:
        # Get message ID from path
        path_params = event.get('pathParameters', {}) or {}
        message_id = path_params.get('messageId')
        
        if not message_id:
            return cors_response(400, {'error': 'messageId is required'}, origin)
        
        # Get direction from query params to determine which table
        query_params = event.get('queryStringParameters', {}) or {}
        direction = query_params.get('direction', 'INBOUND').upper()
        
        # Also check if we should delete media (default: yes for hard delete)
        delete_media = query_params.get('deleteMedia', 'true').lower() == 'true'
        
        # Select table based on direction
        if direction == 'OUTBOUND':
            table_name = OUTBOUND_TABLE
        else:
            table_name = INBOUND_TABLE
        
        table = dynamodb.Table(table_name)
        
        # First, get the message to check for s3Key (and get all key attributes)
        s3_key = None
        item = None
        try:
            response = table.get_item(Key={'id': message_id})
            item = response.get('Item')
            if item:
                s3_key = item.get('s3Key')
        except ClientError as e:
            if 'ValidationException' in str(e):
                try:
                    response = table.get_item(Key={'messageId': message_id})
                    item = response.get('Item')
                    if item:
                        s3_key = item.get('s3Key')
                except Exception as e:
                    logger.warning(f'Fallback message lookup by messageId failed: {e}')
            if not item:
                try:
                    resp = table.scan(
                        FilterExpression='id = :mid OR messageId = :mid',
                        ExpressionAttributeValues={':mid': message_id},
                        Limit=1
                    )
                    items = resp.get('Items', [])
                    if items:
                        item = items[0]
                        s3_key = item.get('s3Key')
                except Exception as e:
                    logger.warning(f'Scan fallback for message {message_id} failed: {e}')
        
        # Delete media from S3 if exists
        media_deleted = False
        if delete_media and s3_key:
            try:
                actual_key = _find_and_delete_s3_file(s3_key, message_id)
                if actual_key:
                    media_deleted = True
            except Exception as e:
                logger.warning(f'S3 media delete failed for message {message_id}: {e}')
        
        # Delete the message from DynamoDB using proper key schema
        try:
            if item:
                delete_key = _build_delete_key(table_name, item)
                table.delete_item(Key=delete_key)
            else:
                try:
                    table.delete_item(Key={'id': message_id})
                except ClientError:
                    table.delete_item(Key={'messageId': message_id})
        except Exception as e:
            logger.warning(f'DynamoDB delete failed for message {message_id}: {e}')

        return cors_response(200, {
            'success': True,
            'messageId': message_id,
            'table': table_name,
            'mediaDeleted': media_deleted,
            's3Key': s3_key,
            'message': f'Message deleted successfully{" (media also deleted)" if media_deleted else ""}'
        }, origin)
        
    except ClientError as e:
        return cors_response(500, {'error': 'Database error'}, origin)
    except Exception as e:
        return cors_response(500, {'error': 'Internal server error'}, origin)


#: Namespaces this route's confirmation tokens so one minted for a cleanup cannot be
#: redeemed here. See `lambda_utils.destructive_confirm`.
CONFIRM_SCOPE = 'messages_clear_all'
#: The two tables this route empties. Named explicitly so the confirmation token and the
#: audit record describe the same thing the loop below touches.
CLEAR_ALL_SELECTION = ['inbound', 'outbound']


def _clear_all_actor(event):
    """The Cognito `sub` of the caller, falling back to the username. Never a body field."""
    auth = event.get('_auth') or {}
    return str((auth.get('attributes') or {}).get('sub') or auth.get('username') or 'unknown')


def _count_table(tbl_name):
    """Row count for the preview, or -1 if it cannot be read."""
    try:
        table = dynamodb.Table(tbl_name)
        count = 0
        kwargs = {'Select': 'COUNT'}
        while True:
            resp = table.scan(**kwargs)
            count += resp.get('Count', 0)
            if 'LastEvaluatedKey' not in resp:
                break
            kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
        return count
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'clear_all_count_error',
                                   'table': tbl_name, 'error': str(e)[:160]}))
        return -1


def _clear_all_preview(event, origin):
    """GET-equivalent for the wipe: live counts plus a single-use confirmation token.

    Reached by passing `preview: true`, because this route has no GET verb — the handler
    serves DELETE/POST/PUT/PATCH only, and adding a GET arm would change the route table.
    """
    counts = {'inbound': _count_table(INBOUND_TABLE), 'outbound': _count_table(OUTBOUND_TABLE)}
    token = destructive_confirm.mint(
        CONFIRM_SCOPE, CLEAR_ALL_SELECTION, counts, _clear_all_actor(event))
    body = {'preview': True, 'counts': counts, 'confirmationToken': token or ''}
    if token is None:
        body['warning'] = ('Confirmation store unavailable — nothing can be deleted until '
                           'it recovers.')
    return cors_response(200, body, origin)


def _handle_clear_all(event, origin):
    """Bulk wipe ALL messages from both Inbound and Outbound tables.

    Four gates, because this empties the entire customer conversation history in one
    call and was previously reachable with no role at all:

    1. Admin on a STAFF-pool token. Re-gated here rather than inherited: the outer gate
       is Operator, which is right for deleting one message and wrong for deleting all
       of them.
    2. An enrolled second factor. Read off `_auth['mfaEnrolled']`, which `require_auth`
       populates only when Admin is required — hence the re-gate above. `None` (lookup
       failed) refuses, so a Cognito outage cannot open this.
    3. A single-use confirmation token from `{"preview": true}`, so a direct call cannot
       delete and a retry cannot delete twice.
    4. A durable audit row, written BEFORE the first delete and failing CLOSED.

    Returns a 503 rather than proceeding if the audit cannot be recorded: an irreversible
    wipe with no record of who asked for it is worse than a refused wipe.
    """
    from lambda_utils.middleware import require_auth
    denied = require_auth(event, required_role='Admin')
    if denied is not None:
        return denied

    if (event.get('_auth') or {}).get('mfaEnrolled') is not True:
        logger.warning(json.dumps({'event': 'clear_all_refused_no_mfa'}))
        return cors_response(403, {
            'error': 'MFA required',
            'detail': ('Clearing all messages requires a second factor. Enrol an '
                       'authenticator app in your account settings, sign in again, and '
                       'retry.'),
        }, origin)

    try:
        body = json.loads(event.get('body') or '{}')
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    if body.get('preview'):
        return _clear_all_preview(event, origin)

    consumed = destructive_confirm.consume(
        CONFIRM_SCOPE, str(body.get('confirmationToken') or '').strip(),
        CLEAR_ALL_SELECTION)
    if not consumed.get('ok'):
        return cors_response(consumed.get('status', 409),
                             {'error': consumed.get('error', 'Confirmation failed')}, origin)

    actor = _clear_all_actor(event)
    log_id = record_audit(
        action='messages.clear_all',
        actor=actor,
        resource_type='messages',
        resource_id='inbound,outbound',
        details={'selection': CLEAR_ALL_SELECTION,
                 'tables': [INBOUND_TABLE, OUTBOUND_TABLE],
                 'previewCounts': consumed.get('counts', {})},
    )
    if not log_id:
        # `record_audit` fails open by design; this caller cannot afford that.
        logger.error(json.dumps({'event': 'clear_all_refused_audit_unavailable',
                                 'actor': actor}))
        return cors_response(503, {'error': 'Audit log unavailable — nothing was deleted'},
                             origin)

    total = 0
    details = {}
    for tbl_name in (INBOUND_TABLE, OUTBOUND_TABLE):
        try:
            schema = _get_key_schema(tbl_name)
            key_names = [k['AttributeName'] for k in schema]
            table = dynamodb.Table(tbl_name)
            tbl_deleted = 0
            while True:
                # Only project key attributes for efficiency
                proj_aliases = {f'#k{i}': name for i, name in enumerate(key_names)}
                resp = table.scan(
                    ProjectionExpression=', '.join(proj_aliases.keys()),
                    ExpressionAttributeNames=proj_aliases,
                )
                items = resp.get('Items', [])
                if not items:
                    break
                with table.batch_writer() as batch:
                    for item in items:
                        key = {k: item[k] for k in key_names if k in item}
                        if key:
                            batch.delete_item(Key=key)
                            tbl_deleted += 1
                if 'LastEvaluatedKey' not in resp:
                    break
            details[tbl_name.split('-')[-1]] = tbl_deleted
            total += tbl_deleted
        except Exception as e:
            details[tbl_name] = f'error: {str(e)}'
    logger.info(json.dumps({'event': 'messages_clear_all', 'actor': actor,
                            'totalDeleted': total, 'auditLogId': log_id}))
    return cors_response(200, {'success': True, 'totalDeleted': total, 'details': details}, origin)


def _find_and_delete_s3_file(stored_key: str, message_id: str) -> str:
    """
    Find and delete the actual S3 file.
    WhatsApp media ID may be appended to the filename.
    Returns the actual key that was deleted, or None if not found.
    """
    # Root the persisted key: an un-rooted key resolves to nothing, so the delete
    # reported success while leaving the object in place.
    stored_key = media_paths.canonical(stored_key)
    try:
        # First try the exact key
        try:
            s3_client.head_object(Bucket=MEDIA_BUCKET, Key=stored_key)
            s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=stored_key)
            return stored_key
        except ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise
        
        # Key doesn't exist exactly, search with prefix
        if '.' in stored_key:
            base_prefix = stored_key.rsplit('.', 1)[0]
        else:
            base_prefix = stored_key
        
        # List objects with prefix
        response = s3_client.list_objects_v2(
            Bucket=MEDIA_BUCKET,
            Prefix=base_prefix,
            MaxKeys=5
        )
        
        contents = response.get('Contents', [])
        if contents:
            actual_key = contents[0]['Key']
            s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=actual_key)

            return actual_key
        
        # Try with full stored key as prefix
        response = s3_client.list_objects_v2(
            Bucket=MEDIA_BUCKET,
            Prefix=stored_key,
            MaxKeys=5
        )
        
        contents = response.get('Contents', [])
        if contents:
            actual_key = contents[0]['Key']
            s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=actual_key)
            return actual_key
        
        return None
        
    except Exception as e:
        raise


def _handle_update(event, origin):
    """Update editable fields on a payment/invoice record."""
    try:
        path_params = event.get('pathParameters', {}) or {}
        message_id = path_params.get('messageId')
        if not message_id:
            return cors_response(400, {'error': 'messageId required'}, origin)

        try:
            body = json.loads(event.get('body', '{}'))
        except (json.JSONDecodeError, TypeError, ValueError):
            return cors_response(400, {'error': 'Invalid JSON in request body'}, origin)
        # Allowed editable fields
        ALLOWED = {
            'paymentItemName', 'paymentQuantity', 'paymentGstRate',
            'paymentPurpose', 'paymentDueRef', 'status',
            'paymentDiscount', 'paymentShipping',
            'paymentOrderId', 'paymentCustomerName', 'paymentCustomerPhone',
            'paymentCustomerEmail', 'paymentShippingAddress', 'paymentBillingAddress',
            'paymentPayFor',
        }
        updates = {k: v for k, v in body.items() if k in ALLOWED}
        if not updates:
            return cors_response(400, {'error': 'No valid fields to update'}, origin)

        table = dynamodb.Table(INBOUND_TABLE)
        expr_parts = []
        attr_names = {}
        attr_values = {}
        for i, (k, v) in enumerate(updates.items()):
            alias = f'#f{i}'
            val_alias = f':v{i}'
            expr_parts.append(f'{alias} = {val_alias}')
            attr_names[alias] = k
            attr_values[val_alias] = v

        table.update_item(
            Key={'id': message_id},
            UpdateExpression='SET ' + ', '.join(expr_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

        return cors_response(200, {'success': True, 'messageId': message_id, 'updated': list(updates.keys())}, origin)
    except Exception as e:
        return cors_response(500, {'error': 'Internal server error'}, origin)


def _handle_create_invoice(event, origin):
    """Create an invoice from dashboard — invokes inbound-whatsapp handler to generate & send."""
    try:
        try:
            body = json.loads(event.get('body', '{}'))
        except (json.JSONDecodeError, TypeError, ValueError):
            return cors_response(400, {'error': 'Invalid JSON in request body'}, origin)

        # Required fields
        contact_id = body.get('contactId', '')
        item_name = body.get('itemName', '')
        unit_price = float(body.get('unitPrice', 0))
        quantity = int(body.get('quantity', 1))

        if not contact_id or not item_name or unit_price <= 0:
            return cors_response(400, {'error': 'contactId, itemName, and unitPrice > 0 are required'}, origin)

        # Optional fields with defaults
        gst_rate = float(body.get('gstRate', 18))
        shipping = float(body.get('shipping', 49))
        discount = float(body.get('discount', 15))
        purpose = body.get('purpose', '')
        order_id = body.get('orderId', 'Offline')
        customer_name = body.get('customerName', '')
        customer_phone = body.get('customerPhone', '')
        customer_email = body.get('customerEmail', '')
        shipping_address = body.get('shippingAddress', '')
        billing_address = body.get('billingAddress', '')
        phone_number_id = body.get('phoneNumberId', '919330994400')

        # Invoke inbound-whatsapp handler with a special "create_invoice" action
        invoke_payload = {
            'action': 'create_invoice',
            'contactId': contact_id,
            'phoneNumberId': phone_number_id,
            'itemName': item_name,
            'unitPrice': unit_price,
            'quantity': quantity,
            'gstRate': gst_rate,
            'shipping': shipping,
            'discount': discount,
            'purpose': purpose,
            'orderId': order_id,
            'customerName': customer_name,
            'customerPhone': customer_phone,
            'customerEmail': customer_email,
            'shippingAddress': shipping_address,
            'billingAddress': billing_address,
            'senderPhone': customer_phone or contact_id,
        }

        response = lambda_client.invoke(
            FunctionName=INBOUND_WHATSAPP_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps(invoke_payload),
        )

        result_payload = json.loads(response['Payload'].read().decode('utf-8'))


        return cors_response(200, {
            'success': True,
            'message': 'Invoice created and sent via WhatsApp',
            'result': result_payload,
        }, origin)

    except Exception as e:
        return cors_response(500, {'error': 'Internal server error'}, origin)
