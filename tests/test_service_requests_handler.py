"""`wecare-service-requests`: the HTTP surface and the internal activation hint. Offline.

The store's own races are pinned in tests/test_service_request_store.py; this file pins what the
HANDLER adds -- authentication before anything that costs, the 401/404 shapes, the body
allow-lists, the internal arm being unreachable from API Gateway, `no-store` on every exit, and
no phone in any log line.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from service_requests_fake_dynamo import KeysTable, RequestTable  # noqa: E402

from lambda_utils import customer_auth  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/service-requests/handler.py"
ALICE = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PHONE = "+918100640044"


@pytest.fixture
def env(monkeypatch):
    spec = importlib.util.spec_from_file_location("service_requests_handler_under_test", HANDLER)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    tables = {h.SERVICE_REQUESTS_TABLE: RequestTable(), h.COMMERCE_KEYS_TABLE: KeysTable()}
    monkeypatch.setattr(h, "_table", lambda name: tables[name])
    state = {"who": ALICE, "allow": True, "rate_calls": []}

    def authenticate(event):
        if not customer_auth.bearer_token(event):
            raise customer_auth.CustomerNotAuthenticated("none")
        return customer_auth.CustomerIdentity(customer_id=state["who"], phone=PHONE,
                                              subject=state["who"])

    def rate(channel, resource, limit, table_name=None):
        state["rate_calls"].append((channel, resource))
        return state["allow"]

    monkeypatch.setattr(h.customer_auth, "authenticate", authenticate)
    monkeypatch.setattr(h.rate_limit, "check_rate_limit", rate)
    h.requests_table = tables[h.SERVICE_REQUESTS_TABLE]
    h.keys_table = tables[h.COMMERCE_KEYS_TABLE]
    h.state = state
    return h


def event(path, body, *, token="tok"):
    headers = {"origin": "https://wecare.digital"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return {"requestContext": {"http": {"method": "POST"}}, "rawPath": path,
            "headers": headers, "body": json.dumps(body)}


def call(h, path, body, **kw):
    response = h.handler(event(path, body, **kw), None)
    return response["statusCode"], json.loads(response["body"]), response["headers"]


def paid_submit(h):
    status, intent, _ = call(h, "/services/request-intent", {"kind": "SUBMIT_REQUEST"})
    assert status == 200
    ref = "WD-PAY-0123456789ABCD"
    h.keys_table.seed({"orderId": "PAYREF#" + ref, "paymentAttemptId": "att-1",
                       "customerId": ALICE, "serviceLine": {
                           "kind": "SUBMIT_REQUEST", "variantId": intent["variantId"],
                           "paise": 9900, "intentId": intent["intentId"]}})
    h.keys_table.seed({"orderId": "PAYMENTATTEMPT#att-1", "orderIdRef": "order-1",
                       "orderNumber": "WD-ORD-ABCDEFGH", "referenceId": ref,
                       "paymentAttemptId": "att-1"})
    return ref


def test_unauthenticated_calls_are_one_identical_401_and_cost_nothing(env):
    first = call(env, "/services/request-intent", {"kind": "SUBMIT_REQUEST"}, token="")
    second = call(env, "/services/my-requests", {}, token="")
    assert first[0] == second[0] == 401
    assert first[1] == second[1] == {"error": "VERIFICATION_REQUIRED",
                                     "message": "Please verify your WhatsApp number to continue."}
    assert env.state["rate_calls"] == [] and env.requests_table.calls == []


def test_every_exit_is_not_cacheable(env):
    for path, body, token in (("/services/request-intent", {"kind": "SUBMIT_REQUEST"}, "t"),
                              ("/services/my-requests", {}, "t"),
                              ("/services/my-requests", {}, ""),
                              ("/services/unknown", {}, "t")):
        _s, _b, headers = call(env, path, body, token=token)
        assert headers["Cache-Control"] == "no-store"


def test_rate_limited_is_429_and_keyed_on_the_proven_subject(env):
    env.state["allow"] = False
    status, body, _ = call(env, "/services/request-intent", {"kind": "SUBMIT_REQUEST"})
    assert (status, body["error"]) == (429, "RATE_LIMITED")
    assert env.state["rate_calls"] == [("service-intent", ALICE)]
    assert env.requests_table.rows == {}


@pytest.mark.parametrize("path,body", [
    ("/services/request-intent", {"kind": "SUBMIT_REQUEST", "customerId": BOB}),
    ("/services/request-intent", {"kind": "SUBMIT_REQUEST", "amountPaise": 1}),
    ("/services/my-requests", {"customerId": BOB}),
])
def test_an_unknown_body_key_is_400(env, path, body):
    status, payload, _ = call(env, path, body)
    assert (status, payload["error"]) == (400, "UNEXPECTED_FIELD")


def test_the_intent_happy_path(env):
    status, body, _ = call(env, "/services/request-intent", {"kind": "SUBMIT_REQUEST"})
    assert status == 200
    # `amountPaise` is None: PRICED AT CHECKOUT, by Wix. The key stays in the payload so the wire
    # shape remains a superset of what src/lib/serviceRequests.ts reads, and None says "not priced
    # yet" where a 0 would have claimed the service is free.
    assert body["amountPaise"] is None and body["currency"] == "INR"
    assert body["variantId"] == "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"


@pytest.mark.parametrize("kind,variant", [
    ("DROP_DOCS", "db166bc8-a763-41ec-9f65-0f718f18155a"),
    ("VAULT", "dcff995e-448c-493a-9259-f6a82ccdc2b4"),
])
def test_drop_docs_and_vault_are_offered_against_one_of_the_callers_requests(env, kind, variant):
    ref = paid_submit(env)
    _s, listed, _h = call(env, "/services/my-requests", {"referenceIds": [ref]})
    public = listed["requests"][0]["requestId"]
    status, body, _ = call(env, "/services/request-intent",
                           {"kind": kind, "targetRequestId": public})
    assert status == 200, body
    assert (body["kind"], body["variantId"], body["amountPaise"], body["currency"]) == \
        (kind, variant, None, "INR")
    assert body["targetRequestId"] == public


@pytest.mark.parametrize("kind", ["DROP_DOCS", "VAULT"])
def test_drop_docs_and_vault_without_a_target_are_400(env, kind):
    status, body, _ = call(env, "/services/request-intent", {"kind": kind})
    assert (status, body["error"]) == (400, "SERVICE_TARGET_REQUIRED")


@pytest.mark.parametrize("kind", ["DROP_DOCS", "VAULT"])
def test_a_new_service_against_someone_elses_request_is_the_same_404(env, kind):
    ref = paid_submit(env)
    _s, listed, _h = call(env, "/services/my-requests", {"referenceIds": [ref]})
    public = listed["requests"][0]["requestId"]
    env.state["who"] = BOB
    theirs = call(env, "/services/request-intent", {"kind": kind, "targetRequestId": public})
    missing = call(env, "/services/request-intent",
                   {"kind": kind, "targetRequestId": "WD-REQ-ZZZZZZZZ"})
    assert theirs[0] == missing[0] == 404
    assert theirs[1] == missing[1]


def test_an_unknown_kind_is_400(env):
    status, body, _ = call(env, "/services/request-intent", {"kind": "SOMETHING"})
    assert (status, body["error"]) == (400, "SERVICE_UNKNOWN_CHOICE")


def test_an_amendment_against_someone_elses_request_is_the_same_404_as_a_missing_one(env):
    ref = paid_submit(env)
    status, listed, _ = call(env, "/services/my-requests", {"referenceIds": [ref]})
    public = listed["requests"][0]["requestId"]
    env.state["who"] = BOB
    theirs = call(env, "/services/request-intent",
                  {"kind": "REQUEST_AMENDMENT", "targetRequestId": public})
    missing = call(env, "/services/request-intent",
                   {"kind": "REQUEST_AMENDMENT", "targetRequestId": "WD-REQ-ZZZZZZZZ"})
    assert theirs[0] == missing[0] == 404
    assert theirs[1] == missing[1]
    env.state["who"] = ALICE
    mine = call(env, "/services/request-intent",
                {"kind": "REQUEST_AMENDMENT", "targetRequestId": public})
    assert mine[0] == 200 and mine[1]["targetRequestId"] == public


def test_my_requests_self_heals_and_lists_only_the_callers_own(env):
    ref = paid_submit(env)
    status, body, _ = call(env, "/services/my-requests", {"referenceIds": [ref]})
    assert status == 200
    [row] = body["requests"]
    assert re.match(r"^WD-REQ-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{8}$", row["requestId"])
    assert row["orderNumber"] == "WD-ORD-ABCDEFGH" and row["kind"] == "SUBMIT_REQUEST"
    env.state["who"] = BOB
    # Bob naming Alice's reference activates nothing and lists nothing.
    status, body, _ = call(env, "/services/my-requests", {"referenceIds": [ref]})
    assert (status, body["requests"]) == (200, [])


def test_my_requests_is_bounded_to_twenty_reference_ids(env):
    refs = [f"WD-PAY-{i:014d}" for i in range(21)]
    status, body, _ = call(env, "/services/my-requests", {"referenceIds": refs})
    assert (status, body["error"]) == (400, "INVALID_REFERENCE_IDS")
    status, _body, _ = call(env, "/services/my-requests", {"referenceIds": refs[:20]})
    assert status == 200
    for bad in (["x" * 40], [7], "WD-PAY-1", [None]):
        assert call(env, "/services/my-requests", {"referenceIds": bad})[0] == 400


def test_the_internal_action_is_ignored_when_request_context_is_present(env):
    ref = paid_submit(env)
    forged = event("/services/my-requests", {})
    forged.update({"internalAction": "activateServiceRequest", "referenceId": ref})
    forged["headers"].pop("authorization")
    response = env.handler(forged, None)
    assert response["statusCode"] == 401
    assert not [k for k in env.requests_table.rows if str(k).startswith("REQ#")]


def test_the_internal_action_activates_and_is_idempotent(env):
    ref = paid_submit(env)
    hint = {"internalAction": "activateServiceRequest", "referenceId": ref,
            "paymentAttemptId": "att-1", "orderId": "order-1"}
    first = env.handler(dict(hint), None)
    second = env.handler(dict(hint), None)
    assert first["outcome"] == "ACTIVATED" and second["outcome"] == "ALREADY_ACTIVE"
    assert first["requestId"] == second["requestId"]
    assert env.keys_table.writes() == []


def test_the_internal_action_never_raises(env, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("table gone")
    monkeypatch.setattr(env.store, "activate", boom)
    result = env.handler({"internalAction": "activateServiceRequest",
                          "referenceId": "WD-PAY-0123456789ABCD"}, None)
    assert result == {"outcome": "ERROR"}
    assert env.handler({"internalAction": "activateServiceRequest",
                        "referenceId": "../../etc"}, None)["outcome"] == "NOT_A_SERVICE_ORDER"


def test_no_log_line_carries_a_phone(env, caplog):
    with caplog.at_level(logging.DEBUG):
        ref = paid_submit(env)
        _s, listed, _h = call(env, "/services/my-requests", {"referenceIds": [ref]})
        call(env, "/services/request-intent",
             {"kind": "DROP_DOCS", "targetRequestId": listed["requests"][0]["requestId"]})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text, "the detector must have something to read"
    # Our own ids (UUIDs, the WD-PAY reference) may legitimately contain digit runs; strip them
    # first so the detector looks only at what could be a phone.
    scrubbed = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "",
                      text.replace("WD-PAY-0123456789ABCD", ""))
    assert not re.search(r"\d{10,}", scrubbed), text
    assert "8100640044" not in text


def test_the_handler_imports_no_money_mover_and_reads_no_secret():
    import ast
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    for banned in ("razorpay_orders", "razorpay_verify", "wix_ecom", "cart_v2", "wix_writeback",
                   "finalization", "order_creation", "secretsmanager"):
        assert not any(banned in name for name in names), banned
    assert "secretsmanager" not in HANDLER.read_text(encoding="utf-8")
