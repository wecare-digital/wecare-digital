"""A CRM contact can be given a Cognito login - behind a flag, with user-level APIs only.

The gap this closes
-------------------
A CRM-created contact has no Cognito user, so the WhatsApp OTP trigger answers
`registered=false` and sends nothing: the customer the CRM just created cannot sign in. The fix
is one idempotent `AdminCreateUser`, which `core/secure-files._ensure_customer_user` already
makes and already holds the grant for, reached by async invoke so the CRM's shared role gains
nothing.

What these tests are actually defending
---------------------------------------
Two things, and neither is "does the happy path work".

1. **OFF MEANS NO CALL AT ALL.** `CRM_PROVISION_CUSTOMER_LOGIN` defaults off, so a CRM create
   must behave today exactly as it did before this landed - not "invoke and ignore the result",
   not "build the client and skip the call". No invoke, and no Lambda client constructed.

2. **NO POOL-LEVEL WRITE, EVER.** On 2026-09-28 a partial `update-user-pool` call against this
   same customer pool returned 200 and silently cleared three auth triggers and flipped
   `AllowAdminCreateUserOnly` to false - self-signup opened on a public, internet-facing pool,
   with no error and no warning. So the absence of that API is asserted on the AST of every file
   this feature touched, rather than left to code review. The forbidden identifier is ASSEMBLED
   AT RUNTIME below so that this file does not itself contain the string it forbids.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contacts_fake_table import FakeContactsResource, FakeContactsTable  # noqa: E402

CONTACTS_HANDLER = ROOT / "amplify/functions/core/contacts/handler.py"
SECURE_FILES_HANDLER = ROOT / "amplify/functions/core/secure-files/handler.py"
CUSTOMER_ORDERS_HANDLER = ROOT / "amplify/functions/ecommerce/customer-orders/handler.py"
SECURE_FILES_PROVISION = ROOT / "scripts/provision_secure_files_api.py"
ENV_MANIFEST = ROOT / "config/lambda-env-manifest.json"

#: Every file this feature changed. The pool-level-write assertion walks all of them.
CHANGED_PYTHON = (
    CONTACTS_HANDLER,
    SECURE_FILES_HANDLER,
    CUSTOMER_ORDERS_HANDLER,
    ROOT / "scripts/report_contact_phone_formats.py",
)

E164 = "+919876543210"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── fakes ─────────────────────────────────────────────────────────────────────

class RecordingLambda:
    """`boto3.client('lambda')`, recording every invoke."""

    def __init__(self, error: Exception | None = None) -> None:
        self.invokes: list = []
        self.error = error

    def invoke(self, **kwargs):
        self.invokes.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"StatusCode": 202}


class _Exceptions:
    class AliasExistsException(Exception):
        pass

    class UsernameExistsException(Exception):
        pass


class FakeCognito:
    """Just enough of `cognito-idp` for `_ensure_customer_user`.

    It deliberately exposes NO `update_user_pool`-shaped method: a fake that answers a call the
    real role must never make would hide the very mistake these tests exist to catch.
    """

    exceptions = _Exceptions

    def __init__(self, create_error: Exception | None = None) -> None:
        self.create_error = create_error
        self.calls: list = []

    def admin_create_user(self, **kwargs):
        self.calls.append(("admin_create_user", kwargs))
        if self.create_error is not None:
            raise self.create_error
        return {"User": {"Username": kwargs["Username"]}}

    def admin_set_user_password(self, **kwargs):
        self.calls.append(("admin_set_user_password", kwargs))
        return {}

    def admin_update_user_attributes(self, **kwargs):
        self.calls.append(("admin_update_user_attributes", kwargs))
        return {}

    def admin_get_user(self, **kwargs):
        # An existing phone-keyed user without a WABA stamp. The production guard
        # must read this before it may add a stamp; a missing fake method is not
        # evidence that the real Cognito read failed.
        self.calls.append(("admin_get_user", kwargs))
        return {"Username": kwargs["Username"], "UserAttributes": []}

    def admin_add_user_to_group(self, **kwargs):
        self.calls.append(("admin_add_user_to_group", kwargs))
        return {}


@pytest.fixture
def contacts(monkeypatch):
    """`(module, table, lambda_client)` with the flag left at its default."""
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("CRM_PROVISION_CUSTOMER_LOGIN", raising=False)
    module = _load(CONTACTS_HANDLER, "contacts_login_under_test")
    table = FakeContactsTable()
    monkeypatch.setattr(module, "dynamodb", FakeContactsResource(table))
    client = RecordingLambda()
    monkeypatch.setattr(module, "_lambda_client", client)
    return module, table, client


@pytest.fixture
def secure_files(monkeypatch):
    """`(module, cognito)` for the function that holds the AdminCreateUser grant."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    module = _load(SECURE_FILES_HANDLER, "secure_files_login_under_test")
    cognito = FakeCognito()
    monkeypatch.setattr(module, "_cognito", cognito)
    return module, cognito


# ─── the flag is off by default ────────────────────────────────────────────────

def test_the_flag_defaults_off(contacts):
    module, _, _ = contacts
    assert module._customer_login_enabled() is False


def test_with_the_flag_off_a_crm_create_makes_no_invoke_at_all(contacts):
    """Not "invokes and ignores" - does not invoke. Off has to mean the behaviour of a CRM create
    is byte-for-byte what it was before this landed."""
    module, table, client = contacts
    response = module._create({"name": "Asha Sen", "phone": E164}, "req-off")
    assert response["statusCode"] == 201
    assert table.puts[0]["phone"] == E164
    assert client.invokes == []


def test_with_the_flag_off_no_lambda_client_is_even_built(monkeypatch):
    """The cold start of every CRM create must be unchanged while the flag is off, so the client
    is constructed on first USE rather than at import."""
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.delenv("CRM_PROVISION_CUSTOMER_LOGIN", raising=False)
    module = _load(CONTACTS_HANDLER, "contacts_no_client_under_test")
    table = FakeContactsTable()
    monkeypatch.setattr(module, "dynamodb", FakeContactsResource(table))

    def refuse(*_args, **_kwargs):
        raise AssertionError("a boto3 client was constructed with the flag off")

    monkeypatch.setattr(module.boto3, "client", refuse)
    assert module._create({"name": "Asha Sen", "phone": E164}, "req-noclient")[
        "statusCode"] == 201
    assert module._lambda_client is None


@pytest.mark.parametrize("value", ["", "0", "no", "False", "off", "TRUE "])
def test_only_the_word_true_turns_it_on(contacts, monkeypatch, value):
    """A flag that treats any non-empty value as on is a flag that turns itself on by typo. The
    trailing-space case is included because an environment variable commonly carries one."""
    module, _, _ = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", value)
    assert module._customer_login_enabled() is (value.strip().lower() == "true")


# ─── the flag on: exactly one invoke, carrying exactly the phone ───────────────

def test_with_the_flag_on_exactly_one_invoke_carries_the_normalised_e164(contacts, monkeypatch):
    module, table, client = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    response = module._create(
        {"name": "Asha Sen", "phone": "+91 98765-43210", "email": "asha@example.com"}, "req-on")
    assert response["statusCode"] == 201
    assert len(client.invokes) == 1
    sent = client.invokes[0]
    assert sent["InvocationType"] == "Event", "fire-and-forget; a login must not block a create"
    payload = json.loads(sent["Payload"].decode("utf-8"))
    assert payload == {"internalAction": "provisionCustomerLogin", "phone": E164}, (
        "the payload carries the normalised phone and NOTHING else - not the name, not the "
        "email, not the contact id")


def test_the_invoke_targets_the_function_that_already_holds_the_grant(contacts, monkeypatch):
    """`core/secure-files` holds `cognito-idp:AdminCreateUser` scoped to the customer pool. The
    alias is named, not `$LATEST`: 58 of 65 functions are invoked through `live` and code at
    `$LATEST` is not live."""
    module, _, client = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    module._create({"name": "Asha Sen", "phone": E164}, "req-target")
    assert client.invokes[0]["FunctionName"] == "wecare-secure-files:live"
    assert module.CUSTOMER_LOGIN_FUNCTION.endswith(":live")


def test_a_refused_phone_dispatches_nothing(contacts, monkeypatch):
    """No row, no login. A bare national number is refused before anything is written."""
    module, table, client = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    response = module._create({"name": "Asha Sen", "phone": "9876543210"}, "req-bad")
    assert response["statusCode"] == 400
    assert table.puts == []
    assert client.invokes == []


def test_an_email_only_contact_dispatches_nothing(contacts, monkeypatch):
    """The login is phone-keyed, so there is nothing to provision without a phone."""
    module, _, client = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    assert module._create({"name": "Asha Sen", "email": "asha@example.com"},
                          "req-email")["statusCode"] == 201
    assert client.invokes == []


def test_a_dispatch_failure_does_not_fail_the_create(contacts, monkeypatch):
    """The contact row is the thing the operator asked for; the login is an attachment to it."""
    module, table, _ = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    monkeypatch.setattr(module, "_lambda_client", RecordingLambda(error=RuntimeError("boom")))
    response = module._create({"name": "Asha Sen", "phone": E164}, "req-fail")
    assert response["statusCode"] == 201
    assert table.puts[0]["phone"] == E164


def test_the_dispatch_happens_after_the_row_is_written(contacts, monkeypatch):
    """Order matters: a login created for a row that then failed to write would leave a Cognito
    user with no contact behind it."""
    module, _, client = contacts
    monkeypatch.setenv("CRM_PROVISION_CUSTOMER_LOGIN", "true")
    tree = ast.parse(CONTACTS_HANDLER.read_text(encoding="utf-8"))
    create = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_create")
    rendered = ast.unparse(create)
    assert rendered.index("put_item") < rendered.index("_provision_customer_login")


def test_the_phone_reaches_the_log_masked(contacts, monkeypatch):
    """Phones are masked to the last four everywhere in this codebase. Asserted on the AST rather
    than on captured output, because the requirement is that no log EXPRESSION carries a full
    number - a test on one captured line would miss a second log site added later."""
    tree = ast.parse(CONTACTS_HANDLER.read_text(encoding="utf-8"))
    dispatch = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_provision_customer_login")
    logged = 0
    for node in ast.walk(dispatch):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "log_event":
            continue
        for keyword in node.keywords:
            if keyword.arg != "phone":
                continue
            logged += 1
            assert isinstance(keyword.value, ast.Call), "a raw phone reached a log expression"
            assert getattr(keyword.value.func, "id", None) == "mask_phone"
    assert logged == 1, "expected exactly one masked phone in the dispatch log"


# ─── the receiving side ────────────────────────────────────────────────────────

def test_the_internal_action_provisions_the_login(secure_files):
    module, cognito = secure_files
    result = module.handler({"internalAction": "provisionCustomerLogin", "phone": E164}, None)
    assert result == {"ok": True, "detail": "provisioned"}
    created = [kwargs for name, kwargs in cognito.calls if name == "admin_create_user"]
    assert len(created) == 1
    assert created[0]["Username"] == E164
    assert created[0]["MessageAction"] == "SUPPRESS", (
        "Cognito must not send an invite: these users have no email and an SMS invite would "
        "bypass the WhatsApp channel the whole flow is built on")
    names = {attr["Name"] for attr in created[0]["UserAttributes"]}
    assert "custom:partner_waba_id" in names, (
        "without the WABA stamp the OTP trigger raises PermissionError and no code arrives")
    assert any(name == "admin_set_user_password" for name, _ in cognito.calls), (
        "admin_create_user leaves the user in FORCE_CHANGE_PASSWORD, which blocks CUSTOM_AUTH")


@pytest.mark.parametrize("conflict", ["AliasExistsException", "UsernameExistsException"])
def test_a_conflict_is_treated_as_success(secure_files, monkeypatch, conflict):
    """The whole point is that a contact can be saved twice. Both exceptions mean the login this
    call was asked to guarantee already exists, so both are success - a retry must not report a
    failure an operator would then chase.

    The two are absorbed in different PLACES, and that is worth pinning rather than hiding behind
    one assertion: `_ensure_customer_user` already catches `UsernameExists` itself and refreshes
    the attributes instead, while `AliasExists` - a phone alias colliding with a DIFFERENT
    username - reaches `provision_customer_login` and is absorbed there.
    """
    module, _ = secure_files
    error = getattr(_Exceptions, conflict)("already there")
    cognito = FakeCognito(create_error=error)
    monkeypatch.setattr(module, "_cognito", cognito)
    ok, detail = module.provision_customer_login(E164)
    assert ok is True, detail
    if conflict == "UsernameExistsException":
        assert detail == "provisioned"
        names = [name for name, _ in cognito.calls]
        assert names.index("admin_get_user") < names.index("admin_update_user_attributes")
        assert any(name == "admin_update_user_attributes" for name, _ in cognito.calls), (
            "an existing user's attributes are refreshed rather than left stale")
    else:
        assert detail == "exists"


def test_an_unexpected_cognito_failure_is_reported_not_swallowed(secure_files, monkeypatch):
    module, _ = secure_files
    monkeypatch.setattr(module, "_cognito",
                        FakeCognito(create_error=RuntimeError("NotAuthorizedException")))
    ok, detail = module.provision_customer_login(E164)
    assert ok is False
    assert detail == "RuntimeError", "the type only; a Cognito message can echo the username"


@pytest.mark.parametrize("value", ["", "+", "919876", "+91987654321012345",
                                   "+91 98765 43210", "+9198765abcde", "+91987654321\u0660"])
def test_a_value_that_is_not_e164_is_refused_before_any_cognito_call(secure_files, value):
    """ASCII digits only, deliberately: `str.isdigit()` is true for an Arabic-Indic digit, which
    would reach `Username` and reserve an identity indistinguishable to a human from the real
    one. The caller always sends an already-normalised value, so this is a guard, not a parser."""
    module, cognito = secure_files
    ok, _ = module.provision_customer_login(value)
    assert ok is False
    assert cognito.calls == []


def test_an_http_caller_cannot_reach_the_internal_action(secure_files):
    """Keyed on the ABSENCE of a requestContext, which API Gateway always supplies. The branch
    falls through to normal routing, which authenticates."""
    module, cognito = secure_files
    module.handler({
        "internalAction": "provisionCustomerLogin",
        "phone": E164,
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"origin": "http://localhost:3000"},
    }, None)
    assert cognito.calls == [], "an HTTP-shaped event must not provision anything"


# ─── no pool-level write, and no widened role ──────────────────────────────────

def _forbidden_spellings() -> tuple:
    """The pool-replace API's identifier, assembled at runtime.

    Spelled this way so that this file does not contain the literal it forbids - otherwise the
    guard trips on its own source, and the usual response to that is to weaken the guard.
    """
    parts = ("update", "user", "pool")
    return ("_".join(parts), "-".join(parts), "".join(parts))


def _identifiers_and_live_strings(path: pathlib.Path) -> set:
    """Every identifier and every non-docstring string constant in a module.

    AST rather than text, because the comments and docstrings in these files explain the
    2026-09-28 incident by name and necessarily mention the API they forbid. A text search would
    report the documentation as the behaviour.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            docstrings.add(id(first.value))

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            found.add(node.value)
    return found


@pytest.mark.parametrize("path", CHANGED_PYTHON, ids=lambda p: p.name)
def test_no_changed_file_performs_a_pool_level_write(path):
    """THE GUARDRAIL. A partial pool update returns 200 and silently resets every field it was
    not given: on 2026-09-28 that cleared three auth triggers and opened self-signup on this very
    customer pool. If a pool-level setting ever has to change it goes through
    `scripts/cognito_pool_safe_update.py --apply` and nothing else.
    """
    tokens = {value.lower() for value in _identifiers_and_live_strings(path)}
    for spelling in _forbidden_spellings():
        assert not any(spelling in token for token in tokens), (
            f"{path.name} reaches the pool-replace API; it must not")


def test_the_safe_updater_is_the_only_route_to_a_pool_level_change():
    """Stated as a test so the alternative is discoverable rather than folklore."""
    assert (ROOT / "scripts/cognito_pool_safe_update.py").exists()


def test_admin_create_user_only_stays_true_in_the_safe_updater():
    """Self-signup on the public customer pool is what the 2026-09-28 call opened."""
    code = (ROOT / "scripts/cognito_pool_safe_update.py").read_text(encoding="utf-8")
    assert "AllowAdminCreateUserOnly" in code


def test_the_crm_handler_holds_no_cognito_capability_at_all():
    """The CRM's role is NOT widened - and the proof that matters offline is that the capability
    is absent from the function. `core/contacts` builds a Lambda client and nothing else; the
    Cognito call lives in the one function already provisioned for it.
    """
    tokens = {value.lower() for value in _identifiers_and_live_strings(CONTACTS_HANDLER)}
    assert not any("cognito" in token for token in tokens)
    assert not any("admin_create_user" in token for token in tokens)
    assert "lambda" in tokens, "it does build a Lambda client, which is the whole mechanism"


def test_the_crm_environment_names_no_user_pool():
    """A pool id in this function's environment would be the first sign the grant moved here."""
    manifest = json.loads(ENV_MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["functions"]["wecare-contacts"]
    assert entry["CRM_PROVISION_CUSTOMER_LOGIN"] == "false", "the deployed default must be off"
    assert entry["CUSTOMER_LOGIN_FUNCTION"] == "wecare-secure-files:live"
    for key, value in entry.items():
        assert "POOL" not in key.upper(), key
        assert not str(value).startswith("us-east-1_"), f"{key} looks like a user pool id"


def test_the_grant_this_feature_relies_on_is_still_scoped_to_the_customer_pool():
    """The invoke is only safe because the receiving role cannot touch the ADMIN pool. Asserted
    on the provisioner; whether the live role matches it is an owner-side read, recorded in the
    FEAT findings, and must be done before the flag is flipped.
    """
    code = SECURE_FILES_PROVISION.read_text(encoding="utf-8")
    assert "cognito-idp:AdminCreateUser" in code
    assert "CustomerPoolOnly" in code
    assert "us-east-1_46ULYuukt" in code
    assert "cognito-idp:AdminDeleteUser" not in code, "nothing here needs to delete a user"
