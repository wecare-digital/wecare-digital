#!/usr/bin/env python3
"""Configure additional Nano Climate sources using the existing Lambda and rate table.

Dry-run by default. Run only after the new gateway code has passed CI and been staged
on $LATEST (existing deploy_all_lambdas.py --no-publish path). This script never
creates a parameter or secret, changes Google API restrictions, publishes an alias or prints keys.
"""
import argparse
import json
import shlex

import boto3

REGION = "us-east-1"
ACCOUNT = "775261844268"
FUNCTION = "wecare-vayulok-environment"
ROLE = "wecare-vayulok-environment-role"
TABLE = "stack-wecare-digital-RateLimitTable"
CPCB = "/wecare/nano-climate/cpcb"
SOURCES = ("elevation", "cpcb", "pvgis", "solar", "spartan")


def _previous_sources(variables):
    """Capture the effective configured subset, without printing arbitrary env text."""
    previous = sorted({source.strip() for source in
                       variables.get("VAYULOK_EXTENDED_SOURCES", "").split(",")
                       if source.strip()})
    if any(source not in SOURCES for source in previous):
        raise SystemExit("Unexpected existing source selection; review it before changing configuration.")
    return previous


def _rollback_command(previous):
    selection = ["--sources", *previous] if previous else ["--disable-all"]
    return shlex.join(["python", "scripts/configure_nano_climate_sources.py",
                       *selection, "--apply"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--sources", nargs="+", choices=SOURCES)
    selection.add_argument("--disable-all", action="store_true",
                           help="Explicitly disable all extended sources (dry-run unless --apply).")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-google-key-and-billing", action="store_true")
    args = parser.parse_args()
    wanted = sorted(set(args.sources or []))
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
    previous = _previous_sources(variables)
    statements = [{
        "Effect": "Allow", "Action": "dynamodb:UpdateItem",
        "Resource": table["TableArn"],
        "Condition": {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["nano-climate:environment:*"]},
                      "Null": {"dynamodb:LeadingKeys": "false"}},
    }]
    variables.pop("VAYULOK_CPCB_SECRET", None)
    if "cpcb" in wanted:
        ssm = boto3.client("ssm", region_name=REGION)
        # Metadata only: no GetParameter or decrypted key in this operator script.
        params = ssm.describe_parameters(ParameterFilters=[
            {"Key": "Name", "Option": "Equals", "Values": [CPCB]}
        ]).get("Parameters", [])
        if (len(params) != 1 or params[0].get("Name") != CPCB
                or params[0].get("Type") != "SecureString"
                or params[0].get("Tier") != "Standard"
                or params[0].get("KeyId") != "alias/aws/ssm"):
            raise SystemExit(f"Create {CPCB} as a Standard SecureString with alias/aws/ssm first. Nothing was changed.")
        key = boto3.client("kms", region_name=REGION).describe_key(KeyId="alias/aws/ssm")["KeyMetadata"]
        if (key.get("KeyManager") != "AWS" or key.get("KeyState") != "Enabled"
                or not key.get("Arn", "").startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/")):
            raise SystemExit("Unexpected SSM encryption key. Nothing was changed.")
        parameter_arn = f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{CPCB}"
        statements.extend([
            {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": parameter_arn},
            {"Effect": "Allow", "Action": "kms:Decrypt", "Resource": key["Arn"],
             "Condition": {"StringEquals": {
                 "kms:ViaService": f"ssm.{REGION}.amazonaws.com",
                 "kms:EncryptionContext:PARAMETER_ARN": parameter_arn,
             }}},
        ])
        variables["VAYULOK_CPCB_PARAMETER"] = CPCB
    else:
        variables.pop("VAYULOK_CPCB_PARAMETER", None)
    variables["VAYULOK_EXTENDED_SOURCES"] = ",".join(wanted)
    variables["VAYULOK_EXTENDED_BUDGET_TABLE"] = TABLE
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "function": FUNCTION,
                      "sources": wanted, "previousSources": previous,
                      "table": TABLE, "secretConfigured": "cpcb" in wanted,
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
    if (actual.get("VAYULOK_EXTENDED_SOURCES") != ",".join(wanted)
            or actual.get("VAYULOK_EXTENDED_BUDGET_TABLE") != TABLE
            or actual.get("VAYULOK_CPCB_PARAMETER") != (CPCB if "cpcb" in wanted else None)
            or "VAYULOK_CPCB_SECRET" in actual):
        raise SystemExit("Configuration read-back did not match")
    print("Source-selection rollback (review live alias and shared execution-role dependencies first): "
          + _rollback_command(previous))
    if any(source in previous for source in ("elevation", "solar")):
        print("Google sources require fresh key/billing verification and --confirm-google-key-and-billing.")
    print("The command restores the previous source selection, not arbitrary prior IAM or environment "
          "settings. If rolling back a published version, use the owning live-alias release workflow first.")
    print("Configured $LATEST only; verify and use the owning Lambda alias release process.")


if __name__ == "__main__":
    main()
