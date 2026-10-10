"""One refusal matrix across every staff route family that can destroy data.

Why a matrix rather than a test per route
----------------------------------------
Before this PR, `require_auth(event)` was called with NO `required_role` on
`system-cleanup`, `messages/clear-all`, `contacts` and the `wa-business` catch-all, and
`require_auth` itself accepted a token from any Cognito pool and defaulted to Viewer. So
one defect — a missing argument — was repeated across four handlers, and the thing that
let it survive is that nothing asserted the families together.

`ROUTES` below is that assertion. Adding a staff route family without adding a row is the
failure this file is built to make noisy, and every case here is driven through the real
`handler()` with the real `require_auth`, so a refusal is end-to-end rather than measured
against a stub.

What each column of the matrix pins
-----------------------------------
* a CUSTOMER-pool token is refused 401 on every family. This was the live hole: a customer
  token validated against `GetUser` and fell through to Viewer.
* an unknown group and a `Partner`-only principal get least privilege, i.e. nothing.
  `Partner` is deliberately absent from `ROLE_HIERARCHY`.
* `Viewer` / `Operator` / `Admin` still behave as they did. This is the regression guard:
  a safety fix that locks out real staff has failed, and "it is secure now" is not an
  acceptable answer to "the dashboard stopped working".
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify/functions"
SHARED = FUNCTIONS / "shared"
for _p in (str(SHARED),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unittest.mock import MagicMock, patch  # noqa: E402

import lambda_utils.destructive_confirm as dc  # noqa: E402
import lambda_utils.middleware as mw  # noqa: E402

CUSTOMER_POOL_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"


def _token(issuer: str) -> str:
    """A JWT-shaped string with a readable payload. Not signed — nothing here verifies it."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer, "sub": "sub-staff-1"}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeCognito:
    """`get_user` succeeds for ANY token, exactly as the real Cognito API does.

    That is the whole reason the issuer pin must exist, so a fake that refused a foreign
    token would be testing the fake rather than the guard.
    """

    class exceptions:
        class NotAuthorizedException(Exception):
            pass

    def __init__(self, groups, mfa=("SOFTWARE_TOKEN_MFA",)):
        self._groups = list(groups)
        self._mfa = list(mfa)

    def get_user(self, AccessToken):  # noqa: N803
        return {"Username": "staff-1",
                "UserAttributes": [{"Name": "email", "Value": "staff@example.test"},
                                   {"Name": "sub", "Value": "sub-staff-1"}]}

    def admin_list_groups_for_user(self, Username, UserPoolId):  # noqa: N803
        return {"Groups": [{"GroupName": g} for g in self._groups]}

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        return {"UserMFASettingList": self._mfa,
                "PreferredMfaSetting": self._mfa[0] if self._mfa else None}


def _load(rel: str, module_name: str):
    """Load a handler by path under a unique name, with boto3 stubbed.

    Unique names because every Lambda in this repo has a `handler.py` and
    `sys.modules['handler']` goes to whichever imported first — the collision
    `tests/test_whatsapp_sender_no_bypass.py` documents.
    """
    path = FUNCTIONS / rel / "handler.py"
    for extra in (str(FUNCTIONS / rel), str(FUNCTIONS / rel / "modules")):
        if os.path.isdir(extra) and extra not in sys.path:
            sys.path.insert(0, extra)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
        with patch("boto3.resource", MagicMock()), patch("boto3.client", MagicMock()):
            spec.loader.exec_module(module)
    return module


# ──────────────────────────────────────────────────────────────────────────
# the handlers under test, loaded once
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def handlers():
    return {
        "cleanup": _load("operations/system-cleanup", "bdg_system_cleanup"),
        "messages": _load("core/messages-delete", "bdg_messages_delete"),
        "contacts": _load("core/contacts", "bdg_contacts"),
        "wa": _load("messaging/whatsapp-business-api", "bdg_wa_business"),
        "invoices": _load("payments/invoice-engine", "bdg_invoice_engine"),
    }


@pytest.fixture(autouse=True)
def offline(handlers, monkeypatch):
    """Nothing in this file may reach AWS, and no arm may actually delete."""
    monkeypatch.delenv("ADMIN_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(mw, "AUTH_SKIP_PATHS", [])
    monkeypatch.setattr(dc, "_dynamodb", MagicMock())
    for module in handlers.values():
        for attr in ("dynamodb", "dynamodb_client", "s3", "sqs", "lambda_client",
                     "cloudwatch", "secrets_client", "sns"):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, MagicMock(), raising=False)
        if hasattr(module, "record_audit"):
            monkeypatch.setattr(module, "record_audit", lambda **kw: "log-1", raising=False)


def as_staff(monkeypatch, groups, mfa=("SOFTWARE_TOKEN_MFA",)):
    monkeypatch.setattr(mw, "cognito", FakeCognito(groups, mfa))
    return _token(mw.staff_pool_issuer())


def as_customer(monkeypatch, groups=("Admin",)):
    """A customer-pool token, with the staff pool holding an Admin of the same username.

    The second half matters: it is the username-collision escalation. Without the issuer
    pin, `get_user` succeeded against the customer pool and the group lookup then returned
    the STAFF Admin's groups.
    """
    monkeypatch.setattr(mw, "cognito", FakeCognito(groups))
    return _token(CUSTOMER_POOL_ISSUER)


def event(method, path, token, body=None, path_params=None, query=None):
    ev = {
        "requestContext": {"apiId": "zllr9lrg7j", "stage": "prod",
                           "domainName": "api.wecare.digital",
                           "http": {"method": method, "path": path,
                                    "sourceIp": "203.0.113.1"}},
        "headers": {"origin": "https://wecare.digital"},
        "rawPath": path,
        "path": path,
        "httpMethod": method,
        "pathParameters": path_params or {},
        "queryStringParameters": query or {},
    }
    if token:
        ev["headers"]["authorization"] = f"Bearer {token}"
    ev["body"] = json.dumps(body if body is not None else {})
    return ev


class _Ctx:
    aws_request_id = "req-bdg-1"


def call(handlers, family, method, path, token, **kw):
    return handlers[family]["module"].handler(
        event(method, path, token, **kw), _Ctx()) if False else None


# ──────────────────────────────────────────────────────────────────────────
# THE MATRIX. One row per destructive-or-customer-data route family.
# (family, method, path, path_params) -> the minimum role the route requires
# ──────────────────────────────────────────────────────────────────────────
ROUTES = [
    # id,                          family,      method,   path,                                       params
    ("cleanup-preview",            "cleanup",   "GET",    "/prod/system-cleanup",                      {}),
    ("cleanup-execute",            "cleanup",   "POST",   "/prod/system-cleanup",                      {}),
    ("messages-clear-all-delete",  "messages",  "DELETE", "/prod/messages/clear-all",                  {}),
    ("messages-clear-all-post",    "messages",  "POST",   "/prod/messages/clear-all",                  {}),
    ("messages-delete-one",        "messages",  "DELETE", "/prod/messages/m-1",                        {"messageId": "m-1"}),
    ("contacts-list",              "contacts",  "GET",    "/prod/contacts",                            {}),
    ("contacts-search",            "contacts",  "GET",    "/prod/contacts/search",                     {}),
    ("contacts-delete",            "contacts",  "DELETE", "/prod/contacts/c-1",                        {"contactId": "c-1"}),
    ("documents-list",             "wa",        "GET",    "/prod/wa-business/documents",               {}),
    ("documents-read",             "wa",        "GET",    "/prod/wa-business/documents/d-1",           {}),
    ("documents-download",         "wa",        "GET",    "/prod/wa-business/documents/d-1/download",  {}),
    ("documents-create",           "wa",        "POST",   "/prod/wa-business/documents",               {}),
    ("documents-update",           "wa",        "PUT",    "/prod/wa-business/documents/d-1",           {}),
    ("flow-submissions-list",      "wa",        "GET",    "/prod/wa-business/flow-submissions",        {}),
    ("flow-submissions-export",    "wa",        "GET",    "/prod/wa-business/flow-submissions/export", {}),
    ("flow-submissions-stats",     "wa",        "GET",    "/prod/wa-business/flow-submissions/stats",  {}),
    ("flow-submissions-status",    "wa",        "POST",   "/prod/wa-business/flow-submissions/update-status", {}),
    ("invoices-clear-all-delete",  "invoices",  "DELETE", "/prod/invoices/clear-all",                  {}),
    ("invoices-clear-all-post",    "invoices",  "POST",   "/prod/invoices/clear-all",                  {}),
    ("invoices-delete-one",        "invoices",  "DELETE", "/prod/invoices/INV-1",                      {"invoiceId": "INV-1"}),
]

ROUTE_IDS = [row[0] for row in ROUTES]


def _invoke(handlers, row, token, body=None):
    _id, family, method, path, params = row
    payload = body if body is not None else {}
    return handlers[family].handler(
        event(method, path, token, body=payload, path_params=params), _Ctx())


# ──────────────────────────────────────────────────────────────────────────
# a customer token is refused everywhere
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_a_customer_pool_token_is_refused_on_every_staff_route(handlers, monkeypatch, row):
    """THE FINDING. Every one of these answered as a staff Viewer to a customer token."""
    token = as_customer(monkeypatch)
    resp = _invoke(handlers, row, token)
    assert resp["statusCode"] == 401, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_an_unknown_group_gets_least_privilege(handlers, monkeypatch, row):
    """No group in ROLE_HIERARCHY means no role, not Viewer."""
    token = as_staff(monkeypatch, groups=("SomeFutureGroup",))
    resp = _invoke(handlers, row, token)
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_a_partner_only_principal_gets_least_privilege(handlers, monkeypatch, row):
    """`Partner` is absent from ROLE_HIERARCHY on purpose, so it scores 0 and grants nothing."""
    token = as_staff(monkeypatch, groups=("Partner",))
    resp = _invoke(handlers, row, token)
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_an_ungrouped_principal_gets_least_privilege(handlers, monkeypatch, row):
    token = as_staff(monkeypatch, groups=())
    resp = _invoke(handlers, row, token)
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_no_token_is_refused_on_every_staff_route(handlers, monkeypatch, row):
    as_staff(monkeypatch, groups=("Admin",))
    resp = _invoke(handlers, row, None)
    assert resp["statusCode"] == 401, (row[0], resp)


# ──────────────────────────────────────────────────────────────────────────
# real staff still work: the regression guard
# ──────────────────────────────────────────────────────────────────────────
#: The minimum role each family needs, and therefore who must still get through.
#: `invoices-*` is absent because both of its destructive arms are withdrawn (410) at
#: every role — see `TestInvoicesAreImmutable`.
REPRESENTATIVE = [
    ("contacts-list", "contacts", "GET", "/prod/contacts", {}, "Viewer"),
    ("documents-list", "wa", "GET", "/prod/wa-business/documents", {}, "Operator"),
    ("flow-submissions-list", "wa", "GET", "/prod/wa-business/flow-submissions", {}, "Operator"),
    ("contacts-delete", "contacts", "DELETE", "/prod/contacts/c-1", {"contactId": "c-1"}, "Operator"),
    ("cleanup-preview", "cleanup", "GET", "/prod/system-cleanup", {}, "Admin"),
]
REP_IDS = [r[0] for r in REPRESENTATIVE]


@pytest.mark.parametrize("row", REPRESENTATIVE, ids=REP_IDS)
def test_the_required_role_is_admitted(handlers, monkeypatch, row):
    """A safety fix that locks out real staff has failed."""
    *route, needed = row
    token = as_staff(monkeypatch, groups=(needed,))
    resp = _invoke(handlers, tuple(route), token)
    assert resp["statusCode"] != 401, (row[0], resp)
    assert resp["statusCode"] != 403, (row[0], resp)


@pytest.mark.parametrize("row", REPRESENTATIVE, ids=REP_IDS)
def test_an_admin_is_admitted_everywhere_the_floor_is_lower(handlers, monkeypatch, row):
    """Admin outranks Viewer and Operator; the hierarchy still works upward."""
    *route, _needed = row
    token = as_staff(monkeypatch, groups=("Admin",))
    resp = _invoke(handlers, tuple(route), token)
    assert resp["statusCode"] not in (401, 403), (row[0], resp)


@pytest.mark.parametrize("row,too_low", [
    (("documents-list", "wa", "GET", "/prod/wa-business/documents", {}), "Viewer"),
    (("flow-submissions-list", "wa", "GET", "/prod/wa-business/flow-submissions", {}), "Viewer"),
    (("contacts-delete", "contacts", "DELETE", "/prod/contacts/c-1", {"contactId": "c-1"}), "Viewer"),
    (("cleanup-preview", "cleanup", "GET", "/prod/system-cleanup", {}), "Operator"),
], ids=["documents-needs-operator", "flow-submissions-needs-operator",
        "contact-delete-needs-operator", "cleanup-needs-admin"])
def test_a_role_below_the_floor_is_refused(handlers, monkeypatch, row, too_low):
    """The floors are real, not decorative."""
    token = as_staff(monkeypatch, groups=(too_low,))
    resp = _invoke(handlers, row, token)
    assert resp["statusCode"] == 403, (row[0], resp)
    body = json.loads(resp["body"])
    assert body["error"] == "Insufficient permissions"
    assert body["currentRole"] == too_low


def test_a_viewer_can_still_read_contacts_and_not_delete_them(handlers, monkeypatch):
    """The two halves of the contacts change, asserted together."""
    token = as_staff(monkeypatch, groups=("Viewer",))
    read = _invoke(handlers, ("contacts-list", "contacts", "GET", "/prod/contacts", {}), token)
    assert read["statusCode"] not in (401, 403)
    delete = _invoke(handlers, ("contacts-delete", "contacts", "DELETE", "/prod/contacts/c-1",
                                {"contactId": "c-1"}), token)
    assert delete["statusCode"] == 403


# ──────────────────────────────────────────────────────────────────────────
# messages/clear-all: the full ladder
# ──────────────────────────────────────────────────────────────────────────
CLEAR_ALL = ("messages-clear-all-delete", "messages", "DELETE", "/prod/messages/clear-all", {})


class TestMessagesClearAll:
    """Wipes the entire Inbound + Outbound history. Was reachable with no role at all."""

    def test_a_viewer_is_refused(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Viewer",))
        assert _invoke(handlers, CLEAR_ALL, token)["statusCode"] == 403

    def test_an_operator_is_refused(self, handlers, monkeypatch):
        """Operator may delete ONE message and must not be able to delete all of them."""
        token = as_staff(monkeypatch, groups=("Operator",))
        assert _invoke(handlers, CLEAR_ALL, token)["statusCode"] == 403

    def test_an_operator_can_still_delete_a_single_message(self, handlers, monkeypatch):
        """The floor moved from nothing to Operator; it must not have moved past it."""
        token = as_staff(monkeypatch, groups=("Operator",))
        resp = _invoke(handlers, ("messages-delete-one", "messages", "DELETE",
                                  "/prod/messages/m-1", {"messageId": "m-1"}), token)
        assert resp["statusCode"] not in (401, 403)

    @pytest.mark.parametrize("mfa", [(), None], ids=["not-enrolled", "lookup-failed"])
    def test_an_admin_without_mfa_is_refused(self, handlers, monkeypatch, mfa):
        if mfa is None:
            fake = FakeCognito(("Admin",), ())
            fake.admin_get_user = lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))
            monkeypatch.setattr(mw, "cognito", fake)
            token = _token(mw.staff_pool_issuer())
        else:
            token = as_staff(monkeypatch, groups=("Admin",), mfa=mfa)
        resp = _invoke(handlers, CLEAR_ALL, token)
        assert resp["statusCode"] == 403
        assert json.loads(resp["body"])["error"] == "MFA required"

    def test_an_mfad_admin_without_a_confirmation_token_is_refused(self, handlers, monkeypatch):
        """The UI-bypass case: a direct call that never asked for a preview."""
        token = as_staff(monkeypatch, groups=("Admin",))
        resp = _invoke(handlers, CLEAR_ALL, token)
        assert resp["statusCode"] == 400
        assert "confirmationToken" in json.loads(resp["body"])["error"]

    def test_the_preview_mints_a_token_and_deletes_nothing(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        monkeypatch.setattr(dc, "mint", lambda *a, **kw: "tok-preview-1")
        resp = _invoke(handlers, CLEAR_ALL, token, body={"preview": True})
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["preview"] is True
        assert body["confirmationToken"] == "tok-preview-1"

    def test_a_wrong_token_is_refused(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        monkeypatch.setattr(dc, "consume",
                            lambda *a, **kw: {"error": "Confirmation token is invalid or "
                                                       "already used", "status": 409})
        resp = _invoke(handlers, CLEAR_ALL, token, body={"confirmationToken": "nope"})
        assert resp["statusCode"] == 409

    def test_a_failing_audit_write_refuses_the_whole_wipe(self, handlers, monkeypatch):
        """`record_audit` fails open by design; an irreversible wipe cannot afford that."""
        token = as_staff(monkeypatch, groups=("Admin",))
        monkeypatch.setattr(dc, "consume", lambda *a, **kw: {"ok": True, "counts": {}})
        monkeypatch.setattr(handlers["messages"], "record_audit", lambda **kw: None)
        resp = _invoke(handlers, CLEAR_ALL, token, body={"confirmationToken": "tok"})
        assert resp["statusCode"] == 503
        assert "nothing was deleted" in json.loads(resp["body"])["error"]

    def test_the_audit_record_names_the_actor_and_the_tables(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        monkeypatch.setattr(dc, "consume",
                            lambda *a, **kw: {"ok": True, "counts": {"inbound": 7}})
        calls = []
        monkeypatch.setattr(handlers["messages"], "record_audit",
                            lambda **kw: (calls.append(kw), "log-1")[1])
        resp = _invoke(handlers, CLEAR_ALL, token, body={"confirmationToken": "tok"})
        assert resp["statusCode"] == 200
        assert len(calls) == 1
        assert calls[0]["action"] == "messages.clear_all"
        assert calls[0]["actor"] == "sub-staff-1"
        assert calls[0]["details"]["previewCounts"] == {"inbound": 7}

    def test_the_post_alias_is_gated_identically(self, handlers, monkeypatch):
        """Gating DELETE and not POST would gate neither — both route to one branch."""
        token = as_staff(monkeypatch, groups=("Operator",))
        row = ("messages-clear-all-post", "messages", "POST", "/prod/messages/clear-all", {})
        assert _invoke(handlers, row, token)["statusCode"] == 403


# ──────────────────────────────────────────────────────────────────────────
# invoices: withdrawn, at every role
# ──────────────────────────────────────────────────────────────────────────
class TestInvoicesAreImmutable:
    """Every invoice carries a number from the consecutive GST series from the moment it
    is created, so there is no invoice these routes could safely delete."""

    DELETE_ONE = ("invoices-delete-one", "invoices", "DELETE", "/prod/invoices/INV-1",
                  {"invoiceId": "INV-1"})

    @pytest.mark.parametrize("group", ["Viewer", "Operator", "Admin"])
    def test_deleting_one_invoice_is_refused_at_every_role(self, handlers, monkeypatch, group):
        token = as_staff(monkeypatch, groups=(group,))
        resp = _invoke(handlers, self.DELETE_ONE, token)
        # Viewer and Operator are refused by the Admin gate; an Admin is refused by the
        # route itself. Both are refusals, and the Admin one is the interesting one.
        assert resp["statusCode"] in (403, 410)
        if group == "Admin":
            assert resp["statusCode"] == 410
            body = json.loads(resp["body"])
            assert body["errorCode"] == "INVOICE_IMMUTABLE"
            assert "cancel" in body["use"]

    def test_the_sequence_counter_is_never_touched(self, handlers, monkeypatch):
        """`adjustSequence` used to DECREMENT the GST counter, so the next invoice reused
        a number already sent to a customer. Asserted on the table handle: no write."""
        token = as_staff(monkeypatch, groups=("Admin",))
        ddb = MagicMock()
        monkeypatch.setattr(handlers["invoices"], "dynamodb", ddb)
        resp = _invoke(handlers, self.DELETE_ONE, token, body={"adjustSequence": True})
        assert resp["statusCode"] == 410
        for call in ddb.Table.return_value.method_calls:
            assert call[0] not in ("update_item", "delete_item", "put_item"), call

    def test_the_invoice_row_and_its_s3_assets_survive(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        s3 = MagicMock()
        monkeypatch.setattr(handlers["invoices"], "s3", s3)
        assert _invoke(handlers, self.DELETE_ONE, token)["statusCode"] == 410
        s3.delete_object.assert_not_called()
        s3.delete_objects.assert_not_called()

    @pytest.mark.parametrize("row", [
        ("invoices-clear-all-delete", "invoices", "DELETE", "/prod/invoices/clear-all", {}),
        ("invoices-clear-all-post", "invoices", "POST", "/prod/invoices/clear-all", {}),
    ], ids=["delete-verb", "post-alias"])
    def test_clear_all_is_withdrawn(self, handlers, monkeypatch, row):
        token = as_staff(monkeypatch, groups=("Admin",))
        resp = _invoke(handlers, row, token)
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"])["errorCode"] == "INVOICE_HISTORY_IMMUTABLE"

    def test_the_body_action_trigger_is_withdrawn_too(self, handlers, monkeypatch):
        """`POST /invoices` with `_action=clear-all` ran BEFORE every other POST arm, so
        leaving it would have left the whole wipe reachable through the create route."""
        token = as_staff(monkeypatch, groups=("Admin",))
        row = ("invoices-create", "invoices", "POST", "/prod/invoices", {})
        resp = _invoke(handlers, row, token, body={"_action": "clear-all"})
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"])["errorCode"] == "INVOICE_HISTORY_IMMUTABLE"

    def test_nothing_is_deleted_by_clear_all(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        ddb = MagicMock()
        s3 = MagicMock()
        monkeypatch.setattr(handlers["invoices"], "dynamodb", ddb)
        monkeypatch.setattr(handlers["invoices"], "s3", s3)
        row = ("invoices-clear-all-delete", "invoices", "DELETE", "/prod/invoices/clear-all", {})
        assert _invoke(handlers, row, token)["statusCode"] == 410
        ddb.Table.return_value.batch_writer.assert_not_called()
        s3.delete_objects.assert_not_called()

    def test_cancel_is_still_reachable_for_an_admin(self, handlers, monkeypatch):
        """The refusal above is only defensible because the supported void still works."""
        token = as_staff(monkeypatch, groups=("Admin",))
        row = ("invoices-cancel", "invoices", "POST", "/prod/invoices/INV-1/cancel",
               {"invoiceId": "INV-1"})
        resp = _invoke(handlers, row, token, body={"reason": "duplicate"})
        assert resp["statusCode"] not in (401, 403, 410)


# ──────────────────────────────────────────────────────────────────────────
# customer-serving routes must NOT be behind require_auth
# ──────────────────────────────────────────────────────────────────────────
def test_customer_document_access_uses_the_customer_pool_helper_not_require_auth():
    """A customer route behind `require_auth` is how a customer becomes a staff Viewer.

    Structural, because the failure mode is a future edit reaching for the convenient
    import. `core/secure-files` serves the customer-facing Drop Docs arms and must prove
    identity against the CUSTOMER pool; the staff arm in the same file keeps `require_auth`
    with an Operator floor, which is correct and is what the second assertion pins.
    """
    source = (FUNCTIONS / "core/secure-files/handler.py").read_text()
    assert "_customer_identity" in source
    assert "customer_auth" in source or "CUSTOMER_POOL" in source.upper()
    assert "require_auth(event, required_role='Operator')" in source


def test_the_staff_pool_is_not_the_customer_pool():
    """One env var holding "the pool" is how the two get confused."""
    import lambda_utils.customer_auth as ca
    assert mw.staff_pool_issuer() != ca.CUSTOMER_POOL_ISSUER
    assert "us-east-1_cSx0RHCIR" in mw.staff_pool_issuer()
    assert "us-east-1_46ULYuukt" in ca.CUSTOMER_POOL_ISSUER
