"""Evidence checks are exercised with fake GitHub responses only."""
from pathlib import Path
import importlib.util

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts" / "require_release_ci.py"
SPEC = importlib.util.spec_from_file_location("require_release_ci", PATH)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

SHA = "a" * 40
RUN = dict(id=8, head_sha=SHA, head_branch="wecare.digital", event="push",
           path=".github/workflows/ci.yml", status="completed",
           conclusion="success", run_attempt=2)
JOB = dict(id=15, name=gate.JOB, head_sha=SHA, status="completed", conclusion="success")


def reader(runs, jobs):
    requests = []
    def read(path):
        requests.append(path)
        if path.startswith("/workflows/"):
            return {"workflow_runs": runs}
        assert path == "/runs/8/attempts/2/jobs?per_page=100"
        return {"jobs": jobs}
    return read, requests


def test_exact_production_push_and_job_attempt_required():
    read, requests = reader([RUN], [JOB])
    assert gate.check_release(SHA, read=read) == dict(
        commit=SHA, branch="wecare.digital", runId=8, runAttempt=2, jobId=15)
    assert f"head_sha={SHA}" in requests[0]


@pytest.mark.parametrize("override", [
    {"head_sha": "b"*40}, {"event": "pull_request"}, {"head_branch": "other"},
    {"path": ".github/workflows/unrelated.yml"}, {"status": "queued"},
])
def test_unrelated_or_pending_checks_do_not_authorize(override):
    read, requests = reader([dict(RUN, **override)], [JOB])
    assert gate.check_release(SHA, read=read) is None
    assert len(requests) == 1


def test_newer_failed_run_blocks_older_green():
    read, _ = reader([dict(RUN, id=7), dict(RUN, conclusion="failure")], [JOB])
    with pytest.raises(gate.ReleaseGateError, match="did not pass"):
        gate.check_release(SHA, read=read)


@pytest.mark.parametrize("jobs", [[], [dict(JOB, conclusion="skipped")], [dict(JOB, head_sha="c"*40)]])
def test_missing_skipped_or_mismatched_job_blocks_release(jobs):
    read, _ = reader([RUN], jobs)
    with pytest.raises(gate.ReleaseGateError, match="Verify job absent"):
        gate.check_release(SHA, read=read)


def test_short_sha_never_queries_github():
    read, requests = reader([RUN], [JOB])
    with pytest.raises(gate.ReleaseGateError, match="full lowercase"):
        gate.check_release(SHA[:8], read=read)
    assert not requests
