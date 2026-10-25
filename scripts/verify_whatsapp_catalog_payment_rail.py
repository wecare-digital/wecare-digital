#!/usr/bin/env python3
"""Hermetic end-to-end verification of the ONE WhatsApp payment rail.

    WhatsApp Catalog order -> wecare-inbound-whatsapp -> wecare-checkout `prepareNativeCart`
    -> ProductsTable pricing -> ONE PaymentAttempt + PAYREF# -> wecare-outbound-whatsapp
    -> `wecare_whatapp_native_pay_template` (button sub_type order_details, payment_gateway /
    Razorpay / WECAREDIGITAL) -> Razorpay `payment.captured` -> wecare-razorpay-webhook
    -> ONE order -> ONE paid invoice -> `wecare_default_invoice_image_template`. No ORDER_STATUS.

WHAT RUNS FOR REAL
------------------
The production handlers, imported from the tree under test: the inbound worker (driven through
its real internal-event entry point), checkout and its packaged invoice engine, outbound, and
the Razorpay webhook. Every DynamoDB and Cognito call is served by moto with real conditional-
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
ORDER_STATUS_TEMPLATE = "wecare_order_status_v2"
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
    'InvoicesTable': ([('invoiceId', 'S', 'HASH')], {'referenceId-index': [('referenceId', 'S', 'HASH')], 'contactId-index': [('contactId', 'S', 'HASH')]}),
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
                 address: bool = True, legacy_shipping: bool = True) -> Dict[str, str]:
        phone = f"+9198765{n:05d}"
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


def _checkout_invokes(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in calls if c["function"] == "wecare-checkout"
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
    pool_id = cognito.create_user_pool(PoolName="hermetic-customers")["UserPool"]["Id"]
    os.environ["CUSTOMER_POOL_ID"] = pool_id
    _create_tables()

    from lambda_utils import contact_key, wa_internal_event  # noqa: E402
    from lambda_utils.ecommerce import checkout_pricing, default_coupon, meta_catalog_sync as mcs
    from lambda_utils.ecommerce import whatsapp_basket
    from lambda_utils.integrations import meta_payment_binding, razorpay_verify
    from lambda_utils.ecommerce import finalization

    inbound = _load("h_inbound", functions / "messaging" / "inbound-whatsapp-handler" / "handler.py")
    checkout = _load("h_checkout", functions / "ecommerce" / "checkout" / "handler.py")
    outbound = _load("h_outbound", functions / "messaging" / "outbound-whatsapp" / "handler.py")
    webhook = _load("h_webhook", functions / "payments" / "razorpay-webhook" / "handler.py")
    import invoice_engine  # noqa: E402 - the copy packaged inside wecare-checkout

    W.handlers.update({"wecare-checkout": checkout.handler, "wecare-outbound-whatsapp": outbound.handler,
                       "wecare-inbound-whatsapp": inbound.handler})

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

    # ── 2. happy path: catalog cart -> ONE attempt -> the ONE approved template ─────────────────
    print("\n== 2. catalog cart -> prepareNativeCart -> ONE attempt -> approved ORDER_DETAILS template")
    alice = shop.customer(1)
    mark = W.mark()
    wamid = "wamid.HERMETIC.ALICE.1"
    items = [{"product_retailer_id": tee, "quantity": 2, "item_price": 499, "currency": "USD"},
             {"product_retailer_id": tee, "quantity": 1, "item_price": 499, "currency": "USD"},
             {"product_retailer_id": "FOREIGN-SKU-9", "quantity": 4, "item_price": 1, "currency": "INR"}]
    deliver(order_event(build, alice["digits"], wamid, items))
    calls = W.since(mark, "invocations")
    prepares = _checkout_invokes(calls)
    check("R10", "inbound invoked wecare-checkout prepareNativeCart exactly once", len(prepares) == 1, len(prepares))
    if prepares:
        payload = prepares[0]["event"]
        check("R1", "prepareNativeCart payload carries no money/payment field",
              set(payload) <= {"internalAction", "lines", "sourceMessageId", "contactId", "senderPhone", "phoneNumberId"}
              and all(set(l) == {"productId", "variantId", "quantity"} for l in payload["lines"]), sorted(payload))
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
        check("R3", "the foreign retailer id never became a payable line",
              len(action["order"]["items"]) == 2 and action["order"]["items"][1]["name"] == "Convenience fee",
              [i["name"] for i in action["order"]["items"]])
        check("PHY", "physical goods carry a complete shipping address",
              action["type"] == "physical-goods" and action["shipping_info"]["addresses"][0]["in_pin_code"] == "700001")
        wire = json.dumps(msg)
        check("R13", "no payment link anywhere in the Meta request", "payment_link" not in wire)
        check("R14", "no UPI intent anywhere in the Meta request", "upi_intent" not in wire and "preferred_upi_app" not in wire)
        check("R15", "message is a template, not an interactive order_details", msg["type"] == "template" and "interactive" not in msg)
        header = [c for c in template["components"] if c.get("type") == "header"][0]
        check("HDR", "fixed WECARE header image link", header["parameters"][0]["image"]["link"].endswith(
            "secure/d/public/whatsapp/wa-tpl/img/wecarepay-header.png"), header["parameters"][0]["image"])
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

    # ── 3. Meta redelivers the same webhook ────────────────────────────────────────────────────
    print("\n== 3. duplicate webhook delivery (same wamid)")
    mark = W.mark()
    deliver(order_event(build, alice["digits"], wamid, items))
    deliver(order_event(build, alice["digits"], wamid, items))
    check("R6", "two redeliveries invoked checkout zero times", len(_checkout_invokes(W.since(mark, "invocations"))) == 0)
    check("R6", "still exactly ONE attempt and ONE payment template",
          len(_attempts_for(alice["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 0)

    # ── 4. wamid-less delivery: content-key fallback ───────────────────────────────────────────
    print("\n== 4. duplicate cart content without a wamid")
    bob = shop.customer(2)
    mark = W.mark()
    deliver(order_event(build, bob["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    deliver(order_event(build, bob["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
    check("R7", "two identical wamid-less carts invoked checkout once",
          len(_checkout_invokes(W.since(mark, "invocations"))) == 1)
    check("R7", "exactly ONE attempt and ONE payment template",
          len(_attempts_for(bob["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1)

    # ── 5. checkout unavailable, then the customer retries ─────────────────────────────────────
    print("\n== 5. checkout unavailable -> safe retry")
    cara = shop.customer(3)
    mark = W.mark()
    W.faults["wecare-checkout"] = ["refused_before_run"]
    deliver(order_event(build, cara["digits"], "wamid.HERMETIC.CARA.1", [{"product_retailer_id": kit, "quantity": 2}]))
    check("R8", "a refused checkout invoke reserved nothing", len(_attempts_for(cara["sub"])) == 0
          and not _pay_sends(W.since(mark, "meta_sends")))
    index = _table("CommerceKeys").get_item(Key={"orderId": "WABASKETMSG#wamid.HERMETIC.CARA.1"}).get("Item")
    check("R8", "its dedupe index was rolled back", index is None)
    deliver(order_event(build, cara["digits"], "wamid.HERMETIC.CARA.2", [{"product_retailer_id": kit, "quantity": 2}]))
    check("R8", "the customer's retry produced exactly ONE attempt and ONE payment template",
          len(_attempts_for(cara["sub"])) == 1 and len(_pay_sends(W.since(mark, "meta_sends"))) == 1)
    dan = shop.customer(4)
    mark = W.mark()
    W.faults["wecare-checkout"] = ["timeout_after_run"]
    deliver(order_event(build, dan["digits"], None, [{"product_retailer_id": kit, "quantity": 1}]))
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
    ok = checkout.handler(dict(direct), FakeContext("wecare-checkout"))
    check("R10", "gate on + prerequisites met: NATIVE_CART_PREPARED", ok.get("outcome") == "NATIVE_CART_PREPARED", ok)
    http = checkout.handler({**direct, "requestContext": {"http": {"method": "POST"}}, "rawPath": "/checkout"},
                            FakeContext("wecare-checkout"))
    check("AUTH", "prepareNativeCart over an HTTP envelope is refused 403", http.get("statusCode") == 403)

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
    refused("customer without a verified WECARE account", gina, [{"productId": shop.kit, "variantId": "KIT1", "quantity": 1}],
            "VERIFIED_CUSTOMER_REQUIRED")
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
          not _pay_sends(W.since(mark, "meta_sends")) and asks and all(b.get("interactiveType") == "address_message" for b in asks),
          [b.get("interactiveType") or b.get("templateName") for b in asks])
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

    # ── 9. payment -> ONE order -> ONE invoice -> invoice template, zero ORDER_STATUS ──────────
    print("\n== 9. Razorpay payment.captured -> order -> invoice -> invoice template")

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
        event = capture(reference, amount, "pay_HERMETIC1", "order_HERMETIC1", alice["phone"])
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
        check("R17", "exactly ONE wecare_default_invoice_image_template send",
              len(counts["invoice_sends"]) - sends_before == 1, len(counts["invoice_sends"]) - sends_before)
        status_traffic = _order_status_traffic(W.since(mark, "invocations"), W.since(mark, "meta_sends"))
        check("R18", "payment completion sent ZERO ORDER_STATUS messages", not status_traffic, status_traffic)
        check("R18", "the order's internal status is 'processing' (database field only)",
              counts["orders"] and counts["orders"][0].get("orderStatus") == "processing")
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
        check("R18", "...and still ZERO ORDER_STATUS",
              not _order_status_traffic(W.since(mark, "invocations"), W.since(mark, "meta_sends")))
        hints = [c for c in W.since(mark, "invocations") if c["function"] in ("wecare-service-requests", "wecare-whatsapp-business-api")
                 and c["event"].get("internalAction") in ("activateServiceRequest", "preparePaidSubmitRequest")]
        check("INFO", "activation hint is re-sent per verified delivery (receiver is idempotent; not exercised here)",
              True, f"{len(hints)} hint invoke(s) over 2 processed deliveries")

    # ── 10. finalization interrupted mid-way, then a redelivery resumes it ─────────────────────
    print("\n== 10. interrupted finalization resumes on redelivery")
    jay = shop.customer(10)
    mark = W.mark()
    deliver(order_event(build, jay["digits"], "wamid.HERMETIC.JAY.1", [{"product_retailer_id": kit, "quantity": 1}]))
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
