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


# -- what a refused link writes, and on WHICH row -------------------------------------------
#
# The conflict marker (`identityConflictAt`, a reason CODE and the `Identity Conflict` tag) is
# the staff reconciliation surface, and the tests below are about its aim rather than its
# existence. A marker on the wrong row is worse than no marker: it fills the one CRM view staff
# are told to work from with rows that need no work. Two rules are pinned here —
#   * a refusal reason that describes the SESSION never marks a contact, and
#   * the rows that get marked are the rows `_upsert_contact` can still collide with.


def legacy_row(fake, **overrides):
    """An unowned WhatsApp-first row, as the inbound writer leaves one.

    `lastInboundMessageAt` present, no `checkoutCustomerId`. Overrides are applied verbatim,
    including `None`s, because the spelling of "live" is exactly what several of these tests are
    about: an attribute absent and an attribute stored as NULL are two different rows.
    """
    row = {
        "id": "legacy-1", "contactId": "legacy-1", "phone": PHONE,
        "email": "old@example.com", "tags": ["Lead"], "deletedAt": None,
        "lastInboundMessageAt": 1700000000,
    }
    row.update(overrides)
    fake.Table(CONTACTS_TABLE).put_item(Item=row)
    return row


def capture_audit(h, monkeypatch):
    """The audit calls this request makes. The fixture's stub discards them."""
    recorded = []
    monkeypatch.setattr(h, "record_audit",
                        lambda action, **kwargs: recorded.append({"action": action, **kwargs}))
    return recorded


def refusals_of(recorded):
    return [entry for entry in recorded if entry["action"] == "identity.claim_refused"]


def save_with_proof(h, fake):
    return h.handler(event(firstName="Asha", lastName="Sen", email=EMAIL,
                           emailProof=proof(h, fake), address=dict(ADDRESS)), None)


class TagRacingContacts:
    """The fake contacts table, except its first `update_item` loses to a concurrent tag edit.

    The other writer's tag is applied to the row BEFORE this call raises, because that is the
    causal order in production: our conditioned write fails *precisely* because the list it was
    computed from is no longer the list in the table.
    """

    def __init__(self, inner, added_tag):
        self._inner = inner
        self._added_tag = added_tag
        self.armed = True

    def update_item(self, **kwargs):
        if self.armed:
            self.armed = False
            row = self._inner.rows[kwargs["Key"]["id"]]
            row["tags"] = [*row.get("tags", []), self._added_tag]
            raise FakeClientError("ConditionalCheckFailedException")
        return self._inner.update_item(**kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def arm_losing_tag_write(fake, monkeypatch, *, added_tag):
    """Make the next contacts `update_item` lose to a tag edit it could not have seen, once."""
    real_table = fake.Table
    proxy = {}

    def Table(name):  # noqa: N802 - boto3's spelling
        inner = real_table(name)
        if name != CONTACTS_TABLE:
            return inner
        if "it" not in proxy:
            proxy["it"] = TagRacingContacts(inner, added_tag)
        # `FakeTable` is a thin view over the parent's rows, so re-pointing keeps the proxy's own
        # `armed` state across the several `_table()` calls one request makes.
        proxy["it"]._inner = inner
        return proxy["it"]

    monkeypatch.setattr(fake, "Table", Table)
    return proxy


def test_an_unverified_session_leaves_no_conflict_marker_on_its_own_row(env):
    """`UNVERIFIED_PHONE` is a fact about the CALLER'S SESSION, not about the contact.

    The row here is the customer's own, perfectly good, inbound WhatsApp contact; the only thing
    wrong is that the pool has not confirmed this session's number. Marking it would put a
    staff-visible conflict on a row with nothing wrong with it, again on every save. The audit
    record is still written, because the attempt did happen and is worth reading.
    """
    h, fake, monkeypatch = env
    legacy_row(fake)
    recorded = capture_audit(h, monkeypatch)
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(phone_verified=False), None))

    assert save_with_proof(h, fake)["statusCode"] == 409
    row = row_of(fake)
    assert "identityConflictAt" not in row
    assert "identityConflictReason" not in row
    assert row["tags"] == ["Lead"], "no conflict tag for a reason that is not about this row"
    assert "checkoutCustomerId" not in row
    assert [entry["details"]["reason"] for entry in refusals_of(recorded)] == ["UNVERIFIED_PHONE"]
    assert refusals_of(recorded)[0]["resource_id"] == "legacy-1"


def test_an_unverified_session_cannot_earn_a_data_shaped_refusal_reason(env):
    """Order of the predicate's checks, and it is load-bearing.

    With two rows on the number an unverified session would otherwise be told `AMBIGUOUS_PHONE`
    — a statement about the CRM — and both rows would be tagged for a conflict whose real cause
    is the session flag. The session check runs first, so the reason stays `UNVERIFIED_PHONE`.
    """
    h, fake, monkeypatch = env
    legacy_row(fake)
    legacy_row(fake, id="legacy-2", contactId="legacy-2")
    recorded = capture_audit(h, monkeypatch)
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(phone_verified=False), None))

    assert save_with_proof(h, fake)["statusCode"] == 409
    for row in fake.all_rows(CONTACTS_TABLE):
        assert "identityConflictReason" not in row
        assert h.CONFLICT_TAG not in row["tags"]
    assert [entry["details"]["reason"] for entry in refusals_of(recorded)] == ["UNVERIFIED_PHONE"]


def test_an_archived_row_is_marked_so_its_dead_end_has_a_staff_surface(env):
    """The one refusal that would otherwise be a permanent 409 with nothing to reconcile from.

    `isDeleted=True` with no `deletedAt` is read two ways on purpose: the claim treats it as
    deleted and refuses, while `_upsert_contact`'s `_active_match` reads only `deletedAt` and
    still sees a live, unowned row — so the save ends in `CONTACT_IDENTITY_CONFLICT` every time,
    for ever. Marking it is the only thing that turns that into something staff can find, which
    is why the assertion below is on the HTTP answer AND on the row.
    """
    h, fake, monkeypatch = env
    legacy_row(fake, deletedAt=None, isDeleted=True, tags=[])
    fake.Table(CONTACTS_TABLE).rows["legacy-1"].pop("deletedAt")
    recorded = capture_audit(h, monkeypatch)

    response = save_with_proof(h, fake)
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "CONTACT_IDENTITY_CONFLICT"
    row = row_of(fake)
    assert "checkoutCustomerId" not in row, "an archived row is never claimed"
    assert row["identityConflictReason"] == "DELETED_CONTACT"
    assert row["identityConflictAt"]
    assert row["tags"] == [h.CONFLICT_TAG]
    assert [entry["resource_id"] for entry in refusals_of(recorded)] == ["legacy-1"]


def test_a_tombstone_refusal_names_the_row_it_refused_without_marking_it(env):
    """A `deletedAt` tombstone is the opposite case, and it is deliberately NOT marked.

    `_active_match` skips it, so the customer simply gets a fresh row and there is no conflict to
    reconcile — a tag here would be noise nobody can act on. The audit record still names the
    row, so the refusal is never a record with an empty `resource_id`.
    """
    h, fake, monkeypatch = env
    legacy_row(fake, deletedAt=1699999999)
    recorded = capture_audit(h, monkeypatch)

    assert save_with_proof(h, fake)["statusCode"] == 200
    tombstone = {row["id"]: row for row in fake.all_rows(CONTACTS_TABLE)}["legacy-1"]
    assert "checkoutCustomerId" not in tombstone, "a tombstone is never resurrected"
    assert "identityConflictAt" not in tombstone
    assert tombstone["tags"] == ["Lead"]
    entry = refusals_of(recorded)[0]
    assert entry["details"]["reason"] == "DELETED_CONTACT"
    assert entry["resource_id"] == "legacy-1"


def test_a_refusal_names_the_live_row_when_a_tombstone_shares_the_number(env):
    """The audit record and the marker must point at the SAME row, and it must be the live one.

    A number can hold both a tombstone and the live row that is actually in the way. The
    tombstone comes back first from the index — `phone-index` has no sort key, so the page is in
    whatever order the rows exist — and naming it would send staff to the one row they cannot act
    on while the `Identity Conflict` tag sits on the other. `len(live) == 1` here, so the reason
    is `FOREIGN_OWNER` rather than `AMBIGUOUS_PHONE`: the tombstone is not a second candidate.
    """
    h, fake, monkeypatch = env
    legacy_row(fake, deletedAt=1699999999)
    legacy_row(fake, id="legacy-2", contactId="legacy-2", tags=[],
               checkoutCustomerId="CUS_01J9999999999999999999999")
    recorded = capture_audit(h, monkeypatch)

    assert save_with_proof(h, fake)["statusCode"] == 409
    rows = {row["id"]: row for row in fake.all_rows(CONTACTS_TABLE)}
    assert "identityConflictAt" not in rows["legacy-1"], "a tombstone is never marked"
    assert rows["legacy-2"]["tags"] == [h.CONFLICT_TAG]
    assert rows["legacy-2"]["identityConflictReason"] == "FOREIGN_OWNER"
    assert "checkoutCustomerId" not in rows["legacy-1"]

    entry = refusals_of(recorded)[0]
    assert entry["details"]["reason"] == "FOREIGN_OWNER"
    assert entry["resource_id"] == "legacy-2", \
        "the record names the row the marker landed on, not the tombstone the index returned first"


def test_a_refusal_record_narrows_its_details_to_a_four_digit_tail(env):
    """What `phoneLast4` is and is not a claim about.

    `details` is narrowed, and against the DIGITS form as well as the `+E.164` one — a test that
    only checked `PHONE not in rendered` would pass on the strength of the leading `+` and mean
    nothing. `resource_id` is the deliberate exception: an audit record about a contact has to
    name the contact, and a WhatsApp-first row's key IS the number (`wa<national digits>`, from
    `inbound-whatsapp-handler._deterministic_contact_id`), so the digits are in the record as the
    primary key of the row acted on. Internal table, 180-day retention, and it is the claimer's
    own verified number — but the narrowing above is of the payload, not of the whole record, and
    this test is what says so.
    """
    h, fake, monkeypatch = env
    digits = PHONE.lstrip("+")
    legacy_row(fake, id=f"wa{digits}", contactId=f"wa{digits}", lastInboundMessageAt=None)
    recorded = capture_audit(h, monkeypatch)

    assert save_with_proof(h, fake)["statusCode"] == 409
    entry = refusals_of(recorded)[0]
    assert entry["details"]["phoneLast4"] == PHONE[-4:]
    details = json.dumps(entry["details"])
    assert PHONE not in details and digits not in details, "a last-4 tail, never the number"
    assert EMAIL not in json.dumps(entry) and "old@example.com" not in json.dumps(entry)
    assert entry["resource_id"] == f"wa{digits}"
    assert [key for key, value in entry.items()
            if key != "resource_id" and digits in json.dumps(value)] == []


def test_the_owned_row_is_still_found_beyond_the_first_five_on_a_number(env):
    """The two phone-index reads must agree about which rows exist on a number.

    With six rows and a five-row page, the ownership read missed the row the customer owns and
    the claim then ran on a view that could not see it — refusing, and tagging the customer's own
    contact for a conflict that does not exist. The 409 here is the PRE-EXISTING answer for a
    number carrying several live rows (`_active_match` returns the first one and it is not this
    session's), and it is not what this test is about: the absence of a conflict marker is.
    """
    h, fake, monkeypatch = env
    for index in range(5):
        legacy_row(fake, id=f"other-{index}", contactId=f"other-{index}",
                   lastInboundMessageAt=None)
    owned = seed_owned(fake, id="owned-6", contactId="owned-6")
    recorded = capture_audit(h, monkeypatch)

    assert h._owned_contact(PHONE, CUSTOMER)["id"] == owned["id"], \
        "the sixth row on a number is still the row this session owns"
    save_with_proof(h, fake)
    for row in fake.all_rows(CONTACTS_TABLE):
        assert "identityConflictReason" not in row, f"{row['id']} was tagged for nothing"
        assert h.CONFLICT_TAG not in row["tags"]
    assert refusals_of(recorded) == [], "the claim must not run when the row is already owned"


def test_the_two_phone_index_reads_share_one_page_size(env):
    """Pinned as a constant rather than as two literals, because the bug was the disagreement.

    Asserted on the `Limit` each read actually passes, not by grepping the source for
    `Limit=PHONE_PAGE_LIMIT` twice. A source-text count is the brittleness this file removed from
    the IAM test: it would fail if `_active_match` were migrated to the shared constant, which
    would be an improvement to the code, and it would pass if both literals were changed in step
    to a wrong value.

    `_active_match`'s own read is deliberately NOT part of this. It still pages 5 and is out of
    scope — it decides which row `_upsert_contact` merges into, not whether a claim may run — so
    the third read is asserted to exist and left alone.
    """
    h, fake, monkeypatch = env
    legacy_row(fake)
    limits = []
    # `FakeDynamo.Table` mints a fresh handle per call, exactly as boto3 does, so the recorder
    # goes on the factory rather than on one handle.
    inner_table = fake.Table

    def recording_table(name):
        table = inner_table(name)
        inner_query = table.query

        def query(**kwargs):
            if name == CONTACTS_TABLE and kwargs.get("IndexName") == "phone-index":
                limits.append(kwargs.get("Limit"))
            return inner_query(**kwargs)

        table.query = query
        return table

    monkeypatch.setattr(fake, "Table", recording_table)
    assert save_with_proof(h, fake)["statusCode"] == 200

    # In order: `_owned_contact`'s ownership read, then `_attempt_claim`'s.
    assert limits[:2] == [h.PHONE_PAGE_LIMIT, h.PHONE_PAGE_LIMIT], \
        "the ownership read and the claim read must see the same rows on a number"
    assert h.PHONE_PAGE_LIMIT >= 5
    assert len(limits) == 3, "and `_active_match` reads the index once more, at its own page size"


def test_a_conflict_marker_retries_rather_than_dropping_a_concurrent_tag(env):
    """The marker is a read-modify-write of `tags`, so it is conditioned on the list it read.

    A tag another writer added between the query and the write would otherwise vanish — and this
    path fires on refusals the customer never asked for, so it fires often. The condition turns
    that loss into one `ConditionalCheckFailedException`, and the retry merges against a
    consistent re-read.
    """
    h, fake, monkeypatch = env
    legacy_row(fake, lastInboundMessageAt=None)
    arm_losing_tag_write(fake, monkeypatch, added_tag="VIP")
    assert save_with_proof(h, fake)["statusCode"] == 409
    row = row_of(fake)
    assert row["tags"] == ["Lead", "VIP", h.CONFLICT_TAG], "the concurrent tag must survive"
    assert row["identityConflictReason"] == "NO_INBOUND_EVIDENCE"


@pytest.mark.parametrize("live_spelling", [
    pytest.param({}, id="both-attributes-absent"),
    pytest.param({"deletedAt": None}, id="deletedAt-stored-as-NULL"),
    pytest.param({"isDeleted": None}, id="isDeleted-stored-as-NULL"),
    pytest.param({"isDeleted": False}, id="isDeleted-false"),
    pytest.param({"deletedAt": None, "isDeleted": False}, id="both-spelled-out"),
])
def test_every_spelling_of_live_satisfies_the_claim_condition(env, live_spelling):
    """The claim's `ConditionExpression` has to accept every row its predicate accepts.

    "Live" is written four ways by four writers: the attribute absent (`core/contacts` strips
    `None` before storage), stored as NULL (the CRM writes `deletedAt: None` outright), or
    `isDeleted` present as NULL or `False`. `_row_deleted` treats all of them as live, so a
    condition that disagreed with one would refuse a row the predicate had just approved — and
    because a rejected condition is not a `ConditionalCheckFailedException` when the operand
    types are wrong, the customer would get a 500 rather than a refusal.
    """
    h, fake, _ = env
    row = {"id": "legacy-1", "contactId": "legacy-1", "phone": PHONE,
           "email": "old@example.com", "tags": ["Lead"],
           "lastInboundMessageAt": 1700000000}
    row.update(live_spelling)
    fake.Table(CONTACTS_TABLE).put_item(Item=row)

    assert save_with_proof(h, fake)["statusCode"] == 200
    stored = row_of(fake)
    assert stored["id"] == "legacy-1", "the claim edits the row; it does not create a second"
    assert stored["checkoutCustomerId"] == CUSTOMER
    assert stored["identityClaimEvidence"] == h.CLAIM_EVIDENCE_INBOUND
