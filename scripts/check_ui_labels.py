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
**Comments and imports are stripped first.** A comment that records why a provider was
removed is documentation, and reporting it as a leak would be reporting the record of the
fix as the defect - the same trap `test_contact_key_wiring.code_only` exists for.

**A string must be user-visible to count.** An API path in a fetch call is not a
label; a heading is. The scan therefore ignores `src/api/` and anything inside an
import specifier, and it distinguishes a bare service word from a resource identifier
- `DynamoDB` in a code comment is nothing, `stack-wecare-digital-ContactsTable`
rendered in a heading is a leak.

Provider names are an allow-list
--------------------------------
A provider named on an ordinary screen must be one the platform actually uses, so the
names a screen may display come from `scripts/provider_allowlist.py` - the same
allow-list the source and live provider gates read. Three shapes put a provider name in
front of a user, and in each the name must be on that list:

    attribution     "via X", "powered by X", "provided by X" ...
    provider field  provider: 'X', providerName="X", carrier: 'X' ...
    provider lists  "X + Y" where one part is an approved provider, and the values of a
                    declaration named for providers (`const PROVIDER_LABELS = {...}`)

There is no list of names that must not appear and no exemption for a "historical"
label: a name that is not approved fails wherever it is shown, and data recorded under
a provider that is no longer used is displayed through the product vocabulary instead.

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
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import provider_allowlist  # noqa: E402

# Surfaces authorised to name infrastructure, each with the reason it is exempt.
# Adding an entry here is a deliberate decision that this screen is a technical
# surface shown to operators, not ordinary product UI.
AUTHORISED_SURFACES = {
    "src/components/workspace/platform/SystemArchitecture.tsx":
        "Technical Details: the architecture map exists to show operators the topology.",
    "src/components/workspace/platform/LambdaFunctions.tsx":
        "Technical Details: a function inventory is the page's entire subject.",
    "src/components/workspace/platform/CodeRepo.tsx":
        "Technical Details: repository and deployment surface for operators.",
    "src/components/workspace/platform/DesignReference.tsx":
        "Internal design reference, not a customer-facing screen.",
    "src/components/dashboard/tabs/SystemTab.tsx":
        "Technical Details tab: system state per resource.",
    "src/components/dashboard/tabs/DataTab.tsx":
        "Technical Details tab: per-table row counts.",
    "src/config/constants.ts":
        "Configuration, not UI. Endpoints belong here rather than in a component.",
    "src/components/workspace/whatsapp/webhooks.tsx":
        "Technical Details: a webhook inventory for operators, whose whole content is "
        "endpoint URLs, handlers and delivery status.",
    "src/components/workspace/whatsapp/calling.tsx":
        "Operator screen carrying a service/resource/purpose infrastructure panel for "
        "WhatsApp Calling. Not customer-facing.",
    "src/components/workspace/whatsapp/waba-dashboard.tsx":
        "Technical Details: WABA and SNS subscription state for operators.",
    # --- added 2026-09-24, clearing the 20 tracked medium violations -------------
    "src/components/seo/InstructionsContent.tsx":
        "Technical Details: the SEO pipeline's own architecture and cost breakdown is "
        "the entire content. Same reason system-architecture.tsx is authorised; it only "
        "shows up separately because it was moved out of src/pages/ to stop Next "
        "publishing it as a chrome-less route.",
    "src/components/workspace/whatsapp/cost-controls.tsx":
        "Technical Details: the page lists the AWS services under cost control, so the "
        "service names ARE the subject. Renaming them would leave an operator unable to "
        "match a line here to a line on the bill.",
    "src/components/workspace/whatsapp/migration.tsx":
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


# --------------------------------------------------------------------------------------
# Provider names: positive. A provider shown in ordinary UI must be on the allow-list.
# --------------------------------------------------------------------------------------
#: Display names a screen may use for a provider, plus product terms ("via SMS").
APPROVED_LABELS = provider_allowlist.ui_labels()
#: Provider identifiers a provider field may carry (`provider: 'meta-social'`).
APPROVED_IDS = provider_allowlist.provider_ids()
#: First words of approved provider labels. A joined list ("X + Y") is only a provider
#: list when one of its parts starts with one of these.
PROVIDER_WORDS = frozenset(label.split()[0] for p in provider_allowlist.PROVIDERS
                           for label in p.ui_labels)
#: Words that may follow an approved name without changing who it names.
GENERIC_TAIL = frozenset({"API", "APIs", "SDK", "Console", "Dashboard", "Integration",
                          "Account", "App", "Platform", "Webhook", "Webhooks"})
#: A capitalised determiner or pronoun opens ordinary prose, not a name.
NOT_A_NAME = frozenset({"a", "an", "the", "this", "that", "these", "those", "your", "our",
                        "their", "my", "his", "her", "its", "any", "all", "each", "every",
                        "no", "one", "some"})

_NAME = r"[A-Z][A-Za-z0-9]*(?:[.&-][A-Za-z0-9]+)*"
_PHRASE = _NAME + r"(?: " + _NAME + r")*"
ATTRIBUTION = re.compile(
    r"\b(?:via|powered by|provided by|carried by|delivered by|processed by|hosted by"
    r"|served by|operated by)\s+(" + _PHRASE + r")")
#: `provider: 'X'`, `provider="X"` or the JSX expression `provider={'X'}`. An object value
#: (`"provider": { "@id": ... }` in JSON-LD) is structure, not a name, and is not read.
PROVIDER_FIELD = re.compile(
    r"""\b(?:provider|providerName|providerLabel|carrier|vendor|gateway|poweredBy)['"]?\s*"""
    r"""(?:[:=]\s*(['"`])(?P<plain>[^'"`\n]{1,80})\1"""
    r"""|=\s*\{\s*(['"`])(?P<jsx>[^'"`\n]{1,80})\3\s*\})""")
#: A provider stack written as "X + Y". Only `+`: an ampersand or slash in a title joins
#: features ("Invoices & WhatsApp Pay"), not carriers.
JOINED = re.compile(r"(" + _PHRASE + r")((?:\s*\+\s*" + _PHRASE + r")+)")
PROVIDER_DECLARATION = re.compile(
    r"\b(?:const|let|var)\s+(\w*(?:provider|PROVIDER|Provider|carrier|CARRIER|Carrier"
    r"|vendor|VENDOR|Vendor|gateway|GATEWAY|Gateway)\w*)\s*(?::[^=\n]+)?=\s*([\[{])")


def approved_label(phrase: str) -> bool:
    """True when ``phrase`` names an approved provider or product term.

    Exact first; then with generic trailing words removed, so "Razorpay Integration" is
    Razorpay, while "AWS Acme" is not AWS: a product name AWS does not carry under that
    label is not approved by the word in front of it.
    """
    phrase = " ".join(phrase.split())
    if phrase in APPROVED_LABELS or phrase in APPROVED_IDS:
        return True
    words = phrase.split()
    while len(words) > 1 and words[-1] in GENERIC_TAIL:
        words.pop()
        if " ".join(words) in APPROVED_LABELS:
            return True
    return False


def _block(code: str, start: int, opener: str) -> str:
    """The bracketed literal starting at ``start`` (depth-counted)."""
    closer = "}" if opener == "{" else "]"
    depth = 0
    for i in range(start, min(len(code), start + 20000)):
        if code[i] == opener:
            depth += 1
        elif code[i] == closer:
            depth -= 1
            if depth == 0:
                return code[start:i + 1]
    return code[start:start + 20000]


def provider_name_findings(code: str):
    """(offset, rule, shown name) for every unapproved provider name in UI copy."""
    out = []
    for m in ATTRIBUTION.finditer(code):
        phrase = m.group(1)
        if phrase.split()[0].lower() in NOT_A_NAME:
            continue
        if not approved_label(phrase):
            out.append((m.start(1), "provider_label", phrase))
    for m in PROVIDER_FIELD.finditer(code):
        group = "plain" if m.group("plain") is not None else "jsx"
        value = m.group(group).strip()
        if value and not approved_label(value):
            parts = [p.strip() for p in re.split(r"\s*[+&/,]\s*", value) if p.strip()]
            if not parts or not all(approved_label(p) for p in parts):
                out.append((m.start(group), "provider_label", value))
    for m in JOINED.finditer(code):
        parts = [m.group(1)] + [p for p in re.split(r"\s*\+\s*", m.group(2)) if p]
        if not any(part.split()[0] in PROVIDER_WORDS for part in parts):
            continue
        for part in parts:
            if not approved_label(part):
                out.append((m.start(), "provider_label", part))
    for m in PROVIDER_DECLARATION.finditer(code):
        body = _block(code, m.start(2), m.group(2))
        for value in re.findall(r"""['"`]([^'"`\n]{1,80})['"`]""", body):
            if not approved_label(value.strip()):
                out.append((m.start(), "provider_label", value.strip()))
    return out


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
        for offset, rule, shown in provider_name_findings(code):
            violations.append({
                "file": rel, "line": code[:offset].count("\n") + 1, "rule": rule,
                "severity": "high", "match": shown[:60],
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
                  f"reason if it is genuinely a Technical Details surface. A provider "
                  f"name must be one scripts/provider_allowlist.py approves.")

    # MEDIUM IS NOW BLOCKING TOO, as of 2026-09-24.
    #
    # It was high-only while 20 medium violations stood, on the same staging the provider
    # gate used: run advisory until the count reaches zero, then flip. A gate
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
