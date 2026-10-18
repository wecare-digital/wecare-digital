"""The checkout shipping data_exchange callback prices shipping by pincode only.

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


def test_shipping_prices_by_pincode_and_recomputes_the_total(callbacks, order):
    response = callbacks['_checkout_apply_shipping'](
        order, {'selected_address': {'in_pin_code': '400051'}}, '3.0', 'req')
    details = response['data']['order_details']
    # Shipping repriced for the Mumbai zone; total recomputed from the frozen components
    # (subtotal 20000 + shipping 9900 + tax 3600 - discount 1000 = 32500).
    assert details['order']['shipping']['value'] == 9900
    assert details['total_amount']['value'] == 32500
    assert details['shipping_info']['selected_address']['in_pin_code'] == '400051'


def test_recalculate_total_subtracts_the_frozen_delight_discount_only(callbacks, order):
    # The `discount` field is the already-applied, server-decided Delight figure; there is no
    # coupon term. A stray `coupon` key on the order is ignored, not honoured.
    order['coupon'] = {'code': 'FORGED', 'discount': {'offset': 100, 'value': 99999}}
    total = callbacks['_recalculate_order_total'](order)
    assert total == 27500  # 20000 + 4900 + 3600 - 1000, coupon ignored
