"""Post-payment delivery for F003 Drop Docs.

A captured standard service order activates exactly one DROP_DOCS request. This module binds a
server-issued Flow session to that paid request before sending the F003 template, so the public
Flow endpoint cannot be opened by an unpaid keyword/session and one paid request cannot authorize
multiple completed uploads.
"""
from __future__ import annotations

import json
import time

import boto3

from lambda_utils import (
    contact_key,
    contact_store,
    customer_auth,
    flow_sessions,
    shared_tables,
    whatsapp_templates,
)
from lambda_utils.ecommerce import service_requests

WABA1_SENDER = "phone-number-id-waba1-direct-1016149501586345"
REQUESTS_TABLE = "stack-wecare-digital-ServiceRequestsTable"
FLOW_CODE = "WD_F003_DROP_DOCS"


def _outcome(response):
    if not isinstance(response, dict):
        return "SEND_UNKNOWN"
    code = int(response.get("statusCode") or 0)
    if 200 <= code < 300:
        return "ACCEPTED"
    if code in (400, 401, 403, 404, 413, 415, 422):
        return "SEND_REJECTED"
    return "SEND_UNKNOWN"


def _recipient(db, row):
    customer_id = str(row.get("customerId") or "")
    if not customer_auth.is_cognito_subject(customer_id):
        return None
    users = boto3.client("cognito-idp").list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + customer_id + '"',
        Limit=2,
    ).get("Users") or []
    if len(users) != 1 or not users[0].get("Enabled", True):
        return None
    attrs = {a["Name"]: a["Value"] for a in users[0].get("Attributes", [])}
    phone = str(attrs.get("phone_number") or "")
    if attrs.get("phone_number_verified") != "true" or not phone:
        return None
    contacts = db.Table(shared_tables.contacts_table_name())
    try:
        contact = contact_store.find_by_phone(contacts, phone)
    except contact_store.IdentityConflict:
        return None
    if (not contact or str(contact.get("checkoutCustomerId") or "") != customer_id
            or contact.get("deletedAt") is not None or contact.get("isDeleted")):
        return None
    return contact, phone


def prepare_and_send(event, lambda_client):
    """Send the paid F003 door once. Money has already moved; never creates a second charge."""
    db = boto3.resource("dynamodb")
    requests = db.Table(REQUESTS_TABLE)
    order_id = str(event.get("orderId") or "")
    pointer = requests.get_item(
        Key={"requestId": "ORDER#" + order_id}, ConsistentRead=True
    ).get("Item") or {}
    request_key = str(pointer.get("targetRequestId") or "")
    row = requests.get_item(Key={"requestId": request_key}, ConsistentRead=True).get("Item") or {}
    if (not request_key or row.get("kind") != service_requests.DROP_DOCS
            or str(row.get("orderId") or "") != order_id
            or str(row.get("paymentAttemptId") or "") != str(event.get("paymentAttemptId") or "")):
        return {"outcome": "DROP_DOCS_PAID_REQUEST_UNAVAILABLE"}

    if row.get("dropDocsCompletedAt"):
        return {"outcome": "DROP_DOCS_ALREADY_COMPLETED", "requestId": row.get("publicRequestId")}

    current = str(row.get("dropDocsFlowNotificationStatus") or "")
    if current == "ACCEPTED":
        return {"outcome": "DROP_DOCS_FLOW_ALREADY_SENT", "requestId": row.get("publicRequestId")}
    if current in ("SENDING", "SEND_UNKNOWN"):
        return {"outcome": "DROP_DOCS_FLOW_RECONCILIATION_REQUIRED"}

    resolved = _recipient(db, row)
    if not resolved:
        return {"outcome": "VERIFIED_RECIPIENT_UNAVAILABLE"}
    contact, phone = resolved

    token = flow_sessions.mint_token("drop_docs", phone, "1")
    try:
        flow_sessions.record_session(
            db.Table(flow_sessions.table_name()),
            capability="drop_docs",
            token=token,
            launch_channel=flow_sessions.LAUNCH_PAYMENT,
            initiated_by="paid_drop_docs",
            service_request_key=request_key,
        )
    except Exception:
        return {"outcome": "DROP_DOCS_SESSION_UNAVAILABLE"}

    try:
        requests.update_item(
            Key={"requestId": request_key},
            UpdateExpression=(
                "SET dropDocsFlowNotificationStatus=:sending, dropDocsFlowIssuedAt=:now, "
                "dropDocsStatus=:awaiting"
            ),
            ConditionExpression=(
                "attribute_not_exists(dropDocsCompletedAt) AND "
                "(attribute_not_exists(dropDocsFlowNotificationStatus) "
                "OR dropDocsFlowNotificationStatus=:rejected)"
            ),
            ExpressionAttributeValues={
                ":sending": "SENDING",
                ":rejected": "SEND_REJECTED",
                ":now": int(time.time()),
                ":awaiting": "AWAITING_UPLOAD",
            },
        )
    except Exception:
        return {"outcome": "DROP_DOCS_FLOW_RECONCILIATION_REQUIRED"}

    body = {
        "contactId": contact_key.resolve(contact),
        "recipientPhone": phone,
        "phoneNumberId": WABA1_SENDER,
        **whatsapp_templates.drop_docs_flow_send_fields(token),
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

    status = _outcome(answer)
    requests.update_item(
        Key={"requestId": request_key},
        UpdateExpression="SET dropDocsFlowNotificationStatus=:status, updatedAt=:now",
        ExpressionAttributeValues={":status": status, ":now": int(time.time())},
    )
    return {
        "outcome": "DROP_DOCS_FLOW_SENT" if status == "ACCEPTED" else "DROP_DOCS_FLOW_PENDING",
        "requestId": row.get("publicRequestId"),
        "sendStatus": status,
    }
