"""The WhatsApp catalogue order, parsed into lines and quantities with no money anywhere.

These tests exist to pin the REMOVAL as much as the addition. The path this module replaces read
Meta's `item_price` as a `float`, added 18% GST to goods Wix had already taxed, re-added supply GST
per item and logged a 2% fee - so the assertions that matter most here are the negative ones: no
float literal, no `float()` call, no money key on the row, and an `item_price` of any size making
no difference at all to what gets stored.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(str(ROOT), "amplify", "functions", "shared"))

from lambda_utils.ecommerce import order_channel, whatsapp_basket as wb  # noqa: E402

MODULE_PATH = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce/whatsapp_basket.py")

#: Two real-shaped Wix UUID pairs. `meta_catalog_sync.parse_retailer_id` anchors on the UUID
#: pattern, so these have to be well-formed or every line would be dropped for the wrong reason.
PRODUCT_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
VARIANT_A = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
PRODUCT_B = "cccccccc-3333-4333-8333-cccccccccccc"
VARIANT_B = "dddddddd-4444-4444-8444-dddddddddddd"

#: NOT a business number, and not the owner's QA recipient either - a plain fixture subscriber.
CUSTOMER_PHONE = "919876543210"


def retailer(product_id: str, variant_id: str) -> str:
    return f"wix:{product_id}:{variant_id}"


def order_message(items, *, message_id="wamid.HBgMOTE5ODc2NTQzMjEwFQIAEhgg", catalog_id="cat-1"):
    return {"id": message_id, "type": "order",
            "order": {"catalog_id": catalog_id, "product_items": list(items)}}


def item(retailer_id, quantity=1, **extra):
    row = {"product_retailer_id": retailer_id, "quantity": quantity}
    row.update(extra)
    return row


# ── parsing ───────────────────────────────────────────────────────────────────


def test_two_wix_lines_become_one_handoff_with_integer_quantities_and_no_money():
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 2, item_price=499, currency="INR"),
        item(retailer(PRODUCT_B, VARIANT_B), 1, item_price=1299, currency="INR"),
    ]))
    assert basket is not None
    assert basket.lines == [
        {"productId": PRODUCT_A, "variantId": VARIANT_A, "quantity": 2},
        {"productId": PRODUCT_B, "variantId": VARIANT_B, "quantity": 1},
    ]
    # `is` on the type, not `isinstance`: `cart_v2.catalog_item` refuses anything whose quantity is
    # not exactly `int`, and `True` is an `int` subclass.
    assert all(type(line["quantity"]) is int for line in basket.lines)

    row = wb.build_handoff(basket, CUSTOMER_PHONE, token="tok-1", now=1_700_000_000)
    assert row["channel"] == order_channel.CHANNEL_WHATSAPP == "whatsapp"
    assert row["orderId"] == "WABASKET#tok-1"
    assert row["phone"] == "+" + CUSTOMER_PHONE
    assert row["lineCount"] == 2
    # THE POINT OF THE WHOLE FEATURE. No money field of any kind, under any spelling.
    money_shaped = [key for key in row
                    if "paise" in key.lower() or "amount" in key.lower()
                    or "price" in key.lower() or "total" in key.lower()
                    or "currency" in key.lower() or "fee" in key.lower()
                    or "gst" in key.lower() or "discount" in key.lower()]
    assert money_shaped == []
    assert set(row) == {"orderId", "token", "phone", "lines", "lineCount", "channel",
                        "sourceMessageId", "catalogId", "createdAt", "expiresAt"}


def test_a_non_wix_retailer_id_is_dropped_and_counted():
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 1),
        item("WD-PARTNER-UP", 3),                       # catalog-builder SKU, not ours
        item("wix:not-a-uuid:also-not", 1),             # our prefix, broken ids
        item(f"wix:{PRODUCT_B}:{VARIANT_B}:extra", 1),  # an extra segment
    ]))
    assert basket is not None
    assert [line["productId"] for line in basket.lines] == [PRODUCT_A]
    assert basket.dropped == 3


def test_an_all_foreign_cart_yields_none():
    assert wb.parse_order_message(order_message([
        item("WD-PARTNER-UP", 1), item("htlu35lrs1", 2)])) is None
    # And so does a message with nothing in it at all, rather than an empty basket nobody can use.
    assert wb.parse_order_message(order_message([])) is None
    assert wb.parse_order_message({}) is None


def test_item_price_is_never_read_so_an_absurd_one_changes_nothing():
    """The regression test for the deleted float reprice, stated as an identity.

    If `item_price` reached any stored field, these two rows could not be equal - one cart claims
    ₹499 and the other claims nine hundred million rupees with a fractional paise tail.
    """
    honest = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 2, item_price=499)]))
    absurd = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 2,
             item_price=900_000_000.333, currency="USD", tax=18.0)]))
    assert honest is not None and absurd is not None
    assert wb.build_handoff(honest, CUSTOMER_PHONE, token="t", now=10) == \
        wb.build_handoff(absurd, CUSTOMER_PHONE, token="t", now=10)


def test_a_zero_or_missing_quantity_floors_to_one_and_a_huge_one_clamps():
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 0),
        {"product_retailer_id": retailer(PRODUCT_B, VARIANT_B)},
    ]))
    assert basket is not None
    assert [line["quantity"] for line in basket.lines] == [1, 1]
    assert basket.clamped == 0

    big = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 10_000)]))
    assert big is not None
    assert big.lines[0]["quantity"] == wb.QUANTITY_CEILING == 100
    assert big.clamped == 1


def test_one_variant_sent_twice_is_summed_not_duplicated():
    """`checkout/handler.py::_require_same_basket` sums saved lines sharing a catalogue key, so a
    duplicated line here would make that comparison disagree with this row about one basket."""
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 2),
        item(retailer(PRODUCT_A, VARIANT_A), 3),
    ]))
    assert basket is not None
    assert basket.lines == [{"productId": PRODUCT_A, "variantId": VARIANT_A, "quantity": 5}]


def test_a_retailer_id_is_lowercased_on_the_way_in():
    """`meta_catalog_sync.retailer_id` publishes lowercase, and `cart_v2.identifier` lowercases
    too, so an upper-case id from Meta must resolve to the same Wix line rather than forking it."""
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A.upper(), VARIANT_A.upper()), 1)]))
    assert basket is not None
    assert basket.lines == [{"productId": PRODUCT_A, "variantId": VARIANT_A, "quantity": 1}]


# ── the phone binding ─────────────────────────────────────────────────────────


def test_no_country_code_is_ever_inferred():
    """Prepending +91 is the exact defect `normalize_phone_preserving_country` exists to prevent:
    the basket would be bound to an unrelated subscriber who could then claim it.

    Meta sends a full international number, so adding `+` is notation. Adding `91` would be a
    guess, and a bare national number therefore produces a DIFFERENT E.164 that simply fails the
    claim comparison - the fail-closed direction.
    """
    assert wb.e164("919876543210") == "+919876543210"
    assert wb.e164("+919876543210") == "+919876543210"
    assert wb.e164("9876543210") == "+9876543210"          # NOT "+919876543210"
    assert wb.e164("6591234567") == "+6591234567"          # a real Singapore number, untouched


def test_something_that_is_not_a_phone_number_is_refused():
    basket = wb.parse_order_message(order_message([item(retailer(PRODUCT_A, VARIANT_A), 1)]))
    for junk in ("", None, "123", "+0919876543210", "not-a-phone"):
        assert wb.e164(junk) == ""
        with pytest.raises(ValueError):
            wb.build_handoff(basket, junk, token="t", now=10)


@pytest.mark.parametrize("sender", ["918031830030", "+919330994400", "919903300044"])
def test_a_business_number_is_never_bound_to_a_handoff(sender):
    assert wb.is_business_sender(sender) is True
    basket = wb.parse_order_message(order_message([item(retailer(PRODUCT_A, VARIANT_A), 1)]))
    with pytest.raises(ValueError):
        wb.build_handoff(basket, sender, token="t", now=10)


def test_the_business_number_set_matches_the_registry_of_record():
    """D4's discipline: the list is duplicated rather than imported, and pinned here.

    `lambda_utils.notifications.events` is the registry, and importing it from `whatsapp_basket`
    would pull a package that builds clients at import. A parity test costs the same as sharing
    the list and catches the same drift.
    """
    from lambda_utils.notifications import events
    assert wb.BUSINESS_SENDERS == events.business_numbers()


# ── claimability ──────────────────────────────────────────────────────────────


@pytest.fixture
def handoff():
    basket = wb.parse_order_message(order_message([
        item(retailer(PRODUCT_A, VARIANT_A), 2),
        item(retailer(PRODUCT_B, VARIANT_B), 1),
    ]))
    return wb.build_handoff(basket, CUSTOMER_PHONE, token="tok-claim", now=1_700_000_000)


def test_the_owning_phone_can_claim_an_unexpired_unclaimed_row(handoff):
    assert wb.claimable(handoff, "+" + CUSTOMER_PHONE, 1_700_000_001) is True


def test_a_different_phone_cannot_claim(handoff):
    assert wb.claimable(handoff, "+919812345678", 1_700_000_001) is False
    # Not a suffix match either: the last four digits agree and the number does not.
    assert wb.claimable(handoff, "+15559873210", 1_700_000_001) is False


def test_a_claimed_row_cannot_be_claimed_again(handoff):
    assert wb.claimable(dict(handoff, claimedAt=1_700_000_001),
                        "+" + CUSTOMER_PHONE, 1_700_000_002) is False


def test_an_expired_row_cannot_be_claimed(handoff):
    assert wb.claimable(handoff, "+" + CUSTOMER_PHONE, handoff["expiresAt"]) is False
    assert wb.claimable(handoff, "+" + CUSTOMER_PHONE, handoff["expiresAt"] + 1) is False
    assert handoff["expiresAt"] == 1_700_000_000 + wb.HANDOFF_LIFETIME_SECONDS


def test_a_missing_row_and_a_row_of_another_kind_are_both_unclaimable(handoff):
    assert wb.claimable(None, "+" + CUSTOMER_PHONE, 1) is False
    assert wb.claimable({}, "+" + CUSTOMER_PHONE, 1) is False
    # A `PAYREF#` row lives in the same partition. The prefix check is what stops a token from
    # addressing one.
    assert wb.claimable(dict(handoff, orderId="PAYREF#WD-PAY-1"),
                        "+" + CUSTOMER_PHONE, 1_700_000_001) is False
    assert wb.claimable(dict(handoff, lines=[]), "+" + CUSTOMER_PHONE, 1_700_000_001) is False


def test_token_from_key_refuses_a_key_of_another_kind():
    assert wb.token_from_key("WABASKET#abc") == "abc"
    assert wb.token_from_key("PAYREF#WD-PAY-1") == ""
    assert wb.token_from_key(None) == ""


# ── idempotency index ─────────────────────────────────────────────────────────


def test_the_wamid_index_points_at_the_handoff_and_is_absent_without_a_wamid():
    basket = wb.parse_order_message(order_message(
        [item(retailer(PRODUCT_A, VARIANT_A), 1)], message_id="wamid.ABC"))
    index = wb.build_message_index(basket, "tok-9", 500)
    assert index == {"orderId": "WABASKETMSG#wamid.ABC", "token": "tok-9",
                     "handoffId": "WABASKET#tok-9", "createdAt": 500}

    no_id = wb.parse_order_message(order_message(
        [item(retailer(PRODUCT_A, VARIANT_A), 1)], message_id=""))
    assert wb.build_message_index(no_id, "tok-9", 500) is None


def test_a_token_is_unguessable_and_comes_from_secrets():
    """`random` is banned on this path: with SnapStart on, a published version's snapshot freezes
    the PRNG state and every restored sandbox produces the same sequence."""
    tokens = {wb.new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 32 for token in tokens)
    source = MODULE_PATH.read_text()
    assert "import secrets" in source
    assert "import random" not in source


# ── the claimed-channel pointer ───────────────────────────────────────────────


#: The Wix cart a claim merged its lines into. Lowercase, because `cart_v2.identifier` lowercases
#: whatever `CustomerCart.ensure` returns and both sides of the comparison must be one spelling.
CLAIMED_CART = "11111111-2222-3333-4444-555555555555"


def test_the_claim_pointer_carries_the_channel_and_the_cart_and_no_money(handoff):
    pointer = wb.build_claim_pointer(handoff, "CUS_01J", now=5_000, cart_id=CLAIMED_CART)
    assert pointer == {"orderId": "WABASKETCLAIM#CUS_01J", "customerId": "CUS_01J",
                       "channel": "whatsapp", "handoffId": "WABASKET#tok-claim",
                       "token": "tok-claim", "wixCartId": CLAIMED_CART, "claimedAt": 5_000,
                       "expiresAt": 5_000 + wb.CLAIM_POINTER_LIFETIME_SECONDS}


def test_an_active_pointer_reports_whatsapp_and_an_expired_one_reports_nothing(handoff):
    pointer = wb.build_claim_pointer(handoff, "CUS_01J", now=5_000, cart_id=CLAIMED_CART)
    assert wb.active_claim(pointer, 5_001, cart_id=CLAIMED_CART)["channel"] == "whatsapp"
    assert wb.active_claim(pointer, pointer["expiresAt"], cart_id=CLAIMED_CART) is None
    assert wb.active_claim(pointer, pointer["expiresAt"] + 1, cart_id=CLAIMED_CART) is None


def test_a_pointer_for_a_different_cart_is_not_an_attribution(handoff):
    """THE DEFECT THIS CLOSES, stated as a test rather than as a comment.

    The pointer is keyed on the CUSTOMER and lives thirty days, but the cart it describes is
    CONSUMED at payment. So a customer who claimed a WhatsApp basket, paid for it, and then placed
    an ordinary website order a week later was still inside the lifetime - and `whatsapp` was
    stamped onto that second order's attempt, its `PAYREF#` row, the order row, the `/orders` tag
    and the `Source:` line of a GST tax invoice. A mislabelled order cannot be told apart from a
    real one afterwards.

    A mismatch degrades EXACTLY like a malformed pointer: `None`, which `order_channel.canonical`
    turns into `website`. Under-claiming the WhatsApp channel is the recoverable direction.
    """
    pointer = wb.build_claim_pointer(handoff, "CUS_01J", now=5_000, cart_id=CLAIMED_CART)
    other_cart = "99999999-8888-7777-6666-555555555555"

    assert wb.active_claim(pointer, 5_001, cart_id=other_cart) is None
    # No cart at all - the pointer's own cart is gone and nothing replaced it yet.
    assert wb.active_claim(pointer, 5_001, cart_id=None) is None
    assert wb.active_claim(pointer, 5_001, cart_id="") is None
    # A pointer written before `wixCartId` existed stops answering rather than answering wrongly.
    legacy = {key: value for key, value in pointer.items() if key != "wixCartId"}
    assert wb.active_claim(legacy, 5_001, cart_id=CLAIMED_CART) is None
    # Case is not a difference: `identifier` lowercases, and both sides are reduced the same way.
    assert wb.active_claim(pointer, 5_001,
                           cart_id=CLAIMED_CART.upper())["channel"] == "whatsapp"


def test_the_pointer_lifetime_matches_the_cart_lifetime():
    """The channel belongs to the CART. A pointer outliving the cart it describes would stamp
    `whatsapp` on an unrelated website order weeks later.

    The lifetime is the OUTER bound and not the binding - see the test above. A cart that is never
    paid for is never consumed, and this is what expires it.
    """
    from lambda_utils.ecommerce import customer_cart
    assert wb.CLAIM_POINTER_LIFETIME_SECONDS == customer_cart.CART_LIFETIME


def test_a_malformed_pointer_degrades_to_no_claim_rather_than_raising():
    """Its one caller is on the money path: a 500 in a prepare is worse than an under-claimed tag."""
    for junk in (None, {}, "pointer", {"expiresAt": "soon"}, {"expiresAt": None}):
        assert wb.active_claim(junk, 1, cart_id=CLAIMED_CART) is None
    # A junk channel on a live pointer for the CURRENT cart degrades to `website`, never to an
    # exception.
    assert wb.active_claim({"expiresAt": 10, "channel": {"not": "a word"},
                            "wixCartId": CLAIMED_CART}, 1,
                           cart_id=CLAIMED_CART)["channel"] == "website"
    # And a junk CART id is a mismatch rather than a raise, for the same reason.
    assert wb.active_claim({"expiresAt": 10, "wixCartId": ["not", "an", "id"]}, 1,
                           cart_id=CLAIMED_CART) is None


# ── stored row -> Wix cart items ──────────────────────────────────────────────


def test_catalog_items_remakes_a_decimal_quantity_as_a_real_int():
    """DynamoDB returns numbers as `Decimal`, and `cart_v2.catalog_item` refuses anything whose
    quantity is not exactly `int` - so a stored row handed straight to Wix would be rejected."""
    from decimal import Decimal
    items = wb.catalog_items({"lines": [
        {"productId": PRODUCT_A, "variantId": VARIANT_A, "quantity": Decimal("3")},
        {"productId": "", "variantId": VARIANT_B, "quantity": 1},
        "not a line",
    ]})
    assert items == [{"productId": PRODUCT_A, "variantId": VARIANT_A, "quantity": 3}]
    assert type(items[0]["quantity"]) is int


# ── the no-float property, proved over the AST ────────────────────────────────


def test_the_module_contains_no_float_literal_and_no_float_call():
    """An `ast` walk, not a grep: the docstring in this module legitimately quotes
    `float(pi.get('item_price'))` while explaining why that line is gone."""
    tree = ast.parse(MODULE_PATH.read_text())
    floats = [node for node in ast.walk(tree)
              if isinstance(node, ast.Constant) and isinstance(node.value, float)]
    assert floats == [], "a float literal reached the WhatsApp basket module"
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "float" not in called
    assert "round" not in called          # `round` on a float is the other half of the old defect
    # And no division, which is the other way a float appears without the word.
    divisions = [node for node in ast.walk(tree)
                 if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)]
    assert divisions == []


def test_the_module_builds_no_aws_client_and_reads_no_environment():
    """The pure-module rule: every dependency injected, nothing constructed at module scope.

    Over the AST rather than the text, for the same reason the float walk is: the docstring says
    "no boto3, no `os.environ` read" in prose, and a substring check would fail on its own
    explanation.
    """
    tree = ast.parse(MODULE_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert "boto3" not in imported
    assert "os" not in imported
    assert "time" not in imported, "`now` is an argument, so this module owns no clock"
