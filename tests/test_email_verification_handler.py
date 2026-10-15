"""The email-verification handler: it wires the tested modules together without leaking.

What these tests defend
-----------------------
The mechanism (hashing, throttling, sending) is tested in test_otp_challenge / test_otp_throttle /
test_verification_email. This file tests the *handler's* obligations: the code never appears in a
response or a log, the same shape comes back whether or not the address is known (no enumeration),
a throttled request 429s before any send, every verify failure collapses to one opaque outcome,
and a successful verify returns a short-lived server-held proof bound to the normalized email.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402

# Load THIS handler under a unique module name. A bare `import handler` collides with every other
# function's handler.py in sys.modules — seo-tools/handler.py, for one — so under a full-suite run
# the name resolves to whichever handler was imported first. spec_from_file_location pins it to
# this file regardless of ordering. (The WhatsApp-auth test does the same, for the same reason.)
_HANDLER_PATH = (Path(__file__).resolve().parents[1]
                 / "amplify/functions/auth/email-verification/handler.py")

OTP_TABLE = 'stack-wecare-digital-DownloadGrantsTable'
#: The one person store. Declared in the fake so a stray write to it would be visible; the
#: handler must never touch it (customer-profile stamps the verified email there).
CONTACTS_TABLE = 'stack-wecare-digital-ContactsTable'
PEPPER = 'test-pepper-not-a-real-secret'
EMAIL = 'Asha@Example.com'          # deliberately mixed-case; handler normalises
NORMALISED = 'asha@example.com'


class _FakeSes:
    """Records the send and returns a message id. Captures args so a test can prove the code
    was passed to SES and NOT to any log."""

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {'MessageId': 'ses-msg-1'}


@pytest.fixture
def handler_env(monkeypatch):
    monkeypatch.setenv('OTP_TABLE', OTP_TABLE)
    monkeypatch.setenv('APP_ENV', 'development')  # allow localhost origin in tests

    spec = importlib.util.spec_from_file_location(
        "email_verification_under_test", _HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(keys={OTP_TABLE: 'grantId', CONTACTS_TABLE: 'id'})
    ses = _FakeSes()

    monkeypatch.setattr(h, '_dynamodb', fake)
    monkeypatch.setattr(h, '_pepper', lambda: PEPPER)
    monkeypatch.setattr(h, '_ses_client', lambda: ses)
    return h, fake, ses


def _event(action, **body):
    return {
        'requestContext': {'http': {'method': 'POST', 'sourceIp': '203.0.113.5',
                                    'apiId': 'zllr9lrg7j'}},
        'headers': {'origin': 'http://localhost:3000'},
        'body': json.dumps({'action': action, **body}),
    }


# ── request ───────────────────────────────────────────────────────────────────

def test_request_sends_and_returns_no_code(handler_env):
    h, _fake, ses = handler_env
    resp = h.handler(_event('request', email=EMAIL, firstName='Asha'), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'sent'
    # The response carries an expiry but never the code.
    assert 'code' not in body
    assert 'expiresInSeconds' in body
    # SES received exactly one message, addressed to the normalised address.
    assert len(ses.sent) == 1
    dest = ses.sent[0]['Destination']['ToAddresses']
    assert dest == [NORMALISED]


def test_request_is_not_an_enumeration_oracle(handler_env):
    # A known and an unknown address must produce the same shape. There is no "already
    # registered" branch to tell them apart.
    h, _fake, _ses = handler_env
    a = h.handler(_event('request', email='known@example.com'), None)
    b = h.handler(_event('request', email='unknown@example.com'), None)
    assert a['statusCode'] == b['statusCode'] == 200
    assert set(json.loads(a['body'])) == set(json.loads(b['body']))


def test_request_rejects_a_malformed_email(handler_env):
    h, _fake, ses = handler_env
    resp = h.handler(_event('request', email='not-an-email'), None)
    assert resp['statusCode'] == 400
    assert json.loads(resp['body'])['error'] == 'INVALID_EMAIL'
    assert ses.sent == []


def test_resend_inside_cooldown_is_refused_before_sending(handler_env):
    h, _fake, ses = handler_env
    first = h.handler(_event('request', email=EMAIL), None)
    assert first['statusCode'] == 200
    # Immediately again: inside the 60s cooldown.
    second = h.handler(_event('request', email=EMAIL), None)
    assert second['statusCode'] == 429
    assert json.loads(second['body'])['error'] == 'RESEND_TOO_SOON'
    # No second send happened.
    assert len(ses.sent) == 1


def test_the_code_never_appears_in_logs(handler_env, caplog):
    h, _fake, ses = handler_env
    with caplog.at_level('INFO'):
        h.handler(_event('request', email=EMAIL), None)
    sent_code = None
    # Recover the code SES was given, then assert it is nowhere in the captured logs.
    body = ses.sent[0]['Content']['Simple']['Body']['Text']['Data']
    for token in body.split():
        if token.isdigit() and len(token) == 6:
            sent_code = token
    assert sent_code is not None
    assert sent_code not in caplog.text


# ── verify ──────────────────────────────────────────────────────────────────

def _issue_and_capture_code(h, ses, email=EMAIL):
    h.handler(_event('request', email=email), None)
    body = ses.sent[-1]['Content']['Simple']['Body']['Text']['Data']
    for token in body.split():
        if token.isdigit() and len(token) == 6:
            return token
    raise AssertionError('no code found in the sent email')


def test_verify_accepts_the_correct_code(handler_env):
    h, _fake, ses = handler_env
    code = _issue_and_capture_code(h, ses)
    resp = h.handler(_event('verify', email=EMAIL, code=code), None)
    assert resp['statusCode'] == 200
    assert json.loads(resp['body'])['status'] == 'VERIFIED'


def test_verify_failures_are_all_one_opaque_outcome(handler_env):
    h, _fake, ses = handler_env
    _issue_and_capture_code(h, ses)
    wrong = h.handler(_event('verify', email=EMAIL, code='000000'), None)
    never = h.handler(_event('verify', email='nochallenge@example.com', code='123456'), None)
    assert wrong['statusCode'] == never['statusCode'] == 400
    assert json.loads(wrong['body'])['status'] == json.loads(never['body'])['status'] \
        == 'INVALID_OR_EXPIRED'


def test_verify_returns_email_bound_proof_and_never_stamps_body_selected_customer(handler_env):
    h, fake, ses = handler_env
    cid = 'wa919999900000'
    fake.Table(CONTACTS_TABLE).put_item(Item={'id': cid, 'contactId': cid})

    code = _issue_and_capture_code(h, ses)
    resp = h.handler(_event('verify', email=EMAIL, code=code, customerId=cid, contactId=cid), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'VERIFIED'
    assert body['proof']
    assert body['expiresInSeconds'] == h.PROOF_TTL_SECONDS

    # Public email verification proves the email only; it cannot mutate a browser-selected
    # customer. The contact row is untouched, and there is no second person store to write to.
    row = fake.Table(CONTACTS_TABLE).get_item(Key={'id': cid})['Item']
    assert 'emailVerifiedAt' not in row
    assert not hasattr(h, 'CUSTOMERS_TABLE')

    proof = fake.Table(OTP_TABLE).get_item(
        Key={'grantId': h.PROOF_PREFIX + body['proof']})['Item']
    assert proof['purpose'] == h.PROOF_PURPOSE
    # Proof binds to the NORMALISED email (handler normalises before _issue_proof; the
    # customer-profile consumer normalises before validating). Asserting raw mixed-case EMAIL was
    # the stale half, fixed 2026-10-03; the security property was always held.
    assert proof['subjectDigest'] == h._proof_digest(NORMALISED)


def test_a_used_code_cannot_be_replayed(handler_env):
    h, _fake, ses = handler_env
    code = _issue_and_capture_code(h, ses)
    assert h.handler(_event('verify', email=EMAIL, code=code), None)['statusCode'] == 200
    replay = h.handler(_event('verify', email=EMAIL, code=code), None)
    assert replay['statusCode'] == 400
    assert json.loads(replay['body'])['status'] == 'INVALID_OR_EXPIRED'
