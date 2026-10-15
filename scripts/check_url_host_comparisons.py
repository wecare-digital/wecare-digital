#!/usr/bin/env python3
"""Guard VayuLok tests against unsafe raw hostname substring checks.

Use requestUrl(...).hostname === "host" (or equivalent exact parsed-host comparison), never
String(url).includes("host"). The latter also accepts attacker-host.example and CodeQL flags it.
"""

from __future__ import annotations

import pathlib
import re
import sys

TARGET = pathlib.Path("src/test/VayuLokLive.test.tsx")
DOMAIN_SUBSTRING = re.compile(
    r"""\.(?:includes|indexOf)\s*\(\s*(['"])(?P<value>[^'"]*\.[a-zA-Z]{2,}(?:[/:][^'"]*)?)\1"""
)

source = TARGET.read_text(encoding="utf-8")
violations: list[str] = []
for line_no, line in enumerate(source.splitlines(), 1):
    match = DOMAIN_SUBSTRING.search(line)
    if match:
        violations.append(
            f"{TARGET}:{line_no}: raw substring hostname check for {match.group('value')!r}; "
            "parse the URL and compare hostname exactly"
        )

if violations:
    print("Unsafe VayuLok URL-host substring checks found:", file=sys.stderr)
    for item in violations:
        print(f"  {item}", file=sys.stderr)
    sys.exit(1)

print("VayuLok URL host comparison guard passed.")
