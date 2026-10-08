"""A revoke marks the message it deleted -- and declines rather than guessing.

``inbound-whatsapp-handler`` used to store a ``revoke`` row and leave the message it
deleted untouched, so the inbox rendered the original message AND a standalone
"[Message deleted by sender]" bubble beside it. ``handler._apply_revoke`` closes that.

A revoke payload carries no reference to its target (the measured payload has no
``context`` key, and the revoke arrives with its own distinct ``wamid`` -- if it reused
the original's id, ``claim_event`` would reject it as a redelivery and no revoke row
would exist at all). Resolution is therefore two-tier:

* **exact** -- Meta supplied the revoked message's wamid; resolved through the
  ``whatsappMessageId-index`` on the **unified** ``MessagesTable``.
* **inferred** -- no usable id, so the single most recent inbound WhatsApp message from
  this contact inside ``REVOKE_CORRELATION_WINDOW_SECONDS``. Exactly one candidate, or
  nothing is marked.

Both tiers read the unified table on purpose, so they can only ever produce the same
primary key, and the mark plus the back-link are mirrored to both tables because the
inbox reads the unified one and only that.

These tests drive the real ``_apply_revoke`` against an in-memory DynamoDB fake that
ENFORCES the two ``ConditionExpression`` forms, so the idempotence and
"never create a row" claims are exercised rather than asserted. No AWS, no network.

THE FIXTURE NEEDS TWO PATCH TARGETS, NOT ONE. ``patch.object(h, 'dynamodb', ...)``
covers the exact tier's index query and every write, because those go through the
handler's own resource. It does NOT cover the candidate read: ``query_by_contact``
closes over ``message_store._dynamodb``, a separate ``boto3.resource`` created when
``lambda_utils.message_store`` is imported -- and the loader imports the handler under
``patch('boto3.resource')``, so that resource is a ``MagicMock``. Left alone,
``query_by_contact`` would iterate a ``MagicMock``, raise inside its own ``try``, log
``message_store_query_failed`` and return ``[]``, and every inferred-tier assertion
below would pass vacuously against an empty candidate list. So the candidate set is
seeded at the handler's bound name instead. ``test_the_candidate_read_goes_through_the_
contact_index_on_the_unified_table`` is the one deliberate exception.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

INBOUND_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler')
INBOUND_HANDLER_PATH = os.path.join(INBOUND_HANDLER_DIR, 'handler.py')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, INBOUND_HANDLER_DIR)
sys.path.insert(0, os.path.join(INBOUND_HANDLER_DIR, 'modules'))

CONTACT_ID = 'wa919876543210'
SENDER_PHONE = '919876543210'
REVOKE_ID = 'rev-row-1'
REVOKE_WAMID = 'wamid.REVOKE'
TARGET_ID = 'msg-target-1'
TARGET_WAMID = 'wamid.TARGET'
TARGET_CONTENT = 'the message that was deleted'
NOW = 1790000000
REQ = 'req-revoke-1'


# ---------------------------------------------------------------------------
# In-memory DynamoDB fake
# ---------------------------------------------------------------------------

class _FakeTable:
    """One table, keyed on ``id``, that enforces the conditions under test.

    Only the operations ``_apply_revoke`` performs are implemented; a ``scan`` is
    recorded and answers empty rather than raising, so the "no scan fallback" claim is
    asserted on the recording instead of being hidden by an exception the production
    code swallows.
    """

    def __init__(self, name, store):
        self.name = name
        self.items = store  # dict: id -> item, shared view for assertions
        self.queries = []
        self.scan_calls = []
        self.update_calls = []
        self.put_calls = []
        self.delete_calls = []

    # -- reads -----------------------------------------------------------
    def query(self, **kwargs):
        self.queries.append(kwargs)
        index = kwargs.get('IndexName', '')
        values = kwargs.get('ExpressionAttributeValues', {})
        limit = kwargs.get('Limit')
        if index == 'whatsappMessageId-index':
            matched = [i for i in self.items.values()
                       if i.get('whatsappMessageId') == values.get(':w')]
        elif index == 'contactId-index':
            matched = [i for i in self.items.values()
                       if i.get('contactId') == values.get(':c')]
        else:
            matched = []
        return {'Items': matched[:limit] if limit else matched}

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        return {'Items': []}

    def get_item(self, **kwargs):
        item = self.items.get((kwargs.get('Key') or {}).get('id'))
        return {'Item': item} if item else {}

    # -- writes ----------------------------------------------------------
    def put_item(self, **kwargs):
        self.put_calls.append(kwargs)
        item = kwargs.get('Item') or {}
        self.items[item.get('id')] = dict(item)
        return {}

    def delete_item(self, **kwargs):
        self.delete_calls.append(kwargs)
        raise AssertionError('a revoke must never delete a row')

    def update_item(self, **kwargs):
        self.update_calls.append(kwargs)
        key = kwargs.get('Key') or {}
        item = self.items.get(key.get('id'))
        condition = kwargs.get('ConditionExpression', '') or ''
        if 'attribute_exists(id)' in condition and item is None:
            raise self._conditional_failure()
        if 'attribute_not_exists(isRevoked)' in condition and item is not None \
                and 'isRevoked' in item:
            raise self._conditional_failure()
        if item is None:
            # No condition guarded it -- DynamoDB would upsert. Record the fact so
            # "the mirror must not create a row" fails loudly instead of silently.
            item = {'id': key.get('id'), '_created_by_update': True}
            self.items[key.get('id')] = item
        expr = (kwargs.get('UpdateExpression') or '').strip()
        values = kwargs.get('ExpressionAttributeValues') or {}
        assert expr.startswith('SET '), f'unsupported UpdateExpression: {expr!r}'
        for assignment in expr[4:].split(','):
            attr, placeholder = (p.strip() for p in assignment.split('='))
            item[attr] = values[placeholder]
        return {}

    @staticmethod
    def _conditional_failure():
        return ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException',
                       'Message': 'The conditional request failed'}},
            'UpdateItem')


class _Dynamo:
    """``dynamodb.Table(name)`` -> a stable per-name fake table."""

    def __init__(self):
        self.tables = {}
        self.stores = {}

    def seed(self, name, items):
        store = self.stores.setdefault(name, {})
        for item in items:
            store[item['id']] = dict(item)

    def Table(self, name):
        if name not in self.tables:
            self.tables[name] = _FakeTable(name, self.stores.setdefault(name, {}))
        return self.tables[name]


def _load_inbound_handler():
    """Load the inbound handler from its absolute path, deterministically.

    A bare ``import handler`` is fragile: several suites insert their own handler
    directory at the front of ``sys.path`` and import the bare name, so collection
    order could resolve ``handler`` to a different module. Same eviction-and-load-by-
    path pattern as ``tests/test_inbound_whatsapp_payment_superseded.py``.
    """
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, os.path.join(INBOUND_HANDLER_DIR, 'modules'))
    sys.path.insert(0, INBOUND_HANDLER_DIR)
    spec = importlib.util.spec_from_file_location('handler', INBOUND_HANDLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['handler'] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def _inbound_row(row_id, *, wamid='', age_seconds=60, **overrides):
    """A unified-table inbound WhatsApp row, `age_seconds` older than the revoke."""
    row = {
        'id': row_id,
        'messageId': row_id,
        'contactId': CONTACT_ID,
        'channel': 'whatsapp',
        'direction': 'inbound',
        'messageType': 'text',
        'content': TARGET_CONTENT,
        'timestamp': NOW - age_seconds,
        'whatsappMessageId': wamid,
    }
    row.update(overrides)
    return row


def _revoke_row():
    return {
        'id': REVOKE_ID,
        'messageId': REVOKE_ID,
        'contactId': CONTACT_ID,
        'channel': 'whatsapp',
        'direction': 'inbound',
        'messageType': 'revoke',
        'content': '[Message deleted by sender]',
        'timestamp': NOW,
        'whatsappMessageId': REVOKE_WAMID,
    }


def _revoke_message(**payload):
    """The inbound `messages[0]` entry for a revoke, as the handler sees it."""
    message = {
        'from': SENDER_PHONE,
        'id': REVOKE_WAMID,
        'timestamp': str(NOW),
        'type': 'revoke',
    }
    message.update(payload)
    return message


@pytest.fixture()
def h():
    """The real handler module, imported with boto3 patched out."""
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            return _load_inbound_handler()


@pytest.fixture()
def env(h):
    """A wired DynamoDB fake holding the revoke's own row in both tables."""
    dynamo = _Dynamo()
    for table in (h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE):
        dynamo.seed(table, [_revoke_row()])
    with patch.object(h, 'dynamodb', dynamo):
        yield h, dynamo


class _Logs:
    """Captured ``logger.info`` / ``logger.warning`` JSON records."""

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


def _run(h, message=None, *, contact_id=CONTACT_ID, candidates=None, logs=None):
    """Drive the real ``_apply_revoke``, seeding the candidate set at the bound name."""
    logs = logs if logs is not None else _Logs()
    rows = list(candidates or [])
    with patch.object(h, 'query_by_contact', lambda cid, limit=50: rows), \
            patch.object(h.logger, 'info', side_effect=logs.capture), \
            patch.object(h.logger, 'warning', side_effect=logs.capture):
        h._apply_revoke(message if message is not None else _revoke_message(),
                        contact_id, REVOKE_ID, REVOKE_WAMID, SENDER_PHONE, NOW, REQ)
    return logs


def _row(dynamo, h, row_id, table=None):
    return dynamo.stores.get(table or h.UNIFIED_MESSAGES_TABLE, {}).get(row_id)


def _revoked_writes(table):
    return [c for c in table.update_calls
            if 'isRevoked' in (c.get('UpdateExpression') or '')]


# ---------------------------------------------------------------------------
# 1 / 1a -- the exact tier, and what happens when it misses
# ---------------------------------------------------------------------------

def test_exact_id_marks_the_named_message(env):
    h, dynamo = env
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [_inbound_row(TARGET_ID, wamid=TARGET_WAMID)])
    dynamo.seed(h.MESSAGES_TABLE, [_inbound_row(TARGET_ID, wamid=TARGET_WAMID)])

    _run(h, _revoke_message(revoke={'revoked_message_id': TARGET_WAMID}))

    # The index query went to the UNIFIED table, not the inbound one.
    unified_queries = dynamo.Table(h.UNIFIED_MESSAGES_TABLE).queries
    assert [q['IndexName'] for q in unified_queries] == ['whatsappMessageId-index']
    assert unified_queries[0]['ExpressionAttributeValues'] == {':w': TARGET_WAMID}
    assert dynamo.Table(h.MESSAGES_TABLE).queries == []

    target = _row(dynamo, h, TARGET_ID)
    assert target['isRevoked'] is True
    assert int(target['revokedAt']) == NOW
    assert target['revokedByWhatsappMessageId'] == REVOKE_WAMID
    assert target['revokeResolution'] == 'exact'


def test_an_exact_id_that_matches_nothing_falls_back_to_inferred(env):
    """An id Meta supplied for a message we never stored must FALL THROUGH, not decline."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, wamid='wamid.OTHER')
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    logs = _run(h, _revoke_message(revoke={'revoked_message_id': 'wamid.NEVER_STORED'}),
                candidates=[candidate])

    assert _row(dynamo, h, TARGET_ID)['revokeResolution'] == 'inferred'
    assert logs.named('revoke_target_unresolved') == [], (
        'an exact miss with one valid candidate must not decline')


# ---------------------------------------------------------------------------
# 2 / 2a -- the inferred tier
# ---------------------------------------------------------------------------

def test_inferred_marks_the_single_recent_candidate(env):
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    _run(h, candidates=[candidate])

    target = _row(dynamo, h, TARGET_ID)
    assert target['isRevoked'] is True
    assert target['revokeResolution'] == 'inferred'
    assert target['revokedByWhatsappMessageId'] == REVOKE_WAMID


def test_a_candidate_with_a_non_numeric_timestamp_is_skipped_not_fatal(env):
    """An ISO-8601 `timestamp` is the shape amplify/data/resource.ts DECLARES.

    A bare int() on such a row would raise inside the candidate comprehension and break
    the never-raises contract. _epoch_or_zero scores it 0, i.e. outside the window.
    """
    h, dynamo = env
    malformed = _inbound_row('msg-iso', timestamp='2026-10-07T12:00:00.000Z')
    valid = _inbound_row(TARGET_ID, age_seconds=120)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [malformed, valid])

    logs = _run(h, candidates=[malformed, valid])

    assert _row(dynamo, h, TARGET_ID)['revokeResolution'] == 'inferred'
    assert 'isRevoked' not in _row(dynamo, h, 'msg-iso')
    assert logs.named('revoke_apply_error') == []
    assert h._epoch_or_zero('2026-10-07T12:00:00.000Z') == 0
    assert h._epoch_or_zero(None) == 0
    assert h._epoch_or_zero('1790000000') == NOW


# ---------------------------------------------------------------------------
# 3 / 4 / 5 -- the restraint cases
# ---------------------------------------------------------------------------

def test_two_candidates_mark_nothing(env):
    """Two messages in the window means we do not know which was deleted."""
    h, dynamo = env
    first = _inbound_row('msg-a', age_seconds=60)
    second = _inbound_row('msg-b', age_seconds=120)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [first, second])

    logs = _run(h, candidates=[first, second])

    for table in dynamo.tables.values():
        assert _revoked_writes(table) == [], 'ambiguity must mark nothing'
    declined = logs.named('revoke_target_unresolved')
    assert len(declined) == 1
    assert declined[0]['candidateCount'] == 2
    assert declined[0]['reason'] == 'ambiguous'
    assert declined[0]['hadExactId'] is False
    # The sender phone is masked, and the full number appears in NO captured record.
    assert declined[0]['senderPhone'] == h.mask_phone(SENDER_PHONE)
    assert SENDER_PHONE not in declined[0]['senderPhone']
    assert all(SENDER_PHONE not in raw for raw in logs.raw)


def test_a_candidate_outside_the_window_is_not_marked(env):
    """The offset is computed FROM the constant, so widening it cannot invalidate this."""
    h, dynamo = env
    stale = _inbound_row(TARGET_ID,
                         age_seconds=h.REVOKE_CORRELATION_WINDOW_SECONDS + 1)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [stale])

    logs = _run(h, candidates=[stale])

    assert 'isRevoked' not in _row(dynamo, h, TARGET_ID)
    assert logs.named('revoke_target_unresolved')[0]['reason'] == 'no_candidate'


def test_a_future_candidate_is_not_marked(env):
    """Reordered webhooks: a revoke cannot delete a message that arrives after it."""
    h, dynamo = env
    future = _inbound_row(TARGET_ID, age_seconds=-30)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [future])

    logs = _run(h, candidates=[future])

    assert 'isRevoked' not in _row(dynamo, h, TARGET_ID)
    assert logs.named('revoke_target_unresolved')[0]['candidateCount'] == 0


def test_the_candidate_read_goes_through_the_contact_index_on_the_unified_table(h):
    """The one test that lets the REAL query_by_contact run.

    It pins decision 5's "default, not an argument" reading: the inferred tier passes no
    ``table_name``, so the read lands on ``message_store.MESSAGES_TABLE``, which is
    ``os.environ['UNIFIED_MESSAGES_TABLE']`` -- the OPPOSITE of this handler's own
    ``MESSAGES_TABLE`` (the inbound table). If someone later threads the handler's table
    through, this goes red and no other inferred-tier test would.
    """
    from lambda_utils import message_store

    assert message_store.MESSAGES_TABLE == h.UNIFIED_MESSAGES_TABLE, (
        'the fixture environment must make the two names agree for this to mean anything')
    assert message_store.MESSAGES_TABLE != h.MESSAGES_TABLE

    handler_dynamo = _Dynamo()
    for table in (h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE):
        handler_dynamo.seed(table, [_revoke_row()])
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    handler_dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    store_dynamo = _Dynamo()
    store_dynamo.seed(message_store.MESSAGES_TABLE, [candidate])

    with patch.object(h, 'dynamodb', handler_dynamo), \
            patch.object(message_store, '_dynamodb', store_dynamo):
        h._apply_revoke(_revoke_message(), CONTACT_ID, REVOKE_ID, REVOKE_WAMID,
                        SENDER_PHONE, NOW, REQ)

    read = store_dynamo.Table(message_store.MESSAGES_TABLE)
    assert [q['IndexName'] for q in read.queries] == ['contactId-index']
    assert read.queries[0]['ExpressionAttributeValues'] == {':c': CONTACT_ID}
    assert read.queries[0]['Limit'] == 50
    assert read.scan_calls == [], 'the candidate read must never fall back to a scan'
    # And the handler's own inbound table was never used for the candidate read.
    assert store_dynamo.Table(h.MESSAGES_TABLE).queries == []
    assert _row(handler_dynamo, h, TARGET_ID)['revokeResolution'] == 'inferred'


# ---------------------------------------------------------------------------
# 6 / 7 / 7a / 7b -- idempotence and the back-link
# ---------------------------------------------------------------------------

def test_redelivery_is_a_no_op(env):
    """attribute_not_exists(isRevoked) makes a second delivery harmless, and says so."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])
    dynamo.seed(h.MESSAGES_TABLE, [candidate])

    _run(h, candidates=[candidate])
    first_revoked_at = _row(dynamo, h, TARGET_ID)['revokedAt']

    logs = _run(h, candidates=[dict(candidate)])

    assert _row(dynamo, h, TARGET_ID)['revokedAt'] == first_revoked_at
    assert _row(dynamo, h, TARGET_ID)['revokeResolution'] == 'inferred'
    already = logs.named('revoke_already_applied')
    assert len(already) == 2, 'both tables report the guard doing its job'
    assert {r['table'] for r in already} == {h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE}


def test_the_revoke_row_survives_and_back_links(env):
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    _run(h, candidates=[candidate])

    revoke = _row(dynamo, h, REVOKE_ID)
    assert revoke is not None, 'the revoke row is never removed'
    assert revoke['content'] == '[Message deleted by sender]'
    assert revoke['revokesMessageId'] == TARGET_ID
    assert revoke['revokeResolution'] == 'inferred'


def test_the_backlink_lands_in_the_table_the_inbox_reads(env):
    """messages-read serves the UNIFIED table and nothing else.

    A back-link written only to WhatsAppInboundTable could never reach the frontend, so
    the revoke bubble would never stop rendering -- the exact double render this closes.
    """
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    _run(h, candidates=[candidate])

    for table in (h.UNIFIED_MESSAGES_TABLE, h.MESSAGES_TABLE):
        revoke = _row(dynamo, h, REVOKE_ID, table=table)
        assert revoke['revokesMessageId'] == TARGET_ID, f'missing back-link on {table}'
        assert revoke['revokeResolution'] == 'inferred'


def test_the_backlink_does_not_create_a_row(env):
    """attribute_exists(id) only -- the mirror must never insert the revoke row."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])
    # The revoke row is absent from the unified table (a dual-write that failed).
    del dynamo.stores[h.UNIFIED_MESSAGES_TABLE][REVOKE_ID]

    logs = _run(h, candidates=[candidate])

    assert REVOKE_ID not in dynamo.stores[h.UNIFIED_MESSAGES_TABLE]
    # Processing still completed: the target was marked and the inbound back-link landed.
    assert _row(dynamo, h, TARGET_ID)['isRevoked'] is True
    assert _row(dynamo, h, REVOKE_ID, table=h.MESSAGES_TABLE)['revokesMessageId'] == TARGET_ID
    # A missing back-link target is not an error worth a warning.
    assert logs.named('revoke_backlink_failed') == []


# ---------------------------------------------------------------------------
# 8 / 9 / 10 -- what must never be touched
# ---------------------------------------------------------------------------

def test_content_is_never_deleted_or_blanked(env):
    """Mark, never delete, never redact: the row is the provenance record."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])
    dynamo.seed(h.MESSAGES_TABLE, [candidate])

    _run(h, candidates=[candidate])

    for table in (h.UNIFIED_MESSAGES_TABLE, h.MESSAGES_TABLE):
        assert _row(dynamo, h, TARGET_ID, table=table)['content'] == TARGET_CONTENT
    for table in dynamo.tables.values():
        assert table.delete_calls == []
        assert table.put_calls == []
    # No write touches `content` at all.
    for table in dynamo.tables.values():
        for call in table.update_calls:
            assert 'content' not in (call.get('UpdateExpression') or '')


def test_a_payment_row_is_never_a_revoke_target(env):
    """A payment record is structurally excluded, so this path cannot reach it."""
    h, dynamo = env
    payment = _inbound_row(TARGET_ID, age_seconds=60,
                           paymentReferenceId='WD-PAY-1', messageType='payment')
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [payment])

    logs = _run(h, candidates=[payment])

    assert 'isRevoked' not in _row(dynamo, h, TARGET_ID)
    assert logs.named('revoke_target_unresolved')[0]['candidateCount'] == 0


def test_an_outbound_candidate_is_never_marked(env):
    h, dynamo = env
    outbound = _inbound_row(TARGET_ID, age_seconds=60, direction='outbound')
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [outbound])

    logs = _run(h, candidates=[outbound])

    assert 'isRevoked' not in _row(dynamo, h, TARGET_ID)
    assert logs.named('revoke_target_unresolved')[0]['reason'] == 'no_candidate'


# ---------------------------------------------------------------------------
# 11 / 11a -- the two tables, and resolving on one store
# ---------------------------------------------------------------------------

def test_a_mirror_write_cannot_create_a_row(env):
    """Target in the unified table, absent from the inbound one. Neither write inserts."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    logs = _run(h, candidates=[candidate])

    assert _row(dynamo, h, TARGET_ID)['isRevoked'] is True
    assert TARGET_ID not in dynamo.stores[h.MESSAGES_TABLE]
    already = [r for r in logs.named('revoke_already_applied')
               if r['table'] == h.MESSAGES_TABLE]
    assert len(already) == 1, 'the inbound miss is logged at info, not raised'
    # Processing completed: the back-link still landed on both tables.
    assert _row(dynamo, h, REVOKE_ID)['revokesMessageId'] == TARGET_ID


def test_a_target_missing_from_the_unified_table_is_a_clean_decline(env):
    """Both tiers resolve on the unified store, so a row only in the inbound table is
    invisible to resolution -- a row the inbox cannot render is a row there is no point
    marking. A decline, not a partial write."""
    h, dynamo = env
    dynamo.seed(h.MESSAGES_TABLE, [_inbound_row(TARGET_ID, wamid=TARGET_WAMID)])

    logs = _run(h, _revoke_message(revoke={'revoked_message_id': TARGET_WAMID}),
                candidates=[])

    for table in dynamo.tables.values():
        assert _revoked_writes(table) == []
    declined = logs.named('revoke_target_unresolved')
    assert len(declined) == 1
    assert declined[0]['hadExactId'] is True
    assert declined[0]['candidateCount'] == 0
    assert 'isRevoked' not in dynamo.stores[h.MESSAGES_TABLE][TARGET_ID]


# ---------------------------------------------------------------------------
# 12 -- a revoke is not a send
# ---------------------------------------------------------------------------

def test_a_revoke_sends_nothing(env):
    """The zero-send discipline: nothing reaches the Graph API or another Lambda."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])
    lambda_client = MagicMock()

    with patch('urllib.request.urlopen') as urlopen, \
            patch.object(h, 'lambda_client', lambda_client), \
            patch.object(h, 'sqs', MagicMock()):
        _run(h, candidates=[candidate])

    assert urlopen.call_count == 0
    assert lambda_client.invoke.call_count == 0
    # And it did do its job.
    assert _row(dynamo, h, TARGET_ID)['isRevoked'] is True


# ---------------------------------------------------------------------------
# Supporting guarantees -- the id scan, the de-duplicated loops, the call site
# ---------------------------------------------------------------------------

def test_every_target_id_key_spelling_is_read(env):
    """All three spellings are checked so a future Meta payload needs no code change."""
    h, dynamo = env
    assert h._REVOKE_TARGET_ID_KEYS == ('revoked_message_id', 'id', 'message_id')

    for source, key in (('revoke', 'revoked_message_id'),
                        ('revoke', 'message_id'),
                        ('context', 'id'),
                        ('context', 'message_id')):
        dynamo = _Dynamo()
        for table in (h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE):
            dynamo.seed(table, [_revoke_row()])
        dynamo.seed(h.UNIFIED_MESSAGES_TABLE,
                    [_inbound_row(TARGET_ID, wamid=TARGET_WAMID)])
        with patch.object(h, 'dynamodb', dynamo):
            _run(h, _revoke_message(**{source: {key: TARGET_WAMID}}))
        assert _row(dynamo, h, TARGET_ID)['revokeResolution'] == 'exact', (
            f'{source}.{key} was not read as a target id')

    # The revoke's OWN wamid is never treated as the target id.
    dynamo = _Dynamo()
    for table in (h.MESSAGES_TABLE, h.UNIFIED_MESSAGES_TABLE):
        dynamo.seed(table, [_revoke_row()])
    with patch.object(h, 'dynamodb', dynamo):
        logs = _run(h, _revoke_message(), candidates=[])
    assert logs.named('revoke_target_unresolved')[0]['hadExactId'] is False


def test_both_write_loops_are_de_duplicated_when_the_tables_coincide(env):
    """If the two env vars are ever pointed at one table, a second write would fail its
    own attribute_not_exists(isRevoked) condition against the write just made."""
    h, _ = env
    dynamo = _Dynamo()
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [_revoke_row()])
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    with patch.object(h, 'MESSAGES_TABLE', h.UNIFIED_MESSAGES_TABLE), \
            patch.object(h, 'dynamodb', dynamo):
        logs = _run(h, candidates=[candidate])

    table = dynamo.Table(h.UNIFIED_MESSAGES_TABLE)
    assert len(_revoked_writes(table)) == 1, 'one table means exactly one mark'
    assert logs.named('revoke_already_applied') == []
    assert _row(dynamo, h, TARGET_ID)['isRevoked'] is True
    assert _row(dynamo, h, REVOKE_ID)['revokesMessageId'] == TARGET_ID


def test_the_exact_tier_degrades_to_inferred_when_the_index_is_unavailable(env):
    """A missing or not-yet-active GSI must not fail the revoke, and must not scan."""
    h, dynamo = env
    candidate = _inbound_row(TARGET_ID, age_seconds=60)
    dynamo.seed(h.UNIFIED_MESSAGES_TABLE, [candidate])

    def boom(**kwargs):
        raise ClientError({'Error': {'Code': 'ValidationException',
                                     'Message': 'index not active'}}, 'Query')

    with patch.object(dynamo.Table(h.UNIFIED_MESSAGES_TABLE), 'query', boom):
        logs = _run(h, _revoke_message(revoke={'revoked_message_id': TARGET_WAMID}),
                    candidates=[candidate])

    assert logs.named('revoke_exact_lookup_failed')[0]['error'] == 'ClientError'
    assert dynamo.Table(h.UNIFIED_MESSAGES_TABLE).scan_calls == []
    assert _row(dynamo, h, TARGET_ID)['revokeResolution'] == 'inferred'


def test_process_message_applies_the_revoke_for_a_revoke_type(h):
    """The call site exists, is reached only for `revoke`, and is fail-open.

    Asserted on the module source rather than by driving the 1100-line
    ``_process_message``: what matters is that the guarded call is present with all
    seven in-scope arguments, after the dual-write and before the ownership signal.
    """
    import inspect
    source = inspect.getsource(h._process_message)
    assert "if msg_type == 'revoke':" in source
    assert ('_apply_revoke(message, contact_id, message_id, whatsapp_message_id,'
            in source)
    assert "'revoke_apply_error'" in source
    # Ordering: after the unified dual-write, before the thread-ownership signal.
    assert source.index('put_message(') < source.index('_apply_revoke(')
    assert source.index('_apply_revoke(') < source.index('thread_ownership.record_signal')
