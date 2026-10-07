"""
Razorpay Webhook Handler Lambda Function

Purpose: Process ALL Razorpay webhook events
Webhook URL: https://api.wecare.digital/razorpay-webhook

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
import boto3
from typing import Dict, Any, Optional
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.logging import get_logger
from lambda_utils import payment_status  # monotonic status, one vocabulary, dedup key
from lambda_utils.privacy import mask_phone  # a full number must never reach CloudWatch

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

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
    someone republished the function. See .kiro/steering/lambda-snapstart-deploy.md.

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
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
WEBHOOK_LOG_TABLE = os.environ.get('WEBHOOK_LOG_TABLE', 'stack-wecare-digital-RazorpayWebhookLogTable')


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process ALL Razorpay webhook events."""
    request_id = context.aws_request_id if context else 'local'
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
    somebody read the history. And it does not perform the downstream side effects - Wix order,
    transaction record, receipt, confirmation - which are separately guarded so that a failure in
    the last one does not re-run the first.

    Never raises. A failure to create the order must not fail the webhook, because a non-2xx makes
    Razorpay retry the whole event and the lease above already handles recovery.
    """
    try:
        from lambda_utils.ecommerce import order_channel, order_creation, order_keys
        from lambda_utils.integrations import razorpay_verify

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
            # the payment request was built from the Wix checkout. Reading them from the webhook
            # instead would make the comparison compare the event against itself.
            attribution['channel'] = row.get('channel', '')
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
        return {
            **outcome.as_dict(),
            'channel': order_channel.canonical(attribution.get('channel')),
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
    """Settle a Section 5 voluntary blog contribution — bound, verified, once, and no Wix order.

    Mirrors ``_handle_wallet_topup_captured`` exactly, for the BLOG_CONTRIBUTION purpose:

      1. A STORED contribution record must exist for the ``contributionId`` the notes name. No
         record -> not an authorised contribution -> settle nothing, quarantine. The notes are
         never the authority.
      2. The amount is RE-DERIVED from the stored record and VERIFIED against Razorpay's API
         (``payment_is_captured``), never read from the event body, and must equal the stored
         record's amount in INR to the paise.
      3. A conditional one-time claim keyed by the payment id is made BEFORE the settle, so a
         duplicate delivery settles exactly once.

    A BLOG_CONTRIBUTION capture creates NO Wix Store product or order. Never raises: a non-2xx
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


def _handle_payment_captured(event_data: Dict, request_id: str) -> None:
    """Handle payment.captured — the main success event. Store payment + mark invoice paid + trigger invoice."""
    payment = event_data.get('payment', {}).get('entity', {})
    payment_id = payment.get('id', '')
    amount_paise = int(payment.get('amount', 0))
    amount_rupees = amount_paise / 100
    currency = payment.get('currency', 'INR')
    order_id = payment.get('order_id', '')
    method = payment.get('method', '')
    contact = payment.get('contact', '')
    email = payment.get('email', '')
    description = payment.get('description', '')
    notes = payment.get('notes', {})

    # Partner prepaid wallet top-up (customer-service): if this payment was created for
    # a wallet top-up, credit the tenant's wallet and stop (not an invoice payment).
    if (notes or {}).get('purpose') == 'wallet_topup' and (notes or {}).get('wabaId'):
        _handle_wallet_topup_captured(payment, request_id)
        return

    # Section 5 voluntary blog contribution (BLOG_CONTRIBUTION): settle the stored contribution
    # record and stop. This is NOT an invoice payment and must NOT create a Wix Store product or
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
    
    # If still not found, try Meta Payment Lookup API using the Razorpay order_id
    # The reference_id is always in the Meta payment record even if Razorpay notes are empty
    if not reference_id and order_id:
        try:
            reference_id = _lookup_reference_id_from_meta(order_id, contact, request_id)
        except Exception as lookup_err:
            # A17: type only. A lookup error message can echo request content.
            logger.warning(json.dumps({
                'event': 'meta_lookup_for_ref_failed',
                'orderId': order_id,
                'error': type(lookup_err).__name__,
                'requestId': request_id,
            }))

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
    # money-confirmed payment record, an invoice-paid write, the receipt/post-payment run, the
    # CTWA purchase attribution, or the order_status confirmation to the customer.
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
    _post_payment_handler(payment_id, amount_rupees, currency, contact, email, description, notes, request_id,
                          channel=str((outcome or {}).get('channel') or ''))

    # Conversions API: if this conversation started from a Click-to-WhatsApp ad,
    # log a Purchase event to Meta so the ad campaign can optimize/measure. No-op
    # (returns 400, just logged) for non-ad conversations. Fire-and-forget.
    _log_ctwa_purchase(contact, amount_rupees, currency, order_id, notes, request_id)

    # Send order_status message to customer (GAP FIX: Razorpay webhook was not sending this)
    if contact and reference_id:
        try:
            clean_phone = (contact or '').replace('+', '').replace(' ', '').replace('-', '')
            if not clean_phone.startswith('91') and len(clean_phone) == 10:
                clean_phone = f'91{clean_phone}'

            # Resolve which phone sent the original payment — look up from invoice
            originating_phone_id = ''
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
            resolved_phone = _resolve_originating_phone(reference_id, _inv)
            if resolved_phone:
                originating_phone_id = resolved_phone
            else:
                # All three authoritative lookups failed. There is no second
                # signal to fall back on: the payment configuration name used to
                # identify the WABA (WABA1 was hyphenated, WABA2 was not), but
                # Meta rebuilt the configs on 2026-08-23 and both WABAs now
                # expose the IDENTICAL pair WECAREDIGITAL / WECAREUPI. The old
                # 'WECARE-'/'UPIVPA' substring test therefore matched nothing and
                # always landed on Phone 2 - it only looked like a decision.
                #
                # The fall-through is now the PRIMARY identity. Phone 2 is
                # marked `paymentProtected: true` and the UI gates it behind an
                # admin authorization step before payments may be sent from it,
                # so defaulting to it server-side bypassed that check.
                originating_phone_id = 'phone-number-id-waba1-direct-1016149501586345'
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

            order_status_payload = {
                'body': json.dumps({
                    'recipientPhone': f'+{clean_phone}',
                    'phoneNumberId': originating_phone_id,
                    'isOrderStatus': True,
                    'orderStatusDetails': {
                        'reference_id': reference_id,
                        'order_status': 'completed',
                        'amount': amount_rupees,
                        'description': f'Payment of \u20b9{amount_rupees:.2f} received via Razorpay. Thank you!'
                    }
                })
            }
            lambda_client.invoke(
                FunctionName=os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp'),
                InvocationType='Event',
                Payload=json.dumps(order_status_payload),
            )
            logger.info(json.dumps({'event': 'razorpay_order_status_sent', 'phone': mask_phone(clean_phone), 'referenceId': reference_id, 'phoneId': originating_phone_id, 'requestId': request_id}))

            # Post-payment flow: after payment is confirmed, optionally start a
            # WhatsApp Flow (e.g. submit-request) so the customer completes service
            # details for the order they just paid for. One flow per payment (idempotent).
            _trigger_post_payment_flow(clean_phone, originating_phone_id, reference_id, notes,
                                       request_id, invoice_id=originating_invoice_id,
                                       display={'order_number': str(order_display_number),
                                                'payment_id': str(payment_id or ''),
                                                'amount': f'\u20b9{amount_rupees:.2f}',
                                                'product': str(order_product)})
        except Exception as e:
            # A17: type only. A ClientError message can echo request content.
            logger.warning(json.dumps({'event': 'razorpay_order_status_error', 'error': type(e).__name__, 'requestId': request_id}))


# Map phone-number-id -> WABA id (for building routable flow tokens)
_PHONE_ID_TO_WABA = {
    'phone-number-id-waba1-direct-1016149501586345': '2094615664435155',
    'phone-number-id-waba-t-direct-1055232054343117': '2513394156072604',
}


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


def _log_ctwa_purchase(contact: str, amount_rupees: float, currency: str,
                       order_id: str, notes: Dict, request_id: str) -> None:
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
            'value': round(float(amount_rupees or 0), 2),
            'currency': currency or 'INR',
            'orderId': order_id or (notes or {}).get('referenceId', ''),
        }
        if waba_id:
            payload['wabaId'] = waba_id
        event = {
            'requestContext': {'http': {'method': 'POST', 'path': '/wa-business/capi/event'}},
            'rawPath': '/wa-business/capi/event',
            'body': json.dumps(payload),
        }
        lambda_client.invoke(
            FunctionName=os.environ.get('WA_BUSINESS_FUNCTION', 'wecare-whatsapp-business-api'),
            InvocationType='Event',  # async, fire-and-forget
            Payload=json.dumps(event),
        )
        logger.info(json.dumps({'event': 'ctwa_purchase_event_dispatched',
                                'phone': phone[-4:], 'amount': amount_rupees,
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


def _trigger_post_payment_flow(clean_phone: str, phone_id: str, reference_id: str,
                               notes: Dict, request_id: str, invoice_id: str = '',
                               display: Dict = None) -> None:
    """After a payment is captured, send a WhatsApp Flow so the customer completes
    post-payment details. Fires only when a flow is configured:
      1) notes.postPaymentFlowId (per-order, explicit) — highest priority
      2) env POST_PAYMENT_FLOW_WABA1 / POST_PAYMENT_FLOW_WABA2 (per-WABA default)
    If none is configured, this is a no-op (so simple bills / wallet top-ups are unaffected).

    ONE FLOW PER PAYMENT: enforced idempotently via a conditional write of
    postPaymentFlowSentAt on the invoice record — duplicate/retried webhooks for
    the same order will not re-send the flow.
    The flow token embeds the reference_id + phone so the submission links to the order."""
    import uuid as _uuid
    try:
        waba_id = _PHONE_ID_TO_WABA.get(phone_id, '')
        # ── Flow resolution chain ──
        # 1) explicit notes.postPaymentFlowId (per-order override) — highest priority
        # 2) catalog product → flow map (each product opens its OWN flow)
        # 3) per-WABA default env
        flow_id = (notes or {}).get('postPaymentFlowId') or (notes or {}).get('post_payment_flow_id')
        mapped = {}
        if not flow_id:
            retailer_id = ((notes or {}).get('catalogRetailerId')
                           or (notes or {}).get('retailer_id') or '')
            if retailer_id:
                try:
                    _cfg_tbl = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
                    _cfg = dynamodb.Table(_cfg_tbl).get_item(Key={'id': 'catalog_flow_map'}).get('Item') or {}
                    _cmap = json.loads(_cfg.get('configValue') or '{}')
                    mapped = _cmap.get(retailer_id) or {}
                    flow_id = mapped.get('flowIdWaba1' if waba_id == '2094615664435155' else 'flowIdWaba2') or ''
                    if flow_id:
                        logger.info(json.dumps({'event': 'post_payment_flow_mapped', 'retailerId': retailer_id,
                                                'flowId': flow_id, 'requestId': request_id}))
                except Exception as _me:
                    logger.warning(json.dumps({'event': 'catalog_flow_map_error', 'error': str(_me),
                                               'requestId': request_id}))
        if not flow_id:
            if waba_id == '2094615664435155':
                flow_id = os.environ.get('POST_PAYMENT_FLOW_WABA1', '')
            elif waba_id == '2513394156072604':
                flow_id = os.environ.get('POST_PAYMENT_FLOW_WABA2', '')
        if not flow_id:
            logger.info(json.dumps({'event': 'post_payment_flow_skipped', 'reason': 'no flow configured',
                                    'referenceId': reference_id, 'requestId': request_id}))
            return

        # One-time guard: mark the invoice as "flow sent" only if not already set.
        # If the conditional write fails, a flow was already sent for this payment/order.
        if invoice_id:
            try:
                import time as _time
                dynamodb.Table(INVOICES_TABLE).update_item(
                    Key={'invoiceId': invoice_id},
                    UpdateExpression='SET postPaymentFlowSentAt = :now',
                    ConditionExpression='attribute_not_exists(postPaymentFlowSentAt)',
                    ExpressionAttributeValues={':now': int(_time.time())},
                )
            except Exception as guard_err:
                if 'ConditionalCheckFailedException' in str(guard_err):
                    logger.info(json.dumps({'event': 'post_payment_flow_skipped', 'reason': 'already sent (idempotent)',
                                            'invoiceId': invoice_id, 'referenceId': reference_id, 'requestId': request_id}))
                    return
                # Non-conditional error (e.g. table/key issue) — log and continue to send once
                logger.warning(json.dumps({'event': 'post_payment_flow_guard_error', 'error': str(guard_err),
                                           'invoiceId': invoice_id, 'requestId': request_id}))

        # Data-exchange flow needs the referenceId so the flow-data endpoint can
        # server-fetch the order + payment. We embed it (hex, hyphen-safe) in the
        # token: postpay-{hexRef}-waba-{1|2}-ph-{phone}. Requires a referenceId.
        if not reference_id:
            logger.info(json.dumps({'event': 'post_payment_flow_skipped', 'reason': 'no reference_id',
                                    'requestId': request_id}))
            return
        waba_suffix = '1' if waba_id == '2094615664435155' else '2'
        hexref = reference_id.encode('utf-8').hex()
        flow_token = f'postpay-{hexref}-waba-{waba_suffix}-ph-{clean_phone}'
        cta = ((notes or {}).get('postPaymentFlowCta') or mapped.get('cta') or 'Complete details')[:20]
        body_text = ((notes or {}).get('postPaymentFlowBody') or mapped.get('body')
                     or 'Thank you for your payment! Please tap below to complete your order details.')
        # Launch as NAVIGATE with the order/payment data pre-filled by the server so
        # the flow opens INSTANTLY (no endpoint round-trip on open). The DETAILS screen
        # footer still uses data_exchange, so the submit is saved server-side (idempotent).
        disp = display or {}
        # Customer-facing Request ID — shown on the flow's success screen and saved
        # with the submission (unique per payment).
        service_request_id = 'WD-SR-' + _uuid.uuid4().hex[:8].upper()
        # Pre-fill the flow's Address screen from the customer's saved address.
        cust_name = ''
        addr = {'line': '', 'city': '', 'state': '', 'pin': '', 'landmark': ''}
        within_window = True  # catalog path is in-window; assume yes unless we learn otherwise
        try:
            import time as _t
            _ct = dynamodb.Table(os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable'))
            _c = _ct.get_item(Key={'id': f'wa{clean_phone}'}).get('Item') or {}
            cust_name = _c.get('contactBookName') or _c.get('name') or ''
            addr = {
                'line': _c.get('addressLine1') or '', 'city': _c.get('city') or '',
                'state': _c.get('state') or '', 'pin': str(_c.get('postalCode') or ''),
                'landmark': _c.get('landmark') or '',
            }
            _li = int(_c.get('lastInboundMessageAt') or 0)
            if _li:
                within_window = (int(_t.time()) - _li) < 24 * 3600
        except Exception:
            pass
        flow_data = {
            'request_id': service_request_id,
            'order_number': str(disp.get('order_number', reference_id)),
            'product': str(disp.get('product', 'Your order')),
            'amount': str(disp.get('amount', '')),
            'cust_name': cust_name,
            'addr_line': addr['line'], 'addr_city': addr['city'], 'addr_state': addr['state'],
            'addr_pin': addr['pin'], 'addr_landmark': addr['landmark'],
        }
        # Persist the Request ID on the invoice so the saved submission correlates.
        if invoice_id:
            try:
                dynamodb.Table(INVOICES_TABLE).update_item(
                    Key={'invoiceId': invoice_id},
                    UpdateExpression='SET serviceRequestId = :r',
                    ExpressionAttributeValues={':r': service_request_id})
            except Exception:
                pass
        if within_window:
            # In-window (catalog path): send as a DIRECT flow message (navigate →
            # SUMMARY, data pre-filled) for an instant open.
            flow_payload = {
                'body': json.dumps({
                    'recipientPhone': f'+{clean_phone}',
                    'phoneNumberId': phone_id,
                    'isInteractive': True,
                    'interactiveType': 'flow',
                    'interactiveData': {
                        'flowId': str(flow_id),
                        'flowToken': flow_token,
                        'flowCta': cta,
                        'flowAction': 'navigate',
                        'screenId': 'SUMMARY',
                        'flowData': flow_data,
                        'body': body_text,
                    },
                })
            }
            send_mode = 'flow_message'
        else:
            # Outside the 24h window (e.g. payment link paid days later): send the
            # approved UTILITY template whose FLOW button opens the same flow.
            tmpl_name = os.environ.get('POST_PAYMENT_REQUEST_TEMPLATE', 'postpay_request_v1')
            flow_payload = {
                'body': json.dumps({
                    'recipientPhone': f'+{clean_phone}',
                    'phoneNumberId': phone_id,
                    'isTemplate': True,
                    'templateName': tmpl_name,
                    'templateParams': ['en'],
                    'flowButton': {'index': 0, 'flowActionData': flow_data},
                })
            }
            send_mode = 'flow_template'
        lambda_client.invoke(
            FunctionName=os.environ.get('OUTBOUND_FUNCTION', 'wecare-outbound-whatsapp'),
            InvocationType='Event',
            Payload=json.dumps(flow_payload),
        )
        logger.info(json.dumps({'event': 'post_payment_flow_sent', 'phone': mask_phone(clean_phone),
                                'flowId': str(flow_id), 'serviceRequestId': service_request_id,
                                'sendMode': send_mode, 'withinWindow': within_window,
                                'referenceId': reference_id, 'phoneId': phone_id, 'requestId': request_id}))
    except Exception as e:
        logger.warning(json.dumps({'event': 'post_payment_flow_error', 'error': str(e),
                                   'referenceId': reference_id, 'requestId': request_id}))


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
    notes = payment.get('notes', {})
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
# META PAYMENT LOOKUP FOR REFERENCE_ID RECOVERY
# ═══════════════════════════════════════════════════════════════════

def _lookup_reference_id_from_meta(razorpay_order_id: str, contact_phone: str, request_id: str) -> str:
    """When Razorpay notes don't contain referenceId, try to find it via Meta Payment Lookup.
    
    Strategy: scan our PaymentsTable or InboundTable for a payment_request record
    that matches the customer phone, then use its referenceId to call Meta Lookup API.
    If Meta confirms the payment is captured for that referenceId, we have our match.
    
    Fallback: scan InvoicesTable for pending invoices for this customer phone.
    """
    clean_phone = (contact_phone or '').replace('+', '').replace(' ', '').replace('-', '')
    if not clean_phone:
        return ''
    
    # Normalize to 10-digit Indian local
    local_phone = clean_phone[2:] if clean_phone.startswith('91') and len(clean_phone) == 12 else (clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone)
    
    try:
        # Check InvoicesTable for pending invoices for this customer
        inv_table = dynamodb.Table(INVOICES_TABLE)
        # Scan for pending invoices (not ideal but reference_id recovery is rare)
        result = inv_table.scan(
            FilterExpression='#st IN (:s1, :s2, :s3)',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={':s1': 'created', ':s2': 'pending_payment', ':s3': 'sent'},
        )
        for inv in result.get('Items', []):
            inv_phone = (inv.get('customerPhone', '') or '').replace('+', '').replace(' ', '').replace('-', '')
            inv_local = inv_phone[2:] if inv_phone.startswith('91') and len(inv_phone) == 12 else (inv_phone[-10:] if len(inv_phone) >= 10 else inv_phone)
            if inv_local == local_phone and inv.get('referenceId'):
                ref = inv['referenceId']
                logger.info(json.dumps({
                    'event': 'reference_id_recovered_from_invoice',
                    'referenceId': ref,
                    'invoiceId': inv.get('invoiceId', ''),
                    'razorpayOrderId': razorpay_order_id,
                    'requestId': request_id,
                }))
                return ref
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'reference_id_recovery_scan_error',
            'error': str(e),
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

    amount_paise = int(payment.get('amount') or 0)
    amount_rupees = amount_paise / 100

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
        'amount': Decimal(str(amount_paise)),
        'amountInRupees': Decimal(str(amount_rupees)),
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
        if 'ConditionalCheckFailedException' in str(e):
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
            if 'ConditionalCheckFailedException' in str(cond_err):
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


def _post_payment_handler(payment_id: str, amount: float, currency: str, contact: str,
                          email: str, description: str, notes: Dict, request_id: str,
                          *, channel: str = '') -> None:
    """
    After payment captured (Razorpay webhook path):
    This is the BACKUP path — WhatsApp inbound handler is the primary invoice generator.
    1. Invoke invoice-engine to create invoice from payment (dedup will return existing if WhatsApp path already created it)
    2. Generate invoice image (POS receipt style) — for internal reference
    3. Generate PDF (async) — for internal reference
    4. NO WhatsApp send — WhatsApp path handles customer delivery

    `channel` is WHERE the order came from (`website` / `whatsapp`), read off the `PAYREF#` row by
    the reconciliation above. KEYWORD-ONLY and defaulted so the legacy callers that pass eight
    positional arguments are unaffected, and so omitting it is a silent, correct `website` rather
    than a TypeError on a path where the money has already moved.
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
                'itemName': description or notes.get('itemName', 'Payment'),
                'gstRate': float(notes.get('gstRate', 18)),
                'shipping': float(notes.get('shipping', 0)),
                'discount': float(notes.get('discount', 0)),
                'convenienceFee': float(notes.get('convenienceFee', 0)),
                'purpose': notes.get('purpose', description or ''),
            }),
            'rawPath': '/invoices/from-payment',
            'requestContext': {'http': {'method': 'POST'}},
        }

        inv_response = lambda_client.invoke(
            FunctionName='wecare-invoice-engine',
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
        logger.error(json.dumps({'event': 'invoice_create_error', 'paymentId': payment_id, 'error': str(e), 'requestId': request_id}))
        return

    if not invoice_id:
        logger.error(json.dumps({'event': 'invoice_create_empty', 'paymentId': payment_id, 'response': str(inv_body), 'requestId': request_id}))
        return

    # If deduplicated (WhatsApp path already created it), image/PDF already exist — skip
    if deduplicated:
        logger.info(json.dumps({'event': 'post_payment_dedup_skip', 'paymentId': payment_id, 'invoiceId': invoice_id, 'requestId': request_id}))
        return

    # ── Step 2: Generate invoice image (internal reference only) ──
    try:
        img_payload = {
            'rawPath': f'/invoices/{invoice_id}/generate-image',
            'requestContext': {'http': {'method': 'POST'}},
            'pathParameters': {'invoiceId': invoice_id},
            'body': json.dumps({'invoiceId': invoice_id}),
        }
        img_response = lambda_client.invoke(
            FunctionName='wecare-invoice-engine',
            InvocationType='RequestResponse',
            Payload=json.dumps(img_payload),
        )
        img_result = json.loads(img_response['Payload'].read())
        img_body = json.loads(img_result.get('body', '{}'))
        image_url = img_body.get('imageUrl', '')

        # A17: the image URL is a receipt/document link and must not reach CloudWatch. Log only
        # the invoice id and whether an image was produced.
        logger.info(json.dumps({'event': 'invoice_image_generated', 'invoiceId': invoice_id, 'hasImage': bool(image_url), 'requestId': request_id}))
    except Exception as e:
        # A17: type only. An image-lambda error body can echo a signed URL or request content.
        logger.error(json.dumps({'event': 'invoice_image_error', 'invoiceId': invoice_id, 'error': type(e).__name__, 'requestId': request_id}))

    # ── Step 3: Generate PDF (async, internal reference only) ──
    try:
        pdf_payload = {
            'rawPath': f'/invoices/{invoice_id}/generate-pdf',
            'requestContext': {'http': {'method': 'POST'}},
            'pathParameters': {'invoiceId': invoice_id},
            'body': json.dumps({'invoiceId': invoice_id}),
        }
        lambda_client.invoke(
            FunctionName='wecare-invoice-engine',
            InvocationType='Event',  # Async
            Payload=json.dumps(pdf_payload),
        )
        logger.info(json.dumps({'event': 'invoice_pdf_triggered', 'invoiceId': invoice_id, 'requestId': request_id}))
    except Exception as e:
        logger.error(json.dumps({'event': 'invoice_pdf_error', 'invoiceId': invoice_id, 'error': str(e), 'requestId': request_id}))

    # NO WhatsApp send — WhatsApp inbound handler is the primary path for customer delivery
    logger.info(json.dumps({'event': 'post_payment_complete', 'paymentId': payment_id, 'invoiceId': invoice_id, 'path': 'webhook_backup', 'requestId': request_id}))



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
            if 'ConditionalCheckFailedException' in str(e):
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
    """Handle settlement.processed event."""
    settlement = event_data.get('settlement', {}).get('entity', {})
    settlement_id = settlement.get('id', '')
    amount = int(settlement.get('amount', 0)) / 100
    logger.info(json.dumps({
        'event': event_type, 'settlementId': settlement_id, 'amount': amount, 'requestId': request_id,
    }))


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
    """Handle payout.* events."""
    payout = event_data.get('payout', {}).get('entity', {})
    payout_id = payout.get('id', '')
    amount = int(payout.get('amount', 0)) / 100
    status = payout.get('status', '')
    logger.info(json.dumps({
        'event': event_type, 'payoutId': payout_id, 'amount': amount, 'status': status, 'requestId': request_id,
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
