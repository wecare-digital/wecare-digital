"""The WA_LIVE_SMOKE_TEST lockdown: a live test can only reach WA_QA_RECIPIENT.

Two layers are under test and they are not redundant:

  * `live_smoke.check_recipient` - the rule itself.
  * `outbound-whatsapp`'s wire guard in `_send_direct_api` - the guarantee. The
    handler-level check is an early exit for a clean 403; a branch added later
    that forgets it still cannot reach a customer, and that is what the wire
    tests pin.

The direction matters and is asserted explicitly: with the flag off, behaviour is
completely unchanged (`test_flag_off_*`). Enabling the flag can only ever narrow
who is reachable, never widen it.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / 'amplify' / 'functions' / 'shared'
OUTBOUND = REPO / 'amplify' / 'functions' / 'messaging' / 'outbound-whatsapp'

for _p in (str(SHARED), str(OUTBOUND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lambda_utils import live_smoke  # noqa: E402

QA = '+91 93309 94400'
QA_DIGITS = '919330994400'
CUSTOMER = '+919876543210'


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(live_smoke.FLAG_ENV, raising=False)
    monkeypatch.delenv(live_smoke.RECIPIENT_ENV, raising=False)
    yield


def _smoke_on(monkeypatch, recipient=QA):
    monkeypatch.setenv(live_smoke.FLAG_ENV, 'true')
    if recipient is not None:
        monkeypatch.setenv(live_smoke.RECIPIENT_ENV, recipient)


# ── the rule ────────────────────────────────────────────────────────────────

class TestFlagOffChangesNothing:
    """Production state. Every recipient is allowed, exactly as before."""

    def test_flag_off_allows_any_recipient(self):
        for who in (CUSTOMER, QA, '', None, 'not-a-phone'):
            allowed, reason = live_smoke.check_recipient(who)
            assert allowed is True, who
            assert reason == 'not_smoke_mode'

    def test_flag_off_even_with_qa_recipient_set(self, monkeypatch):
        monkeypatch.setenv(live_smoke.RECIPIENT_ENV, QA)
        assert live_smoke.check_recipient(CUSTOMER) == (True, 'not_smoke_mode')

    @pytest.mark.parametrize('value', ['1', 'yes', 'TRUE ', 'True\n', 'on', 'false', ''])
    def test_only_exact_true_enables_the_mode(self, monkeypatch, value):
        """Strict on purpose: this mode halts customer messaging, so a stray '1'
        in an env var must not trip it. 'TRUE ' and 'True\\n' strip to 'true'."""
        monkeypatch.setenv(live_smoke.FLAG_ENV, value)
        expected = value.strip().lower() == 'true'
        assert live_smoke.is_smoke_mode() is expected


class TestSmokeModeNarrows:
    def test_qa_recipient_allowed(self, monkeypatch):
        _smoke_on(monkeypatch)
        assert live_smoke.check_recipient(QA) == (True, 'qa_recipient_match')

    @pytest.mark.parametrize('fmt', [QA_DIGITS, '+' + QA_DIGITS, '+91 93309 94400',
                                     '+91-93309-94400', '  919330994400  '])
    def test_formatting_does_not_defeat_the_match(self, monkeypatch, fmt):
        _smoke_on(monkeypatch)
        allowed, _ = live_smoke.check_recipient(fmt)
        assert allowed is True

    def test_customer_refused(self, monkeypatch):
        _smoke_on(monkeypatch)
        assert live_smoke.check_recipient(CUSTOMER) == (False, 'smoke_mode_recipient_not_qa')

    def test_no_qa_recipient_configured_blocks_everything(self, monkeypatch):
        """An operator who enables the mode and forgets the recipient gets zero
        sends - immediately visible - not an unrestricted window."""
        _smoke_on(monkeypatch, recipient=None)
        for who in (CUSTOMER, QA, '', None):
            allowed, reason = live_smoke.check_recipient(who)
            assert allowed is False, who
            assert reason == 'smoke_mode_without_qa_recipient'

    def test_blank_qa_recipient_blocks_everything(self, monkeypatch):
        _smoke_on(monkeypatch, recipient='   ')
        assert live_smoke.check_recipient(QA)[0] is False

    def test_empty_recipient_is_not_a_match(self, monkeypatch):
        """`_normalize(None) == _normalize('')` must not make a missing recipient
        equal to a configured one."""
        _smoke_on(monkeypatch)
        assert live_smoke.check_recipient(None)[0] is False
        assert live_smoke.check_recipient('')[0] is False

    def test_a_number_that_merely_contains_the_qa_digits_is_refused(self, monkeypatch):
        _smoke_on(monkeypatch)
        assert live_smoke.check_recipient('91933099440099')[0] is False
        assert live_smoke.check_recipient('9193309944')[0] is False


class TestDescribeLeaksNoNumber:
    def test_describe_omits_the_number(self, monkeypatch):
        _smoke_on(monkeypatch)
        d = live_smoke.describe()
        assert d == {'smokeMode': True, 'qaRecipientConfigured': True,
                     'qaRecipientSuffix': QA_DIGITS[-4:]}
        assert QA_DIGITS not in json.dumps(d)

    def test_describe_when_unconfigured(self):
        assert live_smoke.describe() == {
            'smokeMode': False, 'qaRecipientConfigured': False, 'qaRecipientSuffix': ''}


# ── the guarantee: the wire guard inside outbound-whatsapp ───────────────────

def _load_outbound():
    """Load outbound-whatsapp under a UNIQUE module name.

    Importing it as plain `handler` collides in sys.modules with every other
    function handler the suite loads, so whichever test file ran first wins. This
    file passed in isolation and then tested inbound-whatsapp in the full run -
    exactly the failure mode tests/test_whatsapp_sender_no_bypass.py documents.
    Same spec_from_file_location pattern.
    """
    spec = importlib.util.spec_from_file_location(
        'outbound_whatsapp_live_smoke_handler', OUTBOUND / 'handler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def outbound():
    """The handler module, with its AWS clients replaced so nothing leaves the machine.

    WHY THE STUBS ARE HERE AND NOT IN EACH TEST. The module builds `dynamodb`, `s3`,
    `cloudwatch` and `secrets_client` at import (handler.py:58-60, 103). The tests below
    that call `outbound.handler(...)` walk the real send pipeline — rate limit, contact
    lookup, latest-inbound-wamid — and each of those reads DynamoDB. Measured on
    f87ea643: six live connections to AWS us-east-1 from this file alone, with the
    ambient (root) credential, every one of them landing inside a swallowed-exception
    path. So the assertions never depended on the calls succeeding; the calls were pure
    side effect, and the tests pass for the same reasons with them stubbed.

    MagicMock rather than a modelled fake on purpose: these tests assert on the lockdown
    decision, not on stored rows, so a fake with real semantics would be more machinery
    pinning behaviour nothing here is testing.
    """
    module = _load_outbound()
    module.dynamodb = MagicMock()
    module.s3 = MagicMock()
    module.cloudwatch = MagicMock()
    module.secrets_client = MagicMock()
    return module


class TestWireGuard:
    """`_send_direct_api` refuses before the Graph call, not after."""

    def _urlopen_must_not_run(self, *a, **k):
        raise AssertionError('a Graph request was made while smoke mode blocked it')

    def test_blocked_recipient_never_reaches_graph(self, outbound, monkeypatch):
        _smoke_on(monkeypatch)
        with patch.object(outbound.urllib.request, 'urlopen', self._urlopen_must_not_run):
            with pytest.raises(outbound.SmokeTestRecipientBlocked) as exc:
                outbound._send_direct_api('phone-1', json.dumps({'to': CUSTOMER, 'type': 'text'}))
        assert 'not_qa' in str(exc.value)

    def test_payload_without_to_is_refused(self, outbound, monkeypatch):
        """"We cannot tell who this reaches" is not a reason to let it through."""
        _smoke_on(monkeypatch)
        with patch.object(outbound.urllib.request, 'urlopen', self._urlopen_must_not_run):
            with pytest.raises(outbound.SmokeTestRecipientBlocked):
                outbound._send_direct_api('phone-1', json.dumps({'type': 'text'}))

    def test_unparsable_payload_is_refused(self, outbound, monkeypatch):
        _smoke_on(monkeypatch)
        with patch.object(outbound.urllib.request, 'urlopen', self._urlopen_must_not_run):
            with pytest.raises(outbound.SmokeTestRecipientBlocked):
                outbound._send_direct_api('phone-1', 'not json at all')

    def test_smoke_without_qa_recipient_refuses_even_the_qa_number(self, outbound, monkeypatch):
        _smoke_on(monkeypatch, recipient=None)
        with patch.object(outbound.urllib.request, 'urlopen', self._urlopen_must_not_run):
            with pytest.raises(outbound.SmokeTestRecipientBlocked) as exc:
                outbound._send_direct_api('phone-1', json.dumps({'to': QA}))
        assert 'without_qa_recipient' in str(exc.value)

    def test_flag_off_does_not_touch_the_send_path(self, outbound):
        """The regression that matters most: with the flag off the guard must be
        entirely inert, including not parsing or rewriting the payload."""
        outbound._direct_api_cache['token'] = 't'
        outbound._direct_api_cache['app_secret'] = ''
        seen = {}

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({'messages': [{'id': 'wamid.OK'}],
                                   'contacts': [{'wa_id': '91'}]}).encode()

        def _fake_urlopen(req, timeout=None):
            seen['body'] = req.data
            return _Resp()

        with patch.object(outbound, '_resolve_meta_phone_id', return_value='meta-1'), \
             patch.object(outbound, '_auto_thumb_enabled', return_value=False), \
             patch.object(outbound.urllib.request, 'urlopen', _fake_urlopen):
            out = outbound._send_direct_api('phone-1', json.dumps({'to': CUSTOMER}))

        assert out == {'messageId': 'wamid.OK', 'waId': '91'}
        assert json.loads(seen['body'].decode()) == {'to': CUSTOMER}

    def test_qa_recipient_still_sends_in_smoke_mode(self, outbound, monkeypatch):
        """The mode has to be usable, or the handset QA it exists for cannot run."""
        _smoke_on(monkeypatch)
        outbound._direct_api_cache['token'] = 't'
        outbound._direct_api_cache['app_secret'] = ''

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({'messages': [{'id': 'wamid.QA'}], 'contacts': []}).encode()

        with patch.object(outbound, '_resolve_meta_phone_id', return_value='meta-1'), \
             patch.object(outbound, '_auto_thumb_enabled', return_value=False), \
             patch.object(outbound.urllib.request, 'urlopen', lambda *a, **k: _Resp()):
            out = outbound._send_direct_api('phone-1', json.dumps({'to': QA_DIGITS}))
        assert out['messageId'] == 'wamid.QA'

    def test_blocked_log_line_masks_the_number(self, outbound, monkeypatch, caplog):
        _smoke_on(monkeypatch)
        with caplog.at_level('ERROR'):
            with pytest.raises(outbound.SmokeTestRecipientBlocked):
                outbound._assert_smoke_recipient_allowed(CUSTOMER, 'unit')
        text = caplog.text
        assert 'smoke_mode_send_blocked' in text
        assert CUSTOMER not in text
        assert CUSTOMER.lstrip('+') not in text


# ── the edge: the handler returns a clean 403, not a 500 ─────────────────────

class _Ctx:
    """A real context stub. A MagicMock is not usable here: the handler logs
    `aws_request_id` through `json.dumps`, which raises on a mock attribute."""
    aws_request_id = 'req-live-smoke-test'
    function_name = 'wecare-outbound-whatsapp'
    memory_limit_in_mb = 512

    def get_remaining_time_in_millis(self):
        return 30000


class TestHandlerReturns403:
    """A blocked smoke test has to be diagnosable. If the only thing stopping the
    send were the wire guard, an operator would see a generic 500 and go looking
    for a Graph outage."""

    def _event(self, recipient=CUSTOMER):
        return {
            'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
            'headers': {'origin': 'https://wecare.digital'},
            'body': json.dumps({'recipientPhone': recipient, 'content': 'ping',
                                'phoneNumberId': 'phone-1'}),
        }

    def _invoke(self, outbound, monkeypatch, recipient=CUSTOMER):
        monkeypatch.setattr(outbound, 'require_auth', lambda *a, **k: None, raising=False)
        monkeypatch.setattr(outbound, '_get_or_create_contact_by_phone',
                            lambda phone: {'contactId': 'c-1', 'phone': phone})
        # If the lockdown lets the request through, fail loudly rather than
        # attempting a real send.
        monkeypatch.setattr(outbound, '_send_direct_api',
                            lambda *a, **k: pytest.fail('reached the send path'))
        return outbound.handler(self._event(recipient), _Ctx())

    def test_customer_recipient_gets_403(self, outbound, monkeypatch):
        _smoke_on(monkeypatch)
        resp = self._invoke(outbound, monkeypatch)
        assert resp['statusCode'] == 403
        body = json.dumps(resp['body'])
        assert 'smoke' in body.lower()
        assert CUSTOMER.lstrip('+') not in body

    def test_403_arrives_before_the_service_window_check(self, outbound, monkeypatch):
        """Ordering claim in the handler comment: the lockdown runs before the
        window check, the typing indicator and every send branch. If the window
        check ran first this would be a 403 about the 24h window instead."""
        _smoke_on(monkeypatch)
        monkeypatch.setattr(outbound, '_is_within_service_window',
                            lambda c: pytest.fail('window check ran before the lockdown'))
        monkeypatch.setattr(outbound, '_send_typing_indicator',
                            lambda *a, **k: pytest.fail('typing indicator ran before the lockdown'))
        resp = self._invoke(outbound, monkeypatch)
        assert resp['statusCode'] == 403

    def test_block_action_on_a_customer_is_refused(self, outbound, monkeypatch):
        """`blockUsers` is an arbitrary list, not the resolved recipient, so it
        needs its own check."""
        _smoke_on(monkeypatch)
        monkeypatch.setattr(outbound, 'require_auth', lambda *a, **k: None, raising=False)
        monkeypatch.setattr(outbound, '_get_or_create_contact_by_phone',
                            lambda phone: {'contactId': 'c-1', 'phone': phone})
        monkeypatch.setattr(outbound, '_block_users_api',
                            lambda *a, **k: pytest.fail('block_users was called'))
        event = {
            'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
            'headers': {}, 'body': json.dumps({
                'recipientPhone': QA, 'phoneNumberId': 'phone-1',
                'blockAction': 'block', 'blockUsers': [CUSTOMER]}),
        }
        resp = outbound.handler(event, _Ctx())
        assert resp['statusCode'] == 403

    def test_flag_off_reaches_the_send_path_unchanged(self, outbound, monkeypatch):
        """The inertness assertion at the handler level: with the flag off the
        request proceeds past the lockdown to the normal pipeline."""
        monkeypatch.setattr(outbound, 'require_auth', lambda *a, **k: None, raising=False)
        monkeypatch.setattr(outbound, '_get_or_create_contact_by_phone',
                            lambda phone: {'contactId': 'c-1', 'phone': phone})
        reached = {}
        monkeypatch.setattr(outbound, '_is_within_service_window',
                            lambda c: reached.setdefault('window', True) and True)
        resp = outbound.handler(self._event(), _Ctx())
        assert reached.get('window') is True
        assert resp['statusCode'] != 403 or 'smoke' not in json.dumps(resp['body']).lower()
