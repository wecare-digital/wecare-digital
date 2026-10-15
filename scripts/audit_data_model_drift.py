#!/usr/bin/env python3
"""Find DynamoDB table names referenced in code that do not exist in the account.

Why this exists
---------------
On 2026-09-21, Phase 0 discovery found two stores referenced by code but absent
from the account:

  stack-wecare-digital-PstnNotificationDelivery   named by lambda_utils/pstn/claims.py
  stack-wecare-digital-RcsMessagesTable           the RCS_TABLE default in three handlers

Nothing caught either, because no check compares the table names the code will
actually pass to DynamoDB against the tables that exist. A wrong name fails only
when its code path first runs, which for a feature behind a disabled flag can be
months after the change that caused it.

What this does and does not compare
-----------------------------------
It compares **exact table-name literals found in Python source** with
`ListTables`. That is a fact on both sides.

It deliberately does NOT try to map Amplify model names in
`amplify/data/consumer.ts` to physical tables. An earlier version of this script
assumed `Model` -> `stack-wecare-digital-Model` and produced 61 false positives:
the declared models are singular (`Contact`, `Message`) while the live tables are
`ContactsTable`, `MessagesTable`, and `backend.ts` resolves them indirectly through
`backend.data.resources.cfnResources.amplifyDynamoDbTables[modelName]`. The two
naming worlds do not line up, and guessing a convention produced noise rather than
signal. That mismatch is itself worth understanding - see
`docs/execution/data-store-inventory.md` - but it is not something this script can
assert.

    python scripts/audit_data_model_drift.py
    python scripts/audit_data_model_drift.py --json
    python scripts/audit_data_model_drift.py --gate   # exit 1 on a missing table

Exit codes
----------
    0  every referenced table exists, or report mode
    1  at least one referenced table is absent (only with --gate)
    2  could not query AWS
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
REPO = pathlib.Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO / "amplify" / "functions", REPO / "scripts"]

# Table-name literals in this codebase are all prefixed by the stack name.
NAME_RE = re.compile(r"['\"](stack-wecare-[A-Za-z0-9_.-]+)['\"]")

# Referenced-but-absent names that are known and accepted, with the reason.
ACCEPTED_ABSENT: dict[str, str] = {
    "stack-wecare-digital-RcsMessagesTable":
        "legacy RCS store; all writes stopped in the Phase 4 migration and the "
        "canonical MessagesTable is the sole store. The RCS_TABLE constants that "
        "named it were removed on 2026-09-21; kept here so a reintroduction is "
        "still reported rather than silently accepted.",

    # NOTIF-STORE-004, cleared 2026-09-24. The other findings in that set were fixed by
    # correcting or deleting the name: three dead SmsAwsTable constants plus a
    # cleanup-registry entry that raised ResourceNotFound on every run, and a Lambda name
    # written with the table prefix so that every invoke using its default failed.
    #
    # Stores deleted with a provider retirement are deliberately NOT listed here. No code
    # names them any more, so a reintroduced name is reported MISSING like any other -
    # an allowance for a retired store would only keep its name alive in the gate.
    "stack-wecare-digital-SystemConfig":
        "Not a read. It is an entry in system-cleanup's PROTECTED_TABLES deny-list, "
        "alongside the correctly-named SystemConfigTable. A protection entry for a "
        "table that does not exist protects nothing and costs nothing, and would "
        "cover a table created under the short name later. Deliberately kept as "
        "defensive breadth rather than deleted.",
}


def referenced_tables() -> dict[str, list[str]]:
    """Table name -> sorted list of repo-relative files that name it."""
    found: dict[str, set[str]] = {}
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            for name in NAME_RE.findall(text):
                found.setdefault(name, set()).add(
                    str(path.relative_to(REPO)))
    return {k: sorted(v) for k, v in sorted(found.items())}


def live_tables() -> set[str]:
    ddb = boto3.client("dynamodb", region_name=REGION)
    names: set[str] = set()
    token = None
    while True:
        kw = {"Limit": 100}
        if token:
            kw["ExclusiveStartTableName"] = token
        r = ddb.list_tables(**kw)
        names |= set(r.get("TableNames", []))
        token = r.get("LastEvaluatedTableName")
        if not token:
            return names


def live_queues() -> set[str]:
    sqs = boto3.client("sqs", region_name=REGION)
    urls = sqs.list_queues().get("QueueUrls", []) or []
    return {u.rsplit("/", 1)[-1] for u in urls}


def live_functions() -> set[str]:
    lam = boto3.client("lambda", region_name=REGION)
    names: set[str] = set()
    token = None
    while True:
        kw = {"MaxItems": 100}
        if token:
            kw["Marker"] = token
        r = lam.list_functions(**kw)
        names |= {f["FunctionName"] for f in r["Functions"]}
        token = r.get("NextMarker")
        if not token:
            return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 if a referenced table does not exist")
    args = ap.parse_args()

    try:
        tables = live_tables()
        queues = live_queues()
        functions = live_functions()
    except (ClientError, BotoCoreError) as exc:
        print(f"could not read AWS: {type(exc).__name__}", file=sys.stderr)
        return 2

    refs = referenced_tables()

    # The `stack-wecare-` prefix is shared by tables, SQS queues and Lambda
    # functions, and the scan is textual, so classify each literal against the
    # live inventories before calling anything missing. Without this the report
    # named four SQS queues and two Lambdas as absent tables, which is the kind
    # of noise that gets an audit ignored.
    missing, accepted, other = {}, {}, {}
    for name, files in refs.items():
        if name in tables:
            continue
        if name in queues:
            other[name] = ("sqs queue", files)
            continue
        if name in functions:
            other[name] = ("lambda function", files)
            continue
        if name.rstrip("-") == "stack-wecare-digital":
            other[name] = ("name prefix, not a resource", files)
            continue
        if name in ACCEPTED_ABSENT:
            accepted[name] = files
            continue
        missing[name] = files

    unreferenced = sorted(t for t in tables if t not in refs)

    report = {
        "region": REGION,
        "liveTables": len(tables),
        "referencedNames": len(refs),
        "MISSING": {n: {"files": f} for n, f in missing.items()},
        "ACCEPTED_ABSENT": sorted(accepted),
        "NOT_A_TABLE": {n: {"kind": k, "files": f} for n, (k, f) in other.items()},
        "LIVE_BUT_UNREFERENCED": unreferenced,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if (missing and args.gate) else 0

    print(f"live DynamoDB tables         : {len(tables)}")
    print(f"live SQS queues              : {len(queues)}")
    print(f"live Lambda functions        : {len(functions)}")
    print(f"stack-prefixed names in src  : {len(refs)}")
    print(f"  of which not tables        : {len(other)} "
          f"(queues, functions, bare prefixes)\n")

    print(f"MISSING - named by code, absent from the account : {len(missing)}")
    for name, files in missing.items():
        print(f"  {name}")
        for f in files:
            print(f"      {f}")
    if not missing:
        print("  (none)")
    print()

    print(f"ACCEPTED_ABSENT - known and justified : {len(accepted)}")
    for name in sorted(accepted):
        print(f"  {name}")
        print(f"      {ACCEPTED_ABSENT[name]}")
    print()

    print(f"LIVE_BUT_UNREFERENCED - table exists, no Python names it : "
          f"{len(unreferenced)}")
    for t in unreferenced:
        print(f"  {t}")
    print("\n  Not necessarily wrong: a table may be reached through an env var "
          "with no literal default, or written only by the frontend data layer. "
          "It does mean the name cannot be traced from Python source.")

    if missing:
        print("\nA referenced table that does not exist is a latent "
              "ResourceNotFoundException. Fix the name, create the table, or "
              "record it in ACCEPTED_ABSENT with a reason.")

    return 1 if (missing and args.gate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
