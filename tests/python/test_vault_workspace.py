"""Execute Vault staff guards with local state and a fake provider; no AWS calls."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / 'amplify/functions/core/secure-files/handler.py'


def access_handler(state='OPEN', current=None):
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_admin_send_access')
    row = {'fileId': 'file-one', 'ownerPhone': '919000000001',
           'ownerCustomerId': 'owner', **(current or {})}
    updates = []
    def update(**kwargs):
        updates.append(kwargs)
        values = kwargs['ExpressionAttributeValues']
        if ':sending' in values:
            row.update(accessResendRequestId=values[':id'], accessResendState='SENDING')
        if ':state' in values:
            row['accessResendState'] = values[':state']
    env = {'Dict': dict, 'Any': object, 'json': json, 're': __import__('re'),
           'time': __import__('time'), 'ClientError': ClientError,
           'FILES_TABLE': 'files', '_table': lambda name: SimpleNamespace(update_item=update),
           '_owned_file_for_admin': lambda file: (row, None),
           '_file_access_state': lambda *args: state,
           '_vault_file_storage_ready': lambda item: True,
           'cors_response': lambda code, body, origin: {'statusCode': code, 'body': body},
           'logger': SimpleNamespace(info=lambda *args: None, warning=lambda *args: None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), env)
    return env['_admin_send_access'], row, updates


def test_unpaid_expired_unverified_file_cannot_resend():
    for state in ('UNPAID', 'EXPIRED', 'PAID_UNVERIFIED'):
        fn, _, updates = access_handler(state)
        with patch.dict(sys.modules, {'whatsapp_delivery': SimpleNamespace(
                send_vault_link=lambda **kw: (_ for _ in ()).throw(AssertionError('sent')))}):
            response = fn('file-one', {'body': '{}'}, '')
        assert response['statusCode'] == 409
        assert not updates


def test_staff_request_claim_precedes_send_and_retains_unknown_state():
    fn, row, updates = access_handler()
    request = '11111111-1111-4111-8111-111111111111'
    def sender(**kwargs):
        assert row['accessResendState'] == 'SENDING'
        assert kwargs['request_id'] == request
        return False, 'provider outcome unknown'
    with patch.dict(sys.modules, {'whatsapp_delivery': SimpleNamespace(send_vault_link=sender)}):
        result = fn('file-one', {'body': json.dumps({'requestId': request})}, '')
    assert result['statusCode'] == 502
    assert updates[0]['ConditionExpression'] == 'attribute_not_exists(accessResendRequestId)'
    assert row['accessResendState'] == 'UNCONFIRMED'


def test_different_request_cannot_bypass_unresolved_send():
    fn, _, updates = access_handler(current={
        'accessResendRequestId': 'old', 'accessResendState': 'UNCONFIRMED'})
    with patch.dict(sys.modules, {'whatsapp_delivery': SimpleNamespace(send_vault_link=lambda **kw: None)}):
        result = fn('file-one', {'body': json.dumps({
            'requestId': '11111111-1111-4111-8111-111111111111',
            'previousRequestId': 'old'})}, '')
    assert result['statusCode'] == 409
    assert not updates
