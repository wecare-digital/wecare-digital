"""Whether a contact is tied to money, answered by two indexed queries and no scan.

Why this exists
---------------
A contact that has paid is the provenance record for that payment. Deleting the row destroys
the only link between a captured payment and the human it belongs to - the same reason a
short-link is never deleted once it has been resolved. So a contact with any payment or order
may be ARCHIVED and never hard-deleted, and this module answers the question the archive rule
turns on: *is there money attached to this row?*

It holds the policy and no AWS client. Every table is injected, matching `payment_attempt.py`
and `order_creation.py`, so the decision is testable offline and so the word `captured` never
has to appear in a handler.

The two signals
---------------
======  ==========================================  ============================  =========================================
Signal  Table                                       Index                         Blocks when
======  ==========================================  ============================  =========================================
1       ``stack-wecare-digital-InvoicesTable``      ``contactId-index``           any invoice at or past the rank of
                                                                                  `payment_status.CAPTURED`, **or** one
                                                                                  carrying a non-empty ``paymentId``
2       ``stack-wecare-digital-OrderTable``         ``customerId-createdAt-index`` **any** row exists for the contact's
                                                                                  ``checkoutCustomerId``
======  ==========================================  ============================  =========================================

Both indexes already exist and both are already readable by the shared role
`wecare-digital-lambda-role`, which holds `dynamodb:Query` on `table/stack-wecare-digital-*`
and on `/index/*`. `core/crm._payments_for_contact` queries signal 1's index today, and its
docstring records that PaymentsTable carries only `orderId-index` and `paymentId-index` - which
is why there is no third signal and nothing to add. **No IAM change is needed for this module.**

Signal 2 deliberately performs no status check. `order_keys`' module docstring states the
invariant: "an order does not exist until a payment has been authoritatively verified as paid".
Existence IS the proof, so asking a second question about status could only ever weaken it.

Every status comparison goes through `lambda_utils.payment_status`. Not a style preference: the
measured defect class is `== 'captured'` missing a row stored as `paid`, and on this path that
mistake reads as "no payments" and lets the delete through.
`tests/test_payment_vocabulary_at_decision_points.py` walks this file's AST to keep it that way.

Fail closed, because "cannot determine" is not "no payments"
------------------------------------------------------------
Any storage error from either query raises `PaymentLinkageUnknown`, and the caller must refuse
the hard delete. A guard that answers "probably fine" on a throttled query is not a guard. The
exception message carries the exception TYPE only, never `str(exc)`: a botocore `ClientError`
message can echo request content, and this value is logged.

Known residual, recorded rather than hidden
-------------------------------------------
A contact that paid but carries neither a ``checkoutCustomerId`` nor any InvoicesTable row is
invisible to both signals. Closing that would need a new GSI or a table scan on a delete path,
and neither is justified: a paying customer reaches `auth/customer-profile` (which stamps
``checkoutCustomerId``) or the invoice engine (which writes a row carrying ``contactId``), so
the uncovered set is empty in practice. Tracked as a LOW gap, not fixed here.
"""

from __future__ import annotations

from typing import Any, List, Mapping, NamedTuple, Optional, Tuple

from lambda_utils import contact_key
from lambda_utils import payment_status

#: The index names, defaults rather than literals at the call site so a rename is one edit.
INVOICES_INDEX = "contactId-index"
ORDERS_INDEX = "customerId-createdAt-index"

#: The attribute `auth/customer-profile` stamps when a customer transacts on the website. It is
#: the ONLY join key between a ContactsTable row and `OrderTable.customerId`.
CHECKOUT_CUSTOMER_ATTRIBUTE = "checkoutCustomerId"

#: Names recorded in `PaymentLinkage.signals`, so a log line says which signals were available
#: rather than implying both ran. A skipped signal is reported, never silently omitted.
SIGNAL_INVOICES = "invoices"
SIGNAL_ORDERS = "orders"
SIGNAL_ORDERS_SKIPPED = "orders-skipped-no-checkout-customer-id"


class PaymentLinkageUnknown(RuntimeError):
    """The linkage could not be read, so it must be treated as present.

    A distinct type because the correct response is not "assume none": the caller has to
    refuse the delete, and an ordinary falsy answer would let it through.
    """


class PaymentLinkage(NamedTuple):
    """The answer, plus which signals produced it.

    `reason` is operator-facing prose and is safe to put on the wire and in a log: it names
    the signal, never an amount, a phone number or an invoice id.
    """

    blocked: bool
    reason: str
    signals: Tuple[str, ...]


def has_payment_links(*,
                      invoices_table: Any,
                      orders_table: Any,
                      contact_row: Optional[Mapping[str, Any]],
                      invoices_index: str = INVOICES_INDEX,
                      orders_index: str = ORDERS_INDEX) -> PaymentLinkage:
    """Is this contact tied to a payment or an order? Raises `PaymentLinkageUnknown` if unsure.

    Returns on the FIRST blocking signal, so a contact with a captured invoice costs one query.
    A clean contact costs two, which is the case worth paying for.

    Conditions are composed as STRING key expressions with `ExpressionAttributeValues`, the
    dialect `core/contacts` already speaks, rather than with `boto3.dynamodb.conditions.Key`.
    That keeps this module free of any boto3 import at all, which is what makes it a policy
    module rather than a second place that talks to AWS.
    """
    contact_id = contact_key.resolve(contact_row)
    if not contact_id:
        # No key means neither query can even be addressed. Fail closed: a row we cannot
        # identify is a row whose payments we cannot rule out.
        raise PaymentLinkageUnknown(
            "the contact row carries no id, so its payment linkage cannot be read")

    signals: List[str] = []

    # ── Signal 1: invoices ────────────────────────────────────────────────────────────────
    try:
        response = invoices_table.query(
            IndexName=invoices_index,
            KeyConditionExpression="contactId = :cid",
            ExpressionAttributeValues={":cid": contact_id},
        )
        invoices = list(response.get("Items") or [])
    except Exception as exc:  # noqa: BLE001 - every failure is "unknown", and unknown blocks
        # `from None` deliberately: chaining would carry the provider's own message into any
        # traceback that gets logged, and a ClientError message can echo request content.
        raise PaymentLinkageUnknown(
            f"the invoice linkage could not be read: {type(exc).__name__}") from None
    signals.append(SIGNAL_INVOICES)

    captured_rank = payment_status.rank(payment_status.CAPTURED)
    for invoice in invoices:
        if payment_status.rank(invoice.get("paymentStatus")) >= captured_rank:
            return PaymentLinkage(
                True,
                "an invoice for this contact has reached or passed capture",
                tuple(signals))
        if str(invoice.get("paymentId") or "").strip():
            # A provider payment id on the invoice is money regardless of what the status
            # column says: the id only exists because Razorpay issued it.
            return PaymentLinkage(
                True,
                "an invoice for this contact carries a provider payment id",
                tuple(signals))

    # ── Signal 2: orders ──────────────────────────────────────────────────────────────────
    checkout_customer_id = str((contact_row or {}).get(CHECKOUT_CUSTOMER_ATTRIBUTE) or "").strip()
    if not checkout_customer_id:
        # Nothing to query by, so the signal is RECORDED AS SKIPPED rather than counted as a
        # clean result. The difference matters when reading a log after an argument about
        # whether a delete should have been allowed.
        signals.append(SIGNAL_ORDERS_SKIPPED)
        return PaymentLinkage(
            False,
            "no invoice linkage, and no checkoutCustomerId to look orders up by",
            tuple(signals))

    try:
        response = orders_table.query(
            IndexName=orders_index,
            KeyConditionExpression="customerId = :cust",
            ExpressionAttributeValues={":cust": checkout_customer_id},
            Limit=1,
        )
        orders = list(response.get("Items") or [])
    except Exception as exc:  # noqa: BLE001 - see signal 1
        raise PaymentLinkageUnknown(
            f"the order linkage could not be read: {type(exc).__name__}") from None
    signals.append(SIGNAL_ORDERS)

    if orders:
        # No status check, on purpose. `order_keys`: "an order does not exist until a payment
        # has been authoritatively verified as paid." Existence is the proof.
        return PaymentLinkage(
            True,
            "an order exists for this contact, and an order is only created after a verified payment",
            tuple(signals))

    return PaymentLinkage(False, "no invoice and no order is linked to this contact", tuple(signals))
