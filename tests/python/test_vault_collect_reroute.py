"""Keep Vault purchases on the native service rail, and honor in-flight invoice settlements.

All tests use AST-loaded functions and fake AWS clients. No provider calls or charges.
The old Vault-via-Collect invoice settlement helper remains for pre-fix in-flight invoices.
"""
import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / 'amplify/functions/core/secure-files/handler.py'


def _load(name, env):
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    base = {'Dict': dict, 'Any': object, 'Optional': Optional, 'Tuple': tuple,
            'json': json, 'time': __import__('time'), 'hashlib': hashlib,
            'ClientError': ClientError,
            'logger': SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                      error=lambda *a: None)}
    base.update(env)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), base)
    return base[name]


# ── _start_native_vault_payment ──────────────────────────────────────────────

ITEM = {'fileId': 'file-1', 'ownerPhone': '919000000001',
        'ownerCustomerId': 'owner-sub', 'ownerName': 'Example Customer'}
CONFIRMATION = {'confirmed': True, 'checkoutAddressUpdatedAt': 1793690000}


def _payment_fn(outcome='PAYMENT_REQUEST_SENT', *, price_valid=True, storage_ready=True,
                invoke_error=False, already_paid=False):
    calls = []
    def invoke(**kwargs):
        calls.append(('invoke', kwargs))
        if invoke_error:
            raise RuntimeError('transport timed out after possible send')
        return {'Payload': io.BytesIO(json.dumps({'outcome': outcome}).encode('utf-8'))}

    def update_item(**kwargs):
        calls.append(('audit', kwargs))

    env = {
        'BUSINESS_API_FUNCTION': 'wecare-whatsapp-business-api:live',
        'FILES_TABLE': 'files',
        '_lambda_client': lambda: SimpleNamespace(invoke=invoke),
        '_table': lambda name: SimpleNamespace(update_item=update_item),
        '_vault_file_storage_ready': lambda item: storage_ready,
        '_vault_storage_unavailable': lambda origin: {'statusCode': 503, 'body': {'error': 'VAULT_STORAGE_UNAVAILABLE'}},
        '_vault_offer_catalog_price_valid': lambda: price_valid,
        '_paid_marks': lambda item: already_paid,
        'catalog_service_checkout': SimpleNamespace(
            VAULT_ITEM_DESCRIPTION_DEFAULT='Vault Access (24 Hrs)',
            valid_vault_item_description=lambda raw: isinstance(raw, str) and 12 <= len(raw) <= 60),
        '_PAYMENT_REQUEST_REPLIES': {
            'PAYMENT_REQUEST_SENT': (200, 'Payment request sent'),
            'PAYMENT_REQUEST_REFUSED': (502, 'Nothing was charged'),
            'PAYMENT_REQUEST_UNCONFIRMED': (202, 'Check WhatsApp'),
            'VAULT_DELIVERY_CONFIRMATION_REQUIRED': (409, 'Confirm delivery address'),
        },
        'cors_response': lambda code, body, origin: {'statusCode': code, 'body': body},
        '_no_store': lambda result: result,
    }
    return _load('_start_native_vault_payment', env), calls


def _invoke_calls(calls):
    return [kwargs for kind, kwargs in calls if kind == 'invoke']


def test_exact_file_vault_payment_uses_native_business_rail_not_collect():
    fn, calls = _payment_fn()
    result = fn(ITEM, 'UNPAID', '', requested_by='staff', expected_total_paise=8497, delivery_address_confirmation=CONFIRMATION)
    assert result['statusCode'] == 200
    assert result['body']['outcome'] == 'PAYMENT_REQUEST_SENT'
    invokes = _invoke_calls(calls)
    assert len(invokes) == 1
    assert invokes[0]['FunctionName'] == 'wecare-whatsapp-business-api:live'
    assert invokes[0]['InvocationType'] == 'RequestResponse'
    payload = json.loads(invokes[0]['Payload'])
    assert payload['internalAction'] == 'catalogService'
    assert payload['action'] == 'sendPayment'
    assert payload['fileId'] == ITEM['fileId']
    assert payload['ownerCustomerId'] == ITEM['ownerCustomerId']
    assert payload['ownerPhone'] == ITEM['ownerPhone']
    assert payload['paymentItemDescription'] == 'Vault Access (24 Hrs)'
    assert payload['expectedTotalPaise'] == 8497
    assert payload['deliveryAddressConfirmation'] == CONFIRMATION
    assert 'rawPath' not in payload
    assert 'invoiceId' not in payload


def test_missing_review_never_reaches_payment_sender_or_audit():
    fn, calls = _payment_fn()
    result = fn(ITEM, 'UNPAID', '', requested_by='staff', expected_total_paise=8497)
    assert result['statusCode'] == 409
    assert result['body']['outcome'] == 'VAULT_DELIVERY_CONFIRMATION_REQUIRED'
    assert calls == []


def test_downstream_stale_address_refusal_does_not_poison_one_shot_file_marker():
    fn, calls = _payment_fn('VAULT_DELIVERY_CONFIRMATION_REQUIRED')
    result = fn(ITEM, 'UNPAID', '', requested_by='staff',
                delivery_address_confirmation=CONFIRMATION)
    assert result['statusCode'] == 409
    assert len(_invoke_calls(calls)) == 1
    assert [kind for kind, _ in calls if kind == 'audit'] == []


def test_native_refusal_never_claims_payment_was_sent():
    fn, calls = _payment_fn('PAYMENT_REQUEST_REFUSED')
    result = fn(ITEM, 'UNPAID', '', requested_by='staff', delivery_address_confirmation=CONFIRMATION)
    assert result['statusCode'] == 502
    assert result['body']['outcome'] == 'PAYMENT_REQUEST_REFUSED'
    assert len(_invoke_calls(calls)) == 1


def test_ambiguous_native_invoke_preserves_uncertain_status():
    fn, calls = _payment_fn(invoke_error=True)
    result = fn(ITEM, 'UNPAID', '', requested_by='staff', delivery_address_confirmation=CONFIRMATION)
    assert result['statusCode'] == 202
    assert result['body']['outcome'] == 'PAYMENT_REQUEST_UNCONFIRMED'
    assert len(_invoke_calls(calls)) == 1


def test_changed_vault_price_refuses_without_issuing_payment():
    fn, calls = _payment_fn(price_valid=False)
    result = fn(ITEM, 'UNPAID', '', requested_by='staff', expected_total_paise=8497, delivery_address_confirmation=CONFIRMATION)
    assert result['statusCode'] == 409
    assert result['body']['outcome'] == 'VAULT_QUOTE_CHANGED'
    assert _invoke_calls(calls) == []


def test_paid_vault_file_never_requests_another_payment():
    fn, calls = _payment_fn(already_paid=True)
    result = fn(ITEM, 'UNPAID', '', requested_by='staff')
    assert result['statusCode'] == 409
    assert _invoke_calls(calls) == []


def test_missing_private_file_refuses_before_payment_invoke():
    fn, calls = _payment_fn(storage_ready=False)
    result = fn(ITEM, 'UNPAID', '', requested_by='staff')
    assert result['statusCode'] == 503
    assert _invoke_calls(calls) == []


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
