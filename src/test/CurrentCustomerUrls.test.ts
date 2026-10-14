import { describe, expect, it } from 'vitest';
import catalog from '../content/catalog-snapshot.json';

describe( 'current customer product destinations', () => {
  it( 'every snapshot product has a route-safe slug for its canonical product page', () => {
    expect( catalog.products.length ).toBeGreaterThan( 0 );
    for ( const product of catalog.products ) {
      // The snapshot no longer carries a provider `productUrl` (that was a Wix-only field, never
      // part of the ShopProduct contract). The canonical page is derived from the slug, which IS
      // the path segment of /shop/<slug>/, so the slug must be present and URL-safe for the page
      // to be reachable.
      expect( product.slug, `${product.slug} is not a route-safe slug` )
        .toMatch( /^[a-z0-9]+(?:-[a-z0-9]+)*$/ );
    }
  } );
} );
