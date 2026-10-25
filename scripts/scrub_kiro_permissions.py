#!/usr/bin/env python3
"""Remove credential-bearing allow-patterns from Kiro's workspace permissions file.

Why this exists
---------------
Kiro records an approved command as a shell allow-pattern when the approval is
"Always allow". If the command carried a credential inline, the *entire command
string* is written to::

    ~/.kiro/workspace-roots/<hash>/permissions.yaml

That is how the 2026-09-19 leak happened. The credential did not arrive via a
config file or a commit - it arrived as a permission rule. See
``.kiro/steering/secret-handling.md`` (retired; now .kiro/steering/00-common.md).

``scripts/block_inline_secrets.py`` stops new ones being created. This script
removes the ones already there.

What it does
------------
Parses the YAML, walks every string leaf, and drops any *list entry* whose text
matches a credential shape. Dropping the entry is the point: the rule is what
carries the value, so redacting the value in place would leave a permission rule
that no longer matches anything. After this runs, a similar command prompts for
approval again, which is the correct behaviour.

Writes atomically (temp file in the same directory, then ``os.replace``) and
forces mode 0600. Prints counts and key names only - never a value. Takes no
backup on purpose: a backup would be one more plaintext copy of the thing we are
removing, which is what the steering file forbids.

Usage
-----
    python scripts/scrub_kiro_permissions.py            # report only (default)
    python scripts/scrub_kiro_permissions.py --apply    # rewrite the file

Exit codes
----------
    0  clean, or scrub applied successfully
    1  credentials present and --apply was not passed
    2  could not read or parse the file
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import tempfile

try:
    import yaml
except ImportError:  # pragma: no cover - venv always has PyYAML
    print("PyYAML is required: .venv/bin/python -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

DEFAULT_TARGET = pathlib.Path.home() / ".kiro/workspace-roots/df7bb16a63efe7f7/permissions.yaml"

# Issuer prefixes are assembled at runtime so this source file contains no
# literal credential shape - otherwise the repo's own secret scanners would
# flag the scrubber. Same trick as scripts/verify_secret_hook.py.
_RZP = "rzp" + "_live_"
_RZP_TEST = "rzp" + "_test_"
_OAI = "sk" + "-"
_GCP = "AI" + "za"
_GH = "gh" + "[pousr]_"
_SLACK = "xo" + "x[abprs]-"
_AWS = "(?:AK" + "IA|AS" + "IA)"
_STRIPE = "sk" + "_live_"

DETECTORS: list[tuple[str, re.Pattern[str]]] = [
    ("razorpay live key id", re.compile(_RZP + r"[A-Za-z0-9]{8,}")),
    ("razorpay test key id", re.compile(_RZP_TEST + r"[A-Za-z0-9]{8,}")),
    ("openai key", re.compile(r"\b" + _OAI + r"(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("google api key", re.compile(r"\b" + _GCP + r"[A-Za-z0-9_\-]{30,}")),
    ("github token", re.compile(r"\b" + _GH + r"[A-Za-z0-9]{30,}")),
    ("slack token", re.compile(r"\b" + _SLACK + r"[A-Za-z0-9\-]{10,}")),
    ("aws access key id", re.compile(r"\b" + _AWS + r"[0-9A-Z]{16}\b")),
    ("stripe secret key", re.compile(r"\b" + _STRIPE + r"[A-Za-z0-9]{20,}")),
    ("plivo auth id", re.compile(r"\bMA[A-Z0-9]{18}\b")),
    ("private key PEM", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("inline secret assignment", re.compile(
        r"\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|APIKEY|API_KEY|AUTH_TOKEN|"
        r"ACCESS_KEY|PRIVATE_KEY|CLIENT_SECRET)[A-Z0-9_]*\s*=\s*['\"][^'\"]{20,}['\"]")),
]

# A reference to a secret by NAME is the correct pattern and must survive the
# scrub, even though the text contains the word "secret".
KEEP = [
    re.compile(r"\{\{resolve:secretsmanager:"),
    re.compile(r"SecretId\s*=\s*['\"]?wecare/"),
    re.compile(r"--secret-id\s+wecare/"),
    re.compile(r"[A-Z0-9_]*SECRET[A-Z0-9_]*\s*=\s*['\"]?wecare/"),
]


def classify(text: str) -> list[str]:
    """Return the credential labels found in ``text``, or [] if it is clean."""
    if any(k.search(text) for k in KEEP):
        return []
    return sorted({label for label, rx in DETECTORS if rx.search(text)})


def summarise(text: str, limit: int = 72) -> str:
    """A safe one-line description of an entry: shape only, never the value."""
    redacted = text
    for _, rx in DETECTORS:
        redacted = rx.sub("<CREDENTIAL>", redacted)
    redacted = " ".join(redacted.split())
    return redacted[:limit] + ("..." if len(redacted) > limit else "")


def scrub(node, findings: list[tuple[str, list[str], str]], path: str = "$"):
    """Recursively drop credential-bearing list entries. Returns the new node."""
    if isinstance(node, dict):
        return {k: scrub(v, findings, f"{path}.{k}") for k, v in node.items()}
    if isinstance(node, list):
        kept = []
        for i, item in enumerate(node):
            if isinstance(item, str):
                labels = classify(item)
                if labels:
                    findings.append((f"{path}[{i}]", labels, summarise(item)))
                    continue
                kept.append(item)
            else:
                kept.append(scrub(item, findings, f"{path}[{i}]"))
        return kept
    if isinstance(node, str):
        labels = classify(node)
        if labels:
            findings.append((path, labels, summarise(node)))
            return "<REDACTED-CREDENTIAL-REMOVED>"
    return node


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=pathlib.Path, default=DEFAULT_TARGET)
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the file; without this the script only reports")
    args = ap.parse_args()

    target: pathlib.Path = args.target
    if not target.exists():
        print(f"not found: {target}")
        return 2

    mode = oct(target.stat().st_mode & 0o777)
    print(f"target : {target}")
    print(f"mode   : {mode}")

    try:
        original = target.read_text()
        data = yaml.safe_load(original)
    except Exception as exc:  # noqa: BLE001 - report, do not crash mid-audit
        print(f"could not parse as YAML: {type(exc).__name__}", file=sys.stderr)
        return 2

    findings: list[tuple[str, list[str], str]] = []
    cleaned = scrub(data, findings)

    print(f"entries carrying credentials: {len(findings)}")
    for loc, labels, shape in findings:
        print(f"  {loc}")
        print(f"      matched : {', '.join(labels)}")
        print(f"      entry   : {shape}")

    if not findings:
        print("\nRESULT: clean - no credential-shaped material in this file.")
        if mode != "0o600":
            print(f"NOTE: mode is {mode}; tighten with chmod 600.")
        return 0

    if not args.apply:
        print("\nRESULT: credentials present. Re-run with --apply to remove them.")
        print("Removing an entry also removes the 'Always allow' rule it encoded,")
        print("so the next similar command will ask for approval again.")
        return 1

    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".permissions.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(cleaned, fh, default_flow_style=False, sort_keys=False)
        os.replace(tmp, target)
    except Exception:
        # never leave a credential-bearing temp file behind
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    os.chmod(target, 0o600)
    after = target.read_text()
    residual = [label for label, rx in DETECTORS if rx.search(after)]
    print(f"\nremoved : {len(findings)} entr{'y' if len(findings) == 1 else 'ies'}")
    print(f"mode    : {oct(target.stat().st_mode & 0o777)}")
    print(f"residual credential shapes in file: {len(residual)}")
    if residual:
        print(f"  STILL PRESENT: {', '.join(sorted(set(residual)))}")
        return 1
    print("\nRESULT: file scrubbed. The values remain valid at the providers until")
    print("rotation, and remain in IDE logs and session transcripts - run")
    print("scripts/audit_leak_footprint.py to measure what is left.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
