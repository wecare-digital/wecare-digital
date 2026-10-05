"""A Wix cart that is GONE is reminted; only a missing ITEM says "no longer available".

The live failure this pins
-------------------------
2026-10-05T23:33, `/aws/lambda/wecare-checkout`::

    {"event": "website_checkout_catalogue_unavailable", "error": "WixEcomError",
     "detail": "Wix eCom GET /ecom/v2/carts/91e2c29a-5efe-49ba-bd19-64ae3d39a7cb
                returned HTTP 404"}

The customer saw "An item in your cart is no longer available. Remove it and try again" and could
not pay. The item was fine: the ₹1 test product `121c9d57-...` was `visible=True`, `IN_STOCK`, and
its variant `c2edc783-...` visible on the migrated site. What was gone was the CART -- a
`CUSTOMERCART#` pointer minted against the previous Wix site, which `CustomerCart.ensure` keeps for
thirty days and which `GET /ecom/v2/carts/{id}` answers 404 for on site `c993128b`.

Two facts made that a dead end rather than a hiccup:

* `_website_prepare` had ONE `except wix_ecom.WixEcomError` arm, and a 404 on a cart is
  indistinguishable there from a 404 on a product, so a dead cart was reported as a dead item.
* removing a line from a cart that does not exist is not an action anybody can take, and the
  pointer survives for thirty days, so EVERY retry produced the same sentence.

What each test below pins
-------------------------
* `CartV2.get` maps a 404 to `cart_v2.CartGone` and nothing else to it, read off a STRUCTURED
  `.status` rather than a substring of the message.
* A seeded pre-migration pointer leads to a fresh cart and a 200, not a refusal.
* The dead pointer is actually dropped, so the next request does not repeat the recovery.
* Recovery is ONCE. `ensure` creates a cart per attempt and abandons it on the live site with
  nothing to clean it up, so a loop here would leak carts.
* The money does not move. The amount the gateway is asked for after a recovery is byte-identical
  to the amount for the same basket with no stale pointer at all -- the replacement cart is priced
  from Wix's own `summary.priceSummary` by `calculate`, never from anything carried over.
* A genuinely missing item STILL says "no longer available", in both of its shapes: the product
  GET 404 (`CART_ITEM_UNAVAILABLE`) and a line Wix reports as off the catalogue
  (`ITEMS_UNAVAILABLE`).
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import (  # noqa: E402
    KEYS_TABLE, body_of, create_event, make_env, pointer, prepare_event, seed_cart_pointer)
from contribution_wix import (  # noqa: E402
    CART_ID, KIOSK_ID, KIOSK_VARIANT, REPLACEMENT_CART_ID, ContributionWix, kiosk_line, saved)

from lambda_utils import wix_ecom  # noqa: E402
from lambda_utils.ecommerce import cart_v2  # noqa: E402


def events_of(caplog):
    return [json.loads(record.message) for record in caplog.records
            if record.message.startswith("{")]


# ══ the adapter-level distinction ═══════════════════════════════════════════════

def test_a_404_on_the_cart_resource_is_CartGone_carrying_the_dead_id():
    """The whole fix in one assertion: a cart 404 is about the CART, not about an item."""
    def transport(endpoint, method="GET", body=None):
        raise wix_ecom.http_error(method, endpoint, 404)

    with pytest.raises(cart_v2.CartGone) as gone:
        cart_v2.CartV2(transport).get(CART_ID)
    assert gone.value.cart_id == CART_ID.lower()
    # NOT the item exception. A caller that treats these the same is the live defect.
    assert not isinstance(gone.value, cart_v2.CartItemUnavailable)
    # Still a `CartContractError`, so a caller with no recovery answers its existing 409 rather
    # than a 500 or a transient 503 that invites a retry which cannot help.
    assert isinstance(gone.value, cart_v2.CartContractError)


@pytest.mark.parametrize("status", [400, 401, 403, 409, 429, 500, 502, 503])
def test_every_other_status_still_propagates_unchanged(status):
    """Only 404 means gone. Anything else keeps today's behaviour, which fails closed."""
    def transport(endpoint, method="GET", body=None):
        raise wix_ecom.http_error(method, endpoint, status)

    with pytest.raises(wix_ecom.WixEcomError) as failure:
        cart_v2.CartV2(transport).get(CART_ID)
    assert not isinstance(failure.value, cart_v2.CartGone)
    assert str(status) in str(failure.value)


def test_a_failure_with_no_readable_status_is_not_mistaken_for_a_missing_cart():
    """Fails CLOSED. An unknown failure must not be read as "the cart is gone" and silently
    trigger a cart creation -- `is_not_found` answers False unless it can SEE a 404."""
    def transport(endpoint, method="GET", body=None):
        raise wix_ecom.WixEcomError("Wix eCom GET /ecom/v2/carts/x returned HTTP 404")

    with pytest.raises(wix_ecom.WixEcomError):
        cart_v2.CartV2(transport).get(CART_ID)
    assert cart_v2.is_not_found(RuntimeError("404 everywhere in the prose")) is False
    assert cart_v2.is_not_found(wix_ecom.http_error("GET", "/x", 404)) is True


# ══ the checkout route ══════════════════════════════════════════════════════════

def gone_cart_env(monkeypatch, **over):
    """The live shape: a seeded `CUSTOMERCART#` pointer naming a cart Wix 404s."""
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          gone_cart_ids=[CART_ID], **over)
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)
    return h, fake, wix


def test_a_pre_migration_cart_is_replaced_and_the_customer_can_pay(monkeypatch, caplog):
    """The dead end is gone: a 200 with payable options, not `CART_ITEM_UNAVAILABLE`."""
    h, _fake, wix = gone_cart_env(monkeypatch)

    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([kiosk_line(1)]), None)

    assert response["statusCode"] == 200, body_of(response)
    assert body_of(response)["status"] == "CHECKOUT_OPTIONS_READY"
    assert wix.created_carts == [REPLACEMENT_CART_ID], \
        "one replacement cart, created from the request"

    recorded = events_of(caplog)
    gone = [event for event in recorded if event["event"] == "checkout_cart_gone_recreated"]
    assert len(gone) == 1
    assert gone[0]["goneCartId"] == CART_ID.lower()
    # The arm that used to answer must not fire at all.
    assert not [event for event in recorded
                if event["event"] == "website_checkout_catalogue_unavailable"]


def test_the_dead_pointer_is_dropped_so_the_recovery_does_not_repeat(monkeypatch):
    """`abandon` + `ensure` must leave the pointer naming the LIVE cart.

    A recovery that priced correctly but left the dead id in place would re-run on every request
    for thirty days, creating and abandoning one live Wix cart each time.
    """
    h, fake, _wix = gone_cart_env(monkeypatch)
    h.handler(prepare_event([kiosk_line(1)]), None)

    row = pointer(fake)
    assert row["wixCartId"] == REPLACEMENT_CART_ID
    assert CART_ID not in json.dumps(row, default=str)


def test_the_replacement_cart_holds_exactly_the_requested_basket(monkeypatch):
    """Created from `requested`, so the basket-equality backstop has nothing left to refuse."""
    h, _fake, wix = gone_cart_env(monkeypatch)
    response = h.handler(prepare_event([kiosk_line(2)]), None)

    assert response["statusCode"] == 200, body_of(response)
    created = [body for _method, path, body in wix.requests
               if path == "/ecom/v2/carts" and body]
    assert len(created) == 1
    reference = created[0]["catalogItems"][0]["catalogReference"]
    assert reference["catalogItemId"] == KIOSK_ID
    assert reference["options"]["variantId"] == KIOSK_VARIANT
    assert created[0]["catalogItems"][0]["quantity"] == 2
    # No reconcile commands: there is nothing to diff against a cart that was just built.
    assert wix.commands == []


def test_the_amount_is_unchanged_by_the_recovery(monkeypatch):
    """MONEY SAFETY, stated as an equality rather than as a claim.

    The replacement cart is re-priced by `cart_v2.calculate` from Wix's own
    `summary.priceSummary` in integer paise; nothing is carried over from the dead cart, which
    had no total of ours in the first place. So the gateway must be asked for exactly the figure
    the same basket produces with no stale pointer involved at all.
    """
    control_h, _control_fake, _control_wix = make_env(monkeypatch)
    assert control_h.handler(prepare_event([kiosk_line(1)]), None)["statusCode"] == 200
    expected = control_h.gateway_orders[0]["amount"]

    h, _fake, _wix = gone_cart_env(monkeypatch)
    assert h.handler(prepare_event([kiosk_line(1)]), None)["statusCode"] == 200
    assert h.gateway_orders[0]["amount"] == expected
    assert isinstance(h.gateway_orders[0]["amount"], int)


def test_the_whatsapp_create_path_recovers_too(monkeypatch):
    """`_create` reconciles nothing -- it refuses a mismatched saved cart -- but it reads the saved
    cart through the same `get`, so it recovers through the same `_settle_saved_cart`."""
    h, _fake, wix = gone_cart_env(monkeypatch)
    response = h.handler(create_event([kiosk_line(1)]), None)

    assert response["statusCode"] == 200, body_of(response)
    assert wix.created_carts == [REPLACEMENT_CART_ID]


def test_recovery_is_attempted_once_and_a_persistent_gone_cart_refuses(monkeypatch, caplog):
    """No loop, and the persistent case answers in the existing vocabulary.

    Driven at the seam rather than through the fake, because after one recovery the cart provably
    exists: `_settle_saved_cart` returns immediately for a freshly created cart, so a second
    `CartGone` is not reachable from a 404-ing GET alone. Forcing it is what proves the retry is
    bounded at one and that the refusal is `CART_NOT_PAYABLE` -- never "remove the item", since no
    item has been shown to be missing.
    """
    h, _fake, _wix = gone_cart_env(monkeypatch)
    attempts = []

    def always_gone(*args, **kwargs):
        attempts.append(1)
        raise cart_v2.CartGone("still gone", CART_ID)

    monkeypatch.setattr(h, "_settle_saved_cart", always_gone)
    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([kiosk_line(1)]), None)

    assert len(attempts) == 2, "once, then exactly one retry"
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    assert [event for event in events_of(caplog)
            if event["event"] == "website_checkout_cart_gone_unrecoverable"]


# ══ a genuinely missing item is still a genuinely missing item ══════════════════

def test_an_item_that_is_really_off_the_catalogue_still_says_item_unavailable(monkeypatch,
                                                                             caplog):
    """THE CONTROL CASE. The 404 that MUST keep its old answer: the product itself is gone.

    `GET /stores/v3/products/{id}` 404s, so `resolved_catalog_lines` raises before any cart is
    touched, and the customer is told to remove the line -- which is an action they can take and
    the only one that works.
    """
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          gone_product_ids=[KIOSK_ID])
    h, fake, wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)

    with caplog.at_level("INFO"):
        response = h.handler(prepare_event([kiosk_line(1)]), None)

    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_ITEM_UNAVAILABLE"
    recorded = events_of(caplog)
    unavailable = [event for event in recorded
                   if event["event"] == "website_checkout_catalogue_unavailable"]
    assert len(unavailable) == 1
    assert "/stores/v3/products/" in unavailable[0]["detail"]
    # No cart was created for it, and no recovery was attempted.
    assert wix.created_carts == []
    assert not [event for event in recorded if event["event"] == "checkout_cart_gone_recreated"]


def test_a_line_wix_reports_as_removed_from_catalog_still_says_items_unavailable(monkeypatch):
    """The other shape of "no longer available": the cart exists and Wix flags the LINE."""
    wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                          line_status="REMOVED_FROM_CATALOG")
    h, fake, _wix = make_env(monkeypatch, wix=wix)
    seed_cart_pointer(h, fake)

    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    body = body_of(response)
    assert body["error"] == "ITEMS_UNAVAILABLE"
    assert body["items"][0]["status"] == "REMOVED_FROM_CATALOG"
