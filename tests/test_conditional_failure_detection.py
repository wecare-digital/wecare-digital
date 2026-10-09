"""Conditional-failure detection on the CAPTURED-PAYMENT path is structural, never a substring.

F-5. Six sites across `razorpay-webhook` and `invoice-engine` decided "was this a DynamoDB
`ConditionalCheckFailedException`?" by asking whether that word appeared in `str(error)`. The
answer to that question decides, on the money path, whether a write that did not happen was an
expected idempotency collision or a real storage failure - and the two outcomes are opposite:
one is an info log and a successful return, the other is an error log, a 500, or a re-raise.

The structural read is `error.response['Error']['Code']`, which
`order_keys.is_conditional_failure` (`order_keys.py:177`) already provides. The two halves below
are what makes the difference measurable, because they are the two ways the rendered message and
the structural code can disagree:

    code present, substring absent   ->  every site must take its IDEMPOTENT branch
    code absent, substring present   ->  every site must take its ERROR branch

Both halves fail against the substring test, in OPPOSITE directions, which is why they are
written as a pair: a change that broke one would have to break the other the other way round to
pass. The first half needs a test-local `ClientError` subclass, because `botocore` interpolates
`Error.Code` into `MSG_TEMPLATE`, so a plain `ClientError` can never carry the code with the
substring absent. No production subclass of `ClientError` is introduced by F-5, and
`is_conditional_failure` itself is unchanged.

THE SIXTH SITE IS NEGATED. `invoice-engine.create_invoice`'s atomic claim asks the question the
other way round (`if not ...`), because for it the conditional failure is the EXPECTED outcome -
the duplicate-invoice race it exists to catch. Its two branches are therefore swapped relative to
the webhook's five: a conditional failure is a 200 dedup hit, and anything else is the 500. That
is the whole reason this file drives all six sites rather than unit-testing the predicate.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import pathlib
import sys
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import order_keys  # noqa: E402

WEBHOOK_PATH = ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"
ENGINE_PATH = ROOT / "amplify/functions/payments/invoice-engine/handler.py"

REFERENCE = "WD-PAY-ABCDEFGHJKMNPQ"
PAYMENT_ID = "pay_LIVE0000000001"
INVOICE_ID = "inv-0000000000000000000000000000cafe"
REQUEST = "req-conditional-1"
#: One of `_PHONE_ID_TO_WABA`'s keys, so the flow-resolution chain reaches the env default.
PHONE_ID = "phone-number-id-waba1-direct-1016149501586345"
FLOW_ID = "1234567890"


def _load(name: str, path: pathlib.Path):
    """Load a handler BY PATH under a unique module name, never `import handler`.

    64 files in this repo are called `handler.py`, so `sys.modules['handler']` is one contended
    slot; `tests/test_handler_import_isolation.py` is the gate that caught that. `boto3` is
    patched for the duration because both modules build a resource and a client at import.
    """
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


webhook = _load("wecare_razorpay_webhook_handler_f5", WEBHOOK_PATH)
engine = _load("wecare_invoice_engine_handler_f5", ENGINE_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# The two fixtures: the structural code and the rendered message, disagreeing
# ══════════════════════════════════════════════════════════════════════════════

class OpaqueConditionalFailure(ClientError):
    """Carries the structural code while rendering a message that lacks it.

    Not a hypothetical: boto3 wrappers, retry shims and re-raises routinely replace the rendered
    message while preserving `.response`. The substring test is what breaks then. Test-local by
    design - F-5 introduces no production subclass of `ClientError`.
    """

    def __str__(self) -> str:
        return "storage error"


def _opaque() -> ClientError:
    """A real conditional failure whose rendered message does not say so."""
    return OpaqueConditionalFailure(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "storage error"}},
        "UpdateItem",
    )


def _substring_only() -> ClientError:
    """A real storage failure whose rendered message happens to name the other one.

    No subclass needed: `ClientError` interpolates `Code` and appends `Message`, so supplying the
    word in `Message` is enough to make `str(error)` contain it while the code says otherwise.
    """
    return ClientError(
        {"Error": {"Code": "ValidationException",
                   "Message": "schema does not support ConditionalCheckFailedException here"}},
        "UpdateItem",
    )


def test_the_premise_a_conditional_failure_can_render_without_its_own_code():
    error = _opaque()
    assert "ConditionalCheckFailedException" not in str(error)
    assert order_keys.is_conditional_failure(error) is True


def test_the_mirror_premise_another_failure_can_render_with_that_code():
    error = _substring_only()
    assert "ConditionalCheckFailedException" in str(error)
    assert order_keys.is_conditional_failure(error) is False


# ══════════════════════════════════════════════════════════════════════════════
# The rig: one raising table, one recording lambda client, six real call sites
# ══════════════════════════════════════════════════════════════════════════════

class _RaisingTable:
    """Every write raises the injected error; reads answer the minimum each site needs."""

    def __init__(self, error: Exception, *, rows=None, item=None) -> None:
        self.error = error
        self.rows = list(rows or [])
        self.item = dict(item or {})

    def update_item(self, **_):
        raise self.error

    def put_item(self, **_):
        raise self.error

    def query(self, **_):
        return {"Items": [dict(row) for row in self.rows]}

    def scan(self, **_):
        return {"Items": []}

    def get_item(self, **_):
        return {"Item": dict(self.item)} if self.item else {}


class _OneTable:
    """A `boto3.resource('dynamodb')` stand-in handing the same fake to every table name.

    Deliberately indiscriminate: each site below opens exactly one table whose write is under
    test, and the incidental reads the surrounding code makes (a contact row, a service-request
    id write) are already inside their own `except: pass`, so answering them from the same fake
    cannot change which branch was taken.
    """

    def __init__(self, table) -> None:
        self.table = table

    def Table(self, _name):  # noqa: N802 - the boto3 resource spelling
        return self.table


class _RecordingLambda:
    """The outbound boundary. Its call count is what "no duplicate side effect" means here."""

    def __init__(self) -> None:
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def _events(caplog):
    """The `event` field of every structured record, paired with its level name."""
    out = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and "event" in payload:
            out.append((payload["event"], record.levelname))
    return out


def _names(caplog):
    return [event for event, _level in _events(caplog)]


# ── the five razorpay-webhook sites ───────────────────────────────────────────

def _drive_post_payment_flow_guard(error, caplog, monkeypatch):
    """`_trigger_post_payment_flow`'s one-flow-per-payment guard (the `guard_err` site)."""
    monkeypatch.setenv("POST_PAYMENT_FLOW_WABA1", FLOW_ID)
    sender = _RecordingLambda()
    monkeypatch.setattr(webhook, "dynamodb", _OneTable(_RaisingTable(error)))
    monkeypatch.setattr(webhook, "lambda_client", sender)
    webhook._trigger_post_payment_flow("918100640044", PHONE_ID, REFERENCE, {}, REQUEST,
                                       invoice_id=INVOICE_ID)
    return sender


def _drive_store_payment_record(error, caplog, monkeypatch):
    """`_store_payment_record`'s monotonic rank-guarded put (the `:2036` site)."""
    monkeypatch.setattr(webhook, "dynamodb", _OneTable(_RaisingTable(error)))
    webhook._store_payment_record(
        {"id": PAYMENT_ID, "amount": 10193, "currency": "INR",
         "notes": {"referenceId": REFERENCE}}, "captured", REQUEST)


def _drive_mark_invoice_paid(error, caplog, monkeypatch):
    """`_mark_invoice_paid_by_reference`'s single-row conditional settle (the `cond_err` site)."""
    table = _RaisingTable(error, rows=[{"invoiceId": INVOICE_ID, "status": "sent",
                                        "referenceId": REFERENCE}])
    monkeypatch.setattr(webhook, "dynamodb", _OneTable(table))
    return webhook._mark_invoice_paid_by_reference(REFERENCE, REQUEST, payment_id=PAYMENT_ID)


def _drive_handle_refund(error, caplog, monkeypatch):
    """`_handle_refund`'s monotonic refund write (the `:2746` site)."""
    monkeypatch.setattr(webhook, "dynamodb", _OneTable(_RaisingTable(error)))
    webhook._handle_refund("refund.processed", {"refund": {"entity": {
        "id": "rfnd_LIVE0000000001", "payment_id": PAYMENT_ID, "amount": 10193,
        "status": "processed"}}}, REQUEST)


def _drive_store_settlement_record(error, caplog, monkeypatch):
    """`_store_settlement_record`'s conditional insert (the `:2866` site)."""
    monkeypatch.setattr(webhook, "dynamodb", _OneTable(_RaisingTable(error)))
    webhook._store_settlement_record("setl_LIVE0000000001", 10193, {"status": "processed"},
                                     REQUEST)


#: site id -> (driver, idempotent-branch event, error-branch event)
WEBHOOK_SITES = {
    "post_payment_flow_guard": (_drive_post_payment_flow_guard,
                                "post_payment_flow_skipped", "post_payment_flow_guard_error"),
    "store_payment_record": (_drive_store_payment_record,
                             "payment_status_not_applied", "payment_store_error"),
    "mark_invoice_paid": (_drive_mark_invoice_paid,
                          "invoice_already_paid_on_settle", "mark_invoice_paid_error"),
    "handle_refund": (_drive_handle_refund,
                      "refund_status_not_applied", "refund_update_error"),
    "store_settlement_record": (_drive_store_settlement_record,
                                "settlement_record_exists", "settlement_record_error"),
}


# ══════════════════════════════════════════════════════════════════════════════
# Half 1 - the code is present and the substring is absent: IDEMPOTENT branch
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("site", sorted(WEBHOOK_SITES))
def test_an_opaque_conditional_failure_is_idempotent_at_every_webhook_site(site, caplog,
                                                                          monkeypatch):
    driver, idempotent_event, error_event = WEBHOOK_SITES[site]
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    driver(_opaque(), caplog, monkeypatch)
    events = _events(caplog)
    assert (idempotent_event, "INFO") in events, f"{site} did not take the idempotent branch"
    if error_event is not None:
        assert error_event not in [name for name, _ in events]


def test_an_opaque_conditional_failure_sends_no_second_post_payment_flow(caplog, monkeypatch):
    """The guard site's side effect, not just its log: an already-sent flow is not re-sent."""
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    sender = _drive_post_payment_flow_guard(_opaque(), caplog, monkeypatch)
    assert sender.calls == []
    assert "post_payment_flow_sent" not in _names(caplog)


def test_an_opaque_conditional_failure_reports_the_invoice_as_settled(caplog, monkeypatch):
    """`_mark_invoice_paid_by_reference` returns True: the row IS paid, just not by this call."""
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    assert _drive_mark_invoice_paid(_opaque(), caplog, monkeypatch) is True


def test_an_opaque_conditional_failure_is_a_dedup_hit_in_the_invoice_engine(caplog, monkeypatch):
    """The NEGATED sixth site. A conditional failure here is the expected duplicate race: a 200
    dedup hit with no invoice number consumed, never a 500."""
    caplog.set_level(logging.INFO, logger=engine.logger.name)
    table = _RaisingTable(_opaque(), item={"invoiceId": INVOICE_ID, "invoiceNumber": "WD/25-26/0007",
                                           "total": 1180, "referenceId": REFERENCE})
    monkeypatch.setattr(engine, "dynamodb", _OneTable(table))
    response = engine.create_invoice({"referenceId": REFERENCE, "paymentId": PAYMENT_ID}, REQUEST)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["deduplicated"] is True and body["invoiceNumber"] == "WD/25-26/0007"
    events = _events(caplog)
    assert ("invoice_dedup_hit_atomic", "INFO") in events
    assert "invoice_claim_error" not in [name for name, _ in events]


# ══════════════════════════════════════════════════════════════════════════════
# Half 2 - the code is absent and the substring is present: ERROR branch
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("site", sorted(site for site in WEBHOOK_SITES
                                        if WEBHOOK_SITES[site][2] is not None))
def test_a_substring_lookalike_is_an_error_at_every_webhook_site(site, caplog, monkeypatch):
    driver, idempotent_event, error_event = WEBHOOK_SITES[site]
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    driver(_substring_only(), caplog, monkeypatch)
    events = _events(caplog)
    assert error_event in [name for name, _ in events], \
        f"{site} did not take the error branch"
    assert (idempotent_event, "INFO") not in events


def test_a_substring_lookalike_reports_the_invoice_as_not_settled(caplog, monkeypatch):
    """`_mark_invoice_paid_by_reference` is the one site whose error branch is a bare `raise`.

    That `raise` lands in the function's own outer handler, which reports False - "we cannot
    confirm a row was settled" - so the legacy caller releases its one-time claim instead of
    stranding the payment. Reporting True here would record a settled invoice that storage
    refused to write.
    """
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    assert _drive_mark_invoice_paid(_substring_only(), caplog, monkeypatch) is False
    assert "invoice_already_paid_on_settle" not in _names(caplog)


def test_a_substring_lookalike_still_sends_the_post_payment_flow_once(caplog, monkeypatch):
    """The guard site's error branch logs and continues: the flow is sent once, not suppressed.

    A storage failure on the idempotency guard must not silently cost the customer the flow they
    paid to receive - that is the silent partial success this audit exists to find.
    """
    caplog.set_level(logging.INFO, logger=webhook.logger.name)
    sender = _drive_post_payment_flow_guard(_substring_only(), caplog, monkeypatch)
    assert len(sender.calls) == 1
    assert "post_payment_flow_sent" in _names(caplog)


def test_a_substring_lookalike_is_a_500_in_the_invoice_engine(caplog, monkeypatch):
    """The NEGATED site, mirrored. A real storage failure must NOT be reported as a dedup hit: a
    silent 200 there would hand the caller an invoice id that was never written."""
    caplog.set_level(logging.INFO, logger=engine.logger.name)
    monkeypatch.setattr(engine, "dynamodb", _OneTable(_RaisingTable(_substring_only())))
    response = engine.create_invoice({"referenceId": REFERENCE, "paymentId": PAYMENT_ID}, REQUEST)
    assert response["statusCode"] == 500
    events = _events(caplog)
    assert "invoice_claim_error" in [name for name, _ in events]
    assert "invoice_dedup_hit_atomic" not in [name for name, _ in events]


# ══════════════════════════════════════════════════════════════════════════════
# The invariant, stated as a test so a new copy of the substring check fails here
# ══════════════════════════════════════════════════════════════════════════════

def test_no_payment_function_decides_a_conditional_failure_from_a_rendered_message():
    """Every site under `amplify/functions/payments` reads the structural code.

    Source-level, because a behavioural test can only cover the sites that exist today. The eight
    remaining substring sites under `core/`, `messaging/` and `shared/` are deliberately out of
    F-5's scope - they are not on the captured-payment path - so this assertion is scoped to
    `payments/` rather than to the tree.
    """
    offenders = []
    for path in sorted((ROOT / "amplify/functions/payments").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if "'ConditionalCheckFailedException'" in line and "str(" in line:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
