"""MSG-3: a failed inbound message is parked for replay, never acknowledged and lost.

Bad input (ValueError) is still acknowledged. Every other failure parks a copy of the
one failed message in the inbound DLQ with an `alert` log line; when the DLQ write
fails too, the invocation fails so the platform retries it. The shared Flow savers
keep a transient session-store error out of the ValueError path.
"""
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

HANDLER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py")
PHONE = "919999999999"


@pytest.fixture(scope="module")
def inbound():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    sys.path.insert(0, str(HANDLER.parent))
    spec = importlib.util.spec_from_file_location("inbound_parking_under_test", HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(HANDLER.parent))
        sys.modules.pop(spec.name, None)


def _context():
    ctx = mock.Mock()
    ctx.get_remaining_time_in_millis.return_value = 120000
    ctx.aws_request_id = "req-1"
    return ctx


def _message(mid):
    return {"id": mid, "from": PHONE, "timestamp": "1700000000", "type": "text",
            "text": {"body": "private-body-marker"}}


def _event(*mids):
    entry = {"id": "waba-1", "changes": [{"field": "messages", "value": {
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "111"},
        "contacts": [{"wa_id": PHONE, "profile": {"name": "Test"}}],
        "messages": [_message(m) for m in mids],
        "statuses": [{"id": "wamid.S", "status": "read"}],
    }}]}
    return {"source": "meta-direct", "version": 1, "entry": entry, "wabaId": "waba-1",
            "metaPhoneNumberIds": ["111"], "requestId": "req-1"}


def _run(inbound, failure, *, parked=True, mids=("wamid.A",)):
    def process(**kwargs):
        if kwargs["message"]["id"] == "wamid.A":
            raise failure

    with mock.patch.object(inbound, "_process_message", side_effect=process) as proc, \
            mock.patch.object(inbound, "_process_status"), \
            mock.patch.object(inbound, "_get_aws_phone_number_id", return_value="aws-1"), \
            mock.patch.object(inbound, "_send_to_dlq", return_value=parked) as dlq:
        try:
            result = inbound.handler(_event(*mids), _context())
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            result = exc
    return result, dlq, proc


def test_store_failure_parks_only_the_failed_message(inbound, caplog):
    result, dlq, proc = _run(inbound, RuntimeError("Submit Request completion could not be saved"),
                             mids=("wamid.A", "wamid.B"))
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"processed": 1, "errors": 1}
    assert proc.call_count == 2  # the next message still runs
    (record, reason, _request), = [c.args for c in dlq.call_args_list]
    value = record["entry"]["changes"][0]["value"]
    assert [m["id"] for m in value["messages"]] == ["wamid.A"]
    assert "statuses" not in value
    assert reason == "message_processing_error:RuntimeError"
    [parked] = [json.loads(r.message) for r in caplog.records
                if "inbound_message_parked" in r.message]
    assert parked["alert"] == "INBOUND_PARKED_IN_DLQ" and parked["messageId"] == "wamid.A"
    assert "private-body-marker" not in json.dumps(parked)


def test_bad_input_is_acknowledged_without_parking(inbound):
    result, dlq, _ = _run(inbound, ValueError("note is required"))
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"processed": 0, "errors": 1}
    dlq.assert_not_called()


def test_identity_conflict_keeps_its_reason(inbound):
    conflict = inbound.contact_store.IdentityConflict("phone", ())
    result, dlq, _ = _run(inbound, conflict)
    assert result["statusCode"] == 200
    assert dlq.call_args.args[1] == "customer_identity_conflict"


def test_unparkable_failure_fails_the_invocation(inbound):
    result, dlq, _ = _run(inbound, RuntimeError("store down"), parked=False)
    assert isinstance(result, RuntimeError)
    # Per-message park, then the record-level park of the whole work item.
    assert dlq.call_count == 2


class _Drafts:
    def __init__(self, error=None):
        self.error = error

    def get_item(self, **_):
        if self.error:
            raise self.error
        return {}


def _db(error=None):
    return SimpleNamespace(Table=lambda _name: _Drafts(error))


def _token(prefix):
    return f"{prefix}-{uuid.uuid4().hex}-waba-1-ph-{PHONE}"


def test_session_store_outage_is_not_bad_input():
    from lambda_utils import (flow_sessions, pickup_request_response, request_amendment_response,
                              submit_request_response, track_shipping_response)

    outage = RuntimeError("ProvisionedThroughputExceeded")
    pickup = {"flow_token": _token("request_pickup"), "reference_number": "order:WD-ORD-1"}
    track = {"flow_token": _token("shipments")}
    sr = {"flow_token": _token("srpaid"), "reference_number": "order:WD-ORD-1"}
    amend = {"flow_token": _token("amendpaid"), "reference_number": "order:WD-ORD-1",
             "request_number": "WD-SR-1", "amendment": "Please change the date."}

    def save_amend(db):
        return request_amendment_response.save_amendment(
            amend, contact_id="c", phone=PHONE, sender_name="", message_id="wamid.A",
            dynamodb=db)

    with pytest.raises(flow_sessions.FlowSessionUnavailable):
        pickup_request_response.save_pickup(pickup, contact_id="c", phone=PHONE, sender_name="",
                                            message_id="wamid.A", dynamodb=_db(outage))
    with pytest.raises(flow_sessions.FlowSessionUnavailable):
        track_shipping_response._session(_db(outage), track, phone=PHONE)
    with pytest.raises(flow_sessions.FlowSessionUnavailable):
        submit_request_response._paid_binding(_db(outage), sr, phone=PHONE)
    with pytest.raises(flow_sessions.FlowSessionUnavailable):
        request_amendment_response._paid_binding(_db(outage), amend, phone=PHONE)
    with pytest.raises(flow_sessions.FlowSessionUnavailable):
        save_amend(_db(outage))  # reaches the inbound worker, which parks it

    # A missing session is still bad input and is acknowledged.
    with pytest.raises(ValueError):
        pickup_request_response.save_pickup(pickup, contact_id="c", phone=PHONE, sender_name="",
                                            message_id="wamid.A", dynamodb=_db())
    with pytest.raises(ValueError):
        track_shipping_response._session(_db(), track, phone=PHONE)
    with pytest.raises(ValueError):
        submit_request_response._paid_binding(_db(), sr, phone=PHONE)
    with pytest.raises(ValueError):
        request_amendment_response._paid_binding(_db(), amend, phone=PHONE)
    with pytest.raises(ValueError):
        save_amend(_db())
