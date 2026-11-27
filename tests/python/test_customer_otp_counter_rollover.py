"""Regression coverage for the standalone Cognito send-budget counter."""
import importlib.util
from pathlib import Path

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def auth(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "amplify/functions/auth/customer-whatsapp-auth/handler.py"
    spec = importlib.util.spec_from_file_location("otp_counter_rollover_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SEND_WINDOW_SECONDS", 3600)
    monkeypatch.setattr(module, "SEND_MAX_PER_WINDOW", 5)
    monkeypatch.setattr(module.time, "time", lambda: 10000)
    return module


def conditional_failure():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")


class UpdateOnlyTable:
    """Simulates the role's UpdateItem-only access and DynamoDB conditions."""

    def __init__(self, row=None, competing_reset=False):
        self.row = dict(row or {})
        self.competing_reset = competing_reset
        self.calls = 0

    def update_item(self, **kwargs):
        self.calls += 1
        values = kwargs["ExpressionAttributeValues"]
        start = self.row.get("windowStartedAt")
        cutoff = values[":cutoff"]
        if kwargs["UpdateExpression"] == "ADD sends :one":
            assert kwargs["ConditionExpression"] == "windowStartedAt > :cutoff"
            if start is None or start <= cutoff:
                raise conditional_failure()
            self.row["sends"] = self.row.get("sends", 0) + values[":one"]
            return {"Attributes": dict(self.row)}
        assert kwargs["ConditionExpression"] == (
            "attribute_not_exists(windowStartedAt) OR windowStartedAt <= :cutoff"
        )
        if self.competing_reset:
            self.competing_reset = False
            self.row.update(sends=1, windowStartedAt=values[":now"], expiresAt=values[":exp"])
            raise conditional_failure()
        if start is not None and start > cutoff:
            raise conditional_failure()
        self.row.update(sends=values[":one"], windowStartedAt=values[":now"], expiresAt=values[":exp"])
        return {}


@pytest.mark.parametrize("row", [{}, {"sends": 99, "windowStartedAt": 6400, "expiresAt": 10000}])
def test_fresh_or_expired_budget_resets_with_update_permission(auth, monkeypatch, row):
    table = UpdateOnlyTable(row)
    monkeypatch.setattr(auth, "_probe_table", lambda: table)
    auth._consume_send_budget("synthetic")
    assert table.row == {"sends": 1, "windowStartedAt": 10000, "expiresAt": 13600}
    assert table.calls == 2


def test_active_window_still_limits_sends(auth, monkeypatch):
    table = UpdateOnlyTable({"sends": 4, "windowStartedAt": 9000, "expiresAt": 12600})
    monkeypatch.setattr(auth, "_probe_table", lambda: table)
    auth._consume_send_budget("synthetic")
    with pytest.raises(auth.OtpSendThrottled):
        auth._consume_send_budget("synthetic")
    assert table.row["sends"] == 6
    assert table.row["windowStartedAt"] == 9000


def test_concurrent_reset_counts_both_requests(auth, monkeypatch):
    table = UpdateOnlyTable({"sends": 99, "windowStartedAt": 6400}, competing_reset=True)
    monkeypatch.setattr(auth, "_probe_table", lambda: table)
    auth._consume_send_budget("synthetic")
    assert table.row["sends"] == 2
    assert table.row["windowStartedAt"] == 10000


def test_storage_errors_still_fail_closed(auth, monkeypatch):
    class Unavailable:
        def update_item(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "UpdateItem")
    monkeypatch.setattr(auth, "_probe_table", lambda: Unavailable())
    with pytest.raises(auth.OtpSendThrottled):
        auth._consume_send_budget("synthetic")
