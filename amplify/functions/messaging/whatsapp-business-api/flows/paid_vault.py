"""Paid Vault access followed by the approved ready and review templates."""
import json
import time
from datetime import datetime
import boto3
from lambda_utils import customer_auth
from lambda_utils.ecommerce import vault_access

HEADER_IMAGE = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png'


def _send_once(requests, row, key, lambda_client, body):
    current = requests.get_item(Key={'requestId': row['requestId']}, ConsistentRead=True).get('Item') or {}
    if current.get(key) == 'ACCEPTED':
        return True
    try:
        requests.update_item(Key={'requestId': row['requestId']},
            UpdateExpression='SET ' + key + '=:s', ConditionExpression='attribute_not_exists(' + key + ')',
            ExpressionAttributeValues={':s': 'SENDING'})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return False
        raise
    response = lambda_client.invoke(FunctionName='wecare-outbound-whatsapp:live',
        InvocationType='RequestResponse', Payload=json.dumps({'body': json.dumps(body)}).encode())
    answer = json.loads(response['Payload'].read())
    ok = not response.get('FunctionError') and 200 <= int(answer.get('statusCode', 500)) < 300
    requests.update_item(Key={'requestId': row['requestId']},
        UpdateExpression='SET ' + key + '=:s',
        ExpressionAttributeValues={':s': 'ACCEPTED' if ok else 'SEND_FAILED'})
    return ok


def prepare_and_send(event, lambda_client):
    db = boto3.resource('dynamodb')
    requests = db.Table('stack-wecare-digital-ServiceRequestsTable')
    result = vault_access.grant_access(requests, db.Table('stack-wecare-digital-WixOrderIds'),
        db.Table(vault_access.FILES_TABLE), db.Table(vault_access.GRANTS_TABLE), event)
    if not result:
        return {'outcome': 'VAULT_ACCESS_UNAVAILABLE'}
    row, file, grant = result
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
    if not _send_once(requests, row, 'vaultNotificationStatus', lambda_client,
                      dict(base, templateName='wecare_share_pdf')):
        return {'outcome': 'VAULT_NOTIFICATION_PENDING'}
    # A PDF attachment is a separate ordinary document message. The approved
    # share template has an IMAGE header and cannot carry the file itself.
    last = contact.get('lastInboundMessageAt', 0)
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace('Z', '+00:00')).timestamp()
    if file.get('deliverable') == 'pdf' and file.get('deliveryKey') and 0 <= time.time() - float(last or 0) < 86400:
        document = {'contactId': contact['id'], 'recipientPhone': phone,
                    'phoneNumberId': '1016149501586345', 'mediaType': 'document',
                    'mediaFile': file['deliveryKey'], 'mediaFileName': file.get('originalFilename') or 'document.pdf',
                    'content': 'Your Vault document'}
        if not _send_once(requests, row, 'vaultDocumentStatus', lambda_client, document):
            return {'outcome': 'VAULT_DOCUMENT_PENDING'}
    review = dict(base, templateName='wecare_leave_review',
                  flowButton={'index': 0, 'flowKey': 'leave_review'})
    accepted = _send_once(requests, row, 'vaultReviewStatus', lambda_client, review)
    return {'outcome': 'VAULT_READY' if accepted else 'VAULT_REVIEW_PENDING',
            'requestId': row['publicRequestId']}
