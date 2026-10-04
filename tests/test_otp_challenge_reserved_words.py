"""`consumed` is a DynamoDB reserved keyword, and only a CORRECT code hit the bug.

What happened, so the tests below read as defence rather than ceremony
---------------------------------------------------------------------
`otp_challenge.verify` consumed a code with

    UpdateExpression="SET consumed = :true, consumedAt = :now"
    ConditionExpression="consumed = :false"

and no `ExpressionAttributeNames`. DynamoDB refused the whole call with `ValidationException`,
the `except` arm recognised only `ConditionalCheckFailedException`, so every other failure became
`OtpStorageUnavailable` -> HTTP 503 -> the browser printing "That email code is invalid or
expired." Eight live confirms returned 503 in 15-53 ms with no log line, and the challenge row
sat at `attempts: 0`, `consumed: false` throughout.

The cruel part is the asymmetry: the WRONG-code branch writes `SET attempts = :next`, which
contains no reserved word, so it worked perfectly and returned a clean 400. The endpoint rejected
exactly the codes that were right.

Why `tests/test_otp_challenge.py` could not catch it, and why this file exists
-----------------------------------------------------------------------------
That suite drives `crm_fake_dynamo.FakeDynamo`, an in-memory fake. **A Python dict does not
implement DynamoDB's reserved-word list**, so the fake accepted the broken expression happily and
all 40-odd tests passed against code that could not work in production. A green unit suite was
not evidence, and it is still not evidence on its own - which is the whole reason the moto tests
below exist alongside the fake-based ones.

So there are two layers here, and they answer different questions:

1. `test_the_consume_step_aliases_the_reserved_word` and friends run against a RECORDING fake and
   answer "does the call carry the alias?" They are fast, they run everywhere, and they would
   catch a careless revert.
2. The `moto` tests answer "does a real DynamoDB engine accept it?" moto implements the reserved
   word list, which `test_moto_really_does_enforce_reserved_words` proves by feeding it the OLD
   expression and requiring a `ValidationException`. Without that calibration a green moto test
   would be worthless - it could be passing because moto does not check, which is precisely the
   failure mode of the dict fake.

moto is NOT in `requirements-dev.txt` (a full freeze, and this needs no production dependency),
so layer 2 skips when it is absent. Run it with an interpreter that has moto installed; the
recorded evidence for this fix was produced that way.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402
from lambda_utils import otp_challenge as otp  # noqa: E402

TABLE = 'stack-wecare-digital-DownloadGrantsTable'
PEPPER = 'test-pepper-not-a-real-secret'
SUBJECT = 'asha@example.com'
PURPOSE = 'email_verification'
NOW = 1_700_000_000

#: The exact expression pair that was live and broken. Kept verbatim so the moto calibration
#: test below is testing the real defect rather than a paraphrase of it.
BROKEN_UPDATE = "SET consumed = :true, consumedAt = :now"
BROKEN_CONDITION = "consumed = :false"


class RecordingTable:
    """A table that remembers every kwarg of every call and otherwise behaves like the fake.

    Needed because the assertion is about the SHAPE of the request - `ExpressionAttributeNames`
    being present and correct - and `FakeTable` deliberately exposes only `(table, operation)`
    pairs on `parent.calls`.
    """

    def __init__(self) -> None:
        self.inner = FakeDynamo(keys={TABLE: 'grantId'}).Table(TABLE)
        self.calls: list = []

    def get_item(self, **kwargs):
        self.calls.append(('get_item', kwargs))
        return self.inner.get_item(**kwargs)

    def put_item(self, **kwargs):
        self.calls.append(('put_item', kwargs))
        return self.inner.put_item(**kwargs)

    def update_item(self, **kwargs):
        self.calls.append(('update_item', kwargs))
        return self.inner.update_item(**kwargs)

    def last(self, operation: str) -> dict:
        for name, kwargs in reversed(self.calls):
            if name == operation:
                return kwargs
        raise AssertionError(f'no {operation} was issued')


def _issue(table, **kw):
    params = dict(purpose=PURPOSE, subject=SUBJECT, pepper=PEPPER, now=NOW)
    params.update(kw)
    return otp.issue(table, **params)


def _verify(table, code, **kw):
    params = dict(purpose=PURPOSE, subject=SUBJECT, pepper=PEPPER, code=code, now=NOW)
    params.update(kw)
    return otp.verify(table, **params)


# ── layer 1: the request shape ─────────────────────────────────────────────────

def test_the_consume_step_aliases_the_reserved_word():
    """Both expressions, not one. `UpdateExpression` is validated first, so aliasing only the
    condition still fails - which is why this asserts on the pair."""
    table = RecordingTable()
    issued = _issue(table)
    assert _verify(table, issued.code).ok

    call = table.last('update_item')
    names = call.get('ExpressionAttributeNames') or {}
    assert names.get('#consumed') == 'consumed', \
        'the consume step must alias `consumed`; it is a DynamoDB reserved keyword'
    assert '#consumed' in call['UpdateExpression']
    assert '#consumed' in call['ConditionExpression']


def test_no_expression_names_the_reserved_word_without_an_alias():
    """The regression this file is named after, stated as a property of the request rather than
    of one spelling: whatever the expression says, `consumed` must only appear via a `#` alias."""
    table = RecordingTable()
    issued = _issue(table)
    _verify(table, issued.code)

    call = table.last('update_item')
    for field in ('UpdateExpression', 'ConditionExpression'):
        expression = str(call.get(field) or '')
        for fragment in expression.replace(',', ' ').split():
            assert fragment != 'consumed', \
                f'{field} names the reserved word `consumed` unaliased: {expression!r}'


def test_the_issue_step_needs_no_alias_because_put_item_takes_a_plain_map():
    """The asymmetry that explains the live symptom: the row was WRITTEN but never UPDATED.

    Reserved words apply to expressions, not to `Item`, so `put_item` was always fine. Pinned so
    nobody "fixes" `issue` as well and concludes the defect was elsewhere.
    """
    table = RecordingTable()
    _issue(table)
    call = table.last('put_item')
    assert 'consumed' in call['Item']
    assert 'UpdateExpression' not in call


def test_the_failed_attempt_branch_is_left_alone():
    """`attempts` is not reserved - proved against live DynamoDB, and the reason a WRONG code
    always returned a correct 400 while a right one 503'd. Changing it was not part of the fix."""
    table = RecordingTable()
    issued = _issue(table)
    wrong = '111111' if issued.code != '111111' else '222222'
    assert _verify(table, wrong).outcome == otp.CODE_INCORRECT
    assert 'attempts' in table.last('update_item')['UpdateExpression']


# ── layer 1: a permanent error must stop masquerading as an outage ─────────────

def test_a_validation_exception_is_not_disguised_as_a_storage_outage():
    """The masking is what hid this for two days.

    A `ValidationException` is a malformed request: it will fail identically on every retry, and
    reporting it as `OtpStorageUnavailable` produced a 503 "temporarily unavailable" that logged
    nothing at all. It must escape, so the handler's own arm answers 500 and records the type.
    """
    table = FakeDynamo(keys={TABLE: 'grantId'}).Table(TABLE)
    issued = _issue(table)
    table.parent.arm_failure(TABLE, 'update_item', FakeClientError('ValidationException'))

    with pytest.raises(FakeClientError) as caught:
        _verify(table, issued.code)
    assert caught.value.response['Error']['Code'] == 'ValidationException'


def test_a_transient_failure_is_still_reported_as_a_storage_outage():
    """The other half of the narrowing. A throttle or an internal error must NOT surface as a
    wrong code, because that would burn the customer's attempt budget for our problem."""
    for code in ('ThrottlingException', 'InternalServerError',
                 'ProvisionedThroughputExceededException'):
        table = FakeDynamo(keys={TABLE: 'grantId'}).Table(TABLE)
        issued = _issue(table)
        table.parent.arm_failure(TABLE, 'update_item', FakeClientError(code))
        with pytest.raises(otp.OtpStorageUnavailable):
            _verify(table, issued.code)


def test_a_lost_conditional_race_is_still_already_used():
    """The narrowing must not swallow the legitimate case: exactly one verification per code."""
    table = FakeDynamo(keys={TABLE: 'grantId'}).Table(TABLE)
    issued = _issue(table)
    table.parent.arm_failure(
        TABLE, 'update_item', FakeClientError('ConditionalCheckFailedException'))
    assert _verify(table, issued.code).outcome == otp.ALREADY_USED


# ── layer 2: a real DynamoDB engine ────────────────────────────────────────────

@pytest.fixture
def moto_table(monkeypatch):
    """A real `boto3` Table backed by moto's DynamoDB implementation.

    Credentials are dummies set here rather than read from the environment: moto must never be
    able to reach a real account, and this suite must never depend on one being configured.
    """
    pytest.importorskip('moto', reason='moto is not in requirements-dev.txt; '
                                       'run with an interpreter that has it installed')
    import boto3
    from moto import mock_aws

    for name, value in (('AWS_ACCESS_KEY_ID', 'testing'),
                        ('AWS_SECRET_ACCESS_KEY', 'testing'),
                        ('AWS_SESSION_TOKEN', 'testing'),
                        ('AWS_DEFAULT_REGION', 'us-east-1')):
        monkeypatch.setenv(name, value)

    with mock_aws():
        resource = boto3.resource('dynamodb', region_name='us-east-1')
        resource.create_table(
            TableName=TABLE,
            KeySchema=[{'AttributeName': 'grantId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'grantId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        yield resource.Table(TABLE)


def test_moto_really_does_enforce_reserved_words(moto_table):
    """CALIBRATION, and the most important test in this file.

    Everything else here is only meaningful if the engine under it actually implements the
    reserved-word rule. So feed it the exact expression that was live and broken and require it
    to be refused. If this test ever starts passing for the wrong reason - moto dropping the
    check - the ones below it become as blind as the dict fake, and this is what says so.
    """
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as caught:
        moto_table.update_item(
            Key={'grantId': 'otp#calibration'},
            UpdateExpression=BROKEN_UPDATE,
            ConditionExpression=BROKEN_CONDITION,
            ExpressionAttributeValues={':true': True, ':false': False, ':now': NOW},
        )
    assert caught.value.response['Error']['Code'] == 'ValidationException'
    assert 'reserved keyword' in str(caught.value).lower()


def test_a_correct_code_verifies_against_a_real_dynamodb_engine(moto_table):
    """The end-to-end proof of the fix. This is the call that returned 503 in production."""
    issued = _issue(moto_table)
    result = _verify(moto_table, issued.code)
    assert result.ok and result.outcome == otp.VERIFIED

    stored = moto_table.get_item(
        Key={'grantId': otp.challenge_key(PEPPER, PURPOSE, SUBJECT)}).get('Item') or {}
    assert stored.get('consumed') is True, 'the row must actually record the consumption'
    assert stored.get('consumedAt') == NOW


def test_single_use_still_holds_against_a_real_engine(moto_table):
    """The `ConditionExpression` is the single-use guarantee, and it is on the same call as the
    alias - so a fix that dropped the condition to dodge the reserved word would pass the test
    above and silently allow two verifications. This is the test that would catch that."""
    issued = _issue(moto_table)
    assert _verify(moto_table, issued.code).ok
    assert _verify(moto_table, issued.code).outcome == otp.ALREADY_USED


def test_a_wrong_code_counts_an_attempt_against_a_real_engine(moto_table):
    """`attempts` stuck at 0 across eight submissions was the fingerprint of the live defect.
    This asserts the counter moves on the real engine, in both branches' presence."""
    issued = _issue(moto_table)
    wrong = '111111' if issued.code != '111111' else '222222'
    assert _verify(moto_table, wrong).outcome == otp.CODE_INCORRECT

    stored = moto_table.get_item(
        Key={'grantId': otp.challenge_key(PEPPER, PURPOSE, SUBJECT)}).get('Item') or {}
    assert int(stored.get('attempts') or 0) == 1
