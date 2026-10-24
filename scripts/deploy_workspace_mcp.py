#!/usr/bin/env python3
"""Review an additive CloudFormation change set. Execution is a separate --execute.

For agent use, prefer the AWS MCP run_script equivalents documented in the runbook.
This SDK entry point is also usable in a CI runner where the MCP client is absent.
Never changes Amplify, Cognito configuration, public /mcp, or provider credentials.
"""
import argparse
import json
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    import subprocess
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
    if branch != "wecare.digital": raise SystemExit("Deploy after merging to wecare.digital; this feature branch is build-only")
    manifest = json.loads(args.manifest.read_text())
    session = boto3.Session(profile_name="wecare-prod", region_name="us-east-1")
    if session.client("sts").get_caller_identity()["Account"] != "775261844268": raise SystemExit("Wrong AWS account")
    cloudformation = session.client("cloudformation")
    change_set = "workspace-mcp-" + manifest["sha256"][:24]
    if args.execute:
        review = cloudformation.describe_change_set(StackName=manifest["stack"], ChangeSetName=change_set)
        if review["Status"] != "CREATE_COMPLETE" or review["ExecutionStatus"] != "AVAILABLE":
            raise SystemExit("Reviewed change set is not executable")
        cloudformation.execute_change_set(StackName=manifest["stack"], ChangeSetName=change_set)
        print(json.dumps({"stack": manifest["stack"], "changeSet": change_set, "status": "execution_started"}))
        return
    archive = args.manifest.with_name("workspace-mcp.zip")
    import hashlib
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]: raise SystemExit("Bundle checksum mismatch")
    # A clean feature tree is buildable, but activation belongs to the later merge.
    session.client("s3").upload_file(str(archive), manifest["s3Bucket"], manifest["s3Key"])
    template = Path(manifest["template"]).read_text()
    cloudformation.validate_template(TemplateBody=template)
    exists = True
    try: cloudformation.describe_stacks(StackName=manifest["stack"])
    except cloudformation.exceptions.ClientError as exc:
        if "does not exist" not in str(exc): raise
        exists = False
    cloudformation.create_change_set(StackName=manifest["stack"], ChangeSetName=change_set,
        ChangeSetType="UPDATE" if exists else "CREATE", TemplateBody=template,
        Capabilities=["CAPABILITY_NAMED_IAM"], Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in manifest["parameters"].items()])
    print(json.dumps({"stack": manifest["stack"], "changeSet": change_set, "status": "review_required"}))


if __name__ == "__main__": main()
