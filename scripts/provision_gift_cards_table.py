#!/usr/bin/env python3
"""Provision the gift-card ledger table, encrypted with a CUSTOMER-MANAGED KMS key.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md`
section 6, and DECISION 6 of that task's `plan.md`.

One table, six row types, one partition attribute
-------------------------------------------------
    GIFTCARD#<codeHash>                        the card: balance, status, expiry
    GCORDER#<codeHash>#<paymentAttemptId>      idempotency claim, carries the winning transactionId
    GCWIXORDER#<wixOrderId>                    pointer -> paymentAttemptId, at WIX_ORDER_CREATED
    GCTXN#<codeHash>#<transactionId>           the transaction record (REDEEM or VOID)
    GCTXNID#<transactionId>                    reverse index -> {codeHash, paymentAttemptId}
    GCHOLD#<codeHash>#<paymentAttemptId>       reservation taken at checkout initiation
    GCID#<giftCardId>                          pointer -> codeHash, for the staff read by our own id

Namespaced rows on a single partition key, the same shape `stack-wecare-digital-WixOrderIds` uses,
because the uniqueness guarantee has to be a conditional write ON THE PARTITION KEY. A GSI is
eventually consistent and so cannot enforce a constraint, and a sort key would change the shape of
every row type to serve one.

THE PARTITION KEY IS NEVER THE CODE
-----------------------------------
`codeHash` is `HMAC-SHA256(pepper, NFKC(code).upper()).hexdigest()`. The SPI bounds a code at 8-20
characters, which is inside brute-force range for a PLAIN hash, so a leaked table would expose live
balances. The pepper lives in Secrets Manager and never reaches this script - nothing here reads a
secret, and nothing here needs to.

DECISION 6: A CUSTOMER-MANAGED KEY, WHICH IS NEW GROUND IN THIS REPOSITORY
--------------------------------------------------------------------------
No other `scripts/provision_*.py` sets `SSESpecification` and no script in this repository creates a
CMK, so this is the first. The table is created with

    SSESpecification = {"Enabled": True, "SSEType": "KMS",
                        "KMSMasterKeyId": "alias/wecare-gift-cards"}

and the alias indirection is deliberate: a key ARN is not known until the key is created, so the
provisioner and the two role policies have to agree on a NAME rather than on a dated ARN.

**KMS key creation requires pointwise owner confirmation** (`maintenance-reporting.md` lists "KMS
create/delete" explicitly), so it is behind `--apply` and is recorded as an owner item. A dry run is
the default and prints what it would create.

TTL IS DISABLED, AND HERE IT IS STRONGER THAN A CONVENTION
----------------------------------------------------------
A gift-card row is a LIABILITY - a balance we owe a customer. An expiring row is a disappearing
debt. Expiry of the card is a FIELD (`expiresAtMs`) that changes what is PERMITTED; it never removes
what is OWED. Asserted in `--verify` rather than merely left unset, so someone enabling TTL later
trips a gate instead of discovering it from a gap in the history.

Point-in-time recovery ON. This table answers "what do we still owe this customer", which has to
stay answerable after a mistake.

Usage:
    python scripts/provision_gift_cards_table.py              # dry run, the default
    python scripts/provision_gift_cards_table.py --apply      # creates the CMK: owner-confirmed
    python scripts/provision_gift_cards_table.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"

#: The one account this project uses. Not a credential - an account id is public in every ARN this
#: repository already commits.
ACCOUNT_ID = "775261844268"

TABLE = "stack-wecare-digital-GiftCardsTable"
KEY_ATTRIBUTE = "giftCardKey"

#: DECISION 6. The alias is what the table and both role policies name, because the key ARN does not
#: exist until the key is created.
KMS_ALIAS = "alias/wecare-gift-cards"
KMS_DESCRIPTION = "Encrypts stack-wecare-digital-GiftCardsTable, the gift-card liability ledger"

#: `status-index` is SPARSE: only card rows carry `status`, so transactions, claims, holds and
#: pointer rows never enter it. `createdAt` is the range key because there are only two status
#: values - a low-cardinality partition that a range key keeps bounded to a window instead of
#: reading whole. Name follows the `<field>-index` convention already live on PaymentsTable,
#: PaymentAttemptsTable and CouponsTable.
INDEXES: list[tuple[str, list[tuple[str, str]]]] = [
    ("status-index", [("status", "HASH"), ("createdAt", "RANGE")]),
]

#: Only key-participating attributes. DynamoDB is schemaless for the rest and rejects a non-key
#: attribute declared here.
ATTRIBUTES: dict[str, str] = {
    KEY_ATTRIBUTE: "S",
    "status": "S",
    "createdAt": "N",
}

#: The two least-privilege roles that need to use the key. Named here so the key policy and
#: `provision_gift_cards_roles.py` cannot disagree about who may decrypt.
CONSUMER_ROLES = ("wecare-gift-cards-role",)


def ddb():
    return boto3.client("dynamodb", region_name=REGION)


def kms():
    return boto3.client("kms", region_name=REGION)


def key_policy() -> dict:
    """The CMK's key policy, built with no AWS call.

    A pure function so a contract test can assert over this exact document offline. Three
    statements, and the second is the one that matters:

    * the account root keeps administrative control, which is required - a key policy that locks out
      the account is unrecoverable;
    * the native consumer role may `Decrypt` and `GenerateDataKey` ONLY through DynamoDB, enforced by
      `kms:ViaService`. Without that condition the grant would let the function decrypt arbitrary
      ciphertext under this key, which is a wider capability than reading the table;
    * nothing is granted to `*`, to the shared fleet role, or to any other principal.
    """
    return {
        "Version": "2012-10-17",
        "Id": "wecare-gift-cards-key-policy",
        "Statement": [
            {
                "Sid": "AccountRootAdministration",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT_ID}:root"},
                "Action": "kms:*",
                "Resource": "*",
            },
            {
                "Sid": "GiftCardRolesViaDynamoDBOnly",
                "Effect": "Allow",
                "Principal": {"AWS": [f"arn:aws:iam::{ACCOUNT_ID}:role/{role}"
                                      for role in CONSUMER_ROLES]},
                "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
                "Resource": "*",
                "Condition": {"StringEquals": {
                    "kms:ViaService": f"dynamodb.{REGION}.amazonaws.com"}},
            },
        ],
    }


def describe():
    try:
        return ddb().describe_table(TableName=TABLE)["Table"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise


def find_alias() -> str:
    """The key ARN behind `alias/wecare-gift-cards`, or `""`."""
    try:
        described = kms().describe_key(KeyId=KMS_ALIAS)
        return described["KeyMetadata"]["Arn"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("NotFoundException", "AccessDeniedException"):
            return ""
        raise


def ensure_key(apply: bool) -> str:
    """Create the CMK and its alias, or report the existing one.

    OWNER-CONFIRMED ACTION. `maintenance-reporting.md` requires pointwise confirmation for a KMS
    create, so this does nothing without `--apply` and the caller is expected to have obtained that
    confirmation. Key rotation is enabled: a liability ledger outlives any single key year.
    """
    existing = find_alias()
    if existing:
        return f"exists ({existing})"
    if not apply:
        return (f"would create a symmetric CMK with rotation enabled and alias {KMS_ALIAS} "
                f"- OWNER CONFIRMATION REQUIRED")
    created = kms().create_key(
        Description=KMS_DESCRIPTION,
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        Policy=json.dumps(key_policy()),
        Tags=[{"TagKey": "Project", "TagValue": "WECARE.DIGITAL"},
              {"TagKey": "Purpose", "TagValue": "GiftCards"}],
    )["KeyMetadata"]
    kms().enable_key_rotation(KeyId=created["KeyId"])
    kms().create_alias(AliasName=KMS_ALIAS, TargetKeyId=created["KeyId"])
    return f"created ({created['Arn']})"


def create(apply: bool) -> str:
    if describe():
        return "exists"
    if not apply:
        return (f"would create ({KEY_ATTRIBUTE} PK, PAY_PER_REQUEST, {len(INDEXES)} GSI, "
                f"SSE KMS via {KMS_ALIAS}, NO TTL, PITR)")
    if not find_alias():
        raise SystemExit(f"refusing to create {TABLE} before {KMS_ALIAS} exists: the table would "
                         f"fall back to an AWS-owned key and DECISION 6 requires a CMK")

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
        # DECISION 6. The alias, never a dated ARN.
        SSESpecification={"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": KMS_ALIAS},
        Tags=[
            {"Key": "Project", "Value": "WECARE.DIGITAL"},
            {"Key": "Purpose", "Value": "GiftCards"},
            {"Key": "managed-by", "Value": "script:provision_gift_cards_table"},
        ],
    )
    ddb().get_waiter("table_exists").wait(TableName=TABLE)

    # PITR is a separate call that can fail independently of create, so it is applied after the
    # waiter rather than assumed to have happened.
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

    # DECISION 6. An AWS-owned key reads as `SSEDescription` absent, which is the default and is
    # exactly what must not be true here.
    sse = table.get("SSEDescription") or {}
    key_arn = find_alias()
    if sse.get("Status") != "ENABLED" or sse.get("SSEType") != "KMS":
        problems.append(f"SSE is {sse.get('Status')}/{sse.get('SSEType')}, expected ENABLED/KMS "
                        f"with a customer-managed key")
    elif key_arn and sse.get("KMSMasterKeyArn") != key_arn:
        problems.append(f"the table is encrypted with {sse.get('KMSMasterKeyArn')}, not the "
                        f"{KMS_ALIAS} key {key_arn}")
    if not key_arn:
        problems.append(f"{KMS_ALIAS} does not resolve to a key")
    else:
        rotation = kms().get_key_rotation_status(KeyId=key_arn)
        if not rotation.get("KeyRotationEnabled"):
            problems.append("key rotation is disabled on the gift-card CMK")
        live_policy = json.loads(kms().get_key_policy(
            KeyId=key_arn, PolicyName="default")["Policy"])
        via_service = [((s.get("Condition") or {}).get("StringEquals") or {}).get("kms:ViaService")
                       for s in live_policy.get("Statement", [])
                       if s.get("Sid") == "GiftCardRolesViaDynamoDBOnly"]
        if via_service != [f"dynamodb.{REGION}.amazonaws.com"]:
            problems.append(f"the key policy's ViaService condition is {via_service}, expected "
                            f"['dynamodb.{REGION}.amazonaws.com']")

    # TTL must stay OFF. A gift-card row is a liability; an expiring row is a disappearing debt.
    ttl = ddb().describe_time_to_live(TableName=TABLE).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") not in ("DISABLED", "DISABLING", None):
        problems.append(
            f"TTL is {ttl.get('TimeToLiveStatus')} on {ttl.get('AttributeName')}, expected "
            f"DISABLED - a gift-card balance is money we owe and must not expire silently")

    backups = ddb().describe_continuous_backups(TableName=TABLE)
    pitr = ((backups.get("ContinuousBackupsDescription") or {})
            .get("PointInTimeRecoveryDescription") or {})
    if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
        problems.append(
            f"PITR is {pitr.get('PointInTimeRecoveryStatus')}, expected ENABLED - this table "
            f"answers 'what do we still owe', which must stay answerable")

    # The shape has to match what the module writes, or the table is right and unusable. Checked
    # against the module rather than against a copy of its field names.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "amplify" / "functions" / "shared"))
    from lambda_utils.ecommerce import gift_card_store
    if gift_card_store.DEFAULT_TABLE_NAME != TABLE:
        problems.append(f"gift_card_store targets {gift_card_store.DEFAULT_TABLE_NAME}, "
                        f"not {TABLE}")
    if gift_card_store.STATUS_INDEX != INDEXES[0][0]:
        problems.append(f"gift_card_store queries {gift_card_store.STATUS_INDEX}, "
                        f"not {INDEXES[0][0]}")
    if gift_card_store.KEY_ATTRIBUTE != KEY_ATTRIBUTE:
        problems.append(f"gift_card_store keys on {gift_card_store.KEY_ATTRIBUTE}")

    print(f"table: {TABLE}")
    print(f"status: {table.get('TableStatus')}")
    print(f"keys: {keys}")
    print(f"billing: {billing}")
    for name in sorted(live_indexes):
        print(f"GSI {name}: {live_indexes[name]}")
    print(f"SSE: {sse.get('Status')}/{sse.get('SSEType')} key {sse.get('KMSMasterKeyArn')}")
    print(f"alias: {KMS_ALIAS} -> {key_arn or 'MISSING'}")
    print(f"TTL: {ttl.get('TimeToLiveStatus')} (expected DISABLED)")
    print(f"PITR: {pitr.get('PointInTimeRecoveryStatus')}")
    print(f"items: {table.get('ItemCount')}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\ngift-cards table verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="create the CMK and the table; without it this is a dry run")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()

    print(f"region: {REGION}\napply: {args.apply}\n")
    print(f"kms key: {ensure_key(args.apply)}")
    print(f"table: {create(args.apply)}")
    if not args.apply:
        print("\ndry run: nothing changed")
        print("\nKMS key creation is an OWNER CONFIRMATION item (maintenance-reporting.md).")
        print(json.dumps(key_policy(), indent=2))
        return 0
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
