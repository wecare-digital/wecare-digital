"""The Wix coupon + gift card harness: real code paths, Wix stubbed at `urlopen` only.

Design reference: `.agents/tasks/wix-coupon-giftcard-sample-20261002/design.md` revision 8, §2.2
(keeping AWS out), §2.3 (the transport stub), §2.4 (these groups) and §2.5 (the adapter).

Every group drives PRODUCTION code. Nothing here constructs a payload by hand.

| Group | Question it answers | Entry point |
|---|---|---|
| A | what goes on the wire for a coupon | `coupon_store.create` + `WixCoupons(wix_ecom._request)` |
| B | what the handler answers, per Wix outcome | `coupons/handler._create` and `._get` |
| C | the Wix-native gift-card adapter's whole contract | `WixGiftCards(wix_ecom._request)` |
| D | the structural guarantees | AST over the tree |

CONTAINMENT, AND THE ONE ASSERTION NOT MADE
-------------------------------------------
`boto3` is sabotaged in `sys.modules` so any attribute access raises a `BaseException`, and
`wix_ecom._key_cache` is seeded with a placeholder so no secret read is attempted. What is
deliberately NOT asserted is `"boto3" not in sys.modules` - that is false in this very module
once the coupon handler is imported (it imports `middleware` and `rate_limit`), so the assertion
would be red in CI regardless of the code under test. `wix_ecom._secrets is None` is the honest
form of the same claim: no Secrets Manager client was ever built.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils import wix_ecom  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import redemption  # noqa: E402
from lambda_utils.ecommerce import store_redemption_provider as srp  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gcs  # noqa: E402
from lambda_utils.ecommerce import wix_coupons as wc  # noqa: E402
from lambda_utils.ecommerce import wix_gift_cards as wg  # noqa: E402
from lambda_utils.ecommerce.money import Money  # noqa: E402
from wix_transport_stub import WixTransport  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ADAPTER = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wix_gift_cards.py"
ADAPTER_SOURCE = ADAPTER.read_text(encoding="utf-8")
ADAPTER_TREE = ast.parse(ADAPTER_SOURCE, filename=str(ADAPTER))
DEMO = ROOT / "scripts/demo_coupon_giftcard_sample.py"
AMPLIFY = ROOT / "amplify"

#: Not a credential. Chosen to match NONE of `scripts/block_inline_secrets.py`'s issuer prefixes
#: (`rzp_live_`, `sk-`, `AIza`, `ghp_`, `xoxb-`, `AKIA`/`ASIA`, `sk_live_`, `ksk_`), and it is
#: never an argv value - it is seeded into a module cache in-process.
PLACEHOLDER_API_KEY = "wix-admin-key-PLACEHOLDER-not-a-credential"

#: Test-only HMAC key, so `card_code` has something to key with. The real pepper lives in
#: Secrets Manager under `wecare/wix/giftcard-spi:code_pepper` and is never read here.
PEPPER = "pepper-for-tests-only"

REFERENCE = "wd-gc-sample-2026-10-02"
NOW = 1_700_000_000
START_MS = 1_719_390_501_000


def clock(value: int = NOW):
    return lambda: value


class _UnexpectedAwsUse(BaseException):
    """BaseException, so the handler's `except Exception` cannot answer 202 over the top of it."""


class _ExplodesOnAttributeAccess:
    def __getattr__(self, name):
        raise _UnexpectedAwsUse(f"this harness touched boto3.{name}")


@pytest.fixture
def transport(monkeypatch) -> WixTransport:
    """Patch `urllib.request.urlopen` and NOTHING ELSE.

    All five behaviours of `wix_ecom._request` therefore execute for real: header composition,
    `json.dumps` with no custom encoder, the `HTTPError`-to-status-prose reduction, `json.loads`
    with no `parse_float`, and the timeout. Stubbing `_request` itself would stub out the
    conversion rules this file exists to measure.
    """
    import urllib.request

    monkeypatch.setitem(wix_ecom._key_cache, "key", PLACEHOLDER_API_KEY)
    monkeypatch.setitem(sys.modules, "boto3", _ExplodesOnAttributeAccess())
    stub = WixTransport()
    monkeypatch.setattr(urllib.request, "urlopen", stub)
    yield stub
    stub.assert_drained()
    assert wix_ecom._secrets is None, "a Secrets Manager client was built"


def coupons_table() -> FakeTable:
    return FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                     indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})


def definition(**overrides):
    base = {
        "code": "WDSAMPLE10",
        "name": "Sample money off",
        "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 12345600,
        "startTimeMs": START_MS,
        "minimumSubtotalPaise": 500000,
        "usageLimit": 10,
        "limitPerCustomer": 1,
    }
    base.update(overrides)
    return cs.validate_definition({k: v for k, v in base.items() if v is not None},
                                  clock=clock())


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _event(route: str = "POST /coupons", body=None, path=None, username="demo-operator"):
    return {
        "requestContext": {"routeKey": route, "http": {"method": route.split(" ")[0],
                                                       "path": route.split(" ", 1)[1]}},
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path or {},
        "headers": {"origin": "https://wecare.digital"},
        "_auth": {"username": username},
    }


@pytest.fixture
def handler(monkeypatch):
    """`coupons/handler`, with exactly two stubs.

    `handler._staff`, NOT `middleware.require_auth`: `handler.middleware` is the shared module
    object that 58 files reference, and patching an attribute on it would reach all of them.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "coupons_handler_under_test", ROOT / "amplify/functions/ecommerce/coupons/handler.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["coupons_handler_under_test"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_staff", lambda event: None)
    return module


# ══ GROUP A — the coupon wire ═════════════════════════════════════════════════

def test_a_coupon_create_goes_to_stores_v2_with_the_exact_body(transport):
    """Method, absolute URL, header set, and the body compared WHOLE.

    An extra key in a coupon specification is a different promise, so the comparison is total
    rather than a subset check.
    """
    transport.expect(method="POST", endpoint=wc.BASE, body=fixture("wix_coupon_create_response.json"))
    store = coupons_table()
    row = cs.create(store, {"code": "WDSAMPLE10", "name": "Sample money off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
                            "startTimeMs": START_MS, "minimumSubtotalPaise": 500000,
                            "usageLimit": 10, "limitPerCustomer": 1}, clock=clock())
    coupon_id = wc.WixCoupons(wix_ecom._request).create(row)
    assert coupon_id == "abeb638b-f9f4-4bb8-8fe7-2319504df6d9"

    recorded = transport.requests[-1]
    assert recorded.method == "POST"
    assert recorded.url == "https://www.wixapis.com/stores/v2/coupons"
    assert "/ecom/" not in recorded.url, "coupons live under /stores/v2/, not /ecom/"

    assert {name.lower() for name in recorded.headers} == {
        "authorization", "content-type", "accept", "wix-site-id"}
    # And the EXACT recorded spelling. Note `Content-type`: `Request.add_header` applies
    # `str.capitalize()` to the name, so this is urllib's behaviour and not a typo. Do not
    # "fix" this by loosening it - the point is that the spelling is measured.
    assert set(recorded.headers) == {"Authorization", "Content-type", "Accept", "Wix-site-id"}
    assert recorded.headers["Wix-site-id"] == wix_ecom.WIX_SITE_ID
    assert recorded.authorization_present is True
    assert recorded.headers["Authorization"] == "<redacted>", (
        "the credential is redacted AT CAPTURE, so no failure diff can carry it")

    assert recorded.body == {"specification": {
        "name": "Sample money off",
        "code": "WDSAMPLE10",
        "startTime": "1719390501000",
        "moneyOffAmount": 123456,
        "minimumSubtotal": 5000,
        "usageLimit": 10,
        "limitPerCustomer": 1,
        "limitedToOneItem": False,
    }}
    parsed = json.loads(recorded.body_bytes.decode("utf-8"))["specification"]
    assert type(parsed["moneyOffAmount"]) is int, "Wix's money fields are JSON numbers"
    assert type(parsed["startTime"]) is str, "startTime is a string-encoded int64"
    assert "type" not in parsed, "`type` is read-only and derived; sending it is a conflict"


def test_a_percent_off_coupon_sends_an_integer_rate_and_no_money_amount(transport):
    """The payload §6.5 hands the owner for the second discount kind."""
    transport.expect(method="POST", endpoint=wc.BASE, body={"id": "wix-coupon-2"})
    row = definition(discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=1000)
    wc.WixCoupons(wix_ecom._request).create(row)

    parsed = json.loads(transport.requests[-1].body_bytes.decode("utf-8"))["specification"]
    assert type(parsed["percentOffRate"]) is int
    assert parsed["percentOffRate"] == 10
    assert "moneyOffAmount" not in parsed


def test_a_deactivate_patches_only_active_with_no_field_mask(transport):
    transport.expect(method="PATCH", endpoint=f"{wc.BASE}/wix-coupon-1", body={})
    wc.WixCoupons(wix_ecom._request).deactivate("wix-coupon-1")

    recorded = transport.requests[-1]
    assert recorded.method == "PATCH"
    assert recorded.url.endswith("/stores/v2/coupons/wix-coupon-1")
    assert recorded.body == {"specification": {"active": False}}, (
        "PATCH semantics: only the properties passed are updated, so a narrow body cannot wipe "
        "the discount, the scope, the limits or the expiry")
    assert "fieldMask" not in (recorded.body or {})


def test_a_wix_error_of_any_status_escapes_the_adapter_as_a_status_only_message(transport):
    for status in (400, 409, 428, 500, 502):
        transport.expect_http_error(method="POST", endpoint=wc.BASE, status=status)
        with pytest.raises(wix_ecom.WixEcomError) as failure:
            wc.WixCoupons(wix_ecom._request).create(definition())
        assert str(status) in str(failure.value)
        # The body is never surfaced: it can echo buyer detail.
        assert "specification" not in str(failure.value)


def test_a_foreign_code_under_our_id_is_a_conflict_a_human_adjudicates(transport):
    """`WIX_CODE_CONFLICT` is reachable ONLY through an explicit `Get Coupon` probe.

    `Create Coupon` documents no errors at all, so a duplicate code looks exactly like a network
    timeout to us. Both halves of §1.3's unrecoverability finding are executable here: this row
    and the case-only non-conflict below.
    """
    foreign = fixture("wix_coupon_get_response.json")
    foreign["coupon"]["specification"]["code"] = "SOMEONE-ELSES"
    transport.expect(method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9",
                     body=foreign)
    with pytest.raises(wc.WixCouponConflict):
        wc.WixCoupons(wix_ecom._request).assert_mirrors(
            wix_coupon_id="abeb638b-f9f4-4bb8-8fe7-2319504df6d9", code="SAVE10")


def test_a_case_only_difference_is_not_a_conflict(transport):
    """Compared on the NORMALISED code. Wix does not document its `code` uniqueness as
    case-insensitive, and a case-only difference is not a different coupon to a customer."""
    lowered = fixture("wix_coupon_get_response.json")
    lowered["coupon"]["specification"]["code"] = "save10"
    transport.expect(method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9",
                     body=lowered)
    view = wc.WixCoupons(wix_ecom._request).assert_mirrors(
        wix_coupon_id="abeb638b-f9f4-4bb8-8fe7-2319504df6d9", code="SAVE10")
    assert view["id"] == "abeb638b-f9f4-4bb8-8fe7-2319504df6d9"


def test_a_wix_float_amount_is_real_and_is_never_read_back(transport):
    """The hazard FIRST, then the containment. Asserting only the containment would pass even if
    `json.loads` had stopped producing floats, which is the thing being guarded against."""
    float_response = fixture("wix_coupon_get_response_float_amounts.json")
    transport.expect(method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9",
                     body=float_response)
    view = wc.WixCoupons(wix_ecom._request).get("abeb638b-f9f4-4bb8-8fe7-2319504df6d9")

    # The hazard is real: `wix_ecom._request` calls `json.loads` with no `parse_float`.
    assert type(float_response["coupon"]["specification"]["moneyOffAmount"]) is float
    # And the containment: no numeric field reaches a caller.
    assert set(view) == {"id", "active", "type", "code"}
    assert not any(isinstance(value, float) for value in view.values())
    for numeric in wc.NUMERIC_RESPONSE_KEYS:
        assert numeric not in view


# ══ GROUP B — the handler, per Wix outcome ════════════════════════════════════

def test_the_handler_mirrors_a_created_coupon_and_answers_201(transport, handler, monkeypatch):
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    transport.expect(method="POST", endpoint=wc.BASE,
                     body=fixture("wix_coupon_create_response.json"))

    response = handler._create(_event(body={
        "code": "WDSAMPLE10", "name": "Sample money off", "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 12345600, "startTimeMs": START_MS, "minimumSubtotalPaise": 500000,
        "usageLimit": 10, "limitPerCustomer": 1}), origin="https://wecare.digital")

    assert response["statusCode"] == 201
    coupon = json.loads(response["body"])["coupon"]
    assert coupon["wixMirrorState"] == cs.MIRROR_DONE
    assert coupon["code"] == "WDSAMPLE10"
    row = store.rows[cs.PREFIX_DEFINITION + "WDSAMPLE10"]
    assert row["createdBy"] == "demo-operator", "created_by comes from event['_auth']"
    assert row["wixCouponId"] == "abeb638b-f9f4-4bb8-8fe7-2319504df6d9"


@pytest.mark.parametrize("status", [400, 409, 428, 500, 502])
def test_every_wix_create_failure_leaves_the_row_pending_and_answers_202(
        transport, handler, monkeypatch, status):
    """No status is special-cased, because `Create Coupon` documents none.

    The worst case is therefore a coupon that does not WORK rather than one that works
    differently from what was promised: `evaluate` refuses a `PENDING_WIX` row.
    """
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    transport.expect_http_error(method="POST", endpoint=wc.BASE, status=status)

    response = handler._create(_event(body={
        "code": "WDSAMPLE10", "name": "Sample money off", "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 12345600, "startTimeMs": START_MS,
               "minimumSubtotalPaise": 500000}), origin="https://wecare.digital")

    assert response["statusCode"] == 202
    row = store.rows[cs.PREFIX_DEFINITION + "WDSAMPLE10"]
    assert row["wixMirrorState"] == cs.MIRROR_PENDING
    assert "wixCouponId" not in row
    assert cs.evaluate(row, cart_id="cart-1") == cs.WIX_MIRROR_INCOMPLETE


def test_a_replayed_coupon_issue_converges_on_one_coupon(transport, handler, monkeypatch):
    """COUPON IDEMPOTENCY, which is the whole reason `coupon_store` is kept under Option B.

    Wix's `Create Coupon` has no `idempotencyKey`, so a retried create is a SECOND live Wix
    coupon rather than the first one again. Our conditional put on `COUPON#<codeUpper>` is what
    makes the retry converge: the replay LOSES the claim, no second Wix create is issued, and the
    row keeps the id the first attempt recorded.

    Read-by-code is deliberately NOT part of this rationale. V2b of
    `docs/execution/wix-contract-verification-20261002.md` measured `specification.code`
    carrying `$eq`, so coupons CAN be filtered by code - which is why the missing
    `idempotencyKey` is the single fact carrying verdict (B), and why `coupon_store` is kept for
    idempotency rather than for recovery of an id we could not otherwise read.
    """
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    transport.expect(method="POST", endpoint=wc.BASE,
                     body=fixture("wix_coupon_create_response.json"))
    payload = {"code": "WDSAMPLE10", "name": "Sample money off",
               "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
               "startTimeMs": START_MS,
               "minimumSubtotalPaise": 500000}

    # Driven through `handler.handler`, not `_create`, deliberately: the refusal-to-status
    # mapping lives in the dispatch's `except coupon_store.CouponError`, so calling `_create`
    # directly would measure the raise and not the answer a caller gets.
    first = handler.handler(_event(body=payload), None)
    assert first["statusCode"] == 201

    # The replay. NOTHING is queued for it, so a second Wix create would raise
    # `UnexpectedWixCall` - which is a BaseException and cannot be laundered into a 202 by the
    # dispatch's `except Exception`.
    replay = handler.handler(_event(body=payload), None)
    assert replay["statusCode"] == cs.CouponConflict.status == 409
    assert json.loads(replay["body"])["error"] == "CODE_ALREADY_EXISTS"

    assert transport.count(method="POST", endpoint=wc.BASE) == 1, "one create, not two"
    definitions = [key for key in store.rows if key.startswith(cs.PREFIX_DEFINITION)]
    assert definitions == [cs.PREFIX_DEFINITION + "WDSAMPLE10"], "one coupon, not two"
    assert store.rows[definitions[0]]["wixCouponId"] == "abeb638b-f9f4-4bb8-8fe7-2319504df6d9"


def test_an_unreadable_mirror_downgrades_the_read_rather_than_failing_it(
        transport, handler, monkeypatch):
    """Our row is the authority, so a Wix failure answers 200 with `PENDING_WIX`."""
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    row = cs.create(store, {"code": "WDSAMPLE10", "name": "Sample money off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
                            "startTimeMs": START_MS,
               "minimumSubtotalPaise": 500000}, clock=clock())
    cs.mark_mirrored(store, row["code"], "abeb638b-f9f4-4bb8-8fe7-2319504df6d9", clock=clock())
    transport.expect_http_error(
        method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9", status=500)

    response = handler._get(_event(route="GET /coupons/WDSAMPLE10",
                                   path={"code": "WDSAMPLE10"}),
                            origin="https://wecare.digital")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["mirror"]["state"] == cs.MIRROR_PENDING


def test_a_mirror_conflict_answers_409_with_the_conflict_code(transport, handler, monkeypatch):
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    row = cs.create(store, {"code": "WDSAMPLE10", "name": "Sample money off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
                            "startTimeMs": START_MS,
               "minimumSubtotalPaise": 500000}, clock=clock())
    cs.mark_mirrored(store, row["code"], "abeb638b-f9f4-4bb8-8fe7-2319504df6d9", clock=clock())
    foreign = fixture("wix_coupon_get_response.json")
    foreign["coupon"]["specification"]["code"] = "SOMEONE-ELSES"
    transport.expect(method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9",
                     body=foreign)

    response = handler._get(_event(route="GET /coupons/WDSAMPLE10",
                                   path={"code": "WDSAMPLE10"}),
                            origin="https://wecare.digital")
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "WIX_CODE_CONFLICT"


def test_no_handler_response_carries_a_float(transport, handler, monkeypatch):
    """The containment on the handler's own projection, driven by the float fixture."""
    store = coupons_table()
    monkeypatch.setattr(handler, "_coupons_table", lambda: store)
    row = cs.create(store, {"code": "WDSAMPLE10", "name": "Sample money off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
                            "startTimeMs": START_MS,
               "minimumSubtotalPaise": 500000}, clock=clock())
    cs.mark_mirrored(store, row["code"], "abeb638b-f9f4-4bb8-8fe7-2319504df6d9", clock=clock())
    transport.expect(method="GET", endpoint=f"{wc.BASE}/abeb638b-f9f4-4bb8-8fe7-2319504df6d9",
                     body=fixture("wix_coupon_get_response_float_amounts.json"))

    response = handler._get(_event(route="GET /coupons/WDSAMPLE10",
                                   path={"code": "WDSAMPLE10"}),
                            origin="https://wecare.digital")
    body = json.loads(response["body"])

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        else:
            yield value

    assert not [value for value in walk(body) if type(value) is float]


# ══ GROUP C — the Wix-native gift-card adapter ════════════════════════════════

def _digest_body(value: str) -> str:
    """The digest under the decoration, so the two derivations can be compared honestly."""
    return value.lower().removeprefix("wdgc").removeprefix("wd-gc-")


def test_the_three_derivations_are_deterministic_in_their_inputs_alone():
    """FIRST, because every keying claim below rests on it. No clock, no counter, no `secrets`.

    A fresh key on retry is how a replay becomes a second gift card, and `create` cannot detect
    that it happened.
    """
    for _ in range(3):
        assert wg.idempotency_key(reference_id=REFERENCE) == wg.idempotency_key(
            reference_id=REFERENCE)
        assert wg.card_code(reference_id=REFERENCE, pepper=PEPPER) == wg.card_code(
            reference_id=REFERENCE, pepper=PEPPER)
        assert wg.demo_code(reference_id=REFERENCE) == wg.demo_code(reference_id=REFERENCE)
    # Different references give different values, so determinism is not constancy.
    assert wg.card_code(reference_id="other", pepper=PEPPER) != wg.card_code(
        reference_id=REFERENCE, pepper=PEPPER)


def test_the_keyed_code_is_not_recoverable_from_a_logged_reference_id():
    """THE assertion that makes `card_code` keyed rather than merely long.

    `reference_id` may be logged IN FULL - the standing payments rule says so, deliberately, so
    a payment log line can be traced with no masked field. Any UNKEYED function of it is
    therefore recoverable by anyone who can read a log line, and a gift-card code recovered that
    way is spendable.

    Asserted in BOTH directions, plus the POSITIVE line for `demo_code` - that third assertion
    is the mutation test that makes the first two capable of failing. Without it, a `_digest_body`
    that returned `""` would satisfy neither-contains-the-other vacuously.
    """
    keyed = _digest_body(wg.card_code(reference_id=REFERENCE, pepper=PEPPER))
    key = _digest_body(wg.idempotency_key(reference_id=REFERENCE))
    demo = _digest_body(wg.demo_code(reference_id=REFERENCE))

    assert keyed and key and demo, "a vacuous digest body would pass the next two lines"
    assert keyed not in key
    assert key not in keyed
    # And the derivation that IS recoverable fails the same test, which is why it is demo-only.
    assert demo in key, (
        "demo_code and idempotency_key expose the same unkeyed sha256 digest of the same "
        "input, so either value yields the other - that is why demo_code is fenced from "
        "amplify/ by a structural guard")


def test_the_code_domain_tag_separates_it_from_the_stores_own_hmac():
    """A RECOMPUTATION, not a black-box check, and the message says so.

    `gift_card_store.code_hash` HMACs under the SAME `code_pepper` with the SAME construction
    over a caller-supplied string. The tag is prefixed to the MESSAGE, never to the output, so
    the two cannot collide for ANY input rather than merely for the inputs they happen to
    receive today. This assertion fails iff `CODE_DOMAIN_TAG` is removed.

    The shared input is a CODE-SHAPED string rather than `REFERENCE`, because `code_hash`
    normalises through `gift_card_store.normalise_code`, which refuses anything outside the
    documented 8-to-20-character shape - and `wd-gc-sample-2026-10-02` is 23 characters. The
    collision question is about the construction, not about which string is fed in.
    """
    shared = "WDGC0000TEST0001"
    untagged = ("WDGC" + gcs.code_hash(shared, pepper=PEPPER)[:16]).upper()
    assert wg.card_code(reference_id=shared, pepper=PEPPER) != untagged, (
        "this is the untagged construction recomputed; if it matches, CODE_DOMAIN_TAG is gone")
    # And the tag is on the message, so it separates for the keyed and unkeyed sides alike.
    import hmac as _hmac
    from hashlib import sha256 as _sha256
    tagged = ("WDGC" + _hmac.new(PEPPER.encode("utf-8"),
                                 wg.CODE_DOMAIN_TAG + shared.encode("utf-8"),
                                 _sha256).hexdigest()[:16]).upper()
    assert wg.card_code(reference_id=shared, pepper=PEPPER) == tagged


def test_both_codes_are_exactly_wixs_maximum_length():
    keyed = wg.card_code(reference_id=REFERENCE, pepper=PEPPER)
    demo = wg.demo_code(reference_id=REFERENCE)
    assert len(keyed) == len(demo) == wg.MAX_CODE_LENGTH == 20
    assert wg.MIN_CODE_LENGTH <= len(keyed) <= wg.MAX_CODE_LENGTH
    # `demo_code` asserted POSITIVELY against its own formula, not just by shape.
    import hashlib
    assert demo == ("WDGC" + hashlib.sha256(
        REFERENCE.encode("utf-8")).hexdigest()[:16]).upper()


def test_a_missing_pepper_is_refused_and_derives_nothing(transport):
    for bad in ("", None):
        with pytest.raises(wg.WixGiftCardError) as refusal:
            wg.card_code(reference_id=REFERENCE, pepper=bad)
        assert refusal.value.code == "A_PEPPER_IS_REQUIRED"
        assert refusal.value.code in wg.REFUSAL_CODES
    assert transport.requests == [], "a refusal costs no HTTP call"


@pytest.mark.parametrize("kwargs,expected", [
    ({"initial_value_paise": 2500.5}, "INVALID_AMOUNT"),
    ({"initial_value_paise": True}, "INVALID_AMOUNT"),
    ({"initial_value_paise": 0}, "INVALID_AMOUNT"),
    ({"initial_value_paise": wg.MAX_INITIAL_VALUE_PAISE + 1}, "INVALID_AMOUNT"),
    ({"currency": "USD"}, "INVALID_CURRENCY"),
    ({"code": "SHORT"}, "INVALID_CODE"),
    ({"code": "X" * 21}, "INVALID_CODE"),
    ({"source": "ORDER"}, "INVALID_SOURCE"),
    ({"idempotency_key": ""}, "INVALID_IDEMPOTENCY_KEY"),
    ({"idempotency_key": "k" * 101}, "INVALID_IDEMPOTENCY_KEY"),
    ({"expiration_iso": "not-a-date"}, "INVALID_EXPIRATION"),
])
def test_every_refusal_names_a_closed_code_and_costs_no_request(transport, kwargs, expected):
    """Every check runs BEFORE any amount is formatted and before any request is composed."""
    base = {"initial_value_paise": 250050, "code": wg.demo_code(reference_id=REFERENCE),
            "idempotency_key": wg.idempotency_key(reference_id=REFERENCE)}
    base.update(kwargs)
    with pytest.raises(wg.WixGiftCardError) as refusal:
        wg.WixGiftCards(wix_ecom._request).create(**base)
    assert refusal.value.code == expected
    assert refusal.value.code in wg.REFUSAL_CODES
    assert isinstance(refusal.value, RuntimeError), "mirrors wix_coupons.WixCouponError"
    assert transport.requests == []


@pytest.mark.parametrize("bad", ["", None, 123, "has/slash", "has?query"])
def test_a_bad_gift_card_id_is_refused_on_get_and_disable(transport, bad):
    for call in ("get", "disable"):
        with pytest.raises(wg.WixGiftCardError) as refusal:
            getattr(wg.WixGiftCards(wix_ecom._request), call)(bad)
        assert refusal.value.code == "INVALID_GIFT_CARD_ID"
    assert transport.requests == []


def test_a_gift_card_create_sends_exactly_the_documented_body(transport):
    """BYTE-EXACT, and the two optional keys are ABSENT rather than null.

    A `"code": null` is a different request from a request with no `code`, and the documented
    meaning of OMITTING `code` is *Wix generates one* - so sending `null` would be asking for an
    undocumented behaviour at a money boundary.
    """
    code = wg.demo_code(reference_id=REFERENCE)
    key = wg.idempotency_key(reference_id=REFERENCE)
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_miss_response.json"))
    transport.expect(method="POST", endpoint=wg.BASE,
                     body=fixture("wix_giftcard_create_response.json"))

    result = wg.WixGiftCards(wix_ecom._request).create(
        initial_value_paise=250050, code=code, idempotency_key=key)

    created = transport.requests[-1]
    assert created.method == "POST"
    assert created.url == "https://www.wixapis.com/gift-cards/v1/gift-cards"
    assert created.body == {
        "giftCard": {"initialValue": {"amount": "2500.50"}, "currency": "INR",
                     "source": "MANUAL", "code": code},
        "idempotencyKey": key,
    }
    parsed = json.loads(created.body_bytes.decode("utf-8"))
    assert type(parsed["giftCard"]["initialValue"]["amount"]) is str, (
        "Wix gift-card money is a decimal string, format DECIMAL_VALUE maxScale 2")
    assert parsed["giftCard"]["currency"] == "INR"
    assert parsed["giftCard"]["source"] == "MANUAL", "required by Wix, measured"
    assert "expirationDate" not in parsed["giftCard"]
    assert "orderInfo" not in parsed["giftCard"], "a false provenance claim"
    assert "notificationInfo" not in parsed["giftCard"], "a live customer email"
    assert result["resolved"] is False
    assert result["balancePaise"] == 250050


def test_an_expiry_is_merged_in_under_wixs_own_key(transport):
    transport.expect(method="POST", endpoint=wg.BASE,
                     body=fixture("wix_giftcard_create_response.json"))
    wg.WixGiftCards(wix_ecom._request).create(
        initial_value_paise=250050, code=None,
        idempotency_key=wg.idempotency_key(reference_id=REFERENCE),
        expiration_iso="2026-11-11T00:00:00Z")
    body = transport.requests[-1].body
    assert body["giftCard"]["expirationDate"] == "2026-11-11T00:00:00Z"
    assert "code" not in body["giftCard"], "omitted, so Wix generates one"


def test_create_resolves_before_it_generates_and_consumes_one_create(transport):
    """Enforced TWO ways: the typed queue, and a direct count of creates.

    The queue is `query(miss) -> create -> query(hit)`. A regression that issued a second
    `POST .../gift-cards` instead of a query would be refused at pop time by the typed queue -
    an untyped FIFO would hand it the queued query response and the test would pass while the
    adapter created two cards. The COUNT is the named enforcement, independent of the queue.

    The replay RE-DERIVES both identifiers from the reference rather than reusing them, which is
    what demonstrates the property instead of assuming it.
    """
    adapter = wg.WixGiftCards(wix_ecom._request)
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_miss_response.json"))
    transport.expect(method="POST", endpoint=wg.BASE,
                     body=fixture("wix_giftcard_create_response.json"))
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_by_code_response.json"))

    first = adapter.create(initial_value_paise=250050,
                           code=wg.demo_code(reference_id=REFERENCE),
                           idempotency_key=wg.idempotency_key(reference_id=REFERENCE))
    replay = adapter.create(initial_value_paise=250050,
                            code=wg.demo_code(reference_id=REFERENCE),
                            idempotency_key=wg.idempotency_key(reference_id=REFERENCE))

    assert transport.count(method="POST", endpoint=wg.BASE) == 1, "one create, not two"
    assert first["giftCardId"] == replay["giftCardId"]
    assert first["resolved"] is False
    assert replay["resolved"] is True
    # The query filters on the FULL code with `$eq`, which is the documented operator.
    query = transport.requests[0]
    assert query.body == {"query": {"filter": {
        "code": {"$eq": wg.demo_code(reference_id=REFERENCE)}}}}


def test_a_find_by_code_miss_is_an_empty_dict_not_a_raise(transport):
    """`{}` is the CONTRACT `create` resolves on. A `None` or a raise would both make the
    resolve path a try/except."""
    for name in ("wix_giftcard_query_miss_response.json",
                 "wix_giftcard_query_miss_no_key_response.json"):
        transport.expect(method="POST", endpoint=f"{wg.BASE}/query", body=fixture(name))
        assert wg.WixGiftCards(wix_ecom._request).find_by_code(
            wg.demo_code(reference_id=REFERENCE)) == {}


def test_two_matches_on_a_unique_code_is_refused_with_no_further_request(transport):
    """`code` is unique in Wix, so two matches mean the filter was NOT honoured as documented -
    a live possibility, since two Wix pages disagree about this API's operator map. Reading
    `giftCards[0]` under those conditions is a money read from an arbitrary row."""
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_two_matches_response.json"))
    with pytest.raises(wg.WixGiftCardError) as refusal:
        wg.WixGiftCards(wix_ecom._request).find_by_code(wg.demo_code(reference_id=REFERENCE))
    assert refusal.value.code == "AMBIGUOUS_CODE"
    assert len(transport.requests) == 1, "nothing further was asked, and nothing was created"


def test_a_resolve_hit_onto_a_disabled_expired_card_is_reported_not_refused(transport):
    """Minting a second card for one reference is the WORSE failure, and it is the failure this
    adapter exists to prevent. So the dead card comes back, with both facts on it."""
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_disabled_response.json"))
    result = wg.WixGiftCards(wix_ecom._request).create(
        initial_value_paise=250050, code=wg.demo_code(reference_id=REFERENCE),
        idempotency_key=wg.idempotency_key(reference_id=REFERENCE))

    assert transport.count(method="POST", endpoint=wg.BASE) == 0, "no create was issued"
    assert result["resolved"] is True
    assert result["disabled"] is True
    # Returned VERBATIM and unparsed: this adapter makes no expiry decision.
    assert result["expirationDate"] == "2027-10-02T00:00:00Z"


def test_the_seven_key_view_is_the_same_on_every_branch(transport):
    """Three subjects, one helper, because branch-independence is the property.

    A finder with six keys and a creator with seven would need two normalisers and two
    assertions, which is how a five-versus-seven drift gets in.
    """
    adapter = wg.WixGiftCards(wix_ecom._request)
    subjects = []

    transport.expect(method="POST", endpoint=wg.BASE,
                     body=fixture("wix_giftcard_create_response.json"))
    subjects.append(("create", adapter.create(
        initial_value_paise=250050, code=None,
        idempotency_key=wg.idempotency_key(reference_id=REFERENCE))))

    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_by_code_response.json"))
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_query_by_code_response.json"))
    subjects.append(("resolve hit", adapter.create(
        initial_value_paise=250050, code=wg.demo_code(reference_id=REFERENCE),
        idempotency_key=wg.idempotency_key(reference_id=REFERENCE))))
    subjects.append(("find_by_code", adapter.find_by_code(
        wg.demo_code(reference_id=REFERENCE))))

    for label, view in subjects:
        assert set(view) == set(wg.VIEW_KEYS), (
            f"{label} returned {sorted(view)}; the view must not depend on which branch "
            f"produced it")
        assert type(view["balancePaise"]) is int
        assert view["currency"] == "INR"
        assert isinstance(view["disabled"], bool)
        assert view["codeLast4"] == "8FA8"


def test_code_last4_is_wixs_own_code_suffix_and_never_a_parse_of_the_code(transport):
    """Absent or not exactly four characters is a REFUSAL, with no fallback to slicing bearer
    value. A fallback that parses bearer value is the one place a rule must not be lenient."""
    for mangled in ({}, {"codeSuffix": "ABC"}, {"codeSuffix": 8}, {"codeSuffix": "TOOLONG"}):
        response = fixture("wix_giftcard_create_response.json")
        response["giftCard"].pop("codeSuffix", None)
        response["giftCard"].update(mangled)
        transport.expect(method="POST", endpoint=wg.BASE, body=response)
        with pytest.raises(wg.WixGiftCardError) as refusal:
            wg.WixGiftCards(wix_ecom._request).create(
                initial_value_paise=250050, code=None,
                idempotency_key=wg.idempotency_key(reference_id=REFERENCE))
        assert refusal.value.code == "CODE_SUFFIX_MISSING"


def test_a_fractional_rupee_amount_survives_the_wix_decimal_boundary_both_ways():
    """The single strongest technical argument for the Wix-native model, asserted exactly.

    Wix gift-card amounts are `DECIMAL_VALUE` with `maxScale: 2`, so integer paise cross the
    boundary and come back with no float anywhere.
    """
    assert Money(250050).to_wix() == "2500.50"
    back = Money.from_wix("2500.50")
    assert type(back.paise) is int
    assert back.paise == 250050
    assert Money.from_wix("999.75").paise == 99975
    # And a float is refused at the boundary rather than coerced. This is the third proof that
    # no float reaches a money value - the other two are the type assertions above and the AST
    # gate in Group D. `float` itself is NOT monkeypatched: the `json` decoder binds
    # `parse_float` at construction, so the patch would be inert and would only risk pytest.
    with pytest.raises(ValueError):
        Money.from_wix(10.0)
    with pytest.raises(ValueError):
        Money.from_wix("2500.505")


def test_the_balance_is_read_back_off_the_query_response_in_integer_paise(transport):
    """One request, not two: `balance` is on the Query response, measured."""
    transport.expect(method="POST", endpoint=f"{wg.BASE}/query",
                     body=fixture("wix_giftcard_balance_after_redeem.json"))
    view = wg.WixGiftCards(wix_ecom._request).find_by_code(
        wg.demo_code(reference_id=REFERENCE))
    assert view["balancePaise"] == 99975
    assert type(view["balancePaise"]) is int
    assert len(transport.requests) == 1


def test_disable_is_a_post_to_the_disable_subresource_and_there_is_no_delete(transport):
    transport.expect(method="POST", endpoint=f"{wg.BASE}/card-1/disable", body={})
    wg.WixGiftCards(wix_ecom._request).disable("card-1")
    assert transport.requests[-1].url.endswith("/gift-cards/v1/gift-cards/card-1/disable")
    assert not hasattr(wg.WixGiftCards, "delete"), "Wix has no delete; disable is the whole of it"


def test_a_gift_card_wix_failure_of_any_status_escapes_as_a_status_only_message(transport):
    for status in (400, 409, 428, 500, 502):
        transport.expect_http_error(method="POST", endpoint=wg.BASE, status=status)
        with pytest.raises(wix_ecom.WixEcomError) as failure:
            wg.WixGiftCards(wix_ecom._request).create(
                initial_value_paise=250050, code=None,
                idempotency_key=wg.idempotency_key(reference_id=REFERENCE))
        assert str(status) in str(failure.value)


# ══ GROUP D — the structural guarantees ══════════════════════════════════════

def _amplify_python_files() -> list:
    # `node_modules` is excluded because `amplify/node_modules` is untracked vendored
    # code (aws-cdk-lib custom-resource handlers). An import gate that reads it lets a
    # dependency, rather than a handler of ours, decide whether the gate passes.
    return sorted(path for path in AMPLIFY.rglob("*.py")
                  if "__pycache__" not in path.parts
                  and "node_modules" not in path.parts)


def test_no_handler_imports_the_wix_native_adapter():
    """The guard that makes "demonstrate, then verify live, then wire and retire" hold.

    The module cannot reach production by drift, only by somebody adding an import and deleting
    this test. It ships in no Lambda package until some handler imports it, because
    `scripts/deploy_all_lambdas.py` packages per-function sources.
    """
    importers = []
    for path in _amplify_python_files():
        if path.resolve() == ADAPTER.resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "wix_gift_cards" in str(node.module or ""):
                importers.append(str(path))
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "wix_gift_cards" for alias in node.names):
                    importers.append(str(path))
            if isinstance(node, ast.Import):
                if any("wix_gift_cards" in alias.name for alias in node.names):
                    importers.append(str(path))
    assert importers == [], f"wix_gift_cards is imported by {importers}, so it is now wired"


def test_the_adapter_imports_none_of_the_four_modules_that_reach_outside_the_process():
    """A DENYLIST, deliberately, and this is said rather than left to be discovered.

    An allowlist assertion here would fail on correct code: the module legitimately imports
    `hashlib`, `hmac`, `datetime` and the shared money types, and that enumeration is
    DESCRIPTIVE. The asserted rule is the four modules that reach outside.
    """
    imports = {alias.name.split(".")[0] for node in ast.walk(ADAPTER_TREE)
               if isinstance(node, ast.Import) for alias in node.names}
    imports |= {(node.module or "").split(".")[0] for node in ast.walk(ADAPTER_TREE)
                if isinstance(node, ast.ImportFrom)}
    for forbidden in ("boto3", "botocore", "urllib", "os"):
        assert forbidden not in imports, f"{forbidden} reaches outside the process"

    attributes = {node.func.attr for node in ast.walk(ADAPTER_TREE)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("get_secret_value", "batch_get_secret_value", "client", "resource"):
        assert forbidden not in attributes


def test_no_file_under_amplify_references_the_demo_only_derivation():
    """An AST walk over `ast.Attribute`, `ast.Name` and `ast.ImportFrom` ONLY.

    NOT `FunctionDef.name`, and not a text grep: `wix_gift_cards.py` is itself under `amplify/`
    and DEFINES `demo_code`, and its docstrings necessarily name it. Walking references rather
    than definitions means the adapter needs no special case, which is what keeps the gate
    honest rather than exempted.
    """
    referencing = []
    for path in _amplify_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "demo_code":
                referencing.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.Name) and node.id == "demo_code":
                referencing.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "demo_code" for alias in node.names):
                referencing.append(f"{path}:{node.lineno}")
    assert referencing == [], (
        f"demo_code is UNKEYED and its value is recoverable from a logged reference_id; "
        f"production must use card_code. Referenced at {referencing}")


def test_the_pepper_is_keyword_only_with_no_default():
    """A defaulted pepper is an unkeyed code wearing a keyed function's name."""
    function = next(node for node in ast.walk(ADAPTER_TREE)
                    if isinstance(node, ast.FunctionDef) and node.name == "card_code")
    names = [arg.arg for arg in function.args.kwonlyargs]
    assert "pepper" in names
    assert function.args.kw_defaults[names.index("pepper")] is None, (
        "pepper must have no default")
    assert function.args.args == [], "both parameters are keyword-only"


def test_the_adapter_holds_no_logger_and_cannot_print():
    """Not "must not log the code" - the code must not APPEAR in a logging expression at all.

    CodeQL tracks taint across function boundaries and has already failed this build twice on a
    ternary over a key's truthiness, so the module simply has no logging surface.

    Over the AST, NOT the text, for the same reason the payment-vocabulary gate does: the
    paragraph explaining why this module holds no logger necessarily contains the word
    `logger`. A text grep here would fail on the code that is correct.
    """
    names = {node.id for node in ast.walk(ADAPTER_TREE) if isinstance(node, ast.Name)}
    assert "print" not in names
    assert "logger" not in names
    imports = {alias.name.split(".")[0] for node in ast.walk(ADAPTER_TREE)
               if isinstance(node, ast.Import) for alias in node.names}
    imports |= {(node.module or "").split(".")[0] for node in ast.walk(ADAPTER_TREE)
                if isinstance(node, ast.ImportFrom)}
    assert "logging" not in imports
    # And no assignment creates one, however it is spelled.
    assigned = {target.id for node in ast.walk(ADAPTER_TREE)
                if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)}
    assert not {name for name in assigned if "logger" in name.lower()}


def test_the_identifier_float_appears_in_neither_the_adapter_nor_the_demo():
    """By AST, over both files. The third of the three no-float proofs."""
    for path in (ADAPTER, DEMO):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders = [f"{path.name}:{node.lineno}" for node in ast.walk(tree)
                     if isinstance(node, ast.Name) and node.id == "float"]
        assert offenders == [], offenders


def test_the_staff_gate_the_harness_stubs_is_the_real_one():
    """`_staff` is stubbed, so this asserts what the stub stands in for.

    Otherwise Group B would prove the handler works with authentication REMOVED and say nothing
    about the handler as shipped.
    """
    path = ROOT / "amplify/functions/ecommerce/coupons/handler.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "_staff")
    rendered = ast.unparse(function)
    assert "middleware.require_auth" in rendered
    assert "STAFF_ROLE" in rendered


def test_the_whole_harness_built_no_secrets_manager_client():
    """Corroborated from OUTSIDE any stubbed call, which is why it is a plain assert."""
    assert wix_ecom._secrets is None


# ══ GROUP E — the INVOICE leg of the same walk-through ════════════════════════

def test_the_invoice_leg_discounts_by_the_very_amount_it_sent_to_wix(transport):
    """The one walk-through continued onto the third surface, and the no-drift proof.

    Groups A-D follow one coupon out to Wix and one card through the ledger. This continues the
    SAME coupon onto the invoice surface, which is the only surface with no Wix cart to ask -
    `Calculate Cart` is what answers "what is this coupon worth" on the website, and a Pay Flow
    invoice has no cart to calculate. So the amount has to come from our own stored definition,
    and the risk is obvious: two readings of one coupon, one by Wix and one by us, that agree on
    the day they are written and drift afterwards.

    They cannot drift, because they read the SAME stored attribute. `wix_coupons.specification`
    turns `moneyOffPaise` into the whole-rupee `moneyOffAmount` on the wire;
    `coupon_store.discount_paise` discounts by that same `moneyOffPaise`. This asserts the two
    against each other in paise, through the figure actually sent over the transport.
    """
    transport.expect(method="POST", endpoint=wc.BASE,
                     body=fixture("wix_coupon_create_response.json"))
    store = coupons_table()
    row = cs.create(store, {"code": "WDSAMPLE10", "name": "Sample money off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 12345600,
                            "startTimeMs": START_MS, "minimumSubtotalPaise": 500000,
                            "usageLimit": 10, "limitPerCustomer": 1}, clock=clock())
    wix_coupon_id = wc.WixCoupons(wix_ecom._request).create(row)
    cs.mark_mirrored(store, "WDSAMPLE10", wix_coupon_id, clock=clock())

    sent_rupees = json.loads(
        transport.requests[-1].body_bytes.decode("utf-8"))["specification"]["moneyOffAmount"]

    # The invoice surface: a collection in integer paise, priced by the module that owns the
    # definition. No cart, no network, no clock.
    definition_row = cs.get_definition(store, "WDSAMPLE10")
    collection_paise = 20000000
    discount = cs.discount_paise(definition_row, collection_paise=collection_paise)

    assert discount == definition_row["moneyOffPaise"]
    assert discount == sent_rupees * cs.PAISE_PER_RUPEE
    assert type(discount) is int

    # And the whole invoice money path, in the documented order: coupon into the fee basis, card
    # off the final total. The fee really falls, which is what makes the coupon a price change.
    applied = redemption.apply_coupon(code="WDSAMPLE10",
                                      collection_before_discount_paise=collection_paise,
                                      cart_ref="WD-PAY-SAMPLE01",
                                      provider=_StoreProvider(store))
    quote = cp.compute_quote(applied.discounted_collection_paise)
    assert applied.discount_paise == discount
    assert quote.convenience_fee_paise < cp.compute_quote(collection_paise).convenience_fee_paise
    assert quote.total_payable_paise == (applied.discounted_collection_paise
                                         + quote.convenience_fee_paise
                                         + quote.convenience_gst_paise)


class _StoreProvider(srp.StoreRedemptionProvider):
    """The real provider over one table, with no gift-card table and no secret reader needed.

    Subclassed rather than hand-written so this cannot become a second provider: `validate_coupon`
    and `read_gift_card` are inherited untouched, and only the construction is narrowed to the
    coupon half the test exercises. A gift-card read here would raise on the `None` reader, which
    is the correct failure for a collaborator a test did not supply.
    """

    def __init__(self, coupons_table) -> None:
        # AFTER the fixture's `startTimeMs`, or `evaluate` answers `NOT_STARTED`. The sample's
        # coupon starts in the future relative to `NOW`, which is what every other group here
        # relies on; this leg needs a clock past it to exercise an ELIGIBLE verdict.
        super().__init__(coupons_table=coupons_table, gift_cards_table=None,
                         secret_reader=None, clock=clock(START_MS // 1000 + 10))
