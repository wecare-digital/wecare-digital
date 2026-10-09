import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

PATH = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-business-api/flows/service_design_drafts.py'
spec = importlib.util.spec_from_file_location('service_design_drafts', PATH)
drafts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drafts)

def test_http_rejected_before_any_provider_call():
    graph = Mock()
    for key in ('requestContext', 'rawPath', 'path', 'httpMethod'):
        assert drafts.handle({key: '', 'action': 'prepare', 'service': 'vault'}, graph, Mock(), Mock(), Mock())['statusCode'] == 403
    graph.assert_not_called()

def test_unknown_action_or_service_cannot_mutate():
    graph = Mock()
    for event in ({'action': 'publish'}, {'action': 'prepare', 'service': 'arbitrary'}):
        assert 'error' in drafts.handle(event, graph, Mock(), Mock(), Mock())
    graph.assert_not_called()

def test_published_design_never_overwritten():
    graph = Mock(return_value={'data': [{'id': 'published', 'name': drafts.NAMES['vault'], 'status': 'PUBLISHED'}]})
    create, upload = Mock(), Mock()
    assert 'error' in drafts.handle({'action': 'prepare', 'service': 'vault'}, graph, create, upload, Mock())
    create.assert_not_called()
    upload.assert_not_called()

def test_repeated_pagination_aborts_before_writes():
    graph = Mock(return_value={'data': [], 'paging': {'next': 'opaque', 'cursors': {'after': 'same'}}})
    create = Mock()
    assert 'error' in drafts.handle({'action': 'prepare', 'service': 'vault'}, graph, create, Mock(), Mock())
    create.assert_not_called()

def test_existing_draft_reused_not_created(tmp_path, monkeypatch):
    module_path = tmp_path / 'service_design_drafts.py'
    assets = tmp_path / 'design-drafts'
    assets.mkdir()
    (assets / 'vault.json').write_text(json.dumps({'version': '7.3', 'screens': []}))
    monkeypatch.setattr(drafts, '__file__', str(module_path))
    graph = Mock(return_value={'data': [{'id': 'existing', 'name': drafts.NAMES['vault'], 'status': 'DRAFT'}]})
    create = Mock()
    upload = Mock(return_value={'body': json.dumps({'success': True, 'hasErrors': False})})
    get = Mock(return_value={'body': json.dumps({'flow': {'id': 'existing', 'status': 'DRAFT'}})})
    answer = drafts.handle({'action': 'prepare', 'service': 'vault'}, graph, create, upload, get)
    assert answer['id'] == 'existing'
    assert answer['created'] is False
    create.assert_not_called()
    assert upload.call_args.args[0] == 'existing'

def test_missing_local_asset_does_not_create_empty_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, '__file__', str(tmp_path / 'module.py'))
    graph = Mock(return_value={'data': []})
    create = Mock()
    try:
        drafts.handle({'action': 'prepare', 'service': 'vault'}, graph, create, Mock(), Mock())
    except FileNotFoundError:
        pass
    else:
        raise AssertionError('missing fixed asset must fail closed')
    create.assert_not_called()


def test_orders_endpoint_uses_fixed_published_flow_not_client_url():
    graph=Mock(return_value={'data':[{'id':'draft','name':drafts.NAMES['orders'],'status':'DRAFT'}]})
    endpoint='https://wecare.digital/api/wa-business/flow-data'
    get=Mock(side_effect=[{'flow':{'id':'1107164111921876','status':'PUBLISHED','validation_errors':[],'endpoint_uri':endpoint}},
                         {'flow':{'status':'DRAFT','validation_errors':[],'endpoint_uri':endpoint}}])
    update=Mock(return_value={'success':True})
    result=drafts.handle({'action':'connect_orders_endpoint','service':'orders','endpoint_uri':'https://attacker.example'},graph,Mock(),Mock(),get,update)
    assert result['endpoint_connected'] is True
    update.assert_called_once_with('draft',{'endpoint_uri':endpoint})
    assert get.call_args_list[0].args==('1107164111921876',)


def test_orders_endpoint_cannot_connect_another_service_or_an_unverified_source():
    graph=Mock();update=Mock()
    assert 'error' in drafts.handle({'action':'connect_orders_endpoint','service':'vault'},graph,Mock(),Mock(),Mock(),update)
    graph.assert_not_called()
    graph.return_value={'data':[{'id':'draft','name':drafts.NAMES['orders'],'status':'DRAFT'}]}
    get=Mock(return_value={'flow':{'id':'1107164111921876','status':'DRAFT','endpoint_uri':'https://wecare.digital/api'}})
    assert 'error' in drafts.handle({'action':'connect_orders_endpoint','service':'orders'},graph,Mock(),Mock(),get,update)
    update.assert_not_called()
