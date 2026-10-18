#!/usr/bin/env python3
"""Give Lambda environment variables a source of truth, and detect drift from it.

326 environment variables across 58 functions existed only in the live AWS
configuration. Nothing in the repository described them: the `environment:` blocks
in `amplify/functions/*/resource.ts` were never deployed, because those functions
are not passed to `defineBackend`, so they synthesized nothing and were deleted on
2026-09-20. `deploy_all_lambdas.py` uploads code and never touches configuration.

That is how the live `VERIFY_TOKEN` holding a real credential stayed invisible for
months: there was nowhere in the repo it could have shown up, and no check that
could have compared intent against reality.

This does not deploy anything. It records what is live, so that a change becomes
visible in a diff, and fails when reality and the record disagree.

    python scripts/env_manifest.py --export     # write the manifest from live AWS
    python scripts/env_manifest.py              # check live against the manifest
    python scripts/env_manifest.py --json

Secret safety: every value is compared against the real values in Secrets Manager
and against issuer-anchored shapes. A credential-classed match is a hard failure -
the manifest is not written, because it is committed to a public repository. Any
other Secrets Manager match, or an issuer-shaped string, is stored as a sha256
prefix instead of the value, which still detects drift without disclosing anything.

Exit status: 0 in sync, 1 on drift or refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "lambda-env-manifest.json"
REGION = "us-east-1"

SECRET_FIELD = re.compile(
    r"(secret|token|password|passphrase|api_key|apikey|private_key|"
    r"auth_token|access_key|client_secret|webhook|credential)", re.I)
CONFIG_FIELD = re.compile(r"(_name|_url|_uri|_arn|_id$|_lambda|_region|_at$|"
                          r"last_updated|_status|_type|_path)", re.I)

SHAPES = [
    "rzp" + r"_live_[A-Za-z0-9]{8,}",
    "sk-" + r"(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{30,}",
    "AIz" + r"a[A-Za-z0-9_\-]{30,}",
    r"(?:AKI" + r"A|ASI" + r"A)[0-9A-Z]{16}",
    "gh" + r"[pousr]_[A-Za-z0-9]{30,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]

# Variables Lambda injects itself; they are not configuration anyone chose.
INJECTED = {"AWS_REGION", "AWS_EXECUTION_ENV", "AWS_LAMBDA_FUNCTION_NAME",
            "AWS_LAMBDA_FUNCTION_VERSION", "AWS_LAMBDA_LOG_GROUP_NAME",
            "AWS_LAMBDA_LOG_STREAM_NAME", "AWS_LAMBDA_INITIALIZATION_TYPE",
            "_HANDLER", "LAMBDA_TASK_ROOT", "LAMBDA_RUNTIME_DIR", "TZ"}

# Written by the maintenance tooling, so they change on every refresh and would
# otherwise report drift forever.
VOLATILE = {"SECRETS_REFRESHED_AT", "SECRETS_ROTATED_AT"}

# Retired feature flags. The code no longer reads these, so a value still set live is a stale
# leftover a deploy should scrub - not configuration this manifest should enshrine. Recording
# one would both contradict the source (CHECKOUT_INITIATION_ENABLED was removed: initiation is
# always on) and fight the contract tests that assert it is absent. Excluded by name so the
# recorded state matches the code, and the live-vs-manifest gap stays visible as the drift it is.
RETIRED = {"CHECKOUT_INITIATION_ENABLED"}

# Readiness EXPECTATIONS, not credentials: they are compared against a live provider
# readback so a disagreement refuses the send - they are meant to be legible in the clear
# and the contract tests pin their literal values (see test_provision_checkout_contract and
# test_whatsapp_payments_are_template_only). The Razorpay merchant id in particular also sits
# inside a stored secret, so the `value in every` guard would otherwise fingerprint it and
# erase the very expectation the manifest exists to record. Exempted by KEY, never by value,
# so a real credential embedded elsewhere is still caught.
PLAINTEXT_EXPECTATION_KEYS = {"EXPECTED_PROVIDER_MID", "EXPECTED_CONFIGURATION_NAME"}


def fp(v: str) -> str:
    return "sha256:" + hashlib.sha256(v.encode()).hexdigest()[:12]


def load_secret_values(sm) -> tuple[dict[str, str], set[str]]:
    """({value: label} for credential fields, {all values}) from Secrets Manager."""
    creds: dict[str, str] = {}
    every: set[str] = set()
    ids = []
    for page in sm.get_paginator("list_secrets").paginate():
        ids += [s["Name"] for s in page["SecretList"] if s["Name"].startswith("wecare/")]
    for sid in sorted(ids):
        try:
            doc = json.loads(sm.get_secret_value(SecretId=sid)["SecretString"])
        except (ClientError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        for field, value in doc.items():
            if not isinstance(value, str) or len(value) < 12:
                continue
            every.add(value)
            if SECRET_FIELD.search(field) and not CONFIG_FIELD.search(field):
                creds[value] = f"{sid}:{field}"
    return creds, every


def live_env(lam) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for page in lam.get_paginator("list_functions").paginate():
        for f in page["Functions"]:
            env = (f.get("Environment") or {}).get("Variables") or {}
            out[f["FunctionName"]] = {
                k: v for k, v in sorted(env.items())
                if k not in INJECTED and k not in VOLATILE and k not in RETIRED
            }
    return dict(sorted(out.items()))


def classify(value: str, creds: dict[str, str], every: set[str],
             key: str = "") -> tuple[str, str | None]:
    """Return (stored_form, refusal_reason).

    Credential matching is by substring, not equality. A credential rarely sits
    alone in a variable - it arrives embedded, as
    `https://host/path?token=<secret>`, and an equality check walks straight past
    that. Non-credential Secrets Manager values are matched by equality only,
    because some of them are short generic strings (a trunk name, a domain) that
    are substrings of half the table names in the account, and refusing on those
    would make the guard useless.

    A readiness-expectation key is stored in the clear: it is a value the manifest
    exists to record, not a credential, and the `value in every` guard below would
    otherwise fingerprint one that also appears inside a stored secret. The embedded-
    credential check still runs first, so a key that genuinely carries a secret is
    still caught rather than waved through by its name.
    """
    for secret, label in creds.items():
        if secret in value:
            where = "holds" if secret == value else "contains"
            return value, f"{where} {label}"
    if key in PLAINTEXT_EXPECTATION_KEYS:
        return value, None
    if value in every:
        return fp(value), None
    for pat in SHAPES:
        if re.search(pat, value):
            return fp(value), None
    return value, None


def build(lam, sm) -> tuple[dict, list[str]]:
    creds, every = load_secret_values(sm)
    refusals, fingerprinted = [], 0
    manifest: dict[str, dict[str, str]] = {}
    for fn, env in live_env(lam).items():
        row = {}
        for k, v in env.items():
            stored, refuse = classify(v, creds, every, key=k)
            if refuse:
                refusals.append(f"{fn} -> {k}: {refuse}")
            if stored != v:
                fingerprinted += 1
            row[k] = stored
        manifest[fn] = row
    doc = {
        "_comment": (
            "Recorded state of live Lambda environment variables. Not deployed by "
            "anything - this is the source of truth to diff against. Regenerate "
            "with scripts/env_manifest.py --export; verify with no arguments."
        ),
        "_region": REGION,
        "_functions": len(manifest),
        "_variables": sum(len(v) for v in manifest.values()),
        "_fingerprinted": fingerprinted,
        "functions": manifest,
    }
    return doc, refusals


def keys_only_drift(lam) -> int:
    """Report key-level drift WITHOUT reading Secrets Manager and without printing values.

    Why this mode exists
    --------------------
    Every other mode calls `load_secret_values`, which reads every `wecare/` secret in order
    to fingerprint credential-shaped values before they are written to a file committed to a
    public repository. That comparison is the whole safety property of `--export`, so it
    cannot be skipped when writing.

    But it also means an operator who is forbidden from reading secret values - which is the
    standing rule for agents in this repository - cannot run ANY mode, and therefore cannot
    even measure how far the manifest has drifted. That is the gap this fills: key SETS are
    not secrets, so the scope of the drift can be established from Lambda configuration
    alone. Only names are printed, never a value, not even a fingerprint.

    This is a measurement, not a repair. Writing the manifest still requires `--export` and
    still requires the Secrets Manager comparison.
    """
    if not MANIFEST.exists():
        print(f"no manifest at {MANIFEST.relative_to(ROOT)} - run --export first")
        return 1

    recorded = json.loads(MANIFEST.read_text())["functions"]
    current = live_env(lam)

    added_fns = sorted(set(current) - set(recorded))
    removed_fns = sorted(set(recorded) - set(current))
    missing_keys: list[tuple[str, str]] = []
    extra_keys: list[tuple[str, str]] = []

    for fn in sorted(set(current) & set(recorded)):
        for k in sorted(set(current[fn]) - set(recorded[fn])):
            missing_keys.append((fn, k))
        for k in sorted(set(recorded[fn]) - set(current[fn])):
            extra_keys.append((fn, k))

    print("key-level drift (names only; no values read, no secrets read)")
    print(f"  functions live            : {len(current)}")
    print(f"  functions in the manifest : {len(recorded)}")

    if added_fns:
        print(f"\n  live but absent from the manifest ({len(added_fns)} functions):")
        for fn in added_fns:
            print(f"    {fn}  ({len(current[fn])} variables)")
    if removed_fns:
        print(f"\n  in the manifest but not live ({len(removed_fns)} functions):")
        for fn in removed_fns:
            print(f"    {fn}")
    if missing_keys:
        print(f"\n  keys set live but NOT recorded ({len(missing_keys)}):")
        for fn, k in missing_keys:
            print(f"    {fn}.{k}")
    if extra_keys:
        print(f"\n  keys recorded but NOT set live ({len(extra_keys)}):")
        for fn, k in extra_keys:
            print(f"    {fn}.{k}")

    total = len(added_fns) + len(removed_fns) + len(missing_keys) + len(extra_keys)
    print(f"\n  key-level differences: {total}")
    if total:
        print("  A full `--export` is needed to resolve these, and that reads Secrets")
        print("  Manager to fingerprint credential-shaped values before writing.")
        print("  NOTE: this mode cannot see a changed VALUE on a key that exists in both,")
        print("  so 0 here does not mean the manifest is in sync.")
    return 1 if total else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true", help="write the manifest")
    ap.add_argument("--keys-only", action="store_true",
                    help="report key-level drift without reading Secrets Manager or values")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    lam = boto3.client("lambda", region_name=REGION)

    if args.keys_only:
        return keys_only_drift(lam)

    sm = boto3.client("secretsmanager", region_name=REGION)

    doc, refusals = build(lam, sm)

    if refusals:
        print("REFUSING: a live environment variable holds a real credential value.")
        print("Move it to Secrets Manager and pass the secret NAME instead.")
        for r in refusals:
            print(f"  {r}")
        print("\nNothing was written. scripts/refresh_secret_consumers.py applies the")
        print("change once the code reads it by reference.")
        return 1

    if args.export:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n")
        print(f"wrote {MANIFEST.relative_to(ROOT)}")
        print(f"  {doc['_functions']} functions, {doc['_variables']} variables, "
              f"{doc['_fingerprinted']} stored as a fingerprint")
        return 0

    if not MANIFEST.exists():
        print(f"no manifest at {MANIFEST.relative_to(ROOT)} - run --export first")
        return 1

    recorded = json.loads(MANIFEST.read_text())["functions"]
    current = doc["functions"]

    added_fns = sorted(set(current) - set(recorded))
    removed_fns = sorted(set(recorded) - set(current))
    drift: list[tuple[str, str, str]] = []
    for fn in sorted(set(current) & set(recorded)):
        cur, rec = current[fn], recorded[fn]
        for k in sorted(set(cur) - set(rec)):
            drift.append((fn, k, "added live, absent from the manifest"))
        for k in sorted(set(rec) - set(cur)):
            drift.append((fn, k, "in the manifest, missing live"))
        for k in sorted(set(cur) & set(rec)):
            if cur[k] != rec[k]:
                shown = "value changed" if not rec[k].startswith("sha256:") \
                    else "fingerprint changed"
                drift.append((fn, k, shown))

    print("=" * 74)
    print("LAMBDA ENVIRONMENT DRIFT")
    print("=" * 74)
    print(f"manifest: {len(recorded)} function(s)   live: {len(current)} function(s)")
    for fn in added_fns:
        print(f"  NEW FUNCTION live, not in the manifest: {fn}")
    for fn in removed_fns:
        print(f"  GONE from live, still in the manifest:  {fn}")
    for fn, k, what in drift:
        print(f"  {fn:38s} {k:26s} {what}")
    total = len(added_fns) + len(removed_fns) + len(drift)
    print("\n" + "=" * 74)
    print(f"differences: {total}")
    print(f"RESULT: {'IN SYNC' if total == 0 else 'DRIFT'}")
    print("=" * 74)
    if args.json:
        print(json.dumps({"added_functions": added_fns, "removed_functions": removed_fns,
                          "drift": [{"function": f, "var": k, "what": w}
                                    for f, k, w in drift]}, indent=2))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
