"""Phase R — a review is attributed to its order, and stored exactly once.

WHAT IS BEING PROVED, AND WHY EACH HALF MATTERS
-----------------------------------------------
The website's "Leave a review" button opens `wa.me/<WABA1>?text=review <REF>`, so the
CUSTOMER messages us with the order they want to review. Two Lambdas have to cooperate
across that hop:

  `wecare-inbound-whatsapp`      recognises `review <REF>`, parks the reference, sends the Flow
  `wecare-whatsapp-business-api` receives the Flow submission, reads the reference back, stores

The reference travels in a FlowDraftTable row (`{phone}#WD_REV_REF`) rather than in the flow
token, and that is load-bearing: the token shape is `{flow_key}-{uuid}-waba-{1|2}-ph-{phone}`,
`router._extract_flow_key` breaks the prefix at the first segment longer than 10 characters,
and `common.get_phone_from_token` splits on `-ph-`, so a reference containing `-` — which
every `WD-ORD-…` number does — would silently reroute the flow or strip the phone.

REPLAY SAFETY IS THE PROPERTY THIS FILE EXISTS FOR
--------------------------------------------------
Meta retries a `data_exchange` it did not get a clean response to. `review_id` is derived
from `flow_completion.completion_key`, so a retry recomputes the SAME id and overwrites an
identical row instead of creating a second review — and `claim_completion`'s conditional put
refuses the duplicate, so only the first attempt may message the customer.

The specific trap tested here is the DRAFT. The reference is read before the write and
cleared only inside `if result.should_fire_side_effects:`. Clear it unconditionally and a
retry reads an empty draft and rewrites the review row with `orderId` gone — losing the
attribution precisely on the path the derived id exists to make safe. That is
`test_a_replay_does_not_drop_the_attribution`.

THE FLAG IS OFF, AND IT GATES BOTH LAMBDAS
------------------------------------------
`REVIEW_ATTRIBUTION_ENABLED` defaults false and is read by BOTH halves. The inbound
ingress invokes `wecare-inbound-whatsapp` UNQUALIFIED, so `$LATEST` is production the
moment `update-function-code` returns and there is no alias gap in which to verify a
behaviour change — it has to ship inert. `test_the_flag_defaults_off` pins that end.

`wecare-whatsapp-business-api` needs the same gate for a different reason, and
`TestTheFlowSideIsGated` is what pins it: the published Flow version on Meta declares the
screen's data model, publishing is owner-only, and the Lambda deploy does not happen at the
same instant. So `handle_init` must not start returning an `order_ref` the published
version has never heard of. With the flag off its response is key-for-key what it was
before Phase R, which is what makes the deploy a provable no-op.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
WBA = ROOT / "amplify" / "functions" / "messaging" / "whatsapp-business-api"
INBOUND = ROOT / "amplify" / "functions" / "messaging" / "inbound-whatsapp-handler"

for _path in (str(SHARED), str(WBA), str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils import flow_completion as fc  # noqa: E402

# The QA recipient the owner nominated (`.kiro/steering/02-qa-recipient.md`), never a
# business number. Used here only as a fixture value; this file sends nothing.
QA_PHONE = "918100640044"
TOKEN = f"leave-3f2a91c4-0000-4aaa-bbbb-000000000001-waba-1-ph-{QA_PHONE}"
REFERENCE = "WD-ORD-A7K2M9PQ"
DRAFT_KEY = f"{QA_PHONE}#WD_REV_REF"

FORM_DATA = {"rating": "5", "category": "service", "review_text": "Sorted it in a day."}


# ───────────────────────────── the Flow submission half ─────────────────────────────

@pytest.fixture()
def review_env(monkeypatch):
    """`flows.leave_review` wired to fake tables, with no network and no sends.

    `flows.common` builds its DynamoDB resource at module scope, so the fakes are patched
    onto the imported module rather than injected - the same approach
    `tests/test_flow_completion.py` takes with `fc._table`.

    THE FLAG IS ON HERE, because attribution is what this fixture exists to exercise. The
    off state is not an afterthought though - it is the shipped default and it has its own
    class, `TestTheFlowSideIsGated`, which deletes the variable instead of setting it.
    """
    monkeypatch.setenv("REVIEW_ATTRIBUTION_ENABLED", "true")
    from flows import common as flows_common
    leave_review = importlib.import_module("flows.leave_review")

    fake = FakeDynamo(
        {
            leave_review.REVIEWS_TABLE: "reviewId",
            flows_common.DRAFTS_TABLE: "draftKey",
            fc.FLOW_SUBMISSIONS_TABLE: "submissionId",
        },
        {
            leave_review.REVIEWS_TABLE: {},
            flows_common.DRAFTS_TABLE: {},
            fc.FLOW_SUBMISSIONS_TABLE: {},
        },
    )
    monkeypatch.setattr(flows_common, "dynamodb", fake)
    monkeypatch.setattr(leave_review, "dynamodb", fake)
    monkeypatch.setattr(fc, "_table", lambda: fake.Table(fc.FLOW_SUBMISSIONS_TABLE))
    # Attribution is what is under test, not contact lookup.
    monkeypatch.setattr(flows_common, "find_contact_by_phone", lambda phone: "wa918100640044")
    monkeypatch.setattr(flows_common, "get_contact_name", lambda cid: "QA Tester")
    monkeypatch.setattr(leave_review, "find_contact_by_phone", lambda phone: "wa918100640044")
    monkeypatch.setattr(leave_review, "get_contact_name", lambda cid: "QA Tester")

    sends: list = []
    monkeypatch.setattr(
        flows_common, "send_simple_confirmation",
        lambda *a, **k: sends.append((a, k)) or True)

    return leave_review, fake, sends


def _park(fake, flows_drafts_table, reference=REFERENCE, expires_in=1800):
    """Write the draft row the inbound handler writes, in exactly its shape.

    `expires_in` is negative in the abandonment tests. `expiresAt` lives INSIDE `formData`
    because `common.restore_draft` returns only `{screen, formData}` and drops every other
    attribute, so the DynamoDB `ttl` attribute is not visible to the reader at all.
    """
    expires_at = int(time.time()) + expires_in
    fake.Table(flows_drafts_table).put_item(Item={
        "draftKey": DRAFT_KEY,
        "phone": QA_PHONE,
        "flowCode": "WD_REV_REF",
        "screen": "REVIEW_FORM",
        # A JSON STRING, because `common.restore_draft` json.loads this field.
        "formData": json.dumps({"reference": reference, "expiresAt": expires_at}),
        "ttl": expires_at,
    })


class TestTheReviewIsAttributed:
    def test_a_parked_reference_lands_on_the_review_row(self, review_env):
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")

        rows = fake.all_rows(leave_review.REVIEWS_TABLE)
        assert len(rows) == 1
        assert rows[0]["orderId"] == REFERENCE

    def test_the_row_carries_the_fields_the_workspace_page_reads(self, review_env):
        """`source` is the bug fix, not a nicety.

        `service_api._list_reviews` reads `i.get('source', i.get('category', 'web'))`, so
        with no `source` a WhatsApp review borrowed its CATEGORY - the Source column showed
        'service' and the workspace's `whatsapp` source filter matched nothing at all.
        """
        leave_review, fake, _ = review_env
        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")

        row = fake.all_rows(leave_review.REVIEWS_TABLE)[0]
        assert row["source"] == "whatsapp"
        assert row["rating"] == 5
        assert isinstance(row["rating"], int)
        assert row["reviewText"] == FORM_DATA["review_text"]

    def test_the_stored_status_stays_in_the_vocabulary_service_api_translates(self, review_env):
        """`submitted`, NOT `pending`, and the distinction is deliberate.

        `service_api` is the single translator for this field: `_list_reviews` maps
        `submitted` -> `pending` for the frontend and `_update_review` maps `pending` ->
        `submitted` back. Writing `pending` here would put two spellings of one state into a
        table two producers share - the vocabulary fork recorded for payment status. The
        staff page already renders this row as `pending`, so the moderation gate holds.
        """
        leave_review, fake, _ = review_env
        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")
        assert fake.all_rows(leave_review.REVIEWS_TABLE)[0]["status"] == "submitted"

    def test_an_unattributed_review_is_stored_without_an_order(self, review_env):
        """Someone who just typed `review` is a supported path, not an error."""
        leave_review, fake, _ = review_env
        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")

        row = fake.all_rows(leave_review.REVIEWS_TABLE)[0]
        assert "orderId" not in row
        assert row["source"] == "whatsapp"

    def test_the_first_screen_shows_the_order_being_reviewed(self, review_env):
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        result = leave_review.handle_init({}, TOKEN, "req-1")
        assert result["screen"] == "REVIEW_FORM"
        assert REFERENCE in result["data"]["order_ref"]

    def test_the_first_screen_never_renders_an_empty_caption(self, review_env):
        """The caption is unconditional in the Flow JSON, so the fallback is what saves it."""
        leave_review, _fake, _ = review_env
        result = leave_review.handle_init({}, TOKEN, "req-1")
        assert result["data"]["order_ref"] == leave_review.UNATTRIBUTED_LABEL
        assert result["data"]["order_ref"].strip()


class TestTheFlowSideIsGated:
    """The OFF state of `wecare-whatsapp-business-api`, which is what actually ships.

    WHY THIS CLASS EXISTS. The published Flow version on Meta declares the screen's data
    model, and a data_exchange response is answered against that model - `${data.order_ref}`
    with no `order_ref` declaration is rejected when the Flow is created. Creating and
    publishing a Flow version is owner-only work, and the Lambda deploy happens at the land
    step, so the two sides do NOT change at the same instant.

    If `handle_init` returned `order_ref` unconditionally, the deploy alone would start
    answering every review Flow init with a key the currently published version has never
    declared, on a path `review`, `feedback` and `rate` already reach today. Whether Meta
    tolerates an extra key is not measurable from this repo - reaching its validator means
    creating the Flow. So the response shape is held still until the owner says otherwise,
    and these tests are what hold it.
    """

    @pytest.fixture()
    def flag_off(self, review_env, monkeypatch):
        monkeypatch.delenv("REVIEW_ATTRIBUTION_ENABLED", raising=False)
        return review_env

    def test_the_flag_defaults_off_here_too(self, flag_off):
        leave_review, _fake, _ = flag_off
        assert leave_review._attribution_enabled() is False

    def test_the_init_response_does_not_mention_order_ref(self, flag_off):
        """ABSENT, not empty. An empty string is still a key in the response."""
        leave_review, fake, _ = flag_off
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        result = leave_review.handle_init({}, TOKEN, "req-1")
        assert "order_ref" not in result["data"]

    def test_the_init_response_is_otherwise_byte_for_byte_what_it_was(self, flag_off):
        """The deploy must be a provable no-op against the published Flow version."""
        leave_review, _fake, _ = flag_off
        result = leave_review.handle_init({}, TOKEN, "req-1")
        assert result["screen"] == "REVIEW_FORM"
        assert set(result["data"]) == {"ratings", "categories"}

    def test_a_parked_reference_is_not_read_at_all(self, flag_off):
        """Not merely unused - unread. The draft row must survive untouched."""
        leave_review, fake, _ = flag_off
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")

        assert "orderId" not in fake.all_rows(leave_review.REVIEWS_TABLE)[0]
        assert fake.Table(flows_common.DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY}).get("Item") is not None

    def test_a_row_already_attributed_is_not_blanked_by_turning_the_flag_off(self, flag_off):
        """Turning the flag off is a ROLLBACK, and a rollback must not destroy data.

        `_stored_order_id` is deliberately NOT gated: it recovers a reference this function
        already wrote. Gated, a Meta retry arriving after the flag went off would rewrite
        the review with `orderId` gone, because the domain write is a `put_item` and
        replaces the whole item rather than merging.
        """
        leave_review, fake, _ = flag_off
        key, _unused = fc.completion_key(TOKEN, "REVIEW_FORM", FORM_DATA)
        review_id = fc.reference_for(key, "WD-REV")
        fake.Table(leave_review.REVIEWS_TABLE).put_item(
            Item={"reviewId": review_id, "orderId": REFERENCE})

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-retry")

        assert fake.all_rows(leave_review.REVIEWS_TABLE)[0]["orderId"] == REFERENCE

    @pytest.mark.parametrize("raw,expected", [
        ("5", 5), ("1", 1), ("3", 3),
        ("0", 0), ("6", 0), ("-2", 0), ("99", 0),
        ("", 0), ("five", 0), (None, 0),
    ])
    def test_the_rating_is_clamped_to_the_one_to_five_the_contract_declares(
            self, review_env, raw, expected):
        leave_review, fake, _ = review_env
        data = dict(FORM_DATA)
        data["rating"] = raw
        leave_review.handle_review_form(data, TOKEN, "req-1")
        rows = fake.all_rows(leave_review.REVIEWS_TABLE)
        # rating 0 is dropped by the falsy filter on the way in, which is today's behaviour.
        assert rows[0].get("rating", 0) == expected


class TestReplaySafety:
    def test_a_replay_stores_the_review_exactly_once(self, review_env):
        leave_review, fake, sends = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        first = leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")
        second = leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-2-retry")

        # One review, one claimed completion, one confirmation.
        assert len(fake.all_rows(leave_review.REVIEWS_TABLE)) == 1
        assert len(fake.all_rows(fc.FLOW_SUBMISSIONS_TABLE)) == 1
        assert len(sends) == 1, "a Meta retry must not send a second confirmation"
        # And the customer sees the same reference both times.
        assert first["data"]["review_id"] == second["data"]["review_id"]

    def test_a_replay_does_not_drop_the_attribution(self, review_env):
        """THE TRAP. The draft is cleared only on a fresh claim.

        Cleared unconditionally, the retry would read an empty draft and rewrite the review
        row with `orderId` gone - losing attribution on exactly the path the derived
        `review_id` exists to make safe.
        """
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")
        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-2-retry")

        rows = fake.all_rows(leave_review.REVIEWS_TABLE)
        assert len(rows) == 1
        assert rows[0]["orderId"] == REFERENCE, "the replay rewrote the row without its order"

    def test_the_reference_is_recovered_from_the_row_when_the_draft_is_gone(self, review_env):
        """The mechanism behind the test above, asserted directly.

        With no draft at all but a row already carrying `orderId`, a repeat completion must
        still store the attribution. This is the only thing standing between a Meta retry
        and a blanked field, because the domain write is a `put_item` and replaces the whole
        item rather than merging.
        """
        leave_review, fake, _ = review_env
        from flows import common as flows_common

        # Pre-existing row, exactly as the winning call would have left it.
        key, _ = fc.completion_key(TOKEN, "REVIEW_FORM", FORM_DATA)
        review_id = fc.reference_for(key, "WD-REV")
        fake.Table(leave_review.REVIEWS_TABLE).put_item(
            Item={"reviewId": review_id, "orderId": REFERENCE})
        assert fake.Table(flows_common.DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY}).get("Item") is None

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-retry")

        rows = fake.all_rows(leave_review.REVIEWS_TABLE)
        assert len(rows) == 1
        assert rows[0]["orderId"] == REFERENCE

    def test_the_draft_is_consumed_so_the_next_review_is_not_misattributed(self, review_env):
        """A stale reference would silently attribute an unrelated later review."""
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")
        assert fake.Table(flows_common.DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY}).get("Item") is None

    def test_an_abandoned_door_does_not_attribute_the_next_review(self, review_env):
        """THE OTHER HALF OF THE SAME INVARIANT, and the submitted case does not cover it.

        Submission is not the only way out of a Flow. A customer can tap the attributed
        review button for order A and simply dismiss the form - nothing clears the parked
        row, because `handle_init` reads it without consuming it and `handle_review_form`
        never ran. Their NEXT message is a bare `review` about something else entirely, and
        with a long-lived row that unrelated review would be stored against order A.

        The expiry is what closes it, and it is enforced on READ rather than left to
        DynamoDB: TTL deletion is best-effort and documented to lag up to 48 hours, so the
        `ttl` attribute bounds storage while `expiresAt` bounds attribution.
        """
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        # Parked, the Flow opened, then abandoned - and long enough ago to have lapsed.
        _park(fake, flows_common.DRAFTS_TABLE, expires_in=-1)

        assert leave_review._pending_reference(QA_PHONE) == ""

        later = TOKEN.replace("3f2a91c4", "77777777")
        leave_review.handle_review_form(dict(FORM_DATA), later, "req-later")

        rows = fake.all_rows(leave_review.REVIEWS_TABLE)
        assert len(rows) == 1
        assert "orderId" not in rows[0], "a lapsed door attributed an unrelated review"

    def test_a_live_door_still_attributes_within_its_window(self, review_env):
        """The bound must not be so tight that the normal path stops working."""
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE, expires_in=60)
        assert leave_review._pending_reference(QA_PHONE) == REFERENCE

    def test_a_row_with_no_expiry_is_treated_as_lapsed(self, review_env):
        """FAIL-CLOSED on a shape this module did not write.

        The cost of refusing is one unattributed review. The cost of accepting is a
        silently wrong order id on a review a staff member will act on.
        """
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        fake.Table(flows_common.DRAFTS_TABLE).put_item(Item={
            "draftKey": DRAFT_KEY, "phone": QA_PHONE, "flowCode": "WD_REV_REF",
            "screen": "REVIEW_FORM", "formData": json.dumps({"reference": REFERENCE}),
        })
        assert leave_review._pending_reference(QA_PHONE) == ""

    def test_a_failed_row_write_keeps_the_draft_so_the_retry_can_attribute(self, review_env):
        """The clear is guarded on the WRITE, not only on winning the claim.

        If the ReviewTable `put_item` raises, there is no row for `_stored_order_id` to
        recover from. Clearing the draft as well would leave a Meta retry with neither
        source, and the review would be stored permanently unattributed - the one outcome
        the two-source read exists to prevent.
        """
        leave_review, fake, _ = review_env
        from flows import common as flows_common
        _park(fake, flows_common.DRAFTS_TABLE)
        fake.arm_failure(leave_review.REVIEWS_TABLE, "put_item", RuntimeError("boom"))

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")

        assert fake.all_rows(leave_review.REVIEWS_TABLE) == []
        assert fake.Table(flows_common.DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY}).get("Item") is not None, \
            "the only surviving copy of the reference was destroyed"

    def test_a_genuinely_new_review_is_a_new_row(self, review_env):
        """The escape hatch: a second review arrives with a new flow token."""
        leave_review, fake, sends = review_env
        other = TOKEN.replace("3f2a91c4", "99999999")

        leave_review.handle_review_form(dict(FORM_DATA), TOKEN, "req-1")
        leave_review.handle_review_form(dict(FORM_DATA), other, "req-2")

        assert len(fake.all_rows(leave_review.REVIEWS_TABLE)) == 2
        assert len(sends) == 2


# ───────────────────────────── the inbound keyword half ─────────────────────────────

@pytest.fixture()
def inbound(monkeypatch):
    """The inbound handler's review helpers, with a fake FlowDraftTable.

    Imported by path rather than exercising `_process_message` end to end: that function
    needs a full SNS envelope, contact storage and media plumbing, none of which is what
    regressed. The reference parser, the flag and the parked row are the three things this
    phase added, and they are exercised directly.
    """
    if str(INBOUND) not in sys.path:
        sys.path.insert(0, str(INBOUND))
    sys.modules.pop("handler", None)
    handler = importlib.import_module("handler")

    fake = FakeDynamo({handler.FLOW_DRAFTS_TABLE: "draftKey"},
                      {handler.FLOW_DRAFTS_TABLE: {}})
    monkeypatch.setattr(handler, "dynamodb", fake)
    yield handler, fake
    sys.modules.pop("handler", None)


class TestTheInboundReferenceParser:
    def test_the_flag_defaults_off(self, inbound, monkeypatch):
        """OFF is today's behaviour, and `$LATEST` is production for this function."""
        handler, _ = inbound
        monkeypatch.delenv("REVIEW_ATTRIBUTION_ENABLED", raising=False)
        assert handler._review_attribution_enabled() is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " true "])
    def test_only_an_explicit_truthy_value_turns_it_on(self, inbound, monkeypatch, value):
        handler, _ = inbound
        monkeypatch.setenv("REVIEW_ATTRIBUTION_ENABLED", value)
        assert handler._review_attribution_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "maybe"])
    def test_anything_else_leaves_it_off(self, inbound, monkeypatch, value):
        handler, _ = inbound
        monkeypatch.setenv("REVIEW_ATTRIBUTION_ENABLED", value)
        assert handler._review_attribution_enabled() is False

    @pytest.mark.parametrize("message,expected", [
        # `content_lower` is already lowercased by the caller; upper-casing is lossless
        # because the order-number alphabet is upper-case and digits.
        ("review wd-ord-a7k2m9pq", "WD-ORD-A7K2M9PQ"),   # current minted form
        ("review a7k2m9pq3wxy", "A7K2M9PQ3WXY"),         # legacy bare 12-char form
        ("review wd-pay-abc123", "WD-PAY-ABC123"),       # a payment reference
        ("review   wd-ord-a7k2m9pq", "WD-ORD-A7K2M9PQ"),  # extra space
    ])
    def test_a_reference_is_recognised(self, inbound, message, expected):
        handler, _ = inbound
        assert handler._extract_review_reference(message) == expected

    @pytest.mark.parametrize("message", [
        "review",                                 # the bare keyword keeps the exact-match path
        "can i leave a review for my order",      # prose must never dispatch a Flow
        "review my order please",                 # two trailing tokens
        "leave review",                           # a different existing keyword
        "reviews wd-ord-a7k2m9pq",                # not the literal root `review`
        "rate wd-ord-a7k2m9pq",                   # a generic keyword, deliberately excluded
        "feedback wd-ord-a7k2m9pq",
        "testimonial wd-ord-a7k2m9pq",
        "review ab",                              # under the 4-character floor
        "review -wd-ord-1234",                    # must start alphanumeric
        "review wd ord a7k2m9pq",                 # spaces are not part of a reference
        "review " + "a" * 64,                     # over the 40-character ceiling
        "",
    ])
    def test_everything_else_does_not_match(self, inbound, message):
        handler, _ = inbound
        assert handler._extract_review_reference(message) == ""

    def test_the_two_ends_of_the_door_share_one_bound(self, inbound):
        """`src/lib/reviewLink.ts` must enforce the identical reference shape.

        A reference the website would put in the link but this end refuses is a button that
        silently does nothing, so the expression is asserted to be the same in both files.
        """
        handler, _ = inbound
        ts = (ROOT / "src" / "lib" / "reviewLink.ts").read_text(encoding="utf-8")
        assert "^[A-Z0-9][A-Z0-9-]{3,39}$" in ts
        assert "[A-Za-z0-9][A-Za-z0-9-]{3,39}" in handler._REVIEW_REF_PATTERN


class TestTheParkedDraftRow:
    def test_it_is_written_where_the_flow_reads_it_back(self, inbound):
        handler, fake = inbound
        assert handler._park_review_reference(QA_PHONE, REFERENCE, "req-1") is True

        row = fake.Table(handler.FLOW_DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY})["Item"]
        assert row["phone"] == QA_PHONE
        assert row["flowCode"] == "WD_REV_REF"
        # A JSON STRING, because `flows.common.restore_draft` json.loads this field. A map
        # here would make the reader return {} and the attribution would vanish silently.
        parked = json.loads(row["formData"])
        assert parked["reference"] == REFERENCE
        # INSIDE formData, because `restore_draft` returns only `{screen, formData}` and
        # drops every other attribute - the reader cannot see `ttl` at all.
        assert parked["expiresAt"] == int(row["ttl"])

    def test_the_parked_reference_expires_in_minutes_not_days(self, inbound):
        """`save_draft`'s 7 days is wrong for this row, and the margin matters.

        A parked reference is only meaningful for one sitting. Left for days, an abandoned
        review door attributes the customer's next unrelated `review` to the order they
        walked away from. One hour is the ceiling asserted here so a future edit cannot
        quietly restore the 7-day TTL this row was first written with.
        """
        handler, fake = inbound
        assert 0 < handler.REVIEW_REF_TTL_SECONDS <= 3600

        before = int(time.time())
        handler._park_review_reference(QA_PHONE, REFERENCE, "req-1")
        row = fake.Table(handler.FLOW_DRAFTS_TABLE).get_item(
            Key={"draftKey": DRAFT_KEY})["Item"]
        assert int(row["ttl"]) <= before + handler.REVIEW_REF_TTL_SECONDS + 5

    def test_the_draft_suffix_matches_the_flow_module(self, inbound):
        handler, _ = inbound
        leave_review = importlib.import_module("flows.leave_review")
        assert handler.REVIEW_REF_DRAFT_CODE == leave_review.REF_DRAFT_CODE

    def test_the_two_halves_read_the_same_flag(self, inbound):
        """One flag, both Lambdas. Two names would be two things to remember to flip."""
        handler, _ = inbound
        leave_review = importlib.import_module("flows.leave_review")
        source = (Path(leave_review.__file__)).read_text(encoding="utf-8")
        assert "REVIEW_ATTRIBUTION_ENABLED" in source
        assert "REVIEW_ATTRIBUTION_ENABLED" in (INBOUND / "handler.py").read_text(
            encoding="utf-8")

    def test_a_storage_failure_is_swallowed_rather_than_losing_the_reply(self, inbound):
        """Attribution is a nicety; answering the customer is not.

        A DynamoDB blip must cost the order reference, not the review form.
        """
        handler, fake = inbound
        fake.arm_failure(handler.FLOW_DRAFTS_TABLE, "put_item", RuntimeError("boom"))
        assert handler._park_review_reference(QA_PHONE, REFERENCE, "req-1") is False


class TestTheInboundBranchIsWiredAndGated:
    """Source-level, for the same reason `test_flow_data_exchange_failure.py` is.

    Reaching this branch through `_process_message` needs a full SNS envelope plus contact
    and media plumbing; these four properties are about WHERE the branch sits and WHAT
    gates it, which is exactly what source answers and an end-to-end fixture obscures.
    """

    @property
    def source(self) -> str:
        return (INBOUND / "handler.py").read_text(encoding="utf-8")

    def test_the_branch_is_behind_the_flag(self):
        assert "if _review_attribution_enabled():" in self.source

    def test_it_sits_after_the_exact_match_loop_so_it_cannot_shadow_it(self):
        text = self.source
        loop = text.index("for flow_key, trigger in flow_triggers.items():")
        branch = text.index("if _review_attribution_enabled():")
        assert loop < branch, "`review` alone must keep taking the existing keyword path"

    def test_it_respects_the_standby_ownership_guard(self):
        assert "_may_send('leave_review_attributed')" in self.source

    def test_it_logs_the_phone_masked_and_the_reference_in_full(self):
        """The reference is neither a secret nor a phone number.

        Logging it whole is what makes a review traceable end to end without unmasking
        anything - the same reasoning `reference_id` carries on the payment path.
        """
        text = self.source
        start = text.index("'event': 'review_attributed_flow_sent'")
        block = text[start:start + 400]
        assert "mask_phone(sender_phone)" in block
        assert "mask_contact_id(contact_id)" in block
        assert "'reference': review_reference" in block

    def test_a_park_failure_is_visible_on_the_event_it_emits(self):
        """The boolean is CONSUMED, not discarded.

        A park failure degrades to an unattributed review - the right trade, since the
        customer still gets the form - but silently. Carrying the result onto the one event
        this branch emits makes a recurring DynamoDB problem answerable from a single
        metric filter, instead of looking like customers not using the website door.
        """
        text = self.source
        assert "parked = _park_review_reference(" in text
        start = text.index("'event': 'review_attributed_flow_sent'")
        assert "'attributed': parked" in text[start:start + 400]

    def test_nothing_here_can_message_a_business_number(self):
        """The `wa.me` door is the CUSTOMER messaging US; this branch only replies.

        Asserted as a property so a future edit cannot introduce a hardcoded destination.

        The slice runs to the branch's own `return`, not to a character count: a fixed
        window silently stops covering the code it was written to cover the moment anyone
        adds a line, which is a test that passes by shrinking.
        """
        text = self.source
        start = text.index("if _review_attribution_enabled():")
        end = text.index("return  # Skip AI automation", start)
        block = text[start:end]
        assert "_send_generic_flow(" in block, "the slice no longer covers the send call"
        for business in ("918031830030", "919330994400", "919903300044"):
            assert business not in block
        assert "sender_phone=sender_phone" in block
