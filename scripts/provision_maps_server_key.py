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
    python scripts/provision_maps_server_key.py --verify      # re-run the live probes
    python scripts/provision_maps_server_key.py --store-from-stdin
                                                              # store a key you already
                                                              # hold, read from stdin

Exit status is 1 unless the key answers on all three probed surfaces: Places API (New),
Weather and Air Quality. Every run prints the one line that must be pasted into
FORBIDDEN_FINGERPRINTS in scripts/verify_public_bundle_secrets.py - without it, the
Amplify build gate that exists to stop an unrestricted server key reaching the public
JS bundle does not recognise this key.
"""
from __future__ import annotations

import argparse
import getpass
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
SECRET_NAME = "wecare/google/cloud"
SECRET_FIELD = "api_key"
DISPLAY_NAME = "WECARE Server Google API Key"
# The one project this repository's Google resources live in. Pinned rather than
# inherited: `api-keys create` against whatever `gcloud config get-value project`
# happens to resolve to would mint a key in the wrong project and this script would
# then store it as if it were correct.
PROJECT = "wecaredigitalbw"

# The file whose FORBIDDEN_FINGERPRINTS gate must learn this key's fingerprint.
# Printed, never read, by print_fingerprint_handoff().
BUNDLE_GATE = "scripts/verify_public_bundle_secrets.py"

# One bounded India coordinate for the Weather/Air Quality probes: New Delhi.
PROBE_LAT = 28.6139
PROBE_LNG = 77.2090

# Least privilege for the two server consumers: address capture + VayuLok environment.
# Deliberately NOT the unified key's broad service list.
#   places.googleapis.com          Places API (New) - autocomplete and place details
#   addressvalidation.googleapis.com  address verification
#   geocoding-backend.googleapis.com  geocoding, only where genuinely required
#   places-backend.googleapis.com     legacy Places. NOTE 2026-10-05: no code needs this
#                                     any more - the WhatsApp location-template proxy has
#                                     migrated to places.googleapis.com. Kept because
#                                     scripts/check_secrets_live.py diagnoses the unified
#                                     key by this target; drop it in a change that also
#                                     updates that diagnostic, not as a side effect here.
API_TARGETS = [
    "places.googleapis.com",
    "addressvalidation.googleapis.com",
    "geocoding-backend.googleapis.com",
    "places-backend.googleapis.com",
    # VayuLok environmental web-service calls. Kept server-side by
    # core/vayulok-environment; never add these to the public browser key.
    "airquality.googleapis.com",
    "weather.googleapis.com",
    # Existing canonical-secret consumer: core/site-language.
    "translate.googleapis.com",
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
    """Run gcloud and parse JSON. Output is NEVER echoed - it may carry a key string.

    `--project` is injected centrally, next to `--format=json`, rather than at each
    call site: a forgotten pin on `api-keys create` mints a key in whichever project
    the ambient gcloud config names, and the only signal would be a resource name
    printed after the fact.
    """
    proc = subprocess.run(
        [gcloud_path(), *args, f"--project={PROJECT}", "--format=json"],
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
    """Replace only the key fields in the canonical Google secret.

    wecare/google/cloud also holds project metadata. Replacing SecretString with
    {"api_key": ...} would delete those siblings, so read/merge/write is required.
    Both candidate key fields are set to the same server value because existing
    consumers deliberately try both while the historical field-name ambiguity is
    being retired.
    """
    client = secrets_client()
    try:
        raw = client.get_secret_value(SecretId=SECRET_NAME).get("SecretString") or "{}"
        current = json.loads(raw)
        if not isinstance(current, dict):
            # Not a JSON object, so there are no siblings to merge. Say so rather than
            # proceeding quietly: the docstring promises preservation, and this branch
            # does the opposite of that promise.
            print(f"  WARNING  {SECRET_NAME} did not hold a JSON object; "
                  f"no sibling field can be preserved. The prior version remains "
                  f"available as AWSPREVIOUS.")
            current = {}
        outcome = "new version"
    except client.exceptions.ResourceNotFoundException:
        current = {}
        outcome = "created"
    except (json.JSONDecodeError, TypeError):
        print(f"  WARNING  {SECRET_NAME}'s SecretString did not parse as JSON; "
              f"no sibling field can be preserved. The prior version remains "
              f"available as AWSPREVIOUS.")
        current = {}
        outcome = "new version"

    # Field NAMES only. A name is not a secret, and printing them is what makes
    # "project metadata survived the write" checkable without reading the secret
    # back - a count alone would not say WHICH fields survived.
    preserved = sorted(
        name for name in current if name not in (SECRET_FIELD, "unified_google_api_key")
    )
    if preserved:
        print(f"  preserved fields   {len(preserved)}: {', '.join(preserved)}")
    else:
        print("  preserved fields   none (no sibling fields were present)")

    current[SECRET_FIELD] = value
    current["unified_google_api_key"] = value
    payload = json.dumps(current)
    if outcome == "created":
        client.create_secret(
            Name=SECRET_NAME,
            Description=(
                "Canonical server-side Google credential and project metadata. "
                "Key value is not browser-safe; browser Maps key lives in Amplify."
            ),
            SecretString=payload,
        )
    else:
        client.put_secret_value(SecretId=SECRET_NAME, SecretString=payload)
    return outcome


def load_stored() -> str | None:
    """Read the stored value for verification only. Returned, never printed."""
    try:
        raw = secrets_client().get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    except ClientError:
        return None
    try:
        data = json.loads(raw)
        return data.get(SECRET_FIELD) or data.get("unified_google_api_key")
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


def probe_weather(key: str) -> tuple[bool, str]:
    """Ask the Weather API whether it accepts this key. Returns (ok, detail).

    One request, one bounded India coordinate. Exists because a green --create used to
    prove only that Places answered, while Weather and Air Quality are the two services
    this whole change exists for.
    """
    request = urllib.request.Request(
        "https://weather.googleapis.com/v1/currentConditions:lookup"
        f"?location.latitude={PROBE_LAT}&location.longitude={PROBE_LNG}",
        method="GET",
        headers={"Accept": "application/json", "X-Goog-Api-Key": key},
    )
    return _probe(request, lambda body: "current conditions returned")


def probe_air_quality(key: str) -> tuple[bool, str]:
    """Ask the Air Quality API whether it accepts this key. Returns (ok, detail)."""
    request = urllib.request.Request(
        "https://airquality.googleapis.com/v1/currentConditions:lookup",
        method="POST",
        data=json.dumps(
            {"location": {"latitude": PROBE_LAT, "longitude": PROBE_LNG}}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
        },
    )
    return _probe(
        request,
        lambda body: f"{len(body.get('indexes', []))} index(es)",
    )


def _probe(request: urllib.request.Request, describe) -> tuple[bool, str]:
    """Shared probe transport. The key is only ever in the X-Goog-Api-Key header."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read() or b"{}")
        return True, describe(body)
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


def run_probes(key: str) -> bool:
    """All three live probes, one labelled line each. Returns the AND of them."""
    results = [
        ("Places API (New)", probe_places_new(key)),
        ("Weather API", probe_weather(key)),
        ("Air Quality API", probe_air_quality(key)),
    ]
    for label, (ok, detail) in results:
        print(f"  {label:<18} {'ACCEPTED' if ok else 'REFUSED'} - {detail}")
    if not all(ok for _, (ok, _) in results):
        print("\n  A refusal here can mean the API is NOT ENABLED in the project rather")
        print(f"  than the key being bad: an --api-target for a service that is not")
        print(f"  enabled in {PROJECT} does not fail at create time. Check")
        print(f"  `gcloud services list --enabled --project={PROJECT}` before")
        print("  concluding the key is wrong. A new key can also take a minute to")
        print("  propagate.")
    return all(ok for _, (ok, _) in results)


def print_fingerprint_handoff(value: str) -> None:
    """Print the one line that has to be pasted into the public-bundle gate.

    A fingerprint is one-way and safe to print; it is the only key-derived value that
    may be. Without this paste, FORBIDDEN_FINGERPRINTS stays empty and the Amplify
    build check written to stop an unrestricted server key being inlined into a public
    JS chunk does not recognise the one key it exists for.

    Deliberately the BARE 12-hex digest, not fp()'s `sha256:`-prefixed form:
    verify_public_bundle_secrets.py:fingerprint() returns the digest with no prefix and
    compares dict KEYS against that, so pasting the prefixed form would create an entry
    that can never match.

    The emitted block must stay VALID PYTHON, since the instruction above is to paste it
    verbatim. The two description lines are separate quoted literals relying on implicit
    concatenation; leaving the first one unterminated makes the gate script unimportable
    at the exact moment --create has just minted an unrestricted key. Pinned by
    tests/test_vayulok_server_key_provisioning.py, which ast.parses what this prints.
    """
    digest = fp(value).split(":", 1)[1]
    print("\n  NEXT STEP - teach the public-bundle gate this key, in the same change.")
    print(f"  Paste this entry into FORBIDDEN_FINGERPRINTS in {BUNDLE_GATE}:\n")
    print(f'    "{digest}": (')
    print('        "WECARE Server Google API Key - no application restriction, so it is"')
    print('        " usable by anyone who holds it and must never reach the export."')
    print("    ),")
    print(f"\n  (human-readable form: {fp(value)})")


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
        ok = run_probes(stored)
        print_fingerprint_handoff(stored)
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

    ok = run_probes(key_string)
    if not ok:
        # The store already succeeded, and --create's duplicate-name guard will refuse
        # a second run. Saying so here is the difference between re-running --verify and
        # trying to mint a second key.
        print(f"\n  The key WAS created and WAS stored in {SECRET_NAME}. Do NOT re-run")
        print("  --create: it refuses when a key with this display name exists. Re-run")
        print("  --verify once the probe target is resolved.")
    print_fingerprint_handoff(key_string)
    return 0 if ok else 1


def store_from_stdin() -> int:
    """Store a key the operator already holds, without it touching argv or stdout.

    The path `provision()` points at when gcloud created the key but did not return its
    string. That is the exact moment an operator is holding a live credential with
    nowhere safe to put it, which is how a value ends up pasted somewhere it must never
    go - so the flag the message names has to exist.

    getpass on a TTY so nothing is echoed; a bare readline otherwise so a password
    manager can pipe it. Never argv: "Always allow" records a whole command string, and
    that is precisely how four live credentials became permanent permission rules on
    2026-09-19.
    """
    if sys.stdin.isatty():
        value = getpass.getpass("Paste the key (not echoed): ")
    else:
        value = sys.stdin.readline()
    value = (value or "").strip()
    if not value:
        raise SystemExit("No value supplied on stdin; nothing stored.")
    # Shape only. Nothing about the value is printed, including on refusal.
    if not value.startswith("AIza") or len(value) < 30:
        raise SystemExit(
            "That does not have the shape of a Google API key (expected an AIza "
            "prefix and at least 30 characters). Nothing was stored, and the value "
            "was not printed."
        )

    outcome = store(value)
    print(f"  stored             {SECRET_NAME} ({outcome})")
    print(f"  fingerprint        {fp(value)}")
    ok = run_probes(value)
    print_fingerprint_handoff(value)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true",
                       help="mint the key, store it, and verify it")
    group.add_argument("--status", action="store_true",
                       help="report key and secret state without changing anything")
    group.add_argument("--verify", action="store_true",
                       help="re-run the live Places/Weather/Air Quality probes")
    group.add_argument("--store-from-stdin", action="store_true",
                       help="store a key read from stdin or a hidden prompt "
                            "(never from argv); use when gcloud created the key "
                            "but did not return its string")
    args = parser.parse_args()

    if args.create:
        return provision()
    if args.store_from_stdin:
        return store_from_stdin()
    if args.verify:
        stored = load_stored()
        if not stored:
            print(f"{SECRET_NAME} holds no value; run --create first.")
            return 1
        print(f"{SECRET_NAME} {fp(stored)}")
        ok = run_probes(stored)
        print_fingerprint_handoff(stored)
        return 0 if ok else 1
    return report_status()


if __name__ == "__main__":
    sys.exit(main())
