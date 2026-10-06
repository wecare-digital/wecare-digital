"""The two Conversation Routing refusal codes must be mapped, and alarmable.

What was wrong
--------------
`2494191` (thread take not permitted — you are not the designated escalation partner)
and `138038` (not the Call primary for this entry point) appeared **nowhere in this
repo**. Both are ownership refusals: Meta rejects the send because of WHO is sending,
not because of what was sent. Unmapped, each one surfaced as a generic send failure in a
stream that also carries rate limits, bad templates and unreachable recipients — which is
exactly how a silent dead end stays invisible for days.

Why `retry` must be False
-------------------------
A retry cannot succeed. The remedy is a change to the routing configuration in Meta
Business Suite, which is console-only and owner-only. Marking either transient would turn
one refusal into a retry storm against an endpoint that will refuse every attempt.

Why the distinct event name is load-bearing
-------------------------------------------
A metric filter on the generic `send_meta_error` line cannot separate an ownership
refusal from everything else, so an alarm on it would either be deafening or useless.
`routing_ownership_rejected` is emitted ALONGSIDE the generic log, never instead of it,
so nothing is lost from the existing failure stream and the alarm has a clean signal.
`scripts/provision_conversation_routing_alarms.py` filters on that exact literal, so
these assertions are what keep the filter and the handlers from drifting apart.

Both tables are lookup-only and both additions are new keys, so no existing code path
changes behaviour: a code that was previously absent and is now present was reaching the
`else`/`None` arm before, which is what still happens for every other unmapped code.
"""
import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUTBOUND = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                        'outbound-whatsapp', 'handler.py')
CALLING = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                       'whatsapp-calling', 'handler.py')

#: 2494191 is a messaging-path refusal and belongs only to the sender. 138038 is the
#: Calling-API refusal and reaches BOTH: outbound maps it because the generic error
#: table is the one place a reader looks up any Meta code, and calling maps it because
#: that is the surface that actually produces it.
EXPECTED_OUTBOUND = (2494191, 138038)
EXPECTED_CALLING = (138038,)


def _table_keys(path: str, name: str) -> set:
    """Integer keys of a module-level dict literal, read via the AST.

    The AST rather than a regex because both tables are hundreds of lines of literal
    and because the comments above them necessarily mention the very codes being
    asserted — a text search would pass on a comment alone.
    """
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            assert isinstance(node.value, ast.Dict), f'{name} is not a dict literal'
            return {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, int)}
    raise AssertionError(f'{name} not found in {path}')


def _table_entry(path: str, name: str, code: int) -> dict:
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            for key, val in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == code:
                    return ast.literal_eval(val)
    raise AssertionError(f'{name}[{code}] not found in {path}')


class TestOutboundTable:
    @pytest.mark.parametrize('code', EXPECTED_OUTBOUND)
    def test_code_is_mapped(self, code):
        assert code in _table_keys(OUTBOUND, 'META_MESSAGE_ERRORS')

    @pytest.mark.parametrize('code', EXPECTED_OUTBOUND)
    def test_code_is_not_retryable(self, code):
        """Retrying an ownership refusal cannot succeed — the fix is in the console."""
        assert _table_entry(OUTBOUND, 'META_MESSAGE_ERRORS', code)['retry'] is False

    @pytest.mark.parametrize('code', EXPECTED_OUTBOUND)
    def test_the_action_text_names_conversation_routing(self, code):
        """The action string is what an on-call reader sees first. If it does not say
        where to look, the mapping has only renamed the mystery."""
        action = _table_entry(OUTBOUND, 'META_MESSAGE_ERRORS', code)['action']
        assert 'Conversation Routing' in action

    def test_the_named_set_matches_the_table(self):
        """The alarm filter keys off this set, so it must not drift from the table."""
        with open(OUTBOUND, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        found = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'ROUTING_OWNERSHIP_ERRORS'
                    for t in node.targets):
                found = tuple(ast.literal_eval(node.value))
        assert found is not None, 'ROUTING_OWNERSHIP_ERRORS not declared'
        assert set(found) == set(EXPECTED_OUTBOUND)
        table = _table_keys(OUTBOUND, 'META_MESSAGE_ERRORS')
        assert set(found) <= table, 'a code is alarmed on but not mapped'


class TestCallingTable:
    @pytest.mark.parametrize('code', EXPECTED_CALLING)
    def test_code_is_mapped(self, code):
        assert code in _table_keys(CALLING, 'META_CALLING_ERRORS')

    def test_the_action_text_says_retrying_will_not_help(self, code=138038):
        entry = _table_entry(CALLING, 'META_CALLING_ERRORS', code)
        assert 'retrying will not help' in entry['action'].lower()

    def test_the_named_set_matches_the_table(self):
        with open(CALLING, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        found = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'ROUTING_OWNERSHIP_ERRORS'
                    for t in node.targets):
                found = tuple(ast.literal_eval(node.value))
        assert found is not None, 'ROUTING_OWNERSHIP_ERRORS not declared'
        assert set(found) == set(EXPECTED_CALLING)
        assert set(found) <= _table_keys(CALLING, 'META_CALLING_ERRORS')


class TestTheDistinctEventIsEmittedAndGuarded:
    """One alarmable event name, guarded on the codes, in all three consumers."""

    @pytest.mark.parametrize('path,expected_sites', [(OUTBOUND, 1), (CALLING, 2)])
    def test_event_is_emitted(self, path, expected_sites):
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        assert source.count("'event': 'routing_ownership_rejected'") == expected_sites

    @pytest.mark.parametrize('path', [OUTBOUND, CALLING])
    def test_emission_is_guarded_on_the_named_set(self, path):
        """Ungated, this would fire on every send failure and the alarm would be noise."""
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        assert 'in ROUTING_OWNERSHIP_ERRORS:' in source

    @pytest.mark.parametrize('path', [OUTBOUND, CALLING])
    def test_the_pre_existing_generic_log_survives(self, path):
        """Added alongside, not instead of. Removing the generic line would quietly
        shrink the existing failure stream everything else is measured from."""
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        marker = ("'event': 'send_meta_error'" if path == OUTBOUND
                  else 'Meta API error')
        assert marker in source
