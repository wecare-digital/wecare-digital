"""Single-order request-service contracts.

This registry describes the customer contract shared by the website, checkout and WhatsApp
handoff. It deliberately contains stable identifiers and policy switches only; ProductsTable
remains the price authority and canonical_flows remains the Meta Flow-id authority.

Customer invariant:
    authenticated customer + existing Order Number + serviceCode
      -> one payment -> one invoice -> exactly one service fulfilment

Flow-backed services launch one matching Meta Flow. Vault is deliberately different: it has no
Meta Flow and fulfils through the secure-file entitlement/download rail. Request-service products
remain ProductsTable price authorities but are never customer-visible Meta catalogue items.

No contract below creates a second customer-facing order number or a public WD-REQ identifier.
Technical payment/invoice/flow identifiers remain internal implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

NATIVE_PAY_TEMPLATE = "wecare_whatapp_native_pay_template"
INVOICE_TEMPLATE = "wecare_default_invoice_image_template"
ORDER_DETAILS_THUMBNAIL_KEY = (
    "secure/d/public/whatsapp/wa-tpl/"
    "WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png"
)


@dataclass(frozen=True)
class RequestServiceContract:
    service_code: str
    label: str
    product_id: str
    sku: str
    flow_capability: str
    fulfillment_kind: str = "flow"
    requires_existing_order: bool = True
    one_payment_one_fulfillment: bool = True
    catalog_visible: bool = False
    supply_gst_bps: int = 0
    express_paise: int = 0
    pay_template: str = NATIVE_PAY_TEMPLATE
    invoice_template: str = INVOICE_TEMPLATE
    order_details_thumbnail_key: str = ORDER_DETAILS_THUMBNAIL_KEY


_CONTRACTS = (
    RequestServiceContract(
        service_code="SUBMIT_REQUEST",
        label="Submit Request",
        product_id="f829697a-b1db-5c4e-bfce-51d1487278a7",
        sku="RSR7M2P9",
        flow_capability="submit_request",
    ),
    RequestServiceContract(
        service_code="REQUEST_AMENDMENT",
        label="Request Amendment",
        product_id="7133c98d-de8d-5e56-94ff-8d9fea7aa331",
        sku="RAM5Q8K4",
        flow_capability="amend_request",
    ),
    RequestServiceContract(
        service_code="DROP_DOCS",
        label="Drop Docs",
        product_id="e1ca7833-5d7d-567b-837c-face04647598",
        sku="RDD9P3M7",
        flow_capability="drop_docs",
        supply_gst_bps=1800,
        express_paise=2500,
    ),
    RequestServiceContract(
        service_code="VAULT",
        label="Vault",
        product_id="d4cfc6e8-10b3-5c47-94c8-3c69f4c03907",
        sku="RVT6K4Q8",
        flow_capability="",
        fulfillment_kind="secure_download",
        supply_gst_bps=1800,
        express_paise=2500,
    ),
    RequestServiceContract(
        service_code="REQUEST_PICKUP",
        label="Request Pickup",
        product_id="166370fe-69a8-5ad2-9f9a-e9ce3f92839c",
        sku="SHP7Q4N9",
        flow_capability="request_pickup",
    ),
)

REQUEST_SERVICE_CONTRACTS: Mapping[str, RequestServiceContract] = MappingProxyType(
    {contract.service_code: contract for contract in _CONTRACTS}
)
REQUEST_SERVICE_BY_SKU: Mapping[str, RequestServiceContract] = MappingProxyType(
    {contract.sku: contract for contract in _CONTRACTS}
)
REQUEST_SERVICE_PRODUCT_IDS = frozenset(
    str(contract.product_id).strip().lower() for contract in _CONTRACTS
)


def request_service_contract(service_code: object) -> Optional[RequestServiceContract]:
    return REQUEST_SERVICE_CONTRACTS.get(str(service_code or "").strip().upper())


def request_service_contract_for_sku(sku: object) -> Optional[RequestServiceContract]:
    return REQUEST_SERVICE_BY_SKU.get(str(sku or "").strip().upper())


def payment_binding(service_code: object, selected_order_number: object) -> dict:
    """Return the stable ids-only binding accepted by the new handoff.

    Ownership and eligibility are NOT proven here; the authenticated boundary must resolve the
    order number under the caller before using this binding to create a payment attempt.
    """
    contract = request_service_contract(service_code)
    order_number = str(selected_order_number or "").strip().upper()
    if contract is None:
        raise ValueError("UNKNOWN_SERVICE")
    if not order_number.startswith("WD-ORD-"):
        raise ValueError("INVALID_ORDER_NUMBER")
    return {
        "serviceCode": contract.service_code,
        "selectedOrderNumber": order_number,
        "sku": contract.sku,
        "flowCapability": contract.flow_capability,
        "fulfillmentKind": contract.fulfillment_kind,
        "payTemplate": contract.pay_template,
        "invoiceTemplate": contract.invoice_template,
    }


__all__ = [
    "INVOICE_TEMPLATE",
    "NATIVE_PAY_TEMPLATE",
    "ORDER_DETAILS_THUMBNAIL_KEY",
    "REQUEST_SERVICE_BY_SKU",
    "REQUEST_SERVICE_CONTRACTS",
    "REQUEST_SERVICE_PRODUCT_IDS",
    "RequestServiceContract",
    "payment_binding",
    "request_service_contract",
    "request_service_contract_for_sku",
]
