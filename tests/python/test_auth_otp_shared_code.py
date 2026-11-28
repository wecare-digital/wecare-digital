"""CA-1, CA-2, CA-5: one shared WhatsApp sign-in code per phone in the standalone trigger.

The fake table supports only UpdateItem, like the function's role, and evaluates the
handler's own condition and update expressions, so the tests exercise the real expressions.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/auth/customer-whatsapp-auth/handler.py")
WABA = "2094615664435155"
PHONE = "+919000000001"
DIGITS = "919000000001"


def _conditional_failure():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")


def _operand(token, item, values):
    return values[token] if token.startswith(":") else item.get(token)


def _term(term, item, values):
    term = term.strip()
    match = re.fullmatch(r"attribute_(not_)?exists\((\w+)\)", term)
    if match:
        present = match.group(2) in item
        return not present if match.group(1) else present
    left, op, right = re.fullmatch(r"(\S+) (<=|>=|<|>|=) (\S+)", term).groups()
    a, b = _operand(left, item, values), _operand(right, item, values)
    if a is None or b is None:
        return False
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "=": a == b}[op]


def _condition(expression, item, values):
    return any(all(_term(t, item, values) for t in alternative.split(" AND "))
               for alternative in expression.split(" OR "))


def _apply(expression, item, values):
    for clause in re.split(r"\s+(?=(?:SET|ADD|REMOVE) )", expression.strip()):
        action, _, body = clause.partition(" ")
        for part in (p.strip() for p in body.split(",")):
            if action == "SET":
                name, _, value = part.partition(" = ")
                item[name.strip()] = values[value.strip()]
            elif action == "ADD":
                name, value = part.split()
                item[name] = item.get(name, 0) + values[value]
            else:
                item.pop(part, None)


class UpdateOnlyTable:
    def __init__(self):
        self.rows = {}
        self.calls = 0

    def update_item(self, *, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeValues=None, ReturnValues="NONE"):
        self.calls += 1
        values = ExpressionAttributeValues or {}
        current = dict(self.rows.get(Key["grantId"]) or {})
        if ConditionExpression and not _condition(ConditionExpression, current, values):
            raise _conditional_failure()
        updated = current or dict(Key)
        _apply(UpdateExpression, updated, values)
        self.rows[Key["grantId"]] = updated
        return {"Attributes": dict(updated)} if ReturnValues == "ALL_NEW" else {}


class BrokenTable:
    calls = 0

    def update_item(self, **kwargs):
        self.calls += 1
        raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "UpdateItem")


@pytest.fixture
def otp(monkeypatch):
    spec = importlib.util.spec_from_file_location("otp_shared_code_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = {"now": 1_000_000, "sent": [], "table": UpdateOnlyTable()}
    monkeypatch.setattr(module.time, "time", lambda: state["now"])
    monkeypatch.setattr(module, "_probe_table", lambda: state["table"])

    def send(phone, code, route):
        state["sent"].append(code)
        return "template"

    monkeypatch.setattr(module, "_send_otp", send)
    module.state = state
    return module


def _event(trigger, *, user_not_found=False, user_name=PHONE, **request):
    body = {"userAttributes": {"phone_number": PHONE, "custom:partner_waba_id": WABA}}
    if user_not_found:
        body = {"userAttributes": {}, "userNotFound": True}
    body.update(request)
    return {"triggerSource": trigger, "userName": user_name, "request": body, "response": {}}


def create(otp, **kwargs):
    return otp.handler(_event("CreateAuthChallenge_Authentication", **kwargs), None)["response"]


def verify(otp, answer):
    event = _event("VerifyAuthChallengeResponse_Authentication", challengeAnswer=answer)
    return otp.handler(event, None)["response"]["answerCorrect"]


def define(otp, *results, **kwargs):
    session = [{"challengeName": "CUSTOM_CHALLENGE", "challengeResult": r} for r in results]
    return otp.handler(_event("DefineAuthChallenge_Authentication", session=session, **kwargs),
                       None)["response"]


def code_row(otp):
    return otp.state["table"].rows.get("otpcode#" + DIGITS) or {}


def wrong(code):
    return "000000" if code != "000000" else "111111"


def test_a_sent_code_is_stored_only_as_a_salted_hash(otp):
    response = create(otp)
    code, = otp.state["sent"]
    row = code_row(otp)
    assert set(row) == {"grantId", "codeSalt", "codeHash", "expiresAt", "attempts"}
    assert row["expiresAt"] == 1_000_000 + otp.OTP_TTL_SECONDS and row["attempts"] == 0
    assert code not in repr(row) and code not in repr(response)
    assert response["privateChallengeParameters"] == {"challenge": "WHATSAPP_OTP"}
    assert response["publicChallengeParameters"]["registered"] == "true"


def test_new_sessions_reuse_the_active_code_without_a_send(otp):
    first = create(otp)
    again = create(otp)
    create(otp)
    assert len(otp.state["sent"]) == 1
    assert otp.state["table"].rows["otpsend#" + DIGITS]["sends"] == 1
    assert again["publicChallengeParameters"] == first["publicChallengeParameters"]


def test_wrong_answers_count_per_phone_across_sessions_and_exhaust_the_code(otp):
    create(otp)
    code = otp.state["sent"][0]
    for _ in range(3):
        assert verify(otp, wrong(code)) is False
    assert define(otp, False)["challengeName"] == "CUSTOM_CHALLENGE"
    assert define(otp, False, False, False)["failAuthentication"] is True
    create(otp)  # a new Cognito session keeps the same code and its count
    assert len(otp.state["sent"]) == 1
    assert verify(otp, wrong(code)) is False
    assert verify(otp, wrong(code)) is False
    assert code_row(otp)["attempts"] == otp.CODE_MAX_ATTEMPTS
    assert define(otp, False) == {"issueTokens": False, "failAuthentication": True}
    assert verify(otp, code) is False


def test_the_fifth_answer_still_counts_and_a_sixth_is_not_compared(otp):
    create(otp)
    code = otp.state["sent"][0]
    for _ in range(otp.CODE_MAX_ATTEMPTS - 1):
        assert verify(otp, wrong(code)) is False
    assert verify(otp, code) is True
    assert code_row(otp)["attempts"] == otp.CODE_MAX_ATTEMPTS
    assert verify(otp, code) is False


def test_a_correct_code_signs_in_once(otp):
    create(otp)
    code = otp.state["sent"][0]
    assert verify(otp, code) is True
    assert define(otp, True) == {"issueTokens": True, "failAuthentication": False}
    assert "codeHash" not in code_row(otp)
    assert define(otp, True) == {"issueTokens": False, "failAuthentication": True}
    assert verify(otp, code) is False


def test_exhausted_used_or_expired_codes_are_replaced_by_a_new_send(otp):
    create(otp)
    first = otp.state["sent"][0]
    for _ in range(otp.CODE_MAX_ATTEMPTS):
        verify(otp, wrong(first))
    create(otp)
    second = otp.state["sent"][1]
    assert code_row(otp)["attempts"] == 0 and second  # new code, fresh count
    otp.state["now"] += otp.OTP_TTL_SECONDS
    assert verify(otp, second) is False  # expired: refused and not counted
    assert code_row(otp)["attempts"] == 0
    assert define(otp, False)["challengeName"] == "CUSTOM_CHALLENGE"
    create(otp)
    assert len(otp.state["sent"]) == 3


def test_over_budget_with_no_active_code_stores_nothing(otp):
    otp.state["table"].rows["otpsend#" + DIGITS] = {
        "grantId": "otpsend#" + DIGITS, "sends": otp.SEND_MAX_PER_WINDOW,
        "windowStartedAt": 1_000_000, "expiresAt": 1_003_600}
    response = create(otp)
    assert otp.state["sent"] == [] and code_row(otp) == {}
    assert response["publicChallengeParameters"]["registered"] == "true"
    assert verify(otp, "123456") is False


def test_a_failed_send_discards_the_code(otp, monkeypatch):
    def down(phone, code, route):
        raise RuntimeError("sender returned HTTP 500")

    monkeypatch.setattr(otp, "_send_otp", down)
    with pytest.raises(RuntimeError):
        create(otp)
    assert "codeHash" not in code_row(otp)
    monkeypatch.setattr(otp, "_send_otp",
                        lambda phone, code, route: otp.state["sent"].append(code) or "template")
    create(otp)
    assert len(otp.state["sent"]) == 1


def test_store_errors_fail_closed(otp):
    otp.state["table"] = BrokenTable()
    with pytest.raises(otp.OtpCodeUnavailable):
        create(otp)
    assert otp.state["sent"] == []
    assert verify(otp, "123456") is False
    assert define(otp, False) == {"issueTokens": False, "failAuthentication": True}
    assert define(otp, True) == {"issueTokens": False, "failAuthentication": True}


@pytest.mark.parametrize("answer", ["", "12345", "1234567", "12 456", "abcdef",
                                    "\u0661\u0662\u0663\u0664\u0665\u0666"])
def test_malformed_answers_never_reach_the_store(otp, answer):
    create(otp)
    calls = otp.state["table"].calls
    assert verify(otp, answer) is False
    assert otp.state["table"].calls == calls
    assert code_row(otp)["attempts"] == 0


def test_unknown_numbers_keep_the_existing_define_and_verify_behaviour(otp):
    assert define(otp, False, user_not_found=True)["challengeName"] == "CUSTOM_CHALLENGE"
    event = _event("VerifyAuthChallengeResponse_Authentication", user_not_found=True,
                   challengeAnswer="123456")
    assert otp.handler(event, None)["response"]["answerCorrect"] is False
    assert otp.state["table"].calls == 0


def test_over_budget_unknown_number_has_the_registered_shape(otp, monkeypatch):
    registered = create(otp)["publicChallengeParameters"]
    monkeypatch.setattr(otp, "_probe_budget_exhausted", lambda digits: True)
    unknown = create(otp, user_not_found=True, user_name="+919000000002")
    assert unknown["publicChallengeParameters"] == {**registered, "destination": "********0002"}
    assert registered["destination"] == "********0001"
    monkeypatch.setattr(otp, "_probe_budget_exhausted", lambda digits: False)
    revealed = create(otp, user_not_found=True, user_name="+919000000002")
    assert revealed["publicChallengeParameters"]["registered"] == "false"


def test_handler_stays_standalone():
    source = HANDLER.read_text()
    assert not re.search(r"^\s*(from|import)\s+lambda_utils", source, re.MULTILINE)
