"""Catalog-first Submit Request and Vault. Internal invocation only; rollout defaults off."""
import json
import os
import secrets
import time
import boto3
from lambda_utils import customer_auth
from lambda_utils.ecommerce import catalog_service_checkout as catalog, service_request_store as store, vault_access as vault

HEADER_IMAGE = 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png'


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


def readiness(get_flow, graph):
    flow_result = get_flow('1728231914933139')
    flow = json.loads(flow_result.get('body') or '{}').get('flow') or {}
    templates = {}
    for name, ident in {'wecarepay_wa': '1783774039408860',
                        'wecare_default_download': '1410998911012572',
                        'wecare_leave_review': '1801972550682516'}.items():
        info = graph(ident, params={'fields': 'id,name,status,language,components'})
        templates[name] = {k: info.get(k) for k in ('id', 'name', 'status', 'language', 'components', 'error')}
    return {'flow': {k: flow.get(k) for k in ('id', 'name', 'status', 'validation_errors', 'endpoint_uri')},
            'templates': templates}


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
    # Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
    if not customer_auth.is_cognito_subject(owner):
        _send(client, {'contactId': contact.get('id', ''), 'phone': event.get('senderPhone', ''),
                       'phoneNumberId': event.get('phoneNumberId', '1016149501586345')},
              content='Please sign in to your WECARE.DIGITAL customer account and verify this WhatsApp number before purchasing this service: https://wecare.digital/account/sign-in/')
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
        if choice['kind'] == 'SUBMIT_REQUEST':
            from lambda_utils.ecommerce.paid_submit_request import has_prior_order
            if not has_prior_order(db.Table('stack-wecare-digital-OrderTable'),
                                   {'customerId': identity.customer_id, 'orderId': ''}):
                _send(client, {'contactId': contact['id'], 'phone': identity.phone,
                               'phoneNumberId': event['phoneNumberId']},
                      content='We could not find an earlier order linked to your verified account. No payment has been requested. Please message us so we can help link your order.')
                return {'outcome': 'SUBMIT_REQUEST_PARENT_ORDER_REQUIRED'}
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
            choices = []
            for item in projected:
                file = files.get_item(Key={'fileId': item['fileId']}, ConsistentRead=True).get('Item') or {}
                if (file.get('status') != 'active' or file.get('ownerPhone') != identity.phone.lstrip('+')
                        or file.get('ownerCustomerId') not in (None, identity.customer_id)):
                    continue
                access_id = str(file.get('vaultEntitlementId') or file.get('vaultAccessGrantId') or '')
                paid = bool(access_id and file.get('vaultPaymentStatus') == 'PAID')
                if paid or (not file.get('vaultAccessGrantId') and file.get('vaultPaymentStatus') != 'PAID'):
                    choices.append((file, paid))
            if not choices:
                row['status'] = 'AWAITING_FILE'
                keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
                _send(client, row, content='No Vault documents are currently available for this verified account. No payment has been requested.')
                return {'outcome': 'VAULT_FILE_NOT_READY'}
            # At most ten choices per native list. Paid rows remain visible as refresh actions.
            row['fileChoices'] = [file['fileId'] for file, _paid in choices[:10]]
            row['fileChoiceStates'] = ['PAID' if paid else 'UNPAID' for _file, paid in choices[:10]]
            keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
            _send(client, row, isInteractive=True, interactiveType='list', interactiveData={
                'body': 'Choose a document. Paid documents refresh access without another charge.',
                'button': 'Choose document', 'sections': [{'title': 'Your documents', 'rows': [
                    {'id': 'vaultpick:' + token + ':' + str(i),
                     'title': (('Paid · ' if paid else '') + str(file.get('displayName') or file.get('originalFilename') or 'Document'))[:24]}
                    for i, (file, paid) in enumerate(choices[:10])]}]})
            return {'outcome': 'VAULT_FILE_SELECTION_SENT'}
        keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
    elif action == 'select':
        row = catalog.selected_session(keys, event.get('token', ''), contact['id'], identity.phone, now)
        index = event.get('fileIndex')
        if (row.get('customerId') != identity.customer_id or row['kind'] != 'VAULT' or row.get('status') != 'SELECTING' or type(index) is not int
                or not 0 <= index < len(row.get('fileChoices') or [])):
            return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['fileChoices'][index])
        state = (row.get('fileChoiceStates') or [])[index] if index < len(row.get('fileChoiceStates') or []) else 'UNPAID'
        if state == 'PAID' or file.get('vaultEntitlementId') or file.get('vaultAccessGrantId') or file.get('vaultPaymentStatus') == 'PAID':
            if os.environ.get('VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED', 'false').lower() != 'true':
                return {'outcome': 'VAULT_REFRESH_NOT_RELEASED'}
            response = _send(client, row, isTemplate=True, templateName='wecare_default_download',
                             templateParams=[], headerImageUrl=HEADER_IMAGE,
                             templateUrlButton={'index': 0, 'suffix': file['fileId']})
            code = int(response.get('statusCode', 500)) if isinstance(response, dict) else 500
            return {'outcome': 'VAULT_ACCESS_REFRESH_SENT' if 200 <= code < 300 else 'VAULT_ACCESS_REFRESH_PENDING',
                    'fileId': file['fileId']}
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
            _send(client, row, content='You already have a service payment in progress. Please complete that payment before starting another purchase.')
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
    if result.get('outcome') in ('NATIVE_SERVICE_WRITEBACK_NOT_READY', 'NATIVE_SERVICE_META_NOT_READY'):
        current = keys.get_item(Key={'orderId': row['orderId']}, ConsistentRead=True).get('Item') or {}
        if not current.get('paymentAttemptId') and not current.get('nativePrepareClaim'):
            keys.update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + identity.customer_id},
                UpdateExpression='SET #s=:closed', ConditionExpression='sessionKey=:session',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':closed': 'CLOSED', ':session': row['orderId']})
            _send(client, row, content='This service is temporarily unavailable. No payment has been requested. Please try again later.')
    return result
