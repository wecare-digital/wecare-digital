"""Catalog-first Vault purchase and paid-file refresh. Internal invocation only; rollout defaults off.

Reached only from the inbound worker for a cart that is exactly one Vault line (see
`catalog_service_checkout.ALLOWED` for why Submit Request is no longer sold here). It proves the
verified customer, lets them pick a file and hands ONE priced session to `wecare-checkout`
`prepareNativeCatalogService`; it never prices, reserves or sends a payment itself.
"""
import json
import os
import secrets
import time
import boto3
from lambda_utils import customer_auth, shared_tables, whatsapp_templates
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


def readiness(graph):
    """Live Meta readback of the two templates a Vault purchase needs. Reads only."""
    templates = {}
    for name, ident in {'wecare_whatapp_native_pay_template': '2714938845570815',
                        'wecare_default_download': '1410998911012572'}.items():
        info = graph(ident, params={'fields': 'id,name,status,language,components'})
        templates[name] = {k: info.get(k) for k in ('id', 'name', 'status', 'language', 'components', 'error')}
    return {'templates': templates}


IDENTITY_NOT_READY = (
    'We could not verify this WhatsApp checkout safely. Nothing has been charged. '
    'Please send the catalog item again or contact support.'
)


def handle(event, client):
    if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true':
        return {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    keys = db.Table('stack-wecare-digital-CommerceKeys')
    contacts = db.Table(shared_tables.contacts_table_name())
    contact = contacts.get_item(Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    # Outbound resolves only our Direct-API sender ids; the bare Meta phone id is refused.
    sender = {'contactId': contact.get('id', ''), 'phone': event.get('senderPhone', ''),
              'phoneNumberId': event.get('phoneNumberId') or os.environ.get(
                  'WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')}

    # Native WhatsApp payment identity is established from signed inbound evidence, not a browser
    # session. Commerce owns the bridge to the dedicated registration function, so this shared
    # business-api role never gains customer-pool provisioning rights.
    try:
        resolved = _invoke(client, 'wecare-commerce:live', {
            'internalAction': 'ensureNativeWhatsAppIdentity',
            'contactId': contact.get('id', ''),
            'senderPhone': event.get('senderPhone', ''),
            'phoneNumberId': sender['phoneNumberId'],
        })
    except Exception:
        resolved = {}
    if resolved.get('outcome') != 'WHATSAPP_IDENTITY_READY':
        _send(client, sender, content=IDENTITY_NOT_READY)
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
    owner = str(resolved.get('customerId') or '')
    number = str(resolved.get('phone') or '')
    if not customer_auth.is_cognito_subject(owner) or not number:
        _send(client, sender, content=IDENTITY_NOT_READY)
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
    identity = customer_auth.CustomerIdentity(
        customer_id=owner, subject=owner, phone=number, phone_verified=True)
    # Re-read because the bridge may have attached checkoutCustomerId to this row.
    contact = contacts.get_item(
        Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    if str(contact.get('checkoutCustomerId') or '') != owner:
        _send(client, sender, content=IDENTITY_NOT_READY)
        return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
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
        files = db.Table(vault.FILES_TABLE)
        projected = files.query(IndexName='owner-created-index',
            KeyConditionExpression='ownerPhone=:p', ExpressionAttributeValues={':p': identity.phone.lstrip('+')},
            Limit=100, ScanIndexForward=False).get('Items') or []
        choices = []
        for item in projected:
            file = files.get_item(Key={'fileId': item['fileId']}, ConsistentRead=True).get('Item') or {}
            # Only files already bound to this customer. `vault.bind_file` refuses an ownerless
            # legacy file (a reassigned phone must not inherit it), so listing one offered a
            # choice that could only fail after the customer picked it.
            if (file.get('status') != 'active' or file.get('ownerPhone') != identity.phone.lstrip('+')
                    or file.get('ownerCustomerId') != identity.customer_id):
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
    elif action == 'select':
        try:
            row = catalog.selected_session(keys, event.get('token', ''), contact['id'], identity.phone, now)
        except customer_auth.CustomerNotAuthorized:
            # A tap on a list whose session expired (one hour) or belongs to someone else.
            _send(client, {**sender, 'phone': identity.phone},
                  content='This document list has expired. Nothing has been charged. Please send the Vault item from the catalog again.')
            return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
        index = event.get('fileIndex')
        if (row.get('customerId') != identity.customer_id or row['kind'] != 'VAULT' or row.get('status') != 'SELECTING' or type(index) is not int
                or not 0 <= index < len(row.get('fileChoices') or [])):
            return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
        try:
            file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['fileChoices'][index])
        except customer_auth.CustomerNotAuthorized:
            return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
        state = (row.get('fileChoiceStates') or [])[index] if index < len(row.get('fileChoiceStates') or []) else 'UNPAID'
        if state == 'PAID' or file.get('vaultEntitlementId') or file.get('vaultAccessGrantId') or file.get('vaultPaymentStatus') == 'PAID':
            response = _send(client, row, **whatsapp_templates.download_send_fields(file['fileId']))
            code = int(response.get('statusCode', 500)) if isinstance(response, dict) else 500
            return {'outcome': 'VAULT_ACCESS_REFRESH_SENT' if 200 <= code < 300 else 'VAULT_ACCESS_REFRESH_PENDING',
                    'fileId': file['fileId']}
        row['vaultFileId'] = file['fileId']
    else:
        return {'outcome': 'CATALOG_ACTION_UNAVAILABLE'}
    # One outstanding native purchase per permanent customer, even across catalog messages.
    # The lock lives exactly as long as the session it names (its `expiresAt`, one hour after the
    # cart) and no longer: it used to close only on a paid finalisation, so a customer who let
    # one payment request expire unpaid was refused every later service purchase, permanently. A
    # lock with no `activeUntil` predates the expiry and is treated as expired. Checkout refuses
    # an expired session, the ORDER_DETAILS request itself expires after 15 minutes, and
    # `finalizeNativeCatalogService` closes by `sessionKey`, so a late payment cannot release a
    # newer session's lock.
    try:
        keys.update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + identity.customer_id},
            UpdateExpression='SET #s=:active, sessionKey=:session, activeUntil=:until',
            ConditionExpression=('attribute_not_exists(orderId) OR #s=:closed '
                                 'OR attribute_not_exists(activeUntil) OR activeUntil < :now'),
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':active': 'ACTIVE', ':closed': 'CLOSED',
                                       ':session': row['orderId'],
                                       ':until': int(row.get('expiresAt') or now + 3600),
                                       ':now': now})
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
