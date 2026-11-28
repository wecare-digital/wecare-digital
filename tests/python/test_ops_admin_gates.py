"""OPS-5: POST /dlq/replay, POST /media/cleanup and GET /billing are Admin-only, scheduled
runs still pass, and a replay logs who ran it."""
import importlib.util
import itertools
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2] / "amplify/functions"
DLQ = ROOT / "operations/dlq-replay/handler.py"
MEDIA = ROOT / "messaging/media-cleanup/handler.py"
BILLING = ROOT / "operations/billing/handler.py"
_names = itertools.count()


def _load(path, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location(f"ops_gate_{next(_names)}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def staff_event(monkeypatch, groups, method, body=None):
    """An API Gateway event that drives the real require_auth with a fake Cognito."""
    from lambda_utils import middleware

    class FakeCognito:
        class exceptions:
            class NotAuthorizedException(Exception):
                pass

        def get_user(self, AccessToken):
            return {"Username": "staff-1", "UserAttributes": [{"Name": "sub", "Value": "sub-1"}]}

        def admin_list_groups_for_user(self, **kwargs):
            return {"Groups": [{"GroupName": g} for g in groups]}

        def admin_get_user(self, **kwargs):
            return {"UserMFASettingList": ["SMS_MFA"]}

    monkeypatch.setattr(middleware, "cognito", FakeCognito())
    monkeypatch.setattr(middleware, "_unverified_issuer", lambda t: middleware.staff_pool_issuer())
    monkeypatch.setattr(middleware, "_unverified_clients", lambda t: {middleware.STAFF_APP_CLIENT_ID})
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    return {
        "headers": {"authorization": "Bearer t"},
        "requestContext": {"apiId": "api", "http": {"method": method, "sourceIp": "1.2.3.4"}},
        "body": json.dumps(body or {}),
    }


@pytest.fixture
def dlq(monkeypatch):
    module = _load(DLQ, monkeypatch)
    module.sqs = Mock()
    module.sqs.receive_message.return_value = {"Messages": []}
    table = Mock()
    table.scan.return_value = {"Items": []}
    module.dynamodb = Mock(Table=Mock(return_value=table))
    module.lambda_client = Mock()
    return module


@pytest.mark.parametrize("groups", [["Operator"], ["Viewer"]])
def test_dlq_replay_refuses_non_admin(dlq, monkeypatch, groups):
    response = dlq.handler(staff_event(monkeypatch, groups, "POST", {"queueName": "inbound-dlq"}), None)
    assert response["statusCode"] == 403
    dlq.sqs.receive_message.assert_not_called()


def test_dlq_replay_admin_runs_and_logs_the_actor(dlq, monkeypatch, caplog):
    caplog.set_level("INFO")
    response = dlq.handler(staff_event(monkeypatch, ["Admin"], "POST", {"queueName": "inbound-dlq"}), None)
    assert response["statusCode"] == 200
    dlq.sqs.receive_message.assert_called_once()
    starts = [json.loads(r.getMessage()) for r in caplog.records
              if "dlq_replay_start" in r.getMessage()]
    assert starts and starts[0]["actor"] == "staff-1"


def test_dlq_list_stays_open_to_viewers(dlq, monkeypatch):
    response = dlq.handler(staff_event(monkeypatch, ["Viewer"], "GET"), None)
    assert response["statusCode"] == 200
    dlq.sqs.receive_message.assert_not_called()


def test_dlq_replay_actor_without_token_is_internal(dlq, caplog):
    caplog.set_level("INFO")
    dlq._replay_dlq_messages({"body": json.dumps({"queueName": "inbound-dlq"})}, "local")
    assert '"actor": "internal"' in caplog.text


@pytest.fixture
def media(monkeypatch):
    module = _load(MEDIA, monkeypatch)
    table = Mock()
    table.scan.return_value = {"Items": []}
    module.dynamodb = Mock(Table=Mock(return_value=table))
    module.table = table
    return module


@pytest.mark.parametrize("groups", [["Operator"], ["Viewer"]])
def test_media_cleanup_refuses_non_admin(media, monkeypatch, groups):
    response = media.handler(staff_event(monkeypatch, groups, "POST"), None)
    assert response["statusCode"] == 403
    media.table.scan.assert_not_called()


def test_media_cleanup_admin_and_schedule_run(media, monkeypatch):
    assert media.handler(staff_event(monkeypatch, ["Admin"], "POST"), None)["statusCode"] == 200
    assert media.handler({}, None)["statusCode"] == 200  # EventBridge: no API Gateway context
    assert media.table.scan.call_count == 2


@pytest.fixture
def billing(monkeypatch):
    module = _load(BILLING, monkeypatch)
    denied = ClientError({"Error": {"Code": "SubscriptionRequiredException", "Message": "x"}}, "op")
    module.health_client = Mock(describe_events=Mock(side_effect=denied))
    module.support_client = Mock(describe_trusted_advisor_checks=Mock(side_effect=denied))
    return module


@pytest.mark.parametrize("groups", [["Operator"], ["Viewer"]])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_billing_refuses_non_admin(billing, monkeypatch, groups, method):
    assert billing.handler(staff_event(monkeypatch, groups, method), None)["statusCode"] == 403
    billing.health_client.describe_events.assert_not_called()


def test_billing_admin_reads(billing, monkeypatch):
    response = billing.handler(staff_event(monkeypatch, ["Admin"], "GET"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["costReportingEnabled"] is False
