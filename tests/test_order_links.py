import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from crm_fake_dynamo import FakeDynamo, FakeClientError
from lambda_utils.ecommerce.order_links import bind_wix_order, canonical_order_for_wix


def tables():
    db = FakeDynamo({'orders': 'orderId', 'keys': 'orderId'})
    orders, keys = db.Table('orders'), db.Table('keys')
    orders.put_item(Item={'orderId': 'internal-1', 'orderNumber': 'ABC23456789D',
                          'customerId': 'permanent-customer', 'customerPhone': '919999999999'})
    return db, orders, keys


def bind(orders, keys, wix='wix-1'):
    bind_wix_order(orders, keys, order_id='internal-1', order_number='ABC23456789D', wix_order_id=wix)


def test_link_replay_keeps_one_order_and_permanent_customer_identity():
    db, orders, keys = tables()
    bind(orders, keys)
    bind(orders, keys)
    linked = canonical_order_for_wix(orders, keys, 'wix-1')
    assert linked['orderId'] == 'internal-1'
    assert linked['customerId'] == 'permanent-customer'
    assert linked['customerPhone'] == '919999999999'
    assert len(db.tables['orders']) == 1


def test_partial_link_failure_is_recoverable_without_recreating_wix_order():
    db, orders, keys = tables()
    db.fail_on[('orders', 'update_item')] = RuntimeError('transient storage failure')
    with pytest.raises(RuntimeError):
        bind(orders, keys)
    with pytest.raises(ValueError):
        canonical_order_for_wix(orders, keys, 'wix-1')
    bind(orders, keys)
    assert canonical_order_for_wix(orders, keys, 'wix-1')['wixOrderId'] == 'wix-1'


def test_wix_order_cannot_be_reassigned_to_another_internal_order():
    _, orders, keys = tables()
    keys.put_item(Item={'orderId': 'wix-1', 'orderIdRef': 'someone-else'})
    with pytest.raises(FakeClientError):
        bind(orders, keys)
    assert 'wixOrderId' not in orders.get_item(Key={'orderId': 'internal-1'})['Item']


def test_internal_order_cannot_be_reassigned_to_another_wix_order():
    _, orders, keys = tables()
    bind(orders, keys)
    with pytest.raises(FakeClientError):
        bind(orders, keys, 'wix-2')
    assert orders.get_item(Key={'orderId': 'internal-1'})['Item']['wixOrderId'] == 'wix-1'


def test_ordinary_wix_order_has_no_canonical_checkout_link():
    _, orders, keys = tables()
    assert canonical_order_for_wix(orders, keys, 'other-wix-order') is None


def test_wix_sync_does_not_mint_another_workspace_order(monkeypatch):
    import boto3
    import importlib.util
    from contextlib import nullcontext
    root = Path(__file__).resolve().parents[1]
    key_name = 'stack-wecare-digital-WixOrderIds'
    order_name = 'stack-wecare-digital-OrderTable'
    cache_name = 'stack-wecare-digital-WixOrdersCache'
    db = FakeDynamo({key_name: 'orderId', order_name: 'orderId', cache_name: 'orderId'})
    orders, keys = db.Table(order_name), db.Table(key_name)
    orders.put_item(Item={'orderId': 'internal-1', 'orderNumber': 'ABC23456789D',
                          'customerId': 'permanent-customer', 'channel': 'whatsapp'})
    bind(orders, keys)
    cache = db.Table(cache_name)
    cache.batch_writer = lambda: nullcontext(cache)
    original_table = db.Table
    db.Table = lambda name: cache if name == cache_name else original_table(name)
    monkeypatch.setattr(boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: object())
    spec = importlib.util.spec_from_file_location('wix_sync_under_test',
        root / 'amplify/functions/ecommerce/wix-store/handler.py')
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    monkeypatch.setattr(handler, '_wix_request', lambda *a, **k: {
        'orders': [{'id': 'wix-1', 'number': '1001', 'fulfillmentStatus': 'FULFILLED'}]})
    monkeypatch.setattr(handler, '_get_or_create_wd_order_number',
                        lambda *a, **k: pytest.fail('must not allocate another number'))
    for _ in range(2):
        result = handler._sync_orders('test')
        assert result['statusCode'] == 200
    assert len(db.tables[order_name]) == 1
    assert orders.get_item(Key={'orderId': 'internal-1'})['Item']['fulfillmentStatus'] == 'FULFILLED'
