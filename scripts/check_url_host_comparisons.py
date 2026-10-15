#!/usr/bin/env python3
"""Reject hostname checks implemented as raw string substring tests.

URL security decisions must parse the URL and compare its hostname exactly.
A check such as url.includes("example.com") also accepts attacker-example.com or
example.com.attacker.test, which CodeQL reports as incomplete sanitization.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOTS = ("src", "tools", "scripts", "public")
SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
DOMAIN_SUBSTRING = re.compile(
    r"""\.(?:includes|indexOf)\s*\(\s*(['"])(?P<value>[^'"]*\.[a-zA-Z]{2,}(?:[/:][^'"]*)?)\1"""
)

violations: list[str] = []
for root_name in ROOTS:
    root = pathlib.Path(root_name)
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(source.splitlines(), 1):
            match = DOMAIN_SUBSTRING.search(line)
            if not match:
                continue
            violations.append(
                f"{path}:{line_no}: raw substring hostname check for {match.group('value')!r}; "
                "parse the URL and compare hostname exactly"
            )

if violations:
    print("Unsafe URL-host substring checks found:", file=sys.stderr)
    for item in violations:
        print(f"  {item}", file=sys.stderr)
    sys.exit(1)

print("URL host comparison guard passed.")
