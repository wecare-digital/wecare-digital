import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * ALL PAGE-LEVEL COVERAGE FOR /orders/ LANDS HERE, and the containment is deliberate.
 *
 * `src/test/PublicPageTopBand.test.tsx` is Phase 2's file by its own file map, and
 * `src/test/LogicalDirectionCss.test.tsx` reads only `src/styles/*.css` by design, so it cannot
 * see a styled-jsx rule. Three of the band gates are file-driven off lists in that Phase 2 file
 * (hand-rolled clearance, retired palette, the red sweep); rather than edit a file another
 * session owns, they are reimplemented here over this one page. Everything else that file
 * asserts is either a hardcoded case array or a test of PageTopBand itself, and is
 * page-independent.
 */

/**
 * THE FLAG SEAM. `vi.mock` is hoisted above the imports, so the factory has to close over a
 * `vi.hoisted()` object - a plain `const` would still be in TDZ when the factory runs.
 *
 * It deliberately does NOT spread the real module: the point is to control the value, and a
 * spread of a `const` object re-introduces the real flag. It is also never reset with
 * `vi.resetModules` mid-file, because the page is imported once at the top, as it is today.
 *
 * Default `false`, which is the SHIPPED state. Each invoice-facing describe sets what it needs
 * in its own `beforeEach`.
 */
const flags = vi.hoisted( () => ( { invoiceDownload: false } ) );
vi.mock( '../config/featureFlags', () => ( { featureFlags: flags } ) );

// The page reads getSession/restoreSession/clearSession and nothing else from customerAuth. The
// module is mocked rather than the storage behind it, because this suite is about what the page
// does with a session, not about how a session is persisted.
const getSession = vi.fn();
const restoreSession = vi.fn();
const clearSession = vi.fn();

vi.mock( '../lib/customerAuth', () => ( {
  getSession: () => getSession(),
  restoreSession: () => restoreSession(),
  clearSession: () => clearSession(),
} ) );

/**
 * CheckoutProfile is STUBBED, and the stub is what makes the H1 regression testable.
 *
 * The real component owns an email-verification round trip of its own; mounting it here would
 * test that flow a second time. What this page is responsible for is narrower and is exactly
 * what the stub exposes: the editor reports a saved value, and the page must decide the
 * `emailVerified` flag from the MODE THAT COMPLETED rather than from the saved value - which
 * carries no such member. The stub therefore renders one button per completion and echoes back
 * the mode it was mounted with.
 */
vi.mock( '../components/CheckoutProfile', () => ( {
  __esModule: true,
  default: ( { mode, initial, onReady }: any ) => (
    <button
      type="button"
      data-testid="profile-save"
      data-mode={ mode }
      onClick={ () => onReady( {
        contactId: 'c1',
        name: 'Rahul Sharma',
        firstName: initial?.firstName || 'Rahul',
        lastName: initial?.lastName || 'Sharma',
        // A NEW address on an 'email' save, so the test cannot pass by the saved value
        // happening to equal the old one.
        email: mode === 'email' ? 'new@example.com' : ( initial?.email || 'rahul@example.com' ),
        phone: '+918100640044',
        addressComplete: !!initial?.address,
        address: initial?.address || null,
      } ) }
    >
      Save { mode }
    </button>
  ),
} ) );

import OrdersPage from '../pages/orders';

const PAGE_PATH = resolve( process.cwd(), 'src/pages/orders.tsx' );
const SOURCE = readFileSync( PAGE_PATH, 'utf8' );

/**
 * Comments stripped before any pattern sweep. Every one of the sweeps below looks for a string
 * that this page's own docblocks legitimately discuss - the retired red hexes are named in a
 * comment explaining that they are retired, and `border-left` is named in a comment saying not
 * to use it. Sweeping the raw text would fail on the explanation rather than on the code.
 */
const CODE = SOURCE.replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );

interface Row {
  orderNumber?: string;
  referenceId?: string;
  createdAt?: number | null;
  amountPaise?: number | null;
  currency?: string;
  currencyUnexpected?: boolean;
  status?: string;
  statusRank?: number;
}

function row ( over: Row = {} ) {
  return {
    orderNumber: 'WD-1042',
    referenceId: 'ref-1',
    createdAt: 1759000000,
    amountPaise: 121481,
    currency: 'INR',
    currencyUnexpected: false,
    status: 'captured',
    statusRank: 40,
    ...over,
  };
}

function profile ( over: Record<string, unknown> = {} ) {
  return {
    name: 'Rahul Sharma',
    firstName: 'Rahul',
    lastName: 'Sharma',
    email: 'rahul@example.com',
    emailVerified: true,
    phone: '+918100640044',
    addressComplete: true,
    address: {
      addressLine1: '12 MG Road',
      addressLine2: '',
      locality: '',
      city: 'Bengaluru',
      state: 'Karnataka',
      postalCode: '560001',
      country: 'India',
      countryCode: 'IN',
      fullAddress: '12 MG Road, Bengaluru, Karnataka, 560001, India',
    },
    ...over,
  };
}

/**
 * The date the fixture epoch must render as, computed the same way the page computes it. The
 * point of the page's formatting is that it happens in the reader's own zone, so pinning a
 * literal here would assert the suite's timezone instead of the page's behaviour.
 */
const EXPECTED_DATE = new Date( 1759000000 * 1000 )
  .toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: 'numeric' } );

/** A fetch answer. `body` is serialised, so a test cannot accidentally share a mutable row. */
function answer ( status: number, body: unknown ) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => JSON.parse( JSON.stringify( body ) ),
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach( () => {
  getSession.mockReset().mockReturnValue( null );
  restoreSession.mockReset().mockResolvedValue( null );
  clearSession.mockReset();
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
} );

/** A live session, so the mount effect proceeds to the first read. */
function withSession () {
  getSession.mockReturnValue( { accessToken: 'tok', expiresAt: Date.now() + 3_600_000 } );
}

/** Render and settle the mount effect's promise chain. */
async function renderSignedIn ( ...answers: ReturnType<typeof answer>[] ) {
  withSession();
  answers.forEach( a => fetchMock.mockResolvedValueOnce( a ) );
  const view = render( <OrdersPage /> );
  await waitFor( () => expect( fetchMock ).toHaveBeenCalled() );
  return view;
}

describe( '/orders/ — structure and the top band', () => {
  it( 'renders exactly one h1 and one main, and the h1 is the band heading', () => {
    const { container } = render( <OrdersPage /> );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
    expect( container.querySelector( 'h1' )!.textContent ).toBe( 'Your orders' );
  } );

  it( 'puts nothing conversion-shaped inside the band block itself', () => {
    // .ptb-top holds only the h1 and the sub-line; children render outside it. So this can only
    // fail on something passed through `sub`, which is a ReactNode - narrow, not vacuous.
    const { container } = render( <OrdersPage /> );
    const top = container.querySelector( '.ptb-top' )!;
    expect( top.querySelectorAll( 'button, a' ) ).toHaveLength( 0 );
    expect( top.textContent ).not.toContain( '₹' );
  } );

  it( 'mounts the static PageTopBand and hand-rolls no header clearance', () => {
    expect( SOURCE ).toContain( '<PageTopBand' );
    // The two header heights, asserted as CLEARANCE rather than as the bare numbers: `96px` on
    // its own is also a legitimate grid track width in this file (.ord-facts), so banning the
    // string would fail on a column rather than on a duplicated header offset.
    expect( CODE ).not.toMatch( /(?:padding|margin)(?:-block)?-?(?:top|start)?\s*:\s*(?:108|96)px/ );
    expect( CODE ).not.toMatch( /calc\(\s*100(?:v|d)h\s*-/ );
    expect( CODE ).not.toContain( 'RotatingHero' );
  } );

  it( 'uses no retired red, in any notation', () => {
    expect( CODE ).not.toContain( '#b91c1c' );
    expect( CODE ).not.toContain( '#fef2f2' );
    expect( CODE ).not.toContain( '#ef4444' );
    // Every hex in the file, judged by its channels rather than by a prefix. A prefix pattern
    // cannot tell #ef4444 from #e5e7eb or #fff, so it either misses the reds or fails on the
    // page's own hairline and its white - which is what makes this the asserting form.
    for ( const hex of CODE.match( /#[0-9a-f]{3}(?:[0-9a-f]{3})?\b/gi ) || [] )
    {
      const full = hex.length === 4
        ? hex.slice( 1 ).split( '' ).map( c => c + c ).join( '' )
        : hex.slice( 1 );
      const [ r, g, b ] = [ 0, 2, 4 ].map( i => parseInt( full.slice( i, i + 2 ), 16 ) );
      expect( r >= 150 && r - g >= 60 && r - b >= 60, `${ hex } reads as red` ).toBe( false );
    }
    expect( CODE ).not.toMatch( /\brgba?\(\s*(?:1[6-9]\d|2[0-5]\d)\s*,\s*[0-5]?\d\s*,/i );
    expect( CODE ).not.toMatch( /\bhsla?\(\s*(?:[0-9]|1[0-9]|3[4-9]\d|35\d)\s*,/i );
    expect( CODE ).not.toMatch( /:\s*(?:red|crimson|firebrick|tomato|indianred|darkred)\b/i );
  } );

  /**
   * THE SIGNED-IN HERO, WHICH NOTHING PINNED BEFORE THIS.
   *
   * `PageTopBand` is the outermost element of this page's `return` and wraps `.ord-page`
   * entirely, so the hero renders in every view - but the one-h1/one-main test above only ever
   * exercises the SIGNED-OUT render, because it renders with no session. The two-column
   * restructure happens inside `.ord-page`, so the band cannot be dropped unless the band
   * itself is moved; this is the test that fails if a later edit moves or conditionally
   * renders it. Both halves must be green, which is the point of having two.
   */
  it( 'keeps the hero in the signed-in render, not just the signed-out one', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelector( 'h1' )!.textContent ).toBe( 'Your orders' );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
    const top = container.querySelectorAll( '.ptb-top' );
    expect( top ).toHaveLength( 1 );
    expect( screen.getByText(
      'What you have bought from us, and what each payment is doing.' ) ).toBeInTheDocument();
    // Still nothing conversion-shaped inside the band, now that the body below it holds a table.
    expect( top[ 0 ].querySelectorAll( 'button, a' ) ).toHaveLength( 0 );
    expect( top[ 0 ].textContent ).not.toContain( '₹' );
  } );
} );

describe( '/orders/ — the two-column layout', () => {
  it( 'names the panel without adding a heading to it', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const panel = container.querySelector( '[aria-label="Your details"]' )!;
    expect( panel ).toBeTruthy();
    expect( panel.tagName ).toBe( 'ASIDE' );
    expect( panel.querySelector( 'h1, h2, h3, h4, h5, h6' )!.textContent )
      .toBe( 'What we have on file' );
    // The card renders INSIDE it, and the h2 ladder is unchanged by the panel existing.
    expect( panel.textContent ).toContain( 'rahul@example.com' );
    const h2 = Array.from( container.querySelectorAll( 'h2' ) ).map( h => h.textContent );
    expect( h2 ).toEqual( [ 'What we have on file', 'Order history' ] );
  } );

  it( 'declares minmax(0,1fr) on the right column inside the 1024px query', () => {
    // minmax(0,...) is what keeps document.documentElement.scrollWidth - vw at 0: a bare `1fr`
    // is minmax(auto,1fr), refuses to shrink, and hands the overflow to the DOCUMENT, which is
    // what tools/browser/devicecheck.js fails on at 280px.
    expect( CODE ).toMatch(
      /@media\(min-width:1024px\)\{[\s\S]*?grid-template-columns:340px minmax\(0,1fr\)/ );
    expect( CODE ).toMatch(
      /@media\(min-width:1024px\)\{[\s\S]*?\.ord-shell-editing\{grid-template-columns:1fr\}/ );
    expect( CODE ).toContain( 'min-inline-size:0' );
  } );

  it( 'is one column by default, with the panel ahead of the orders in DOM order', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( CODE ).toContain( '.ord-shell{display:grid;grid-template-columns:1fr' );
    const shell = container.querySelector( '.ord-shell' )!;
    const children = Array.from( shell.children ).map( node => node.className );
    // DOM order equals visual order at every width, so there is no `order:` property anywhere.
    expect( children ).toEqual( [ 'ord-panel', 'ord-main' ] );
    expect( CODE ).not.toMatch( /[;{\s]order\s*:\s*-?\d/ );
  } );

  it( 'collapses the shell to one column while the editor is open, and back when it closes',
    async () => {
      const { container } = await renderSignedIn( answer( 200, {
        orders: [ row() ], profile: profile(),
      } ) );
      await screen.findByText( 'rahul@example.com' );
      expect( container.querySelector( '.ord-shell' )!.className ).toBe( 'ord-shell' );
      fireEvent.click( screen.getByRole( 'button', { name: 'Edit name' } ) );
      await screen.findByTestId( 'profile-save' );
      expect( container.querySelector( '.ord-shell' )!.className )
        .toBe( 'ord-shell ord-shell-editing' );
      fireEvent.click( screen.getByTestId( 'profile-save' ) );
      await waitFor( () => expect( screen.queryByTestId( 'profile-save' ) ).toBeNull() );
      expect( container.querySelector( '.ord-shell' )!.className ).toBe( 'ord-shell' );
    } );

  it( 'widens the measure to 1100px and keeps declaring the colour scheme', () => {
    expect( CODE ).toContain( 'max-width:1100px' );
    expect( CODE ).not.toContain( 'max-width:700px' );
    expect( CODE ).toMatch( /color-scheme\s*:\s*light/ );
  } );
} );

describe( '/orders/ — static source gates', () => {
  it( 'declares no physical direction property', () => {
    for ( const physical of [
      'border-left', 'border-right', 'margin-left', 'margin-right',
      'padding-left', 'padding-right',
    ] )
    {
      expect( CODE ).not.toContain( physical );
    }
    // A bare `left:` / `right:` offset, which `border-inline-start` is the correct form of.
    expect( CODE ).not.toMatch( /[;{\s]left\s*:/ );
    expect( CODE ).not.toMatch( /[;{\s]right\s*:/ );
  } );

  it( 'cannot clip on increased text spacing', () => {
    // WCAG 1.4.12 is Level AA and the failure mode is a clipped or fixed-height box. This page
    // has neither, and that is what the assertion keeps true.
    expect( CODE ).not.toMatch( /overflow\s*:\s*hidden/ );
    expect( CODE ).not.toMatch( /[;{\s]height\s*:\s*\d/ );
  } );

  it( 'declares the colour scheme rather than letting a browser infer one', () => {
    expect( CODE ).toMatch( /color-scheme\s*:\s*light/ );
  } );

  it( 'declares the font stack on its own heading and body rungs', () => {
    // Inheriting leaves a lockup on a serif when the global body rule is absent. The DECLARING
    // rule is the one that opens the selector at the start of a line - `.ord-h2` also appears in
    // a later descendant rule that only resets a margin, which legitimately carries no font.
    for ( const selector of [ '.ord-h2{', '.ord-p,.ord-aside{' ] )
    {
      const body = CODE.slice( CODE.indexOf( selector ) + selector.length, );
      expect( body.slice( 0, body.indexOf( '}' ) ) ).toContain( "'Inter'" );
    }
  } );

  it( 'clears both tap-target floors, read from every style element', () => {
    // One querySelector('style') returns whichever is first in the container, and PillButton's
    // styled-jsx is a SEPARATE element from the page's own - so a single read asserts against
    // one of two stylesheets and passes or fails for the wrong reason.
    const { container } = render( <OrdersPage /> );
    const css = Array.from( container.querySelectorAll( 'style' ) )
      .map( node => node.textContent || '' ).join( '\n' );
    expect( css ).toContain( 'min-height:44px' );
    expect( css ).toContain( 'min-height:52px' );
  } );
} );

describe( '/orders/ — the signed-out gate', () => {
  it( 'renders signed-out with no session and issues no request at all', async () => {
    render( <OrdersPage /> );
    await waitFor( () => expect( restoreSession ).toHaveBeenCalled() );
    expect( fetchMock ).not.toHaveBeenCalled();
    expect( screen.getByText( /Sign in on your WhatsApp number/ ) ).toBeInTheDocument();
  } );

  it( 'links into the existing sign-in flow carrying the return path', () => {
    render( <OrdersPage /> );
    const link = screen.getByRole( 'link', { name: /Sign in on WhatsApp/ } );
    expect( link ).toHaveAttribute( 'href', '/account/sign-in/?return=/orders/' );
    expect( link.textContent ).toBe( 'Sign in on WhatsApp' );
  } );

  it( 'says nothing about OTP anywhere a customer can read it', () => {
    // "OTP" is the mechanism's name, not customer copy, and this control sends no code.
    const { container } = render( <OrdersPage /> );
    expect( container.textContent ).not.toContain( 'OTP' );
  } );

  it( 'never renders loading as the first paint', () => {
    // The page is public and indexed. A `loading` first render would index "Loading…".
    const { container } = render( <OrdersPage /> );
    expect( container.textContent ).not.toContain( 'Loading your orders' );
  } );
} );

describe( '/orders/ — the order list', () => {
  it( 'renders number, date, amount and status for a row', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    await screen.findByText( 'WD-1042' );
    expect( screen.getByText( '₹1,214.81' ) ).toBeInTheDocument();
    expect( screen.getByText( 'Paid' ) ).toBeInTheDocument();
    // DERIVED, not pinned to a literal. The epoch is formatted in the BROWSER's zone so an IST
    // reader sees their own day, which is the behaviour being asserted - a hardcoded "28 Sept"
    // would pass or fail on the machine the suite happens to run in rather than on the page.
    expect( screen.getByText( EXPECTED_DATE ) ).toBeInTheDocument();
  } );

  it( 'formats integer paise exactly, with Indian grouping', async () => {
    await renderSignedIn( answer( 200, {
      orders: [ row( { amountPaise: 100, referenceId: 'a' } ), row( { amountPaise: 121481, orderNumber: 'WD-2', referenceId: 'b' } ) ],
      profile: profile(),
    } ) );
    expect( await screen.findByText( '₹1.00' ) ).toBeInTheDocument();
    expect( screen.getByText( '₹1,214.81' ) ).toBeInTheDocument();
  } );

  it( 'refuses to render a missing amount as money', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { amountPaise: null } ) ], profile: profile(),
    } ) );
    expect( await screen.findByText( 'Amount unavailable' ) ).toBeInTheDocument();
    expect( container.textContent ).not.toContain( '₹' );
  } );

  it( 'refuses a foreign currency rather than putting a rupee sign over it', async () => {
    // Compared explicitly, never inferred from the amount.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { currency: 'USD', currencyUnexpected: true } ) ], profile: profile(),
    } ) );
    expect( await screen.findByText( 'Amount unavailable' ) ).toBeInTheDocument();
    expect( container.textContent ).not.toContain( '₹' );
  } );

  it( 'reads the status through the canonical map, and says so when it cannot', async () => {
    await renderSignedIn( answer( 200, {
      orders: [ row( { status: '' } ) ], profile: profile(),
    } ) );
    expect( await screen.findByText( 'Status unavailable' ) ).toBeInTheDocument();
    expect( screen.getByText( 'Contact us and we will check.' ) ).toBeInTheDocument();
  } );

  it( 'renders no date line rather than an Invalid Date', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { createdAt: null } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.textContent ).not.toContain( 'Invalid Date' );
    expect( container.querySelector( '.ord-date' ) ).toBeNull();
  } );

  it( 'flags the identifier and the amount against translation, but not the date', async () => {
    // SupportWidget rewrites text-node values. A regrouped amount would make this page lie about
    // money; a localised month name is an improvement and no decision depends on its spelling.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelector( '.ord-itemh' ) ).toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( '.ord-amount' ) ).toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( '.ord-date' ) ).not.toHaveAttribute( 'data-wc-no-translate' );
  } );

  it( 'leaves "Amount unavailable" translatable, because it is prose', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { amountPaise: null } ) ], profile: profile(),
    } ) );
    const dd = await screen.findByText( 'Amount unavailable' );
    expect( dd.getAttribute( 'data-wc-no-translate' ) ).toBeNull();
    expect( container.querySelector( '.ord-amount' ) ).toBeNull();
  } );

  it( 'falls back from order number to reference to date for the row heading', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [
        row( { orderNumber: '', referenceId: 'REF-9' } ),
        row( { orderNumber: '', referenceId: '', createdAt: 1759000000 } ),
      ],
      profile: profile(),
    } ) );
    await waitFor( () => expect( container.querySelectorAll( 'h3' ) ).toHaveLength( 2 ) );
    const headings = Array.from( container.querySelectorAll( 'h3' ) ).map( h => h.textContent );
    expect( headings[ 0 ] ).toBe( 'REF-9' );
    expect( headings[ 1 ] ).toBe( EXPECTED_DATE );
  } );

  it( 'renders only the two expected h2 rungs', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const h2 = Array.from( container.querySelectorAll( 'h2' ) ).map( h => h.textContent );
    expect( h2 ).toEqual( [ 'What we have on file', 'Order history' ] );
  } );
} );

describe( '/orders/ — pagination', () => {
  it( 'offers "Show more orders" only when the response carried a cursor', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    await screen.findByText( 'WD-1042' );
    // Absent from the DOM, not hidden: a hidden control is still a tab stop.
    expect( screen.queryByRole( 'button', { name: 'Show more orders' } ) ).toBeNull();
  } );

  it( 'appends a second page and keeps the button while a cursor remains', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockResolvedValueOnce( answer( 200, {
      orders: [ row( { orderNumber: 'WD-2', referenceId: 'ref-2' } ) ], cursor: 'c2',
    } ) );
    fireEvent.click( more );
    expect( await screen.findByText( 'WD-2' ) ).toBeInTheDocument();
    expect( screen.getByText( 'WD-1042' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'button', { name: 'Show more orders' } ) ).toBeInTheDocument();
  } );

  it( 'drops the button silently on an empty cursored page, and does not re-ask', async () => {
    // DynamoDB hands out a cursor whenever a query stops at Limit, so a customer with exactly 20
    // orders gets one. There is no "no more orders" message because there is nothing to tell
    // them - and this is NOT the empty-first-page branch, so the one-shot re-ask must not fire.
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockResolvedValueOnce( answer( 200, { orders: [] } ) );
    fireEvent.click( more );
    await waitFor( () => expect(
      screen.queryByRole( 'button', { name: 'Show more orders' } ) ).toBeNull() );
    expect( screen.getByText( 'WD-1042' ) ).toBeInTheDocument();
    expect( screen.queryByText( /no more orders/i ) ).toBeNull();
    await act( async () => { vi.advanceTimersByTime( 10_000 ); } );
    expect( fetchMock ).toHaveBeenCalledTimes( 2 );
  } );

  it( 'keeps the rows and the button when a second page fails', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockResolvedValueOnce( answer( 503, {} ) );
    fireEvent.click( more );
    await waitFor( () => expect(
      screen.getByText( /could not load your orders/ ) ).toBeInTheDocument() );
    expect( screen.getByText( 'WD-1042' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'button', { name: 'Show more orders' } ) ).toBeInTheDocument();
  } );

  it( 'leaves the identity card alone when a cursored response omits profile', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockResolvedValueOnce( answer( 200, {
      orders: [ row( { orderNumber: 'WD-2', referenceId: 'ref-2' } ) ],
    } ) );
    fireEvent.click( more );
    await screen.findByText( 'WD-2' );
    // `undefined` means "not answered on this request", never "no contact row".
    expect( screen.getByText( 'rahul@example.com' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'heading', { name: 'What we have on file' } ) ).toBeInTheDocument();
  } );
} );

describe( '/orders/ — the empty state', () => {
  it( 'describes the absence without asserting that nothing was bought', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    await renderSignedIn( answer( 200, { orders: [], profile: profile() } ) );
    await screen.findByText( /Checking for recent orders/ );
    fetchMock.mockResolvedValueOnce( answer( 200, { orders: [], profile: profile() } ) );
    await act( async () => { vi.advanceTimersByTime( 5_000 ); } );
    expect( await screen.findByRole( 'heading', { name: 'No orders yet' } ) ).toBeInTheDocument();
    // Finalization can stage PURCHASED_SNAPSHOT_MISSING and return before the order write, so a
    // captured payment can leave no order row at all. This page must not claim otherwise.
    expect( screen.getByText( /Ordered over WhatsApp/ ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: /Shop/ } ) ).toBeInTheDocument();
  } );

  it( 're-asks exactly once, then stops', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    await renderSignedIn( answer( 200, { orders: [], profile: profile() } ) );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
    fetchMock.mockResolvedValueOnce( answer( 200, { orders: [], profile: profile() } ) );
    await act( async () => { vi.advanceTimersByTime( 5_000 ); } );
    expect( fetchMock ).toHaveBeenCalledTimes( 2 );
    await act( async () => { vi.advanceTimersByTime( 60_000 ); } );
    expect( fetchMock ).toHaveBeenCalledTimes( 2 );
  } );

  it( 'shows a neutral checking line on a status element during the window', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    const { container } = await renderSignedIn( answer( 200, { orders: [], profile: profile() } ) );
    const checking = await screen.findByText( /Checking for recent orders/ );
    expect( checking ).toHaveAttribute( 'role', 'status' );
    // The common visitor on this branch has never bought anything, so a confident "your order is
    // being confirmed" would be wrong for most of them.
    expect( container.textContent ).not.toContain( 'being confirmed' );
  } );

  it( 'issues no second read when the page is left inside the window', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    const { unmount } = await renderSignedIn( answer( 200, { orders: [], profile: profile() } ) );
    await screen.findByText( /Checking for recent orders/ );
    unmount();
    await act( async () => { vi.advanceTimersByTime( 10_000 ); } );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'renders the order list and the empty state as alternatives, never together', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    await screen.findByText( 'WD-1042' );
    expect( screen.queryByRole( 'heading', { name: 'No orders yet' } ) ).toBeNull();
  } );
} );

describe( '/orders/ — the identity card', () => {
  it( 'renders the card with the orders-side copy', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    expect( await screen.findByText( 'Your details' ) ).toBeInTheDocument();
    expect( screen.getByRole( 'heading', { name: 'What we have on file' } ) ).toBeInTheDocument();
    expect( screen.queryByText( 'Checkout details' ) ).toBeNull();
    expect( screen.queryByText( 'Ready to pay' ) ).toBeNull();
  } );

  it( 'puts no verified badge beside an email nothing proved', async () => {
    // This page's server-side predicate answers "is this the caller's contact row", not "is this
    // email proven", so the badge must be suppressed rather than assumed.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile( { emailVerified: false } ),
    } ) );
    await screen.findByText( 'rahul@example.com' );
    const email = screen.getByText( 'Email' ).parentElement!;
    expect( email.querySelector( '.identity-badge' ) ).toBeNull();
    // The phone badge is unconditional: the session proves the number.
    const phone = screen.getByText( 'Phone' ).parentElement!;
    expect( phone.querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
    expect( container.textContent ).toContain( '✓ verified' );
  } );

  it( 'keeps the badge when the email was proved', async () => {
    await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile( { emailVerified: true } ),
    } ) );
    await screen.findByText( 'rahul@example.com' );
    const email = screen.getByText( 'Email' ).parentElement!;
    expect( email.querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
  } );

  it( 'says there is no address on file rather than showing a partial one', async () => {
    await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile( { addressComplete: false } ),
    } ) );
    expect( await screen.findByText( 'No address on file' ) ).toBeInTheDocument();
  } );

  it( 'renders no card and routes to the cart when there is no contact row', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: null } ) );
    await screen.findByText( 'WD-1042' );
    expect( screen.queryByRole( 'heading', { name: 'What we have on file' } ) ).toBeNull();
    expect( screen.getByText( /We do not have your details yet/ ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'cart' } ) ).toHaveAttribute( 'href', '/cart/' );
  } );
} );

/**
 * THE DESIGN REVIEW'S HIGH, ASSERTED IN BOTH DIRECTIONS.
 *
 * `CheckoutProfileValue` has no `emailVerified` member, so spreading a saved value into the
 * card's `identity` left the flag `undefined`, `undefined !== false` is true, and "✓ verified"
 * came back over an email nothing had verified. The flag must therefore come from the MODE that
 * completed: 'email' completes only against a fresh code bound to the new address and should
 * flip it true; 'name' and 'address' post no code at all and must leave it exactly as it was.
 */
describe( '/orders/ — a profile edit and the verified badge', () => {
  async function openEditor ( button: string, emailVerified: boolean ) {
    await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile( { emailVerified } ),
    } ) );
    await screen.findByText( 'rahul@example.com' );
    fireEvent.click( await screen.findByRole( 'button', { name: button } ) );
    return screen.findByTestId( 'profile-save' );
  }

  function emailBadge () {
    return screen.getByText( 'Email' ).parentElement!.querySelector( '.identity-badge' );
  }

  it( 'does not make the badge reappear after a name edit', async () => {
    const save = await openEditor( 'Edit name', false );
    expect( save ).toHaveAttribute( 'data-mode', 'name' );
    fireEvent.click( save );
    await waitFor( () => expect( screen.queryByTestId( 'profile-save' ) ).toBeNull() );
    expect( emailBadge() ).toBeNull();
  } );

  it( 'does not make the badge reappear after an address edit', async () => {
    const save = await openEditor( 'Edit address', false );
    expect( save ).toHaveAttribute( 'data-mode', 'address' );
    fireEvent.click( save );
    await waitFor( () => expect( screen.queryByTestId( 'profile-save' ) ).toBeNull() );
    expect( emailBadge() ).toBeNull();
  } );

  it( 'keeps a proved badge across a name edit', async () => {
    const save = await openEditor( 'Edit name', true );
    fireEvent.click( save );
    await waitFor( () => expect( screen.queryByTestId( 'profile-save' ) ).toBeNull() );
    expect( emailBadge()!.textContent ).toBe( '✓ verified' );
  } );

  it( 'badges the new address only after an email change, which required a fresh code', async () => {
    const save = await openEditor( 'Change email', false );
    expect( save ).toHaveAttribute( 'data-mode', 'email' );
    fireEvent.click( save );
    await screen.findByText( 'new@example.com' );
    expect( emailBadge()!.textContent ).toBe( '✓ verified' );
  } );

  it( 'locks the three affordances while the editor is open', async () => {
    await openEditor( 'Edit name', true );
    expect( screen.getByRole( 'button', { name: 'Edit name' } ) ).toBeDisabled();
    expect( screen.getByRole( 'button', { name: 'Change email' } ) ).toBeDisabled();
    expect( screen.getByRole( 'button', { name: 'Edit address' } ) ).toBeDisabled();
  } );
} );

/**
 * THE EDIT POLICY: NAME AND EMAIL ARE EDITABLE, THE PHONE IS NOT.
 *
 * This is already the implemented behaviour and it is structural rather than conventional -
 * `CheckoutIdentityCard` declares exactly `onEditName`, `onChangeEmail` and `onEditAddress`, and
 * `CheckoutProfileMode` has no 'phone' member, so there is no prop to pass and no mode to open.
 * These three tests are what stop a later edit adding one, because "we did not build it" is not
 * a guarantee.
 *
 * The phone IS the identity: sign-in is a WhatsApp OTP on that number against a phone-keyed
 * CUSTOM_AUTH pool, and the card's "✓ verified" badge is unconditional because of it. A
 * self-service phone edit would let a signed-in session rewrite the credential that session was
 * issued against - an account-takeover shape, not a profile edit - and the badge would become a
 * false claim the moment it shipped.
 *
 * Equality, not containment: a containment assertion passes while the surface grows.
 */
describe( '/orders/ — the profile panel edit policy', () => {
  it( 'renders exactly three edit controls, and they are these three', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'rahul@example.com' );
    const panel = container.querySelector( '[aria-label="Your details"]' )!;
    const names = Array.from( panel.querySelectorAll( 'button' ) )
      .map( node => ( node.getAttribute( 'aria-label' ) || node.textContent || '' ).trim() );
    expect( names ).toEqual( [ 'Edit name', 'Change email', 'Edit address' ] );
  } );

  it( 'shows the phone with its badge and offers no control that could change it', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'rahul@example.com' );
    const panel = container.querySelector( '[aria-label="Your details"]' )!;
    const phoneRow = screen.getByText( 'Phone' ).parentElement!;
    // Masked by the card's own maskPhone, which this page does not override.
    expect( phoneRow.textContent ).toMatch( /\d/ );
    expect( phoneRow.querySelector( '.identity-badge' )!.textContent ).toBe( '✓ verified' );
    for ( const node of Array.from( panel.querySelectorAll( 'button' ) ) )
    {
      const name = ( node.getAttribute( 'aria-label' ) || node.textContent || '' );
      expect( name, `${ name } reads as a phone affordance` )
        .not.toMatch( /phone|number|mobile/i );
    }
  } );

  it( 'source: there is no phone edit path to open', () => {
    // CODE, not SOURCE: the page's own docblock legitimately NAMES onEditPhone in a comment
    // explaining that no such prop exists, so sweeping the raw text would fail on the
    // explanation rather than on the code. Same reasoning as every other sweep in this file.
    expect( CODE ).not.toContain( 'onEditPhone' );
    const modes = Array.from( CODE.matchAll( /openEditor\(\s*'([^']*)'\s*\)/g ) )
      .map( match => match[ 1 ] );
    expect( modes.length ).toBeGreaterThan( 0 );
    for ( const mode of modes )
    {
      expect( [ 'name', 'email', 'address' ] ).toContain( mode );
    }
  } );
} );

describe( '/orders/ — failure handling', () => {
  it( 'returns an expired session to the signed-out state with the expiry line', async () => {
    // An hour-long token ending is the normal case, not a fault, so it is never the error state.
    await renderSignedIn( answer( 401, {} ) );
    expect( await screen.findByText( /sign-in has expired/ ) ).toBeInTheDocument();
    expect( clearSession ).toHaveBeenCalledTimes( 1 );
    expect( screen.getByRole( 'link', { name: /Sign in on WhatsApp/ } ) ).toBeInTheDocument();
    expect( screen.queryByText( /could not load your orders/ ) ).toBeNull();
  } );

  it( 'offers a retry on an unavailable read', async () => {
    await renderSignedIn( answer( 503, {} ) );
    expect( await screen.findByText( /could not load your orders/ ) ).toBeInTheDocument();
    const retry = screen.getByRole( 'button', { name: 'Try again' } );
    fetchMock.mockResolvedValueOnce( answer( 200, { orders: [ row() ], profile: profile() } ) );
    fireEvent.click( retry );
    expect( await screen.findByText( 'WD-1042' ) ).toBeInTheDocument();
  } );

  it( 'names the rate limit rather than calling it a failure', async () => {
    await renderSignedIn( answer( 429, {} ) );
    expect( await screen.findByText( /Too many requests/ ) ).toBeInTheDocument();
  } );

  it( 'treats a network rejection as unavailable, not as a crash', async () => {
    withSession();
    fetchMock.mockRejectedValueOnce( new Error( 'offline' ) );
    render( <OrdersPage /> );
    expect( await screen.findByText( /could not load your orders/ ) ).toBeInTheDocument();
  } );

  it( 'stays signed out when a silent refresh fails', async () => {
    restoreSession.mockRejectedValueOnce( new Error( 'no' ) );
    render( <OrdersPage /> );
    await waitFor( () => expect( restoreSession ).toHaveBeenCalled() );
    expect( screen.getByRole( 'link', { name: /Sign in on WhatsApp/ } ) ).toBeInTheDocument();
    expect( fetchMock ).not.toHaveBeenCalled();
  } );
} );

describe( '/orders/ — the request it sends', () => {
  it( 'posts a bearer token to the my-orders route with an allowlisted body', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    const [ url, init ] = fetchMock.mock.calls[ 0 ];
    expect( String( url ) ).toContain( '/ecommerce/my-orders' );
    expect( init.method ).toBe( 'POST' );
    expect( init.headers.Authorization ).toBe( 'Bearer tok' );
    // The server's body allowlist is {limit, cursor} and nothing else; any other key is a 400.
    expect( JSON.parse( init.body ) ).toEqual( {} );
  } );

  it( 'sends the cursor and only the cursor on a second page', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockResolvedValueOnce( answer( 200, { orders: [] } ) );
    fireEvent.click( more );
    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 2 ) );
    expect( JSON.parse( fetchMock.mock.calls[ 1 ][ 1 ].body ) ).toEqual( { cursor: 'c1' } );
  } );

  it( 'compares no raw provider spelling of a payment state', () => {
    // The mapping from 'PAYMENT_PAID', 'paid' and 'completed' happened once, on the server, in
    // payment_status. A spelling appearing here would be the frontend starting a sixth
    // vocabulary. 'captured' is the canonical key of a lookup table, which is the one allowed
    // use - so what is banned is a COMPARISON against any spelling.
    expect( CODE ).not.toMatch( /===?\s*['"](?:captured|paid|completed|PAYMENT_PAID)['"]/ );
    expect( CODE ).not.toContain( "'paid'" );
    expect( CODE ).not.toContain( "'completed'" );
    expect( CODE ).not.toContain( 'PAYMENT_PAID' );
  } );
} );

describe( '/orders/ — keyboard reachability', () => {
  it( 'hides nothing behind opacity:0 that a Tab can still reach', () => {
    // opacity:0 does not remove an element from the tab order, and this page's children contain
    // buttons, a link and a form - which is why it arms no entrance animation of its own.
    //
    // Read from THIS PAGE'S SOURCE, not from the rendered stylesheets: the joined <style>
    // elements also carry PillButton's and PageTopBand's rules, and both of those legitimately
    // use opacity:0 on their own non-focusable decoration. A container-wide sweep therefore
    // fails on another component's correct code and says nothing about this page.
    expect( CODE ).not.toMatch( /opacity\s*:\s*0\b/ );
  } );

  it( 'skips a disabled affordance rather than styling it as available', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], cursor: 'c1', profile: profile() } ) );
    const more = await screen.findByRole( 'button', { name: 'Show more orders' } );
    fetchMock.mockImplementationOnce( () => new Promise( () => undefined ) );
    fireEvent.click( more );
    const busy = await screen.findByRole( 'button', { name: 'Loading…' } );
    expect( busy ).toBeDisabled();
  } );
} );
