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


def test_authenticated_read_uses_fixed_host_and_does_not_follow_redirect(monkeypatch):
    import io
    monkeypatch.setenv("WECARE_GITHUB_ACTIONS_READ_TOKEN", "synthetic-test-only")

    class Opener:
        def open(self, request, *, timeout):
            assert request.full_url == gate.API + "/runs/8"
            assert request.get_header("Authorization") == "Bearer synthetic-test-only"
            assert timeout <= 10
            return io.BytesIO(b'{"id":8}')

    def opener(handler):
        assert handler.redirect_request() is None
        return Opener()

    monkeypatch.setattr(gate, "build_opener", opener)
    assert gate._json("/runs/8") == {"id": 8}


def test_rate_limit_error_is_explicit_and_redacted(monkeypatch):
    from email.message import Message
    headers = Message()
    headers["X-RateLimit-Remaining"] = "0"

    class Opener:
        def open(self, request, *, timeout):
            raise gate.HTTPError(request.full_url, 403, "provider details", headers, None)

    monkeypatch.setattr(gate, "build_opener", lambda *_: Opener())
    with pytest.raises(gate.ReleaseGateError, match="rate limited the gate"):
        gate._json("/runs/8")


def test_canonical_promotion_refuses_without_a_verified_rollback_hash(monkeypatch, tmp_path):
    from scripts import snapstart_publish as publisher

    current = publisher.State("12", None, "alias-revision", "new-code-hash", "function-revision")
    monkeypatch.setattr(publisher, "current_state", lambda *_: current)
    receipt = tmp_path / "release.jsonl"
    receipt.write_text("")
    # The stub has no mutation methods; an attempted publish would fail the test.
    assert publisher.publish_and_move(
        object(), "test-function", False, True, "new-code-hash", receipt,
    ) == "failed"
    assert not receipt.read_text()


def test_canonical_apply_uploads_only_verified_commit_bytes(monkeypatch, tmp_path):
    import io
    import subprocess
    import sys
    import zipfile
    from scripts import deploy_all_lambdas as deploy

    function = tmp_path / "amplify/functions/test"
    modules = function / "modules"
    modules.mkdir(parents=True)
    shared = function.parent / "shared/lambda_utils"
    shared.mkdir(parents=True)
    for name in ("__init__.py", "logging.py", "response.py"):
        (shared / name).write_text("")
    handler = function / "handler.py"
    reviewed_handler = "def lambda_handler(event, context):\n    return 'reviewed'\n"
    handler.write_text(reviewed_handler)
    (modules / "tracked.py").write_text("NAME = 'reviewed'\n")
    config = tmp_path / "src/config.json"
    config.parent.mkdir()
    config.write_text('{"reviewed":true}\n')
    (tmp_path / ".gitignore").write_text(".scratch/\n/amplify/functions/test/modules/local-note.txt\n")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q")
    git("add", "--", ".gitignore", "amplify/functions", "src/config.json")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "reviewed")
    verified_commit = git("rev-parse", "HEAD")
    (modules / "local-note.txt").write_text("harmless ignored fixture\n")
    assert git("status", "--porcelain") == ""

    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "FUNCTIONS", function.parent)
    monkeypatch.setattr(deploy, "LAMBDA_UTILS", shared)
    monkeypatch.setattr(deploy, "STATIC_KB", shared.parent / "static_knowledge_base.py")
    spec = deploy.Spec("example", "test", external_files=[("../../src/config.json", "config.json")])
    monkeypatch.setattr(deploy, "SPECS", [spec])
    monkeypatch.setattr(sys, "argv", ["deploy_all_lambdas.py", "--no-publish", "example"])

    def verify(commit, wait):
        assert (commit, wait) == (verified_commit, 0)
        # Model a real concurrent local edit after the clean-checkout check.
        handler.write_text("def lambda_handler(event, context):\n    return 'local edit'\n")
        return {"commit": commit, "runId": 8}

    class Lambda:
        def get_function_configuration(self, **_kwargs):
            return {"Handler": "handler.lambda_handler"}

    captured = []
    def upload(_client, _spec, package, _current):
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            captured.append(archive.namelist())
            assert archive.read("handler.py").decode() == reviewed_handler
            assert archive.read("modules/tracked.py") == b"NAME = 'reviewed'\n"
            assert archive.read("config.json") == b'{"reviewed":true}\n'
            assert "modules/local-note.txt" not in archive.namelist()
        return "updated"

    monkeypatch.setattr(deploy, "wait_for_release", verify)
    monkeypatch.setattr(deploy.boto3, "client", lambda *_args, **_kwargs: Lambda())
    monkeypatch.setattr(deploy, "deploy", upload)
    assert deploy.main() == 0
    assert len(captured) == 1


def fake_clock(monkeypatch):
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(gate.time, 'monotonic', lambda: clock[0])
    def sleep(seconds):
        assert 0 < seconds <= 30
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(gate.time, 'sleep', sleep)
    return clock, sleeps


def test_rate_limit_uses_provider_reset_and_then_requires_real_evidence(monkeypatch):
    clock, sleeps = fake_clock(monkeypatch)
    evidence = {'commit': SHA, 'jobId': 15}
    reads = []
    def check(commit):
        reads.append(clock[0])
        assert commit == SHA
        if len(reads) == 1:
            raise gate.RateLimitedError(91)
        return evidence
    monkeypatch.setattr(gate, 'check_release', check)
    assert gate.wait_for_release(SHA, 120) == evidence
    assert reads == [0, 91]
    assert sum(sleeps) == 91


def test_rate_limit_without_headers_backs_off_and_never_authorizes(monkeypatch):
    clock, sleeps = fake_clock(monkeypatch)
    reads = []
    def check(_):
        reads.append(clock[0])
        raise gate.RateLimitedError()
    monkeypatch.setattr(gate, 'check_release', check)
    with pytest.raises(gate.ReleaseGateError, match='remaining wait budget'):
        gate.wait_for_release(SHA, 200)
    assert reads == [0, 60, 180]
    assert sum(sleeps) == 180


def test_terminal_ci_failure_is_not_retried(monkeypatch):
    _, sleeps = fake_clock(monkeypatch)
    def check(_):
        raise gate.ReleaseGateError('Production CI run 8 did not pass: failure')
    monkeypatch.setattr(gate, 'check_release', check)
    with pytest.raises(gate.ReleaseGateError, match='did not pass'):
        gate.wait_for_release(SHA, 3000)
    assert not sleeps


def test_rate_headers_never_retry_before_either_provider_limit(monkeypatch):
    monkeypatch.setattr(gate.time, 'time', lambda: 1000)
    assert gate.rate_limit_delay({'Retry-After':'60','X-RateLimit-Reset':'1090','X-RateLimit-Remaining':'0'}) == 91
    assert gate.rate_limit_delay({'Retry-After':'invalid','X-RateLimit-Reset':'invalid'}) is None
    assert gate.rate_limit_delay({'Retry-After':'0'}) == 1
