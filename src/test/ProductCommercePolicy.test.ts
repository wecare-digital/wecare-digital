import { describe, expect, it } from 'vitest';
import { PRODUCT_POLICY_TEXT, PRODUCT_POLICY_TITLE } from '../content/productCommerce';

describe( 'shared product policy summary', () => {
  it( 'stays concise and aligned with the Terms refund remedies', () => {
    expect( PRODUCT_POLICY_TITLE ).toBe( 'Shipping, cancellation & refunds' );
    expect( PRODUCT_POLICY_TEXT ).toBe(
      'Shipping or fulfilment timing depends on the product or service. Cancellation may not be available once work, processing or customisation has started. For voluntary cancellations or discretionary adjustments, cash refunds and refunds to the original payment method are not available; where eligible, we issue WECARE.DIGITAL store credit instead. This does not limit any refund, replacement or other remedy required by applicable law.'
    );

    expect( PRODUCT_POLICY_TEXT ).toContain( 'cash refunds and refunds to the original payment method are not available' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'WECARE.DIGITAL store credit instead' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'required by applicable law' );
    expect( PRODUCT_POLICY_TEXT ).not.toContain( 'valid for 30 days' );
  } );
} );
