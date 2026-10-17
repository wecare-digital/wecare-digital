import { describe, expect, it } from 'vitest';
import catalog from '../content/catalogSnapshot';

describe( 'current customer product destinations', () => {
  it( 'accepts an intentionally empty snapshot and validates every product when present', () => {
    expect( catalog.productCount ).toBe( catalog.products.length );
    for ( const product of catalog.products ) {
      const slug = String( product.slug || '' );
      expect( slug, `${slug} is not a route-safe slug` )
        .toMatch( /^[a-z0-9]+(?:-[a-z0-9]+)*$/ );
    }
  } );
} );
