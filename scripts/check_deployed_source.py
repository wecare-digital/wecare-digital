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
    MISSING  : file exists locally, absent from the artifact
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

Exit status is 1 when any compared file differs, so it can gate a release.
"""

from __future__ import annotations

import argparse
import hashlib
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

    def __init__(self, name: str, source, arcname_map, owner: str):
        self.name = name
        self.source = source
        self.arcname_map = arcname_map
        self.owner = owner
        self.standalone = True
        self.extra_dirs: list[str] = []
        self.extra_files: list[str] = []
        self.provisioned_by = ""


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
        ),
    }


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
            if info.is_dir():
                continue
            parts = set(pathlib.PurePosixPath(info.filename).parts)
            if parts & SKIP_PARTS or any(p.endswith(tuple(SKIP_PARTS)) for p in parts):
                continue
            if not info.filename.endswith(COMPARE_SUFFIXES):
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
        row["error"] = exc.response["Error"]["Code"]
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
    for arcname, blob in sorted(entries.items()):
        if only_file and not arcname.endswith(only_file):
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
    row["compared"] = compared
    row["differs"] = differs
    row["extra_in_artifact"] = extra
    row["missing_from_artifact"] = missing
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
        has_diff = bool(row.get("differs"))
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
            for d in row["differs"]:
                print(f"      DIFFERS  {d['path']}  "
                      f"deployed {d['deployed_bytes']}B/{d['deployed_sha256']} "
                      f"vs local {d['local_bytes']}B/{d['local_sha256']}")
        elif row.get("compared"):
            print(f"      OK — {row['compared']} file(s) byte-identical to the local tree")
        for x in row.get("extra_in_artifact", [])[:5]:
            print(f"      EXTRA    {x}  (in artifact, not in the tree)")

    print(f"\nfunctions checked={len(rows)}  with stale file(s)={drifted}")
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(rows, indent=2) + "\n")
        print(f"wrote {args.json_out}")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
