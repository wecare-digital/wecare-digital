"""Provider response contracts cannot disagree between checkout and diagnostics."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest

@pytest.fixture
def api():
    path=Path(__file__).resolve().parents[1]/'amplify/functions/messaging/whatsapp-business-api/handler.py'
    with patch('boto3.resource'),patch('boto3.client'):
        spec=importlib.util.spec_from_file_location('audit_payment_handler',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def config(status='Active'):
    return {'configuration_name':'WECAREDIGITAL','status':status,
            'provider_name':'Razorpay','provider_mid':'merchant-fixture'}

@pytest.mark.parametrize('nested',[True,False])
def test_current_provider_shape_has_consistent_active_diagnostic(api,monkeypatch,nested):
    calls=[]
    response={'data':[{'payment_configurations':[config()]}]} if nested else {'data':[config()]}
    def graph(path,**kwargs):calls.append(kwargs);return response
    monkeypatch.setattr(api,'_graph_api',graph)
    result=json.loads(api._check_payment_gateway(api.WABA1_ID)['body'])['gatewayChecks'][0]
    found=next(c for c in result['configurations'] if c['name']=='WECAREDIGITAL')
    assert found['status']=='Active' and found['gateway']=='Razorpay'
    assert found['mid']=='merchant-fixture' and found['canReceivePayments']
    assert result['activeConfigs']==1
    assert all('fields' not in c.get('params',{}) for c in calls)

def test_provider_read_failure_does_not_report_readiness(api,monkeypatch):
    monkeypatch.setattr(api,'_graph_api',lambda *a,**k:{'error':{'code':100}})
    result=json.loads(api._check_payment_gateway(api.WABA1_ID)['body'])['gatewayChecks'][0]
    assert result['activeConfigs']==0
    assert all(not c['canReceivePayments'] for c in result['configurations'])

def test_payment_configuration_read_follows_cursor_without_fields(api,monkeypatch):
    calls=[]
    def graph(path,**kwargs):
        calls.append(kwargs)
        if len(calls)==1:return {'data':[{'payment_configurations':[]}], 'paging':{'next':'https://fixture.invalid/next','cursors':{'after':'cursor-1'}}}
        assert kwargs['params']=={'after':'cursor-1'}
        return {'data':[{'payment_configurations':[config()]}]}
    monkeypatch.setattr(api,'_graph_api',graph)
    assert api._read_payment_configurations(api.WABA1_ID)['data']==[config()]
    assert len(calls)==2

def test_repeated_cursor_discards_partial_read(api,monkeypatch):
    monkeypatch.setattr(api,'_graph_api',lambda *a,**k:{'data':[config()],
        'paging':{'next':'https://fixture.invalid/next','cursors':{'after':'same'}}})
    result=api._read_payment_configurations(api.WABA1_ID)
    assert 'error' in result and 'data' not in result

@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_retired_raw_diagnostic_has_explicit_replacement_without_provider_call(api, monkeypatch, method):
    from unittest.mock import Mock
    graph = Mock()
    monkeypatch.setattr(api, '_graph_api', graph)
    result = api.handler({'path': '/wa-business/payment-config/raw', 'httpMethod': method,
        'queryStringParameters': {'phoneId': 'fixture-phone'}}, None)
    assert result['statusCode'] == 410
    body = json.loads(result['body'])
    assert body['replacement'] == '/wa-business/payment-config/list'
    assert body['diagnostic'] == '/wa-business/payment-config/check'
    graph.assert_not_called()
