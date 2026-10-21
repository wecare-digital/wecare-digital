#!/usr/bin/env python3
"""Relink canonical inbox messages that temporarily lack contactId.

Dry-run by default. With --apply, only rows with a usable sender phone and exactly one
canonical live contact are updated. Ambiguous identities are never guessed.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
from lambda_utils import contact_key, contact_store  # noqa: E402

REGION = "us-east-1"
CONTACTS = "stack-wecare-digital-ContactsTable"
MESSAGES = "stack-wecare-digital-MessagesTable"

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--region", default=REGION)
    args = ap.parse_args(argv)
    try:
        ddb = boto3.resource("dynamodb", region_name=args.region)
        contacts = ddb.Table(CONTACTS)
        messages = ddb.Table(MESSAGES)
        rows, start = [], None
        while True:
            kwargs = {
                "FilterExpression": "attribute_not_exists(contactId)",
                "ProjectionExpression": "#id,messageId,senderPhone,channel,direction,messageType",
                "ExpressionAttributeNames": {"#id": "id"},
            }
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = messages.scan(**kwargs)
            rows.extend(page.get("Items") or [])
            start = page.get("LastEvaluatedKey")
            if not start:
                break

        metrics = {"scanned": len(rows), "eligible": 0, "relinked": 0,
                   "noIdentity": 0, "conflict": 0, "updateRaced": 0}
        for row in rows:
            phone = str(row.get("senderPhone") or "").strip()
            if not phone:
                metrics["noIdentity"] += 1
                continue
            try:
                contact = contact_store.find_by_phone(contacts, phone)
            except contact_store.IdentityConflict:
                metrics["conflict"] += 1
                continue
            cid = contact_key.resolve(contact) if contact else ""
            if not cid:
                metrics["noIdentity"] += 1
                continue
            message_id = str(row.get("id") or row.get("messageId") or "")
            if not message_id:
                metrics["noIdentity"] += 1
                continue
            metrics["eligible"] += 1
            if not args.apply:
                continue
            try:
                messages.update_item(
                    Key={"id": message_id},
                    UpdateExpression="SET contactId = :cid",
                    ConditionExpression="attribute_not_exists(contactId)",
                    ExpressionAttributeValues={":cid": cid},
                )
                metrics["relinked"] += 1
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    metrics["updateRaced"] += 1
                    continue
                raise
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **metrics}, indent=2))
        return 0 if metrics["conflict"] == 0 else 1
    except (ClientError, BotoCoreError) as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
