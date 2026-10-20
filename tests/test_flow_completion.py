"""The single idempotent Flow completion writer.

Why this file exists
--------------------
Measured on 2026-09-22: four writers into `FlowSubmissionTable` across two Lambdas, two row
shapes, and only two guarded. The encrypted `/flow-data` endpoint - the transport for nine
flows - had no deduplication of any kind and no `wamid` to key on.

One duplicated paid `submit_request` completion produced 2 submission rows, 2 invoices,
**2 payment links sent to the customer**, and 2 confirmation messages.

What is pinned here is the decision that makes that impossible, and the decisions that could
reasonably have gone the other way:

* the key is `(flow_token, screen)` - coarse on purpose
* an absent token degrades to hashing the payload, it does **not** merge every tokenless
  completion into one row
* the customer-facing reference is *derived*, so a retry shows the same request number
* `status='error'` refuses side effects, because an unknown claim state is not permission
  to send a second payment link
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
for path in (str(SHARED), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402
from lambda_utils import flow_completion as fc  # noqa: E402

TOKEN = "sr-3f2a91c4-0000-4aaa-bbbb-000000000001-waba-1-ph-918100640044"
OTHER_TOKEN = "sr-99999999-0000-4aaa-bbbb-000000000002-waba-1-ph-918100640044"


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDynamo({fc.FLOW_SUBMISSIONS_TABLE: "submissionId"},
                      {fc.FLOW_SUBMISSIONS_TABLE: {}})
    monkeypatch.setattr(fc, "_table",
                        lambda: fake.Table(fc.FLOW_SUBMISSIONS_TABLE))
    return fake


class TestCompletionKey:
    def test_same_token_and_screen_is_the_same_completion(self):
        a, _ = fc.completion_key(TOKEN, "REVIEW")
        b, _ = fc.completion_key(TOKEN, "REVIEW")
        assert a == b

    def test_a_new_flow_message_is_a_new_completion(self):
        """The escape hatch: a genuine second request comes with a new token."""
        a, _ = fc.completion_key(TOKEN, "REVIEW")
        b, _ = fc.completion_key(OTHER_TOKEN, "REVIEW")
        assert a != b

    def test_a_different_terminal_screen_is_a_different_event(self):
        a, _ = fc.completion_key(TOKEN, "REVIEW")
        b, _ = fc.completion_key(TOKEN, "DETAILS")
        assert a != b

    def test_screen_is_case_and_space_insensitive(self):
        a, _ = fc.completion_key(TOKEN, "REVIEW")
        b, _ = fc.completion_key(TOKEN, "  review ")
        assert a == b

    def test_the_key_is_coarse_form_data_does_not_split_it(self):
        """The central decision. Re-answering the form is not a second request.

        Splitting on payload would treat a retry that arrived with a re-serialised body as
        a new request, and the cost of that mistake is a second invoice. Merging costs a
        lost second enquiry, which a human notices.
        """
        a, _ = fc.completion_key(TOKEN, "REVIEW", {"subject": "one"})
        b, _ = fc.completion_key(TOKEN, "REVIEW", {"subject": "two"})
        assert a == b

    def test_no_token_does_not_merge_unrelated_completions(self):
        """Hashing '' would give every tokenless completion the same key."""
        a, degraded_a = fc.completion_key("", "REVIEW", {"phone": "1", "x": 1})
        b, degraded_b = fc.completion_key("", "REVIEW", {"phone": "2", "x": 2})
        assert degraded_a and degraded_b
        assert a != b

    def test_no_token_still_collapses_a_byte_identical_retry(self):
        a, _ = fc.completion_key("", "REVIEW", {"a": 1, "b": 2})
        b, _ = fc.completion_key("", "REVIEW", {"b": 2, "a": 1})
        assert a == b, "dict order must not affect the fallback key"

    def test_degraded_is_only_true_without_a_token(self):
        _, degraded = fc.completion_key(TOKEN, "REVIEW")
        assert degraded is False

    def test_whitespace_token_counts_as_absent(self):
        _, degraded = fc.completion_key("   ", "REVIEW")
        assert degraded is True

    def test_hyphen_split_cannot_collide(self):
        """Flow tokens are full of hyphens; joining on one would let parts merge."""
        assert fc.completion_key("a-b", "c")[0] != fc.completion_key("a", "b-c")[0]

    def test_key_does_not_leak_the_token(self):
        """A reference number reaches the customer and appears in logs."""
        key, _ = fc.completion_key(TOKEN, "REVIEW")
        assert "918100640044" not in key
        assert TOKEN not in key


class TestReference:
    def test_is_derived_so_a_retry_shows_the_same_number(self):
        key, _ = fc.completion_key(TOKEN, "REVIEW")
        assert fc.reference_for(key, "WD-SR") == fc.reference_for(key, "WD-SR")

    def test_keeps_the_human_readable_prefix(self):
        key, _ = fc.completion_key(TOKEN, "REVIEW")
        reference = fc.reference_for(key, "WD-SR")
        assert reference.startswith("WD-SR-")
        assert len(reference.split("-")[-1]) == 8
        assert reference.split("-")[-1].isupper() or reference.split("-")[-1].isdigit()

    def test_different_prefixes_do_not_change_the_identity(self):
        key, _ = fc.completion_key(TOKEN, "REVIEW")
        assert fc.reference_for(key, "WD-SR").split("-")[-1] == \
            fc.reference_for(key, "WD-APT").split("-")[-1]

    def test_empty_prefix_falls_back_rather_than_producing_a_bare_hash(self):
        key, _ = fc.completion_key(TOKEN, "REVIEW")
        assert fc.reference_for(key, "").startswith("WD-")


class TestClaim:
    def _claim(self, **overrides):
        kwargs = dict(flow_token=TOKEN, screen="REVIEW", flow_code="01.WD_SR",
                      flow_type="form_submit", phone="918100640044",
                      contact_id="c-1", sender_name="QA",
                      form_data={"order_id": "o-1", "subject": "Broken screen"},
                      reference_prefix="WD-SR", request_id="r-1")
        kwargs.update(overrides)
        return fc.claim_completion(**kwargs)

    def test_first_delivery_is_created(self, db):
        result = self._claim()
        assert result.status == "created"
        assert result.created
        assert result.should_fire_side_effects
        assert db.count(fc.FLOW_SUBMISSIONS_TABLE) == 1

    def test_retry_is_a_duplicate_and_writes_nothing(self, db):
        first = self._claim()
        second = self._claim()
        assert second.status == "duplicate"
        assert second.submission_id == first.submission_id
        assert db.count(fc.FLOW_SUBMISSIONS_TABLE) == 1

    def test_a_duplicate_must_not_fire_side_effects(self, db):
        self._claim()
        assert self._claim().should_fire_side_effects is False

    def test_an_error_must_not_fire_side_effects(self, db):
        """An unknown claim state is not permission to send a second payment link."""
        db.arm_failure(fc.FLOW_SUBMISSIONS_TABLE, "put_item",
                       FakeClientError("ProvisionedThroughputExceededException"))
        result = self._claim()
        assert result.status == "error"
        assert result.should_fire_side_effects is False
        assert result.error

    def test_a_new_flow_message_claims_separately(self, db):
        self._claim()
        second = self._claim(flow_token=OTHER_TOKEN)
        assert second.status == "created"
        assert db.count(fc.FLOW_SUBMISSIONS_TABLE) == 2

    def test_submission_id_override_is_honoured(self, db):
        """postpay has a stronger key - a Razorpay reference shared across transports."""
        result = self._claim(submission_id="postpay-WD-PAY-123")
        assert result.submission_id == "postpay-WD-PAY-123"

    def test_an_override_dedupes_across_transports(self, db):
        """Two different tokens, one payment: the override is what collapses them."""
        self._claim(submission_id="postpay-REF9")
        second = self._claim(flow_token=OTHER_TOKEN, submission_id="postpay-REF9")
        assert second.status == "duplicate"
        assert db.count(fc.FLOW_SUBMISSIONS_TABLE) == 1

    def test_the_row_keeps_the_legacy_shape(self, db):
        """Existing readers query these fields; the shape must not change."""
        self._claim(requires_payment=True, payment_amount=250000,
                    payment_ref_id="WD-PAY-AAA")
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        for field in ("submissionId", "submissionNumber", "flowCode", "flowType",
                      "phone", "contactId", "formData", "flowToken", "status",
                      "paymentRequired", "paymentAmount", "paymentStatus",
                      "paymentRefId", "createdAt", "updatedAt", "ttl"):
            assert field in row, f"{field} is read by existing consumers"
        assert row["paymentStatus"] == "pending"
        assert row["paymentAmount"] == 250000

    def test_order_centric_fields_are_promoted_for_the_gsis(self, db):
        self._claim(form_data={"order_id": "ORD-7", "subject": "S",
                               "description": "D", "request_type": "RT"})
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        assert row["orderId"] == "ORD-7"
        assert row["requestType"] == "RT"

    def test_unpaid_completion_records_no_payment_state(self, db):
        """An unpaid flow must not inherit a caller's stray amount or reference.

        The stored shape matches the legacy `common.save_flow_submission` filter exactly,
        which is `v is not None and v != ''`. Note that this keeps `paymentAmount: 0` and
        `paymentRequired: False` - `0 != ''` and `False != ''` are both true in Python. That
        is deliberate fidelity, not an oversight: the other legacy writer additionally
        stripped `False`, and matching the nine-flow writer is what keeps existing readers
        of this table working.
        """
        self._claim(requires_payment=False, payment_amount=9999,
                    payment_ref_id="WD-PAY-X")
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        assert row["paymentStatus"] == "none"
        assert "paymentRefId" not in row, "an unpaid flow must not carry a payment ref"
        assert row["paymentAmount"] == 0, "the caller's stray 9999 must not be recorded"
        assert row["paymentRequired"] is False

    def test_the_key_is_stored_for_reconciliation(self, db):
        result = self._claim()
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        assert row["completionKey"] == result.key

    def test_degraded_claim_is_recorded_on_the_row(self, db):
        result = self._claim(flow_token="")
        assert result.degraded
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        assert row["completionKeyDegraded"] is True

    def test_extra_fields_cannot_overwrite_the_key(self, db):
        """A caller must not be able to redirect the claim through `extra`."""
        result = self._claim(extra={"submissionId": "hijacked",
                                   "completionKey": "hijacked",
                                   "referenceId": "legit"})
        assert result.submission_id != "hijacked"
        row = db.all_rows(fc.FLOW_SUBMISSIONS_TABLE)[0]
        assert row["submissionId"] != "hijacked"
        assert row["referenceId"] == "legit"

    def test_condition_failure_is_recognised_from_a_wrapped_error(self, db):
        """A false negative here means a duplicate invoice, so both forms are matched."""

        class Wrapped(Exception):
            pass

        assert fc._is_condition_failure(
            Wrapped("... ConditionalCheckFailedException ..."))
        assert not fc._is_condition_failure(Wrapped("ThrottlingException"))


class TestCrmMirror:
    def test_skipped_for_a_duplicate(self, monkeypatch):
        called = []
        result = fc.CompletionResult(status="duplicate", submission_id="s",
                                     reference="r", key="k")
        assert fc.capture_crm_lead(result, contact_id="c-1")["outcome"] == "skipped"
        assert not called

    def test_skipped_without_a_contact(self):
        result = fc.CompletionResult(status="created", submission_id="s",
                                     reference="r", key="k")
        assert fc.capture_crm_lead(result, contact_id="")["outcome"] == "skipped"

    def test_a_crm_failure_never_breaks_the_completion(self, monkeypatch):
        """No default pipeline provisioned must not fail a customer's submission."""
        import lambda_utils.crm.service as crm_service

        def boom(**_):
            raise ValueError("no default pipeline; run CRM provisioning first")

        monkeypatch.setattr(crm_service, "capture_lead", boom)
        result = fc.CompletionResult(status="created", submission_id="s",
                                     reference="r", key="k")
        outcome = fc.capture_crm_lead(result, contact_id="c-1", flow_token=TOKEN)
        assert outcome["outcome"] == "error"
        assert "pipeline" in outcome["reason"]

    def test_uses_the_flow_token_as_the_lead_source_ref(self, monkeypatch):
        """So the lead's identity matches what crm.keys documents as single-use."""
        seen = {}
        import lambda_utils.crm.service as crm_service

        def record(**kwargs):
            seen.update(kwargs)
            return {"outcome": "created", "lead": {"leadId": "lead_x"}}

        monkeypatch.setattr(crm_service, "capture_lead", record)
        result = fc.CompletionResult(status="created", submission_id="s",
                                     reference="r", key="k")
        fc.capture_crm_lead(result, contact_id="c-1", flow_token=TOKEN,
                            subject="Broken screen", amount_paise=1000)
        assert seen["source_ref"] == TOKEN
        assert seen["source"] == "FLOW_SUBMISSION"
        assert seen["contact_id"] == "c-1"
        assert seen["amount_paise"] == 1000


class TestEveryFlowModuleIsWired:
    """No flow module may write a submission or message a customer unguarded.

    Source-level, for the same reason `test_contact_key_wiring` is: the invariant is "no
    module anywhere", which a behavioural test over one handler cannot express - it passes
    while the tenth flow, added next month, reintroduces the unguarded pattern.

    The nine flow modules were all identical before this: mint a random id, write the
    domain row, call `save_flow_submission` discarding its return, then send a confirmation.
    Six of the nine sent a customer message with nothing in front of it.
    """

    FLOWS_DIR = (ROOT / "amplify" / "functions" / "messaging" /
                 "whatsapp-business-api" / "flows")

    #: Modules that complete a flow and write a submission.
    COMPLETION_MODULES = (
        "submit_request.py", "subscribe.py", "rx_slot.py", "appointment.py",
        "drop_docs.py", "leave_review.py", "enterprise_assist.py",
        "order_notes.py", "generic.py", "subscribe_profile.py",
    )

    #: The calls that reach a customer or move money.
    #:
    #: `OUTBOUND_WHATSAPP_FUNCTION` is here because `subscribe.py` bypasses the helpers and
    #: invokes the sender directly. Listing only the three helper names would have declared
    #: subscribe compliant while it still messaged the customer on every retry.
    SIDE_EFFECT_CALLS = (
        "send_simple_confirmation(",
        "send_confirmation(",
        "send_payment(",
        "OUTBOUND_WHATSAPP_FUNCTION",
    )

    def source(self, name: str) -> str:
        return (self.FLOWS_DIR / name).read_text(encoding="utf-8")

    def test_the_inventory_is_complete(self):
        """A tenth flow module that writes a submission must be added here."""
        found = set()
        for path in self.FLOWS_DIR.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "record_completion(" in text or "save_flow_submission(" in text:
                found.add(path.name)
        # common.py defines both; postpay has its own stronger key.
        found -= {"common.py", "postpay.py"}
        assert found == set(self.COMPLETION_MODULES), (
            f"flow modules writing submissions changed: {sorted(found)} vs "
            f"{sorted(self.COMPLETION_MODULES)}")

    @pytest.mark.parametrize("module", COMPLETION_MODULES)
    def test_uses_the_single_writer(self, module):
        text = self.source(module)
        assert "record_completion(" in text, (
            f"{module} must claim its completion through record_completion")

    @pytest.mark.parametrize("module", COMPLETION_MODULES)
    def test_does_not_mint_a_random_reference(self, module):
        """A random reference is what made a retry a second row and a second request number."""
        import re

        text = self.source(module)
        offenders = re.findall(r"f'WD-[A-Z]+-\{uuid\.uuid4\(\)", text)
        assert not offenders, (
            f"{module} still mints a random reference {offenders}; derive it from the "
            "completion key so a retry recomputes the same value")

    @pytest.mark.parametrize("module", COMPLETION_MODULES)
    def test_side_effects_are_gated_on_the_claim(self, module):
        """Every customer-facing call must sit under `should_fire_side_effects`."""
        text = self.source(module)
        calls = [call for call in self.SIDE_EFFECT_CALLS if call in text]
        if not calls:
            return  # generic.py sends nothing
        assert "should_fire_side_effects" in text, (
            f"{module} calls {calls} but never checks the claim; a retry would send a "
            "second message or open a second invoice")

    def test_postpay_keeps_its_own_stronger_key(self):
        """Not a gap: a Razorpay reference identifies the payment better than a token.

        postpay is deliberately excluded from the rewrite. It already writes with
        `attribute_not_exists(submissionId)` against a reference-derived id, and that id is
        shared with the inbound transport - which a token-derived key could not be, because
        the two transports carry different tokens for one payment.
        """
        text = self.source("postpay.py")
        assert "attribute_not_exists(submissionId)" in text
        assert "_reference_from_token(" in text

    def test_common_still_offers_the_legacy_wrapper_but_it_hides_the_status(self):
        """Documented on purpose, so nobody reaches for it for a paying flow.

        `save_flow_submission` returns a bare dict, so a caller cannot tell a duplicate from
        a fresh claim. It is kept only so an unconverted caller still gets the conditional
        put. Any caller with a side effect must use `record_completion`.
        """
        text = self.source("common.py")
        assert "def save_flow_submission(" in text
        assert "def record_completion(" in text
        assert "should_fire_side_effects" in text

    def test_record_completion_is_total(self):
        """Callers assign the result inside a `try:` and branch on it afterwards.

        If `record_completion` could raise, `result` would be unbound and the guard would
        become a NameError - an error screen for the customer instead of a confirmation.
        """
        text = self.source("common.py")
        assert "def _record_completion(" in text, (
            "record_completion must wrap a body that cannot escape")
        head = text.split("def _record_completion(")[0]
        assert "flow_completion_unexpected_error" in head
        assert "status='error'" in head
