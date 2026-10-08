"""Re-send the Phase O-1 activation hint for named payment references. Dry run by default.

The operator recovery for a paid services order whose webhook hint was missed and whose
customer has not revisited /orders (the self-heal). It invokes `wecare-service-requests:live`
with the SAME internal action the webhook sends, so the receiver re-reads every link and is
idempotent: a reference that already has its request answers ALREADY_ACTIVE and writes nothing.

    python scripts/reconcile_service_requests.py --reference-id WD-PAY-... [--reference-id ...]
    python scripts/reconcile_service_requests.py --reference-id WD-PAY-... --apply

Prints outcomes only. Moves no money and reads no secret.
"""

from __future__ import annotations

import argparse
import json
import re

import boto3

FUNCTION = "wecare-service-requests:live"
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,35}$")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-id", action="append", default=[], required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    bad = [ref for ref in args.reference_id if not _REFERENCE_RE.match(ref)]
    if bad:
        print(f"refusing malformed reference ids: {bad}")
        return 2
    client = boto3.client("lambda", region_name="us-east-1") if args.apply else None
    for ref in dict.fromkeys(args.reference_id):
        payload = {"internalAction": "activateServiceRequest", "referenceId": ref}
        if not args.apply:
            print(f"would invoke {FUNCTION} with {json.dumps(payload)}")
            continue
        response = client.invoke(FunctionName=FUNCTION, InvocationType="RequestResponse",
                                 Payload=json.dumps(payload).encode("utf-8"))
        print(f"{ref}: {response['Payload'].read().decode('utf-8')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
