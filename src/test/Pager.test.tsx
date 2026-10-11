import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import Pager, { pageWindow } from '../components/Pager';

/**
 * The extracted paginator.
 *
 * WHAT IS WORTH ASSERTING HERE. Most of this control is already pinned from the outside:
 * src/test/BlogDesign.test.tsx drives it through /blog/ and /blog/page/N/ at the DOM level, and
 * src/test/ShopListing.test.tsx does the same through /shop/. What those two cannot see is the
 * reason this file exists - the responsive block that MOVED with the markup.
 *
 * THE MEDIA BLOCK IS THE POINT. Three pager rules used to sit inside BlogIndexView's shared
 * @media(max-width:767px) block. Once nav.pager and ol.pager-list carry Pager's styled-jsx hash
 * instead of BlogIndexView's, a rule left behind there matches nothing and the mobile pager
 * silently loses its wrap-to-own-row layout and its full-width steps on BOTH listings. Nothing
 * else can catch that: jsdom cannot read a computed style, so the component's own style TEXT is
 * the only available source of truth, which is the same technique BlogDesign.test.tsx uses.
 */

const cssOf = ( container: HTMLElement ) =>
  Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

/** The declarations of the first @media(...max-width:767px...) block in a stylesheet. */
const narrowBlock = ( css: string ): string => {
  const at = css.indexOf( 'max-width:767px' );
  if ( at === -1 ) return '';
  const open = css.indexOf( '{', at );
  // The block nests one level (the :global rule inside it), so count braces rather than
  // stopping at the first '}'.
  let depth = 0;
  for ( let i = open; i < css.length; i++ ) {
    if ( css[ i ] === '{' ) depth++;
    if ( css[ i ] === '}' ) {
      depth--;
      if ( depth === 0 ) return css.slice( open, i + 1 );
    }
  }
  return '';
};

const hrefFor = ( page: number ) => ( page <= 1 ? '/shop/' : `/shop/page/${page}/` );

describe( 'pageWindow', () => {
  it( 'prints every number up to seven pages', () => {
    expect( pageWindow( 1, 1 ) ).toEqual( [ 1 ] );
    expect( pageWindow( 2, 3 ) ).toEqual( [ 1, 2, 3 ] );
    expect( pageWindow( 4, 7 ) ).toEqual( [ 1, 2, 3, 4, 5, 6, 7 ] );
  } );
  it( 'elides to first, last and a window beyond seven, with no page cap', () => {
    // null is an elision. The count is never capped - that is what "unlimited pagination"
    // means here: a longer run prints more gaps, not fewer pages.
    expect( pageWindow( 1, 20 ) ).toEqual( [ 1, 2, null, 20 ] );
    expect( pageWindow( 10, 20 ) ).toEqual( [ 1, null, 9, 10, 11, null, 20 ] );
    expect( pageWindow( 20, 20 ) ).toEqual( [ 1, null, 19, 20 ] );
    expect( pageWindow( 500, 999 ) ).toEqual( [ 1, null, 499, 500, 501, null, 999 ] );
  } );
} );

describe( 'Pager (Perspectives style)', () => {
  it( 'declares its own narrow-screen block, so a rule here has a home', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 5 } hrefFor={ hrefFor } ariaLabel="Shop pages" />,
    );
    const block = narrowBlock( cssOf( container ) );
    expect( block, 'Pager declares no max-width:767px block of its own' ).not.toBe( '' );
  } );

  it( 'is two circular arrows plus a lime progress bar, with NO page numbers', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 5 } hrefFor={ hrefFor } ariaLabel="Blog pages" />,
    );
    // The arrows, drawn chevrons on real links where a page exists.
    const arrows = Array.from( container.querySelectorAll( '.pager-arrow' ) );
    expect( arrows ).toHaveLength( 2 );
    // The lime progress bar.
    expect( container.querySelector( '.pager-progress-track[role="progressbar"]' ) ).not.toBeNull();
    expect( container.querySelector( '.pager-progress-fill' ) ).not.toBeNull();
    // No numbered page list, no current-page chip, no ellipsis - the whole numbered idiom is gone.
    expect( container.querySelector( '.pager-list' ) ).toBeNull();
    expect( container.querySelector( '.pager-num' ) ).toBeNull();
    expect( container.querySelector( '.pager-gap' ) ).toBeNull();
    expect( container.querySelector( '[aria-current="page"]' ) ).toBeNull();
    // Nothing in the nav prints a page number to a sighted reader. Exclude <style>, whose
    // styled-jsx CSS text carries digits in values that are not visible to a reader.
    const visible = Array.from( container.querySelectorAll( 'nav.pager *:not(style)' ) )
      .flatMap( n => Array.from( n.childNodes ) )
      .filter( n => n.nodeType === 3 )
      .map( n => n.textContent || '' )
      .join( ' ' );
    expect( visible ).not.toMatch( /\d/ );
  } );

  it( 'offers only the directions that exist, with real rel=prev/next links', () => {
    const { container } = render(
      <Pager page={ 1 } totalPages={ 3 } hrefFor={ hrefFor } ariaLabel="Shop pages" />,
    );
    // No prev link on page 1; an inert, aria-hidden arrow in its place so the row does not reflow.
    expect( container.querySelector( 'a[rel="prev"]' ) ).toBeNull();
    expect( container.querySelector( '.pager-arrow.is-off[aria-hidden="true"]' ) ).not.toBeNull();
    // A real next link to the adjacent page URL - the no-JS / crawlable path. next/link strips
    // the trailing slash in jsdom, so compare slash-insensitively.
    const next = container.querySelector( 'a[rel="next"]' );
    expect( next ).not.toBeNull();
    expect( String( next!.getAttribute( 'href' ) ).replace( /\/$/, '' ) ).toBe( '/shop/page/2' );
  } );

  it( 'carries position in the progressbar for assistive tech, not as printed text', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 4 } hrefFor={ hrefFor } ariaLabel="Blog pages" />,
    );
    const bar = container.querySelector( '.pager-progress-track' )!;
    expect( bar.getAttribute( 'aria-valuenow' ) ).toBe( '2' );
    expect( bar.getAttribute( 'aria-valuemax' ) ).toBe( '4' );
    expect( bar.getAttribute( 'aria-valuetext' ) ).toBe( 'Page 2 of 4' );
  } );

  it( 'names the arrows from the step labels, defaulting to the blog listing', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 3 } hrefFor={ hrefFor } ariaLabel="Blog pages" />,
    );
    expect( container.querySelector( 'a[rel="prev"]' )!.getAttribute( 'aria-label' ) ).toContain( 'Newer' );
    expect( container.querySelector( 'a[rel="next"]' )!.getAttribute( 'aria-label' ) ).toContain( 'Older' );
  } );
} );
