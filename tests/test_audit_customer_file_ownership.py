"""A recycled verified phone cannot claim another permanent customer's files."""
from unittest.mock import Mock
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import pytest
from test_secure_files import mod
from test_service_request_store import who, ALICE, BOB
from coupon_fake_dynamo import FakeTable
from lambda_utils import customer_auth

@pytest.mark.parametrize('owner', [None, BOB, ''])
def test_vault_refuses_unlinked_or_other_permanent_owner(owner):
    from lambda_utils.ecommerce import vault_access
    files=FakeTable(key_attr='fileId', name='files')
    row={'fileId':'legacy', 'ownerPhone':'910000000000', 'status':'active'}
    if owner is not None: row['ownerCustomerId']=owner
    files.seed(row)
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        vault_access.bind_file(files, who(), 'legacy')
    assert files.rows['legacy']==row

@pytest.mark.parametrize('owner', [None, BOB, ''])
def test_direct_file_lookup_requires_permanent_owner(mod, monkeypatch, owner):
    row={'fileId':'f', 'ownerPhone':'910000000000', 'status':'active'}
    if owner is not None: row['ownerCustomerId']=owner
    table=Mock();table.get_item.return_value={'Item':row}
    monkeypatch.setattr(mod, '_table', lambda _:table)
    assert mod._owned_active_file('f', {'phone':'910000000000','subject':ALICE}) is None

def test_new_operator_upload_records_server_resolved_subject(mod, monkeypatch):
    monkeypatch.setattr(mod,'_ensure_customer_user',lambda *a:'+910000000000')
    client=Mock();client.admin_get_user.return_value={'Enabled':True,'UserAttributes':[
        {'Name':'sub','Value':ALICE},{'Name':'phone_number','Value':'+910000000000'}]}
    monkeypatch.setattr(mod,'_cognito_client',lambda:client)
    table=Mock();monkeypatch.setattr(mod,'_table',lambda _:table)
    s3=Mock();s3.generate_presigned_url.return_value='https://fixture.invalid/upload'
    monkeypatch.setattr(mod,'_s3_client',lambda:s3)
    response=mod._upload_init({'body':'{"name":"QA","mobile":"+910000000000","originalFilename":"report.pdf","sizeBytes":10}'},'https://wecare.digital')
    assert response['statusCode']==201
    assert table.put_item.call_args.kwargs['Item']['ownerCustomerId']==ALICE

def test_upload_without_permanent_subject_writes_nothing(mod, monkeypatch):
    monkeypatch.setattr(mod,'_ensure_customer_user',lambda *a:'+910000000000')
    client=Mock();client.admin_get_user.return_value={'UserAttributes':[]}
    monkeypatch.setattr(mod,'_cognito_client',lambda:client)
    table=Mock();monkeypatch.setattr(mod,'_table',lambda _:table)
    response=mod._upload_init({'body':'{"name":"QA","mobile":"+910000000000","originalFilename":"report.pdf","sizeBytes":10}'},'https://wecare.digital')
    assert response['statusCode']==503
    table.put_item.assert_not_called()

def test_list_hides_phone_only_legacy_file(mod,monkeypatch):
    table=Mock();table.query.return_value={'Items':[{'fileId':'legacy'}]}
    table.get_item.return_value={'Item':{'fileId':'legacy','status':'active','ownerPhone':'910000000000'}}
    monkeypatch.setattr(mod,'_table',lambda _:table)
    import json
    result=mod._customer_list({'phone':'910000000000','subject':ALICE},'https://wecare.digital')
    assert json.loads(result['body'])['files']==[]

@pytest.mark.parametrize('verified,subject',[(False,ALICE),(True,''),(True,ALICE)])
def test_authenticated_session_still_requires_verified_phone_and_subject(mod,monkeypatch,verified,subject):
    client=Mock();client.get_user.return_value={'Username':'qa','UserAttributes':[
        {'Name':'phone_number','Value':'+910000000000'},
        {'Name':'phone_number_verified','Value':'true' if verified else 'false'},
        {'Name':'sub','Value':subject}]}
    monkeypatch.setattr(mod,'_cognito_client',lambda:client)
    monkeypatch.setattr(mod,'_jwt_claims_unverified',lambda _:{'iss':mod.CUSTOMER_POOL_ISSUER})
    result=mod._customer_identity({'headers':{'Authorization':'Bearer fixture'}})
    assert bool(result)==bool(verified and subject)

def test_foreign_permanent_grant_cannot_redeem_owned_file(mod,monkeypatch):
    monkeypatch.setattr(mod,'_owned_active_file',lambda *a:{'fileId':'f','ownerCustomerId':ALICE})
    table=Mock();table.get_item.return_value={'Item':{'grantId':'g','customerId':BOB,'paid':True}}
    monkeypatch.setattr(mod,'_table',lambda _:table)
    result=mod._redeem('f',{'queryStringParameters':{'grant':'g'}},
                       {'phone':'910000000000','subject':ALICE},'https://wecare.digital')
    assert result['statusCode']==403
    table.update_item.assert_not_called()

@pytest.mark.parametrize('configured,expected',[('21600',900),('1',60),('300',300)])
def test_whatsapp_direct_link_lifetime_is_bounded(mod,monkeypatch,configured,expected):
    monkeypatch.setenv('WHATSAPP_LINK_TTL_SECONDS',configured)
    import importlib.util
    spec=importlib.util.spec_from_file_location('secure_files_ttl_fixture',mod.__file__)
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    assert loaded.WHATSAPP_LINK_TTL==expected
