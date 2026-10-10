"""`require_auth` accepts STAFF-pool tokens and nothing else, and never invents a role.

What was measured, on commit f87ea643
-------------------------------------
`lambda_utils.middleware.require_auth` validated a bearer token with
`cognito.get_user(AccessToken=token)`. `GetUser` takes **only a token**: it resolves the
user from whichever pool issued it, so a token minted by the customer pool
`us-east-1_46ULYuukt`, or by any Cognito pool in any AWS account, validated there. The
group lookup that followed was `admin_list_groups_for_user(Username=..., UserPoolId=STAFF)`
wrapped in `except Exception` -> `logger.warning` -> `groups = []`, and the role was then
`'Viewer'` with upgrade-only. So a foreign token reached every `require_auth` route as a
Viewer.

The escalation was worse than Viewer. Because the lookup is keyed on `Username` against
the STAFF pool, a caller who controls any Cognito pool can create a user whose `Username`
equals a real staff username: `get_user` succeeds against *their* pool and
`admin_list_groups_for_user` then returns *the real staff user's* groups. That is why the
issuer pin is the fix and least-privilege defaults are not sufficient on their own.

These tests pin all three refusals separately — wrong pool, lookup failed, no staff group
— because the three have different causes and different log events, and a single
"refused" assertion would pass if two of the three regressed into the one that remained.
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

import pytest

SHARED = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import lambda_utils.middleware as mw  # noqa: E402

#: The customer pool. Deliberately NOT the staff pool; this value is the finding.
CUSTOMER_POOL_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"
#: A pool in somebody else's AWS account. `GetUser` would have validated this too.
FOREIGN_POOL_ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_attacker"


def _token(issuer: str, client: str | None = None) -> str:
    """A JWT-shaped string with a readable payload. Not signed — nothing here verifies it.

    `client` defaults to the pinned staff app client, read at call time so a test that
    overrides `mw.STAFF_APP_CLIENT_ID` still mints a token the gate accepts. Pass it
    explicitly to mint a token from a DIFFERENT app client on the same pool.
    """
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer, "sub": "sub-1234",
                    "client_id": mw.STAFF_APP_CLIENT_ID if client is None else client}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeCognito:
    """Stands in for the Cognito client. No network, no AWS.

    `get_user` succeeds for ANY token on purpose: that is exactly what the real API does
    and is the reason the issuer pin has to exist. A fake that refused a foreign token
    would be testing the fake.
    """

    class exceptions:
        class NotAuthorizedException(Exception):
            pass

    def __init__(self, groups=None, groups_raise=False):
        self._groups = groups if groups is not None else ["Viewer"]
        self._groups_raise = groups_raise
        self.group_lookups = 0
        self.mfa_lookups = 0

    def get_user(self, AccessToken):  # noqa: N803
        return {"Username": "staff-1",
                "UserAttributes": [{"Name": "email", "Value": "staff@example.test"}]}

    def admin_list_groups_for_user(self, Username, UserPoolId):  # noqa: N803
        self.group_lookups += 1
        if self._groups_raise:
            raise RuntimeError("UserNotFoundException")
        return {"Groups": [{"GroupName": g} for g in self._groups]}

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        self.mfa_lookups += 1
        return {"UserMFASettingList": ["SOFTWARE_TOKEN_MFA"],
                "PreferredMfaSetting": "SOFTWARE_TOKEN_MFA"}


def gw_event(token: str, *, method: str = "POST", path: str = "/prod/thing"):
    """An event shaped the way API Gateway delivers one."""
    event = {
        "requestContext": {"apiId": "zllr9lrg7j", "stage": "prod",
                           "domainName": "api.wecare.digital",
                           "http": {"method": method, "path": path,
                                    "sourceIp": "203.0.113.1"}},
        "headers": {"origin": "https://wecare.digital"},
    }
    if token is not None:
        event["headers"]["authorization"] = f"Bearer {token}"
    return event


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ADMIN_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(mw, "AUTH_SKIP_PATHS", [])


@pytest.fixture
def staff_token():
    return _token(mw.staff_pool_issuer())


def _install(monkeypatch, fake):
    monkeypatch.setattr(mw, "cognito", fake)
    return fake


# ==========================================================================
# wrong pool — the finding
# ==========================================================================
def test_a_customer_pool_token_is_refused(monkeypatch):
    """The exact finding: a customer token used to authorise as a staff Viewer."""
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    result = mw.require_auth(gw_event(_token(CUSTOMER_POOL_ISSUER)))
    assert result is not None
    assert result["statusCode"] == 401
    assert fake.group_lookups == 0, "the staff group lookup ran for a foreign token"


def test_a_foreign_pool_token_is_refused(monkeypatch):
    """Any Cognito pool in any AWS account validates against `GetUser`."""
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    result = mw.require_auth(gw_event(_token(FOREIGN_POOL_ISSUER)))
    assert result["statusCode"] == 401
    assert fake.group_lookups == 0


def test_the_username_collision_escalation_is_closed(monkeypatch):
    """A foreign pool whose user is named like a real staff member must gain nothing.

    Without the issuer pin this path returned the REAL staff user's groups, because the
    lookup is keyed on `Username` against the staff pool. Admin via a pool we do not own.
    """
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    event = gw_event(_token(FOREIGN_POOL_ISSUER))
    result = mw.require_auth(event, required_role="Admin")
    assert result["statusCode"] == 401
    assert "_auth" not in event
    assert fake.group_lookups == 0


def test_a_non_jwt_token_is_refused(monkeypatch):
    """The literal kind of value the old fixtures used: no payload, so no issuer."""
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    assert mw.require_auth(gw_event("valid-token"))["statusCode"] == 401


def test_a_token_with_a_corrupt_payload_is_refused(monkeypatch):
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    assert mw.require_auth(gw_event("header.!!!not-base64!!!.sig"))["statusCode"] == 401


def test_a_token_with_no_iss_claim_is_refused(monkeypatch):
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "x"}).encode()).decode().rstrip("=")
    assert mw.require_auth(gw_event(f"header.{payload}.sig"))["statusCode"] == 401


#: A second app client on the SAME staff pool. Shaped like a Cognito client id.
#: No such client exists today — that is the point: the pin is what keeps it that way.
OTHER_STAFF_CLIENT = "9zzzzzz99z9z9zzz9z999zzz9z"


# ==========================================================================
# wrong app client — the issuer pin narrows the pool, not the client within it
# ==========================================================================
def test_a_token_from_another_app_client_on_the_staff_pool_is_refused(monkeypatch):
    """The gap the issuer pin leaves open.

    `iss` names the POOL. Every app client on a pool mints tokens bearing the same `iss`,
    so the issuer pin alone admits any client anyone adds to `us-east-1_cSx0RHCIR` — a
    partner integration, a machine-to-machine client with `ALLOW_USER_PASSWORD_AUTH`, a
    throwaway created for a test. Each would have reached every `require_auth` route with
    whatever groups its user held.
    """
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    event = gw_event(_token(mw.staff_pool_issuer(), client=OTHER_STAFF_CLIENT))
    result = mw.require_auth(event, required_role="Admin")
    assert result is not None
    assert result["statusCode"] == 401
    assert "_auth" not in event
    assert fake.group_lookups == 0, "the staff group lookup ran for an unpinned client"


def test_a_token_naming_no_app_client_is_refused(monkeypatch):
    """Fails CLOSED. A token with neither `client_id` nor `aud` names no client, and the
    staff pool has exactly one client that every real token names."""
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-1234"}).encode()
    ).decode().rstrip("=")
    result = mw.require_auth(gw_event(f"header.{payload}.sig"))
    assert result["statusCode"] == 401
    assert fake.group_lookups == 0


def test_an_id_token_carrying_the_client_in_aud_is_accepted(monkeypatch):
    """Access tokens spell it `client_id`; ID tokens spell it `aud`. Both must pass.

    `require_auth` validates an ACCESS token, so `client_id` is what answers in production.
    Reading `aud` as well means the pin cannot be slipped by sending the other token type,
    and cannot refuse a caller who legitimately sends one.
    """
    _install(monkeypatch, FakeCognito(groups=["Operator"]))
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-1234",
                    "aud": mw.STAFF_APP_CLIENT_ID}).encode()
    ).decode().rstrip("=")
    event = gw_event(f"header.{payload}.sig")
    assert mw.require_auth(event, required_role="Operator") is None
    assert event["_auth"]["role"] == "Operator"


def test_an_aud_list_containing_the_staff_client_is_accepted(monkeypatch):
    """`aud` is permitted to be a list by the JWT spec. A list is not a mismatch."""
    _install(monkeypatch, FakeCognito(groups=["Viewer"]))
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-1234",
                    "aud": ["something-else", mw.STAFF_APP_CLIENT_ID]}).encode()
    ).decode().rstrip("=")
    assert mw.require_auth(gw_event(f"header.{payload}.sig"),
                           required_role="Viewer") is None


def test_an_aud_list_without_the_staff_client_is_refused(monkeypatch):
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-1234",
                    "aud": ["something-else", OTHER_STAFF_CLIENT]}).encode()
    ).decode().rstrip("=")
    assert mw.require_auth(gw_event(f"header.{payload}.sig"))["statusCode"] == 401


def test_the_wrong_pool_refusal_still_wins_over_the_client_refusal(monkeypatch, caplog):
    """A customer-pool token that happens to carry the staff client id is refused as the
    WRONG POOL, not the wrong client. Order matters for diagnosis: the pool is the
    coarser fact and the one that was the live hole."""
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    with caplog.at_level("WARNING"):
        result = mw.require_auth(gw_event(_token(CUSTOMER_POOL_ISSUER)))
    assert result["statusCode"] == 401
    assert "auth_wrong_pool" in caplog.text
    assert "auth_wrong_client" not in caplog.text


def test_the_client_refusal_has_its_own_log_event(monkeypatch, caplog):
    """A fourth refusal cause needs a fourth event name, for the reason the three above do:
    one shared "refused" line would let a regression in any of them pass unnoticed."""
    with caplog.at_level("WARNING"):
        _install(monkeypatch, FakeCognito(groups=["Admin"]))
        mw.require_auth(gw_event(_token(mw.staff_pool_issuer(), client=OTHER_STAFF_CLIENT)))
    assert "auth_wrong_client" in caplog.text
    assert "auth_wrong_pool" not in caplog.text


def test_the_client_pin_is_overridable_for_a_client_rotation(monkeypatch):
    """Rotating the app client must be a one-line change, not a reason to delete the pin.

    The failure mode a pin has to avoid is refusing every token the moment the thing it
    pins legitimately moves — that is what gets pins removed rather than updated.
    """
    monkeypatch.setattr(mw, "STAFF_APP_CLIENT_ID", OTHER_STAFF_CLIENT)
    _install(monkeypatch, FakeCognito(groups=["Viewer"]))
    assert mw.require_auth(gw_event(_token(mw.staff_pool_issuer(), client=OTHER_STAFF_CLIENT)),
                           required_role="Viewer") is None
    assert mw.require_auth(
        gw_event(_token(mw.staff_pool_issuer(), client="1j8kbi48m4v2rped3n224rlevb")),
    )["statusCode"] == 401


def test_the_pinned_client_is_the_one_the_repository_declares(monkeypatch):
    """Anti-drift, and the reason this pin cannot lock out real staff.

    A pin on the WRONG client refuses everyone, which is worse than no pin at all. The
    value is therefore cross-checked against the two committed declarations that decide
    what the browser actually uses — `amplify/auth/resource.ts`'s `userPoolClientId` and
    `shared/config.ts`'s `COGNITO_CONFIG.APP_CLIENT_ID` — plus the independent pin
    `ai/workspace-mcp/handler.py` already carries for the same pool.
    """
    functions = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions"
    auth_resource = (functions.parent / "auth/resource.ts").read_text()
    shared_config = (functions / "shared/config.ts").read_text()
    workspace_mcp = (functions / "ai/workspace-mcp/handler.py").read_text()

    assert f"userPoolClientId: '{mw.STAFF_APP_CLIENT_ID}'" in auth_resource
    assert f"APP_CLIENT_ID: '{mw.STAFF_APP_CLIENT_ID}'" in shared_config
    assert f'STAFF_CLIENT = "{mw.STAFF_APP_CLIENT_ID}"' in workspace_mcp


def test_the_pin_follows_the_configured_pool(monkeypatch):
    """`staff_pool_issuer()` is derived from `USER_POOL_ID`, not a second literal.

    A pin that did not move with the pool would refuse every token the moment the pool
    was overridden, which is the failure mode that makes people delete pins.
    """
    monkeypatch.setattr(mw, "USER_POOL_ID", "us-east-1_other")
    _install(monkeypatch, FakeCognito(groups=["Viewer"]))
    assert mw.staff_pool_issuer().endswith("/us-east-1_other")
    assert mw.require_auth(gw_event(_token(mw.staff_pool_issuer())),
                           required_role="Viewer") is None
    assert mw.require_auth(gw_event(_token(mw.STAFF_POOL_ISSUER)),
                           required_role="Viewer")["statusCode"] == 401


# ==========================================================================
# no default role — the second half of the finding
# ==========================================================================
def test_a_failing_group_lookup_is_refused_not_defaulted(monkeypatch, staff_token):
    """Was: swallow the exception, `groups = []`, role `'Viewer'`. Now: 403.

    The group lookup is the only thing that establishes a role, so an answer we could not
    obtain is not an answer we may substitute a default for.
    """
    _install(monkeypatch, FakeCognito(groups_raise=True))
    event = gw_event(staff_token)
    result = mw.require_auth(event)
    assert result is not None
    assert result["statusCode"] == 403
    assert "_auth" not in event, "a principal with no established role was let through"


def test_an_ungrouped_staff_user_is_refused(monkeypatch, staff_token):
    _install(monkeypatch, FakeCognito(groups=[]))
    event = gw_event(staff_token)
    assert mw.require_auth(event)["statusCode"] == 403
    assert "_auth" not in event


def test_a_partner_only_principal_is_refused(monkeypatch, staff_token):
    """`Partner` is deliberately absent from ROLE_HIERARCHY, so it scores 0.

    Least privilege: a Partner is a tenant-scoped principal, not a staff role, and the
    fix for a Partner-facing staff route is that route authorising the tenant — not
    adding `Partner` to the staff hierarchy.
    """
    _install(monkeypatch, FakeCognito(groups=["Partner"]))
    event = gw_event(staff_token)
    result = mw.require_auth(event)
    assert result["statusCode"] == 403
    assert "_auth" not in event


def test_an_unknown_group_is_refused(monkeypatch, staff_token):
    _install(monkeypatch, FakeCognito(groups=["SomeFutureGroup"]))
    assert mw.require_auth(gw_event(staff_token))["statusCode"] == 403


def test_the_refusal_events_are_separable_in_logs(monkeypatch, staff_token, caplog):
    """Three causes, three event names. One shared "refused" line would hide two of them."""
    with caplog.at_level("WARNING"):
        _install(monkeypatch, FakeCognito(groups=["Admin"]))
        mw.require_auth(gw_event(_token(CUSTOMER_POOL_ISSUER)))
        assert "auth_wrong_pool" in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING"):
        _install(monkeypatch, FakeCognito(groups_raise=True))
        mw.require_auth(gw_event(staff_token))
        assert "auth_group_lookup_failed" in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING"):
        _install(monkeypatch, FakeCognito(groups=["Partner"]))
        mw.require_auth(gw_event(staff_token))
        assert "auth_no_staff_group" in caplog.text


# ==========================================================================
# real staff tokens behave exactly as before
# ==========================================================================
def test_a_viewer_passes_a_viewer_route(monkeypatch, staff_token):
    _install(monkeypatch, FakeCognito(groups=["Viewer"]))
    event = gw_event(staff_token)
    assert mw.require_auth(event, required_role="Viewer") is None
    assert event["_auth"]["role"] == "Viewer"
    assert event["_auth"]["groups"] == ["Viewer"]
    assert event["_auth"]["email"] == "staff@example.test"


def test_an_operator_passes_an_operator_route(monkeypatch, staff_token):
    _install(monkeypatch, FakeCognito(groups=["Operator"]))
    event = gw_event(staff_token)
    assert mw.require_auth(event, required_role="Operator") is None
    assert event["_auth"]["role"] == "Operator"


def test_an_operator_on_an_admin_route_gets_the_unchanged_403_body(monkeypatch, staff_token):
    """The body shape callers already parse. This PR must not change it."""
    _install(monkeypatch, FakeCognito(groups=["Operator"]))
    result = mw.require_auth(gw_event(staff_token), required_role="Admin")
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"] == "Insufficient permissions"
    assert body["requiredRole"] == "Admin"
    assert body["currentRole"] == "Operator"


def test_an_admin_passes_and_the_mfa_block_still_runs(monkeypatch, staff_token):
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    event = gw_event(staff_token)
    assert mw.require_auth(event, required_role="Admin") is None
    assert event["_auth"]["role"] == "Admin"
    assert event["_auth"]["mfaEnrolled"] is True
    assert fake.mfa_lookups == 1


def test_the_highest_group_still_wins(monkeypatch, staff_token):
    _install(monkeypatch, FakeCognito(groups=["Viewer", "Admin", "Operator"]))
    event = gw_event(staff_token)
    assert mw.require_auth(event, required_role="Operator") is None
    assert event["_auth"]["role"] == "Admin"


def test_partner_alongside_a_staff_group_keeps_the_staff_role(monkeypatch, staff_token):
    """Refusing a Partner must not refuse an Operator who also happens to be a Partner."""
    _install(monkeypatch, FakeCognito(groups=["Partner", "Operator"]))
    event = gw_event(staff_token)
    assert mw.require_auth(event, required_role="Operator") is None
    assert event["_auth"]["role"] == "Operator"


# ==========================================================================
# the bypasses that must survive
# ==========================================================================
def test_an_internal_invoke_still_returns_none(monkeypatch):
    """No API Gateway context = Lambda-to-Lambda. Breaking this breaks every internal call."""
    fake = _install(monkeypatch, FakeCognito(groups=[]))
    assert mw.require_auth({"action": "process", "payload": {}}) is None
    assert mw.require_auth({"internalAction": "x"}, required_role="Admin") is None
    assert fake.group_lookups == 0


def test_an_internal_invoke_with_a_routing_http_block_still_returns_none(monkeypatch):
    """Internal callers build a minimal `requestContext.http` for routing and no apiId."""
    _install(monkeypatch, FakeCognito(groups=[]))
    event = {"requestContext": {"http": {"method": "POST", "path": "/wix-store/orders"}},
             "rawPath": "/wix-store/orders", "headers": {}}
    assert mw.require_auth(event, required_role="Admin") is None


def test_options_still_skips(monkeypatch):
    fake = _install(monkeypatch, FakeCognito(groups=[]))
    assert mw.require_auth(gw_event(None, method="OPTIONS")) is None
    assert fake.group_lookups == 0


def test_a_missing_token_is_still_401(monkeypatch):
    _install(monkeypatch, FakeCognito(groups=["Admin"]))
    assert mw.require_auth(gw_event(None))["statusCode"] == 401


def test_an_expired_token_is_still_401(monkeypatch, staff_token):
    fake = FakeCognito(groups=["Admin"])

    def expired(AccessToken):  # noqa: N803
        raise FakeCognito.exceptions.NotAuthorizedException("Access Token has expired")

    fake.get_user = expired
    _install(monkeypatch, fake)
    assert mw.require_auth(gw_event(staff_token))["statusCode"] == 401


def test_an_exempt_path_still_skips_and_a_prefix_sibling_does_not(monkeypatch):
    """Keeps `tests/test_auth_skip_paths.py`'s guarantee: segments, never substrings."""
    monkeypatch.setattr(mw, "AUTH_SKIP_PATHS", ["/wa-business/flow-data"])
    fake = _install(monkeypatch, FakeCognito(groups=["Admin"]))

    assert mw.require_auth(gw_event(None, path="/prod/wa-business/flow-data")) is None
    assert mw.require_auth(gw_event(None, path="/prod/wa-business/flow-data/sub")) is None
    assert fake.group_lookups == 0

    refused = mw.require_auth(gw_event(None, path="/prod/wa-business/flow-dataX"))
    assert refused is not None and refused["statusCode"] == 401
