"""Per-item process preparation. Drafts never send or launch a WhatsApp Flow.

The invoice and provider capture stay authoritative. A retained contact identity
is never unlocked here, and a draft cannot turn a browser status into a payment.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

ITEM_IDS = frozenset(f"fixed-{n:02d}" for n in range(1, 30))
CONFIG_KEYS = frozenset(f"payment_item_process_fixed_{n:02d}" for n in range(1, 30))
FIELDS = frozenset({"schemaVersion", "itemId", "processId", "trigger", "enabled",
                    "processDescription", "templateName", "templateId", "flowId", "startScreen"})


def validate_draft(key: str, proposed: Any) -> str:
    if key not in CONFIG_KEYS or not isinstance(proposed, dict) or set(proposed) != FIELDS:
        return "Invalid item process draft"
    item_id = proposed.get("itemId")
    if (not isinstance(item_id, str) or item_id not in ITEM_IDS or key != "payment_item_process_" + item_id.replace("-", "_")
            or proposed.get("processId") != "payment-item-" + item_id
            or proposed.get("schemaVersion") != 1 or type(proposed.get("schemaVersion")) is not int
            or proposed.get("trigger") != "payment.captured" or proposed.get("enabled") is not False):
        return "Item process must remain a draft bound to verified payment capture"
    limits = {"processDescription": 3000, "templateName": 128, "templateId": 30,
              "flowId": 30, "startScreen": 100}
    for field, limit in limits.items():
        value = proposed.get(field)
        if not isinstance(value, str) or len(value) > limit:
            return "Invalid process field: " + field
    if proposed["templateName"] and not re.fullmatch(r"[a-z0-9_]+", proposed["templateName"]):
        return "Template name must use Meta's lowercase name"
    for field in ("templateId", "flowId"):
        if proposed[field] and not proposed[field].isdigit():
            return "Meta identifiers must contain digits only"
    if proposed["startScreen"] and not re.fullmatch(r"[A-Za-z0-9_]+", proposed["startScreen"]):
        return "Invalid starting screen"
    return ""


def verified_item_id(invoice: dict, reservation: dict | None = None,
                     attempt: dict | None = None) -> str:
    """Attribute paid processes from immutable invoice or verified service lineage."""
    if isinstance(invoice.get("fixedPresetId"), str) and invoice["fixedPresetId"] in ITEM_IDS:
        return invoice["fixedPresetId"]
    reservation, attempt = reservation or {}, attempt or {}
    payment_id = invoice.get("paymentId") or invoice.get("providerPaymentId")
    ref = invoice.get("referenceId")
    if (not ref or reservation.get("referenceId") != ref
            or reservation.get("paymentAttemptId") != attempt.get("paymentAttemptId")
            or attempt.get("referenceId") != ref or attempt.get("status") != "PAYMENT_PAID"
            or not payment_id or attempt.get("verifiedProviderPaymentId") != payment_id
            or (attempt.get("invoiceId") and attempt["invoiceId"] != invoice.get("invoiceId"))
            or attempt.get("currency", "INR") != invoice.get("currency", "INR")):
        return ""
    try:
        total = Decimal(str(invoice.get("total"))) * 100
        captured = Decimal(str(attempt.get("verifiedCapturedPaise")))
        if not total.is_finite() or total != total.to_integral_value() or total != captured or total <= 0:
            return ""
    except (ValueError, TypeError, InvalidOperation):
        return ""
    if attempt.get("staffContribute") is True:
        return "fixed-23"
    kind = str(attempt.get("serviceKind") or "")
    if kind == "VAULT" and not attempt.get("vaultFileId"):
        return ""
    service_item = {"SUBMIT_REQUEST": "fixed-24", "REQUEST_AMENDMENT": "fixed-25",
                    "DROP_DOCS": "fixed-26", "VAULT": "fixed-27", "REQUEST_PICKUP": "fixed-29"}.get(kind, "")
    if service_item:
        return service_item
    from lambda_utils.ecommerce.item_process_products import ITEM_BY_PRODUCT_ID
    snapshot = attempt.get("purchasedSnapshot") or {}
    lines = snapshot.get("items") if isinstance(snapshot, dict) else None
    if not isinstance(lines, list) or len(lines) != 1 or not isinstance(lines[0], dict):
        return ""
    product_id = str(lines[0].get("productId") or "")
    item_id = ITEM_BY_PRODUCT_ID.get(product_id, "")
    # A Vault product name/price/reference alone cannot prove an exact paid file.
    if item_id == "fixed-27" and not attempt.get("vaultFileId"):
        return ""
    return item_id


def verified_item_ids(invoice: dict, reservation: dict | None = None,
                      attempt: dict | None = None) -> list[str]:
    single = verified_item_id(invoice, reservation, attempt)
    if single:
        return [single]
    attempt = attempt or {}
    snapshot = attempt.get("purchasedSnapshot") or {}
    lines = snapshot.get("items") if isinstance(snapshot, dict) else None
    if not isinstance(lines, list) or not 1 < len(lines) <= 100:
        return []
    ids = []
    for line in lines:
        if not isinstance(line, dict):
            return []
        item_id = verified_item_id(invoice, reservation, {**attempt, "purchasedSnapshot": {**snapshot, "items": [line]}})
        if not item_id:
            return []
        if item_id not in ids:
            ids.append(item_id)
    return ids


def record_captured(invoice_table: Any, invoice_id: str, payment_id: str, *,
                    reservation: dict | None = None, attempt: dict | None = None) -> str:
    """Prepare one process checkpoint after a real capture/receipt. Never sends.

    Retrying a webhook cannot reset or duplicate the checkpoint. Flow dispatch is
    deliberately unavailable until the owner supplies the item-specific Flows.
    """
    invoice = invoice_table.get_item(Key={"invoiceId": invoice_id}, ConsistentRead=True).get("Item") or {}
    if (invoice.get("paymentStatus") not in ("captured", "paid")
            or str(invoice.get("paymentId") or invoice.get("providerPaymentId") or "") != payment_id):
        return "PAYMENT_NOT_VERIFIED"
    item_ids = verified_item_ids(invoice, reservation, attempt)
    if not item_ids:
        return "ITEM_NOT_ATTRIBUTED"
    if invoice.get("itemProcessCapturedPaymentId"):
        return "ALREADY_RECORDED"
    item_id = item_ids[0] if len(item_ids) == 1 else "MULTI_ITEM"
    invoice_table.update_item(
        Key={"invoiceId": invoice_id},
        UpdateExpression="SET itemProcessId = :process, itemProcessItemId = :item, "
                         "postPaymentProcessState = :state, itemProcessCapturedPaymentId = :payment, "
                         "itemProcessIds = :processes, itemProcessStates = :states",
        ConditionExpression="attribute_not_exists(itemProcessCapturedPaymentId) AND "
                            "(paymentStatus = :captured OR paymentStatus = :paid) AND "
                            "(paymentId = :payment OR providerPaymentId = :payment)",
        ExpressionAttributeValues={":process": "payment-item-" + item_id, ":item": item_id,
                                   ":state": "AWAITING_FLOW_SETUP", ":payment": payment_id,
                                   ":captured": "captured", ":paid": "paid",
                                   ":processes": ["payment-item-" + value for value in item_ids],
                                   ":states": {value: "AWAITING_FLOW_SETUP" for value in item_ids}},
    )
    return "AWAITING_FLOW_SETUP"
