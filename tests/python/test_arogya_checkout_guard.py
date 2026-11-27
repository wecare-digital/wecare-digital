"""Prevent Arogya's unbound SKU from reaching the shared charge pipeline."""
from unittest.mock import Mock

import pytest

from lambda_utils.ecommerce import catalog_pricing, native_cart, native_checkout, native_shipping


def test_arogya_catalog_price_cannot_be_used_by_ordinary_cart():
    reader = Mock()
    for product, variant in [(native_cart.AROGYA_PRODUCT_ID, native_cart.AROGYA_VARIANT_ID),
                             (native_cart.AROGYA_PRODUCT_ID.upper(), 'other'),
                             ('other', native_cart.AROGYA_VARIANT_ID.lower())]:
        with pytest.raises(ValueError, match='verified appointment checkout'):
            native_cart._unit_price_paise(reader, product, variant)
    reader.assert_not_called()


def test_saved_cart_cannot_quote_an_unbound_arogya_line():
    reader = Mock()
    cart = {'cartId': 'synthetic', 'lineItems': [
        {'productId': native_cart.AROGYA_PRODUCT_ID, 'variantId': native_cart.AROGYA_VARIANT_ID,
         'quantity': 1, 'unitPricePaise': 55000, 'requiresDelivery': False}]}
    with pytest.raises(catalog_pricing.CatalogPricingError, match='verified appointment checkout'):
        native_checkout.quote_native_cart(cart, product_reader=reader, customer_id='synthetic',
            created_at=1800000000, ttl_seconds=300, shipping_policy=native_shipping.ShippingPolicy())
    reader.assert_not_called()
