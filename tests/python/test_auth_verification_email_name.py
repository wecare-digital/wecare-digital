"""CA-4: the public `firstName` field is one short line before it reaches the email."""
import importlib.util
import json
from pathlib import Path

import pytest

from lambda_utils import otp_challenge
from lambda_utils.comms import verification_email as ve

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("raw,expected", [
    ("Asha", "Asha"),
    ("  Asha   Rao ", "Asha Rao"),
    ("Asha\r\nYour account is locked. Call +1 555 0100", "Asha Your account is locked. Call +1 555 0100"),
    ("Asha\tRao\x00\x1b[31m", "Asha Rao [31m"),
    ("Asha\u2028Rao\u2029\u0085x", "Asha Rao x"),
    ("evil\u202egnp.exe", "evilgnp.exe"),
    ("\u0928\u093f\u0927\u093f\u200d", "\u0928\u093f\u0927\u093f\u200d"),
    (None, ""),
    (12345, "12345"),
])
def test_clean_first_name(raw, expected):
    assert ve.clean_first_name(raw) == expected


def test_clean_first_name_caps_the_length():
    cleaned = ve.clean_first_name("A" * 500)
    assert cleaned == "A" * ve.FIRST_NAME_MAX == "A" * 60
    assert ve.clean_first_name(("B" * 59) + " " + ("C" * 10)) == "B" * 59


def test_plain_text_and_html_bodies_carry_one_short_line():
    hostile = "Asha\nVisit evil.example to unlock\n" + "x" * 200
    text = ve.text_body("123456", first_name=hostile)
    greeting = text.splitlines()[0]
    assert greeting == f"Hi {ve.clean_first_name(hostile)},"
    assert len(greeting) <= ve.FIRST_NAME_MAX + 4
    assert "\nVisit evil.example" not in text
    html_body = ve.html_body("123456", first_name="<b>Asha</b>\n")
    assert "Hi &lt;b&gt;Asha&lt;/b&gt;," in html_body


def test_email_request_sends_the_cleaned_name(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "email_verify_name", ROOT / "amplify/functions/auth/email-verification/handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    sent = {}
    monkeypatch.setattr(handler.otp_throttle, "check_and_consume", lambda *a, **k: (1, 1))
    monkeypatch.setattr(handler, "_table", lambda: object())
    monkeypatch.setattr(handler, "_pepper", lambda: "pepper")
    monkeypatch.setattr(handler, "_ses_client", lambda: object())
    monkeypatch.setattr(handler.otp_challenge, "issue",
                        lambda *a, **k: otp_challenge.IssuedChallenge("123456", 2000, 1, 600))
    monkeypatch.setattr(handler.verification_email, "send",
                        lambda client, **kwargs: sent.update(kwargs) or "msg")
    event = {"requestContext": {"http": {"method": "POST", "sourceIp": "198.51.100.1"}},
             "headers": {"origin": "https://wecare.digital"},
             "body": json.dumps({"action": "request", "email": "a@example.com",
                                 "firstName": "Asha\r\nCall now " + "y" * 100})}
    assert handler.handler(event, None)["statusCode"] == 200
    assert sent["first_name"] == ve.clean_first_name("Asha\r\nCall now " + "y" * 100)
    assert "\n" not in sent["first_name"] and len(sent["first_name"]) == 60
