"""Coexistence (`smb_app_state_sync`, `smb_message_echoes`) and `partner_solutions`.

This deployment is **not** a coexistence deployment and **not** a multi-partner
solution. The three fields are therefore NAMED, PARSED, AUDITED and NON-ACTING: the raw
envelope goes to ``SystemConfigTable`` through ``_store_system_event``, a named log line
carries the counts, and nothing else happens. The precedent is the ``messaging_handovers``
arm in the same handler -- *structured parse, NO decision taken from it*.

``smb_message_echoes`` carries copies of messages the owner sent from the WhatsApp
Business app on a coexistence number, so writing them to the inbox would duplicate the
owner's own messages into the CRM timeline on a deployment that has no coexistence
configured. That is the specific thing test 1 guards, and it guards it AT THE WRITE
BOUNDARY -- ``put_item`` call counts per table and whether ``put_message`` ran -- rather
than on intermediate state, which is the discipline
``tests/test_standby_produces_no_sends.py`` established.

``COEXISTENCE_INGEST_ENABLED`` is the seam a future adoption would open. It defaults
FALSE, false means audit-only, and its TRUE branch logs a warning and still writes
nothing (test 8). A flag whose enabled path silently does nothing is worse than no flag.

No AWS, no network: every table is an in-memory recorder and the Graph boundary and the
Lambda client are both counted.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest
from unittest.mock import MagicMock, patch

INBOUND_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler')
INBOUND_HANDLER_PATH = os.path.join(INBOUND_HANDLER_DIR, 'handler.py')
CALLING_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling')
CALLING_HANDLER_PATH = os.path.join(CALLING_HANDLER_DIR, 'handler.py')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, INBOUND_HANDLER_DIR)
sys.path.insert(0, os.path.join(INBOUND_HANDLER_DIR, 'modules'))

from lambda_utils import thread_ownership as to  # noqa: E402

RECIPIENT = '919876543210'
PHONE_NUMBER_ID = '1016149501586345'
REQ = 'req-coexistence-1'


# ---------------------------------------------------------------------------
# In-memory DynamoDB recorder
# ---------------------------------------------------------------------------

class _RecordingTable:
    """Records every write so the "no message row" claim is counted, not asserted."""

    def __init__(self, name):
        self.name = name
        self.items = {}
        self.put_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.query_calls = []

    def get_item(self, **kwargs):
        item = self.items.get((kwargs.get('Key') or {}).get('id'))
        return {'Item': item} if item else {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {'Items': []}

    def put_item(self, **kwargs):
        self.put_calls.append(kwargs)
        item = kwargs.get('Item') or {}
        self.items[item.get('id')] = dict(item)
        return {}

    def update_item(self, **kwargs):
        self.update_calls.append(kwargs)
        return {}

    def delete_item(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}


class _Dynamo:
    def __init__(self):
        self.tables = {}

    def Table(self, name):
        if name not in self.tables:
            self.tables[name] = _RecordingTable(name)
        return self.tables[name]

    def writes(self, name):
        table = self.tables.get(name)
        return list(table.put_calls) if table else []


class _Logs:
    """Captured ``logger.info`` / ``logger.warning`` records, JSON-decoded when possible."""

    def __init__(self):
        self.records = []
        self.raw = []

    def capture(self, msg, *a, **k):
        self.raw.append(str(msg))
        try:
            self.records.append(json.loads(msg))
        except (ValueError, TypeError):
            self.records.append({'raw': str(msg)})

    def named(self, event):
        return [r for r in self.records if r.get('event') == event]


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------

def _load_by_path(module_name: str, path: str, extra_paths=()):
    """Load a handler from its absolute path, deterministically.

    A bare ``import handler`` is fragile: several suites insert their own handler
    directory at the front of ``sys.path`` and import the bare name, so collection order
    could resolve ``handler`` to a different module. Same eviction-and-load-by-path
    pattern as ``tests/test_inbound_whatsapp_revoke.py``.
    """
    for stale in [m for m in sys.modules if m == module_name or m.startswith(module_name + '.')]:
        del sys.modules[stale]
    for extra in extra_paths:
        sys.path.insert(0, extra)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def h():
    """The real inbound handler module, imported with boto3 patched out."""
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return _load_by_path('handler', INBOUND_HANDLER_PATH,
                                 (os.path.join(INBOUND_HANDLER_DIR, 'modules'), INBOUND_HANDLER_DIR))


@pytest.fixture()
def calling():
    """The real whatsapp-calling ingress, loaded under its own module name."""
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return _load_by_path('wa_calling_handler', CALLING_HANDLER_PATH, (CALLING_HANDLER_DIR,))


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _make_sns_event(webhook_entry: dict) -> dict:
    """Build a minimal SNS event wrapping a WhatsApp webhook entry.

    Same shape as ``tests/test_inbound_whatsapp.py``'s helper.
    """
    return {
        'Records': [{
            'Sns': {
                'Message': json.dumps({
                    'context': {
                        'MetaWabaIds': ['2094615664435155'],
                        'MetaPhoneNumberIds': [PHONE_NUMBER_ID],
                    },
                    'whatsAppWebhookEntry': json.dumps(webhook_entry),
                    'messageId': 'test-msg-id',
                })
            }
        }]
    }


def _echo(to=RECIPIENT, msg_type='text', wamid='wamid.ECHO1'):
    return {'to': to, 'id': wamid, 'timestamp': '1790000000', 'type': msg_type,
            'text': {'body': 'sent from the Business app'}}


def _echoes_entry(echoes=None, *, with_metadata=True, key='message_echoes'):
    value = {'messaging_product': 'whatsapp'}
    if with_metadata:
        value['metadata'] = {'display_phone_number': '919330994400',
                             'phone_number_id': PHONE_NUMBER_ID}
    value[key] = [_echo()] if echoes is None else echoes
    return {'changes': [{'field': 'smb_message_echoes', 'value': value}]}


def _app_state_entry(contacts=2, chats=3, *, with_metadata=True):
    value = {'messaging_product': 'whatsapp',
             'state': {'contacts': [{'wa_id': RECIPIENT}] * contacts,
                       'chats': [{'id': f'chat-{i}'} for i in range(chats)]}}
    if with_metadata:
        value['metadata'] = {'display_phone_number': '919330994400',
                             'phone_number_id': PHONE_NUMBER_ID}
    return {'changes': [{'field': 'smb_app_state_sync', 'value': value}]}


def _partner_solutions_entry():
    return {'changes': [{'field': 'partner_solutions',
                         'value': {'solution_id': 'sol-1', 'event': 'SOLUTION_ATTACHED',
                                   'partner_business_id': '2238810740192680'}}]}


class _Ctx:
    aws_request_id = REQ

    @staticmethod
    def get_remaining_time_in_millis():
        return 120000


def _drive(h, entry, *, env=None, logs=None):
    """Run the REAL handler over a webhook entry, counting every write and every send.

    Two boundaries outside the ``h`` fixture's ``boto3`` patch have to be closed here, or this
    module's "no AWS, no network" claim is false for any ``messages`` change:

    * ``claim_event`` is patched for the same reason ``tests/test_inbound_whatsapp.py`` and
      ``tests/test_standby_produces_no_sends.py`` patch it -- the handler imports it lazily
      from ``lambda_utils.webhook_dedup``, which builds its DynamoDB resource at module scope.
      Left unpatched it reaches the LIVE ``WebhookDedup`` table and claims the wamid
      permanently, so the test passes ONCE and then fails for the 7-day TTL.
    * ``thread_ownership`` resolves its table lazily through ``_get_table()``, so the ``h``
      fixture's patch has already exited by the time a message is processed. It is injected
      through the module's own ``set_table`` seam -- the same seam
      ``tests/test_standby_produces_no_sends.py`` uses -- pointed at this run's recorder, so
      ownership writes are counted like every other table instead of reaching AWS and
      failing open with a warning.
    """
    logs = logs if logs is not None else _Logs()
    dynamo = _Dynamo()
    urlopen = MagicMock(side_effect=AssertionError('a coexistence webhook must not send'))
    lam = MagicMock()
    lam.invoke.side_effect = AssertionError('a coexistence webhook must not invoke')
    put_message = MagicMock()
    with patch.dict(os.environ, dict(env or {})), \
            patch.object(h, 'dynamodb', dynamo), \
            patch.object(h, 'lambda_client', lam), \
            patch.object(h, 'put_message', put_message), \
            patch('lambda_utils.webhook_dedup.claim_event', return_value=True), \
            patch('urllib.request.urlopen', urlopen), \
            patch.object(h.logger, 'info', side_effect=logs.capture), \
            patch.object(h.logger, 'warning', side_effect=logs.capture), \
            patch.object(h.logger, 'error', side_effect=logs.capture):
        to.set_table(dynamo.Table(to.table_name()))
        try:
            result = h.handler(_make_sns_event(entry), _Ctx())
        finally:
            to.set_table(None)
    return {'result': result, 'dynamo': dynamo, 'logs': logs,
            'urlopen': urlopen, 'lambda_client': lam, 'put_message': put_message}


def _message_table_writes(h, run):
    """Every write to any table that can reach the inbox or the contact record."""
    writes = []
    for table in (h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE, h.CONTACTS_TABLE):
        writes.extend(run['dynamo'].writes(table))
    return writes


# ---------------------------------------------------------------------------
# 1. The load-bearing test
# ---------------------------------------------------------------------------

def test_smb_message_echoes_writes_no_message_row(h):
    """An echo is counted, never stored as a message. Counted at the write boundary."""
    run = _drive(h, _echoes_entry([_echo(), _echo(wamid='wamid.ECHO2')]))

    assert run['dynamo'].writes(h.MESSAGES_TABLE) == []
    assert run['dynamo'].writes(h.UNIFIED_MESSAGES_TABLE) == []
    assert run['dynamo'].writes(h.CONTACTS_TABLE) == []
    assert run['put_message'].call_count == 0
    # The envelope IS audited -- that is the whole value of the arm.
    assert len(run['dynamo'].writes(h.SYSTEM_CONFIG_TABLE)) == 1


# ---------------------------------------------------------------------------
# 2. Nothing sends
# ---------------------------------------------------------------------------

def test_smb_message_echoes_sends_nothing(h):
    run = _drive(h, _echoes_entry())
    assert run['urlopen'].call_count == 0
    assert run['lambda_client'].invoke.call_count == 0


# ---------------------------------------------------------------------------
# 3. It is audited, and the count is in the log line
# ---------------------------------------------------------------------------

def test_smb_message_echoes_is_audited(h):
    logs = _Logs()
    store = MagicMock()
    with patch.object(h, '_store_system_event', store), \
            patch.object(h.logger, 'info', side_effect=logs.capture), \
            patch.object(h.logger, 'warning', side_effect=logs.capture):
        h._process_coexistence_event(
            'smb_message_echoes',
            {'metadata': {'phone_number_id': PHONE_NUMBER_ID},
             'message_echoes': [_echo(), _echo(msg_type='image', wamid='wamid.ECHO2')]},
            REQ)

    assert store.call_count == 1
    assert store.call_args[0][0] == 'smb_message_echoes'
    line = logs.named('smb_message_echoes_received')
    assert len(line) == 1
    assert line[0]['echoCount'] == 2
    assert line[0]['types'] == ['image', 'text']
    # `phone_number_id` is NOT a phone number, so it is logged in full.
    assert line[0]['phoneNumberId'] == PHONE_NUMBER_ID
    assert line[0]['ingested'] is False
    assert line[0]['requestId'] == REQ


# ---------------------------------------------------------------------------
# 4. App state sync counts contacts and chats
# ---------------------------------------------------------------------------

def test_smb_app_state_sync_counts_contacts_and_chats(h):
    run = _drive(h, _app_state_entry(contacts=2, chats=3))
    line = run['logs'].named('smb_app_state_sync_received')
    assert len(line) == 1
    assert line[0]['contactCount'] == 2
    assert line[0]['chatCount'] == 3
    assert line[0]['ingested'] is False
    assert _message_table_writes(h, run) == []


# ---------------------------------------------------------------------------
# 5. partner_solutions is informational only
# ---------------------------------------------------------------------------

def test_partner_solutions_is_stored_as_a_system_event(h):
    assert 'partner_solutions' not in h._COEXISTENCE_FIELDS  # no parser, by decision
    run = _drive(h, _partner_solutions_entry())

    stored = run['dynamo'].writes(h.SYSTEM_CONFIG_TABLE)
    assert len(stored) == 1
    assert stored[0]['Item']['id'] == 'whatsapp_events_partner_solutions'
    assert run['logs'].named('webhook_partner_solutions_stored')
    assert _message_table_writes(h, run) == []
    assert run['put_message'].call_count == 0


# ---------------------------------------------------------------------------
# 6. A malformed payload cannot raise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('entry', [
    _echoes_entry({'not': 'a list'}),                       # dict instead of list
    _echoes_entry(None, with_metadata=False),               # no metadata
    _echoes_entry([None, 'string', {'to': None}]),          # junk members
    {'changes': [{'field': 'smb_message_echoes', 'value': {}}]},
    {'changes': [{'field': 'smb_app_state_sync', 'value': {'state': 'not a dict'}}]},
    {'changes': [{'field': 'smb_app_state_sync', 'value': {}}]},
])
def test_a_malformed_echo_payload_does_not_raise(h, entry):
    run = _drive(h, entry)
    assert run['result']['statusCode'] == 200
    assert run['logs'].named('coexistence_event_error') == []
    assert _message_table_writes(h, run) == []


# ---------------------------------------------------------------------------
# 7. Recipients are masked
# ---------------------------------------------------------------------------

def test_recipients_are_masked(h):
    run = _drive(h, _echoes_entry([_echo(to=RECIPIENT), _echo(to='918100640044',
                                                              wamid='wamid.ECHO2')]))
    blob = '\n'.join(run['logs'].raw)
    assert RECIPIENT not in blob
    assert '918100640044' not in blob
    line = run['logs'].named('smb_message_echoes_received')[0]
    assert line['recipients'] == [h.mask_phone(RECIPIENT), h.mask_phone('918100640044')]
    assert all(r and r != RECIPIENT for r in line['recipients'])


def test_echoes_carried_under_the_messages_key_are_still_not_ingested(h):
    """Supporting guarantee, and the one case that was MEASURED to break the rule.

    ``_process_coexistence_event`` reads ``messages`` as a fallback, so the payload shape
    is anticipated -- and the handler's generic message loop runs BEFORE the coexistence
    arm. Driven with that shape before the guard existed, the handler wrote a row to
    WhatsAppInboundTable, auto-created a contact, called ``put_message`` and attempted a
    welcome send: it ingested the owner's own outbound copies as inbound CUSTOMER
    messages and replied to them. The guard is a computed empty message list, not a
    ``continue``, so the audit arm below it stays reachable.
    """
    run = _drive(h, _echoes_entry(key='messages'))

    assert _message_table_writes(h, run) == []
    assert run['put_message'].call_count == 0
    assert run['urlopen'].call_count == 0
    assert run['lambda_client'].invoke.call_count == 0
    # Still audited and still counted -- the guard suppresses ingest, not the record.
    assert len(run['dynamo'].writes(h.SYSTEM_CONFIG_TABLE)) == 1
    assert run['logs'].named('smb_message_echoes_received')[0]['echoCount'] == 1


def test_a_coexistence_statuses_payload_is_not_processed(h):
    """Supporting guarantee: `_process_status` writes to both message tables."""
    entry = {'changes': [{'field': 'smb_message_echoes', 'value': {
        'metadata': {'phone_number_id': PHONE_NUMBER_ID},
        'message_echoes': [_echo()],
        'statuses': [{'id': 'wamid.ECHO1', 'status': 'delivered',
                      'timestamp': '1790000000', 'recipient_id': RECIPIENT}],
    }}]}
    run = _drive(h, entry)
    assert _message_table_writes(h, run) == []
    assert run['logs'].named('smb_message_echoes_received')


def test_a_normal_messages_change_is_unaffected_by_the_guard(h):
    """The guard must be inert for every other field -- it is computed per change."""
    entry = {'changes': [{'field': 'messages', 'value': {
        'messaging_product': 'whatsapp',
        'metadata': {'display_phone_number': '919330994400',
                     'phone_number_id': PHONE_NUMBER_ID},
        'contacts': [{'profile': {'name': 'Test User'}, 'wa_id': RECIPIENT}],
        'messages': [{'from': RECIPIENT, 'id': 'wamid.NORMAL', 'timestamp': '1790000000',
                      'type': 'text', 'text': {'body': 'hello'}}],
    }}]}
    run = _drive(h, entry)
    assert run['put_message'].call_count == 1
    assert len(run['dynamo'].writes(h.MESSAGES_TABLE)) == 1


def test_the_recipient_list_is_capped_at_ten(h):
    """Supporting guarantee: a large echo batch cannot turn one log line into a dump."""
    echoes = [_echo(wamid=f'wamid.E{i}') for i in range(25)]
    run = _drive(h, _echoes_entry(echoes))
    line = run['logs'].named('smb_message_echoes_received')[0]
    assert line['echoCount'] == 25
    assert len(line['recipients']) == 10


# ---------------------------------------------------------------------------
# 8. The flag defaults false, and its true branch still writes nothing
# ---------------------------------------------------------------------------

def test_the_ingest_flag_defaults_false(h):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop('COEXISTENCE_INGEST_ENABLED', None)
        assert h._coexistence_ingest_enabled() is False
    for off in ('false', 'FALSE', '0', 'no', 'off', '', '  '):
        with patch.dict(os.environ, {'COEXISTENCE_INGEST_ENABLED': off}):
            assert h._coexistence_ingest_enabled() is False
    for on in ('true', 'TRUE', ' True ', '1', 'yes', 'on'):
        with patch.dict(os.environ, {'COEXISTENCE_INGEST_ENABLED': on}):
            assert h._coexistence_ingest_enabled() is True

    # Enabled: the warning fires and STILL nothing is written. This pins the
    # non-acting decision -- the flag is a seam, not an enablement.
    run = _drive(h, _echoes_entry(), env={'COEXISTENCE_INGEST_ENABLED': 'true'})
    warned = run['logs'].named('coexistence_ingest_requested_but_absent')
    assert len(warned) == 1
    assert warned[0]['field'] == 'smb_message_echoes'
    assert _message_table_writes(h, run) == []
    assert run['put_message'].call_count == 0
    assert run['urlopen'].call_count == 0
    assert run['lambda_client'].invoke.call_count == 0


def test_the_flag_is_read_per_call_and_not_at_module_scope(h):
    """Supporting guarantee: a module-scope read would be frozen for the sandbox's life.

    Asserted behaviourally -- the same process observes both answers without reimporting.
    """
    with patch.dict(os.environ, {'COEXISTENCE_INGEST_ENABLED': 'true'}):
        assert h._coexistence_ingest_enabled() is True
    with patch.dict(os.environ, {'COEXISTENCE_INGEST_ENABLED': 'false'}):
        assert h._coexistence_ingest_enabled() is False


# ---------------------------------------------------------------------------
# 9. The ingress forwards all three fields, and the catch-all still works
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('field', ['smb_app_state_sync', 'smb_message_echoes',
                                   'partner_solutions'])
def test_the_ingress_forwards_all_three_fields(calling, field):
    forward = MagicMock()
    body = {'object': 'whatsapp_business_account',
            'entry': [{'id': '2094615664435155',
                       'changes': [{'field': field, 'value': {'messaging_product': 'whatsapp'}}]}]}
    with patch.object(calling, '_forward_to_inbound_handler', forward):
        calling._handle_webhook_event(body, REQ)
    assert forward.call_count == 1


def test_the_ingress_catch_all_still_forwards_an_unknown_field(calling):
    """The regression guard the 2026-10-06 naming change left behind.

    Naming a field in the explicit tuple is byte-identical in behaviour BECAUSE the
    catch-all `else` forwards everything; if that ever stopped being true, naming a
    field would silently become the only way to receive it.
    """
    forward = MagicMock()
    body = {'object': 'whatsapp_business_account',
            'entry': [{'id': '2094615664435155',
                       'changes': [{'field': 'a_field_meta_has_not_shipped_yet',
                                    'value': {}}]}]}
    with patch.object(calling, '_forward_to_inbound_handler', forward):
        calling._handle_webhook_event(body, REQ)
    assert forward.call_count == 1
