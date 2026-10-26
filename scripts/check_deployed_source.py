#!/usr/bin/env python3
"""Prove, file by file, what source is actually running behind each `live` alias.

Why this exists
---------------
`deploy_all_lambdas.py --dry-run` compares the whole packaged zip's sha256 to the
live `CodeSha256`. That is the right check before uploading, but it is useless as
a *drift report*, because every one of the 62 zips embeds
`amplify/functions/shared/lambda_utils/`. One commit to a shared module changes
every package hash at once. On 2026-09-26 the dry run reported `would_update=56`
including functions nobody had touched in weeks, which says "a shared module
moved", not "56 functions are running stale code".

The execution brief requires stronger evidence than that:

    DEPLOYED: immutable deployed artifact is proven by version/hash/job/resource
    readback.

So this downloads the artifact the `live` alias actually points at, opens it, and
compares **each file inside it** against the file in the local working tree. The
output answers the question that matters -- "is the fix I pushed in the thing
production is executing?" -- for a named file, not for an opaque aggregate hash.

What it reports per function
----------------------------
    alias version, the version's CodeSha256, LastModified
    DIFFERS  : file exists in both, contents differ  (deployed code is stale)
    MISSING  : a file the function's own packager ships, absent from the artifact. The
               list comes from that packager (`deploy_all_lambdas.build_zip`, or the
               delegated script's builder), so the two cannot disagree.
    EXTRA    : file in the artifact with no local counterpart (deleted since)
    $LATEST vs alias: whether unpublished code is sitting in front of the alias

Only `.py` files are compared; `.json` flow definitions are compared too because
`deploy_all_lambdas.py` ships `flows/*.json` and a past PowerShell script silently
dropped them.

Reads only. It calls GetFunction / GetAlias and downloads the presigned code URL
that AWS returns for our own artifact. Environment variables are NOT in the zip,
so no configuration value -- and therefore no secret -- is fetched or printed.

Usage
-----
    .venv/bin/python scripts/check_deployed_source.py                    # whole fleet
    .venv/bin/python scripts/check_deployed_source.py wecare-contacts    # some
    .venv/bin/python scripts/check_deployed_source.py --file lambda_utils/wa_internal_event.py
    .venv/bin/python scripts/check_deployed_source.py --json out.json

A full-fleet run also lists every function in the account that nothing here maps to
source (UNTRACKED), so "checked=N" cannot pass for complete coverage while a function is
skipped. A spec whose function is not created yet is reported as awaiting its
provisioner, the way `deploy_all_lambdas.py` reports it, rather than as an error.

Exit status is 1 when any compared file differs, so it can gate a release.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import pathlib
import sys
import urllib.request
import zipfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGION = "us-east-1"
CFG = Config(retries={"max_attempts": 6, "mode": "adaptive"})

COMPARE_SUFFIXES = (".py", ".json")
# Never meaningful to compare: bytecode, and the packaging of third-party wheels.
SKIP_PARTS = {"__pycache__", "dist-info", "egg-info"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DelegatedSpec:
    """A stand-in Spec for a function `deploy_all_lambdas.py` does not own.

    THE BLIND SPOT THIS CLOSES. This script derives its fleet from `dal.SPECS`, so the two
    functions in `dal.DELEGATED` were invisible to it: `check_deployed_source.py` reported
    "functions checked=62" against a fleet of 66 and nobody noticed the four missing, because
    62 of 62 passing reads exactly like complete coverage.

    Those two are the ones least covered by anything else. `wecare-seo-tools` is the hottest
    function in the account and has NO `live` alias, so `$LATEST` reaches production the
    instant it is uploaded - there is no alias step in which to catch a bad deploy.
    `wecare-mcp` is a public unauthenticated endpoint.

    Each carries a non-standard in-zip layout, which is precisely why it is delegated, so the
    mapping from archive path back to the working tree has to be stated per function rather
    than derived. `arcname_map` is an ordered list of (archive prefix, local base) tried
    longest-prefix-first by `local_bytes`.
    """

    def __init__(self, name: str, source, arcname_map, owner: str, *,
                 expected=None, only=(), edge: bool = False):
        self.name = name
        self.source = source
        self.arcname_map = arcname_map
        self.owner = owner
        self.standalone = True
        self.extra_dirs: list[str] = []
        self.extra_files: list[str] = []
        self.provisioned_by = ""
        # What the owning script's packager ships: a zero-argument callable returning the
        # archive names, or the names themselves. A shipped file absent from the artifact is
        # drift as much as a stale copy is.
        self.expected = expected
        # Archive paths that come from this repository. Empty means every file does; a
        # package that vendors its own SDK names its few source files instead.
        self.only = set(only)
        # Lambda@Edge: CloudFront runs a numbered version, never `live` or $LATEST.
        self.edge = edge


def delegated_specs(dal) -> dict:
    functions = dal.FUNCTIONS
    return {
        # Shim at the zip root importing operations/seo-tools, with lambda_utils under
        # shared/ rather than at the top level. deploy_seo_tools.py owns the packaging.
        "wecare-seo-tools": DelegatedSpec(
            "wecare-seo-tools",
            functions / "operations" / "seo-tools",
            [
                ("shared/lambda_utils/", dal.LAMBDA_UTILS),
                ("shared/", dal.SHARED),
                ("operations/seo-tools/", functions / "operations" / "seo-tools"),
                ("seo_tools_handler.py", functions),
            ],
            "scripts/deploy_seo_tools.py",
            expected=packaged_by("deploy_seo_tools", "package"),
        ),
        # handler.py plus config/public-pages.json copied in beside it. The catalogue is
        # the reason this cannot be a normal Spec: extra_files resolves relative to the
        # function directory and is skipped entirely for a standalone spec.
        "wecare-mcp": DelegatedSpec(
            "wecare-mcp",
            functions / "ai" / "mcp",
            [
                ("public-pages.json", ROOT / "config"),
                ("handler.py", functions / "ai" / "mcp"),
            ],
            "scripts/deploy_mcp_server.py",
            expected=packaged_by("deploy_mcp_server", "package"),
        ),
        # The same blind spot again, measured 2026-10-25: "checked=68" against 74 functions,
        # while wecare-native-catalog-admin ran 25 shared modules from 2026-10-23 (its auth
        # middleware among them) and nothing reported it. These are the rest of
        # dal.DELEGATED plus the functions owned by their own provisioners.
        "wecare-blog-public": DelegatedSpec(
            "wecare-blog-public",
            functions / "operations" / "blog-public",
            [],
            "scripts/build_blog_public.py",
            expected=packaged_by("build_blog_public", "package"),
        ),
        # Its pinned SDK is bundled beside three source files and one config file; only
        # those four come from this repository. Its builder needs the installed SDK, so the
        # four are named here rather than read from it.
        "wecare-workspace-mcp": DelegatedSpec(
            "wecare-workspace-mcp",
            functions / "ai" / "workspace-mcp",
            [("workspace-mcp.json", ROOT / "config")],
            "scripts/build_workspace_mcp.py",
            expected=WORKSPACE_MCP_SOURCES,
            only=WORKSPACE_MCP_SOURCES,
        ),
        "wecare-native-catalog-admin": DelegatedSpec(
            "wecare-native-catalog-admin",
            functions / "ecommerce" / "native-catalog-admin",
            [],
            "scripts/provision_native_catalog_api.py",
            expected=packaged_by("provision_native_catalog_api", "zip_code"),
        ),
        "wecare-catalog-media": DelegatedSpec(
            "wecare-catalog-media",
            functions / "ecommerce" / "catalog-media",
            [],
            "scripts/provision_catalog_media.py",
            expected=packaged_by("provision_catalog_media", "zip_code"),
        ),
        # A CloudFront origin-response trigger with no packaging script: one handler file.
        # Compared at the version the cache behaviour names, which is what production executes.
        "wecare-get-miss-redirect": DelegatedSpec(
            "wecare-get-miss-redirect",
            functions / "edge" / "get-miss-redirect",
            [],
            "CloudFront Lambda@Edge association",
            expected=("handler.py",),
            edge=True,
        ),
        # Deployed by its own CloudFormation stack with the code inline (`ZipFile`), which
        # CloudFormation packages as `index.py`. The directory holds the template and that code.
        "wecare-customer-commerce-mcp": DelegatedSpec(
            "wecare-customer-commerce-mcp",
            functions / "ai" / "customer-commerce-mcp",
            [],
            "CloudFormation stack wecare-customer-commerce-mcp",
            expected=("index.py",),
        ),
    }


WORKSPACE_MCP_SOURCES = ("handler.py", "provider_adapters.py", "chat_oauth.py",
                         "workspace-mcp.json")


def packaged_by(module: str, builder: str):
    """The archive names a packaging script in scripts/ builds, read from its own builder.

    Lazy: the script is imported only when its function is checked. Each named builder is a
    pure function returning zip bytes; none makes an AWS call.
    """
    def names() -> set[str]:
        zip_bytes = getattr(importlib.import_module(module), builder)()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return {info.filename for info in zf.infolist() if not info.is_dir()}
    return names


def comparable(arcname: str) -> bool:
    """The archive paths this script compares: source and config, not bytecode or wheels."""
    parts = set(pathlib.PurePosixPath(arcname).parts)
    if parts & SKIP_PARTS or any(p.endswith(tuple(SKIP_PARTS)) for p in parts):
        return False
    return arcname.endswith(COMPARE_SUFFIXES)


def expected_names(dal, spec) -> set[str] | None:
    """What the function's own packager ships, or None when that is not known here."""
    if isinstance(spec, DelegatedSpec):
        if spec.expected is None:
            return None
        names = set(spec.expected() if callable(spec.expected) else spec.expected)
    else:
        names = set(dal.build_zip(spec)[1])
    return {n for n in names if comparable(n)}


def edge_versions(function_name: str) -> list[str]:
    """The versions of a Lambda@Edge function that CloudFront cache behaviours name."""
    cloudfront = boto3.client("cloudfront", config=CFG)
    found = set()
    for page in cloudfront.get_paginator("list_distributions").paginate():
        for dist in (page.get("DistributionList") or {}).get("Items") or []:
            behaviours = [dist.get("DefaultCacheBehavior") or {}]
            behaviours += (dist.get("CacheBehaviors") or {}).get("Items") or []
            for behaviour in behaviours:
                for assoc in (behaviour.get("LambdaFunctionAssociations") or {}).get("Items") or []:
                    base, _, version = assoc.get("LambdaFunctionARN", "").rpartition(":")
                    if base.endswith(f":function:{function_name}"):
                        found.add(version)
    return sorted(found)


def account_functions(lam) -> list[str]:
    return [fn["FunctionName"]
            for page in lam.get_paginator("list_functions").paginate()
            for fn in page.get("Functions", [])]


def load_specs():
    """Reuse deploy_all_lambdas' own map so the two can never disagree.

    Then add the delegated functions, so "checked=N" describes the whole fleet rather than
    only the part one script happens to own.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_all_lambdas as dal  # noqa: PLC0415

    specs = {s.name: s for s in dal.SPECS}
    for name, spec in delegated_specs(dal).items():
        if name in specs:
            # Already a real Spec, so deploy_all_lambdas took ownership back. Prefer it and
            # say so, rather than silently shadowing it with the stand-in.
            print(f"note: {name} is now a real Spec; ignoring the delegated stand-in")
            continue
        specs[name] = spec
    return dal, specs


def artifact_entries(zip_bytes: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not comparable(info.filename):
                continue
            out[info.filename] = zf.read(info)
    return out


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - AWS presigned
        return resp.read()


def local_bytes(dal, spec, arcname: str) -> bytes | None:
    """Map an in-archive path back to the working tree."""
    # A delegated function states its own mapping, because its zip layout is the reason it
    # is delegated. Longest prefix first, so `shared/lambda_utils/` wins over `shared/`.
    for prefix, base in sorted(getattr(spec, "arcname_map", []),
                               key=lambda pair: -len(pair[0])):
        if arcname == prefix:
            cand = pathlib.Path(base) / pathlib.PurePosixPath(arcname).name
            return cand.read_bytes() if cand.is_file() else None
        if arcname.startswith(prefix):
            cand = pathlib.Path(base) / arcname[len(prefix):]
            return cand.read_bytes() if cand.is_file() else None

    # external_files map a source RELATIVE TO amplify/functions onto a destination name in the
    # zip (`(source_rel, dest_rel)`), so a dest like `invoice_engine.py` resolves to its single
    # source `payments/invoice-engine/handler.py` rather than to a copy beside the handler. This
    # is why the reverse map must consult them: the invoice engine ships from one source now.
    for source_rel, dest_rel in getattr(spec, "external_files", []):
        if arcname == dest_rel:
            cand = dal.FUNCTIONS / source_rel
            return cand.read_bytes() if cand.is_file() else None
    p = pathlib.PurePosixPath(arcname)
    if p.parts[0] == "lambda_utils":
        cand = dal.LAMBDA_UTILS.joinpath(*p.parts[1:])
    elif arcname == "static_knowledge_base.py":
        cand = dal.STATIC_KB
    else:
        cand = spec.source.joinpath(*p.parts)
    if cand.is_file():
        return cand.read_bytes()
    # Some specs pull extra dirs in from shared/.
    alt = dal.SHARED.joinpath(*p.parts)
    if alt.is_file():
        return alt.read_bytes()
    return None


def check_function(lam, dal, spec, only_file: str | None):
    name = spec.name
    row: dict = {"function": name}
    if getattr(spec, "edge", False):
        versions = edge_versions(name)
        if len(versions) != 1:
            row["error"] = (f"CloudFront names {len(versions)} versions: {versions}"
                            if versions else "no CloudFront association")
            return row
        row["alias_version"] = versions[0]
        row["note"] = "Lambda@Edge — compared at the version CloudFront runs"
    else:
        try:
            alias = lam.get_alias(FunctionName=name, Name="live")
            row["alias_version"] = alias["FunctionVersion"]
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                row["alias_version"] = None
                row["note"] = "no `live` alias — $LATEST reaches production directly"
            else:
                row["error"] = code
                return row

    qualifier = row.get("alias_version") or "$LATEST"
    try:
        got = lam.get_function(FunctionName=name, Qualifier=qualifier)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceNotFoundException" and getattr(spec, "provisioned_by", ""):
            # Not created yet. deploy_all_lambdas reports the same state as "awaiting
            # provisioning" rather than a failure; reporting it as an ERROR here taught readers
            # to skip ERROR lines.
            row["note"] = f"not created yet — awaiting `{spec.provisioned_by}`"
            row["awaiting_provisioning"] = True
            return row
        row["error"] = code
        return row

    cfgv = got["Configuration"]
    row["deployed_code_sha256"] = cfgv["CodeSha256"]
    row["deployed_last_modified"] = cfgv["LastModified"]
    row["runtime"] = cfgv.get("Runtime")
    row["package_type"] = cfgv.get("PackageType")
    if cfgv.get("PackageType") != "Zip":
        row["note"] = f"PackageType={cfgv.get('PackageType')} — not comparable here"
        return row

    # Is unpublished code sitting in front of the alias?
    try:
        latest = lam.get_function_configuration(FunctionName=name)
        row["latest_code_sha256"] = latest["CodeSha256"]
        row["latest_differs_from_alias"] = (
            latest["CodeSha256"] != cfgv["CodeSha256"]
        )
    except ClientError:
        pass

    try:
        expected = expected_names(dal, spec)
    except (OSError, RuntimeError, ImportError, AttributeError, zipfile.BadZipFile) as exc:
        # The repository cannot build this package, so a deploy from it would fail too.
        row["error"] = f"cannot build the package locally: {type(exc).__name__}: {exc}"
        return row

    url = got.get("Code", {}).get("Location")
    if not url:
        row["error"] = "no code location returned"
        return row
    entries = artifact_entries(download(url))
    row["artifact_file_count"] = len(entries)

    differs: list[dict] = []
    missing: list[str] = []
    extra: list[str] = []
    compared = 0
    only = getattr(spec, "only", set())
    vendored = 0
    for arcname, blob in sorted(entries.items()):
        if only_file and not arcname.endswith(only_file):
            continue
        if only and arcname not in only:
            vendored += 1  # a bundled third-party file, not source from this repository
            continue
        local = local_bytes(dal, spec, arcname)
        if local is None:
            extra.append(arcname)
            continue
        compared += 1
        if sha(local) != sha(blob):
            differs.append({
                "path": arcname,
                "deployed_sha256": sha(blob)[:16],
                "local_sha256": sha(local)[:16],
                "deployed_bytes": len(blob),
                "local_bytes": len(local),
            })
    # A file the packager ships that the artifact lacks: a stale artifact can miss a new module
    # as easily as hold an old copy of one.
    if expected is not None:
        missing = sorted(n for n in expected - set(entries)
                         if not only_file or n.endswith(only_file))
    row["compared"] = compared
    row["differs"] = differs
    row["extra_in_artifact"] = extra
    row["missing_from_artifact"] = missing
    if vendored:
        row["vendored_not_compared"] = vendored
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("functions", nargs="*", help="function names; default is every spec")
    ap.add_argument("--file", help="only compare archive paths ending with this")
    ap.add_argument("--json", dest="json_out", help="also write the full result here")
    ap.add_argument("--quiet-clean", action="store_true",
                    help="only print functions with a difference")
    args = ap.parse_args()

    dal, specs = load_specs()
    targets = args.functions or list(specs)
    unknown = [t for t in targets if t not in specs]
    if unknown:
        print("unknown function(s): " + ", ".join(unknown), file=sys.stderr)
        print("known: " + ", ".join(sorted(specs)), file=sys.stderr)
        return 2

    lam = boto3.client("lambda", region_name=REGION, config=CFG)
    rows = []
    drifted = 0
    print(f"region={REGION} targets={len(targets)} "
          f"comparing={'all files' if not args.file else args.file}")
    for t in targets:
        row = check_function(lam, dal, specs[t], args.file)
        rows.append(row)
        has_diff = bool(row.get("differs") or row.get("missing_from_artifact"))
        if has_diff:
            drifted += 1
        if args.quiet_clean and not has_diff and not row.get("error"):
            continue
        ver = row.get("alias_version") or "$LATEST"
        print(f"  {row['function']}  alias=live -> v{ver}  "
              f"sha={(row.get('deployed_code_sha256') or '?')[:12]}...  "
              f"modified={row.get('deployed_last_modified')}")
        if row.get("error"):
            print(f"      ERROR {row['error']}")
            continue
        if row.get("note"):
            print(f"      note: {row['note']}")
        if row.get("latest_differs_from_alias"):
            print("      $LATEST differs from the alias — unpublished code is not live")
        if has_diff:
            for d in row.get("differs", []):
                print(f"      DIFFERS  {d['path']}  "
                      f"deployed {d['deployed_bytes']}B/{d['deployed_sha256']} "
                      f"vs local {d['local_bytes']}B/{d['local_sha256']}")
        elif row.get("compared"):
            print(f"      OK — {row['compared']} file(s) byte-identical to the local tree")
        for x in row.get("missing_from_artifact", []):
            print(f"      MISSING  {x}  (in the tree, not in the artifact)")
        for x in row.get("extra_in_artifact", [])[:5]:
            print(f"      EXTRA    {x}  (in artifact, not in the tree)")

    awaiting = sum(1 for r in rows if r.get("awaiting_provisioning"))
    untracked: list[str] = []
    if not args.functions:
        # Only a full-fleet run can say what it did NOT cover.
        accounted = set(specs) | set(getattr(dal, "SKIPPED", {}))
        untracked = sorted(set(account_functions(lam)) - accounted)
        for name in untracked:
            print(f"  UNTRACKED {name}  in the account, but nothing in this repository maps it "
                  "to source")
    print(f"\nfunctions checked={len(rows)}  with stale file(s)={drifted}  "
          f"awaiting provisioning={awaiting}  untracked={len(untracked)}")
    rows.extend({"function": name, "untracked": True} for name in untracked)
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
        print(f"wrote {args.json_out}")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
