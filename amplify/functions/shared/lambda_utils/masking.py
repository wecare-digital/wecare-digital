"""
Recursive secret/PII masking for safe logging.

`mask_secrets(obj)` returns a deep-copied structure with sensitive fields masked.
Covers auth tokens, app secrets, verify/flow tokens, encryption material, SIP creds,
payment references, and (by default) full phone numbers / WA IDs.
"""
import re
from typing import Any

# Keys whose values are fully redacted
_SECRET_KEYS = {
    'authorization', 'access_token', 'accesstoken', 'token', 'appsecret_proof',
    'app_secret', 'appsecret', 'verify_token', 'verifytoken', 'encrypted_flow_data',
    'encrypted_aes_key', 'initial_vector', 'private_key', 'privatekey', 'passphrase',
    'client_encryption_key', 'sip_password', 'password', 'secret', 'client_secret',
    'flow_token', 'flowtoken',
    # Added 2026-09-23. Every one of these was absent, and this module feeds
    # `audit.record_audit` and `record_system_event`, so an unmasked value lands in a
    # persistent DynamoDB row rather than a log line that rotates.
    #
    # `auth_token` is the sharpest of them: it is the literal field name of the
    # Plivo account credential this codebase reads from Secrets Manager, and having
    # `token` in the list did not cover it, because matching is exact.
    'api_key', 'apikey', 'auth_token', 'authtoken', 'auth_id', 'authid',
    'refresh_token', 'refreshtoken', 'api_secret', 'apisecret',
    'secret_access_key', 'secretaccesskey', 'session_token', 'sessiontoken',
    'webhook_secret', 'webhooksecret', 'credentials', 'bearer',
}

# Value-shape backstop. Issuer-prefixed credentials are redacted under ANY key name,
# because no key list can cover a field called `notes` or `detail`.
#
# Deliberately the same prefixes that scripts/block_inline_secrets.py refuses on a
# command line, and high-precision for the same reason: a noisy mask gets switched
# off, or makes the audit trail unreadable so nobody consults it. Like that hook, it
# will NOT catch an arbitrary high-entropy string with no issuer prefix - it is a
# backstop, not a substitute for keeping credentials out of a details dict.
_ISSUER_PREFIXES = (
    'sk-', 'sk_live_', 'sk_test_', 'pk_live_', 'rzp_live_', 'rzp_test_',
    'AIza', 'ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_', 'xoxb-', 'xoxp-', 'xoxa-',
    'AKIA', 'ASIA', 'shpat_', 'shpss_', 'glpat-',
)
# Long enough that a real token matches and a prose fragment such as "SK-1001" or a
# sentence beginning "AKIAless" does not.
_ISSUER_MIN_LENGTH = 20
_PEM_MARKER = '-----BEGIN'


def _looks_like_a_credential(value: Any) -> bool:
    """A single issuer-prefixed token, or a PEM private key block.

    The whitespace rule is what makes this precise rather than merely eager. A
    credential is one opaque token and never contains a space, whereas prose that
    happens to begin with an issuer prefix does - "AKIAless text, no credential here"
    matched on a prefix-and-length check alone, which is why that assertion exists.
    """
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if _PEM_MARKER in stripped and 'PRIVATE KEY' in stripped:
        return True
    if len(stripped) < _ISSUER_MIN_LENGTH:
        return False
    if any(c.isspace() for c in stripped):
        return False
    return stripped.startswith(_ISSUER_PREFIXES)
# Keys treated as phone/WA id (partial mask)
_PHONE_KEYS = {
    'phone', 'phonenumber', 'phone_number', 'wa_id', 'recipient_id', 'from', 'to',
    'sender_phone', 'senderphone', 'recipientphone', 'recipient_phone', 'callernumber',
    'destinationnumber', 'msisdn', 'user_wa_id',
}
# Keys treated as payment references (partial mask)
_PAYMENT_KEYS = {
    'payment_id', 'paymentid', 'order_id', 'orderid', 'razorpay_payment_id',
    'razorpay_order_id', 'reference_id', 'referenceid', 'txnid', 'mihpayid',
}

_FULL = '***REDACTED***'


def _mask_tail(value: str, keep: int = 4) -> str:
    if not isinstance(value, str) or len(value) <= keep + 2:
        return '***'
    return value[:2] + '****' + value[-keep:]


def mask_value(key: str, value: Any) -> Any:
    k = (key or '').lower().replace('-', '_')
    if k in _SECRET_KEYS:
        return _FULL
    if _looks_like_a_credential(value):
        return _FULL
    if isinstance(value, str):
        if k in _PHONE_KEYS:
            return _mask_tail(value, 4)
        if k in _PAYMENT_KEYS:
            return _mask_tail(value, 4)
    return value


def mask_secrets(obj: Any) -> Any:
    """Deep-mask sensitive fields in dicts/lists; returns a new structure."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = (k or '').lower().replace('-', '_')
            # Checked BEFORE recursing, so a secret key holding a dict or a list is
            # redacted wholesale rather than walked into. `{'credentials': {...}}`
            # previously recursed and emitted the contents.
            if kl in _SECRET_KEYS:
                out[k] = _FULL
            elif isinstance(v, (dict, list)):
                out[k] = mask_secrets(v)
            else:
                out[k] = mask_value(k, v)
        return out
    if isinstance(obj, list):
        return [mask_secrets(i) for i in obj]
    # A bare issuer-shaped string, e.g. an element of a list.
    if _looks_like_a_credential(obj):
        return _FULL
    return obj


# Mask "Bearer <token>" style strings inside free text
_BEARER_RE = re.compile(r'(Bearer\s+)([A-Za-z0-9._\-]+)', re.IGNORECASE)


def mask_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    return _BEARER_RE.sub(lambda m: m.group(1) + _FULL, text)

# A Meta Graph API error, reduced to the parts Meta did not write as prose.
#
# WHY THIS EXISTS. `_send_via_aws` in whatsapp-calling returns the RAW Meta response on its
# error branch, and three log sites dumped it whole -- two of them on the same line as
# `mask_phone(to_number or '')`, so the number was masked on the left and could come back
# unmasked on the right. Meta writes the recipient into the prose of several messaging
# errors; 131030 is the well-known one ("Recipient phone number not in allowed list: Add
# recipient phone number ..."), and `error_data.details` is free text in general.
#
# So the rule is the same one `.kiro/steering/secret-handling.md` (retired; now .kiro/steering/00-common.md) states for exceptions:
# text our own code did not construct does not go in a log. The codes are what a human
# actually debugs from, they come from a closed set Meta documents, and `fbtrace_id` is the
# handle Meta support asks for -- none of them can carry a subscriber's number.
_META_ERROR_SAFE_FIELDS = ('code', 'error_subcode', 'type', 'fbtrace_id')


def meta_error_summary(result: object) -> str:
    """Meta's error identifiers, never its message text.

    Returns a short, stable, log-safe string for any shape, including a non-dict, so a
    caller never has to guard it. Absence of an error is reported rather than hidden,
    because a silent empty string at an error log site reads as a missing field.
    """
    if not isinstance(result, dict):
        return f'non-dict result ({type(result).__name__})'
    error = result.get('error')
    if isinstance(error, dict):
        fields = [f'{k}={error[k]}' for k in _META_ERROR_SAFE_FIELDS if error.get(k) is not None]
        # `message` and `error_data` are deliberately absent. `message_present` keeps the
        # fact that Meta said something, which is the part worth knowing without the text.
        if error.get('message') is not None:
            fields.append('message_present=True')
        return 'meta_error ' + (' '.join(fields) if fields else '(no identifiable fields)')
    # The non-Meta shapes `_send_via_aws` also returns: `{'error': True, 'detail': ...}`
    # where `detail` is either our own f-string or `str(exc)`. `str(exc)` is provider text
    # by the same argument, so the detail is reduced to its presence and length.
    if error is not None:
        detail = result.get('detail')
        if detail is None:
            return 'error=True (no detail)'
        return f'error=True detail_len={len(str(detail))}'
    return 'no error field'
