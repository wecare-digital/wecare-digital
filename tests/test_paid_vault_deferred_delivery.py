"""A native Vault purchase that delivered nothing must not be reported ready.

With `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` absent - which it is everywhere - the ready
message is `wecare_share_pdf`, which has an IMAGE header and carries no URL button and no file
parameter. The file itself travels as a separate ordinary document message, gated on the file
being a PDF, on a `deliveryKey`, and on the 24-hour customer-service window. When that compound
condition is false the branch is skipped and the purchase used to report `VAULT_READY` having
delivered neither a link nor a file.

These pin the outcome, the reason enum's evaluation order, and the fact that the review nudge
still goes out: the customer did buy something, and suppressing it would hide the problem.
"""
from __future__ import annotations

import importlib
import io
import json
import logging
import pathlib
import sys
import time
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_service_request_store import ALICE
from test_paid_submit_request import flow_module  # noqa: F401  (fixture)
from test_paid_vault import vault_env  # noqa: F401  (fixture)
from coupon_fake_dynamo import FakeTable

STALE = 25 * 3600  # comfortably past the 24-hour window, in seconds


def _records(caplog):
    """Every structured record the flow emitted, parsed."""
    found = []
    for record in caplog.records:
        try:
            found.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    return found


def _run(vault_env, monkeypatch, *, deliverable='pdf', delivery_key='secure/d/report.pdf',
         window_open=True):
    """Drive `prepare_and_send` over the vault fixture, returning (outcome, sent messages).

    The flag stays absent in every case here - never opened to make a test pass.
    """
    module = importlib.import_module('flows.paid_vault')
    monkeypatch.delenv('VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED', raising=False)
    requests, keys, files, grants, event = vault_env

    row = files.rows['file-1']
    row['deliverable'] = deliverable
    if delivery_key is None:
        row.pop('deliveryKey', None)
    else:
        row['deliveryKey'] = delivery_key

    contacts = FakeTable(key_attr='id', name='contacts', indexes={'phone-index': ('phone', None)})
    last = int(time.time()) if window_open else int(time.time()) - STALE
    contacts.seed({'id': 'c', 'phone': '+910000000000', 'checkoutCustomerId': ALICE,
                   'lastInboundMessageAt': last})
    tables = {requests.name: requests, 'stack-wecare-digital-WixOrderIds': keys,
              files.name: files, grants.name: grants,
              'stack-wecare-digital-ContactsTable': contacts}
    db = Mock()
    db.Table.side_effect = lambda name: tables[name]
    cognito = Mock()
    cognito.list_users.return_value = {'Users': [{'Enabled': True, 'Attributes': [
        {'Name': 'phone_number', 'Value': '+910000000000'},
        {'Name': 'phone_number_verified', 'Value': 'true'}]}]}
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)

    sent = []

    def invoke(**kwargs):
        sent.append(json.loads(json.loads(kwargs['Payload'])['body']))
        return {'Payload': io.BytesIO(json.dumps({'statusCode': 200}).encode())}

    client = Mock()
    client.invoke.side_effect = invoke
    return module.prepare_and_send(event, client), sent


def test_a_paid_vault_purchase_outside_the_window_is_not_reported_ready(
        vault_env, flow_module, monkeypatch, caplog):
    """The file is perfectly deliverable; only the window closed. Say so."""
    module = importlib.import_module('flows.paid_vault')
    caplog.set_level(logging.INFO, logger=module.logger.name)
    result, sent = _run(vault_env, monkeypatch, window_open=False)

    assert result['outcome'] == 'VAULT_DELIVERY_DEFERRED'
    # exactly one template send - the share template - plus the review nudge, and no document
    assert [message['templateName'] for message in sent] == ['wecare_share_pdf',
                                                             'wecare_leave_review']
    assert not [message for message in sent if message.get('mediaType') == 'document']

    [record] = [found for found in _records(caplog)
                if found.get('event') == 'vault_delivery_deferred']
    assert record['reason'] == 'window_closed'
    assert set(record) == {'event', 'requestId', 'reason'}
    rendered = json.dumps(record)
    for identifier in ('report.pdf', 'secure/d/report.pdf', '910000000000', 'file-1'):
        assert identifier not in rendered


def test_a_purchase_inside_the_window_is_still_ready(vault_env, flow_module, monkeypatch, caplog):
    """The sensitivity proof: a delivery that happened still reports ready, and logs nothing."""
    module = importlib.import_module('flows.paid_vault')
    caplog.set_level(logging.INFO, logger=module.logger.name)
    result, sent = _run(vault_env, monkeypatch, window_open=True)

    assert result['outcome'] == 'VAULT_READY'
    assert [message for message in sent if message.get('mediaType') == 'document']
    assert not [found for found in _records(caplog)
                if found.get('event') == 'vault_delivery_deferred']


def test_a_non_pdf_reports_not_deliverable(vault_env, flow_module, monkeypatch, caplog):
    """First match wins: a file shape that can never be sent outranks a window that will reopen."""
    module = importlib.import_module('flows.paid_vault')
    caplog.set_level(logging.INFO, logger=module.logger.name)
    result, _ = _run(vault_env, monkeypatch, deliverable='docx', window_open=False)

    assert result['outcome'] == 'VAULT_DELIVERY_DEFERRED'
    [record] = [found for found in _records(caplog)
                if found.get('event') == 'vault_delivery_deferred']
    assert record['reason'] == 'not_deliverable'


def test_a_missing_delivery_key_reports_no_delivery_key(
        vault_env, flow_module, monkeypatch, caplog):
    """The second permanent data problem, also ahead of the timing one."""
    module = importlib.import_module('flows.paid_vault')
    caplog.set_level(logging.INFO, logger=module.logger.name)
    result, _ = _run(vault_env, monkeypatch, delivery_key=None, window_open=False)

    assert result['outcome'] == 'VAULT_DELIVERY_DEFERRED'
    [record] = [found for found in _records(caplog)
                if found.get('event') == 'vault_delivery_deferred']
    assert record['reason'] == 'no_delivery_key'
