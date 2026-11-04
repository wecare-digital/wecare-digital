"""Two payable Vault cards for ONE file, customer pays both (owner decision 2026-11-04: option b).

Pins today's settlement behaviour through the REAL `vault_access.grant_access`:
  * the first capture creates ONE durable VAULT_ENTITLEMENT (paidWindowCount 1);
  * the second capture adds ONE more paid window to that SAME entitlement (paidWindowCount 2);
  * no second entitlement row is ever created, in either capture order;
  * a replayed capture of the same card never adds another window.
In-memory tables only; no AWS.
"""
import copy
from types import SimpleNamespace

import pytest
from boto3.dynamodb.types import TypeDeserializer

from lambda_utils.ecommerce import order_keys, service_request_store as store, vault_access

CUSTOMER = '940844d8-c031-70cf-4398-f1a58831231b'
PHONE = '919000000001'
FILE_ID = 'f' * 32 + '-' + 'e' * 32
VARIANT = vault_access.VARIANT_ID


class Table:
    def __init__(self, key, name):
        self.key, self.rows, self.name = key, {}, name

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get(Key[self.key])
        return {'Item': copy.deepcopy(row)} if row else {}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression == 'attribute_not_exists(grantId)' and Item[self.key] in self.rows:
            raise RuntimeError('ConditionalCheckFailed')
        self.rows[Item[self.key]] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression='', ExpressionAttributeValues=None, **_):
        row = self.rows.setdefault(Key[self.key], dict(Key))
        if 'vaultStatus' in UpdateExpression:
            row['vaultStatus'] = (ExpressionAttributeValues or {}).get(':s')


def card(requests, n):
    """One paid Vault card: its request row, ORDER# pointer and PAYREF/attempt claim."""
    rid, oid, ref, att = f'REQ#{n}', f'order-{n}', f'WD-PAY-CARD{n}', f'attempt-{n}'
    requests.rows[rid] = {'requestId': rid, 'kind': 'VAULT', 'paidAt': 1793780000 + n,
                          'vaultFileId': FILE_ID, 'serviceVariantId': VARIANT, 'orderId': oid,
                          'paymentAttemptId': att, 'referenceId': ref, 'customerId': CUSTOMER,
                          'vaultOwnerPhone': PHONE, 'publicRequestId': f'WD-REQ-{n}', 'orderNumber': f'WD-ORD-{n}'}
    requests.rows['ORDER#' + oid] = {'requestId': 'ORDER#' + oid, 'targetRequestId': rid}
    return {'referenceId': ref, 'paymentAttemptId': att, 'orderId': oid}


@pytest.fixture
def world(monkeypatch):
    requests, keys = Table('requestId', 'requests'), Table('orderId', 'keys')
    files = Table('fileId', vault_access.FILES_TABLE)
    grants = Table('grantId', vault_access.GRANTS_TABLE)
    files.rows[FILE_ID] = {'fileId': FILE_ID, 'status': 'active', 'ownerCustomerId': CUSTOMER,
                           'ownerPhone': PHONE}
    events = {}

    monkeypatch.setattr(store, 'activate', lambda *a, **k: SimpleNamespace(outcome=store.ACTIVATED))
    monkeypatch.setattr(order_keys, 'resolve_order_for_payment',
                        lambda _k, att: {'orderIdRef': events[att]['orderId']})
    monkeypatch.setattr(order_keys, 'resolve_payment_reference',
                        lambda _k, ref: {'customerId': CUSTOMER,
                                         'paymentAttemptId': next(e['paymentAttemptId'] for e in events.values() if e['referenceId'] == ref),
                                         'serviceLine': {'variantId': VARIANT, 'kind': 'VAULT'}})

    def transact(_requests_table, items):
        # Apply the grant/entitlement writes the way DynamoDB would, including conditions.
        for op in items:
            if 'Put' in op and op['Put']['TableName'] == vault_access.GRANTS_TABLE:
                item = {k: TypeDeserializer().deserialize(v) for k, v in op['Put']['Item'].items()}
                if item['grantId'] in grants.rows:
                    raise RuntimeError('TransactionCanceled')
                grants.rows[item['grantId']] = item
            elif 'Update' in op and op['Update']['TableName'] == vault_access.GRANTS_TABLE:
                gid = TypeDeserializer().deserialize(op['Update']['Key']['grantId'])
                row = grants.rows[gid]
                row['paidWindowCount'] = int(row.get('paidWindowCount', 1)) + 1
    monkeypatch.setattr(store, '_transact', transact)
    return requests, keys, files, grants, events


def pay(world, n):
    requests, keys, files, grants, events = world
    ev = card(requests, n)
    events[ev['paymentAttemptId']] = ev
    return vault_access.grant_access(requests, keys, files, grants, ev)


def entitlements(grants):
    return [g for g in grants.rows.values() if g.get('recordType') == 'VAULT_ENTITLEMENT']


@pytest.mark.parametrize('order', [(1, 2), (2, 1)])
def test_second_paid_card_adds_one_window_to_the_same_entitlement(world, order):
    first, second = order
    assert pay(world, first) is not None
    ents = entitlements(world[3])
    assert len(ents) == 1 and int(ents[0].get('paidWindowCount', 1)) == 1

    assert pay(world, second) is not None
    ents = entitlements(world[3])
    assert len(ents) == 1, 'a second payment must never create a second entitlement'
    assert int(ents[0]['paidWindowCount']) == 2, 'option (b): the second payment adds one window'
    purchase_grants = [g for g in world[3].rows.values() if g.get('source') == 'vault_purchase']
    assert len(purchase_grants) == 2 and all(g['paid'] for g in purchase_grants)


def test_replayed_capture_of_the_same_card_adds_no_extra_window(world):
    requests, keys, files, grants, events = world
    assert pay(world, 1) is not None
    replay = events['attempt-1']
    assert vault_access.grant_access(requests, keys, files, grants, replay) is not None
    ents = entitlements(grants)
    assert len(ents) == 1 and int(ents[0].get('paidWindowCount', 1)) == 1
