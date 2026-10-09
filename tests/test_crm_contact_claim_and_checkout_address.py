"""CRM address visibility and permanent customer ownership.

Legacy phone-only adoption was superseded by the 2026-10-09 security contract.
Existing contact edits require explicit permanent ownership; email verification
and stable public customer identifiers retain their original guarantees.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contacts_fake_table import FakeContactsResource, FakeContactsTable  # noqa: E402
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import contact_address  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402
from lambda_utils.identity import customer_uuid  # noqa: E402

CONTACTS = "stack-wecare-digital-ContactsTable"
ATTEMPTS = "stack-wecare-digital-PaymentAttemptsTable"
KEYS = "stack-wecare-digital-CommerceKeys"
OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"

CONTACTS_HANDLER = ROOT / "amplify/functions/core/contacts/handler.py"
CHECKOUT_HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
PROFILE_HANDLER = ROOT / "amplify/functions/auth/customer-profile/handler.py"

CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"
OTHER_CUSTOMER = "CUS_01J8Z9SOMEONEELSE000"
RAW_PHONE = "+91 81006 40044"
STORED_PHONE = customer_identity.normalize_phone_preserving_country(RAW_PHONE)
EMAIL = "asha@example.com"
ADDRESS = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
           "state": "West Bengal", "postalCode": "700001"}


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── FIX 3: the CRM can see the checkout address ───────────────────────────────

@pytest.fixture
def contacts(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    return _load(CONTACTS_HANDLER, "contacts_crm_address_under_test")


def test_the_crm_declares_the_same_attribute_names_the_checkout_writes(contacts):
    """One definition of the two names, in two places that must never drift.

    `core/contacts` does not import `contact_address` - that would pull `wix_address` and the
    India tax tables into a CRM handler for two string constants - so the names are repeated
    locally and pinned HERE instead. A rename on the write side fails this test rather than
    silently blanking a column.
    """
    assert contacts.CHECKOUT_ADDRESS_READ_FIELDS == (
        contact_address.ATTRIBUTE, contact_address.UPDATED_ATTRIBUTE)


def test_a_contact_read_carries_the_checkout_address_through(contacts):
    """`_from_dynamo` is the single funnel every contact read passes through."""
    row = {
        "id": "contact-1", "contactId": "contact-1",
        "phone": STORED_PHONE, "email": EMAIL, "name": "Asha Sen",
        contact_address.ATTRIBUTE: dict(ADDRESS),
        contact_address.UPDATED_ATTRIBUTE: 1700000000,
    }
    out = contacts._from_dynamo(row)
    assert out[contact_address.ATTRIBUTE] == ADDRESS
    assert out[contact_address.UPDATED_ATTRIBUTE] == 1700000000


def test_the_crm_cannot_write_the_checkout_address(contacts):
    """One writer, and it is the checkout path.

    A hand-edit here could produce a map `contact_address.from_contact` re-validates to `None`,
    which demotes a payable customer to `409 DELIVERY_DETAILS_REQUIRED` with nothing in the CRM
    to explain why. `PUT /contacts` filters on `ALLOWED_UPDATE_FIELDS`, so absence from that set
    is the enforcement.
    """
    for field in contacts.CHECKOUT_ADDRESS_READ_FIELDS:
        assert field not in contacts.ALLOWED_UPDATE_FIELDS


def test_no_contact_read_narrows_itself_with_a_projection():
    """The way this fix would most plausibly be undone.

    `_list_all` is a full-table scan, so adding a `ProjectionExpression` to it is the obvious
    next optimisation - and it would drop the two attributes again without touching anything
    named after them. The only `ProjectionExpression` in the file belongs to
    `_check_duplicate_scan`, which compares phone and email and reads no address at all.
    """
    tree = ast.parse(CONTACTS_HANDLER.read_text(encoding="utf-8"))
    readers = {"_list_all", "_read_one", "_search"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in readers:
            rendered = ast.unparse(node)
            assert "ProjectionExpression" not in rendered, \
                f"{node.name} projects, which silently drops attributes it does not name"


def test_the_crm_ui_renders_the_checkout_address():
    """The backend already returned the attribute; nothing displayed it. Asserted on the source
    because the whole defect was a field that existed everywhere except on screen."""
    page = (ROOT / "src/pages/workspace/contacts/index.tsx").read_text(encoding="utf-8")
    assert "checkoutDeliveryAddress" in page
    assert "formatCheckoutAddress" in page
    assert "Checkout Delivery Address" in page, "the detail panel needs a labelled row"
    assert "Checkout Address" in page, "the list needs a column"


def _normalize_contact_body() -> str:
    """The body of `normalizeContact`, sliced out of `client.ts`.

    Textual rather than parsed because there is no TypeScript AST available here. The slice runs
    from the declaration to the first line that is exactly `}`, which is the mapper's own closer:
    the function is a single `return { ... };`, so no nested brace sits in column zero.
    """
    client = (ROOT / "src/api/client.ts").read_text(encoding="utf-8")
    start = client.index("function normalizeContact")
    end = client.index("\n}\n", start)
    return client[start:end]


def test_the_client_mapper_carries_the_checkout_address_not_just_the_type():
    """The way this fix was ALREADY shipped dead once, so the assertion has to reach the mapper.

    `normalizeContact` is a closed field-by-field object literal with no spread of `item`, and
    it is the only way a contact enters the UI - `listContacts`, `getContact`, `createContact`
    and `updateContact` all map through it. The first attempt added both fields to the `Contact`
    interface and nothing to the mapper, so `checkoutDeliveryAddress` was `undefined` in the
    browser for every contact and the new column rendered the em-dash permanently.

    Nothing caught it: `tsc --noEmit` passes because both fields are optional, and the guard
    assertion was `"checkoutDeliveryAddress" in client`, which a type declaration alone
    satisfies. Green suite, dead feature - the same shape as the OTP defect this branch exists
    to fix, where a dict fake could not enforce the constraint that actually mattered.

    `src/test/CrmCheckoutAddress.test.ts` is the stronger half of this guard: it drives the real
    `listContacts` against a stubbed payload and reads the field off the result.
    """
    body = _normalize_contact_body()
    for field in ("checkoutDeliveryAddress", "checkoutAddressUpdatedAt"):
        assert f"{field}:" in body, (
            f"`{field}` must be assigned inside normalizeContact; declaring it on the Contact "
            "interface alone leaves it undefined in the browser"
        )


# ─── FIX 4a: customer-profile claims an unowned row ────────────────────────────

class ProfileIdentity:
    def __init__(self, customer_id=CUSTOMER, phone=RAW_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-fixture"


@pytest.fixture
def profile(monkeypatch):
    monkeypatch.setenv("OTP_TABLE", OTP_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("APP_ENV", "development")
    h = _load(PROFILE_HANDLER, "customer_profile_claim_under_test")
    fake = FakeDynamo(
        keys={OTP_TABLE: "grantId", CONTACTS: "id"},
        indexes={CONTACTS: {"phone-index": ("phone", None), "email-index": ("email", None)}},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_pepper", lambda: "claim-test-pepper")
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (ProfileIdentity(), None))
    return h, fake, monkeypatch


def crm_row(fake, **overrides):
    """A contact as the CRM creates one: no `checkoutCustomerId`, no `emailVerifiedAt`."""
    row = {
        "id": "crm-1", "contactId": "crm-1",
        "phone": STORED_PHONE, "email": EMAIL,
        "name": "Asha Sen", "firstName": "Asha", "lastName": "Sen",
        "shippingAddress": "12 Dalhousie Square, Kolkata",
        "tags": ["Lead"], "createdAt": 1, "updatedAt": 1, "deletedAt": None,
    }
    row.update(overrides)
    fake.Table(CONTACTS).put_item(
        Item={k: v for k, v in row.items() if v is not None or k == "deletedAt"})
    return row


def test_an_unowned_crm_row_requires_staff_reconciliation(profile):
    h, fake, _ = profile
    crm_row(fake)
    owned = h._owned_contact(STORED_PHONE, CUSTOMER)
    assert owned is None


def test_a_crm_create_stores_the_EXACT_string_the_website_looks_up(monkeypatch):
    """The link, asserted end to end rather than as two separate normalisations.

    `STORED_PHONE` here is `normalize_phone_preserving_country(RAW_PHONE)` - the same call every
    reader makes on the session phone before it queries `phone-index`. So this test says: the
    string `core/contacts` WRITES is byte-identical to the string `customer-profile`, `checkout`
    and `customer-orders` READ. That identity is the whole of requirement 5; before it, the CRM
    wrote `+9876543210` and all three readers looked for `+919876543210`.
    """
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    contacts = _load(CONTACTS_HANDLER, "contacts_create_link_under_test")
    table = FakeContactsTable()
    monkeypatch.setattr(contacts, "dynamodb", FakeContactsResource(table))

    response = contacts._create({"name": "Asha Sen", "phone": RAW_PHONE, "email": EMAIL},
                                "req-link")
    assert response["statusCode"] == 201
    assert table.puts[0]["phone"] == STORED_PHONE


def test_a_crm_created_owned_row_is_editable_and_its_address_resolves(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER, **{contact_address.ATTRIBUTE: dict(ADDRESS)})
    owned = h._owned_contact(STORED_PHONE, CUSTOMER)
    assert owned is not None and owned["id"] == "crm-1"
    resolved = contact_address.from_contact(owned)
    assert resolved is not None, "an adopted row's stored address must still resolve"
    assert {key: resolved[key] for key in ADDRESS} == ADDRESS


def test_a_row_owned_by_another_customer_is_never_claimed(profile):
    """The security boundary. Claiming is for a row with NO owner, never for someone else's."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=OTHER_CUSTOMER)
    assert h._owned_contact(STORED_PHONE, CUSTOMER) is None


def test_an_already_owned_row_wins_over_a_claimable_duplicate(profile):
    """Otherwise a session with its own row could adopt a stray unowned one on the same number
    and start editing the wrong record."""
    h, fake, _ = profile
    crm_row(fake, id="crm-1", contactId="crm-1")
    crm_row(fake, id="mine-1", contactId="mine-1", checkoutCustomerId=CUSTOMER)
    owned = h._owned_contact(STORED_PHONE, CUSTOMER)
    assert owned is not None and owned["id"] == "mine-1"


def test_a_owned_row_is_stamped_with_the_session_customer_id(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER)
    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"address": dict(ADDRESS)}),
    }, None)
    assert response["statusCode"] == 200
    row = fake.all_rows(CONTACTS)[0]
    assert row["checkoutCustomerId"] == CUSTOMER
    # The NORMALISED address, not the submitted dict: `normalize_for_storage` fills in
    # `countryCode`, `country` and `fullAddress`. Asserting on the submitted keys only, because
    # the normalisation itself is `test_contact_address.py`'s job, not this file's.
    stored = row[contact_address.ATTRIBUTE]
    assert {key: stored[key] for key in ADDRESS} == ADDRESS


def test_editing_does_not_verify_the_email(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER)
    h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"address": dict(ADDRESS)}),
    }, None)
    row = fake.all_rows(CONTACTS)[0]
    assert row["checkoutCustomerId"] == CUSTOMER
    assert "emailVerifiedAt" not in row, \
        "editing a row must not stamp it verified; only a validated proof may do that"


def test_a_owned_blog_subscriber_row_keeps_the_verification_it_already_proved(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER, emailVerifiedAt=1700000000)
    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"email": EMAIL}),
    }, None)
    assert response["statusCode"] == 200, "row 4: the stored email is already proven"
    row = fake.all_rows(CONTACTS)[0]
    assert row["checkoutCustomerId"] == CUSTOMER, "the claim is still written"
    assert row["emailVerifiedAt"] == 1700000000, \
        "an inherited verification must not be re-stamped; the timestamp records when it was proved"


def test_a_owned_verified_row_still_demands_a_proof_for_a_DIFFERENT_email(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER, emailVerifiedAt=1700000000)
    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"email": "someone.else@example.com"}),
    }, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    row = fake.all_rows(CONTACTS)[0]
    assert row["email"] == EMAIL, "the unproven address must not have been written"


def test_a_owned_row_still_needs_a_proof_before_its_email_is_trusted(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER)
    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"email": EMAIL}),
    }, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "EMAIL_VERIFICATION_REQUIRED"
    assert "emailVerifiedAt" not in fake.all_rows(CONTACTS)[0]


# ─── FIX 4b: checkout reads an unowned row, but not an unverified one ──────────

class CheckoutIdentity:
    def __init__(self, customer_id=CUSTOMER, phone=RAW_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-fixture"

    def owns(self, value):
        return bool(value) and value == self.customer_id


@pytest.fixture
def checkout(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS)
    monkeypatch.setenv("APP_ENV", "development")
    h = _load(CHECKOUT_HANDLER, "checkout_claim_under_test")
    fake = FakeDynamo(
        keys={CONTACTS: "id", ATTEMPTS: "paymentAttemptId", KEYS: "orderId"},
        indexes={CONTACTS: {"phone-index": ("phone", None)}},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (CheckoutIdentity(), None))
    return h, fake, monkeypatch


def payable_row(fake, **overrides):
    """A row that is ready to pay except for whatever the test overrides."""
    row = {
        "id": "contact-1", "contactId": "contact-1",
        "phone": STORED_PHONE, "email": EMAIL,
        "name": "Asha Sen", "firstName": "Asha", "lastName": "Sen",
        "checkoutCustomerId": CUSTOMER, "emailVerifiedAt": 1,
        contact_address.ATTRIBUTE: dict(ADDRESS),
        contact_address.UPDATED_ATTRIBUTE: 1,
        "deletedAt": None,
    }
    row.update(overrides)
    fake.Table(CONTACTS).put_item(
        Item={k: v for k, v in row.items() if v is not None or k == "deletedAt"})
    return row


def test_an_unowned_but_verified_row_is_not_this_session_s_profile(checkout):
    h, fake, _ = checkout
    payable_row(fake, checkoutCustomerId=None)
    row = h._checkout_profile(CheckoutIdentity())
    assert row is None


def test_an_unowned_row_with_no_verified_email_still_cannot_pay(checkout):
    """THE GUARDRAIL, restated where it is enforced. This is the exact relaxation that must NOT
    happen: paying against an unverified email is worse than being asked to verify one."""
    h, fake, _ = checkout
    payable_row(fake, checkoutCustomerId=None, emailVerifiedAt=None)
    assert h._checkout_profile(CheckoutIdentity()) is None


def test_an_unowned_row_with_no_email_at_all_cannot_pay(checkout):
    h, fake, _ = checkout
    payable_row(fake, checkoutCustomerId=None, email=None)
    assert h._checkout_profile(CheckoutIdentity()) is None


def test_a_row_owned_by_another_customer_is_still_refused(checkout):
    h, fake, _ = checkout
    payable_row(fake, checkoutCustomerId=OTHER_CUSTOMER)
    assert h._checkout_profile(CheckoutIdentity()) is None


def test_a_deleted_row_is_not_claimable(checkout):
    h, fake, _ = checkout
    payable_row(fake, checkoutCustomerId=None, deletedAt=1)
    assert h._checkout_profile(CheckoutIdentity()) is None


def test_an_owned_row_wins_over_an_unowned_one(checkout):
    h, fake, _ = checkout
    payable_row(fake, id="stray-1", contactId="stray-1", checkoutCustomerId=None)
    payable_row(fake, id="mine-1", contactId="mine-1")
    row = h._checkout_profile(CheckoutIdentity())
    assert row is not None and row["id"] == "mine-1"


def test_checkout_does_not_try_to_write_the_claim_it_has_no_grant_for():
    """`amplify/infra/checkout.json` gives this role `dynamodb:Query` on the phone index and
    nothing else on ContactsTable, so a stamp from here would fail with AccessDenied at runtime
    and no test would see it. The claim is written by `auth/customer-profile`, which holds
    `UpdateItem`. Asserted on the source, because this is about a call that must NOT appear.
    """
    tree = ast.parse(CHECKOUT_HANDLER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"_checkout_profile", "_unowned"}:
            rendered = ast.unparse(node)
            for writer in ("update_item", "put_item", "delete_item"):
                assert writer not in rendered, \
                    f"{node.name} calls {writer}; this role has no write grant on ContactsTable"

    infra = json.loads((ROOT / "amplify/infra/checkout.json").read_text(encoding="utf-8"))
    policy = infra["Resources"]["CheckoutRole"]["Properties"]["Policies"][0]
    statements = policy["PolicyDocument"]["Statement"]
    contacts_statements = [
        s for s in statements
        if any("ContactsTable" in json.dumps(r) for r in s.get("Resource", []))
    ]
    assert contacts_statements, "expected a ContactsTable statement to assert against"
    for statement in contacts_statements:
        assert set(statement["Action"]) == {"dynamodb:Query"}, \
            "the ContactsTable grant must stay read-only; the claim is written elsewhere"


# ─── the public customer id survives a claim and a re-save ────────────────────
#
# `auth/customer-profile` is the OTHER writer of a contact row, and it reaches a row three
# different ways: the edit path (site 1), the deterministic create (site 2) and the race fallback
# on that create (site 3). All three must converge on ONE public customer id per customer, because
# that id is printed on an invoice the customer keeps.
#
# Site 1 and site 3 share `_set_fragments`, which assigns it with `if_not_exists`. Site 2 mints
# inline, and is only reachable when neither index resolved a row. `FakeDynamo` evaluates
# `if_not_exists` for real (see `_apply_update`), so these assert on the STORED value rather than
# on the expression text.


def test_a_profile_save_mints_a_public_customer_id(profile):
    """A website customer with no prior CRM row gets one - `_upsert_contact`'s create branch.

    Driven through `_upsert_contact` rather than through `handler`, because reaching site (2) via
    the route additionally needs a name, an email AND a verified email proof bound to it; the
    proof machinery is `test_crm_customer_login.py`'s subject, and threading it here would test
    the OTP exchange rather than the id.
    """
    h, fake, _ = profile
    result = h._upsert_contact(customer_id=CUSTOMER, phone=STORED_PHONE, email=EMAIL,
                               first_name="Asha", last_name="Sen",
                               address=dict(ADDRESS), proof_validated=True)
    assert result["created"] is True
    row = fake.all_rows(CONTACTS)[0]
    assert customer_uuid.is_customer_uuid(row[customer_uuid.ATTRIBUTE])


def test_editing_a_crm_row_does_NOT_replace_its_public_customer_id(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    existing = "11111111-1111-4111-8111-111111111111"
    crm_row(fake, checkoutCustomerId=CUSTOMER, **{customer_uuid.ATTRIBUTE: existing})

    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"address": dict(ADDRESS)}),
    }, None)
    assert response["statusCode"] == 200
    row = fake.all_rows(CONTACTS)[0]
    assert row["checkoutCustomerId"] == CUSTOMER, "the claim itself must still have happened"
    assert row[customer_uuid.ATTRIBUTE] == existing


def test_a_owned_crm_row_with_no_id_yet_gains_one(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER)
    response = h.handler({
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"address": dict(ADDRESS)}),
    }, None)
    assert response["statusCode"] == 200
    row = fake.all_rows(CONTACTS)[0]
    assert customer_uuid.is_customer_uuid(row[customer_uuid.ATTRIBUTE])


def test_two_consecutive_saves_do_not_issue_two_ids(profile):
    """An explicitly owned contact preserves address, email-proof and public-ID semantics."""
    h, fake, _ = profile
    crm_row(fake, checkoutCustomerId=CUSTOMER)
    event = {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"address": dict(ADDRESS)}),
    }
    assert h.handler(event, None)["statusCode"] == 200
    first = fake.all_rows(CONTACTS)[0][customer_uuid.ATTRIBUTE]
    assert h.handler(event, None)["statusCode"] == 200
    assert fake.all_rows(CONTACTS)[0][customer_uuid.ATTRIBUTE] == first


def test_the_public_id_is_never_the_row_id(profile):
    """`_upsert_contact`'s create branch mints the row `id` as uuid5 of the Cognito sub. The
    public id must be a different value AND a different version, or printing it on an invoice
    would publish a hash of the Cognito subject."""
    h, fake, _ = profile
    h._upsert_contact(customer_id=CUSTOMER, phone=STORED_PHONE, email=EMAIL,
                      first_name="Asha", last_name="Sen",
                      address=dict(ADDRESS), proof_validated=True)
    row = fake.all_rows(CONTACTS)[0]
    assert row[customer_uuid.ATTRIBUTE] != row["id"]
    assert customer_uuid.is_customer_uuid(row[customer_uuid.ATTRIBUTE])
    # The row id really is the uuid5 this test is distinguishing it from.
    assert not customer_uuid.is_customer_uuid(row["id"])
