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
    single_order_flow,
)
from lambda_utils import (
    canonical_flows,
    contact_key,
    contact_store,
    flow_completion,
    flow_sessions,
    shared_tables,
    whatsapp_templates,
)
from lambda_utils.meta_client import MetaGraphClient

logger = logging.getLogger(__name__)

WABA1_ID = "2094615664435155"
WABA1_SENDER = "phone-number-id-waba1-direct-1016149501586345"
_DIRECT_SCREEN = {
    "submit_request": "NOTE",
    "amend_request": "NOTE",
    "drop_docs": "UPLOAD",
    "request_pickup": "PICKUP_DETAILS",
}
_TOKEN_PREFIX = {
    "submit_request": "srpaid",
    "amend_request": "amendpaid",
    "drop_docs": "drop_docs",
    "request_pickup": "pickuppaid",
}
_meta = MetaGraphClient()


def _send_outcome(response):
    if not isinstance(response, dict):
        return "SEND_UNKNOWN"
    code = int(response.get("statusCode") or 0)
    if 200 <= code < 300:
        return "ACCEPTED"
    if code in (400, 401, 403, 404, 413, 415, 422):
        return "SEND_REJECTED"
    return "SEND_UNKNOWN"


def _template_ready(capability):
    """True only when Meta exposes the exact approved direct-entry launcher we expect."""
    template = whatsapp_templates.PAID_SERVICE_FLOW_TEMPLATES.get(capability)
    published = canonical_flows.published_flow(capability)
    screen = _DIRECT_SCREEN.get(capability)
    if template is None or published is None or not screen:
        return False
    try:
        result = _meta.get(
            f"{WABA1_ID}/message_templates",
            params={
                "fields": "name,status,category,language,components,id",
                "limit": 100,
            },
            waba_id=WABA1_ID,
        )
    except Exception:
        return False
    if _meta.is_error(result):
        return False
    rows = [
        row for row in (result.get("data") or [])
        if str(row.get("name") or "") == template.name
        and str(row.get("language") or "") == template.language
    ]
    if len(rows) != 1:
        return False
    row = rows[0]
    if str(row.get("status") or "") != "APPROVED":
        return False
    if str(row.get("category") or "") != template.category:
        return False

    components = row.get("components") or []
    body = next((x for x in components if x.get("type") == "BODY"), {})
    buttons = next((x for x in components if x.get("type") == "BUTTONS"), {})
    flow_buttons = [
        button for button in (buttons.get("buttons") or [])
        if str(button.get("type") or "") == "FLOW"
    ]
    if "{{1}}" not in str(body.get("text") or "") or len(flow_buttons) != 1:
        return False
    button = flow_buttons[0]
    return (
        str(button.get("flow_id") or "") == str(published.get("flowId") or "")
        and str(button.get("flow_action") or "NAVIGATE") == "NAVIGATE"
        and str(button.get("navigate_screen") or "") == screen
    )


def _single_order_recipient(db, attempt):
    """Return the verified ContactsTable row + canonical phone for this paid attempt."""
    customer_id = str(attempt.get("customerId") or "")
    phone = contact_store.canonical_phone(attempt.get("customerPhone"))
    contact_id = str(attempt.get("contactId") or "").strip()
    if not customer_id or not phone:
        return None
    contacts = db.Table(shared_tables.contacts_table_name())
    try:
        contact = (
            contacts.get_item(Key={"id": contact_id}, ConsistentRead=True).get("Item") or {}
            if contact_id else contact_store.lookup(contacts, phone) or {}
        )
    except Exception:
        return None
    if not contact or contact.get("deletedAt") is not None or contact.get("isDeleted"):
        return None
    if str(contact.get("checkoutCustomerId") or "") != customer_id:
        return None
    if contact_store.canonical_phone(contact.get("phone")) != phone:
        return None
    return contact, phone


def _mark_service_activity(orders, binding, status):
    """Repairable projection of launcher state onto the existing order activity."""
    try:
        rows = binding.order.get("serviceActivities") or []
        index = next(
            i for i, row in enumerate(rows)
            if isinstance(row, dict)
            and str(row.get("paymentAttemptId") or "") == binding.payment_attempt_id
            and str(row.get("serviceCode") or "").upper() == binding.service_code
        )
        orders.update_item(
            Key={"orderId": binding.order_id},
            UpdateExpression=(
                f"SET serviceActivities[{index}].flowStatus=:status, "
                f"serviceActivities[{index}].flowUpdatedAt=:now"
            ),
            ExpressionAttributeValues={
                ":status": status,
                ":now": int(__import__("time").time()),
            },
        )
    except Exception:
        pass


def _launch_single_order_flow(event, lambda_client, *, contract, line, keys, orders):
    """Send exactly one post-invoice launcher for a finalized existing-order service payment."""
    db = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    attempts = db.Table(shared_tables.payment_attempts_table_name())
    attempt_id = str(event.get("paymentAttemptId") or "")
    attempt = attempts.get_item(
        Key={"paymentAttemptId": attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    if (
        str(attempt.get("status") or "") != "PAYMENT_PAID"
        or str(attempt.get("finalizationStage") or "") != "ORDER_FINALIZED"
        or attempt.get("singleOrderService") is not True
        or str(attempt.get("selectedOrderId") or "") != str(line.get("selectedOrderId") or "")
        or str(attempt.get("selectedOrderNumber") or "").upper()
            != str(line.get("selectedOrderNumber") or "").upper()
        or str(attempt.get("serviceCode") or "").upper() != contract.service_code
        or str(attempt.get("serviceSku") or "") != contract.sku
        or str(attempt.get("flowCapability") or "") != contract.flow_capability
    ):
        return {"outcome": "SERVICE_PAYMENT_NOT_FINALIZED"}

    # Deployment-safe rollout: current approved launchers still start at SELECT_TARGET. Do not
    # issue a session or claim a send until Meta approves the direct detail-screen revision.
    if not _template_ready(contract.flow_capability):
        return {
            "outcome": "SERVICE_FLOW_TEMPLATE_PENDING",
            "serviceCode": contract.service_code,
            "flowCapability": contract.flow_capability,
            "orderNumber": str(line.get("selectedOrderNumber") or ""),
        }

    current = str(attempt.get("serviceFlowLaunchStatus") or "")
    if current == "ACCEPTED":
        return {
            "outcome": "SERVICE_FLOW_ALREADY_SENT",
            "serviceCode": contract.service_code,
            "orderNumber": str(line.get("selectedOrderNumber") or ""),
        }
    if current in ("SENDING", "SEND_UNKNOWN"):
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED"}

    resolved = _single_order_recipient(db, attempt)
    if not resolved:
        return {"outcome": "VERIFIED_RECIPIENT_UNAVAILABLE"}
    contact, phone = resolved

    token_prefix = _TOKEN_PREFIX.get(contract.flow_capability)
    if not token_prefix:
        return {"outcome": "SERVICE_FLOW_CAPABILITY_UNSUPPORTED"}
    token = flow_sessions.mint_token(token_prefix, phone, "1")
    try:
        flow_sessions.record_session(
            db.Table(flow_sessions.table_name()),
            capability=contract.flow_capability,
            token=token,
            launch_channel=flow_sessions.LAUNCH_PAYMENT,
            initiated_by="single_order_post_invoice",
            payment_attempt_id=attempt_id,
            order_id=str(line.get("selectedOrderId") or ""),
            order_number=str(line.get("selectedOrderNumber") or ""),
            service_code=contract.service_code,
        )
        session = flow_sessions.verify_session(
            db.Table(flow_sessions.table_name()),
            capability=contract.flow_capability,
            token=token,
            rejected_message="This service form is no longer available.",
        )
        binding = single_order_flow.verify_paid_session(
            session=session,
            attempts=attempts,
            orders=orders,
            capability=contract.flow_capability,
            service_code=contract.service_code,
            phone=phone,
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_SESSION_UNAVAILABLE"}

    try:
        attempts.update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression=(
                "SET serviceFlowLaunchStatus=:sending, serviceFlowIssuedAt=:now, "
                "serviceFlowTokenDigest=:digest, updatedAt=:now"
            ),
            ConditionExpression=(
                "#status=:paid AND finalizationStage=:finalized "
                "AND (attribute_not_exists(serviceFlowLaunchStatus) "
                "OR serviceFlowLaunchStatus=:rejected)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":paid": "PAYMENT_PAID",
                ":finalized": "ORDER_FINALIZED",
                ":sending": "SENDING",
                ":rejected": "SEND_REJECTED",
                ":now": int(__import__("time").time()),
                ":digest": flow_sessions.token_digest(token),
            },
        )
    except Exception:
        return {"outcome": "SERVICE_FLOW_RECONCILIATION_REQUIRED"}

    body = {
        "contactId": contact_key.resolve(contact),
        "recipientPhone": phone,
        "phoneNumberId": WABA1_SENDER,
        "idempotencyKey": "single-order-flow:" + attempt_id,
        **whatsapp_templates.paid_service_flow_send_fields(
            contract.flow_capability,
            token,
            binding.order_number,
        ),
    }
    answer = None
    try:
        response = lambda_client.invoke(
            FunctionName="wecare-outbound-whatsapp:live",
            InvocationType="RequestResponse",
            Payload=json.dumps({"body": json.dumps(body)}).encode(),
        )
        raw = response["Payload"].read()
        answer = json.loads(raw or b"{}")
        if response.get("FunctionError"):
            answer = None
    except Exception:
        answer = None

    status = _send_outcome(answer)
    try:
        attempts.update_item(
            Key={"paymentAttemptId": attempt_id},
            UpdateExpression=(
                "SET serviceFlowLaunchStatus=:status, serviceFlowLaunchUpdatedAt=:now, "
                "updatedAt=:now"
            ),
            ExpressionAttributeValues={
                ":status": status,
                ":now": int(__import__("time").time()),
            },
        )
    except Exception:
        if status == "ACCEPTED":
            status = "SEND_UNKNOWN"
    _mark_service_activity(orders, binding, status)

    return {
        "outcome": "SERVICE_FLOW_SENT" if status == "ACCEPTED" else "SERVICE_FLOW_PENDING",
        "serviceCode": contract.service_code,
        "flowCapability": contract.flow_capability,
        "orderNumber": binding.order_number,
        "sendStatus": status,
    }


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


def prepare_and_send(event, lambda_client, get_flow):
    """Activate the paid service and, after invoice delivery, launch its one fulfilment path.

    New single-order Flow services use only the finalized PaymentAttempt + existing Order activity.
    They never enter the legacy ServiceRequests activation path and never mint a WD-REQ number.
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
                or contract.flow_capability != str(line.get('flowCapability') or '')):
            return {'outcome': 'SERVICE_CONTRACT_MISMATCH'}

        # Vault has no Meta Flow. A single-order Vault payment created before the generic route
        # was closed has no file binding, so it cannot be fulfilled safely. Fail closed instead
        # of pretending "vault" is a Flow or unlocking an arbitrary customer file.
        if contract.fulfillment_kind == 'secure_download':
            return {
                'outcome': 'VAULT_SECURE_FILE_BINDING_REQUIRED',
                'serviceCode': contract.service_code,
                'orderNumber': selected_order_number,
            }

        return _launch_single_order_flow(
            event,
            lambda_client,
            contract=contract,
            line=line,
            keys=keys,
            orders=orders,
        )

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
