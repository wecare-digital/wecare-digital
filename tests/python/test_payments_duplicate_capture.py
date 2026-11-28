"""PAY-2: an existing order only accepts the payment already bound to it."""
from botocore.exceptions import ClientError

from lambda_utils.ecommerce import order_creation, order_keys


def _conditional():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


class Keys:
    def __init__(self):
        self.rows = {}

    def put_item(self, *, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(orderId)"
        if Item["orderId"] in self.rows:
            raise _conditional()
        self.rows[Item["orderId"]] = dict(Item)

    def get_item(self, *, Key, ConsistentRead=False):
        row = self.rows.get(Key["orderId"])
        return {"Item": dict(row)} if row is not None else {}

    def update_item(self, *, Key, UpdateExpression, ConditionExpression,
                    ExpressionAttributeValues):
        row = self.rows.get(Key["orderId"])
        if row is None or "orderNumber" in row:
            raise _conditional()
        row["orderNumber"] = ExpressionAttributeValues[":n"]


ATTEMPT = {"paymentAttemptId": "pa_1", "customerId": "c1", "amountPaise": 1000,
           "currency": "INR", "providerPaymentId": "", "providerOrderId": "order_1"}


def _reconcile(keys, *, event_payment_id, calls):
    def verify(_reference):
        calls.append("verify")
        return True, "pay_A", 1000, "INR"
    return order_creation.reconcile_payment(
        table=keys, reference_id="WD-PAY-ABCDEF12", verify_payment=verify,
        load_attempt=lambda _ref: dict(ATTEMPT), event_payment_id=event_payment_id)


def test_redelivery_of_the_bound_payment_still_resolves_the_order():
    keys, calls = Keys(), []
    first = _reconcile(keys, event_payment_id="pay_A", calls=calls)
    assert first.outcome == order_creation.ORDER_CREATED and first.provider_payment_id == "pay_A"
    again = _reconcile(keys, event_payment_id="pay_A", calls=calls)
    assert again.outcome == order_creation.ORDER_ALREADY_EXISTS and again.has_order
    assert calls == ["verify"]


def test_a_different_or_missing_payment_id_is_a_duplicate_capture():
    keys, calls = Keys(), []
    _reconcile(keys, event_payment_id="pay_A", calls=calls)
    before = {key: dict(row) for key, row in keys.rows.items()}
    for event_id in ("pay_B", ""):
        outcome = _reconcile(keys, event_payment_id=event_id, calls=calls)
        assert outcome.outcome == order_creation.DUPLICATE_CAPTURE
        assert not outcome.has_order and not outcome.needs_human
        assert outcome.verified_captured_paise == 0
    assert keys.rows == before
    assert calls == ["verify"]          # the short cut never asks the provider


def test_callers_without_an_event_keep_the_old_short_cut():
    keys, calls = Keys(), []
    _reconcile(keys, event_payment_id="pay_A", calls=calls)
    outcome = _reconcile(keys, event_payment_id=None, calls=calls)
    assert outcome.outcome == order_creation.ORDER_ALREADY_EXISTS


def test_unnumbered_claim_is_not_finished_for_another_payment():
    keys, calls = Keys(), []
    order_keys.claim_order_for_payment(keys, payment_attempt_id="pa_1", order_id="ord_1",
                                       provider_transaction_id="pay_A")
    outcome = _reconcile(keys, event_payment_id="pay_B", calls=calls)
    assert outcome.outcome == order_creation.DUPLICATE_CAPTURE
    assert not any(key.startswith(order_keys.ORDER_NUMBER_PREFIX) for key in keys.rows)
    finished = _reconcile(keys, event_payment_id="pay_A", calls=calls)
    assert finished.has_order and finished.order_number
    assert calls == []
