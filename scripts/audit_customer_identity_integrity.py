#!/usr/bin/env python3
"""Read-only cross-channel customer identity integrity audit.

Checks Contacts -> Orders -> Messages -> Flow submissions -> Invoices -> Payment attempts.
Outputs counts only; never prints phone numbers, emails, customer IDs, or message content.
Dependent tables are processed page-by-page with narrow projections so production scans are bounded
by one DynamoDB page rather than buffered in memory.
Exit 0 = clean, 1 = integrity gaps found, 2 = AWS/read error.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
TABLES = {
    "contacts": "stack-wecare-digital-ContactsTable",
    "orders": "stack-wecare-digital-OrderTable",
    "messages": "stack-wecare-digital-MessagesTable",
    "flows": "stack-wecare-digital-FlowSubmissionTable",
    "invoices": "stack-wecare-digital-InvoicesTable",
    "attempts": "stack-wecare-digital-PaymentAttemptsTable",
}


def pages(table, **kwargs):
    start = None
    while True:
        args = dict(kwargs)
        if start:
            args["ExclusiveStartKey"] = start
        page = table.scan(**args)
        yield page.get("Items") or []
        start = page.get("LastEvaluatedKey")
        if not start:
            return


def live(row):
    return (
        not row.get("deletedAt")
        and not row.get("isDeleted")
        and str(row.get("mergeState") or "").lower() != "merged"
    )


def dependent_counts(table, active_ids, *, orders=False):
    counts = {
        "total": 0,
        "missingContactId": 0,
        "orphanContactId": 0,
    }
    projection = "contactId"
    if orders:
        projection += ",finalizationStage,customerUuid"
        counts["finalizedMissingContactId"] = 0
        counts["finalizedMissingCustomerUuid"] = 0

    for rows in pages(table, ProjectionExpression=projection):
        for row in rows:
            counts["total"] += 1
            contact_id = str(row.get("contactId") or "")
            if not contact_id:
                counts["missingContactId"] += 1
            elif contact_id not in active_ids:
                counts["orphanContactId"] += 1
            if orders and row.get("finalizationStage") == "ORDER_FINALIZED":
                if not contact_id:
                    counts["finalizedMissingContactId"] += 1
                if not row.get("customerUuid"):
                    counts["finalizedMissingCustomerUuid"] += 1
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        ddb = boto3.resource("dynamodb", region_name=args.region)
        contacts_table = ddb.Table(TABLES["contacts"])

        active_ids = set()
        phones = defaultdict(set)
        emails = defaultdict(set)
        uuids = defaultdict(set)
        contact_counts = {
            "total": 0,
            "live": 0,
            "idContactIdMismatches": 0,
            "nonCanonicalPhones": 0,
            "brokenMergeAliases": 0,
        }
        merged_targets = []

        contact_projection = (
            "#id,contactId,phone,email,customerUuid,deletedAt,isDeleted,"
            "mergeState,mergedIntoContactId"
        )
        for rows in pages(
            contacts_table,
            ProjectionExpression=contact_projection,
            ExpressionAttributeNames={"#id": "id"},
        ):
            for row in rows:
                contact_counts["total"] += 1
                cid = str(row.get("id") or row.get("contactId") or "")
                if str(row.get("mergeState") or "").lower() == "merged":
                    merged_targets.append(str(row.get("mergedIntoContactId") or ""))
                    continue
                if not live(row):
                    continue
                contact_counts["live"] += 1
                if cid:
                    active_ids.add(cid)
                if row.get("id") and row.get("contactId") and row["id"] != row["contactId"]:
                    contact_counts["idContactIdMismatches"] += 1

                phone = str(row.get("phone") or "")
                digits = "".join(ch for ch in phone if ch.isdigit())
                if phone:
                    if not (
                        phone.startswith("+")
                        and phone[1:].isdigit()
                        and 7 <= len(phone[1:]) <= 15
                    ):
                        contact_counts["nonCanonicalPhones"] += 1
                    if digits and cid:
                        phones[digits].add(cid)
                email = str(row.get("email") or "").strip().lower()
                if email and cid:
                    emails[email].add(cid)
                customer_uuid = str(row.get("customerUuid") or "").strip()
                if customer_uuid and cid:
                    uuids[customer_uuid].add(cid)

        contact_counts["brokenMergeAliases"] = sum(
            1 for target in merged_targets if not target or target not in active_ids
        )
        contact_counts["duplicatePhoneGroups"] = sum(
            1 for ids in phones.values() if len(ids) > 1
        )
        contact_counts["duplicateEmailGroups"] = sum(
            1 for ids in emails.values() if len(ids) > 1
        )
        contact_counts["duplicateCustomerUuidGroups"] = sum(
            1 for ids in uuids.values() if len(ids) > 1
        )

        report = {
            "contacts": contact_counts,
            "orders": dependent_counts(
                ddb.Table(TABLES["orders"]), active_ids, orders=True
            ),
            "messages": dependent_counts(
                ddb.Table(TABLES["messages"]), active_ids
            ),
            "flows": dependent_counts(
                ddb.Table(TABLES["flows"]), active_ids
            ),
            "invoices": dependent_counts(
                ddb.Table(TABLES["invoices"]), active_ids
            ),
            "attempts": dependent_counts(
                ddb.Table(TABLES["attempts"]), active_ids
            ),
        }

        table = boto3.client("dynamodb", region_name=args.region).describe_table(
            TableName=TABLES["orders"]
        )["Table"]
        v2 = next(
            (
                g
                for g in table.get("GlobalSecondaryIndexes") or []
                if g.get("IndexName") == "customerId-createdAt-v2-index"
            ),
            {},
        )
        report["orderCustomerV2Index"] = {
            "status": v2.get("IndexStatus"),
            "backfilling": bool(v2.get("Backfilling", False)),
        }

        failures = (
            report["contacts"]["duplicatePhoneGroups"]
            + report["contacts"]["duplicateEmailGroups"]
            + report["contacts"]["duplicateCustomerUuidGroups"]
            + report["contacts"]["idContactIdMismatches"]
            + report["contacts"]["brokenMergeAliases"]
            + report["contacts"]["nonCanonicalPhones"]
            + report["orders"]["orphanContactId"]
            + report["orders"]["finalizedMissingContactId"]
            + report["orders"]["finalizedMissingCustomerUuid"]
            + report["flows"]["orphanContactId"]
            + report["messages"]["orphanContactId"]
        )
        report["clean"] = (
            failures == 0
            and v2.get("IndexStatus") == "ACTIVE"
            and not v2.get("Backfilling", False)
        )

        print(json.dumps(report, indent=2, default=str))
        return 0 if report["clean"] else 1
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
