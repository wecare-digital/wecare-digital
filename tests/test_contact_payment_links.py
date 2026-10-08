"""The hard-delete guard's policy: two indexed signals, and an unknown answer blocks.

Why each case here is the case
------------------------------
The failure this guard prevents has no undo. `_hard_delete` deletes every message row and
every S3 media object before it deletes the contact, so a guard that answers "no payments"
when it does not know has already destroyed the provenance for a captured payment by the time
anyone notices.

So the tests split into three groups rather than two:

  BLOCKED      the signal fired. Includes the `paid` spelling, which is the one a raw
               `== 'captured'` comparison misses - the measured defect class.
  NOT BLOCKED  the signals ran and found nothing. A pending invoice is not money.
  UNKNOWN      a query raised. This must NOT be in the "not blocked" group, and the only
               reason it is a separate exception type rather than a falsy answer is that a
               falsy answer would let the delete through.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
for path in (str(SHARED), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from contacts_fake_table import FakeContactsTable  # noqa: E402
from lambda_utils import payment_status  # noqa: E402
from lambda_utils.ecommerce import contact_payment_links as links  # noqa: E402

CONTACT_ID = "contact-1"
CUSTOMER_ID = "CUS_ASHA_SEN"

#: A CRM-created row: no `checkoutCustomerId`, because only the checkout path writes one.
CRM_ROW = {"id": CONTACT_ID, "contactId": CONTACT_ID, "phone": "+918100640044"}

#: The same contact after it has transacted on the website.
WEBSITE_ROW = {**CRM_ROW, "checkoutCustomerId": CUSTOMER_ID}


def ask(*, invoices=None, orders=None, contact_row=WEBSITE_ROW,
        invoices_error=None, orders_error=None):
    return links.has_payment_links(
        invoices_table=FakeContactsTable(invoices or [], query_error=invoices_error),
        orders_table=FakeContactsTable(orders or [], query_error=orders_error),
        contact_row=contact_row,
    )


# ── blocked ───────────────────────────────────────────────────────────────────────────────

def test_a_captured_invoice_blocks():
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": payment_status.CAPTURED}])
    assert result.blocked
    assert links.SIGNAL_INVOICES in result.signals


def test_a_paid_spelled_invoice_blocks_which_is_the_whole_point():
    """`paid` and `captured` are one state. A raw `== 'captured'` comparison returns False
    here, which on this path means "no payments" and permits the delete - the dangerous
    direction, and the reason every comparison goes through `payment_status.rank`."""
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": "paid"}])
    assert result.blocked


def test_a_refunded_invoice_still_blocks():
    """A refund is proof money moved, not proof it did not. `refunded` outranks `captured` on
    the ladder, so `>= rank(CAPTURED)` already covers it - asserted so a later `== CAPTURED`
    'simplification' fails here."""
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": payment_status.REFUNDED}])
    assert result.blocked


def test_an_invoice_carrying_a_payment_id_blocks_whatever_its_status_says():
    """The id only exists because Razorpay issued it. A status column that disagrees is a
    stale column, not an absence of money."""
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": "pending",
                            "paymentId": "pay_ABC123"}])
    assert result.blocked
    assert "payment id" in result.reason


def test_an_order_row_blocks_with_no_status_check_at_all():
    """`order_keys`: an order does not exist until a payment has been authoritatively verified
    as paid. So existence is the proof, and the row here deliberately carries NO status."""
    result = ask(orders=[{"customerId": CUSTOMER_ID, "orderId": "ord-1"}])
    assert result.blocked
    assert result.signals == (links.SIGNAL_INVOICES, links.SIGNAL_ORDERS)


def test_the_invoice_signal_short_circuits_before_the_order_query():
    """One query for the common blocking case. Also pins that `signals` reports what RAN."""
    orders = FakeContactsTable([{"customerId": CUSTOMER_ID}])
    result = links.has_payment_links(
        invoices_table=FakeContactsTable([{"contactId": CONTACT_ID, "paymentStatus": "paid"}]),
        orders_table=orders,
        contact_row=WEBSITE_ROW,
    )
    assert result.blocked
    assert orders.queries == [], "the order index must not be read once the answer is known"
    assert result.signals == (links.SIGNAL_INVOICES,)


# ── not blocked ───────────────────────────────────────────────────────────────────────────

def test_a_pending_only_invoice_with_no_order_does_not_block():
    """An abandoned checkout is not a payment. Blocking here would make every abandoned cart
    permanently undeletable, which is how a guard gets switched off."""
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": payment_status.PENDING}])
    assert not result.blocked


def test_a_failed_invoice_does_not_block():
    result = ask(invoices=[{"contactId": CONTACT_ID, "paymentStatus": payment_status.FAILED}])
    assert not result.blocked


def test_nothing_at_all_does_not_block():
    result = ask()
    assert not result.blocked
    assert result.signals == (links.SIGNAL_INVOICES, links.SIGNAL_ORDERS)


def test_another_contacts_invoice_does_not_block_this_one():
    """The index query is keyed, so this also proves the fake is filtering rather than
    returning everything it holds."""
    result = ask(invoices=[{"contactId": "someone-else", "paymentStatus": "paid"}])
    assert not result.blocked


def test_another_customers_order_does_not_block_this_contact():
    result = ask(orders=[{"customerId": "CUS_SOMEONE_ELSE"}])
    assert not result.blocked


# ── the skipped signal is reported, not hidden ────────────────────────────────────────────

def test_the_order_signal_is_skipped_and_RECORDED_without_a_checkout_customer_id():
    """A CRM-only row has nothing to query `OrderTable.customerId` by. Recording the skip is
    what lets a log line say which signals were available instead of implying both ran."""
    orders = FakeContactsTable([{"customerId": CUSTOMER_ID}])
    result = links.has_payment_links(
        invoices_table=FakeContactsTable([]),
        orders_table=orders,
        contact_row=CRM_ROW,
    )
    assert not result.blocked
    assert result.signals == (links.SIGNAL_INVOICES, links.SIGNAL_ORDERS_SKIPPED)
    assert orders.queries == [], "there is no key to query by, so no query may be made"


def test_a_blank_checkout_customer_id_counts_as_absent():
    result = ask(contact_row={**CRM_ROW, "checkoutCustomerId": "   "})
    assert result.signals[-1] == links.SIGNAL_ORDERS_SKIPPED


# ── unknown blocks ────────────────────────────────────────────────────────────────────────

def test_an_invoice_query_error_raises_rather_than_answering_no():
    with pytest.raises(links.PaymentLinkageUnknown):
        ask(invoices_error=RuntimeError("ProvisionedThroughputExceededException"))


def test_an_order_query_error_raises_too():
    with pytest.raises(links.PaymentLinkageUnknown):
        ask(orders_error=RuntimeError("ProvisionedThroughputExceededException"))


def test_the_unknown_message_names_only_the_exception_TYPE():
    """A botocore `ClientError` message can echo request content, and this value is logged and
    put on the wire. So the message carries the type name and nothing from the exception."""
    with pytest.raises(links.PaymentLinkageUnknown) as caught:
        ask(invoices_error=RuntimeError("Table stack-wecare-digital-InvoicesTable: secret-ish"))
    message = str(caught.value)
    assert "RuntimeError" in message
    assert "secret-ish" not in message
    assert caught.value.__cause__ is None, (
        "chaining would carry the provider's own message into any logged traceback")


def test_a_row_with_no_usable_id_raises_rather_than_answering_no():
    """Neither query can even be addressed, which is the definition of cannot-determine."""
    for row in (None, {}, {"phone": "+918100640044"}):
        with pytest.raises(links.PaymentLinkageUnknown):
            ask(contact_row=row)


def test_unknown_is_an_exception_and_not_a_falsy_result():
    """Pins the shape of the fail-closed contract. If this ever became a `PaymentLinkage` with
    `blocked=False`, every caller written as `if not result.blocked: delete()` would start
    destroying paid contacts on a throttled query."""
    assert issubclass(links.PaymentLinkageUnknown, Exception)
    assert not isinstance(links.PaymentLinkage(False, "", ()), links.PaymentLinkageUnknown)


# ── the queries themselves ────────────────────────────────────────────────────────────────

def test_both_signals_query_an_INDEX_and_never_scan():
    """A scan on a delete path is a full-table read per click, and `contact_payment_links`
    holds no `scan` at all - asserted on the calls so a later 'fallback' is caught."""
    invoices = FakeContactsTable([])
    orders = FakeContactsTable([])
    links.has_payment_links(invoices_table=invoices, orders_table=orders,
                            contact_row=WEBSITE_ROW)

    assert invoices.queries[0]["IndexName"] == links.INVOICES_INDEX == "contactId-index"
    assert orders.queries[0]["IndexName"] == links.ORDERS_INDEX == "customerId-createdAt-index"
    assert invoices.scans == [] and orders.scans == []
    # Limit=1 on the order query: existence is the whole question, so reading more rows would
    # be paying for data the decision cannot use.
    assert orders.queries[0]["Limit"] == 1


def test_the_module_imports_no_boto3():
    """It is a policy module. Every table is injected, so it needs no client and no credential
    - the same contract `payment_attempt.py` and `order_creation.py` hold.

    Walked with `ast` rather than searched as text, for the reason the payment-vocabulary gate
    gives: the module's own docstring explains why it does not use `boto3.dynamodb.conditions`,
    so a substring search flags its own explanation.
    """
    import ast

    tree = ast.parse(
        (SHARED / "lambda_utils" / "ecommerce" / "contact_payment_links.py").read_text(
            encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "boto3" not in imported
    assert "botocore" not in imported
