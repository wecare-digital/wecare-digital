"""Offline F004 website payment lock and completion contracts (no provider calls)."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import ast
import json
import time

import pytest

from lambda_utils.ecommerce import payment_attempt, website_submit_request as web

OWNER = "customer-A"
ORDER = "order-A"
NUMBER = "WD-ORD-7ZTSG8X7"
KEY = "a" * 32
KEY2 = "b" * 32
AMOUNT = 16600
NOTE = "Please review this order."


class ConditionalError(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Table:
    """Minimal conditional-write fixture; rejects a competing create right."""
    def __init__(self, key):
        self.key = key
        self.rows = {}

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead
        return {"Item": deepcopy(self.rows.get(Key[self.key], {}))}

    def put_item(self, *, Item, ConditionExpression, ExpressionAttributeValues=None):
        key = Item[self.key]
        old = self.rows.get(key)
        if ConditionExpression == "attribute_not_exists(orderId)":
            if old:
                raise ConditionalError()
        else:
            assert ConditionExpression == "paymentAttemptId = :previous AND customerId = :owner"
            if (not old or old["paymentAttemptId"] != ExpressionAttributeValues[":previous"]
                    or old["customerId"] != ExpressionAttributeValues[":owner"]):
                raise ConditionalError()
        self.rows[key] = deepcopy(Item)

    def update_item(self, *, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeValues, ExpressionAttributeNames=None):
        row = self.rows[Key[self.key]]
        v = ExpressionAttributeValues
        if UpdateExpression == "SET sendRefused=:yes":
            assert row["paymentAttemptId"] == v[":attempt"]
            row["sendRefused"] = True
        elif UpdateExpression.startswith("SET serviceActivities["):
            assert row["customerId"] == v[":owner"]
            i = int(UpdateExpression.split("[")[1].split("]")[0])
            assert row["serviceActivities"][i]["paymentAttemptId"] == v[":aid"]
            row["serviceActivities"][i].update(flowStatus=v[":done"], flowSubmissionId=v[":sid"])
        elif UpdateExpression.startswith("SET websiteSubmissionId"):
            assert row["status"] == v[":paid"] and row["customerId"] == v[":owner"]
            row["websiteSubmissionId"] = v[":sid"]
        elif UpdateExpression.startswith("SET openServiceRequestId"):
            assert row["checkoutCustomerId"] == v[":owner"]
            row["openServiceRequestId"] = v[":sid"]
        else:
            raise AssertionError(UpdateExpression)


def reserve(keys, attempts, key=KEY, aid="attempt-A", note=NOTE):
    return web.reserve(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER,
                       key=key, note=note, amount=AMOUNT, attempt_id=aid)


def state(keys, attempts):
    return web.state(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER)


def attempt(key=KEY, aid="attempt-A"):
    return dict(paymentAttemptId=aid, customerId=OWNER, selectedOrderId=ORDER,
                selectedOrderNumber=NUMBER, websiteForm=web.VERSION, websiteRequestKey=key,
                websiteRequestNote=NOTE, serviceCode=web.SERVICE, flowCapability=web.CAPABILITY,
                singleOrderService=True, status=payment_attempt.PAYMENT_READINESS_CHECKED,
                amountPaise=AMOUNT, paymentRequestExpiresAt=int(time.time()) + 900)


def test_note_boundary():
    assert web.clean_note("  note  ") == "note"
    assert web.clean_note("x" * 300) == "x" * 300
    for invalid in (None, "", "  ", "x" * 301, "\U0001f600" * 151):
        with pytest.raises(ValueError):
            web.clean_note(invalid)


def test_duplicate_click_and_second_tab_are_not_payable():
    keys, attempts = Table("orderId"), Table("paymentAttemptId")
    assert state(keys, attempts)["state"] == "idle"
    assert reserve(keys, attempts)
    # No attempt row yet: an ambiguous crash remains locked, not idle.
    assert state(keys, attempts)["state"] == "pending"
    assert not reserve(keys, attempts)
    assert not reserve(keys, attempts, KEY2, "attempt-B")
    with pytest.raises(ValueError, match="REQUEST_KEY_CONFLICT"):
        reserve(keys, attempts, note="changed")
    with pytest.raises(RuntimeError):
        web.state(keys, attempts, owner="foreign", order_id=ORDER, number=NUMBER)
    assert len(keys.rows) == 2


def test_paid_is_saving_until_durable_completion_and_replay_never_charges_again():
    keys, attempts = Table("orderId"), Table("paymentAttemptId")
    assert reserve(keys, attempts)
    row = attempt()
    attempts.rows[row["paymentAttemptId"]] = row
    row["status"] = payment_attempt.PAYMENT_PAID
    assert state(keys, attempts)["state"] == "saving"
    assert not reserve(keys, attempts, KEY2, "attempt-B")
    row["websiteSubmissionId"] = "WD-SR-FIXTURE"
    assert state(keys, attempts)["state"] == "received"
    assert reserve(keys, attempts, KEY2, "attempt-B")
    assert not reserve(keys, attempts)
    assert state(keys, attempts)["requestKey"] == KEY2


def test_failure_only_releases_after_refusal_or_expired_terminal_state():
    keys, attempts = Table("orderId"), Table("paymentAttemptId")
    assert reserve(keys, attempts)
    row = attempt()
    attempts.rows[row["paymentAttemptId"]] = row
    row["status"] = payment_attempt.PAYMENT_FAILED
    assert state(keys, attempts)["state"] == "pending"
    assert not reserve(keys, attempts, KEY2, "attempt-B")
    row["paymentRequestExpiresAt"] = int(time.time()) - 1
    assert state(keys, attempts)["state"] == "failed"
    assert reserve(keys, attempts, KEY2, "attempt-B")
    web.refused(keys, order_id=ORDER, attempt_id="attempt-B")
    assert state(keys, attempts)["state"] == "failed"


def test_quote_reconciles_the_server_snapshot():
    snap = SimpleNamespace(
        frozen_data={"items": [{"quantity": 1, "unitPricePaise": 9900}],
                     "pricingMetadata": {"supplyGstPaise": 1782, "discountPaise": 58, "expressPaise": 4500}},
        quote=SimpleNamespace(currency="INR", total_payable_paise=AMOUNT,
                              convenience_fee_paise=403, convenience_gst_paise=73))
    q = web.quote(snap, NUMBER)
    assert q["orderNumber"] == NUMBER and q["totalPayablePaise"] == AMOUNT
    snap.quote.total_payable_paise += 1
    with pytest.raises(ValueError):
        web.quote(snap, NUMBER)


def test_completion_checks_payment_and_durable_record_then_marks_original_activity():
    keys, attempts, orders, submissions, contacts = (
        Table("orderId"), Table("paymentAttemptId"), Table("orderId"),
        Table("submissionId"), Table("id"))
    assert reserve(keys, attempts)
    a = attempt()
    a.update(status=payment_attempt.PAYMENT_PAID, finalizationStage="ORDER_FINALIZED",
             orderId=ORDER, orderNumber=NUMBER, referenceId="reference-A",
             customerPhone="+919000000001", verifiedProviderPaymentId="pay_fixture",
             verifiedCapturedPaise=AMOUNT)
    attempts.rows["attempt-A"] = a
    contact = {"id": "contact-A", "checkoutCustomerId": OWNER, "name": "Fixture"}
    contacts.rows["contact-A"] = contact
    orders.rows[ORDER] = {"orderId": ORDER, "customerId": OWNER, "orderNumber": NUMBER,
                          "serviceActivityPaymentIds": ["attempt-A"],
                          "serviceActivities": [{"paymentAttemptId": "attempt-A", "serviceCode": web.SERVICE,
                              "flowCapability": web.CAPABILITY, "providerPaymentId": "pay_fixture",
                              "amountPaise": AMOUNT, "flowStatus": "PENDING"}]}
    db = Mock()
    db.Table.side_effect = {web.shared_tables.orders_table_name(): orders,
                            web.shared_tables.flow_submissions_table_name(): submissions,
                            web.shared_tables.contacts_table_name(): contacts}.__getitem__
    def claim(**kw):
        assert kw["channel"] == web.flow_completion.CHANNEL_WEBSITE
        assert kw["form_data"]["note"] == NOTE
        assert kw["flow_token"] == "website:f004:attempt-A"
        sid = "WD-SR-FIXTURE"
        existed = sid in submissions.rows
        submissions.rows.setdefault(sid, {"submissionId": sid, "flowToken": kw["flow_token"],
            "channel": kw["channel"], "createdAt": 1, **kw["extra"]})
        return SimpleNamespace(status="duplicate" if existed else "created", submission_id=sid)
    with patch.object(web.contact_key, "resolve", return_value="contact-A"), \
         patch.object(web.flow_completion, "claim_completion", side_effect=claim) as writer:
        with pytest.raises(ValueError):
            web.complete(db, attempts, {**a, "status": payment_attempt.PAYMENT_PENDING},
                         contact=contact, phone="+919000000001", reference_id="reference-A")
        writer.assert_not_called()
        assert state(keys, attempts)["state"] == "saving"
        for _ in range(2):
            result = web.complete(db, attempts, a, contact=contact, phone="+919000000001",
                                  reference_id="reference-A")
            assert result["outcome"] == "WEBSITE_REQUEST_COMPLETED"
        assert len(submissions.rows) == 1
        assert orders.rows[ORDER]["serviceActivities"][0]["flowStatus"] == "COMPLETED"
        assert state(keys, attempts)["state"] == "received"
        assert contacts.rows["contact-A"]["openServiceRequestId"] == "WD-SR-FIXTURE"


def test_checkout_refuses_foreign_order_before_quote_or_create():
    source = (Path(__file__).resolve().parents[2] /
              "amplify/functions/ecommerce/checkout/handler.py").read_text()
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_website_f004")
    keys, orders = Table("orderId"), Table("orderId")
    order_keys = SimpleNamespace(is_public_order_number=lambda n: n == NUMBER, ORDER_NUMBER_PREFIX="ORDERNO#")
    keys.rows["ORDERNO#" + NUMBER] = {"orderIdRef": ORDER}
    orders.rows[ORDER] = {"customerId": "different", "orderNumber": NUMBER, "paymentStatus": "captured"}
    create, quote = Mock(), Mock()
    env = {"_hardened": lambda r: r, "cors_response": lambda code, body, origin: {"statusCode": code, "body": json.dumps(body)},
           "_keys_table": lambda: keys, "_orders_table": lambda: orders,
           "order_keys": order_keys, "payment_status": SimpleNamespace(canonical=lambda x: x, CAPTURED="captured"),
           "_create": create, "_native_quote": quote}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "f004-handler", "exec"), env)
    reply = env["_website_f004"](SimpleNamespace(customer_id=OWNER),
                {"action": "request-service-web-start", "selectedOrderNumber": NUMBER,
                 "requestKey": KEY, "note": NOTE, "expectedTotalPaise": AMOUNT}, "", "request-service-web-start")
    assert reply["statusCode"] == 404
    create.assert_not_called()
    quote.assert_not_called()


def test_native_prepare_uses_existing_order_and_same_gateway_on_resume():
    from lambda_utils.ecommerce import website_checkout as checkout
    keys, attempts = Table("orderId"), Table("paymentAttemptId")
    amount = 7468
    snapshot = SimpleNamespace(
        snapshot_hash="fixture-snapshot", frozen_data={
            "items": [{"quantity": 1, "unitPricePaise": 4900}],
            "pricingMetadata": {"supplyGstPaise": 882, "discountPaise": 28, "expressPaise": 1500}},
        quote=SimpleNamespace(currency="INR", total_payable_paise=amount,
                              convenience_fee_paise=181, convenience_gst_paise=33))
    gateway = "order_fixture"
    reference = "reference-A"
    payref = dict(customerId=OWNER, paymentAttemptId="attempt-A", amountPaise=amount,
                  checkoutMode=checkout.CHECKOUT_MODE_WEBSITE, websiteForm=web.VERSION,
                  serviceLine=dict(singleOrder=True, serviceCode=web.SERVICE,
                                   selectedOrderId=ORDER, selectedOrderNumber=NUMBER))
    binding = dict(customerId=OWNER, paymentAttemptId="attempt-A", gatewayOrderId=gateway,
                   referenceId=reference, requestKey=KEY, amountPaise=amount,
                   currency="INR", accountKeyId="rzp_test_fixture")
    fields = dict(customerId=OWNER, selectedOrderId=ORDER, selectedOrderNumber=NUMBER,
                  websiteForm=web.VERSION, websiteRequestKey=KEY, websiteRequestNote=NOTE,
                  serviceCode=web.SERVICE, flowCapability=web.CAPABILITY, singleOrderService=True)
    provider = Mock(return_value={"id": gateway, "key_id": "rzp_test_fixture"})
    def allocate(table, *, payment_attempt_id, extra):
        assert payment_attempt_id == "attempt-A"
        assert extra["serviceLine"]["selectedOrderId"] == ORDER
        assert extra["amountPaise"] == amount
        return reference
    def persist(row):
        attempts.rows[row["paymentAttemptId"]] = row
    def engine(**kw):
        assert kw["customer_id"] == OWNER
        assert kw["presented_snapshot_hash"] == snapshot.snapshot_hash
        assert kw["allocate_reference"]("attempt-A", amount) == reference
        kw["create_order"](amount_paise=amount, receipt=reference, notes={})
        kw["reserve_attempt"](dict(paymentAttemptId="attempt-A", referenceId=reference,
            checkoutMode=checkout.CHECKOUT_MODE_WEBSITE, providerOrderId=gateway,
            amountPaise=amount, status=payment_attempt.PAYMENT_PENDING))
        return SimpleNamespace(status=checkout.CHECKOUT_OPTIONS_READY)
    args = dict(keys=keys, attempts=attempts, owner=OWNER, order_id=ORDER, number=NUMBER,
                key=KEY, note=NOTE, snapshot=snapshot, expected_amount=amount, now=1,
                initiation_enabled=True, create_order=provider, find_order_by_receipt=Mock(),
                account_mode_of=Mock(), payref_fields=payref, attempt_fields=fields,
                reserve_attempt=persist, prefill={})
    with patch.object(checkout, "prepare_checkout", side_effect=engine) as prepare, \
         patch.object(web.order_keys, "allocate_payment_reference", side_effect=allocate), \
         patch.object(web.order_keys, "resolve_gateway_order", return_value=binding), \
         patch.object(web.order_keys, "resolve_payment_reference", return_value=payref):
        with pytest.raises(ValueError, match="SERVICE_PRICE_CHANGED"):
            web.prepare_native(**{**args, "expected_amount": amount + 1})
        prepare.assert_not_called()
        provider.assert_not_called()
        initial = web.prepare_native(**args)
        assert initial["state"] == "pending" and initial["options"]["orderId"] == gateway
        assert initial["options"]["amountPaise"] == amount
        assert initial["resumeAvailable"] is True
        assert attempts.rows["attempt-A"]["selectedOrderId"] == ORDER
        assert attempts.rows["attempt-A"]["websiteRequestNote"] == NOTE
        # Repeating the click or another key cannot create a second gateway order.
        assert "options" not in web.prepare_native(**args)
        assert "options" not in web.prepare_native(**{**args, "key": KEY2})
        provider.assert_called_once()
        resumed = web.resume_options(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER)
        assert resumed["orderId"] == gateway and resumed["amountPaise"] == amount
        with pytest.raises(RuntimeError):
            web.resume_options(keys, attempts, owner="foreign", order_id=ORDER, number=NUMBER)
        binding["amountPaise"] = amount + 1
        assert web.resume_options(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER) is None
        binding["amountPaise"] = amount
        attempts.rows["attempt-A"]["checkoutMode"] = "WHATSAPP_NATIVE_CART"
        assert web.resume_options(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER) is None
        attempts.rows["attempt-A"]["checkoutMode"] = checkout.CHECKOUT_MODE_WEBSITE
        attempts.rows["attempt-A"]["status"] = payment_attempt.PAYMENT_PAID
        assert state(keys, attempts)["state"] == "saving"
        assert web.resume_options(keys, attempts, owner=OWNER, order_id=ORDER, number=NUMBER) is None


def test_legacy_f004_start_cannot_send_whatsapp_even_for_owned_order():
    source = (Path(__file__).resolve().parents[2] /
              "amplify/functions/ecommerce/checkout/handler.py").read_text()
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_website_f004")
    keys, orders = Table("orderId"), Table("orderId")
    keys.rows["ORDERNO#" + NUMBER] = {"orderIdRef": ORDER}
    orders.rows[ORDER] = {"customerId": OWNER, "orderNumber": NUMBER, "paymentStatus": "captured"}
    create = Mock()
    env = {"_hardened": lambda r: r, "cors_response": lambda code, body, origin: {"statusCode": code, "body": json.dumps(body)},
           "_keys_table": lambda: keys, "_orders_table": lambda: orders,
           "order_keys": SimpleNamespace(is_public_order_number=lambda n: n == NUMBER, ORDER_NUMBER_PREFIX="ORDERNO#"),
           "payment_status": SimpleNamespace(canonical=lambda x: x, CAPTURED="captured"),
           "_create": create}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "f004-handler", "exec"), env)
    result = env["_website_f004"](SimpleNamespace(customer_id=OWNER),
        {"action": "request-service-web-start", "selectedOrderNumber": NUMBER,
         "requestKey": KEY, "note": NOTE, "expectedTotalPaise": AMOUNT}, "", "request-service-web-start")
    assert result["statusCode"] == 409
    assert json.loads(result["body"])["error"] == "WEBSITE_PAYMENT_CLIENT_UPDATE_REQUIRED"
    create.assert_not_called()
