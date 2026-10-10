"""What the claim actually buys the customer, asserted at the three gates it has to pass.

The link itself is one attribute: `contact.checkoutCustomerId == <the Cognito sub>`. Every
downstream gate already compares exactly that, so NO downstream handler changes in this work -
checkout, the order list and the WhatsApp catalog services start accepting the customer the
moment the row is stamped. A claim nobody downstream honours is a write with no effect, and a
downstream relaxation dressed up as a claim is a security regression, so each test below is a
PAIR: the stamped row is accepted, and the same row with the stamp removed is still refused.

That pairing is the whole design of this file. Either assertion alone is satisfiable by the wrong
code - "accepted" alone passes if the gate stopped checking ownership, and "refused" alone passes
if the gate stopped working at all.

`tests/test_crm_contact_claim_and_checkout_address.py::test_checkout_does_not_try_to_write_the_claim_it_has_no_grant_for`
is the other half of the contract: checkout READS the stamp and has no grant to write one.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import contact_address  # noqa: E402

CONTACTS = "stack-wecare-digital-ContactsTable"
ATTEMPTS = "stack-wecare-digital-PaymentAttemptsTable"
KEYS = "stack-wecare-digital-CommerceKeys"
ORDERS = "stack-wecare-digital-OrderTable"
RATE_LIMIT = "stack-wecare-digital-RateLimitTable"

CHECKOUT_HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
ORDERS_HANDLER = ROOT / "amplify/functions/ecommerce/customer-orders/handler.py"

#: The Cognito `sub`, which is what a claim writes into `checkoutCustomerId`.
SUBJECT = "11111111-2222-3333-4444-555555555555"
PHONE = "+919000000000"
WA_CONTACT_ID = "wa919000000000"
EMAIL = "customer@example.com"
ADDRESS = {"addressLine1": "1 Example Road", "city": "Kolkata",
           "state": "West Bengal", "postalCode": "700001"}


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaimedIdentity:
    """The session a claim was performed for: the same `sub`, and the same verified number."""

    def __init__(self, customer_id=SUBJECT, phone=PHONE, phone_verified=True):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = customer_id
        self.phone_verified = phone_verified

    def owns(self, value):
        return bool(value) and value == self.customer_id


def claimed_row(claimed: bool = True) -> dict:
    """The WhatsApp-first contact after the claim landed, or the same row before it.

    `identityClaimedAt`/`identityClaimEvidence` travel with it because that is what
    `auth/customer-profile::_attempt_claim` writes, and because a reader that tripped over either
    of them would be a regression this file should catch.
    """
    row = {
        "id": WA_CONTACT_ID, "contactId": WA_CONTACT_ID,
        "phone": PHONE, "email": EMAIL,
        "name": "Test Customer", "firstName": "Test", "lastName": "Customer",
        "emailVerifiedAt": 1700000000,
        "lastInboundMessageAt": 1700000000,
        contact_address.ATTRIBUTE: dict(ADDRESS),
        contact_address.UPDATED_ATTRIBUTE: 1700000000,
        "deletedAt": None,
    }
    if claimed:
        row["checkoutCustomerId"] = SUBJECT
        row["identityClaimedAt"] = 1700000001
        row["identityClaimEvidence"] = "WHATSAPP_INBOUND"
    return row


# ── gate 1: website checkout can price and charge the cart ───────────────────

@pytest.fixture
def checkout(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS)
    monkeypatch.setenv("APP_ENV", "development")
    h = _load(CHECKOUT_HANDLER, "checkout_downstream_under_test")
    fake = FakeDynamo(
        keys={CONTACTS: "id", ATTEMPTS: "paymentAttemptId", KEYS: "orderId"},
        indexes={CONTACTS: {"phone-index": ("phone", None)}},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    return h, fake


def test_checkout_accepts_the_claimed_contact(checkout):
    h, fake = checkout
    fake.Table(CONTACTS).put_item(Item=claimed_row())
    row = h._checkout_profile(ClaimedIdentity())
    assert row is not None, "the claim is what makes this row payable"
    assert row["id"] == WA_CONTACT_ID
    assert contact_address.from_contact(row) is not None, \
        "the stored delivery address must still resolve, or the cart cannot be priced"


def test_checkout_still_refuses_the_same_row_without_the_claim(checkout):
    """The negative half. Without this, the test above passes just as happily against a checkout
    that stopped checking ownership at all."""
    h, fake = checkout
    fake.Table(CONTACTS).put_item(Item=claimed_row(claimed=False))
    assert h._checkout_profile(ClaimedIdentity()) is None


def test_a_claimed_row_with_no_verified_email_still_cannot_pay(checkout):
    """Claiming is not verifying, restated where payment is authorised. This is the exact
    relaxation that must never follow from the claim."""
    h, fake = checkout
    row = claimed_row()
    row.pop("emailVerifiedAt")
    fake.Table(CONTACTS).put_item(Item=row)
    assert h._checkout_profile(ClaimedIdentity()) is None


# ── gate 2: the order list shows the customer their own profile card ─────────

@pytest.fixture
def orders(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("ORDERS_TABLE", ORDERS)
    monkeypatch.setenv("RATE_LIMIT_TABLE", RATE_LIMIT)
    monkeypatch.setenv("APP_ENV", "development")
    h = _load(ORDERS_HANDLER, "customer_orders_downstream_under_test")
    fake = FakeDynamo(
        keys={CONTACTS: "id", ORDERS: "orderId", RATE_LIMIT: "pk"},
        indexes={CONTACTS: {"phone-index": ("phone", None)}},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    return h, fake


def test_the_order_list_profile_card_accepts_the_claimed_contact(orders):
    h, fake = orders
    fake.Table(CONTACTS).put_item(Item=claimed_row())
    profile = h._profile(ClaimedIdentity())
    assert profile is not None
    assert profile["email"] == EMAIL
    assert profile["emailVerified"] is True
    assert profile["addressComplete"] is True


def test_the_order_list_profile_card_is_still_withheld_without_the_claim(orders):
    h, fake = orders
    fake.Table(CONTACTS).put_item(Item=claimed_row(claimed=False))
    assert h._profile(ClaimedIdentity()) is None


# ── gate 3: the WhatsApp catalog services accept the same person ─────────────

def _cognito_users(subject: str = SUBJECT, verified: str = "true") -> list:
    """A `ListUsers` result for the claimed customer, in the shape `verified_identity` reads."""
    return [{"Enabled": True, "Attributes": [
        {"Name": "sub", "Value": subject},
        {"Name": "phone_number", "Value": PHONE},
        {"Name": "phone_number_verified", "Value": verified},
    ]}]


def test_the_catalog_services_gate_accepts_the_claimed_contact():
    from lambda_utils import customer_auth
    from lambda_utils.ecommerce import catalog_service_checkout as catalog

    identity = catalog.verified_identity(claimed_row(), _cognito_users(), PHONE)
    assert isinstance(identity, customer_auth.CustomerIdentity)
    assert identity.customer_id == SUBJECT
    # The pool confirmed the number on the line above, so the session carries the flag honestly -
    # which is what `auth/customer-profile` reads before it claims anything.
    assert identity.phone_verified is True


def test_the_catalog_services_gate_still_refuses_the_unclaimed_contact():
    from lambda_utils import customer_auth
    from lambda_utils.ecommerce import catalog_service_checkout as catalog

    with pytest.raises(customer_auth.CustomerNotAuthorized):
        catalog.verified_identity(claimed_row(claimed=False), _cognito_users(), PHONE)


def test_the_catalog_services_gate_refuses_an_unverified_cognito_phone():
    from lambda_utils import customer_auth
    from lambda_utils.ecommerce import catalog_service_checkout as catalog

    with pytest.raises(customer_auth.CustomerNotAuthorized):
        catalog.verified_identity(claimed_row(), _cognito_users(verified="false"), PHONE)
