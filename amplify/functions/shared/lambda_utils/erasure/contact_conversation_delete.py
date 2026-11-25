"""Delete a whole inbox conversation AND its contact so the number can be re-added.

This extends per-message inbox deletion (`inbox_delete`) to the contact.
An unconverted contact with chat history can be eligible. Retain contacts with:

* verified/registered customer (see VERIFIED_FIELDS below),
* payment or financial linkage: invoices, orders, payment fields or payment
  evidence in any message, or a linkage that cannot be read,
* legal lock (any lockedReason other than 'created') or a retention hold.

Fields that mark a verified/registered customer, written by customer-registration,
customer-profile and customer-whatsapp-auth: ``checkoutCustomerId`` and
``cognitoSub`` (Cognito subject), ``identityClaimedAt`` (profile claim),
``phoneVerifiedAt`` (WhatsApp OTP), and ``fieldSources.phone`` equal to
``PAYMENT_VERIFIED``. ``bsuid``, ``lastInboundMessageAt`` and ``emailVerifiedAt``
are NOT evidence: they only show the number messaged us or subscribed to a blog.

Deletion order: audit and conditionally reserve the exact eligible contact first,
then S3 message media
(exact keys only; the bucket is versioned so delete markers are written and
older versions remain), source rows, canonical MessagesTable rows, extra
per-contact rows (for example scheduled messages), ConversationMeta, identity
claims (PHONE, EMAIL and scoped WHATSAPP_BSUID owned by this contact), and the
ContactsTable row LAST. A failure before the last step keeps the contact row,
so the operation can be run again. The reservation serializes this operation;
it is not a cross-service lock on unrelated producers. Provider (Meta) copies
and backups are not erased.

All dependencies are injected so the policy runs without AWS.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from botocore.exceptions import ClientError

from lambda_utils import identity_claims
from lambda_utils.ecommerce import contact_payment_links
from lambda_utils.erasure import inbox_delete

VERIFIED_FIELDS = ("checkoutCustomerId", "cognitoSub", "identityClaimedAt", "phoneVerifiedAt")
VERIFIED_PHONE_SOURCE = "PAYMENT_VERIFIED"
BSUID_CLAIM_PREFIX = "WHATSAPP_BSUID#"
_RESERVATION = "inboxDeleteOperation"
# Exceeds the maximum Lambda invocation time. A timed-out owner cannot still
# be making destructive calls after a replacement is allowed to acquire.
_RESERVATION_SECONDS = 20 * 60
_PROTECTED_SNAPSHOT = (
    "createdAt", "locked", "lockedReason", "tags", "fieldSources",
    "phone", "email", "whatsappIdentities", *VERIFIED_FIELDS,
)


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


def _has_payment_fields(row: Mapping[str, Any]) -> bool:
    return any(row.get(f) not in (None, "", [], {}) for f in inbox_delete._PAYMENT_FIELDS)


def _pending(contact: Mapping[str, Any]) -> bool:
    reservation = contact.get(_RESERVATION)
    return isinstance(reservation, Mapping) and reservation.get("started") is True


def _active(contact: Mapping[str, Any], now: int) -> bool:
    reservation = contact.get(_RESERVATION)
    if not isinstance(reservation, Mapping):
        return _RESERVATION in contact  # unknown state must not be overwritten
    expires = reservation.get("expiresAt")
    try:
        return expires is None or expires > now
    except TypeError:
        return True


def _snapshot_condition(
    row: Mapping[str, Any], fields: tuple[str, ...], primary_key: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Compare exact observed safety fields, including absence vs null."""
    names = {"#id": primary_key}
    values = {}
    parts = ["attribute_exists(#id)"]
    for i, field in enumerate(fields):
        name, value = f"#f{i}", f":v{i}"
        names[name] = field
        if field in row:
            parts.append(f"{name} = {value}")
            values[value] = row[field]
        else:
            parts.append(f"attribute_not_exists({name})")
    return " AND ".join(parts), names, values


def _observed_condition(row, fields, primary_key):
    condition, names, values = _snapshot_condition(row, fields, primary_key)
    kwargs = {"ConditionExpression": condition, "ExpressionAttributeNames": names}
    if values:
        kwargs["ExpressionAttributeValues"] = values
    return kwargs


def _conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _incomplete() -> inbox_delete.DeleteDecision:
    return _refuse(
        "CONTACT_DELETE_INCOMPLETE",
        "Deletion may be incomplete. Refresh and run it again.", 503,
    )


def _still_same(row, observed, fields):
    return all((field in row) == (field in observed)
               and row.get(field) == observed.get(field) for field in fields)


def _finish_reservation(table, key, reservation, *, keep_pending):
    """Relinquish only this exact reservation and retain its audit link on retry."""
    names = {"#operation": _RESERVATION}
    values = {":held": reservation}
    expr = "REMOVE #operation"
    if keep_pending:
        expr = "SET #operation = :pending"
        values[":pending"] = {**reservation, "expiresAt": 0, "started": True}
    table.update_item(
        Key=key, UpdateExpression=expr,
        ConditionExpression="#operation = :held",
        ExpressionAttributeNames=names, ExpressionAttributeValues=values,
    )


def _leftovers_remain(contact_id: str, claim_keys: list[str], tables: list[Any],
                      claims_table: Any) -> bool:
    if any(inbox_delete._scan_conversation(t, contact_id) for t in tables):
        return True
    return any((claims_table.get_item(Key={"claimKey": k}, ConsistentRead=True)
                .get("Item") or {}).get("contactId") == contact_id for k in claim_keys)


def _guard(contact: Mapping[str, Any], meta: Mapping[str, Any], rows: list[Mapping[str, Any]],
           invoices: Any, orders: Any) -> inbox_delete.DeleteDecision | None:
    # Treat only the canonical creation marker as exempt. Case variants
    # lack proof that the lock was issued by the creation path.
    if ("locked" in contact and contact["locked"] is not False
            and contact.get("lockedReason") != "created"):
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
    # Structured payment fields only. Free text such as "fee" or "booking" in a
    # lead's chat is not evidence of payment, so no keyword matching here.
    if any(_has_payment_fields(r) for r in rows):
        return _refuse("CONTACT_DELETE_FINANCIAL_RETENTION",
                       "This chat has payment messages that must be retained.")
    return None


def _recheck_media_rows(tables_and_rows) -> inbox_delete.DeleteDecision | None:
    """Re-read exact source rows before S3 writes; the scan is not a snapshot."""
    for table, rows in tables_and_rows:
        for observed in rows:
            if not str(observed.get("s3Key") or "").strip():
                continue
            fresh = table.get_item(
                Key={"id": observed["id"]}, ConsistentRead=True,
            ).get("Item") or {}
            if not fresh or not _still_same(fresh, observed, ("contactId", "s3Key")):
                return _refuse(
                    "CONTACT_DELETE_STATE_CHANGED",
                    "Message media ownership changed before deletion. Refresh and review it again.",
                )
            if _has_payment_fields(fresh):
                return _refuse(
                    "CONTACT_DELETE_FINANCIAL_RETENTION",
                    "This chat has payment messages that must be retained.",
                )
    return None


def _delete_rows(table: Any, rows: list[Mapping[str, Any]], key_names: tuple[str, ...],
                 contact_id: str) -> int:
    count = 0
    for row in rows:
        if row.get("contactId") != contact_id:
            raise ValueError("Message identity changed")
        key = {k: row[k] for k in key_names}
        # Do not remove a replaced row or newly added payment evidence.
        table.delete_item(
            Key=key,
            **_observed_condition(
                row, ("contactId", "s3Key", *inbox_delete._PAYMENT_FIELDS), key_names[0],
            ),
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
    key = {"id": contact_id}
    now = int(time.time())
    was_pending = False
    try:
        contact = contacts_table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        if not contact:
            return _refuse("CONTACT_NOT_FOUND", "This contact no longer exists.", 404)
        if _active(contact, now):
            return _refuse("CONTACT_DELETE_IN_PROGRESS",
                           "A deletion is already running. Refresh and try again later.")
        was_pending = _pending(contact)
        meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        canonical = inbox_delete._scan_conversation(canonical_table, contact_id)
        inbound = inbox_delete._scan_conversation(inbound_table, contact_id)
        outbound = inbox_delete._scan_conversation(outbound_table, contact_id)
        extras = {name: inbox_delete._scan_conversation(tbl, contact_id)
                  for name, (tbl, _keys) in extra_tables.items()}
        protected_rows = [*canonical, *inbound, *outbound,
                          *(row for rows in extras.values() for row in rows)]
        guard = _guard(contact, meta, protected_rows, invoices_table, orders_table)
        if guard:
            return _incomplete() if was_pending else guard
    except Exception:
        if was_pending:
            return _incomplete()
        return _refuse("CONTACT_DELETE_LINKAGE_UNKNOWN",
                       "Conversation, identity or payment inventory could not be verified.", 503)

    claim_keys = claim_keys_for(contact)
    media_keys = _media_keys([*canonical, *inbound, *outbound])
    counts = {"messages": len(canonical), "sourceRows": len(inbound) + len(outbound),
              "mediaObjects": 0, "extraRows": sum(len(v) for v in extras.values())}
    reservation = None
    started = was_pending
    finished = False

    try:
        prior = contact.get(_RESERVATION) or {}
        audit_id = audit(
            action="contact.delete_with_conversation",
            actor=actor, resource_type="contact", resource_id=contact_id,
            details={"messages": counts["messages"], "sourceRows": counts["sourceRows"],
                     "mediaKeys": len(media_keys), "claimCount": len(claim_keys),
                     "hadConversationMeta": bool(meta), "erasureComplete": False,
                     "priorAuditId": prior.get("auditId") if was_pending else None})
        if not audit_id:
            return _incomplete() if was_pending else _refuse(
                "CONTACT_DELETE_AUDIT_UNAVAILABLE",
                "A required audit record could not be written.", 503)

        # The reservation compares the exact eligibility/identity snapshot at
        # write time, not a second independently maintained eligibility test.
        candidate = {"owner": uuid4().hex, "expiresAt": int(time.time()) + _RESERVATION_SECONDS,
                     "auditId": str(audit_id), "started": was_pending}
        protected = (*_PROTECTED_SNAPSHOT, _RESERVATION)
        condition, names, values = _snapshot_condition(contact, protected, "id")
        names["#operation"] = _RESERVATION
        values[":operation"] = candidate
        try:
            contacts_table.update_item(
                Key=key, UpdateExpression="SET #operation = :operation",
                ConditionExpression=condition,
                ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        except ClientError as exc:
            if not _conditional_failure(exc):
                raise
            return _incomplete() if was_pending else _refuse(
                "CONTACT_DELETE_STATE_CHANGED",
                "The contact changed before deletion started. Refresh and review it again.")
        reservation = candidate
        reserved_row = {**contact, _RESERVATION: reservation}

        # Recheck the contact and other safeguards after obtaining ownership.
        # A second invocation cannot proceed while this operation is active.
        fresh = contacts_table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        fresh_meta = meta_table.get_item(
            Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
        if not fresh or not _still_same(fresh, reserved_row, protected):
            return _incomplete() if was_pending else _refuse(
                "CONTACT_DELETE_STATE_CHANGED",
                "The contact changed before deletion started. Refresh and review it again.")
        recheck = _guard(fresh, fresh_meta, protected_rows, invoices_table, orders_table)
        if recheck:
            return _incomplete() if was_pending else recheck

        # Persist that effects may happen *before* the first effect. On a
        # crash/timeout a later authorized retry re-inventories exact keys.
        candidate = {**reservation, "started": True}
        condition, names, values = _snapshot_condition(fresh, protected, "id")
        names["#operation"] = _RESERVATION
        values[":operation"] = candidate
        try:
            contacts_table.update_item(
                Key=key, UpdateExpression="SET #operation = :operation",
                ConditionExpression=condition,
                ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        except ClientError as exc:
            if not _conditional_failure(exc):
                raise
            return _incomplete() if was_pending else _refuse(
                "CONTACT_DELETE_STATE_CHANGED",
                "The contact changed before deletion started. Refresh and review it again.")
        reservation = candidate
        started = True
        reserved_row[_RESERVATION] = reservation

        def check_current(*, recheck_finance=False):
            current = contacts_table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
            if not current or not _still_same(current, reserved_row, protected):
                raise RuntimeError("Contact deletion reservation or eligibility changed")
            current_meta = meta_table.get_item(
                Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
            if "retention-hold" in (current_meta.get("tags") or []):
                raise RuntimeError("Conversation retention hold changed")
            if recheck_finance and _guard(current, current_meta, [], invoices_table, orders_table):
                raise RuntimeError("Contact retention or financial eligibility changed")
            return current_meta

        check_current()
        if media_keys:
            try:
                media_refusal = _recheck_media_rows((
                    (canonical_table, canonical), (inbound_table, inbound),
                    (outbound_table, outbound),
                ))
            except Exception:
                media_refusal = _refuse(
                    "CONTACT_DELETE_LINKAGE_UNKNOWN",
                    "Message media could not be reverified. No deletion was started.", 503,
                )
            if media_refusal:
                # The started marker is durable before any effects, but this
                # invocation can still prove it made none on this return path.
                started = was_pending
                return _incomplete() if was_pending else media_refusal
        for media_key in media_keys:
            try:
                if delete_media(media_key):
                    counts["mediaObjects"] += 1
            except ValueError:
                continue  # not message-owned storage; never delete it
        check_current()
        _delete_rows(inbound_table, inbound, ("id",), contact_id)
        _delete_rows(outbound_table, outbound, ("id",), contact_id)
        _delete_rows(canonical_table, canonical, ("id",), contact_id)
        for name, rows in extras.items():
            _delete_rows(extra_tables[name][0], rows, extra_tables[name][1], contact_id)
        observed_meta = check_current(recheck_finance=True)
        if observed_meta:
            meta_table.delete_item(
                Key={"conversationId": contact_id},
                **_observed_condition(observed_meta, ("tags",), "conversationId"),
            )
        if check_current():
            return _incomplete()
        for claim_key in claim_keys:
            identity_claims.release(claims_table, claim_key, contact_id)

        # Check for concurrent inserts/claims. Cross-service writers are not
        # fenced by this contact reservation, so do not claim atomic erasure.
        if _leftovers_remain(
                contact_id, claim_keys,
                [canonical_table, inbound_table, outbound_table,
                 *(tbl for tbl, _keys in extra_tables.values())], claims_table):
            return _incomplete()
        if check_current():
            return _incomplete()

        contacts_table.delete_item(
            Key=key, **_observed_condition(reserved_row, protected, "id"),
        )
        finished = True
    except Exception:
        return _incomplete()
    finally:
        if reservation is not None and not finished:
            try:
                _finish_reservation(
                    contacts_table, key, reservation, keep_pending=started,
                )
            except Exception:
                # An ambiguous mutation response or crash leaves the durable
                # reservation in place until expiry; another owner is untouched.
                pass

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
