import { describe, expect, it } from 'vitest';
import { PRODUCT_POLICY_TEXT, PRODUCT_POLICY_TITLE } from '../content/productCommerce';

describe( 'shared product policy summary', () => {
  it( 'stays concise and aligned with the Terms refund remedies', () => {
    expect( PRODUCT_POLICY_TITLE ).toBe( 'Shipping, cancellation & refunds' );
    expect( PRODUCT_POLICY_TEXT ).toBe(
      'Shipping or fulfilment timing depends on the product or service. Cancellation may not be available once work, processing or customisation has started. Where a refund or other remedy is available, it is handled under the applicable service terms and law and may include the original payment method, store credit, replacement or rescheduling.'
    );

    expect( PRODUCT_POLICY_TEXT ).toContain( 'original payment method' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'applicable service terms and law' );
    expect( PRODUCT_POLICY_TEXT ).not.toContain( 'Cash refunds are not available' );
    expect( PRODUCT_POLICY_TEXT ).not.toContain( 'store credit valid for 30 days' );
  } );
} );
