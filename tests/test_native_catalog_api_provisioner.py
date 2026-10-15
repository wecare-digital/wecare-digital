"""The catalog admin provisioner must see every route and integration on the shared API.

API Gateway v2 `get_routes` / `get_integrations` return one page and a `NextToken`. The shared
HTTP API carries hundreds of routes, so a first-page-only read missed the catalog routes that
already existed and the redeploy failed on `create_route` with ConflictException.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "provision_native_catalog_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("provision_native_catalog_api_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Paged:
    """A list call that answers in pages of two, the way the real API answers in pages."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        start = int(kwargs.get("NextToken") or 0)
        page = {"Items": self.items[start:start + 2]}
        if start + 2 < len(self.items):
            page["NextToken"] = str(start + 2)
        return page


def test_all_items_follows_every_next_token():
    provisioner = _load()
    routes = [{"RouteKey": f"GET /r{i}"} for i in range(5)]
    call = _Paged(routes)
    assert provisioner.all_items(call, ApiId="api") == routes
    assert [c.get("NextToken") for c in call.calls] == [None, "2", "4"]
    assert all(c["ApiId"] == "api" for c in call.calls)


def test_no_route_or_integration_read_is_first_page_only():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "apigw.get_routes(" not in source
    assert "apigw.get_integrations(" not in source
    assert source.count("all_items(apigw.get_routes") == 2
    assert source.count("all_items(apigw.get_integrations") == 2
