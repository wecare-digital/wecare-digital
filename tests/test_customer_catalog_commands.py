import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]

def load(name):
 p=ROOT/'amplify/functions/messaging/whatsapp-business-api/flows'/f'{name}.py'
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.mark.parametrize('text,expected', [('Orders',('orders',1)),('Orders page 2',('orders',2)),('Customer ID',('customer_id',1)),('orders page 0',None),('orders +919876543210',None)])
def test_command_is_exact(text,expected):assert load('customer_commands').command(text)==expected

def test_owner_partition_and_pagination():
 m=load('customer_commands');calls=[]
 class Table:
  def query(self,**kwargs):
   calls.append(dict(kwargs));return {'Items':[{'orderNumber':'WD-100'}],**({'LastEvaluatedKey':{'orderId':'one'}} if len(calls)==1 else {})}
 assert m.order_page(Table(),'verified-owner',2)==(['WD-100'],False)
 assert all(x['ExpressionAttributeValues']=={':owner':'verified-owner'} for x in calls)
 assert calls[1]['ExclusiveStartKey']=={'orderId':'one'}

def test_customer_id_is_stored_uuid_never_internal_id():
 m=load('customer_commands');uuid='11111111-2222-4333-8444-555555555555'
 assert uuid in m.reply(None,{'customerUuid':uuid},SimpleNamespace(customer_id='internal'),('customer_id',1))
 assert 'internal' not in m.reply(None,{},SimpleNamespace(customer_id='internal'),('customer_id',1))

def test_internal_commands_reject_http_before_aws():
 assert load('customer_commands').handle({'path':'/api','text':'Orders'},None)['statusCode']==403
 assert load('catalog_lifecycle').handle({'path':'/api'},None)['statusCode']==403

def test_catalog_prepare_reuses_existing_and_never_deletes():
 m=load('catalog_lifecycle');calls=[]
 def graph(endpoint,**kwargs):calls.append((endpoint,kwargs));return {'data':[{'id':'fresh','name':m.FRESH_NAME}]}
 assert m.handle({'action':'prepare'},graph)['created'] is False
 assert all(c[1].get('method','GET')=='GET' for c in calls)

def test_inventory_does_not_silently_truncate():
 m=load('catalog_lifecycle');calls=[]
 def graph(endpoint,**kwargs):
  calls.append(kwargs);return {'data':[{'id':str(len(calls))}],**({'paging':{'next':'not-fetched','cursors':{'after':'cursor'}}} if len(calls)==1 else {})}
 assert len(m.collection(graph,'owned','id')['data'])==2
 assert calls[1]['params']['after']=='cursor'

def test_customer_arrivals_are_private_before_registration():
 source=(ROOT/'amplify/functions/messaging/inbound-whatsapp-handler/handler.py').read_text()
 assert "MEDIA_PREFIX = media_paths.secure('u/whatsapp/incoming/')" in source
 assert 'dest_key = media_paths.secure(f"u/service-requests/' in source
 assert "'url': f'https://{MEDIA_CDN_DOMAIN}/{dest_key}'" not in source

def test_staff_message_preview_signs_private_media_without_logging_bearer_url():
 source=(ROOT/'amplify/functions/core/messages-read/handler.py').read_text()
 assert "if media_paths.is_gated(actual_s3_key)" in source
 assert "ExpiresIn=300" in source
 assert "'cdnUrl': cdn_url" not in source
