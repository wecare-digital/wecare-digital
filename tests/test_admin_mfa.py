"""Admin role requires enrolled MFA. Warn first, enforce behind a flag.

Measured on pool `us-east-1_cSx0RHCIR` (WECARE.DIGITAL) on 2026-09-23, before any
change:

    MfaConfiguration            OFF
    SoftwareTokenMfaConfig      not enabled
    SmsMfaConfiguration         present but unused
    users                       1
    that user's MFA             ["SMS_MFA", "EMAIL_OTP"], preferred EMAIL_OTP
    groups                      Admin / Operator / Viewer / Partner
    members of each group       0 / 0 / 0 / 0

Two findings there, both worth stating plainly.

**The user's MFA was enrolled but inert.** With the pool at `OFF`, Cognito does not
issue an MFA challenge even to a user who has factors registered. So MFA looked
configured and did nothing. Setting the pool to `OPTIONAL` activated the existing
enrolment - which is why `OPTIONAL` was the right step and `ON` was not: `ON` forces
every user through setup, and with one account and an unexercised setup flow the only
thing it could achieve is locking out the sole operator.

**Nobody is in any group.** `ROLE_HIERARCHY` defaults an ungrouped user to `Viewer`,
and 16 live handlers gate on `required_role='Admin'`. So every admin-gated operation
currently refuses the only account. That is fail-closed rather than exploitable, but it
means those features are unusable, and granting the role is an owner decision because
it widens privilege.

What this module adds
---------------------
An Admin must have MFA enrolled. Checked at the point the Admin role is *used*, not at
sign-in, because that is where the privilege is actually exercised.

Honest about its limit: this checks ENROLMENT, not whether MFA was used in this
session. `require_auth` validates an access token via `get_user`, and a Cognito access
token carries no reliable `amr` claim - so "did this session use MFA" is not answerable
here. Enrolment plus pool `OPTIONAL` means Cognito will have challenged them; claiming
more than that would be the kind of overstated control this codebase has been removing.

Staged: warn by default, enforce when `ADMIN_MFA_REQUIRED` is set. Enforcing on day one
would lock out an Admin who has not yet enrolled, and the first person to hit that would
turn the check off rather than enrol.
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


class FakeCognito:
    """Stands in for the Cognito client. No network, no AWS."""

    class exceptions:
        class NotAuthorizedException(Exception):
            pass

    def __init__(self, groups=None, mfa=None, preferred=None):
        self._groups = groups or []
        self._mfa = mfa or []
        self._preferred = preferred
        self.mfa_lookups = 0

    def get_user(self, AccessToken):  # noqa: N803
        return {"Username": "u-1",
                "UserAttributes": [{"Name": "email", "Value": "a@b.test"}]}

    def admin_list_groups_for_user(self, Username, UserPoolId):  # noqa: N803
        return {"Groups": [{"GroupName": g} for g in self._groups]}

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        self.mfa_lookups += 1
        return {"UserMFASettingList": list(self._mfa),
                "PreferredMfaSetting": self._preferred}


def _staff_token() -> str:
    """A JWT-shaped token carrying the STAFF pool issuer. Not signed; nothing verifies it.

    The bearer here used to be the opaque string `token-value-not-a-real-token`.
    `require_auth` now pins the issuer, and a token with no readable payload carries no
    `iss`, so this fixture mints the shape production sends. Read through
    `mw.staff_pool_issuer()` so it follows the `USER_POOL_ID` the `clean_env` fixture
    installs. No assertion in this module changed.
    """
    payload = base64.urlsafe_b64encode(
        # `client_id` because `require_auth` pins the staff app client as well as the pool.
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-1234",
                    "client_id": mw.STAFF_APP_CLIENT_ID}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def gw_event():
    """An event shaped the way API Gateway delivers one."""
    return {
        "requestContext": {"apiId": "zllr9lrg7j", "stage": "prod",
                           "domainName": "api.wecare.digital",
                           "http": {"method": "POST", "path": "/prod/admin/thing",
                                    "sourceIp": "1.2.3.4"}},
        "headers": {"authorization": f"Bearer {_staff_token()}"},
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ADMIN_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(mw, "USER_POOL_ID", "us-east-1_test")


def _run(monkeypatch, *, groups, mfa, preferred=None, required_role="Admin",
         enforce=False):
    fake = FakeCognito(groups=groups, mfa=mfa, preferred=preferred)
    monkeypatch.setattr(mw, "cognito", fake)
    if enforce:
        monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    event = gw_event()
    result = mw.require_auth(event, required_role=required_role)
    return result, event, fake


# ==========================================================================
# the control
# ==========================================================================
def test_an_admin_with_mfa_is_allowed(monkeypatch):
    result, event, _ = _run(monkeypatch, groups=["Admin"], mfa=["SOFTWARE_TOKEN_MFA"],
                            preferred="SOFTWARE_TOKEN_MFA", enforce=True)
    assert result is None
    assert event["_auth"]["role"] == "Admin"
    assert event["_auth"]["mfaEnrolled"] is True


def test_an_admin_without_mfa_is_refused_when_enforcing(monkeypatch):
    result, _, _ = _run(monkeypatch, groups=["Admin"], mfa=[], enforce=True)
    assert result is not None
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"] == "MFA required"
    # Must say what to DO, not only that it failed.
    assert "enrol" in body["detail"].lower() or "enroll" in body["detail"].lower()


def test_an_admin_without_mfa_is_allowed_but_flagged_when_not_enforcing(monkeypatch):
    """Default posture. Enforcing on day one would lock out an Admin who has not
    enrolled, and the first person to hit that turns the check off rather than
    enrolling."""
    result, event, _ = _run(monkeypatch, groups=["Admin"], mfa=[], enforce=False)
    assert result is None
    assert event["_auth"]["mfaEnrolled"] is False
    assert event["_auth"]["mfaRequired"] is False


def test_the_warning_is_logged_so_it_is_findable(monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        _run(monkeypatch, groups=["Admin"], mfa=[], enforce=False)
    assert "admin_without_mfa" in caplog.text
    assert "ADMIN_MFA_MISSING" in caplog.text


@pytest.mark.parametrize("factor", ["SOFTWARE_TOKEN_MFA", "SMS_MFA", "EMAIL_OTP"])
def test_any_enrolled_factor_counts(monkeypatch, factor):
    """The live account's sole user has SMS_MFA and EMAIL_OTP, not TOTP. Requiring TOTP
    specifically would refuse the one person who actually has MFA."""
    result, event, _ = _run(monkeypatch, groups=["Admin"], mfa=[factor],
                            preferred=factor, enforce=True)
    assert result is None
    assert event["_auth"]["mfaEnrolled"] is True


# ==========================================================================
# scope: only the Admin role, and only when it is being used
# ==========================================================================
def test_a_viewer_is_not_asked_for_mfa(monkeypatch):
    # `groups=["Viewer"]` rather than `groups=[]`: `require_auth` no longer defaults an
    # ungrouped principal to Viewer, it refuses them. A Viewer is what this test is about,
    # so the fixture now says so. Assertions unchanged.
    result, event, fake = _run(monkeypatch, groups=["Viewer"], mfa=[],
                               required_role=None, enforce=True)
    assert result is None
    assert fake.mfa_lookups == 0, "an MFA lookup was made for a non-admin"


def test_an_operator_is_not_asked_for_mfa(monkeypatch):
    """Only Admin carries the privileges worth a second factor. Widening this to
    Operator would be a policy change, not a fix."""
    result, event, fake = _run(monkeypatch, groups=["Operator"], mfa=[],
                               required_role="Operator", enforce=True)
    assert result is None
    assert fake.mfa_lookups == 0


def test_the_check_runs_only_when_the_admin_role_is_actually_required(monkeypatch):
    """An Admin reading a Viewer-level route does not need to prove MFA: the privilege
    is not being exercised, and an extra AdminGetUser on every request is latency and
    cost for nothing."""
    result, event, fake = _run(monkeypatch, groups=["Admin"], mfa=[],
                               required_role=None, enforce=True)
    assert result is None
    assert fake.mfa_lookups == 0


def test_the_role_check_still_runs_first(monkeypatch):
    """A Viewer asking for Admin must get the role refusal, not an MFA message - the
    MFA detail would leak that Admin exists and what it needs."""
    result, _, fake = _run(monkeypatch, groups=[], mfa=[], required_role="Admin",
                           enforce=True)
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"] == "Insufficient permissions"
    assert fake.mfa_lookups == 0


# ==========================================================================
# failure modes
# ==========================================================================
def test_an_mfa_lookup_failure_fails_CLOSED_when_enforcing(monkeypatch):
    """Opposite of the audit-sink decision, deliberately. An audit write that fails
    open loses a record; an authorization check that fails open grants admin. When the
    answer is unknown and the flag says enforce, refuse."""
    fake = FakeCognito(groups=["Admin"], mfa=["SMS_MFA"])

    def boom(**kwargs):
        raise RuntimeError("cognito unavailable")

    fake.admin_get_user = boom
    monkeypatch.setattr(mw, "cognito", fake)
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    result = mw.require_auth(gw_event(), required_role="Admin")
    assert result is not None
    assert result["statusCode"] == 403


def test_an_mfa_lookup_failure_does_not_block_when_not_enforcing(monkeypatch):
    fake = FakeCognito(groups=["Admin"], mfa=["SMS_MFA"])

    def boom(**kwargs):
        raise RuntimeError("cognito unavailable")

    fake.admin_get_user = boom
    monkeypatch.setattr(mw, "cognito", fake)
    event = gw_event()
    assert mw.require_auth(event, required_role="Admin") is None
    assert event["_auth"]["mfaEnrolled"] is None, "unknown must not read as True"


def test_unknown_enrolment_is_none_not_false(monkeypatch):
    """`None` means "could not determine", `False` means "definitely not enrolled".
    Collapsing them would make a Cognito outage look like a policy violation."""
    fake = FakeCognito(groups=["Admin"], mfa=[])
    fake.admin_get_user = lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setattr(mw, "cognito", fake)
    event = gw_event()
    mw.require_auth(event, required_role="Admin")
    assert event["_auth"]["mfaEnrolled"] is None


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_the_flag_accepts_the_usual_spellings(monkeypatch, value):
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", value)
    fake = FakeCognito(groups=["Admin"], mfa=[])
    monkeypatch.setattr(mw, "cognito", fake)
    assert mw.require_auth(gw_event(), required_role="Admin") is not None


def test_internal_invokes_are_unaffected(monkeypatch):
    """A Lambda-to-Lambda invoke has no API Gateway context and never reached the role
    check, so it must not start reaching the MFA check either."""
    fake = FakeCognito(groups=[], mfa=[])
    monkeypatch.setattr(mw, "cognito", fake)
    monkeypatch.setenv("ADMIN_MFA_REQUIRED", "true")
    assert mw.require_auth({"detail": "internal"}, required_role="Admin") is None
    assert fake.mfa_lookups == 0
