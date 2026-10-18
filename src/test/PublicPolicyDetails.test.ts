import { describe, expect, it } from 'vitest';
import { EMBEDDED_POLICY_ROUTES, publicPolicyDetailsForRoute } from '../content/publicPolicyDetails';

describe( 'public PolicyDetails coverage', () => {
  it( 'covers every shared public page except home and the redirect-only 404 document', () => {
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

    for ( const route of routes ) {
      const policy = publicPolicyDetailsForRoute( route );
      expect( policy, route ).not.toBeNull();
      expect( policy?.overview.length, route ).toBeGreaterThan( 20 );
      expect( policy?.shipping.length, route ).toBeGreaterThan( 20 );
      expect( policy?.returns.length, route ).toBeGreaterThan( 20 );
      expect( policy?.refunds.length, route ).toBeGreaterThan( 20 );
      expect( policy?.disclaimer.length, route ).toBeGreaterThan( 20 );
    }
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
    expect( contact?.overview ).not.toBe( privacy?.overview );
    expect( privacy?.overview ).not.toBe( cart?.overview );
    expect( contact?.disclaimer ).not.toBe( cart?.disclaimer );
  } );
} );
