"""Paid service and parent order remain distinct, with ownership at commit."""
import copy
import pathlib
import sys
from unittest.mock import patch
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_service_request_store import submitted, ALICE, BOB
from service_requests_fake_dynamo import RequestTable, KeysTable, FakeClientError
from coupon_fake_dynamo import FakeTable, _deserialise_map, _evaluate_condition, _apply_update
from lambda_utils.ecommerce import paid_submit_request as paid
from lambda_utils.privacy import mask_flow_token

@pytest.fixture
def setup():
    requests, keys = RequestTable(), KeysTable()
    submitted(requests, keys)
    row = next(copy.deepcopy(v) for k, v in requests.rows.items() if k.startswith('REQ#'))
    orders = FakeTable(key_attr='orderId', name='orders', indexes={'customerId-createdAt-index': ('customerId','createdAt')})
    orders.seed({'orderId': 'earlier', 'customerId': ALICE, 'createdAt': 1, 'orderNumber':'WD-ORD-OLD'})
    orders.seed({'orderId': 'foreign', 'customerId': BOB, 'createdAt': 1})
    orders.seed({'orderId': row['orderId'], 'customerId': ALICE, 'createdAt': 2})
    return requests, keys, orders, row


def test_paid_capability_resumes_and_is_redacted(setup):
    requests, keys, _, row = setup
    first, token = paid.prepare(requests, keys, row['requestId'])
    assert first['detailsStatus'] == 'AWAITING_DETAILS'
    assert paid.prepare(requests, keys, row['requestId'])[1] == token
    assert paid.resolve(requests, keys, token)['orderId'] == row['orderId']
    assert token not in mask_flow_token(token)
    with pytest.raises(paid.RequestUnavailable):
        paid.resolve(requests, keys, token[:-1] + ('a' if token[-1] != 'a' else 'b'))

@pytest.mark.parametrize('damage', ['claim', 'owner', 'variant', 'paid'])
def test_no_entitlement_without_matching_paid_purchase(setup, damage):
    requests, keys, _, row = setup
    if damage == 'claim':
        keys.rows.pop('PAYMENTATTEMPT#' + row['paymentAttemptId'])
    elif damage == 'owner':
        keys.rows['PAYREF#' + row['referenceId']]['customerId'] = BOB
    elif damage == 'variant':
        keys.rows['PAYREF#' + row['referenceId']]['serviceLine']['variantId'] = 'amendment'
    else:
        requests.rows[row['requestId']].pop('paidAt')
    with pytest.raises(paid.RequestUnavailable):
        paid.prepare(requests, keys, row['requestId'])
    assert 'requestFlowToken' not in requests.rows[row['requestId']]


def test_only_owned_earlier_orders_and_missing_orders_preserve_payment(setup):
    requests, keys, orders, row = setup
    assert paid.list_orders(orders, row) == [{'id':'earlier','title':'WD-ORD-OLD'}]
    orders.rows.clear()
    assert paid.list_orders(orders, row) == []
    assert paid.prepare(requests, keys, row['requestId'])[0]['paidAt']

@pytest.mark.parametrize('order', ['foreign', 'missing', 'purchase'])
def test_foreign_missing_and_service_purchase_cannot_be_parent(setup, order):
    requests, keys, orders, row = setup
    _, token = paid.prepare(requests, keys, row['requestId'])
    with pytest.raises(paid.RequestUnavailable):
        paid.submit(requests, keys, orders, token, {'record_id':row['orderId'] if order == 'purchase' else order,
                                                  'subject':'Help', 'description':'Details'})
    assert 'parentOrderId' not in requests.rows[row['requestId']]


def commit(requests, orders, items):
    """Evaluate both actual conditions before applying either transaction operation."""
    operations = []
    for item in items:
        operation, body = next(iter(item.items()))
        table = orders if body['TableName'] == orders.name else requests
        key = _deserialise_map(body['Key'], where='key')[table.key_attr]
        values = _deserialise_map(body.get('ExpressionAttributeValues', {}), where='values')
        assert operation in ('ConditionCheck','Update')
        if not _evaluate_condition(body['ConditionExpression'], table.rows.get(key), values, {}):
            raise FakeClientError('TransactionCanceledException')
        operations.append((operation, body, table, key, values))
    for operation, body, table, key, values in operations:
        if operation == 'Update':
            table.rows[key] = _apply_update(body['UpdateExpression'], table.rows[key], values, {})


def test_submit_once_separates_service_order_parent_order_and_request(setup):
    requests, keys, orders, row = setup
    _, token = paid.prepare(requests, keys, row['requestId'])
    data = {'record_id':'earlier', 'subject':'Access documents', 'description':'Please help'}
    with patch.object(paid.store, '_transact', side_effect=lambda table, items: commit(table, orders, items)) as tx:
        saved = paid.submit(requests, keys, orders, token, data)
        assert saved['parentOrderId'] == 'earlier'
        assert saved['orderId'] == row['orderId']
        assert saved['detailsStatus'] == 'READY'
        again = paid.submit(requests, keys, orders, token, {**data,'subject':'Changed'})
        assert again['subject'] == 'Access documents'
        assert tx.call_count == 1
    assert len([k for k in requests.rows if k.startswith('REQ#')]) == 1
    assert keys.writes() == []


def test_order_ownership_change_between_read_and_commit_refuses_submission(setup):
    requests, keys, orders, row = setup
    _, token = paid.prepare(requests, keys, row['requestId'])
    def race(table, items):
        orders.rows['earlier']['customerId'] = BOB
        commit(table, orders, items)
    with patch.object(paid.store, '_transact', side_effect=race), pytest.raises(FakeClientError):
        paid.submit(requests, keys, orders, token, {'record_id':'earlier','subject':'Help','description':'Details'})
    assert 'detailsSubmittedAt' not in requests.rows[row['requestId']]

@pytest.fixture
def flow_module(monkeypatch):
    import importlib
    monkeypatch.syspath_prepend(str(pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-business-api'))
    return importlib.import_module('flows.paid_submit_request')


def test_flow_back_does_not_submit_and_completion_repairs_workspace(setup, flow_module, monkeypatch):
    requests, keys, orders, row = setup
    _, token = paid.prepare(requests, keys, row['requestId'])
    monkeypatch.setattr(flow_module, 'tables', lambda: (requests, keys, orders))
    with patch.object(paid, 'submit') as submit, patch.object(flow_module, 'mirror'):
        flow_module.route('BACK','REVIEW',{},token)
        submit.assert_not_called()
    assert flow_module.route('INIT','',{},token)['screen'] == 'SELECT_RECORD'
    orders.rows.clear()
    assert flow_module.route('INIT','',{},token)['screen'] == 'NO_ORDERS'
    assert requests.rows[row['requestId']]['detailsStatus'] == 'AWAITING_DETAILS'
    assert flow_module.route('INIT','',{},token+'bad')['screen'] == 'UNAVAILABLE'


def test_internal_hint_prepares_draft_without_sending(setup, flow_module, monkeypatch):
    from unittest.mock import Mock
    import json
    requests, keys, orders, row = setup
    monkeypatch.setattr(flow_module, 'tables', lambda: (requests, keys, orders))
    client = Mock()
    meta = lambda _: {'body': json.dumps({'flow':{'status':'DRAFT'}})}
    result = flow_module.prepare_and_send({'referenceId':row['referenceId'],
        'paymentAttemptId':row['paymentAttemptId'],'orderId':row['orderId']},client,meta)
    assert result['outcome'] == 'FLOW_DRAFT'
    assert requests.rows[row['requestId']]['requestFlowToken'].startswith('paidsr:')
    client.invoke.assert_not_called()


def test_internal_send_requires_verified_owner_contact_and_current_window(setup, flow_module, monkeypatch):
    from unittest.mock import Mock
    import json, io, time
    requests, keys, orders, row = setup
    monkeypatch.setattr(flow_module, 'tables', lambda: (requests, keys, orders))
    contact = FakeTable(key_attr='id',name='contacts',indexes={'phone-index':('phone',None)})
    contact.seed({'id':'contact','phone':'+919999999999','checkoutCustomerId':ALICE,
                  'lastInboundMessageAt':int(time.time())})
    db=Mock();db.Table.return_value=contact
    cognito=Mock();cognito.list_users.return_value={'Users':[{'Attributes':[
        {'Name':'phone_number','Value':'+919999999999'}, {'Name':'phone_number_verified','Value':'true'}]}]}
    monkeypatch.setattr(flow_module.boto3,'resource',lambda *a,**k: db)
    monkeypatch.setattr(flow_module.boto3,'client',lambda *a,**k: cognito)
    meta=lambda _: {'body':json.dumps({'flow':{'status':'PUBLISHED'}})}
    event={'referenceId':row['referenceId'],'paymentAttemptId':row['paymentAttemptId'],'orderId':row['orderId']}
    client=Mock();client.invoke.return_value={'Payload':io.BytesIO(json.dumps({'statusCode':200}).encode())}
    contact.rows['contact']['checkoutCustomerId']=BOB
    assert flow_module.prepare_and_send(event,client,meta)['outcome']=='CONTACT_LINK_UNAVAILABLE'
    contact.rows['contact']['checkoutCustomerId']=ALICE
    contact.rows['contact']['deletedAt']=int(time.time())
    assert flow_module.prepare_and_send(event,client,meta)['outcome']=='CONTACT_LINK_UNAVAILABLE'
    contact.rows['contact'].pop('deletedAt')
    contact.rows['contact']['lastInboundMessageAt']=0
    assert flow_module.prepare_and_send(event,client,meta)['outcome']=='AWAITING_CUSTOMER_MESSAGE'
    client.invoke.assert_not_called()
    contact.rows['contact']['lastInboundMessageAt']=int(time.time())
    assert flow_module.prepare_and_send(event,client,meta)['outcome']=='INVITATION_ACCEPTED'
    assert flow_module.prepare_and_send(event,client,meta)['outcome']=='INVITATION_ALREADY_CLAIMED'
    assert client.invoke.call_count==1
    payload=json.loads(client.invoke.call_args.kwargs['Payload'])
    message=json.loads(payload['body'])
    assert message['interactiveData']['flowAction']=='data_exchange'
    assert message['interactiveData']['flowToken'].startswith('paidsr:')


def test_workspace_mirror_keeps_both_orders_and_omits_empty_index_keys(setup, flow_module, monkeypatch):
    from unittest.mock import Mock
    requests, _, _, row = setup
    row.update({'detailsSubmittedAt':123,'parentOrderId':'earlier','subject':'Help','description':'Details'})
    db=Mock();table=Mock();db.Table.return_value=table
    monkeypatch.setattr(flow_module.boto3,'resource',lambda *a,**k:db)
    flow_module.mirror(row)
    item=table.put_item.call_args.kwargs['Item']
    assert item['orderId']=='earlier'
    assert item['serviceOrderId']==row['orderId']
    assert item['submissionId']==row['publicRequestId']
    assert 'phone' not in item and 'contactId' not in item
    assert 'requestFlowToken' not in item
