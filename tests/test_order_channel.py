"""`order_channel` is the channel vocabulary, and this file is what keeps it to two words.

Three properties, and each one is here because breaking it would be silent:

1. `canonical()` is TOTAL. Its callers - `finalization.accept_paid` and
   `customer-orders._project` - both document a degrade-never-raise contract, and `accept_paid`
   runs AFTER the money has been taken, so an exception there is a captured payment with no order
   record. A parametrisation over junk, `None`, a dict and an object whose `__str__` raises is the
   only way to assert "total" rather than "total for the inputs I thought of".

2. `channel` is written onto the order row and `checkoutMode` is NOT touched. The two are
   attribution and mechanics, and `ACCEPTED_CHECKOUT_MODES` gates finalisation - so a channel
   spelled into `checkoutMode` would be a new settlement path. The membership of that frozenset
   is asserted by EQUALITY for the same reason the IAM documents are: a test that checks it
   *contains* two modes passes just as happily when a third is added.

3. An attempt with no channel at all writes `website`. That is every attempt row in existence
   today, so this is the backfill assertion, not a convenience.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(ROOT / "tests"))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import finalization, order_channel  # noqa: E402

CUSTOMER = "CUS_channel_001"
CART = "11111111-2222-3333-4444-555555555555"
ATTEMPT_ID = "pa_channel_1"


class _StrRaises:
    """An object whose `__str__` raises. Not a realistic DynamoDB value - the point is that
    `canonical` is defined over EVERY object, so there is no input that can reach `accept_paid`
    and turn a taken payment into an exception."""

    def __str__(self):
        raise RuntimeError("no string for you")


# ── the two literals, and nothing else ───────────────────────────────────────

def test_the_vocabulary_is_exactly_two_words():
    """Equality, so a third channel is a deliberate test edit rather than a quiet addition."""
    assert order_channel.CHANNEL_WEBSITE == "website"
    assert order_channel.CHANNEL_WHATSAPP == "whatsapp"
    assert order_channel.CHANNELS == frozenset({"website", "whatsapp"})


@pytest.mark.parametrize("value", [
    "whatsapp", "WhatsApp", "WHATSAPP", "  whatsapp  ", "whatsapp ", "\twhatsapp\n",
])
def test_whatsapp_is_matched_case_insensitively_and_whitespace_tolerantly(value):
    """`WhatsApp` is the spelling Meta's own documentation uses, and a stored value that picked up
    a trailing space is still the customer's channel."""
    assert order_channel.canonical(value) == order_channel.CHANNEL_WHATSAPP


@pytest.mark.parametrize("value", [
    None, "", "   ", "website", "WEBSITE", "Website", "whats app", "whatsapp_business",
    "wa", "WhatsAppBusiness", "junk", 0, 1, 3.5, True, False, [], {}, ["whatsapp"],
    {"channel": "whatsapp"}, object(), _StrRaises(),
])
def test_everything_else_is_the_website(value):
    """ASYMMETRIC ON PURPOSE. A typo under-claims the WhatsApp channel rather than mislabelling a
    website order, and a mislabelled row cannot be told from a real one after the fact."""
    assert order_channel.canonical(value) == order_channel.CHANNEL_WEBSITE


def test_canonical_never_raises_and_always_answers_one_of_the_two(value_set=None):
    """The total-by-construction property, stated once over every input this file knows about."""
    for value in (None, "", "whatsapp", "WEBSITE", "junk", 7, 7.5, True, [], {},
                  object(), _StrRaises(), b"whatsapp"):
        assert order_channel.canonical(value) in order_channel.CHANNELS


def test_a_bytes_value_is_not_quietly_whatsapp():
    """`str(b"whatsapp")` is `"b'whatsapp'"`, which is not the word - so bytes read as website
    rather than being decoded. Recorded because the opposite behaviour would be defensible and is
    NOT what this does: nothing writes bytes here, and a decode would be a guess about encoding."""
    assert order_channel.canonical(b"whatsapp") == order_channel.CHANNEL_WEBSITE


# ── the order row `accept_paid` writes ───────────────────────────────────────

def _attempt(**overrides):
    attempt = {
        "paymentAttemptId": ATTEMPT_ID,
        "customerId": CUSTOMER,
        "referenceId": "WD-REF-CHANNEL-1",
        "amountPaise": 100000,
        "currency": "INR",
        "status": "PAYMENT_PENDING",
        "checkoutMode": "WEBSITE_RAZORPAY_STANDARD",
        "purchasedSnapshot": {"cart": {"id": CART}},
        "snapshotHash": "hash-channel",
    }
    attempt.update(overrides)
    return attempt


def _accept(**attempt_overrides):
    """Drive `accept_paid` and return `(order_row, attempt_row)`.

    `verified_captured_paise` equals the payable, which is the 100%-Razorpay shape: this file is
    about attribution, and a split tender would add a second thing that could fail.
    """
    attempt = _attempt(**attempt_overrides)
    attempts = FakeTable(key_attr="paymentAttemptId")
    attempts.put_item(Item=dict(attempt))
    orders = FakeTable(key_attr="orderId")
    keys = FakeTable(key_attr="orderId")
    finalization.accept_paid(
        attempts=attempts, orders=orders, keys=keys, attempt=attempt,
        outcome={"hasOrder": True, "orderId": "ORD-channel",
                 "orderNumber": "WD-ORD-CHANNEL1",
                 "providerPaymentId": "pay_channel_1"},
        verified_captured_paise=attempt["amountPaise"])
    return orders.rows["ORD-channel"], attempts.rows[ATTEMPT_ID]


def test_a_whatsapp_attempt_writes_a_whatsapp_order_row():
    order, _ = _accept(channel="whatsapp")
    assert order["channel"] == "whatsapp"


def test_an_attempt_with_no_channel_writes_a_website_order_row():
    """Every attempt row written before this landed, which is why the default had to be measured
    rather than chosen: the WhatsApp hand-off that could produce one does not exist yet."""
    order, _ = _accept()
    assert "channel" not in _attempt()
    assert order["channel"] == "website"


@pytest.mark.parametrize("stored,expected", [
    ("WhatsApp", "whatsapp"), ("whatsapp ", "whatsapp"),
    ("", "website"), (None, "website"), ("telegram", "website"), (42, "website"),
])
def test_the_order_row_carries_the_canonical_word_and_not_the_stored_one(stored, expected):
    """`accept_paid` writes through `canonical`, so a sloppy attempt value cannot become a sloppy
    order row - there is one spelling on the wire whatever was stored."""
    order, _ = _accept(channel=stored)
    assert order["channel"] == expected


# ── what must NOT have moved ─────────────────────────────────────────────────

@pytest.mark.parametrize("channel", ["whatsapp", "website", None])
def test_checkout_mode_is_untouched_on_both_channels(channel):
    """ATTRIBUTION IS NOT MECHANICS. `checkoutMode` gates finalisation through
    `ACCEPTED_CHECKOUT_MODES`, so a channel written into it would open a second settlement path
    instead of labelling the one that exists."""
    overrides = {} if channel is None else {"channel": channel}
    order, _ = _accept(**overrides)
    assert order["checkoutMode"] == "WEBSITE_RAZORPAY_STANDARD"
    assert order["paymentStatus"] == "PAYMENT_PAID"


def test_accepted_checkout_modes_still_has_exactly_two_members():
    """Equality, not containment. A WhatsApp-origin order settles through the SAME mode as a
    website one, so this frozenset must not have grown."""
    assert finalization.ACCEPTED_CHECKOUT_MODES == frozenset(
        {"WIX_HEADLESS", "WEBSITE_RAZORPAY_STANDARD"})
    assert len(finalization.ACCEPTED_CHECKOUT_MODES) == 2
    assert "whatsapp" not in finalization.ACCEPTED_CHECKOUT_MODES
    assert "WHATSAPP_RAZORPAY_STANDARD" not in finalization.ACCEPTED_CHECKOUT_MODES


def test_the_module_does_its_own_comparing_so_no_caller_has_to():
    """Nothing outside `order_channel` may compare a channel string by hand. Asserted on the
    SOURCE of the three callers, because a comparison that agrees with `canonical` today is still
    a second place the vocabulary lives tomorrow."""
    callers = [
        ROOT / "amplify/functions/shared/lambda_utils/ecommerce/finalization.py",
        ROOT / "amplify/functions/ecommerce/customer-orders/handler.py",
        ROOT / "amplify/functions/ecommerce/checkout/handler.py",
    ]
    for path in callers:
        source = path.read_text(encoding="utf-8")
        for spelling in ('== "whatsapp"', "== 'whatsapp'",
                         '!= "whatsapp"', "!= 'whatsapp'"):
            assert spelling not in source, f"{path.name} compares a channel word raw"
        assert "order_channel" in source, f"{path.name} does not consult order_channel"
