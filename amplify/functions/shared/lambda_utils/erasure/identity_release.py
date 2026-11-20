"""Free a contact's identity keys so the same phone can be added again.

This is the identity step of an approved erasure. The Admin+MFA gate, approval token
and coordinator dispatch stay in `contacts/handler._delete` and `dispatch.py`; this
module is what the coordinator calls once those checks pass. It takes table objects
so it holds no AWS client and can be tested with in-memory tables.

What it removes
---------------
* the ContactsTable row (its `phone-index` / `bsuid-index` GSI entries go with it, and
  so does the deterministic `wa{digits}` / `wab{bsuid}` primary key);
* every IdentityClaimsTable entry (`PHONE#...`, `EMAIL#...`) that the row owned, so
  `claim_identities` succeeds for a new contact with the same number;
* merge links: alias rows whose `mergedIntoContactId` is this contact, and their claims.

What it never touches
---------------------
Payment, invoice, order and Razorpay tables are not parameters. A contact that is locked,
or whose row is already a merge alias of another contact, is refused.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from lambda_utils import contact_store, identity_claims

CLAIM_PHONE_FIELDS = ("phone", "mergedSourcePhone", "primaryPhone")
CLAIM_EMAIL_FIELDS = ("email",)


class ErasureRefused(RuntimeError):
    """The row must be retained. Nothing was deleted."""


def _claim_keys(row: Mapping[str, Any]) -> List[str]:
    keys: List[str] = []
    for field in CLAIM_PHONE_FIELDS:
        value = row.get(field)
        if value:
            k = identity_claims.key("PHONE", value)
            if k and k not in keys:
                keys.append(k)
    for field in CLAIM_EMAIL_FIELDS:
        value = row.get(field)
        if value:
            k = identity_claims.key("EMAIL", value)
            if k and k not in keys:
                keys.append(k)
    return keys


def _merge_aliases(contacts_table: Any, contact_id: str) -> List[Dict[str, Any]]:
    from boto3.dynamodb.conditions import Attr

    out: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {"FilterExpression": Attr("mergedIntoContactId").eq(contact_id)}
    while True:
        page = contacts_table.scan(**kwargs)
        out.extend(page.get("Items") or [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return out
        kwargs["ExclusiveStartKey"] = start


def _owned_claims_for(claims_table: Any, row: Mapping[str, Any], owner_id: str) -> int:
    released = 0
    for claim_key in _claim_keys(row):
        if identity_claims.release(claims_table, claim_key, owner_id):
            released += 1
    return released


def release_contact_identity(
    *, contacts_table: Any, claims_table: Any, contact_id: str,
    row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Delete the contact row, its identity claims and its merge aliases.

    Idempotent: a missing row is treated as already erased and returns zero counts.
    """
    contact_id = str(contact_id or "").strip()
    if not contact_id:
        raise ErasureRefused("contact id is required")
    row = dict(row or contacts_table.get_item(Key={"id": contact_id}, ConsistentRead=True).get("Item") or {})
    if not row:
        return {"contactRows": 0, "claims": 0, "aliasRows": 0}
    if row.get("locked"):
        raise ErasureRefused("contact is locked for legal retention")
    if str(row.get("mergedIntoContactId") or "").strip():
        raise ErasureRefused("contact is a merge alias; erase the canonical contact")

    # Claims first: a crash between the steps leaves an orphan row (retryable, still
    # blocks re-add) rather than a live-looking row with no claim.
    aliases = _merge_aliases(contacts_table, contact_id)
    alias_count = 0
    claim_count = 0
    for alias in aliases:
        alias_id = str(alias.get("id") or "")
        if not alias_id:
            continue
        # An alias may have handed its claims to the canonical contact, so try both owners.
        claim_count += _owned_claims_for(claims_table, alias, alias_id)
        claim_count += _owned_claims_for(claims_table, alias, contact_id)
        contacts_table.delete_item(Key={"id": alias_id})
        alias_count += 1

    claim_count += _owned_claims_for(claims_table, row, contact_id)
    # Also free the canonical spellings derived from the stored phone.
    for variant in contact_store.phone_variants(row.get("phone")):
        k = identity_claims.key("PHONE", variant)
        if k and identity_claims.release(claims_table, k, contact_id):
            claim_count += 1
    contacts_table.delete_item(Key={"id": contact_id})
    return {"contactRows": 1, "claims": claim_count, "aliasRows": alias_count}
