"""Deleting the shadowing `_is_deterministic_trigger` must not change one decision.

What was wrong
--------------
`inbound-whatsapp-handler/handler.py` defined `_is_deterministic_trigger` **twice**. The
second definition shadowed the first, and the file's own docstring called that out as a
known defect. The consequence was not cosmetic: the first definition is the one that reads
the `ai_hybrid_routing` row from SystemConfigTable and honours `enabled: false`, so the
documented kill switch **could never work** — the function that read it was never the
function being called. Measured during the investigation, that row is also ABSENT from the
table, so the switch had never been exercised either. There was no runtime way to stop
replying from standby without a code deploy.

Why this test is not redundant with "the tests still pass"
----------------------------------------------------------
The two functions were **not equivalent**, in three measured ways:

    | | deleted (live)                    | config-driven (dead)                  |
    |-|-----------------------------------|---------------------------------------|
    | types    | + `nfm_reply`            | no `nfm_reply`                        |
    | keywords | `_STANDBY_TEXT_TRIGGERS` | `_DETERMINISTIC_KEYWORDS` (+ `help`)  |
    | contains | none                     | `_DETERMINISTIC_CONTAINS` (substring) |

So deleting the shadow and keeping the survivor's original defaults would have been a real
behaviour change: flow and address submissions (`nfm_reply`) would have stopped being
claimed, and every free-form message containing `pay`, `track`, `faq` or `help` would have
started being claimed. The survivor's defaults were changed to reproduce the deleted
function instead, and this is the proof.

**The expectations below are retyped from the deleted function's semantics**, not
generated from the new code. A table generated from the implementation under test proves
only that it agrees with itself. The deleted function was:

    t = (message or {}).get('type', '')
    if t in ('interactive', 'order', 'button', 'nfm_reply'):      -> True
    if t == 'text':
        txt = body.strip().lower()
        if not txt:                                               -> False
        if txt.startswith('/'):                                   -> True
        return txt in _STANDBY_TEXT_TRIGGERS or
               strip_decorative_edges(txt) in _STANDBY_TEXT_TRIGGERS
    return False                                                  # every other type
"""
import ast
import importlib.util
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_INBOUND_DIR = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                            'inbound-whatsapp-handler')
HANDLER_PATH = os.path.join(_INBOUND_DIR, 'handler.py')


@pytest.fixture(scope='module')
def wa():
    """The inbound handler, loaded by explicit path under a unique module name.

    Same reason as tests/test_own_prefill_triggers_menu.py: every Lambda entry point in
    this repo is named `handler.py`, so a plain `import handler` resolves to whichever one
    is first on the path.
    """
    for path in (os.path.join(_ROOT, 'amplify', 'functions', 'shared'),
                 _INBOUND_DIR,
                 os.path.join(_INBOUND_DIR, 'modules')):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location('inbound_wa_equiv', HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wa_equiv'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_config_row(wa, monkeypatch):
    """Run against the BUILT-IN DEFAULTS, with no config row and no cache.

    `ai_hybrid_routing` is absent from SystemConfigTable (measured 2026-10-06), so the
    defaults are what production actually uses. The 60-second cache is reset per test or
    the first test's result would be reused by every other.
    """
    monkeypatch.setitem(wa._routing_cache, 'v', None)
    monkeypatch.setitem(wa._routing_cache, 't', 0.0)
    monkeypatch.setattr(wa, 'dynamodb', _NoTable())
    yield
    wa._routing_cache['v'] = None
    wa._routing_cache['t'] = 0.0


class _NoTable:
    """A DynamoDB stand-in whose get_item raises, which is how `_get_routing_config`
    reaches its built-in defaults. Raising rather than returning empty also proves the
    loader's `except` arm is what production is relying on today."""

    def Table(self, _name):
        return self

    def get_item(self, **_kwargs):
        raise RuntimeError('no config row')


def _text(body):
    return {'type': 'text', 'text': {'body': body}}


#: Retyped from the deleted function. (message, expected).
EXPECTATIONS = [
    # ── the four accepted types, true regardless of content ──
    ({'type': 'interactive'}, True),
    ({'type': 'interactive', 'interactive': {'type': 'list_reply'}}, True),
    ({'type': 'interactive', 'interactive': {'type': 'button_reply'}}, True),
    ({'type': 'interactive', 'interactive': {'type': 'nfm_reply'}}, True),
    ({'type': 'order'}, True),
    ({'type': 'button'}, True),
    # nfm_reply as a top-level type is the one the UNCHANGED config defaults would have
    # dropped. Flow and India address submissions are what this covers.
    ({'type': 'nfm_reply'}, True),

    # ── slash commands: ANY body starting with '/' ──
    (_text('/menu'), True),
    (_text('/pay'), True),
    (_text('/unknown'), True),
    (_text('/imagine a cat'), True),
    (_text('/'), True),

    # ── every member of _STANDBY_TEXT_TRIGGERS, exact match ──
    (_text('hi'), True),
    (_text('hello'), True),
    (_text('hey'), True),
    (_text('menu'), True),
    (_text('main menu'), True),
    (_text('show menu'), True),
    (_text('start'), True),
    (_text('get started'), True),
    (_text('browse menu'), True),
    (_text('need help!'), True),
    (_text('subscribe'), True),
    (_text('pay'), True),
    (_text('catalog'), True),
    (_text('view catalog'), True),
    (_text('submit request'), True),
    (_text('track request'), True),
    (_text('track'), True),
    (_text('amend request'), True),
    (_text('appointment'), True),
    (_text('rx slot'), True),
    (_text('drop docs'), True),
    (_text('enterprise'), True),
    (_text('leave review'), True),
    (_text('faq'), True),
    (_text('get help'), True),
    (_text('hi \U0001f44b'), True),

    # ── case and surrounding whitespace are normalised ──
    (_text('MENU'), True),
    (_text('  Main Menu  '), True),
    (_text('Get Help'), True),

    # ── decoration fallback ──
    (_text('hi \U0001f44b\U0001f3fd'), True),       # + skin-tone modifier
    (_text('menu \U0001f64f'), True),
    (_text('\u2753 faq'), True),

    # ── empty text is NOT a trigger (and must not be coerced to a greeting) ──
    (_text(''), False),
    (_text('   '), False),
    (_text('\U0001f44b'), False),                   # pure decoration strips to ''

    # ── free-form text: left to the AI ──
    (_text('what are your hours'), False),
    (_text('i need a payment plan'), False),
    (_text('track my shipment please'), False),
    (_text('help'), False),
    (_text('can you send me an invoice'), False),
    (_text('tell me about your catalogue options'), False),

    # ── other message types ──
    ({'type': 'reaction'}, False),
    ({'type': 'request_welcome'}, False),
    ({'type': 'image'}, False),
    ({'type': 'audio'}, False),
    ({'type': 'document'}, False),
    ({'type': 'location'}, False),
    ({'type': 'system'}, False),
    ({'type': 'unsupported'}, False),
    ({}, False),
    (None, False),
]

#: The three cases that prove the default change in `_get_routing_config` actually landed.
#: Each would be WRONGLY True under the survivor's ORIGINAL defaults:
#:   'i need a payment plan'      contains 'pay'   -> _DETERMINISTIC_CONTAINS
#:   'track my shipment please'   contains 'track' -> _DETERMINISTIC_CONTAINS
#:   'help'                       exact            -> _DETERMINISTIC_KEYWORDS
WOULD_HAVE_REGRESSED = [
    _text('i need a payment plan'),
    _text('track my shipment please'),
    _text('help'),
]


class TestThereIsOnlyOneDefinitionNow:
    def test_exactly_one_def_in_the_source(self):
        """An AST walk, not a text search: the comments explaining the deletion
        necessarily contain the function's name, so grep would pass on prose alone."""
        with open(HANDLER_PATH, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        definitions = [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == '_is_deterministic_trigger']
        assert len(definitions) == 1, (
            f'{len(definitions)} definitions of _is_deterministic_trigger; the shadowing '
            f'copy is what made the ai_hybrid_routing kill switch unreachable')

    def test_the_surviving_one_reads_the_config(self):
        """It has to be the config-driven one that survived, or the kill switch is still
        unreachable and this change achieved nothing."""
        with open(HANDLER_PATH, encoding='utf-8') as fh:
            source = fh.read()
        index = source.index('def _is_deterministic_trigger')
        body = source[index:index + 2000]
        assert '_get_routing_config()' in body
        assert "cfg.get('enabled'" in body


class TestDecisionsAreIdentical:
    @pytest.mark.parametrize('message,expected', EXPECTATIONS)
    def test_retyped_expectation(self, wa, message, expected):
        assert wa._is_deterministic_trigger(message) is expected

    @pytest.mark.parametrize('message', WOULD_HAVE_REGRESSED)
    def test_substring_and_help_matching_stayed_off(self, wa, message):
        """These three are the load-bearing cases. Each would be True under the
        config-driven function's ORIGINAL defaults, so each one failing means the default
        change in `_get_routing_config` was dropped and free-form questions are being
        claimed from the Meta AI."""
        assert wa._is_deterministic_trigger(message) is False

    def test_nfm_reply_is_still_claimed(self, wa):
        """The other direction: `nfm_reply` was absent from the config-driven defaults,
        so this is what proves flow and address submissions did not stop being handled."""
        assert wa._is_deterministic_trigger({'type': 'nfm_reply'}) is True

    def test_the_widening_sets_still_exist_as_an_opt_in(self, wa):
        """`_DETERMINISTIC_KEYWORDS` / `_DETERMINISTIC_CONTAINS` are no longer the
        defaults but are kept in the module, so a seeded config row can opt into the
        broader matching deliberately rather than by accident."""
        assert 'help' in wa._DETERMINISTIC_KEYWORDS
        assert 'pay' in wa._DETERMINISTIC_CONTAINS


class TestTheKillSwitchNowWorks:
    def test_enabled_false_claims_nothing_at_all(self, wa, monkeypatch):
        """The whole point of keeping the config-driven definition: `enabled: false` is a
        runtime stop with no deploy. With the shadow in place this was unreachable."""
        monkeypatch.setattr(wa, '_get_routing_config', lambda: {'enabled': False})
        for message, _expected in EXPECTATIONS:
            assert wa._is_deterministic_trigger(message) is False

    def test_a_row_can_widen_the_types(self, wa, monkeypatch):
        monkeypatch.setattr(wa, '_get_routing_config', lambda: {
            'enabled': True, 'types': ['image'], 'keywords': [], 'contains': [],
            'commandPrefix': '/'})
        assert wa._is_deterministic_trigger({'type': 'image'}) is True
        assert wa._is_deterministic_trigger({'type': 'order'}) is False

    def test_a_row_can_re_enable_substring_matching(self, wa, monkeypatch):
        monkeypatch.setattr(wa, '_get_routing_config', lambda: {
            'enabled': True, 'types': [], 'keywords': [], 'contains': ['pay'],
            'commandPrefix': '/'})
        assert wa._is_deterministic_trigger(_text('i need a payment plan')) is True


class TestTheDefaultsMatchTheSeedScript:
    """The seeded row must be a no-op on the day it lands, or seeding is a behaviour
    change dressed as configuration."""

    def test_seed_script_values_equal_the_code_defaults(self, wa):
        sys.path.insert(0, os.path.join(_ROOT, 'scripts'))
        spec = importlib.util.spec_from_file_location(
            'seed_ai_hybrid_routing',
            os.path.join(_ROOT, 'scripts', 'seed_ai_hybrid_routing.py'))
        seed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seed)

        defaults = wa._get_routing_config()
        for key in ('enabled', 'commandPrefix'):
            assert seed.CONFIG_VALUE[key] == defaults[key], key
        for key in ('keywords', 'contains', 'types'):
            assert sorted(seed.CONFIG_VALUE[key]) == sorted(defaults[key]), key
