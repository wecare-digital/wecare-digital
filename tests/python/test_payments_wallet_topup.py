"""PAY-3: a wallet top-up credits only a payment made on the intent's own payment link, once."""
import ast
import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError

import lambda_utils
from lambda_utils.ecommerce import order_keys

_FUNCTIONS = Path(__file__).resolve().parents[2] / "amplify/functions"
_WEBHOOK = _FUNCTIONS / "payments/razorpay-webhook/handler.py"
_ONBOARDING = _FUNCTIONS / "messaging/partner-onboarding/handler.py"
REF = "WD-PAY-TOPUP001"


def _conditional():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "Op")


class Keys:
    """CommerceKeys rows with the conditions order_keys uses on this path."""

    def __init__(self):
        self.rows = {}
        self.fail_updates = False

    def put_item(self, *, Item, ConditionExpression):
        if Item["orderId"] in self.rows:
            raise _conditional()
        self.rows[Item["orderId"]] = dict(Item)

    def get_item(self, *, Key, ConsistentRead=False):
        row = self.rows.get(Key["orderId"])
        return {"Item": dict(row)} if row is not None else {}

    def update_item(self, *, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeValues, ExpressionAttributeNames=None):
        if self.fail_updates:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Op")
        row = self.rows.get(Key["orderId"])
        guarded = "paymentLinkId" if "paymentLinkId" in ConditionExpression else "creditedPaymentId"
        if row is None or guarded in row:
            raise _conditional()
        if guarded == "paymentLinkId":
            row["paymentLinkId"] = ExpressionAttributeValues[":link"]
        else:
            row["creditedPaymentId"] = ExpressionAttributeValues[":pid"]
            row["creditStatus"] = ExpressionAttributeValues[":credited"]


def test_link_binding_and_credit_flip_happen_once():
    keys = Keys()
    order_keys.reserve_topup_intent(keys, reference_id=REF, waba_id="w1", amount_paise=50000)
    assert order_keys.bind_topup_payment_link(keys, reference_id=REF, payment_link_id="plink_1")
    assert order_keys.bind_topup_payment_link(keys, reference_id=REF, payment_link_id="plink_1")
    assert not order_keys.bind_topup_payment_link(keys, reference_id=REF, payment_link_id="plink_2")
    assert order_keys.mark_topup_intent_credited(keys, reference_id=REF, payment_id="pay_1") == (True, "pay_1")
    assert order_keys.mark_topup_intent_credited(keys, reference_id=REF, payment_id="pay_2") == (False, "pay_1")
    assert not order_keys.bind_topup_payment_link(keys, reference_id="WD-PAY-NOPE0001",
                                                  payment_link_id="plink_9")


# ── partner-onboarding: the created link id is stored on the intent ──────────────

def _topup_order_function(namespace):
    tree = ast.parse(_ONBOARDING.read_text())
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_do_topup_order")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(_ONBOARDING), "exec"), namespace)
    return namespace["_do_topup_order"]


@pytest.mark.parametrize("bind_fails", [False, True])
def test_topup_order_stores_the_link_id_before_returning_the_url(bind_fails):
    keys = Keys()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(_request, timeout):
        if bind_fails:
            keys.fail_updates = True
        return Response(json.dumps({"id": "plink_1", "short_url": "https://rzp.io/x"}).encode())

    namespace = {
        "_auth_ctx": lambda _e: {"isAdmin": True, "wabaId": "", "username": "staff"},
        "_razorpay_creds": lambda: ("key", "secret"),
        "cors_response": lambda code, body, _origin: {"statusCode": code, "body": body},
        "boto3": SimpleNamespace(resource=lambda *_a, **_k: SimpleNamespace(Table=lambda _n: keys)),
        "REGION": "us-east-1", "json": json, "logger": SimpleNamespace(error=lambda *_a: None),
        "urllib": SimpleNamespace(request=SimpleNamespace(Request=lambda *a, **k: None, urlopen=urlopen),
                                  error=types.SimpleNamespace(HTTPError=type("HTTPError", (Exception,), {}))),
    }
    response = _topup_order_function(namespace)({}, {"wabaId": "w1", "amount": 500}, "")
    intents = [row for key, row in keys.rows.items() if key.startswith(order_keys.TOPUP_INTENT_PREFIX)]
    assert len(intents) == 1
    if bind_fails:
        assert response["statusCode"] == 502 and "shortUrl" not in response["body"]
        assert "paymentLinkId" not in intents[0]
    else:
        assert response == {"statusCode": 200, "body": {"success": True,
                                                        "shortUrl": "https://rzp.io/x", "id": "plink_1"}}
        assert intents[0]["paymentLinkId"] == "plink_1"


# ── razorpay-webhook: the credit gate ────────────────────────────────────────────

@pytest.fixture
def topup(monkeypatch):
    def unexpected_aws(*_args, **_kwargs):
        raise AssertionError("no AWS in this test")

    class NoAws:
        def __getattr__(self, _name):
            return unexpected_aws

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_kw: NoAws())
    monkeypatch.setattr(boto3, "client", lambda *_a, **_kw: NoAws())
    spec = importlib.util.spec_from_file_location("razorpay_webhook_topup_under_test", _WEBHOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    keys = Keys()
    order_keys.reserve_topup_intent(keys, reference_id=REF, waba_id="w1", amount_paise=50000)
    order_keys.bind_topup_payment_link(keys, reference_id=REF, payment_link_id="plink_1")
    monkeypatch.setattr(module, "dynamodb", SimpleNamespace(Table=lambda _n: keys))
    parked, credits = [], []
    monkeypatch.setattr(module, "_quarantine_unverified_capture",
                        lambda ref, pid, _o, _r: parked.append(pid))
    billing = types.ModuleType("lambda_utils.partner_billing")
    billing.topup = lambda waba, amount, **kw: credits.append((waba, str(amount))) or {"balance": 1}
    monkeypatch.setitem(sys.modules, "lambda_utils.partner_billing", billing)
    monkeypatch.setattr(lambda_utils, "partner_billing", billing, raising=False)

    from lambda_utils.integrations import razorpay_verify
    provider = {"payments": {"pay_1": (True, 50000, "INR", "order_link")},
                "link": {"id": "plink_1", "order_id": "order_link",
                         "payments": [{"payment_id": "pay_1", "status": "captured"}]}}
    monkeypatch.setattr(razorpay_verify, "payment_capture_details",
                        lambda pid: provider["payments"].get(pid, (False, 0, "", "")))
    monkeypatch.setattr(razorpay_verify, "payment_link_entity", lambda _lid: provider["link"])
    return module, keys, provider, parked, credits


def _payment(payment_id="pay_1"):
    return {"id": payment_id, "amount": 50000,
            "notes": {"purpose": "wallet_topup", "wabaId": "w1", "referenceId": REF}}


def test_credit_once_for_the_links_own_payment(topup):
    module, _keys, _provider, parked, credits = topup
    first = module._handle_wallet_topup_captured(_payment(), "req")
    assert first["settled"] and not first["duplicate"]
    again = module._handle_wallet_topup_captured(_payment(), "req")
    assert again["settled"] and again["duplicate"]
    assert credits == [("w1", "500")] and parked == []


def test_a_same_amount_payment_from_elsewhere_credits_nothing(topup):
    module, _keys, provider, parked, credits = topup
    provider["payments"]["pay_other"] = (True, 50000, "INR", "order_other")
    result = module._handle_wallet_topup_captured(_payment("pay_other"), "req")
    assert result == {"settled": False} and credits == [] and parked == ["pay_other"]


def test_a_second_link_payment_cannot_credit_the_intent_again(topup):
    module, _keys, provider, parked, credits = topup
    provider["payments"]["pay_2"] = (True, 50000, "INR", "order_link")
    provider["link"]["payments"].append({"payment_id": "pay_2", "status": "captured"})
    module._handle_wallet_topup_captured(_payment(), "req")
    assert module._handle_wallet_topup_captured(_payment("pay_2"), "req") == {"settled": False}
    assert credits == [("w1", "500")] and parked == ["pay_2"]


def test_an_intent_without_a_link_is_parked(topup):
    module, keys, _provider, parked, credits = topup
    keys.rows[order_keys.TOPUP_INTENT_PREFIX + REF].pop("paymentLinkId")
    assert module._handle_wallet_topup_captured(_payment(), "req") == {"settled": False}
    assert credits == [] and parked == ["pay_1"]


def test_crash_between_flip_and_claim_is_finished_on_redelivery(topup):
    module, keys, _provider, _parked, credits = topup
    order_keys.mark_topup_intent_credited(keys, reference_id=REF, payment_id="pay_1")
    result = module._handle_wallet_topup_captured(_payment(), "req")
    assert result["settled"] and not result["duplicate"] and credits == [("w1", "500")]


def test_provider_outage_raises_so_razorpay_retries(topup, monkeypatch):
    module, _keys, _provider, parked, credits = topup
    from lambda_utils.integrations import razorpay_verify

    def down(_pid):
        raise razorpay_verify.RazorpayUnavailable("down")

    monkeypatch.setattr(razorpay_verify, "payment_capture_details", down)
    with pytest.raises(razorpay_verify.RazorpayUnavailable):
        module._handle_wallet_topup_captured(_payment(), "req")
    assert credits == [] and parked == []
