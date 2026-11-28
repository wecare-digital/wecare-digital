"""Explicitly bound, verified Google Gmail grant for Arogya's provider runtime.

Only the deployment-selected staff grant is accessed. There is no scan, caller-selected
owner, generic Gmail proxy or copy of a staff refresh token. The refresh fence is the
same one used by the retired workspace service, so concurrent refreshes cannot overwrite a newer grant.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from botocore.exceptions import ClientError
from .gmail_otp import GmailApi, MailboxAccessRequired, GmailReadUnavailable
from .apollo_session import MAILBOX

PROVIDER = 'google-gmail-apollo'
SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise GmailReadUnavailable('Google OAuth redirect refused')


def _refresh(client_id, client_secret, refresh_token):
    request = urllib.request.Request(TOKEN_ENDPOINT, method='POST',
        data=urllib.parse.urlencode({'grant_type': 'refresh_token', 'client_id': client_id,
            'client_secret': client_secret, 'refresh_token': refresh_token}).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=5) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise GmailReadUnavailable('Google OAuth response exceeded limit')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        if error.code in (400, 401, 403):
            raise MailboxAccessRequired('Google OAuth grant requires staff consent') from None
        raise GmailReadUnavailable('Google OAuth temporarily unavailable') from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise GmailReadUnavailable('Google OAuth temporarily unavailable') from None


def _scope_ok(value):
    return isinstance(value, str) and set(value.split()) == {SCOPE}


class VerifiedGmailGrant:
    def __init__(self, table, kms, *, key_arn, owner, oauth_config, clock=time.time, refresh=_refresh):
        if not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise MailboxAccessRequired('Explicit Apollo service grant binding required')
        self.table, self.kms, self.key_arn, self.owner = table, kms, key_arn, owner
        self.key = {'pk': 'connection:' + owner + ':' + PROVIDER}
        self.context = {'purpose': 'workspace-mcp', 'owner': owner, 'provider': PROVIDER}
        self.oauth_config, self.clock, self.refresh = oauth_config, clock, refresh

    def verified_row(self):
        row = self.table.get_item(Key=self.key, ConsistentRead=True).get('Item', {})
        if (row.get('owner') != self.owner or row.get('provider') != PROVIDER
                or row.get('status') != 'verified' or row.get('hasRefreshToken') is not True
                or not row.get('cipher') or not row.get('lastVerifiedAt')):
            raise MailboxAccessRequired('Verified Apollo mailbox grant required')
        return row

    def _tokens(self, row):
        value = json.loads(self.kms.decrypt(KeyId=self.key_arn, CiphertextBlob=bytes(row['cipher']),
            EncryptionContext=self.context)['Plaintext'])
        if (not isinstance(value, dict) or not _scope_ok(value.get('scope'))
                or not isinstance(value.get('access_token'), str) or not value['access_token']
                or not isinstance(value.get('refresh_token'), str) or not value['refresh_token']):
            raise MailboxAccessRequired('Reconnect the approved read-only Apollo mailbox')
        return value

    def _validated_client(self, tokens):
        config = self.oauth_config()
        client_id, client_secret = config.get('client_id'), config.get('client_secret')
        if (not isinstance(client_id, str) or not client_id.endswith('.apps.googleusercontent.com')
                or not isinstance(client_secret, str) or not client_secret
                or tokens.get('_oauth_client_id') != client_id):
            raise MailboxAccessRequired('Apollo OAuth client configuration mismatch')
        return client_id, client_secret

    def access_token(self):
        row = self.verified_row()
        tokens = self._tokens(row)
        now = int(self.clock())
        if int(row.get('expiresAt', 0)) > now + 60:
            return tokens['access_token']
        lease = secrets.token_hex(16)
        try:
            self.table.update_item(Key=self.key,
                UpdateExpression='SET refreshLockUntil = :until, refreshLease = :lease',
                ConditionExpression='attribute_exists(pk) AND #s = :verified AND (attribute_not_exists(refreshLockUntil) OR refreshLockUntil < :now)',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':until': now + 30, ':lease': lease, ':now': now, ':verified': 'verified'})
        except ClientError:
            raise GmailReadUnavailable('Google OAuth refresh is in progress') from None
        try:
            row = self.verified_row()
            tokens = self._tokens(row)
            if int(row.get('expiresAt', 0)) > int(self.clock()) + 60:
                return tokens['access_token']
            client_id, client_secret = self._validated_client(tokens)
            response = self.refresh(client_id, client_secret, tokens['refresh_token'])
            if not isinstance(response, dict):
                raise GmailReadUnavailable('Google OAuth response invalid')
            access = response.get('access_token')
            lifetime = response.get('expires_in')
            scope = response.get('scope', tokens['scope'])
            refresh_token = response.get('refresh_token', tokens['refresh_token'])
            if (not isinstance(access, str) or not access or type(lifetime) is not int
                    or not 60 < lifetime <= 86400 or not _scope_ok(scope)
                    or not isinstance(refresh_token, str) or not refresh_token):
                raise MailboxAccessRequired('Google OAuth grant requires renewed consent')
            # Persist only recognized OAuth fields and the original client identity.
            refreshed = {'access_token': access, 'refresh_token': refresh_token,
                'scope': scope, 'token_type': 'Bearer', 'expires_in': lifetime,
                '_oauth_client_id': client_id}
            raw = json.dumps(refreshed, separators=(',', ':')).encode()
            if len(raw) > 4096:
                raise GmailReadUnavailable('Google OAuth custody record exceeded limit')
            cipher = self.kms.encrypt(KeyId=self.key_arn, Plaintext=raw,
                EncryptionContext=self.context)['CiphertextBlob']
            current = int(self.clock())
            try:
                self.table.update_item(Key=self.key,
                    UpdateExpression='SET cipher = :cipher, expiresAt = :expiry, hasRefreshToken = :refresh',
                    ConditionExpression='refreshLease = :lease AND refreshLockUntil > :now AND #s = :verified',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':cipher': cipher, ':expiry': current + lifetime,
                        ':refresh': True, ':lease': lease, ':now': current, ':verified': 'verified'})
            except ClientError:
                raise GmailReadUnavailable('Google OAuth refresh lease expired') from None
            return access
        finally:
            try:
                self.table.update_item(Key=self.key,
                    UpdateExpression='REMOVE refreshLockUntil, refreshLease',
                    ConditionExpression='refreshLease = :lease',
                    ExpressionAttributeValues={':lease': lease})
            except ClientError:
                pass

    def transport(self):
        # One token per bounded provider step, not one decrypt/refresh for every message.
        access = self.access_token()
        return GmailApi(lambda: access)

    def verify_mailbox(self, transport=None):
        transport = transport or self.transport()
        profile = transport('/gmail/v1/users/me/profile', {})
        if str(profile.get('emailAddress', '')).lower() != MAILBOX:
            raise MailboxAccessRequired('Google OAuth mailbox does not match Apollo')
        return transport
