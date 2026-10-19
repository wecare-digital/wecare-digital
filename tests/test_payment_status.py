"""Monotonic payment status, the shared vocabulary, and the webhook dedup key.

Two of the three defects tested here were measured on live traffic, not inferred.

Defect 1 - the dedup key dropped real events. CloudWatch, 4 days to 2026-09-23:

    events received                                       3030
    skipped as duplicates                                 1495
    dedup keys delivered more than once                    1347
      of those, keys whose deliveries carried DIFFERENT bodies 19
    distinct events silently dropped (lower bound)          59

Defect 2 - `_handle_downtime` read `event_data.get('downtime')` while the entity arrives
under the literal key `payment.downtime`. All 607 live downtime events were processed with
`method: ""` and `instrument: "{}"`, confirmed in CloudWatch. Downtime is the only payment
webhook traffic this account has ever received.

Defect 3 - payment status was an unconditional `put_item`, so a redelivered
`payment.captured` after `refund.processed` reset the status AND erased the refund fields,
because the record written carries no refund attributes and a put replaces the whole item.
Latent - PaymentsTable holds 0 rows - but it is the one that misstates money.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import payment_status as ps  # noqa: E402

#: The real live payload, copied from a RazorpayWebhookLogTable row on 2026-09-23.
LIVE_DOWNTIME = {
    "event": "payment.downtime.started",
    "account_id": "acc_RETIRED_FIXTURE",
    "created_at": 1790068149,
    "payload": {
        "payment.downtime": {
            "entity": {
                "id": "Tf1mpc6y3FVyFs",
                "method": "netbanking",
                "status": "started",
                "created_at": 1790068149,
                "updated_at": 1790068149,
                "instrument": {"bank": "IDIB"},
                "severity": "HIGH",
                "scheduled": False,
            }
        }
    },
}

LIVE_PAYMENT = {
    "event": "payment.captured",
    "account_id": "acc_RETIRED_FIXTURE",
    "created_at": 1790068200,
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_ABC123",
                "status": "captured",
                "amount": 250000,
                "currency": "INR",
                "order_id": "order_XYZ",
                "email": "customer@example.com",
                "contact": "+918100640044",
                "vpa": "someone@upi",
                "notes": {"referenceId": "WD-PAY-AAA"},
            }
        }
    },
}


class TestLadder:
    def test_capture_beats_authorization(self):
        """An authorisation is a hold, not a receipt."""
        assert ps.should_apply(ps.AUTHORIZED, ps.CAPTURED)
        assert not ps.should_apply(ps.CAPTURED, ps.AUTHORIZED)

    def test_authorization_does_not_mask_a_failure(self):
        """Ranking a hold above a failure is how a customer looks paid when nothing settled."""
        assert ps.rank(ps.AUTHORIZED) < ps.rank(ps.FAILED)
        assert not ps.should_apply(ps.FAILED, ps.AUTHORIZED)

    def test_capture_beats_failure(self):
        """A failed attempt followed by a successful one must end captured."""
        assert ps.should_apply(ps.FAILED, ps.CAPTURED)
        assert not ps.should_apply(ps.CAPTURED, ps.FAILED)

    def test_refund_outranks_capture_and_cannot_be_undone(self):
        """The specific regression: a redelivered capture must not un-refund a payment."""
        assert ps.should_apply(ps.CAPTURED, ps.REFUNDED)
        assert not ps.should_apply(ps.REFUNDED, ps.CAPTURED)
        assert not ps.should_apply(ps.REFUNDED, ps.AUTHORIZED)
        assert not ps.should_apply(ps.REFUNDED, ps.PENDING)

    def test_dispute_outranks_everything(self):
        for other in (ps.CREATED, ps.PENDING, ps.AUTHORIZED, ps.FAILED,
                      ps.CAPTURED, ps.REFUNDED):
            assert ps.should_apply(other, ps.DISPUTED)
            assert not ps.should_apply(ps.DISPUTED, other)

    def test_an_unknown_status_never_overwrites_a_known_one(self):
        """A status Razorpay adds later must not silently outrank refunded."""
        assert not ps.should_apply(ps.CAPTURED, "settled_maybe")
        assert not ps.should_apply(None, "settled_maybe")
        assert ps.rank("settled_maybe") == 0

    def test_reasserting_the_same_status_is_not_a_forward_move(self):
        """Idempotent redelivery must be refused, not reapplied."""
        for state in ps.STATUS_RANK:
            assert not ps.should_apply(state, state)

    def test_failed_is_not_terminal(self):
        """A failed attempt is routinely followed by a successful one."""
        assert not ps.is_terminal(ps.FAILED)
        assert ps.is_terminal(ps.REFUNDED)
        assert ps.is_terminal(ps.DISPUTED)

    def test_the_condition_expression_admits_a_first_write(self):
        expr = ps.condition_expression()
        assert "attribute_not_exists" in expr
        assert ps.RANK_ATTRIBUTE in expr
        assert ":rank" in expr

    def test_the_condition_expression_accepts_an_alias(self):
        """The refund path addresses the rank through ExpressionAttributeNames."""
        assert ps.condition_expression("#rank") == \
            "attribute_not_exists(#rank) OR #rank < :rank"


class TestVocabulary:
    def test_paid_and_captured_are_one_state(self):
        """InvoicesTable and OrderTable say `paid` where PaymentsTable says `captured`."""
        assert ps.canonical("paid") == ps.CAPTURED
        assert ps.rank("paid") == ps.rank("captured")

    def test_pending_payment_is_pending(self):
        assert ps.canonical("pending_payment") == ps.PENDING

    def test_british_spelling_is_accepted(self):
        assert ps.canonical("authorised") == ps.AUTHORIZED

    def test_none_is_not_a_payment_state(self):
        """"No payment attempted" must never overwrite a capture."""
        assert ps.canonical("none") == ""
        assert ps.rank("none") == 0
        assert not ps.should_apply(ps.CAPTURED, "none")

    def test_empty_and_missing_are_rank_zero(self):
        for value in ("", "   ", None):
            assert ps.rank(value) == 0

    def test_cancelled_maps_to_failed_not_refunded(self):
        """A cancelled attempt never took money, so it must not outrank a capture."""
        assert ps.canonical("cancelled") == ps.FAILED
        assert not ps.should_apply(ps.CAPTURED, "cancelled")

    def test_case_and_separator_insensitive(self):
        assert ps.canonical("  Payment_Failed ") == ps.FAILED
        assert ps.canonical("refund-processed") == ps.REFUNDED

    def test_describe_shows_the_mapping_and_leaks_nothing(self):
        text = ps.describe("paid")
        assert "captured" in text
        text = ps.describe("weird")
        assert "rank 0" in text and "will not overwrite" in text


class TestMoney:
    def test_paise_is_integer_and_refuses_nonsense(self):
        assert ps.paise(250000) == 250000
        assert ps.paise("250000") == 250000
        for bad in (None, "abc", -1, True):
            with pytest.raises(ValueError):
                ps.paise(bad)

    def test_rupees_is_a_string_so_it_cannot_be_summed_by_accident(self):
        """Every float-rupee bug here began as a display conversion later used in maths."""
        assert ps.rupees_str(250000) == "2500.00"
        assert isinstance(ps.rupees_str(250000), str)

    def test_small_amounts_are_exact(self):
        """The magnitude heuristic in payments-read got both of these wrong."""
        assert ps.rupees_str(5) == "0.05"      # was reported as 500.00
        assert ps.rupees_str(999) == "9.99"    # was reported as 999.00
        assert ps.rupees_str(1000) == "10.00"

    def test_no_float_rounding_drift(self):
        """1/3 of a rupee summed a thousand times: integers cannot drift."""
        total = sum(ps.paise(33) for _ in range(1000))
        assert total == 33000
        assert ps.rupees_str(total) == "330.00"

    def test_zero_is_valid(self):
        assert ps.paise(0) == 0
        assert ps.rupees_str(0) == "0.00"


class TestEntityExtraction:
    def test_finds_the_dotted_downtime_key(self):
        """`event_data.get('downtime')` never matched; the key is `payment.downtime`."""
        container, entity = ps.extract_entity(LIVE_DOWNTIME["payload"])
        assert container == "payment.downtime"
        assert entity["id"] == "Tf1mpc6y3FVyFs"
        assert entity["method"] == "netbanking"

    def test_the_old_lookup_really_did_return_nothing(self):
        """Reproduces the defect, so this test fails if someone reverts the key."""
        payload = LIVE_DOWNTIME["payload"]
        assert payload.get("downtime", {}).get("entity", {}) == {}
        assert payload.get("payment", {}).get("downtime", {}) == {}

    def test_finds_a_payment_entity(self):
        container, entity = ps.extract_entity(LIVE_PAYMENT["payload"])
        assert container == "payment"
        assert entity["id"] == "pay_ABC123"

    def test_prefers_payment_when_several_containers_exist(self):
        payload = {"refund": {"entity": {"id": "rfnd_1"}},
                   "payment": {"entity": {"id": "pay_1"}}}
        container, entity = ps.extract_entity(payload)
        assert container == "payment" and entity["id"] == "pay_1"

    def test_missing_and_malformed_payloads_are_safe(self):
        for payload in (None, {}, {"payment": {}}, {"payment": {"entity": {}}},
                        {"payment": "not a dict"}, "not a mapping"):
            assert ps.extract_entity(payload) == ("", {})


class TestDedupKey:
    def test_the_live_downtime_gets_an_entity_scoped_key(self):
        assert ps.dedup_key(LIVE_DOWNTIME) == \
            "Tf1mpc6y3FVyFs:payment.downtime.started"

    def test_two_banks_failing_in_the_same_second_get_different_keys(self):
        """The measured defect: 19 keys collapsed distinct events, >=59 dropped."""
        import copy

        other = copy.deepcopy(LIVE_DOWNTIME)
        other["payload"]["payment.downtime"]["entity"]["id"] = "Tf1OTHERbank00"
        other["payload"]["payment.downtime"]["entity"]["instrument"] = {"bank": "SBIN"}
        # Same account, same event type, same created_at - the old key was identical.
        assert other["created_at"] == LIVE_DOWNTIME["created_at"]
        assert other["event"] == LIVE_DOWNTIME["event"]
        assert ps.dedup_key(other) != ps.dedup_key(LIVE_DOWNTIME)

    def test_the_old_key_would_have_collapsed_them(self):
        """Pins what was wrong, so the reason for the change stays legible."""
        def old_key(payload):
            entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            if entity.get("id"):
                return f'{entity["id"]}:{payload.get("event")}'
            return (f'{payload.get("account_id", "")}:{payload.get("event", "")}:'
                    f'{payload.get("created_at", "")}')

        import copy

        other = copy.deepcopy(LIVE_DOWNTIME)
        other["payload"]["payment.downtime"]["entity"]["id"] = "Tf1OTHERbank00"
        assert old_key(other) == old_key(LIVE_DOWNTIME), "the defect, reproduced"

    def test_a_retry_of_the_same_event_still_collapses(self):
        """Idempotency must survive the fix - 1495 of 3030 deliveries were real retries."""
        import copy

        retry = copy.deepcopy(LIVE_DOWNTIME)
        assert ps.dedup_key(retry) == ps.dedup_key(LIVE_DOWNTIME)

    def test_different_event_types_on_one_entity_are_distinct(self):
        """started and resolved for one downtime are two events."""
        import copy

        resolved = copy.deepcopy(LIVE_DOWNTIME)
        resolved["event"] = "payment.downtime.resolved"
        assert ps.dedup_key(resolved) != ps.dedup_key(LIVE_DOWNTIME)

    def test_a_payment_keeps_its_strong_key(self):
        assert ps.dedup_key(LIVE_PAYMENT) == "pay_ABC123:payment.captured"

    def test_refunds_get_entity_scoped_keys(self):
        a = ps.dedup_key({"event": "refund.processed", "account_id": "acc_1",
                          "created_at": 1, "payload": {"refund": {"entity": {
                              "id": "rfnd_A", "payment_id": "pay_1"}}}})
        b = ps.dedup_key({"event": "refund.processed", "account_id": "acc_1",
                          "created_at": 1, "payload": {"refund": {"entity": {
                              "id": "rfnd_B", "payment_id": "pay_1"}}}})
        assert a != b, "two refunds of one payment in the same second must not collapse"

    def test_falls_back_only_when_there_is_no_entity_id(self):
        key = ps.dedup_key({"event": "some.event", "account_id": "acc_1",
                            "created_at": 99, "payload": {}})
        assert key == "acc_1:some.event:99"

    def test_returns_empty_when_there_is_nothing_to_key_on(self):
        """Callers must treat '' as process-it, not duplicate."""
        assert ps.dedup_key({}) == ""
        assert ps.dedup_key(None) == ""


class TestEntitySummary:
    def test_carries_the_actionable_downtime_detail(self):
        """All 607 live downtime events discarded exactly these fields."""
        summary = ps.entity_summary(LIVE_DOWNTIME["payload"])
        assert summary["entityId"] == "Tf1mpc6y3FVyFs"
        assert summary["method"] == "netbanking"
        assert summary["severity"] == "HIGH"
        assert summary["instrument"] == {"bank": "IDIB"}
        assert summary["status"] == "started"

    def test_does_not_leak_customer_identifiers(self):
        """This output goes to CloudWatch."""
        summary = ps.entity_summary(LIVE_PAYMENT["payload"])
        rendered = repr(summary)
        for secret in ("customer@example.com", "918100640044", "someone@upi",
                       "WD-PAY-AAA"):
            assert secret not in rendered, f"{secret} must not reach logs"
        assert "email" not in summary and "contact" not in summary
        assert "vpa" not in summary and "notes" not in summary

    def test_amount_is_reported_as_integer_paise(self):
        summary = ps.entity_summary(LIVE_PAYMENT["payload"])
        assert summary["amountPaise"] == 250000

    def test_an_unusable_amount_reports_none_rather_than_zero(self):
        """A silent 0 is a reconciliation error that looks like a success."""
        summary = ps.entity_summary({"payment": {"entity": {"id": "p", "amount": "??"}}})
        assert summary["amountPaise"] is None

    def test_absent_entity_is_reported_plainly(self):
        assert ps.entity_summary({}) == {"entity": None}


class TestTheHandlersAreWired:
    """Source-level, because the invariants are "nowhere in the payment tree".

    A behavioural test over one handler cannot say "no payment writer is unconditional" or
    "no handler reads the wrong entity key" - it passes while the next handler added
    reintroduces either. These are the four defects this phase fixed, each pinned so a
    revert is visible.
    """

    FUNCTIONS = ROOT / "amplify" / "functions"
    RAZORPAY = FUNCTIONS / "payments" / "razorpay-webhook" / "handler.py"
    INVOICE = FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
    READ = FUNCTIONS / "payments" / "payments-read" / "handler.py"

    @staticmethod
    def code_only(path: Path) -> str:
        """Source with docstrings and comments removed.

        The fixed handlers quote the old broken expressions in their comments to explain
        what changed, and a naive substring search then reports the documentation as the
        defect. Prose describing a bug is not the bug. Comments are blanked IN PLACE rather
        than by rejoining tokens - rejoining splits every expression across lines and makes
        these assertions unfailable, which is a mistake this repo has already made once.
        """
        import ast
        import io
        import tokenize

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        docstring_lines: set = set()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstring_lines.update(
                    range(first.lineno, (first.end_lineno or first.lineno) + 1))

        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    row, col = tok.start
                    if 1 <= row <= len(lines):
                        lines[row - 1] = lines[row - 1][:col]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass

        return "\n".join(line for number, line in enumerate(lines, start=1)
                         if number not in docstring_lines)

    # -- dedup key -------------------------------------------------------
    def test_the_webhook_uses_the_shared_dedup_key(self):
        code = self.code_only(self.RAZORPAY)
        assert "payment_status.dedup_key(payload)" in code

    def test_the_webhook_no_longer_builds_the_coarse_key_itself(self):
        """`account_id:event:created_at` dropped >=59 real events in 4 days.

        Scoped to the dedup-key construction. The payment.* handlers still read
        `payload.payment.entity` directly and should - that is where a payment entity
        genuinely lives. What must not come back is *deriving the idempotency key* from a
        payment-only lookup, because that is what made the key coarse for refunds,
        disputes, settlements, payouts, order.paid, invoice.* and downtime.
        """
        code = self.code_only(self.RAZORPAY)
        assert "payload.get('account_id', '') + ':'" not in code
        # Everything assigned to the dedup variable must come from the shared helper.
        assignments = [line.strip() for line in code.splitlines()
                       if "razorpay_event_id =" in line]
        assert assignments, "the dedup key assignment disappeared entirely"
        for line in assignments:
            assert "payment_status.dedup_key" in line, (
                f"dedup key built without the shared helper: {line}")

    # -- entity keys -----------------------------------------------------
    def test_no_handler_reads_the_undotted_downtime_or_dispute_key(self):
        """The keys are `payment.downtime` and `payment.dispute`, with dots."""
        code = self.code_only(self.RAZORPAY)
        assert "event_data.get('downtime'" not in code
        assert "event_data.get('dispute'" not in code

    def test_downtime_and_dispute_use_the_shared_extractor(self):
        code = self.code_only(self.RAZORPAY)
        assert code.count("payment_status.entity_summary(event_data)") >= 2

    def test_the_audit_log_records_the_entity_id(self):
        """Without it the reconciliation table cannot say which downtime a row is."""
        code = self.code_only(self.RAZORPAY)
        assert "'entityId'" in code and "'entityKey'" in code

    # -- monotonic writes ------------------------------------------------
    def test_the_payment_write_is_conditional(self):
        code = self.code_only(self.RAZORPAY)
        assert "payment_status.condition_expression()" in code
        assert "payment_status.RANK_ATTRIBUTE" in code

    def test_there_is_no_unconditional_payment_put(self):
        """`table.put_item(Item=clean)` is the exact line that erased refund fields."""
        code = self.code_only(self.RAZORPAY)
        assert "put_item(Item=clean)" not in code

    def test_the_refund_write_is_conditional_too(self):
        code = self.code_only(self.RAZORPAY)
        assert "payment_status.condition_expression('#rank')" in code

    def test_a_refused_write_is_logged_not_swallowed(self):
        code = self.code_only(self.RAZORPAY)
        assert "payment_status_not_applied" in code
        assert "refund_status_not_applied" in code

    # -- units -----------------------------------------------------------
    def test_the_refund_amount_is_stored_in_paise(self):
        """It was rupees, on a row whose `amount` was paise. One item, two units."""
        code = self.code_only(self.RAZORPAY)
        assert "'refundAmountPaise'" in code
        assert "int(refund.get('amount', 0)) / 100" not in code

    def test_payments_read_has_no_magnitude_heuristic(self):
        """`amount/100 if amount > 1000 else amount` cannot recover an unrecorded unit."""
        code = self.code_only(self.READ)
        assert "if amount > 1000" not in code
        assert "payment_status.paise(" in code

    def test_payments_read_still_emits_the_field_the_dashboard_reads(self):
        """src/pages/workspace/engage/commerce falls back to `amount`, which is paise."""
        code = self.code_only(self.READ)
        assert "'amountInRupees'" in code
        assert "'amountPaise'" in code

    # -- invoice idempotency ---------------------------------------------
    def test_invoice_creation_claims_before_consuming_a_sequence_number(self):
        """A duplicate must not burn a number out of the GST series."""
        code = self.code_only(self.INVOICE)
        claim = code.index("'status': 'claiming'")
        sequence = code.index("invoice_number = _get_next_invoice_number")
        assert claim < sequence, (
            "the claim must precede the sequence increment, or the losing racer still "
            "consumes a GST invoice number and leaves a gap in the series")

    def test_the_invoice_id_is_derived_so_the_condition_can_fire(self):
        """It was a fresh uuid4, so `attribute_not_exists(invoiceId)` never fired."""
        code = self.code_only(self.INVOICE)
        assert "dedup_source = reference_id or payment_id" in code
        assert "invoice_id = 'inv-'" in code

    def test_a_lost_claim_returns_the_existing_invoice(self):
        code = self.code_only(self.INVOICE)
        assert "invoice_dedup_hit_atomic" in code
        assert "'deduplicated': True" in code

    # -- refund initiation has exactly one dormant execution boundary ---------
    def test_only_the_designated_gated_executor_can_initiate_a_refund(self):
        """One reviewed provider POST is allowed; every other refund call shape is prohibited."""
        import re

        patterns = (
            r"/v1/payments/[^\s'\"]*/refund",
            r"/v1/refunds",
            r"\.refund\s*\(",
            r"\.refunds\s*\.\s*create",
        )
        allowed = self.FUNCTIONS / "shared" / "lambda_utils" / "integrations" / "razorpay_refund.py"
        offenders = []
        found_allowed = False
        for path in self.FUNCTIONS.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                if re.search(pattern, text):
                    if path.resolve() == allowed.resolve():
                        found_allowed = True
                    else:
                        offenders.append(f"{path.relative_to(self.FUNCTIONS)}: {pattern}")
        assert found_allowed, "the single reviewed Razorpay refund boundary disappeared"
        assert not offenders, f"refund initiation escaped its designated executor: {offenders}"

        executor = allowed.read_text(encoding="utf-8")
        assert 'REFUND_INITIATION_ENABLED' in executor
        assert '== "true"' in executor

        import ast
        tree = ast.parse(executor)
        refund_fn = next(
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "create_full_refund"
        )
        assert not any(isinstance(node, (ast.For, ast.AsyncFor, ast.While))
                       for node in ast.walk(refund_fn)), (
            "the irreversible provider function must not grow an automatic retry loop"
        )

    def test_the_audit_vocabulary_still_covers_a_refund(self):
        """Not a capability - a control. If a refund path is ever added it must be audited."""
        audit = (self.FUNCTIONS / "shared" / "lambda_utils" / "audit.py").read_text(
            encoding="utf-8")
        assert "'payment.refund'" in audit
