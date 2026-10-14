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
    """Catalog analytics facts from a paid attempt, provider-neutral.

    Reads a small `catalogContents` list — `[{productId, variantId, quantity}, ...]` — which a
    native checkout may attach to the attempt. The content id is emitted as
    `wix:<productId>:<variantId>` because the native catalog PRESERVES the original product and
    variant UUIDs (the Meta retailer-id contract), so the id a downstream pixel/CAPI event keys
    on is unchanged by the Wix exit.

    Returns None when the attempt is not a clean paid INR order, when no `catalogContents` is
    present (nothing to attribute), or when any line fails the known product/variant allowlist —
    a mixed basket must not attribute the whole payment to one service.
    """
    if (attempt.get('status') != payment_attempt.PAYMENT_PAID
            or not attempt.get('orderNumber') or attempt.get('currency') != 'INR'):
        return None
    amount = _integer(attempt.get('amountPaise'))
    lines = attempt.get('catalogContents')
    if not amount or not isinstance(lines, list) or not lines:
        return None
    contents = []
    for line in lines:
        if not isinstance(line, Mapping):
            return None
        product = line.get('productId')
        variant = line.get('variantId')
        quantity = _integer(line.get('quantity'))
        # A mixed basket must not attribute the entire payment to one service.
        if (product != PRODUCT_ID or not isinstance(variant, str)
                or variant not in VARIANTS or not quantity):
            return None
        contents.append({'id': f'wix:{PRODUCT_ID}:{variant}', 'quantity': quantity})
    return {'contents': contents, 'amountPaise': amount, 'currency': 'INR'}
