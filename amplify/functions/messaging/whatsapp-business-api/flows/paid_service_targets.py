"""Session-verified INIT for paid services with the shared SELECT_TARGET screen.

Published F004 Submit Request, F005 Request Amendment and Pickup use
SELECT_TARGET -> NOTE -> CONFIRMATION, not the retired ORDER_SELECT screens.
The session is the authorization boundary; neither a client picker nor phone
number inside an unverified token is sufficient to enumerate customer orders.
"""
from __future__ import annotations

import logging
import os
from typing import Dict

import boto3

from lambda_utils import flow_sessions, shared_tables
from lambda_utils.ecommerce import single_order_flow

logger = logging.getLogger(__name__)

# Routing token prefix -> (server-owned capability, paid service code).
PAID_FLOWS = {
    "srpaid-": ("submit_request", "SUBMIT_REQUEST"),
    "amendpaid-": ("amend_request", "REQUEST_AMENDMENT"),
    "request_pickup-": ("request_pickup", "REQUEST_PICKUP"),
}

UNAVAILABLE = "This service form is unavailable. Please request a new link."


def _unavailable(reason: str) -> Dict:
    logger.warning("paid_service_flow_init_blocked: %s", reason)
    return {"screen": "SELECT_TARGET", "data": {
        "targets": [{"id": "unavailable", "title": UNAVAILABLE}],
    }}


def handle_init(flow_token: str) -> Dict:
    """Return ONLY the paid, verified existing order in the common picker."""
    pair = next(
        (value for prefix, value in PAID_FLOWS.items()
         if str(flow_token or "").startswith(prefix)), None,
    )
    if pair is None:
        return _unavailable("unknown_token_prefix")

    capability, service_code = pair
    try:
        db = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        session = flow_sessions.verify_session(
            db.Table(shared_tables.flow_drafts_table_name()),
            capability=capability,
            token=flow_token,
            rejected_message=UNAVAILABLE,
        )
        if session.consumed_at:
            return _unavailable("session_consumed")
        binding = single_order_flow.verify_paid_session(
            session=session,
            attempts=db.Table(shared_tables.payment_attempts_table_name()),
            orders=db.Table(shared_tables.orders_table_name()),
            capability=capability,
            service_code=service_code,
            phone=session.phone,
        )
    except (flow_sessions.FlowSessionRejected,
            flow_sessions.FlowSessionUnavailable,
            single_order_flow.PaidFlowBindingError):
        return _unavailable("session_or_payment_rejected")
    except Exception as exc:
        logger.warning("paid_service_flow_init_error: %s", type(exc).__name__)
        return _unavailable("temporary_unavailable")

    order_number = binding.order_number
    return {"screen": "SELECT_TARGET", "data": {
        "targets": [{
            "id": "order:" + order_number,
            "title": "Order · " + order_number,
        }],
    }}
