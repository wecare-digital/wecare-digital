"""Bind one private file to one verified Vault purchase; never charge.

A purchase is one ₹49 access window for one file. The first purchase creates the durable
VAULT_ENTITLEMENT; a later purchase of the same file (a renewal, sold only once every paid window
has been used) adds one to that entitlement's `paidWindowCount` instead of creating a second row.
"""
import hashlib
import time
from lambda_utils import customer_auth
from lambda_utils.ecommerce import order_keys, service_requests, service_request_store as store

#: Derived from the one catalogue map. #712 blanked a hand-copied literal here, after which
#: `grant_access` refused every real Vault payment: paid, but no entitlement and no download.
VARIANT_ID = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
FILES_TABLE = 'stack-wecare-digital-SecureFilesTable'
GRANTS_TABLE = 'stack-wecare-digital-DownloadGrantsTable'


def bind_file(files, identity, file_id):
    row = files.get_item(Key={'fileId': str(file_id)}, ConsistentRead=True).get('Item') or {}
    phone = ''.join(c for c in identity.phone if c.isdigit())
    if (not row or row.get('status') != 'active' or row.get('ownerPhone') != phone
            or not identity.customer_id or row.get('ownerCustomerId') != identity.customer_id):
        raise customer_auth.CustomerNotAuthorized('file unavailable')
    # A phone can be reassigned. Legacy ownerless files require explicit staff
    # reconciliation; a matching verified phone never establishes their original owner.
    files.update_item(Key={'fileId': row['fileId']},
        UpdateExpression='SET ownerCustomerId=:owner',
        ConditionExpression='ownerPhone=:phone AND #s=:active AND '
                            'ownerCustomerId=:owner',
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
        entitlement_id = existing.get('entitlementId') or (
            'vault-entitlement#' + row['customerId'] + '#' + file['fileId'])
        entitlement = grants.get_item(
            Key={'grantId': entitlement_id}, ConsistentRead=True).get('Item') or {}
        if not entitlement:
            entitlement = {
                'grantId': entitlement_id, 'recordType': 'VAULT_ENTITLEMENT',
                'entitlementState': 'ACTIVE', 'customerId': row['customerId'],
                'fileId': file['fileId'], 'ownerPhone': file['ownerPhone'],
                'sourceGrantId': existing['grantId'], 'orderId': oid, 'reference': ref,
                'requestId': row['requestId'], 'createdAt': int(time.time()),
                'paidAt': int(row.get('paidAt') or time.time()), 'paidWindowCount': 1,
            }
            try:
                grants.put_item(Item=entitlement, ConditionExpression='attribute_not_exists(grantId)')
            except Exception:
                entitlement = grants.get_item(
                    Key={'grantId': entitlement_id}, ConsistentRead=True).get('Item') or {}
        if entitlement.get('entitlementState') != 'ACTIVE':
            raise ValueError('entitlement unavailable')
        existing['entitlementId'] = entitlement_id
        return row, file, existing
    now = int(time.time())
    entitlement_id = 'vault-entitlement#' + row['customerId'] + '#' + file['fileId']
    current = grants.get_item(Key={'grantId': entitlement_id}, ConsistentRead=True).get('Item') or {}
    renewal = bool(current)
    if renewal and (current.get('recordType') != 'VAULT_ENTITLEMENT'
                    or current.get('entitlementState') != 'ACTIVE'
                    or current.get('customerId') != row['customerId']
                    or current.get('fileId') != file['fileId']):
        raise ValueError('entitlement unavailable')
    grant = {'grantId': gid, 'fileId': file['fileId'], 'ownerPhone': file['ownerPhone'],
             'customerId': row['customerId'], 'orderId': oid, 'reference': ref,
             'requestId': row['requestId'], 'source': 'vault_purchase', 'paid': True,
             'consumed': False, 'entitlementId': entitlement_id, 'createdAt': now,
             'renewal': renewal}
    if renewal:
        # One more paid window on the SAME entitlement. The grant Put below is conditional on its
        # own absence in the same transaction, so a replayed payment cannot add a second window.
        # A missing counter is the one original purchase, hence if_not_exists(..., 1) + 1.
        entitlement_write = {'Update': {
            'TableName': grants.name, 'Key': store._marshal_item({'grantId': entitlement_id}),
            'UpdateExpression': ('SET paidWindowCount = if_not_exists(paidWindowCount, :one) + :one, '
                                 'lastGrantId = :g, renewedAt = :now'),
            'ConditionExpression': ('recordType = :type AND entitlementState = :active '
                                    'AND customerId = :owner AND fileId = :file'),
            'ExpressionAttributeValues': store._marshal_item({
                ':one': 1, ':g': gid, ':now': now, ':type': 'VAULT_ENTITLEMENT',
                ':active': 'ACTIVE', ':owner': row['customerId'], ':file': file['fileId']})}}
    else:
        entitlement = {'grantId': entitlement_id, 'recordType': 'VAULT_ENTITLEMENT',
                       'entitlementState': 'ACTIVE', 'customerId': row['customerId'],
                       'fileId': file['fileId'], 'ownerPhone': file['ownerPhone'],
                       'sourceGrantId': gid, 'orderId': oid, 'reference': ref,
                       'requestId': row['requestId'], 'createdAt': now,
                       'paidAt': int(row.get('paidAt') or now), 'paidWindowCount': 1}
        entitlement_write = store._put(grants.name, entitlement, 'attribute_not_exists(grantId)')
    # The original private file must still be active and owned at the grant commit.
    items = [store._put(grants.name, grant, 'attribute_not_exists(grantId)'),
        entitlement_write,
        {'Update': {'TableName': files.name, 'Key': store._marshal_item({'fileId': file['fileId']}),
                    'UpdateExpression': 'SET vaultAccessGrantId=:g, vaultEntitlementId=:e, vaultPaymentStatus=:paid, vaultOrderNumber=:number, vaultRequestNumber=:request',
                    'ConditionExpression': 'ownerCustomerId=:owner AND #s=:active',
                    'ExpressionAttributeNames': {'#s': 'status'},
                    'ExpressionAttributeValues': store._marshal_item({':g': gid, ':e': entitlement_id, ':owner': row['customerId'], ':active': 'active', ':paid': 'PAID', ':number': str(row.get('orderNumber') or oid), ':request': row['publicRequestId']})}},
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
