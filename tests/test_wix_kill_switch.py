"""The Wix kill switch must cover every credential path, and must not cover the public read.

WHY THIS FILE EXISTS SEPARATELY FROM `test_attribution_and_wix_guards.py`.

That file fixed and tested the switch in ONE path, `ecommerce/wix-store`, on 2026-09-23. The
fix was real. What it did not do was cover the other two credential loaders, measured
2026-09-29:

    ecommerce/wix-store/handler.py       _load_wix_api_key()   honoured the switch
    operations/seo-tools/wix.py          _load_api_key()       IGNORED it
    scripts/wix_blog_migrate.py          load_api_key()        IGNORED it

The two that ignored it are the BLOG paths - the ones Blog Production publishes through. So
a switch named as though it disables Wix disabled the store and left publishing running,
which is the original defect in a new costume: an operator flips it, reads the commit that
says it was fixed, and believes they are safe.

The other half of the contract matters just as much. `_load_visitor_access_token` serves the
PUBLIC BLOG anonymously using a public client id, not a credential. If the switch covered
that too, setting it would take 1,323 live posts and the sitemap offline - and an incident
control whose side effect is a site outage will not be used during an incident, which is the
only time it exists for.

That client id is `WIX_BLOG_CLIENT_ID` since 2026-10-05, not `WIX_CLIENT_ID`: the storefront
migrated to a new Wix site that has no Blog app, and while the two shared one variable the
blog read 401 and failed the static build. The separation is pinned by
tests/test_wix_blog_client_separation.py. Nothing about the kill switch changed - the
anonymous path is still deliberately unguarded, for the reason above.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
SEO_TOOLS = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
for path in (str(SHARED), str(SEO_TOOLS), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from lambda_utils import wix_guard  # noqa: E402

STORE = ROOT / "amplify/functions/ecommerce/wix-store/handler.py"
SEO_WIX = SEO_TOOLS / "wix.py"
MIGRATE = ROOT / "scripts/wix_blog_migrate.py"

#: Every function that resolves a Wix API key. Each must refuse before reading a secret.
CREDENTIAL_LOADERS = (
    (STORE, "_load_wix_api_key"),
    (SEO_WIX, "_load_api_key"),
    (MIGRATE, "load_api_key"),
)


# ── The switch itself ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "on", "enabled"])
def test_the_usual_spellings_all_disable(monkeypatch, value):
    monkeypatch.setenv(wix_guard.FLAG, value)
    assert wix_guard.credentials_disabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "maybe", " "])
def test_anything_else_does_not_disable(monkeypatch, value):
    monkeypatch.setenv(wix_guard.FLAG, value)
    assert wix_guard.credentials_disabled() is False


def test_an_absent_variable_does_not_disable(monkeypatch):
    """The switch must not become the reason Wix is off.

    If its ABSENCE disabled Wix, the absence would be load-bearing and would hide a real
    misconfiguration - which is precisely how the original defect stayed invisible.
    """
    monkeypatch.delenv(wix_guard.FLAG, raising=False)
    assert wix_guard.credentials_disabled() is False


def test_the_switch_is_read_per_call_not_captured_at_import():
    """An incident control that needs a sandbox recycle to take effect is not a control."""
    source = (SHARED / "lambda_utils" / "wix_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_env = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and "environ" in ast.unparse(node.value)
    ]
    assert module_level_env == [], "the flag is captured at import"
    assert "os.environ.get(FLAG" in source


def test_refuse_if_disabled_raises_only_when_disabled(monkeypatch):
    monkeypatch.delenv(wix_guard.FLAG, raising=False)
    wix_guard.refuse_if_disabled("ctx")  # must not raise

    monkeypatch.setenv(wix_guard.FLAG, "true")
    with pytest.raises(RuntimeError, match="disabled"):
        wix_guard.refuse_if_disabled("ctx")


def test_the_refusal_names_the_variable_and_says_not_to_work_around_it(monkeypatch):
    monkeypatch.setenv(wix_guard.FLAG, "true")
    with pytest.raises(RuntimeError) as excinfo:
        wix_guard.refuse_if_disabled("publish path")
    message = str(excinfo.value)
    assert wix_guard.FLAG in message
    assert "publish path" in message
    # A refusal that does not say how to undo itself gets worked around.
    assert "clear that variable" in message
    # And it must say what it does NOT stop, or somebody will assume the site is down.
    assert "public blog" in message


# ── Every credential path honours it ────────────────────────────────────────────

@pytest.mark.parametrize("path,function", CREDENTIAL_LOADERS,
                         ids=lambda v: getattr(v, "name", v))
def test_every_credential_loader_mentions_the_switch(path, function):
    """Structural, so a loader added later without the guard is visible."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == function), None)
    assert node is not None, f"{function} not found in {path.name}"
    body = ast.unparse(node)
    assert ("refuse_if_disabled" in body
            or "_credentials_disabled" in body
            or wix_guard.FLAG in body), f"{path.name}::{function} ignores the kill switch"


def test_the_seo_tools_loader_refuses_before_reading_a_secret(monkeypatch):
    monkeypatch.setenv(wix_guard.FLAG, "true")
    monkeypatch.setenv("WIX_API_KEY_SECRET", "wecare/wix/headless-api-key")
    monkeypatch.setenv("WIX_SITE_ID", "fcd82f0c-9572-49c7-acfb-88fb05042ece")
    module = importlib.reload(importlib.import_module("wix"))

    import boto3
    real_client = boto3.client

    def guard(service, **kwargs):
        if service == "secretsmanager":
            raise AssertionError("a Secrets Manager read was attempted while disabled")
        return real_client(service, **kwargs)

    monkeypatch.setattr(boto3, "client", guard)
    with pytest.raises(RuntimeError, match="disabled"):
        module._load_api_key()


def test_the_publish_script_refuses_before_reading_a_secret(monkeypatch):
    """This is the path `gastronomy_batch.py` publishes through, transitively."""
    monkeypatch.setenv(wix_guard.FLAG, "true")
    import wix_blog_migrate

    monkeypatch.setattr(wix_blog_migrate, "_api_key", None, raising=False)

    import boto3
    real_client = boto3.client

    def guard(service, **kwargs):
        if service == "secretsmanager":
            raise AssertionError("a Secrets Manager read was attempted while disabled")
        return real_client(service, **kwargs)

    monkeypatch.setattr(boto3, "client", guard)
    with pytest.raises(RuntimeError, match="disabled"):
        wix_blog_migrate.load_api_key()


def test_an_unset_switch_lets_the_loaders_fail_for_the_honest_reason(monkeypatch):
    """"nothing is configured" and "deliberately disabled" are different operational facts."""
    monkeypatch.delenv(wix_guard.FLAG, raising=False)
    monkeypatch.delenv("WIX_API_KEY_SECRET", raising=False)
    module = importlib.reload(importlib.import_module("wix"))
    with pytest.raises(RuntimeError) as excinfo:
        module._load_api_key()
    assert "disabled" not in str(excinfo.value).lower()


# ── The public blog must keep serving ───────────────────────────────────────────

def test_the_anonymous_visitor_path_is_not_guarded():
    """Deliberately unguarded. Guarding it would make the switch a site outage.

    `_load_visitor_access_token` uses the public `WIX_CLIENT_ID` to read the blog for the
    public site - 1,140 posts, the sitemap, and the search index. It is not a credential.
    """
    module = importlib.import_module("wix")
    source = inspect.getsource(module._load_visitor_access_token)
    assert "refuse_if_disabled" not in source
    assert wix_guard.FLAG not in source


def test_the_public_blog_reads_do_not_route_through_the_api_key():
    """If they did, the switch would take the public site down as a side effect."""
    module = importlib.import_module("wix")
    for name in ("list_blog_posts", "get_blog_post_by_slug", "public_blog_request"):
        function = getattr(module, name, None)
        if function is None:
            continue
        source = inspect.getsource(function)
        assert "_load_api_key" not in source, f"{name} would be disabled by the switch"


# ── No drift between the implementations ───────────────────────────────────────

def test_the_store_handler_accepts_the_same_spellings():
    """Two loaders disagreeing about what "on" means is how a switch half-works."""
    source = STORE.read_text(encoding="utf-8")
    for spelling in ("1", "true", "yes", "on"):
        assert f"'{spelling}'" in source or f'"{spelling}"' in source, spelling


def test_cost_flags_agrees_on_truthiness():
    from lambda_utils import cost_flags
    assert set(cost_flags._TRUTHY).issubset(set(wix_guard.TRUTHY))
