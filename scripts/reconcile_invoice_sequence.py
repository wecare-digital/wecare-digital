#!/usr/bin/env python3
"""Report, and only on request advance, the GST invoice counter for one financial year.

Why this exists
---------------
`invoice-engine._get_next_invoice_number` now confirms every number it hands out with an
immutable `INVOICENO#` reservation row, so a counter that sits BELOW the issued series
self-heals: the next call walks past the reserved candidates and continues from the true floor.
That walk is bounded (`_INVOICE_NUMBER_ATTEMPTS`), and it costs one wasted counter advance per
already-issued number, so a counter that was reset far below the series should be realigned once
by an operator rather than crawled past on every invoice.

This script answers "where is the series really?" from three independent sources and, with
`--apply`, moves the counter forward to match.

    InvoicesTable.invoiceNumber     what we actually issued and still hold a row for
    INVOICENO# on the keys table    what we recorded as issued, surviving an invoice-table wipe
    --floor WD/2627/00004           what an operator knows went out, for numbers whose rows and
                                    reservations were BOTH destroyed (a full system reset clears
                                    the keys table too) - the only source for erased history

What it will and will not do
----------------------------
Default is REPORT ONLY: it prints the three figures, the proposed floor and the action it would
take, writes nothing, and exits 0. `--apply` issues one conditional `SET last_seq = :floor`
guarded on `last_seq < :floor`, so it can only ever move the counter FORWARD and two concurrent
runs cannot move it backwards. It never deletes a row, never issues an invoice number, never
writes a reservation row and never touches an invoice.

    python scripts/reconcile_invoice_sequence.py --fy 2026-2027
    python scripts/reconcile_invoice_sequence.py --fy 2026-2027 --floor WD/2627/00004
    python scripts/reconcile_invoice_sequence.py --fy 2026-2027 --floor WD/2627/00004 --apply

Exit codes: 0 the counter is at or above the floor (or the advance was applied), 1 the counter is
behind the floor and nothing was written.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "amplify", "functions", "shared"))

try:
    import boto3  # noqa: F401 - imported for parity with the other reconcile scripts
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

from lambda_utils.ecommerce import order_keys  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")
INVOICES_TABLE = os.environ.get("INVOICES_TABLE", "stack-wecare-digital-InvoicesTable")
INVOICE_SEQ_TABLE = os.environ.get("INVOICE_SEQ_TABLE",
                                   "stack-wecare-digital-InvoiceSequenceTable")

#: `WD/2627/00004` - the shape `invoice-engine._format_invoice_number` writes.
_NUMBER_RE = re.compile(r"^(?P<prefix>[A-Z]+)/(?P<fy>\d{4})/(?P<seq>\d+)$")


def _resource():
    import boto3 as _boto3
    return _boto3.resource("dynamodb", region_name=REGION)


def fy_short(fy: str) -> str:
    """`2026-2027` -> `2627`, the form that appears inside the number."""
    return fy.replace("20", "").replace("-", "")


def parse_sequence(number: str, *, fy: str) -> int:
    """The sequence inside an invoice number for `fy`, or 0 when it is for another year.

    0 rather than an exception: this reads production rows, and one unparseable legacy number
    must not stop the report that tells an operator where the series is. A number that cannot be
    read contributes nothing to the floor, which errs toward NOT moving the counter.
    """
    match = _NUMBER_RE.match(str(number or "").strip())
    if not match or match.group("fy") != fy_short(fy):
        return 0
    return int(match.group("seq"))


def highest_issued_invoice(table, *, fy: str) -> int:
    """The highest `invoiceNumber` on InvoicesTable for `fy`. Paginated.

    A Scan is correct rather than lazy: the question spans every invoice ever raised, there is no
    index on the number, and this runs by hand. Pagination is not optional - a single Scan page
    is 1MB, and reading one page would under-report the floor, which is the one direction that
    matters here.
    """
    highest, kwargs = 0, {"ProjectionExpression": "invoiceNumber"}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            highest = max(highest, parse_sequence(item.get("invoiceNumber"), fy=fy))
        if "LastEvaluatedKey" not in page:
            return highest
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def highest_reserved_number(table, *, fy: str) -> int:
    """The highest `INVOICENO#` reservation on the commerce-keys table for `fy`.

    These rows outlive `clear_all_invoice_data`, so this source can be ahead of InvoicesTable -
    which is exactly the case the reservation rows were added for.
    """
    highest, kwargs = 0, {}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            key = str(item.get("orderId", ""))
            if not key.startswith(order_keys.INVOICE_NUMBER_PREFIX):
                continue
            highest = max(highest, parse_sequence(
                item.get("invoiceNumber") or key[len(order_keys.INVOICE_NUMBER_PREFIX):], fy=fy))
        if "LastEvaluatedKey" not in page:
            return highest
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def counter_last_seq(table, *, fy: str) -> int:
    """The counter's `last_seq` for `fy`, or 0 when the row is absent (or was wiped)."""
    row = table.get_item(Key={"fy": fy}, ConsistentRead=True).get("Item") or {}
    return int(row.get("last_seq", 0) or 0)


def advance_counter(table, *, fy: str, floor: int) -> bool:
    """Move `last_seq` up to `floor`. True when it moved, False when it was already at or above.

    Conditional on `last_seq < :floor`, so this can only ever move the counter forward. Two
    concurrent runs therefore cannot move it backwards, and a re-run is a no-op rather than a
    second advance. `prefix` is left alone - this script does not decide what a number looks like.
    """
    try:
        table.update_item(
            Key={"fy": fy},
            UpdateExpression="SET last_seq = :floor, updated_at = :now",
            ConditionExpression="attribute_not_exists(last_seq) OR last_seq < :floor",
            ExpressionAttributeValues={":floor": int(floor), ":now": int(time.time())},
        )
        return True
    except Exception as error:  # noqa: BLE001
        if order_keys.is_conditional_failure(error):
            return False
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fy", required=True, metavar="YYYY-YYYY",
                    help="financial year, e.g. 2026-2027")
    ap.add_argument("--floor", metavar="INVOICE_NUMBER", default="",
                    help="a number an operator knows went out, e.g. WD/2627/00004")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only (the default; accepted so a run can say so explicitly)")
    ap.add_argument("--apply", action="store_true",
                    help="advance the counter to the proposed floor (forward only)")
    args = ap.parse_args(argv)

    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run contradict each other")

    resource = _resource()
    invoices = resource.Table(INVOICES_TABLE)
    keys = resource.Table(order_keys.commerce_keys_table_name())
    sequence = resource.Table(INVOICE_SEQ_TABLE)

    from_invoices = highest_issued_invoice(invoices, fy=args.fy)
    from_reservations = highest_reserved_number(keys, fy=args.fy)
    from_operator = parse_sequence(args.floor, fy=args.fy) if args.floor else 0
    if args.floor and not from_operator:
        ap.error(f"--floor {args.floor!r} is not an invoice number for FY {args.fy}")

    floor = max(from_invoices, from_reservations, from_operator)
    last_seq = counter_last_seq(sequence, fy=args.fy)

    print(f"FY {args.fy}")
    print(f"  highest on InvoicesTable      {from_invoices:5d}")
    print(f"  highest INVOICENO# reservation {from_reservations:5d}")
    print(f"  operator --floor               {from_operator:5d}")
    print(f"  proposed floor                 {floor:5d}")
    print(f"  counter last_seq               {last_seq:5d}")

    if floor <= last_seq:
        print("\ncounter is at or above the floor; nothing to do")
        return 0

    print(f"\ncounter is BEHIND the floor by {floor - last_seq}; "
          f"next issued number would collide and be walked past")

    if not args.apply:
        print("report only; nothing written. Pass --apply to advance last_seq to "
              f"{floor} (forward only)")
        return 1

    if advance_counter(sequence, fy=args.fy, floor=floor):
        print(f"advanced last_seq to {floor}; no invoice, number or reservation was written")
    else:
        print(f"another run already advanced last_seq to at least {floor}; nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
