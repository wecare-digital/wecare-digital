"""One explicit receipt resend intent; invoice-level CAS serializes browser tabs.

No money, customer record or invoice number is changed. Uncertain sends remain
locked until the durable request can be reconciled; they are never blindly retried.
"""
import hashlib
import json
import re
from .collect_contract import is_collect


def conditional(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException'


def resend(body, *, actor, invoices, keys, latest_asset, recipient_valid, send, paid, now,
           original_ready=None, reconcile=None):
    required = {'_action', 'invoiceId', 'resendRequestId', 'previousRequestId', 'expectedAssetKey'}
    if (set(body) != required or body.get('_action') != 'collect-resend'
            or not all(isinstance(body.get(k), str) for k in required)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', body['invoiceId'])
            or not re.fullmatch(r'[a-f0-9]{32}', body['resendRequestId'])
            or len(body['previousRequestId']) > 64 or len(body['expectedAssetKey']) > 1000):
        return 400, {'error': 'INVALID_RESEND_REQUEST'}
    if not actor:
        return 403, {'error': 'AUTHENTICATED_ADMIN_REQUIRED'}
    invoice_id, intent = body['invoiceId'], body['resendRequestId']
    identity = hashlib.sha256((invoice_id + ':' + intent).encode()).hexdigest()
    key = 'COLLECT_RECEIPT_RESEND#' + identity
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def prior_result(row):
        if row.get('fingerprint') != fingerprint:
            return 409, {'error': 'RESEND_INTENT_CONFLICT'}
        return _resolve_result(row, invoice_id=invoice_id, intent=intent, key=key,
                               invoices=invoices, keys=keys, reconcile=reconcile, now=now)

    old = keys.get_item(Key={'orderId': key}, ConsistentRead=True).get('Item')
    if old:
        return prior_result(old)
    inv = invoices.get_item(Key={'invoiceId': invoice_id}, ConsistentRead=True).get('Item') or {}
    if not is_collect(inv):
        return 409, {'error': 'COLLECT_INVOICE_REQUIRED'}
    if not paid(inv):
        return 409, {'error': 'PAID_RECEIPT_REQUIRED'}
    if not recipient_valid(inv):
        return 409, {'error': 'SAVED_RECIPIENT_INVALID'}
    asset = latest_asset(invoice_id) or {}
    if (not asset.get('s3Key') or asset['s3Key'] != body['expectedAssetKey']
            or int(asset.get('generatedAt') or asset.get('createdAt') or 0) < int(inv.get('paidAt') or 0)):
        return 409, {'error': 'PAID_IMAGE_CHANGED_OR_MISSING'}
    if original_ready and not original_ready(inv):
        return 409, {'error': 'ORIGINAL_RECEIPT_UNRESOLVED'}
    if (str(inv.get('collectResendRequestId') or '') != body['previousRequestId']
            or inv.get('collectResendState') in ('SENDING', 'UNCONFIRMED')):
        return 409, {'error': 'RESEND_PENDING_OR_CHANGED'}
    try:
        keys.put_item(Item={'orderId': key, 'invoiceId': invoice_id, 'requestId': intent,
                            'fingerprint': fingerprint, 'state': 'SENDING', 'createdAt': now,
                            'expectedAssetKey': body['expectedAssetKey'],
                            'actorHash': hashlib.sha256(actor.encode()).hexdigest()},
                      ConditionExpression='attribute_not_exists(orderId)')
    except Exception as error:
        if not conditional(error):
            raise
        return prior_result(keys.get_item(Key={'orderId': key}, ConsistentRead=True).get('Item') or {})
    values = {':intent': intent, ':sending': 'SENDING', ':now': now,
              ':captured': 'captured', ':paid': 'paid'}
    condition = '(paymentStatus = :captured OR paymentStatus = :paid) AND '
    if body['previousRequestId']:
        condition += 'collectResendRequestId = :previous AND collectResendState IN (:accepted, :refused)'
        values.update({':previous': body['previousRequestId'], ':accepted': 'ACCEPTED', ':refused': 'REFUSED'})
    else:
        condition += 'attribute_not_exists(collectResendRequestId)'
    try:
        invoices.update_item(Key={'invoiceId': invoice_id},
            UpdateExpression='SET collectResendRequestId=:intent, collectResendState=:sending, collectResendAt=:now',
            ConditionExpression=condition, ExpressionAttributeValues=values)
    except Exception as error:
        if not conditional(error):
            raise
        keys.update_item(Key={'orderId': key}, UpdateExpression='SET #s=:state',
                         ExpressionAttributeNames={'#s': 'state'}, ExpressionAttributeValues={':state': 'REFUSED'})
        return 409, {'error': 'RESEND_PENDING_OR_CHANGED'}
    try:
        result = send(invoice_id, str(inv.get('customerPhone') or ''), asset['s3Key'])
        payload = json.loads(result.get('body') or '{}')
        code = int(result.get('statusCode') or 0)
        accepted = code == 200 and payload.get('status') in ('sent', 'accepted', 'delivered', 'read') and payload.get('waMessageId')
        # A server error or ambiguous acceptance must hold the invoice lock.
        state = ('ACCEPTED' if accepted else 'REFUSED' if (400 <= code < 500 or payload.get('status') in ('failed', 'rejected')) else 'UNCONFIRMED')
        message_id = str(payload.get('waMessageId') or '')
    except Exception:
        state, message_id = 'UNCONFIRMED', ''
    keys.update_item(Key={'orderId': key}, UpdateExpression='SET #s=:state, waMessageId=:message, updatedAt=:now',
        ConditionExpression='#s=:sending', ExpressionAttributeNames={'#s': 'state'},
        ExpressionAttributeValues={':state': state, ':message': message_id, ':now': now, ':sending': 'SENDING'})
    invoices.update_item(Key={'invoiceId': invoice_id},
        UpdateExpression='SET collectResendState=:state, collectResendMessageId=:message',
        ConditionExpression='collectResendRequestId=:intent',
        ExpressionAttributeValues={':state': state, ':message': message_id, ':intent': intent})
    return 200 if state != 'UNCONFIRMED' else 202, {
        'requestId': intent, 'state': state, 'waMessageId': message_id, 'deduplicated': False}


def _resolve_result(row, *, invoice_id, intent, key, invoices, keys, reconcile, now):
    if row.get('state') in ('SENDING', 'UNCONFIRMED') and reconcile:
        proof = reconcile(invoice_id, intent, row.get('expectedAssetKey', ''))
        if proof and proof.get('state') in ('ACCEPTED', 'REFUSED'):
            try:
                keys.update_item(Key={'orderId': key},
                    UpdateExpression='SET #s=:state, waMessageId=:message, updatedAt=:now',
                    ConditionExpression='#s=:previous', ExpressionAttributeNames={'#s':'state'},
                    ExpressionAttributeValues={':state':proof['state'], ':message':proof.get('waMessageId',''),
                                               ':now':now, ':previous':row['state']})
            except Exception as error:
                if not conditional(error):
                    raise
            row = keys.get_item(Key={'orderId':key}, ConsistentRead=True).get('Item') or row
    if row.get('state') in ('ACCEPTED', 'REFUSED'):
        try:
            invoices.update_item(Key={'invoiceId': invoice_id},
                UpdateExpression='SET collectResendState=:state, collectResendMessageId=:message',
                ConditionExpression='collectResendRequestId=:intent',
                ExpressionAttributeValues={':state':row['state'], ':message':row.get('waMessageId',''), ':intent':intent})
        except Exception as error:
            if not conditional(error):
                raise
    return 200, {'requestId':intent, 'state':row.get('state','UNCONFIRMED'),
                 'waMessageId':row.get('waMessageId',''), 'deduplicated':True}


def reconcile_existing(invoice_id, *, actor, invoices, keys, reconcile, now):
    """Resolve the stored intent in any staff browser; this entry point cannot send."""
    if not actor:
        return 403, {'error':'AUTHENTICATED_ADMIN_REQUIRED'}
    inv=invoices.get_item(Key={'invoiceId':str(invoice_id)}, ConsistentRead=True).get('Item') or {}
    if not is_collect(inv):
        return 409, {'error':'COLLECT_INVOICE_REQUIRED'}
    intent=str(inv.get('collectResendRequestId') or '')
    if not intent:
        return 409, {'error':'NO_RESEND_INTENT'}
    key='COLLECT_RECEIPT_RESEND#'+hashlib.sha256((invoice_id+':'+intent).encode()).hexdigest()
    row=keys.get_item(Key={'orderId':key}, ConsistentRead=True).get('Item') or {}
    if row.get('invoiceId')!=invoice_id or row.get('requestId')!=intent:
        return 409, {'error':'RESEND_INTENT_UNAVAILABLE'}
    return _resolve_result(row, invoice_id=invoice_id, intent=intent, key=key,
                           invoices=invoices, keys=keys, reconcile=reconcile, now=now)
