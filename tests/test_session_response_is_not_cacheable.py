"""A session or OTP response must never be cacheable (Finding 2 of the 2026-10-01 audit).

What this defends, and why it is not merely defensive
-----------------------------------------------------
`lambda_utils/response.py::cors_headers` sets `Content-Type` and three CORS headers and **no**
`Cache-Control`. The responses it builds for the auth doors travel through the Amplify `/api/<*>`
status-200 rewrite, so a shared cache sits in front of them. The session responses in particular
carry `SessionView.csrf_token` in the BODY, and that token is what `build_set_cookie`'s deliberate
`SameSite=Lax` choice relies on to guard the mutations Lax still permits - so a cache that served
one customer's response to another would not weaken the CSRF defence, it would remove it.

`response.py` is deliberately NOT changed: `core/contacts/handler.py:285` removed `Cache-Control`
there on purpose, so a blanket header would override a considered decision in an unrelated handler.
The contract lives in `customer_session.harden_session_headers` and each owning handler opts in.

Three groups of tests:
  1. the helper itself - both headers present, input preserved, input not mutated;
  2. a structural guard over the two handlers we own, asserting that EVERY return of a response
     builder is wrapped. A behavioural test can only reach the paths it can provoke; the audit
     finding is about *every* return path, so the guard walks the AST instead;
  3. behavioural proof on the paths reachable with no AWS at all, plus the forward-looking tripwire
     that a response body carrying `csrfToken` cannot be built in a module that does not harden.
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils import customer_session  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_REGISTRATION = _ROOT / "amplify/functions/auth/customer-registration/handler.py"
_EMAIL_VERIFICATION = _ROOT / "amplify/functions/auth/email-verification/handler.py"
#: The customer order-history read. Added here because its 200 is a per-customer order list and
#: its 401 is a per-customer denial, and `cors_headers` sets no cache directive on either - so a
#: shared cache in front of the Amplify `/api/<*>` rewrite could replay one customer's history to
#: another. Its own module docstring records why the route is POST for the same reason.
_CUSTOMER_ORDERS = _ROOT / "amplify/functions/ecommerce/customer-orders/handler.py"

#: The builders whose results reach the client. `throttled_response` is in the list because it is
#: built by `otp_throttle`, not by `cors_response` - a cached 429 would misreport another caller's
#: remaining budget, so it needs the header exactly as much as a 200 does.
_RESPONSE_BUILDERS = {"cors_response", "options_response", "error_response", "throttled_response"}
#: The wrapper each owned handler defines locally.
_WRAPPER = "_no_store"


# ── 1. the helper ────────────────────────────────────────────────────────────────

def test_the_helper_emits_both_headers():
    assert customer_session.harden_session_headers() == {
        "Cache-Control": "no-store", "Pragma": "no-cache"}


def test_the_constant_is_the_pair_the_repo_already_uses():
    # edge/get-miss-redirect/handler.py:83 emits exactly this pair; ai/mcp and core/site-language
    # emit `no-store` alone. The stricter existing pattern is the one copied.
    assert customer_session.NO_STORE_HEADERS == {
        "Cache-Control": "no-store", "Pragma": "no-cache"}


def test_it_preserves_whatever_it_was_handed():
    given = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "https://wecare.digital",
        "Set-Cookie": "wd_csid=opaque; Path=/; HttpOnly; Secure; SameSite=Lax",
    }
    out = customer_session.harden_session_headers(given)
    for key, value in given.items():
        assert out[key] == value
    assert out["Cache-Control"] == "no-store"


def test_it_does_not_mutate_its_input():
    given = {"Content-Type": "application/json"}
    customer_session.harden_session_headers(given)
    assert given == {"Content-Type": "application/json"}


def test_a_weaker_cache_control_loses():
    # A session response with `max-age` is a bug, not a caller preference, so no-store wins.
    out = customer_session.harden_session_headers({"Cache-Control": "public, max-age=300"})
    assert out["Cache-Control"] == "no-store"


def test_both_names_are_exported():
    assert "NO_STORE_HEADERS" in customer_session.__all__
    assert "harden_session_headers" in customer_session.__all__


# ── 2. the structural guard: EVERY return path, not only the reachable ones ───────

def _returned_response_calls(source_path: Path):
    """Every `return <call>` in the module whose callee is a response builder or the wrapper.

    Yields `(function_name, line, callee_name, wrapped)`. Walking the AST rather than grepping is
    the established pattern here (see tests/test_payment_vocabulary_at_decision_points.py): the
    explanatory docstrings in these handlers legitimately mention `cors_response` by name.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
                continue
            callee = node.value.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(
                callee, "id", "")
            if name == _WRAPPER:
                inner = node.value.args[0] if node.value.args else None
                inner_name = ""
                if isinstance(inner, ast.Call):
                    inner_callee = inner.func
                    inner_name = (inner_callee.attr if isinstance(inner_callee, ast.Attribute)
                                  else getattr(inner_callee, "id", ""))
                yield func.name, node.lineno, inner_name, True
            elif name in _RESPONSE_BUILDERS:
                yield func.name, node.lineno, name, False


@pytest.mark.parametrize("source_path", [_REGISTRATION, _EMAIL_VERIFICATION, _CUSTOMER_ORDERS],
                         ids=["customer-registration", "email-verification", "customer-orders"])
def test_every_returned_response_is_hardened(source_path):
    unwrapped = [(fn, line, callee)
                 for fn, line, callee, wrapped in _returned_response_calls(source_path)
                 if not wrapped]
    assert unwrapped == [], (
        f"{source_path.name}: these return paths bypass {_WRAPPER} and would be cacheable: "
        f"{unwrapped}")


@pytest.mark.parametrize("source_path", [_REGISTRATION, _EMAIL_VERIFICATION, _CUSTOMER_ORDERS],
                         ids=["customer-registration", "email-verification", "customer-orders"])
def test_the_guard_actually_found_something(source_path):
    # A guard that silently matches nothing proves nothing. Both handlers return several responses;
    # if this count ever drops to zero the walker has stopped seeing them.
    found = list(_returned_response_calls(source_path))
    assert len(found) >= 5
    assert all(callee in _RESPONSE_BUILDERS for _, _, callee, _ in found)


@pytest.mark.parametrize("source_path", [_REGISTRATION, _EMAIL_VERIFICATION, _CUSTOMER_ORDERS],
                         ids=["customer-registration", "email-verification", "customer-orders"])
def test_the_wrapper_goes_through_the_shared_contract(source_path):
    # The header pair is defined once, in customer_session. A handler that hard-coded the strings
    # would drift the day the contract changes.
    source = source_path.read_text(encoding="utf-8")
    assert "harden_session_headers" in source
    assert '"Cache-Control"' not in source and "'Cache-Control'" not in source


def test_response_py_is_not_the_place_this_was_fixed():
    # Pinned deliberately: core/contacts/handler.py:285 removed Cache-Control on purpose, so a
    # blanket header in the shared builder would override an unrelated considered decision.
    shared = (_ROOT / "amplify/functions/shared/lambda_utils/response.py").read_text(
        encoding="utf-8")
    assert "Cache-Control" not in shared


# ── 3. behavioural proof + the csrfToken tripwire ────────────────────────────────

def _load(path: Path, name: str, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _assert_no_store(response):
    headers = response["headers"]
    assert headers["Cache-Control"] == "no-store"
    assert headers["Pragma"] == "no-cache"
    # The CORS contract survives the merge.
    assert headers["Content-Type"] == "application/json"
    assert "Access-Control-Allow-Origin" in headers


@pytest.mark.parametrize("path,name", [
    (_REGISTRATION, "registration_no_store_under_test"),
    (_EMAIL_VERIFICATION, "email_verification_no_store_under_test"),
], ids=["customer-registration", "email-verification"])
def test_the_preflight_response_is_uncacheable(path, name, monkeypatch):
    module = _load(path, name, monkeypatch)
    response = module.handler({"requestContext": {"http": {"method": "OPTIONS"}}}, None)
    assert response["statusCode"] == 200
    _assert_no_store(response)


def test_a_rejected_registration_verify_is_uncacheable(monkeypatch):
    # Reachable with no AWS at all: the missing-code check precedes every client construction.
    module = _load(_REGISTRATION, "registration_no_store_verify", monkeypatch)
    response = module.handler(
        {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/auth/register/verify",
         "body": '{"phone": "+919330994400"}'}, None)
    assert response["statusCode"] == 400
    _assert_no_store(response)


def test_a_rejected_email_verification_is_uncacheable(monkeypatch):
    module = _load(_EMAIL_VERIFICATION, "email_verification_no_store_invalid", monkeypatch)
    response = module.handler(
        {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/email/verify",
         "body": '{"email": "not-an-address"}'}, None)
    assert response["statusCode"] == 400
    _assert_no_store(response)


@pytest.mark.parametrize("path,name", [
    (_REGISTRATION, "registration_no_store_error"),
    (_EMAIL_VERIFICATION, "email_verification_no_store_error"),
], ids=["customer-registration", "email-verification"])
def test_the_internal_error_response_is_uncacheable(path, name, monkeypatch):
    module = _load(path, name, monkeypatch)
    monkeypatch.setattr(module, "_request", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("boom")))
    response = module.handler(
        {"requestContext": {"http": {"method": "POST"}}, "body": "{}"}, None)
    assert response["statusCode"] == 500
    _assert_no_store(response)


def _modules_returning_a_csrf_token():
    """Every amplify handler whose source builds a body with a `csrfToken` key."""
    offenders = []
    for path in sorted((_ROOT / "amplify/functions").rglob("handler.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if _mentions_csrf_token_key(source) and "harden_session_headers" not in source:
            offenders.append(str(path.relative_to(_ROOT)))
    return offenders


def _mentions_csrf_token_key(source: str) -> bool:
    """True when the source contains a `csrfToken` string literal - a response-body key.

    Compares string CONSTANTS from the AST, not the raw text, so a comment or docstring explaining
    this rule (which necessarily names the key) is not itself a hit. Same reason
    tests/test_payment_vocabulary_at_decision_points.py walks the AST.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - a handler that does not parse fails elsewhere
        return False
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value not in docstrings and "csrfToken" in node.value):
            return True
    return False


def test_no_handler_returns_a_csrf_token_without_the_no_store_contract():
    # Forward-looking tripwire. Today it matches nothing: no handler imports customer_session for
    # its session view yet (tests/test_checkout_package_completeness.py:42 records that the module
    # "ships ahead"). The moment one returns a csrfToken it must harden the response, which is the
    # single header the audit found missing.
    assert _modules_returning_a_csrf_token() == []


def test_the_csrf_tripwire_detects_what_it_claims_to():
    # Positive control: a guard that cannot fail is not a guard.
    assert _mentions_csrf_token_key('body = {"csrfToken": view.csrf_token}') is True
    # And it is not fooled by prose about the rule.
    assert _mentions_csrf_token_key('"""Never return csrfToken uncached."""\nx = 1') is False
