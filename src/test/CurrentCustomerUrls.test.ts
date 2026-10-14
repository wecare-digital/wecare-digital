import { describe, expect, it } from 'vitest';
import catalog from '../content/catalog-snapshot.json';

describe( 'current customer product destinations', () => {
  it( 'every snapshot product points at its existing canonical product page', () => {
    expect( catalog.products.length ).toBeGreaterThan( 0 );
    for ( const product of catalog.products ) {
      expect( product.productUrl ).toBe( `https://wecare.digital/shop/${product.slug}/` );
    }
  } );
} );
