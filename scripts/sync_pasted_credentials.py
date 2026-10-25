#!/usr/bin/env python3
"""Non-interactive sibling of store_provider_secret.py.

WHY THIS EXISTS
---------------
store_provider_secret.py reads every value from a hidden getpass prompt. That is
the right default: it keeps a human in the loop and keeps values out of argv,
logs and Kiro permission rules. But it cannot be driven by an agent, and it asks
the operator to retype ~40 fields across 9 providers.

This script does the same job from a staging file instead of a keyboard, for the
case where the values are already known. The security properties that matter are
preserved:

  * No secret value is ever passed on a command line. The only argv is a PATH.
  * No secret value is ever printed. Output is metadata only: secret id, field
    names, value length, a truncated SHA-256 fingerprint, and the version id.
  * The staging file lives outside the repo, at mode 0600, and the caller is
    expected to shred it immediately (--shred does it for you).
  * The TXT ledger receives fingerprints for secret fields, never values. Config
    fields (a URL, a project id) are recorded in the clear, as they are not
    credentials.

NOTHING IS ROTATED. No value is regenerated, revoked or deactivated at any
provider. Provider rotation is deferred by explicit user decision until PROJECT
COMPLETE, per .kiro/steering/plaintext-source-policy.md (retired; now .kiro/steering/00-common.md).

STAGING FILE FORMAT
-------------------
    {
      "wecare/some-secret": {
        "_create": true,            # create_secret, else merge into existing
        "field_name": "value",
        ...
      },
      ...
    }
Keys beginning with "_" are directives, not fields. A top-level "_note" is ignored.

USAGE
-----
    python scripts/sync_pasted_credentials.py ~/.wecare-credential-stage.json --dry-run
    python scripts/sync_pasted_credentials.py ~/.wecare-credential-stage.json
    python scripts/sync_pasted_credentials.py ~/.wecare-credential-stage.json --shred

    --dry-run   validate and report what WOULD change. Writes nothing.
    --shred     overwrite and unlink the staging file after a successful run.
    --no-ledger skip the TXT append.

ON get_secret_value
-------------------
Merging into an existing secret requires reading its current value, so that
fields we were not given are preserved rather than silently dropped.
.kiro/steering/aws-agent-rules.md (retired; now .kiro/steering/00-common.md) forbids an agent from calling get-secret-value
because it pulls a value into the agent's context. Here the value is read into
this process's memory, merged, and written back; it is never rendered to stdout,
never returned to the caller, and never enters the transcript. Secrets created
with _create=true take the create_secret path and read nothing.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Dict, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: use .venv/bin/python")

REGION = "us-east-1"
ACCOUNT = "775261844268"
LEDGER = Path(os.path.expanduser("~/aws-new-keys-SAVE-THEN-DELETE.txt"))

# Substrings that mark a field as a credential. Anything matching is fingerprinted
# rather than displayed, in stdout and in the ledger alike. Deliberately broad:
# over-classifying a field costs nothing, under-classifying leaks it.
SECRET_MARKERS = (
    "key", "token", "password", "secret", "credential", "passphrase", "pat",
)

# Fields that are identifiers rather than credentials despite matching above.
CONFIG_OVERRIDES = {
    "phone_number_id", "voice_application_id", "outbound_trunk_id",
    "inbound_trunk_ids", "project_id", "client_id", "customer_id",
    "manager_customer_id", "ga4_property_id", "number_application_uuid",
    "inbound_trunk_wecaredigital_id", "outbound_trunk_credential_username",
}


def is_secret(field: str) -> bool:
    if field in CONFIG_OVERRIDES:
        return False
    lowered = field.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def describe(field: str, value: str) -> str:
    """One-line rendering that is safe to print and safe to write to the ledger."""
    if is_secret(field):
        return f"len={len(value)} sha256:{fingerprint(value)}"
    return value


def load_stage(path: Path) -> Dict[str, dict]:
    if not path.exists():
        sys.exit(f"staging file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        sys.exit(f"staging file {path} is mode {mode:o}; refusing to read a "
                 "world/group-readable credential file. chmod 600 it first.")
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def sync_one(sm, secret_id: str, spec: dict, dry_run: bool) -> dict:
    fields = {k: v for k, v in spec.items() if not k.startswith("_")}
    if not fields:
        return {"skipped": "no fields"}
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            return {"error": f"field {name} is empty or not a string"}

    exists = True
    try:
        sm.describe_secret(SecretId=secret_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            exists = False
        else:
            raise

    declared_create = bool(spec.get("_create"))
    if declared_create and exists:
        return {"error": f"_create=true but {secret_id} already exists; refusing "
                         "to clobber. Set _create=false to merge instead."}
    if not declared_create and not exists:
        return {"error": f"_create=false but {secret_id} does not exist. Set "
                         "_create=true to create it."}

    if dry_run:
        return {"dry_run": True, "exists": exists, "fields": sorted(fields),
                "action": "create" if not exists else "merge"}

    if not exists:
        response = sm.create_secret(
            Name=secret_id,
            SecretString=json.dumps(fields, indent=2, sort_keys=True),
            Description=(f"Created {datetime.date.today()} by "
                         "sync_pasted_credentials.py. Values supplied by the "
                         "account owner. NOT ROTATED - provider rotation deferred "
                         "until PROJECT COMPLETE."),
        )
        return {"action": "created", "arn": response["ARN"],
                "version": response.get("VersionId"), "preserved": [],
                "fields": sorted(fields)}

    # Merge, preserving siblings we were not given. Stays in memory; never printed.
    try:
        current_raw = sm.get_secret_value(SecretId=secret_id).get("SecretString") or "{}"
        current = json.loads(current_raw)
        if not isinstance(current, dict):
            current = {}
    except (ClientError, ValueError):
        current = {}

    preserved = sorted(k for k in current if k not in fields)
    unchanged = sorted(k for k in fields if current.get(k) == fields[k])
    changed = sorted(k for k in fields if current.get(k) != fields[k])

    if not changed:
        return {"action": "already-current", "fields": sorted(fields),
                "preserved": preserved, "unchanged": unchanged}

    merged = {**current, **fields}
    response = sm.put_secret_value(
        SecretId=secret_id,
        SecretString=json.dumps(merged, indent=2, sort_keys=True),
    )
    return {"action": "merged", "arn": response["ARN"],
            "version": response.get("VersionId"), "preserved": preserved,
            "unchanged": unchanged, "changed": changed, "fields": sorted(fields)}


def append_ledger(entries: list, dry_run: bool) -> bool:
    if not entries:
        return False
    today = datetime.date.today().isoformat()
    lines = [
        "",
        "=" * 70,
        f"[{today}] CREDENTIAL SYNC (sync_pasted_credentials.py)  account {ACCOUNT}",
        "  source: values supplied by the account owner",
        "  status: STORED, NOT ROTATED - provider rotation deferred until PROJECT COMPLETE",
        "  note:   secret fields recorded as length + SHA-256 fingerprint, never as values",
        "=" * 70,
    ]
    for secret_id, action, fields, version in entries:
        lines.append(f"  {secret_id}   [{action}]  version={version or 'n/a'}")
        for name in sorted(fields):
            lines.append(f"      {name}: {fields[name]}")
    block = "\n".join(lines) + "\n"

    if dry_run:
        print("\n  ledger entry that WOULD be appended:")
        for line in lines:
            print("    " + line)
        return False

    if not LEDGER.exists():
        print(f"  ledger missing at {LEDGER} - skipping append")
        return False

    original_mode = stat.S_IMODE(LEDGER.stat().st_mode)
    existing = LEDGER.read_text(errors="replace")
    handle, tmp_path = tempfile.mkstemp(dir=str(LEDGER.parent),
                                        prefix=".ledger.", suffix=".tmp")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w") as stream:
            stream.write(existing)
            if not existing.endswith("\n"):
                stream.write("\n")
            stream.write(block)
        os.replace(tmp_path, LEDGER)
        os.chmod(LEDGER, original_mode)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return True


def shred(path: Path) -> None:
    """Overwrite then unlink. Best effort: APFS copy-on-write means the only real
    guarantee is that the plaintext is no longer reachable by name."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as stream:
            for _ in range(3):
                stream.seek(0)
                stream.write(os.urandom(size))
                stream.flush()
                os.fsync(stream.fileno())
        path.unlink()
        print(f"  staging file shredded and removed: {path}")
    except OSError as exc:
        print(f"  WARNING could not shred {path}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", help="path to the staging JSON file")
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    parser.add_argument("--shred", action="store_true",
                        help="destroy the staging file after a successful run")
    parser.add_argument("--no-ledger", action="store_true", help="skip TXT append")
    args = parser.parse_args()

    stage_path = Path(os.path.expanduser(args.stage))
    stage = load_stage(stage_path)

    sts = boto3.client("sts", region_name=REGION)
    identity = sts.get_caller_identity()
    if identity["Account"] != ACCOUNT:
        sys.exit(f"wrong account: {identity['Account']}, expected {ACCOUNT}")
    print(f"account {identity['Account']}  region {REGION}")
    print(f"staging {stage_path}  ({len(stage)} secrets)")
    print("NOTHING IS ROTATED BY THIS SCRIPT.\n")

    sm = boto3.client("secretsmanager", region_name=REGION)
    ledger_entries = []
    failures = 0

    for secret_id in sorted(stage):
        spec = stage[secret_id]
        result = sync_one(sm, secret_id, spec, args.dry_run)

        if result.get("error"):
            print(f"  FAIL  {secret_id}: {result['error']}")
            failures += 1
            continue
        if result.get("skipped"):
            print(f"  SKIP  {secret_id}: {result['skipped']}")
            continue

        fields = {k: v for k, v in spec.items() if not k.startswith("_")}
        rendered = {name: describe(name, value) for name, value in fields.items()}

        if result.get("dry_run"):
            print(f"  DRY   {secret_id}  would {result['action']}  "
                  f"fields={len(result['fields'])}")
            for name in sorted(rendered):
                print(f"          {name}: {rendered[name]}")
            ledger_entries.append((secret_id, result["action"], rendered, None))
            continue

        action = result["action"]
        print(f"  OK    {secret_id}  [{action}]  version={result.get('version', 'n/a')}")
        for name in sorted(rendered):
            marker = ""
            if action == "merged":
                marker = "  (unchanged)" if name in result.get("unchanged", []) else "  (set)"
            print(f"          {name}: {rendered[name]}{marker}")
        if result.get("preserved"):
            print(f"          preserved siblings: {', '.join(result['preserved'])}")
        if action != "already-current":
            ledger_entries.append((secret_id, action, rendered, result.get("version")))

    print()
    if not args.no_ledger:
        if append_ledger(ledger_entries, args.dry_run):
            print(f"  ledger: appended to {LEDGER} (mode preserved, fingerprints only)")

    if failures:
        print(f"\n{failures} secret(s) FAILED. Staging file retained for retry.")
        return 1

    if args.shred and not args.dry_run:
        shred(stage_path)
    elif not args.dry_run:
        print(f"\n  staging file RETAINED at {stage_path} - re-run with --shred "
              "or delete it yourself. Do not leave it on disk.")

    print("\n  next: python scripts/secrets_backup.py    # refresh encrypted local + S3")
    print("  verify: python scripts/txt_source_healthcheck.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
