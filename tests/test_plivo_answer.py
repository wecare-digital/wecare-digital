"""Tests for the Plivo answer URL that drives the WhatsApp IVR.

No network calls, no Plivo API use. Asserts XML shape, content type and the
token gate, since a malformed response makes the caller hear silence.
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

import importlib.util

# Handlers all share the filename handler.py, so load by absolute path under a
# unique module name to avoid colliding with other test modules.
_HANDLER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging',
    'plivo-answer', 'handler.py'))

_spec = importlib.util.spec_from_file_location('plivo_answer_handler_under_test', _HANDLER)
pa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pa)


@pytest.fixture(autouse=True)
def _hermetic_token_lookup(monkeypatch):
    """Stop `_get_answer_token()` reaching real Secrets Manager.

    These tests used to pass only by accident: `wecare/plivo-answer` did not
    exist, so the lazy lookup reached real AWS, found nothing, and left the gate
    open, which is what the no-token cases silently relied on. The moment the
    secret was provisioned the same lookup returned a live token and every test
    that does not send one began failing with 403. The gate was correct; the
    tests were simply not isolated from the account.

    Default state here is "no token configured", so the response-contract tests
    exercise the open path. The token-gate tests seed `_answer_token_cache`
    themselves, and the resolver tests install their own fake client; both run
    after this fixture, so their monkeypatching wins.
    """
    monkeypatch.setattr(pa, '_answer_token_cache', '')
    monkeypatch.delenv('PLIVO_ANSWER_TOKEN', raising=False)

    class _NoSecretsManager:
        def get_secret_value(self, SecretId):  # noqa: N803
            raise RuntimeError('tests must not call AWS')

    import boto3
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: _NoSecretsManager())

    # The handler now de-duplicates the post-call SMS through
    # lambda_utils.webhook_dedup, which talks to a real DynamoDB table. Left
    # unstubbed these tests reach AWS and, worse, contaminate each other: the
    # first test to claim a CallUUID makes every later test using the same UUID
    # look like a duplicate and skip its side effect. That is the identical
    # isolation failure this fixture was added to fix for the token lookup.
    # Always-fresh here; the dedup behaviour itself is covered in
    # tests/test_plivo_routes.py against a stub.
    monkeypatch.setattr(pa, '_claim_once', lambda call_uuid, suffix: True)

    # Persisting the CDR is likewise a real table write.
    class _NoTable:
        def put_item(self, Item):  # noqa: N803
            raise RuntimeError('tests must not write to DynamoDB')

    monkeypatch.setattr(pa, '_table', lambda: _NoTable())


def _event(body='', qs=None, b64=False):
    return {
        'requestContext': {'http': {'method': 'POST', 'path': '/plivo/answer'}},
        'headers': {'content-type': 'application/x-www-form-urlencoded'},
        'body': body,
        'isBase64Encoded': b64,
        'queryStringParameters': qs,
    }


PLIVO_FORM = (
    'CallUUID=abc-123&From=919876543210&To=918031830030'
    '&Direction=inbound&CallStatus=ringing'
)


# --------------------------------------------------------------------------
# Response contract
# --------------------------------------------------------------------------
def test_returns_xml_content_type():
    """Plivo ignores the body unless Content-Type is XML."""
    r = pa.handler(_event(PLIVO_FORM), None)
    assert r['statusCode'] == 200
    assert 'text/xml' in r['headers']['Content-Type']


def test_body_is_wellformed_xml():
    r = pa.handler(_event(PLIVO_FORM), None)
    ET.fromstring(r['body'])  # raises if malformed


def test_xml_is_play_then_hangup_in_order():
    r = pa.handler(_event(PLIVO_FORM), None)
    root = ET.fromstring(r['body'])
    assert root.tag == 'Response'
    assert [c.tag for c in root] == ['Play', 'Hangup']


def test_play_points_at_a_plivo_supported_format():
    r = pa.handler(_event(PLIVO_FORM), None)
    url = ET.fromstring(r['body']).find('Play').text
    assert url.startswith('https://')
    assert url.endswith(('.wav', '.mp3')), \
        'Plivo <Play> does not reliably support OGG/Opus'


def test_no_tts_or_record_elements():
    """The IVR is pre-recorded only: no Speak, no Record."""
    body = pa.handler(_event(PLIVO_FORM), None)['body']
    for forbidden in ('<Speak', '<Record', '<GetDigits', '<Dial'):
        assert forbidden not in body


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def test_parses_form_encoded_body():
    p = pa._parse_body(_event(PLIVO_FORM))
    assert p['CallUUID'] == 'abc-123'
    assert p['Direction'] == 'inbound'


def test_parses_json_body_too():
    p = pa._parse_body(_event('{"CallUUID":"json-1"}'))
    assert p['CallUUID'] == 'json-1'


def test_parses_base64_body():
    import base64
    ev = _event(base64.b64encode(PLIVO_FORM.encode()).decode(), b64=True)
    assert pa._parse_body(ev)['CallUUID'] == 'abc-123'


def test_empty_body_still_answers():
    """A missing body must not stop the greeting from playing."""
    r = pa.handler(_event(''), None)
    assert r['statusCode'] == 200
    assert '<Play>' in r['body']


# --------------------------------------------------------------------------
# Token gate
# --------------------------------------------------------------------------
# The token is now resolved lazily from Secrets Manager and cached in
# `_answer_token_cache`, instead of being read from the env at import. Seeding the
# cache short-circuits `_get_answer_token()` so these stay hermetic — no AWS call.
def test_no_token_configured_means_open(monkeypatch):
    monkeypatch.setattr(pa, '_get_answer_token', lambda: '')
    assert pa.handler(_event(PLIVO_FORM), None)['statusCode'] == 200


def test_wrong_token_is_rejected_with_hangup(monkeypatch):
    monkeypatch.setattr(pa, '_answer_token_cache', 'sekret')
    r = pa.handler(_event(PLIVO_FORM, qs={'token': 'nope'}), None)
    assert r['statusCode'] == 403
    assert '<Hangup/>' in r['body']
    assert '<Play>' not in r['body'], 'must not leak the media URL'


def test_correct_token_is_accepted(monkeypatch):
    monkeypatch.setattr(pa, '_answer_token_cache', 'sekret')
    r = pa.handler(_event(PLIVO_FORM, qs={'token': 'sekret'}), None)
    assert r['statusCode'] == 200
    assert '<Play>' in r['body']


def test_missing_token_is_rejected_when_one_is_configured(monkeypatch):
    """The abuse vector: an unauthenticated POST must not reach the SMS path.

    CallStatus=completed is what triggers the post-call SMS, so a caller with no
    token must be refused before that runs.
    """
    monkeypatch.setattr(pa, '_answer_token_cache', 'sekret')
    sent = []
    monkeypatch.setattr(pa, '_send_post_call_sms',
                        lambda *a, **k: sent.append(a))
    r = pa.handler(_event('CallUUID=x&From=919999999999&CallStatus=completed'), None)
    assert r['statusCode'] == 403
    assert sent == [], 'no-token request must not trigger the follow-up SMS'


def test_token_resolver_prefers_secrets_manager_and_caches(monkeypatch):
    """Secrets Manager first, env only as fallback, and fetched at most once."""
    monkeypatch.setattr(pa, '_answer_token_cache', '')
    monkeypatch.setenv('PLIVO_ANSWER_TOKEN', 'from-env')
    calls = []

    class _FakeSM:
        def get_secret_value(self, SecretId):            # noqa: N803
            calls.append(SecretId)
            return {'SecretString': '{"token": "from-secrets-manager"}'}

    import boto3
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: _FakeSM())

    assert pa._get_answer_token() == 'from-secrets-manager'
    assert pa._get_answer_token() == 'from-secrets-manager'
    assert len(calls) == 1, 'must cache, not re-fetch on every request'


def test_token_resolver_falls_back_to_env_when_secret_absent(monkeypatch):
    monkeypatch.setattr(pa, '_answer_token_cache', '')
    monkeypatch.setenv('PLIVO_ANSWER_TOKEN', 'from-env')

    import boto3

    def _boom(*a, **k):
        raise RuntimeError('ResourceNotFoundException')

    monkeypatch.setattr(boto3, 'client', _boom)
    assert pa._get_answer_token() == 'from-env'


def test_xml_escaping_of_media_url(monkeypatch):
    monkeypatch.setattr(pa, 'IVR_AUDIO_URL', 'https://x/a.wav?a=1&b=2')
    body = pa.handler(_event(PLIVO_FORM), None)['body']
    assert '&amp;' in body
    ET.fromstring(body)


# --------------------------------------------------------------------------
# Post-call follow-up SMS
# --------------------------------------------------------------------------
HANGUP_FORM = (
    'CallUUID=abc-123&From=919876543210&To=918031830030'
    '&Direction=inbound&CallStatus=completed&Duration=25'
)


def test_ringing_returns_xml_and_sends_no_sms(monkeypatch):
    """The answer pass must return XML and must NOT text anyone."""
    calls = []
    monkeypatch.setattr(pa, '_send_post_call_sms',
                        lambda *a, **k: calls.append(a))
    r = pa.handler(_event(PLIVO_FORM), None)
    assert 'text/xml' in r['headers']['Content-Type']
    assert '<Play>' in r['body']
    assert calls == [], 'SMS must not be sent on the answer pass'


def test_completed_sends_sms_and_returns_no_xml(monkeypatch):
    """The hangup pass must text the caller exactly once - WHEN VERIFIED.

    Updated 2026-09-19. This previously passed with no token configured, which is
    what made the hole visible: sending the SMS did not require the request to be
    proven to be Plivo. The assertion is unchanged except that the request is now
    token-gated, which a genuine Plivo answer_url fetch is.
    """
    calls = []
    monkeypatch.setattr(pa, '_send_post_call_sms',
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(pa, '_get_answer_token', lambda: 'tok')
    event = _event(HANGUP_FORM)
    event['queryStringParameters'] = {'token': 'tok'}
    r = pa.handler(event, None)
    assert r['statusCode'] == 200
    assert '<Play>' not in r['body'], 'must not replay audio on hangup'
    assert len(calls) == 1
    assert calls[0][0] == '919876543210'


def test_unverified_completed_pass_sends_no_sms(monkeypatch):
    """An unverified caller must not be able to make us text an arbitrary number.

    This is the SMS-pumping vector the trust split closes. POSTing
    CallStatus=completed&From=91XXXXXXXXXX to /plivo/answer used to send a
    DLT-templated message to that number, at our cost, under our registered
    sender, whenever the answer token happened to be unreadable.

    The request is still ACCEPTED - refusing it would drop real calls when a
    secret read fails - but the side effect is suppressed.
    """
    calls = []
    monkeypatch.setattr(pa, '_send_post_call_sms',
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(pa, '_get_answer_token', lambda: '')
    monkeypatch.setattr(pa, '_get_plivo_auth_token', lambda: '')
    r = pa.handler(_event(HANGUP_FORM), None)
    assert calls == [], 'SMS must not be sent for an unverified request'
    assert r['statusCode'] == 202, 'accepted, but side effects suppressed'
    assert json.loads(r['body'])['sideEffectsSuppressed'] is True


def test_unverified_answer_pass_still_returns_the_ivr(monkeypatch):
    """Serving the call and performing a side effect are separate privileges.

    Plivo does not sign answer_url fetches, so refusing an unsigned one would drop
    every real inbound call. The IVR must still be served at TRUST_NONE.
    """
    monkeypatch.setattr(pa, '_get_answer_token', lambda: '')
    monkeypatch.setattr(pa, '_get_plivo_auth_token', lambda: '')
    r = pa.handler(_event(PLIVO_FORM), None)
    assert r['statusCode'] == 200
    assert '<Play>' in r['body']


def test_wrong_token_is_rejected_outright(monkeypatch):
    """A WRONG token is an attacker; a MISSING one may be our own outage."""
    monkeypatch.setattr(pa, '_get_answer_token', lambda: 'tok')
    monkeypatch.setattr(pa, '_get_plivo_auth_token', lambda: '')
    event = _event(PLIVO_FORM)
    event['queryStringParameters'] = {'token': 'not-the-token'}
    r = pa.handler(event, None)
    assert r['statusCode'] == 403
    assert '<Hangup' in r['body']


def test_sms_body_matches_approved_dlt_template():
    """Operator drops mismatched content, so this copy is load-bearing."""
    body = pa.IVR_SMS_BODY
    assert body.startswith('Thanks for contacting WECARE.DIGITAL!')
    assert 'https://wecare.digital/submit-request/' in body
    assert 'https://wecare.digital/r/wa' in body
    assert body.count('\n\n') == 2, 'DLT template has two blank-line breaks'
    assert pa.DLT_TEMPLATE_KEY == 'ivr-default'


def test_non_indian_caller_is_skipped(monkeypatch):
    """No approved DLT template exists for non-India, so do not send."""
    sent = []
    monkeypatch.setattr(pa, 'POST_CALL_SMS_ENABLED', True)

    class FakeLambda:
        def invoke(self, **kw):
            sent.append(kw)

    import types
    monkeypatch.setitem(__import__('sys').modules, 'boto3',
                        types.SimpleNamespace(client=lambda *a, **k: FakeLambda()))
    pa._send_post_call_sms('+14155552671', 'uuid-1', 'req-1')
    assert sent == [], 'must not send to a non-Indian caller'


def test_indian_caller_invokes_sms_lambda_async(monkeypatch):
    sent = []
    monkeypatch.setattr(pa, 'POST_CALL_SMS_ENABLED', True)

    class FakeLambda:
        def invoke(self, **kw):
            sent.append(kw)

    import types
    monkeypatch.setitem(__import__('sys').modules, 'boto3',
                        types.SimpleNamespace(client=lambda *a, **k: FakeLambda()))
    pa._send_post_call_sms('919876543210', 'uuid-2', 'req-2')
    assert len(sent) == 1
    assert sent[0]['InvocationType'] == 'Event', 'must not block the call'
    assert 'wecare-sms-aws' in sent[0]['FunctionName']
    body = __import__('json').loads(
        __import__('json').loads(sent[0]['Payload'].decode())['body'])
    assert body['phoneNumber'] == '+919876543210'
    assert body['dltTemplateKey'] == 'ivr-default'
    assert body['messageType'] == 'TRANSACTIONAL'


def test_sms_failure_never_breaks_the_call(monkeypatch):
    monkeypatch.setattr(pa, 'POST_CALL_SMS_ENABLED', True)

    class Boom:
        def invoke(self, **kw):
            raise RuntimeError('lambda unavailable')

    import types
    monkeypatch.setitem(__import__('sys').modules, 'boto3',
                        types.SimpleNamespace(client=lambda *a, **k: Boom()))
    pa._send_post_call_sms('919876543210', 'uuid-3', 'req-3')  # must not raise


def test_post_call_sms_is_always_enabled_regardless_of_env(monkeypatch):
    """The follow-up is unconditional: the env var no longer disables it.

    A deployment that set POST_CALL_SMS_ENABLED=false used to silently stop every caller
    getting a follow-up; the flag is now hardcoded on. Loaded fresh with the env explicitly
    set to 'false' to prove the source ignores it.
    """
    monkeypatch.setenv('POST_CALL_SMS_ENABLED', 'false')
    fresh_spec = importlib.util.spec_from_file_location('plivo_always_on_probe', _HANDLER)
    fresh = importlib.util.module_from_spec(fresh_spec)
    fresh_spec.loader.exec_module(fresh)
    assert fresh.POST_CALL_SMS_ENABLED is True, 'env must not be able to disable the follow-up'

    sent = []

    class FakeLambda:
        def invoke(self, **kw):
            sent.append(kw)

    import types
    monkeypatch.setitem(__import__('sys').modules, 'boto3',
                        types.SimpleNamespace(client=lambda *a, **k: FakeLambda()))
    fresh._send_post_call_sms('919876543210', 'uuid-4', 'req-4')
    assert len(sent) == 1, 'an env disable must no longer suppress the follow-up'
