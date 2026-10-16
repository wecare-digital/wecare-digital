"""SQS fan-out for bulk ingestion, and the three things that made a self-chaining sweep wrong.

WHAT THE SWEEP DID, AND WHY IT DOES NOT SCALE.

`blog_sources.run_worker` asks the table for UPLOADED sources, extracts five, and re-invokes
itself if any remain. For fifty documents that is fine. For the stated requirement - thousands in
one go - it has three problems, and only the first is about speed:

1. **It is strictly serial.** One invocation at a time, five documents each, so 2,500 sources is
   500 sequential invocations. The work is embarrassingly parallel and none of it was.
2. **A poison document stops nothing and retries forever.** A PDF that makes pypdf raise is
   marked EXTRACTION_FAILED and skipped, which is correct - but a source that fails for a
   TRANSIENT reason gets no retry at all unless somebody clicks Retry, and a source that fails
   deterministically inside the chain has nowhere to be recorded except its own status field.
3. **Every invocation pays a full sweep.** `pending_sources` filters the whole `blogSource`
   partition server-side AFTER reading it, so the cost of finding the next five documents grows
   with the total number of sources - fastest at the start of a run and slowest at the end.

A queue fixes all three: messages are consumed concurrently, a message that keeps failing lands
in a dead-letter queue instead of disappearing, and a consumer is handed its work rather than
searching for it.

## Why the queue cannot starve the API it shares a function with

`wecare-seo-tools` serves the admin HTTP API AND consumes this queue. Left alone, SQS scales a
consumer up to 1,000 concurrent executions, which would consume the account's concurrency and
make every admin request queue behind document extraction.

`ScalingConfig.MaximumConcurrency` on the event source mapping is the control, set to
`MAX_CONCURRENCY` below. Five concurrent extractions is still five times the old serial rate, and
it leaves the function's concurrency overwhelmingly available to the API. The alternative -
reserving concurrency for the API - would cap the API instead, which is the wrong end.

## At-least-once delivery is safe here, and it is not luck

A standard queue can deliver the same message twice. `blog_sources.process_source` claims a
source with a conditional write on `status = UPLOADED`, so the second delivery loses the race and
returns SKIPPED. That is the same mechanism that made the self-chaining sweep safe when a chained
invocation overlapped its predecessor, and it is why a FIFO queue is not needed - FIFO would add
ordering nobody wants and a 300 messages/second cap for no benefit.

## Partial batch failure, reported per message

With `ReportBatchItemFailures` the consumer returns the identifiers of just the messages that
failed, and only those are retried. Without it, one bad document in a batch of ten redelivers all
ten, so nine already-extracted sources are re-read, lose the claim race, and the batch makes no
progress while looking busy.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

import boto3

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

#: Set by the deploy script. ABSENT IS A SUPPORTED STATE, not an error: unit tests and a
#: not-yet-provisioned environment fall back to the sweep, and `enqueue` reports
#: `configured: False` so the caller can tell the difference between "queued nothing" and "there
#: is no queue".
QUEUE_URL = os.environ.get("BLOG_INGEST_QUEUE_URL", "")
QUEUE_NAME = os.environ.get("BLOG_INGEST_QUEUE_NAME", "wecare-blog-ingest")
DLQ_NAME = QUEUE_NAME + "-dlq"

#: SQS's own hard limit on `SendMessageBatch`. Not a tuning choice.
SEND_BATCH = 10

#: The event source mapping's batch size and concurrency cap. Small batches on purpose: a
#: 40 MB PDF can take seconds, and a batch of ten of them risks the visibility timeout, at which
#: point the messages redeliver and the work is done twice.
CONSUME_BATCH = 5
MAX_CONCURRENCY = 5

#: Deliveries before a message is dead-lettered. Three is enough to ride out a transient S3 read
#: or a cold pypdf import, and few enough that a deterministically poisonous document reaches the
#: DLQ within a minute rather than cycling for an hour.
MAX_RECEIVES = 3

_sqs = None


def sqs_client():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=REGION)
    return _sqs


def configured() -> bool:
    return bool(QUEUE_URL)


def _send_payloads(payloads: Sequence[Dict[str, Any]], event_name: str) -> Dict[str, Any]:
    if not payloads:
        return {"queued": 0, "failed": 0, "configured": configured()}
    if not configured():
        return {"queued": 0, "failed": 0, "configured": False}

    queued = failed = 0
    client = sqs_client()
    for start in range(0, len(payloads), SEND_BATCH):
        chunk = payloads[start:start + SEND_BATCH]
        entries = [{
            "Id": str(index),
            "MessageBody": json.dumps(payload, separators=(",", ":")),
        } for index, payload in enumerate(chunk)]
        try:
            response = client.send_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
        except Exception as exc:  # noqa: BLE001
            failed += len(chunk)
            logger.warning(json.dumps({
                "event": event_name + "_failed", "count": len(chunk),
                "error": type(exc).__name__,
            }))
            continue
        queued += len(response.get("Successful") or [])
        for item in response.get("Failed") or []:
            failed += 1
            logger.warning(json.dumps({
                "event": event_name + "_rejected",
                "code": str(item.get("Code") or ""),
                "senderFault": bool(item.get("SenderFault")),
            }))
    logger.info(json.dumps({"event": event_name, "queued": queued, "failed": failed}))
    return {"queued": queued, "failed": failed, "configured": True}


def enqueue(source_ids: Sequence[str], reason: str = "") -> Dict[str, Any]:
    """Fan out source extraction. Existing callers remain backwards-compatible."""
    ids = [str(value) for value in source_ids if str(value or "").strip()]
    return _send_payloads(
        [{"action": "extract", "sourceId": source_id, "reason": reason}
         for source_id in ids],
        "blog_ingest_enqueued",
    )


def _send_one(payload: Dict[str, Any], event_name: str, delay_seconds: int = 0) -> Dict[str, Any]:
    if not configured():
        return {"queued": 0, "failed": 0, "configured": False}
    try:
        sqs_client().send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payload, separators=(",", ":")),
            DelaySeconds=max(0, min(int(delay_seconds or 0), 900)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": event_name + "_failed", "error": type(exc).__name__,
        }))
        return {"queued": 0, "failed": 1, "configured": True}
    logger.info(json.dumps({"event": event_name, "queued": 1, "failed": 0}))
    return {"queued": 1, "failed": 0, "configured": True}


def enqueue_site_build(generation: int, actor: str, delay_seconds: int = 0) -> Dict[str, Any]:
    return _send_one(
        {"action": "site-build", "generation": int(generation), "actor": str(actor or "site-bridge")},
        "blog_site_build_enqueued", delay_seconds)


def enqueue_site_check(job_id: str, attempt: int = 1, delay_seconds: int = 0) -> Dict[str, Any]:
    return _send_one(
        {"action": "site-check", "jobId": str(job_id), "attempt": int(attempt)},
        "blog_site_check_enqueued", delay_seconds)


def enqueue_site_verify(source_ids: Sequence[str], job_id: str, attempt: int = 1,
                        delay_seconds: int = 0) -> Dict[str, Any]:
    ids = [str(value) for value in source_ids if str(value or "").strip()]
    failed_ids: List[str] = []
    queued = 0
    for source_id in ids:
        result = _send_one(
            {"action": "site-verify", "sourceId": source_id, "jobId": str(job_id),
             "attempt": int(attempt), "actor": "site-bridge"},
            "blog_site_verify_enqueued", delay_seconds)
        if int(result.get("queued") or 0) == 1:
            queued += 1
        else:
            failed_ids.append(source_id)
    return {
        "queued": queued,
        "failed": len(failed_ids),
        "configured": configured(),
        "failedSourceIds": failed_ids,
    }


def enqueue_publish(job_ids: Sequence[str], actor: str, reason: str = "bulk-publish") -> Dict[str, Any]:
    """Fan out publish work for jobs that were already explicitly released.

    This never releases an article and therefore cannot turn extraction/batch completion into
    publication. It only scales the second phase of the existing two-phase release -> publish
    contract. The worker re-runs blog_publish.publish, including its conditional claim and
    publish-time sign-off/body-hash checks.
    """
    ids = [str(value) for value in job_ids if str(value or "").strip()]
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required for bulk publish")
    return _send_payloads(
        [{"action": "publish", "jobId": job_id, "actor": who, "reason": reason}
         for job_id in ids],
        "blog_publish_bulk_enqueued",
    )


def is_queue_event(event: Dict[str, Any]) -> bool:
    """True only for a genuine SQS batch.

    Checked on `eventSource` rather than merely on the presence of `Records`, because S3 and
    DynamoDB Streams events also carry `Records` and would otherwise be mistaken for ingestion
    work. An API Gateway request cannot produce a top-level `Records` key at all - an HTTP
    payload arrives under `body` as a JSON string - so this branch is reachable only through the
    event source mapping, which is IAM-gated.
    """
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        return False
    return all(isinstance(record, dict) and record.get("eventSource") == "aws:sqs"
               for record in records)


def _payload_of(record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        body = json.loads(record.get("body") or "{}")
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _source_id_of(record: Dict[str, Any]) -> str:
    return str(_payload_of(record).get("sourceId") or "").strip()


def consume(event: Dict[str, Any]) -> Dict[str, Any]:
    """Consume extraction and explicit publish jobs with per-message retry."""
    import blog_publish
    import blog_sources

    records = event.get("Records") or []
    failures: List[Dict[str, str]] = []
    outcomes: Dict[str, int] = {}
    touched: set = set()

    for record in records:
        message_id = str(record.get("messageId") or "")
        payload = _payload_of(record)
        action = str(payload.get("action") or "extract").strip().lower()

        if action == "site-build":
            try:
                import blog_site_bridge
                result = blog_site_bridge.start_build(
                    str(payload.get("actor") or "site-bridge"))
                state = str(result.get("status") or "UNKNOWN")
                outcomes["SITE_BUILD_" + state] = outcomes.get("SITE_BUILD_" + state, 0) + 1
            except Exception:  # noqa: BLE001
                logger.exception("site build trigger failed")
                outcomes["SITE_BUILD_RAISED"] = outcomes.get("SITE_BUILD_RAISED", 0) + 1
                if message_id:
                    failures.append({"itemIdentifier": message_id})
            continue

        if action == "site-check":
            try:
                import blog_site_bridge
                result = blog_site_bridge.check_build(
                    str(payload.get("jobId") or ""),
                    int(payload.get("attempt") or 1))
                state = str(result.get("status") or "UNKNOWN")
                outcomes["SITE_CHECK_" + state] = outcomes.get("SITE_CHECK_" + state, 0) + 1
            except (LookupError, ValueError) as exc:
                outcomes["SITE_CHECK_REJECTED"] = outcomes.get("SITE_CHECK_REJECTED", 0) + 1
                logger.warning(json.dumps({
                    "event": "blog_site_check_rejected", "error": str(exc)[:300],
                }))
            except Exception:  # noqa: BLE001
                logger.exception("site build check failed")
                outcomes["SITE_CHECK_RAISED"] = outcomes.get("SITE_CHECK_RAISED", 0) + 1
                if message_id:
                    failures.append({"itemIdentifier": message_id})
            continue

        if action == "site-verify":
            try:
                import blog_site_bridge
                result = blog_site_bridge.verify_article(
                    str(payload.get("sourceId") or ""),
                    str(payload.get("jobId") or ""),
                    int(payload.get("attempt") or 1),
                    str(payload.get("actor") or "site-bridge"))
                state = str(result.get("status") or "UNKNOWN")
                outcomes["SITE_VERIFY_" + state] = outcomes.get("SITE_VERIFY_" + state, 0) + 1
            except (LookupError, ValueError) as exc:
                outcomes["SITE_VERIFY_REJECTED"] = outcomes.get("SITE_VERIFY_REJECTED", 0) + 1
                logger.warning(json.dumps({
                    "event": "blog_site_verify_rejected", "error": str(exc)[:300],
                }))
            except Exception:  # noqa: BLE001
                logger.exception("site verification message failed")
                outcomes["SITE_VERIFY_RAISED"] = outcomes.get("SITE_VERIFY_RAISED", 0) + 1
                if message_id:
                    failures.append({"itemIdentifier": message_id})
            continue

        if action == "publish":
            job_id = str(payload.get("jobId") or "").strip()
            actor = str(payload.get("actor") or "").strip()
            if not job_id or not actor:
                outcomes["MALFORMED_PUBLISH"] = outcomes.get("MALFORMED_PUBLISH", 0) + 1
                continue
            try:
                result = blog_publish.publish(job_id, actor)
                state = str(result.get("status") or "PUBLISHED")
                outcomes["PUBLISH_" + state] = outcomes.get("PUBLISH_" + state, 0) + 1
            except (LookupError, ValueError) as exc:
                # Deterministic refusal: missing job, revoked sign-off, edited body, or a
                # non-QUEUED state. Retrying the same message cannot change those facts.
                outcomes["PUBLISH_REJECTED"] = outcomes.get("PUBLISH_REJECTED", 0) + 1
                logger.warning(json.dumps({
                    "event": "blog_publish_bulk_rejected", "jobId": job_id,
                    "error": str(exc)[:300],
                }))
            except Exception as exc:  # noqa: BLE001
                outcomes["PUBLISH_RAISED"] = outcomes.get("PUBLISH_RAISED", 0) + 1
                logger.exception("bulk blog publish message failed")
                if message_id:
                    failures.append({"itemIdentifier": message_id})
            continue

        source_id = str(payload.get("sourceId") or "").strip()
        if not source_id:
            outcomes["MALFORMED"] = outcomes.get("MALFORMED", 0) + 1
            logger.warning(json.dumps({
                "event": "blog_ingest_message_malformed", "messageId": message_id}))
            continue
        stored = blog_sources.get_source(source_id)
        if stored:
            touched.add(str(stored.get("batchId") or blog_sources.NO_BATCH))
        try:
            outcome = blog_sources.process_source(source_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("blog ingest message failed")
            outcome = blog_sources.RAISED
            logger.warning(json.dumps({
                "event": "blog_ingest_message_raised", "sourceId": source_id,
                "error": type(exc).__name__}))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome == blog_sources.RAISED and message_id:
            failures.append({"itemIdentifier": message_id})

    blog_sources.refresh_batches(touched)
    logger.info(json.dumps({
        "event": "blog_queue_batch", "messages": len(records),
        "outcomes": dict(sorted(outcomes.items())), "retried": len(failures),
        "batches": sorted(touched),
    }))
    return {"batchItemFailures": failures}


def depth() -> Dict[str, Any]:
    """Queue and DLQ depth, for the dashboard and the alarms.

    A DLQ with anything in it is the signal that matters: it means a document failed three
    deliveries, and nothing else in this system will mention it again.
    """
    if not configured():
        return {"configured": False, "visible": 0, "inFlight": 0, "dlq": 0,
                "note": "no ingest queue is configured; extraction uses the sweep"}
    client = sqs_client()
    out: Dict[str, Any] = {"configured": True, "visible": 0, "inFlight": 0, "dlq": 0,
                           "note": ""}
    try:
        attributes = client.get_queue_attributes(
            QueueUrl=QUEUE_URL,
            AttributeNames=["ApproximateNumberOfMessages",
                            "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
        out["visible"] = int(attributes.get("ApproximateNumberOfMessages") or 0)
        out["inFlight"] = int(attributes.get("ApproximateNumberOfMessagesNotVisible") or 0)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"queue depth unavailable ({type(exc).__name__})"
    try:
        dlq_url = client.get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
        attributes = client.get_queue_attributes(
            QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]
        out["dlq"] = int(attributes.get("ApproximateNumberOfMessages") or 0)
    except Exception as exc:  # noqa: BLE001
        out["note"] = (out["note"] + "; " if out["note"] else "") + \
            f"dlq depth unavailable ({type(exc).__name__})"
    return out


def redrive(limit: int = 0) -> Dict[str, Any]:
    """Move dead-lettered messages back onto the ingest queue.

    Deliberately explicit rather than automatic. A message reaches the DLQ after three failures,
    so the reason is usually not transient - re-driving without looking is how a genuinely
    unreadable PDF cycles forever. An operator reads the source's `error` field first, fixes the
    cause, and then re-drives.

    Implemented by receive-and-resend rather than `StartMessageMoveTask` so the count is exact
    and reported synchronously; the move task is asynchronous and reports progress separately,
    which is the wrong shape for a route that has to tell an operator what happened.
    """
    if not configured():
        return {"moved": 0, "remaining": 0, "configured": False}
    client = sqs_client()
    try:
        dlq_url = client.get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
    except Exception as exc:  # noqa: BLE001
        return {"moved": 0, "remaining": 0, "configured": True,
                "error": f"no dead-letter queue ({type(exc).__name__})"}

    moved = 0
    ceiling = limit or 500
    while moved < ceiling:
        received = client.receive_message(
            QueueUrl=dlq_url, MaxNumberOfMessages=min(10, ceiling - moved),
            WaitTimeSeconds=0)
        messages = received.get("Messages") or []
        if not messages:
            break
        for message in messages:
            client.send_message(QueueUrl=QUEUE_URL, MessageBody=message["Body"])
            client.delete_message(QueueUrl=dlq_url,
                                  ReceiptHandle=message["ReceiptHandle"])
            moved += 1
    state = depth()
    logger.info(json.dumps({"event": "blog_ingest_redrive", "moved": moved,
                            "dlqRemaining": state["dlq"]}))
    return {"moved": moved, "remaining": state["dlq"], "configured": True}
