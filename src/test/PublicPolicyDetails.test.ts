import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { EMBEDDED_POLICY_ROUTES, publicPolicyDetailsForRoute } from '../content/publicPolicyDetails';

describe( 'public PolicyDetails coverage', () => {
  const routes = [
    '/contact',
    '/orders',
    '/vayulok',
    '/elsewhere/activities',
    '/ritual-guru/ritva',
    '/leave-review',
    '/privacy',
    '/terms',
    '/shop',
    '/account/sign-in',
    '/cart',
    '/checkout/status',
    '/checkout/success',
    '/get',
    '/blog',
    '/blog/page/[page]',
    '/blog/topic/[topic]',
    '/blog/topic/[topic]/page/[page]',
    '/post/[slug]',
    '/shop/page/[page]',
  ];

  it( 'covers every shared public page except home and the redirect-only 404 document', () => {
    for ( const route of routes ) {
      const policy = publicPolicyDetailsForRoute( route );
      expect( policy, route ).not.toBeNull();
      expect( Object.keys( policy || {} ).sort(), route )
        .toEqual( [ 'disclaimer', 'refunds', 'returns', 'shipping' ] );
      expect( policy?.shipping.length, route ).toBeGreaterThan( 20 );
      expect( policy?.returns.length, route ).toBeGreaterThan( 20 );
      expect( policy?.refunds.length, route ).toBeGreaterThan( 20 );
      expect( policy?.disclaimer.length, route ).toBeGreaterThan( 20 );
    }
  } );

  it( 'renders shared fallback policy as four concepts without an overview paragraph', () => {
    const source = readFileSync(
      resolve( process.cwd(), 'src/components/public/PublicPolicyDetails.tsx' ),
      'utf8',
    );
    expect( source ).not.toContain( 'policy.overview' );
    expect( source ).toContain( 'showStatutoryRights={ false }' );
  } );

  it( 'does not duplicate product-level PolicyDetails', () => {
    for ( const route of EMBEDDED_POLICY_ROUTES ) {
      expect( publicPolicyDetailsForRoute( route ), route ).toBeNull();
    }
    expect( publicPolicyDetailsForRoute( '/shop/[slug]' ) ).toBeNull();
    expect( publicPolicyDetailsForRoute( '/grahak-os' ) ).toBeNull();
  } );

  it( 'keeps home and the redirect-only 404 document free of the disclosure', () => {
    expect( publicPolicyDetailsForRoute( '/' ) ).toBeNull();
    expect( publicPolicyDetailsForRoute( '/404' ) ).toBeNull();
  } );

  it( 'uses route-specific wording rather than one shared paragraph for unrelated pages', () => {
    const contact = publicPolicyDetailsForRoute( '/contact' );
    const privacy = publicPolicyDetailsForRoute( '/privacy' );
    const cart = publicPolicyDetailsForRoute( '/cart' );
    expect( contact?.shipping ).not.toBe( privacy?.shipping );
    expect( privacy?.refunds ).not.toBe( cart?.refunds );
    expect( contact?.disclaimer ).not.toBe( cart?.disclaimer );
  } );
} );
