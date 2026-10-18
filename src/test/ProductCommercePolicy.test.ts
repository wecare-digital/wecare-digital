import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PRODUCT_REFUNDS, productPolicyCopy } from '../content/productCommerce';

describe( 'shared product policy summary', () => {
  it( 'keeps the shared refund rule concise and law-safe', () => {
    expect( PRODUCT_REFUNDS ).toBe(
      'Cancellation may not be available once work starts. Approved cancellations or adjustments are issued as WECARE.DIGITAL store credit valid for 30 calendar days. No cash or original-payment-method refund is provided unless required by law.'
    );
  } );

  it( 'keeps statutory consumer-rights wording centralized in PolicyDetails', () => {
    const policy = readFileSync( resolve( process.cwd(), 'src/components/public/PolicyDetails.tsx' ), 'utf8' );
    const commerce = readFileSync( resolve( process.cwd(), 'src/content/productCommerce.ts' ), 'utf8' );
    expect( policy ).toContain( 'Statutory consumer rights remain unaffected.' );
    const grahak = commerce.slice( commerce.indexOf( "'grahak-os':" ), commerce.indexOf( "'bharat-rx':" ) );
    expect( grahak ).not.toContain( 'Statutory consumer rights remain unaffected.' );
  } );

  it( 'keeps page-specific fulfilment and disclaimer copy behind one resolver', () => {
    const grahak = productPolicyCopy( 'grahak-os', 'Grahak OS' );
    expect( grahak.shipping ).toMatch( /delivered digitally/i );
    expect( grahak.shipping ).toBe( 'Delivered digitally; no physical shipping applies. Separate physical items follow their own delivery terms.' );
    expect( grahak.returns ).toBe( 'The consultation is digital and cannot be physically returned. Separate physical items follow their own return or replacement terms.' );
    expect( grahak.disclaimer ).toContain( 'Your purchase covers one Grahak OS consultation.' );
    expect( grahak.disclaimer ).toContain( 'Deployment, implementation, integrations' );
    expect( grahak.refunds ).toBe( PRODUCT_REFUNDS );

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
