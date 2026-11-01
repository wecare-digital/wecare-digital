#!/usr/bin/env python3
"""Verify the Lambda fleet's S3 usage against the one media bucket and its two roots.

Why this exists
---------------
The merge into `wecare-digital-get` mapped `wecare-digital-get/<X>` to `o/<X>`, but the
handler prefixes kept the pre-merge shape, so the fleet read and wrote one level above its
own data. Nothing failed loudly: the apex host serves the whole bucket, so a key written to
the root returned HTTP 200. The breakage only showed up as a missing invoice logo, an
empty cleanup sweep, and a document download pointing at a bucket that does not exist.

Five things are checked, and each one corresponds to a defect that actually shipped:

1. **No dead bucket names.** `wecare-digital-media` and `wecare-digital-documents` (never
   existed) must not appear in handler source or in live Lambda configuration.
2. **Keys are rooted.** Every S3 key prefix must sit under `o/` or `secure/`.
3. **Import precedes use.** `media_paths` imported BELOW its first use is a module-scope
   NameError that byte-compiles cleanly and only fails at runtime. Three handlers shipped
   that way for one deploy cycle; this is the check that catches it statically.
4. **The edge gate matches the key contract.** The Lambda@Edge package cannot import
   `media_paths`, so it carries its own copy of `PRIVATE_DELIVERABLE_PREFIXES`; the two
   must be identical, and the edge must refuse a key under every one of them.
5. **The host topology matches whichever state we are actually in.** This check used to
   assert that `wecare-digital-get` still served this bucket through origin path `/o`,
   on the reasoning that the dual-homing was the only thing making `o/` load-bearing.
   That host was retired on 2026-09-28 — distribution `ERCXSFDL0VM8X` deleted, DNS
   record removed — so the old assertion could never pass again, and a check that can
   only fail gets ignored rather than fixed.

   `o/` is still load-bearing, for a reason that does not depend on the legacy host at
   all: every handler key, every `storageKey` already persisted in DynamoDB, the BIMI
   `l=` URL and every apex `/get/o/...` URL are written against it. Moving off `o/` is
   now a data migration, not a rename. So the convention is still enforced, and this
   check instead verifies the retirement is *coherent*: the host is gone from DNS, and
   nothing in source or live configuration still mints a URL on it.

    python scripts/verify_media_prefixes.py            # source checks only
    python scripts/verify_media_prefixes.py --live     # also check AWS

Exit status: 0 all checks pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import socket
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
MEDIA_PATHS = FUNCTIONS / "shared" / "lambda_utils" / "media_paths.py"

BUCKET = "wecare-digital-get"
# The live bucket must never be listed here. The 2026-10-24 retired-subdomain cleanup rewrote
# the deleted pre-merge bucket's name in this list to `wecare-digital-get`, which turned
# check 1 against every correct use of the live bucket.
DEAD_BUCKETS = ["wecare-digital-media", "wecare-digital-documents"]
PUBLIC_ROOT = "o/"
SECURE_ROOT = "secure/"

# The retired dual-homing host. Distribution deleted and DNS record removed 2026-09-28,
# so both are expected to be absent. Kept named here because the retirement itself is the
# thing under test: if either ever comes back, the topology claim in media_paths.py needs
# rewriting rather than silently diverging from reality.
#
# The distribution id is `ERCXSFDL0VM8X`, settled from
# docs/execution/snapshots/cloudfront-ERCXSFDL0VM8X-before-alias-removal.json, whose
# captured `Aliases` are exactly ["wecare-digital-get", "wecare.digital/contact",
# "selfcare.wecare.digital"]. Two places in the repo said `E1DP37QIS4G0T4` instead - that
# id resolves to nothing and never appears in any snapshot, so it was a transcription
# error. It happened to be harmless here only because BOTH ids return NoSuchDistribution,
# which is precisely the kind of coincidence that keeps a wrong constant alive.
LEGACY_HOST = "wecare-digital-get"
LEGACY_HOST_DISTRIBUTION = "ERCXSFDL0VM8X"
LEGACY_HOST_ORIGIN_PATH = "/o"

# An S3 key: a string constant beginning with a known top-level folder name.
KEYISH_RE = re.compile(r"(?:stack|stream|public|whatsapp-media|obd-audio|media)/")


class Result:
    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"  ok    {name}" + (f"  [{detail}]" if detail else ""))
        else:
            self.failed += 1
            print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))


def handler_files() -> list[pathlib.Path]:
    return [p for p in sorted(FUNCTIONS.rglob("*.py"))
            if p != MEDIA_PATHS and "__pycache__" not in p.parts
            and "/tests/" not in p.as_posix()]


def check_no_dead_buckets(r: Result) -> None:
    print("\n1. no dead bucket names in handler source")
    offenders: list[str] = []
    files = handler_files()
    for p in files:
        parsed = parse(p)
        if parsed is None:
            continue
        tree, _src, docstrings = parsed
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue  # prose explaining the history is expected, and necessary
            if node.value in DEAD_BUCKETS:
                offenders.append(f"{p.relative_to(FUNCTIONS)}:{node.lineno} {node.value}")
    r.add("no dead bucket literal is used as a value", not offenders,
          "; ".join(offenders[:4]) if offenders else f"{len(files)} files scanned")


def parse(p: pathlib.Path):
    """(tree, source, docstring_node_ids) or None when the file will not parse.

    Text scanning was wrong twice here, in opposite directions, which is why this is an
    AST now:

    * Per-LINE scanning missed rooting that sits on a continuation line, because
      `media_paths.public(` ends up on the previous physical line. Three false positives.
    * Per-STATEMENT scanning then flagged PROSE, because a docstring explaining the `o/`
      convention legitimately contains the text `media_paths.` and `stack/`. One false
      positive, in the very file being documented.

    An AST distinguishes code from the text that describes it, which is exactly the
    distinction both mistakes turned on.
    """
    src = p.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return tree, src, docstrings


def enclosing_statements(tree):
    """Map id(node) -> nearest enclosing statement, so a whole statement can be re-read."""
    owner = {}
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.stmt):
            for child in ast.walk(stmt):
                owner.setdefault(id(child), stmt)
    return owner


def constant_is_always_rooted(tree: ast.AST, statement: ast.AST) -> bool:
    """Accept a named suffix only when every local load is inside a root helper.

    A declaration such as RECEIPT_PREFIX = 'd/public/receipts/' is not itself an S3
    address when its only use is media_paths.secure(f'{RECEIPT_PREFIX}...'). Any
    bare load, return, alias, or direct S3 use keeps the original check failing.
    """
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
        return False
    name = statement.targets[0].id
    parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    loads = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)]
    if not loads:
        return False
    for load in loads:
        node, rooted = load, False
        while id(node) in parents:
            node = parents[id(node)]
            if isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name) and function.value.id == "media_paths" and function.attr in {"secure", "dual_homed"}:
                    rooted = True
                break  # Do not assume an intervening function roots its output.
            if isinstance(node, ast.stmt):
                break
        if not rooted:
            return False
    return True


def check_keys_rooted(r: Result) -> None:
    print("\n2. every S3 key prefix is rooted in o/ or secure/")
    offenders: list[str] = []
    for p in handler_files():
        parsed = parse(p)
        if parsed is None:
            offenders.append(f"{p.relative_to(FUNCTIONS)} does not parse")
            continue
        tree, src, docstrings = parsed
        owner = enclosing_statements(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue  # prose, not a key
            key = node.value
            if not KEYISH_RE.match(key) or key.startswith((PUBLIC_ROOT, SECURE_ROOT)):
                continue
            stmt = owner.get(id(node))
            stmt_src = ast.get_source_segment(src, stmt) or "" if stmt else ""
            # Rooted at runtime by a media_paths call in the same statement, or used only
            # to CLASSIFY a legacy string rather than to address an object.
            if "media_paths." in stmt_src or ".startswith(" in stmt_src:
                continue
            if stmt is not None and constant_is_always_rooted(tree, stmt):
                continue
            offenders.append(f"{p.relative_to(FUNCTIONS)}:{node.lineno} {key}")
    r.add("no un-rooted key addresses an object", not offenders,
          "; ".join(offenders[:4]) if offenders else "all rooted")


def check_import_before_use(r: Result) -> None:
    print("\n3. media_paths is imported above its first MODULE-SCOPE use")
    offenders: list[str] = []
    for p in handler_files():
        parsed = parse(p)
        if parsed is None:
            continue
        tree, _src, _docstrings = parsed

        imp = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "lambda_utils" \
                    and any(a.name == "media_paths" for a in node.names):
                imp = node.lineno if imp is None else min(imp, node.lineno)

        # Only MODULE-SCOPE uses can raise at import time. A reference inside a function
        # body is resolved when that function is called, by which point the import has run
        # regardless of where it sits - so flagging those would be noise.
        module_scope_uses = []
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and node.id == "media_paths":
                    module_scope_uses.append(node.lineno)
        if not module_scope_uses:
            continue
        first = min(module_scope_uses)
        if imp is None or imp > first:
            where = f"import@{imp}" if imp else "NO IMPORT"
            offenders.append(f"{p.relative_to(FUNCTIONS)} {where} use@{first}")
    r.add("no module-scope NameError from import ordering", not offenders,
          "; ".join(offenders[:4]) if offenders else "ordering correct")


def check_edge_parity(r: Result) -> None:
    print("\n4. the edge gate refuses exactly media_paths.PRIVATE_DELIVERABLE_PREFIXES")
    import importlib.util

    def load(path: pathlib.Path, name: str):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # Both files are dependency-free at import, which is what lets this run in CI.
    paths = load(MEDIA_PATHS, "media_paths_parity")
    edge = load(FUNCTIONS / "edge" / "get-miss-redirect" / "handler.py", "edge_parity")
    expected = tuple(paths.PRIVATE_DELIVERABLE_PREFIXES)
    actual = tuple(getattr(edge, "PRIVATE_DELIVERABLE_PREFIXES", ()))
    r.add("edge PRIVATE_DELIVERABLE_PREFIXES matches media_paths", actual == expected,
          f"{len(expected)} prefixes" if actual == expected else
          f"only in media_paths: {sorted(set(expected) - set(actual))}; "
          f"only in edge: {sorted(set(actual) - set(expected))}")
    refused = [p for p in expected if not edge._is_denied("/" + p + "x")]
    r.add("edge refuses a key under every private prefix", not refused,
          "; ".join(refused) if refused else "all refused")


def check_live(r: Result) -> None:
    print("\n5. live AWS configuration")
    try:
        import boto3
    except ImportError:
        r.add("boto3 available", False, "pip install boto3")
        return

    lam = boto3.client("lambda", region_name="us-east-1")
    bad: list[str] = []
    checked = 0
    for page in lam.get_paginator("list_functions").paginate():
        for f in page["Functions"]:
            env = (f.get("Environment") or {}).get("Variables") or {}
            checked += 1
            for k, v in env.items():
                if not isinstance(v, str):
                    continue
                # Substring, not equality. A dead name is just as broken embedded in a
                # URL or a prefix as it is standing alone, and `CDN_DOMAIN` used to hold
                # `wecare-digital-get/<something>` rather than the bare host - equality
                # would have walked straight past it.
                for dead in DEAD_BUCKETS:
                    if dead in v:
                        bad.append(f"{f['FunctionName']}.{k} contains {dead}")
    r.add("no live env var names a dead bucket", not bad,
          "; ".join(bad[:4]) if bad else f"{checked} functions checked")

    s3 = boto3.client("s3", region_name="us-east-1")
    roots = {c["Prefix"] for c in s3.list_objects_v2(
        Bucket=BUCKET, Delimiter="/").get("CommonPrefixes", [])}
    r.add("bucket has exactly the two documented roots",
          roots == {PUBLIC_ROOT, SECURE_ROOT}, f"found {sorted(roots)}")

    # Both customer document prefixes deliberately sit below the otherwise public
    # deliverable subtree. The edge alone is not an adequate privacy control when
    # its live numbered version can lag behind GitHub. A targeted bucket-policy
    # Deny on CloudFront OAC must remain in place independently of rollout order.
    expected_private_oac_denies = {
        "DenyCloudFrontReadPrivateDropDocs": "secure/d/public/drop-docs/",
        "DenyCloudFrontReadPrivateVaultValut": "secure/d/public/valut/",
    }
    try:
        bucket_policy = json.loads(s3.get_bucket_policy(Bucket=BUCKET)["Policy"])
        statements = bucket_policy.get("Statement") or []
    except Exception as exc:  # noqa: BLE001
        r.add("private customer S3 OAC deny policy readable", False,
              type(exc).__name__)
    else:
        for sid, prefix in expected_private_oac_denies.items():
            allowed = [
                statement for statement in statements
                if statement.get("Sid") == sid
                and statement.get("Effect") == "Deny"
                and statement.get("Principal") == {"Service": "cloudfront.amazonaws.com"}
                and statement.get("Action") == "s3:GetObject"
                and statement.get("Resource") == f"arn:aws:s3:::{BUCKET}/{prefix}*"
            ]
            r.add(f"CloudFront OAC denied from private {prefix}", len(allowed) == 1,
                  f"policy {sid}" if allowed else "missing targeted Deny")

    # The legacy host is expected to be RETIRED. Both outcomes below are legitimate
    # states of the world, so neither is hardcoded as the pass condition - what is
    # asserted is that the distribution and DNS agree with each other, because a
    # half-retired host is the state that silently breaks media.
    cf = boto3.client("cloudfront")
    dist_present = True
    try:
        cfg = cf.get_distribution_config(Id=LEGACY_HOST_DISTRIBUTION)["DistributionConfig"]
        origin = cfg["Origins"]["Items"][0]
    except cf.exceptions.NoSuchDistribution:
        dist_present = False
    except Exception as exc:  # noqa: BLE001
        r.add("legacy host distribution state determinable", False, type(exc).__name__)
        return

    try:
        socket.getaddrinfo(LEGACY_HOST, 443)
        dns_present = True
    except socket.gaierror:
        dns_present = False

    if dist_present:
        # Still dual-homed. The original invariant applies: `o/` is what makes an object
        # reachable on both hosts, so the origin path must stay `/o` on this bucket.
        r.add("legacy host serves this bucket via origin path /o",
              origin["OriginPath"] == LEGACY_HOST_ORIGIN_PATH and BUCKET in origin["DomainName"],
              f"path={origin['OriginPath']!r} origin={origin['DomainName']}")
        r.add("legacy host resolves, matching its live distribution", dns_present,
              "DNS present" if dns_present else
              "distribution exists but DNS does not resolve - half-retired")
    else:
        # Retired. Assert the retirement is complete rather than partial: a DNS record
        # still pointing at a deleted distribution is a dangling alias.
        r.add("legacy host retired: distribution deleted", True,
              f"{LEGACY_HOST_DISTRIBUTION} absent, as expected since 2026-09-28")
        r.add("legacy host retired: DNS record also removed", not dns_present,
              "does not resolve" if not dns_present else
              f"{LEGACY_HOST} still resolves with no distribution behind it")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also check AWS configuration")
    args = ap.parse_args()

    if not MEDIA_PATHS.is_file():
        sys.exit(f"missing {MEDIA_PATHS}")

    print(f"media prefix verification - bucket {BUCKET}")
    r = Result()
    check_no_dead_buckets(r)
    check_keys_rooted(r)
    check_import_before_use(r)
    check_edge_parity(r)
    if args.live:
        check_live(r)
    else:
        print("\n5. live AWS configuration  (skipped, pass --live)")

    print(f"\n{r.passed} passed, {r.failed} failed")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
