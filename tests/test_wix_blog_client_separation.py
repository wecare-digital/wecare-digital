"""The blog's Wix client and the storefront's Wix client must stay separate.

WHAT HAPPENED, BECAUSE THE INVARIANT ONLY MAKES SENSE WITH IT
-------------------------------------------------------------
On 2026-10-05 the owner moved the storefront to a new Wix site, account and headless app
(commit a2c95f41), repointing `WIX_SITE_ID`, `WIX_ACCOUNT_ID` and `WIX_CLIENT_ID` on every
function that carried them. That was correct for catalog, cart, checkout and webhooks.

It also moved the BLOG, silently, because `_load_visitor_access_token` in
`operations/seo-tools/wix.py` minted its anonymous visitor token from the same
`WIX_CLIENT_ID`. The new site has no Blog app installed, so all 1,323 published posts
stopped being reachable. Measured against Wix directly, same mint, same two calls:

    197cd718-...  (old site fcd82f0c)   token OK   categories 200   posts 200, total=1323
    42b3cdbf-...  (new site c993128b)   token OK   categories 401   posts 401
                                        401 body: "UNAUTHENTICATED: No blog instanceId found"

THE TOKEN MINT SUCCEEDS FOR BOTH, which is the detail that made this expensive to find.
`grantType: anonymous` with any valid client id returns a usable token, so nothing failed
that looked like auth; the token was simply scoped to a site with no blog. The Lambda
translated the 401 into a 503 ("The blog index is temporarily unavailable"),
`src/lib/public-blog.ts` retried the 503 four times and then failed the build at
`/blog/page/[page]`, and three consecutive Amplify builds died there - one of them carrying
an unrelated fix for every authenticated /workspace/* route rendering blank. A blog on the
wrong site was able to block deploying work that had nothing to do with the blog.

WHAT THIS PINS. Not the literal ids - those change when the blog genuinely moves - but the
SEPARATION: the blog token must come from its own variable, that variable must not default
to the storefront's client, and the declared value must agree across the three places it is
written. Collapsing them back into one variable is a one-line change that produces no error
until a build happens to fail, which is exactly what happened.

Neither id is a secret. Both are public identifiers that grant nothing on their own and are
already committed in `src/config/wix.ts`; `src/config/wix.ts` says so at length.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEO_TOOLS = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
# `wix.py` is a bare-name sibling on sys.path inside the handler directory, so it is only
# importable once that directory is on the path - the same three lines test_wix_kill_switch.py
# uses. conftest EVICTS these modules between tests but deliberately does not add the path,
# so a file that relies on another file having done it passes in a full run and fails alone.
for _path in (str(ROOT / "amplify" / "functions" / "shared"), str(SEO_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

WIX_PY = SEO_TOOLS / "wix.py"
SEO_RESOURCES = ROOT / "amplify" / "seo-resources.ts"
MANIFEST = ROOT / "config" / "lambda-env-manifest.json"

STOREFRONT_VAR = "WIX_CLIENT_ID"
BLOG_VAR = "WIX_BLOG_CLIENT_ID"


def _env_default(source: str, name: str) -> str:
    """The literal default in `os.environ.get(name, 'default')`.

    Parsed from the AST rather than matched with a regex, because the call is wrapped
    across lines and followed by `.strip()`; a line-oriented pattern misses it.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        if not (isinstance(func.value, ast.Attribute) and func.value.attr == "environ"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != name:
            continue
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            return str(node.args[1].value)
        return ""
    raise AssertionError(f"no os.environ.get({name!r}, ...) found in wix.py")


def test_the_blog_token_is_minted_from_the_blog_client_not_the_storefront_one():
    module = importlib.import_module("wix")
    source = inspect.getsource(module._load_visitor_access_token)
    assert BLOG_VAR in source, (
        "_load_visitor_access_token must mint from the blog client. Minting from the "
        "storefront client points the blog at a site with no Blog app, and every blog "
        "read 401s."
    )
    # NEGATIVE ASSERTIONS GO AGAINST CODE, NOT COMMENTS - and this one failed on its first
    # run for exactly that reason. The function now carries a comment saying which of the two
    # variables it must use and which it must not, so the forbidden name appears in the
    # source as prose explaining the rule. This is the same trap PublicWidgets.test.tsx and
    # PublicBundleWeight.test.ts both document, one language over; stripping comments first
    # removes the whole class rather than re-deriving a pattern that dodges this one.
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines()
    )
    # Not even in a fallback chain: `WIX_BLOG_CLIENT_ID or WIX_CLIENT_ID` would reintroduce
    # the coupling the moment the blog variable were unset, which is the silent direction.
    assert not re.search(rf"\b{STOREFRONT_VAR}\b", code), (
        "the storefront client id must not be referenced in the blog token path"
    )


def test_the_two_clients_are_separate_variables_with_different_defaults():
    source = WIX_PY.read_text(encoding="utf-8")
    storefront = _env_default(source, STOREFRONT_VAR)
    blog = _env_default(source, BLOG_VAR)
    assert storefront and blog, "both clients need a default so an unset var still works"
    assert blog != storefront, (
        "WIX_BLOG_CLIENT_ID defaults to the storefront client, so the separation is "
        "cosmetic - a storefront migration would take the blog with it again"
    )


def test_the_blog_client_default_is_the_site_that_has_the_blog():
    """The default must be the value that WORKS, so an unset variable degrades to working.

    Pinned by identity against the pre-migration snapshot rather than by a literal typed
    here, so there is one source for "which client could read the blog" and this test
    cannot disagree with the record of what changed.
    """
    snapshot = json.loads(
        (ROOT / "docs" / "execution" / "snapshots"
         / "lambda-env-wix-before-site-migration-20261005.json").read_text(encoding="utf-8")
    )
    pre_migration = snapshot["old_to_new"][STOREFRONT_VAR]["old"]
    source = WIX_PY.read_text(encoding="utf-8")
    assert _env_default(source, BLOG_VAR) == pre_migration, (
        "the blog client default must be the client the blog was being read with before "
        "the storefront migration - that is the one measured to return posts/query "
        "total=1323. Anything else is a guess."
    )


def test_the_blog_client_is_declared_in_infra_and_not_only_live_patched():
    """A value that exists only on the live function is one redeploy from vanishing."""
    resources = SEO_RESOURCES.read_text(encoding="utf-8")
    assert f"{BLOG_VAR}:" in resources, (
        f"{BLOG_VAR} must be declared in amplify/seo-resources.ts, or the next CDK deploy "
        "drops it and the blog 401s again"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert BLOG_VAR in manifest["functions"]["wecare-seo-tools"], (
        f"{BLOG_VAR} must be declared in config/lambda-env-manifest.json"
    )


def test_the_declared_value_and_the_manifest_fingerprint_agree():
    """Three copies of one id drift. This makes a drift a test failure.

    The manifest stores `sha256:` plus the first 12 hex of the digest - the shape
    scripts/env_manifest.py writes - so the comparison is on fingerprints, and no id has to
    be duplicated into the manifest in clear.
    """
    resources = SEO_RESOURCES.read_text(encoding="utf-8")
    declared = re.search(rf"{BLOG_VAR}:\s*'([^']+)'", resources)
    assert declared, f"{BLOG_VAR} has no literal value in seo-resources.ts"
    fingerprint = "sha256:" + hashlib.sha256(declared.group(1).encode()).hexdigest()[:12]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["functions"]["wecare-seo-tools"][BLOG_VAR] == fingerprint, (
        "the manifest fingerprint does not match the value declared in seo-resources.ts; "
        "one of the two has drifted"
    )


def test_the_python_default_matches_the_infra_declaration():
    """Otherwise an unset variable serves a different site from a deployed one."""
    resources = SEO_RESOURCES.read_text(encoding="utf-8")
    declared = re.search(rf"{BLOG_VAR}:\s*'([^']+)'", resources)
    assert declared
    source = WIX_PY.read_text(encoding="utf-8")
    assert _env_default(source, BLOG_VAR) == declared.group(1), (
        "wix.py's fallback and seo-resources.ts disagree about the blog client"
    )
