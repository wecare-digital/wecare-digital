"""
The site-language handler had no test. These cover the two things that cost money.

WHY THESE AND NOT COVERAGE. This function is reachable without a session and it spends on a
metered API per character, so the assertions worth writing are the ones about who may spend:
that /translate refuses a caller which is not one of our pages, and that the two Polly routes
are gone rather than merely unused.

The handler is imported with boto3 clients stubbed. It builds a translate client, a Secrets
Manager client and a DynamoDB resource at module scope, so importing it unprepared either
reaches AWS or raises - neither of which belongs in a unit test.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

HANDLER_DIR = Path(__file__).resolve().parents[1] / "amplify" / "functions" / "core" / "site-language"


@pytest.fixture(scope="module")
def handler_module():
    """Import handler.py with boto3 replaced by a stub that records nothing and calls nothing."""

    class _Stub:
        """Answers any attribute with a callable returning an empty dict."""

        def __getattr__(self, _name):
            return lambda *args, **kwargs: {}

    class _Table(_Stub):
        def get_item(self, **kwargs):
            return {}

        def put_item(self, **kwargs):
            return {}

    class _Resource:
        def Table(self, _name):
            return _Table()

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = lambda *args, **kwargs: _Stub()
    fake_boto3.resource = lambda *args, **kwargs: _Resource()

    saved_boto3 = sys.modules.get("boto3")
    sys.modules["boto3"] = fake_boto3
    sys.path.insert(0, str(HANDLER_DIR))
    try:
        if "handler" in sys.modules:
            del sys.modules["handler"]
        module = importlib.import_module("handler")
        yield module
    finally:
        sys.path.remove(str(HANDLER_DIR))
        if saved_boto3 is not None:
            sys.modules["boto3"] = saved_boto3
        else:
            sys.modules.pop("boto3", None)
        sys.modules.pop("handler", None)


def _event(path, method="POST", origin=None, body=None):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": headers,
        "body": json.dumps(body) if body is not None else None,
    }


class TestTranslateOriginGate:
    """
    /translate spends per character on a public endpoint. Sized against the limits actually
    configured - 15 rps in scripts/deploy_site_language.py, MAX_TOTAL_BYTES of 30,000 - the
    ceiling is 450,000 characters a second, about $9/sec or $32,000/hour at Google's rate.
    The DynamoDB cache does not help: its key is the text, so novel text never hits it.
    """

    def test_refuses_a_caller_with_no_origin_header(self, handler_module):
        # This is the open-proxy case and the one that mattered. curl sends no Origin, so
        # before the gate it was served and billed. CORS could never have stopped it: the
        # Access-Control-Allow-Origin header is an instruction to a browser, and a script is
        # not a browser.
        response = handler_module.handler(
            _event("/site-language/translate", body={"texts": ["hello"], "targetLanguage": "hi"}),
            None,
        )
        assert response["statusCode"] == 403
        assert "origin" in json.loads(response["body"])["error"].lower()

    def test_refuses_a_caller_from_another_site(self, handler_module):
        response = handler_module.handler(
            _event(
                "/site-language/translate",
                origin="https://not-our-site.example",
                body={"texts": ["hello"], "targetLanguage": "hi"},
            ),
            None,
        )
        assert response["statusCode"] == 403

    def test_allows_our_own_origins_through_the_gate(self, handler_module):
        # Past the gate the request reaches the translate path, where the stubbed clients make
        # the outcome uninteresting - so this asserts only that it is NOT the 403. Asserting a
        # 200 would be asserting the stub.
        for origin in sorted(handler_module.ALLOWED_ORIGINS):
            response = handler_module.handler(
                _event(
                    "/site-language/translate",
                    origin=origin,
                    body={"texts": ["hello"], "targetLanguage": "hi"},
                ),
                None,
            )
            assert response["statusCode"] != 403, f"{origin} should be allowed"

    def test_both_configured_origins_are_present(self, handler_module):
        # A gate against an empty allowlist would refuse the real site too, and the failure
        # would look like an outage rather than a misconfiguration.
        #
        # WRITTEN AS A SET SUPERSET, NOT TWO `"https://..." in ...` CHECKS. The readable form
        # tripped CodeQL's "Incomplete URL substring sanitization" rule at high severity, twice,
        # and failed the security gate. It was a false positive - ALLOWED_ORIGINS is a set, so
        # `in` is exact membership and not the substring match the rule warns about - but the
        # rule cannot tell those apart from a URL literal on the left of `in`, and an assertion
        # is not worth arguing with a scanner over. Comparing sets says the same thing and
        # carries no URL literal into an `in` expression. Do not "simplify" this back.
        expected = {"https://wecare.digital", "https://wecare.digital"}
        assert set(handler_module.ALLOWED_ORIGINS).issuperset(expected)


class TestCatalogueStaysOpen:
    def test_languages_needs_no_origin(self, handler_module):
        # The catalogue must stay open: the widget fetches it on every page load before the
        # visitor has asked for anything, and it is a static list that costs nothing per call.
        # Gating it would blank the language control for everyone.
        response = handler_module.handler(_event("/site-language/languages", method="GET"), None)
        assert response["statusCode"] != 403


class TestPollyRoutesAreGone:
    """
    Removed rather than deprecated. They drove Polly, had no consumer once the widget dropped
    read-aloud - Polly has no voice for Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada,
    Malayalam or Punjabi - and stayed unauthenticated and billable at roughly $2,400/hour at
    the configured throttle.
    """

    @pytest.mark.parametrize(
        "path,method",
        [("/site-language/tts", "POST"), ("/site-language/voices", "GET")],
    )
    def test_route_returns_not_found(self, handler_module, path, method):
        response = handler_module.handler(
            _event(path, method=method, origin="https://wecare.digital", body={"text": "x", "language": "hi"}),
            None,
        )
        assert response["statusCode"] == 404

    def test_the_synthesis_code_is_deleted_not_merely_unrouted(self, handler_module):
        # Unreachable code can be re-routed by one line. Asserting the functions are absent is
        # what makes the removal stick.
        for name in ("_handle_tts", "_list_voices", "_pick_voice", "_resolve_locale"):
            assert not hasattr(handler_module, name), f"{name} should have been deleted"
        assert not hasattr(handler_module, "polly_client")

    def test_the_source_no_longer_builds_a_polly_client(self):
        # Belt to the braces above: hasattr would also pass if the client were built lazily
        # inside a function. This reads the file.
        source = (HANDLER_DIR / "handler.py").read_text(encoding="utf-8")
        # Comments explain why Polly went, so match the call rather than the word.
        assert 'boto3.client("polly"' not in source
        assert "synthesize_speech" not in source
