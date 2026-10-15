import sys
from pathlib import Path
from decimal import Decimal
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
from lambda_utils.ecommerce import meta_catalog_sync
from lambda_utils.ecommerce.catalog_analytics import purchase_facts, PRODUCT_ID, VARIANTS


def paid():
    """A paid native attempt carrying the provider-neutral `catalogContents` list.

    The analytics facts are projected from `catalogContents` (`[{productId, variantId,
    quantity}]`). The product/variant UUIDs are ProductsTable keys, so each emitted content id is
    the Meta catalogue retailer id for that pair.
    """
    variant = sorted(VARIANTS)[0]
    return {'status': 'PAYMENT_PAID', 'orderNumber': 'WD-ORD-QATEST01',
            'amountPaise': Decimal(5300), 'currency': 'INR',
            'catalogContents': [{'productId': PRODUCT_ID, 'variantId': variant,
                                 'quantity': Decimal(1)}]}


def test_paid_facts_use_frozen_variant_and_captured_total_without_customer_data():
    row = paid()
    row.update(customerPhone='+919999999999', customerId='private-customer')
    facts = purchase_facts(row)
    content_id = meta_catalog_sync.retailer_id(PRODUCT_ID, sorted(VARIANTS)[0])
    assert facts == {'contents': [{'id': content_id, 'quantity': 1}],
                     'amountPaise': 5300, 'currency': 'INR'}


@pytest.mark.parametrize('status', ['PAYMENT_PENDING', 'PAYMENT_FAILED', 'CREATED', 'PAYMENT_EXPIRED'])
def test_not_paid_cannot_be_a_purchase(status):
    row = paid(); row['status'] = status
    assert purchase_facts(row) is None


def test_no_catalog_contents_is_omitted_rather_than_guessed():
    """A paid order with no `catalogContents` (the native default today) yields no event, not a
    fabricated one."""
    row = paid(); del row['catalogContents']
    assert purchase_facts(row) is None


@pytest.mark.parametrize('field,value', [('orderNumber', ''), ('amountPaise', True),
    ('amountPaise', Decimal('1.1')), ('amountPaise', Decimal('NaN')), ('currency', 'USD')])
def test_incomplete_or_invalid_paid_evidence_is_omitted(field, value):
    row = paid(); row[field] = value
    assert purchase_facts(row) is None


@pytest.mark.parametrize('line', [
    {'productId': 'other', 'variantId': sorted(VARIANTS)[0], 'quantity': 1},
    {'productId': PRODUCT_ID, 'variantId': 'unknown-variant', 'quantity': 1},
    {'productId': PRODUCT_ID, 'variantId': sorted(VARIANTS)[0], 'quantity': 0},
    'malformed',
])
def test_unknown_references_do_not_emit_or_break_status(line):
    row = paid(); row['catalogContents'] = [line]
    assert purchase_facts(row) is None


def test_mixed_basket_does_not_attribute_all_payment_to_one_service():
    row = paid(); row['catalogContents'].append({'productId': 'other', 'quantity': 1})
    assert purchase_facts(row) is None
