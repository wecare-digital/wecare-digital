import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
from lambda_utils.ecommerce import catalog_service_checkout as catalog


@pytest.mark.parametrize('row', [
    {'status': 'PAYMENT_PENDING', 'wixOrderId': 'wix-1', 'finalizationStage': 'WIX_CART_COMPLETED'},
    {'status': 'PAYMENT_PAID', 'finalizationStage': 'WIX_CART_COMPLETED'},
    {'status': 'PAYMENT_PAID', 'wixOrderId': 'wix-1', 'finalizationStage': 'NEEDS_RECONCILIATION'},
    {'status': 'PAYMENT_PAID', 'wixOrderId': 'wix-1', 'finalizationStage': 'WIX_ORDER_CREATED'},
])
def test_partial_finalization_cannot_unlock_service(row):
    assert catalog.finalization_complete(row) is False


def test_only_paid_wix_cart_completion_unlocks_service():
    assert catalog.finalization_complete({'status': 'PAYMENT_PAID', 'wixOrderId': 'wix-1',
                                           'finalizationStage': 'WIX_CART_COMPLETED'}) is True
