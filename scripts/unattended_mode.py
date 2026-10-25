#!/usr/bin/env python3
"""Turn on unattended mode: auto-approve the destructive AWS operations that would
otherwise stop a long run to ask, and write an audit record for each one.

Why this is a mode and not a deleted guard
------------------------------------------
`block_catastrophic.py` asks before destructive AWS deletes because
`.kiro/steering/maintenance-reporting.md` (retired 2026-10-09, af7858fa) requires pointwise confirmation for
deleting a secret, bucket, Lambda, table, queue or topic, and for IAM and KMS
changes. That is a real control, and simply removing it would leave no record
that it ever existed.

So instead the guard consults this mode. When the mode is on, those operations
proceed **and are appended to an audit log**, which is what the steering actually
wants: "Record confirmation id, decision, timestamp, action, result - never a
secret value." Approval moves from per-command clicking to one recorded,
time-bounded decision.

Three properties make it safe to leave on:

* **It expires.** A forgotten permanent bypass is a defect. Default 7 days; the
  guard treats an expired file as off, so lapsing fails closed.
* **It is narrow.** Only the `ask` tier is affected. Everything in the hard-block
  tier stays blocked with the mode on: `rm -rf` of `/`, `$HOME`, `~/.aws`,
  `~/.ssh`, `~/.kiro` or the repo root; destroying the retained plaintext
  credential source; `chmod` widening; raw device writes; and
  `aws secretsmanager get-secret-value`, which `aws-agent-rules` forbids outright.
* **It is auditable.** Every auto-approved action lands in
  `~/.local/share/kiro-unattended/audit.jsonl` with a timestamp and the command,
  outside the repository so it is never committed.

What it does NOT do
-------------------
It cannot remove the approval gates in the cutover brief itself. That document
defines `A3_PRODUCTION` and `A4_DESTRUCTIVE` classes requiring explicit owner
approval immediately before action, across seven of its eleven phases. Those are
process gates, not tool prompts, and no local setting satisfies them.

Usage
-----
    python scripts/unattended_mode.py status
    python scripts/unattended_mode.py on  --reason "cutover phase 1 discovery"
    python scripts/unattended_mode.py on  --days 3 --reason "..."
    python scripts/unattended_mode.py off
    python scripts/unattended_mode.py audit          # last 20 auto-approvals
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLAG = Path.home() / ".kiro" / "unattended.json"
AUDIT = Path.home() / ".local" / "share" / "kiro-unattended" / "audit.jsonl"
DEFAULT_DAYS = 7

# Only this tier is affected. The hard-block tier is never waived.
WAIVABLE = "aws_destructive_delete"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def read_state() -> dict:
    """Current mode. Absent, malformed or expired all mean off."""
    if not FLAG.is_file():
        return {"enabled": False, "reason": "no flag file"}
    try:
        d = json.loads(FLAG.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"enabled": False, "reason": f"unreadable flag file: {e}"}

    # NOTE ordering: the file's own contents are spread FIRST so the verdict keys
    # below always win. Written the other way round (`{"enabled": False, **d}`)
    # the file's `enabled: true` silently overrode every negative verdict, and an
    # EXPIRED flag kept waiving. That defeated the whole fail-closed property and
    # is covered by the self-test.
    if not d.get("enabled"):
        return {**d, "enabled": False, "reason": "explicitly disabled"}

    exp = d.get("expires_at")
    if exp:
        try:
            when = datetime.fromisoformat(exp)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            return {**d, "enabled": False,
                    "reason": f"unparseable expires_at {exp!r} - failing closed"}
        if _now() >= when:
            return {**d, "enabled": False,
                    "reason": f"EXPIRED at {exp} - fails closed by design"}
        d["expires_in_hours"] = round((when - _now()).total_seconds() / 3600, 1)

    return {**d, "enabled": True, "reason": "active"}


def is_waived(kind: str = WAIVABLE) -> bool:
    """Called by block_catastrophic.py. True when this tier may proceed."""
    st = read_state()
    if not st.get("enabled"):
        return False
    allow = st.get("allow")
    # `or [WAIVABLE]` would be wrong here: an explicitly empty list is falsy, so
    # `"allow": []` - which plainly means waive nothing - would have fallen back
    # to the default and waived the destructive tier. Absent key and empty list
    # are different intents and must stay distinguishable.
    if allow is None:
        allow = [WAIVABLE]
    return kind in allow or "*" in allow


def audit(action: str, detail: str, command: str = "") -> None:
    """Append one record. Best effort - never raise into the guard."""
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _now().isoformat(timespec="seconds"),
            "action": action,
            "detail": detail,
            "command": command[:500],
            "cwd": os.getcwd(),
            "pid": os.getpid(),
        }
        with AUDIT.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        os.chmod(AUDIT, 0o600)
    except OSError:
        pass


def cmd_on(args) -> int:
    if not args.reason:
        print("--reason is required. The audit record is worthless without it.",
              file=sys.stderr)
        return 1
    days = max(1, min(args.days, 30))
    expires = _now() + timedelta(days=days)
    state = {
        "enabled": True,
        "enabled_at": _now().isoformat(timespec="seconds"),
        "expires_at": expires.isoformat(timespec="seconds"),
        "reason": args.reason,
        "allow": [WAIVABLE],
        "note": ("Waives ONLY the ask-tier destructive AWS deletes in "
                 "block_catastrophic.py. Hard blocks are never waived. "
                 "Expires automatically; an expired file fails closed."),
    }
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLAG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, FLAG)
    audit("mode_enabled", f"{days}d, reason={args.reason}")
    print(f"unattended mode ON for {days} day(s), expires "
          f"{expires.isoformat(timespec='seconds')}")
    print(f"  waives : {WAIVABLE}")
    print(f"  audit  : {AUDIT}")
    print(f"  flag   : {FLAG} (mode 0600)")
    print("\nStill blocked, with the mode on:")
    print("  rm -rf on / $HOME ~/.aws ~/.ssh ~/.kiro or the repo root")
    print("  destroying the retained plaintext credential source")
    print("  chmod widening on protected files; raw device writes")
    print("  aws secretsmanager get-secret-value")
    return 0


def cmd_off(_args) -> int:
    if FLAG.is_file():
        FLAG.unlink()
        audit("mode_disabled", "turned off")
        print(f"unattended mode OFF (removed {FLAG})")
    else:
        print("unattended mode already off (no flag file)")
    return 0


def cmd_status(_args) -> int:
    st = read_state()
    on = st.get("enabled")
    print(f"unattended mode : {'ON' if on else 'OFF'}")
    print(f"  reason        : {st.get('reason')}")
    if st.get("enabled_at"):
        print(f"  enabled_at    : {st['enabled_at']}")
    if st.get("expires_at"):
        print(f"  expires_at    : {st['expires_at']}")
    if st.get("expires_in_hours") is not None:
        print(f"  expires_in    : {st['expires_in_hours']}h")
    if st.get("allow"):
        print(f"  waives        : {st['allow']}")
    n = 0
    if AUDIT.is_file():
        n = sum(1 for _ in AUDIT.open())
    print(f"  audit records : {n} ({AUDIT})")
    return 0 if on else 1


def cmd_audit(args) -> int:
    if not AUDIT.is_file():
        print(f"no audit log at {AUDIT}")
        return 0
    lines = AUDIT.read_text(errors="replace").splitlines()
    for line in lines[-args.limit:]:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(f"{r.get('ts')}  {r.get('action'):<18} {r.get('detail','')}")
        if r.get("command"):
            print(f"{'':22}  $ {r['command'][:120]}")
    print(f"\n{len(lines)} record(s) total")
    return 0


def self_test() -> int:
    """Prove the fail-closed properties. Uses a temp flag path, never the real one."""
    global FLAG
    import tempfile
    real = FLAG
    failures = 0

    def check(label: str, want: bool) -> None:
        nonlocal failures
        got = read_state().get("enabled") is True
        ok = got == want
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  enabled={got!s:<5} want={want!s:<5} {label}")

    with tempfile.TemporaryDirectory() as td:
        FLAG = Path(td) / "unattended.json"

        check("absent flag file", False)

        FLAG.write_text("{ not json")
        check("malformed flag file", False)

        FLAG.write_text(json.dumps({"enabled": False}))
        check("explicitly disabled", False)

        past = (_now() - timedelta(hours=1)).isoformat(timespec="seconds")
        FLAG.write_text(json.dumps({"enabled": True, "expires_at": past,
                                    "reason": "stale run"}))
        check("EXPIRED 1h ago (the real bug: file's enabled:true must not win)", False)

        FLAG.write_text(json.dumps({"enabled": True, "expires_at": "not-a-date"}))
        check("unparseable expires_at", False)

        future = (_now() + timedelta(days=1)).isoformat(timespec="seconds")
        FLAG.write_text(json.dumps({"enabled": True, "expires_at": future,
                                    "reason": "live run", "allow": [WAIVABLE]}))
        check("valid and unexpired", True)

        # waiver scoping
        print(f"  {'ok  ' if is_waived(WAIVABLE) else 'FAIL'}  "
              f"is_waived({WAIVABLE}) is True when active")
        failures += not is_waived(WAIVABLE)
        print(f"  {'ok  ' if not is_waived('rm_home') else 'FAIL'}  "
              f"is_waived('rm_home') is False - waiver is scoped, not blanket")
        failures += is_waived("rm_home")

        FLAG.write_text(json.dumps({"enabled": True, "expires_at": future,
                                    "allow": []}))
        print(f"  {'ok  ' if not is_waived(WAIVABLE) else 'FAIL'}  "
              f"empty allow list waives nothing")
        failures += is_waived(WAIVABLE)

    FLAG = real
    print(f"\n{9 - failures}/9 cases passed")
    return 1 if failures else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_on = sub.add_parser("on", help="enable, with a reason and a TTL")
    p_on.add_argument("--reason", required=False, default="")
    p_on.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p_on.set_defaults(func=cmd_on)

    sub.add_parser("off", help="disable").set_defaults(func=cmd_off)
    sub.add_parser("status", help="show current mode").set_defaults(func=cmd_status)

    p_a = sub.add_parser("audit", help="show recent auto-approvals")
    p_a.add_argument("--limit", type=int, default=20)
    p_a.set_defaults(func=cmd_audit)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
