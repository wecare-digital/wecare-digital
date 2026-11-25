"""Own the WhatsApp message lease boundary, separate from business side effects."""
from __future__ import annotations

from lambda_utils.logging import log_event


def process_tracked_message(process, **kwargs):
    """Close leases only after the entire callback has returned successfully."""
    leased_ids = []
    process(dedup_tracker=leased_ids, **kwargs)
    if leased_ids:
        from lambda_utils.webhook_dedup import complete_event
        for leased_id in leased_ids:
            complete_event(leased_id)


def should_skip_duplicate(message_id, *, message_exists, dedup_tracker, logger, request_id) -> bool:
    """Preserve the expiring lease and the persisted-row duplicate safeguard."""
    leased = False
    duplicate = False
    try:
        from lambda_utils.webhook_dedup import claim_event_with_lease
        if message_id:
            leased = claim_event_with_lease(message_id, source="whatsapp_inbound")
            duplicate = not leased
    except Exception as error:
        # A failure in the optional dedup store must not drop a real webhook.
        log_event(logger, "inbound_dedup_unavailable", level="warning",
                  errorType=type(error).__name__)

    if duplicate or message_exists(message_id):
        if leased and message_id:
            # Existing storage confirms the durable message already exists; finish
            # a reclaimed lease instead of letting repeated retries reclaim it.
            from lambda_utils.webhook_dedup import complete_event
            complete_event(message_id)
        log_event(logger, "message_duplicate_skipped",
                  whatsappMessageId=message_id, requestId=request_id)
        return True

    if leased and dedup_tracker is not None and message_id:
        dedup_tracker.append(message_id)
    return False
