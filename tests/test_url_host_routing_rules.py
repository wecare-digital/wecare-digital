"""The Amplify `customRules` array: its SHAPE, and the RATIFICATION of every redirect in it.

WHY THIS FILE EXISTS, AND WHY IT NO LONGER PINS A COUNT.

`scripts/provision_legacy_redirects.py` is the config-as-code source of every explicit
redirect on the public site. A redirect that shadows `/api/<*>` is a payment outage - that
prefix is where `POST /api/razorpay-webhook` is delivered - so the array genuinely needs a
gate. What it does not need is a gate that pins how MANY redirects there are.

That pin broke twice in two days, in both directions:

  * `c7afae00` (2026-10-01) landed a 540-line version of this file whose assertions were
    written around exactly one sanctioned redirect. `da78ef68` then deleted 420 of those
    lines while purging retired customer-link sources, leaving a 2.8 KB stub - a REMOVAL
    took the guard out.
  * `bb1cf39b` (2026-10-02) declared `/zip -> /shipments/` and `/zip/ -> /shipments/` for the
    owner's product rename, taking `desired_redirects()` from one rule to three. Five tests
    across this file and `test_legacy_redirect_rollback_snapshot.py` went red - an ADDITION
    broke the guard, and the production change was correct.

A guard that reddens on every legitimate product change trains people to ignore it, and then
to delete it. `tests/test_meta_version.py` states the principle this file now follows: "a
count in a document goes stale, a grep does not". So the redirect set is held HERE, as data,
with the instruction that sanctioned each entry recorded beside it. Adding or retiring a
redirect is one dict entry in `RATIFIED_REDIRECTS`. Everything else asserts a PROPERTY that
survives the set changing size: the host rule is first, no redirect can shadow a passthrough
in either direction, no rule targets the staff tree, the catch-all is last and unique.

THE RETIRED SET IS DERIVED, NOT TYPED, AND THAT IS NOT A STYLE CHOICE. The public path this
array used to forward to the home page was purged on 2026-10-02 by owner instruction, and the
purge rewrote it to a redaction marker inside the committed pre-change evidence itself
(`docs/execution/snapshots/retired-url-rules-before-20261002.json`). A hand-typed negative
assertion naming the old spelling would therefore match nothing in the fixture it reads: it
would pass while proving nothing, which is the same defect class as an assertion placed after
a set-equality that already failed. `_retired_sources()` computes the set from the fixture and
every caller asserts it is NON-EMPTY before using it, so vacuity is a test failure rather than
a silent pass. It also keeps working when the next removal lands, without re-typing anything
the owner has ordered removed.

SHADOWING IS COMPARED ON AMPLIFY PATTERN SEMANTICS, NOT ON A STRING PREFIX, and that is the
one place this file has already been wrong once. Round 2 of it compared a redirect source
against a hand-kept tuple of passthrough prefixes with `str.startswith`, which rejected
`/getting-started` as shadowing `/get/<*>` - a page the owner could plausibly ship tomorrow,
reddening the gate for no reason, which is the failure this redesign exists to end. It also
needed a second reverse branch to catch `/ap<*>` swallowing `/api/<*>`. `_patterns_overlap()`
replaces both with the actual question - can one request path match both patterns - and
`test_pattern_overlap_is_segment_aware_in_both_directions` pins it by example. Do not
"simplify" it back to a prefix test.

No AWS call is made anywhere in this file: `apply()` takes its client as an argument and the
client here is a stub that records the write.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "docs/execution/snapshots"

# Measured live state, both of them. NEITHER is an expected output and neither may be edited
# to make a test pass: `amplify-custom-rules-after-url-host-cleanup-20261001.json` is what the
# app served on 2026-10-01, and `--apply` has not run since the /zip rules were declared
# (bb1cf39b: "NOT APPLIED - THIS IS SOURCE ONLY"). Reconciling the 12-rule pre-change array now
# yields 11 rules, not the 9 in the `after` file. Rewriting that file to 11 would fabricate
# evidence for a write that has not happened, so the reconciliation test below computes its
# expectation from the provisioner instead.
PRE_CHANGE = SNAPSHOTS / "retired-url-rules-before-20261002.json"
POST_REMOVAL = SNAPSHOTS / "amplify-custom-rules-after-url-host-cleanup-20261001.json"

WWW_CANONICAL = {
    "source": "https://www.wecare.digital",
    "target": "https://wecare.digital",
    "status": "301",
}
CATCH_ALL = {"source": "/<*>", "target": "/404.html", "status": "404-200"}

# The runtime rewrites this file exists to protect, and what each one carries. Used as a
# COVERAGE FLOOR, not as the comparison: the set actually asserted against is DERIVED from what
# `apply()` writes, through the provisioner's own `is_ours()`, so a passthrough added later is
# protected without anybody editing this table. `test_the_critical_passthroughs_survive_the
# _write` pins the floor, so a rewrite silently disappearing is still a failure.
CRITICAL_PASSTHROUGHS = {
    "/api/<*>": "every provider webhook, including POST /api/razorpay-webhook",
    "/get/<*>": "the public media CDN origin",
    "/r/<*>": "the short-link service",
    "/mcp": "the tool catalogue served to MCP clients",
}
WILDCARD = "<*>"

# Mirrors `provision_legacy_redirects.REDIRECT_STATUSES` for the two tests that read a
# committed snapshot with no provisioner in scope. `test_the_redirect_status_set_matches_the
# _provisioner` stops the copy drifting from the original.
REDIRECT_STATUSES = frozenset({"301", "302", "307", "308", "404"})


# ───────────────────────────── the ratified redirect set, as data ─────────────────────────────
#
# Keyed on the whole (source, target, status) triple, so a silently RETARGETED or DOWNGRADED
# redirect is caught as well as a new source - `/zip -> /elsewhere/` and `/zip -> /shipments/`
# at 302 are both unratified. Insertion order is the expected array order, so one structure
# serves the membership check and the ordering check.
#
# The value is the instruction that sanctioned the entry. It is asserted non-trivial by
# `test_every_ratified_redirect_records_why_it_is_sanctioned`, matching the in-repo precedent
# `UNDECLARED_ALLOWED` in `scripts/check_data_model_drift.py` and the test that pins it,
# `test_both_new_tables_are_allowed_in_the_drift_gate_with_a_reason`: a gate that can be
# satisfied with an empty string is a gate somebody switches off.

RATIFIED_REDIRECTS: dict[tuple[str, str, str], str] = {
    ("https://www.wecare.digital", "https://wecare.digital", "301"):
        "Host canonicalisation, restored 2026-10-01T08:59:52Z. Source and target are bare "
        "origins with no path, which is what makes Amplify carry the request path across - "
        "measured, www /contact/ -> apex /contact/, not apex home. Evidence: "
        "docs/execution/url-host-matrix-20261001.md. SAMPLE CORRECTED 2026-10-04: this reason "
        "cited www /shop/ -> apex /shop/, which stops being a clean demonstration now that the "
        "/shop index itself 301s - www /shop/ chains 301 -> apex /shop/ -> 301 -> apex /, so "
        "landing on home would no longer distinguish path preservation from path loss. "
        "/contact/ is a terminal 200, so it still tells the two apart. The path-preservation "
        "PROPERTY is unchanged; only the sample URL moved.",
    ("/zip", "/shipments/", "301"):
        "RENAMED, not retired. bb1cf39b: the owner retired the product name Zip on 2026-10-02 "
        "and the page moved to /shipments/ with content unchanged. retired_url_equity.py: a 404 "
        "is correct for a page deleted because it was wrong and WRONG for a page that was "
        "replaced, because it discards link equity. Measured before: /zip 301 -> /zip/ -> 404, "
        "a redirect chain ending in a dead end.",
    ("/zip/", "/shipments/", "301"):
        "The canonical form under next.config trailingSlash. Both forms are declared because "
        "an Amplify source pattern is matched as given, not normalised, and links in the wild "
        "carry both - declaring one leaves the other 404ing. Target keeps its trailing slash "
        "because /shipments would itself redirect before resolving. 301 not 302: only a "
        "permanent redirect consolidates ranking.",
    # THE THREE /shop 301 RULES ARE GONE, 2026-10-10. They sent /shop, /shop/ and
    # /shop/index.html to the home page while the catalogue index was withdrawn (owner
    # instruction 2026-10-04). The owner reversed that on 2026-10-10: the index is browsable
    # again (src/pages/shop/index.tsx recreated, /shop back in PUBLIC_PAGE_META and PUBLIC_EXACT),
    # so a 301 in front of it would bounce the catalogue to home. desired_redirects() no longer
    # declares them, and RATIFIED_REDIRECTS no longer ratifies them, so the two stay in step.
    # The seven /shop/<slug>/ product pages were never redirected and are unaffected.
}

RATIFIED_RULES = [
    dict(zip(("source", "target", "status"), key)) for key in RATIFIED_REDIRECTS
]


def _rule_key(rule: dict) -> tuple[str, str, str]:
    return (str(rule.get("source", "")), str(rule.get("target", "")), str(rule.get("status", "")))


def _is_redirect(rule: dict) -> bool:
    return str(rule.get("status", "")) in REDIRECT_STATUSES


def _is_passthrough(rule: dict) -> bool:
    """A rule the provisioner does not own: a runtime rewrite, not a redirect.

    Classified through `_is_redirect` (which mirrors the provisioner's `is_ours()`) rather than
    by matching a hand-kept prefix list, so a rewrite added later is protected automatically.
    The catch-all is excluded: it is a 404-family fallback evaluated after file lookup, and it
    is pinned by its own test.
    """
    return not _is_redirect(rule) and str(rule.get("source", "")) != CATCH_ALL["source"]


def _match_prefix(pattern: str) -> tuple[str, bool]:
    """Split an Amplify source pattern into its literal prefix and whether it wildcards."""
    if pattern.endswith(WILDCARD):
        return pattern[: -len(WILDCARD)], True
    return pattern, False


def _patterns_overlap(a: str, b: str) -> bool:
    """True when some request path could be matched by BOTH Amplify source patterns.

    WHY THIS IS NOT `str.startswith` ON A PREFIX LIST. An Amplify source is matched AS GIVEN,
    not normalised - that is the documented reason both `/zip` and `/zip/` have to be declared
    separately. A raw string prefix therefore gets the question wrong in BOTH directions:

      * `/getting-started` shares the prefix `/get` with the CDN passthrough and cannot match
        `/get/<*>`, `/get` or `/get/`. Rejecting it would redden this gate on an ordinary new
        product page - the exact failure this redesign exists to end. Same for `/api-docs`,
        `/mcp-legacy`, and `/r` against `/r/<*>`.
      * `/ap<*>` does not START WITH any passthrough source, yet its wildcard swallows
        `/api/<*>` whole. A forward-only prefix test misses it.

    So compare the literal prefixes together with their wildcard-ness. `<*>` is treated as
    matching any suffix, which is the conservative reading: it makes overlap easier to detect,
    so the check fails closed.
    """
    prefix_a, wild_a = _match_prefix(a)
    prefix_b, wild_b = _match_prefix(b)
    if wild_a and wild_b:
        return prefix_a.startswith(prefix_b) or prefix_b.startswith(prefix_a)
    if wild_a:
        return b.startswith(prefix_a)
    if wild_b:
        return a.startswith(prefix_b)
    return a == b


def _retired_sources(rules: list[dict]) -> set[str]:
    """Redirect sources present in `rules` that the ratified set does not sanction.

    Derived rather than typed - see the module docstring. Every caller must assert the result
    is non-empty before asserting absence, or the negative check proves nothing.
    """
    ratified = {source for source, _target, _status in RATIFIED_REDIRECTS}
    return {str(r.get("source", "")) for r in rules if _is_redirect(r)} - ratified


@pytest.fixture(scope="module")
def redirects():
    path = ROOT / "scripts" / "provision_legacy_redirects.py"
    spec = importlib.util.spec_from_file_location("_hosting_redirects", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_hosting_redirects"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def before() -> list[dict]:
    """The 12-rule array measured live before the retired forwarding was removed."""
    return json.loads(PRE_CHANGE.read_text())


@pytest.fixture
def after() -> list[dict]:
    """The 9-rule array measured live on 2026-10-01. Evidence, not expected output."""
    return json.loads(POST_REMOVAL.read_text())


class _CapturingAmplify:
    """Records the write. `written` stays None when `apply()` short-circuits, which is the
    signal that a fixture was already converged and the assertions after it measured nothing."""

    def __init__(self) -> None:
        self.written: list[dict] | None = None

    def update_app(self, appId: str, customRules: list[dict]):  # noqa: N803 - boto3 casing
        self.written = customRules
        return {"app": {"appId": appId}}


# ─────────────────────── ratification: the set, and the reason for each entry ───────────────────────

def test_every_emitted_redirect_is_ratified_and_every_ratified_redirect_is_emitted(redirects):
    """Both directions. An allowlist is not a one-way sink.

    The two by-name loops sit BEFORE the set equality deliberately. The equality catches the
    same drift, but with a message a reader has to decode; and an assertion placed after it
    could never run. Round 1 of this file shipped its negative checks after an equality, where
    they were unreachable.
    """
    emitted = redirects.desired_redirects()

    # Stated as a requirement rather than a skip gate. Round 1 carried a helper that skipped
    # the file when the provisioner had not yet restored the host rule; it has, so that skip
    # could never fire again, and a skip that cannot fire is dead code hiding a real check.
    assert WWW_CANONICAL in emitted, (
        "the host canonicalisation rule is not emitted - without it every www URL is a "
        "duplicate-content copy of the apex"
    )

    unratified = [r for r in emitted if _rule_key(r) not in RATIFIED_REDIRECTS]
    assert not unratified, (
        "the provisioner emits redirects that nothing in this repo sanctions: "
        + ", ".join(f"{r['status']} {r['source']} -> {r['target']}" for r in unratified)
        + ". If these are intended, add one entry to RATIFIED_REDIRECTS recording the "
        "instruction that sanctioned each - the key is the whole (source, target, status) "
        "triple, so a retarget or a status downgrade needs ratifying too."
    )

    missing = [r for r in RATIFIED_RULES if r not in emitted]
    assert not missing, (
        "redirects are ratified but no longer emitted: "
        + ", ".join(f"{r['status']} {r['source']} -> {r['target']}" for r in missing)
        + ". A sanctioned redirect disappearing is drift in the other direction - inbound "
        "links to it start 404ing. Remove its RATIFIED_REDIRECTS entry if that was intended."
    )

    assert emitted == RATIFIED_RULES, "emitted redirects differ from the ratified set in ORDER"


def test_every_ratified_redirect_records_why_it_is_sanctioned():
    """An entry cannot be waved through with "" or "ok".

    Mirrors `test_both_new_tables_are_allowed_in_the_drift_gate_with_a_reason`. The whole value
    of moving the redirect set into data is that the instruction travels with it; an entry whose
    reason is a token is an exemption nobody can audit.
    """
    for key, reason in RATIFIED_REDIRECTS.items():
        assert reason.strip(), f"{key} is ratified with no recorded reason"
        assert len(reason.strip()) >= 40, (
            f"{key} is ratified with a token, not an instruction: {reason!r}. Record what "
            f"sanctioned it - who asked, when, and the evidence."
        )


def test_the_redirect_status_set_matches_the_provisioner(redirects):
    """The local copy exists only for the snapshot-reading tests; it must not drift."""
    assert REDIRECT_STATUSES == redirects.REDIRECT_STATUSES


# ─────────────────────────── reconciliation: what apply() actually writes ───────────────────────────

def test_the_pre_change_array_reconciles_to_the_ratified_set_with_every_passthrough_preserved(
    redirects, before, tmp_path, monkeypatch,
):
    """The real guarantee: a pre-change live array reconciles to the ratified set.

    REPLACES `test_saved_pre_removal_configuration_reconciles_to_post_removal_snapshot`, which
    asserted one committed snapshot reproduced another byte for byte. That is not a property of
    the provisioner, it is a property of two files, and it broke the moment a legitimate
    redirect was added (F4: reconciling the 12-rule pre-change array now yields 11 rules, and
    the committed `after` file holds 9). The `after` snapshot is deliberately NOT read here.
    """
    retired = _retired_sources(before)
    assert retired, (
        "the fixture holds no retired redirect, so removal is unproven - this test would pass "
        "on a provisioner that removes nothing"
    )

    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    assert redirects.apply(client, [dict(r) for r in before]) == 0
    assert client.written is not None, (
        "apply() short-circuited - the write path was not exercised, so nothing below is "
        "measuring the reconciliation. Drive this from a PRE-change array, not a converged one."
    )

    written_sources = {str(r.get("source", "")) for r in client.written}
    for source in sorted(retired):
        assert source not in written_sources, (
            f"apply() preserved retired forwarding for {source!r} - a path the owner ordered "
            f"removed is still redirecting"
        )

    expected = RATIFIED_RULES + [dict(r) for r in before if not redirects.is_ours(r)]
    assert client.written == expected
    assert client.written[0] == WWW_CANONICAL, "the host rule must lead the array"
    assert client.written[-1] == CATCH_ALL, "the 404-200 fallback must be last"


def test_applying_the_policy_twice_writes_once(redirects, before, tmp_path, monkeypatch):
    """Idempotence, asserted from whatever the ratified set currently is.

    REPLACES `test_converged_configuration_is_not_rewritten`, which fed the committed `after`
    snapshot and expected no write. That snapshot is no longer converged, so the test failed for
    a reason that had nothing to do with idempotence. Feeding `apply()`'s own output back to it
    needs no snapshot and keeps working as the ratified set changes.
    """
    monkeypatch.setattr(redirects, "ROOT", tmp_path)

    first = _CapturingAmplify()
    assert redirects.apply(first, [dict(r) for r in before]) == 0
    assert first.written is not None, "the first apply() must write, or there is nothing to re-apply"

    second = _CapturingAmplify()
    assert redirects.apply(second, [dict(r) for r in first.written]) == 0
    assert second.written is None, (
        "re-applying a converged array wrote again - every run would then churn the live app "
        "and emit a rollback snapshot for a no-op"
    )


def test_an_unratified_redirect_is_dropped_and_no_passthrough_is_disturbed(
    redirects, before, tmp_path, monkeypatch,
):
    """RENAMED from `test_unknown_redirect_removed_without_touching_proxy_rules`, whose body
    compared the write to the committed `after` snapshot and so failed on an unrelated addition.
    The passthrough guarantee is now derived through the provisioner's own classifier."""
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    existing = [{"source": "/unratified-fixture", "target": "/", "status": "302"}] + [
        dict(r) for r in before
    ]

    assert redirects.apply(client, existing) == 0
    assert client.written is not None, "apply() short-circuited; the removal was not exercised"

    assert "/unratified-fixture" not in {str(r.get("source", "")) for r in client.written}, (
        "an unratified redirect survived reconciliation"
    )
    assert [r for r in client.written if not redirects.is_ours(r)] == [
        r for r in before if not redirects.is_ours(r)
    ], "a runtime rewrite was reordered or dropped while removing a redirect"


# ─────────────────────────── structural invariants of the array ───────────────────────────

def test_no_ratified_redirect_can_shadow_a_passthrough_or_target_the_staff_tree(
    redirects, before, tmp_path, monkeypatch,
):
    """Asserted on the array `apply()` WRITES, in both overlap directions.

    REPLACES `test_no_path_redirects_shadow_api_or_staff_pages`, which asserted no rule in the
    committed `after` snapshot is a path redirect. `/zip` IS a sanctioned path redirect; that
    test passed only because the snapshot predates it and `--apply` has not run. It would have
    failed the moment anyone applied the policy and refreshed the snapshot - the premise was
    wrong, not the measurement.

    NON-OVERLAP, NOT ORDERING. The live array had the retired 302s at indexes 1-3 ahead of all
    seven passthroughs (`docs/execution/url-host-matrix-20261001.md:122`), so "passthroughs come
    first" was never the true guarantee. A redirect that cannot MATCH an /api, /get, /r or /mcp
    request cannot shadow it wherever it sits, which is the stronger property anyway.

    Ratification buys no exemption here: this runs on what apply() writes, so a redirect has to
    pass both this and `RATIFIED_REDIRECTS` to reach production.
    """
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    assert redirects.apply(client, [dict(r) for r in before]) == 0
    assert client.written is not None, "apply() short-circuited; the live shape was not built"

    passthrough_sources = {
        str(r.get("source", "")) for r in client.written if _is_passthrough(r)
    }
    assert passthrough_sources, "the rebuilt array must still contain the runtime rewrites"

    for rule in client.written:
        target = str(rule.get("target", ""))
        assert not target.startswith("/workspace"), (
            f"{rule.get('source')} targets the staff workspace: {target}. A customer URL may "
            f"never resolve into /workspace/**"
        )

        source = str(rule.get("source", ""))
        if not _is_redirect(rule) or not source.startswith("/"):
            continue  # the host rule's source is an origin, not a path; it cannot match one
        if rule == CATCH_ALL:
            continue  # the 404-200 fallback is evaluated after file lookup, and pinned elsewhere

        # One check, both directions, on Amplify pattern semantics rather than raw string
        # prefixes - see `_patterns_overlap`. A redirect UNDER a passthrough (/api/legacy) and a
        # wildcard redirect that SWALLOWS one (/ap<*> eats /api/<*>) both fail here; a redirect
        # that merely shares a string prefix (/getting-started vs /get/<*>) correctly passes.
        shadowed = sorted(p for p in passthrough_sources if _patterns_overlap(source, p))
        assert not shadowed, (
            f"redirect {source} overlaps runtime rewrite(s) {shadowed} - a request meant for a "
            f"passthrough would be redirected instead, regardless of array order. Provider "
            f"webhooks are delivered through /api/<*>, so a shadowing rule is a payment outage"
        )


def test_the_restored_shop_index_has_no_redirect_and_no_wildcard_near_a_product_page(
    redirects, before, tmp_path, monkeypatch,
):
    """The /shop index is browsable again: no 301 on it, and still no wildcard near a product page.

    INVERTED 2026-10-10. The owner withdrew the catalogue index on 2026-10-04 and had /shop,
    /shop/ and /shop/index.html 301 to home; this test used to assert those three rules were
    written. The owner reversed that on 2026-10-10 (src/pages/shop/index.tsx recreated, /shop back
    in PUBLIC_PAGE_META and PUBLIC_EXACT), so a 301 in front of the index would now bounce the
    catalogue to home. The first assertion is therefore inverted: NONE of the three spellings may
    be a /shop -> / 301 any more.

    THE WILDCARD GUARD IS KEPT UNCHANGED, because it protects the seven /shop/<slug>/ product
    pages regardless of what the index does. A `/shop/<*>` source would 301 every product page
    onto home - a self-inflicted catalogue outage no status check on /shop/ would notice - so its
    absence stays a first-class requirement, asserted through this file's own `_match_prefix`
    rather than a substring search.

    The three `_patterns_overlap` probes are deliberately a trio including a POSITIVE case. Two
    negatives alone would pass on a predicate broken into always returning False, which would
    disable the shadowing guard; the `/shop/<*>` case proves the predicate can still tell the
    dangerous pattern from the safe ones.

    No AWS call: `apply()` takes the capturing stub and the committed pre-change fixture.
    """
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    assert redirects.apply(client, [dict(r) for r in before]) == 0
    assert client.written is not None, (
        "apply() short-circuited - nothing below measured the written array. Drive this from a "
        "PRE-change array, not a converged one."
    )

    written = {_rule_key(r) for r in client.written}
    for spelling in ("/shop", "/shop/", "/shop/index.html"):
        assert (spelling, "/", "301") not in written, (
            f"{spelling} still 301s to the home page, but the owner restored the catalogue index "
            f"on 2026-10-10. A redirect in front of a page that now resolves at 200 bounces the "
            f"catalogue to home - remove the rule from desired_redirects()."
        )

    wildcarded = sorted(
        str(r.get("source", "")) for r in client.written
        if str(r.get("source", "")).startswith("/shop") and _match_prefix(str(r.get("source", "")))[1]
    )
    assert not wildcarded, (
        f"a /shop source wildcards its suffix: {wildcarded}. An Amplify wildcard matches any "
        f"suffix, so this 301s every /shop/<slug>/ product page onto the home page. The three "
        f"index spellings must stay EXACT sources."
    )

    assert not _patterns_overlap("/shop/", "/shop/file-assist/"), (
        "the exact /shop/ redirect is reported as able to match a product page"
    )
    assert not _patterns_overlap("/shop/index.html", "/shop/file-assist/"), (
        "the exact /shop/index.html redirect is reported as able to match a product page"
    )
    assert _patterns_overlap("/shop/<*>", "/shop/file-assist/"), (
        "_patterns_overlap no longer reports /shop/<*> as matching a product page, so the two "
        "negative assertions above prove nothing - the predicate itself is broken"
    )

    catalogue = json.loads((ROOT / "src/content/wix-catalog.json").read_text())
    slugs = [str(p["slug"]) for p in catalogue["products"] if p.get("slug")]
    assert slugs, (
        "no slugs were read from the catalogue snapshot, so the per-product loop below would "
        "assert nothing"
    )
    for slug in slugs:
        product_path = f"/shop/{slug}/"
        for source, _target, _status in RATIFIED_REDIRECTS:
            if not source.startswith("/"):
                continue  # the host rule's source is an origin, not a path
            assert not _patterns_overlap(source, product_path), (
                f"ratified redirect {source} can match the product page {product_path}, which "
                f"the owner's same instruction requires to keep rendering"
            )


def test_pattern_overlap_is_segment_aware_in_both_directions():
    """The predicate the shadowing guard turns on, pinned by example in both directions.

    Added 2026-10-02 after review: the first version of that guard compared raw string
    prefixes, so `/getting-started` was rejected as shadowing `/get/<*>`. A gate that reddens
    on an ordinary new product page is the failure this whole file was rewritten to end, so the
    cases are asserted here rather than left implicit in the loop.

    MUST NOT OVERLAP are real spellings the owner could plausibly ship next. MUST OVERLAP are
    mutations M8 and M9, which have to keep failing the guard.
    """
    must_not_overlap = [
        ("/getting-started", "/get/<*>"),   # shares the string prefix /get, cannot match it
        ("/getting-started", "/get"),
        ("/getting-started", "/get/"),
        ("/api-docs", "/api/<*>"),
        ("/mcp-legacy", "/mcp"),
        ("/mcp-legacy", "/mcp/"),
        ("/r", "/r/<*>"),                   # /r/<*> matches /r/abc, never bare /r
        ("/zip", "/get/<*>"),
        ("/zip/", "/api/<*>"),
    ]
    for source, passthrough in must_not_overlap:
        assert not _patterns_overlap(source, passthrough), (
            f"{source} is reported as shadowing {passthrough}, but an Amplify source is "
            f"matched as given rather than normalised, so it cannot - and rejecting a "
            f"legitimate new page is how this gate gets switched off"
        )

    must_overlap = [
        ("/api/legacy", "/api/<*>"),        # M8: under the passthrough
        ("/ap<*>", "/api/<*>"),             # M9: wildcard swallows the passthrough
        ("/mcp", "/mcp"),                   # exact collision with a rewrite
        ("/get/<*>", "/get/index.html"),    # wildcard redirect over an exact rewrite
        ("/<*>", "/api/<*>"),               # a redirect-status catch-all eats everything
    ]
    for source, passthrough in must_overlap:
        assert _patterns_overlap(source, passthrough), (
            f"{source} genuinely can intercept a request meant for {passthrough} and the "
            f"guard must fail closed on it"
        )


def test_the_critical_passthroughs_survive_the_write(redirects, before, tmp_path, monkeypatch):
    """The four rewrites whose loss is an outage are still there after reconciliation.

    The shadowing guard derives its passthrough set from `apply()`'s output, which is the right
    way round - a rewrite added later is protected without editing this file. The cost is that
    an empty derived set would make the guard vacuous in the one way that matters, so the floor
    is asserted by name here, with what each rewrite carries recorded beside it.
    """
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    assert redirects.apply(client, [dict(r) for r in before]) == 0
    assert client.written is not None, "apply() short-circuited; nothing was measured"

    written_sources = {str(r.get("source", "")) for r in client.written}
    for source, carries in CRITICAL_PASSTHROUGHS.items():
        assert source in written_sources, (
            f"the {source} rewrite is gone from the reconciled array - it carries {carries}"
        )
        assert carries.strip(), f"{source} is listed as critical with no recorded reason"


def test_the_catch_all_is_last_and_unique_in_the_snapshot_and_in_the_write(
    redirects, before, after, tmp_path, monkeypatch,
):
    """RENAMED from `test_missing_page_rule_stays_last`, and now asserted on both arrays.

    A second /<*> rule, or one that is not last, means the missing-page document stops being
    reachable - and that rule is also what `apply()` refuses to run without.
    """
    assert after[-1] == CATCH_ALL, f"snapshot: last rule must be the fallback, found {after[-1]}"
    assert [r for r in after if r.get("source") == "/<*>"] == [CATCH_ALL], (
        "snapshot: there must be exactly one /<*> rule"
    )

    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _CapturingAmplify()
    assert redirects.apply(client, [dict(r) for r in before]) == 0
    assert client.written is not None, "apply() short-circuited; the write was not inspected"
    assert client.written[-1] == CATCH_ALL
    assert [r for r in client.written if r.get("source") == "/<*>"] == [CATCH_ALL]


def test_the_host_rule_is_first_and_carries_no_path(after):
    """Source and target are bare origins, which is what preserves the request path.

    Measured after applying: `https://www.wecare.digital/contact/` -> 301 ->
    `https://wecare.digital/contact/`. Had the source carried a path, www would have collapsed
    every URL onto the apex home page - worse than the duplicate-content state the rule was
    restored to fix.

    SAMPLE CORRECTED 2026-10-04. This docstring cited `/shop/` as the measured sample. With the
    /shop index now 301ing to home, `www /shop/` chains 301 -> `apex /shop/` -> 301 -> `apex /`,
    so a reader checking that sample would see www traffic terminate on home - which is
    indistinguishable from the path-LOSS failure this rule exists to prevent. `/contact/` is a
    terminal 200, so it still separates the two. The property asserted below is unchanged.
    """
    assert after[0] == WWW_CANONICAL, f"first rule must be the host canonicalisation, found {after[0]}"
    for field in ("source", "target"):
        value = WWW_CANONICAL[field]
        assert value.startswith("https://"), value
        assert value.count("/") == 2, f"{field} must be a bare origin with no path: {value}"


def test_the_two_committed_snapshots_differ_only_in_redirect_rules(before, after):
    """The removal touched redirects and nothing else.

    Generalises round 1's `test_the_only_difference_is_the_host_canonicalisation_rule`, which
    named the one rule that moved and so had to be rewritten every time another one did. The
    property is what matters: whatever the redirect set does, the runtime rewrites and the
    fallback come through unchanged and in the same order.
    """
    assert [r for r in before if not _is_redirect(r)] == [r for r in after if not _is_redirect(r)]


def test_both_mcp_forms_proxy_to_one_backend(after):
    mcp = [rule for rule in after if rule["source"] in ("/mcp", "/mcp/")]
    assert len(mcp) == 2
    assert len({rule["target"] for rule in mcp}) == 1
    assert all(rule["status"] == "200" for rule in mcp)
