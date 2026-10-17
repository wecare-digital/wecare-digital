"""`GET /ecommerce/service-prices`: anonymous, input-free, fails closed — AWS-native.

Drives the SHIPPED `checkout/handler.py` with CATALOG_SOURCE=aws and a stubbed native
variant reader (ProductsTable), so no network call is made. Pins the two properties that
justify an unauthenticated route:
  * require_customer is never reached on the GET (regression that moved the arm
    below the auth gate fails loudly),
  * nothing a caller supplies changes the answer (query/body ignored).
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import body_of, make_env  # noqa: E402

# The five service variants (same UUIDs the live catalog uses), with distinct test prices.
SUBMIT = "22222222-2222-4222-8222-222222222222"
AMEND = "33333333-3333-4333-8333-333333333333"
DROP_DOCS = "44444444-4444-4444-8444-444444444444"
VAULT = "55555555-5555-4555-8555-555555555555"
PICKUP = "66666666-6666-4666-8666-666666666666"
PAISE = {SUBMIT: 14900, AMEND: 20100, DROP_DOCS: 45000, VAULT: 7700, PICKUP: 28800}


def _reader(priced=None, unpriced=()):
    """A native variant reader: variant_id -> {priceMinor, currency, status} or None."""
    priced = PAISE if priced is None else priced
    unpriced = set(unpriced)

    def read(variant_id):
        if variant_id in unpriced or variant_id not in priced:
            return None
        return {"priceMinor": priced[variant_id], "currency": "INR", "status": "active"}
    return read


def prices_event(*, method="GET", query=None, body=None):
    return {"httpMethod": method, "path": "/ecommerce/service-prices", "headers": {},
            "queryStringParameters": query, "body": body}


def _native_env(monkeypatch, reader=None):
    h, fake, _catalog = make_env(monkeypatch)
    monkeypatch.setenv("CATALOG_SOURCE", "aws")
    monkeypatch.setattr(h, "_native_variant_reader", lambda: (reader or _reader()))
    return h


def test_native_route_prices_every_slug(monkeypatch):
    h = _native_env(monkeypatch)
    resp = h.handler(prices_event(), None)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert body["currency"] == "INR"
    assert all(v.get("available") for v in body["prices"].values())
    assert len(body["prices"]) >= 4


def test_native_route_never_reaches_customer_auth(monkeypatch):
    h = _native_env(monkeypatch)

    def never(_event):
        raise AssertionError("the public price arm must not reach require_customer")
    monkeypatch.setattr(h.customer_auth, "require_customer", never)
    resp = h.handler(prices_event(), None)
    assert resp["statusCode"] == 200


def test_native_route_ignores_caller_input(monkeypatch):
    h = _native_env(monkeypatch)
    clean = body_of(h.handler(prices_event(), None))
    dirty = body_of(h.handler(prices_event(query={"variantId": "x"},
                                           body=json.dumps({"inject": True})), None))
    assert clean == dirty


def test_native_route_fails_closed_when_nothing_prices(monkeypatch):
    h = _native_env(monkeypatch, reader=_reader(priced={}))  # reader resolves nothing
    resp = h.handler(prices_event(), None)
    assert resp["statusCode"] == 503
    assert body_of(resp)["error"] == "SERVICE_PRICES_UNAVAILABLE"


def test_native_route_partial_prices_the_rest(monkeypatch):
    h = _native_env(monkeypatch, reader=_reader(unpriced={VAULT}))
    resp = h.handler(prices_event(), None)
    assert resp["statusCode"] == 200
    prices = body_of(resp)["prices"]
    available = [s for s, v in prices.items() if v.get("available")]
    unavailable = [s for s, v in prices.items() if not v.get("available")]
    assert available and unavailable  # one unpriced slug does not take the others down
