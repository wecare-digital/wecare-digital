import sys
from pathlib import Path
from decimal import Decimal
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
from lambda_utils.ecommerce.catalog_analytics import purchase_facts, PRODUCT_ID, VARIANTS, STORES_APP_ID


def paid():
    variant = sorted(VARIANTS)[0]
    return {'status': 'PAYMENT_PAID', 'orderNumber': 'WD-ORD-QATEST01',
            'amountPaise': Decimal(5300), 'currency': 'INR',
            'wixOrderPayload': {'lineItems': [{
                'catalogReference': {'appId': STORES_APP_ID, 'catalogItemId': PRODUCT_ID,
                                     'options': {'variantId': variant}}, 'quantity': Decimal(1)}]}}


def test_paid_facts_use_frozen_variant_and_captured_total_without_customer_data():
    row = paid()
    row.update(customerPhone='+919999999999', customerId='private-customer')
    facts = purchase_facts(row)
    assert facts == {'contents': [{'id': f'wix:{PRODUCT_ID}:{sorted(VARIANTS)[0]}', 'quantity': 1}],
                     'amountPaise': 5300, 'currency': 'INR'}


@pytest.mark.parametrize('status', ['PAYMENT_PENDING', 'PAYMENT_FAILED', 'CREATED', 'PAYMENT_EXPIRED'])
def test_not_paid_cannot_be_a_purchase(status):
    row = paid(); row['status'] = status
    assert purchase_facts(row) is None


@pytest.mark.parametrize('field,value', [('orderNumber', ''), ('amountPaise', True),
    ('amountPaise', Decimal('1.1')), ('amountPaise', Decimal('NaN')), ('currency', 'USD')])
def test_incomplete_or_invalid_paid_evidence_is_omitted(field, value):
    row = paid(); row[field] = value
    assert purchase_facts(row) is None


@pytest.mark.parametrize('ref', ['malformed', {'options': 'bad'}, {'catalogItemId': 'other'}])
def test_unknown_references_do_not_emit_or_break_status(ref):
    row = paid(); row['wixOrderPayload']['lineItems'][0]['catalogReference'] = ref
    assert purchase_facts(row) is None


def test_mixed_basket_does_not_attribute_all_payment_to_one_service():
    row = paid(); row['wixOrderPayload']['lineItems'].append({'catalogReference': {}, 'quantity': 1})
    assert purchase_facts(row) is None
