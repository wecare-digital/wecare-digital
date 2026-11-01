"""Bounded owner-scoped WhatsApp Vault file lookup and one-shot reply audit.

Legacy signed-inbound chooser only. Staff-created exact-file Review & Pay
and paid entitlements are unaffected.
"""
import json

QUERY_PAGE_SIZE = 25
MAX_QUERY_PAGES = 12
MAX_INDEX_RECORDS = QUERY_PAGE_SIZE * MAX_QUERY_PAGES
MAX_CHOICES = 10
ELIGIBLE_STATES = frozenset(('UNPAID', 'OPEN', 'READY'))


def eligible_owner_files(files, phone, customer_id, state_for_file,
                         *, page_size=QUERY_PAGE_SIZE,
                         max_pages=MAX_QUERY_PAGES,
                         max_index_records=MAX_INDEX_RECORDS,
                         max_choices=MAX_CHOICES):
    """Return (choices, index_exhausted) using bounded DynamoDB pagination.

    An unexhausted index is never evidence that no document exists. Each index
    candidate is re-read consistently from the base table and owner-checked.
    Query responses can stop at 1 MB even before the requested Limit.
    """
    if (not phone or not customer_id or not callable(state_for_file)
            or page_size < 1 or max_pages < 1
            or max_index_records < 1 or max_choices < 1):
        return [], False
    choices, cursor, evaluated = [], None, 0

    for _ in range(max_pages):
        remaining = max_index_records - evaluated
        if remaining <= 0:
            break
        args = {
            'IndexName': 'owner-created-index',
            'KeyConditionExpression': 'ownerPhone=:p',
            'ExpressionAttributeValues': {':p': phone},
            'Limit': min(page_size, remaining),
            'ScanIndexForward': False,
        }
        if cursor:
            args['ExclusiveStartKey'] = cursor
        page = files.query(**args)
        projected = page.get('Items') or []
        if not isinstance(projected, list):
            return choices, False
        scanned = page.get('ScannedCount')
        evaluated += max(scanned, len(projected)) if isinstance(scanned, int) and scanned >= 0 else len(projected)
        for candidate in projected:
            fid = candidate.get('fileId') if isinstance(candidate, dict) else None
            if not isinstance(fid, str) or not fid or len(fid) > 120:
                continue
            row = files.get_item(
                Key={'fileId': fid}, ConsistentRead=True,
            ).get('Item') or {}
            if (row.get('status') != 'active'
                    or row.get('ownerPhone') != phone
                    or row.get('ownerCustomerId') != customer_id
                    or row.get('fileId') != fid):
                continue
            state = state_for_file(row)
            if state in ELIGIBLE_STATES:
                choices.append((row, state))
                if len(choices) >= max_choices:
                    return choices, False

        next_cursor = page.get('LastEvaluatedKey')
        if not next_cursor:
            return choices, True
        if next_cursor == cursor:
            return choices, False
        cursor = next_cursor

    return choices, False


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

    The signed inbound message is already claimed with a conditional index Put
    by the caller. An unknown result or failed audit update is reconciled, not
    blindly re-sent. The outbound idempotency key is also stable per session.
    """
    idem = 'vault-chooser:' + row['token']
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
