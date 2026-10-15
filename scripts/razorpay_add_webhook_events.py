#!/usr/bin/env python3
"""Add the missing event subscriptions to the existing Razorpay webhook.

Non-destructive by construction:

  * Targets ONLY the webhook whose url is wecare.digital/api/razorpay-webhook.
    Any other webhook on the account is never touched.
  * Razorpay's update REPLACES the events map, so this sends the UNION of what is
    already enabled plus what is missing. Nothing is unsubscribed.
  * `secret` is deliberately omitted from the payload, so the existing webhook
    secret is left alone. Changing it would break signature verification against
    Secrets Manager `wecare/razorpay-webhook:webhook_secret`.
  * Reads back afterwards and fails loudly if any previously-enabled event
    disappeared.

Credentials come from Secrets Manager in memory. Nothing is printed.

    python scripts/razorpay_add_webhook_events.py --dry-run
    python scripts/razorpay_add_webhook_events.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import boto3

REGION = "us-east-1"
TARGET_URL = "https://wecare.digital/api/razorpay-webhook"
ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"
API = "https://api.razorpay.com/v1/webhooks"


def handled_events() -> set[str]:
    pat = (r"'((?:payment|order|subscription|invoice|settlement|refund|payment_link"
           r"|virtual_account|fund_account|transfer|account|qr_code)\.[a-z_.]+)'")
    return set(re.findall(pat, HANDLER.read_text()))


def auth_header() -> str:
    sm = boto3.client("secretsmanager", region_name=REGION)
    d = json.loads(sm.get_secret_value(SecretId="wecare/razorpay/api")["SecretString"])
    tok = base64.b64encode(f"{d['key_id']}:{d['key_secret']}".encode()).decode()
    return f"Basic {tok}"


def call(method: str, url: str, hdr: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": hdr,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:600]
        raise SystemExit(f"Razorpay HTTP {exc.code} on {method} {url}\n{detail}")


def enabled(w: dict) -> set[str]:
    ev = w.get("events")
    if isinstance(ev, dict):
        return {k for k, v in ev.items() if v}
    return set(ev or [])


def main() -> int:
    dry = "--dry-run" in sys.argv
    hdr = auth_header()

    items = call("GET", f"{API}?count=100", hdr).get("items", [])
    target = next((w for w in items if w.get("url") == TARGET_URL), None)
    if not target:
        raise SystemExit(f"no webhook found with url {TARGET_URL}")

    wid = target["id"]
    before = enabled(target)
    want = handled_events()
    missing = sorted(want - before)

    print(f"webhook id      : {wid}")
    print(f"url             : {target.get('url')}")
    print(f"other webhooks  : {[w.get('url') for w in items if w['id'] != wid]}")
    print(f"events enabled  : {len(before)}")
    print(f"handler handles : {len(want)}")
    print(f"missing         : {missing or 'none'}")

    if not missing:
        print("\nnothing to add")
        return 0

    union = sorted(before | want)
    print(f"\nwill set        : {len(union)} events "
          f"(= {len(before)} existing + {len(missing)} added, 0 removed)")
    if dry:
        print("dry run: nothing sent")
        return 0

    # secret deliberately omitted so the existing one is preserved.
    # Razorpay's update route/verb differs by account type, so try the documented
    # variants and stop at the first that is accepted.
    acct = ""
    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        acct = json.loads(sm.get_secret_value(
            SecretId="wecare/razorpay/api")["SecretString"]).get("account_id", "")
    except Exception:  # noqa: BLE001
        pass

    payload = {"url": TARGET_URL, "events": {e: 1 for e in union}}
    attempts = [
        ("PUT", f"{API}/{wid}"),
        ("PATCH", f"{API}/{wid}"),
        ("PUT", f"https://api.razorpay.com/v1/accounts/{acct}/webhooks/{wid}") if acct else None,
        ("PATCH", f"https://api.razorpay.com/v1/accounts/{acct}/webhooks/{wid}") if acct else None,
    ]
    ok = False
    for attempt in [a for a in attempts if a]:
        method, url = attempt
        try:
            call(method, url, hdr, payload)
            print(f"\naccepted via {method} {url.replace(acct, '<account_id>') if acct else url}")
            ok = True
            break
        except SystemExit as exc:
            print(f"  {method} rejected: {str(exc).splitlines()[0]}")
    if not ok:
        print("\nNo update route accepted. Razorpay restricts webhook editing to the\n"
              "dashboard for this account type. Add these two events manually:")
        for e in missing:
            print(f"    {e}")
        print("  Settings -> Webhooks -> edit the wecare.digital/api hook.")
        print("  Do NOT change the secret while doing so.")
        return 2

    after_items = call("GET", f"{API}?count=100", hdr).get("items", [])
    after_w = next(w for w in after_items if w["id"] == wid)
    after = enabled(after_w)

    lost = sorted(before - after)
    added = sorted(after - before)
    print(f"\nafter           : {len(after)} events")
    print(f"added           : {added}")
    print(f"LOST            : {lost or 'none'}")
    still_missing = sorted(want - after)
    print(f"still missing   : {still_missing or 'none'}")
    print(f"url unchanged   : {after_w.get('url') == TARGET_URL}")
    print(f"other webhooks untouched: "
          f"{[w.get('url') for w in after_items if w['id'] != wid]}")

    if lost or still_missing:
        print("\nPROBLEM - see above")
        return 1
    print("\nOK - all handled events subscribed, none removed, secret untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
