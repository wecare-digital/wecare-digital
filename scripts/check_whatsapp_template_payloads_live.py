#!/usr/bin/env python3
"""Read-only: build every registered WhatsApp template's send with the production code and check
it against that template's LIVE Meta definition.

`check_whatsapp_templates_live.py` proves each registered template is APPROVED. This proves the
message each sender builds is one Meta can accept, component by component:

  * a header parameter of the declared type (IMAGE link or media id, LOCATION latitude and
    longitude), and no header when the template has none;
  * exactly as many body parameters as the body has variables;
  * a parameter for every dynamic URL button, at that button's index;
  * a `flow` component carrying a `flow_token` for a FLOW button;
  * the `order_details` action (reference, goods type, INR, Razorpay payment_settings, order,
    total) for the ORDER_DETAILS button, and an `order_status` component for ORDER_STATUS;
  * the AUTHENTICATION copy-code shape: the code as the body variable and as URL button 0, and
    an OTP lifetime equal to the template's `code_expiration_minutes`;
  * the template's language, and a sender that resolves to WABA1's phone number.
A send that fails any of these is refused by Meta (131008, 131009, 132000, 132012).

What runs for real, read-only
  * the live definitions: `wecare-whatsapp-template-management:live` (components) and
    `wecare-whatsapp-business-api:live` `/wa-business/payment-templates/list` (status,
    sub_category);
  * the reads outbound's own gates make (template category, ORDER_STATUS approval, payment
    readiness), through `wecare-whatsapp-business-api:live`;
  * the production builders from this tree: `outbound-whatsapp`'s handler for every outbound
    template, fed the request bodies the real callers compose, and `customer-whatsapp-auth` into
    `whatsapp-business-api`'s send route for the OTP.

Where a caller is not callable without its database (the invoice engine, the Workspace
TemplateSender), its request body is mirrored here and named as such; the invoice engine to
outbound boundary is exercised end to end by `verify_whatsapp_catalog_payment_rail.py`.

What is stubbed: the Meta send itself (the message is captured instead), contact rows, the rate
limit, message records and media upload. Secrets Manager reads, DynamoDB/S3/CloudWatch writes,
any Lambda invoke other than a GET to the two read functions, and every `urllib` request are
refused, so the run cannot read a token, send a message or change a row. It prints template
structure and verdicts only, never a token or a customer value; the recipient is a placeholder.

    uv run --no-project --python 3.12 --with boto3==1.40.55 --with cryptography==50.0.2 \\
        python scripts/check_whatsapp_template_payloads_live.py

Exit 0 when every send matches its live template, 1 on any mismatch, 2 when the live definitions
or the code under test cannot be loaded.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import boto3

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
REGION = "us-east-1"
WABA_ID = "2094615664435155"
WABA_PHONE_ID = "1016149501586345"
DEFINITIONS_FUNCTION = "wecare-whatsapp-template-management:live"
BUSINESS_API_FUNCTION = "wecare-whatsapp-business-api:live"
READ_FUNCTIONS = frozenset({DEFINITIONS_FUNCTION, BUSINESS_API_FUNCTION})

#: Placeholders, never a real customer.
RECIPIENT = "+919876500099"
CONTACT_ID = "wa919876500099"
REFERENCE = "WD-PAY-VERIFYPAYLOAD01"
VAULT_FILE_ID = "verify-file-0001"
VAULT_OFFER_TOKEN = "verifyOfferToken0123456789abcdef"
OTP_CODE = "482913"

VARIABLE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class HarnessError(RuntimeError):
    """The code under test no longer has a seam this harness relies on."""


# ── guards: installed before any handler is imported ───────────────────────────────────────────

def _install_guards() -> None:
    """Refuse every side effect at the SDK and urllib layers, so a stub that misses cannot send."""
    boto3.setup_default_session(region_name=REGION)
    events = boto3.DEFAULT_SESSION.events

    def refuse(operation: str) -> Callable[..., None]:
        def handler(**_: Any) -> None:
            raise RuntimeError(f"verifier refused {operation}")
        return handler

    events.register("before-parameter-build.secrets-manager.GetSecretValue",
                    refuse("secretsmanager:GetSecretValue"))
    for operation in ("PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem",
                      "TransactWriteItems", "Scan"):
        events.register(f"before-parameter-build.dynamodb.{operation}",
                        refuse(f"dynamodb:{operation}"))
    for operation in ("PutObject", "DeleteObject", "DeleteObjects", "CopyObject"):
        events.register(f"before-parameter-build.s3.{operation}", refuse(f"s3:{operation}"))
    events.register("before-parameter-build.cloudwatch.PutMetricData",
                    refuse("cloudwatch:PutMetricData"))

    def guard_invoke(params: Dict[str, Any], **_: Any) -> None:
        name = str(params.get("FunctionName") or "")
        try:
            payload = json.loads(params.get("Payload") or b"{}")
        except (TypeError, ValueError):
            payload = {}
        method = str(payload.get("httpMethod") or "").upper() if isinstance(payload, dict) else ""
        if name not in READ_FUNCTIONS or method != "GET":
            raise RuntimeError(f"verifier refused lambda:Invoke {name} {method or 'non-GET'}")

    events.register("before-parameter-build.lambda.Invoke", guard_invoke)

    def no_urlopen(request: Any, *_: Any, **__: Any) -> None:
        url = getattr(request, "full_url", str(request))
        raise RuntimeError("verifier refused urlopen " + url.split("?", 1)[0][:80])

    urllib.request.urlopen = no_urlopen  # type: ignore[assignment]


def _manifest_env(function: str) -> Dict[str, str]:
    """A function's recorded non-secret environment, minus fingerprinted placeholders."""
    manifest = json.loads((ROOT / "config" / "lambda-env-manifest.json").read_text())
    values = manifest.get("functions", {}).get(function, {})
    return {k: str(v) for k, v in values.items() if not str(v).startswith("sha256:")}


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HarnessError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _patch(module: Any, name: str, value: Any) -> None:
    """Replace a seam, refusing to run if it has gone: an unpatched seam could reach Meta."""
    if not hasattr(module, name):
        raise HarnessError(f"{module.__name__}.{name} no longer exists; update this harness")
    setattr(module, name, value)


# ── live definitions ───────────────────────────────────────────────────────────────────────────

def _invoke_get(function: str, path: str, query: Dict[str, str]) -> Dict[str, Any]:
    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=function, InvocationType="RequestResponse",
        Payload=json.dumps({"httpMethod": "GET", "path": path,
                            "queryStringParameters": query}).encode())
    payload = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError(f"{function} {path} unavailable")
    body = payload.get("body")
    return json.loads(body) if isinstance(body, str) else (body or {})


def live_definitions(names: List[str]) -> Dict[str, Dict[str, Any]]:
    """name -> {name, status, category, sub_category, language, components} for `en` on WABA1."""
    listed = _invoke_get(BUSINESS_API_FUNCTION, "/wa-business/payment-templates/list",
                         {"wabaId": WABA_ID}).get("data") or []
    meta = {(r.get("name"), r.get("language")): r for r in listed if isinstance(r, dict)}
    templates = _invoke_get(DEFINITIONS_FUNCTION, "/whatsapp/templates",
                            {"wabaId": WABA_ID, "maxResults": "200"}).get("templates") or []
    found: Dict[str, Dict[str, Any]] = {}
    for row in templates:
        name, language = row.get("name"), row.get("language")
        if name in names and language == "en":
            listing = meta.get((name, language), {})
            found[name] = {"name": name, "language": language, "status": row.get("status"),
                           "category": row.get("category"),
                           "sub_category": listing.get("sub_category") or "",
                           "components": row.get("components") or [],
                           "fixedHeaderMedia": row.get("fixedHeaderMedia") or ""}
    return found


def _definition_parts(definition: Dict[str, Any]):
    components = definition.get("components") or []
    header = next((c for c in components if str(c.get("type")).upper() == "HEADER"), None)
    body = next((c for c in components if str(c.get("type")).upper() == "BODY"), {}) or {}
    footer = next((c for c in components if str(c.get("type")).upper() == "FOOTER"), {}) or {}
    buttons = next((c.get("buttons") for c in components
                    if str(c.get("type")).upper() == "BUTTONS"), None) or []
    return header, body, footer, buttons


# ── the check ──────────────────────────────────────────────────────────────────────────────────

def check_send(captured: Dict[str, Any], definition: Dict[str, Any]) -> List[str]:
    """Every reason Meta would refuse this captured send of this template; empty when none."""
    issues: List[str] = []
    payload = captured.get("payload") or {}
    if captured.get("sender") != WABA_PHONE_ID:
        issues.append(f"sender resolves to {captured.get('sender')!r}, not WABA1's phone")
    if payload.get("type") != "template":
        return issues + [f"message type is {payload.get('type')!r}, not template"]
    template = payload.get("template") or {}
    if template.get("name") != definition["name"]:
        issues.append(f"template name {template.get('name')!r}")
    language = (template.get("language") or {}).get("code")
    if language != definition["language"]:
        issues.append(f"language {language!r} != {definition['language']!r}")

    sent = template.get("components") or []
    headers = [c for c in sent if c.get("type") == "header"]
    bodies = [c for c in sent if c.get("type") == "body"]
    buttons: Dict[int, Dict[str, Any]] = {}
    for component in sent:
        if component.get("type") == "button":
            try:
                buttons[int(component.get("index"))] = component
            except (TypeError, ValueError):
                issues.append(f"button component with a non-numeric index {component.get('index')!r}")
    others = [c for c in sent if c.get("type") not in ("header", "body", "button")]
    def_header, def_body, def_footer, def_buttons = _definition_parts(definition)

    # Header.
    if def_header:
        fmt = str(def_header.get("format") or "").upper()
        params = (headers[0].get("parameters") or []) if headers else []
        if fmt in ("IMAGE", "VIDEO", "DOCUMENT"):
            kind = fmt.lower()
            media = (params[0].get(kind) or {}) if params else {}
            if not headers:
                issues.append(f"{fmt} header has no header parameter")
            elif len(params) != 1 or params[0].get("type") != kind or not (media.get("link") or media.get("id")):
                issues.append(f"header parameter is not one {kind} link or media id")
        elif fmt == "LOCATION":
            location = (params[0].get("location") or {}) if params else {}
            if not (len(params) == 1 and params[0].get("type") == "location"
                    and location.get("latitude") and location.get("longitude")):
                issues.append("LOCATION header needs one location parameter with latitude and longitude")
        elif fmt == "TEXT":
            wanted = len(VARIABLE.findall(def_header.get("text") or ""))
            if wanted != len(params):
                issues.append(f"TEXT header has {wanted} variable(s), send carries {len(params)}")
    elif headers:
        issues.append("header parameter sent for a template with no header")

    # Body.
    wanted = len(VARIABLE.findall(def_body.get("text") or ""))
    params = (bodies[0].get("parameters") or []) if bodies else []
    if wanted != len(params):
        issues.append(f"body has {wanted} variable(s), send carries {len(params)}")
    if any(p.get("type") != "text" or not str(p.get("text") or "").strip() for p in params):
        issues.append("a body parameter is not non-empty text")

    # Buttons.
    needed = set()
    for index, button in enumerate(def_buttons):
        kind = str(button.get("type") or "").upper()
        component = buttons.get(index)
        if kind == "URL" and "{{" in str(button.get("url") or ""):
            needed.add(index)
            values = (component or {}).get("parameters") or []
            if not component or component.get("sub_type") != "url":
                issues.append(f"button {index} (dynamic URL) has no url parameter")
            elif len(values) != 1 or values[0].get("type") != "text" or not values[0].get("text"):
                issues.append(f"button {index} url parameter is not one non-empty text")
        elif kind == "FLOW":
            needed.add(index)
            action = (((component or {}).get("parameters") or [{}])[0] or {}).get("action") or {}
            if not component or component.get("sub_type") != "flow":
                issues.append(f"button {index} (FLOW) has no flow component")
            elif not action.get("flow_token"):
                issues.append(f"button {index} flow component has no flow_token")
        elif kind == "ORDER_DETAILS":
            needed.add(index)
            if not component or component.get("sub_type") != "order_details":
                issues.append(f"button {index} (ORDER_DETAILS) has no order_details component")
            else:
                issues += _order_details_issues(component)
        elif kind == "COPY_CODE":
            needed.add(index)
            if not component or component.get("sub_type") != "copy_code":
                issues.append(f"button {index} (COPY_CODE) has no copy_code component")
        elif kind == "QUICK_REPLY" and component is not None:
            # Optional for Meta (a tap then returns the button text); when sent it must be one
            # non-empty payload, which is how the Vault offer names its document.
            needed.add(index)
            values = component.get("parameters") or []
            if component.get("sub_type") != "quick_reply":
                issues.append(f"button {index} (QUICK_REPLY) component is not sub_type quick_reply")
            elif len(values) != 1 or values[0].get("type") != "payload" or not values[0].get("payload"):
                issues.append(f"button {index} quick_reply parameter is not one non-empty payload")
    unexpected = sorted(set(buttons) - needed)
    if unexpected:
        issues.append(f"button component(s) at index {unexpected} the template does not take")

    # Authentication: the code is the body variable AND the copy-code URL suffix.
    if definition.get("category") == "AUTHENTICATION":
        body_code = str((params[0] if params else {}).get("text") or "")
        url_code = str(((buttons.get(0) or {}).get("parameters") or [{}])[0].get("text") or "")
        if not (body_code and body_code == url_code and body_code.isdigit() and len(body_code) <= 15):
            issues.append("OTP code must be the body variable and URL button 0, digits, <= 15")
        if def_footer.get("code_expiration_minutes") is None:
            issues.append("AUTHENTICATION template declares no code_expiration_minutes")

    # ORDER_STATUS sub-category and anything else.
    status_components = [c for c in others if c.get("type") == "order_status"]
    if definition.get("sub_category") == "ORDER_STATUS":
        order = ((((status_components or [{}])[0].get("parameters") or [{}])[0] or {})
                 .get("order_status") or {})
        if not (len(status_components) == 1 and order.get("reference_id")
                and (order.get("order") or {}).get("status")):
            issues.append("ORDER_STATUS template needs one order_status component with "
                          "reference_id and order.status")
        if (template.get("language") or {}).get("policy") != "deterministic":
            issues.append("ORDER_STATUS send must use language policy 'deterministic'")
    elif status_components:
        issues.append("order_status component sent for a template without sub_category ORDER_STATUS")
    stray = sorted({str(c.get("type")) for c in others if c.get("type") != "order_status"})
    if stray:
        issues.append(f"component type(s) the template does not take: {stray}")
    return issues


def _order_details_issues(component: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    action = ((component.get("parameters") or [{}])[0] or {}).get("action") or {}
    details = action.get("order_details") or {}
    missing = [k for k in ("reference_id", "type", "currency", "payment_settings", "order",
                           "total_amount") if not details.get(k)]
    if missing:
        issues.append(f"order_details is missing {missing}")
    if details.get("currency") and details.get("currency") != "INR":
        issues.append("order_details currency is not INR")
    settings = details.get("payment_settings") or [{}]
    gateway = (settings[0] or {}).get("payment_gateway") or {}
    if not (len(settings) == 1 and settings[0].get("type") == "payment_gateway"
            and gateway.get("type") == "razorpay" and gateway.get("configuration_name")):
        issues.append("payment_settings is not one Razorpay payment_gateway with a configuration")
    if details.get("type") == "physical-goods" and not (details.get("shipping_info") or {}).get("addresses"):
        issues.append("physical-goods order_details has no shipping addresses")
    total = details.get("total_amount") or {}
    if not (total.get("offset") == 100 and isinstance(total.get("value"), int) and total["value"] > 0):
        issues.append("total_amount is not positive integer paise with offset 100")
    items = (details.get("order") or {}).get("items") or []
    if not items or any(not (i.get("retailer_id") and i.get("name") and i.get("amount")
                             and i.get("quantity")) for i in items):
        issues.append("order items need retailer_id, name, amount and quantity")
    return issues


def check_registry(template: Any, definition: Dict[str, Any]) -> List[str]:
    """The registry's declared shape against the live template."""
    issues: List[str] = []
    if definition.get("status") != "APPROVED":
        issues.append(f"status {definition.get('status')}")
    if definition.get("category") != template.category:
        issues.append(f"category {definition.get('category')} != {template.category}")
    if template.sub_category and definition.get("sub_category") != template.sub_category:
        issues.append(f"sub_category {definition.get('sub_category')!r} != {template.sub_category!r}")
    def_header, _, _, def_buttons = _definition_parts(definition)
    live_header = str((def_header or {}).get("format") or "").lower() or None
    if live_header != template.header:
        issues.append(f"registry header {template.header!r} != live {live_header!r}")
    live_buttons = tuple(str(b.get("type") or "").lower() for b in def_buttons)
    if live_buttons != tuple(template.buttons):
        issues.append(f"registry buttons {template.buttons} != live {live_buttons}")
    return issues


# ── driving the production senders ─────────────────────────────────────────────────────────────

class _Captured:
    def __init__(self) -> None:
        self.sends: List[Dict[str, Any]] = []


class _FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_item(self, **_: Any) -> Dict[str, Any]:
        return {}

    def query(self, **_: Any) -> Dict[str, Any]:
        return {"Items": []}

    def __getattr__(self, attr: str) -> Any:
        raise RuntimeError(f"verifier refused DynamoDB {attr} on {self.name}")


class _FakeDynamo:
    def Table(self, name: str) -> _FakeTable:  # noqa: N802 - boto3 resource spelling
        return _FakeTable(name)


class _NoSecrets:
    def get_secret_value(self, **_: Any) -> None:
        raise RuntimeError("verifier refused secretsmanager:GetSecretValue")


def load_outbound(captured: _Captured) -> Any:
    os.environ.update(_manifest_env("wecare-outbound-whatsapp"))
    os.environ.update({"SEND_MODE": "LIVE", "LOG_LEVEL": "ERROR", "AWS_REGION": REGION})
    os.environ.pop("WA_LIVE_SMOKE_TEST", None)
    sys.path.insert(0, str(FUNCTIONS / "shared"))
    outbound = _load("verify_outbound", FUNCTIONS / "messaging" / "outbound-whatsapp" / "handler.py")
    contacts: Dict[str, Dict[str, Any]] = {}

    def contact(contact_id: str) -> Optional[Dict[str, Any]]:
        return contacts.get(contact_id)

    def send_direct_api(phone_number_id: str, message_json: str) -> Dict[str, Any]:
        try:
            sender = outbound._resolve_meta_phone_id(phone_number_id)
        except Exception as error:  # noqa: BLE001 - an unresolvable sender is the finding
            sender = type(error).__name__
        captured.sends.append({"sender": sender, "payload": json.loads(message_json)})
        return {"messageId": "wamid.VERIFIER", "waId": ""}

    _patch(outbound, "dynamodb", _FakeDynamo())
    _patch(outbound, "secrets_client", _NoSecrets())
    _patch(outbound, "_get_contact", contact)
    _patch(outbound, "_get_or_create_contact_by_phone",
           lambda phone: contacts.get(CONTACT_ID) or {"id": CONTACT_ID, "phone": phone})
    _patch(outbound, "_check_rate_limit", lambda *_: True)
    _patch(outbound, "_get_latest_inbound_wamid", lambda *_, **__: "")
    _patch(outbound, "_send_typing_indicator", lambda *_, **__: None)
    _patch(outbound, "_store_message_record", lambda *_, **__: None)
    _patch(outbound, "_emit_delivery_metric", lambda *_, **__: None)
    _patch(outbound, "_enrich_contact_identity", lambda *_, **__: None)
    _patch(outbound, "_upload_media",
           lambda media_file, *_, **__: (media_file, "verifier-media-id", None))
    _patch(outbound, "_send_direct_api", send_direct_api)
    outbound._verify_contacts = contacts
    return outbound


def send_outbound(outbound: Any, captured: _Captured, body: Dict[str, Any], *,
                  window_open: bool) -> Dict[str, Any]:
    outbound._verify_contacts[CONTACT_ID] = {
        "id": CONTACT_ID, "contactId": CONTACT_ID, "phone": RECIPIENT,
        "lastInboundMessageAt": int(time.time()) if window_open else 0}
    before = len(captured.sends)
    response = outbound.handler({"body": json.dumps(body)}, None)
    sends = captured.sends[before:]
    return {"status": response.get("statusCode"), "body": response.get("body"),
            "send": sends[-1] if sends else None, "count": len(sends)}


def otp_send(captured: _Captured) -> Dict[str, Any]:
    """customer-whatsapp-auth `_send_otp` into whatsapp-business-api's send-template route."""
    os.environ.update(_manifest_env("wecare-customer-whatsapp-auth"))
    auth = _load("verify_customer_whatsapp_auth",
                 FUNCTIONS / "auth" / "customer-whatsapp-auth" / "handler.py")
    sys.path.insert(0, str(FUNCTIONS / "messaging" / "whatsapp-business-api"))
    api = _load("verify_business_api", FUNCTIONS / "messaging" / "whatsapp-business-api" / "handler.py")
    _patch(api, "secrets_client", _NoSecrets())
    invoked: List[Dict[str, Any]] = []

    class _Lambda:
        def invoke(self, **kwargs: Any) -> Dict[str, Any]:
            event = json.loads(kwargs["Payload"])
            invoked.append({"function": kwargs.get("FunctionName"), "event": event})
            answer = api._route_send_message(event["path"], json.loads(event["body"]))
            return {"Payload": io.BytesIO(json.dumps(answer).encode())}

    def graph(endpoint: str, method: str = "GET", payload: Any = None, **_: Any) -> Dict[str, Any]:
        captured.sends.append({"sender": endpoint.split("/", 1)[0], "payload": payload,
                               "endpoint": endpoint, "method": method})
        return {"messages": [{"id": "wamid.VERIFIER"}], "contacts": [{"user_id": ""}]}

    _patch(auth, "_lambda", _Lambda())
    _patch(api, "_graph_api", graph)
    route = auth.WABA_ROUTES.get(WABA_ID)
    if not route:
        raise HarnessError("customer-whatsapp-auth has no WABA1 OTP route")
    before = len(captured.sends)
    auth._send_otp(RECIPIENT, OTP_CODE, route)
    sends = captured.sends[before:]
    return {"send": sends[-1] if sends else None, "count": len(sends),
            "senderFunction": auth.SENDER_FUNCTION, "ttlSeconds": auth.OTP_TTL_SECONDS,
            "invokedFunction": (invoked[-1] if invoked else {}).get("function")}


def main() -> int:
    _install_guards()
    sys.path.insert(0, str(FUNCTIONS / "shared"))
    from lambda_utils import template_media, whatsapp_templates  # noqa: E402
    from lambda_utils.ecommerce import review_token, wa_order_status, wa_payment_request  # noqa: E402

    names = [t.name for t in whatsapp_templates.ALL]
    try:
        definitions = live_definitions(names)
    except Exception as error:  # noqa: BLE001 - a read failure is its own exit code
        print(f"ERROR could not read the live template definitions: {type(error).__name__}")
        return 2
    captured = _Captured()
    try:
        outbound = load_outbound(captured)
    except Exception as error:  # noqa: BLE001
        print(f"ERROR could not load outbound-whatsapp: {type(error).__name__}: {error}")
        return 2

    sender = wa_payment_request.PHONE_NUMBER_ID_1
    person = {"contactId": CONTACT_ID, "recipientPhone": RECIPIENT, "phoneNumberId": sender}

    def flow_index(name: str) -> int:
        _, _, _, buttons = _definition_parts(definitions.get(name, {}))
        return next((i for i, b in enumerate(buttons) if str(b.get("type")).upper() == "FLOW"), 0)

    # (registry template, the caller whose request body this is, body, customer window open)
    cases = [
        (whatsapp_templates.PAY, "invoice-engine send_payment_link -> outbound checkout path", {
            **person, "isCheckoutTemplate": True, "isTemplate": True,
            "templateName": whatsapp_templates.PAY.name, "templateParams": [],
            "checkoutOrderDetails": {
                "reference_id": REFERENCE, "type": "digital-goods", "currency": "INR",
                "payment_configuration": os.environ.get("EXPECTED_CONFIGURATION_NAME", ""),
                "total_amount": {"value": 4900, "offset": 100},
                "order": {"status": "pending",
                          "items": [{"retailer_id": "verify-item", "name": "Verification item",
                                     "amount": {"value": 4900, "offset": 100}, "quantity": 1}],
                          "subtotal": {"value": 4900, "offset": 100},
                          "tax": {"value": 0, "offset": 100, "description": "GST"}}}}, False),
        (whatsapp_templates.INVOICE, "invoice-engine send_invoice_whatsapp (mirrored body)", {
            **person, "content": "", "isTemplate": True,
            "templateName": whatsapp_templates.INVOICE.name, "templateParams": [],
            "templateHeaderMedia": "secure/d/public/Invoice/customer_invoice/verify.png",
            "templateHeaderType": "image",
            "templateFlowButton": {"index": 0, "flowToken": review_token.mint()}}, False),
        (whatsapp_templates.ORDER_STATUS, "invoice-engine send_order_status, window closed", {
            **person, "orderStatusDetails": {
                "reference_id": REFERENCE, "order_status": "processing",
                "description": wa_order_status.default_body("processing")}}, False),
        (whatsapp_templates.DOWNLOAD, "paid_vault / catalog_services via download_send_fields", {
            **person, "isTemplate": True, "templateParams": [],
            **whatsapp_templates.download_send_fields(VAULT_FILE_ID)}, False),
        (whatsapp_templates.LEAVE_REVIEW, "Workspace TemplateSender (mirrored body)", {
            **person, "isTemplate": True, "templateName": whatsapp_templates.LEAVE_REVIEW.name,
            "templateParams": [], "headerType": "image",
            "headerMedia": template_media.fixed_image_header(whatsapp_templates.LEAVE_REVIEW.name),
            "flowButton": {"index": flow_index(whatsapp_templates.LEAVE_REVIEW.name)}}, True),
        (whatsapp_templates.LOCATION_PIN, "Workspace TemplateSender (mirrored body)", {
            **person, "isTemplate": True, "templateName": whatsapp_templates.LOCATION_PIN.name,
            "templateParams": [], "headerType": "location",
            "headerLocation": {"latitude": "22.5726", "longitude": "88.3639",
                               "name": "WECARE.DIGITAL", "address": "Kolkata"}}, True),
        (whatsapp_templates.VAULT_OFFER, "business-api catalog_services sendOffer via vault_offer_send_fields", {
            **person, **whatsapp_templates.vault_offer_send_fields(
                "Verification document", VAULT_OFFER_TOKEN)}, False),
    ]

    problems = 0

    def report(template: Any, caller: str, issues: List[str], summary: str) -> None:
        nonlocal problems
        verdict = "OK  " if not issues else "FAIL"
        problems += bool(issues)
        print(f"{verdict} {template.name:40} {caller}")
        print(f"       sends: {summary}")
        for issue in issues:
            print(f"       - {issue}")

    def summary_of(send: Optional[Dict[str, Any]]) -> str:
        components = ((send or {}).get("payload") or {}).get("template", {}).get("components") or []
        return ", ".join(f"{c.get('type')}{'/' + c['sub_type'] if c.get('sub_type') else ''}"
                         f"[{c.get('index')}]" if c.get("type") == "button" else str(c.get("type"))
                         for c in components) or "(no components)"

    for template, caller, body, window_open in cases:
        definition = definitions.get(template.name)
        if not definition:
            report(template, caller, ["no 'en' definition on WABA1"], "-")
            continue
        issues = check_registry(template, definition)
        try:
            result = send_outbound(outbound, captured, body, window_open=window_open)
        except Exception as error:  # noqa: BLE001 - a crash is a failed construction
            report(template, caller, issues + [f"builder raised {type(error).__name__}: {error}"], "-")
            continue
        if result["count"] != 1 or not result["send"]:
            detail = str(result.get("body") or "")[:160]
            report(template, caller, issues + [f"no send built: HTTP {result['status']} {detail}"], "-")
            continue
        report(template, caller, issues + check_send(result["send"], definition),
               summary_of(result["send"]))

    # The OTP is sent by customer-whatsapp-auth through the business API, not by outbound.
    definition = definitions.get(whatsapp_templates.OTP.name)
    caller = "customer-whatsapp-auth _send_otp -> business-api /messages/send/template"
    if not definition:
        report(whatsapp_templates.OTP, caller, ["no 'en' definition on WABA1"], "-")
    else:
        issues = check_registry(whatsapp_templates.OTP, definition)
        try:
            result = otp_send(captured)
        except Exception as error:  # noqa: BLE001
            report(whatsapp_templates.OTP, caller, issues + [f"sender raised {type(error).__name__}: {error}"], "-")
        else:
            _, _, footer, _ = _definition_parts(definition)
            minutes = footer.get("code_expiration_minutes")
            if minutes is not None and int(result["ttlSeconds"]) != int(minutes) * 60:
                issues.append(f"OTP_TTL_SECONDS {result['ttlSeconds']} != template expiry {minutes} min")
            if result["invokedFunction"] != BUSINESS_API_FUNCTION:
                issues.append(f"OTP sender function is {result['invokedFunction']!r}")
            if result["count"] != 1 or not result["send"]:
                issues.append("no send built")
                report(whatsapp_templates.OTP, caller, issues, "-")
            else:
                report(whatsapp_templates.OTP, caller, issues + check_send(result["send"], definition),
                       summary_of(result["send"]))

    total = len(cases) + 1
    print(f"\n{total - problems}/{total} template sends match their live WABA1 definitions "
          "(nothing was sent)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
