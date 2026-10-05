#!/usr/bin/env python3
"""Store the Wix Headless API key in AWS Secrets Manager. Hidden input only.

Why the key is typed at a prompt rather than passed as an argument
-----------------------------------------------------------------
On 2026-09-19 four live credentials ended up in plaintext inside Kiro's own
permissions file, because commands had been run with the credential inline and
"Always allow" recorded the whole command string. A credential in argv also lands in
shell history, in `ps` output for the life of the process, and in any CI log.

So this script takes the value through `getpass` and refuses to accept it any other
way. It prints metadata only - never the value, not even truncated. A fingerprint is
printed instead, which is enough to confirm two machines hold the same key without
either of them displaying it.

Two mechanisms, one secret
--------------------------
Wix documents the OAuth **client_credentials** grant as the recommended way to
authorize admin operations from a headless project: exchange client id + client secret
for a short-lived access token, then call the admin APIs with that token. The permanent
admin API key is the older mechanism and is what `wecare-wix-store` reads today.

Both can be stored side by side (`api_key`, `client_secret`) so a migration can store
and verify the new mechanism before removing the old one. Supplying one does not erase
the other.

Usage
-----
    python scripts/set_wix_credential.py --status            # read nothing, report state

    python scripts/set_wix_credential.py                     # store / replace the API key
    python scripts/set_wix_credential.py --verify            # store, then prove it works

    python scripts/set_wix_credential.py --client-secret     # store the OAuth client secret
    python scripts/set_wix_credential.py --client-secret --verify-oauth

    python scripts/set_wix_credential.py --set-env           # also point the Lambda at it
    python scripts/set_wix_credential.py --enable            # also clear the kill switch

`--set-env` writes only the secret's NAME into the function environment, which is not
a credential. `--enable` clears `WIX_CREDENTIALS_DISABLED`, and is deliberately a
separate flag because it is the step that makes Wix live again.

`--verify` exercises the API key against the sites endpoint. `--verify-oauth` exercises
the client secret against the token endpoint. Neither prints a credential or a token.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Must match src/config/wix.ts WIX_API_KEY_SECRET and the secret that actually exists
# in the account. This constant read "wecare/wix/headless" until 2026-09-26, which is a
# name that has never existed: `--status` therefore reported `exists: false` for a secret
# that was present, and `--set-env` would have pointed the live Lambda at nothing. The
# handler's loader raises RuntimeError when the secret is unreadable, so the failure mode
# was a hard 500 on every Wix call, attributed to the wrong cause.
SECRET_NAME = "wecare/wix/headless-api-key"

FUNCTION = "wecare-wix-store"

# Wix OAuth token endpoint for the client_credentials grant.
WIX_TOKEN_URL = "https://www.wixapis.com/oauth2/token"

# Non-secret identifiers. Safe to hold in source: they name resources, they do not
# grant access to them. Confirmed against the live function config on 2026-09-23,
# where WIX_ACCOUNT_ID and WIX_SITE_ID already carried exactly these values.
WIX_ACCOUNT_ID = "478bf907-96cc-4cab-9220-bb96f1d35cbb"
WIX_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"
WIX_CLIENT_ID = "42b3cdbf-d90e-4138-a06c-ddda4fb8da01"
WIX_CLIENT_NAME = "apiwx"

WIX_API_BASE = "https://www.wixapis.com"


def fingerprint(value: str) -> str:
    """A stable, non-reversible identity for a secret value.

    Twelve hex characters of SHA-256. Enough to confirm that the key in AWS is the one
    you meant to store, without displaying any part of it. Never print a prefix or a
    suffix of a credential - an issuer prefix plus a length is a meaningful head start.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def refuse_argv_secrets(argv: list) -> None:
    """Refuse if the key looks like it was passed on the command line."""
    for arg in argv:
        if arg.startswith("IST.") or len(arg) > 80:
            sys.exit(
                "REFUSED: that looks like a credential passed as an argument.\n"
                "Run the script with no value and paste it at the hidden prompt. A "
                "credential in argv lands in shell history and in ps output."
            )
    for name in ("WIX_API_KEY", "WIX_KEY", "WIX_TOKEN"):
        if os.environ.get(name):
            sys.exit(
                f"REFUSED: {name} is set in the environment.\n"
                "Unset it and use the hidden prompt. An environment variable holding a "
                "credential is readable by every child process."
            )


def read_key_hidden() -> str:
    """Read the key without echoing it. Validates shape without printing any of it."""
    print("Paste the Wix Headless API key. It will NOT be displayed.")
    print("(Wix shows it once, at creation, in Headless > API keys.)")
    key = getpass.getpass("Wix API key: ").strip()

    if not key:
        sys.exit("REFUSED: empty value.")
    if len(key) < 60:
        sys.exit(f"REFUSED: value is {len(key)} characters, too short for a Wix API "
                 f"key. Nothing was written.")
    if not key.startswith("IST."):
        print("WARNING: value does not begin with the usual Wix API key marker.")
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit("Aborted. Nothing was written.")

    again = getpass.getpass("Paste it again to confirm: ").strip()
    if again != key:
        sys.exit("REFUSED: the two entries differ. Nothing was written.")
    return key


def read_client_secret_hidden() -> str:
    """Read the OAuth client secret without echoing it.

    A client secret is not an `IST.` JWT, so the API-key shape checks do not apply. It is
    still admin-equivalent: exchanged for an access token via client_credentials it grants
    the headless project's own permissions.
    """
    print("Paste the Wix Headless OAuth CLIENT SECRET. It will NOT be displayed.")
    print("(Wix dashboard > Headless > OAuth apps > your app > client secret.)")
    secret = getpass.getpass("Wix client secret: ").strip()

    if not secret:
        sys.exit("REFUSED: empty value.")
    if len(secret) < 20:
        sys.exit(f"REFUSED: value is {len(secret)} characters, too short for a Wix client "
                 f"secret. Nothing was written.")

    again = getpass.getpass("Paste it again to confirm: ").strip()
    if again != secret:
        sys.exit("REFUSED: the two entries differ. Nothing was written.")
    return secret


def store(key: str = "", client_secret: str = "") -> dict:
    """Create or replace the secret, preserving whichever credential is not supplied.

    Two mechanisms can live in this one secret:

      api_key        the legacy permanent Wix admin API key. `wix-store`'s loader reads
                     this field first, so it stays the field name.
      client_secret  the OAuth client secret, exchanged for a short-lived access token
                     via the client_credentials grant. This is what Wix documents as the
                     recommended way to authorize headless admin operations, and it is
                     what the conversational-commerce spec targets.

    Supplying one does not erase the other, so a migration can store the client secret,
    verify it, and only then drop the API key.
    """
    client = boto3.client("secretsmanager", region_name=REGION)

    fields = {
        "account_id": WIX_ACCOUNT_ID,
        "site_id": WIX_SITE_ID,
        "client_id": WIX_CLIENT_ID,
        "client_name": WIX_CLIENT_NAME,
    }

    # Preserve any credential we were not given. Read into memory, merged, written back —
    # never rendered. Same justification as scripts/sync_pasted_credentials.py.
    existing: dict = {}
    try:
        raw = client.get_secret_value(SecretId=SECRET_NAME).get("SecretString") or "{}"
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            existing = parsed
        del raw, parsed
    except (ClientError, json.JSONDecodeError, TypeError, ValueError):
        # Absent, empty (no AWSCURRENT version), or a bare string. Nothing to preserve.
        pass

    for name, supplied in (("api_key", key), ("client_secret", client_secret)):
        value = supplied or existing.get(name, "")
        if value:
            fields[name] = value

    if not (fields.get("api_key") or fields.get("client_secret")):
        sys.exit("REFUSED: that would store no credential at all. Nothing was written.")

    payload = json.dumps(fields)

    try:
        response = client.create_secret(
            Name=SECRET_NAME,
            Description="Wix Headless API key and non-secret ids for wecare-wix-store.",
            SecretString=payload,
        )
        action = "created"
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceExistsException":
            raise
        response = client.put_secret_value(SecretId=SECRET_NAME, SecretString=payload)
        action = "replaced"

    result = {
        "action": action,
        "arn": response.get("ARN"),
        "versionId": response.get("VersionId"),
        # Reported from what was actually written, not from a hardcoded list that could
        # drift from the payload.
        "fields": sorted(fields),
        "credentialsPresent": sorted(
            name for name in ("api_key", "client_secret") if fields.get(name)),
    }
    # Fingerprint only what this invocation supplied. Fingerprinting a preserved value
    # would disclose something the caller did not provide and does not need.
    if key:
        result["apiKeyLength"] = len(key)
        result["apiKeyFingerprint"] = fingerprint(key)
    if client_secret:
        result["clientSecretLength"] = len(client_secret)
        result["clientSecretFingerprint"] = fingerprint(client_secret)
    return result


def set_env_pointer() -> dict:
    """Point the Lambda at the secret by NAME. Not a credential."""
    client = boto3.client("lambda", region_name=REGION)
    current = client.get_function_configuration(FunctionName=FUNCTION)
    env = dict((current.get("Environment") or {}).get("Variables", {}) or {})
    before = sorted(env)

    env["WIX_API_KEY_SECRET"] = SECRET_NAME
    env.setdefault("WIX_ORDER_IDS_TABLE", "stack-wecare-digital-WixOrderIds")

    client.update_function_configuration(
        FunctionName=FUNCTION, Environment={"Variables": env})
    after = client.get_function_configuration(FunctionName=FUNCTION)
    keys = sorted((after.get("Environment") or {}).get("Variables", {}))
    return {"before": before, "after": keys, "added": sorted(set(keys) - set(before))}


def enable() -> dict:
    """Clear WIX_CREDENTIALS_DISABLED. The step that makes Wix live again.

    Separate flag on purpose: storing a key is reversible and inert, whereas clearing
    the switch changes what the running system does.
    """
    client = boto3.client("lambda", region_name=REGION)
    current = client.get_function_configuration(FunctionName=FUNCTION)
    env = dict((current.get("Environment") or {}).get("Variables", {}) or {})
    was = env.pop("WIX_CREDENTIALS_DISABLED", None)
    env.pop("CREDENTIAL_PURGE_EPOCH", None)
    client.update_function_configuration(
        FunctionName=FUNCTION, Environment={"Variables": env})
    return {"wasDisabled": was, "nowDisabled": False}


def verify() -> dict:
    """One live READ against Wix to prove the stored key works.

    Reads the value straight from Secrets Manager into memory for a single request and
    never logs it. This is the one place a read is unavoidable - the point of the
    exercise is to prove the provider accepts it, and only the provider can say.
    """
    raw = boto3.client("secretsmanager", region_name=REGION).get_secret_value(
        SecretId=SECRET_NAME)["SecretString"]
    key = json.loads(raw)["api_key"]

    # Ask for a full page, not one row. This used to send `limit: 1` and then report
    # `matchesConfiguredSiteId` from that single row - an assertion that could only ever
    # be true by luck. On 2026-09-26 it reported `false` against a correctly configured
    # site simply because a different site sorted first, which reads as "wrong site
    # configured" and would send someone to change a correct value.
    request = urllib.request.Request(
        f"{WIX_API_BASE}/site-list/v2/sites/query",
        data=json.dumps({"query": {"paging": {"limit": 100}}}).encode(),
        headers={
            "Authorization": key,
            "Content-Type": "application/json",
            "wix-account-id": WIX_ACCOUNT_ID,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode() or "{}")
        sites = body.get("sites") or []
        # Site ids and display names are not credentials. Listing them is what makes the
        # "is the configured site the right one?" question answerable instead of guessed.
        inventory = [
            {
                "id": s.get("id"),
                "name": s.get("displayName", ""),
                "published": s.get("published", False),
                "isConfigured": s.get("id") == WIX_SITE_ID,
            }
            for s in sites
        ]
        return {
            "accepted": True,
            "httpStatus": 200,
            "sitesVisible": len(sites),
            "totalResults": body.get("totalResults"),
            "configuredSiteId": WIX_SITE_ID,
            "matchesConfiguredSiteId": any(s["isConfigured"] for s in inventory),
            "sites": inventory,
        }
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read().decode() or "")[:200]
        except Exception:  # noqa: BLE001
            pass
        return {"accepted": False, "httpStatus": exc.code, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"accepted": False, "error": type(exc).__name__}


def verify_client_credentials() -> dict:
    """Prove the stored client secret can mint an access token via client_credentials.

    Wix documents this grant as the recommended way to authorize admin operations from a
    headless project. Only the provider can confirm the secret is accepted, so one live
    exchange is unavoidable. The token is counted and discarded; neither the secret nor
    the token is logged.
    """
    try:
        raw = boto3.client("secretsmanager", region_name=REGION).get_secret_value(
            SecretId=SECRET_NAME)["SecretString"]
    except ClientError as exc:
        return {"accepted": False, "reason": f"secret unreadable ({type(exc).__name__})"}

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"accepted": False, "reason": "secret is not a JSON object"}
    finally:
        del raw

    client_secret = (data.get("client_secret") or "").strip()
    client_id = (data.get("client_id") or WIX_CLIENT_ID).strip()
    if not client_secret:
        return {"accepted": False, "reason": "no client_secret stored; run --client-secret"}

    request = urllib.request.Request(
        WIX_TOKEN_URL,
        data=json.dumps({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    del data, client_secret

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode() or "{}")
        token = body.get("access_token") or ""
        return {
            "accepted": bool(token),
            "httpStatus": 200,
            "tokenType": body.get("token_type"),
            "expiresIn": body.get("expires_in"),
            "tokenLength": len(token),
        }
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read().decode() or "")[:200]
        except Exception:  # noqa: BLE001
            pass
        return {"accepted": False, "httpStatus": exc.code, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"accepted": False, "error": type(exc).__name__}


def status() -> dict:
    """Report state without reading any secret value."""
    sm = boto3.client("secretsmanager", region_name=REGION)
    out = {}
    try:
        described = sm.describe_secret(SecretId=SECRET_NAME)
        # A secret can exist as an empty container: created with a description and no
        # value, so it has no AWSCURRENT version and get_secret_value raises
        # ResourceNotFoundException. That was the live state on 2026-09-26, and reporting
        # only `exists: true` would have hidden it. Report stage coverage explicitly.
        stages = described.get("VersionIdsToStages") or {}
        has_current = any("AWSCURRENT" in s for s in stages.values())
        out["secret"] = {
            "name": described.get("Name"),
            "arn": described.get("ARN"),
            "lastChanged": str(described.get("LastChangedDate")),
            "lastAccessed": str(described.get("LastAccessedDate")),
            "exists": True,
            "versionCount": len(stages),
            "hasCurrentVersion": has_current,
            "holdsValue": has_current,
        }
    except ClientError:
        out["secret"] = {"name": SECRET_NAME, "exists": False, "holdsValue": False}

    config = boto3.client("lambda", region_name=REGION).get_function_configuration(
        FunctionName=FUNCTION)
    env = dict((config.get("Environment") or {}).get("Variables", {}) or {})
    out["function"] = {
        "name": FUNCTION,
        "apiKeySecretName": env.get("WIX_API_KEY_SECRET"),
        "accountId": env.get("WIX_ACCOUNT_ID"),
        "siteId": env.get("WIX_SITE_ID"),
        "credentialsDisabled": env.get("WIX_CREDENTIALS_DISABLED"),
        "accountIdMatchesExpected": env.get("WIX_ACCOUNT_ID") == WIX_ACCOUNT_ID,
        "siteIdMatchesExpected": env.get("WIX_SITE_ID") == WIX_SITE_ID,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true",
                        help="report state and exit; reads no secret value")
    parser.add_argument("--set-env", action="store_true",
                        help="point the Lambda at the secret by name")
    parser.add_argument("--enable", action="store_true",
                        help="clear WIX_CREDENTIALS_DISABLED")
    parser.add_argument("--verify", action="store_true",
                        help="make one live read against Wix to prove the API key works")
    parser.add_argument("--client-secret", action="store_true",
                        help="store the OAuth client secret instead of the API key")
    parser.add_argument("--verify-oauth", action="store_true",
                        help="exchange the stored client secret for an access token")
    args = parser.parse_args()

    refuse_argv_secrets(sys.argv[1:])

    if args.status:
        print(json.dumps(status(), indent=2))
        return 0

    # Operational flags run standalone against whatever is already stored. Originally all
    # of these were reachable only AFTER read_key_hidden(), so pointing the Lambda at an
    # already-stored secret, or clearing the kill switch, forced the operator to re-paste
    # a credential they had no reason to touch. Re-pasting a secret to perform an
    # operation that does not need it is how a secret ends up somewhere new.
    standalone = (args.verify_oauth or args.verify or args.set_env or args.enable)
    if standalone and not args.client_secret:
        if args.set_env:
            print("env pointer:", json.dumps(set_env_pointer(), indent=2))
        if args.enable:
            print("kill switch:", json.dumps(enable(), indent=2))
        if args.verify:
            print("provider verification:", json.dumps(verify(), indent=2))
        if args.verify_oauth:
            print("oauth verification:", json.dumps(verify_client_credentials(), indent=2))
        return 0

    if args.client_secret:
        client_secret = read_client_secret_hidden()
        result = store(client_secret=client_secret)
        client_secret = ""
    else:
        key = read_key_hidden()
        result = store(key=key)
        # Drop the local reference promptly. Not a guarantee in CPython, but it costs
        # nothing and narrows the window.
        key = ""
    print("\nstored:", json.dumps(result, indent=2))

    if args.set_env:
        print("env pointer:", json.dumps(set_env_pointer(), indent=2))
    if args.enable:
        print("kill switch:", json.dumps(enable(), indent=2))
    if args.verify:
        print("provider verification:", json.dumps(verify(), indent=2))
    if args.verify_oauth:
        print("oauth verification:", json.dumps(verify_client_credentials(), indent=2))

    print("\nThe value was never printed, logged, or passed as an argument.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
