"""Provision the exact Workspace MCP code-release OIDC role policy.

This role is intentionally code-release-only. The concurrency read is required by the
post-deploy verifier so CI can prove the live function still has its reviewed operational limit.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3

REGION = "us-east-1"
ROLE = "wecare-workspace-mcp-deploy-oidc"
POLICY = "WorkspaceMcpCodeRelease"
RESOURCES = [
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-workspace-mcp",
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-workspace-mcp:*",
]
ACTIONS = [
    "lambda:GetFunctionConfiguration",
    "lambda:GetAlias",
    "lambda:UpdateFunctionCode",
    "lambda:PublishVersion",
    "lambda:UpdateAlias",
    "lambda:GetFunction",
    "lambda:GetFunctionConcurrency",
]
DOCUMENT = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "WorkspaceMcpCodeReleaseOnly",
        "Effect": "Allow",
        "Action": ACTIONS,
        "Resource": RESOURCES,
    }],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    iam = boto3.client("iam", region_name=REGION)
    if args.apply:
        iam.put_role_policy(
            RoleName=ROLE,
            PolicyName=POLICY,
            PolicyDocument=json.dumps(DOCUMENT, separators=(",", ":")),
        )
    live = iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
    good = live == DOCUMENT
    print(json.dumps({"role": ROLE, "policy": POLICY, "verified": good, "apply": args.apply}, indent=2))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
