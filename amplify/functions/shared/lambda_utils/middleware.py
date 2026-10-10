"""
Auth enforcement middleware for Lambda handlers. STAFF pool only.

Usage:
    from lambda_utils.middleware import require_auth

    def handler(event, context):
        auth_result = require_auth(event, required_role='Viewer')
        if auth_result is not None:
            return auth_result  # 401/403 response
        # ... proceed with handler logic

What this gate asserts, and what it deliberately does not
---------------------------------------------------------
Three things, all of which have to hold:

1. The token is live — `GetUser` against Cognito.
2. The token was issued by the STAFF pool — `staff_pool_issuer()`. Step 1 does NOT
   establish this: `GetUser` takes only a token and resolves it against whichever pool
   issued it, so a customer-pool token used to pass here. See `_unverified_issuer`.
3. The token was minted by the STAFF APP CLIENT — `STAFF_APP_CLIENT_ID`. Step 2 narrows
   the pool but not the client within it, and an app client is the unit that decides
   which auth flows, scopes and token lifetimes apply. See `_unverified_clients`.
4. The principal holds a staff group that is in `ROLE_HIERARCHY`. There is **no default
   role**. An ungrouped principal, a `Partner`-only principal, and a group lookup that
   failed are all refused rather than treated as `Viewer`.

NOT for customer sessions. A customer token is refused here by design; customer-serving
routes authorise through `lambda_utils.customer_auth` (or, in `core/secure-files`, its
in-handler `_customer_identity`), which pins the CUSTOMER pool and then checks resource
ownership. Reaching for `require_auth` on a customer route is how a customer silently
became a staff Viewer.

Every call site should pass `required_role` explicitly, including `'Viewer'` for a
read-only route: with the default gone, `required_role=None` has nothing to check.
"""

import base64
import os
import json
import boto3
from typing import Any, Dict, Optional, Set

from lambda_utils.response import cors_response, extract_origin
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

cognito = boto3.client('cognito-idp', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID', 'us-east-1_cSx0RHCIR')
STAFF_POOL_REGION = os.environ.get('AWS_REGION', 'us-east-1')

ROLE_HIERARCHY = {'Admin': 3, 'Operator': 2, 'Viewer': 1}


def staff_pool_issuer() -> str:
    """The `iss` claim a STAFF token must carry.

    Derived from `USER_POOL_ID` rather than kept as a second literal, so overriding the
    pool moves the pin with it instead of leaving a pin that points at the old pool.
    Read per call for the same reason: `USER_POOL_ID` is a module global that tests and
    a future loader can both legitimately replace.

    Same shape as `lambda_utils.customer_auth.CUSTOMER_POOL_ISSUER`, and deliberately a
    DIFFERENT pool: keeping staff and customer apart is the whole point.
    """
    return f'https://cognito-idp.{STAFF_POOL_REGION}.amazonaws.com/{USER_POOL_ID}'


#: The issuer for the default pool. Convenience for callers and tests; the gate in
#: `require_auth` reads `staff_pool_issuer()` so a pool override is honoured.
STAFF_POOL_ISSUER = staff_pool_issuer()

#: The ONE app client on the staff pool. An identifier, not a secret - the same public
#: value `amplify/auth/resource.ts` declares as `userPoolClientId`, `README.md` records as
#: the App Client, `shared/config.ts` holds as `COGNITO_CONFIG.APP_CLIENT_ID`, and the
#: Amplify branch environment ships to the browser as `NEXT_PUBLIC_COGNITO_CLIENT_ID`.
#:
#: A LITERAL rather than an env read, deliberately, and on the precedent of
#: `ai/workspace-mcp/handler.py:31` (`STAFF_CLIENT`), which already pins exactly this value
#: alongside its issuer check. A new env var would make the pin optional on any function
#: whose environment was not updated, i.e. would ship a pin that is absent where it is most
#: needed. `USER_POOL_ID` is env-readable because the pool is a deployment coordinate; the
#: client within that pool is not.
#:
#: Why pinning cannot lock out real staff: `docs/execution/aws-inventory.json` records the
#: staff pool `us-east-1_cSx0RHCIR` with exactly ONE client
#: (`/cognito/user_pools[1]/clients[0]/id`), and this is it. There is no second staff client
#: to refuse. Every token a signed-in staff member holds is minted here.
STAFF_APP_CLIENT_ID = '1j8kbi48m4v2rped3n224rlevb'


def _unverified_issuer(token: str) -> str:
    """The `iss` claim, read WITHOUT signature verification.

    Safe only because it is used to *reject*, never to accept. `GetUser` has already
    proven the token live; this narrows WHICH pool proved it. Copied in shape from
    `lambda_utils.customer_auth._unverified_issuer` and
    `core/secure-files/handler.py`, which both made the same call for the same reason.

    `GetUser` takes a token and nothing else, so it resolves the user from whichever
    pool issued it — a customer-pool token, or a token from any Cognito pool in any AWS
    account, validates there. Without this pin the group lookup below then runs against
    the STAFF pool keyed on `Username`, so a foreign pool holding a user named like a
    real staff member inherits that staff member's groups. That is full role escalation,
    not merely a missing least-privilege default, which is why this is load-bearing and
    not defence in depth.
    """
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get('iss') or '')
    except Exception:  # noqa: BLE001 - a malformed token simply has no issuer
        return ''


def _unverified_clients(token: str) -> Set[str]:
    """Every app client the token names, read WITHOUT signature verification.

    Same safety argument as `_unverified_issuer`, and the same single use: these values
    only ever cause a REJECTION. `GetUser` has proven the token live and the issuer pin has
    proven which pool proved it; this narrows which client within that pool minted it.

    Returns a SET because the two Cognito token types spell the claim differently and one
    of them may be plural:

      * an ACCESS token carries `client_id`, a string. This is the token `require_auth`
        actually receives — it validates with `get_user(AccessToken=token)` — so in
        production this is the claim that answers.
      * an ID token carries `aud`, which the JWT spec permits to be either a string or a
        list of strings. Read as well, so the pin does not silently pass a caller who sends
        the other token type.

    An empty set means the token named no client, and the gate refuses that: a token with
    no `client_id` and no `aud` is not a token this pool issued through its one app client.
    """
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - a malformed token simply names no client
        return set()
    if not isinstance(claims, dict):
        return set()

    presented: Set[str] = set()
    for claim in ('client_id', 'aud'):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            presented.add(value)
        elif isinstance(value, (list, tuple)):
            presented.update(str(item) for item in value if isinstance(item, str) and item)
    return presented

# Paths that skip auth. Only genuinely self-authenticating provider endpoints
# belong here - a Meta Flows data-exchange endpoint proves authenticity by RSA
# decryption, a provider webhook by HMAC signature. An endpoint that merely
# *sounds* like a callback does not qualify; see `path_is_exempt`.
AUTH_SKIP_PATHS = os.environ.get('AUTH_SKIP_PATHS', '').split(',')


def path_is_exempt(path: str, stage: str = '', skips=None) -> bool:
    """Exact path match, or a child segment of an exempt path. Never a substring.

    The original form was `skip.strip() in path`, a bare substring test, and that
    is wider than it looks once a catch-all route exists. `wecare-whatsapp-business-api`
    serves `ANY /wa-business/{proxy+}` alongside its explicit routes, so a request
    to `/wa-business/webhooks-anything` reached the same handler, matched the
    substring, and skipped authentication - then fell into the handler's
    `elif '/webhooks' in path` branch and executed the management action anyway.
    Two loose matchers in series, each individually defensible.

    Matching on segment boundaries removes the first one. `/wa-business/flow-data`
    still exempts itself and `/wa-business/flow-data/sub`; it no longer exempts
    `/wa-business/flow-dataX` or `/x/wa-business/flow-data`.
    """
    candidates = [s.strip() for s in (AUTH_SKIP_PATHS if skips is None else skips) if s and s.strip()]
    if not candidates:
        return False

    # Strip the API Gateway stage prefix, so `/prod/x` and `/x` behave alike. On
    # this HTTP API the custom-domain mapping puts the stage in the path, and that
    # difference has already caused two production incidents - see
    # `lambda_utils.http_path`. Without this, a stage-prefixed request to a
    # genuinely exempt endpoint would be sent to the auth gate instead.
    try:
        from lambda_utils.http_path import strip_stage
        normalized = strip_stage(path or '', stage or '')
    except Exception:  # pragma: no cover - the normalizer must never gate auth
        normalized = path or ''
    normalized = '/' + (normalized or '').strip('/')

    for skip in candidates:
        skip = '/' + skip.strip('/')
        if normalized == skip or normalized.startswith(skip + '/'):
            return True
    return False


def require_auth(
    event: Dict[str, Any],
    required_role: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Validate Cognito JWT token from the Authorization header.

    Returns None if auth succeeds (caller should proceed).
    Returns a cors_response dict if auth fails (caller should return it).

    Sets event['_auth'] with user info on success:
        event['_auth'] = {
            'username': str,
            'email': str,
            'role': str,
            'groups': list,
        }

    Skips auth for:
    - OPTIONS preflight requests
    - Paths listed in AUTH_SKIP_PATHS env var
    - Lambda-to-Lambda invocations (no requestContext.http and no httpMethod)
    """
    origin = extract_origin(event)

    # Skip auth for OPTIONS
    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', '')).upper()
    if method == 'OPTIONS':
        return None

    # Skip auth for internal Lambda-to-Lambda invocations.
    # Requests that arrive through API Gateway (the only externally reachable
    # path) always carry an API Gateway request context — apiId, domainName, and
    # http.sourceIp are injected by API Gateway HTTP APIs. Internal invokes built
    # by our own code (e.g. flow -> invoice-engine payment links, inbound -> pay)
    # do not have these, even though some include a minimal requestContext.http
    # for routing. The previous "no http context at all" check missed those and
    # returned 401 on legitimate internal calls. Treat any event lacking an API
    # Gateway context as internal. This does NOT create external exposure:
    # unauthenticated external callers can only reach the function via API Gateway
    # (apiId present -> auth enforced); direct Lambda invokes already require IAM.
    is_api_gateway = bool(
        rc.get('apiId') or rc.get('domainName')
        or rc.get('http', {}).get('sourceIp')
    )
    if not is_api_gateway:
        return None

    # Skip auth for configured self-authenticating provider endpoints.
    path = rc.get('http', {}).get('path', event.get('path', ''))
    if path_is_exempt(path, str(rc.get('stage') or '')):
        return None

    # Extract token
    headers = event.get('headers', {})
    auth_header = headers.get('authorization', headers.get('Authorization', ''))
    token = auth_header.replace('Bearer ', '') if auth_header else ''

    if not token:
        return cors_response(401, {'error': 'No authorization token provided'}, origin)

    # Validate with Cognito
    try:
        user_info = cognito.get_user(AccessToken=token)
    except cognito.exceptions.NotAuthorizedException:
        return cors_response(401, {'error': 'Invalid or expired token'}, origin)
    except Exception as e:
        logger.warning(json.dumps({'event': 'auth_validation_error', 'error': str(e)}))
        return cors_response(401, {'error': 'Token validation failed'}, origin)

    # The token is live. Narrow WHICH pool proved that — see `_unverified_issuer`.
    # A token from the customer pool, or from any other Cognito pool, stops here.
    # Refused as 401 rather than 403: the credential is not valid for this API at all,
    # and a 403 would say "you are authenticated here, just not enough", which is
    # neither true nor useful to the caller.
    if _unverified_issuer(token) != staff_pool_issuer():
        logger.warning(json.dumps({'event': 'auth_wrong_pool'}))
        return cors_response(401, {'error': 'Invalid or expired token'}, origin)

    # The pool is right. Narrow WHICH APP CLIENT on that pool minted the token.
    #
    # The issuer pin above is not sufficient on its own: `iss` names the pool, and every
    # app client on a pool issues tokens bearing the same `iss`. An app client is the unit
    # that carries the auth flows, the OAuth scopes, the callback URLs and the token
    # lifetimes, so a second client added to this pool for any purpose — a partner
    # integration, a machine-to-machine client with `ALLOW_USER_PASSWORD_AUTH`, a
    # throwaway for a test — would mint tokens that passed every check below and reached
    # every staff route. Pinning the one client that exists closes that before it opens.
    #
    # 401, placed BEFORE the group lookup, and logged under its own event name, for the
    # same three reasons as the issuer pin: the credential is not valid for this API at
    # all; a refused caller must not cause an `admin_list_groups_for_user` against the
    # staff pool keyed on a username it chose; and three refusal causes sharing one log
    # line would let two of them regress unnoticed.
    if STAFF_APP_CLIENT_ID not in _unverified_clients(token):
        logger.warning(json.dumps({'event': 'auth_wrong_client'}))
        return cors_response(401, {'error': 'Invalid or expired token'}, origin)

    username = user_info.get('Username', '')
    attributes = {attr['Name']: attr['Value'] for attr in user_info.get('UserAttributes', [])}

    # Get groups. FAILS CLOSED: the group lookup is the only thing that establishes a
    # role, so an answer we could not obtain is not an answer we may substitute a
    # default for. This used to swallow the exception and fall through to Viewer.
    try:
        groups_resp = cognito.admin_list_groups_for_user(
            Username=username, UserPoolId=USER_POOL_ID
        )
        groups = [g['GroupName'] for g in groups_resp.get('Groups', [])]
    except Exception as e:
        logger.warning(json.dumps({
            'event': 'auth_group_lookup_failed', 'username': username,
            'error': type(e).__name__,
        }))
        return cors_response(403, {'error': 'Could not determine role'}, origin)

    # Determine highest role. NO DEFAULT: a principal with no group in the hierarchy has
    # no role, and `None` is not silently promoted to the bottom rung. This is what
    # refuses an ungrouped user and a `Partner`-only user — `Partner` is deliberately
    # absent from ROLE_HIERARCHY, so it scores 0 and grants nothing.
    role: Optional[str] = None
    for group in groups:
        if ROLE_HIERARCHY.get(group, 0) > ROLE_HIERARCHY.get(role or '', 0):
            role = group

    if role is None:
        logger.warning(json.dumps({
            'event': 'auth_no_staff_group', 'username': username, 'groups': groups,
        }))
        return cors_response(403, {
            'error': 'Insufficient permissions',
            'requiredRole': required_role or 'Viewer',
            'currentRole': None,
        }, origin)

    # Check required role
    if required_role and ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(required_role, 0):
        return cors_response(403, {
            'error': 'Insufficient permissions',
            'requiredRole': required_role,
            'currentRole': role,
        }, origin)

    # --- Admin second factor -------------------------------------------------
    # Checked where the Admin privilege is USED, not at sign-in, because that is where
    # it is actually exercised - and only when Admin is required, so an Admin reading a
    # Viewer-level route does not pay an extra AdminGetUser per request.
    #
    # The role refusal above runs FIRST on purpose: a Viewer asking for Admin gets
    # "Insufficient permissions", not an MFA message, which would disclose that the
    # Admin role exists and what it requires.
    mfa_enrolled: Optional[bool] = None
    mfa_required = _admin_mfa_required()
    if required_role == 'Admin':
        mfa_enrolled = _has_enrolled_mfa(username)

        if mfa_enrolled is not True:
            log_level = 'error' if mfa_required else 'warning'
            logger.warning(json.dumps({
                'event': 'admin_without_mfa',
                'alert': 'ADMIN_MFA_MISSING',
                'level': log_level,
                'username': username,
                # None means the lookup failed; False means definitely not enrolled.
                # Collapsing the two would make a Cognito outage look like a policy
                # violation, and vice versa.
                'mfaEnrolled': mfa_enrolled,
                'enforcing': mfa_required,
            }))

        if mfa_required and mfa_enrolled is not True:
            # Fails CLOSED, deliberately the opposite of the audit sink's choice. An
            # audit write that fails open loses a record; an authorization check that
            # fails open grants administrator.
            return cors_response(403, {
                'error': 'MFA required',
                'detail': ('Administrator actions require a second factor. Enrol an '
                           'authenticator app in your account settings, sign in '
                           'again, and retry.'),
            }, origin)

    # Attach auth info to event for downstream use.
    # `attributes` includes any custom attributes (e.g. custom:partner_waba_id)
    # so handlers can scope data to a specific tenant for customer users.
    event['_auth'] = {
        'username': username,
        'email': attributes.get('email', ''),
        'role': role,
        'groups': groups,
        'attributes': attributes,
        # True / False / None, where None means the lookup could not answer.
        'mfaEnrolled': mfa_enrolled,
        'mfaRequired': mfa_required,
    }

    return None


def _admin_mfa_required() -> bool:
    """Whether a missing Admin second factor should refuse rather than warn.

    Read per call, not captured at import: this is a security posture switch and one
    that only takes effect after every warm sandbox recycles is not much of a switch.

    Defaults to warn, but the reason it defaulted to warn HAS EXPIRED. Recorded here
    because the original note is now misleading and would argue against a change that is
    already safe.

    Measured 2026-09-23: "the pool has one user, that user is in NO group, and all four
    groups are empty - so enforcing immediately would refuse the first Admin ever created
    until they enrolled, and whoever hit that would turn the check off rather than enrol."

    Re-measured 2026-09-28 against the live pool `us-east-1_cSx0RHCIR`:

        1 user, CONFIRMED and enabled
        that user IS in the Admin group   (Admin: 1, Operator/Partner/Viewer: 0)
        that user HAS two factors enrolled: SMS_MFA and EMAIL_OTP
        AdminCreateUserConfig.AllowAdminCreateUserOnly: true  (no self-signup)
        DeletionProtection: ACTIVE

    So the lock-out risk the warn-first default was protecting against no longer exists,
    and `ADMIN_MFA_REQUIRED=true` is already set on all 13 functions that gate anything on
    an Admin role - including every one of the nine handlers that pass
    `required_role='Admin'`. Enforcement is therefore live, not pending.

    The remaining softness is at the Cognito layer rather than here: the pool's
    `MfaConfiguration` is OPTIONAL, so Cognito itself will not force a challenge for a
    user who has enrolled nothing. This function is what refuses that user, and line 199
    treats `None` - a failed enrolment lookup - as not-enrolled, so it fails closed.
    Raising the pool to `ON` is an account-level security change and
    `00-current-owner-overrides.md` explicitly records admin MFA as "not MANDATORY", so it
    is an owner decision rather than a default to flip here.
    """
    return str(os.environ.get('ADMIN_MFA_REQUIRED', '')).strip().lower() in (
        '1', 'true', 'yes', 'on')


def _has_enrolled_mfa(username: str) -> Optional[bool]:
    """True / False / None for "does this user have a second factor registered".

    Deliberately ENROLMENT, not "did this session use MFA". `require_auth` validates an
    access token via `get_user`, and a Cognito access token carries no reliable `amr`
    claim, so the session question is not answerable here. Enrolment plus a pool
    `MfaConfiguration` of OPTIONAL or ON means Cognito will have issued a challenge;
    claiming to verify more than that would overstate the control.

    Any factor counts - TOTP, SMS or email OTP. The live account's sole user has
    SMS_MFA and EMAIL_OTP and no TOTP, so insisting on TOTP would refuse the one person
    who actually has a second factor.

    Returns None rather than False when the lookup fails, so a Cognito outage is
    distinguishable from a user who has enrolled nothing.
    """
    try:
        detail = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=username)
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            'event': 'mfa_lookup_failed', 'username': username,
            'error': type(exc).__name__,
        }))
        return None

    factors = detail.get('UserMFASettingList') or []
    if detail.get('PreferredMfaSetting'):
        return True
    return bool(factors)


def health_check(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Return a 200 health check response if the request path ends with /health.
    Returns None if not a health check request (caller should proceed).
    """
    rc = event.get('requestContext', {})
    path = rc.get('http', {}).get('path', event.get('path', ''))
    if path.rstrip('/').endswith('/health'):
        from lambda_utils.response import cors_response, extract_origin
        origin = extract_origin(event)
        return cors_response(200, {'status': 'healthy'}, origin)
    return None
