"""Proof that a paid Flow belongs to one verified existing-order service payment.

The single-order request-service path deliberately creates no ServiceRequests row and no public
WD-REQ identifier. A post-payment Flow therefore binds to the durable facts that do exist:
PaymentAttemptsTable + the existing OrderTable serviceActivities append + a server-issued
FlowSession.

This module is pure table plumbing. Callers inject DynamoDB tables so completion handlers and the
post-invoice launcher use one verifier without minting any new customer identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lambda_utils import contact_store, flow_sessions
from lambda_utils.ecommerce import payment_attempt


class PaidFlowBindingError(ValueError):
    """The session cannot prove this paid existing-order service."""


@dataclass(frozen=True)
class PaidFlowBinding:
    payment_attempt_id: str
    customer_id: str
    order_id: str
    order_number: str
    service_code: str
    flow_capability: str
    attempt: dict
    order: dict


def verify_paid_session(*, session: flow_sessions.FlowSession, attempts: Any, orders: Any,
                        capability: str, service_code: str, phone: str) -> PaidFlowBinding:
    """Verify Flow session -> paid attempt -> existing order -> recorded service activity.

    Every comparison is against server-written fields. A customer-visible order number or Flow
    form field never establishes ownership by itself.
    """
    expected_capability = str(capability or "").strip()
    expected_service = str(service_code or "").strip().upper()
    if session.launch_channel != flow_sessions.LAUNCH_PAYMENT:
        raise PaidFlowBindingError("SESSION_NOT_PAYMENT")
    if session.capability != expected_capability:
        raise PaidFlowBindingError("CAPABILITY_MISMATCH")
    if session.service_code != expected_service:
        raise PaidFlowBindingError("SERVICE_CODE_MISMATCH")
    if not (session.payment_attempt_id and session.order_id and session.order_number):
        raise PaidFlowBindingError("SESSION_CONTEXT_MISSING")
    if contact_store.digits(session.phone) != contact_store.digits(phone):
        raise PaidFlowBindingError("SESSION_PHONE_MISMATCH")

    attempt = attempts.get_item(
        Key={"paymentAttemptId": session.payment_attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    if str(attempt.get("status") or "") != payment_attempt.PAYMENT_PAID:
        raise PaidFlowBindingError("PAYMENT_NOT_PAID")
    if not attempt.get("singleOrderService"):
        raise PaidFlowBindingError("NOT_SINGLE_ORDER_SERVICE")
    if str(attempt.get("selectedOrderId") or "") != session.order_id:
        raise PaidFlowBindingError("ATTEMPT_ORDER_ID_MISMATCH")
    if str(attempt.get("selectedOrderNumber") or "").upper() != session.order_number:
        raise PaidFlowBindingError("ATTEMPT_ORDER_NUMBER_MISMATCH")
    if str(attempt.get("serviceCode") or "").upper() != expected_service:
        raise PaidFlowBindingError("ATTEMPT_SERVICE_MISMATCH")
    if str(attempt.get("flowCapability") or "") != expected_capability:
        raise PaidFlowBindingError("ATTEMPT_CAPABILITY_MISMATCH")
    attempt_phone = contact_store.digits(attempt.get("customerPhone"))
    if attempt_phone and attempt_phone != contact_store.digits(phone):
        raise PaidFlowBindingError("ATTEMPT_PHONE_MISMATCH")

    order = orders.get_item(
        Key={"orderId": session.order_id}, ConsistentRead=True
    ).get("Item") or {}
    if str(order.get("orderNumber") or "").upper() != session.order_number:
        raise PaidFlowBindingError("ORDER_NUMBER_MISMATCH")
    if str(order.get("customerId") or "") != str(attempt.get("customerId") or ""):
        raise PaidFlowBindingError("ORDER_OWNER_MISMATCH")
    if session.payment_attempt_id not in [
        str(value) for value in (order.get("serviceActivityPaymentIds") or [])
    ]:
        raise PaidFlowBindingError("SERVICE_ACTIVITY_MISSING")

    matching = [
        row for row in (order.get("serviceActivities") or [])
        if isinstance(row, dict)
        and str(row.get("paymentAttemptId") or "") == session.payment_attempt_id
        and str(row.get("serviceCode") or "").upper() == expected_service
        and str(row.get("flowCapability") or "") == expected_capability
    ]
    if len(matching) != 1:
        raise PaidFlowBindingError("SERVICE_ACTIVITY_MISMATCH")

    return PaidFlowBinding(
        payment_attempt_id=session.payment_attempt_id,
        customer_id=str(attempt.get("customerId") or ""),
        order_id=session.order_id,
        order_number=session.order_number,
        service_code=expected_service,
        flow_capability=expected_capability,
        attempt=attempt,
        order=order,
    )
