"""R1/C1 + R2: the legacy invoice settlement path cannot be tricked into a free or double settle.

These are the regression tests the 2026-10-01 audit flagged as missing. They drive the REAL
`_handle_payment_captured` / `_verified_legacy_invoice` / `_mark_invoice_paid_by_reference` against
the honest in-memory DynamoDB fake with a stubbed provider readback - never a static mock that
bypasses the handler's own control flow. Each asserts that NO invoice is actually settled on a
blocked path (the invoice row's status is read back from the fake), and that the positive path
settles exactly once.

Covered:
  (a) a PAID_BUT_BLOCKED outcome (CUSTOMER_MISMATCH, PROVIDER_PAYMENT_CONFLICT) arriving at a
      referenceId that DOES have an invoice row must quarantine, NOT settle (R1/C1).
  (b) one captured payment whose amount matches two invoice rows under one reference settles none
      (ambiguous), never both (R2 single-row discipline).
  (c) a second signature-valid event with the SAME payment_id but a DIFFERENT referenceId does not
      double-settle - the PROVIDERPAYMENT# claim blocks it (R2 one-time claim / replay defence).
  (d) a genuine UNKNOWN_REFERENCE legacy invoice with a matching provider binding and a
      provider-verified capture DOES settle exactly once (positive path preserved).
  (e) the stranded-claim window (review Issue 1): a legacy claim whose subsequent settle no-ops
      (the row's write errors between claim and settle) is RELEASED, not burned, so a legitimate
      redelivery settles exactly once; and the release is money-safe - it never removes a commerce
      PROVIDER_PAYMENT_CLAIM sharing the PROVIDERPAYMENT# namespace.
"""

import importlib
import json
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(REPO, 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_creation, order_keys  # noqa: E402

WEBHOOK_DIR = os.path.join(REPO, 'amplify', 'functions', 'payments', 'razorpay-webhook')

KEYS_TABLE = 'stack-wecare-digital-CommerceKeys'
INVOICES_TABLE = 'stack-wecare-digital-InvoicesTable'
PAYMENTS_TABLE = 'stack-wecare-digital-PaymentsTable'

REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
REFERENCE_B = 'WD-PAY-ZYXWVUTSRQPNML'
ATTEMPT = '01930000-0000-7000-8000-000000000001'
TXN = 'pay_LIVE0000000001'
PROVIDER_ORDER = 'order_ABC'
PROVIDER_ORDER_B = 'order_XYZ'
AMOUNT = 59900  # paise = Rs 599.00
CONTACT = '+919876543210'


@pytest.fixture
def webhook():
    for stale in [m for m in sys.modules if m == 'handler' or m.startswith('handler.')]:
        del sys.modules[stale]
    sys.path.insert(0, WEBHOOK_DIR)
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            module = importlib.import_module('handler')
    return module


@pytest.fixture
def fake_ddb():
    return FakeDynamo(
        keys={KEYS_TABLE: 'orderId', INVOICES_TABLE: 'invoiceId',
              PAYMENTS_TABLE: 'id'},
        indexes={INVOICES_TABLE: {'referenceId-index': ('referenceId', None)}},
    )


def _seed_attempt(ddb, *, amount=AMOUNT, currency='INR'):
    """A PAYREF# row as the payment-request builder wrote it (a commerce attempt exists)."""
    order_keys.reserve_payment_reference(
        ddb.Table(KEYS_TABLE), reference_id=REFERENCE, payment_attempt_id=ATTEMPT,
        extra={'customerId': 'CUS_01J0000000000000000000000',
               'amountPaise': amount, 'currency': currency,
               'providerPaymentId': TXN})


def _seed_invoice(ddb, *, invoice_id='INV-LEGACY-1', reference_id=REFERENCE,
                  total='599.00', status='sent', provider_order_id=PROVIDER_ORDER):
    item = {
        'invoiceId': invoice_id, 'referenceId': reference_id,
        'total': Decimal(total), 'status': status,
        'customerPhone': CONTACT, 'invoiceNumber': 'WD/2627/00001',
    }
    if provider_order_id:
        item['providerOrderId'] = provider_order_id
    ddb.Table(INVOICES_TABLE).put_item(Item=item)


def _event(*, reference_id=REFERENCE, payment_id=TXN, order_id=PROVIDER_ORDER,
           amount=AMOUNT, contact=CONTACT):
    return {'payment': {'entity': {
        'id': payment_id, 'order_id': order_id, 'amount': amount,
        'currency': 'INR', 'status': 'captured', 'method': 'upi',
        'contact': contact, 'email': 'buyer@example.com',
        'description': 'order', 'notes': {'referenceId': reference_id},
    }}}


# -- the raw-string invoice query shim (production uses a raw KeyConditionExpression) -----------

class _InvoiceRawQueryTable:
    def __init__(self, fake_table):
        self._t = fake_table

    def query(self, IndexName=None, KeyConditionExpression=None,
              ExpressionAttributeValues=None, Limit=None, **_):
        self._t._fail_if_armed('query')
        self._t.parent.calls.append((self._t.name, f'query:{IndexName}'))
        if isinstance(KeyConditionExpression, str) and 'referenceId' in KeyConditionExpression:
            ref = (ExpressionAttributeValues or {}).get(':ref')
            items = [dict(r) for r in self._t.rows.values() if r.get('referenceId') == ref]
            if Limit:
                items = items[:Limit]
            return {'Items': items, 'Count': len(items)}
        return self._t.query(IndexName=IndexName,
                             KeyConditionExpression=KeyConditionExpression,
                             ExpressionAttributeValues=ExpressionAttributeValues,
                             Limit=Limit)

    def __getattr__(self, name):
        return getattr(self._t, name)


class _HybridDynamo:
    def __init__(self, fake):
        self._fake = fake
        self.tables = fake.tables
        self.calls = fake.calls

    def Table(self, name):  # noqa: N802 - boto3's spelling
        table = self._fake.Table(name)
        if name == INVOICES_TABLE:
            return _InvoiceRawQueryTable(table)
        return table

    def arm_failure(self, *a, **k):
        return self._fake.arm_failure(*a, **k)


def _invoice_status(ddb, invoice_id):
    return ddb.tables.get(INVOICES_TABLE, {}).get(invoice_id, {}).get('status')


def _any_invoice_paid(ddb):
    return any(r.get('status') == 'paid'
               for r in ddb.tables.get(INVOICES_TABLE, {}).values())


class _PostSpies:
    """Let the real settle run; stub only the heavy downstream (post-payment, lambda, CTWA)."""

    def __init__(self, webhook):
        self.webhook = webhook

    def __enter__(self):
        self._patchers = [
            patch.object(self.webhook, 'lambda_client', MagicMock()),
            patch.object(self.webhook, '_post_payment_handler'),
            patch.object(self.webhook, '_log_ctwa_purchase'),
            patch.object(self.webhook, '_store_payment_record'),
        ]
        self.lambda_client = self._patchers[0].start()
        self.post_payment = self._patchers[1].start()
        self.ctwa = self._patchers[2].start()
        self.store = self._patchers[3].start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()


def _drive(webhook, ddb, event, *, verifier, capture_details):
    with patch.object(webhook, 'dynamodb', _HybridDynamo(ddb)):
        with patch('lambda_utils.integrations.razorpay_verify.verifier_for_event',
                   return_value=verifier):
            with patch('lambda_utils.integrations.razorpay_verify.payment_capture_details',
                       return_value=capture_details):
                webhook._handle_payment_captured(event, 'req-1')


# ══════════════════════════════════════════════════════════════════════════════
# (a) a PAID_BUT_BLOCKED outcome at a reference WITH an invoice row must NOT settle
# ══════════════════════════════════════════════════════════════════════════════

def test_paid_but_blocked_customer_mismatch_at_invoice_reference_does_not_settle(webhook, fake_ddb):
    """A capture whose commerce attempt is refused (CUSTOMER_MISMATCH) must NOT fall through to
    the legacy path and settle the same-reference invoice. R1/C1."""
    _seed_attempt(fake_ddb)
    _seed_invoice(fake_ddb)  # same reference carries an invoice row too

    # Reconcile returns a paid-but-blocked outcome. We stub _create_order_for_captured_payment to
    # produce it, which is exactly what the real reconciler returns for this class of refusal.
    with _PostSpies(webhook) as spies:
        with patch.object(webhook, '_create_order_for_captured_payment',
                          return_value={'outcome': order_creation.CUSTOMER_MISMATCH,
                                        'hasOrder': False}):
            # payment_capture_details would say "captured for the right amount" - the point is the
            # handler must NEVER even consult the legacy path for a blocked outcome.
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
                   capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))

        assert _invoice_status(fake_ddb, 'INV-LEGACY-1') == 'sent'  # NOT paid
        assert not _any_invoice_paid(fake_ddb)
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()
    # A durable quarantine row was written for the human.
    assert any(str(k).startswith(order_keys.QUARANTINE_PREFIX)
               for k in fake_ddb.tables.get(KEYS_TABLE, {}))


def test_paid_but_blocked_provider_conflict_at_invoice_reference_does_not_settle(webhook, fake_ddb):
    """Same as above for PROVIDER_PAYMENT_CONFLICT: a blocked outcome never settles the invoice."""
    _seed_attempt(fake_ddb)
    _seed_invoice(fake_ddb)
    with _PostSpies(webhook) as spies:
        with patch.object(webhook, '_create_order_for_captured_payment',
                          return_value={'outcome': order_creation.PROVIDER_PAYMENT_CONFLICT,
                                        'hasOrder': False}):
            _drive(webhook, fake_ddb, _event(),
                   verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
                   capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))

        assert _invoice_status(fake_ddb, 'INV-LEGACY-1') == 'sent'
        assert not _any_invoice_paid(fake_ddb)
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()


def test_every_paid_but_blocked_outcome_routes_to_quarantine_not_legacy(webhook, fake_ddb):
    """Enumerate the whole PAID_BUT_BLOCKED set: none may settle the same-reference invoice."""
    for kind in sorted(order_creation.PAID_BUT_BLOCKED_OUTCOMES):
        ddb = FakeDynamo(
            keys={KEYS_TABLE: 'orderId', INVOICES_TABLE: 'invoiceId', PAYMENTS_TABLE: 'id'},
            indexes={INVOICES_TABLE: {'referenceId-index': ('referenceId', None)}})
        _seed_attempt(ddb)
        _seed_invoice(ddb)
        with _PostSpies(webhook):
            with patch.object(webhook, '_create_order_for_captured_payment',
                              return_value={'outcome': kind, 'hasOrder': False}):
                _drive(webhook, ddb, _event(),
                       verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
                       capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))
        assert _invoice_status(ddb, 'INV-LEGACY-1') == 'sent', f'{kind} settled an invoice'
        assert not _any_invoice_paid(ddb), f'{kind} settled an invoice'


# ══════════════════════════════════════════════════════════════════════════════
# (b) one capture matching two invoice rows under one reference settles NONE
# ══════════════════════════════════════════════════════════════════════════════

def test_two_invoices_under_one_reference_settle_none(webhook, fake_ddb):
    """The referenceId GSI is not unique. Two rows sharing it is ambiguous: settle none."""
    _seed_invoice(fake_ddb, invoice_id='INV-A', total='599.00')
    _seed_invoice(fake_ddb, invoice_id='INV-B', total='599.00')
    with _PostSpies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))

        assert _invoice_status(fake_ddb, 'INV-A') == 'sent'
        assert _invoice_status(fake_ddb, 'INV-B') == 'sent'
        assert not _any_invoice_paid(fake_ddb)
        spies.post_payment.assert_not_called()


def test_mark_invoice_paid_by_reference_settles_exactly_one_or_none(webhook, fake_ddb):
    """Unit-level: the single-row discipline settles one unique row, and none when ambiguous."""
    # One row -> settled.
    _seed_invoice(fake_ddb, invoice_id='INV-ONE', reference_id='WD-PAY-ONEONEONEONEON')
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)):
        webhook._mark_invoice_paid_by_reference('WD-PAY-ONEONEONEONEON', 'req-x', TXN)
    assert _invoice_status(fake_ddb, 'INV-ONE') == 'paid'
    assert fake_ddb.tables[INVOICES_TABLE]['INV-ONE'].get('providerPaymentId') == TXN

    # Two rows under one reference -> ambiguous -> none, and a quarantine row is written.
    _seed_invoice(fake_ddb, invoice_id='INV-X', reference_id='WD-PAY-TWOTWOTWOTWOTW')
    _seed_invoice(fake_ddb, invoice_id='INV-Y', reference_id='WD-PAY-TWOTWOTWOTWOTW')
    with patch.object(webhook, 'dynamodb', _HybridDynamo(fake_ddb)):
        webhook._mark_invoice_paid_by_reference('WD-PAY-TWOTWOTWOTWOTW', 'req-y', TXN)
    assert _invoice_status(fake_ddb, 'INV-X') == 'sent'
    assert _invoice_status(fake_ddb, 'INV-Y') == 'sent'


# ══════════════════════════════════════════════════════════════════════════════
# (c) a replay with the SAME payment_id under a DIFFERENT reference does NOT double-settle
# ══════════════════════════════════════════════════════════════════════════════

def test_replay_same_payment_different_reference_does_not_double_settle(webhook, fake_ddb):
    """The PROVIDERPAYMENT#<payment_id> claim is one-time across references."""
    # Two unrelated legacy invoices, each bound to its own provider order, same price.
    _seed_invoice(fake_ddb, invoice_id='INV-FIRST', reference_id=REFERENCE,
                  provider_order_id=PROVIDER_ORDER, total='599.00')
    _seed_invoice(fake_ddb, invoice_id='INV-SECOND', reference_id=REFERENCE_B,
                  provider_order_id=PROVIDER_ORDER_B, total='599.00')

    # First event: payment TXN captured against PROVIDER_ORDER, settles INV-FIRST exactly once.
    with _PostSpies(webhook):
        _drive(webhook, fake_ddb,
               _event(reference_id=REFERENCE, order_id=PROVIDER_ORDER),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))
    assert _invoice_status(fake_ddb, 'INV-FIRST') == 'paid'
    assert _invoice_status(fake_ddb, 'INV-SECOND') == 'sent'

    # Replay: same payment id TXN, DIFFERENT reference/order. The claim is already held, so the
    # second invoice must NOT settle - even though its binding and amount would otherwise match.
    with _PostSpies(webhook) as spies:
        _drive(webhook, fake_ddb,
               _event(reference_id=REFERENCE_B, order_id=PROVIDER_ORDER_B),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER_B))
        spies.post_payment.assert_not_called()
    assert _invoice_status(fake_ddb, 'INV-SECOND') == 'sent'  # NOT double-settled
    # Only ONE invoice is paid in total.
    paid = [k for k, v in fake_ddb.tables[INVOICES_TABLE].items() if v.get('status') == 'paid']
    assert paid == ['INV-FIRST']


# ══════════════════════════════════════════════════════════════════════════════
# (d) a genuine bound UNKNOWN_REFERENCE legacy invoice settles exactly once
# ══════════════════════════════════════════════════════════════════════════════

def test_bound_legacy_invoice_settles_exactly_once(webhook, fake_ddb):
    """Positive path: no attempt (UNKNOWN_REFERENCE), a bound invoice, a verified capture -> paid."""
    _seed_invoice(fake_ddb, invoice_id='INV-GENUINE', provider_order_id=PROVIDER_ORDER)
    with _PostSpies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))

        assert _invoice_status(fake_ddb, 'INV-GENUINE') == 'paid'
        assert spies.store.call_count == 1
        assert spies.post_payment.call_count == 1
    # The one-time claim exists under the payment id.
    claim = fake_ddb.tables[KEYS_TABLE].get(order_keys.PROVIDER_PAYMENT_PREFIX + TXN)
    assert claim is not None
    assert claim['invoiceIdRef'] == 'INV-GENUINE'


def test_unbound_legacy_invoice_refuses_to_settle(webhook, fake_ddb):
    """R2 binding: an invoice with NO provider binding cannot be positively tied to a capture."""
    _seed_invoice(fake_ddb, invoice_id='INV-UNBOUND', provider_order_id='')
    with _PostSpies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))

        assert _invoice_status(fake_ddb, 'INV-UNBOUND') == 'sent'
        assert not _any_invoice_paid(fake_ddb)
        spies.post_payment.assert_not_called()


def test_bound_legacy_invoice_wrong_provider_order_refuses(webhook, fake_ddb):
    """R2 binding: the capture's provider order id must match the invoice's stored binding."""
    _seed_invoice(fake_ddb, invoice_id='INV-BOUND', provider_order_id=PROVIDER_ORDER)
    with _PostSpies(webhook) as spies:
        # The capture is for a DIFFERENT provider order than the invoice is bound to.
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', 'order_SOMETHING_ELSE'))

        assert _invoice_status(fake_ddb, 'INV-BOUND') == 'sent'
        assert not _any_invoice_paid(fake_ddb)
        spies.post_payment.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# (e) the stranded-claim window (review Issue 1): a claim whose settle no-ops is RELEASED,
#     so a legitimate redelivery settles exactly once - and the release never touches a
#     commerce PROVIDER_PAYMENT_CLAIM.
# ══════════════════════════════════════════════════════════════════════════════

def _provider_payment_claim(ddb):
    return ddb.tables.get(KEYS_TABLE, {}).get(order_keys.PROVIDER_PAYMENT_PREFIX + TXN)


def test_legacy_claim_released_when_settle_noops_then_redelivery_settles(webhook, fake_ddb):
    """A legacy claim is taken inside the verifier BEFORE the settle. If that settle no-ops (here a
    storage error on the invoice update), the irreversible claim would otherwise be burned with no
    settled row, stranding the payment forever. The handler must RELEASE the claim and quarantine,
    and a legitimate Razorpay redelivery must then settle exactly once."""
    _seed_invoice(fake_ddb, invoice_id='INV-STRANDED', provider_order_id=PROVIDER_ORDER)

    # First delivery: the verifier binds + claims, then the invoice update is armed to error, so
    # _mark_invoice_paid_by_reference reports not-settled and the claim is released.
    with _PostSpies(webhook) as spies:
        fake_ddb.arm_failure(INVOICES_TABLE, 'update_item', RuntimeError('throttled'))
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))
        # Nothing settled, no post-payment, no payment record on this stranded delivery.
        spies.post_payment.assert_not_called()
        spies.store.assert_not_called()
    assert _invoice_status(fake_ddb, 'INV-STRANDED') == 'sent'
    assert not _any_invoice_paid(fake_ddb)
    # The one-time claim was RELEASED (not burned), so a redelivery can re-claim it.
    assert _provider_payment_claim(fake_ddb) is None
    # A durable quarantine row was still written for the human.
    assert any(str(k).startswith(order_keys.QUARANTINE_PREFIX)
               for k in fake_ddb.tables.get(KEYS_TABLE, {}))

    # Razorpay redelivery of the SAME capture (no armed failure this time) now settles exactly once.
    with _PostSpies(webhook) as spies:
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))
        assert spies.post_payment.call_count == 1
        assert spies.store.call_count == 1
    assert _invoice_status(fake_ddb, 'INV-STRANDED') == 'paid'
    paid = [k for k, v in fake_ddb.tables[INVOICES_TABLE].items() if v.get('status') == 'paid']
    assert paid == ['INV-STRANDED']
    # The claim is now held and backed by a settled row.
    claim = _provider_payment_claim(fake_ddb)
    assert claim is not None and claim['invoiceIdRef'] == 'INV-STRANDED'


def test_release_is_money_safe_when_a_row_actually_settled(webhook, fake_ddb):
    """If the settle DID mark a row paid, the claim must be KEPT, never released - a settled row
    must stay backed by its one-time claim so a replay still finds it held."""
    _seed_invoice(fake_ddb, invoice_id='INV-KEPT', provider_order_id=PROVIDER_ORDER)
    with _PostSpies(webhook):
        _drive(webhook, fake_ddb, _event(),
               verifier=lambda _r: (True, TXN, AMOUNT, 'INR'),
               capture_details=(True, AMOUNT, 'INR', PROVIDER_ORDER))
    assert _invoice_status(fake_ddb, 'INV-KEPT') == 'paid'
    # Claim retained because a row actually settled.
    claim = _provider_payment_claim(fake_ddb)
    assert claim is not None and claim['invoiceIdRef'] == 'INV-KEPT'


def test_release_never_removes_a_commerce_provider_payment_claim(webhook, fake_ddb):
    """Unit-level money-safety: release_legacy_invoice_payment_claim is conditional on the row being
    a LEGACY_INVOICE_PAYMENT_CLAIM for this invoice. A commerce PROVIDER_PAYMENT_CLAIM sharing the
    PROVIDERPAYMENT# namespace (one payment funds at most one order) must NEVER be released."""
    keys_table = fake_ddb.Table(KEYS_TABLE)
    # Simulate the commerce path having claimed this payment for an order.
    order_keys.claim_order_for_payment(
        keys_table, payment_attempt_id=ATTEMPT, order_id='ORD-COMMERCE',
        provider_transaction_id=TXN)
    before = _provider_payment_claim(fake_ddb)
    assert before is not None and before['kind'] == 'PROVIDER_PAYMENT_CLAIM'

    # A (hypothetical) legacy release for the same payment id must lose the conditional delete.
    released = order_keys.release_legacy_invoice_payment_claim(
        keys_table, payment_id=TXN, invoice_id='INV-WHATEVER')
    assert released is False
    after = _provider_payment_claim(fake_ddb)
    assert after is not None and after['kind'] == 'PROVIDER_PAYMENT_CLAIM'


def test_release_only_removes_the_matching_invoice_claim(webhook, fake_ddb):
    """A legacy release is bound to the invoice the claim names: a release naming a DIFFERENT
    invoice must be a no-op, so a claim another worker re-bound is never removed."""
    keys_table = fake_ddb.Table(KEYS_TABLE)
    won, _ = order_keys.claim_legacy_invoice_payment(
        keys_table, payment_id=TXN, invoice_id='INV-REAL', reference_id=REFERENCE)
    assert won is True

    # Wrong invoice id -> conditional delete loses, claim stays.
    assert order_keys.release_legacy_invoice_payment_claim(
        keys_table, payment_id=TXN, invoice_id='INV-OTHER') is False
    assert _provider_payment_claim(fake_ddb) is not None

    # Correct invoice id -> released.
    assert order_keys.release_legacy_invoice_payment_claim(
        keys_table, payment_id=TXN, invoice_id='INV-REAL') is True
    assert _provider_payment_claim(fake_ddb) is None
