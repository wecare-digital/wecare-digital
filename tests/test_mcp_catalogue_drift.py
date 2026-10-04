"""The live /mcp catalogue check, and the guard that keeps its workflow read-only.

WHY A SECOND CATALOGUE CHECK EXISTS AT ALL. `deploy_mcp_server.py --verify` already compares
the deployed zip's copy of config/public-pages.json byte for byte, and it is the stronger of
the two. But it calls lambda:GetFunction, so it only runs on the OIDC read role inside
public-surface-deploy.yml - a workflow that is dispatch-only and has no schedule, because its
sibling job writes production routing. The result was a guard that existed and never ran.

Measured on 2026-09-30, hours after /hunar and /vault merged: the live endpoint served 21 pages
while the repo declared 23. Nothing reported it. `--verify-live` is the credential-free check
that can therefore be scheduled, and these are its tests.

THE TESTS THAT MATTER MOST ARE THE EXIT-CODE ONES. A drift check that cannot tell "the
catalogue moved" from "I could not reach the endpoint" is worse than none: plivo-drift.yml
reported a false CRITICAL on 2026-09-28 for exactly that reason, because a failed credential
read and a moved invariant shared one exit code. So 1 and 3 are asserted separately, and every
unreachable shape is pinned to 3.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_mcp_server.py"
WORKFLOW = ROOT / ".github" / "workflows" / "mcp-catalogue-drift.yml"
CATALOG = ROOT / "config" / "public-pages.json"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("deploy_mcp_server", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_mcp_server"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("deploy_mcp_server", None)


SITE = "https://wecare.digital"

PAGES = [
    {"path": "/", "group": "start", "name": "Home", "description": "The home page."},
    {"path": "/vault", "group": "customerservice", "name": "Vault", "description": "Ask for a copy."},
]


def _catalog(tmp_path: Path, pages=None) -> Path:
    file = tmp_path / "public-pages.json"
    file.write_text(json.dumps({"pages": pages if pages is not None else PAGES}), encoding="utf-8")
    return file


def _served(pages=None) -> dict:
    """The response shape the live endpoint was measured to return."""
    out = []
    for page in (pages if pages is not None else PAGES):
        url = f"{SITE}/" if page["path"] == "/" else f"{SITE}{page['path']}/"
        out.append({**page, "url": url})
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"structuredContent": {"count": len(out), "pages": out, "groups": []}}}


def _wire(mod, monkeypatch, tmp_path, response, pages=None):
    """Point the module at a temporary catalogue and a canned endpoint reply."""
    monkeypatch.setattr(mod, "CATALOG_FILE", _catalog(tmp_path, pages))
    if isinstance(response, Exception):
        def rpc(*_args, **_kwargs):
            raise response
    else:
        def rpc(*_args, **_kwargs):
            return response
    monkeypatch.setattr(mod, "_rpc", rpc)


# --------------------------------------------------------------------------- #
# in step
# --------------------------------------------------------------------------- #

def test_matching_catalogue_is_in_step(mod, monkeypatch, tmp_path):
    _wire(mod, monkeypatch, tmp_path, _served())
    assert mod.verify_live() == 0


# --------------------------------------------------------------------------- #
# drift -> 1
# --------------------------------------------------------------------------- #

def test_a_page_missing_from_the_endpoint_is_drift(mod, monkeypatch, tmp_path):
    """The /hunar and /vault case: the repo grew and the Lambda was never redeployed."""
    _wire(mod, monkeypatch, tmp_path, _served(PAGES[:1]))
    assert mod.verify_live() == 1


def test_a_page_the_repo_dropped_but_the_endpoint_still_serves_is_drift(mod, monkeypatch, tmp_path):
    """The /my-order case, which is the worse direction: /mcp hands an agent a URL that 404s."""
    _wire(mod, monkeypatch, tmp_path, _served(), pages=PAGES[:1])
    assert mod.verify_live() == 1


def test_a_reworded_description_is_drift(mod, monkeypatch, tmp_path):
    """Descriptions are compared, not just paths. `list_pages` returns the same four fields the
    catalogue declares, so a reworded sentence is visible here - and it is what an agent reads
    out of /llms.txt."""
    stale = [dict(PAGES[0]), {**PAGES[1], "description": "Download your documents."}]
    _wire(mod, monkeypatch, tmp_path, _served(stale))
    assert mod.verify_live() == 1


def test_a_moved_group_is_drift(mod, monkeypatch, tmp_path):
    moved = [dict(PAGES[0]), {**PAGES[1], "group": "services"}]
    _wire(mod, monkeypatch, tmp_path, _served(moved))
    assert mod.verify_live() == 1


def test_a_url_without_the_trailing_slash_is_drift(mod, monkeypatch, tmp_path):
    """next.config.js sets trailingSlash, so the slashless form 301s and a citation carrying it
    can rot. test_mcp_server.py pins the same rule against the handler; this pins it against
    whatever is actually deployed."""
    response = _served()
    response["result"]["structuredContent"]["pages"][1]["url"] = f"{SITE}/vault"
    _wire(mod, monkeypatch, tmp_path, response)
    assert mod.verify_live() == 1


# --------------------------------------------------------------------------- #
# unreachable -> 3, never 1
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("failure", [
    urllib.error.URLError("connection refused"),
    urllib.error.HTTPError("https://wecare.digital/mcp", 502, "Bad Gateway", {}, None),
    TimeoutError("timed out"),
    ValueError("not JSON"),
])
def test_a_transport_failure_is_unreachable_not_drift(mod, monkeypatch, tmp_path, failure):
    _wire(mod, monkeypatch, tmp_path, failure)
    assert mod.verify_live() == 3


@pytest.mark.parametrize("response", [
    {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such method"}},
    {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"text": "boom"}]}},
    {"jsonrpc": "2.0", "id": 1, "result": {}},
    {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"pages": []}}},
])
def test_an_unusable_response_is_unreachable_not_drift(mod, monkeypatch, tmp_path, response):
    """An empty page list is UNREACHABLE rather than "every page is missing". A server that
    answers with nothing is broken, and reporting 23 missing pages would bury that."""
    _wire(mod, monkeypatch, tmp_path, response)
    assert mod.verify_live() == 3


def test_an_unreadable_catalogue_is_unreachable(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "CATALOG_FILE", tmp_path / "absent.json")
    assert mod.verify_live() == 3


# --------------------------------------------------------------------------- #
# the request itself
# --------------------------------------------------------------------------- #

def test_the_probe_posts_json_rpc_and_does_not_get(mod, monkeypatch):
    """POST, not GET, and it matters more here than usual: Amplify Hosting 301s an
    extension-less path to add a trailing slash and does it for POST too, which is why the
    /mcp rewrite exists at all. A probe that drifted to GET would stop exercising the thing
    the rewrite protects.
    """
    seen = {}

    class Response:
        def read(self):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(request, timeout=None):
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    mod._rpc("tools/call", {"name": "list_pages", "arguments": {}}, 11)

    assert seen["method"] == "POST"
    assert seen["url"] == "https://wecare.digital/mcp"
    assert seen["headers"]["content-type"] == "application/json"
    # JSON only. The streamable-http transport invites text/event-stream; the deployed server
    # was measured to answer JSON either way, and asking only for JSON means a future switch to
    # event-stream framing fails loudly here instead of being tolerated.
    assert seen["headers"]["accept"] == "application/json"
    assert seen["body"]["method"] == "tools/call"
    assert seen["body"]["params"]["name"] == "list_pages"
    assert seen["body"]["jsonrpc"] == "2.0"
    assert seen["timeout"] == 11


def test_no_handshake_is_sent_before_the_tool_call(mod, monkeypatch, tmp_path):
    """The server is stateless, and a bare tools/call was measured to work against production.
    One POST, so there is one thing to go wrong rather than two."""
    calls = []
    monkeypatch.setattr(mod, "CATALOG_FILE", _catalog(tmp_path))

    def rpc(method, params, timeout):
        calls.append(method)
        return _served()

    monkeypatch.setattr(mod, "_rpc", rpc)
    assert mod.verify_live() == 0
    assert calls == ["tools/call"], f"expected exactly one call, got {calls}"


# --------------------------------------------------------------------------- #
# the workflow must stay read-only
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_requests_no_aws_identity(workflow):
    """No id-token permission is the cheapest possible proof that nothing here assumes a role.
    It is also the property that lets this be scheduled at all: public-surface-deploy.yml left
    a verify cron out because a job that stays red waiting for an IAM decision is noise, and a
    check needing no role cannot end up in that state.
    """
    assert workflow["permissions"] == {"contents": "read"}, (
        "this workflow must need nothing but a checkout"
    )
    for name, job in workflow["jobs"].items():
        for step in job["steps"]:
            assert "role-to-assume" not in (step.get("with") or {}), (
                f"{name} assumes an AWS role; this check is meant to need no credentials"
            )


def test_the_workflow_never_runs_the_script_in_a_mode_that_writes(workflow):
    """A scheduled job that converged would redeploy a Lambda unreviewed. It reports instead.

    Asserted against every invocation rather than by searching for "--apply", because the bare
    command with no flag is the one that deploys.

    A LINE IS AN INVOCATION ONLY IF IT STARTS WITH `python`. The first version of this test
    scanned every line mentioning the script and failed on its own warning message, which
    legitimately advises running `deploy_mcp_server.py --verify` as the next diagnostic step.
    That is the same distinction test_public_surface_role_permissions.py records for `-f
    action=apply`: prose naming a command is not a call to it.
    """
    invocations = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            for line in (step.get("run") or "").splitlines():
                bare = line.strip()
                if bare.startswith("python ") and "deploy_mcp_server.py" in bare:
                    invocations.append(bare)
    assert invocations, "the workflow does not run the check at all"
    for line in invocations:
        assert "--verify-live" in line, f"not the read-only mode: {line}"
        assert "--apply" not in line, f"writes: {line}"


def test_the_workflow_fires_when_the_catalogue_changes(workflow):
    """The push trigger is the part that turns "someone has to remember to redeploy" into a red
    check on the merge that caused it, so the path filter has to name the file that goes stale.
    """
    paths = workflow[True]["push"]["paths"]
    assert "config/public-pages.json" in paths
    assert workflow[True]["push"]["branches"] == ["stack"]
    assert "schedule" in workflow[True], "out-of-band drift has no commit to key off"
    assert "workflow_dispatch" in workflow[True]


def test_the_workflow_distinguishes_drift_from_unreachable(workflow):
    """Exit 3 must not be treated as drift. If this collapses back into "non-zero is bad", the
    check starts reporting network blips as a wrong page catalogue.
    """
    runs = "\n".join(
        step.get("run") or "" for job in workflow["jobs"].values() for step in job["steps"]
    )
    assert "::warning::" in runs, "unreachable must warn"
    assert "::error::" in runs, "drift must error"
    # The exit codes are branched on explicitly rather than lumped together.
    assert "3)" in runs and "1)" in runs


def test_the_real_catalogue_has_the_fields_the_check_compares(mod):
    """verify_live compares path, name, description and group. If the catalogue ever stops
    carrying one of them the check would silently compare None against None and pass.
    """
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["pages"], "the real catalogue is empty"
    for page in catalog["pages"]:
        for field in ("path", "name", "description", "group"):
            assert page.get(field), f"{page.get('path')} has no {field}"
