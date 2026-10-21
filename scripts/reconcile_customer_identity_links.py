#!/usr/bin/env python3
"""Reconcile missing canonical contactId links on MessagesTable and FlowSubmissionTable.

Dry-run is the default. This never guesses identity: it only relinks a row when its stored phone
resolves to exactly one live ContactsTable record across canonical/bare phone spellings. Ambiguous,
missing, deleted, or merged identities are skipped and counted.

--apply performs conditional updates only when contactId is still absent/empty, so concurrent
writers win safely. No phone, email, customer id, message content, or form content is printed.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
CONTACTS = "stack-wecare-digital-ContactsTable"
MESSAGES = "stack-wecare-digital-MessagesTable"
FLOWS = "stack-wecare-digital-FlowSubmissionTable"


def digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def variants(value):
    d = digits(value)
    out = []
    for v in (("+" + d) if d else "", d, str(value or "").strip()):
        if v and v not in out:
            out.append(v)
    return out


def live(row):
    return bool(row) and not row.get("deletedAt") and not row.get("isDeleted") and \
        str(row.get("mergeState") or "").strip().lower() != "merged"


def resolve_contact(contacts, phone):
    ids = {}
    for value in variants(phone):
        page = contacts.query(
            IndexName="phone-index",
            KeyConditionExpression=Key("phone").eq(value),
            Limit=25,
        )
        for row in page.get("Items") or []:
            if not live(row):
                continue
            cid = str(row.get("id") or row.get("contactId") or "").strip()
            if cid:
                ids[cid] = row
    if len(ids) != 1:
        return "", "ambiguous" if len(ids) > 1 else "missing"
    return next(iter(ids)), "resolved"


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


def repair_table(table, contacts, *, phone_field, apply):
    counts = {"candidates": 0, "resolved": 0, "updated": 0, "missing": 0, "ambiguous": 0,
              "raced": 0}
    for rows in pages(
        table,
        FilterExpression="attribute_not_exists(contactId) OR contactId = :empty",
        ExpressionAttributeValues={":empty": ""},
        ProjectionExpression="#pk," + phone_field + ",contactId",
        ExpressionAttributeNames={"#pk": table.key_schema[0]["AttributeName"]},
    ):
        for row in rows:
            counts["candidates"] += 1
            phone = row.get(phone_field)
            cid, outcome = resolve_contact(contacts, phone)
            if not cid:
                counts[outcome] += 1
                continue
            counts["resolved"] += 1
            if not apply:
                continue
            pk = table.key_schema[0]["AttributeName"]
            try:
                table.update_item(
                    Key={pk: row[pk]},
                    UpdateExpression="SET contactId=:cid",
                    ConditionExpression="attribute_not_exists(contactId) OR contactId=:empty",
                    ExpressionAttributeValues={":cid": cid, ":empty": ""},
                )
                counts["updated"] += 1
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    counts["raced"] += 1
                else:
                    raise
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--region", default=REGION)
    args = ap.parse_args(argv)
    try:
        ddb = boto3.resource("dynamodb", region_name=args.region)
        contacts = ddb.Table(CONTACTS)
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "messages": repair_table(
                ddb.Table(MESSAGES), contacts, phone_field="senderPhone", apply=args.apply
            ),
            "flows": repair_table(
                ddb.Table(FLOWS), contacts, phone_field="phone", apply=args.apply
            ),
        }
        report["clean"] = all(
            section["missing"] == 0 and section["ambiguous"] == 0
            for name, section in report.items() if isinstance(section, dict)
        )
        print(json.dumps(report, indent=2))
        return 0 if report["clean"] else 1
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
