"""F003 Drop Docs Flow data endpoint.

The current Flow uploads files with Meta's native DocumentPicker. This module owns
trusted INIT data only: verified customer identity and customer-owned target choices.
Final file ingestion happens from the WhatsApp Flow completion webhook.

Legacy DOC_FORM/REVIEW handlers remain read-only compatibility for old unpublished
previews. They must not create placeholder document rows or ask for a second upload.
"""
import logging
from typing import Dict

from flows.orders import fetch_orders_for_flow
from flows.common import dynamodb
from lambda_utils import contact_store, flow_sessions, shared_tables

logger = logging.getLogger(__name__)

CAPABILITY = "drop_docs"
REJECTED = "This document form session is no longer valid. Open Drop Docs again."


def _verify(flow_token: str):
    return flow_sessions.verify_session(
        dynamodb.Table(shared_tables.flow_drafts_table_name()),
        capability=CAPABILITY,
        token=flow_token,
        rejected_message=REJECTED,
    )


def _contact(phone: str) -> Dict:
    try:
        return contact_store.lookup(
            dynamodb.Table(shared_tables.contacts_table_name()), phone) or {}
    except Exception as exc:  # noqa: BLE001 - INIT fails closed to identity-free choices
        logger.warning("Drop Docs contact lookup failed: %s", type(exc).__name__)
        return {}


def _masked_phone(phone: str) -> str:
    digits = contact_store.digits(phone)
    if not digits:
        return ""
    return "+" + digits[:2] + " " + ("•" * max(0, len(digits) - 6)) + digits[-4:]


def _order_targets(phone: str) -> list:
    """Return only orders resolved through the existing customer-order lookup."""
    targets = []
    try:
        for order in fetch_orders_for_flow(phone, "")[:20]:
            order_id = str(order.get("id") or "").strip()
            title = str(order.get("title") or order_id).strip()
            if order_id:
                targets.append({
                    "id": "order:" + order_id,
                    "title": ("Order · " + title)[:72],
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drop Docs order lookup failed: %s", type(exc).__name__)
    return targets


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT -> SELECT_TARGET.

    The Flow never supplies the trusted phone/customer identity. The server-issued
    Flow session does, and the order lookup is then scoped to that phone.
    """
    try:
        session = _verify(flow_token)
    except flow_sessions.FlowSessionRejected as exc:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": str(exc),
                "phone_number": "",
                "customer_id": "",
                "targets": [{"id": "not_found", "title": REJECTED}],
            },
        }
    except flow_sessions.FlowSessionUnavailable:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": "Please try again.",
                "phone_number": "",
                "customer_id": "",
                "targets": [{"id": "not_found", "title": "Please try again"}],
            },
        }

    if session.consumed_at:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": REJECTED,
                "phone_number": "",
                "customer_id": "",
                "targets": [{"id": "not_found", "title": REJECTED}],
            },
        }

    contact = _contact(session.phone)
    customer_id = str(
        contact.get("customerUuid")
        or contact.get("customerId")
        or contact.get("id")
        or ""
    ).strip()
    targets = _order_targets(session.phone)
    targets.append({
        "id": "not_found",
        "title": "I cannot find my order or request",
    })

    return {
        "screen": "SELECT_TARGET",
        "data": {
            "phone_number": _masked_phone(session.phone),
            "customer_id": customer_id,
            "targets": targets,
        },
    }


# Compatibility for old unpublished three-screen previews. No writes or sends.
def handle_doc_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    return {
        "screen": "REVIEW",
        "data": {
            "doc_type": data.get("doc_type", ""),
            "order_id": data.get("order_id", "none"),
            "description": data.get("description", "") or "—",
        },
    }


def handle_review(data: Dict, flow_token: str, request_id: str) -> Dict:
    return {
        "screen": "CONFIRM",
        "data": {
            "doc_id": "",
            "message": "Use the current Drop Docs form to upload documents directly.",
        },
    }
