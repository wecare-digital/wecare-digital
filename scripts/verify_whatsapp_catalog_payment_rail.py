#!/usr/bin/env python3
# CI contract: .github/workflows/payment-rail-ci.yml runs this script for payment-rail PRs.
"""Hermetic end-to-end verification of the ONE WhatsApp payment rail.

    WhatsApp Catalog order -> wecare-inbound-whatsapp -> wecare-commerce `prepareNativeCart`
    -> ProductsTable pricing -> the India Address Message, opened on the saved address, which the
    customer sends back to confirm (or change) where THIS order ships -> `prepareNativeCart` again
    with `deliveryConfirmed` -> ONE PaymentAttempt + PAYREF# -> wecare-outbound-whatsapp
    -> `wecare_whatapp_native_pay_template` (button sub_type order_details, payment_gateway /
    Razorpay / WECAREDIGITAL) -> Razorpay `payment.captured` -> wecare-razorpay-webhook
    -> ONE order (internal fulfilment starts at processing) + ONE paid invoice
    -> ZERO structured WhatsApp order_status messages
    -> `wecare_default_invoice_image_template` (its FLOW button carries an order-bound review token).
    -> the order page (`/orders/?o=<orderNumber>`, checkout's `order` action): the delivery address
    frozen at checkout, the reviewed lines and the paid status, to the order's owner only.
    Section 9d covers the website prepare's own address gate. Section 13 runs one ₹49 Vault
    purchase the same way: the `wecare_valut_49` offer, the Unlock Vault tap, Review and Pay, the
    capture, the durable entitlement, the Access Vault link, the customer's Vault list and
    download, replays, a not-yet-linked WhatsApp contact, and a renewal.

WHAT RUNS FOR REAL
------------------
The production handlers, imported from the tree under test: the inbound worker (driven through
its real internal-event entry point), checkout and its packaged invoice engine, outbound, and
the Razorpay webhook; for the Vault, also business-api's catalog-service and paid-delivery flows,
secure-files and service-requests. Every DynamoDB and Cognito call is served by moto with real conditional-
expression semantics, so "exactly one attempt / order / invoice / send" is enforced by the same
conditional writes production uses. Lambda-to-Lambda invokes are routed in-process to those
handlers, and the Lambda client configuration each caller asks for is recorded.

WHAT IS FAKED, AND ONLY AT PROVIDER SEAMS
-----------------------------------------
* Meta message send (`outbound._send_direct_api`) and media upload: payloads are captured.
* Meta payment-configuration and template reads (the business-API Lambda): replayed from the
  live readback shape measured on 2026-10-25 (WECAREDIGITAL / Razorpay / acc_TTFSyolquKEZEy;
  `wecare_whatapp_native_pay_template` APPROVED UTILITY ORDER_DETAILS en).
* Meta payment lookup (`meta_payment_binding`'s HTTP call) and the Razorpay payment readback
  (`razorpay_verify._get`).
* Invoice PNG rendering (`invoice_engine.generate_invoice_image`).
Any other network use fails the run: sockets are disabled and `urllib.request.urlopen` refuses.

RUN (pinned and ephemeral; nothing is added to the repository's dependency set)
------------------------------------------------------------------------------
    uv run --no-project --python 3.12 --with boto3==1.43.116 \\
        --with "moto[dynamodb,cognitoidp]==5.2.4" \\
        python scripts/verify_whatsapp_catalog_payment_rail.py [--root <exported tree>]

`--root` points the run at another checkout of the repository, e.g. the exact export that is
about to be deployed. Exit 0 when every check passes, 1 when any fails, 2 when the toolchain is
missing. Creates no AWS resource, sends no message and charges nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import io
import json
import os
import re
import secrets
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── hermetic AWS environment, fixed BEFORE boto3 is imported ─────────────────────────────────
for _var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
    os.environ.pop(_var, None)
os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull, "AWS_CONFIG_FILE": os.devnull,
    "AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-east-1",
    "AWS_EC2_METADATA_DISABLED": "true",
})

WABA1 = "2094615664435155"
WABA2 = "2513394156072604"
META_PHONE_1 = "1016149501586345"
PHONE_ID_1 = "phone-number-id-waba1-direct-1016149501586345"
PHONE_ID_2 = "phone-number-id-waba-t-direct-1055232054343117"
PAY_TEMPLATE = "wecare_whatapp_native_pay_template"
INVOICE_TEMPLATE = "wecare_default_invoice_image_template"
ORDER_STATUS_TEMPLATE = "wecare_order_status_v3"
CONFIG_NAME = "WECAREDIGITAL"
PROVIDER_MID = "acc_TTFSyolquKEZEy"
CATALOG_ID = "1457045652952851"

# The live alias environment for the rail, as read on 2026-10-25 (non-secret values only).
os.environ.update({
    "WA_CATALOG_ORDERS_ENABLED": "true",
    "EXPECTED_CONFIGURATION_NAME": CONFIG_NAME,
    "EXPECTED_PROVIDER_MID": PROVIDER_MID,
    "CHECKOUT_MODE": "AWS_NATIVE",
    "PAYMENT_WABA_ID": WABA1,
    "WA_PAY_TEMPLATE": PAY_TEMPLATE,
    "WA_INVOICE_TEMPLATE": INVOICE_TEMPLATE,
    "WHATSAPP_PHONE_NUMBER_ID_1": PHONE_ID_1,
    "WHATSAPP_PHONE_NUMBER_ID_2": PHONE_ID_2,
    "STANDBY_REPLY_ENABLED": "false",
    "SEND_MODE": "LIVE",
})
for _var in ("WHATSAPP_CATALOG_SERVICES_ENABLED", "WA_LIVE_SMOKE_TEST", "DIRECT_SEND_ENABLED_WABAS"):
    os.environ.pop(_var, None)

try:
    import boto3
    from botocore.exceptions import ClientError, ReadTimeoutError
    from moto import mock_aws
except ImportError as _missing:  # pragma: no cover - toolchain message only
    print(f"missing toolchain ({_missing}); run with:\n  uv run --no-project --python 3.12 "
          "--with boto3==1.43.116 --with \"moto[dynamodb,cognitoidp]==5.2.4\" "
          "python scripts/verify_whatsapp_catalog_payment_rail.py", file=sys.stderr)
    sys.exit(2)

# ── no network: moto serves AWS in-process, everything else must not leave the machine ────────
def _no_socket(self, address):  # noqa: ARG001
    raise RuntimeError(f"network disabled in hermetic verification: {address!r}")


socket.socket.connect = _no_socket  # type: ignore[assignment]

# Table key schemas and GSIs, copied from the live account's DescribeTable (metadata only).
TABLES: Dict[str, Any] = {
    'ContactsTable': ([('id', 'S', 'HASH')], {'bsuid-index': [('bsuid', 'S', 'HASH')], 'email-index': [('email', 'S', 'HASH')], 'phone-index': [('phone', 'S', 'HASH')]}),
    'IdentityClaimsTable': ([('claimKey', 'S', 'HASH')], {}),
    'WebhookDedup': ([('eventId', 'S', 'HASH')], {}),
    'WhatsAppInboundTable': ([('id', 'S', 'HASH')], {'whatsappMessageId-index': [('whatsappMessageId', 'S', 'HASH')], 'senderPhone-status-index': [('senderPhone', 'S', 'HASH'), ('status', 'S', 'RANGE')]}),
    'MessagesTable': ([('id', 'S', 'HASH')], {'whatsappMessageId-index': [('whatsappMessageId', 'S', 'HASH')], 'paymentReferenceId-index': [('paymentReferenceId', 'S', 'HASH')], 'channel-index': [('channel', 'S', 'HASH'), ('timestamp', 'N', 'RANGE')], 'contactId-index': [('contactId', 'S', 'HASH'), ('timestamp', 'N', 'RANGE')], 'partnerWabaId-index': [('partnerWabaId', 'S', 'HASH')]}),
    'WhatsAppOutboundTable': ([('id', 'S', 'HASH')], {'whatsappMessageId-index': [('whatsappMessageId', 'S', 'HASH')], 'paymentReferenceId-index': [('paymentReferenceId', 'S', 'HASH')]}),
    'SystemConfigTable': ([('id', 'S', 'HASH')], {}),
    'ThreadOwnershipTable': ([('threadKey', 'S', 'HASH'), ('recordType', 'S', 'RANGE')], {}),
    'CommerceKeys': ([('orderId', 'S', 'HASH')], {}),
    'PaymentAttemptsTable': ([('paymentAttemptId', 'S', 'HASH')], {'status-index': [('status', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')], 'referenceId-index': [('referenceId', 'S', 'HASH')], 'customerId-index': [('customerId', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')]}),
    'OrderTable': ([('orderId', 'S', 'HASH')], {'shortId': [('shortId', 'S', 'HASH')], 'customerPhone': [('customerPhone', 'S', 'HASH')], 'customerId-createdAt-v2-index': [('customerId', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')], 'orderStatus': [('orderStatus', 'S', 'HASH')], 'source': [('source', 'S', 'HASH')], 'customerId-createdAt-index': [('customerId', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')]}),
    'ProductsTable': ([('id', 'S', 'HASH')], {'slug-updatedAt-index': [('slug', 'S', 'HASH'), ('updatedAt', 'S', 'RANGE')], 'category-updatedAt-index': [('category', 'S', 'HASH'), ('updatedAt', 'S', 'RANGE')], 'status-updatedAt-index': [('status', 'S', 'HASH'), ('updatedAt', 'S', 'RANGE')]}),
    'PaymentsTable': ([('id', 'S', 'HASH')], {'orderId-index': [('orderId', 'S', 'HASH')], 'paymentId-index': [('paymentId', 'S', 'HASH')]}),
    'InvoicesTable': ([('invoiceId', 'S', 'HASH')], {
        'referenceId-index': [('referenceId', 'S', 'HASH')],
        'contactId-index': [('contactId', 'S', 'HASH')],
        'orderStatusRetry-index': [('orderStatusRetry', 'S', 'HASH'), ('pendingOrderStatusAt', 'N', 'RANGE')],
    }),
    'InvoiceItemsTable': ([('invoiceId', 'S', 'HASH'), ('itemIndex', 'N', 'RANGE')], {}),
    'InvoiceAssetsTable': ([('invoiceId', 'S', 'HASH'), ('assetType', 'S', 'RANGE')], {}),
    'InvoiceSequenceTable': ([('fy', 'S', 'HASH')], {}),
    'InvoiceDeliveryLogTable': ([('invoiceId', 'S', 'HASH'), ('timestamp', 'N', 'RANGE')], {}),
    'RazorpayWebhookLogTable': ([('id', 'S', 'HASH')], {'paymentId-index': [('paymentId', 'S', 'HASH')], 'eventType-index': [('eventType', 'S', 'HASH')]}),
    'RateLimitTable': ([('id', 'S', 'HASH')], {}),
    'MediaFilesTable': ([('id', 'S', 'HASH')], {}),
    'AuditLogsTable': ([('id', 'S', 'HASH')], {}),
    'FlowSubmissionTable': ([('submissionId', 'S', 'HASH')], {'submissionNumber': [('submissionNumber', 'S', 'HASH')], 'flowCode': [('flowCode', 'S', 'HASH')], 'orderId': [('orderId', 'S', 'HASH')], 'phone': [('phone', 'S', 'HASH')], 'paymentRefId': [('paymentRefId', 'S', 'HASH')], 'flowId': [('flowId', 'S', 'HASH')], 'paymentStatus': [('paymentStatus', 'S', 'HASH')], 'status': [('status', 'S', 'HASH')]}),
    'ServiceRequestsTable': ([('requestId', 'S', 'HASH')], {'orderId-index': [('orderId', 'S', 'HASH')], 'customerId-createdAt-index': [('customerId', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')]}),
    'DocumentTable': ([('documentId', 'S', 'HASH')], {'customerPhone': [('customerPhone', 'S', 'HASH')], 'orderId': [('orderId', 'S', 'HASH')], 'sourceType': [('sourceType', 'S', 'HASH')], 'verificationStatus': [('verificationStatus', 'S', 'HASH')]}),
    'CartTable': ([('cartId', 'S', 'HASH')], {'customerId-updatedAt-index': [('customerId', 'S', 'HASH'), ('updatedAt', 'S', 'RANGE')]}),
    'SystemEventTable': ([('id', 'S', 'HASH')], {'wabaId-index': [('wabaId', 'S', 'HASH')], 'eventType-index': [('eventType', 'S', 'HASH')]}),
    'AIInteractionsTable': ([('id', 'S', 'HASH')], {}),
    'ConversationMetaTable': ([('conversationId', 'S', 'HASH')], {}),
    'AutomationRulesTable': ([('id', 'S', 'HASH')], {}),
    'WhatsAppPhonesTable': ([('displayPhoneNumber', 'S', 'HASH')], {}),
    'TemplateAnalyticsTable': ([('id', 'S', 'HASH')], {'templateName-index': [('templateName', 'S', 'HASH')]}),
    'AdClickAttributionTable': ([('id', 'S', 'HASH')], {'adId-index': [('adId', 'S', 'HASH')], 'contactId-index': [('contactId', 'S', 'HASH')]}),
    'CustomerSessionsTable': ([('sidHash', 'S', 'HASH')], {}),
    'RequestStatusHistoryTable': ([('historyId', 'S', 'HASH')], {'submissionId': [('submissionId', 'S', 'HASH')], 'orderId': [('orderId', 'S', 'HASH')]}),
    'CouponsTable': ([('couponKey', 'S', 'HASH')], {'status-index': [('status', 'S', 'HASH'), ('createdAt', 'N', 'RANGE')]}),
    'SecureFilesTable': ([('fileId', 'S', 'HASH')], {'owner-created-index': [('ownerPhone', 'S', 'HASH'), ('createdAt', 'S', 'RANGE')]}),
    'DownloadGrantsTable': ([('grantId', 'S', 'HASH')], {'order-index': [('orderId', 'S', 'HASH')]}),
}
PREFIX = "stack-wecare-digital-"

# The live Meta readback (2026-10-25), replayed for the business-API reads.
LIVE_PAYMENT_CONFIGURATIONS = [
    {"configuration_name": "WECAREUPI", "status": "Active", "provider_name": None,
     "provider_mid": None},
    {"configuration_name": CONFIG_NAME, "status": "Active", "provider_name": "Razorpay",
     "provider_mid": PROVIDER_MID},
]
LIVE_TEMPLATES = [
    {"name": "wecare_otp", "status": "APPROVED", "category": "AUTHENTICATION", "sub_category": None, "language": "en"},
    {"name": "wecare_default_download", "status": "APPROVED", "category": "UTILITY", "sub_category": "CUSTOM", "language": "en"},
    {"name": INVOICE_TEMPLATE, "status": "APPROVED", "category": "UTILITY", "sub_category": "CUSTOM", "language": "en"},
    {"name": "wecare_location_share_pin", "status": "APPROVED", "category": "UTILITY", "sub_category": "CUSTOM", "language": "en"},
    {"name": "feedback_survey_form_1", "status": "APPROVED", "category": "UTILITY", "sub_category": "FORM", "language": "en_US"},
    {"name": "wecare_leave_review", "status": "APPROVED", "category": "UTILITY", "sub_category": "FORM", "language": "en"},
    {"name": PAY_TEMPLATE, "status": "APPROVED", "category": "UTILITY", "sub_category": "ORDER_DETAILS", "language": "en", "id": "2714938845570815"},
    {"name": ORDER_STATUS_TEMPLATE, "status": "APPROVED", "category": "UTILITY", "sub_category": "ORDER_STATUS", "language": "en", "id": "1754227779211208"},
]

# ── result collection ─────────────────────────────────────────────────────────────────────────
RESULTS: List[Dict[str, Any]] = []


def check(req: str, name: str, ok: Any, evidence: Any = "") -> bool:
    passed = bool(ok)
    RESULTS.append({"req": req, "name": name, "pass": passed, "evidence": str(evidence)[:400]})
    print(f"  [{'PASS' if passed else 'FAIL'}] {req:<4} {name}" + (f"  :: {evidence}" if evidence != "" else ""))
    return passed


# ── fakes ─────────────────────────────────────────────────────────────────────────────────────
class FakeContext:
    def __init__(self, name: str):
        self.function_name = name
        self.aws_request_id = str(uuid.uuid4())
        self.invoked_function_arn = f"arn:aws:lambda:us-east-1:000000000000:function:{name}:live"

    @staticmethod
    def get_remaining_time_in_millis() -> int:
        return 110_000


class World:
    """Every observable side effect, so each scenario can be measured as a delta."""

    def __init__(self) -> None:
        self.invocations: List[Dict[str, Any]] = []
        self.meta_sends: List[Dict[str, Any]] = []
        self.meta_lookups: List[Dict[str, str]] = []
        self.rzp_reads: List[str] = []
        self.unexpected_http: List[str] = []
        self.lambda_configs: List[Any] = []
        self.faults: Dict[str, List[str]] = {}
        self.meta_payments: Dict[str, Dict[str, str]] = {}
        self.rzp_payments: Dict[str, Dict[str, Any]] = {}
        self.payment_configurations = list(LIVE_PAYMENT_CONFIGURATIONS)
        self.templates = list(LIVE_TEMPLATES)
        self.handlers: Dict[str, Callable] = {}

    def mark(self) -> Dict[str, int]:
        return {"invocations": len(self.invocations), "meta_sends": len(self.meta_sends),
                "meta_lookups": len(self.meta_lookups)}

    def since(self, mark: Dict[str, int], key: str) -> List[Dict[str, Any]]:
        return getattr(self, key)[mark[key]:]


W = World()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fake_urlopen(request, *args, **kwargs):  # noqa: ARG001
    url = request.full_url if hasattr(request, "full_url") else str(request)
    match = re.match(r"https://graph\.facebook\.com/v[\d.]+/(\d+)/payments/([^/]+)/([^/?]+)", url)
    if match:
        phone, config, reference = match.groups()
        W.meta_lookups.append({"phone": phone, "config": config, "reference": reference})
        bound = W.meta_payments.get(reference)
        if not bound:
            return _Resp(json.dumps({"payments": []}).encode())
        return _Resp(json.dumps({"payments": [{
            "reference_id": reference, "status": "captured",
            "transactions": [{"id": bound["order_id"], "pg_transaction_id": bound["payment_id"],
                              "status": "success", "type": "razorpay"}]}]}).encode())
    W.unexpected_http.append(url.split("?")[0])
    raise urllib.error.URLError("network disabled in hermetic verification")


urllib.request.urlopen = _fake_urlopen  # type: ignore[assignment]


def _api(status: int, body: Any) -> Dict[str, Any]:
    return {"statusCode": status, "body": json.dumps(body, default=str)}


def _business_api(event: Dict[str, Any], context: Any) -> Dict[str, Any]:  # noqa: ARG001
    path = str(event.get("path") or event.get("rawPath") or "")
    if "/wa-business/payment-config/list" in path:
        return _api(200, {"data": W.payment_configurations})
    if "/wa-business/payment-templates/list" in path:
        return _api(200, {"data": W.templates})
    return _api(200, {"ok": True, "recordedOnly": True})


class FakeLambda:
    """A Lambda client whose invoke runs the target handler in-process."""

    def __init__(self, config: Any = None):
        self.config = config

    def invoke(self, FunctionName: str, InvocationType: str = "RequestResponse",
               Payload: Any = b"{}", **_: Any) -> Dict[str, Any]:
        name = str(FunctionName).split(":function:")[-1].split(":")[0]
        raw = Payload.decode() if isinstance(Payload, (bytes, bytearray)) else str(Payload)
        event = json.loads(raw or "{}")
        W.invocations.append({"function": name, "qualifier": str(FunctionName), "type": InvocationType,
                              "event": event, "config": self.config})
        queue = W.faults.get(name) or []
        fault = queue.pop(0) if queue else None
        if fault == "refused_before_run":
            raise ClientError({"Error": {"Code": "TooManyRequestsException",
                                         "Message": "Rate exceeded"}}, "Invoke")
        target = W.handlers.get(name, _business_api if name == "wecare-whatsapp-business-api"
                                else None)
        error = None
        if target is None:
            result: Any = {"ok": True, "recordedOnly": True}
        else:
            try:
                result = target(event, FakeContext(name))
            except Exception as exc:  # noqa: BLE001 - emulate Lambda's FunctionError envelope
                error = "Unhandled"
                result = {"errorMessage": f"{type(exc).__name__}: {exc}",
                          "errorType": type(exc).__name__}
                W.unexpected_http.append(f"UNHANDLED in {name}: {type(exc).__name__}: {exc}")
        if fault == "timeout_after_run":
            raise ReadTimeoutError(endpoint_url="https://lambda.us-east-1.amazonaws.com")
        if InvocationType == "Event":
            return {"StatusCode": 202, "Payload": io.BytesIO(b"")}
        response = {"StatusCode": 200, "ExecutedVersion": "live",
                    "Payload": io.BytesIO(json.dumps(result, default=str).encode())}
        if error:
            response["FunctionError"] = error
        return response


_real_boto3_client = boto3.client


def _client(service_name, *args, **kwargs):
    if service_name == "lambda":
        W.lambda_configs.append(kwargs.get("config"))
        return FakeLambda(kwargs.get("config"))
    return _real_boto3_client(service_name, *args, **kwargs)


boto3.client = _client  # type: ignore[assignment]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ── data helpers ──────────────────────────────────────────────────────────────────────────────
def _table(short: str):
    return boto3.resource("dynamodb", region_name="us-east-1").Table(PREFIX + short)


def _scan(short: str) -> List[Dict[str, Any]]:
    table, rows, kwargs = _table(short), [], {}
    while True:
        page = table.scan(**kwargs)
        rows += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _create_tables() -> None:
    ddb = _real_boto3_client("dynamodb", region_name="us-east-1")
    for short, (keys, gsis) in TABLES.items():
        attrs = {a: t for a, t, _ in keys}
        for parts in gsis.values():
            attrs.update({a: t for a, t, _ in parts})
        kwargs: Dict[str, Any] = {
            "TableName": PREFIX + short, "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": a, "KeyType": k} for a, _, k in keys],
            "AttributeDefinitions": [{"AttributeName": a, "AttributeType": t}
                                     for a, t in attrs.items()],
        }
        if gsis:
            kwargs["GlobalSecondaryIndexes"] = [
                {"IndexName": n, "Projection": {"ProjectionType": "ALL"},
                 "KeySchema": [{"AttributeName": a, "KeyType": k} for a, _, k in parts]}
                for n, parts in gsis.items()]
        ddb.create_table(**kwargs)


class Shop:
    """Products, customers and Meta order messages for the scenarios."""

    def __init__(self, pool_id: str, mcs, contact_key):
        self.pool_id, self.mcs, self.contact_key = pool_id, mcs, contact_key
        self.cognito = _real_boto3_client("cognito-idp", region_name="us-east-1")
        self.tee = str(uuid.uuid5(uuid.NAMESPACE_URL, "hermetic/tee"))
        self.kit = "native:hermetic-kit"
        self.retired = str(uuid.uuid5(uuid.NAMESPACE_URL, "hermetic/retired"))
        now = str(int(time.time()))
        for pid, title, status, variants in (
                (self.tee, "Hermetic Tee", "active", [{"id": "TEE-M", "sku": "TEE-M", "label": "M", "priceMinor": 59900}]),
                (self.kit, "Hermetic Kit", "active", [{"id": "KIT1", "sku": "KIT1", "label": "Kit", "priceMinor": 9900}]),
                (self.retired, "Retired Item", "archived", [{"id": "OLD", "sku": "OLD", "label": "Old", "priceMinor": 1000}])):
            _table("ProductsTable").put_item(Item={
                "id": pid, "title": title, "name": title, "status": status, "currency": "INR",
                "slug": pid.replace(":", "-"), "updatedAt": now, "createdAt": now,
                "metaEnabled": True, "websiteEnabled": True,
                "variants": [dict(v, inventory=0, trackInventory=False, inventoryVerified=False)
                             for v in variants]})

    def rid(self, product: str, variant: str) -> str:
        return self.mcs.retailer_id(product, variant)

    def customer(self, n: int, *, verified: bool = True, email: bool = True,
                 address: bool = True, legacy_shipping: bool = True,
                 phone: Optional[str] = None) -> Dict[str, str]:
        phone = phone or f"+9198765{n:05d}"
        sub = ""
        if verified:
            user = self.cognito.admin_create_user(
                UserPoolId=self.pool_id, Username=phone, MessageAction="SUPPRESS",
                UserAttributes=[{"Name": "phone_number", "Value": phone},
                                {"Name": "phone_number_verified", "Value": "true"}])["User"]
            sub = next(a["Value"] for a in user["Attributes"] if a["Name"] == "sub")
        contact_id = "wa" + phone[1:]
        now = int(time.time())
        row: Dict[str, Any] = {**self.contact_key.contact_item_keys(contact_id),
                               "phone": phone, "name": f"Buyer {n}", "firstName": "Buyer",
                               "lastName": str(n), "customerUuid": str(uuid.uuid4()),
                               "optInWhatsApp": True, "allowlistWhatsApp": True,
                               "lastInboundMessageAt": Decimal(now),
                               "createdAt": Decimal(now), "updatedAt": Decimal(now)}
        if sub:
            row["checkoutCustomerId"] = sub
        if email:
            row["email"] = f"buyer{n}@example.com"
        if address:
            row["checkoutDeliveryAddress"] = {"addressLine1": "12 Hermetic Street",
                                              "city": "Kolkata", "state": "West Bengal",
                                              "postalCode": "700001", "countryCode": "IN"}
            row["checkoutAddressUpdatedAt"] = Decimal(now)
        if legacy_shipping:
            row["shippingAddress"] = "12 Hermetic Street, Kolkata 700001"
        _table("ContactsTable").put_item(Item=row)
        return {"phone": phone, "digits": phone[1:], "contactId": contact_id, "sub": sub}


def order_event(wa_event_builder, digits: str, wamid: Optional[str], items: List[Dict[str, Any]],
                *, meta_phone: str = META_PHONE_1, display: str = "919330994400") -> Dict[str, Any]:
    message: Dict[str, Any] = {"from": digits, "timestamp": str(int(time.time())), "type": "order",
                               "order": {"catalog_id": CATALOG_ID, "text": "", "product_items": items}}
    if wamid:
        message["id"] = wamid
    entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": display, "phone_number_id": meta_phone},
        "contacts": [{"wa_id": digits, "profile": {"name": "Hermetic Buyer"}}],
        "messages": [message]}}]}
    return wa_event_builder(entry=entry, waba_id=WABA1, meta_phone_number_ids=[meta_phone],
                            request_id=str(uuid.uuid4()))


def _payrefs_for(customer_id: str) -> List[Dict[str, Any]]:
    return [r for r in _scan("CommerceKeys")
            if str(r.get("orderId", "")).startswith("PAYREF#") and r.get("customerId") == customer_id]


def _attempts_for(customer_id: str) -> List[Dict[str, Any]]:
    return [r for r in _scan("PaymentAttemptsTable") if r.get("customerId") == customer_id]


def _pay_sends(sends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sends if (s["payload"].get("template") or {}).get("name") == PAY_TEMPLATE]


#: The two function names that run the one checkout + invoice-engine package.
COMMERCE_FUNCTIONS = ("wecare-checkout", "wecare-commerce")


def _checkout_invokes(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in calls if c["function"] in COMMERCE_FUNCTIONS
            and c["event"].get("internalAction") == "prepareNativeCart"]


def _order_status_traffic(calls, sends) -> List[str]:
    found = []
    for call in calls:
        body = call["event"].get("body")
        body = json.loads(body) if isinstance(body, str) else (body or {})
        if isinstance(body, dict) and (body.get("orderStatusDetails") or body.get("isOrderStatus")):
            found.append(f"invoke:{call['function']}")
    for send in sends:
        payload = send["payload"]
        if (payload.get("template") or {}).get("name") == ORDER_STATUS_TEMPLATE:
            found.append("meta:order_status_template")
        if (payload.get("interactive") or {}).get("type") == "order_status":
            found.append("meta:interactive_order_status")
    return found


def _outbound_body(call: Dict[str, Any]) -> Dict[str, Any]:
    body = call["event"].get("body")
    return json.loads(body) if isinstance(body, str) else (body or {})


# ── the run ───────────────────────────────────────────────────────────────────────────────────
def run(root: Path) -> int:
    functions = root / "amplify" / "functions"
    sys.path[:0] = [str(functions / "shared"),
                    str(functions / "messaging" / "inbound-whatsapp-handler"),
                    str(functions / "ecommerce" / "checkout"),
                    str(functions / "payments" / "invoice-engine")]

    cognito = _real_boto3_client("cognito-idp", region_name="us-east-1")
    pool_id = cognito.create_user_pool(
        PoolName="hermetic-customers",
        Schema=[{
            "Name": "partner_waba_id",
            "AttributeDataType": "String",
            "Mutable": True,
            "Required": False,
            "StringAttributeConstraints": {"MinLength": "1", "MaxLength": "64"},
        }],
    )["UserPool"]["Id"]
    os.environ["CUSTOMER_POOL_ID"] = pool_id
    _create_tables()

    from lambda_utils import contact_key, template_media, wa_internal_event  # noqa: E402
    from lambda_utils.ecommerce import checkout_pricing, default_coupon, meta_catalog_sync as mcs
    from lambda_utils.ecommerce import whatsapp_basket
    from lambda_utils.integrations import meta_payment_binding, razorpay_verify
    from lambda_utils.ecommerce import finalization

    inbound = _load("h_inbound", functions / "messaging" / "inbound-whatsapp-handler" / "handler.py")
    checkout = _load("h_checkout", functions / "ecommerce" / "checkout" / "handler.py")
    registration = _load("h_customer_registration",
                         functions / "auth" / "customer-registration" / "handler.py")
    outbound = _load("h_outbound", functions / "messaging" / "outbound-whatsapp" / "handler.py")
    webhook = _load("h_webhook", functions / "payments" / "razorpay-webhook" / "handler.py")
    # The invoice engine ships inside wecare-checkout AS `invoice_engine.py`, sourced from its one
    # home payments/invoice-engine/handler.py (there is no copy beside the checkout handler any
    # more). Load that single source under the packaged module name so checkout's lazy
    # `import invoice_engine` resolves to it and the seam patched below is the one that runs.
    invoice_engine = _load("invoice_engine",
                           functions / "payments" / "invoice-engine" / "handler.py")

    check("HDR", "large payment header and small item image use separate approved assets",
          template_media.PAYMENT_TEMPLATE_HEADER.endswith(
              "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png")
          and template_media.ORDER_ITEM_IMAGE.endswith(
              "secure/d/public/whatsapp/wa-tpl/wecare-catalog-icon.png"),
          {"header": template_media.PAYMENT_TEMPLATE_HEADER,
           "item": template_media.ORDER_ITEM_IMAGE})

    # wecare-commerce and wecare-checkout are two functions running ONE package (the checkout
    # handler + its packaged invoice engine). Production callers address them by name: inbound's
    # cart leg and the webhook's post-capture work go to wecare-commerce, the catalog-service leg
    # to wecare-checkout. Both names route to the same handler here, exactly as deployed.
    W.handlers.update({name: checkout.handler for name in COMMERCE_FUNCTIONS})
    W.handlers.update({"wecare-outbound-whatsapp": outbound.handler,
                       "wecare-inbound-whatsapp": inbound.handler,
                       "wecare-customer-registration": registration.handler})
    # The function inbound's cart leg invokes, so faults land where production would see them.
    cart_function = str(inbound.CHECKOUT_FUNCTION).split(":")[0]

    # Provider seams.
    def fake_send_direct_api(phone_number_id: str, message_json: Any) -> Dict[str, str]:
        payload = json.loads(message_json) if isinstance(message_json, str) else message_json
        W.meta_sends.append({"phoneNumberId": phone_number_id, "payload": payload})
        return {"messageId": f"wamid.HERMETIC{len(W.meta_sends):04d}", "waId": str(payload.get("to", "")).lstrip("+")}

    outbound._send_direct_api = fake_send_direct_api
    outbound._send_typing_indicator = lambda *a, **k: None
    outbound._upload_media = lambda media_file, media_type, message_id, *a, **k: (
        media_file, f"MEDIA-{message_id[:8]}", "invoice.png")
    meta_payment_binding._default_load_token = lambda: {"access_token": "hermetic", "app_secret": ""}

    def fake_rzp_get(path: str) -> Dict[str, Any]:
        W.rzp_reads.append(path)
        match = re.match(r"^/payments/(pay_\w+)$", path)
        if match and match.group(1) in W.rzp_payments:
            return W.rzp_payments[match.group(1)]
        match = re.match(r"^/orders/(order_\w+)/payments$", path)
        if match:
            return {"items": [p for p in W.rzp_payments.values() if p["order_id"] == match.group(1)]}
        raise razorpay_verify.RazorpayUnavailable("unknown provider object")

    razorpay_verify._get = fake_rzp_get

    def fake_generate_invoice_image(invoice_id: str, request_id: str) -> Dict[str, Any]:  # noqa: ARG001
        key = f"secure/d/public/Invoice/customer_invoice/{invoice_id}.png"
        _table("InvoiceAssetsTable").put_item(Item={"invoiceId": invoice_id, "assetType": "image",
                                                    "s3Key": key, "createdAt": int(time.time())})
        return {"statusCode": 200, "body": json.dumps({"imageUrl": "", "s3Key": key})}

    invoice_engine.generate_invoice_image = fake_generate_invoice_image
    webhook_secret = secrets.token_hex(16)  # per-run test value; not a credential
    webhook._get_webhook_secret = lambda: webhook_secret

    shop = Shop(pool_id, mcs, contact_key)
    tee = shop.rid(shop.tee, "TEE-M")
    kit = shop.rid(shop.kit, "KIT1")
    build = wa_internal_event.build

    def deliver(event: Dict[str, Any]) -> Dict[str, Any]:
        return inbound.handler(event, FakeContext("wecare-inbound-whatsapp"))

    def address_forms(customer: Dict[str, str], since: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
        """The India Address Message forms Meta was asked to show this customer."""
        sends = W.since(since, "meta_sends") if since else W.meta_sends
        return [s["payload"] for s in sends if s["payload"].get("to") == customer["phone"]
                and (s["payload"].get("interactive") or {}).get("type") == "address_message"]

    def form_parameters(form: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return (((form or {}).get("interactive") or {}).get("action") or {}).get("parameters") or {}

    def address_reply(customer: Dict[str, str], wamid_in: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """The customer's Address Message submission, as Meta delivers it (nfm_reply)."""
        message = {"from": customer["digits"], "id": wamid_in, "timestamp": str(int(time.time())),
                   "type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
                       "name": "address_message", "body": "Sent",
                       "response_json": json.dumps({"values": values})}}}
        entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "919330994400", "phone_number_id": META_PHONE_1},
            "contacts": [{"wa_id": customer["digits"], "profile": {"name": "Hermetic Buyer"}}],
            "messages": [message]}}]}
        return build(entry=entry, waba_id=WABA1, meta_phone_number_ids=[META_PHONE_1],
                     request_id=str(uuid.uuid4()))

    def confirm_prefilled(customer: Dict[str, str], wamid_in: str) -> Dict[str, Any]:
        """The customer sends back the address form they were just shown, without changing it."""
        forms = address_forms(customer)
        return deliver(address_reply(customer, wamid_in,
                                     dict(form_parameters(forms[-1] if forms else None).get("values") or {})))

    # ── 1. parser and retailer-id contract (pure) ────────────────────────────────────────────
    print("\n== 1. retailer id contract and Meta order parsing")
    for pid, vid in ((shop.tee, "TEE-M"), (shop.kit, "KIT1"),
                     ("8d0c6a3e-1d4f-4e7a-9a52-0d8a3e2b7c11", "5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d")):
        rid = mcs.retailer_id(pid, vid)
        back = mcs.parse_retailer_id(rid)
        check("R-ID", f"retailer id round-trips {rid[:34]}...", back == (pid.lower() if rid.count(':') == 2 else pid,
                                                                    vid.lower() if rid.count(':') == 2 else vid), back)
    for foreign in ("SKU-123", "OTHERBRAND:v2:abc:def", "WECARE.DIGITAL:v2:bad!:x", "", None,
                    "WECARE.DIGITAL:v2:" + mcs._b64url_encode(shop.tee) + "=:" + mcs._b64url_encode("TEE-M")):
        check("R3", f"foreign/non-canonical retailer id refused: {str(foreign)[:30]!r}",
              mcs.parse_retailer_id(foreign) is None)
    basket = whatsapp_basket.parse_order_message({"id": "wamid.P1", "order": {"product_items": [
        {"product_retailer_id": tee, "quantity": 2, "item_price": 499, "currency": "USD"},
        {"product_retailer_id": "SOMEONE-ELSE-1", "quantity": 1, "item_price": 1, "currency": "INR"},
        {"product_retailer_id": tee, "quantity": 1, "item_price": 1, "currency": "USD"},
        {"product_retailer_id": kit, "quantity": 150, "item_price": 0, "currency": "INR"}]}})
    lines = {(l["productId"], l["variantId"]): l["quantity"] for l in basket.lines}
    check("R4", "duplicate retailer ids merge deterministically (2+1=3)", lines.get((shop.tee, "TEE-M")) == 3, basket.lines)
    check("R5", "quantity above the per-line ceiling is clamped to 100", lines.get((shop.kit, "KIT1")) == 100, basket.lines)
    check("R3", "foreign line dropped and counted, never guessed", basket.dropped == 1, f"dropped={basket.dropped}")
    check("R1", "parsed lines carry no price/currency (only productId/variantId/quantity)",
          all(set(l) == {"productId", "variantId", "quantity"} for l in basket.lines), basket.lines)
    reversed_basket = whatsapp_basket.parse_order_message({"id": "wamid.P2", "order": {"product_items": [
        {"product_retailer_id": tee, "quantity": 1}, {"product_retailer_id": tee, "quantity": 2}]}})
    check("R4", "merge is order-independent", reversed_basket.lines[0]["quantity"] == 3)
    summed = whatsapp_basket.parse_order_message({"id": "wamid.P3", "order": {"product_items": [
        {"product_retailer_id": kit, "quantity": 60}, {"product_retailer_id": kit, "quantity": 60}]}})
    check("R5", "duplicate lines summing past the ceiling are clamped after the merge",
          summed.lines[0]["quantity"] == 100 and summed.clamped == 1, summed.lines)
    check("R3", "an all-foreign cart parses to nothing payable",
          whatsapp_basket.parse_order_message({"order": {"product_items": [
              {"product_retailer_id": "SKU-1", "quantity": 1}]}}) is None)
    from lambda_utils.ecommerce import contact_address
    saved = contact_address.normalize_for_storage({
        "addressLine1": "12 Hermetic Street", "addressLine2": "Flat 3B", "locality": "Park Street",
        "city": "Kolkata", "state": "West Bengal", "postalCode": "700001", "countryCode": "IN"})
    prefill = contact_address.to_meta_address_values(saved)
    check("ADDR", "a saved address prefills Meta's form fields, and the form sent back unchanged stores it as it was",
          prefill == {"address": "12 Hermetic Street", "house_number": "Flat 3B",
                      "landmark_area": "Park Street", "city": "Kolkata", "state": "West Bengal",
                      "in_pin_code": "700001"}
          and contact_address.normalize_for_storage(contact_address.map_meta_address(prefill)) == saved,
          prefill)
    check("ADDR", "...a foreign address prefills nothing, and only +91 numbers are sent the form",
          contact_address.to_meta_address_values({**saved, "countryCode": "US"}) == {}
          and contact_address.address_message_reaches("+919876500001")
          and not contact_address.address_message_reaches("+14155550123"))

    # ── 2. happy path: catalog cart -> address confirmed -> ONE attempt -> the ONE approved template
    print("\n== 2. catalog cart -> delivery address confirmed for this order -> prepareNativeCart -> "
          "ONE attempt -> approved ORDER_DETAILS template")
    alice = shop.customer(1)
    mark = W.mark()
    wamid = "wamid.HERMETIC.ALICE.1"
    items = [{"product_retailer_id": tee, "quantity": 2, "item_price": 499, "currency": "USD"},
             {"product_retailer_id": tee, "quantity": 1, "item_price": 499, "currency": "USD"}]
    deliver(order_event(build, alice["digits"], wamid, items))
    calls = W.since(mark, "invocations")
    asked_after = [i for i, c in enumerate(calls) if c["function"] == "wecare-outbound-whatsapp"]
    priced_at = [i for i, c in enumerate(calls) if c["function"] in COMMERCE_FUNCTIONS
                 and c["event"].get("internalAction") == "prepareNativeCart"]
    forms = address_forms(alice, mark)
    form = forms[0] if forms else {}
    prefill = form_parameters(form).get("values") or {}
    check("ADDR", "a buyer with a saved address is asked to confirm it before any payment: one form, nothing reserved",
          len(forms) == 1 and len(asked_after) == 1 and not _pay_sends(W.since(mark, "meta_sends"))
          and not _attempts_for(alice["sub"]) and not _payrefs_for(alice["sub"]),
          {"forms": len(forms), "outbound": len(asked_after)})
    check("ADDR", "...only after checkout priced the cart and found payments ready",
          len(priced_at) == 1 and asked_after and priced_at[0] < asked_after[0], {"prepare": priced_at, "ask": asked_after})
    check("ADDR", "...the form opens on the saved address in Meta's fields, with nothing marked",
          prefill.get("address") == "12 Hermetic Street" and prefill.get("city") == "Kolkata"
          and prefill.get("state") == "West Bengal" and prefill.get("in_pin_code") == "700001"
          and prefill.get("name") == "Buyer 1" and not form_parameters(form).get("validation_errors"), prefill)
    check("ADDR", "...and says what to do: confirm it, change it if needed, then the payment request follows",
          "confirm the delivery address for this order"
          in str(((form.get("interactive") or {}).get("body") or {}).get("text") or "").lower(),
          ((form.get("interactive") or {}).get("body") or {}).get("text"))
    mark = W.mark()
    confirm_prefilled(alice, "wamid.HERMETIC.ALICE.ADDR1")
    calls = W.since(mark, "invocations")
    prepares = _checkout_invokes(calls)
    check("R10", "sending the form back resumed the cart: prepareNativeCart exactly once", len(prepares) == 1, len(prepares))
    if prepares:
        payload = prepares[0]["event"]
        check("R1", "prepareNativeCart payload carries no money/payment field",
              set(payload) <= {"internalAction", "lines", "sourceMessageId", "contactId", "senderPhone", "phoneNumberId",
                               "deliveryConfirmed", "deliveryRecipient"}
              and all(set(l) == {"productId", "variantId", "quantity"} for l in payload["lines"]), sorted(payload))
        check("ADDR", "...it says the address was confirmed for this cart, and who the parcel is for",
              payload.get("deliveryConfirmed") is True and payload.get("deliveryRecipient") == "Buyer 1"
              and payload.get("sourceMessageId") == wamid,
              {k: payload.get(k) for k in ("deliveryConfirmed", "deliveryRecipient", "sourceMessageId")})
        check("R10", "lines = exact ProductsTable identity + integer quantity",
              payload["lines"] == [{"productId": shop.tee, "variantId": "TEE-M", "quantity": 3}], payload["lines"])
        check("R16", "prepareNativeCart sent the WABA1 sender id", payload["phoneNumberId"] == PHONE_ID_1)
        cfg = prepares[0]["config"]
        check("IDEM", "inbound->checkout invoke has SDK retries disabled and a read timeout above checkout's 60 s",
              cfg is not None and (cfg.retries or {}).get("max_attempts") == 0 and cfg.read_timeout > 60,
              f"retries={getattr(cfg, 'retries', None)} read_timeout={getattr(cfg, 'read_timeout', None)}")
    payrefs, attempts = _payrefs_for(alice["sub"]), _attempts_for(alice["sub"])
    check("R10", "exactly ONE PAYREF# and ONE PaymentAttempt", len(payrefs) == 1 and len(attempts) == 1,
          f"payrefs={len(payrefs)} attempts={len(attempts)}")
    sends = W.since(mark, "meta_sends")
    pay = _pay_sends(sends)
    check("R12", "exactly ONE Meta send, and it is wecare_whatapp_native_pay_template",
          len(sends) == 1 and len(pay) == 1, [s["payload"].get("type") for s in sends])
    if payrefs and attempts and pay:
        ref, attempt, msg = payrefs[0], attempts[0], pay[0]["payload"]
        alice["reference"], alice["attempt"] = ref["referenceId"], attempt
        check("R2", "PAYREF# carries the Meta binding inputs (phoneId, configurationName, wabaId)",
              ref.get("phoneId") == PHONE_ID_1 and ref.get("configurationName") == CONFIG_NAME
              and ref.get("wabaId") == WABA1, {k: ref.get(k) for k in ("phoneId", "configurationName", "wabaId", "checkoutMode")})
        template = msg["template"]
        check("R12", "template language en, sent from WABA1",
              template["language"]["code"] == "en" and pay[0]["phoneNumberId"] == PHONE_ID_1)
        buttons = [c for c in template["components"] if c.get("type") == "button"]
        check("R12", "one button, sub_type order_details, index 0",
              len(buttons) == 1 and buttons[0]["sub_type"] == "order_details" and buttons[0]["index"] == 0)
        action = buttons[0]["parameters"][0]["action"]["order_details"]
        settings = action["payment_settings"]
        check("R12", "payment_settings = server-built payment_gateway / razorpay / WECAREDIGITAL",
              len(settings) == 1 and settings[0]["type"] == "payment_gateway"
              and settings[0]["payment_gateway"]["type"] == "razorpay"
              and settings[0]["payment_gateway"]["configuration_name"] == CONFIG_NAME, settings)
        check("R12", "Razorpay receipt/notes carry exactly the reserved reference",
              settings[0]["payment_gateway"]["razorpay"]["notes"]["referenceId"] == ref["referenceId"] == action["reference_id"])
        unit = action["order"]["items"][0]
        check("R1", "item priced from ProductsTable (59900 paise), not Meta item_price (499)",
              unit["amount"]["value"] == 59900 and unit["quantity"] == 3, unit)
        check("R2", "settlement currency INR despite inbound USD", action["currency"] == "INR" and attempt["currency"] == "INR")
        subtotal = 59900 * 3
        collection = subtotal - default_coupon.delight_paise(subtotal)
        expected_total = checkout_pricing.compute_quote(collection, currency="INR").total_payable_paise
        check("R1", "total = ProductsTable price x qty, Delight, 2.5% fee + 18% fee GST",
              action["total_amount"]["value"] == expected_total == int(attempt["amountPaise"]) == int(ref["amountPaise"]),
              f"total={action['total_amount']['value']} expected={expected_total} attempt={attempt['amountPaise']}")
        check("R3", "the only payable lines are the ProductsTable line and the convenience fee",
              len(action["order"]["items"]) == 2 and action["order"]["items"][1]["name"] == "Convenience fee",
              [i["name"] for i in action["order"]["items"]])
        check("INV", "the attempt records the invoice lines it was quoted (name, quantity, unit paise)",
              (attempt.get("invoiceLines") or {}).get("lines") == [
                  {"productId": shop.tee, "variantId": "TEE-M", "name": "Hermetic Tee",
                   "quantity": 3, "unitPricePaise": 59900}],
              (attempt.get("invoiceLines") or {}).get("lines"))
        check("PHY", "physical goods carry a complete shipping address",
              action["type"] == "physical-goods" and action["shipping_info"]["addresses"][0]["in_pin_code"] == "700001")
        frozen_address = attempt.get("deliveryAddress") or {}
        check("ADDR", "the attempt freezes the address and recipient Meta was shown",
              frozen_address.get("postalCode") == "700001"
              and frozen_address.get("addressLine1") == "12 Hermetic Street"
              and attempt.get("deliveryRecipient") == "Buyer 1"
              == action["shipping_info"]["addresses"][0]["name"],
              {"postalCode": frozen_address.get("postalCode"),
               "recipient": attempt.get("deliveryRecipient")})
        wire = json.dumps(msg)
        check("R13", "no payment link anywhere in the Meta request", "payment_link" not in wire)
        check("R14", "no UPI intent anywhere in the Meta request", "upi_intent" not in wire and "preferred_upi_app" not in wire)
        check("R15", "message is a template, not an interactive order_details", msg["type"] == "template" and "interactive" not in msg)
        header = [c for c in template["components"] if c.get("type") == "header"][0]
        check("HDR", "fixed wide payment header", header["parameters"][0]["image"]["link"].endswith(
            "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"), header["parameters"][0]["image"])
        send_calls = [c for c in calls if c["function"] == "wecare-outbound-whatsapp"]
        bodies = [_outbound_body(c) for c in send_calls]
        check("R11", "checkout's only outbound call uses isCheckoutTemplate + the approved template",
              len(bodies) == 1 and bodies[0].get("isCheckoutTemplate") is True
              and bodies[0].get("templateName") == PAY_TEMPLATE
              and not any(k in bodies[0] for k in ("isPaymentTemplate", "isInteractivePayment", "orderDetails"))
              and "payment_settings" not in bodies[0].get("checkoutOrderDetails", {}), [sorted(b) for b in bodies])
        outbound_cfg = send_calls[0]["config"] if send_calls else None
        check("IDEM", "checkout->outbound send has SDK retries disabled and a read timeout above outbound's 60 s",
              outbound_cfg is not None and (outbound_cfg.retries or {}).get("max_attempts") == 0
              and outbound_cfg.read_timeout > 60)
        check("R10", "attempt advanced to PAYMENT_REQUEST_SENT (monotonic rank write)",
              attempt.get("status") == "PAYMENT_REQUEST_SENT" and int(attempt.get("attemptRank", 0)) == 30,
              {k: attempt.get(k) for k in ("status", "attemptRank")})

    # ── 2b. a cart that is partly not ours is refused whole, and the customer is told ─────────
    print("\n== 2b. partly foreign cart")
    kim = shop.customer(11)
    mark = W.mark()
    deliver(order_event(build, kim["digits"], "wamid.HERMETIC.KIM.1",
                        [{"product_retailer_id": tee, "quantity": 1},
                         {"product_retailer_id": "FOREIGN-SKU-9", "quantity": 4, "item_price": 1}]))
    calls = W.since(mark, "invocations")
    replies = [_outbound_body(c) for c in calls if c["function"] == "wecare-outbound-whatsapp"]
    check("R3", "a partly foreign cart never reaches checkout and reserves nothing",
          not _checkout_invokes(calls) and not _attempts_for(kim["sub"]) and not _pay_sends(W.since(mark, "meta_sends")))
    check("UX", "...and the customer gets one plain reply saying nothing was charged",
          len(replies) == 1 and "Nothing has been charged" in str(replies[0].get("content")),
          [r.get("content") or r.get("interactiveType") for r in replies])

    # ── 3. Meta redelivers the same webhook ────────────────────────────────────────────────────
    print("\n== 3. duplicate webhook delivery (same wamid)")
    mark = W.mark()
    deliver(order_event(build, alice["digits"], wamid, items))
    deliver(order_event(build, alice["digits"], wamid, items))
    check("R6", "two redeliveries invoked checkout zero times", len(_checkout_invokes(W.since(mark, "invocations"))) == 0)
    check("R6", "still exactly ONE attempt and ONE payment template",
          len(_attempts_for(alice["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 0)

    # ── 3b. the same cart sent again as a NEW message while its request is still payable ──────
    print("\n== 3b. identical cart in a new message (new wamid)")
    mark = W.mark()
    deliver(order_event(build, alice["digits"], "wamid.HERMETIC.ALICE.2", list(reversed(items))))
    calls = W.since(mark, "invocations")
    replies = [_outbound_body(c) for c in calls if c["function"] == "wecare-outbound-whatsapp"]
    check("DUP", "a second message with the same basket mints no second attempt or payment template",
          len(_attempts_for(alice["sub"])) == 1 and not _pay_sends(W.since(mark, "meta_sends")),
          f"attempts={len(_attempts_for(alice['sub']))}")
    check("DUP", "...the customer is pointed at the request they already hold",
          len(replies) == 1 and "already sent you a payment request" in str(replies[0].get("content")),
          [r.get("content") for r in replies])

    # ── 4. wamid-less delivery: content-key fallback ───────────────────────────────────────────
    print("\n== 4. duplicate cart content without a wamid")
    bob = shop.customer(2)
    mark = W.mark()
    deliver(order_event(build, bob["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    confirm_prefilled(bob, "wamid.HERMETIC.BOB.ADDR1")
    prepared = W.mark()
    deliver(order_event(build, bob["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    check("R7", "the same wamid-less cart, redelivered once its payment request is out, never reaches checkout",
          len(_checkout_invokes(W.since(prepared, "invocations"))) == 0)
    check("R7", "exactly ONE attempt and ONE payment template",
          len(_attempts_for(bob["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1)

    # ── 5. checkout unavailable, then the customer retries ─────────────────────────────────────
    print("\n== 5. checkout unavailable -> safe retry")
    cara = shop.customer(3)
    mark = W.mark()
    W.faults[cart_function] = ["refused_before_run"]
    deliver(order_event(build, cara["digits"], "wamid.HERMETIC.CARA.1", [{"product_retailer_id": kit, "quantity": 2}]))
    check("R8", "a refused checkout invoke reserved nothing", len(_attempts_for(cara["sub"])) == 0
          and not _pay_sends(W.since(mark, "meta_sends")))
    index = _table("CommerceKeys").get_item(Key={"orderId": "WABASKETMSG#wamid.HERMETIC.CARA.1"}).get("Item")
    check("R8", "its dedupe index was rolled back", index is None)
    deliver(order_event(build, cara["digits"], "wamid.HERMETIC.CARA.2", [{"product_retailer_id": kit, "quantity": 2}]))
    confirm_prefilled(cara, "wamid.HERMETIC.CARA.ADDR1")
    check("R8", "the customer's retry produced exactly ONE attempt and ONE payment template",
          len(_attempts_for(cara["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1)
    dan = shop.customer(4)
    mark = W.mark()
    deliver(order_event(build, dan["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    # The prepare that times out is the one that pays: the confirmed resume, not the first ask.
    W.faults[cart_function] = ["timeout_after_run"]
    confirm_prefilled(dan, "wamid.HERMETIC.DAN.ADDR1")
    deliver(order_event(build, dan["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    check("R8", "an ambiguous (timed-out) prepare keeps the dedupe key: still ONE attempt, ONE template",
          len(_attempts_for(dan["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1,
          f"attempts={len(_attempts_for(dan['sub']))}")

    # ── 6. rollout gate ────────────────────────────────────────────────────────────────────────
    print("\n== 6. rollout gate")
    erin = shop.customer(5)
    direct = {"internalAction": "prepareNativeCart", "lines": [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1}],
              "contactId": erin["contactId"], "senderPhone": erin["digits"], "phoneNumberId": PHONE_ID_1}
    mark = W.mark()
    os.environ["WA_CATALOG_ORDERS_ENABLED"] = "false"
    gated = checkout.handler(dict(direct), FakeContext("wecare-checkout"))
    os.environ["WA_CATALOG_ORDERS_ENABLED"] = "true"
    check("R9", "prepareNativeCart refuses with NATIVE_CART_ROLLOUT_DISABLED when the gate is off",
          gated.get("outcome") == "NATIVE_CART_ROLLOUT_DISABLED", gated)
    check("R9", "...and reserves/sends nothing", len(_attempts_for(erin["sub"])) == 0 and not W.since(mark, "invocations"))
    _table("SystemConfigTable").put_item(Item={"id": "whatsapp_catalog_orders", "configValue": "false"})
    deliver(order_event(build, erin["digits"], "wamid.HERMETIC.ERIN.1", [{"product_retailer_id": kit, "quantity": 1}]))
    _table("SystemConfigTable").delete_item(Key={"id": "whatsapp_catalog_orders"})
    check("R9", "inbound SystemConfig override off: no checkout invoke at all",
          not _checkout_invokes(W.since(mark, "invocations")))
    for label, extra in (("not confirmed for this cart", {}),
                         ("'confirmed' sent as a string", {"deliveryConfirmed": "true"})):
        unconfirmed = checkout.handler({**direct, **extra}, FakeContext("wecare-checkout"))
        check("ADDR", f"gate on + prerequisites met, address {label}: DELIVERY_CONFIRMATION_REQUIRED, nothing reserved",
              unconfirmed.get("outcome") == "NATIVE_CART_NOT_PREPARED"
              and unconfirmed.get("error") == "DELIVERY_CONFIRMATION_REQUIRED"
              and len(_attempts_for(erin["sub"])) == 0, unconfirmed)
    ok = checkout.handler({**direct, "deliveryConfirmed": True}, FakeContext("wecare-checkout"))
    check("R10", "gate on + prerequisites met + address confirmed: NATIVE_CART_PREPARED",
          ok.get("outcome") == "NATIVE_CART_PREPARED", ok)
    http = checkout.handler({**direct, "requestContext": {"http": {"method": "POST"}}, "rawPath": "/checkout"},
                            FakeContext("wecare-checkout"))
    check("AUTH", "prepareNativeCart over an HTTP envelope is refused 403", http.get("statusCode") == 403)
    website_no_session = checkout.handler(
        {"requestContext": {"http": {"method": "POST", "path": "/ecommerce/checkout"}},
         "rawPath": "/ecommerce/checkout", "headers": {}, "body": json.dumps({"lineItems": []})},
        FakeContext("wecare-checkout"))
    check("AUTH", "website checkout still requires its customer session",
          website_no_session.get("statusCode") == 401, website_no_session.get("statusCode"))

    # ── 7. refusals that must never reach a payable message ────────────────────────────────────
    print("\n== 7. refusals before any payable message")
    def refused(label: str, customer: Dict[str, str], lines_in, expect: str, *, phone_id: str = PHONE_ID_1) -> None:
        before = W.mark()
        result = checkout.handler({"internalAction": "prepareNativeCart", "lines": lines_in,
                                   "contactId": customer["contactId"], "senderPhone": customer["digits"],
                                   "phoneNumberId": phone_id}, FakeContext("wecare-checkout"))
        got = result.get("outcome") if result.get("outcome") != "NATIVE_CART_NOT_PREPARED" else result.get("error") or result.get("status")
        check("REF", f"{label}: refused as {expect}", got == expect and not _pay_sends(W.since(before, "meta_sends"))
              and len(_attempts_for(customer["sub"] or "-")) == 0, result)

    frank = shop.customer(6, address=False, legacy_shipping=False)
    refused("physical goods without a delivery address", frank, [{"productId": shop.tee, "variantId": "TEE-M", "quantity": 1}],
            "DELIVERY_DETAILS_REQUIRED")
    gina = shop.customer(7, verified=False)
    staff_only = shop.customer(15, verified=False)
    _table("ContactsTable").update_item(
        Key={"id": staff_only["contactId"]},
        UpdateExpression="REMOVE lastInboundMessageAt")
    refused("contact with no signed WhatsApp inbound evidence", staff_only,
            [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1}],
            "WHATSAPP_IDENTITY_REQUIRED")
    hank = shop.customer(8)
    refused("archived ProductsTable item", hank, [{"productId": shop.retired, "variantId": "OLD", "quantity": 1}],
            "AMOUNT_NOT_SETTLED")
    refused("non-integer quantity", hank, [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1.5}], "NATIVE_CART_EMPTY")
    refused("WABA2 sender", hank, [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1}],
            "PAYMENT_SENDER_NOT_PERMITTED", phone_id=PHONE_ID_2)
    W.payment_configurations = [dict(LIVE_PAYMENT_CONFIGURATIONS[1], provider_mid="acc_SOMEONEELSE")]
    refused("Meta configuration pointing at another Razorpay MID", hank,
            [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1}], "payment_unavailable")
    W.payment_configurations = list(LIVE_PAYMENT_CONFIGURATIONS)
    mark = W.mark()
    deliver(order_event(build, frank["digits"], "wamid.HERMETIC.FRANK.1", [{"product_retailer_id": tee, "quantity": 1}]))
    asks = [_outbound_body(c) for c in W.since(mark, "invocations") if c["function"] == "wecare-outbound-whatsapp"]
    check("PHY", "missing address over WhatsApp: only an address request is sent, never a payment",
          not _pay_sends(W.since(mark, "meta_sends")) and len(asks) == 1
          and all(b.get("interactiveType") == "address_message" for b in asks),
          [b.get("interactiveType") or b.get("templateName") for b in asks])
    ask_data = (asks[0].get("interactiveData") or {}) if asks else {}
    check("ADDR", "...with nothing on file, the form asks for an address and prefills only the name and number",
          set(ask_data.get("values") or {}) <= {"name", "phone_number"}
          and "please share your delivery address" in str(ask_data.get("body") or "").lower(),
          sorted(ask_data.get("values") or {}))
    order_at = [i for i, c in enumerate(W.since(mark, "invocations"))
                if c["function"] in COMMERCE_FUNCTIONS and c["event"].get("internalAction") == "prepareNativeCart"]
    ask_at = [i for i, c in enumerate(W.since(mark, "invocations"))
              if c["function"] == "wecare-outbound-whatsapp" and _outbound_body(c).get("interactiveType") == "address_message"]
    check("UX", "the address is requested only AFTER checkout answered DELIVERY_DETAILS_REQUIRED",
          order_at and ask_at and ask_at[0] > order_at[0], f"prepare@{order_at} ask@{ask_at}")
    pending = _table("CommerceKeys").get_item(Key={"orderId": "WABASKETPENDING#" + frank["contactId"]}).get("Item")
    check("UX", "the refused cart waits for the address (lines + quantity, no money)",
          pending and [dict(l, quantity=int(l["quantity"])) for l in pending["lines"]]
          == [{"productId": shop.tee, "variantId": "TEE-M", "quantity": 1}]
          and not any(k in pending for k in ("amountPaise", "price", "total")), pending and pending.get("lines"))

    def address_event(digits: str, wamid_in: str, pin: str = "700016") -> Dict[str, Any]:
        values = {"name": "Buyer Six", "phone_number": "+" + digits, "address": "7 Resume Road",
                  "landmark_area": "Park Street", "city": "Kolkata", "state": "West Bengal",
                  "in_pin_code": pin}
        message = {"from": digits, "id": wamid_in, "timestamp": str(int(time.time())), "type": "interactive",
                   "interactive": {"type": "nfm_reply", "nfm_reply": {
                       "name": "address_message", "body": "Sent", "response_json": json.dumps({"values": values})}}}
        entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "919330994400", "phone_number_id": META_PHONE_1},
            "contacts": [{"wa_id": digits, "profile": {"name": "Hermetic Buyer"}}],
            "messages": [message]}}]}
        return build(entry=entry, waba_id=WABA1, meta_phone_number_ids=[META_PHONE_1],
                     request_id=str(uuid.uuid4()))

    # A five-digit PIN passes storage (international) but cannot settle a WhatsApp payment.
    mark = W.mark()
    deliver(address_event(frank["digits"], "wamid.HERMETIC.FRANK.ADDR0", pin="70001"))
    reasks = [_outbound_body(c) for c in W.since(mark, "invocations")
              if c["function"] == "wecare-outbound-whatsapp"]
    reask_data = (reasks[0].get("interactiveData") or {}) if reasks else {}
    frank_row = _table("ContactsTable").get_item(Key={"id": frank["contactId"]}).get("Item") or {}
    check("ADDR", "an address WhatsApp payment cannot settle is sent back, filled in, with the PIN marked",
          not _pay_sends(W.since(mark, "meta_sends")) and len(reasks) == 1
          and reasks[0].get("interactiveType") == "address_message"
          and "in_pin_code" in (reask_data.get("validationErrors") or {})
          and (reask_data.get("values") or {}).get("address") == "7 Resume Road"
          and "could not use that address" in str(reask_data.get("body")),
          reask_data.get("validationErrors"))
    reask_wire = [s["payload"] for s in W.since(mark, "meta_sends")
                  if (s["payload"].get("interactive") or {}).get("type") == "address_message"]
    wire_params = (((reask_wire[0].get("interactive") or {}).get("action") or {})
                   .get("parameters") or {}) if reask_wire else {}
    check("ADDR", "...and Meta receives the values and validation_errors on the address form",
          len(reask_wire) == 1 and "in_pin_code" in (wire_params.get("validation_errors") or {})
          and (wire_params.get("values") or {}).get("in_pin_code") == "70001"
          and wire_params.get("country") == "IN", sorted(wire_params))
    check("ADDR", "...it is not saved, and the cart keeps waiting for a usable one",
          not frank_row.get("checkoutDeliveryAddress")
          and bool(_table("CommerceKeys").get_item(
              Key={"orderId": "WABASKETPENDING#" + frank["contactId"]}).get("Item")),
          frank_row.get("checkoutDeliveryAddress"))
    mark = W.mark()
    deliver(address_event(frank["digits"], "wamid.HERMETIC.FRANK.ADDR1"))
    frank_attempts = _attempts_for(frank["sub"])
    check("UX", "submitting the address resumes the cart: ONE attempt and ONE payment template",
          len(frank_attempts) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1,
          f"attempts={len(frank_attempts)} pay={len(_pay_sends(W.since(mark, 'meta_sends')))}")
    resumed = _pay_sends(W.since(mark, "meta_sends"))
    if resumed:
        shipped = [c for c in resumed[0]["payload"]["template"]["components"] if c.get("type") == "button"][0]
        info = shipped["parameters"][0]["action"]["order_details"]["shipping_info"]["addresses"][0]
        check("UX", "...addressed to the address just submitted", info.get("in_pin_code") == "700016", info)
        check("ADDR", "...and to the name typed on the form, which the attempt keeps for the order",
              info.get("name") == "Buyer Six" and bool(frank_attempts)
              and frank_attempts[0].get("deliveryRecipient") == "Buyer Six",
              {"meta": info.get("name"),
               "attempt": frank_attempts[0].get("deliveryRecipient") if frank_attempts else None})
    check("UX", "...and the waiting cart is consumed",
          not _table("CommerceKeys").get_item(Key={"orderId": "WABASKETPENDING#" + frank["contactId"]}).get("Item"))
    mark = W.mark()
    deliver(address_event(frank["digits"], "wamid.HERMETIC.FRANK.ADDR2"))
    check("UX", "a second address submission resumes nothing",
          len(_attempts_for(frank["sub"])) == 1 and not _pay_sends(W.since(mark, "meta_sends")))

    # Gina has never signed into the website and has no Cognito user. The signed inbound cart
    # itself is the handset proof: inbound stamps lastInboundMessageAt before prepareNativeCart.
    _table("ContactsTable").update_item(Key={"id": gina["contactId"]},
                                        UpdateExpression="SET lastInboundMessageAt = :t",
                                        ExpressionAttributeValues={":t": Decimal(int(time.time()) - 172800)})
    mark = W.mark()
    deliver(order_event(build, gina["digits"], "wamid.HERMETIC.GINA.1",
                        [{"product_retailer_id": kit, "quantity": 1}]))
    # The cart's own message proved the handset; the confirmed address then resumes the cart
    # against the identity that first pass created.
    confirm_prefilled(gina, "wamid.HERMETIC.GINA.ADDR1")
    gina_contact = _table("ContactsTable").get_item(
        Key={"id": gina["contactId"]}, ConsistentRead=True).get("Item") or {}
    gina_owner = str(gina_contact.get("checkoutCustomerId") or "")
    gina_attempts = _attempts_for(gina_owner) if gina_owner else []
    gina_pay = _pay_sends(W.since(mark, "meta_sends"))
    gina_ctas = [s for s in W.since(mark, "meta_sends")
                 if (s["payload"].get("interactive") or {}).get("type") == "cta_url"]
    check("UX", "WhatsApp-first buyer is linked server-side with no browser sign-in",
          bool(gina_owner) and len(gina_ctas) == 0, {"owner": bool(gina_owner), "ctas": len(gina_ctas)})
    check("UX", "...and receives exactly ONE native payment request",
          len(gina_attempts) == 1 and len(gina_pay) == 1,
          {"attempts": len(gina_attempts), "pay": len(gina_pay)})
    users = cognito.list_users(UserPoolId=pool_id, Filter='phone_number = "' + gina["phone"] + '"',
                               Limit=2).get("Users") or []
    check("AUTH", "...the bridge created one verified customer-pool identity for later website use",
          len(users) == 1 and any(a.get("Name") == "phone_number_verified" and a.get("Value") == "true"
                                  for a in users[0].get("Attributes", [])), len(users))
    # A saved address WhatsApp payment cannot settle (a five-digit PIN, which storage accepts): the
    # form opens on it with the PIN marked, and the corrected form resumes the cart.
    omar = shop.customer(61)  # 1-15 and 40-42 belong to the other scenarios
    omar_row = _table("ContactsTable").get_item(Key={"id": omar["contactId"]})["Item"]
    _table("ContactsTable").put_item(Item={**omar_row, "checkoutDeliveryAddress": {
        **omar_row["checkoutDeliveryAddress"], "postalCode": "70001"}})
    mark = W.mark()
    deliver(order_event(build, omar["digits"], "wamid.HERMETIC.OMAR.1",
                        [{"product_retailer_id": kit, "quantity": 1}]))
    omar_forms = address_forms(omar, mark)
    omar_form = omar_forms[0] if omar_forms else {}
    omar_params = form_parameters(omar_form)
    omar_text = str(((omar_form.get("interactive") or {}).get("body") or {}).get("text") or "")
    check("ADDR", "an address on file WhatsApp cannot settle: the form opens on it, PIN marked, nothing payable",
          len(omar_forms) == 1 and not _pay_sends(W.since(mark, "meta_sends"))
          and not _attempts_for(omar["sub"])
          and (omar_params.get("values") or {}).get("address") == "12 Hermetic Street"
          and (omar_params.get("values") or {}).get("in_pin_code") == "70001"
          and "in_pin_code" in (omar_params.get("validation_errors") or {})
          and "cannot deliver to the address we have on file" in omar_text.lower(),
          {"errors": omar_params.get("validation_errors"), "text": omar_text[:60]})
    mark = W.mark()
    deliver(address_reply(omar, "wamid.HERMETIC.OMAR.ADDR1",
                          dict(omar_params.get("values") or {}, in_pin_code="700001")))
    omar_attempts = _attempts_for(omar["sub"])
    check("ADDR", "...the corrected form resumes the cart: ONE attempt and ONE payment template, to the new PIN",
          len(omar_attempts) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1
          and (omar_attempts[0].get("deliveryAddress") or {}).get("postalCode") == "700001",
          {"attempts": len(omar_attempts),
           "pin": (omar_attempts[0].get("deliveryAddress") or {}).get("postalCode") if omar_attempts else None})

    # A number outside India: Meta sends the India Address Message to +91 numbers only.
    # 63 and 64 are unused by the other scenarios.
    uma = shop.customer(63, address=False, legacy_shipping=False, phone="+14155550163")
    mark = W.mark()
    deliver(order_event(build, uma["digits"], "wamid.HERMETIC.UMA.1",
                        [{"product_retailer_id": kit, "quantity": 1}]))
    uma_calls = W.since(mark, "invocations")
    uma_replies = [_outbound_body(c) for c in uma_calls if c["function"] == "wecare-outbound-whatsapp"]
    uma_reply = uma_replies[0] if uma_replies else {}
    check("ADDR", "a non-+91 buyer with no address gets one website reply, never an address form it cannot receive",
          len(_checkout_invokes(uma_calls)) == 1 and len(uma_replies) == 1
          and not address_forms(uma, mark) and not _pay_sends(W.since(mark, "meta_sends"))
          and not _attempts_for(uma["sub"])
          and "only from Indian (+91) numbers" in json.dumps(uma_reply)
          and "https://wecare.digital/shop/" in json.dumps(uma_reply),
          [r.get("interactiveType") or r.get("content") for r in uma_replies])
    check("ADDR", "...and no cart is left waiting for an address that cannot arrive",
          not _table("CommerceKeys").get_item(Key={"orderId": "WABASKETPENDING#" + uma["contactId"]}).get("Item"))
    vic = shop.customer(64, phone="+14155550164")
    mark = W.mark()
    deliver(order_event(build, vic["digits"], "wamid.HERMETIC.VIC.1",
                        [{"product_retailer_id": kit, "quantity": 1}]))
    check("ADDR", "a non-+91 buyer with a payable address on file still gets ONE payment request, with no form",
          len(_attempts_for(vic["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1
          and not address_forms(vic, mark),
          {"attempts": len(_attempts_for(vic["sub"])), "pay": len(_pay_sends(W.since(mark, "meta_sends")))})

    mark = W.mark()
    ivy = shop.customer(9)
    deliver(order_event(build, ivy["digits"], "wamid.HERMETIC.IVY.1", [{"product_retailer_id": kit, "quantity": 1}],
                        meta_phone="1999999999999999", display="919999999999"))
    check("R16", "a cart that reached an unmapped number never reaches checkout",
          not _checkout_invokes(W.since(mark, "invocations")) and len(_attempts_for(ivy["sub"])) == 0)
    mark = W.mark()
    deliver(order_event(build, ivy["digits"], "wamid.HERMETIC.IVY.2", [{"product_retailer_id": "OTHER-SHOP-1", "quantity": 1}]))
    check("R3", "an all-foreign cart never reaches checkout", not _checkout_invokes(W.since(mark, "invocations")))

    # ── 8. the payment boundary refuses every other rail ───────────────────────────────────────
    print("\n== 8. outbound payment boundary")
    base_details = {"reference_id": "WD-PAY-HERMETICBOUNDARY", "type": "digital-goods", "currency": "INR",
                    "total_amount": {"value": 10000, "offset": 100},
                    "order": {"status": "pending", "items": [{"name": "x", "quantity": 1, "amount": {"value": 10000, "offset": 100}}],
                              "subtotal": {"value": 10000, "offset": 100}}}

    def boundary(label: str, req: str, body: Dict[str, Any], expect_status: int, expect_error: str) -> None:
        before = W.mark()
        result = outbound.handler({"body": json.dumps(body)}, FakeContext("wecare-outbound-whatsapp"))
        detail = json.loads(result.get("body") or "{}")
        check(req, f"{label} -> {expect_status} {expect_error}", result.get("statusCode") == expect_status
              and detail.get("error") == expect_error and not W.since(before, "meta_sends"),
              f"{result.get('statusCode')} {detail.get('error')}")

    common = {"isTemplate": True, "isCheckoutTemplate": True, "templateName": PAY_TEMPLATE, "templateParams": [],
              "phoneNumberId": PHONE_ID_1}
    removed, unresolved = "WA_PAY_ENVELOPE_NOT_PERMITTED", "WA_PAY_CONFIG_UNRESOLVED"
    boundary("retired isPaymentTemplate", "R15", {"isPaymentTemplate": True, "phoneNumberId": PHONE_ID_1}, 400, removed)
    boundary("retired isInteractivePayment", "R15", {"isInteractivePayment": True, "phoneNumberId": PHONE_ID_1}, 400, removed)
    boundary("free-form interactive order_details", "R15", {"orderDetails": base_details, "phoneNumberId": PHONE_ID_1}, 400, removed)
    for key, value, req in (("upi_intent_link", "upi://pay?pa=x@y", "R14"), ("payment_link_uri", "https://rzp.io/x", "R13"),
                            ("payment_link", "https://rzp.io/x", "R13"), ("preferred_upi_app", "gpay", "R14"),
                            ("enabled_payment_options", ["upi"], "R14"),
                            ("payment_settings", [{"type": "upi_intent_link"}], "R15"),
                            ("payment_configuration", "WECAREUPI", "R15")):
        boundary(f"caller-supplied {key}", req, {**common, "checkoutOrderDetails": {**base_details, key: value}},
                 409, unresolved)
    boundary("a second payment template name", "R12", {**common, "templateName": "wecare_other_pay_template",
                                                        "checkoutOrderDetails": base_details}, 409, "WA_PAY_TEMPLATE_NOT_PERMITTED")
    boundary("WABA2 / alternate payment WABA", "R16", {**common, "phoneNumberId": PHONE_ID_2, "checkoutOrderDetails": base_details},
             409, "WA_PAY_SENDER_NOT_PERMITTED")
    boundary("non-INR settlement currency", "R2", {**common, "checkoutOrderDetails": {**base_details, "currency": "USD"}},
             400, "ORDER_DETAILS_INVALID")
    boundary("unknown goods type", "R15", {**common, "checkoutOrderDetails": {**base_details, "type": "subscription"}},
             400, "ORDER_DETAILS_INVALID")
    boundary("empty order details", "R15", {**common, "checkoutOrderDetails": {}}, 400, "ORDER_DETAILS_INVALID")
    W.templates = [t for t in LIVE_TEMPLATES if t["name"] != PAY_TEMPLATE]
    boundary("template not APPROVED on WABA1", "R12", {**common, "checkoutOrderDetails": base_details}, 409, "WA_PAY_NOT_READY")
    W.templates = list(LIVE_TEMPLATES)
    boundary("readiness proven, no recipient (zero-send positive control)", "R12", {**common, "checkoutOrderDetails": base_details},
             400, "contactId or recipientPhone is required")

    # ── 9. payment -> ordered processing/completed templates -> ONE invoice template ─────────────
    print("\n== 9. Razorpay payment.captured -> processing -> completed -> invoice template")

    def capture(reference: str, amount: int, payment_id: str, order_id: str, phone: str) -> Dict[str, Any]:
        W.meta_payments[reference] = {"order_id": order_id, "payment_id": payment_id}
        W.rzp_payments[payment_id] = {"id": payment_id, "order_id": order_id, "status": "captured",
                                      "amount": amount, "currency": "INR"}
        body = json.dumps({"entity": "event", "account_id": PROVIDER_MID, "event": "payment.captured",
                           "contains": ["payment"], "created_at": int(time.time()), "payload": {"payment": {"entity": {
                               "id": payment_id, "entity": "payment", "amount": amount, "currency": "INR",
                               "status": "captured", "order_id": order_id, "method": "upi", "captured": True,
                               "contact": phone, "email": "", "description": "",
                               "notes": {"referenceId": reference, "source": "wecare_invoice_engine"},
                               "created_at": int(time.time())}}}})
        signature = hmac.new(webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return {"headers": {"x-razorpay-signature": signature}, "body": body, "isBase64Encoded": False,
                "requestContext": {"http": {"method": "POST", "path": "/razorpay-webhook"}}}

    def post_payment_counts(reference: str, attempt_id: str) -> Dict[str, Any]:
        orders = [o for o in _scan("OrderTable") if o.get("paymentAttemptId") == attempt_id]
        invoices = [i for i in _scan("InvoicesTable") if i.get("referenceId") == reference]
        invoice_sends = [s for s in W.meta_sends if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
        return {"orders": orders, "invoices": invoices, "invoice_sends": invoice_sends}

    if alice.get("reference"):
        reference, attempt = alice["reference"], alice["attempt"]
        amount = int(attempt["amountPaise"])
        # Paid from someone else's UPI: Razorpay's payer contact is NOT the billed customer.
        payer_phone = "+919999911111"
        event = capture(reference, amount, "pay_HERMETIC1", "order_HERMETIC1", payer_phone)
        mark = W.mark()
        sends_before = len([s for s in W.meta_sends if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE])
        first = webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        counts = post_payment_counts(reference, attempt["paymentAttemptId"])
        stored = _table("PaymentAttemptsTable").get_item(Key={"paymentAttemptId": attempt["paymentAttemptId"]}).get("Item") or {}
        check("PAY", "webhook accepted the signed capture", first.get("statusCode") == 200, first.get("body"))
        lookups = W.since(mark, "meta_lookups")
        check("PAY", "Meta binding lookup addressed WABA1 phone + WECAREDIGITAL + the reference",
              lookups == [{"phone": META_PHONE_1, "config": CONFIG_NAME, "reference": reference}], lookups)
        check("PAY", "provider readback verified the money (Razorpay /payments/{id})", "/payments/pay_HERMETIC1" in W.rzp_reads)
        check("R17", "exactly ONE internal order, finalized and paid",
              len(counts["orders"]) == 1 and counts["orders"][0].get("finalizationStage") == "ORDER_FINALIZED"
              and counts["orders"][0].get("paymentStatus") == "PAYMENT_PAID"
              and int(counts["orders"][0].get("amountPaise", 0)) == amount,
              [(o.get("orderNumber"), o.get("finalizationStage")) for o in counts["orders"]])
        check("R17", "attempt is PAYMENT_PAID with verified provider evidence",
              stored.get("status") == "PAYMENT_PAID" and int(stored.get("verifiedCapturedPaise", 0)) == amount
              and stored.get("verifiedProviderPaymentId") == "pay_HERMETIC1")
        check("R17", "exactly ONE paid invoice for the reference",
              len(counts["invoices"]) == 1 and counts["invoices"][0].get("status") == "paid", len(counts["invoices"]))
        first_asset_count = 0
        if counts["invoices"]:
            invoice = counts["invoices"][0]
            invoice_assets = [a for a in _scan("InvoiceAssetsTable")
                              if a.get("invoiceId") == invoice["invoiceId"]
                              and str(a.get("assetType") or "").startswith("image")
                              and a.get("s3Key")]
            first_asset_count = len(invoice_assets)
            check("INV", "verified capture guarantees at least one customer invoice PNG",
                  first_asset_count >= 1,
                  [(a.get("assetType"), a.get("s3Key")) for a in invoice_assets])
            from boto3.dynamodb.conditions import Key as _Key
            rows = sorted((_table("InvoiceItemsTable").query(
                KeyConditionExpression=_Key("invoiceId").eq(invoice["invoiceId"]))
                .get("Items") or []), key=lambda r: int(r["itemIndex"]))
            paise = lambda v: int((Decimal(str(v)) * 100).to_integral_value())  # noqa: E731
            subtotal_p, discount_p, tax_p, fee_p, total_p = (paise(invoice.get(k, 0)) for k in
                                                             ("subtotal", "discount", "tax", "convenienceFee", "total"))
            quote = checkout_pricing.compute_quote(collection, currency="INR")
            check("INV", "invoice is billed to the verified buyer, not the Razorpay payer",
                  invoice.get("customerPhone") == alice["phone"] and invoice.get("paidByPhone") == payer_phone,
                  {k: invoice.get(k) for k in ("customerPhone", "paidByPhone")})
            check("INV", "invoice itemises the cart (product name, quantity) instead of one 'Payment' line",
                  [(r["name"], int(r["quantity"])) for r in rows] == [("Hermetic Tee", 3)],
                  [(r.get("name"), r.get("quantity")) for r in rows])
            check("INV", "line amounts are taxable values that sum to the subtotal",
                  sum(paise(r["amount"]) * int(r["quantity"]) for r in rows) == subtotal_p,
                  f"lines={[str(r['amount']) for r in rows]} subtotal={invoice.get('subtotal')}")
            check("INV", "Delight discount shown and named; fee + fee GST exactly as quoted",
                  invoice.get("couponCode") == "DELIGHT" and discount_p > 0
                  and fee_p == quote.convenience_fee_paise + quote.convenience_gst_paise,
                  {k: invoice.get(k) for k in ("couponCode", "discount", "convenienceFee")})
            check("INV", "subtotal - discount + tax + fee == the captured amount, to the paise",
                  subtotal_p - discount_p + tax_p + fee_p == total_p == amount,
                  f"{subtotal_p}-{discount_p}+{tax_p}+{fee_p}={subtotal_p - discount_p + tax_p + fee_p} total={total_p} captured={amount}")
            check("INV", "goods GST is the 18% inclusive share of the goods collection (within rounding)",
                  abs(tax_p - (collection - (collection * 100 + 59) // 118)) <= 3,
                  f"tax={tax_p} expected~{collection - (collection * 100 + 59) // 118}")
            delivered_to = [s["payload"].get("to") for s in W.since(mark, "meta_sends")
                            if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
            check("INV", "the invoice template went to the buyer's number", delivered_to == [alice["phone"]], delivered_to)
        check("R17", "exactly ONE wecare_default_invoice_image_template send",
              len(counts["invoice_sends"]) - sends_before == 1, len(counts["invoice_sends"]) - sends_before)
        # R18: payment collection is a template-only ordered chain:
        # pending -> processing ("Payment received.") -> completed ("Payment complete.") -> invoice.
        capture_sends = W.since(mark, "meta_sends")
        status_idx = [i for i, s in enumerate(capture_sends)
                      if (s["payload"].get("template") or {}).get("name") == ORDER_STATUS_TEMPLATE]
        invoice_idx = [i for i, s in enumerate(capture_sends)
                       if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
        status_traffic = _order_status_traffic(W.since(mark, "invocations"), capture_sends)
        check("R18", "payment completion sent exactly TWO order-status templates",
              status_traffic.count("meta:order_status_template") == 2
              and status_traffic.count("meta:interactive_order_status") == 0,
              status_traffic)

        status_values = []
        status_refs = []
        for i in status_idx:
            tpl = capture_sends[i]["payload"].get("template") or {}
            for comp in tpl.get("components") or []:
                if comp.get("type") != "order_status":
                    continue
                for param in comp.get("parameters") or []:
                    osd = param.get("order_status") or {}
                    status_values.append(((osd.get("order") or {}).get("status")))
                    status_refs.append(osd.get("reference_id"))
        check("R18", "status templates are ordered processing -> completed on the same reference",
              status_values == ["processing", "completed"]
              and status_refs == [reference, reference],
              {"statuses": status_values, "refs": status_refs})
        check("R18", "both order-status templates went out BEFORE the invoice template",
              len(status_idx) == 2 and bool(invoice_idx)
              and status_idx[0] < status_idx[1] < invoice_idx[0],
              {"order_status": status_idx, "invoice": invoice_idx})

        post_capture_kinds = [
            "invoice" if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE
            else "order_status" if (s["payload"].get("template") or {}).get("name") == ORDER_STATUS_TEMPLATE
            else "order_page" if (s["payload"].get("interactive") or {}).get("type") == "cta_url"
            else f"OTHER:{s['payload'].get('type')}:{(s['payload'].get('template') or {}).get('name', '')}"
            for s in capture_sends]
        check("R17", "the capture sent two status templates, one invoice template, then the order page",
              post_capture_kinds == ["order_status", "order_status", "invoice", "order_page"], post_capture_kinds)
        # The last message: one "View your order" button to the buyer's own order page, after the
        # invoice, never instead of it.
        page_sends = [s["payload"] for s in capture_sends
                      if (s["payload"].get("interactive") or {}).get("type") == "cta_url"]
        page_action = (((page_sends[0].get("interactive") or {}).get("action") or {})
                       .get("parameters") or {}) if page_sends else {}
        page_number = str((counts["orders"][0] if counts["orders"] else {}).get("orderNumber") or "")
        check("LINK", "the order page message opens the buyer's own order, sent to the buyer",
              len(page_sends) == 1 and bool(page_number)
              and page_action.get("url") == f"https://wecare.digital/orders/?o={page_number}"
              and page_action.get("display_text") == "View your order"
              and page_sends[0].get("to") == alice["phone"],
              {"url": page_action.get("url"), "text": page_action.get("display_text")})
        page_claim = _table("CommerceKeys").get_item(Key={
            "orderId": f"INVOICEDELIVERY#{counts['invoices'][0]['invoiceId']}#order-page-link"
        }).get("Item") if counts["invoices"] else None
        check("LINK", "...and its delivery claim is recorded as delivered, so it is sent once",
              bool(page_claim) and page_claim.get("deliveryStatus") == "DELIVERED",
              (page_claim or {}).get("deliveryStatus"))
        invoice_template = (capture_sends[invoice_idx[0]]["payload"].get("template") or {}) if invoice_idx else {}
        components = invoice_template.get("components") or []
        header_ok = any(c.get("type") == "header" and any(p.get("type") == "image" for p in c.get("parameters") or [])
                        for c in components)
        button_ok = any(c.get("type") == "button" and c.get("sub_type") == "flow" and str(c.get("index")) == "0"
                        for c in components)
        check("R17", "the invoice template carries the PNG IMAGE header and the FLOW button at index 0",
              header_ok and button_ok, [(c.get("type"), c.get("sub_type"), c.get("index")) for c in components])
        check("R18", "the invoice records Meta's terminal payment-order status",
              bool(counts["invoices"]) and counts["invoices"][0].get("waOrderStatus") == "completed",
              counts["invoices"][0].get("waOrderStatus") if counts["invoices"] else None)
        check("R18", "the order payment-order projection reaches completed",
              counts["orders"] and counts["orders"][0].get("orderStatus") == "completed",
              counts["orders"][0].get("orderStatus") if counts["orders"] else None)
        paid_order = counts["orders"][0] if counts["orders"] else {}
        check("ADDR", "the order records where it ships: the address and recipient frozen at checkout",
              (paid_order.get("checkoutDeliveryAddress") or {}).get("postalCode") == "700001"
              and str(paid_order.get("shippingAddress") or "").startswith("12 Hermetic Street, Kolkata")
              and paid_order.get("deliveryRecipient") == "Buyer 1",
              {k: paid_order.get(k) for k in ("shippingAddress", "deliveryRecipient")})
        # F002: the invoice's Leave Review FLOW button carries an order-bound review token, so a
        # review written from it can be tied to this order and invoice.
        flow_tokens = [((param.get("action") or {}).get("flow_token"))
                       for i in invoice_idx
                       for comp in (capture_sends[i]["payload"].get("template") or {}).get("components") or []
                       if comp.get("type") == "button" and comp.get("sub_type") == "flow"
                       for param in comp.get("parameters") or []]
        check("F002", "the invoice FLOW button carries a minted review token (no phone inside)",
              len(flow_tokens) == 1 and str(flow_tokens[0]).startswith("review-")
              and alice["digits"] not in str(flow_tokens[0]), flow_tokens)
        if flow_tokens and counts["invoices"] and counts["orders"]:
            binding = _table("CommerceKeys").get_item(
                Key={"orderId": f"REVIEWTOKEN#{flow_tokens[0]}"}).get("Item") or {}
            check("F002", "...bound to this invoice, this order and this reference",
                  binding.get("invoiceId") == counts["invoices"][0].get("invoiceId")
                  and binding.get("boundOrderId") == counts["orders"][0].get("orderId")
                  and binding.get("referenceId") == reference,
                  {k: binding.get(k) for k in ("invoiceId", "boundOrderId", "referenceId")})
        replay = webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        check("RETRY", "identical Razorpay retry is acknowledged as already processed",
              "already_processed" in str(replay.get("body")), replay.get("body"))
        _table("WebhookDedup").delete_item(Key={"eventId": "pay_HERMETIC1:payment.captured"})
        reprocess = webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        again = post_payment_counts(reference, attempt["paymentAttemptId"])
        check("RETRY", "a full reprocess (dedup lease gone) still converges: 1 order, 1 invoice, 1 invoice send",
              reprocess.get("statusCode") == 200 and len(again["orders"]) == 1 and len(again["invoices"]) == 1
              and len(again["invoice_sends"]) - sends_before == 1,
              f"orders={len(again['orders'])} invoices={len(again['invoices'])} sends={len(again['invoice_sends']) - sends_before}")
        if again["invoices"]:
            replay_assets = [a for a in _scan("InvoiceAssetsTable")
                             if a.get("invoiceId") == again["invoices"][0]["invoiceId"]
                             and str(a.get("assetType") or "").startswith("image")
                             and a.get("s3Key")]
            check("RETRY", "...and ensure-image reuses the existing PNG instead of creating a new rendition",
                  len(replay_assets) == first_asset_count,
                  [(a.get("assetType"), a.get("s3Key")) for a in replay_assets])
        # Replaying the provider event must not create any third/fourth status message: the
        # terminal Meta state is already completed, so only the original two sends exist.
        replay_traffic = _order_status_traffic(W.since(mark, "invocations"), W.since(mark, "meta_sends"))
        check("R18", "...and replay/reprocess still leave exactly the original TWO status templates",
              sorted(replay_traffic) == [
                  "invoke:wecare-outbound-whatsapp", "invoke:wecare-outbound-whatsapp",
                  "meta:order_status_template", "meta:order_status_template"],
              replay_traffic)
        page_after_replay = [s for s in W.since(mark, "meta_sends")
                             if (s["payload"].get("interactive") or {}).get("type") == "cta_url"]
        check("LINK", "...and the order page message is not sent again by a replay or reprocess",
              len(page_after_replay) == 1, len(page_after_replay))
        # Only a WhatsApp cart or catalog-service payment gets it: a website payment's buyer is
        # already on the page, and an invoice-native payment has no order. Default deny.
        keys = _table("CommerceKeys")
        link_mark = W.mark()
        outcomes = {}
        for label, mode in (("website", "WEBSITE_RAZORPAY_STANDARD"), ("invoice-native", "WHATSAPP_NATIVE_PG"),
                            ("unknown reference", None)):
            ref = f"WD-PAY-HERMETICLINK{len(outcomes)}"
            if mode:
                keys.put_item(Item={"orderId": f"PAYREF#{ref}", "checkoutMode": mode})
            invoice_id = f"inv-hermetic-link-{len(outcomes)}"
            _table("InvoicesTable").put_item(Item={"invoiceId": invoice_id, "referenceId": ref,
                                                   "orderNumber": "WD-ORD-22222226"})
            outcomes[label] = invoice_engine._send_order_page_link(
                invoice_id, alice["contactId"], alice["phone"], PHONE_ID_1, keys, "hermetic")
        outcomes["repeat"] = invoice_engine._send_order_page_link(
            counts["invoices"][0]["invoiceId"], alice["contactId"], alice["phone"], PHONE_ID_1,
            keys, "hermetic") if counts["invoices"] else ""
        check("LINK", "website, invoice-native and unknown payments get no order page message; a repeat is refused",
              outcomes == {"website": "not_a_whatsapp_order", "invoice-native": "not_a_whatsapp_order",
                           "unknown reference": "not_a_whatsapp_order", "repeat": "already_sent"}
              and not W.since(link_mark, "meta_sends"), outcomes)
        # Outside the 24-hour window the free-form message is refused by outbound and nothing
        # reaches Meta; the claim stays, so it is not retried into a late duplicate.
        contact_row = _table("ContactsTable").get_item(Key={"id": alice["contactId"]})["Item"]
        _table("ContactsTable").put_item(Item={**contact_row, "lastInboundMessageAt": Decimal(1)})
        keys.put_item(Item={"orderId": "PAYREF#WD-PAY-HERMETICLINKW", "checkoutMode": "WHATSAPP_NATIVE_CART"})
        _table("InvoicesTable").put_item(Item={"invoiceId": "inv-hermetic-link-window",
                                               "referenceId": "WD-PAY-HERMETICLINKW",
                                               "orderNumber": "WD-ORD-22222227"})
        window_mark = W.mark()
        closed = invoice_engine._send_order_page_link(
            "inv-hermetic-link-window", alice["contactId"], alice["phone"], PHONE_ID_1, keys, "hermetic")
        again = invoice_engine._send_order_page_link(
            "inv-hermetic-link-window", alice["contactId"], alice["phone"], PHONE_ID_1, keys, "hermetic")
        _table("ContactsTable").put_item(Item=contact_row)
        check("LINK", "outside the 24-hour window: refused by outbound, nothing sent, and not retried",
              closed.startswith("not_sent_4") and again == "already_sent"
              and not W.since(window_mark, "meta_sends"), (closed, again))

        # Terminal idempotency: asking for completed again is a local no-op and never reaches
        # outbound. Then model the real uncertain edge case separately by putting the invoice back
        # at its legitimate intermediate state (processing) and crashing the completed transport.
        alice_invoice = counts["invoices"][0]["invoiceId"] if counts["invoices"] else ""
        if alice_invoice:
            repeat = invoice_engine.send_order_status(
                alice_invoice, "completed", "", PHONE_ID_1, "hermetic")
            check("R18", "a repeat 'completed' is refused before outbound (ORDER_STATUS_UNCHANGED)",
                  repeat["statusCode"] == 409 and "ORDER_STATUS_UNCHANGED" in repeat["body"],
                  repeat.get("body"))

            _table("InvoicesTable").update_item(
                Key={"invoiceId": alice_invoice},
                UpdateExpression="SET orderStatus = :p, waOrderStatus = :p",
                ExpressionAttributeValues={":p": "processing"})
            # The happy path already confirmed the completed delivery claim. Remove only that
            # hermetic claim so this isolated scenario can model the first completed attempt
            # crashing after processing was accepted.
            _table("CommerceKeys").delete_item(
                Key={"orderId": f"INVOICEDELIVERY#{alice_invoice}#order-status:completed"})
            real_outbound = W.handlers["wecare-outbound-whatsapp"]

            def crashing_outbound(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
                if "orderStatusDetails" in str(event.get("body") or ""):
                    raise RuntimeError("simulated outbound crash")
                return real_outbound(event, context)

            W.handlers["wecare-outbound-whatsapp"] = crashing_outbound
            crash_mark = W.mark()
            try:
                first = invoice_engine.send_order_status(
                    alice_invoice, "completed", "Payment complete.", PHONE_ID_1, "hermetic")
                second = invoice_engine.send_order_status(
                    alice_invoice, "completed", "Payment complete.", PHONE_ID_1, "hermetic")
            finally:
                W.handlers["wecare-outbound-whatsapp"] = real_outbound
                # The crash is injected on purpose; keep the global NET check about everything else.
                W.unexpected_http[:] = [u for u in W.unexpected_http if "simulated outbound crash" not in u]
            row = _table("InvoicesTable").get_item(Key={"invoiceId": alice_invoice}).get("Item") or {}
            check("R18", "a completed-send crash is UNCERTAIN: 502, and waOrderStatus stays processing",
                  first["statusCode"] == 502 and "ORDER_STATUS_SEND_UNCERTAIN" in first["body"]
                  and row.get("waOrderStatus") == "processing",
                  (first.get("body"), row.get("waOrderStatus")))
            outbound_calls = [call for call in W.since(crash_mark, "invocations")
                              if call["function"] == "wecare-outbound-whatsapp"]
            check("R18", "...and the held completed claim blocks a duplicate before outbound",
                  second["statusCode"] == 409 and "ORDER_STATUS_IN_FLIGHT" in second["body"]
                  and len(outbound_calls) == 1, (second.get("body"), len(outbound_calls)))
        hints = [c for c in W.since(mark, "invocations") if c["function"] in ("wecare-service-requests", "wecare-whatsapp-business-api")
                 and c["event"].get("internalAction") in ("activateServiceRequest", "preparePaidSubmitRequest")]
        check("INFO", "activation hint is re-sent per verified delivery (receiver is idempotent; not exercised here)",
              True, f"{len(hints)} hint invoke(s) over 2 processed deliveries")
        mark = W.mark()
        deliver(order_event(build, alice["digits"], "wamid.HERMETIC.ALICE.3", items))
        confirm_prefilled(alice, "wamid.HERMETIC.ALICE.ADDR3")
        check("DUP", "once the request is PAID, the same basket can be requested again (a new purchase)",
              len(_attempts_for(alice["sub"])) == 2 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1,
              f"attempts={len(_attempts_for(alice['sub']))}")

        # ── 9c. the order page: the owner reads the order; nobody else can ─────────────────────
        print("\n== 9c. order page: /orders/?o=<orderNumber> -> checkout action 'order'")
        from lambda_utils import customer_auth
        origin = "https://wecare.digital"
        number = str(paid_order.get("orderNumber") or "")
        owner = customer_auth.CustomerIdentity(customer_id=alice["sub"], subject=alice["sub"],
                                               phone=alice["phone"])
        page = checkout._order_detail(owner, {"orderNumber": number}, origin)
        page_body = json.loads(page.get("body") or "{}")
        view = page_body.get("order") or {}
        check("PAGE", "the owner gets the order: 200 ORDER_READY, never cached",
              page.get("statusCode") == 200 and page_body.get("status") == "ORDER_READY"
              and view.get("orderNumber") == number
              and "no-store" in json.dumps(page.get("headers") or {}).lower(),
              (page.get("statusCode"), page_body.get("status")))
        check("PAGE", "...with the lines the buyer reviewed (name, quantity, integer paise)",
              view.get("items") == [{"name": "Hermetic Tee", "quantity": 3, "unitPricePaise": 59900,
                                     "totalPaise": 179700}], view.get("items"))
        charges = view.get("charges") or {}
        check("PAGE", "...a breakdown that closes to the amount paid, with Delight named",
              charges.get("totalPaise") == amount == view.get("amountPaise")
              and charges.get("merchandisePaise") == 179700 and charges.get("discountPaise", 0) > 0
              and charges.get("discountLabel") == "Delight", charges)
        # Payment and fulfilment are separate. Capture starts the internal fulfilment state at
        # processing; the customer order page reads that same OrderTable value.
        check("PAGE", "...paid, placed on WhatsApp, and payment-order state is not mislabelled as fulfilment",
              view.get("paymentStatus") == "captured" and view.get("fulfilmentStatus") == ""
              and view.get("channel") == "whatsapp"
              and paid_order.get("orderStatus") == "completed",
              {k: view.get(k) for k in ("paymentStatus", "fulfilmentStatus", "channel")})
        delivery = view.get("delivery") or {}
        check("PAGE", "...and the delivery address frozen at checkout",
              (delivery.get("address") or {}).get("postalCode") == "700001"
              and delivery.get("recipient") == "Buyer 1", delivery.get("recipient"))
        contact_row = _table("ContactsTable").get_item(Key={"id": alice["contactId"]})["Item"]
        _table("ContactsTable").put_item(Item={**contact_row, "checkoutDeliveryAddress": {
            "addressLine1": "9 Moved Lane", "city": "Bengaluru", "state": "Karnataka",
            "postalCode": "560001", "countryCode": "IN"}})
        moved = json.loads(checkout._order_detail(owner, {"orderNumber": number}, origin)["body"])
        _table("ContactsTable").put_item(Item=contact_row)
        check("PAGE", "a profile address edited AFTER payment does not move the order",
              ((moved.get("order") or {}).get("delivery") or {}).get("address", {}).get("postalCode")
              == "700001", ((moved.get("order") or {}).get("delivery") or {}).get("address"))
        stranger = customer_auth.CustomerIdentity(customer_id=bob["sub"], subject=bob["sub"],
                                                  phone=bob["phone"])
        foreign = checkout._order_detail(stranger, {"orderNumber": number}, origin)
        absent = checkout._order_detail(owner, {"orderNumber": "WD-ORD-22222222"}, origin)
        check("PAGE", "another customer's order and a non-existent order answer the identical 404",
              foreign.get("statusCode") == absent.get("statusCode") == 404
              and foreign.get("body") == absent.get("body"),
              (foreign.get("statusCode"), absent.get("statusCode")))
        malformed = checkout._order_detail(owner, {"orderNumber": "WD-ORD-../../x"}, origin)
        check("PAGE", "a malformed order number is refused 400 before any read",
              malformed.get("statusCode") == 400, malformed.get("statusCode"))
        anonymous = checkout.handler(
            {"requestContext": {"http": {"method": "POST", "path": "/ecommerce/checkout/status"}},
             "rawPath": "/ecommerce/checkout/status", "headers": {},
             "body": json.dumps({"action": "order", "orderNumber": number})},
            FakeContext("wecare-checkout"))
        check("PAGE", "the order action requires the customer session (401 without one)",
              anonymous.get("statusCode") == 401, anonymous.get("statusCode"))

    # ── 9d. website checkout: the server asks for the address and freezes the one confirmed ───
    print("\n== 9d. website prepare: delivery address enforced server-side and frozen on the attempt")
    from lambda_utils import customer_auth as _customer_auth
    created_orders: List[Dict[str, Any]] = []

    def fake_create_order(*, amount_paise: int, receipt: str, notes: Any = None) -> Dict[str, Any]:
        order = {"id": f"order_WEB{len(created_orders) + 1:03d}", "key_id": "rzp_test_hermetic",
                 "amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes or {}}
        created_orders.append(order)
        return order

    real_create, real_find = checkout.razorpay_orders.create_order, checkout.razorpay_orders.find_order_by_receipt
    checkout.razorpay_orders.create_order = fake_create_order
    checkout.razorpay_orders.find_order_by_receipt = lambda receipt: None
    try:
        web_basket = [{"catalogReference": {"catalogItemId": shop.kit, "options": {"variantId": "KIT1"}},
                       "quantity": 1}]

        def web_prepare(customer: Dict[str, str], key: str) -> Dict[str, Any]:
            who = _customer_auth.CustomerIdentity(customer_id=customer["sub"], subject=customer["sub"],
                                                  phone=customer["phone"])
            result = checkout._website_prepare(who, {"action": "prepare", "lineItems": web_basket,
                                                     "requestKey": key}, "https://wecare.digital")
            return {"statusCode": result.get("statusCode"), **json.loads(result.get("body") or "{}")}

        def set_address(customer: Dict[str, str], postal: str, city: str, state: str) -> None:
            row = _table("ContactsTable").get_item(Key={"id": customer["contactId"]})["Item"]
            row["checkoutDeliveryAddress"] = {"addressLine1": f"{postal} Web Street", "city": city,
                                              "state": state, "postalCode": postal, "countryCode": "IN"}
            _table("ContactsTable").put_item(Item=row)

        # 62: 1-15, 40-42 and 61 belong to the other scenarios.
        web = shop.customer(62, address=False, legacy_shipping=False)
        before = len(created_orders)
        missing = web_prepare(web, "hermetic-web-1")
        check("WEB", "a physical basket with no delivery address is refused 409 before any provider call",
              missing["statusCode"] == 409 and missing.get("error") == "DELIVERY_DETAILS_REQUIRED"
              and len(created_orders) == before and not _attempts_for(web["sub"]), missing)
        set_address(web, "12345", "Kolkata", "West Bengal")
        unpayable = web_prepare(web, "hermetic-web-1")
        check("WEB", "...and so is an address the website channel cannot settle (5-digit PIN)",
              unpayable["statusCode"] == 409 and unpayable.get("error") == "DELIVERY_DETAILS_REQUIRED"
              and len(created_orders) == before, unpayable)
        set_address(web, "700020", "Kolkata", "West Bengal")
        ready = web_prepare(web, "hermetic-web-1")
        web_attempt_id = str(ready.get("paymentAttemptId") or "")
        web_attempt = _table("PaymentAttemptsTable").get_item(
            Key={"paymentAttemptId": web_attempt_id}).get("Item") or {} if web_attempt_id else {}
        check("WEB", "a payable address opens the payment and is frozen on the attempt",
              ready.get("status") == "CHECKOUT_OPTIONS_READY"
              and (web_attempt.get("deliveryAddress") or {}).get("postalCode") == "700020"
              and web_attempt.get("deliveryRecipient") == "Buyer 62", ready.get("status"))
        set_address(web, "560001", "Bengaluru", "Karnataka")
        resumed = web_prepare(web, "hermetic-web-1")
        web_attempt = _table("PaymentAttemptsTable").get_item(
            Key={"paymentAttemptId": web_attempt_id}).get("Item") or {}
        check("WEB", "a resumed prepare after an address change re-stamps the unpaid attempt",
              resumed.get("status") == "CHECKOUT_OPTIONS_READY"
              and resumed.get("paymentAttemptId") == web_attempt_id
              and (web_attempt.get("deliveryAddress") or {}).get("postalCode") == "560001"
              and len(created_orders) == before + 1,
              {"status": resumed.get("status"), "orders": len(created_orders) - before})
        # Exactly the attributes the browser verify's `_record_verified_capture` writes (it does NOT
        # write `verifiedProviderPaymentId`; `record_paid` does that later, inside finalization).
        _table("PaymentAttemptsTable").update_item(
            Key={"paymentAttemptId": web_attempt_id},
            UpdateExpression="SET paidAt = :t, providerPaymentId = :p, verifiedCapturedPaise = :v",
            ExpressionAttributeValues={":t": int(time.time()), ":p": "pay_HERMETICWEB",
                                       ":v": int(web_attempt.get("amountPaise") or 0)})
        from lambda_utils.ecommerce import order_delivery as _order_delivery
        web_who = _customer_auth.CustomerIdentity(customer_id=web["sub"], subject=web["sub"],
                                                  phone=web["phone"])
        checkout._refresh_attempt_delivery(web_attempt_id, web_who, _order_delivery.attempt_fields(
            {"addressLine1": "1 Late Lane", "city": "New Delhi", "state": "Delhi",
             "postalCode": "110001", "countryCode": "IN"}, {"name": "Someone Else"}))
        set_address(web, "110001", "New Delhi", "Delhi")
        web_prepare(web, "hermetic-web-1")
        web_attempt = _table("PaymentAttemptsTable").get_item(
            Key={"paymentAttemptId": web_attempt_id}).get("Item") or {}
        check("WEB", "...but once a capture is recorded the frozen address never moves",
              (web_attempt.get("deliveryAddress") or {}).get("postalCode") == "560001"
              and web_attempt.get("deliveryRecipient") == "Buyer 62",
              (web_attempt.get("deliveryAddress") or {}).get("postalCode"))
        order_view = checkout._order_view(
            {"orderNumber": "WD-ORD-22222223", "currency": "INR", "amountPaise": Decimal(100),
             "paymentStatus": "PAYMENT_PAID", "orderStatus": "shipped", "createdAt": Decimal(1),
             "checkoutDeliveryAddress": {"addressLine1": "x"}},
            {"invoiceLines": {"lines": [{"name": "A", "quantity": 1, "unitPricePaise": 100}],
                              "deliveryPaise": 0, "discountPaise": 0, "convenienceFeePaise": 1,
                              "convenienceGstPaise": 0, "totalPaise": 101}})
        check("PAGE", "an unreconciled breakdown or an unusable stored address is omitted, not shown",
              order_view["charges"] is None and order_view["delivery"] is None
              and order_view["items"][0]["totalPaise"] == 100 and order_view["fulfilmentStatus"] == "shipped",
              {k: order_view[k] for k in ("charges", "delivery", "fulfilmentStatus")})
        # A website order's row is fulfilment, set by staff, so it is shown; the same word on a
        # WhatsApp-paid row is the payment-order state and is not.
        website_view = checkout._order_view(
            {"orderNumber": "WD-ORD-22222224", "currency": "INR", "amountPaise": Decimal(100),
             "paymentStatus": "PAYMENT_PAID", "orderStatus": "completed",
             "checkoutMode": "WEBSITE_RAZORPAY_STANDARD", "createdAt": Decimal(1)}, {})
        whatsapp_view = checkout._order_view(
            {"orderNumber": "WD-ORD-22222225", "currency": "INR", "amountPaise": Decimal(100),
             "paymentStatus": "PAYMENT_PAID", "orderStatus": "completed",
             "checkoutMode": "WHATSAPP_NATIVE_CART", "createdAt": Decimal(1)}, {})
        check("PAGE", "'completed' is fulfilment on a website order and not on a WhatsApp-paid one",
              website_view["fulfilmentStatus"] == "completed" and whatsapp_view["fulfilmentStatus"] == "",
              (website_view["fulfilmentStatus"], whatsapp_view["fulfilmentStatus"]))
    finally:
        checkout.razorpay_orders.create_order = real_create
        checkout.razorpay_orders.find_order_by_receipt = real_find

    # ── 9b. status webhooks are logged without the customer's number ──────────────────────────
    print("\n== 9b. PII in inbound status logs")
    import logging as _logging

    class _Capture(_logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.lines: List[str] = []

        def emit(self, record: _logging.LogRecord) -> None:
            self.lines.append(record.getMessage())

    capture_logs = _Capture()
    _logging.getLogger().addHandler(capture_logs)
    status_entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "919330994400", "phone_number_id": META_PHONE_1},
        "statuses": [{"id": "wamid.HERMETIC0001", "status": "delivered", "timestamp": str(int(time.time())),
                      "recipient_id": alice["digits"],
                      "errors": [{"code": 131047, "title": "Re-engagement message",
                                  "error_data": {"details": "Message failed to send to " + alice["digits"]}}]}]}}]}
    deliver(build(entry=status_entry, waba_id=WABA1, meta_phone_number_ids=[META_PHONE_1],
                  request_id=str(uuid.uuid4())))
    _logging.getLogger().removeHandler(capture_logs)
    leaked = [line[:120] for line in capture_logs.lines if alice["digits"] in line]
    check("PII", "a status webhook logs no full customer number", capture_logs.lines and not leaked, leaked[:3])

    # ── 10. finalization interrupted mid-way, then a redelivery resumes it ─────────────────────
    print("\n== 10. interrupted finalization resumes on redelivery")
    jay = shop.customer(10)
    mark = W.mark()
    deliver(order_event(build, jay["digits"], "wamid.HERMETIC.JAY.1", [{"product_retailer_id": kit, "quantity": 1}]))
    confirm_prefilled(jay, "wamid.HERMETIC.JAY.ADDR1")
    jay_refs = _payrefs_for(jay["sub"])
    if jay_refs:
        reference = jay_refs[0]["referenceId"]
        jay_attempt = _attempts_for(jay["sub"])[0]
        amount = int(jay_attempt["amountPaise"])
        real_accept_paid = finalization.accept_paid
        state = {"calls": 0}

        def crash_once(**kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                finalization.record_paid(kwargs["attempts"], kwargs["attempt"],
                                         kwargs["outcome"]["providerPaymentId"], kwargs["verified_captured_paise"])
                raise RuntimeError("simulated crash after record_paid")
            return real_accept_paid(**kwargs)

        finalization.accept_paid = crash_once
        event = capture(reference, amount, "pay_HERMETIC2", "order_HERMETIC2", jay["phone"])
        webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        mid = post_payment_counts(reference, jay_attempt["paymentAttemptId"])
        quarantined = _table("CommerceKeys").scan(
            FilterExpression="begins_with(orderId, :q) AND referenceId = :r",
            ExpressionAttributeValues={":q": "CAPTUREQUARANTINE#", ":r": reference}).get("Items", [])
        check("RESUME", "crash mid-finalization: no order row, no invoice, capture quarantined",
              not mid["orders"] and not mid["invoices"] and quarantined, f"quarantine={len(quarantined)}")
        _table("WebhookDedup").delete_item(Key={"eventId": "pay_HERMETIC2:payment.captured"})
        webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        finalization.accept_paid = real_accept_paid
        done = post_payment_counts(reference, jay_attempt["paymentAttemptId"])
        jay_sends = [s for s in W.since(mark, "meta_sends") if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
        check("RESUME", "redelivery resumes from recorded evidence: ONE finalized order, ONE invoice, ONE invoice send",
              len(done["orders"]) == 1 and done["orders"][0].get("finalizationStage") == "ORDER_FINALIZED"
              and len(done["invoices"]) == 1 and len(jay_sends) == 1,
              f"orders={len(done['orders'])} invoices={len(done['invoices'])} sends={len(jay_sends)}")

    # ── 10b. the order_status step failing never blocks or repeats the invoice ──────────────────
    print("\n== 10b. order_status outage is isolated from invoice delivery")
    lea = shop.customer(40)  # numbers 1-14 belong to the other scenarios
    mark = W.mark()
    deliver(order_event(build, lea["digits"], "wamid.HERMETIC.LEA.1", [{"product_retailer_id": kit, "quantity": 1}]))
    confirm_prefilled(lea, "wamid.HERMETIC.LEA.ADDR1")
    lea_refs = _payrefs_for(lea["sub"])
    check("ISO", "setup: the buyer's cart produced a payment reference", bool(lea_refs))
    if lea_refs:
        reference = lea_refs[0]["referenceId"]
        lea_attempt = _attempts_for(lea["sub"])[0]
        real_outbound = W.handlers["wecare-outbound-whatsapp"]

        def outbound_order_status_down(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
            if "orderStatusDetails" in str(event.get("body") or ""):
                raise RuntimeError("simulated order_status outage")
            return real_outbound(event, context)

        W.handlers["wecare-outbound-whatsapp"] = outbound_order_status_down
        try:
            event = capture(reference, int(lea_attempt["amountPaise"]), "pay_HERMETIC3", "order_HERMETIC3",
                            lea["phone"])
            settled = webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))
        finally:
            W.handlers["wecare-outbound-whatsapp"] = real_outbound
            W.unexpected_http[:] = [u for u in W.unexpected_http if "simulated order_status outage" not in u]
        lea_sends = W.since(mark, "meta_sends")
        lea_invoice_sends = [s for s in lea_sends if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
        check("ISO", "order_status outage: the capture still settles with 200 (no forced replay)",
              settled.get("statusCode") == 200, settled.get("body"))
        check("ISO", "...the invoice template still went out exactly once, to the buyer",
              [s["payload"].get("to") for s in lea_invoice_sends] == [lea["phone"]], len(lea_invoice_sends))
        check("ISO", "...no order_status reached Meta",
              not [s for s in lea_sends
                   if (s["payload"].get("template") or {}).get("name") == ORDER_STATUS_TEMPLATE
                   or (s["payload"].get("interactive") or {}).get("type") == "order_status"])
        routes = [str(c["event"].get("rawPath") or "") for c in W.since(mark, "invocations")
                  if c["function"] in COMMERCE_FUNCTIONS]
        send_at = [i for i, r in enumerate(routes) if r.endswith("/send-whatsapp")]
        status_at = [i for i, r in enumerate(routes) if r.endswith("/order-status")]
        check("ISO", "...the order_status step ran once, BEFORE the invoice send, and did not stop it",
              len(status_at) == 1 and bool(send_at) and status_at[0] < send_at[0],
              {"send": send_at, "status": status_at})
        lea_invoice = post_payment_counts(reference, lea_attempt["paymentAttemptId"])["invoices"]
        check("ISO", "...and the invoice does not claim Meta accepted any status",
              bool(lea_invoice) and not lea_invoice[0].get("waOrderStatus"),
              lea_invoice[0].get("waOrderStatus") if lea_invoice else None)

    # ── 10b2. approved status template unavailable -> scheduled retry completes the chain ─────
    print("\n== 10b2. deferred processing retry -> processing -> completed")
    ria = shop.customer(42)
    mark = W.mark()
    deliver(order_event(build, ria["digits"], "wamid.HERMETIC.RIA.1",
                        [{"product_retailer_id": kit, "quantity": 1}]))
    # Every WhatsApp cart confirms its delivery address before the payment request.
    confirm_prefilled(ria, "wamid.HERMETIC.RIA.ADDR1")
    ria_refs = _payrefs_for(ria["sub"])
    check("RETRY", "setup: deferred-status buyer produced a payment reference", bool(ria_refs))
    if ria_refs:
        reference = ria_refs[0]["referenceId"]
        ria_attempt = _attempts_for(ria["sub"])[0]
        saved_templates = list(W.templates)
        W.templates = [t for t in W.templates if t.get("name") != ORDER_STATUS_TEMPLATE]
        try:
            event = capture(reference, int(ria_attempt["amountPaise"]), "pay_HERMETIC_RETRY",
                            "order_HERMETIC_RETRY", ria["phone"])
            settled = webhook.handler(json.loads(json.dumps(event)),
                                      FakeContext("wecare-razorpay-webhook"))
        finally:
            W.templates = saved_templates

        ria_rows = post_payment_counts(reference, ria_attempt["paymentAttemptId"])["invoices"]
        check("RETRY", "capture still settled and invoice was delivered while status template was unavailable",
              settled.get("statusCode") == 200 and bool(ria_rows), settled.get("body"))
        if ria_rows:
            ria_invoice = ria_rows[0]
            check("RETRY", "processing was parked in the sparse retry index",
                  ria_invoice.get("pendingOrderStatus") == "processing"
                  and ria_invoice.get("orderStatusRetry") == "PENDING",
                  {k: ria_invoice.get(k) for k in ("pendingOrderStatus", "orderStatusRetry")})

            old = int(time.time()) - 16 * 60
            _table("InvoicesTable").update_item(
                Key={"invoiceId": ria_invoice["invoiceId"]},
                UpdateExpression="SET pendingOrderStatusAt = :old, pendingOrderStatusSince = :old",
                ExpressionAttributeValues={":old": old})

            retry_mark = W.mark()
            result = webhook.handler(
                {"internalAction": "reconcileCustomerOrderLinks"},
                FakeContext("wecare-razorpay-webhook"))
            retry_sends = W.since(retry_mark, "meta_sends")
            retry_statuses = []
            for send in retry_sends:
                tpl = send["payload"].get("template") or {}
                if tpl.get("name") != ORDER_STATUS_TEMPLATE:
                    continue
                for comp in tpl.get("components") or []:
                    if comp.get("type") != "order_status":
                        continue
                    for param in comp.get("parameters") or []:
                        retry_statuses.append(
                            (((param.get("order_status") or {}).get("order") or {}).get("status")))
            check("RETRY", "scheduled retry preserved processing -> completed ordering",
                  retry_statuses == ["processing", "completed"],
                  {"statuses": retry_statuses, "result": result.get("orderStatusRetry")})
            final_invoice = _table("InvoicesTable").get_item(
                Key={"invoiceId": ria_invoice["invoiceId"]}).get("Item") or {}
            check("RETRY", "retry finished at terminal Meta status and cleared retry marker",
                  final_invoice.get("waOrderStatus") == "completed"
                  and not final_invoice.get("orderStatusRetry")
                  and not final_invoice.get("pendingOrderStatus"),
                  {k: final_invoice.get(k) for k in
                   ("waOrderStatus", "orderStatusRetry", "pendingOrderStatus")})

    # ── 10c. Razorpay never delivers; Meta's payment status asks the webhook to settle ─────────
    print("\n== 10c. Meta payment status -> reconcileReference -> ONE order, ONE invoice")
    moe = shop.customer(41)
    mark = W.mark()
    deliver(order_event(build, moe["digits"], "wamid.HERMETIC.MOE.1", [{"product_retailer_id": kit, "quantity": 1}]))
    confirm_prefilled(moe, "wamid.HERMETIC.MOE.ADDR1")
    moe_refs = _payrefs_for(moe["sub"])
    check("META", "setup: the buyer's cart produced a payment reference", bool(moe_refs))
    if moe_refs:
        reference = moe_refs[0]["referenceId"]
        moe_attempt = _attempts_for(moe["sub"])[0]
        amount = int(moe_attempt["amountPaise"])
        # The money moved at Razorpay and Meta knows it, but no Razorpay webhook ever arrives.
        W.meta_payments[reference] = {"order_id": "order_HERMETIC4", "payment_id": "pay_HERMETIC4"}
        W.rzp_payments["pay_HERMETIC4"] = {"id": "pay_HERMETIC4", "order_id": "order_HERMETIC4",
                                           "status": "captured", "amount": amount, "currency": "INR"}
        pay_status_entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "919330994400", "phone_number_id": META_PHONE_1},
            "statuses": [{"id": "wamid.HERMETIC.MOE.PAY", "type": "payment", "status": "captured",
                          "timestamp": str(int(time.time())), "recipient_id": moe["digits"],
                          "payment": {"reference_id": reference,
                                      "amount": {"value": amount, "offset": 100}, "currency": "INR",
                                      "transaction": {"id": "pay_HERMETIC4", "type": "razorpay",
                                                      "status": "success"}}}]}}]}
        W.handlers["wecare-razorpay-webhook"] = webhook.handler
        try:
            deliver(build(entry=pay_status_entry, waba_id=WABA1, meta_phone_number_ids=[META_PHONE_1],
                          request_id=str(uuid.uuid4())))
        finally:
            W.handlers.pop("wecare-razorpay-webhook", None)
        triggers = [c for c in W.since(mark, "invocations") if c["function"] == "wecare-razorpay-webhook"]
        check("META", "inbound asked the webhook to reconcile the reference, asynchronously, once",
              len(triggers) == 1 and triggers[0]["type"] == "Event"
              and triggers[0]["event"] == {"internalAction": "reconcileReference", "referenceId": reference},
              [(t["type"], t["event"]) for t in triggers])
        settled_counts = post_payment_counts(reference, moe_attempt["paymentAttemptId"])
        moe_stored = _table("PaymentAttemptsTable").get_item(
            Key={"paymentAttemptId": moe_attempt["paymentAttemptId"]}).get("Item") or {}
        check("META", "...the provider readback settled it: ONE paid order, ONE invoice",
              len(settled_counts["orders"]) == 1
              and settled_counts["orders"][0].get("paymentStatus") == "PAYMENT_PAID"
              and len(settled_counts["invoices"]) == 1 and moe_stored.get("status") == "PAYMENT_PAID",
              f"orders={len(settled_counts['orders'])} invoices={len(settled_counts['invoices'])} "
              f"attempt={moe_stored.get('status')}")
        check("META", "...with the Razorpay readback as the evidence, not Meta's word",
              "/payments/pay_HERMETIC4" in W.rzp_reads, W.rzp_reads[-3:])
        moe_sends = [s for s in W.since(mark, "meta_sends")
                     if (s["payload"].get("template") or {}).get("name") == INVOICE_TEMPLATE]
        check("META", "...and the buyer got exactly ONE invoice template", len(moe_sends) == 1, len(moe_sends))

    # ── 11. a failed payment with Razorpay's empty-notes shape is acknowledged, not retried ─────
    print("\n== 11. payment.failed with notes: []")
    body = json.dumps({"entity": "event", "event": "payment.failed", "created_at": int(time.time()),
                       "payload": {"payment": {"entity": {"id": "pay_HERMETICFAIL", "entity": "payment",
                                                          "amount": 100, "currency": "INR", "status": "failed",
                                                          "notes": [], "error_code": "BAD_REQUEST_ERROR"}}}})
    failed_event = {"headers": {"x-razorpay-signature": hmac.new(webhook_secret.encode(), body.encode(),
                                                                 hashlib.sha256).hexdigest()},
                    "body": body, "isBase64Encoded": False,
                    "requestContext": {"http": {"method": "POST", "path": "/razorpay-webhook"}}}
    failed = webhook.handler(failed_event, FakeContext("wecare-razorpay-webhook"))
    check("RETRY", "payment.failed with notes [] -> 200 (no retry storm)", failed.get("statusCode") == 200, failed.get("body"))
    bad = webhook.handler({**failed_event, "headers": {"x-razorpay-signature": "0" * 64}},
                          FakeContext("wecare-razorpay-webhook"))
    check("AUTH", "a capture with an invalid signature is refused 401", bad.get("statusCode") == 401)

    # ── 12. the catalog-service leg (Vault), with its rollout flag on for this section only ───────
    print("\n== 12. catalog-service leg: Vault only, every refusal answered, lock expires with its session")
    from lambda_utils.ecommerce import catalog_service_checkout as catalog_svc, service_requests
    catalog_services = _load("h_catalog_services", functions / "messaging" / "whatsapp-business-api"
                             / "flows" / "catalog_services.py")
    download_button = {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Access Vault",
                                                       "url": "https://wecare.digital/vault/?file={{1}}"}]}
    vault_readiness = {"templates": {
        PAY_TEMPLATE: {"id": "2714938845570815", "name": PAY_TEMPLATE, "status": "APPROVED",
                       "language": "en", "components": []},
        "wecare_default_download": {"id": "1410998911012572", "name": "wecare_default_download",
                                    "status": "APPROVED", "language": "en", "components": [download_button]}}}

    def business_api_with_services(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        if event.get("internalAction") == "catalogService":
            return catalog_services.handle(event, FakeLambda())
        if event.get("internalAction") == "catalogServiceReadiness":
            return json.loads(json.dumps(vault_readiness))
        return _business_api(event, context)

    def service_line(kind: str, quantity: int = 1) -> Dict[str, Any]:
        variant = service_requests.SERVICE_VARIANT_BY_KIND[kind]
        return {"product_retailer_id": shop.rid(service_requests.SERVICE_PRODUCT_BY_VARIANT[variant], variant),
                "quantity": quantity}

    def service_invokes(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [c for c in calls if c["function"] == "wecare-whatsapp-business-api"
                and c["event"].get("internalAction") == "catalogService"]

    def replies_in(calls: List[Dict[str, Any]]) -> List[str]:
        return [json.dumps(_outbound_body(c)) for c in calls if c["function"] == "wecare-outbound-whatsapp"]

    W.handlers["wecare-whatsapp-business-api"] = business_api_with_services
    os.environ["WHATSAPP_CATALOG_SERVICES_ENABLED"] = "true"
    lena = shop.customer(12)
    for label, lines_in, expected in (
            ("a Vault line mixed with goods", [service_line(service_requests.VAULT), {"product_retailer_id": tee, "quantity": 1}],
             "ordered on its own"),
            ("a Vault line with quantity 2", [service_line(service_requests.VAULT, 2)], "ordered on its own"),
            ("Submit Request (not sold on WhatsApp)", [service_line(service_requests.SUBMIT_REQUEST)],
             "cannot be bought from the WhatsApp catalog"),
            ("Drop Docs (not sold on WhatsApp)", [service_line(service_requests.DROP_DOCS)],
             "cannot be bought from the WhatsApp catalog")):
        mark = W.mark()
        deliver(order_event(build, lena["digits"], f"wamid.HERMETIC.LENA.{len(label)}.{expected[:6]}", lines_in))
        calls = W.since(mark, "invocations")
        replies = replies_in(calls)
        check("SVC", f"{label}: no service session, no checkout, nothing reserved",
              not service_invokes(calls) and not _checkout_invokes(calls) and not _attempts_for(lena["sub"]),
              [c["function"] for c in calls])
        check("SVC", f"{label}: the customer gets one reply ({expected!r})",
              len(replies) == 1 and expected in replies[0], replies)

    mark = W.mark()
    deliver(order_event(build, lena["digits"], "wamid.HERMETIC.LENA.VAULT", [service_line(service_requests.VAULT)]))
    calls = W.since(mark, "invocations")
    svc = service_invokes(calls)
    replies = replies_in(calls)
    check("SVC", "a lone Vault line goes to business-api catalogService once, asynchronously, never to prepareNativeCart",
          len(svc) == 1 and svc[0]["type"] == "Event" and svc[0]["event"].get("action") == "start"
          and not _checkout_invokes(calls), [(c["function"], c["event"].get("internalAction")) for c in calls])
    check("SVC", "...a verified customer with no Vault file is told so and nothing is reserved",
          not _attempts_for(lena["sub"]) and len(replies) == 1 and "No payment has been requested" in replies[0], replies)

    mia = shop.customer(13)
    mia_contact = _table("ContactsTable").get_item(Key={"id": mia["contactId"]})["Item"]
    _table("ContactsTable").put_item(Item={**mia_contact, "checkoutCustomerId": lena["sub"]})
    mark = W.mark()
    refusal = catalog_services.handle({"internalAction": "catalogService", "action": "start",
                                       "lines": [{"productId": service_requests.SERVICE_PRODUCT_BY_VARIANT[
                                           service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]],
                                           "variantId": service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT],
                                           "quantity": 1}],
                                       "sourceMessageId": "wamid.HERMETIC.MIA.1", "contactId": mia["contactId"],
                                       "senderPhone": mia["digits"], "phoneNumberId": PHONE_ID_1}, FakeLambda())
    replies = replies_in(W.since(mark, "invocations"))
    check("SVC", "an account linked to another verified number is refused without a browser sign-in CTA",
          refusal.get("outcome") == "WHATSAPP_IDENTITY_REQUIRED" and len(replies) == 1
          and "could not verify" in replies[0].lower() and "sign in" not in replies[0].lower()
          and not _table("CommerceKeys").get_item(Key={"orderId": "CATALOGSERVICEMSG#wamid.HERMETIC.MIA.1"}).get("Item"),
          refusal)

    nora = shop.customer(14)
    vault_variant = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
    vault_product = service_requests.SERVICE_PRODUCT_BY_VARIANT[vault_variant]

    # Vault is the exact-price exception at the single shared checkout seam. Pin the customer-
    # visible contract here: a 4900-paise catalogue line must remain a 4900-paise payable, while
    # an ordinary service at the same catalogue amount still receives the standard fee policy.
    original_reader = checkout._native_product_reader
    try:
        submit_variant = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.SUBMIT_REQUEST]
        submit_product = service_requests.SERVICE_PRODUCT_BY_VARIANT[submit_variant]
        products = {
            vault_product: {"status": "active", "variants": [{"sku": vault_variant, "priceMinor": 4900}]},
            submit_product: {"status": "active", "variants": [{"sku": submit_variant, "priceMinor": 4900}]},
        }
        checkout._native_product_reader = lambda: (lambda product_id: products.get(product_id))
        identity = type("CheckoutIdentity", (), {"customer_id": nora["sub"]})()
        vault_quote = checkout._native_quote(identity, [{
            "catalogReference": {"catalogItemId": vault_product, "options": {"variantId": vault_variant}},
            "quantity": 1,
        }], int(time.time())).quote
        ordinary_quote = checkout._native_quote(identity, [{
            "catalogReference": {"catalogItemId": submit_product, "options": {"variantId": submit_variant}},
            "quantity": 1,
        }], int(time.time())).quote
        check("SVC", "Vault catalogue price is the exact payable: 4900 paise, zero fee and zero fee GST",
              vault_quote.total_payable_paise == 4900
              and vault_quote.convenience_fee_paise == 0
              and vault_quote.convenience_gst_paise == 0,
              vault_quote.components())
        check("SVC", "the Vault exception does not remove the standard fee from other services",
              ordinary_quote.total_payable_paise > 4900
              and ordinary_quote.convenience_fee_paise > 0,
              ordinary_quote.components())
    finally:
        checkout._native_product_reader = original_reader

    lock_key = {"orderId": "NATIVESERVICEACTIVE#" + nora["sub"]}
    stubbed = {"calls": 0}

    def checkout_not_ready(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        if event.get("internalAction") == "prepareNativeCatalogService":
            stubbed["calls"] += 1
            return {"outcome": "NATIVE_SERVICE_META_NOT_READY"}
        return checkout.handler(event, context)

    def vault_session(token: str, file_id: str, *, owner: Optional[str]) -> None:
        now_s = int(time.time())
        file_row = {"fileId": file_id, "ownerPhone": nora["digits"], "status": "active",
                    "createdAt": str(now_s), "displayName": "Hermetic.pdf"}
        if owner:
            file_row["ownerCustomerId"] = owner
        _table("SecureFilesTable").put_item(Item=file_row)
        _table("CommerceKeys").put_item(Item={
            "orderId": catalog_svc.SESSION_PREFIX + token, "token": token, "kind": "VAULT",
            "variantId": vault_variant, "productId": vault_product, "contactId": nora["contactId"],
            "phone": nora["phone"], "customerId": nora["sub"], "phoneNumberId": PHONE_ID_1,
            "sourceMessageId": "wamid." + token, "createdAt": now_s, "expiresAt": now_s + 3600,
            "status": "SELECTING", "fileChoices": [file_id], "fileChoiceStates": ["UNPAID"]})

    def select(token: str) -> Dict[str, Any]:
        return catalog_services.handle({"internalAction": "catalogService", "action": "select", "token": token,
                                        "fileIndex": 0, "contactId": nora["contactId"], "senderPhone": nora["digits"],
                                        "phoneNumberId": PHONE_ID_1}, FakeLambda())

    W.handlers["wecare-commerce"] = checkout_not_ready
    # The REAL intent store runs here. It used to be stubbed with a comment blaming moto for
    # TransactWriteItems failing with "unhashable type: 'dict'", but that error was the
    # production defect itself: `_transact` marshalled values a second time, DynamoDB refused
    # every service transaction, and no Vault intent or grant was ever written (35f67be75).
    # The stub hid exactly that from this verifier.
    now_s = int(time.time())
    _table("CommerceKeys").put_item(Item={**lock_key, "status": "ACTIVE", "sessionKey": "CATALOGSERVICE#abandoned"})
    token_a = "A" * 24
    vault_session(token_a, "file-hermetic-a", owner=nora["sub"])
    first = select(token_a)
    lock = _table("CommerceKeys").get_item(Key=lock_key)["Item"]
    session_a = _table("CommerceKeys").get_item(Key={"orderId": catalog_svc.SESSION_PREFIX + token_a})["Item"]
    check("LOCK", "an abandoned lock from before the expiry existed no longer blocks a new purchase",
          stubbed["calls"] == 1 and lock.get("sessionKey") == catalog_svc.SESSION_PREFIX + token_a, first)
    check("LOCK", "the lock lives exactly as long as the session it names",
          int(lock.get("activeUntil", 0)) == int(session_a["expiresAt"]), {k: lock.get(k) for k in ("activeUntil", "status")})
    _table("CommerceKeys").put_item(Item={**lock_key, "status": "ACTIVE", "sessionKey": "CATALOGSERVICE#live",
                                          "activeUntil": now_s + 600})
    token_b = "B" * 24
    vault_session(token_b, "file-hermetic-b", owner=nora["sub"])
    mark = W.mark()
    second = select(token_b)
    replies = replies_in(W.since(mark, "invocations"))
    check("LOCK", "a live lock still refuses a second purchase, and says so",
          second.get("outcome") == "NATIVE_SERVICE_PAYMENT_ALREADY_IN_PROGRESS" and stubbed["calls"] == 1
          and len(replies) == 1 and "already have a service payment in progress" in replies[0], second)
    _table("CommerceKeys").put_item(Item={**lock_key, "status": "ACTIVE", "sessionKey": "CATALOGSERVICE#live",
                                          "activeUntil": now_s - 1})
    third = select(token_b)
    check("LOCK", "once its session has expired the lock is taken over by the new session",
          stubbed["calls"] == 2 and _table("CommerceKeys").get_item(Key=lock_key)["Item"].get("sessionKey")
          == catalog_svc.SESSION_PREFIX + token_b, third)
    token_c = "C" * 24
    vault_session(token_c, "file-hermetic-c", owner=None)
    _table("CommerceKeys").delete_item(Key=lock_key)
    fourth = select(token_c)
    check("SVC", "an ownerless legacy file is refused at selection without a crash or a lock",
          fourth.get("outcome") == "VAULT_FILE_SELECTION_UNAVAILABLE" and stubbed["calls"] == 2
          and not _table("CommerceKeys").get_item(Key=lock_key).get("Item"), fourth)
    W.handlers["wecare-commerce"] = checkout.handler

    # ── 13. one ₹49 Vault purchase end to end ────────────────────────────────────────────────────
    # Section 12 proves the leg up to Review and Pay; nothing else here paid for, granted or
    # delivered a Vault file. This drives the whole purchase through the production handlers:
    # business-api (offer, tap, paid delivery), commerce (Review and Pay, finalization), the
    # Razorpay webhook, service-requests (activation), secure-files (window, the customer's Vault
    # list, the download) and outbound, with the real service-request store on moto.
    print("\n== 13. Vault ₹49 end to end: offer -> Unlock Vault -> pay -> entitlement -> Access Vault"
          " -> download -> renewal")
    sys.path.insert(0, str(functions / "messaging" / "whatsapp-business-api"))
    sys.path.insert(0, str(functions / "core" / "secure-files"))
    paid_service = importlib.import_module("flows.paid_submit_request")
    activation = _load("h_service_requests", functions / "ecommerce" / "service-requests" / "handler.py")
    vault_files = _load("h_secure_files", functions / "core" / "secure-files" / "handler.py")

    def business_api_vault(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        if event.get("internalAction") == "preparePaidSubmitRequest":
            return paid_service.prepare_and_send(event, FakeLambda(), None)
        return business_api_with_services(event, context)

    W.handlers.update({"wecare-whatsapp-business-api": business_api_vault,
                       "wecare-service-requests": activation.handler,
                       "wecare-secure-files": vault_files.handler})
    saved_reader, saved_templates = checkout._native_product_reader, list(W.templates)
    vault_catalogue = {vault_product: {"status": "active",
                                       "variants": [{"sku": vault_variant, "priceMinor": 4900}]}}
    checkout._native_product_reader = lambda: (lambda product_id: vault_catalogue.get(product_id))
    # Outbound proves a template's live category before it sends (the 2026-10-26 readback).
    W.templates = saved_templates + [{"name": "wecare_valut_49", "status": "APPROVED",
                                      "category": "UTILITY", "sub_category": None, "language": "en"}]

    def unlock_tap(customer: Dict[str, str], wamid: str, payload: str) -> Dict[str, Any]:
        """A tap on the offer's Unlock Vault quick reply, as Meta delivers it."""
        message = {"from": customer["digits"], "id": wamid, "timestamp": str(int(time.time())),
                   "type": "button", "button": {"payload": payload, "text": "Unlock Vault"},
                   "context": {"from": "919330994400", "id": "wamid.HERMETIC.VAULTOFFER"}}
        entry = {"id": WABA1, "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "919330994400", "phone_number_id": META_PHONE_1},
            "contacts": [{"wa_id": customer["digits"], "profile": {"name": "Hermetic Buyer"}}],
            "messages": [message]}}]}
        return build(entry=entry, waba_id=WABA1, meta_phone_number_ids=[META_PHONE_1],
                     request_id=str(uuid.uuid4()))

    def sends_of(since: Dict[str, int], template: str) -> List[Dict[str, Any]]:
        return [s["payload"] for s in W.since(since, "meta_sends")
                if (s["payload"].get("template") or {}).get("name") == template]

    def component_value(payload: Dict[str, Any], kind: str, sub_type: str = "") -> str:
        """The first parameter of the template's body, or of its button of `sub_type`."""
        for component in (payload.get("template") or {}).get("components") or []:
            if component.get("type") == kind and (not sub_type or component.get("sub_type") == sub_type):
                parameter = (component.get("parameters") or [{}])[0]
                return str(parameter.get("text") or parameter.get("payload") or "")
        return ""

    def send_offer(customer: Dict[str, str], file_id: str) -> Dict[str, Any]:
        """Staff "Send ₹49 Vault message", as secure-files invokes it."""
        return catalog_services.handle({"internalAction": "catalogService", "action": "sendOffer",
                                        "fileId": file_id, "ownerCustomerId": customer["sub"],
                                        "ownerPhone": customer["digits"], "requestedBy": "hermetic"},
                                       FakeLambda())

    def offer_tokens(file_id: str) -> set:
        return {str(row["orderId"]).split("#", 1)[1] for row in _scan("CommerceKeys")
                if str(row.get("orderId", "")).startswith("VAULTOFFER#") and row.get("fileId") == file_id}

    def register_vault_file(customer: Dict[str, str], file_id: str, name: str) -> None:
        _table("SecureFilesTable").put_item(Item={
            "fileId": file_id, "ownerPhone": customer["digits"], "ownerCustomerId": customer["sub"],
            "status": "active", "createdAt": str(int(time.time())), "displayName": name,
            "originalFilename": "hermetic.pdf", "s3Key": "secure/u/" + file_id + ".pdf",
            "deliverable": "pdf", "deliveryKey": "secure/d/" + file_id + ".pdf",
            "contentType": "application/pdf", "sizeBytes": 1000, "pricePaise": 4900})

    def pay(attempt: Dict[str, Any], payment_id: str, phone: str) -> Dict[str, Any]:
        event = capture(attempt["referenceId"], int(attempt["amountPaise"]), payment_id,
                        "order_" + payment_id, phone)
        return webhook.handler(json.loads(json.dumps(event)), FakeContext("wecare-razorpay-webhook"))

    # A WhatsApp-only customer: no email, no address, no shipping profile (the QA number's shape).
    vera = shop.customer(70, email=False, address=False, legacy_shipping=False)
    vera_file = "file-hermetic-vault-e2e"
    register_vault_file(vera, vera_file, "Hermetic report.pdf")
    vera_vault = {"username": vera["phone"], "phone": vera["digits"], "subject": vera["sub"]}
    entitlement_id = "vault-entitlement#" + vera["sub"] + "#" + vera_file

    mark = W.mark()
    offered = send_offer(vera, vera_file)
    tokens = offer_tokens(vera_file)
    offer_sends = sends_of(mark, "wecare_valut_49")
    token = next(iter(tokens), "")
    check("VLT", "staff Send ₹49 Vault message: ONE wecare_valut_49 naming the file, its Unlock Vault tied to one offer",
          offered.get("outcome") == "VAULT_OFFER_SENT" and len(offer_sends) == 1 and len(tokens) == 1
          and component_value(offer_sends[0], "body") == "Hermetic report.pdf"
          and component_value(offer_sends[0], "button", "quick_reply") == "vaultoffer:" + token,
          {"outcome": offered, "sends": len(offer_sends), "offers": len(tokens)})

    mark = W.mark()
    deliver(unlock_tap(vera, "wamid.HERMETIC.VAULT.TAP1", "vaultoffer:" + token))
    attempts = _attempts_for(vera["sub"])
    intents = [r for r in _scan("ServiceRequestsTable")
               if str(r.get("requestId", "")).startswith("INTENT#") and r.get("vaultFileId") == vera_file]
    check("VLT", "Unlock Vault records a real Vault intent and sends ONE Review and Pay for 4900 paise",
          len(intents) == 1 and len(sends_of(mark, PAY_TEMPLATE)) == 1 and len(attempts) == 1
          and int(attempts[0].get("amountPaise") or 0) == 4900,
          {"intents": len(intents), "attempts": [{k: a.get(k) for k in ("status", "amountPaise")} for a in attempts]})
    mark = W.mark()
    deliver(unlock_tap(vera, "wamid.HERMETIC.VAULT.TAP1", "vaultoffer:" + token))
    check("VLT", "a replayed tap reserves and sends nothing new",
          not sends_of(mark, PAY_TEMPLATE) and len(_attempts_for(vera["sub"])) == 1,
          len(_attempts_for(vera["sub"])))

    if attempts:
        purchase = attempts[0]
        mark = W.mark()
        answer = pay(purchase, "pay_HERMETIC_VAULT1", vera["phone"])
        orders = [o for o in _scan("OrderTable") if o.get("paymentAttemptId") == purchase["paymentAttemptId"]]
        check("VLT", "the capture finalizes ONE paid order",
              answer.get("statusCode") == 200 and len(orders) == 1
              and orders[0].get("finalizationStage") == "ORDER_FINALIZED"
              and orders[0].get("paymentStatus") == "PAYMENT_PAID",
              [(o.get("orderNumber"), o.get("finalizationStage"), o.get("paymentStatus")) for o in orders])
        entitlement = _table("DownloadGrantsTable").get_item(Key={"grantId": entitlement_id}).get("Item") or {}
        paid_file = _table("SecureFilesTable").get_item(Key={"fileId": vera_file}).get("Item") or {}
        vault_requests = [r for r in _scan("ServiceRequestsTable")
                          if str(r.get("requestId", "")).startswith("REQ#") and r.get("vaultFileId") == vera_file]
        check("VLT", "payment activates ONE Vault request, writes ONE durable entitlement and marks the file PAID",
              len(vault_requests) == 1 and bool(vault_requests[0].get("paidAt"))
              and entitlement.get("recordType") == "VAULT_ENTITLEMENT"
              and entitlement.get("entitlementState") == "ACTIVE"
              and int(entitlement.get("paidWindowCount") or 0) == 1
              and paid_file.get("vaultPaymentStatus") == "PAID"
              and paid_file.get("vaultEntitlementId") == entitlement_id,
              {"requests": len(vault_requests),
               "entitlement": {k: entitlement.get(k) for k in ("recordType", "entitlementState", "paidWindowCount")},
               "file": {k: paid_file.get(k) for k in ("vaultPaymentStatus", "vaultEntitlementId")}})
        access_sends = sends_of(mark, "wecare_default_download")
        check("VLT", "ONE Access Vault link whose button carries the file id, and the paid 24-hour window opens",
              len(access_sends) == 1 and component_value(access_sends[0], "button", "url") == vera_file
              and int(entitlement.get("accessWindowCount") or 0) == 1
              and int(entitlement.get("accessWindowEndsAt") or 0) > time.time(),
              {"sends": len(access_sends),
               "window": {k: entitlement.get(k) for k in ("accessWindowCount", "accessWindowEndsAt")}})
        listed = json.loads(vault_files._customer_list(vera_vault, "https://wecare.digital")["body"])
        vault_row = next((f for f in listed.get("files") or [] if f.get("fileId") == vera_file), {})
        download = vault_files._redeem(vera_file, {"queryStringParameters": {"grant": vault_row.get("paidEntitlementId") or ""}},
                                       vera_vault, "https://wecare.digital")
        download_body = json.loads(download["body"])
        check("VLT", "the customer's Vault lists the file OPEN and issues a short-lived download",
              vault_row.get("accessState") == "OPEN" and download["statusCode"] == 200
              and str(download_body.get("downloadUrl") or "").startswith("https://")
              and 0 < int(download_body.get("expiresInSeconds") or 0) <= 300,
              {"accessState": vault_row.get("accessState"), "status": download["statusCode"],
               "keys": sorted(download_body)})
        _table("WebhookDedup").delete_item(Key={"eventId": "pay_HERMETIC_VAULT1:payment.captured"})
        mark = W.mark()
        pay(purchase, "pay_HERMETIC_VAULT1", vera["phone"])
        replayed = _table("DownloadGrantsTable").get_item(Key={"grantId": entitlement_id}).get("Item") or {}
        check("VLT", "a reprocessed capture grants, charges and sends nothing new",
              not sends_of(mark, "wecare_default_download") and not sends_of(mark, PAY_TEMPLATE)
              and int(replayed.get("paidWindowCount") or 0) == 1 and int(replayed.get("accessWindowCount") or 0) == 1,
              {k: replayed.get(k) for k in ("paidWindowCount", "accessWindowCount")})

        # The window closes; staff ask again; the customer pays; the SAME entitlement gains a window.
        _table("DownloadGrantsTable").update_item(
            Key={"grantId": entitlement_id}, UpdateExpression="SET accessWindowEndsAt = :past",
            ExpressionAttributeValues={":past": int(time.time()) - 7 * 86400})
        listed = json.loads(vault_files._customer_list(vera_vault, "https://wecare.digital")["body"])
        expired_state = next((f.get("accessState") for f in listed.get("files") or []
                              if f.get("fileId") == vera_file), None)
        # The per-file guard refuses a second offer within 60 s, and this run is faster than that.
        _table("CommerceKeys").delete_item(Key={"orderId": "VAULTOFFERFILE#" + vera_file})
        renewal_offer = send_offer(vera, vera_file)
        new_tokens = offer_tokens(vera_file) - tokens
        check("VLT", "once the window closes the file reads EXPIRED and staff send a renewal offer",
              expired_state == "EXPIRED" and renewal_offer.get("outcome") == "VAULT_OFFER_SENT"
              and renewal_offer.get("renewal") is True and len(new_tokens) == 1,
              {"state": expired_state, "offer": renewal_offer})
        mark = W.mark()
        deliver(unlock_tap(vera, "wamid.HERMETIC.VAULT.TAP2", "vaultoffer:" + next(iter(new_tokens), "")))
        renewals = [a for a in _attempts_for(vera["sub"]) if a["paymentAttemptId"] != purchase["paymentAttemptId"]]
        check("VLT", "the renewal tap sends ONE more Review and Pay for 4900 paise",
              len(sends_of(mark, PAY_TEMPLATE)) == 1 and len(renewals) == 1
              and int(renewals[0].get("amountPaise") or 0) == 4900,
              [{k: a.get(k) for k in ("status", "amountPaise")} for a in renewals])
        if renewals:
            mark = W.mark()
            pay(renewals[0], "pay_HERMETIC_VAULT2", vera["phone"])
            renewed = _table("DownloadGrantsTable").get_item(Key={"grantId": entitlement_id}).get("Item") or {}
            again = vault_files._redeem(vera_file, {"queryStringParameters": {"grant": entitlement_id}},
                                        vera_vault, "https://wecare.digital")
            check("VLT", "renewal adds a second paid window to the SAME entitlement, opens it, sends ONE Access"
                  " Vault and the download works again",
                  int(renewed.get("paidWindowCount") or 0) == 2 and int(renewed.get("accessWindowCount") or 0) == 2
                  and int(renewed.get("accessWindowEndsAt") or 0) > time.time()
                  and len(sends_of(mark, "wecare_default_download")) == 1 and again["statusCode"] == 200,
                  {"entitlement": {k: renewed.get(k) for k in ("paidWindowCount", "accessWindowCount")},
                   "access_sends": len(sends_of(mark, "wecare_default_download")), "download": again["statusCode"]})

    # A Vault customer whose WhatsApp contact was never linked to their account, the usual state for
    # a file registered under Secure files: the tap is itself the signed message the identity bridge
    # links them from, so Review and Pay needs no website sign-in first.
    wren = shop.customer(71, email=False, address=False, legacy_shipping=False)
    _table("ContactsTable").update_item(Key={"id": wren["contactId"]}, UpdateExpression="REMOVE checkoutCustomerId")
    wren_file = "file-hermetic-vault-unlinked"
    register_vault_file(wren, wren_file, "Unlinked report.pdf")
    send_offer(wren, wren_file)
    mark = W.mark()
    deliver(unlock_tap(wren, "wamid.HERMETIC.VAULT.UNLINKED", "vaultoffer:" + next(iter(offer_tokens(wren_file)), "")))
    linked = (_table("ContactsTable").get_item(Key={"id": wren["contactId"]}).get("Item") or {}).get("checkoutCustomerId")
    check("VLT", "an unlinked WhatsApp contact is linked by the tap itself and gets ONE Review and Pay",
          linked == wren["sub"] and len(sends_of(mark, PAY_TEMPLATE)) == 1 and len(_attempts_for(wren["sub"])) == 1,
          {"linked": linked == wren["sub"], "pays": len(sends_of(mark, PAY_TEMPLATE)),
           "attempts": len(_attempts_for(wren["sub"]))})

    checkout._native_product_reader = saved_reader
    W.templates = saved_templates
    W.handlers.pop("wecare-service-requests", None)
    W.handlers.pop("wecare-secure-files", None)
    W.handlers.pop("wecare-whatsapp-business-api", None)
    # Paid Vault delivery and the invoice copy reach the customer through outbound, which resolves
    # only our Direct-API sender ids and refuses the bare Meta phone id they used to send with.
    flows_dir = functions / "messaging" / "whatsapp-business-api" / "flows"
    paid_vault = _load("h_paid_vault", flows_dir / "paid_vault.py")
    try:
        resolved = outbound._resolve_meta_phone_id(paid_vault.WABA1_SENDER)
    except Exception as error:  # noqa: BLE001 - a refusal is the failure being checked
        resolved = type(error).__name__
    bare = [f"{p.name}:{n}" for p in sorted(flows_dir.glob("*.py"))
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if re.search(r"'phoneNumberId':\s*'\d+'", line)]
    check("SVC", "paid Vault delivery sends from a sender outbound resolves; no flow sends from a bare Meta id",
          resolved == META_PHONE_1 and not bare, {"resolved": resolved, "bare": bare})
    os.environ.pop("WHATSAPP_CATALOG_SERVICES_ENABLED", None)

    # ── summary ────────────────────────────────────────────────────────────────────────────────
    stray = [u for u in W.unexpected_http]
    check("NET", "no unexpected network call or unhandled handler error", not stray, stray[:5])
    failed = [r for r in RESULTS if not r["pass"]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for r in failed:
        print(f"  FAILED {r['req']} {r['name']} :: {r['evidence']}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="repository tree to verify (default: this checkout)")
    parser.add_argument("--json", dest="json_out", help="also write the check results here")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    print(f"verifying the WhatsApp payment rail in {root}")
    with mock_aws():
        try:
            code = run(root)
        except Exception:  # noqa: BLE001 - a crash in the harness is a failed verification
            traceback.print_exc()
            code = 1
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(RESULTS, indent=2) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
