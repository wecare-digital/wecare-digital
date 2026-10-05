#!/usr/bin/env python3
"""Assert the exported site does not publish a server-side credential.

WHY THIS EXISTS
---------------
`next.config.js` uses ``output: 'export'``, so every ``NEXT_PUBLIC_*`` value is
inlined into a JS chunk under ``out/_next/static/chunks/`` at build time and
served to every visitor. That is fine for a Maps *browser* key, which Google's own
model treats as public and restricts by HTTP referrer. It is a disclosure for any
key that also authorizes server-side APIs.

Those two cases are indistinguishable by variable name alone, and this repo has a
specific trap: ``docs/provider-inventory.md`` records that `wecare/google/cloud`,
`wecare/google-api-key` and `wecare/google-maps` **all hold the same unified key**,
fingerprint ``sha256:0bd4beb6496a``. `wecare-whatsapp-templates` reads it
server-side for the Places proxy, under a comment saying it is "never exposed to
the browser". Pasting that one value into ``NEXT_PUBLIC_GOOGLE_MAPS_KEY`` would
publish the credential that authorizes Places, Geocoding and PageSpeed to every
visitor - and it is already one of the four historically exposed credentials
awaiting rotation (``.kiro/steering/secret-handling.md``).

`scripts/verify_no_secrets_in_tree.py` does not cover this: it scans a fixed list
of six source files and never looks at build output.

HOW IT DECIDES, WITHOUT EVER READING A SECRET
---------------------------------------------
Fingerprints are compared, never values. The unified key's fingerprint is already
committed in ``docs/provider-inventory.md``, so this check needs no Secrets Manager
read - which is prohibited anyway (``.kiro/steering/aws-agent-rules.md``).

  * A Google key whose fingerprint matches a known SERVER-SIDE key  -> FAIL.
  * Any other Google key                                            -> allowed,
    reported with its fingerprint. A browser key is public by design; this check
    deliberately does not pretend otherwise.
  * Any other issuer shape (Razorpay live, OpenAI, AWS, GitHub, Slack, Stripe
    live, PEM private key) -> FAIL. None of those has a legitimate reason to be
    in a browser bundle, so there is no fingerprint exception for them.

Values are never printed. Findings are reported as file + fingerprint + length,
the metadata set sanctioned by ``.kiro/steering/plaintext-source-policy.md``.

WHERE THIS HAS TO RUN, AND WHY CI IS NOT ENOUGH
-----------------------------------------------
Scanning ``out/`` only catches the key if the build that produced ``out/`` had the
variable set. GitHub Actions does **not** set ``NEXT_PUBLIC_GOOGLE_MAPS_KEY``, so
the CI copy of this check scans an export that never contained a key and passes
trivially. The build that matters is **Amplify's**, because that is where the
branch environment variables exist.

So this check is wired in three places, deliberately:

  1. ``amplify.yml`` build phase - the real gate. Runs inside the Amplify build,
     after ``npm run build``, where the variable is present. Fails the build
     before anything is deployed.
  2. ``.github/workflows/build-test.yml`` - a weak backstop. It cannot see Amplify
     variables, so it only catches a credential committed into the source tree.
  3. ``--amplify-env`` - reads the Amplify branch variables over the API and
     fingerprints them, so the answer is available without waiting for a build.

Usage
-----
    python scripts/verify_public_bundle_secrets.py            # scans out/
    python scripts/verify_public_bundle_secrets.py --dir out
    python scripts/verify_public_bundle_secrets.py --amplify-env
    python scripts/verify_public_bundle_secrets.py --list-fingerprints

Exit codes: 0 clean, 1 a forbidden credential is present, 2 nothing to scan
(a missing export is a setup error, not a pass - see the note in main()).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Matches scripts/env_manifest.py:fp() and the other fingerprint helpers in
# scripts/, so a value fingerprinted here is comparable with one fingerprinted
# there. Do not change the digest or the truncation independently of those.
def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


# Server-side keys that must never appear in the export. Fingerprints only - these
# are one-way, so this list discloses nothing. Add a key here when it is known to
# lack browser restrictions.
#
# CORRECTED 2026-09-25, and the correction matters more than the original entry.
# `0bd4beb6496a` - the unified Google key - was listed here on the assumption that
# it was a server-side credential. It is not. Measured against the live project:
#
#     gcloud services api-keys list --project=wecaredigitalbw
#     -> ONE key, "WECARE Unified Google API Key", with
#        browserKeyRestrictions.allowedReferrers =
#          https://wecare.digital/*, https://*.wecare.digital/*
#
# It is a BROWSER key, already restricted to exactly the referrers this repo's own
# .env.local.example asks for. A referrer-restricted browser key is public by
# Google's design, so publishing it in a chunk is legitimate and blocking it here
# would have failed the Amplify build on the CORRECT action.
#
# The same measurement found the real defect, in the opposite direction: the key
# cannot be used server-side at all. `scripts/check_secrets_live.py` gets
# `REQUEST_DENIED: API keys with referer restrictions cannot be used with this API`
# for fingerprint sha256:0bd4beb6 on both `wecare/google-api-key` and
# `wecare/google/cloud`. So `whatsapp-templates`' Places proxy and
# `site-language`'s Translate call are the things that are broken - not the
# browser path.
#
# The invariant worth enforcing is therefore NOT "this fingerprint must not ship".
# It is "anything published must be browser-restricted", which cannot be decided
# from the bundle alone - matching a bundle fingerprint back to a GCP key would
# require reading key strings. So a Google key found in the export is REPORTED with
# its fingerprint, and the restriction check belongs in the Cloud console review
# recorded in docs/CREDENTIAL-ROTATION-RUNBOOK.md.
FORBIDDEN_FINGERPRINTS: dict[str, str] = {
    # Populate when a key is known to lack browser restrictions - e.g. the
    # IP-restricted server key that the Places proxy and Translate need, once it
    # exists. That one genuinely must never reach the export.
    #
    # PLACEHOLDER SLOT - WECARE Server Google API Key. TODO: paste the entry here
    # the first time `python scripts/provision_maps_server_key.py --create` runs.
    #
    # That key is minted with NO application restriction, deliberately: Lambda has no
    # stable egress IP to allowlist, so the compensating control is a narrow apiTargets
    # list plus Secrets Manager. A key with no application restriction is usable by
    # anyone who holds it, so unlike the referrer-restricted browser key it must never
    # be inlined into a public JS chunk - which is exactly the case this dict exists to
    # fail the build on, and exactly the key it has never yet been taught.
    #
    # NO VALUE IS INVENTED HERE. The key does not exist yet, so its fingerprint is
    # unknowable; a made-up hex string would be a gate that can never match. --create,
    # --verify, --status and --store-from-stdin each print the exact dict entry to
    # paste, in the bare 12-hex form fingerprint() compares against.
    #
    #     "<12 hex>": (
    #         "WECARE Server Google API Key - no application restriction, so it is"
    #         " usable by anyone who holds it and must never reach the export."
    #     ),
}

# Issuer-anchored and long-tailed, so prose and placeholders do not register.
# `google` is handled separately because it is the one shape with a legitimate
# public form.
GOOGLE = re.compile(r"AIza[A-Za-z0-9_\-]{30,}")

NEVER_PUBLIC = {
    "razorpay live":    re.compile(r"rzp_live_[A-Za-z0-9]{8,}"),
    "openai":           re.compile(r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{30,}"),
    "aws access key":   re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    "github":           re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "slack":            re.compile(r"xox[abprs]-[A-Za-z0-9\-]{20,}"),
    "stripe live":      re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    "pem private key":  re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
}

# AWS's published documentation example, and runs of one repeated character used
# as synthetic filler in this repo's own hook tests.
AWS_DOC_EXAMPLE = "AKI" + "A" + "IOSFODNN7EXAMPLE"
FILLER = re.compile(r"(.)\1{19,}")

# Text-ish payloads only. Fonts, images and source maps of binary assets cannot
# carry a credential that a browser would read as configuration, and scanning
# them makes the check slow enough that someone will switch it off.
SCAN_SUFFIXES = {".js", ".mjs", ".cjs", ".json", ".html", ".css", ".txt", ".xml", ".map"}


def benign(match: str) -> bool:
    return match == AWS_DOC_EXAMPLE or bool(FILLER.search(match))


def scan_file(path: Path, rel: str) -> tuple[list[dict], list[dict]]:
    """Return (failures, allowed_google_keys) for one file."""
    failures: list[dict] = []
    allowed: list[dict] = []
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        # Unreadable file in the export is itself worth surfacing, but it is a
        # build problem rather than a credential problem.
        print(f"  WARN  could not read {rel}: {type(exc).__name__}")
        return failures, allowed

    for label, rx in NEVER_PUBLIC.items():
        for m in rx.findall(text):
            if benign(m):
                continue
            failures.append({
                "file": rel, "kind": label,
                "fingerprint": fingerprint(m), "length": len(m),
                "why": f"{label} credentials have no legitimate public form",
            })

    for m in GOOGLE.findall(text):
        if benign(m):
            continue
        fp = fingerprint(m)
        if fp in FORBIDDEN_FINGERPRINTS:
            failures.append({
                "file": rel, "kind": "google (server-side)",
                "fingerprint": fp, "length": len(m),
                "why": FORBIDDEN_FINGERPRINTS[fp],
            })
        else:
            allowed.append({"file": rel, "fingerprint": fp, "length": len(m)})

    return failures, allowed


APP_ID = "d22dm4b0jn71jw"
BRANCH = "stack"


def check_amplify_env() -> int:
    """Fingerprint the Amplify branch environment variables.

    Catches the mistake at the point it is actually made - someone pasting a value
    into the Amplify console - rather than one build later. Values are never
    printed or returned; only a fingerprint comparison happens, and the
    fingerprints it compares against are already public in the docs.

    Every ``NEXT_PUBLIC_*`` variable is inlined into the client bundle by
    ``output: 'export'``, so a forbidden value in any of them is published. A
    non-public variable is reported separately: still wrong to keep in Amplify,
    but not served to visitors.
    """
    try:
        import boto3
    except ImportError:
        print("boto3 unavailable; --amplify-env needs it")
        return 2

    client = boto3.client("amplify", region_name="us-east-1")
    env = client.get_branch(appId=APP_ID, branchName=BRANCH)["branch"].get(
        "environmentVariables", {}) or {}

    published, private = [], []
    for name, value in sorted(env.items()):
        fp = fingerprint((value or "").strip())
        if fp in FORBIDDEN_FINGERPRINTS:
            (published if name.startswith("NEXT_PUBLIC_") else private).append(
                {"name": name, "fingerprint": fp, "why": FORBIDDEN_FINGERPRINTS[fp]})

    print(f"Amplify app {APP_ID} branch {BRANCH}: {len(env)} environment variable(s)")
    print(f"  NEXT_PUBLIC_* (inlined into the public bundle): "
          f"{sum(1 for k in env if k.startswith('NEXT_PUBLIC_'))}")

    if not published and not private:
        print("\nPASS: no Amplify variable holds a known server-side credential")
        return 0

    for row in published:
        print(f"\nFAIL {row['name']} is NEXT_PUBLIC_* and holds a server-side credential")
        print(f"  fingerprint sha256:{row['fingerprint']}")
        print(f"  why         {row['why']}")
        print("  This value is inlined into a JS chunk and served to every visitor.")
    for row in private:
        print(f"\nFAIL {row['name']} holds a server-side credential")
        print(f"  fingerprint sha256:{row['fingerprint']}")
        print(f"  why         {row['why']}")
        print("  Not NEXT_PUBLIC_, so not published - but it belongs in Secrets Manager.")
    print("\nThe value is NOT printed. Replace it; do not echo it to confirm.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="out",
                    help="directory to scan, relative to the repo root (default: out)")
    ap.add_argument("--amplify-env", action="store_true",
                    help="fingerprint the live Amplify branch environment variables")
    ap.add_argument("--list-fingerprints", action="store_true",
                    help="print the forbidden fingerprints and exit")
    args = ap.parse_args()

    if args.amplify_env:
        return check_amplify_env()

    if args.list_fingerprints:
        print("Server-side key fingerprints that must never reach the export:\n")
        for fp, why in FORBIDDEN_FINGERPRINTS.items():
            print(f"  sha256:{fp}\n    {why}\n")
        return 0

    target = ROOT / args.dir
    if not target.is_dir():
        # Deliberately NOT exit 0. A gate that silently passes when the thing it
        # inspects is absent is the failure mode this repo has already been bitten
        # by (see the header of scripts/snapstart_publish.py).
        print(f"NOTHING TO SCAN: {args.dir}/ does not exist. Run `npm run build` first.")
        return 2

    files = [p for p in target.rglob("*")
             if p.is_file() and p.suffix.lower() in SCAN_SUFFIXES]

    failures: list[dict] = []
    allowed: list[dict] = []
    for p in files:
        f, a = scan_file(p, str(p.relative_to(ROOT)))
        failures += f
        allowed += a

    print(f"scanned {len(files)} text files under {args.dir}/")

    if allowed:
        # Grouped by fingerprint: one key inlined into one chunk is the expected
        # shape, and the count matters more than the file list.
        by_fp: dict[str, list[str]] = {}
        for a in allowed:
            by_fp.setdefault(a["fingerprint"], []).append(a["file"])
        print("\nPublic Google keys present (allowed - a browser key is public by design):")
        for fp, fs in by_fp.items():
            print(f"  sha256:{fp}  in {len(fs)} file(s): {', '.join(sorted(set(fs))[:3])}")
        print("  This check CANNOT confirm the key is referrer-restricted - that would")
        print("  need the key string to match it back to a GCP key. Confirm out of band:")
        print("    gcloud services api-keys list --project=wecaredigitalbw")
        print("  Every published key needs browserKeyRestrictions.allowedReferrers set to")
        print("  wecare.digital/* AND *.wecare.digital/*, and its apiTargets narrowed to")
        print("  the Maps APIs the browser actually calls - a published key also carrying")
        print("  Vision, Translate, YouTube and Custom Search is a wide billing surface,")
        print("  because a Referer header is trivially forged.")

    if failures:
        print(f"\nFAIL: {len(failures)} forbidden credential occurrence(s) in the export\n")
        for f in failures:
            print(f"  {f['file']}")
            print(f"    kind        {f['kind']}")
            print(f"    fingerprint sha256:{f['fingerprint']}  (length {f['length']})")
            print(f"    why         {f['why']}")
        print("\nThe value is NOT printed. Do not echo it to find it - locate it by")
        print("fingerprint with scripts/env_manifest.py, remove it from the")
        print("NEXT_PUBLIC_* variable that carries it, and rebuild.")
        return 1

    print("\nPASS: the export publishes no server-side credential")
    return 0


if __name__ == "__main__":
    sys.exit(main())
