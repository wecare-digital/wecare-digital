#!/usr/bin/env python3
"""Configure additional Nano Climate sources using the existing Lambda and rate table.

Dry-run by default. Run only after the new gateway code has passed CI and been staged
on $LATEST (existing deploy_all_lambdas.py --no-publish path). This script never
creates a secret, changes Google API restrictions, publishes an alias or prints keys.
"""
import argparse
import json

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION = "wecare-vayulok-environment"
ROLE = "wecare-vayulok-environment-role"
TABLE = "stack-wecare-digital-RateLimitTable"
CPCB = "wecare/nano-climate/cpcb"
SOURCES = ("elevation", "cpcb", "pvgis", "solar", "spartan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", choices=SOURCES, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-google-key-and-billing", action="store_true")
    args = parser.parse_args()
    wanted = sorted(set(args.sources))
    sts = boto3.client("sts", region_name=REGION)
    if sts.get_caller_identity()["Account"] != ACCOUNT:
        raise SystemExit("Wrong AWS account")
    lam = boto3.client("lambda", region_name=REGION)
    iam = boto3.client("iam")
    ddb = boto3.client("dynamodb", region_name=REGION)
    table = ddb.describe_table(TableName=TABLE)["Table"]
    if table["TableStatus"] != "ACTIVE" or table["KeySchema"] != [{"AttributeName": "id", "KeyType": "HASH"}]:
        raise SystemExit("Unexpected live rate-limit table schema")
    config = lam.get_function_configuration(FunctionName=FUNCTION)
    if config["Role"] != f"arn:aws:iam::{ACCOUNT}:role/{ROLE}":
        raise SystemExit("Unexpected Lambda execution role")
    if args.apply and any(s in wanted for s in ("elevation", "solar")) and not args.confirm_google_key_and_billing:
        raise SystemExit("Verify the exact server key API targets, billing-account use and quotas first")
    variables = dict(config.get("Environment", {}).get("Variables", {}))
    statements = [{
        "Effect": "Allow", "Action": "dynamodb:UpdateItem",
        "Resource": table["TableArn"],
        "Condition": {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["nano-climate:environment:*"]},
                      "Null": {"dynamodb:LeadingKeys": "false"}},
    }]
    if "cpcb" in wanted:
        secrets = boto3.client("secretsmanager", region_name=REGION)
        try:
            metadata = secrets.describe_secret(SecretId=CPCB)
        except secrets.exceptions.ResourceNotFoundException:
            raise SystemExit(f"Secret {CPCB} does not exist. The owner must create it with the data.gov.in API key "
                             "before CPCB can be enabled. Nothing was changed.")
        if metadata.get("DeletedDate"):
            raise SystemExit("CPCB secret pending deletion")
        statements.append({"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": metadata["ARN"]})
        key = metadata.get("KmsKeyId")
        if key and key.startswith("arn:aws:kms:"):
            statements.append({"Effect": "Allow", "Action": "kms:Decrypt", "Resource": key,
                               "Condition": {"StringEquals": {"kms:ViaService": f"secretsmanager.{REGION}.amazonaws.com"}}})
        variables["VAYULOK_CPCB_SECRET"] = CPCB
    else:
        variables.pop("VAYULOK_CPCB_SECRET", None)
    variables["VAYULOK_EXTENDED_SOURCES"] = ",".join(wanted)
    variables["VAYULOK_EXTENDED_BUDGET_TABLE"] = TABLE
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "function": FUNCTION,
                      "sources": wanted, "table": TABLE, "secretConfigured": "cpcb" in wanted,
                      "publishedAliasChanged": False}))
    if not args.apply:
        return
    # Narrow, namespaced rights on the pre-existing table. Transactions authorize
    # their underlying UpdateItem operations. No broad table read/write grant.
    iam.put_role_policy(RoleName=ROLE, PolicyName="NanoClimateExtendedSources",
                        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements}))
    lam.update_function_configuration(FunctionName=FUNCTION, RevisionId=config["RevisionId"],
                                      Environment={"Variables": variables})
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    updated = lam.get_function_configuration(FunctionName=FUNCTION)
    actual = updated.get("Environment", {}).get("Variables", {})
    if actual.get("VAYULOK_EXTENDED_SOURCES") != ",".join(wanted) or actual.get("VAYULOK_EXTENDED_BUDGET_TABLE") != TABLE:
        raise SystemExit("Configuration read-back did not match")
    print("Configured $LATEST only; verify and use the owning Lambda alias release process.")


if __name__ == "__main__":
    main()
