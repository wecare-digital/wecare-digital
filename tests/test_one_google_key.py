"""Canonical Google server secret and browser/server credential boundary.

The maintained contract is docs/operations.md#credential-handling-and-google-keys.
These tests enforce repository defaults and compatible candidate fields; they do not
assert current provider key validity, read credential values or authorize rotation.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_LANGUAGE = ROOT / "amplify/functions/core/site-language/handler.py"
WHATSAPP_TEMPLATES = ROOT / "amplify/functions/messaging/whatsapp-templates/handler.py"
VAYULOK_ENVIRONMENT = ROOT / "amplify/functions/core/vayulok-environment/handler.py"

#: The one id every consumer must read the Google API key from.
#:
#: wecare/google/cloud and not one of the others, because store_provider_secret.py already
#: records it as the canonical id for the google-cloud provider and it is the CMK-encrypted one.
CANONICAL = "wecare/google/cloud"

#: The ids that hold the same key and must no longer be read by any Lambda. They are NOT deleted
#: from AWS by this change - deleting a secret is an owner action, not something a code change
#: should do - but nothing in the repository may depend on them.
RETIRED = ("wecare/google-maps", "wecare/google-api-key")

LAMBDA_ROOT = ROOT / "amplify/functions"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """Drop # comments and docstrings.

    Both handlers document the ids they moved away from, at length and on purpose. A substring
    search cannot tell a citation from a call, and banning the strings outright would mean
    deleting the explanation that justifies the consolidation - the same trap
    Header.test.tsx records for rgba(26,58,42,.2).
    """
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return "\n".join(
        line.split("#", 1)[0] for line in without_docstrings.splitlines()
    )


def test_both_consumers_default_to_the_canonical_secret():
    for path in (SITE_LANGUAGE, WHATSAPP_TEMPLATES, VAYULOK_ENVIRONMENT):
        code = _strip_comments(_source(path))
        match = re.search(r'GOOGLE_SECRET\W*,\s*[\'"]([^\'"]+)[\'"]', code)
        assert match, f"{path.name}: no default secret id found"
        assert match.group(1) == CANONICAL, (
            f"{path.name} defaults to {match.group(1)!r}, not {CANONICAL!r}. Two ids for one key "
            f"means the owner's rotation updates one copy and leaves this consumer on a dead key."
        )


def test_no_lambda_reads_a_retired_google_secret_id():
    offenders = []
    for path in LAMBDA_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        code = _strip_comments(_source(path))
        for retired in RETIRED:
            if retired in code:
                offenders.append(f"{path.relative_to(ROOT)} still reads {retired}")
    assert not offenders, (
        "these hold the same key as " + CANONICAL + " and must not be read:\n  "
        + "\n  ".join(offenders)
    )


def test_the_two_consumers_agree_on_the_candidate_field_names():
    """The field list is duplicated in both handlers, and this is what keeps them identical.

    It is duplicated rather than shared because site-language does not import lambda_utils at
    all - it is a standalone handler - so a shared constant would change how it is packaged to
    save four words. A test that fails when the two lists drift is cheaper and carries no
    deployment risk.
    """
    # KEYED BY THE FULL RELATIVE PATH, NOT path.name. Both files are called handler.py, so the
    # first version of this collapsed the dict to a single entry and then raised IndexError
    # reaching for the second - a test that could never have compared anything.
    lists = {}
    for path in (SITE_LANGUAGE, WHATSAPP_TEMPLATES, VAYULOK_ENVIRONMENT):
        code = _strip_comments(_source(path))
        match = re.search(r'GOOGLE_SECRET_FIELD\W*,\s*[\'"]([^\'"]+)[\'"]', code)
        assert match, f"{path.relative_to(ROOT)}: no candidate field list found"
        lists[str(path.relative_to(ROOT))] = tuple(
            p.strip() for p in match.group(1).split(",") if p.strip()
        )
    names = sorted(lists)
    assert len(names) == 3, f"expected three distinct consumers, got {names}"
    assert lists[names[0]] == lists[names[1]], f"candidate field lists have drifted: {lists}"
    # Both names must be present, because the repository contradicts itself about which is real:
    # store_provider_secret.py declares `api_key`, check_secrets_live.py probes
    # `unified_google_api_key`. Dropping either reinstates a silent failure.
    for expected in ("api_key", "unified_google_api_key"):
        assert expected in lists[names[0]], (
            f"{expected} missing from the candidate fields. The repo disagrees about this "
            f"secret's field name, so trying only one guess is how the miss went unnoticed."
        )


def test_a_refused_credential_is_not_reported_as_an_empty_result():
    """REQUEST_DENIED must not look like "no addresses matched".

    Both Places proxies used to return HTTP 200 with Google's status echoed in the body and an
    empty list, so a refused key was indistinguishable from a query that matched nothing. The
    runbook records that REQUEST_DENIED is the EXPECTED answer here until a server key exists,
    which makes the ambiguity worse rather than better: an expected failure nobody can see is one
    nobody fixes.
    """
    code = _source(WHATSAPP_TEMPLATES)
    assert "def _google_status_problem" in code
    # ZERO_RESULTS is a real answer and must stay a success.
    assert "'ZERO_RESULTS'" in code
    # The referrer case is named specifically, because the generic message sent readers looking
    # for a quota or a typo.
    assert "referrer-restricted BROWSER key" in code
    # And both proxies consult it.
    assert code.count("_google_status_problem(data)") == 2


def test_operations_preserves_the_browser_server_credential_boundary():
    """A server key is unavoidable, and the consolidation must not be mistaken for solving it.

    A referrer-restricted key cannot authorise a server-side call, and an unrestricted key must
    not ship in a public JS bundle. So the browser and the server genuinely need different keys;
    consolidating the SECRET IDS does not change that, and this asserts the document that says so
    has not quietly lost the point.
    """
    operations = (ROOT / "docs/operations.md").read_text(encoding="utf-8")
    section = operations.split("## Credential handling and Google keys\n", 1)[1].split("\n## ", 1)[0]
    assert "referrer-restricted browser key cannot\nbe used server-side at all" in section
    assert "separate server key" in section
    assert "Server\ncredentials must never ship in a public JavaScript bundle" in section
    assert "Consolidating\nsecret identifiers does not remove this browser/server separation" in section
    assert CANONICAL in section
    assert "api_key" in section and "unified_google_api_key" in section
    assert "must not fetch secret values or rotate/revoke credentials" in section
