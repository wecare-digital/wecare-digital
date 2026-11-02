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
            response = fn('file-one', {'body': json.dumps({'requestId': '11111111-1111-4111-8111-111111111111'})}, '')
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


def test_scheduled_access_supplies_stable_resend_identity():
    from datetime import datetime, timezone, timedelta
    import uuid
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_dispatch_vault_scheduled_action')
    schedule_id = 'vault-' + 'a' * 32
    row = {'kind': 'VAULT_ACTION', 'status': 'DISPATCHING',
           'dispatchToken': 't' * 32, 'vaultAction': 'access', 'fileId': 'file-one',
           'ownerCustomerId': 'owner', 'scheduledAt': datetime.now(timezone.utc).isoformat()}
    calls = []
    def resend(file, event, origin):
        calls.append(json.loads(event['body']))
        return {'statusCode': 200, 'body': json.dumps({'outcome': 'VAULT_LINK_SENT'})}
    env = {'Dict': dict, 'Any': object, 'json': json, 'datetime': datetime,
           'timezone': timezone, 'timedelta': timedelta, 'uuid': uuid,
           'time': __import__('time'), 'ClientError': ClientError,
           'VAULT_SCHEDULE_TABLE': 'schedule', 'VAULT_SCHEDULE_KIND': 'VAULT_ACTION',
           'VAULT_SCHEDULE_ACTIONS': ('access', 'payment', 'offer'),
           '_table': lambda name: SimpleNamespace(get_item=lambda **kw: {'Item': row},
                                                  update_item=lambda **kw: None),
           '_owned_file_for_admin': lambda file: ({'ownerCustomerId': 'owner',
                                                   'accessResendRequestId': 'previous'}, None),
           '_file_access_state': lambda *args: 'OPEN', '_admin_send_access': resend}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), env)
    event = {'scheduleId': schedule_id, 'dispatchToken': 't' * 32}
    assert env['_dispatch_vault_scheduled_action'](event)['result'] == 'SENT'
    assert env['_dispatch_vault_scheduled_action'](event)['result'] == 'SENT'
    assert calls[0] == calls[1]
    assert calls[0]['previousRequestId'] == 'previous'
    assert str(uuid.UUID(calls[0]['requestId'])) == calls[0]['requestId']


def test_accepted_link_stays_unresolved_if_ready_window_transition_fails():
    fn, row, _ = access_handler(state='READY')
    fn.__globals__.update({
        '_entitlement_for_file': lambda *args: {'ownerPhone': '919000000001'},
        'vault_window': SimpleNamespace(access_state=lambda *args: 'READY'),
        '_open_access_window': lambda *args: (_ for _ in ()).throw(ValueError('unavailable'))})
    with patch.dict(sys.modules, {'whatsapp_delivery': SimpleNamespace(
            send_vault_link=lambda **kw: (True, 'wamid.accepted'))}):
        result = fn('file-one', {'body': json.dumps({
            'requestId': '11111111-1111-4111-8111-111111111111'})}, '')
    assert result['statusCode'] == 202
    assert row['accessResendState'] == 'LINK_ACCEPTED'


def test_staff_pdf_preview_is_inline_but_customer_download_stays_attachment():
    from typing import Optional
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_download_url')
    calls = []
    def sign(operation, **kwargs):
        calls.append(kwargs)
        return 'https://private.example/signed'
    env = {'Dict': dict, 'Any': object, 'Optional': Optional,
           'BUCKET': 'private-bucket', 'DOWNLOAD_URL_TTL': 60,
           'DELIVERABLE_TYPES': {'application/pdf': 'pdf', 'image/png': 'image'},
           '_safe_download_filename': lambda item: 'wecare-digital-id.pdf',
           '_s3_client': lambda: SimpleNamespace(generate_presigned_url=sign)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), env)
    item = {'s3Key': 'private/id.pdf', 'contentType': 'application/pdf'}
    env['_download_url'](item)
    env['_download_url'](item, inline=True)
    env['_download_url'](dict(item, contentType='text/html'), inline=True)
    assert calls[0]['Params']['ResponseContentDisposition'].startswith('attachment;')
    assert calls[1]['Params']['ResponseContentDisposition'].startswith('inline;')
    assert calls[2]['Params']['ResponseContentDisposition'].startswith('attachment;')
    assert all(call['ExpiresIn'] == 60 for call in calls)
