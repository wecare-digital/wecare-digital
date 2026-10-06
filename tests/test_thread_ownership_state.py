"""Derived thread ownership: set, clear, and the 24-hour idle reset.

Why derived state needs its own tests before anything gates on it
-----------------------------------------------------------------
Meta's Conversation Routing has no ownership API — the docs require an integration to
*derive* ownership from four signals and maintain it locally. That means every answer this
module gives is a belief rather than a reading, and the only way a belief gets to refuse a
customer a reply is if it has first been shown to be right. So this release writes and logs
only, and these tests pin the transitions so the eventual enforcement has something to
stand on.

The DynamoDB fake
-----------------
A dict-backed table injected through `thread_ownership.set_table`, implementing just the
two shapes the module uses: `update_item` with a `SET` expression plus
`ReturnValues='ALL_NEW'`, and `get_item`. Deliberately narrow rather than moto: a fake that
only supports what is used will break loudly if the module starts doing something else,
which is the behaviour wanted from a test double on a path that gates sends.

`if_not_exists(#act, :now)` is supported because it is load-bearing, not incidental — see
`test_a_handover_does_not_move_the_idle_clock`.
"""
import os
import re
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SHARED = os.path.join(_ROOT, 'amplify', 'functions', 'shared')
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from lambda_utils import thread_ownership as to  # noqa: E402

PID = '1055232054343117'
BSUID = 'BSUID-TEST-1'
WA_ID = '918100640044'
DAY = 86400


class FakeTable:
    """Enough DynamoDB to exercise the module, and no more."""

    def __init__(self, fail=False):
        self.items = {}
        self.fail = fail
        self.puts = []
        self.updates = 0

    @staticmethod
    def _k(key):
        return (key[to.TABLE_HASH_KEY], key[to.TABLE_RANGE_KEY])

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues, ReturnValues=None):
        if self.fail:
            raise RuntimeError('simulated DynamoDB failure')
        self.updates += 1
        item = dict(self.items.get(self._k(Key), {}))
        item.update(Key)
        body = UpdateExpression[len('SET '):]
        # Split on commas that are not inside parentheses, so `if_not_exists(#a, :b)`
        # survives as one clause.
        for clause in re.split(r',\s*(?![^()]*\))', body):
            target, expr = [part.strip() for part in clause.split('=', 1)]
            attribute = ExpressionAttributeNames[target]
            guard = re.fullmatch(r'if_not_exists\((#\w+),\s*(:\w+)\)', expr)
            if guard:
                existing = item.get(ExpressionAttributeNames[guard.group(1)])
                if existing is None:
                    item[attribute] = ExpressionAttributeValues[guard.group(2)]
            else:
                item[attribute] = ExpressionAttributeValues[expr]
        self.items[self._k(Key)] = item
        return {'Attributes': dict(item)} if ReturnValues == 'ALL_NEW' else {}

    def get_item(self, Key):
        if self.fail:
            raise RuntimeError('simulated DynamoDB failure')
        item = self.items.get(self._k(Key))
        return {'Item': dict(item)} if item else {}

    def put_item(self, Item):
        if self.fail:
            raise RuntimeError('simulated DynamoDB failure')
        self.puts.append(Item)
        self.items[(Item[to.TABLE_HASH_KEY], Item[to.TABLE_RANGE_KEY])] = dict(Item)
        return {}


@pytest.fixture
def table():
    fake = FakeTable()
    to.set_table(fake)
    yield fake
    to.set_table(None)


@pytest.fixture
def broken_table():
    fake = FakeTable(fail=True)
    to.set_table(fake)
    yield fake
    to.set_table(None)


class TestThreadKey:
    def test_bsuid_wins_over_wa_id(self):
        """Meta's guidance is to index by business-scoped user ID, and a BSUID is the
        stabler of the two: a wa_id changes when a customer changes phone number, which
        arrives as a `user_changed_user_id` system message this handler already handles."""
        assert to.thread_key(PID, bsuid=BSUID, wa_id=WA_ID) == f'{PID}#{BSUID}'

    def test_wa_id_is_the_fallback(self):
        assert to.thread_key(PID, wa_id=WA_ID) == f'{PID}#{WA_ID}'

    @pytest.mark.parametrize('pid,bsuid,wa_id', [
        ('', BSUID, WA_ID), (PID, '', ''), ('', '', ''),
        ('   ', BSUID, ''), (PID, '  ', '  '),
    ])
    def test_returns_empty_when_the_thread_cannot_be_identified(self, pid, bsuid, wa_id):
        """A partial key would collide every untrackable thread onto one row, which is
        worse than not tracking: it would read as state about a specific conversation."""
        assert to.thread_key(pid, bsuid=bsuid, wa_id=wa_id) == ''

    def test_the_phone_id_is_part_of_the_key(self):
        """One contact can hold TWO independent threads — the same person talks to both
        WABA numbers, and those threads can have different owners at the same moment."""
        a = to.thread_key('1016149501586345', bsuid=BSUID)
        b = to.thread_key('1055232054343117', bsuid=BSUID)
        assert a != b


class TestSignalsSetAndClearOwnership:
    @pytest.mark.parametrize('signal', [
        to.SIGNAL_MESSAGE_RECEIVED,
        to.SIGNAL_HANDOVER_GAINED,
        to.SIGNAL_SERVICE_MESSAGE_SENT,
    ])
    def test_ownership_claiming_signals_set_owned(self, table, signal):
        state = to.record_signal(PID, bsuid=BSUID, signal=signal, now=1000)
        assert state['tracked'] is True
        assert state['owned'] is True
        assert state['lastSignal'] == signal

    @pytest.mark.parametrize('signal', [
        to.SIGNAL_HANDOVER_LOST,
        to.SIGNAL_STANDBY_OBSERVED,
    ])
    def test_ownership_losing_signals_clear_owned(self, table, signal):
        to.record_signal(PID, bsuid=BSUID,
                         signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        state = to.record_signal(PID, bsuid=BSUID, signal=signal, now=1001)
        assert state['owned'] is False
        assert state['lastSignal'] == signal

    def test_control_taken_then_control_passed_round_trips(self, table):
        """The pair that matters: losing a thread then being given it back."""
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_HANDOVER_LOST, now=1000)
        assert to.get_state(PID, bsuid=BSUID, now=1000)['owned'] is False
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_HANDOVER_GAINED, now=1001)
        assert to.get_state(PID, bsuid=BSUID, now=1001)['owned'] is True

    def test_an_unknown_signal_is_refused_rather_than_stored(self, table):
        state = to.record_signal(PID, bsuid=BSUID, signal='something_invented', now=1000)
        assert state['tracked'] is False
        assert table.updates == 0

    def test_an_unkeyable_thread_writes_nothing(self, table):
        state = to.record_signal('', bsuid='', wa_id='',
                                 signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        assert state['tracked'] is False
        assert table.updates == 0

    def test_every_write_carries_a_ttl(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        stored = table.items[(f'{PID}#{BSUID}', to.RECORD_OWNER)]
        assert stored['expiresAt'] == 1000 + to.RECORD_TTL_SECONDS

    def test_the_ttl_outlasts_the_idle_reset(self):
        """State that expired at the 24h boundary could not be RECONCILED against the
        idle reset — you have to still hold the stale value to notice it went idle."""
        assert to.RECORD_TTL_SECONDS > to.IDLE_RESET_SECONDS


class TestTheIdleReset:
    def test_a_thread_idle_for_24h_reports_not_owned(self, table):
        """Meta's thread lifecycle: a thread returns to idle on its own after 24h of USER
        inactivity, and local state must be reconciled against that. A stored owned=True
        older than the reset is a belief about a state that no longer exists."""
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        state = to.get_state(PID, bsuid=BSUID, now=1000 + DAY)
        assert state['idle'] is True
        assert state['owned'] is False
        # The stored value is still visible, so the reset is observable rather than a
        # silent overwrite of what we were actually told.
        assert state['storedOwned'] is True

    def test_just_under_24h_is_not_idle(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        state = to.get_state(PID, bsuid=BSUID, now=1000 + DAY - 1)
        assert state['idle'] is False
        assert state['owned'] is True

    def test_the_reset_is_exactly_24h(self):
        assert to.IDLE_RESET_SECONDS == DAY

    def test_a_new_user_message_restarts_the_clock(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED,
                         now=1000 + DAY + 50)
        state = to.get_state(PID, bsuid=BSUID, now=1000 + DAY + 60)
        assert state['idle'] is False
        assert state['owned'] is True

    def test_a_handover_does_not_move_the_idle_clock(self, table):
        """The reset is defined on USER inactivity. A control change is not the user
        doing anything, so it must not keep a dead thread looking alive."""
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_HANDOVER_GAINED,
                         now=1000 + DAY - 10)
        state = to.get_state(PID, bsuid=BSUID, now=1000 + DAY)
        assert state['idle'] is True

    def test_a_handover_on_a_fresh_thread_is_not_born_idle(self, table):
        """`if_not_exists` seeds the clock on the first write, so a thread whose only
        signal is a handover does not read as idle-since-the-epoch."""
        state = to.record_signal(PID, bsuid=BSUID,
                                 signal=to.SIGNAL_HANDOVER_GAINED, now=1000)
        assert state['idle'] is False
        assert state['owned'] is True

    def test_a_business_send_does_not_hold_the_thread_open(self, table):
        """Same rule as the handover: sending is not the user being active."""
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_SERVICE_MESSAGE_SENT,
                         now=1000 + DAY - 10)
        assert to.get_state(PID, bsuid=BSUID, now=1000 + DAY)['idle'] is True


class TestMaySendFailsOpen:
    """The opposite of otp_throttle, deliberately, and worth a test that says why."""

    def test_unknown_thread_may_send(self, table):
        """No row yet is the normal case for every thread that has not spoken since this
        table was created. Refusing would mute the whole customer base."""
        assert to.may_send(PID, bsuid='never-seen') is True

    def test_unkeyable_thread_may_send(self, table):
        assert to.may_send('', bsuid='', wa_id='') is True

    def test_a_read_failure_may_send(self, broken_table):
        """A DynamoDB blip must not be the reason a customer goes unanswered. This guards
        a path that ANSWERS someone; otp_throttle guards one that spends money and rings
        a stranger's handset, which is why that one fails closed and this one does not."""
        assert to.may_send(PID, bsuid=BSUID) is True

    def test_a_known_unowned_thread_may_not_send(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_STANDBY_OBSERVED, now=1000)
        assert to.may_send(PID, bsuid=BSUID, now=1000) is False

    def test_a_known_owned_thread_may_send(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        assert to.may_send(PID, bsuid=BSUID, now=1000) is True

    def test_an_idle_owned_thread_may_not_send(self, table):
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        assert to.may_send(PID, bsuid=BSUID, now=1000 + DAY) is False


class TestWritesNeverRaise:
    """These run on the inbound webhook path beside real customer messages."""

    def test_record_signal_survives_a_write_failure(self, broken_table):
        state = to.record_signal(PID, bsuid=BSUID,
                                 signal=to.SIGNAL_MESSAGE_RECEIVED, now=1000)
        assert state['tracked'] is False

    def test_get_state_survives_a_read_failure(self, broken_table):
        assert to.get_state(PID, bsuid=BSUID)['tracked'] is False

    def test_store_standby_message_survives_a_write_failure(self, broken_table):
        assert to.store_standby_message(
            PID, bsuid=BSUID, message={'id': 'wamid.X', 'type': 'text'}) is False


class TestConversationContext:
    def test_it_is_persisted_when_present(self, table):
        context = {'summary': 'Customer asked about delivery timelines.'}
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_HANDOVER_GAINED,
                         conversation_context=context, now=1000)
        assert to.get_state(PID, bsuid=BSUID, now=1000)['conversationContext'] == context

    def test_a_later_signal_without_one_does_not_erase_it(self, table):
        """It arrives only on control_passed, and only sometimes. Writing None over a
        stored summary would discard the most useful thing a handover ever gives us."""
        context = {'summary': 'Discussed a refund.'}
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_HANDOVER_GAINED,
                         conversation_context=context, now=1000)
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED, now=1001)
        assert to.get_state(PID, bsuid=BSUID, now=1001)['conversationContext'] == context


class TestStandbyContextRows:
    def test_a_standby_message_is_stored_and_marked(self, table):
        stored = to.store_standby_message(
            PID, bsuid=BSUID,
            message={'id': 'wamid.ABC', 'type': 'text', 'timestamp': '1700000000'},
            content='what are your hours', now=1000)
        assert stored is True
        row = table.puts[0]
        assert row[to.TABLE_HASH_KEY] == f'{PID}#{BSUID}'
        assert row[to.TABLE_RANGE_KEY].startswith(to.RECORD_STANDBY_PREFIX)
        # The marker is the whole point: a standby copy is NOT a message addressed to us.
        assert row['standbySourced'] is True
        assert row['content'] == 'what are your hours'
        assert row['expiresAt'] == 1000 + to.RECORD_TTL_SECONDS

    def test_rows_sort_under_the_same_partition_as_the_owner_row(self, table):
        """One table with a sort key so that gaining control is a single query: the owner
        row and the context explaining it come back together."""
        to.record_signal(PID, bsuid=BSUID, signal=to.SIGNAL_STANDBY_OBSERVED, now=1000)
        to.store_standby_message(PID, bsuid=BSUID,
                                 message={'id': 'wamid.A', 'type': 'text'}, now=1001)
        partitions = {k[0] for k in table.items}
        assert partitions == {f'{PID}#{BSUID}'}

    def test_two_messages_do_not_overwrite_each_other(self, table):
        to.store_standby_message(PID, bsuid=BSUID,
                                 message={'id': 'wamid.A', 'type': 'text'}, now=1000)
        to.store_standby_message(PID, bsuid=BSUID,
                                 message={'id': 'wamid.B', 'type': 'text'}, now=1000)
        assert len(table.puts) == 2
        assert len({row[to.TABLE_RANGE_KEY] for row in table.puts}) == 2

    def test_a_message_with_no_id_still_stores(self, table):
        """Losing a standby message because Meta omitted a field would reintroduce the
        discard this storage exists to fix."""
        assert to.store_standby_message(PID, bsuid=BSUID, message={'type': 'text'},
                                        now=1000) is True

    def test_an_unkeyable_thread_stores_nothing(self, table):
        assert to.store_standby_message('', message={'id': 'x'}) is False
        assert table.puts == []


class TestSignalForControl:
    @pytest.mark.parametrize('control,expected', [
        (to.CONTROL_PASSED, to.SIGNAL_HANDOVER_GAINED),
        (to.CONTROL_TAKEN, to.SIGNAL_HANDOVER_LOST),
        ('', ''),
        ('something_else', ''),
    ])
    def test_mapping(self, control, expected):
        assert to.signal_for_control({'control': control}) == expected

    def test_a_missing_record_maps_to_nothing(self):
        assert to.signal_for_control({}) == ''
        assert to.signal_for_control(None) == ''

    @pytest.mark.parametrize('builder_control,expected', [
        ('control_passed', to.SIGNAL_HANDOVER_GAINED),
        ('control_taken', to.SIGNAL_HANDOVER_LOST),
    ])
    def test_each_live_payload_shape_drives_the_right_signal(self, table,
                                                             builder_control, expected):
        """End to end across the parser and the store, for all three payload shapes we
        have actually seen — the documented one and the two legacy ones."""
        payloads = [
            {  # documented
                'metadata': {'phone_number_id': PID},
                'contacts': [{'wa_id': WA_ID, 'user_id': BSUID}],
                builder_control: {'previous_owner_role': 'ai_agent',
                                  'new_owner_role': 'business'},
            },
            {  # legacy bare-string metadata
                'metadata': {'phone_number_id': PID},
                'contacts': [{'wa_id': WA_ID}],
                builder_control: {'metadata': '{"reason": "MARKETING_MESSAGE"}'},
            },
            {  # legacy app-role pair
                'metadata': {'phone_number_id': PID},
                'contacts': [{'wa_id': WA_ID, 'user_id': BSUID}],
                builder_control: {'previous_owner_app_id': '1143680903703001',
                                  'previous_owner_app_role': 'meta_business_agent'},
            },
        ]
        for payload in payloads:
            record = to.parse_handover(payload)
            assert to.signal_for_control(record) == expected
            state = to.record_signal(
                record['phone_number_id'], bsuid=record['bsuid'],
                wa_id=record['wa_id'], signal=expected, now=1000)
            assert state['tracked'] is True
            assert state['owned'] is (expected == to.SIGNAL_HANDOVER_GAINED)


class TestTheHandlerWiresAllFourSignals:
    """The module is useless if the signals are never recorded. Asserted against the
    handler source because the call sites are inside a 7000-line request path."""

    @pytest.fixture(scope='class')
    def source(self):
        path = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                            'inbound-whatsapp-handler', 'handler.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    @pytest.mark.parametrize('signal_const', [
        'SIGNAL_MESSAGE_RECEIVED',
        'SIGNAL_STANDBY_OBSERVED',
    ])
    def test_webhook_signals_are_recorded(self, source, signal_const):
        assert f'thread_ownership.{signal_const}' in source

    def test_handover_signals_go_through_the_mapper(self, source):
        """`signal_for_control` keeps the control-event-to-ownership mapping in one place
        rather than duplicating an if/else at the call site."""
        assert 'thread_ownership.signal_for_control(' in source

    def test_nothing_gates_a_send_on_may_send_yet(self, source):
        """Phase 2 is write-and-log only. If this starts failing, a release has begun
        enforcing state that has not been observed against real delivery."""
        assert 'thread_ownership.may_send(' not in source \
            or '_standby_reply_enabled()' in source
