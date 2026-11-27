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

MAILBOX = 'wecare.digital.bw@gmail.com'
CHALLENGE_TTL = 300
RENEWAL_COOLDOWN = 60
MAX_VERIFY_ATTEMPTS = 3


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
    if any(response.get(key) for key in ('requiresPasswordChange', 'RequiresPasswordChange', 'isPasswordExpired', 'IsPasswordExpired')):
        raise ApolloAuthorizationRequired('Apollo account requires an interactive credential update')
    profile = provider.get_profile(token)
    email = str(profile.get('EmailId', profile.get('emailId', profile.get('userName', '')))).strip().lower()
    if email != MAILBOX:
        raise ApolloAuthorizationRequired('Apollo profile does not match the configured account')
    expires_at = _expiry_hint(token, now)
    if expires_at <= now + 30:
        raise ApolloAuthorizationRequired('Apollo issued an expired session')
    return {'stage': 'ready', 'token': token, 'expiresAt': expires_at,
            'lastRenewalAt': now, 'consumedMessageIds': []}


def advance_session(*, store, provider, gmail_get: Callable,
                    credentials: Callable, approved_sender: str, now: int) -> SessionResult:
    """Advance a leased, encrypted service-account session by one network stage.

    Store interface: read(), claim(now, lease_seconds)->lease or None,
    read_under_lease(lease), save(lease, record), release(lease).
    No token, OTP, upstream error body or password is returned by public_status.
    The caller must enforce customer/staff authentication before invoking this.
    """
    state = store.read() or {}
    if state.get('stage') == 'ready' and int(state.get('expiresAt', 0)) > now + 30:
        return SessionResult('ready', token=state['token'])
    if state.get('stage') == 'blocked':
        raise ApolloAuthorizationRequired('Apollo account requires administrator attention')
    if int(state.get('nextPollAt', 0)) > now:
        return SessionResult('renewing', retry_after=2)
    lease = store.claim(now=now, lease_seconds=25)
    if not lease:
        return SessionResult('renewing', retry_after=2)
    try:
        # Re-read after claiming. Another caller may have completed renewal.
        state = store.read_under_lease(lease) or {}
        if state.get('stage') == 'ready' and int(state.get('expiresAt', 0)) > now + 30:
            return SessionResult('ready', token=state['token'])
        if state.get('stage') == 'blocked':
            raise ApolloAuthorizationRequired('Apollo account requires administrator attention')
        if state.get('stage') == 'awaiting_otp' and now - int(state['requestedAt']) <= CHALLENGE_TTL:
            if int(state.get('nextPollAt', 0)) > now:
                return SessionResult('renewing', retry_after=2)
            code = find_apollo_otp(gmail_get, expected_mailbox=MAILBOX,
                approved_sender=approved_sender, requested_at_ms=int(state['requestedAt']) * 1000,
                now_ms=now * 1000, consumed_message_ids=frozenset(state.get('consumedMessageIds', [])))
            if code is None:
                store.save(lease, {**state, 'nextPollAt': now + 3})
                return SessionResult('renewing', retry_after=3)
            # Fence the consumed message before sending verification: an ambiguous
            # timeout must not cause concurrent verification or OTP replay.
            attempted = {**state, 'consumedMessageIds': [*state.get('consumedMessageIds', []), code.message_id],
                         'verifyAttempts': int(state.get('verifyAttempts', 0)) + 1,
                         'nextPollAt': now + 3}
            store.save(lease, attempted)
            result = provider.verify_otp(user_id=state['userId'], email=MAILBOX, otp=code.code)
            if _token(result):
                try:
                    ready = _verified_session(provider, result, now)
                except ApolloAuthorizationRequired:
                    store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                    raise
                store.save(lease, ready)
                return SessionResult('ready', token=ready['token'])
            if attempted['verifyAttempts'] >= MAX_VERIFY_ATTEMPTS:
                store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                raise ApolloAuthorizationRequired('Apollo OTP verification requires attention')
            return SessionResult('renewing', retry_after=3)
        last = int(state.get('lastRenewalAt', 0))
        if last and now - last < RENEWAL_COOLDOWN:
            return SessionResult('renewing', retry_after=RENEWAL_COOLDOWN - (now - last))
        attempts = int(state.get('challengeCount', 0)) + 1
        if attempts > 3:
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo renewal needs administrator attention')
        store.save(lease, {'stage': 'login_pending', 'lastRenewalAt': now, 'challengeCount': attempts})
        config = credentials()
        result = provider.login(login_payload(config['username'], config['password']))
        if any(result.get(key) for key in ('requiresPasswordChange', 'RequiresPasswordChange', 'isPasswordExpired', 'IsPasswordExpired')):
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo requires an interactive credential update')
        if _token(result):
            try:
                ready = _verified_session(provider, result, now)
            except ApolloAuthorizationRequired:
                store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
                raise
            store.save(lease, ready)
            return SessionResult('ready', token=ready['token'])
        error = result.get('errCode', result.get('ErrCode'))
        user_id = result.get('userId', result.get('UserId'))
        requires_otp = result.get('requiresOtp', result.get('RequiresOtp'))
        if error != 0 or not requires_otp or type(user_id) is not int or user_id <= 0:
            store.save(lease, {'stage': 'blocked', 'lastRenewalAt': now})
            raise ApolloAuthorizationRequired('Apollo account sign-in requires attention')
        # Save an in-flight marker first. If SendOtp times out, no second OTP is
        # sent automatically; the same challenge waits for delivery or expiry.
        pending = {'stage': 'awaiting_otp', 'userId': user_id, 'requestedAt': now,
                   'lastRenewalAt': now, 'nextPollAt': now + 3,
                   'verifyAttempts': 0, 'consumedMessageIds': [], 'challengeCount': attempts}
        store.save(lease, pending)
        provider.send_otp(MAILBOX)
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
        saved = str(current.get('token') or '')
        if current.get('stage') == 'ready' and saved and hmac.compare_digest(saved, rejected_token):
            store.save(lease, {'stage': 'expired', 'lastRenewalAt': int(current.get('lastRenewalAt', 0))})
            return True
        return False
    finally:
        store.release(lease)
