#!/usr/bin/env python3
"""Fail closed unless the production push's GitHub Verify job passed."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from shutil import copyfileobj
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPO = "wecare-digital/wecare-digital"
BRANCH = "wecare.digital"
API = f"https://api.github.com/repos/{REPO}/actions"
WORKFLOW = ".github/workflows/ci.yml"
JOB = "Verify (typecheck, lint, test)"


class ReleaseGateError(RuntimeError):
    pass


class RateLimitedError(ReleaseGateError):
    def __init__(self, retry_seconds: float | None = None):
        super().__init__("GitHub Actions API rate limited the gate; retry after it resets "
                         "or configure the scoped Actions-read token")
        self.retry_seconds = retry_seconds


def rate_limit_delay(headers) -> float | None:
    """Respect GitHub's provider headers; never retry before the primary reset."""
    delays = []
    retry = headers.get("Retry-After", "")
    if retry.isdigit():
        delays.append(float(retry))
    reset = headers.get("X-RateLimit-Reset", "")
    if headers.get("X-RateLimit-Remaining") == "0" and reset.isdigit():
        delays.append(max(1.0, float(reset) - time.time() + 1))
    return max(1.0, *delays) if delays else None


class _NoRedirect(HTTPRedirectHandler):
    # Never forward the optional Actions-read credential to another origin.
    def redirect_request(self, *_args, **_kwargs):
        return None


def _json(path: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "wecare-release-gate",
    }
    token = os.environ.get("WECARE_GITHUB_ACTIONS_READ_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(API + path, headers=headers)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 429 or exc.headers.get("X-RateLimit-Remaining") == "0" or (
            exc.code == 403 and exc.headers.get("Retry-After")
        ):
            raise RateLimitedError(rate_limit_delay(exc.headers)) from None
        raise ReleaseGateError(f"GitHub Actions API could not verify release (HTTP {exc.code})") from None
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
    rate_attempts = 0
    while True:
        delay = 30.0
        try:
            evidence = check_release(commit)
            if evidence:
                return evidence
            rate_attempts = 0
        except RateLimitedError as exc:
            rate_attempts += 1
            delay = exc.retry_seconds or min(60 * 2 ** min(rate_attempts - 1, 4), 900)
            remaining = deadline - time.monotonic()
            if remaining < delay:
                raise ReleaseGateError(
                    f"GitHub Actions API rate limited the gate; retry in {int(delay) + 1}s "
                    "(outside this build's remaining wait budget)"
                ) from None
            print(f"GitHub CI gate rate limited; waiting {int(delay) + 1}s before retry.", flush=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReleaseGateError(f"Verified production CI is not available for {commit}")
        # Short sleep chunks keep the process responsive without querying GitHub early.
        next_read = time.monotonic() + min(delay, remaining)
        while True:
            pause = min(30, next_read - time.monotonic())
            if pause <= 0:
                break
            time.sleep(pause)


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


@contextmanager
def committed_function_sources(root: Path, commit: str, extra_paths=()):
    """Yield a private snapshot of regular function files from the verified commit."""
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ReleaseGateError("A full lowercase Git commit SHA is required")
    paths = tuple(Path(name) for name in ("amplify/functions", *extra_paths))
    if any(path.is_absolute() or not path.parts or ".." in path.parts for path in paths):
        raise ReleaseGateError("Function package inputs must stay within the repository")
    with tempfile.TemporaryDirectory(prefix="wecare-verified-source-") as tmp:
        snapshot = Path(tmp).resolve()
        with tempfile.TemporaryFile() as archive:
            try:
                subprocess.run(
                    ["git", "-C", str(root), "archive", "--format=tar", commit,
                     "--", *(path.as_posix() for path in paths)], stdout=archive, check=True,
                )
            except subprocess.CalledProcessError as exc:
                raise ReleaseGateError("Could not export the verified function sources") from exc
            archive.seek(0)
            with tarfile.open(fileobj=archive, mode="r:") as files:
                for entry in files:
                    rel = Path(entry.name)
                    if (rel.is_absolute() or ".." in rel.parts
                            or not (entry.isdir() or entry.isreg())
                            or not any(rel.is_relative_to(path)
                                       or (entry.isdir() and path.is_relative_to(rel))
                                       for path in paths)):
                        raise ReleaseGateError("Unexpected path or file type in function source export")
                    target = snapshot / rel
                    if entry.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with files.extractfile(entry) as source, target.open("xb") as destination:
                            copyfileobj(source, destination)
        yield snapshot / "amplify" / "functions"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 3000:
        parser.error("--wait-seconds must be between 0 and 3000")
    try:
        print(json.dumps(wait_for_release(args.commit, args.wait_seconds), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, ReleaseGateError) as exc:
        parser.exit(1, f"Release blocked: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
