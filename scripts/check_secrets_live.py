#!/usr/bin/env python3
"""Ask each provider whether the credential in Secrets Manager actually works.

Rotating a key by hand has two failure modes that look identical from the outside:
the new value was typed wrong, or the new value was never activated at the
provider. Both leave Secrets Manager looking perfectly healthy. The only way to
tell is to spend the credential against the provider and read the answer.

Run this after every manual rotation. VALID means the provider accepted it just
now, not that a field is non-empty.

    python scripts/check_secrets_live.py
    python scripts/check_secrets_live.py --only razorpay
    python scripts/check_secrets_live.py --json

Statuses:
    VALID       the provider accepted the credential
    INVALID     the provider rejected it - the rotation is not finished
    UNTESTABLE  no read-only endpoint can validate it alone (documented per item)
    ERROR       the check itself failed (network, timeout, unexpected response)

Values are read into memory, reported as a sha256 prefix, and never printed,
logged or placed on a command line. Exit status is 1 if anything is INVALID.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import boto3
from botocore.exceptions import ClientError

import meta_graph_version

REGION = "us-east-1"
TIMEOUT = 20


def fp(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def http(url: str, *, headers=None, data=None, method=None) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw[:200].decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return e.code, raw[:200].decode(errors="replace")


def basic(user: str, password: str) -> dict:
    tok = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {tok}"}


# --------------------------------------------------------------------------
# Per-provider checks. Each returns (status, detail).
# --------------------------------------------------------------------------
def check_meta(s: dict) -> list[tuple[str, str, str, str]]:
    out = []
    token, app_id, app_secret = s.get("access_token"), s.get("app_id"), s.get("app_secret")
    if token and app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        code, body = http(meta_graph_version.graph_base() + "/me?" + urllib.parse.urlencode(
            {"access_token": token, "appsecret_proof": proof, "fields": "id,name"}))
        if code == 200:
            out.append(("access_token + app_secret", "VALID",
                        f"Graph /me answered for id={body.get('id','?')}", fp(token)))
        else:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            out.append(("access_token + app_secret", "INVALID",
                        f"HTTP {code}: {str(err.get('message'))[:90]}", fp(token)))
    if app_id and app_secret:
        code, body = http(meta_graph_version.graph_base() + "/" + app_id + "?" +
                          urllib.parse.urlencode({"access_token": f"{app_id}|{app_secret}",
                                                  "fields": "id"}))
        out.append(("app_secret (app token)", "VALID" if code == 200 else "INVALID",
                    f"HTTP {code}", fp(app_secret)))
    for field in ("client_token", "client_token_waba2"):
        if s.get(field):
            out.append((field, "UNTESTABLE",
                        "client tokens only authenticate client-side SDK calls; "
                        "no server endpoint validates one alone", fp(s[field])))
    if s.get("waba_t_verify_token"):
        out.append(("waba_t_verify_token", "UNTESTABLE",
                    "self-chosen value; validated by the webhook handshake - "
                    "see the wecare-whatsapp-calling smoke test", fp(s["waba_t_verify_token"])))
    return out


def check_razorpay(s: dict) -> list[tuple[str, str, str, str]]:
    kid, ksec = s.get("key_id"), s.get("key_secret")
    if not (kid and ksec):
        return [("key_id/key_secret", "ERROR", "field missing", "")]
    code, body = http("https://api.razorpay.com/v1/payments?count=1", headers=basic(kid, ksec))
    if code == 200:
        n = len(body.get("items", [])) if isinstance(body, dict) else 0
        return [("key_id + key_secret", "VALID", f"payments API answered, {n} item(s)", fp(ksec))]
    desc = ""
    if isinstance(body, dict):
        desc = str(body.get("error", {}).get("description", ""))[:90]
    return [("key_id + key_secret", "INVALID", f"HTTP {code}: {desc}", fp(ksec))]


def check_plivo(s: dict) -> list[tuple[str, str, str, str]]:
    aid, tok = s.get("auth_id"), s.get("auth_token")
    if not (aid and tok):
        return [("auth_id/auth_token", "ERROR", "field missing", "")]
    code, body = http(f"https://api.plivo.com/v1/Account/{aid}/", headers=basic(aid, tok))
    if code == 200:
        name = body.get("name", "?") if isinstance(body, dict) else "?"
        return [("auth_id + auth_token", "VALID", f"account API answered for '{name}'", fp(tok))]
    return [("auth_id + auth_token", "INVALID", f"HTTP {code}", fp(tok))]


def check_google_key(s: dict, field: str) -> list[tuple[str, str, str, str]]:
    """Probe the key against BOTH a legacy Maps API and Places API (New).

    Two endpoints, not one, because they are gated by different entries in the key's
    `apiTargets` restriction and a key can pass one while being unable to call the other.

    That is not hypothetical. Until 2026-09-26 the unified key allowlisted
    `places-backend.googleapis.com` (legacy Places) and **not** `places.googleapis.com`
    (Places New), while `places.googleapis.com` was enabled on the project. A
    Geocoding-only check reported VALID throughout, so the one restriction that blocked
    the address-capture migration was invisible to the checker that existed to catch
    exactly this.

    Legacy Places Autocomplete is deprecated, so the New probe is the one that matters
    going forward; the legacy probe stays because the live Places proxy in
    `whatsapp-templates/handler.py` still calls the legacy web service.
    """
    key = s.get(field)
    if not key:
        return []

    rows: list[tuple[str, str, str, str]] = []

    # 1. Legacy Maps, via Geocoding.
    code, body = http("https://maps.googleapis.com/maps/api/geocode/json?" +
                      urllib.parse.urlencode({"address": "New Delhi", "key": key}))
    status = body.get("status") if isinstance(body, dict) else "?"
    if code == 200 and status in ("OK", "ZERO_RESULTS"):
        rows.append((f"{field} [legacy Geocoding]", "VALID",
                     f"Geocoding answered status={status}", fp(key)))
    elif status == "REQUEST_DENIED":
        msg = str(body.get("error_message", ""))[:120] if isinstance(body, dict) else ""
        lowered = msg.lower()
        if "referer restrictions" in lowered or "referrer restrictions" in lowered:
            # Same reasoning as the Places probe: a statement about the test, not the key.
            verdict = "UNTESTABLE"
        elif "api key" in lowered or "expired" in lowered:
            verdict = "INVALID"
        else:
            verdict = "UNTESTABLE"
        rows.append((f"{field} [legacy Geocoding]", verdict, f"REQUEST_DENIED: {msg}", fp(key)))
    else:
        rows.append((f"{field} [legacy Geocoding]", "ERROR",
                     f"HTTP {code} status={status}", fp(key)))

    rows.append(_check_places_new(key, field))
    return rows


def _check_places_new(key: str, field: str) -> tuple[str, str, str, str]:
    """Does this key answer on Places API (New) Autocomplete?

    Verdicts are kept distinct rather than collapsed into pass/fail, because the useful
    information is *why* a refusal happened and they call for opposite responses:

      API_KEY_SERVICE_BLOCKED   the key's apiTargets omit places.googleapis.com
                                -> fix the key restriction
      API_KEY_HTTP_REFERRER_BLOCKED
                                the key is browser-restricted and this is a server call
                                with no Referer -> the key needs a server-side sibling,
                                which is the split this repo still owes
      SERVICE_DISABLED          places.googleapis.com is off on the project
      INVALID_ARGUMENT          key accepted, request shape wrong -> our bug, not the key

    Collapsing these to INVALID would send someone to rotate a perfectly good key, which
    is the same mistake the OpenAI check below documents at length.
    """
    code, body = http(
        "https://places.googleapis.com/v1/places:autocomplete",
        method="POST",
        headers={"Content-Type": "application/json",
                 "X-Goog-Api-Key": key,
                 # Ask for the smallest possible response.
                 "X-Goog-FieldMask": "suggestions.placePrediction.placeId"},
        data=json.dumps({"input": "New Delhi", "regionCode": "IN"}).encode(),
    )
    label = f"{field} [Places API New]"

    if code == 200:
        n = len((body or {}).get("suggestions", [])) if isinstance(body, dict) else 0
        return (label, "VALID", f"Autocomplete answered with {n} suggestion(s)", fp(key))

    reason, message = "", ""
    if isinstance(body, dict):
        err = body.get("error") or {}
        message = str(err.get("message", ""))[:120]
        for detail in err.get("details") or []:
            if detail.get("reason"):
                reason = str(detail["reason"])
                break

    # ORDER MATTERS, and getting it wrong is how this check lied on its first run.
    # A referrer refusal also contains the word "blocked", so a generic
    # `"blocked" in message` test placed first swallows it and reports a *service*
    # restriction instead - sending someone to edit apiTargets when the entry is already
    # there and the real problem is that a browser key cannot be used server-side at all.
    # Specific reason codes are therefore matched before any substring fallback, and the
    # raw reason is always carried into the detail so the next reader can see it.
    if reason == "API_KEY_HTTP_REFERRER_BLOCKED":
        # UNTESTABLE, not INVALID, and the distinction is the whole point of this file's
        # verdict vocabulary. A referrer-restricted key may be perfectly valid; this script
        # simply cannot exercise it, because it is not a browser and sends no Referer.
        # Calling it INVALID makes the run report "a rotation is incomplete" when no
        # rotation is owed, which is the same misleading collapse the OpenAI check below
        # documents. The genuine defect - a browser key wired into a server-side code path
        # - is named in the detail so it does not become invisible.
        return (label, "UNTESTABLE",
                "browser-key referrer restriction: cannot be validated server-side. If a "
                "Lambda reads this secret, that is a defect - it needs the server-restricted "
                "sibling wecare/google-maps-server; adding apiTargets will NOT fix it",
                fp(key))
    if reason == "API_KEY_SERVICE_BLOCKED":
        return (label, "INVALID",
                "key restriction does not allow places.googleapis.com - add it to apiTargets",
                fp(key))
    if reason == "SERVICE_DISABLED":
        return (label, "INVALID", "places.googleapis.com is not enabled on the project", fp(key))
    if code == 403:
        return (label, "INVALID", f"403 reason={reason or 'unknown'}: {message}", fp(key))
    if code == 400:
        return (label, "UNTESTABLE", f"key accepted, request rejected: {message}", fp(key))
    if code == 429:
        return (label, "UNTESTABLE", "quota exhausted - key not proven either way", fp(key))
    return (label, "ERROR", f"HTTP {code} {reason or message}", fp(key))


def check_openai(s: dict) -> list[tuple[str, str, str, str]]:
    """401 means the key is dead. 403 means it authenticated and lacks a scope.

    Treating both as failure is wrong and actively misleading during a rotation:
    a scope-restricted service-account key is working exactly as issued, and
    reporting it as INVALID sends someone to re-rotate a perfectly good key.

    The OpenAI-Organization header is deliberately not sent. The organization_id
    stored beside this key no longer matches the key's own organization, and
    supplying it turns a working request into `mismatched_organization`.
    """
    out = []
    for field in ("ads_service_account_api_key", "project_api_key"):
        key = s.get(field)
        if not key:
            continue
        code, body = http("https://api.openai.com/v1/models",
                          headers={"Authorization": f"Bearer {key}"})
        msg = ""
        if isinstance(body, dict):
            err = body.get("error")
            msg = err if isinstance(err, str) else str((err or {}).get("message", ""))
        if code == 200:
            n = len(body.get("data", [])) if isinstance(body, dict) else 0
            out.append((field, "VALID", f"{n} model(s) listed", fp(key)))
        elif code == 403 and ("scope" in msg.lower() or "permission" in msg.lower()):
            out.append((field, "VALID",
                        "authenticated; scope-restricted by design "
                        f"({msg.split('.')[0][:60]})", fp(key)))
        else:
            out.append((field, "INVALID", f"HTTP {code}: {msg[:80]}", fp(key)))
    return out


def check_shared_secret(s: dict, field: str, what: str) -> list[tuple[str, str, str, str]]:
    v = s.get(field)
    if not v:
        return []
    return [(field, "UNTESTABLE", what, fp(v))]


CHECKS = {
    # A checker function that is not registered here never runs, and the report still
    # looks complete. Adding a checker without adding its line below is a no-op.
    "wecare/meta-system-user-token": check_meta,
    "wecare/razorpay/api": check_razorpay,
    "wecare/plivo/api": check_plivo,
    "wecare/openai/api": check_openai,
    "wecare/google-api-key": lambda s: check_google_key(s, "api_key"),
    "wecare/google/cloud": lambda s: check_google_key(s, "unified_google_api_key"),
    # Registered 2026-09-26, after it was found missing from this table: this is the secret
    # the live Places proxy actually reads (whatsapp-templates/handler.py, SecretId
    # 'wecare/google-maps', field 'api_key'), and it was the one Google secret NOT in this
    # table. So the credential that address capture depends on was the credential nothing
    # checked, while two adjacent Google secrets were checked diligently.
    #
    # It is EXPECTED to report INVALID on both probes, and that is the finding rather than
    # a fault in the check: it holds the browser key, and Google refuses referrer-restricted
    # keys for server-side calls. Fixed by wecare/google-maps-server below, not by editing
    # this key. Left registered so the day someone points a browser key at a server path
    # again, this says so.
    "wecare/google-maps": lambda s: check_google_key(s, "api_key"),
    # The server-restricted sibling, minted 2026-09-26 by
    # scripts/provision_maps_server_key.py. No application restriction by design - Lambda
    # has no stable egress IP - scoped instead to 4 apiTargets against the unified key's 49.
    "wecare/google-maps-server": lambda s: check_google_key(s, "api_key"),
    "wecare/razorpay-webhook": lambda s: check_shared_secret(
        s, "webhook_secret",
        "shared HMAC secret - no endpoint validates it; proven only when Razorpay "
        "delivers a webhook whose signature verifies"),
    "wecare/plivo-answer": lambda s: check_shared_secret(
        s, "token", "our own callback gate token, not a provider credential"),
    "wecare/google/ads": lambda s: check_shared_secret(
        s, "developer_token",
        "Google Ads needs the developer token plus an OAuth credential together"),
    "wecare/seo/google-oauth": lambda s: check_shared_secret(
        s, "client_secret", "OAuth client secret is only exercised by a full auth flow"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring filter on the secret id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sm = boto3.client("secretsmanager", region_name=REGION)
    print("=" * 78)
    print("LIVE CREDENTIAL CHECK - each value is spent against its provider")
    print("=" * 78)

    rows, tally = [], {"VALID": 0, "INVALID": 0, "UNTESTABLE": 0, "ERROR": 0}
    for sid, fn in sorted(CHECKS.items()):
        if args.only and args.only not in sid:
            continue
        try:
            doc = json.loads(sm.get_secret_value(SecretId=sid)["SecretString"])
        except ClientError as exc:
            print(f"\n{sid}\n  ERROR       cannot read: {exc.response['Error']['Code']}")
            tally["ERROR"] += 1
            continue
        except json.JSONDecodeError:
            print(f"\n{sid}\n  ERROR       not JSON")
            tally["ERROR"] += 1
            continue
        print(f"\n{sid}")
        try:
            results = fn(doc)
        except Exception as exc:  # noqa: BLE001
            results = [("(check)", "ERROR", f"{type(exc).__name__}: {exc}"[:90], "")]
        if not results:
            print("  (no checkable field present)")
        for field, status, detail, digest in results:
            tally[status] = tally.get(status, 0) + 1
            tag = f"sha256:{digest}" if digest else ""
            print(f"  {status:11s} {field:26s} {detail}")
            if tag:
                print(f"              {tag}")
            rows.append({"secret": sid, "field": field, "status": status,
                         "detail": detail, "fp": digest})

    print("\n" + "=" * 78)
    print(f"VALID {tally['VALID']}   INVALID {tally['INVALID']}   "
          f"UNTESTABLE {tally['UNTESTABLE']}   ERROR {tally['ERROR']}")
    print(f"RESULT: {'PASS' if tally['INVALID'] == 0 else 'FAIL - a rotation is incomplete'}")
    print("=" * 78)
    if args.json:
        print(json.dumps(rows, indent=2))
    return 1 if tally["INVALID"] else 0


if __name__ == "__main__":
    sys.exit(main())
