"""The WhatsApp post-pay flow writes its info back onto the ONE OrderTable row it belongs to.

A flow completion echoes a payment `reference_id` (`WD-PAY-...`), never the canonical OrderTable
`orderId` (`WD-ORD-...`). `_link_flow_submission_to_order` is the join: it resolves the order
through the immutable CommerceKeys chain the payment already wrote
(`PAYREF#<ref>` -> paymentAttemptId -> `PAYMENTATTEMPT#<attempt>` -> orderIdRef) and decorates
that order row with the flow `submissionId` and the delivery address the flow collected — never
creating an order, never touching a money field.

These tests pin the three outcomes that matter: a resolvable order is decorated (both the join id
and the address land on it), an unresolvable reference is a silent no-op (a pending attempt is the
normal case, not an error), and the five finalization conflict keys are never written here.
"""
from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INBOUND_DIR = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler"
for _p in (str(ROOT / "amplify/functions/shared"), str(INBOUND_DIR),
           str(INBOUND_DIR / "modules"), str(pathlib.Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import contact_address, order_keys  # noqa: E402

KEYS_TABLE = "stack-wecare-digital-CommerceKeys"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"

REFERENCE_ID = "WD-PAY-FLOWLINK01"
ATTEMPT_ID = "att_flowlink_01"
ORDER_ID = "WD-ORD-FL0WL1NK"
ORDER_NUMBER = "WD-1042"
SUBMISSION_ID = "req_flowlink_01"

ADDRESS_VALUES = {
    "address": "12 MG Road", "landmark_area": "Near Park", "city": "Mumbai",
    "state": "Maharashtra", "in_pin_code": "400051",
}


@pytest.fixture
def engine(monkeypatch):
    """The inbound handler loaded against a FakeDynamo wired for the two tables the join reads
    and writes: CommerceKeys (the PAYREF/PAYMENTATTEMPT chain) and OrderTable."""
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setenv("ORDERS_TABLE", ORDERS_TABLE)
    fake = FakeDynamo(keys={KEYS_TABLE: "orderId", ORDERS_TABLE: "orderId"})
    import importlib
    import handler as _handler  # noqa: F401 — the inbound handler module
    importlib.reload(_handler)
    monkeypatch.setattr(_handler, "dynamodb", fake)
    monkeypatch.setattr(_handler, "COMMERCE_KEYS_TABLE", KEYS_TABLE)
    monkeypatch.setattr(_handler.shared_tables, "orders_table_name", lambda: ORDERS_TABLE)
    return _handler, fake


def _seed_payref_chain(fake):
    """The immutable chain finalization/initiation already writes: PAYREF -> attempt -> order."""
    keys = fake.Table(KEYS_TABLE)
    keys.put_item(Item={"orderId": order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE_ID,
                        "referenceId": REFERENCE_ID, "paymentAttemptId": ATTEMPT_ID})
    keys.put_item(Item={"orderId": order_keys.PAYMENT_ATTEMPT_PREFIX + ATTEMPT_ID,
                        "orderIdRef": ORDER_ID, "orderNumber": ORDER_NUMBER,
                        "referenceId": REFERENCE_ID})


def _seed_order(fake):
    """A committed order row, as finalization.accept_paid leaves it (money fields present)."""
    fake.Table(ORDERS_TABLE).put_item(Item={
        "orderId": ORDER_ID, "orderNumber": ORDER_NUMBER, "referenceId": REFERENCE_ID,
        "customerId": "cus-1", "paymentAttemptId": ATTEMPT_ID, "providerPaymentId": "pay_1",
        "snapshotHash": "hash-1", "amountPaise": 100000, "currency": "INR",
        "paymentStatus": "PAYMENT_PAID",
    })


def _canonical():
    return contact_address.normalize_for_storage(
        contact_address.map_meta_address(ADDRESS_VALUES))


def test_a_resolvable_order_is_decorated_with_the_submission_and_the_address(engine):
    handler, fake = engine
    _seed_payref_chain(fake)
    _seed_order(fake)

    handler._link_flow_submission_to_order(REFERENCE_ID, SUBMISSION_ID, _canonical(), "req-1")

    row = fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"]
    assert row["flowSubmissionId"] == SUBMISSION_ID
    assert row["shippingAddress"].startswith("12 MG Road")
    # The order carries the SAME canonical Map the contact does — one address, not two.
    assert row[contact_address.ATTRIBUTE]["city"] == "Mumbai"
    assert row[contact_address.ATTRIBUTE]["postalCode"] == "400051"


def test_the_money_and_identity_keys_are_never_written_by_the_link(engine):
    handler, fake = engine
    _seed_payref_chain(fake)
    _seed_order(fake)
    before = dict(fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"])

    handler._link_flow_submission_to_order(REFERENCE_ID, SUBMISSION_ID, _canonical(), "req-1")

    row = fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"]
    # The five keys the finalization association-conflict guard compares are untouched.
    for key in ("customerId", "paymentAttemptId", "providerPaymentId", "snapshotHash",
                "orderNumber", "amountPaise", "currency"):
        assert row[key] == before[key], key


def test_an_unresolvable_reference_is_a_silent_no_op(engine):
    handler, fake = engine
    # No PAYREF chain seeded: the reference belongs to a pending/failed attempt with no order yet.
    _seed_order(fake)
    before = dict(fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"])

    handler._link_flow_submission_to_order(REFERENCE_ID, SUBMISSION_ID, _canonical(), "req-1")

    row = fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"]
    assert "flowSubmissionId" not in row
    assert row == before


def test_an_empty_reference_touches_nothing(engine):
    handler, fake = engine
    _seed_payref_chain(fake)
    _seed_order(fake)

    handler._link_flow_submission_to_order("", SUBMISSION_ID, _canonical(), "req-1")

    row = fake.Table(ORDERS_TABLE).get_item(Key={"orderId": ORDER_ID})["Item"]
    assert "flowSubmissionId" not in row
