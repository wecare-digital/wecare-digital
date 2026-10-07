"""R7.4 for Phase O-1: a service CANNOT be charged twice, demonstrated by enumeration.

(a) AST: the four new modules import no money mover and only the dispatcher invokes a Lambda.
(b) A recording fake of every provider seam on the prepare path enumerates EXACTLY the calls a
    services basket makes -- as a set equality -- and a second prepare on the same request key
    makes zero further Razorpay order creates.
(c) A captured payment delivered 3x by the webhook and once via verify-callback yields exactly
    one PAYMENTATTEMPT# claim, one ORDER pointer, one REQ#, and the Razorpay fake records only
    reads -- no capture, refund or payment-configuration call exists to record.
(d) The enumeration is not vacuous.
(e) The new role names no Razorpay or Wix credential path.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import pathlib
import re
import sys
from unittest.mock import patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import contribution_wix  # noqa: E402
from contribution_env import ATTEMPTS_TABLE, KEYS_TABLE, body_of, make_env, prepare_event  # noqa
from contribution_wix import STORES_APP_ID, ContributionWix  # noqa: E402
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from service_requests_fake_dynamo import RequestTable  # noqa: E402

from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import order_creation, order_keys  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"

NEW_MODULES = (
    "amplify/functions/ecommerce/service-requests/handler.py",
    "amplify/functions/shared/lambda_utils/ecommerce/service_request_store.py",
    "amplify/functions/shared/lambda_utils/ecommerce/service_requests.py",
    "amplify/functions/shared/lambda_utils/ecommerce/service_request_dispatch.py",
)
BANNED_IMPORTS = {"razorpay_orders", "razorpay_verify", "wix_ecom", "wix_writeback",
                  "finalization", "order_creation", "urllib", "requests", "http"}


def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(part for part in (node.module or "").split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
    return names


@pytest.mark.parametrize("relative", NEW_MODULES)
def test_a_the_new_modules_import_no_money_mover(relative):
    source = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not _imports(tree) & BANNED_IMPORTS
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("secretsmanager" in value for value in literals)
    invokes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "invoke"]
    if relative.endswith("service_request_dispatch.py"):
        assert len(invokes) == 1
        assert "wecare-service-requests:live" in literals
    else:
        assert invokes == []


# ── (b) the prepare path, enumerated ─────────────────────────────────────────

def _service_line():
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": PRODUCT,
                                 "options": {"variantId": SUBMIT}}, "quantity": 1}


def _endpoint_shape(path: str) -> str:
    return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "{id}", path)


def test_b_the_prepare_path_makes_exactly_the_enumerated_calls(monkeypatch):
    wix = ContributionWix()
    monkeypatch.setitem(contribution_wix.UNIT_RUPEES, PRODUCT, 99)
    wix.variants[PRODUCT] = [SUBMIT]
    h, fake, wix = make_env(monkeypatch, wix=wix)
    event = prepare_event([_service_line()],
                          serviceIntentId="01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f")
    response = h.handler(event, None)
    assert response["statusCode"] == 200, body_of(response)
    assert {(method, _endpoint_shape(path)) for method, path in wix.calls} == {
        ("GET", "/stores/v3/products/{id}"),        # resolve the line's variant
        ("POST", "/ecom/v2/carts"),                 # CustomerCart.ensure (new cart)
        ("POST", "/ecom/v2/carts/{id}/calculate"),  # delivery options + the price
        ("POST", "/ecom/v2/carts/{id}/set-delivery-method"),  # the one Wix-resolved method
    }
    assert len(h.gateway_orders) == 1               # Razorpay orders.create x1
    # A second prepare with the SAME requestKey creates NO second gateway order. Its answer is
    # either a resume (200) or INTENT_CHANGED (409): the delivery-method write bumps Wix's cart
    # revision, which `website_checkout` documents as the case its fingerprint refuses -- the
    # same behaviour a contribution basket has. Either way nothing payable is minted.
    again = h.handler(event, None)
    assert again["statusCode"] in (200, 409), body_of(again)
    assert body_of(again).get("reason") in (None, "INTENT_CHANGED")
    assert len(h.gateway_orders) == 1
    assert len(fake.all_rows(ATTEMPTS_TABLE)) == 1


# ── (c) captured 3x via webhook + once via verify -> one of everything ────────

class RecordingRazorpay:
    """Every method a Razorpay client could expose. Only reads may ever be called."""

    def __init__(self, amount):
        self.amount = amount
        self.calls = []

    def verifier(self, _reference):
        self.calls.append("payment.fetch")
        return True, "pay_LIVE0000000001", self.amount, "INR"

    def __getattr__(self, name):
        def forbidden(*_a, **_k):
            self.calls.append(name)
            raise AssertionError(f"money-moving call {name!r} reached the provider")
        return forbidden


class LambdaToReceiver:
    """The webhook's lambda client, delivering each hint synchronously to the real receiver."""

    def __init__(self, receiver):
        self.receiver = receiver
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        self.receiver.handler(json.loads(kwargs["Payload"].decode("utf-8")), None)
        return {"StatusCode": 202}


def test_c_a_capture_delivered_four_times_makes_one_claim_one_order_one_request(monkeypatch):
    keys = FakeDynamo(keys={"stack-wecare-digital-WixOrderIds": "orderId"}).Table(
        "stack-wecare-digital-WixOrderIds")
    requests = RequestTable()
    identity = customer_auth.CustomerIdentity(customer_id="sub-1", phone="+910000000000",
                                              subject="sub-1")
    intent = store.request_intent(requests, identity, "SUBMIT_REQUEST")
    reference = order_keys.allocate_payment_reference(
        keys, payment_attempt_id="att-1",
        extra={"customerId": "sub-1", "amountPaise": 10193, "currency": "INR",
               "serviceLine": {"kind": "SUBMIT_REQUEST", "variantId": SUBMIT, "paise": 9900,
                               "intentId": intent["intentId"]}})

    spec = importlib.util.spec_from_file_location(
        "service_requests_receiver", ROOT / "amplify/functions/ecommerce/service-requests/"
        "handler.py")
    receiver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receiver)
    tables = {receiver.SERVICE_REQUESTS_TABLE: requests, receiver.COMMERCE_KEYS_TABLE: keys}
    monkeypatch.setattr(receiver, "_table", lambda name: tables[name])

    webhook_dir = str(ROOT / "amplify/functions/payments/razorpay-webhook")
    for stale in [m for m in sys.modules if m == "handler" or m.startswith("handler.")]:
        del sys.modules[stale]
    sys.path.insert(0, webhook_dir)
    try:
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            with patch("boto3.resource"), patch("boto3.client"):
                webhook = importlib.import_module("handler")
    finally:
        sys.path.remove(webhook_dir)
    razorpay = RecordingRazorpay(10193)
    lam = LambdaToReceiver(receiver)
    payload = {"id": "pay_LIVE0000000001", "order_id": "order_ABC", "amount": 10193,
               "currency": "INR"}
    outcomes = []
    with patch.object(webhook, "dynamodb") as ddb, patch.object(webhook, "lambda_client", lam):
        ddb.Table.return_value = keys
        with patch("lambda_utils.integrations.razorpay_verify.verifier_for_event",
                   return_value=razorpay.verifier):
            for delivery in range(3):
                outcomes.append(webhook._create_order_for_captured_payment(
                    payload, reference, f"req-{delivery}"))
    # The verify-callback path reconciles through the same `reconcile_payment`.
    verify = order_creation.reconcile_payment(
        table=keys, reference_id=reference, verify_payment=razorpay.verifier,
        load_attempt=lambda ref: order_keys.resolve_payment_reference(keys, ref))
    store.activate(requests, keys, reference_id=reference, caller_customer_id="sub-1")

    assert [o["outcome"] for o in outcomes] == ["ORDER_CREATED", "ORDER_ALREADY_EXISTS",
                                                "ORDER_ALREADY_EXISTS"]
    assert verify.outcome == "ORDER_ALREADY_EXISTS"
    claims = [k for k in keys.rows if str(k).startswith("PAYMENTATTEMPT#")]
    assert len(claims) == 1
    assert len([k for k in requests.rows if str(k).startswith("REQ#")]) == 1
    assert len([k for k in requests.rows if str(k).startswith("ORDER#")]) == 1
    assert len(lam.calls) == 3
    assert set(razorpay.calls) <= {"payment.fetch"}
    assert razorpay.calls, "the verifier must actually have been consulted"


# ── (d) and (e) ───────────────────────────────────────────────────────────────

def test_d_the_enumeration_itself_is_not_vacuous():
    probe = ast.parse("from lambda_utils.integrations import razorpay_orders\n"
                      "client.invoke(FunctionName='x')\n")
    assert _imports(probe) & BANNED_IMPORTS == {"razorpay_orders"}
    assert [n for n in ast.walk(probe) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "invoke"]
    rp = RecordingRazorpay(1)
    with pytest.raises(AssertionError):
        rp.refund()
    assert rp.calls == ["refund"]


def test_e_the_new_role_names_no_provider_credential_path():
    spec = importlib.util.spec_from_file_location(
        "prov_sr_e", ROOT / "scripts/provision_service_requests.py")
    prov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prov)
    text = json.dumps(prov.expected_role_policy("123456789012")).lower()
    for needle in ("secretsmanager", "razorpay", "wecare/wix", "kms", "lambda:invoke"):
        assert needle not in text
