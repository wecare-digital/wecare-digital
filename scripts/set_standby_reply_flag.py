"""Move `STANDBY_REPLY_ENABLED` on `wecare-inbound-whatsapp`, preserving every other key.

What this is for
----------------
`amplify/functions/messaging/inbound-whatsapp-handler/handler.py` ships the standby
suppression fix OFF: `_standby_reply_enabled()` defaults to `'true'`, which is the
behaviour that was already live. Activating the fix is **one environment variable going
from ABSENT to the literal string `false`**. No code and no in-code default move, which is
why rollback here is `--state absent`, not an `update-function-code`.

The hazard this script exists to remove
---------------------------------------
`UpdateFunctionConfiguration` **REPLACES** `Environment.Variables` wholesale — the same
replace-not-patch shape as `UpdateUserPool`. The function carries several keys that inbound
WhatsApp cannot work without. Writing a one-key map would not error; it would silently
drop the rest. So this reads the whole map, changes exactly one key, writes the whole map
back, and **refuses** to write unless the resulting key set is exactly
`current | {flag}` (for `true`/`false`) or `current - {flag}` (for `absent`).

Why a committed script rather than inline boto3
-----------------------------------------------
It makes the rollback a single reviewed command instead of retyped boto3 against a live
production function, and it makes the env-preservation property unit-testable without
touching AWS (`tests/test_set_standby_reply_flag.py`).

Secret hygiene
--------------
`STANDBY_REPLY_ENABLED` is a non-secret feature flag and is the ONLY value this script
ever prints. Every other environment key is reported by NAME and count only. Nothing is
ever passed on a command line.

Deploy note
-----------
`wecare-whatsapp-calling` and `wecare-messages-delete` invoke this function UNQUALIFIED,
so `$LATEST` is production: the change is live as soon as the update settles, before any
alias move. Run `scripts/snapstart_publish.py wecare-inbound-whatsapp` afterwards so the
alias-based integrations carry the same configuration.

Usage:
    .venv/bin/python scripts/set_standby_reply_flag.py --verify
    .venv/bin/python scripts/set_standby_reply_flag.py --state false --dry-run
    .venv/bin/python scripts/set_standby_reply_flag.py --state false --apply
    .venv/bin/python scripts/set_standby_reply_flag.py --state absent --apply   # rollback
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import boto3

REGION = "us-east-1"
FUNCTION_NAME = "wecare-inbound-whatsapp"
LIVE_ALIAS = "live"
FLAG = "STANDBY_REPLY_ENABLED"

#: The literal strings `_standby_reply_enabled()` treats as OFF, after `.strip().lower()`.
#: Anything else — including a typo — reads as TRUE, so `--state false` must write exactly
#: `false`. Pinned against the handler itself by tests/test_set_standby_reply_flag.py.
OFF_VALUE = "false"
ON_VALUE = "true"

_client = None


def lam():
    global _client
    if _client is None:
        _client = boto3.client("lambda", region_name=REGION)
    return _client


def _config(qualifier: str | None = None) -> dict:
    kwargs = {"FunctionName": FUNCTION_NAME}
    if qualifier:
        kwargs["Qualifier"] = qualifier
    return lam().get_function_configuration(**kwargs)


def _env(config: dict) -> dict:
    return dict((config.get("Environment") or {}).get("Variables") or {})


def _flag_of(env: dict):
    """The flag's current value, or None when absent."""
    return env.get(FLAG)


def _describe(label: str, config: dict) -> dict:
    """Print the safe fields for one qualifier and return them as a dict.

    Prints the flag's value (non-secret) plus env key NAMES. Never any other value.
    """
    env = _env(config)
    names = sorted(env)
    flag = _flag_of(env)
    print(f"{label}:")
    print(f"  version      {config.get('Version')}")
    print(f"  CodeSha256   {config.get('CodeSha256')}")
    print(f"  {FLAG} {flag!r}" if flag is not None else f"  {FLAG} <absent>")
    print(f"  env keys     {len(names)}: {', '.join(names)}")
    return {
        "version": config.get("Version"),
        "codeSha256": config.get("CodeSha256"),
        "flag": flag,
        "envKeyNames": names,
        "envKeyCount": len(names),
    }


def _live_version() -> str:
    return lam().get_alias(FunctionName=FUNCTION_NAME, Name=LIVE_ALIAS)["FunctionVersion"]


def verify(snapshot_path: str | None = None) -> int:
    """Read-only report of `$LATEST` and the `live` alias version."""
    print(f"region: {REGION}\nfunction: {FUNCTION_NAME}\n")
    latest = _describe("$LATEST", _config())
    live_version = _live_version()
    live = _describe(f"live alias -> v{live_version}", _config(live_version))

    print()
    if latest["codeSha256"] == live["codeSha256"]:
        print(f"code agrees: live v{live_version} CodeSha256 == $LATEST")
    else:
        print(f"WARNING live v{live_version} CodeSha256 differs from $LATEST")
    if latest["flag"] == live["flag"]:
        if latest["flag"] is None:
            print(f"{FLAG} absent at both (code default {ON_VALUE!r} in force)")
        else:
            print(f"{FLAG} agrees at both: {latest['flag']!r}")
    else:
        print(f"WARNING {FLAG} differs: $LATEST {latest['flag']!r} vs "
              f"live {live['flag']!r} - publish a version and move the alias")

    if snapshot_path:
        payload = {
            "functionName": FUNCTION_NAME,
            "region": REGION,
            "liveAliasVersion": live_version,
            "latestCodeSha256": latest["codeSha256"],
            "liveCodeSha256": live["codeSha256"],
            "envKeyNames": latest["envKeyNames"],
            "envKeyCount": latest["envKeyCount"],
            "standbyReplyEnabled": latest["flag"],
            "capturedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rollback": (
                f"{FLAG} back to its captured state with "
                f"`scripts/set_standby_reply_flag.py --state "
                f"{'absent' if latest['flag'] is None else latest['flag']} --apply`, then "
                f"`scripts/snapstart_publish.py {FUNCTION_NAME}`. "
                f"Code is NOT rolled back: v{live_version} carries the intended code."
            ),
        }
        with open(snapshot_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"\nwrote snapshot {snapshot_path}")
    return 0


def _wanted_env(current: dict, state: str) -> dict:
    wanted = dict(current)
    if state == "absent":
        wanted.pop(FLAG, None)
    else:
        wanted[FLAG] = OFF_VALUE if state == "false" else ON_VALUE
    return wanted


def _refuse_unless_only_the_flag_moved(current: dict, wanted: dict, state: str) -> list:
    """The one failure mode that matters is dropping another key. Catch it before writing."""
    problems = []
    expected_keys = set(current) - {FLAG} if state == "absent" else set(current) | {FLAG}
    if set(wanted) != expected_keys:
        problems.append(
            f"resulting key set is not the expected one: "
            f"missing {sorted(expected_keys - set(wanted))}, "
            f"unexpected {sorted(set(wanted) - expected_keys)}")
    for key in sorted(set(current) - {FLAG}):
        if wanted.get(key) != current.get(key):
            problems.append(f"value of preserved key {key} would change")
    return problems


def apply(state: str, dry_run: bool) -> int:
    print(f"region: {REGION}\nfunction: {FUNCTION_NAME}\ntarget state: {FLAG}="
          f"{'<absent>' if state == 'absent' else (OFF_VALUE if state == 'false' else ON_VALUE)}\n")
    config = _config()
    current = _env(config)
    wanted = _wanted_env(current, state)

    problems = _refuse_unless_only_the_flag_moved(current, wanted, state)
    if problems:
        print("REFUSED - the write would change more than the flag:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    before = _flag_of(current)
    after = _flag_of(wanted)
    print(f"  {FLAG}: {'<absent>' if before is None else repr(before)} -> "
          f"{'<absent>' if after is None else repr(after)}")
    print(f"  env keys: {len(current)} -> {len(wanted)}")
    preserved = sorted(set(current) - {FLAG})
    print(f"  preserved unchanged ({len(preserved)}): {', '.join(preserved)}")

    if before == after:
        print("\nalready in the target state: nothing to do")
        return 0
    if dry_run:
        print("\ndry run: nothing changed "
              "(pass --apply to write)")
        return 0

    lam().update_function_configuration(
        FunctionName=FUNCTION_NAME, Environment={"Variables": wanted})
    lam().get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
    print(f"\nwrote {FLAG}="
          f"{'<absent>' if after is None else after} on $LATEST")
    print("\n$LATEST is production for the unqualified callers "
          "(wecare-whatsapp-calling, wecare-messages-delete).")
    print(f"Next: .venv/bin/python scripts/snapstart_publish.py {FUNCTION_NAME}")
    print("\nread-back verification:\n")
    return verify()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=["false", "true", "absent"],
                        help=f"target state for {FLAG}; `absent` removes the key, which is "
                             f"the preferred rollback because it leaves the default in "
                             f"exactly one place (the code)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; dry run is the default")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicit no-op write (the default behaviour)")
    parser.add_argument("--verify", action="store_true",
                        help="read-only report of $LATEST and the live alias version")
    parser.add_argument("--snapshot", metavar="PATH",
                        help="with --verify, also write the rollback snapshot JSON "
                             "(env key NAMES only, never other values)")
    args = parser.parse_args(argv)

    if args.verify:
        return verify(args.snapshot)
    if not args.state:
        parser.error("--state is required unless --verify is given")
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    return apply(args.state, dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
