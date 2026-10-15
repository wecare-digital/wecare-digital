"""The Lightsail nano toolkit is dry-run by default, owner-gated, and never aims at the micro.

The scripts run against a stub `aws` (AWS_BIN) that records every call, so nothing here can
touch the account.
"""
from __future__ import annotations

import os
import pathlib
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIR = ROOT / "scripts" / "lightsail-nano-migration"
SCRIPTS = ["_common.sh", "preflight.sh", "bootstrap-nano.sh", "migrate-workload.sh",
           "verify-nano.sh", "rollback.sh"]
MUTATING = ("create-instances", "open-instance-public-ports", "detach-static-ip",
            "attach-static-ip", "delete-instance", "stop-instance")

STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
args="$*"
case "$args" in
  *"sts get-caller-identity"*) echo "${STUB_ACCOUNT:-775261844268}" ;;
  *"get-instance-snapshot"*) echo "${STUB_SNAPSHOT_STATE:-available}" ;;
  *"get-instance --instance-name wecare-voice-bot "*"state.name"*) echo running ;;
  *"get-instance --instance-name wecare-voice-bot "*) echo 52.3.44.165 ;;
  *"get-instance --instance-name"*"state.name"*) [ -n "${STUB_NANO_STATE:-}" ] && echo "$STUB_NANO_STATE" || exit 254 ;;
  *"get-instance --instance-name"*) echo 3.3.3.3 ;;
  *"staticIp.attachedTo"*) echo "${STUB_ATTACHED:-wecare-voice-bot}" ;;
  *"get-static-ip"*) echo 52.3.44.165 ;;
  *) echo "{}" ;;
esac
"""


@pytest.fixture()
def env(tmp_path):
    stub = tmp_path / "aws"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "aws.log"
    log.touch()
    base = {k: v for k, v in os.environ.items() if k not in {"APPLY", "CONFIRM", "NANO_INSTANCE"}}
    base.update({"AWS_BIN": str(stub), "STUB_LOG": str(log), "SSH_BIN": "/bin/false"})
    return base, log


def _run(script, env_vars, *args, **extra):
    e = dict(env_vars)
    e.update(extra)
    return subprocess.run(["bash", str(DIR / script), *args], env=e, capture_output=True,
                          text=True, timeout=60)


def _mutations(log):
    return [line for line in log.read_text().splitlines() if any(m in line for m in MUTATING)]


@pytest.mark.parametrize("script", SCRIPTS)
def test_syntax(script):
    assert subprocess.run(["bash", "-n", str(DIR / script)]).returncode == 0


def test_apply_flag_really_switches_off_dry_run(env):
    e, _ = env
    probe = 'cd "%s"; . ./_common.sh; echo "DRYRUN=$DRYRUN"' % DIR
    out = subprocess.run(["bash", "-c", probe], env={**e, "APPLY": "1"},
                         capture_output=True, text=True).stdout
    assert "DRYRUN=0" in out
    out = subprocess.run(["bash", "-c", probe], env=e, capture_output=True, text=True).stdout
    assert "DRYRUN=1" in out


def test_bootstrap_dry_run_mutates_nothing(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e)
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN would: create fresh nano instance" in r.stdout
    assert _mutations(log) == []


def test_bootstrap_apply_needs_the_owner_token(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e, APPLY="1")
    assert r.returncode != 0 and "I-APPROVE-provision-nano" in r.stderr
    assert _mutations(log) == []


def test_bootstrap_apply_with_token_creates_only_the_nano(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e, APPLY="1", CONFIRM="I-APPROVE-provision-nano")
    assert r.returncode == 0, r.stderr
    created = [m for m in _mutations(log) if "create-instances" in m]
    assert len(created) == 1 and "--instance-names wecare-voice-bot-nano" in created[0]
    assert all("wecare-voice-bot " not in m.replace("wecare-voice-bot-nano", "")
               for m in _mutations(log))


def test_bootstrap_refuses_without_an_available_recovery_snapshot(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e, APPLY="1", CONFIRM="I-APPROVE-provision-nano",
             STUB_SNAPSHOT_STATE="pending")
    assert r.returncode != 0 and "recovery snapshot" in r.stderr
    assert _mutations(log) == []


def test_nano_name_can_never_be_the_production_instance(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e, NANO_INSTANCE="wecare-voice-bot")
    assert r.returncode != 0 and "must not be the production instance" in r.stderr
    r = _run("migrate-workload.sh", e, NANO_INSTANCE="wecare-voice-bot")
    assert r.returncode != 0
    assert _mutations(log) == []


def test_wrong_account_is_refused(env):
    e, log = env
    r = _run("bootstrap-nano.sh", e, STUB_ACCOUNT="111111111111")
    assert r.returncode != 0 and "wrong account" in r.stderr


def test_migrate_dry_run_and_cutover_preview_touch_nothing(env):
    e, log = env
    r = _run("migrate-workload.sh", e)
    assert r.returncode == 0, r.stderr
    assert "sha256 tree digest" in r.stdout
    r = _run("migrate-workload.sh", e, "--cutover")
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN would: attach static IP to the nano" in r.stdout
    assert _mutations(log) == []


def test_cutover_needs_token_and_precutover_verification(env):
    e, log = env
    r = _run("migrate-workload.sh", e, "--cutover", APPLY="1")
    assert r.returncode != 0 and "I-APPROVE-cutover" in r.stderr
    r = _run("migrate-workload.sh", e, "--cutover", APPLY="1", CONFIRM="I-APPROVE-cutover")
    assert r.returncode != 0 and "PRECUTOVER_VERIFIED" in r.stderr
    assert _mutations(log) == []


def test_transfer_refuses_when_ssh_cannot_prove_versions(env):
    """SSH_BIN=/bin/false: no version proof, so no transfer and no cutover."""
    e, log = env
    r = _run("migrate-workload.sh", e, APPLY="1", CONFIRM="I-APPROVE-migrate")
    assert r.returncode != 0
    assert _mutations(log) == []


def test_rollback_preview_and_apply(env):
    e, log = env
    r = _run("rollback.sh", e, STUB_ATTACHED="wecare-voice-bot-nano")
    assert r.returncode == 0, r.stderr
    assert _mutations(log) == []
    r = _run("rollback.sh", e, APPLY="1", STUB_ATTACHED="wecare-voice-bot-nano")
    assert r.returncode != 0 and "I-APPROVE-rollback" in r.stderr
    r = _run("rollback.sh", e, APPLY="1", CONFIRM="I-APPROVE-rollback",
             STUB_ATTACHED="wecare-voice-bot-nano")
    assert r.returncode == 0, r.stderr
    attach = [m for m in _mutations(log) if "attach-static-ip" in m and "detach" not in m]
    assert len(attach) == 1 and attach[0].endswith("--instance-name wecare-voice-bot")


def test_rollback_is_a_no_op_when_the_ip_is_already_on_the_micro(env):
    e, log = env
    r = _run("rollback.sh", e, APPLY="1", CONFIRM="I-APPROVE-rollback")
    assert r.returncode == 0 and "nothing to roll back" in r.stdout
    assert _mutations(log) == []


def test_no_script_embeds_a_credential():
    for script in SCRIPTS:
        text = (DIR / script).read_text()
        for needle in ("AKIA", "BEGIN RSA", "BEGIN OPENSSH", "password=", "secret="):
            assert needle not in text, (script, needle)
