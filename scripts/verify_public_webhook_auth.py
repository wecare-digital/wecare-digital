#!/usr/bin/env python3
"""Live check: the two public webhook ingresses reject unauthenticated callers.

This is the deployed counterpart to tests/test_public_webhook_auth.py. Unit tests
prove the handler logic; this proves the deployed alias actually enforces it,
which a green test suite cannot.

Every probe is deliberately inert
---------------------------------
  POST /whatsapp/inbound      unsigned, body {}    expect 401
  POST /webhook/sinch-rcs     unsigned, INBOUND    expect 503
  GET  /webhook/sinch-rcs     unsigned             expect 200 (health)

The inbound-shaped Sinch body is the exploit payload: before 2026-09-21 it wrote
a forged message into the canonical MessagesTable and could trigger an outbound
RCS send. It is safe to send now precisely because the fix refuses it before any
parsing or side effect - if this script ever reports 200 for that probe, the
protection has regressed.

Deliberately NOT probed: an unsigned MESSAGE_DELIVERY body. While no webhook
secret is configured at Sinch that type is still processed by design, and
`_process_delivery` issues a DynamoDB update_item, which upserts - so a probe
with a synthetic message id would write a junk row into MessagesTable. Unit
tests cover that path instead.

No credential is sent, because these endpoints require none. That is the point.

    python scripts/verify_public_webhook_auth.py
    python scripts/verify_public_webhook_auth.py --gate   # exit 1 on any mismatch
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = "https://wecare.digital/api"
TIMEOUT = 20

# (label, method, path, body, expected status, why)
PROBES = [
    # --- signed provider ingresses ---
    ("whatsapp inbound, unsigned", "POST", "/whatsapp/inbound", {}, 401,
     "no X-Hub-Signature-256; must not reach the SNS-envelope parser"),
    ("whatsapp inbound, unsigned create_invoice", "POST", "/whatsapp/inbound",
     {"action": "create_invoice", "contactId": "probe"}, 401,
     "the internal-only branch must not be reachable over HTTP"),
    ("sinch rcs, unsigned MESSAGE_INBOUND", "POST", "/webhook/sinch-rcs",
     {"message": {"contact_message": {"text_message": {"text": "probe"}},
                  "channel_identity": {"channel": "RCS", "identity": "+910000000000"}}},
     503, "forged inbound must be refused before MessagesTable or rcs-send"),
    ("sinch rcs health", "GET", "/webhook/sinch-rcs", None, 200,
     "the health path stays reachable"),

    # --- routes moved behind require_auth on 2026-09-21 ---
    # All reads, so each is inert whether or not the guard holds.
    ("short-link management, no token", "GET", "/links", None, 401,
     "link enumeration was anonymous; a listing leaks every destination"),
    ("bulk worker status, no token", "GET", "/bulk/worker", None, 401,
     "leaked SEND_MODE anonymously"),
    ("product image preview, no token", "GET", "/store/preview-product-image",
     None, 401, "image generation costs money per call"),
    ("ai generate, no token", "POST", "/ai/generate", {"messageContent": "probe"},
     401, "spent model tokens anonymously on both HTTP APIs"),

    # --- AUTH_SKIP_PATHS narrowed on 2026-09-21 (SEC-ROUTE-009) ---
    # `/wa-business/webhooks` was exempt from auth on the stated grounds that it
    # "authenticates via verify token". It is not a Meta callback: it is the
    # management surface for Meta's subscribed_apps API. Measured before the fix,
    # GET returned 400 "wabaId required" - past auth, inside the handler.
    #
    # The POST and DELETE probes carry NO wabaId, so the handler's own 400 check
    # would stop them before any Graph call even if the guard were broken. Without
    # that, DELETE would unsubscribe the production WABA from every webhook field
    # and stop all inbound WhatsApp delivery.
    ("wa-business webhooks read, no token", "GET", "/wa-business/webhooks", None,
     401, "listed the WABA's webhook subscriptions anonymously"),
    ("wa-business webhooks subscribe, no token", "POST", "/wa-business/webhooks",
     {}, 401, "POST forwards override_callback_uri to Meta: inbound redirection"),
    ("wa-business webhooks unsubscribe, no token", "DELETE",
     "/wa-business/webhooks", {}, 401,
     "DELETE stops all inbound WhatsApp delivery for the WABA"),
    ("wa-business substring near-miss, no token", "GET",
     "/wa-business/webhooks-anything", None, 401,
     "the old skip was a substring test, and ANY /wa-business/{proxy+} exists"),

    # --- and the anonymous paths that must KEEP working ---
    # The Flows data-exchange endpoint is the ONE legitimate exemption on that
    # function: it carries no staff token. Since 2026-10-25 it requires Meta's
    # X-Hub-Signature-256 (an RSA-encrypted body proves nothing, because our key
    # is public), so this unsigned probe is refused with 432, Meta's specified
    # status for a failed signature, before anything is decrypted. A 401 here
    # would mean the exemption was lost along with the webhooks one.
    ("flows data-exchange stays public", "POST", "/wa-business/flow-data",
     {"encrypted_flow_data": "bm90LXJlYWw=", "encrypted_aes_key": "bm90LXJlYWw=",
      "initial_vector": "bm90LXJlYWw="}, 432,
     "authenticates by Meta's X-Hub-Signature-256 (432 unsigned) and RSA decryption, not by token"),
    ("short-link redirect stays public", "GET", "/r/verify-probe-no-such-code",
     None, 302, "a customer following a short link has no Cognito token"),
    # The bare /{code} catch-all was retired on 2026-10-02 (3b8f6b06c, link-resources.ts):
    # short links live only at /r/{code}, so an unknown API path must stay API Gateway's
    # JSON 404 and must never be redirected. A 302 here would mean the catch-all came back.
    ("unknown API path stays a JSON 404", "GET", "/verify-probe-no-such-code",
     None, 404, "short links are /r/{code} only; no bare /{code} catch-all"),
]

# Deliberately not probed live: POST /media/cleanup. It is the only guarded route
# with no read method, and if the guard were broken the probe itself would delete
# media from Meta. Its guard is identical to the others verified here and is
# covered by tests/test_route_auth_enforcement.py.


# Build one opener with proxies explicitly disabled. urllib otherwise consults
# the system proxy configuration, and on this machine an unset-but-present macOS
# proxy lookup made the first request hang past a 180s budget while the identical
# curl call returned in under a second.
#
# Redirects are NOT followed. urllib follows them by default, which turned the
# short-link probes into a 200 from the site's fallback page and hid the 302 that
# is the actual thing under test.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect())


def probe(method: str, path: str, body) -> tuple[int, str]:
    data = None
    headers = {"user-agent": "wecare-auth-verifier/1.0",
               "connection": "close"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method=method)
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(400).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(400).decode(errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"transport error: {type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 if any probe does not match its expectation")
    args = ap.parse_args()

    print(f"target {BASE}\n")
    failures = 0
    for label, method, path, body, expected, why in PROBES:
        status, snippet = probe(method, path, body)
        ok = status == expected
        if not ok:
            failures += 1
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {label}")
        print(f"       {method} {path} -> {status} (expected {expected})")
        print(f"       {why}")
        if not ok:
            print(f"       body: {snippet.strip()[:200]}")
        print()

    print(f"{len(PROBES) - failures}/{len(PROBES)} probes as expected")
    if failures:
        print("\nA mismatch here means the deployed alias is not enforcing what "
              "the unit tests assert. Check that `live` points at the version "
              "carrying the fix.")
    return 1 if (failures and args.gate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
