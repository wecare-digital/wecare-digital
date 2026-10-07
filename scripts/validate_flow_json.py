#!/usr/bin/env python3
"""Structurally validate every WhatsApp Flow JSON in the repo, offline.

WHY THIS IS A LOCAL CHECK AND NOT META'S VALIDATOR
--------------------------------------------------
Meta validates Flow JSON as a side effect of `POST /{waba-id}/flows` (or
`POST /{flow-id}/assets`) — i.e. you have to CREATE the Flow on the WABA to be told
whether the JSON is well formed. Creating and publishing a Flow is an owner-only,
customer-visible action under `.kiro/steering/01-standing-authorization.md`, so the
build loop cannot reach the API validator without doing the one thing it is not
allowed to do. The alternative was to validate nothing, which is how a flow ships
with a `${data.x}` nobody declared and fails on the handset instead of in CI.

So this is a LOCAL STRUCTURAL CHECK, and any report that cites it must say so rather
than implying Meta signed the JSON off. It catches the class of mistake that is cheap
to make while editing JSON by hand — a dangling screen reference, an undeclared data
key, a form field the Footer names but the screen does not contain — and it cannot
catch a component property Meta renamed between Flow versions.

It is read-only: no network, no AWS, no writes. Exit 0 if every file is valid,
1 otherwise, printing `<file>: <screen>: <problem>` per failure.

THE RULES, AND WHY EACH ONE EARNS ITS PLACE
-------------------------------------------
1. `version` present. Meta rejects a Flow without one.
2. `routing_model` present WHEN THERE IS MORE THAN ONE SCREEN. `postpay-flow-v1.json`
   is a single terminal screen and legitimately omits it, so requiring it
   unconditionally would fail a live flow — and a validator that fails on shipped,
   working input gets switched off, which protects nothing.
3. Every `routing_model` key and every target names a declared screen. A typo here is
   invisible until a customer taps the button that goes nowhere.
4. At least one screen is `terminal: true` AND reachable from the first screen. A flow
   whose terminal screen cannot be reached traps the customer; a flow with no terminal
   screen never completes, so `data_exchange` never fires and nothing is ever stored.
5. No screen is unreachable from the first screen. Dead screens are usually a renamed
   id that one of the two places was not updated for.
6. Every declared `data` key carries an `__example__`. Meta uses it to type-check the
   screen, and a missing one is rejected at publish time — the slowest possible place
   to find out.
7. Every `${data.X}` used in a screen's `layout` is declared in THAT screen's `data`.
   Screen data does not inherit, so a reference to another screen's key renders empty.
   `${WD_LOGO_BASE64}` and friends are deliberately NOT checked: they are global
   substitutions performed by the sender, not screen data.
8. Every `${form.X}` in a screen's layout names a component in the same screen. This is
   the one that actually bites: rename a Dropdown's `name` and the Footer payload
   silently delivers nothing, so the handler stores a review with no rating.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
FLOWS_DIR = ROOT / "amplify" / "functions" / "messaging" / "whatsapp-business-api" / "flows"

#: `${data.foo}` / `${data.foo.bar}` — the leading segment is the declared key.
_DATA_REF = re.compile(r"\$\{data\.([A-Za-z0-9_]+)")
#: `${form.foo}` — must name a component in the same screen.
_FORM_REF = re.compile(r"\$\{form\.([A-Za-z0-9_]+)")


def _component_names(node: Any, found: set) -> set:
    """Every `name` on every component in a layout subtree.

    Walked structurally rather than regexed out of the serialized layout: a `name`
    key inside a `data-source` example would be picked up by a text scan and would
    make rule 8 pass on a form field that does not exist.
    """
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str) and node.get("type"):
            found.add(name)
        for value in node.values():
            _component_names(value, found)
    elif isinstance(node, list):
        for item in node:
            _component_names(item, found)
    return found


def _reachable(first: str, routing: Dict[str, List[str]]) -> set:
    seen = {first}
    stack = [first]
    while stack:
        for target in routing.get(stack.pop(), []) or []:
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def validate_flow(doc: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable problems. Empty means valid."""
    problems: List[str] = []

    if not doc.get("version"):
        problems.append("top level: no `version`")

    screens = doc.get("screens")
    if not isinstance(screens, list) or not screens:
        problems.append("top level: no `screens`")
        return problems

    ids = [s.get("id") for s in screens if isinstance(s, dict)]
    if len(ids) != len(screens) or any(not isinstance(i, str) or not i for i in ids):
        problems.append("top level: every screen needs a string `id`")
        return problems
    if len(set(ids)) != len(ids):
        problems.append("top level: duplicate screen ids")

    routing = doc.get("routing_model")
    if routing is None:
        # Rule 2: a single terminal screen needs no routing model.
        if len(screens) > 1:
            problems.append("top level: no `routing_model` but more than one screen")
        routing = {}
    elif not isinstance(routing, dict):
        problems.append("top level: `routing_model` must be an object")
        routing = {}

    for key, targets in routing.items():
        if key not in ids:
            problems.append(f"routing_model: `{key}` is not a declared screen")
        for target in targets or []:
            if target not in ids:
                problems.append(f"routing_model: `{key}` -> `{target}` is not a declared screen")

    reachable = _reachable(ids[0], routing)
    terminal = {s["id"] for s in screens if s.get("terminal")}
    if not terminal:
        problems.append("top level: no screen is `terminal: true`")
    elif not terminal & reachable:
        problems.append(
            f"top level: terminal screen(s) {sorted(terminal)} unreachable from `{ids[0]}`")
    for orphan in sorted(set(ids) - reachable):
        problems.append(f"{orphan}: unreachable from `{ids[0]}`")

    for screen in screens:
        sid = screen["id"]
        data = screen.get("data") or {}
        if not isinstance(data, dict):
            problems.append(f"{sid}: `data` must be an object")
            data = {}
        for key, spec in data.items():
            if isinstance(spec, dict) and "__example__" not in spec:
                problems.append(f"{sid}: data key `{key}` has no `__example__`")

        layout = screen.get("layout")
        if layout is None:
            problems.append(f"{sid}: no `layout`")
            continue
        serialized = json.dumps(layout, ensure_ascii=False)
        for ref in sorted(set(_DATA_REF.findall(serialized))):
            if ref not in data:
                problems.append(f"{sid}: `${{data.{ref}}}` is not declared in this screen's `data`")
        names = _component_names(layout, set())
        for ref in sorted(set(_FORM_REF.findall(serialized))):
            if ref not in names:
                problems.append(f"{sid}: `${{form.{ref}}}` names no component in this screen")

    return problems


def flow_files(directory: Path = FLOWS_DIR) -> Iterable[Path]:
    return sorted(directory.glob("*.json"))


def main() -> int:
    files = list(flow_files())
    if not files:
        print(f"no flow JSON found under {FLOWS_DIR}", file=sys.stderr)
        return 1

    failures = 0
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{path.name}: unreadable: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        problems = validate_flow(doc)
        if problems:
            failures += 1
            for problem in problems:
                print(f"{path.name}: {problem}")
        else:
            print(f"{path.name}: OK")

    print(f"\n{len(files) - failures}/{len(files)} flow JSON files valid "
          f"(LOCAL structural check, not Meta's Flow JSON API)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
