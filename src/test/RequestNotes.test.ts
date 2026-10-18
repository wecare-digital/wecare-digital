import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import { publicPolicyDetailsForRoute } from '../content/publicPolicyDetails';

const ROOT = path.join( __dirname, '..', '..' );
const PRODUCT_PAGE = fs.readFileSync(
  path.join( ROOT, 'src', 'components', 'ProductPage.tsx' ), 'utf8' );

const CTAS_RULE = ( /\.pdp-ctas\{([^}]*)\}/.exec( PRODUCT_PAGE ) ?? [] )[ 1 ];
const CTA_RULE = ( /\.pdp-cta\{([^}]*)\}/.exec( PRODUCT_PAGE ) ?? [] )[ 1 ];

describe( 'request-page disclosure ownership', () => {
  it( 'keeps non-commerce ProductPage routes on the shared Policy Details fallback', () => {
    for ( const route of [ '/leave-review', '/elsewhere/activities', '/ritual-guru/ritva' ] ) {
      expect( publicPolicyDetailsForRoute( route ), route ).not.toBeNull();
    }

    const review = publicPolicyDetailsForRoute( '/leave-review' );
    expect( review?.shipping ).toBe( 'No fulfilment applies to submitting feedback.' );
    expect( review?.returns ).toContain( 'A review is not a return' );
    expect( review?.refunds ).toContain( 'does not change refund rights' );
    expect( review?.disclaimer ).toContain( 'publication is not guaranteed' );
  } );

  it( 'does not restore the retired ProductPage boundary-note card', () => {
    expect( PRODUCT_PAGE ).not.toContain( 'className="pdp-note"' );
    expect( PRODUCT_PAGE ).not.toContain( 'className="pdp-note-p"' );
    expect( PRODUCT_PAGE ).not.toContain( '!sku && product.note' );
    expect( PRODUCT_PAGE ).not.toContain( '.pdp-note{' );
  } );
} );

describe( '.pdp-ctas single-CTA spacing contract', () => {
  it( 'keeps the 30px top gap on the wrapper, not on the pill', () => {
    expect( CTAS_RULE ).toBeDefined();
    expect( CTAS_RULE ).toContain( 'margin-top:30px' );
    expect( CTA_RULE ).toBeDefined();
    expect( CTA_RULE ).not.toContain( 'margin-top' );
    expect( CTAS_RULE ).toContain( 'display:flex' );
    expect( CTAS_RULE ).toContain( 'flex-wrap:wrap' );
  } );
} );
