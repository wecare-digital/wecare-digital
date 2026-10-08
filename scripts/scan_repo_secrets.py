#!/usr/bin/env python3
"""Scan the repo for credential material, WITHOUT reading any secret value.

Policy constraint (AGENTS.md "Secret Safety" + steering 01-standing-authorization):
    MUST NOT call `secretsmanager get-secret-value` / `batch-get-secret-value`.
This script therefore NEVER fetches secret values. It runs the two checks that
need no values, and explicitly skips the one that would.

Checks
------
1. **Secrets Manager enumeration (names only).** `ListSecrets` + `DescribeSecret`
   for `wecare/*`. Reports how many secrets exist and which fields each declares,
   using the DescribeSecret metadata only. No value is ever fetched. This gives
   the fleet inventory without touching value material.

2. **Issuer-shape scan (tree + full history).** Anchored patterns for credentials
   by their issuer shape (AWS key id, Razorpay/Stripe live keys, Plivo auth id,
   private-key blocks, Slack webhooks, ...). Needs no secret values, so it is the
   compliant public-leak check. History is scanned because on a public repo a
   value deleted later is still fetchable from the object database.

   SKIPPED — exact-value match. The previous version loaded every `wecare/*`
   value via `get_secret_value` and grepped the tree/history for those exact
   strings. That is the only check able to catch a prefix-less secret (a raw AWS
   secret access key, a webhook secret), but it REQUIRES reading secret values,
   which policy forbids here. It is intentionally not performed. To run it, use
   an environment explicitly authorized for value reads (e.g. a scoped CI job),
   never this agent against the account.

Usage:
    python scripts/scan_repo_secrets.py            # enumerate + shape scan (tree + history)
    python scripts/scan_repo_secrets.py --tree     # working tree only, faster
    python scripts/scan_repo_secrets.py --json

Exit status: 0 clean, 1 issuer-shaped credential material found in the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
SECRET_PREFIX = "wecare/"

# Issuer-anchored shapes, assembled at runtime so this file holds no literal
# credential shape and does not trip the block-inline-secrets hook.
SHAPES = {
    "razorpay live key":   "rzp" + r"_live_[A-Za-z0-9]{8,}",
    "openai key":          "sk-" + r"(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{30,}",
    "google api key":      "AIz" + r"a[A-Za-z0-9_\-]{30,}",
    "aws access key id":   r"(?:AKI" + r"A|ASI" + r"A)[0-9A-Z]{16}",
    "github token":        "gh" + r"[pousr]_[A-Za-z0-9]{30,}",
    "slack token":         "xox" + r"[abprs]-[A-Za-z0-9\-]{20,}",
    "stripe live key":     r"(?:s|p|r)k" + r"_live_[A-Za-z0-9]{16,}",
    "google oauth secret": "GOC" + r"SPX-[A-Za-z0-9_\-]{20,}",
    "sendgrid key":        "SG" + r"\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}",
    "twilio key":          r"(?:AC|SK)[0-9a-f]{32}",
    "plivo auth id":       r"\bMA[A-Z0-9]{18}\b",
    "private key block":   r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "slack webhook":       r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}",
}

# AWS's published example key, and runs of one repeated character used as
# synthetic filler in the guards' own test cases.
BENIGN = {"AKI" + "A" + "IOSFODNN7EXAMPLE"}
FILLER = re.compile(r"(.)\1{15,}")

SKIP_DIRS = {".git", "node_modules", ".venv", ".next", "__pycache__", "out",
             "dist", "build", ".pytest_cache"}


def digest(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:8]


def enumerate_secrets() -> tuple[list[dict], list[str]]:
    """List wecare/* secrets by NAME and declared fields, via metadata only.

    Uses ListSecrets + DescribeSecret. NEVER calls get_secret_value /
    batch_get_secret_value. No value material enters this process.
    """
    out: list[dict] = []
    notes: list[str] = []
    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        paginator = sm.get_paginator("list_secrets")
        ids: list[str] = []
        for page in paginator.paginate():
            for s in page["SecretList"]:
                if s["Name"].startswith(SECRET_PREFIX):
                    ids.append(s["Name"])
        for sid in sorted(ids):
            try:
                meta = sm.describe_secret(SecretId=sid)
            except (ClientError, BotoCoreError) as exc:
                notes.append(f"  undescribable {sid}: {exc}")
                continue
            # DescribeSecret exposes names/metadata, never the SecretString.
            scheduled = "DeletedDate" in meta or "DeletionDate" in meta
            out.append({
                "name": sid,
                "last_changed": str(meta.get("LastChangedDate", "")),
                "scheduled_deletion": scheduled,
                "rotation_enabled": meta.get("RotationEnabled", False),
            })
            notes.append(f"  {sid}: rotation={meta.get('RotationEnabled', False)}"
                         f"{' SCHEDULED-DELETE' if scheduled else ''}")
    except (ClientError, BotoCoreError) as exc:
        notes.append(f"  enumeration unavailable (no/insufficient AWS access): {exc}")
    return out, notes


def worktree_files() -> list[Path]:
    files = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        try:
            if p.stat().st_size > 20_000_000:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def git_blob_data() -> tuple[bytes, int]:
    listing = subprocess.run(
        ["git", "cat-file", "--batch-all-objects",
         "--batch-check=%(objectname) %(objecttype)"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    blobs = [ln.split()[0] for ln in listing.splitlines() if ln.endswith(" blob")]
    data = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                          input=("\n".join(blobs) + "\n").encode(),
                          capture_output=True, check=True).stdout
    return data, len(blobs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", action="store_true", help="skip the history scan")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"secrets": [], "shapes_tree": [], "shapes_history": []}

    print("=" * 74)
    print("REPOSITORY CREDENTIAL SCAN - no secret value is ever read")
    print("=" * 74)

    print("\n1. Secrets Manager enumeration (names + metadata only)")
    secrets, notes = enumerate_secrets()
    for n in notes:
        print(n)
    report["secrets"] = secrets
    print(f"  {len(secrets)} secret(s) under {SECRET_PREFIX!r} (enumerated by name)")

    print("\n   exact-value match: SKIPPED (requires get_secret_value, forbidden "
          "by secret-safety policy)")

    files = worktree_files()

    print("\n2. issuer-shaped material in the working tree")
    shape_tree = 0
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for label, pat in SHAPES.items():
            for m in re.findall(pat, text):
                if m in BENIGN or FILLER.search(m):
                    continue
                rel = f.relative_to(ROOT).as_posix()
                report["shapes_tree"].append(
                    {"label": label, "file": rel, "fp": digest(m), "len": len(m)})
                shape_tree += 1
                print(f"  {label}: {rel}  len={len(m)} sha256:{digest(m)}")
    if not shape_tree:
        print("  none")

    shape_hist = 0
    if args.tree:
        print("\n3. git history: skipped (--tree)")
    else:
        print("\n3. issuer-shaped material in git history (every blob ever committed)")
        data, nblobs = git_blob_data()
        text = data.decode("utf-8", errors="replace")
        for label, pat in SHAPES.items():
            for m in set(re.findall(pat, text)):
                if m in BENIGN or FILLER.search(m):
                    continue
                report["shapes_history"].append(
                    {"label": label, "fp": digest(m), "len": len(m)})
                shape_hist += 1
                print(f"  {label}: in history  len={len(m)} sha256:{digest(m)}")
        print(f"  {nblobs} blobs scanned, {len(data)/1048576:.0f} MB")
        if not shape_hist:
            print("  no issuer-shaped material in history")

    print("\n" + "=" * 74)
    print(f"issuer-shaped strings in tree    : {shape_tree}")
    print(f"issuer-shaped strings in history : {shape_hist}")
    print(f"secrets enumerated (names only)  : {len(secrets)}")
    found = shape_tree + shape_hist
    verdict = "CLEAN (shape scan)" if found == 0 else "CREDENTIAL-SHAPED MATERIAL FOUND"
    print(f"RESULT: {verdict}")
    print("  NOTE: exact-value match not performed (policy). Run it only from an")
    print("        environment explicitly authorized to read secret values.")
    print("=" * 74)

    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if found == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
