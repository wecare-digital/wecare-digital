#!/usr/bin/env python3
"""Assert that no real credential material sits in the files this change added.

Synthetic fillers and AWS's public documentation example key are assembled at
runtime rather than written literally, so this file does not trip the
block-inline-secrets hook it sits alongside.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    "scripts/block_inline_secrets.py",
    "scripts/verify_secret_hook.py",
    "scripts/verify_no_secrets_in_tree.py",
    ".kiro/hooks/block-inline-secrets.json",
    "docs/CREDENTIAL-ROTATION-RUNBOOK.md",
]

# Long-tailed, issuer-anchored shapes only, so prose like `rzp_live_...` in docs
# does not register.
DETECTORS = {
    "razorpay live": re.compile(r"rzp_live_[A-Za-z0-9]{8,}"),
    "openai":        re.compile(r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{30,}"),
    "google":        re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    "aws key id":    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    "github":        re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "slack":         re.compile(r"xox[abprs]-[A-Za-z0-9\-]{20,}"),
}

# Known-benign: AWS's published example key, and runs of a single repeated
# character used as synthetic filler in the hook's own test cases.
AWS_DOC_EXAMPLE = "AKI" + "A" + "IOSFODNN7EXAMPLE"
FILLER = re.compile(r"(.)\1{19,}")


def benign(match: str) -> bool:
    return match == AWS_DOC_EXAMPLE or bool(FILLER.search(match))


def main() -> int:
    problems = 0
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"  MISSING  {rel}")
            problems += 1
            continue
        text = p.read_text(errors="replace")
        for label, rx in DETECTORS.items():
            for m in rx.findall(text):
                if benign(m):
                    continue
                print(f"  REAL-LOOKING {label} in {rel}: {m[:8]}…")
                problems += 1
        print(f"  ok  {rel}")

    if problems:
        print(f"\nFAIL: {problems} problem(s)")
        return 1
    print("\nPASS: no real credential material in any file added by this change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
