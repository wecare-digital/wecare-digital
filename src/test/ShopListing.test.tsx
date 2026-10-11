import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ShopIndex from '../pages/shop/index';
import ShopListingPage, { getStaticPaths } from '../pages/shop/page/[page]';
import ShopListingView from '../components/ShopListingView';
import { PRODUCTS } from '../content/products';
import { SHOP_PRODUCTS, catalogReadOn } from '../content/shop';
import {
  SHOP_LISTINGS, SHOP_LISTINGS_PER_PAGE, shopListingPageCount, shopListingPageHref,
} from '../content/shopProducts';

/**
 * /shop/ - the re-skinned catalogue listing, and the merged shelf behind it.
 *
 * WHAT IS WORTH ASSERTING HERE AND WHAT IS NOT. The layout is measured in the browser -
 * tools/browser/seocheck.js, sectioncheck.js, devicecheck.js and pageaudit.js all carry /shop/ -
 * and a jsdom test cannot read a computed style, which is the trap the mega-menu documents: 112
 * browser assertions passed while every row was unstyled. So this file asserts the things that
 * are TRUE OR FALSE rather than visual, and where a CSS property is the subject it reads the
 * component's own <style> TEXT, which is the technique src/test/BlogDesign.test.tsx established.
 *
 * NOTHING HERE PINS A COUNT. .github/workflows/catalogue-sync.yml re-reads Wix every six hours
 * and pushes src/content/wix-catalog.json straight to this branch, so a literal 15 would turn an
 * untouched branch red the moment the owner adds a product in Wix - and the only available fix
 * would be editing a number in a test, which teaches the next person to edit numbers in tests.
 * The slug SET is asserted as a property of PRODUCTS and SHOP_PRODUCTS instead.
 */

const ROOT = path.resolve( __dirname, '..', '..' );
const read = ( relative: string ): string => fs.readFileSync( path.join( ROOT, relative ), 'utf8' );

const cssOf = ( container: HTMLElement ) =>
  Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );
/** One component's style block, picked by a selector only it declares. */
const styleBlockWith = ( container: HTMLElement, marker: string ) =>
  Array.from( container.querySelectorAll( 'style' ) )
    .map( node => node.textContent || '' )
    .find( text => text.includes( marker ) ) || '';
/** CSS comments stripped, so a negative assertion cannot fail on its own documentation. */
const declarationsOnly = ( css: string ) => css.replace( /\/\*[\s\S]*?\*\//g, '' );

const totalPages = shopListingPageCount( SHOP_LISTINGS.length );
const propsFor = ( page: number ) => {
  const start = ( page - 1 ) * SHOP_LISTINGS_PER_PAGE;
  return {
    listings: SHOP_LISTINGS.slice( start, start + SHOP_LISTINGS_PER_PAGE ),
    allListings: SHOP_LISTINGS,
    page,
    totalPages,
  };
};

/** next/link strips the trailing slash the source passes, so compare paths slash-insensitively. */
const samePath = ( href: string | null ) => String( href ).replace( /\/$/, '' ) || '/';

describe( 'the merged shelf', () => {
  it( 'is exactly the union of the product pages and the visible catalogue rows', () => {
    /*
     * ASSERTED AS A PROPERTY, NOT AGAINST A NUMBER. The set is the union of the two halves, so a
     * product added in either place is in the listing by construction, and this assertion says so
     * rather than counting. The sighting as of the 2026-10-10 snapshot is 15 - 8 PRODUCTS plus 8
     * visible Wix rows minus the `anew` overlap - and that number belongs in this comment.
     */
    const expected = new Set( [
      ...PRODUCTS.map( product => product.slug ),
      ...SHOP_PRODUCTS.map( product => product.slug ),
    ] );
    expect( SHOP_LISTINGS.map( listing => listing.slug ).sort() ).toEqual( [ ...expected ].sort() );
    // The floor the content module enforces: PRODUCTS alone supplies 8, so only a deliberate
    // code deletion can cross it.
    expect( SHOP_LISTINGS.length ).toBeGreaterThanOrEqual( 8 );
  } );

  it( 'de-duplicates anew to the richer page and gives it no price of its own', () => {
    const anew = SHOP_LISTINGS.filter( listing => listing.slug === 'anew' );
    expect( anew, 'anew is in both halves and must be ONE card' ).toHaveLength( 1 );
    expect( anew[ 0 ].href ).toBe( '/anew/' );
    expect( anew[ 0 ].source ).toBe( 'product' );
    // A ProductDef card never prints a price, so the page cannot quote a number nobody quoted.
    expect( anew[ 0 ].formattedPrice ).toBeUndefined();
  } );

  it( 'keeps every slug route-safe and clear of the /shop/page/ route', () => {
    for ( const listing of SHOP_LISTINGS ) {
      expect( listing.slug, `${listing.slug} is not route-safe` ).toMatch( /^[a-z0-9]+(?:-[a-z0-9]+)*$/ );
      expect( listing.slug, 'a product slugged page would collide with /shop/page/N/' ).not.toBe( 'page' );
      expect( listing.name.trim().length ).toBeGreaterThan( 0 );
      expect( listing.blurb.trim().length ).toBeGreaterThan( 0 );
    }
  } );

  it( 'imports its copy verbatim and never rewrites it', () => {
    // Read off the two source modules rather than compared to literals, so an owner copy edit in
    // Wix or in products.ts cannot turn this red.
    for ( const product of PRODUCTS ) {
      const listing = SHOP_LISTINGS.find( entry => entry.slug === product.slug )!;
      expect( listing.name ).toBe( product.name );
      expect( listing.blurb ).toBe( product.blurb );
      expect( listing.href ).toBe( `/${product.slug}/` );
      expect( listing.formattedPrice ).toBeUndefined();
    }
    for ( const product of SHOP_PRODUCTS ) {
      const listing = SHOP_LISTINGS.find( entry => entry.slug === product.slug )!;
      if ( listing.source === 'product' ) continue; // the anew overlap
      expect( listing.name ).toBe( product.name );
      expect( listing.blurb ).toBe( product.tagline );
      expect( listing.href ).toBe( `/shop/${product.slug}/` );
      // Wix's own formatted string, passed through, never rebuilt.
      expect( listing.formattedPrice ).toBe( product.formattedPrice );
    }
  } );

  it( 'points every card at a page file that exists', () => {
    for ( const listing of SHOP_LISTINGS ) {
      const file = listing.source === 'product'
        ? `src/pages/${listing.slug}.tsx`
        : 'src/pages/shop/[slug].tsx';
      expect(
        fs.existsSync( path.join( ROOT, file ) ),
        `${listing.slug} links to ${listing.href}, which has no page file at ${file}`,
      ).toBe( true );
    }
  } );

  it( 'sends page 1 to /shop/ rather than to /shop/page/1/', () => {
    expect( shopListingPageHref( 1 ) ).toBe( '/shop/' );
    expect( shopListingPageHref( 3 ) ).toBe( '/shop/page/3/' );
    // getStaticPaths therefore starts at 2, or the same six cards would exist at two URLs.
    return ( getStaticPaths( {} ) as unknown as Promise<{ paths: { params: { page: string } }[] }> )
      .then( ( { paths } ) => {
        const pages = paths.map( entry => Number( entry.params.page ) );
        expect( pages ).not.toContain( 1 );
        expect( pages ).toEqual(
          Array.from( { length: totalPages - 1 }, ( _, i ) => i + 2 ),
        );
      } );
  } );
} );

describe( 'the listing page', () => {
  it( 'owns a single main and a single h1 through the shared hero', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelector( 'h1' )!.textContent ).toContain( 'A shop for' );
    const words = Array.from( container.querySelectorAll( '.rh-cyc-word' ) ).map( w => w.textContent );
    expect( words ).toEqual( [ 'services', 'documents', 'products', 'journeys' ] );
    // The pill animates to each word's measured width, so keep the set close in length.
    for ( const word of words ) expect( ( word || '' ).length ).toBeLessThanOrEqual( 18 );
  } );

  it( 'mounts the blog search box, named for the shop', () => {
    render( <ShopIndex { ...propsFor( 1 ) } /> );
    // The accessible name is the visually hidden label, which is what a screen reader
    // announces and what BlogDesign.test.tsx resolves the blog's own field by.
    const field = screen.getByLabelText( 'Search the shop' );
    expect( field ).toHaveAttribute( 'type', 'search' );
    expect( field ).toHaveAttribute( 'name', 'q' );
    expect( field ).toHaveAttribute( 'placeholder', 'Search products' );
    // A real GET form, so the no-JavaScript path navigates to /shop/?q=...
    expect( field.closest( 'form' ) ).toHaveAttribute( 'action', '/shop/' );
    expect( field.closest( 'form' ) ).toHaveAttribute( 'method', 'get' );
    // And /blog/'s own id is not duplicated onto this page.
    expect( field ).toHaveAttribute( 'id', 'shop-q' );
  } );

  it( 'renders one card per listing in the slice, each linking to its own detail page', () => {
    const props = propsFor( 1 );
    const { container } = render( <ShopIndex { ...props } /> );
    const cards = Array.from( container.querySelectorAll( 'a.shop-card' ) );
    expect( cards ).toHaveLength( props.listings.length );
    cards.forEach( ( card, i ) => {
      expect( samePath( card.getAttribute( 'href' ) ) )
        .toBe( samePath( props.listings[ i ].href ) );
      expect( card.textContent ).toContain( props.listings[ i ].name );
      expect( card.textContent ).toContain( props.listings[ i ].blurb );
    } );
  } );

  it( 'reaches every product across its pages, and only through real links', () => {
    const seen: string[] = [];
    for ( let page = 1; page <= totalPages; page++ ) {
      const props = propsFor( page );
      const { container } = render(
        page === 1 ? <ShopIndex { ...props } /> : <ShopListingPage { ...props } />,
      );
      for ( const card of Array.from( container.querySelectorAll( 'a.shop-card' ) ) ) {
        seen.push( samePath( card.getAttribute( 'href' ) ) );
      }
    }
    expect( seen.sort() ).toEqual( SHOP_LISTINGS.map( l => samePath( l.href ) ).sort() );
  } );

  it( 'lays the cards out one per row', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    const block = declarationsOnly( styleBlockWith( container, '.shop-grid' ) );
    expect( block ).toContain( 'grid-template-columns:1fr' );
    // One column has nothing to reflow, so there is no auto-fill and no multi-column step.
    expect( block ).not.toContain( 'repeat(' );
  } );

  it( 'rotates three hues on the card spine, through :global(), and excludes amber', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    const block = declarationsOnly( styleBlockWith( container, '.shop-card' ) );
    expect( block ).toContain( 'border-inline-start:3px solid #3da35a' );
    expect( block ).toContain( ':global(.shop-card:nth-child(3n+2))' );
    expect( block ).toContain( ':global(.shop-card:nth-child(3n+3))' );
    expect( block ).toContain( 'border-inline-start-color:#2563eb' );
    expect( block ).toContain( 'border-inline-start-color:#9849e8' );
    /*
     * EVERY .shop-card RULE GOES THROUGH :global(), and this is the assertion that catches the
     * form that compiles to nothing. .shop-card is on a capitalised <Link>, so styled-jsx never
     * hashes it and a BARE .shop-card selector matches nothing - the cards would render as plain
     * blue underlined links while a text search for the three spine declarations still passed.
     * So the check is on the selector shape: no rule in this block may START with .shop-card.
     */
    for ( const rule of block.split( '}' ) ) {
      const brace = rule.indexOf( '{' );
      if ( brace === -1 ) continue;
      const selector = rule.slice( 0, brace ).trim();
      if ( !selector || selector.startsWith( '@' ) ) continue;
      for ( const part of selector.split( ',' ) ) {
        expect(
          part.trim().startsWith( '.shop-card' ),
          `${part.trim()} is a bare .shop-card selector, which matches nothing because the class is on a <Link>`,
        ).toBe( false );
      }
    }
    // Amber was measured at 2.04:1 on a 3px stroke and rejected; the spine set is three hues.
    expect( block ).not.toContain( '#f0a818' );
    expect( block ).not.toContain( '#fef3c7' );
  } );

  it( 'renders the paginator on page 1 and marks the page it is on', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    expect( container.querySelector( 'nav[aria-label="Shop pages"]' ) ).not.toBeNull();
    expect( container.querySelector( '.pager [aria-current="page"]' )!.textContent ).toBe( '1' );
    expect( samePath( container.querySelector( 'a[rel="next"]' )!.getAttribute( 'href' ) ) )
      .toBe( '/shop/page/2' );
  } );

  it( 'labels the steps Previous and Next, not the blog listing Newer and Older', () => {
    // The shelf is in declaration order and then name order, so "Older" would be a claim about
    // a sort nobody performed.
    const { container } = render( <ShopListingPage { ...propsFor( 2 ) } /> );
    const prev = container.querySelector( 'a[rel="prev"]' )!;
    expect( prev.textContent ).toContain( 'Previous' );
    expect( samePath( prev.getAttribute( 'href' ) ) ).toBe( '/shop' );
    const next = container.querySelector( '.pager-step.is-next' )!;
    expect( next.textContent ).toContain( 'Next' );
  } );

  it( 'renders Home / Shop on page 1 and Home / Shop / Page N beyond it', () => {
    const { container: first } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    const firstCrumbs = Array.from( first.querySelectorAll( 'nav[aria-label="Breadcrumb"] li' ) )
      .map( node => node.textContent );
    expect( firstCrumbs ).toEqual( [ 'Home', 'Shop' ] );

    const { container: second } = render( <ShopListingPage { ...propsFor( 2 ) } /> );
    const secondCrumbs = Array.from( second.querySelectorAll( 'nav[aria-label="Breadcrumb"] li' ) )
      .map( node => node.textContent );
    expect( secondCrumbs ).toEqual( [ 'Home', 'Shop', 'Page 2' ] );
    // The Shop crumb is a link back to the listing's first page, not to this one.
    const shopCrumb = Array.from( second.querySelectorAll( 'nav[aria-label="Breadcrumb"] a' ) )
      .find( node => node.textContent === 'Shop' )!;
    expect( samePath( shopCrumb.getAttribute( 'href' ) ) ).toBe( '/shop' );
  } );

  it( 'states when the catalogue was read, and nothing else on that line', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    const asof = container.querySelector( '.shop-asof' )!;
    expect( asof.textContent ).toBe( `Catalogue read on ${catalogReadOn()}` );
    // On every page, because the Wix half is on every page.
    const { container: second } = render( <ShopListingPage { ...propsFor( 2 ) } /> );
    expect( second.querySelector( '.shop-asof' )!.textContent )
      .toBe( `Catalogue read on ${catalogReadOn()}` );
  } );
} );

describe( 'searching the shelf', () => {
  it( 'narrows on a name and on a blurb, and will not match across the boundary', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    const field = screen.getByLabelText( 'Search the shop' );

    fireEvent.change( field, { target: { value: 'kiosk' } } );
    const byName = Array.from( container.querySelectorAll( 'a.shop-card' ) );
    expect( byName.length ).toBeGreaterThan( 0 );
    for ( const card of byName ) {
      expect( `${card.textContent}`.toLowerCase() ).toContain( 'kiosk' );
    }

    // A blurb word that is in no product NAME, so this can only pass through the blurb.
    fireEvent.change( field, { target: { value: 'visas' } } );
    const byBlurb = Array.from( container.querySelectorAll( 'a.shop-card' ) );
    expect( byBlurb.map( card => card.getAttribute( 'href' ) ).map( samePath ) )
      .toContain( '/elsewhere' );

    /*
     * THE NEWLINE JOIN, ASSERTED. The fields are joined with '\n' rather than a space, so a query
     * made of the end of the name and the start of the blurb cannot match. With a space join,
     * "Elsewhere" + "Travel, visas..." gives "elsewhere travel", which no product says.
     */
    fireEvent.change( field, { target: { value: 'elsewhere travel' } } );
    expect( container.querySelectorAll( 'a.shop-card' ) ).toHaveLength( 0 );
    expect( container.querySelector( '.shop-empty' )!.textContent )
      .toBe( 'No products match that search.' );
  } );

  it( 'hides the paginator while a query is active and lists every match', () => {
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    expect( container.querySelector( 'nav[aria-label="Shop pages"]' ) ).not.toBeNull();
    // A single letter that is in every entry's name or blurb somewhere, so the match set is
    // larger than one page.
    fireEvent.change( screen.getByLabelText( 'Search the shop' ), { target: { value: 'a' } } );
    expect( container.querySelector( 'nav[aria-label="Shop pages"]' ) ).toBeNull();
    const matching = SHOP_LISTINGS.filter( listing => (
      [ listing.name, listing.blurb ].join( '\n' ).toLowerCase().includes( 'a' )
    ) );
    expect( matching.length ).toBeGreaterThan( SHOP_LISTINGS_PER_PAGE );
    expect( container.querySelectorAll( 'a.shop-card' ) ).toHaveLength( matching.length );

    // Clearing restores the slice and the paginator.
    fireEvent.change( screen.getByLabelText( 'Search the shop' ), { target: { value: '' } } );
    expect( container.querySelectorAll( 'a.shop-card' ) ).toHaveLength( SHOP_LISTINGS_PER_PAGE );
    expect( container.querySelector( 'nav[aria-label="Shop pages"]' ) ).not.toBeNull();
  } );

  it( 'reads ?q= on the first paint, and truncates an over-long value instead of throwing', () => {
    const original = window.location.search;
    const set = ( search: string ) => {
      Object.defineProperty( window, 'location', {
        configurable: true,
        value: { ...window.location, search },
      } );
    };

    set( '?q=kiosk' );
    const { container } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    // Already filtered, not six cards and then a narrowing.
    const cards = Array.from( container.querySelectorAll( 'a.shop-card' ) );
    expect( cards.length ).toBeGreaterThan( 0 );
    for ( const card of cards ) expect( `${card.textContent}`.toLowerCase() ).toContain( 'kiosk' );

    set( `?q=${'x'.repeat( 500 )}` );
    const { container: long } = render( <ShopIndex { ...propsFor( 1 ) } /> );
    expect( ( long.querySelector( '#shop-q' ) as HTMLInputElement ).value ).toHaveLength( 100 );
    expect( long.querySelector( '.shop-empty' ) ).not.toBeNull();

    set( original );
  } );
} );

describe( 'the house rules this listing has to hold', () => {
  it( 'mounts no Header and no Footer of its own', () => {
    // _app.tsx mounts the chrome for every public route, and
    // src/test/PublicRouteRegistration.test.ts fails any public page that mounts it per page.
    for ( const file of [ 'src/pages/shop/index.tsx', 'src/pages/shop/page/[page].tsx' ] ) {
      const source = read( file );
      expect( source, `${file} imports Header` ).not.toContain( 'components/Header' );
      expect( source, `${file} imports Footer` ).not.toContain( 'components/Footer' );
    }
  } );

  it( 'keeps the index page a real exported Next page', () => {
    const source = read( 'src/pages/shop/index.tsx' );
    expect( source ).toMatch( /export default\s/ );
    expect( source ).toContain( 'getStaticProps' );
  } );

  it( 'writes its new copy to the house rules: no exclamation mark, no em or en dash', () => {
    /*
     * SCOPED TO THE STRINGS THIS CHANGE AUTHORS. The product copy it renders is imported verbatim
     * from src/content/products.ts and the Wix snapshot, and several of those lines legitimately
     * carry an em dash and a rupee sign - rewriting imported copy to satisfy a tone sweep is the
     * opposite of the rule. So this reads the three new source files instead.
     */
    for ( const file of [
      'src/components/ShopListingView.tsx',
      'src/components/ShopListingHead.tsx',
      'src/content/shopProducts.ts',
    ] ) {
      const strings = Array.from( read( file ).matchAll( /'([^'\n]*)'|"([^"\n]*)"/g ) )
        .map( match => match[ 1 ] ?? match[ 2 ] ?? '' );
      for ( const value of strings ) {
        expect( value, `${file}: ${value}` ).not.toContain( '!' );
        expect( value, `${file}: ${value}` ).not.toContain( '\u2014' );
        expect( value, `${file}: ${value}` ).not.toContain( '\u2013' );
        expect( value, `${file}: ${value}` ).not.toContain( '\u20b9' );
      }
    }
  } );

  it( 'keeps /shop/page/[page] in the isContentPublic chain', () => {
    // Without it every page but the first renders an empty body at HTTP 200 - a 404 that does
    // not look like one, with a 200 in the sitemap and a 200 in every uptime check.
    expect(
      read( 'src/pages/_app.tsx' ),
      "router.pathname === '/shop/page/[page]' is gone from _app.tsx.",
    ).toContain( "router.pathname === '/shop/page/[page]'" );
  } );

  it( 'reuses the hero rotation rather than introducing a colour', () => {
    const { container } = render( <ShopListingView { ...propsFor( 1 ) } /> );
    const css = declarationsOnly( cssOf( container ) );
    // Red is retired from these surfaces, and PublicPageTopBand.test.tsx enforces its absence
    // on the neighbouring shop files.
    expect( css ).not.toContain( '#dc2626' );
    expect( css ).not.toContain( '#fee2e2' );
  } );
} );
