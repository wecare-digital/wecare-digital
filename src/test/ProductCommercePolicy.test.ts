import { describe, expect, it } from 'vitest';
import { PRODUCT_POLICY_TEXT, PRODUCT_POLICY_TITLE, productPolicyCopy } from '../content/productCommerce';

describe( 'shared product policy summary', () => {
  it( 'stays concise and aligned with the Terms refund remedies', () => {
    expect( PRODUCT_POLICY_TITLE ).toBe( 'Shipping, returns & refunds' );
    expect( PRODUCT_POLICY_TEXT ).toBe(
      'Shipping or fulfilment timing depends on the product or service and is disclosed for the transaction. Return eligibility depends on the product or service, its condition, whether work or customisation has started, and applicable law. Refunds include approved voluntary cancellations and discretionary adjustments: cash refunds and refunds to the original payment method are not available; where eligible, we issue WECARE.DIGITAL store credit instead. Store credit issued under this policy is valid for 30 calendar days from the date of issue; any unused balance expires at the end of that period, unless applicable law requires otherwise. This does not limit any refund, replacement, return or other remedy required by applicable law.'
    );

    expect( PRODUCT_POLICY_TEXT ).toContain( 'Return eligibility depends on the product or service' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'Refunds include approved voluntary cancellations and discretionary adjustments' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'cash refunds and refunds to the original payment method are not available' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'WECARE.DIGITAL store credit instead' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'required by applicable law' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'valid for 30 calendar days from the date of issue' );
    expect( PRODUCT_POLICY_TEXT ).toContain( 'unused balance expires at the end of that period' );
  } );

  it( 'keeps page-specific fulfilment and disclaimer copy behind one resolver', () => {
    const grahak = productPolicyCopy( 'grahak-os', 'Grahak OS' );
    expect( grahak.shipping ).toMatch( /delivered digitally/i );
    expect( grahak.returns ).toContain( 'nothing physical to return' );
    expect( grahak.disclaimer ).toContain( 'Deployment, implementation, integrations' );

    const kit = productPolicyCopy( 'ritual-guru-diy-puja-kit', 'DIY Puja Kit' );
    expect( kit.shipping ).toContain( 'physical fulfilment' );

    const visa = productPolicyCopy(
      'elsewhere-visa',
      'Visa',
      'Visa decisions are controlled by the relevant authority.',
    );
    expect( visa.disclaimer ).toBe( 'Visa decisions are controlled by the relevant authority.' );
  } );
} );
