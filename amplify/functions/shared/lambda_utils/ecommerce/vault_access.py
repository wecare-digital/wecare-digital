"""Bind one private file to one verified Wix Vault purchase; never charge."""
import hashlib
import time
from lambda_utils import customer_auth
from lambda_utils.ecommerce import order_keys, service_request_store as store

VARIANT_ID = 'dcff995e-448c-493a-9259-f6a82ccdc2b4'
FILES_TABLE = 'stack-wecare-digital-SecureFilesTable'
GRANTS_TABLE = 'stack-wecare-digital-DownloadGrantsTable'


def bind_file(files, identity, file_id):
    row = files.get_item(Key={'fileId': str(file_id)}, ConsistentRead=True).get('Item') or {}
    phone = ''.join(c for c in identity.phone if c.isdigit())
    if (not row or row.get('status') != 'active' or row.get('ownerPhone') != phone
            or row.get('ownerCustomerId') not in (None, identity.customer_id)):
        raise customer_auth.CustomerNotAuthorized('file unavailable')
    # Adopt legacy phone-owned files only after an authenticated verified session.
    files.update_item(Key={'fileId': row['fileId']},
        UpdateExpression='SET ownerCustomerId=:owner',
        ConditionExpression='ownerPhone=:phone AND #s=:active AND '
                            '(attribute_not_exists(ownerCustomerId) OR ownerCustomerId=:owner)',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':owner': identity.customer_id, ':phone': phone, ':active': 'active'})
    row['ownerCustomerId'] = identity.customer_id
    return row


def grant_access(requests, keys, files, grants, event):
    ref = str(event.get('referenceId') or '')
    attempt = str(event.get('paymentAttemptId') or '')
    outcome = store.activate(requests, keys, reference_id=ref, payment_attempt_id=attempt)
    if outcome.outcome not in (store.ACTIVATED, store.ALREADY_ACTIVE):
        return None
    claim = order_keys.resolve_order_for_payment(keys, attempt) or {}
    oid = claim.get('orderIdRef')
    if not oid or oid != event.get('orderId'):
        return None
    pointer = requests.get_item(Key={'requestId': 'ORDER#' + oid}, ConsistentRead=True).get('Item') or {}
    row = requests.get_item(Key={'requestId': pointer.get('targetRequestId', '')}, ConsistentRead=True).get('Item') or {}
    payref = order_keys.resolve_payment_reference(keys, ref) or {}
    line = payref.get('serviceLine') or {}
    if (row.get('kind') != 'VAULT' or not row.get('paidAt') or not row.get('vaultFileId')
            or row.get('serviceVariantId') != VARIANT_ID or row.get('orderId') != oid
            or row.get('paymentAttemptId') != attempt or row.get('referenceId') != ref
            or payref.get('customerId') != row.get('customerId')
            or payref.get('paymentAttemptId') != attempt or line.get('variantId') != VARIANT_ID
            or line.get('kind') != 'VAULT'):
        return None
    file = files.get_item(Key={'fileId': row['vaultFileId']}, ConsistentRead=True).get('Item') or {}
    if (file.get('status') != 'active' or file.get('ownerCustomerId') != row.get('customerId')
            or file.get('ownerPhone') != row.get('vaultOwnerPhone')):
        requests.update_item(Key={'requestId': row['requestId']},
            UpdateExpression='SET vaultStatus=:s', ExpressionAttributeValues={':s': 'FILE_UNAVAILABLE'})
        return None
    gid = 'vault-' + hashlib.sha256((row['requestId'] + '|' + file['fileId']).encode()).hexdigest()
    existing = grants.get_item(Key={'grantId': gid}, ConsistentRead=True).get('Item')
    if existing:
        if (existing.get('customerId') != row['customerId'] or existing.get('fileId') != file['fileId']
                or existing.get('orderId') != oid or not existing.get('paid')):
            raise ValueError('grant ownership mismatch')
        return row, file, existing
    grant = {'grantId': gid, 'fileId': file['fileId'], 'ownerPhone': file['ownerPhone'],
             'customerId': row['customerId'], 'orderId': oid, 'reference': ref,
             'requestId': row['requestId'], 'source': 'wix_vault', 'paid': True,
             'consumed': False, 'createdAt': int(time.time())}
    # The original private file must still be active and owned at the grant commit.
    items = [store._put(grants.name, grant, 'attribute_not_exists(grantId)'),
        {'Update': {'TableName': files.name, 'Key': store._marshal_item({'fileId': file['fileId']}),
                    'UpdateExpression': 'SET vaultAccessGrantId=:g, vaultPaymentStatus=:paid, vaultOrderNumber=:number, vaultRequestNumber=:request',
                    'ConditionExpression': 'ownerCustomerId=:owner AND #s=:active',
                    'ExpressionAttributeNames': {'#s': 'status'},
                    'ExpressionAttributeValues': store._marshal_item({':g': gid, ':owner': row['customerId'], ':active': 'active', ':paid': 'PAID', ':number': str(row.get('orderNumber') or oid), ':request': row['publicRequestId']})}},
        {'Update': {'TableName': requests.name, 'Key': store._marshal_item({'requestId': row['requestId']}),
                    'UpdateExpression': 'SET vaultStatus=:ready, vaultGrantId=:g',
                    'ConditionExpression': 'customerId=:owner AND orderId=:o',
                    'ExpressionAttributeValues': store._marshal_item({':ready': 'READY', ':g': gid, ':owner': row['customerId'], ':o': oid})}}]
    try:
        store._transact(requests, items)
    except Exception:
        winner = grants.get_item(Key={'grantId': gid}, ConsistentRead=True).get('Item')
        if not winner or winner.get('customerId') != row['customerId'] or winner.get('fileId') != file['fileId'] or winner.get('orderId') != oid:
            raise
        grant = winner
    row.update(vaultStatus='READY', vaultGrantId=gid)
    return row, file, grant
