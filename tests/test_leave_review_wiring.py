"""The `leave_review` door is wired to the PUBLISHED flow, and the workspace shows the same thing.

WHY THIS FILE EXISTS
--------------------
The reported symptom was that "Leave Review" did nothing. Three separate causes, each of
which alone is enough to produce that exact symptom:

  1. `DEFAULT_FLOW_TRIGGERS['leave_review'].flowId` pointed at a flow that was never
     published, so the open failed.
  2. The flow it should point at — WD_Leave_Review_v2, 1578178897413815 — is ENDPOINTLESS
     (no `data_api_version`, first screen `FEEDBACK` carries no `data` block). Opening an
     endpointless flow with `data_exchange` fails at open, and the failure looks identical
     to cause 1. So the flow id alone is not sufficient; `STATIC_ENTRY_SCREENS` must also
     name it. That is what `test_leave_review_opens_with_navigate...` guards.
  3. Four workspace surfaces advertised a different flow id and a shorter keyword list than
     the backend answers, so staff reading the workspace told customers the wrong words.
     That is what the drift guard at the bottom of this file guards.

THE SINGLE SOURCE OF TRUTH, AND WHY IT IS NOW A MODULE
------------------------------------------------------
There are TWO sources that must agree, in two languages that cannot import each other:

  * Python — `DEFAULT_FLOW_TRIGGERS['leave_review']` in the inbound handler.
  * TypeScript — `src/lib/reviewEntry.ts`, which the public page CTA and all four workspace
    tables import.

`KEYWORDS` below is the owner-decided ordered set, encoded ONCE here, and BOTH sources are
compared against it. The five TS surfaces are then asserted to REFERENCE the module's
constants rather than restate them — which is a stronger guard than comparing five literal
arrays, because a literal cannot drift if a literal is not allowed to exist.

Order matters and is asserted as an ordered list, not a set, because the first keyword
(`leave review`) is the prefill on the owner's `wa.me/message/ZM74K2H2BIFOA1` short link and
the handler's dispatch is an exact match over this collection.

No boto3 and no network: `load_entry` from test_customer_idea_entry execs only the top-level
nodes it needs.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# pytest.ini uses `--import-mode=importlib`, so a sibling test module is not importable by
# name without this. Same shape as tests/test_blog_queue.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_customer_idea_entry import load_entry  # noqa: E402

FLOW_ID = '1578178897413815'
WA_SHORT_LINK = 'https://wa.me/message/ZM74K2H2BIFOA1'

#: The ordered keyword set. Edit HERE first, then `reviewEntry.ts` and the handler, or this
#: module fails.
KEYWORDS = [
    'leave review', 'leave a review', 'review', 'reviews', 'feedback',
    'leave feedback', 'give feedback', 'share feedback', 'rate', 'rate us',
    'rate service', 'rating', 'ratings', 'testimonial', 'write a review',
    'give a review', 'share your experience', 'how was it',
    '\u2b50 leave review',
]

#: The one TypeScript source every review surface reads.
REVIEW_ENTRY = ROOT / 'src/lib/reviewEntry.ts'

PAGE = ROOT / 'src/content/customerservice.ts'
SELFSERVICE = ROOT / 'src/pages/workspace/forms/selfservice.tsx'
SCRIPTS = ROOT / 'src/pages/workspace/engage/whatsapp/scripts.tsx'
SETTINGS = ROOT / 'src/pages/workspace/engage/whatsapp/settings.tsx'
SYSARCH = ROOT / 'src/pages/workspace/dashboard/system-architecture.tsx'

WORKSPACE_FILES = [SELFSERVICE, SCRIPTS, SETTINGS, SYSARCH]


# ───────────────────────────── the backend wiring ─────────────────────────────

def test_leave_review_points_at_the_published_flow_with_the_full_keyword_set():
    ns, _ = load_entry()
    trigger = ns['DEFAULT_FLOW_TRIGGERS']['leave_review']
    assert trigger['flowId'] == FLOW_ID
    # An ordered list, deliberately: the dispatch is exact-match over this collection and
    # the first item is the short link's prefill.
    assert trigger['keywords'] == KEYWORDS
    assert trigger['enabled'] is True


def test_leave_review_opens_with_navigate_on_the_static_entry_screen():
    """The load-bearing guard — the assertion the flow id alone does not cover.

    WD_Leave_Review_v2 is endpointless, so `data_exchange` at open fails. Without
    `leave_review` in `STATIC_ENTRY_SCREENS` the keyword stays broken with a correct flow id,
    and the symptom is indistinguishable from the wrong id.
    """
    ns, calls = load_entry()
    ns['_send_generic_flow']('fixture-contact', 'phone1', 'fixture-phone', 'fixture-request',
                             flow_config=ns['DEFAULT_FLOW_TRIGGERS']['leave_review'],
                             flow_key='leave_review')
    assert len(calls) == 1
    data = json.loads(calls[0]['body'])['interactiveData']
    assert data['flowId'] == FLOW_ID
    assert data['flowAction'] == 'navigate'
    assert data['screenId'] == 'FEEDBACK'


def test_leave_review_shares_one_published_flow_with_customer_idea():
    """Two inbound doors, one Meta flow. Meta has no per-door flow identity, so this is the
    only available shape — recorded as an assertion so it reads as intended, not accidental."""
    ns, _ = load_entry()
    triggers = ns['DEFAULT_FLOW_TRIGGERS']
    assert triggers['leave_review']['flowId'] == triggers['customer_idea']['flowId'] == FLOW_ID


def test_the_customer_idea_overlap_resolves_to_the_same_door():
    """`customer_idea` CLAIMS 11 of the 19 keywords, and that is safe — asserted, not assumed.

    Dispatch is exact-match over `DEFAULT_FLOW_TRIGGERS` insertion order and `customer_idea`
    comes first, so for `leave review`, `review`, `feedback` and eight others it is the
    `customer_idea` trigger that answers. That is only harmless while the two doors are
    indistinguishable to a customer, so the three things that would make them differ are
    pinned here: the flow, the entry screen, and the WABA 2 fallback link. If a future edit
    repoints either door, this fails rather than silently sending half the keywords somewhere
    else.
    """
    ns, _ = load_entry()
    triggers = ns['DEFAULT_FLOW_TRIGGERS']
    overlap = set(triggers['customer_idea']['keywords']) & set(KEYWORDS)
    assert overlap, 'expected customer_idea to claim some review keywords'

    opens = {}
    for key in ('leave_review', 'customer_idea'):
        ns_i, calls = load_entry()
        ns_i['_send_generic_flow']('fixture-contact', 'phone1', 'fixture-phone',
                                   'fixture-request',
                                   flow_config=ns_i['DEFAULT_FLOW_TRIGGERS'][key],
                                   flow_key=key)
        data = json.loads(calls[0]['body'])['interactiveData']
        opens[key] = (data['flowId'], data['flowAction'], data['screenId'])
    assert opens['leave_review'] == opens['customer_idea'] == (FLOW_ID, 'navigate', 'FEEDBACK')

    # The WABA 2 CTA fallback, which is the one place the two keys used to disagree.
    for key in ('leave_review', 'customer_idea'):
        ns_i, _ = load_entry()
        ctas = []
        ns_i['_send_cta_button'] = lambda *a, **k: ctas.append(a)
        ns_i['_send_generic_flow']('fixture-contact', 'phone2', 'fixture-phone',
                                   'fixture-request',
                                   flow_config=ns_i['DEFAULT_FLOW_TRIGGERS'][key],
                                   flow_key=key)
        assert ctas and ctas[0][3] == WA_SHORT_LINK, \
            f'{key} WABA2 fallback is {ctas[0][3] if ctas else None!r}, not the verified link'


def test_no_other_flow_shadows_a_leave_review_keyword():
    """Dispatch is exact-match over dict insertion order, so an earlier trigger holding one
    of these words would swallow it. `customer_idea` is the one permitted overlap and is
    separately proven harmless by `test_the_customer_idea_overlap_resolves_to_the_same_door`."""
    ns, _ = load_entry()
    for key, config in ns['DEFAULT_FLOW_TRIGGERS'].items():
        if key in ('leave_review', 'customer_idea'):
            continue
        overlap = set(config.get('keywords') or []) & set(KEYWORDS)
        assert not overlap, f'{key} shadows leave_review keyword(s): {sorted(overlap)}'


# ──────────────────────── the cross-language drift guard ────────────────────────

def _ts_const(path, name):
    """Read a single-quoted TS string constant. The match is asserted, so a rename fails
    loudly rather than silently matching nothing."""
    match = re.search(rf"export const {name}\s*=\s*'([^']*)'", path.read_text())
    assert match, f'{path.name}: no `export const {name}` string found'
    return match.group(1)


def _ts_const_array(path, name):
    """Read an ordered TS string-array constant, anchored on the export."""
    source = path.read_text()
    match = re.search(rf"export const {name}\s*=\s*\[([^\]]*)\]", source)
    assert match, f'{path.name}: no `export const {name}` array found'
    return re.findall(r"'((?:[^'\\]|\\.)*)'", match.group(1))


def test_the_typescript_source_matches_the_backend():
    """One module, asserted against the same ordered list the handler is asserted against."""
    assert _ts_const(REVIEW_ENTRY, 'REVIEW_FLOW_ID') == FLOW_ID
    assert _ts_const(REVIEW_ENTRY, 'REVIEW_ENTRY_URL') == WA_SHORT_LINK
    assert _ts_const_array(REVIEW_ENTRY, 'REVIEW_ENTRY_KEYWORDS') == KEYWORDS


def test_every_review_surface_reads_the_shared_module_rather_than_restating_it():
    """The guard that makes drift structurally impossible instead of merely detectable.

    A surface that imports the constants cannot disagree with the handler. A surface that
    restates the id or the keyword list can, which is exactly how four tables came to
    advertise a flow that is not on the WABA at all — so a literal is a failure here, not a
    style preference.
    """
    for path in WORKSPACE_FILES:
        source = path.read_text()
        assert "from '" in source and 'reviewEntry' in source, \
            f'{path.name} does not import src/lib/reviewEntry'
        assert 'REVIEW_FLOW_ID' in source, f'{path.name} does not use REVIEW_FLOW_ID'
        assert 'REVIEW_ENTRY_KEYWORDS' in source, \
            f'{path.name} does not use REVIEW_ENTRY_KEYWORDS'
        # The id and the keyword list must not ALSO be written out by hand.
        assert FLOW_ID not in source, \
            f'{path.name} restates the flow id literally; import REVIEW_FLOW_ID instead'
        assert 'leave a review' not in source.lower(), \
            f'{path.name} restates the keyword list literally; use REVIEW_ENTRY_KEYWORDS'

    page = PAGE.read_text()
    assert 'reviewEntry' in page, 'the /leave-review/ page does not import reviewEntry'
    assert 'REVIEW_ENTRY_URL' in page
    assert WA_SHORT_LINK not in page, \
        'the page restates the short link literally; import REVIEW_ENTRY_URL instead'


def test_the_retired_flow_ids_and_link_are_gone_repo_wide():
    """963443293213262 was not present on the WABA at all; 4423166114671543 is an unpublished
    draft; F35I7EOSRPUII1 is the stale `wa.me/message` short link with no prefill.

    Scanned across every root the brief names rather than `src` alone, because a stale id in
    `amplify/`, `config/` or `docs/` is read by someone and acted on just as readily. Two
    deliberate exclusions: `docs/execution/change-authority-matrix.md` is APPEND-ONLY and
    carries a superseded historical line, and this file's own guard literals.
    """
    stale = ('963443293213262', '4423166114671543', 'F35I7EOSRPUII1')
    roots = ('src', 'amplify', 'tests', 'config', 'docs')
    suffixes = {'.ts', '.tsx', '.js', '.jsx', '.py', '.json', '.md', '.yml', '.yaml'}
    excluded = {
        ROOT / 'docs/execution/change-authority-matrix.md',
        Path(__file__).resolve(),
    }

    hits = []
    for root in roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob('*'):
            if (not path.is_file() or path.suffix not in suffixes
                    or path.resolve() in excluded or 'node_modules' in path.parts):
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for needle in stale:
                if needle in text:
                    hits.append(f'{path.relative_to(ROOT).as_posix()}: {needle}')
    assert not hits, 'retired leave-review identifiers still present:\n  ' + '\n  '.join(hits)


def test_the_page_cta_and_the_workspace_link_are_the_same_short_link():
    """One door, one URL. The page button and the workspace's copyable link must not diverge,
    because the link's Meta-side prefill (`Leave Review`) is what matches the first keyword.

    Keyed on `MESSAGE_LINKS.leave_review` rather than on the file containing the URL anywhere,
    so a link that moves to some other row fails instead of passing by coincidence.
    """
    source = SELFSERVICE.read_text()
    match = re.search(r'leave_review:\s*(REVIEW_ENTRY_URL)\b', source)
    assert match, 'selfservice MESSAGE_LINKS.leave_review does not read REVIEW_ENTRY_URL'
    # Both the page and the workspace resolve that identifier to the asserted constant.
    assert _ts_const(REVIEW_ENTRY, 'REVIEW_ENTRY_URL') == WA_SHORT_LINK
    assert 'REVIEW_ENTRY_URL' in PAGE.read_text()
