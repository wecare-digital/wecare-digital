import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( relative: string ): string => fs.readFileSync( path.join( ROOT, relative ), 'utf8' );

describe( 'public visible-copy audit', () => {
  it( 'keeps retired checkout and secure-access implementation wording out of customer UI', () => {
    const sources = [
      read( 'src/components/ProductBuyBox.tsx' ),
      read( 'src/components/ServiceBuyBox.tsx' ),
      read( 'src/components/cart/CartPage.tsx' ),
      read( 'src/components/get/GetPage.tsx' ),
      read( 'src/pages/shop/[slug].tsx' ),
    ].join( '\n' );

    for ( const phrase of [
      'final total confirmed at checkout',
      'Review your final total in the cart before payment',
      'The store confirms your final total',
      'We could not prepare this order',
      'We could not prepare your service',
      'Your session expired. Please verify again.',
      'This page is not a checkout',
      'Live payment is not on yet',
    ] ) {
      expect( sources, phrase ).not.toContain( phrase );
    }

    expect( sources ).toContain( 'Taxes and fees are shown before payment.' );
    expect( sources ).toContain( 'We could not start this order.' );
    expect( sources ).toContain( 'We could not start your service.' );
    expect( sources ).toContain( 'Your secure access expired. Please verify again.' );
  } );

  it( 'keeps customer-facing legal copy free of implementation detail', () => {
    const privacy = read( 'src/content/legal/privacy.ts' );
    const terms = read( 'src/content/legal/terms.ts' );

    for ( const phrase of [
      'blog post identifier or slug',
      'amount in paise and the currency',
      'payment attempt identifier',
      'where applicable and as configured',
      'server-side against the authoritative order total',
      'decided by us server-side',
      'not by anything calculated in your browser',
      'as configured for those offers',
      'confirm server-side',
    ] ) {
      expect( privacy + terms, phrase ).not.toContain( phrase );
    }

    expect( privacy ).toContain( 'the contribution reference, the article it relates to, the amount and currency' );
    expect( terms ).toContain( 'We apply it against the confirmed amount due' );
    expect( terms ).toContain( 'the applicable offer rules decide which code is used' );
  } );

  it( 'changes the Grahak CTA text without changing its WhatsApp destination', () => {
    const grahak = read( 'src/pages/grahak-os/index.tsx' );
    const checkoutLinks = Array.from(
      grahak.matchAll( /<a[^>]*href="([^"]+)"[^>]*>\s*Checkout on WhatsApp(?:\s|&|<)/g ),
    ).map( match => match[ 1 ] );

    expect( checkoutLinks ).toEqual( [ 'https://wa.me/message/APDM5HUWH26SG1' ] );
    expect( grahak ).not.toMatch( /href="https:\/\/wecare\.digital\/grahak-os\/"[^>]*>\s*Checkout on WhatsApp/i );
  } );

  it( 'keeps retired Continue on WhatsApp wording out of public checkout surfaces', () => {
    const publicCheckoutSources = [
      read( 'src/pages/grahak-os/index.tsx' ),
      read( 'src/pages/bharat-rx.tsx' ),
      read( 'src/components/ProductPage.tsx' ),
      read( 'src/components/PublicShare.tsx' ),
    ].join( '\n' );

    expect( publicCheckoutSources ).not.toContain( 'Continue on WhatsApp' );
    expect( publicCheckoutSources ).toContain( 'Checkout on WhatsApp' );
  } );
} );
