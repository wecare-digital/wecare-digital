"""One-shot, audited notice for retired WhatsApp Vault chooser entry points.

No list pagination, file search, entitlement read, payment or customer lookup
occurs here. Retained provider IDs prove Meta acceptance, not handset delivery.
"""
import json


def classify_reply_send(response):
    """Return (status, provider_message_id, safe_detail).

    HTTP 2xx without a real message ID is unknown, not accepted. A timeout or
    5xx may follow acceptance and is never reported as a certain rejection.
    """
    if not isinstance(response, dict):
        return 'UNKNOWN', '', 'sender_unconfirmed'
    try:
        status_code = int(response.get('statusCode') or 0)
    except (TypeError, ValueError):
        return 'UNKNOWN', '', 'sender_status_invalid'
    payload = response.get('body')
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = None
    payload = payload if isinstance(payload, dict) else {}
    wamid = payload.get('whatsappMessageId')
    wamid = wamid.strip() if isinstance(wamid, str) else ''
    if 200 <= status_code < 300:
        if payload.get('status') == 'dry_run' or payload.get('mode') == 'DRY_RUN':
            return 'REJECTED', '', 'dry_run_not_sent'
        if wamid:
            return 'ACCEPTED', wamid, 'meta_accepted_handset_unverified'
        return 'UNKNOWN', '', 'provider_id_missing'
    if 400 <= status_code < 500:
        return 'REJECTED', '', 'sender_rejected'
    return 'UNKNOWN', wamid, 'sender_unconfirmed'


def send_once_with_audit(keys, row, send, *, row_status):
    """Persist the single reply intent, send once, and retain provider evidence.

    The first conditional Put reserves the reply for this signed inbound WAMID.
    A replay, timeout or failed audit update cannot cause another send; a human
    must reconcile uncertain delivery before any manual action.
    """
    idem = 'vault-retired:' + row['orderId'].split('#', 1)[-1]
    record = {**row, 'status': row_status,
              'replySendStatus': 'SENDING', 'replyIdempotencyKey': idem}
    keys.put_item(
        Item=record, ConditionExpression='attribute_not_exists(orderId)',
    )
    try:
        answer = send(idem)
    except Exception:
        answer = None  # Accepted send may precede a timeout.
    status, wamid, detail = classify_reply_send(answer)
    try:
        keys.update_item(
            Key={'orderId': row['orderId']},
            UpdateExpression='SET replySendStatus=:s, replyMessageId=:m, replySendDetail=:d',
            ConditionExpression='replySendStatus=:sending',
            ExpressionAttributeValues={
                ':s': status, ':m': wamid, ':d': detail, ':sending': 'SENDING',
            },
        )
    except Exception:
        return {'replyStatus': 'UNKNOWN', 'whatsappMessageId': wamid,
                'reconciliationRequired': True}
    return {'replyStatus': status, 'whatsappMessageId': wamid,
            'reconciliationRequired': status == 'UNKNOWN'}
