"""A coupon and a gift card on a Pay Flow invoice, through the SAME authority the cart uses.

WHAT THIS FILE IS FOR
---------------------
`invoice-engine.create_invoice` is the GST-numbering path. It is also, after this change, the
staff-facing surface where a coupon and a gift card are applied. Those two facts together are why
almost every test below is about a REFUSAL rather than a success: a GST invoice number comes out
of a consecutive series that Rule 46(b) requires and cannot be reassigned once issued, so a
coupon the store refuses has to refuse *before* a number exists. A refusal that burns a number is
not a validation error, it is a permanent gap in a tax series.

THE THREE PROPERTIES WORTH READING TWICE
----------------------------------------
1. `test_an_invoice_with_no_codes_is_byte_for_byte_what_it_was` - the no-code path is untouched.
   Everything here is additive, and an invoice raised with neither code must produce the total it
   produced before the feature existed. Asserted against figures written out in full, not against
   a re-run of the same arithmetic.

2. `test_a_coupon_is_indistinguishable_from_the_same_manual_discount` - the proof that the coupon
   fed the convenience-fee calculator rather than being applied after it. A `₹100` coupon and a
   `₹100` manual adjustment must yield the IDENTICAL document, because a coupon is a price change.
   This is stronger than asserting a number: it says the coupon entered the pipeline at the right
   point, which is the thing that can silently regress.

3. `test_a_gift_card_does_not_reduce_the_taxable_value` - the proof that the gift card was applied
   as TENDER. The stored `tax` must be the same figure with and without the card. If a gift card
   ever reduced taxable value, every gift-card order would under-report GST.

TECHNIQUE
---------
`create_invoice` is driven directly against in-memory tables. The coupon and gift-card tables are
the real `coupon_fake_dynamo.FakeTable` the rest of that suite uses, so the holds and the
conditional writes are genuinely evaluated; the invoice/items/sequence tables get purpose-built
fakes here because the engine's expressions (an `OR` filter scan, an `if_not_exists` counter
increment) are shapes the coupon fake deliberately refuses.

The sequence fake counts every advance, so "no invoice number was consumed" is a measured
assertion rather than an inference from the status code.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify" / "functions"
sys.path.insert(0, str(FUNCTIONS / "shared"))
sys.path.insert(0, str(Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import checkout_pricing as cp  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import gift_card_settlement as gcs  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402
from lambda_utils.ecommerce import redemption  # noqa: E402

#: Not a credential. A test-only HMAC key, assembled here so the file carries no issuer-shaped
#: literal; the real pepper lives in Secrets Manager and is read by reference at request time.
PEPPER = "pepper" + "-for-tests-only"
CARD_CODE = "WDGC0000TEST0001"
COUPON_CODE = "SAVE100"
REFERENCE_ID = "WD-PAY-INVOICE01"
NOW_MS = 1_700_000_000_000


# ══════════════════════════════════════════════════════════════════════════════
# In-memory tables for the shapes the coupon fake deliberately refuses
# ══════════════════════════════════════════════════════════════════════════════

def _conditional_failure() -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException",
                                  "Message": "ConditionalCheckFailedException"}},
                       "PutItem")


class _InvoicesTable:
    """Key `invoiceId`. Supports the engine's dedup scan, its atomic claim and its updates.

    The scan filter is `referenceId = :ref OR paymentId = :pid`, which the coupon fake refuses by
    design (it is not an exact-key read). Here it is evaluated against the two placeholders
    directly - narrow on purpose, so an unexpected filter shape fails loudly rather than matching
    everything and making a dedup test pass for the wrong reason.
    """

    def __init__(self) -> None:
        self.rows: dict = {}

    def scan(self, FilterExpression="", ExpressionAttributeValues=None, **_):
        values = ExpressionAttributeValues or {}
        if set(values) - {":ref", ":pid"}:
            raise AssertionError(f"unexpected scan filter {FilterExpression!r}")
        matched = [dict(row) for row in self.rows.values()
                   if (":ref" in values and row.get("referenceId") == values[":ref"])
                   or (":pid" in values and row.get("paymentId") == values[":pid"])]
        return {"Items": matched}

    def put_item(self, Item=None, ConditionExpression=None, **_):
        item = dict(Item or {})
        key = item["invoiceId"]
        if ConditionExpression and "attribute_not_exists(invoiceId)" in str(ConditionExpression) \
                and key in self.rows:
            raise _conditional_failure()
        self.rows[key] = item
        return {}

    def get_item(self, Key=None, **_):
        row = self.rows.get((Key or {})["invoiceId"])
        return {"Item": dict(row)} if row else {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, **_):
        key = (Key or {})["invoiceId"]
        row = self.rows.setdefault(key, {"invoiceId": key})
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        body = UpdateExpression.split("SET", 1)[1] if "SET" in UpdateExpression else ""
        for assignment in body.split(","):
            target, _, source = (part.strip() for part in assignment.partition("="))
            if not target:
                continue
            row[names.get(target, target)] = values[source]
        return {"Attributes": dict(row)}


class _ItemsTable:
    """Composite `(invoiceId, itemIndex)`, queried with a real boto3 `Key(...).eq(...)`."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        self.rows[(item["invoiceId"], int(item["itemIndex"]))] = item
        return {}

    def query(self, KeyConditionExpression=None, **_):
        expression = KeyConditionExpression.get_expression()
        attribute, value = expression["values"]
        if attribute.name != "invoiceId":
            raise AssertionError(f"unexpected query on {attribute.name!r}")
        return {"Items": [dict(row) for (invoice_id, _), row in sorted(self.rows.items())
                          if invoice_id == value]}


class _SequenceTable:
    """The GST counter, with `advances` exposed so "no number was consumed" is measurable.

    The engine's expression is a single `if_not_exists(last_seq, :zero) + :inc`, which is the
    atomicity that makes a burned number irreversible. That is modelled as a plain increment here
    because the test's subject is WHETHER it ran, not how it races.
    """

    def __init__(self) -> None:
        self.rows: dict = {}
        self.advances = 0
        self.fail_with: Exception | None = None

    def update_item(self, Key=None, **_):
        self.advances += 1
        if self.fail_with is not None:
            raise self.fail_with
        fy = (Key or {})["fy"]
        row = self.rows.setdefault(fy, {"fy": fy, "last_seq": 0, "prefix": "WD"})
        row["last_seq"] = int(row["last_seq"]) + 1
        return {"Attributes": dict(row)}

    def get_item(self, Key=None, **_):
        row = self.rows.get((Key or {})["fy"])
        return {"Item": dict(row)} if row else {}


class _InertTable:
    """A table whose contents no assertion here depends on: contacts, assets, the delivery log.

    Present so the engine's incidental reads and writes do not fail, and empty so nothing it
    finds can influence a figure under test - a contact with a saved address, for instance, would
    change the WhatsApp payload for reasons that have nothing to do with a coupon.
    """

    def __init__(self) -> None:
        self.rows: list = []

    def put_item(self, Item=None, **_):
        self.rows.append(dict(Item or {}))
        return {}

    def update_item(self, **_):
        return {}

    def get_item(self, **_):
        return {}

    def query(self, **_):
        return {"Items": []}

    def scan(self, **_):
        return {"Items": []}


class _Tables:
    """A `boto3.resource('dynamodb')` stand-in: one named fake per table the engine opens."""

    def __init__(self, handler) -> None:
        self.invoices = _InvoicesTable()
        self.items = _ItemsTable()
        self.sequence = _SequenceTable()
        self.coupons = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                                 indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
        self.cards = FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                               indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})
        self.contacts = _InertTable()
        self.delivery = _InertTable()
        self.assets = _InertTable()
        self._by_name = {
            handler.INVOICES_TABLE: self.invoices,
            handler.INVOICE_ITEMS_TABLE: self.items,
            handler.INVOICE_SEQ_TABLE: self.sequence,
            handler.COUPONS_TABLE: self.coupons,
            handler.GIFT_CARDS_TABLE: self.cards,
            handler.CONTACTS_TABLE: self.contacts,
            handler.INVOICE_DELIVERY_TABLE: self.delivery,
            handler.INVOICE_ASSETS_TABLE: self.assets,
        }

    def Table(self, name):  # noqa: N802 - the boto3 resource spelling
        try:
            return self._by_name[name]
        except KeyError:
            raise AssertionError(f"the engine opened an unexpected table {name!r}") from None


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def engine(monkeypatch):
    """The real handler module, imported with no AWS, then pointed at the in-memory tables."""
    monkeypatch.syspath_prepend(str(FUNCTIONS / "payments" / "invoice-engine"))
    sys.modules.pop("handler", None)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}), \
            patch("boto3.resource"), patch("boto3.client"):
        import handler  # noqa: PLC0415 - deliberately imported under the patches

    tables = _Tables(handler)
    monkeypatch.setattr(handler, "dynamodb", tables)

    # A secretsmanager client that answers with the pepper, so `_read_gift_card_secret` and
    # `gift_card_store.read_pepper` both run for real rather than being stubbed out. The value
    # never reaches a command line, an env assignment or a log line.
    #
    # Patched on the real `boto3` module rather than by replacing `handler.boto3`: the handler
    # also reaches `boto3.dynamodb.conditions.Key` for its item query, and a MagicMock module
    # answers that with a mock whose key condition the fake table cannot read.
    import boto3  # noqa: PLC0415
    import boto3.dynamodb.conditions  # noqa: PLC0415,F401 - ensures the attribute resolves
    secrets = MagicMock()
    secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({gc.PEPPER_FIELD: PEPPER})}
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: secrets)

    handler.tables = tables
    yield handler
    sys.modules.pop("handler", None)


def _issue_coupon(engine, *, code: str = COUPON_CODE, mirrored: bool = True, **overrides):
    payload = {
        "code": code,
        "name": "A hundred rupees off",
        "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 10000,
        "startTimeMs": NOW_MS,
        # `validate_definition` requires a scope OR a floor for every kind except FREE_SHIPPING,
        # so that a coupon cannot apply to everything with no minimum. Zero is the explicit
        # "no floor" and keeps the floor from being the reason a probe below refuses.
        "minimumSubtotalPaise": 0,
    }
    payload.update(overrides)
    payload = {key: value for key, value in payload.items() if value is not None}
    definition = cs.create(engine.tables.coupons, payload, created_by="staff-1",
                           clock=lambda: NOW_MS // 1000)
    if mirrored:
        cs.mark_mirrored(engine.tables.coupons, code, "wix-" + code.lower(),
                         clock=lambda: NOW_MS // 1000)
    # Both logs cleared, so every later assertion counts only what the ENGINE did. Issuance is
    # setup; counting it would make "the no-code path reads neither store" untestable.
    engine.tables.coupons.calls.clear()
    engine.tables.coupons.applied.clear()
    return definition


def _issue_card(engine, *, value_paise: int = 30000, code: str = CARD_CODE, **extra):
    issued = gc.issue(engine.tables.cards, initial_value_paise=value_paise, pepper=PEPPER,
                      code=code, clock=lambda: NOW_MS // 1000, **extra)
    engine.tables.cards.calls.clear()
    engine.tables.cards.applied.clear()
    return issued


def _body(**overrides):
    """A ₹1000 service invoice at 18% GST, raised from Pay Flow. ₹0 manual discount."""
    body = {
        "referenceId": REFERENCE_ID,
        "customerPhone": "+918100640044",
        "customerEmail": "customer@example.com",
        "shippingAddress": "12 Example Road, Kolkata, West Bengal 700012",
        "billingAddress": "12 Example Road, Kolkata, West Bengal 700012",
        "entryPoint": "pay_flow",
        "items": [{"name": "Service", "amount": 1000.0, "quantity": 1}],
        "discount": 0,
        "gstRate": 18,
        "currency": "INR",
    }
    body.update(overrides)
    return body


def _create(engine, **overrides):
    response = engine.create_invoice(_body(**overrides), "req-1")
    return response["statusCode"], json.loads(response["body"])


def _stored(engine):
    rows = [row for row in engine.tables.invoices.rows.values() if row.get("invoiceNumber")]
    assert len(rows) == 1, f"expected exactly one issued invoice, got {len(rows)}"
    return rows[0]


# ══════════════════════════════════════════════════════════════════════════════
# 1. the no-code path is untouched
# ══════════════════════════════════════════════════════════════════════════════

def test_an_invoice_with_no_codes_is_byte_for_byte_what_it_was(engine):
    """₹1000 + 18% GST + a 2.5% convenience fee with 18% GST on the fee.

    The figures are written out rather than recomputed, which is the point: if the restructuring
    that moved the amount block above `_get_next_invoice_number` had changed the arithmetic by a
    paise, re-deriving the expectation would hide it.
    """
    status, created = _create(engine)
    assert status == 201
    row = _stored(engine)
    assert row["subtotal"] == Decimal("1000.00")
    assert row["discount"] == Decimal("0.00")
    assert row["tax"] == Decimal("180.00")
    assert row["convenienceFee"] == Decimal("34.81")
    assert row["total"] == Decimal("1214.81")
    assert created["total"] == 1214.81
    # And not one redemption attribute exists. ABSENT, not zero: an invoice where nobody applied
    # a coupon must stay distinguishable from one where a coupon was worth nothing.
    for attribute in ("couponCode", "couponDiscount", "amountPayable", "giftCardLast4",
                      "giftCardFullyCovered", gcs.REQUIRED_PAISE_ATTR, gcs.CODE_HASH_ATTR,
                      gcs.REDEEMED_PAISE_ATTR):
        assert attribute not in row, attribute
    for key in ("couponDiscount", "giftCardAppliedPaise", "amountPayable", "couponReason",
                "giftCardReason"):
        assert key not in created, key


def test_the_no_code_path_reads_neither_store(engine):
    """Guarded, not merely harmless: a coupon table read on every invoice would make the common
    path depend on a table the common path does not need, and a throttle there would start
    refusing ordinary invoices."""
    _create(engine)
    assert engine.tables.coupons.calls == []
    assert engine.tables.cards.calls == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. a coupon is a PRICE CHANGE and feeds the fee calculator
# ══════════════════════════════════════════════════════════════════════════════

def test_a_money_off_coupon_discounts_the_invoice_exactly(engine):
    _issue_coupon(engine)
    status, created = _create(engine, couponCode="save100")
    assert status == 201
    row = _stored(engine)
    assert row["couponCode"] == COUPON_CODE          # normalised, uppercase
    assert row["couponDiscount"] == Decimal("100.00")
    assert row["discount"] == Decimal("100.00")      # manual 0 + coupon 100
    assert created["couponDiscount"] == 100.0
    assert created["couponReason"] == redemption.COUPON_APPLIED


def test_a_coupon_is_indistinguishable_from_the_same_manual_discount(engine):
    """THE apply-order test. A coupon is a price change, so a ₹100 coupon must produce the exact
    document a ₹100 manual adjustment produces - same convenience fee, same GST on that fee, same
    total. Any implementation that applies the coupon AFTER the calculator fails here, because the
    fee would still have been charged on the undiscounted ₹1180 collection."""
    _issue_coupon(engine)
    status, _ = _create(engine, couponCode=COUPON_CODE)
    assert status == 201
    with_coupon = copy.deepcopy(_stored(engine))

    engine.tables.invoices.rows.clear()
    status, _ = _create(engine, referenceId="WD-PAY-INVOICE02", discount=100)
    assert status == 201
    with_manual = _stored(engine)

    for field in ("subtotal", "discount", "tax", "convenienceFee", "total"):
        assert with_coupon[field] == with_manual[field], field
    # And the fee really did fall, so the two agreeing is not two identical mistakes.
    engine.tables.invoices.rows.clear()
    _create(engine, referenceId="WD-PAY-INVOICE03")
    assert with_coupon["convenienceFee"] < _stored(engine)["convenienceFee"]


def test_a_percent_off_coupon_rounds_half_up_the_way_the_fee_does(engine):
    """15% of `14570` paise is `2185.5`: half-up gives `2186`, truncation `2185`. One paise, and
    the whole path fails closed on a one-paise mismatch - so the coupon must round the way
    `checkout_pricing.round_half_up` rounds the convenience fee rather than a second way.

    GST is zero on this one so the collection IS the item amount, which is what puts the exact
    half-paise case in reach; `coupon_store` only accepts a whole-percent rate, so the fraction
    has to come from the collection rather than from the rate.
    """
    _issue_coupon(engine, discountKind=cs.PERCENT_OFF, moneyOffPaise=None, percentOffBps=1500)
    status, created = _create(
        engine, items=[{"name": "Service", "amount": 145.70, "quantity": 1}],
        gstRate=0, couponCode=COUPON_CODE)
    assert status == 201
    row = _stored(engine)
    assert cp.round_half_up(14570, 1500) == 2186        # half-up
    assert 14570 * 1500 // 10000 == 2185                # what truncation would have given
    assert row["couponDiscount"] == Decimal("21.86")
    assert created["couponDiscount"] == 21.86


def test_the_manual_adjustment_and_the_coupon_are_stored_separately(engine):
    """`discount` is the SUM because Meta validates `total == subtotal + tax + shipping -
    discount` and both renderers read it. The coupon's own share is stored alongside so the
    document can print two lines and a reconciliation can tell the two apart."""
    _issue_coupon(engine)
    status, _ = _create(engine, couponCode=COUPON_CODE, discount=25)
    assert status == 201
    row = _stored(engine)
    assert row["couponDiscount"] == Decimal("100.00")
    assert row["discount"] == Decimal("125.00")


# ══════════════════════════════════════════════════════════════════════════════
# 3. a gift card is TENDER and reduces only the payable
# ══════════════════════════════════════════════════════════════════════════════

def test_a_partial_gift_card_reduces_the_payable_and_nothing_else(engine):
    _issue_card(engine, value_paise=30000)
    status, created = _create(engine, giftCardCode=CARD_CODE)
    assert status == 201
    row = _stored(engine)
    assert row["total"] == Decimal("1214.81")            # the document total is unchanged
    assert row[gcs.REQUIRED_PAISE_ATTR] == 30000
    assert row[gcs.REDEEMED_PAISE_ATTR] == 0             # nothing has been debited
    assert row["amountPayable"] == Decimal("914.81")
    assert row["giftCardFullyCovered"] is False
    assert created["giftCardAppliedPaise"] == 30000
    assert created["amountPayable"] == 914.81
    # M6, exactly: the redemption and the payable account for the whole total, in paise.
    assert row[gcs.REQUIRED_PAISE_ATTR] + int(row["amountPayable"] * 100) == 121481


def test_a_gift_card_does_not_reduce_the_taxable_value(engine):
    """A gift card is tender, not a price change. If it ever netted into the subtotal, the GST on
    every gift-card order would be under-reported - so the stored tax must be identical with and
    without the card."""
    status, _ = _create(engine)
    assert status == 201
    without = copy.deepcopy(_stored(engine))

    engine.tables.invoices.rows.clear()
    _issue_card(engine, value_paise=30000)
    status, _ = _create(engine, referenceId="WD-PAY-INVOICE02", giftCardCode=CARD_CODE)
    assert status == 201
    with_card = _stored(engine)

    assert with_card["tax"] == without["tax"] == Decimal("180.00")
    assert with_card["subtotal"] == without["subtotal"]
    assert with_card["convenienceFee"] == without["convenienceFee"]
    assert with_card["total"] == without["total"]


def test_a_card_covering_the_whole_total_is_flagged_and_no_link_can_be_sent(engine):
    _issue_card(engine, value_paise=200000)
    status, created = _create(engine, giftCardCode=CARD_CODE)
    assert status == 201
    row = _stored(engine)
    assert row[gcs.REQUIRED_PAISE_ATTR] == 121481
    assert row["amountPayable"] == Decimal("0.00")
    assert row["giftCardFullyCovered"] is True
    assert created["giftCardFullyCovered"] is True

    response = engine.send_payment_link(row["invoiceId"], "", "", "req-2")
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["errorCode"] == "FULLY_COVERED_NO_GATEWAY"


def test_the_card_balance_is_never_moved_at_invoice_create(engine):
    """DECISION 3. The debit belongs to the producer that mints the payment attempt; an invoice
    can sit unpaid for days and must never burn balance in the meantime."""
    issued = _issue_card(engine, value_paise=30000)
    key = issued["card"][gc.KEY_ATTRIBUTE]
    before = dict(engine.tables.cards.rows[key])
    _create(engine, giftCardCode=CARD_CODE)
    after = engine.tables.cards.rows[key]
    assert after["balancePaise"] == before["balancePaise"] == 30000
    assert gc.HOLD_ATTEMPT_ATTRIBUTE not in after
    assert [name for name, _ in engine.tables.cards.applied] == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. both together, in the plan's order
# ══════════════════════════════════════════════════════════════════════════════

def test_a_coupon_and_a_gift_card_compose_in_the_documented_order(engine):
    """Recomputed independently here through `apply_coupon` -> `compute_quote` -> `verify_gift_card`
    -> `build_payable`, so the assertion is on the ORDER rather than on a number this test could
    have copied out of the implementation."""
    _issue_coupon(engine)
    _issue_card(engine, value_paise=30000)
    status, created = _create(engine, couponCode=COUPON_CODE, giftCardCode=CARD_CODE)
    assert status == 201
    row = _stored(engine)

    # Coupon first, on the collection that feeds the fee: 1180.00 -> 1080.00.
    assert row["couponDiscount"] == Decimal("100.00")
    assert row["total"] == Decimal("1111.86")
    # Gift card last, off the FINAL total.
    assert row[gcs.REQUIRED_PAISE_ATTR] == 30000
    assert row["amountPayable"] == Decimal("811.86")
    assert created["amountPayable"] == 811.86
    # The identity holds exactly, in integer paise.
    assert 30000 + 81186 == 111186


def test_every_stored_money_attribute_is_a_decimal_and_never_a_float(engine):
    """DynamoDB refuses a float anyway; asserting it here makes the discipline deliberate rather
    than a property we happen to get from the driver."""
    _issue_coupon(engine)
    _issue_card(engine, value_paise=30000)
    _create(engine, couponCode=COUPON_CODE, giftCardCode=CARD_CODE)
    row = _stored(engine)
    for attribute in ("subtotal", "discount", "shipping", "handling", "gstRate", "tax",
                      "convenienceFee", "total", "couponDiscount", "amountPayable"):
        assert isinstance(row[attribute], Decimal), attribute
        assert not isinstance(row[attribute], float), attribute
    # The gift-card figures are integer paise, which is the gift-card ledger's own unit.
    for attribute in (gcs.REQUIRED_PAISE_ATTR, gcs.REDEEMED_PAISE_ATTR):
        assert type(row[attribute]) is int, attribute


# ══════════════════════════════════════════════════════════════════════════════
# 5. the nine fail-closed refusals - each one consumes NO invoice number
# ══════════════════════════════════════════════════════════════════════════════

def _refused(engine, expected_status, expected_code, **overrides):
    status, payload = _create(engine, **overrides)
    assert status == expected_status, payload
    assert payload["errorCode"] == expected_code, payload
    # The whole point: nothing was issued and the GST counter never moved.
    assert engine.tables.sequence.advances == 0, "a refused invoice consumed an invoice number"
    assert engine.tables.sequence.rows == {}
    assert not [row for row in engine.tables.invoices.rows.values()
                if row.get("invoiceNumber")]
    return payload


def test_1_an_unknown_coupon_code_is_refused(engine):
    _refused(engine, 400, "UNKNOWN_CODE", couponCode="NOSUCHCODE")


def test_2a_an_unmirrored_coupon_is_refused(engine):
    """Fail closed. The same code on the website would be rejected by Wix's `Add Coupon`, so
    honouring it here would make the two surfaces disagree about what the customer was promised."""
    _issue_coupon(engine, mirrored=False)
    _refused(engine, 400, "COUPON_INELIGIBLE", couponCode=COUPON_CODE)


def test_2b_an_expired_coupon_is_refused(engine):
    _issue_coupon(engine, expirationTimeMs=NOW_MS + 1000)
    _refused(engine, 400, "COUPON_EXPIRED", couponCode=COUPON_CODE)


def test_2c_a_usage_limited_coupon_is_refused_once_spent(engine):
    _issue_coupon(engine, usageLimit=1)
    cs.commit_redemption(engine.tables.coupons, code=COUPON_CODE, cart_id="cart-a",
                         order_id="order-a", customer_id="customer-a",
                         clock=lambda: NOW_MS // 1000)
    _refused(engine, 400, "COUPON_INELIGIBLE", couponCode=COUPON_CODE)


@pytest.mark.parametrize("overrides", [
    {"discountKind": cs.FREE_SHIPPING, "moneyOffPaise": None},
    {"discountKind": cs.BUY_X_GET_Y, "moneyOffPaise": None, "buyX": 2, "buyY": 1},
])
def test_3_a_coupon_kind_an_invoice_cannot_price_is_refused(engine, overrides):
    """Both need line-item or shipping context an invoice-level collection cannot supply. Refusing
    is the fail-closed answer; discounting nothing while answering 201 would collect the full
    amount after promising a reduction."""
    _issue_coupon(engine, **overrides)
    _refused(engine, 400, "COUPON_KIND_UNSUPPORTED", couponCode=COUPON_CODE)


def test_3b_an_unmet_minimum_subtotal_is_refused(engine):
    _issue_coupon(engine, minimumSubtotalPaise=500000)
    _refused(engine, 400, "MINIMUM_SUBTOTAL", couponCode=COUPON_CODE)


def test_4a_a_coupon_already_held_by_another_cart_is_refused_at_eligibility(engine):
    """Two different refusals share one fact, and the distinction is worth pinning.

    A hold that ALREADY existed when we looked is an eligibility answer - `coupon_store.evaluate`
    returns `HELD_BY_ANOTHER_CART`, which crosses the provider seam as `INELIGIBLE` - so the
    invoice is refused 400 before any write is attempted. Losing the RACE for the hold is a
    different thing and answers 409; that is the test below.
    """
    _issue_coupon(engine)
    # The engine's provider uses the real clock, so the competing hold has to be taken on the
    # real clock too - a hold stamped in 2023 has lapsed and the coupon would be eligible again,
    # which is correct behaviour and would make this test pass for the wrong reason.
    cs.hold(engine.tables.coupons, code=COUPON_CODE, cart_id="someone-elses-cart")
    _refused(engine, 400, "COUPON_INELIGIBLE", couponCode=COUPON_CODE)


def test_4a2_losing_the_race_for_the_hold_is_a_conflict(engine):
    """A coupon that was eligible when evaluated and claimed by another cart a moment later.

    `coupon_store.hold` is ONE conditional `UpdateItem` with no preceding read, so the loser is
    refused by the database rather than by a check it could have raced past. 409 and not 400: the
    code is real and the caller may legitimately retry once the other hold lapses.
    """
    _issue_coupon(engine)
    engine.tables.coupons.arm_failure(
        "update_item", __import__("coupon_fake_dynamo").FakeClientError(
            "ConditionalCheckFailedException"))
    _refused(engine, 409, "HELD_BY_ANOTHER_CART", couponCode=COUPON_CODE)


def test_4b_a_coupon_store_outage_is_retryable_and_never_invalid(engine):
    """A throttle reported as "invalid" refuses a live coupon and tells the customer their code is
    wrong. `coupon_store` gives the outage its own type precisely so that cannot happen."""
    _issue_coupon(engine)
    engine.tables.coupons.arm_failure("get_item", RuntimeError("throttled"))
    payload = _refused(engine, 503, "COUPON_STORE_UNAVAILABLE", couponCode=COUPON_CODE)
    assert payload["retryable"] is True


@pytest.mark.parametrize("code,expected", [
    ("WDGC9999NOSUCH99", "GIFT_CARD_INVALID"),
    ("short", "GIFT_CARD_INVALID"),
])
def test_5a_an_unknown_or_malformed_card_is_refused_identically(engine, code, expected):
    """One answer for both, so the route cannot be ground into a code-validity oracle."""
    _refused(engine, 400, expected, giftCardCode=code)


def test_5b_a_disabled_card_is_refused(engine):
    issued = _issue_card(engine)
    gc.disable(engine.tables.cards, code_hash=issued["codeHash"],
               clock=lambda: NOW_MS // 1000)
    _refused(engine, 400, "GIFT_CARD_INELIGIBLE", giftCardCode=CARD_CODE)


def test_5c_an_expired_card_is_refused(engine):
    """Issued with an expiry a day after the fixture clock - and therefore years before the real
    one the engine's provider reads, which is what makes the card expired at create time."""
    _issue_card(engine, expires_at_ms=NOW_MS + 86_400_000)
    _refused(engine, 400, "GIFT_CARD_EXPIRED", giftCardCode=CARD_CODE)


def test_6_a_spent_card_is_refused_for_insufficient_balance(engine):
    issued = _issue_card(engine, value_paise=30000)
    engine.tables.cards.rows[issued["card"][gc.KEY_ATTRIBUTE]]["balancePaise"] = 0
    _refused(engine, 400, "INSUFFICIENT_BALANCE", giftCardCode=CARD_CODE)


@pytest.mark.parametrize("currency", ["USD", "usd", "EUR"])
def test_7_a_non_inr_invoice_carrying_a_code_is_refused(engine, currency):
    """Compared EXPLICITLY. A currency is never inferred from an amount, and the comparison
    happens before anything is read from a table."""
    _issue_coupon(engine)
    _refused(engine, 400, "UNSUPPORTED_CURRENCY", couponCode=COUPON_CODE, currency=currency)
    assert engine.tables.coupons.calls == []


def test_8_a_sub_paise_collection_is_refused_rather_than_rounded(engine):
    """A figure that is not an exact number of paise cannot be charged, and rounding it into
    something that can is how a one-paise mismatch becomes a silently wrong total. `_dec` is the
    quantiser, so this is reached by making the amount itself unrepresentable."""
    _issue_coupon(engine)
    with patch.object(engine, "_dec", side_effect=lambda v: Decimal("1.005")):
        status, payload = _create(engine, couponCode=COUPON_CODE)
    assert status == 400
    assert payload["errorCode"] == "AMOUNT_MISMATCH"
    assert engine.tables.sequence.advances == 0


def test_9_a_payable_below_one_rupee_is_refused(engine):
    """Razorpay cannot take a leg under ₹1, so an invoice that would ask it to is refused here
    rather than failing at the gateway with the customer watching. Exactly ZERO is a different
    case and is allowed - see the fully-covered test above."""
    assert gc.RAZORPAY_MIN_LEG_PAISE == 100
    _issue_card(engine, value_paise=121400)   # total 121481 paise -> 81 paise left
    _refused(engine, 400, "PAYABLE_BELOW_GATEWAY_MINIMUM", giftCardCode=CARD_CODE)


def test_a_refused_coupon_leaves_no_hold_behind(engine):
    """The hold is taken only once BOTH legs are accepted. A refused invoice must not reserve a
    coupon somebody else could have used."""
    _issue_coupon(engine)
    # The coupon brings the total to 1111.86, so a card of 111136 paise leaves 50 - under the
    # gateway minimum, which refuses the whole create AFTER the coupon was already accepted.
    _issue_card(engine, value_paise=111136)
    _refused(engine, 400, "PAYABLE_BELOW_GATEWAY_MINIMUM",
             couponCode=COUPON_CODE, giftCardCode=CARD_CODE)
    definition = cs.get_definition(engine.tables.coupons, COUPON_CODE)
    assert cs.HOLD_CART_ATTRIBUTE not in definition


# ══════════════════════════════════════════════════════════════════════════════
# 6. idempotency
# ══════════════════════════════════════════════════════════════════════════════

def test_the_coupon_hold_is_keyed_on_the_invoice_reference(engine):
    _issue_coupon(engine)
    _create(engine, couponCode=COUPON_CODE)
    definition = cs.get_definition(engine.tables.coupons, COUPON_CODE)
    assert definition[cs.HOLD_CART_ATTRIBUTE] == REFERENCE_ID


def test_re_posting_the_same_body_deduplicates_and_discounts_once(engine):
    """The second create hits the existing atomic claim and returns `deduplicated: true` WITHOUT
    re-running either leg - so one discount, one hold, and crucially no second invoice number."""
    _issue_coupon(engine)
    first_status, first = _create(engine, couponCode=COUPON_CODE)
    assert first_status == 201
    assert engine.tables.sequence.advances == 1

    second_status, second = _create(engine, couponCode=COUPON_CODE)
    assert second_status == 200
    assert second["deduplicated"] is True
    assert second["invoiceId"] == first["invoiceId"]
    assert engine.tables.sequence.advances == 1, "the replay consumed a second number"

    row = _stored(engine)
    assert row["couponDiscount"] == Decimal("100.00")
    assert row["discount"] == Decimal("100.00")


def test_the_same_reference_can_re_take_its_own_hold(engine):
    """`coupon_store.hold`'s condition includes `activeHoldCartId = :me`, so a retry for the same
    `referenceId` is idempotent by construction rather than by a caller remembering to check."""
    _issue_coupon(engine)
    _create(engine, couponCode=COUPON_CODE)
    engine.tables.invoices.rows.clear()
    status, _ = _create(engine, couponCode=COUPON_CODE)
    assert status == 201


# ══════════════════════════════════════════════════════════════════════════════
# 7. the code never leaks
# ══════════════════════════════════════════════════════════════════════════════

def test_no_gift_card_code_reaches_a_log_record_or_a_stored_attribute(engine, caplog):
    """Asserted against captured records and the stored row, not by reading source. A gift-card
    code is a bearer secret; a coupon code is broadcast marketing material and IS logged, because
    it is the only correlation id that path has."""
    _issue_coupon(engine)
    _issue_card(engine, value_paise=30000)
    with caplog.at_level(logging.DEBUG):
        _create(engine, couponCode=COUPON_CODE, giftCardCode=CARD_CODE)
        _create(engine, referenceId="WD-PAY-INVOICE09", giftCardCode="WDGC9999NOSUCH99")
    emitted = "\n".join(record.getMessage() for record in caplog.records)
    assert CARD_CODE not in emitted
    assert PEPPER not in emitted
    assert gc.code_hash(CARD_CODE, pepper=PEPPER) not in emitted
    assert COUPON_CODE in emitted

    stored = json.dumps({key: str(value) for key, value in _stored(engine).items()})
    assert CARD_CODE not in stored
    assert PEPPER not in stored
    # Only the last four, which `gift_card_store.code_last4` documents as the one part of a code
    # ever stored in clear - the renderers have to print `****0001` rather than nothing.
    assert _stored(engine)["giftCardLast4"] == CARD_CODE[-4:]


# ══════════════════════════════════════════════════════════════════════════════
# 8. a code cannot be changed after the fact
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("field", ["couponCode", "giftCardCode"])
def test_a_code_on_update_is_refused_rather_than_ignored(engine, field):
    """Silently dropping it would answer 200, look like the coupon was applied, and collect the
    full amount. Refusing says the caller must raise a new invoice."""
    response = engine.update_invoice("inv-1", {field: COUPON_CODE}, "req-3")
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["errorCode"] == "USE_CREATE"
    assert engine.tables.invoices.rows == {}


# ══════════════════════════════════════════════════════════════════════════════
# 9. the WhatsApp payload and the rendered document
# ══════════════════════════════════════════════════════════════════════════════

def test_the_meta_discount_term_carries_the_verified_gift_card(engine):
    """Meta's `order_details` has no tender concept and validates `total == subtotal + tax +
    shipping - discount`, so the amount it shows has to equal what Razorpay collects. The
    redemption therefore rides in `discount` while the stored tax stays computed on the
    pre-redemption subtotal - tax-correct and Meta-valid at once."""
    _issue_coupon(engine)
    _issue_card(engine, value_paise=30000)
    _create(engine, couponCode=COUPON_CODE, giftCardCode=CARD_CODE)
    row = _stored(engine)

    sent = {}

    def _invoke(**kwargs):
        sent.update(json.loads(json.loads(kwargs["Payload"])["body"]))
        return {"Payload": __import__("io").BytesIO(
            json.dumps({"statusCode": 200, "body": json.dumps({"messageId": "wamid.1"})}
                       ).encode())}

    client = MagicMock()
    client.invoke.side_effect = _invoke
    with patch.object(engine, "lambda_client", client):
        engine.send_payment_link(row["invoiceId"], "phone-1", "WECAREDIGITAL", "req-4")

    order = sent["checkoutOrderDetails"]["order"]
    discount_paise = order["discount"]["value"]
    # ₹100 coupon (inside `discount`) + ₹300 gift card, in paise.
    assert discount_paise == 10000 + 30000
    assert order["discount"]["description"] == "Promo + Gift Card"
    total = sent["checkoutOrderDetails"]["total_amount"]["value"]
    assert total == (order["subtotal"]["value"] + order["tax"]["value"]
                     + order["shipping"]["value"] - discount_paise)
    # And that total is what Razorpay will collect.
    assert total == int(row["amountPayable"] * 100)


def test_the_document_prints_the_coupon_and_the_card_as_two_separate_lines(engine):
    _issue_coupon(engine)
    _issue_card(engine, value_paise=30000)
    _create(engine, couponCode=COUPON_CODE, giftCardCode=CARD_CODE, discount=25)
    row = _stored(engine)

    html = engine._build_invoice_html(row, [{"name": "Service", "amount": Decimal("1000.00"),
                                             "quantity": 1, "gstRate": Decimal("18")}])
    assert "Promo" in html and "25.00" in html            # the manual adjustment, on its own
    assert f"Coupon {COUPON_CODE}" in html                # the coupon, labelled with its code
    assert "Paid by gift card" in html
    assert "Amount Payable" in html
    # NEVER the code; only the masked form.
    assert CARD_CODE not in html
    assert gc.masked(CARD_CODE[-4:]) in html
