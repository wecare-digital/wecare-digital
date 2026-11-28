"""PAY-1: lease states that tell a finished event from one an unfinished attempt still holds."""
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from lambda_utils import webhook_dedup


def _conditional():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


class LeaseTable:
    """Just the conditional operations webhook_dedup issues."""

    def __init__(self):
        self.rows = {}
        self.put_error = None
        self.get_error = None

    def put_item(self, *, Item, ConditionExpression, ExpressionAttributeValues=None):
        if self.put_error:
            raise self.put_error
        row = self.rows.get(Item["eventId"])
        if ConditionExpression == "attribute_not_exists(eventId)":
            if row is not None:
                raise _conditional()
        else:
            assert ConditionExpression == "leaseExpiresAt = :seen"
            if row is None or row.get("leaseExpiresAt") != ExpressionAttributeValues[":seen"]:
                raise _conditional()
        self.rows[Item["eventId"]] = dict(Item)

    def get_item(self, *, Key):
        if self.get_error:
            raise self.get_error
        row = self.rows.get(Key["eventId"])
        return {"Item": dict(row)} if row is not None else {}

    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeValues,
                    ConditionExpression=None):
        row = self.rows.get(Key["eventId"])
        if UpdateExpression == "SET completedAt = :now":
            row["completedAt"] = ExpressionAttributeValues[":now"]
            return
        assert ConditionExpression == "leaseExpiresAt = :mine AND attribute_not_exists(completedAt)"
        if (row is None or row.get("leaseExpiresAt") != ExpressionAttributeValues[":mine"]
                or "completedAt" in row):
            raise _conditional()
        row["leaseExpiresAt"] = ExpressionAttributeValues[":released"]
        row["leaseReleasedAt"] = ExpressionAttributeValues[":released"]


@pytest.fixture
def leases(monkeypatch):
    table = LeaseTable()
    clock = SimpleNamespace(now=1000)
    monkeypatch.setattr(webhook_dedup, "_table", lambda: table)
    monkeypatch.setattr(webhook_dedup, "time", SimpleNamespace(time=lambda: clock.now))
    return table, clock


def test_states_for_fresh_held_completed_and_permanent(leases):
    table, clock = leases
    first = webhook_dedup.claim_event_lease("evt", lease_seconds=900)
    assert first.state == webhook_dedup.LEASE_CLAIMED and first.lease_expires_at == 1900
    assert webhook_dedup.claim_event_lease("evt").state == webhook_dedup.LEASE_IN_PROGRESS
    webhook_dedup.complete_event("evt")
    assert webhook_dedup.claim_event_lease("evt").state == webhook_dedup.LEASE_COMPLETED
    table.rows["legacy"] = {"eventId": "legacy", "processedAt": 1}
    assert webhook_dedup.claim_event_lease("legacy").state == webhook_dedup.LEASE_PERMANENT
    clock.now = 5000
    assert webhook_dedup.claim_event_lease("evt").state == webhook_dedup.LEASE_COMPLETED


def test_bool_form_answers_exactly_as_before(leases):
    table, clock = leases
    assert webhook_dedup.claim_event_with_lease("a") is True           # fresh
    assert webhook_dedup.claim_event_with_lease("a") is False          # lease held
    clock.now += webhook_dedup.DEFAULT_LEASE_SECONDS + 1
    assert webhook_dedup.claim_event_with_lease("a") is True           # salvaged
    webhook_dedup.complete_event("a")
    assert webhook_dedup.claim_event_with_lease("a") is False          # completed
    table.rows["b"] = {"eventId": "b"}
    assert webhook_dedup.claim_event_with_lease("b") is False          # no lease
    assert webhook_dedup.claim_event_with_lease("") is True            # unkeyable
    table.put_error = ClientError({"Error": {"Code": "ThrottlingException"}}, "PutItem")
    assert webhook_dedup.claim_event_with_lease("c") is True           # fails open
    table.put_error = None
    table.rows["d"] = {"eventId": "d", "leaseExpiresAt": 1}
    table.get_error = RuntimeError("read failed")
    assert webhook_dedup.claim_event_with_lease("d") is True           # fails open


def test_lost_salvage_race_is_in_progress(leases, monkeypatch):
    table, clock = leases
    table.rows["e"] = {"eventId": "e", "leaseExpiresAt": 10}
    real_put = table.put_item

    def racing_put(**kwargs):
        if kwargs.get("ConditionExpression") == "leaseExpiresAt = :seen":
            table.rows["e"]["leaseExpiresAt"] = 99999   # another worker won first
        return real_put(**kwargs)

    monkeypatch.setattr(table, "put_item", racing_put)
    assert webhook_dedup.claim_event_lease("e").state == webhook_dedup.LEASE_IN_PROGRESS


def test_released_lease_is_claimable_immediately(leases):
    table, clock = leases
    claim = webhook_dedup.claim_event_lease("evt")
    assert webhook_dedup.release_event_lease("evt", claim.lease_expires_at) is True
    retry = webhook_dedup.claim_event_lease("evt")      # same second, no clock change
    assert retry.state == webhook_dedup.LEASE_CLAIMED


def test_release_never_reopens_a_completed_event_or_takes_another_lease(leases):
    table, clock = leases
    mine = webhook_dedup.claim_event_lease("done")
    webhook_dedup.complete_event("done")
    assert webhook_dedup.release_event_lease("done", mine.lease_expires_at) is False
    assert webhook_dedup.claim_event_lease("done").state == webhook_dedup.LEASE_COMPLETED

    webhook_dedup.claim_event_lease("other")
    assert webhook_dedup.release_event_lease("other", 1) is False
    assert webhook_dedup.claim_event_lease("other").state == webhook_dedup.LEASE_IN_PROGRESS
    assert webhook_dedup.release_event_lease("other", None) is False
