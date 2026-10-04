"""Every WhatsApp menu is deleted from the inbound handler, and nothing goes silent.

The owner's instruction on 2026-10-02 was to delete the menu entirely and build a
fresh one later. A previous change tried to do it by emptying
`DEFAULT_ONE_MENU['sections']`, which was worse than leaving it alone: the
interactive-list sender short-circuited on an empty `sections`, so a greeting
produced TOTAL SILENCE while all the dispatch machinery stayed behind.

So this file pins both halves of the real deletion:

* the menu configs, their getters, the row-id dispatch table and the
  interactive-list sender are **gone**, not emptied; and
* the three trigger paths that used to open a menu - greeting keywords, the
  button/ice-breaker texts and the customer-service keywords - now reach a plain-text
  placeholder. The trigger SETS deliberately survive: they are live on Meta's side
  as QR prefills, ice breakers and slash commands, and you cannot answer a trigger
  word without a trigger-word set.

A tap on a list row still sitting in a customer's chat history gets the placeholder
too. That is the accepted cost of deleting the dispatch table rather than hiding it.

The module is loaded by explicit file path under a unique name, the same as
`test_own_prefill_triggers_menu.py`: every Lambda entry point in this repo is called
`handler.py` and `conftest.py` clears `sys.modules['handler']` between tests, so a
plain `import handler` resolves to whichever one is first on the path.
"""
import ast
import importlib.util
import os
import re
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_INBOUND_DIR = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                            'inbound-whatsapp-handler')
HANDLER_PATH = os.path.join(_INBOUND_DIR, 'handler.py')
AI_HANDLER_PATH = os.path.join(_ROOT, 'amplify', 'functions', 'ai',
                               'ai-generate-response', 'handler.py')

# The agreed stand-in copy. Asserted character for character: it is customer-facing,
# and it is the only thing a greeting produces now.
PLACEHOLDER = "We're refreshing our menu - please type *menu* and we'll help you."

# Menu configs, their getters, and the interactive-list sender. None of these may
# come back as a module attribute.
DELETED_NAMES = [
    'DEFAULT_ONE_MENU',
    'DEFAULT_MAIN_MENU',
    'DEFAULT_CUSTOMERSERVICE_MENU',
    'DEFAULT_BHARAT_STACK_MENU',
    'DEFAULT_LANGUAGE_PICKER',
    'REGION_LANGUAGE_LISTS',
    '_get_welcome_config',
    '_get_customerservice_menu',
    '_get_bharat_stack_menu',
    '_get_language_picker_config',
    '_get_region_language_list',
    '_send_interactive_list',
    # Phase 2, 2026-10-02. The IVR button router, the list-reply router and the
    # follow-up button chooser ("What next? / Explore More / All Set"): a button
    # chooser is a navigation menu, so it went with the rest.
    '_handle_ivr_response',
    '_handle_list_reply',
    '_send_reply_buttons',
    '_send_followup_buttons',
]

# The three trigger paths that used to open a menu. Each is a function-local set, so
# it is checked against the source rather than imported.
TRIGGER_SETS = ['HI_KEYWORDS', 'BUTTON_MENU_TRIGGERS', 'CUSTOMERSERVICE_KEYWORDS']


@pytest.fixture(scope='module')
def handler_source():
    with open(HANDLER_PATH, encoding='utf-8') as fh:
        return fh.read()


@pytest.fixture(scope='module')
def handler_tree(handler_source):
    return ast.parse(handler_source)


@pytest.fixture(scope='module')
def wa():
    """The inbound handler, loaded under a UNIQUE module name - see the docstring."""
    for path in (os.path.join(_ROOT, 'amplify', 'functions', 'shared'),
                 _INBOUND_DIR,
                 os.path.join(_INBOUND_DIR, 'modules')):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location('inbound_wa_menus_deleted', HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wa_menus_deleted'] = module
    spec.loader.exec_module(module)
    return module


def _nested_literal(source: str, name: str):
    """literal_eval a `NAME = {...}` assignment at ANY nesting depth."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not found in source')


def _flow_keywords(wa):
    """Every keyword that resolves to a flow, lowercased."""
    out = {}
    for key, trigger in wa.DEFAULT_FLOW_TRIGGERS.items():
        for keyword in trigger.get('keywords', []):
            out[keyword.lower()] = key
    return out


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name} not found')


def _trigger_branch(source: str, name: str) -> str:
    """The source from a trigger set's ASSIGNMENT to the first `return` after it.

    That slice is the whole branch: the set literal, the guard, the logging and the
    send. Anchored on the assignment rather than any mention of the name, because
    two comments elsewhere in the file reference HI_KEYWORDS by name.
    """
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.match(r'\s*' + name + r'\s*=', line)]
    assert len(starts) == 1, f'expected exactly one {name} assignment, found {len(starts)}'
    start = starts[0]
    for i in range(start, len(lines)):
        if re.match(r'\s*return\b', lines[i]):
            return '\n'.join(lines[start:i + 1])
    raise AssertionError(f'no return found after the {name} assignment')


class TestEveryMenuIsGone:
    @pytest.mark.parametrize('name', DELETED_NAMES)
    def test_the_module_no_longer_defines_it(self, wa, name):
        assert not hasattr(wa, name), f'{name} is back in the inbound handler'

    def test_the_row_id_dispatch_table_is_gone(self, handler_tree):
        """MENU_TO_KEYWORD was function-local, so an attribute check cannot see it.

        Walked rather than grepped: the table used to sit inside _handle_list_reply.
        """
        for node in ast.walk(handler_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assert target.id != 'MENU_TO_KEYWORD', \
                            f'MENU_TO_KEYWORD is back at line {node.lineno}'

    def test_nothing_calls_the_interactive_list_sender(self, handler_tree):
        """A surviving call would be a NameError at runtime, not a dead branch."""
        for node in ast.walk(handler_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != '_send_interactive_list', \
                    f'interactive list send survives at line {node.lineno}'

    def test_the_welcome_text_config_survives(self, wa):
        """Scope guard. `_get_welcome_config_key` and `_load_welcome_text` read the
        welcome_message TEXT config, not a menu, and must NOT be collateral."""
        assert callable(wa._get_welcome_config_key)
        assert callable(wa._load_welcome_text)

    def test_typed_keyword_flows_survive(self, wa):
        """DEFAULT_FLOW_TRIGGERS drives typed keywords and is untouched, so nothing
        the menu offered becomes unreachable by EVERY route."""
        assert wa.DEFAULT_FLOW_TRIGGERS
        assert callable(wa._get_flow_triggers_config)


class TestNobodyGetsSilence:
    def test_the_placeholder_copy_is_exact(self, wa):
        assert wa.MENU_PLACEHOLDER_TEXT == PLACEHOLDER

    def test_the_placeholder_sender_exists(self, wa):
        assert callable(wa._send_menu_placeholder)

    @pytest.mark.parametrize('name', TRIGGER_SETS)
    def test_the_trigger_set_survives(self, handler_source, name):
        """The sets stay and only what they DO changes: each is live on Meta as a QR
        prefill, an ice breaker or a slash command."""
        assert re.search(r'\s' + name + r'\s*=\s*\{', handler_source), \
            f'{name} was removed - its trigger words would stop being answered'

    @pytest.mark.parametrize('name', TRIGGER_SETS)
    def test_the_trigger_path_reaches_the_placeholder(self, handler_source, name):
        branch = _trigger_branch(handler_source, name)
        assert '_send_menu_placeholder' in branch, \
            f'the {name} path sends no reply - that is the silence this forbids'
        assert '_send_interactive_list' not in branch


class TestATappedRowStillAnswers:
    """Phase 2 removed the two routers this class used to call into.

    `_handle_list_reply` and `_handle_ivr_response` are gone, so the answer is now
    produced inline in the interactive dispatch block. The guarantee is unchanged
    and is what these assertions pin: a tap on a row or a button that is still
    sitting in a customer's chat history gets the plain-text placeholder, never
    silence and never a NameError.
    """

    @staticmethod
    def _interactive_dispatch(handler_source: str) -> str:
        start = handler_source.index("if msg_type == 'interactive':")
        end = handler_source.index("elif interactive_type == 'nfm_reply':", start)
        return handler_source[start:end]

    @pytest.mark.parametrize('reply_type', ['button_reply', 'list_reply'])
    def test_the_dispatch_answers_with_the_placeholder(self, handler_source, reply_type):
        block = self._interactive_dispatch(handler_source)
        branch = block.split(f"elif interactive_type == '{reply_type}':", 1)[1]
        branch = branch.split('elif interactive_type ==', 1)[0]
        assert '_send_menu_placeholder' in branch, \
            f'a tapped {reply_type} sends nothing - that is the silence this forbids'

    @pytest.mark.parametrize('event', ['button_reply_received', 'list_reply_received'])
    def test_the_correlation_log_line_survives(self, handler_source, event):
        """The only handle on a tapped id, and the reason a stale tap is traceable."""
        assert event in self._interactive_dispatch(handler_source)

    def test_the_nfm_reply_branch_is_untouched(self, handler_source):
        """nfm_reply carries India address submissions and post-payment flow
        completions. It is not a menu and must still route."""
        assert "elif interactive_type == 'nfm_reply':" in handler_source
        assert '_handle_address_submission' in handler_source
        assert '_handle_postpay_submission' in handler_source


class TestNothingBecameUnreachable:
    """Carried forward UNCHANGED from tests/test_one_menu.py::TestNothingWasTakenAway.

    This is the wipe's central safety claim: deleting every menu removed a way of
    DISCOVERING things, not the things themselves. Each destination the menu used to
    offer has to stay reachable by a typed keyword, and the Help reply has to keep
    naming them, or the deletion silently took features away with it.

    These assertions predate the wipe and none of them is about a menu, which is why
    they survive it word for word.
    """

    def test_appointment_keywords_survive(self, wa):
        """"Appointment" is out of customer-facing copy, but it stays as an inbound
        alias: it is live in Meta's ice breakers, in a wa.me link, and in customers'
        habits. Same precedent as Bharat Stack."""
        keywords = wa.DEFAULT_FLOW_TRIGGERS['schedule_appointment']['keywords']
        for required in ('appointment', 'schedule appointment', 'book appointment'):
            assert required in keywords
        for added in ('book a visit', 'visit'):
            assert added in keywords

    def test_dropped_rows_are_still_reachable_by_keyword(self, wa, handler_source):
        """Every destination the deleted menus listed answers to a typed keyword."""
        flow_keywords = _flow_keywords(wa)
        assert 'leave review' in flow_keywords
        assert 'order notes' in flow_keywords
        for name, keyword in (('MY_ID_KEYWORDS', 'my id'),
                              ('STORE_KEYWORDS', 'store'),
                              ('GIFT_KEYWORDS', 'gift card'),
                              ('BHARAT_KEYWORDS', 'bharat stack'),
                              ('ABOUT_KEYWORDS', 'about')):
            assert keyword in _nested_literal(handler_source, name)

    def test_help_reply_names_the_dropped_rows(self, handler_source):
        """With no menu left, the Help reply is the ONLY place a customer is told
        these keywords exist."""
        body = handler_source.split('def _send_help_about', 1)[1].split('\ndef ', 1)[0]
        for mention in ('*my id*', '*store*', '*gift card*', '*order notes*',
                        '*review*', '*bharat stack*'):
            assert mention in body, f'{mention} is not discoverable anywhere'


class TestTheRivalMenuIsGone:
    """Carried forward from tests/test_one_menu.py, which this file replaces.

    `ai-generate-response` once carried a sixth menu of its own. Its delivery path
    was dead code, but a menu defined anywhere is a menu that can come back.
    """

    @pytest.fixture(scope='class')
    def ai_source(self):
        with open(AI_HANDLER_PATH, encoding='utf-8') as fh:
            return fh.read()

    def test_ai_handler_defines_no_menu(self, ai_source):
        bot_flow = _nested_literal(ai_source, 'DEFAULT_BOT_FLOW')
        assert 'mainMenu' not in bot_flow, 'a second main menu is back in ai-generate-response'
        assert 'subMenus' not in bot_flow
