"""Read-only service attribution for the existing statutory invoice ledger.

Vault/Drop Docs are *file/intent-bound* service payments. A label or invoice item
name is not proof of that binding. Only a reserved PAYREF -> verified captured
PaymentAttempt may classify an invoice as a service purchase.

This module never writes payment, order, or invoice data. It deliberately reuses
the two GetItem permissions already granted to the canonical Commerce Lambda;
no new table, GSI, IAM permission, or separate payment processor is introduced.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from lambda_utils.ecommerce import order_keys, service_requests

SERVICE_KINDS = frozenset(service_requests.SERVICE_KIND_BY_SLUG.values())


def _paise(value: Any) -> int | None:
    try:
        minor = Decimal(str(value)) * 100
        if not minor.is_finite() or minor != minor.to_integral_value() or minor < 0:
            return None
        return int(minor)
    except (ValueError, TypeError, InvalidOperation):
        return None


def verified_service_kind(
    invoice: Mapping[str, Any],
    commerce_keys_table: Any,
    payment_attempts_table: Any,
) -> str:
    """Return the source service kind only when exact paid lineage is proven.

    There may be multiple services with the same price, customer, or display
    name. None of those is an identifier. Unknown/old records remain unclassified
    rather than being silently counted as Vault.
    """
    ref = str(invoice.get("referenceId") or "").strip()
    invoice_payment = str(invoice.get("providerPaymentId")
                          or invoice.get("paymentId") or "").strip()
    if not ref.startswith(order_keys.REFERENCE_ID_PREFIX) or not invoice_payment:
        return ""

    reservation = order_keys.resolve_payment_reference(commerce_keys_table, ref) or {}
    if str(reservation.get("referenceId") or "") != ref:
        return ""
    attempt_id = str(reservation.get("paymentAttemptId") or "").strip()
    if not attempt_id:
        return ""

    attempt = payment_attempts_table.get_item(
        Key={"paymentAttemptId": attempt_id}, ConsistentRead=True
    ).get("Item") or {}
    kind = str(attempt.get("serviceKind") or "")
    if kind not in SERVICE_KINDS:
        return ""
    if (str(attempt.get("referenceId") or "") != ref
            or str(attempt.get("status") or "") != "PAYMENT_PAID"):
        return ""
    if str(attempt.get("verifiedProviderPaymentId") or "") != invoice_payment:
        return ""
    linked_invoice = str(attempt.get("invoiceId") or "")
    if linked_invoice and linked_invoice != str(invoice.get("invoiceId") or ""):
        return ""
    if (str(invoice.get("currency") or "INR")
            != str(attempt.get("currency") or "INR")):
        return ""

    invoiced_paise = _paise(invoice.get("total"))
    try:
        captured_paise = int(attempt.get("verifiedCapturedPaise"))
    except (ValueError, TypeError):
        return ""
    if invoiced_paise is None or invoiced_paise != captured_paise:
        return ""
    return kind


__all__ = ["SERVICE_KINDS", "verified_service_kind"]
