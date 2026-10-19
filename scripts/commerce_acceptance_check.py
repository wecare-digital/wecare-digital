#!/usr/bin/env python3
"""Read-only acceptance checks for a known order, across every surface a customer/staff touches.

Why this exists
---------------
The acceptance review's correct caution: passing unit tests and correct stored records do not
prove every customer SCREEN works. A full live journey (website checkout, WhatsApp payment,
account link, history view, Flow pick) necessarily CREATES a payment and SENDS messages, so it
cannot run unattended. This kit does the half that is safe to automate: for a KNOWN order it
confirms the record is present and correctly shaped on each surface the UI reads from, so a
reviewer's manual click-through is verifying presentation on top of proven data rather than
re-deriving the data each time.

STRICTLY READ-ONLY. It creates no payment, sends no message, writes nothing. It is the
"non-financial checks kept separate from tests that create payments" the review asked for.

    python scripts/commerce_acceptance_check.py --order WD-ORD-TJMG7G4N
    python scripts/commerce_acceptance_check.py --order WD-ORD-TJMG7G4N --json

Exit codes: 0 all checks pass, 1 a check failed, 2 the order was not found / AWS error.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
ORDERS_TABLE = "stack-wecare-digital-OrderTable"
BY_CUSTOMER_INDEX = "customerId-createdAt-v2-index"
BY_PHONE_INDEX = "customerPhone"
BY_SHORT_INDEX = "shortId"


def _orders():
    return boto3.resource("dynamodb", region_name=REGION).Table(ORDERS_TABLE)


def _find_order(table, order_number: str) -> dict | None:
    """Locate the order row by its public order number (shortId GSI, then a bounded scan)."""
    short = order_number.rsplit("-", 1)[-1] if "-" in order_number else order_number
    try:
        hit = table.query(IndexName=BY_SHORT_INDEX,
                          KeyConditionExpression=Key("shortId").eq(short), Limit=1).get("Items")
        if hit:
            return hit[0]
    except (ClientError, BotoCoreError):
        pass
    # Fallback: bounded scan by orderNumber.
    kwargs = {"FilterExpression": boto3.dynamodb.conditions.Attr("orderNumber").eq(order_number),
              "Limit": 500}
    while True:
        page = table.scan(**kwargs)
        for row in page.get("Items") or []:
            return row
        if "LastEvaluatedKey" not in page:
            return None
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def run_checks(order_number: str) -> dict:
    table = _orders()
    order = _find_order(table, order_number)
    if not order:
        return {"found": False, "orderNumber": order_number, "checks": {}}

    order_id = str(order.get("orderId") or "")
    customer_id = str(order.get("customerId") or "")
    phone = str(order.get("customerPhone") or "")
    checks: dict = {}

    # 1. Staff orders surface: the row exists, is paid and finalized.
    checks["staff_order_present"] = {
        "pass": bool(order_id),
        "detail": f"orderId={order_id}"}
    checks["paid_and_finalized"] = {
        "pass": (str(order.get("paymentStatus")) == "PAYMENT_PAID"
                 and str(order.get("finalizationStage")) == "ORDER_FINALIZED"),
        "detail": f"paymentStatus={order.get('paymentStatus')},"
                  f" stage={order.get('finalizationStage')}"}

    # 2. Website history: reachable on the v2 customer index by the OWNING customerId, and that
    #    id is a Cognito sub (a linked account), not a bare contactId - a NEEDS_CUSTOMER_LINK row
    #    would still carry the contactId here and be invisible to the authenticated query.
    website_visible = False
    is_sub = "-" in customer_id and not customer_id.startswith("wa")
    try:
        rows = table.query(IndexName=BY_CUSTOMER_INDEX,
                           KeyConditionExpression=Key("customerId").eq(customer_id)).get("Items") or []
        website_visible = any(str(r.get("orderId")) == order_id for r in rows)
    except (ClientError, BotoCoreError) as exc:
        checks["website_history_query_error"] = {"pass": False, "detail": type(exc).__name__}
    checks["website_history_visible"] = {
        "pass": website_visible and is_sub,
        "detail": f"onV2Index={website_visible}, ownerIsCognitoSub={is_sub} ({customer_id})"}
    checks["website_row_carries_channel_and_uuid"] = {
        "pass": bool(order.get("channel")) and bool(order.get("customerUuid")),
        "detail": f"channel={order.get('channel')}, customerUuid={order.get('customerUuid')}"}

    # 3. WhatsApp Flow picker: reachable on the phone-keyed index the picker reads.
    picker_visible = False
    try:
        rows = table.query(IndexName=BY_PHONE_INDEX,
                           KeyConditionExpression=Key("customerPhone").eq(phone)).get("Items") or []
        picker_visible = any(str(r.get("orderId")) == order_id for r in rows)
    except (ClientError, BotoCoreError) as exc:
        checks["flow_picker_query_error"] = {"pass": False, "detail": type(exc).__name__}
    checks["flow_picker_visible"] = {
        "pass": picker_visible,
        "detail": f"onPhoneIndex={picker_visible} (phone={phone[:4]}***)"}

    return {"found": True, "orderNumber": order_number, "orderId": order_id, "checks": checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--order", required=True, help="public order number, e.g. WD-ORD-TJMG7G4N")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        result = run_checks(args.order)
    except (ClientError, BotoCoreError) as exc:
        print(f"AWS call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not result["found"]:
        print(f"NOT FOUND: {args.order}", file=sys.stderr)
        return 2

    checks = result["checks"]
    all_pass = all(c["pass"] for c in checks.values())

    if args.json:
        print(json.dumps({"allPass": all_pass, **result}, indent=2, default=str))
        return 0 if all_pass else 1

    print("=" * 70)
    print(f"ACCEPTANCE CHECK — {result['orderNumber']}  ({result['orderId']})")
    print("=" * 70)
    for name, c in checks.items():
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {name}: {c['detail']}")
    print("=" * 70)
    print("RESULT:", "ALL PASS — the record is present and correctly shaped on every surface"
          if all_pass else "ATTENTION — a surface check failed")
    print("\nNOTE: this proves the DATA. A reviewer still clicks through the website history and"
          "\nthe real WhatsApp Flow to confirm PRESENTATION — those steps create/send and are manual.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
