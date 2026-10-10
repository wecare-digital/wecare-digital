"""One refusal matrix across every staff route family that can destroy data.

Why a matrix rather than a test per route
----------------------------------------
Before the Phase-0 safety fix, `require_auth(event)` was called with NO `required_role` on
`system-cleanup`, `messages/clear-all`, `contacts` and the `wa-business` catch-all, and
`require_auth` itself accepted a token from ANY Cognito pool and defaulted to Viewer. So
one defect — a missing argument — was repeated across four handlers, and what let it
survive is that nothing asserted the families together.

`ROUTES` below is that assertion. Adding a staff route family without adding a row is the
failure this file exists to make noisy. Every case is driven through the real `handler()`
with the real `require_auth`, so a refusal is end-to-end rather than measured against a
stub.

What each block pins
--------------------
* a CUSTOMER-pool token is refused on every family. This was the live hole: a customer
  token validated against `GetUser`, the staff group lookup then raised, the raise was
  swallowed, and the caller landed as a Viewer. The fake below reproduces that faithfully —
  its `get_user` succeeds for any token, because that is what the real API does.
* an unknown group, a `Partner`-only principal and an ungrouped principal all get least
  privilege, i.e. nothing. `Partner` is deliberately absent from `ROLE_HIERARCHY`.
* `Viewer` / `Operator` / `Admin` still behave as they did. This is the regression guard: a
  safety fix that locks out real staff has failed, and "it is secure now" is not an answer
  to "the dashboard stopped working".
* the two invoice routes are withdrawn at EVERY role, including Admin, and the GST sequence
  counter is never written.
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
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from unittest.mock import MagicMock, patch  # noqa: E402

import lambda_utils.destructive_confirm as dc  # noqa: E402
import lambda_utils.middleware as mw  # noqa: E402

CUSTOMER_POOL_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"


def _token(issuer: str) -> str:
    """A JWT-shaped string with a readable payload. Not signed — nothing here verifies it."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer, "sub": "sub-staff-1",
                    # `require_auth` pins the app client as well as the pool, so a token
                    # the gate should ACCEPT has to carry the claim a real access token
                    # carries. The customer-pool token below carries it too, so the pool
                    # refusal these rows assert is still the pool refusal.
                    "client_id": mw.STAFF_APP_CLIENT_ID}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeCognito:
    """`get_user` succeeds for ANY token, exactly as the real Cognito API does.

    That is the whole reason the issuer pin has to exist, so a fake that refused a foreign
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


class _EmptyTable:
    """An empty DynamoDB table handle that, crucially, TERMINATES.

    A bare `MagicMock` cannot stand in here. Several of these handlers paginate with

        while True:
            resp = table.scan(...)
            if 'LastEvaluatedKey' not in resp: break

    and on a MagicMock `scan()` returns a truthy mock while `'LastEvaluatedKey' not in resp`
    is False forever — so the loop never exits and the test HANGS rather than fails.
    Returning real dicts is what makes this file finish.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_item(self, **kw):
        return {}

    def put_item(self, **kw):
        return {}

    def update_item(self, **kw):
        return {"Attributes": {}}

    def delete_item(self, **kw):
        return {}

    def scan(self, **kw):
        return {"Items": [], "Count": 0}

    def query(self, **kw):
        return {"Items": [], "Count": 0}

    def batch_writer(self):
        return self


class _EmptyDynamo:
    def __init__(self):
        self.tables = {}

    def Table(self, name):  # noqa: N802 - boto3's spelling
        return self.tables.setdefault(name, _EmptyTable())


class _EmptyDynamoClient:
    def describe_table(self, TableName):  # noqa: N803
        return {"Table": {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}}

    def list_tables(self, **kw):
        return {"TableNames": []}


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
    """Nothing here may reach AWS, and no arm may actually delete."""
    monkeypatch.delenv("ADMIN_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(mw, "AUTH_SKIP_PATHS", [])
    monkeypatch.setattr(dc, "_dynamodb", _EmptyDynamo())
    for module in handlers.values():
        if hasattr(module, "dynamodb"):
            monkeypatch.setattr(module, "dynamodb", _EmptyDynamo(), raising=False)
        if hasattr(module, "dynamodb_client"):
            monkeypatch.setattr(module, "dynamodb_client", _EmptyDynamoClient(), raising=False)
        for attr in ("s3", "sqs", "lambda_client", "cloudwatch", "secrets_client", "sns"):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, MagicMock(), raising=False)
        if hasattr(module, "record_audit"):
            monkeypatch.setattr(module, "record_audit", lambda **kw: "log-1", raising=False)


def as_staff(monkeypatch, groups, mfa=("SOFTWARE_TOKEN_MFA",)):
    monkeypatch.setattr(mw, "cognito", FakeCognito(groups, mfa))
    return _token(mw.staff_pool_issuer())


def as_other_app_client(monkeypatch, groups=("Admin",)):
    """A token from the RIGHT pool but a DIFFERENT app client, with staff Admin groups.
    `iss` names the pool, not the client, so the issuer pin alone admits every client on
    `us-east-1_cSx0RHCIR`. One row per family, because a client pin applied in the gate but
    bypassed by a handler that authorises some other way would pass a single-route test.
    """
    monkeypatch.setattr(mw, "cognito", FakeCognito(groups))
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": mw.staff_pool_issuer(), "sub": "sub-staff-1",
                    "client_id": "9zzzzzz99z9z9zzz9z999zzz9z"}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def as_customer(monkeypatch, groups=("Admin",)):
    """A customer-pool token, with the STAFF pool holding an Admin of the same username.

    The second half is the point: it is the username-collision escalation. Without the
    issuer pin, `get_user` succeeded against the customer pool and the group lookup then
    returned the staff Admin's groups — full role escalation, not a missing default.
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
        "body": json.dumps(body if body is not None else {}),
    }
    if token:
        ev["headers"]["authorization"] = f"Bearer {token}"
    return ev


class _Ctx:
    aws_request_id = "req-bdg-1"


# ──────────────────────────────────────────────────────────────────────────
# THE MATRIX. One row per destructive-or-customer-data route family.
# ──────────────────────────────────────────────────────────────────────────
ROUTES = [
    ("cleanup-preview",            "cleanup",   "GET",    "/prod/system-cleanup",                             {}),
    ("cleanup-execute",            "cleanup",   "POST",   "/prod/system-cleanup",                             {}),
    ("messages-clear-all-delete",  "messages",  "DELETE", "/prod/messages/clear-all",                         {}),
    ("messages-clear-all-post",    "messages",  "POST",   "/prod/messages/clear-all",                         {}),
    ("messages-delete-one",        "messages",  "DELETE", "/prod/messages/m-1",                               {"messageId": "m-1"}),
    ("contacts-list",              "contacts",  "GET",    "/prod/contacts",                                   {}),
    ("contacts-search",            "contacts",  "GET",    "/prod/contacts/search",                            {}),
    ("contacts-create",            "contacts",  "POST",   "/prod/contacts",                                   {}),
    ("contacts-update",            "contacts",  "PUT",    "/prod/contacts/c-1",                               {"contactId": "c-1"}),
    ("contacts-lock",              "contacts",  "POST",   "/prod/contacts/c-1/lock",                          {"contactId": "c-1"}),
    ("contacts-unlock",            "contacts",  "POST",   "/prod/contacts/c-1/unlock",                        {"contactId": "c-1"}),
    ("contacts-delete",            "contacts",  "DELETE", "/prod/contacts/c-1",                               {"contactId": "c-1"}),
    ("documents-list",             "wa",        "GET",    "/prod/wa-business/documents",                      {}),
    ("documents-read",             "wa",        "GET",    "/prod/wa-business/documents/d-1",                  {}),
    ("documents-download",         "wa",        "GET",    "/prod/wa-business/documents/d-1/download",         {}),
    ("documents-create",           "wa",        "POST",   "/prod/wa-business/documents",                      {}),
    ("documents-update",           "wa",        "PUT",    "/prod/wa-business/documents/d-1",                  {}),
    ("flow-submissions-list",      "wa",        "GET",    "/prod/wa-business/flow-submissions",               {}),
    ("flow-submissions-export",    "wa",        "GET",    "/prod/wa-business/flow-submissions/export",        {}),
    ("flow-submissions-stats",     "wa",        "GET",    "/prod/wa-business/flow-submissions/stats",         {}),
    ("flow-submissions-status",    "wa",        "POST",   "/prod/wa-business/flow-submissions/update-status", {}),
    ("invoices-clear-all-delete",  "invoices",  "DELETE", "/prod/invoices/clear-all",                         {}),
    ("invoices-clear-all-post",    "invoices",  "POST",   "/prod/invoices/clear-all",                         {}),
    ("invoices-delete-one",        "invoices",  "DELETE", "/prod/invoices/INV-1",                             {"invoiceId": "INV-1"}),
]

ROUTE_IDS = [row[0] for row in ROUTES]


def _invoke(handlers, row, token, body=None):
    _id, family, method, path, params = row
    return handlers[family].handler(
        event(method, path, token, body=body if body is not None else {},
              path_params=params), _Ctx())


# ──────────────────────────────────────────────────────────────────────────
# a non-staff principal is refused everywhere
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_a_customer_pool_token_is_refused_on_every_staff_route(handlers, monkeypatch, row):
    """THE FINDING. Every one of these answered a customer token as a staff Viewer."""
    resp = _invoke(handlers, row, as_customer(monkeypatch))
    assert resp["statusCode"] == 401, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_a_token_from_another_app_client_is_refused_on_every_staff_route(
        handlers, monkeypatch, row):
    """Right pool, wrong client, full Admin groups — refused everywhere.

    This is the residue the issuer pin left: a second app client on the staff pool mints
    tokens with an identical `iss`, so every row here would have admitted one.
    """
    resp = _invoke(handlers, row, as_other_app_client(monkeypatch))
    assert resp["statusCode"] == 401, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_an_unknown_group_gets_least_privilege(handlers, monkeypatch, row):
    """No group in ROLE_HIERARCHY means no role, not Viewer."""
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("SomeFutureGroup",)))
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_a_partner_only_principal_gets_least_privilege(handlers, monkeypatch, row):
    """`Partner` is absent from ROLE_HIERARCHY on purpose, so it scores 0 and grants nothing."""
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Partner",)))
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_an_ungrouped_principal_gets_least_privilege(handlers, monkeypatch, row):
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=()))
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", ROUTES, ids=ROUTE_IDS)
def test_no_token_is_refused_on_every_staff_route(handlers, monkeypatch, row):
    as_staff(monkeypatch, groups=("Admin",))
    resp = _invoke(handlers, row, None)
    assert resp["statusCode"] == 401, (row[0], resp)


# ──────────────────────────────────────────────────────────────────────────
# real staff still work: the regression guard
# ──────────────────────────────────────────────────────────────────────────
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
    resp = _invoke(handlers, tuple(route), as_staff(monkeypatch, groups=(needed,)))
    assert resp["statusCode"] not in (401, 403), (row[0], resp)


@pytest.mark.parametrize("row", REPRESENTATIVE, ids=REP_IDS)
def test_an_admin_is_admitted_wherever_the_floor_is_lower(handlers, monkeypatch, row):
    """Admin outranks Viewer and Operator; the hierarchy still works upward."""
    *route, _needed = row
    resp = _invoke(handlers, tuple(route), as_staff(monkeypatch, groups=("Admin",)))
    assert resp["statusCode"] not in (401, 403), (row[0], resp)


@pytest.mark.parametrize("row,too_low", [
    (("documents-list", "wa", "GET", "/prod/wa-business/documents", {}), "Viewer"),
    (("flow-submissions-list", "wa", "GET", "/prod/wa-business/flow-submissions", {}), "Viewer"),
    (("contacts-delete", "contacts", "DELETE", "/prod/contacts/c-1", {"contactId": "c-1"}), "Viewer"),
    (("cleanup-preview", "cleanup", "GET", "/prod/system-cleanup", {}), "Operator"),
], ids=["documents-needs-operator", "flow-submissions-needs-operator",
        "contact-delete-needs-operator", "cleanup-needs-admin"])
def test_a_role_below_the_floor_is_refused(handlers, monkeypatch, row, too_low):
    """The floors are real, not decorative, and the 403 body shape is unchanged."""
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=(too_low,)))
    assert resp["statusCode"] == 403, (row[0], resp)
    body = json.loads(resp["body"])
    assert body["error"] == "Insufficient permissions"
    assert body["currentRole"] == too_low


CONTACT_MUTATIONS = [
    ("contacts-create", "contacts", "POST", "/prod/contacts", {}),
    ("contacts-update", "contacts", "PUT", "/prod/contacts/c-1", {"contactId": "c-1"}),
    ("contacts-lock", "contacts", "POST", "/prod/contacts/c-1/lock", {"contactId": "c-1"}),
    ("contacts-unlock", "contacts", "POST", "/prod/contacts/c-1/unlock", {"contactId": "c-1"}),
    ("contacts-delete", "contacts", "DELETE", "/prod/contacts/c-1", {"contactId": "c-1"}),
]


@pytest.mark.parametrize("row", CONTACT_MUTATIONS, ids=[row[0] for row in CONTACT_MUTATIONS])
def test_a_viewer_cannot_mutate_contacts(handlers, monkeypatch, row):
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Viewer",)))
    assert resp["statusCode"] == 403, (row[0], resp)


@pytest.mark.parametrize("row", CONTACT_MUTATIONS, ids=[row[0] for row in CONTACT_MUTATIONS])
def test_an_operator_can_attempt_each_contact_mutation(handlers, monkeypatch, row):
    resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Operator",)))
    assert resp["statusCode"] not in (401, 403), (row[0], resp)


def test_a_viewer_can_read_contacts_and_cannot_delete_them(handlers, monkeypatch):
    """The two halves of the contacts change, asserted together."""
    token = as_staff(monkeypatch, groups=("Viewer",))
    read = _invoke(handlers, ("contacts-list", "contacts", "GET", "/prod/contacts", {}), token)
    assert read["statusCode"] not in (401, 403)
    deleted = _invoke(handlers, ("contacts-delete", "contacts", "DELETE",
                                 "/prod/contacts/c-1", {"contactId": "c-1"}), token)
    assert deleted["statusCode"] == 403


def test_contact_history_protection_is_untouched_by_the_new_gate():
    """The gate added is on WHO may ask. WHETHER the delete is allowed is a separate,
    older guard and must still be there: an Operator does not outrank it."""
    source = (FUNCTIONS / "core/contacts/handler.py").read_text()
    # The refusal path and the three codes it answers with, all still present and all still
    # declared in the handler rather than inlined at a call site.
    assert "_hard_delete_refusal" in source
    assert "HARD_DELETE_REFUSED_PAYMENTS = 'CONTACT_HAS_PAYMENTS'" in source
    assert "HARD_DELETE_REFUSED_UNKNOWN = 'PAYMENT_LINKAGE_UNKNOWN'" in source
    assert "DELETE_REFUSED_LOCKED = 'CONTACT_LOCKED'" in source
    # And the linkage question is still asked of the shared module, which is the thing that
    # fail-closes when it cannot answer.
    assert "contact_payment_links.has_payment_links(" in source
    links = (SHARED / "lambda_utils/ecommerce/contact_payment_links.py").read_text()
    assert "PaymentLinkageUnknown" in links


# ──────────────────────────────────────────────────────────────────────────
# messages/clear-all: the full ladder
# ──────────────────────────────────────────────────────────────────────────
CLEAR_ALL = ("messages-clear-all-delete", "messages", "DELETE", "/prod/messages/clear-all", {})


class TestMessagesClearAll:
    """Wipes the entire Inbound + Outbound conversation history. Was reachable with no role."""

    def test_a_viewer_is_refused(self, handlers, monkeypatch):
        assert _invoke(handlers, CLEAR_ALL,
                       as_staff(monkeypatch, groups=("Viewer",)))["statusCode"] == 403

    def test_an_operator_is_refused(self, handlers, monkeypatch):
        """Operator may delete ONE message and must not be able to delete all of them."""
        assert _invoke(handlers, CLEAR_ALL,
                       as_staff(monkeypatch, groups=("Operator",)))["statusCode"] == 403

    def test_an_operator_can_still_delete_a_single_message(self, handlers, monkeypatch):
        """The floor moved from nothing to Operator; it must not have moved past it."""
        resp = _invoke(handlers, ("messages-delete-one", "messages", "DELETE",
                                  "/prod/messages/m-1", {"messageId": "m-1"}),
                       as_staff(monkeypatch, groups=("Operator",)))
        assert resp["statusCode"] not in (401, 403)

    @pytest.mark.parametrize("mfa", [(), None], ids=["not-enrolled", "lookup-failed"])
    def test_an_admin_without_mfa_is_refused(self, handlers, monkeypatch, mfa):
        """False and None both refuse. None means the Cognito lookup could not answer, so a
        Cognito outage cannot open this route."""
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
        """THE UI-BYPASS CASE: a direct call that never asked for a preview."""
        resp = _invoke(handlers, CLEAR_ALL, as_staff(monkeypatch, groups=("Admin",)))
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

    def test_a_wrong_or_replayed_token_is_refused(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        monkeypatch.setattr(dc, "consume", lambda *a, **kw: {
            "error": "Confirmation token is invalid or already used", "status": 409})
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

    def test_the_audit_record_names_the_actor_and_the_counts(self, handlers, monkeypatch):
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
        # The actor is the token's `sub`, never a body field.
        assert calls[0]["actor"] == "sub-staff-1"
        assert calls[0]["details"]["previewCounts"] == {"inbound": 7}

    def test_the_post_alias_is_gated_identically(self, handlers, monkeypatch):
        """Gating DELETE and not POST would gate neither — both route to one branch."""
        row = ("messages-clear-all-post", "messages", "POST", "/prod/messages/clear-all", {})
        assert _invoke(handlers, row,
                       as_staff(monkeypatch, groups=("Operator",)))["statusCode"] == 403


# ──────────────────────────────────────────────────────────────────────────
# invoices: withdrawn, at every role
# ──────────────────────────────────────────────────────────────────────────
class TestInvoicesAreImmutable:
    """Every invoice carries a number from the consecutive GST series from the moment it is
    created, so there is no invoice these routes could safely delete."""

    DELETE_ONE = ("invoices-delete-one", "invoices", "DELETE", "/prod/invoices/INV-1",
                  {"invoiceId": "INV-1"})

    @pytest.mark.parametrize("group", ["Viewer", "Operator", "Admin"])
    def test_deleting_one_invoice_is_refused_at_every_role(self, handlers, monkeypatch, group):
        resp = _invoke(handlers, self.DELETE_ONE, as_staff(monkeypatch, groups=(group,)))
        # Viewer and Operator are stopped by the Admin gate; an Admin is stopped by the route
        # itself, and that is the interesting one.
        assert resp["statusCode"] in (403, 410)
        if group == "Admin":
            assert resp["statusCode"] == 410
            body = json.loads(resp["body"])
            assert body["errorCode"] == "INVOICE_IMMUTABLE"
            assert "cancel" in body["use"]

    def test_the_sequence_counter_is_never_written(self, handlers, monkeypatch):
        """`adjustSequence` used to DECREMENT the GST counter, so the next invoice reused a
        number already sent to a customer. Two documents, one number."""
        token = as_staff(monkeypatch, groups=("Admin",))
        ddb = MagicMock()
        monkeypatch.setattr(handlers["invoices"], "dynamodb", ddb)
        resp = _invoke(handlers, self.DELETE_ONE, token, body={"adjustSequence": True})
        assert resp["statusCode"] == 410
        for name, _args, _kw in ddb.Table.return_value.method_calls:
            assert name not in ("update_item", "delete_item", "put_item"), name

    def test_the_rendered_invoice_is_not_deleted_from_s3(self, handlers, monkeypatch):
        """The PDF/PNG is the artefact the customer was sent."""
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
        resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Admin",)))
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"])["errorCode"] == "INVOICE_HISTORY_IMMUTABLE"

    def test_the_body_action_trigger_is_withdrawn_too(self, handlers, monkeypatch):
        """`POST /invoices` with `_action=clear-all` ran BEFORE every other POST arm, so
        leaving it would have left the whole wipe reachable through the create route."""
        row = ("invoices-create", "invoices", "POST", "/prod/invoices", {})
        resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Admin",)),
                       body={"_action": "clear-all"})
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"])["errorCode"] == "INVOICE_HISTORY_IMMUTABLE"

    def test_clear_all_deletes_nothing(self, handlers, monkeypatch):
        token = as_staff(monkeypatch, groups=("Admin",))
        ddb = MagicMock()
        s3 = MagicMock()
        monkeypatch.setattr(handlers["invoices"], "dynamodb", ddb)
        monkeypatch.setattr(handlers["invoices"], "s3", s3)
        row = ("invoices-clear-all-delete", "invoices", "DELETE", "/prod/invoices/clear-all", {})
        assert _invoke(handlers, row, token)["statusCode"] == 410
        ddb.Table.return_value.batch_writer.assert_not_called()
        s3.delete_objects.assert_not_called()

    def test_both_refusals_are_audited(self, handlers, monkeypatch):
        """An ATTEMPT to destroy a tax document is worth knowing about. Best effort rather
        than fail-closed, because nothing is being deleted either way."""
        token = as_staff(monkeypatch, groups=("Admin",))
        calls = []
        monkeypatch.setattr(handlers["invoices"], "record_audit",
                            lambda **kw: (calls.append(kw), "log-1")[1])
        _invoke(handlers, self.DELETE_ONE, token)
        _invoke(handlers, ("invoices-clear-all-delete", "invoices", "DELETE",
                           "/prod/invoices/clear-all", {}), token)
        actions = [c["action"] for c in calls]
        assert "invoice.delete" in actions
        assert "invoice.clear_all" in actions
        assert all(c["details"]["outcome"] == "refused" for c in calls)

    def test_cancel_is_still_reachable(self, handlers, monkeypatch):
        """The refusals above are only defensible because the supported void still works:
        `cancel_invoice` keeps the row and the number and records the reason."""
        row = ("invoices-cancel", "invoices", "POST", "/prod/invoices/INV-1/cancel",
               {"invoiceId": "INV-1"})
        resp = _invoke(handlers, row, as_staff(monkeypatch, groups=("Admin",)),
                       body={"reason": "duplicate"})
        assert resp["statusCode"] not in (401, 403, 410)


# ──────────────────────────────────────────────────────────────────────────
# customer-serving routes must NOT be behind require_auth
# ──────────────────────────────────────────────────────────────────────────
def test_customer_document_access_uses_the_customer_pool_helper_not_require_auth():
    """A customer route behind `require_auth` is how a customer becomes a staff Viewer.

    Structural, because the failure mode is a future edit reaching for the convenient
    import. `core/secure-files` serves the customer-facing Drop Docs arms and proves
    identity against the CUSTOMER pool; the staff arm in the same file keeps `require_auth`
    at an Operator floor, which is correct and is what the last assertion pins.
    """
    source = (FUNCTIONS / "core/secure-files/handler.py").read_text()
    assert "_customer_identity" in source
    assert "customer_auth" in source or "CUSTOMER_POOL" in source.upper()
    # The STAFF arm still carries a role, and it is Operator. Matched loosely on the
    # argument rather than on an exact call string, because this file passes it
    # positionally — `require_auth(event, "Operator")` — and pinning the spelling rather
    # than the requirement is how a structural test breaks on a reformat.
    assert "require_auth(event" in source
    assert "Operator" in source


def test_the_staff_pool_is_not_the_customer_pool():
    """One env var holding "the pool" is how the two get confused."""
    import lambda_utils.customer_auth as ca
    assert mw.staff_pool_issuer() != ca.CUSTOMER_POOL_ISSUER
    assert "us-east-1_cSx0RHCIR" in mw.staff_pool_issuer()
    assert "us-east-1_46ULYuukt" in ca.CUSTOMER_POOL_ISSUER
