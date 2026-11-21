"""Delete a whole inbox conversation AND its contact so the number can be re-added.

This extends per-message inbox deletion (`inbox_delete`) to the contact. Only
these cases refuse; everything else, including an unconverted contact with a
long chat history, is deletable:

* verified/registered customer (see VERIFIED_FIELDS below),
* payment or financial linkage: invoices, orders, payment fields or payment
  text in any message, or a linkage that cannot be read,
* legal lock (any lockedReason other than 'created') or a retention hold.

Fields that mark a verified/registered customer, written by customer-registration,
customer-profile and customer-whatsapp-auth: ``checkoutCustomerId`` and
``cognitoSub`` (Cognito subject), ``identityClaimedAt`` (profile claim),
``phoneVerifiedAt`` (WhatsApp OTP), and ``fieldSources.phone`` equal to
``PAYMENT_VERIFIED``. ``bsuid``, ``lastInboundMessageAt`` and ``emailVerifiedAt``
are NOT evidence: they only show the number messaged us or subscribed to a blog.

Deletion order (retry-safe): audit first (fail closed), then S3 message media
(exact keys only; the bucket is versioned so delete markers are written and
older versions remain), source rows, canonical MessagesTable rows, extra
per-contact rows (for example scheduled messages), ConversationMeta, identity
claims (PHONE, EMAIL and scoped WHATSAPP_BSUID owned by this contact), and the
ContactsTable row LAST. A failure before the last step keeps the contact row,
so the operation can be run again. Provider (Meta) copies and backups are not
erased.

All dependencies are injected so the policy runs without AWS.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from lambda_utils import identity_claims
from lambda_utils.ecommerce import contact_payment_links
from lambda_utils.erasure import inbox_delete

VERIFIED_FIELDS = ("checkoutCustomerId", "cognitoSub", "identityClaimedAt", "phoneVerifiedAt")
VERIFIED_PHONE_SOURCE = "PAYMENT_VERIFIED"
BSUID_CLAIM_PREFIX = "WHATSAPP_BSUID#"


def _refuse(code: str, reason: str, status: int = 409) -> inbox_delete.DeleteDecision:
    return inbox_delete.DeleteDecision(status, {
        "errorCode": code, "error": reason, "rowDeleted": False,
        "contactDeleted": False, "erasureComplete": False,
    })


def is_verified_customer(contact: Mapping[str, Any]) -> bool:
    if any(contact.get(f) not in (None, "", [], {}) for f in VERIFIED_FIELDS):
        return True
    sources = contact.get("fieldSources")
    if isinstance(sources, Mapping):
        phone = sources.get("phone")
        if isinstance(phone, Mapping):
            phone = phone.get("source")
        return str(phone or "").strip().upper() == VERIFIED_PHONE_SOURCE
    return False


def claim_keys_for(contact: Mapping[str, Any]) -> list[str]:
    """Every identity-registry key that would block this contact being recreated."""
    keys = [identity_claims.key("PHONE", contact.get("phone")),
            identity_claims.key("EMAIL", contact.get("email"))]
    profiles = contact.get("whatsappIdentities")
    if isinstance(profiles, Mapping):
        for portfolio, profile in profiles.items():
            bsuid = str((profile or {}).get("bsuid") or "").strip() if isinstance(profile, Mapping) else ""
            if portfolio and bsuid:
                keys.append(f"{BSUID_CLAIM_PREFIX}{portfolio}#{bsuid}")
    return list(dict.fromkeys(k for k in keys if k))


def _media_keys(rows: list[Mapping[str, Any]]) -> list[str]:
    return list(dict.fromkeys(
        str(r.get("s3Key")).strip() for r in rows if str(r.get("s3Key") or "").strip()))


def _guard(contact: Mapping[str, Any], meta: Mapping[str, Any], rows: list[Mapping[str, Any]],
           invoices: Any, orders: Any) -> inbox_delete.DeleteDecision | None:
    if bool(contact.get("locked")) and str(contact.get("lockedReason") or "").lower() != "created":
        return _refuse("CONTACT_DELETE_LOCKED",
                       "This contact is locked for legal or payment retention.")
    if "retention-hold" in (meta.get("tags") or []) or "retention-hold" in (contact.get("tags") or []):
        return _refuse("CONTACT_DELETE_RETENTION_HOLD", "This contact has a retention hold.")
    if is_verified_customer(contact):
        return _refuse("CONTACT_DELETE_VERIFIED_CUSTOMER",
                       "This is a verified customer and cannot be deleted.")
    try:
        linked = contact_payment_links.has_payment_links(
            invoices_table=invoices, orders_table=orders, contact_row=contact)
    except Exception:
        return _refuse("CONTACT_DELETE_LINKAGE_UNKNOWN",
                       "Payment history could not be verified, so nothing was deleted.", 503)
    if linked.blocked:
        return _refuse("CONTACT_DELETE_FINANCIAL_RETENTION",
                       "This contact has payment or order history.")
    if any(inbox_delete._is_financial(r) for r in rows):
        return _refuse("CONTACT_DELETE_FINANCIAL_RETENTION",
                       "This chat has payment messages that must be retained.")
    return None


def _delete_rows(table: Any, rows: list[Mapping[str, Any]], key_names: tuple[str, ...],
                 contact_id: str) -> int:
    count = 0
    for row in rows:
        key = {k: row[k] for k in key_names}
        table.delete_item(
            Key=key,
            ConditionExpression="#cid = :cid",
            ExpressionAttributeNames={"#cid": "contactId"},
            ExpressionAttributeValues={":cid": contact_id},
        )
        count += 1
    return count


def delete_contact_conversation(
    *,
    contact_id: str,
    actor: str,
    canonical_table: Any,
    inbound_table: Any,
    outbound_table: Any,
    contacts_table: Any,
    meta_table: Any,
    claims_table: Any,
    invoices_table: Any,
    orders_table: Any,
    audit: Callable[..., Any],
    delete_media: Callable[[str], Any],
    extra_tables: Mapping[str, tuple[Any, tuple[str, ...]]] | None = None,
) -> inbox_delete.DeleteDecision:
    """Remove the chat, media, identity claims and contact of an eligible contact.

    ``delete_media(key)`` removes one exact message-owned S3 key and raises
    ValueError for a key outside message storage (such keys are skipped).
    ``extra_tables`` maps a name to (table, key attribute names); rows with a
    matching contactId are removed.
    """
    contact_id = str(contact_id or "").strip()
    if not contact_id or len(contact_id) > 250 or not actor:
        return _refuse("CONTACT_DELETE_REQUEST_INVALID",
                       "A verified actor and exact contact ID are required.", 400)
    extra_tables = extra_tables or {}
    try:
        contact = contacts_table.get_item(
            Key={"id": contact_id}, ConsistentRead=True).get("Item") or {}
        if not contact:
            return _refuse("CONTACT_NOT_FOUND", "This contact no longer exists.", 404)
        meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        canonical = inbox_delete._scan_conversation(canonical_table, contact_id)
        inbound = inbox_delete._scan_conversation(inbound_table, contact_id)
        outbound = inbox_delete._scan_conversation(outbound_table, contact_id)
        extras = {name: inbox_delete._scan_conversation(tbl, contact_id)
                  for name, (tbl, _keys) in extra_tables.items()}
        guard = _guard(contact, meta, [*canonical, *inbound, *outbound],
                       invoices_table, orders_table)
        if guard:
            return guard
    except Exception:
        return _refuse("CONTACT_DELETE_LINKAGE_UNKNOWN",
                       "Conversation, identity or payment inventory could not be verified.", 503)

    claim_keys = claim_keys_for(contact)
    media_keys = _media_keys([*canonical, *inbound, *outbound])
    counts = {"messages": len(canonical), "sourceRows": len(inbound) + len(outbound),
              "mediaObjects": 0, "extraRows": sum(len(v) for v in extras.values())}

    try:
        audit_id = audit(
            action="contact.delete_with_conversation",
            actor=actor, resource_type="contact", resource_id=contact_id,
            details={"messages": counts["messages"], "sourceRows": counts["sourceRows"],
                     "mediaKeys": len(media_keys), "claimCount": len(claim_keys),
                     "hadConversationMeta": bool(meta), "erasureComplete": False})
        if not audit_id:
            return _refuse("CONTACT_DELETE_AUDIT_UNAVAILABLE",
                           "A required audit record could not be written.", 503)

        # Re-read guards at execution time; a hold or lock may have been added.
        fresh = contacts_table.get_item(
            Key={"id": contact_id}, ConsistentRead=True).get("Item") or {}
        fresh_meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        if not fresh:
            return _refuse("CONTACT_NOT_FOUND", "This contact no longer exists.", 404)
        recheck = _guard(fresh, fresh_meta, [], invoices_table, orders_table)
        if recheck:
            return recheck

        for key in media_keys:
            try:
                if delete_media(key):
                    counts["mediaObjects"] += 1
            except ValueError:
                continue  # not message-owned storage; never delete it
        _delete_rows(inbound_table, inbound, ("id",), contact_id)
        _delete_rows(outbound_table, outbound, ("id",), contact_id)
        _delete_rows(canonical_table, canonical, ("id",), contact_id)
        for name, rows in extras.items():
            _delete_rows(extra_tables[name][0], rows, extra_tables[name][1], contact_id)
        if meta:
            meta_table.delete_item(Key={"conversationId": contact_id})
        for claim_key in claim_keys:
            identity_claims.release(claims_table, claim_key, contact_id)

        # Contact row last, and only if still the same unlocked, unverified row.
        contacts_table.delete_item(
            Key={"id": contact_id}, ConditionExpression="attribute_exists(#id)",
            ExpressionAttributeNames={"#id": "id"})

        leftovers = (
            contacts_table.get_item(Key={"id": contact_id}, ConsistentRead=True).get("Item")
            or inbox_delete._scan_conversation(canonical_table, contact_id)
            or inbox_delete._scan_conversation(inbound_table, contact_id)
            or inbox_delete._scan_conversation(outbound_table, contact_id)
            or any((claims_table.get_item(Key={"claimKey": k}, ConsistentRead=True)
                    .get("Item") or {}).get("contactId") == contact_id for k in claim_keys)
        )
        if leftovers:
            return inbox_delete.DeleteDecision(503, {
                "errorCode": "CONTACT_DELETE_RECONCILIATION_REQUIRED",
                "error": "Some stored rows could not be verified as removed.",
                "contactDeleted": False, "erasureComplete": False})
    except Exception:
        # The contact row is still present unless the final delete succeeded, so a
        # retry is safe. Never claim 'nothing deleted' for an indeterminate result.
        return inbox_delete.DeleteDecision(503, {
            "errorCode": "CONTACT_DELETE_INCOMPLETE",
            "error": "Deletion is incomplete. Refresh and run it again.",
            "rowDeleted": False, "contactDeleted": False, "erasureComplete": False})

    return inbox_delete.DeleteDecision(200, {
        "success": True,
        "contactDeleted": True,
        "contactId": contact_id,
        "messagesDeleted": counts["messages"],
        "sourceRowsDeleted": counts["sourceRows"],
        "mediaObjectsDeleted": counts["mediaObjects"],
        "identityClaimsReleased": True,
        "contactRecreatable": True,
        "auditId": str(audit_id),
        "erasureComplete": False,
        "providerCopiesErased": False,
        "warning": ("Local chat, media (S3 delete markers), identity and contact removed. "
                    "Meta copies, S3 older versions and backups are not erased."),
    })
