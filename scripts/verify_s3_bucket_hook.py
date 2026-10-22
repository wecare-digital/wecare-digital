#!/usr/bin/env python3
"""Verify the S3 bucket-creation guard: blocks creation, allows everything else.

Run: python scripts/verify_s3_bucket_hook.py

A guard is only worth having if its false-positive rate is known. Half of these cases
assert that ordinary work is NOT blocked, because a noisy guard gets switched off and a
switched-off guard protects nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from block_s3_bucket_creation import APPROVED_BUCKET, KNOWN_TYPO, inspect  # noqa: E402

MUST_BLOCK = [
    # AWS CLI
    f"aws s3api create-bucket --bucket {APPROVED_BUCKET}-new --region us-east-1",
    "aws s3 mb s3://wecare-blog-sources",
    "aws s3control create-bucket --bucket foo --outpost-id op-1",
    # boto3
    "boto3.client('s3').create_bucket(Bucket='wecare-blog')",
    'python3 -c "import boto3; boto3.client(\'s3\').create_bucket(Bucket=\'x\')"',
    # IaC
    "cat > t.yml <<'Y'\nResources:\n  B:\n    Type: AWS::S3::Bucket\nY",
    "echo \"new s3.Bucket(this, 'BlogBucket')\" >> lib/stack.ts",
    "echo \"new Bucket(this, 'BlogBucket')\" >> lib/stack.ts",
    'printf \'resource "aws_s3_bucket" "blog" {}\' > main.tf',
    "npx ampx sandbox  # after adding defineStorage({ name: 'blog' })",
    # The typo, with and without a creation verb
    f"aws s3 ls s3://{KNOWN_TYPO}/",
    f"aws s3api create-bucket --bucket {KNOWN_TYPO}",
]

MUST_ALLOW = [
    # Every ordinary operation against the approved bucket
    f"aws s3api head-bucket --bucket {APPROVED_BUCKET}",
    f"aws s3 ls s3://{APPROVED_BUCKET}/ --recursive",
    f"aws s3api put-object --bucket {APPROVED_BUCKET} --key secure/example/a.json",
    f"aws s3api get-object --bucket {APPROVED_BUCKET} --key secure/example/a.json out.json",
    f"aws s3api list-objects-v2 --bucket {APPROVED_BUCKET} --prefix secure/example/",
    f"aws s3api get-bucket-encryption --bucket {APPROVED_BUCKET}",
    f"aws s3api get-bucket-policy --bucket {APPROVED_BUCKET}",
    f"aws s3api delete-object --bucket {APPROVED_BUCKET} --key secure/example/a.json",
    # Unrelated work that happens to mention buckets or S3
    "python3 scripts/deploy_seo_tools.py",
    "grep -rn 'Bucket' amplify/functions/ | head",
    "aws lambda get-function-configuration --function-name wecare-seo-tools",
    # The guard's own machinery and the prose stating the rule must not self-block
    "python3 scripts/block_s3_bucket_creation.py",
    "python3 scripts/verify_s3_bucket_hook.py",
    "echo 'DO NOT CREATE a bucket; use the existing one' >> notes.md",
    "grep -n \"assert 'create_bucket\" scripts/verify_s3_bucket_hook.py",
    # Empty input
    "",
]


def main() -> int:
    failures = []

    for command in MUST_BLOCK:
        blocked, reason = inspect(command)
        if not blocked:
            failures.append(f"SHOULD BLOCK but allowed: {command[:80]}")
        elif APPROVED_BUCKET not in reason:
            failures.append(f"reason does not name the approved bucket: {command[:60]}")

    for command in MUST_ALLOW:
        blocked, reason = inspect(command)
        if blocked:
            failures.append(f"SHOULD ALLOW but blocked: {command[:80]}\n    reason: {reason[:120]}")

    total = len(MUST_BLOCK) + len(MUST_ALLOW)
    if failures:
        print(f"FAIL  {len(failures)} of {total} cases wrong\n")
        for failure in failures:
            print("  " + failure)
        return 1
    print(f"OK  {total} cases  ({len(MUST_BLOCK)} blocked, {len(MUST_ALLOW)} allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
