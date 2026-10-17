import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getStaticPaths } from '../pages/shop/[slug]';
import { shopProductBySlug } from '../content/shop';
import catalogue from '../content/catalogSnapshot';

/**
 * THE TWO HALVES OF THE /shop CATALOGUE DECISION, PINNED TOGETHER IN ONE FILE.
 *
 * On 2026-10-04 the owner withdrew the catalogue index and had /shop 301 to the home page. On
 * 2026-10-10 the owner REVERSED that: /shop is browsable again. This file is inverted to pin the
 * restored state (the repo's standing "invert, don't delete" convention, so the file keeps
 * guarding both halves of the decision rather than disappearing):
 *
 *   ITEM 1  /shop/ is browsable: the index page exists, no /shop 301 rules remain, and '/shop' is
 *           in the page allowlist and the sitemap.
 *   ITEM 2  every /shop/<slug>/ product page keeps rendering and keeps adding to cart.
 *
 * ITEM 2 was never affected by either direction of the decision - the product pages read the same
 * SHOP_PRODUCTS list the index does - so those assertions are unchanged. What inverted is ITEM 1:
 * the page must now EXIST, the redirect rules must now be ABSENT, and the breadcrumb must now NAME
 * the index rather than hide it.
 *
 * WHY SOME ASSERTIONS READ SOURCE AS TEXT. Where the value under test is a LITERAL rather than a
 * runtime export - a Python dict, a `const` array of route strings - there is nothing to import,
 * so the source is read and parsed. src/test/PublicRouteRegistration.test.ts and
 * src/test/PublicAiSurface.test.ts already use exactly this technique, and it is the only way a
 * vitest file can assert the content of a Python provisioner.
 *
 * EVERY SOURCE SCAN SLICES ITS DECLARATION FIRST, and that is not a style preference.
 * `PublicAiSurface.test.ts` records why: the declarations in this repo carry long explanatory
 * comments BETWEEN their entries which themselves quote route paths, so matching a raw block
 * "picks up 24 paths for 21 entries". A file-wide `not.toContain( '/shop' )` would be wrong in
 * both directions at once - it would pass on a file that still declared `'/shop/'` (a different
 * quoted token), and it would fail on a file whose only mention of `/shop` is the comment
 * explaining the withdrawal. Both failure modes are present in the files below, because the
 * withdrawal comments necessarily name the route they are withdrawing.
 */

const ROOT = path.resolve( __dirname, '..', '..' );
const read = ( relative: string ): string =>
  fs.readFileSync( path.join( ROOT, relative ), 'utf8' );

/**
 * Slice a declaration out of a source file and return the quoted route-ish tokens inside it,
 * comment lines stripped. `end` is the token that closes the declaration, which differs per file:
 * `] )` for the sitemap's `new Set( [ ... ] )`, `]` for a bare array.
 */
const declaredTokens = ( source: string, declaration: string, end: string ): string[] => {
  const start = source.indexOf( declaration );
  expect( start, `${declaration} not found - this guard needs updating` ).toBeGreaterThan( -1 );
  const stop = source.indexOf( end, start + declaration.length );
  expect( stop, `${declaration} is unterminated` ).toBeGreaterThan( -1 );
  return Array.from(
    source.slice( start, stop )
      .split( '\n' )
      .filter( line => !line.trim().startsWith( '//' ) )
      .join( '\n' )
      .matchAll( /'(\/[a-z0-9\-/[\]]*)'/g ),
  ).map( match => match[ 1 ] );
};

describe( 'the restored catalogue index (ITEM 1)', () => {
  it( 'a: has a listing page in the export again', () => {
    // Restored 2026-10-10. output: 'export' emits out/shop/index.html from this source file, which
    // is what makes /shop/ serve the catalogue rather than fall through to the catch-all.
    expect( fs.existsSync( path.join( ROOT, 'src/pages/shop/index.tsx' ) ) ).toBe( true );
  } );

  it( 'b: declares no /shop redirect, and no /shop wildcard either', () => {
    /*
     * THIS ASSERTS A DECLARATION, NOT LIVE BEHAVIOUR. A vitest file cannot reach Amplify, so what
     * is checked here is that scripts/provision_legacy_redirects.py SAYS the right thing. The live
     * proof is the /shop rows in scripts/probe_url_host_matrix.py, which follow the real redirect
     * chain against the deployed site; tests/test_url_host_routing_rules.py proves the same
     * declaration from the Python side, against what apply() actually writes.
     *
     * BOTH the three index 301s AND a /shop wildcard must be ABSENT: either one, in front of a
     * page that now resolves at 200, would 301 the restored catalogue away.
     */
    const provisioner = read( 'scripts/provision_legacy_redirects.py' );
    const signature = provisioner.indexOf( 'def desired_redirects' );
    expect( signature, 'desired_redirects() not found' ).toBeGreaterThan( -1 );

    /*
     * SLICED TO THE `return [ ... ]` LIST, NOT TO THE WHOLE FUNCTION BODY. desired_redirects()'s
     * docstring names /shop while explaining the restoration, so slicing the body would make the
     * negative assertions below fail against a correct provisioner and the obvious "fix" would be
     * to delete the explanation.
     */
    const start = provisioner.indexOf( 'return [', signature );
    expect( start, 'desired_redirects() has no return list' ).toBeGreaterThan( -1 );
    const list = provisioner.slice( start, provisioner.indexOf( '\n    ]', start ) );

    for ( const spelling of [ '/shop', '/shop/', '/shop/index.html' ] ) {
      expect(
        list,
        `${spelling} is still declared as a 301 in desired_redirects(), but the index is restored.`,
      ).not.toContain( `{"source": "${spelling}", "target": "/", "status": "301"}` );
    }
    expect(
      list,
      'desired_redirects() declares a /shop wildcard. In front of the restored index this 301s '
      + 'the catalogue and all seven product pages onto the home page.',
    ).not.toContain( '/shop/<*>' );
  } );

  it( 'c: is back in the page allowlist and the sitemap, and the product prefix still stays', () => {
    const appSource = read( 'src/pages/_app.tsx' );
    const metaStart = appSource.indexOf( 'const PUBLIC_PAGE_META' );
    expect( metaStart, 'PUBLIC_PAGE_META not found in _app.tsx' ).toBeGreaterThan( -1 );
    const metaEnd = appSource.indexOf( '\nconst ', metaStart + 10 );
    const metaBlock = appSource.slice( metaStart, metaEnd === -1 ? undefined : metaEnd );
    const metaRoutes = Array.from(
      metaBlock.matchAll( /^\s*'(\/[a-z0-9-]+(?:\/[a-z0-9-]+)*)'\s*:/gm ),
    ).map( match => match[ 1 ] );
    expect( metaRoutes.length, 'no routes parsed out of PUBLIC_PAGE_META' ).toBeGreaterThan( 10 );
    expect( metaRoutes ).toContain( '/shop' );

    const sitemapSource = read( 'scripts/generate-sitemap.js' );
    const exact = declaredTokens( sitemapSource, 'const PUBLIC_EXACT', '] )' );
    expect( exact.length, 'no routes parsed out of PUBLIC_EXACT' ).toBeGreaterThan( 10 );
    expect( exact ).toContain( '/shop' );

    // THE PREFIX STILL MATTERS: it is how the seven product URLs are advertised to a crawler
    // (the index links to them for a human, but the sitemap enumerates them through this prefix).
    // normalizeRoute( '/shop/file-assist/' ) yields '/shop/file-assist', which still
    // startsWith( '/shop/' ), and the restored EXACT '/shop' entry is a different token.
    const prefixes = declaredTokens( sitemapSource, 'const PUBLIC_PREFIXES', ']' );
    expect( prefixes ).toContain( '/shop/' );
  } );

  it( 'd: keeps /shop/[slug] in the isContentPublic chain', () => {
    /*
     * THE SHARPEST REGRESSION THIS PHASE COULD CAUSE, and it would not look like a failure.
     * Without this comparison a product page falls out of the public render chain and _app.tsx
     * renders the staff sign-in shell instead - at HTTP 200, with a 200 in the sitemap and a 200
     * in every uptime check. It is easy to delete by accident while withdrawing the '/shop' key
     * from PUBLIC_PAGE_META a few hundred lines above it.
     */
    expect(
      read( 'src/pages/_app.tsx' ),
      "router.pathname === '/shop/[slug]' is gone from _app.tsx. Without it a product page "
      + 'renders the staff sign-in shell at HTTP 200.',
    ).toContain( "router.pathname === '/shop/[slug]'" );
  } );
} );

describe( 'the product route follows the current catalogue (ITEM 2)', () => {
  it( 'e: generates exactly the current catalogue product paths', async () => {
    const { paths, fallback } = await getStaticPaths( {} ) as {
      paths: { params: { slug: string } }[]; fallback: boolean;
    };
    const slugs = paths.map( entry => entry.params.slug ).sort();
    const expected = catalogue.products
      .filter( product => product.visible !== false && !!product.slug && !!product.name )
      .map( product => String( product.slug ) )
      .filter( slug => shopProductBySlug( slug ) !== null )
      .sort();
    expect( slugs ).toEqual( expected );
    expect( fallback ).toBe( false );
  } );

  it( 'f: an empty snapshot creates no stale product routes', async () => {
    if ( catalogue.products.length !== 0 ) return;
    const { paths } = await getStaticPaths( {} ) as {
      paths: { params: { slug: string } }[]; fallback: boolean;
    };
    expect( paths ).toEqual( [] );
    expect( shopProductBySlug( 'file-assist' ) ).toBeNull();
    expect( shopProductBySlug( 'kiosk' ) ).toBeNull();
  } );
} );

describe( 'the snapshot and the tree still agree', () => {
  it( 'h: carries a top-level variantVerifiedAt and a real variant for every product', () => {
    /*
     * THE STANDING GATE ON THE SNAPSHOT WRITER (scripts/build-catalog-snapshot.py). An earlier
     * fetch script emitted variantCount and no variants array, so a refresh would have silently
     * dropped every variant - breaking the merchandise fit/size selector, the variantId the cart
     * sends, and nothing at build time. This asserts the SHAPE the site consumes, so a regression
     * in the writer is caught the next time the snapshot is regenerated rather than in production.
     */
    const snapshot = catalogue as unknown as {
      variantVerifiedAt?: string;
      products: { slug: string; variantCount: number; variants?: { id: string }[] }[];
    };
    expect( typeof snapshot.variantVerifiedAt ).toBe( 'string' );
    expect( snapshot.variantVerifiedAt!.length ).toBeGreaterThan( 0 );
    expect( snapshot.products.length ).toBe( catalogue.products.length );
    for ( const product of snapshot.products ) {
      if ( product.variantCount < 1 ) continue;
      expect( Array.isArray( product.variants ), `${product.slug} has no variants array` )
        .toBe( true );
      expect( product.variants!.length, `${product.slug} has an empty variants array` )
        .toBeGreaterThan( 0 );
      for ( const variant of product.variants! ) {
        expect( typeof variant.id, `${product.slug} has a variant with no id` ).toBe( 'string' );
        expect( variant.id.length, `${product.slug} has a variant with an empty id` )
          .toBeGreaterThan( 0 );
      }
    }
  } );

  it( 'i: the restored index page is a real exported Next page', () => {
    /*
     * RESTORED 2026-10-10. This block used to guard that nothing imported the deleted
     * src/pages/shop/index page; with the page back, the right assertion is that it is a genuine
     * Next page - a default-exported React component with a getStaticProps (output: 'export'
     * builds it from that pair) - so a future edit that empties or malforms it reddens here with a
     * named file rather than failing opaquely at build time.
     */
    const indexPath = path.join( ROOT, 'src/pages/shop/index.tsx' );
    expect( fs.existsSync( indexPath ), 'src/pages/shop/index.tsx is missing' ).toBe( true );
    const source = fs.readFileSync( indexPath, 'utf8' );
    expect( source, 'the index page has no default export' ).toMatch( /export default\s/ );
    expect( source, 'the index page has no getStaticProps, so output: export cannot build it' )
      .toContain( 'getStaticProps' );
  } );
} );
