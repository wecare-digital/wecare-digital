"""The shared offline harness for the Phase-2 contribution tests.

Extracted rather than duplicated because two test files drive the same handler against the same
`FakeDynamo` and the same stateful Cart V2 fake, and a second copy of a 100-line fixture is how
two files come to disagree about what "a seeded cart pointer" means.

Nothing here reaches AWS, the network or a credential. The Razorpay client is stubbed, the Wix
transport is `tests/contribution_wix.py`, and DynamoDB is `FakeDynamo`.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from contribution_wix import (  # noqa: E402
    CART_ID, CONTRIBUTION_CHOICES, CONTRIBUTION_ID, CONTRIBUTION_VARIANT, CONTRIBUTION_VARIANTS,
    ContributionWix, KIOSK_ID, KIOSK_VARIANT, OTHER_ID, OTHER_VARIANT, REPLACEMENT_CART_ID,
    contribution_line, contribution_paise, kiosk_line, other_line, saved)

from lambda_utils.ecommerce import contact_address  # noqa: E402
from lambda_utils.identity import customer as customer_identity  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
ATTEMPTS_TABLE = "stack-wecare-digital-PaymentAttemptsTable"
KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
CUSTOMER = "CUS_01J8Z9EXAMPLECUSTOMER"

OWNED = {"addressLine1": "12 Dalhousie Square", "city": "Kolkata",
         "state": "West Bengal", "postalCode": "700001"}
WIX_ADDRESS = {"country": "IN", "subdivision": "IN-WB", "city": "Kolkata",
               "postalCode": "700001", "addressLine": "12 Dalhousie Square"}

SESSION_PHONE = "+918100640044"
STORED_PHONE = customer_identity.normalize_phone_preserving_country(SESSION_PHONE)


class _Identity:
    def __init__(self, customer_id=CUSTOMER, phone=SESSION_PHONE):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = "subject-1"

    def owns(self, cid):
        return bool(cid) and cid == self.customer_id


class _Payload:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw


class _FakeLambda:
    def invoke(self, FunctionName=None, InvocationType=None, Payload=None, **_):
        event = json.loads(Payload.decode("utf-8"))
        if "payment-config" in str(event.get("path") or ""):
            inner = {"statusCode": 200, "body": json.dumps({"data": [{
                "configuration_name": "WECAREDIGITAL", "status": "active",
                "payment_gateway": {"type": "razorpay", "merchant_id": "acc_TESTMID"}}]})}
        else:
            inner = {"statusCode": 200, "body": "{}"}
        return {"Payload": _Payload(json.dumps(inner).encode("utf-8"))}


def seed_contact(fake, *, address=OWNED, customer=CUSTOMER):
    fake.Table(CONTACTS_TABLE).put_item(Item={
        "id": "contact-contrib-1", "contactId": "contact-contrib-1", "phone": STORED_PHONE,
        "email": "asha@example.com", "name": "Asha Sen", "firstName": "Asha", "lastName": "Sen",
        "checkoutCustomerId": customer, "emailVerifiedAt": 1, "deletedAt": None,
        contact_address.ATTRIBUTE: dict(address) if address is not None else None,
        contact_address.UPDATED_ATTRIBUTE: 1,
    })


def _load_handler(monkeypatch, *, contribution_env=CONTRIBUTION_ID, committed=(CONTRIBUTION_ID,)):
    monkeypatch.setenv("PAYMENT_ATTEMPTS_TABLE", ATTEMPTS_TABLE)
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("EXPECTED_CONFIGURATION_NAME", "WECAREDIGITAL")
    monkeypatch.setenv("EXPECTED_PROVIDER_MID", "acc_TESTMID")
    monkeypatch.setenv("PAYMENT_WABA_ID", "2094615664435155")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WIX_CART_V2_ENABLED", "true")
    monkeypatch.delenv("WIX_CART_V2_DISABLED", raising=False)
    if contribution_env:
        monkeypatch.setenv("CONTRIBUTION_PRODUCT_ID", contribution_env)
    else:
        monkeypatch.delenv("CONTRIBUTION_PRODUCT_ID", raising=False)

    spec = importlib.util.spec_from_file_location("contribution_handler_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    # The COMMITTED recognition set, which in the shipped tree is empty until the owner's GUID
    # lands. Patched on the module the handler imported it from, so `_contribution_ids` reads it.
    monkeypatch.setattr(h, "CONTRIBUTION_PRODUCT_IDS", frozenset(committed))
    return h


def _stub_gateway(h, monkeypatch, created):
    """A Razorpay order create that records rather than calls.

    Initiation is ENABLED in this file, unlike `tests/test_checkout_website_handler.py`'s default,
    because the properties under test are the reserved attempt, the `PAYREF#` row and the amount
    the gateway was asked for -- and with the gate off `prepare_checkout` returns
    `PAYMENT_INITIATION_DISABLED` and reserves nothing, so there would be nothing to measure. No
    network call and no credential read happens either way: the client is stubbed.
    """
    def create_order(*, amount_paise, receipt, notes):
        created.append({"amount": amount_paise, "receipt": receipt, "notes": dict(notes)})
        return {"id": f"order-contrib-{len(created)}", "amount": amount_paise,
                "currency": "INR", "status": "created", "receipt": receipt,
                "key_id": "fixture-live-publishable"}

    monkeypatch.setattr(h.razorpay_orders, "create_order", create_order)
    monkeypatch.setattr(h.razorpay_orders, "find_order_by_receipt", lambda receipt: None)
    monkeypatch.setattr(h.razorpay_orders, "account_mode", lambda key_id: "live")


def make_env(monkeypatch, *, wix=None, contribution_env=CONTRIBUTION_ID,
             committed=(CONTRIBUTION_ID,), address=OWNED, real_loader=False):
    h = _load_handler(monkeypatch, contribution_env=contribution_env, committed=committed)
    fake = FakeDynamo(keys={ATTEMPTS_TABLE: "paymentAttemptId", KEYS_TABLE: "orderId",
                            CONTACTS_TABLE: "id"},
                      indexes={CONTACTS_TABLE: {"phone-index": ("phone", None)}})
    wix = wix if wix is not None else ContributionWix()
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_lambda_client", lambda: _FakeLambda())
    monkeypatch.setattr(h, "INITIATION_ENABLED", True)
    h.gateway_orders = []
    _stub_gateway(h, monkeypatch, h.gateway_orders)
    monkeypatch.setattr(h, "_wix_request", wix)
    monkeypatch.setattr(h.wix_ecom, "_request", wix)
    monkeypatch.setattr(h.customer_auth, "authenticate", lambda event: _Identity())
    seed_contact(fake, address=address)
    if real_loader:
        monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS", h._load_owned_address)
    else:
        monkeypatch.setattr(h, "LOAD_OWNED_ADDRESS",
                            lambda customer_id: dict(address) if address else address)
    return h, fake, wix


def prepare_event(line_items, **over):
    body = {"lineItems": line_items, "requestKey": "rk-contribution-1"}
    body.update(over)
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.5"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer tok"},
        "rawPath": "/ecommerce/prepare-checkout",
        "body": json.dumps(body),
    }


def create_event(line_items, **over):
    body = {"lineItems": line_items}
    body.update(over)
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.5"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer tok"},
        "body": json.dumps({"action": "create", **body}),
    }


def seed_cart_pointer(h, fake, *, cart_id=CART_ID, version=1, busy=False, now=None):
    """A `CUSTOMERCART#` pointer exactly as `customer_cart.execute` leaves one."""
    item = {"orderId": "CUSTOMERCART#" + STORED_PHONE, "customerId": CUSTOMER,
            "version": version, "wixCartId": cart_id,
            "expiresAt": (now or 2_000_000_000) + 60}
    if busy:
        item["busy"] = True
    fake.Table(KEYS_TABLE).put_item(Item=item)
    return item


def pointer(fake):
    rows = [row for row in fake.all_rows(KEYS_TABLE)
            if str(row["orderId"]).startswith("CUSTOMERCART#")]
    return rows[0] if rows else None


def body_of(response):
    return json.loads(response["body"])
