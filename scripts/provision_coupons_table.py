#!/usr/bin/env python3
"""Provision the coupons table.

Why one table with namespaced rows
----------------------------------
Four row types share one partition attribute, `couponKey`:

    COUPON#<codeUpper>                      the definition
    COUPONUSE#<codeUpper>#<customerId>      per-customer usage counter
    COUPONHOLD#<codeUpper>#<cartId>         a short-lived eligibility reservation
    COUPONREDEEM#<codeUpper>#<orderId>      idempotent terminal redemption record

The same namespaced-row shape `order_keys` uses for the CommerceKeys table, and for the same
reason: the uniqueness guarantee has to be a conditional write ON THE PARTITION KEY. A GSI is eventually consistent, so it
cannot enforce a constraint, and a sort key would change the shape of every row type to serve one.

Why the name is CouponsTable and not Coupon
-------------------------------------------
`scripts/check_data_model_drift.py` maps a declared model to a physical table by pluralising and
appending `Table`, so `Coupon` -> `CouponsTable` follows that default rule and needs no entry in
that script's explicit map.

It DOES need an `UNDECLARED_ALLOWED` allowance, and that is a different list from the one
`provision_payment_attempts_table.py`'s docstring talks about. `PaymentAttempt` is a declared model
in `amplify/data/resource.ts`; `Coupon` is not, deliberately - this table is the coupon ledger
(definitions, usage counters, holds and redemptions), not part of the CRM data model. So a live table with no declared
model lands in `undeclared_tables`, then in `undeclared_tables_unexpected`, and `--gate` exits
non-zero until the allowance is added. That edit is owned by the shared-gate step, not by this
script.

TTL IS DISABLED AND THAT IS LOAD-BEARING
----------------------------------------
A coupon row is the record of what discount was promised and how often it was used. An expired
coupon must still be READABLE long after it stops being APPLICABLE, because a settled order
references it and a disappearing definition makes that order unauditable. Expiry is a field, never
a deletion.

The one row type permitted to vanish is `COUPONHOLD#`, and `coupon_store` deletes it explicitly on
release. A TTL would make that expiry silent, which is the opposite of what a reservation needs.

Asserted in `--verify` rather than merely left unset, so someone enabling TTL later trips a gate
instead of discovering it from a gap in the history.

Point-in-time recovery ON. This table answers "what was this customer promised, and had they
already used it" - a question that has to stay answerable after a mistake.

Usage:
    python scripts/provision_coupons_table.py              # dry run, the default
    python scripts/provision_coupons_table.py --apply
    python scripts/provision_coupons_table.py --verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-CouponsTable"

KEY_ATTRIBUTE = "couponKey"

#: `status-index` is SPARSE: only definition rows carry `status`, so counters, holds and
#: redemption records never enter it. `createdAt` is the range key because there are only three
#: status values - a low-cardinality partition that a range key keeps bounded to a window
#: instead of reading whole. Name follows the `<field>-index` convention already live on
#: PaymentsTable and PaymentAttemptsTable.
INDEXES: list[tuple[str, list[tuple[str, str]]]] = [
    ("status-index", [("status", "HASH"), ("createdAt", "RANGE")]),
]

#: Only key-participating attributes. DynamoDB is schemaless for the rest and rejects a
#: non-key attribute declared here.
ATTRIBUTES: dict[str, str] = {
    KEY_ATTRIBUTE: "S",
    "status": "S",
    "createdAt": "N",
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


def create(apply: bool) -> str:
    if describe():
        return "exists"
    if not apply:
        return (f"would create ({KEY_ATTRIBUTE} PK, PAY_PER_REQUEST, "
                f"{len(INDEXES)} GSI, NO TTL, PITR)")

    ddb().create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": t}
                              for a, t in sorted(ATTRIBUTES.items())],
        KeySchema=[{"AttributeName": KEY_ATTRIBUTE, "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": name,
                "KeySchema": [{"AttributeName": a, "KeyType": k} for a, k in keys],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name, keys in INDEXES
        ],
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "Coupons"},
            {"Key": "managed-by", "Value": "script:provision_coupons_table"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)

    # PITR is a separate call that can fail independently of create, so it is applied
    # after the waiter rather than assumed to have happened. Kept as an explicit call
    # here (not only via the helper below) because the create path must demonstrably
    # turn PITR on rather than rely on a default — see
    # tests/test_coupons_iam_and_table.py.
    ddb().update_continuous_backups(
        TableName=TABLE,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True})

    # Also apply the AWS Backup selection tag (`backup=daily`) so the table joins
    # `wecare-backup-plan` for retained snapshots. The shared helper is the standard
    # one-line call for new table scripts; its PITR step is an idempotent re-affirm
    # of the explicit enable above.
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
    if keys != [(KEY_ATTRIBUTE, "HASH")]:
        problems.append(f"key schema is {keys}, expected a single {KEY_ATTRIBUTE} hash key")

    billing = (table.get("BillingModeSummary") or {}).get("BillingMode")
    if billing != "PAY_PER_REQUEST":
        problems.append(f"billing mode is {billing}, expected PAY_PER_REQUEST")

    live_indexes = {
        i["IndexName"]: [(k["AttributeName"], k["KeyType"]) for k in i["KeySchema"]]
        for i in table.get("GlobalSecondaryIndexes") or []
    }
    for name, expected in INDEXES:
        if name not in live_indexes:
            problems.append(f"missing GSI {name}")
        elif live_indexes[name] != expected:
            problems.append(f"GSI {name} keys are {live_indexes[name]}, expected {expected}")
    for extra in sorted(set(live_indexes) - {n for n, _ in INDEXES}):
        problems.append(f"unexpected GSI {extra}")

    # TTL must stay OFF. A coupon definition is the record of what was promised, and a settled
    # order references it - deleting it makes that order unauditable. Expiry is a field.
    ttl = ddb().describe_time_to_live(TableName=TABLE).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("DISABLED", "DISABLING", None):
        problems.append(
            f"TTL is {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}, expected "
            f"DISABLED - an expired coupon must stay readable for the orders that cite it")

    backups = ddb().describe_continuous_backups(TableName=TABLE)
    pitr = ((backups.get("ContinuousBackupsDescription") or {})
            .get("PointInTimeRecoveryDescription") or {})
    if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
        problems.append(
            f"PITR is {pitr.get('PointInTimeRecoveryStatus')}, expected ENABLED - this table "
            f"answers 'what was this customer promised', which must stay answerable")

    # The shape has to match what the module writes, or the table is right and unusable.
    # Checked against the module rather than against a copy of its field names.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "amplify" / "functions" / "shared"))
    from lambda_utils.ecommerce import coupon_store
    sample = coupon_store.validate_definition(
        {"code": "VERIFY", "name": "verification probe", "discountKind": "MONEY_OFF",
         "moneyOffPaise": 10000, "startTimeMs": coupon_store.MIN_EPOCH_MS,
         "minimumSubtotalPaise": 100000},
        clock=lambda: 1700000000)
    for attribute in (KEY_ATTRIBUTE, "status", "createdAt"):
        if attribute not in sample:
            problems.append(f"coupon_store.validate_definition() does not emit {attribute}, "
                            f"which this table keys on")
    if coupon_store.DEFAULT_TABLE_NAME != TABLE:
        problems.append(f"coupon_store targets {coupon_store.DEFAULT_TABLE_NAME}, not {TABLE}")
    if coupon_store.STATUS_INDEX != INDEXES[0][0]:
        problems.append(f"coupon_store queries {coupon_store.STATUS_INDEX}, "
                        f"not {INDEXES[0][0]}")

    print(f"table: {TABLE}")
    print(f"status: {table.get('TableStatus')}")
    print(f"keys: {keys}")
    print(f"billing: {billing}")
    for name in sorted(live_indexes):
        print(f"GSI {name}: {live_indexes[name]}")
    print(f"TTL: {ttl.get('TimeToLiveStatus')} (expected DISABLED)")
    print(f"PITR: {pitr.get('PointInTimeRecoveryStatus')}")
    print(f"items: {table.get('ItemCount')}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ncoupons table verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="create the table; without it this is a dry run")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}\napply: {args.apply}\n")
    print(f"table: {create(args.apply)}")
    if not args.apply:
        print("\ndry run: nothing changed")
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
