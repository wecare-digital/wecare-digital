import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

import { renderToStaticMarkup } from 'react-dom/server';

import HeaderCart from '../components/HeaderCart';
import Header from '../components/Header';
import * as cart from '../lib/cart';
import type { ShopProduct } from '../content/shop';

/**
 * THE SHOPPING BAG IN THE HEADER, and specifically the two things about it that are true or false
 * rather than visual.
 *
 * jsdom cannot read a computed style, so the chip's geometry, the 44px tap target and the glyph's
 * colour are measured in a real browser - tools/browser/devicecheck.js carries all four
 * transactional routes now and asserts every header control clears 44px at fifteen postures,
 * including 280px where the header has the least room. What jsdom CAN decide is the count logic and
 * the accessible name, and the count logic has a trap that only a test will catch.
 *
 * THE TRAP IS HYDRATION. The cart is in localStorage and these pages are statically exported, so the
 * server render has no cart. If the component rendered a count during the first client render it
 * would have to render 0 - which is a different tree from the server's only if the server somehow
 * knew better, and either way it is a guess shown to a shopper who has three items. So `null` means
 * "not read yet", is distinct from 0, and shows no badge at all; the number appears only after the
 * effect has run. These tests pin that: the FIRST render carries no digits even when storage is
 * already populated.
 */

const PRODUCT: ShopProduct = {
  id: 'prod-abc-123',
  name: 'Kiosk',
  slug: 'kiosk',
  formattedPrice: '₹24,999.00',
  price: '24999.00',
  currency: 'INR',
  inStock: true,
  tagline: 'Put your location to work.',
  body: [ 'You already have the place.' ],
};

const OTHER: ShopProduct = { ...PRODUCT, id: 'prod-def-456', name: 'Merchandise', slug: 'merchandise' };

// Header reads router.pathname to mark the current row. Mocked the same way Header.test.tsx does it.
const routerState = vi.hoisted( () => ( { pathname: '/' } ) );
vi.mock( 'next/router', () => ( { useRouter: () => routerState } ) );

/** The link, found the way a visitor's screen reader finds it: by role and accessible name. */
const bag = (): HTMLElement => screen.getByRole( 'link', { name: /Shopping Bag/ } );

/** The digits drawn inside the glyph, or '' when the badge is absent. */
const digits = ( container: HTMLElement ): string =>
  container.querySelector( '.hdr-cart-n' )?.textContent || '';

beforeEach( () => {
  window.localStorage.clear();
} );

afterEach( () => {
  vi.restoreAllMocks();
} );

describe( 'the count is read after mount, never during the server render', () => {
  it( 'renders no digits in the server markup even when storage is already full', () => {
    cart.addItem( PRODUCT, 3 );
    /*
     * ASSERTED AGAINST THE SERVER RENDERER, WHICH IS THE ONLY PLACE THE DEFECT LIVES.
     * renderToStaticMarkup runs no effects, so this is exactly the HTML the static export writes -
     * and it is the HTML the client has to agree with on its first pass or React reports a
     * hydration mismatch. A component that read the cart in its render body would emit "3" here
     * and "3" on the client, which looks fine in a test and is wrong in production: the export is
     * built once, on a machine with no cart, so the committed HTML would say 0 for everybody.
     *
     * A client render cannot show this. testing-library wraps render() in act(), which flushes
     * effects before it returns, so the pre-effect tree is not observable from there.
     */
    // The <style> block has to come out first: styled-jsx inlines the stylesheet into the markup,
    // and that stylesheet names .hdr-cart-n whether or not the element exists.
    const markup = renderToStaticMarkup( <HeaderCart /> )
      .replace( /<style[\s\S]*?<\/style>/g, '' );
    expect( markup ).not.toContain( 'hdr-cart-n' );
    // The bag itself IS in the server markup - it is the badge that waits, not the control.
    expect( markup ).toContain( 'Shopping Bag' );
  } );

  it( 'shows the single-unit line count once the effect has run', async () => {
    cart.addItem( PRODUCT, 3 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
  } );
} );

describe( 'zero, one and many', () => {
  it( 'shows no badge for an empty cart, and says so in the accessible name', async () => {
    const { container } = render( <HeaderCart /> );
    // 'empty' rather than '0': the name is read aloud, and "Shopping Bag 0" is not a sentence.
    await waitFor( () => expect( bag() ).toHaveAccessibleName( /empty/ ) );
    // No digit is drawn in the bag at all - a zero in the glyph reads as a badge worth looking at.
    expect( digits( container ) ).toBe( '' );
  } );

  it( 'uses the singular for one item', async () => {
    cart.addItem( PRODUCT, 1 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
    expect( bag() ).toHaveAccessibleName( /1 item$/ );
  } );

  it( 'counts distinct single-unit lines', async () => {
    cart.addItem( PRODUCT, 2 );
    cart.addItem( OTHER, 3 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '2' ) );
    expect( bag() ).toHaveAccessibleName( /2 items/ );
  } );

  it( 'does not inflate the badge when the same product is added repeatedly', async () => {
    cart.addItem( PRODUCT, 250 );
    cart.addItem( PRODUCT, 250 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
    expect( bag() ).toHaveAccessibleName( /1 item$/ );
    expect( container.querySelector( '.hdr-cart-n' ) ).not.toHaveAttribute( 'data-wide' );
  } );

  it( 'leaves two distinct lines at the full badge size', async () => {
    cart.addItem( PRODUCT, 12 );
    cart.addItem( OTHER, 12 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '2' ) );
    expect( container.querySelector( '.hdr-cart-n' ) ).not.toHaveAttribute( 'data-wide' );
  } );
} );

describe( 'the badge follows the cart without a navigation', () => {
  it( 'updates when an item is added in the same document', async () => {
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( bag() ).toHaveAccessibleName( /empty/ ) );

    // THE REASON src/lib/cart.ts DISPATCHES ITS OWN EVENT. The browser's `storage` event fires in
    // OTHER tabs and never in the one that made the write, so /shop/<slug>/'s add-to-cart button
    // would leave this badge stale until the next page load.
    act( () => { cart.addItem( PRODUCT, 2 ); } );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
  } );

  it( 'empties when the cart is cleared', async () => {
    cart.addItem( PRODUCT, 1 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
    act( () => { cart.clearCart(); } );
    await waitFor( () => expect( digits( container ) ).toBe( '' ) );
  } );

  it( 'stops listening when it unmounts', async () => {
    const remove = vi.spyOn( window, 'removeEventListener' );
    const { unmount } = render( <HeaderCart /> );
    await waitFor( () => expect( bag() ).toHaveAccessibleName( /empty/ ) );
    unmount();
    const events = remove.mock.calls.map( call => String( call[ 0 ] ) );
    expect( events ).toContain( 'storage' );
    expect( events ).toContain( cart.CART_CHANGED_EVENT );
  } );
} );

describe( 'the control itself', () => {
  it( 'is a link to the cart, so it works with no JavaScript', () => {
    render( <HeaderCart /> );
    // A plain anchor rather than next/link, for the same styled-jsx reason the logo is one. The
    // trailing slash is load-bearing: next.config.js sets trailingSlash, so /cart would 308.
    expect( bag() ).toHaveAttribute( 'href', '/cart/' );
  } );

  it( 'renders no text at all and carries its name on the attribute', () => {
    const { container } = render( <HeaderCart /> );
    /*
     * THE LABEL IS DELETED, NOT CLIPPED, on owner instruction - "shopping Bag text delete not
     * hidden". So there is no .hdr-cart-label and no .hdr-cart-spoken element, and the control
     * renders ZERO visible or hidden text; the only thing inside it is the aria-hidden glyph.
     *
     * The name therefore has to be the attribute. That is a reversal of the previous contract here,
     * which asserted the opposite, and the reason is worth keeping: a link whose only content is an
     * aria-hidden glyph has no accessible name at all, which a screen reader announces as a bare
     * "link" and Lighthouse fails as a discernible-name violation. The cost is that attribute text
     * is never translated - SupportWidget's walker rewrites text nodes only - so this string stays
     * English where the old clipped node would have been translated. That is the trade the
     * instruction buys, and it is recorded rather than hidden.
     */
    const link = bag();
    expect( link.getAttribute( 'aria-label' ) ).toBe( 'Shopping Bag, empty' );
    expect( container.querySelector( '.hdr-cart-label' ) ).toBeNull();
    expect( container.querySelector( '.hdr-cart-spoken' ) ).toBeNull();
    /*
     * No text node anywhere in the control - the glyph and the badge digits are all there is.
     * The <style> element is excluded because styled-jsx renders the stylesheet INSIDE the
     * component in jsdom (it is hoisted to the head in a real build), so its CSS would otherwise
     * count as this element's text. Cloning and removing it reads the markup rather than the
     * stylesheet, which is the thing being asserted.
     */
    const copy = link.cloneNode( true ) as HTMLElement;
    copy.querySelectorAll( 'style' ).forEach( node => node.remove() );
    expect( ( copy.textContent || '' ).trim() ).toBe( '' );

    /*
     * Still icon only: no border and no fill at rest. The focus ring is deliberately NOT asserted
     * away - it is an accessibility requirement, not decoration.
     */
    /*
     * Asserted as the absence of a RULE, not of the substring: a comment that explains why a class
     * is gone necessarily names it, and a bare `not.toContain` would fail on the explanation
     * instead of on a real rule. Matching `{` pins the declaration itself.
     */
    const css = container.querySelector( 'style' )?.textContent || '';
    expect( css ).not.toMatch( /\.hdr-cart-label\s*\{/ );
    expect( css ).not.toMatch( /\.hdr-cart-spoken\s*\{/ );
    const rest = /\.hdr-cart\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    expect( rest ).toContain( 'border:0' );
    expect( rest ).toContain( 'background:none' );
    expect( rest ).not.toContain( '#cfe0a6' );
    expect( css ).toContain( '.hdr-cart:focus-visible' );
  } );

  it( 'wears the MENU ICON\'S hover, same colour and same shape', () => {
    /*
     * OWNER INSTRUCTION: "cart hover color should match menu hover color".
     *
     * .nav-trigger's hover in Header.tsx is `background:#d1f470` with the chevron left at #1a3a2a -
     * a LIME SURFACE, not a glyph recolour. Matching it therefore means painting the surface and
     * leaving the bag dark, which reverses an earlier pass that recoloured the glyph to #3da35a.
     * That earlier value measured well (3.19:1 on white) but is not a colour the menu icon uses, so
     * it answered the wrong question.
     *
     * THIS DOES NOT CONTRADICT "dont show back grund rounc cicilr". That rejected a round CIRCLE.
     * The menu chip is a 10px rounded square, so this control's radius is 10px too and the shapes
     * now match - which is why the radius assertion below is part of THIS test rather than a
     * separate one: colour and shape are one instruction.
     *
     * Read from the rule BODY, not the whole sheet: the comment above the rule necessarily discusses
     * the background that was removed and the colours that were rejected, so a substring check
     * against the stylesheet would match the explanation instead of a declaration.
     */
    const { container } = render( <HeaderCart /> );
    const css = container.querySelector( 'style' )?.textContent || '';

    const hover = /\.hdr-cart:hover\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    expect( hover ).toContain( 'background:var(--public-brand-lime)' );
    // The glyph is NOT recoloured - it stays #1a3a2a, which is 10.03:1 on lime. A colour declaration
    // here would be the reverted treatment creeping back.
    expect( hover ).not.toMatch( /(^|;)\s*color:/ );
    // The menu grows a 2px dark edge on hover; this control does not, because its border was removed
    // outright on a separate instruction ("only cart icon no text or boder").
    expect( hover ).not.toMatch( /border/ );

    const rest = /\.hdr-cart\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    // 10px, matching .nav-trigger's chip - NOT 50%. The circle is what was objected to.
    expect( rest ).toContain( 'border-radius:10px' );
    expect( rest ).not.toContain( 'border-radius:50%' );
    // The transition follows the property that actually animates. A leftover `transition:color`
    // would leave the lime fill snapping in with no glide.
    expect( rest ).toContain( 'transition:background-color' );
    // Still nothing drawn at REST: lime is a hover state, not a permanent chip.
    expect( rest ).toContain( 'background:none' );
    // The focus ring is untouched by a hover change - re-asserted because this is the test most
    // likely to be edited by whoever next changes the hover treatment.
    expect( css ).toContain( '.hdr-cart:focus-visible' );
  } );

  it( 'uses the same hover colour the menu trigger uses, read from Header.tsx', () => {
    /*
     * THE MATCH IS ASSERTED AGAINST THE SOURCE OF TRUTH, not against a copy of the hex.
     *
     * "Match the menu" is a relationship between two files, and a test that hard-codes #d1f470 in
     * both places would keep passing after someone restyled the menu - which is exactly when this
     * needs to fail. So Header.tsx is read and its .nav-trigger hover background is extracted, then
     * compared with the bag's.
     */
    const header = fs.readFileSync(
      path.join( process.cwd(), 'src', 'components', 'Header.tsx' ), 'utf8',
    );
    const menuHover = /\.nav-trigger:hover[^{]*\{([^}]*)\}/.exec( header )?.[ 1 ] || '';
    const menuColour = /background:([^;}]+)/i.exec( menuHover )?.[ 1 ];
    expect( menuColour ).toBeTruthy();

    const { container } = render( <HeaderCart /> );
    const css = container.querySelector( 'style' )?.textContent || '';
    const bagHover = /\.hdr-cart:hover\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    const bagColour = /background:([^;}]+)/i.exec( bagHover )?.[ 1 ];

    expect( bagColour ).toBe( menuColour );
  } );

  it( 'draws a 36px glyph inside an unchanged 44px target', () => {
    /*
     * OWNER INSTRUCTION: "cart icon if possible increase the size". 30px -> 36px, which is the
     * largest even step that still leaves a 4px inset on each side of the 44px box.
     *
     * THE 44px DOES NOT MOVE, and that is the point of asserting both numbers in one test: 44px is
     * the WCAG 2.5.8 target floor AND what holds .hdr-in's row at the pinned 108px / 96px header
     * height. Growing the target to fit a bigger glyph would silently change the header geometry
     * that Header.test.tsx and devicecheck.js both pin.
     *
     * jsdom computes no styles, so this reads the declarations. The rendered geometry is
     * devicecheck.js's job across fifteen postures.
     */
    const { container } = render( <HeaderCart /> );
    const css = container.querySelector( 'style' )?.textContent || '';
    const glyph = /\.hdr-cart-glyph\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    expect( glyph ).toContain( 'inline-size:36px' );
    expect( glyph ).toContain( 'block-size:36px' );
    const svg = /\.hdr-cart-glyph svg\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    expect( svg ).toContain( 'inline-size:36px' );
    expect( svg ).toContain( 'block-size:36px' );
    // The box and the artwork have to agree, or the badge's 60% offset lands off the bag's body.
    expect( glyph ).not.toContain( '30px' );
    expect( svg ).not.toContain( '30px' );

    const rest = /\.hdr-cart\{([^}]*)\}/.exec( css )?.[ 1 ] || '';
    expect( rest ).toContain( 'inline-size:44px' );
    expect( rest ).toContain( 'min-height:44px' );
  } );

  it( 'keeps the glyph decorative so the name is not read twice', () => {
    const { container } = render( <HeaderCart /> );
    const glyph = container.querySelector( '.hdr-cart-glyph' );
    expect( glyph?.getAttribute( 'aria-hidden' ) ).toBe( 'true' );
    // The digits live inside that aria-hidden subtree, which is why the spoken count is a separate
    // node: a walker and a screen reader both skip this one.
    expect( glyph?.querySelector( 'svg' ) ).not.toBeNull();
  } );

  it( 'flags the drawn number as untranslatable, the way prices are', async () => {
    cart.addItem( PRODUCT, 2 );
    const { container } = render( <HeaderCart /> );
    await waitFor( () => expect( digits( container ) ).toBe( '1' ) );
    // A regrouped numeral is a different number. Belt and braces - the glyph is aria-hidden, which
    // the walker already skips - but it keeps the handling of numbers consistent across the site.
    expect( container.querySelector( '.hdr-cart-n' ) )
      .toHaveAttribute( 'data-wc-no-translate', 'true' );
  } );
} );

describe( 'the header still reads the way its own tests require', () => {
  /*
   * Header.test.tsx reaches the menu trigger with container.querySelector('button') to prove the
   * chevron is drawn rather than typed. Adding a control to the header could have broken that
   * silently, so the ordering is asserted here too - from the other side, where the bag is the thing
   * being added.
   */
  it( 'leaves the menu trigger as the first and only button', () => {
    const { container } = render( <Header /> );
    const buttons = container.querySelectorAll( 'button' );
    expect( buttons[ 0 ].className ).toContain( 'nav-trigger' );
    // The bag is an anchor, so it adds no button at all.
    expect( buttons[ 0 ].textContent ).toBe( '' );
  } );

  it( 'puts the bag after the brand in the reading and tab order', () => {
    const { container } = render( <Header /> );
    const logo = container.querySelector( '.logo' ) as Node;
    const bagLink = container.querySelector( '.hdr-cart' ) as Node;
    expect( logo ).not.toBeNull();
    expect( bagLink ).not.toBeNull();
    // DOCUMENT_POSITION_FOLLOWING = 4. The bag comes after the lockup, so a keyboard user reaches
    // the brand and the menu first.
    expect( logo.compareDocumentPosition( bagLink ) & Node.DOCUMENT_POSITION_FOLLOWING ).toBeTruthy();
  } );

  it( 'reserves room for a 44px chip at 280px rather than letting it overflow', () => {
    /*
     * MEASURED, NOT GUESSED, AND THE NUMBERS ARE WHY THIS RULE EXISTS. On the built header at 280px
     * - Galaxy Fold, folded, the narrowest posture devicecheck.js carries - the 16px gutter leaves a
     * 248px content box and .logo-nav occupies 212.8px of it. That is 35.2px free, against the 44px
     * floor every header control has to clear. 10px of gutter returns 12px and a 6px .logo-nav gap
     * returns 2px: 49.2px, which is 44px of chip and 5.2px of air.
     *
     * Asserted as a string because jsdom applies no CSS. The real geometry is devicecheck's job;
     * this exists so deleting the rule is a test failure rather than a 280px overflow nobody runs.
     */
    const source = fs.readFileSync(
      path.join( process.cwd(), 'src', 'components', 'Header.tsx' ), 'utf8',
    );
    expect( source ).toContain( '@media(max-width:340px){.hdr-in{padding-inline:10px}.logo-nav{gap:6px}}' );
    // 340px is RotatingHero's own narrow rung, reused so the site has one narrow breakpoint. 344px
    // (Z Fold cover) sits above it and keeps the full gutter.
    expect( source ).not.toContain( '@media(max-width:360px)' );
  } );

  it( 'still pins both header heights and the 46px trigger', () => {
    // The two numbers the brief required to be unchanged. Header.test.tsx asserts them too; this
    // repeats them because THIS change is the one that could have moved them.
    const { container } = render( <Header /> );
    const css = Array.from( container.querySelectorAll( 'style' ) )
      .map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( 'box-sizing:border-box;height:108px' );
    expect( css ).toContain( '@media(max-width:767px){.hdr-in{height:96px' );
    expect( css ).toContain( '.nav-trigger{min-width:46px;min-height:46px' );
  } );
} );
