"""CA-6: otp_challenge issues with one conditional write and counts attempts atomically.

`FakeTable` evaluates the condition and update expressions otp_challenge sends, and can serve
a stale read to simulate a concurrent request landing between the read and the write.
"""
import re

import pytest
from botocore.exceptions import ClientError

from lambda_utils import otp_challenge as oc

KW = {"purpose": "email_verification", "subject": "a@example.com", "pepper": "pepper"}
KEY = oc.challenge_key("pepper", "email_verification", "a@example.com")


def _failed():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "Write")


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.stale = None
        self.reads = []

    def get_item(self, *, Key, ConsistentRead=False):
        self.reads.append(ConsistentRead)
        if self.stale is not None:
            item, self.stale = self.stale, None
            return {"Item": dict(item)}
        row = self.rows.get(Key["grantId"])
        return {"Item": dict(row)} if row else {}

    def _check(self, expression, item, names, values):
        if not expression:
            return
        for term in expression.split(" AND "):
            term = term.strip()
            for alias, name in (names or {}).items():
                term = term.replace(alias, name)
            match = re.fullmatch(r"attribute_not_exists\((\w+)\)", term)
            if match:
                ok = match.group(1) not in item
            else:
                left, op, right = re.fullmatch(r"(\w+) (=|<) (:\w+)", term).groups()
                have, want = item.get(left), values[right]
                ok = have is not None and (have == want if op == "=" else have < want)
            if not ok:
                raise _failed()

    def put_item(self, *, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        current = self.rows.get(Item["grantId"]) or {}
        self._check(ConditionExpression, current, None, ExpressionAttributeValues)
        self.rows[Item["grantId"]] = dict(Item)

    def update_item(self, *, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeNames=None, ExpressionAttributeValues=None,
                    ReturnValues="NONE"):
        item = self.rows[Key["grantId"]]
        values = ExpressionAttributeValues or {}
        self._check(ConditionExpression, item, ExpressionAttributeNames, values)
        changed = {}
        tokens = re.split(r"\b(SET|ADD)\b", UpdateExpression)
        for action, body in zip(tokens[1::2], tokens[2::2]):
            for part in body.split(","):
                part = part.strip()
                for alias, name in (ExpressionAttributeNames or {}).items():
                    part = part.replace(alias, name)
                if action == "SET":
                    name, value = [p.strip() for p in part.split("=")]
                    changed[name] = values[value]
                else:
                    name, value = part.split()
                    changed[name] = item.get(name, 0) + values[value]
        item.update(changed)
        return {"Attributes": dict(changed)} if ReturnValues == "UPDATED_NEW" else {}


@pytest.fixture
def table():
    return FakeTable()


def test_issue_reads_consistently_and_writes_once_conditionally(table):
    first = oc.issue(table, now=1000, **KW)
    assert table.reads == [True]
    assert table.rows[KEY]["sendCount"] == 1 and table.rows[KEY]["lastSentAt"] == 1000
    second = oc.issue(table, now=1100, **KW)
    assert table.rows[KEY]["sendCount"] == 2 and second.code and first.code


def test_a_concurrent_issue_cannot_overwrite_or_lose_a_send(table):
    oc.issue(table, now=1000, **KW)
    stale = dict(table.rows[KEY])
    oc.issue(table, now=1100, **KW)  # another request issued after our read
    table.stale = stale
    with pytest.raises(oc.ResendTooSoon) as refused:
        oc.issue(table, now=1101, **KW)
    assert refused.value.retry_after_seconds >= 1
    assert table.rows[KEY]["sendCount"] == 2 and table.rows[KEY]["lastSentAt"] == 1100


def test_a_racing_first_issue_is_refused(table):
    oc.issue(table, now=1000, **KW)
    table.stale = {}
    with pytest.raises(oc.ResendTooSoon):
        oc.issue(table, now=1001, **KW)
    assert table.rows[KEY]["sendCount"] == 1


def test_wrong_answers_are_counted_atomically_from_the_stored_value(table):
    code = oc.issue(table, now=1000, **KW).code
    wrong = "000000" if code != "000000" else "111111"
    table.rows[KEY]["attempts"] = 3  # two answers landed after our read
    table.stale = {**table.rows[KEY], "attempts": 1}
    result = oc.verify(table, code=wrong, now=1001, **KW)
    assert result.outcome == oc.CODE_INCORRECT
    assert table.rows[KEY]["attempts"] == 4 and result.attempts_remaining == 1
    assert table.reads[-1] is True


def test_attempt_cap_holds_against_a_stale_read(table):
    code = oc.issue(table, now=1000, **KW).code
    wrong = "000000" if code != "000000" else "111111"
    table.rows[KEY]["attempts"] = oc.DEFAULT_MAX_ATTEMPTS
    table.stale = {**table.rows[KEY], "attempts": 0}
    assert oc.verify(table, code=wrong, now=1001, **KW).outcome == oc.ATTEMPTS_EXHAUSTED
    assert table.rows[KEY]["attempts"] == oc.DEFAULT_MAX_ATTEMPTS
    table.stale = {**table.rows[KEY], "attempts": 0}
    refused = oc.verify(table, code=code, now=1001, **KW)
    assert not refused.ok and table.rows[KEY]["consumed"] is False


def test_correct_code_verifies_once(table):
    code = oc.issue(table, now=1000, **KW).code
    assert oc.verify(table, code=code, now=1001, **KW).ok
    assert oc.verify(table, code=code, now=1002, **KW).outcome == oc.ALREADY_USED
    assert table.reads == [True, True, True]


def test_five_wrong_answers_exhaust_the_code(table):
    code = oc.issue(table, now=1000, **KW).code
    wrong = "000000" if code != "000000" else "111111"
    outcomes = [oc.verify(table, code=wrong, now=1001, **KW).outcome for _ in range(6)]
    assert outcomes == [oc.CODE_INCORRECT] * 5 + [oc.ATTEMPTS_EXHAUSTED]
    assert oc.verify(table, code=code, now=1002, **KW).outcome == oc.ATTEMPTS_EXHAUSTED
