"""The public customer id has to survive the whole way from the contact row to the order row.

THE SEAM, AND WHY IT HAS TWO HALVES THAT MUST BOTH FIRE
-------------------------------------------------------
There are two lineages out of one checkout, and they read attribution off two different rows:

  * `finalization.accept_paid` reads the ATTEMPT row and writes the ORDER row, which is what
    `/orders` and the customer's receipt are built from.
  * `razorpay-webhook._load_attempt` reads the `PAYREF#` row, and what it reports is what reaches
    `/invoices/from-payment` and therefore the GST invoice.

Writing the id to only one of them is the exact defect Phase W shipped with `channel` and had to
come back and fix: the orders page said WhatsApp while the tax invoice said Website, for one
order, with no error anywhere. So this file asserts BOTH rows carry it, from one read of the
contact row, driven through the real shipped handler.

THE PROPERTY THAT BOUNDS IT
---------------------------
A contact with no public id must produce rows byte-identical to today's. That is not a nicety:
`tests/test_checkout_service_lines.py::test_a_non_service_payref_is_unchanged` asserts the
`PAYREF#` key set by EQUALITY, so an unconditionally-written `customerUuid: ''` is a breaking
change to the row shape for no gain - `''` suppresses every downstream render anyway. Hence the
conditional spread at the write site, and hence the `absent` cases below.

AND THE PROPERTY IT MUST NOT TOUCH
----------------------------------
No money. The id is attribution: it does not reach `reconcile_payment`, it is not in
`accept_paid`'s five-key association-conflict comparison, and it changes no amount or currency.
The last two tests say so directly.

Offline throughout: FakeDynamo, a recording Razorpay stub, no network, no credential.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import (  # noqa: E402
    ATTEMPTS_TABLE, CONTACTS_TABLE, KEYS_TABLE, body_of, make_env, prepare_event)
from contribution_wix import kiosk_line  # noqa: E402
from lambda_utils import identifiers  # noqa: E402
from lambda_utils.ecommerce import finalization, payment_attempt  # noqa: E402
from lambda_utils.identity import customer_uuid  # noqa: E402

#: A real minted id, so this test cannot drift from the minter.
CUSTOMER_ID = customer_uuid.new_customer_uuid()


def _stamp_contact(fake, value):
    """Put `value` in the seeded contact's public-id attribute, or remove it for `None`."""
    table = fake.Table(CONTACTS_TABLE)
    row = dict(fake.all_rows(CONTACTS_TABLE)[0])
    if value is None:
        row.pop(customer_uuid.ATTRIBUTE, None)
    else:
        row[customer_uuid.ATTRIBUTE] = value
    table.put_item(Item=row)


def _prepare(h, fake):
    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 200, body_of(response)
    return response


def _payref(fake):
    rows = [row for row in fake.all_rows(KEYS_TABLE)
            if str(row["orderId"]).startswith("PAYREF#")]
    assert len(rows) == 1, f"expected exactly one PAYREF# row, got {len(rows)}"
    return rows[0]


def _attempt(fake):
    rows = fake.all_rows(ATTEMPTS_TABLE)
    assert len(rows) == 1, f"expected exactly one attempt row, got {len(rows)}"
    return rows[0]


# ══════════════════════════════════════════════════════════════════════════════
# 1. both rows carry it, from one read of the contact
# ══════════════════════════════════════════════════════════════════════════════

def test_the_attempt_row_carries_the_contacts_public_id(monkeypatch):
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, CUSTOMER_ID)
    _prepare(h, fake)
    assert _attempt(fake)[customer_uuid.ATTRIBUTE] == CUSTOMER_ID


def test_the_payref_row_carries_it_too(monkeypatch):
    """The webhook lineage's row. Without this the GST invoice for a WhatsApp-settled order would
    print no customer id while the orders page showed one."""
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, CUSTOMER_ID)
    _prepare(h, fake)
    assert _payref(fake)[customer_uuid.ATTRIBUTE] == CUSTOMER_ID


def test_both_rows_agree(monkeypatch):
    """One read of the contact row, so the two lineages cannot disagree. Two reads is how an
    invoice and an orders page come to show different ids for one order."""
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, CUSTOMER_ID)
    _prepare(h, fake)
    assert (_attempt(fake)[customer_uuid.ATTRIBUTE]
            == _payref(fake)[customer_uuid.ATTRIBUTE] == CUSTOMER_ID)


def test_the_checkout_reads_the_contact_once(monkeypatch):
    """No extra contacts Query for the id. It is taken off the row `_checkout_profile` already
    returned, so the money path still touches ContactsTable exactly as often as before."""
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, CUSTOMER_ID)
    _prepare(h, fake)
    contact_reads = [call for call in fake.calls
                     if call[0] == CONTACTS_TABLE and call[1].startswith("query")]
    assert len(contact_reads) <= 1, contact_reads


# ══════════════════════════════════════════════════════════════════════════════
# 2. absent, and junk, leave no trace
# ══════════════════════════════════════════════════════════════════════════════

def test_a_contact_with_no_public_id_writes_rows_unchanged(monkeypatch):
    """The state of every contact created before this attribute existed. Absent, not empty -
    `test_checkout_service_lines` asserts the `PAYREF#` key set by equality."""
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, None)
    _prepare(h, fake)
    assert customer_uuid.ATTRIBUTE not in _payref(fake)
    assert customer_uuid.ATTRIBUTE not in _attempt(fake)


@pytest.mark.parametrize("junk", ["", "junk", "not-a-uuid"])
def test_a_junk_stored_value_is_dropped_not_carried(monkeypatch, junk):
    """`from_contact` re-validates at the read, so a bad value never enters the payment path at
    all - rather than travelling to a renderer that then has to decide what to do with it."""
    h, fake, _wix = make_env(monkeypatch)
    _stamp_contact(fake, junk)
    _prepare(h, fake)
    assert customer_uuid.ATTRIBUTE not in _payref(fake)
    assert customer_uuid.ATTRIBUTE not in _attempt(fake)


def test_a_uuid7_stored_on_the_contact_never_reaches_a_row(monkeypatch):
    """Named on its own because it is the one junk value that PARSES as a UUID. Carrying it would
    put the customer's record-creation millisecond on a document they keep and forward."""
    h, fake, _wix = make_env(monkeypatch)
    seven = identifiers.new_uuid7()
    _stamp_contact(fake, seven)
    _prepare(h, fake)
    assert seven not in str(_payref(fake))
    assert seven not in str(_attempt(fake))


# ══════════════════════════════════════════════════════════════════════════════
# 3. the order row, and the money boundary
# ══════════════════════════════════════════════════════════════════════════════

class _FakeOrders:
    def __init__(self):
        self.items = []

    def put_item(self, Item=None, **_):   # noqa: N803 - boto3's spelling
        self.items.append(dict(Item or {}))
        return {}

    def get_item(self, **_):
        return {}


class _FakeAttempts:
    """Enough of the attempts table for `record_paid` and `_stage`."""

    def __init__(self):
        self.writes = []

    def update_item(self, **kwargs):
        self.writes.append(kwargs)
        return {}

    def get_item(self, **_):
        return {}


def _paid_attempt(**overrides):
    """An attempt in the one state `accept_paid` accepts, with a frozen snapshot."""
    attempt = payment_attempt.build(
        customer_id="CUS_01J0000000000000000000000",
        reference_id="WD-PAY-ABCDEFGHJKMNPQ",
        amount_paise=59900,
        configuration_name="WECAREDIGITAL",
        customer_uuid=CUSTOMER_ID,
    )
    attempt = payment_attempt.transition(attempt, payment_attempt.PAYMENT_PAID)
    attempt["checkoutMode"] = "WEBSITE_RAZORPAY_STANDARD"
    attempt["snapshotHash"] = "hash-fixture"
    attempt["purchasedSnapshot"] = {"cart": {"lineItems": []}}
    attempt.update(overrides)
    return attempt


def _accept(attempt):
    orders = _FakeOrders()
    finalization.accept_paid(
        attempts=_FakeAttempts(), orders=orders, keys=None, attempt=attempt,
        outcome={"hasOrder": True, "orderId": "WD-ORD-ABCD1234",
                 "orderNumber": "WD-1001", "providerPaymentId": "pay_LIVE0000000001"},
        verified_captured_paise=59900)
    assert len(orders.items) == 1
    return orders.items[0]


def test_the_order_row_carries_the_public_id(monkeypatch):
    """The row `/orders` and the customer receipt are built from."""
    assert _accept(_paid_attempt())[customer_uuid.ATTRIBUTE] == CUSTOMER_ID


def test_an_attempt_with_no_public_id_writes_an_order_row_unchanged(monkeypatch):
    attempt = _paid_attempt()
    attempt.pop(customer_uuid.ATTRIBUTE)
    assert customer_uuid.ATTRIBUTE not in _accept(attempt)


def test_the_public_id_is_not_in_the_association_conflict_comparison():
    """THE money boundary, asserted on the source because it is about a key that must NOT appear.

    `accept_paid`'s idempotent re-entry refuses when a committed order row disagrees on
    `customerId`, `paymentAttemptId`, `providerPaymentId`, `snapshotHash` or `orderNumber` - all
    five of which are money or identity. Adding the public id would mean a harmless redelivery
    for a customer whose id was backfilled between the two deliveries raises
    `internal order association conflict`, which the handler's wrapper alarms as
    PAID_BUT_NO_ORDER. An attribution label must not be able to do that.

    Read from the AST and not from the text, for the reason this repo has been caught by twice:
    the comment explaining the rule necessarily NAMES both the conflict message and the attribute,
    so a substring search finds its own explanation. The comparison is the one tuple literal
    inside `accept_paid` that contains `'snapshotHash'`.
    """
    import ast

    source = (ROOT / "amplify/functions/shared/lambda_utils/ecommerce"
              / "finalization.py").read_text(encoding="utf-8")
    accept = next(node for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.FunctionDef) and node.name == "accept_paid")
    tuples = [
        tuple(element.value for element in node.elts)
        for node in ast.walk(accept)
        if isinstance(node, ast.Tuple)
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
        and any(getattr(e, "value", None) == "snapshotHash" for e in node.elts)
    ]
    assert len(tuples) == 1, f"expected one conflict tuple, found {tuples}"
    assert set(tuples[0]) == {"customerId", "paymentAttemptId", "providerPaymentId",
                              "snapshotHash", "orderNumber"}
    assert customer_uuid.ATTRIBUTE not in tuples[0]


def test_the_money_fields_are_untouched_by_the_public_id():
    """One paise is still one paise, and INR is still compared explicitly. The id is a string
    beside the money, never an input to it."""
    with_id = _accept(_paid_attempt())
    without = _accept({**_paid_attempt(), customer_uuid.ATTRIBUTE: ""})
    for key in ("amountPaise", "currency", "providerPaymentId", "snapshotHash", "orderNumber"):
        assert with_id[key] == without[key]
    assert with_id["amountPaise"] == 59900 and isinstance(with_id["amountPaise"], int)
    assert with_id["currency"] == "INR"
