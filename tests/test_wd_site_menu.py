"""The WECARE.DIGITAL site menu, back on WhatsApp as interactive lists.

Owner decision, 2026-10-03: rebuild the menu to mirror the public site mega-menu in
`src/components/Header.tsx`, and **exclude Shop entirely**. The structure, the row
ids, the labels and the paths in this file are retyped from the owner's approved
brief, deliberately NOT imported from the handler — a test that reads its
expectations out of the code under test proves only that the code is self-consistent.

This file replaces `tests/test_menus_are_deleted.py`, which pinned the 2026-10-02
deletion. Four of that file's assertions are false by owner decision now that a menu
is back, but everything in it that was never about a menu is carried forward
unchanged and sits in the ported classes at the bottom:

* `TestNothingBecameUnreachable` — the deletion's central safety claim, still true:
  every destination the old menus offered stays reachable by a TYPED keyword, and the
  Help reply keeps naming them.
* `TestTheRivalMenuIsGone` — `ai-generate-response` must still define no menu of its
  own.
* `TestOnlyOneMenuExists` — the old menu dicts, their getters, `_send_interactive_list`,
  `_handle_list_reply`, `_handle_ivr_response`, `_send_reply_buttons` and
  `_send_followup_buttons` must all still be absent, so `WD_LISTS` is provably the
  only menu in the handler.

No live WhatsApp message is sent by anything here: `_send_direct_api_message` and
`_send_ai_auto_reply` are monkeypatched in every behavioural test.

The handler is loaded by explicit file path under a unique module name. Every Lambda
entry point in this repo is called `handler.py` and `conftest.py` clears
`sys.modules['handler']` between tests, so a plain `import handler` resolves to
whichever one happens to be first on `sys.path`.
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
HEADER_TSX = os.path.join(_ROOT, 'src', 'components', 'Header.tsx')

# ── The approved structure, retyped from the brief ───────────────────────────
MAIN_ROW_IDS = ['wd_home', 'wd_products', 'wd_request', 'wd_work', 'wd_legal']

SUBMENU_ROW_IDS = {
    'wd_products': ['wd_products_1', 'wd_products_2', 'wd_back'],
    'wd_products_1': ['wd_grahak_os', 'wd_vayulok', 'wd_bharat_rx', 'wd_elsewhere',
                      'wd_expo_week', 'wd_dastavez', 'wd_back'],
    'wd_products_2': ['wd_clear_closure', 'wd_ritual_guru', 'wd_anew', 'wd_hunar',
                      'wd_niji_setu', 'wd_back'],
    'wd_request': ['wd_orders', 'wd_submit', 'wd_amend', 'wd_drop_docs', 'wd_vault',
                   'wd_shipments', 'wd_review', 'wd_back'],
    'wd_work': ['wd_refer', 'wd_contact', 'wd_perks', 'wd_back'],
    'wd_legal': ['wd_terms', 'wd_privacy', 'wd_back'],
}

# Trailing slashes are LOAD-BEARING. The site runs with trailingSlash on, so dropping
# one turns a customer-facing link into a redirect at best.
LEAF_PATHS = {
    'wd_home': '/',
    'wd_grahak_os': '/grahak-os/',
    'wd_vayulok': '/vayulok/',
    'wd_bharat_rx': '/bharat-rx/',
    'wd_elsewhere': '/elsewhere/',
    'wd_expo_week': '/expo-week/',
    'wd_dastavez': '/dastavez/',
    'wd_clear_closure': '/clear-closure/',
    'wd_ritual_guru': '/ritual-guru/',
    'wd_anew': '/anew/',
    'wd_hunar': '/hunar/',
    'wd_niji_setu': '/niji-setu/',
    'wd_orders': '/orders/',
    'wd_submit': '/submit-request/',
    'wd_amend': '/request-amendment/',
    'wd_drop_docs': '/drop-docs/',
    'wd_vault': '/vault/',
    'wd_shipments': '/shipments/',
    'wd_review': '/leave-review/',
    'wd_refer': '/refer-and-earn/',
    'wd_contact': '/contact/',
    'wd_perks': '/perks/',
    'wd_terms': '/terms/',
    'wd_privacy': '/privacy/',
}

MAIN_HEADER = 'WECARE.DIGITAL'
MAIN_BODY = 'Everyday AI, built for Bharat. What do you need?'
MAIN_BUTTON = 'Open Menu'

# Absent, and must stay absent — `WD_LISTS` has to be the only menu in the handler.
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
    '_handle_ivr_response',
    '_handle_list_reply',
    '_send_reply_buttons',
    '_send_followup_buttons',
]

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
    spec = importlib.util.spec_from_file_location('inbound_wd_menu', HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules['inbound_wd_menu'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sent(wa, monkeypatch):
    """Capture every send instead of making one. NO live WhatsApp message.

    Both outbound routes are stubbed: `_send_direct_api_message` (the lists, which go
    straight to the Graph API) and `_send_ai_auto_reply` (the leaf text and the
    degraded placeholder, which go via outbound-whatsapp).
    """
    calls = {'graph': [], 'text': []}

    def fake_graph(to_number, message_payload, meta_phone_id=None):
        calls['graph'].append({'to': to_number, 'payload': message_payload,
                               'metaPhoneId': meta_phone_id})
        return {'success': True, 'messageId': 'wamid.TEST'}

    def fake_text(contact_id, content, phone_number_id, request_id):
        calls['text'].append({'contactId': contact_id, 'content': content})

    monkeypatch.setattr(wa, '_send_direct_api_message', fake_graph)
    monkeypatch.setattr(wa, '_send_ai_auto_reply', fake_text)
    # The inbox mirror writes to DynamoDB; it is a dual-write and never the point here.
    monkeypatch.setattr(wa, 'put_message', lambda **kw: 'msg-test')
    return calls


def _all_rows(wa):
    for list_key, spec in wa.WD_LISTS.items():
        for row in spec['rows']:
            yield list_key, row


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name} not found')


def _called_names(node):
    out = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            if isinstance(inner.func, ast.Name):
                out.add(inner.func.id)
            elif isinstance(inner.func, ast.Attribute):
                out.add(inner.func.attr)
    return out


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


def _trigger_branch(source: str, name: str) -> str:
    """The source from a trigger set's ASSIGNMENT to the first `return` after it.

    That slice is the whole branch: the set literal, the guard, the logging and the
    send. Anchored on the assignment rather than any mention of the name, because
    comments elsewhere in the file reference HI_KEYWORDS by name.
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


def _interactive_dispatch(handler_source: str) -> str:
    start = handler_source.index("if msg_type == 'interactive':")
    end = handler_source.index("elif interactive_type == 'nfm_reply':", start)
    return handler_source[start:end]


def _reply_branch_node(tree, reply_type: str):
    """The `If` node for `interactive_type == '<reply_type>'`.

    Walked as AST rather than sliced as text on purpose: the comments that explain
    the routing rule necessarily contain words like "raises", so a text search for
    `raise` reports a hit in prose. Same reasoning as the payment-vocabulary gate in
    tests/test_payment_vocabulary_at_decision_points.py.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == 'interactive_type'
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == reply_type):
            return node
    raise AssertionError(f"no interactive_type == '{reply_type}' branch found")


class TestTheStructureIsExactlyWhatWasApproved:
    def test_there_are_seven_lists_and_no_others(self, wa):
        assert set(wa.WD_LISTS) == {'wd_main'} | set(SUBMENU_ROW_IDS)

    def test_the_main_menu_rows_are_the_five_approved_ones_in_order(self, wa):
        assert [r['id'] for r in wa.WD_LISTS['wd_main']['rows']] == MAIN_ROW_IDS

    def test_the_main_menu_copy_is_exact(self, wa):
        """Customer-facing. Asserted character for character."""
        main = wa.WD_LISTS['wd_main']
        assert main['header'] == MAIN_HEADER
        assert main['body'] == MAIN_BODY
        assert main['button'] == MAIN_BUTTON

    @pytest.mark.parametrize('list_key', sorted(SUBMENU_ROW_IDS))
    def test_each_submenu_has_exactly_the_approved_rows_in_order(self, wa, list_key):
        assert [r['id'] for r in wa.WD_LISTS[list_key]['rows']] == SUBMENU_ROW_IDS[list_key]

    @pytest.mark.parametrize('list_key', sorted(SUBMENU_ROW_IDS))
    def test_every_submenu_ends_with_back_to_menu(self, wa, list_key):
        """Nobody is stranded one level down."""
        assert wa.WD_LISTS[list_key]['rows'][-1]['id'] == 'wd_back'

    def test_only_the_main_menu_carries_a_header(self, wa):
        assert wa.WD_LISTS['wd_main'].get('header')
        for list_key in SUBMENU_ROW_IDS:
            assert not wa.WD_LISTS[list_key].get('header'), \
                f'{list_key} grew a header the brief does not specify'

    def test_the_main_menu_row_titles_and_descriptions_are_exact(self, wa):
        expected = [
            ('\U0001f3e0 About / Home', 'Who we are and what we do'),
            ('\U0001f4e6 Products', 'Explore our products'),
            ('\U0001f9fe Request', 'Orders, requests, documents'),
            ('\U0001f91d Work with us', 'Refer, contact, perks'),
            ('\U0001f4c4 Legal & Extras', 'Terms, privacy, perks'),
        ]
        actual = [(r['title'], r['description']) for r in wa.WD_LISTS['wd_main']['rows']]
        assert actual == expected

    def test_the_products_chooser_copy_is_exact(self, wa):
        chooser = wa.WD_LISTS['wd_products']
        assert chooser['body'] == 'Products — choose a set'
        assert [(r['title'], r.get('description')) for r in chooser['rows']] == [
            ('Products (1 of 2)', 'Grahak OS, VayuLok, Bharat Rx…'),
            ('Products (2 of 2)', 'Clear Closure, Anew, Hunar…'),
            ('\u2b05\ufe0f Back to menu', None),
        ]


class TestWhatsAppLimits:
    """Meta rejects an over-length list with a 400, and a 400 is a silent menu.

    This is the test that makes a future label edit safe.
    """

    def test_every_list_fits_in_ten_rows(self, wa):
        for list_key, spec in wa.WD_LISTS.items():
            assert len(spec['rows']) <= 10, f'{list_key} has {len(spec["rows"])} rows'

    def test_every_row_title_fits_in_twenty_four_chars(self, wa):
        for list_key, row in _all_rows(wa):
            assert len(row['title']) <= 24, \
                f'{list_key}/{row["id"]} title is {len(row["title"])} chars: {row["title"]!r}'

    def test_every_description_fits_in_seventy_two_chars(self, wa):
        for list_key, row in _all_rows(wa):
            desc = row.get('description')
            if desc is not None:
                assert len(desc) <= 72, f'{list_key}/{row["id"]} description is {len(desc)}'

    def test_every_button_fits_in_twenty_chars(self, wa):
        for list_key, spec in wa.WD_LISTS.items():
            assert 1 <= len(spec['button']) <= 20, f'{list_key} button {spec["button"]!r}'

    def test_every_header_and_body_fit(self, wa):
        for list_key, spec in wa.WD_LISTS.items():
            assert len(spec.get('header', '')) <= 60, f'{list_key} header too long'
            assert 1 <= len(spec['body']) <= 1024, f'{list_key} body length {len(spec["body"])}'

    def test_every_row_id_is_within_metas_two_hundred_char_limit(self, wa):
        for list_key, row in _all_rows(wa):
            assert 1 <= len(row['id']) <= 200


class TestEveryLeafResolvesToTheSitePath:
    def test_there_are_exactly_the_twenty_four_approved_leaves(self, wa):
        assert set(wa.WD_LEAF_LINKS) == set(LEAF_PATHS)

    @pytest.mark.parametrize('leaf_id,path', sorted(LEAF_PATHS.items()))
    def test_the_path_is_exact_including_the_trailing_slash(self, wa, leaf_id, path):
        assert wa.WD_LEAF_LINKS[leaf_id][1] == path

    @pytest.mark.parametrize('leaf_id', sorted(LEAF_PATHS))
    def test_the_path_starts_and_ends_with_a_slash(self, wa, leaf_id):
        assert re.fullmatch(r'/([a-z0-9-]+/)?', wa.WD_LEAF_LINKS[leaf_id][1])

    def test_the_base_url_has_no_trailing_slash_so_paths_do_not_double_up(self, wa):
        assert wa.WD_SITE_BASE == 'https://wecare.digital'

    def test_every_leaf_has_a_non_empty_display_name(self, wa):
        for leaf_id, (name, _path) in wa.WD_LEAF_LINKS.items():
            assert name and name.strip() == name, f'{leaf_id} name {name!r}'


class TestEveryRowIsReachableAndEveryLeafIsListed:
    """The closure property. This is what catches an orphaned page or a dead row."""

    def test_every_row_id_goes_somewhere(self, wa):
        known = set(wa.WD_LISTS) | set(wa.WD_LEAF_LINKS) | {'wd_back'}
        for list_key, row in _all_rows(wa):
            assert row['id'] in known, f'{list_key}/{row["id"]} routes nowhere'

    def test_every_leaf_appears_as_a_row_somewhere(self, wa):
        listed = {row['id'] for _k, row in _all_rows(wa)}
        for leaf_id in wa.WD_LEAF_LINKS:
            assert leaf_id in listed, f'{leaf_id} is a dead end - no row opens it'

    def test_every_submenu_opener_is_reachable_from_the_main_menu(self, wa):
        """Walk the graph from wd_main; every list must be found."""
        seen, queue = set(), ['wd_main']
        while queue:
            key = queue.pop()
            if key in seen:
                continue
            seen.add(key)
            for row in wa.WD_LISTS[key]['rows']:
                if row['id'] in wa.WD_LISTS:
                    queue.append(row['id'])
        assert seen == set(wa.WD_LISTS), f'unreachable lists: {set(wa.WD_LISTS) - seen}'


class TestNothingGoesSilent:
    """A tap that produces no reply is the one failure this menu must not have."""

    def test_the_list_reply_branch_routes_through_the_router(self, handler_source):
        branch = _interactive_dispatch(handler_source)
        branch = branch.split("elif interactive_type == 'list_reply':", 1)[1]
        assert '_route_wd_list_reply' in branch

    def test_the_button_reply_branch_opens_the_main_menu(self, handler_source):
        branch = _interactive_dispatch(handler_source)
        branch = branch.split("elif interactive_type == 'button_reply':", 1)[1]
        branch = branch.split('elif interactive_type ==', 1)[0]
        assert '_send_wd_main_menu' in branch, \
            'a tapped button sends nothing - that is the silence this forbids'

    @pytest.mark.parametrize('event', ['button_reply_received', 'list_reply_received'])
    def test_the_correlation_log_line_survives(self, handler_source, event):
        """The only handle on a tapped id, and the reason a stale tap is traceable."""
        assert event in _interactive_dispatch(handler_source)

    def test_the_router_knows_all_three_destinations_and_a_fallback(self, handler_tree):
        router = _function(handler_tree, '_route_wd_list_reply')
        called = _called_names(router)
        for name in ('_send_wd_main_menu', '_send_wd_list', '_send_wd_leaf_link'):
            assert name in called, f'_route_wd_list_reply never calls {name}'

    @pytest.mark.parametrize('reply_type', ['button_reply', 'list_reply'])
    def test_the_dispatch_never_raises(self, handler_tree, reply_type):
        """An unknown id must fall back, not blow up the whole inbound message."""
        router = _function(handler_tree, '_route_wd_list_reply')
        for node in ast.walk(router):
            assert not isinstance(node, ast.Raise), 'the router raises on some path'
        branch = _reply_branch_node(handler_tree, reply_type)
        for node in branch.body:
            for inner in ast.walk(node):
                assert not isinstance(inner, ast.Raise), \
                    f'the {reply_type} branch raises on some path'

    def test_a_graph_failure_degrades_to_the_placeholder(self, handler_tree):
        """No token, or a Meta outage, still produces an answer."""
        main = _function(handler_tree, '_send_wd_main_menu')
        assert '_send_menu_placeholder' in _called_names(main)

    def test_the_placeholder_copy_is_still_byte_identical_to_the_calling_lambda(self, wa):
        """Pinned by tests/test_calling_menu_template_is_gone.py from the other side."""
        assert wa.MENU_PLACEHOLDER_TEXT == \
            "We're refreshing our menu - please type *menu* and we'll help you."


class TestTheRouterBehaviour:
    """The same guarantees as above, executed rather than read. Sends are mocked."""

    ARGS = ('wa918100640044', '918100640044', 'phone-1', 'req-test')

    def test_a_submenu_id_sends_that_list(self, wa, sent):
        assert wa._route_wd_list_reply('wd_products', *self.ARGS) == 'list'
        assert len(sent['graph']) == 1
        rows = sent['graph'][0]['payload']['interactive']['action']['sections'][0]['rows']
        assert [r['id'] for r in rows] == SUBMENU_ROW_IDS['wd_products']

    def test_wd_back_returns_the_main_menu(self, wa, sent):
        assert wa._route_wd_list_reply('wd_back', *self.ARGS) == 'back'
        rows = sent['graph'][0]['payload']['interactive']['action']['sections'][0]['rows']
        assert [r['id'] for r in rows] == MAIN_ROW_IDS

    @pytest.mark.parametrize('stale', ['menu_main', 'menu_customerservice_1', 'ivr_1',
                                       'lang_hi', '', 'wd_nope', 'WD_HOME'])
    def test_an_unknown_or_stale_id_falls_back_to_the_main_menu(self, wa, sent, stale):
        """Rows from the deleted menus are still sitting in customers' chat history."""
        assert wa._route_wd_list_reply(stale, *self.ARGS) == 'unknown'
        rows = sent['graph'][0]['payload']['interactive']['action']['sections'][0]['rows']
        assert [r['id'] for r in rows] == MAIN_ROW_IDS

    @pytest.mark.parametrize('stale', ['menu_main', '', None])
    def test_an_unknown_id_never_raises(self, wa, sent, stale):
        wa._route_wd_list_reply(stale, *self.ARGS)  # must not raise

    @pytest.mark.parametrize('leaf_id,path', sorted(LEAF_PATHS.items()))
    def test_a_leaf_replies_with_the_exact_link_text(self, wa, sent, leaf_id, path):
        assert wa._route_wd_list_reply(leaf_id, *self.ARGS) == 'leaf'
        assert not sent['graph'], 'a leaf must answer with text, not another list'
        assert len(sent['text']) == 1
        name = wa.WD_LEAF_LINKS[leaf_id][0]
        assert sent['text'][0]['content'] == (
            f"{name}\nOpen it here \U0001f449 https://wecare.digital{path}"
            "\n\nOr just tell me what you need and I'll help."
        )

    def test_the_sent_payload_is_a_meta_interactive_list(self, wa, sent):
        wa._send_wd_list('wd_main', *self.ARGS)
        payload = sent['graph'][0]['payload']
        assert payload['type'] == 'interactive'
        assert payload['interactive']['type'] == 'list'
        assert payload['interactive']['header'] == {'type': 'text', 'text': MAIN_HEADER}
        assert payload['interactive']['body']['text'] == MAIN_BODY
        assert payload['interactive']['action']['button'] == MAIN_BUTTON
        assert len(payload['interactive']['action']['sections']) == 1

    def test_a_failed_send_reports_failure_so_the_caller_can_fall_back(self, wa, monkeypatch):
        monkeypatch.setattr(wa, '_send_direct_api_message',
                            lambda *a, **k: {'error': True, 'status': 400})
        assert wa._send_wd_list('wd_main', *self.ARGS) is False

    def test_an_exception_in_the_send_is_swallowed_not_propagated(self, wa, monkeypatch):
        """A menu send must never break _process_message."""
        def boom(*a, **k):
            raise RuntimeError('graph down')
        monkeypatch.setattr(wa, '_send_direct_api_message', boom)
        assert wa._send_wd_list('wd_main', *self.ARGS) is False

    def test_an_unknown_list_key_is_a_failure_not_a_crash(self, wa, sent):
        assert wa._send_wd_list('wd_not_a_list', *self.ARGS) is False
        assert not sent['graph']

    def test_the_live_smoke_lockdown_applies_to_the_direct_send(self, wa, sent, monkeypatch):
        """The direct Graph send bypasses outbound-whatsapp's gate, so it re-applies it.

        With WA_LIVE_SMOKE_TEST on and a different QA recipient configured, the menu
        must NOT reach a customer.
        """
        monkeypatch.setenv('WA_LIVE_SMOKE_TEST', 'true')
        monkeypatch.setenv('WA_QA_RECIPIENT', '+918100640044')
        assert wa._send_wd_list('wd_main', 'wa919000000001', '919000000001',
                                'phone-1', 'req-test') is True
        assert not sent['graph'], 'the lockdown let a non-QA recipient through'

    def test_the_qa_recipient_still_receives_in_smoke_mode(self, wa, sent, monkeypatch):
        monkeypatch.setenv('WA_LIVE_SMOKE_TEST', 'true')
        monkeypatch.setenv('WA_QA_RECIPIENT', '+918100640044')
        assert wa._send_wd_list('wd_main', *self.ARGS) is True
        assert len(sent['graph']) == 1


class TestTheTriggerPathsOpenTheMenu:
    @pytest.mark.parametrize('name', TRIGGER_SETS)
    def test_the_trigger_set_survives(self, handler_source, name):
        """The sets stay and only what they DO changes: each is live on Meta as a QR
        prefill, an ice breaker or a slash command."""
        assert re.search(r'\s' + name + r'\s*=\s*\{', handler_source), \
            f'{name} was removed - its trigger words would stop being answered'

    @pytest.mark.parametrize('name', TRIGGER_SETS)
    def test_the_trigger_path_opens_the_main_menu(self, handler_source, name):
        branch = _trigger_branch(handler_source, name)
        assert '_send_wd_main_menu' in branch, \
            f'the {name} path no longer opens the menu'

    @pytest.mark.parametrize('word', ['hi', 'hello', 'menu', 'start', 'get started'])
    def test_the_briefs_trigger_words_reach_the_menu(self, handler_source, word):
        """Five of the brief's six words go straight to the menu."""
        hi = _nested_literal(handler_source, 'HI_KEYWORDS')
        buttons = _nested_literal(handler_source, 'BUTTON_MENU_TRIGGERS')
        assert word in hi or word in buttons

    def test_bare_help_is_answered_by_the_commands_reply_on_purpose(self, handler_source):
        """The brief lists `help` as a trigger word; it is answered, but by the
        long-established commands reply rather than the menu.

        `help` is contested by COMMANDS_KEYWORDS and FAQ_KEYWORDS and first match
        wins - see defect #6 in docs/whatsapp-experience-structure.md. Re-pointing it
        at the menu would change two established replies, so it is deliberately left
        alone and recorded here instead of silently diverging from the brief.
        """
        assert 'help' in _nested_literal(handler_source, 'COMMANDS_KEYWORDS')

    def test_the_welcome_paths_still_mark_welcome_sent(self, handler_source):
        """Without this write the menu re-sends on every message from a new contact."""
        assert handler_source.count('SET welcomeSent = :t, welcomeSentAt = :ts') >= 2


class TestShopIsExcluded:
    """Owner decisions, which now point in TWO directions and are pinned apart here.

    WHATSAPP: Shop is still NOT a menu row or leaf. The WhatsApp list is the owner's curated
    journey and Shop was deliberately kept off it; `test_typed_shop_still_answers` records that a
    customer who types `shop` is still answered with a CTA button rather than a menu entry.

    SITE NAV: Shop was WITHDRAWN from the site on 2026-10-04 and then RESTORED on 2026-10-10, the
    same reversal pinned by src/test/ShopIndexRedirect.test.ts. Header.tsx now carries the Shop
    nav link again, so the nav assertion below is INVERTED (invert, don't delete) to guard the
    restored state: the link must be PRESENT, not absent.
    """

    def test_no_list_row_mentions_shop(self, wa):
        for list_key, row in _all_rows(wa):
            assert 'shop' not in row['id'].lower(), f'{list_key}/{row["id"]}'
            assert 'shop' not in row['title'].lower(), f'{list_key}/{row["title"]}'

    def test_no_leaf_mentions_shop(self, wa):
        for leaf_id, (name, path) in wa.WD_LEAF_LINKS.items():
            assert 'shop' not in leaf_id.lower()
            assert 'shop' not in name.lower()
            assert 'shop' not in path.lower()

    def test_the_site_nav_has_the_restored_shop_link(self):
        """RESTORED 2026-10-10. The site nav carries the Shop link again, pointing at the
        browsable catalogue index at /shop/. Inverted from the withdrawal-era assertion that the
        link was absent; the restoration is the same one ShopIndexRedirect.test.ts pins. Asserted
        on the nav data, not the whole file: Header.tsx also mentions the SHOPPING BAG (the cart
        icon), which is a different thing from the menu entry."""
        with open(HEADER_TSX, encoding='utf-8') as fh:
            source = fh.read()
        assert "href: '/shop/'" in source
        assert "label: 'Shop'" in source

    def test_typed_shop_still_answers(self, handler_source):
        """STORE_KEYWORDS keeps `shop` as a TYPED alias on purpose - it is a live
        inbound word customers already send, answered with a CTA button, and it is
        not a menu row. Removing it would silently stop answering it."""
        assert 'shop' in _nested_literal(handler_source, 'STORE_KEYWORDS')


class TestTheSendPathIsSelfContainedAndByReference:
    def test_the_list_send_goes_straight_to_the_graph_api(self, handler_tree):
        called = _called_names(_function(handler_tree, '_send_wd_list'))
        assert '_send_direct_api_message' in called

    def test_the_list_send_does_not_go_through_outbound_whatsapp(self, handler_tree):
        """outbound-whatsapp answers interactiveType='list' with a 400 since
        2026-10-02, so delegating there would fail every menu send."""
        called = _called_names(_function(handler_tree, '_send_wd_list'))
        assert 'invoke' not in called
        assert '_send_ai_auto_reply' not in called

    def test_the_token_is_never_read_inline(self, handler_tree):
        """It comes from _load_direct_api_token, lazily, by reference."""
        called = _called_names(_function(handler_tree, '_send_wd_list'))
        assert 'get_secret_value' not in called

    def test_the_secret_is_named_not_embedded(self, wa):
        assert wa.META_TOKEN_SECRET == 'wecare/meta-system-user-token'

    def test_no_credential_shaped_literal_is_in_the_module(self, handler_source):
        for issuer in ('EAAG', 'rzp_live_', 'sk-', 'AIza', 'ghp_', 'AKIA'):
            assert issuer not in handler_source, f'{issuer}-shaped literal in the handler'

    def test_the_phone_number_is_masked_in_every_menu_log(self, handler_tree):
        """A full number in a log is a disclosure. Only the smoke-blocked line logs
        the phone at all, and it masks it."""
        source = ast.unparse(_function(handler_tree, '_send_wd_list'))
        assert "'senderPhone': mask_phone" in source
        assert 'mask_contact_id(contact_id)' in source


class TestOnlyOneMenuExists:
    """Ported from tests/test_menus_are_deleted.py. WD_LISTS is the only menu."""

    @pytest.mark.parametrize('name', DELETED_NAMES)
    def test_the_old_menu_machinery_stays_gone(self, wa, name):
        assert not hasattr(wa, name), f'{name} is back in the inbound handler'

    def test_the_old_row_id_dispatch_table_stays_gone(self, handler_tree):
        """MENU_TO_KEYWORD was function-local, so an attribute check cannot see it."""
        for node in ast.walk(handler_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assert target.id != 'MENU_TO_KEYWORD', \
                            f'MENU_TO_KEYWORD is back at line {node.lineno}'

    def test_nothing_calls_the_deleted_interactive_list_sender(self, handler_tree):
        """A surviving call would be a NameError at runtime, not a dead branch."""
        for node in ast.walk(handler_tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != '_send_interactive_list', \
                    f'the deleted sender is called at line {node.lineno}'

    def test_the_welcome_text_config_survives(self, wa):
        """Scope guard. `_get_welcome_config_key` and `_load_welcome_text` read the
        welcome_message TEXT config, not a menu, and must NOT be collateral."""
        assert callable(wa._get_welcome_config_key)
        assert callable(wa._load_welcome_text)

    def test_typed_keyword_flows_survive(self, wa):
        assert wa.DEFAULT_FLOW_TRIGGERS
        assert callable(wa._get_flow_triggers_config)

    def test_the_nfm_reply_branch_is_untouched(self, handler_source):
        """nfm_reply carries India address submissions and post-payment flow
        completions. It is not a menu and must still route."""
        assert "elif interactive_type == 'nfm_reply':" in handler_source
        assert '_handle_address_submission' in handler_source
        assert '_handle_postpay_submission' in handler_source


class TestNothingBecameUnreachable:
    """Carried forward UNCHANGED from tests/test_menus_are_deleted.py, which carried
    it from tests/test_one_menu.py.

    Every destination the old menus offered has to stay reachable by a typed keyword,
    and the Help reply has to keep naming them. None of these assertions is about a
    menu, which is why they survive both the deletion and this rebuild.
    """

    def test_appointment_keywords_survive(self, wa):
        keywords = wa.DEFAULT_FLOW_TRIGGERS['schedule_appointment']['keywords']
        for required in ('appointment', 'schedule appointment', 'book appointment'):
            assert required in keywords
        for added in ('book a visit', 'visit'):
            assert added in keywords

    def test_dropped_rows_are_still_reachable_by_keyword(self, wa, handler_source):
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
        body = handler_source.split('def _send_help_about', 1)[1].split('\ndef ', 1)[0]
        for mention in ('*my id*', '*store*', '*gift card*', '*order notes*',
                        '*review*', '*bharat stack*'):
            assert mention in body, f'{mention} is not discoverable anywhere'


class TestTheRivalMenuIsGone:
    """Carried forward from tests/test_menus_are_deleted.py.

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
