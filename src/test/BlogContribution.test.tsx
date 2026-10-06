import fs from 'fs';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import BlogContribution from '../components/BlogContribution';
import { CONTRIBUTION_CHOICES, CONTRIBUTION_PRODUCT_ID } from '../config/contribution';
import type { ShopProduct } from '../content/shop';
import {
  addItem, basketFingerprint, cartCount, clearCart, readCart, setContribution, toLineItems,
} from '../lib/cart';

/** A kiosk to stand beside a contribution, so the mixed-basket cases have something to mix. */
const KIOSK: ShopProduct = {
  id: '00d4c72b-f694-441a-a192-e16f4b192440',
  name: 'Kiosk',
  slug: 'kiosk',
  formattedPrice: '\u20B924,999.00',
  price: '24999.00',
  currency: 'INR',
  inStock: true,
  tagline: 'A kiosk.',
  body: [],
  variants: [ { id: '9f1c0e8a-1111-4222-8333-444455556666', label: 'One', inStock: true } ],
};

/** The three choices, by position, so a case can name an amount without re-typing a GUID. */
const [ LOW, MID, HIGH ] = CONTRIBUTION_CHOICES;

/**
 * THE "SUPPORT THIS WORK" CONTRIBUTION COMPONENT, IN ISOLATION.
 *
 * These cases pin the things Section 5 is explicit about and that would regress silently:
 *   1. The offered amounts come from src/config/contribution.ts, not from literals in the markup.
 *   2. Choosing one writes ONE cart line at quantity 1 and navigates. Nothing is validated,
 *      parsed or coerced, because a control with three fixed values cannot emit a fourth.
 *   3. With the product unconfigured, the UI shows an honest non-error state and renders NO form.
 *      A browser signal is never treated as proof of payment.
 *
 * WHAT THE 2026-10-04 OWNER MODEL CHANGE DELETED FROM THIS FILE, so the absence is not read as a
 * gap in coverage: every custom-amount case. There was a `describe` block for client-side bounds
 * (`isAllowedContributionPaise` at the boundary, `rupeesToPaise` refusing 'abc' / '' / '-5' /
 * '10.123'), an `it.each` over six rejected strings, a two-sided check that the component and the
 * cart field showed the same help sentence, and two "does not submit" cases. All of them tested a
 * free-text field that no longer exists. They are not replaced by weaker assertions - there is
 * simply nothing left to reject.
 */

beforeEach( () => {
  // localStorage persists across cases in one jsdom environment, and most of these cases assert
  // on the cart's CONTENTS -- so a leftover line from the previous case would be read as this
  // one's result.
  window.localStorage.clear();
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
} );

const renderBlock = () =>
  render( <BlogContribution postId="post-1" slug="a-clear-question" /> );

describe( 'BlogContribution choices', () => {
  it( 'renders exactly the three choices from the central config, and no Other', () => {
    const { container } = renderBlock();
    const faces = Array.from( container.querySelectorAll( '.bc-choice-face' ) )
      .map( n => n.textContent || '' );

    // One face per choice, carrying the rupee value declared in the config.
    for ( const choice of CONTRIBUTION_CHOICES ) {
      expect( faces.some( f => f.trim() === `\u20B9${ choice.rupees }` ) ).toBe( true );
    }
    // The owner's amounts, proving nothing re-typed a different number into the markup. Asserted
    // as FULL face text rather than as substrings: '100' is a substring of '1000' and would pass a
    // loose check on the wrong number.
    expect( faces.map( f => f.trim() ) ).toEqual( [ '\u20B9100', '\u20B9250', '\u20B9500' ] );
    // The retired amounts, and the retired custom option, must not still be on screen. The ₹1
    // product model and the ₹200/₹400/₹600 presets both predate this.
    expect( faces.join( ' ' ) ).not.toContain( 'Other' );
    expect( faces.join( ' ' ) ).not.toContain( '\u20B9200' );
    expect( faces.join( ' ' ) ).not.toContain( '\u20B9400' );
    expect( faces.join( ' ' ) ).not.toContain( '\u20B9600' );

    // One radio per choice and nothing else: no "Other" radio, and no free-text input anywhere.
    expect( container.querySelectorAll( 'input[type="radio"]' ) )
      .toHaveLength( CONTRIBUTION_CHOICES.length );
    expect( container.querySelectorAll( 'input:not([type="radio"])' ) ).toHaveLength( 0 );
  } );

  it( 'offers three fixed prices, which is the whole set the server accepts', () => {
    // The paise figures are what `blog_contribution.CONTRIBUTION_CHOICES_PAISE` holds, and
    // tests/test_blog_contribution.py pins the two declarations equal. This side asserts the
    // rupee/paise pair is internally consistent, so a typo in one of the two numbers on a choice
    // cannot pass by agreeing with the Python copy of the same typo.
    for ( const choice of CONTRIBUTION_CHOICES ) {
      expect( choice.paise ).toBe( choice.rupees * 100 );
      expect( choice.variantId ).toMatch( /^[0-9a-f-]{36}$/ );
    }
    expect( CONTRIBUTION_CHOICES ).toHaveLength( 3 );
    expect( new Set( CONTRIBUTION_CHOICES.map( c => c.variantId ) ).size ).toBe( 3 );
  } );

  it( 'uses an h2 heading and the mandated primary copy, never an h1', () => {
    const { container } = renderBlock();
    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( container.textContent ).toContain(
      'If you found this useful, you\u2019re welcome to make a small voluntary contribution.'
    );
  } );
} );

describe( 'the second payment implementation is GONE, not disabled', () => {
  /**
   * T12. Phase 2's central claim, asserted as the thing that would regress silently.
   *
   * This component used to POST to an endpoint that answered 404, branch on a backend state, and
   * hold `submitting` / `ready` phases. A contribution is now ONE fixed-price Wix product line in
   * the existing cart, paid on the one live checkout path. So the assertion is not "the fetch
   * returns the right thing" - it is that THERE IS NO FETCH, in any state, because a second money
   * path is the failure this phase exists to remove.
   */
  it( 'issues NO network request on submit, for any of the three choices', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    const assign = vi.fn();
    vi.stubGlobal( 'location', { ...window.location, assign } );

    renderBlock();
    for ( const choice of CONTRIBUTION_CHOICES ) {
      fireEvent.click( screen.getByDisplayValue( choice.variantId ) );
      fireEvent.click( screen.getByRole( 'button', { name: /^Contribute / } ) );
    }

    expect( fetchMock ).not.toHaveBeenCalled();
  } );

  it( 'names no contribution endpoint in its source at all', () => {
    // A source pin, because an unused constant is the step before a reinstated fetch.
    const source = fs.readFileSync(
      path.resolve( __dirname, '../components/BlogContribution.tsx' ), 'utf8' );
    expect( source ).not.toMatch( /CONTRIBUTION_INITIATE_URL/ );
    // The endpoint PATH is deliberately not asserted absent: the docblock explaining why this
    // component no longer calls it necessarily names it, and a text search cannot tell an
    // explanation from a call site. What is asserted instead is the absence of anything that
    // could USE a path - the constant, the fetch, and the state machine around it.
    expect( source ).not.toMatch( /\bfetch\s*\(/ );
    expect( source ).not.toMatch( /CHECKOUT_OPTIONS_READY/ );
    expect( source ).not.toMatch( /PAYMENT_INITIATION_DISABLED/ );
  } );

  it( 'writes ONE cart line at QUANTITY 1 for the chosen amount, and navigates to the cart', () => {
    const assign = vi.fn();
    vi.stubGlobal( 'location', { ...window.location, assign } );
    renderBlock();

    fireEvent.click( screen.getByDisplayValue( MID.variantId ) );
    fireEvent.click( screen.getByRole( 'button', { name: `Contribute \u20B9${ MID.rupees }` } ) );

    const cart = readCart();
    expect( cart ).toHaveLength( 1 );
    // QUANTITY 1, not the rupee figure. This is the invariant the model change turns on: the
    // amount is the variant's own price, so nothing about the amount is carried by the quantity.
    expect( cart[ 0 ].quantity ).toBe( 1 );
    expect( cart[ 0 ].productId ).toBe( CONTRIBUTION_PRODUCT_ID );
    expect( cart[ 0 ].variantId ).toBe( MID.variantId );
    // The amount is in the name and in the price, because the quantity no longer says it.
    expect( cart[ 0 ].name ).toBe( `Contribute \u20B9${ MID.rupees }` );
    expect( cart[ 0 ].formattedPrice ).toBe( `\u20B9${ MID.rupees }.00` );
    // Empty slug, so the cart row does NOT link to a /shop/contribute/ page that SHOP_PRODUCTS
    // deliberately excludes.
    expect( cart[ 0 ].slug ).toBe( '' );
    expect( assign ).toHaveBeenCalledWith( '/cart/' );
  } );

  it( 'REPLACES rather than adds when a second amount is chosen', () => {
    // `setContribution` does not reuse `addItem`, which increments: choosing ₹100 then ₹500 would
    // leave two contribution lines, which the server refuses as two contributions.
    vi.stubGlobal( 'location', { ...window.location, assign: vi.fn() } );
    renderBlock();
    fireEvent.click( screen.getByDisplayValue( LOW.variantId ) );
    fireEvent.click( screen.getByRole( 'button', { name: `Contribute \u20B9${ LOW.rupees }` } ) );
    fireEvent.click( screen.getByDisplayValue( HIGH.variantId ) );
    fireEvent.click( screen.getByRole( 'button', { name: `Contribute \u20B9${ HIGH.rupees }` } ) );

    const cart = readCart();
    expect( cart ).toHaveLength( 1 );
    expect( cart[ 0 ].variantId ).toBe( HIGH.variantId );
    expect( cart[ 0 ].quantity ).toBe( 1 );
  } );

  it( 'writes nothing for a variant that is not one of the three', () => {
    // Unreachable from this component - every control emits a committed variant id - and reachable
    // from a cart written by an older build or a console call. Membership is the only check left
    // now that there is no amount to validate.
    expect( setContribution( '00000000-0000-4000-8000-000000000000' ) ).toHaveLength( 0 );
    expect( readCart() ).toHaveLength( 0 );
  } );

  it( 'puts NO fee-disclosure line under the CTA', () => {
    // OWNER DECISION [PHASE2-FEE-001] is answered fee-exempt, so the customer pays exactly the
    // figure on the button. A disclosure about a fee that is not charged would be its own small
    // untruth.
    const { container } = renderBlock();
    const text = container.textContent || '';
    expect( text ).not.toMatch( /fee/i );
    expect( text ).not.toMatch( /convenience/i );
    expect( text ).not.toMatch( /GST/ );
  } );

  it( 'warns once when the cart already holds other items, and still navigates', () => {
    const assign = vi.fn();
    vi.stubGlobal( 'location', { ...window.location, assign } );
    addItem( KIOSK, 1 );
    renderBlock();
    expect( screen.getByText( /A contribution is paid on its own/ ) ).toBeInTheDocument();

    fireEvent.click( screen.getByRole( 'button', { name: /^Contribute / } ) );
    // The submit still goes to /cart/, where the notice and BOTH one-click exits live. Deciding
    // for the customer which lines to drop would be worse than telling them.
    expect( assign ).toHaveBeenCalledWith( '/cart/' );
  } );

  it( 'keeps its accessibility furniture and its h2 rung', () => {
    const { container } = renderBlock();
    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    expect( container.querySelector( '[role="radiogroup"]' ) ).not.toBeNull();
    // The reduced-motion block and the palette are untouched by this phase.
    const source = fs.readFileSync(
      path.resolve( __dirname, '../components/BlogContribution.tsx' ), 'utf8' );
    expect( source ).toMatch( /prefers-reduced-motion:reduce/ );
    expect( source ).toMatch( /#d1f470/ );
    expect( source ).toMatch( /#1a3a2a/ );
    expect( source ).toMatch( /outline:3px solid #1a3a2a;outline-offset:2px/ );
  } );

  it( 'scopes the radio group NAME to the post, so two blocks on one page do not share state', () => {
    // `embedded` puts this block on /vayulok/ as well as on every post, and a page could hold
    // both. A fixed `name="bc-amount"` would make the two radio groups one.
    const { container } = render( <BlogContribution postId="p" slug="first-post" /> );
    const names = new Set( Array.from( container.querySelectorAll( 'input[type="radio"]' ) )
      .map( n => n.getAttribute( 'name' ) ) );
    expect( names ).toEqual( new Set( [ 'bc-amount-first-post' ] ) );
  } );
} );

describe( 'the honest-unavailable state, and what now gates it', () => {
  /**
   * The only browser-side gate is CONFIGURATION, and it is knowable at BUILD time - which is what
   * a static export needs. A build with no contribution vehicle says contributions are unavailable
   * instead of offering a button that cannot work.
   *
   * Driven by mocking `../content/shop`, because `CONTRIBUTION_CONFIGURED` is resolved at module
   * scope.
   */
  it( 'renders the honest line and NO FORM when nothing is configured', async () => {
    vi.resetModules();
    vi.doMock( '../content/shop', async () => ( {
      ...( await vi.importActual<typeof import( '../content/shop' )>( '../content/shop' ) ),
      CONTRIBUTION_CONFIGURED: false,
      CONTRIBUTION_PRODUCT_ID: '',
    } ) );
    const Unconfigured = ( await import( '../components/BlogContribution' ) ).default;
    const { container } = render( <Unconfigured postId="p" slug="s" /> );

    expect( container.textContent )
      .toContain( 'Contributions are not available right now.' );
    expect( container.querySelector( 'form' ) ).toBeNull();
    expect( container.querySelectorAll( 'input' ) ).toHaveLength( 0 );
    expect( container.querySelector( 'button' ) ).toBeNull();
    // Still an h2 block inside a page that owns its own h1.
    expect( container.querySelector( 'h1' ) ).toBeNull();
    expect( container.querySelector( 'h2' )?.textContent ).toBe( 'Contribute' );
    vi.doUnmock( '../content/shop' );
    vi.resetModules();
  } );
} );

describe( 'cartCount and basketFingerprint, which the header and the request key read', () => {
  it( 'counts a contribution as ONE, which is now its real quantity', () => {
    // Under the retired amount-as-quantity model this needed a special case in `cartCount`, or a
    // ₹400 contribution rendered "Shopping Bag, 400 items". The line is quantity 1 now, so the
    // plain sum is the honest answer and the special case is gone.
    setContribution( MID.variantId );
    expect( cartCount() ).toBe( 1 );
    expect( readCart()[ 0 ].quantity ).toBe( 1 );
  } );

  it( 'counts a contribution plus a kiosk at quantity 2 as THREE', () => {
    setContribution( MID.variantId );
    addItem( KIOSK, 2 );
    expect( cartCount() ).toBe( 3 );
  } );

  it( 'is stable across two calls on an unchanged cart', () => {
    setContribution( MID.variantId );
    expect( basketFingerprint() ).toBe( basketFingerprint() );
  } );

  it( 'is order-independent for the same lines added either way', () => {
    addItem( KIOSK, 1 );
    setContribution( LOW.variantId );
    const forwards = basketFingerprint();
    clearCart();
    setContribution( LOW.variantId );
    addItem( KIOSK, 1 );
    expect( basketFingerprint() ).toBe( forwards );
  } );

  it( 'CHANGES when the contribution amount changes', () => {
    // A changed amount IS a changed intent: `intent_fingerprint` covers `total_payable_paise`, so
    // resuming the old reservation for it is exactly the refusal the scoping removes. The amount
    // now moves the VARIANT rather than the quantity, which is why this case has to keep existing
    // -- the fingerprint covers both fields, and only one of them moves any more.
    setContribution( LOW.variantId );
    const before = basketFingerprint();
    setContribution( HIGH.variantId );
    expect( basketFingerprint() ).not.toBe( before );
  } );

  it( 'carries a digest, a length and a line count, and the count is the real one', () => {
    setContribution( MID.variantId );
    addItem( KIOSK, 1 );
    const fingerprint = basketFingerprint();
    expect( fingerprint ).toMatch( /^[0-9a-z]+\.[0-9a-z]+\.\d+$/ );
    expect( Number( fingerprint.split( '.' )[ 2 ] ) ).toBe( toLineItems().length );
  } );

  it( 'agrees between the explicit and default forms, and the explicit one describes its argument', () => {
    setContribution( MID.variantId );
    const payload = toLineItems();
    expect( basketFingerprint( payload ) ).toBe( basketFingerprint() );
    // Mutate storage WITHOUT re-reading: the explicit form must still describe the array it was
    // handed, which is the property that stops the post-save retry keying a basket it is not
    // sending.
    setContribution( HIGH.variantId );
    expect( basketFingerprint( payload ) ).not.toBe( basketFingerprint() );
    expect( basketFingerprint( payload ) ).toBe( basketFingerprint( payload ) );
  } );
} );

describe( 'BlogContribution does not fetch at render time', () => {
  it( 'does not fetch at render time, so the static export is not broken', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    renderBlock();
    // The default server-rendered state is the three-choice form; a call happens only on a user
    // action, never during render/prerender -- and there is no call to happen at all.
    expect( fetchMock ).not.toHaveBeenCalled();
  } );
} );
