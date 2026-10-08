"""The website and the WhatsApp catalogue must exclude the SAME twelve Wix template samples.

PHASE W, FEAT-001, and the enforcement half of plan decision D4.

WHY TWO COPIES EXIST AT ALL. `src/content/shop.ts` owns `WIX_TEMPLATE_SAMPLE_PRODUCT_IDS` and
`WIX_TEMPLATE_SAMPLE_SLUGS`; `lambda_utils/ecommerce/meta_catalog_sync.py` carries its own copy.
Moving the list into one shared JSON file read by both would be the obvious fix and was rejected:
`shop.ts` is concurrently owned by the phase-o1 and ui-native-replace worktrees, so the shared-file
version means editing their file. A parity test catches the same drift at the same cost and touches
nothing they own.

WHAT DRIFT WOULD COST, so the test is not mistaken for tidiness. The twelve are the Wix store
template's demo products - Baseball Cap, Ceramic Flower Vase, Crew T-Shirt and nine more. They are
`visible: true` real catalogue rows that `/shop/` filters out rather than deleting from Wix. If the
Python copy fell behind, the WhatsApp catalogue would offer a Baseball Cap for sale to a customer
while the website did not list it - and ten of the twelve carry Wix's placeholder description
verbatim, so the WhatsApp listing would read "I'm a product description. I'm a great place to add
more details about...".

IT READS THE REAL FILE BY REGEX rather than importing it, because `shop.ts` is TypeScript and
importing it from pytest would need a transpiler for two arrays. The regex is anchored on the
exported `const` name and bounded by the closing bracket, so it extracts one array block and
cannot drift onto a neighbouring declaration.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync as sync  # noqa: E402

SHOP_TS = ROOT / "src/content/shop.ts"

EXPECTED_COUNT = 12


def _array(name: str) -> list[str]:
    """Extract the string members of `export const <name>: ... = [ ... ]` from `shop.ts`.

    Non-greedy up to the first `]`, so it stops at the end of the declaration it matched. Comments
    are ignored because only quoted members are collected - which matters: every id in that array
    is followed by a `// Product Name` comment naming the sample.
    """
    text = SHOP_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name}\s*:[^=]*=\s*\[(.*?)\]", text, re.S)
    assert match, f"{name} is no longer declared in {SHOP_TS.name} in the expected shape"
    return re.findall(r"'([^']+)'", match.group(1))


@pytest.fixture(scope="module")
def shop_ids() -> list[str]:
    return _array("WIX_TEMPLATE_SAMPLE_PRODUCT_IDS")


@pytest.fixture(scope="module")
def shop_slugs() -> list[str]:
    return _array("WIX_TEMPLATE_SAMPLE_SLUGS")


def test_the_regex_actually_found_twelve_of_each(shop_ids, shop_slugs):
    """THE GUARD ON THE GUARD. A regex that silently matched nothing would make every assertion
    below compare two empty sets and pass - which is the one way a parity test can be worse than
    no test. So the extraction is asserted before the comparison.
    """
    assert len(shop_ids) == EXPECTED_COUNT
    assert len(shop_slugs) == EXPECTED_COUNT
    assert all(re.fullmatch(r"[0-9a-f-]{36}", value) for value in shop_ids)
    assert all(re.fullmatch(r"[a-z0-9-]+", value) for value in shop_slugs)


def test_the_product_ids_match_exactly(shop_ids):
    assert set(shop_ids) == set(sync.WIX_TEMPLATE_SAMPLE_PRODUCT_IDS)


def test_the_slugs_match_exactly(shop_slugs):
    assert set(shop_slugs) == set(sync.WIX_TEMPLATE_SAMPLE_SLUGS)


def test_neither_list_has_a_duplicate(shop_ids, shop_slugs):
    """A duplicate would make the counts agree while the sets disagreed."""
    for values in (shop_ids, shop_slugs,
                   sync.WIX_TEMPLATE_SAMPLE_PRODUCT_IDS, sync.WIX_TEMPLATE_SAMPLE_SLUGS):
        assert len(set(values)) == len(values)


def test_the_python_copy_is_lowercase_so_the_comparison_is_the_one_is_syncable_makes(shop_ids):
    """`is_syncable` lowercases the row's id and slug before checking membership, so an upper-case
    member of either list would never match and the exclusion would silently stop working."""
    assert list(sync.WIX_TEMPLATE_SAMPLE_PRODUCT_IDS) == [
        v.lower() for v in sync.WIX_TEMPLATE_SAMPLE_PRODUCT_IDS]
    assert list(sync.WIX_TEMPLATE_SAMPLE_SLUGS) == [
        v.lower() for v in sync.WIX_TEMPLATE_SAMPLE_SLUGS]


def test_the_contribution_product_is_in_NEITHER_sample_list():
    """It is excluded from `/shop/` by a DIFFERENT rule (`isContributionRow`) and is deliberately
    INCLUDED in the Meta catalogue. Asserting it is not a sample keeps the two reasons separate:
    if it ever appeared in the sample list, the WhatsApp catalogue would lose it silently.
    """
    assert sync.CONTRIBUTION_PRODUCT_ID not in sync.WIX_TEMPLATE_SAMPLE_PRODUCT_IDS
    assert "contribute" not in sync.WIX_TEMPLATE_SAMPLE_SLUGS


def test_shop_ts_is_not_edited_by_this_feature():
    """D4's other half, stated as a test so the concurrency rule is visible where it is relied on.

    `shop.ts` is owned by the phase-o1 and ui-native-replace worktrees. This asserts the file still
    declares both arrays in the shape the regex above expects - which is what makes "we read their
    file and never write it" a safe arrangement rather than a hope.
    """
    text = SHOP_TS.read_text(encoding="utf-8")
    assert "export const WIX_TEMPLATE_SAMPLE_PRODUCT_IDS" in text
    assert "export const WIX_TEMPLATE_SAMPLE_SLUGS" in text
    assert "isTemplateSampleRow" in text
