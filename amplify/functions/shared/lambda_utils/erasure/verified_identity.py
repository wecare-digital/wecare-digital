"""Guarded two-reviewer local contact/identity removal.

This narrow operation is intentionally NOT full personal-data erasure: retained
audit records, provider copies and backups remain. A contact is eligible only
when there are no stored dependent records, no business/provider identity and
no payment evidence. Any unknown dependency fails closed.

A fresh, exact-record digest is bound to an expiring approval case. A distinct
Admin reviewer approves. Execution atomically consumes the case, deletes the
contact row and releases only phone/email claims owned by that contact.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any, Mapping

from lambda_utils import identity_claims

CASE_SECONDS = 900
MAX_ROWS = 20000
SCOPE_PREFIX = "verified_contact_remove:"
DEPENDENCY_TABLES = (
    "MessagesTable", "WhatsAppInboundTable", "WhatsAppOutboundTable",
    "PaymentsTable", "PaymentAttemptsTable", "InvoicesTable", "OrderTable",
    "FlowSubmissionTable", "FlowDraftTable", "FlowLogTable",
    "CustomerSessionsTable", "ScheduledMessagesTable", "DLQMessagesTable",
    "CrmActivities", "CrmLeads", "CrmOpportunities",
    "VoiceAwsTable", "VoiceCDRTable", "WhatsAppVoiceTable",
    "PstnSoftphoneSessions", "InvoiceAssetsTable", "InvoiceItemsTable",
    "InvoiceDeliveryLogTable",
)
# These are exact reference fields, never free-text substring searches.
DEPENDENCY_FIELDS = (
    "contactId", "customerId", "customerUuid", "checkoutCustomerId",
    "subscriberId", "phone", "senderPhone", "recipientPhone",
    "customerPhone", "paidByPhone", "recipientBsuid", "senderBsuid",
    "bsuid", "email", "customerEmail", "resourceId",
)
PROVIDER_FIELDS = (
    "bsuid", "parentBsuid", "username", "whatsappIdentities", "cognitoSub",
    "checkoutCustomerId", "checkoutDeliveryAddress",
    "profileUsername", "lastPaymentId", "paymentId", "invoiceId", "orderId",
)


class Refused(Exception):
    def __init__(self, code: str, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(code)


def _digest(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _exact_values(contact: Mapping[str, Any]) -> set[str]:
    values = {str(contact.get(field) or "").strip()
              for field in ("id", "contactId", "phone", "email", "customerUuid",
                            "checkoutCustomerId", "subscriberId", "bsuid")}
    phone = str(contact.get("phone") or "")
    digits = "".join(c for c in phone if c.isdigit())
    if digits:
        values.update({digits, "+" + digits})
        if digits.startswith("91") and len(digits) == 12:
            values.add(digits[2:])
    return {v for v in values if v}


def _scan(table: Any) -> list[dict]:
    found = []
    kwargs = {"ConsistentRead": True}
    seen = set()
    while True:
        page = table.scan(**kwargs)
        if not isinstance(page.get("Items"), list):
            raise Refused("ERASURE_INVENTORY_INCOMPLETE", "A dependency read was incomplete.")
        found.extend(page["Items"])
        if len(found) > MAX_ROWS:
            raise Refused("ERASURE_INVENTORY_INCOMPLETE", "A dependency table is too large for verified removal.")
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return found
        key = _digest(cursor)
        if key in seen:
            raise Refused("ERASURE_INVENTORY_INCOMPLETE", "Dependency scan did not advance.")
        seen.add(key)
        kwargs["ExclusiveStartKey"] = cursor


def _validate_target(contact_id: str, tables: Mapping[str, Any]) -> tuple[dict, list[str], str]:
    contacts = tables["ContactsTable"]
    row = contacts.get_item(Key={"id": contact_id}, ConsistentRead=True).get("Item") or {}
    if not row:
        raise Refused("CONTACT_NOT_FOUND", "This contact no longer exists.")
    if str(row.get("id")) != contact_id or row.get("deletedAt") or row.get("mergeState"):
        raise Refused("ERASURE_IDENTITY_UNVERIFIED", "Contact identity or merge status is not eligible.")
    # 'created' marks a default contact-origin lock; manual/legal/paid locks
    # and any retention hold continue to prohibit deletion.
    if row.get("locked") and str(row.get("lockedReason") or "").lower() != "created":
        raise Refused("CONTACT_LOCKED", "A protected contact cannot be deleted.")
    if "retention-hold" in (row.get("tags") or []):
        raise Refused("CONTACT_LOCKED", "The contact is on retention hold.")
    meta = tables["ConversationMetaTable"].get_item(
        Key={"conversationId": contact_id}, ConsistentRead=True).get("Item") or {}
    if meta:
        raise Refused("CONTACT_HAS_HISTORY", "Conversation metadata must be retained or reviewed.")
    # Staff-created phone contacts are linked to Cognito via secure-files, and
    # even a partial provision can exist without checkoutCustomerId. We do not
    # remove or verify Cognito users in this local-only transaction, so a phone
    # contact cannot use this narrow delete path.
    if row.get("phone"):
        raise Refused("ERASURE_EXTERNAL_IDENTITY_REVIEW_REQUIRED",
                      "Phone contacts require a verified Cognito/provider identity release.")
    if any(row.get(field) not in (None, "", [], {}) for field in PROVIDER_FIELDS):
        raise Refused("ERASURE_EXTERNAL_IDENTITY_REVIEW_REQUIRED",
                      "A linked business, checkout, or provider identity needs independent review.")
    claims = []
    claim_table = tables["IdentityClaimsTable"]
    for kind, field in (("PHONE", "phone"), ("EMAIL", "email")):
        key = identity_claims.key(kind, row.get(field))
        if not key:
            continue
        claim = claim_table.get_item(Key={"claimKey": key}, ConsistentRead=True).get("Item") or {}
        if claim:
            if claim.get("contactId") != contact_id:
                raise Refused("ERASURE_IDENTITY_CONFLICT", "An identity claim belongs to another customer.")
            claims.append(key)
    values = _exact_values(row)
    for table_name in DEPENDENCY_TABLES:
        if table_name not in tables:
            raise Refused("ERASURE_INVENTORY_INCOMPLETE", "Required dependency source is missing.")
        for linked in _scan(tables[table_name]):
            if not isinstance(linked, dict):
                raise Refused("ERASURE_INVENTORY_INCOMPLETE", "Unrecognized dependency row.")
            if any(str(linked.get(field) or "").strip() in values
                   for field in DEPENDENCY_FIELDS):
                # Audit evidence is retained and must not be overwritten.
                # A contact with historical audit records is not eligible
                # for complete local removal under this narrow procedure.
                raise Refused("ERASURE_DEPENDENCY_RETAINED",
                              "This contact has linked history or financial evidence.")
    return row, claims, _digest(row)


def _case(table: Any, case_id: str) -> dict:
    if not case_id.startswith(SCOPE_PREFIX):
        raise Refused("ERASURE_CASE_INVALID", "The case is invalid.")
    record = table.get_item(Key={"id": case_id}, ConsistentRead=True).get("Item") or {}
    if not record or int(record.get("expiresAt") or 0) <= int(time.time()):
        raise Refused("ERASURE_CASE_EXPIRED", "The reviewed case has expired.")
    return record


def prepare(*, contact_id: str, actor: str, tables: Mapping[str, Any],
            audit: Any) -> dict:
    row, claims, digest = _validate_target(contact_id, tables)
    case_id = SCOPE_PREFIX + str(uuid.uuid4())
    now = int(time.time())
    log = audit(action="contact.erasure_prepare", actor=actor,
                resource_type="contact", resource_id=contact_id,
                details={"caseId": case_id, "claimCount": len(claims)})
    if not log:
        raise Refused("ERASURE_AUDIT_UNAVAILABLE", "Approval cannot begin without an audit record.")
    tables["SystemConfigTable"].put_item(
        Item={"id": case_id, "contactId": contact_id, "preparedBy": actor,
              "manifestSha256": digest, "status": "PENDING_SECOND_REVIEW",
              "createdAt": now, "expiresAt": now + CASE_SECONDS,
              "auditId": log, "claimKeys": claims},
        ConditionExpression="attribute_not_exists(id)")
    return {"caseId": case_id, "contactId": contact_id,
            "manifestSha256": digest, "status": "PENDING_SECOND_REVIEW",
            "expiresAt": now + CASE_SECONDS, "erasureComplete": False}


def approve(*, case_id: str, expected_contact_id: str, actor: str,
            tables: Mapping[str, Any], audit: Any) -> dict:
    cases = tables["SystemConfigTable"]
    case = _case(cases, case_id)
    if case.get("contactId") != expected_contact_id:
        raise Refused("ERASURE_CASE_CONTACT_MISMATCH",
                      "The approval case belongs to a different contact.")
    if actor == case.get("preparedBy"):
        raise Refused("ERASURE_SECOND_REVIEWER_REQUIRED",
                      "A different administrator must approve the deletion.")
    if case.get("status") != "PENDING_SECOND_REVIEW":
        raise Refused("ERASURE_ALREADY_REVIEWED", "This case was already reviewed.")
    _, claims, digest = _validate_target(str(case["contactId"]), tables)
    if digest != case.get("manifestSha256") or claims != (case.get("claimKeys") or []):
        raise Refused("ERASURE_SNAPSHOT_CHANGED", "Contact or identity claims changed; prepare again.")
    token = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(token.encode()).hexdigest()
    log = audit(action="contact.erasure_approve", actor=actor,
                resource_type="contact", resource_id=str(case["contactId"]),
                details={"caseId": case_id})
    if not log:
        raise Refused("ERASURE_AUDIT_UNAVAILABLE", "Approval could not be audited.")
    cases.update_item(
        Key={"id": case_id},
        UpdateExpression="SET #status=:approved, approvedBy=:actor, tokenHash=:hash, approvalAuditId=:log",
        ConditionExpression="#status=:pending AND expiresAt > :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":approved": "APPROVED",
                                  ":pending": "PENDING_SECOND_REVIEW",
                                  ":actor": actor, ":hash": hashed,
                                  ":log": log, ":now": int(time.time())})
    return {"caseId": case_id, "contactId": case["contactId"],
            "manifestSha256": digest, "approvalToken": token,
            "status": "APPROVED", "erasureComplete": False}


def execute(*, contact_id: str, case_id: str, manifest_sha256: str,
            approval_token: str, actor: str, tables: Mapping[str, Any],
            transact_write: Any, audit: Any) -> dict:
    cases = tables["SystemConfigTable"]
    case = _case(cases, case_id)
    if (case.get("status") != "APPROVED"
            or case.get("contactId") != contact_id
            or case.get("manifestSha256") != manifest_sha256
            or actor != case.get("approvedBy")
            or not hmac.compare_digest(str(case.get("tokenHash") or ""),
                      hashlib.sha256(approval_token.encode()).hexdigest())):
        raise Refused("ERASURE_APPROVAL_INVALID", "The approval is missing, expired, or already used.")
    row, claim_keys, digest = _validate_target(contact_id, tables)
    if digest != manifest_sha256 or claim_keys != (case.get("claimKeys") or []):
        raise Refused("ERASURE_SNAPSHOT_CHANGED", "Contact or dependencies changed; prepare again.")
    log = audit(action="contact.erasure_execute", actor=actor,
                resource_type="contact", resource_id=contact_id,
                details={"caseId": case_id, "claimCount": len(claim_keys)})
    if not log:
        raise Refused("ERASURE_AUDIT_UNAVAILABLE", "Deletion cannot proceed without an audit.")
    # A single transaction consumes the grant and removes only the exact
    # contact plus strong claims. No message, payment, S3 or provider deletes.
    now = int(time.time())
    conditions = ["attribute_exists(#id)"]
    names = {"#id": "id"}
    values = {}
    for idx, field in enumerate(("phone", "email", "updatedAt", "locked", "lockedReason",
                                 "bsuid", "customerUuid", "checkoutCustomerId")):
        alias = "#f" + str(idx)
        names[alias] = field
        if field in row:
            value_key = ":v" + str(idx)
            conditions.append(alias + " = " + value_key)
            values[value_key] = row[field]
        else:
            conditions.append("attribute_not_exists(" + alias + ")")
    ops = [
        {"Update": {
            "TableName": cases.name, "Key": {"id": case_id},
            "UpdateExpression": "SET #status=:used, consumedAt=:now, executionAuditId=:log",
            "ConditionExpression": "#status=:approved AND approvedBy=:actor AND tokenHash=:hash AND expiresAt > :now",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {
                ":used": "CONSUMED", ":approved": "APPROVED",
                ":actor": actor, ":hash": case["tokenHash"],
                ":now": now, ":log": log}}},
        {"Delete": {
            "TableName": tables["ContactsTable"].name,
            "Key": {"id": contact_id},
            "ConditionExpression": " AND ".join(conditions),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values}},
    ]
    for key in claim_keys:
        ops.append({"Delete": {
            "TableName": tables["IdentityClaimsTable"].name,
            "Key": {"claimKey": key},
            "ConditionExpression": "contactId = :cid",
            "ExpressionAttributeValues": {":cid": contact_id}}})
    transact_write(ops)
    existing = tables["ContactsTable"].get_item(
        Key={"id": contact_id}, ConsistentRead=True).get("Item")
    owners = [tables["IdentityClaimsTable"].get_item(
        Key={"claimKey": key}, ConsistentRead=True).get("Item") for key in claim_keys]
    if existing or any(owners):
        raise Refused("ERASURE_RECONCILIATION_REQUIRED",
                      "The identity transaction requires reconciliation.")
    return {"caseId": case_id, "contactId": contact_id,
            "manifestSha256": manifest_sha256, "auditId": log,
            "erasureComplete": True, "reconciliationComplete": True,
            "protectedContactsVerified": True, "financialEvidencePreserved": True,
            "identityClaimsReleased": True, "contactRecreatable": True,
            "localOnly": True, "auditRecordsPreserved": True,
            "providerCopiesErased": False}
