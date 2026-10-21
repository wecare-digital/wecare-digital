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

  it( 'keeps every public commerce entry single-channel until after cart review', () => {
    const entrySources = [
      read( 'src/pages/grahak-os/index.tsx' ),
      read( 'src/pages/bharat-rx.tsx' ),
      read( 'src/pages/shop/[slug].tsx' ),
      read( 'src/components/ProductPage.tsx' ),
      read( 'src/components/ProductBuyBox.tsx' ),
      read( 'src/components/ServiceBuyBox.tsx' ),
      read( 'src/components/PublicShare.tsx' ),
      read( 'src/components/ElsewhereTravelAssistant.tsx' ),
    ].join( '\n' );

    // Route/widget commerce must not expose a payment-channel choice before the cart.
    expect( entrySources ).not.toContain( 'Checkout on WhatsApp' );
    expect( entrySources ).not.toContain( 'Continue on WhatsApp' );
    expect( entrySources ).not.toContain( 'Pay on WhatsApp' );
    expect( entrySources ).not.toContain( 'Pay here' );

    // Contribute follows the same contract: one Checkout entry, then the shared cart.
    const contribute = read( 'src/components/PublicShare.tsx' );
    expect( contribute ).toContain( 'aria-label="Checkout contribution"' );
    expect( contribute ).not.toContain( 'aria-label="Contribute on WhatsApp"' );
  } );

  it( 'keeps the two payment options only on the post-cart checkout page', () => {
    const chooser = read( 'src/pages/checkout/index.tsx' );
    expect( chooser ).toContain( 'Pay on WhatsApp' );
    expect( chooser ).toContain( 'Pay here' );
    expect( chooser ).toContain( 'The ONE payment-method decision after cart review.' );
  } );
} );
