import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const PRODUCT_PAGE = read( 'src/components/ProductPage.tsx' );
const SHOP_DETAIL = read( 'src/pages/shop/[slug].tsx' );
const SHOP_LISTING = read( 'src/components/ShopListingView.tsx' );
const SHOP_PRODUCTS = read( 'src/content/shopProducts.ts' );

describe( 'catalog artwork placement', () => {
  it( 'keeps catalog artwork on the Shop listing and off detail pages', () => {
    expect( SHOP_PRODUCTS ).toContain( 'anew-4096.png' );
    expect( SHOP_PRODUCTS ).toContain( 'https://wecare.digital/api/catalog-media/anew-4096.png' );
    expect( SHOP_LISTING ).toContain( 'className="shop-card-image"' );

    expect( PRODUCT_PAGE ).not.toContain( 'wd-catalog-live' );
    expect( PRODUCT_PAGE ).not.toContain( 'pdp-artwork' );
    expect( SHOP_DETAIL ).not.toContain( 'shopd-image' );
    expect( SHOP_DETAIL ).not.toContain( 'catalogue artwork' );
  } );

  it( 'keeps product and request detail pages on the shared RotatingHero layout', () => {
    expect( PRODUCT_PAGE ).toContain( "import RotatingHero from './RotatingHero';" );
    expect( PRODUCT_PAGE ).toContain( '<RotatingHero' );

    for ( const rel of [
      'src/pages/grahak-os/index.tsx',
      'src/pages/vayulok/index.tsx',
      'src/pages/bharat-rx.tsx',
      'src/pages/anew.tsx',
      'src/pages/hunar/kaushal.tsx',
      'src/pages/hunar/prastuti.tsx',
      'src/pages/niji-setu.tsx',
      'src/pages/expo-week.tsx',
      'src/pages/dastavez/drafting.tsx',
      'src/pages/dastavez/registration.tsx',
      'src/pages/dastavez/legal-reference.tsx',
      'src/pages/ritual-guru/puja-guidance.tsx',
      'src/pages/ritual-guru/diy-puja-kit.tsx',
      'src/pages/submit-request.tsx',
      'src/pages/request-amendment.tsx',
      'src/pages/drop-docs.tsx',
      'src/pages/vault.tsx',
      'src/pages/request-pickup.tsx',
      'src/pages/shipments/track.tsx',
    ] ) {
      const source = read( rel );
      expect(
        source.includes( '<RotatingHero' ) || source.includes( '<ProductPage' ),
        rel,
      ).toBe( true );
      expect( source, rel ).not.toContain( 'wd-catalog-live' );
    }
  } );
} );
