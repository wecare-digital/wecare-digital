#!/usr/bin/env python3
"""Provision the WhatsApp thread ownership + standby-context table.

Why ownership has to be stored at all
-------------------------------------
Meta's Conversation Routing has **no ownership API**. The docs say so directly: an
integration must *derive* ownership and maintain it locally, from four signals — messages
it receives, `messaging_handovers` events, standby events, and Service messages it sends.
Today we maintain none of them and cannot answer "may I send on this thread?" at any
point. Under an active routing configuration a Service message from a non-owner is
rejected by Meta, so that question has a customer-visible answer.

Why a dedicated table, and not attributes on ContactsTable
----------------------------------------------------------
**One contact can hold two independent threads.** The same `wa_id` talks to both WABA
phone numbers (…4400 and …0044), and those two threads can have different owners at the
same moment. A contact-keyed attribute cannot represent two ownership states for one
contact, so the thread — not the person — has to be the key.

And explicitly **not** `SystemConfigTable`. Its `_store_system_event` ring buffer keeps
the **last 10 events per type**, inserting at index 0 unconditionally. That is an audit
sample, not state: the ten handover events surviving from Jul-Aug 2026 are all that is
left of that whole period. Ownership that silently falls out of a 10-deep buffer is worse
than no ownership, because it reads as present.

Why one table with a sort key rather than two tables
----------------------------------------------------
The standby context and the ownership it informs are read **together** at the one moment
that matters — when control is gained, the docs direct you to retrieve the standby events
you stored so you can see what the other responder was handling. Two tables would mean two
reads on that path and two things to keep consistent.

Shape, and why
--------------
  threadKey (S)   HASH. `{phone_number_id}#{bsuid or wa_id}`, composed by
                  `lambda_utils.thread_ownership.thread_key`. **BSUID-preferred, wa_id
                  fallback**, because Meta's own guidance is to index standby events by
                  business-scoped user ID, and because a BSUID is stable where a wa_id can
                  change (a `user_changed_user_id` system message is a real event this
                  handler already processes). The phone id is in the key because of the
                  two-threads-per-contact fact above.

  recordType (S)  RANGE.
                    'OWNER'                -> the one ownership row for that thread
                    'SB#<epoch>#<wamid>'   -> one standby-context row per standby message
                  A sort key rather than a second table so that gaining control is a single
                  `query` on the partition: the owner row and the context that explains it
                  come back together.

  TTL on expiresAt, 7 days. Ownership is operational routing state, not a record of what a
  customer was told, so a dormant thread should self-clean. 7 days rather than 1: the
  documented idle reset is 24 hours, and state that expired at exactly the reset boundary
  could not be *reconciled against* that reset — you need to still be holding the stale
  value to notice it went idle.

  PAY_PER_REQUEST. Volume tracks inbound WhatsApp traffic, which is 473 real customer
  messages in 30 days. Provisioned capacity would pay a baseline for an idle table.

  Point-in-time recovery ON. Cheap, and this table will eventually gate sends.

No IAM change is needed: the inline `wecare-digital-lambda-permissions` policy on
`wecare-digital-lambda-role` already grants DynamoDB on `table/stack-wecare-digital-*`
and `/index/*`, verified against the live role. A wildcard narrowing here would widen
nothing but a narrowing elsewhere would affect the whole fleet, which shares that role.

Usage:
    .venv/bin/python scripts/provision_thread_ownership_table.py --dry-run
    .venv/bin/python scripts/provision_thread_ownership_table.py
    .venv/bin/python scripts/provision_thread_ownership_table.py --verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-ThreadOwnershipTable"

HASH_KEY = "threadKey"
RANGE_KEY = "recordType"
TTL_ATTRIBUTE = "expiresAt"

#: Only key attributes. DynamoDB is schemaless for the rest and rejects a non-key
#: attribute declared here.
ATTRIBUTES: dict[str, str] = {
    HASH_KEY: "S",
    RANGE_KEY: "S",
}


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
        return (f"would create ({HASH_KEY} HASH + {RANGE_KEY} RANGE, PAY_PER_REQUEST, "
                f"no GSI, TTL on {TTL_ATTRIBUTE}, PITR)")

    ddb().create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": t}
                              for a, t in sorted(ATTRIBUTES.items())],
        KeySchema=[{"AttributeName": HASH_KEY, "KeyType": "HASH"},
                   {"AttributeName": RANGE_KEY, "KeyType": "RANGE"}],
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "WhatsAppThreadOwnership"},
            {"Key": "managed-by", "Value": "script:provision_thread_ownership_table"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)

    # TTL and PITR are separate calls that can fail independently of create, so they are
    # applied after the waiter rather than assumed to have happened.
    ddb().update_time_to_live(
        TableName=TABLE,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE})
    ddb().update_continuous_backups(
        TableName=TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})
    return "created"


def verify() -> int:
    problems: list[str] = []
    table = describe()
    if not table:
        print(f"FAIL table {TABLE} does not exist")
        return 1

    keys = [(k["AttributeName"], k["KeyType"]) for k in table.get("KeySchema", [])]
    expected_keys = [(HASH_KEY, "HASH"), (RANGE_KEY, "RANGE")]
    if keys != expected_keys:
        problems.append(f"key schema is {keys}, expected {expected_keys} - the sort key is "
                        f"what lets the owner row and its standby context be read together")

    billing = (table.get("BillingModeSummary") or {}).get("BillingMode")
    if billing != "PAY_PER_REQUEST":
        problems.append(f"billing mode is {billing}, expected PAY_PER_REQUEST")

    if table.get("GlobalSecondaryIndexes"):
        problems.append("unexpected GSI - every access path here is by threadKey")

    ttl = ddb().describe_time_to_live(TableName=TABLE).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("ENABLED", "ENABLING"):
        problems.append(f"TTL is {ttl.get('TimeToLiveStatus')}, expected ENABLED on "
                        f"{TTL_ATTRIBUTE} - this is operational state, not a record of "
                        f"what a customer was told, so a dormant thread must self-clean")
    elif ttl.get("AttributeName") not in (TTL_ATTRIBUTE, None):
        problems.append(f"TTL is on {ttl.get('AttributeName')}, expected {TTL_ATTRIBUTE}")

    backups = ddb().describe_continuous_backups(TableName=TABLE)
    pitr = ((backups.get("ContinuousBackupsDescription") or {})
            .get("PointInTimeRecoveryDescription") or {})
    if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
        problems.append(f"PITR is {pitr.get('PointInTimeRecoveryStatus')}, expected ENABLED")

    # The shape has to match what the module writes, or the table is right and unusable.
    # Checked against the module rather than against a copy of its field names.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "amplify" / "functions" / "shared"))
    from lambda_utils import thread_ownership as to
    if to.TABLE_HASH_KEY != HASH_KEY or to.TABLE_RANGE_KEY != RANGE_KEY:
        problems.append(f"thread_ownership keys on "
                        f"({to.TABLE_HASH_KEY}, {to.TABLE_RANGE_KEY}), table keys on "
                        f"({HASH_KEY}, {RANGE_KEY})")
    if to.TABLE_NAME_DEFAULT != TABLE:
        problems.append(f"thread_ownership defaults to {to.TABLE_NAME_DEFAULT!r}, "
                        f"this script provisions {TABLE!r}")
    # BSUID-preferred, wa_id fallback. Asserted here because the key rule is the one
    # thing a later reader is most likely to 'simplify' into wa_id-only.
    if to.thread_key("PID", bsuid="BS", wa_id="91999") != f"PID#BS":
        problems.append("thread_key does not prefer BSUID over wa_id")
    if to.thread_key("PID", wa_id="91999") != "PID#91999":
        problems.append("thread_key does not fall back to wa_id")
    if to.thread_key("PID") != "":
        problems.append("thread_key must return '' when neither identifier is usable")

    print(f"table: {TABLE}")
    print(f"status: {table.get('TableStatus')}")
    print(f"keys: {keys}")
    print(f"billing: {billing}")
    print(f"TTL: {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}")
    print(f"PITR: {pitr.get('PointInTimeRecoveryStatus')}")
    print(f"items: {table.get('ItemCount')}")
    print(f"thread_key is BSUID-preferred: "
          f"{to.thread_key('PID', bsuid='BS', wa_id='91999') == 'PID#BS'}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nthread ownership table verified")
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
