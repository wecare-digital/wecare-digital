#!/usr/bin/env python3
"""CI gate: enforce the measured constraints declared here and in src/styles/tokens.css.

The contract was calibrated by measuring the live public pages, not by eye, and it
names five retired colours explicitly. This gate stops them coming back, and stops the
semantic state colours collapsing into each other again.

What it found on 2026-09-23, before it existed
----------------------------------------------
* `--warning` and `--info` were both `#1a3a2a` — the same value as `--success`. So a
  warning rendered identically to a success at all 3 live `var(--warning)` call sites.
  A state colour that cannot be told from another state is not a state colour.
* `--text-secondary` and `--color-grey-600` were `#4b5563`, which the contract retires
  by name: "the only blue-tinted grey in the page's own copy", reading cooler than the
  neutral body text beside it. 25 live uses.
* `src/lib/design-tokens.ts` declares itself the single source of truth, mirrors
  `tokens.css` "MIRRORS" in its own docstring, contradicts it in several places, and has
  **zero importers**. 172 lines nobody uses, which is why ~1,500 border-radius
  declarations across `src/` use twelve different values against a contract that
  specifies one.

Comments are stripped before matching
-------------------------------------
`src/pages/grahak-os/index.tsx` names all five retired colours in comments that explain
why each was retired — that is the documentation working, not a violation. Reporting it
would be reporting the record of the fix as the defect, which is a mistake this
repository's tests have had to correct three times now.

Usage
-----
    python scripts/check_design_drift.py
    python scripts/check_design_drift.py --gate
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOKENS_CSS = SRC / "styles/tokens.css"

# Retired by name in the design contract. None may appear in real CSS or in a style
# object; a comment explaining the retirement is fine.
RETIRED_COLOURS = {
    "#2f6b52": "retired brand green",
    "#075e54": "retired WhatsApp green",
    "#f2fbf6": "retired lime wash",
    "#fbfff0": "retired lime wash",
    "#1e293b": "retired slate, specifically as a code-panel body",
    "#4b5563": "retired blue-tinted grey; use rgba(0,0,0,.54)",
    "#0f172a": "rest of the retired slate ramp",
    "#94a3b8": "rest of the retired slate ramp",
    "#1e1e1e": "retired code-panel background; both panels are #000",
    # Promoted from the stylesheet-only rule on 2026-09-24. It used to live in its own
    # scan because 129 uses were still sitting in inline React style objects across 22
    # files - a separate job that is now done, so there is no longer a reason for it to
    # be checked less strictly than the other eight.
    "#111827": ("retired blue-tinted grey; #1a1a1a for text (tokens.css --text), "
                "rgba(0,0,0,.95) for the heading rung, #000 for a code panel"),
}

# `design-tokens.ts` opens by declaring itself the single source of truth and says it
# MIRRORS tokens.css. It did not: `text` was #111827 against `--text: #1a1a1a`, and
# `grey900` was #111827 against `--color-grey-900: rgba(0,0,0,.95)`. That matters
# because the file has 14 importers, so `colors.text` resolved to a retired colour in
# 14 files while every rule reading the CSS variable resolved to the right one - two
# primary text colours on the same screen, decided by which system a component happened
# to use. Pinned here rather than trusted to a comment.
TOKEN_MIRROR = {
    "text": "--text",
    "textSecondary": "--text-secondary",
    "textMuted": "--text-muted",
    "textLight": "--text-light",
    "grey900": "--color-grey-900",
}
DESIGN_TOKENS_TS = SRC / "lib/design-tokens.ts"

# State tokens that must stay visually distinct from one another.
STATE_TOKENS = ("--success", "--warning", "--info", "--danger")

# ---------------------------------------------------------------------------
# Inner-page alignment, added 2026-09-24
# ---------------------------------------------------------------------------
# The contract's hairline rule is "2px means hoverable, 1px means static, and the
# colour is always #e5e7eb", with lime kept for our own surfaces and a hover that
# swaps the border TO lime. inner-pages.css had it inverted on 39 surfaces: lime
# at rest, dark green on hover. Seven of those were selects, text inputs and
# textareas, so every form field on the dashboard wore a ring that reads as
# permanently focused - the same defect already fixed on the sign-in form and
# never propagated to the pages behind it.
#
# Two lime resting borders are legitimate: .msg-bar.success and .success-banner
# are lime with #1a3a2a type, which is contract treatment 1 ("our own surfaces,
# full voice") rather than a stray hairline.
#
# Allowlisted by SELECTOR, not by count. A numeric budget would have been
# satisfied by any two lime borders in the file, so moving a rule or adding a new
# offender while deleting an allowed one would pass silently - the allowlist has
# to name what it permits. This gate found a third site on its first run:
# `.logs-table` carried `2px solid #d1f470`, which the migration's `1.5px` grep
# had missed entirely.
# Scans ALL of src/styles, not one file. Scoping this to inner-pages.css was the
# first version's mistake and the shipped CSS exposed it: after that file was
# clean, a rebuilt bundle still carried 36 lime resting borders, because the same
# inversion is repeated in eight other stylesheets - including tokens.css, where
# `input, select, textarea` is UNSCOPED and so paints the public pages too.
STYLE_DIR = SRC / "styles"
LIME_RESTING_BORDER = re.compile(r"border(?:-color)?:\s*[\d.]+px\s+solid\s+#d1f470",
                                 re.I)
LIME_RESTING_ALLOWED = (".msg-bar.success", ".success-banner",
                        ".message-bar.success", ".message-bubble.outbound")

# The public measure. .hero, .api, .pp-inner and Footer's .ft-in all cap at
# 1300px; an inner container on a different measure lines up with neither the
# header above it nor the footer below.
PUBLIC_MEASURE = "1300px"
MEASURE_SITES = [
    (SRC / "styles/inner-ux.css", r"\.inner-page-container\s*\{[^}]*?max-width:\s*([^;]+);"),
]

# Every --font-sans must lead with Inter. They are declared in three files and
# resolved by _app.tsx import order, so one without Inter silently wins and the
# page mixes two typefaces against a body that does use Inter.
FONT_SANS_FILES = [SRC / "styles/Pages.css", SRC / "styles/Dashboard.css",
                   SRC / "styles/tokens.css"]

# A destructive affordance must not wear the success colour. Found three: a
# delete button, a delete panel and a danger icon button, all painted #1a3a2a -
# which the palette assigns to "active states, accents" and tokens.css assigns to
# --success. Same defect as --warning and --info both resolving to --success, and
# worse, because here the colour told the user a delete was safe.
SUCCESS_GREEN = "#1a3a2a"
DANGER_SELECTOR = re.compile(r"\.(?:[\w-]*danger[\w-]*|[\w-]*delete[\w-]*)\b", re.I)
# Narrowed after its first run flagged nine sites, of which four were not
# affordances at all. High precision matters more than coverage here: a gate that
# cries about an API-docs label is a gate someone switches off.
#
#   .delete-options button   a segmented picker for WHICH scope to delete. The
#                            destructive trigger is a separate confirm, so the
#                            picker's selected state is an ordinary active state.
#   .api-method.delete       the word DELETE in API documentation. A label, not a
#                            control; nothing happens when you look at it.
DANGER_ALLOWED = (".delete-options", ".api-method")


def strip_comments(text: str, suffix: str) -> str:
    """Blank comments, preserving line numbers so reported locations are usable."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text,
                  flags=re.S)
    if suffix in (".ts", ".tsx"):
        text = "\n".join(re.sub(r"(?<!:)//.*$", "", ln) for ln in text.splitlines())
    return text


def scan_retired():
    violations = []
    for path in sorted(list(SRC.rglob("*.tsx")) + list(SRC.rglob("*.ts"))
                       + list(SRC.rglob("*.css"))):
        if "node_modules" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.endswith((".test.tsx", ".test.ts")):
            continue
        code = strip_comments(path.read_text(encoding="utf-8", errors="ignore"),
                              path.suffix)
        for colour, why in RETIRED_COLOURS.items():
            for match in re.finditer(re.escape(colour), code, re.I):
                violations.append({
                    "rule": "retired_colour", "file": rel,
                    "line": code[:match.start()].count("\n") + 1,
                    "match": colour, "why": why,
                })
    return violations


def scan_state_collision():
    """Two state tokens resolving to the same colour is a defect, not a preference."""
    if not TOKENS_CSS.exists():
        return [{"rule": "tokens_missing", "file": "src/styles/tokens.css",
                 "line": 0, "match": "", "why": "token file not found"}]

    text = strip_comments(TOKENS_CSS.read_text(encoding="utf-8"), ".css")
    values = {}
    for token in STATE_TOKENS:
        m = re.search(rf"{re.escape(token)}:\s*([^;]+);", text)
        if m:
            values[token] = m.group(1).strip().lower()

    violations = []
    seen = {}
    for token, value in values.items():
        if value in seen:
            violations.append({
                "rule": "state_colour_collision",
                "file": "src/styles/tokens.css", "line": 0, "match": value,
                "why": (f"{token} and {seen[value]} are both {value}; a state that "
                        f"cannot be distinguished from another state is not a state"),
            })
        seen[value] = token
    return violations


def scan_lime_resting_borders():
    """Lime is an interactive-state colour, not a resting hairline."""
    hits = []
    for path in sorted(STYLE_DIR.glob("*.css")):
        rel = path.relative_to(ROOT).as_posix()
        code = strip_comments(path.read_text(encoding="utf-8"), ".css")
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if not LIME_RESTING_BORDER.search(line):
                continue
            # Walk back to the selector this declaration belongs to. A lime border
            # inside :hover, :focus, :active or on a .selected / .sent surface is
            # the contract working, not drift.
            j = i
            while j > 0 and "{" not in lines[j]:
                j -= 1
            k = j
            while k > 0 and lines[k - 1].strip() and not lines[k - 1].strip().endswith("}"):
                k -= 1
            sel = " ".join(x.strip() for x in lines[k:j + 1])
            if any(s in sel for s in (":hover", ":focus", ":active", ".selected",
                                      ".active", ".sent", ".outbound")):
                continue
            if any(a in sel for a in LIME_RESTING_ALLOWED):
                continue
            hits.append({"rule": "lime_resting_border", "file": rel, "line": i + 1,
                         "match": line.strip(),
                         "why": ("lime is reserved for interactive state and our own "
                                 "surfaces; a resting hairline is #e5e7eb, 2px when "
                                 "the element has a :hover and 1px when it does not")})
    return hits


def scan_token_mirror():
    """`design-tokens.ts` must not contradict the CSS variable it claims to mirror.

    Values are compared after compositing, because the two files legitimately express
    the same colour differently - `rgba(0,0,0,.898)` over white IS `#1a1a1a`, exactly -
    and flagging that as a mismatch would push someone to "fix" agreement into
    disagreement.
    """
    if not DESIGN_TOKENS_TS.exists() or not TOKENS_CSS.exists():
        return []

    css = strip_comments(TOKENS_CSS.read_text(encoding="utf-8"), ".css")
    ts = strip_comments(DESIGN_TOKENS_TS.read_text(encoding="utf-8"), ".ts")

    violations = []
    for ts_key, css_var in TOKEN_MIRROR.items():
        tm = re.search(rf"\b{re.escape(ts_key)}:\s*'([^']+)'", ts)
        cm = re.search(rf"{re.escape(css_var)}:\s*([^;]+);", css)
        if not tm or not cm:
            continue
        a, b = normalise_colour(tm.group(1)), normalise_colour(cm.group(1))
        if a != b:
            violations.append({
                "rule": "token_mirror_mismatch",
                "file": DESIGN_TOKENS_TS.relative_to(ROOT).as_posix(),
                "line": ts[:tm.start()].count("\n") + 1,
                "match": f"{ts_key}={tm.group(1)} vs {css_var}={cm.group(1).strip()}",
                "why": ("this file says it mirrors tokens.css and has 14 importers, so "
                        "a disagreement puts two different values for the same token on "
                        "one screen depending on which system a component reads")})
    return violations


def normalise_colour(value: str) -> str:
    """A colour as an #rrggbb string, compositing rgba() over white.

    White because every surface these tokens paint text on is white or near-white, and
    the contract's own body colour is written as `rgba(0,0,0,.898)` in one file and
    `#1a1a1a` in another - the same colour, two spellings.
    """
    value = value.strip().lower()
    m = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)"
                 r"(?:[,/\s]+([\d.]+))?\s*\)", value)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        r, g, b = (round(c * a + 255 * (1 - a)) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"
    m = re.match(r"#([0-9a-f]{3})$", value)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1))
    m = re.match(r"#([0-9a-f]{6})$", value)
    return f"#{m.group(1)}" if m else value


def scan_danger_in_success_green():
    """A danger or delete surface must not be painted the success green."""
    hits = []
    for path in sorted(STYLE_DIR.glob("*.css")):
        rel = path.relative_to(ROOT).as_posix()
        code = strip_comments(path.read_text(encoding="utf-8"), ".css")
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if SUCCESS_GREEN not in line:
                continue
            if not re.search(r"\b(?:color|border-color|background(?:-color)?|border)\s*:",
                             line):
                continue
            j = i
            while j > 0 and "{" not in lines[j]:
                j -= 1
            k = j
            while k > 0 and lines[k - 1].strip() and not lines[k - 1].strip().endswith("}"):
                k -= 1
            sel = " ".join(x.strip() for x in lines[k:j + 1])
            if not DANGER_SELECTOR.search(sel):
                continue
            if any(a in sel for a in DANGER_ALLOWED):
                continue
            hits.append({
                "rule": "danger_painted_success_green", "file": rel,
                "line": i + 1, "match": line.strip(),
                "why": (f"{SUCCESS_GREEN} is --success; a destructive affordance must "
                        f"use --danger #dc2626 so the colour does not say the action "
                        f"is safe")})
    return hits


def scan_measure():
    """The inner content measure must match the public one."""
    violations = []
    for path, pattern in MEASURE_SITES:
        if not path.exists():
            continue
        rel = path.relative_to(ROOT).as_posix()
        code = strip_comments(path.read_text(encoding="utf-8"), ".css")
        m = re.search(pattern, code, re.S)
        if not m:
            violations.append({"rule": "measure_missing", "file": rel, "line": 0,
                               "match": "", "why": "could not find the container rule"})
            continue
        value = m.group(1).strip()
        if value != PUBLIC_MEASURE:
            violations.append({
                "rule": "measure_mismatch", "file": rel,
                "line": code[:m.start(1)].count("\n") + 1, "match": value,
                "why": (f"the public pages cap at {PUBLIC_MEASURE}; an inner "
                        f"container at {value} aligns with neither the header nor "
                        f"the footer")})
    return violations


def scan_font_sans():
    """Inter must lead every --font-sans, or import order decides the typeface."""
    violations = []
    for path in FONT_SANS_FILES:
        if not path.exists():
            continue
        rel = path.relative_to(ROOT).as_posix()
        code = strip_comments(path.read_text(encoding="utf-8"), ".css")
        for m in re.finditer(r"--font-sans:\s*([^;]+);", code):
            value = m.group(1).strip()
            if not value.lower().startswith(("'inter'", '"inter"', "inter")):
                violations.append({
                    "rule": "font_sans_missing_inter", "file": rel,
                    "line": code[:m.start()].count("\n") + 1,
                    "match": value[:60],
                    "why": ("body renders Inter, so a --font-sans without it makes "
                            "the page mix two typefaces depending on whether a rule "
                            "names the token")})
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    violations = (scan_retired() + scan_state_collision()
                  + scan_lime_resting_borders() + scan_token_mirror()
                  + scan_danger_in_success_green()
                  + scan_measure() + scan_font_sans())

    if args.json:
        print(json.dumps({"violations": violations}, indent=2))
    elif not violations:
        print("DESIGN DRIFT OK - no retired colours, no state-colour collisions.")
    else:
        by_rule = {}
        for v in violations:
            by_rule.setdefault(v["rule"], []).append(v)
        for rule, items in sorted(by_rule.items()):
            print(f"\n  {rule}  ({len(items)})")
            for v in items[:12]:
                loc = f"{v['file']}:{v['line']}" if v["line"] else v["file"]
                print(f"     {loc}  {v['match']}  — {v['why']}")
            if len(items) > 12:
                print(f"     ... and {len(items) - 12} more")
        print(f"\n{len(violations)} violation(s). The contract is "
              f"declared in scripts/check_design_drift.py and src/styles/tokens.css; calibrated from the "
              f"live pages, so change it deliberately rather than incidentally.")

    if args.gate and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
