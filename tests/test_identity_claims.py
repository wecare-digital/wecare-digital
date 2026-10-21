from pathlib import Path
import sys

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import identity_claims as claims  # noqa: E402


def conditional():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
        "UpdateItem",
    )


class Table:
    def __init__(self):
        self.rows = {}

    def update_item(self, **kw):
        key = kw["Key"]["claimKey"]
        cid = kw["ExpressionAttributeValues"][":cid"]
        old = dict(self.rows.get(key) or {})
        if old and old.get("contactId") != cid:
            raise conditional()
        now = kw["ExpressionAttributeValues"][":now"]
        self.rows[key] = {
            "claimKey": key,
            "contactId": cid,
            "identityType": kw["ExpressionAttributeValues"][":kind"],
            "claimedAt": old.get("claimedAt", now),
            "updatedAt": now,
        }
        return {"Attributes": old} if old else {}

    def delete_item(self, **kw):
        key = kw["Key"]["claimKey"]
        cid = kw["ExpressionAttributeValues"][":cid"]
        old = self.rows.get(key)
        if old and old.get("contactId") != cid:
            raise conditional()
        if old:
            del self.rows[key]
        return {}

    def get_item(self, **kw):
        return {"Item": dict(self.rows.get(kw["Key"]["claimKey"]) or {})}


def test_normalization_is_stable():
    assert claims.key("PHONE", "+91 98765-43210") == "PHONE#+919876543210"
    assert claims.key("EMAIL", " A@Example.COM ") == "EMAIL#a@example.com"


def test_same_contact_claim_is_idempotent():
    table = Table()
    claims.claim_identities(table, contact_id="c-1", phone="+919876543210", now=10)
    claims.claim_identities(table, contact_id="c-1", phone="919876543210", now=20)
    row = table.rows["PHONE#+919876543210"]
    assert row["contactId"] == "c-1"
    assert row["claimedAt"] == 10
    assert row["updatedAt"] == 20


def test_different_contact_fails_closed():
    table = Table()
    claims.claim_identities(table, contact_id="c-1", phone="+919876543210")
    with pytest.raises(claims.IdentityClaimConflict):
        claims.claim_identities(table, contact_id="c-2", phone="+919876543210")
    assert table.rows["PHONE#+919876543210"]["contactId"] == "c-1"


def test_partial_multi_claim_rolls_back_only_new_claim():
    table = Table()
    claims.claim_identities(table, contact_id="other", email="taken@example.com")
    with pytest.raises(claims.IdentityClaimConflict):
        claims.claim_identities(
            table, contact_id="c-1", phone="+919876543210", email="taken@example.com"
        )
    assert "PHONE#+919876543210" not in table.rows
    assert table.rows["EMAIL#taken@example.com"]["contactId"] == "other"


def test_changed_identity_release_never_deletes_other_owner():
    table = Table()
    claims.claim_identities(table, contact_id="c-1", phone="+919876543210")
    claims.claim_identities(table, contact_id="c-1", phone="+919111111111")
    claims.release_changed(
        table,
        contact_id="c-1",
        old_phone="+919876543210",
        new_phone="+919111111111",
    )
    assert "PHONE#+919876543210" not in table.rows
    assert claims.owner(table, "PHONE", "+919111111111") == "c-1"
