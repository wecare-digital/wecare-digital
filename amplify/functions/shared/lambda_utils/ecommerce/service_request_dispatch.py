"""Tell `wecare-service-requests` that an order exists. Create nothing, decide nothing.

Modelled on `razorpay-webhook._dispatch_download_grant_confirmation`: the webhook is a HINT. The
payload is ids only -- no amount, no phone, no kind -- and the receiver re-reads every one of them
(``PAYREF#`` -> ``PAYMENTATTEMPT#`` claim -> ``INTENT#``) before creating a request, so a forged or
replayed hint produces at most a no-op. Dispatch runs for EVERY order the webhook reconciles; the
receiver answers ``NOT_A_SERVICE_ORDER`` for the ordinary ones, which keeps the webhook free of
any service knowledge.

Fire-and-forget (`InvocationType="Event"`) and NEVER raises: a dispatch failure must not fail the
webhook (a non-2xx makes Razorpay retry the whole event), and it is recoverable two ways -- the
/orders page's self-heal and ``scripts/reconcile_service_requests.py``.

The shared Lambda role already holds ``lambda:InvokeFunction`` on ``function:wecare-*``, so this
needs no IAM change on the webhook.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The receiver, by its `live` alias, so an unpublished `$LATEST` is never what runs.
TARGET_FUNCTION = "wecare-service-requests:live"
INTERNAL_ACTION = "activateServiceRequest"


def dispatch_activation(lambda_client: Any, *, reference_id: str, payment_attempt_id: str,
                        order_id: str, request_id: str = "") -> None:
    """Send the activation hint. Never raises."""
    try:
        lambda_client.invoke(
            FunctionName=TARGET_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({
                "internalAction": INTERNAL_ACTION,
                "referenceId": str(reference_id or ""),
                "paymentAttemptId": str(payment_attempt_id or ""),
                "orderId": str(order_id or ""),
            }).encode("utf-8"),
        )
        logger.info(json.dumps({"event": "service_request_activation_dispatched",
                                "referenceId": reference_id, "orderId": order_id,
                                "requestId": request_id}))
    except Exception as error:  # noqa: BLE001
        # Type only. A ClientError message can echo request content.
        logger.warning(json.dumps({"event": "service_request_activation_dispatch_failed",
                                   "error": type(error).__name__, "referenceId": reference_id,
                                   "requestId": request_id}))
    try:
        lambda_client.invoke(
            FunctionName='wecare-whatsapp-business-api:live', InvocationType='Event',
            Payload=json.dumps({'internalAction': 'preparePaidSubmitRequest',
                                'referenceId': str(reference_id or ''),
                                'paymentAttemptId': str(payment_attempt_id or ''),
                                'orderId': str(order_id or '')}).encode('utf-8'))
    except Exception as error:
        logger.warning(json.dumps({'event': 'paid_request_flow_dispatch_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))
