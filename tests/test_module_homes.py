"""Phase 8.1 — the declared module homes exist, are reachable, and load lazily.

A registry that names routes is worth nothing if the routes are not there. This parses
`src/config/navigation.ts` and checks each declared home and inner page against the
actual page files and against `getAllNavItems()`'s two trees, because the whole point of
the registry is that the IA stops being implicit.

It also pins the lazy-loading half of 8.1, which is where the measurable win was: four
hub pages statically imported their tab bodies, so opening the RCS hub downloaded the
inbox, the broadcast composer and the logs view before showing any of them. Measured per
page against the built export:

    /engage/rcs                  1,957,586 -> 1,233,536   -37.0%
    /engage/ses                  1,944,813 -> 1,233,034   -36.6%
    /engage/whatsapp/settings    1,669,961 -> 1,233,687   -26.1%
    /engage/dashboard            1,520,749 -> 1,443,385    -5.1%

Total bytes on disk went UP 6%, which is the correct trade and why "total _next/static"
is the wrong metric for a splitting change: more chunks, each smaller, and nobody
downloads all of them.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAV = ROOT / "src/config/navigation.ts"
PAGES = ROOT / "src/pages"

# The master prompt names eight module homes. Seven of them are declared; `growth` was
# removed on 2026-09-25 by owner instruction, along with `src/pages/growth/index.tsx` and
# the `NEXT_PUBLIC_ENABLE_GROWTH_MODULE` flag that used to gate it.
#
# This test previously demanded all eight unconditionally and had been failing on `growth`
# ever since. Three red tests that everyone knows to ignore are worse than no test, so the
# expectation is corrected here rather than left to rot - but the removal is recorded, not
# quietly absorbed, and `test_removing_growth_left_nothing_unreachable` below pins the
# property that actually mattered about it.
REQUIRED_IDS = {
    "home", "communications", "customers", "commerce",
    "service-operations", "platform-operations", "settings",
}

# Deliberately absent from REQUIRED_IDS. Named so the removal is searchable, and so
# re-adding the home means deleting a line here rather than guessing what changed.
REMOVED_IDS = {"growth"}

# `growth` was a grouping page over routes that each stand on their own. If the removal
# had orphaned any of them, that would be a real regression rather than a tidy-up, so the
# list it used to group is asserted reachable independently.
#
# Four routes left this list on 2026-10-07: /workspace/seo/pages, /workspace/seo/analytics,
# /workspace/seo/tracking and /workspace/seo/schema. They were retired consciously under
# owner decision B1 = CUT, not orphaned. Their backend was the `wecare-seo-platform`
# FastAPI service reached through `NEXT_PUBLIC_SEO_API_URL`, a variable that was never
# configured on `stack`, so `src/api/seo.ts`'s `seoFetch` threw on every call and all four
# screens errored on load - they were unreachable in practice long before they became
# unreachable by deletion. Removing them here is the honest bookkeeping, not a weakening:
# the property this list guards is unchanged, and the three routes that remain must still
# resolve to a real page file.
GROWTH_FORMER_INNER_PAGES = [
    "/workspace/seo",
    "/workspace/engage/whatsapp/ctwa-ads", "/workspace/engage/whatsapp/conversions-api",
]

HUBS_THAT_MUST_BE_LAZY = {
    "src/pages/workspace/engage/whatsapp/settings.tsx": 15,
    "src/pages/workspace/dashboard/index.tsx": 5,
    "src/pages/workspace/engage/rcs/index.tsx": 4,
    "src/pages/workspace/engage/ses/index.tsx": 3,
}


def route_to_page(route: str) -> pathlib.Path | None:
    """The page file backing a route, or None."""
    rel = route.strip("/").split("?")[0]
    for candidate in (PAGES / f"{rel}.tsx", PAGES / rel / "index.tsx"):
        if candidate.exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def nav_source() -> str:
    return NAV.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def homes(nav_source: str) -> list[dict]:
    block = nav_source.split("export const moduleHomes")[1]
    block = block[: block.index("\n];")]
    out = []
    for entry in re.finditer(
            r"id:\s*'([^']+)',\s*label:\s*'([^']+)',\s*(?:\n\s*)?path:\s*(null|'[^']*')",
            block):
        raw_path = entry.group(3)
        out.append({
            "id": entry.group(1),
            "label": entry.group(2),
            "path": None if raw_path == "null" else raw_path.strip("'"),
        })
    return out


@pytest.fixture(scope="module")
def inner_pages(nav_source: str) -> list[str]:
    block = nav_source.split("export const moduleHomes")[1]
    block = block[: block.index("\n];")]
    return re.findall(r"'(/[a-z0-9/-]+)'", block)


class TestTheDeclaredHomesExist:
    def test_all_declared_homes_are_present(self, homes):
        assert len(homes) == len(REQUIRED_IDS), (
            f"expected {len(REQUIRED_IDS)} module homes, found {len(homes)}")

    def test_the_ids_are_the_expected_set(self, homes):
        assert {h["id"] for h in homes} == REQUIRED_IDS

    def test_removed_homes_stay_removed(self, homes):
        """A re-added home must come back through REQUIRED_IDS, not by accident.

        Without this, restoring `growth` to the registry while leaving its page missing
        would make `test_the_ids_are_the_expected_set` fail with a confusing diff instead
        of saying what happened.
        """
        assert {h["id"] for h in homes} & REMOVED_IDS == set()

    @pytest.mark.parametrize("route", GROWTH_FORMER_INNER_PAGES)
    def test_removing_growth_left_nothing_unreachable(self, route):
        """Only the grouping page went; every route it listed still has its own page.

        This is the part of `growth` worth guarding. The home itself was navigation
        sugar, but if deleting it had taken a real destination with it, that would be a
        functional regression hiding behind a tidy-up.
        """
        assert route_to_page(route) is not None, (
            f"{route} was an inner page of the removed growth home and now has no page "
            "file - the removal orphaned a route")

    @pytest.mark.parametrize("module_id", sorted(REQUIRED_IDS - {"settings"}))
    def test_every_home_with_a_path_has_a_real_page(self, homes, module_id):
        home = next(h for h in homes if h["id"] == module_id)
        assert home["path"], f"{module_id} declares no path"
        assert route_to_page(home["path"]) is not None, (
            f"{module_id} points at {home['path']}, which has no page file")

    def test_settings_is_deliberately_not_a_route(self, homes, nav_source):
        settings = next(h for h in homes if h["id"] == "settings")
        assert settings["path"] is None
        # The reason has to be written down, or the next person "fixes" it by adding a
        # [retired public path] page and reintroduces a destination you navigate to before
        # navigating.
        assert "panel, not a route" in nav_source

    def test_no_declared_inner_page_is_missing(self, inner_pages):
        missing = [p for p in set(inner_pages) if route_to_page(p) is None]
        assert not missing, f"module homes declare inner pages that do not exist: {missing}"


class TestCommunicationsExposesExactlyThree:
    def test_exactly_three_and_they_are_the_named_three(self, nav_source):
        # The master prompt is explicit about this one, so it gets its own assertion
        # rather than being folded into the generic inner-page check.
        block = nav_source.split("id: 'communications'")[1]
        block = block[: block.index("},")]
        # Only the innerPages array. The first naive version of this also matched the
        # module's own `path: '[retired public path]'` and reported four.
        inner = block.split("innerPages:")[1]
        inner = inner[: inner.index("]")]
        pages = re.findall(r"'(/[a-z0-9/-]+)'", inner)
        assert pages == ["/workspace/engage/inbox", "/workspace/engage/whatsapp", "/workspace/engage/voice"], (
            f"Communications must expose exactly Common Inbox, WhatsApp Business and "
            f"Business Calling; found {pages}")


class TestReachability:
    def test_every_home_is_in_the_navigation_trees(self, homes, nav_source):
        # getAllNavItems() is the single source the command palette is built from, so a
        # home absent from both trees is a route you can only reach by typing the URL.
        for home in homes:
            if not home["path"]:
                continue
            assert f"'{home['path']}'" in nav_source, (
                f"{home['id']} -> {home['path']} appears in no nav tree, so the palette "
                f"cannot find it")

    def test_the_palette_still_walks_both_trees(self, nav_source):
        walker = nav_source.split("export function getAllNavItems")[1]
        assert "traverse( navigationConfig )" in walker
        assert "settingsConfig" in walker


class TestInnerPagesLoadLazily:
    @pytest.mark.parametrize("hub,minimum", sorted(HUBS_THAT_MUST_BE_LAZY.items()))
    def test_hub_tab_bodies_are_dynamic(self, hub, minimum):
        code = (ROOT / hub).read_text(encoding="utf-8")
        assert "next/dynamic" in code, f"{hub} does not import next/dynamic"
        count = len(re.findall(r"lazyTab\(\s*\(\s*\)\s*=>\s*import\(", code))
        assert count >= minimum, (
            f"{hub} lazy-loads only {count} tab bodies, expected at least {minimum}")

    @pytest.mark.parametrize("hub", sorted(HUBS_THAT_MUST_BE_LAZY))
    def test_no_tab_body_is_still_statically_imported(self, hub):
        code = (ROOT / hub).read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        code = "\n".join(re.sub(r"(?<!:)//.*$", "", ln) for ln in code.splitlines())
        # A page module imported statically defeats the split for that tab. Component
        # and library imports are fine - those are shared, not per-tab.
        #
        # OverviewTab is exempt and the exemption is load-bearing, not a loophole: it is
        # the dashboard's DEFAULT tab, so making it dynamic would add a network round
        # trip before the page can render anything. A separate test asserts it stays
        # eager, so this pair cannot both be satisfied by accident.
        eager_by_design = {"OverviewTab"}
        offenders = [
            m.group(2) for m in re.finditer(
                r"^import\s+(\w+)\s+from\s+'(\.[^']*(?:tabs/|pages/)[^']*)'", code, re.M)
            if m.group(1) not in eager_by_design
        ]
        assert not offenders, f"{hub} still statically imports tab bodies: {offenders}"

    def test_the_lazy_helper_keeps_prop_types(self, ):
        # Annotating the loader `Promise<any>` erased every tab's props and typecheck
        # rejected signOut/user/embedded at 17 call sites. The helper must stay generic.
        for hub in HUBS_THAT_MUST_BE_LAZY:
            code = (ROOT / hub).read_text(encoding="utf-8")
            assert "function lazyTab<P>" in code, (
                f"{hub}'s lazyTab is not generic, so it flattens tab prop types")

    def test_the_default_dashboard_tab_stays_eager(self):
        code = (ROOT / "src/pages/workspace/dashboard/index.tsx").read_text(encoding="utf-8")
        assert re.search(r"^import OverviewTab from", code, re.M), (
            "OverviewTab is the default tab; lazy-loading it only adds a round trip "
            "before the page can show anything")
