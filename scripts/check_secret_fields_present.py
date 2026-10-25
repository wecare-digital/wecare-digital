#!/usr/bin/env python3
"""Report WHICH FIELDS a Secrets Manager entry has. Never a value, never a fingerprint.

Why this exists
---------------
Deciding whether a webhook handler can verify signatures requires knowing only
one thing: is the signing secret configured? Not its value, not its length, not
its first four characters.

`scripts/audit_secrets_structure.py` answers a different question - it prints
lengths and short fingerprints for the leak-audit target list. For a
"can we enforce verification yet?" decision that is more disclosure than the
decision needs, and it covers a fixed set of secrets.

This script prints `field: present|absent` and nothing else. The value is read
inside this process, compared against nothing, and discarded. Per
`.kiro/steering/secret-handling.md` (retired; now .kiro/steering/00-common.md) the secret is passed **by reference** - the
secret id is an argument, the value never is.

Usage
-----
    python scripts/check_secret_fields_present.py wecare/sinch/rcs webhook_secret
    python scripts/check_secret_fields_present.py wecare/sinch/rcs webhook_secret username

Exit codes
----------
    0  every requested field is present and non-empty
    1  at least one requested field is missing or empty
    2  the secret could not be read
"""

from __future__ import annotations

import json
import sys

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    secret_id, fields = argv[0], argv[1:]
    client = boto3.client("secretsmanager", region_name=REGION)

    try:
        raw = client.get_secret_value(SecretId=secret_id)["SecretString"]
    except (ClientError, BotoCoreError) as exc:
        # Print the error CLASS only. A botocore message can echo request
        # context, and this script must stay safe to run in a transcript.
        print(f"{secret_id}: unreadable ({type(exc).__name__})")
        return 2

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError):
        # A plain-string secret has no fields. Say so without describing it.
        del raw
        print(f"{secret_id}: not a JSON object, so it has no named fields")
        return 1

    present = {k for k, v in data.items() if isinstance(v, str) and v.strip()}
    all_keys = sorted(data.keys())
    del raw, data  # drop the values as early as possible

    print(f"{secret_id}")
    print(f"  field names present : {', '.join(all_keys) if all_keys else '(none)'}")
    print(f"  field count         : {len(all_keys)}")
    missing = []
    for field in fields:
        ok = field in present
        print(f"  {field:22}: {'present' if ok else 'ABSENT or empty'}")
        if not ok:
            missing.append(field)

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
