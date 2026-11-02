"""Behavioural tests for the pure helpers in lambda_utils.customer_auth.

Only the functions that do NOT touch Cognito are exercised: bearer_token,
is_cognito_subject, customer_id_from_attributes and _unverified_issuer.
authenticate()/_client() need a live Cognito pool and are deliberately not called.

The is_cognito_subject tests are the load-bearing ones: that predicate is the
ListUsers-filter injection defence, so it must refuse uppercase, malformed,
non-string and injection-looking input. _unverified_issuer is fed a hand-built
UNSIGNED JWT (no secret, synthetic issuer) so no real token is used.
"""

import base64
import json

from lambda_utils import customer_auth
from lambda_utils.customer_auth import (
    bearer_token,
    customer_id_from_attributes,
    is_cognito_subject,
)

# A synthetic canonical lowercase UUID (not a real Cognito sub).
VALID_SUB = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


def _b64url(obj):
    raw = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unsigned_jwt(payload):
    header = _b64url({"alg": "none", "typ": "JWT"})
    body = _b64url(payload)
    return f"{header}.{body}."


# --- bearer_token ----------------------------------------------------------

def test_bearer_token_strips_scheme_v1_casing():
    event = {"headers": {"Authorization": "Bearer abc.def.ghi"}}
    assert bearer_token(event) == "abc.def.ghi"


def test_bearer_token_is_case_insensitive_on_header_name_and_scheme():
    # API Gateway v2 lowercases header names; the scheme casing varies too.
    event = {"headers": {"authorization": "bearer tok123"}}
    assert bearer_token(event) == "tok123"


def test_bearer_token_accepts_bare_token():
    event = {"headers": {"authorization": "baretoken"}}
    assert bearer_token(event) == "baretoken"


def test_bearer_token_empty_when_absent():
    assert bearer_token({"headers": {}}) == ""
    assert bearer_token({}) == ""


# --- is_cognito_subject ----------------------------------------------------

def test_is_cognito_subject_accepts_canonical_lowercase_uuid():
    assert is_cognito_subject(VALID_SUB) is True


def test_is_cognito_subject_refuses_uppercase():
    # Cognito mints sub lowercase; uppercase is not a sub this pool issued.
    assert is_cognito_subject(VALID_SUB.upper()) is False


def test_is_cognito_subject_refuses_malformed_and_non_string():
    assert is_cognito_subject("not-a-uuid") is False
    assert is_cognito_subject("") is False
    assert is_cognito_subject(None) is False
    assert is_cognito_subject(12345) is False


def test_is_cognito_subject_refuses_injection_looking_values():
    # The ListUsers-filter defence: a value that would break out of
    # Filter='sub = "..."' must be refused before it reaches Cognito.
    assert is_cognito_subject(f'{VALID_SUB}" or "1"="1') is False
    assert is_cognito_subject(f"{VALID_SUB}\nextra") is False
    assert is_cognito_subject(f" {VALID_SUB} ") is False


# --- customer_id_from_attributes -------------------------------------------

def test_customer_id_from_attributes_returns_sub():
    assert customer_id_from_attributes({"sub": VALID_SUB}) == VALID_SUB


def test_customer_id_from_attributes_empty_when_absent():
    # Never invents an id.
    assert customer_id_from_attributes({}) == ""
    assert customer_id_from_attributes({"sub": None}) == ""


# --- _unverified_issuer ----------------------------------------------------

def test_unverified_issuer_decodes_iss_claim():
    issuer = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_EXAMPLE"
    token = _unsigned_jwt({"iss": issuer, "sub": VALID_SUB})
    assert customer_auth._unverified_issuer(token) == issuer


def test_unverified_issuer_empty_on_malformed_token():
    assert customer_auth._unverified_issuer("not-a-jwt") == ""
    assert customer_auth._unverified_issuer("") == ""
