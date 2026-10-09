"""Paid Vault access followed by the approved ready and review templates."""
import os
import json
import time
from datetime import datetime
import boto3
from lambda_utils import customer_auth
from lambda_utils.ecommerce import vault_access
from lambda_utils.logging import get_logger, log_event

logger = get_logger(__name__)

HEADER_IMAGE = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png'


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
    try:
        response = lambda_client.invoke(FunctionName='wecare-outbound-whatsapp:live',
            InvocationType='RequestResponse', Payload=json.dumps({'body': json.dumps(body)}).encode())
        answer = json.loads(response['Payload'].read())
        code = int(answer.get('statusCode', 500))
        if not response.get('FunctionError'):
            if 200 <= code < 300:
                status = 'ACCEPTED'
            elif code in (400, 401, 403, 404, 413, 415, 422):
                status = 'SEND_REJECTED'
    except Exception:
        # Failure may occur after Meta accepted the message. Never blindly retry it.
        pass
    requests.update_item(Key=record_key,
        UpdateExpression='SET ' + key + '=:s, ' + retry_key + '=:retry',
        ConditionExpression=key + '=:sending AND ' + attempts_key + '=:count',
        ExpressionAttributeValues={':s': status, ':retry': now + 30,
                                   ':sending': 'SENDING', ':count': previous + 1})
    return status == 'ACCEPTED'


def prepare_and_send(event, lambda_client):
    db = boto3.resource('dynamodb')
    requests = db.Table('stack-wecare-digital-ServiceRequestsTable')
    result = vault_access.grant_access(requests, db.Table('stack-wecare-digital-WixOrderIds'),
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
    contacts = db.Table('stack-wecare-digital-ContactsTable')
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
            'phoneNumberId': '1016149501586345', 'isTemplate': True,
            'templateParams': [], 'headerImageUrl': HEADER_IMAGE}
    ready = dict(base, templateName='wecare_share_pdf')
    # The share template has an IMAGE header and carries no URL button, so it delivers no
    # link. Only the dynamic download template does, and it stays closed.
    link_sent = False
    # Enable only after live Meta readback confirms this exact template is approved.
    if os.environ.get('VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED', 'false').lower() == 'true':
        ready = dict(base, templateName='wecare_default_download',
                     templateUrlButton={'index': 0, 'suffix': file['fileId']})
        link_sent = True
    if not _send_once(requests, row, 'vaultNotificationStatus', lambda_client, ready):
        return {'outcome': 'VAULT_NOTIFICATION_PENDING'}
    # A PDF attachment is a separate ordinary document message. The approved
    # share template has an IMAGE header and cannot carry the file itself.
    last = contact.get('lastInboundMessageAt', 0)
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace('Z', '+00:00')).timestamp()
    delivered = False
    if file.get('deliverable') == 'pdf' and file.get('deliveryKey') and 0 <= time.time() - float(last or 0) < 86400:
        document = {'contactId': contact['id'], 'recipientPhone': phone,
                    'phoneNumberId': '1016149501586345', 'mediaType': 'document',
                    'mediaFile': file['deliveryKey'], 'mediaFileName': file.get('originalFilename') or 'document.pdf',
                    'content': 'Your Vault document'}
        if not _send_once(requests, row, 'vaultDocumentStatus', lambda_client, document):
            return {'outcome': 'VAULT_DOCUMENT_PENDING'}
        delivered = True
    if not link_sent and not delivered:
        # Neither a link nor a file reached the customer, so this is not ready. Reporting it
        # is what makes the paid-but-undelivered population findable. First match wins,
        # mirroring the document condition's own left-to-right evaluation: the two
        # file-shape reasons are permanent data problems, while a closed window is a timing
        # problem a re-send resolves - so it comes last, being the only one that can be true
        # while the file is perfectly deliverable.
        if file.get('deliverable') != 'pdf':
            reason = 'not_deliverable'
        elif not file.get('deliveryKey'):
            reason = 'no_delivery_key'
        else:
            reason = 'window_closed'
        log_event(logger, 'vault_delivery_deferred',
                  requestId=row['publicRequestId'], reason=reason)
        return {'outcome': 'VAULT_DELIVERY_DEFERRED', 'requestId': row['publicRequestId']}
    return {'outcome': 'VAULT_READY', 'requestId': row['publicRequestId']}


def send_review(event, lambda_client):
    """Send the Vault review only after the first authenticated access attempt.

    The persisted send state on the service request means repeated refreshes or duplicate
    async invokes converge on one accepted invitation.
    """
    db = boto3.resource('dynamodb')
    requests = db.Table('stack-wecare-digital-ServiceRequestsTable')
    row = requests.get_item(
        Key={'requestId': str(event.get('requestId') or '')},
        ConsistentRead=True).get('Item') or {}
    if row.get('kind') != 'VAULT' or not row.get('paidAt') or not row.get('customerId'):
        return {'outcome': 'REVIEW_NOT_DUE'}

    # Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
    if not customer_auth.is_cognito_subject(row['customerId']):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    users = boto3.client('cognito-idp').list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID,
        Filter='sub = "' + row['customerId'] + '"', Limit=2).get('Users') or []
    if len(users) != 1 or not users[0].get('Enabled', True):
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}
    attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}
    phone = attrs.get('phone_number', '')
    if attrs.get('phone_number_verified') != 'true' or not phone:
        return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}

    contacts = db.Table('stack-wecare-digital-ContactsTable')
    matches = contacts.query(
        IndexName='phone-index', KeyConditionExpression='phone=:p',
        ExpressionAttributeValues={':p': phone}).get('Items') or []
    valid = []
    for projection in matches:
        contact = contacts.get_item(
            Key={'id': projection['id']}, ConsistentRead=True).get('Item') or {}
        if (contact.get('checkoutCustomerId') == row['customerId']
                and not contact.get('isDeleted') and contact.get('deletedAt') is None):
            valid.append(contact)
    if len(valid) != 1:
        return {'outcome': 'CONTACT_LINK_UNAVAILABLE'}

    body = {
        'contactId': valid[0]['id'], 'recipientPhone': phone,
        'phoneNumberId': '1016149501586345', 'isTemplate': True,
        'templateName': 'wecare_leave_review', 'templateParams': [],
        'headerImageUrl': HEADER_IMAGE,
        'flowButton': {'index': 0, 'flowKey': 'leave_review'},
    }
    accepted = _send_once(
        requests, row, 'vaultReviewStatus', lambda_client, body)
    return {'outcome': 'REVIEW_ACCEPTED' if accepted else 'REVIEW_PENDING'}
