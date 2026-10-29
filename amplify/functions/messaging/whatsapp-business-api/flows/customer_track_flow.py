"""Authenticated website launcher for free F006 Track Shipping.

This is deliberately not a checkout path. The website has already authenticated the customer;
this module re-verifies the trusted contact owner, records a server Flow session and sends the
approved Track template. No ProductsTable price, PaymentAttempt, invoice or order write exists.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple

import boto3

from lambda_utils import (
    canonical_flows,
    contact_key,
    contact_store,
    customer_auth,
    flow_sessions,
    shared_tables,
    whatsapp_templates,
)

CAPABILITY = "shipments"
TEMPLATE_NAME = "track_ship_flow"
WABA1_SENDER = "phone-number-id-waba1-direct-1016149501586345"


def _send_outcome(response: Any) -> str:
    if not isinstance(response, dict):
        return "SEND_UNKNOWN"
    code = int(response.get("statusCode") or 0)
    if 200 <= code < 300:
        return "ACCEPTED"
    if code in (400, 401, 403, 404, 413, 415, 422):
        return "SEND_REJECTED"
    return "SEND_UNKNOWN"


def _verified_contact(db: Any, event: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    customer_id = str(event.get("customerId") or "").strip()
    supplied_phone = contact_store.canonical_phone(event.get("customerPhone"))
    supplied_contact_id = str(event.get("contactId") or "").strip()
    if not customer_auth.is_cognito_subject(customer_id) or not supplied_phone:
        raise ValueError("verified customer required")

    contacts = db.Table(shared_tables.contacts_table_name())
    contact = (
        contacts.get_item(Key={"id": supplied_contact_id}, ConsistentRead=True).get("Item") or {}
        if supplied_contact_id else contact_store.lookup(contacts, supplied_phone) or {}
    )
    if not contact or contact.get("deletedAt") is not None or contact.get("isDeleted"):
        raise ValueError("verified contact required")
    if str(contact.get("checkoutCustomerId") or "") != customer_id:
        raise ValueError("verified contact owner mismatch")
    phone = contact_store.canonical_phone(contact.get("phone"))
    if not phone or phone != supplied_phone:
        raise ValueError("verified contact phone mismatch")
    return contact, phone


def prepare_and_send(event: Dict[str, Any], lambda_client: Any) -> Dict[str, Any]:
    """Send one free Track Flow invitation to the authenticated customer's WhatsApp."""
    published = canonical_flows.published_flow(CAPABILITY)
    if not published or str(published.get("flowId") or "") != "1804165164183485":
        return {"outcome": "TRACK_FLOW_NOT_PUBLISHED"}

    db = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    try:
        contact, phone = _verified_contact(db, event)
    except ValueError:
        return {"outcome": "VERIFIED_CUSTOMER_REQUIRED"}

    token = flow_sessions.mint_token("shipments", phone, "1")
    try:
        flow_sessions.record_session(
            db.Table(flow_sessions.table_name()),
            capability=CAPABILITY,
            token=token,
            launch_channel=flow_sessions.LAUNCH_WEBSITE,
            initiated_by="customer_track_page",
        )
    except Exception:
        return {"outcome": "TRACK_FLOW_SESSION_UNAVAILABLE"}

    body = {
        "contactId": contact_key.resolve(contact),
        "recipientPhone": phone,
        "phoneNumberId": WABA1_SENDER,
        "idempotencyKey": "track-flow:" + flow_sessions.token_digest(token),
        **whatsapp_templates.track_flow_send_fields(token),
    }
    answer = None
    try:
        response = lambda_client.invoke(
            FunctionName="wecare-outbound-whatsapp:live",
            InvocationType="RequestResponse",
            Payload=json.dumps({"body": json.dumps(body)}).encode("utf-8"),
        )
        raw = response["Payload"].read()
        answer = json.loads(raw or b"{}")
        if response.get("FunctionError"):
            answer = None
    except Exception:
        answer = None

    status = _send_outcome(answer)
    if status == "ACCEPTED":
        return {"outcome": "TRACK_FLOW_SENT"}
    if status == "SEND_REJECTED":
        return {"outcome": "TRACK_FLOW_SEND_REJECTED"}
    return {"outcome": "TRACK_FLOW_SEND_UNKNOWN"}
