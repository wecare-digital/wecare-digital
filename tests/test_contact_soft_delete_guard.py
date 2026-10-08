"""A contact tied to money may be archived, never destroyed - asserted at the handler.

`test_contact_payment_links.py` pins the POLICY. This file pins the thing that actually
protects the data: that `core/contacts._delete` consults the policy BEFORE `_hard_delete`
runs, and that a refusal leaves every message row, every S3 object and the contact row
exactly where they were.

The ordering is the whole point. `_hard_delete` deletes messages and media first and the
contact row last, so a check made anywhere inside it would already have destroyed the
history the guard exists to protect. "Nothing was deleted" is therefore asserted as
`delete_item was never called`, not as "the row is still there".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
CONTACTS_HANDLER_PATH = ROOT / "amplify" / "functions" / "core" / "contacts" / "handler.py"
for path in (str(SHARED), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from contacts_fake_table import FakeContactsResource, FakeContactsTable  # noqa: E402
from lambda_utils import payment_status  # noqa: E402
from lambda_utils.ecommerce import contact_payment_links  # noqa: E402

CONTACT_ID = "contact-1"
CUSTOMER_ID = "CUS_ASHA_SEN"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"
INVOICES_TABLE = "stack-wecare-digital-InvoicesTable"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
INBOUND_TABLE = "stack-wecare-digital-WhatsAppInboundTable"
OUTBOUND_TABLE = "stack-wecare-digital-WhatsAppOutboundTable"


class Wiring:
    """The five tables one hard delete touches, each a separate fake.

    A single shared fake would make an invoice row and a contact row indistinguishable, which
    is exactly the distinction under test.
    """

    def __init__(self, *, contact=None, invoices=None, orders=None, messages=None,
                 invoices_error=None, orders_error=None):
        row = {"id": CONTACT_ID, "contactId": CONTACT_ID, "phone": "+918100640044"}
        row.update(contact or {})
        self.contacts = FakeContactsTable([row])
        self.invoices = FakeContactsTable(invoices or [], query_error=invoices_error)
        self.orders = FakeContactsTable(orders or [], query_error=orders_error)
        self.inbound = FakeContactsTable(messages or [])
        self.outbound = FakeContactsTable([])
        self.resource = FakeContactsResource(self.contacts, {
            CONTACTS_TABLE: self.contacts,
            INVOICES_TABLE: self.invoices,
            ORDERS_TABLE: self.orders,
            INBOUND_TABLE: self.inbound,
            OUTBOUND_TABLE: self.outbound,
        })

    @property
    def deleted_anything(self) -> bool:
        return bool(self.contacts.deletes or self.inbound.deletes or self.outbound.deletes)


def contacts_module(monkeypatch, wiring: Wiring):
    """`core/contacts` loaded by path under a unique name, with the fakes wired in.

    By path for the reason `test_crm_api._contacts_module` gives: dozens of Lambdas here have a
    `handler.py` and `sys.modules['handler']` resolves to whichever imported first.
    """
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location(
        "wecare_contacts_delete_guard_under_test", CONTACTS_HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "dynamodb", wiring.resource)
    monkeypatch.setattr(module, "s3_client", _RefusingS3())
    return module


class _RefusingS3:
    """S3 must not be touched on a refusal, and a refusal is the common case here."""

    def delete_object(self, **kwargs):
        raise AssertionError("no S3 object may be deleted on this path")


def body(response) -> dict:
    return json.loads(response["body"])


# ── refused: payments exist ───────────────────────────────────────────────────────────────

def test_a_captured_invoice_refuses_the_hard_delete_and_deletes_nothing(monkeypatch):
    wiring = Wiring(
        invoices=[{"contactId": CONTACT_ID, "paymentStatus": payment_status.CAPTURED}],
        messages=[{"id": "msg-1", "contactId": CONTACT_ID, "s3Key": "o/x.jpg"}],
    )
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-1")

    assert response["statusCode"] == 409
    payload = body(response)
    assert payload["error"] == contacts.HARD_DELETE_REFUSED_PAYMENTS == "CONTACT_HAS_PAYMENTS"
    assert payload["archiveInstead"] is False
    assert not wiring.deleted_anything, "a refusal must not delete a single row"
    assert wiring.contacts.items, "the contact row survives, intact"


def test_a_paid_spelled_invoice_refuses_too(monkeypatch):
    """The spelling a raw `== 'captured'` comparison misses. Through the handler, because this
    is the path where missing it destroys data."""
    wiring = Wiring(invoices=[{"contactId": CONTACT_ID, "paymentStatus": "paid"}])
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-2")

    assert response["statusCode"] == 409
    assert body(response)["error"] == "CONTACT_HAS_PAYMENTS"
    assert not wiring.deleted_anything


def test_an_order_row_refuses_the_hard_delete(monkeypatch):
    wiring = Wiring(contact={"checkoutCustomerId": CUSTOMER_ID},
                    orders=[{"customerId": CUSTOMER_ID, "orderId": "ord-1"}])
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-3")

    assert response["statusCode"] == 409
    assert body(response)["error"] == "CONTACT_HAS_PAYMENTS"
    assert contact_payment_links.SIGNAL_ORDERS in body(response)["signals"]
    assert not wiring.deleted_anything


# ── refused: linkage unknown ──────────────────────────────────────────────────────────────

def test_an_invoice_query_error_refuses_with_a_DISTINCT_code(monkeypatch):
    """Cannot determine is not no payments. Distinct on the wire so the UI can say which
    happened rather than offering one vague failure."""
    wiring = Wiring(invoices_error=RuntimeError("ProvisionedThroughputExceededException"))
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-4")

    assert response["statusCode"] == 409
    payload = body(response)
    assert payload["error"] == contacts.HARD_DELETE_REFUSED_UNKNOWN == "PAYMENT_LINKAGE_UNKNOWN"
    assert payload["archiveInstead"] is False
    assert not wiring.deleted_anything


def test_an_order_query_error_refuses_the_same_way(monkeypatch):
    wiring = Wiring(contact={"checkoutCustomerId": CUSTOMER_ID},
                    orders_error=RuntimeError("ProvisionedThroughputExceededException"))
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-5")

    assert response["statusCode"] == 409
    assert body(response)["error"] == "PAYMENT_LINKAGE_UNKNOWN"
    assert not wiring.deleted_anything


def test_an_unreadable_contact_row_refuses_rather_than_proceeding(monkeypatch):
    """The third fail-closed arm: if the row itself cannot be read, its linkage cannot be
    either, so the guard refuses instead of handing an empty row to the policy."""
    wiring = Wiring()
    contacts = contacts_module(monkeypatch, wiring)

    def explode(**kwargs):
        raise RuntimeError("ProvisionedThroughputExceededException")

    monkeypatch.setattr(wiring.contacts, "get_item", explode)

    response = contacts._delete(CONTACT_ID, True, "req-6")

    assert response["statusCode"] == 409
    assert body(response)["error"] == "PAYMENT_LINKAGE_UNKNOWN"
    assert not wiring.deleted_anything


def test_the_refusal_reason_carries_no_provider_text(monkeypatch):
    """The reason is rendered to an operator and written to a log, so it names the exception
    type and nothing from the exception - a ClientError message can echo request content."""
    wiring = Wiring(invoices_error=RuntimeError("Table ...InvoicesTable says secret-ish"))
    contacts = contacts_module(monkeypatch, wiring)

    payload = body(contacts._delete(CONTACT_ID, True, "req-7"))

    assert "RuntimeError" in payload["reason"]
    assert "secret-ish" not in payload["reason"]


def test_no_refusal_payload_carries_the_phone(monkeypatch):
    """The contact id is the correlation key here. The phone is not needed, so it is absent
    rather than masked."""
    wiring = Wiring(invoices=[{"contactId": CONTACT_ID, "paymentStatus": "paid"}])
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-8")

    assert "8100640044" not in response["body"]


# ── still allowed: a clean contact ────────────────────────────────────────────────────────

def test_a_contact_with_zero_payments_is_still_hard_deletable(monkeypatch):
    """The guard narrows the delete, it does not remove it. A CRM row that never transacted
    must still be destroyable, messages and media included, exactly as before."""
    wiring = Wiring(messages=[{"id": "msg-1", "contactId": CONTACT_ID, "s3Key": "o/x.jpg"}])
    contacts = contacts_module(monkeypatch, wiring)
    deleted_keys = []
    monkeypatch.setattr(contacts, "_delete_s3", lambda key: deleted_keys.append(key))

    response = contacts._delete(CONTACT_ID, True, "req-9")

    assert response["statusCode"] == 200
    payload = body(response)
    assert payload["success"] is True
    assert payload["deleteType"] == "hard"
    assert payload["messagesDeleted"] == 1
    assert payload["mediaDeleted"] == 1
    assert deleted_keys == ["o/x.jpg"]
    assert wiring.contacts.deletes == [{"id": CONTACT_ID}]
    assert wiring.inbound.deletes == [{"id": "msg-1"}]


def test_a_pending_invoice_does_not_make_an_abandoned_cart_undeletable(monkeypatch):
    wiring = Wiring(invoices=[{"contactId": CONTACT_ID,
                               "paymentStatus": payment_status.PENDING}])
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete(CONTACT_ID, True, "req-10")

    assert response["statusCode"] == 200
    assert wiring.contacts.deletes == [{"id": CONTACT_ID}]


def test_a_missing_contact_still_answers_404_and_not_409(monkeypatch):
    """`_hard_delete` owns the not-found answer. The guard returning 409 here would turn a
    plain 404 into an operator chasing a payment that does not exist."""
    wiring = Wiring()
    wiring.contacts.items = []
    contacts = contacts_module(monkeypatch, wiring)

    response = contacts._delete("nobody", True, "req-11")

    assert response["statusCode"] == 404


# ── the soft delete, which is what Archive actually is ────────────────────────────────────

@pytest.mark.parametrize("hard", [False, True])
def test_paid_contact_cannot_be_deleted_or_archived(monkeypatch, hard):
    wiring = Wiring(invoices=[{"contactId": CONTACT_ID, "paymentStatus": "paid"}])
    contacts = contacts_module(monkeypatch, wiring)
    response = contacts._delete(CONTACT_ID, hard, "req-12")
    assert response["statusCode"] == 409
    assert body(response)["archiveInstead"] is False
    assert not wiring.contacts.updates
    assert not wiring.deleted_anything


def test_unpaid_contact_can_still_be_archived(monkeypatch):
    wiring = Wiring()
    response = contacts_module(monkeypatch, wiring)._delete(CONTACT_ID, False, "req-13")
    assert response["statusCode"] == 200
    assert wiring.contacts.items[0]["deletedAt"] is not None


def test_crm_order_phone_blocks_archiving_without_checkout_id(monkeypatch):
    wiring = Wiring(orders=[{"customerPhone": "918100640044", "orderId": "ord-crm"}])
    response = contacts_module(monkeypatch, wiring)._delete(CONTACT_ID, False, "req-14")
    assert response["statusCode"] == 409
    assert not wiring.contacts.updates


def test_unknown_payment_linkage_blocks_archiving(monkeypatch):
    wiring = Wiring(invoices_error=RuntimeError("read failed"))
    response = contacts_module(monkeypatch, wiring)._delete(CONTACT_ID, False, "req-15")
    assert response["statusCode"] == 409
    assert body(response)["error"] == "PAYMENT_LINKAGE_UNKNOWN"
    assert not wiring.contacts.updates


# ── wiring ────────────────────────────────────────────────────────────────────────────────

def test_the_two_table_defaults_match_the_env_manifest(monkeypatch):
    """A recorded-but-not-yet-deployed variable has to be inert, so the in-code default and
    the manifest literal must be the same string."""
    wiring = Wiring()
    contacts = contacts_module(monkeypatch, wiring)
    manifest = json.loads((ROOT / "config" / "lambda-env-manifest.json").read_text(
        encoding="utf-8"))["functions"]["wecare-contacts"]

    assert contacts.INVOICES_TABLE == manifest["INVOICES_TABLE"] == INVOICES_TABLE
    assert contacts.ORDERS_TABLE == manifest["ORDERS_TABLE"] == ORDERS_TABLE


def test_the_resource_declares_the_same_two_literals():
    resource = (ROOT / "amplify" / "functions" / "core" / "contacts" / "resource.ts").read_text(
        encoding="utf-8")
    assert f"INVOICES_TABLE: '{INVOICES_TABLE}'" in resource
    assert f"ORDERS_TABLE: '{ORDERS_TABLE}'" in resource


def test_the_handler_delegates_and_never_compares_a_payment_word_itself(monkeypatch):
    """The policy lives in the shared module so the handler holds no payment vocabulary. The
    AST gate in `test_payment_vocabulary_at_decision_points.py` covers the module; this covers
    the handler's side of that split."""
    source = CONTACTS_HANDLER_PATH.read_text(encoding="utf-8")
    assert "contact_payment_links" in source
    assert "paymentStatus" not in source
