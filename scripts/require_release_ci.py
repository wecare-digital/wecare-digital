#!/usr/bin/env python3
"""Fail closed unless the production push's GitHub Verify job passed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO = "wecare-digital/wecare-digital"
BRANCH = "wecare.digital"
API = f"https://api.github.com/repos/{REPO}/actions"
WORKFLOW = ".github/workflows/ci.yml"
JOB = "Verify (typecheck, lint, test)"


class ReleaseGateError(RuntimeError):
    pass


def _json(path: str) -> dict:
    request = Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "wecare-release-gate",
    })
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ReleaseGateError("Unexpected response from GitHub Actions")
    return result


def check_release(commit: str, *, read=_json) -> dict | None:
    """Return exact successful evidence, None if pending, or raise on failure."""
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ReleaseGateError("A full lowercase Git commit SHA is required")
    filters = urlencode({"branch": BRANCH, "event": "push", "head_sha": commit, "per_page": 20})
    runs = read(f"/workflows/ci.yml/runs?{filters}").get("workflow_runs")
    if not isinstance(runs, list):
        raise ReleaseGateError("GitHub did not return workflow runs")
    exact = [run for run in runs if run.get("head_sha") == commit
             and run.get("head_branch") == BRANCH and run.get("event") == "push"
             and run.get("path", "").split("@", 1)[0] == WORKFLOW]
    if not exact:
        return None
    run = max(exact, key=lambda record: int(record["id"]))
    if run.get("status") != "completed":
        return None
    if run.get("conclusion") != "success":
        raise ReleaseGateError(f"Production CI run {run['id']} did not pass: {run.get('conclusion')}")
    attempt = int(run["run_attempt"])
    jobs = read(f"/runs/{int(run['id'])}/attempts/{attempt}/jobs?per_page=100").get("jobs")
    if not isinstance(jobs, list):
        raise ReleaseGateError("GitHub did not return the run attempt's jobs")
    verify = [job for job in jobs if job.get("name") == JOB]
    if len(verify) != 1 or verify[0].get("head_sha") != commit or (
        verify[0].get("status"), verify[0].get("conclusion")
    ) != ("completed", "success"):
        raise ReleaseGateError(f"Exact successful Verify job absent from CI run {run['id']}")
    return {"commit": commit, "branch": BRANCH, "runId": run["id"], "runAttempt": attempt,
            "jobId": verify[0]["id"]}


def wait_for_release(commit: str, wait_seconds: int) -> dict:
    deadline = time.monotonic() + wait_seconds
    while True:
        evidence = check_release(commit)
        if evidence:
            return evidence
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReleaseGateError(f"Verified production CI is not available for {commit}")
        time.sleep(min(15, remaining))


def clean_checkout_commit(root: Path) -> str:
    """Bind local publish artifacts to a clean checkout, never an unproven archive."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root.resolve():
            raise ReleaseGateError("Run from the root of a clean repository checkout")
        if git("status", "--porcelain=v1", "--untracked-files=normal"):
            raise ReleaseGateError("Commit or isolate local changes before releasing")
        return git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseGateError("A clean Git checkout is required for production release") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds must be between 0 and 600")
    try:
        print(json.dumps(wait_for_release(args.commit, args.wait_seconds), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, ReleaseGateError) as exc:
        parser.exit(1, f"Release blocked: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
