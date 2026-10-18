"""Checkout callbacks cannot reprice a reserved payment.

Executes the actual pure callback definitions without importing the Lambda's
module-level AWS clients. No network or production state is touched.

Coupon authority is NOT tested here any more: there is no coupon callback. The only
discount is the always-on Delight policy, applied once server-side at invoice creation
(default_coupon.delight_paise) — never advertised, applied, or removed from this Meta
data_exchange callback. The callback below is the one live sub-action that remains.
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
        '_handle_checkout_data_exchange', '_checkout_apply_shipping',
    }
    constants = set()
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


@pytest.mark.parametrize('pin', ['400051', '700001', '', 'not-a-pin'])
def test_shipping_change_refuses_without_mutating_reserved_amount(callbacks, order, pin):
    before = copy.deepcopy(order)
    response = callbacks['_checkout_apply_shipping'](
        order, {'selected_address': {'in_pin_code': pin}}, '3.0', 'req')
    assert response['version'] == '3.0'
    assert response['sub_action'] == 'apply_shipping'
    assert response['data']['error_code'] == 'SHIPPING_REQUIRES_CHECKOUT'
    assert 'order_details' not in response['data']
    assert order == before


@pytest.mark.parametrize('action', ['get_coupons', 'apply_coupon', 'remove_coupon'])
def test_retired_discount_actions_preserve_protocol_and_frozen_order(callbacks, order, action):
    before = copy.deepcopy(order)
    response = callbacks['_handle_checkout_data_exchange'](
        action, {'order_details': order}, '3.0', 'req')
    assert response['version'] == '3.0'
    assert response['sub_action'] == action
    assert response['data']['error_code'] == 'CHECKOUT_ACTION_RETIRED'
    assert 'order_details' not in response['data']
    assert order == before
