#!/usr/bin/env python3
"""Read-only cross-channel customer identity integrity audit.

Checks the production contract:
Contacts -> Orders -> Messages -> Flow submissions -> Invoices -> Payment attempts.
Prints counts only; never prints phone numbers, emails, customer IDs, or message content.
Exit 0 = clean, 1 = integrity gaps found, 2 = AWS/read error.
"""
from __future__ import annotations
import argparse, json, sys
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

def scan_all(table, **kwargs):
    rows, start = [], None
    while True:
        args = dict(kwargs)
        if start:
            args["ExclusiveStartKey"] = start
        page = table.scan(**args)
        rows.extend(page.get("Items") or [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return rows

def live(row):
    return not row.get("deletedAt") and not row.get("isDeleted") and str(row.get("mergeState") or "").lower() != "merged"

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        ddb = boto3.resource("dynamodb", region_name=args.region)
        contacts = scan_all(ddb.Table(TABLES["contacts"]))
        active = [r for r in contacts if live(r)]
        active_ids = {str(r.get("id") or r.get("contactId") or "") for r in active}
        active_ids.discard("")

        def groups(field, normalizer=lambda v: str(v or "").strip()):
            found = defaultdict(set)
            for row in active:
                value = normalizer(row.get(field))
                cid = str(row.get("id") or row.get("contactId") or "")
                if value and cid:
                    found[value].add(cid)
            return [ids for ids in found.values() if len(ids) > 1]

        dup_phone = groups("phone", lambda v: "".join(ch for ch in str(v or "") if ch.isdigit()))
        dup_email = groups("email", lambda v: str(v or "").strip().lower())
        dup_uuid = groups("customerUuid")

        dependent = {}
        for key in ("orders", "messages", "flows", "invoices", "attempts"):
            rows = scan_all(ddb.Table(TABLES[key]))
            dependent[key] = {
                "total": len(rows),
                "missingContactId": sum(1 for r in rows if not r.get("contactId")),
                "orphanContactId": sum(1 for r in rows if r.get("contactId") and str(r["contactId"]) not in active_ids),
            }
            if key == "orders":
                finalized = [r for r in rows if r.get("finalizationStage") == "ORDER_FINALIZED"]
                dependent[key]["finalizedMissingContactId"] = sum(1 for r in finalized if not r.get("contactId"))
                dependent[key]["finalizedMissingCustomerUuid"] = sum(1 for r in finalized if not r.get("customerUuid"))

        table = boto3.client("dynamodb", region_name=args.region).describe_table(
            TableName=TABLES["orders"])["Table"]
        v2 = next((g for g in table.get("GlobalSecondaryIndexes") or []
                   if g.get("IndexName") == "customerId-createdAt-v2-index"), {})
        report = {
            "contacts": {
                "total": len(contacts), "live": len(active),
                "duplicatePhoneGroups": len(dup_phone),
                "duplicateEmailGroups": len(dup_email),
                "duplicateCustomerUuidGroups": len(dup_uuid),
                "idContactIdMismatches": sum(1 for r in active if r.get("id") and r.get("contactId") and r["id"] != r["contactId"]),
                "nonCanonicalPhones": sum(1 for r in active if r.get("phone") and not (
                    str(r["phone"]).startswith("+") and str(r["phone"])[1:].isdigit())),
                "brokenMergeAliases": sum(1 for r in contacts if str(r.get("mergeState") or "").lower() == "merged"
                    and str(r.get("mergedIntoContactId") or "") not in active_ids),
            },
            **dependent,
            "orderCustomerV2Index": {
                "status": v2.get("IndexStatus"), "backfilling": bool(v2.get("Backfilling", False))
            },
        }
        failures = (
            report["contacts"]["duplicatePhoneGroups"] +
            report["contacts"]["duplicateEmailGroups"] +
            report["contacts"]["duplicateCustomerUuidGroups"] +
            report["contacts"]["idContactIdMismatches"] +
            report["contacts"]["brokenMergeAliases"] +
            report["orders"].get("orphanContactId", 0) +
            report["orders"].get("finalizedMissingContactId", 0) +
            report["orders"].get("finalizedMissingCustomerUuid", 0) +
            report["flows"].get("orphanContactId", 0) +
            report["messages"].get("orphanContactId", 0)
        )
        report["clean"] = failures == 0 and v2.get("IndexStatus") == "ACTIVE" and not v2.get("Backfilling", False)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["clean"] else 1
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
