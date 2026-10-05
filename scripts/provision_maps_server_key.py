#!/usr/bin/env python3
"""Mint a server-restricted Google Maps key and store it, without the value being seen.

Why this script exists at all
----------------------------
`gcloud services api-keys create` returns the key string in its response. Running it
interactively puts a live credential into the terminal, the shell history, and - when an
agent runs it - the agent's context and the session transcript. That is precisely how four
live credentials ended up in cleartext in a Kiro permissions file on 2026-09-19.

So the value is never allowed to surface. It is captured from gcloud's stdout in memory,
written straight to Secrets Manager, and the only things printed are metadata: the key's
resource name, its API restrictions, a sha256 prefix, and whether Google accepted it.

Why a SECOND key rather than fixing the existing one
----------------------------------------------------
Measured 2026-09-26. The existing `WECARE Unified Google API Key` is a **browser** key:
`browserKeyRestrictions.allowedReferrers`. Google refuses referrer-restricted keys for
server-side calls, on both surfaces this project needs:

    legacy Geocoding        REQUEST_DENIED
                            "API keys with referer restrictions cannot be used with this API"
    Places API (New)        403 API_KEY_HTTP_REFERRER_BLOCKED

Adding `places.googleapis.com` to that key's `apiTargets` was necessary and **not
sufficient** - it was added, and the call still fails, because the refusal is about the key
*type*, not its API list. No edit to a browser key can make it work server-side. The only
fix is a separate key, which is what `docs/spec.md` ADR-4 already required.

The new key carries **no** application restriction. That is deliberate and it is the
standard pattern for Lambda, which has no stable egress IP to allowlist, so `--allowed-ips`
is not available. The compensating control is a tight `apiTargets` list: six services
instead of the unified key's forty-nine. A key with no application restriction is usable by
anyone who holds it, which is exactly why it must be separate, narrow, and in Secrets
Manager rather than shared with the browser.

Usage
-----
    python scripts/provision_maps_server_key.py --create     # mint, store, verify
    python scripts/provision_maps_server_key.py --status      # report without changing
    python scripts/provision_maps_server_key.py --verify      # re-run the live probe

Exit status is 1 if the key does not answer on Places API (New).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
SECRET_NAME = "wecare/google-maps-server"
SECRET_FIELD = "api_key"
DISPLAY_NAME = "WECARE Address Capture Server Key"

# Least privilege for the two server consumers: address capture + VayuLok environment.
# Deliberately NOT the unified key's broad service list.
#   places.googleapis.com          Places API (New) - autocomplete and place details
#   addressvalidation.googleapis.com  address verification
#   geocoding-backend.googleapis.com  geocoding, only where genuinely required
#   places-backend.googleapis.com     legacy Places, retained only until the existing
#                                     WhatsApp location-template proxy migrates off it
API_TARGETS = [
    "places.googleapis.com",
    "addressvalidation.googleapis.com",
    "geocoding-backend.googleapis.com",
    "places-backend.googleapis.com",
    # VayuLok environmental web-service calls. Kept server-side by
    # core/vayulok-environment; never add these to the public browser key.
    "airquality.googleapis.com",
    "weather.googleapis.com",
]

TIMEOUT = 20


def fp(value: str) -> str:
    """A stable, non-reversible identifier for a secret, safe to print."""
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:12]


def gcloud_path() -> str:
    """Resolve gcloud without relying on an interactive shell's PATH.

    Scripts do not inherit ~/.zshrc, which is interactive-only, so a bare `gcloud` can
    resolve locally and then fail under automation.
    """
    found = shutil.which("gcloud")
    if found:
        return found
    candidate = os.path.expanduser("~/google-cloud-sdk/bin/gcloud")
    if os.path.exists(candidate):
        return candidate
    raise SystemExit("gcloud not found on PATH or at ~/google-cloud-sdk/bin/gcloud")


def run_gcloud(args: list[str]) -> dict:
    """Run gcloud and parse JSON. Output is NEVER echoed - it may carry a key string."""
    proc = subprocess.run(
        [gcloud_path(), *args, "--format=json"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        # stderr from gcloud can legitimately be long; it does not carry the key string,
        # but it is still truncated so an unexpected echo cannot dump a large payload.
        raise SystemExit(f"gcloud failed: {proc.stderr.strip()[:400]}")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise SystemExit("gcloud returned output that is not JSON")


def secrets_client():
    return boto3.client("secretsmanager", region_name=REGION)


def store(value: str) -> str:
    """Put the value in Secrets Manager, creating the container if needed.

    Never logs the value and never places it on a command line - boto3 carries it in the
    request body over TLS.
    """
    client = secrets_client()
    payload = json.dumps({SECRET_FIELD: value})
    try:
        client.create_secret(
            Name=SECRET_NAME,
            Description="Server-restricted Google Maps key for address capture. "
                        "No application restriction by design; Lambda has no stable "
                        "egress IP. Scoped by apiTargets instead.",
            SecretString=payload,
        )
        return "created"
    except client.exceptions.ResourceExistsException:
        client.put_secret_value(SecretId=SECRET_NAME, SecretString=payload)
        return "new version"


def load_stored() -> str | None:
    """Read the stored value for verification only. Returned, never printed."""
    try:
        raw = secrets_client().get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    except ClientError:
        return None
    try:
        return json.loads(raw).get(SECRET_FIELD)
    except json.JSONDecodeError:
        return raw.strip() or None


def probe_places_new(key: str) -> tuple[bool, str]:
    """Ask Places API (New) whether it accepts this key. Returns (ok, detail)."""
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:autocomplete",
        method="POST",
        data=json.dumps({"input": "New Delhi", "regionCode": "IN"}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "suggestions.placePrediction.placeId",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read() or b"{}")
        return True, f"{len(body.get('suggestions', []))} suggestion(s)"
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read() or b"{}").get("error", {})
        except json.JSONDecodeError:
            error = {}
        reason = ""
        for detail in error.get("details") or []:
            if detail.get("reason"):
                reason = str(detail["reason"])
                break
        return False, f"HTTP {exc.code} {reason or str(error.get('message', ''))[:120]}"
    except Exception as exc:  # noqa: BLE001
        # Type only. An exception's text here could in principle echo the request.
        return False, type(exc).__name__


def report_status() -> int:
    keys = run_gcloud(["services", "api-keys", "list"])
    mine = [k for k in keys if k.get("displayName") == DISPLAY_NAME]
    print(f"gcloud keys named {DISPLAY_NAME!r}: {len(mine)}")
    for key in mine:
        restrictions = key.get("restrictions") or {}
        targets = [t["service"] for t in restrictions.get("apiTargets") or []]
        app_restriction = next(
            (name for name in (
                "browserKeyRestrictions", "serverKeyRestrictions",
                "androidKeyRestrictions", "iosKeyRestrictions") if name in restrictions),
            "none",
        )
        print(f"  uid                {key.get('uid')}")
        print(f"  apiTargets         {len(targets)}: {', '.join(sorted(targets))}")
        print(f"  app restriction    {app_restriction}")

    stored = load_stored()
    print(f"\nSecrets Manager {SECRET_NAME}")
    print(f"  holds a value      {'yes' if stored else 'NO'}")
    if stored:
        print(f"  fingerprint        {fp(stored)}")
        ok, detail = probe_places_new(stored)
        print(f"  Places API (New)   {'ACCEPTED' if ok else 'REFUSED'} - {detail}")
        return 0 if ok else 1
    return 1


def provision() -> int:
    existing = [
        k for k in run_gcloud(["services", "api-keys", "list"])
        if k.get("displayName") == DISPLAY_NAME
    ]
    if existing:
        print(f"A key named {DISPLAY_NAME!r} already exists "
              f"(uid {existing[0].get('uid')}). Refusing to mint a second.")
        print("Use --status to inspect it, or delete it in the console first.")
        return 1

    args = ["services", "api-keys", "create", f"--display-name={DISPLAY_NAME}"]
    args += [f"--api-target=service={service}" for service in API_TARGETS]
    created = run_gcloud(args)

    response = created.get("response") or created
    key_string = response.get("keyString")
    if not key_string:
        # The key exists but its string was not returned. Do not guess; tell the operator
        # exactly what to do, and do not print a command that would echo the value.
        raise SystemExit(
            "Key created but gcloud did not return keyString. Retrieve it with "
            "`gcloud services api-keys get-key-string <uid>` in a private shell and store "
            "it with this script's --store-from-stdin path - do NOT paste it into a chat."
        )

    name = response.get("name", "?")
    uid = response.get("uid", name.rsplit("/", 1)[-1])
    outcome = store(key_string)

    print(f"Created  {name}")
    print(f"  uid              {uid}")
    print(f"  apiTargets       {len(API_TARGETS)}: {', '.join(API_TARGETS)}")
    print(f"  app restriction  none (deliberate: Lambda has no stable egress IP)")
    print(f"  fingerprint      {fp(key_string)}")
    print(f"  stored           {SECRET_NAME} ({outcome})")

    ok, detail = probe_places_new(key_string)
    print(f"  Places API (New) {'ACCEPTED' if ok else 'REFUSED'} - {detail}")
    if not ok:
        print("\nA new key can take a minute to propagate. Re-run with --verify.")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true",
                       help="mint the key, store it, and verify it")
    group.add_argument("--status", action="store_true",
                       help="report key and secret state without changing anything")
    group.add_argument("--verify", action="store_true",
                       help="re-run the live Places API (New) probe")
    args = parser.parse_args()

    if args.create:
        return provision()
    if args.verify:
        stored = load_stored()
        if not stored:
            print(f"{SECRET_NAME} holds no value; run --create first.")
            return 1
        ok, detail = probe_places_new(stored)
        print(f"{SECRET_NAME} {fp(stored)}: "
              f"Places API (New) {'ACCEPTED' if ok else 'REFUSED'} - {detail}")
        return 0 if ok else 1
    return report_status()


if __name__ == "__main__":
    sys.exit(main())
