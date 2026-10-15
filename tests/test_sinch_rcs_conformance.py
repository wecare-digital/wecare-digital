"""The Sinch RCS production configuration, pinned.

This is the owner-supplied specification for WECARE.DIGITAL's live RCS setup, asserted
against the source so a later edit cannot quietly repoint it. Every value here was also
confirmed against the live account on 2026-09-23.

Two things it deliberately protects
-----------------------------------
**The authentication flow.** Live traffic uses the Keycloak password grant against
`auth.aclwhatsapp.com` (Sinch India, formerly ACL Mobile). It is NOT the global Sinch
platform, and it does NOT use a `KEY_ID`/`KEY_SECRET` pair. A well-meaning "upgrade" to
`auth.sinch.com` would point at a different account that does not carry this project, and
the symptom would be a blanket 401 on every send. Measured: 730 sends over 30 days with
**zero** authentication failures, so the current flow is known-good.

**Credentials in Secrets Manager only.** No username, no password, in source or in an
environment variable. The username matters as much as the password here because the
password grant authenticates with the pair, so a hardcoded username is half a credential
in source control - and, worse, a literal default masks a real configuration fault by
turning a missing field into an opaque 401.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

RCS_SEND = ROOT / "amplify" / "functions" / "messaging" / "rcs-send" / "handler.py"
RCS_DLR = ROOT / "amplify" / "functions" / "messaging" / "rcs-dlr" / "handler.py"
SINCH = SHARED / "lambda_utils" / "sinch_rcs.py"

# ---- the specification -----------------------------------------------------
REGION = "us-east-1"
SECRET_ID = "wecare/sinch/rcs"
SECRET_FIELDS = ("username", "password", "project_id", "app_id", "bot_id")

AUTH_URL = ("https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/"
            "openid-connect/token")
CLIENT_ID = "ipmessaging-client"
GRANT_TYPE = "password"
SEND_BASE = "https://convapi.aclwhatsapp.com/v1/projects"

PROJECT_ID = "c8114d03-eeb2-401d-a8f1-abb93594cb33"
APP_ID = "01KQSB792X3R148D8ZGHQYW3SP"
BOT_ID = "69e0b2c980cbf50614ffa5fd"
USERNAME = "wecaretrans"
DEFAULT_TEMPLATE = "rcsmenu"

#: Functions that opt in to RCS with SINCH_RCS_ENABLED=true, as recorded in
#: config/lambda-env-manifest.json.
RCS_ENABLED_FUNCTIONS = ("wecare-whatsapp-calling",)


def code_only(path: Path) -> str:
    """Source with docstrings and comments stripped.

    Both handlers document the old broken forms in prose so the reason for each change stays
    legible, and a naive substring search would then report the documentation as the defect.
    Comments are blanked in place rather than by rejoining tokens: rejoining splits every
    expression across lines and makes the assertions below unfailable.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    docstring_lines: set = set()
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            docstring_lines.update(
                range(first.lineno, (first.end_lineno or first.lineno) + 1))

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                if 1 <= row <= len(lines):
                    lines[row - 1] = lines[row - 1][:col]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    return "\n".join(line for n, line in enumerate(lines, start=1)
                     if n not in docstring_lines)


class TestAuthenticationFlow:
    """The password grant against Sinch India. Not the global Sinch platform."""

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_token_endpoint(self, path):
        assert AUTH_URL in code_only(path), f"{path.name} must post to {AUTH_URL}"

    @pytest.mark.parametrize("path", [RCS_SEND])
    def test_grant_type_and_client_id(self, path):
        code = code_only(path)
        assert f"'{GRANT_TYPE}'" in code
        assert f"'{CLIENT_ID}'" in code

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_send_endpoint(self, path):
        assert SEND_BASE in code_only(path)

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_not_migrated_to_the_global_sinch_platform(self, path):
        """A different account that does not carry this project. Symptom: blanket 401."""
        code = code_only(path)
        for forbidden in ("auth.sinch.com", "us.conversation.api.sinch.com",
                          "eu.conversation.api.sinch.com", "KEY_ID", "KEY_SECRET",
                          "key_secret"):
            assert forbidden not in code, (
                f"{path.name} references {forbidden}; live RCS authenticates with the "
                "username/password grant against auth.aclwhatsapp.com and migrating is a "
                "separately planned change")


class TestCredentialsComeOnlyFromSecretsManager:
    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_secret_id_is_referenced(self, path):
        assert SECRET_ID in code_only(path)

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_no_password_from_the_environment(self, path):
        code = code_only(path)
        offenders = re.findall(r"(?:environ(?:\.get)?|getenv)\s*[\(\[]\s*['\"]"
                               r"([A-Z0-9_]*(?:PASSWORD|PASSWD|PWD)[A-Z0-9_]*)['\"]", code)
        assert not offenders, f"{path.name} reads a password from the environment: {offenders}"

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_no_username_from_the_environment(self, path):
        """The username is half of the password-grant credential pair."""
        code = code_only(path)
        offenders = re.findall(r"(?:environ(?:\.get)?|getenv)\s*[\(\[]\s*['\"]"
                               r"([A-Z0-9_]*USER(?:NAME)?[A-Z0-9_]*)['\"]", code)
        assert not offenders, f"{path.name} reads a username from the environment: {offenders}"

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_no_literal_username_fallback(self, path):
        """A default username masks a missing field as an opaque 401."""
        code = code_only(path)
        assert f"'{USERNAME}'" not in code, (
            f"{path.name} still falls back to the literal username; that puts half a "
            "credential in source and hides a misconfigured secret")

    @pytest.mark.parametrize("path", [RCS_SEND, SINCH])
    def test_no_literal_bot_id_fallback(self, path):
        code = code_only(path)
        assert f"'{BOT_ID}'" not in code, (
            f"{path.name} still defaults bot_id; after a bot change that would query the "
            "wrong agent and report its templates as ours")

    def test_no_credential_literal_anywhere_in_the_tree(self):
        """Nothing that looks like the password grant's secret half is committed."""
        functions = ROOT / "amplify" / "functions"
        offenders = []
        for path in functions.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"['\"]password['\"]\s*:\s*['\"][^'\"]{6,}['\"]", text):
                offenders.append(str(path.relative_to(functions)))
        assert not offenders, f"literal password value committed in {offenders}"

    def test_sinch_module_loads_every_declared_field(self):
        from lambda_utils import sinch_rcs

        assert tuple(sinch_rcs.SINCH_RCS_FIELDS) == SECRET_FIELDS, (
            "the loader must know every field the secret carries; bot_id was previously "
            "absent here even though the secret held it")
        assert set(sinch_rcs.REQUIRED_FIELDS) == {"username", "password"}

    def test_sinch_module_refuses_an_incomplete_secret(self, monkeypatch):
        """A blank username must fail loudly, not authenticate as a literal."""
        from lambda_utils import sinch_rcs

        class FakeClient:
            def get_secret_value(self, SecretId):  # noqa: N803 - boto3 spelling
                import json as _json
                return {"SecretString": _json.dumps({"password": "x", "app_id": "a"})}

        sinch_rcs._sinch_cache.clear()
        monkeypatch.setattr(sinch_rcs, "_get_secrets_client", lambda: FakeClient())
        assert sinch_rcs._load_sinch_credentials() == {}
        sinch_rcs._sinch_cache.clear()

    def test_sinch_module_loads_a_complete_secret(self, monkeypatch):
        from lambda_utils import sinch_rcs

        class FakeClient:
            def get_secret_value(self, SecretId):  # noqa: N803
                import json as _json
                assert SecretId == SECRET_ID
                return {"SecretString": _json.dumps({
                    "username": USERNAME, "password": "not-a-real-value",
                    "project_id": PROJECT_ID, "app_id": APP_ID, "bot_id": BOT_ID})}

        sinch_rcs._sinch_cache.clear()
        monkeypatch.setattr(sinch_rcs, "_get_secrets_client", lambda: FakeClient())
        creds = sinch_rcs._load_sinch_credentials()
        assert creds["username"] == USERNAME
        assert creds["project_id"] == PROJECT_ID
        assert creds["app_id"] == APP_ID
        assert creds["bot_id"] == BOT_ID
        sinch_rcs._sinch_cache.clear()


class TestNonSecretConfiguration:
    def test_project_and_app_ids_match_the_specification(self):
        code = code_only(RCS_SEND)
        assert PROJECT_ID in code
        assert APP_ID in code

    def test_project_and_app_ids_are_environment_overridable(self):
        """They are non-secret configuration, so they belong in env with a known default."""
        code = code_only(RCS_SEND)
        assert "os.environ.get('RCS_PROJECT_ID'" in code
        assert "os.environ.get('RCS_APP_ID'" in code
        assert "os.environ.get('RCS_SECRET_NAME'" in code

    def test_default_template_is_rcsmenu(self):
        """The default is still `rcsmenu`, but it is now resolved rather than literal.

        Changed 2026-09-28. This previously read the default off the function signature:

            signature.parameters["template_id"].default == DEFAULT_TEMPLATE

        `send_rcs_template` now takes `template_id=None` and resolves it per call from
        `NOTIF_RCS_TEMPLATE_NAME`, falling back to `DEFAULT_IVR_TEMPLATE`. That was not a
        loosening — it closed a split where `notifications/policy.py` honoured the
        variable and this module hardcoded `'rcsmenu'` four times, so setting the
        variable switched one sender and silently left the other. The hardcoded half was
        the live one.

        So the assertion moves to the resolved value, which is what actually gets sent,
        and gains an override case. Signature defaults cannot express "resolved per
        call", and pinning one would forbid the fix.
        """
        import inspect
        import os

        code = code_only(RCS_SEND)
        assert f"'{DEFAULT_TEMPLATE}'" in code
        from lambda_utils import sinch_rcs

        signature = inspect.signature(sinch_rcs.send_rcs_template)
        assert signature.parameters["template_id"].default is None, (
            "template_id must default to None so it can be resolved at call time"
        )
        assert sinch_rcs.DEFAULT_IVR_TEMPLATE == DEFAULT_TEMPLATE

        previous = os.environ.pop("NOTIF_RCS_TEMPLATE_NAME", None)
        try:
            assert sinch_rcs._ivr_template() == DEFAULT_TEMPLATE
            os.environ["NOTIF_RCS_TEMPLATE_NAME"] = "rcsmenu_apex"
            assert sinch_rcs._ivr_template() == "rcsmenu_apex", (
                "the template must be overridable without a deploy; an approved RCS body "
                "cannot be edited, so switching template is the only repair available"
            )
        finally:
            os.environ.pop("NOTIF_RCS_TEMPLATE_NAME", None)
            if previous is not None:
                os.environ["NOTIF_RCS_TEMPLATE_NAME"] = previous

    def test_rcs_is_opt_in_and_defaults_off(self):
        from lambda_utils import sinch_rcs

        assert "SINCH_RCS_ENABLED" in code_only(SINCH)
        assert sinch_rcs.is_rcs_enabled() is False, (
            "with the flag unset the sender must be off; it is an opt-in")

    def test_the_recorded_opt_ins_are_the_specified_ones(self):
        import json

        manifest = json.loads((ROOT / "config" / "lambda-env-manifest.json").read_text())
        opted_in = tuple(sorted(fn for fn, env in manifest["functions"].items()
                                if env.get("SINCH_RCS_ENABLED") == "true"))
        assert opted_in == RCS_ENABLED_FUNCTIONS


class TestRecipientIdentity:
    """India only, and refuse rather than rewrite."""

    def test_indian_forms_are_accepted(self):
        from lambda_utils import sinch_rcs

        for value in ("+919903300044", "919903300044", "9903300044",
                      "+91 99033 00044"):
            assert sinch_rcs._normalize_phone(value) == "919903300044", value

    def test_the_ambiguous_std_trunk_form_is_refused(self):
        """`0` + ten digits is the Indian STD prefix AND the UK national format.

        `07911123456` (UK) has the same shape and its ten digits also start in 6-9, so
        assuming India would be the fabrication bug again, just narrower. Measured: all 13
        ContactsTable rows store `+91` E.164 and zero leading-zero forms exist, so accepting
        it bought nothing and made this sender disagree with `notifications.policy`.
        """
        from lambda_utils import sinch_rcs

        assert sinch_rcs._normalize_phone("09903300044") == ""
        assert sinch_rcs._normalize_phone("07911123456") == ""

    def test_the_qa_recipient_is_accepted(self):
        from lambda_utils import sinch_rcs

        assert sinch_rcs._normalize_phone("+918100640044") == "918100640044"

    def test_foreign_numbers_are_refused_not_rewritten(self):
        """The defect: several countries are exactly 10 digits in full E.164.

        `+65 8123 4567` used to become `916581234567` - a real and different Indian
        subscriber - and the provider accepted it, so the message reached a stranger with
        nothing reporting a fault.
        """
        from lambda_utils import sinch_rcs

        for value in ("+6581234567", "+14155552671", "+85212345678", "+4512345678"):
            assert sinch_rcs._normalize_phone(value) == "", (
                f"{value} must be refused, never coerced into an Indian identity")

    def test_the_old_rule_is_gone_from_both_senders(self):
        for path in (RCS_SEND, SINCH):
            code = code_only(path)
            assert "'91' + clean[-10:]" not in code
            assert "'91' + clean[-10:]" not in code.replace(" ", "")

    def test_there_is_one_country_authority(self):
        """Both senders defer to lambda_utils.comms.numbers. Two copies is how they drifted."""
        for path in (RCS_SEND, SINCH):
            assert "comms import numbers" in code_only(path), (
                f"{path.name} must use lambda_utils.comms.numbers for country logic")

    def test_empty_and_junk_are_refused(self):
        from lambda_utils import sinch_rcs

        for value in ("", "   ", "12345", "abc"):
            assert sinch_rcs._normalize_phone(value) == ""


class TestSendPayloadShape:
    """The Conversation API body the owner specified."""

    def test_template_send_builds_the_specified_shape(self):
        code = code_only(RCS_SEND)
        for fragment in ("'app_id'", "identified_by", "channel_identities",
                         "'RCS'", "template_message", "channel_template",
                         "template_id", "language_code"):
            assert fragment in code, f"send payload is missing {fragment}"

    def test_identity_carries_no_plus_prefix(self):
        """Sinch Conversation API identity is digits only."""
        from lambda_utils import sinch_rcs

        identity = sinch_rcs._normalize_phone("+919903300044")
        assert identity == "919903300044"
        assert not identity.startswith("+")


class TestEligibilityAndSendingAgree:
    """India-only must be decided at eligibility time, not just refused at send time.

    Two layers make the same country decision:

      `notifications.policy.decide_rcs`  chooses a provider and creates a delivery row
      `sinch_rcs._normalize_phone`       builds the identity, or refuses

    If they disagree, one of two bad things happens. Either eligibility says Sinch and the
    sender refuses - producing a delivery row that no-ops with nothing reporting a fault -
    or eligibility says non-India and routes to AWS RCS, which is not provisioned, so a
    reachable Indian customer silently loses the channel.

    They disagreed until this was written: `decide_rcs` called `numbers.is_india` on the raw
    destination, and `is_india('9903300044')` is False while
    `is_india(to_e164('9903300044'))` is True. A bare ten-digit Indian mobile was reported
    as `INELIGIBLE_UNSUPPORTED: non-India RCS requires AWS End User Messaging RCS` - wrong
    verdict, misleading reason - while the sender would have accepted it.
    """

    #: (destination, sinch_is_the_right_answer)
    CASES = (
        ("+919903300044", True),
        ("919903300044", True),
        ("9903300044", True),          # bare Indian mobile: the case that disagreed
        ("+918100640044", True),       # the owner-nominated QA recipient
        ("09903300044", False),        # ambiguous with the UK national format
        ("+6581234567", False),        # Singapore: 10 digits in full E.164
        ("+14155552671", False),
        ("+85212345678", False),
        ("+4512345678", False),
        ("", False),
    )

    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setenv("SINCH_RCS_ENABLED", "true")

    @pytest.mark.parametrize("destination,expected", CASES)
    def test_both_layers_reach_the_same_verdict(self, destination, expected):
        from lambda_utils import sinch_rcs
        from lambda_utils.notifications import policy

        decision = policy.decide_rcs(destination)
        policy_says_sinch = bool(decision.eligible) and decision.provider == "sinch-rcs"
        sender_accepts = bool(sinch_rcs._normalize_phone(destination))

        assert policy_says_sinch == expected, (
            f"policy verdict for {destination!r} is {policy_says_sinch}, expected {expected}"
            f" ({decision.reason})")
        assert sender_accepts == expected, (
            f"sender verdict for {destination!r} is {sender_accepts}, expected {expected}")

    def test_non_india_is_never_routed_to_sinch(self):
        """Sinch is approved for India only and is not a non-India fallback."""
        from lambda_utils.notifications import policy

        for destination in ("+6581234567", "+14155552671", "+4512345678"):
            decision = policy.decide_rcs(destination)
            assert decision.provider != "sinch-rcs", (
                f"{destination} must not be routed to Sinch")

    def test_india_with_the_flag_off_is_ineligible_not_routed_elsewhere(self, monkeypatch):
        """Turning RCS off must not silently promote the message to another provider."""
        monkeypatch.setenv("SINCH_RCS_ENABLED", "false")
        from lambda_utils.notifications import policy

        decision = policy.decide_rcs("+919903300044")
        assert decision.eligible is False
        assert decision.provider == "sinch-rcs"
        assert "SINCH_RCS_ENABLED" in decision.reason

    def test_the_policy_normalises_before_classifying(self):
        """The fix, pinned: classifying a raw destination misreads a bare Indian mobile."""
        code = code_only(SHARED / "lambda_utils" / "notifications" / "policy.py")
        assert "numbers.is_india(destination)" not in code, (
            "classify a normalised number, not the raw destination")
        assert "def _india(" in code
