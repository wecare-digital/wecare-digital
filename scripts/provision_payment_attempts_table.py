#!/usr/bin/env python3
"""Provision the payment attempts table.

Why this table exists separately from orders
--------------------------------------------
Most payment attempts never become orders, and that is normal rather than exceptional: an
abandoned checkout, a timed-out UPI mandate, a declined card. Every one leaves a record that has
to be visible to the customer and to staff, and none of them may carry an order number, appear in
order history, or produce a receipt.

So this is the only entity that exists before money moves. It deliberately has no `orderId` or
`orderNumber` attribute - the order identity lives in the reservation ledger
(`stack-wecare-digital-CommerceKeys`, reached through `order_keys.commerce_keys_table_name`) and is
minted only after a provider readback confirms capture. Keeping the two apart is what makes "an
order does not exist until payment is authoritatively verified as paid" a property of the shape
rather than a matter of discipline.

Why the name is PaymentAttemptsTable and not PaymentAttempt
----------------------------------------------------------
`scripts/check_data_model_drift.py` maps a declared model to a physical table by pluralising and
appending `Table`, with irregular cases listed one by one. `PaymentAttempt` ->
`PaymentAttemptsTable` follows that default rule exactly, so this table needs no entry in that
script's explicit map and no allowance in `PHANTOM_ALLOWED`. A name that needs an exception
recorded is a name that will be got wrong later.

Shape, and why
--------------
  paymentAttemptId (S)  partition key, no sort key. UUIDv7, minted by
                        `payment_attempt.new_payment_attempt_id`. Internal only - never shown to a
                        customer, because a customer-facing identifier on a pre-payment record is
                        how a failed attempt gets mistaken for an order.

  customerId-index      HASH customerId, RANGE createdAt. The customer's payment history, newest
                        first. The sort key is not a convenience: a retry chain can be several
                        attempts long, and a client-side sort would mean reading every attempt a
                        customer ever made to render one page.

  referenceId-index     HASH referenceId. Resolving an inbound provider event to its attempt. A
                        unique lookup, so no sort key. Note this is a SECOND path to the same
                        binding - `PAYREF#<ref>` in the reservation ledger is the authoritative,
                        conditionally-written one. This index is for reading, never for uniqueness:
                        a GSI is eventually consistent and cannot enforce a constraint.

  status-index          HASH status, RANGE createdAt. The staff view of stuck and failed attempts.
                        There are only 8 distinct status values, so the partition key is low
                        cardinality by nature; `createdAt` is what keeps a query bounded to a
                        window rather than reading an entire status partition. Same shape as
                        `eventType-index` on RazorpayWebhookLogTable.

  No TTL, deliberately. A failed attempt is the record proving no order was created, and payment
  history has to keep it. Every other short-lived table here (DownloadGrants, PstnSoftphone,
  AgentApprovals) has TTL because expiry IS the point of the record; here expiry would destroy
  the evidence. This is stated as an assertion in --verify, not just left unset, so that someone
  enabling TTL later trips a gate instead of quietly losing the history.

  PAY_PER_REQUEST. Attempt volume tracks human checkout traffic, which is per-day rather than
  per-second. Provisioned capacity would pay a baseline for a table that is idle most of the time.

  Point-in-time recovery ON. This is the record of what a customer was asked to pay and whether
  they paid it. Losing it loses the ability to answer "was this person charged", which is the one
  question that must always be answerable.

Usage:
    python scripts/provision_payment_attempts_table.py --dry-run
    python scripts/provision_payment_attempts_table.py
    python scripts/provision_payment_attempts_table.py --verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE = "stack-wecare-digital-PaymentAttemptsTable"

KEY_ATTRIBUTE = "paymentAttemptId"

#: (index name, [(attribute, key type), ...]). Names follow the `<field>-index` convention already
#: live on PaymentsTable and RazorpayWebhookLogTable, which is also what Amplify Data's
#: `index('field')` produces - so the declared model and the physical table agree on names too,
#: not only on existence.
INDEXES: list[tuple[str, list[tuple[str, str]]]] = [
    ("customerId-index", [("customerId", "HASH"), ("createdAt", "RANGE")]),
    ("referenceId-index", [("referenceId", "HASH")]),
    ("status-index", [("status", "HASH"), ("createdAt", "RANGE")]),
]

#: Only the attributes that participate in a key. DynamoDB is schemaless for the rest, and
#: declaring a non-key attribute here is rejected.
ATTRIBUTES: dict[str, str] = {
    KEY_ATTRIBUTE: "S",
    "customerId": "S",
    "referenceId": "S",
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


def create(dry_run: bool) -> str:
    if describe():
        return "exists"
    if dry_run:
        return (f"would create ({KEY_ATTRIBUTE} PK, PAY_PER_REQUEST, "
                f"{len(INDEXES)} GSIs, NO TTL, PITR)")

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
            {"Key": "Purpose", "Value": "PaymentAttempts"},
            {"Key": "managed-by", "Value": "script:provision_payment_attempts_table"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)

    # PITR is a separate call that can fail independently of create, so it is applied after the
    # waiter rather than assumed to have happened.
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

    # TTL must stay OFF. Asserted rather than merely left unset: a failed attempt is the record
    # proving no order was created, so a TTL here would delete the evidence that a customer was
    # not charged twice. Someone enabling it later should trip this, not discover it from a gap.
    ttl = ddb().describe_time_to_live(TableName=TABLE).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("DISABLED", "DISABLING", None):
        problems.append(
            f"TTL is {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}, expected "
            f"DISABLED - payment history must keep failed attempts as the proof no order exists")

    backups = ddb().describe_continuous_backups(TableName=TABLE)
    pitr = ((backups.get("ContinuousBackupsDescription") or {})
            .get("PointInTimeRecoveryDescription") or {})
    if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
        problems.append(
            f"PITR is {pitr.get('PointInTimeRecoveryStatus')}, expected ENABLED - this table "
            f"answers 'was this person charged', which must always be answerable")

    # The shape has to match what the module writes, or the table is right and unusable. Checked
    # against the module rather than a copy of its field names.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "amplify" / "functions" / "shared"))
    from lambda_utils.ecommerce import payment_attempt as pa
    sample = pa.build(customer_id="CUS_TEST", reference_id="WDPAY_TEST",
                      amount_paise=100, configuration_name="test")
    for attribute in (KEY_ATTRIBUTE, "customerId", "referenceId", "status", "createdAt"):
        if attribute not in sample:
            problems.append(f"payment_attempt.build() does not emit {attribute}, "
                            f"which this table keys on")
    for forbidden in ("orderId", "orderNumber"):
        if forbidden in sample:
            problems.append(
                f"payment_attempt.build() emits {forbidden!r}; an attempt must carry no order "
                f"identity, or a failed payment can be mistaken for an order")

    print(f"table: {TABLE}")
    print(f"status: {table.get('TableStatus')}")
    print(f"keys: {keys}")
    print(f"billing: {billing}")
    for name in sorted(live_indexes):
        print(f"GSI {name}: {live_indexes[name]}")
    print(f"TTL: {ttl.get('TimeToLiveStatus')} (expected DISABLED)")
    print(f"PITR: {pitr.get('PointInTimeRecoveryStatus')}")
    print(f"items: {table.get('ItemCount')}")
    print(f"attempt record carries no order identity: "
          f"{'orderId' not in sample and 'orderNumber' not in sample}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\npayment attempts table verified")
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
