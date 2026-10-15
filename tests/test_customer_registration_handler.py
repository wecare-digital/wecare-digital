"""The customer-registration handler: it wires the tested modules together without leaking.

What these tests defend
-----------------------
The mechanism (hashing, throttling, the ordered begin/complete flow) is tested in
test_otp_challenge / test_otp_throttle / test_registration. This file tests the *handler's*
obligations at the HTTP boundary (Section 59 of the Wix-Velo prompt):

- the OTP never appears in a response or a log;
- `request` returns the same shape whether or not the number is a customer (no enumeration);
- the per-IP and per-phone throttle refuses BEFORE any WhatsApp send;
- every `verify` failure collapses to one opaque outcome;
- a successful `verify` resolves-or-creates exactly one immutable `CUS_<ULID>` customer and
  administratively provisions a Cognito login — the browser is never asked to create one;
- the customer id is NOT returned to the browser (the session credential comes from the
  subsequent Cognito sign-in, not from here).
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

# Pin the module to this file — a bare `import handler` collides with every other function's
# handler.py under a full-suite run. Same pattern as the email-verification and WhatsApp-auth tests.
_HANDLER_PATH = (Path(__file__).resolve().parents[1]
                 / "amplify/functions/auth/customer-registration/handler.py")

OTP_TABLE = 'stack-wecare-digital-DownloadGrantsTable'
#: The one person store: registration resolves to, or creates, the customer's ContactsTable row.
CONTACTS_TABLE = 'stack-wecare-digital-ContactsTable'
PHONE_INDEX = 'phone-index'
PEPPER = 'test-pepper-not-a-real-secret'
# Spaced, WITH an explicit country code. The handler still normalises the separators; what it no
# longer does is guess the country. A bare '93309 94400' was previously inferred to be Indian,
# and that inference is the defect: a ten-digit foreign number matched the same pattern and was
# prefixed, so the OTP went to an unrelated Indian subscriber and the wrong identity was
# reserved. See tests/test_phone_country_code_preservation.py.
RAW_PHONE = '+91 93309 94400'
BARE_PHONE = '93309 94400'           # no country code; now refused rather than assumed Indian
E164 = '+919330994400'


class _FakeLambda:
    """Captures the internal template-send invoke and returns a 200 from the sender."""

    def __init__(self):
        self.invocations = []
        self.fail = False

    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        decoded = json.loads(Payload.decode('utf-8'))
        self.invocations.append({'FunctionName': FunctionName, 'event': decoded})
        status = 502 if self.fail else 200
        inner = json.dumps({'statusCode': status, 'body': '{}'}).encode('utf-8')
        return {'Payload': _FakePayload(inner)}


class _FakePayload:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _CognitoExc(Exception):
    pass


class _FakeCognito:
    """Records admin provisioning; raises UsernameExistsException on demand."""

    class exceptions:
        UsernameExistsException = _CognitoExc

    def __init__(self):
        self.created = []
        self.updated = []
        self.passwords = []
        self.exists = False

    def admin_create_user(self, **kwargs):
        if self.exists:
            raise self.exceptions.UsernameExistsException()
        self.created.append(kwargs)
        return {'User': {'Username': kwargs['Username']}}

    def admin_set_user_password(self, **kwargs):
        self.passwords.append(kwargs)

    def admin_update_user_attributes(self, **kwargs):
        self.updated.append(kwargs)


@pytest.fixture
def handler_env(monkeypatch):
    monkeypatch.setenv('OTP_TABLE', OTP_TABLE)
    monkeypatch.setenv('CONTACTS_TABLE', CONTACTS_TABLE)
    monkeypatch.setenv('APP_ENV', 'development')  # allow localhost origin in tests

    spec = importlib.util.spec_from_file_location(
        "customer_registration_under_test", _HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(
        keys={OTP_TABLE: 'grantId', CONTACTS_TABLE: 'id'},
        indexes={CONTACTS_TABLE: {PHONE_INDEX: ('phone', None)}},
    )
    lam = _FakeLambda()
    cog = _FakeCognito()

    monkeypatch.setattr(h, '_dynamodb', fake)
    monkeypatch.setattr(h, '_pepper', lambda: PEPPER)
    monkeypatch.setattr(h, '_lambda_client', lambda: lam)
    monkeypatch.setattr(h, '_cognito_client', lambda: cog)
    return h, fake, lam, cog


def _event(action, ip='203.0.113.5', **body):
    return {
        'requestContext': {'http': {'method': 'POST', 'sourceIp': ip, 'apiId': 'zllr9lrg7j'}},
        'headers': {'origin': 'http://localhost:3000'},
        'body': json.dumps({'action': action, **body}),
    }


def _sent_code(lam):
    """Recover the OTP the WhatsApp sender was handed, from the last invoke."""
    event = lam.invocations[-1]['event']
    body = json.loads(event['body'])
    text_params = body['components'][0]['parameters']
    return text_params[0]['text']


def _issue_and_capture_code(h, lam, phone=RAW_PHONE, ip='203.0.113.5'):
    resp = h.handler(_event('request', ip=ip, phone=phone), None)
    assert resp['statusCode'] == 200, resp
    return _sent_code(lam)


# ── request ─────────────────────────────────────────────────────────────────

def test_request_sends_and_returns_no_code(handler_env):
    h, _fake, lam, _cog = handler_env
    resp = h.handler(_event('request', phone=RAW_PHONE), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'code_sent'
    assert 'code' not in body
    assert 'expiresInSeconds' in body
    # Exactly one WhatsApp template send, to the normalised digits-only destination.
    assert len(lam.invocations) == 1
    sent = json.loads(lam.invocations[0]['event']['body'])
    assert sent['to'] == '919330994400'
    assert sent['templateName'] == 'wecare_otp'
    # The OTP is delivered via a URL button, never copy_code.
    assert sent['components'][1]['sub_type'] == 'url'


def test_request_is_not_an_enumeration_oracle(handler_env):
    h, fake, lam, cog = handler_env
    # Pre-create a contact for one number so it is "known".
    fake.Table(CONTACTS_TABLE).put_item(
        Item={'id': 'wa919000000001', 'contactId': 'wa919000000001',
              'phone': '+919000000001'})
    known = h.handler(_event('request', phone='+919000000001'), None)
    unknown = h.handler(_event('request', phone='+919000000002'), None)
    assert known['statusCode'] == unknown['statusCode'] == 200
    assert set(json.loads(known['body'])) == set(json.loads(unknown['body']))


def test_request_rejects_a_malformed_phone(handler_env):
    h, _fake, lam, _cog = handler_env
    resp = h.handler(_event('request', phone='12'), None)
    assert resp['statusCode'] == 400
    assert json.loads(resp['body'])['status'] == 'invalid_phone'
    assert lam.invocations == []


def test_request_rejects_a_number_with_no_country_code(handler_env):
    """At the HTTP door, not just in the module. `PhoneField` always emits a dial code, so a
    bare national number reaching here is a direct API caller - and guessing +91 for it is
    exactly how a foreign customer's code ends up on an Indian handset."""
    h, _fake, lam, _cog = handler_env
    resp = h.handler(_event('request', phone=BARE_PHONE), None)
    assert resp['statusCode'] == 400
    assert json.loads(resp['body'])['status'] == 'invalid_phone'
    assert lam.invocations == [], 'nothing may be sent for a refused number'


def test_resend_inside_cooldown_is_refused_before_sending(handler_env):
    h, _fake, lam, _cog = handler_env
    first = h.handler(_event('request', phone=RAW_PHONE), None)
    assert first['statusCode'] == 200
    second = h.handler(_event('request', phone=RAW_PHONE), None)
    assert second['statusCode'] == 429
    # No second WhatsApp message went out.
    assert len(lam.invocations) == 1


def test_per_ip_throttle_refuses_before_send(handler_env):
    h, _fake, lam, _cog = handler_env
    # DEFAULT_IP_MAX is 20/hour. Twenty-one distinct numbers from one IP trips the IP axis; each
    # number is fresh so the per-phone cooldown never fires first.
    from lambda_utils import otp_throttle
    tripped = None
    for i in range(otp_throttle.DEFAULT_IP_MAX + 1):
        resp = h.handler(_event('request', ip='198.51.100.7',
                                phone=f'+9199000{i:05d}'), None)
        if resp['statusCode'] == 429:
            tripped = i
            break
    assert tripped is not None, "the per-IP limit never tripped"
    # Every accepted request sent exactly one message; the tripped one sent none.
    assert len(lam.invocations) == tripped


def test_the_code_never_appears_in_logs(handler_env, caplog):
    h, _fake, lam, _cog = handler_env
    with caplog.at_level('INFO'):
        h.handler(_event('request', phone=RAW_PHONE), None)
    code = _sent_code(lam)
    assert code and code.isdigit()
    assert code not in caplog.text
    # And the full phone number is not logged either.
    assert '919330994400' not in caplog.text


# ── verify ────────────────────────────────────────────────────────────────

def test_verify_creates_the_customer_and_provisions_a_login(handler_env):
    h, fake, lam, cog = handler_env
    code = _issue_and_capture_code(h, lam)
    resp = h.handler(_event('verify', phone=RAW_PHONE, code=code), None)
    assert resp['statusCode'] == 200
    body = json.loads(resp['body'])
    assert body['status'] == 'verified'
    # The customer id is NEVER handed to the browser.
    assert 'customerId' not in body and 'customer_id' not in json.dumps(body)

    # Exactly one contact row, phone verified, keyed by the SAME deterministic id the WhatsApp
    # inbox mints - so the customer's later WhatsApp messages land on this row, not a second one.
    rows = fake.all_rows(CONTACTS_TABLE)
    assert len(rows) == 1
    assert rows[0]['id'] == rows[0]['contactId'] == 'wa919330994400'
    assert rows[0]['phoneVerifiedAt']
    assert rows[0]['phone'] == E164
    # Transactional identity is not marketing consent.
    assert rows[0]['optInWhatsApp'] is False and rows[0]['allowlistWhatsApp'] is False

    # The Cognito login was provisioned administratively, stamped with the WABA, with a permanent
    # password (so it is CONFIRMED and CUSTOM_AUTH works). No SignUp anywhere.
    assert len(cog.created) == 1
    attrs = {a['Name']: a['Value'] for a in cog.created[0]['UserAttributes']}
    assert attrs['custom:partner_waba_id']
    assert attrs['phone_number'] == E164
    assert cog.created[0]['MessageAction'] == 'SUPPRESS'
    assert len(cog.passwords) == 1 and cog.passwords[0]['Permanent'] is True

    # IT MUST NOT STAMP `custom:customer_id`, AND THAT IS THE POINT OF THIS ASSERTION.
    # The attribute is not in pool us-east-1_46ULYuukt's schema (measured 2026-10-02: the only
    # custom attribute is `custom:partner_waba_id`), so sending it would have Cognito reject the
    # whole AdminCreateUser call with InvalidParameterException. Session identity comes from the
    # Cognito `sub` via `customer_auth.customer_id_from_attributes` instead. The contact row above
    # is the customer RECORD, which is a different thing from the session's identity.
    assert 'custom:customer_id' not in attrs
    # Only attributes the pool can actually hold.
    assert set(attrs) <= {'phone_number', 'phone_number_verified', 'custom:partner_waba_id'}


def test_verify_of_existing_customer_reuses_the_identity(handler_env):
    h, fake, lam, cog = handler_env
    # The customer already exists - minted by the website profile save (a uuid id, not the
    # inbox's `wa{digits}`), so only the phone index can find it.
    fake.Table(CONTACTS_TABLE).put_item(
        Item={'id': 'c0ffee00-0000-5000-8000-000000000001',
              'contactId': 'c0ffee00-0000-5000-8000-000000000001',
              'phone': E164, 'phoneVerifiedAt': 111})
    cog.exists = True  # the Cognito user already exists too

    code = _issue_and_capture_code(h, lam)
    resp = h.handler(_event('verify', phone=RAW_PHONE, code=code), None)
    assert resp['statusCode'] == 200
    # No second contact was minted: every channel converges on the one row.
    assert fake.count(CONTACTS_TABLE) == 1
    # Provisioning ran idempotently as an attribute update, not a create.
    assert cog.created == []
    assert len(cog.updated) == 1


def test_verify_failures_are_all_one_opaque_outcome(handler_env):
    h, _fake, lam, _cog = handler_env
    _issue_and_capture_code(h, lam)
    wrong = h.handler(_event('verify', phone=RAW_PHONE, code='000000'), None)
    never = h.handler(_event('verify', phone='+919000000009', code='123456'), None)
    assert wrong['statusCode'] == never['statusCode'] == 401
    assert (json.loads(wrong['body'])['status']
            == json.loads(never['body'])['status'] == 'invalid_code')


def test_a_used_code_cannot_be_replayed(handler_env):
    h, _fake, lam, _cog = handler_env
    code = _issue_and_capture_code(h, lam)
    assert h.handler(_event('verify', phone=RAW_PHONE, code=code), None)['statusCode'] == 200
    replay = h.handler(_event('verify', phone=RAW_PHONE, code=code), None)
    assert replay['statusCode'] == 401
    assert json.loads(replay['body'])['status'] == 'invalid_code'


def test_verify_requires_a_code(handler_env):
    h, _fake, lam, _cog = handler_env
    resp = h.handler(_event('verify', phone=RAW_PHONE), None)
    assert resp['statusCode'] == 400
    assert json.loads(resp['body'])['error'] == 'CODE_REQUIRED'


def test_never_calls_cognito_signup(handler_env):
    """The browser must never provision a pool user; the pool is admin-create-only."""
    h, _fake, _lam, cog = handler_env
    # The fake has no sign_up, so a call would blow up; and the handler must make no such call.
    assert not hasattr(cog, 'sign_up')
    source = _HANDLER_PATH.read_text()
    # Guard against the CALL forms, not the prose. The docstring deliberately explains what the
    # handler does NOT do ("Nothing in this handler calls SignUp"), so a bare substring check
    # would flag its own documentation. Provisioning goes through admin_create_user only.
    assert '.sign_up(' not in source
    assert '"SignUp"' not in source and "'SignUp'" not in source
    assert 'admin_create_user' in source
