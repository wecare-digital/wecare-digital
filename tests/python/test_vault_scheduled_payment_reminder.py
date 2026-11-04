"""A due scheduled Vault PAYMENT is a staff reminder: STAFF_REVIEW_DUE, nothing sent, claim unused.

Runs the real `_dispatch_vault_scheduled_action` against in-memory tables. A send is impossible
here: the payment and access senders are replaced with functions that fail the test if called.
"""
import ast
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'amplify/functions/core/secure-files/handler.py'


class Table:
    def __init__(self, row):
        self.row, self.updates = row, []

    def get_item(self, Key, ConsistentRead=False):
        return {'Item': dict(self.row)}

    def update_item(self, **kw):
        self.updates.append(kw)


def dispatch(row, *, state='UNPAID'):
    node = next(n for n in ast.parse(SOURCE.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_dispatch_vault_scheduled_action')
    table = Table(row)

    def never(*a, **k):
        raise AssertionError('no send may happen for a scheduled payment')
    ns = {'json': json, 'time': time, 'datetime': datetime, 'timedelta': timedelta,
          'timezone': timezone, 'Dict': dict, 'Any': object, 'uuid': __import__('uuid'),
          '_table': lambda name: table, 'VAULT_SCHEDULE_TABLE': 't',
          'VAULT_SCHEDULE_KIND': 'VAULT_ACTION', 'VAULT_SCHEDULE_ACTIONS': {'payment', 'access'},
          '_owned_file_for_admin': lambda fid: ({'fileId': fid, 'ownerCustomerId': 'owner'}, None),
          '_file_access_state': lambda f, now: state, '_paid_marks': lambda f: False,
          '_admin_request_payment': never, '_admin_send_access': never,
          '_admin_send_vault_offer': never, '_vault_offer_catalog_price_valid': lambda: True,
          'catalog_service_checkout': SimpleNamespace(VAULT_ITEM_DESCRIPTION_DEFAULT='Vault'),
          'logger': SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
          'ClientError': Exception}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
    event = {'scheduleId': 'vault-' + 'a' * 32, 'dispatchToken': 't' * 24}
    return ns['_dispatch_vault_scheduled_action'](event), table


def row(action):
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    return {'id': 'vault-' + 'a' * 32, 'kind': 'VAULT_ACTION', 'status': 'DISPATCHING',
            'dispatchToken': 't' * 24, 'vaultAction': action, 'fileId': 'file-1',
            'ownerCustomerId': 'owner', 'scheduledAt': due}


def test_due_payment_schedule_is_a_reminder_and_sends_nothing():
    result, table = dispatch(row('payment'))
    assert result == {'result': 'FAILED', 'reason': 'STAFF_REVIEW_DUE'}
    # The one-use claim (vaultExecutedAt) was NOT consumed.
    assert not any('vaultExecutedAt' in str(u.get('UpdateExpression')) for u in table.updates)


def test_paid_file_payment_schedule_still_refuses_as_before():
    result, _ = dispatch(row('payment'), state='OPEN')
    assert result['reason'] == 'ALREADY_PAID_OR_UNAVAILABLE'
