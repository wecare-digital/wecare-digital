"""
Razorpay Webhook Handler Lambda Function

Purpose: Process ALL Razorpay webhook events
Webhook URL: https://wecare.digital/api/razorpay-webhook

Supported Event Categories:
- payment.* (authorized, pending, failed, captured, dispute.*, downtime.*)
- order.* (paid, notification.delivered, notification.failed)
- invoice.* (paid, partially_paid, expired)
- subscription.* (authenticated, paused, resumed, activated, pending, halted, charged, cancelled, completed, updated)
- settlement.* (processed)
- fund_account.* (validation.completed, validation.failed)
- payout.* (processed, reversed, initiated, updated, rejected, pending)
- refund.* (speed_changed, processed, failed, created)
- account.* (instantly_activated, activated_kyc_pending)
- payment_link.* (paid, partially_paid, expired, cancelled)
- token.* (service_provider.activated, service_provider.failed, service_provider.cancelled, service_provider.deactivated)
"""

import os
import json
import hmac
import hashlib
import logging
import re
import time
import boto3
from typing import Dict, Any, Optional
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.logging import get_logger
from lambda_utils import payment_status  # monotonic status, one vocabulary, dedup key
from lambda_utils.privacy import mask_phone  # a full number must never reach CloudWatch
# Module scope, matching `invoice-engine`, because `COMMERCE_KEYS_TABLE` below is resolved from
# it. Import-safe: `order_keys` creates no client and reads no secret at import.
from lambda_utils.ecommerce import order_keys

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
COMMERCE_FUNCTION = os.environ.get('COMMERCE_FUNCTION', 'wecare-commerce:live')

def _secret_from_sm(secret_id: str, key: str) -> str:
    """Fetch a key from a Secrets Manager JSON secret. Returns '' on any failure (fail-safe)."""
    try:
        import json as _json
        _sm = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        return _json.loads(_sm.get_secret_value(SecretId=secret_id)['SecretString']).get(key, '') or ''
    except Exception as e:
        logger.warning(json.dumps({'event': 'secret_fetch_failed', 'secretId': secret_id, 'errorType': type(e).__name__}))
        return ''


RAZORPAY_WEBHOOK_SECRET_ID = os.environ.get('RAZORPAY_WEBHOOK_SECRET_ID', 'wecare/razorpay-webhook')
_webhook_secret_cache = ''


def _get_webhook_secret() -> str:
    """Resolve the Razorpay webhook signing secret, Secrets Manager first.

    Fetched on first request and cached for the life of the execution
    environment — deliberately NOT at import time. These functions run with
    SnapStart (SnapStart.ApplyOn=PublishedVersions), which snapshots module
    init, so an import-time read freezes whatever value existed when the
    version was published. Because _verify_signature fails closed, a rotation
    in Secrets Manager would then silently 401 every live payment webhook until
    someone republished the function. See .kiro/steering/lambda-snapstart-deploy.md (retired 2026-10-09, af7858fa).

    Secrets Manager is the source of truth; RAZORPAY_WEBHOOK_SECRET remains a
    fallback only, so rotating the secret takes effect without a redeploy even
    if a stale env var is still attached to the function.
    """
    global _webhook_secret_cache
    if _webhook_secret_cache:
        return _webhook_secret_cache
    _webhook_secret_cache = (
        _secret_from_sm(RAZORPAY_WEBHOOK_SECRET_ID, 'webhook_secret')
        or os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
    )
    return _webhook_secret_cache


PAYMENTS_TABLE = os.environ.get('PAYMENTS_TABLE', 'stack-wecare-digital-PaymentsTable')
INVOICES_TABLE = os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable')
#: The first PaymentAttempts WRITE this handler has ever made. Declared explicitly rather than
#: relied on from a code default, because a default name is not a permission and a silent
#: `AccessDeniedException` inside a `try` on a money path is the failure this names rather than
#: hides.
PAYMENT_ATTEMPTS_TABLE = os.environ.get('PAYMENT_ATTEMPTS_TABLE',
                                        'stack-wecare-digital-PaymentAttemptsTable')
#: Already accessed via the code default; made explicit so the manifest describes the dependency
#: instead of the default hiding it.
#:
#: Resolved through `order_keys.commerce_keys_table_name()` (today
#: `stack-wecare-digital-CommerceKeys`, overridable by COMMERCE_KEYS_TABLE) and NEVER through a
#: second literal. This constant once carried its own hard-coded default that disagreed with the
#: resolver, so `reconcile` read the reservation from one table while the delivery and review
#: claims below addressed another. Two spellings of one dependency inside one handler is the
#: defect; the resolver is the single home for it.
COMMERCE_KEYS_TABLE = order_keys.commerce_keys_table_name()

#: WABA1's phone id, hoisted to a module constant so it stops appearing twice in this file. It is
#: the PRIMARY identity and the correct fallback: WABA2 is `paymentProtected` and the UI gates it
#: behind an admin authorization step, so defaulting to it server-side bypassed that check.
WABA1_PHONE_ID = 'phone-number-id-waba1-direct-1016149501586345'

MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
WEBHOOK_LOG_TABLE = os.environ.get('WEBHOOK_LOG_TABLE', 'stack-wecare-digital-RazorpayWebhookLogTable')


def _redrive_quarantined_capture(reference_id: str, payment_id: str,
                                 request_id: str) -> Dict[str, Any]:
    """Reprocess one quarantined capture from the previously signed audit receipt.

    This is not an arbitrary webhook replay endpoint. It is reachable only from the
    IAM/direct-invoke arm in handler and requires our own durable quarantine,
    payment-reference, and stored payment.captured audit evidence.

    The stored payload is only a trigger/correlation source. The normal captured-payment
    handler still performs Meta binding lookup and Razorpay provider verification before
    any paid state can be written.
    """
    from boto3.dynamodb.conditions import Key
    from lambda_utils.ecommerce import payment_attempt

    reference_id = str(reference_id or '').strip()
    payment_id = str(payment_id or '').strip()
    if not reference_id.startswith(order_keys.REFERENCE_ID_PREFIX) or not payment_id.startswith('pay_'):
        return {'status': 'REFUSED', 'reason': 'INVALID_IDENTIFIERS'}

    keys = dynamodb.Table(COMMERCE_KEYS_TABLE)
    parked = order_keys.resolve_capture_quarantine(keys, payment_id) or {}
    if not parked:
        return {'status': 'REFUSED', 'reason': 'QUARANTINE_NOT_FOUND'}
    if str(parked.get('referenceId') or '') != reference_id:
        return {'status': 'REFUSED', 'reason': 'QUARANTINE_REFERENCE_MISMATCH'}
    if str(parked.get('status') or '') == 'RESOLVED':
        return {
            'status': 'ALREADY_RESOLVED',
            'referenceId': reference_id,
            'paymentId': payment_id,
            'orderId': str(parked.get('resolvedOrderId') or ''),
        }

    reservation = order_keys.resolve_payment_reference(keys, reference_id) or {}
    attempt_id = str(reservation.get('paymentAttemptId') or '')
    if not attempt_id:
        return {'status': 'REFUSED', 'reason': 'PAYMENT_REFERENCE_NOT_FOUND'}

    audit = dynamodb.Table(WEBHOOK_LOG_TABLE)
    page = audit.query(
        IndexName='paymentId-index',
        KeyConditionExpression=Key('paymentId').eq(payment_id),
    )
    candidates = []
    for row in page.get('Items') or []:
        if str(row.get('eventType') or '') != 'payment.captured':
            continue
        try:
            event_data = json.loads(str(row.get('rawPayload') or ''))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        entity = ((event_data.get('payment') or {}).get('entity') or {})
        notes = entity.get('notes') if isinstance(entity.get('notes'), dict) else {}
        event_ref = str(notes.get('referenceId') or notes.get('reference_id') or notes.get('ref') or '')
        if (str(entity.get('id') or '') == payment_id
                and payment_status.canonical(entity.get('status')) == payment_status.CAPTURED
                and event_ref == reference_id):
            candidates.append((int(row.get('processedAt') or row.get('createdAt') or 0), event_data))

    if not candidates:
        return {'status': 'REFUSED', 'reason': 'SIGNED_CAPTURE_AUDIT_NOT_FOUND'}

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    _handle_payment_captured(candidates[0][1], request_id)

    claim = order_keys.resolve_order_for_provider_payment(keys, payment_id) or {}
    order_id = str(claim.get('orderIdRef') or '')
    if not order_id:
        return {'status': 'PENDING', 'reason': 'ORDER_NOT_MATERIALIZED'}

    attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
        Key={'paymentAttemptId': attempt_id}, ConsistentRead=True).get('Item') or {}
    if (str(attempt.get('status') or '') != payment_attempt.PAYMENT_PAID
            or str(attempt.get('providerPaymentId') or '') != payment_id):
        return {'status': 'PENDING', 'reason': 'PAID_EVIDENCE_NOT_RECORDED', 'orderId': order_id}

    invoice_id = str(reservation.get('invoiceId') or '')
    if invoice_id:
        invoice = dynamodb.Table(INVOICES_TABLE).get_item(
            Key={'invoiceId': invoice_id}, ConsistentRead=True).get('Item') or {}
        if str(invoice.get('paymentStatus') or '').lower() != 'paid':
            return {'status': 'PENDING', 'reason': 'INVOICE_NOT_PAID', 'orderId': order_id}

    order_keys.mark_capture_quarantine_resolved(
        keys, payment_id=payment_id,
        resolution='replayed stored signed payment.captured after provider-binding repair',
        actor='system:razorpay-webhook-redrive', order_id=order_id)
    return {
        'status': 'RESOLVED',
        'referenceId': reference_id,
        'paymentId': payment_id,
        'orderId': order_id,
        'orderNumber': str(claim.get('orderNumber') or ''),
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process ALL Razorpay webhook events."""
    request_id = context.aws_request_id if context else 'local'
    # Direct Lambda invokes require IAM. HTTP payloads cannot enter this recovery arm:
    # API Gateway/Function URLs always supply an envelope, and body JSON is never unwrapped.
    if event.get('internalAction') in ('recoverPaidInvoiceOrder', 'reconcileCustomerOrderLinks',
                                              'redriveQuarantinedCapture', 'sweepStaleAttempts',
                                              'reconcileReference'):
        if any(key in event for key in ('requestContext', 'rawPath', 'path', 'httpMethod',
                                        'headers', 'body', 'Records')):
            return _response(403, {'error': 'Internal invocation required'})
        if event['internalAction'] == 'redriveQuarantinedCapture':
            return _redrive_quarantined_capture(
                str(event.get('referenceId') or ''), str(event.get('paymentId') or ''), request_id)
        if event['internalAction'] == 'sweepStaleAttempts':
            return {'sweep': _sweep_stale_attempts(request_id)}
        if event['internalAction'] == 'reconcileReference':
            # Inbound's Meta payment-status webhook asks for this when Meta reports a capture,
            # so a late or lost Razorpay webhook does not leave the customer waiting for the
            # next sweep. The provider readback still decides; see `_reconcile_reference`.
            return _reconcile_reference(str(event.get('referenceId') or ''), request_id)
        from lambda_utils import shared_tables
        from lambda_utils.ecommerce import customer_order_link, paid_invoice_order
        if event['internalAction'] == 'reconcileCustomerOrderLinks':
            metrics = customer_order_link.reconcile_metrics(
                orders=dynamodb.Table(shared_tables.orders_table_name()),
                contacts=dynamodb.Table(shared_tables.contacts_table_name()),
                attempts=dynamodb.Table(PAYMENT_ATTEMPTS_TABLE))
            # Publish the sweep's health so a schedule that runs green while the backlog grows or
            # a promotion fails is visible. A small-but-OLD backlog and a large-but-fresh one are
            # different incidents, so age is emitted beside count. Best-effort: a metrics failure
            # must not fail the reconciliation it is reporting on.
            _emit_reconciliation_metrics(metrics, request_id)
            # Ride the same 5-minute schedule with the stale-attempt safety net so a dropped
            # Razorpay webhook is still recovered without a second EventBridge rule. A sweep
            # failure must never fail the link reconcile it rides on, and `_sweep_stale_attempts`
            # never raises - but guard here too so this contract is local and obvious.
            sweep = {}
            try:
                sweep = _sweep_stale_attempts(request_id)
            except Exception as sweep_error:  # noqa: BLE001 - sweep must not fail reconcile
                logger.error(json.dumps({'event': 'scheduled_sweep_error',
                                         'error': type(sweep_error).__name__,
                                         'requestId': request_id}))
            # And the deferred fulfilment updates, on the same schedule and the same terms.
            order_status_retry = {}
            try:
                order_status_retry = _retry_deferred_order_status(request_id)
            except Exception as retry_error:  # noqa: BLE001 - retry must not fail reconcile
                logger.error(json.dumps({'event': 'order_status_retry_error',
                                         'error': type(retry_error).__name__,
                                         'requestId': request_id}))
            return {'linkedOrders': metrics['promoted'], 'sweep': sweep,
                    'orderStatusRetry': order_status_retry, **metrics}
        return paid_invoice_order.materialize(
            invoices=dynamodb.Table(INVOICES_TABLE),
            items=dynamodb.Table(shared_tables.invoice_items_table_name()),
            contacts=dynamodb.Table(shared_tables.contacts_table_name()),
            attempts=dynamodb.Table(PAYMENT_ATTEMPTS_TABLE),
            keys=dynamodb.Table(COMMERCE_KEYS_TABLE),
            orders=dynamodb.Table(shared_tables.orders_table_name()),
            reference_id=str(event.get('referenceId') or ''), now=int(time.time()))
    origin = extract_origin(event)
    logger.info(json.dumps({'event': 'razorpay_webhook_received', 'requestId': request_id}))

    try:
        headers = event.get('headers', {})
        body = event.get('body', '')
        
        # API Gateway / Function URL may base64-encode the body
        import base64 as _b64
        if event.get('isBase64Encoded') and body:
            try:
                body = _b64.b64decode(body).decode('utf-8')
            except Exception as e:
                logger.warning(f'Base64 decode failed, using raw body: {e}')
        
        signature = headers.get('x-razorpay-signature') or headers.get('X-Razorpay-Signature', '')
        
        # Request shape only. This used to log bodyFirst100 and
        # signatureFirst20 on every request at INFO: the first 100 bytes of a
        # Razorpay webhook body is live order/payment/customer data, and the
        # signature prefix is HMAC output over it. Neither belongs in CloudWatch.
        logger.info(json.dumps({
            'event': 'webhook_received_shape',
            'hasBody': bool(body),
            'bodyLen': len(body) if body else 0,
            'hasSignature': bool(signature),
            'isBase64Encoded': event.get('isBase64Encoded', False),
            'requestId': request_id,
        }))

        if not _verify_signature(body, signature):
            logger.warning(json.dumps({'event': 'webhook_signature_invalid', 'requestId': request_id}))
            return _response(401, {'error': 'Invalid signature'})

        payload = json.loads(body) if isinstance(body, str) else body
        event_type = payload.get('event', '')
        event_data = payload.get('payload', {})

        # Idempotency key. Built from whichever entity the event carries, not only
        # `payload.payment.entity`.
        #
        # This previously fell back to `account_id:event:created_at` for every event
        # without a payment entity - which is refund, dispute, settlement, payout,
        # order.paid, invoice.*, payment_link.* and downtime, i.e. all of our live
        # traffic. Razorpay emits one downtime per bank and banks fail together, so
        # `created_at` is not a discriminator. Measured over 4 days to 2026-09-23:
        # 3030 events received, 1495 claimed as duplicates, and 19 keys whose
        # deliveries carried DIFFERENT bodies - at least 59 distinct events silently
        # thrown away. See lambda_utils/payment_status.dedup_key.
        razorpay_event_id = payment_status.dedup_key(payload)

        logger.info(json.dumps({'event': 'razorpay_event_received', 'eventType': event_type, 'razorpayEventId': razorpay_event_id, 'requestId': request_id}))

        # Idempotency check — skip if this event was already processed
        if _is_duplicate_event(razorpay_event_id, request_id):
            logger.info(json.dumps({'event': 'webhook_duplicate_skipped', 'razorpayEventId': razorpay_event_id, 'requestId': request_id}))
            return _response(200, {'status': 'already_processed'})

        # Log every webhook event to DynamoDB for audit trail
        _log_webhook_event(event_type, event_data, request_id, razorpay_event_id)

        # ═══════════════════════════════════════════════════════════
        # PAYMENT EVENTS
        # ═══════════════════════════════════════════════════════════
        if event_type == 'payment.captured':
            _handle_payment_captured(event_data, request_id)
        elif event_type == 'payment.authorized':
            _handle_payment_authorized(event_data, request_id)
        elif event_type == 'payment.pending':
            _handle_payment_pending(event_data, request_id)
        elif event_type == 'payment.failed':
            _handle_payment_failed(event_data, request_id)

        # Payment Dispute Events
        elif event_type == 'payment.dispute.created':
            _handle_dispute(event_type, event_data, request_id)
        elif event_type == 'payment.dispute.won':
            _handle_dispute(event_type, event_data, request_id)
        elif event_type == 'payment.dispute.lost':
            _handle_dispute(event_type, event_data, request_id)
        elif event_type == 'payment.dispute.closed':
            _handle_dispute(event_type, event_data, request_id)
        elif event_type == 'payment.dispute.under_review':
            _handle_dispute(event_type, event_data, request_id)
        elif event_type == 'payment.dispute.action_required':
            _handle_dispute(event_type, event_data, request_id)

        # Payment Downtime Events
        elif event_type == 'payment.downtime.started':
            _handle_downtime(event_type, event_data, request_id)
        elif event_type == 'payment.downtime.updated':
            _handle_downtime(event_type, event_data, request_id)
        elif event_type == 'payment.downtime.resolved':
            _handle_downtime(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # ORDER EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'order.paid':
            _handle_order_paid(event_data, request_id)
        elif event_type == 'order.notification.delivered':
            _handle_order_notification(event_type, event_data, request_id)
        elif event_type == 'order.notification.failed':
            _handle_order_notification(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # INVOICE EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'invoice.paid':
            _handle_invoice_event(event_type, event_data, request_id)
        elif event_type == 'invoice.partially_paid':
            _handle_invoice_event(event_type, event_data, request_id)
        elif event_type == 'invoice.expired':
            _handle_invoice_event(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # SUBSCRIPTION EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type.startswith('subscription.'):
            _handle_subscription_event(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # SETTLEMENT EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'settlement.processed':
            _handle_settlement(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # FUND ACCOUNT EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'fund_account.validation.completed':
            _handle_fund_account(event_type, event_data, request_id)
        elif event_type == 'fund_account.validation.failed':
            _handle_fund_account(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # PAYOUT EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type.startswith('payout.'):
            _handle_payout_event(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # REFUND EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'refund.created':
            _handle_refund(event_type, event_data, request_id)
        elif event_type == 'refund.processed':
            _handle_refund(event_type, event_data, request_id)
        elif event_type == 'refund.failed':
            _handle_refund(event_type, event_data, request_id)
        elif event_type == 'refund.speed_changed':
            _handle_refund(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # ACCOUNT EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'account.instantly_activated':
            _handle_account_event(event_type, event_data, request_id)
        elif event_type == 'account.activated_kyc_pending':
            _handle_account_event(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # PAYMENT LINK EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type == 'payment_link.paid':
            _handle_payment_link(event_type, event_data, request_id)
        elif event_type == 'payment_link.partially_paid':
            _handle_payment_link(event_type, event_data, request_id)
        elif event_type == 'payment_link.expired':
            _handle_payment_link(event_type, event_data, request_id)
        elif event_type == 'payment_link.cancelled':
            _handle_payment_link(event_type, event_data, request_id)

        # ═══════════════════════════════════════════════════════════
        # TOKEN EVENTS
        # ═══════════════════════════════════════════════════════════
        elif event_type.startswith('token.'):
            _handle_token_event(event_type, event_data, request_id)

        else:
            logger.info(json.dumps({'event': 'razorpay_event_unhandled', 'eventType': event_type, 'requestId': request_id}))

        # Close the dedup lease. LAST thing on the success path, deliberately: everything above
        # has run, so this is the point at which "already processed" becomes true. Moving it
        # earlier recreates the claim-before-work defect it exists to fix, and leaving it out
        # entirely means every event is reprocessed once the lease lapses.
        _complete_event(razorpay_event_id, request_id)

        return _response(200, {'status': 'ok', 'event': event_type})

    except json.JSONDecodeError as e:
        logger.error(json.dumps({'event': 'webhook_parse_error', 'error': str(e), 'requestId': request_id}))
        return _response(400, {'error': 'Invalid JSON'})
    except Exception as e:
        # The lease is deliberately NOT completed here. Letting it lapse is what allows Razorpay's
        # retry to be processed instead of dismissed as a duplicate, which is the entire fix.
        logger.error(json.dumps({'event': 'webhook_error', 'error': str(e), 'requestId': request_id}))
        return _response(500, {'error': 'Internal server error'})


# ═══════════════════════════════════════════════════════════════════
# SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════════

def _verify_signature(body: str, signature: str) -> bool:
    secret = _get_webhook_secret()
    if not secret:
        logger.error(f'Razorpay webhook secret unavailable from {RAZORPAY_WEBHOOK_SECRET_ID} '
                     'or RAZORPAY_WEBHOOK_SECRET — rejecting webhook (fail closed)')
        return False
    if not signature:
        logger.warning('No signature header received')
        return False
    try:
        body_bytes = body.encode('utf-8') if isinstance(body, str) else body
        expected = hmac.new(
            secret.encode('utf-8'),
            body_bytes,
            hashlib.sha256
        ).hexdigest()
        match = hmac.compare_digest(expected, signature)
        if not match:
            # Deliberately records only that a mismatch happened and how big the
            # body was. The previous version logged the first 20 chars of both
            # the expected and received HMAC plus len(secret); expected-digest
            # material and the secret's length are attacker-useful and do not
            # help debugging.
            logger.warning(json.dumps({
                'event': 'signature_mismatch',
                'bodyLen': len(body_bytes),
            }))
        return match
    except Exception as e:
        logger.error(f"Signature verification error: {str(e)}")
        return False


# ═══════════════════════════════════════════════════════════════════
# WEBHOOK AUDIT LOG
# ═══════════════════════════════════════════════════════════════════

def _log_webhook_event(event_type: str, event_data: Dict, request_id: str, razorpay_event_id: str = '') -> None:
    """Log every webhook event to DynamoDB for audit trail with idempotency key."""
    import time, uuid
    try:
        table = dynamodb.Table(WEBHOOK_LOG_TABLE)
        now = int(time.time())
        # Whichever entity the event carries, not only `payload.payment.entity`. With the
        # old payment-only lookup, all 607 live downtime rows stored `amount: 0` and a
        # `status` inferred from the event-type suffix, and carried no entity id at all -
        # so this table, which exists to be the reconciliation record, could not identify
        # which downtime any row referred to.
        _container, _entity = payment_status.extract_entity(event_data)
        try:
            _amount = payment_status.paise(_entity.get('amount')) if \
                _entity.get('amount') is not None else 0
        except ValueError:
            _amount = 0
        item = {
            'id': str(uuid.uuid4()),
            'eventType': event_type or 'unknown',
            'orderId': _entity.get('order_id', ''),
            # Integer paise. Named plainly because this table previously held a bare
            # `amount` whose unit depended on which handler wrote the row.
            'amount': _amount,
            'amountPaise': _amount,
            'status': _entity.get('status', event_type.split('.')[-1] if '.' in event_type else ''),
            'entityKey': _container,
            'entityId': _entity.get('id', ''),
            'rawPayload': json.dumps(event_data, default=str)[:4000],  # Truncate large payloads
            'processedAt': now,
            'createdAt': now,
            'expiresAt': now + 180 * 24 * 60 * 60,  # TTL: 180 days
        }
        # paymentId is the HASH key of paymentId-index. DynamoDB rejects an empty
        # string for an index key attribute, which previously made PutItem fail for
        # every event without a payment entity (e.g. payment.downtime) and silently
        # dropped those rows from the audit trail. Omit the attribute instead so the
        # row still persists and is simply absent from that sparse index.
        #
        # Only a genuine payment id goes in: a downtime id is not a payment id, and
        # putting one here would make that index return non-payments.
        _payment_id = (_entity.get('id') or '') if _container == 'payment' else \
            (_entity.get('payment_id') or '')
        if _payment_id:
            item['paymentId'] = _payment_id
        if razorpay_event_id:
            item['razorpayEventId'] = razorpay_event_id
        table.put_item(Item=item)
    except Exception as e:
        # Don't fail the webhook if logging fails
        logger.warning(json.dumps({'event': 'webhook_log_failed', 'error': str(e), 'requestId': request_id}))


def _is_duplicate_event(razorpay_event_id: str, request_id: str) -> bool:
    """Idempotency via the shared WebhookDedup table, as a LEASE rather than a permanent claim.

    Returns True if this event was already processed (caller should skip).

    It used to call `claim_event`, which claims permanently. That has an invisible and expensive
    failure mode on a payment path:

        claim -> handler raises -> claim remains -> Razorpay retries -> "duplicate" -> DROPPED

    The claim was taken before the work and never released, so an exception anywhere below made
    Razorpay's retry look like a duplicate. On `payment.captured` that silently discards a captured
    payment, and throws away the exact mechanism that exists to recover from it.

    `claim_event_with_lease` releases the claim by lapsing if `_complete_event` is never reached,
    so a crashed handler gets retried and a successful one is closed permanently. Legacy rows carry
    no lease and stay non-reclaimable, so the 271 entries already in the table are unaffected.

    Still fails open, and that is safer than it used to be: order creation is now guarded by its own
    conditional markers in `lambda_utils/ecommerce/order_keys`, so processing an event twice
    converges on one order rather than making two."""
    if not razorpay_event_id:
        return False
    try:
        from lambda_utils.webhook_dedup import claim_event_with_lease
        # Returns True when newly claimed (process); duplicate = not claimed.
        return not claim_event_with_lease(razorpay_event_id, source='razorpay')
    except Exception as e:
        logger.warning(json.dumps({'event': 'idempotency_check_failed', 'error': str(e), 'requestId': request_id}))
        return False  # Fail open on check errors — better to process twice than miss


def _complete_event(razorpay_event_id: str, request_id: str) -> None:
    """Close the lease. MUST be the last thing a successful path does.

    Calling it earlier turns the lease back into a claim-before-work-and-never-release, which is
    the defect it replaced. Never raises: a failure here leaves the lease to lapse, costing one
    reprocess, and a reprocess is safe."""
    if not razorpay_event_id:
        return
    try:
        from lambda_utils.webhook_dedup import complete_event
        complete_event(razorpay_event_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'dedup_complete_failed',
                                   'error': type(e).__name__, 'requestId': request_id}))


def _create_order_for_captured_payment(payment: Dict, reference_id: str,
                                       request_id: str) -> Dict[str, Any]:
    """Turn a verified capture into exactly one order. Returns the outcome as a dict.

    This is the step the payment path never had. Measured across the tree, nothing here created a
    commerce order - the path produced payment records, invoice state, GST invoices and
    notifications. So this is an addition, and `OrderTable` held zero rows when it was written.

    Two things it deliberately does NOT do. It does not trust `payment`: the amount, currency and
    status all come back from Razorpay's API through `razorpay_verify`, because the webhook signing
    secret is in this repository's public git history and a signature therefore proves only that
    somebody read the history. And it does not perform the downstream side effects - transaction
    record, receipt, confirmation - which are separately guarded so that a failure in the last one
    does not re-run the first.

    Never raises. A failure to create the order must not fail the webhook, because a non-2xx makes
    Razorpay retry the whole event and the lease above already handles recovery.
    """
    try:
        from lambda_utils.ecommerce import (order_channel, order_creation, order_keys,
                                            wa_payment_request, website_checkout)
        from lambda_utils.identity import customer_uuid
        from lambda_utils.integrations import meta_payment_binding, razorpay_verify

        payment_id = str(payment.get('id') or '')
        order_id = str(payment.get('order_id') or '')
        if not payment_id and not order_id:
            return {'outcome': order_creation.NO_PROVIDER_ID, 'hasOrder': False}

        table = dynamodb.Table(order_keys.commerce_keys_table_name())

        # `_load_attempt` runs INSIDE `reconcile_payment`, so the row it reads is not otherwise
        # visible out here - and the channel is needed again further down, for the invoice. Noted
        # on the way past rather than re-read: it is the same row, and a second GetItem on a money
        # path buys nothing. It is deliberately NOT added to the narrowed dict `_load_attempt`
        # returns: `reconcile_payment` is a pure module that decides money questions and has no
        # business with attribution, so a key it never reads would only suggest it did. Empty
        # until the row is read, which is why the reader below goes through
        # `order_channel.canonical` rather than trusting this dict.
        attribution: Dict[str, Any] = {}

        def _load_attempt(ref: str):
            row = order_keys.resolve_payment_reference(table, ref)
            if not row or not row.get('paymentAttemptId'):
                return None
            # The attempt's authoritative amount and currency live on the PAYREF# row, written when
            # the payment request was created. Reading them from the webhook instead would make
            # the comparison compare the event against itself.
            attribution['channel'] = row.get('channel', '')
            # The public customer id, on the same footing and for the same reasons as the
            # channel one line above: read off OUR row and never from the event, noted on the
            # way past rather than re-read, and kept OUT of the narrowed dict below. An id the
            # Razorpay `notes` could set would be an id a customer could forge onto someone
            # else's tax invoice.
            attribution['customerUuid'] = row.get('customerUuid', '')
            # Carried on the same footing as the two above, and for the paid-state write and the
            # invoice-delivery gate below: read off OUR row, noted on the way past, and kept OUT
            # of the narrowed dict because `reconcile_payment` does not read them and a key it
            # never reads would only suggest it did.
            attribution['checkoutMode'] = row.get('checkoutMode', '')
            attribution['paymentAttemptId'] = row.get('paymentAttemptId', '')
            attribution['invoiceId'] = row.get('invoiceId', '')

            # ── NATIVE WHATSAPP LEG ONLY: bind the gateway order, from META ──
            #
            # On the website leg WE create the Razorpay order and store its id before the browser
            # sees checkout options, so `verifier_for_event` has a binding to key on. On this leg
            # Meta creates it when the customer taps Pay, so an unbound native attempt fails
            # closed with PROVIDER_UNAVAILABLE - correct behaviour, wrong outcome.
            #
            # The binding comes from an authenticated Meta lookup and NEVER from this event body.
            # The webhook signing secret is in this repository's git history, so a signature
            # proves only that somebody read the history; accepting the event's own `order_id`
            # would let a forged event name any Razorpay order and bind it to any reference.
            #
            # Three gates, each deliberate:
            #   * on `checkoutMode`, so the website leg cannot acquire a Meta lookup. This is the
            #     ONE place the field is read on this leg, and it selects a binding SOURCE - not
            #     a finalisation path.
            #   * on the binding being ABSENT, so a redelivery after a successful bind makes no
            #     Graph call at all and the external-call count does not grow with redeliveries.
            #   * inside `_load_attempt`, so `verify_payment` and `load_attempt` both see the
            #     same bound row.
            if ((row.get('checkoutMode') in wa_payment_request.NATIVE_CHECKOUT_MODES
                    or row.get('checkoutMode') == 'AWS_NATIVE')
                    and not row.get('providerOrderId')
                    and not row.get('providerPaymentId')):
                meta_payment_binding.bind_attempt(
                    table, reference_id=ref,
                    phone_number_id=str(row.get('phoneId') or ''),
                    config_name=str(row.get('configurationName') or ''),
                    payment_attempt_id=str(row.get('paymentAttemptId') or ''),
                    invoice_id=str(row.get('invoiceId') or ''),
                    amount_paise=row.get('amountPaise'),
                    now=int(time.time()))
                # Re-read rather than patching the dict in memory, so the value `verify_payment`
                # and `load_attempt` both see is the value that is actually STORED.
                # `resolve_payment_reference` reads consistently, so this is the one place a
                # strongly consistent read matters.
                row = order_keys.resolve_payment_reference(table, ref) or row

            return {
                'paymentAttemptId': row['paymentAttemptId'],
                'customerId': row.get('customerId', ''),
                'amountPaise': row.get('amountPaise'),
                'providerPaymentId': row.get('providerPaymentId', ''),
                'providerOrderId': row.get('providerOrderId', ''),
                'currency': row.get('currency', ''),
            }

        outcome = order_creation.reconcile_payment(
            table=table,
            reference_id=reference_id,
            verify_payment=razorpay_verify.verifier_for_event(
                payment_id=payment_id, order_id=order_id, load_attempt=_load_attempt),
            load_attempt=_load_attempt,
        )

        logger.info(json.dumps({
            'event': 'order_reconciliation_result',
            'outcome': outcome.outcome,
            'hasOrder': outcome.has_order,
            'needsHuman': outcome.needs_human,
            'orderNumber': outcome.order_number or None,
            'referenceId': reference_id,
            'requestId': request_id,
        }))

        # ── write PAID STATE onto a native attempt ──────────────────────────────────────────
        #
        # `reconcile_payment` SYNTHESISES the paid status for its eligibility check -
        # `{**attempt, 'status': PAYMENT_PAID}` - and writes nothing back. It has no attempts
        # table and no writer for one. The website leg advances the attempt twice outside
        # `reconcile_payment`; the native leg did neither, so a paid native attempt stayed at
        # `PAYMENT_READINESS_CHECKED` - a member of `IN_FLIGHT_STATES` - permanently. An attempt
        # that reads as in-flight is the state most likely to produce a second payment request,
        # and no `verifiedCapturedPaise` existed anywhere durable on this leg.
        #
        # THE GATE IS ON THE OUTCOME **AND** ON EVIDENCE BEING PRESENT, and that second half is
        # not belt-and-braces. `ReconciliationOutcome.verified_captured_paise` defaults to 0 and
        # is omitted on THREE paths that report `has_order`: the idempotent short-circuit (which
        # answers before the provider is contacted), and both `_finish_numbering` returns. So
        # gating on `has_order` alone would call `record_paid` with 0 on every ordinary
        # redelivery, its nested condition would fail against the stored real amount, and we
        # would log an ERROR saying two verified amounts disagree when nothing is wrong. Worse:
        # if the FIRST processed delivery landed on a `_finish_numbering` path, zero would become
        # the authoritative evidence and the later correct amount would then be refused by the
        # same condition.
        #
        # So: a real readback writes evidence; an absent readback is a clean idempotent INFO
        # no-op, never an evidence conflict.
        native_invoice = (attribution.get('checkoutMode')
                          == wa_payment_request.WA_NATIVE_CHECKOUT_MODE)
        # Website Standard Checkout is finalized here too. Its order row is normally written by
        # the browser verify/status path (`checkout._finalize` -> `finalization.accept_paid`), but
        # a capture whose browser never returned (closed tab, lost network) would otherwise leave
        # a numbered order identity with no Order row until a human intervened. `accept_paid`'s
        # `put_item` is conditional with an explicit field-agreement check, and `checkout._finalize`
        # is documented as safe to re-enter from both verify and status for exactly this reason, so
        # running it again from the webhook converges on the SAME single order rather than writing a
        # second one. `website_checkout.verify_callback` only VERIFIES - it writes no order itself -
        # so there is no conflicting writer; the sole writer of the order record is `accept_paid`,
        # reached from either path through the same idempotent conditional put.
        native_cart = (attribution.get('checkoutMode')
                       in (wa_payment_request.WA_NATIVE_CART_CHECKOUT_MODE, 'AWS_NATIVE',
                           website_checkout.CHECKOUT_MODE_WEBSITE))
        if native_invoice and outcome.has_order:
            if (outcome.outcome == order_creation.ORDER_CREATED
                    and outcome.verified_captured_paise > 0
                    and outcome.provider_payment_id):
                from botocore.exceptions import ClientError
                from lambda_utils.ecommerce import finalization
                try:
                    finalization.record_paid(
                        # A WRITE-only handle, created here and never used to read. The read
                        # path above still makes exactly one table handle - the commerce-keys
                        # one - so no attempts-table READ is added to the money path.
                        dynamodb.Table(PAYMENT_ATTEMPTS_TABLE),
                        # Both fields `record_paid` conditions on: its ConditionExpression is
                        # `attribute_exists(paymentAttemptId) AND referenceId = :ref AND (...)`,
                        # and `:ref` is taken from the dict. A KeyError on either is impossible
                        # because `_load_attempt` already refused a row without an attempt id.
                        {'paymentAttemptId': attribution.get('paymentAttemptId', ''),
                         'referenceId': reference_id},
                        # The PROVIDER's figure, never the order total. Passing the expectation
                        # in place of the evidence would make the stored evidence unfalsifiable.
                        outcome.provider_payment_id,
                        outcome.verified_captured_paise)
                    logger.info(json.dumps({
                        'event': 'native_attempt_paid_recorded',
                        'referenceId': reference_id,
                        'verifiedCapturedPaise': outcome.verified_captured_paise,
                        'requestId': request_id}))
                except ClientError as exc:
                    if not order_keys.is_conditional_failure(exc):
                        raise
                    # TWO DIFFERENT verified amounts, or two different provider payment ids, for
                    # one attempt. That is a reconciliation incident and a human has to look at
                    # it. The order already exists and is numbered, so this does not undo
                    # anything: the attempt's paid state is the RECORD of the order, not its
                    # cause.
                    logger.error(json.dumps({
                        'event': 'native_attempt_paid_evidence_conflict',
                        'referenceId': reference_id,
                        'verifiedCapturedPaise': outcome.verified_captured_paise,
                        'requestId': request_id}))
            else:
                # A redelivery, or a resumed numbering run. This outcome carries no provider
                # readback because `reconcile_payment` answered before contacting the provider;
                # the evidence was written by the delivery that DID contact it. Nothing to
                # record, and explicitly NOT a conflict.
                logger.info(json.dumps({
                    'event': 'native_attempt_paid_evidence_already_recorded',
                    'outcome': outcome.outcome,
                    'referenceId': reference_id,
                    'requestId': request_id}))

        # Product/cart native checkout carries the frozen cart snapshot on the PaymentAttempt.
        # Unlike the invoice-native leg above, it can therefore use the same internal order
        # finalizer as website checkout after Meta/Razorpay have supplied authoritative capture
        # evidence. No finalization is attempted on idempotent outcomes that carry no fresh
        # provider readback; the first successful delivery already wrote the order.
        #
        # RESUMABLE. A delivery that won the claim but failed inside `accept_paid` leaves a
        # numbered order identity with no order row; every later delivery or redrive then answers
        # ORDER_ALREADY_EXISTS before contacting the provider. That later pass resumes ONLY from
        # the evidence the verified delivery already recorded on the attempt (`record_paid`), and
        # `accept_paid` is idempotent on it (conditional order put + association check), so a
        # retry converges on the same single order instead of skipping finalization forever.
        if native_cart and outcome.has_order:
            from lambda_utils import shared_tables
            from lambda_utils.ecommerce import finalization
            attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
                Key={'paymentAttemptId': outcome.payment_attempt_id},
                ConsistentRead=True).get('Item') or {}
            if not attempt:
                raise RuntimeError('native cart payment attempt missing')
            evidence = None
            if (outcome.outcome == order_creation.ORDER_CREATED
                    and outcome.verified_captured_paise > 0
                    and outcome.provider_payment_id):
                evidence = (outcome.provider_payment_id, outcome.verified_captured_paise)
            elif attempt.get('finalizationStage') != 'ORDER_FINALIZED':
                stored_id = str(attempt.get('verifiedProviderPaymentId') or '')
                stored_paise = finalization.integer_paise(
                    attempt.get(finalization.VERIFIED_CAPTURED_PAISE_ATTR))
                if stored_id and stored_paise:
                    evidence = (stored_id, stored_paise)
                else:
                    # Money moved and no verified evidence is on the attempt. Never invent it:
                    # a human redrives this capture through a fresh provider readback.
                    logger.error(json.dumps({
                        'event': 'native_cart_finalization_evidence_missing',
                        'alert': 'PAID_BUT_NO_ORDER_RECORD',
                        'outcome': outcome.outcome,
                        'referenceId': reference_id,
                        'requestId': request_id,
                    }))
            if evidence:
                finalization.accept_paid(
                    attempts=dynamodb.Table(PAYMENT_ATTEMPTS_TABLE),
                    orders=dynamodb.Table(shared_tables.orders_table_name()),
                    keys=table,
                    attempt=attempt,
                    outcome={
                        **outcome.as_dict(),
                        'providerPaymentId': evidence[0],
                    },
                    verified_captured_paise=evidence[1],
                )
                logger.info(json.dumps({
                    'event': 'native_cart_order_finalized',
                    'outcome': outcome.outcome,
                    'referenceId': reference_id,
                    'orderNumber': outcome.order_number or None,
                    'requestId': request_id,
                }))

        if outcome.has_order:
            # Phase O-1: a hint only (ids, fire-and-forget, never raises); the receiver re-reads
            # every link and no-ops for an ordinary order.
            from lambda_utils.ecommerce import service_request_dispatch
            service_request_dispatch.dispatch_activation(
                lambda_client, reference_id=reference_id,
                payment_attempt_id=outcome.payment_attempt_id, order_id=outcome.order_id,
                request_id=request_id)

        if outcome.needs_human:
            # Money moved and no order followed. The alarm condition: recoverable only by staff,
            # and the customer must never be asked to pay again.
            logger.error(json.dumps({
                'event': 'order_reconciliation_needs_attention',
                'alert': 'PAID_BUT_NO_ORDER',
                'outcome': outcome.outcome,
                'reason': outcome.reason,
                'referenceId': reference_id,
                'requestId': request_id,
            }))
        # `channel` is added HERE and not inside `ReconciliationOutcome`: that class is a pure
        # module's published contract with its key set pinned by equality tests, and attribution is
        # not part of what a reconciliation decides. `order_channel.canonical` is total, so a row
        # written before the channel existed - which is every row today - reports `website`.
        # `customerUuid` joins it, and unlike the channel it has NO canonical default: an order
        # whose `PAYREF#` row carries none reports `''`, which suppresses the Customer ID row at
        # every render site. `customer_uuid.from_contact` is reused here as the validator - it
        # re-checks the stored value and never raises - so a junk or uuid7 value cannot reach a
        # printed invoice even if some future writer put one on the row.
        return {
            **outcome.as_dict(),
            'channel': order_channel.canonical(attribution.get('channel')),
            'customerUuid': customer_uuid.from_contact(attribution),
            # MECHANICS, beside the channel's attribution. Read off the `PAYREF#` row, never from
            # the event. Absent on the legacy settlement path, where there is no `PAYREF#` row at
            # all - which closes the invoice-delivery gate below, the fail-closed direction.
            'checkoutMode': str(attribution.get('checkoutMode') or ''),
            'invoiceId': str(attribution.get('invoiceId') or ''),
        }

    except Exception as e:  # noqa: BLE001
        # Type only, and never re-raised: a non-2xx makes Razorpay retry the whole event, and the
        # lease already provides recovery without the noise.
        logger.error(json.dumps({
            'event': 'order_reconciliation_error',
            'error': type(e).__name__,
            'referenceId': reference_id,
            'requestId': request_id,
        }))
        from lambda_utils.ecommerce import order_creation
        return {'outcome': order_creation.RECONCILIATION_ERROR, 'hasOrder': False}




# ═══════════════════════════════════════════════════════════════════
# SECURE FILE DOWNLOAD GRANTS
# ═══════════════════════════════════════════════════════════════════

def _dispatch_download_grant_confirmation(order_id: str, request_id: str) -> None:
    """Tell `secure-files` that an order may have been paid. Grant nothing.

    This function used to flip the grant to `paid` itself, treating a valid webhook
    signature as proof of payment. It no longer writes to the grants table at all, and
    that is the entire point.

    The webhook secret used to verify these callbacks is present in this repository's
    public git history. While a signature was proof of payment, anyone who read that
    history could forge a `payment.captured` event and mint a free download. Rotating
    the secret would close that; taking the secret out of the decision closes it
    permanently, and does not depend on a rotation ever happening.

    So the webhook is demoted to a hint. All it may assert is "order X changed" - it
    cannot name a file, a recipient, or an amount, because those are read from the grant
    this system wrote at order-creation time. Whether money actually moved is then
    answered by Razorpay's own API inside `secure-files._confirm_with_razorpay`, which
    is now the only writer of `paid` anywhere in the system.

    A forged event therefore produces exactly one outcome: an API call to Razorpay that
    reports no captured payment, and no grant.

    Fire-and-forget on purpose. Razorpay retries on a non-2xx, and this webhook has
    other work to do; a dispatch failure is recoverable by
    `scripts/reconcile_file_deliveries.py`, which re-runs the same confirmation path.
    """
    try:
        lambda_client.invoke(
            FunctionName='wecare-secure-files:live',
            InvocationType='Event',
            Payload=json.dumps({
                'internalAction': 'confirmAndDeliver',
                'orderId': order_id,
            }).encode('utf-8'),
        )
        logger.info(json.dumps({
            'event': 'download_grant_confirmation_dispatched', 'orderId': order_id,
            'requestId': request_id}))
    except Exception as exc:  # noqa: BLE001
        # Type only. A ClientError message can echo request content.
        logger.error(json.dumps({
            'event': 'download_grant_confirmation_dispatch_failed', 'orderId': order_id,
            'error': type(exc).__name__, 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# PAYMENT EVENT HANDLERS
# ═══════════════════════════════════════════════════════════════════

def _verified_legacy_invoice(reference_id: str, payment: Dict, request_id: str) -> str:
    """The claimed invoice id when this reference is a genuine, provider-verified, BOUND legacy
    invoice; an empty string otherwise.

    Legacy invoice-only payments predate the commerce checkout: they have an invoice row keyed by
    referenceId but no PaymentAttempt (so reconcile returns UNKNOWN_REFERENCE). The brief forbids
    treating that absence as proof of legacy origin - a forged event naming an unknown reference
    would then mint a free invoice-paid. So identification is by POSITIVE signals that, together,
    establish that THIS payment settles THIS invoice:

      1. An existing InvoicesTable row for this referenceId (exactly one; an ambiguous match is
         refused rather than guessed).
      2. An authoritative provider readback (`razorpay_verify.payment_capture_details`, never the
         event body) that the named payment is CAPTURED, in INR, for the invoice total to the
         paise.
      3. R2 binding: the invoice row must itself carry a stored provider identifier and the
         provider-verified capture's own provider order id must match it. The binding fields
         consulted on the invoice row, in order of preference, are:
             providerOrderId  (the Razorpay order the invoice was raised against)
             order_id         (snake_case variant written by older invoice rows)
             providerPaymentId (a specific Razorpay payment id bound to the invoice)
         A payment is bound when its provider order id equals the invoice's providerOrderId/
         order_id, OR when the verified payment id equals the invoice's providerPaymentId. If the
         invoice carries NO provider binding at all, amount equality cannot prove this capture is
         for this invoice - so we refuse (return False -> quarantine) rather than settle.
      4. R2 one-time claim: a conditional PROVIDERPAYMENT#<payment_id> marker is claimed BEFORE any
         invoice write. One provider payment can settle at most one invoice (and, sharing the claim
         namespace with the commerce path, at most one thing overall). A replay carrying the same
         payment_id under a different referenceId finds the claim already held and settles nothing.

    Only when all of these hold is the invoice-paid / post-payment work allowed to run. Any lookup
    or verification failure returns '' (falsy), which routes the capture into quarantine rather
    than guessing. Never raises.

    Returns the claimed invoice id (truthy) on success so the caller can reconcile the one-time
    PROVIDERPAYMENT#<payment_id> claim with the ACTUAL row settlement: the claim is taken here,
    before `_mark_invoice_paid_by_reference` runs (the two-query design), so if that later settle
    no-ops the caller releases this claim rather than stranding the payment. See the asymmetry note
    in `_handle_payment_captured`.
    """
    if not reference_id:
        return ''
    try:
        from lambda_utils.ecommerce import order_keys
        from lambda_utils.ecommerce.money import positive_paise
        from lambda_utils.integrations import razorpay_verify

        # 1) Positive signal: an invoice row must already exist for this reference. More than one
        #    is ambiguous - refuse rather than pick.
        inv_table = dynamodb.Table(INVOICES_TABLE)
        resp = inv_table.query(
            IndexName='referenceId-index',
            KeyConditionExpression='referenceId = :ref',
            ExpressionAttributeValues={':ref': reference_id},
            Limit=2,
        )
        items = resp.get('Items', [])
        if not items:
            # No invoice, no attempt: absence is not evidence. Let the caller quarantine it.
            return ''
        if len(items) > 1:
            logger.error(json.dumps({
                'event': 'legacy_invoice_reference_ambiguous',
                'referenceId': reference_id,
                'stage': 'legacy_verify',
                'requestId': request_id,
            }))
            return ''
        invoice = items[0]

        # The invoice's authoritative total, in integer paise. If it is unparseable OR carries
        # sub-paise noise we cannot compare exactly, so we refuse rather than guess: paise() would
        # otherwise truncate (599.999 -> 59999) and match against a rounded-down expectation.
        try:
            total_minor = Decimal(str(invoice.get('total', 0))) * 100
            if total_minor != total_minor.to_integral_value():
                return ''
            expected_paise = payment_status.paise(total_minor)
        except (ValueError, ArithmeticError, TypeError):
            return ''
        if expected_paise <= 0:
            return ''

        # 3a) R2 binding: the invoice MUST carry a stored provider identifier. Without one, amount
        #     equality alone cannot establish that this capture is for this invoice - refuse.
        invoice_order_id = str(invoice.get('providerOrderId')
                               or invoice.get('order_id') or '')
        invoice_payment_id = str(invoice.get('providerPaymentId') or '')
        if not invoice_order_id and not invoice_payment_id:
            logger.error(json.dumps({
                'event': 'legacy_invoice_no_provider_binding',
                'referenceId': reference_id,
                'stage': 'legacy_verify',
                'requestId': request_id,
            }))
            return ''

        # 2) Authoritative provider verification. The event body is never trusted: we ask Razorpay
        #    directly for the named payment id and require a captured INR amount that equals the
        #    invoice total to the paise, and we read the capture's provider order id for binding.
        payment_id = str(payment.get('id') or '')
        if not payment_id:
            return ''
        (captured, provider_paise, provider_currency,
         provider_order_id) = razorpay_verify.payment_capture_details(payment_id)
        if not captured:
            return ''
        if str(provider_currency or '') != 'INR':
            return ''
        try:
            provider_paise = positive_paise(provider_paise)
        except ValueError:
            return ''
        if provider_paise != expected_paise:
            # Money moved but not for this invoice's amount. Do not mark it paid; a human decides.
            logger.error(json.dumps({
                'event': 'legacy_invoice_amount_mismatch',
                'referenceId': reference_id,
                'stage': 'legacy_verify',
                'requestId': request_id,
            }))
            return ''

        # 3b) R2 binding check: the provider-verified capture must belong to the invoice's bound
        #     provider order, or be the invoice's bound payment. The event body is never consulted
        #     here - provider_order_id came from the authoritative readback above.
        bound = False
        if invoice_order_id and provider_order_id and provider_order_id == invoice_order_id:
            bound = True
        if invoice_payment_id and payment_id == invoice_payment_id:
            bound = True
        if not bound:
            logger.error(json.dumps({
                'event': 'legacy_invoice_binding_mismatch',
                'referenceId': reference_id,
                'stage': 'legacy_verify',
                'requestId': request_id,
            }))
            return ''

        # 4) R2 one-time claim: before any invoice write, claim PROVIDERPAYMENT#<payment_id>. If it
        #    is already held (by a prior settlement or by the commerce path), this payment has
        #    settled - or will settle - something else: refuse and let the caller quarantine. This
        #    is what blocks a replay of the same payment_id under a different referenceId.
        keys_table = dynamodb.Table(order_keys.commerce_keys_table_name())
        invoice_id = str(invoice.get('invoiceId') or '')
        won, claimed_invoice = order_keys.claim_legacy_invoice_payment(
            keys_table, payment_id=payment_id,
            invoice_id=invoice_id,
            reference_id=reference_id,
            extra={'source': 'razorpay-webhook-legacy'})
        if not won:
            logger.error(json.dumps({
                'event': 'legacy_invoice_payment_already_claimed',
                'referenceId': reference_id,
                'stage': 'legacy_verify',
                'claimedInvoiceId': claimed_invoice or None,
                'requestId': request_id,
            }))
            return ''

        logger.info(json.dumps({
            'event': 'legacy_invoice_verified',
            'referenceId': reference_id,
            'stage': 'legacy_verify',
            'requestId': request_id,
        }))
        # Return the claimed invoice id so the caller can release this one-time claim if the
        # subsequent settle no-ops (the stranded-claim window the review flagged).
        return invoice_id
    except Exception as exc:  # noqa: BLE001
        # Type only. Provider error bodies and ClientError messages can echo request content.
        logger.warning(json.dumps({
            'event': 'legacy_invoice_verify_failed',
            'referenceId': reference_id,
            'stage': 'legacy_verify',
            'error': type(exc).__name__,
            'requestId': request_id,
        }))
        return ''


def _release_legacy_invoice_payment_claim(payment_id: str, invoice_id: str,
                                          request_id: str) -> None:
    """Release a legacy one-time PROVIDERPAYMENT#<payment_id> claim that settled no invoice row.

    Reconciles the stranded-claim window (review Issue 1): the claim is taken inside
    `_verified_legacy_invoice` before `_mark_invoice_paid_by_reference` runs, so a settle that then
    no-ops would otherwise burn the claim with no settled row behind it. Called ONLY on the legacy
    path and ONLY after that settle reported not-settled, so no invoice is paid for this payment
    anywhere when this runs.

    The release is a CONDITIONAL delete bound to the row still being THIS payment's legacy claim
    for THIS invoice (see `order_keys.release_legacy_invoice_payment_claim`), so it can never remove
    a commerce `PROVIDER_PAYMENT_CLAIM` or a claim another worker already re-bound. After release a
    legitimate Razorpay redelivery re-claims and re-attempts; if the ambiguity/vanish persists it
    simply quarantines again (idempotent). Never raises - a release failure is logged by type and
    the capture is still quarantined by the caller, so the claim is at worst left in place (the old
    behaviour) rather than making anything worse.
    """
    if not payment_id or not invoice_id:
        return
    try:
        from lambda_utils.ecommerce import order_keys
        keys_table = dynamodb.Table(order_keys.commerce_keys_table_name())
        released = order_keys.release_legacy_invoice_payment_claim(
            keys_table, payment_id=payment_id, invoice_id=invoice_id)
        logger.error(json.dumps({
            'event': 'legacy_invoice_claim_released_unsettled'
                     if released else 'legacy_invoice_claim_release_noop',
            'stage': 'legacy_verify',
            'paymentId': payment_id,
            'requestId': request_id,
        }))
    except Exception as exc:  # noqa: BLE001
        # Type only. A ClientError message can echo request content. A failed release leaves the
        # claim in place (the pre-fix behaviour); it never settles anything.
        logger.error(json.dumps({
            'event': 'legacy_invoice_claim_release_failed',
            'stage': 'legacy_verify',
            'paymentId': payment_id,
            'error': type(exc).__name__,
            'requestId': request_id,
        }))


def _quarantine_unverified_capture(reference_id: str, payment_id: str,
                                   outcome: Optional[Dict[str, Any]],
                                   request_id: str) -> None:
    """Durably park a capture that could not be authoritatively cleared. Writes nothing financial.

    Reached when a commerce reference did not reconcile to an order and the reference is not a
    provider-verified legacy invoice, or when reconciliation/verification/storage failed. It marks
    NO invoice paid, runs NO post-payment, sends NO confirmation, and does NOT double-write any
    financial state.

    What it DOES do, and why this changed: it persists a durable, recoverable intake row
    (reference_id, payment_id, outcome category, created_at, and acknowledgement fields) to the
    commerce-keys table via the same conditional-write pattern order creation uses. The row it
    replaced was a staff alert LOG and nothing else - which disappears from the operational view
    the moment CloudWatch retention lapses, and is gone entirely once Razorpay stops retrying. A
    durable row stays queryable (see scripts/reconcile_captures.py) and an acknowledged event
    remains recoverable afterwards. The staff alert log is still emitted alongside it, so existing
    alerting keeps firing; the row is the thing that survives.

    The event RECEIPT (the audit row and the 200 response) is handled by the caller and is
    unaffected - this keeps the raw receipt separate from verified financial state. The money may
    or may not have moved, so the customer is never told to retry.
    """
    from lambda_utils.ecommerce import order_creation, order_keys
    category = (outcome or {}).get('outcome') or order_creation.NEEDS_RECONCILIATION

    # The durable, recoverable intake. Keyed by payment id and idempotent, so a redelivery of the
    # same unverified capture does not pile up rows or undo an acknowledgement. A storage failure
    # here must be visible, not swallowed - without the row there is no recovery record - but it
    # must also not fail the webhook (a non-2xx makes Razorpay retry the whole event, and the lease
    # already handles that). So it is logged by type and the alert still fires below.
    persisted = False
    try:
        table = dynamodb.Table(order_keys.commerce_keys_table_name())
        order_keys.record_capture_quarantine(
            table, payment_id=payment_id, reference_id=reference_id or '',
            outcome=category, extra={'source': 'razorpay-webhook'})
        persisted = True
    except Exception as exc:  # noqa: BLE001
        # Type only. A ClientError message can echo request content.
        logger.error(json.dumps({
            'event': 'capture_quarantine_persist_failed',
            'outcome': category,
            'paymentId': payment_id,
            'referenceId': reference_id or None,
            'stage': 'quarantine',
            'error': type(exc).__name__,
            'requestId': request_id,
        }))

    logger.error(json.dumps({
        'event': 'capture_needs_reconciliation',
        'alert': order_creation.NEEDS_RECONCILIATION,
        'outcome': category,
        'paymentId': payment_id,
        'referenceId': reference_id or None,
        'durable': persisted,
        'stage': 'quarantine',
        'requestId': request_id,
    }))


def _handle_wallet_topup_captured(payment: Dict, request_id: str) -> None:
    """Credit a partner wallet for a customer-service top-up — bound, verified, and once.

    This used to trust the event body outright: it read the amount and the recipient WABA from
    `payment.notes` and called `partner_billing.topup` immediately. The webhook signing secret is
    in this repository's public git history, so a signature proves only that someone read the
    history - which meant anyone could forge a `payment.captured` with any `amount` and any
    `wabaId` and mint free wallet balance, and a duplicate delivery of a genuine capture would
    credit twice.

    Three gates close that, in order:

      1. A STORED top-up intent must exist for this reference. The customer-service flow reserves one
         (`reserve_topup_intent`) before the payment link is created, carrying the WABA and amount
         the business actually asked for. No intent -> this is not an authorised top-up -> credit
         nothing. The event notes are never the authority for who or how much.
      2. The captured amount is VERIFIED against Razorpay's API (`payment_is_captured`), never read
         from the event, and must equal the stored intent's amount in INR to the paise.
      3. An idempotency marker (`claim_topup_credit`, keyed by payment id, conditional) is claimed
         BEFORE the credit, so one captured payment credits exactly once and a redelivery credits
         nothing.

    Never raises: a non-2xx makes Razorpay retry the whole event, and nothing here is worth that.
    """
    from decimal import Decimal
    from lambda_utils.ecommerce import order_keys
    from lambda_utils.ecommerce.money import positive_paise
    from lambda_utils.integrations import razorpay_verify

    notes = payment.get('notes', {}) or {}
    payment_id = str(payment.get('id') or '')
    waba_id = str(notes.get('wabaId') or '')
    reference_id = str(notes.get('referenceId') or notes.get('reference_id')
                       or notes.get('ref') or '')

    if not payment_id:
        logger.error(json.dumps({'event': 'partner_wallet_topup_no_payment_id',
                                 'stage': 'wallet_topup', 'requestId': request_id}))
        return

    try:
        table = dynamodb.Table(order_keys.commerce_keys_table_name())

        # Gate 1: a stored top-up intent the business actually created.
        intent = order_keys.resolve_topup_intent(table, reference_id) if reference_id else None
        if not intent:
            # No authorised intent. The event notes are not evidence, so credit nothing and park
            # it for a human instead of trusting the body.
            logger.error(json.dumps({
                'event': 'partner_wallet_topup_no_intent',
                'alert': 'TOPUP_WITHOUT_INTENT',
                'paymentId': payment_id,
                'referenceId': reference_id or None,
                'stage': 'wallet_topup',
                'requestId': request_id,
            }))
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return

        try:
            intent_paise = positive_paise(intent.get('amountPaise'))
        except (ValueError, TypeError):
            logger.error(json.dumps({'event': 'partner_wallet_topup_intent_amount_invalid',
                                     'paymentId': payment_id, 'referenceId': reference_id or None,
                                     'stage': 'wallet_topup', 'requestId': request_id}))
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return
        intent_waba = str(intent.get('wabaId') or '')
        if not intent_waba or (waba_id and waba_id != intent_waba):
            # The event names a different WABA than the one the top-up was created for. Never let
            # the event body redirect a credit; the stored intent is the authority.
            logger.error(json.dumps({'event': 'partner_wallet_topup_waba_mismatch',
                                     'alert': 'TOPUP_WABA_MISMATCH', 'paymentId': payment_id,
                                     'referenceId': reference_id or None, 'stage': 'wallet_topup',
                                     'requestId': request_id}))
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return

        # Gate 2: authoritative provider verification of the captured amount. Never the event body.
        captured, provider_paise, provider_currency = razorpay_verify.payment_is_captured(
            payment_id)
        if not captured or str(provider_currency or '') != 'INR':
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return
        try:
            provider_paise = positive_paise(provider_paise)
        except ValueError:
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return
        if provider_paise != intent_paise:
            # Money moved, but not for the amount the top-up was created for. A human decides.
            logger.error(json.dumps({'event': 'partner_wallet_topup_amount_mismatch',
                                     'alert': 'TOPUP_AMOUNT_MISMATCH', 'paymentId': payment_id,
                                     'referenceId': reference_id or None, 'stage': 'wallet_topup',
                                     'requestId': request_id}))
            _quarantine_unverified_capture(reference_id, payment_id, None, request_id)
            return

        # Gate 3: idempotency. Claim the credit BEFORE applying it, so a duplicate delivery that
        # loses the claim credits nothing. A lost claim is the normal duplicate case, not an error.
        if not order_keys.claim_topup_credit(
                table, payment_id=payment_id, reference_id=reference_id,
                waba_id=intent_waba, amount_paise=intent_paise):
            logger.info(json.dumps({'event': 'partner_wallet_topup_duplicate_skipped',
                                    'paymentId': payment_id, 'referenceId': reference_id or None,
                                    'stage': 'wallet_topup', 'requestId': request_id}))
            return

        # Credit the amount from the STORED INTENT (verified equal to the provider's), in rupees
        # from exact integer paise - never from the event body's float.
        amount_rupees = Decimal(intent_paise) / 100
        from lambda_utils import partner_billing
        r = partner_billing.topup(intent_waba, amount_rupees,
                                  note=f'Razorpay top-up {payment_id}', actor='customer-service')
        logger.info(json.dumps({'event': 'partner_wallet_topup_paid', 'wabaId': intent_waba,
                                'amountPaise': intent_paise, 'balance': r.get('balance'),
                                'paymentId': payment_id, 'referenceId': reference_id or None,
                                'stage': 'wallet_topup', 'requestId': request_id}, default=str))
    except Exception as e:  # noqa: BLE001
        # Type only. A ClientError / provider error message can echo request content.
        logger.error(json.dumps({'event': 'partner_wallet_topup_error',
                                 'error': type(e).__name__, 'paymentId': payment_id,
                                 'stage': 'wallet_topup', 'requestId': request_id}))


def _handle_blog_contribution_captured(payment: Dict, request_id: str) -> None:
    """Settle a Section 5 voluntary blog contribution — bound, verified, once, and no order.

    Mirrors ``_handle_wallet_topup_captured`` exactly, for the BLOG_CONTRIBUTION purpose:

      1. A STORED contribution record must exist for the ``contributionId`` the notes name. No
         record -> not an authorised contribution -> settle nothing, quarantine. The notes are
         never the authority.
      2. The amount is RE-DERIVED from the stored record and VERIFIED against Razorpay's API
         (``payment_is_captured``), never read from the event body, and must equal the stored
         record's amount in INR to the paise.
      3. A conditional one-time claim keyed by the payment id is made BEFORE the settle, so a
         duplicate delivery settles exactly once.

    A BLOG_CONTRIBUTION capture creates NO store product or order. Never raises: a non-2xx
    makes Razorpay retry the whole event, and nothing here is worth that.
    """
    from lambda_utils.ecommerce import blog_contribution, order_keys
    from lambda_utils.integrations import razorpay_verify

    payment_id = str(payment.get('id') or '')
    try:
        table = dynamodb.Table(order_keys.commerce_keys_table_name())

        def quarantine(reference_id: str, pay_id: str) -> None:
            _quarantine_unverified_capture(reference_id, pay_id, None, request_id)

        def verify_capture(pid: str):
            return razorpay_verify.payment_is_captured(pid)

        result = blog_contribution.settle_contribution_capture(
            payment=payment, keys_table=table, verify_capture=verify_capture,
            quarantine=quarantine)
        logger.info(json.dumps({'event': 'blog_contribution_capture_handled',
                                'outcome': result.status, 'paymentId': payment_id,
                                'stage': 'contribution', 'requestId': request_id}))
    except Exception as e:  # noqa: BLE001
        # Type only. A ClientError / provider error message can echo request content.
        logger.error(json.dumps({'event': 'blog_contribution_error',
                                 'error': type(e).__name__, 'paymentId': payment_id,
                                 'stage': 'contribution', 'requestId': request_id}))


_cloudwatch = None


def _emit_reconciliation_metrics(metrics: Dict, request_id: str) -> None:
    """Publish the customer-link reconciliation health to CloudWatch. Best-effort, never raises.

    Namespace `WeCare/CustomerOrderLink`. Four metrics an operator can alarm on:
    `PromotedThisRun`, `PendingRemaining`, `OldestPendingAgeSeconds`, `ReconciliationFailures`.
    The caller's reconciliation must not fail because telemetry did, so every error is logged and
    swallowed here.
    """
    global _cloudwatch
    try:
        if _cloudwatch is None:
            _cloudwatch = boto3.client(
                'cloudwatch', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        _cloudwatch.put_metric_data(Namespace='WeCare/CustomerOrderLink', MetricData=[
            {'MetricName': 'PromotedThisRun', 'Value': float(metrics['promoted']), 'Unit': 'Count'},
            {'MetricName': 'PendingRemaining', 'Value': float(metrics['pendingRemaining']),
             'Unit': 'Count'},
            {'MetricName': 'OldestPendingAgeSeconds',
             'Value': float(metrics['oldestPendingAgeSeconds']), 'Unit': 'Seconds'},
            {'MetricName': 'ReconciliationFailures', 'Value': float(metrics['failures']),
             'Unit': 'Count'},
        ])
    except Exception as error:  # noqa: BLE001 - telemetry must not break reconciliation
        logger.warning(json.dumps({'event': 'reconciliation_metrics_emit_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))


def _materialize_paid_invoice_order(reference_id: str, outcome: Dict, request_id: str) -> None:
    """Resume the complete manual order projection from stored verified payment evidence."""
    from lambda_utils import shared_tables
    from lambda_utils.ecommerce import paid_invoice_order, wa_payment_request
    if (not outcome.get('hasOrder')
            or outcome.get('checkoutMode') != wa_payment_request.WA_NATIVE_CHECKOUT_MODE):
        return
    try:
        row = paid_invoice_order.materialize(
            invoices=dynamodb.Table(INVOICES_TABLE),
            items=dynamodb.Table(shared_tables.invoice_items_table_name()),
            contacts=dynamodb.Table(shared_tables.contacts_table_name()),
            attempts=dynamodb.Table(PAYMENT_ATTEMPTS_TABLE),
            keys=dynamodb.Table(COMMERCE_KEYS_TABLE),
            orders=dynamodb.Table(shared_tables.orders_table_name()),
            reference_id=reference_id, now=int(time.time()))
        logger.info(json.dumps({'event': 'paid_invoice_order_projected',
            'referenceId': reference_id, 'stage': row['finalizationStage'], 'requestId': request_id}))
    except Exception as error:
        logger.error(json.dumps({'event': 'paid_invoice_order_projection_failed',
            'referenceId': reference_id, 'error': type(error).__name__, 'requestId': request_id}))
        # Leave a durable intake record AND fail this delivery so the webhook lease can retry.
        provider_id = str(outcome.get('providerPaymentId') or '')
        if provider_id:
            order_keys.record_capture_quarantine(dynamodb.Table(COMMERCE_KEYS_TABLE),
                payment_id=provider_id, reference_id=reference_id,
                outcome='PAID_ORDER_PROJECTION_FAILED', extra={'stage': 'ORDER_PROJECTION'})
        raise RuntimeError('paid invoice order projection incomplete') from None


def _notification_recipient(reference_id: str, provider_contact: str) -> str:
    """The billed customer owns invoice notifications; the payer may be someone else."""
    try:
        items = dynamodb.Table(INVOICES_TABLE).query(
            IndexName='referenceId-index', KeyConditionExpression='referenceId = :ref',
            ExpressionAttributeValues={':ref': reference_id}, Limit=2).get('Items', [])
        if len(items) > 1:
            return ''
        if items:
            return str(items[0].get('customerPhone') or '')
        reference = order_keys.resolve_payment_reference(
            dynamodb.Table(COMMERCE_KEYS_TABLE), reference_id) or {}
        if reference.get('invoiceId'):
            invoice = dynamodb.Table(INVOICES_TABLE).get_item(
                Key={'invoiceId': reference['invoiceId']}, ConsistentRead=True).get('Item') or {}
            if invoice.get('referenceId') == reference_id:
                return str(invoice.get('customerPhone') or '')
            return ''
        # Native WhatsApp checkout (catalog cart / catalog service) has no invoice until this
        # capture creates one, so the billed customer is the one checkout recorded on OUR PAYREF#
        # row from the Cognito-verified session phone - never the Razorpay event body. The
        # engine's own recipient check (`send_invoice_whatsapp`) still refuses delivery unless
        # the created invoice names the same customer.
        from lambda_utils.ecommerce import wa_payment_request, website_checkout
        if reference.get('checkoutMode') in (wa_payment_request.WA_NATIVE_CART_CHECKOUT_MODE,
                                             'AWS_NATIVE'):
            return str(reference.get('customerPhone') or '')
        # Website Standard Checkout also authenticates the buyer through the same WhatsApp-OTP
        # identity, and the proven phone is stored server-side on OUR rows: newer PAYREF# rows
        # carry it directly, while older rows predating that write carry it only on the
        # PaymentAttempt (read by the stored paymentAttemptId). Never the Razorpay payer contact.
        # The engine's own recipient check still refuses delivery unless the created invoice names
        # the same customer, so this only names a candidate; it never forces delivery.
        if reference.get('checkoutMode') == website_checkout.CHECKOUT_MODE_WEBSITE:
            billed = str(reference.get('customerPhone') or '')
            if billed:
                return billed
            attempt_id = str(reference.get('paymentAttemptId') or '')
            if attempt_id:
                attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
                    Key={'paymentAttemptId': attempt_id},
                    ConsistentRead=True).get('Item') or {}
                return str(attempt.get('customerPhone') or '')
            return ''
        return ''
    except Exception as error:
        logger.warning(json.dumps({'event': 'payment_recipient_unavailable',
            'referenceId': reference_id, 'error': type(error).__name__}))
        return ''



def _handle_payment_captured(event_data: Dict, request_id: str) -> None:
    """Handle payment.captured — the main success event. Store payment + mark invoice paid + trigger invoice."""
    payment = event_data.get('payment', {}).get('entity', {})
    payment_id = payment.get('id', '')
    # INTEGER PAISE is the single value. `amount_rupees` is gone: it was a float derived by
    # division and then passed into four other functions, two of which persisted it.
    amount_paise = payment_status.paise(payment.get('amount', 0))
    # A display STRING beside it. A string cannot be arithmetic'd by accident, which is the
    # whole reason `payment_status.rupees_str` returns one.
    amount_display = payment_status.rupees_str(amount_paise)
    currency = payment.get('currency', 'INR')
    order_id = payment.get('order_id', '')
    method = payment.get('method', '')
    contact = payment.get('contact', '')
    email = payment.get('email', '')
    description = payment.get('description', '')
    # Razorpay serialises EMPTY notes as a JSON array (`"notes": []` in its own sample payloads),
    # not as an object. Every read below is a `.get`, so a capture carrying no notes raised
    # AttributeError at the referenceId lookup: a 500 on every Razorpay retry, and a capture that
    # never reached the quarantine below. Anything that is not an object carries no notes.
    notes = payment.get('notes')
    if not isinstance(notes, dict):
        notes = {}

    # Partner prepaid wallet top-up (customer-service): if this payment was created for
    # a wallet top-up, credit the tenant's wallet and stop (not an invoice payment).
    if (notes or {}).get('purpose') == 'wallet_topup' and (notes or {}).get('wabaId'):
        _handle_wallet_topup_captured(payment, request_id)
        return

    # Section 5 voluntary blog contribution (BLOG_CONTRIBUTION): settle the stored contribution
    # record and stop. This is NOT an invoice payment and must NOT create a store product or
    # order, so it must not fall through below. The amount is re-derived from the stored record,
    # never from these notes - the notes are only a routing hint.
    if (notes or {}).get('purpose') == 'BLOG_CONTRIBUTION':
        _handle_blog_contribution_captured(payment, request_id)
        return

    # Paid secure-file download (wecare.digital/get): hand the order id to secure-files
    # and stop. Not an invoice payment, so it must not fall through below.
    #
    # Note what is NOT passed: payment_id, amount, contact, notes. Nothing this event
    # claims is carried forward, because nothing this event claims is trusted. Only the
    # order id travels, and secure-files re-derives everything else from the grant and
    # from Razorpay's API.
    if (notes or {}).get('purpose') == 'secure_file_download' and order_id:
        _dispatch_download_grant_confirmation(order_id, request_id)
        return

    # Try to find referenceId from multiple locations in Razorpay notes
    # Meta passes our notes through to Razorpay, but the key name may vary:
    # - 'referenceId' (our standard)
    # - 'reference_id' (snake_case variant)
    # - 'ref' (short form used in some test scripts)
    # - description field (legacy)
    reference_id = (
        notes.get('referenceId', '')
        or notes.get('reference_id', '')
        or notes.get('ref', '')
        or ''
    )
    
    # If not found in notes, try description
    if not reference_id:
        desc = payment.get('description', '') or ''
        if desc.upper().startswith('WD'):
            reference_id = desc
    
    # Still none: resolve it from an EXACT stored binding of the Razorpay order id, or not at all.
    # A phone number, an amount or "the customer's pending invoice" is never evidence of which
    # purchase a payment is for. An unattributed capture falls through to the durable quarantine
    # below - recorded and recoverable, never guessed. See `_reference_id_from_stored_binding`.
    if not reference_id:
        reference_id = _reference_id_from_stored_binding(order_id, payment_id, request_id)

    # A17: the receipt of the event is worth recording, but the event body is not evidence and
    # must not be dumped. Log only a correlation id (referenceId), the stage, the requestId, and
    # the paymentId. No contact, no notes, no description, no email, no amount-as-free-text.
    logger.info(json.dumps({
        'event': 'payment_captured', 'paymentId': payment_id,
        'referenceId': reference_id or None,
        'stage': 'received',
        'requestId': request_id,
    }))

    # ── C1: an authoritative PAID verdict, not the event, gates every financial-success effect ──
    #
    # The webhook body is a trigger, never proof: the signing secret is in this repository's public
    # git history, so a valid signature proves only that someone read the history. So we reconcile
    # against Razorpay's own API and act ONLY on the typed verdict it returns. A NOT_PAID /
    # mismatch / unknown / unavailable / error / quarantine verdict produces ZERO of: a captured
    # money-confirmed payment record, an invoice-paid write, the receipt/post-payment run, or the
    # CTWA purchase attribution. (No verdict sends an ORDER_STATUS: see the block further down.)
    from lambda_utils.ecommerce import order_creation

    outcome = None
    if reference_id:
        outcome = _create_order_for_captured_payment(payment, reference_id, request_id)

    verified_paid = bool(outcome and outcome.get('hasOrder'))
    outcome_kind = (outcome or {}).get('outcome') or ''

    # ── R1/C1: the typed outcome, not `not verified_paid`, decides the fall-through ──
    #
    # The old guard branched to the legacy verifier on ANY non-success. That swept in every
    # PAID_BUT_BLOCKED outcome (AMOUNT_MISMATCH / CURRENCY_MISMATCH / CUSTOMER_MISMATCH /
    # IDENTITY_UNAVAILABLE / PROVIDER_PAYMENT_CONFLICT): a capture whose money moved but whose
    # commerce attempt we refused could still be matched to a same-priced invoice and settled.
    # The legacy path is now permitted for exactly ONE positively-established provenance:
    # UNKNOWN_REFERENCE - no PaymentAttempt exists at all, so this may genuinely be a pre-commerce
    # invoice-only payment. Every other outcome (paid-but-blocked, not-paid, unavailable, error,
    # needs-reconciliation) goes straight to durable quarantine and never touches an invoice.
    legacy_invoice_id = ''
    if reference_id and not verified_paid and outcome_kind == order_creation.UNKNOWN_REFERENCE:
        legacy_invoice_id = _verified_legacy_invoice(
            reference_id, payment, request_id)
    legacy_invoice_verified = bool(legacy_invoice_id)

    financial_success = verified_paid or legacy_invoice_verified

    if not financial_success:
        # Nothing here is authoritatively paid for THIS invoice/order. Do NOT write a
        # money-confirmed 'captured' record, do NOT mark any invoice paid, do NOT run post-payment,
        # do NOT attribute, do NOT confirm. A paid-but-blocked outcome in particular must be parked
        # for a human rather than guessed into a legacy settlement.
        _quarantine_unverified_capture(reference_id, payment_id, outcome, request_id)
        return

    # ── Legacy stranded-claim reconciliation (review Issue 1) ──
    #
    # On the legacy path the one-time PROVIDERPAYMENT#<payment_id> claim is taken INSIDE
    # _verified_legacy_invoice, before this settle runs - a two-query design (the verifier reads the
    # referenceId GSI with Limit=2 and claims; the settle re-queries that GSI independently with
    # full pagination). If the settle then no-ops - the row vanished, a second row appeared so it is
    # ambiguous, or the conditional update raised a non-conditional storage error - the irreversible
    # claim would be burned with NO settled row behind it, stranding a legitimate payment so it can
    # never settle any invoice afterward, including on a Razorpay redelivery (only a human could
    # clear it). So on the legacy path we settle FIRST and keep the claim only when a row was
    # actually marked paid. When nothing settled we RELEASE the claim and quarantine instead.
    #
    # This stays money-safe. The release is conditional on the claim still being THIS payment's
    # LEGACY_INVOICE_PAYMENT_CLAIM for THIS invoice, and it runs only when _mark_invoice_paid_by_
    # reference reports no settled row - so no invoice is paid for this payment anywhere when we
    # release. A cross-reference replay still loses the held claim while it is held; a one-payment-
    # two-invoices (ambiguous) case still settles none. R1/C1 and R2 are untouched: the commerce
    # path below is unchanged, and the legacy claim/settle ordering only adds a release on failure.
    if legacy_invoice_verified:
        if not _mark_invoice_paid_by_reference(reference_id, request_id, payment_id):
            _release_legacy_invoice_payment_claim(
                payment_id, legacy_invoice_id, request_id)
            _quarantine_unverified_capture(reference_id, payment_id, outcome, request_id)
            return
        # A legacy invoice row is now settled and the claim is backed by it. Record the captured
        # financial state.
        _store_payment_record(payment, 'captured', request_id)
    else:
        # Verified commerce path (ORDER_CREATED / ORDER_ALREADY_EXISTS). The authoritative order
        # already exists via reconcile; the invoice-paid write is a secondary projection. Ordering
        # and behaviour here are unchanged from before this reconciliation was added.
        _store_payment_record(payment, 'captured', request_id)
        _mark_invoice_paid_by_reference(reference_id, request_id, payment_id)

    # Post-payment: create invoice, generate image (internal reference only)
    #
    # The channel rides along so the GST invoice prints the SAME origin the orders page shows for
    # the same order. It comes off the reconciliation outcome, which read it from the `PAYREF#`
    # row - never from `notes`, because Razorpay notes are request content and attribution the
    # request can set is attribution a customer can forge. Absent on the legacy settlement path
    # (no `PAYREF#` row exists there), which `create_invoice` canonicalises to `website`.
    # `customerUuid` rides the same outcome dict for the same reason, and is absent on the
    # legacy settlement path where no `PAYREF#` row exists - which prints no Customer ID row
    # rather than a placeholder.
    # ── the originating phone, resolved ONCE and BEFORE the post-payment call ──
    #
    # It used to be resolved inside the `if contact and reference_id:` block further down, which
    # runs AFTER `_post_payment_handler` returns - so the invoice delivery that call now performs
    # had no sender to use. Resolved here instead, so the GST invoice returns from the SAME
    # number that collected the payment, and the WABA1 default travels WITH the resolution.
    _materialize_paid_invoice_order(reference_id, outcome or {}, request_id)
    contact = _notification_recipient(reference_id, contact)
    originating_phone_id = _resolve_originating_phone(reference_id) or WABA1_PHONE_ID

    # The owner-approved post-payment sequence (plan T7/D2), and nothing else:
    #   1. PAYMENT_PAID -> OrderTable.orderStatus 'processing' (written by finalization above)
    #   2. Meta order_status 'processing' for a WhatsApp-native order (`_start_native_fulfilment`)
    #   3. the paid invoice template, once - the statutory receipt with the Leave Review button
    # Steps 2 and 3 both run inside `_post_payment_handler`, because the engine keys an
    # order_status on the invoice, so the invoice must exist first. Step 2 is bounded and can
    # never raise, so the receipt never depends on it; see `_start_native_fulfilment`.
    checkout_mode = str((outcome or {}).get('checkoutMode') or '')
    _post_payment_handler(payment_id, contact, email, description, notes, request_id,
                          channel=str((outcome or {}).get('channel') or ''),
                          customer_uuid=str((outcome or {}).get('customerUuid') or ''),
                          checkout_mode=checkout_mode,
                          originating_phone_id=originating_phone_id,
                          reference_id=reference_id)

    # Conversions API: if this conversation started from a Click-to-WhatsApp ad,
    # log a Purchase event to Meta so the ad campaign can optimize/measure. No-op
    # (returns 400, just logged) for non-ad conversations. Fire-and-forget.
    _log_ctwa_purchase(
        contact, amount_paise, currency, order_id, notes, request_id,
        payment_attempt_id=str((outcome or {}).get('paymentAttemptId') or ''),
    )

    # Post-payment service activation remains an internal business step.
    #
    # Customer-facing payment completion is the invoice-image template sent above.
    # The paid-submit-request handler this
    # invokes no longer pushes a separate interactive Flow invitation; it only activates the
    # service relationship and preserves the details-collection model for its normal entry points.
    if contact and reference_id:
        try:
            clean_phone = (contact or '').replace('+', '').replace(' ', '').replace('-', '')
            if not clean_phone.startswith('91') and len(clean_phone) == 10:
                clean_phone = f'91{clean_phone}'

            # The phone is already resolved above. The invoice-row read below can still REFINE
            # it, but only as an upgrade - see the block further down.
            originating_invoice_id = ''
            order_display_number = reference_id
            order_product = 'Your order'
            _inv = None
            inv_items = []
            try:
                inv_table = dynamodb.Table(INVOICES_TABLE)
                inv_resp = inv_table.query(
                    IndexName='referenceId-index',
                    KeyConditionExpression='referenceId = :ref',
                    ExpressionAttributeValues={':ref': reference_id},
                    Limit=1,
                )
                inv_items = inv_resp.get('Items', [])
                if inv_items:
                    _inv = inv_items[0]
                    originating_invoice_id = _inv.get('invoiceId', '')
                    order_display_number = (_inv.get('invoiceNumber') or _inv.get('orderId')
                                            or originating_invoice_id or reference_id)
                    _its = _inv.get('items')
                    if isinstance(_its, str):
                        try:
                            _its = json.loads(_its)
                        except Exception:
                            _its = []
                    if isinstance(_its, list) and _its and isinstance(_its[0], dict):
                        order_product = _its[0].get('name', '') or order_product
                    # Carry the catalog product id so the post-payment flow resolver
                    # can open the flow mapped to THIS product (catalog_flow_map).
                    _rid = _inv.get('catalogRetailerId') or ''
                    if _rid and 'catalogRetailerId' not in (notes or {}):
                        if notes is None:
                            notes = {}
                        notes['catalogRetailerId'] = _rid
            except Exception:
                pass

            # ── Resolve the ORIGINATING WABA phone reliably ──
            # The payment message was SENT from a specific business number; the
            # confirmation + post-pay flow MUST go back from that SAME number/WABA
            # (never cross-WABA). The authoritative source is the OutboundTable
            # record (paymentReferenceId-index → awsPhoneNumberId/phoneNumberId).
            # Guessing from paymentConfiguration is unreliable for catalog orders
            # (they carry no 'WECARE-' config) and caused WABA1 payments to reply
            # from WABA2. Fall back to the config guess only if the lookup fails.
            # The invoice row is the authority `_resolve_originating_phone`'s own layer 1 names,
            # so it is permitted to REFINE the value resolved above - but only as an UPGRADE,
            # never as a replacement by a weaker source. A disagreement is logged so it is
            # visible rather than silent.
            resolved_phone = _resolve_originating_phone(reference_id, _inv)
            if resolved_phone and resolved_phone != originating_phone_id:
                logger.info(json.dumps({
                    'event': 'razorpay_phone_refined', 'referenceId': reference_id,
                    'phoneId': resolved_phone, 'requestId': request_id}))
                originating_phone_id = resolved_phone
            elif not resolved_phone and originating_phone_id == WABA1_PHONE_ID:
                # All three authoritative lookups failed. There is no second
                # signal to fall back on: the payment configuration name used to
                # identify the WABA (WABA1 was hyphenated, WABA2 was not), but
                # Meta rebuilt the configs on 2026-08-23 and both WABAs now
                # expose the IDENTICAL pair WECAREDIGITAL / WECAREUPI. The old
                # 'WECARE-'/'UPIVPA' substring test therefore matched nothing and
                # always landed on Phone 2 - it only looked like a decision.
                #
                # The fall-through is the PRIMARY identity. Phone 2 is
                # marked `paymentProtected: true` and the UI gates it behind an
                # admin authorization step before payments may be sent from it,
                # so defaulting to it server-side bypassed that check.
                logger.warning(json.dumps({
                    'event': 'razorpay_phone_unresolved_using_primary',
                    'referenceId': reference_id, 'phoneId': originating_phone_id,
                    'note': 'invoice/Outbound/Inbound lookups all failed; config name '
                            'cannot identify a WABA. Defaulting to the primary '
                            'identity; never to the admin-gated secondary.',
                    'requestId': request_id}))
            logger.info(json.dumps({'event': 'razorpay_phone_resolved', 'referenceId': reference_id,
                                    'phoneId': originating_phone_id, 'fromOutbound': bool(resolved_phone),
                                    'requestId': request_id}))

            # No post-payment Flow or interactive message is sent here.
            # The paid invoice image template is the only customer confirmation after capture.
        except Exception as e:
            # A17: type only. A ClientError message can echo request content.
            logger.warning(json.dumps({'event': 'razorpay_post_payment_flow_error', 'error': type(e).__name__, 'requestId': request_id}))


def _phone_from_payment_reference_table(table_name: str, reference_id: str) -> str:
    """Look up a payment_request/outbound record by paymentReferenceId in the given
    table and return its originating business phone id. Tries the GSI first, then a
    bounded scan. Returns '' if not found."""
    try:
        table = dynamodb.Table(table_name)
        items = []
        try:
            resp = table.query(
                IndexName='paymentReferenceId-index',
                KeyConditionExpression='paymentReferenceId = :ref',
                ExpressionAttributeValues={':ref': reference_id},
                Limit=1,
            )
            items = resp.get('Items', [])
        except Exception:
            resp = table.scan(
                FilterExpression='paymentReferenceId = :ref',
                ExpressionAttributeValues={':ref': reference_id},
                ProjectionExpression='awsPhoneNumberId, phoneNumberId',
                Limit=2000,
            )
            items = resp.get('Items', [])
        if items:
            return items[0].get('awsPhoneNumberId') or items[0].get('phoneNumberId') or ''
    except Exception as e:
        logger.warning(json.dumps({'event': 'phone_lookup_error', 'table': table_name,
                                   'error': str(e), 'referenceId': reference_id}))
    return ''


def _log_ctwa_purchase(contact: str, amount_paise: int, currency: str,
                       order_id: str, notes: Dict, request_id: str,
                       payment_attempt_id: str = '') -> None:
    """Fire a Click-to-WhatsApp Purchase conversion event via the Conversions API.
    Delegates to wecare-whatsapp-business-api (which owns the dataset + ctwa_clid
    lookup). If the customer's conversation didn't originate from a CTWA ad, the
    business-api returns 400 and this is a harmless no-op. Never blocks payment."""
    try:
        phone = ''.join(ch for ch in (contact or '') if ch.isdigit())
        if not phone:
            return
        waba_id = (notes or {}).get('wabaId', '') or (notes or {}).get('metaWabaId', '')
        payload = {
            'eventName': 'Purchase',
            'phone': phone,
            # Built ONCE from integer paise, as a string. Meta's Conversions API takes a decimal
            # value; deriving it exactly from paise is what keeps a reported conversion value
            # from drifting from the amount actually captured.
            'value': payment_status.rupees_str(amount_paise),
            'currency': currency or 'INR',
            'orderId': order_id or (notes or {}).get('referenceId', ''),
        }
        if payment_attempt_id:
            try:
                from lambda_utils.ecommerce import meta_catalog_sync
                attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
                    Key={'paymentAttemptId': payment_attempt_id},
                    ConsistentRead=True,
                ).get('Item') or {}
                raw_contents = attempt.get('catalogContents')
                if isinstance(raw_contents, list) and raw_contents:
                    contents = []
                    for line in raw_contents:
                        if not isinstance(line, dict):
                            contents = []
                            break
                        product_id = str(line.get('productId') or '').strip()
                        variant_id = str(line.get('variantId') or '').strip()
                        quantity = line.get('quantity')
                        if (not product_id or not variant_id
                                or type(quantity) is not int or quantity <= 0):
                            contents = []
                            break
                        contents.append({
                            'id': meta_catalog_sync.retailer_id(product_id, variant_id),
                            'quantity': quantity,
                        })
                    if contents:
                        payload['contents'] = contents
            except Exception:
                # Analytics enrichment must never change a verified payment outcome.
                pass
        if waba_id:
            payload['wabaId'] = waba_id
        event = {
            'requestContext': {'http': {'method': 'POST', 'path': '/wa-business/capi/event'}},
            'rawPath': '/wa-business/capi/event',
            'body': json.dumps(payload),
        }
        lambda_client.invoke(
            # The `live` alias: the unqualified name would run $LATEST, unpublished code.
            FunctionName=os.environ.get('WA_BUSINESS_FUNCTION', 'wecare-whatsapp-business-api:live'),
            InvocationType='Event',  # async, fire-and-forget
            Payload=json.dumps(event),
        )
        logger.info(json.dumps({'event': 'ctwa_purchase_event_dispatched',
                                'phone': phone[-4:], 'amountPaise': amount_paise,
                                'requestId': request_id}))
    except Exception as e:  # noqa: BLE001
        logger.warning(f'ctwa purchase event dispatch failed (non-blocking): {e}')


def _resolve_originating_phone(reference_id: str, invoice_item: Dict = None) -> str:
    """Resolve the business phone (WABA) the payment message was sent from, so the
    confirmation + post-pay flow reply from the SAME number/WABA (NEVER cross-WABA).

    Layered, in priority order (each is an authoritative record tied to this exact
    payment reference — no config guessing):
      1) the invoice record's own awsPhoneNumberId (stored at send time)
      2) OutboundTable  paymentReferenceId-index  → awsPhoneNumberId
      3) InboundTable   payment_request record    → awsPhoneNumberId  (catalog cart path;
         the outbound Lambda writes this with the sending phone)
    Returns '' only if none of the sources know the phone (caller then guesses)."""
    # 1) invoice record (most reliable — the webhook already fetched it)
    if invoice_item:
        inv_phone = invoice_item.get('awsPhoneNumberId') or invoice_item.get('phoneNumberId') or ''
        if inv_phone:
            return inv_phone
    if not reference_id:
        return ''
    # 2) OutboundTable
    phone = _phone_from_payment_reference_table(
        os.environ.get('OUTBOUND_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable'), reference_id)
    if phone:
        return phone
    # 3) InboundTable payment_request record (catalog cart interactive-payment send)
    phone = _phone_from_payment_reference_table(
        os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable'), reference_id)
    if phone:
        return phone
    return ''


# Post-payment WhatsApp Flows and interactive messages are intentionally retired.
# Payment capture proceeds directly to paid-invoice PNG delivery.


# Post-payment WhatsApp Flows and interactive messages are intentionally retired.
# Payment capture proceeds directly to paid-invoice PNG delivery.


def _handle_payment_authorized(event_data: Dict, request_id: str) -> None:
    """Handle payment.authorized — payment authorized but not yet captured."""
    payment = event_data.get('payment', {}).get('entity', {})
    payment_id = payment.get('id', '')
    logger.info(json.dumps({'event': 'payment_authorized', 'paymentId': payment_id, 'requestId': request_id}))
    _store_payment_record(payment, 'authorized', request_id)


def _handle_payment_pending(event_data: Dict, request_id: str) -> None:
    """Handle payment.pending — UPI/bank transfer pending."""
    payment = event_data.get('payment', {}).get('entity', {})
    payment_id = payment.get('id', '')
    logger.info(json.dumps({'event': 'payment_pending', 'paymentId': payment_id, 'requestId': request_id}))
    _store_payment_record(payment, 'pending', request_id)


def _handle_payment_failed(event_data: Dict, request_id: str) -> None:
    """Handle payment.failed — payment attempt failed. Update linked invoice status."""
    payment = event_data.get('payment', {}).get('entity', {})
    payment_id = payment.get('id', '')
    error_code = payment.get('error_code', '')
    error_desc = payment.get('error_description', '')
    # Razorpay serialises EMPTY notes as `[]`; `.get` on it raised AttributeError, turning every
    # notes-less `payment.failed` into a 500 that Razorpay retries. Same guard as the capture path.
    notes = payment.get('notes')
    if not isinstance(notes, dict):
        notes = {}
    logger.warning(json.dumps({
        'event': 'payment_failed', 'paymentId': payment_id,
        'errorCode': error_code, 'errorDesc': error_desc, 'requestId': request_id,
    }))
    _store_payment_record(payment, 'failed', request_id)

    # Update linked invoice status to payment_failed (if referenceId exists)
    reference_id = notes.get('referenceId', '')
    if reference_id:
        try:
            import time as _time
            inv_table = dynamodb.Table(os.environ.get('INVOICES_TABLE', 'stack-wecare-digital-InvoicesTable'))
            # Use referenceId GSI instead of full table scan
            matched = []
            query_kwargs = {
                'IndexName': 'referenceId-index',
                'KeyConditionExpression': 'referenceId = :ref',
                'ExpressionAttributeValues': {':ref': reference_id},
            }
            resp = inv_table.query(**query_kwargs)
            matched.extend(resp.get('Items', []))
            while 'LastEvaluatedKey' in resp:
                query_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                resp = inv_table.query(**query_kwargs)
                matched.extend(resp.get('Items', []))

            for inv in matched:
                if inv.get('paymentStatus') in ('pending', 'pending_payment', None, ''):
                    inv_table.update_item(
                        Key={'invoiceId': inv['invoiceId']},
                        UpdateExpression='SET paymentStatus = :ps, updatedAt = :now',
                        ExpressionAttributeValues={
                            ':ps': 'failed',
                            ':now': Decimal(str(int(_time.time()))),
                        },
                    )
                    logger.info(json.dumps({'event': 'invoice_payment_failed', 'invoiceId': inv['invoiceId'], 'referenceId': reference_id, 'requestId': request_id}))
        except Exception as e:
            logger.error(json.dumps({'event': 'invoice_fail_update_error', 'referenceId': reference_id, 'error': str(e), 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# REFERENCE_ID RECOVERY: AN EXACT STORED BINDING, NEVER A GUESS
# ═══════════════════════════════════════════════════════════════════

def _reference_id_from_stored_binding(razorpay_order_id: str, payment_id: str,
                                      request_id: str) -> str:
    """The referenceId a capture without `notes.referenceId` EXACTLY belongs to, or ''.

    Attribution is by identifier, never by resemblance. The one key consulted is the capture's
    Razorpay `order_id`, read against the `GATEWAYORDER#<order_id>` binding on the commerce-keys
    table (`order_keys.resolve_gateway_order`, one consistent GetItem). Only this system writes
    that row, and it records a `referenceId` on two paths: `website_checkout._bind_and_ready` when
    our checkout creates the gateway order, and `meta_payment_binding.bind_attempt` once Meta has
    confirmed which gateway order paid a native reference. It is keyed by the order id and claimed
    conditionally, once, so a match is exact by construction and there is never a second
    candidate to choose between.

    What this replaced, so nobody re-derives it as a convenience: `_lookup_reference_id_from_meta`
    scanned InvoicesTable filtered only by status and returned the referenceId of the FIRST
    pending invoice whose `customerPhone` matched the payment's `contact`. A customer with two
    pending invoices could have the payment attributed to the other one, and that referenceId
    then drove reconciliation, the invoice-paid write and the customer's confirmation. Downstream
    checks refuse most wrong guesses but not all: `reconcile_payment` answers ORDER_ALREADY_EXISTS
    for an attempt that already has an order BEFORE it contacts the provider, so a guess landing
    on an already-ordered reference read as a verified success and settled the wrong invoice.
    Its docstring also promised a Meta Payment Lookup confirmation; no such call was ever made.

    Deliberately NOT consulted:

      * the payment's `contact`, `email` or amount. None of them identifies a purchase: two
        pending invoices for one phone at one price is an ordinary repeat order.
      * InvoicesTable. No current writer records a Razorpay order id on an invoice (the legacy
        `providerOrderId` / `order_id` fields `_verified_legacy_invoice` reads have none), the
        payment ids that do land there (`paymentId`, `providerPaymentId`) are recorded only once
        a payment is already settled, and nothing indexes any of them. Matching there would be a
        full scan for values a first delivery cannot carry.
      * Meta. Its Payment Lookup is keyed by OUR reference, which is the unknown here; the native
        leg binds through `meta_payment_binding` once a reference is known.
      * the entity's `invoice_id`, or a payment-link id (which a `payment.captured` entity does
        not carry). Nothing here stores either, so neither can be matched exactly.

    Returns '' when there is no order id, no binding, a binding that names no reference (a blog
    contribution's carries `contributionId` instead), or the binding cannot be read. An unreadable
    binding means "we do not know" and is never widened into an answer from a weaker source. Each
    '' is logged as ONE structured `reference_id_unattributed` event carrying provider ids and a
    reason only (no contact, notes, email or amount), and the caller then parks the capture via
    `_quarantine_unverified_capture`: the durable `CAPTUREQUARANTINE#<paymentId>` row that
    `scripts/reconcile_captures.py` lists, beside the `RazorpayWebhookLogTable` audit row that
    `handler` writes before dispatch. Recorded and recoverable, never guessed.

    A match only SELECTS which stored reference to reconcile and proves nothing about money; it
    gives a forged event nothing it could not already claim through `notes.referenceId`.
    Everything after it is unchanged, including the provider readback and the exact
    amount/currency comparison `reconcile_payment` makes against the attempt.

    Never raises.
    """
    order_id = str(razorpay_order_id or '')
    reason = 'no_provider_order_id'
    error_type = ''
    if order_id:
        try:
            binding = order_keys.resolve_gateway_order(
                dynamodb.Table(order_keys.commerce_keys_table_name()), order_id)
            reference_id = str((binding or {}).get('referenceId') or '')
            if reference_id:
                logger.info(json.dumps({
                    'event': 'reference_id_recovered',
                    'source': 'gateway_order_binding',
                    'referenceId': reference_id,
                    'paymentId': payment_id,
                    'razorpayOrderId': order_id,
                    'stage': 'reference_recovery',
                    'requestId': request_id,
                }))
                return reference_id
            reason = 'binding_has_no_reference' if binding else 'no_stored_binding'
        except Exception as exc:  # noqa: BLE001
            # Type only. A ClientError message can echo request content.
            reason = 'binding_unavailable'
            error_type = type(exc).__name__

    logger.warning(json.dumps({
        'event': 'reference_id_unattributed',
        'reason': reason,
        'error': error_type or None,
        'paymentId': payment_id,
        'razorpayOrderId': order_id or None,
        'stage': 'reference_recovery',
        'requestId': request_id,
    }))
    return ''


# ═══════════════════════════════════════════════════════════════════
# STORE PAYMENT RECORD
# ═══════════════════════════════════════════════════════════════════

def _store_payment_record(payment: Dict, status: str, request_id: str) -> None:
    """Store/update payment record in PaymentsTable."""
    import time as _time
    payment_id = payment.get('id', '')
    if not payment_id:
        return

    amount_paise = payment_status.paise(payment.get('amount') or 0)

    def _safe_int(val):
        """Safely convert to int, handling None."""
        if val is None:
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    record = {
        'id': payment_id,
        'paymentId': payment_id,
        'orderId': payment.get('order_id') or '',
        'referenceId': (payment.get('notes') or {}).get('referenceId', '') or (payment.get('notes') or {}).get('ref', ''),
        'status': status,
        'amount': Decimal(amount_paise),
        # A STRING, so the unit ambiguity `payment_status.paise`'s docstring records - "one item,
        # two units, no field name saying which" - cannot be arithmetic'd even by a reader who
        # misses it. `amount` above is the comparable figure.
        'amountInRupees': payment_status.rupees_str(amount_paise),
        'currency': payment.get('currency') or 'INR',
        'method': payment.get('method') or '',
        'contact': payment.get('contact') or '',
        'email': payment.get('email') or '',
        'description': payment.get('description') or '',
        'notes': json.dumps(payment.get('notes') or {}, default=str),
        'vpa': payment.get('vpa') or '',
        'bank': payment.get('bank') or '',
        'wallet': payment.get('wallet') or '',
        'cardId': payment.get('card_id') or '',
        'fee': Decimal(str(_safe_int(payment.get('fee')))),
        'tax': Decimal(str(_safe_int(payment.get('tax')))),
        'errorCode': payment.get('error_code') or '',
        'errorDescription': payment.get('error_description') or '',
        'errorSource': payment.get('error_source') or '',
        'errorStep': payment.get('error_step') or '',
        'errorReason': payment.get('error_reason') or '',
        'international': payment.get('international', False),
        'captured': payment.get('captured', False),
        'razorpayCreatedAt': Decimal(str(_safe_int(payment.get('created_at')))),
        'createdAt': Decimal(str(int(_time.time()))),
        'updatedAt': Decimal(str(int(_time.time()))),
        'requestId': request_id,
    }

    # The rank makes this write MONOTONIC. It used to be a bare `put_item`, which meant
    # the last delivery won whatever it said - and because a `put_item` replaces the whole
    # item while this record carries no refund fields, a redelivered `payment.captured`
    # arriving after `refund.processed` both reset the status to captured AND erased
    # `refundId` and `refundAmount`. The row then read as money kept when the money had
    # been returned, with nothing anywhere reporting it.
    #
    # `refunded` outranks `captured`, so that put is now refused outright and the refund
    # fields survive by never being overwritten. Same mechanism as
    # lambda_utils/wa_status and rcs_status, applied to the one domain where a backward
    # transition is a financial misstatement rather than a cosmetic one.
    record[payment_status.RANK_ATTRIBUTE] = payment_status.rank(status)

    # Remove empty string values (DynamoDB doesn't allow empty strings in some cases)
    clean = {k: v for k, v in record.items() if v is not None and v != ''}

    try:
        table = dynamodb.Table(PAYMENTS_TABLE)
        table.put_item(
            Item=clean,
            ConditionExpression=payment_status.condition_expression(),
            ExpressionAttributeValues={':rank': payment_status.rank(status)},
        )
        logger.info(json.dumps({'event': 'payment_stored', 'paymentId': payment_id,
                                'status': status,
                                'rank': payment_status.rank(status),
                                'requestId': request_id}))
    except Exception as e:
        if order_keys.is_conditional_failure(e):
            # Expected and correct: a stale or out-of-order delivery. Recorded at info,
            # not error, so it does not read as a fault - but recorded, because a high
            # volume here would mean the provider is redelivering heavily.
            logger.info(json.dumps({
                'event': 'payment_status_not_applied',
                'paymentId': payment_id,
                'incomingStatus': status,
                'reason': payment_status.describe(status) + ' does not beat the stored rank',
                'requestId': request_id,
            }))
            return
        logger.error(json.dumps({'event': 'payment_store_error', 'paymentId': payment_id, 'error': str(e), 'requestId': request_id}))

def _mark_invoice_paid_by_reference(reference_id: str, request_id: str,
                                    payment_id: str = '') -> bool:
    """Settle EXACTLY ONE invoice row for `reference_id`, conditionally, or none when ambiguous.

    R2 (single-row conditional settlement). This used to loop over every GSI match and mark each
    one paid. The referenceId GSI is not a unique key: more than one invoice row can carry the same
    referenceId (a reissue, a backfill, or a forged collision), and the loop would then settle all
    of them off a single capture. That is the same defect the sibling
    `_mark_invoice_paid_by_phone_and_amount` already closed, so this now mirrors its discipline:

      * more than one matching row -> AMBIGUOUS. Settle none and park the capture for a human; a
        wrongly-settled invoice is unrecoverable because nothing downstream knows it was wrong.
      * exactly one matching row -> settle it with a ConditionExpression that binds the write to
        the row still being unpaid (`status <> 'paid'`), so a concurrent delivery cannot double
        it and a redelivery is a harmless no-op.

    When a `payment_id` is supplied (the legacy path), it is stamped onto the settled row as the
    provider transaction that settled it, so the row records which capture paid it.

    Returns True when the referenced invoice is settled (newly marked paid by this call, OR already
    paid by a concurrent/earlier delivery), and False when NOTHING is settled - no row matched, the
    match was ambiguous, or a storage error prevented the write. The legacy caller uses this verdict
    to decide whether the irreversible one-time PROVIDERPAYMENT# claim it took earlier is backed by
    an actually-settled row; a False here lets it release that claim rather than strand the payment
    (see `_handle_payment_captured`). This return value must stay truthful about settlement for that
    reconciliation to be money-safe: never return True unless a paid row exists for this reference.
    """
    if not reference_id:
        return False
    try:
        import time as _time
        import datetime
        table = dynamodb.Table(INVOICES_TABLE)
        now = int(_time.time())
        now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        paid_at_ts = int(now_ist.timestamp())

        # Use referenceId GSI instead of table scan.
        found = []
        query_kwargs = {
            'IndexName': 'referenceId-index',
            'KeyConditionExpression': 'referenceId = :ref',
            'ExpressionAttributeValues': {':ref': reference_id},
        }
        resp = table.query(**query_kwargs)
        found.extend(resp.get('Items', []))
        while 'LastEvaluatedKey' in resp:
            query_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            resp = table.query(**query_kwargs)
            found.extend(resp.get('Items', []))

        if len(found) > 1:
            # AMBIGUOUS: a single capture cannot be allowed to settle multiple invoice rows. Refuse
            # and surface it for manual reconciliation rather than settling the wrong one(s).
            logger.error(json.dumps({
                'event': 'invoice_reference_match_ambiguous_not_marked',
                'referenceId': reference_id,
                'candidateCount': len(found),
                'candidateInvoiceIds': sorted(
                    str(c.get('invoiceId', '')) for c in found)[:10],
                'requestId': request_id,
            }))
            _quarantine_unverified_capture(reference_id, payment_id or '', None, request_id)
            return False

        if not found:
            # No invoice row for this reference. Nothing settled.
            return False

        inv = found[0]
        if inv.get('status') == 'paid':
            # Already settled (earlier delivery / concurrent writer). The row IS paid, so this is a
            # settled outcome - the legacy caller must NOT release its claim.
            return True

        update_names = {
            '#st': 'status', '#ps': 'paymentStatus',
            '#pa': 'paidAt', '#ua': 'updatedAt',
        }
        update_values = {
            ':st': 'paid', ':ps': 'captured',
            ':pa': paid_at_ts, ':now': now, ':paid': 'paid',
        }
        set_expr = 'SET #st = :st, #ps = :ps, #pa = :pa, #ua = :now'
        if payment_id:
            update_names['#pt'] = 'providerPaymentId'
            update_values[':pt'] = payment_id
            set_expr += ', #pt = :pt'
        try:
            table.update_item(
                Key={'invoiceId': inv['invoiceId']},
                UpdateExpression=set_expr,
                # Conditional: only settle a row that is not already paid, so a concurrent or
                # replayed delivery cannot settle twice.
                ConditionExpression='#st <> :paid',
                ExpressionAttributeNames=update_names,
                ExpressionAttributeValues=update_values,
            )
        except Exception as cond_err:  # noqa: BLE001
            if order_keys.is_conditional_failure(cond_err):
                # Already paid by a concurrent delivery. Harmless and expected; not an error.
                logger.info(json.dumps({
                    'event': 'invoice_already_paid_on_settle',
                    'invoiceId': inv['invoiceId'],
                    'referenceId': reference_id,
                    'requestId': request_id,
                }))
                # The row is paid, just not by this call. Settled either way.
                return True
            raise
        logger.info(json.dumps({
            'event': 'invoice_marked_paid_by_webhook',
            'invoiceId': inv['invoiceId'],
            'referenceId': reference_id,
            'requestId': request_id,
        }))
        return True
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'mark_invoice_paid_error',
            'referenceId': reference_id,
            'error': type(e).__name__,
            'requestId': request_id,
        }))
        # A storage error means we cannot confirm a row was settled. Report not-settled so the
        # legacy caller releases its one-time claim rather than stranding the payment.
        return False

def _mark_invoice_paid_by_phone_and_amount(phone: str, amount_rupees: float,
                                           request_id: str) -> bool:
    """Fallback: find the ONE pending invoice matching this phone and amount.

    Matching is an exact 10-digit local number plus an exact integer-paise amount.
    It used to be a float comparison with an epsilon, and both properties that
    changed were wrong in the same direction - too permissive:

    * The epsilon was 0.02 while the comment claimed +/- Rs 0.01, so a Rs 100.00
      invoice matched a Rs 100.01 payment.
    * More than one match was resolved by taking the oldest. Two pending invoices
      for the same phone and the same total is an ordinary repeat order, and there
      the old code marked the wrong invoice paid and left the real one
      outstanding - one payment, two wrong rows.

    Returns True only when exactly one invoice was matched and updated; False for
    no match, an ambiguous match, or an error. An unreconciled payment is
    recoverable because someone can still look at it; a wrongly-reconciled one is
    not, because nothing downstream knows it was wrong.

    Runs only after referenceId recovery has already failed, so there is no
    further signal available here to disambiguate with.
    """
    if not phone:
        return False
    try:
        import time as _time
        import datetime
        amount_paise = payment_status.paise(Decimal(str(amount_rupees)) * 100)
        table = dynamodb.Table(INVOICES_TABLE)
        clean_ph = phone.replace('+', '').replace(' ', '').replace('-', '')
        if clean_ph.startswith('91') and len(clean_ph) == 12:
            local10 = clean_ph[2:]
        elif len(clean_ph) >= 10:
            local10 = clean_ph[-10:]
        else:
            local10 = clean_ph
        now = int(_time.time())
        now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        paid_at_ts = int(now_ist.timestamp())

        pending_statuses = ['created', 'pending_payment', 'sent']
        scan_kwargs = {
            'FilterExpression': 'attribute_exists(customerPhone) AND #st IN (:s1, :s2, :s3)',
            'ExpressionAttributeNames': {'#st': 'status'},
            'ExpressionAttributeValues': {':s1': 'created', ':s2': 'pending_payment', ':s3': 'sent'},
        }
        candidates = []
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get('Items', []):
                inv_phone_raw = (item.get('customerPhone', '') or '').replace('+', '').replace(' ', '').replace('-', '')
                if inv_phone_raw.startswith('91') and len(inv_phone_raw) == 12:
                    inv_local = inv_phone_raw[2:]
                elif len(inv_phone_raw) >= 10:
                    inv_local = inv_phone_raw[-10:]
                else:
                    inv_local = inv_phone_raw
                # Exact match in integer paise. This used to be
                # `abs(float(total) - amount_rupees) < 0.02`, whose comment claimed
                # "within Rs 0.01" while the epsilon was 0.02 - so an invoice for
                # 100.00 matched a payment of 100.01, and a float comparison
                # decided which invoice was paid. Money is compared as minor units
                # here and nowhere as a float.
                try:
                    inv_paise = payment_status.paise(
                        Decimal(str(item.get('total', 0))) * 100)
                except (ValueError, ArithmeticError, TypeError):
                    continue
                if inv_local == local10 and len(local10) == 10 and inv_paise == amount_paise:
                    candidates.append(item)
            if 'LastEvaluatedKey' in resp:
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            else:
                break

        if len(candidates) > 1:
            # AMBIGUOUS - do not guess.
            #
            # This path previously sorted by createdAt and marked the OLDEST match
            # paid. Two pending invoices for the same phone with the same total is
            # an ordinary situation (a repeat order), and in that case the old code
            # marked the wrong invoice paid AND left the real one outstanding: one
            # payment, two wrong rows. Picking deterministically is not the same as
            # picking correctly.
            #
            # This is the fallback that only runs after referenceId recovery has
            # already failed, so there is no further signal available here to
            # disambiguate. Refuse, and surface it for manual reconciliation -
            # an unreconciled payment is recoverable, a wrongly-reconciled one is
            # not, because nothing afterwards knows it was wrong.
            logger.error(json.dumps({
                'event': 'invoice_match_ambiguous_not_marked',
                'candidateCount': len(candidates),
                'candidateInvoiceIds': sorted(
                    str(c.get('invoiceId', '')) for c in candidates)[:10],
                'amountPaise': amount_paise,
                'phoneLast4': local10[-4:] if len(local10) >= 4 else '',
                'requestId': request_id,
            }))
            return False

        if len(candidates) == 1:
            inv = candidates[0]
            table.update_item(
                Key={'invoiceId': inv['invoiceId']},
                UpdateExpression='SET #st = :st, #ps = :ps, #pa = :pa, #ua = :now',
                ExpressionAttributeNames={
                    '#st': 'status', '#ps': 'paymentStatus',
                    '#pa': 'paidAt', '#ua': 'updatedAt',
                },
                ExpressionAttributeValues={
                    ':st': 'paid', ':ps': 'captured',
                    ':pa': paid_at_ts, ':now': now,
                },
            )
            # Phone masked to the last four, as at every other log site in this
            # codebase. These three lines carried the full number.
            logger.info(json.dumps({
                'event': 'invoice_marked_paid_by_phone_amount',
                'invoiceId': inv['invoiceId'],
                'phoneLast4': local10[-4:] if len(local10) >= 4 else '',
                'amountPaise': amount_paise,
                'requestId': request_id,
            }))
            return True

        logger.warning(json.dumps({
            'event': 'no_invoice_match_phone_amount',
            'phoneLast4': local10[-4:] if len(local10) >= 4 else '',
            'amountPaise': amount_paise,
            'requestId': request_id,
        }))
        return False
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'mark_invoice_paid_by_phone_error',
            'error': str(e),
            'requestId': request_id,
        }))
        return False


# ═══════════════════════════════════════════════════════════════════
# POST-PAYMENT HANDLER (Invoice + WhatsApp)
# ═══════════════════════════════════════════════════════════════════


def _plain_number(value: Any) -> Any:
    """`json.dumps` default for DynamoDB numbers: whole Decimals as int, anything else as str."""
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return str(value)


def _native_cart_invoice_fields(reference_id: str, checkout_mode: str,
                                request_id: str) -> Dict[str, Any]:
    """The billed customer and quoted invoice lines for a native-cart OR website paid invoice.

    Both come from OUR rows: the `PAYREF#` reservation (the Cognito-verified phone checkout
    recorded, the same one `_notification_recipient` delivers to) and its PaymentAttempt's
    `invoiceLines`. The Razorpay payer contact is not the billed customer - it can be empty or
    another number, and an invoice addressed to it is refused delivery to the buyer - and the
    event's notes are request content.

    Website Standard Checkout is included for the same reason as the native cart: the buyer is
    proven through the same WhatsApp-OTP identity and checkout records the billed phone and the
    quoted `invoiceLines` on OUR rows, so a capture whose browser never returned still bills the
    verified buyer and itemises the basket rather than addressing the Razorpay payer as one line.
    Older website rows predating those writes carry neither field, and the single-line fallback
    below covers them.

    `{}` for every other checkout mode and on any read failure, so the invoice keeps its
    single-line fallback instead of failing a capture that has already settled.
    """
    from lambda_utils.ecommerce import wa_payment_request, website_checkout
    if not reference_id or checkout_mode not in (wa_payment_request.WA_NATIVE_CART_CHECKOUT_MODE,
                                                 'AWS_NATIVE',
                                                 website_checkout.CHECKOUT_MODE_WEBSITE):
        return {}
    try:
        reference = order_keys.resolve_payment_reference(
            dynamodb.Table(COMMERCE_KEYS_TABLE), reference_id) or {}
        fields: Dict[str, Any] = {}
        billed_phone = str(reference.get('customerPhone') or '')
        if billed_phone:
            fields['customerPhone'] = billed_phone
        attempt_id = str(reference.get('paymentAttemptId') or '')
        if attempt_id:
            attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
                Key={'paymentAttemptId': attempt_id}, ConsistentRead=True).get('Item') or {}
            lines = attempt.get('invoiceLines')
            if isinstance(lines, dict) and lines.get('lines'):
                fields['nativeCartInvoice'] = json.loads(json.dumps(lines, default=_plain_number))
        return fields
    except Exception as error:  # noqa: BLE001 - itemisation never fails a settled capture
        logger.warning(json.dumps({'event': 'native_cart_invoice_fields_unavailable',
                                   'referenceId': reference_id,
                                   'error': type(error).__name__, 'requestId': request_id}))
        return {}


def _post_payment_handler(payment_id: str, contact: str,
                          email: str, description: str, notes: Dict, request_id: str,
                          *, channel: str = '', customer_uuid: str = '',
                          checkout_mode: str = '', originating_phone_id: str = '',
                          reference_id: str = '') -> None:
    """
    After payment captured (Razorpay webhook path):
    This is the authoritative invoice path for a verified capture. (It was once described as a
    BACKUP to a WhatsApp inbound generator; that generator no longer mints the invoice, so the
    label was stale.)
    1. Invoke invoice-engine to create invoice from payment (dedup will return existing if another path already created it)
    2. Generate invoice image (POS receipt style)
    3. WhatsApp-native orders only: advance the Meta payment-order lifecycle in order:
       `processing` ("Payment received.") then `completed` ("Payment complete.").
       The second transition is attempted only after the first was accepted or already current.
    4. Deliver the GST invoice IMAGE template on WhatsApp, once. The invoice template itself
       exposes the Leave Review Flow button; no standalone review/free-form confirmation is sent.

    `channel` is WHERE the order came from (`website` / `whatsapp`), read off the `PAYREF#` row by
    the reconciliation above. KEYWORD-ONLY and defaulted so the legacy callers that pass eight
    positional arguments are unaffected, and so omitting it is a silent, correct `website` rather
    than a TypeError on a path where the money has already moved.

    `customer_uuid` is the public customer id, read off the same `PAYREF#` row. Keyword-only and
    defaulted for the identical reason, and - unlike the channel - an omission has no default
    beyond empty: the invoice simply prints no Customer ID row, which is the honest answer for a
    payment whose reference row carries none.

    `checkout_mode` is MECHANICS - how the money settled. It remains on the invoice/order context
    for attribution and diagnostics, but it no longer gates receipt delivery: a verified paid
    commerce order with a server-resolved WhatsApp recipient receives the invoice template.

    `amount` and `currency` are GONE from this signature rather than retyped. Measured, neither
    name occurred anywhere in the body after the signature - they were dead parameters carrying
    a float on a money path.
    """
    logger.info(json.dumps({'event': 'post_payment_start', 'paymentId': payment_id, 'path': 'webhook_backup', 'requestId': request_id}))

    # ── Step 1: Create invoice from payment (dedup-safe) ──
    try:
        invoice_payload = {
            'body': json.dumps({
                'paymentId': payment_id,
                'entryPoint': 'webhook',
                # NOT the same fact as `entryPoint`, which records which internal flow minted the
                # invoice. A WhatsApp-origin catalogue order settles on the website leg, so its
                # entryPoint is a website one while its channel is `whatsapp`; printing entryPoint
                # as the Source line would tell the customer the wrong origin.
                'channel': channel,
                # OURS, read off the `PAYREF#` row, never from `notes`. The engine re-validates
                # it with `customer_uuid.is_customer_uuid` before storing, so a junk value is
                # dropped rather than printed on a tax invoice.
                'customerUuid': customer_uuid,
                'itemName': description or notes.get('itemName', 'Payment'),
                # ── the `notes` money quartet is DROPPED, not re-derived ──
                #
                # `gstRate`, `shipping`, `discount` and `convenienceFee` used to be read off
                # Razorpay `notes` as floats. The event body is not evidence and `notes` are
                # REQUEST CONTENT a caller can set, so these were four caller-settable money
                # figures travelling into a GST invoice. The authoritative values live on the
                # `PAYREF#`/attempt row for a native payment and on the invoice itself for a
                # legacy one, and `create_invoice_from_payment` already defaults `gstRate` to 18
                # and the three money fields to 0. Re-deriving them from the attempt was the
                # alternative and is more code for a value the invoice already holds.
                'purpose': notes.get('purpose', description or ''),
                # A native WhatsApp cart: the BILLED customer and the quoted lines, read from OUR
                # PAYREF# + attempt rows (never from this event), so the invoice is itemised and
                # addressed to the verified buyer rather than to whoever's contact Razorpay holds.
                **_native_cart_invoice_fields(reference_id, checkout_mode, request_id),
            }),
            'rawPath': '/invoices/from-payment',
            'requestContext': {'http': {'method': 'POST'}},
        }

        inv_response = lambda_client.invoke(
            FunctionName=COMMERCE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps(invoice_payload),
        )
        inv_result = json.loads(inv_response['Payload'].read())
        inv_body = json.loads(inv_result.get('body', '{}'))
        invoice_id = inv_body.get('invoiceId', '')
        invoice_number = inv_body.get('invoiceNumber', '')
        deduplicated = inv_body.get('deduplicated', False)

        logger.info(json.dumps({
            'event': 'invoice_created_from_payment', 'paymentId': payment_id,
            'invoiceId': invoice_id, 'invoiceNumber': invoice_number,
            'deduplicated': deduplicated, 'requestId': request_id,
        }))
    except Exception as e:
        # A verified capture with no invoice is a money-moved-but-no-receipt incident. Record a
        # durable quarantine and RAISE so the webhook lease lapses and Razorpay redelivers the
        # capture; the invoice create is dedup-safe, so the retry cannot double-bill. Only the
        # commerce path reaches this handler (an order was verified above), so there is always a
        # reference/order behind the failure. `type(e).__name__` only - an exception message can
        # echo request content.
        order_keys.record_capture_quarantine(
            dynamodb.Table(COMMERCE_KEYS_TABLE),
            payment_id=payment_id, reference_id=reference_id,
            outcome='INVOICE_CREATE_FAILED', extra={'error': type(e).__name__})
        logger.error(json.dumps({'event': 'invoice_create_error', 'paymentId': payment_id,
                                 'error': type(e).__name__, 'requestId': request_id,
                                 'alert': 'INVOICE_CREATE_FAILED'}))
        raise RuntimeError('invoice creation failed for a verified capture') from None
    if not invoice_id:
        # Same incident as the exception above: the engine answered but named no invoice, so there
        # is no receipt to deliver and no durable projection. Quarantine and raise so the capture
        # is redelivered rather than silently dropped.
        order_keys.record_capture_quarantine(
            dynamodb.Table(COMMERCE_KEYS_TABLE),
            payment_id=payment_id, reference_id=reference_id,
            outcome='INVOICE_CREATE_FAILED', extra={'stage': 'EMPTY_INVOICE_ID'})
        logger.error(json.dumps({'event': 'invoice_create_empty', 'paymentId': payment_id,
                                 'requestId': request_id, 'alert': 'INVOICE_CREATE_FAILED'}))
        raise RuntimeError('invoice creation returned no invoice id for a verified capture')

    # If deduplicated (WhatsApp path already created it), the receipt image already exists —
    # skip the render step only.
    #
    # This used to `return`, and with delivery added below that would skip delivery for exactly
    # the case where the invoice already existed - which is the COMMON case on the native leg,
    # because `send_payment_link` wrote `referenceId` onto the invoice, so
    # `create_invoice_from_payment` dedups onto it and reports `deduplicated: True` on the very
    # first capture. The delivery CLAIM is the idempotency control for step 4, and a claim is
    # strictly better than inferring delivery from invoice novelty.
    if not deduplicated:
        _generate_invoice_assets(invoice_id, request_id)
    else:
        logger.info(json.dumps({'event': 'post_payment_dedup_skip_assets',
                                'paymentId': payment_id, 'invoiceId': invoice_id,
                                'requestId': request_id}))

    # ── Step 3: finish the Meta payment-order lifecycle before the receipt ──
    #
    # Payment-only invariant: pending -> processing -> completed. The chained helper sends the
    # second transition ONLY when processing was accepted (or was already current), so Meta never
    # receives completed out of order. Both sends are template-only in outbound-whatsapp.
    _start_native_fulfilment(reference_id, checkout_mode, originating_phone_id, request_id,
                             invoice_id=invoice_id)

    # ── Step 4: deliver the GST invoice to the customer's VERIFIED WhatsApp number ──
    #
    # UNIVERSAL FOR COMMERCE ORDERS: both Website and WhatsApp checkout authenticate the customer
    # through the same WhatsApp-OTP identity. Website checkout stores that proven phone on the
    # PaymentAttempt/PAYREF/order; _notification_recipient above resolves from those server-owned
    # rows. Therefore channel is attribution only and MUST NOT suppress the receipt.
    #
    # We still require a resolved stored contact. No browser/body phone can open this gate.
    # Legacy settlements with no verified commerce identity remain fail-closed because contact
    # resolves empty unless existing server-owned invoice/reference evidence supplies it.
    #
    # It travels as the approved `wecare_default_invoice_image_template` (invoice PNG in its
    # header). It does not depend on step 3: it goes out whether that update was sent, deferred,
    # not applicable or unavailable. Later fulfilment updates (shipped / completed) stay a
    # staff-driven workflow (`/invoices/{id}/order-status`). This template delivers the statutory
    # receipt and its embedded Leave Review Flow button.
    #
    # Delivery is retried by REPLAY: a miss raises so the webhook lease lapses and Razorpay
    # redelivers the capture, and the delivery CLAIM inside `send_invoice_whatsapp` makes the
    # re-send idempotent (no double receipt). The retry is bounded by
    # `_receipt_delivery_should_retry`.
    delivered = False
    if contact and invoice_id:
        delivered = _deliver_invoice_on_whatsapp(
            invoice_id, contact, originating_phone_id, request_id)
        if not delivered and _receipt_delivery_should_retry(invoice_id, request_id):
            # A transient miss (Meta down, throttle, uncertain send): raise so the webhook
            # lease lapses and Razorpay redelivers, and the delivery CLAIM makes the re-send
            # idempotent. BOUNDED by `_receipt_delivery_should_retry` so a persistently
            # undeliverable receipt cannot pin the money-path lease in an infinite replay of an
            # already-captured, already-finalized payment: once the cap is reached the capture
            # is allowed to settle and the stuck receipt is quarantined for manual follow-up
            # below. The paid state and the order are already correct at this point.
            raise RuntimeError('Invoice receipt delivery is pending')
        if not delivered:
            # Retries exhausted. Do NOT raise - the capture must settle. Record a durable
            # quarantine so a human can re-send the receipt; the delivery claim is idempotent,
            # so a later manual or forced resend still cannot double-send.
            order_keys.record_capture_quarantine(
                dynamodb.Table(COMMERCE_KEYS_TABLE),
                payment_id=payment_id, reference_id=reference_id,
                outcome='RECEIPT_DELIVERY_EXHAUSTED', extra={'invoiceId': invoice_id})
            logger.error(json.dumps({
                'event': 'invoice_receipt_delivery_exhausted', 'invoiceId': invoice_id,
                'referenceId': reference_id, 'requestId': request_id,
                'alert': 'RECEIPT_DELIVERY_EXHAUSTED'}))

    # The invoice template itself contains the Leave Review Flow button.
    # Do not send a second standalone review template from the payment webhook.
    logger.info(json.dumps({'event': 'post_payment_complete', 'paymentId': payment_id,
                            'invoiceId': invoice_id, 'invoiceDelivered': delivered,
                            'path': 'webhook_backup', 'requestId': request_id}))


def _generate_invoice_assets(invoice_id: str, request_id: str) -> None:
    """Render the invoice PNG used for customer delivery.

    Invoice PDF generation is intentionally retired. The WhatsApp customer receives one
    rendered image, and all post-payment automation depends only on that image asset.
    Historical PDF assets remain untouched but no new PDF is generated here.
    """
    try:
        img_payload = {
            'rawPath': f'/invoices/{invoice_id}/generate-image',
            'requestContext': {'http': {'method': 'POST'}},
            'pathParameters': {'invoiceId': invoice_id},
            'body': json.dumps({'invoiceId': invoice_id}),
        }
        img_response = lambda_client.invoke(
            FunctionName=COMMERCE_FUNCTION,
            InvocationType='RequestResponse',
            Payload=json.dumps(img_payload),
        )
        img_result = json.loads(img_response['Payload'].read())
        img_body = json.loads(img_result.get('body', '{}'))
        image_url = img_body.get('imageUrl', '')

        logger.info(json.dumps({
            'event': 'invoice_image_generated',
            'invoiceId': invoice_id,
            'hasImage': bool(image_url),
            'requestId': request_id,
        }))
    except Exception as e:
        logger.error(json.dumps({
            'event': 'invoice_image_error',
            'invoiceId': invoice_id,
            'error': type(e).__name__,
            'requestId': request_id,
        }))


#: How many times a captured payment may be REPLAYED to retry a missed receipt delivery before
#: the capture is allowed to settle and the receipt is quarantined for manual follow-up. Each
#: Razorpay redelivery of the capture is one attempt. Bounded so a persistently undeliverable
#: receipt (a number Meta will not message, a permanently rejected template) cannot pin the
#: money-path lease in an endless replay of an already-finalized payment.
_RECEIPT_DELIVERY_MAX_ATTEMPTS = 6


def _receipt_delivery_should_retry(invoice_id: str, request_id: str) -> bool:
    """Record one receipt-delivery attempt on the invoice; True while under the retry cap.

    The counter lives on the invoice row (`receiptDispatchAttempts`), incremented with an
    ADD so a redelivered capture advances it by one. Fails OPEN to retry: if the counter cannot
    be read/written we return True, because the existing behaviour was to always retry and a
    storage blip must not be what drops a customer's receipt. It only returns False once the
    stored count has reached the cap - the one case where continuing to raise would replay a
    finalized payment forever.
    """
    try:
        updated = dynamodb.Table(INVOICES_TABLE).update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression='ADD receiptDispatchAttempts :one',
            ExpressionAttributeValues={':one': 1},
            ReturnValues='UPDATED_NEW',
        )
        attempts = int(updated.get('Attributes', {}).get('receiptDispatchAttempts', 1) or 1)
        return attempts < _RECEIPT_DELIVERY_MAX_ATTEMPTS
    except Exception as error:  # noqa: BLE001 - fail OPEN toward retrying
        logger.warning(json.dumps({
            'event': 'receipt_delivery_attempt_count_unavailable', 'invoiceId': invoice_id,
            'error': type(error).__name__, 'requestId': request_id}))
        return True


def _deliver_invoice_on_whatsapp(invoice_id: str, contact: str, phone_number_id: str,
                                 request_id: str) -> bool:
    """Observe engine acceptance; an accepted Lambda invoke alone is not delivery evidence."""
    from lambda_utils.comms.numbers import to_e164
    recipient = to_e164(contact)
    if not recipient:
        return False
    table = dynamodb.Table(COMMERCE_KEYS_TABLE)
    try:
        if not order_keys.claim_invoice_delivery(table, invoice_id=invoice_id,
                channel='whatsapp-dispatch', extra={'requestId': request_id}):
            previous = order_keys.resolve_invoice_delivery(table, invoice_id,
                                                            channel='whatsapp-dispatch') or {}
            if previous.get('deliveryStatus') == order_keys.DELIVERY_CONFIRMED:
                return True
            # Our own dispatch claim exists but is NOT confirmed. That is the ambiguous case: an
            # earlier capture claimed delivery and either the engine really sent it (and our
            # confirm write was lost) or it never did. Consult the ENGINE's own delivery claim,
            # which `send_invoice_whatsapp` owns, to break the tie rather than re-sending blindly.
            engine = order_keys.resolve_invoice_delivery(table, invoice_id,
                                                         channel='whatsapp') or {}
            engine_status = engine.get('deliveryStatus')
            if engine_status == order_keys.DELIVERY_CONFIRMED:
                # The engine delivered. Confirm OUR dispatch claim with the engine's waMessageId
                # so a later pass short-circuits here, and report success - no re-send.
                order_keys.confirm_invoice_delivery(table, invoice_id=invoice_id,
                    channel='whatsapp-dispatch',
                    wa_message_id=str(engine.get('waMessageId') or ''))
                return True
            if engine_status == order_keys.DELIVERY_CLAIMED:
                # The engine holds its own in-flight claim: a send may be in progress. Re-sending
                # now could double-deliver, so wait for a later pass rather than resolve it here.
                return False
            # The engine has no claim at all, so the stale dispatch claim is not backed by any
            # send. Release it and retry the invoke ONCE on this pass.
            order_keys.release_invoice_delivery(table, invoice_id=invoice_id,
                                                channel='whatsapp-dispatch')
            if not order_keys.claim_invoice_delivery(table, invoice_id=invoice_id,
                    channel='whatsapp-dispatch', extra={'requestId': request_id}):
                # Another concurrent pass re-claimed between the release and here. Treat it the
                # same as a held claim: do not double-send.
                return False
        response = lambda_client.invoke(
            FunctionName=COMMERCE_FUNCTION, InvocationType='RequestResponse',
            Payload=json.dumps({'rawPath': f'/invoices/{invoice_id}/send-whatsapp',
                'requestContext': {'http': {'method': 'POST'}},
                'pathParameters': {'invoiceId': invoice_id},
                'body': json.dumps({'invoiceId': invoice_id, 'toWhatsAppNumber': recipient,
                    'phoneNumberId': phone_number_id or WABA1_PHONE_ID})}))
        if response.get('FunctionError'):
            return False
        result = json.loads(response['Payload'].read())
        body = result.get('body') or {}
        if isinstance(body, str):
            body = json.loads(body)
        status = body.get('status')
        message_id = body.get('waMessageId') or body.get('whatsappMessageId')
        accepted = (int(result.get('statusCode') or 0) == 200 and message_id
                    and status in ('accepted', 'sent', 'delivered', 'read', 'already_delivered'))
        if accepted:
            order_keys.confirm_invoice_delivery(table, invoice_id=invoice_id,
                channel='whatsapp-dispatch', wa_message_id=message_id)
            return True
        if status in ('failed', 'rejected') or int(result.get('statusCode') or 0) in (400, 401, 403, 404):
            order_keys.release_invoice_delivery(table, invoice_id=invoice_id,
                                                channel='whatsapp-dispatch')
        return False
    except Exception as error:
        # The engine may already have submitted the message. Preserve the pending claim.
        logger.error(json.dumps({'event': 'invoice_delivery_dispatch_uncertain',
            'invoiceId': invoice_id, 'error': type(error).__name__, 'requestId': request_id}))
        return False


# ═══════════════════════════════════════════════════════════════════
# ORDER EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_order_paid(event_data: Dict, request_id: str) -> None:
    """Handle order.paid — order fully paid."""
    order = event_data.get('order', {}).get('entity', {})
    order_id = order.get('id', '')
    logger.info(json.dumps({'event': 'order_paid', 'orderId': order_id, 'requestId': request_id}))


def _handle_order_notification(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle order notification events (delivered/failed)."""
    order = event_data.get('order', {}).get('entity', {})
    order_id = order.get('id', '')
    logger.info(json.dumps({'event': event_type, 'orderId': order_id, 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# PAYMENT LINK EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_payment_link(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle payment_link.* events."""
    link = event_data.get('payment_link', {}).get('entity', {})
    link_id = link.get('id', '')
    status = link.get('status', '')
    logger.info(json.dumps({'event': event_type, 'linkId': link_id, 'status': status, 'requestId': request_id}))

    # If payment link paid, the payment.captured event will also fire
    # and handle invoice creation. Just log here.


# ═══════════════════════════════════════════════════════════════════
# REFUND EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_refund(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle refund.* events."""
    _, refund = payment_status.extract_entity(event_data)
    refund_id = refund.get('id', '')
    payment_id = refund.get('payment_id', '')
    # Paise, matching `amount` on the same row. It used to divide by 100 and store rupees
    # in `refundAmount` while `amount` on that very item stayed in paise - one row, two
    # units, and no field name saying which. Nothing would have caught a reconciliation
    # comparing them. PaymentsTable holds 0 rows, so there is nothing to migrate.
    try:
        refund_paise = payment_status.paise(refund.get('amount'))
    except ValueError as exc:
        logger.error(json.dumps({
            'event': 'refund_amount_unusable', 'refundId': refund_id,
            'paymentId': payment_id, 'reason': str(exc), 'requestId': request_id,
        }))
        refund_paise = None
    status = refund.get('status', '')
    logger.info(json.dumps({
        'event': event_type, 'refundId': refund_id, 'paymentId': payment_id,
        'amountPaise': refund_paise, 'status': status, 'requestId': request_id,
    }))

    # Update payment record status if refund processed
    if event_type == 'refund.processed' and payment_id and refund_paise is not None:
        try:
            table = dynamodb.Table(PAYMENTS_TABLE)
            import time as _time
            # Monotonic, like the capture write. `refunded` outranks `captured`, so this
            # applies over a captured payment and is then itself protected from any later
            # redelivered payment.* event.
            refunded_rank = payment_status.rank(payment_status.REFUNDED)
            table.update_item(
                Key={'id': payment_id},
                UpdateExpression=('SET #st = :st, #refundId = :rid, #refundAmount = :ra, '
                                  f'#rank = :rank, #ua = :now'),
                ConditionExpression=payment_status.condition_expression('#rank'),
                ExpressionAttributeNames={
                    '#st': 'status', '#refundId': 'refundId',
                    '#refundAmount': 'refundAmountPaise',
                    '#rank': payment_status.RANK_ATTRIBUTE, '#ua': 'updatedAt',
                },
                ExpressionAttributeValues={
                    ':st': payment_status.REFUNDED, ':rid': refund_id,
                    ':ra': Decimal(str(refund_paise)), ':rank': refunded_rank,
                    ':now': Decimal(str(int(_time.time()))),
                },
            )
        except Exception as e:
            if order_keys.is_conditional_failure(e):
                logger.info(json.dumps({
                    'event': 'refund_status_not_applied', 'paymentId': payment_id,
                    'refundId': refund_id,
                    'reason': 'stored rank already at or beyond refunded',
                    'requestId': request_id,
                }))
                return
            logger.error(json.dumps({'event': 'refund_update_error', 'error': str(e), 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# DISPUTE EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_dispute(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle payment.dispute.* events.

    Same entity-key defect as downtime: a dispute arrives under ``payment.dispute``, and
    this read ``event_data.get('dispute')``. No dispute has been received on this account,
    so unlike downtime the fault was never exercised - but it would have logged an empty
    dispute for a contested payment, which is the worst possible moment to have no detail.

    Still log-only. Writing `disputed` onto the payment row is a behaviour change and a
    separate decision; the rank exists in `payment_status` for when it is made.
    """
    logger.warning(json.dumps({
        'event': event_type,
        **payment_status.entity_summary(event_data),
        'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# DOWNTIME EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_downtime(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle payment.downtime.* events.

    The entity arrives under the literal key ``payment.downtime`` - with a dot. This used
    to read ``event_data.get('downtime')`` and then fall back to
    ``event_data.get('payment', {}).get('downtime', {})``; neither key exists, so the
    entity was always `{}`.

    Verified against CloudWatch: all 607 downtime events in the live log were processed
    with `method: ""` and `instrument: "{}"`. Downtime is currently the ONLY payment
    webhook traffic this account receives, and its method, affected bank and severity -
    the entire actionable content - were being discarded.
    """
    logger.warning(json.dumps({
        'event': event_type,
        **payment_status.entity_summary(event_data),
        'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# SETTLEMENT EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_settlement(event_type: str, event_data: Dict, request_id: str) -> None:
    """Record a settlement as reconciliation evidence. Creates no paid state.

    A settlement is the BANK TRANSFER of money already captured, arriving days later in a batch
    covering many payments. The money became ours at `payment.captured`, which is the only event
    permitted to move an order forward - so this writes a settlement record and touches no order,
    no invoice and no customer message.

    It deliberately does NOT finalize an order, mark an invoice paid, send a message, or move any
    payment status. Doing so would either be a no-op or, worse, a SECOND write path to paid state.
    The honest fix for this handler was integer money plus a durable record, not a finalisation it
    has no business performing.
    """
    # `extract_entity` rather than a hand-dug `event_data['settlement']['entity']`:
    # `payment_status.ENTITY_KEYS` exists because `event_data.get('downtime')` never matched for
    # 607 live events, and a settlement is in exactly that family of nested containers.
    _, settlement = payment_status.extract_entity(event_data)
    settlement_id = str(settlement.get('id') or '')
    try:
        amount_paise = payment_status.paise(settlement.get('amount'))
    except (ValueError, ArithmeticError, TypeError):
        logger.error(json.dumps({'event': 'settlement_amount_unreadable',
                                 'settlementId': settlement_id, 'requestId': request_id}))
        return
    # Compared EXPLICITLY, never inferred from the amount.
    if str(settlement.get('currency') or 'INR') != 'INR':
        logger.error(json.dumps({'event': 'settlement_currency_unexpected',
                                 'settlementId': settlement_id, 'requestId': request_id}))
        return
    logger.info(json.dumps({
        'event': event_type, 'settlementId': settlement_id,
        'amountPaise': amount_paise,                               # INTEGER
        'amountRupees': payment_status.rupees_str(amount_paise),    # STRING, display only
        'status': str(settlement.get('status') or ''),
        'requestId': request_id,
    }))
    _store_settlement_record(settlement_id, amount_paise, settlement, request_id)


def _store_settlement_record(settlement_id: str, amount_paise: int, settlement: Dict,
                             request_id: str) -> None:
    """A durable settlement row, conditional so a redelivery is a no-op.

    Carries `amountPaise` as an integer and NO customer identifier: a settlement is about the
    business bank account, not about any one customer.
    """
    if not settlement_id:
        return
    try:
        dynamodb.Table(PAYMENTS_TABLE).put_item(
            Item={'id': 'SETTLEMENT#' + settlement_id,
                  'recordType': 'SETTLEMENT',
                  'settlementId': settlement_id,
                  'amountPaise': Decimal(amount_paise),
                  'currency': 'INR',
                  'settlementStatus': str(settlement.get('status') or ''),
                  'createdAt': Decimal(int(time.time()))},
            ConditionExpression='attribute_not_exists(id)')
    except Exception as e:  # noqa: BLE001
        if order_keys.is_conditional_failure(e):
            logger.info(json.dumps({'event': 'settlement_record_exists',
                                    'settlementId': settlement_id, 'requestId': request_id}))
            return
        logger.error(json.dumps({'event': 'settlement_record_error',
                                 'settlementId': settlement_id,
                                 'error': type(e).__name__, 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# SUBSCRIPTION EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_subscription_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle subscription.* events."""
    sub = event_data.get('subscription', {}).get('entity', {})
    sub_id = sub.get('id', '')
    plan_id = sub.get('plan_id', '')
    status = sub.get('status', '')
    logger.info(json.dumps({
        'event': event_type, 'subscriptionId': sub_id, 'planId': plan_id, 'status': status, 'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# PAYOUT EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_payout_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle payout.* events. Integer paise, and it finalizes nothing.

    A payout is money LEAVING the business account. It has no order at all, so there is nothing
    here to move forward and the only correctness question is the arithmetic.
    """
    _, payout = payment_status.extract_entity(event_data)
    payout_id = str(payout.get('id') or '')
    try:
        amount_paise = payment_status.paise(payout.get('amount'))
    except (ValueError, ArithmeticError, TypeError):
        logger.error(json.dumps({'event': 'payout_amount_unreadable',
                                 'payoutId': payout_id, 'requestId': request_id}))
        return
    logger.info(json.dumps({
        'event': event_type, 'payoutId': payout_id,
        'amountPaise': amount_paise,                              # INTEGER
        'amountRupees': payment_status.rupees_str(amount_paise),   # STRING, display only
        'status': str(payout.get('status') or ''), 'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# FUND ACCOUNT EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_fund_account(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle fund_account.validation.* events."""
    fa = event_data.get('fund_account', {}).get('entity', event_data.get('fund_account.validation', {}).get('entity', {}))
    fa_id = fa.get('id', '')
    status = fa.get('status', '')
    logger.info(json.dumps({
        'event': event_type, 'fundAccountId': fa_id, 'status': status, 'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# ACCOUNT EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_account_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle account.* events (marketplace/route)."""
    account = event_data.get('account', {}).get('entity', {})
    account_id = account.get('id', '')
    logger.info(json.dumps({
        'event': event_type, 'accountId': account_id, 'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# TOKEN EVENTS
# ═══════════════════════════════════════════════════════════════════

def _handle_token_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle token.service_provider.* events."""
    token = event_data.get('token', {}).get('entity', {})
    token_id = token.get('id', '')
    logger.info(json.dumps({
        'event': event_type, 'tokenId': token_id, 'requestId': request_id,
    }))


# ═══════════════════════════════════════════════════════════════════
# INVOICE EVENTS (Razorpay invoices, not our internal invoices)
# ═══════════════════════════════════════════════════════════════════

def _handle_invoice_event(event_type: str, event_data: Dict, request_id: str) -> None:
    """Handle invoice.* events from Razorpay."""
    invoice = event_data.get('invoice', {}).get('entity', {})
    invoice_id = invoice.get('id', '')
    status = invoice.get('status', '')
    logger.info(json.dumps({
        'event': event_type, 'razorpayInvoiceId': invoice_id, 'status': status, 'requestId': request_id,
    }))


def _start_native_fulfilment(reference_id: str, checkout_mode: str, phone_number_id: str,
                             request_id: str, *, invoice_id: str = '') -> None:
    """Finish the payment-only Meta lifecycle: pending -> processing -> completed.

    Both transitions use the approved ORDER_STATUS template. The completed update is attempted
    only after processing was accepted or the engine reports it is already current. This keeps
    Meta's transition order valid and makes Razorpay webhook redelivery idempotent.
    """
    try:
        from lambda_utils.ecommerce import wa_payment_request
        if not reference_id or checkout_mode not in (
                wa_payment_request.WA_NATIVE_CHECKOUT_MODE,
                wa_payment_request.WA_NATIVE_CART_CHECKOUT_MODE, 'AWS_NATIVE'):
            return
        if not invoice_id:
            items = dynamodb.Table(INVOICES_TABLE).query(
                IndexName='referenceId-index', KeyConditionExpression='referenceId = :ref',
                ExpressionAttributeValues={':ref': reference_id}, Limit=2).get('Items', [])
            if len(items) == 1:
                invoice_id = str(items[0].get('invoiceId') or '')
        if not invoice_id:
            logger.info(json.dumps({'event': 'payment_order_status_skipped',
                                    'referenceId': reference_id, 'reason': 'NO_SINGLE_INVOICE',
                                    'requestId': request_id}))
            return

        processing_status, processing_code = _invoke_order_status(
            invoice_id, 'processing', phone_number_id, request_id,
            event_prefix='order_status_processing',
            description='Payment received.')
        if not (processing_status == 200 or processing_code == 'ORDER_STATUS_UNCHANGED'):
            logger.info(json.dumps({
                'event': 'order_status_completed_blocked',
                'invoiceId': invoice_id,
                'processingStatusCode': processing_status,
                'processingCode': processing_code,
                'requestId': request_id,
            }))
            return

        _invoke_order_status(
            invoice_id, 'completed', phone_number_id, request_id,
            event_prefix='order_status_completed',
            description='Payment complete.')
    except Exception as error:  # noqa: BLE001 - must never mask the receipt step's outcome
        logger.warning(json.dumps({'event': 'payment_order_status_unavailable',
                                   'referenceId': reference_id, 'error': type(error).__name__,
                                   'requestId': request_id}))


#: How long the order_status step may hold up the receipt. The engine's send is one Meta call
#: (about a second); the webhook's own timeout is 60 s and the invoice create, render and send
#: still follow. A timeout here is UNCERTAIN, not failed: the engine may still send, and its
#: one-send claim keeps a redelivery from sending twice.
_FULFILMENT_INVOKE_READ_TIMEOUT_SECONDS = 12
_fulfilment_client = None


def _fulfilment_lambda():
    """A Lambda client for the order_status step: short read timeout, no client-side retry."""
    global _fulfilment_client
    if _fulfilment_client is None:
        from botocore.config import Config
        _fulfilment_client = boto3.client(
            'lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'),
            config=Config(connect_timeout=5,
                          read_timeout=_FULFILMENT_INVOKE_READ_TIMEOUT_SECONDS,
                          retries={'total_max_attempts': 1}))
    return _fulfilment_client


def _send_order_status_processing(invoice_id: str, phone_number_id: str,
                                  request_id: str) -> None:
    """Ask the invoice engine to send the buyer a fulfilment ORDER_STATUS of 'processing'.

    BEST-EFFORT and native-only (`_start_native_fulfilment` gates the checkout mode): it never
    raises. The engine owns idempotency and the 24h messaging window: a 200 reports the channel
    it used; a 409 ORDER_STATUS_UNCHANGED or ORDER_STATUS_IN_FLIGHT means another delivery
    already sent or is sending it; ORDER_STATUS_DEFERRED (window closed, no approved template)
    and ORDER_STATUS_NOT_APPLICABLE are expected verdicts. All outcomes are logged WITHOUT PII -
    only the invoice id, the engine code and the request id.
    """
    if not invoice_id:
        return
    _invoke_order_status(invoice_id, 'processing', phone_number_id, request_id,
                         event_prefix='order_status_processing')


def _invoke_order_status(invoice_id: str, target: str, phone_number_id: str, request_id: str,
                         *, event_prefix: str, description: str = '') -> tuple[int, str]:
    """One fulfilment ORDER_STATUS request to the engine. Returns (HTTP status, engine code).

    Never raises: (0, '') means the engine could not be reached or answered with a function
    error, so the caller cannot tell what happened and must not act on it.
    """
    try:
        # The same commerce runtime the invoice create, render and delivery invokes use, so all
        # post-capture work lands on one engine and one alias. A dedicated, bounded client: this
        # call runs before the receipt, so it must not be able to spend the webhook's budget.
        response = _fulfilment_lambda().invoke(
            FunctionName=COMMERCE_FUNCTION, InvocationType='RequestResponse',
            Payload=json.dumps({
                'rawPath': f'/invoices/{invoice_id}/order-status',
                'requestContext': {'http': {'method': 'POST'}},
                'pathParameters': {'invoiceId': invoice_id},
                'body': json.dumps({'invoiceId': invoice_id, 'orderStatus': target,
                                    'description': description,
                                    'phoneNumberId': phone_number_id or WABA1_PHONE_ID})}))
        if response.get('FunctionError'):
            logger.warning(json.dumps({'event': f'{event_prefix}_invoke_error',
                                       'invoiceId': invoice_id, 'requestId': request_id}))
            return 0, ''
        result = json.loads(response['Payload'].read())
        status_code = int(result.get('statusCode') or 0)
        body = result.get('body') or {}
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (TypeError, ValueError):
                body = {}
        code = str(body.get('code') or body.get('status') or '')
        logger.info(json.dumps({'event': f'{event_prefix}_result',
                                'invoiceId': invoice_id, 'targetStatus': target,
                                'statusCode': status_code, 'code': code,
                                'requestId': request_id}))
        return status_code, code
    except Exception as error:  # noqa: BLE001 - fulfilment hint must not fail a settled capture
        logger.warning(json.dumps({'event': f'{event_prefix}_unavailable',
                                   'invoiceId': invoice_id, 'error': type(error).__name__,
                                   'requestId': request_id}))
        return 0, ''


#: Deferred payment-order updates. The engine parks a status when the approved ORDER_STATUS
#: template cannot be proven available. `orderStatusRetry='PENDING'` puts the invoice in this
#: sparse index keyed by `pendingOrderStatusAt`. Each scheduled run retries the same template-only
#: transport; there is no 24-hour-window or interactive fallback.
_ORDER_STATUS_RETRY_INDEX = 'orderStatusRetry-index'
_ORDER_STATUS_RETRY_PENDING = 'PENDING'
_ORDER_STATUS_RETRY_MIN_AGE_SECONDS = 15 * 60          # at most one retry per 15 minutes
_ORDER_STATUS_RETRY_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # after a week, leave it to staff
_ORDER_STATUS_RETRY_LIMIT = 10                          # per run
_ORDER_STATUS_RETRY_BUDGET_SECONDS = 15
#: Engine verdicts that make a parked update moot: the order already has that status, can no
#: longer move to it, or never had a Meta order. Retrying them would never succeed.
_ORDER_STATUS_RETRY_MOOT = frozenset({
    'ORDER_STATUS_UNCHANGED', 'ORDER_STATUS_TRANSITION_INVALID', 'ORDER_STATUS_NOT_APPLICABLE',
    'ORDER_STATUS_NOT_ALLOWED', 'ORDER_NOT_PAID'})


def _clear_order_status_retry(invoice_id: str, target: str, now: int, *, reason: str,
                              request_id: str) -> bool:
    """Take one invoice out of the retry index, only while it still waits on `target`."""
    try:
        dynamodb.Table(INVOICES_TABLE).update_item(
            Key={'invoiceId': invoice_id},
            UpdateExpression=('REMOVE orderStatusRetry '
                              'SET pendingOrderStatusRetryEndedAt = :now, '
                              'pendingOrderStatusRetryEndReason = :reason'),
            ConditionExpression='orderStatusRetry = :pending AND pendingOrderStatus = :target',
            ExpressionAttributeValues={':pending': _ORDER_STATUS_RETRY_PENDING, ':target': target,
                                       ':now': now, ':reason': reason})
        return True
    except Exception as error:  # noqa: BLE001 - a lost race means someone else resolved it
        if 'ConditionalCheckFailed' not in type(error).__name__ + str(error):
            logger.warning(json.dumps({'event': 'order_status_retry_clear_failed',
                                       'invoiceId': invoice_id, 'error': type(error).__name__,
                                       'requestId': request_id}))
        return False


def _retry_deferred_order_status(request_id: str) -> Dict[str, Any]:
    """Retry fulfilment updates the engine deferred. Bounded, scan-free and never raises."""
    from boto3.dynamodb.conditions import Key

    now = int(time.time())
    deadline = time.time() + _ORDER_STATUS_RETRY_BUDGET_SECONDS
    counts = {'candidates': 0, 'sent': 0, 'deferred': 0, 'moot': 0, 'abandoned': 0,
              'unknown': 0, 'errors': 0}
    try:
        page = dynamodb.Table(INVOICES_TABLE).query(
            IndexName=_ORDER_STATUS_RETRY_INDEX,
            KeyConditionExpression=(
                Key('orderStatusRetry').eq(_ORDER_STATUS_RETRY_PENDING)
                & Key('pendingOrderStatusAt').lte(now - _ORDER_STATUS_RETRY_MIN_AGE_SECONDS)),
            Limit=_ORDER_STATUS_RETRY_LIMIT)
    except Exception as error:  # noqa: BLE001 - the index may not exist yet; nothing to retry
        counts['errors'] += 1
        logger.warning(json.dumps({'event': 'order_status_retry_query_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))
        return counts
    for row in page.get('Items') or []:
        if time.time() > deadline:
            break  # the rest wait for the next run
        invoice_id = str(row.get('invoiceId') or '')
        target = str(row.get('pendingOrderStatus') or '')
        if not invoice_id or not target:
            continue
        counts['candidates'] += 1
        since = int(row.get('pendingOrderStatusSince') or row.get('pendingOrderStatusAt') or now)
        if now - since > _ORDER_STATUS_RETRY_MAX_AGE_SECONDS:
            if _clear_order_status_retry(invoice_id, target, now, reason='expired',
                                         request_id=request_id):
                counts['abandoned'] += 1
                # Kept visible: `pendingOrderStatus` stays on the invoice for staff.
                logger.warning(json.dumps({'event': 'order_status_retry_abandoned',
                                           'invoiceId': invoice_id, 'targetStatus': target,
                                           'requestId': request_id}))
            continue
        status_code, code = _invoke_order_status(invoice_id, target, WABA1_PHONE_ID, request_id,
                                                 event_prefix='order_status_retry')
        if status_code == 200:
            counts['sent'] += 1  # the engine removed the retry markers itself
        elif code == 'ORDER_STATUS_DEFERRED':
            counts['deferred'] += 1  # re-parked by the engine with a fresh pendingOrderStatusAt
        elif code in _ORDER_STATUS_RETRY_MOOT:
            counts['moot'] += 1
            _clear_order_status_retry(invoice_id, target, now, reason=code,
                                      request_id=request_id)
        else:
            counts['unknown'] += 1  # in flight, rejected or unreachable: try again next run
    logger.info(json.dumps({'event': 'order_status_retry_complete', 'requestId': request_id,
                            **counts}))
    return counts


#: The stale-attempt sweep's bounds. A Razorpay webhook that never arrives (a provider delivery
#: that was dropped before this function ever saw it) leaves an attempt stuck IN-FLIGHT with money
#: possibly already captured at the gateway. The sweep is the safety net: it reconciles such
#: attempts from the PROVIDER'S own API, never from any event body. Bounded so it cannot turn into
#: a wide scan - a short window and a small page per status.
_SWEEP_MIN_AGE_SECONDS = 120          # younger than this is still a live checkout; leave it alone
_SWEEP_MAX_AGE_SECONDS = 24 * 60 * 60  # older than this is beyond the recovery horizon
_SWEEP_PAGE_LIMIT = 25                 # per status, per run
#: Wall-clock budget for one run. The function's timeout is 60 s and the sweep rides the same
#: invocation as the customer-link reconcile, so it stops starting new provider lookups after this
#: and leaves the rest for the next 5-minute run.
_SWEEP_TIME_BUDGET_SECONDS = 30


#: The in-flight statuses a capture can still be missing from. The invoice leg stays
#: PAYMENT_READINESS_CHECKED after sending, so it is included.
_RECONCILABLE_STATUSES = ('PAYMENT_REQUEST_SENT', 'PAYMENT_PENDING', 'PAYMENT_READINESS_CHECKED')


def _reconcile_in_flight_attempt(attempt: Dict[str, Any], keys_table: Any,
                                 request_id: str) -> str:
    """Settle ONE in-flight attempt from the provider's own records. Never raises.

    The shared body of the scheduled sweep and the Meta-payment trigger. It asks the right
    PROVIDER whether exactly one capture exists:

      * website mode with a stored providerOrderId -> Razorpay `GET /orders/{id}/payments`
        (`razorpay_verify.order_is_paid`).
      * native modes -> Meta payment lookup by our reference id
        (`meta_payment_binding.lookup_payment`), which returns the gateway order/payment ids.

    When exactly one captured payment id is found it reconstructs a minimal payment ENTITY from
    the AUTHENTICATED Razorpay readback (`payment_capture_details`) and runs the normal
    `_handle_payment_captured` path, which re-resolves the reference from the stored provider
    binding and RE-VERIFIES against Razorpay before any paid state is written. The reconstructed
    entity is a trigger, not evidence, so this is not a second paid-state producer.

    Returns the outcome word the sweep counts: skipped_paid, skipped, no_capture, reconciled,
    provider_unavailable or errors.
    """
    from lambda_utils.ecommerce import wa_payment_request, website_checkout
    from lambda_utils.integrations import meta_payment_binding, razorpay_verify

    # Skip anything that has since reached a terminal/paid state (a redelivery or the browser
    # path may have settled it between the read and here).
    if (str(attempt.get('status') or '') not in _RECONCILABLE_STATUSES
            or attempt.get('finalizationStage') == 'ORDER_FINALIZED'
            or attempt.get('paidAt')):
        return 'skipped_paid'
    reference_id = str(attempt.get('referenceId') or '')
    checkout_mode = str(attempt.get('checkoutMode') or '')
    if not reference_id:
        return 'skipped'
    try:
        captured_payment_id = ''
        if checkout_mode == website_checkout.CHECKOUT_MODE_WEBSITE:
            provider_order_id = str(attempt.get('providerOrderId') or '')
            if not provider_order_id:
                return 'skipped'
            paid, pay_id, _amount, _currency = razorpay_verify.order_is_paid(provider_order_id)
            if paid and pay_id:
                captured_payment_id = pay_id
        elif (checkout_mode in wa_payment_request.NATIVE_CHECKOUT_MODES
              or checkout_mode == 'AWS_NATIVE'):
            # The sender phone and configuration live on OUR `PAYREF#` row (the binding's
            # configuration source `_load_attempt` reads); cart and catalog-service attempts do
            # not copy `phoneId` onto the attempt.
            reference_row = order_keys.resolve_payment_reference(keys_table, reference_id) or {}
            found = meta_payment_binding.lookup_payment(
                reference_id=reference_id,
                phone_number_id=str(reference_row.get('phoneId') or attempt.get('phoneId') or ''),
                config_name=str(reference_row.get('configurationName')
                                or attempt.get('configurationName') or ''))
            captured_payment_id = str(found.get('gatewayPaymentId') or '')
            if not captured_payment_id:
                # Meta reported a captured ORDER but no explicit payment id. Resolve the single
                # captured payment id from the Razorpay order so the normal path can re-verify a
                # payment entity.
                order_paid, pay_id, _a, _c = razorpay_verify.order_is_paid(
                    str(found.get('gatewayOrderId') or ''))
                if order_paid and pay_id:
                    captured_payment_id = pay_id
        else:
            return 'skipped'

        if not captured_payment_id:
            return 'no_capture'

        captured, amount_paise, currency, provider_order_id = (
            razorpay_verify.payment_capture_details(captured_payment_id))
        if not captured:
            return 'no_capture'
        # `notes.referenceId` is OUR reference, read off our own attempt row. A native attempt
        # whose webhook never arrived has no stored gateway binding yet, so without it the
        # captured path could not find the attempt and would quarantine the payment instead of
        # binding it through the Meta lookup.
        entity = {'id': captured_payment_id, 'order_id': provider_order_id,
                  'status': razorpay_verify.CAPTURED, 'amount': amount_paise,
                  'currency': currency, 'notes': {'referenceId': reference_id}}
        _handle_payment_captured({'payment': {'entity': entity}}, request_id)
        return 'reconciled'
    except razorpay_verify.RazorpayUnavailable:
        return 'provider_unavailable'
    except meta_payment_binding.MetaBindingUnavailable:
        # Not a confirmation of payment; just nothing to reconcile from Meta.
        return 'no_capture'
    except Exception as error:  # noqa: BLE001 - one attempt must not stop the caller
        logger.warning(json.dumps({'event': 'reconcile_attempt_failed',
                                   'referenceId': reference_id,
                                   'error': type(error).__name__, 'requestId': request_id}))
        return 'errors'


#: Our payment reference shape (`WD-PAY-` + base32), checked before any lookup so the
#: Meta-payment trigger cannot be made to address arbitrary keys.
_REFERENCE_RE = re.compile(r'^WD-PAY-[A-Z0-9]{6,32}$')


def _reconcile_reference(reference_id: str, request_id: str) -> Dict[str, Any]:
    """Settle the ONE attempt behind a reference, now. The Meta-payment-webhook trigger.

    Meta's payment status webhook is advisory and creates no paid state; when it reports a
    capture, inbound asks for this instead of waiting for the next 5-minute sweep. The attempt
    is resolved from OUR `PAYREF#` row, and settlement still comes only from the provider
    readback in `_reconcile_in_flight_attempt`. Never raises.
    """
    reference_id = str(reference_id or '').strip()
    if not _REFERENCE_RE.fullmatch(reference_id):
        return {'outcome': 'invalid_reference'}
    try:
        keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)
        payref = order_keys.resolve_payment_reference(keys_table, reference_id) or {}
        attempt_id = str(payref.get('paymentAttemptId') or '')
        if not attempt_id:
            return {'outcome': 'no_attempt'}
        attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
            Key={'paymentAttemptId': attempt_id}, ConsistentRead=True).get('Item') or {}
        if not attempt:
            return {'outcome': 'no_attempt'}
        outcome = _reconcile_in_flight_attempt(attempt, keys_table, request_id)
    except Exception as error:  # noqa: BLE001 - a trigger must never fail its caller
        logger.warning(json.dumps({'event': 'reconcile_reference_failed',
                                   'referenceId': reference_id, 'error': type(error).__name__,
                                   'requestId': request_id}))
        outcome = 'errors'
    logger.info(json.dumps({'event': 'reconcile_reference_complete', 'referenceId': reference_id,
                            'outcome': outcome, 'requestId': request_id}))
    return {'outcome': outcome}


def _sweep_stale_attempts(request_id: str) -> Dict[str, Any]:
    """Reconcile in-flight attempts whose Razorpay capture webhook never arrived.

    Bounded, provider-authoritative, and NEVER raises out: a failure here must not fail the
    schedule it rides on. For each candidate attempt (status in-flight, aged into the recovery
    window) it asks the right PROVIDER for whether exactly one capture exists:

      * website mode with a stored providerOrderId -> Razorpay `GET /orders/{id}/payments`
        (`razorpay_verify.order_is_paid`).
      * native modes -> Meta payment lookup by our reference id
        (`meta_payment_binding.lookup_payment`), which returns the gateway order/payment ids.

    When exactly one captured payment id is found it reconstructs a minimal payment ENTITY from
    the AUTHENTICATED Razorpay readback (`payment_capture_details`: status, amount, currency,
    order_id) and runs the normal `_handle_payment_captured({'payment': {'entity': entity}})`
    path. That path re-resolves the reference from the stored provider binding (never the body)
    and RE-VERIFIES against Razorpay through `_create_order_for_captured_payment` before any paid
    state is written, so the reconstructed entity is a trigger, not trusted evidence. Attempts
    already PAID/finalized are skipped. One summary line is emitted; metrics are best-effort.
    The per-attempt work is `_reconcile_in_flight_attempt`, shared with the Meta-payment trigger.
    """
    from boto3.dynamodb.conditions import Key
    from lambda_utils.ecommerce import payment_attempt

    now = int(time.time())
    deadline = time.time() + _SWEEP_TIME_BUDGET_SECONDS
    low = now - _SWEEP_MAX_AGE_SECONDS
    high = now - _SWEEP_MIN_AGE_SECONDS
    counts = {'scanned': 0, 'skipped_paid': 0, 'no_capture': 0, 'reconciled': 0,
              'provider_unavailable': 0, 'errors': 0, 'deferred': 0}
    keys_table = dynamodb.Table(COMMERCE_KEYS_TABLE)
    # The invoice leg stays PAYMENT_READINESS_CHECKED after sending, so it is swept too.
    statuses = (payment_attempt.PAYMENT_REQUEST_SENT, payment_attempt.PAYMENT_PENDING,
                payment_attempt.PAYMENT_READINESS_CHECKED)
    attempts_table = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE)
    try:
        for status in statuses:
            try:
                page = attempts_table.query(
                    IndexName='status-index',
                    KeyConditionExpression=(Key('status').eq(status)
                                            & Key('createdAt').between(low, high)),
                    Limit=_SWEEP_PAGE_LIMIT)
            except Exception as error:  # noqa: BLE001
                counts['errors'] += 1
                logger.warning(json.dumps({'event': 'sweep_status_query_failed',
                                           'status': status, 'error': type(error).__name__,
                                           'requestId': request_id}))
                continue
            for attempt in page.get('Items') or []:
                if time.time() > deadline:
                    # Out of budget: leave the remainder for the next scheduled run.
                    counts['deferred'] += 1
                    continue
                counts['scanned'] += 1
                outcome = _reconcile_in_flight_attempt(attempt, keys_table, request_id)
                if outcome in counts:
                    counts[outcome] += 1
    except Exception as error:  # noqa: BLE001 - the sweep itself must never raise
        counts['errors'] += 1
        logger.error(json.dumps({'event': 'sweep_stale_attempts_error',
                                 'error': type(error).__name__, 'requestId': request_id}))
    logger.info(json.dumps({'event': 'sweep_stale_attempts_complete',
                            'requestId': request_id, **counts}))
    _emit_sweep_metrics(counts, request_id)
    return counts


def _emit_sweep_metrics(counts: Dict[str, Any], request_id: str) -> None:
    """Publish the stale-attempt sweep's health to CloudWatch. Best-effort, never raises."""
    global _cloudwatch
    try:
        if _cloudwatch is None:
            _cloudwatch = boto3.client(
                'cloudwatch', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        _cloudwatch.put_metric_data(Namespace='WeCare/CustomerOrderLink', MetricData=[
            {'MetricName': 'SweepScanned', 'Value': float(counts['scanned']), 'Unit': 'Count'},
            {'MetricName': 'SweepReconciled', 'Value': float(counts['reconciled']),
             'Unit': 'Count'},
            {'MetricName': 'SweepProviderUnavailable',
             'Value': float(counts['provider_unavailable']), 'Unit': 'Count'},
            {'MetricName': 'SweepErrors', 'Value': float(counts['errors']), 'Unit': 'Count'},
        ])
    except Exception as error:  # noqa: BLE001 - telemetry must not break the sweep
        logger.warning(json.dumps({'event': 'sweep_metrics_emit_failed',
                                   'error': type(error).__name__, 'requestId': request_id}))


# ═══════════════════════════════════════════════════════════════════
# RESPONSE HELPER
# ═══════════════════════════════════════════════════════════════════

def _response(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Razorpay-Signature',
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body, default=str),
    }
