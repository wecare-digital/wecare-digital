"""Three payment paths that were too permissive, each in a way that was invisible.

Carried over as MEDIUM from the Phase 4d payment audit. None of them errored;
each produced a confident wrong answer.

1. `_mark_invoice_paid_by_phone_and_amount` matched on a float epsilon and, when
   several invoices matched, marked the OLDEST paid. Two pending invoices for the
   same phone with the same total is an ordinary repeat order, so that marked the
   wrong invoice paid AND left the real one outstanding.
2. `_get_next_invoice_number` fell back to `WD-PAY-TEMP-<uuid>` when the sequence
   counter was unreachable, putting a non-consecutive number into the GST series
   and returning it as an ordinary success.
3. Meta payment verification used a bool initialised True, so a capture that was
   never checked looked exactly like one Meta had confirmed.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "amplify" / "functions"
for extra in (FUNCTIONS / "shared",):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


# ---------------------------------------------------------------------------
# 1. Invoice matching must refuse to guess
# ---------------------------------------------------------------------------

@pytest.fixture
def razorpay(monkeypatch):
    """Load razorpay-webhook with boto3 stubbed, and hand back its module."""
    path = str(FUNCTIONS / "payments" / "razorpay-webhook")
    monkeypatch.syspath_prepend(path)
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415 - deliberately imported under the patches
    yield handler
    sys.modules.pop("handler", None)


def invoice(invoice_id: str, phone: str, total: str, created: int = 1):
    return {
        "invoiceId": invoice_id,
        "customerPhone": phone,
        "total": Decimal(total),
        "status": "created",
        "createdAt": created,
    }


def fake_table(items):
    table = MagicMock()
    table.scan.return_value = {"Items": items}
    return table


def test_exactly_one_match_is_marked_paid(razorpay, monkeypatch):
    table = fake_table([invoice("INV-1", "+919876543210", "100.00")])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    marked = razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-1")

    assert marked is True
    table.update_item.assert_called_once()
    assert table.update_item.call_args.kwargs["Key"] == {"invoiceId": "INV-1"}


def test_two_identical_invoices_are_not_guessed_between(razorpay, monkeypatch):
    """The bug. A repeat order produced two pending invoices, same phone, same total.

    The old code sorted by createdAt and marked the oldest paid, which is
    deterministic but not correct: one payment, one invoice wrongly marked paid,
    and the actual one still outstanding. Nothing downstream could detect it.
    """
    table = fake_table([
        invoice("INV-OLD", "+919876543210", "100.00", created=1),
        invoice("INV-NEW", "+919876543210", "100.00", created=2),
    ])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    marked = razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-2")

    assert marked is False
    table.update_item.assert_not_called()


def test_a_one_paisa_difference_no_longer_matches(razorpay, monkeypatch):
    """The epsilon was 0.02 while the comment claimed 0.01.

    So a Rs 100.00 invoice matched a Rs 100.01 payment, and a float comparison
    decided which invoice got paid. Amounts are compared as integer paise now,
    so this is an exact question with an exact answer.
    """
    table = fake_table([invoice("INV-1", "+919876543210", "100.00")])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    marked = razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.01, "req-3")

    assert marked is False
    table.update_item.assert_not_called()


def test_a_different_amount_on_the_same_phone_does_not_match(razorpay, monkeypatch):
    table = fake_table([invoice("INV-1", "+919876543210", "250.00")])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    assert razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-4") is False


def test_a_different_phone_on_the_same_amount_does_not_match(razorpay, monkeypatch):
    table = fake_table([invoice("INV-1", "+919999888877", "100.00")])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    assert razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-5") is False


def test_no_candidates_returns_false_rather_than_raising(razorpay, monkeypatch):
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: fake_table([]))
    assert razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-6") is False


def test_an_unparseable_total_is_skipped_not_fatal(razorpay, monkeypatch):
    """A junk total must not take down the whole reconciliation attempt."""
    table = fake_table([
        {"invoiceId": "INV-BAD", "customerPhone": "+919876543210",
         "total": "not-a-number", "status": "created", "createdAt": 1},
        invoice("INV-GOOD", "+919876543210", "100.00", created=2),
    ])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    assert razorpay._mark_invoice_paid_by_phone_and_amount(
        "+919876543210", 100.00, "req-7") is True
    assert table.update_item.call_args.kwargs["Key"] == {"invoiceId": "INV-GOOD"}


def test_the_full_phone_number_is_not_logged(razorpay, monkeypatch, caplog):
    """Every other log site in this codebase masks to the last four; these did not."""
    table = fake_table([invoice("INV-1", "+919876543210", "100.00")])
    monkeypatch.setattr(razorpay.dynamodb, "Table", lambda _name: table)

    with caplog.at_level("INFO"):
        razorpay._mark_invoice_paid_by_phone_and_amount(
            "+919876543210", 100.00, "req-8")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "9876543210" not in logged
    assert "919876543210" not in logged


# ---------------------------------------------------------------------------
# 2. The GST invoice series must not receive a substitute number
# ---------------------------------------------------------------------------

@pytest.fixture
def invoice_engine(monkeypatch):
    path = str(FUNCTIONS / "payments" / "invoice-engine")
    monkeypatch.syspath_prepend(path)
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415
    yield handler
    sys.modules.pop("handler", None)


def test_a_working_sequence_returns_a_gst_series_number(invoice_engine, monkeypatch):
    table = MagicMock()
    table.update_item.return_value = {"Attributes": {"last_seq": 7, "prefix": "WD"}}
    monkeypatch.setattr(invoice_engine.dynamodb, "Table", lambda _n: table)

    number = invoice_engine._get_next_invoice_number("2026-2027")

    assert number == "WD/2627/00007"


def test_a_broken_sequence_raises_instead_of_inventing_a_number(invoice_engine, monkeypatch):
    """The core of it.

    Rule 46(b) requires a consecutive series for the financial year. A uuid is not
    part of one, so `WD-PAY-TEMP-<uuid>` was not a degraded invoice number, it was
    an invalid one - returned as an ordinary success at the exact moment the system
    had lost track of what the next number should be.
    """
    table = MagicMock()
    table.update_item.side_effect = RuntimeError("counter unreachable")
    monkeypatch.setattr(invoice_engine.dynamodb, "Table", lambda _n: table)

    with pytest.raises(invoice_engine.InvoiceSequenceUnavailable):
        invoice_engine._get_next_invoice_number("2026-2027")


def test_no_temp_number_can_be_constructed(invoice_engine):
    """Assert on the construction, not on mentions.

    The docstring explains the removal and therefore names the old shape, which is
    the point of it. What must not exist is the f-string that built one.
    """
    source = (FUNCTIONS / "payments" / "invoice-engine" / "handler.py").read_text()
    assert 'f"WD-PAY-TEMP' not in source
    assert "f'WD-PAY-TEMP" not in source
    # `WD-PAY-` on its own is a legitimate referenceId prefix and must survive.
    assert "f\"WD-PAY-{uuid.uuid4().hex[:8].upper()}\"" in source


def test_create_invoice_answers_503_and_writes_nothing(invoice_engine, monkeypatch):
    """503 rather than 500: the payload is fine, the counter is not.

    And nothing is written - an invoice numbered outside the series is worse than
    no invoice, because the number cannot be reassigned once it has been sent.
    """
    seq_table = MagicMock()
    seq_table.update_item.side_effect = RuntimeError("counter unreachable")
    monkeypatch.setattr(invoice_engine.dynamodb, "Table", lambda _n: seq_table)

    response = invoice_engine.create_invoice(
        {"customerPhone": "+919876543210", "items": [], "addressLine1": "12 MG Road",
         "city": "Bengaluru", "state": "Karnataka", "postalCode": "560001"}, "req-9")

    assert response["statusCode"] == 503
    import json
    body = json.loads(response["body"])
    assert body["errorCode"] == "INVOICE_SEQUENCE_UNAVAILABLE"
    assert body["retryable"] is True
    seq_table.put_item.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Verification outcome must be recorded, and the flag must exist and be off
# ---------------------------------------------------------------------------

def test_the_four_verification_outcomes_are_named_in_source():
    """A bool cannot distinguish "confirmed" from "never checked".

    The four states are: confirmed by Meta, not checked because there was no
    payment config, not checked because the lookup failed, and actively
    contradicted. Only the last used to be distinguishable from the first.

    SUPERSEDED (2026-10-01, website-only ruling): the in-WhatsApp capture branch no
    longer creates ANY paid state, so the old fail-open accept log
    (``payment_capture_accepted_unverified``) is gone. The verification is retained
    only to compute an auditable outcome, now recorded on the
    ``in_whatsapp_payment_capture_superseded`` record. The three outcome CONSTANTS must
    still be named so the outcome stays legible in that audit trail.
    """
    source = (FUNCTIONS / "messaging" / "inbound-whatsapp-handler" / "handler.py").read_text()
    for name in ("UNVERIFIED_NO_CONFIG", "UNVERIFIED_LOOKUP_FAILED",
                 "REJECTED_MISMATCH", "in_whatsapp_payment_capture_superseded"):
        assert name in source, f"{name} missing"
    # The retired fail-open accept log must be gone: an unverified capture no longer
    # "accepts" anything financial — it is superseded.
    assert "payment_capture_accepted_unverified" not in source
    # The old bool must be gone from live code.
    for line in source.splitlines():
        if "payment_verified" in line:
            assert line.lstrip().startswith("#"), f"live reference: {line.strip()}"


def test_the_fail_closed_flag_exists_and_defaults_off():
    """Tightening this alters live payment acceptance, so it is not switched on here.

    What matters is that the option exists, is a one-line env change, and is not
    on by accident: only an explicit truthy string enables it.
    """
    source = (FUNCTIONS / "messaging" / "inbound-whatsapp-handler" / "handler.py").read_text()
    assert "PAYMENT_LOOKUP_REQUIRED" in source
    assert "os.environ.get('PAYMENT_LOOKUP_REQUIRED', '')" in source
    assert "in ('1', 'true', 'yes', 'on')" in source


def test_an_empty_payments_array_is_not_treated_as_a_confirmation():
    """A 200 with no payments means Meta reported nothing for the reference.

    That is not a confirmation. It previously fell through with the bool still
    True, which is the most easily-missed of the three unverified paths because it
    is on the success branch of the HTTP call.
    """
    source = (FUNCTIONS / "messaging" / "inbound-whatsapp-handler" / "handler.py").read_text()
    assert "payment_lookup_empty" in source


# ---------------------------------------------------------------------------
# 4. Writes must not be able to introduce a sixth vocabulary
# ---------------------------------------------------------------------------

def test_for_storage_canonicalises_a_known_alias():
    from lambda_utils import payment_status

    # InvoicesTable and OrderTable say "paid" where PaymentsTable says "captured".
    assert payment_status.for_storage("paid") == payment_status.CAPTURED
    assert payment_status.for_storage("SUCCESS") == payment_status.CAPTURED
    assert payment_status.for_storage("authorised") == payment_status.AUTHORIZED
    assert payment_status.for_storage("pending_payment") == payment_status.PENDING


def test_for_storage_refuses_an_unknown_spelling():
    """The asymmetry with canonical(), which is the whole design.

    Reads degrade to "" because they run on provider input and must not break
    webhook processing. Writes refuse, because we choose the value there and
    letting an unrecognised one through is exactly how five vocabularies
    accumulated.
    """
    from lambda_utils import payment_status

    assert payment_status.canonical("settled") == ""        # read: degrade
    with pytest.raises(ValueError):                          # write: refuse
        payment_status.for_storage("settled")


def test_for_storage_refuses_absence_rather_than_inventing_a_state():
    from lambda_utils import payment_status

    for absent in (None, "", "   ", "none"):
        with pytest.raises(ValueError):
            payment_status.for_storage(absent)
