"""Encrypted customer OAuth custody and resource-bound token helpers."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from customer_oauth_config import *
from customer_oauth_config import _CLIENTS

def aws(service: str):
    if service not in _CLIENTS:
        import boto3
        _CLIENTS[service] = boto3.resource('dynamodb', region_name='us-east-1') if service == 'dynamodb' else boto3.client(service, region_name='us-east-1')
    return _CLIENTS[service]

class Store:
    """IAM limits this service to mcp:commerce:* custody rows."""

    def table(self):
        return aws('dynamodb').Table(os.environ.get('CUSTOMER_SESSIONS_TABLE', 'stack-wecare-digital-CustomerSessionsTable'))

    def get(self, key: str) -> dict | None:
        if not key.startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        row = self.table().get_item(Key={'sidHash': key}, ConsistentRead=True).get('Item')
        return row if row and row.get('absoluteExpiresAt', 0) > int(time.time()) else None

    def put(self, row: dict) -> None:
        from boto3.dynamodb.conditions import Attr
        if not row.get('sidHash', '').startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        self.table().put_item(Item=row, ConditionExpression=Attr('sidHash').not_exists())

    def take(self, key: str) -> dict | None:
        from boto3.dynamodb.conditions import Attr
        if not key.startswith(PREFIX):
            raise AuthError('Invalid session namespace')
        try:
            return self.table().delete_item(Key={'sidHash': key}, ReturnValues='ALL_OLD', ConditionExpression=Attr('sidHash').exists() & Attr('absoluteExpiresAt').gt(int(time.time()))).get('Attributes')
        except self.table().meta.client.exceptions.ConditionalCheckFailedException:
            return None
STORE = Store()

def capsule(data: dict, client_id: str, key: str) -> str:
    context = {'app': 'wecare-customer-commerce', 'resource': resource(), 'client': client_id, 'record': key}
    plain = json.dumps(data).encode()
    if len(plain) > 32768:
        raise AuthError('Custody payload too large')
    if len(plain) > 4096:
        parts = [plain[index:index + 3000] for index in range(0, len(plain), 3000)]
        encrypted = [base64.b64encode(aws('kms').encrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'], EncryptionContext={**context, 'part': str(index), 'parts': str(len(parts))}, Plaintext=part)['CiphertextBlob']).decode() for index, part in enumerate(parts)]
        return 'kms2:' + json.dumps(encrypted, separators=(',', ':'))
    result = aws('kms').encrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'], EncryptionContext=context, Plaintext=plain)
    return base64.b64encode(result['CiphertextBlob']).decode()

def uncapsule(cipher: str, client_id: str, key: str) -> dict:
    context = {'app': 'wecare-customer-commerce', 'resource': resource(), 'client': client_id, 'record': key}
    if cipher.startswith('kms2:'):
        parts = json.loads(cipher[5:])
        if not isinstance(parts, list) or not 2 <= len(parts) <= 11 or any((not isinstance(part, str) or len(part) > 12000 for part in parts)):
            raise AuthError('Invalid custody parts')
        plain = b''.join((aws('kms').decrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'], EncryptionContext={**context, 'part': str(index), 'parts': str(len(parts))}, CiphertextBlob=base64.b64decode(part, validate=True))['Plaintext'] for index, part in enumerate(parts)))
        if len(plain) > 32768:
            raise AuthError('Custody payload too large')
    else:
        plain = aws('kms').decrypt(KeyId=os.environ['CUSTOMER_SESSION_KMS_KEY_ID'], EncryptionContext=context, CiphertextBlob=base64.b64decode(cipher, validate=True))['Plaintext']
    value = json.loads(plain)
    if not isinstance(value, dict):
        raise AuthError('Invalid custody')
    return value

def checked_cognito(auth: dict) -> tuple[dict, str]:
    token = auth.get('AccessToken', '')
    if not isinstance(token, str) or not token or (not auth.get('RefreshToken')):
        raise AuthError('Incomplete authentication')
    try:
        user = aws('cognito-idp').get_user(AccessToken=token)
    except Exception as error:
        code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        if code in {'NotAuthorizedException', 'UserNotFoundException'}:
            raise AuthError('Customer session expired or revoked') from None
        raise
    attributes = {item['Name']: item['Value'] for item in user.get('UserAttributes', [])}
    try:
        encoded = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, IndexError, json.JSONDecodeError):
        raise AuthError('Invalid customer token') from None
    if claims.get('iss') != f'https://cognito-idp.us-east-1.amazonaws.com/{CUSTOMER_POOL}' or claims.get('client_id') != CUSTOMER_CLIENT or claims.get('token_use') != 'access' or (not attributes.get('sub')) or (claims.get('sub') != attributes['sub']):
        raise AuthError('Customer authentication required')
    return (attributes, attributes['sub'])

def bound(row: dict | None, params: dict) -> dict:
    if not row or row.get('client') != params.get('client_id') or row.get('resource') != params.get('resource'):
        raise AuthError('Invalid grant')
    client(row['client'])
    return row

def issue(grant: dict, auth: dict) -> dict:
    now = int(time.time())
    lifetime = min(int(auth.get('ExpiresIn', 3600)), 3600, grant['absoluteExpiresAt'] - now)
    if lifetime <= 0:
        raise AuthError('Expired session')
    access = 'wca_' + secrets.token_urlsafe(32)
    refresh = 'wcr_' + secrets.token_urlsafe(32)
    for kind, token, expiry in (('access', access, now + lifetime), ('refresh', refresh, grant['absoluteExpiresAt'])):
        STORE.put({'sidHash': row_key(kind, token), 'kind': kind, 'client': grant['client'], 'resource': resource(), 'grant': grant['sidHash'], 'scope': grant['scope'], 'absoluteExpiresAt': expiry})
    return {'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': lifetime, 'scope': grant['scope']}

def token_exchange(params: dict) -> dict:
    client(params.get('client_id', ''))
    if params.get('resource') != resource():
        raise AuthError('Invalid resource')
    if params.get('grant_type') == 'authorization_code':
        if set(params) != {'grant_type', 'client_id', 'resource', 'code', 'redirect_uri', 'code_verifier'}:
            raise AuthError('Invalid token request')
        verifier = params['code_verifier']
        if not re.fullmatch('[A-Za-z0-9._~-]{43,128}', verifier):
            raise AuthError('Invalid PKCE')
        key = row_key('code', params['code'])
        row = bound(STORE.get(key), params)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        if row.get('redirect') != params['redirect_uri'] or not hmac.compare_digest(row['challenge'], challenge):
            raise AuthError('Invalid grant')
        if STORE.take(key) is None:
            raise AuthError('Authorization code already used')
        grant = STORE.get(row['grant'])
        if not grant:
            raise AuthError('Expired session')
        cognito = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
        checked_cognito(cognito)
        return issue(grant, cognito)
    if params.get('grant_type') == 'refresh_token':
        if set(params) != {'grant_type', 'client_id', 'resource', 'refresh_token'}:
            raise AuthError('Invalid refresh request')
        key = row_key('refresh', params['refresh_token'])
        row = bound(STORE.get(key), params)
        if STORE.take(key) is None:
            raise AuthError('Refresh token already used')
        grant = STORE.take(row['grant'])
        if not grant:
            raise AuthError('Expired session')
        previous = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
        result = aws('cognito-idp').initiate_auth(ClientId=CUSTOMER_CLIENT, AuthFlow='REFRESH_TOKEN_AUTH', AuthParameters={'REFRESH_TOKEN': previous['RefreshToken']})
        cognito = {**result.get('AuthenticationResult', {}), 'RefreshToken': previous['RefreshToken']}
        _, subject = checked_cognito(cognito)
        if subject != grant['subject']:
            raise AuthError('Customer changed')
        grant['cipher'] = capsule(cognito, grant['client'], grant['sidHash'])
        STORE.put(grant)
        return issue(grant, cognito)
    raise AuthError('Unsupported grant')

def customer_event(event: dict, scope: str) -> dict:
    headers = {str(key).lower(): str(value) for key, value in (event.get('headers') or {}).items()}
    authorization = headers.get('authorization', '')
    if not authorization.startswith('Bearer wca_'):
        raise AuthError('Resource-bound customer session required')
    row = STORE.get(row_key('access', authorization[7:]))
    if not row or row.get('resource') != resource() or scope not in row.get('scope', '').split():
        raise AuthError('Customer scope required')
    client(row['client'])
    grant = STORE.get(row['grant'])
    if not grant or grant.get('resource') != resource() or grant.get('client') != row['client']:
        raise AuthError('Revoked customer session')
    cognito = uncapsule(grant['cipher'], grant['client'], grant['sidHash'])
    _, subject = checked_cognito(cognito)
    if subject != grant['subject']:
        raise AuthError('Customer changed')
    return {**event, 'headers': {**headers, 'authorization': 'Bearer ' + cognito['AccessToken']}}
