"""Retain contacts with payment or order history for both delete modes.

Queries invoices by contact id, orders by stable checkout customer id, and CRM
orders by customer phone. Phone variants are used only to prevent deletion,
never to grant customer access to an order. Unreadable linkage refuses deletion.
Tables are injected so this policy can be tested without AWS clients.
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
        while response.get("LastEvaluatedKey"):
            response = invoices_table.query(
                IndexName=invoices_index,
                KeyConditionExpression="contactId = :cid",
                ExpressionAttributeValues={":cid": contact_id},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            invoices.extend(response.get("Items") or [])
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

    # Orders may be linked by checkout identity or by the CRM customer phone.
    checkout_customer_id = str((contact_row or {}).get(CHECKOUT_CUSTOMER_ATTRIBUTE) or "").strip()
    if checkout_customer_id:
        try:
            response = orders_table.query(
                IndexName=orders_index,
                KeyConditionExpression="customerId = :cust",
                ExpressionAttributeValues={":cust": checkout_customer_id},
                Limit=1,
            )
        except Exception as exc:
            raise PaymentLinkageUnknown(
                f"the order linkage could not be read: {type(exc).__name__}") from None
        signals.append(SIGNAL_ORDERS)
        if response.get("Items"):
            return PaymentLinkage(True, "an order is linked to this customer identity", tuple(signals))
    else:
        signals.append(SIGNAL_ORDERS_SKIPPED)

    raw_phone = str((contact_row or {}).get("phone") or "").strip()
    digits = "".join(c for c in raw_phone if c.isdigit())
    if digits:
        if len(digits) == 10:
            digits = "91" + digits
        variants = [raw_phone, "+" + digits, digits]
        if len(digits) == 12 and digits.startswith("91"):
            variants.append(digits[2:])
        for phone in dict.fromkeys(variants):
            try:
                response = orders_table.query(
                    IndexName="customerPhone",
                    KeyConditionExpression="customerPhone = :phone",
                    ExpressionAttributeValues={":phone": phone},
                    Limit=1,
                )
            except Exception as exc:
                raise PaymentLinkageUnknown(
                    f"the order phone linkage could not be read: {type(exc).__name__}") from None
            if response.get("Items"):
                return PaymentLinkage(True, "an order is linked to this customer phone",
                                      tuple(signals + ["orders-by-phone"]))
        signals.append("orders-by-phone")
    return PaymentLinkage(False, "no invoice and no order is linked to this contact", tuple(signals))
