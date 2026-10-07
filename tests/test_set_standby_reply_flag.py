"""`scripts/set_standby_reply_flag.py` must move one env key and preserve every other.

Why this test exists
--------------------
`UpdateFunctionConfiguration` **REPLACES** `Environment.Variables` wholesale — the same
replace-not-patch shape that silently reset four fields on a Cognito pool. Writing a
one-key map to `wecare-inbound-whatsapp` would not error; it would drop
`CONTACTS_TABLE`, `INBOUND_TABLE`, `OUTBOUND_TABLE`, `MEDIA_BUCKET`, `IAM_REFRESH` and
both `WHATSAPP_PHONE_NUMBER_ID_*` keys and break inbound WhatsApp outright. The env
preservation is therefore the property under test, not an implementation detail.

Everything here runs against a fake Lambda client. No AWS call is made.

The parse-semantics assertion goes THROUGH the handler
------------------------------------------------------
`test_false_is_a_value_the_handler_reads_as_off` imports the real
`_standby_reply_enabled()` and asserts the written value evaluates to `False`, rather than
restating the parse rule here. The rule is a DISABLE list (`false`, `0`, `no`, `off`), so
any other spelling — including `fasle` or `disabled` — reads as TRUE. Asserting through
the handler means a change to those semantics breaks this test instead of silently
leaving the script writing a value that no longer disables anything.
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "set_standby_reply_flag.py"
_INBOUND_DIR = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler"

for _p in (str(ROOT / "amplify/functions/shared"), str(_INBOUND_DIR),
           str(_INBOUND_DIR / "modules")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: The live environment of `wecare-inbound-whatsapp` as measured 2026-10-07, by NAME only.
#: The values are placeholders — the test asserts they survive byte-identical, so their
#: content is irrelevant and real values must never appear in a test file.
LIVE_KEYS = (
    "CONTACTS_TABLE", "IAM_REFRESH", "INBOUND_TABLE", "MEDIA_BUCKET",
    "OUTBOUND_TABLE", "WHATSAPP_PHONE_NUMBER_ID_1", "WHATSAPP_PHONE_NUMBER_ID_2",
)
BASE_ENV = {name: f"placeholder-{name.lower()}" for name in LIVE_KEYS}


class FakeLambda:
    """Counts writes and records the environment map the script would send."""

    def __init__(self, env=None, flag=None):
        self.env = dict(BASE_ENV if env is None else env)
        if flag is not None:
            self.env["STANDBY_REPLY_ENABLED"] = flag
        self.writes = []
        self.waited = []

    def get_function_configuration(self, FunctionName, Qualifier=None):
        return {
            "FunctionName": FunctionName,
            "Version": Qualifier or "$LATEST",
            "CodeSha256": "0bjTkI9BQcFnIHqD5F7PMBrrNhtukRcH8DOax5Tq++Q=",
            "Environment": {"Variables": dict(self.env)},
        }

    def get_alias(self, FunctionName, Name):
        return {"FunctionVersion": "76"}

    def update_function_configuration(self, FunctionName, Environment):
        self.writes.append(dict(Environment["Variables"]))
        self.env = dict(Environment["Variables"])
        return {"FunctionName": FunctionName}

    def get_waiter(self, name):
        fake = self

        class _Waiter:
            def wait(self, **kwargs):
                fake.waited.append(name)

        return _Waiter()


@pytest.fixture()
def script():
    spec = importlib.util.spec_from_file_location("set_standby_reply_flag", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def handler():
    spec = importlib.util.spec_from_file_location(
        "inbound_handler_for_flag_test", _INBOUND_DIR / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script, fake, argv):
    with patch.object(script, "lam", return_value=fake):
        return script.main(argv)


class TestEnvPreservation:
    """The one failure mode that matters: dropping a key that is not the flag."""

    def test_false_adds_the_flag_and_preserves_the_other_seven(self, script):
        fake = FakeLambda()
        assert _run(script, fake, ["--state", "false", "--apply"]) == 0
        assert len(fake.writes) == 1
        written = fake.writes[0]
        assert len(written) == 8
        assert written["STANDBY_REPLY_ENABLED"] == "false"
        for name in LIVE_KEYS:
            assert written[name] == BASE_ENV[name], f"{name} was not preserved"

    def test_absent_removes_only_the_flag(self, script):
        fake = FakeLambda(flag="false")
        assert _run(script, fake, ["--state", "absent", "--apply"]) == 0
        written = fake.writes[0]
        assert "STANDBY_REPLY_ENABLED" not in written
        assert len(written) == 7
        assert written == BASE_ENV

    def test_true_writes_the_literal_true_and_preserves(self, script):
        fake = FakeLambda()
        assert _run(script, fake, ["--state", "true", "--apply"]) == 0
        written = fake.writes[0]
        assert written["STANDBY_REPLY_ENABLED"] == "true"
        assert {k: v for k, v in written.items() if k != "STANDBY_REPLY_ENABLED"} == BASE_ENV

    def test_a_write_waits_for_the_update_to_settle(self, script):
        fake = FakeLambda()
        _run(script, fake, ["--state", "false", "--apply"])
        assert "function_updated_v2" in fake.waited


class TestTheValueActuallyDisables:

    def test_false_is_a_value_the_handler_reads_as_off(self, script, handler):
        """Assert through the real parse function, not by restating its rule.

        The handler's semantics are a DISABLE list, so writing anything other than
        `false`/`0`/`no`/`off` would leave the flag effectively ON while looking set.
        """
        fake = FakeLambda()
        _run(script, fake, ["--state", "false", "--apply"])
        written = fake.writes[0]["STANDBY_REPLY_ENABLED"]
        with patch.dict(os.environ, {"STANDBY_REPLY_ENABLED": written}, clear=False):
            assert handler._standby_reply_enabled() is False

    def test_the_rollback_value_restores_the_default(self, script, handler):
        fake = FakeLambda(flag="false")
        _run(script, fake, ["--state", "absent", "--apply"])
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STANDBY_REPLY_ENABLED", None)
            assert handler._standby_reply_enabled() is True


class TestDryRunIsTheDefault:

    def test_no_apply_flag_performs_zero_writes(self, script):
        fake = FakeLambda()
        assert _run(script, fake, ["--state", "false"]) == 0
        assert fake.writes == []
        assert "STANDBY_REPLY_ENABLED" not in fake.env

    def test_explicit_dry_run_performs_zero_writes(self, script):
        fake = FakeLambda()
        assert _run(script, fake, ["--state", "false", "--dry-run"]) == 0
        assert fake.writes == []

    def test_verify_performs_zero_writes(self, script):
        fake = FakeLambda()
        assert _run(script, fake, ["--verify"]) == 0
        assert fake.writes == []

    def test_already_in_target_state_writes_nothing(self, script):
        fake = FakeLambda(flag="false")
        assert _run(script, fake, ["--state", "false", "--apply"]) == 0
        assert fake.writes == []


class TestItRefusesRatherThanDroppingAKey:

    def test_a_key_set_that_would_change_by_more_than_the_flag_is_refused(self, script):
        """If the builder ever drops a key, the script must exit non-zero and not write."""
        fake = FakeLambda()
        original = script._wanted_env

        def _lossy(current, state):
            wanted = original(current, state)
            wanted.pop("CONTACTS_TABLE", None)     # simulate the regression
            return wanted

        with patch.object(script, "_wanted_env", _lossy):
            assert _run(script, fake, ["--state", "false", "--apply"]) == 1
        assert fake.writes == []

    def test_a_changed_value_on_a_preserved_key_is_refused(self, script):
        fake = FakeLambda()
        original = script._wanted_env

        def _mangling(current, state):
            wanted = original(current, state)
            wanted["INBOUND_TABLE"] = "something-else"
            return wanted

        with patch.object(script, "_wanted_env", _mangling):
            assert _run(script, fake, ["--state", "false", "--apply"]) == 1
        assert fake.writes == []

    def test_state_is_required_unless_verify(self, script):
        fake = FakeLambda()
        with pytest.raises(SystemExit):
            _run(script, fake, [])
        assert fake.writes == []


class TestItNeverPrintsAnotherEnvValue:

    @pytest.mark.parametrize("argv", [["--verify"],
                                      ["--state", "false"],
                                      ["--state", "false", "--apply"]])
    def test_no_other_env_value_reaches_stdout(self, script, capsys, argv):
        """Key NAMES and the non-secret flag only. Every other value stays out of the log."""
        fake = FakeLambda()
        _run(script, fake, argv)
        out = capsys.readouterr().out
        for name in LIVE_KEYS:
            assert name in out, f"{name} should be reported by name"
            assert BASE_ENV[name] not in out, f"the VALUE of {name} was printed"
