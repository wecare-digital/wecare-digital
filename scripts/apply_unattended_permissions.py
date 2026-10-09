#!/usr/bin/env python3
"""Replace Kiro's accumulated click-by-click allow list with six deliberate rules,
so a long agent run never stops to ask for approval.

The problem this solves
-----------------------
Kiro records permissions per workspace root in
``~/.kiro/workspace-roots/<sha256(abspath)[:16]>/permissions.yaml``. Every time
you click **Always allow**, a new entry is appended. Over time that file becomes
a transcript of past approvals rather than a policy. Measured in this workspace on
2026-09-20, before this script ran:

* **156** shell match patterns
* **12** junk artifacts that can never match a real program, captured from shell
  syntax rather than commands: ``$G *``, ``$A *``, ``$p *``, ``$PY *``,
  ``break *``, ``continue *``, ``read *``, ``set *``, ``mk *``, ``check *``,
  ``classify *``, ``": *"``
* **6** literal one-off command strings, e.g. a full
  ``env -u AWS_PROFILE ... python3 probe3.py`` invocation
* **no** ``fs_read`` or ``fs_write`` rule at all, so file edits still prompted
* ``web_fetch`` limited to 9 hardcoded domains
* ``mcp`` limited to 3 named tools

The gaps are what actually kill an unattended run: the agent hits the 157th
distinct command, or an MCP tool, or a domain that is not on the list, and stops
dead waiting for a human.

Why this is *safer* than what it replaces
-----------------------------------------
Counter-intuitive but important: a wildcard rule is **lower** leak risk than a
long accumulated list.

On 2026-09-19 an audit found four live credentials in plaintext inside this exact
file. They got there because commands were run with the secret inline and then
approved with "Always allow" - which recorded the **entire command string**,
secret included, permanently to disk. The literal entries still visible at lines
111 and 133-138 are that same mechanism, caught mid-act.

``match: ['*']`` cannot do that. It is six lines that never grow and never embed
command text. Removing the incentive to click "Always allow" removes the leak
channel.

Safety is not being dropped - it is moving from *prompts* to *guards*
--------------------------------------------------------------------
Prompting is a poor control for an unattended fleet: it blocks progress on the
999 safe commands and relies on a tired human to catch the one bad one. The
protection is instead carried by PreToolUse hooks that **deny specific shapes
without asking**, which is what makes them compatible with blanket allow:

============================================  ==================================
``.kiro/hooks/block-inline-secrets.json``     issuer-shaped credentials in argv
``.kiro/hooks/block-broad-git-staging.json``  ``git add .`` and friends
``.kiro/hooks/block-catastrophic.json``       irreversible destruction
============================================  ==================================

**Do not apply this policy to a workspace that lacks those hooks.** This script
refuses to, unless ``--force`` is given.

Usage
-----
    python scripts/apply_unattended_permissions.py --list
    python scripts/apply_unattended_permissions.py --dry-run
    python scripts/apply_unattended_permissions.py
    python scripts/apply_unattended_permissions.py --root /path/to/other/project
    python scripts/apply_unattended_permissions.py --all

``--root`` is how you set a *different* project up: it computes that project's
workspace key, creates the directory if Kiro has not seen it yet, and writes the
same policy. ``--restore`` puts the most recent backup back.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

KIRO = Path.home() / ".kiro"
ROOTS = KIRO / "workspace-roots"

REQUIRED_HOOKS = (
    "block-inline-secrets.json",
    "block-broad-git-staging.json",
    "block-catastrophic.json",
)

HEADER = """\
# Kiro permissions - MANAGED FILE
#
# Written by scripts/apply_unattended_permissions.py. Six deliberate rules that
# replaced 156 accumulated "Always allow" entries on 2026-09-20.
#
# Do not hand-edit to add a narrow entry. If a run stops for approval, the answer
# is a broader capability here, not another literal command string: recording
# command strings is exactly how four live credentials were written to this file
# on 2026-09-19.
#
# Blanket allow is only safe because these PreToolUse hooks DENY without asking:
#   .kiro/hooks/block-inline-secrets.json     - credentials in a command line
#   .kiro/hooks/block-broad-git-staging.json  - git add . across live sessions
#   .kiro/hooks/block-catastrophic.json       - irreversible destruction
# Remove a hook and you remove the reason this file is acceptable.
#
# Regenerate:  python scripts/apply_unattended_permissions.py
# Roll back:   python scripts/apply_unattended_permissions.py --restore
"""

POLICY = """\
rules:
  # Any shell command. The narrow per-command list this replaces was the thing
  # that stalled long runs and the thing that leaked secrets.
  - capability: shell
    effect: allow
    match:
      - '*'

  # Reading and writing files in the workspace. Previously absent entirely, so
  # every edit prompted.
  - capability: fs_read
    effect: allow
  - capability: fs_write
    effect: allow

  # Research without a domain allow-list to maintain.
  - capability: web_search
    effect: allow
  - capability: web_fetch
    effect: allow

  # Every MCP tool from every configured server. Both forms are listed because
  # entries are 'server/tool' and a single star may not span the separator.
  - capability: mcp
    effect: allow
    match:
      - '*'
      - '*/*'
"""

USER_HEADER = """\
# Kiro USER-LEVEL permissions - MANAGED FILE
#
# Written by scripts/apply_unattended_permissions.py --user.
#
# Why this file needs rules at all
# --------------------------------
# The per-workspace file grants fs_read/fs_write for the workspace root. Any path
# OUTSIDE a registered root falls through to here. On 2026-09-21 an unattended run
# was interrupted repeatedly because the agent used /tmp for scratch output and
# read ~/.kiro config: 18 literal path entries had accumulated in this file, one
# per approval click, and each new scratch filename prompted again.
#
# Literal entries are the wrong answer for the same reason they were in the
# workspace file: they never stop growing, and "Always allow" records the whole
# string it was shown. Directory scopes replace them.
#
# Deliberately NOT granted
# ------------------------
# $HOME is not wildcarded. block-catastrophic.json guards ~/.aws, ~/.ssh and the
# retained plaintext credential source against shell and MCP routes, but its
# matcher does not cover the file-write tools - so a blanket $HOME write rule here
# would open an unguarded path to exactly the files that policy protects. Scratch
# space and Kiro's own config are enough.
#
# Regenerate:  python scripts/apply_unattended_permissions.py --user
# Roll back:   python scripts/apply_unattended_permissions.py --user --restore
"""

# Scratch and config scopes outside any workspace root. macOS resolves /tmp to
# /private/tmp, and Kiro records the resolved form, so both are listed.
USER_POLICY = """\
rules:
  - capability: shell
    effect: allow
    match:
      - '*'

  - capability: fs_read
    effect: allow
    match:
      - '/tmp/**'
      - '/private/tmp/**'
      - '/var/folders/**'
      - '{home}/.kiro/**'

  - capability: fs_write
    effect: allow
    match:
      - '/tmp/**'
      - '/private/tmp/**'
      - '/var/folders/**'
      - '{home}/.kiro/**'

  - capability: web_search
    effect: allow
  - capability: web_fetch
    effect: allow

  - capability: mcp
    effect: allow
    match:
      - '*'
      - '*/*'
"""


def user_settings_file() -> Path:
    return Path.home() / ".kiro" / "settings" / "permissions.yaml"


def write_user_policy(*, dry_run: bool) -> bool:
    """Replace accumulated literal path entries with directory scopes."""
    target = user_settings_file()
    print(f"\n=== user-level settings")
    print(f"    file   {target}")

    before = summarize(target)
    if before["exists"]:
        print(f"    before {before['lines']} lines, {before['bytes']} bytes, "
              f"{before['rule_entries']} match entries, "
              f"capabilities={before['capabilities']}")
    else:
        print("    before (no user permissions file yet)")

    if dry_run:
        print("    dry-run: would write 6 capabilities scoped to scratch + .kiro")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        backup = target.with_name(
            f"permissions.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(target, backup)
        print(f"    backup {backup.name}")

    body = USER_POLICY.replace("{home}", str(Path.home()))
    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(USER_HEADER + "\n" + body)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)

    after = summarize(target)
    print(f"    after  {after['lines']} lines, {after['bytes']} bytes, "
          f"{after['rule_entries']} match entries, "
          f"capabilities={after['capabilities']}")
    return True


def restore_user() -> bool:
    target = user_settings_file()
    backups = sorted(target.parent.glob("permissions.yaml.bak-*"))
    if not backups:
        print(f"    no backup found in {target.parent}")
        return False
    newest = backups[-1]
    shutil.copy2(newest, target)
    print(f"=== user-level settings\n    restored from {newest.name}")
    return True


def workspace_key(path: str | Path) -> str:
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]


def known_roots() -> list[tuple[str, str | None]]:
    """[(key, root_path_or_None)] for every workspace Kiro has registered."""
    import json
    out = []
    if not ROOTS.is_dir():
        return out
    for d in sorted(ROOTS.iterdir()):
        if not d.is_dir():
            continue
        root = None
        mig = d / ".trust-migration.json"
        if mig.is_file():
            try:
                root = json.loads(mig.read_text()).get("root")
            except Exception:
                pass
        out.append((d.name, root))
    return out


def summarize(path: Path) -> dict:
    """Cheap shape report on an existing permissions.yaml."""
    if not path.is_file():
        return {"exists": False}
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    matches = [l.strip()[2:].strip() for l in lines if l.strip().startswith("- ")]
    # A match entry with no glob character is a literal path - the shape that
    # "Always allow" records one click at a time and that never stops growing.
    # Counting those, rather than counting all entries, is what makes the
    # accumulation warning meaningful: a policy of directory scopes has many
    # entries and zero literals.
    literals = [m for m in matches
                if m and "capability:" not in m and "*" not in m]
    return {
        "exists": True,
        "bytes": len(text),
        "lines": len(lines),
        "rule_entries": len(matches),
        "literal_entries": len(literals),
        "capabilities": [l.split("capability:", 1)[1].strip()
                         for l in lines if "capability:" in l],
    }


def hooks_present(project: Path) -> tuple[list[str], list[str]]:
    hooks_dir = project / ".kiro" / "hooks"
    present, missing = [], []
    for h in REQUIRED_HOOKS:
        (present if (hooks_dir / h).is_file() else missing).append(h)
    return present, missing


def write_policy(key: str, root: str | None, *, dry_run: bool,
                 force: bool) -> bool:
    target_dir = ROOTS / key
    target = target_dir / "permissions.yaml"

    print(f"\n=== {root or '(unresolved)'}")
    print(f"    key    {key}")
    print(f"    file   {target}")

    before = summarize(target)
    if before["exists"]:
        print(f"    before {before['lines']} lines, {before['bytes']} bytes, "
              f"{before['rule_entries']} match entries, "
              f"capabilities={before['capabilities']}")
    else:
        print("    before (no permissions file yet)")

    if root:
        present, missing = hooks_present(Path(root))
        print(f"    hooks  present={present or 'none'}")
        if missing:
            print(f"           MISSING={missing}")
            if not force:
                print("    SKIPPED: blanket allow requires the deny hooks above. "
                      "Add them, or re-run with --force if you accept the risk.")
                return False

    if dry_run:
        print("    dry-run: would write 6 rules "
              "(shell, fs_read, fs_write, web_search, web_fetch, mcp)")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        backup = target.with_name(
            f"permissions.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(target, backup)
        print(f"    backup {backup.name}")

    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(HEADER + "\n" + POLICY)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)

    after = summarize(target)
    print(f"    after  {after['lines']} lines, {after['bytes']} bytes, "
          f"capabilities={after['capabilities']}")
    return True


def restore(key: str, root: str | None) -> bool:
    target_dir = ROOTS / key
    backups = sorted(target_dir.glob("permissions.yaml.bak-*"))
    if not backups:
        print(f"    no backup found in {target_dir}")
        return False
    newest = backups[-1]
    shutil.copy2(newest, target_dir / "permissions.yaml")
    print(f"=== {root or key}\n    restored from {newest.name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", action="append", default=[],
                    help="project path to configure (repeatable); "
                         "defaults to the current workspace")
    ap.add_argument("--all", action="store_true",
                    help="every workspace root Kiro already knows about")
    ap.add_argument("--list", action="store_true",
                    help="show known roots and their current policy shape")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="apply even when the deny hooks are absent")
    ap.add_argument("--restore", action="store_true",
                    help="put the most recent backup back")
    ap.add_argument("--user", action="store_true",
                    help="also write ~/.kiro/settings/permissions.yaml, which "
                         "governs paths outside any workspace root (scratch "
                         "files, Kiro's own config)")
    args = ap.parse_args()

    if args.list:
        print("Workspace roots Kiro has registered:\n")
        for key, root in known_roots():
            s = summarize(ROOTS / key / "permissions.yaml")
            shape = (f"{s['lines']} lines, {s['rule_entries']} entries, "
                     f"{s['capabilities']}") if s["exists"] else "no policy file"
            print(f"  {key}  {root or '(unresolved)'}")
            print(f"  {'':16}  {shape}")
            if root:
                present, missing = hooks_present(Path(root))
                print(f"  {'':16}  hooks present={len(present)}/"
                      f"{len(REQUIRED_HOOKS)}"
                      + (f", missing={missing}" if missing else ""))
        u = summarize(user_settings_file())
        print(f"\nUser-level fallback for paths outside every root:")
        print(f"  {user_settings_file()}")
        if u["exists"]:
            print(f"  {u['lines']} lines, {u['rule_entries']} match entries "
                  f"({u['literal_entries']} literal), {u['capabilities']}")
            if u["literal_entries"]:
                print(f"  NOTE: {u['literal_entries']} literal path entr"
                      f"{'y' if u['literal_entries'] == 1 else 'ies'} - these "
                      "accumulate one approval click at a time. Re-run with "
                      "--user to replace them with directory scopes.")
        else:
            print("  no policy file - every path outside a root will prompt")
        return 0

    targets: list[tuple[str, str | None]] = []
    if args.all:
        targets = known_roots()
    elif args.root:
        targets = [(workspace_key(r), str(Path(r).resolve())) for r in args.root]
    else:
        here = Path.cwd().resolve()
        targets = [(workspace_key(here), str(here))]

    if args.restore:
        ok = sum(restore(k, r) for k, r in targets)
        if args.user:
            ok += restore_user()
        print(f"\nrestored {ok} target(s)")
        return 0 if ok else 1

    written = 0
    for key, root in targets:
        if write_policy(key, root, dry_run=args.dry_run, force=args.force):
            written += 1

    if args.user:
        write_user_policy(dry_run=args.dry_run)

    print(f"\n{written}/{len(targets)} workspace(s) written"
          + (" (dry run)" if args.dry_run else ""))
    if written:
        print("Restart or reload the Kiro window for the new policy to take "
              "effect in already-open sessions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
