"""`parse_handover` must read the documented shape AND the two shapes we have seen.

Why this test exists at all
---------------------------
Ten real `messaging_handovers` events survive in `SystemConfigTable`'s 10-deep audit ring
buffer from 2026-07-29 to 2026-08-01, from a period when Conversation Routing was live on
both WABAs. Read directly during the investigation, **none of them matched Meta's
currently documented payload**: they carry either a bare JSON-string `metadata` holding a
`reason`, or the intermediate `previous_owner_app_id` / `previous_owner_app_role` pair,
while the docs specify `previous_owner_role` / `new_owner_role`.

So a parser written from the samples is wrong for the future and a parser written only
from the docs is wrong for everything we have actually observed. The module is written
from the docs and tolerates the legacy shapes, and `shape` records which arm matched —
which is what makes retiring a legacy arm a measurement instead of a guess. These tests
pin all three arms, because dropping one silently is the failure mode.

The fixtures below are modelled on the real stored payloads (reasons `MARKETING_MESSAGE`,
`UNSUPPORTED_MESSAGE`, `end_bad_conversation`, app id `1143680903703001` =
Meta Business Agent) with phone numbers replaced.
"""
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_SHARED = os.path.join(_ROOT, 'amplify', 'functions', 'shared')
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from lambda_utils import thread_ownership as to  # noqa: E402

CALLING_HANDLER = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                               'whatsapp-calling', 'handler.py')


def _documented(control='control_passed', with_context=True):
    """Meta's current documented shape, per the Thread control reference."""
    block = {
        'previous_owner_role': 'ai_agent',
        'new_owner_role': 'business',
        'recipient': {'user_id': 'BSUID-DOC-1', 'wa_id': '918100640044'},
        'metadata': {'reason': 'HUMAN_AGENT_REQUESTED'},
    }
    if with_context:
        block['conversation_context'] = {
            'summary': 'Customer asked about delivery timelines.'}
    return {
        'messaging_product': 'whatsapp',
        'metadata': {'display_phone_number': '+91 99033 00044',
                     'phone_number_id': '1055232054343117'},
        'contacts': [{'wa_id': '918100640044', 'user_id': 'BSUID-DOC-1'}],
        control: block,
    }


def _legacy_metadata_string(control='control_taken'):
    """Shape (a): `metadata` arrives as a bare JSON STRING carrying the reason.

    This is the commonest of the ten stored samples — seven of them carry a reason of
    MARKETING_MESSAGE, UNSUPPORTED_MESSAGE or NO_ACTIVE_CONTROLLER this way and no roles
    at all.
    """
    return {
        'metadata': {'phone_number_id': '1016149501586345'},
        'contacts': [{'wa_id': '919330994400'}],
        control: {'metadata': '{"reason": "MARKETING_MESSAGE"}'},
    }


def _legacy_app_role(control='control_passed'):
    """Shape (b): the intermediate `previous_owner_app_id` / `_app_role` pair.

    Taken from the 2026-07-29T07:30:07Z event on WABA2, the one that names
    `meta_business_agent` and app `1143680903703001` — the single strongest piece of
    evidence that routing was genuinely live rather than merely configured.
    """
    return {
        'metadata': {'phone_number_id': '1055232054343117'},
        'contacts': [{'wa_id': '918100640044', 'user_id': 'BSUID-LEGACY-2'}],
        control: {
            'previous_owner_app_id': '1143680903703001',
            'previous_owner_app_role': 'meta_business_agent',
            'metadata': '{"reason": "end_bad_conversation"}',
        },
    }


class TestTheThreeShapes:
    def test_documented_shape_yields_both_roles(self):
        rec = to.parse_handover(_documented())
        assert rec['control'] == 'control_passed'
        assert rec['previous_owner_role'] == 'ai_agent'
        assert rec['new_owner_role'] == 'business'
        assert rec['shape'] == to.SHAPE_DOCUMENTED

    def test_legacy_metadata_string_yields_its_reason(self):
        """The reason is the only usable fact in seven of the ten stored samples."""
        rec = to.parse_handover(_legacy_metadata_string())
        assert rec['control'] == 'control_taken'
        assert rec['reason'] == 'MARKETING_MESSAGE'
        assert rec['metadata'] == {'reason': 'MARKETING_MESSAGE'}
        assert rec['shape'] == to.SHAPE_LEGACY_METADATA_STRING

    def test_legacy_app_role_maps_onto_previous_owner_role(self):
        """`previous_owner_app_role` answers the same question as the documented field,
        so it must land in the same slot rather than needing a second reader."""
        rec = to.parse_handover(_legacy_app_role())
        assert rec['previous_owner_role'] == 'meta_business_agent'
        assert rec['previous_owner_app_id'] == '1143680903703001'
        assert rec['reason'] == 'end_bad_conversation'
        assert rec['shape'] == to.SHAPE_LEGACY_APP_ROLE

    @pytest.mark.parametrize('builder', [_documented, _legacy_metadata_string,
                                         _legacy_app_role])
    def test_every_shape_resolves_the_phone_number_id(self, builder):
        """The phone id is half the thread key, so losing it loses the thread."""
        assert to.parse_handover(builder())['phone_number_id']

    @pytest.mark.parametrize('control', ['control_passed', 'control_taken'])
    def test_both_control_directions_are_recognised(self, control):
        assert to.parse_handover(_documented(control))['control'] == control


class TestConversationContextIsConditional:
    def test_present_when_sent(self):
        rec = to.parse_handover(_documented(with_context=True))
        assert isinstance(rec['conversation_context'], dict)
        assert rec['conversation_context']['summary']

    def test_absent_yields_none_and_does_not_raise(self):
        """The docs call it conditional. Every stored sample we have lacks it, so
        'absent' is the normal case and must not read as an error."""
        rec = to.parse_handover(_documented(with_context=False))
        assert rec['conversation_context'] is None

    def test_an_empty_dict_is_treated_as_absent(self):
        payload = _documented(with_context=False)
        payload['control_passed']['conversation_context'] = {}
        assert to.parse_handover(payload)['conversation_context'] is None


class TestParsingNeverRaises:
    @pytest.mark.parametrize('garbage', [
        None, '', 'not a dict', 0, [], {}, {'control_passed': 'a string'},
        {'metadata': 'not a dict', 'control_taken': None},
        {'contacts': 'not a list', 'control_passed': {}},
        {'contacts': ['not a dict'], 'control_passed': {'metadata': '{{{not json'}},
    ])
    def test_garbage_yields_a_record_rather_than_an_exception(self, garbage):
        """This runs on the inbound webhook path beside real customer messages. A
        malformed handover must not be able to change what happens to them."""
        rec = to.parse_handover(garbage)
        assert isinstance(rec, dict)
        assert set(rec) >= {'control', 'shape', 'conversation_context'}

    def test_unrecognised_payload_is_labelled_unknown(self):
        assert to.parse_handover({'something_else': {}})['shape'] == to.SHAPE_UNKNOWN

    def test_undecodable_metadata_string_does_not_lose_the_event(self):
        rec = to.parse_handover({'control_taken': {'metadata': '{{{not json'}})
        assert rec['control'] == 'control_taken'
        assert rec['metadata'] == {}
        assert rec['reason'] == ''


class TestIngressNamesBothRoutingFields:
    """C9. `standby` and `messaging_handovers` already forwarded via the catch-all
    `else`, so nothing about delivery changes — but they logged as "Unhandled webhook
    field", which reads as a defect during triage and made the explicit branch list the
    wrong answer to "do we receive routing webhooks?"."""

    @pytest.fixture(scope='class')
    def source(self):
        with open(CALLING_HANDLER, encoding='utf-8') as fh:
            return fh.read()

    def test_both_fields_are_named_in_a_branch_of_their_own(self, source):
        assert "elif field in ('standby', 'messaging_handovers'):" in source

    def test_the_branch_emits_a_named_event(self, source):
        assert "'event': 'conversation_routing_webhook'" in source

    def test_the_catch_all_else_is_still_there(self, source):
        """The named branch must not have replaced the backstop: an unknown field still
        has to reach the worker rather than being dropped at the door."""
        assert 'Unhandled webhook field' in source
