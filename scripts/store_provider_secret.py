#!/usr/bin/env python3
"""Store a provider credential in Secrets Manager and record it in the TXT ledger.

WITHOUT ROTATING ANYTHING. Rotation at the provider is a deliberate manual step
the user performs at project close (see .kiro/steering/plaintext-source-policy.md (retired; now .kiro/steering/00-common.md),
"Provider rotation deferred by user"). This script only writes what you already
hold into the two places that are supposed to hold it:

    secure hidden input  ->  AWS Secrets Manager (runtime source)
                         ->  ~/aws-new-keys-SAVE-THEN-DELETE.txt (maintenance source)

Why it exists
-------------
On 2026-09-19 credentials arrived by being typed into chat, which is persisted to
~/.kiro/logs and the session transcript. The rule in
.kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md) is that a secret value must never appear in a
command, an argv, an environment assignment on a command line, or a log line.
So an agent cannot write these values for you: doing so would require putting
them in a tool call. YOU run this, and the value goes from your keyboard into
memory and then into Secrets Manager. It is never echoed, never logged, never in
shell history, never in a Kiro permission rule.

Usage
-----
    python scripts/store_provider_secret.py --list
    python scripts/store_provider_secret.py truecaller
    python scripts/store_provider_secret.py plivo-sip
    python scripts/store_provider_secret.py meta-whatsapp-sip
    python scripts/store_provider_secret.py plivo-answer --generate

    --generate      mint the value locally with secrets.token_urlsafe(32) instead
                    of prompting. Only offered for fields marked generatable,
                    i.e. shared secrets we own both ends of.
    --no-ledger     write Secrets Manager only, skip the TXT append.
    --dry-run       validate inputs and show what WOULD be written. Writes nothing.

What it prints
--------------
Metadata only: secret id, field names, value lengths, a truncated SHA-256
fingerprint per field, and the Secrets Manager version ids. Never a value.
The fingerprint is there so you can confirm two systems hold the same string
without either of them displaying it.

What it does NOT do
-------------------
* Does not revoke, regenerate or deactivate anything at the provider.
* Does not read secrets back out (`get_secret_value` is prohibited for agents by
  .kiro/steering/aws-agent-rules.md (retired; now .kiro/steering/00-common.md); retrieve values from the AWS console when a
  human needs to paste one somewhere).
* Does not touch the encrypted backups. Run scripts/secrets_backup.py afterwards
  so the local and S3 artifacts include the new material.
"""
from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
ACCOUNT = "775261844268"
LEDGER = Path(os.path.expanduser("~/aws-new-keys-SAVE-THEN-DELETE.txt"))


class Field:
    """One field inside a secret."""

    def __init__(
        self,
        name: str,
        *,
        secret: bool = True,
        prefix: tuple = (),
        generatable: bool = False,
        note: str = "",
    ) -> None:
        self.name = name
        # secret=False means it is configuration, not a credential: it may be
        # typed visibly and is safe to show back. e.g. an app domain.
        self.secret = secret
        self.prefix = prefix
        self.generatable = generatable
        self.note = note


# Secret ids are the ones that ALREADY EXIST in this account wherever possible —
# do not invent a parallel name, or consumers keep reading the old one. Verified
# against ListSecrets on 2026-09-19 (28 secrets). NEW marks ids that do not exist
# yet and will be created on first run.
PROVIDERS: Dict[str, dict] = {
    # ---- new ids -----------------------------------------------------------
    "truecaller": {
        "secret_id": "wecare/truecaller",                          # FUTURE / unprovisioned
        "fields": [
            Field("app_key", note="partner/app key from developer.truecaller.com"),
            Field("app_name", secret=False),
            Field("app_domain", secret=False),
            Field("callback_url", secret=False),
        ],
        "consumers": "POST /auth/truecaller/callback - NOT BUILT YET, so nothing "
                     "reads this until that Lambda and route exist",
    },
    "kiro": {
        "secret_id": "wecare/kiro/api",
        "fields": [
            Field("api_key", prefix=("ksk_",),
                  note="Legacy Kiro service API key; no active workflow or runtime consumer"),
        ],
        "consumers": "No active consumer. Retain only until the provider credential is separately retired.",
    },
    "plivo-answer": {
        "secret_id": "wecare/plivo-answer",                        # NEW
        "fields": [
            Field("token", generatable=True,
                  note="shared secret appended as ?token= to the three Plivo URLs"),
        ],
        "consumers": "wecare-plivo-answer (gates POST /plivo/answer)",
    },
    "meta-whatsapp-sip": {
        "secret_id": "wecare/meta/whatsapp-sip",                   # NEW
        "fields": [
            Field("hostname", secret=False),
            Field("port", secret=False),
            Field("sip_user_password",
                  note="Meta calling-settings SIP password. Recording it gives you a "
                       "known-good value to roll back to after a repoint."),
            Field("phone_number_id", secret=False),
        ],
        "consumers": "Meta WhatsApp Business Calling -> SIP media leg",
    },
    # ---- existing ids: fields are MERGED, siblings preserved ---------------
    "plivo-api": {
        "secret_id": "wecare/plivo/api",                           # EXISTS
        "fields": [Field("auth_id"), Field("auth_token")],
        "consumers": "Plivo REST API callers",
    },
    "plivo-trunks": {
        "secret_id": "wecare/plivo",                               # EXISTS
        "fields": [
            Field("outbound_trunk_name", secret=False),
            Field("outbound_trunk_credential",
                  note="the outbound trunk password, not the account auth token"),
            Field("outbound_trunk_id", secret=False),
            Field("outbound_trunk_host", secret=False, note="e.g. <id>.zt.plivo.com"),
            Field("inbound_trunk_ids", secret=False,
                  note="comma-separate several; these are Zentrunk trunk ids"),
            Field("voice_application_id", secret=False),
            Field("sip_endpoint_uri", secret=False),
            Field("sip_endpoint_username", secret=False),
        ],
        "consumers": "Plivo voice application WECARE-WHATSAPP-IVR + Zentrunk",
    },
    "sinch-sms": {
        "secret_id": "wecare/sinch/sms",                           # EXISTS
        # Field names MUST match what the Lambda reads, see
        # messaging/outbound-sms/handler.py _load_sinch_sms_creds().
        "fields": [
            Field("app_id", secret=False),
            Field("user_id", secret=False),
            Field("password"),
            Field("oauth_token", note="lifetime OAuth token, no IP allowlist"),
            Field("oauth_host", secret=False, note="e.g. jumbo.aclgateway.com"),
        ],
        "consumers": "wecare-outbound-sms (_send_sinch_sms) and wecare-sinch-dlr",
    },
    "google-cloud": {
        "secret_id": "wecare/google/cloud",                        # EXISTS
        "fields": [
            Field("api_key", prefix=("AIza",), note="unified Google API key"),
            Field("project_id", secret=False),
            Field("project_number", secret=False),
            Field("project_name", secret=False),
        ],
        "consumers": "SEO tooling; see also wecare/google-api-key (PageSpeed) and "
                     "wecare/google-maps (Places) which hold their own keys",
    },
    "google-oauth": {
        "secret_id": "wecare/seo/google-oauth",                    # EXISTS
        "fields": [
            Field("client_id", secret=False),
            Field("client_secret", prefix=("GOCSPX-",)),
        ],
        "consumers": "Google OAuth flows (Search Console / SEO). Reuse this client "
                     "for People API contact sync rather than minting a second one.",
    },
    "google-ads": {
        "secret_id": "wecare/google/ads",                          # EXISTS
        "fields": [
            Field("developer_token", note="from the Google Ads API Center"),
            Field("customer_id", secret=False, note="e.g. 836-758-9699"),
            Field("manager_customer_id", secret=False, note="the MCC, e.g. 427-041-2231"),
        ],
        "consumers": "Google Ads API callers (none built yet)",
    },
    "github-pat": {
        "secret_id": "wecare/github-pat",                          # EXISTS
        # The field name MUST match the workspace MCP's GITHUB_TOKEN_FIELD (CloudFormation
        # parameter GithubTokenField, live value "token"). The prefix guard only accepts a
        # FINE-GRAINED token, so the exposed near-full-scope classic token (ghp_...) this
        # replaces cannot be stored again by mistake.
        "fields": [
            Field("token", prefix=("github_pat_",),
                  note="fine-grained PAT: resource owner wecare-digital, only the repository "
                       "wecare-digital/wecare-digital, Repository permissions > Metadata: "
                       "Read-only, nothing else"),
        ],
        "consumers": "wecare-workspace-mcp github_status (GET /repos/wecare-digital/wecare-digital). "
                     "Revoke the old classic token at github.com/settings/tokens only after "
                     "github_status succeeds with this one.",
    },
}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def prompt(field: Field, *, generate: bool) -> str:
    if field.generatable and generate:
        value = secrets.token_urlsafe(32)
        print(f"    {field.name}: generated locally, len={len(value)} "
              f"fp={fingerprint(value)}")
        print("      retrieve it from the AWS console when you need to paste it "
              "into the provider; it is not printed here")
        return value

    if field.note:
        print(f"    ({field.note})")

    if not field.secret:
        value = input(f"    {field.name}: ").strip()
        if not value:
            raise SystemExit(f"{field.name} is empty; aborting")
        print(f"      accepted: {value}")
        return value

    first = getpass.getpass(f"    {field.name} (hidden): ").strip()
    if not first:
        raise SystemExit(f"{field.name} is empty; aborting")
    second = getpass.getpass(f"    {field.name} (confirm): ").strip()
    if first != second:
        raise SystemExit(f"{field.name} entries do not match; aborting")
    if field.prefix and not first.startswith(field.prefix):
        raise SystemExit(
            f"{field.name} does not start with any of {field.prefix}; aborting "
            "(guards against pasting the wrong field)"
        )
    print(f"      accepted: len={len(first)} fp={fingerprint(first)}")
    return first


def write_secret(secret_id: str, values: Dict[str, str], dry_run: bool) -> dict:
    """Create or update, preserving any field already in the secret we did not ask for."""
    sm = boto3.client("secretsmanager", region_name=REGION)

    existing_keys: List[str] = []
    exists = True
    try:
        # DescribeSecret does NOT return the value, so this is safe.
        sm.describe_secret(SecretId=secret_id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            exists = False
        else:
            raise

    if dry_run:
        return {"dry_run": True, "exists": exists, "would_write": sorted(values),
                "secret_id": secret_id}

    if not exists:
        response = sm.create_secret(
            Name=secret_id,
            SecretString=json.dumps(values, indent=2, sort_keys=True),
            Description=f"Created {datetime.date.today()} by store_provider_secret.py. "
                        "Provider rotation deferred by user.",
        )
        return {"created": True, "arn": response["ARN"],
                "version": response.get("VersionId"), "preserved_fields": []}

    # Merge: keep fields we were not given. Reading the current value here is
    # unavoidable to preserve siblings, and it stays in memory only.
    try:
        current_raw = sm.get_secret_value(SecretId=secret_id).get("SecretString") or "{}"
        current = json.loads(current_raw)
        if not isinstance(current, dict):
            current = {}
    except (ClientError, ValueError):
        current = {}
    existing_keys = sorted(k for k in current if k not in values)

    merged = {**current, **values}
    response = sm.put_secret_value(
        SecretId=secret_id,
        SecretString=json.dumps(merged, indent=2, sort_keys=True),
    )
    return {"created": False, "arn": response["ARN"],
            "version": response.get("VersionId"),
            "preserved_fields": existing_keys}


def append_ledger(provider: str, secret_id: str, values: Dict[str, str],
                  fields: List[Field], result: dict, dry_run: bool) -> bool:
    """Append one event, atomically, preserving mode 0600. Leaves no remnant."""
    action = "CREATED-SECRET" if result.get("created") else "UPDATED-SECRET"
    today = datetime.date.today().isoformat()
    lines = [
        "",
        f"[{today}] {action} (secretsmanager)  account {ACCOUNT}",
        f"  subject: {secret_id}  (provider: {provider})",
        f"  fields: {', '.join(sorted(values))}",
    ]
    by_name = {f.name: f for f in fields}
    for key in sorted(values):
        field = by_name.get(key)
        if field is not None and not field.secret:
            lines.append(f"  {key}: {values[key]}")
        else:
            lines.append(f"  {key}: len={len(values[key])} sha256:{fingerprint(values[key])}")
    lines += [
        f"  version: {result.get('version', 'n/a')}",
        "  why: recorded for the maintenance/runtime split; value entered at a hidden prompt",
        "  status: STORED, NOT ROTATED - provider rotation deferred by user until PROJECT COMPLETE",
    ]
    block = "\n".join(lines) + "\n"

    if dry_run:
        print("    ledger entry that WOULD be appended:")
        for line in lines:
            print("      " + line)
        return False

    if not LEDGER.exists():
        print(f"    ledger missing at {LEDGER} - skipping append")
        return False

    original_mode = stat.S_IMODE(LEDGER.stat().st_mode)
    existing = LEDGER.read_text(errors="replace")
    handle, tmp_path = tempfile.mkstemp(dir=str(LEDGER.parent), prefix=".ledger.", suffix=".tmp")
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
        # Never leave a credential-bearing temp file behind.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("provider", nargs="?", help="which provider to store")
    parser.add_argument("--list", action="store_true", help="show known providers and exit")
    parser.add_argument("--generate", action="store_true",
                        help="mint generatable fields locally instead of prompting")
    parser.add_argument("--no-ledger", action="store_true", help="skip the TXT append")
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    args = parser.parse_args()

    if args.list or not args.provider:
        print("known providers:\n")
        for name, spec in PROVIDERS.items():
            print(f"  {name:20s} -> {spec['secret_id']}")
            print(f"  {'':20s}    fields: "
                  f"{', '.join(f.name + ('' if f.secret else ' (config)') for f in spec['fields'])}")
            print(f"  {'':20s}    consumers: {spec['consumers']}\n")
        return 0 if args.list else 1

    if args.provider not in PROVIDERS:
        print(f"unknown provider {args.provider!r}; try --list")
        return 1

    spec = PROVIDERS[args.provider]
    secret_id = spec["secret_id"]
    print(f"\n{args.provider} -> {secret_id}   (region {REGION}, account {ACCOUNT})")
    print("  nothing is rotated or revoked at the provider by this script.\n")

    values: Dict[str, str] = {}
    for field in spec["fields"]:
        values[field.name] = prompt(field, generate=args.generate)

    print()
    result = write_secret(secret_id, values, args.dry_run)
    if args.dry_run:
        print(f"    DRY RUN: would {'create' if not result['exists'] else 'update'} "
              f"{secret_id} with fields {result['would_write']}")
    else:
        verb = "created" if result.get("created") else "updated"
        print(f"    Secrets Manager: {verb} {secret_id}")
        print(f"      version: {result.get('version')}")
        if result.get("preserved_fields"):
            print(f"      preserved existing fields: {', '.join(result['preserved_fields'])}")

    if not args.no_ledger:
        if append_ledger(args.provider, secret_id, values, spec["fields"],
                         result, args.dry_run):
            print(f"    ledger: appended to {LEDGER} (mode preserved)")

    print("\n  next: python scripts/secrets_backup.py   "
          "# refresh the encrypted local + S3 artifacts")
    print("  verify: python scripts/txt_source_healthcheck.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
