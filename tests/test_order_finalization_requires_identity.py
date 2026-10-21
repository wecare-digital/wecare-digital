from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import finalization, payment_attempt  # noqa: E402
from lambda_utils.identity import customer_uuid  # noqa: E402


PUBLIC = customer_uuid.new_customer_uuid()


class Attempts:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class Orders:
    def __init__(self):
        self.row = None
        self.finalize_calls = []

    def put_item(self, **kwargs):
        self.row = dict(kwargs["Item"])
        return {}

    def get_item(self, **kwargs):
        return {"Item": dict(self.row or {})}

    def update_item(self, **kwargs):
        self.finalize_calls.append(kwargs)
        if self.row:
            self.row["finalizationStage"] = kwargs["ExpressionAttributeValues"][":stage"]
        return {}


def attempt(**overrides):
    row = payment_attempt.build(
        customer_id="00000000-0000-4000-8000-000000000001",
        reference_id="WD-PAY-ABCDEFGHJKMNPQ",
        amount_paise=100,
        configuration_name="WECAREDIGITAL",
        customer_uuid=PUBLIC,
        now=10,
    )
    row = payment_attempt.transition(row, payment_attempt.PAYMENT_PAID, now=11)
    row.update({
        "checkoutMode": "WEBSITE_RAZORPAY_STANDARD",
        "snapshotHash": "hash",
        "purchasedSnapshot": {"cart": {"lineItems": []}},
        "contactId": "contact-1",
    })
    row.update(overrides)
    return row


def run(row):
    attempts = Attempts()
    orders = Orders()
    finalization.accept_paid(
        attempts=attempts,
        orders=orders,
        keys=None,
        attempt=row,
        outcome={
            "hasOrder": True,
            "orderId": "order-1",
            "orderNumber": "WD-ORD-ABCDEFGH",
            "providerPaymentId": "pay_1",
        },
        verified_captured_paise=100,
    )
    stages = [
        call.get("ExpressionAttributeValues", {}).get(":stage")
        for call in attempts.calls
        if ":stage" in call.get("ExpressionAttributeValues", {})
    ]
    return attempts, orders, stages


def test_missing_contact_id_never_reaches_order_finalized():
    row = attempt()
    row.pop("contactId")
    _, orders, stages = run(row)
    assert orders.row is not None
    assert "ORDER_FINALIZED" not in stages
    assert "NEEDS_RECONCILIATION" in stages
    assert not orders.finalize_calls


def test_missing_customer_uuid_never_reaches_order_finalized():
    row = attempt()
    row.pop("customerUuid")
    _, orders, stages = run(row)
    assert orders.row is not None
    assert "ORDER_FINALIZED" not in stages
    assert "NEEDS_RECONCILIATION" in stages
    assert not orders.finalize_calls


def test_complete_identity_can_finalize():
    _, orders, stages = run(attempt())
    assert "ORDER_FINALIZED" in stages
    assert orders.finalize_calls
