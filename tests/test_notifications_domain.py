"""The connected-call notification domain: trigger, recipient, ordering, claims.

Provenance — what was measured before this was written
-----------------------------------------------------
Eight live notification producers existed across four Lambdas. **Seven** fired on
something that is not a connection. CloudWatch over 14 days, at the time of writing:

    plivo-answer  plivo_post_call_sms_queued      32   PROHIBITED (hangup)
    plivo-answer  plivo_dial_event                 0   the only compliant trigger
    whatsapp-calling  call_event                   0   (12,180 log lines total)
    whatsapp-calling  disconnect_sms_triggered     0   PROHIBITED (terminate)
    whatsapp-calling  call_wa_template_sent        0   PROHIBITED (connect = setup)
    whatsapp-calling  post_call_sent               0   PROHIBITED (post_call_sip)
    two CDR-replay ingesters (since deleted)       0   PROHIBITED (CDR replay)

So the only connected-call notification reaching real customers was triggered by
**hangup**, and the one compliant path had never fired - its claim table
(`PstnNotificationDelivery`) is declared in four places and exists in none, so every
attempt raised `ClaimStoreUnavailable` and answered 503.

The recipient defect these tests pin
------------------------------------
`pstn/notifications.handle_connected` parsed `Direction` and then did
``destination = event.caller`` unconditionally. On an outbound call Plivo's ``From``
is our own CLI, so a connected outbound call would have texted ``+919330994400`` —
our own number, billed to us, under our own registered DLT sender.

These tests are offline. No AWS, no provider calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.notifications import events as events_mod  # noqa: E402
from lambda_utils.notifications import keys as keys_mod  # noqa: E402
from lambda_utils.notifications import policy as policy_mod  # noqa: E402
from lambda_utils.notifications import states as states_mod  # noqa: E402

CUSTOMER = "+919876543210"
CUSTOMER_2 = "+918765432109"
FOREIGN = "+6581234567"
BUSINESS_WA1 = "+919330994400"
BUSINESS_WA2 = "+919903300044"
BUSINESS_PSTN = "+918031830030"
A_LEG = "a-leg-uuid-1234"

PHONE1_META = "1016149501586345"
PHONE2_META = "1055232054343117"


def plivo_params(**overrides):
    """A signed, connected inbound Plivo dial callback."""
    params = {
        "DialAction": "connected",
        "DialALegUUID": A_LEG,
        "DialBLegUUID": "b-leg-uuid-9999",
        "CallUUID": A_LEG,
        "Direction": "inbound",
        "From": CUSTOMER,
        "To": BUSINESS_PSTN,
    }
    params.update(overrides)
    return params


# ══════════════════════════════════════════════════════════════════════════════
# The trigger. Only a verified remote-connected state may produce an event.
# ══════════════════════════════════════════════════════════════════════════════

class TestOnlyConnectedIsATrigger:
    def test_connected_inbound_builds_an_event(self):
        event, reason = events_mod.from_plivo_dial_callback(plivo_params())
        assert reason == ""
        assert event is not None
        assert event.provider == "plivo"
        assert event.canonical_call_id == A_LEG
        assert event.direction == "inbound"

    @pytest.mark.parametrize("action", ["answer", "hangup", "digits"])
    def test_the_other_three_dial_actions_are_refused(self, action):
        """Verified against Plivo's official Dial status reporting docs on
        2026-09-21: callback `DialAction` is one of answer, connected, hangup,
        digits. `answer` is NOT a connection - on an outbound dial it can fire for
        the A-leg while the remote party is still ringing, the same mistake as
        trusting the Browser SDK's `onCallConnected`."""
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(DialAction=action))
        assert event is None
        assert reason == f"not_connected_{action}"

    def test_absent_dial_action_is_refused(self):
        params = plivo_params()
        del params["DialAction"]
        event, reason = events_mod.from_plivo_dial_callback(params)
        assert event is None
        assert reason == "no_dial_action"

    def test_an_unknown_dial_action_is_refused_not_assumed(self):
        """A value Plivo adds later must not be silently treated as a connection."""
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(DialAction="bridged"))
        assert event is None
        assert reason == "unknown_dial_action"

    @pytest.mark.parametrize("prohibited", [
        "ringing", "initiated", "permission", "rejected", "failed", "unanswered",
        "hangup", "disconnect", "cdr_replay", "onCallConnected", "post_call_sip",
    ])
    def test_every_state_the_brief_prohibits_produces_nothing(self, prohibited):
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(DialAction=prohibited))
        assert event is None, f"{prohibited} must not be a trigger"
        assert reason != ""


class TestCanonicalCallId:
    def test_a_leg_is_the_key_not_call_uuid(self):
        """On a `<Dial>` the A-leg is the original call and the B-leg is the dialled
        party. Callbacks arrive carrying either, so keying on CallUUID claims the two
        legs separately and sends one call two messages."""
        event, _ = events_mod.from_plivo_dial_callback(
            plivo_params(DialALegUUID=A_LEG, CallUUID="a-different-uuid"))
        assert event.canonical_call_id == A_LEG

    def test_b_leg_is_never_the_key(self):
        event, _ = events_mod.from_plivo_dial_callback(plivo_params())
        assert event.canonical_call_id != "b-leg-uuid-9999"

    def test_missing_a_leg_refuses(self):
        params = plivo_params()
        del params["DialALegUUID"]
        params["CallUUID"] = "only-a-call-uuid"
        event, reason = events_mod.from_plivo_dial_callback(params)
        assert event is None
        assert reason == "no_a_leg_uuid"

    @pytest.mark.parametrize("unsafe", [
        "has:a:colon", "has space", "has\nnewline", "x" * 200,
    ])
    def test_an_id_that_cannot_be_a_claim_key_refuses(self, unsafe):
        """`:` is the key separator, so a value containing one forges a different key
        shape. An id that cannot be made idempotent has no safe send path."""
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(DialALegUUID=unsafe))
        assert event is None
        assert reason in ("unsafe_canonical_call_id", "no_a_leg_uuid")


# ══════════════════════════════════════════════════════════════════════════════
# The recipient. This is the live bug.
# ══════════════════════════════════════════════════════════════════════════════

class TestRecipientFollowsDirection:
    def test_inbound_notifies_the_external_caller(self):
        event, _ = events_mod.from_plivo_dial_callback(
            plivo_params(Direction="inbound", From=CUSTOMER, To=BUSINESS_PSTN))
        assert event.external_party == CUSTOMER
        assert event.business_number == BUSINESS_PSTN

    def test_outbound_notifies_the_external_callee_not_our_own_cli(self):
        """The defect, stated as a test. The retired module did
        `destination = event.caller` unconditionally, so this case resolved to
        `From` - our own business CLI."""
        event, _ = events_mod.from_plivo_dial_callback(
            plivo_params(Direction="outbound", From=BUSINESS_PSTN, To=CUSTOMER))
        assert event.external_party == CUSTOMER, (
            "outbound must notify the dialled customer, not the origin number")
        assert event.business_number == BUSINESS_PSTN

    @pytest.mark.parametrize("raw,expected", [
        ("inbound", "inbound"), ("INBOUND", "inbound"), ("  in  ", "inbound"),
        ("incoming", "inbound"), ("outbound", "outbound"), ("OUT", "outbound"),
        ("outgoing", "outbound"), ("outbound-api", "outbound"),
    ])
    def test_direction_spellings_normalize(self, raw, expected):
        # The From/To pair must match the direction under test. An earlier draft of
        # this test overrode only `Direction`, leaving `To` as our own PSTN number -
        # and the business-number backstop correctly refused all four outbound cases.
        # That was the guard working, not a bug, but it makes the point that these two
        # fields cannot be varied independently.
        if expected == "outbound":
            params = plivo_params(Direction=raw, From=BUSINESS_PSTN, To=CUSTOMER)
        else:
            params = plivo_params(Direction=raw, From=CUSTOMER, To=BUSINESS_PSTN)
        event, _ = events_mod.from_plivo_dial_callback(params)
        assert event is not None, raw
        assert event.direction == expected
        assert event.external_party == CUSTOMER

    @pytest.mark.parametrize("raw", ["", None, "sideways", "unknown", "both"])
    def test_ambiguous_direction_refuses_rather_than_guessing(self, raw):
        """There is no safe default. Guessing inbound texts our own number on every
        outbound call; guessing outbound texts the agent endpoint on every inbound
        one."""
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(Direction=raw))
        assert event is None
        assert reason == "ambiguous_direction"


class TestBusinessNumberBackstop:
    """Direction is the rule; the registry is the backstop. Both are enforced because
    they fail differently - a wrong `Direction` defeats the rule but not the registry,
    and an unregistered business number defeats the registry but not the rule."""

    @pytest.mark.parametrize("business", [BUSINESS_WA1, BUSINESS_WA2, BUSINESS_PSTN])
    def test_all_three_of_our_numbers_are_registered(self, business):
        assert events_mod.is_business_number(business) is True

    @pytest.mark.parametrize("business", [BUSINESS_WA1, BUSINESS_WA2, BUSINESS_PSTN])
    def test_a_wrong_direction_cannot_make_us_message_ourselves(self, business):
        """Provider says inbound, but `From` is one of our own numbers. The rule
        alone would accept it; the registry refuses."""
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(Direction="inbound", From=business, To=CUSTOMER))
        assert event is None
        assert reason == "recipient_is_business_number"

    def test_outbound_to_our_own_number_is_refused(self):
        event, reason = events_mod.from_plivo_dial_callback(
            plivo_params(Direction="outbound", From=BUSINESS_PSTN, To=BUSINESS_WA1))
        assert event is None
        assert reason == "recipient_is_business_number"

    @pytest.mark.parametrize("formatted", [
        "919330994400", "+91 93309 94400", "+91-93309-94400", "  +919330994400 ",
    ])
    def test_formatting_does_not_defeat_the_registry(self, formatted):
        assert events_mod.is_business_number(formatted) is True

    def test_a_customer_number_is_not_a_business_number(self):
        assert events_mod.is_business_number(CUSTOMER) is False
        assert events_mod.is_business_number(FOREIGN) is False

    def test_registry_is_overridable_but_defaults_populated(self, monkeypatch):
        """An empty default would silently remove the backstop, so the default is the
        full known set."""
        monkeypatch.delenv("NOTIF_BUSINESS_NUMBERS", raising=False)
        assert len(events_mod.business_numbers()) == 3
        monkeypatch.setenv("NOTIF_BUSINESS_NUMBERS", "+447700900000")
        assert events_mod.is_business_number("+447700900000") is True
        assert events_mod.is_business_number(BUSINESS_WA1) is False


class TestMetaIsNotWiredUp:
    """The brief: verify Meta's connected state before selecting a trigger, and do not
    invent a webhook event or use hangup as connection evidence.

    Measured: the official cloud-api/calling/call-events page was unreachable on
    2026-09-21, and the account has delivered ZERO call events in 14 days against
    12,180 log lines. So no Meta event is accepted."""

    @pytest.mark.parametrize("event_type", [
        "connect", "terminate", "ringing", "offer", "accept", "reject",
        "pre_accept", "call_permission_response", "call_permission_status",
    ])
    def test_no_meta_event_is_a_trigger(self, event_type):
        event, reason = events_mod.from_meta_call_event({"event": event_type})
        assert event is None
        assert reason == f"meta_state_not_a_trigger_{event_type}"

    def test_connect_is_call_setup_not_an_answer(self):
        """Meta's `connect` carries the SDP offer - it is setup, before anyone
        answered. The retired handler treated it as a send trigger."""
        event, reason = events_mod.from_meta_call_event(
            {"event": "connect", "session": {"sdp": "v=0..."}})
        assert event is None
        assert "not_a_trigger" in reason

    def test_an_unrecognised_meta_shape_is_also_refused(self):
        event, reason = events_mod.from_meta_call_event({"event": "whatever_is_next"})
        assert event is None
        assert reason == "meta_connected_state_unverified"

    def test_the_note_records_why(self):
        note = events_mod.META_TRIGGER_NOTE
        assert "UNVERIFIED" in note
        assert "ZERO call events" in note


# ══════════════════════════════════════════════════════════════════════════════
# Claim keys. A key computed two ways is not an idempotency key.
# ══════════════════════════════════════════════════════════════════════════════

class TestClaimKeys:
    def test_parent_shape(self):
        assert (keys_mod.parent_claim_key("plivo", A_LEG)
                == f"plivo:{A_LEG}:connected-notifications:v2")

    def test_child_is_parent_plus_channel(self):
        parent = keys_mod.parent_claim_key("plivo", A_LEG)
        for channel in ("whatsapp", "sms", "rcs"):
            assert (keys_mod.child_claim_key("plivo", A_LEG, channel)
                    == f"{parent}:{channel}")

    def test_child_resolves_back_to_its_parent_without_a_table_read(self):
        child = keys_mod.child_claim_key("meta", "wacid.ABC", "sms")
        assert keys_mod.parent_of(child) == keys_mod.parent_claim_key("meta", "wacid.ABC")

    def test_provider_is_in_the_key(self):
        """v1 keyed on a bare A-leg UUID, which works only while one provider exists.
        Meta call ids and Plivo leg UUIDs are opaque strings from namespaces that make
        no promise not to collide, and a collision silently suppresses a real
        customer's notification."""
        assert (keys_mod.parent_claim_key("plivo", "shared-id")
                != keys_mod.parent_claim_key("meta", "shared-id"))

    def test_three_channels_give_three_distinct_children(self):
        keys = {keys_mod.child_claim_key("plivo", A_LEG, c)
                for c in keys_mod.SUPPORTED_CHANNELS}
        assert len(keys) == 3

    def test_version_is_v2(self):
        assert keys_mod.CONNECTED_NOTIFICATIONS_VERSION == "v2"
        assert ":v2" in keys_mod.parent_claim_key("plivo", A_LEG)

    @pytest.mark.parametrize("bad", ["", "   ", None, "has:colon", "has space", "x" * 200])
    def test_unsafe_call_ids_are_refused(self, bad):
        with pytest.raises(keys_mod.ClaimKeyError):
            keys_mod.parent_claim_key("plivo", bad)

    @pytest.mark.parametrize("bad", ["", "email", "push", "voice", None])
    def test_unknown_channels_are_refused(self, bad):
        with pytest.raises(keys_mod.ClaimKeyError):
            keys_mod.child_claim_key("plivo", A_LEG, bad)

    def test_the_call_providers_are_plivo_and_meta(self):
        assert keys_mod.SUPPORTED_PROVIDERS == ("plivo", "meta")

    @pytest.mark.parametrize("bad", ["", "unknown-carrier", "sinch", "twilio", None])
    def test_unknown_providers_are_refused(self, bad):
        with pytest.raises(keys_mod.ClaimKeyError):
            keys_mod.parent_claim_key(bad, A_LEG)

    def test_parse_child_round_trips(self):
        child = keys_mod.child_claim_key("plivo", A_LEG, "rcs")
        assert keys_mod.parse_child_key(child) == ("plivo", A_LEG, "v2", "rcs")

    def test_parse_tells_the_two_shapes_apart(self):
        """Used to distinguish a parent claim from a child key, so asking is not an
        error and must not raise."""
        parent = keys_mod.parent_claim_key("plivo", A_LEG)
        assert keys_mod.parse_child_key(parent) is None
        assert keys_mod.parse_parent_key(parent) == ("plivo", A_LEG, "v2")
        child = keys_mod.child_claim_key("plivo", A_LEG, "sms")
        assert keys_mod.parse_parent_key(child) is None

    @pytest.mark.parametrize("junk", ["", "nonsense", "a:b", "a:b:c:d:e:f:g", None])
    def test_parsing_junk_returns_none_rather_than_raising(self, junk):
        assert keys_mod.parse_child_key(junk) is None
        assert keys_mod.parse_parent_key(junk) is None
        assert keys_mod.parent_of(junk) == ""

    def test_legacy_v1_keys_are_derivable_for_suppression(self):
        """Needed so the version bump does not re-notify callers served under v1."""
        assert keys_mod.legacy_v1_parent_key(A_LEG) == f"{A_LEG}:connected-notifications:v1"
        assert keys_mod.legacy_v1_child_key(A_LEG, "sms") == f"{A_LEG}:sms:v1"

    def test_there_is_no_v1_whatsapp_key_to_fabricate(self):
        """v1 only had sms and rcs. WhatsApp was sent by a different, unclaimed path,
        so returning a key here would let a caller conclude 'not previously sent' from
        a key that never existed."""
        assert keys_mod.legacy_v1_child_key(A_LEG, "whatsapp") == ""


# ══════════════════════════════════════════════════════════════════════════════
# The state machine.
# ══════════════════════════════════════════════════════════════════════════════

class TestStateLadder:
    def test_accepted_is_below_sent(self):
        """A provider's 200 carries a message id, not evidence of transmission.
        Writing SENT at that moment claims something the provider has not said - the
        same defect fixed in the WhatsApp status lifecycle in Phase 2."""
        assert states_mod.rank("ACCEPTED") < states_mod.rank("SENT")

    def test_failed_sits_below_delivered(self):
        """A failure report arriving after the handset confirmed arrival is refused:
        positive evidence of delivery is stronger than an earlier failure report."""
        assert states_mod.rank("FAILED") < states_mod.rank("DELIVERED")
        applied, reason = states_mod.apply_receipt("DELIVERED", "FAILED")
        assert applied is False
        assert reason == "out_of_order"

    def test_failed_after_sent_applies(self):
        applied, _ = states_mod.apply_receipt("SENT", "FAILED")
        assert applied is True

    def test_delivered_after_failed_is_allowed(self):
        applied, _ = states_mod.apply_receipt("FAILED", "DELIVERED")
        assert applied is False, "FAILED is terminal; see TERMINAL_STATES"

    def test_reconciliation_required_is_below_any_real_outcome(self):
        """It means 'we do not know'. Any real answer is more informative."""
        for better in ("ACCEPTED", "SENT", "DELIVERED", "READ", "FAILED"):
            applied, _ = states_mod.apply_receipt("RECONCILIATION_REQUIRED", better)
            assert applied is True, better

    def test_unknown_state_ranks_zero_and_never_wins(self):
        assert states_mod.rank("TELEPORTED") == 0
        assert states_mod.rank(None) == 0
        for known in states_mod.ALL_STATES:
            applied, reason = states_mod.apply_receipt(known, "TELEPORTED")
            assert applied is False, known
            assert reason == "unknown_state"

    def test_case_and_whitespace_tolerated(self):
        assert states_mod.rank("  sent ") == states_mod.rank("SENT")
        assert states_mod.normalize(" delivered ") == "DELIVERED"

    def test_normalize_returns_empty_for_unknown_rather_than_raising(self):
        assert states_mod.normalize("nope") == ""
        assert states_mod.normalize(None) == ""


class TestTerminalStates:
    @pytest.mark.parametrize("terminal", ["READ", "FAILED", "SKIPPED"])
    def test_nothing_follows_a_terminal_state(self, terminal):
        assert states_mod.is_terminal(terminal) is True
        assert list(states_mod.successors(terminal)) == []
        for target in states_mod.ALL_STATES:
            applied, reason = states_mod.apply_receipt(terminal, target)
            assert applied is False, f"{terminal} -> {target}"
            assert reason in ("duplicate_state", f"terminal_{terminal.lower()}")

    def test_delivered_is_not_terminal_because_read_follows_it(self):
        assert states_mod.is_terminal("DELIVERED") is False
        assert "READ" in states_mod.successors("DELIVERED")

    def test_skipped_outranks_everything_but_is_unreachable_after_a_send(self):
        """The high rank stops a confused late receipt resurrecting a channel policy
        already closed; the transition table stops it being reached after a send.
        Both guards point the same way."""
        assert states_mod.rank("SKIPPED") > states_mod.rank("READ")
        for sent_state in ("ACCEPTED", "SENT", "DELIVERED"):
            assert states_mod.can_transition(sent_state, "SKIPPED") is False
        assert states_mod.can_transition("PENDING", "SKIPPED") is True
        assert states_mod.can_transition("READY", "SKIPPED") is True


class TestTransitionLegality:
    def test_the_happy_path_is_legal_end_to_end(self):
        chain = ["PENDING", "READY", "LEASED", "ACCEPTED", "SENT", "DELIVERED", "READ"]
        for source, target in zip(chain, chain[1:]):
            assert states_mod.can_transition(source, target), f"{source} -> {target}"
            applied, reason = states_mod.apply_receipt(source, target)
            assert applied is True, f"{source} -> {target}: {reason}"

    def test_leased_back_to_ready_is_the_retry_and_lease_reclaim_edge(self):
        """There is no TRANSIENT_FAILED state. A transient fault returns the delivery
        to READY for a bounded retry, and the same edge reclaims an expired lease."""
        assert states_mod.can_transition("LEASED", "READY") is True

    def test_a_transient_fault_never_reaches_failed_directly_from_ready(self):
        assert states_mod.can_transition("READY", "ACCEPTED") is False
        assert states_mod.can_transition("READY", "SENT") is False

    def test_initial_write_of_any_state_is_legal(self):
        for state in states_mod.ALL_STATES:
            assert states_mod.can_transition(None, state) is True
            applied, reason = states_mod.apply_receipt(None, state)
            assert applied is True and reason == "initial"

    def test_same_state_twice_is_a_duplicate_not_progress(self):
        for state in states_mod.ALL_STATES:
            applied, reason = states_mod.apply_receipt(state, state)
            assert applied is False, state
            assert reason in ("duplicate_state", f"terminal_{state.lower()}")

    def test_illegal_and_backwards_are_reported_differently(self):
        _, illegal = states_mod.apply_receipt("PENDING", "DELIVERED")
        assert illegal == "illegal_transition"
        _, backwards = states_mod.apply_receipt("DELIVERED", "SENT")
        assert backwards == "out_of_order"

    def test_every_state_is_reachable_in_the_table(self):
        """Guards against adding a state to the rank map and forgetting the table."""
        reachable = {"PENDING"}
        for state in states_mod.ALL_STATES:
            reachable.update(states_mod.successors(state))
        assert reachable == set(states_mod.ALL_STATES)


class TestAtomicGuard:
    """The DynamoDB form must agree with the in-memory form, or the enforcement and
    the tests are describing different systems."""

    def test_condition_names_the_rank_attribute_and_the_terminals(self):
        expr = states_mod.condition_expression()
        assert states_mod.RANK_ATTRIBUTE in expr
        assert "attribute_not_exists" in expr
        assert ":t_read" in expr and ":t_failed" in expr and ":t_skipped" in expr

    def test_condition_values_carry_the_incoming_rank(self):
        values = states_mod.condition_values("SENT")
        assert values[":rank"] == states_mod.rank("SENT")
        assert values[":t_read"] == "READ"

    def test_allow_initial_false_drops_the_first_write_arm(self):
        strict = states_mod.condition_expression(allow_initial=False)
        assert "attribute_not_exists(stateRank)" not in strict


# ══════════════════════════════════════════════════════════════════════════════
# Channel policy.
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clean_policy_env(monkeypatch):
    for var in ("SINCH_RCS_ENABLED", "AWS_RCS_AVAILABLE",
                "NOTIF_WA_VERIFIED_SENDERS", "NOTIF_BUSINESS_NUMBERS"):
        monkeypatch.delenv(var, raising=False)
    yield


class TestAlwaysThreeDecisions:
    def test_every_call_yields_one_decision_per_channel(self):
        """An ineligible channel gets a SKIPPED decision, not an absent one: 'not
        applicable' and 'we forgot' must be distinguishable on a dashboard."""
        decisions = policy_mod.decide_all(CUSTOMER, sender_phone_id=PHONE1_META)
        assert set(decisions) == set(keys_mod.SUPPORTED_CHANNELS)
        assert len(decisions) == 3

    def test_decisions_carry_a_real_state_from_the_machine(self):
        for decision in policy_mod.decide_all(CUSTOMER, sender_phone_id=PHONE1_META).values():
            assert decision.state in states_mod.ALL_STATES
            assert decision.state in (states_mod.PENDING, states_mod.SKIPPED)

    def test_no_destination_skips_all_three(self):
        for decision in policy_mod.decide_all("").values():
            assert decision.eligible is False
            assert decision.state == states_mod.SKIPPED


class TestSmsPolicy:
    def test_india_routes_to_ap_south_1_with_dlt(self):
        d = policy_mod.decide_sms(CUSTOMER)
        assert d.eligible is True
        assert d.provider == "aws-end-user-messaging"
        assert d.region == "ap-south-1"
        assert d.dlt_template_key == "ivr-default"

    def test_non_india_carries_no_india_dlt_metadata(self):
        """Attaching India DLT metadata to a foreign destination is invalid, and the
        operator accepts the call while silently dropping the message - a failure that
        looks like a success."""
        d = policy_mod.decide_sms(FOREIGN)
        assert d.eligible is True
        assert d.region == "us-east-1"
        assert d.dlt_template_key == ""

    def test_sms_is_always_aws_never_another_provider(self):
        for destination in (CUSTOMER, CUSTOMER_2, FOREIGN, "+14155550100"):
            assert policy_mod.decide_sms(destination).provider == "aws-end-user-messaging"


class TestRcsPolicy:
    def test_india_rcs_is_skipped_while_the_flag_is_off(self):
        d = policy_mod.decide_rcs(CUSTOMER)
        assert d.eligible is False
        assert d.state == states_mod.SKIPPED
        assert "UNSUPPORTED" in d.reason

    def test_india_rcs_uses_sinch_when_enabled(self, monkeypatch):
        monkeypatch.setenv("SINCH_RCS_ENABLED", "true")
        d = policy_mod.decide_rcs(CUSTOMER)
        assert d.eligible is True
        assert d.provider == "sinch-rcs"
        assert d.template_name == "rcsmenu"
        assert "UNVERIFIED" in d.reason, "the rcsmenu id/version is not yet read back"

    def test_non_india_rcs_never_falls_back_to_sinch(self, monkeypatch):
        """Sinch is approved for India only. 'It would have worked' is not a reason to
        breach the provider matrix, and a silent downgrade is how a prohibited
        provider re-enters a system that documented its removal."""
        monkeypatch.setenv("SINCH_RCS_ENABLED", "true")
        d = policy_mod.decide_rcs(FOREIGN)
        assert d.eligible is False
        assert d.provider == "aws-end-user-messaging-rcs"
        assert "sinch" in d.reason.lower() and "NOT used as a fallback" in d.reason

    def test_non_india_rcs_needs_aws_provisioning(self, monkeypatch):
        monkeypatch.setenv("AWS_RCS_AVAILABLE", "true")
        d = policy_mod.decide_rcs(FOREIGN)
        assert d.eligible is True
        assert d.provider == "aws-end-user-messaging-rcs"


class TestWhatsAppPolicy:
    def test_unresolved_sender_refuses_rather_than_picking_a_waba(self):
        """Picking a default sender is how a caller receives a message from a number
        they never contacted, outside the 24-hour window belonging to the conversation
        they actually opened."""
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id="")
        assert d.eligible is False
        assert "SENDER_UNRESOLVED" in d.reason

    def test_no_template_configured_is_skipped_not_sent(self):
        """The shipped state since 2026-10-02. `wd_menu` was the default template
        name and Meta deleted it with every other WhatsApp menu, so the default is
        now empty and the channel refuses rather than naming a template that does
        not exist. This is reported in preference to UNVERIFIED because it is the
        more specific truth."""
        assert policy_mod.WA_TEMPLATE_NAME == ""
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id=PHONE1_META)
        assert d.eligible is False
        assert "TEMPLATE_UNCONFIGURED" in d.reason
        assert d.template_id == "998210796499191"

    def test_unverified_template_is_skipped_not_sent(self, monkeypatch):
        """With a template name configured, the verified-sender check is what refuses.
        Patching the module attribute rather than the env var on purpose:
        WA_TEMPLATE_NAME is read once at import, so setenv would not reach it."""
        monkeypatch.setattr(policy_mod, "WA_TEMPLATE_NAME", "wd_call_followup_v1")
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id=PHONE1_META)
        assert d.eligible is False
        assert "TEMPLATE_UNVERIFIED" in d.reason
        assert d.template_id == "998210796499191"

    def test_verified_sender_becomes_eligible(self, monkeypatch):
        monkeypatch.setattr(policy_mod, "WA_TEMPLATE_NAME", "wd_call_followup_v1")
        monkeypatch.setenv("NOTIF_WA_VERIFIED_SENDERS", PHONE1_META)
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id=PHONE1_META)
        assert d.eligible is True
        assert d.provider == "meta-direct"
        assert d.template_name == "wd_call_followup_v1"
        assert d.template_id == "998210796499191"
        assert d.sender_label == "WABA1"

    def test_a_configured_name_cannot_be_bypassed_by_verification(self, monkeypatch):
        """Verifying a sender must not make an unconfigured template eligible - the
        UNCONFIGURED guard sits ahead of the verified check for exactly this case."""
        monkeypatch.setenv("NOTIF_WA_VERIFIED_SENDERS", PHONE1_META)
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id=PHONE1_META)
        assert d.eligible is False
        assert "TEMPLATE_UNCONFIGURED" in d.reason

    def test_each_phone_id_maps_to_exactly_one_template_object(self):
        """The 'never duplicate from WABA2' rule expressed as data: one phone id
        resolves to one template object, so no code path can send from both."""
        assert policy_mod.WA_SENDER_TEMPLATES[PHONE1_META][0] == "998210796499191"
        assert policy_mod.WA_SENDER_TEMPLATES[PHONE2_META][0] == "2429247000907048"
        ids = [tid for tid, _ in policy_mod.WA_SENDER_TEMPLATES.values()]
        assert len(ids) == len(set(ids))

    def test_secondary_number_uses_its_own_object_not_waba1s(self, monkeypatch):
        monkeypatch.setattr(policy_mod, "WA_TEMPLATE_NAME", "wd_call_followup_v1")
        monkeypatch.setenv("NOTIF_WA_VERIFIED_SENDERS", PHONE2_META)
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id=PHONE2_META)
        assert d.eligible is True
        assert d.template_id == "2429247000907048"
        assert d.sender_label == "WABA2"

    def test_an_unregistered_sender_is_refused(self, monkeypatch):
        monkeypatch.setenv("NOTIF_WA_VERIFIED_SENDERS", "9999")
        d = policy_mod.decide_whatsapp(CUSTOMER, sender_phone_id="9999")
        assert d.eligible is False
        assert "UNKNOWN_SENDER" in d.reason

    def test_verified_senders_defaults_to_empty(self):
        assert policy_mod.wa_verified_senders() == frozenset()


class TestRewindEdges:
    """Two transitions are deliberately backwards on the ladder, and the rank guard
    must not reject them.

    Found by a failing test rather than by review: the first draft applied the
    rank-forward rule to every move, so a transient retry (`LEASED -> READY`) was
    refused as `out_of_order`. In production that would have stranded every retryable
    delivery at `LEASED` until its lease expired - and then stranded it again on the
    next attempt, forever, with no terminal state and no alarm.
    """

    def test_the_retry_edge_is_allowed_despite_going_backwards(self):
        assert states_mod.rank("READY") < states_mod.rank("LEASED")
        applied, reason = states_mod.apply_receipt("LEASED", "READY")
        assert applied is True
        assert reason == "rewind"

    def test_the_reconciler_edge_is_allowed_too(self):
        assert states_mod.rank("READY") < states_mod.rank("RECONCILIATION_REQUIRED")
        applied, reason = states_mod.apply_receipt("RECONCILIATION_REQUIRED", "READY")
        assert applied is True
        assert reason == "rewind"

    def test_exactly_two_rewind_edges_exist(self):
        assert states_mod.REWIND_EDGES == frozenset({
            ("LEASED", "READY"), ("RECONCILIATION_REQUIRED", "READY")})

    @pytest.mark.parametrize("source", ["ACCEPTED", "SENT", "DELIVERED"])
    def test_a_sent_delivery_can_never_be_rewound(self, source):
        """The reason the edges are enumerated rather than inferred. A rule like 'any
        move to READY is a rewind' would admit `DELIVERED -> READY`, which is not a
        retry - it is losing a delivery confirmation."""
        assert states_mod.is_rewind(source, "READY") is False
        applied, _ = states_mod.apply_receipt(source, "READY")
        assert applied is False

    def test_pending_to_ready_is_forward_not_a_rewind(self):
        applied, reason = states_mod.apply_receipt("PENDING", "READY")
        assert applied is True
        assert reason == "forward"

    def test_the_rewind_guard_tests_the_source_state_not_the_rank(self):
        """A rank comparison is the wrong test for a move that is backwards by design,
        so the atomic form switches shape."""
        expr = states_mod.condition_expression("READY")
        assert "#state IN (:rw0, :rw1)" in expr
        assert f"{states_mod.RANK_ATTRIBUTE} < :rank" not in expr

        values = states_mod.condition_values("READY")
        assert {values[":rw0"], values[":rw1"]} == {"LEASED", "RECONCILIATION_REQUIRED"}

    def test_the_rewind_guard_is_stricter_than_the_rank_guard(self):
        """It admits exactly two source states, where the rank form would admit any row
        with a lower rank."""
        sources = states_mod.REWIND_SOURCES["READY"]
        assert set(sources) == {"LEASED", "RECONCILIATION_REQUIRED"}
        assert "DELIVERED" not in sources

    def test_a_receipt_still_gets_the_rank_guard(self):
        expr = states_mod.condition_expression("DELIVERED")
        assert f"{states_mod.RANK_ATTRIBUTE} < :rank" in expr
        assert ":rw0" not in expr

    def test_rank_is_always_supplied_so_the_row_stays_consistent(self):
        """The update expression sets `stateRank` whichever guard was used, so the
        row's rank must end up matching its state either way."""
        assert states_mod.condition_values("READY")[":rank"] == states_mod.rank("READY")
