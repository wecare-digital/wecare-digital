#!/usr/bin/env python3
"""Watch the Dependabot alerts dismissed because they cannot be fixed here.

Authority: read-only. It reads the committed `amplify/package-lock.json` and, with
`--check-upstream`, public npm registry metadata and tarballs. It holds no credentials, writes
no files and never changes alert state; dismissing or reopening an alert stays a deliberate step
recorded in docs/security-dependabot-triage.md.

Why this exists
---------------
A dismissed alert cannot come back to tell you it became fixable. Worse, a NEW vulnerable copy
of the same package in the same manifest is silently covered by the old dismissal. This script
replaces both missing signals: `--gate` fails when the lockfile facts a dismissal rests on have
moved, and `--check-upstream` answers "is it fixable yet?" on demand.

What it watches (measured 2026-10-25)
-------------------------------------
* 119, `@opentelemetry/core < 2.8.0`, dismissed `inaccurate`. The lockfile records four
  bundled 2.0.0 copies inside data-construct and graphql-api-construct that their tarballs do
  not contain. npm keeps those entries only because `npm ci` demands one for the exact `2.0.0`
  the bundled resources/sdk-trace-base declare (docs/npm-ci-backend-isolation.md); a clean
  `npm ci` installs core 2.8.0 and 2.11.0 and nothing older. The gate fails if a sub-2.8.0 copy
  appears anywhere else or stops being inBundle: either would be a real copy the dismissal hides.
* 120, `zod < 4.6.6`, dismissed `tolerable_risk`. Every copy is 3.x, the only patched line is
  4.6.6+, and the Amplify packages that carry it pin 3.25.17 exactly or bundle it. The gate
  fails if a 4.x copy below 4.6.6 appears (a patch bump would fix that one) or a copy appears
  that the triage never measured.

Retired: `brace-expansion` inside `aws-cdk-lib` (alerts 55/56/57), watched here from 2026-09-30
until `--check-upstream` reported that `aws-cdk-lib` 2.274.0 bundles the patched 5.0.12. The pin
moved on 2026-10-25 and the alerts were reopened so Dependabot could close them as fixed; with
no dismissal in place, nothing here suppresses Dependabot's own reporting if the copy regresses.

Two kinds of finding, and the distinction matters
-------------------------------------------------
A PROBLEM means the reasoning behind a dismissal no longer holds; it fails `--gate`. A NOTICE
means a fact moved without invalidating it - a version bump, including the good one - and does
not. Getting that split wrong is how a gate ends up firing on routine upgrades and then switched
off.

`--check-upstream` (needs network) reads the newest Amplify packages: registry metadata for a
declared requirement, the tarball itself for a bundled copy, because a bundled dependency does
not appear in a package's declared dependency list. The tarball is the authority: the lockfile
records what was requested, the tarball records what shipped.

Usage:
    python3 scripts/check_bundled_advisories.py                  # report
    python3 scripts/check_bundled_advisories.py --gate           # offline, non-zero on drift
    python3 scripts/check_bundled_advisories.py --check-upstream # is it fixable yet?
    python3 scripts/check_bundled_advisories.py --json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AMPLIFY_LOCK = ROOT / "amplify" / "package-lock.json"

#: Alert 119, measured 2026-10-25 and dismissed `inaccurate`. The four phantom paths are
#: lockfile entries only: the measured tarballs (and the then-latest 1.17.8 / 1.22.3) contain no
#: core under resources or sdk-trace-base, and `npm ci` of the committed lockfile installs core
#: 2.8.0 inside each construct and 2.11.0 at the top level.
OTEL_TRIAGED = {
    "alert": 119,
    "package": "@opentelemetry/core",
    "firstSafeVersion": "2.8.0",
    "parents": {
        "node_modules/@aws-amplify/data-construct": "1.17.7",
        "node_modules/@aws-amplify/graphql-api-construct": "1.22.2",
    },
    "phantomPaths": [
        f"node_modules/@aws-amplify/{parent}/node_modules/@opentelemetry/{sub}"
        f"/node_modules/@opentelemetry/core"
        for parent in ("data-construct", "graphql-api-construct")
        for sub in ("resources", "sdk-trace-base")
    ],
}

#: Alert 120, measured 2026-10-25 and dismissed `tolerable_risk`. Every copy the triage
#: measured, all 3.x; any other copy is outside the dismissal and must be triaged on its own.
ZOD_TRIAGED = {
    "alert": 120,
    "package": "zod",
    "firstSafeVersion": "4.6.6",
    "copies": {
        "node_modules/zod": "3.25.17",
        **{
            f"node_modules/@aws-amplify/{parent}/node_modules/{inner}zod": version
            for parent in ("data-construct", "graphql-api-construct")
            for inner, version in (
                ("", "3.24.2"),
                ("@aws-amplify/backend-output-schemas/node_modules/", "3.25.17"),
                ("@aws-amplify/platform-core/node_modules/", "3.25.17"),
            )
        },
    },
    #: Whose declared zod requirement decides whether a fixed version can be installed at all.
    "requiredBy": [
        "@aws-amplify/backend-cli",
        "@aws-amplify/backend-output-schemas",
        "@aws-amplify/cli-core",
        "@aws-amplify/client-config",
        "@aws-amplify/deployed-backend-client",
        "@aws-amplify/platform-core",
    ],
    #: Whose tarball ships its own zod, which no override or requirement change can reach.
    "bundledBy": ["@aws-amplify/data-construct", "@aws-amplify/graphql-api-construct"],
}


def parse_version(value: str) -> tuple[int, ...]:
    """`5.0.9` -> `(5, 0, 9)`. Non-numeric parts are dropped rather than raising."""
    return tuple(int(part) for part in re.findall(r"\d+", value or ""))


def below(version: str, first_safe: str) -> bool:
    return parse_version(version) < parse_version(first_safe)


def load_packages() -> dict:
    """The `packages` map of the committed amplify lockfile."""
    lock = json.loads(AMPLIFY_LOCK.read_text(encoding="utf-8"))
    return lock.get("packages", {})


def lock_copies(packages: dict, name: str) -> dict[str, str]:
    """Every versioned lockfile copy of `name`, keyed by its install path."""
    suffix = f"node_modules/{name}"
    return {path: meta["version"] for path, meta in packages.items()
            if meta.get("version") and (path == suffix or path.endswith(f"/{suffix}"))}


def check_otel(packages: dict) -> tuple[dict, list[str], list[str]]:
    """Alert 119: is every sub-2.8.0 core copy still one of the four lockfile-only entries?"""
    triaged = OTEL_TRIAGED
    alert, safe = triaged["alert"], triaged["firstSafeVersion"]
    copies = lock_copies(packages, triaged["package"])
    vulnerable = {path: version for path, version in copies.items() if below(version, safe)}
    problems: list[str] = []
    notices: list[str] = []

    for path, version in sorted(vulnerable.items()):
        if path not in triaged["phantomPaths"]:
            problems.append(
                f"@opentelemetry/core {version} at {path} is not one of the lockfile-only "
                f"entries alert {alert} was dismissed for. It is a real copy and the "
                f"`inaccurate` dismissal would hide it.")
        elif not packages[path].get("inBundle"):
            problems.append(
                f"{path} is no longer inBundle, so npm would now fetch and install core "
                f"{version}. The 'lockfile only' evidence for alert {alert} no longer holds.")

    for parent, measured in triaged["parents"].items():
        current = (packages.get(parent) or {}).get("version")
        if current != measured:
            notices.append(
                f"{parent.removeprefix('node_modules/')} is now {current}, not the {measured} "
                f"whose tarball was measured. Re-run --check-upstream before citing alert "
                f"{alert}'s evidence again.")

    if not vulnerable:
        notices.append(
            f"no @opentelemetry/core copy below {safe} remains in the lockfile, so alert "
            f"{alert}'s phantom entries are gone and this watch can be deleted.")
    return {"copies": copies, "vulnerable": vulnerable}, problems, notices


def check_zod(packages: dict) -> tuple[dict, list[str], list[str]]:
    """Alert 120: is every zod copy still a measured 3.x copy with no reachable fix?"""
    triaged = ZOD_TRIAGED
    alert, safe = triaged["alert"], triaged["firstSafeVersion"]
    copies = lock_copies(packages, triaged["package"])
    vulnerable = {path: version for path, version in copies.items() if below(version, safe)}
    problems: list[str] = []
    notices: list[str] = []

    for path, version in sorted(vulnerable.items()):
        if parse_version(version)[:1] >= (4,):
            # The patched release is in the same major, so this copy IS fixable.
            problems.append(
                f"zod {version} at {path} is 4.x below {safe}. A patch bump fixes it, so the "
                f"`tolerable_risk` dismissal of alert {alert} does not cover it.")
        elif path not in triaged["copies"]:
            problems.append(
                f"zod {version} at {path} was never measured by the triage of alert {alert}; "
                f"its reachability argument has not been made for this copy.")
        elif version != triaged["copies"][path]:
            notices.append(
                f"zod at {path} moved {triaged['copies'][path]} -> {version}. Still 3.x and "
                f"still affected; update ZOD_TRIAGED.")

    for path in sorted(set(triaged["copies"]) - set(copies)):
        notices.append(f"the triaged zod copy {path} is gone from the lockfile.")

    if copies and not vulnerable:
        notices.append(
            f"every zod copy is now >= {safe}, which CLEARS alert {alert}. Undo its dismissal "
            f"or let Dependabot close it, and delete this watch.")
    return {"copies": copies, "vulnerable": vulnerable}, problems, notices


def npm_view(spec: str, *fields: str) -> dict:
    """`npm view <spec> <fields> --json`, always as a {field: value} mapping."""
    result = subprocess.run(["npm", "view", spec, *fields, "--json"],
                            capture_output=True, text=True, check=True, timeout=120)
    data = json.loads(result.stdout or "null")
    return {fields[0]: data} if len(fields) == 1 else (data or {})


def bundled_copies(spec: str, names: tuple[str, ...]) -> dict[str, str]:
    """Every copy of `names` shipped inside the tarball for `spec`, keyed by path."""
    tarball = npm_view(spec, "dist.tarball")["dist.tarball"]
    with urllib.request.urlopen(tarball, timeout=180) as response:
        blob = response.read()
    alternatives = "|".join(re.escape(name) for name in names)
    pattern = re.compile(rf"^package/((?:.*/)?node_modules/(?:{alternatives}))/package\.json$")
    found: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive.getmembers():
            match = pattern.match(member.name)
            handle = archive.extractfile(member) if match else None
            if match and handle is not None:
                found[match.group(1)] = json.loads(handle.read().decode("utf-8")).get("version")
    return found


def upstream_amplify() -> dict:
    """Do the newest Amplify packages still keep zod and core where the triage found them?"""
    try:
        requirements: dict[str, str] = {}
        for name in ZOD_TRIAGED["requiredBy"]:
            meta = npm_view(f"{name}@latest", "version", "dependencies", "peerDependencies")
            declared = {**(meta.get("peerDependencies") or {}), **(meta.get("dependencies") or {})}
            requirements[f"{name}@{meta.get('version')}"] = declared.get("zod", "")
        bundled: dict[str, dict[str, str]] = {}
        for name in ZOD_TRIAGED["bundledBy"]:
            version = npm_view(f"{name}@latest", "version")["version"]
            bundled[f"{name}@{version}"] = bundled_copies(
                f"{name}@{version}", ("zod", "@opentelemetry/core"))
    except (subprocess.SubprocessError, OSError, ValueError, tarfile.TarError) as exc:
        return {"error": f"could not read the Amplify packages: {type(exc).__name__}"}

    # Only a plain 3.x requirement is treated as blocking; anything more complex is printed
    # for a human to read rather than guessed at.
    still_3x = sorted(name for name, spec in requirements.items()
                      if re.fullmatch(r"[\^~]?3(\.\d+){0,2}", spec.strip()))
    bundled_zod = {f"{owner}:{path}": version for owner, copies in bundled.items()
                   for path, version in copies.items() if path.endswith("node_modules/zod")}
    bundled_core = {f"{owner}:{path}": version for owner, copies in bundled.items()
                    for path, version in copies.items()
                    if path.endswith("node_modules/@opentelemetry/core")}
    return {
        "zodRequirements": requirements,
        "zodRequiredAs3x": still_3x,
        "bundledZod": bundled_zod,
        "bundledCore": bundled_core,
        "zodFixAvailable": not still_3x and all(
            not below(v, ZOD_TRIAGED["firstSafeVersion"]) for v in bundled_zod.values()),
        "coreBelowSafe": {k: v for k, v in bundled_core.items()
                          if below(v, OTEL_TRIAGED["firstSafeVersion"])},
    }


def print_copies(title: str, result: dict, expected: list[str] | dict[str, str],
                 expected_mark: str) -> None:
    print(title)
    print("=" * 72)
    for path, version in sorted(result["copies"].items()):
        if path not in result["vulnerable"]:
            mark = "ok        "
        elif path in expected:
            mark = expected_mark
        else:
            mark = "VULNERABLE"
        print(f"    {mark} {version:10s} {path}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gate", action="store_true",
                        help="offline; non-zero when the triaged facts have moved")
    parser.add_argument("--check-upstream", action="store_true",
                        help="read the latest Amplify packages from npm and report whether a "
                             "fix exists")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if not AMPLIFY_LOCK.exists():
        print(f"ERROR: {AMPLIFY_LOCK.relative_to(ROOT)} not found", file=sys.stderr)
        return 2

    packages = load_packages()
    otel, otel_problems, otel_notices = check_otel(packages)
    zod, zod_problems, zod_notices = check_zod(packages)
    problems = otel_problems + zod_problems
    notices = otel_notices + zod_notices
    report: dict = {
        "triaged": {str(OTEL_TRIAGED["alert"]): OTEL_TRIAGED, str(ZOD_TRIAGED["alert"]): ZOD_TRIAGED},
        "watches": {str(OTEL_TRIAGED["alert"]): otel, str(ZOD_TRIAGED["alert"]): zod},
    }

    upstream: dict = {}
    if args.check_upstream:
        upstream = upstream_amplify()
        report["upstream"] = upstream
        if upstream.get("error"):
            notices.append(f"upstream check failed: {upstream['error']}")
        else:
            if upstream["zodFixAvailable"]:
                notices.append(
                    f"A ZOD FIX MAY BE AVAILABLE: no latest Amplify package requires plain 3.x "
                    f"and every bundled copy is >= {ZOD_TRIAGED['firstSafeVersion']}. Read the "
                    f"requirements below, bump amplify/package.json, regenerate the lockfile "
                    f"and undo the dismissal of alert {ZOD_TRIAGED['alert']}.")
            if upstream["coreBelowSafe"]:
                notices.append(
                    f"the latest Amplify constructs bundle @opentelemetry/core below "
                    f"{OTEL_TRIAGED['firstSafeVersion']}: {upstream['coreBelowSafe']}. "
                    f"Upgrading to them would make alert {OTEL_TRIAGED['alert']} real.")

    report["problems"] = problems
    report["notices"] = notices

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print_copies(f"ALERT {OTEL_TRIAGED['alert']} - @opentelemetry/core < "
                     f"{OTEL_TRIAGED['firstSafeVersion']} (dismissed inaccurate)",
                     otel, OTEL_TRIAGED["phantomPaths"], "LOCK-ONLY ")
        print_copies(f"ALERT {ZOD_TRIAGED['alert']} - zod < {ZOD_TRIAGED['firstSafeVersion']} "
                     f"(dismissed tolerable_risk)", zod, ZOD_TRIAGED["copies"], "TRIAGED   ")
        if args.check_upstream:
            if upstream.get("error"):
                print(f"  upstream: {upstream['error']}")
            else:
                print("  latest Amplify zod requirements:")
                for name, spec in sorted(upstream["zodRequirements"].items()):
                    print(f"    {spec or '-':12s} {name}")
                print("  bundled in the latest constructs:")
                for path, version in sorted({**upstream["bundledZod"],
                                             **upstream["bundledCore"]}.items()):
                    print(f"    {version:12s} {path}")
                print(f"  ZOD FIX AVAILABLE       : {upstream['zodFixAvailable']}")
        if notices:
            print("\n  NOTICES")
            for notice in notices:
                print(f"    - {notice}")
        if problems:
            print("\n  PROBLEMS")
            for problem in problems:
                print(f"    - {problem}")

    if args.gate:
        if problems:
            print("\nGATE FAILED - the facts a dismissal rests on have changed", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            print("\nRe-read docs/security-dependabot-triage.md and update both it and the "
                  "TRIAGED tables in this script.", file=sys.stderr)
            return 1
        print("\nGATE PASSED - still the situation that was triaged; nothing new is reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
