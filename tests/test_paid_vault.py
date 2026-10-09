import copy
import importlib
import io
import json
import time
import sys
import pathlib
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from unittest.mock import Mock
import pytest
from test_service_request_store import who, pay, ALICE, BOB
from test_paid_submit_request import flow_module
from test_service_requests_handler import env, call, PHONE
from test_secure_files import mod
from service_requests_fake_dynamo import RequestTable, KeysTable, FakeClientError
from coupon_fake_dynamo import FakeTable, _deserialise_map, _evaluate_condition, _apply_update
from lambda_utils import customer_auth
from lambda_utils.ecommerce import service_request_store as store, vault_access as vault


@pytest.fixture
def vault_env(monkeypatch):
    requests, keys = RequestTable(), KeysTable()
    files = FakeTable(key_attr='fileId', name=vault.FILES_TABLE)
    grants = FakeTable(key_attr='grantId', name=vault.GRANTS_TABLE)
    file = {'fileId':'file-1','ownerPhone':'910000000000','ownerCustomerId':ALICE,'status':'active',
            'displayName':'Report','originalFilename':'report.pdf', 'deliverable':'pdf',
            'deliveryKey':'secure/d/report.pdf'}
    files.seed(file)
    file = vault.bind_file(files,who(),file['fileId'])
    intent = store.request_intent(requests,who(),'VAULT',vault_file=file)
    ref, attempt, oid = pay(keys,intent,paise=4900)
    tables = {t.name:t for t in (files,grants,requests)}
    original = store._transact
    def transaction(table,items):
        if all(next(iter(i.values()))['TableName']==requests.name for i in items):
            return original(table,items)
        edits=[]
        for item in items:
            op,body=next(iter(item.items())); target=tables[body['TableName']]
            data=_deserialise_map(body.get('Item',body.get('Key',{})),where='key')
            key=data[target.key_attr]
            values=_deserialise_map(body.get('ExpressionAttributeValues',{}),where='values')
            names=body.get('ExpressionAttributeNames',{})
            if not _evaluate_condition(body['ConditionExpression'],target.rows.get(key),values,names):
                raise FakeClientError('TransactionCanceledException')
            edits.append((op,body,target,key,data,values,names))
        for op,body,target,key,data,values,names in edits:
            target.rows[key] = data if op=='Put' else _apply_update(body['UpdateExpression'],target.rows[key],values,names)
    monkeypatch.setattr(store,'_transact',transaction)
    event={'referenceId':ref,'paymentAttemptId':attempt,'orderId':oid}
    return requests,keys,files,grants,event


def test_file_bound_intent_and_one_grant_per_verified_purchase(vault_env):
    requests,keys,files,grants,event=vault_env
    result=vault.grant_access(requests,keys,files,grants,event)
    row,file,grant=result
    assert row['kind']=='VAULT' and row['amountPaise']==4900
    assert file['ownerCustomerId']==ALICE
    assert grant['orderId']==event['orderId'] and grant['paid'] and not grant['consumed']
    entitlement_id='vault-entitlement#'+ALICE+'#'+file['fileId']
    assert grant['entitlementId']==entitlement_id
    assert grants.rows[entitlement_id]['recordType']=='VAULT_ENTITLEMENT'
    assert grants.rows[entitlement_id]['entitlementState']=='ACTIVE'
    assert 'expiresAt' not in grants.rows[entitlement_id]
    assert files.rows[file['fileId']]['vaultAccessGrantId']==grant['grantId']
    assert files.rows[file['fileId']]['vaultEntitlementId']==entitlement_id
    assert files.rows[file['fileId']]['vaultPaymentStatus']=='PAID'
    assert vault.grant_access(requests,keys,files,grants,event)[2]['grantId']==grant['grantId']
    assert len(grants.rows)==2


@pytest.mark.parametrize('damage',['unpaid','wrong_order','foreign_file','revoked'])
def test_missing_proof_or_wrong_file_never_grants(vault_env,damage):
    requests,keys,files,grants,event=vault_env
    if damage=='unpaid': keys.rows.pop('PAYMENTATTEMPT#'+event['paymentAttemptId'])
    elif damage=='wrong_order': event['orderId']='foreign'
    elif damage=='foreign_file': files.rows['file-1']['ownerCustomerId']=BOB
    else: files.rows['file-1']['status']='revoked'
    assert vault.grant_access(requests,keys,files,grants,event) is None
    assert not grants.rows


@pytest.mark.parametrize('damage',['phone','identity','pending'])
def test_file_selection_rejects_foreign_or_incomplete_uploads(damage):
    files=FakeTable(key_attr='fileId',name='files')
    file={'fileId':'f','ownerPhone':'910000000000','status':'active'}
    if damage=='phone': file['ownerPhone']='919999999999'
    elif damage=='identity': file['ownerCustomerId']=BOB
    else: file['status']='pending'
    files.seed(file)
    with pytest.raises(customer_auth.CustomerNotAuthorized): vault.bind_file(files,who(),'f')


def test_different_file_changes_intent_before_payment(vault_env):
    requests,_,files,_,_=vault_env
    other=copy.deepcopy(files.rows['file-1']);other['fileId']='file-2'
    a=store.request_intent(requests,who(),'VAULT',vault_file=files.rows['file-1'])
    b=store.request_intent(requests,who(),'VAULT',vault_file=other)
    assert a['intentId']!=b['intentId']
    assert requests.rows['INTENT#'+b['intentId']]['vaultFileId']=='file-2'


@pytest.mark.parametrize('paid_field', ['vaultPaymentStatus', 'vaultAccessGrantId'])
def test_paid_file_cannot_create_a_new_purchase_intent(vault_env, paid_field):
    requests, _, files, _, _ = vault_env
    file = copy.deepcopy(files.rows['file-1'])
    file[paid_field] = 'PAID' if paid_field == 'vaultPaymentStatus' else 'existing-grant'
    before = copy.deepcopy(requests.rows)
    with pytest.raises(store.ServiceRejected, match='VAULT_ALREADY_PAID'):
        store.request_intent(requests, who(), 'VAULT', vault_file=file)
    assert requests.rows == before


@pytest.mark.parametrize('open_window',[True,False])
def test_notification_document_and_review_sequence_is_once_only(vault_env,flow_module,monkeypatch,open_window):
    module=importlib.import_module('flows.paid_vault')
    requests,keys,files,grants,event=vault_env
    contacts=FakeTable(key_attr='id',name='contacts',indexes={'phone-index':('phone',None)})
    contacts.seed({'id':'c','phone':'+910000000000','checkoutCustomerId':ALICE,
                   'lastInboundMessageAt':int(time.time()) if open_window else 0})
    tables={requests.name:requests, 'stack-wecare-digital-WixOrderIds':keys,
            files.name:files,grants.name:grants,'stack-wecare-digital-ContactsTable':contacts}
    db=Mock();db.Table.side_effect=lambda name:tables[name]
    cognito=Mock();cognito.list_users.return_value={'Users':[{'Enabled':True,'Attributes':[
        {'Name':'phone_number','Value':'+910000000000'},{'Name':'phone_number_verified','Value':'true'}]}]}
    monkeypatch.setattr(module.boto3,'resource',lambda *a,**k:db)
    monkeypatch.setattr(module.boto3,'client',lambda *a,**k:cognito)
    sent=[]
    def invoke(**kwargs):
        sent.append(json.loads(json.loads(kwargs['Payload'])['body']))
        return {'Payload':io.BytesIO(json.dumps({'statusCode':200}).encode())}
    client=Mock();client.invoke.side_effect=invoke
    assert module.prepare_and_send(event,client)['outcome']==('VAULT_READY' if open_window else 'VAULT_DELIVERY_DEFERRED')
    assert module.prepare_and_send(event,client)['outcome']==('VAULT_READY' if open_window else 'VAULT_DELIVERY_DEFERRED')
    assert sent[0]['templateName']=='wecare_share_pdf'
    assert all(message.get('templateName')!='wecare_leave_review' for message in sent)
    assert len(sent)==(2 if open_window else 1)
    if open_window: assert sent[1]['mediaType']=='document' and sent[1]['mediaFile']=='secure/d/report.pdf'


def test_vault_review_is_due_after_access_and_deduplicated(vault_env,flow_module,monkeypatch):
    module=importlib.import_module('flows.paid_vault')
    requests,keys,files,grants,event=vault_env
    row, _file, _grant = vault.grant_access(requests,keys,files,grants,event)
    requests.rows[row['requestId']]['paidAt']=int(time.time())
    contacts=FakeTable(key_attr='id',name='contacts',indexes={'phone-index':('phone',None)})
    contacts.seed({'id':'c','phone':'+910000000000','checkoutCustomerId':ALICE})
    tables={requests.name:requests,'stack-wecare-digital-ContactsTable':contacts}
    db=Mock();db.Table.side_effect=lambda name:tables[name]
    cognito=Mock();cognito.list_users.return_value={'Users':[{'Enabled':True,'Attributes':[
        {'Name':'phone_number','Value':'+910000000000'},
        {'Name':'phone_number_verified','Value':'true'}]}]}
    monkeypatch.setattr(module.boto3,'resource',lambda *a,**k:db)
    monkeypatch.setattr(module.boto3,'client',lambda *a,**k:cognito)
    sent=[]
    def invoke(**kwargs):
        sent.append(json.loads(json.loads(kwargs['Payload'])['body']))
        return {'Payload':io.BytesIO(json.dumps({'statusCode':200}).encode())}
    client=Mock();client.invoke.side_effect=invoke
    first=module.send_review({'requestId':row['requestId']},client)
    second=module.send_review({'requestId':row['requestId']},client)
    assert first['outcome']=='REVIEW_ACCEPTED'
    assert second['outcome']=='REVIEW_ACCEPTED'
    assert len(sent)==1
    assert sent[0]['templateName']=='wecare_leave_review'
    assert sent[0]['flowButton']=={'index':0,'flowKey':'leave_review'}


def test_ambiguous_ready_notification_never_retries_blindly(vault_env,flow_module,monkeypatch):
    module=importlib.import_module('flows.paid_vault')
    requests,_,_,_,_=vault_env
    row={'requestId':'REQ#test'}; requests.seed(row)
    client=Mock();client.invoke.return_value={'Payload':io.BytesIO(b'{"statusCode":502}')}
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{'templateName':'wecare_share_pdf'})
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert client.invoke.call_count==1
    assert requests.rows[row['requestId']]['vaultNotificationStatus']=='SEND_UNKNOWN'


def test_definite_send_rejection_can_retry_after_backoff(vault_env, flow_module, monkeypatch):
    module=importlib.import_module('flows.paid_vault')
    requests, _, _, _, _=vault_env
    row={'requestId':'REQ#retry'}; requests.seed(row)
    clock=[1000]; monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    client=Mock(); client.invoke.side_effect=[
        {'Payload':io.BytesIO(b'{"statusCode":400}')},
        {'Payload':io.BytesIO(b'{"statusCode":200}')},
    ]
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert client.invoke.call_count==1
    clock[0]+=31
    assert module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert client.invoke.call_count==2


def test_outbound_exception_records_ambiguity_without_second_send(vault_env, flow_module):
    module=importlib.import_module('flows.paid_vault')
    requests, _, _, _, _=vault_env
    row={'requestId':'REQ#unknown'}; requests.seed(row)
    client=Mock(); client.invoke.side_effect=TimeoutError('provider acceptance unknown')
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
    assert client.invoke.call_count==1
    assert requests.rows[row['requestId']]['vaultNotificationStatus']=='SEND_UNKNOWN'


@pytest.mark.parametrize('verified',[True,False])
def test_http_selection_requires_verified_phone_before_binding(env,monkeypatch,verified):
    files=FakeTable(key_attr='fileId',name=vault.FILES_TABLE)
    files.seed({'fileId':'f','ownerPhone':PHONE[1:],'ownerCustomerId':ALICE,'status':'active','displayName':'Report'})
    old=env._table
    monkeypatch.setattr(env,'_table',lambda name:files if name==vault.FILES_TABLE else old(name))
    cognito=Mock();cognito.get_user.return_value={'UserAttributes':[
        {'Name':'phone_number_verified','Value':'true' if verified else 'false'},
        {'Name':'phone_number','Value':PHONE},{'Name':'sub','Value':ALICE}]}
    monkeypatch.setattr(env.boto3,'client',lambda *a,**k:cognito)
    status,body,_=call(env,'/services/request-intent',{'kind':'VAULT','fileId':'f'})
    assert status==(200 if verified else 401)
    if verified:
        assert body['kind']=='VAULT'
        assert files.rows['f']['ownerCustomerId']==ALICE
    else:
        assert files.rows['f']['ownerCustomerId']==ALICE
        assert not env.requests_table.rows


def test_vault_file_list_exposes_renewable_paid_access_only_to_permanent_owner(mod,monkeypatch):
    files=FakeTable(key_attr='fileId',name='files',indexes={'owner-created-index':('ownerPhone','createdAt')})
    grants=FakeTable(key_attr='grantId',name='grants')
    files.seed({'fileId':'f','ownerPhone':'910000000000','ownerCustomerId':ALICE,
                'status':'active','createdAt':1,'vaultAccessGrantId':'g'})
    # Historical paid+consumed evidence must still migrate to durable entitlement.
    grants.seed({'grantId':'g','fileId':'f','ownerPhone':'910000000000',
                 'customerId':ALICE,'paid':True,'consumed':True,'orderId':'o1'})
    monkeypatch.setattr(mod,'_table',lambda name:files if name==mod.FILES_TABLE else grants)
    response=mod._customer_list({'phone':'910000000000','subject':ALICE},'')
    body=json.loads(response['body'])
    eid='vault-entitlement#'+ALICE+'#f'
    assert body['files'][0]['paidEntitlementId']==eid
    assert body['files'][0]['paidGrantId']==eid
    assert grants.rows[eid]['recordType']=='VAULT_ENTITLEMENT'
    assert 'expiresAt' not in grants.rows[eid]
    response=mod._customer_list({'phone':'910000000000','subject':BOB},'')
    assert json.loads(response['body'])['files']==[]


def test_paid_entitlement_can_issue_repeated_fresh_sessions_without_second_payment(mod,monkeypatch):
    files=FakeTable(key_attr='fileId',name='files')
    grants=FakeTable(key_attr='grantId',name='grants')
    files.seed({'fileId':'f','ownerPhone':'910000000000','ownerCustomerId':ALICE,
                'status':'active','s3Key':'secure/u/f.pdf','originalFilename':'f.pdf'})
    eid='vault-entitlement#'+ALICE+'#f'
    grants.seed({'grantId':eid,'recordType':'VAULT_ENTITLEMENT','entitlementState':'ACTIVE',
                 'fileId':'f','ownerPhone':'910000000000','customerId':ALICE,'paidAt':1})
    monkeypatch.setattr(mod,'_table',lambda name:files if name==mod.FILES_TABLE else grants)
    counter={'n':0}
    def fresh(_item, ttl=None):
        counter['n']+=1
        return 'https://signed.example/'+str(counter['n'])
    monkeypatch.setattr(mod,'_download_url',fresh)
    identity={'phone':'910000000000','subject':ALICE}
    event={'queryStringParameters':{'grant':eid}}
    first=mod._redeem('f',event,identity,'')
    second=mod._redeem('f',event,identity,'')
    a=json.loads(first['body']); b=json.loads(second['body'])
    assert first['statusCode']==200 and second['statusCode']==200
    assert a['downloadUrl']!=b['downloadUrl']
    assert a['downloadSessionId']!=b['downloadSessionId']
    assert a['entitlementId']==eid==b['entitlementId']
    assert grants.rows[eid]['entitlementState']=='ACTIVE'
    sessions=[x for x in grants.rows.values() if x.get('recordType')=='VAULT_DOWNLOAD_SESSION']
    assert len(sessions)==2
    assert all(x.get('expiresAt') for x in sessions)


def test_revoked_file_blocks_refresh_even_with_active_entitlement(mod,monkeypatch):
    files=FakeTable(key_attr='fileId',name='files')
    grants=FakeTable(key_attr='grantId',name='grants')
    files.seed({'fileId':'f','ownerPhone':'910000000000','ownerCustomerId':ALICE,
                'status':'revoked','s3Key':'secure/u/f.pdf'})
    eid='vault-entitlement#'+ALICE+'#f'
    grants.seed({'grantId':eid,'recordType':'VAULT_ENTITLEMENT','entitlementState':'ACTIVE',
                 'fileId':'f','ownerPhone':'910000000000','customerId':ALICE})
    monkeypatch.setattr(mod,'_table',lambda name:files if name==mod.FILES_TABLE else grants)
    response=mod._redeem('f',{'queryStringParameters':{'grant':eid}},
                         {'phone':'910000000000','subject':ALICE},'')
    assert response['statusCode']==403
    assert not [x for x in grants.rows.values() if x.get('recordType')=='VAULT_DOWNLOAD_SESSION']


def test_vault_grant_cannot_be_downloaded_by_recreated_different_identity(mod,monkeypatch):
    files=FakeTable(key_attr='fileId',name='files')
    grants=FakeTable(key_attr='grantId',name='grants')
    files.seed({'fileId':'f','ownerPhone':'910000000000','status':'active'})
    grants.seed({'grantId':'g','fileId':'f','ownerPhone':'910000000000','customerId':ALICE,
                 'source':'wix_vault','paid':True,'consumed':False})
    monkeypatch.setattr(mod,'_table',lambda name:files if name==mod.FILES_TABLE else grants)
    response=mod._redeem('f',{'queryStringParameters':{'grant':'g'}},{'phone':'910000000000','subject':BOB},'')
    assert response['statusCode']==403
    assert not grants.rows['g']['consumed']


def test_rejected_send_stops_after_three_attempts(vault_env,flow_module,monkeypatch):
    module=importlib.import_module('flows.paid_vault')
    requests,_,_,_,_=vault_env
    row={'requestId':'REQ#bounded'};requests.seed(row)
    clock=[1000];monkeypatch.setattr(module.time,'time',lambda:clock[0])
    client=Mock();client.invoke.side_effect=lambda **kwargs:{'Payload':io.BytesIO(b'{"statusCode":400}')}
    for _ in range(5):
        assert not module._send_once(requests,row,'vaultNotificationStatus',client,{})
        clock[0]+=31
    assert client.invoke.call_count==3
    assert requests.rows[row['requestId']]['vaultNotificationStatusAttempts']==3
