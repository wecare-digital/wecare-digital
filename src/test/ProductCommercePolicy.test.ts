import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PRODUCT_REFUNDS, PRODUCT_SKU_BY_SLUG, productPolicyCopy } from '../content/productCommerce';

describe( 'shared product policy summary', () => {
  it( 'keeps the shared refund rule concise and law-safe', () => {
    expect( PRODUCT_REFUNDS ).toBe(
      'Cancellation may not be available once work starts. Approved cancellations or adjustments are issued as WECARE.DIGITAL store credit valid for 30 calendar days. No cash or original-payment-method refund is provided unless required by law.'
    );
  } );

  it( 'keeps the retired statutory footer out of policy source and commerce copy', () => {
    const retiredFooter = [ 'Statutory consumer rights', 'remain unaffected.' ].join( ' ' );
    const policy = readFileSync( resolve( process.cwd(), 'src/components/public/PolicyDetails.tsx' ), 'utf8' );
    const commerce = readFileSync( resolve( process.cwd(), 'src/content/productCommerce.ts' ), 'utf8' );
    expect( policy ).not.toContain( retiredFooter );
    expect( commerce ).not.toContain( retiredFooter );
    expect( policy ).not.toContain( 'showStatutoryRights' );
    expect( policy ).not.toContain( 'overview' );
  } );


  it( 'keeps every commerce policy field crisp', () => {
    for ( const slug of Object.keys( PRODUCT_SKU_BY_SLUG ) ) {
      const policy = productPolicyCopy( slug, slug );
      for ( const [ field, copy ] of Object.entries( policy ) ) {
        expect( copy.split( /\s+/ ).length, `${slug} ${field}` ).toBeLessThanOrEqual( 40 );
      }
    }
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
      'A deliberately long page note that must not replace the crisp policy override.',
    );
    expect( visa.disclaimer ).toBe(
      'We can prepare and track the application; approval and timing remain with the relevant authority.'
    );

    const anew = productPolicyCopy(
      'anew',
      'Anew',
      'A deliberately long page note that must not be copied wholesale into Policy Details.',
    );
    expect( anew.disclaimer ).toContain( 'Anew is written reflection' );
    expect( anew.disclaimer ).not.toContain( 'deliberately long page note' );
  } );
} );
