"""OPS-6: media-cleanup skips cleaned rows in the scan, updates by the table key, and logs an
alert key when nothing could be processed."""
import importlib.util
import itertools
import json
import time
from pathlib import Path

import pytest

MEDIA = (Path(__file__).resolve().parents[2]
         / "amplify/functions/messaging/media-cleanup/handler.py")
_names = itertools.count()
OLD = int(time.time()) - 40 * 86400


class MediaTable:
    """Applies the parts of the scan filter the handler relies on, one page per call."""

    def __init__(self, rows, page=10, fail=False):
        self.rows, self.page, self.fail = rows, page, fail
        self.filters, self.updates = [], []

    def scan(self, FilterExpression, ExpressionAttributeValues, ExclusiveStartKey=None):
        if self.fail:
            raise RuntimeError("scan failed")
        self.filters.append(FilterExpression)
        start = (ExclusiveStartKey or {}).get("i", 0)
        chunk = self.rows[start:start + self.page]
        cutoff = ExpressionAttributeValues[":cutoff"]
        items = [dict(r) for r in chunk if r["uploadedAt"] < cutoff and r.get("whatsappMediaId")
                 and not ("attribute_not_exists(cleanedUp)" in FilterExpression and "cleanedUp" in r)]
        out = {"Items": items}
        if start + self.page < len(self.rows):
            out["LastEvaluatedKey"] = {"i": start + self.page}
        return out

    def update_item(self, **kwargs):
        self.updates.append(kwargs["Key"])


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MAX_DELETIONS", "5")
    spec = importlib.util.spec_from_file_location(f"media_cleanup_{next(_names)}", MEDIA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def _run(table, delete=lambda media_id: True):
        module.dynamodb = type("D", (), {"Table": lambda self, name: table})()
        module._delete_media_from_meta = delete
        return json.loads(module.handler({}, None)["body"])
    return _run


def row(i, **extra):
    return {"id": f"row-{i}", "fileId": f"row-{i}", "whatsappMediaId": f"m-{i}",
            "uploadedAt": OLD, **extra}


def test_cleaned_rows_do_not_starve_the_run(run):
    cleaned = [row(i, cleanedUp=True) for i in range(20)]
    fresh = [row(100 + i) for i in range(3)]
    table = MediaTable(cleaned + fresh)
    result = run(table)
    assert "attribute_not_exists(cleanedUp)" in table.filters[0]
    assert result == {"deleted": 3, "failed": 0, "skipped": 0}
    assert table.updates == [{"id": f"row-{100 + i}"} for i in range(3)]


def test_update_uses_the_table_key_not_file_id(run):
    table = MediaTable([row(1, fileId="something-else"), {**row(2), "fileId": None}])
    table.rows[1].pop("fileId")
    assert run(table)["deleted"] == 2
    assert table.updates == [{"id": "row-1"}, {"id": "row-2"}]


def test_nothing_processed_raises_an_alert_key(run, caplog):
    def fail(media_id):
        raise RuntimeError("meta down")
    result = run(MediaTable([row(1), row(2)]), delete=fail)
    assert result == {"deleted": 0, "failed": 2, "skipped": 0}
    summary = [json.loads(r.getMessage()) for r in caplog.records
               if "media_cleanup_complete" in r.getMessage()][-1]
    assert summary["alert"] == "MEDIA_CLEANUP_NOTHING_PROCESSED"
    assert (summary["candidates"], summary["deleted"], summary["skipped"]) == (2, 0, 0)


def test_scan_failure_raises_an_alert_key(run, caplog):
    run(MediaTable([], fail=True))
    assert "MEDIA_CLEANUP_NOTHING_PROCESSED" in caplog.text


def test_no_alert_when_work_was_done_or_there_was_none(run, caplog):
    caplog.set_level("INFO")
    run(MediaTable([row(1)]))
    run(MediaTable([row(2, uploadedAt=int(time.time()))]))
    summaries = [json.loads(r.getMessage()) for r in caplog.records
                 if "media_cleanup_complete" in r.getMessage()]
    assert [s.get("alert") for s in summaries] == [None, None]
    assert [s["deleted"] for s in summaries] == [1, 0]
