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
from lambda_utils.ecommerce import contact_address, payment_address
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
    row={'id':'wa918100640044','phone':'+918100640044','name':'QA','email':'qa@example.com','updatedAt':100,
         'companyName':'WECARE QA','designation':'Tester',
         'customerUuid':'5f701556-7818-494a-a9aa-cf57da6287c2',
         'checkoutCustomerId':'11111111-2222-3333-4444-555555555555',
         'consentLedger':[{'state':'OPTED_OUT'}],
         'optInWhatsApp':False,'allowlistWhatsApp':False,
         contact_address.ATTRIBUTE:contact_address.normalize_for_storage(ADDRESS)}
    table=Table(row)
    monkeypatch.setattr(mod,'_context',lambda token:(table,'918100640044',copy.deepcopy(table.row)))
    calls=[]
    monkeypatch.setattr(mod.common,'record_completion',lambda **kw:calls.append(kw) or SimpleNamespace(error=''))
    monkeypatch.setattr(mod.subscribe_messages,'copy_for',lambda returning: dict(
        mod.subscribe_messages.DEFAULTS['returningCustomer' if returning else 'newCustomer']))
    monkeypatch.setattr(mod.identity_claims, 'claim_identities', lambda *args, **kwargs: ())
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
    old_uuid=table.row['customerUuid']; old_owner=table.row['checkoutCustomerId']
    old_consent=copy.deepcopy(table.row['consentLedger'])
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert result['data']['customer_id']=='C-ED6BQSW2P7PQ'
    assert table.row['customerUuid']==old_uuid
    assert table.row['checkoutCustomerId']==old_owner
    assert table.row['phone']=='+918100640044'
    assert table.row['consentLedger']==old_consent and table.row['optInWhatsApp'] is False
    assert table.row['allowlistWhatsApp'] is False
    assert table.row[contact_address.ATTRIBUTE]['addressLine1']=='45 New Road'
    assert table.row['addressLine1']=='45 New Road'
    assert form(mod)['address_line1']=='45 New Road'
    assert calls[0]['requires_payment'] is False
    assert calls[0]['flow_type']=='subscribe'
    assert calls[0]['form_data']['customer_id']=='C-ED6BQSW2P7PQ'
    assert calls[0]['form_data']['phone_number']=='+918100640044'
    assert 'profile_version' not in calls[0]['form_data']
    assert 'country_code' not in calls[0]['form_data']

def test_retry_does_not_repeat_profile_write(setup):
    mod,table,calls=setup; data=form(mod)
    mod.handle_review(data,TOKEN,'r'); mod.handle_review(data,TOKEN,'retry')
    assert len(table.updates)==1 and len(calls)==2

def test_newer_profile_edit_is_not_overwritten(setup):
    mod,table,_=setup; data=form(mod); table.row['updatedAt']=101
    assert mod.handle_review(data,TOKEN,'r')['screen']=='REVIEW'
    assert not table.updates

def test_optional_business_and_secondary_address_fields_allow_blank_values(setup):
    mod,table,_=setup
    data=form(mod)
    data.update(company_name='', designation='', address_line2='', locality='')
    result=mod.handle_review(data,TOKEN,'r-optional')
    assert result['screen']=='COMPLETE'
    assert table.row['companyName']==''
    assert table.row['designation']==''
    assert table.row[contact_address.ATTRIBUTE]['addressLine2']==''
    assert table.row[contact_address.ATTRIBUTE]['locality']==''


def test_partial_address_does_not_save_or_show_success(setup):
    mod,table,_=setup; data=form(mod); data['city']=''
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='REVIEW' and 'city' in result['data']['error_message']
    assert not table.updates

def test_new_contact_created_with_canonical_identity_and_no_marketing_optins(setup):
    mod,table,_=setup; table.row={}; data=form(mod); data.update(
        full_name='New QA',company_name='WECARE QA',designation='Tester',
        email_address='qa@example.com',**{key:ADDRESS[attr] for key,attr in mod.ADDRESS_FIELDS.items()})
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert table.row['id']=='wa918100640044'
    assert customer_uuid.from_contact(table.row)
    assert not table.row.get('optInWhatsApp') and not table.row.get('optInEmail')
    assert table.puts[0]['ConditionExpression']=='attribute_not_exists(id)'


def test_subscribe_india_address_is_the_same_address_for_web_and_whatsapp_pay(setup):
    mod,table,_=setup
    result=mod.handle_review(form(mod),TOKEN,'r')
    assert result['screen']=='COMPLETE'
    web,web_err=contact_address.payable_for(table.row,payment_address.WEBSITE_RAZORPAY)
    wa,wa_err=contact_address.payable_for(table.row,payment_address.WHATSAPP_ORDER_DETAILS)
    assert web_err is None and wa_err is None
    assert web==wa==table.row[contact_address.ATTRIBUTE]


def test_subscribe_international_address_stays_web_payable_but_not_whatsapp_native(setup):
    mod,table,_=setup
    data=form(mod)
    data.update(address_line1='1 Market St',city='San Francisco',state='US-CA',
                postal_code='94105',country='United States',country_code='IN')
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    stored=table.row[contact_address.ATTRIBUTE]
    assert stored['countryCode']=='US'
    web,web_err=contact_address.payable_for(table.row,payment_address.WEBSITE_RAZORPAY)
    _wa,wa_err=contact_address.payable_for(table.row,payment_address.WHATSAPP_ORDER_DETAILS)
    assert web_err is None and web==stored
    assert wa_err is not None and wa_err.code=='COUNTRY_NOT_PAYABLE_ON_CHANNEL'

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




def test_customer_copy_hides_country_code_and_has_short_labels():
    doc=json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/subscribe.json').read_text())
    def walk(node):
        if isinstance(node,dict):
            yield node
            for value in node.values():yield from walk(value)
        elif isinstance(node,list):
            for value in node:yield from walk(value)
    inputs=[n for n in walk(doc) if n.get('type')=='TextInput']
    assert not any(n.get('name')=='country_code' for n in inputs)
    assert all(len(n['label'])<=20 for n in inputs)
    dropdowns=[n for n in walk(doc) if n.get('type')=='Dropdown']
    required={n['name'] for n in inputs + dropdowns if n.get('required')}
    assert {'full_name','address_line1','city','state','postal_code','country'}<=required
    assert not {'company_name','designation','address_line2','locality'} & required
    country=next(n for n in dropdowns if n.get('name')=='country')
    assert country['data-source']
    assert country['data-source'][0]['id']=='India'
    assert len(country['data-source']) <= 200
    assert all(len(option['title']) <= 30 for option in country['data-source'])
    assert any(option['id']=='India' for option in country['data-source'])
    assert any(option['id']=='United States' for option in country['data-source'])
    copy_text=' '.join(n.get('text','') for n in walk(doc) if isinstance(n.get('text',''),str))
    assert 'Your website and WhatsApp' not in copy_text
    assert 'marketing subscriptions' not in copy_text




def test_country_dropdown_matches_backend_country_mapping(setup):
    mod,_table,_=setup
    doc=json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/subscribe.json').read_text())
    address=next(screen for screen in doc['screens'] if screen['id']=='ADDRESS')
    form=next(child for child in address['layout']['children'] if child.get('type')=='Form')
    country=next(child for child in form['children'] if child.get('name')=='country')
    assert country['data-source']==mod.country_options.OPTIONS


def test_new_customer_defaults_country_to_india_but_can_change_it(setup):
    mod,table,_=setup
    table.row={}
    data=form(mod)
    assert data['country']=='India' and data['country_code']=='IN'
    data.update(full_name='New QA', company_name='WECARE QA', designation='Tester',
                address_line1='1 Main Street', address_line2='Suite 2',
                locality='Westminster', city='London',
                state='England', postal_code='SW1A 1AA',
                country='United Kingdom', country_code='IN')
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert table.row[contact_address.ATTRIBUTE]['country']=='United Kingdom'
    assert table.row[contact_address.ATTRIBUTE]['countryCode']=='GB'


def test_existing_customer_saved_country_wins_over_india_default(setup):
    mod,table,_=setup
    table.row[contact_address.ATTRIBUTE]=contact_address.normalize_for_storage({
        'addressLine1':'10 Downing Street','city':'London','state':'England',
        'postalCode':'SW1A 2AA','country':'United Kingdom','countryCode':'GB'})
    data=form(mod)
    assert data['country']=='United Kingdom'
    assert data['country_code']=='GB'


def test_existing_international_customer_prefills_country_from_iso_code(setup):
    mod,table,_=setup
    table.row[contact_address.ATTRIBUTE]=contact_address.normalize_for_storage({
        'addressLine1':'1 Market St','city':'San Francisco','state':'US-CA',
        'postalCode':'94105','country':'India','countryCode':'US'})
    data=form(mod)
    assert data['country']=='United States'
    assert data['country_code']=='US'


def test_explicit_country_choice_derives_iso_code_and_updates_canonical_address(setup):
    mod,table,_=setup
    data=form(mod)
    data.update(country='United Kingdom', country_code='IN',
                state='GB-ENG', postal_code='SW1A 1AA')
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    saved=table.row[contact_address.ATTRIBUTE]
    assert saved['country']=='United Kingdom'
    assert saved['countryCode']=='GB'

def test_subscribe_does_not_collect_or_change_email(setup):
    mod,table,calls=setup; data=form(mod)
    assert 'email_address' not in data
    data['email_address']='attacker@example.com'
    assert mod.handle_review(data,TOKEN,'r')['screen']=='COMPLETE'
    assert table.row['email']=='qa@example.com'
    assert 'email_address' not in calls[0]['form_data']
    doc=json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/subscribe.json').read_text())
    assert 'email_address' not in json.dumps(doc)


def test_profile_username_preserves_meta_identity_and_customer_id(setup):
    mod,table,calls=setup
    table.row.update(username='meta_handle',bsuid='business-user-id',profileUsername='Previous')
    data=form(mod)
    assert data['username']=='Previous'
    data['username']='New customer name'
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='COMPLETE'
    assert table.row['profileUsername']=='New customer name'
    assert table.row['username']=='meta_handle' and table.row['bsuid']=='business-user-id'
    assert result['data']['customer_id']=='C-ED6BQSW2P7PQ'
    assert calls[0]['form_data']['username']=='New customer name'



def test_validation_error_echoes_canonical_country_pair(setup):
    mod,table,_=setup
    data=form(mod)
    data.update(country='United Kingdom',country_code='IN',username='x'*51)
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='REVIEW'
    assert result['data']['country']=='United Kingdom'
    assert result['data']['country_code']=='GB'
    assert not table.updates


def test_username_limit_does_not_write_profile(setup):
    mod,table,_=setup; data=form(mod); data['username']='x'*51
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='REVIEW' and 'username' in result['data']['error_message']
    assert not table.updates


def test_returning_confirmation_stays_the_same_on_retry(setup):
    mod,table,_=setup; data=form(mod)
    first=mod.handle_review(data,TOKEN,'r')
    retry=mod.handle_review(data,TOKEN,'r')
    assert first['data']['message']==retry['data']['message']=='Your details have been updated.'


def test_new_customer_confirmation_stays_the_same_on_retry(setup):
    mod,table,_=setup; table.row={}; data=form(mod)
    data.update(full_name='New QA',company_name='WECARE QA',designation='Tester',
                **{key:ADDRESS[attr] for key,attr in mod.ADDRESS_FIELDS.items()})
    first=mod.handle_review(data,TOKEN,'r')
    retry=mod.handle_review(data,TOKEN,'r')
    assert first['data']['message']==retry['data']['message']=='Your details have been saved.'


def test_retry_refuses_an_incomplete_saved_scenario(setup):
    mod,table,calls=setup; data=form(mod)
    table.row['subscribeLastFlowToken']=TOKEN
    table.row.pop('subscribeProfileWasExisting',None)
    result=mod.handle_review(data,TOKEN,'r')
    assert result['screen']=='REVIEW'
    assert 'incomplete' in result['data']['error_message'].lower()
    assert not table.updates
    assert not calls


def test_saved_profile_uses_workspace_confirmation(setup,monkeypatch):
    mod,table,_=setup
    monkeypatch.setattr(mod.subscribe_messages,'copy_for',lambda returning:{'confirmation':'Your profile update is saved.'})
    result=mod.handle_review(form(mod),TOKEN,'r')
    assert result['data']['message']=='Your profile update is saved.'
    assert result['data']['customer_id']=='C-ED6BQSW2P7PQ'


def test_f001_uses_us_english_customer_copy():
    doc=json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/subscribe.json').read_text())
    def walk(node):
        if isinstance(node,dict):
            yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node,list):
            for value in node:
                yield from walk(value)
    nodes=list(walk(doc))
    fields={n.get('name'):n for n in nodes if n.get('type') in ('TextInput','Dropdown') and n.get('name')}
    assert fields['username']['label']=='WhatsApp username'
    assert fields['company_name']['label']=='Organization'
    assert fields['designation']['label']=='Job title'
    assert fields['address_line2']['label']=='Apartment / suite / unit'
    assert fields['locality']['label']=='Landmark / neighborhood'
    assert fields['postal_code']['label']=='Postal code'
    assert fields['username']['helper-text']=='Optional — for your WECARE.DIGITAL profile'
    assert fields['company_name']['helper-text']=='Optional'
    assert fields['designation']['helper-text']=='Optional'
    assert fields['address_line2']['helper-text']=='Optional'
    assert fields['locality']['helper-text']=='Optional'
    assert fields['full_name']['max-chars']==200
    assert fields['username']['max-chars']==50
    assert fields['company_name']['max-chars']==200
    assert fields['designation']['max-chars']==200
    assert fields['address_line1']['max-chars']==200
    assert fields['address_line2']['max-chars']==200
    assert fields['locality']['max-chars']==100
    assert fields['city']['max-chars']==100
    assert fields['state']['max-chars']==100
    assert fields['postal_code']['max-chars']==100
    all_copy=json.dumps(doc,ensure_ascii=False)
    for forbidden in ('Organisation','colour','PIN / postal code','Profile username','WECARE services'):
        assert forbidden not in all_copy
    assert 'WECARE.DIGITAL services' in all_copy


def test_subscribe_default_copy_uses_us_english_and_whatsapp_username(setup):
    mod,_table,_calls=setup
    new=mod.subscribe_messages.DEFAULTS['newCustomer']
    returning=mod.subscribe_messages.DEFAULTS['returningCustomer']
    assert 'WECARE.DIGITAL' in new['body'] and 'WECARE.DIGITAL' in returning['body']
    assert 'WhatsApp username' in new['body'] and 'WhatsApp username' in returning['body']


def test_f001_does_not_switch_copy_by_user_locale():
    source=(ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/subscribe_profile.py').read_text()
    assert 'user_locale' not in source
