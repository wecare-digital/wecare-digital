"""On-demand Apollo login/OTP renewal policy. No scheduled keepalive or browser tokens.

The runtime supplies an encrypted, versioned state store, a credential resolver,
the fixed-origin provider client and the OAuth-authenticated Gmail transport.
Each call advances at most one network stage so an HTTP request does not sleep
waiting for mail. Store writes must be fenced by the claimed lease.
"""
from __future__ import annotations

import base64
import json
import hmac
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .gmail_otp import find_apollo_otp
from .apollo_client import ApolloUnavailable, ApolloSessionExpired

MAILBOX = 'wecare.digital.bw@gmail.com'
_INTERACTIVE = ('requiresCaptcha', 'RequiresCaptcha', 'captchaRequired', 'CaptchaRequired',
                'requiresPasswordChange', 'RequiresPasswordChange', 'isPasswordExpired', 'IsPasswordExpired')
CHALLENGE_TTL = 300
RENEWAL_COOLDOWN = 60
MAX_VERIFY_ATTEMPTS = 3
# Must exceed the owning Lambda runtime timeout (configure that at <=60s).
RENEWAL_LEASE_SECONDS = 90


class ApolloAuthorizationRequired(RuntimeError):
    """The provider account needs an administrator's attention."""


@dataclass(frozen=True)
class SessionResult:
    status: str
    retry_after: int = 0
    token: str = field(default='', repr=False)

    def public_status(self):
        # A provider session token is never a public/customer response field.
        return {'status': self.status, 'retryAfter': self.retry_after}


def login_payload(username: str, password: str) -> dict:
    """Match the portal's observed three-pass UTF-8/base64 transport encoding.

    This is provider wire encoding, not password encryption or secure custody.
    """
    if username.strip().lower() != MAILBOX or not password:
        raise ApolloAuthorizationRequired('Apollo account configuration requires attention')
    def encode(value):
        for _ in range(3):
            value = base64.b64encode(value.encode('utf-8')).decode('ascii')
        return value
    return {'userName': encode(username), 'password': encode(password)}


def _token(response):
    if not isinstance(response, Mapping):
        return ''
    value = response.get('ICUserToken', response.get('iCUserToken', response.get('icUserToken', '')))
    return value if isinstance(value, str) else ''


def _expiry_hint(token: str, now: int) -> int:
    """Cache hint only. Provider API authentication remains the authority.

    JWT payload decoding is not signature validation. Limit the cache to five
    minutes when expiry is absent, and at most one hour when the claim exists.
    A 401 must invalidate the stored session; it never triggers a booking retry.
    """
    try:
        part = token.split('.')[1]
        payload = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        expiry = int(payload['exp'])
        return min(expiry, now + 3600)
    except (ValueError, KeyError, IndexError, TypeError):
        return now + 300


def _verified_session(provider, response, now):
    token = _token(response)
    if not token:
        raise ApolloAuthorizationRequired('Apollo did not establish a session')
    # Credential-policy requirements must never be bypassed by an automation.
    if any(response.get(key) for key in _INTERACTIVE):
        raise ApolloAuthorizationRequired('Apollo account requires an interactive credential update')
    profile = provider.get_profile(token)
    if not isinstance(profile, Mapping):
        raise ApolloAuthorizationRequired('Apollo profile could not be verified')
    email = str(profile.get('EmailId', profile.get('emailId', profile.get('userName', '')))).strip().lower()
    if email != MAILBOX:
        raise ApolloAuthorizationRequired('Apollo profile does not match the configured account')
    expires_at = _expiry_hint(token, now)
    if expires_at <= now + 30:
        raise ApolloAuthorizationRequired('Apollo issued an expired session')
    return {'stage': 'ready', 'token': token, 'expiresAt': expires_at,
            'lastRenewalAt': now, 'consumedMessageIds': []}



def _valid_state(state):
    if not isinstance(state, Mapping):
        return False
    if not state:
        return True
    stage = state.get('stage')
    if stage not in {'ready', 'blocked', 'expired', 'login_pending', 'awaiting_otp', 'awaiting_profile'}:
        return False
    numeric = ('expiresAt', 'lastRenewalAt', 'nextPollAt', 'requestedAt', 'candidateAt', 'verifyAttempts', 'challengeCount')
    if any(key in state and (type(state[key]) is not int or state[key] < 0) for key in numeric):
        return False
    if stage == 'awaiting_otp':
        if type(state.get('userId')) is not int or state['userId'] <= 0 or not state.get('requestedAt'):
            return False
        consumed = state.get('consumedMessageIds', [])
        if not isinstance(consumed, list) or len(consumed) > MAX_VERIFY_ATTEMPTS or any(not isinstance(x, str) for x in consumed):
            return False
    if stage in {'ready', 'awaiting_profile'}:
        if not isinstance(state.get('token'), str) or not state['token'] or not state.get('expiresAt'):
            return False
    if stage == 'awaiting_profile' and not state.get('candidateAt'):
        return False
    return True


def _complete_candidate(store, lease, provider, candidate, now):
    if candidate['expiresAt'] <= now + 30 or now - candidate['candidateAt'] > CHALLENGE_TTL:
        store.save(lease, {'stage': 'expired', 'lastRenewalAt': candidate.get('lastRenewalAt', 0),
                           'challengeCount': candidate.get('challengeCount', 1)})
        return SessionResult('renewing', retry_after=3)
    try:
        ready = _verified_session(provider, {'ICUserToken': candidate['token']}, now)
    except ApolloSessionExpired:
        store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
        raise ApolloAuthorizationRequired('Apollo rejected the new session; administrator attention required') from None
    except ApolloUnavailable:
        # Keep the encrypted candidate, not a usable public session. The next
        # request retries only GetProfile, never Login, SendOtp or VerifyOtp.
        store.save(lease, {**candidate, 'nextPollAt': now + 3})
        return SessionResult('renewing', retry_after=3)
    except ApolloAuthorizationRequired:
        store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
        raise
    store.save(lease, ready)
    return SessionResult('ready', token=ready['token'])


def _establish_candidate(store, lease, provider, result, state, now):
    if any(result.get(key) for key in _INTERACTIVE):
        store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
        raise ApolloAuthorizationRequired('Apollo requires an interactive credential update')
    candidate = {'stage': 'awaiting_profile', 'token': _token(result),
                 'expiresAt': _expiry_hint(_token(result), now), 'candidateAt': now,
                 'lastRenewalAt': state.get('lastRenewalAt', now),
                 'challengeCount': state.get('challengeCount', 1), 'nextPollAt': now}
    # Persist before GetProfile so a network error cannot discard a verified token.
    store.save(lease, candidate)
    return _complete_candidate(store, lease, provider, candidate, now)


def advance_session(*, store, provider, gmail_get: Callable,
                    credentials: Callable, approved_sender: str, now: int) -> SessionResult:
    """Advance a leased, encrypted service-account session by one network stage.

    Store interface: read(), claim(now, lease_seconds)->lease or None,
    read_under_lease(lease), save(lease, record), release(lease).
    The caller must authenticate the customer/staff request before invoking this.
    """
    state = store.read() or {}
    if _valid_state(state):
        if state.get('stage') == 'ready' and state.get('expiresAt', 0) > now + 30:
            return SessionResult('ready', token=state['token'])
        if state.get('stage') == 'blocked':
            raise ApolloAuthorizationRequired('Apollo account requires administrator attention')
        if state.get('nextPollAt', 0) > now:
            return SessionResult('renewing', retry_after=2)
    lease = store.claim(now=now, lease_seconds=RENEWAL_LEASE_SECONDS)
    if not lease:
        return SessionResult('renewing', retry_after=2)
    try:
        state = store.read_under_lease(lease) or {}
        if not _valid_state(state):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo saved state requires administrator attention')
        if state.get('stage') == 'ready' and state.get('expiresAt', 0) > now + 30:
            return SessionResult('ready', token=state['token'])
        if state.get('stage') == 'blocked':
            raise ApolloAuthorizationRequired('Apollo account requires administrator attention')
        if state.get('nextPollAt', 0) > now:
            return SessionResult('renewing', retry_after=2)
        if state.get('stage') == 'awaiting_profile':
            return _complete_candidate(store, lease, provider, state, now)
        if state.get('stage') == 'ready':
            # A local cache deadline is not proof that the provider session ended.
            # Check the existing token before sending another login email.
            try:
                profile = provider.get_profile(state['token'])
            except ApolloSessionExpired:
                state = {'stage': 'expired', 'lastRenewalAt': state.get('lastRenewalAt', 0)}
                store.save(lease, state)
            except ApolloUnavailable:
                store.save(lease, {**state, 'nextPollAt': now + 3})
                return SessionResult('renewing', retry_after=3)
            else:
                email = str(profile.get('EmailId', profile.get('emailId', profile.get('userName', '')))).strip().lower() if isinstance(profile, Mapping) else ''
                if email != MAILBOX:
                    store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                    raise ApolloAuthorizationRequired('Apollo profile does not match the configured account')
                refreshed = {**state, 'expiresAt': now + 300, 'nextPollAt': 0}
                store.save(lease, refreshed)
                return SessionResult('ready', token=refreshed['token'])
        if state.get('stage') == 'awaiting_otp' and 0 <= now - state['requestedAt'] <= CHALLENGE_TTL:
            if state.get('verifyAttempts', 0) >= MAX_VERIFY_ATTEMPTS:
                store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                raise ApolloAuthorizationRequired('Apollo OTP verification requires attention')
            code = find_apollo_otp(gmail_get, expected_mailbox=MAILBOX,
                approved_sender=approved_sender, requested_at_ms=state['requestedAt'] * 1000,
                now_ms=now * 1000, consumed_message_ids=frozenset(state.get('consumedMessageIds', [])))
            if code is None:
                store.save(lease, {**state, 'nextPollAt': now + 3})
                return SessionResult('renewing', retry_after=3)
            attempted = {**state, 'consumedMessageIds': [*state.get('consumedMessageIds', []), code.message_id],
                         'verifyAttempts': state.get('verifyAttempts', 0) + 1, 'nextPollAt': now + 3}
            store.save(lease, attempted)
            result = provider.verify_otp(user_id=state['userId'], email=MAILBOX, otp=code.code)
            if isinstance(result, Mapping) and any(result.get(key) for key in _INTERACTIVE):
                store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                raise ApolloAuthorizationRequired('Apollo requires interactive verification')
            if _token(result):
                return _establish_candidate(store, lease, provider, result, state, now)
            if attempted['verifyAttempts'] >= MAX_VERIFY_ATTEMPTS:
                store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                raise ApolloAuthorizationRequired('Apollo OTP verification requires attention')
            return SessionResult('renewing', retry_after=3)
        last = state.get('lastRenewalAt', 0)
        if last and now - last < RENEWAL_COOLDOWN:
            return SessionResult('renewing', retry_after=RENEWAL_COOLDOWN - (now - last))
        attempts = state.get('challengeCount', 0) + 1
        if attempts > 3:
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo renewal needs administrator attention')
        login_state = {'stage': 'login_pending', 'lastRenewalAt': now, 'challengeCount': attempts}
        store.save(lease, login_state)
        config = credentials()
        result = provider.login(login_payload(config['username'], config['password']))
        if not isinstance(result, Mapping):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo sign-in response requires attention')
        if any(result.get(key) for key in _INTERACTIVE):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo requires an interactive credential update')
        if _token(result):
            return _establish_candidate(store, lease, provider, result, login_state, now)
        error = result.get('errCode', result.get('ErrCode'))
        user_id = result.get('userId', result.get('UserId'))
        requires_otp = result.get('requiresOtp', result.get('RequiresOtp'))
        if error != 0 or not requires_otp or type(user_id) is not int or user_id <= 0:
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo account sign-in requires attention')
        pending = {'stage': 'awaiting_otp', 'userId': user_id, 'requestedAt': now,
                   'lastRenewalAt': now, 'nextPollAt': now + 3,
                   'verifyAttempts': 0, 'consumedMessageIds': [], 'challengeCount': attempts}
        store.save(lease, pending)
        sent = provider.send_otp(MAILBOX)
        if isinstance(sent, Mapping) and any(sent.get(key) for key in _INTERACTIVE):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo requires interactive verification')
        return SessionResult('renewing', retry_after=3)
    finally:
        store.release(lease)


def invalidate_session(store, rejected_token: str, *, now: int) -> bool:
    """Invalidate a provider-rejected cached session without erasing a newer one."""
    lease = store.claim(now=now, lease_seconds=10)
    if not lease:
        return False
    try:
        current = store.read_under_lease(lease) or {}
        if not _valid_state(current):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            return False
        saved = str(current.get('token') or '')
        if current.get('stage') == 'ready' and saved and hmac.compare_digest(saved, rejected_token):
            store.save(lease, {'stage': 'expired', 'lastRenewalAt': int(current.get('lastRenewalAt', 0))})
            return True
        return False
    finally:
        store.release(lease)
