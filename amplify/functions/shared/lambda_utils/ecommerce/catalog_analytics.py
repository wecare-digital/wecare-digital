"""Customer-safe catalog analytics facts from an already authorized, paid attempt.

No event is sent here. Browser consent is separate, and unknown references are
omitted rather than manufacturing a catalog match from a product name.
"""
from collections.abc import Mapping
from decimal import Decimal

from . import payment_attempt

PRODUCT_ID = 'df976a0a-f582-4535-b2e1-d532f348bd27'
VARIANTS = frozenset({
    'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b',
    'dcff995e-448c-493a-9259-f6a82ccdc2b4',
})
STORES_APP_ID = '215238eb-22a5-4c36-9e7b-e7c08025e04e'


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    try:
        return int(value) if value == int(value) and value > 0 else None
    except (ValueError, OverflowError):
        return None


def purchase_facts(attempt):
    if (attempt.get('status') != payment_attempt.PAYMENT_PAID
            or not attempt.get('orderNumber') or attempt.get('currency') != 'INR'):
        return None
    amount = _integer(attempt.get('amountPaise'))
    payload = attempt.get('wixOrderPayload')
    if not amount or not isinstance(payload, Mapping):
        return None
    lines = payload.get('lineItems')
    if not isinstance(lines, list) or not lines:
        return None
    contents = []
    for line in lines:
        if not isinstance(line, Mapping):
            return None
        ref = line.get('catalogReference') or {}
        if not isinstance(ref, Mapping):
            return None
        options = ref.get('options') or {}
        if not isinstance(options, Mapping):
            return None
        variant = options.get('variantId')
        quantity = _integer(line.get('quantity'))
        # A mixed basket must not attribute the entire payment to one service.
        if (ref.get('appId') != STORES_APP_ID or ref.get('catalogItemId') != PRODUCT_ID
                or not isinstance(variant, str) or variant not in VARIANTS or not quantity):
            return None
        contents.append({'id': f'wix:{PRODUCT_ID}:{variant}', 'quantity': quantity})
    return {'contents': contents, 'amountPaise': amount, 'currency': 'INR'}
