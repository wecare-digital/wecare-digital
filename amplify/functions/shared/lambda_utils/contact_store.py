"""One contact store for every channel: find the person, whatever minted their row.

`ContactsTable` is the only person store. The WhatsApp inbox, WhatsApp catalog orders,
WhatsApp Flows and the website checkout all resolve a customer to the same row, and this
module is how they do it.

Why a lookup needs more than one step
-------------------------------------
Rows in the table were minted by different writers, so one person's row can carry any of
these ids:

    wa{digits}           inbound WhatsApp (`_deterministic_contact_id`)
    uuid5(sub)           website profile save (customer-profile)
    uuid4                staff create (core/contacts)
    uuid5(phone|email)   blog subscribe

Readers that re-derived one scheme by hand (for example a `get_item` on `wa{digits}`) missed
every row minted by the others. The phone is the one attribute every writer stores, so
`lookup` tries the cheap deterministic key first and then the `phone-index` GSI, using every
spelling of the number that has been written: `+digits` (the canonical form), bare digits
(Meta's `wa_id`) and the caller's own text.

Writes go the other way. `canonical_phone` gives the one spelling new writes should store,
so the `phone-index` lookups of later readers keep converging on the same row.

Soft-deleted rows (`deletedAt` / `isDeleted`) are skipped, matching the inbound handler.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, shared_tables

PHONE_INDEX = 'phone-index'
BSUID_INDEX = 'bsuid-index'


class IdentityConflict(RuntimeError):
    """More than one live canonical contact claims the same strong identity."""

    def __init__(self, identity: str, contact_ids: Iterable[str]):
        ids = tuple(sorted({str(value).strip() for value in contact_ids if str(value).strip()}))
        self.identity = identity
        self.contact_ids = ids
        super().__init__(f'identity conflict for {identity}: {len(ids)} live contacts')


_MIN_DIGITS = 7
_MAX_DIGITS = 15
_NON_DIGIT = re.compile(r'\D+')


def table_name() -> str:
    """The contacts table for this execution environment."""
    return shared_tables.CONTACTS.name()


def digits(phone: Any) -> str:
    """The phone as bare digits, or `''` when it is not a plausible number (7 to 15 digits).

    No country code is inferred. A 10-digit Indian mobile stays 10 digits, because guessing
    `+91` is how a foreign number gets locked onto the wrong person.
    """
    text = _NON_DIGIT.sub('', str(phone or ''))
    return text if _MIN_DIGITS <= len(text) <= _MAX_DIGITS else ''


def canonical_phone(phone: Any) -> str:
    """The one spelling new contact writes store: `+` followed by digits, or `''`."""
    value = digits(phone)
    return f'+{value}' if value else ''


def phone_variants(phone: Any) -> List[str]:
    """Every spelling a stored `phone` may carry, canonical first, without duplicates."""
    out: List[str] = []
    value = digits(phone)
    candidates: Iterable[str] = (
        f'+{value}' if value else '',
        value,
        str(phone or '').strip(),
    )
    for candidate in candidates:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def deterministic_id(phone: Any) -> str:
    """The id the inbound handler mints for a phone-only contact: `wa` + digits."""
    value = digits(phone)
    return f'wa{value}' if value else ''


def is_live(row: Optional[Mapping[str, Any]]) -> bool:
    """True for an active canonical row or an in-progress merge source."""
    if not row:
        return False
    if row.get('deletedAt') or row.get('isDeleted'):
        return False
    return str(row.get('mergeState') or '').strip().lower() != 'merged'


def _get(
    table: Any,
    contact_id: str,
    _seen: Optional[set[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Read an explicit contact id, following a completed merge alias to canonical."""
    if not contact_id:
        return None

    seen = set(_seen or ())
    if contact_id in seen:
        return None
    seen.add(contact_id)

    item = table.get_item(
        Key=contact_key.key(contact_id), ConsistentRead=True).get('Item')
    if not item:
        return None

    if str(item.get('mergeState') or '').strip().lower() == 'merged':
        target_id = str(item.get('mergedIntoContactId') or '').strip()
        return _get(table, target_id, seen) if target_id else None
    return item if is_live(item) else None


def find_by_phone(table: Any, phone: Any) -> Optional[Dict[str, Any]]:
    """Return the one canonical live row for ``phone``; fail closed on ambiguity.

    A DynamoDB GSI cannot enforce uniqueness.  Query every known spelling, follow completed
    merge aliases, deduplicate by canonical contact id, and refuse to pick an arbitrary row when
    two live contacts still claim the same number.  Silently taking ``Items[0]`` would let the
    inbox, checkout and Flows disagree about who owns an order or message.
    """
    matches: Dict[str, Dict[str, Any]] = {}
    for variant in phone_variants(phone):
        response = table.query(
            IndexName=PHONE_INDEX,
            KeyConditionExpression=Key('phone').eq(variant),
            Limit=25,
        )
        for item in response.get('Items') or []:
            contact_id = str(item.get('id') or item.get('contactId') or '').strip()
            canonical = _get(table, contact_id) if contact_id else None
            if canonical:
                canonical_id = contact_key.resolve(canonical)
                if canonical_id:
                    matches[canonical_id] = canonical
    if len(matches) > 1:
        raise IdentityConflict(f'phone:{canonical_phone(phone) or digits(phone)}', matches.keys())
    return next(iter(matches.values()), None)


def find_by_bsuid(table: Any, bsuid: Any) -> Optional[Dict[str, Any]]:
    """The one live row on `bsuid-index`; fail closed if a BSUID is duplicated."""
    value = str(bsuid or '').strip()
    if not value:
        return None
    response = table.query(
        IndexName=BSUID_INDEX,
        KeyConditionExpression=Key('bsuid').eq(value),
        Limit=25,
    )
    matches: Dict[str, Dict[str, Any]] = {}
    for item in response.get('Items') or []:
        contact_id = str(item.get('id') or item.get('contactId') or '').strip()
        canonical = _get(table, contact_id) if contact_id else None
        if canonical:
            canonical_id = contact_key.resolve(canonical)
            if canonical_id:
                matches[canonical_id] = canonical
    if len(matches) > 1:
        raise IdentityConflict(f'bsuid:{value}', matches.keys())
    return next(iter(matches.values()), None)


def lookup(table: Any, phone: Any = '', *, contact_id: str = '') -> Optional[Dict[str, Any]]:
    """The one live contact for this person, or None.

    Order: an explicit id, then the deterministic `wa{digits}` key (a consistent read, and
    the row the inbox writes), then `phone-index` (rows minted by the website, staff or blog
    writers). Read errors propagate; callers decide whether a lookup is best-effort.
    """
    row = _get(table, contact_key.resolve(contact_id=contact_id))
    if row:
        return row
    row = _get(table, deterministic_id(phone))
    if row:
        return row
    return find_by_phone(table, phone)


def lookup_id(table: Any, phone: Any = '', *, contact_id: str = '') -> str:
    """`lookup`, reduced to the canonical contact id (`''` when there is no row)."""
    return contact_key.resolve(lookup(table, phone, contact_id=contact_id))
