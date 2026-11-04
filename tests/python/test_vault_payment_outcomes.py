"""Exercise the real native outcome boundary without invoking AWS or Meta."""
import ast
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py'


def functions():
    nodes = [node for node in ast.parse(SOURCE.read_text()).body
             if isinstance(node, ast.FunctionDef)
             and node.name in {'_payment_outcome', '_payment_diagnostic'}]
    namespace = {'json': json, 're': __import__('re')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


@pytest.mark.parametrize('result', [
    {'statusCode': 500, 'body': '{}'},
    {'statusCode': 503, 'body': '{"error":"DELIVERY_OUTCOME_UNKNOWN"}'},
    {'statusCode': 409, 'body': '{"error":"MESSAGE_SEND_IN_FLIGHT"}'},
    {'statusCode': 502, 'body': '{}'},
    {'statusCode': 200, 'body': '{}'},
    {'statusCode': 200, 'body': 'invalid JSON'},
    {'statusCode': 'broken', 'body': '{}'},
    {}, None,
])
def test_unknown_or_inflight_send_never_becomes_a_definitive_refusal(result):
    assert functions()['_payment_outcome'](result) == 'PAYMENT_REQUEST_UNCONFIRMED'


@pytest.mark.parametrize('result,expected', [
    ({'statusCode': 200, 'body': '{"status":"PAYMENT_REQUEST_SENT"}'}, 'PAYMENT_REQUEST_SENT'),
    ({'statusCode': 409, 'body': '{"error":"QUOTE_CHANGED"}'}, 'VAULT_QUOTE_CHANGED'),
    ({'statusCode': 409, 'body': '{"error":"DELIVERY_CONFIRMATION_REQUIRED"}'}, 'VAULT_DELIVERY_CONFIRMATION_REQUIRED'),
    ({'statusCode': 502, 'body': '{"sendUnconfirmed":false}'}, 'PAYMENT_REQUEST_NOT_SENT'),
    ({'statusCode': 502, 'body': '{"sendUnconfirmed":true}'}, 'PAYMENT_REQUEST_UNCONFIRMED'),
])
def test_explicit_success_and_pre_send_refusals_keep_their_meaning(result, expected):
    assert functions()['_payment_outcome'](result) == expected


def test_diagnostic_exposes_machine_code_and_status_without_free_text():
    diagnostic = functions()['_payment_diagnostic']
    assert diagnostic({'statusCode': 409, 'body': json.dumps({
        'error': 'DELIVERY_CONFIRMATION_REQUIRED', 'message': 'Private customer address'})}) == {
        'reason': 'DELIVERY_CONFIRMATION_REQUIRED', 'upstreamStatus': 409}
    assert diagnostic({'reason': 'Customer +919000000001 at Private Street',
                       'message': 'Private customer data'}) == {}


def test_native_prepare_preserves_refusal_reason_across_the_lambda_boundary():
    from types import SimpleNamespace
    nodes = [node for node in ast.parse(SOURCE.read_text()).body
             if isinstance(node, ast.FunctionDef)
             and node.name in {'_prepare_payment', '_payment_outcome', '_payment_diagnostic'}]
    namespace = {
        'json': json, 're': __import__('re'), 'time': SimpleNamespace(time=lambda: 100),
        'vault': SimpleNamespace(FILES_TABLE='files', bind_file=lambda *a: {'status': 'active'}),
        'store': SimpleNamespace(request_intent=lambda *a, **kw: {'intentId': 'intent'}),
        'REQUESTS_TABLE': 'requests', '_NOT_SENT': {'VAULT_DELIVERY_CONFIRMATION_REQUIRED'},
        '_close': lambda *a: None,
        '_invoke': lambda *a: {'statusCode': 409, 'body': json.dumps({
            'error': 'DELIVERY_CONFIRMATION_REQUIRED', 'message': 'Private address'})},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    result = namespace['_prepare_payment'](
        object(), SimpleNamespace(Table=lambda name: object()),
        SimpleNamespace(update_item=lambda **kw: None),
        {'orderId': 'session', 'token': 'opaque', 'vaultFileId': 'exact-file',
         'kind': 'VAULT', 'expiresAt': 1000},
        SimpleNamespace(customer_id='owner'), 'UNPAID', notify=False)
    assert result == {'outcome': 'VAULT_DELIVERY_CONFIRMATION_REQUIRED',
                      'fileId': 'exact-file', 'renewal': False,
                      'reason': 'DELIVERY_CONFIRMATION_REQUIRED', 'upstreamStatus': 409}
