"""Configured-app-only metadata binding; no provider calls or credential reads."""
import ast
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-business-api/handler.py'


def _update():
    node = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_update_flow')
    node.returns = None
    for arg in node.args.args:
        arg.annotation = None
    calls = []
    namespace = {'META_APP_ID': 'configured-app', '_resp': lambda status, body: {'statusCode': status, 'body': body},
        '_graph_api': lambda path, **kwargs: calls.append((path, kwargs)) or {'success': True}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['_update_flow'], calls


@pytest.mark.parametrize('app', ['foreign-app', 12345])
def test_unconfigured_app_is_refused_before_provider_call(app):
    update, calls = _update()
    assert update('approved-flow', {'application_id': app})['statusCode'] == 400
    assert not calls


def test_configured_app_is_attached_without_changing_flow_content():
    update, calls = _update()
    assert update('approved-flow', {'application_id': 'configured-app'})['statusCode'] == 200
    assert calls == [('approved-flow', {'method': 'POST', 'payload': {'application_id': 'configured-app'}})]


def test_existing_metadata_update_remains_compatible():
    update, calls = _update()
    assert update('draft', {'name': 'Draft'})['statusCode'] == 200
    assert calls[0][1]['payload'] == {'name': 'Draft'}
