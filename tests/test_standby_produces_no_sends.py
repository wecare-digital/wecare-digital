"""A standby webhook must produce ZERO Graph sends when STANDBY_REPLY_ENABLED is false.

The defect being fixed
----------------------
The standby arm of `inbound-whatsapp-handler/handler.py` deliberately falls a filtered
subset of standby messages through into full normal processing, and the comment that used
to sit there stated the intent: *"sending a reply takes thread control from the AI"*. That
was true on 2026-07-21, when it was written — the Meta Business Agent shared the phone
number and no Conversation Routing configuration existed.

Meta's current Standby-partners and Thread-lifecycle docs close that path:

* Once routing is active, **only the designated escalation partner** can take a thread by
  sending; a Service message from any other standby partner is **rejected**.
* A Service message from a responder that does not own the thread **fails with an API
  error** rather than silently doing nothing.
* **Receiving** the message is what makes you the owner — you do not reply to claim it.

So the failure mode is not a double reply or a hijack. It is a **silent dead end**: the
customer taps a menu row, Meta refuses our send, and nothing arrives. Thirteen distinct
outbound side-effects are reachable from a standby copy, including a payment Review & Pay.

Why the flag defaults TRUE and these tests are shaped around that
-----------------------------------------------------------------
`wecare-whatsapp-calling` invokes `wecare-inbound-whatsapp` **unqualified**, so `$LATEST`
is production: this code is live the instant `update-function-code` returns, before any
alias move. There is no staging gap in which to verify a behaviour change, so the fix
ships inert and `STANDBY_REPLY_ENABLED` defaults to today's behaviour. That makes the
flag-TRUE tests as load-bearing as the flag-FALSE ones — they are the proof that shipping
this changed nothing.

Counting at BOTH Graph boundaries
---------------------------------
There are two, and counting one would miss half the sends:

* `urllib.request.urlopen` — the Direct API path (`_send_direct_api_message`,
  `_send_direct_api_reaction`, `_send_direct_api_read_receipt`).
* `lambda_client.invoke` — everything routed through `wecare-outbound-whatsapp`,
  including the payment `order_details`.
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_INBOUND_DIR = _ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler'
HANDLER_PATH = _INBOUND_DIR / 'handler.py'

for _p in (str(_ROOT / 'amplify/functions/shared'), str(_INBOUND_DIR),
           str(_INBOUND_DIR / 'modules')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lambda_utils import thread_ownership as to  # noqa: E402

META_PHONE = '1016149501586345'          # WABA1, Direct API
AWS_PHONE = 'phone-number-id-waba1-direct-1016149501586345'
WABA = '2094615664435155'
WA_ID = '918100640044'
BSUID = 'BSUID-STANDBY-1'


# ── fixtures ────────────────────────────────────────────────────────────────────

class FakeOwnershipTable:
    """Minimal DynamoDB for thread_ownership. Mirrors tests/test_thread_ownership_state."""

    def __init__(self):
        self.items = {}
        self.standby_rows = []

    @staticmethod
    def _k(key):
        return (key[to.TABLE_HASH_KEY], key[to.TABLE_RANGE_KEY])

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues, ReturnValues=None):
        import re
        item = dict(self.items.get(self._k(Key), {}))
        item.update(Key)
        for clause in re.split(r',\s*(?![^()]*\))', UpdateExpression[len('SET '):]):
            target, expr = [p.strip() for p in clause.split('=', 1)]
            attribute = ExpressionAttributeNames[target]
            guard = re.fullmatch(r'if_not_exists\((#\w+),\s*(:\w+)\)', expr)
            if guard:
                if item.get(ExpressionAttributeNames[guard.group(1)]) is None:
                    item[attribute] = ExpressionAttributeValues[guard.group(2)]
            else:
                item[attribute] = ExpressionAttributeValues[expr]
        self.items[self._k(Key)] = item
        return {'Attributes': dict(item)} if ReturnValues == 'ALL_NEW' else {}

    def get_item(self, Key):
        item = self.items.get(self._k(Key))
        return {'Item': dict(item)} if item else {}

    def put_item(self, Item):
        if str(Item.get(to.TABLE_RANGE_KEY, '')).startswith(to.RECORD_STANDBY_PREFIX):
            self.standby_rows.append(Item)
        self.items[(Item[to.TABLE_HASH_KEY], Item[to.TABLE_RANGE_KEY])] = dict(Item)
        return {}


@pytest.fixture(scope='module')
def h():
    """The inbound handler, loaded by explicit path under a name nothing else uses."""
    spec = importlib.util.spec_from_file_location(
        'inbound_wa_standby_sends', str(HANDLER_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wa_standby_sends'] = module
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            spec.loader.exec_module(module)
    return module


class Run:
    """What one `handler()` invocation did, at both Graph boundaries."""

    def __init__(self):
        self.urlopen_calls = []
        self.invoke_calls = []
        self.messages_put = []
        self.standby_rows = []

    @property
    def total_sends(self):
        return len(self.urlopen_calls) + len(self.invoke_calls)

    @property
    def gated_sends(self):
        """Sends that ownership gates, i.e. everything except the read receipt.

        Needed because the `status: read` / `typing_indicator` POST is DELIBERATELY
        ungated and goes to the same endpoint over the same boundary. A total count would
        therefore stay non-zero even when every gated send was correctly suppressed, so a
        test asserting on the total could not tell the two apart. The menu, the lists and
        the CTAs all go out through `_send_direct_api_message`, not through
        `lambda_client.invoke`, so this cannot be done by picking a boundary either.
        """
        count = len(self.invoke_calls)
        for req in self.urlopen_calls:
            body = (req.data or b'').decode('utf-8', 'replace') if req.data else ''
            if '"status"' in body and 'read' in body:
                continue
            count += 1
        return count

    @property
    def payloads(self):
        out = []
        for call in self.invoke_calls:
            out.append(json.dumps(call.get('Payload', ''), default=str))
        for req in self.urlopen_calls:
            try:
                out.append((req.data or b'').decode('utf-8', 'replace'))
            except Exception:
                out.append('')
        return out


def _standby_event(messages):
    """A standby webhook in the REAL stored shape.

    Taken from the one standby event preserved in SystemConfigTable from
    2026-07-21T06:26:56Z: the message and contacts nest under `value["standby"]`, and
    `value["metadata"]` is present (which is what makes phone resolution work at all).
    """
    return {
        'source': 'meta-direct',
        'version': 1,
        'wabaId': WABA,
        'metaPhoneNumberIds': [META_PHONE],
        'requestId': 'req-standby',
        'entry': {
            'id': WABA,
            'changes': [{
                'field': 'standby',
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {'display_phone_number': '919330994400',
                                 'phone_number_id': META_PHONE},
                    'standby': {
                        'messages': messages,
                        'contacts': [{'wa_id': WA_ID, 'user_id': BSUID,
                                      'profile': {'name': 'QA'}}],
                    },
                },
            }],
        },
    }


def _handover_event(control, block, with_contacts=True):
    value = {
        'messaging_product': 'whatsapp',
        'metadata': {'display_phone_number': '919330994400',
                     'phone_number_id': META_PHONE},
        control: block,
    }
    if with_contacts:
        value['contacts'] = [{'wa_id': WA_ID, 'user_id': BSUID}]
    return {
        'source': 'meta-direct', 'version': 1, 'wabaId': WABA,
        'metaPhoneNumberIds': [META_PHONE], 'requestId': 'req-handover',
        'entry': {'id': WABA, 'changes': [{'field': 'messaging_handovers',
                                           'value': value}]},
    }


def _drive(h, event, *, flag=None, ownership=None, reset_context=True):
    """Invoke `handler()` with both Graph boundaries counted. Returns a `Run`."""
    run = Run()
    table = ownership if ownership is not None else FakeOwnershipTable()
    to.set_table(table)

    env = {'AWS_REGION': 'us-east-1'}
    if flag is not None:
        env['STANDBY_REPLY_ENABLED'] = flag

    tables = {}

    def _table(name):
        if name not in tables:
            mock = MagicMock()
            if name == h.SYSTEM_CONFIG_TABLE:
                # Make the routing-config read fail so `_get_routing_config` falls back to
                # its built-in defaults — which is what production uses today, the
                # `ai_hybrid_routing` row having been absent until it was seeded as a
                # no-op copy of those same defaults.
                mock.get_item.side_effect = RuntimeError('no config row')
            else:
                # REAL dicts, not MagicMocks. A MagicMock `Item` is truthy, so the cart
                # path read it as a stored shipping address and then died inside
                # `json.dumps` — the harness, not the code, but it would have hidden the
                # flag-true money assertions behind an exception.
                mock.get_item.return_value = {'Item': {}}
                mock.query.return_value = {'Items': []}
                mock.update_item.return_value = {'Attributes': {}}
            tables[name] = mock
        return tables[name]

    context = MagicMock()
    context.aws_request_id = 'req-test'
    context.get_remaining_time_in_millis.return_value = 300000

    def _urlopen(req, *a, **kw):
        run.urlopen_calls.append(req)
        resp = MagicMock()
        resp.read.return_value = json.dumps({'messages': [{'id': 'wamid.SENT'}]}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *args: False
        resp.status = 200
        return resp

    def _invoke(**kwargs):
        run.invoke_calls.append(kwargs)
        return {'StatusCode': 202}

    # Reset the 60-second routing-config cache, or the first test's config leaks.
    h._routing_cache['v'] = None
    h._routing_cache['t'] = 0.0
    # Reset the send context between invocations, so one test cannot pass or fail because
    # of another's leftovers. `reset_context=False` deliberately leaves a poisoned context
    # in place — that is how the leak test proves `_process_message` clears it.
    if reset_context:
        h._send_context = {'standby': False, 'phone_number_id': '', 'bsuid': '',
                           'wa_id': ''}

    with patch.dict(os.environ, env, clear=False), \
            patch('urllib.request.urlopen', side_effect=_urlopen), \
            patch.object(h.lambda_client, 'invoke', side_effect=_invoke), \
            patch('lambda_utils.webhook_dedup.claim_event', return_value=True), \
            patch.object(h.dynamodb, 'Table', side_effect=_table), \
            patch.object(h, '_message_exists', return_value=False), \
            patch.object(h, '_get_or_create_contact',
                         return_value={'contactId': 'c-standby', 'welcomeSent': True}), \
            patch.object(h, '_update_contact_timestamp'), \
            patch.object(h, '_load_direct_api_token', return_value='token-placeholder'), \
            patch.object(h, 'put_message'), \
            patch.object(h, '_get_aws_phone_number_id', return_value=AWS_PHONE):
        if flag is None:
            os.environ.pop('STANDBY_REPLY_ENABLED', None)
        h.handler(event, context)

    messages_table = tables.get(h.MESSAGES_TABLE)
    if messages_table is not None:
        run.messages_put = list(messages_table.put_item.call_args_list)
    run.standby_rows = list(table.standby_rows)
    to.set_table(None)
    return run


# ── the parametrised standby messages ───────────────────────────────────────────

LIST_REPLY = {
    'id': 'wamid.LIST', 'from': WA_ID, 'from_user_id': BSUID, 'timestamp': '1700000000',
    'type': 'interactive',
    'interactive': {'type': 'list_reply',
                    'list_reply': {'id': 'wd_menu_faq', 'title': 'FAQ'}},
}
CART_ORDER = {
    'id': 'wamid.ORDER', 'from': WA_ID, 'from_user_id': BSUID, 'timestamp': '1700000001',
    'type': 'order',
    'order': {'catalog_id': 'cat-1',
              'product_items': [{'product_retailer_id': 'SKU1', 'quantity': 1,
                                 'item_price': 500, 'currency': 'INR'}]},
}
SLASH_MENU = {
    'id': 'wamid.MENU', 'from': WA_ID, 'from_user_id': BSUID, 'timestamp': '1700000002',
    'type': 'text', 'text': {'body': '/menu'},
}
FREE_FORM = {
    'id': 'wamid.FREE', 'from': WA_ID, 'from_user_id': BSUID, 'timestamp': '1700000003',
    'type': 'text', 'text': {'body': 'what are your hours'},
}

DETERMINISTIC = [
    pytest.param(LIST_REPLY, id='interactive_list_reply'),
    pytest.param(CART_ORDER, id='order_cart'),
    pytest.param(SLASH_MENU, id='text_slash_menu'),
]
ALL_MESSAGES = DETERMINISTIC + [pytest.param(FREE_FORM, id='text_free_form')]


# ── the load-bearing assertions ─────────────────────────────────────────────────

class TestFlagFalseProducesZeroSends:
    """The fix. Asserted by COUNTING CALLS at both Graph boundaries, not by inspecting
    log lines — a log saying "suppressed" beside a real send would pass that check."""

    @pytest.mark.parametrize('message', ALL_MESSAGES)
    def test_zero_graph_sends(self, h, message):
        run = _drive(h, _standby_event([message]), flag='false')
        assert run.urlopen_calls == [], (
            f'{len(run.urlopen_calls)} Direct API call(s) escaped a suppressed standby '
            f'message')
        assert run.invoke_calls == [], (
            f'{len(run.invoke_calls)} outbound invoke(s) escaped a suppressed standby '
            f'message')

    def test_zero_sends_for_a_whole_batch(self, h):
        """All four in one webhook, which is how a real batch arrives."""
        run = _drive(h, _standby_event(
            [LIST_REPLY, CART_ORDER, SLASH_MENU, FREE_FORM]), flag='false')
        assert run.total_sends == 0

    @pytest.mark.parametrize('spelling', ['false', 'FALSE', 'False', '0', 'no', 'off'])
    def test_every_off_spelling_suppresses(self, h, spelling):
        """An operator setting the flag in a hurry must not get a silent no-op."""
        assert _drive(h, _standby_event([LIST_REPLY]), flag=spelling).total_sends == 0

    @pytest.mark.parametrize('message', ALL_MESSAGES)
    def test_suppression_STORES_rather_than_discards(self, h, message):
        """Suppressing a reply must not re-create the discard this also fixes. Today's
        code `continue`s on every non-deterministic standby message, so the free-form
        conversation the other responder is handling is never stored anywhere — and that
        is exactly the context a later handover would need."""
        run = _drive(h, _standby_event([message]), flag='false')
        assert len(run.standby_rows) == 1
        row = run.standby_rows[0]
        assert row['standbySourced'] is True
        assert row[to.TABLE_HASH_KEY] == f'{META_PHONE}#{BSUID}', \
            'standby context must be indexed by BSUID, per Meta guidance'

    def test_the_free_form_message_is_stored_too(self, h):
        """The half of the discard that today's `continue` loses entirely."""
        run = _drive(h, _standby_event([FREE_FORM]), flag='false')
        assert [r['whatsappMessageId'] for r in run.standby_rows] == ['wamid.FREE']


class TestFlagTrueIsTodaysBehaviour:
    """The shipped default. If these fail, this release changed production."""

    @pytest.mark.parametrize('message', DETERMINISTIC)
    def test_default_and_explicit_true_agree(self, h, message):
        """Flag unset (the shipped default) and STANDBY_REPLY_ENABLED=true must produce
        the SAME send list, and it must be non-empty — proving the default path still
        replies rather than trivially matching by both sending nothing."""
        default = _drive(h, _standby_event([message]), flag=None)
        explicit = _drive(h, _standby_event([message]), flag='true')
        assert default.total_sends > 0, 'the default path stopped replying'
        assert default.total_sends == explicit.total_sends
        assert len(default.urlopen_calls) == len(explicit.urlopen_calls)
        assert len(default.invoke_calls) == len(explicit.invoke_calls)

    @pytest.mark.parametrize('message', DETERMINISTIC)
    def test_the_default_path_replies(self, h, message):
        assert _drive(h, _standby_event([message]), flag=None).total_sends > 0

    def test_a_free_form_standby_message_still_gets_no_reply_by_default(self, h):
        """Unchanged from today: free-form is left to the other responder. The only
        difference is that it is now STORED as context instead of discarded."""
        run = _drive(h, _standby_event([FREE_FORM]), flag=None)
        assert run.total_sends == 0
        assert len(run.standby_rows) == 1

    def test_the_flag_is_read_per_call_not_cached(self, h):
        """A module-scope read would freeze for the life of the execution environment,
        so a configuration change would not take effect until every warm sandbox
        recycled. Driving the same loaded module with both values proves it is not."""
        off = _drive(h, _standby_event([LIST_REPLY]), flag='false')
        on = _drive(h, _standby_event([LIST_REPLY]), flag='true')
        assert off.total_sends == 0
        assert on.total_sends > 0

    def test_the_default_in_code_is_true(self, h):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('STANDBY_REPLY_ENABLED', None)
            assert h._standby_reply_enabled() is True


class TestTheMoneyPath:
    """R3. A rejected Review & Pay send after the reference is minted leaves a pending
    row behind, and a customer retry on top of that is the duplicate-paid-order shape
    .kiro/steering/whatsapp-payments-india-reference.md forbids."""

    def test_flag_false_mints_no_reference(self, h):
        run = _drive(h, _standby_event([CART_ORDER]), flag='false')
        assert run.total_sends == 0
        for payload in run.payloads:
            assert 'WD-PAY-' not in payload, 'a payment reference reached the wire'

    def test_flag_false_writes_no_payment_row(self, h):
        """The guard sits BEFORE the mint, so there is no reference_id to write and no
        MessagesTable row carrying one."""
        run = _drive(h, _standby_event([CART_ORDER]), flag='false')
        written = [str(call.kwargs.get('Item', {})) for call in run.messages_put]
        assert not any('WD-PAY-' in item for item in written)

    def test_flag_true_still_sends_the_order_details(self, h):
        run = _drive(h, _standby_event([CART_ORDER]), flag=None)
        assert any('isInteractivePayment' in p for p in run.payloads), \
            'the catalog checkout stopped producing a Review & Pay'

    def test_flag_true_still_mints_a_reference(self, h):
        run = _drive(h, _standby_event([CART_ORDER]), flag=None)
        assert any('WD-PAY-' in p for p in run.payloads)

    def test_the_guard_precedes_the_mint_in_source(self, h):
        """Structural, because the ordering is the whole fix and a later edit could move
        the mint above the guard without any test noticing."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        start = source.index('def _send_payment_request')
        body = source[start:start + 6000]
        guard = body.index("_may_send('payment_request')")
        mint = body.index('WD-PAY-{uuid.uuid4()')
        assert guard < mint, 'the may-send check must precede the reference_id mint'


class TestTheReadReceiptStaysUngated:
    """DELIBERATE. Meta's docs gate "Service messages" and never classify a
    `status: read` or a `typing_indicator`; both go to the same /{phone_id}/messages
    endpoint. It is unverified, it is ungated today, and it fires 462 times per 30 days,
    so guessing either way is worse than leaving one known unknown labelled.

    If someone "finishes the job" by gating it, this fails — which is the point."""

    def test_the_todo_naming_the_open_question_is_present(self):
        source = HANDLER_PATH.read_text(encoding='utf-8')
        assert 'TODO(conversation-routing)' in source
        start = source.index('TODO(conversation-routing)')
        todo = source[start:start + 1200]
        assert 'typing_indicator' in todo
        assert 'UNVERIFIED' in todo

    def test_the_direct_api_receipt_call_is_not_guarded(self):
        """Read structurally: the receipt send must not sit behind `_may_send`."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        index = source.index('_send_direct_api_read_receipt(whatsapp_message_id, show_typing=True)')
        preceding = source[max(0, index - 700):index]
        assert '_may_send(' not in preceding, \
            'the read receipt / typing indicator was gated; its ownership status is ' \
            'still unverified and gating it is a behaviour change nobody authorised'

    def test_the_reaction_beside_it_IS_guarded(self):
        """The asymmetry is deliberate, not an oversight: a reaction is unambiguously a
        Service message, a mark-as-read is not."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        assert "_auto_thumb_enabled() and _may_send('auto_reaction')" in source


class TestHandoverDrivesOwnership:
    """C2 full, through `handler()` rather than through the parser in isolation."""

    DOCUMENTED = {'previous_owner_role': 'ai_agent', 'new_owner_role': 'business'}
    LEGACY_STRING = {'metadata': '{"reason": "MARKETING_MESSAGE"}'}
    LEGACY_APP_ROLE = {'previous_owner_app_id': '1143680903703001',
                       'previous_owner_app_role': 'meta_business_agent'}
    SHAPES = [pytest.param(DOCUMENTED, id='documented'),
              pytest.param(LEGACY_STRING, id='legacy_metadata_string'),
              pytest.param(LEGACY_APP_ROLE, id='legacy_app_role')]

    @pytest.mark.parametrize('block', SHAPES)
    def test_control_passed_sets_ownership(self, h, block):
        table = FakeOwnershipTable()
        _drive(h, _handover_event('control_passed', dict(block)), ownership=table)
        to.set_table(table)
        try:
            state = to.get_state(META_PHONE, bsuid=BSUID)
            assert state['tracked'] is True
            assert state['owned'] is True
            assert state['lastSignal'] == to.SIGNAL_HANDOVER_GAINED
        finally:
            to.set_table(None)

    @pytest.mark.parametrize('block', SHAPES)
    def test_control_taken_clears_ownership(self, h, block):
        table = FakeOwnershipTable()
        to.set_table(table)
        to.record_signal(META_PHONE, bsuid=BSUID,
                         signal=to.SIGNAL_MESSAGE_RECEIVED)
        to.set_table(None)
        _drive(h, _handover_event('control_taken', dict(block)), ownership=table)
        to.set_table(table)
        try:
            state = to.get_state(META_PHONE, bsuid=BSUID)
            assert state['owned'] is False
            assert state['lastSignal'] == to.SIGNAL_HANDOVER_LOST
        finally:
            to.set_table(None)

    def test_a_handover_sends_nothing(self, h):
        """It is a notification. It was audit-only before and must stay send-free."""
        run = _drive(h, _handover_event('control_passed', dict(self.DOCUMENTED)))
        assert run.total_sends == 0

    def test_conversation_context_is_captured_when_present(self, h):
        block = dict(self.DOCUMENTED)
        block['conversation_context'] = {'summary': 'Asked about delivery.'}
        table = FakeOwnershipTable()
        _drive(h, _handover_event('control_passed', block), ownership=table)
        to.set_table(table)
        try:
            assert to.get_state(META_PHONE, bsuid=BSUID)['conversationContext'] == \
                {'summary': 'Asked about delivery.'}
        finally:
            to.set_table(None)

    def test_a_malformed_handover_does_not_raise(self, h):
        """The arm runs beside real customer messages; a bad payload must not poison the
        event, because an async worker that raises retries and re-crashes forever."""
        run = _drive(h, _handover_event('control_passed', 'not a dict'))
        assert run.total_sends == 0


class TestStandbyObservedClearsOwnership:
    def test_a_standby_copy_means_somebody_else_owns_it(self, h):
        table = FakeOwnershipTable()
        to.set_table(table)
        to.record_signal(META_PHONE, bsuid=BSUID, signal=to.SIGNAL_MESSAGE_RECEIVED)
        to.set_table(None)
        _drive(h, _standby_event([FREE_FORM]), flag='false', ownership=table)
        to.set_table(table)
        try:
            state = to.get_state(META_PHONE, bsuid=BSUID)
            assert state['owned'] is False
            assert state['lastSignal'] == to.SIGNAL_STANDBY_OBSERVED
        finally:
            to.set_table(None)


class TestNormalMessagesAreNeverGated:
    """Receiving a message on the `messages` field is itself the documented proof of
    ownership — "you do not have to reply to claim the thread" — so normal traffic must
    never be gated, even with the flag off.

    Two mechanisms produce that, and it is worth being precise about which is load-bearing
    rather than claiming both are. `_send_context` is a module global (following the
    existing `_current_direct_api_phone` precedent) reset unconditionally at the top of
    `_process_message`, so a `standby: True` cannot survive into the next message. **But
    even if it did**, `record_signal(message_received)` runs before any send site and sets
    `owned=True`, so `_may_send` would allow the send anyway. The reset is therefore
    defence in depth, not the thing standing between a normal message and suppression —
    and a behavioural test cannot distinguish the two. The reset is asserted structurally
    below; this test asserts the property that actually matters.
    """

    def test_a_normal_message_is_answered_even_with_the_flag_off(self, h):
        normal = {
            'source': 'meta-direct', 'version': 1, 'wabaId': WABA,
            'metaPhoneNumberIds': [META_PHONE], 'requestId': 'req-normal',
            'entry': {'id': WABA, 'changes': [{
                'field': 'messages',
                'value': {'metadata': {'display_phone_number': '919330994400',
                                       'phone_number_id': META_PHONE},
                          'contacts': [{'wa_id': WA_ID, 'user_id': BSUID}],
                          'messages': [LIST_REPLY]},
            }]},
        }
        # Start from a table that says NOT OWNED and a poisoned send context — the worst
        # case a leak could produce — and do not let the harness clear either.
        table = FakeOwnershipTable()
        to.set_table(table)
        to.record_signal(META_PHONE, bsuid=BSUID, signal=to.SIGNAL_STANDBY_OBSERVED)
        assert to.may_send(META_PHONE, bsuid=BSUID) is False, 'precondition'
        to.set_table(None)
        h._send_context = {'standby': True, 'phone_number_id': META_PHONE,
                           'bsuid': BSUID, 'wa_id': WA_ID}
        run = _drive(h, normal, flag='false', ownership=table, reset_context=False)
        # Assert on the GATED sends specifically. The read receipt is deliberately
        # ungated and goes out over the same boundary regardless, so a total-count
        # assertion could not tell a correctly suppressed send from an escaped one.
        assert run.gated_sends > 0, (
            'a message that arrived on the `messages` field was suppressed — receiving '
            'one is the documented proof that we own the thread, so this must reply '
            'whatever the flag says')

    def test_the_received_signal_runs_before_any_send_site(self):
        """Structural, and this ordering is why the test above holds: the
        `message_received` signal must be recorded BEFORE the first guarded send, or a
        normal message could be refused on stale state."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        start = source.index('def _process_message')
        body = source[start:start + 40000]
        signal = body.index('thread_ownership.SIGNAL_MESSAGE_RECEIVED')
        first_guard = body.index("_may_send('automation_auto_reply')")
        assert signal < first_guard

    def test_the_context_is_reset_inside_process_message(self):
        """Structural: the reset must be unconditional and must not OR in the previous
        value. Defence in depth rather than the load-bearing mechanism, but a leaked
        `standby: True` would still be wrong, and the assertion is free."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        start = source.index('def _process_message')
        body = source[start:start + 4000]
        assert 'global _send_context' in body
        assert "'standby': bool(standby_sourced)," in body


class TestTheOwnershipGuardLayer:
    """The `_may_send` guards are a SECOND layer, and today they are unreachable from the
    standby webhook path. Said plainly because it would be easy to imply otherwise.

    With `STANDBY_REPLY_ENABLED=false` the standby arm `continue`s before
    `_process_message` is ever called, so the zero sends proved above come from that
    `continue`, not from the guards. Verified by mutation: forcing `_may_send` to return
    True unconditionally does not make any zero-send test fail.

    That layering is deliberate. The flag must be decisive, because `thread_ownership`
    fails OPEN on unknown state — if the flag merely delegated to the guards, switching it
    off would still send a standby reply for every thread whose ownership we had not yet
    derived, which is most of them.

    So the guards exist for the cases the `continue` does not cover: a future, narrower
    policy than "reply or do not reply", and `_send_payment_request`'s other callers. That
    makes them easy to leave untested, which is what this class prevents — they are
    exercised directly, through `_process_message` with `standby_sourced=True`.
    """

    def _run_process_message(self, h, message, *, flag, standby_sourced, owned):
        run = Run()
        table = FakeOwnershipTable()
        to.set_table(table)
        to.record_signal(META_PHONE, bsuid=BSUID,
                         signal=(to.SIGNAL_MESSAGE_RECEIVED if owned
                                 else to.SIGNAL_STANDBY_OBSERVED))

        tables = {}

        def _table(name):
            if name not in tables:
                mock = MagicMock()
                if name == h.SYSTEM_CONFIG_TABLE:
                    mock.get_item.side_effect = RuntimeError('no config row')
                else:
                    mock.get_item.return_value = {'Item': {}}
                    mock.query.return_value = {'Items': []}
                tables[name] = mock
            return tables[name]

        def _urlopen(req, *a, **kw):
            run.urlopen_calls.append(req)
            resp = MagicMock()
            resp.read.return_value = json.dumps(
                {'messages': [{'id': 'wamid.SENT'}]}).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *args: False
            return resp

        h._routing_cache['v'] = None
        h._routing_cache['t'] = 0.0
        with patch.dict(os.environ, {'STANDBY_REPLY_ENABLED': flag,
                                     'AWS_REGION': 'us-east-1'}, clear=False), \
                patch('urllib.request.urlopen', side_effect=_urlopen), \
                patch.object(h.lambda_client, 'invoke',
                             side_effect=lambda **kw: run.invoke_calls.append(kw)), \
                patch('lambda_utils.webhook_dedup.claim_event', return_value=True), \
                patch.object(h.dynamodb, 'Table', side_effect=_table), \
                patch.object(h, '_message_exists', return_value=False), \
                patch.object(h, '_get_or_create_contact',
                             return_value={'contactId': 'c-1', 'welcomeSent': True}), \
                patch.object(h, '_update_contact_timestamp'), \
                patch.object(h, '_load_direct_api_token', return_value='token-placeholder'), \
                patch.object(h, 'put_message'), \
                patch.object(to, 'record_signal', return_value={'tracked': True}):
            # `record_signal` is stubbed because the `message_received` signal would
            # claim the thread before any guard runs — correct for real traffic, but it
            # would mask the guard under test. The seeded row above is what `may_send`
            # reads, so the guard is measured rather than the signal.
            h._process_message(
                message,
                {'display_phone_number': '919330994400',
                 'phone_number_id': META_PHONE},
                'req-guard', '919330994400', AWS_PHONE, [WABA],
                standby_sourced=standby_sourced,
            )
        to.set_table(None)
        return run

    @pytest.mark.parametrize('message', [
        pytest.param(LIST_REPLY, id='interactive_list_reply'),
        pytest.param(SLASH_MENU, id='text_slash_menu'),
    ])
    def test_the_guards_suppress_a_standby_message_we_do_not_own(self, h, message):
        run = self._run_process_message(h, message, flag='false',
                                        standby_sourced=True, owned=False)
        assert run.gated_sends == 0

    @pytest.mark.parametrize('message', [
        pytest.param(LIST_REPLY, id='interactive_list_reply'),
        pytest.param(SLASH_MENU, id='text_slash_menu'),
    ])
    def test_the_guards_allow_a_standby_message_we_DO_own(self, h, message):
        """Ownership, not provenance, is the question. A standby copy on a thread we own
        is still ours to answer."""
        run = self._run_process_message(h, message, flag='false',
                                        standby_sourced=True, owned=True)
        assert run.gated_sends > 0

    @pytest.mark.parametrize('message', [
        pytest.param(LIST_REPLY, id='interactive_list_reply'),
        pytest.param(SLASH_MENU, id='text_slash_menu'),
    ])
    def test_the_guards_are_inert_with_the_flag_true(self, h, message):
        """The shipped default. Not owned, standby-sourced, and it still replies —
        because with the flag true `_may_send` short-circuits before reading any state."""
        run = self._run_process_message(h, message, flag='true',
                                        standby_sourced=True, owned=False)
        assert run.gated_sends > 0

    def test_a_non_standby_message_is_never_checked(self, h):
        run = self._run_process_message(h, LIST_REPLY, flag='false',
                                        standby_sourced=False, owned=False)
        assert run.gated_sends > 0

    def test_may_send_short_circuits_before_reading_state(self, h):
        """Directly, because this is the line the byte-identical claim rests on: with the
        flag true it must not even consult the store."""
        h._send_context = {'standby': True, 'phone_number_id': META_PHONE,
                           'bsuid': BSUID, 'wa_id': WA_ID}
        with patch.dict(os.environ, {'STANDBY_REPLY_ENABLED': 'true'}, clear=False), \
                patch.object(to, 'may_send',
                             side_effect=AssertionError('state was consulted')):
            assert h._may_send('probe') is True

    def test_may_send_consults_state_only_when_both_conditions_hold(self, h):
        h._send_context = {'standby': True, 'phone_number_id': META_PHONE,
                           'bsuid': BSUID, 'wa_id': WA_ID}
        with patch.dict(os.environ, {'STANDBY_REPLY_ENABLED': 'false'}, clear=False), \
                patch.object(to, 'may_send', return_value=False) as spy:
            assert h._may_send('probe') is False
            assert spy.called


class TestGuardCoverage:
    """Every reachable send must be guarded, or the fix has a hole. Counted so adding a
    send without a guard is visible."""

    def test_the_expected_guards_are_all_present(self):
        source = HANDLER_PATH.read_text(encoding='utf-8')
        for purpose in ('automation_auto_reply', 'button_reply_menu', 'list_reply_route',
                        'address_submission', 'postpay_submission', 'cart_order',
                        'auto_reaction', 'auto_reaction_aws', 'request_welcome_menu',
                        'button_text_menu', 'text_keyword_routing',
                        'brand_new_contact_welcome', 'payment_request'):
            assert f"_may_send('{purpose}')" in source, f'missing guard: {purpose}'

    def test_the_welcome_write_still_runs_when_the_send_is_suppressed(self):
        """Deliberate asymmetry with a named cost: the contact is still marked welcomed,
        so a suppressed welcome is never re-sent. The alternative is retrying it on every
        later message from that contact, which under routing is a rejected Graph send
        every time, forever."""
        source = HANDLER_PATH.read_text(encoding='utf-8')
        start = source.index("_may_send('brand_new_contact_welcome')")
        block = source[start:start + 900]
        assert 'welcomeSent = :t' in block
        # The write must NOT be inside the guarded branch.
        guarded_line_end = block.index('\n', block.index('_send_wd_main_menu'))
        assert 'welcomeSent = :t' in block[guarded_line_end:]
