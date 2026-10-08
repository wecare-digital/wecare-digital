"""Legacy coupon callbacks cannot change a payment without ledger authority.

Execute the actual pure callback definitions without importing the Lambda's
module-level AWS clients. No network or production state is touched.
"""
import ast
import copy
import json
import logging
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[1] / 'amplify/functions/messaging/whatsapp-business-api/handler.py'


@pytest.fixture
def callbacks():
    tree = ast.parse(HANDLER.read_text())
    names = {
        '_checkout_get_coupons', '_checkout_coupon_refusal',
        '_checkout_apply_coupon', '_checkout_remove_coupon',
        '_checkout_apply_shipping', '_calculate_shipping_paise',
        '_get_shipping_zone', '_recalculate_order_total',
    }
    constants = {'SHIPPING_RATES_PAISE', '_PIN_ZONE_MAP'}
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name in names or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                                                  t.id in constants for t in node.targets)]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {'json': json, 'logger': logging.getLogger(__name__)}
    exec(compile(module, str(HANDLER), 'exec'), namespace)
    return namespace


@pytest.fixture
def order():
    return {'reference_id': 'inv-ref', 'order': {
        'subtotal': {'offset': 100, 'value': 20000},
        'shipping': {'offset': 100, 'value': 4900},
        'tax': {'offset': 100, 'value': 3600},
        'discount': {'offset': 100, 'value': 1000},
    }, 'total_amount': {'offset': 100, 'value': 27500}}


def test_no_unbacked_coupon_is_advertised(callbacks, order):
    before = copy.deepcopy(order)
    response = callbacks['_checkout_get_coupons'](order, {}, '3.0', 'req')
    assert response['data']['coupons'] == []
    assert order == before


@pytest.mark.parametrize('action', ['apply_coupon', 'remove_coupon'])
def test_coupon_edits_refuse_without_repricing_or_mutating(callbacks, order, action):
    order['coupon'] = {'code': 'WELCOME10', 'discount': {'value': 99999, 'offset': 100}}
    before = copy.deepcopy(order)
    response = callbacks['_checkout_' + action](order, {'coupon': {'code': 'FREESHIP'}}, '3.0', 'req')
    assert response['data']['error_code'] == 'COUPON_REQUIRES_CHECKOUT'
    assert 'order_details' not in response['data']
    assert order == before


def test_shipping_cannot_reuse_a_caller_supplied_coupon_amount(callbacks, order):
    order['coupon'] = {'code': 'FORGED', 'discount': {'offset': 100, 'value': 99999}}
    before = copy.deepcopy(order)
    response = callbacks['_checkout_apply_shipping'](
        order, {'selected_address': {'in_pin_code': '700001'}}, '3.0', 'req')
    assert response['data']['error_code'] == 'COUPON_REQUIRES_CHECKOUT'
    assert order == before


def test_shipping_without_a_coupon_keeps_the_existing_callback(callbacks, order):
    response = callbacks['_checkout_apply_shipping'](
        order, {'selected_address': {'in_pin_code': '400051'}}, '3.0', 'req')
    assert response['data']['order_details']['order']['shipping']['value'] == 9900
    assert response['data']['order_details']['total_amount']['value'] == 32500
