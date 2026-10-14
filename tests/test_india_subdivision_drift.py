"""The state dropdown and the tax table must name the same 36 places.

Why this gate exists
--------------------
`src/config/indiaSubdivisions.ts` is a second copy of the keys of
`lambda_utils.ecommerce.india_address.INDIA_SUBDIVISIONS`, and a copy of a table that decides
money is exactly the kind of duplicate that goes stale quietly. The subdivision is the place of
supply, so it decides the CGST/SGST versus IGST split.

Both directions are failures, and both are silent without this test:

* a name the form OFFERS that the Python table cannot resolve is a dead-end loop - the address
  saves, and then pay time refuses with ``UNMAPPABLE_STATE`` on a value the customer cannot
  correct, because nothing on screen says which spelling was wanted;
* a key the Python table HAS that the form does not offer is a customer who cannot enter their
  own state at all.

A set comparison catches both, which is why this asserts equality rather than a subset.

Case, aliases, and order
------------------------
The server lowercases before lookup (`india_subdivision` normalises whitespace, lowercases, and
maps ``&`` to ``and``), so the TS display names only have to match case-insensitively. Order is
deliberately not pinned: the TS file is alphabetical so the select is scannable, while the Python
table is in GST state-code order.

`INDIA_ALIASES` is NOT part of the comparison. It is a lookup convenience for spellings that turn
up in real data and Google Places output ("NCT of Delhi", "Orissa", "Daman and Diu"), so offering
one in the dropdown would mean offering a non-canonical name. The alias test is that the keys, and
only the keys, appear in the TS file.

Parsing
-------
Every single-quoted literal in the TS source, the same `re.findall` shape the repo's other
drift tests use against a TypeScript file. That is why `indiaSubdivisions.ts` carries a note
forbidding any other single-quoted string in it, comments included - a stray apostrophe in prose
would read as a 37th state.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import india_address  # noqa: E402

TS_SOURCE = ROOT / "src/config/indiaSubdivisions.ts"


def _ts_names() -> list:
    source = TS_SOURCE.read_text(encoding="utf-8")
    return re.findall(r"'([^']+)'", source)


def test_the_form_offers_exactly_what_the_tax_table_can_map():
    names = _ts_names()
    assert {n.lower() for n in names} == set(india_address.INDIA_SUBDIVISIONS)


def test_all_thirty_six_are_present_and_none_is_duplicated():
    names = _ts_names()
    assert len(names) == 36
    assert len(set(names)) == 36
    assert len(india_address.INDIA_SUBDIVISIONS) == 36


def test_the_two_names_that_are_easy_to_get_wrong():
    names = _ts_names()
    # One merged union territory since 2020, not the two the alias table still accepts.
    assert "Dadra and Nagar Haveli and Daman and Diu" in names
    # The canonical key is the short form; "NCT of Delhi" is an alias, not a key.
    assert "Delhi" in names
    assert "NCT of Delhi" not in names


def test_no_iso_code_leaked_into_the_display_table():
    """An ISO 3166-2 code here would not resolve: the server looks names up, not codes."""
    for name in _ts_names():
        assert not re.match(r"^[A-Z]{2}-[A-Z0-9]{1,3}$", name), name


def test_no_alias_is_offered_as_if_it_were_canonical():
    offered = {n.lower() for n in _ts_names()}
    aliases = set(india_address.INDIA_ALIASES) - set(india_address.INDIA_SUBDIVISIONS)
    assert offered & aliases == set()
