#!/usr/bin/env python3
"""Compute and (optionally) apply a least-privilege S3 policy for the shared lambda role.

THE PROBLEM
-----------
`wecare-digital-lambda-role` (inline policy `wecare-digital-lambda-permissions`), shared by
~60 functions, currently grants `s3:GetObject/PutObject/DeleteObject/ListBucket` on the whole
bucket `wecare-digital-get` and `wecare-digital-get/*`, with a `DenyLegacyMediaWrites` override
on four retired prefixes. Bucket-wide write is broader than any function needs.

WHY THIS IS STAGED, NOT A BLIND CUT
-----------------------------------
The steering note is explicit: narrowing this blindly could break WhatsApp, receipts, invoices,
cleanup, voice or workspace. So this tool does NOT silently rewrite a live policy. It:
  1. Derives the EXACT prefix union the fleet legitimately uses, straight from the canonical
     contract `lambda_utils.media_paths` (so it cannot drift from the code), and
  2. Emits a proposed least-privilege policy + a unified diff against the live policy, and
  3. Runs iam:simulate-principal-policy for a battery of known-good operations (the real keys
     WhatsApp/receipts/invoices/cleanup/voice/workspace read and write) and known-bad ones
     (bucket root write, secure/u uploads write), and
  4. Only with --apply AND a clean simulation does it put_role_policy.

The tightened policy keeps READ broad (GetObject/ListBucket on the whole bucket - reads are not
the risk and several paths read legacy keys during migration) but narrows WRITE
(PutObject/DeleteObject) to exactly the two roots the fleet writes under - the public-delivery
subtree `secure/d/public/*` and the public root `o/*` - plus the upload prefixes `secure/u/*`.
It removes the ability to write to the BUCKET ROOT and to the gated `secure/` top level outside
those sub-roots. The existing `DenyLegacyMediaWrites` statement is preserved verbatim.

USAGE
-----
    python scripts/scope_shared_lambda_s3.py                 # show proposed policy + diff (no AWS write)
    python scripts/scope_shared_lambda_s3.py --simulate      # + run simulate-principal-policy (reads AWS)
    python scripts/scope_shared_lambda_s3.py --apply         # put policy, but ONLY if --simulate passes

Exit 0 on a clean plan/simulation; 1 on any simulation regression or apply refusal.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_PATHS_FILE = ROOT / "amplify" / "functions" / "shared" / "lambda_utils" / "media_paths.py"

# Load the canonical key contract without placing lambda_utils itself on sys.path.
# That directory contains logging.py; inserting it at sys.path[0] shadows Python's
# standard-library logging module when boto3 imports it during --simulate/--apply.
_spec = importlib.util.spec_from_file_location("wecare_media_paths", MEDIA_PATHS_FILE)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load media path contract from {MEDIA_PATHS_FILE}")
mp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mp)

REGION = "us-east-1"
ROLE = "wecare-digital-lambda-role"
POLICY = "wecare-digital-lambda-permissions"
BUCKET = mp.BUCKET  # wecare-digital-get
SID_S3 = "SharedMediaS3"
SID_DENY = "DenyLegacyMediaWrites"

# The two write roots the fleet legitimately writes under, plus uploads, derived from the
# contract. WRITE is scoped to these; the bucket ROOT and bare secure/ are intentionally out.
WRITE_ROOTS = [
    mp.PUBLIC_DELIVERABLE_ROOT,  # secure/d/public/
    mp.PUBLIC_ROOT,              # o/
    mp.SECURE_UPLOAD_ROOT,       # secure/u/
]

# Keys used to VERIFY the tightened policy still permits real work (and still blocks what it
# must). Drawn from the actual prefix constants so they track the code.
MUST_ALLOW_WRITE = [
    mp.WHATSAPP_INCOMING_PREFIX + "x.jpg",
    mp.WHATSAPP_TEMPLATE_IMAGE_PREFIX + "x.png",
    mp.INVOICE_CUSTOMER_IMAGE_PREFIX + "x.png",
    mp.RECEIPT_PREFIX + "x.pdf",
    mp.CATALOG_MEDIA_PREFIX + "x.png",
    mp.PUBLIC_STREAM_MEDIA_M_PREFIX + "x.png",
    mp.DROP_DOCS_UPLOAD_PREFIX + "x.pdf",
    mp.SERVICE_REQUEST_UPLOAD_PREFIX + "x.pdf",
]
MUST_DENY_WRITE = [
    "x-at-root.bin",                                  # bucket root
    "secure/private-top-level.bin",                   # bare secure/ (not u/ or d/public)
    mp.INVOICE_CUSTOMER_IMAGE_PREFIX.replace("secure/d/public/", "secure/") + "x.png",  # legacy Invoice (Deny guard)
    "o/stack/whatsapp-media/x.pdf",                   # legacy whatsapp (Deny guard)
]
MUST_ALLOW_READ = [k for k in MUST_ALLOW_WRITE] + ["o/stream/media/anything.png"]


def deny_statement() -> dict:
    """The retired-path write deny, preserved verbatim from the contract."""
    return {
        "Sid": SID_DENY,
        "Effect": "Deny",
        "Action": ["s3:PutObject", "s3:DeleteObject"],
        "Resource": [
            f"arn:aws:s3:::{BUCKET}/secure/Invoice/customer_invoice/*",
            f"arn:aws:s3:::{BUCKET}/secure/Invoice/fonts/*",
            f"arn:aws:s3:::{BUCKET}/o/stack/whatsapp-media/*",
            f"arn:aws:s3:::{BUCKET}/stack/whatsapp-media/*",
        ],
    }


def proposed_s3_statements() -> list[dict]:
    write_resources = [f"arn:aws:s3:::{BUCKET}/{root}*" for root in WRITE_ROOTS]
    return [
        {
            "Sid": SID_S3 + "ReadList",
            "Effect": "Allow",
            # Reads stay broad: reads are not the exposure, and migration paths read legacy keys.
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
        },
        {
            "Sid": SID_S3 + "Write",
            "Effect": "Allow",
            # Writes narrowed to the three legitimate roots - NOT the bucket root, NOT bare secure/.
            "Action": ["s3:PutObject", "s3:DeleteObject"],
            "Resource": sorted(write_resources),
        },
        deny_statement(),
    ]


def _iam():
    import boto3
    return boto3.client("iam", region_name=REGION)


def live_policy(iam) -> dict:
    return iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]


def proposed_full(live: dict) -> dict:
    """Replace only the S3-related statements; keep everything else (SMS, dynamo, secrets...)."""
    s3_sids = {SID_DENY} | {s["Sid"] for s in proposed_s3_statements() if "Sid" in s}
    # Drop any existing statement that is an S3 Allow/Deny on this bucket OR carries our Sids.
    kept = []
    for st in live.get("Statement", []):
        sid = st.get("Sid", "")
        acts = st.get("Action", [])
        acts = [acts] if isinstance(acts, str) else acts
        is_s3 = any(a.startswith("s3:") for a in acts)
        if sid in s3_sids or is_s3:
            continue
        kept.append(st)
    return {"Version": live.get("Version", "2012-10-17"),
            "Statement": kept + proposed_s3_statements()}


def simulate(iam, policy: dict) -> int:
    """iam:simulate-custom-policy for the must-allow / must-deny write + read matrices."""
    def run(actions, resources, context_name):
        res = iam.simulate_custom_policy(
            PolicyInputList=[json.dumps(policy)],
            ActionNames=actions,
            ResourceArns=resources)
        out = {}
        for r in res["EvaluationResults"]:
            action = r["EvalActionName"]
            specific = r.get("ResourceSpecificResults") or []
            if specific:
                for item in specific:
                    out[(action, item["EvalResourceName"])] = item["EvalResourceDecision"]
            else:
                out[(action, r["EvalResourceName"])] = r["EvalDecision"]
        return out

    failures = []
    allow_w = run(["s3:PutObject"], [f"arn:aws:s3:::{BUCKET}/{k}" for k in MUST_ALLOW_WRITE], "allow-write")
    for k in MUST_ALLOW_WRITE:
        d = allow_w.get(("s3:PutObject", f"arn:aws:s3:::{BUCKET}/{k}"))
        if d != "allowed":
            failures.append(f"MUST-ALLOW write denied: {k} -> {d}")
    deny_w = run(["s3:PutObject"], [f"arn:aws:s3:::{BUCKET}/{k}" for k in MUST_DENY_WRITE], "deny-write")
    for k in MUST_DENY_WRITE:
        d = deny_w.get(("s3:PutObject", f"arn:aws:s3:::{BUCKET}/{k}"))
        if d == "allowed":
            failures.append(f"MUST-DENY write allowed: {k} -> {d}")
    allow_r = run(["s3:GetObject"], [f"arn:aws:s3:::{BUCKET}/{k}" for k in MUST_ALLOW_READ], "allow-read")
    for k in MUST_ALLOW_READ:
        d = allow_r.get(("s3:GetObject", f"arn:aws:s3:::{BUCKET}/{k}"))
        if d != "allowed":
            failures.append(f"MUST-ALLOW read denied: {k} -> {d}")

    print(f"simulation: {len(MUST_ALLOW_WRITE)} allow-write, {len(MUST_DENY_WRITE)} deny-write, "
          f"{len(MUST_ALLOW_READ)} allow-read")
    for f in failures:
        print(f"  FAIL  {f}")
    if not failures:
        print("  all simulation checks passed")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--simulate", action="store_true", help="run iam:simulate-custom-policy (reads AWS)")
    ap.add_argument("--apply", action="store_true", help="put the tightened policy (implies --simulate)")
    args = ap.parse_args()

    proposed_s3 = proposed_s3_statements()
    print("Proposed S3 statements (write narrowed to the three legitimate roots):")
    print(json.dumps(proposed_s3, indent=2))

    if not (args.simulate or args.apply):
        print("\nWRITE roots: " + ", ".join(WRITE_ROOTS))
        print("Run with --simulate (needs AWS read) to verify, then --apply to put.")
        return 0

    iam = _iam()
    live = live_policy(iam)
    new = proposed_full(live)

    before = json.dumps(live, indent=2, sort_keys=True).splitlines()
    after = json.dumps(new, indent=2, sort_keys=True).splitlines()
    print("\n--- live policy vs proposed (unified diff) ---")
    print("\n".join(difflib.unified_diff(before, after, "live", "proposed", lineterm="")))

    sim = simulate(iam, new)
    if sim != 0:
        print("\nREFUSING to apply: simulation regressed.", file=sys.stderr)
        return 1

    if args.apply:
        iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY, PolicyDocument=json.dumps(new))
        print(f"\napplied least-privilege S3 scope to {ROLE}/{POLICY}")
    else:
        print("\nsimulation clean. Re-run with --apply to put the policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
