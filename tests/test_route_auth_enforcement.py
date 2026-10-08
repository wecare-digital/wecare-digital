"""Every non-allowlisted HTTP route must authenticate its caller.

Provenance
----------
The route audit reported "0 findings" for a long time because its marker set
accepted `Authorization`, `api_key`, `verify_token` and `appsecret_proof` as
evidence of authentication. On 2026-09-21 each of those was traced in the seven
handlers below and every single match was either

    "Access-Control-Allow-Headers: Content-Type,Authorization"

or an OUTBOUND credential being sent to a provider. None of them checked the
caller. `require_auth` appeared zero times across all seven.

That left 30 routes anonymously reachable, including:

    POST   /media/cleanup              deletes media from Meta
    DELETE /voice-in/obd/clear-logs    wipes campaign logs
    DELETE /voice-in/c2c/clear-logs    wipes call history
    POST   /voice-in/obd/upload-csv    uploads a recipient list
    POST   /ai/generate                spends model tokens, on BOTH HTTP APIs
    POST   /links                      mints short links on a wecare.digital host
    POST   /store/generate-product-image  spends on image generation

These tests pin the guard at each entry point. They are structural on purpose:
the failure mode is a future edit that moves or drops the check, which a
behavioural test on a 5,661-line handler would not reliably catch.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
FUNCTIONS = ROOT / "amplify" / "functions"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

# handler path -> the side-effecting marker the guard must precede
GUARDED = {
    "core/url-shortener": "create_link(",
    "messaging/voice-in/c2c": "json.loads(event.get('body'",
    # Was `_is_cdr_callback(body)` until 2026-09-25. That branch was the Airtel CDR
    # write path and has been removed, so the marker had to move to a side effect
    # that still exists. `_text_to_audio` is a good one: it synthesises speech, which
    # costs money, so an anonymous caller reaching it would be a real finding.
    "messaging/voice-in/obd": "_text_to_audio(body, request_id)",
    "ecommerce/product-image-gen": "_generate_and_upload(",
    "messaging/media-cleanup": "cutoff =",
    "operations/bulk-worker": "'status': 'bulk-worker-active'",
    "ai/ai-generate-response": "auth_failure",
}


def _src(rel: str) -> str:
    return (FUNCTIONS / rel / "handler.py").read_text()


@pytest.mark.parametrize("rel", sorted(GUARDED))
class TestGuardPresent:
    def test_imports_require_auth(self, rel):
        # url-shortener imports it lazily inside the management branch so the
        # anonymous redirect path does not load the middleware; the import is
        # indented rather than at module scope.
        assert "from lambda_utils.middleware import require_auth" in _src(rel), rel

    def test_calls_require_auth(self, rel):
        assert "require_auth(event)" in _src(rel), rel

    def test_returns_the_failure_rather_than_ignoring_it(self, rel):
        src = _src(rel)
        i = src.index("require_auth(event)")
        window = src[i:i + 260]
        assert "is not None" in window, rel
        assert "return" in window, rel

    def test_guard_precedes_the_side_effect(self, rel):
        src = _src(rel)
        marker = GUARDED[rel]
        if marker == "auth_failure":
            return  # guard is the first statement after OPTIONS; nothing to order
        assert marker in src, f"{rel}: marker {marker!r} moved, revisit this test"
        assert src.index("require_auth(event)") < src.index(marker), rel


class TestUrlShortenerKeepsRedirectsPublic:
    """One Lambda, two audiences: anonymous redirects, authenticated management."""

    @pytest.fixture
    def mod(self):
        path = str(FUNCTIONS / "core" / "url-shortener")
        if path not in sys.path:
            sys.path.insert(0, path)
        for name in list(sys.modules):
            if name == "handler":
                del sys.modules[name]
        with patch("boto3.resource") as res, patch("boto3.client") as cli:
            res.return_value = MagicMock()
            cli.return_value = MagicMock()
            import handler as m  # noqa: PLC0415
            yield m
        sys.path.remove(path)

    def _event(self, method, path):
        return {
            "httpMethod": method,
            "rawPath": path,
            "path": path,
            "requestContext": {"http": {"method": method, "path": path,
                                        "sourceIp": "203.0.113.9"},
                               "apiId": "zllr9lrg7j", "stage": "prod"},
            "headers": {},
        }

    # The handler imports require_auth lazily inside the management branch, so the
    # patch target is the middleware module rather than a handler attribute. That
    # is also what proves the redirect path never reaches the import at all.
    TARGET = "lambda_utils.middleware.require_auth"

    def test_redirect_does_not_require_auth(self, mod):
        with patch.object(mod, "redirect", return_value={"statusCode": 302}) as r, \
             patch(self.TARGET) as auth:
            resp = mod.handler(self._event("GET", "/r/abc123"), None)
        assert resp["statusCode"] == 302
        r.assert_called_once()
        auth.assert_not_called()

    def test_catch_all_redirect_does_not_require_auth(self, mod):
        with patch.object(mod, "redirect", return_value={"statusCode": 302}), \
             patch(self.TARGET) as auth:
            mod.handler(self._event("GET", "/abc123"), None)
        auth.assert_not_called()

    def test_link_creation_requires_auth(self, mod):
        denied = {"statusCode": 401, "body": "{}"}
        with patch.object(mod, "create_link") as create, \
             patch(self.TARGET, return_value=denied) as auth:
            resp = mod.handler(self._event("POST", "/links"), None)
        assert resp["statusCode"] == 401
        auth.assert_called_once()
        create.assert_not_called()

    def test_link_deletion_requires_auth(self, mod):
        denied = {"statusCode": 401, "body": "{}"}
        with patch.object(mod, "delete_link") as delete, \
             patch(self.TARGET, return_value=denied):
            resp = mod.handler(self._event("DELETE", "/links/abc123"), None)
        assert resp["statusCode"] == 401
        delete.assert_not_called()

    def test_link_listing_proceeds_once_authenticated(self, mod):
        with patch.object(mod, "list_links", return_value={"statusCode": 200}) as ls, \
             patch(self.TARGET, return_value=None):
            resp = mod.handler(self._event("GET", "/links"), None)
        assert resp["statusCode"] == 200
        ls.assert_called_once()


class TestAuditMarkerPolicy:
    """The audit tool must not re-accept a marker that proves nothing."""

    @pytest.fixture(scope="class")
    def audit(self):
        path = str(ROOT / "scripts")
        if path not in sys.path:
            sys.path.insert(0, path)
        import audit_route_auth as m  # noqa: PLC0415
        return m

    def test_weak_markers_are_not_in_the_default_set(self, audit):
        for weak in ("Authorization", "api_key", "API_KEY", "verify_token",
                     "VERIFY_TOKEN", "appsecret_proof"):
            assert weak not in audit.MARKERS, weak

    def test_default_set_is_exactly_the_strong_set(self, audit):
        assert audit.MARKERS == audit.STRONG_MARKERS

    def test_shared_verifier_calls_count_as_strong(self, audit):
        """rcs-dlr and inbound-whatsapp delegate to lambda_utils verifiers."""
        assert "sinch_signature.verify" in audit.STRONG_MARKERS
        assert "meta_signature.verify" in audit.STRONG_MARKERS

    def test_every_public_route_states_a_reason(self, audit):
        assert audit.EXPECTED_PUBLIC_ROUTES
        for route, reason in audit.EXPECTED_PUBLIC_ROUTES.items():
            assert reason and len(reason) > 20, route

    @pytest.mark.parametrize('source', ['identity, denied = customer_auth.require_customer(event)', 'identity = customer_auth.authenticate(event)'])
    def test_customer_auth_calls_are_recognized_without_public_exemption(self, audit, source):
        routes = [{'RouteKey': 'POST /ecommerce/checkout', 'Target': 'integrations/fixture', 'AuthorizationType': 'NONE'}]
        integrations = {'fixture': 'arn:aws:lambda:us-east-1:775261844268:function:wecare-checkout:live'}
        result = audit.classify(routes, integrations, {'wecare-checkout': source}, {'wecare-checkout'}, audit.MARKERS)
        assert result[1] == [('POST /ecommerce/checkout', 'wecare-checkout')]
        assert result[2] == [] and result[5] == []

    def test_customer_auth_import_alone_does_not_pass(self, audit):
        routes = [{'RouteKey': 'POST /ecommerce/checkout', 'Target': 'integrations/fixture', 'AuthorizationType': 'NONE'}]
        integrations = {'fixture': 'arn:aws:lambda:us-east-1:775261844268:function:wecare-checkout:live'}
        result = audit.classify(routes, integrations, {'wecare-checkout': 'from lambda_utils import customer_auth'}, {'wecare-checkout'}, audit.MARKERS)
        assert result[2] == [('POST /ecommerce/checkout', 'wecare-checkout')]

    def test_allowlist_holds_only_routes_that_cannot_authenticate(self, audit):
        """A route lands here because auth is impossible or circular, not awkward.

        This set is deliberately a LITERAL and deliberately duplicates
        ``audit_route_auth.EXPECTED_PUBLIC_ROUTES``. The duplication IS the
        control: "auth is impossible or circular" cannot be derived from source,
        so the only enforcement available is that exempting a route from
        authentication takes two edits in two files rather than one. Do not
        "fix" this by computing the right-hand side from the audit module - that
        makes the assertion vacuous and removes the one gate standing between a
        new HTTP route and a permanently unauthenticated production endpoint.

        Adding a line here is the second key. Turning it. Justify it.
        """
        assert set(audit.EXPECTED_PUBLIC_ROUTES) == {
            "GET /r/{code}",
            "POST /auth/validate",
            # Public email-ownership OTP door. It returns only a short-lived proof bound to the
            # normalized email; it performs no customer/contact mutation by itself.
            "POST /auth/email-verification",
            # Public by design, but unlike the generic /contacts API it can write only after
            # both server-side OTP proofs succeed. The paired allowlist edit is intentional.
            "POST /blog/subscribe",
            # Anonymous public-product read. There is no customer identity to authenticate;
            # the handler admits only WECARE HTTPS origins, India coordinates and a fixed
            # Weather/Air operation set, and API Gateway imposes a separate spend throttle.
            "POST /vayulok/environment",
            "GET /webhook/sinch-rcs",
            "POST /webhook/sinch-rcs",
            # The provider's browser callback has no AWS/staff identity. It is
            # bound to an authenticated initiating principal by ten-minute
            # one-use state and PKCE, tested for expiry, replay and supersession
            # in test_workspace_mcp.py. No administrative tool is reachable.
            "GET /workspace/mcp/oauth/callback",
            # An MCP client has no Cognito session and the protocol defines no
            # place to carry one, so require_auth would make the endpoint
            # unusable for its only purpose. Admitted because the capability to
            # do harm is ABSENT rather than unpermitted: the handler imports no
            # boto3 (asserted by test_mcp_server.py::
            # test_the_handler_imports_no_aws_client) and its advertised tool
            # list is compared for exact equality against a frozen read-only
            # allowlist, so a tool that mutates or costs money per call fails
            # the suite on the addition. If that ever changes, this line and the
            # one in audit_route_auth.py both come out and /mcp moves behind
            # require_auth. See docs/ai-discovery-surface.md.
            "ANY /mcp",
            # Anonymous public price read. There is no customer identity to authenticate on a
            # public service page -- the live price is what decides whether a visitor signs in
            # at all -- and the arm accepts no path parameter, no query string and no body, so
            # nothing a caller supplies reaches Wix or a table. It returns only Wix-live prices
            # in integer paise, cannot mutate anything, and is edge-cached for 60 seconds. The
            # exemption is on the METHOD as well as the path: POST /ecommerce/* still requires a
            # customer session, and tests/test_service_prices_route.py pins both halves.
            "GET /ecommerce/service-prices",
        }
