"""OPS-1: the WhatsApp analytics export is written, and stays, outside what the CDN serves."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from lambda_utils import media_paths

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "amplify/functions/operations/whatsapp-analytics-export/handler.py"
EDGE = ROOT / "amplify/functions/edge/get-miss-redirect/handler.py"
OLD_PREFIX = "secure/d/public/whatsapp/analytics/operational"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def load_export(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    count = iter(range(100))

    def load(prefix=None):
        if prefix is None:
            monkeypatch.delenv("ANALYTICS_PREFIX", raising=False)
        else:
            monkeypatch.setenv("ANALYTICS_PREFIX", prefix)
        return _load(EXPORT, f"analytics_export_{next(count)}")
    return load


EDGE_MODULE = _load(EDGE, "edge_get_miss_redirect_ops1")


def test_default_prefix_is_the_private_media_paths_constant(load_export):
    module = load_export()
    assert module.PREFIX + "/" == media_paths.WHATSAPP_ANALYTICS_EXPORT_PREFIX
    assert media_paths.is_gated(module.PREFIX + "/orders/part.json")
    assert media_paths.public_url(module.PREFIX + "/orders/part.json") == ""


@pytest.mark.parametrize("configured", [
    OLD_PREFIX, "/" + OLD_PREFIX + "/", "o/stream/media/reports", "analytics/operational",
    "secure/d/public/other",
])
def test_cdn_served_override_is_ignored(load_export, configured):
    module = load_export(configured)
    assert module.PREFIX == module.PRIVATE_PREFIX


def test_private_override_is_honoured(load_export):
    module = load_export("secure/d/analytics/whatsapp/staging/")
    assert module.PREFIX == "secure/d/analytics/whatsapp/staging"


def test_export_writes_only_under_the_private_prefix(load_export, caplog):
    module = load_export(OLD_PREFIX)
    paginator = Mock()
    paginator.paginate.return_value = [{"Items": [{"orderId": "o1", "amountPaise": 100}]}]
    module._ddb = Mock(get_paginator=Mock(return_value=paginator))
    module._s3 = Mock()
    result = module.handler({}, Mock(aws_request_id="req-1"))
    keys = [c.kwargs["Key"] for c in module._s3.put_object.call_args_list]
    assert len(keys) == len(module.DATASETS)
    assert all(k.startswith(media_paths.WHATSAPP_ANALYTICS_EXPORT_PREFIX) for k in keys)
    assert all(media_paths.is_gated(k) and EDGE_MODULE._is_denied("/" + k) for k in keys)
    assert result["prefix"] == module.PRIVATE_PREFIX
    assert "analytics_prefix_override_ignored" in caplog.text


@pytest.mark.parametrize("key", [
    OLD_PREFIX + "/orders/snapshot_date=2026-11-28/snapshot_hour=01/part-x.json",
    "secure/d/public/whatsapp/analytics/meta-events/date=2026-11-28/event_type=x/1.json",
])
def test_existing_files_under_the_old_prefix_are_gated(key):
    assert media_paths.is_gated(key)
    assert media_paths.public_url(key) == ""
    assert EDGE_MODULE._is_denied("/" + key)
    # S3 decodes the path once, so an encoded spelling must be refused too.
    assert EDGE_MODULE._is_denied("/" + key.replace("analytics", "analytic%73"))


def test_edge_refuses_and_empties_an_analytics_object():
    key = OLD_PREFIX + "/orders/snapshot_date=2026-11-28/snapshot_hour=01/part-x.json"
    event = {"Records": [{"cf": {
        "request": {"uri": "/" + key},
        "response": {"status": "200", "body": "{\"order_id\":\"o1\"}", "headers": {
            "content-length": [{"key": "Content-Length", "value": "17"}],
            "etag": [{"key": "ETag", "value": "\"abc\""}],
        }},
    }}]}
    response = EDGE_MODULE.handler(event, None)
    assert response["status"] == "302"
    assert response["body"] == ""
    assert "etag" not in response["headers"]


def test_new_private_prefixes_are_refused_and_public_media_still_served():
    assert EDGE_MODULE._is_denied("/" + media_paths.WHATSAPP_ANALYTICS_EXPORT_PREFIX + "x.json")
    assert EDGE_MODULE._is_denied("/" + media_paths.SCRAPED_DOCS_PREFIX + "_sources.json")
    assert not EDGE_MODULE._is_denied("/" + media_paths.WHATSAPP_TEMPLATE_IMAGE_PREFIX + "a.png")


def test_edge_private_list_matches_media_paths():
    assert EDGE_MODULE.PRIVATE_DELIVERABLE_PREFIXES == media_paths.PRIVATE_DELIVERABLE_PREFIXES
    assert media_paths.WHATSAPP_ANALYTICS_PREFIX in media_paths.PRIVATE_DELIVERABLE_PREFIXES
    assert all(EDGE_MODULE._is_denied("/" + p + "x") for p in media_paths.PRIVATE_DELIVERABLE_PREFIXES)


def test_export_result_shape_is_unchanged(load_export):
    module = load_export()
    paginator = Mock()
    paginator.paginate.return_value = [{"Items": []}]
    module._ddb = Mock(get_paginator=Mock(return_value=paginator))
    module._s3 = Mock()
    result = module.handler({}, Mock(aws_request_id="req-2"))
    assert result["ok"] is True and result["privacyBounded"] is True
    assert [d["dataset"] for d in result["datasets"]] == list(module.DATASETS)
    json.dumps(result)
