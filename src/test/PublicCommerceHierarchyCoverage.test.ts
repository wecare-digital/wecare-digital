import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PRODUCT_CHECKOUT } from '../config/productCheckout';
import { PRODUCT_SKU_BY_SLUG } from '../content/productCommerce';
import { EMBEDDED_POLICY_ROUTES } from '../content/publicPolicyDetails';

const read = ( rel: string ): string => readFileSync( resolve( process.cwd(), rel ), 'utf8' );

interface CommerceRoute {
  route: string;
  file: string;
  owner: 'product' | 'service' | 'grahak' | 'bharat';
  selector?: string;
}

const STATIC_COMMERCE_ROUTES: readonly CommerceRoute[] = [
  { route: '/grahak-os', file: 'src/pages/grahak-os/index.tsx', owner: 'grahak' },
  { route: '/bharat-rx', file: 'src/pages/bharat-rx.tsx', owner: 'bharat' },
  { route: '/elsewhere/visa', file: 'src/pages/elsewhere/visa.tsx', owner: 'product', selector: 'elsewhere-visa' },
  { route: '/elsewhere/trip', file: 'src/pages/elsewhere/trip.tsx', owner: 'product', selector: 'elsewhere-trip' },
  { route: '/expo-week', file: 'src/pages/expo-week.tsx', owner: 'product', selector: 'expo-week' },
  { route: '/dastavez/drafting', file: 'src/pages/dastavez/drafting.tsx', owner: 'product', selector: 'dastavez-drafting' },
  { route: '/dastavez/registration', file: 'src/pages/dastavez/registration.tsx', owner: 'product', selector: 'dastavez-registration' },
  { route: '/dastavez/legal-reference', file: 'src/pages/dastavez/legal-reference.tsx', owner: 'product', selector: 'dastavez-legal-reference' },
  { route: '/ritual-guru/puja-guidance', file: 'src/pages/ritual-guru/puja-guidance.tsx', owner: 'product', selector: 'ritual-guru-puja-guidance' },
  { route: '/ritual-guru/diy-puja-kit', file: 'src/pages/ritual-guru/diy-puja-kit.tsx', owner: 'product', selector: 'ritual-guru-diy-puja-kit' },
  { route: '/anew', file: 'src/pages/anew.tsx', owner: 'product', selector: 'anew' },
  { route: '/hunar/kaushal', file: 'src/pages/hunar/kaushal.tsx', owner: 'product', selector: 'hunar-kaushal' },
  { route: '/hunar/prastuti', file: 'src/pages/hunar/prastuti.tsx', owner: 'product', selector: 'hunar-prastuti' },
  { route: '/niji-setu', file: 'src/pages/niji-setu.tsx', owner: 'product', selector: 'niji-setu' },
  { route: '/submit-request', file: 'src/pages/submit-request.tsx', owner: 'service', selector: 'SUBMIT_REQUEST' },
  { route: '/request-amendment', file: 'src/pages/request-amendment.tsx', owner: 'service', selector: 'REQUEST_AMENDMENT' },
  { route: '/drop-docs', file: 'src/pages/drop-docs.tsx', owner: 'service', selector: 'DROP_DOCS' },
  { route: '/vault', file: 'src/pages/vault.tsx', owner: 'service', selector: 'VAULT' },
  { route: '/shipments/track', file: 'src/pages/shipments/track.tsx', owner: 'product', selector: 'shipments-track' },
  { route: '/request-pickup', file: 'src/pages/request-pickup.tsx', owner: 'service', selector: 'REQUEST_PICKUP' },
] as const;

describe( 'Step 5 public commerce hierarchy coverage', () => {
  it( 'keeps the static commerce route inventory complete and fallback-suppressed', () => {
    expect( STATIC_COMMERCE_ROUTES ).toHaveLength( 20 );
    expect( [ ...EMBEDDED_POLICY_ROUTES ].sort() )
      .toEqual( STATIC_COMMERCE_ROUTES.map( row => row.route ).sort() );
  } );

  it.each( STATIC_COMMERCE_ROUTES )( '$route has exactly one checkout rail', row => {
    const source = read( row.file );
    const productBoxes = source.match( /<ProductBuyBox\b/g ) || [];
    const serviceBoxes = source.match( /<ServiceBuyBox\b/g ) || [];

    if ( row.owner === 'service' ) {
      expect( productBoxes, row.route ).toHaveLength( 0 );
      expect( serviceBoxes, row.route ).toHaveLength( 1 );
      expect( source, row.route ).toContain( `serviceByKind( '${ row.selector }' )` );
    } else {
      expect( productBoxes, row.route ).toHaveLength( 1 );
      expect( serviceBoxes, row.route ).toHaveLength( 0 );
      if ( row.owner === 'product' && row.selector ) {
        expect( PRODUCT_SKU_BY_SLUG[ row.selector ], row.route ).toBeTruthy();
      }
    }
  } );

  it( 'keeps every ordinary checkout SKU identical to the public SKU source', () => {
    for ( const [ slug, line ] of Object.entries( PRODUCT_CHECKOUT ) ) {
      expect( PRODUCT_SKU_BY_SLUG[ slug ], slug ).toBe( line.variantId );
    }
  } );

  it( 'keeps ProductPage in price/note -> SKU -> Policy Details order without a duplicate boundary note', () => {
    const source = read( 'src/components/ProductPage.tsx' );
    const checkout = source.indexOf( '{ belowCta }' );
    const commerce = source.indexOf( '<div className="pdp-commerce">' );
    const sku = source.indexOf( '<p className="pdp-sku"', commerce );
    const policy = source.indexOf( '<PolicyDetails', commerce );

    expect( checkout ).toBeGreaterThan( -1 );
    expect( commerce ).toBeGreaterThan( checkout );
    expect( sku ).toBeGreaterThan( commerce );
    expect( policy ).toBeGreaterThan( sku );
    expect( source ).toContain( 'productPolicyCopy( product.slug, product.name, product.note )' );
    expect( source ).toContain( '{ !sku && product.note && (' );
  } );

  it( 'keeps the two direct static commerce pages on the reference hierarchy', () => {
    for ( const [ file, buy, wrap, skuClass ] of [
      [ 'src/pages/grahak-os/index.tsx', '<ProductBuyBox', '<div className="gos-commerce">', 'GRAHAK_SKU' ],
      [ 'src/pages/bharat-rx.tsx', '<ProductBuyBox slug="bharat-rx" />', '<div className="brx-commerce">', 'className="brx-sku"' ],
    ] as const ) {
      const source = read( file );
      const checkout = source.indexOf( buy );
      const commerce = source.indexOf( wrap );
      const sku = source.indexOf( skuClass, commerce );
      const policy = source.indexOf( '<PolicyDetails', commerce );

      expect( checkout, file ).toBeGreaterThan( -1 );
      expect( commerce, file ).toBeGreaterThan( checkout );
      expect( sku, file ).toBeGreaterThan( commerce );
      expect( policy, file ).toBeGreaterThan( sku );
    }
  } );

  it( 'keeps dynamic shop commerce in price -> supporting note -> SKU -> Policy Details order', () => {
    const source = read( 'src/pages/shop/[slug].tsx' );
    const price = source.indexOf( '<p className="shopd-price"' );
    const note = source.indexOf( '<p className="shopd-offer-note">' );
    const wrap = source.indexOf( '<div className="shopd-policy-wrap">' );
    const sku = source.indexOf( '<p className="shopd-sku"', wrap );
    const policy = source.indexOf( '<PolicyDetails', wrap );

    expect( price ).toBeGreaterThan( -1 );
    expect( note ).toBeGreaterThan( price );
    expect( wrap ).toBeGreaterThan( note );
    expect( sku ).toBeGreaterThan( wrap );
    expect( policy ).toBeGreaterThan( sku );
  } );

  it( 'keeps shared buy boxes responsible for price and offer note only', () => {
    for ( const file of [
      'src/components/ProductBuyBox.tsx',
      'src/components/ServiceBuyBox.tsx',
    ] ) {
      const source = read( file );
      expect( source, file ).not.toContain( '<PolicyDetails' );
      expect( source, file ).not.toContain( 'SKU:' );
    }
  } );
} );
