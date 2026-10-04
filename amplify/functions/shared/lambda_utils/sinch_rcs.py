"""
Sinch RCS Notification Utility

Shared module for sending RCS messages via Sinch India Conversation API.
Used by: voice-in/cdr, whatsapp-calling, order notifications.

Authentication:
  Token endpoint: POST https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token
  Grant type: password
  Client ID: ipmessaging-client
  Username/Password from Secrets Manager: wecare/sinch/rcs

Send API:
  POST https://convapi.aclwhatsapp.com/v1/projects/{projectId}/messages:send
  Authorization: Bearer <token>

Config:
  - AWS Secret: wecare/sinch/rcs (keys: username, password, project_id, app_id)
  - Env: SINCH_RCS_ENABLED=true to activate

Templates (approved, Jio, MEDIUM height):
  - rcsmenu — IVR/call disconnect notifications
  - rcsorder — order confirmation notifications
  - waalert — WhatsApp alert notifications
"""

import os
import json
import time
import logging
import urllib.request
import urllib.error
import urllib.parse
import boto3

# Country logic has exactly one home. `rcs-send` already uses this module for the same
# decision, and adding a second normaliser here is what produced the defect below.
from lambda_utils.comms import numbers as _numbers
from lambda_utils.privacy import mask_phone

logger = logging.getLogger(__name__)

# Auth and API endpoints (same as rcs-send handler — the working one)
RCS_AUTH_URL = "https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token"
RCS_API_BASE = "https://convapi.aclwhatsapp.com/v1/projects"

# Cache credentials and token
_sinch_cache = {}
_token_cache = {'token': '', 'expires_at': 0, 'refresh_token': '', 'refresh_expires_at': 0}
_secrets_client = None


def _get_secrets_client():
    global _secrets_client
    if not _secrets_client:
        _secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    return _secrets_client


def is_rcs_enabled() -> bool:
    """Check if Sinch RCS is enabled via environment variable."""
    return os.environ.get('SINCH_RCS_ENABLED', 'false').lower() == 'true'


#: The only place these credentials come from. Never an environment variable, never a
#: literal: the password grant authenticates with `username` + `password`, so a hardcoded
#: username is half a credential sitting in source control.
SINCH_RCS_SECRET_ID = os.environ.get('RCS_SECRET_NAME', 'wecare/sinch/rcs')

#: Every field the secret carries. `bot_id` was previously not loaded here at all, so
#: anything routed through this module had no bot id even though the secret held one.
SINCH_RCS_FIELDS = ('username', 'password', 'project_id', 'app_id', 'bot_id')

#: Without both of these there is no authentication, so proceeding is pointless.
REQUIRED_FIELDS = ('username', 'password')


def _load_sinch_credentials() -> dict:
    """Load Sinch RCS credentials from Secrets Manager. Cached per execution environment.

    Secrets Manager only, with **no default for any field**. The previous version fell back
    to `data.get('username', 'wecaretrans')` plus literal project and app ids, which was
    wrong twice over:

    * it put half of the password-grant credential pair into source control, and
    * it made an incomplete secret *look* usable. A missing `username` would authenticate as
      `wecaretrans` with an empty password, producing a 401 that reads like a provider
      outage rather than a configuration fault - and if the username were ever rotated, the
      fallback would mask it.

    Returns `{}` when the secret cannot be read or a required field is blank, naming the
    missing field. Never logs a value.
    """
    if _sinch_cache.get('loaded'):
        return _sinch_cache

    try:
        client = _get_secrets_client()
        resp = client.get_secret_value(SecretId=SINCH_RCS_SECRET_ID)
        data = json.loads(resp['SecretString'])
    except Exception as e:
        logger.error(json.dumps({
            'event': 'sinch_rcs_secret_unavailable',
            'secretId': SINCH_RCS_SECRET_ID,
            'error': str(e)[:200],
        }))
        return {}

    missing = [f for f in REQUIRED_FIELDS if not str(data.get(f) or '').strip()]
    if missing:
        # Field names only. Naming them turns an opaque 401 into a fixable fault.
        logger.error(json.dumps({
            'event': 'sinch_rcs_secret_incomplete',
            'secretId': SINCH_RCS_SECRET_ID,
            'missingFields': missing,
        }))
        return {}

    _sinch_cache.update({f: str(data.get(f) or '').strip() for f in SINCH_RCS_FIELDS})
    _sinch_cache['loaded'] = True
    logger.info(json.dumps({
        'event': 'sinch_rcs_secret_loaded',
        'secretId': SINCH_RCS_SECRET_ID,
        # Presence only, never values.
        'fieldsPresent': sorted(f for f in SINCH_RCS_FIELDS if _sinch_cache.get(f)),
    }))
    return _sinch_cache


def _get_token() -> str:
    """Get valid RCS auth token (cached, auto-refresh via username/password).
    
    Uses the same auth flow as rcs-send/handler.py which works correctly.
    """
    now = int(time.time())

    # Return cached token if still valid (with 30s buffer)
    if _token_cache['token'] and _token_cache['expires_at'] > now + 30:
        return _token_cache['token']

    # Try refresh token if available
    if _token_cache['refresh_token'] and _token_cache['refresh_expires_at'] > now + 30:
        token = _refresh_token()
        if token:
            return token

    # Full auth with username/password
    return _authenticate()


def _authenticate() -> str:
    """Authenticate with Sinch RCS using username/password grant."""
    creds = _load_sinch_credentials()
    username = creds.get('username') or ''
    password = creds.get('password', '')

    if not password:
        logger.error("RCS: No password in wecare/sinch/rcs secret — cannot authenticate")
        return ''

    body = urllib.parse.urlencode({
        'grant_type': 'password',
        'client_id': 'ipmessaging-client',
        'username': username,
        'password': password,
    }).encode()

    # Try both URL variants (same as rcs-send handler)
    urls = [
        RCS_AUTH_URL,
        "https://auth.aclwhatsapp.com/auth/realms/ipmessaging/protocol/openid-connect/token",
    ]

    for url in urls:
        try:
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'cache-control': 'no-cache',
            }, method='POST')

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                token = data.get('access_token', '')
                if token:
                    now = int(time.time())
                    _token_cache['token'] = token
                    _token_cache['expires_at'] = now + data.get('expires_in', 300)
                    _token_cache['refresh_token'] = data.get('refresh_token', '')
                    _token_cache['refresh_expires_at'] = now + data.get('refresh_expires_in', 1800)
                    logger.info(f"RCS auth success, expires_in={data.get('expires_in')}s")
                    return token
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:100] if e.fp else ''
            logger.warning(f"RCS auth failed ({url}): HTTP {e.code} - {err}")
        except Exception as e:
            logger.warning(f"RCS auth error ({url}): {e}")

    logger.error("RCS auth FAILED on all URLs — check wecare/sinch/rcs password")
    return ''


def _refresh_token() -> str:
    """Refresh the RCS auth token."""
    body = urllib.parse.urlencode({
        'grant_type': 'refresh_token',
        'client_id': 'ipmessaging-client',
        'refresh_token': _token_cache['refresh_token'],
    }).encode()

    try:
        req = urllib.request.Request(RCS_AUTH_URL, data=body, headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'cache-control': 'no-cache',
        }, method='POST')

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            token = data.get('access_token', '')
            if token:
                now = int(time.time())
                _token_cache['token'] = token
                _token_cache['expires_at'] = now + data.get('expires_in', 300)
                _token_cache['refresh_token'] = data.get('refresh_token', '')
                _token_cache['refresh_expires_at'] = now + data.get('refresh_expires_in', 1800)
                return token
    except Exception as e:
        logger.warning(f"RCS token refresh failed: {e}")

    return ''


def _normalize_phone(phone: str) -> str:
    """The Sinch Conversation API identity (12 digits, no `+`), or `''` if unreachable.

    What changed, and why it mattered
    ---------------------------------
    This used to end with ``return '91' + clean[-10:]`` for any input of ten digits or more.
    That is not normalisation, it is fabrication. Several countries are exactly ten digits in
    full E.164 - Singapore, Hong Kong, Denmark - so ``+65 8123 4567`` became
    ``916581234567``: a real and *different* Indian subscriber. The provider accepted it, the
    message was delivered to a stranger, and nothing anywhere reported a fault.

    `rcs-send` had the same defect and was fixed earlier by delegating to
    `lambda_utils.comms.numbers`. This now delegates to the same module, so the two senders
    cannot drift apart again - a second normaliser is precisely how they diverged.

    The old docstring promised `09903300044`. That is deliberately no longer accepted
    ------------------------------------------------------------------------------------
    A leading `0` followed by ten digits is the Indian STD trunk prefix - and it is also the
    UK national format: `07911123456` has exactly that shape, and its ten digits start with
    7, inside the same 6-9 range Indian mobiles use. The two forms are structurally
    indistinguishable without a country context.

    Assuming India would therefore be the same mistake as the `'91' + clean[-10:]` rule this
    replaced, just narrower. Measured before deciding: all 13 rows in ContactsTable store
    `+91` E.164, twelve digits, and **zero** leading-zero forms exist anywhere in
    ContactsTable or CrmLeads. So the special case served no real input while creating a
    disagreement between this sender and `notifications.policy`, which normalises through
    the same helper and refused the form.

    One authority, no local exceptions. If a genuine STD-formatted number ever needs to be
    accepted, it should be normalised where the country IS known - at the point of capture -
    not guessed at send time.

    Returns `''` rather than raising: every caller in this module already treats an empty
    identity as "do not send".
    """
    if not phone:
        return ''

    e164 = _numbers.to_e164(str(phone).strip())
    if not e164 or not _numbers.is_india(e164):
        logger.warning(json.dumps({
            'event': 'rcs_recipient_refused',
            'phone': _numbers.last4(e164 or str(phone)),
            'reason': 'Sinch India RCS serves Indian destinations only; refusing rather '
                      'than rewriting the number',
        }))
        return ''
    return e164.lstrip('+')


def send_rcs_text(phone: str, text: str, correlation_id: str = '') -> dict:
    """Send a plain text RCS message via Sinch Conversation API."""
    if not is_rcs_enabled():
        return {'success': False, 'error': 'RCS not enabled'}

    creds = _load_sinch_credentials()
    if not creds.get('project_id') or not creds.get('app_id'):
        return {'success': False, 'error': 'Sinch credentials not configured'}

    identity = _normalize_phone(phone)
    payload = {
        'app_id': creds['app_id'],
        'recipient': {
            'identified_by': {
                'channel_identities': [
                    {'channel': 'RCS', 'identity': identity}
                ]
            }
        },
        'message': {
            'text_message': {
                'text': text
            }
        },
    }

    return _send_sinch_message(payload)


def send_rcs_card(phone: str, title: str, description: str,
                  media_url: str = '', choices: list = None,
                  correlation_id: str = '') -> dict:
    """Send an RCS rich card via Sinch Conversation API."""
    if not is_rcs_enabled():
        return {'success': False, 'error': 'RCS not enabled'}

    creds = _load_sinch_credentials()
    if not creds.get('project_id') or not creds.get('app_id'):
        return {'success': False, 'error': 'Sinch credentials not configured'}

    identity = _normalize_phone(phone)

    card = {
        'title': title,
        'description': description,
    }
    if media_url:
        card['media_message'] = {'url': media_url}
    if choices:
        card['choices'] = [
            {'url_message': {'title': c['title'], 'url': c['url']}}
            for c in choices
        ]

    payload = {
        'app_id': creds['app_id'],
        'recipient': {
            'identified_by': {
                'channel_identities': [
                    {'channel': 'RCS', 'identity': identity}
                ]
            }
        },
        'message': {
            'card_message': card
        },
    }

    return _send_sinch_message(payload)


#: The post-call RCS template, resolved at call time from the SAME environment
#: variable `notifications/policy.py` already reads.
#:
#: WHY THIS IS NOT A LITERAL ANY MORE. `policy.RCS_INDIA_TEMPLATE` has been
#: `os.environ.get("NOTIF_RCS_TEMPLATE_NAME", "rcsmenu")` for a while, while this module
#: hardcoded `'rcsmenu'` in four places and never read the variable. Those are two
#: different senders for the same notification, so setting `NOTIF_RCS_TEMPLATE_NAME`
#: switched one and silently left the other — a half-applied migration that looks
#: applied. `send_rcs_ivr_notification` is the path the three live callers use
#: (voice-in/c2c, voice-in/obd, whatsapp-calling, all with `SINCH_RCS_ENABLED=true`),
#: so it was the half that mattered.
#:
#: WHY IT MATTERS NOW. `rcsmenu`'s approved body and its Get Started button point at
#: `https://r.wecare.digital/...`, and that hostname's Route 53 record was deleted on
#: 2026-09-28 06:07Z under confirmation `YES R53-DELETE-001`. The API Gateway custom
#: domain still exists, so only DNS went — which means the button now fails to RESOLVE
#: rather than returning a 404. An approved RCS body cannot be edited in place, so the
#: repair is to send a different, already-approved template whose links are on the apex
#: (`rcsmenu_apex` is approved and every one of its URLs measured 200). Reading the env
#: var makes that a one-variable change with instant rollback and no deploy.
#:
#: Resolved per call, not at import: a module-scope read is frozen for the life of the
#: execution environment, so a change would not take effect until every warm sandbox
#: recycled. Same reasoning as the lazy secret loading in this file.
DEFAULT_IVR_TEMPLATE = 'rcsmenu'


def _ivr_template() -> str:
    return os.environ.get('NOTIF_RCS_TEMPLATE_NAME', DEFAULT_IVR_TEMPLATE)


def send_rcs_template(phone: str, template_id: str = None,
                     language: str = 'en', parameters: dict = None,
                     correlation_id: str = '') -> dict:
    """Send an RCS template message via Sinch Conversation API."""
    if template_id is None:
        template_id = _ivr_template()
    if not is_rcs_enabled():
        return {'success': False, 'error': 'RCS not enabled'}

    creds = _load_sinch_credentials()
    if not creds.get('project_id') or not creds.get('app_id'):
        return {'success': False, 'error': 'Sinch credentials not configured'}

    identity = _normalize_phone(phone)
    payload = {
        'app_id': creds['app_id'],
        'recipient': {
            'identified_by': {
                'channel_identities': [
                    {'channel': 'RCS', 'identity': identity}
                ]
            }
        },
        'message': {
            'template_message': {
                'channel_template': {
                    'RCS': {
                        'template_id': template_id,
                        'language_code': language,
                        'parameters': parameters or {},
                    }
                }
            }
        },
    }

    return _send_sinch_message(payload)


def send_rcs_ivr_notification(phone: str, request_id: str = '') -> dict:
    """Send the standard IVR/call disconnect RCS notification.

    Uses the proven wecare-rcs-send Lambda which handles auth, payload format,
    and template sending correctly. This is the SAME path that successfully
    delivers RCS messages from the dashboard.

    Falls back to direct Sinch API call if Lambda invoke fails.
    """
    normalized = _normalize_phone(phone)
    if not normalized or len(normalized) < 10:
        # Masked in the LOG, whole in the returned error. The log goes to CloudWatch and is
        # read by whoever has log access; the error goes back to the caller that already
        # holds the number it just passed in, so redacting it there would only make the
        # response useless without protecting anything.
        logger.warning(f'RCS IVR skipped — invalid phone: {mask_phone(phone or "")} '
                       f'(normalized_len={len(normalized or "")})')
        return {'success': False, 'error': f'Invalid phone number: {phone}'}

    template = _ivr_template()
    logger.info(f'RCS IVR sending to ...{normalized[-4:]} (template={template} via rcs-send Lambda, request_id={request_id})')

    # ── Primary: Invoke wecare-rcs-send Lambda (proven working path) ──
    try:
        import boto3 as _boto3
        _lambda = _boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        invoke_payload = {
            'requestContext': {'http': {'method': 'POST'}},
            'body': json.dumps({
                'action': 'send',
                'phoneNumber': normalized,
                'template': template,
                'language': 'en',
            }),
        }
        resp = _lambda.invoke(
            FunctionName='wecare-rcs-send',
            InvocationType='RequestResponse',
            Payload=json.dumps(invoke_payload).encode(),
        )
        result = json.loads(resp['Payload'].read())
        status_code = result.get('statusCode', 500)
        if status_code == 200:
            body = json.loads(result.get('body', '{}'))
            if body.get('success'):
                msg_id = body.get('messageId', '')
                logger.info(f'RCS IVR delivered via rcs-send Lambda: message_id={msg_id} phone=...{normalized[-4:]}')
                return {'success': True, 'message_id': msg_id, 'response': body}
        logger.warning(f'rcs-send Lambda returned non-success: HTTP {status_code} body={result.get("body","")[:200]}')
    except Exception as invoke_err:
        logger.warning(f'rcs-send Lambda invoke failed: {invoke_err} — falling back to direct API')

    # ── Fallback: Direct API call to Sinch ──
    result = send_rcs_template(
        phone=phone,
        template_id=template,
    )

    if result.get('success'):
        logger.info(f'RCS IVR delivered (direct): message_id={result.get("message_id", "")} phone=...{normalized[-4:]}')
        return result

    # Final fallback: card_message
    error_msg = result.get('error', 'unknown')
    logger.warning(f'{template} template failed ({error_msg}), falling back to card_message')
    result = send_rcs_card(
        phone=phone,
        title='Thanks for contacting WECARE.DIGITAL!',
        description=(
            'Submit your request here: https://wecare.digital/submit-request/ '
            'or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\n'
            "We'll review it and follow up if needed.\nWECARE.DIGITAL"
        ),
        media_url='https://wecare.digital/get/o/stream/media/m/customerservice.mp4',
        choices=[
            {'title': 'Get Started', 'url': 'https://wecare.digital/r/getstarted'},
        ],
    )

    if not result.get('success'):
        logger.error(f'RCS IVR card_message ALSO FAILED: phone=...{normalized[-4:]}, '
                     f'error={result.get("error", "unknown")}')

    return result


# Removed 2026-09-19: send_rcs_order_notification() and send_rcs_wa_alert().
# Both were approved-template senders (wd_order / waalert) with no caller
# anywhere in the tree. They are recoverable from git history if an order or
# alert RCS flow is built; re-adding dead surface now would only widen what the
# Sinch credential can be used for.


def _send_sinch_message(payload: dict) -> dict:
    """Send message via Sinch Conversation API (convapi.aclwhatsapp.com).
    
    Uses the same API endpoint as rcs-send/handler.py which works correctly.
    Authenticates via username/password OAuth (auto-refresh).
    """
    creds = _load_sinch_credentials()
    project_id = creds.get('project_id', '')
    if not project_id:
        return {'success': False, 'error': 'No project_id configured'}

    token = _get_token()
    if not token:
        return {'success': False, 'error': 'RCS auth failed — check wecare/sinch/rcs password'}

    url = f'{RCS_API_BASE}/{project_id}/messages:send'
    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    # Extract recipient for logging
    recipient_identity = ''
    try:
        identities = payload.get('recipient', {}).get('identified_by', {}).get('channel_identities', [])
        if identities:
            recipient_identity = identities[0].get('identity', '')[-4:]
    except (KeyError, IndexError):
        pass

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                msg_id = result.get('message_id', '')
                logger.info(f'RCS sent: message_id={msg_id} phone=...{recipient_identity}')
                return {'success': True, 'message_id': msg_id, 'response': result}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''

            # On 401, token may have expired mid-request — re-auth and retry
            if e.code == 401 and attempt < max_retries:
                logger.info('RCS 401 — re-authenticating...')
                _token_cache['token'] = ''
                _token_cache['expires_at'] = 0
                new_token = _authenticate()
                if new_token:
                    headers['Authorization'] = f'Bearer {new_token}'
                    continue

            if e.code in (502, 503) and attempt < max_retries:
                time.sleep((attempt + 1) * 2)
                continue

            logger.error(f'RCS send FAILED: HTTP {e.code} | {error_body[:200]} | phone=...{recipient_identity}')
            return {'success': False, 'error': f'HTTP {e.code}: {error_body[:200]}'}

        except Exception as e:
            if attempt < max_retries:
                time.sleep((attempt + 1) * 2)
                continue
            logger.error(f'RCS send error: {e} | phone=...{recipient_identity}')
            return {'success': False, 'error': str(e)}

    return {'success': False, 'error': 'All retries failed'}
