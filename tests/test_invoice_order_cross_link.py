"""One logical order across channels: an invoice and the order it settles are joinable both ways.

`_cross_link_invoice_and_order` resolves the fulfilment OrderTable row for a just-created invoice
through the immutable CommerceKeys chain (`PAYREF#<ref>` -> paymentAttemptId ->
`PAYMENTATTEMPT#<attempt>` -> orderIdRef) and writes a direct cross-link: `internalOrderId` onto
the invoice, `invoiceId` onto the order. The two records stay SEPARATE — a statutory GST invoice
and a mutable fulfilment order — so this is a cross-link, never a merge.

These tests pin: a resolvable order is linked both ways, an unresolvable reference is a silent
no-op, and the order's finalization money/identity keys are never written by the link.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
sys.path.insert(0, str(FUNCTIONS / "shared"))
sys.path.insert(0, str(Path(__file__).parent))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

REFERENCE_ID = "WD-PAY-XLINK01"
ATTEMPT_ID = "att_xlink_01"
ORDER_ID = "WD-ORD-XL1NK001"
ORDER_NUMBER = "WD-2055"
INVOICE_ID = "inv_xlink_01"
INVOICE_NUMBER = "WD/2627/00042"


@pytest.fixture
def engine(monkeypatch):
    """The real invoice handler, imported with no AWS, pointed at a FakeDynamo for the two tables
    the cross-link reads/writes: CommerceKeys (the resolve chain + the invoice row) and OrderTable."""
    monkeypatch.syspath_prepend(str(FUNCTIONS / "payments" / "invoice-engine"))
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415

    fake = FakeDynamo(keys={handler.COMMERCE_KEYS_TABLE: "orderId",
                            handler.INVOICES_TABLE: "invoiceId",
                            "stack-wecare-digital-OrderTable": "orderId"})
    monkeypatch.setattr(handler, "dynamodb", fake)
    monkeypatch.setattr(handler.shared_tables, "orders_table_name",
                        lambda: "stack-wecare-digital-OrderTable")
    handler._fake = fake
    yield handler
    sys.modules.pop("handler", None)


def _seed_chain(fake, keys_table):
    k = fake.Table(keys_table)
    k.put_item(Item={"orderId": order_keys.PAYMENT_REFERENCE_PREFIX + REFERENCE_ID,
                     "referenceId": REFERENCE_ID, "paymentAttemptId": ATTEMPT_ID})
    k.put_item(Item={"orderId": order_keys.PAYMENT_ATTEMPT_PREFIX + ATTEMPT_ID,
                     "orderIdRef": ORDER_ID, "orderNumber": ORDER_NUMBER,
                     "referenceId": REFERENCE_ID})


def _seed_invoice(fake, invoices_table):
    fake.Table(invoices_table).put_item(Item={
        "invoiceId": INVOICE_ID, "invoiceNumber": INVOICE_NUMBER, "referenceId": REFERENCE_ID,
        "total": "1180.00", "orderId": "order_RZPprovider",  # provider order id namespace
    })


def _seed_order(fake):
    fake.Table("stack-wecare-digital-OrderTable").put_item(Item={
        "orderId": ORDER_ID, "orderNumber": ORDER_NUMBER, "referenceId": REFERENCE_ID,
        "customerId": "cus-1", "paymentAttemptId": ATTEMPT_ID, "providerPaymentId": "pay_1",
        "snapshotHash": "hash-1", "amountPaise": 118000, "currency": "INR",
    })


def test_a_resolvable_order_links_both_ways(engine):
    fake = engine._fake
    _seed_chain(fake, engine.COMMERCE_KEYS_TABLE)
    _seed_invoice(fake, engine.INVOICES_TABLE)
    _seed_order(fake)

    engine._cross_link_invoice_and_order(REFERENCE_ID, INVOICE_ID, INVOICE_NUMBER, "req-1")

    inv = fake.Table(engine.INVOICES_TABLE).get_item(Key={"invoiceId": INVOICE_ID})["Item"]
    order = fake.Table("stack-wecare-digital-OrderTable").get_item(
        Key={"orderId": ORDER_ID})["Item"]
    # Invoice -> order, on a distinct attribute (the invoice's own `orderId` stays the provider id).
    assert inv["internalOrderId"] == ORDER_ID
    assert inv["orderNumber"] == ORDER_NUMBER
    assert inv["orderId"] == "order_RZPprovider"
    # Order -> invoice.
    assert order["invoiceId"] == INVOICE_ID
    assert order["invoiceNumber"] == INVOICE_NUMBER


def test_the_order_money_and_identity_keys_are_never_written(engine):
    fake = engine._fake
    _seed_chain(fake, engine.COMMERCE_KEYS_TABLE)
    _seed_invoice(fake, engine.INVOICES_TABLE)
    _seed_order(fake)
    before = dict(fake.Table("stack-wecare-digital-OrderTable").get_item(
        Key={"orderId": ORDER_ID})["Item"])

    engine._cross_link_invoice_and_order(REFERENCE_ID, INVOICE_ID, INVOICE_NUMBER, "req-1")

    order = fake.Table("stack-wecare-digital-OrderTable").get_item(
        Key={"orderId": ORDER_ID})["Item"]
    for key in ("customerId", "paymentAttemptId", "providerPaymentId", "snapshotHash",
                "orderNumber", "amountPaise", "currency"):
        assert order[key] == before[key], key


def test_an_unresolvable_reference_is_a_silent_no_op(engine):
    fake = engine._fake
    # No PAYREF chain: the invoice belongs to a payment with no finalised order yet.
    _seed_invoice(fake, engine.INVOICES_TABLE)
    _seed_order(fake)

    engine._cross_link_invoice_and_order(REFERENCE_ID, INVOICE_ID, INVOICE_NUMBER, "req-1")

    inv = fake.Table(engine.INVOICES_TABLE).get_item(Key={"invoiceId": INVOICE_ID})["Item"]
    order = fake.Table("stack-wecare-digital-OrderTable").get_item(
        Key={"orderId": ORDER_ID})["Item"]
    assert "internalOrderId" not in inv
    assert "invoiceId" not in order


def test_empty_arguments_touch_nothing(engine):
    fake = engine._fake
    _seed_chain(fake, engine.COMMERCE_KEYS_TABLE)
    _seed_invoice(fake, engine.INVOICES_TABLE)
    _seed_order(fake)

    engine._cross_link_invoice_and_order("", INVOICE_ID, INVOICE_NUMBER, "req-1")
    engine._cross_link_invoice_and_order(REFERENCE_ID, "", INVOICE_NUMBER, "req-1")

    inv = fake.Table(engine.INVOICES_TABLE).get_item(Key={"invoiceId": INVOICE_ID})["Item"]
    assert "internalOrderId" not in inv
