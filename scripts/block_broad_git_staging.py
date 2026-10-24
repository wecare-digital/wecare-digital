#!/usr/bin/env python3
"""Stop one Kiro session from committing or destroying another session's work.

Kiro PreToolUse hook. Companion to ``block_inline_secrets.py``.

Why this exists
---------------
Local Kiro sessions are not isolated. Every session open on a workspace points at
the same working tree, the same git index and the same ``HEAD``; there is no
per-session staging area and no merge step. Measured on 2026-09-20 this workspace
had **three warm sessions at once**, and while one of them was writing tooling the
others had four unrelated files modified:

    M amplify/functions/core/site-language/handler.py
    M scripts/snapstart_publish.py
    M src/components/Header.tsx
    M src/components/__tests__/Header.test.tsx

A single ``git add .`` in any session would have swept all four into an unrelated
commit on ``wecare.digital``, attributing half-finished work to the wrong change. The
project rule already says to stage by explicit path; this hook is what makes the
rule hold when an agent reaches for the convenient thing.

Checkpoints do not save you here. Kiro only snapshots files its **own** file tools
touched in that session, so a revert in session A silently discards session B's
edits to the same file, with no record that it happened. Git is the only shared
source of truth between sessions, which is exactly why tree-wide git commands are
the dangerous ones.

What it does
------------
Parses the command shell-aware (splits on ``&&``, ``||``, ``;``, ``|`` and
newlines, then ``shlex``), finds every ``git`` invocation, and inspects the real
arguments rather than pattern-matching raw text. Two tiers:

**BLOCK (exit 2)** - tree-wide staging, where naming the paths is always
available and always better:

    git add .          git add -A         git add --all
    git add -u         git add :/         git add '*'
    git commit -a      git commit -am ... git commit --all
    git stash          git stash push     (bare, no pathspec)

**ASK (exit 0 + permissionDecision)** - destructive to the shared tree, but
sometimes genuinely wanted, so the user decides:

    git reset --hard   git checkout -- .  git restore .
    git clean -f/-fd   git push --force   git push -f

Read-only forms stay silent: ``git stash list``, ``git stash show``,
``git add -p``, ``git add <path>``, ``git status``, ``git diff``.

The refusal message carries the live warm-session count, so the agent reading it
knows whether it is one session or four that would be affected.

Self-test
---------
    python scripts/block_broad_git_staging.py --self-test
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_shell_parse import (  # noqa: E402
    segments as shell_segments,
    split_args,
)

WARM_MINS = 5
KIRO = Path.home() / ".kiro"

# Tree-wide pathspecs. "-u"/"--update" stages every tracked modification, which
# is just as broad as "." for our purposes.
ADD_ALL_FLAGS = {"-A", "--all", "--no-ignore-removal", "-u", "--update"}
ADD_ALL_PATHSPECS = {".", "*", ":/", "./", ":/.", "-"}


# --------------------------------------------------------------------------- #
# payload
# --------------------------------------------------------------------------- #

def find_commands(payload: object) -> list[str]:
    """Pull command strings out of the hook payload.

    Schema-agnostic on purpose: the PreToolUse contract may nest the command
    under different keys across Kiro versions, and a guard that silently stops
    matching after an upgrade is worse than one that over-reads. Prefer
    command-ish keys, fall back to every string in the payload.
    """
    found: list[str] = []
    fallback: list[str] = []

    def walk(node: object, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str):
            if key.lower() in ("command", "cmd", "commandline", "command_line",
                               "script", "shellcommand"):
                found.append(node)
            elif "git" in node:
                fallback.append(node)

    walk(payload)
    return found or fallback


def git_invocations(command: str) -> list[list[str]]:
    """Every git call in a (possibly compound) command, as argv lists.

    Heredoc bodies are stripped first, so a commit message that *documents*
    ``git add .`` is not mistaken for running it. That was a live false positive:
    the guard refused the very commit that introduced it.
    """
    out: list[list[str]] = []
    for segment in shell_segments(command):
        if "git" not in segment:
            continue
        argv = split_args(segment)

        i = 0
        while i < len(argv):
            tok = argv[i]
            # Skip leading env assignments so `FOO=bar git add .` still matches.
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tok):
                i += 1
                continue
            if tok == "git" or tok.endswith("/git"):
                out.append(argv[i:])
            # Only command position counts; stop at the first real program.
            break
    return out


def subcommand(argv: list[str]) -> tuple[str, list[str]]:
    """git [global opts] <subcommand> [args] -> (subcommand, args)."""
    i = 1
    takes_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--exec-path", "--config-env"}
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("-"):
            return tok, argv[i + 1:]
        if tok in takes_value:
            i += 2
            continue
        i += 1
    return "", []


def has_short(args: list[str], letter: str) -> bool:
    """True if a clustered short flag contains `letter`, e.g. -am contains 'a'."""
    for a in args:
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            if letter in a[1:]:
                return True
    return False


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #

def classify(argv: list[str]) -> tuple[str, str] | None:
    """Return (severity, reason) where severity is 'block' or 'ask'."""
    sub, args = subcommand(argv)
    if not sub:
        return None
    positional = [a for a in args if not a.startswith("-")]

    if sub == "add":
        if "-p" in args or "--patch" in args or "-i" in args or "--interactive" in args:
            return None                      # interactive, user picks hunks
        if any(a in ADD_ALL_FLAGS for a in args) or has_short(args, "A"):
            return "block", "`git add` with a tree-wide flag (-A/--all/-u)"
        if any(p in ADD_ALL_PATHSPECS for p in positional):
            return "block", "`git add` with a tree-wide pathspec (. / * / :/)"
        if not positional:
            return "block", "`git add` with no pathspec"
        return None

    if sub == "commit":
        if "--all" in args or has_short(args, "a"):
            return "block", "`git commit -a/--all` stages every tracked change"
        return None

    if sub == "stash":
        action = positional[0] if positional else "push"
        if action in ("list", "show"):
            return None                      # read-only
        if action in ("push", "save", "create", "store"):
            # A pathspec-scoped stash is fine; a bare one takes the whole tree.
            if "--" in args or len(positional) > 1:
                return None
            return "block", f"`git stash {action}` removes every uncommitted change in the tree"
        if action in ("pop", "apply", "drop", "clear", "branch"):
            return "ask", f"`git stash {action}` rewrites shared working-tree state"
        return "block", "bare `git stash` removes every uncommitted change in the tree"

    if sub == "reset":
        if "--hard" in args:
            return "ask", "`git reset --hard` discards uncommitted work tree-wide"
        return None

    if sub in ("checkout", "restore"):
        if any(p in ADD_ALL_PATHSPECS for p in positional) or (
                "--" in args and not [p for p in positional if p not in ADD_ALL_PATHSPECS]):
            return "ask", f"`git {sub}` with a tree-wide pathspec discards uncommitted edits"
        return None

    if sub == "clean":
        if has_short(args, "f") or "--force" in args:
            return "ask", "`git clean -f` deletes untracked files tree-wide"
        return None

    if sub == "push":
        if "--force" in args or "--force-with-lease" in args or has_short(args, "f"):
            return "ask", "`git push --force` rewrites the shared remote branch"
        return None

    return None


# --------------------------------------------------------------------------- #
# context: how many sessions would this affect
# --------------------------------------------------------------------------- #

def warm_session_count(root: str | None = None) -> tuple[int, int]:
    """(warm, open) IDE sessions for this workspace. Cheap: stat only, no walk."""
    root = root or os.environ.get("KIRO_WORKSPACE_ROOT") or os.getcwd()
    try:
        key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    except OSError:
        return 0, 0

    idx = KIRO / "session-index" / f"{key}.jsonl"
    if not idx.is_file():
        return 0, 0

    state: dict[str, str] = {}
    try:
        for line in idx.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = str(rec.get("sessionPath", "")).rsplit("/", 1)[-1]
            if sid:
                state[sid] = rec.get("op", "")
    except OSError:
        return 0, 0

    now = time.time()
    warm = opened = 0
    for sid, op in state.items():
        if op != "add":
            continue
        d = KIRO / "sessions" / key / sid
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        opened += 1
        if now - mtime <= WARM_MINS * 60:
            warm += 1
    return warm, opened


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def decide(raw: str) -> tuple[int, str]:
    """Return (exit_code, message_to_emit)."""
    if not raw.strip():
        return 0, ""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw

    blocks: list[str] = []
    asks: list[str] = []
    for command in find_commands(payload):
        for argv in git_invocations(command):  # heredoc bodies already stripped
            verdict = classify(argv)
            if not verdict:
                continue
            severity, reason = verdict
            (blocks if severity == "block" else asks).append(reason)

    if not blocks and not asks:
        return 0, ""

    warm, opened = warm_session_count()
    if opened > 1:
        ctx = (f"This workspace has {opened} open Kiro session(s), {warm} of them "
               f"warm. They share one working tree and one git index.")
    else:
        ctx = "This workspace currently has one session, but the rule still holds."

    if blocks:
        return 2, (
            "BLOCKED: tree-wide git staging.\n"
            + "\n".join(f"  - {r}" for r in dict.fromkeys(blocks)) + "\n"
            + ctx + "\n"
            "Another session's half-finished edits would be captured in your "
            "commit, attributed to your change. Kiro checkpoints will not "
            "recover it: a session only snapshots files its own tools touched.\n"
            "Stage by explicit path instead:\n"
            "  git add path/one.py path/two.ts\n"
            "  git commit -m '...'\n"
            "Run `git status --short` first, and `python scripts/session_map.py` "
            "to see who else is live."
        )

    return 0, json.dumps({
        "hookSpecificOutput": {
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                "Destructive to the shared working tree: "
                + "; ".join(dict.fromkeys(asks)) + ". " + ctx
                + " Confirm only if you know no other session has uncommitted work."
            ),
        }
    })


SELF_TEST = [
    # (command, expected exit code)
    ("git add .", 2),
    ("git add -A", 2),
    ("git add --all", 2),
    ("git add -u", 2),
    ("git add :/", 2),
    ("git add", 2),
    ("git commit -am 'x'", 2),
    ("git commit -a -m 'x'", 2),
    ("git commit --all -m 'x'", 2),
    ("git stash", 2),
    ("git stash push", 2),
    ("git add scripts/foo.py && git commit -m 'x'", 0),
    ("git add -p", 0),
    ("git add scripts/a.py scripts/b.py", 0),
    ("git commit -m 'only staged'", 0),
    ("git status --short", 0),
    ("git diff --cached --name-only", 0),
    ("git stash list", 0),
    ("git stash show", 0),
    ("git -C /tmp/repo add .", 2),
    ("git log --oneline -1", 0),
    ("ls -la && git add .", 2),
    ("git push origin wecare.digital", 0),
    ("git stash push -- scripts/foo.py", 0),
    # Regression: a commit message that DOCUMENTS tree-wide staging must not be
    # mistaken for performing it. This guard refused its own introducing commit.
    ("git add scripts/a.py && git commit -F - <<'MSG'\n"
     "guard: refuse tree-wide staging\n\n"
     "Blocks `git add .`, `git add -A` and `git commit -a` because concurrent\n"
     "sessions share one index. Stage by path instead.\n"
     "MSG", 0),
    ("grep -rn 'git add -A' docs/", 0),
    ("echo 'never run git add .'", 0),
    ("FOO=bar git add .", 2),
]

ASK_TESTS = [
    "git reset --hard",
    "git checkout -- .",
    "git restore .",
    "git clean -fd",
    "git push --force origin wecare.digital",
    "git push -f origin wecare.digital",
    "git stash pop",
]


def self_test() -> int:
    failures = 0
    for cmd, want in SELF_TEST:
        code, msg = decide(json.dumps({"command": cmd}))
        ok = code == want
        if not ok:
            failures += 1
        print(f"  {'ok  ' if ok else 'FAIL'}  exit={code} want={want}  {cmd}")

    for cmd in ASK_TESTS:
        code, msg = decide(json.dumps({"command": cmd}))
        is_ask = code == 0 and "permissionDecision" in msg
        if not is_ask:
            failures += 1
        print(f"  {'ok  ' if is_ask else 'FAIL'}  ask={is_ask}  {cmd}")

    total = len(SELF_TEST) + len(ASK_TESTS)
    print(f"\n{total - failures}/{total} cases passed")
    return 1 if failures else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    code, msg = decide(sys.stdin.read())
    if code == 2:
        print(msg, file=sys.stderr)
    elif msg:
        print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
