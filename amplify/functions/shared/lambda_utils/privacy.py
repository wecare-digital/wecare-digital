"""
PII redaction utilities for Lambda handlers.

Usage:
    from lambda_utils.privacy import mask_phone, mask_email, redact_pii

    masked = mask_phone('+919330994400')  # '+91****4400'
    masked = mask_email('user@example.com')  # 'u***@example.com'
    safe = redact_pii({'phone': '+919330994400', 'name': 'Test'})
"""

import re
from typing import Any, Dict


def mask_phone(phone: str) -> str:
    """Mask phone number, keeping country code and last 4 digits."""
    if not phone or not isinstance(phone, str):
        return '***'
    clean = phone.strip()
    if len(clean) <= 6:
        return '***'
    # Keep first 3 chars (e.g. +91) and last 4
    return clean[:3] + '****' + clean[-4:]


def mask_email(email: str) -> str:
    """Mask email address, keeping first char and domain."""
    if not email or not isinstance(email, str):
        return '***'
    parts = email.split('@')
    if len(parts) != 2:
        return '***'
    local = parts[0]
    return local[0] + '***@' + parts[1] if local else '***@' + parts[1]


def mask_contact_id(contact_id: str) -> str:
    """Mask a contact id, but only the form that is a phone number.

    THE FINDING, 2026-09-28. `contactId` reads like an opaque surrogate key and is the
    standard correlation field in this codebase's logs -- 83 logger sites carried it. It
    is not opaque. `inbound-whatsapp-handler._deterministic_contact_id` mints it as

        f'wa{digits}'   where digits = normalize_phone(phone)

    so a WhatsApp-originated contact id **is** the customer's E.164 digits behind a
    two-character prefix. Confirmed against the live table without reading a value:
    all 6 rows in `stack-wecare-digital-ContactsTable` match the character-class
    pattern `Ax999999999999` -- `wa` followed by twelve digits.

    The scheme is deliberate and worth keeping: one phone maps to one contact, which is
    what removes the duplicate-contact churn that GSI eventual consistency used to
    cause. The defect is only that the value was being logged whole.

    TWO FORMS, AND ONLY ONE IS MASKED. Contacts created through the API get
    `str(uuid.uuid4())` (`core/contacts/handler.py`), and a uuid discloses nothing, so
    masking it would destroy a usable correlation key for no gain. This masks the
    phone-derived form and returns the uuid form untouched -- the distinction is
    checkable from the value itself, which is why it can be made here rather than at
    every call site.

    Last four, not a hash, because that is already the convention every other masked
    number in these logs follows and an operator reading two adjacent lines should not
    have to hold two schemes in their head. `.kiro/steering/02-qa-recipient.md` notes
    the ambiguity this creates for `...0044` and why widening the mask is the wrong
    answer to it.
    """
    if not contact_id or not isinstance(contact_id, str):
        return ''
    if contact_id.startswith('wa') and contact_id[2:].isdigit() and len(contact_id) > 6:
        return 'wa***' + contact_id[-4:]
    return contact_id


def mask_flow_token(token: str) -> str:
    """Drop the phone segment from a WhatsApp Flow token so it can be logged.

    A Flow token is minted as ``{prefix}-{uuid4}-waba-{n}-ph-{phone}`` (see
    ``lambda_utils/flow_completion.py``) and ``flows/common.get_phone_from_token``
    recovers the customer's number by splitting on ``-ph-``. So a log line carrying a
    whole Flow token carries a full E.164 number, and four sites were doing exactly
    that under the key ``flowToken`` -- invisible to a check that looks for phone-shaped
    field NAMES, which is why this needed finding by reading rather than by grepping.

    Everything before ``-ph-`` is kept, because that half is what makes the token useful
    in a log: the prefix says which flow, the uuid correlates the send with the
    submission, and ``-waba-{n}`` says which business number sent it. Only the phone
    goes.

    Two existing sites truncated at ``flow_token[:25]`` instead. That is correct today
    -- a uuid4 is 36 characters, so 25 cannot reach ``-ph-`` -- but it is correct by
    arithmetic rather than by construction, and it silently stops being correct if the
    prefix ever grows. This is the same intent expressed so it cannot drift.
    """
    if not token or not isinstance(token, str):
        return ''
    for prefix in ('paidsr:', 'orders:'):
        if token.startswith(prefix):
            return prefix + '***'
    head, separator, _ = token.partition('-ph-')
    return head + '-ph-***' if separator else token


_PHONE_RE = re.compile(r'\+?\d{10,15}')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def redact_pii(data: Dict[str, Any], phone_fields: list = None, email_fields: list = None) -> Dict[str, Any]:
    """
    Redact PII fields in a dictionary for safe logging.
    Auto-detects phone/email fields by name if not specified.
    Returns a new dict (does not mutate original).
    """
    if not isinstance(data, dict):
        return data

    phone_keys = set(phone_fields or [
        'phone', 'phoneNumber', 'phone_number', 'senderPhone', 'sender_phone',
        'recipientPhone', 'recipient_phone', 'fromNumber', 'from_number',
        'toNumber', 'to_number', 'callerNumber', 'destinationNumber',
        'from', 'to', 'wa_id', 'recipient_id', 'contactPhone',
    ])
    email_keys = set(email_fields or [
        'email', 'buyerEmail', 'contactEmail',
    ])

    result = {}
    for key, val in data.items():
        if key in phone_keys and isinstance(val, str):
            result[key] = mask_phone(val)
        elif key in email_keys and isinstance(val, str):
            result[key] = mask_email(val)
        elif isinstance(val, dict):
            result[key] = redact_pii(val, phone_fields, email_fields)
        else:
            result[key] = val
    return result


def redact_string(text: str) -> str:
    """Redact phone numbers and emails from a free-text string."""
    if not text or not isinstance(text, str):
        return text
    result = _PHONE_RE.sub(lambda m: mask_phone(m.group()), text)
    result = _EMAIL_RE.sub(lambda m: mask_email(m.group()), result)
    return result
