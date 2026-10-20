"""Subscribe profile round trips preserve identity, consent and the shared address."""
import copy
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from botocore.exceptions import ClientError
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer_uuid

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'subscribe-qa-waba-1-ph-918100640044'
ADDRESS = {'addressLine1':'12 Test Road','addressLine2':'Flat 2','locality':'Near park',
           'city':'Kolkata','state':'West Bengal','postalCode':'700001','country':'India','countryCode':'IN'}

class Table:
    def __init__(self, row): self.row=copy.deepcopy(row); self.updates=[]; self.puts=[]
    def get_item(self, **kw): return {'Item':copy.deepcopy(self.row)}
    def update_item(self, **kw):
        self.updates.append(kw)
        names=kw['ExpressionAttributeNames']; attrs=kw['ExpressionAttributeValues']
        for clause in kw['UpdateExpression'][4:].split(','):
            name,value=clause.strip().split('='); self.row[names[name]]=attrs[value]
    def put_item(self, **kw): self.puts.append(kw); self.row=copy.deepcopy(kw['Item'])

@pytest.fixture
def setup(monkeypatch):
    sys.path.insert(0,str(ROOT/'amplify/functions/messaging/whatsapp-business-api'))
    with patch('boto3.client'),patch('boto3.resource'):
        mod=importlib.import_module('flows.subscribe_profile')
    row={'id':'wa918100640044','phone':'+918100640044','name':'QA','updatedAt':100,
         'customerUuid':'5f701556-7818-494a-a9aa-cf57da6287c2','consentLedger':[{'state':'OPTED_OUT'}],
         'optInWhatsApp':False,'allowlistWhatsApp':False,
         contact_address.ATTRIBUTE:contact_address.normalize_for_storage(ADDRESS)}
    table=Table(row)
    monkeypatch.setattr(mod,'_context',lambda token:(table,'918100640044',copy.deepcopy(table.row)))
    calls=[]
    monkeypatch.setattr(mod.common,'record_completion',lambda **kw:calls.append(kw) or SimpleNamespace(error=''))
    return mod,table,calls

def form(mod):return mod.handle_init({},TOKEN,'r')['data']

def test_prefill_uses_canonical_address_and_compact_id(setup):
    mod,table,_=setup
    table.row['addressLine1']='STALE LEGACY VALUE'
    data=form(mod)
    assert data['address_line1']=='12 Test Road'
    assert data['address_line2']=='Flat 2'
    assert data['customer_id']=='C-ED6BQSW2P7PQ'
    assert not table.updates
    assert not any(k.startswith('opt_in') for k in data)

def test_save_and_reopen_updates_shared_address_without_consent_or_id_churn(setup):
    mod,table,calls=setup; data=form(mod)
    data.update(full_name='Updated QA',address_line1='45 New Road',customer_id='FORGED',phone_number='+19999999999')
    old_uuid=table.row['customerUuid']; old_consent=copy.deepcopy(table.row['consentLedger'])
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert result['data']['customer_id']=='C-ED6BQSW2P7PQ'
    assert table.row['customerUuid']==old_uuid
    assert table.row['phone']=='+918100640044'
    assert table.row['consentLedger']==old_consent and table.row['optInWhatsApp'] is False
    assert table.row['allowlistWhatsApp'] is False
    assert table.row[contact_address.ATTRIBUTE]['addressLine1']=='45 New Road'
    assert table.row['addressLine1']=='45 New Road'
    assert form(mod)['address_line1']=='45 New Road'
    assert calls[0]['requires_payment'] is False

def test_retry_does_not_repeat_profile_write(setup):
    mod,table,calls=setup; data=form(mod)
    mod.handle_review(data,TOKEN,'r'); mod.handle_review(data,TOKEN,'retry')
    assert len(table.updates)==1 and len(calls)==2

def test_newer_profile_edit_is_not_overwritten(setup):
    mod,table,_=setup; data=form(mod); table.row['updatedAt']=101
    assert mod.handle_review(data,TOKEN,'r')['screen']=='REVIEW'
    assert not table.updates

def test_partial_address_does_not_save_or_show_success(setup):
    mod,table,_=setup; data=form(mod); data['city']=''
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='REVIEW' and 'city' in result['data']['error_message']
    assert not table.updates

def test_new_contact_created_with_canonical_identity_and_no_marketing_optins(setup):
    mod,table,_=setup; table.row={}; data=form(mod); data['full_name']='New QA'
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert table.row['id']=='wa918100640044'
    assert customer_uuid.from_contact(table.row)
    assert not table.row.get('optInWhatsApp') and not table.row.get('optInEmail')
    assert table.puts[0]['ConditionExpression']=='attribute_not_exists(id)'

def test_deleted_address_not_prefilled_from_legacy_data(setup):
    mod,table,_=setup; table.row.pop(contact_address.ATTRIBUTE); table.row['shippingAddress']='DELETED'
    assert form(mod)['address_line1']==''

def test_missing_legacy_uuid_is_minted_only_at_save(setup):
    mod,table,_=setup; table.row.pop('customerUuid'); data=form(mod)
    assert data['customer_id']=='Assigned when you save'
    assert mod.handle_review(data,TOKEN,'r')['data']['customer_id'].startswith('C-')

def test_draft_has_no_preferences_and_valid_local_schema():
    sys.path.insert(0,str(ROOT/'scripts'))
    from validate_flow_json import validate_flow
    doc=json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/subscribe.json').read_text())
    assert not validate_flow(doc)
    assert [s['id'] for s in doc['screens']]==['PROFILE','ADDRESS','REVIEW','COMPLETE']
    assert 'opt_in_whatsapp' not in json.dumps(doc)
