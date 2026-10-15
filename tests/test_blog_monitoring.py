"""Monitoring: the failure modes the existing Lambda-error alarm structurally cannot see.

WHY THESE ALARMS ARE NOT REDUNDANT.

`wecare-lambda-errors-wecare-seo-tools` already alarms on unhandled Lambda errors, and it is the
wrong instrument for this pipeline. Every failure mode here is CAUGHT and recorded on a record
rather than raised, which is correct: one bad PDF must not stop a batch of 2,500, a failed
verification is evidence rather than a crash, a rejected post is a defect rather than an outage.

The consequence is the thing worth testing. A run in which every single document failed produces
zero Lambda errors, so from the existing alarms it is indistinguishable from a run in which every
document succeeded.

THE TEST THAT CARRIES THIS FILE is `test_a_refusal_never_pages_anybody`. A refusal is an
operator's own decision, not a defect. Paging somebody because the switch they threw is working is
how a channel gets ignored, and an ignored channel is worth less than no channel.
"""
from __future__ import annotations

import importlib.util
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
from blog_pdf_fixture import make_pdf  # noqa: E402
from test_blog_sources import FakeLambda, FakeS3, FakeTable, _pdf_entry  # noqa: E402


def deploy_module():
    spec = importlib.util.spec_from_file_location(
        "dep_seo_alarms", ROOT / "scripts" / "deploy_seo_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def env(monkeypatch):
    import blog_sources as bs
    import storage

    table = FakeTable()
    s3 = FakeS3()
    lam = FakeLambda()
    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(bs, "s3_client", lambda: s3)
    monkeypatch.setattr(bs, "lambda_client", lambda: lam)
    monkeypatch.setattr(bs, "BUCKET", "wecare-digital-get")
    return {"table": table, "s3": s3, "bs": bs, "storage": storage}


# ── The alarms exist and every one of them pages somebody ───────────────────────

def test_every_alarm_names_an_action():
    """`put_metric_alarm` accepts an empty `AlarmActions` without complaint.

    An alarm that pages nobody is created just as successfully as one that works, and reads
    identically in a deploy log. So the deploy verifies it afterwards and refuses, and this asserts
    that every alarm definition carries the topic in the first place.
    """
    module = deploy_module()
    assert module.ALARM_TOPIC.startswith("arn:aws:sns:")
    assert module.ALARM_TOPIC.endswith(":wecare-alarm-notifications")
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    #: EVERY CALL SITE, not every alarm. Three sites create five alarms, because the three
    #: log-metric alarms share one `put_metric_alarm` inside a loop over `LOG_ALARMS` - counting
    #: alarms rather than calls asserted 5 and found 3, which is a test failing on its own
    #: arithmetic rather than on a defect.
    calls = source.count("cw.put_metric_alarm(")
    assert calls == 3, f"{calls} put_metric_alarm call sites; update this test deliberately"
    assert source.count("AlarmActions=[ALARM_TOPIC]") == calls, (
        "a put_metric_alarm call site does not name the SNS topic")
    assert "AlarmActions=[]" not in source


def test_the_deploy_refuses_an_actionless_alarm():
    """The verification step is not decoration: it is the only thing that catches a topic ARN
    that is wrong rather than missing."""
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    assert "would page nobody" in source
    assert "raise SystemExit" in source


def test_the_alarms_use_the_topic_every_existing_alarm_uses():
    """61 alarms already route there. A new topic would be a second place to check."""
    module = deploy_module()
    assert module.ALARM_TOPIC == (
        f"arn:aws:sns:{module.REGION}:{module.ACCOUNT}:wecare-alarm-notifications")


def test_the_namespace_matches_the_existing_custom_metrics():
    """`scripts/_create_dedup_alarm.py` established WECARE.DIGITAL. A second namespace would
    split the custom metrics across two places in the console."""
    module = deploy_module()
    assert module.ALARM_NAMESPACE == "WECARE.DIGITAL"
    dedup = ( ROOT / "scripts" / "_create_dedup_alarm.py" ).read_text(encoding="utf-8")
    assert 'NS = "WECARE.DIGITAL"' in dedup


def test_three_log_alarms_cover_the_three_recorded_failure_modes():
    module = deploy_module()
    names = {name for name, *_ in module.LOG_ALARMS}
    assert names == {
        "wecare-blog-extraction-failures",
        "wecare-blog-verification-failures",
        "wecare-blog-publish-failures",
    }
    for name, event, metric, threshold, period, description in module.LOG_ALARMS:
        assert event.startswith("blog_"), event
        assert metric.startswith("Blog"), metric
        assert period in (60, 300), period
        assert len(description) > 60, f"{name} has no usable description"


def test_the_thresholds_are_not_all_zero():
    """A single extraction failure in a 2,500-document wave is ordinary - a scanned PDF with no
    text layer - and alarming on it would fire on every real batch. A verification failure is
    different: it means a LIVE article does not match what was approved."""
    module = deploy_module()
    thresholds = { name: threshold for name, _, _, threshold, _, _ in module.LOG_ALARMS }
    assert thresholds["wecare-blog-extraction-failures"] > 0
    assert thresholds["wecare-blog-verification-failures"] == 0
    assert thresholds["wecare-blog-publish-failures"] == 0


def test_the_queue_alarms_measure_the_right_thing():
    """Depth is meaningless on the main queue mid-wave - 2,000 messages is a healthy fan-out - so
    the main queue is alarmed on AGE and only the DLQ on depth."""
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    module = deploy_module()
    assert 'MetricName="ApproximateNumberOfMessagesVisible"' in source
    assert 'MetricName="ApproximateAgeOfOldestMessage"' in source
    #: The depth alarm is on the DLQ and the age alarm on the ingest queue, not the other way round.
    depth = source.split('MetricName="ApproximateNumberOfMessagesVisible"', 1)[1][:400]
    assert '"Value": DLQ_NAME' in depth
    age = source.split('MetricName="ApproximateAgeOfOldestMessage"', 1)[1][:400]
    assert '"Value": QUEUE_NAME' in age
    assert module.MAX_RECEIVES == 3


def test_the_dlq_alarm_explains_what_to_do():
    """A DLQ message is the one failure nothing else in the system will mention again: it is not
    in the queue, its source row still says UPLOADED, and the sweep will re-queue it only to have
    it fail three more times. The description has to name the route out."""
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    assert "/blog-sources/redrive" in source


def test_the_metric_filters_default_to_zero():
    """Without a default the metric has NO datapoints while nothing is failing, and
    `TreatMissingData` decides the state instead of the data. With 0 the alarm sits in OK on
    evidence."""
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    assert '"defaultValue": 0.0' in source
    assert 'TreatMissingData="notBreaching"' in source


def test_alarms_are_provisioned_after_the_function():
    """A metric filter needs its log group. Lambda creates `/aws/lambda/<name>` on first use, and
    `put_metric_filter` against a missing group raises rather than no-opping."""
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    body = source.split("def main()", 1)[1]
    assert body.index("deploy_lambda(") < body.index("provision_alarms(")


# ── The events the filters count are actually emitted ───────────────────────────

def test_an_extraction_failure_logs_the_event_the_filter_counts(env, caplog):
    """The event has to exist, or the filter counts a string that is never written and the alarm
    sits in OK for ever - which is worse than no alarm, because it is believed."""
    import logging
    module = deploy_module()
    event = dict((name, ev) for name, ev, *_ in module.LOG_ALARMS)[
        "wecare-blog-extraction-failures"]

    #: A PDF with no usable prose, which is the ordinary cause of a real extraction failure.
    payload = make_pdf([["x"], ["y"]])
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload)]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")

    with caplog.at_level(logging.WARNING):
        env["bs"].run_worker({})
    assert env["bs"].get_source(source_id)["status"] == "EXTRACTION_FAILED"
    emitted = [record.getMessage() for record in caplog.records]
    assert any(event in message for message in emitted), (
        f"{event} was never logged, so the metric filter would count nothing")
    line = next(message for message in emitted if event in message)
    payload_json = json.loads(line)
    assert payload_json["sourceId"] == source_id
    assert payload_json["error"]


def test_a_successful_extraction_logs_no_failure_event(env, caplog):
    """A filter that also matched the success path would alarm on a healthy batch."""
    import logging
    from test_blog_qa import PROSE
    from blog_pdf_fixture import wrap
    lines = ["THE GIVEN WORD", ""]
    for paragraph in PROSE:
        lines += wrap(paragraph) + [""]
    payload = make_pdf([lines, lines])
    result = env["bs"].register(
        {"category": "Conversations", "sources": [_pdf_entry(payload)]},
        "admin", q.CATEGORIES)
    source_id = result["sources"][0]["sourceId"]
    env["s3"].objects[env["table"].items[source_id]["s3Key"]] = payload
    env["bs"].confirm({"sourceIds": [source_id]}, "admin")
    with caplog.at_level(logging.WARNING):
        env["bs"].run_worker({})
    assert env["bs"].get_source(source_id)["status"] == "EXTRACTED"
    assert not any("blog_source_extraction_failed" in record.getMessage()
                   for record in caplog.records)


def test_the_verification_failure_event_is_the_one_the_filter_counts():
    """`blog_verify` already logged this name before the alarm existed, so the filter reuses it
    rather than adding a second line for the same fact."""
    module = deploy_module()
    event = dict((name, ev) for name, ev, *_ in module.LOG_ALARMS)[
        "wecare-blog-verification-failures"]
    source = ( ROOT / "amplify" / "functions" / "operations" / "seo-tools"
               / "blog_verify.py" ).read_text(encoding="utf-8")
    assert f'"{event}"' in source


def test_the_publish_failure_event_is_emitted_and_the_refusal_is_gone():
    """The failure event the alarm counts is emitted, and no refusal event exists.

    Native publishing has no credential to revoke and no kill switch, so a publish is never
    REFUSED - a write either PUBLISHED or FAILED. The alarm counts `blog_publish_failed` (a write
    that did not succeed), and `blog_publish_refused` is emitted nowhere, so there is no refusal
    event for a filter to accidentally count.
    """
    module = deploy_module()
    events = { name: ev for name, ev, *_ in module.LOG_ALARMS }
    source = ( ROOT / "amplify" / "functions" / "operations" / "seo-tools"
               / "blog_publish.py" ).read_text(encoding="utf-8")
    assert f'"{events["wecare-blog-publish-failures"]}"' in source
    assert '"blog_publish_refused"' not in source


def test_a_refusal_never_pages_anybody():
    """THE test. A refusal is an operator's own decision, not a defect.

    Paging somebody because the switch they threw is working is how a channel gets ignored, and an
    ignored channel is worth less than no channel. The filter patterns are exact strings, so this
    asserts `blog_publish_refused` appears in none of them.
    """
    module = deploy_module()
    for name, event, *_ in module.LOG_ALARMS:
        assert event != "blog_publish_refused", name
        assert "refused" not in event, f"{name} counts a refusal: {event}"
    source = ( ROOT / "scripts" / "deploy_seo_tools.py" ).read_text(encoding="utf-8")
    assert "blog_publish_refused" not in source.split("def provision_alarms", 1)[1]


# ── Naming stays in the house convention ────────────────────────────────────────

def test_alarm_names_follow_the_existing_convention():
    """Eight `wecare-*-dlq-depth` and a `wecare-queue-age-*` already exist. A new shape would make
    the console list stop sorting usefully."""
    module = deploy_module()
    stem = module.QUEUE_NAME.removeprefix("wecare-")
    assert f"wecare-{stem}-dlq-depth" == "wecare-blog-ingest-dlq-depth"
    assert f"wecare-queue-age-{stem}" == "wecare-queue-age-blog-ingest"
    for name, *_ in module.LOG_ALARMS:
        assert name.startswith("wecare-blog-"), name
