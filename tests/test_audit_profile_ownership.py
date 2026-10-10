"""Permanent contact ownership must survive phone reuse and valid new email proof."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_customer_orders_handler import ctx as orders_ctx, contact_row, call as orders_call
from test_checkout_profile_status import env as checkout_env, seed, call as checkout_call
from test_customer_profile_handler import (
    env as profile_env, seed_owned, proof, event, ADDRESS, EMAIL, CONTACTS_TABLE, CUSTOMER,
)


@pytest.mark.parametrize("owner", [None, "", "another-permanent-customer"])
def test_order_profile_never_discloses_a_contact_without_exact_ownership(orders_ctx, owner):
    module, _, contacts, _ = orders_ctx
    contacts.items = [contact_row(checkoutCustomerId=owner)]
    _, body = orders_call(module, body={})
    assert body["profile"] is None


@pytest.mark.parametrize("owner", [None, "", "another-permanent-customer"])
def test_checkout_never_prefills_a_contact_without_exact_ownership(checkout_env, owner):
    h, fake, _ = checkout_env
    seed(fake, checkoutCustomerId=owner)
    _, body = checkout_call(h)
    assert body["status"] == "PROFILE_REQUIRED"
    assert "email" not in body


@pytest.mark.parametrize("owner", [None, "", "another-permanent-customer"])
def test_valid_new_email_proof_cannot_replace_existing_contact_ownership(profile_env, owner):
    """A proven email is a claim about an ADDRESS and never about an owner.

    The seeded row carries no `lastInboundMessageAt`, so the WhatsApp-first link refuses it as
    well - `NO_INBOUND_EVIDENCE` for the two unowned spellings, `FOREIGN_OWNER` for the third -
    and the answer stays the same generic 409.

    The assertion is no longer byte equality of the row, because a refused link now deliberately
    leaves staff something to reconcile from: `identityConflictAt`, a reason CODE and the
    `Identity Conflict` tag. So every other field is pinned by name instead, which is the
    stronger statement about the thing this test is actually for - the owner, the email, the
    verification timestamp and the stored address must all come through a refusal untouched.
    """
    h, fake, _ = profile_env
    seed_owned(fake, checkoutCustomerId=owner)
    before = copy.deepcopy(fake.all_rows(CONTACTS_TABLE))
    token = proof(h, fake)
    response = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                               emailProof=token, address=dict(ADDRESS)), None)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "CONTACT_IDENTITY_CONFLICT"

    after = fake.all_rows(CONTACTS_TABLE)
    assert len(after) == len(before) == 1
    for field, value in before[0].items():
        if field == "tags":
            continue
        assert after[0][field] == value, f"{field} must not change on a refused claim"
    assert after[0].get("checkoutCustomerId") == before[0].get("checkoutCustomerId")
    # The marker, and ONLY the marker, is new. A `checkoutCustomerId` or an `identityClaimedAt`
    # appearing here would be the ownership replacement this test exists to refuse.
    assert set(after[0]) - set(before[0]) == {"identityConflictAt", "identityConflictReason"}
    assert set(before[0]["tags"]) < set(after[0]["tags"])
    assert h.CONFLICT_TAG in after[0]["tags"]


def test_owner_change_after_lookup_prevents_the_contact_update(profile_env, monkeypatch):
    h, fake, _ = profile_env
    seed_owned(fake)
    original_table = h._table
    contact_table = original_table(CONTACTS_TABLE)
    update = contact_table.update_item

    def changed_owner(**kwargs):
        contact_table.rows["contact-1"]["checkoutCustomerId"] = "new-owner"
        return update(**kwargs)

    monkeypatch.setattr(contact_table, "update_item", changed_owner)
    monkeypatch.setattr(h, "_table", lambda name: contact_table if name == CONTACTS_TABLE else original_table(name))
    response = h.handler(event(address=dict(ADDRESS, city="Chennai")), None)
    assert response["statusCode"] == 409
    row = fake.all_rows(CONTACTS_TABLE)[0]
    assert row["checkoutCustomerId"] == "new-owner"
    assert row["checkoutDeliveryAddress"]["city"] == "Bengaluru"


@pytest.mark.parametrize("owner", [None, "another-permanent-customer"])
def test_creation_collision_cannot_take_an_unowned_or_foreign_deterministic_id(profile_env, owner):
    import uuid
    h, fake, _ = profile_env
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wecare:checkout-customer:{CUSTOMER}"))
    row = {"id": key, "name": "Existing identity", "checkoutCustomerId": owner}
    fake.Table(CONTACTS_TABLE).put_item(Item=row)
    before = copy.deepcopy(fake.all_rows(CONTACTS_TABLE))
    token = proof(h, fake)
    response = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                               emailProof=token, address=dict(ADDRESS)), None)
    assert response["statusCode"] == 409
    assert fake.all_rows(CONTACTS_TABLE) == before
