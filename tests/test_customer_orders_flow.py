import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'amplify/functions/shared'))
sys.path.insert(0,str(ROOT/'tests'))
from coupon_fake_dynamo import FakeTable
from lambda_utils import customer_auth

@pytest.fixture
def hub():
    spec=importlib.util.spec_from_file_location('orders_flow_test', ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/customer_orders.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def test_hub_refuses_http_session_creation_without_reads(hub, monkeypatch):
    db=Mock(); monkeypatch.setattr(hub,'_db',db)
    assert hub.prepare({'requestContext':{}})['statusCode']==403
    db.assert_not_called()

@pytest.mark.parametrize('token',['', 'orders:guess', 'orders:https://example.com', 'paidsr:wrong'])
def test_forged_tokens_fail_before_customer_lookup(hub,monkeypatch,token):
    db=Mock();monkeypatch.setattr(hub,'_db',db)
    assert hub.route('INIT','',{},token)['screen']=='UNAVAILABLE'
    db.assert_not_called()

def test_owned_order_only_and_no_false_amount(hub):
    orders=FakeTable(key_attr='orderId'); identity=SimpleNamespace(customer_id='owner')
    orders.seed({'orderId':'a','customerId':'owner','orderNumber':'WD-ORD-A','amountPaise':9900,'currency':'INR','paymentStatus':'paid'})
    orders.seed({'orderId':'b','customerId':'foreign','orderNumber':'WD-ORD-B'})
    assert hub.order_details(orders,identity,'a')['amount']=='₹99.00'
    with pytest.raises(customer_auth.CustomerNotAuthorized): hub.order_details(orders,identity,'b')
    orders.rows['a']['amountPaise']=True
    assert hub.order_details(orders,identity,'a')['amount']=='Amount unavailable'

def test_account_output_uses_verified_records_not_client_fields(hub,monkeypatch):
    identity=SimpleNamespace(customer_id='owner',phone='+919000000000')
    monkeypatch.setattr(hub,'_context',lambda token:(Mock(),{'name':'Owner','email':'owner@example.com'},identity,{}))
    result=hub.route('INIT','',{'email':'attacker@example.com','phone':'+919999999999'},'ignored')
    assert result['data']['email']=='owner@example.com'
    assert result['data']['phone']==identity.phone
    assert result['data']['email_state']=='Verification needed'

def test_order_selection_rechecks_ownership(hub,monkeypatch):
    orders=FakeTable(key_attr='orderId'); orders.seed({'orderId':'x','customerId':'other','orderNumber':'WD-X'})
    db=Mock();db.Table.return_value=orders
    monkeypatch.setattr(hub,'_context',lambda token:(db,{},SimpleNamespace(customer_id='owner'),{}))
    assert hub.route('data_exchange','ORDERS',{'order_id':'x'},'ignored')['screen']=='UNAVAILABLE'
    assert hub.route('data_exchange','ORDERS',{'order_id':'not_found'},'ignored')['screen']=='ORDER_HELP'


def test_missing_order_help_is_saved_once_without_order_or_payment(hub):
    table=FakeTable(key_attr='submissionId')
    identity=SimpleNamespace(customer_id='owner',phone='+919000000000')
    data={'order_reference':'WD-ORD-MISSING','description':'Please locate the order from my receipt.'}
    a=hub.record_order_help(table,identity,'contact','opaque-session',data)
    b=hub.record_order_help(table,identity,'contact','opaque-session',{**data,'description':'Changed'})
    assert a==b
    assert len(table.rows)==1
    row=next(iter(table.rows.values()))
    assert row['status']=='awaiting_order_verification'
    assert row['customerId']=='owner' and row['orderReference']=='WD-ORD-MISSING'
    assert not any(k in row for k in ['orderId','paymentAttemptId','amountPaise'])


def test_missing_number_is_allowed_but_request_context_required(hub):
    table=FakeTable(key_attr='submissionId'); identity=SimpleNamespace(customer_id='owner',phone='+919000000000')
    with pytest.raises(ValueError): hub.record_order_help(table,identity,'contact','token',{'description':''})
    assert not table.rows
    assert hub.record_order_help(table,identity,'contact','token',{'description':'I cannot find the number either.'})


def test_orders_capability_is_never_logged():
    from lambda_utils.privacy import mask_flow_token
    assert mask_flow_token('orders:' + 'A' * 43) == 'orders:***'


def test_order_pagination_cursor_is_server_owned(hub):
    identity=SimpleNamespace(customer_id='owner')
    orders=Mock(); orders.query.return_value={'Items':[], 'LastEvaluatedKey':{'customerId':'owner','orderId':'last','createdAt':1}}
    keys=Mock();db=Mock();db.Table.side_effect=lambda name: orders if name.endswith('OrderTable') else keys
    response=hub.order_page(db,identity,{},'token')
    assert response['data']['orders'][0]['id']=='more_orders'
    assert 'ExclusiveStartKey' not in orders.query.call_args.kwargs
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        hub.order_page(db,identity,{'orderCursor':{'customerId':'foreign'}},'token',next_page=True)
    assert orders.query.call_count==1
    hub.order_page(db,identity,{'orderCursor':{'customerId':'owner','orderId':'last','createdAt':1}},'token',next_page=True)
    assert orders.query.call_args.kwargs['ExclusiveStartKey']['orderId']=='last'


def test_expired_session_refuses_before_identity_lookup(hub,monkeypatch):
    keys=Mock();keys.get_item.return_value={'Item':{'expiresAt':1,'customerId':'owner'}}
    db=Mock();db.Table.return_value=keys; monkeypatch.setattr(hub,'_db',lambda:db)
    verify=Mock();monkeypatch.setattr(hub,'_verified',verify)
    assert hub.route('INIT','',{},'orders:'+'A'*43)['screen']=='UNAVAILABLE'
    verify.assert_not_called()


def test_session_customer_cannot_be_rebound_to_recreated_contact(hub,monkeypatch):
    keys=Mock();keys.get_item.return_value={'Item':{'expiresAt':9999999999,'customerId':'original','contactId':'c','phone':'+919000000000'}}
    db=Mock();db.Table.return_value=keys; monkeypatch.setattr(hub,'_db',lambda:db)
    monkeypatch.setattr(hub,'_verified',lambda *args:({},SimpleNamespace(customer_id='replacement')))
    assert hub.route('INIT','',{},'orders:'+'A'*43)['screen']=='UNAVAILABLE'


def test_profile_update_rejects_identity_and_unverified_email_fields(hub):
    db=Mock();identity=SimpleNamespace(customer_id='owner')
    for key in ['phone','email','emailVerifiedAt','customerUuid','customerId']:
        with pytest.raises(ValueError): hub.update_profile(db,{'id':'c'},identity,{key:'forged'})
    db.Table.assert_not_called()


def test_profile_update_changes_contact_only_and_retains_owner_condition(hub):
    db=Mock();identity=SimpleNamespace(customer_id='owner')
    hub.update_profile(db,{'id':'c'},identity,{'first_name':'Asha','last_name':'Das',
        'address_line1':'12 Park Street','address_line2':'','city':'Kolkata','state':'West Bengal',
        'postal_code':'700016','country_code':'IN'})
    assert db.Table.call_args.args[0]=='stack-wecare-digital-ContactsTable'
    update=db.Table.return_value.update_item.call_args.kwargs
    assert 'checkoutCustomerId=:owner' in update['ConditionExpression']
    assert update['ExpressionAttributeValues'][':owner']=='owner'
    assert 'emailVerifiedAt' not in update['UpdateExpression']
