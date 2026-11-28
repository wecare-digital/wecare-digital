"""CA-1, CA-2, CA-5: one WhatsApp sign-in code per phone in the standalone trigger.

A new sign-in under the send budget replaces the phone's code and sends it. Wrong answers
are counted per phone across codes, and ten in an hour lock the phone until the window
passes.

The fake table supports only UpdateItem, like the function's role, and evaluates the
handler's own condition and update expressions, so the tests exercise the real expressions.
"""
import importlib.util
import itertools
import operator
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/auth/customer-whatsapp-auth/handler.py")
WABA = "2094615664435155"
PHONE = "+919000000001"
DIGITS = "919000000001"
START = 1_000_000
# Codes run from 100000 to 999999, so this six-digit answer is always wrong.
WRONG = "000000"
CHALLENGE = {"issueTokens": False, "failAuthentication": False,
             "challengeName": "CUSTOM_CHALLENGE"}
FAILED = {"issueTokens": False, "failAuthentication": True}
SIGNED_IN = {"issueTokens": True, "failAuthentication": False}


def _conditional_failure():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")


_TOKEN = re.compile(r"\s*(\(|\)|<=|>=|<>|<|>|=|attribute_(?:not_)?exists\(\w+\)|:?\w+)")
_COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
            "=": operator.eq, "<>": operator.ne}


def _tokens(expression):
    tokens, position, expression = [], 0, expression.strip()
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        assert match, f"cannot parse {expression[position:]!r}"
        tokens.append(match.group(1))
        position = match.end()
    return tokens


def _condition(expression, item, values):
    """Evaluate a condition with DynamoDB's precedence: NOT, then AND, then OR.

    As in DynamoDB, a comparison with a missing attribute is false.
    """
    tokens = _tokens(expression)

    def disjunction():
        result = conjunction()
        while tokens and tokens[0] == "OR":
            tokens.pop(0)
            right = conjunction()
            result = result or right
        return result

    def conjunction():
        result = negation()
        while tokens and tokens[0] == "AND":
            tokens.pop(0)
            right = negation()
            result = result and right
        return result

    def negation():
        if tokens[0] == "NOT":
            tokens.pop(0)
            return not negation()
        return primary()

    def primary():
        token = tokens.pop(0)
        if token == "(":
            result = disjunction()
            assert tokens.pop(0) == ")"
            return result
        match = re.fullmatch(r"attribute_(not_)?exists\((\w+)\)", token)
        if match:
            present = match.group(2) in item
            return not present if match.group(1) else present
        op, right = tokens.pop(0), tokens.pop(0)
        a, b = (values[t] if t.startswith(":") else item.get(t) for t in (token, right))
        return a is not None and b is not None and _COMPARE[op](a, b)

    result = disjunction()
    assert not tokens, f"unparsed {tokens}"
    return result


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
                assert action == "REMOVE"
                item.pop(part, None)


class UpdateOnlyTable:
    def __init__(self):
        self.rows = {}
        self.calls = 0

    def update_item(self, *, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeValues=None, ReturnValues="NONE"):
        self.calls += 1
        values = ExpressionAttributeValues or {}
        # DynamoDB rejects unused or undefined placeholders. Every write to a code is conditional.
        used = set(re.findall(r":\w+", f"{UpdateExpression} {ConditionExpression or ''}"))
        assert used == set(values), (used, set(values))
        assert ConditionExpression or not Key["grantId"].startswith("otpcode#")
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
    state = {"now": START, "sent": [], "table": UpdateOnlyTable()}
    monkeypatch.setattr(module.time, "time", lambda: state["now"])
    monkeypatch.setattr(module, "_probe_table", lambda: state["table"])
    # Distinct codes, so a test can tell an old code from the one that replaced it.
    codes = itertools.count(234_567, 7_919)
    monkeypatch.setattr(module.secrets, "randbelow", lambda bound: next(codes) % bound)

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


def _session(results):
    return [{"challengeName": "CUSTOM_CHALLENGE", "challengeResult": r} for r in results]


def create(otp, *results, **kwargs):
    """Create for a new sign-in, or for the next answer of a session with these results."""
    event = _event("CreateAuthChallenge_Authentication", session=_session(results), **kwargs)
    return otp.handler(event, None)["response"]


def verify(otp, answer):
    event = _event("VerifyAuthChallengeResponse_Authentication", challengeAnswer=answer)
    return otp.handler(event, None)["response"]["answerCorrect"]


def define(otp, *results, **kwargs):
    event = _event("DefineAuthChallenge_Authentication", session=_session(results), **kwargs)
    return otp.handler(event, None)["response"]


def code_row(otp):
    return otp.state["table"].rows.get("otpcode#" + DIGITS) or {}


def last_code(otp):
    return otp.state["sent"][-1]


def sends(otp):
    return otp.state["table"].rows["otpsend#" + DIGITS]["sends"]


def test_a_sent_code_is_stored_only_as_a_salted_hash(otp):
    response = create(otp)
    code, = otp.state["sent"]
    row = code_row(otp)
    assert set(row) == {"grantId", "codeSalt", "codeHash", "expiresAt", "attempts"}
    assert row["expiresAt"] == START + otp.OTP_TTL_SECONDS and row["attempts"] == 0
    assert code not in repr(row) and code not in repr(response)
    assert response["privateChallengeParameters"] == {"challenge": "WHATSAPP_OTP"}
    assert response["publicChallengeParameters"]["registered"] == "true"


def test_a_resend_sends_a_new_code_that_replaces_the_old_one(otp):
    first = create(otp)
    old_hash = code_row(otp)["codeHash"]
    otp.state["now"] += 30
    again = create(otp)  # a new sign-in: the first message did not arrive
    old, new = otp.state["sent"]
    assert old != new and code_row(otp)["codeHash"] != old_hash
    assert code_row(otp)["expiresAt"] == START + 30 + otp.OTP_TTL_SECONDS
    assert sends(otp) == 2
    assert again["publicChallengeParameters"] == first["publicChallengeParameters"]
    assert verify(otp, old) is False
    assert verify(otp, new) is True


def test_the_next_answer_in_a_session_keeps_its_code_without_a_send(otp):
    create(otp)
    code = last_code(otp)
    assert verify(otp, WRONG) is False
    assert define(otp, False) == CHALLENGE
    create(otp, False)  # Cognito asks for the session's second answer
    assert otp.state["sent"] == [code] and sends(otp) == 1
    assert verify(otp, code) is True


def test_wrong_answers_carry_across_codes_and_a_right_answer_is_not_counted(otp):
    create(otp)
    for _ in range(otp.MAX_ATTEMPTS):
        assert verify(otp, WRONG) is False
    assert define(otp, False, False, False) == FAILED  # the session's own limit
    row = code_row(otp)
    assert row["failedCount"] == 3 and row["windowStart"] == START
    otp.state["now"] += 60
    create(otp)  # the new code starts with no answers, the phone keeps its count
    row = code_row(otp)
    assert row["attempts"] == 0 and row["failedCount"] == 3 and row["windowStart"] == START
    assert verify(otp, WRONG) is False
    assert verify(otp, last_code(otp)) is True
    row = code_row(otp)
    assert row["failedCount"] == 4 and row["attempts"] == 2


def test_ten_wrong_answers_in_an_hour_lock_the_phone_until_the_window_passes(otp):
    for minute in range(4):  # four sign-ins, each sent a new code
        otp.state["now"] = START + 60 * minute
        create(otp)
        for _ in range(otp.MAX_ATTEMPTS if minute < 3 else 1):
            assert verify(otp, WRONG) is False
    assert len(otp.state["sent"]) == 4
    locked = code_row(otp)
    assert locked["failedCount"] == otp.FAIL_MAX_PER_WINDOW == 10
    assert locked["windowStart"] == START
    assert verify(otp, last_code(otp)) is False  # refused without being compared or counted
    assert code_row(otp) == locked
    assert define(otp, False) == FAILED  # ends the open session
    assert define(otp) == FAILED  # and fails each new sign-in before a code is sent
    create(otp)  # a Create that raced the lock stores and sends nothing
    assert len(otp.state["sent"]) == 4 and code_row(otp) == locked

    otp.state["now"] = START + otp.FAIL_WINDOW_SECONDS - 1
    assert define(otp) == FAILED
    otp.state["now"] = START + otp.FAIL_WINDOW_SECONDS  # the window has passed
    assert define(otp) == CHALLENGE
    create(otp)
    assert len(otp.state["sent"]) == 5
    assert verify(otp, WRONG) is False  # the first wrong answer opens a new window
    row = code_row(otp)
    assert row["failedCount"] == 1 and row["windowStart"] == otp.state["now"]
    assert verify(otp, last_code(otp)) is True


def test_an_answer_that_races_a_new_window_is_counted_in_it(otp):
    create(otp)
    table = otp.state["table"]
    real = table.update_item

    def racing(**kwargs):
        if kwargs["UpdateExpression"].startswith("SET windowStart"):
            # A concurrent wrong answer opens the window between this answer's two writes.
            table.update_item = real
            table.rows["otpcode#" + DIGITS].update(windowStart=otp.state["now"], failedCount=1)
        return real(**kwargs)

    table.update_item = racing
    assert verify(otp, last_code(otp)) is True
    row = code_row(otp)
    assert row["failedCount"] == 1 and row["attempts"] == 1


def test_over_budget_a_new_sign_in_keeps_the_active_code_and_sends_nothing(otp):
    first = create(otp)
    for _ in range(otp.SEND_MAX_PER_WINDOW - 1):
        create(otp)
    sent = list(otp.state["sent"])
    kept = code_row(otp)["codeHash"]
    response = create(otp)
    assert otp.state["sent"] == sent and code_row(otp)["codeHash"] == kept
    assert response["publicChallengeParameters"] == first["publicChallengeParameters"]
    assert verify(otp, sent[-2]) is False
    assert verify(otp, sent[-1]) is True


def test_over_budget_with_no_active_code_stores_nothing(otp):
    otp.state["table"].rows["otpsend#" + DIGITS] = {
        "grantId": "otpsend#" + DIGITS, "sends": otp.SEND_MAX_PER_WINDOW,
        "windowStartedAt": START, "expiresAt": START + 3600}
    response = create(otp)
    assert otp.state["sent"] == [] and code_row(otp) == {}
    assert response["publicChallengeParameters"]["registered"] == "true"
    assert verify(otp, "123456") is False


def test_a_correct_code_signs_in_once_and_keeps_the_wrong_answer_count(otp):
    create(otp)
    code = last_code(otp)
    assert verify(otp, WRONG) is False
    assert verify(otp, code) is True
    assert define(otp, False, True) == SIGNED_IN
    row = code_row(otp)
    assert "codeHash" not in row and "codeSalt" not in row  # consumed
    assert row["failedCount"] == 1 and row["windowStart"] == START
    assert define(otp, False, True) == FAILED  # already used
    assert verify(otp, code) is False


def test_the_fifth_answer_on_a_code_still_counts_and_a_sixth_is_not_compared(otp):
    create(otp)
    code = last_code(otp)
    for _ in range(otp.CODE_MAX_ATTEMPTS - 1):
        assert verify(otp, WRONG) is False
    assert verify(otp, code) is True
    assert code_row(otp)["attempts"] == otp.CODE_MAX_ATTEMPTS
    assert verify(otp, code) is False


def test_a_code_out_of_answers_ends_the_session_and_a_new_sign_in_replaces_it(otp):
    create(otp)
    for _ in range(otp.CODE_MAX_ATTEMPTS):  # answers from parallel sessions on one code
        assert verify(otp, WRONG) is False
    assert define(otp, False) == FAILED
    assert define(otp) == CHALLENGE  # 5 of the phone's 10
    create(otp)
    row = code_row(otp)
    assert len(otp.state["sent"]) == 2 and row["attempts"] == 0
    assert row["failedCount"] == otp.CODE_MAX_ATTEMPTS


def test_an_expired_code_is_refused_uncounted_and_the_session_gets_a_new_one(otp):
    create(otp)
    otp.state["now"] += otp.OTP_TTL_SECONDS  # checked in code: TTL is off on the table
    assert verify(otp, last_code(otp)) is False
    assert code_row(otp)["attempts"] == 0 and "failedCount" not in code_row(otp)
    assert define(otp, False) == CHALLENGE
    create(otp, False)  # the session's next answer has no active code to keep
    assert len(otp.state["sent"]) == 2
    assert verify(otp, last_code(otp)) is True


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
    assert define(otp) == FAILED
    assert define(otp, False) == FAILED
    assert define(otp, True) == FAILED


@pytest.mark.parametrize("answer", ["", "12345", "1234567", "12 456", "abcdef",
                                    "\u0661\u0662\u0663\u0664\u0665\u0666"])
def test_malformed_answers_never_reach_the_store(otp, answer):
    create(otp)
    calls = otp.state["table"].calls
    assert verify(otp, answer) is False
    assert otp.state["table"].calls == calls
    assert code_row(otp)["attempts"] == 0


def test_unknown_numbers_keep_the_existing_define_and_verify_behaviour(otp):
    assert define(otp, user_not_found=True) == CHALLENGE
    assert define(otp, False, user_not_found=True) == CHALLENGE
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


def test_handler_stays_standalone_and_uses_only_update_item():
    source = HANDLER.read_text()
    assert not re.search(r"^\s*(from|import)\s+lambda_utils", source, re.MULTILINE)
    assert not re.search(
        r"\.(get_item|put_item|delete_item|query|scan|batch_\w+|transact_\w+)\(", source)
