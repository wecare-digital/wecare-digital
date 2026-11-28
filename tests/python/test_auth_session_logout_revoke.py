"""CA-7: sign-out revokes the session's refresh token at Cognito, failing soft."""
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lambda_utils import customer_session as sessions

HANDLER = Path(__file__).resolve().parents[2] / "amplify/functions/ecommerce/customer-session/handler.py"
ORIGIN = "https://wecare.digital"


class MemoryStore:
    """The SessionStore interface over a dict."""

    def __init__(self):
        self.rows = {}

    def put_session(self, row):
        assert row["sidHash"] not in self.rows
        self.rows[row["sidHash"]] = dict(row)

    def get_session(self, key):
        row = self.rows.get(key)
        return dict(row) if row else None

    def touch_session(self, key, *, last_seen_at, idle_expires_at):
        self.rows[key].update(lastSeenAt=last_seen_at, idleExpiresAt=idle_expires_at)

    def revoke_session(self, key, *, revoked_at):
        self.rows[key]["revokedAt"] = revoked_at
        self.rows[key].pop("refreshRef", None)


def test_revoke_hands_the_sealed_reference_to_the_callback_after_marking_revoked():
    store = MemoryStore()
    opaque, _ = sessions.create_session(store, customer_id="c1", refresh_ref="sealed-ref")
    seen = []

    def revoke_refresh(ref):
        row, = store.rows.values()
        seen.append((ref, bool(row.get("revokedAt"))))

    sessions.revoke(store, opaque, revoke_refresh=revoke_refresh)
    assert seen == [("sealed-ref", True)]


def test_a_failed_cognito_revoke_still_signs_out():
    store = MemoryStore()
    opaque, _ = sessions.create_session(store, customer_id="c1", refresh_ref="sealed-ref")

    def unavailable(ref):
        raise RuntimeError("cognito unavailable")

    sessions.revoke(store, opaque, revoke_refresh=unavailable)
    row, = store.rows.values()
    assert row["revokedAt"] and "refreshRef" not in row
    with pytest.raises(sessions.SessionInvalid):
        sessions.validate(store, opaque)


def test_unknown_or_already_revoked_sessions_revoke_nothing_at_cognito():
    store = MemoryStore()
    opaque, _ = sessions.create_session(store, customer_id="c1", refresh_ref="sealed-ref")
    calls = []
    sessions.revoke(store, sessions.new_opaque_id(), revoke_refresh=calls.append)
    sessions.revoke(store, opaque, revoke_refresh=calls.append)
    sessions.revoke(store, opaque, revoke_refresh=calls.append)
    assert calls == ["sealed-ref"]


class FakeKms:
    def encrypt(self, *, KeyId, Plaintext, EncryptionContext):
        return {"CiphertextBlob": b"sealed:" + Plaintext}

    def decrypt(self, *, KeyId, CiphertextBlob, EncryptionContext):
        assert CiphertextBlob.startswith(b"sealed:")
        return {"Plaintext": CiphertextBlob[len(b"sealed:"):]}


class FakeCognito:
    def __init__(self, fail_revoke=False):
        self.calls = []
        self.fail_revoke = fail_revoke

    def revoke_token(self, **kwargs):
        self.calls.append(("revoke_token", kwargs))
        if self.fail_revoke:
            raise RuntimeError("cognito unavailable")
        return {}

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            raise AssertionError(f"unexpected Cognito call {name}")
        return call


@pytest.fixture
def session_handler(monkeypatch):
    spec = importlib.util.spec_from_file_location("customer_session_logout", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("CUSTOMER_SESSIONS_TABLE", "sessions")
    monkeypatch.setenv("CUSTOMER_SESSION_KMS_KEY_ID", "key")
    store = MemoryStore()
    state = SimpleNamespace(store=store, cognito=FakeCognito(), kms=FakeKms())
    monkeypatch.setattr(module, "SessionStore", lambda table: store)
    monkeypatch.setattr(module, "boto3", SimpleNamespace(
        resource=lambda name: SimpleNamespace(Table=lambda table_name: object()),
        client=lambda name: {"kms": state.kms, "cognito-idp": state.cognito}[name]))
    module.state = state
    return module


def _logout(module, opaque, csrf):
    return module.handler({
        "headers": {"origin": ORIGIN, "x-customer-csrf": csrf},
        "cookies": [f"{sessions.COOKIE_NAME}={opaque}"],
        "body": json.dumps({"action": "logout"}),
    }, None)


@pytest.mark.parametrize("fail_revoke", [False, True])
def test_logout_revokes_the_refresh_token_and_always_signs_out(session_handler, fail_revoke):
    state = session_handler.state
    state.cognito.fail_revoke = fail_revoke
    sealed = base64.b64encode(b"sealed:refresh-token-value").decode()
    opaque, view = sessions.create_session(state.store, customer_id="c1", refresh_ref=sealed)
    reply = _logout(session_handler, opaque, view.csrf_token)
    assert reply["statusCode"] == 200 and json.loads(reply["body"]) == {"signedOut": True}
    assert reply["cookies"] == [sessions.build_clear_cookie()]
    assert state.cognito.calls == [("revoke_token", {"Token": "refresh-token-value",
                                                     "ClientId": session_handler.CLIENT_ID})]
    row, = state.store.rows.values()
    assert row["revokedAt"] and "refreshRef" not in row


def test_logout_without_csrf_revokes_nothing(session_handler):
    state = session_handler.state
    opaque, _ = sessions.create_session(state.store, customer_id="c1",
                                        refresh_ref=base64.b64encode(b"sealed:t").decode())
    reply = _logout(session_handler, opaque, "wrong")
    assert reply["statusCode"] == 403 and state.cognito.calls == []
    row, = state.store.rows.values()
    assert not row.get("revokedAt")
