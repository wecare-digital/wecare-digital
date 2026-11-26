"""The inbound DLQ must retain unproven or failed replays."""
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

PATH = Path(__file__).resolve().parents[2] / "amplify/functions/operations/dlq-replay/handler.py"
SPEC = importlib.util.spec_from_file_location("dlq_replay", PATH)
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)


def work(*ids):
    return {"source": "meta-direct", "entry": {"changes": [
        {"field": "messages", "value": {"messages": [{"id": mid} for mid in ids]}}
    ]}}


def worker_response(body, **response_fields):
    return {"Payload": io.BytesIO(json.dumps({
        "statusCode": 200, "body": json.dumps(body),
    }).encode()), **response_fields}


def canonical_row(mid):
    return {"whatsappMessageId": mid, "channel": "whatsapp", "direction": "inbound"}


@pytest.fixture
def aws(monkeypatch):
    table, sqs, worker = Mock(), Mock(), Mock()
    table.query.return_value = {"Items": []}
    table.get_item.return_value = {}
    monkeypatch.setattr(HANDLER, "dynamodb", Mock(Table=Mock(return_value=table)))
    monkeypatch.setattr(HANDLER, "sqs", sqs)
    monkeypatch.setattr(HANDLER, "lambda_client", worker)
    return table, sqs, worker


@pytest.fixture
def replay(monkeypatch, aws):
    table, sqs, worker = aws
    table.get_item.return_value = {"Item": {"retryCount": 0}}

    def run(*events, retries=0):
        table.get_item.return_value = {"Item": {"retryCount": retries}}
        receipts = [{"ReceiptHandle": str(i), "MessageId": str(i), "Body": json.dumps({
            "originalMessageId": "tracking-A", "originalRecord": event,
        })} for i, event in enumerate(events)]
        sqs.receive_message.return_value = {"Messages": receipts}
        response = HANDLER._replay_dlq_messages(
            {"body": json.dumps({"queueName": "inbound-dlq"})}, "local")
        assert response["statusCode"] == 200
        return json.loads(response["body"])

    return run


@pytest.mark.parametrize("body", [
    {"processed": 0, "errors": 1},
    {"processed": 1, "errors": 1},
    {"processed": 0, "errors": 0},
    {"processed": 1},
    {"processed": 1, "errors": False},
    {"processed": 1, "errors": 0},  # Lease/no-op: no durable canonical row.
])
def test_http_200_does_not_ack_an_unproved_replay(aws, replay, body):
    table, sqs, worker = aws
    worker.invoke.return_value = worker_response(body)
    stats = replay(work("a"), work("b"))
    assert stats["failed"] == 1 and stats["skipped"] == 1 and stats["succeeded"] == 0
    sqs.delete_message.assert_not_called()
    table.delete_item.assert_not_called()
    table.update_item.assert_called_once()


def test_expended_retry_budget_preserves_inbound_receipt(aws, replay):
    table, sqs, worker = aws
    assert replay(work("a"), retries=HANDLER.MAX_RETRIES)["skipped"] == 1
    sqs.delete_message.assert_not_called()
    table.delete_item.assert_not_called()
    worker.invoke.assert_not_called()


@pytest.mark.parametrize("row", [None, canonical_row("another"), {
    **canonical_row("a"), "direction": "outbound",
}])
def test_index_match_alone_is_not_durable_proof(aws, row):
    table, _, worker = aws
    table.query.return_value = {"Items": [{"id": "candidate"}]}
    table.get_item.return_value = {"Item": row}
    worker.invoke.return_value = worker_response({"processed": 1, "errors": 0})
    assert HANDLER._replay_message("inbound-dlq", work("a"), "local") is False
    assert all(call.kwargs["ConsistentRead"] for call in table.get_item.call_args_list)


def test_clean_worker_response_after_both_rows_are_durably_written(aws, replay):
    table, sqs, worker = aws
    table.query.side_effect = [
        {"Items": []}, {"Items": [{"id": "uuid-a"}]}, {"Items": [{"id": "uuid-b"}]},
    ]
    table.get_item.side_effect = [
        {"Item": {"retryCount": 0}},
        {"Item": canonical_row("a")},
        {"Item": canonical_row("b")},
    ]
    worker.invoke.return_value = worker_response({"processed": 2, "errors": 0})
    assert replay(work("a", "b"))["succeeded"] == 1
    sqs.delete_message.assert_called_once()
    table.delete_item.assert_called_once_with(Key={"id": "tracking-A"})


def test_partial_batch_does_not_ack(aws, replay):
    table, sqs, worker = aws
    table.query.side_effect = [
        {"Items": []}, {"Items": [{"id": "uuid-a"}]}, {"Items": []},
    ]
    table.get_item.side_effect = [{"Item": {"retryCount": 0}}, {"Item": canonical_row("a")}]
    worker.invoke.return_value = worker_response({"processed": 2, "errors": 0})
    assert replay(work("a", "b"))["failed"] == 1
    sqs.delete_message.assert_not_called()
    table.delete_item.assert_not_called()


def test_durable_duplicate_is_acked_without_reinvoking_worker(aws):
    table, _, worker = aws
    table.query.return_value = {"Items": [{"id": "uuid-a"}]}
    table.get_item.return_value = {"Item": canonical_row("a")}
    assert HANDLER._replay_message("inbound-dlq", work("a"), "local") is True
    worker.invoke.assert_not_called()


def test_sqs_delete_failure_retains_tracking_record(aws, replay):
    table, sqs, worker = aws
    table.query.return_value = {"Items": [{"id": "uuid-a"}]}
    table.get_item.side_effect = [{"Item": {"retryCount": 0}}, {"Item": canonical_row("a")}]
    sqs.delete_message.side_effect = RuntimeError
    assert replay(work("a"))["failed"] == 1
    table.delete_item.assert_not_called()
    worker.invoke.assert_not_called()


def test_mixed_or_unrecognized_shapes_are_not_acknowledged(aws):
    _, _, worker = aws
    mixed = work("a")
    mixed["entry"]["changes"][0]["value"]["statuses"] = [{"id": "status"}]
    for event in (mixed, work(""), {}, {"messages": [{"id": "a"}]}):
        assert HANDLER._replay_message("inbound-dlq", event, "local") is False
    worker.invoke.assert_not_called()


def test_legacy_sns_same_acknowledgment_contract(aws):
    table, _, worker = aws
    legacy = {"Records": [{"Sns": {"Message": json.dumps({
        "whatsAppWebhookEntry": json.dumps(work("a")["entry"]),
    })}}]}
    table.query.return_value = {"Items": [{"id": "uuid-a"}]}
    table.get_item.return_value = {"Item": canonical_row("a")}
    assert HANDLER._replay_message("inbound-dlq", legacy, "local") is True
    worker.invoke.assert_not_called()


def test_bulk_worker_response_contract_unchanged(aws):
    _, _, worker = aws
    worker.invoke.return_value = {"Payload": io.BytesIO(b'{"jobId":"demo","status":"completed"}')}
    assert HANDLER._replay_message("bulk-dlq", {"jobId": "demo"}, "local") is True
