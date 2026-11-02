"""Offline per-item capture/draft contracts. No AWS clients, messages or payments."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import re
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
# Isolate the pure helpers from lambda_utils.__init__, which imports the runtime SDK.
# No AWS client or credential chain is loaded by this offline contract check.
sys.path.insert(0,str(ROOT/'amplify/functions/shared'))
for name,path in [('lambda_utils',ROOT/'amplify/functions/shared/lambda_utils'),('lambda_utils.ecommerce',ROOT/'amplify/functions/shared/lambda_utils/ecommerce')]:
    package=types.ModuleType(name);package.__path__=[str(path)];sys.modules[name]=package
spec=importlib.util.spec_from_file_location('item_processes',ROOT/'amplify/functions/shared/lambda_utils/ecommerce/item_processes.py')
processes=importlib.util.module_from_spec(spec);spec.loader.exec_module(processes)

class Table:
    def __init__(self,row):self.row=row;self.writes=[]
    def get_item(self,**kwargs):return {'Item':dict(self.row)}
    def update_item(self,**kwargs):
        self.writes.append(kwargs);v=kwargs['ExpressionAttributeValues']
        self.row['itemProcessCapturedPaymentId']=v[':payment']

class ProcessContracts(unittest.TestCase):
    def draft(self,n=1):
        item=f'fixed-{n:02d}'
        return dict(schemaVersion=1,itemId=item,processId='payment-item-'+item,
                    trigger='payment.captured',enabled=False,processDescription='',templateName='',templateId='',flowId='',startScreen='')
    def test_all29_have_distinct_backend_keys_and_processes(self):
        self.assertEqual(len(processes.CONFIG_KEYS),29)
        for n in range(1,30):
            d=self.draft(n);self.assertEqual(processes.validate_draft(f'payment_item_process_fixed_{n:02d}',d),'')
    def test_draft_cannot_activate_or_move_to_another_item_or_trigger(self):
        for mutation in [dict(enabled=True),dict(trigger='message.delivered'),dict(itemId='fixed-02'),dict(itemId={}),dict(flowId='invalid'),dict(extra='value')]:
            d=self.draft();d.update(mutation);self.assertTrue(processes.validate_draft('payment_item_process_fixed_01',d))
    def test_unpaid_or_wrong_payment_never_checkpoints(self):
        for row in [dict(invoiceId='i',fixedPresetId='fixed-01',paymentStatus='pending',paymentId='p'),dict(invoiceId='i',fixedPresetId='fixed-01',paymentStatus='captured',paymentId='other')]:
            t=Table(row);self.assertEqual(processes.record_captured(t,'i','p'),'PAYMENT_NOT_VERIFIED');self.assertEqual(t.writes,[])
    def test_paid_process_is_idempotent_and_waits_for_real_flow_setup(self):
        t=Table(dict(invoiceId='i',fixedPresetId='fixed-01',paymentStatus='captured',paymentId='p'))
        self.assertEqual(processes.record_captured(t,'i','p'),'AWAITING_FLOW_SETUP')
        self.assertEqual(processes.record_captured(t,'i','p'),'ALREADY_RECORDED')
        self.assertEqual(len(t.writes),1)
        self.assertIn('paymentId = :payment',t.writes[0]['ConditionExpression'])
    def test_concurrent_checkpoint_conflict_rechecks_same_verified_payment(self):
        class ConditionalConflict(Exception):
            response={'Error':{'Code':'ConditionalCheckFailedException'}}
        class RacingTable(Table):
            def update_item(self,**kwargs):
                self.row['itemProcessCapturedPaymentId']='p'
                raise ConditionalConflict()
        row=dict(invoiceId='i',fixedPresetId='fixed-01',paymentStatus='captured',paymentId='p')
        self.assertEqual(processes.record_captured(RacingTable(row),'i','p'),'ALREADY_RECORDED')
        class ChangedTable(Table):
            def update_item(self,**kwargs):
                self.row['paymentStatus']='refunded'
                raise ConditionalConflict()
        self.assertEqual(processes.record_captured(ChangedTable({**row,'itemProcessCapturedPaymentId':''}),'i','p'),'PAYMENT_NOT_VERIFIED')
        class FailedTable(Table):
            def update_item(self,**kwargs):raise RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            processes.record_captured(FailedTable({**row,'itemProcessCapturedPaymentId':''}),'i','p')

    def test_service_attribution_requires_exact_paid_lineage_and_file_target(self):
        i=dict(invoiceId='i',paymentId='p',referenceId='ref',total='84.97',currency='INR')
        r=dict(referenceId='ref',paymentAttemptId='a')
        a=dict(paymentAttemptId='a',referenceId='ref',status='PAYMENT_PAID',verifiedProviderPaymentId='p',verifiedCapturedPaise=8497,serviceKind='VAULT',vaultFileId='f')
        self.assertEqual(processes.verified_item_id(i,r,a),'fixed-27')
        self.assertEqual(processes.verified_item_id(i,r,{**a,'vaultFileId':''}),'')
        self.assertEqual(processes.verified_item_id(i,r,{**a,'verifiedCapturedPaise':8496}),'')
        self.assertEqual(processes.verified_item_id(i,r,{**a,'status':'PAYMENT_PENDING'}),'')

class ContactRetentionContracts(unittest.TestCase):
    def send_until_quote(self,contact):
        source=(ROOT/'amplify/functions/ecommerce/checkout/handler.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_staff_contribution_send')
        class Conflict(Exception):pass
        identity=SimpleNamespace(customer_id='verified-owner')
        env=dict(Dict=dict,Any=object,json=json,re=re,time=SimpleNamespace(time=lambda:1),
          cors_response=lambda code,data,origin:{'statusCode':code,'body':data},
          _STAFF_CONTRIBUTION_CONTACT_ID=re.compile(r'[A-Za-z0-9_-]+'),
          CONTRIBUTION_CHOICES_PAISE={'sku':30000},CONTRIBUTION_PRODUCT_IDS={'product'},CONTRIBUTION_PRODUCT_ID='product',
          staff_contribution=SimpleNamespace(STAFF_CONTRIBUTION_TOTAL_PAISE=30000,valid_staff_contribution_snapshot=lambda *a,**k:False),
          CONTACTS_TABLE='contacts',_table=lambda name:Table(contact),
          contact_key=SimpleNamespace(assert_consistent=lambda r:None,resolve=lambda r:r['id'],ContactKeyMismatch=Conflict),
          contact_store=SimpleNamespace(is_live=lambda r:not r.get('deletedAt')),
          customer_auth=SimpleNamespace(is_cognito_subject=lambda x:x=='verified-owner',CustomerNotAuthorized=Conflict),
          customer_identity=SimpleNamespace(InvalidPhoneNumber=Conflict),
          wa_payment_request=SimpleNamespace(PHONE_NUMBER_ID_1='sender',PAYMENT_SENDERS={'sender'}),
          _native_whatsapp_identity=lambda *a:(identity,contact),_native_quote=lambda *a:object(),
          catalog_pricing=SimpleNamespace(CatalogPricingError=Conflict))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'staff_send_contract','exec'),env)
        return env['_staff_contribution_send']({'action':'staff-contribute-send','contactId':'saved-owner'},'',staff_actor_hash='a'*64)
    def test_retention_locked_verified_customer_reaches_price_guard(self):
        row=dict(id='saved-owner',name='Fictional',phone='+919000000001',checkoutCustomerId='verified-owner',locked=True,lockedReason='paid')
        answer=self.send_until_quote(row)
        self.assertEqual(answer['body']['error'],'CONTRIBUTION_PRICE_MISMATCH')
    def test_unverified_and_archived_still_refused(self):
        row=dict(id='saved-owner',name='Fictional',phone='+919000000001',checkoutCustomerId='verified-owner',locked=True)
        for extra in [dict(checkoutCustomerId='unverified'),dict(archivedAt=1),dict(deletedAt=1)]:
            self.assertEqual(self.send_until_quote({**row,**extra})['body']['error'],'CONTRIBUTION_CUSTOMER_UNVERIFIED')

class StaffOrderBindingContracts(unittest.TestCase):
    def service_start(self,order,contract_kind='flow'):
        source=(ROOT/'amplify/functions/ecommerce/checkout/handler.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_request_service_start')
        calls=[]
        contract=SimpleNamespace(service_code='SUBMIT_REQUEST',fulfillment_kind=contract_kind,product_id='product',sku='sku',flow_capability='submit_request')
        keys=SimpleNamespace(get_item=lambda **k:{'Item':{'orderIdRef':'internal-order'}})
        env=dict(Dict=dict,Any=object,customer_auth=SimpleNamespace(CustomerIdentity=object),
          cors_response=lambda code,data,origin:{'statusCode':code,'body':data},
          request_service_contracts=SimpleNamespace(request_service_contract=lambda code:contract),
          order_keys=SimpleNamespace(is_public_order_number=lambda n:n=='WD-ORD-7ZTSG8X7',ORDER_NUMBER_PREFIX='ORDERNO#'),
          _keys_table=lambda:keys,_table=lambda name:Table(order),ORDERS_TABLE='orders',
          payment_status=SimpleNamespace(canonical=lambda x:x,CAPTURED='captured'),
          _create=lambda *a,**kw:calls.append((a,kw)) or {'statusCode':200})
        exec(compile(ast.Module(body=[node],type_ignores=[]),'service_binding','exec'),env)
        response=env['_request_service_start'](SimpleNamespace(customer_id='owner'),{'serviceCode':'SUBMIT_REQUEST','selectedOrderNumber':'WD-ORD-7ZTSG8X7'},'',native_contact={'id':'contact'},expected_total_paise=16600,staff_actor_hash='a'*64,staff_item_process_id='fixed-24')
        return response,calls
    def test_paid_owned_order_carries_server_context_and_reviewed_total(self):
        result,calls=self.service_start(dict(orderId='internal-order',orderNumber='WD-ORD-7ZTSG8X7',customerId='owner',paymentStatus='captured'))
        self.assertEqual(result['statusCode'],200);self.assertEqual(len(calls),1)
        args,kw=calls[0];self.assertEqual(args[1]['expectedTotalPaise'],16600)
        self.assertEqual(kw['verified_service_context']['selectedOrderId'],'internal-order')
        self.assertEqual(kw['native_contact']['id'],'contact')
        self.assertEqual(kw['staff_item_process_id'],'fixed-24')
    def test_foreign_or_unpaid_order_cannot_reach_payment(self):
        for extra in [dict(customerId='foreign'),dict(paymentStatus='pending')]:
            result,calls=self.service_start({**dict(orderId='internal-order',orderNumber='WD-ORD-7ZTSG8X7',customerId='owner',paymentStatus='captured'),**extra})
            self.assertEqual(result['statusCode'],404);self.assertEqual(calls,[])
    def test_vault_stays_exact_file_bound(self):
        result,calls=self.service_start({},contract_kind='secure_download')
        self.assertEqual(result['statusCode'],409);self.assertEqual(calls,[])
    def test_all29_catalog_process_identities_are_unique(self):
        from lambda_utils.ecommerce.item_process_products import ITEM_BY_PRODUCT_ID
        self.assertEqual(set(ITEM_BY_PRODUCT_ID.values()),processes.ITEM_IDS)
    def test_shop_capture_uses_catalog_identity_not_display_name(self):
        from lambda_utils.ecommerce.item_process_products import ITEM_BY_PRODUCT_ID
        product_id=next(k for k,v in ITEM_BY_PRODUCT_ID.items() if v=='fixed-01')
        i=dict(invoiceId='i',paymentId='p',referenceId='r',total='1132.98')
        r=dict(referenceId='r',paymentAttemptId='a')
        a=dict(paymentAttemptId='a',referenceId='r',status='PAYMENT_PAID',verifiedProviderPaymentId='p',verifiedCapturedPaise=113298,purchasedSnapshot={'items':[{'productId':product_id,'name':'untrusted display'}]})
        self.assertEqual(processes.verified_item_id(i,r,a),'fixed-01')
        self.assertEqual(processes.verified_item_id(i,r,{**a,'purchasedSnapshot':{'items':[{'name':'Grahak OS'}]}}),'')

class StaffServiceSendContracts(unittest.TestCase):
    def run_send(self,*,amount=16600,extra=None):
        source=(ROOT/'amplify/functions/ecommerce/checkout/handler.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_staff_item_service_send')
        calls=[]
        class Conflict(Exception):pass
        contact=dict(id='owner',name='Fictional',phone='+919000000001',checkoutCustomerId='subject',locked=True)
        identity=SimpleNamespace(customer_id='subject')
        env=dict(Dict=dict,Any=object,re=re,json=json,time=SimpleNamespace(time=lambda:1),
          _STAFF_ITEM_ACTION='staff-item-service-send',_STAFF_ITEM_SERVICES={'fixed-24':'SUBMIT_REQUEST'},
          _STAFF_CONTRIBUTION_CONTACT_ID=re.compile(r'[A-Za-z0-9_-]+'),
          cors_response=lambda code,data,origin:{'statusCode':code,'body':json.dumps(data)},
          order_keys=SimpleNamespace(is_public_order_number=lambda n:n=='WD-ORD-7ZTSG8X7'),
          CONTACTS_TABLE='contacts',_table=lambda name:Table(contact),
          contact_key=SimpleNamespace(assert_consistent=lambda r:None,resolve=lambda r:r['id'],ContactKeyMismatch=Conflict),
          contact_store=SimpleNamespace(is_live=lambda r:True),
          customer_auth=SimpleNamespace(is_cognito_subject=lambda x:x=='subject',CustomerNotAuthorized=Conflict),
          customer_identity=SimpleNamespace(InvalidPhoneNumber=Conflict),
          wa_payment_request=SimpleNamespace(PHONE_NUMBER_ID_1='sender',PAYMENT_SENDERS={'sender'}),
          _native_whatsapp_identity=lambda *a:(identity,contact),
          request_service_contracts=SimpleNamespace(request_service_contract=lambda kind:SimpleNamespace(product_id='p',sku='s',service_code=kind)),
          _native_quote=lambda *a:SimpleNamespace(quote=SimpleNamespace(total_payable_paise=amount)),
          _wa_cart_live_key=lambda *a:'live-key',_claim_wa_cart=lambda *a:calls.append('claim') or 'token',
          _take_over_settled_wa_cart=lambda *a:None,_release_wa_cart=lambda *a:calls.append('release'),
          _record_wa_cart=lambda *a:calls.append('record'),
          _request_service_start=lambda *a,**kw:calls.append(('owned-order-check',a,kw)) or {'statusCode':404,'body':'{"error":"ORDER_NOT_AVAILABLE"}'})
        exec(compile(ast.Module(body=[node],type_ignores=[]),'staff_item_send','exec'),env)
        body=dict(action='staff-item-service-send',contactId='owner',itemId='fixed-24',selectedOrderNumber='WD-ORD-7ZTSG8X7',expectedTotalPaise=16600)
        body.update(extra or {})
        return env['_staff_item_service_send'](body,'',staff_actor_hash='a'*64),calls
    def test_price_change_refuses_before_claim_or_owned_order_write(self):
        result,calls=self.run_send(amount=16601)
        self.assertEqual(json.loads(result['body'])['error'],'QUOTE_CHANGED');self.assertEqual(calls,[])
    def test_client_cannot_supply_phone_template_or_amount(self):
        for extra in [dict(phone='+919000000099'),dict(template='other'),dict(amount=1),dict(itemId={})]:
            result,calls=self.run_send(extra=extra);self.assertEqual(result['statusCode'],400);self.assertEqual(calls,[])
    def test_locked_owner_uses_existing_order_proof_and_refusal_releases_slot(self):
        result,calls=self.run_send();self.assertEqual(result['statusCode'],404)
        check=next(call for call in calls if isinstance(call,tuple))
        self.assertEqual(check[2]['native_contact']['id'],'owner')
        self.assertEqual(check[2]['expected_total_paise'],16600)
        self.assertEqual(check[2]['staff_item_process_id'],'fixed-24')
        self.assertIn('release',calls);self.assertNotIn('record',calls)

if __name__=='__main__':unittest.main(verbosity=2)
