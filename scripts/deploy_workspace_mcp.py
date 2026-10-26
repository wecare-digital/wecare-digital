#!/usr/bin/env python3
"""Review an additive CloudFormation change set. Execution is a separate --execute.

For agent use, prefer the AWS MCP run_script equivalents documented in the runbook.
This SDK entry point is also usable in a CI runner where the MCP client is absent.
Optional Chat OAuth adds a dedicated Cognito client; existing clients are unchanged.
Never changes Amplify, the public /mcp route, or provider credentials.
"""
import argparse
import hashlib
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
    template_bytes = Path(manifest["template"]).read_bytes()
    template_digest = hashlib.sha256(template_bytes).hexdigest()
    if manifest.get("templateSha256", template_digest) != template_digest:
        raise SystemExit("Template checksum mismatch; rebuild the deployment manifest")
    identity = {"code": manifest["sha256"], "template": template_digest, "parameters": manifest["parameters"]}
    change_set = "workspace-mcp-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    if args.execute:
        review = cloudformation.describe_change_set(StackName=manifest["stack"], ChangeSetName=change_set)
        if review["Status"] != "CREATE_COMPLETE" or review["ExecutionStatus"] != "AVAILABLE":
            raise SystemExit("Reviewed change set is not executable")
        cloudformation.execute_change_set(StackName=manifest["stack"], ChangeSetName=change_set)
        print(json.dumps({"stack": manifest["stack"], "changeSet": change_set, "status": "execution_started"}))
        return
    archive = args.manifest.with_name("workspace-mcp.zip")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]: raise SystemExit("Bundle checksum mismatch")
    # A clean feature tree is buildable, but activation belongs to the later merge.
    session.client("s3").upload_file(str(archive), manifest["s3Bucket"], manifest["s3Key"])
    # Compact transport only; the manifest still binds the exact source bytes.
    template = json.dumps(json.loads(template_bytes), separators=(',', ':'))
    cloudformation.validate_template(TemplateBody=template)
    exists = True
    previous_parameters = set()
    try:
        previous = cloudformation.describe_stacks(StackName=manifest["stack"])["Stacks"][0]
        previous_parameters = {item["ParameterKey"] for item in previous.get("Parameters", [])}
    except cloudformation.exceptions.ClientError as exc:
        if "does not exist" not in str(exc): raise
        exists = False
    parameters = [{"ParameterKey": k, "ParameterValue": v} for k, v in manifest["parameters"].items()]
    for name in ("ChatRedirectUri", "ChatDiscoveryEnabled", "SeparateProvidersEnabled",
            'GoogleCloudRedirectUri', 'GoogleAdsRedirectUri', 'PlivoRedirectUri', 'SinchIndiaRedirectUri',
            'ProviderConfigRevision'):
        if name not in manifest["parameters"] and name in previous_parameters:
            parameters.append({"ParameterKey": name, "UsePreviousValue": True})
    cloudformation.create_change_set(StackName=manifest["stack"], ChangeSetName=change_set,
        ChangeSetType="UPDATE" if exists else "CREATE", TemplateBody=template,
        Capabilities=["CAPABILITY_NAMED_IAM"], Parameters=parameters)
    print(json.dumps({"stack": manifest["stack"], "changeSet": change_set, "status": "review_required"}))


if __name__ == "__main__": main()
