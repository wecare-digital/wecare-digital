#!/usr/bin/env python3
"""PreToolUse guard: refuse unapproved attempts to create an S3 bucket.

WHY A HOOK AND NOT JUST A STEERING RULE.

The steering file states the rule, and a rule in prose is followed by whoever read it. The
project specification names the bucket with a one-character typo (`wecare-difital-get`),
and the single most likely failure mode here is an agent resolving that 404 by helpfully
creating the bucket the name implies - which would produce a second, empty, wrongly-named
storage location that looks correct in logs and holds nothing the application reads.

This refuses instead of asking. Asking is a poor control for unattended work: it blocks
the 999 safe commands and relies on a tired human to catch the one bad one. Same posture as
the three existing deny hooks, and the reason a blanket-allow permissions file is
defensible at all.

It is deliberately HIGH-PRECISION rather than broad. A noisy guard gets switched off, and a
switched-off guard protects nothing. It matches bucket CREATION only, and allows every
read, write, list and policy operation against the existing bucket.

Exit 2 blocks the call and forwards stderr. Exit 0 allows it.

Verify with `python scripts/verify_s3_bucket_hook.py`.
"""
from __future__ import annotations

import json
import re
import sys

#: Established shared bucket used by the repository.
APPROVED_BUCKET = "wecare-digital-get"

#: The typo in the project specification. Called out by name so the refusal can explain
#: itself rather than looking like an arbitrary block.
KNOWN_TYPO = "wecare-difital-get"

#: Command shapes that create a bucket. Each is anchored on the verb, so a bucket name
#: appearing in an unrelated command cannot trip them.
CREATE_PATTERNS = (
    # AWS CLI
    (r"\baws\s+s3api\s+create-bucket\b", "aws s3api create-bucket"),
    (r"\baws\s+s3\s+mb\b", "aws s3 mb"),
    (r"\baws\s+s3control\s+create-bucket\b", "aws s3control create-bucket"),
    # boto3 / botocore, including the resource form
    (r"\bcreate_bucket\s*\(", "boto3 create_bucket()"),
    (r"\bBucket\s*\(\s*['\"]", "boto3 resource Bucket() create"),
    # CloudFormation / SAM / CDK
    (r"AWS::S3::Bucket\b", "CloudFormation AWS::S3::Bucket"),
    (r"\bnew\s+s3\.Bucket\s*\(", "CDK new s3.Bucket()"),
    (r"\bnew\s+Bucket\s*\(", "CDK new Bucket()"),
    (r"\bs3\.Bucket\s*\(\s*self\b", "CDK python s3.Bucket(self"),
    # Terraform
    (r'\bresource\s+"aws_s3_bucket"', "Terraform aws_s3_bucket"),
    # Amplify Gen2
    (r"\bdefineStorage\s*\(", "Amplify defineStorage()"),
)

#: By-reference and read-only forms that must never be blocked. Checked first, because
#: `create_bucket(` inside a comment explaining the prohibition would otherwise self-block -
#: which is exactly how a guard teaches people to delete the documentation.
ALLOW_PATTERNS = (
    r"block_s3_bucket_creation",          # this file, and the hook config naming it
    r"verify_s3_bucket_hook",             # its verifier
    r"DO\s+NOT\s+CREATE",                 # prose stating the rule
    r"assert\s+['\"]?create_bucket",      # a test asserting absence
    r"not\s+in\s+source",                 # a test asserting absence
)


def _decision(reason: str) -> str:
    return json.dumps({
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def inspect(command: str) -> tuple[bool, str]:
    """`(blocked, reason)`. Pure, so the verifier can exercise it directly."""
    if not command:
        return False, ""

    for allow in ALLOW_PATTERNS:
        if re.search(allow, command, re.IGNORECASE):
            return False, ""

    for pattern, label in CREATE_PATTERNS:
        if re.search(pattern, command):
            reason = (
                f"BLOCKED: {label} creates an S3 bucket.\n"
                f"\n"
                f"Use established repository storage such as {APPROVED_BUCKET!r}. Creating a "
                f"new bucket is prohibited without explicit owner approval.\n"
                f"\n"
                f"If you reached for this because a bucket lookup returned 404: the project "
                f"specification spells the name {KNOWN_TYPO!r}, which is a known typo and "
                f"does not exist. The bucket you want is {APPROVED_BUCKET!r}. Do not create "
                f"the misspelled one.\n"
                f"\n"
                f"For isolation, use a prefix, IAM scoping, object tags or metadata."
            )
            return True, reason

    # The typo on its own, in any command, is worth surfacing even when nothing is being
    # created - it means something is about to address a bucket that is not there.
    if KNOWN_TYPO in command:
        return True, (
            f"BLOCKED: this command names {KNOWN_TYPO!r}, which does not exist - it is a "
            f"one-character typo for {APPROVED_BUCKET!r}. Verified 2026-09-29: head-bucket "
            f"returns 404 and no bucket with that spelling exists in account 775261844268. "
            f"Use {APPROVED_BUCKET!r}."
        )

    return False, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # A guard that cannot parse its input must not block real work. The other deny
        # hooks take the same position: fail open on a malformed event, closed on a match.
        return 0

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = str(tool_input.get("command") or payload.get("command") or "")

    blocked, reason = inspect(command)
    if blocked:
        print(reason, file=sys.stderr)
        print(_decision(reason))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
