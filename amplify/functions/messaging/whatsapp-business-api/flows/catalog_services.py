"""Catalog-first Submit Request and Vault. Internal invocation only; rollout defaults off."""
import json
import os
import secrets
import time
import boto3
from lambda_utils import customer_auth
from lambda_utils.ecommerce import catalog_service_checkout as catalog, service_request_store as store, vault_access as vault


def _invoke(client, function, payload):
    result = client.invoke(FunctionName=function, InvocationType='RequestResponse',
                           Payload=json.dumps(payload).encode())
    answer = json.loads(result['Payload'].read())
    if result.get('FunctionError'):
        raise RuntimeError('downstream invocation failed')
    return answer


def _send(client, row, **body):
    return _invoke(client, 'wecare-outbound-whatsapp:live', {'body': json.dumps({
        'contactId': row['contactId'], 'recipientPhone': row['phone'],
        'phoneNumberId': row['phoneNumberId'], **body})})


def handle(event, client):
    if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true':
        return {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    keys = db.Table('stack-wecare-digital-WixOrderIds')
    contacts = db.Table('stack-wecare-digital-ContactsTable')
    contact = contacts.get_item(Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    owner = contact.get('checkoutCustomerId')
    if not owner:
        return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}
    users = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'us-east-1')).list_users(
        UserPoolId=customer_auth.CUSTOMER_POOL_ID, Filter='sub = "' + owner + '"', Limit=2).get('Users') or []
    identity = catalog.verified_identity(contact, users, event.get('senderPhone', ''))
    now = int(time.time())
    action = event.get('action', 'start')
    if action == 'start':
        choice = catalog.service_from_lines(event.get('lines') or [])
        if not choice or not event.get('sourceMessageId'):
            return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
        # Source message owns exactly one session. Replay never creates another payment.
        index_key = 'CATALOGSERVICEMSG#' + event['sourceMessageId']
        token = secrets.token_urlsafe(24)
        try:
            keys.put_item(Item={'orderId': index_key, 'token': token},
                          ConditionExpression='attribute_not_exists(orderId)')
        except Exception as error:
            if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return {'outcome': 'CATALOG_SERVICE_REPLAY'}
            raise
        row = {'orderId': catalog.SESSION_PREFIX + token, 'token': token, **choice,
               'contactId': contact['id'], 'phone': identity.phone, 'customerId': identity.customer_id,
               'phoneNumberId': event['phoneNumberId'], 'sourceMessageId': event['sourceMessageId'],
               'createdAt': now, 'expiresAt': now + 3600, 'status': 'SELECTING'}
        if choice['kind'] == 'VAULT':
            files = db.Table(vault.FILES_TABLE)
            projected = files.query(IndexName='owner-created-index',
                KeyConditionExpression='ownerPhone=:p', ExpressionAttributeValues={':p': identity.phone.lstrip('+')},
                Limit=100, ScanIndexForward=False).get('Items') or []
            eligible = []
            for item in projected:
                file = files.get_item(Key={'fileId': item['fileId']}, ConsistentRead=True).get('Item') or {}
                if (file.get('status') == 'active' and file.get('ownerPhone') == identity.phone.lstrip('+')
                        and file.get('ownerCustomerId') in (None, identity.customer_id)):
                    eligible.append(file)
            if not eligible:
                row['status'] = 'AWAITING_FILE'
                keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
                _send(client, row, content='Your document is not ready yet. We will prepare it before asking you to pay for Vault.')
                return {'outcome': 'VAULT_FILE_NOT_READY'}
            # At most ten choices per native list. An additional batch needs a new catalog request.
            row['fileChoices'] = [file['fileId'] for file in eligible[:10]]
            keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
            _send(client, row, isInteractive=True, interactiveType='list', interactiveData={
                'body': 'Choose the document you want to unlock with this Vault purchase.',
                'button': 'Choose document', 'sections': [{'title': 'Your documents', 'rows': [
                    {'id': 'vaultpick:' + token + ':' + str(i),
                     'title': str(file.get('displayName') or file.get('originalFilename') or 'Document')[:24]}
                    for i, file in enumerate(eligible[:10])]}]})
            return {'outcome': 'VAULT_FILE_SELECTION_SENT'}
        keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
    elif action == 'select':
        row = catalog.selected_session(keys, event.get('token', ''), contact['id'], identity.phone, now)
        index = event.get('fileIndex')
        if (row['kind'] != 'VAULT' or row.get('status') != 'SELECTING' or type(index) is not int
                or not 0 <= index < len(row.get('fileChoices') or [])):
            return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['fileChoices'][index])
        row['vaultFileId'] = file['fileId']
    else:
        return {'outcome': 'CATALOG_ACTION_UNAVAILABLE'}
    # One outstanding native purchase per permanent customer, even across catalog messages.
    try:
        keys.update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + identity.customer_id},
            UpdateExpression='SET #s=:active, sessionKey=:session',
            ConditionExpression='attribute_not_exists(orderId) OR #s=:closed',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':active': 'ACTIVE', ':closed': 'CLOSED', ':session': row['orderId']})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return {'outcome': 'NATIVE_SERVICE_PAYMENT_ALREADY_IN_PROGRESS'}
        raise
    # Freeze the intent and selected file before native checkout can reserve any money reference.
    try:
        keys.update_item(Key={'orderId': row['orderId']},
            UpdateExpression='SET #s=:preparing, vaultFileId=:file',
            ConditionExpression='#s=:selecting AND customerId=:owner',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':preparing': 'PREPARING_PAYMENT', ':selecting': 'SELECTING',
                ':owner': identity.customer_id, ':file': row.get('vaultFileId', '')})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            return {'outcome': 'CATALOG_SERVICE_ALREADY_PREPARING'}
        raise
    file = None
    if row['kind'] == 'VAULT':
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['vaultFileId'])
    intent = store.request_intent(db.Table('stack-wecare-digital-ServiceRequestsTable'), identity,
                                  row['kind'], vault_file=file)
    keys.update_item(Key={'orderId': row['orderId']}, UpdateExpression='SET serviceIntentId=:intent',
                     ExpressionAttributeValues={':intent': intent['intentId']})
    result = _invoke(client, 'wecare-checkout:live', {
        'internalAction': 'prepareNativeCatalogService', 'catalogToken': row['token']})
    # No automatic second attempt after an ambiguous provider send. Staff reconcile this session.
    keys.update_item(Key={'orderId': row['orderId']}, UpdateExpression='SET paymentResult=:result',
                     ExpressionAttributeValues={':result': result})
    return result
