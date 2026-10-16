"""`--apply` must write the pre-change rules BEFORE it changes them, or there is no way back.

WHY THIS EXISTS. `provision_legacy_redirects.py --apply` rewrites the live Amplify
`customRules` array - 112 rules governing every retired URL on the public site. Until
2026-09-29 the only rollback artefact it produced was
`docs/execution/snapshots/amplify-custom-rules-before-8.4.json`, and that file is written
once and then kept forever, so it holds the THREE rules the app had on 2026-09-24. The
workflow summary named it as the thing to restore from. Restoring it would have deleted every
rule added since - the `/mcp` rewrite, the `/get/<*>` CDN passthrough, the whole `/workspace`
tree - a far larger outage than whatever it was reverting.

The timestamped snapshot that replaced it has two properties worth pinning, because both are
invisible on a successful run and only matter on the day someone needs them:

  1. it holds what was live, not what is about to be written;
  2. it is on disk BEFORE `update_app` is called.

Property 2 is the one a refactor breaks silently. A snapshot written after the write - or in
the same try block after an exception - is a file that describes the state you already lost.
The fake client here asserts the file exists at the moment `update_app` runs, so the ordering
is checked rather than assumed.

No AWS call is made: the client is a stub and `apply()` takes it as an argument.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".scratch"
PATTERN = "amplify-custom-rules-before-*.json"

# The glob the apply job hands to actions/upload-artifact. If the filename the script writes
# stops matching it, the artefact silently does not upload - the step warns and stays green.
WORKFLOW_GLOB = "amplify-custom*.json"

# Enough of a rule list to satisfy apply(): a domain 301, something it does not own, and the
# catch-all it refuses to write without.
LIVE_RULES = [
    {"source": "https://wecare.digital", "target": "https://wecare.digital", "status": "301"},
    {"source": "/get/<*>", "target": "https://d1kf2rchz7yras.cloudfront.net/<*>", "status": "200"},
    {"source": "/obsolete-fixture", "target": "/replacement-fixture/", "status": "301"},
    {"source": "/<*>", "target": "/404.html", "status": "404-200"},
]


@pytest.fixture(scope="module")
def redirects():
    path = ROOT / "scripts" / "provision_legacy_redirects.py"
    spec = importlib.util.spec_from_file_location("_legacy_redirects", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_legacy_redirects"] = module
    spec.loader.exec_module(module)
    return module


class _FakeAmplify:
    """Records the write, and checks the snapshot was already on disk when it happened."""

    def __init__(self) -> None:
        self.written: list[dict] | None = None
        self.snapshots_at_write_time: list[pathlib.Path] = []

    def update_app(self, appId: str, customRules: list[dict]):  # noqa: N803 - boto3 casing
        self.snapshots_at_write_time = sorted(SCRATCH.glob(PATTERN))
        self.written = customRules
        return {"app": {"appId": appId}}


def test_rollback_snapshot_is_written_before_the_write_and_holds_the_old_rules(redirects):
    before = set(SCRATCH.glob(PATTERN)) if SCRATCH.exists() else set()
    client = _FakeAmplify()

    # apply() mutates the catch-all in place, so hand it a copy and keep the original to
    # compare the snapshot against.
    result = redirects.apply(client, [dict(rule) for rule in LIVE_RULES])
    assert result == 0, "apply() refused to run on a rule list that contains the catch-all"
    assert client.written, "update_app was never called"

    new = sorted(set(SCRATCH.glob(PATTERN)) - before)
    try:
        assert len(new) == 1, f"expected one new rollback snapshot, found {new}"
        snapshot = new[0]

        assert snapshot in client.snapshots_at_write_time, (
            "the snapshot did not exist when update_app was called, so it describes state "
            "that was already overwritten"
        )

        saved = json.loads(snapshot.read_text())
        assert saved == LIVE_RULES, (
            "the snapshot is not the rules that were live. A snapshot of the NEW rules is "
            "worse than none: it looks like a rollback artefact and restores the state you "
            "were trying to leave"
        )
        assert saved != client.written, "snapshot and written rules are identical"

        assert snapshot.match(WORKFLOW_GLOB), (
            f"{snapshot.name} does not match the glob the apply job uploads "
            f"({WORKFLOW_GLOB}), so in CI the artefact would silently not upload"
        )
    finally:
        for path in new:
            path.unlink(missing_ok=True)


def test_the_historical_snapshot_is_not_advertised_as_a_rollback_target(redirects):
    """It holds three rules from 2026-09-24. Restoring it is an outage, not a recovery.

    Pinned because the mistake was in prose, and prose is where it will come back. Both the
    script and the workflow must say what the file is, and the workflow must not name it as
    the thing to restore from.
    """
    assert redirects.SNAPSHOT.name == "amplify-custom-rules-before-8.4.json"
    if redirects.SNAPSHOT.exists():
        historical = json.loads(redirects.SNAPSHOT.read_text())
        assert len(historical) < 10, (
            "this file was expected to hold the handful of rules the app started with; if it "
            "now holds a full list, re-read why it is excluded as a rollback target"
        )

    workflow = (ROOT / ".github/workflows/public-surface-deploy.yml").read_text()
    assert "amplify-custom-rules-before-${{ github.run_id }}" in workflow, (
        "the apply job must upload the pre-change rules as a run artefact"
    )
    assert "is NOT a" in workflow and "amplify-custom-rules-before-8.4.json" in workflow, (
        "the summary must name the historical snapshot and say it is not a rollback target"
    )


def test_owner_policy_preserves_rewrites_without_restoring_legacy_destinations(redirects, tmp_path, monkeypatch):
    """Legacy redirects disappear and no legacy destination comes back.

    2026-10-02: `assert approved == [removals[0]]` was deleted from this body. It pinned the
    approved set to exactly ONE rule, and the owner adds and retires redirects as ordinary
    product work - `bb1cf39b` declared `/zip -> /shipments/` for a product rename and this
    assertion went red on a correct production change. That is the second time in two days a
    count pin in this area broke on a legitimate edit (the first was a removal deleting the
    guard outright), so the count is gone and the PROPERTY it was standing in for is asserted
    instead: every retired source stays retired, and no `/workspace` destination returns.

    The exact ratified redirect set is owned by `tests/test_url_host_routing_rules.py`
    (`RATIFIED_REDIRECTS`), cross-referenced rather than duplicated - two copies of the same
    expectation in two files is precisely the drift this change exists to end. The retired set
    below is derived from this test's OWN fixture data, so it needs no import and no sys.path
    edit under `--import-mode=importlib`.
    """
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    rewrites = [
        {"source": "/api/<*>", "target": "https://api.example/prod/<*>", "status": "200"},
        {"source": "/get/<*>", "target": "https://media.example/<*>", "status": "200"},
        {"source": "/mcp", "target": "https://api.example/prod/mcp", "status": "200"},
        {"source": "/<*>", "target": "/404.html", "status": "404-200"},
    ]
    removals = [
        {"source": "https://wecare.digital", "target": "https://wecare.digital", "status": "301"},
        {"source": "/obsolete-fixture-2/", "target": "/anew/", "status": "301"},
        {"source": "/obsolete-login-fixture/<*>", "target": "/workspace/obsolete-login-fixture/<*>", "status": "302"},
        {"source": "/retired", "target": "/", "status": "404"},
    ]
    client = _FakeAmplify()
    assert redirects.apply(client, removals + rewrites) == 0
    approved = redirects.desired_redirects()
    assert client.written, "update_app was never called, so no removal was exercised"

    # Derived from this test's own fixtures, not typed: whatever `removals` offers that the
    # policy does not approve is what must have been dropped.
    approved_sources = {r["source"] for r in approved}
    retired = {r["source"] for r in removals} - approved_sources
    assert retired, (
        "every fixture redirect is approved, so this test proves no removal - add a legacy "
        "rule to `removals` or it is asserting against an empty set"
    )

    written_sources = {r["source"] for r in client.written}
    for source in sorted(retired):
        assert source not in approved_sources, f"legacy redirect {source!r} is back in the policy"
        assert source not in written_sources, f"legacy redirect {source!r} was written to the app"

    # EVERY SPECIFIC ASSERTION SITS ABOVE THE EQUALITY, deliberately, and these two were moved
    # here on 2026-10-02 after review. They are not redundant with the derived loop above:
    # ratifying a source removes it from `retired`, so a RATIFIED reinstatement of the legacy
    # login forwarding is caught only by these hand-named literals (measured - mutation M11).
    # They used to sit after the equality, where a reordering defect that fails the equality
    # first (mutation M10) would mean they never execute at all. An assertion downstream of a
    # failed equality is the same defect class as a vacuous one: it cannot report what it was
    # written to report.
    assert not any(r['source'].startswith('/obsolete-login-fixture') for r in approved)
    assert all("/workspace" not in r["target"] for r in approved)
    assert approved[0] == removals[0], "the host canonicalisation must lead the approved set"

    # The broad net, last: it catches the same drift as everything above, but with a list diff
    # a reader has to decode rather than a message that names the offending rule.
    assert client.written == approved + rewrites
    client.written = None
    assert redirects.apply(client, approved + rewrites) == 0
    assert client.written is None, "a converged config must not write or recreate aliases"


def test_removal_refuses_to_erase_a_missing_page_fallback(redirects, tmp_path, monkeypatch):
    monkeypatch.setattr(redirects, "ROOT", tmp_path)
    client = _FakeAmplify()
    assert redirects.apply(client, LIVE_RULES[:-1]) == 2
    assert client.written is None
