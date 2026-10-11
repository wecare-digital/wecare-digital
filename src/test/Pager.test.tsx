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

describe( 'Pager', () => {
  it( 'keeps the three responsive rules that moved out of BlogIndexView', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 5 } hrefFor={ hrefFor } ariaLabel="Shop pages" />,
    );
    const block = narrowBlock( cssOf( container ) );
    expect( block, 'Pager declares no max-width:767px block of its own' ).not.toBe( '' );
    // The numbers wrap to their own row under the prev/next pair.
    expect( block ).toContain( 'order:3' );
    // The steps go full width once the numbers are on their own row.
    expect( block ).toContain( 'flex:1' );
    // Still through :global(), because .pager-step is on a next/link.
    expect( block ).toContain( ':global(.pager-step)' );
  } );

  it( 'marks the current page and offers only the directions that exist', () => {
    const { container } = render(
      <Pager page={ 1 } totalPages={ 3 } hrefFor={ hrefFor } ariaLabel="Shop pages" />,
    );
    expect( container.querySelector( 'a[rel="prev"]' ) ).toBeNull();
    // Rendered rather than omitted so the row does not reflow, and hidden from the
    // accessibility tree because it is a dead control.
    expect( container.querySelector( '.pager-step.is-off[aria-hidden="true"]' ) ).not.toBeNull();
    expect( container.querySelector( 'a[rel="next"]' ) ).not.toBeNull();
    expect( container.querySelector( '.pager [aria-current="page"]' )!.textContent ).toBe( '1' );
  } );

  it( 'renders a real ellipsis character for an elision', () => {
    const { container } = render(
      <Pager page={ 10 } totalPages={ 20 } hrefFor={ hrefFor } ariaLabel="Shop pages" />,
    );
    const gaps = Array.from( container.querySelectorAll( '.pager-gap' ) );
    expect( gaps.length ).toBe( 2 );
    // A real character, not a styled empty element: a screen reader needs something
    // between "1" and "9" or the jump is silent.
    for ( const gap of gaps ) expect( gap.textContent ).toBe( '…' );
  } );

  it( 'defaults its step labels to the blog listing, so that call site passes none', () => {
    const { container } = render(
      <Pager page={ 2 } totalPages={ 3 } hrefFor={ hrefFor } ariaLabel="Blog pages" />,
    );
    expect( container.querySelector( 'a[rel="prev"]' )!.textContent ).toContain( 'Newer' );
    expect( container.querySelector( 'a[rel="next"]' )!.textContent ).toContain( 'Older' );
  } );
} );
