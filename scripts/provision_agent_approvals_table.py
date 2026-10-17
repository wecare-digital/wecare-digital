#!/usr/bin/env python3
"""Provision the agent approvals table.

Why this table has to exist before an agent write can ever happen: the default
approval store is in-memory, and a Lambda's memory does not outlive the invocation
that created the approval. So an operator approving a plan in one request and the
apply arriving in the next has nowhere to look. With no table, every apply is
refused - which is the right default, and this is the deliberate step out of it.

The table does NOT enable anything. `governance.py` still holds every APPLY tool at
`enabled=False`, so after this an apply is still refused, just for one reason
instead of two.

Shape, and why:

  planHash (S)  partition key, no sort key. An approval is identified by the intent
                it authorises, and the plan hash IS that intent - tool, catalog
                version and canonical arguments. One row per intent means the
                single-use condition has exactly one thing to test.

  expiresTtl    DynamoDB TTL attribute. Housekeeping only. TTL deletion is
                documented as taking up to 48 hours, so an expired approval would
                stay spendable for two days if TTL were the control. The control is
                the `expiresAt > :now` condition in DynamoApprovalStore.consume.

  PAY_PER_REQUEST. Approvals are granted by a human clicking approve; the traffic is
  measured in per-day, not per-second. Provisioned capacity here would be paying a
  baseline for a table that is idle almost all of the time.

  Point-in-time recovery ON. This is an authorisation record - who approved a
  customer-facing send and when. Losing it loses the audit trail of decisions, which
  is the one thing that makes an approval worth having after the fact.

Usage:
    python scripts/provision_agent_approvals_table.py --dry-run
    python scripts/provision_agent_approvals_table.py
    python scripts/provision_agent_approvals_table.py --verify
"""

from __future__ import annotations

import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-AgentApprovalsTable"
TTL_ATTRIBUTE = "expiresTtl"


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def describe():
    try:
        return ddb().describe_table(TableName=TABLE)["Table"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise


def create(dry_run: bool) -> str:
    if describe():
        return "exists"
    if dry_run:
        return "would create (planHash PK, PAY_PER_REQUEST, TTL on expiresTtl, PITR)"

    ddb().create_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": "planHash", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "planHash", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "AgentApprovals"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)

    # TTL and PITR are separate calls and both can fail independently of create, so
    # they are applied after the waiter rather than assumed.
    for attempt in range(6):
        try:
            ddb().update_time_to_live(
                TableName=TABLE,
                TimeToLiveSpecification={"Enabled": True,
                                         "AttributeName": TTL_ATTRIBUTE})
            break
        except ClientError:
            if attempt == 5:
                raise
            time.sleep(3)

    ddb().update_continuous_backups(
        TableName=TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
    # Join the AWS Backup plan: apply the backup=daily tag (and re-affirm PITR) so
    # this table gets retained snapshots, not just continuous recovery.
    import table_backup_defaults  # scripts/, next to this file
    posture = table_backup_defaults.apply(TABLE)
    if "error" in str(posture["tagged"]):
        raise SystemExit(f"backup tag not applied for {TABLE}: {posture}")
    return "created"


def verify() -> int:
    problems: list[str] = []
    table = describe()
    if not table:
        print(f"FAIL table {TABLE} does not exist")
        return 1

    keys = [(k["AttributeName"], k["KeyType"]) for k in table.get("KeySchema", [])]
    if keys != [("planHash", "HASH")]:
        problems.append(f"key schema is {keys}, expected a single planHash hash key")

    billing = (table.get("BillingModeSummary") or {}).get("BillingMode")
    if billing != "PAY_PER_REQUEST":
        problems.append(f"billing mode is {billing}, expected PAY_PER_REQUEST")

    ttl = ddb().describe_time_to_live(TableName=TABLE).get(
        "TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("ENABLED", "ENABLING"):
        problems.append(f"TTL is {ttl.get('TimeToLiveStatus')}, expected ENABLED")
    if ttl.get("AttributeName") not in (TTL_ATTRIBUTE, None):
        problems.append(f"TTL attribute is {ttl.get('AttributeName')}, "
                        f"expected {TTL_ATTRIBUTE}")

    backups = ddb().describe_continuous_backups(TableName=TABLE)
    pitr = ((backups.get("ContinuousBackupsDescription") or {})
            .get("PointInTimeRecoveryDescription") or {})
    if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
        problems.append(
            f"PITR is {pitr.get('PointInTimeRecoveryStatus')}, expected ENABLED - "
            f"this table is the record of who authorised a customer-facing send")

    # The whole point: the table changes nothing about enablement.
    sys.path.insert(0, "amplify/functions/shared")
    from lambda_utils.agent import governance as gov
    enabled_applies = [n for n, t in gov.CATALOG.items()
                       if t.tool_class == gov.CLASS_APPLY and t.enabled]
    if enabled_applies:
        problems.append(f"APPLY tools are enabled: {enabled_applies}")

    print(f"table: {TABLE}")
    print(f"status: {table.get('TableStatus')}")
    print(f"keys: {keys}")
    print(f"billing: {billing}")
    print(f"TTL: {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}")
    print(f"PITR: {pitr.get('PointInTimeRecoveryStatus')}")
    print(f"items: {table.get('ItemCount')}")
    print(f"APPLY tools enabled: {len(enabled_applies)} (expected 0)")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\napprovals table verified; enablement unchanged")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}\ndry run: {args.dry_run}\n")
    print(f"table: {create(args.dry_run)}")
    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
