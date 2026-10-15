#!/usr/bin/env python3
"""Inventory every inbound webhook this platform expects, and audit Razorpay's live config.

Writes a non-secret report to docs/WEBHOOK-INVENTORY.md and prints a summary.
Credentials are read from Secrets Manager in memory for the read-only Razorpay
query; nothing is printed and nothing is written that contains a value.

    python scripts/webhook_inventory.py            # report, always exits 0
    python scripts/webhook_inventory.py --gate     # exit 1 on a violated expectation

`--gate` is opt-in because this script also performs a live provider query that can
fail for reasons unrelated to the endpoint table, and a reporting run should not go
red on Razorpay being slow. See the comment above ENDPOINTS for what the route check
asserts in each direction.
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

GATE = "--gate" in sys.argv

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import provider_allowlist  # noqa: E402

REGION = "us-east-1"
API_ID = "zllr9lrg7j"
BASE = "https://wecare.digital/api"
ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/payments/razorpay-webhook/handler.py"


# Names the handler mentions that Razorpay does NOT accept as event
# subscriptions. Verified 2026-09-19 by a live PUT, which returned
# BAD_REQUEST_ERROR "Invalid event name/names".
NOT_REAL_EVENTS = {
    # A dict-key lookup at handler.py:1386, not an event type. The real events
    # fund_account.validation.completed / .failed are handled and subscribed.
    "fund_account.validation",
    # A live `elif event_type == 'payment.pending'` branch at handler.py:120, but
    # Razorpay has no such event, so that branch is unreachable. See GAP.
    "payment.pending",
}


def razorpay_events() -> list[str]:
    """Event names the handler dispatches on AND Razorpay actually accepts."""
    src = HANDLER.read_text()
    pat = (r"'((?:payment|order|subscription|invoice|settlement|refund|payment_link"
           r"|virtual_account|fund_account|transfer|account|qr_code)\.[a-z_.]+)'")
    return sorted(set(re.findall(pat, src)) - NOT_REAL_EVENTS)


def razorpay_live_webhooks() -> tuple[list[dict], str]:
    sm = boto3.client("secretsmanager", region_name=REGION)
    d = json.loads(sm.get_secret_value(SecretId="wecare/razorpay/api")["SecretString"])
    token = base64.b64encode(f"{d['key_id']}:{d['key_secret']}".encode()).decode()
    for path in ("/v1/webhooks", f"/v1/accounts/{d.get('account_id','')}/webhooks"):
        req = urllib.request.Request(
            f"https://api.razorpay.com{path}?count=100",
            headers={"Authorization": f"Basic {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode())
            return body.get("items", body.get("entity") and [body] or []), f"OK via {path}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code} on {path}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__} on {path}"
    return [], last


def gateway_routes() -> list[str]:
    """Every route key on the API. get_routes pages, so NextToken is always drained."""
    api = boto3.client("apigatewayv2", region_name=REGION)
    items, token = [], None
    while True:
        kwargs = {"ApiId": API_ID, "MaxResults": "100"}
        if token:
            kwargs["NextToken"] = token
        page = api.get_routes(**kwargs)
        items += page["Items"]
        token = page.get("NextToken")
        if not token:
            return sorted(r["RouteKey"] for r in items)


# Provider -> (endpoint, method, auth model, consuming Lambda). Every row is expected LIVE.
#
# THE ROUTE CHECK IS TWO-SIDED, AND BOTH SIDES ARE POSITIVE.
#
#   1. Every endpoint below must have a live route. These are the URLs configured at each
#      provider; a missing one means a provider is posting into nothing.
#   2. Every live route in the inbound webhook namespace must be an APPROVED webhook route
#      in scripts/provider_allowlist.py. An IaC deploy or a well-meaning re-provision is
#      exactly how a retired provider's callback returns, and this side catches it by the
#      route not being approved, whatever provider it belonged to.
#
# This table once carried rows for retired endpoints with an "expect absence" marker, so
# that a returning route would fail. Side 2 does that for every retired route at once,
# without the inventory having to name any of them.
ENDPOINTS = [
    ("Razorpay", "/razorpay-webhook", "POST",
     "HMAC SHA256 X-Razorpay-Signature vs webhook_secret", "wecare-razorpay-webhook"),
    ("Meta / WhatsApp Cloud", "/whatsapp/inbound", "POST",
     "X-Hub-Signature-256 vs app_secret + verify_token on GET", "wecare-inbound-whatsapp"),
    ("Meta / WhatsApp (business)", "/wa-business/webhooks", "POST",
     "X-Hub-Signature-256", "wecare-whatsapp-business-api"),
    ("Plivo (voice IVR)", "/plivo/answer", "POST",
     "optional ?token= shared secret (PLIVO_ANSWER_TOKEN); Plivo does not sign answer_url",
     "wecare-plivo-answer"),
    ("Sinch (RCS)", "/webhook/sinch-rcs", "POST", "provider callback", "wecare-rcs-dlr"),
]


def route_failures(routes: set) -> list[str]:
    """Both sides of the route check, as failure messages. Pure, for tests."""
    failures = []
    for _prov, path, method, _auth, fn in ENDPOINTS:
        if f"{method} {path}" not in routes:
            failures.append(f"{method} {path} should be live but no route exists "
                            f"(target {fn})")
    for route in sorted(routes):
        path = route.split(None, 1)[-1]
        if provider_allowlist.is_webhook_route(path) and \
                not provider_allowlist.webhook_route_ok(path):
            failures.append(f"{route} is a webhook route that is not on the provider "
                            f"allow-list (scripts/provider_allowlist.py)")
    return failures


def main() -> int:
    events = razorpay_events()
    routes = set(gateway_routes())
    live, status = razorpay_live_webhooks()

    print(f"Razorpay events handled in code : {len(events)}")
    print(f"Razorpay live webhook query     : {status}")
    print(f"Razorpay webhooks configured    : {len(live)}")

    configured_urls = {w.get("url", "") for w in live}
    configured_events: set[str] = set()
    for w in live:
        ev = w.get("events")
        if isinstance(ev, dict):
            configured_events |= {k for k, v in ev.items() if v}
        elif isinstance(ev, list):
            configured_events |= set(ev)

    missing = [e for e in events if e not in configured_events]
    extra = sorted(configured_events - set(events))

    lines: list[str] = []
    add = lines.append
    add("# Webhook inventory\n")
    add("Generated by `scripts/webhook_inventory.py`. No credential values here.\n")
    add(f"- API Gateway: `{API_ID}` · base `{BASE}`")
    add(f"- Razorpay live query: {status}\n")

    add("## Endpoints to configure at each provider\n")
    add("`scripts/webhook_inventory.py --gate` fails when one of these has no live route,")
    add("**and** when a live route in the webhook namespace is not an approved webhook")
    add("route in `scripts/provider_allowlist.py`.\n")
    add("| Provider | URL | Method | Route state | Auth | Lambda |")
    add("|---|---|---|---|---|---|")
    for prov, path, method, auth, fn in ENDPOINTS:
        state = "YES" if f"{method} {path}" in routes else "**MISSING**"
        add(f"| {prov} | `{BASE}{path}` | {method} | {state} | {auth} | `{fn}` |")

    unapproved = [r for r in sorted(routes)
                  if provider_allowlist.is_webhook_route(r.split(None, 1)[-1])
                  and not provider_allowlist.webhook_route_ok(r.split(None, 1)[-1])]
    if unapproved:
        add(f"\n### Webhook routes not on the allow-list ({len(unapproved)})\n")
        for route in unapproved:
            add(f"- `{route}`")
        add("")

    add("\n## Razorpay — current state\n")
    if live:
        add("| # | URL | Status | Events |")
        add("|---|---|---|---|")
        for i, w in enumerate(live, 1):
            ev = w.get("events")
            n = len([k for k, v in ev.items() if v]) if isinstance(ev, dict) else len(ev or [])
            add(f"| {i} | `{w.get('url','')}` | {w.get('status','')} | {n} |")
    else:
        add("No webhooks returned by the API. Either none are configured, or the\n"
            "webhook endpoints are not exposed to this key type (Razorpay restricts\n"
            "`/v1/webhooks` on some account types) - in that case configure in the\n"
            "dashboard: **Settings → Webhooks → Add New Webhook**.\n")

    add(f"\n### Events the handler processes ({len(events)})\n")
    add("Subscribe exactly these. Anything else is ignored by the handler.\n")
    add("```")
    for e in events:
        add(e)
    add("```")

    if configured_events:
        add(f"\n### Not yet subscribed ({len(missing)})\n")
        add("```")
        for e in missing:
            add(e)
        add("```")
        if extra:
            add(f"\n### Subscribed but NOT handled ({len(extra)}) — harmless, just noise\n")
            add("```")
            for e in extra:
                add(e)
            add("```")

    add("\n## Razorpay setup, manual\n")
    add(f"1. Dashboard → **Settings → Webhooks → Add New Webhook**")
    add(f"2. Webhook URL: `{BASE}/razorpay-webhook`")
    add("3. Secret: must match the `webhook_secret` field in Secrets Manager secret\n"
        "   `wecare/razorpay-webhook`. If you change one, change both, or signature\n"
        "   verification fails and every payment webhook is rejected.")
    add("4. Select the events listed above.")
    add("5. Save, then use **Send Test Webhook** and confirm a 200.\n")

    add("## Razorpay setup, via API\n")
    add("`POST https://api.razorpay.com/v1/webhooks` with Basic auth "
        "(`key_id:key_secret`). Never put those on a command line - read them from\n"
        "Secrets Manager in a script. Body shape:\n")
    add("```json")
    add(json.dumps({
        "url": f"{BASE}/razorpay-webhook",
        "alert_email": "admin@wecare.digital",
        "secret": "<value of wecare/razorpay-webhook:webhook_secret>",
        "events": {e: 1 for e in events},
    }, indent=2))
    add("```")

    out = ROOT / "docs" / "WEBHOOK-INVENTORY.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {out} ({out.stat().st_size} bytes)")

    print("\nendpoint route check:")
    for _prov, path, method, _a, fn in ENDPOINTS:
        mark = "ok      " if f"{method} {path}" in routes else "MISSING "
        print(f"  {mark} {method:5s} {path:28s} -> {fn}")

    failures = route_failures(routes)
    print(f"\n{len(ENDPOINTS)} endpoint(s) expected live; "
          f"{len(routes)} live route(s) checked against the webhook allow-list")
    if failures:
        print(f"\nFAIL — {len(failures)} endpoint expectation(s) violated:")
        for f in failures:
            print(f"  {f}")
        return 1 if GATE else 0
    print("WEBHOOK ENDPOINT EXPECTATIONS OK — every listed route exists and every live "
          "webhook route is approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
