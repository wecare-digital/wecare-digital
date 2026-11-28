"""CA-6: the email and registration verify endpoints are throttled per subject and per IP,
and the email send throttle is keyed on the email rather than the optional phone field."""
import importlib.util
import json
from pathlib import Path

import pytest

from lambda_utils import otp_challenge, otp_throttle
from lambda_utils.identity import registration

ROOT = Path(__file__).resolve().parents[2]


def _load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Counters:
    """Records the throttle keys check_and_consume increments."""

    def __init__(self):
        self.counts = {}
        self.started = {}

    def update_item(self, *, Key, ExpressionAttributeValues, **kwargs):
        key = Key["grantId"]
        self.counts[key] = self.counts.get(key, 0) + 1
        self.started.setdefault(key, ExpressionAttributeValues[":now"])
        return {"Attributes": {"attempts": self.counts[key],
                               "windowStartedAt": self.started[key]}}


def _event(body, ip="198.51.100.1"):
    return {"requestContext": {"http": {"method": "POST", "sourceIp": ip}},
            "headers": {"origin": "https://wecare.digital"}, "body": json.dumps(body)}


def _keys(counters, prefix):
    return {k: v for k, v in counters.counts.items() if k.startswith(prefix)}


@pytest.fixture
def email(monkeypatch):
    module = _load("amplify/functions/auth/email-verification/handler.py", "email_verify_throttle")
    counters = Counters()
    monkeypatch.setattr(module, "_table", lambda: counters)
    monkeypatch.setattr(module, "_pepper", lambda: "pepper")
    monkeypatch.setattr(module, "_ses_client", lambda: object())
    module.counters = counters
    return module


def test_email_send_throttle_ignores_the_phone_field(email, monkeypatch):
    issued = otp_challenge.IssuedChallenge("123456", 2000, 1, 600)
    monkeypatch.setattr(email.otp_challenge, "issue", lambda *a, **k: issued)
    monkeypatch.setattr(email.verification_email, "send", lambda *a, **k: "msg")
    for phone in ("+6591234567", "+6591234568", "not a phone", None):
        reply = email.handler(_event({"action": "request", "email": "A@Example.com",
                                      "phone": phone}), None)
        assert reply["statusCode"] == 200
    subject = otp_throttle.PHONE_PREFIX + otp_throttle._hashed("a@example.com")
    assert _keys(email.counters, otp_throttle.PHONE_PREFIX) == {subject: 4}


def test_email_verify_is_throttled_per_email_and_ip_in_its_own_buckets(email, monkeypatch):
    verdicts = []
    monkeypatch.setattr(email.otp_challenge, "verify",
                        lambda *a, **k: verdicts.append(1) or otp_challenge.VerificationResult(
                            otp_challenge.CODE_INCORRECT, 1))
    body = {"action": "verify", "email": "a@example.com", "code": "000000"}
    replies = [email.handler(_event(body), None)
               for _ in range(otp_throttle.DEFAULT_VERIFY_SUBJECT_MAX + 1)]
    assert [r["statusCode"] for r in replies] == [400] * otp_throttle.DEFAULT_VERIFY_SUBJECT_MAX + [429]
    assert len(verdicts) == otp_throttle.DEFAULT_VERIFY_SUBJECT_MAX
    tag = otp_throttle.VERIFY_SCOPE + "#"
    assert set(email.counters.counts) == {
        otp_throttle.PHONE_PREFIX + tag + otp_throttle._hashed("a@example.com"),
        otp_throttle.IP_PREFIX + tag + otp_throttle._hashed("198.51.100.1"),
    }
    assert replies[-1]["headers"]["Cache-Control"] == "no-store"


def test_email_verify_ip_axis_spans_addresses(email, monkeypatch):
    monkeypatch.setattr(email.otp_challenge, "verify", lambda *a, **k:
                        otp_challenge.VerificationResult(otp_challenge.NO_CHALLENGE))
    statuses = [email.handler(_event({"action": "verify", "email": f"u{n}@example.com",
                                      "code": "000000"}), None)["statusCode"]
                for n in range(otp_throttle.DEFAULT_VERIFY_IP_MAX + 1)]
    assert statuses[-1] == 429 and set(statuses[:-1]) == {400}


def test_email_verify_fails_closed_when_the_counter_is_unavailable(email, monkeypatch):
    class Down:
        def update_item(self, **kwargs):
            raise RuntimeError("dynamodb unavailable")

    monkeypatch.setattr(email, "_table", lambda: Down())
    called = []
    monkeypatch.setattr(email.otp_challenge, "verify", lambda *a, **k: called.append(1))
    reply = email.handler(_event({"action": "verify", "email": "a@example.com",
                                  "code": "000000"}), None)
    assert reply["statusCode"] == 503 and called == []


def _complete(counters, phone="+919000000001", ip="198.51.100.1", verdict=None):
    calls = []

    def verify(*args, **kwargs):
        calls.append(kwargs["subject"])
        return verdict or otp_challenge.VerificationResult(otp_challenge.CODE_INCORRECT, 1)

    original = registration.otp_challenge.verify
    registration.otp_challenge.verify = verify
    try:
        result = registration.complete(
            raw_phone=phone, code="000000",
            event={"requestContext": {"http": {"sourceIp": ip}}},
            throttle_table=counters, challenge_table=object(), pepper="pepper",
            resolve_customer=lambda e164: None, create_customer=lambda e164: {},
            provision_login=lambda e164, cid: None, now=1000)
    finally:
        registration.otp_challenge.verify = original
    return result, calls


def test_registration_verify_is_throttled_per_phone_before_the_code_check():
    counters = Counters()
    results = [_complete(counters) for _ in range(otp_throttle.DEFAULT_VERIFY_SUBJECT_MAX + 1)]
    assert [r.outcome for r, _ in results[:-1]] == [registration.CODE_REJECTED] * 10
    last, calls = results[-1]
    assert last.outcome == registration.THROTTLED and last.http_status() == 429
    assert calls == []
    tag = otp_throttle.VERIFY_SCOPE + "#"
    assert otp_throttle.PHONE_PREFIX + tag + otp_throttle._hashed("+919000000001") \
        in counters.counts


def test_registration_verify_ip_axis_and_store_failure():
    counters = Counters()
    outcomes = [_complete(counters, phone=f"+9190000001{n:02d}")[0].outcome
                for n in range(otp_throttle.DEFAULT_VERIFY_IP_MAX + 1)]
    assert outcomes[-1] == registration.THROTTLED

    class Down:
        def update_item(self, **kwargs):
            raise RuntimeError("dynamodb unavailable")

    result, calls = _complete(Down())
    assert result.outcome == registration.STORE_UNAVAILABLE and calls == []


def test_registration_handler_passes_the_event_and_throttle_table():
    source = (ROOT / "amplify/functions/auth/customer-registration/handler.py").read_text()
    call = source[source.index("registration.complete("):]
    call = call[:call.index(")\n")]
    assert "event=event" in call and "throttle_table=_table()" in call
