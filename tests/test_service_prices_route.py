"""`GET /ecommerce/service-prices`: anonymous, input-free, edge-cached, and fails closed.

Drives the SHIPPED `checkout/handler.py` through the contribution harness, with a purpose-built
Wix fake for the three Cart V2 calls this arm makes (`create`, `get`, `estimate`). Offline:
FakeDynamo, no network, no credential.

The two properties worth stating, because they are what justify an unauthenticated route:

* `require_customer` is never reached on the GET -- asserted by replacing it with a function that
  raises, so a regression that moved the arm below the auth gate fails loudly rather than quietly
  turning the price into a signed-in-only read.
* nothing a caller supplies reaches Wix -- asserted by sending a query string and a body and
  comparing the Wix call log against the clean case for equality.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import KEYS_TABLE, body_of, make_env  # noqa: E402
from lambda_utils.ecommerce import service_pricing  # noqa: E402

PRODUCT = "df976a0a-f582-4535-b2e1-d532f348bd27"
SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
AMEND = "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b"
DROP_DOCS = "db166bc8-a763-41ec-9f65-0f718f18155a"
VAULT = "dcff995e-448c-493a-9259-f6a82ccdc2b4"

#: Four DIFFERENT figures, and none of them the prices live today, so a pass cannot be a leaked
#: constant. `{variant: rupees}`.
RUPEES = {SUBMIT: 149, AMEND: 201, DROP_DOCS: 450, VAULT: 77}
PAISE = {variant: rupees * 100 for variant, rupees in RUPEES.items()}

CART_IDS = {SUBMIT: "11111111-1111-4111-8111-111111111111",
            AMEND: "22222222-2222-4222-8222-222222222222",
            DROP_DOCS: "33333333-3333-4333-8333-333333333333",
            VAULT: "44444444-4444-4444-8444-444444444444"}


class PriceWix:
    """The three Cart V2 calls the price arm makes, and nothing else."""

    def __init__(self, *, unpriced=(), fail=()):
        self.unpriced = set(unpriced)
        self.fail = set(fail)
        self.calls = []
        self._variant_of = {cart: variant for variant, cart in CART_IDS.items()}

    def __call__(self, endpoint, method="GET", body=None):
        method = method.upper()
        self.calls.append((method, endpoint, json.dumps(body, sort_keys=True)))
        if endpoint == "/ecom/v2/carts" and method == "POST":
            variant = body["catalogItems"][0]["catalogReference"]["options"]["variantId"]
            if variant in self.fail:
                raise RuntimeError("wix refused")
            return {"cart": self._cart(CART_IDS[variant])}
        if endpoint.endswith("/estimate") and method == "POST":
            cart_id = endpoint.split("/")[-2]
            variant = self._variant_of[cart_id]
            if variant in self.unpriced:
                return {"cart": self._cart(cart_id), "summary": {"priceSummary": {}}}
            return {"cart": self._cart(cart_id),
                    "summary": {"priceSummary": {"subtotal": {"amount": f"{RUPEES[variant]}.00"}},
                                "violations": []}}
        # Any other GET: the cart itself.
        cart_id = endpoint[len("/ecom/v2/carts/"):].split("/")[0]
        return {"cart": self._cart(cart_id)}

    @classmethod
    def _cart(cls, cart_id, currency="INR"):
        money = {"currencyCode": currency}
        # LINE ITEMS ARE PART OF THE SHAPE, because the resolver's reuse path checks that a cart
        # read back from a pointer row actually holds the variant it is being priced for. A fake
        # that answered a cart with no lines would make every reuse look like a wrong cart and
        # hide the pointer bound this file asserts.
        variant = {c: v for v, c in CART_IDS.items()}.get(cart_id)
        return {"id": cart_id, "revision": "1", "businessInfo": dict(money),
                "customerInfo": dict(money), "paymentInfo": dict(money),
                "lineItems": [cls._line(variant)] if variant else []}

    @staticmethod
    def _line(variant):
        return {"id": "line-" + variant[:8],
                "source": {"catalogReference": {
                    "appId": "215238eb-22a5-4c36-9e7b-e7c08025e04e",
                    "catalogItemId": PRODUCT, "options": {"variantId": variant}}},
                "quantityInfo": {"requestedQuantity": 1, "confirmedQuantity": 1}}

    def creates(self):
        return [call for call in self.calls if call[1] == "/ecom/v2/carts"]


def prices_event(*, method="GET", path="/ecommerce/service-prices", query=None, body=None,
                 authorization=None):
    headers = {"origin": "https://wecare.digital"}
    if authorization:
        headers["authorization"] = authorization
    event = {
        "requestContext": {"http": {"method": method, "sourceIp": "203.0.113.5"}},
        "headers": headers,
        "rawPath": path,
    }
    if query is not None:
        event["queryStringParameters"] = query
    if body is not None:
        event["body"] = json.dumps(body)
    return event


@pytest.fixture(autouse=True)
def _clean_cache():
    service_pricing.reset_cache()
    yield
    service_pricing.reset_cache()


def _env(monkeypatch, wix=None):
    h, fake, wix = make_env(monkeypatch, wix=wix if wix is not None else PriceWix())

    def never(event):
        raise AssertionError("the public price arm must not reach require_customer")

    monkeypatch.setattr(h.customer_auth, "require_customer", never)
    return h, fake, wix


# ── the anonymous read ────────────────────────────────────────────────────────

def test_the_get_answers_without_a_session_and_prices_every_slug(monkeypatch):
    h, _fake, _wix = _env(monkeypatch)
    response = h.handler(prices_event(), None)
    assert response["statusCode"] == 200, body_of(response)
    assert body_of(response) == {"currency": "INR", "prices": {
        "submit-request": {"available": True, "paise": PAISE[SUBMIT]},
        "request-amendment": {"available": True, "paise": PAISE[AMEND]},
        "drop-docs": {"available": True, "paise": PAISE[DROP_DOCS]},
        "vault": {"available": True, "paise": PAISE[VAULT]},
    }}


def test_the_four_slugs_carry_four_DIFFERENT_prices(monkeypatch):
    """The owner's report was "each is a different item". One payload, four distinct figures."""
    h, _fake, _wix = _env(monkeypatch)
    prices = body_of(h.handler(prices_event(), None))["prices"]
    assert len({price["paise"] for price in prices.values()}) == 4


def test_the_response_is_edge_cacheable_for_sixty_seconds(monkeypatch):
    h, _fake, _wix = _env(monkeypatch)
    response = h.handler(prices_event(), None)
    assert response["headers"]["Cache-Control"] == "public, max-age=60"
    assert response["headers"]["Cache-Control"] == \
        f"public, max-age={service_pricing.CACHE_SECONDS}"


def test_a_cacheable_response_cannot_serve_one_origin_anothers_cors_header(monkeypatch):
    """The one response in this handler a SHARED cache may store, so it must not name one origin.

    `response.cors_headers` reflects whichever of the apex and `www` asked. Measured on
    2026-10-08: the `/api/*` edge caches a `public, max-age` response, STRIPS the origin's
    `Vary: Origin`, and served a request carrying `Origin: https://www.wecare.digital` the cached
    apex `Access-Control-Allow-Origin`. A browser rejects that, `fetchServicePrices` fails closed,
    and every `www` visitor reads "temporarily unavailable" with no way to buy.

    `*` is the fix the measurement forces, because `Vary: Origin` alone is inert at that edge. It
    is legal and safe for THIS body only: a public price list with no customer data, no
    credential and no cookie, fetched without credentials.
    """
    h, _fake, _wix = _env(monkeypatch)
    for origin in ("https://wecare.digital", "https://www.wecare.digital",
                   "https://example.invalid", None):
        service_pricing.reset_cache()
        event = prices_event()
        if origin is None:
            event["headers"].pop("origin", None)
        else:
            event["headers"]["origin"] = origin
        headers = h.handler(event, None)["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*", origin
        # Sent anyway, for an intermediary that does honour it and so a future return to a
        # reflected origin is not silently poisoned.
        assert headers["Vary"] == "Origin", origin


def test_only_the_cacheable_arm_widens_cors(monkeypatch):
    """The 503s stay on the reflected origin: nothing caches them, so there is nothing to mix."""
    h, _fake, wix = _env(monkeypatch)
    monkeypatch.delenv("WIX_CART_V2_ENABLED", raising=False)
    headers = h.handler(prices_event(), None)["headers"]
    assert headers["Access-Control-Allow-Origin"] == "https://wecare.digital"
    assert "Cache-Control" not in headers
    assert wix.calls == []


def test_nothing_the_caller_supplies_reaches_wix(monkeypatch):
    """A query string and a body on the GET change the Wix call log not at all."""
    h, _fake, clean = _env(monkeypatch)
    h.handler(prices_event(), None)
    service_pricing.reset_cache()
    h2, _f2, dirty = _env(monkeypatch, wix=PriceWix())
    h2.handler(prices_event(query={"variantId": "../../etc", "paise": "1"},
                            body={"productId": "someone-elses"}), None)
    assert [(m, e) for m, e, _b in dirty.calls] == [(m, e) for m, e, _b in clean.calls]
    assert [body for _m, _e, body in dirty.calls] == [body for _m, _e, body in clean.calls]


def test_the_pointer_rows_bound_wix_cart_creation_to_four_forever(monkeypatch):
    h, fake, wix = _env(monkeypatch)
    h.handler(prices_event(), None)
    assert len(wix.creates()) == 4
    pointers = [row for row in fake.all_rows(KEYS_TABLE)
                if str(row["orderId"]).startswith(service_pricing.SERVICE_PRICE_CART_PREFIX)]
    assert len(pointers) == 4
    # A cold resolver on the same table reuses them and creates nothing.
    service_pricing.reset_cache()
    again = PriceWix()
    monkeypatch.setattr(h, "_wix_request", again)
    h.handler(prices_event(), None)
    assert again.creates() == []


# ── the authenticated chain is untouched ──────────────────────────────────────

def test_a_post_to_the_same_path_still_requires_a_session(monkeypatch):
    h, _fake, _wix = _env(monkeypatch)
    with pytest.raises(AssertionError, match="must not reach require_customer"):
        h.handler(prices_event(method="POST"), None)


@pytest.mark.parametrize("path", ["/ecommerce/prepare-checkout", "/ecommerce/checkout",
                                  "/ecommerce/service-prices/extra", "/service-prices"])
def test_only_the_exact_path_is_public(monkeypatch, path):
    h, _fake, _wix = _env(monkeypatch)
    with pytest.raises(AssertionError, match="must not reach require_customer"):
        h.handler(prices_event(path=path), None)


def test_a_trailing_slash_is_the_same_route(monkeypatch):
    h, _fake, _wix = _env(monkeypatch)
    assert h.handler(prices_event(path="/ecommerce/service-prices/"), None)["statusCode"] == 200


# ── fail closed ───────────────────────────────────────────────────────────────

def test_one_unpriceable_slug_leaves_the_other_three_on_sale(monkeypatch):
    h, _fake, _wix = _env(monkeypatch, wix=PriceWix(unpriced={VAULT}))
    response = h.handler(prices_event(), None)
    assert response["statusCode"] == 200, body_of(response)
    prices = body_of(response)["prices"]
    assert prices["vault"] == {"available": False}
    assert "paise" not in prices["vault"]
    assert all(prices[slug]["available"] for slug in
               ("submit-request", "request-amendment", "drop-docs"))


def test_no_price_at_all_is_a_503_rather_than_an_empty_payload(monkeypatch):
    """An empty payload is a number a browser could read as free. 503 cannot be misread."""
    h, _fake, _wix = _env(monkeypatch, wix=PriceWix(fail=set(CART_IDS)))
    response = h.handler(prices_event(), None)
    assert response["statusCode"] == 503
    assert body_of(response) == {"error": "SERVICE_PRICES_UNAVAILABLE"}


def test_cart_v2_off_is_a_503_before_any_wix_call(monkeypatch):
    h, _fake, wix = _env(monkeypatch)
    # AFTER `_env`, because the harness sets the flag on as part of loading the handler.
    monkeypatch.delenv("WIX_CART_V2_ENABLED", raising=False)
    response = h.handler(prices_event(), None)
    assert response["statusCode"] == 503
    assert body_of(response) == {"error": "SERVICE_PRICES_UNAVAILABLE"}
    assert wix.calls == []


def test_the_payload_never_carries_a_float(monkeypatch):
    h, _fake, _wix = _env(monkeypatch)
    raw = h.handler(prices_event(), None)["body"]
    assert "." not in raw.replace("INR", "")
    def walk(value):
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
    walk(json.loads(raw))
