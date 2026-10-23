"""Two scripts write the GitHub OIDC trust policy. They must write the same one.

WHY THIS TEST EXISTS. On 2026-09-27 the repository was renamed `bharat-stack` ->
`wecare-digital` and two deploy workflows went dark for 22 hours with

    Not authorized to perform sts:AssumeRoleWithWebIdentity

which reads as a credentials fault and is not one. This repo was created after
2026-07-15, so it uses GitHub's immutable subject format:

    repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH

The ids survive a rename. The NAME segments are still in the string and do not.
Both trust policies pinned the whole string with `StringEquals`, so the rename
broke them.

THE REGRESSION THIS GUARDS, which is subtler than the original bug. After the
repair, `scripts/provision_ci_route_auth_role.py` still contained a name-pinned
`StringEquals` document *and* called `update_assume_role_policy` with it. Running
`--apply` for any unrelated reason would have silently reverted the hardening on
one of the three roles and re-armed the outage for the next rename. Nothing would
have failed at the time; the damage only appears on a rename, which is exactly the
kind of latent trap a test has to hold down.

So: both modules must emit a byte-identical document, and that document must not
pin a repository or owner NAME anywhere.

These assertions are pure data checks on module constants. No AWS call is made and
no credential is read, so this runs in CI with no permissions.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

OWNER_ID = "319896805"
REPO_ID = "1342943014"
BRANCH = "stack"
PROVIDER = "token.actions.githubusercontent.com"

# Names that must never appear in the matched subject. Both the old and the current
# repository name are listed: the current one is just as wrong to pin, because
# pinning it is what makes the next rename an outage.
FORBIDDEN_NAMES = ("bharat-stack", "wecare-digital@")


def _load(relpath: str, name: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, relpath
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def provisioner():
    return _load("scripts/provision_ci_route_auth_role.py", "_oidc_provisioner")


@pytest.fixture(scope="module")
def plivo():
    return _load("scripts/provision_ci_plivo_drift_role.py", "_oidc_plivo")


@pytest.fixture(scope="module")
def fixer():
    return _load("scripts/fix_github_oidc_trust.py", "_oidc_fixer")


def _canonical(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _account_id_from(doc: dict) -> str:
    """Extract the account id from the already-declared provisioner trust ARN."""
    arn = doc["Statement"][0]["Principal"]["Federated"]
    return str(arn).split(":")[4]


def _conditions(doc: dict) -> tuple[dict, dict]:
    statements = doc["Statement"]
    assert len(statements) == 1, "expected exactly one trust statement"
    condition = statements[0]["Condition"]
    return condition.get("StringEquals", {}), condition.get("StringLike", {})


def test_both_scripts_write_the_same_document(provisioner, fixer):
    """Whichever runs last must not change the outcome."""
    assert _canonical(provisioner.TRUST) == _canonical(
        fixer.target_policy(_account_id_from(provisioner.TRUST))
    )


@pytest.mark.parametrize("which", ["provisioner", "fixer"])
def test_subject_is_matched_by_pattern_not_by_name(which, provisioner, fixer):
    doc = provisioner.TRUST if which == "provisioner" else fixer.target_policy(
        _account_id_from(provisioner.TRUST)
    )
    equals, like = _conditions(doc)

    # The subject must be a StringLike pattern. A StringEquals subject is the bug.
    assert f"{PROVIDER}:sub" not in equals, (
        "subject pinned with StringEquals; a rename will break this role"
    )
    subject = like.get(f"{PROVIDER}:sub")
    assert subject, "no StringLike subject condition"

    # IAM rejects a trust policy whose sub condition is only a wildcard.
    assert subject.strip() not in ("*", "?"), "IAM refuses a wholly wildcard subject"

    for name in FORBIDDEN_NAMES:
        assert name not in subject, f"subject pins the repository name via {name!r}"

    # The ids and the branch are what actually constrain it.
    assert f"@{OWNER_ID}/" in subject
    assert f"@{REPO_ID}:" in subject
    assert subject.endswith(f":ref:refs/heads/{BRANCH}")


@pytest.mark.parametrize("which", ["provisioner", "fixer"])
def test_immutable_ids_pinned_as_their_own_conditions(which, provisioner, fixer):
    """Belt and braces: the ids are also asserted outside the subject string."""
    doc = provisioner.TRUST if which == "provisioner" else fixer.target_policy(
        _account_id_from(provisioner.TRUST)
    )
    equals, _ = _conditions(doc)
    assert equals.get(f"{PROVIDER}:aud") == "sts.amazonaws.com"
    assert equals.get(f"{PROVIDER}:repository_owner_id") == OWNER_ID
    assert equals.get(f"{PROVIDER}:repository_id") == REPO_ID


def test_trust_grants_only_web_identity_assumption(provisioner):
    statement = provisioner.TRUST["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Principal"]["Federated"].endswith(f"oidc-provider/{PROVIDER}")


def _roles_declared_in_the_repository() -> dict[str, list[str]]:
    """Every GitHub Actions role name this repository declares, and where.

    Three precise shapes rather than a loose grep, so a role NAMED IN PROSE does not
    count and a role actually wired up does:

      * `role/GitHubActions-...` in a workflow -- a literal `role-to-assume`
      * `ROLE = "GitHubActions-..."` in a script -- a provisioner's module constant
      * `--role-name GitHubActions-...` in a scripts/*.md -- a committed create-role command

    fix_github_oidc_trust.py is excluded from the scan because it holds the list under
    test; including it would make the assertion trivially true.
    """
    found: dict[str, list[str]] = {}

    def record(name: str, where: pathlib.Path) -> None:
        places = found.setdefault(name, [])
        relpath = str(where.relative_to(ROOT))
        if relpath not in places:
            places.append(relpath)

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + \
        sorted((ROOT / ".github" / "workflows").glob("*.yaml"))
    for path in workflows:
        for name in re.findall(r"role/(GitHubActions-[A-Za-z0-9_+=,.@-]+)", path.read_text()):
            record(name, path)

    for path in sorted((ROOT / "scripts").glob("*.py")):
        if path.name == "fix_github_oidc_trust.py":
            continue
        for name in re.findall(
            r'^ROLE\s*=\s*"(GitHubActions-[A-Za-z0-9_+=,.@-]+)"', path.read_text(), re.M
        ):
            record(name, path)

    for path in sorted((ROOT / "scripts").glob("*.md")):
        for name in re.findall(
            r"--role-name\s+(GitHubActions-[A-Za-z0-9_+=,.@-]+)", path.read_text()
        ):
            record(name, path)

    return found


def test_fixer_covers_every_oidc_role_the_repository_declares(fixer):
    """A role left off the list is a role that silently keeps the old policy.

    THIS USED TO BE A LITERAL SET, and the literal was wrong. It named four roles and
    asserted they were exactly the OIDC roles; meanwhile
    `scripts/provision_ci_plivo_drift_role.py` had created a fifth in AWS on 2026-09-28
    and nobody added it. So the test certified a list that was missing a live role -- the
    failure mode it was written to prevent, wearing the costume of a passing test. A
    second copy of a set is a thing that drifts, in the same way a second copy of a
    policy is.

    So the expected set is now DERIVED from what the repository declares. A new
    provisioner script or a new `role-to-assume` fails this test until the role is
    registered with the fixer, which is the property the original test was reaching for.

    It cannot see a role created straight from the CLI and never mentioned in the repo.
    `fix_github_oidc_trust.py --status` covers that half against live IAM, because only
    an AWS call can.
    """
    declared = _roles_declared_in_the_repository()
    missing = sorted(set(declared) - set(fixer.ROLES))
    assert not missing, (
        "these roles are wired up in the repository but not registered in "
        "fix_github_oidc_trust.ROLES, so they keep whatever trust document their creator "
        "wrote: " + ", ".join(f"{name} (declared in {', '.join(declared[name])})" for name in missing)
    )

    # And nothing goes the other way without a reason. A name in ROLES that the repo does
    # not declare anywhere is either a typo or a role nothing uses.
    unexplained = sorted(set(fixer.ROLES) - set(declared))
    assert not unexplained, (
        "registered with the fixer but declared nowhere in the repository: "
        + ", ".join(unexplained)
    )


def test_all_three_provisioners_and_the_fixer_write_one_document(provisioner, plivo, fixer):
    """Three scripts and one committed file. Four copies, one document.

    `test_both_scripts_write_the_same_document` covered two of the four. The plivo
    provisioner was the third and it differed -- it carried a `Sid` the others did not --
    which is enough to fail the fixer's byte comparison. The consequence was not cosmetic:
    once plivo-drift was registered with the fixer, `--apply` would strip the Sid and the
    next `provision_ci_plivo_drift_role.py --apply` would restore it, two scripts
    reverting each other forever.
    """
    account_id = _account_id_from(provisioner.TRUST)
    assert _canonical(plivo.TRUST) == _canonical(fixer.target_policy(account_id))
    assert _canonical(provisioner.TRUST) == _canonical(fixer.target_policy(account_id))


def test_read_role_grants_no_write_action():
    """The safe half may inspect/simulate policy but must remain unable to mutate production.

    The role is also reused by the shared-S3 scope check. That check needs GetRolePolicy on one
    named role plus SimulateCustomPolicy, which is non-mutating and does not support useful
    resource scoping. Keep those two exceptions explicit so "read-only" remains a property,
    not a filename.
    """
    doc = json.loads((ROOT / "scripts" / "iam-public-surface-read-permissions.json").read_text())
    auxiliary_reads = {"iam:GetRolePolicy", "iam:SimulateCustomPolicy"}
    for statement in doc["Statement"]:
        assert statement["Effect"] == "Allow"
        actions = statement["Action"]
        actions = actions if isinstance(actions, list) else [actions]
        for action in actions:
            assert "*" not in action, f"{action} is a wildcard action"
            service, verb = action.split(":", 1)
            assert (
                verb.startswith("Get")
                or (service, verb) == ("apigateway", "GET")
                or action in auxiliary_reads
            ), f"{action} is not an approved non-mutating read/simulation action"
        resources = statement["Resource"]
        resources = resources if isinstance(resources, list) else [resources]
        for resource in resources:
            if resource == "*":
                assert actions == ["iam:SimulateCustomPolicy"], (
                    f"{statement['Sid']} grants wildcard resource outside the IAM custom-policy simulator"
                )


def test_committed_trust_document_matches_the_fixer(fixer):
    """The JSON handed to `aws iam create-role` must be the document the fixer enforces.

    The role is created from a committed file - scripts/iam-public-surface-trust.json -
    because a trust policy pasted into a terminal is not reviewable and not diffable.
    That file is therefore a second copy of the same document, and a second copy is a
    thing that drifts: if it kept a name-pinned subject while the fixer wildcarded it,
    `create-role` would install the bug and `fix_github_oidc_trust.py --apply` would
    quietly undo it later, so whichever ran last would decide whether the next rename
    is an outage. Byte equality is asserted rather than eyeballed.
    """
    committed = json.loads((ROOT / "scripts" / "iam-public-surface-trust.json").read_text())
    assert _canonical(committed) == _canonical(
        fixer.target_policy(_account_id_from(committed))
    )


def test_route_auth_live_gate_does_not_run_on_pull_requests():
    """The branch-scoped subject cannot be produced by a pull_request event.

    A PR emits `...:pull_request` rather than `...:ref:refs/heads/stack`, so the job
    can never authenticate there; and a fork PR gets no OIDC token at all. Running
    it on PRs made the job red for a reason a contributor could not fix.

    This asserts the PROPERTY (the live-gate's guard excludes pull_request), not a
    single literal spelling. The guard was later tightened from
    `github.event_name != 'pull_request'` to an allowlist of
    `schedule`/`workflow_dispatch` (moving the live-AWS job off the push fan-out).
    Both forms keep PRs out; a brittle substring match would fail the stricter —
    and still-correct — form, so match either.
    """
    route_auth = ROOT / ".github/workflows/route-auth.yml"
    if not route_auth.exists():
        # The workflow was removed in `ci: remove route auth workflow for now` (e8882658) while
        # the CI gates were consolidated. There is no live-gate to constrain when the file is
        # absent, so this property is vacuously satisfied — skip rather than hard-error on a
        # deleted path. If route-auth.yml returns, this test resumes guarding it.
        pytest.skip("route-auth.yml is not present on this tree (CI gate consolidation)")
    workflow = route_auth.read_text(encoding="utf-8")
    live_gate_if = next(
        (ln.split("if:", 1)[1].strip()
         for ln in workflow.splitlines()
         if "if:" in ln and "ROUTE_AUTH_ROLE_ARN" in ln),
        "",
    )
    assert live_gate_if, "could not find the live-gate's `if:` guard in route-auth.yml"
    excludes_prs = (
        "github.event_name != 'pull_request'" in live_gate_if
        or (
            "pull_request" not in live_gate_if
            and "github.event_name ==" in live_gate_if
            and "schedule" in live_gate_if
            and "workflow_dispatch" in live_gate_if
        )
    )
    assert excludes_prs, (
        "route-auth live-gate must be excluded from pull_request events; its guard was: "
        + live_gate_if
    )
