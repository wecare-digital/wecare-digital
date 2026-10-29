"""Native form for one already-paid Submit Request service purchase."""
import os
import json
import logging
import boto3
from lambda_utils.ecommerce import paid_submit_request as paid
from lambda_utils.ecommerce import (
    service_request_store as store,
    service_requests,
    request_service_contracts,
    order_keys,
)
from lambda_utils import flow_completion, shared_tables

logger = logging.getLogger(__name__)


def tables():
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return (db.Table('stack-wecare-digital-ServiceRequestsTable'),
            db.Table('stack-wecare-digital-CommerceKeys'),
            db.Table(shared_tables.orders_table_name()))


def route(action, screen, data, token):
    if action == 'ping':
        return {'data': {'status': 'active'}}
    requests, keys, orders = tables()
    try:
        row = paid.resolve(requests, keys, token)
        if row.get('detailsSubmittedAt'):
            mirror(row)
            return {'screen': 'DONE', 'data': {'request_number': row['publicRequestId']}}
        if action == 'INIT' or (action == 'BACK' and screen == 'SELECT_RECORD'):
            choices = paid.list_orders(orders, row)
            if not choices:
                return {'screen': 'NO_ORDERS', 'data': {}}
            return {'screen': 'SELECT_RECORD', 'data': {'orders': choices,
                    'request_number': row['publicRequestId']}}
        if action == 'data_exchange' and screen == 'REVIEW':
            saved = paid.submit(requests, keys, orders, token, data)
            mirror(saved)
            return {'screen': 'DONE', 'data': {'request_number': saved['publicRequestId']}}
        return {'data': data}
    except Exception as error:
        # No raw exception, payment data, token or request details reach the handset.
        logger.warning(json.dumps({'event': 'paid_request_flow_unavailable',
                                   'error': type(error).__name__}))
        return {'screen': 'UNAVAILABLE', 'data': {}}


def mirror(row):
    """Repairable workspace projection through the one Flow completion writer."""
    form = {
        'order_id': row.get('parentOrderId', ''),
        'subject': row.get('subject', ''),
        'description': row.get('description', ''),
        'serviceOrderId': row.get('orderId', ''),
        'referenceId': row.get('referenceId', ''),
    }
    result = flow_completion.claim_completion(
        flow_token=row['publicRequestId'],
        screen='REVIEW',
        flow_code='01.WD_PAID_SR',
        flow_type='form_submit',
        phone=row.get('flowPhone', ''),
        contact_id=row.get('flowContactId', ''),
        form_data=form,
        submission_id=row['publicRequestId'],
        status='submitted',
        channel=flow_completion.CHANNEL_WHATSAPP,
        extra={
            'flowId': paid.FLOW_ID,
            'flowName': 'Paid Submit Request',
            'paymentStatus': 'paid',
            'customerId': row.get('customerId', ''),
            'createdAt': row.get('detailsSubmittedAt'),
            'orderId': row.get('parentOrderId', ''),
            'serviceOrderId': row.get('orderId', ''),
            'requestId': row['publicRequestId'],
            'referenceId': row.get('referenceId', ''),
            'subject': row.get('subject', ''),
            'description': row.get('description', ''),
        },
        ttl_seconds=0,
    )
    return result


def send_review(event, lambda_client):
    """Legacy internal action retained as a no-op.

    The paid invoice template already contains the Leave Review Flow button, so sending a
    standalone review template here would duplicate the customer prompt.
    """
    return {'outcome': 'REVIEW_INCLUDED_IN_INVOICE_TEMPLATE'}


def _single_order_fulfillment(requests, *, event, payref, line, contract):
    """Create/read one internal paid fulfillment row for the already-finalized payment.

    The key is payment-attempt scoped and never customer-facing. There is no WD-REQ identifier,
    no second order and no catalog-service session on this path.
    """
    attempt = str(event.get('paymentAttemptId') or '').strip()
    order_id = str(line.get('selectedOrderId') or '').strip()
    order_number = str(line.get('selectedOrderNumber') or '').strip()
    reference = str(event.get('referenceId') or '').strip()
    customer_id = str(payref.get('customerId') or '').strip()
    if not (attempt and order_id and order_number and reference and customer_id):
        return '', None
    key = 'FULFILLMENT#' + attempt
    now = int(time.time())
    item = {
        'requestId': key,
        'recordType': 'PAID_SERVICE_FULFILLMENT',
        'kind': contract.service_code,
        'customerId': customer_id,
        'orderId': order_id,
        'orderNumber': order_number,
        'paymentAttemptId': attempt,
        'referenceId': reference,
        'serviceVariantId': contract.sku,
        'flowCapability': contract.flow_capability,
        'fulfillmentKind': contract.fulfillment_kind,
        'paidAt': now,
        'updatedAt': now,
    }
    try:
        requests.put_item(Item=item, ConditionExpression='attribute_not_exists(requestId)')
        return key, item
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
            raise
        current = requests.get_item(Key={'requestId': key}, ConsistentRead=True).get('Item') or {}
        immutable = ('kind', 'customerId', 'orderId', 'orderNumber', 'paymentAttemptId',
                     'referenceId', 'serviceVariantId', 'flowCapability', 'fulfillmentKind')
        if not current or any(str(current.get(k) or '') != str(item.get(k) or '') for k in immutable):
            return '', None
        return key, current


def prepare_and_send(event, lambda_client, get_flow):
    """Activate the paid service without sending any post-payment interactive Flow.

    The invoice template is the only post-payment customer message. Service details remain
    available through the normal Submit Request Flow entry points; payment finalization does not
    push a second Flow invitation.
    """
    requests, keys, _ = tables()
    payref = order_keys.resolve_payment_reference(keys, str(event.get('referenceId') or '')) or {}
    line = payref.get('serviceLine') if isinstance(payref.get('serviceLine'), dict) else {}

    # New single-order service purchases are already financially finalized onto the selected
    # existing order. They MUST NOT enter store.activate(), because that legacy path creates a
    # ServiceRequestsTable row and mints WD-REQ-*.
    if line.get('singleOrder') is True:
        claim = order_keys.resolve_order_for_payment(
            keys, str(event.get('paymentAttemptId') or '')) or {}
        selected_order_id = str(line.get('selectedOrderId') or '')
        selected_order_number = str(line.get('selectedOrderNumber') or '')
        if (not selected_order_id
                or str(claim.get('orderIdRef') or '') != selected_order_id
                or selected_order_id != str(event.get('orderId') or '')
                or str(claim.get('orderNumber') or '') != selected_order_number):
            return {'outcome': 'ORDER_MISMATCH'}

        contract = request_service_contracts.request_service_contract(line.get('serviceCode'))
        if (contract is None
                or contract.sku != str(line.get('sku') or '')
                or contract.flow_capability != str(line.get('flowCapability') or '')
                or contract.fulfillment_kind != str(line.get('fulfillmentKind') or '')):
            return {'outcome': 'SERVICE_CONTRACT_MISMATCH'}

        # Vault has no Meta Flow. A single-order Vault payment created before the generic route
        # was closed has no file binding, so it cannot be fulfilled safely. Fail closed instead
        # of pretending Vault is a Flow or unlocking an arbitrary customer file.
        if contract.fulfillment_kind == 'secure_download':
            return {
                'outcome': 'VAULT_SECURE_FILE_BINDING_REQUIRED',
                'serviceCode': contract.service_code,
                'orderNumber': selected_order_number,
            }

        # F003 already exists. Bind the paid single-order purchase to one internal fulfillment
        # row and launch F003 from that payment proof. Replays hit the same row/session claim.
        if contract.service_code == service_requests.DROP_DOCS:
            request_key, _row = _single_order_fulfillment(
                requests, event=event, payref=payref, line=line, contract=contract)
            if not request_key:
                return {'outcome': 'SERVICE_FULFILLMENT_UNAVAILABLE'}
            from .paid_drop_docs import prepare_and_send as drop_docs_send
            return drop_docs_send(event, lambda_client, request_key=request_key)

        # The remaining three services are blocked before payment until their new canonical
        # Meta Flows are PUBLISHED. Keep the post-payment seam fail-closed too.
        return {
            'outcome': 'SERVICE_FLOW_PENDING_WIRING',
            'serviceCode': contract.service_code,
            'flowCapability': contract.flow_capability,
            'orderNumber': selected_order_number,
        }

    if payref.get('nativeCatalogService'):
        result = lambda_client.invoke(
            FunctionName='wecare-commerce:live',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'internalAction': 'finalizeNativeCatalogService',
                'paymentAttemptId': str(event.get('paymentAttemptId') or ''),
            }).encode(),
        )
        answer = json.loads(result['Payload'].read())
        if result.get('FunctionError') or answer.get('outcome') != 'NATIVE_SERVICE_FINALIZED':
            return {'outcome': 'NATIVE_SERVICE_FINALIZATION_PENDING'}

    outcome = store.activate(
        requests,
        keys,
        reference_id=str(event.get('referenceId') or ''),
        payment_attempt_id=str(event.get('paymentAttemptId') or ''),
    )
    if outcome.outcome not in (store.ACTIVATED, store.ALREADY_ACTIVE):
        return {'outcome': outcome.outcome}

    claim = order_keys.resolve_order_for_payment(
        keys, str(event.get('paymentAttemptId') or '')) or {}
    oid = claim.get('orderIdRef')
    if not oid or oid != event.get('orderId'):
        return {'outcome': 'ORDER_MISMATCH'}

    pointer = requests.get_item(
        Key={'requestId': 'ORDER#' + oid}, ConsistentRead=True).get('Item') or {}
    target = pointer.get('targetRequestId', '')
    candidate = requests.get_item(
        Key={'requestId': target}, ConsistentRead=True).get('Item') or {}

    if candidate.get('kind') == 'VAULT':
        from .paid_vault import prepare_and_send as vault_send
        return vault_send(event, lambda_client)
    if candidate.get('kind') == service_requests.DROP_DOCS:
        from .paid_drop_docs import prepare_and_send as drop_docs_send
        return drop_docs_send(event, lambda_client)
    if candidate.get('kind') != 'SUBMIT_REQUEST':
        return {'outcome': 'NOT_SUBMIT_REQUEST'}

    row, _token = paid.prepare(requests, keys, target)
    if row.get('detailsSubmittedAt'):
        mirror(row)
        return {'outcome': 'ALREADY_COMPLETED'}

    return {
        'outcome': 'SERVICE_ACTIVATED_NO_POSTPAY_FLOW',
        'requestId': row['publicRequestId'],
    }
