"""Every WhatsApp site-menu row leads somewhere real.

The WhatsApp site menu (`WD_LEAF_LINKS` / `WD_LISTS` in inbound-whatsapp-handler) mirrors
the public Header by hand. On 2026-10-15 Elsewhere became a category with three child pages;
the Header followed, the WhatsApp menu did not,
and its Elsewhere row kept sending customers a link that 404'd to the home page.

These tests pin the class of defect rather than that one row:

* every row in every list resolves to another list, a leaf, or `wd_back`;
* every leaf path is a page the static export actually builds - an exact public route
  from scripts/generate-sitemap.js, or a `/shop/<slug>/` product in the catalogue snapshot;
* every list stays inside Meta's interactive-list limits, and every submenu offers a way back.

The handler module builds AWS clients at import time, so the two dicts are read from its
source with `ast` instead of importing it.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'
SITEMAP = ROOT / 'scripts/generate-sitemap.js'

# Meta interactive-list limits (also enforced defensively by `_send_wd_list`).
MAX_ROWS, MAX_TITLE, MAX_DESCRIPTION = 10, 24, 72
MAX_BODY, MAX_BUTTON, MAX_HEADER = 1024, 20, 60


def _literal(name: str):
    """The literal value assigned to a module-level `name` in the handler source."""
    tree = ast.parse(HANDLER.read_text(encoding='utf-8'))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if name in targets:
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not found in {HANDLER}')


LEAVES: dict = _literal('WD_LEAF_LINKS')
LISTS: dict = _literal('WD_LISTS')


def _public_exact() -> set[str]:
    """Routes in PUBLIC_EXACT, read from the sitemap generator with comments stripped."""
    source = SITEMAP.read_text(encoding='utf-8')
    block = re.search(r'const PUBLIC_EXACT = new Set\(\s*\[(.*?)\]\s*\);', source, re.S)
    assert block, 'PUBLIC_EXACT not found in scripts/generate-sitemap.js'
    body = re.sub(r'(^|\s)//[^\n]*', r'\1', block.group(1))
    return set(re.findall(r"'(/[^']*)'", body))


def _is_built_page(path: str, exact: set[str]) -> bool:
    if path == '/':
        return True
    shop = re.fullmatch(r'/shop/([a-z0-9-]+)/', path)
    if shop:
        return (ROOT / 'src/pages/shop/[slug].tsx').is_file()
    return path.endswith('/') and path.rstrip('/') in exact


def test_every_row_resolves_to_a_list_a_leaf_or_back():
    dangling = [(key, row['id']) for key, spec in LISTS.items() for row in spec['rows']
                if row['id'] != 'wd_back' and row['id'] not in LISTS and row['id'] not in LEAVES]
    assert not dangling, f'rows that would fall through to "unknown": {dangling}'


def test_no_id_is_both_a_list_and_a_leaf():
    # A list id wins in `_handle_wd_list_reply`, so a duplicate leaf would be dead code
    # that still reads as the row's destination.
    assert not set(LISTS) & set(LEAVES)


@pytest.mark.parametrize('leaf_id', sorted(LEAVES))
def test_every_leaf_links_a_page_the_export_builds(leaf_id):
    name, path = LEAVES[leaf_id]
    assert name.strip(), leaf_id
    if path.startswith('https://wa.me/message/'):
        assert leaf_id in {'wd_referral', 'wd_perks'}, (leaf_id, path)
        return
    assert path.startswith('/') and path.endswith('/'), (
        f'{leaf_id}: {path!r} must be root-relative with the load-bearing trailing slash')
    assert _is_built_page(path, _public_exact()), (
        f'{leaf_id} links {path}, which is neither in PUBLIC_EXACT nor a visible /shop/ '
        'product - customers tapping it land on the 404 page')


def test_every_leaf_is_reachable_from_the_main_menu():
    seen, queue, reached = {'wd_main'}, ['wd_main'], set()
    while queue:
        for row in LISTS[queue.pop()]['rows']:
            rid = row['id']
            if rid in LISTS and rid not in seen:
                seen.add(rid)
                queue.append(rid)
            elif rid in LEAVES:
                reached.add(rid)
    assert set(LEAVES) - reached == set(), 'leaves no menu path can reach'


@pytest.mark.parametrize('key', sorted(LISTS))
def test_lists_stay_inside_meta_limits_and_offer_a_way_back(key):
    spec = LISTS[key]
    rows = spec['rows']
    assert 0 < len(rows) <= MAX_ROWS, key
    assert len(spec['body']) <= MAX_BODY and len(spec['button']) <= MAX_BUTTON, key
    assert len(spec.get('header', '')) <= MAX_HEADER, key
    for row in rows:
        assert len(row['title']) <= MAX_TITLE, (key, row['title'])
        assert len(row.get('description', '')) <= MAX_DESCRIPTION, (key, row['id'])
    if key != 'wd_main':
        assert rows[-1]['id'] == 'wd_back', f'{key} strands the customer one level down'


def test_elsewhere_opens_its_three_child_pages():
    rows = [r['id'] for r in LISTS['wd_elsewhere']['rows']]
    assert [LEAVES[r][1] for r in rows if r != 'wd_back'] == [
        '/elsewhere/visa/', '/elsewhere/trip/', '/elsewhere/activities/']
