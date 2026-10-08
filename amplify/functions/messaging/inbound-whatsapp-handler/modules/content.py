"""
Message content extraction from WhatsApp webhook payloads.

Handles all WhatsApp message types: text, image, video, audio, document,
location, contacts, sticker, reaction, interactive, button, order, system,
unsupported, request_welcome, ephemeral, referral, ad_click, product, poll,
edit, revoke.
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Stable label for the measured 131051 case (125 of 128 payloads): Meta flags the
# message unsupported and its `unsupported.type` is `unknown`, so it genuinely does
# not say what arrived. Quoting Meta's own error title at the customer read as a
# system fault, so the label is ours and fixed — the inbox also prefix-matches
# `[Unsupported: ` so a row stored before this change still renders cleanly.
UNSUPPORTED_UNKNOWN = '[Unsupported: WhatsApp did not say what this message was]'

# Caps for the stored contacts payload. A DynamoDB item is capped at 400 KB and a
# forwarded vCard is attacker-influenced input, so bound it at ingest rather than
# trusting the sender.
MAX_CONTACTS = 5
MAX_ITEMS = 5
MAX_STR = 128


def _trim(value) -> str:
    """Return a stripped, length-bounded string, or '' for anything non-string."""
    if not isinstance(value, str):
        return ''
    return value.strip()[:MAX_STR]


def extract_content(message: Dict, msg_type: str) -> str:
    """Extract human-readable content string from a WhatsApp message based on type."""
    extractor = _EXTRACTORS.get(msg_type)
    if extractor:
        return extractor(message)

    logger.warning(json.dumps({
        'event': 'unknown_message_type',
        'messageType': msg_type,
        'messageKeys': list(message.keys()),
    }))
    return f'[{msg_type}]'


def _text(m: Dict) -> str:
    return m.get('text', {}).get('body', '')


def _image(m: Dict) -> str:
    return m.get('image', {}).get('caption', '[Image]')


def _video(m: Dict) -> str:
    return m.get('video', {}).get('caption', '[Video]')


def _audio(_m: Dict) -> str:
    return '[Audio]'


def _document(m: Dict) -> str:
    return m.get('document', {}).get('filename', '[Document]')


def _location(m: Dict) -> str:
    loc = m.get('location', {})
    return f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"


def _contacts_label(m: Dict) -> str:
    """Build the `[Contact Card]` label, carrying the shared name and first number.

    The bracket prefix is kept: both inbox previews key on the bracket shape, and
    one already-stored row contains the bare label with no payload beside it.
    Called from both the `contacts` extractor and the contacts-in-unsupported
    fallback so the two cannot drift apart again.
    """
    try:
        contacts = m.get('contacts')
        if not isinstance(contacts, list) or not contacts:
            return '[Contact Card]'
        first = contacts[0]
        if not isinstance(first, dict):
            return '[Contact Card]'

        name_obj = first.get('name')
        if not isinstance(name_obj, dict):
            name_obj = {}
        display = _trim(name_obj.get('formatted_name')) or ' '.join(
            part for part in (_trim(name_obj.get('first_name')),
                              _trim(name_obj.get('last_name'))) if part
        )

        phone = ''
        phones = first.get('phones')
        if isinstance(phones, list):
            for entry in phones:
                if isinstance(entry, dict):
                    phone = _trim(entry.get('phone'))
                    if phone:
                        break

        parts = [part for part in (display, phone) if part]
        return '[Contact Card] ' + ' · '.join(parts) if parts else '[Contact Card]'
    except Exception:  # noqa: BLE001 — a label must never fail an inbound write
        return '[Contact Card]'


def _contacts(m: Dict) -> str:
    return _contacts_label(m)


def _sanitise_rows(items, fields) -> List[Dict[str, str]]:
    """Bounded copy of a list of flat string dicts, keeping only `fields`."""
    if not isinstance(items, list):
        return []
    out: List[Dict[str, str]] = []
    for raw in items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        row = {field: _trim(raw.get(field)) for field in fields}
        row = {key: value for key, value in row.items() if value}
        if row:
            out.append(row)
    return out


def extract_contacts_payload(message: Dict) -> Optional[List[Dict]]:
    """Sanitised, size-bounded copy of an inbound `contacts[]` array, or None.

    Shape mirrors what this repo's own outbound composer declares (the Cloud API
    shape): name{formatted_name,first_name,last_name}, phones[{phone,type,wa_id}],
    emails[{email,type}], org{company,title}. Only fields Meta actually sent are
    emitted, so every key is optional on the read side.

    This can never raise. It runs on the inbound write path, where losing the
    whole message to a malformed vCard would be far worse than losing the card.
    """
    try:
        if not isinstance(message, dict):
            return None
        contacts = message.get('contacts')
        if not isinstance(contacts, list):
            return None

        out: List[Dict] = []
        for raw in contacts[:MAX_CONTACTS]:
            if not isinstance(raw, dict):
                continue
            entry: Dict = {}

            name_obj = raw.get('name')
            if isinstance(name_obj, dict):
                name = {field: _trim(name_obj.get(field))
                        for field in ('formatted_name', 'first_name', 'last_name')}
                name = {key: value for key, value in name.items() if value}
                if name:
                    entry['name'] = name

            phones = _sanitise_rows(raw.get('phones'), ('phone', 'type', 'wa_id'))
            if phones:
                entry['phones'] = phones

            emails = _sanitise_rows(raw.get('emails'), ('email', 'type'))
            if emails:
                entry['emails'] = emails

            org_obj = raw.get('org')
            if isinstance(org_obj, dict):
                org = {field: _trim(org_obj.get(field)) for field in ('company', 'title')}
                org = {key: value for key, value in org.items() if value}
                if org:
                    entry['org'] = org

            if entry:
                out.append(entry)
        return out or None
    except Exception:  # noqa: BLE001 — see docstring
        return None


def _sticker(_m: Dict) -> str:
    return '[Sticker]'


def _reaction(m: Dict) -> str:
    return m.get('reaction', {}).get('emoji', '[Reaction]')


def _interactive(m: Dict) -> str:
    interactive = m.get('interactive', {})
    itype = interactive.get('type', '')

    if itype == 'button_reply':
        btn = interactive.get('button_reply', {})
        bid = btn.get('id', '')
        if bid.startswith(('opt_', 'rate_', 'menu_', 'lang_', 'store_')):
            return bid
        return btn.get('title', '[Button Reply]')

    if itype == 'list_reply':
        lr = interactive.get('list_reply', {})
        rid = lr.get('id', '')
        if rid.startswith(('lang_', 'brand_', 'menu_', 'opt_', 'rate_')):
            return rid
        return lr.get('title', '[List Reply]')

    if itype == 'nfm_reply':
        rj = interactive.get('nfm_reply', {}).get('response_json', '')
        return f'[Flow Response: {rj[:50]}...]' if len(rj) > 50 else f'[Flow Response: {rj}]'

    return f'[Interactive: {itype}]'


def _button(m: Dict) -> str:
    return m.get('button', {}).get('text', '[Button]')


def _order(_m: Dict) -> str:
    return '[Order]'


def _system(m: Dict) -> str:
    return m.get('system', {}).get('body', '[System Message]')


def _request_welcome(_m: Dict) -> str:
    return '[User requested to start conversation]'


def _ephemeral(m: Dict) -> str:
    """Handle ephemeral (disappearing) messages.
    
    When a chat has disappearing messages enabled, Meta may deliver the
    message with type='ephemeral'.  The actual content is sometimes nested
    inside the ephemeral object or carried as a sibling field.  We try to
    extract it; if nothing is found, we label it clearly.
    """
    # Some ephemeral messages carry the real payload inside an 'ephemeral' key
    inner = m.get('ephemeral', {})
    if isinstance(inner, dict):
        # Check for nested text
        body = inner.get('text', {}).get('body', '') if isinstance(inner.get('text'), dict) else ''
        if body:
            return body
        # Check for nested message type
        for mtype in ('text', 'image', 'video', 'audio', 'document', 'sticker'):
            if mtype in inner:
                extractor = _EXTRACTORS.get(mtype)
                if extractor:
                    return extractor(inner)
    
    # Fallback: check if text/image/video etc. exist at the top level alongside type=ephemeral
    for mtype in ('text', 'image', 'video', 'audio', 'document'):
        if mtype in m and mtype != 'ephemeral':
            extractor = _EXTRACTORS.get(mtype)
            if extractor:
                result = extractor(m)
                if result and result not in ('[Image]', '[Video]', '[Audio]', '[Document]'):
                    return result
    
    return '[Disappearing Message — content not available via Business API]'


def _referral(m: Dict) -> str:
    ref = m.get('referral', {})
    source = ref.get('source_type', 'unknown')
    headline = ref.get('headline', '')
    return f'[Referral: {source}] {headline}'.strip() if headline else f'[Referral: {source}]'


def _ad_click(m: Dict) -> str:
    ref = m.get('referral', {})
    return f'[Ad Click: {ref.get("source_url", "")}]' if ref.get('source_url') else '[Ad Click]'


def _product(m: Dict) -> str:
    prod = m.get('product', m.get('product_inquiry', {}))
    cid = prod.get('catalog_id', '')
    pid = prod.get('product_retailer_id', '')
    return f'[Product: {cid}/{pid}]' if cid else '[Product]'


def _poll(m: Dict) -> str:
    q = m.get('poll', {}).get('question', '')
    return f'[Poll: {q[:60]}]' if q else '[Poll]'


def _edit(m: Dict) -> str:
    """Handle edit message webhook — user edited a previously sent message."""
    edit_data = m.get('text', {})
    new_body = edit_data.get('body', '')
    edited_msg_id = m.get('context', {}).get('id', '')
    if new_body:
        return f'[Edited] {new_body}'
    return f'[Message edited: {edited_msg_id}]' if edited_msg_id else '[Message edited]'


def _revoke(m: Dict) -> str:
    """Handle revoke message webhook — user deleted a previously sent message.

    Content only. The join back to the message that was deleted lives in
    ``handler._apply_revoke`` (two-tier: an exact wamid when Meta supplies one, else a
    single-candidate recency inference), which is also what writes ``isRevoked`` and the
    ``revokesMessageId`` back-link. Resolution is not a content extractor's job, so this
    label is unchanged regardless of whether the target resolved.
    """
    return '[Message deleted by sender]'


def extract_unsupported_content(message: Dict) -> str:
    """Extract info from unsupported message types.

    WhatsApp marks several message categories as 'unsupported' in the
    Business API webhook, most notably OTP / authentication templates
    sent by Meta itself.  We detect common patterns so the inbox can
    render a friendlier label instead of a generic error.
    
    Common causes of unsupported:
    - OTP / authentication templates (error 131051)
    - Disappearing / ephemeral messages sent to API numbers
    - Multi-image bundles
    - Polls, view-once, some interactive subtypes
    - Messages between two WABA/Cloud API numbers
    """
    errors = message.get('errors', [])

    # What Meta itself claims the message was. `unknown` (or absent) is the measured
    # case and is deliberately NOT in KNOWN_TYPES, so it stays here.
    _unsupported = message.get('unsupported')
    if not isinstance(_unsupported, dict):
        _unsupported = {}
    declared_type = _unsupported.get('type') or _unsupported.get('raw_type') or ''

    # ── Detect OTP / authentication template ──
    for error in errors:
        code = error.get('code', 0)
        # Meta puts the human-readable detail at errors[].error_data.details and
        # never at the top level — measured on 126/126 131051 payloads. Reading only
        # the top level left `details` empty, which is what kept the OTP and
        # ephemeral keyword branches below unreachable. Same precedent as the status
        # webhook's error read.
        details = error.get('details') or (error.get('error_data') or {}).get('details', '')
        title = error.get('title', '')
        error_text = (details or title or '').lower()

        # The message was revoked or expired before Meta could hand it over. Needs its
        # own branch ahead of 131051: with `details` now populated it would otherwise
        # fall through and print Meta's raw sentence.
        if code == 131060:
            return '[Unsupported: This message is no longer available]'

        if code == 131051 or 'not supported' in error_text:
            if any(kw in error_text for kw in ('otp', 'authentication', 'security', 'verification')):
                return '[Unsupported: OTP or authentication message — content hidden by WhatsApp for security]'
            if code == 131051 and declared_type in ('', 'unknown'):
                return UNSUPPORTED_UNKNOWN
            # A 131051 naming some other type has never been measured; keep the
            # interpolated text rather than inventing a label for it.
            return f'[Unsupported: {details or title or "Message type not supported (error 131051)"}]'

        if 'ephemeral' in error_text or 'disappearing' in error_text:
            return '[Unsupported: Disappearing message — disable disappearing messages in this chat to fix]'

        if details:
            return f'[Unsupported: {details}]'
        if title:
            return f'[Unsupported: {title}]'

    # ── Try to detect message subtype from payload keys ──
    # Many "unsupported" messages still carry useful nested data

    # View-once messages (photos/videos sent as view-once)
    if 'image' in message or 'video' in message or 'audio' in message:
        media_type = 'image' if 'image' in message else ('video' if 'video' in message else 'audio')
        media = message.get(media_type, {})
        caption = media.get('caption', '')
        if caption:
            return f'[View-once {media_type}] {caption}'
        return f'[View-once {media_type} — content hidden by WhatsApp]'

    # Sticker in unsupported wrapper
    if 'sticker' in message:
        return '[Sticker]'

    # Poll messages
    if 'poll' in message:
        q = message['poll'].get('question', '')
        return f'[Poll: {q[:60]}]' if q else '[Poll]'

    # Reaction in unsupported wrapper
    if 'reaction' in message:
        emoji = message['reaction'].get('emoji', '')
        return f'[Reaction: {emoji}]' if emoji else '[Reaction]'

    # Location in unsupported wrapper
    if 'location' in message:
        loc = message['location']
        return f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"

    # Contacts in unsupported wrapper
    if 'contacts' in message:
        return _contacts_label(message)

    # Document in unsupported wrapper
    if 'document' in message:
        fname = message['document'].get('filename', '')
        return f'[Document: {fname}]' if fname else '[Document]'

    # Interactive in unsupported wrapper
    if 'interactive' in message:
        itype = message['interactive'].get('type', '')
        return f'[Interactive: {itype}]' if itype else '[Interactive message]'

    if 'referral' in message:
        src = message['referral'].get('source_type', '')
        if src:
            return f'[Referral from {src}]'

    ctx = message.get('context', {})
    if ctx.get('referred_product'):
        return '[Product Inquiry]'

    # Try to extract any text content from the message
    for key in ('text', 'caption', 'body'):
        val = message.get(key, {})
        if isinstance(val, dict):
            body = val.get('body', '')
            if body:
                return body
        elif isinstance(val, str) and val:
            return val

    # Check for forwarded/frequently_forwarded context — likely a view-once or multi-image
    if ctx.get('forwarded') or ctx.get('frequently_forwarded'):
        return '[Forwarded message — content not available via Business API]'

    # Log the full message keys for debugging unknown unsupported types
    logger.warning(json.dumps({
        'event': 'unsupported_message_no_detail',
        'messageKeys': list(message.keys()),
        'errors': errors,
    }))

    return '[Message type not supported by WhatsApp Business API]'


# Dispatch table
_EXTRACTORS = {
    'text': _text, 'image': _image, 'video': _video, 'audio': _audio,
    'document': _document, 'location': _location, 'contacts': _contacts,
    'sticker': _sticker, 'reaction': _reaction, 'interactive': _interactive,
    'button': _button, 'order': _order, 'system': _system,
    'unsupported': lambda m: extract_unsupported_content(m),
    'request_welcome': _request_welcome, 'ephemeral': _ephemeral,
    'referral': _referral, 'ad_click': _ad_click,
    'product': _product, 'product_inquiry': _product, 'poll': _poll,
    'edit': _edit, 'revoke': _revoke,
}

# The one source of truth for "is this a type we can actually render". The handler's
# unsupported-type recovery checks membership here rather than keeping a second
# hand-copied list — a duplicate list is how `edit`/`revoke` ended up named in a log
# warning while being unreachable. Note `unknown` is absent on purpose.
KNOWN_TYPES = frozenset(_EXTRACTORS)
