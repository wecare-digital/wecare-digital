"""Our own QR / widget prefill messages must reach the menu placeholder.

The bug this pins, found 2026-09-26: both business numbers carry a Cloud API QR deep
link with a prefilled first message, and `SupportWidget.tsx`,
`public/wecare-wa-widget.js` and `src/pages/forms/customerservice.tsx` all send customers
through them. Measured live against Meta:

    WABA1  1016149501586345  QR APDM5HUWH26SG1  prefilled "Get Help"
    WABA2  1055232054343117  QR DPESCFW7U4FXO1  prefilled "Hi 👋"

Neither matched ANY keyword set in the inbound handler. It looked like it worked
because a first-ever contact still gets a reply from the brand-new-contact path.
A RETURNING visitor tapping the same widget fell through every keyword set to the
unmatched-text path, which deliberately sends nothing — so the second visit was
silence.

Every menu was deleted on 2026-10-02, so what these keywords now reach is the
plain-text placeholder rather than an interactive list (see
tests/test_menus_are_deleted.py). That changes the destination, not the bug: a
prefill that matches no set is still silence.

Both halves are tested here, and the second is the one that matters:

* the two literals are present in the sets (the narrow fix);
* `strip_decorative_edges` removes the *reason* both failed — every keyword set is
  exact-match, so "Hi 👋🏽", "menu 🙏" and the next prefill anyone sets on Meta would
  have failed identically.

`HI_KEYWORDS` and `BUTTON_MENU_TRIGGERS` are function-local, so they are asserted
against the source text — the same approach as `src/test/PublicWidgets.test.tsx`,
which reads the live widget JS rather than trusting a copy of the URL.
"""
import importlib.util
import os
import re
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_INBOUND_DIR = os.path.join(_ROOT, 'amplify', 'functions', 'messaging',
                            'inbound-whatsapp-handler')
HANDLER_PATH = os.path.join(_INBOUND_DIR, 'handler.py')

# Live QR prefills, read from Meta's message_qrdls on 2026-09-26, lowercased the way
# the handler lowercases inbound text.
OWN_PREFILLS = ['get help', 'hi \U0001f44b']


@pytest.fixture(scope='module')
def handler_source():
    with open(HANDLER_PATH, encoding='utf-8') as fh:
        return fh.read()


@pytest.fixture(scope='module')
def wa():
    """The inbound handler, loaded under a UNIQUE module name.

    A plain `import handler` is unsafe in this suite: every Lambda entry point in this
    repo is named `handler.py`, several test files insert their own handler directory at
    `sys.path[0]`, and `conftest.py`'s autouse fixture deletes `sys.modules['handler']`
    between tests. So `import handler` resolves to whichever handler happens to be first
    on the path — running this file alongside `test_business_api.py` picked up the
    business-API handler and failed with AttributeError. Loading by explicit file path
    under a distinct name is immune to both the ordering and the cache clearing.
    """
    for path in (os.path.join(_ROOT, 'amplify', 'functions', 'shared'),
                 _INBOUND_DIR,
                 os.path.join(_INBOUND_DIR, 'modules')):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location('inbound_wa_handler', HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wa_handler'] = module
    spec.loader.exec_module(module)
    return module


def _literal_set_members(source: str, name: str) -> set:
    """Pull the string literals out of a `NAME = { ... }` assignment in the source.

    Needed because HI_KEYWORDS and BUTTON_MENU_TRIGGERS are local to the message
    handler and cannot be imported.
    """
    match = re.search(name + r'\s*=\s*\{(.*?)\}', source, re.DOTALL)
    assert match, f'{name} not found in handler source'
    return set(re.findall(r"'([^']*)'", match.group(1)))


class TestOwnPrefillsReachThePlaceholder:
    @pytest.mark.parametrize('prefill', OWN_PREFILLS)
    def test_hi_keywords_contains_prefill(self, handler_source, prefill):
        """The greeting set is what actually answers a prefill."""
        assert prefill in _literal_set_members(handler_source, 'HI_KEYWORDS')

    def test_button_triggers_contains_get_help(self, handler_source):
        """A prefill can arrive as msg_type='button' rather than text."""
        assert 'get help' in _literal_set_members(handler_source, 'BUTTON_MENU_TRIGGERS')

    @pytest.mark.parametrize('prefill', OWN_PREFILLS)
    def test_our_deterministic_flow_claims_the_prefill_on_standby(self, wa, prefill):
        """A prefill arriving as a standby copy must be claimed by OUR flow.

        Renamed 2026-10-06. It was `test_bot_takes_control_from_the_ai`, and that name
        carried a premise Meta has since retired: that sending a reply is how an observing
        app takes thread control. Under an active Conversation Routing configuration only
        the designated escalation partner can take a thread that way, and ownership is
        claimed by RECEIVING rather than by replying.

        The assertion is unchanged and still right, because membership in this set is a
        narrower claim than the old name made: it decides whether our deterministic flow
        HANDLES the message. Whether a reply is then actually sent is
        `STANDBY_REPLY_ENABLED`'s decision — see tests/test_standby_produces_no_sends.py.
        """
        assert prefill in wa._STANDBY_TEXT_TRIGGERS

    def test_deterministic_keywords_contains_get_help(self, wa):
        assert 'get help' in wa._DETERMINISTIC_KEYWORDS


class TestNoEarlierSetSwallowsThem:
    """Precedence. Every set below is evaluated BEFORE HI_KEYWORDS, and each one
    returns, so a match there would mean the greeting is never answered."""

    @pytest.mark.parametrize('prefill', OWN_PREFILLS)
    def test_not_claimed_by_an_earlier_exact_match_set(self, handler_source, prefill):
        for name in ('MY_ID_KEYWORDS', 'PAY_KEYWORDS'):
            assert prefill not in _literal_set_members(handler_source, name), \
                f'{name} is evaluated before HI_KEYWORDS and would swallow {prefill!r}'

    @pytest.mark.parametrize('prefill', OWN_PREFILLS)
    def test_not_claimed_by_a_flow_trigger(self, wa, prefill):
        """DEFAULT_FLOW_TRIGGERS is evaluated before the pay and greeting sets."""
        for key, trigger in wa.DEFAULT_FLOW_TRIGGERS.items():
            keywords = [k.lower() for k in trigger.get('keywords', [])]
            assert prefill not in keywords, \
                f'flow {key} claims {prefill!r} before the greeting set runs'

    @pytest.mark.parametrize('prefill', OWN_PREFILLS)
    def test_not_caught_by_pay_fuzzy_substrings(self, handler_source, prefill):
        """PAY_FUZZY is substring-matched, so it can claim a string it does not list."""
        match = re.search(r'PAY_FUZZY\s*=\s*\((.*?)\)', handler_source, re.DOTALL)
        assert match, 'PAY_FUZZY not found'
        for fuzzy in re.findall(r"'([^']*)'", match.group(1)):
            assert fuzzy not in prefill, \
                f'PAY_FUZZY {fuzzy!r} is a substring of {prefill!r}'


class TestDecorativeEdgeNormalisation:
    """The literals above fix two strings. This fixes the *reason* they failed."""

    @pytest.mark.parametrize('raw,expected', [
        ('hi \U0001f44b', 'hi'),                                   # WABA2 QR prefill
        ('hi \U0001f44b\U0001f3fd', 'hi'),                         # + skin-tone modifier
        ('menu \U0001f64f', 'menu'),
        ('\u2753 faqs', 'faqs'),                                   # menu row echoed back
        ('\U0001f680 customerservice', 'customerservice'),
        ('\u270f\ufe0f amend request', 'amend request'),            # VS16
        ('\U0001f1ee\U0001f1f3 bharat stack', 'bharat stack'),      # regional indicators
        ('\u2b50 leave review', 'leave review'),
    ])
    def test_decoration_is_trimmed(self, wa, raw, expected):
        assert wa.strip_decorative_edges(raw) == expected

    @pytest.mark.parametrize('raw', [
        '/menu',                     # ASCII punctuation must survive
        '/pay',
        'need help' + chr(33),       # trailing '!' is not decoration
        'get help',
        'main menu',
    ])
    def test_plain_input_is_untouched(self, wa, raw):
        assert wa.strip_decorative_edges(raw) == raw

    @pytest.mark.parametrize('hindi', [
        '\u092d\u0941\u0917\u0924\u093e\u0928',                     # भुगतान
        '\u092c\u093e\u0915\u0940',                                 # बाकी — ends in a matra
        '\u092a\u0947\u092e\u0947\u0902\u091f',                     # पेमेंट
        '\u0915\u093f\u0924\u0928\u093e \u092c\u093e\u0915\u0940 \u0939\u0948',
    ])
    def test_devanagari_survives_intact(self, wa, hindi):
        """Why this uses explicit codepoint ranges instead of Unicode categories.

        A category-based strip (`So`/`Mn`) would also eat Devanagari combining marks off
        the edges of these live PAY_KEYWORDS entries. Truncating a customer's Hindi
        payment request would be a worse bug than the one being fixed.
        """
        assert wa.strip_decorative_edges(hindi) == hindi

    def test_pure_decoration_becomes_empty_and_matches_nothing(self, wa):
        """A bare emoji must NOT be coerced into a greeting by accident."""
        assert wa.strip_decorative_edges('\U0001f44b') == ''
        assert '' not in wa._STANDBY_TEXT_TRIGGERS

    def test_menu_sets_use_the_fallback(self, handler_source):
        """The helper is worthless unless the match sites actually consult it."""
        for guard in (
            'content_lower in HI_KEYWORDS or _content_plain in HI_KEYWORDS',
            'content_lower in CUSTOMERSERVICE_KEYWORDS or _content_plain in CUSTOMERSERVICE_KEYWORDS',
            'content_lower in COMMANDS_KEYWORDS or _content_plain in COMMANDS_KEYWORDS',
            'strip_decorative_edges(button_text_lower) in BUTTON_MENU_TRIGGERS',
        ):
            assert guard in handler_source, f'missing decoration fallback: {guard}'

    def test_money_and_record_creating_sets_do_not_use_the_fallback(self, handler_source):
        """Scope guard. A false positive on the placeholder is harmless; one that
        pulls an invoice, opens a paid flow or discloses subscriber details is not."""
        for forbidden in ('_content_plain in PAY_KEYWORDS',
                          '_content_plain in MY_ID_KEYWORDS'):
            assert forbidden not in handler_source, \
                f'decoration fallback must not be applied here: {forbidden}'

    def test_the_deterministic_gate_normalises_decoration_too(self, wa, monkeypatch):
        """Decoration must not stop our flow recognising a prefill.

        Rewritten 2026-10-06. This was `test_standby_gate_normalises_too`, and its
        docstring read: *"A standby 'Hi 👋' must be taken by our own flow, not handed to
        the Meta AI."* That asserted the **opposite** of Meta's current rule. Under an
        active routing configuration a Service message from a non-owner is rejected, so
        "taken by our own flow" is precisely what must NOT follow from recognising a
        standby message — recognising it and replying to it are two separate decisions.

        What this was really testing is kept: `'Hi 👋'` must still normalise through
        `strip_decorative_edges` and still be recognised as a deterministic trigger, so
        the live WABA2 QR prefill matches. Whether a reply then goes out from standby is
        `STANDBY_REPLY_ENABLED`'s decision, which
        tests/test_standby_produces_no_sends.py covers.

        The config read is stubbed so this measures the decision function rather than
        whatever is currently in the `ai_hybrid_routing` row.
        """
        monkeypatch.setitem(wa._routing_cache, 'v', None)
        monkeypatch.setitem(wa._routing_cache, 't', 0.0)
        monkeypatch.setattr(wa, '_get_routing_config', lambda: {
            'enabled': True,
            'types': ['button', 'interactive', 'order', 'nfm_reply'],
            'keywords': sorted(wa._STANDBY_TEXT_TRIGGERS),
            'contains': [],
            'commandPrefix': '/',
        })
        assert wa._is_deterministic_trigger(
            {'type': 'text', 'text': {'body': 'Hi \U0001f44b'}}) is True
