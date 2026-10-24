#!/usr/bin/env python3
"""Verify Secrets Manager entries contain the expected FIELDS, without exposing values.

Reports, per secret: the JSON key names, each value's length and an irreversible
`sha256[:12]` fingerprint. That is enough to confirm a field is populated and to
tell across runs whether it is still the same value, while never putting the
value into agent context, a log, a command line or a file.

**Corrected 2026-09-29.** This docstring used to describe the fingerprint as
"first 4 / last 2 characters", and `fingerprint()` did exactly that - so the
report disclosed six characters of every field of all seven secrets. See that
function for why a prefix and a length are not a safe rendering.

    python scripts/audit_secrets_structure.py

Exit 0 always; this is a report.
"""
from __future__ import annotations

import hashlib
import json

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"

# Secrets relevant to the 2026-09-19 leak plus their production consumers.
TARGETS = [
    ("wecare/razorpay/api",      "Razorpay API credentials (migrated 2026-09-18)"),
    ("wecare/razorpay-webhook",  "Razorpay webhook signing secret only; API key pair lives in wecare/razorpay/api"),
    ("wecare/google-api-key",    "Google API key (migrated 2026-09-18)"),
    ("wecare/google-maps",       "Google Maps key read by wecare-whatsapp-templates"),
    # Added 2026-09-30. Google Cloud project wecaredigitalbw contains exactly ONE API key -
    # "WECARE Unified Google API Key", uid 1febded3-3e68-4d6a-9737-9628ff8ebc19, created
    # 2026-08-17 - while FOUR secrets here describe themselves as holding a Google key, two of
    # them claiming different restriction profiles that a single key cannot have at once.
    # Whether they hold one value or several is answerable ONLY by comparing fingerprints,
    # which is the whole reason this audit exists, so the two missing ones are now in scope.
    ("wecare/google/cloud",      "Unified Google API key + project metadata (CMK-encrypted)"),
    ("wecare/google-maps-server", "Claims to be a SERVER-restricted Maps key for address capture"),
    ("wecare/openai/api",        "OpenAI key (migrated 2026-09-18)"),
    ("wecare/plivo/api",         "Plivo API credentials (migrated 2026-09-18)"),
]


def fingerprint(v: object) -> str:
    """Identify a value without disclosing any part of it.

    This used to return `len={n} {v[:4]}…{v[-2:]}`, i.e. four leading and two
    trailing characters of the live value, for every field of all seven secrets
    below - including `wecare/razorpay/api`'s `key_secret` and the AWS IAM secret
    access key. Six characters of a live credential is still six characters of a
    live credential, and this function's output goes to a terminal, which goes to
    `~/.kiro/logs` and the session transcript: the exact path that put four
    credentials on disk on 2026-09-19. An issuer prefix plus an exact length is a
    meaningful head start for anyone reading those files.

    `scripts/secrets_backup.py::fp` already carried this same fix and the same
    reasoning; this copy was missed. A sha256 prefix identifies a value across
    runs just as well and discloses nothing, because it is one-way and there is
    no shorter guess than the value itself.
    """
    if not isinstance(v, str):
        return f"<{type(v).__name__}>"
    if len(v) <= 8:
        # Kept from the original, and it is not redundant: a sha256 of a value this
        # short is invertible by brute force, so hashing it would disclose it. A field
        # this short is not a credential anyway - it is a flag or a region code.
        return f"len={len(v)} <short>"
    digest = hashlib.sha256(v.encode("utf-8")).hexdigest()[:12]
    return f"len={len(v):<4} sha256:{digest}"


def main() -> int:
    sm = boto3.client("secretsmanager", region_name=REGION)
    print(f"region={REGION}\n")
    for name, note in TARGETS:
        print(f"=== {name}")
        print(f"    {note}")
        try:
            meta = sm.describe_secret(SecretId=name)
        except ClientError as exc:
            print(f"    MISSING or inaccessible: {exc.response['Error']['Code']}\n")
            continue
        kms = meta.get("KmsKeyId") or "aws/secretsmanager (AWS-managed)"
        print(f"    KMS:      {kms}")
        print(f"    Changed:  {meta.get('LastChangedDate')}")
        print(f"    Rotation: {meta.get('RotationEnabled', False)}")
        tags = {t['Key']: t['Value'] for t in meta.get("TagList", [])}
        print(f"    Tags:     {tags or 'none'}")
        try:
            raw = sm.get_secret_value(SecretId=name)["SecretString"]
        except ClientError as exc:
            print(f"    cannot read: {exc.response['Error']['Code']}\n")
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            print(f"    format:   plain string, {fingerprint(raw)}\n")
            continue
        if isinstance(obj, dict):
            print(f"    format:   JSON object, {len(obj)} field(s)")
            for k in sorted(obj):
                print(f"      - {k:24s} {fingerprint(obj[k])}")
        else:
            print(f"    format:   JSON {type(obj).__name__}")
        print()
    print("No secret value was printed, and no part of one: only field names, "
          "lengths and irreversible sha256[:12] fingerprints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
