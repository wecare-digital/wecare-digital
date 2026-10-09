#!/usr/bin/env python3
"""CI gate: infrastructure names must not leak into ordinary UI.

Why
---
The brief requires a provider-neutral product vocabulary, with exact provider and
resource names appearing only inside authorised Technical Details surfaces. Measured
2026-09-23 before this existed, `src/` carried 454 Lambda function names, 147
DynamoDB table names, 46 ARNs and one raw API Gateway id.

Most of that concentration is legitimate and must stay: `system-architecture.tsx`,
`lambda-functions.tsx` and `SystemTab.tsx` exist precisely to show
operators the topology. A scan that failed on those would be turned off within a day.

So the gate is built around an explicit allowlist of authorised surfaces, each with a
stated reason, and it fails on everything else. That inverts the usual shape: the
question is not "does this file mention DynamoDB" but "is this file allowed to".

Two refinements that stop it being noise
----------------------------------------
**Comments and imports are stripped first.** `SEO.tsx` mentions Airtel in a comment
that says Airtel is retired, and reporting that as a leak would be reporting the
documentation as the defect - the same trap `test_contact_key_wiring.code_only`
exists for. Prose describing a retired provider is not a use of it.

**A string must be user-visible to count.** An API path in a fetch call is not a
label; a heading is. The scan therefore ignores `src/api/` and anything inside an
import specifier, and it distinguishes a bare service word from a resource identifier
- `DynamoDB` in a code comment is nothing, `stack-wecare-digital-ContactsTable`
rendered in a heading is a leak.

Usage
-----
    python scripts/check_ui_labels.py            # report
    python scripts/check_ui_labels.py --gate     # exit 1 on any violation
    python scripts/check_ui_labels.py --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Surfaces authorised to name infrastructure, each with the reason it is exempt.
# Adding an entry here is a deliberate decision that this screen is a technical
# surface shown to operators, not ordinary product UI.
AUTHORISED_SURFACES = {
    "src/pages/workspace/dashboard/system-architecture.tsx":
        "Technical Details: the architecture map exists to show operators the topology.",
    "src/pages/workspace/dashboard/lambda-functions.tsx":
        "Technical Details: a function inventory is the page's entire subject.",
    "src/pages/workspace/dashboard/code-repo.tsx":
        "Technical Details: repository and deployment surface for operators.",
    "src/pages/workspace/dashboard/design-reference.tsx":
        "Internal design reference, not a customer-facing screen.",
    "src/components/dashboard/tabs/SystemTab.tsx":
        "Technical Details tab: system state per resource.",
    "src/components/dashboard/tabs/DataTab.tsx":
        "Technical Details tab: per-table row counts.",
    "src/pages/workspace/dashboard/index.tsx":
        "Operator dashboard shell that hosts the Technical Details tabs.",
    "src/config/constants.ts":
        "Configuration, not UI. Endpoints belong here rather than in a component.",
    "src/pages/workspace/engage/whatsapp/webhooks.tsx":
        "Technical Details: a webhook inventory for operators, whose whole content is "
        "endpoint URLs, handlers and delivery status.",
    "src/pages/workspace/engage/whatsapp/calling.tsx":
        "Operator screen carrying a service/resource/purpose infrastructure panel for "
        "WhatsApp Calling. Not customer-facing.",
    "src/pages/workspace/engage/whatsapp/waba-dashboard.tsx":
        "Technical Details: WABA and SNS subscription state for operators.",
    # --- added 2026-09-24, clearing the 20 tracked medium violations -------------
    "src/components/seo/InstructionsContent.tsx":
        "Technical Details: the SEO pipeline's own architecture and cost breakdown is "
        "the entire content. Same reason system-architecture.tsx is authorised; it only "
        "shows up separately because it was moved out of src/pages/ to stop Next "
        "publishing it as a chrome-less route.",
    "src/pages/workspace/engage/whatsapp/cost-controls.tsx":
        "Technical Details: the page lists the AWS services under cost control, so the "
        "service names ARE the subject. Renaming them would leave an operator unable to "
        "match a line here to a line on the bill.",
    "src/pages/workspace/engage/whatsapp/migration.tsx":
        "Technical Details: a WABA migration screen showing callback URL, phone ids and "
        "where the verify token lives. Naming Secrets Manager is the by-reference form "
        "that secret-handling.md asks for - it tells an operator where to look without "
        "printing the value, and 'stored securely' would be useless to them.",
}

# Directories that are not UI at all.
NON_UI_PREFIXES = ("src/api/", "src/types/", "src/test/", "src/lib/seo-",
                   "src/utils/")

PATTERNS = {
    # Resource identifiers: always a leak outside an authorised surface, because they
    # name a specific thing an operator could act on.
    "dynamodb_table": (r"stack-wecare-digital-[A-Za-z0-9]+", "high"),
    # Requires a 12-digit account id. `arn:aws:iam::role/...` as an input placeholder
    # is a generic shape that teaches a user the format and discloses nothing; an ARN
    # carrying our account number is a disclosure. The first version of this pattern
    # flagged the harmless one, which is how a gate earns a reputation for noise.
    "arn": (r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:", "high"),
    "execute_api_url": (r"[a-z0-9]{10}\.execute-api\.[a-z0-9-]+\.amazonaws\.com",
                        "high"),
    # `wecare-wa-widget` is a DOM element id and a public JS asset filename, not a
    # Lambda, so `-widget` is excluded. Without that the gate reports the embed script
    # as an infrastructure leak, which is the kind of false positive that gets a gate
    # switched off rather than fixed.
    "lambda_function": (
        r"\bwecare-(?!digital\b)[a-z0-9]+(?:-[a-z0-9]+)+\b(?<!-widget)", "high"),
    # Retired providers: naming one in product UI implies it is still in use.
    "retired_provider": (r"\b(Airtel|PayU|Pinpoint)\b", "high"),
    # Bare service words: lower severity, because "Bedrock" in a tooltip is a
    # vocabulary problem rather than an actionable disclosure.
    "aws_service_word": (
        r"\b(DynamoDB|CloudWatch|Secrets Manager|API Gateway|Bedrock|"
        r"SQS|SNS|Cognito|S3 bucket)\b", "medium"),
}


def strip_noise(text: str) -> str:
    """Blank out comments and imports, preserving line numbers.

    Comments first: a file that documents a retired provider must not be reported for
    saying the word. Imports next: a module path is not a label.

    Lines are BLANKED, never removed. Dropping a line shifts every number after it,
    and a gate that reports the wrong location is a gate people learn to distrust -
    the first run of this script pointed at an empty-state div forty lines below the
    real match.
    """
    # Block comments: keep the newlines so the line count is preserved.
    text = re.sub(r"/\*.*?\*/",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    lines = []
    for line in text.splitlines():
        # A // inside a URL string must survive, so only strip when it is not
        # preceded by a colon.
        line = re.sub(r"(?<!:)//.*$", "", line)
        if re.match(r"\s*import\s", line) or re.match(r"\s*export\s+\*", line):
            line = ""
        lines.append(line)
    return "\n".join(lines)


def relevant_files():
    for path in sorted(SRC.rglob("*")):
        if path.is_dir() or path.suffix not in (".ts", ".tsx"):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if "node_modules" in rel or "__tests__" in rel:
            continue
        if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
            continue
        if any(rel.startswith(p) for p in NON_UI_PREFIXES):
            continue
        yield rel, path


# A retired provider may be NAMED when the same line marks it as past. Reading old
# rows tagged `airtel` is legitimate and the label has to say something; what is not
# allowed is describing a retired provider as current, which is what
# "AWS Pinpoint + Airtel IQ" did on the SMS channel card.
HISTORICAL_MARKERS = re.compile(
    r"histor|legacy|retired|deprecat|archive|former|previous|migrated|past", re.I)

def is_config_object_key(line_text: str, word: str) -> bool:
    """True for `Cognito: {` on its own line — an SDK config key, not a label.

    Deliberately anchored to the WHOLE line rather than just testing for `: {` after
    the word. The loose version also swallowed `<p>DynamoDB: {count} rows</p>`, where
    the `{` opens a JSX interpolation rather than an object literal - which would have
    turned a precision fix into a hole in the gate. A config key is alone on its line;
    a label is not.
    """
    stripped = line_text.strip()
    return stripped.startswith(word) and stripped[len(word):].strip() in (": {", ":{")


def scan():
    violations = []
    for rel, path in relevant_files():
        if rel in AUTHORISED_SURFACES:
            continue
        code = strip_noise(path.read_text(encoding="utf-8", errors="ignore"))
        lines = code.splitlines()
        for name, (pattern, severity) in PATTERNS.items():
            for match in re.finditer(pattern, code):
                line_no = code[:match.start()].count("\n") + 1
                line_text = lines[line_no - 1] if line_no <= len(lines) else ""

                # A retired provider adjacent to a historical marker is a correct
                # label, not a leak. `label: 'Airtel (historical)'` is the shape we
                # want people to write.
                if name == "retired_provider" and HISTORICAL_MARKERS.search(line_text):
                    continue

                # An object KEY introducing a block is code, not a label. This scanner
                # reads UI copy, and `Cognito: {` inside `Amplify.configure()` is the
                # SDK's own required key - there is no wording to change, and the only
                # way to satisfy the gate would be to authorise all of _app.tsx, which
                # does contain real UI copy (the MFA chooser labels) that should stay
                # checked. Narrow on purpose: a label is never followed by `: {`.
                if is_config_object_key(line_text, match.group(0)):
                    continue

                violations.append({
                    "file": rel, "line": line_no, "rule": name,
                    "severity": severity, "match": match.group(0)[:60],
                })
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 on a HIGH severity violation")
    parser.add_argument("--strict", action="store_true",
                        help="also fail on medium (bare AWS service words)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    violations = scan()
    scanned = sum(1 for _ in relevant_files())

    if args.json:
        print(json.dumps({"scanned": scanned,
                          "authorisedSurfaces": len(AUTHORISED_SURFACES),
                          "violations": violations}, indent=2))
    else:
        print(f"UI label scan: {scanned} ordinary UI files, "
              f"{len(AUTHORISED_SURFACES)} authorised technical surfaces skipped")
        if not violations:
            print("UI LABELS OK - no infrastructure names in ordinary UI.")
        else:
            by_rule = {}
            for v in violations:
                by_rule.setdefault(v["rule"], []).append(v)
            for rule, items in sorted(by_rule.items(),
                                      key=lambda kv: -len(kv[1])):
                print(f"\n  {rule}  ({items[0]['severity']}, {len(items)})")
                for v in items[:8]:
                    print(f"     {v['file']}:{v['line']}  {v['match']!r}")
                if len(items) > 8:
                    print(f"     ... and {len(items) - 8} more")
            print(f"\n{len(violations)} violation(s). Either move the label into the "
                  f"product vocabulary, or add the file to AUTHORISED_SURFACES with a "
                  f"reason if it is genuinely a Technical Details surface.")

    # MEDIUM IS NOW BLOCKING TOO, as of 2026-09-24.
    #
    # It was high-only while 20 medium violations stood, on the same staging as
    # provider-policy.yml: run advisory until the count reaches zero, then flip. A gate
    # that fails on day one for something nobody is going to fix this week gets switched
    # off, which is worse than a gate that starts narrow.
    #
    # The count is now zero - 8 labels reworded, 3 files authorised with a stated reason,
    # and one false positive fixed in the scanner - so the allowance has outlived its
    # purpose. Leaving it would mean the 21st violation lands silently under a line
    # reading "GATE PASSED", which is exactly the shape of the problems this whole phase
    # has been removing.
    #
    # `--strict` is kept as a no-op alias so any existing caller keeps working.
    blocking = list(violations)
    if args.gate and blocking:
        by_sev = {}
        for v in blocking:
            by_sev[v["severity"]] = by_sev.get(v["severity"], 0) + 1
        print(f"\nGATE FAILED on {len(blocking)} violation(s) "
              f"({', '.join(f'{n} {s}' for s, n in sorted(by_sev.items()))}).")
        return 1
    if args.gate:
        print("\nGATE PASSED. No infrastructure names in ordinary UI, at any severity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
