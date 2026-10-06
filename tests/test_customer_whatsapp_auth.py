"""Tests for isolated customer Cognito -> WhatsApp OTP authentication."""
import importlib.util
import json
import os
from pathlib import Path

import pytest


WABA1 = "2094615664435155"
WABA1_PHONE_ID = "1016149501586345"
WABA2 = "2513394156072604"
WABA2_PHONE_ID = "1055232054343117"

os.environ.setdefault("META_WABA_ID", WABA1)
os.environ.setdefault("META_PHONE_NUMBER_ID", WABA1_PHONE_ID)
os.environ.setdefault("OTP_TEMPLATE_NAME", "wecare_otp")
os.environ.setdefault("OTP_TEMPLATE_LANGUAGE", "en")
# Both WABAs, set before the module is exec'd because the map is parsed at import.
os.environ.setdefault("OTP_WABA_MAP", json.dumps({
    WABA1: {"phone_number_id": WABA1_PHONE_ID,
            "template_name": "wecare_otp", "template_language": "en"},
    WABA2: {"phone_number_id": WABA2_PHONE_ID,
            "template_name": "wecare_otp", "template_language": "en"},
}, separators=(",", ":"), sort_keys=True))

HANDLER = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
)
_spec = importlib.util.spec_from_file_location(
    "customer_whatsapp_auth_under_test", HANDLER
)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)


def _event(trigger, request=None):
    return {
        "triggerSource": trigger,
        "request": request or {},
        "response": {},
    }


def test_initial_challenge_requests_custom_challenge():
    event = _event("DefineAuthChallenge_Authentication", {"session": []})
    result = auth.handler(event, None)
    assert result["response"] == {
        "issueTokens": False,
        "failAuthentication": False,
        "challengeName": "CUSTOM_CHALLENGE",
    }


def test_successful_challenge_issues_tokens():
    event = _event(
        "DefineAuthChallenge_Authentication",
        {
            "session": [{
                "challengeName": "CUSTOM_CHALLENGE",
                "challengeResult": True,
            }]
        },
    )
    result = auth.handler(event, None)
    assert result["response"]["issueTokens"] is True
    assert result["response"]["failAuthentication"] is False


def test_three_failed_challenges_fail_authentication():
    event = _event(
        "DefineAuthChallenge_Authentication",
        {
            "session": [
                {
                    "challengeName": "CUSTOM_CHALLENGE",
                    "challengeResult": False,
                }
                for _ in range(3)
            ]
        },
    )
    result = auth.handler(event, None)
    assert result["response"]["issueTokens"] is False
    assert result["response"]["failAuthentication"] is True


def test_unknown_user_does_not_send_whatsapp(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "_send_otp", lambda *args: sent.append(args))
    event = _event(
        "CreateAuthChallenge_Authentication",
        {
            "userNotFound": True,
            "userAttributes": {},
        },
    )
    result = auth.handler(event, None)
    assert sent == []
    assert (
        result["response"]["publicChallengeParameters"]["destination"]
        == "********"
    )


def test_cross_waba_user_is_rejected_before_send(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "_send_otp", lambda *args: sent.append(args))
    event = _event(
        "CreateAuthChallenge_Authentication",
        {
            "userAttributes": {
                "phone_number": "+919876543210",
                "custom:partner_waba_id": "wrong-waba",
            }
        },
    )
    with pytest.raises(PermissionError):
        auth.handler(event, None)
    assert sent == []


def test_correct_waba_sends_six_digit_otp(monkeypatch):
    sent = []
    monkeypatch.setattr(
        auth,
        "_send_otp",
        lambda phone, otp, route: sent.append((phone, otp)),
    )
    # Within budget: let the send proceed. The throttle itself is exercised below.
    monkeypatch.setattr(auth, "_consume_send_budget", lambda digits: None)
    event = _event(
        "CreateAuthChallenge_Authentication",
        {
            "userAttributes": {
                "phone_number": "+919876543210",
                "custom:partner_waba_id": WABA1,
            }
        },
    )
    result = auth.handler(event, None)

    assert len(sent) == 1
    phone, otp = sent[0]
    assert phone == "+919876543210"
    assert otp.isdigit() and len(otp) == 6
    assert (
        result["response"]["privateChallengeParameters"]["answer"]
        == otp
    )
    assert (
        result["response"]["publicChallengeParameters"]["destination"]
        == "********3210"
    )


def test_verify_accepts_correct_unexpired_code(monkeypatch):
    monkeypatch.setattr(auth.time, "time", lambda: 1_000)
    event = _event(
        "VerifyAuthChallengeResponse_Authentication",
        {
            "privateChallengeParameters": {
                "answer": "123456",
                "expiresAt": "1100",
            },
            "challengeAnswer": "123456",
        },
    )
    assert auth.handler(event, None)["response"]["answerCorrect"] is True


@pytest.mark.parametrize(
    ("answer", "expires_at"),
    [("654321", "1100"), ("123456", "999")],
)
def test_verify_rejects_wrong_or_expired_code(
    monkeypatch, answer, expires_at
):
    monkeypatch.setattr(auth.time, "time", lambda: 1_000)
    event = _event(
        "VerifyAuthChallengeResponse_Authentication",
        {
            "privateChallengeParameters": {
                "answer": "123456",
                "expiresAt": expires_at,
            },
            "challengeAnswer": answer,
        },
    )
    assert auth.handler(event, None)["response"]["answerCorrect"] is False


def test_sender_payload_uses_approved_authentication_template(monkeypatch):
    calls = []

    class _Payload:
        def read(self):
            return b'{"statusCode": 200}'

    class _Lambda:
        def invoke(self, **kwargs):
            calls.append(kwargs)
            return {"StatusCode": 200, "Payload": _Payload()}

    monkeypatch.setattr(auth, "_lambda", _Lambda())
    auth._send_otp("+919876543210", "123456", auth.WABA_ROUTES[WABA1])

    event = json.loads(calls[0]["Payload"].decode("utf-8"))
    body = json.loads(event["body"])

    assert calls[0]["FunctionName"] == "wecare-whatsapp-business-api:live"
    assert event["path"] == "/wa-business/messages/send/template"
    assert body["phoneId"] == WABA1_PHONE_ID
    assert body["templateName"] == "wecare_otp"
    assert body["language"] == "en"
    assert body["components"][0]["parameters"][0]["text"] == "123456"
    # `url`, not `copy_code`. This asserted copy_code and was wrong against the live
    # WABA: wecare_otp is an AUTHENTICATION template whose copy-code affordance Meta
    # materialises as a real URL button (.../otp/code/?...&code=otp{{1}}), so the OTP is
    # a text substitution into that URL. Sending copy_code with a coupon_code parameter
    # is refused outright:
    #   (#132018) buttons: Button at index 0 must be of type Url
    # which surfaces to the caller only as "sender returned HTTP 400". Confirmed by a
    # live round trip 2026-09-25: copy_code fails, url succeeds.
    assert body["components"][1]["sub_type"] == "url"
    assert body["components"][1]["parameters"][0] == {"type": "text", "text": "123456"}


# ── send throttle (G5): a REGISTERED number is bounded, fail-closed ──────────────
#
# The gap this closes: the browser calls Cognito's public InitiateAuth directly
# (src/lib/customerAuth.ts), so before this a registered number had NO send limit and a
# loop drove unbounded WhatsApp messages to a real handset. The trigger is the one place
# that can bound the send regardless of how the flow was entered.

import sys as _sys  # noqa: E402

_sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
_sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402

SEND_TABLE = 'stack-wecare-digital-DownloadGrantsTable'


def _registered_event():
    return _event(
        "CreateAuthChallenge_Authentication",
        {"userAttributes": {"phone_number": "+919876543210",
                            "custom:partner_waba_id": WABA1}},
    )


def _wire_fake_table(monkeypatch):
    fake = FakeDynamo(keys={SEND_TABLE: 'grantId'})
    monkeypatch.setattr(auth, "_ddb", fake)
    return fake


def test_send_is_bounded_and_then_suppressed(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "_send_otp",
                        lambda phone, otp, route: sent.append((phone, otp)))
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)
    _wire_fake_table(monkeypatch)

    # SEND_MAX_PER_WINDOW defaults to 5: the first five sends go, the sixth is suppressed.
    for _ in range(auth.SEND_MAX_PER_WINDOW):
        result = auth.handler(_registered_event(), None)
        # A code is always issued regardless, so the Cognito flow is unchanged.
        assert result["response"]["privateChallengeParameters"]["answer"].isdigit()
    assert len(sent) == auth.SEND_MAX_PER_WINDOW

    suppressed = auth.handler(_registered_event(), None)
    # No sixth message, but the response is indistinguishable from a normal issue.
    assert len(sent) == auth.SEND_MAX_PER_WINDOW
    assert suppressed["response"]["publicChallengeParameters"]["registered"] == "true"
    assert suppressed["response"]["privateChallengeParameters"]["answer"].isdigit()


def test_send_throttle_fails_closed_on_storage_error(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "_send_otp",
                        lambda phone, otp, route: sent.append((phone, otp)))
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)
    fake = _wire_fake_table(monkeypatch)
    fake.arm_failure(SEND_TABLE, "update_item", FakeClientError("InternalServerError"))

    result = auth.handler(_registered_event(), None)
    # Fail closed: the message is NOT sent when the counter cannot be read.
    assert sent == []
    # But the challenge is still issued, so the flow does not break.
    assert result["response"]["privateChallengeParameters"]["answer"].isdigit()


def test_send_budget_resets_after_the_window(monkeypatch):
    sent = []
    monkeypatch.setattr(auth, "_send_otp",
                        lambda phone, otp, route: sent.append((phone, otp)))
    _wire_fake_table(monkeypatch)

    base = 1_700_000_000
    monkeypatch.setattr(auth.time, "time", lambda: base)
    for _ in range(auth.SEND_MAX_PER_WINDOW):
        auth.handler(_registered_event(), None)
    # Sixth in-window is suppressed.
    auth.handler(_registered_event(), None)
    assert len(sent) == auth.SEND_MAX_PER_WINDOW

    # Past the window, the counter resets and a send goes again.
    monkeypatch.setattr(auth.time, "time", lambda: base + auth.SEND_WINDOW_SECONDS + 1)
    auth.handler(_registered_event(), None)
    assert len(sent) == auth.SEND_MAX_PER_WINDOW + 1


# ── multi-WABA routing: the customer's own WABA sends, and nothing else does ─────
#
# Before this, one pinned phone-number id meant every OTP left from WABA1 and a
# WABA2-scoped customer was refused outright. These assert on the body the sender Lambda
# would actually receive, not on a stub call, because the mapping only matters at the
# payload - a correct lookup that still writes the old `phoneId` would pass a stub test.

class _Payload:
    def __init__(self, raw=b'{"statusCode": 200}'):
        self._raw = raw

    def read(self):
        return self._raw


class _CapturingLambda:
    def __init__(self, raw=b'{"statusCode": 200}'):
        self.calls = []
        self._raw = raw

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 200, "Payload": _Payload(self._raw)}

    def sent_body(self):
        event = json.loads(self.calls[0]["Payload"].decode("utf-8"))
        return json.loads(event["body"])


def _waba_event(waba_id):
    attributes = {"phone_number": "+919876543210"}
    if waba_id is not None:
        attributes["custom:partner_waba_id"] = waba_id
    return _event("CreateAuthChallenge_Authentication",
                  {"userAttributes": attributes})


@pytest.mark.parametrize(
    ("waba_id", "phone_id"),
    [(WABA1, WABA1_PHONE_ID), (WABA2, WABA2_PHONE_ID)],
)
def test_each_waba_sends_from_its_own_number(monkeypatch, waba_id, phone_id):
    fake = _CapturingLambda()
    monkeypatch.setattr(auth, "_lambda", fake)
    monkeypatch.setattr(auth, "_consume_send_budget", lambda digits: None)

    auth.handler(_waba_event(waba_id), None)

    body = fake.sent_body()
    assert body["phoneId"] == phone_id
    assert body["templateName"] == "wecare_otp"
    assert body["language"] == "en"


@pytest.mark.parametrize("waba_id", ["9999999999999999", None, "", "wrong-waba"])
def test_an_unsupported_waba_fails_closed_with_no_send(monkeypatch, capsys, waba_id):
    """No map entry, no send - and specifically no fallback to WABA1.

    `None` is the important row: an operator who forgets the attribute entirely must not
    get a code from an arbitrary business number, which is what any `or <first waba>`
    default would produce.
    """
    fake = _CapturingLambda()
    monkeypatch.setattr(auth, "_lambda", fake)
    monkeypatch.setattr(auth, "_consume_send_budget", lambda digits: None)

    with pytest.raises(PermissionError):
        auth.handler(_waba_event(waba_id), None)

    assert fake.calls == []
    out = capsys.readouterr().out
    assert "customer_whatsapp_otp_denied" in out
    assert '"reason": "unknown_waba"' in out
    # No phone number, in any form, in the denial record.
    assert "9876543210" not in out
    assert "3210" not in out


def test_the_denial_log_echoes_a_waba_id_but_never_a_phone_shaped_value(capsys):
    """A mistyped WABA id is the whole point of the log; a 15-digit value is not safe.

    E.164 allows at most 15 digits, so refusing anything shorter than 16 makes it
    structurally impossible for this field to carry a phone number.
    """
    assert auth._loggable_waba("2513394156072604") == "2513394156072604"
    assert auth._loggable_waba("918100640044") == "invalid"
    assert auth._loggable_waba("123456789012345") == "invalid"
    assert auth._loggable_waba(None) == "invalid"
    assert auth._loggable_waba("2094615664435155 ") == "invalid"
    capsys.readouterr()


# ── observability: the two silent branches now leave a record ───────────────────

def test_the_unknown_user_branch_logs_a_skip_without_any_digit(monkeypatch, capsys):
    """RC-5: "no OTP arrived" for an unprovisioned number used to leave no trace at all.

    The masked suffix is deliberately absent too: `...0044` is ambiguous in this account
    between the QA recipient and a business sender, so the event carries no digit at all.
    """
    _wire_fake_table(monkeypatch)
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)
    event = _event("CreateAuthChallenge_Authentication",
                   {"userNotFound": True, "userAttributes": {}})
    event["userName"] = "+918100640044"

    auth.handler(event, None)

    out = capsys.readouterr().out
    assert "customer_whatsapp_otp_skipped" in out
    assert '"reason": "user_not_found"' in out
    assert not any(ch.isdigit() for ch in out)


def test_the_suppressed_send_reports_rate_limited(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(auth, "_send_otp",
                        lambda phone, otp, route: sent.append((phone, otp)))
    monkeypatch.setattr(auth.time, "time", lambda: 1_700_000_000)
    _wire_fake_table(monkeypatch)

    for _ in range(auth.SEND_MAX_PER_WINDOW + 1):
        auth.handler(_registered_event(), None)

    out = capsys.readouterr().out
    assert "customer_whatsapp_otp_send_suppressed" in out
    assert '"reason": "rate_limited"' in out


# ── Meta 132001: approval does not cross WABAs ──────────────────────────────────

def test_a_meta_template_error_is_logged_with_its_code_and_still_raises(
        monkeypatch, capsys):
    """`wecare_otp` must be APPROVED in WABA2's OWN template list.

    Approval does not cross WABAs. If it is missing, Meta answers 132001 and no code is
    delivered even though the routing is correct. Before this the caller saw only "sender
    returned HTTP 400" with nothing naming the WABA or the Meta code.
    """
    fake = _CapturingLambda(
        raw=b'{"statusCode": 400, "body": "{\\"error\\": {\\"code\\": 132001}}"}')
    monkeypatch.setattr(auth, "_lambda", fake)

    with pytest.raises(RuntimeError):
        auth._send_otp("+919876543210", "123456", auth.WABA_ROUTES[WABA2])

    out = capsys.readouterr().out
    assert "customer_whatsapp_otp_send_failed" in out
    assert "132001" in out
    assert WABA2 in out
    # Not the destination, and not the code that was being sent.
    assert "9876543210" not in out
    assert "123456" not in out


# ── the map itself ──────────────────────────────────────────────────────────────

def _reload_handler(monkeypatch, waba_map):
    """Re-exec the handler module with a different OTP_WABA_MAP, parsed at import."""
    if waba_map is None:
        monkeypatch.delenv("OTP_WABA_MAP", raising=False)
    else:
        monkeypatch.setenv("OTP_WABA_MAP", waba_map)
    spec = importlib.util.spec_from_file_location(
        "customer_whatsapp_auth_reloaded", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_without_the_map_the_function_degrades_to_exactly_todays_behaviour(
        monkeypatch, capsys):
    """A missed env apply must not be a total OTP outage - nor a cross-WABA opening.

    With `OTP_WABA_MAP` absent the map is rebuilt from the legacy single-WABA env pair,
    so WABA1 keeps working exactly as before and WABA2 is still refused.
    """
    reloaded = _reload_handler(monkeypatch, None)
    capsys.readouterr()

    assert set(reloaded.WABA_ROUTES) == {WABA1}
    assert reloaded.WABA_ROUTES[WABA1]["phone_number_id"] == WABA1_PHONE_ID

    monkeypatch.setattr(reloaded, "_consume_send_budget", lambda digits: None)
    fake = _CapturingLambda()
    monkeypatch.setattr(reloaded, "_lambda", fake)
    with pytest.raises(PermissionError):
        reloaded.handler(_waba_event(WABA2), None)
    assert fake.calls == []


def test_an_unusable_map_entry_is_dropped_rather_than_half_used(monkeypatch, capsys):
    """A route with no sender cannot send, so it must not pass the membership test."""
    reloaded = _reload_handler(monkeypatch, json.dumps({
        WABA1: {"phone_number_id": WABA1_PHONE_ID},
        WABA2: {"template_name": "wecare_otp"},   # no phone_number_id
        "": {"phone_number_id": "1"},
    }))
    capsys.readouterr()
    assert set(reloaded.WABA_ROUTES) == {WABA1}
    # Per-entry template/language fall back to the env defaults.
    assert reloaded.WABA_ROUTES[WABA1]["template_name"] == "wecare_otp"
    assert reloaded.WABA_ROUTES[WABA1]["template_language"] == "en"


def test_unparseable_map_falls_back_without_raising(monkeypatch, capsys):
    reloaded = _reload_handler(monkeypatch, "{not json")
    out = capsys.readouterr().out
    assert "waba_map_unparseable" in out
    assert set(reloaded.WABA_ROUTES) == {WABA1}


# ── deployed configuration must agree with the handler ──────────────────────────

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def provisioner():
    import sys
    spec = importlib.util.spec_from_file_location(
        "provision_customer_whatsapp_auth",
        ROOT / "scripts" / "provision_customer_whatsapp_auth.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_customer_whatsapp_auth"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_customer_whatsapp_auth", None)


def test_the_map_agrees_across_handler_provisioner_and_manifest(provisioner):
    """Three copies of the same fact, so all three have to be checked together.

    The handler parses the env; the provisioner defines what the env must be and is what
    `--verify` compares the `live` alias against; the manifest is the recorded inventory.
    A WABA added to one and not the others is a customer who cannot sign in.
    """
    expected = json.loads(provisioner.expected_environment()["OTP_WABA_MAP"])
    manifest = json.loads(
        (ROOT / "config/lambda-env-manifest.json").read_text()
    )["functions"]["wecare-customer-whatsapp-auth"]

    assert manifest["OTP_WABA_MAP"] == provisioner.expected_environment()["OTP_WABA_MAP"]
    assert set(expected) == {WABA1, WABA2} == set(auth.WABA_ROUTES)
    for waba_id, phone_id in ((WABA1, WABA1_PHONE_ID), (WABA2, WABA2_PHONE_ID)):
        assert expected[waba_id]["phone_number_id"] == phone_id
        assert auth.WABA_ROUTES[waba_id]["phone_number_id"] == phone_id
