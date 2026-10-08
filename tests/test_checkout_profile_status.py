"""`action:"profile"` on `ecommerce/checkout` — the readiness question, answered with 200.

Why this action exists
----------------------
`cart.tsx` has to know, before it renders anything, whether this signed-in customer can pay
without being asked for a name, an email OTP or an address. Every other answer to that question
costs the customer a form they already filled in.

Two answers, both `200`, with the state in `status`. `PROFILE_REQUIRED` is a question being
answered, not a refused request: a 409 would make the browser treat a normal first-time customer
as an error.

THE MOST IMPORTANT TEST IN THIS FILE
------------------------------------
`test_a_raw_session_phone_still_finds_the_row_the_writer_normalised`. The contact row's partition
key on `phone-index` is the phone, `auth/customer-profile` writes the
`normalize_phone_preserving_country` output, and this handler used to read the RAW session value.
If those two strings can ever differ the consequence is not an error — `action:"profile"` answers
`PROFILE_REQUIRED` forever, `from_contact` returns `None` forever, and checkout keeps refusing
with `DELIVERY_DETAILS_REQUIRED`. A returning customer whose saved profile cannot be found is
re-asked for everything they already gave us, which is the exact bug this phase exists to kill,
and it is silent and log-free. So the row here is seeded the way the WRITER writes it and read
with a differently-spaced session phone.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402

from lambda_utils.ecommerce import contact_address  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
CONTACTS = "stack-wecare-digital-ContactsTable"
ATTEMPTS = "stack-wecare-digital-PaymentAttemptsTable"
KEYS = "stack-wecare-digital-CommerceKeys"
CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"

#: The owner-nominated QA recipient, in the RAW spelling a Cognito attribute could carry.
RAW_PHONE = "+91 81006 40044"
#: The same number as `auth/customer-profile` stores it.
STORED_PHONE = customer_identity.normalize_phone_preserving_country(RAW_PHONE)

ADDRESS = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
           "state": "West Bengal", "postalCode": "700001"}

EMAIL = "asha@example.com"


class Identity:
    def __init__(self, customer_id=CUSTOMER, phone=RAW_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "sub-fixture"

    def owns(self, value):
        return bool(value) and value == self.customer_id


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS)
    monkeypatch.setenv("APP_ENV", "development")

    spec = importlib.util.spec_from_file_location("checkout_profile_status_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(
        keys={CONTACTS: "id", ATTEMPTS: "paymentAttemptId", KEYS: "orderId"},
        indexes={CONTACTS: {"phone-index": ("phone", None)}},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(), None))
    return h, fake, monkeypatch


def seed(fake, **overrides):
    """A contact row exactly as `auth/customer-profile` writes it.

    Keyed on the NORMALISED phone, never on the spelling a test's session happens to use, so the
    read key is under test rather than assumed. Passing a key as `None` removes it.
    """
    row = {
        "id": "contact-1",
        "contactId": "contact-1",
        "phone": STORED_PHONE,
        "email": EMAIL,
        "name": "Asha Sen",
        "firstName": "Asha",
        "lastName": "Sen",
        "checkoutCustomerId": CUSTOMER,
        "emailVerifiedAt": 1,
        "deletedAt": None,
        contact_address.ATTRIBUTE: dict(ADDRESS),
        contact_address.UPDATED_ATTRIBUTE: 1,
    }
    row.update(overrides)
    fake.Table(CONTACTS).put_item(Item={k: v for k, v in row.items() if v is not None
                                        or k == "deletedAt"})
    return row


def event(action="profile", **body):
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer fixture"},
        "body": json.dumps({"action": action, **body}),
    }


def call(h):
    response = h.handler(event(), None)
    return response, json.loads(response["body"])


# ── the §3.0 read-key pin ────────────────────────────────────────────────────────

def test_a_raw_session_phone_still_finds_the_row_the_writer_normalised(env):
    """Seeded under the normaliser's output, read with the raw, differently-spaced session value.

    On a raw lookup this answers `PROFILE_REQUIRED` and a returning customer is treated as new.
    """
    h, fake, _mp = env
    seed(fake)
    assert RAW_PHONE != STORED_PHONE, "the fixture must actually exercise a spelling difference"

    response, body = call(h)
    assert response["statusCode"] == 200
    assert body["status"] == "PROFILE_READY"
    assert body["addressComplete"] is True


def test_a_session_phone_the_normaliser_refuses_misses_rather_than_500s(env):
    """The `_profile_phone` fallback: today's behaviour (a lookup that misses), not a 500."""
    h, fake, monkeypatch = env
    seed(fake)
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda e: (Identity(phone="8100640044"), None))

    response, body = call(h)
    assert response["statusCode"] == 200
    assert body["status"] == "PROFILE_REQUIRED"


# ── the two answers ─────────────────────────────────────────────────────────────

def test_with_no_contact_row_the_answer_is_profile_required_at_200(env):
    h, _fake, _mp = env
    response, body = call(h)
    assert response["statusCode"] == 200
    assert body == {"status": "PROFILE_REQUIRED"}


def test_an_unverified_email_is_not_ready_to_pay(env):
    """`_checkout_profile` is the ready-to-pay predicate and this action does not weaken it."""
    h, fake, _mp = env
    seed(fake, emailVerifiedAt=None)
    _response, body = call(h)
    assert body["status"] == "PROFILE_REQUIRED"


def test_a_row_owned_by_another_customer_is_not_this_session_s_profile(env):
    h, fake, _mp = env
    seed(fake, checkoutCustomerId="CUS_SOMEONE_ELSE")
    _response, body = call(h)
    assert body["status"] == "PROFILE_REQUIRED"


def test_a_complete_row_answers_profile_ready_with_the_whole_identity_card(env):
    h, fake, _mp = env
    seed(fake)
    response, body = call(h)

    assert response["statusCode"] == 200
    assert body["status"] == "PROFILE_READY"
    assert body["contactId"] == "contact-1"
    assert body["name"] == "Asha Sen"
    assert body["firstName"] == "Asha"
    assert body["lastName"] == "Sen"
    assert body["email"] == EMAIL
    assert body["emailVerified"] is True
    assert body["addressComplete"] is True
    assert body["address"]["city"] == "Kolkata"
    assert body["address"]["countryCode"] == "IN"


def test_the_phone_comes_from_the_row_and_not_the_raw_session_value(env):
    """Otherwise the identity card's Phone row changes spelling after an edit."""
    h, fake, _mp = env
    seed(fake)
    _response, body = call(h)
    assert body["phone"] == STORED_PHONE
    assert body["phone"] != RAW_PHONE


def test_a_row_with_no_stored_address_is_ready_but_incomplete(env):
    h, fake, _mp = env
    seed(fake, **{contact_address.ATTRIBUTE: None})
    _response, body = call(h)

    assert body["status"] == "PROFILE_READY"
    assert body["addressComplete"] is False
    assert body["address"] is None


def test_a_stored_address_the_contract_now_refuses_is_reported_as_incomplete(env, caplog):
    """FEAT-003: from_contact is structural only, so a legacy/edge address with an unmapped state
    is reported COMPLETE here; its payability is enforced at the actual checkout
    (payment_address), not pre-judged by the profile-status endpoint.
    """
    h, fake, _mp = env
    seed(fake, **{contact_address.ATTRIBUTE: {"addressLine1": "12 MG Road", "city": "Bengaluru",
                                              "state": "Nowhere Pradesh",
                                              "postalCode": "560001"}})
    with caplog.at_level("INFO"):
        _response, body = call(h)

    assert body["status"] == "PROFILE_READY"
    assert body["addressComplete"] is True
    assert body["address"] is not None
    assert body["address"]["state"] == "Nowhere Pradesh"


def test_the_name_falls_back_to_the_two_parts_when_the_row_has_no_name(env):
    h, fake, _mp = env
    seed(fake, name=None)
    _response, body = call(h)
    assert body["name"] == "Asha Sen"


# ── the response is not cacheable, and the action is not public ──────────────────

def test_both_answers_carry_no_store(env):
    """`cors_response` sets no `Cache-Control`, and Amplify fronts `/api/*` with a shared cache.

    This body carries an email address and a postal address.
    """
    h, fake, _mp = env
    empty = h.handler(event(), None)
    seed(fake)
    ready = h.handler(event(), None)

    for response in (empty, ready):
        assert "no-store" in response["headers"]["Cache-Control"]


def test_an_unauthenticated_caller_gets_the_same_opaque_401_as_every_other_action(env):
    h, fake, monkeypatch = env
    seed(fake)
    denial = {"statusCode": 401, "headers": {}, "body": json.dumps({"error": "UNAUTHORIZED"})}
    monkeypatch.setattr(h.customer_auth, "require_customer", lambda e: (None, denial))

    response = h.handler(event(), None)
    assert response["statusCode"] == 401
    assert EMAIL not in json.dumps(response)


def test_the_action_accepts_no_address_from_the_body(env):
    """Authority comes from the row. A body-supplied address is not read, stored or echoed."""
    h, fake, _mp = env
    seed(fake)
    hostile = event(address={"addressLine1": "1 Attacker Lane", "city": "Mumbai",
                             "state": "Maharashtra", "postalCode": "400001"})
    body = json.loads(h.handler(hostile, None)["body"])

    assert body["address"]["city"] == "Kolkata"
    assert "Attacker" not in json.dumps(body)
    assert fake.all_rows(CONTACTS)[0][contact_address.ATTRIBUTE] == ADDRESS


# ── logs carry no PII, on either answer ─────────────────────────────────────────

def test_no_log_line_carries_an_email_or_any_address_component(env, caplog):
    h, fake, _mp = env
    seed(fake)
    with caplog.at_level("DEBUG"):
        h.handler(event(), None)
        h.handler(event(), None)

    emitted = caplog.text
    for secret in (EMAIL, "asha", "Dalhousie", "Kolkata", "700001", "West Bengal",
                   STORED_PHONE, RAW_PHONE):
        assert secret not in emitted, f"{secret!r} reached a log line"


# ── the dispatch arm exists, so a readiness probe is not a checkout create ──────

def test_the_profile_action_does_not_fall_through_to_the_create_path(env):
    """Adding "profile" to `_action`'s tuple without a dispatch arm routes it into `_create`.

    `_create` with no `lineItems` answers `400 LINE_ITEMS_REQUIRED`, so that mistake is visible
    here rather than only in production.
    """
    h, _fake, _mp = env
    response, body = call(h)
    assert response["statusCode"] == 200
    assert body.get("error") is None
    assert "status" in body
