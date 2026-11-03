"""Regression guard: a Collect receipt resend never sends for an unpaid invoice.

The approved receipt body asserts "Payment received", so no receipt may be
dispatched for an invoice whose money has not been captured. The paid-state
check lives in ``collect_receipts.resend`` (and is mirrored by a DynamoDB
ConditionExpression and by ``send_invoice_whatsapp`` in the invoice-engine
handler). This test pins the shared entry point: for every non-captured payment
state it must refuse with ``PAID_RECEIPT_REQUIRED`` and must NEVER invoke the
injected ``send`` callable.

The handler itself imports live AWS resources at module load, so it cannot be
imported in a unit test. ``collect_receipts.resend`` is the pure, dependency
injected core that gates _send_collect_receipt, so testing it exercises the
real guard the staff "resend receipt" button passes through.

Fixtures are synthetic: no real invoice ids, phone numbers or account data.
"""

import pytest

from lambda_utils import payment_status as pay_status
from lambda_utils.ecommerce import collect_receipts


# A valid Collect invoice per collect_contract.is_collect: pay_flow entry point,
# no fixed preset and no service kind. Only paymentStatus varies between cases.
_COLLECT_INVOICE_ID = "inv-collect-0001"
_VALID_RESEND_REQUEST_ID = "a" * 32  # 32 lowercase hex chars, per the validator.


def _collect_invoice(payment_status_value):
    return {
        "invoiceId": _COLLECT_INVOICE_ID,
        "entryPoint": "pay_flow",
        "customerPhone": "+919000000000",
        "paymentStatus": payment_status_value,
    }


class _FakeTable:
    """Minimal DynamoDB table stand-in.

    ``resend`` reads the idempotency row from ``keys`` and the invoice from
    ``invoices`` via ``get_item(...).get('Item')``. For the unpaid cases the
    paid-state refusal fires before any write, so get_item is all that is
    exercised; put_item/update_item raise if ever reached so an accidental
    write on an unpaid invoice fails loudly.
    """

    def __init__(self, items=None):
        self._items = dict(items or {})

    def get_item(self, Key, **_kwargs):
        key = next(iter(Key.values()))
        item = self._items.get(key)
        return {"Item": item} if item is not None else {}

    def put_item(self, **_kwargs):  # pragma: no cover - must not run on unpaid path
        raise AssertionError("put_item must not run for an unpaid Collect invoice")

    def update_item(self, **_kwargs):  # pragma: no cover - must not run on unpaid path
        raise AssertionError("update_item must not run for an unpaid Collect invoice")


class _SendSpy:
    """Records whether the outbound receipt send was ever attempted."""

    def __init__(self):
        self.called = False

    def __call__(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("send must never run for an unpaid Collect invoice")


def _run_resend(invoice, send_spy):
    body = {
        "_action": "collect-resend",
        "invoiceId": _COLLECT_INVOICE_ID,
        "resendRequestId": _VALID_RESEND_REQUEST_ID,
        "previousRequestId": "",
        "expectedAssetKey": "media/invoices/inv-collect-0001/image.png",
    }
    invoices = _FakeTable({_COLLECT_INVOICE_ID: invoice})
    keys = _FakeTable()  # no prior idempotency row
    return collect_receipts.resend(
        body,
        actor="staff-sub-123",
        invoices=invoices,
        keys=keys,
        latest_asset=lambda _iid: {
            "s3Key": body["expectedAssetKey"],
            "generatedAt": 10_000,
        },
        recipient_valid=lambda _inv: True,
        send=send_spy,
        paid=lambda inv: pay_status.canonical(inv.get("paymentStatus")) == pay_status.CAPTURED,
        original_ready=lambda _inv: True,
        reconcile=lambda *_a, **_k: None,
        now=20_000,
    )


# Every state the money can be in that is NOT a verified capture. The approved
# receipt body would lie for each of these, so each must be refused.
_UNPAID_STATES = [
    "",             # no payment state at all
    "pending",
    "pending_payment",
    "authorized",
    "failed",
    "refunded",
    "disputed",
]


@pytest.mark.parametrize("payment_status_value", _UNPAID_STATES)
def test_unpaid_collect_resend_is_refused_and_never_sends(payment_status_value):
    send_spy = _SendSpy()
    code, result = _run_resend(_collect_invoice(payment_status_value), send_spy)

    # Refused with the named paid-state code, before any send.
    assert code == 409, (payment_status_value, code, result)
    assert result.get("error") == "PAID_RECEIPT_REQUIRED", result
    # The outbound receipt was never attempted.
    assert send_spy.called is False


def test_refunded_is_not_mistaken_for_captured():
    """`refunded` ranks above `captured` but is still not a payable receipt state."""
    assert pay_status.canonical("refunded") == pay_status.REFUNDED
    assert pay_status.canonical("refunded") != pay_status.CAPTURED
    send_spy = _SendSpy()
    code, result = _run_resend(_collect_invoice("refunded"), send_spy)
    assert code == 409 and result.get("error") == "PAID_RECEIPT_REQUIRED"
    assert send_spy.called is False


def test_paid_aliases_canonicalise_to_captured():
    """The guard keys off canonical(), so `paid`/`payment_paid` count as captured.

    This pins the alias mapping the guard relies on: if these ever stopped
    canonicalising to CAPTURED, a genuinely paid Collect invoice would be
    wrongly refused. The test asserts the mapping only; it does not drive a send.
    """
    for alias in ("paid", "payment_paid", "captured"):
        assert pay_status.canonical(alias) == pay_status.CAPTURED, alias
