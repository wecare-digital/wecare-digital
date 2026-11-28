"""PAY-2/3/6/9: Razorpay readback helpers return the provider's own entity, never a guess."""
import pytest

from lambda_utils.integrations import razorpay_verify


@pytest.fixture
def api(monkeypatch):
    responses = {}
    requested = []

    def fake_get(path):
        requested.append(path)
        return responses[path]

    monkeypatch.setattr(razorpay_verify, "_get", fake_get)
    return responses, requested


def test_verifier_hands_back_the_verified_entity(api):
    responses, _ = api
    responses["/payments/pay_A"] = {"id": "pay_A", "status": "captured", "amount": 1500,
                                    "currency": "INR", "order_id": "order_1",
                                    "contact": "+919000000001"}
    capture = {}
    verify = razorpay_verify.verifier_for_event(
        payment_id="pay_A", order_id="order_1", capture=capture,
        load_attempt=lambda _ref: {"providerOrderId": "order_1"})
    assert verify("WD-PAY-ABCDEF12") == (True, "pay_A", 1500, "INR")
    assert capture["payment"]["contact"] == "+919000000001"


def test_verifier_without_capture_is_unchanged(api):
    responses, _ = api
    responses["/payments/pay_A"] = {"id": "pay_A", "status": "authorized", "amount": 1500,
                                    "currency": "INR", "order_id": "order_1"}
    verify = razorpay_verify.verifier_for_event(
        payment_id="pay_A", load_attempt=lambda _ref: {"providerOrderId": "order_1"})
    assert verify("WD-PAY-ABCDEF12") == (False, "", 0, "")


@pytest.mark.parametrize("reader,path", [
    (razorpay_verify.payment_entity, "/payments/x_1"),
    (razorpay_verify.refund_entity, "/refunds/x_1"),
    (razorpay_verify.payment_link_entity, "/payment_links/x_1"),
    (razorpay_verify.dispute_entity, "/disputes/x_1"),
])
def test_entity_readers_refuse_an_answer_for_another_id(api, reader, path):
    responses, requested = api
    responses[path] = {"id": "x_1", "status": "processed"}
    assert reader("x_1")["status"] == "processed"
    responses[path] = {"id": "x_2"}
    with pytest.raises(razorpay_verify.RazorpayUnavailable):
        reader("x_1")
    with pytest.raises(ValueError):
        reader("")
    assert requested == [path, path]
