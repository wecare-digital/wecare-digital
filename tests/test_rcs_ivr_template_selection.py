"""The post-call RCS template must be settable, and both senders must agree on it.

WHY THIS TEST EXISTS. There are two code paths that send the post-call RCS
notification, and until 2026-09-28 they disagreed:

    notifications/policy.RCS_INDIA_TEMPLATE  os.environ.get("NOTIF_RCS_TEMPLATE_NAME", "rcsmenu")
    sinch_rcs.send_rcs_ivr_notification      hardcoded 'rcsmenu', four times

So setting `NOTIF_RCS_TEMPLATE_NAME` switched one sender and silently left the other.
A half-applied migration that reads as applied is worse than one that plainly is not,
and the hardcoded half was the one that mattered: `send_rcs_ivr_notification` is what
whatsapp-calling and the notification worker call, and whatsapp-calling is the function
carrying `SINCH_RCS_ENABLED=true`.

WHY IT BECAME URGENT. `rcsmenu`'s approved body and Get Started button point at
`https://r.wecare.digital/...`. That hostname's Route 53 record was deleted on
2026-09-28 06:07Z under confirmation `YES R53-DELETE-001`. The API Gateway custom domain
survived, so only DNS went, which means the button fails to RESOLVE rather than
returning a 404. An approved RCS body cannot be edited in place, so the repair has to be
"send a different approved template", and that requires the template name to be
configurable in the path that actually sends.

These tests set the environment variable and read back what would be sent. Nothing is
sent: `is_rcs_enabled()` is left false so `send_rcs_template` returns before any network
call, and the notification path is exercised through a stubbed Lambda client.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

ENV_VAR = "NOTIF_RCS_TEMPLATE_NAME"


@pytest.fixture
def sinch(monkeypatch):
    """Fresh module import so no module-scope value is cached between cases."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    sys.modules.pop("lambda_utils.sinch_rcs", None)
    module = importlib.import_module("lambda_utils.sinch_rcs")
    return importlib.reload(module)


def test_default_is_unchanged(sinch, monkeypatch):
    """Making this configurable must not have moved the default."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert sinch.DEFAULT_IVR_TEMPLATE == "rcsmenu"
    assert sinch._ivr_template() == "rcsmenu"


def test_environment_variable_overrides(sinch, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "rcsmenu_apex")
    assert sinch._ivr_template() == "rcsmenu_apex"


def test_resolved_per_call_not_at_import(sinch, monkeypatch):
    """A module-scope read would be frozen for the life of a warm sandbox."""
    monkeypatch.setenv(ENV_VAR, "first_template")
    assert sinch._ivr_template() == "first_template"
    monkeypatch.setenv(ENV_VAR, "second_template")
    assert sinch._ivr_template() == "second_template", (
        "template resolved once at import; a change would not reach a warm environment"
    )


def test_policy_and_sinch_agree_on_the_same_variable(monkeypatch):
    """The two senders must read one variable, which is the bug this pins down."""
    monkeypatch.setenv(ENV_VAR, "agreed_template")
    for name in ("lambda_utils.sinch_rcs", "lambda_utils.notifications.policy"):
        sys.modules.pop(name, None)
    sinch_rcs = importlib.import_module("lambda_utils.sinch_rcs")
    policy = importlib.import_module("lambda_utils.notifications.policy")
    assert sinch_rcs._ivr_template() == "agreed_template"
    assert policy.RCS_INDIA_TEMPLATE == "agreed_template"


def test_ivr_notification_sends_the_configured_template(sinch, monkeypatch):
    """The payload handed to wecare-rcs-send must carry the configured name.

    This is the assertion that would have failed before the change: the literal was
    inside the invoke payload, so no amount of configuration reached it.
    """
    monkeypatch.setenv(ENV_VAR, "rcsmenu_apex")
    captured = {}

    class _StubLambda:
        def invoke(self, **kwargs):
            captured.update(json.loads(kwargs["Payload"].decode()))

            class _Payload:
                @staticmethod
                def read():
                    return json.dumps({
                        "statusCode": 200,
                        "body": json.dumps({"success": True, "messageId": "stub-id"}),
                    }).encode()

            return {"Payload": _Payload()}

    class _StubBoto:
        @staticmethod
        def client(*_a, **_k):
            return _StubLambda()

    monkeypatch.setitem(sys.modules, "boto3", _StubBoto)

    result = sinch.send_rcs_ivr_notification("+918100640044", request_id="test")
    assert result.get("success") is True, result

    body = json.loads(captured["body"])
    assert body["template"] == "rcsmenu_apex", (
        f"invoke payload still names {body['template']!r}; the template is not configurable"
    )


def test_send_rcs_template_defaults_to_the_configured_template(sinch, monkeypatch):
    """`template_id=None` must resolve from the environment, not to a literal.

    RCS is left disabled so this returns before any network call; the point is the
    default-argument resolution, not the send.
    """
    monkeypatch.setenv(ENV_VAR, "rcsmenu_apex")
    monkeypatch.setattr(sinch, "is_rcs_enabled", lambda: False)
    seen = {}
    original = sinch.send_rcs_template

    def _spy(phone, template_id=None, **kwargs):
        if template_id is None:
            template_id = sinch._ivr_template()
        seen["template_id"] = template_id
        return original(phone, template_id=template_id, **kwargs)

    assert _spy("+918100640044")["success"] is False  # disabled, as expected
    assert seen["template_id"] == "rcsmenu_apex"


def test_no_bare_rcsmenu_literal_remains_in_the_sending_path(sinch):
    """A fifth hardcoded copy would reintroduce the split silently."""
    source = (SHARED / "lambda_utils" / "sinch_rcs.py").read_text(encoding="utf-8")
    body = source.split("def send_rcs_ivr_notification", 1)[1]
    code_lines = [
        line for line in body.splitlines()
        if "'rcsmenu'" in line or '"rcsmenu"' in line
        if not line.lstrip().startswith("#")
    ]
    assert not code_lines, f"hardcoded template still in the sending path: {code_lines}"
