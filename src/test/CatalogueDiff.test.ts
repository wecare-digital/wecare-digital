import { describe, expect, it } from 'vitest';
import { compare } from '../../scripts/catalogue-diff.js';
import catalog from '../content/wix-catalog.json';

/**
 * The gate between "Wix changed" and "rebuild production".
 *
 * `.github/workflows/catalogue-sync.yml` runs every six hours and commits to `stack`, and branch
 * `stack` has `enableAutoBuild: true` - so whatever this function calls a change becomes a
 * production build. Both directions are failures with a cost:
 *
 *   FALSE POSITIVE  four empty commits a day and four needless Amplify builds, because
 *                   `fetch-wix-catalog.js` restamps `fetchedAt` and `variantVerifiedAt` on every
 *                   single run. This is the common case, not the edge case.
 *   FALSE NEGATIVE  a product added in Wix never reaches the site, which is the whole defect B2
 *                   exists to fix.
 *
 * So each case below is one of those two, stated as a property.
 */

type Snapshot = Record<string, unknown>;

const base = (): Snapshot => ( {
  source: 'wix stores/v3 products/search (anonymous visitor token)',
  catalogVersion: 'V3',
  fetchedAt: '2026-10-04T14:49:13.404Z',
  productCount: 2,
  products: [
    { id: 'p1', slug: 'kiosk', name: 'Kiosk', price: '24999.00', variants: [ { id: 'v1' } ] },
    { id: 'p2', slug: 'viveka', name: 'Viveka', price: '599.00', variants: [ { id: 'v2' } ] },
  ],
  variantVerifiedAt: '2026-10-04T14:49:13.391Z',
} );

/** Deep-clone through JSON, which is enough: a snapshot is JSON by construction. */
const clone = ( value: Snapshot ): Snapshot => JSON.parse( JSON.stringify( value ) );

describe( 'the catalogue change gate', () => {
  it( 'calls a timestamp-only refetch NO CHANGE, so the schedule does not commit noise', () => {
    const after = clone( base() );
    after.fetchedAt = '2026-10-04T20:49:13.404Z';
    after.variantVerifiedAt = '2026-10-04T20:49:13.391Z';
    const result = compare( base(), after );
    expect( result.changed ).toBe( false );
    expect( result.summary ).toMatch( /no change/ );
  } );

  it( 'is insensitive to key ORDER, which Wix does not promise to keep stable', () => {
    // JSON.stringify comparison would fail here and trigger a build on a serialisation detail.
    const after = clone( base() );
    const [ first ] = after.products as Record<string, unknown>[];
    ( after.products as Record<string, unknown>[] )[ 0 ] = {
      variants: first.variants, name: first.name, price: first.price,
      slug: first.slug, id: first.id,
    };
    expect( compare( base(), after ).changed ).toBe( false );
  } );

  it( 'reports a NEW product by slug - the case that makes auto-sync worth having', () => {
    const after = clone( base() );
    ( after.products as unknown[] ).push( { id: 'p3', slug: 'new-thing', name: 'New Thing' } );
    after.productCount = 3;
    const result = compare( base(), after );
    expect( result.changed ).toBe( true );
    expect( result.added ).toEqual( [ 'new-thing' ] );
    expect( result.removed ).toEqual( [] );
    expect( result.summary ).toContain( 'new-thing' );
  } );

  it( 'reports a REMOVED product, which is the one direction worth a human reading', () => {
    const after = clone( base() );
    after.products = ( after.products as unknown[] ).slice( 0, 1 );
    after.productCount = 1;
    const result = compare( base(), after );
    expect( result.changed ).toBe( true );
    expect( result.removed ).toEqual( [ 'viveka' ] );
  } );

  it( 'reports a price edit, a rename and a variant change as a modification', () => {
    for ( const mutate of [
      ( row: Record<string, unknown> ) => { row.price = '25999.00'; },
      ( row: Record<string, unknown> ) => { row.name = 'Kiosk Pro'; },
      ( row: Record<string, unknown> ) => { row.variants = [ { id: 'v1' }, { id: 'v9' } ]; },
      ( row: Record<string, unknown> ) => { row.visible = false; },
    ] ) {
      const after = clone( base() );
      mutate( ( after.products as Record<string, unknown>[] )[ 0 ] );
      const result = compare( base(), after );
      expect( result.changed ).toBe( true );
      expect( result.modified ).toEqual( [ 'kiosk' ] );
    }
  } );

  it( 'reports a change in the top-level catalogue metadata', () => {
    // `source` moving means the fetch SCOPE moved - e.g. a visitor token replaced by an admin key,
    // which changes whether hidden products are included. That is a rebuild and a read.
    const after = clone( base() );
    after.source = 'wix stores/v3 products/search (admin api key)';
    const result = compare( base(), after );
    expect( result.changed ).toBe( true );
    expect( result.meta ).toBe( true );
  } );

  it( 'treats a slug RENAME as one removal and one addition, not a silent modification', () => {
    // The slug is the route. A rename retires /shop/<old>/ and creates /shop/<new>/, and reporting
    // it as a mere "modified" would hide that a live URL just 404'd.
    const after = clone( base() );
    ( after.products as Record<string, unknown>[] )[ 0 ].slug = 'kiosk-2';
    const result = compare( base(), after );
    expect( result.added ).toEqual( [ 'kiosk-2' ] );
    expect( result.removed ).toEqual( [ 'kiosk' ] );
  } );

  it( 'finds no change when the committed snapshot is compared with itself', () => {
    // Drives the REAL file, so the shape this function is given in CI is the shape it was written
    // against - a committed snapshot that grew a field would otherwise only be discovered live.
    const result = compare(
      catalog as unknown as Snapshot, clone( catalog as unknown as Snapshot ) );
    expect( result.changed ).toBe( false );
  } );
} );
