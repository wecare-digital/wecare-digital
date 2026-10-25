"""Paid Vault access followed by the approved ready and review templates."""
import os
import json
import time
from datetime import datetime
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
    # The link is the delivery: the template is approved for use outside the 24-hour window, so
    # every paid (or renewed) file reaches the customer through it. `_send_once` keys on this
    # purchase's request row, so a renewal - a new request - sends again.
    if not _send_once(requests, row, 'vaultNotificationStatus', lambda_client, ready):
        return {'outcome': 'VAULT_NOTIFICATION_PENDING'}
    # A PDF attachment is a separate ordinary document message. The approved
    # share template has an IMAGE header and cannot carry the file itself.
    last = contact.get('lastInboundMessageAt', 0)
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace('Z', '+00:00')).timestamp()
    if file.get('deliverable') == 'pdf' and file.get('deliveryKey') and 0 <= time.time() - float(last or 0) < 86400:
        document = {'contactId': contact['id'], 'recipientPhone': phone,
                    'phoneNumberId': WABA1_SENDER, 'mediaType': 'document',
                    'mediaFile': file['deliveryKey'], 'mediaFileName': file.get('originalFilename') or 'document.pdf',
                    'content': 'Your Vault document'}
        if not _send_once(requests, row, 'vaultDocumentStatus', lambda_client, document):
            return {'outcome': 'VAULT_DOCUMENT_PENDING'}
    log_event(logger, 'vault_ready', requestId=row['publicRequestId'],
              renewal=bool(grant.get('renewal')))
    return {'outcome': 'VAULT_READY', 'requestId': row['publicRequestId']}


def send_review(event, lambda_client):
    """Legacy internal action retained as a no-op.

    The paid invoice template already contains the Leave Review Flow button, so a standalone
    review template would duplicate the customer prompt.
    """
    return {'outcome': 'REVIEW_INCLUDED_IN_INVOICE_TEMPLATE'}
