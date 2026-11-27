"""Synthetic provider/Gmail fixtures. No external authentication or booking writes."""
import base64
import copy
import json
import pytest
from lambda_utils.arogya.apollo_session import (
    MAILBOX, ApolloAuthorizationRequired, SessionResult, advance_session, login_payload,
)

NOW = 1800000000
SENDER = 'test-otp@apollohospitals.com'


def token(exp=NOW + 3600):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return 'synthetic.' + payload + '.signature'


class Store:
    def __init__(self, state=None, busy=False):
        self.state = state or {}
        self.busy = busy
        self.released = []
    def read(self): return copy.deepcopy(self.state)
    def read_under_lease(self, lease): return self.read()
    def claim(self, **kwargs): return None if self.busy else 'synthetic-lease'
    def save(self, lease, state): self.state = copy.deepcopy(state)
    def release(self, lease): self.released.append(lease)


class Provider:
    def __init__(self):
        self.calls = []
        self.verified = {'errCode': 0, 'ICUserToken': token()}
        self.profile = {'EmailId': MAILBOX}
        self.login_result = {'errCode': 0, 'requiresOtp': True, 'userId': 12}
    def login(self, payload):
        self.calls.append('login')
        assert set(payload) == {'userName', 'password'}
        return self.login_result
    def send_otp(self, email):
        assert email == MAILBOX
        self.calls.append('send')
    def verify_otp(self, **kwargs):
        assert kwargs == {'user_id': 12, 'email': MAILBOX, 'otp': '123456'}
        self.calls.append('verify')
        return self.verified
    def get_profile(self, access):
        assert access == token()
        self.calls.append('profile')
        return self.profile


def gmail(path, params):
    if path.endswith('/profile'): return {'emailAddress': MAILBOX}
    if path.endswith('/messages'): return {'messages': [{'id': 'synthetic-email'}]}
    return {'internalDate': str((NOW + 1) * 1000), 'payload': {
        'mimeType': 'text/plain',
        'headers': [{'name': 'From', 'value': SENDER}, {'name': 'To', 'value': MAILBOX}],
        'body': {'data': base64.urlsafe_b64encode(b'Your OTP is 123456').decode()}}}


def advance(store, provider, now=NOW, transport=gmail):
    return advance_session(store=store, provider=provider, gmail_get=transport,
        credentials=lambda: {'username': MAILBOX, 'password': 'synthetic-fixture'},
        approved_sender=SENDER, now=now)


def test_login_encoding_matches_three_base64_passes_without_password_custody():
    payload = login_payload(MAILBOX, 'synthetic-fixture')
    value = payload['password']
    for _ in range(3): value = base64.b64decode(value).decode()
    assert value == 'synthetic-fixture'
    with pytest.raises(ApolloAuthorizationRequired): login_payload('other@gmail.com', 'fixture')


def test_valid_session_is_reused_without_any_provider_or_gmail_call():
    store = Store({'stage': 'ready', 'token': token(), 'expiresAt': NOW + 3600})
    provider = Provider()
    result = advance(store, provider, transport=lambda *_: pytest.fail('must not read Gmail'))
    assert result.status == 'ready'
    assert result.token == token()
    assert 'token' not in result.public_status()
    assert token() not in repr(result)
    assert provider.calls == []


def test_renewal_advances_once_per_request_and_reuses_the_verified_session():
    store, provider = Store(), Provider()
    assert advance(store, provider).public_status() == {'status': 'renewing', 'retryAfter': 3}
    assert provider.calls == ['login', 'send']
    assert store.state['stage'] == 'awaiting_otp'
    assert advance(store, provider, NOW + 1).status == 'renewing'
    assert provider.calls == ['login', 'send']
    result = advance(store, provider, NOW + 3)
    assert result.status == 'ready'
    assert provider.calls == ['login', 'send', 'verify', 'profile']
    assert store.state['stage'] == 'ready'
    assert 'password' not in store.state and 'otp' not in store.state
    assert advance(store, provider, NOW + 4).status == 'ready'
    assert len(provider.calls) == 4


def test_busy_lease_never_sends_another_challenge():
    store, provider = Store(busy=True), Provider()
    assert advance(store, provider).status == 'renewing'
    assert provider.calls == []


def test_missing_email_does_not_sleep_or_resend_otp():
    store, provider = Store(), Provider()
    advance(store, provider)
    def no_mail(path, params):
        return {'emailAddress': MAILBOX} if path.endswith('/profile') else {'messages': []}
    assert advance(store, provider, NOW + 3, no_mail).retry_after == 3
    assert provider.calls == ['login', 'send']


def test_password_update_policy_stops_automated_sign_in():
    store, provider = Store(), Provider()
    provider.login_result['requiresPasswordChange'] = True
    with pytest.raises(ApolloAuthorizationRequired): advance(store, provider)
    assert store.state['stage'] == 'blocked'
    assert provider.calls == ['login']
    assert store.released == ['synthetic-lease']


def test_profile_mismatch_never_persists_a_ready_token():
    store, provider = Store(), Provider()
    advance(store, provider)
    provider.profile = {'EmailId': 'other@gmail.com'}
    with pytest.raises(ApolloAuthorizationRequired): advance(store, provider, NOW + 3)
    assert store.state['stage'] == 'blocked'
    assert 'token' not in store.state


def test_consumed_code_is_not_replayed_after_a_verification_refusal():
    store, provider = Store(), Provider()
    advance(store, provider)
    provider.verified = {'errCode': 1}
    assert advance(store, provider, NOW + 3).status == 'renewing'
    assert advance(store, provider, NOW + 6).status == 'renewing'
    assert provider.calls.count('verify') == 1


def test_ambiguous_send_timeout_does_not_immediately_send_another_code():
    store, provider = Store(), Provider()
    def timeout(email): raise TimeoutError('synthetic upstream')
    provider.send_otp = timeout
    with pytest.raises(TimeoutError): advance(store, provider)
    assert store.state['stage'] == 'awaiting_otp'
    assert advance(store, provider, NOW + 1).status == 'renewing'
    assert provider.calls == ['login']


def test_repeated_challenge_timeouts_eventually_require_admin_attention():
    store = Store({'stage': 'awaiting_otp', 'requestedAt': NOW - 400,
                   'lastRenewalAt': NOW - 400, 'challengeCount': 3})
    provider = Provider()
    with pytest.raises(ApolloAuthorizationRequired): advance(store, provider)
    assert provider.calls == []
    assert store.state['stage'] == 'blocked'


def test_stale_401_cannot_invalidate_a_newly_renewed_session():
    from lambda_utils.arogya.apollo_session import invalidate_session
    store = Store({'stage': 'ready', 'token': 'new-token', 'expiresAt': NOW + 3600})
    assert not invalidate_session(store, 'old-token', now=NOW)
    assert store.state['token'] == 'new-token'
    assert invalidate_session(store, 'new-token', now=NOW)
    assert store.state['stage'] == 'expired'
    assert 'token' not in store.state


@pytest.mark.parametrize('record', [
    {'stage': 'awaiting_otp'},
    {'stage': 'awaiting_otp', 'requestedAt': 'broken', 'userId': 12},
    {'stage': 'ready', 'expiresAt': NOW + 1000},
    {'stage': 'unknown'},
])
def test_malformed_saved_state_is_quarantined_without_a_crash_loop(record):
    store, provider = Store(record), Provider()
    with pytest.raises(ApolloAuthorizationRequired): advance(store, provider)
    assert store.state['stage'] == 'blocked'
    assert provider.calls == []
    assert store.released == ['synthetic-lease']


def test_profile_timeout_preserves_candidate_and_retries_no_other_auth_stage():
    from lambda_utils.arogya.apollo_client import ApolloUnavailable
    store, provider = Store(), Provider()
    advance(store, provider)
    original = provider.get_profile
    attempts = []
    def get_profile(access):
        attempts.append(access)
        if len(attempts) == 1: raise ApolloUnavailable('synthetic network failure')
        return original(access)
    provider.get_profile = get_profile
    assert advance(store, provider, NOW + 3).status == 'renewing'
    assert store.state['stage'] == 'awaiting_profile'
    assert store.state['token'] == token()
    assert advance(store, provider, NOW + 6).status == 'ready'
    assert len(attempts) == 2
    assert provider.calls.count('login') == 1
    assert provider.calls.count('send') == 1
    assert provider.calls.count('verify') == 1
