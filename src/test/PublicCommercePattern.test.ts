import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = ( rel: string ) => readFileSync( resolve( process.cwd(), rel ), 'utf8' );

describe( 'canonical public commerce pattern', () => {
  it( 'owns policy presentation in the shared disclosure', () => {
    const policy = read( 'src/components/public/PolicyDetails.tsx' );
    expect( policy ).toContain( '<summary>Policy details</summary>' );
    expect( policy ).toContain( '<strong>Shipping / fulfilment:</strong>' );
    expect( policy ).toContain( '<strong>Returns:</strong>' );
    expect( policy ).toContain( '<strong>Refunds & cancellations:</strong>' );
    expect( policy ).toContain( 'refunds = PRODUCT_REFUNDS' );
    expect( policy ).toContain( '<strong>Disclaimer:</strong>' );
    expect( policy ).not.toContain( 'showStatutoryRights' );
    expect( policy ).not.toContain( 'overview' );
  } );

  it( 'keeps Checkout visually distinct from the Policy details disclosure', () => {
    const checkout = read( 'src/components/CheckoutAction.tsx' );
    const elsewhere = read( 'src/components/ElsewhereTravelAssistant.tsx' );
    const policy = read( 'src/components/public/PolicyDetails.tsx' );

    expect( checkout ).toContain( 'shopping_cart_checkout' );
    expect( checkout ).toContain( 'background:var(--public-accent-amber)' );
    expect( checkout ).toContain( 'border:2px solid transparent;border-radius:11px' );
    expect( checkout ).toContain( 'text-decoration:none' );
    expect( checkout ).toContain( 'background:#fff;border-color:var(--public-accent-amber)' );
    expect( checkout ).toContain( 'box-shadow:0 5px 14px rgba(240,168,24,.18),0 2px 5px rgba(26,58,42,.08)' );
    expect( checkout ).toContain( 'transform:translateY(0) scale(.98);box-shadow:none' );
    expect( checkout ).toContain( 'outline:3px solid var(--public-brand-green);outline-offset:3px' );

    // Elsewhere owns a route-local Checkout renderer, so it must use the same house icon and
    // Option B surface instead of silently drifting back to the old green contour.
    expect( elsewhere ).toContain( 'eta-material eta-checkout-icon' );
    expect( elsewhere ).toContain( '>shopping_cart_checkout</span>' );
    expect( elsewhere ).toContain( 'border:2px solid transparent;border-radius:11px;background:var(--public-accent-amber)' );
    expect( elsewhere ).toContain( 'background:#fff;border-color:var(--public-accent-amber)' );
    expect( elsewhere ).toContain( 'box-shadow:0 5px 14px rgba(240,168,24,.18),0 2px 5px rgba(26,58,42,.08)' );

    expect( policy ).toContain( 'background:var(--public-lime-tint)' );
    expect( policy ).toContain( 'text-decoration:underline' );
    expect( policy ).not.toContain( 'background:var(--public-accent-amber)' );
  } );

  it( 'keeps public commerce microcopy free of internal checkout wording', () => {
    const product = read( 'src/components/ProductBuyBox.tsx' );
    const service = read( 'src/components/ServiceBuyBox.tsx' );
    const shop = read( 'src/pages/shop/[slug].tsx' );

    for ( const [ file, source ] of [
      [ 'ProductBuyBox', product ],
      [ 'ServiceBuyBox', service ],
      [ 'shop/[slug]', shop ],
    ] as const ) {
      expect( source, file ).not.toContain( 'final total confirmed at checkout' );
      expect( source, file ).not.toContain( 'Review your final total in the cart before payment' );
      expect( source, file ).not.toContain( 'One-time purchase ·' );
    }

    expect( product ).toContain( "offerNote = 'One-time purchase'" );
    expect( service ).toContain( '>One-time service</p>' );
    expect( shop ).toContain( '>One-time purchase</p>' );
  } );

  it( 'keeps both checkout rails in CTA -> price -> offer-note order', () => {
    for ( const [ file, prefix ] of [
      [ 'src/components/ProductBuyBox.tsx', 'pbb' ],
      [ 'src/components/ServiceBuyBox.tsx', 'sbb' ],
    ] as const ) {
      const source = read( file );
      const cta = source.indexOf( '<CheckoutAction' );
      const price = source.indexOf( `className="${ prefix }-buy"` );
      const note = source.indexOf( `className="${ prefix }-offer-note"` );
      expect( cta, file ).toBeGreaterThan( -1 );
      expect( price, file ).toBeGreaterThan( cta );
      expect( note, file ).toBeGreaterThan( price );
    }
    for ( const file of [ 'src/components/ProductBuyBox.tsx', 'src/components/ServiceBuyBox.tsx' ] ) {
      const rail = read( file );
      expect( rail, file ).toContain( 'font-size:var(--public-body-size)' );
      expect( rail, file ).toContain( 'color:var(--public-muted)' );
      expect( rail, file ).toContain( 'font-family:var(--font-sans)' );
      expect( rail, file ).toContain( 'max-width:var(--public-copy-max)' );
      expect( rail, file ).toContain( 'text-wrap:balance' );
    }
  } );

  it( 'keeps Grahak OS on one shared ProductBuyBox price/note rail before SKU/policy', () => {
    const source = read( 'src/pages/grahak-os/index.tsx' );
    const checkout = source.indexOf( '<ProductBuyBox' );
    const offer = source.indexOf( 'offerNote="One-time consultation · full deployment separate"' );
    const commerce = source.indexOf( '<div className="gos-commerce">' );
    expect( checkout ).toBeGreaterThan( -1 );
    expect( offer ).toBeGreaterThan( checkout );
    expect( commerce ).toBeGreaterThan( offer );
    expect( source ).not.toContain( 'className="gos-price"' );
    expect( source ).not.toContain( 'className="gos-offer-note"' );
    expect( source ).not.toContain( 'Checkout on WhatsApp' );
    expect( source ).not.toContain( 'className="gos-wa-cta"' );
    expect( source ).not.toContain( 'className="api-steps-ctas"' );
    expect( source.slice( commerce ) ).toContain( '<PolicyDetails' );
  } );

  it( 'keeps Bharat Rx checkout metadata before its shared policy', () => {
    const source = read( 'src/pages/bharat-rx.tsx' );
    const checkout = source.indexOf( '<ProductBuyBox slug="bharat-rx" />' );
    const commerce = source.indexOf( 'className="brx-commerce"' );
    expect( commerce ).toBeGreaterThan( checkout );
    expect( source.slice( commerce ) ).toContain( '<PolicyDetails' );
    expect( source ).not.toContain( 'PRODUCT_POLICY_TEXT' );
    expect( source ).not.toContain( 'className="brx-note"' );
  } );

  it( 'keeps ProductPage policy below its checkout rail', () => {
    const source = read( 'src/components/ProductPage.tsx' );
    const checkout = source.indexOf( '{ belowCta }' );
    const commerce = source.indexOf( 'className="pdp-commerce"' );
    expect( commerce ).toBeGreaterThan( checkout );
    expect( source.slice( commerce ) ).toContain( '<PolicyDetails' );
    expect( source.slice( commerce ) ).toContain( 'refunds={ policy.refunds }' );
    expect( source ).not.toContain( 'priceUnit' );
    expect( source ).not.toContain( 'className="pdp-price"' );
  } );

  it( 'keeps Anew on the ProductBuyBox price/note rail instead of a page-local price', () => {
    const source = read( 'src/pages/anew.tsx' );
    expect( source ).toContain( "const ANEW_DISPLAY_PRICE = productCheckoutLine( 'anew' )?.formattedPrice.replace( /\\.00$/, '' ) ?? undefined" );
    expect( source ).toContain( 'displayPrice={ ANEW_DISPLAY_PRICE }' );
    expect( source ).toContain( 'offerNote="One decision · written reflection · usually 2–3 business days"' );
    expect( source ).not.toContain( 'priceUnit=' );
    expect( source ).not.toContain( 'showPrice=' );
  } );

  it( 'keeps dynamic shop pages in action -> price -> note -> SKU/policy order', () => {
    const source = read( 'src/pages/shop/[slug].tsx' );
    const action = source.indexOf( '<CheckoutAction' );
    const price = source.indexOf( '<p className="shopd-price"' );
    const note = source.indexOf( '<p className="shopd-offer-note">' );
    const commerce = source.indexOf( '<div className="shopd-policy-wrap">' );
    expect( price ).toBeGreaterThan( action );
    expect( note ).toBeGreaterThan( price );
    expect( commerce ).toBeGreaterThan( note );
    expect( source.slice( commerce ) ).toContain( '<PolicyDetails' );
    expect( source.slice( commerce ) ).toContain( 'refunds={ policy.refunds }' );
    expect( source ).toContain( 'color:var(--public-muted);text-wrap:balance' );
    expect( source ).toContain( 'className="shopd-sku-value"' );
  } );
} );
