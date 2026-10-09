"""One purchase, one review invitation - and never at the cost of replaying a captured payment.

F-2. Three senders of `wecare_leave_review` exist, claimed in three unrelated namespaces that
cannot see each other: the webhook arm claims `INVOICEDELIVERY#<invoiceId>#review`, the native
Submit Request arm claims a `requestReviewStatus` attribute on the ServiceRequests row, and the
native Vault arm claims `vaultReviewStatus` on that same row. Nothing correlates them, so a native
catalogue purchase was asked twice.

The webhook arm is the one that yields. The native trigger asks AFTER the service was actually
delivered; the webhook asks at capture, before any fulfilment. So the webhook now resolves the
`PAYREF#` row and skips when it carries `nativeCatalogService`.

WHY HALF THIS FILE IS ABOUT THE FAILURE BRANCH
----------------------------------------------
That resolve is a DynamoDB read inserted into the one block the webhook documents as FAIL-OPEN,
on the captured-payment path. `order_keys._read_row` deliberately raises `OrderIdentityUnavailable`
on every storage error rather than reporting absence, and an exception escaping this block reaches
the handler's top-level `except`, returns 500, and leaves the idempotency lease uncompleted - which
is precisely what makes Razorpay REPLAY a captured payment. So two cases below are worth more than
the dedup itself:

* `test_an_unreadable_payment_reference_does_not_fail_the_capture` - a throttle must fail OPEN,
  defaulting to `native = False`, i.e. we SEND the review. A duplicate nudge during a storage
  outage is strictly preferable to a replayed capture, and inverting that default to "skip on
  error" would make a transient throttle silently suppress a legitimate website review request.
* `test_an_error_outside_the_storage_wrapper_is_not_swallowed` - the catch is
  `OrderIdentityUnavailable` SPECIFICALLY. Every storage failure is that type by construction, so
  the narrow catch has no storage blind spot; it is deliberately not total over programming errors,
  so a later tidy-up to `except Exception` fails here. A storage outage must fail open on a
  captured payment; a logic bug must be loud.

TECHNIQUE
---------
Both legs run against ONE shared fake commerce-keys/ServiceRequests pair, and both outbound
boundaries are spied: `lambda_client.invoke` (the only way either leg sends anything) and
`urllib.request.urlopen`, which is asserted never to be called at all. The review count is read
off the recorded invokes rather than off either leg's return value - a leg that reported
"skipped" after already invoking would pass a return-value test.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import pathlib
import sys
import time
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from service_requests_fake_dynamo import KeysTable, RequestTable  # noqa: E402
from test_service_request_store import ALICE, pay, who  # noqa: E402
from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402

WEBHOOK_PATH = ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"
WHATSAPP_DIR = ROOT / "amplify/functions/messaging/whatsapp-business-api"

REVIEW_TEMPLATE = "wecare_leave_review"
INVOICE_ID = "INV-NATIVE-1"
PAYMENT_ID = "pay_LIVE0000000001"
CONTACT = "+910000000000"
REQUEST = "req-review-dedup-1"

# The customer's ORIGINAL order, which a Submit Request is now frozen against: `request_intent`
# refuses a SUBMIT_REQUEST whose `original_order` is not a dict owned by the caller carrying both
# an order id and a payment reference. It is NOT the service order `pay()` seeds below - a Submit
# Request is bought against an earlier purchase, and the two order ids stay separate.
ORIGINAL_ORDER = {"orderId": "order-parent-review-dedup-1", "customerId": ALICE,
                  "referenceId": "WD-PAY-REF00000000900",
                  "orderNumber": "WD-ORD-PARENT01"}


def _load_webhook():
    """The real webhook handler, BY PATH under a unique module name, with no AWS at import."""
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        spec = importlib.util.spec_from_file_location(
            "wecare_razorpay_webhook_handler_f2", WEBHOOK_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


webhook = _load_webhook()


@pytest.fixture
def native_flow(monkeypatch):
    """The real `flows.paid_submit_request`, whose `send_review` is the arm that keeps asking."""
    monkeypatch.syspath_prepend(str(WHATSAPP_DIR))
    return importlib.import_module("flows.paid_submit_request")


# ══════════════════════════════════════════════════════════════════════════════
# The two spied boundaries
# ══════════════════════════════════════════════════════════════════════════════

def _payload_stream(obj):
    stream = MagicMock()
    stream.read.return_value = json.dumps(obj).encode("utf-8")
    return stream


class _Outbound:
    """Every `invoke` either leg makes, with the review sends counted off the real payloads."""

    def __init__(self) -> None:
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        name = str(kwargs.get("FunctionName") or "")
        if "invoice-engine" in name:
            # The webhook's step 1. `deduplicated: True` is the native leg's normal answer (the
            # payment-link send already wrote `referenceId` onto the invoice), and it keeps the
            # asset render out of a test about review sends.
            return {"Payload": _payload_stream({"body": json.dumps(
                {"invoiceId": INVOICE_ID, "invoiceNumber": "WD/25-26/0007",
                 "deduplicated": True})})}
        return {"Payload": _payload_stream({"statusCode": 200})}

    @property
    def reviews(self):
        return [call for call in self.calls
                if REVIEW_TEMPLATE in str(call.get("Payload") or "")]


@pytest.fixture(autouse=True)
def no_http():
    """Neither leg may reach the network. Spied by failing loudly rather than by counting."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a review leg opened an HTTP connection")

    with patch("urllib.request.urlopen", forbidden):
        yield


# ══════════════════════════════════════════════════════════════════════════════
# One shared commerce-keys / ServiceRequests pair, seeded as a real purchase leaves it
# ══════════════════════════════════════════════════════════════════════════════

class _Purchase:
    """A paid purchase, readable by both legs: the `PAYREF#` row and the activated `REQ#` row."""

    def __init__(self, *, native: bool, submitted: bool) -> None:
        self.requests = RequestTable()
        self.keys = KeysTable()
        intent = store.request_intent(self.requests, who(), "SUBMIT_REQUEST",
                                      original_order=ORIGINAL_ORDER)
        self.reference_id, self.attempt_id, self.order_id = pay(self.keys, intent)
        if native:
            # Written by `checkout` into the `extra` of `allocate_payment_reference`. The webhook
            # reads this one marker rather than inventing a new one.
            self.keys.rows["PAYREF#" + self.reference_id]["nativeCatalogService"] = True
        outcome = store.activate(self.requests, self.keys, reference_id=self.reference_id)
        assert outcome.outcome == store.ACTIVATED
        self.request_id = next(key for key in self.requests.rows if str(key).startswith("REQ#"))
        row = self.requests.rows[self.request_id]
        # The native arm's own gate. `send_review` requires all four, and case 3 below is about
        # what happens when `detailsSubmittedAt` is absent.
        row["flowContactId"] = "contact-1"
        row["flowPhone"] = CONTACT
        if submitted:
            row["detailsSubmittedAt"] = int(time.time())

    @property
    def row(self):
        return self.requests.rows[self.request_id]


class _WebhookTables:
    """The webhook's `dynamodb`: the shared commerce-keys fake, inert everywhere else."""

    def __init__(self, keys) -> None:
        self.keys = keys
        self.other = FakeTable(key_attr="invoiceId", name="inert")

    def Table(self, name):  # noqa: N802 - the boto3 resource spelling
        return self.keys if name == webhook.COMMERCE_KEYS_TABLE else self.other


def _run_webhook_leg(purchase, outbound, monkeypatch, *, keys_table=None, resource=None):
    """Step 5 as the live path reaches it: `_post_payment_handler` on a confirmed capture.

    `channel` and `checkout_mode` are left at their defaults, which closes step 4's invoice
    delivery - this file is about step 5, and the delivery gate has its own tests.
    """
    monkeypatch.setattr(webhook, "lambda_client", outbound)
    monkeypatch.setattr(webhook, "dynamodb",
                        resource or _WebhookTables(keys_table or purchase.keys))
    return webhook._post_payment_handler(
        PAYMENT_ID, CONTACT, "buyer@example.com", "Submit Request", {},
        REQUEST, reference_id=purchase.reference_id)


def _run_native_leg(purchase, outbound, native_flow, monkeypatch):
    """`paid_submit_request.send_review`, with the identity chain it re-verifies satisfied."""
    orders = FakeTable(key_attr="orderId", name="orders")
    monkeypatch.setattr(native_flow, "tables",
                        lambda: (purchase.requests, purchase.keys, orders))

    contacts = FakeTable(key_attr="id", name="contacts")
    contacts.seed({"id": "contact-1", "phone": CONTACT, "checkoutCustomerId": ALICE,
                   "deletedAt": None})
    resource = MagicMock()
    resource.Table.return_value = contacts
    cognito = MagicMock()
    cognito.list_users.return_value = {"Users": [{"Enabled": True, "Attributes": [
        {"Name": "phone_number", "Value": CONTACT},
        {"Name": "phone_number_verified", "Value": "true"}]}]}
    fake_boto3 = MagicMock()
    fake_boto3.resource.return_value = resource
    fake_boto3.client.return_value = cognito
    monkeypatch.setattr(native_flow, "boto3", fake_boto3)

    from flows import paid_vault
    monkeypatch.setattr(paid_vault, "boto3", fake_boto3)
    return native_flow.send_review({"requestId": purchase.request_id}, outbound)


def _events(caplog):
    out = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and "event" in payload:
            out.append((payload["event"], record.levelname))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 1-3. one purchase, one invitation - and no fulfilment, no invitation
# ══════════════════════════════════════════════════════════════════════════════

def test_one_native_purchase_asks_for_a_review_once(native_flow, monkeypatch, caplog):
    """Two were sent before the fix: the webhook at capture and the native arm at delivery."""
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    purchase = _Purchase(native=True, submitted=True)
    outbound = _Outbound()
    _run_webhook_leg(purchase, outbound, monkeypatch)
    assert _run_native_leg(purchase, outbound, native_flow, monkeypatch) == \
        {"outcome": "REVIEW_ACCEPTED"}
    assert len(outbound.reviews) == 1
    assert ("review_request_skipped_native", "INFO") in _events(caplog)


def test_a_website_purchase_still_asks_once(native_flow, monkeypatch, caplog):
    """The sensitivity proof: the fix yielded on the native marker, it did not disable the arm.

    No `nativeCatalogService`, so the webhook arm is the only sender - and the native arm, with no
    fulfilment recorded, correctly declines. Exactly one invitation either way.
    """
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    purchase = _Purchase(native=False, submitted=False)
    outbound = _Outbound()
    _run_webhook_leg(purchase, outbound, monkeypatch)
    assert _run_native_leg(purchase, outbound, native_flow, monkeypatch) == \
        {"outcome": "REVIEW_NOT_DUE"}
    assert len(outbound.reviews) == 1
    assert ("review_request_sent", "INFO") in _events(caplog)
    assert "review_request_skipped_native" not in [name for name, _ in _events(caplog)]


def test_a_paid_native_purchase_with_no_details_asks_for_no_review(native_flow, monkeypatch):
    """No fulfilment implies no review invitation, deliberately.

    The purchase is paid and native, but nothing was delivered: the webhook arm yields to the
    native one, and the native one is not due. The reconciliation surface for a paid-but-unfulfilled
    purchase is the workspace, not a review nudge.
    """
    purchase = _Purchase(native=True, submitted=False)
    outbound = _Outbound()
    _run_webhook_leg(purchase, outbound, monkeypatch)
    assert _run_native_leg(purchase, outbound, native_flow, monkeypatch) == \
        {"outcome": "REVIEW_NOT_DUE"}
    assert outbound.reviews == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. the failure branch that decides whether a captured payment can be replayed
# ══════════════════════════════════════════════════════════════════════════════

def _throttle() -> ClientError:
    return ClientError({"Error": {"Code": "ProvisionedThroughputExceededException",
                                  "Message": "throughput exceeded"}}, "GetItem")


def test_an_unreadable_payment_reference_does_not_fail_the_capture(monkeypatch, caplog):
    """A throttle on the `PAYREF#` read must fail OPEN, in this order of importance.

    1. `_post_payment_handler` returns normally and does not raise.
    2. The top-level handler therefore does not return 500 and does not abandon the lease.
    3. Exactly one review invite went out - the fail-open default is `native = False`, i.e. SEND.
    4. `review_native_check_unavailable` was logged at WARNING, so the outage is greppable.
    """
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    purchase = _Purchase(native=True, submitted=True)
    purchase.keys.arm_failure("get_item", _throttle())
    outbound = _Outbound()

    assert _run_webhook_leg(purchase, outbound, monkeypatch) is None
    assert len(outbound.reviews) == 1
    assert ("review_native_check_unavailable", "WARNING") in _events(caplog)
    assert "review_request_skipped_native" not in [name for name, _ in _events(caplog)]


def _route_captured(outbound, monkeypatch, post_payment):
    """The real top-level `handler` on a signed `payment.captured`, down to step 5.

    `_handle_payment_captured` calls `_post_payment_handler` UNGUARDED, inside the handler's one
    top-level `try`, so it is stood in for here by `post_payment` - the provider readback and
    reconciliation it does first have their own tests and would not change which arm of the
    handler's `except` runs. Everything that decides 200-versus-500 is real: the signature is a
    real HMAC over the real body, and the lease is the real `_complete_event`.
    """
    secret = "test-only-webhook-" + "signing-key"
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": PAYMENT_ID, "amount": 10193, "currency": "INR", "status": "captured",
        "contact": CONTACT}}}})
    import hashlib
    import hmac
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    completed = []
    monkeypatch.setattr(webhook, "lambda_client", outbound)
    monkeypatch.setattr(webhook, "_get_webhook_secret", lambda: secret)
    monkeypatch.setattr(webhook, "_is_duplicate_event", lambda *_a, **_k: False)
    monkeypatch.setattr(webhook, "_log_webhook_event", lambda *_a, **_k: None)
    monkeypatch.setattr(webhook, "_complete_event",
                        lambda event_id, _request_id: completed.append(event_id))
    monkeypatch.setattr(webhook, "_handle_payment_captured",
                        lambda _event_data, request_id: post_payment(request_id))
    response = webhook.handler({"body": body, "headers": {"x-razorpay-signature": signature},
                                "requestContext": {"http": {"method": "POST"}}}, None)
    return response, completed


def test_a_throttled_native_check_still_answers_the_provider_200(monkeypatch):
    """The property the guard exists for, read off the real handler's status code.

    A 500 here leaves the lease uncompleted, which is exactly what lets Razorpay's retry be
    processed rather than dismissed - a deliberate REPLAY of a captured payment.
    """
    purchase = _Purchase(native=True, submitted=True)
    purchase.keys.arm_failure("get_item", _throttle())
    outbound = _Outbound()

    response, completed = _route_captured(
        outbound, monkeypatch,
        lambda request_id: _run_webhook_leg_inline(purchase, outbound, request_id))
    assert response["statusCode"] == 200
    assert len(completed) == 1, "a 200 must complete the lease"
    assert len(outbound.reviews) == 1


def test_the_rig_would_have_caught_a_500_and_an_abandoned_lease(monkeypatch):
    """Sensitivity proof for the case above: an unguarded raise IS visible through this rig.

    Without this, a 200 could mean "the guard works" or "the rig cannot see a failure". It raises
    `OrderIdentityUnavailable` - the exact exception the unguarded form propagated.
    """
    outbound = _Outbound()

    def raising(_request_id):
        raise order_keys.OrderIdentityUnavailable("could not read 'PAYREF#...': ClientError")

    response, completed = _route_captured(outbound, monkeypatch, raising)
    assert response["statusCode"] == 500
    assert completed == [], "a 500 must NOT complete the lease, or the retry is dismissed"


def _run_webhook_leg_inline(purchase, outbound, request_id):
    """`_post_payment_handler` with `dynamodb` already pointed at the shared fakes."""
    webhook.dynamodb = _WebhookTables(purchase.keys)
    return webhook._post_payment_handler(
        PAYMENT_ID, CONTACT, "buyer@example.com", "Submit Request", {},
        request_id, reference_id=purchase.reference_id)


# ══════════════════════════════════════════════════════════════════════════════
# 5. the catch is narrow on purpose
# ══════════════════════════════════════════════════════════════════════════════

class _BrokenResource:
    """`.Table()` itself raises - evaluated BEFORE `resolve_payment_reference` is entered.

    This is the whole subtlety of the case. A `KeyError` raised by `table.get_item` would arrive
    at the guard as `OrderIdentityUnavailable`, because `order_keys._read_row` wraps EVERY storage
    exception into that one type - so injecting there would prove nothing and would report red on
    correct code. Injecting at `.Table()` is inside the guard's `try` but outside `_read_row`'s,
    so it cannot be converted.
    """

    def Table(self, _name):  # noqa: N802 - the boto3 resource spelling
        raise KeyError("COMMERCE_KEYS_TABLE")


def test_an_error_outside_the_storage_wrapper_is_not_swallowed(monkeypatch):
    """A programming error must be LOUD, and must not be absorbed into the fail-open default.

    A storage outage fails open on a captured payment; a logic bug - a bad table name, a
    non-mapping result, a missing module attribute - does not. That asymmetry is the reason the
    catch names `OrderIdentityUnavailable` rather than `Exception`, and this case is what makes a
    later widening of it fail the suite.
    """
    purchase = _Purchase(native=True, submitted=True)
    outbound = _Outbound()

    with pytest.raises(KeyError):
        _run_webhook_leg(purchase, outbound, monkeypatch, resource=_BrokenResource())
    assert outbound.reviews == []


def test_the_guard_catches_the_storage_type_and_not_everything():
    """Source-level, so a tidy-up to `except Exception` cannot pass by behaving the same today."""
    source = WEBHOOK_PATH.read_text(encoding="utf-8")
    block = source.split("native = False", 1)[1].split("logger.info(json.dumps({'event': 'post_payment_complete'", 1)[0]
    assert "except order_keys.OrderIdentityUnavailable:" in block
    assert "except Exception" not in block
