"""SQS fan-out: per-message retry, a dead-letter queue, and a cap that protects the API.

THE THREE TESTS THAT CARRY THIS FILE.

`test_only_a_raised_message_is_retried`. With ReportBatchItemFailures the consumer returns just
the messages that need another attempt. Report too many and a bad document redelivers the whole
batch, so already-extracted sources are re-read, lose the claim, and the batch makes no progress
while looking busy. Report too few and a transient S3 failure silently drops a document.

`test_a_duplicate_delivery_does_not_extract_twice`. A standard queue is at-least-once. The
conditional claim on `status = UPLOADED` is the only thing making that safe, and with the Bedrock
step attached a duplicate extraction is a duplicate model call.

`test_an_api_gateway_event_is_never_mistaken_for_a_queue_batch`. The consumer runs without
`require_auth`, and what makes that safe is that no HTTP request can produce its trigger shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blog_quality_v2 as q  # noqa: E402
from blog_pdf_fixture import make_pdf, wrap  # noqa: E402
from test_blog_sources import FakeLambda, FakeS3, FakeTable, _pdf_entry  # noqa: E402
from test_blog_qa import PROSE  # noqa: E402


class FakeSQS:
    """Enough of SQS to express a partial batch failure and a dead-letter queue."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.dlq: List[Dict[str, Any]] = []
        #: Indices within a SendMessageBatch call to reject. A partial failure returns HTTP 200
        #: with a `Failed` list, which is the case a caller checking only for an exception
        #: silently miscounts.
        self.reject_indices: set = set()
        self.raise_on_send = False
        self.queues = {"wecare-blog-ingest-dlq": "https://sqs.test/dlq"}

    def send_message_batch(self, QueueUrl, Entries):  # noqa: N803
        if self.raise_on_send:
            raise RuntimeError("throttled")
        successful, failed = [], []
        for index, entry in enumerate(Entries):
            if index in self.reject_indices:
                failed.append({"Id": entry["Id"], "Code": "InternalError",
                               "SenderFault": False})
                continue
            self.sent.append({"url": QueueUrl, "body": entry["MessageBody"]})
            successful.append({"Id": entry["Id"], "MessageId": f"m{len(self.sent)}"})
        return {"Successful": successful, "Failed": failed}

    def send_message(self, QueueUrl, MessageBody):  # noqa: N803
        self.sent.append({"url": QueueUrl, "body": MessageBody})
        return {"MessageId": f"m{len(self.sent)}"}

    def get_queue_url(self, QueueName):  # noqa: N803
        if QueueName not in self.queues:
            raise RuntimeError("NonExistentQueue")
        return {"QueueUrl": self.queues[QueueName]}

    def get_queue_attributes(self, QueueUrl, AttributeNames):  # noqa: N803
        if QueueUrl == "https://sqs.test/dlq":
            return {"Attributes": {"ApproximateNumberOfMessages": str(len(self.dlq))}}
        return {"Attributes": {"ApproximateNumberOfMessages": str(len(self.sent)),
                               "ApproximateNumberOfMessagesNotVisible": "0"}}

    def receive_message(self, QueueUrl, MaxNumberOfMessages, WaitTimeSeconds):  # noqa: N803
        taken, self.dlq = self.dlq[:MaxNumberOfMessages], self.dlq[MaxNumberOfMessages:]
        return {"Messages": [{"Body": item["body"], "ReceiptHandle": f"r{index}"}
                             for index, item in enumerate(taken)]}

    def delete_message(self, QueueUrl, ReceiptHandle):  # noqa: N803
        return {}


@pytest.fixture()
def env(monkeypatch):
    import blog_queue as bq
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    sqs = FakeSQS()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    monkeypatch.setattr(bq, "sqs_client", lambda: sqs)
    monkeypatch.setattr(bq, "QUEUE_URL", "https://sqs.test/ingest")
    return {"table": table, "s3": s3, "lambda": lam, "sqs": sqs, "bq": bq, "bs": bs,
            "storage": storage}


def sample_pdf(header: str = "THE GIVEN WORD") -> bytes:
    lines = [header, ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    return make_pdf([lines, lines])


def _uploaded(env, header: str = "THE GIVEN WORD") -> str:
    """A source whose bytes are in S3 and whose status is UPLOADED - queue-ready."""
    payload = sample_pdf(header)
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload, f"{header}.pdf")]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    return source_id


def _message(source_id: str, message_id: str = "msg-1") -> Dict[str, Any]:
    return {"eventSource": "aws:sqs", "messageId": message_id,
            "body": json.dumps({"sourceId": source_id, "reason": "test"})}


# ── Fan-out ─────────────────────────────────────────────────────────────────────

def test_confirming_enqueues_one_message_per_source(env):
    """Serial was the problem: 2,500 sources was 500 sequential invocations of five."""
    ids = [_uploaded(env, f"DOC{index}") for index in range(3)]
    env["sqs"].sent.clear()
    result = env["bs"].confirm({"sourceIds": ids}, "admin")
    assert result["queued"] == 3
    assert result["queueConfigured"] is True
    assert len(env["sqs"].sent) == 3
    bodies = [json.loads(item["body"])["sourceId"] for item in env["sqs"].sent]
    assert set(bodies) == set(ids)


def test_confirming_does_not_also_start_the_sweep(env):
    """Both paths running would double the work and race on every claim."""
    source_id = _uploaded(env)
    env["lambda"].invocations.clear()
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    assert env["lambda"].invocations == []


def test_the_sweep_is_the_fallback_when_no_queue_is_configured(env, monkeypatch):
    """Not defensive padding: it keeps the unit tests and an unprovisioned environment working,
    and it is the same path the reconciliation route uses, so it stays exercised."""
    monkeypatch.setattr(env["bq"], "QUEUE_URL", "")
    source_id = _uploaded(env)
    env["lambda"].invocations.clear()
    env["sqs"].sent.clear()
    result = env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    assert result["queueConfigured"] is False
    assert result["workerStarted"] is True
    assert env["sqs"].sent == []
    assert env["lambda"].invocations


def test_sends_are_chunked_to_the_sqs_batch_limit(env):
    """Ten is SQS's own hard limit on SendMessageBatch, not a tuning choice."""
    sent_batches = []
    original = env["sqs"].send_message_batch

    def counting(QueueUrl, Entries):  # noqa: N803
        sent_batches.append(len(Entries))
        return original(QueueUrl=QueueUrl, Entries=Entries)

    env["sqs"].send_message_batch = counting
    result = env["bq"].enqueue([f"blogsrc_{index:064x}" for index in range(23)])
    assert result["queued"] == 23
    assert sent_batches == [10, 10, 3]


def test_a_partial_send_failure_is_counted_not_swallowed(env):
    """SendMessageBatch returns 200 with a `Failed` list, so a caller checking only for an
    exception counts ten sends when three did not happen."""
    env["sqs"].reject_indices = {0, 4}
    result = env["bq"].enqueue([f"blogsrc_{index:064x}" for index in range(5)])
    assert result["queued"] == 3
    assert result["failed"] == 2


def test_a_send_exception_never_fails_the_request(env):
    """The records are already durable, so a failed hand-off costs a delay, not the work."""
    env["sqs"].raise_on_send = True
    result = env["bq"].enqueue([f"blogsrc_{index:064x}" for index in range(3)])
    assert result == {"queued": 0, "failed": 3, "configured": True}


def test_enqueueing_nothing_is_not_an_error(env):
    assert env["bq"].enqueue([]) == {"queued": 0, "failed": 0, "configured": True}
    assert env["bq"].enqueue(["", None, "  "])["queued"] == 0


# ── The consumer ────────────────────────────────────────────────────────────────

def test_a_message_extracts_its_source(env):
    source_id = _uploaded(env)
    result = env["bq"].consume({"Records": [_message(source_id)]})
    assert result == {"batchItemFailures": []}
    assert env["bs"].get_source(source_id)["status"] == "EXTRACTED"


def test_a_batch_of_messages_is_processed_independently(env):
    ids = [_uploaded(env, f"DOC{index}") for index in range(4)]
    records = [_message(source_id, f"msg-{index}")
               for index, source_id in enumerate(ids)]
    result = env["bq"].consume({"Records": records})
    assert result["batchItemFailures"] == []
    assert all(env["bs"].get_source(source_id)["status"] == "EXTRACTED"
               for source_id in ids)


def test_a_duplicate_delivery_does_not_extract_twice(env):
    """A standard queue is at-least-once. The conditional claim is what makes that safe."""
    source_id = _uploaded(env)
    env["bq"].consume({"Records": [_message(source_id, "msg-1")]})
    extracted_at = env["bs"].get_source(source_id)["updatedAt"]

    calls = {"count": 0}
    original = env["bs"]._store_extract

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    env["bs"]._store_extract = counting
    try:
        result = env["bq"].consume({"Records": [_message(source_id, "msg-2")]})
    finally:
        env["bs"]._store_extract = original
    assert calls["count"] == 0, "the second delivery re-extracted the document"
    assert result["batchItemFailures"] == []
    assert env["bs"].get_source(source_id)["updatedAt"] == extracted_at


def test_only_a_raised_message_is_retried(env):
    """DONE and FAILED are terminal and recorded on the record; retrying re-reads a document to
    reach the same conclusion. SKIPPED means somebody else holds the claim. Only RAISED may be
    transient."""
    good = _uploaded(env, "GOOD")
    thin = _uploaded(env, "THIN")
    #: A source whose object is missing produces a FAILED extract - terminal, not retried.
    del env["s3"].objects[env["table"].items[thin]["s3Key"]]
    exploding = _uploaded(env, "BOOM")

    original = env["bs"]._extract_one

    def sometimes(record, bp):
        if record["id"] == exploding:
            raise RuntimeError("transient")
        return original(record, bp)

    env["bs"]._extract_one = sometimes
    try:
        result = env["bq"].consume({"Records": [
            _message(good, "msg-good"),
            _message(thin, "msg-thin"),
            _message(exploding, "msg-boom"),
        ]})
    finally:
        env["bs"]._extract_one = original

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-boom"}]
    assert env["bs"].get_source(good)["status"] == "EXTRACTED"
    assert env["bs"].get_source(thin)["status"] == "EXTRACTION_FAILED"


def test_a_malformed_body_is_not_retried(env):
    """It cannot succeed on a second attempt, and three redeliveries only delay the DLQ."""
    result = env["bq"].consume({"Records": [
        {"eventSource": "aws:sqs", "messageId": "msg-1", "body": "not json"},
        {"eventSource": "aws:sqs", "messageId": "msg-2", "body": "{}"},
    ]})
    assert result["batchItemFailures"] == []


def test_an_unknown_source_is_not_retried(env):
    """Already deleted, or never existed. No number of retries produces it."""
    result = env["bq"].consume({"Records": [_message("blogsrc_nope")]})
    assert result["batchItemFailures"] == []


def test_the_consumer_refreshes_the_batches_it_touched(env):
    import blog_batches as bb
    batch_id = bb.create({"name": "Wave 1", "defaultCategory": "Conversations"},
                         "admin", q.CATEGORIES, q.ARTICLE_CLASSES)["batchId"]
    payload = sample_pdf("ONE")
    result = env["bs"].register(
        {"batchId": batch_id, "category": "Conversations",
         "sources": [_pdf_entry(payload)]}, "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    env["bq"].consume({"Records": [_message(source_id)]})
    assert bb.get(batch_id)["status"] == bb.READY


# ── The trigger shape is the security boundary ───────────────────────────────────

def test_an_api_gateway_event_is_never_mistaken_for_a_queue_batch(env):
    """The consumer runs without require_auth. What makes that safe is that no HTTP request can
    produce its trigger shape - an API Gateway payload arrives under `body` as a JSON string,
    never as a top-level `Records` key."""
    assert env["bq"].is_queue_event({
        "requestContext": {"http": {"method": "POST", "path": "/seo-tools"}},
        "body": json.dumps({"Records": [{"eventSource": "aws:sqs", "messageId": "x",
                                         "body": "{}"}]}),
    }) is False


def test_another_aws_event_source_is_not_mistaken_for_ingestion(env):
    """S3 and DynamoDB Streams events also carry `Records`."""
    assert env["bq"].is_queue_event({"Records": [
        {"eventSource": "aws:s3", "s3": {}}]}) is False
    assert env["bq"].is_queue_event({"Records": [
        {"eventSource": "aws:dynamodb", "dynamodb": {}}]}) is False
    assert env["bq"].is_queue_event({"Records": [
        {"eventSource": "aws:sqs", "messageId": "a", "body": "{}"},
        {"eventSource": "aws:s3"}]}) is False


def test_an_empty_or_absent_records_key_is_not_a_queue_event(env):
    assert env["bq"].is_queue_event({}) is False
    assert env["bq"].is_queue_event({"Records": []}) is False
    assert env["bq"].is_queue_event({"Records": "not a list"}) is False


def test_the_handler_routes_a_queue_batch_before_anything_else(env, monkeypatch):
    """Checked first, because an SQS batch carries no requestContext at all."""
    import handler
    source_id = _uploaded(env)
    monkeypatch.setattr(handler, "blog_queue", env["bq"])
    result = handler.handler({"Records": [_message(source_id)]}, None)
    assert result == {"batchItemFailures": []}
    assert env["bs"].get_source(source_id)["status"] == "EXTRACTED"


def test_an_infrastructural_failure_reports_every_message(env, monkeypatch):
    """A failure that escapes `consume` is infrastructural, so the messages should redeliver and
    eventually dead-letter rather than vanish."""
    import handler
    monkeypatch.setattr(handler.blog_queue, "consume",
                        lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    result = handler.handler({"Records": [
        {"eventSource": "aws:sqs", "messageId": "a", "body": "{}"},
        {"eventSource": "aws:sqs", "messageId": "b", "body": "{}"},
    ]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "a"},
                                            {"itemIdentifier": "b"}]}


# ── Depth, reconciliation and redrive ───────────────────────────────────────────

def test_depth_reports_the_dlq_separately(env):
    """A DLQ with anything in it is the signal that matters: a document failed three deliveries
    and nothing else in this system will mention it again."""
    env["bq"].enqueue(["blogsrc_" + "a" * 64])
    env["sqs"].dlq.append({"body": json.dumps({"sourceId": "blogsrc_" + "b" * 64})})
    state = env["bq"].depth()
    assert state["configured"] is True
    assert state["visible"] == 1
    assert state["dlq"] == 1


def test_depth_says_so_when_there_is_no_queue(env, monkeypatch):
    monkeypatch.setattr(env["bq"], "QUEUE_URL", "")
    state = env["bq"].depth()
    assert state["configured"] is False
    assert "sweep" in state["note"]


def test_a_missing_dlq_degrades_rather_than_failing(env):
    env["sqs"].queues.clear()
    state = env["bq"].depth()
    assert state["configured"] is True
    assert state["dlq"] == 0
    assert "dlq depth unavailable" in state["note"]


def test_redrive_moves_dead_lettered_messages_back(env):
    for index in range(3):
        env["sqs"].dlq.append({"body": json.dumps({"sourceId": f"blogsrc_{index:064x}"})})
    env["sqs"].sent.clear()
    result = env["bq"].redrive()
    assert result["moved"] == 3
    assert result["remaining"] == 0
    assert len(env["sqs"].sent) == 3


def test_redrive_respects_a_limit(env):
    for index in range(5):
        env["sqs"].dlq.append({"body": json.dumps({"sourceId": f"blogsrc_{index:064x}"})})
    assert env["bq"].redrive(limit=2)["moved"] == 2
    assert len(env["sqs"].dlq) == 3


def test_the_sweep_still_finds_a_source_with_no_message(env):
    """The reconciliation case: a record written before the queue existed, a partially failed
    SendMessageBatch, a message that aged out. The sweep asks the TABLE what is outstanding,
    which is the only check that does not assume the queue is correct."""
    payload = sample_pdf("ORPHAN")
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload)]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    #: Straight to UPLOADED without a confirm, so no message was ever sent.
    env["table"].items[source_id]["status"] = "UPLOADED"
    assert env["sqs"].sent == []
    assert [row["id"] for row in env["bs"].pending_sources()] == [source_id]
    env["bs"].run_worker({})
    assert env["bs"].get_source(source_id)["status"] == "EXTRACTED"


def test_process_source_is_the_single_unit_of_work(env):
    """The sweep and the consumer must not drift, so they share it."""
    source = ROOT / "amplify" / "functions" / "operations" / "seo-tools"
    worker = (source / "blog_sources.py").read_text(encoding="utf-8")
    consumer = (source / "blog_queue.py").read_text(encoding="utf-8")
    assert "process_source(" in worker
    assert "blog_sources.process_source(" in consumer
    #: Neither may re-implement the claim-extract-store sequence.
    assert consumer.count("_store_extract") == 0
    assert consumer.count("_claim_for_extraction") == 0


# ── The deploy contract ─────────────────────────────────────────────────────────

def _deploy_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dep_seo_queue", ROOT / "scripts" / "deploy_seo_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_consumer_concurrency_is_capped():
    """This function ALSO serves the admin HTTP API. Uncapped, SQS scales a consumer to 1,000
    concurrent executions and every admin request queues behind document extraction."""
    module = _deploy_module()
    assert 2 <= module.MAX_CONCURRENCY <= 20
    import blog_queue as bq
    assert module.MAX_CONCURRENCY == bq.MAX_CONCURRENCY
    assert module.CONSUME_BATCH == bq.CONSUME_BATCH
    assert module.MAX_RECEIVES == bq.MAX_RECEIVES


def test_the_visibility_timeout_exceeds_the_function_timeout():
    """A visibility timeout shorter than the handler's worst case is the classic SQS mistake:
    the message reappears while the first consumer is still working and the work happens twice."""
    module = _deploy_module()
    assert module.VISIBILITY_TIMEOUT > module.FUNCTION_TIMEOUT
    #: Derived rather than coincidentally larger. The worst case is a full batch of documents
    #: each taking the whole function timeout, so the relationship has to hold as either number
    #: changes - `FUNCTION_TIMEOUT` was a bare 120 in two places, which is how they drift.
    assert module.VISIBILITY_TIMEOUT >= module.FUNCTION_TIMEOUT * module.CONSUME_BATCH
    assert module.VISIBILITY_TIMEOUT <= 43_200, "SQS caps VisibilityTimeout at 12 hours"


def test_the_dlq_retains_longer_than_the_queue():
    """A dead-lettered document is evidence; the maximum retention is the right answer."""
    module = _deploy_module()
    assert module.DLQ_RETENTION > module.MESSAGE_RETENTION
    assert module.DLQ_RETENTION == 1_209_600


def test_the_queue_names_match_the_lambda_constants():
    module = _deploy_module()
    import blog_queue as bq
    assert module.QUEUE_NAME == bq.QUEUE_NAME
    assert module.DLQ_NAME == bq.DLQ_NAME


def test_the_mapping_reports_batch_item_failures():
    """Without it, one bad document in a batch of five redelivers all five."""
    source = (ROOT / "scripts" / "deploy_seo_tools.py").read_text(encoding="utf-8")
    assert "ReportBatchItemFailures" in source
    assert "ScalingConfig" in source
    assert "MaximumConcurrency" in source


# ── Bulk publish fan-out on the same queue ─────────────────────────────────────

def test_bulk_publish_enqueue_uses_same_queue_and_carries_actor(env):
    env["sqs"].sent.clear()
    result = env["bq"].enqueue_publish(["blogpub_a", "blogpub_b"], "operator")
    assert result == {"queued": 2, "failed": 0, "configured": True}
    bodies = [json.loads(item["body"]) for item in env["sqs"].sent]
    assert bodies == [
        {"action": "publish", "jobId": "blogpub_a", "actor": "operator",
         "reason": "bulk-publish"},
        {"action": "publish", "jobId": "blogpub_b", "actor": "operator",
         "reason": "bulk-publish"},
    ]


def test_bulk_publish_rejects_more_than_1000_queue_items(env):
    with pytest.raises(ValueError, match="at most 1000"):
        env["bq"].enqueue_publish(
            [f"blogpub_{index}" for index in range(1001)], "operator")


def test_bulk_publish_consumer_calls_existing_publish_path(env, monkeypatch):
    import blog_publish

    calls = []
    def fake_publish(job_id, actor):
        calls.append((job_id, actor))
        return {"jobId": job_id, "status": "PUBLISHED", "published": True}

    monkeypatch.setattr(blog_publish, "publish", fake_publish)
    result = env["bq"].consume({"Records": [
        {"eventSource": "aws:sqs", "messageId": "p1",
         "body": json.dumps({"action": "publish", "jobId": "blogpub_a",
                             "actor": "operator"})},
    ]})
    assert result == {"batchItemFailures": []}
    assert calls == [("blogpub_a", "operator")]


def test_bulk_publish_deterministic_rejection_is_not_retried(env, monkeypatch):
    import blog_publish

    monkeypatch.setattr(blog_publish, "publish",
                        lambda job_id, actor: (_ for _ in ()).throw(
                            ValueError("sign-off was revoked")))
    result = env["bq"].consume({"Records": [
        {"eventSource": "aws:sqs", "messageId": "p1",
         "body": json.dumps({"action": "publish", "jobId": "blogpub_a",
                             "actor": "operator"})},
    ]})
    assert result == {"batchItemFailures": []}
