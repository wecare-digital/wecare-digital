import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import PageTopBand from '../components/PageTopBand';
import Cart from '../pages/cart';
import SignIn from '../pages/account/sign-in';
import CheckoutStatus, { viewFor } from '../pages/checkout/status';
import CheckoutSuccess from '../pages/checkout/success';
import ShopProductPage from '../pages/shop/[slug]';
import { shopProductBySlug } from '../content/shop';
import type { ShopProduct } from '../content/shop';
import * as customerAuth from '../lib/customerAuth';
import * as cartLib from '../lib/cart';
import { CONTRIBUTION_CHOICES } from '../config/contribution';

/**
 * THE TOP SECTION EVERY PUBLIC PAGE MUST CARRY, and the four transactional pages that did not.
 *
 * The owner reported these pages as missing the shared structure, the animations and the home
 * page's design language. Two of the three were measurable defects rather than matters of taste:
 * /checkout/status/ and /checkout/success/ carried NO header clearance at all - they centred a card
 * inside min-height:100vh under a 108px fixed header - and declared no font family, so their
 * typeface was a side effect of an Amplify stylesheet setting one on body.
 *
 * What is asserted where. jsdom applies no CSS, so clearance, type rungs and tap targets are
 * measured in a real browser: tools/browser/devicecheck.js now carries /cart/, /account/sign-in/,
 * /checkout/status/ and /checkout/success/ across fifteen postures, and pageaudit.js probes the
 * header clearance with elementFromPoint. These tests cover what jsdom can decide: the structure
 * (one main, one h1, nothing conversion-shaped inside the band), the opt-in direction of the
 * entrance animation, and the copy invariants that protect a customer's money.
 */

const KIOSK = (): ShopProduct => shopProductBySlug( 'kiosk' ) as ShopProduct;

/** The four pages that moved onto the shared band, plus the catalogue page that joined them. */
const BAND_PAGE_FILES = [
  'src/pages/cart.tsx',
  'src/pages/account/sign-in.tsx',
  'src/pages/checkout/status.tsx',
  'src/pages/checkout/success.tsx',
  'src/pages/shop/[slug].tsx',
];

/**
 * The surfaces the "no red" instruction covers: the five band pages plus the two shared components
 * they mount. A per-page list alone would miss an error treatment that lives in a component, which
 * is where a shared one would naturally go.
 */
const NO_RED_FILES = [
  ...BAND_PAGE_FILES,
  'src/components/PageTopBand.tsx',
  'src/components/HeaderCart.tsx',
];

const read = ( rel: string ): string =>
  fs.readFileSync( path.join( process.cwd(), rel ), 'utf8' );

let navigatedTo: string;

beforeEach( () => {
  window.localStorage.clear();
  navigatedTo = '';
  Object.defineProperty( window, 'location', {
    configurable: true,
    value: {
      ...window.location,
      search: '',
      assign: ( url: string ) => { navigatedTo = String( url ); },
      replace: ( url: string ) => { navigatedTo = String( url ); },
    },
  } );
} );

afterEach( () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
} );

describe( 'PageTopBand ships the settled state and arms the entrance afterwards', () => {
  it( 'renders a readable heading with no JavaScript having run', () => {
    /*
     * THE DIRECTION OF THIS IS THE WHOLE POINT, and getting it backwards shipped a blank hero on
     * twelve pages of this site. The CSS default must be the FINISHED band, with JavaScript adding
     * a class that puts the start state back - so a failed bundle, a crawler or a reader with
     * scripting off sees a complete heading rather than an invisible one.
     *
     * The first render is the no-JS proxy: the effect has not run, so .is-armed is absent and the
     * only declarations in play are the settled ones.
     */
    const { container } = render(
      <PageTopBand heading="Your cart" sub="A sub-line." ariaLabel="Your cart" />,
    );
    const layout = container.querySelector( '.ptb-layout' ) as HTMLElement;
    expect( layout.className ).not.toContain( 'is-armed' );
    expect( screen.getByRole( 'heading', { level: 1 } ).textContent ).toBe( 'Your cart' );
  } );

  it( 'arms and then reveals once motion is known to be allowed', async () => {
    const { container } = render(
      <PageTopBand heading="Your cart" ariaLabel="Your cart" />,
    );
    const layout = () => container.querySelector( '.ptb-layout' ) as HTMLElement;
    // .is-armed puts the start state back; .show plays it. Both land on the className, not through
    // classList - RotatingHero records why: React rewrites className on render and silently drops
    // an imperatively added class.
    await waitFor( () => expect( layout().className ).toContain( 'is-armed' ) );
    await waitFor( () => expect( layout().className ).toContain( 'show' ) );
  } );

  it( 'never arms at all when the reader asks for reduced motion', async () => {
    vi.spyOn( window, 'matchMedia' ).mockImplementation( ( query: string ) => ( {
      media: query, matches: true, onchange: null,
      addEventListener: () => undefined, removeEventListener: () => undefined,
      addListener: () => undefined, removeListener: () => undefined,
      dispatchEvent: () => false,
    } as unknown as MediaQueryList ) );

    const { container } = render( <PageTopBand heading="Your cart" ariaLabel="Your cart" /> );
    // Staying at the settled state is the correct response, because the settled state is what the
    // CSS already declares. There is nothing to undo.
    await new Promise( resolve => setTimeout( resolve, 120 ) );
    expect( ( container.querySelector( '.ptb-layout' ) as HTMLElement ).className )
      .not.toContain( 'is-armed' );
  } );

  it( 'puts the page inside the band rather than beside it', () => {
    const { container } = render(
      <PageTopBand heading="Your cart" ariaLabel="Your cart">
        <p className="child">below the band</p>
      </PageTopBand>,
    );
    // One main landmark, and the children share its measure. A page that rendered its own <main>
    // alongside this one would report two, which tools/audit/htmlcheck.js flags at HIGH.
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
    expect( container.querySelector( '.ptb-layout > .child' ) ).not.toBeNull();
  } );

  it( 'arms only the heading and the sub-line, never the children', () => {
    /*
     * opacity:0 does NOT remove an element from the tab order. Arming a band that contains a form
     * or a button would therefore leave invisible focusable controls for the length of the reveal,
     * which is the defect skill §6 names. So the armed selectors name .ptb-h1 and .ptb-sub and
     * nothing else.
     */
    const css = read( 'src/components/PageTopBand.tsx' );
    expect( css ).toContain( '.ptb-layout.is-armed .ptb-h1,.ptb-layout.is-armed .ptb-sub{opacity:0' );
    // No blanket rule over the layout or its descendants.
    expect( css ).not.toMatch( /\.ptb-layout\.is-armed\s*\{[^}]*opacity:0/ );
  } );

  it( 'carries both header heights and declares its own font stack', () => {
    const css = read( 'src/components/PageTopBand.tsx' );
    // The two-height clearance, which is the thing /checkout/* had none of. A style attribute
    // cannot express it, which is how an earlier page shipped a 48px pad under a 108px header.
    expect( css ).toContain( 'padding-top:108px' );
    expect( css ).toContain( 'padding-top:96px' );
    // Declared, not inherited: --font-sans has no Inter in it, so an inheriting band falls to a
    // serif the day the Amplify stylesheet import moves.
    expect( css ).toContain( "font-family:'Inter'" );
    // Tracking in em on the fluid size. A fixed px value against clamp() made optical tightness
    // swing 2.75x across the breakpoints.
    expect( css ).toContain( 'letter-spacing:-0.04em' );
    expect( css ).not.toMatch( /clamp\([^)]*\)[^}]*letter-spacing:-?[\d.]+px/ );
  } );
} );

describe( 'every page that moved onto the band kept exactly one h1 and one main', () => {
  it( 'renders one of each, with the page name as the heading', async () => {
    const cases: { name: string; element: React.ReactElement; heading: string }[] = [
      { name: 'cart', element: <Cart />, heading: 'Your cart' },
      { name: 'sign-in', element: <SignIn />, heading: 'Sign in to check out' },
      // No ?a= in the URL, so the honest answer is the holding screen rather than "confirming" -
      // there is no attempt to confirm. The structure is what this test is about either way.
      { name: 'status', element: <CheckoutStatus />, heading: 'Nothing to show here' },
      { name: 'success', element: <CheckoutSuccess />, heading: 'Order confirmation unavailable' },
      { name: 'product', element: <ShopProductPage product={ KIOSK() } />, heading: 'Kiosk' },
    ];
    for ( const entry of cases )
    {
      vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
      const { container, unmount } = render( entry.element );
      expect( container.querySelectorAll( 'main' ), entry.name ).toHaveLength( 1 );
      const h1s = container.querySelectorAll( 'h1' );
      expect( h1s, entry.name ).toHaveLength( 1 );
      expect( h1s[ 0 ].textContent, entry.name ).toBe( entry.heading );
      unmount();
    }
  } );

  it( 'puts no button, no link and no price inside the band itself', async () => {
    /*
     * Skill §6: "No CTA, no price, no conversion furniture in that band - the action belongs further
     * down." The product page was the live violation - its price sat in the top band, directly under
     * the h1 - and the price now sits with the button that acts on it.
     */
    const { container } = render( <ShopProductPage product={ KIOSK() } /> );
    const band = container.querySelector( '.ptb-top' ) as HTMLElement;
    expect( band ).not.toBeNull();
    expect( band.querySelectorAll( 'button, a' ) ).toHaveLength( 0 );
    expect( band.textContent || '' ).not.toContain( '₹' );
    // And the price really is on the page, below the band, rather than having been deleted.
    expect( container.querySelector( '.shopd-about .shopd-price' )?.textContent )
      .toBe( '₹24,999.00' );
  } );

  it( 'stops hand-rolling the clearance each page used to own', () => {
    // The point of sharing the band: five pages previously each stated their own 108px/96px pair,
    // or in two cases stated neither. None of them may state it again - a second copy is a second
    // thing to get wrong at one of the two header heights.
    for ( const file of BAND_PAGE_FILES )
    {
      expect( read( file ), file ).toContain( 'PageTopBand' );
      // Comments stripped: two of these files explain in prose that they USED to centre a card
      // inside min-height:100vh, and a substring search cannot tell a citation from a declaration.
      const code = read( file ).replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );
      expect( code, file ).not.toContain( 'padding-top:108px' );
      expect( code, file ).not.toContain( 'min-height:100vh' );
    }
  } );
} );

describe( 'no red anywhere on these pages, on owner instruction', () => {
  it( 'drops the pink/maroon error palette and the off-palette green', () => {
    /*
     * The owner's instruction was that error states use the lime scheme and that red is not used.
     * These five values were the whole of the off-palette colour on these pages:
     *   #fbe9e9 / #f0c0c0 / #8a1f1f   the pink error wash, its border and its maroon type
     *   #1f8f4e                       a green that appears nowhere in the home design, used as a
     *                                 button fill on both checkout screens
     * The replacement is the site's own state tint rgba(209,244,112,.22) behind a solid #d1f470
     * inline-start edge with #1a3a2a type - .shop-asof's treatment - and the lime pill CTA.
     *
     * Colour is NOT the only cue, which is what makes removing red safe rather than a regression:
     * role=alert / role=status carries the severity, the sentence states the problem, and the firm
     * variant steps the edge to 4px and the weight to 700 - a luminance and weight change, which
     * survives forced-colors and reduced colour discrimination in a way a hue swap does not.
     */
    const RETIRED = [ '#fbe9e9', '#f0c0c0', '#8a1f1f', '#1f8f4e' ];
    for ( const file of NO_RED_FILES )
    {
      // Comments stripped first: these files cite the values they replaced, and a substring search
      // cannot tell a citation from a declaration. This repo has had to correct that three times.
      const code = read( file ).replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );
      for ( const colour of RETIRED )
      {
        expect( code.toLowerCase(), `${file} still declares ${colour}` ).not.toContain( colour );
      }
    }
  } );

  it( 'declares no red by any notation: hex, rgb(), hsl() or name', () => {
    /*
     * A NAMED LIST OF FOUR HEXES IS NOT A SWEEP, which is why this test sits beside the one above
     * rather than replacing it. That one pins the specific values this work removed - useful as a
     * regression guard, useless against a NEW red arriving in a different notation. The obvious
     * failure mode is someone reaching for `color:crimson` or `rgb(220,38,38)` on the next error
     * state and no gate noticing.
     *
     * WHY NOT GREP FOR THE WORD "red". Because "required", "rendered", "border" and "reduce" all
     * contain it, and this page is full of all four - a naive search reports twenty hits and zero
     * are colours. The three patterns below match NOTATION instead:
     *   - a 3- or 6-digit hex whose red channel dominates both others by a clear margin;
     *   - rgb()/rgba() with the same dominance;
     *   - CSS named colours that are actually red or pink, listed explicitly.
     * hsl() is matched on hue rather than channels. The dominance margin rather than "any r > g" is
     * what keeps #1a3a2a, #d1f470 and rgba(0,0,0,.898) from being reported.
     *
     * SCOPE. The five band pages PLUS the two components the band pages mount - PageTopBand and
     * HeaderCart - because an error treatment living in a shared component would be just as red and
     * is not covered by a per-page list.
     */
    const NAMED_RED = [
      'red', 'crimson', 'maroon', 'firebrick', 'darkred', 'indianred', 'tomato', 'orangered',
      'salmon', 'lightsalmon', 'darksalmon', 'pink', 'hotpink', 'deeppink', 'lightpink',
      'palevioletred', 'mediumvioletred', 'lightcoral', 'rosybrown', 'brown', 'mistyrose',
    ];

    /** A hex is "red" when its red channel beats both others by more than a sixteenth of the range. */
    function hexIsRed ( hex: string ): boolean {
      const h = hex.length === 4
        ? hex[ 1 ] + hex[ 1 ] + hex[ 2 ] + hex[ 2 ] + hex[ 3 ] + hex[ 3 ]
        : hex.slice( 1 );
      const r = parseInt( h.slice( 0, 2 ), 16 );
      const g = parseInt( h.slice( 2, 4 ), 16 );
      const b = parseInt( h.slice( 4, 6 ), 16 );
      return r - g > 16 && r - b > 16;
    }

    for ( const file of NO_RED_FILES )
    {
      const code = read( file ).replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );

      const hexes = code.match( /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b/g ) || [];
      for ( const hex of hexes )
      {
        expect( hexIsRed( hex ), `${file} declares the red/pink hex ${hex}` ).toBe( false );
      }

      const rgbs = code.match( /rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+/g ) || [];
      for ( const rgb of rgbs )
      {
        const [ r, g, b ] = ( rgb.match( /\d+/g ) || [] ).map( Number );
        expect( r - g > 16 && r - b > 16, `${file} declares the red/pink ${rgb}…)` ).toBe( false );
      }

      // hsl() hues 0-20 and 330-360 are the red/pink arc.
      const hsls = code.match( /hsla?\(\s*(\d+)/g ) || [];
      for ( const hsl of hsls )
      {
        const hue = Number( ( hsl.match( /\d+/ ) || [ '0' ] )[ 0 ] );
        expect( hue <= 20 || hue >= 330, `${file} declares the red/pink ${hsl}…)` ).toBe( false );
      }

      for ( const name of NAMED_RED )
      {
        // Anchored to a CSS value position - after a colon or a space inside a declaration - so
        // "required", "rendered", "border" and "reduce" cannot match. \b alone is not enough:
        // "border" contains no standalone "red", but "brown" would match inside "brownish" without
        // the trailing boundary, and `color:red` must match while `aria-required` must not.
        const asValue = new RegExp( `(?::|\\s)${name}\\s*(?:;|\\}|!|$)`, 'gmi' );
        expect( asValue.test( code ), `${file} declares the named colour ${name}` ).toBe( false );
      }
    }
  } );

  it( 'keeps the severity in the role rather than in the colour', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'requestOtp' ).mockRejectedValue( new Error( 'Enter a valid mobile number' ) );
    vi.stubGlobal( 'fetch', vi.fn() );

    render( <SignIn /> );
    fireEvent.change( screen.getByLabelText( 'WhatsApp number' ), { target: { value: '1' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );

    // An alert, not a colour. A reader who cannot see the tint still gets the interruption.
    const alert = await screen.findByRole( 'alert' );
    expect( alert.textContent ).toBeTruthy();
  } );
} );

describe( 'the money copy survived being shortened', () => {
  it( 'never claims nothing was charged on the status screen', () => {
    /*
     * THE INVARIANT THAT MATTERS MOST IN THIS FILE. The two states a visitor is most likely to land
     * on are "in flight" and "unknown", and in both of them the money may in fact have been
     * captured - the browser cannot tell. "No charge was made" there is the one wrong answer that
     * cannot be taken back, so it appears nowhere on this page in any state.
     */
    for ( const [ status, orderNumber ] of [
      [ 'PAYMENT_PENDING', null ], [ 'PAYMENT_PAID', null ], [ '', null ],
      [ 'PAYMENT_INITIATION_DISABLED', null ], [ 'WHAT_IS_THIS', null ],
      [ 'PAYMENT_FAILED', null ],
    ] as [ string, string | null ][] )
    {
      const { container, unmount } = render( <CheckoutStatus /> );
      // Rendered for the default view; the copy table is what is being asserted, via viewFor.
      expect( viewFor( status, orderNumber ) ).toBeTruthy();
      expect( container.textContent || '' ).not.toMatch( /no charge|not been charged|nothing was taken/i );
      unmount();
    }
    const source = read( 'src/pages/checkout/status.tsx' )
      .replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );
    expect( source.toLowerCase() ).not.toContain( 'no charge' );
  } );

  it( 'offers no retry for a paid, pending or unknown attempt', () => {
    // viewFor is the whole decision, so assert the mapping rather than six renders. Only 'failed'
    // may carry an action that starts a new checkout, and it is reached solely from a terminal
    // backend status.
    expect( viewFor( 'PAYMENT_PAID', null ) ).toBe( 'finalizing' );
    expect( viewFor( 'PAYMENT_PAID', 'WD-ORD-000123' ) ).toBe( 'confirming' );
    expect( viewFor( 'PAYMENT_PENDING', null ) ).toBe( 'confirming' );
    expect( viewFor( 'PAYMENT_REQUEST_SENT', null ) ).toBe( 'confirming' );
    expect( viewFor( 'PAYMENT_INITIATION_DISABLED', null ) ).toBe( 'unavailable' );
    expect( viewFor( undefined, null ) ).toBe( 'unavailable' );
    expect( viewFor( 'SOMETHING_NEW_FROM_THE_BACKEND', null ) ).toBe( 'unavailable' );
    for ( const terminal of [ 'PAYMENT_FAILED', 'PAYMENT_CANCELLED', 'PAYMENT_EXPIRED' ] )
    {
      expect( viewFor( terminal, null ) ).toBe( 'failed' );
    }
  } );

  it( 'keeps "Do not pay again" verbatim on the finalizing screen', () => {
    // The one sentence on that page that prevents a double charge. Shortening the copy around it is
    // fine; shortening it is not.
    expect( read( 'src/pages/checkout/status.tsx' ) ).toContain( 'Do not pay again.' );
  } );

  it( 'still says what the cart does and does not do', async () => {
    // The boundary note belongs to a cart with something in it; the empty state has nothing to make
    // a statement about.
    cartLib.addItem( KIOSK(), 1 );
    const { container } = render( <Cart /> );
    // The server decides the final total before payment. The page must not make
    // a blanket no-charge claim or display internal release flag commentary.
    await waitFor( () => expect( container.textContent || '' ).toContain( 'before payment' ) );
    expect( container.textContent || '' ).toMatch( /confirms your final total/ );
    expect( container.textContent || '' ).not.toMatch( /Live payment is not on yet|charges you nothing/ );
  } );
} );

describe( 'the country code is a segment of the one divided field, on owner instruction', () => {
  /*
   * THIS BLOCK HAS NOW BEEN REWRITTEN TWICE, BY THE SAME OWNER, AND BOTH REVERSALS ARE RECORDED
   * BECAUSE THE INVARIANT UNDERNEATH NEVER MOVED.
   *
   *   v1  a <select> BESIDE a national-number input - two visibly separate boxes.
   *   v2  "phone numbr and whatsapp ountrycode hsod in one feid" - one <input>, shopper types
   *       "+91 9876543210", page parses it, bare digits refused with MISSING_CODE.
   *   v3  "countcode + number should bin same dived divide and rounded corner" - one outlined
   *       container, divided by a hairline, holding a code segment and a number segment.
   *
   * THE INVARIANT, unchanged across all three: the country is never GUESSED from the digits.
   * customerAuth.normaliseMobile() turns any ten digits beginning 6-9 into a +91 number and is NOT
   * modified (it must match the backend byte for byte). v2 protected that with an error message. v3
   * protects it structurally, which is stronger: a code is always selected and on screen, so the
   * ten-digit inference can never be what decides the country. That is why MISSING_CODE is gone
   * rather than merely unused - see the note in sign-in.tsx's MSG.
   */
  const sendCode = (): void => {
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );
  };
  const typeNumber = ( value: string ): void => {
    fireEvent.change( screen.getByLabelText( 'WhatsApp number' ), { target: { value } } );
  };
  const pickCode = ( value: string ): void => {
    fireEvent.change( screen.getByLabelText( 'Calling code' ), { target: { value } } );
  };

  it( 'is one divided field: a code segment and a number segment, with no native validation', () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const { container } = render( <SignIn /> );

    const field = screen.getByLabelText( 'WhatsApp number' ) as HTMLInputElement;
    expect( field.tagName ).toBe( 'INPUT' );
    /*
     * NOT `required`, AND THAT IS THE FIX RATHER THAN A REGRESSION.
     *
     * `required` made the browser render its OWN validation bubble - "Please fill out this field."
     * with an orange warning icon - which the owner reported from the live sign-in page. That
     * bubble cannot be themed, cannot be translated by this site's text walker, and contradicts
     * the standing no-red instruction that stripped #fee2e2/#ef4444/#7f1d1d from these surfaces.
     * Emptiness is still caught - by the page's own submit path, surfaced through the in-page
     * error treatment (lime state tint, role=alert) and wired to the field with aria-invalid +
     * aria-describedby, so the message is themed, translatable and announced exactly once.
     * This assertion is inverted deliberately: if `required` comes back, the orange bubble does.
     */
    expect( field.required ).toBe( false );
    expect( field.type ).toBe( 'tel' );
    // EMPTY, not prefilled. v2 seeded "+91 " so the shape was visible; the code segment shows that
    // now, and a prefix sitting in the number box would be typed into twice.
    expect( field.value ).toBe( '' );
    // tel-national, because the browser is filling the number segment ONLY. "tel" here would offer
    // a full international number into a box that already has a code beside it.
    expect( field.getAttribute( 'autocomplete' ) ).toBe( 'tel-national' );

    // The code segment is a dedicated text/search input with a visible default - not a guess.
    // PhoneField deliberately avoids a native country dropdown so the divided field stays compact
    // and consistent in browsers/webviews while still keeping the calling code explicit.
    const code = screen.getByLabelText( 'Calling code' ) as HTMLInputElement;
    expect( code.tagName ).toBe( 'INPUT' );
    expect( code.value ).toBe( '+91' );

    /*
     * BOTH SEGMENTS SIT IN ONE CONTAINER, which is the whole point of the instruction. Asserted as
     * a shared parent rather than by reading CSS: jsdom computes no styles, so "looks like one
     * field" is not observable here - but "is inside one box" is, and if the two controls ever drift
     * into separate wrappers the divided look is gone whatever the CSS says.
     */
    const box = container.querySelector( '.pf' );
    expect( box ).not.toBeNull();
    expect( box!.contains( code ) ).toBe( true );
    expect( box!.contains( field ) ).toBe( true );
  } );

  it( 'uses the SELECTED code for bare national digits, never the inferred one', async () => {
    /*
     * THE LOAD-BEARING TEST OF THIS WHOLE BLOCK, and the one that replaces v2's refusal.
     *
     * "9876543210" is ten digits starting with 9, which is exactly the shape normaliseMobile()
     * rewrites to +91. With +971 selected the composed value must be +9719876543210 - thirteen
     * digits, so the inference cannot fire - and emphatically NOT +919876543210. A shopper in Dubai
     * being signed in as a non-existent Indian customer was the failure mode the separate select
     * existed to prevent, and it is prevented here by construction rather than by a message.
     */
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 's', destination: '****3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    pickCode( '+971' );
    typeNumber( '9876543210' );
    sendCode();
    await waitFor( () => expect( requestOtp ).toHaveBeenCalledWith( '+9719876543210' ) );
    expect( requestOtp ).not.toHaveBeenCalledWith( '+919876543210' );
  } );

  it( 'strips a domestic trunk zero rather than sending it to the gateway', async () => {
    // "09876543210" is how the same Indian number is dialled domestically. Prefixing the code
    // without dropping the zero would build +91098… , which is not a number.
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 's', destination: '****3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    typeNumber( '09876543210' );
    sendCode();
    await waitFor( () => expect( requestOtp ).toHaveBeenCalledWith( '+919876543210' ) );
  } );

  it( 'lets a PASTED international number override the selected code', async () => {
    /*
     * PEOPLE PASTE WHOLE NUMBERS, and this is the case that would otherwise corrupt them silently.
     * With +91 showing and "+971 50 123 4567" pasted into the number segment, blindly prefixing the
     * selection builds +91971501234567 - wrong in a way the shopper cannot spot, because both the
     * code they pasted and the code on screen look correct to them. A typed code therefore wins.
     * Spaces are not significant.
     */
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 's', destination: '****4567', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    // The selector is left on its +91 default on purpose - that is the conflict being tested.
    typeNumber( '+971 50 123 4567' );
    sendCode();
    await waitFor( () => expect( requestOtp ).toHaveBeenCalledWith( '+971501234567' ) );
    expect( requestOtp ).not.toHaveBeenCalledWith( '+91971501234567' );
  } );

  it( 'treats 00 as the international prefix', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 's', destination: '****3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    typeNumber( '0091 98765 43210' );
    sendCode();
    await waitFor( () => expect( requestOtp ).toHaveBeenCalledWith( '+919876543210' ) );
  } );

  it( 'rejects a number the E.164 rule cannot accept', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    typeNumber( '+9' );
    sendCode();
    await waitFor( () => expect( screen.getByText( 'Enter a valid number.' ) ).toBeTruthy() );
    expect( requestOtp ).not.toHaveBeenCalled();
  } );

  it( 'does NOT blame WhatsApp when the send fails, because the 502 cannot prove that', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: '', destination: '', expiresInSeconds: 0, registered: false,
    } );
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: false, status: 502, json: async () => ( { status: 'send_failed' } ),
    } ) );
    render( <SignIn /> );
    typeNumber( '+919876543210' );
    sendCode();
    // The front door's 502 also covers a transient Meta send failure, so the specific
    // "Use a WhatsApp number." claim would be a guess. The generic line is the honest one.
    await waitFor( () => expect(
      screen.getByText( 'Couldn\u2019t send a code. Check your number.' ) ).toBeTruthy() );
    expect( screen.queryByText( 'Use a WhatsApp number.' ) ).toBeNull();
  } );

  it( 'associates the error with the field so a correction is possible', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.stubGlobal( 'fetch', vi.fn() );
    render( <SignIn /> );
    /*
     * "+9" rather than the bare "501234567" this used to type. Bare national digits are no longer an
     * error at all - the code segment composes them - so the old trigger produced a valid number and
     * no message to associate with anything. "+9" is a typed code too short to be a number, which is
     * a refusal the divided field can still reach.
     */
    typeNumber( '+9' );
    sendCode();
    await waitFor( () => expect( screen.getByText( 'Enter a valid number.' ) ).toBeTruthy() );
    const field = screen.getByLabelText( 'WhatsApp number' );
    expect( field.getAttribute( 'aria-invalid' ) ).toBe( 'true' );
    // The hint stays in the description list alongside the error, so it is not lost.
    expect( field.getAttribute( 'aria-describedby' ) ).toBe( 'si-hint si-error' );
    // BOTH segments are marked, because the field is wrong as a whole rather than one half of it.
    expect( screen.getByLabelText( 'Calling code' ).getAttribute( 'aria-invalid' ) ).toBe( 'true' );
  } );
} );

describe( 'the cart keeps its own top band, and every Phase-2 addition lands BELOW it', () => {
  /**
   * T15, and the owner's top-band requirement guarded against a later refactor.
   *
   * Phase 2 creates no new page. /cart/ already carries a `PageTopBand` with its own heading and
   * sub in the home hero's visual language, and the three routes the brief also names -
   * /checkout/status/, /checkout/success/ and /account/sign-in/ - already carry one with
   * per-outcome content. So the requirement is met by NOT REGRESSING it, which is a thing a test
   * can hold and a comment cannot: the cases above already drive all four pages through the same
   * band matrix, and keeping them green with NO edit to those pages is what makes them
   * verified-unchanged rather than merely unedited.
   *
   * The new work here is the second case: every Phase-2 addition - the mixed-basket notice, the
   * contribution amount row, the new outcome copy, the "Start a new cart" control - must render as
   * a descendant of the band's `children` and NOT inside `.ptb-top`. The band states what the page
   * is; it carries no CTA, no price and no conversion furniture.
   */
  it( 'renders exactly one h1, inside the band, with the cart\'s own heading and sub', () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const { container } = render( <Cart /> );
    const h1s = container.querySelectorAll( 'h1' );
    expect( h1s ).toHaveLength( 1 );
    expect( h1s[ 0 ].textContent ).toBe( 'Your cart' );
    // Inside the band, not merely on the page.
    expect( container.querySelector( '.ptb-top h1' ) ).not.toBeNull();
    // Its own sub, page-specific rather than generic. Still accurate for a contribution basket:
    // a contribution IS in the cart.
    expect( container.textContent )
      .toContain( 'Review what you have added before you check out.' );
  } );

  it( 'puts no cart control, notice or amount field inside .ptb-top', () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    // A basket that exercises the contribution row and the mixed-basket notice together.
    cartLib.clearCart();
    cartLib.setContribution( CONTRIBUTION_CHOICES[ 1 ].variantId );
    cartLib.addItem( KIOSK(), 1 );
    const { container } = render( <Cart /> );
    const band = container.querySelector( '.ptb-top' ) as HTMLElement;
    expect( band ).not.toBeNull();

    // Nothing actionable and nothing money-shaped in the band itself.
    expect( band.querySelectorAll( 'button' ) ).toHaveLength( 0 );
    expect( band.querySelectorAll( 'input' ) ).toHaveLength( 0 );
    expect( band.querySelectorAll( 'a' ) ).toHaveLength( 0 );
    expect( band.textContent || '' ).not.toMatch( /\u20B9/ );
    expect( band.textContent || '' ).not.toMatch( /Amount in rupees/ );
    expect( band.textContent || '' ).not.toMatch( /paid on its own/ );

    // And the additions really are on the page, below it - so this is not passing vacuously.
    expect( container.querySelectorAll( 'input' ).length ).toBeGreaterThan( 0 );
    cartLib.clearCart();
  } );

  it( 'leaves the checkout pages and sign-in untouched, which is why their cases still pass', () => {
    // A source pin on the three routes the brief names but the design puts no code change on. If
    // a future edit moves a band on any of them, this fails beside the matrix above rather than
    // leaving "verified unchanged" as an unchecked claim.
    for ( const relative of [
      'src/pages/checkout/status.tsx',
      'src/pages/checkout/success.tsx',
      'src/pages/account/sign-in.tsx',
      'src/components/PageTopBand.tsx',
    ] )
    {
      const source = fs.readFileSync( path.resolve( __dirname, '../..', relative ), 'utf8' );
      // Each still mounts the STATIC band, never the rotating marketing hero: content that moves
      // automatically for over 5s with no pause mechanism is a WCAG 2.2.2 failure, and four cycle
      // words above a screen a customer is reading to find out whether their money moved would be
      // invented marketing copy.
      if ( relative !== 'src/components/PageTopBand.tsx' )
      {
        expect( source, relative ).toMatch( /<PageTopBand/ );
      }
      // `PageTopBand.tsx` itself NAMES `RotatingHero` in its header, where it explains why it
      // omits the rotation -- a WCAG 2.2.2 pause failure, plus invented marketing copy above a
      // screen a customer is reading to find out whether their money moved. A page MOUNTING it is
      // the thing being refused, so the check is scoped to the pages.
      if ( relative !== 'src/components/PageTopBand.tsx' )
      {
        expect( source, relative ).not.toMatch( /RotatingHero/ );
      }
      // And no contribution code leaked into any of them.
      expect( source, relative ).not.toMatch( /[Cc]ontribution/ );
    }
  } );
} );
