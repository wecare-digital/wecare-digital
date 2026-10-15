import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const PRODUCT_PAGE = fs.readFileSync(
  path.join( ROOT, 'src', 'components', 'ProductPage.tsx' ), 'utf8' );
const SHOP_PRODUCTS = fs.readFileSync(
  path.join( ROOT, 'src', 'content', 'shopProducts.ts' ), 'utf8' );

describe( 'Anew artwork placement', () => {
  it( 'keeps the 4096 catalogue tile on Shop but not on the Anew detail page', () => {
    expect( SHOP_PRODUCTS ).toContain( "anew: CATALOG_ARTWORK_BASE + 'anew-4096.png'" );
    expect( PRODUCT_PAGE ).not.toContain( "anew: CATALOG_ARTWORK_BASE + 'anew-4096.png'" );
  } );

  it( 'keeps the Anew detail page on the shared RotatingHero layout', () => {
    expect( PRODUCT_PAGE ).toContain( "import RotatingHero from './RotatingHero';" );
    expect( PRODUCT_PAGE ).toContain( '<RotatingHero' );
  } );
} );
