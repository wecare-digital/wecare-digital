"""OPS-2: docs-scraper fetches only allowlisted https hosts that resolve to public addresses,
runs Chromium without AWS credentials, and writes outside what the CDN serves."""
import importlib.util
import itertools
import json
import socket
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from lambda_utils import media_paths

SCRAPER = (Path(__file__).resolve().parents[2]
           / "amplify/functions/operations/docs-scraper/handler.py")
DOCS = "https://developers.facebook.com/documentation/business-messaging/"
PUBLIC_IP = "157.240.22.19"
_names = itertools.count()


@pytest.fixture
def load(monkeypatch):
    def _load(**env):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        for key in ("DOCS_PREFIX", "DOCS_ALLOWED_HOSTS"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        spec = importlib.util.spec_from_file_location(f"docs_scraper_{next(_names)}", SCRAPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return _load


@pytest.fixture
def dns(monkeypatch):
    table = {"developers.facebook.com": [PUBLIC_IP]}

    def getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, port)) for ip in table[host]]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return table


@pytest.mark.parametrize("url,reason", [
    ("http://developers.facebook.com/documentation/", "https"),
    ("file:///proc/self/environ", "https"),
    ("javascript:alert(1)", "https"),
    ("https://evil.example/documentation/", "allowlist"),
    ("https://169.254.169.254/latest/meta-data/", "allowlist"),
    ("https://127.0.0.1/", "allowlist"),
    ("https://developers.facebook.com.evil.example/", "allowlist"),
    ("https://user:pw@developers.facebook.com/", "credentials"),
    ("https://developers.facebook.com:8443/", "ports"),
    ("https://developers.facebook.com:99999/", "invalid"),
])
def test_url_policy_refuses(load, dns, url, reason):
    module = load()
    assert reason in module._url_problem(url)


def test_url_policy_allows_allowlisted_public_https(load, dns):
    module = load()
    assert module._url_problem(DOCS + "overview") == ""
    assert module._url_problem("https://Developers.Facebook.com./documentation/") == ""


@pytest.mark.parametrize("addresses", [
    ["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], ["100.64.0.1"], ["0.0.0.0"],
    ["224.0.0.1"], ["::1"], ["fd00:ec2::254"], ["fe80::1"], ["::ffff:127.0.0.1"],
    [PUBLIC_IP, "10.0.0.5"],
])
def test_private_resolution_is_refused(load, dns, addresses):
    dns["developers.facebook.com"] = addresses
    module = load()
    assert "public addresses" in module._url_problem(DOCS)


def test_unresolvable_host_is_refused(load, dns):
    module = load(DOCS_ALLOWED_HOSTS="docs.example.com")
    assert "public addresses" in module._url_problem("https://docs.example.com/")
    assert "allowlist" in module._url_problem(DOCS)


def test_add_source_checks_before_writing(load, dns, monkeypatch):
    module = load()
    module.s3 = Mock()
    monkeypatch.setattr(module, "_s3_get_json", lambda key, default: default)
    for body in ({"name": "a", "rootUrl": "file:///proc/self/environ"},
                 {"name": "a", "rootUrl": "http://developers.facebook.com/x"},
                 {"name": "a", "rootUrl": DOCS, "pathPrefix": "https://evil.example/"}):
        response = module._add_source(body)
        assert response["statusCode"] == 400
    module.s3.put_object.assert_not_called()
    assert module._add_source({"name": "meta", "rootUrl": DOCS + "overview"})["statusCode"] == 200
    key = module.s3.put_object.call_args.kwargs["Key"]
    assert key == module.SOURCES_KEY and media_paths.is_gated(key)


def test_api_add_source_refuses_internal_url(load, dns, monkeypatch):
    module = load()
    monkeypatch.setattr(module, "require_auth", lambda event, required_role=None: None)
    monkeypatch.setattr(module, "_s3_get_json", lambda key, default: default)
    module.s3 = Mock()
    event = {"routeKey": "POST /docs/sources", "requestContext": {"http": {"method": "POST"}},
             "body": json.dumps({"name": "x", "rootUrl": "https://169.254.169.254/"})}
    assert module.lambda_handler(event, None)["statusCode"] == 400
    module.s3.put_object.assert_not_called()


class FakeRoute:
    def __init__(self, url, status=200, fetch_error=False):
        self.request = types.SimpleNamespace(url=url)
        self.response = types.SimpleNamespace(status=status)
        self.fetch_error = fetch_error
        self.calls = []

    def abort(self, error_code="failed"):
        self.calls.append(("abort", error_code))

    def fetch(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        if self.fetch_error:
            raise RuntimeError("network")
        return self.response

    def fulfill(self, **kwargs):
        self.calls.append(("fulfill", kwargs))


def test_route_guard_blocks_without_fetching(load, dns):
    module = load()
    for url in ("http://developers.facebook.com/a.js", "https://evil.example/a.js",
                "https://169.254.169.254/latest/", "file:///etc/passwd"):
        route = FakeRoute(url)
        module._guard_route(route)
        assert route.calls == [("abort", "blockedbyclient")]


def test_route_guard_fetches_without_redirects_and_refuses_3xx(load, dns):
    module = load()
    ok = FakeRoute(DOCS + "app.js")
    module._guard_route(ok)
    assert ok.calls == [("fetch", {"max_redirects": 0}), ("fulfill", {"response": ok.response})]
    for status in (301, 302, 307, 308):
        moved = FakeRoute(DOCS, status=status)
        module._guard_route(moved)
        assert moved.calls[-1] == ("abort", "blockedbyclient")
        assert not any(call[0] == "fulfill" for call in moved.calls)
    failed = FakeRoute(DOCS, fetch_error=True)
    module._guard_route(failed)
    assert failed.calls[-1] == ("abort", "failed")


def test_browser_env_carries_no_credentials(load, monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_LAMBDA_RUNTIME_API", "_AWS_XRAY_DAEMON_ADDRESS"):
        monkeypatch.setenv(key, "secret-value")
    monkeypatch.setenv("PATH", "/usr/bin")
    module = load()
    env = module._browser_env()
    assert env["HOME"] == "/tmp" and env["PATH"] == "/usr/bin"
    assert "secret-value" not in env.values()
    assert not any("AWS" in key for key in env)


@pytest.mark.parametrize("configured", ["", "o/stream/media/docs/", "secure/d/public/docs/"])
def test_output_prefix_is_private(load, configured):
    module = load(DOCS_PREFIX=configured) if configured else load()
    assert module.PREFIX + "/" == media_paths.SCRAPED_DOCS_PREFIX
    for key in (module.SOURCES_KEY, module.INDEX_KEY, module.CHANGELOG_KEY):
        assert media_paths.is_gated(key)


def test_private_prefix_override_is_honoured(load):
    assert load(DOCS_PREFIX="secure/d/docs-scraper-staging/").PREFIX == "secure/d/docs-scraper-staging"


class FakeBrowserStack:
    """Records what _scrape_source asks of Playwright."""

    def __init__(self, html_by_url=None, goto_error=None):
        self.html_by_url = html_by_url or {}
        self.goto_error = goto_error
        self.launch_kwargs = None
        self.context_kwargs = None
        self.routes = []
        self.visited = []
        self.closed = False
        stack = self

        class Page:
            current = None

            def route(self, pattern, handler):
                stack.routes.append((pattern, handler))

            def goto(self, url, **kwargs):
                if stack.goto_error:
                    raise stack.goto_error
                stack.visited.append(url)
                Page.current = url

            def content(self):
                return stack.html_by_url.get(Page.current, "")

        class Context:
            def new_page(self):
                return Page()

        class Browser:
            def new_context(self, **kwargs):
                stack.context_kwargs = kwargs
                return Context()

            def close(self):
                stack.closed = True

        class Chromium:
            def launch(self, **kwargs):
                stack.launch_kwargs = kwargs
                return Browser()

        class Manager:
            def __enter__(self):
                return types.SimpleNamespace(chromium=Chromium())

            def __exit__(self, *exc):
                return False

        self.manager = Manager

    def install(self, monkeypatch):
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = self.manager
        monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
        monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _prepare(module, monkeypatch, links):
    module.s3 = Mock()
    monkeypatch.setattr(module, "_discover_links", lambda html, base, prefix: links)
    monkeypatch.setattr(module, "_clean_html", lambda html, selector: html)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-value")


def test_scrape_runs_a_guarded_browser_and_skips_disallowed_links(load, dns, monkeypatch):
    module = load()
    page_a, outside = DOCS + "a", "https://evil.example/documentation/b"
    stack = FakeBrowserStack({DOCS: "root text", page_a: "page a text"})
    stack.install(monkeypatch)
    _prepare(module, monkeypatch, [page_a, outside])
    changes = module._scrape_source({"name": "meta", "rootUrl": DOCS, "pathPrefix": DOCS}, {})
    assert stack.routes == [("**/*", module._guard_route)]
    assert stack.context_kwargs == {"service_workers": "block"}
    assert "secret-value" not in stack.launch_kwargs["env"].values()
    assert stack.visited == [DOCS, page_a]
    blocked = [c for c in changes if c["url"] == outside]
    assert blocked and blocked[0]["type"] == "error" and "blocked" in blocked[0]["error"]
    keys = [c.kwargs["Key"] for c in module.s3.put_object.call_args_list]
    assert len(keys) == 2 and all(media_paths.is_gated(k) for k in keys)


@pytest.mark.parametrize("source", [
    {"name": "x", "rootUrl": "https://169.254.169.254/latest/meta-data/"},
    {"name": "x", "rootUrl": "file:///proc/self/environ"},
    {"name": "x", "rootUrl": DOCS, "pathPrefix": "https://evil.example/"},
])
def test_stored_bad_source_never_launches_the_browser(load, dns, monkeypatch, source):
    module = load()
    stack = FakeBrowserStack()
    stack.install(monkeypatch)
    _prepare(module, monkeypatch, [])
    changes = module._scrape_source(source, {})
    assert stack.launch_kwargs is None
    assert changes[0]["type"] == "error" and changes[0]["error"].startswith("blocked:")


def test_root_failure_is_recorded_not_raised(load, dns, monkeypatch):
    module = load()
    stack = FakeBrowserStack(goto_error=RuntimeError("net::ERR_BLOCKED_BY_CLIENT"))
    stack.install(monkeypatch)
    _prepare(module, monkeypatch, [])
    changes = module._scrape_source({"name": "x", "rootUrl": DOCS}, {})
    assert changes[0]["type"] == "error" and "ERR_BLOCKED_BY_CLIENT" in changes[0]["error"]
    assert stack.closed
    module.s3.put_object.assert_not_called()
