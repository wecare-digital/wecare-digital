"""Authenticated checkout profile safely converges into Workspace Contacts.

The save is **presence-driven**: what is required depends on what the body carries and on
whether this session already owns a row. So most of what follows is pairs — the same body
against a row and against no row — and several assertions are deliberately made on the **stored
attribute** rather than on the status code, because the failures that matter here (a stringified
dict sitting in the delivery address, an `emailVerifiedAt` that moved when it should not have)
are invisible to a 200.
"""

import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "amplify/functions/auth/customer-profile/handler.py"

OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CUSTOMER = "CUS_01J0000000000000000000000"
PHONE = "+919330994400"
EMAIL = "asha@example.com"
PEPPER = "profile-test-pepper"

#: The one shape the browser posts. India-only form, so it carries no `countryCode`.
ADDRESS = {
    "addressLine1": "12 MG Road",
    "addressLine2": "Flat 3B",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postalCode": "560001",
}
ADDRESS_ATTRIBUTE = "checkoutDeliveryAddress"
ADDRESS_UPDATED_ATTRIBUTE = "checkoutAddressUpdatedAt"


class Identity:
    #: `phone_verified` mirrors Cognito's `phone_number_verified`, and the stub asserts it True
    #: because every session reaching this route was minted by a WhatsApp OTP. It matters here
    #: only through `_attempt_claim`: with it False every refusal below would be earned by the
    #: unverified phone instead of by the predicate under test.
    def __init__(self, customer_id=CUSTOMER, phone=PHONE, phone_verified=True):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-1"
        self.phone_verified = phone_verified


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OTP_TABLE", OTP_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("APP_ENV", "development")

    spec = importlib.util.spec_from_file_location("customer_profile_under_test", HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(
        keys={OTP_TABLE: "grantId", CONTACTS_TABLE: "id"},
        indexes={CONTACTS_TABLE: {
            "phone-index": ("phone", None),
            "email-index": ("email", None),
        }},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_pepper", lambda: PEPPER)
    # `lambda_utils.audit` holds its OWN boto3 resource, so an unpatched `record_audit` on the
    # claim-refusal path would reach the live AuditLogsTable from a unit test.
    monkeypatch.setattr(h, "record_audit", lambda *args, **kwargs: "audit-stub")
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(), None))
    return h, fake, monkeypatch


def event(**body):
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer test"},
        "body": json.dumps(body),
    }


def proof(h, fake, email=EMAIL):
    token = "proof-fixture"
    now = int(time.time())
    fake.Table(OTP_TABLE).put_item(Item={
        "grantId": h.PROOF_PREFIX + token,
        "purpose": h.PROOF_PURPOSE,
        "subjectDigest": h._proof_digest(email),
        "createdAt": now,
        "expiresAt": now + 600,
    })
    return token


def seed_owned(fake, **overrides):
    """A non-deleted contact row this session owns, i.e. one `_owned_contact` will return.

    Owned means non-deleted **and** `checkoutCustomerId == customer_id`, and nothing more — the
    predicate is deliberately weaker than checkout's "ready to pay", so a row with no
    `emailVerifiedAt` is still an editable row.
    """
    row = {
        "id": "contact-1", "contactId": "contact-1",
        "phone": PHONE, "email": EMAIL, "name": "Asha Sen",
        "firstName": "Asha", "lastName": "Sen",
        "checkoutCustomerId": CUSTOMER,
        "emailVerifiedAt": 1700000000,
        ADDRESS_ATTRIBUTE: dict(ADDRESS),
        "tags": ["Customer"],
        "createdAt": 1, "updatedAt": 1, "deletedAt": None,
    }
    row.update(overrides)
    for key, value in list(row.items()):
        if value is None and key != "deletedAt":
            row.pop(key)
    fake.Table(CONTACTS_TABLE).put_item(Item=row)
    return row


def row_of(fake):
    rows = fake.all_rows(CONTACTS_TABLE)
    assert len(rows) == 1
    return rows[0]


def index_queries(fake, index):
    return [call for call in fake.calls if call == (CONTACTS_TABLE, f"query:{index}")]


def test_requires_authenticated_customer(env):
    h, _fake, monkeypatch = env
    denied = {"statusCode": 401, "headers": {}, "body": "{}"}
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (None, denied))
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof="x"), None)
    assert resp["statusCode"] == 401


def test_rejects_unexpected_browser_fields(env):
    h, fake, _ = env
    token = proof(h, fake)
    resp = h.handler(event(
        firstName="Asha", lastName="Sen", email=EMAIL, emailProof=token,
        phone="+919999999999", tags=["VIP"], optInEmail=True,
    ), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "UNEXPECTED_FIELD"
    assert fake.count(CONTACTS_TABLE) == 0


def test_email_proof_is_bound_to_exact_email(env):
    h, fake, _ = env
    token = proof(h, fake, EMAIL)
    resp = h.handler(event(
        firstName="Asha", lastName="Sen", email="other@example.com", emailProof=token,
        address=dict(ADDRESS),
    ), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    assert fake.count(CONTACTS_TABLE) == 0


def test_creates_workspace_contact_from_session_phone_without_marketing_consent(env):
    h, fake, _ = env
    token = proof(h, fake)
    resp = h.handler(event(
        firstName="Asha", lastName="Sen", email=EMAIL, emailProof=token,
        address=dict(ADDRESS),
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "PROFILE_READY"
    assert body["phone"] == PHONE

    rows = fake.all_rows(CONTACTS_TABLE)
    assert len(rows) == 1
    row = rows[0]
    assert row["phone"] == PHONE
    assert row["email"] == EMAIL
    assert row["name"] == "Asha Sen"
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row["tags"] == ["Customer"]
    assert row["phoneVerifiedAt"] and row["emailVerifiedAt"]
    assert row["optInWhatsApp"] is False
    assert row["optInEmail"] is False
    assert row["optInSms"] is False
    assert row["allowlistWhatsApp"] is False
    assert row["allowlistEmail"] is False
    assert row["allowlistSms"] is False


def test_merges_existing_phone_contact_and_preserves_explicit_consent(env):
    h, fake, _ = env
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-1", "contactId": "contact-1",
        "phone": PHONE, "email": "old@example.com", "name": "Asha",
        "checkoutCustomerId": CUSTOMER,
        "tags": ["VIP"], "optInEmail": True, "allowlistEmail": True,
        "createdAt": 1, "updatedAt": 1, "deletedAt": None,
    })
    token = proof(h, fake)
    resp = h.handler(event(
        firstName="Asha", lastName="Sen", email=EMAIL, emailProof=token,
        address=dict(ADDRESS),
    ), None)
    assert resp["statusCode"] == 200
    assert fake.count(CONTACTS_TABLE) == 1
    row = fake.all_rows(CONTACTS_TABLE)[0]
    assert row["id"] == "contact-1"
    assert set(row["tags"]) == {"VIP", "Customer"}
    assert row["optInEmail"] is True
    assert row["allowlistEmail"] is True


def test_refuses_to_merge_phone_and_email_that_belong_to_two_contacts(env):
    h, fake, _ = env
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "phone-contact", "contactId": "phone-contact",
        "phone": PHONE, "email": "old@example.com", "tags": [], "deletedAt": None,
    })
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "email-contact", "contactId": "email-contact",
        "phone": "+919999999999", "email": EMAIL, "tags": [], "deletedAt": None,
    })
    token = proof(h, fake)
    resp = h.handler(event(
        firstName="Asha", lastName="Sen", email=EMAIL, emailProof=token,
        address=dict(ADDRESS),
    ), None)
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error"] == "CONTACT_IDENTITY_CONFLICT"
    assert fake.count(CONTACTS_TABLE) == 2


# -- creation: one save and the customer is ready to pay ---------------------------------

def test_creation_persists_the_structured_address_and_its_timestamp(env):
    h, fake, _ = env
    token = proof(h, fake)
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=token, address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row[ADDRESS_ATTRIBUTE]["city"] == "Bengaluru"
    assert row[ADDRESS_ATTRIBUTE]["countryCode"] == "IN"
    assert isinstance(row[ADDRESS_UPDATED_ATTRIBUTE], int)
    body = json.loads(resp["body"])
    assert body["addressComplete"] is True
    assert body["address"]["state"] == "Karnataka"


def test_creation_without_an_address_is_refused_rather_than_half_saved(env):
    h, fake, _ = env
    token = proof(h, fake)
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=token), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body == {"error": "INVALID_ADDRESS", "code": "ADDRESS_REQUIRED"}
    assert fake.count(CONTACTS_TABLE) == 0


def test_creation_without_an_email_is_refused(env):
    h, fake, _ = env
    resp = h.handler(event(firstName="Asha", lastName="Sen",
                           address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "INVALID_EMAIL"
    assert fake.count(CONTACTS_TABLE) == 0


def test_email_proof_does_not_adopt_a_legacy_phone_row(env):
    h, fake, _ = env
    # Email proof cannot authorize adoption of a legacy contact.
    #
    # The refusal is EARNED rather than incidental, and the assertion below says so: the seeded
    # row carries no `lastInboundMessageAt`, so `_attempt_claim`'s predicate (e) refuses it as
    # `NO_INBOUND_EVIDENCE` — a row typed by staff or created by an outbound send proves nothing
    # about who holds the handset. The sibling test immediately after this one seeds the same row
    # WITH inbound evidence and gets a 200, which is what keeps this pin honest: without it, this
    # test would keep passing for the wrong reason the day the predicate was weakened.
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "legacy-1", "contactId": "legacy-1", "phone": PHONE,
        "email": "old@example.com", "tags": [], "deletedAt": None,
    })
    assert "lastInboundMessageAt" not in row_of(fake)
    unproved = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                               address=dict(ADDRESS)), None)
    assert unproved["statusCode"] == 400
    assert json.loads(unproved["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    assert "emailVerifiedAt" not in row_of(fake)

    token = proof(h, fake)
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=token, address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 409
    row = row_of(fake)
    assert "checkoutCustomerId" not in row
    assert "emailVerifiedAt" not in row


def test_the_same_legacy_row_WITH_inbound_evidence_is_claimed_and_saved(env):
    """The sibling of the test above, and the pair is the point.

    Identical seed, identical body, one attribute different: `lastInboundMessageAt`. That is the
    whole of the WhatsApp-first link — the number messaged us, the row has no owner, and the
    session proved the same number by OTP — so the save becomes an edit of the existing row
    instead of a 409 and a second contact.
    """
    h, fake, _ = env
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "legacy-1", "contactId": "legacy-1", "phone": PHONE,
        "email": "old@example.com", "tags": [], "deletedAt": None,
        "lastInboundMessageAt": 1700000000,
    })
    token = proof(h, fake)
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=token, address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["id"] == "legacy-1", "the claim keeps the original row, it does not create a second"
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row["identityClaimEvidence"] == h.CLAIM_EVIDENCE_INBOUND
    assert row["identityClaimedAt"]


# -- the email index is only consulted when there is a second identity to reconcile --------

def test_an_address_only_save_does_not_query_the_email_index(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address=dict(ADDRESS, addressLine1="7 Park Street")), None)
    assert resp["statusCode"] == 200
    # Without the `if email else None` guard this issues `Key("email").eq(None)`, DynamoDB
    # answers ValidationException, and every save this flow adds becomes a 500.
    assert index_queries(fake, "email-index") == []
    assert index_queries(fake, "phone-index")
    assert row_of(fake)[ADDRESS_ATTRIBUTE]["addressLine1"] == "7 Park Street"


# -- the edit rules, and the ordered email-proof decision list -----------------------------

def test_an_address_only_save_does_not_move_email_verified_at(env):
    h, fake, _ = env
    seed_owned(fake, emailVerifiedAt=1700000000)
    resp = h.handler(event(address=dict(ADDRESS, city="Kolkata", state="West Bengal",
                                        postalCode="700016")), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["emailVerifiedAt"] == 1700000000
    assert row[ADDRESS_ATTRIBUTE]["city"] == "Kolkata"


def test_an_address_save_on_an_unverified_owned_row_is_allowed(env):
    h, fake, _ = env
    # Row 3 beats row 6. The row exists and this session owns it, but it was never verified —
    # so it already cannot pay. Refusing the address save as well removes the only way forward
    # and adds no protection, and nothing here writes `emailVerifiedAt`.
    seed_owned(fake, emailVerifiedAt=None)
    resp = h.handler(event(address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert "emailVerifiedAt" not in row
    assert row[ADDRESS_ATTRIBUTE]["postalCode"] == "560001"


def test_a_name_only_save_writes_neither_email_nor_address(env):
    h, fake, _ = env
    seed_owned(fake, **{ADDRESS_ATTRIBUTE: None})
    resp = h.handler(event(firstName="Asha", lastName="Sengupta"), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["name"] == "Asha Sengupta"
    assert row["email"] == EMAIL
    assert ADDRESS_ATTRIBUTE not in row
    assert index_queries(fake, "email-index") == []


def test_an_email_proof_with_no_email_is_refused_and_touches_nothing(env):
    h, fake, _ = env
    # A proof is a claim about an ADDRESS. Binding it to the stored value would let a proof
    # minted in one request verify another.
    seed_owned(fake, emailVerifiedAt=None, **{ADDRESS_ATTRIBUTE: None})
    token = proof(h, fake)
    resp = h.handler(event(emailProof=token, address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    row = row_of(fake)
    assert "emailVerifiedAt" not in row
    assert ADDRESS_ATTRIBUTE not in row


def test_an_unchanged_verified_email_needs_no_proof(env):
    h, fake, _ = env
    seed_owned(fake, emailVerifiedAt=1700000000)
    resp = h.handler(event(email="  ASHA@Example.com  "), None)
    assert resp["statusCode"] == 200
    assert row_of(fake)["emailVerifiedAt"] == 1700000000


def test_a_changed_email_without_a_proof_is_refused(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(email="new@example.com"), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    assert row_of(fake)["email"] == EMAIL


def test_a_changed_email_with_a_proof_bound_to_the_old_address_is_refused(env):
    h, fake, _ = env
    seed_owned(fake)
    token = proof(h, fake, EMAIL)
    resp = h.handler(event(email="new@example.com", emailProof=token), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    assert row_of(fake)["email"] == EMAIL


def test_a_changed_email_with_a_bound_proof_is_written_and_stamped(env):
    h, fake, _ = env
    seed_owned(fake, emailVerifiedAt=1700000000)
    token = proof(h, fake, "new@example.com")
    resp = h.handler(event(email="new@example.com", emailProof=token), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["email"] == "new@example.com"
    assert row["emailVerifiedAt"] != 1700000000


def test_a_stored_email_that_will_not_normalise_is_treated_as_changed(env):
    h, fake, _ = env
    # A CRM import or a People sync can leave a value `normalize_email` refuses. Fail closed by
    # requiring a proof, rather than 500ing on legacy data.
    seed_owned(fake, email="legacy contact")
    resp = h.handler(event(email=EMAIL), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"


def test_a_blank_email_on_an_edit_is_absent_rather_than_a_request_to_clear(env):
    h, fake, _ = env
    seed_owned(fake, emailVerifiedAt=1700000000)
    resp = h.handler(event(email="   ", address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["email"] == EMAIL
    assert row["emailVerifiedAt"] == 1700000000


def test_exactly_one_name_part_on_an_edit_is_refused(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(firstName="Asha"), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "NAME_REQUIRED"
    assert row_of(fake)["name"] == "Asha Sen"


# -- the owned-row lookup keys on the NORMALISED phone -------------------------------------

def test_a_session_phone_needing_normalisation_still_resolves_its_owned_row(env):
    h, fake, monkeypatch = env
    # Seeded the way the WRITER writes it, never the way the session happens to spell it, so the
    # read key is under test rather than assumed.
    seed_owned(fake, phone="+6591234567", **{ADDRESS_ATTRIBUTE: None})
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda e: (Identity(phone="+65 9123 4567"), None))
    resp = h.handler(event(address=dict(ADDRESS)), None)
    # A lookup on the raw session phone would miss this row, demote the edit to a creation, and
    # demand a name + email + proof from a customer who already has all three.
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["phone"] == "+6591234567"
    assert row_of(fake)[ADDRESS_ATTRIBUTE]["city"] == "Bengaluru"


# -- a bad address is a 400 with a field, never a 500 and never an uncaught invocation -----

def test_an_invalid_pin_is_a_four_hundred_naming_the_postal_code(env):
    # FEAT-003: storage is international; the India PIN rule moved to payment_address and runs at
    # checkout, not here. A profile save with a non-standard PIN is now ACCEPTED (200) — the
    # website checkout refuses an unpayable address at pay time with DELIVERY_DETAILS_REQUIRED.
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address=dict(ADDRESS, postalCode="056001")), None)
    assert resp["statusCode"] == 200


def test_an_unmapped_state_is_now_accepted_at_profile_save(env):
    # FEAT-003: the Wix/subdivision rule moved to payment time. An unmapped state is stored here
    # and refused later at checkout, not at the profile save.
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address=dict(ADDRESS, state="Bangalore State")), None)
    assert resp["statusCode"] == 200


def test_a_structurally_refused_address_is_not_echoed_back_to_the_caller(env):
    # A STRUCTURAL failure (missing required field) still 400s and must not echo input back.
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address={"addressLine1": "12 MG Road", "city": "Bengaluru"}), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "error" in body
    for value in ("12 MG Road", "Bengaluru"):
        assert value not in resp["body"]


def test_a_non_scalar_on_a_required_address_field_is_a_four_hundred_not_a_five_hundred(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address={
        "addressLine1": "12 MG Road", "city": {"x": 1},
        "state": "Karnataka", "postalCode": 560001,
    }), None)
    # The whole point of the pre-`try` arm: inside the try this would escape handler() as an
    # unhandled invocation with no CORS headers at all.
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {
        "error": "INVALID_ADDRESS", "code": "FIELD_REQUIRED", "field": "city"}


def test_a_non_scalar_on_an_optional_address_field_is_stored_as_empty(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address={
        "addressLine1": "12 MG Road", "addressLine2": {"long_name": "Flat 3B"},
        "city": "Bengaluru", "state": "Karnataka", "postalCode": 560001,
    }), None)
    assert resp["statusCode"] == 200
    # Asserted on the STORED attribute, because that is what prices the cart and what the
    # identity card's Deliver line renders — and a stringified dict sitting there is invisible
    # to every status assertion in this file.
    stored = row_of(fake)[ADDRESS_ATTRIBUTE]
    assert stored["addressLine2"] == ""
    assert "long_name" not in stored["fullAddress"]


# -- the response is the POST-WRITE merged view, not an echo -------------------------------

def test_a_name_only_save_returns_the_stored_email_and_stays_address_complete(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(firstName="Asha", lastName="Sengupta"), None)
    body = json.loads(resp["body"])
    assert body["email"] == EMAIL
    assert body["name"] == "Asha Sengupta"
    # An echo-only response would report false here and send a returning customer back to an
    # address form they never opened.
    assert body["addressComplete"] is True
    assert body["address"]["city"] == "Bengaluru"


def test_an_address_only_save_returns_the_stored_identity(env):
    h, fake, _ = env
    seed_owned(fake)
    resp = h.handler(event(address=dict(ADDRESS, city="Kolkata", state="West Bengal",
                                        postalCode="700016")), None)
    body = json.loads(resp["body"])
    # An echo-only response would blank the identity card's name and email.
    assert body["firstName"] == "Asha"
    assert body["lastName"] == "Sen"
    assert body["name"] == "Asha Sen"
    assert body["email"] == EMAIL
    assert body["addressComplete"] is True
    assert body["address"]["city"] == "Kolkata"


def test_a_stored_address_with_an_unmapped_state_is_structurally_complete_now(env):
    # FEAT-003: from_contact is structural only, so an unmapped-state stored address is returned
    # (addressComplete true) rather than reported incomplete. Its payability — whether that state
    # can price a Wix/Razorpay cart — is enforced at checkout via payment_address, not here. The
    # customer is no longer bounced back to the profile form for a legacy/edge address; checkout
    # asks them to confirm it only if it actually cannot pay.
    h, fake, _ = env
    seed_owned(fake, **{ADDRESS_ATTRIBUTE: dict(ADDRESS, state="Bangalore State")})
    resp = h.handler(event(firstName="Asha", lastName="Sengupta"), None)
    body = json.loads(resp["body"])
    assert body["addressComplete"] is True
    assert body["address"] is not None
    assert body["address"]["state"] == "Bangalore State"


# -- the race fallback shares the composer with the edit path ------------------------------

def test_the_conditional_check_fallback_writes_the_address_and_leaves_merged_tags_alone(env):
    h, fake, _ = env
    deterministic = str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"wecare:checkout-customer:{CUSTOMER}"))
    # The racing writer got there first and merged tags. No phone on the row, so neither index
    # matches and this request takes the put_item path.
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": deterministic, "contactId": deterministic,
        "checkoutCustomerId": CUSTOMER,
        "tags": ["VIP", "Customer"], "deletedAt": None,
    })
    fake.arm_failure(CONTACTS_TABLE, "put_item",
                     FakeClientError("ConditionalCheckFailedException"))
    token = proof(h, fake)
    resp = h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=token, address=dict(ADDRESS)), None)
    assert resp["statusCode"] == 200
    row = row_of(fake)
    assert row["id"] == deterministic
    # `tags=if_not_exists(tags,:tags)`: the fallback has NOT read the row, so it must not
    # overwrite a merge another writer performed.
    assert row["tags"] == ["VIP", "Customer"]
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row[ADDRESS_ATTRIBUTE]["city"] == "Bengaluru"
    assert row["emailVerifiedAt"]
