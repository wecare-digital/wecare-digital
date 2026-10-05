"""`wecare-wix-catalog-webhook`: a verified Wix event rebuilds, an unverified one does not.

Design reference: `.agents/tasks/wix-catalog-auto-sync-b2.md` step 3 and
`docs/wix-catalogue-auto-sync.md`.

THE PROPERTY UNDER TEST IS A CONJUNCTION, and both halves are needed:

    valid signature    -> a GitHub repository_dispatch is sent
    anything else      -> 401, EMPTY body, and NO dispatch at all

The second half is the one worth the file. An endpoint that rebuilds production on an
unauthenticated POST is a free denial-of-wallet: each call starts an Amplify build. So every
rejection case below asserts the dispatch was NOT attempted, not merely that the status was 401 -
a verifier that refuses the caller after already firing the trigger would pass a status-only test.

A REAL KEYPAIR, NOT A MOCK. The whole value of this module is that a signature verifies or does
not, and a stub that returns what it is told proves nothing about that. `cryptography` signs here
with the same primitives the verifier checks with, so the wrong-key and `alg`-confusion cases are
genuine cryptographic refusals.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import wix_webhook  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wix_webhook.py"
HANDLER = ROOT / "amplify/functions/ecommerce/wix-catalog-webhook/handler.py"


def _load_receiver():
    """Load the handler BY PATH under a unique module name, never `import handler`.

    This repo has 64 files called `handler.py`, so `sys.modules["handler"]` is one slot
    contended by all of them - and a module-level `import handler` runs at COLLECTION time,
    before `conftest.isolate_handler_imports` exists, binding whichever got there first.

    This was not a theoretical risk here: the first run of this file bound
    `amplify/functions/operations/seo-tools/handler.py` and eleven tests failed on
    `AttributeError: module 'handler' has no attribute '_read_secret'`. A unique module name
    removes the shared key entirely, so this file neither depends on nor affects collection
    order. `tests/test_handler_import_isolation.py` is the gate that caught it.
    """
    spec = importlib.util.spec_from_file_location(
        "wecare_wix_catalog_webhook_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["wecare_wix_catalog_webhook_handler"] = module
    spec.loader.exec_module(module)
    return module


receiver = _load_receiver()

#: A Wix application id is a public identifier, not a credential.
APP_ID = "197cd718-e4ec-4e2e-b380-46c297eb18a2"
INSTANCE_ID = "99999999-8888-4777-8666-555555555555"

NOW = 1_700_000_000


@pytest.fixture(scope="module")
def keys():
    """One RSA keypair, a second RSA keypair to be the WRONG key, and an EC key.

    The EC key covers the case where a correctly-formed PEM is the wrong KIND of key for the
    declared `alg` - `cryptography` raises something other than `InvalidSignature` there, and that
    path has to end in a refusal rather than a 500.
    """
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    curve = ec.generate_private_key(ec.SECP256R1())
    pem = lambda key: key.public_key().public_bytes(  # noqa: E731
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return {"private": private, "other": other,
            "public_pem": pem(private), "other_public_pem": pem(other),
            "ec_public_pem": pem(curve)}


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def envelope(event_type: str = "wix.stores.catalog.v3.product_created",
             slug: str = "a-new-product", entity_id: str = "prod-1") -> str:
    """Wix's own shape: `data` is a JSON STRING, whose `data` is a JSON string again."""
    return json.dumps({
        "instanceId": INSTANCE_ID,
        "eventType": event_type,
        "entityId": entity_id,
        "data": json.dumps({"id": entity_id, "slug": slug, "name": "A New Product"}),
    })


def claims(**overrides) -> dict:
    payload = {
        "iss": "wix.com",
        "aud": APP_ID,
        "iat": NOW - 5,
        "exp": NOW + 300,
        "data": envelope(),
    }
    payload.update(overrides)
    return payload


def token(keys, payload: dict | None = None, *, alg: str = "RS256",
          sign_with: str = "private", header_extra: dict | None = None) -> str:
    """A signed JWT. `alg` goes in the header AND selects the hash, so the two cannot disagree."""
    head = {"alg": alg, "typ": "JWT"}
    head.update(header_extra or {})
    body = claims() if payload is None else payload
    signing_input = f"{b64(json.dumps(head).encode())}.{b64(json.dumps(body).encode())}"
    hash_for = {"RS256": hashes.SHA256(), "RS384": hashes.SHA384(),
                "RS512": hashes.SHA512()}.get(alg, hashes.SHA256())
    signature = keys[sign_with].sign(
        signing_input.encode("ascii"), padding.PKCS1v15(), hash_for)
    return f"{signing_input}.{b64(signature)}"


def reader_for(public_pem: str, *, app_id: str | None = APP_ID):
    """A secret reader returning the configured public key, and the github token when asked."""
    secret = {wix_webhook.PUBLIC_KEY_FIELD: public_pem}
    if app_id is not None:
        secret[wix_webhook.APP_ID_FIELD] = app_id

    def read(secret_id: str):
        if secret_id == wix_webhook.SECRET_ID:
            return secret
        if secret_id == receiver.GITHUB_SECRET_ID:
            return {receiver.GITHUB_TOKEN_FIELD: "ghp-not-a-real-token-value"}
        raise AssertionError(f"unexpected secret read: {secret_id}")

    return read


class Dispatches:
    """Records every outbound dispatch. `calls == []` is the assertion that matters."""

    def __init__(self, status: int = 204):
        self.calls: list[dict] = []
        self.status = status

    def __call__(self, request, timeout=None):
        self.calls.append({
            "url": request.full_url,
            "method": request.get_method(),
            "body": json.loads(request.data.decode("utf-8")),
            "timeout": timeout,
        })
        status = self.status

        class Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        Response.status = status
        return Response()


# ── 1. the happy path ─────────────────────────────────────────────────────────


def test_a_validly_signed_product_event_verifies(keys):
    verified = wix_webhook.verify_signature(
        token(keys), now=NOW, reader=reader_for(keys["public_pem"]))
    assert verified.event_type == "wix.stores.catalog.v3.product_created"
    assert verified.slug == "a-new-product"
    assert verified.entity_id == "prod-1"
    assert verified.instance_id == INSTANCE_ID


def test_every_allowed_algorithm_verifies(keys):
    for alg in sorted(wix_webhook.ALLOWED_ALGORITHMS):
        verified = wix_webhook.verify_signature(
            token(keys, alg=alg), now=NOW, reader=reader_for(keys["public_pem"]))
        assert verified.event_type.endswith("product_created"), alg


def test_a_base64_encoded_body_is_decoded_before_the_shape_check(keys):
    raw = base64.b64encode(token(keys).encode("ascii")).decode("ascii")
    verified = wix_webhook.verify_signature(
        raw, now=NOW, reader=reader_for(keys["public_pem"]), is_base64_encoded=True)
    assert verified.slug == "a-new-product"


# ── 1a. the body shapes a JWT can arrive in ──────────────────────────────────
#
# Measured against the deployed endpoint on 2026-10-05, not assumed. A BARE JWT body already
# reached signature verification through both `https://wecare.digital/api/wix-catalog-webhook`
# (the Amplify `/api/<*>` rewrite) and the execute-api host - so the Amplify proxy passes a POST
# body through intact and there was nothing to fix there. A JSON-QUOTED body was the one shape
# that reproduced the live symptom, `"the request body is not a three-segment JWT"`, exactly.


def test_a_bare_jwt_body_is_the_shape_that_already_worked(keys):
    """The control for the case below. The deployed endpoint accepts this today."""
    assert wix_webhook.token_from_body(token(keys)) == token(keys)


def test_a_json_quoted_jwt_body_verifies(keys):
    """`"eyJ...sig"`, quotes included - the shape Wix's own JS examples `JSON.parse` first.

    Signature verification is untouched by the unwrapping: the token still has to be signed by the
    private half of the configured public key, which is why accepting one more wrapping widens
    what is parsed and not what is trusted.
    """
    verified = wix_webhook.verify_signature(
        json.dumps(token(keys)), now=NOW, reader=reader_for(keys["public_pem"]))
    assert verified.event_type == "wix.stores.catalog.v3.product_created"
    assert verified.slug == "a-new-product"


def test_a_json_quoted_body_is_unwrapped_only_when_what_comes_out_is_a_jwt(keys):
    """The narrowness IS the security property.

    `_unquote_json_token` accepts exactly one wrapping and only when the result is already three
    base64url segments. It does not parse arbitrary JSON and hunt for a token-shaped field, so a
    quoted non-token, an object and an array are all returned unchanged and refused with the
    existing reason.
    """
    for body in ['"not-a-jwt"', '{"jwt": "a.b.c"}', '["a.b.c"]', '"a.b"', '""', '"a.b.c.d"']:
        with pytest.raises(wix_webhook.WixWebhookUnauthorized):
            wix_webhook.verify_signature(
                body, now=NOW, reader=reader_for(keys["public_pem"]))


def test_a_quoted_jwt_that_is_also_base64_encoded_verifies(keys):
    """Both unwrappings compose, in the documented order: base64 first, then the quotes."""
    quoted = json.dumps(token(keys))
    raw = base64.b64encode(quoted.encode("ascii")).decode("ascii")
    verified = wix_webhook.verify_signature(
        raw, now=NOW, reader=reader_for(keys["public_pem"]), is_base64_encoded=True)
    assert verified.slug == "a-new-product"


def test_a_quoted_but_wrongly_signed_token_is_still_refused(keys):
    """Unwrapping must not become a bypass: the signature check runs on the unwrapped token."""
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            json.dumps(token(keys, sign_with="other")), now=NOW,
            reader=reader_for(keys["public_pem"]))


# ── 2. the refusals ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    None,
    "",
    "   ",
    "not-a-jwt",
    "only.two",
    "a.b.c.d",
    "..",
    "eyJ.eyJ.",                       # an empty signature segment
    "ey!.ey!.sig",                    # not base64url
    123,
    {"body": "object"},
])
def test_a_body_that_is_not_a_jwt_is_refused(keys, body):
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            body, now=NOW, reader=reader_for(keys["public_pem"]))


def test_a_token_signed_by_the_wrong_key_is_refused(keys):
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            token(keys, sign_with="other"), now=NOW,
            reader=reader_for(keys["public_pem"]))


def test_a_tampered_payload_is_refused(keys):
    original = token(keys)
    head, _, signature = original.split(".")
    forged = b64(json.dumps(claims(data=envelope(slug="attacker-product"))).encode())
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            f"{head}.{forged}.{signature}", now=NOW,
            reader=reader_for(keys["public_pem"]))


@pytest.mark.parametrize("alg", ["none", "None", "HS256", "HS512", "RS1", "ES256", "", "PS256"])
def test_an_algorithm_outside_the_allowlist_is_refused(keys, alg):
    """`none` and every HMAC in one refusal.

    The HMAC case is the textbook key-confusion attack and its worst form: the "secret" would be
    the PUBLIC key, which the attacker also holds. The allowlist is the decision and the token
    does not get a vote - so this is checked BEFORE the key is even read.
    """
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims()).encode())
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            f"{head}.{body}.{b64(b'signature')}", now=NOW,
            reader=reader_for(keys["public_pem"]))


def test_the_algorithm_is_refused_before_the_key_is_read(keys):
    """So a bad `alg` cannot even cost a Secrets Manager call, let alone a verification."""
    reads: list[str] = []

    def read(secret_id: str):
        reads.append(secret_id)
        return {wix_webhook.PUBLIC_KEY_FIELD: keys["public_pem"]}

    head = b64(json.dumps({"alg": "HS256"}).encode())
    body = b64(json.dumps(claims()).encode())
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            f"{head}.{body}.{b64(b'x')}", now=NOW, reader=read)
    assert reads == []


def test_a_non_wix_issuer_is_refused(keys):
    """A token that DECLARES an issuer must name Wix. `None` is a declaration, not an absence.

    `{"iss": null}` is the interesting member of this list: `payload.get("iss")` cannot tell it
    from a token with no `iss` key at all, and the two must land on opposite sides. A token that
    carried the field and failed to fill it in is refused; see the test below for the absent case.
    """
    for issuer in ["wix.co", "notwix.com", "", None, "WIX.COM", 123, ["wix.com"],
                   {"iss": "wix.com"}, "https://wix.com"]:
        with pytest.raises(wix_webhook.WixWebhookUnauthorized):
            wix_webhook.verify_signature(
                token(keys, claims(iss=issuer)), now=NOW,
                reader=reader_for(keys["public_pem"]))


def test_a_token_with_NO_iss_claim_verifies(keys):
    """THE REGRESSION TEST. The real Wix webhook envelope carries no `iss` at all.

    Measured 2026-10-05 against live deliveries to `wecare-wix-catalog-webhook`: Wix began
    delivering genuinely signed events, every one passed signature verification against the
    configured public key, and every one was then refused with "the token issuer is not Wix"
    because this module required the exact string `wix.com` - a value taken from the legacy
    app-instance token shape rather than from a delivery.

    Wix's documented verification agrees: `webhooks.process` in the official JavaScript SDK, and
    the documented manual equivalent `jwt.decode(body, public_key, algorithms=["RS256"])`, check
    the signature and the expiry and assert no issuer at all.

    The fixture is the real shape - `data`, `iat`, `exp` and nothing else - so this fails again if
    anyone restores an unconditional issuer requirement.
    """
    payload = {"iat": NOW - 5, "exp": NOW + 300, "data": envelope()}
    assert "iss" not in payload
    verified = wix_webhook.verify_signature(
        token(keys, payload), now=NOW, reader=reader_for(keys["public_pem"], app_id=None))
    assert verified.event_type == "wix.stores.catalog.v3.product_created"
    assert verified.slug == "a-new-product"
    assert verified.instance_id == INSTANCE_ID


def test_a_token_with_no_iss_still_has_to_be_signed_by_the_configured_key(keys):
    """Accepting an absent issuer must not become a bypass of anything else.

    `iss` was never the authenticity claim - Wix holds the private half of the configured public
    key and nobody else does. So the checks that matter are asserted to still bite on a token
    shaped exactly like a real Wix one.
    """
    real_shape = {"iat": NOW - 5, "exp": NOW + 300, "data": envelope()}
    for payload, sign_with, app_id in [
        (real_shape, "other", None),                                   # wrong key
        ({**real_shape, "exp": NOW - 120}, "private", None),           # expired
        ({**real_shape, "iat": NOW + 600}, "private", None),           # issued in the future
        ({k: v for k, v in real_shape.items() if k != "exp"}, "private", None),   # no exp
        ({k: v for k, v in real_shape.items() if k != "iat"}, "private", None),   # no iat
        ({**real_shape, "aud": "another-app"}, "private", APP_ID),     # wrong audience
    ]:
        with pytest.raises(wix_webhook.WixWebhookUnauthorized):
            wix_webhook.verify_signature(
                token(keys, payload, sign_with=sign_with), now=NOW,
                reader=reader_for(keys["public_pem"], app_id=app_id))


def test_the_accepted_issuer_set_is_an_allowlist_and_not_a_wildcard(keys):
    """The fix is "no declared issuer, or a Wix one" - never "any issuer".

    Asserted on the constant as well as on behaviour, because the dangerous regression here is
    someone replacing the check with `pass` and the behavioural tests above still passing for a
    token that simply omits the claim.
    """
    assert wix_webhook.ACCEPTED_ISSUERS == frozenset({"wix.com"})
    assert wix_webhook.ISSUER in wix_webhook.ACCEPTED_ISSUERS


def test_an_expired_wix_webhook_token_is_refused(keys):
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            token(keys, claims(exp=NOW - 120)), now=NOW,
            reader=reader_for(keys["public_pem"]))


def test_a_token_issued_in_the_future_is_refused(keys):
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            token(keys, claims(iat=NOW + 600)), now=NOW,
            reader=reader_for(keys["public_pem"]))


@pytest.mark.parametrize("bad", [None, "1700000000", True, 1.5, [], {}])
def test_a_missing_or_non_integer_iat_or_exp_is_refused(keys, bad):
    """Never defaulted. A token with no expiry is a replay token.

    `True` is in the list on purpose: `isinstance(True, int)` is True in Python, so an unguarded
    check would read `iat: true` as the integer 1 and date the token to 1970.
    """
    for field in ("iat", "exp"):
        with pytest.raises(wix_webhook.WixWebhookUnauthorized):
            wix_webhook.verify_signature(
                token(keys, claims(**{field: bad})), now=NOW,
                reader=reader_for(keys["public_pem"]))


def test_clock_skew_is_tolerated_in_both_directions(keys):
    """Symmetric and bounded at 60 seconds, so a slightly fast Wix clock is not an outage."""
    inside = wix_webhook.CLOCK_SKEW_SECONDS - 1
    for payload in [claims(iat=NOW + inside), claims(exp=NOW - inside)]:
        assert wix_webhook.verify_signature(
            token(keys, payload), now=NOW, reader=reader_for(keys["public_pem"]))


def test_a_wrong_audience_is_refused_when_an_app_id_is_configured(keys):
    for audience in ["another-app", "", None, [APP_ID], [APP_ID, "other"]]:
        with pytest.raises(wix_webhook.WixWebhookUnauthorized):
            wix_webhook.verify_signature(
                token(keys, claims(aud=audience)), now=NOW,
                reader=reader_for(keys["public_pem"]))


def test_the_audience_check_is_skipped_when_no_app_id_is_configured(keys):
    """The documented floor: the key alone is enough to start working.

    An attacker still needs the private half of the CONFIGURED public key to get this far, and the
    worst a wrong-audience-but-correctly-signed event could achieve is a catalogue re-read.
    """
    verified = wix_webhook.verify_signature(
        token(keys, claims(aud="some-other-app")), now=NOW,
        reader=reader_for(keys["public_pem"], app_id=None))
    assert verified.slug == "a-new-product"


@pytest.mark.parametrize("secret", [
    {},
    None,
    {"public_key": ""},
    {"public_key": None},
    {"public_key": "not a pem"},
    {"public_key": "-----BEGIN PUBLIC KEY-----\nnope\n-----END PUBLIC KEY-----\n"},
    {"app_id": APP_ID},
])
def test_an_unusable_configured_key_refuses_rather_than_raising(keys, secret):
    """FAIL CLOSED, and as a 401 rather than a 500.

    This is the state the receiver ships in: `wecare/wix/catalog-webhook` does not exist yet, so
    every call is refused. That is the correct resting state for an endpoint that triggers a
    production build.
    """
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(token(keys), now=NOW, reader=lambda _: secret)


def test_an_elliptic_curve_key_for_an_rs_algorithm_refuses_rather_than_raising(keys):
    with pytest.raises(wix_webhook.WixWebhookUnauthorized):
        wix_webhook.verify_signature(
            token(keys), now=NOW, reader=reader_for(keys["ec_public_pem"]))


# ── 3. the envelope is for reporting only ────────────────────────────────────


@pytest.mark.parametrize("data", [
    None, "", "not json", "[]", "123", {}, [], {"eventType": None},
    json.dumps({"eventType": "x"}),
    json.dumps({"data": "not json either"}),
])
def test_an_unreadable_envelope_still_verifies(keys, data):
    """Because the rebuild decision does not read it.

    A verified Wix event means "re-read the catalogue", which is right whatever the event said. So
    an envelope shape change costs a log field and can never cost a missed sync. If this ever
    starts raising, the receiver has grown a dependency on Wix's payload shape that it must not
    have.
    """
    verified = wix_webhook.verify_signature(
        token(keys, claims(data=data)), now=NOW, reader=reader_for(keys["public_pem"]))
    assert isinstance(verified, wix_webhook.WixEvent)


def test_an_envelope_sent_as_an_object_rather_than_a_string_is_read(keys):
    """Defensive at both nesting levels, because Wix's own examples nest a string in a string."""
    payload = claims(data={"eventType": "product_updated", "data": {"slug": "kiosk"}})
    verified = wix_webhook.verify_signature(
        token(keys, payload), now=NOW, reader=reader_for(keys["public_pem"]))
    assert verified.event_type == "product_updated"
    assert verified.slug == "kiosk"


def test_the_audience_is_reported_even_when_no_app_id_is_configured(keys):
    """The point of reporting `aud` at all: step 7 cannot run until `app_id` is known.

    With `app_id` unset the verifier does not compare the audience, so the delivered token is the
    only authority on which appId Wix addressed. Reporting it is what lets the right value be
    configured; an appId is a public installation identifier, the same class as `instanceId`.
    """
    verified = wix_webhook.verify_signature(
        token(keys, claims(aud="6cbf8eaf-264d-495a-bde1-d63d016d58a9")), now=NOW,
        reader=reader_for(keys["public_pem"], app_id=None))
    assert verified.audience == "6cbf8eaf-264d-495a-bde1-d63d016d58a9"


@pytest.mark.parametrize("audience", [None, 123, ["a", "b"], {"aud": "a"}])
def test_a_non_string_audience_is_reported_as_empty_rather_than_coerced(keys, audience):
    """Matching step 7, which refuses a list-valued `aud` rather than searching it.

    `str(["a", "b"])` in a log line would read like an audience this endpoint accepted. Empty is
    the honest report for "the token did not name a single app".
    """
    verified = wix_webhook.verify_signature(
        token(keys, claims(aud=audience)), now=NOW,
        reader=reader_for(keys["public_pem"], app_id=None))
    assert verified.audience == ""


# ── 4. the handler: 401 and NO dispatch, or 200 and one dispatch ─────────────


def test_the_handler_dispatches_exactly_once_on_a_verified_event(keys, monkeypatch):
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)

    answer = receiver.handler({"body": token(keys)}, None)

    assert answer["statusCode"] == 200
    assert json.loads(answer["body"]) == {
        "received": True, "rebuildRequested": True,
        "eventType": "wix.stores.catalog.v3.product_created"}
    assert len(sent.calls) == 1
    call = sent.calls[0]
    assert call["url"] == (
        f"https://api.github.com/repos/{receiver.GITHUB_REPOSITORY}/dispatches")
    assert call["method"] == "POST"
    assert call["body"] == {"event_type": receiver.DISPATCH_EVENT_TYPE}
    # A hung GitHub must not hold a Lambda to its own timeout.
    assert call["timeout"] == receiver.DISPATCH_TIMEOUT_SECONDS


def test_the_verified_log_line_carries_the_catalogue_correlation_fields(keys, monkeypatch):
    """`wix_webhook_verified` is the ONE permanent log line, so its fields are pinned.

    They are what a reader greps in /aws/lambda/wecare-wix-catalog-webhook to tie a Wix edit to a
    workflow run to an Amplify build. All four are public catalogue or installation identifiers.

    `audience` is asserted ABSENT. It was logged during the 2026-10-05 debugging to discover which
    appId Wix addressed deliveries to; the first real delivery (15:33:22) answered it by carrying
    no `aud` at all, so the field would now be permanently empty. `WixEvent.audience` still
    exists - this asserts the handler stopped logging it, not that the verifier stopped reading it.
    """
    lines = []
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)
    monkeypatch.setattr(receiver.logger, "info", lambda line: lines.append(line))

    receiver.handler({"body": token(keys)}, None)

    verified = next(json.loads(line) for line in lines
                    if json.loads(line).get("event") == "wix_webhook_verified")
    assert verified["eventType"] == "wix.stores.catalog.v3.product_created"
    assert verified["instanceId"] == INSTANCE_ID
    assert "audience" not in verified


@pytest.mark.parametrize("event", [
    {},
    {"body": None},
    {"body": ""},
    {"body": "not-a-jwt"},
    {"body": '{"eventType":"product_created","slug":"attacker"}'},
    {"body": "a.b.c"},
])
def test_an_unsigned_post_gets_401_and_triggers_NO_rebuild(keys, monkeypatch, event):
    """The case the endpoint exists to refuse.

    Each call starts an Amplify production build, so an endpoint that rebuilds on an
    unauthenticated POST is a free denial-of-wallet. `sent.calls == []` is the assertion; the 401
    alone would pass even if the trigger had already fired.
    """
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)

    answer = receiver.handler(event, None)

    assert answer["statusCode"] == 401
    assert answer["body"] == ""
    assert sent.calls == []


def test_a_refusal_logs_THE_REASON_AND_NOTHING_ELSE(keys, monkeypatch):
    """`wix_webhook_rejected` is the whole of the refusal log, and that is pinned on purpose.

    During the 2026-10-05 debugging this path also carried two TEMPORARY diagnostics - a body
    `wix_webhook_shape` line and a `wix_webhook_claims` claim extractor - because Wix had never
    delivered here and nothing on record said what a real delivery looked like. A verified
    delivery at 15:33:22 discharged both and they were removed.

    The assertion that matters is the second half: the refused body must not be reconstructible
    from the log at all. `reason` is assembled in `wix_webhook.py` from known-safe literal parts,
    so it is the one field that may be emitted.
    """
    lines = []
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.logger, "warning", lambda line: lines.append(line))

    bad = token(keys, claims(iss="not-wix.example"), sign_with="other",
                header_extra={"kid": "TEST-KEY-ID"})
    answer = receiver.handler({
        "body": bad,
        "headers": {"Content-Type": "application/json", "User-Agent": "whatever"},
        "isBase64Encoded": False,
    }, None)

    assert answer["statusCode"] == 401
    assert sent.calls == []

    assert [json.loads(line)["event"] for line in lines] == ["wix_webhook_rejected"]
    rejected = json.loads(lines[0])
    assert set(rejected) == {"event", "reason"}
    assert rejected["reason"] == "the token signature does not verify"
    for line in lines:
        assert bad not in line, "the token must never be logged whole"
        assert bad.split(".")[2] not in line, "the signature segment must never be logged"
        assert bad.split(".")[1] not in line, "the payload segment must never be logged"
        assert INSTANCE_ID not in line, "the envelope must not reach the refusal log"
        assert "a-new-product" not in line, "product data must not reach the refusal log"
        assert APP_ID not in line, "no claim value may reach the refusal log"


def test_a_body_of_any_awkward_type_gets_401_rather_than_500(keys, monkeypatch):
    """A refusal that raises becomes a 500, and a 500 makes Wix retry a body it cannot fix.

    Measured against the live endpoint rather than predicted: a JWT-SHAPED body once reached the
    key read and escaped as a 500, which is how `_read_secret`'s "`{}` on any failure" rule was
    found. These are the shapes that get nowhere near a key and must still land on 401.
    """
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)

    for body in [None, "", "not-a-jwt", {"wrapped": "a.b.c"}, 123, b"not-a-jwt",
                 "a.b.c", "ey!.ey!.sig", f"{b64(b'[]')}.{b64(b'null')}.{b64(b'x')}"]:
        answer = receiver.handler({"body": body, "headers": None}, None)
        assert answer["statusCode"] == 401, f"{type(body).__name__} body did not refuse cleanly"
        assert answer["body"] == ""
    assert sent.calls == []


def test_a_verified_event_logs_NO_WARNING_AT_ALL(keys, monkeypatch):
    """A working endpoint stays off the refusal channel entirely.

    Which is also what keeps `test_verification_precedes_every_other_statement_in_the_handler`
    honest: nothing is logged about a caller before that caller has been refused.
    """
    lines = []
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)
    monkeypatch.setattr(receiver.logger, "warning", lambda line: lines.append(line))

    answer = receiver.handler({"body": token(keys)}, None)

    assert answer["statusCode"] == 200
    assert lines == []


def test_a_wrong_key_signature_gets_401_and_triggers_NO_rebuild(keys, monkeypatch):
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)

    answer = receiver.handler({"body": token(keys, sign_with="other")}, None)

    assert answer["statusCode"] == 401
    assert sent.calls == []


def test_an_unconfigured_public_key_gets_401_and_triggers_NO_rebuild(monkeypatch):
    """The resting state before the owner creates `wecare/wix/catalog-webhook`."""
    sent = Dispatches()
    monkeypatch.setattr(receiver, "_read_secret", lambda _: {})
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)

    answer = receiver.handler({"body": "a.b.c"}, None)

    assert answer["statusCode"] == 401
    assert sent.calls == []


def test_a_missing_github_token_is_reported_without_a_retry_inducing_error(keys, monkeypatch):
    """200 with `rebuildRequested: false`.

    A non-2xx would make Wix retry, and a retry cannot conjure a GitHub token. The six-hourly
    `catalogue-sync.yml` cron is what actually covers this, so the honest answer is "received, and
    the rebuild was not started".
    """
    sent = Dispatches()

    def read(secret_id: str):
        if secret_id == wix_webhook.SECRET_ID:
            return {wix_webhook.PUBLIC_KEY_FIELD: keys["public_pem"],
                    wix_webhook.APP_ID_FIELD: APP_ID}
        return {}

    monkeypatch.setattr(receiver, "_read_secret", read)
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)

    answer = receiver.handler({"body": token(keys)}, None)

    assert answer["statusCode"] == 200
    assert json.loads(answer["body"])["rebuildRequested"] is False
    assert sent.calls == []


@pytest.mark.parametrize("failure", [
    RuntimeError("ResourceNotFoundException"),
    ValueError("not json"),
    KeyError("SecretString"),
    OSError("connection reset"),
])
def test_a_secret_READ_failure_is_401_and_not_500(monkeypatch, failure):
    """A REGRESSION TEST, for a defect the LIVE PROBE found and this file originally missed.

    `wecare/wix/catalog-webhook` does not exist, so a JWT-SHAPED body got past the cheap checks,
    reached the key read, and boto3's `ResourceNotFoundException` escaped the verifier's
    `WixWebhookUnauthorized` handler. Measured against the deployed endpoint:

        POST 'not-a-jwt'                           -> 401
        POST 'eyJhbGciOiJSUzI1NiJ9.eyJ...fQ.c2ln'  -> 500   <- the defect
        POST ''                                    -> 401

    Every case in this file's rejection parametrisation used a body that was refused BEFORE the
    read, so none of them could have caught it. A verifier that cannot read its key must refuse,
    not crash - so this drives the reader to RAISE and asserts the answer is still 401 with no
    dispatch.
    """
    sent = Dispatches()

    def exploding_client(*args, **kwargs):
        raise failure

    # Patch `boto3.client` itself, so the REAL `_read_secret` body runs and its own except clause
    # is the thing under test. Patching `_read_secret` would be testing the test.
    import boto3
    monkeypatch.setattr(boto3, "client", exploding_client)
    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)

    answer = receiver.handler({"body": "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJ3aXguY29tIn0.c2ln"}, None)

    assert answer["statusCode"] == 401
    assert answer["body"] == ""
    assert sent.calls == []


def test_a_github_failure_is_reported_rather_than_raised(keys, monkeypatch):
    sent = Dispatches(status=500)

    def boom(request, timeout=None):
        raise OSError("connection reset")

    monkeypatch.setattr(receiver, "_read_secret", reader_for(keys["public_pem"]))
    monkeypatch.setattr(receiver.time, "time", lambda: NOW)

    monkeypatch.setattr(receiver.urllib.request, "urlopen", boom)
    answer = receiver.handler({"body": token(keys)}, None)
    assert answer["statusCode"] == 200
    assert json.loads(answer["body"])["rebuildRequested"] is False

    monkeypatch.setattr(receiver.urllib.request, "urlopen", sent)
    answer = receiver.handler({"body": token(keys)}, None)
    assert json.loads(answer["body"])["rebuildRequested"] is False


# ── 5. structural guarantees, asserted by AST rather than by reading ────────


def test_the_handler_cannot_read_the_catalogue_or_write_anything():
    """It verifies and dispatches. It is not a second opinion about what Wix contains.

    `scripts/fetch-wix-catalog.js` in the workflow is the single authority on the catalogue, with
    its 0-product and variant guards. A receiver that also fetched would be a second code path
    with its own guards to keep in step.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    # TOP-LEVEL only, from `tree.body` rather than `ast.walk`: `boto3` is imported deliberately
    # INSIDE `_read_secret`, so walking the whole tree would always find it and this assertion
    # would be about nothing.
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "boto3" not in imported, (
        "boto3 is imported lazily inside _read_secret on purpose; a top-level import means "
        "something else in this handler grew an AWS dependency")

    # WALKS THE AST, NOT THE TEXT. The docstring explaining why this receiver must not fetch the
    # catalogue necessarily names `fetch-wix-catalog.js`, so a substring scan of the file would
    # fail on the comment that documents the rule. Only code is examined: attribute names, plain
    # names, and string constants that are not docstrings.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    code_text = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            code_text.append(node.attr)
        elif isinstance(node, ast.Name):
            code_text.append(node.id)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings):
            code_text.append(node.value)

    haystack = "\n".join(code_text)
    for forbidden in ("dynamodb", "wixapis.com", "put_item", "PutItem", "start_job",
                      "fetch-wix-catalog", "Table"):
        assert forbidden not in haystack, f"the receiver must not reference {forbidden} in code"


def test_verification_precedes_every_other_statement_in_the_handler():
    """Asserted on the AST, not by reading the file.

    The first statement of `handler` after normalising the event must be the `try` that calls
    `verify_signature`. Anything before it is work done for an unauthenticated caller.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    func = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "handler")
    body = [n for n in func.body if not isinstance(n, ast.Expr)]  # drop the docstring
    assert isinstance(body[0], ast.Assign), "expected the event normalisation first"
    assert isinstance(body[1], ast.Try), "verification must be the first thing that can fail"
    called = {n.func.attr for n in ast.walk(body[1])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "verify_signature" in called


def test_no_secret_appears_in_a_logging_expression():
    """Not "is not logged" - must not APPEAR in the expression.

    CodeQL's `py/clear-text-logging-sensitive-data` tracks taint across function boundaries and
    has already failed this build twice over a ternary on a key's truthiness. So no logger call in
    either file may mention a token, a key or a token segment at all.
    """
    for path in (MODULE, HANDLER):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
                continue
            rendered = ast.dump(node)
            for forbidden in ("'token'", "'public_key'", "'secret'", "public_key_pem",
                              "signature_segment", "payload_segment", "raw_body"):
                assert forbidden not in rendered, (
                    f"{path.name}: a logger call references {forbidden}")


def test_no_credential_reading_function_is_a_default_argument():
    """A REGRESSION TEST, for a defect this file's first run produced rather than predicted.

    `_dispatch` was written `def _dispatch(reader=_read_secret, ...)`. A default argument is bound
    at DEFINITION time, so `monkeypatch.setattr(receiver, "_read_secret", ...)` had no effect and
    the test meant to simulate a MISSING GitHub token instead called live Secrets Manager, read the
    real credential into the test process, and passed the dispatch. The test reported success for
    the opposite of what it was asserting.

    So: no parameter default in either file may name a secret-reading function. They resolve
    inside, from the module attribute, where a patch reaches them.
    """
    for path in (MODULE, HANDLER):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            defaults = list(node.args.defaults) + [
                d for d in node.args.kw_defaults if d is not None]
            for default in defaults:
                # A `_read*` FUNCTION, not a secret NAME. `secret_id: str = SECRET_ID` is fine and
                # is the by-reference pattern this repo requires - SECRET_ID is a name, never a
                # value, and rebinding it has no late-binding hazard.
                assert not (isinstance(default, ast.Name)
                            and default.id.startswith("_read")), (
                    f"{path.name}:{node.name} binds {getattr(default, 'id', '?')} as a default "
                    "argument; resolve it inside the function instead")


def test_the_verifier_logs_nothing_at_all():
    """It is handed a token and a key. The cheapest proof it cannot leak either is no logger."""
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "logger" not in names
    assert "print" not in names
