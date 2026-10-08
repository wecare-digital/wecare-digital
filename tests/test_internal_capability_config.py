"""Settings expose real executor authority and never invent successful work."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from lambda_utils.agent import governance

PATH = Path(__file__).resolve().parents[1] / 'amplify/functions/ai/ai-config-management/handler.py'

def load_functions(table):
    tree = ast.parse(PATH.read_text())
    names = {'_get_internal_config', '_test_ai_response'}
    unit = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    scope = {'Dict': dict, 'Any': object, 'json': json, 'gov': governance, 'dynamodb': SimpleNamespace(Table=lambda _: table), 'SYSTEM_CONFIG_TABLE': 'fixture', 'DEFAULT_INTERNAL_AI_CONFIG': {'modelId': 'fixture'}, 'cors_headers': lambda _: {}, 'origin': '', 'logger': Mock(), '_error_response': lambda status, message: {'statusCode': status, 'body': json.dumps({'error': message})}}
    exec(compile(unit, str(PATH), 'exec'), scope)
    return scope

def test_missing_settings_is_read_only_and_exposes_governed_authority(monkeypatch):
    monkeypatch.delenv('AGENT_TOOLS_KILL_SWITCH', raising=False)
    table = Mock(); table.get_item.return_value = {}
    result = load_functions(table)['_get_internal_config']('test')
    body = json.loads(result['body'])
    assert result['statusCode'] == 200
    assert 'search_contacts' in body['toolCapabilities']['enabled']
    assert 'send_whatsapp' in body['toolCapabilities']['refused']
    table.put_item.assert_not_called()

def test_saved_send_preferences_cannot_override_kill_switch(monkeypatch):
    monkeypatch.setenv('AGENT_TOOLS_KILL_SWITCH', 'true')
    table = Mock(); table.get_item.return_value = {'Item': {'configValue': json.dumps({'enabledTools': ['send_whatsapp','search_contacts']})}}
    result = load_functions(table)['_get_internal_config']('test')
    body = json.loads(result['body'])
    assert body['toolCapabilities']['enabled'] == {}
    assert 'send_whatsapp' in body['toolCapabilities']['refused']
    assert 'search_contacts' in body['toolCapabilities']['refused']
    table.put_item.assert_not_called()

def test_failed_settings_read_does_not_return_success():
    table = Mock(); table.get_item.side_effect = RuntimeError('fixture')
    result = load_functions(table)['_get_internal_config']('test')
    assert result['statusCode'] == 503
    assert 'toolCapabilities' not in json.loads(result['body'])

def test_ai_test_never_returns_a_canned_generated_response():
    scope = load_functions(Mock())
    assert scope['_test_ai_response']({'message': 'hello'}, 'test')['statusCode'] == 501
    assert scope['_test_ai_response']({'message': ' '}, 'test')['statusCode'] == 400
