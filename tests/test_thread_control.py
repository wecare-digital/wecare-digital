"""Meta Business Agent thread control: the request we would send is the documented one.

A live round trip is impossible here and that is a measured fact, not an excuse: it needs
a routing configuration on the WABA (owner answer **O1**, unanswered) and, for `take`, an
escalation-partner designation (**O3**, unanswered). What *can* be proven is the thing
that actually failed before -- `_thread_control` sent a correct-looking request to the
WRONG HOST, on a LEGACY PATH, with the ACCESS TOKEN IN THE URL QUERY STRING (twice), under
a hardcoded `X-API-Version: "1.0.0"` that was not even this module's `API_VERSION`. Five
faults, none of which a response assertion would have caught and all of which are visible
in the request.

So every test here counts and inspects at the `urllib.request.urlopen` boundary, the
discipline `tests/test_standby_produces_no_sends.py` established.

TWO THINGS THIS FILE DELIBERATELY DOES NOT DO
---------------------------------------------
**It never asserts the absence of a query string.** `_meta_request` appends
`appsecret_proof=` and MUST keep doing so: that value is an HMAC-SHA256 of the token under
the app secret, not the token, and `api.facebook.com` requires it. A test written as "the
URL has no `?`" fails on correct code, and a reviewer watching it fail would reasonably but
wrongly conclude the token removal had regressed. `test_no_token_in_the_url` therefore
names `access_token=` and `oauth_token=` specifically.

**It contains no Graph version literal.** Assertions read `handler.GRAPH` and
`handler.API_VERSION`. A test carrying `v25.0` or `v26.0` would encode the one thing
`lambda_utils.meta_version` exists to keep in a single place, and would go red the next
time the fleet default moves -- which `tests/test_meta_version_sources.py` already guards
fleet-wide.
"""
import importlib.util
import inspect
import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_AGENT_DIR = _ROOT / 'amplify/functions/messaging/meta-business-agent'
_INBOUND_DIR = _ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler'
AGENT_HANDLER_PATH = _AGENT_DIR / 'handler.py'
INBOUND_HANDLER_PATH = _INBOUND_DIR / 'handler.py'

for _p in (str(_ROOT / 'amplify/functions/shared'), str(_AGENT_DIR),
           str(_INBOUND_DIR), str(_INBOUND_DIR / 'modules')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lambda_utils import thread_ownership as to  # noqa: E402

PHONE_ID = '1016149501586345'          # WABA1 phone-number id
WABA = '2094615664435155'
BSUID = 'BSUID-THREAD-CONTROL-1'
E164 = '+918100640044'                 # the owner-nominated QA recipient; never sent to
WA_ID = '918100640044'

# Not a credential. A stand-in so `_creds()` never reaches Secrets Manager, and so
# `_appsecret_proof` has something to HMAC -- which is what keeps `appsecret_proof=`
# present in the captured URL, the condition `test_no_token_in_the_url` is written around.
FAKE_TOKEN = 'token-stand-in'
FAKE_APP_SECRET = 'app-secret-stand-in'


@pytest.fixture(scope='module')
def handler():
    """The meta-business-agent handler, loaded by path under a private module name."""
    spec = importlib.util.spec_from_file_location(
        'meta_business_agent_thread_control', str(AGENT_HANDLER_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules['meta_business_agent_thread_control'] = module
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            spec.loader.exec_module(module)
    return module


class Capture:
    """Everything one `_thread_control` call put on the wire."""

    def __init__(self):
        self.requests = []

    @property
    def count(self):
        return len(self.requests)

    @property
    def url(self):
        assert self.requests, 'no request was issued'
        return self.requests[-1].full_url

    @property
    def headers(self):
        """Header names lowercased -- urllib capitalises what `add_header` is given."""
        return {k.lower(): v for k, v in self.requests[-1].header_items()}

    @property
    def sent(self):
        return json.loads((self.requests[-1].data or b'{}').decode('utf-8'))


def _call(handler, fn, body, status=200, payload=None):
    """Drive one handler function with the Graph boundary captured, never reached."""
    cap = Capture()

    def _urlopen(req, *a, **kw):
        cap.requests.append(req)
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload or {'success': True}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *args: False
        resp.status = status
        return resp

    with patch.object(handler, '_creds', return_value=(FAKE_TOKEN, FAKE_APP_SECRET)), \
            patch('urllib.request.urlopen', side_effect=_urlopen):
        result = fn(body)
    return result, cap


def _body(result):
    return json.loads(result['body'])


# ── 1. the host and the path ────────────────────────────────────────────────────

def test_release_targets_the_graph_host_and_documented_path(handler):
    """Fault (a) and (b): GRAPH_HOST (api.facebook.com) on a legacy path.

    Asserting `startswith(handler.GRAPH)` proves BOTH halves at once -- the Graph host
    and the single sourced version, without naming either.
    """
    result, cap = _call(handler, handler._thread_control,
                        {'entityId': PHONE_ID, 'bsuid': BSUID})
    assert result['statusCode'] == 200
    assert cap.count == 1
    assert cap.url.startswith(handler.GRAPH), cap.url
    assert handler.GRAPH != handler.GRAPH_HOST, \
        'the Graph base and the agent-API host must not be the same value'
    path = cap.url.split('?', 1)[0]
    assert path.endswith(f'/{PHONE_ID}/thread_control'), path


# ── 2. the token leaves the URL ─────────────────────────────────────────────────

def test_no_token_in_the_url(handler):
    """Fault (d): the token was in the query string TWICE.

    Named substrings, NOT "the URL has no query string": `appsecret_proof=` is appended
    by `_meta_request` and must stay, so the broader assertion would fail on correct code.
    """
    _, cap = _call(handler, handler._thread_control,
                   {'entityId': PHONE_ID, 'bsuid': BSUID})
    assert 'access_token=' not in cap.url
    assert 'oauth_token=' not in cap.url
    assert FAKE_TOKEN not in cap.url, 'the token value itself must not reach the URL'
    # The derived HMAC is NOT the credential, and removing it breaks the call.
    assert 'appsecret_proof=' in cap.url
    assert cap.headers.get('authorization') == f'Bearer {FAKE_TOKEN}'


# ── 3. the legacy path cannot come back ─────────────────────────────────────────

def test_the_legacy_path_is_gone(handler):
    """Pin the absence of the known-bad spelling, the technique
    tests/test_payment_vocabulary_at_decision_points.py established."""
    source = AGENT_HANDLER_PATH.read_text(encoding='utf-8')
    assert '/business/whatsapp/phone_numbers/' not in source


# ── 4, 5, 5a. the recipient shape, read through its one helper ──────────────────

def test_bsuid_becomes_the_recipient_shape(handler):
    """Read THROUGH the helper, never against a literal nesting.

    The shape is UNVERIFIED (owner answer O1) and the helper's docstring says so, so a
    correction must cost one function body and zero test edits.
    """
    _, cap = _call(handler, handler._thread_control,
                   {'entityId': PHONE_ID, 'bsuid': BSUID})
    sent = cap.sent
    assert {'recipient': sent['recipient']} == handler._thread_control_recipient(BSUID, '')
    assert 'to' not in sent, 'no bare top-level `to` alongside the recipient fragment'
    assert sent['messaging_product'] == 'whatsapp'
    assert sent['action'] == 'release'


def test_phone_fallback_uses_the_same_helper(handler):
    """BSUID absent -> the phone fallback, through the same single correction point."""
    _, cap = _call(handler, handler._thread_control,
                   {'entityId': PHONE_ID, 'to': E164})
    sent = cap.sent
    assert {'recipient': sent['recipient']} == handler._thread_control_recipient('', E164)
    assert 'to' not in sent


def test_the_recipient_shape_lives_in_one_place(handler):
    """`_thread_control` must not re-inline the shape past the helper."""
    source = inspect.getsource(handler._thread_control)
    assert 'user_id' not in source


# ── 6. pass requires a target role ─────────────────────────────────────────────

def test_pass_requires_and_sends_target_role(handler):
    """A pass naming no target is malformed; refusing locally beats a Graph 400."""
    result, cap = _call(handler, handler._thread_control,
                        {'entityId': PHONE_ID, 'bsuid': BSUID, 'action': 'pass'})
    assert result['statusCode'] == 400
    assert cap.count == 0
    assert 'targetRole' in _body(result)['error']

    result, cap = _call(handler, handler._thread_control,
                        {'entityId': PHONE_ID, 'bsuid': BSUID, 'action': 'pass',
                         'targetRole': 'ESCALATION_PARTNER'})
    assert result['statusCode'] == 200
    assert cap.count == 1
    assert cap.sent['control_pass'] == {'target_role': 'ESCALATION_PARTNER'}
    assert _body(result)['targetRole'] == 'ESCALATION_PARTNER'


# ── 7. take is refused in code, with the owner action named ────────────────────

def test_take_is_refused_without_calling_meta(handler):
    """409 with ownerAction O3, and the boundary count is the assertion that matters.

    Sending it and letting Meta answer 2494191 would produce an error an operator cannot
    act on. A 409 naming O3 tells them exactly what unblocks it.
    """
    result, cap = _call(handler, handler._thread_control,
                        {'entityId': PHONE_ID, 'bsuid': BSUID, 'action': 'take'})
    assert result['statusCode'] == 409
    assert cap.count == 0
    body = _body(result)
    assert body['ownerAction'] == 'O3'
    assert body['action'] == 'take'
    assert '2494191' in body['reason']


# ── 8. an unknown action never reaches Meta ────────────────────────────────────

def test_unknown_action_is_refused(handler):
    result, cap = _call(handler, handler._thread_control,
                        {'entityId': PHONE_ID, 'bsuid': BSUID, 'action': 'hijack'})
    assert result['statusCode'] == 400
    assert cap.count == 0
    assert list(handler._THREAD_CONTROL_ACTIONS) == ['release', 'pass', 'take']


def test_a_thread_with_no_identifier_is_refused(handler):
    """Neither bsuid nor to -> 400, zero calls. The old code required `to` and so could
    not express a BSUID-identified thread at all."""
    result, cap = _call(handler, handler._thread_control, {'entityId': PHONE_ID})
    assert result['statusCode'] == 400
    assert cap.count == 0
    result, cap = _call(handler, handler._thread_control, {'bsuid': BSUID})
    assert result['statusCode'] == 400
    assert cap.count == 0


# ── 9. the header change is surgical: a PAIR, not one test ─────────────────────

def test_no_x_api_version_header_on_a_graph_call(handler):
    """Fault (e). `X-API-Version` is an agent-API header; the Graph version already
    travels in the URL via `handler.GRAPH`."""
    _, cap = _call(handler, handler._thread_control,
                   {'entityId': PHONE_ID, 'bsuid': BSUID})
    assert 'x-api-version' not in cap.headers


def test_another_agent_action_still_sends_the_header(handler):
    """The companion. Without it, removing the header for EVERYONE would pass the test
    above -- the pair is what makes the change surgical. `_eligibility` calls
    `_meta_request` with three positional arguments, like all 44 pre-existing sites."""
    _, cap = _call(handler, handler._eligibility, {'entityId': PHONE_ID})
    assert cap.headers.get('x-api-version') == handler.API_VERSION
    assert cap.url.startswith(handler.GRAPH_HOST)


# ── 10. the log line discloses the BSUID and masks the phone ───────────────────

def test_the_phone_is_masked_in_the_log_and_the_bsuid_is_not(handler, caplog):
    """BSUID in full (business-scoped, traceable), phone masked. That pairing is what
    makes a routing event followable without disclosing a customer's number -- the same
    discipline the inbound handler's handover arm already applies."""
    caplog.set_level(logging.INFO)
    _call(handler, handler._thread_control,
          {'entityId': PHONE_ID, 'bsuid': BSUID, 'to': E164})
    lines = [r.getMessage() for r in caplog.records
             if 'thread_control_requested' in r.getMessage()]
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged['bsuid'] == BSUID
    assert logged['to'] == handler.mask_phone(E164)
    assert E164 not in lines[0]
    assert logged['phoneNumberId'] == PHONE_ID
    assert logged['action'] == 'release'
    assert logged['httpStatus'] == 200


# ── 11. the inbound handover arm is STILL write-and-log-only ───────────────────

@pytest.fixture(scope='module')
def inbound():
    spec = importlib.util.spec_from_file_location(
        'inbound_wa_thread_control_guard', str(INBOUND_HANDLER_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wa_thread_control_guard'] = module
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            spec.loader.exec_module(module)
    return module


def _handover_event():
    """A `messaging_handovers` control_passed webhook in the stored shape."""
    return {
        'source': 'meta-direct', 'version': 1, 'wabaId': WABA,
        'metaPhoneNumberIds': [PHONE_ID], 'requestId': 'req-handover-guard',
        'entry': {'id': WABA, 'changes': [{
            'field': 'messaging_handovers',
            'value': {
                'messaging_product': 'whatsapp',
                'metadata': {'display_phone_number': '919330994400',
                             'phone_number_id': PHONE_ID},
                'contacts': [{'wa_id': WA_ID, 'user_id': BSUID}],
                'control_passed': {'previous_owner_role': 'AI_RESPONDER',
                                   'new_owner_role': 'BUSINESS',
                                   'reason': 'escalation'},
            },
        }]},
    }


def test_messaging_handovers_still_takes_no_action(inbound):
    """The guard on design decision 6, so a later pass cannot quietly wire the webhook
    to the now-working endpoint.

    Derived ownership must be OBSERVED correct before it is allowed to refuse a customer
    a reply, and automatically releasing or passing control off a parsed webhook is
    exactly that kind of decision. Thread control stays operator-initiated.

    Both Graph boundaries are counted, because counting one would miss half the sends:
    `urllib.request.urlopen` is the Direct API path and `lambda_client.invoke` is
    everything routed through `wecare-outbound-whatsapp`.
    """
    urlopen_calls = []
    invoke_calls = []

    def _urlopen(req, *a, **kw):
        urlopen_calls.append(req)
        resp = MagicMock()
        resp.read.return_value = b'{}'
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *args: False
        resp.status = 200
        return resp

    def _invoke(**kwargs):
        invoke_calls.append(kwargs)
        return {'StatusCode': 202}

    context = MagicMock()
    context.aws_request_id = 'req-handover-guard'
    context.get_remaining_time_in_millis.return_value = 300000

    to.set_table(MagicMock())
    try:
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}, clear=False), \
                patch('urllib.request.urlopen', side_effect=_urlopen), \
                patch.object(inbound.lambda_client, 'invoke', side_effect=_invoke), \
                patch('lambda_utils.webhook_dedup.claim_event', return_value=True), \
                patch.object(inbound.dynamodb, 'Table', return_value=MagicMock()), \
                patch.object(inbound, '_load_direct_api_token',
                             return_value='token-stand-in'):
            inbound.handler(_handover_event(), context)
    finally:
        to.set_table(None)

    assert len(urlopen_calls) == 0, 'a handover webhook must issue no Graph request'
    assert len(invoke_calls) == 0, 'a handover webhook must trigger no outbound send'
