"""Paid Vault access through one owner-bound dynamic download link (no raw PDF send)."""
import os
import json
import time
import boto3
from lambda_utils import customer_auth, shared_tables, whatsapp_templates
from lambda_utils.ecommerce import vault_access
from lambda_utils.logging import get_logger, log_event

#: The WABA1 sender as outbound knows it. Outbound resolves only our Direct-API sender ids
#: (`_resolve_meta_phone_id` fails closed), so the bare Meta phone id this module used to send
#: with was refused and a paid Vault file was never delivered. Same value as `flows.common`.
WABA1_SENDER = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')

logger = get_logger(__name__)

HEADER_IMAGE = whatsapp_templates.VAULT_HEADER_IMAGE

#: The IMAGE header both Vault templates declare, in the keys outbound's generic template builder
#: reads. Outbound honours `headerImageUrl` only on the ORDER_DETAILS checkout path, so a body that
#: carried only `headerImageUrl` reached Meta with no header component and was refused: the
#: approval-time example image is not reusable at send time.
TEMPLATE_IMAGE_HEADER = {'templateHeaderMedia': HEADER_IMAGE, 'templateHeaderType': 'image'}


# The paid-invoice send is accepted before the post-invoice Vault dispatch starts.
# A bounded four-second gap avoids placing Access Vault on top of the paid receipt.
# Provider acceptance is NOT proof of handset delivery or handset order.
# Payment + entitlement guards, durable per-stage send claims and no blind retries stay unchanged.
_POST_RECEIPT_ACCESS_GAP_SECONDS = 4


def _post_receipt_access_gap_seconds() -> int:
    """Bounded staff-configured spacing; never a handset-delivery guarantee."""
    try:
        db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        table = db.Table(os.environ.get(
            'SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable'))
        item = table.get_item(
            Key={'id': 'vault_delivery_timing_v1'}, ConsistentRead=True).get('Item') or {}
        raw = item.get('configValue') or '{}'
        value = json.loads(raw) if isinstance(raw, str) else raw
        gap = value.get('postReceiptAccessGapSeconds') if isinstance(value, dict) else None
        if type(gap) is int and 0 <= gap <= 5:
            return gap
    except Exception as exc:
        log_event(logger, 'vault_access_spacing_config_unavailable', level='warning',
                  reason=type(exc).__name__)
    return _POST_RECEIPT_ACCESS_GAP_SECONDS


def _send_once(requests, row, key, lambda_client, body, *, record_key=None):
    record_key = record_key or {'requestId': row['requestId']}
    current = requests.get_item(Key=record_key, ConsistentRead=True).get('Item') or {}
    if current.get(key) == 'ACCEPTED':
        return True
    now = int(time.time())
    attempts_key, retry_key = key + 'Attempts', key + 'RetryAt'
    previous = int(current.get(attempts_key) or 0)
    if current.get(key) and (current.get(key) != 'SEND_REJECTED' or previous >= 3
                            or int(current.get(retry_key) or 0) > now):
        # Uncertain acceptance and historical SEND_FAILED require reconciliation.
        return False
    condition = 'attribute_not_exists(' + key + ')'
    values = {':s': 'SENDING', ':count': previous + 1}
    if current.get(key):
        condition = key + '=:rejected AND ' + attempts_key + '=:previous'
        values.update({':rejected': 'SEND_REJECTED', ':previous': previous})
    try:
        requests.update_item(Key=record_key,
            UpdateExpression='SET ' + key + '=:s, ' + attempts_key + '=:count',
            ConditionExpression=condition, ExpressionAttributeValues=values)
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return False
        raise
    status = 'SEND_UNKNOWN'
    whatsapp_message_id = ''
    try:
        response = lambda_client.invoke(FunctionName='wecare-outbound-whatsapp:live',
            InvocationType='RequestResponse', Payload=json.dumps({'body': json.dumps(body)}).encode())
        answer = json.loads(response['Payload'].read())
        code = int(answer.get('statusCode', 500))
        if not response.get('FunctionError'):
            if 200 <= code < 300:
                accepted = answer.get('body') or {}
                if isinstance(accepted, str):
                    try:
                        accepted = json.loads(accepted)
                    except (TypeError, ValueError):
                        accepted = {}
                if isinstance(accepted, dict) and (
                        accepted.get('mode') == 'DRY_RUN' or accepted.get('status') == 'dry_run'):
                    status = 'SEND_REJECTED'
                else:
                    if isinstance(accepted, dict):
                        whatsapp_message_id = str(accepted.get('whatsappMessageId') or '')
                    # The provider WAMID is required for status webhook reconciliation.
                    # A 200 with no WAMID is uncertain, never proof of Meta acceptance.
                    status = 'ACCEPTED' if whatsapp_message_id else 'SEND_UNKNOWN'
            elif code in (400, 401, 403, 404, 413, 415, 422):
                status = 'SEND_REJECTED'
    except Exception:
        # Failure may occur after Meta accepted the message. Never blindly retry it.
        pass
    requests.update_item(Key=record_key,
        UpdateExpression='SET ' + key + '=:s, ' + retry_key + '=:retry, '
                         + key + 'MessageId=:wamid',
        ConditionExpression=key + '=:sending AND ' + attempts_key + '=:count',
        ExpressionAttributeValues={':s': status, ':retry': now + 30,
                                   ':wamid': whatsapp_message_id,
                                   ':sending': 'SENDING', ':count': previous + 1})
    return status == 'ACCEPTED'


# The old internal openVaultAccessWindow invocation was removed deliberately.
# Meta accepted is not handset delivered; opening before download can consume
# paid hours while a customer cannot see the message. Secure-files _redeem
# starts the single paid window after verified sign-in and private S3 HEAD.


#: Outcomes after which a captured Vault payment has not reached its customer. This module runs
#: only from the paid-capture dispatch, so money has already moved; each outcome used to return
#: silently into an asynchronous invoke nobody reads. They are logged with an alert so staff can
#: reconcile (Access Vault resend, or the entitlement itself). Nothing here charges again.
#:   PAID_VAULT_UNFULFILLED  no entitlement was granted for the payment.
#:   VAULT_DELIVERY_UNSENT   the entitlement exists, but the Access Vault link did not go out.
_UNDELIVERED_ALERTS = {
    'VAULT_ACCESS_UNAVAILABLE': 'PAID_VAULT_UNFULFILLED',
    'VERIFIED_RECIPIENT_UNAVAILABLE': 'VAULT_DELIVERY_UNSENT',
    'CONTACT_LINK_UNAVAILABLE': 'VAULT_DELIVERY_UNSENT',
    'VAULT_NOTIFICATION_PENDING': 'VAULT_DELIVERY_UNSENT',
}


def prepare_and_send(event, lambda_client):
    """Grant the paid Vault entitlement and send its Access Vault link; alert when either fails."""
    try:
        result = _prepare_and_send(event, lambda_client)
    except Exception as error:
        # A table, Cognito or invoke failure raised before any outcome existed. This runs in an
        # asynchronous invoke whose retries end silently, after money has moved, so every failed
        # attempt is alerted like an ungranted entitlement. Re-raised so Lambda still retries.
        log_event(logger, 'paid_vault_not_delivered', level='error',
                  alert='PAID_VAULT_UNFULFILLED', outcome='VAULT_ACCESS_ERROR',
                  error=type(error).__name__,
                  referenceId=str(event.get('referenceId') or ''),
                  paymentAttemptId=str(event.get('paymentAttemptId') or ''),
                  orderId=str(event.get('orderId') or ''))
        raise
    outcome = str((result or {}).get('outcome') or '')
    alert = _UNDELIVERED_ALERTS.get(outcome)
    if alert:
        # Correlation ids only: the reference, the attempt and the order. No phone, no file name.
        log_event(logger, 'paid_vault_not_delivered', level='error', alert=alert, outcome=outcome,
                  referenceId=str(event.get('referenceId') or ''),
                  paymentAttemptId=str(event.get('paymentAttemptId') or ''),
                  orderId=str(event.get('orderId') or ''))
    return result


def _prepare_and_send(event, lambda_client):
    db = boto3.resource('dynamodb')
    requests = db.Table('stack-wecare-digital-ServiceRequestsTable')
    result = vault_access.grant_access(requests, db.Table('stack-wecare-digital-CommerceKeys'),
        db.Table(vault_access.FILES_TABLE), db.Table(vault_access.GRANTS_TABLE), event)
    if not result:
        return {'outcome': 'VAULT_ACCESS_UNAVAILABLE'}
    row, file, grant = result

    # Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
    if not customer_auth.is_cognito_subject(row['customerId']):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    users = boto3.client('cognito-idp').list_users(UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + row['customerId'] + '"', Limit=2).get('Users') or []
    if len(users) != 1 or not users[0].get('Enabled', True):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}
    phone = attrs.get('phone_number', '')
    if attrs.get('phone_number_verified') != 'true' or phone != '+' + grant['ownerPhone']:
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    contacts = db.Table(shared_tables.contacts_table_name())
    matches = contacts.query(IndexName='phone-index', KeyConditionExpression='phone=:p',
        ExpressionAttributeValues={':p': phone}).get('Items') or []
    valid = []
    for projection in matches:
        contact = contacts.get_item(Key={'id': projection['id']}, ConsistentRead=True).get('Item') or {}
        if (contact.get('checkoutCustomerId') == row['customerId'] and not contact.get('isDeleted')
                and contact.get('deletedAt') is None):
            valid.append(contact)
    if len(valid) != 1:
        return {'outcome': 'CONTACT_LINK_UNAVAILABLE'}
    contact = valid[0]
    base = {'contactId': contact['id'], 'recipientPhone': phone,
            'phoneNumberId': WABA1_SENDER, 'isTemplate': True,
            'templateParams': [], **TEMPLATE_IMAGE_HEADER}
    # The approved Vault delivery template is always the dynamic download template.
    # Its IMAGE header is fixed by whatsapp_templates.download_send_fields and button 0
    # receives only the file-id suffix for https://wecare.digital/vault/?file={{1}}.
    ready = dict(base, **whatsapp_templates.download_send_fields(file['fileId']))
    # Read before the send so a replayed payment event, whose link was already accepted, opens
    # no window below.
    delivered_before = (requests.get_item(Key={'requestId': row['requestId']}, ConsistentRead=True)
                        .get('Item') or {}).get('vaultNotificationStatus') == 'ACCEPTED'
    # Only the verified post-invoice path invokes us. Leave a short gap before the final
    # Access Vault message; the paid request row still deduplicates concurrent invocations.
    # A sleep is spacing, not a receipt-delivered acknowledgement.
    if not delivered_before:
        time.sleep(_post_receipt_access_gap_seconds())
    # The approved download template is tied to this paid purchase's file ID.
    if not _send_once(requests, row, 'vaultNotificationStatus', lambda_client, ready):
        return {'outcome': 'VAULT_NOTIFICATION_PENDING'}
    # The single 24-hour entitlement remains READY until the customer's first
    # authenticated private-file download. WhatsApp provider acceptance has no
    # reliable handset-delivery timestamp, so it must not consume paid access.
    # This send has zero window openings; previous OPEN/EXPIRED records remain
    # unchanged and an in-flight captured payment remains fulfilable.
    window_opened = False
    # Vault is a paid, owner-bound DOWNLOAD product, not a WhatsApp PDF forwarding
    # service. The approved Access Vault button above is the only automatic
    # document-delivery message; customer authentication and the 24-hour
    # entitlement remain enforced by /vault/ and secure-files. Never send a
    # raw document attachment as a second message, even when the customer
    # recently replied (a 24-hour chat window is not a download entitlement).
    log_event(logger, 'vault_ready', requestId=row['publicRequestId'],
              renewal=bool(grant.get('renewal')), windowOpened=window_opened)
    return {'outcome': 'VAULT_READY', 'requestId': row['publicRequestId'],
            'windowOpened': window_opened}


def send_review(event, lambda_client):
    """Legacy internal action retained as a no-op.

    The paid invoice template already contains the Leave Review Flow button, so a standalone
    review template would duplicate the customer prompt.
    """
    return {'outcome': 'REVIEW_INCLUDED_IN_INVOICE_TEMPLATE'}
