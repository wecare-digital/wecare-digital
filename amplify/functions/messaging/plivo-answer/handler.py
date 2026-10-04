"""Plivo voice webhooks: answer, fallback, hangup and events.

  WhatsApp user / PSTN caller
    -> Plivo Voice Application (WECARE-WHATSAPP-IVR, 12775976954213184)
    -> POST https://wecare.digital/api/plivo/answer     -> <Play> + <Hangup/>
       POST https://wecare.digital/api/plivo/fallback    -> emergency XML
       POST https://wecare.digital/api/plivo/hangup      -> persist CDR, 2xx
       POST https://wecare.digital/api/plivo/events      -> record, 2xx

These are APEX paths behind an Amplify rewrite `/api/<*>` -> execute-api, as of
2026-09-26. The rewrite CONSUMES the `/api` segment, which broke every signed
callback until `PLIVO_CALLBACK_HOST` and `PLIVO_CALLBACK_PATH_PREFIX` were set on
this function - see lambda_utils/plivo_signature.reconstruct_url. Both variables
are REQUIRED here; without them `hangup`, `events` and `dial-events` all reject.

One Lambda serves all four routes. They share provider verification, the call
record and the post-call SMS de-duplication, and splitting them would mean three
copies of each or a shared layer to hold them. The function is still named
wecare-plivo-answer for continuity with its alias and integrations.

PROVIDER AUTHENTICATION (§18)
-----------------------------
Primary: Plivo X-Plivo-Signature-V3, verified in lambda_utils.plivo_signature
against the auth token from Secrets Manager.

The `?token=` shared secret is retained as DIAGNOSTIC COMPATIBILITY ONLY, per
§18, not as proof of provider identity. It matters that these are different
things: the token is a bearer secret sitting in a URL that appears in the Plivo
console and in our own snapshots, whereas the V3 signature covers the URL, the
sorted POST body and a per-request nonce, so it also proves the payload was not
edited in transit and cannot be replayed.

Plivo does NOT sign answer_url fetches - only callbacks. So:

    /plivo/answer     signature verified WHEN PRESENT, token gate enforced.
                      Cannot require a signature: a genuine answer_url fetch
                      arrives unsigned and rejecting it drops the call.
    /plivo/hangup     signature REQUIRED. It is a callback, and it is the route
    /plivo/events     with side effects (SMS, CDR writes).
    /plivo/fallback   signature verified when present; answer-style fetch.

That asymmetry is the whole reason the hangup side effect was worth moving off
the answer URL.

§19 RESPONSIBILITIES
--------------------
    answer    -> valid Plivo XML, 200, text/xml
    fallback  -> record the primary failure, return emergency XML, terminate
    hangup    -> persist final CDR state, dedupe by CallUUID, return 2xx
    events    -> record, return 2xx

The hangup endpoint MUST NOT return the answer IVR. Returning <Play> to a hangup
callback is how a terminated call gets re-answered.
"""
import base64
import hmac
import json
import os
import time
import urllib.parse
from decimal import Decimal
from xml.sax.saxutils import escape

from lambda_utils.logging import get_logger, log_event
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')

# The greeting Plivo fetches for <Play>. Moved onto the apex `/get/o/` path on
# 2026-09-26, when app.wecare.digital's objects were consolidated into
# wecare-digital-get under the `o/` prefix.
#
# Verified equivalent before switching, because <Play> is what a real caller hears
# and a 404 here is silence: same ETag (2479657262de…), same 738160 bytes, same
# `audio/wav`, and — the part a plain GET would have missed — the same
# `206 Partial Content` with an identical `content-range` for a Range request.
# A media fetcher that ranges would otherwise have failed on a URL that looked
# healthy in a browser.
# Expressed through lambda_utils.media_paths so there is ONE rooting convention in the
# fleet rather than two. This handler had it right before the others did, but it carried
# the `o/` in the BASE while every other handler carries it in the KEY. That split is a
# trap for the next edit, so the root moves into the key and MEDIA_BASE becomes the plain
# CDN host. The composed URL is byte-identical to what this function already served:
#   https://wecare.digital/get/o/stream/media/ivr/incoming_welcome.wav
MEDIA_BASE = os.environ.get('IVR_MEDIA_BASE', f'https://{media_paths.CDN_DOMAIN}')
IVR_AUDIO_KEY = os.environ.get(
    'IVR_AUDIO_KEY', media_paths.public('stream/media/ivr/incoming_welcome.wav'))
IVR_AUDIO_URL = os.environ.get('IVR_AUDIO_URL', f'{MEDIA_BASE}/{IVR_AUDIO_KEY}')

# --- post-call follow-up SMS -------------------------------------------------
# Body MUST match approved DLT template ivr-default (1007277993798259629)
# character for character. The operator silently drops mismatched content even
# though the API call succeeds, so do not "improve" this copy.
SMS_FUNCTION = os.environ.get('SMS_FUNCTION', 'wecare-sms-aws:live')
POST_CALL_SMS_ENABLED = os.environ.get('POST_CALL_SMS_ENABLED', 'true').lower() == 'true'
DLT_TEMPLATE_KEY = os.environ.get('DLT_TEMPLATE_KEY', 'ivr-default')
IVR_SMS_BODY = os.environ.get('IVR_SMS_BODY', (
    "Thanks for contacting WECARE.DIGITAL!\n\n"
    "Submit your request here: https://wecare.digital/submit-request/ "
    "or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\n"
    "We'll review it and follow up if needed."
))

# --- browser routing (Phase 7) -----------------------------------------------
# OFF by default. Turning this on changes what a real caller hears, so it is a
# production decision with its own approval - never a deployment side effect.
#
# false -> play the greeting and hang up   (the current, safe production default)
# true  -> <Dial><User> the agent endpoint (browser softphone)
PSTN_BROWSER_ROUTING_ENABLED = os.environ.get(
    'PSTN_BROWSER_ROUTING_ENABLED', 'false').lower() == 'true'

# The endpoint the inbound call is dialled to. A SIP URI is NOT accepted from a
# request - only this server-side configuration - so no caller can redirect a call
# to a destination of their choosing.
PSTN_AGENT_ENDPOINT = os.environ.get('PSTN_AGENT_ENDPOINT', '')

# Seconds to ring the agent before giving up and falling back to the greeting.
PSTN_DIAL_TIMEOUT = int(os.environ.get('PSTN_DIAL_TIMEOUT', '25'))

# Where Plivo reports the dial outcome. This is the AUTHORITATIVE connected
# signal; see lambda_utils/pstn/notifications.py.
#
# The default moved off `api.wecare.digital` on 2026-09-26 when that custom domain
# was retired. It was unreachable rather than merely stale: this URL is handed to
# Plivo inside `<Dial callbackUrl=...>`, so a dial would have reported its outcome
# to a host that no longer resolves, silently losing the connected signal. It has
# never fired in production only because PSTN_BROWSER_ROUTING_ENABLED is off - so
# this was a landmine armed for whoever turned that flag on, not a live fault.
PSTN_DIAL_CALLBACK_URL = os.environ.get(
    'PSTN_DIAL_CALLBACK_URL', 'https://wecare.digital/api/plivo/dial-events')

CDR_TABLE = os.environ.get('VOICE_CDR_TABLE', 'stack-wecare-digital-VoiceCDRTable')
CDR_TTL_SECONDS = 90 * 24 * 60 * 60

PLIVO_ANSWER_SECRET_ID = os.environ.get('PLIVO_ANSWER_SECRET_ID', 'wecare/plivo-answer')
PLIVO_API_SECRET_ID = os.environ.get('PLIVO_API_SECRET_ID', 'wecare/plivo/api')

_answer_token_cache: str = ''
_plivo_auth_token_cache: str = ''
_ddb = None


def _table():
    global _ddb
    if _ddb is None:
        import boto3
        _ddb = boto3.resource('dynamodb', region_name=REGION)
    return _ddb.Table(CDR_TABLE)


def _secret_field(secret_id: str, field: str) -> str:
    try:
        import boto3
        sm = boto3.client('secretsmanager', region_name=REGION)
        raw = sm.get_secret_value(SecretId=secret_id).get('SecretString', '') or ''
        try:
            return (json.loads(raw).get(field) or '').strip()
        except (ValueError, TypeError):
            return raw.strip()
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 'plivo_secret_unavailable', level='debug',
                  secretId=secret_id, field=field, error=type(exc).__name__)
        return ''


def _get_answer_token() -> str:
    """Diagnostic token. Only a successful lookup is cached.

    Caching the empty result would strand a sandbox that started before the
    secret existed - it would keep returning '' until recycled.
    """
    global _answer_token_cache
    if _answer_token_cache:
        return _answer_token_cache
    value = _secret_field(PLIVO_ANSWER_SECRET_ID, 'token') \
        or os.environ.get('PLIVO_ANSWER_TOKEN', '')
    if value:
        _answer_token_cache = value
    return value


def _get_plivo_auth_token() -> str:
    """The Plivo account auth token, used as the V3 signing key."""
    global _plivo_auth_token_cache
    if _plivo_auth_token_cache:
        return _plivo_auth_token_cache
    value = _secret_field(PLIVO_API_SECRET_ID, 'auth_token')
    if value:
        _plivo_auth_token_cache = value
    return value


# --------------------------------------------------------------------------
# responses
# --------------------------------------------------------------------------
def _xml(body: str, status: int = 200) -> dict:
    return {
        'statusCode': status,
        # Plivo ignores a non-XML content type and the caller hears silence.
        'headers': {'Content-Type': 'text/xml; charset=utf-8',
                    'Cache-Control': 'no-store'},
        'body': body,
    }


def _hangup_xml(status: int = 403) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n    <Hangup/>\n</Response>')


def _ivr_xml(audio_url: str) -> str:
    """Play the greeting, then hang up. No <Record>, no <Speak>, no TTS."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'    <Play>{escape(audio_url)}</Play>\n'
            '    <Hangup/>\n'
            '</Response>')


def _dial_user_xml(endpoint_username: str) -> str:
    """Ring a browser agent endpoint, then fall back to the greeting.

    `<User>` dials a Plivo ENDPOINT, not an arbitrary SIP URI. The username comes
    from server configuration and is escaped, so neither a caller nor an operator
    request can point a live call at a destination of their choosing.

    `callbackUrl` carries the authoritative connected event. `callbackMethod` is
    POST to match every other callback on this application.

    If the agent does not answer within the timeout, the verbs AFTER <Dial>
    execute - so the caller hears the existing greeting rather than silence. That
    is why the greeting stays in this response instead of being replaced by it.
    """
    escaped = escape(endpoint_username)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            f'    <Dial timeout="{PSTN_DIAL_TIMEOUT}" '
            f'callbackUrl="{escape(PSTN_DIAL_CALLBACK_URL)}" '
            'callbackMethod="POST" redirect="false">\n'
            f'        <User>sip:{escaped}@phone.plivo.com</User>\n'
            '    </Dial>\n'
            f'    <Play>{escape(IVR_AUDIO_URL)}</Play>\n'
            '    <Hangup/>\n'
            '</Response>')


def _answer_xml() -> str:
    """The answer response, which depends on the browser-routing flag.

    Falls back to the greeting whenever browser routing is off OR no agent
    endpoint is configured. A flag turned on without an endpoint would otherwise
    emit a <Dial> to an empty destination, which drops the call - so the missing
    configuration is treated as "not enabled" and logged, rather than trusted.
    """
    if PSTN_BROWSER_ROUTING_ENABLED and PSTN_AGENT_ENDPOINT:
        return _dial_user_xml(PSTN_AGENT_ENDPOINT)
    if PSTN_BROWSER_ROUTING_ENABLED and not PSTN_AGENT_ENDPOINT:
        log_event(logger, 'plivo_browser_routing_misconfigured', level='error',
                  alert='PSTN_BROWSER_ROUTING_NO_ENDPOINT',
                  detail=('PSTN_BROWSER_ROUTING_ENABLED is true but '
                          'PSTN_AGENT_ENDPOINT is empty; serving the greeting '
                          'rather than dialling an empty destination'))
    return _ivr_xml(IVR_AUDIO_URL)


def _fallback_xml() -> str:
    """Emergency XML for when the primary answer URL failed (§19).

    Deliberately simpler than the IVR: the fallback fires precisely when
    something is already broken, so it must not depend on the same S3 media fetch
    that may be what failed. <Speak> needs no external asset.
    """
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Response>\n'
            '    <Speak language="en-IN" voice="WOMAN">'
            'Thank you for calling WECARE DIGITAL. '
            'We are unable to take your call right now. '
            'Please message us on WhatsApp and we will follow up.'
            '</Speak>\n'
            '    <Hangup/>\n'
            '</Response>')


def _ack(payload: dict = None, status: int = 200) -> dict:
    return {'statusCode': status,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(payload or {'ok': True})}


# --------------------------------------------------------------------------
# request parsing / verification
# --------------------------------------------------------------------------
def _parse_body(event: dict) -> dict:
    """Plivo posts form-encoded; tolerate JSON. Single values collapsed."""
    raw = event.get('body') or ''
    if event.get('isBase64Encoded'):
        try:
            raw = base64.b64decode(raw).decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            raw = ''
    if not raw:
        return {}
    stripped = raw.lstrip()
    if stripped.startswith('{'):
        try:
            return json.loads(stripped)
        except Exception:  # noqa: BLE001
            return {}
    return {k: v[0] if len(v) == 1 else v
            for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}


# Authentication strength, weakest last. Serving IVR XML and performing a SIDE
# EFFECT are different privileges, and conflating them was a real hole - see
# _route_answer.
TRUST_SIGNATURE = 'signature'    # V3 verified: cryptographically proven Plivo
TRUST_TOKEN = 'token'            # ?token= matched: proves a shared secret
TRUST_NONE = 'unverified'        # nothing proven


def _verify_provider(event: dict, *, require_signature: bool) -> tuple:
    """(ok, trust_level, mechanism_or_reason).

    require_signature=True for callbacks, which Plivo does sign. False for
    answer-style fetches, which it does not - there the token is the only gate
    available, and requiring a signature would drop every genuine call.

    The third element is what callers must branch on before doing anything with a
    side effect. `ok=True` means "respond normally"; it does NOT mean "this request
    is proven to be Plivo".

    Why this returns a trust level rather than just a boolean
    --------------------------------------------------------
    Plivo does not sign answer_url fetches, so /plivo/answer cannot require a
    signature without dropping every real call. The previous version therefore
    returned True when no token was configured, which is defensible for RETURNING
    XML and indefensible for the rest of what that route does: it also handles the
    CallStatus=completed pass, which sends a DLT-templated SMS.

    That combination was an SMS-pumping vector. An unauthenticated
    POST /plivo/answer carrying CallStatus=completed&From=91XXXXXXXXXX would send a
    message to an arbitrary Indian number at our cost, under our registered sender.
    It required the token lookup to return empty - so a transient Secrets Manager
    failure, or the secret being removed, was enough to open it.

    Failing closed on a missing token instead would trade that for an outage:
    every inbound call would drop while the secret was unreadable. Neither is
    acceptable, so the privilege is split instead. Answer still serves XML at
    TRUST_NONE; side effects require TRUST_TOKEN or better.
    """
    from lambda_utils import plivo_signature

    auth_token = _get_plivo_auth_token()
    hdrs = plivo_signature.headers_lower(event)
    has_sig = bool(hdrs.get(plivo_signature.HEADER_V3)
                   or hdrs.get(plivo_signature.HEADER_MA_V3))

    if has_sig and auth_token:
        ok, reason = plivo_signature.verify_request(event, auth_token)
        if ok:
            return True, TRUST_SIGNATURE, f'signature_{reason}'
        return False, TRUST_NONE, reason

    if require_signature:
        return False, TRUST_NONE, ('signature_required_but_absent' if not has_sig
                                   else 'auth_token_not_configured')

    # Answer-style fetch: fall back to the diagnostic token gate.
    token = _get_answer_token()
    if not token:
        # Serve the call, but say so loudly and carry no privilege. A real call
        # must not drop because a secret read failed; a side effect must not run
        # because one did.
        log_event(logger, 'plivo_answer_token_unavailable', level='error',
                  alert='PLIVO_ANSWER_TOKEN_UNAVAILABLE',
                  detail=('answer-style request served unverified; side effects '
                          'suppressed'))
        return True, TRUST_NONE, 'unverified_no_token_configured'

    qs = event.get('queryStringParameters') or {}
    if _token_matches(qs.get('token'), token):
        return True, TRUST_TOKEN, 'token'
    return False, TRUST_NONE, 'bad_or_missing_token'


def _token_matches(presented, expected: str) -> bool:
    """Constant-time comparison of the diagnostic bearer token.

    This was a plain `==` until 2026-09-23, in the same file where
    `plivo_signature.validate_signature` already documents why that is wrong and
    uses `hmac.compare_digest`. `==` on a secret short-circuits at the first
    differing byte, leaking its length and matching prefix. The token is the weaker
    of the two credentials, which is a reason to compare it carefully, not loosely.

    Both sides are encoded first because `compare_digest` raises TypeError on a
    non-ASCII str, and `?token=caf\u00e9` turning a 403 into a 500 matters here: on
    /plivo/answer a 500 is a non-XML body, so the caller hears silence instead of a
    clean hangup.
    """
    if not isinstance(presented, str) or not presented:
        return False
    return hmac.compare_digest(presented.encode('utf-8', 'surrogatepass'),
                               expected.encode('utf-8', 'surrogatepass'))


# --------------------------------------------------------------------------
# side effects
# --------------------------------------------------------------------------
def _claim_once(call_uuid: str, suffix: str) -> bool:
    """True when this (call, event) pair has not been handled yet.

    Plivo retries callbacks, and during the transition the hangup pass can arrive
    on BOTH /plivo/answer and /plivo/hangup. Without this, one call sends two
    DLT-templated SMS to the same customer.
    """
    if not call_uuid:
        return True
    try:
        from lambda_utils.webhook_dedup import claim_event
        return claim_event(f'{call_uuid}:{suffix}', source='plivo')
    except Exception as exc:  # noqa: BLE001
        # Dedup unavailable: proceed rather than drop a real event, but say so.
        log_event(logger, 'plivo_dedup_unavailable', level='warning',
                  callUuid=call_uuid, error=type(exc).__name__)
        return True


def _external_party(params: dict) -> tuple:
    """`(recipient, reason)` — the customer side of this call, by direction.

    Exists because `_send_post_call_sms` used to be called with
    `params.get('From')` regardless of direction. On an inbound call `From` is the
    customer and that is right; on an outbound call `From` is our own CLI, so the
    business number would have been texted - billed to us, under our own registered
    DLT sender.

    Direction is the rule and the business-number registry is the backstop, for the
    reason set out in `lambda_utils.notifications.events`: they fail differently, so
    one mistake in either is not enough to message ourselves.
    """
    from lambda_utils.notifications import events as notif_events

    direction = str(params.get('Direction') or '').strip().lower()
    if direction in ('inbound', 'in', 'incoming'):
        recipient = params.get('From', '')
    elif direction in ('outbound', 'out', 'outgoing', 'outbound-api', 'outbound_api'):
        recipient = params.get('To', '')
    else:
        # No safe default: guessing inbound texts our own number on every outbound
        # call, guessing outbound texts the agent endpoint on every inbound one.
        return '', 'ambiguous_direction'

    if not recipient:
        return '', 'no_external_party'
    if notif_events.is_business_number(recipient):
        return '', 'recipient_is_business_number'
    return recipient, ''


def _send_post_call_sms(caller: str, call_uuid: str, request_id: str) -> None:
    """Text the customer the customer-service links. Fire and forget.

    LEGACY, and triggered by hangup, which the brief lists as *not* a notification
    trigger. It is retained because it is the only connected-call notification
    actually reaching customers today - measured at 32 sends in 14 days, against 0
    for the compliant `/plivo/dial-events` path - so silencing it before the
    replacement is live would simply stop callers getting a follow-up. Its
    retirement is manifest-first work for Phase 9; see
    `docs/notification-retirement-manifest.md`.

    Callers must pass a recipient resolved by `_external_party`, not a raw `From`.
    """
    if not POST_CALL_SMS_ENABLED or not caller:
        return
    digits = ''.join(c for c in str(caller) if c.isdigit())
    if not (digits.startswith('91') and len(digits) == 12):
        log_event(logger, 'plivo_post_call_sms_skipped',
                  reason='non_indian_caller', callUuid=call_uuid,
                  requestId=request_id)
        return
    try:
        import boto3
        payload = {
            'requestContext': {'http': {'method': 'POST', 'path': '/sms-aws/send'}},
            'headers': {'origin': 'https://wecare.digital'},
            'body': json.dumps({
                'phoneNumber': f'+{digits}',
                'content': IVR_SMS_BODY,
                'messageType': 'TRANSACTIONAL',
                'dltTemplateKey': DLT_TEMPLATE_KEY,
                'campaignName': 'plivo-ivr-follow-up',
            }),
        }
        boto3.client('lambda').invoke(
            FunctionName=SMS_FUNCTION, InvocationType='Event',
            Payload=json.dumps(payload).encode())
        log_event(logger, 'plivo_post_call_sms_queued', callUuid=call_uuid,
                  phone=digits[-4:], templateKey=DLT_TEMPLATE_KEY,
                  via=SMS_FUNCTION, requestId=request_id)
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 'plivo_post_call_sms_failed', level='warning',
                  callUuid=call_uuid,
                  error=f'{type(exc).__name__}: {str(exc)[:160]}',
                  requestId=request_id)


# Plivo CallStatus -> the overallCallStatus vocabulary the CDR readers and the
# dashboard aggregate on. Without this mapping a Plivo row has no
# overallCallStatus at all, so it counts as neither answered nor missed and the
# stats silently under-report.
_PLIVO_STATUS_TO_OVERALL = {
    'completed': 'Answered',      # refined below: 0-duration completed is Missed
    'busy': 'Busy',
    'no-answer': 'Missed',
    'noanswer': 'Missed',
    'failed': 'Missed',
    'cancel': 'Missed',
    'canceled': 'Missed',
    'cancelled': 'Missed',
    'timeout': 'Missed',
    'ringing': 'Ringing',
    'in-progress': 'In Progress',
}


def _plivo_seconds(params: dict) -> int:
    """Call duration in whole seconds. Plivo sends these as strings."""
    for key in ('Duration', 'BillDuration', 'ConferenceDuration'):
        raw = params.get(key)
        if raw in (None, ''):
            continue
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return 0


def _plivo_overall_status(params: dict, seconds: int) -> str:
    """Map Plivo's CallStatus onto the reader's status vocabulary.

    A `completed` call with zero duration was never actually talked on - Plivo
    reports completed for a normal teardown regardless of whether the callee
    picked up - so reporting it as Answered would overstate the answer rate.
    """
    status = str(params.get('CallStatus') or '').strip().lower()
    mapped = _PLIVO_STATUS_TO_OVERALL.get(status, '')
    if mapped == 'Answered' and seconds <= 0:
        return 'Missed'
    return mapped or (status.title() if status else '')


# Where each callback sits in the call's life. All five _persist_cdr call sites
# write the SAME row id - `plivo#{CallUUID}` - so without a rank the last callback
# to arrive wins on the whole item, whatever it actually reports.
#
# Measured 2026-09-23 before this was added: 56 of 56 live rows were won by
# `route='hangup'`, so it had not yet fired. It is reachable by design, not by
# accident: `_route_dial_events` answers 503 on purpose when the notification
# store is unreachable so Plivo REDELIVERS, and a redelivery can land after
# hangup. It becomes routine the moment PSTN_BROWSER_ROUTING_ENABLED is turned on
# and dial-events starts firing on every call.
#
# The damage is not cosmetic. A mid-call payload carries no Duration, so
# `_plivo_overall_status` downgrades it to 'Missed', and `_calculate_stats` counts
# the answer rate off exactly that field. `put_item` also REPLACES the item, so
# `hangupCause`, `durationSec` and `end_time` were deleted rather than left alone.
#
# Equal ranks are allowed through: a retried hangup carrying a corrected
# BillDuration must land, and the transitional completed pass on /plivo/answer is
# the same lifecycle position as a hangup callback.
_CDR_ROUTE_RANK = {
    'events': 10,              # mid-call lifecycle event
    'dial-events': 20,         # dial outcome, still mid-call
    'fallback': 30,            # primary answer URL failed
    'answer-hangup-pass': 40,  # terminal, arriving on the answer URL
    'hangup': 40,              # terminal
}
CDR_RANK_ATTRIBUTE = 'cdrRank'

# Set once and never restamped. `createdAt` is the sort key for both read paths in
# voice-cdr-read AND the date fallback the renderer uses when `timestamp` is
# absent, so moving it moves the row's place in history.
_CDR_WRITE_ONCE = ('createdAt',)


def _write_cdr_row(item: dict, route: str, call_uuid: str,
                   request_id: str) -> bool:
    """Merge the row forward. Never lowers the recorded lifecycle state.

    An `update_item` rather than a `put_item` so that a field absent from this
    callback is left alone instead of deleted, and conditional on the rank so a
    late lower-ranked callback cannot win.
    """
    rank = Decimal(str(_CDR_ROUTE_RANK.get(route, 0)))
    fields = {k: v for k, v in item.items()
              if k != 'id' and v not in ('', None)}

    names = {'#rank': CDR_RANK_ATTRIBUTE}
    values = {':rank': rank}
    sets = ['#rank = :rank']
    for i, key in enumerate(sorted(fields)):
        np, vp = f'#n{i}', f':v{i}'
        names[np] = key
        values[vp] = fields[key]
        if key in _CDR_WRITE_ONCE:
            sets.append(f'{np} = if_not_exists({np}, {vp})')
        else:
            sets.append(f'{np} = {vp}')

    try:
        _table().update_item(
            Key={'id': item['id']},
            UpdateExpression='SET ' + ', '.join(sets),
            ConditionExpression='attribute_not_exists(#rank) OR #rank <= :rank',
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except Exception as exc:  # noqa: BLE001
        code = ''
        response = getattr(exc, 'response', None)
        if isinstance(response, dict):
            code = (response.get('Error') or {}).get('Code') or ''
        if code == 'ConditionalCheckFailedException':
            # Not an error. A higher-ranked callback already recorded this call,
            # so there is nothing to write. Reporting False here would make
            # `_route_hangup` log cdrPersisted=false on a healthy call.
            log_event(logger, 'plivo_cdr_write_superseded',
                      callUuid=call_uuid, route=route, rank=int(rank),
                      requestId=request_id)
            return True
        log_event(logger, 'plivo_cdr_persist_failed', level='error',
                  callUuid=call_uuid, table=CDR_TABLE, route=route,
                  error=f'{type(exc).__name__}: {str(exc)[:160]}',
                  requestId=request_id)
        return False
    return True


def _persist_cdr(params: dict, route: str, request_id: str) -> bool:
    """Final call state into VoiceCDRTable. Never raises.

    Writes BOTH shapes on purpose.

    The camelCase keys are what every reader and the dashboard actually use
    (voice-cdr-read._format_record_for_ui, _calculate_stats, and the CDR tab in
    src/pages/dm/voice-in). Before this, Plivo rows were written only in
    snake_case, so they were present in the table and invisible in the product:
    blank caller/destination/status cells, no date (there was no `createdAt`,
    which is also the sort key, so every Plivo row sorted to 0 and fell off the
    bottom of a limited page), and they inflated `total` while counting as
    neither inbound/outbound nor answered/missed.

    The snake_case keys are kept because rows written before this change carry
    them and nothing rewrites history; dropping them would strip fields off
    existing rows on any subsequent callback for the same call.

    `source='plivo'` stays the discriminator - this table contains Plivo and historical retired-provider rows.
    """
    call_uuid = params.get('CallUUID') or ''
    if not call_uuid:
        return False
    now = int(time.time())
    seconds = _plivo_seconds(params)
    direction = str(params.get('Direction') or '').strip().lower()
    # Plivo says 'inbound'/'outbound', sometimes 'outbound-api'. The readers
    # filter on exactly INBOUND/OUTBOUND.
    call_type = 'INBOUND' if direction.startswith('in') else (
        'OUTBOUND' if direction.startswith('out') else '')
    from_number = params.get('From') or ''
    to_number = params.get('To') or ''
    hangup_cause = params.get('HangupCause') or params.get('HangupCauseName') or ''
    overall = _plivo_overall_status(params, seconds)

    item = {
        'id': f'plivo#{call_uuid}',
        'source': 'plivo',
        'route': route,

        # ---- snake_case, retained for rows written before the normalisation ----
        'call_uuid': call_uuid,
        'from_number': from_number,
        'to_number': to_number,
        'direction': params.get('Direction') or '',
        'call_status': params.get('CallStatus') or '',
        'hangup_cause': hangup_cause,
        'hangup_source': params.get('HangupSource') or '',
        'duration_seconds': params.get('Duration') or params.get('BillDuration') or '',
        'end_time': params.get('EndTime') or '',
        'received_at': now,

        # ---- camelCase: what the readers, stats and UI bind to ----
        # createdAt is load-bearing twice over: it is the sort key for both read
        # paths AND the date fallback when there is no `timestamp` string.
        'createdAt': Decimal(str(now)),
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now)),
        'callerNumber': from_number,
        'destinationNumber': to_number,
        'callerId': to_number if call_type == 'INBOUND' else from_number,
        'callType': call_type,
        'overallCallStatus': overall,
        'hangupCause': hangup_cause,
        'hangupStatus': params.get('HangupSource') or '',
        'durationSec': Decimal(str(seconds)),
        'durationMs': Decimal(str(seconds * 1000)),
        # Plivo bills the whole connected call; there is no separate IVR wait leg
        # to subtract, so conversation and billable both track duration. Left
        # explicit rather than derived so a reader does not have to guess.
        'conversationDurationSec': Decimal(str(seconds)),
        'conversationDurationMs': Decimal(str(seconds * 1000)),
        'billableDurationSec': Decimal(str(seconds)),
        'billableDurationMs': Decimal(str(seconds * 1000)),
        'callUuid': call_uuid,

        'expiresAt': Decimal(str(now + CDR_TTL_SECONDS)),
    }
    if not _write_cdr_row(item, route, call_uuid, request_id):
        return False

    # Unified timeline breadcrumb, so a Plivo call also appears on the Calls
    # page rather than only in the CDR tab. Best-effort: a breadcrumb failure
    # must not lose the CDR we just stored.
    try:
        from lambda_utils.message_store import put_call_breadcrumb
        put_call_breadcrumb(
            call_id=f'plivo#{call_uuid}',
            direction='inbound' if call_type == 'INBOUND' else 'outbound',
            status=overall,
            duration=seconds or None,
            call_type='plivo',
            phone=from_number if call_type == 'INBOUND' else to_number,
            recording_url=None,
        )
    except Exception as exc:  # noqa: BLE001
        log_event(logger, 'plivo_cdr_breadcrumb_skipped', level='warning',
                  callUuid=call_uuid, error=type(exc).__name__,
                  requestId=request_id)
    return True


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
def _route_answer(params: dict, request_id: str, trust: str = TRUST_NONE) -> dict:
    """§19 answer: return valid Plivo XML.

    During the transition this URL is still registered as the hangup URL too, so
    a CallStatus=completed pass may arrive here. Handle it, de-duplicated against
    /plivo/hangup so the customer gets exactly one SMS per call.

    The completed pass is SIDE-EFFECTING - it sends a DLT-templated SMS - so it
    requires TRUST_TOKEN or better. Returning the IVR XML does not, because Plivo
    does not sign answer_url fetches and refusing an unsigned one would drop every
    real call. See _verify_provider for why the two are separated.
    """
    status = str(params.get('CallStatus', '')).lower()
    call_uuid = params.get('CallUUID', '')
    if status == 'completed':
        if trust == TRUST_NONE:
            # Refuse the side effect, not the request. An unverified caller must
            # not be able to make us text an arbitrary number.
            log_event(logger, 'plivo_postcall_refused_unverified', level='error',
                      callUuid=call_uuid, route='answer',
                      alert='PLIVO_UNVERIFIED_POSTCALL_ATTEMPT',
                      from_last4=str(params.get('From', ''))[-4:],
                      requestId=request_id)
            return _ack({'ok': True, 'callUuid': call_uuid,
                         'sideEffectsSuppressed': True}, status=202)
        if _claim_once(call_uuid, 'postcall'):
            _persist_cdr(params, 'answer-hangup-pass', request_id)
            _recipient, _why = _external_party(params)
            if _recipient:
                _send_post_call_sms(_recipient, call_uuid, request_id)
            else:
                log_event(logger, 'plivo_post_call_sms_skipped', reason=_why,
                          callUuid=call_uuid, requestId=request_id)
        else:
            log_event(logger, 'plivo_postcall_deduped', callUuid=call_uuid,
                      route='answer', requestId=request_id)
        return {'statusCode': 200,
                'headers': {'Content-Type': 'text/plain'}, 'body': 'ok'}
    return _xml(_answer_xml())


def _route_fallback(params: dict, request_id: str) -> dict:
    """§19 fallback: record that the primary answer URL failed, then degrade."""
    log_event(logger, 'plivo_answer_primary_failed', level='error',
              callUuid=params.get('CallUUID', ''),
              from_last4=str(params.get('From', ''))[-4:],
              # Plivo reports why the primary failed in these fields.
              fallbackReason=params.get('FallbackReason', ''),
              primaryError=params.get('ErrorType', '') or params.get('Error', ''),
              requestId=request_id,
              alert='PLIVO_PRIMARY_ANSWER_URL_FAILED')
    _persist_cdr(params, 'fallback', request_id)
    return _xml(_fallback_xml())


def _route_hangup(params: dict, request_id: str) -> dict:
    """§19 hangup: persist final CDR, dedupe, return 2xx.

    Returns JSON, never the answer IVR. Returning <Play> to a hangup callback is
    how a terminated call gets re-answered.
    """
    call_uuid = params.get('CallUUID', '')
    fresh = _claim_once(call_uuid, 'postcall')
    persisted = _persist_cdr(params, 'hangup', request_id)
    if fresh:
        _recipient, _why = _external_party(params)
        if _recipient:
            _send_post_call_sms(_recipient, call_uuid, request_id)
        else:
            log_event(logger, 'plivo_post_call_sms_skipped', reason=_why,
                      callUuid=call_uuid, requestId=request_id)
    else:
        log_event(logger, 'plivo_postcall_deduped', callUuid=call_uuid,
                  route='hangup', requestId=request_id)
    log_event(logger, 'plivo_hangup', callUuid=call_uuid,
              callStatus=params.get('CallStatus', ''),
              hangupCause=params.get('HangupCause', ''),
              duration=params.get('Duration', ''),
              cdrPersisted=persisted, deduped=not fresh, requestId=request_id)
    return _ack({'ok': True, 'callUuid': call_uuid, 'deduped': not fresh})


def _route_events(params: dict, request_id: str) -> dict:
    """§19 events: record and acknowledge."""
    call_uuid = params.get('CallUUID', '')
    log_event(logger, 'plivo_event', callUuid=call_uuid,
              event=params.get('Event', '') or params.get('EventName', ''),
              callStatus=params.get('CallStatus', ''), requestId=request_id)
    _persist_cdr(params, 'events', request_id)
    return _ack({'ok': True, 'callUuid': call_uuid})


# Callbacks are signed by Plivo; answer-style fetches are not.
def _route_dial_events(params: dict, request_id: str) -> dict:
    """The AUTHORITATIVE connected-call signal: <Dial callbackUrl>.

    Signature required. This route decides whether a customer gets a message, so
    an unsigned request must never reach the claim logic.

    Returns a retryable 5xx when the claim store is unreachable. That is
    deliberate: Plivo redelivers, so the cost of refusing to guess is latency,
    whereas guessing means duplicate SMS to real people under our registered DLT
    sender.
    """
    from lambda_utils.notifications import keys as notif_keys
    from lambda_utils.notifications import service as notif_service
    from lambda_utils.notifications import store as notif_store

    call_uuid = params.get('CallUUID', '')
    try:
        # PROVIDER_PLIVO names the CALL provider whose callback shape this is —
        # it selects the dial-callback parser, not an SMS transport. Plivo is the
        # approved PSTN voice provider (§6); the notification channels it fans out
        # to still resolve through the normal AWS senders.
        outcome = notif_service.handle_connected_call(
            params, provider=notif_keys.PROVIDER_PLIVO, request_id=request_id)
    except notif_store.NotificationStoreUnavailable as exc:
        # Fail closed. 503 so Plivo retries; nothing was sent.
        log_event(logger, 'plivo_dial_store_unavailable', level='error',
                  callUuid=call_uuid,
                  alert='NOTIF_STORE_UNAVAILABLE',
                  error=type(exc).__name__, requestId=request_id)
        return _ack({'error': 'notification store unavailable, retry'}, status=503)

    _persist_cdr(params, 'dial-events', request_id)
    log_event(logger, 'plivo_dial_event', callUuid=call_uuid,
              dialAction=params.get('DialAction', ''),
              claimed=outcome.get('claimed'),
              reason=outcome.get('reason'),
              published=','.join(outcome.get('published') or []) or None,
              skipped=','.join(outcome.get('skipped') or []) or None,
              requestId=request_id)
    return _ack({'ok': True, 'callUuid': call_uuid,
                 'claimed': outcome.get('claimed', False)})


# `_dispatch_notification` was removed here on 2026-09-21.
#
# It sent SMS inline, synchronously, inside the signed webhook, and left RCS
# permanently `PENDING` with a comment explaining that a worker would own it one day.
# No worker was ever built, so every RCS row it created would have sat unsent forever
# - and the table it wrote to did not exist either, so in practice the route answered
# 503 and `plivo_dial_event` fired 0 times in 14 days.
#
# Dispatch now belongs to the outbox in `lambda_utils.notifications.store`: the claim
# and the job are written in one transaction, and a worker leases the job. Nothing is
# sent from this webhook, which removes both the provider latency inside Plivo's
# callback timeout and the one unrecoverable case - a timeout mid-send, where the
# claim cannot record what happened.


_ROUTES = {
    '/plivo/answer':   (_route_answer,   False),
    '/plivo/fallback': (_route_fallback, False),
    '/plivo/hangup':   (_route_hangup,   True),
    '/plivo/events':   (_route_events,   True),
    # Signature REQUIRED: this route decides whether a customer is messaged.
    '/plivo/dial-events': (_route_dial_events, True),
}


def handler(event, context):
    request_id = getattr(context, 'aws_request_id', 'local') if context else 'local'

    # Strip the API Gateway stage prefix. Measured: a request to
    # https://api.wecare.digital/plivo/hangup arrives with
    # rawPath="/prod/plivo/hangup", so matching rawPath directly sends every
    # callback to the default route - and if that default is the answer handler,
    # a hangup callback gets the IVR back, which re-answers a terminated call.
    from lambda_utils import plivo_signature
    path = plivo_signature.normalize_path(event).rstrip('/') or '/plivo/answer'

    if path not in _ROUTES:
        # Refuse. Until 2026-09-23 this logged a warning and then fell through to
        # `(_route_answer, False)` anyway - which is the behaviour the comment here
        # said not to have, and it is what hid the stage-prefix incident:
        # /prod/plivo/hangup "worked" by returning <Play> to a hangup callback,
        # which re-answers a terminated call.
        #
        # Nothing live depends on the fallback. All five routes on this integration
        # are exact POST paths, the API has no $default or {proxy+} route, and
        # normalize_path strips the stage from requestContext.stage rather than a
        # hardcoded "prod". So the only way to reach here is a route added without a
        # _ROUTES entry, and for that case a 404 that shows up in the metric beats an
        # IVR served to a callback.
        #
        # Refused BEFORE _verify_provider, deliberately: the path is not a
        # credential, and verifying first would make this 404 depend on two secret
        # reads it has no need for.
        log_event(logger, 'plivo_unknown_path', level='warning',
                  path=path, rawPath=event.get('rawPath', ''),
                  alert='PLIVO_UNKNOWN_PATH_REFUSED',
                  requestId=request_id)
        return _ack({'error': 'not found'}, status=404)

    route, require_signature = _ROUTES[path]

    ok, trust, mechanism = _verify_provider(event,
                                            require_signature=require_signature)
    if not ok:
        # Do not tell the caller which check failed.
        log_event(logger, 'plivo_request_rejected', level='warning',
                  path=path, reason=mechanism, requestId=request_id)
        if path in ('/plivo/answer', '/plivo/fallback'):
            return _xml(_hangup_xml(), status=403)
        return _ack({'error': 'unauthorized'}, status=401)

    params = _parse_body(event)
    log_event(logger, 'plivo_request', path=path, auth=mechanism, trust=trust,
              callUuid=params.get('CallUUID', ''),
              from_last4=str(params.get('From', ''))[-4:],
              to_last4=str(params.get('To', ''))[-4:],
              direction=params.get('Direction', ''),
              callStatus=params.get('CallStatus', ''),
              # A REAL SIP call carries SIP headers; synthetic tests do not.
              sipHeaders=params.get('SIPHeaders', ''),
              requestId=request_id)

    if route is _route_answer:
        return route(params, request_id, trust)
    return route(params, request_id)
