"""Permanent contact delete frees phone/email keys so the same number can be added again.

All identifiers are synthetic. The approval gate stays in contacts/handler._delete; the
coordinator is faked and calls the same key-release step a real coordinator would.
"""
import io
import json
import os
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
for sub in ("amplify/functions/shared", "amplify/functions/core/contacts"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)
os.environ.setdefault("AWS_REGION", "us-east-1")

import handler as h  # noqa: E402
from lambda_utils import identity_claims  # noqa: E402
from lambda_utils.erasure import identity_release  # noqa: E402

PHONE = "+15550001234"


class MemTable:
    def __init__(self, key="id"):
        self.key = key
        self.rows = {}
        self.deleted = []

    def get_item(self, Key, **kw):
        row = self.rows.get(Key[self.key])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item, **kw):
        self.rows[Item[self.key]] = dict(Item)

    def delete_item(self, Key, **kw):
        k = Key[self.key]
        cond = kw.get("ExpressionAttributeValues") or {}
        if kw.get("ConditionExpression") and (
                k not in self.rows or self.rows[k].get("contactId") != cond.get(":cid")):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        self.rows.pop(k, None)
        self.deleted.append(k)

    def update_item(self, Key, **kw):
        k = Key[self.key]
        cid = kw["ExpressionAttributeValues"][":cid"]
        old = self.rows.get(k)
        if old and old.get("contactId") != cid:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        self.rows[k] = {self.key: k, "contactId": cid}
        return {"Attributes": dict(old)} if old else {}

    def scan(self, **kw):
        return {"Items": [dict(r) for r in self.rows.values()
                          if r.get("mergedIntoContactId") == "wa15550001234"]}


@pytest.fixture
def world():
    contacts, claims, payments = MemTable("id"), MemTable("claimKey"), MemTable("invoiceId")
    contacts.put_item({"id": "wa15550001234", "phone": PHONE, "email": "a@example.test", "name": "Syn"})
    identity_claims.claim_identities(claims, contact_id="wa15550001234", phone=PHONE, email="a@example.test")
    payments.put_item({"invoiceId": "inv1", "contactId": "wa15550001234", "paymentStatus": "captured"})
    return contacts, claims, payments


def test_delete_then_readd_same_phone(world):
    contacts, claims, payments = world
    with pytest.raises(identity_claims.IdentityClaimConflict):
        identity_claims.claim_identities(claims, contact_id="new-uuid", phone=PHONE)

    result = identity_release.release_contact_identity(
        contacts_table=contacts, claims_table=claims, contact_id="wa15550001234")

    assert result["contactRows"] == 1 and result["claims"] == 2
    assert "wa15550001234" not in contacts.rows
    assert claims.rows == {}
    # Same phone and email now claim cleanly for a brand-new contact.
    identity_claims.claim_identities(claims, contact_id="new-uuid", phone=PHONE, email="a@example.test")
    assert identity_claims.owner(_Getter(claims), "PHONE", PHONE) == "new-uuid"
    # Retained financial record is untouched.
    assert payments.rows["inv1"]["paymentStatus"] == "captured"
    assert payments.deleted == []


class _Getter:
    def __init__(self, t):
        self.t = t

    def get_item(self, Key, **kw):
        return self.t.get_item(Key)


def test_merge_aliases_and_claims_are_freed(world):
    contacts, claims, _ = world
    contacts.put_item({"id": "alias1", "phone": "+15550009999", "mergedIntoContactId": "wa15550001234"})
    claims.put_item({"claimKey": "PHONE#+15550009999", "contactId": "alias1"})
    result = identity_release.release_contact_identity(
        contacts_table=contacts, claims_table=claims, contact_id="wa15550001234")
    assert result["aliasRows"] == 1
    assert "alias1" not in contacts.rows and claims.rows == {}


def test_locked_or_alias_row_is_refused_and_nothing_deleted(world):
    contacts, claims, _ = world
    contacts.rows["wa15550001234"]["locked"] = True
    with pytest.raises(identity_release.ErasureRefused):
        identity_release.release_contact_identity(
            contacts_table=contacts, claims_table=claims, contact_id="wa15550001234")
    assert contacts.deleted == [] and len(claims.rows) == 2


def test_missing_row_is_idempotent(world):
    contacts, claims, _ = world
    assert identity_release.release_contact_identity(
        contacts_table=contacts, claims_table=claims, contact_id="nope")["contactRows"] == 0


ADMIN_MFA = {"role": "Admin", "mfaEnrolled": True, "username": "admin-1"}
APPROVAL = {"caseId": "case-12345", "manifestSha256": "a" * 64,
            "approvalToken": "synthetic-single-use-approval-token-98765"}


def _event(auth):
    return {"_auth": auth, "body": json.dumps(APPROVAL)}


def test_coordinator_path_gating_is_unchanged_and_end_to_end_frees_phone(world, monkeypatch):
    contacts, claims, payments = world
    monkeypatch.setattr(h, "dynamodb", type("D", (), {"Table": lambda self, n: contacts})())
    monkeypatch.setattr(h, "_hard_delete_refusal", lambda *a, **k: None)
    monkeypatch.setattr(h, "_locked_delete_refusal", lambda *a, **k: None)
    monkeypatch.setattr(h, "_merged_alias_mutation_refusal", lambda *a, **k: None)
    monkeypatch.setenv("ERASURE_COORDINATOR_FUNCTION", "coordinator-fn")

    class FakeLambda:
        def invoke(self, **kw):
            identity_release.release_contact_identity(
                contacts_table=contacts, claims_table=claims, contact_id="wa15550001234")
            body = {**{k: APPROVAL[k] for k in ("caseId", "manifestSha256")},
                    "contactId": "wa15550001234", "erasureComplete": True,
                    "reconciliationComplete": True, "protectedContactsVerified": True,
                    "financialEvidencePreserved": True, "auditId": "audit-1"}
            return {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(body).encode())}

    monkeypatch.setattr(h.boto3, "client", lambda *a, **k: FakeLambda())

    # Gating: non-MFA 403, soft delete 400, nothing deleted.
    no_mfa = h._delete("wa15550001234", True, "r", event=_event({"role": "Admin", "mfaEnrolled": False}))
    assert no_mfa["statusCode"] == 403 and "ERASURE_ADMIN_MFA_REQUIRED" in no_mfa["body"]
    soft = h._delete("wa15550001234", False, "r", event=_event(ADMIN_MFA))
    assert soft["statusCode"] == 400 and "ERASURE_EXPLICIT_HARD_REQUEST_REQUIRED" in soft["body"]
    assert "wa15550001234" in contacts.rows

    ok = h._delete("wa15550001234", True, "r", event=_event(ADMIN_MFA))
    assert ok["statusCode"] == 200
    assert "wa15550001234" not in contacts.rows
    identity_claims.claim_identities(claims, contact_id="new-uuid", phone=PHONE)
    assert payments.rows["inv1"]["paymentStatus"] == "captured"
