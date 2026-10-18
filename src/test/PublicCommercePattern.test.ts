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
    expect( policy ).toContain( 'WECARE.DIGITAL store credit valid for 30 calendar days' );
    expect( policy ).toContain( '<strong>Disclaimer:</strong>' );
  } );

  it( 'keeps both checkout rails in CTA -> price -> offer-note order', () => {
    for ( const [ file, prefix ] of [
      [ 'src/components/ProductBuyBox.tsx', 'pbb' ],
      [ 'src/components/ServiceBuyBox.tsx', 'sbb' ],
    ] as const ) {
      const source = read( file );
      const cta = source.indexOf( `className="${ prefix }-cta"` );
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
    expect( source.slice( commerce ) ).toContain( 'overview={ null }' );
    expect( source.slice( commerce ) ).toContain( 'refunds={ policy.refunds }' );
    expect( source ).not.toContain( 'priceUnit' );
    expect( source ).not.toContain( 'className="pdp-price"' );
  } );

  it( 'keeps Anew on the ProductBuyBox price/note rail instead of a page-local price', () => {
    const source = read( 'src/pages/anew.tsx' );
    expect( source ).toContain( 'displayPrice="₹599"' );
    expect( source ).toContain( 'offerNote="One decision · written reflection · usually 2–3 business days"' );
    expect( source ).not.toContain( 'priceUnit=' );
    expect( source ).not.toContain( 'showPrice=' );
  } );

  it( 'keeps dynamic shop pages in action -> price -> note -> SKU/policy order', () => {
    const source = read( 'src/pages/shop/[slug].tsx' );
    const action = source.indexOf( 'className="shopd-cta shopd-cta-btn"' );
    const price = source.indexOf( '<p className="shopd-price"' );
    const note = source.indexOf( '<p className="shopd-offer-note">' );
    const commerce = source.indexOf( '<div className="shopd-policy-wrap">' );
    expect( price ).toBeGreaterThan( action );
    expect( note ).toBeGreaterThan( price );
    expect( commerce ).toBeGreaterThan( note );
    expect( source.slice( commerce ) ).toContain( '<PolicyDetails' );
    expect( source.slice( commerce ) ).toContain( 'overview={ null }' );
    expect( source.slice( commerce ) ).toContain( 'refunds={ policy.refunds }' );
    expect( source ).toContain( 'color:var(--public-muted);text-wrap:balance' );
    expect( source ).toContain( 'className="shopd-sku-value"' );
  } );
} );
