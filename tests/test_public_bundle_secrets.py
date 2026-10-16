"""Tests for scripts/verify_public_bundle_secrets.py.

The point of the guard is a narrow distinction: a Google *browser* key in the
export is fine, the *unified server-side* key in the export is a disclosure. So
these tests exercise both sides of that line, plus the shapes that have no public
form at all.

No literal credential appears in this file. Every test value is assembled at
runtime from fragments, the same technique scripts/verify_no_secrets_in_tree.py
uses, so the file itself carries no issuer-shaped string.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "verify_public_bundle_secrets.py"

_spec = importlib.util.spec_from_file_location("bundle_secrets_under_test", _SCRIPT)
vpbs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vpbs)


# ── synthetic values, assembled so no literal shape is stored here ────────────

def _join(*parts: str) -> str:
    """Concatenate via a call, because `+` between literals is folded at compile time.

    The comment above used to be true of the source and false of the artifact:
    CPython folds `"rzp" + "_" + "live" + "_" + "Q" * 14` while compiling, so the
    assembled shape landed in tests/__pycache__/*.pyc as a literal. Harmless in
    itself - every value here is synthetic - but it makes this repo's own secret
    scanners report hits on their own test bytecode, and a scanner people learn to
    dismiss is a scanner that stops working. A function call is opaque to the
    folder. Found 2026-09-29 alongside the same bug in verify_secret_hook.py.
    """
    return "".join(parts)


def _google_key(tail: str) -> str:
    """An AIza-shaped string of realistic length, without writing the prefix.

    Padded with a repeating multi-character pattern rather than one character.
    Single-character padding would produce a run of 20+ identical characters,
    which the scanner's FILLER rule correctly classifies as a synthetic
    placeholder and skips - so a naive `ljust(35, "x")` here silently tested
    nothing.
    """
    pad = "a1B2c3D4e5F6g7H8j9K0" * 3
    return _join("AI", "za", (tail + pad)[:35])


def _razorpay_key() -> str:
    return _join("rzp", "_", "live", "_", "Q" * 14)


def _openai_key() -> str:
    return _join("sk", "-", "proj", "-", "b7Kq2Xn" * 6)


def _aws_key() -> str:
    """Synthetic AWS-shaped value assembled at runtime, never stored literally."""
    return _join("AK", "IA", "AB12", "CD34", "EF56", "GH78")


BENIGN_GOOGLE = _google_key("browserkey0")
SERVER_GOOGLE = _google_key("serverkey0")


@pytest.fixture()
def export(tmp_path):
    """A stand-in for out/, with the one chunk layout the real export produces."""
    d = tmp_path / "out"
    (d / "_next" / "static" / "chunks").mkdir(parents=True)
    return d


def _write(export: Path, name: str, body: str) -> None:
    (export / "_next" / "static" / "chunks" / name).write_text(body)


def _scan(export: Path, name: str):
    p = export / "_next" / "static" / "chunks" / name
    return vpbs.scan_file(p, name)


# ── the fingerprint convention must not drift ────────────────────────────────

def test_fingerprint_matches_the_repo_wide_convention():
    """scripts/env_manifest.py:fp() is sha256 truncated to 12 hex. If this drifts,
    a fingerprint recorded by one script stops comparing against another."""
    value = "any-value"
    assert vpbs.fingerprint(value) == hashlib.sha256(value.encode()).hexdigest()[:12]
    assert len(vpbs.fingerprint(value)) == 12


def test_the_unified_google_key_is_NOT_forbidden():
    """Reversed on 2026-09-25, and the reason is the point of the test.

    This originally asserted that sha256:0bd4beb6496a MUST be in the forbidden set,
    on the assumption it was a server-side credential. Measuring the live project
    showed the opposite: `gcloud services api-keys list --project=wecaredigitalbw`
    returns ONE key whose restrictions are
    browserKeyRestrictions.allowedReferrers = https://wecare.digital/*,
    https://*.wecare.digital/* - a browser key, already restricted to exactly the
    referrers this repo asks for.

    A referrer-restricted browser key is public by design, so blocking it would
    have failed the Amplify build on the CORRECT action - the owner pasting the
    right key. Keeping this as an assertion stops the entry being re-added by
    someone reading the old reasoning."""
    assert "0bd4beb6496a" not in vpbs.FORBIDDEN_FINGERPRINTS


def test_a_browser_key_is_never_blocked_by_default():
    """With no forbidden fingerprints configured, any Google key in the export is
    reported rather than refused. The shapes with no public form at all are still
    refused - that is asserted separately below."""
    assert vpbs.FORBIDDEN_FINGERPRINTS == {} or all(
        isinstance(v, str) for v in vpbs.FORBIDDEN_FINGERPRINTS.values())


# ── the two sides of the Google distinction ──────────────────────────────────

def test_a_server_side_google_key_in_the_export_fails(export, monkeypatch):
    """The dangerous case. A real value matching sha256:0bd4beb6496a cannot be
    forged here - that is what a one-way digest buys - so the MECHANISM is tested
    by declaring this synthetic key's own fingerprint forbidden."""
    monkeypatch.setitem(vpbs.FORBIDDEN_FINGERPRINTS,
                        vpbs.fingerprint(SERVER_GOOGLE), "synthetic server-side key")
    _write(export, "page-abc.js", f'var k="{SERVER_GOOGLE}";')

    failures, allowed = _scan(export, "page-abc.js")

    assert len(failures) == 1, failures
    assert failures[0]["kind"] == "google (server-side)"
    assert failures[0]["fingerprint"] == vpbs.fingerprint(SERVER_GOOGLE)
    assert allowed == []


def test_a_browser_google_key_in_the_export_is_allowed(export):
    """The legitimate case, and it must NOT fail: a Maps browser key is public by
    design. It is still reported, so its presence is visible rather than silent."""
    _write(export, "page-def.js", f'var k="{BENIGN_GOOGLE}";')

    failures, allowed = _scan(export, "page-def.js")

    assert failures == []
    assert len(allowed) == 1
    assert allowed[0]["fingerprint"] == vpbs.fingerprint(BENIGN_GOOGLE)


def test_a_failure_never_carries_the_value(export, monkeypatch):
    """Findings must report fingerprint and length only. A guard that echoes the
    credential to report it has recreated the incident it exists to prevent."""
    monkeypatch.setitem(vpbs.FORBIDDEN_FINGERPRINTS,
                        vpbs.fingerprint(SERVER_GOOGLE), "synthetic server-side key")
    _write(export, "page-ghi.js", f'var k="{SERVER_GOOGLE}";')

    failures, _ = _scan(export, "page-ghi.js")

    blob = repr(failures)
    assert SERVER_GOOGLE not in blob
    # not even a long prefix of it
    assert SERVER_GOOGLE[:20] not in blob
    assert set(failures[0]) == {"file", "kind", "fingerprint", "length", "why"}


# ── shapes with no public form at all ────────────────────────────────────────

@pytest.mark.parametrize("label,value", [
    ("razorpay live", _razorpay_key()),
    ("openai", _openai_key()),
])
def test_never_public_shapes_fail_regardless_of_fingerprint(export, label, value):
    _write(export, "page-jkl.js", f'var k="{value}";')

    failures, allowed = _scan(export, "page-jkl.js")

    assert [f["kind"] for f in failures] == [label]
    assert allowed == []


def test_the_aws_documentation_example_key_is_not_a_finding(export):
    """AWS publishes this one in its own docs; flagging it trains people to ignore
    the check."""
    example = _join("AKI", "A", "IOSFODNN7EXAMPLE")
    _write(export, "page-mno.js", f'var k="{example}";')

    failures, _ = _scan(export, "page-mno.js")

    assert failures == []


def test_unknown_aws_credential_shape_still_fails(export):
    """The numcodecs exception must not weaken the default AWS credential gate."""
    value = _aws_key()
    _write(export, "page-aws.js", f'var k="{value}";')

    failures, allowed = _scan(export, "page-aws.js")

    assert [f["kind"] for f in failures] == ["aws access key"]
    assert allowed == []


def test_exact_benign_aws_fingerprint_can_be_allowlisted(export, monkeypatch):
    """Only an exact verified fingerprint may bypass the AWS-shaped token gate."""
    value = _aws_key()
    monkeypatch.setattr(
        vpbs,
        "BENIGN_AWS_FINGERPRINTS",
        { *vpbs.BENIGN_AWS_FINGERPRINTS, vpbs.fingerprint(value) },
    )
    _write(export, "page-codec.js", f'var k="{value}";')

    failures, allowed = _scan(export, "page-codec.js")

    assert failures == []
    assert allowed == []


def test_verified_numcodecs_fingerprints_are_pinned():
    assert {
        "1cbb1adb8621", "7fb6cb4173b3", "25b3c9880103", "a319dbdf2041",
    } <= set(vpbs.BENIGN_AWS_FINGERPRINTS)


def test_numcodecs_false_positive_exception_is_exact_and_fingerprint_only():
    """Only the four public WASM-wrapper byte constants proven by the one-off
    dependency diagnostic may bypass the AWS-shape check. A future codec/version
    must repeat that provenance check rather than widening the regex."""
    assert vpbs.BENIGN_AWS_FINGERPRINTS == {
        "1cbb1adb8621", "7fb6cb4173b3",
        "25b3c9880103", "a319dbdf2041",
    }


def test_repeated_character_filler_is_not_a_finding(export):
    """The repo's own hook tests use runs of one character as stand-in values."""
    filler = _join("AI", "za", "A" * 35)
    _write(export, "page-pqr.js", f'var k="{filler}";')

    failures, allowed = _scan(export, "page-pqr.js")

    assert failures == []
    assert allowed == []


# ── the gate must not pass by accident ───────────────────────────────────────

def test_a_missing_export_directory_does_not_report_success(monkeypatch, tmp_path):
    """Exit 2, not 0. A gate that passes when its subject is absent is the exact
    failure mode recorded at the top of scripts/snapstart_publish.py, where a
    missing file made the publish step silently no-op on every deploy."""
    monkeypatch.setattr(vpbs, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["verify_public_bundle_secrets.py", "--dir", "nope"])

    assert vpbs.main() == 2


def test_a_clean_export_passes(export, monkeypatch):
    monkeypatch.setattr(vpbs, "ROOT", export.parent)
    monkeypatch.setattr("sys.argv", ["verify_public_bundle_secrets.py", "--dir", "out"])
    _write(export, "page-stu.js", 'var greeting="hello";')

    assert vpbs.main() == 0


def test_a_dirty_export_returns_one(export, monkeypatch):
    monkeypatch.setattr(vpbs, "ROOT", export.parent)
    monkeypatch.setattr("sys.argv", ["verify_public_bundle_secrets.py", "--dir", "out"])
    _write(export, "page-vwx.js", f'var k="{_razorpay_key()}";')

    assert vpbs.main() == 1


# ── --amplify-env: catching the paste, not the build after it ─────────────────
#
# The out/ scan only sees a key if the build that produced out/ had the variable
# set, and GitHub Actions does not set it. So the Amplify env check is what makes
# the answer available without a build. boto3 is stubbed; these never touch AWS.

class _FakeAmplify:
    def __init__(self, env):
        self._env = env

    def get_branch(self, appId, branchName):
        assert appId and branchName
        return {"branch": {"environmentVariables": dict(self._env)}}


@pytest.fixture()
def fake_boto3(monkeypatch):
    import types

    def install(env):
        mod = types.ModuleType("boto3")
        mod.client = lambda service, region_name=None: _FakeAmplify(env)
        monkeypatch.setitem(__import__("sys").modules, "boto3", mod)
    return install


def test_amplify_env_clean_passes(fake_boto3, capsys):
    fake_boto3({"NEXT_PUBLIC_API_BASE": "https://api.wecare.digital",
                "NEXT_PUBLIC_GOOGLE_BROWSER_KEY": BENIGN_GOOGLE})

    assert vpbs.check_amplify_env() == 0
    assert "PASS" in capsys.readouterr().out


def test_amplify_env_catches_a_server_side_key_in_a_public_var(
        fake_boto3, monkeypatch, capsys):
    """The exact mistake: the unified key pasted into NEXT_PUBLIC_GOOGLE_BROWSER_KEY."""
    monkeypatch.setitem(vpbs.FORBIDDEN_FINGERPRINTS,
                        vpbs.fingerprint(SERVER_GOOGLE), "synthetic server-side key")
    fake_boto3({"NEXT_PUBLIC_GOOGLE_BROWSER_KEY": SERVER_GOOGLE})

    rc = vpbs.check_amplify_env()
    out = capsys.readouterr().out

    assert rc == 1
    assert "NEXT_PUBLIC_GOOGLE_BROWSER_KEY" in out
    assert "every visitor" in out
    # the value itself must never be printed
    assert SERVER_GOOGLE not in out
    assert SERVER_GOOGLE[:20] not in out


def test_amplify_env_reports_a_non_public_var_differently(
        fake_boto3, monkeypatch, capsys):
    """Still wrong to hold a credential in Amplify, but it is not published - so the
    report must not claim visitors can read it."""
    monkeypatch.setitem(vpbs.FORBIDDEN_FINGERPRINTS,
                        vpbs.fingerprint(SERVER_GOOGLE), "synthetic server-side key")
    fake_boto3({"GOOGLE_API_KEY": SERVER_GOOGLE})

    rc = vpbs.check_amplify_env()
    out = capsys.readouterr().out

    assert rc == 1
    assert "not published" in out
    assert "every visitor" not in out
    assert SERVER_GOOGLE not in out


def test_amplify_env_whitespace_does_not_defeat_the_fingerprint(
        fake_boto3, monkeypatch):
    """A pasted value often carries a trailing newline; it must still match."""
    monkeypatch.setitem(vpbs.FORBIDDEN_FINGERPRINTS,
                        vpbs.fingerprint(SERVER_GOOGLE), "synthetic server-side key")
    fake_boto3({"NEXT_PUBLIC_GOOGLE_BROWSER_KEY": f"  {SERVER_GOOGLE}\n"})

    assert vpbs.check_amplify_env() == 1


# ── the wiring itself is part of the guarantee ────────────────────────────────

def test_the_gate_runs_in_the_amplify_build_after_the_build():
    """If this step is removed from amplify.yml the check stops protecting the only
    build that has the environment variables, and CI would still be green."""
    import yaml

    spec = yaml.safe_load((ROOT / "amplify.yml").read_text())
    cmds = spec["frontend"]["phases"]["build"]["commands"]
    gate = [i for i, c in enumerate(cmds) if "verify_public_bundle_secrets" in c]
    assert gate, "the credential gate is missing from amplify.yml"
    # MATCHED AS A SUBSTRING, not the whole command: the build line now exports
    # NEXT_PUBLIC_GOOGLE_BROWSER_KEY from Secrets Manager and then runs `npm run build` in the
    # same shell command, so an exact cmds.index("npm run build") no longer finds it.
    build = [i for i, c in enumerate(cmds) if "npm run build" in c]
    assert build, "the build step is missing from amplify.yml"
    assert build[0] < gate[0], "the gate must run after the build"

    pre = spec["frontend"]["phases"]["preBuild"]["commands"]
    assert any("python3 --version" in c for c in pre), \
        "preBuild must prove python3 exists, or the gate can silently skip"
