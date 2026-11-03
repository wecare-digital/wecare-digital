"""Vault payment rerouted onto the Collect invoice-engine rail, and its post-capture settlement.

Executes the two new secure-files functions with local fakes and no AWS calls:
  * `_invoice_engine_vault_payment` - creates a pay_flow invoice and sends its payment link,
    mapping engine responses onto the `_PAYMENT_REQUEST_REPLIES` outcome vocabulary.
  * `_vault_settle_from_invoice` - mints the owner-bound paid-download grant and hands off to
    `confirm_and_deliver`, refusing when the invoice's claimed owner disagrees with the file.
"""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / 'amplify/functions/core/secure-files/handler.py'


def _load(name, env):
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    base = {'Dict': dict, 'Any': object, 'Optional': object, 'Tuple': tuple,
            'json': json, 'time': __import__('time'), 'hashlib': hashlib,
            'ClientError': ClientError,
            'logger': SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                      error=lambda *a: None)}
    base.update(env)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), base)
    return base[name]


# ── _invoice_engine_vault_payment ─────────────────────────────────────────────

ITEM = {'fileId': 'file-1', 'ownerPhone': '919000000001',
        'ownerCustomerId': 'owner-sub', 'ownerName': 'Example Customer'}


def _payment_fn(responses):
    """responses: list of (status, body) returned by successive invoice-engine invokes."""
    calls = []
    seq = iter(responses)

    def invoke(payload):
        calls.append(payload)
        return next(seq)

    env = {
        'VAULT_ITEM_RUPEES': 49, 'VAULT_EXPRESS_RUPEES': 25,
        '_invoke_invoice_engine': invoke,
        'catalog_service_checkout': SimpleNamespace(
            vault_item_description=lambda raw: raw or 'Vault Access (24 Hrs)'),
    }
    return _load('_invoice_engine_vault_payment', env), calls


def test_create_then_send_maps_to_payment_request_sent():
    fn, calls = _payment_fn([
        (201, {'invoiceId': 'inv-1'}),
        (200, {'status': 'payment_link_sent'}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'PAYMENT_REQUEST_SENT'
    # First invoke creates a pay_flow invoice carrying the file binding and the owner id.
    create = json.loads(calls[0]['body'])
    assert create['entryPoint'] == 'pay_flow'
    assert create['goodsType'] == 'physical-goods'
    assert create['vaultFileId'] == 'file-1'
    assert create['vaultCustomerId'] == 'owner-sub'
    assert create['items'][0]['amount'] == 49
    assert create['shipping'] == 25
    # Second invoke sends the payment link for the created invoice.
    assert 'send-payment-link' in calls[1]['rawPath']


def test_send_in_progress_is_also_a_clean_send():
    fn, _ = _payment_fn([
        (201, {'invoiceId': 'inv-1'}),
        (200, {'status': 'send_in_progress'}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'PAYMENT_REQUEST_SENT'


def test_delivery_required_refusal_on_create_is_refused_not_unconfirmed():
    fn, calls = _payment_fn([
        (400, {'errorCode': 'DELIVERY_REQUIRED'}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'PAYMENT_REQUEST_REFUSED'
    # No send is attempted once create refused.
    assert len(calls) == 1


def test_transient_create_failure_is_unavailable_not_charged():
    fn, _ = _payment_fn([
        (503, {'retryable': True}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'CATALOG_SERVICE_UNAVAILABLE'


def test_transient_send_failure_is_unconfirmed_never_a_clean_send():
    fn, _ = _payment_fn([
        (201, {'invoiceId': 'inv-1'}),
        (503, {}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'PAYMENT_REQUEST_UNCONFIRMED'


def test_send_refusal_from_engine_is_refused():
    fn, _ = _payment_fn([
        (201, {'invoiceId': 'inv-1'}),
        (409, {'error': 'Invoice is already paid'}),
    ])
    assert fn(ITEM, 'Vault Access (24 Hrs)', 'staff') == 'PAYMENT_REQUEST_REFUSED'


# ── _vault_settle_from_invoice ────────────────────────────────────────────────

def _settle_fn(*, file_row, grants_store, confirm_result=(True, 'pay_abc')):
    confirmed = []

    def confirm_and_deliver(order_id):
        confirmed.append(order_id)
        return confirm_result

    class _Grants:
        def get_item(self, Key, **kw):
            return {'Item': grants_store.get(Key['grantId'])} if grants_store.get(Key['grantId']) else {}

        def put_item(self, Item, ConditionExpression=None):
            gid = Item['grantId']
            if ConditionExpression and gid in grants_store:
                raise ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'PutItem')
            grants_store[gid] = Item

    env = {
        'GRANTS_TABLE': 'grants',
        '_owned_file_for_admin': lambda fid: ((file_row, None) if file_row else (None, 'UNKNOWN_FILE')),
        '_table': lambda name: _Grants(),
        'confirm_and_deliver': confirm_and_deliver,
    }
    return _load('_vault_settle_from_invoice', env), confirmed, grants_store


def test_settlement_mints_owner_bound_grant_and_confirms():
    store = {}
    file_row = {'fileId': 'file-1', 'ownerCustomerId': 'owner-sub', 'ownerPhone': '919000000001'}
    fn, confirmed, grants = _settle_fn(file_row=file_row, grants_store=store)
    ok, _ = fn({'invoiceId': 'inv-1', 'fileId': 'file-1', 'customerId': 'owner-sub',
                'razorpayOrderId': 'order_xyz', 'paymentId': 'pay_abc', 'referenceId': 'WD-PAY-1'})
    assert ok is True
    assert confirmed == ['order_xyz']
    gid = 'vault-collect-' + hashlib.sha256(b'inv-1|file-1').hexdigest()
    grant = grants[gid]
    assert grant['orderId'] == 'order_xyz'
    assert grant['customerId'] == 'owner-sub'    # from the FILE row, not the event
    assert grant['ownerPhone'] == '919000000001'
    assert grant['paid'] is False                # only Razorpay may flip this, via confirm_and_deliver
    assert grant['channel'] == 'whatsapp'


def test_settlement_refuses_when_claimed_owner_differs_from_file_owner():
    store = {}
    file_row = {'fileId': 'file-1', 'ownerCustomerId': 'owner-sub', 'ownerPhone': '919000000001'}
    fn, confirmed, grants = _settle_fn(file_row=file_row, grants_store=store)
    ok, detail = fn({'invoiceId': 'inv-1', 'fileId': 'file-1', 'customerId': 'someone-else',
                     'razorpayOrderId': 'order_xyz'})
    assert ok is False
    assert 'owner' in detail
    assert confirmed == []        # never reaches confirm/deliver
    assert grants == {}           # never mints a grant


def test_settlement_without_order_id_refuses_rather_than_granting():
    file_row = {'fileId': 'file-1', 'ownerCustomerId': 'owner-sub', 'ownerPhone': '919000000001'}
    fn, confirmed, _ = _settle_fn(file_row=file_row, grants_store={})
    ok, detail = fn({'invoiceId': 'inv-1', 'fileId': 'file-1', 'customerId': 'owner-sub'})
    assert ok is False
    assert 'razorpayOrderId' in detail
    assert confirmed == []


def test_settlement_replay_reuses_the_same_grant():
    store = {}
    file_row = {'fileId': 'file-1', 'ownerCustomerId': 'owner-sub', 'ownerPhone': '919000000001'}
    event = {'invoiceId': 'inv-1', 'fileId': 'file-1', 'customerId': 'owner-sub',
             'razorpayOrderId': 'order_xyz', 'paymentId': 'pay_abc'}
    fn, confirmed, grants = _settle_fn(file_row=file_row, grants_store=store)
    fn(event)
    fn(event)      # replayed webhook
    assert len(grants) == 1          # one grant, not two
    assert confirmed == ['order_xyz', 'order_xyz']   # idempotent re-confirm each time
