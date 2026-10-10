import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ShopProductPage, { getStaticPaths } from '../pages/shop/[slug]';
import { shopProductSchema } from '../components/ShopProductHead';
import { readCart, toLineItems } from '../lib/cart';
import { shopProductBySlug } from '../content/shop';
import type { ShopProduct } from '../content/shop';
import catalogue from '../content/wix-catalog.json';

/**
 * THE TWO HALVES OF THE 2026-10-04 OWNER INSTRUCTION, PINNED TOGETHER IN ONE FILE.
 *
 * The instruction has two clauses that pull in opposite directions:
 *
 *   ITEM 1  /shop/ stops being browsable and goes to the home page.
 *   ITEM 2  every /shop/<slug>/ product page keeps rendering and keeps adding to cart.
 *
 * Either one is easy alone. The cheapest way to satisfy ITEM 1 is a single `/shop/<*>` Amplify
 * redirect, and that silently destroys ITEM 2 by 301ing all seven product pages onto the home
 * page. The cheapest way to protect ITEM 2 is to change nothing, which ignores ITEM 1. So they are
 * asserted in the same file, and a change that trades one for the other reddens here.
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

describe( 'the withdrawn catalogue index (ITEM 1)', () => {
  it( 'a: has no listing page left in the export', () => {
    // The hosting redirect and the deletion are two layers and both ship. The redirect is what
    // makes /shop/ stop being browsable; deleting the page is what makes that true even if a
    // rule is lost, and it is what removes out/shop/index.html from the artifact.
    expect( fs.existsSync( path.join( ROOT, 'src/pages/shop/index.tsx' ) ) ).toBe( false );
  } );

  it( 'b: declares all three index spellings as EXACT 301s, and no /shop wildcard', () => {
    /*
     * THIS ASSERTS A DECLARATION, NOT LIVE BEHAVIOUR. A vitest file cannot reach Amplify, so what
     * is checked here is that scripts/provision_legacy_redirects.py SAYS the right thing. The live
     * proof is the four /shop rows in scripts/probe_url_host_matrix.py, which follow the real
     * redirect chain against the deployed site; tests/test_url_host_routing_rules.py proves the
     * same declaration from the Python side, against what apply() actually writes.
     *
     * The wildcard's ABSENCE is the assertion that matters most in this file. /shop/<*> would
     * satisfy ITEM 1 in one line and 301 every product page onto home.
     */
    const provisioner = read( 'scripts/provision_legacy_redirects.py' );
    const signature = provisioner.indexOf( 'def desired_redirects' );
    expect( signature, 'desired_redirects() not found' ).toBeGreaterThan( -1 );

    /*
     * SLICED TO THE `return [ ... ]` LIST, NOT TO THE WHOLE FUNCTION BODY. This is the same
     * slice-the-declaration discipline the module docstring describes, and it bit immediately:
     * desired_redirects()'s own docstring EXPLAINS why /shop/<*> is forbidden, so it necessarily
     * contains that string. Slicing the body would make the negative assertion below fail against
     * a completely correct provisioner, and the obvious "fix" would be to delete the explanation.
     */
    const start = provisioner.indexOf( 'return [', signature );
    expect( start, 'desired_redirects() has no return list' ).toBeGreaterThan( -1 );
    const list = provisioner.slice( start, provisioner.indexOf( '\n    ]', start ) );

    for ( const spelling of [ '/shop', '/shop/', '/shop/index.html' ] ) {
      expect(
        list,
        `${spelling} is not declared as a 301 to the home page in desired_redirects()`,
      ).toContain( `{"source": "${spelling}", "target": "/", "status": "301"}` );
    }
    expect(
      list,
      'desired_redirects() declares a /shop wildcard. An Amplify wildcard source matches any '
      + 'suffix, so this 301s all seven product pages onto the home page.',
    ).not.toContain( '/shop/<*>' );
  } );

  it( 'c: is withdrawn from the page allowlist and the sitemap, while the product prefix stays', () => {
    const appSource = read( 'src/pages/_app.tsx' );
    const metaStart = appSource.indexOf( 'const PUBLIC_PAGE_META' );
    expect( metaStart, 'PUBLIC_PAGE_META not found in _app.tsx' ).toBeGreaterThan( -1 );
    const metaEnd = appSource.indexOf( '\nconst ', metaStart + 10 );
    const metaBlock = appSource.slice( metaStart, metaEnd === -1 ? undefined : metaEnd );
    const metaRoutes = Array.from(
      metaBlock.matchAll( /^\s*'(\/[a-z0-9-]+)'\s*:/gm ),
    ).map( match => match[ 1 ] );
    expect( metaRoutes.length, 'no routes parsed out of PUBLIC_PAGE_META' ).toBeGreaterThan( 10 );
    expect( metaRoutes ).not.toContain( '/shop' );

    const sitemapSource = read( 'scripts/generate-sitemap.js' );
    const exact = declaredTokens( sitemapSource, 'const PUBLIC_EXACT', '] )' );
    expect( exact.length, 'no routes parsed out of PUBLIC_EXACT' ).toBeGreaterThan( 10 );
    expect( exact ).not.toContain( '/shop' );

    // THE PREFIX MUST SURVIVE, and it is the other half of the same decision. It is now the only
    // way the seven product URLs are advertised, because there is no listing page linking to them.
    // normalizeRoute( '/shop/file-assist/' ) yields '/shop/file-assist', which still
    // startsWith( '/shop/' ) - so dropping the EXACT entry cannot affect it.
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

describe( 'the product pages are untouched by it (ITEM 2)', () => {
  it( 'e: still generates a path for all seven slugs, and never depended on the index', () => {
    // Path generation reads SHOP_PRODUCTS, which reads the snapshot. The index page was only ever
    // a consumer of the same list, so deleting it cannot change what gets built.
    const result = getStaticPaths( {} ) as unknown as Promise<{
      paths: { params: { slug: string } }[]; fallback: boolean;
    }>;
    return result.then( ( { paths, fallback } ) => {
      const slugs = paths.map( entry => entry.params.slug );
      // The catalogue auto-syncs from Wix, so the count is not frozen: assert every known product
      // slug has a statically-generated path, not an exact length that would break whenever a
      // product is added or removed in Wix.
      for ( const slug of [
        'file-assist', 'guided-resolution', 'kiosk', 'merchandise', 'paperwork',
        'referral-partner', 'anew',
      ] ) {
        expect( slugs, `${ slug } has no static path` ).toContain( slug );
      }
      expect( slugs.length ).toBeGreaterThanOrEqual( 7 );
      // fallback: false because next.config.js sets output: 'export' - there is no server to
      // render a missing slug on demand.
      expect( fallback ).toBe( false );
    } );
  } );

  it( 'f1: renders file-assist and adds exactly one correct line to the cart', () => {
    window.localStorage.clear();
    const product = shopProductBySlug( 'file-assist' ) as ShopProduct;
    expect( product, 'file-assist is not in the catalogue snapshot' ).toBeTruthy();

    const { container } = render( React.createElement( ShopProductPage, { product } ) );
    const headings = container.querySelectorAll( 'h1' );
    expect( headings ).toHaveLength( 1 );
    expect( headings[ 0 ].textContent ).toBe( product.name );

    // file-assist reports variantCount 1, so the variant gate cannot disable the button. The
    // merchandise case - 10 variants, button disabled until one is chosen - is covered in
    // src/test/ShopCatalogue.test.tsx.
    const button = screen.getByRole( 'button', { name: `Add ${product.name} to cart` } );
    expect( button ).toBeEnabled();
    fireEvent.click( button );

    const cart = readCart();
    expect( cart ).toHaveLength( 1 );
    const snapshotProduct = catalogue.products.find( entry => entry.slug === 'file-assist' );
    expect( snapshotProduct, 'file-assist is missing from the snapshot' ).toBeTruthy();
    expect( cart[ 0 ].productId ).toBe( snapshotProduct!.id );
    expect( toLineItems()[ 0 ].catalogReference.catalogItemId ).toBe( snapshotProduct!.id );
    window.localStorage.clear();
  } );

  it( 'f2: sends no price to the server, asserted at the checkout boundary', () => {
    /*
     * ASSERTED AT toLineItems(), NOT AT readCart(), and the distinction is the whole point.
     * A CART ITEM DELIBERATELY CARRIES formattedPrice - src/lib/cart.ts declares it and writes it,
     * because the cart list has to print a price. Asserting its absence there would be a test that
     * can never pass. toLineItems() is the price-free boundary: it projects each item down to
     * { catalogReference, quantity }, so the server is told WHAT was bought and decides the amount
     * itself. That is what stops a tampered browser dictating a total.
     */
    window.localStorage.clear();
    const product = shopProductBySlug( 'file-assist' ) as ShopProduct;
    render( React.createElement( ShopProductPage, { product } ) );
    fireEvent.click( screen.getByRole( 'button', { name: `Add ${product.name} to cart` } ) );

    expect( toLineItems() ).toHaveLength( 1 );
    expect( JSON.stringify( toLineItems() ) ).not.toMatch( /price|amount|formattedPrice/i );
    window.localStorage.clear();
  } );

  it( 'g: names the withdrawn index nowhere a visitor or a crawler can follow it', () => {
    // Both surfaces, because they fail differently. A rendered href that 301s is a visible
    // round trip; a BreadcrumbList item pointing at a redirect makes the rich result disappear
    // with no error at all.
    const product = shopProductBySlug( 'kiosk' ) as ShopProduct;
    const { container } = render( React.createElement( ShopProductPage, { product } ) );
    const hrefs = Array.from( container.querySelectorAll( 'a' ) )
      .map( anchor => anchor.getAttribute( 'href' ) );
    expect( hrefs ).not.toContain( '/shop/' );
    expect( hrefs ).not.toContain( '/shop' );

    const graph = JSON.stringify( shopProductSchema( product ) );
    expect(
      graph,
      'the BreadcrumbList still names the withdrawn /shop/ index',
    ).not.toContain( 'wecare.digital/shop/"' );
    expect( graph ).not.toContain( '"name":"Shop"' );
  } );
} );

describe( 'the snapshot and the tree still agree', () => {
  it( 'h: carries a top-level variantVerifiedAt and a real variant for every product', () => {
    /*
     * THE STANDING GATE ON scripts/fetch-wix-catalog.js. That script emitted variantCount and no
     * variants array, so a refresh would have silently dropped every variant - breaking the
     * merchandise fit/size selector, the variantId the cart sends, and nothing at build time.
     * This asserts the SHAPE the site consumes, so a regression in the fetch script is caught the
     * next time the snapshot is regenerated rather than in production.
     */
    const snapshot = catalogue as unknown as {
      variantVerifiedAt?: string;
      products: { slug: string; variantCount: number; variants?: { id: string }[] }[];
    };
    expect( typeof snapshot.variantVerifiedAt ).toBe( 'string' );
    expect( snapshot.variantVerifiedAt!.length ).toBeGreaterThan( 0 );
    expect( snapshot.products.length ).toBeGreaterThan( 0 );
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

  it( 'i: has no module anywhere still importing the deleted listing page', () => {
    /*
     * THE CROSS-PHASE GUARD. src/test/ShopCatalogue.test.tsx is also edited by another workstream,
     * and its copy carries `import ShopIndex from '../pages/shop/index'`. If that copy lands with
     * the import intact, this goes red BEFORE tsc is consulted and it goes red NAMING THE FILE,
     * which is a far faster read than a module-resolution error from the type checker.
     */
    const walk = ( dir: string ): string[] => fs.readdirSync( dir, { withFileTypes: true } )
      .flatMap( entry => {
        const full = path.join( dir, entry.name );
        if ( entry.isDirectory() ) return walk( full );
        return /\.tsx?$/.test( entry.name ) ? [ full ] : [];
      } );

    const sources = walk( path.join( ROOT, 'src' ) );
    expect( sources.length, 'no sources were walked, so this assertion proves nothing' )
      .toBeGreaterThan( 50 );
    /*
     * ANCHORED TO AN `import` STATEMENT AT THE START OF A LINE, not to a mention of the path
     * anywhere in the file. This file's own comment above quotes the offending import line, so an
     * unanchored match reported THIS FILE as an importer - a guard that always fails is a guard
     * that gets deleted. The anchored form asserts the real thing: a module that actually imports
     * the deleted page.
     */
    const importers = sources
      .filter( file => /^\s*import\s[^;\n]*from\s'[^']*pages\/shop\/index'/m
        .test( fs.readFileSync( file, 'utf8' ) ) )
      .map( file => path.relative( ROOT, file ) );
    expect(
      importers,
      'these modules import src/pages/shop/index, which was deleted on 2026-10-04 when the '
      + 'owner withdrew the catalogue index',
    ).toEqual( [] );
  } );
} );
