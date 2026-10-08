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
/**
 * RequestsPanel (Phase O-1) is STUBBED here so this file's fetch-count assertions keep measuring
 * the ORDERS page alone; the panel's own fetch, copy and states are pinned in
 * src/test/OrdersRequests.test.tsx. The stub keeps its heading so the h2 ladder is still real.
 */
vi.mock( '../components/orders/RequestsPanel', () => ( {
  __esModule: true,
  default: () => <section aria-labelledby="rqp-title"><h2 id="rqp-title">Your requests</h2></section>,
} ) );
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
  channel?: string;
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
    expect( h2 ).toEqual( [ 'What we have on file', 'Your requests', 'Order history' ] );
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
    const view = await renderSignedIn(
      answer( 200, { orders: [ row() ], profile: profile() } ) );
    await screen.findByText( 'WD-1042' );
    expect( screen.getByText( '₹1,214.81' ) ).toBeInTheDocument();
    expect( screen.getByText( 'Paid' ) ).toBeInTheDocument();
    // DERIVED, not pinned to a literal. The epoch is formatted in the BROWSER's zone so an IST
    // reader sees their own day, which is the behaviour being asserted - a hardcoded "28 Sept"
    // would pass or fail on the machine the suite happens to run in rather than on the page.
    //
    // MIGRATED to a cell query rather than loosened: the date is now in its own column AND, for
    // the CSS-only fold, in an always-present .ord-subdate sub-line, so a bare getByText finds
    // two nodes. Both are asserted, which is strictly more than the one this used to check.
    const { container } = view;
    expect( container.querySelector( 'td.ord-col-date' )!.textContent ).toBe( EXPECTED_DATE );
    expect( container.querySelector( '.ord-subdate' )!.textContent ).toBe( EXPECTED_DATE );
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
    // MIGRATED: the Date column's cell is still rendered, it is EMPTY. An absent cell would
    // misalign the column indices against a five-column header.
    expect( container.querySelector( 'td.ord-col-date' )!.textContent ).toBe( '' );
    expect( container.querySelector( '.ord-subdate' )!.textContent ).toBe( '' );
  } );

  it( 'flags the identifier and the amount against translation, but not the date', async () => {
    // SupportWidget rewrites text-node values. A regrouped amount would make this page lie about
    // money; a localised month name is an improvement and no decision depends on its spelling.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    // MIGRATED from .ord-itemh / .ord-date, which were the card shell's classes.
    expect( container.querySelector( '.ord-ordno' ) ).toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( '.ord-ref' ) ).toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( '.ord-amount' ) ).toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( 'td.ord-col-date' ) )
      .not.toHaveAttribute( 'data-wc-no-translate' );
    expect( container.querySelector( '.ord-subdate' ) )
      .not.toHaveAttribute( 'data-wc-no-translate' );
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
    // MIGRATED from the <h3> card heading to the identifier span inside the <th scope="row">.
    // Same ladder, same two expected values; the element it lives in changed.
    await waitFor( () => expect(
      container.querySelectorAll( '.ord-ordno' ) ).toHaveLength( 2 ) );
    const ids = Array.from( container.querySelectorAll( '.ord-ordno' ) )
      .map( node => node.textContent );
    expect( ids[ 0 ] ).toBe( 'REF-9' );
    expect( ids[ 1 ] ).toBe( EXPECTED_DATE );
  } );

  it( 'renders only the three expected h2 rungs', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const h2 = Array.from( container.querySelectorAll( 'h2' ) ).map( h => h.textContent );
    expect( h2 ).toEqual( [ 'What we have on file', 'Your requests', 'Order history' ] );
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
    /**
     * WAIT FOR THE CHECKING LINE BEFORE ADVANCING THE CLOCK, and it is a synchronisation point
     * rather than an extra assertion. `orders.tsx:256` registers the one-shot re-ask only once
     * `view === 'empty'`, which needs the FIRST fetch to have resolved and set state; and
     * `checking` at :195 is that same condition, so this line rendering IS the timer being
     * registered. Advancing a clock before the timer exists advances past nothing, and the
     * re-ask then never fires.
     *
     * Without it this case failed in roughly 2 of 5 full-suite runs with "expected 2 times, got
     * 1 times" while passing every time in isolation - load-sensitive, because
     * `shouldAdvanceTime: true` lets wall-clock time move the fake clock while the suite is
     * busy elsewhere. The two sibling cases in this describe block always awaited this line and
     * never flaked, which is what identified the cause. `shouldAdvanceTime` is KEPT: it is what
     * lets the awaits in `renderSignedIn` settle, and removing it changes more than this race.
     */
    await screen.findByText( /Checking for recent orders/ );
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

/**
 * The clipboard state, installed with `defineProperty` ON THE REAL navigator and restored from
 * descriptors. Both halves are measured decisions rather than style:
 *
 *   `{ ...navigator }` copies NOTHING - Navigator's members are accessors on
 *   Navigator.prototype, so against this jsdom `Object.keys({ ...navigator })` has length 0. A
 *   spread stub happens to work for `navigator.clipboard` while silently replacing every other
 *   navigator property with undefined for the rest of the block.
 *
 *   `Object.create( navigator, { clipboard: … } )` is fragile differently: jsdom's generated
 *   getters brand-check the receiver, so any inherited read throws "called on an object that is
 *   not a valid instance of Navigator".
 *
 * The restore is not optional. The file-level afterEach is `vi.unstubAllGlobals();
 * vi.useRealTimers();`, which reverses a `vi.stubGlobal` and reverses NO `defineProperty` at
 * all - so without this, `isSecureContext: true` leaks into every describe that runs afterwards.
 * `realClipboard` is captured as a DESCRIPTOR rather than a value because jsdom may not define
 * `clipboard` at all; the restore then `delete`s the property instead of writing `undefined`
 * over it, which is the difference between "absent" and "present and falsy" for canCopy's
 * `!!navigator.clipboard` read.
 */
function withClipboard () {
  const realClipboard = Object.getOwnPropertyDescriptor( navigator, 'clipboard' );
  const realSecure = Object.getOwnPropertyDescriptor( window, 'isSecureContext' );

  beforeEach( () => {
    Object.defineProperty( navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue( undefined ) }, configurable: true,
    } );
    Object.defineProperty( window, 'isSecureContext', { value: true, configurable: true } );
  } );

  afterEach( () => {
    if ( realClipboard ) Object.defineProperty( navigator, 'clipboard', realClipboard );
    else delete ( navigator as unknown as Record<string, unknown> ).clipboard;
    if ( realSecure ) Object.defineProperty( window, 'isSecureContext', realSecure );
    else delete ( window as unknown as Record<string, unknown> ).isSecureContext;
  } );
}

/** `writeText`, typed, so a test can assert its argument. */
function writeText () {
  return ( navigator.clipboard as unknown as { writeText: ReturnType<typeof vi.fn> } ).writeText;
}

describe( '/orders/ — the order history table', () => {
  it( 'renders one real table with column headers and a row header', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelectorAll( 'table' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'thead' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'tbody' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'th[scope="row"]' ) ).toHaveLength( 1 );
    // No display:block re-flow anywhere: that strips table semantics in several screen readers.
    expect( CODE ).not.toMatch( /\.ord-(?:table|tr|td|th)[^{]*\{[^}]*display\s*:\s*block/ );
  } );

  it( 'wraps the table in a keyboard-scrollable labelled region', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const wrap = container.querySelector( '.ord-tablewrap' )!;
    expect( wrap ).toHaveAttribute( 'role', 'region' );
    expect( wrap ).toHaveAttribute( 'aria-labelledby', 'ord-history' );
    expect( wrap ).toHaveAttribute( 'tabindex', '0' );
    // overflow-x:auto, which the gate permits; overflow:hidden, which it forbids, is absent.
    expect( CODE ).toContain( '.ord-tablewrap{overflow-x:auto' );
  } );

  it( 'puts the number, the reference, the date, the amount and the status on one row',
    async () => {
      const { container } = await renderSignedIn( answer( 200, {
        orders: [ row() ], profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      const cells = Array.from(
        container.querySelectorAll( 'tr.ord-tr > th, tr.ord-tr > td' ) );
      expect( cells ).toHaveLength( 5 );
      expect( cells[ 0 ].textContent ).toContain( 'WD-1042' );
      // WhatsApp sends this as `Ref:`, so it is on the ROW rather than hidden in the panel.
      expect( cells[ 0 ].textContent ).toContain( 'Ref ref-1' );
      expect( cells[ 1 ].textContent ).toBe( EXPECTED_DATE );
      expect( cells[ 2 ].textContent ).toBe( '₹1,214.81' );
      expect( cells[ 3 ].textContent ).toContain( 'Paid' );
    } );

  it( 'keeps formatPaiseINR exact and Indian through the move into a cell', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [
        row( { amountPaise: 100, referenceId: 'a' } ),
        row( { amountPaise: 10_000_000, orderNumber: 'WD-2', referenceId: 'b' } ),
      ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const amounts = Array.from( container.querySelectorAll( 'td.ord-td-num' ) )
      .map( node => node.textContent );
    // Lakh grouping, and exact: formatPaiseINR slices strings, it never divides.
    expect( amounts ).toEqual( [ '₹1.00', '₹1,00,000.00' ] );
    expect( CODE ).toContain( 'font-variant-numeric:tabular-nums' );
  } );

  it( 'does not blank the table when one row is unreadable', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [
        row( { referenceId: 'a' } ),
        row( { referenceId: 'b', orderNumber: 'WD-BAD', amountPaise: null, status: '',
          createdAt: null } ),
        row( { referenceId: 'c', orderNumber: 'WD-3' } ),
      ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    // Counted BY CLASS. An expanded row contributes a second tr.ord-detailrow, so a bare <tr>
    // count would silently become a test of how many panels are open.
    expect( container.querySelectorAll( 'tbody tr.ord-tr' ) ).toHaveLength( 3 );
    expect( screen.getByText( 'Amount unavailable' ) ).toBeInTheDocument();
    expect( screen.getByText( 'Status unavailable' ) ).toBeInTheDocument();
    expect( container.textContent ).not.toContain( 'Invalid Date' );
  } );

  it( 'has exactly five column headers, and they are these five', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    // EQUALITY, so a sixth column cannot be added without a deliberate test edit.
    const headers = Array.from( container.querySelectorAll( 'th[scope="col"]' ) )
      .map( node => node.textContent );
    expect( headers ).toEqual( [ 'Order #', 'Date', 'Amount', 'Status', 'Invoice' ] );
  } );

  it( 'renders the date exactly once at every width', async () => {
    // Three assertions, because "appears outside any media query" is not expressible as one
    // toMatch - and CODE has comments stripped, so no regex may rely on them.
    expect( CODE.slice( 0, CODE.indexOf( '@media' ) ) )
      .toContain( '.ord-subdate{display:none' );
    expect( CODE ).toMatch(
      /@media\(max-width:767px\)\{[\s\S]*?\.ord-col-date\{display:none\}[\s\S]*?\.ord-subdate\{display:block\}[\s\S]*?\}/ );
    // And on the rendered tree: display:none hides ONE element, while the fold hides a COLUMN,
    // so the class is on the header AND every cell or the data outlives its header.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: 'a' } ), row( { referenceId: 'b', orderNumber: 'WD-2' } ) ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelectorAll( 'th.ord-col-date' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'td.ord-col-date' ).length )
      .toBe( container.querySelectorAll( 'tr.ord-tr' ).length );
  } );

  it( 'leaves the row inert: it is a reading aid, not an affordance', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const tr = container.querySelector( 'tr.ord-tr' )!;
    expect( tr.getAttribute( 'onclick' ) ).toBeNull();
    expect( tr.getAttribute( 'role' ) ).toBeNull();
    expect( tr.getAttribute( 'tabindex' ) ).toBeNull();
    // SCOPED to the .ord-tr{…} block: .ord-ordbtn and .ord-copy legitimately declare
    // cursor:pointer, so a substring search over the whole stylesheet would fail on correct code.
    const block = CODE.match( /(?:^|[;}\s])\.ord-tr\{([^}]*)\}/ )!;
    expect( block[ 1 ] ).not.toMatch( /cursor\s*:\s*pointer/ );
    // The tint is a background only, and there is no :active equivalent - a tap on a row must do
    // nothing and look like it did nothing.
    expect( CODE ).toContain( '.ord-tr:hover{background:rgba(209,244,112,.22)}' );
    expect( CODE ).not.toContain( '.ord-tr:active' );
  } );

  it( 'removes the dead card CSS and keeps the definition list the panel now uses', () => {
    for ( const gone of [ '.ord-items', '.ord-item', '.ord-itemh' ] )
    {
      expect( CODE, `${ gone } is dead CSS and must not ship` ).not.toContain( gone );
    }
    expect( CODE ).toContain( '.ord-facts dt' );
    expect( CODE ).toContain( '.ord-facts dd' );
    // visibility:hidden is the ONE permitted hide mechanism on this page, and it must not
    // spread: .ord-tip is the only element entitled to it.
    expect( CODE.match( /visibility\s*:\s*hidden/g ) ).toHaveLength( 1 );
  } );

  it( 'adds the two controls as selectors on the shared quiet block, not as copies of it', () => {
    expect( CODE ).toContain( '.ord-quiet,.ord-inv,.ord-copy{' );
    for ( const cls of [ '.ord-inv', '.ord-copy' ] )
    {
      // The override blocks only, i.e. `.ord-copy{…}` with no other selector in front of it.
      const own = CODE.match( new RegExp( `(^|[;}\\s])\\${ cls }\\{([^}]*)\\}`, 'g' ) ) ?? [];
      expect( own.length, `${ cls } has no override block` ).toBeGreaterThan( 0 );
      for ( const block of own )
      {
        expect( block, `${ cls } must not redeclare the shared body` ).not.toMatch( /border\s*:/ );
        expect( block ).not.toMatch( /min-height\s*:/ );
      }
    }
    // All three state rules carry all three selectors, so a later edit cannot extend the body
    // and forget :disabled - which is the opacity:.55 the invoice table relies on.
    for ( const state of [ ':hover:not(:disabled)', ':focus-visible', ':disabled' ] )
    {
      for ( const cls of [ '.ord-quiet', '.ord-inv', '.ord-copy' ] )
      {
        expect( CODE, `${ cls }${ state } is missing` ).toContain( `${ cls }${ state }` );
      }
    }
  } );

  it( 'writes the table header as the page label rung, not as small caps', () => {
    expect( CODE ).not.toMatch( /text-transform\s*:\s*uppercase/ );
    const th = CODE.match( /(?:^|[;}\s])\.ord-th\{([^}]*)\}/ )![ 1 ];
    expect( th ).toContain( 'font-size:12px' );
    expect( th ).toContain( 'font-weight:700' );
    expect( th ).toContain( 'letter-spacing:0' );
    expect( th ).toContain( 'color:#1a3a2a' );
    // Logical, never physical: the gate matches text-align:left.
    expect( th ).toContain( 'text-align:start' );
  } );

  it( 'resets the row header cell, which the UA stylesheet centres and bolds', () => {
    // .ord-td is ALSO carried by the <th scope="row">, where the UA default is
    // font-weight:bold;text-align:center, and .ord-th's start alignment does not reach it.
    // Without these two the widest cell on the page renders centred and bold.
    const td = CODE.match( /(?:^|[;}\s])\.ord-td\{([^}]*)\}/ )![ 1 ];
    expect( td ).toContain( 'text-align:start' );
    expect( td ).toContain( 'font-weight:400' );
  } );
} );

describe( '/orders/ — the order-source tag', () => {
  it( 'says WhatsApp on a WhatsApp order and Website on a website order', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [
        row( { channel: 'whatsapp', referenceId: 'a' } ),
        row( { channel: 'website', orderNumber: 'WD-2', referenceId: 'b' } ),
      ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const tags = Array.from( container.querySelectorAll( '.ord-src' ) )
      .map( node => node.textContent );
    expect( tags ).toEqual( [ 'WhatsApp', 'Website' ] );
  } );

  it( 'reads Website for a row that carries no channel on the wire', async () => {
    // Every order that existed before `channel` was written, and every row the SERVING index's
    // older projection does not carry it on - the repoint to customerId-createdAt-v2-index is a
    // separate deliberate step. `row()` deliberately omits the field, so this is the real shape.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelector( '.ord-src' )!.textContent ).toBe( 'Website' );
  } );

  it( 'reads Website for an unrecognised channel rather than rendering it', async () => {
    // The server canonicalises, so this should be unreachable - which is exactly why the browser
    // must not echo whatever arrived. A third word on the page would be a disclosure of a bug
    // dressed up as a label.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { channel: 'telegram' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( container.querySelector( '.ord-src' )!.textContent ).toBe( 'Website' );
    expect( container.textContent ).not.toContain( 'telegram' );
  } );

  it( 'adds no sixth column: the header is still exactly these five', async () => {
    // The tag lives inside the existing Order # cell. A sixth column would be a restructure of
    // the table, and the detail row's colSpan={5} would silently stop spanning the whole row.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { channel: 'whatsapp' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WhatsApp' );
    const headers = Array.from( container.querySelectorAll( 'th[scope="col"]' ) )
      .map( node => node.textContent );
    expect( headers ).toEqual( [ 'Order #', 'Date', 'Amount', 'Status', 'Invoice' ] );
    expect( CODE ).toContain( 'colSpan={ 5 }' );
  } );

  it( 'is TEXT, not colour: the tag carries a readable word and a weight', () => {
    // WCAG 1.4.1 - a tag distinguished only by hue fails for anyone who cannot see the
    // difference, and this page has no legend to look one up in.
    const src = CODE.match( /(?:^|[;}\s])\.ord-src\{([^}]*)\}/ )![ 1 ];
    expect( src ).toContain( 'font-weight:700' );
    expect( src ).not.toContain( 'background' );
  } );

  it( 'shows the same word in the row and in the opened detail panel', async () => {
    // Both read ONE local, so they cannot disagree. Asserted on the rendered tree rather than on
    // the source, because "derived from the same variable" is only interesting if it shows up.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { channel: 'whatsapp' } ) ], profile: profile(),
    } ) );
    const trigger = await screen.findByRole( 'button', { expanded: false } );
    fireEvent.click( trigger );
    const terms = Array.from( container.querySelectorAll( '.ord-facts dt' ) )
      .map( node => node.textContent );
    expect( terms ).toContain( 'Ordered on' );
    const panel = Array.from( container.querySelectorAll( '.ord-facts dt' ) )
      .find( node => node.textContent === 'Ordered on' )!.nextElementSibling;
    expect( panel!.textContent ).toBe( 'WhatsApp' );
    expect( container.querySelector( '.ord-src' )!.textContent ).toBe( 'WhatsApp' );
  } );

  it( 'leaves the tag translatable, because "Website" is prose', async () => {
    // Nothing branches on the rendered string - the branch is on `order.channel`, which is the
    // canonical value from the wire and never the text a reader sees.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { channel: 'whatsapp' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WhatsApp' );
    expect( container.querySelector( '.ord-src' ) )
      .not.toHaveAttribute( 'data-wc-no-translate' );
  } );
} );

describe( '/orders/ — WhatsApp parity', () => {
  it( 'compares no status field against any string literal at all', () => {
    // The existing sweep bans four named spellings and the comparisons against them. This one
    // names none, so it catches a sixth spelling nobody has thought of yet.
    expect( CODE ).not.toMatch( /\.(?:status|paymentStatus)\s*===?\s*['"]/ );
  } );

  it( 'reads the canonical word through a lookup, and renders it as "Paid"', async () => {
    await renderSignedIn( answer( 200, { orders: [ row() ], profile: profile() } ) );
    expect( await screen.findByText( 'Paid' ) ).toBeInTheDocument();
    // A lookup object, not a conditional chain. WhatsApp sends Meta's own order_status enum
    // ('completed'); the mapping onto one vocabulary happened on the server, in payment_status.
    expect( CODE ).toContain( 'const STATUS_LABEL: Record<string, string> = {' );
    expect( CODE ).not.toMatch( /if\s*\(\s*order\.status/ );
  } );

  it( 'aliases invoice eligibility to the firm-status set rather than declaring a second one',
    () => {
      // The states that are financially settled are exactly the states an invoice can exist
      // for, so this is the same fact twice. If a later phase legitimately splits them - a rank
      // that is firm but not invoiceable - THIS is the test to replace rather than delete.
      expect( CODE ).toContain( 'const INVOICE_ELIGIBLE = STATUS_FIRM;' );
      expect( CODE.match( /new Set\(/g ) ).toHaveLength( 1 );
    } );

  it( 'shows the reference id WhatsApp sends as Ref, on the row', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: 'WD-REF-0012' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const ref = container.querySelector( '.ord-ref' )!;
    expect( ref.textContent ).toBe( 'Ref WD-REF-0012' );
    expect( ref ).toHaveAttribute( 'data-wc-no-translate' );
  } );

  it( 'agrees with WhatsApp on the digits, and diverges only on the separators', async () => {
    // ACCEPTED DIVERGENCE, recorded rather than fixed. formatPaiseINR uses en-IN lakh/crore
    // grouping, so 10,000,000 paise renders ₹1,00,000.00; Python's f'{total:,.2f}' renders
    // 100,000.00 and f'{amount:.2f}' renders 100000.00 with no grouping at all. THE DIGITS
    // ALWAYS AGREE; the separators diverge at five figures and above. Changing the WhatsApp
    // side means editing a float format string on the payment path, which is out of scope.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { amountPaise: 10_000_000 } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const rendered = container.querySelector( 'td.ord-td-num' )!.textContent!;
    const digits = ( value: string ) => value.replace( /[^0-9]/g, '' );
    expect( digits( rendered ) ).toBe( digits( '100000.00' ) );
  } );
} );

describe( '/orders/ — the order-id trigger and the detail row', () => {
  withClipboard();

  it( 'renders the order number as a collapsed disclosure trigger', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const trigger = container.querySelector( 'th[scope="row"] button[aria-expanded]' )!;
    expect( trigger.tagName ).toBe( 'BUTTON' );
    // A real button, so Enter and Space both activate it and aria-expanded announces the state.
    // Not a div with a handler, and not the <tr>.
    expect( trigger ).toHaveAttribute( 'type', 'button' );
    expect( trigger ).toHaveAttribute( 'aria-expanded', 'false' );
    expect( trigger.getAttribute( 'aria-controls' ) ).toBeTruthy();
  } );

  it( 'gives a row with neither identifier a working trigger anyway', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { orderNumber: '', referenceId: '' } ) ], profile: profile(),
    } ) );
    await waitFor( () => expect( screen.getAllByText( EXPECTED_DATE ).length )
      .toBeGreaterThan( 0 ) );
    // rowKey falls back to row-<index> and detailId is derived from the index, so aria-controls
    // is never empty even with nothing to key on.
    const trigger = container.querySelector( 'th[scope="row"] button[aria-expanded]' )!;
    expect( trigger.getAttribute( 'aria-controls' ) ).toBe( 'ord-detail-0' );
    fireEvent.click( trigger );
    expect( container.querySelectorAll( 'tr.ord-detailrow' ) ).toHaveLength( 1 );
  } );

  it( 'announces the identifier only from the row header', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: 'WD-REF-0012' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    // Resolved through the ACCESSIBILITY TREE, so this fails if the aria-label is dropped and
    // the name falls back to the cell's concatenated text content - which would otherwise
    // announce "WD-1042 Copy Copy order ID Ref WD-REF-0012 <date>" before every data cell.
    const header = screen.getByRole( 'rowheader', { name: 'WD-1042' } );
    expect( header.getAttribute( 'aria-label' ) ).toBe( 'WD-1042' );
    expect( header.getAttribute( 'aria-label' ) ).not.toMatch( /Ref/ );
    expect( header.getAttribute( 'aria-label' ) ).not.toContain( EXPECTED_DATE );
    // The label RENAMES the cell; it does not hide what is in it.
    expect( header.querySelector( 'button[aria-expanded]' ) ).toBeTruthy();
    expect( header.querySelector( 'button.ord-copy' ) ).toBeTruthy();
    expect( container.querySelector( '.ord-ref' )!.textContent ).toBe( 'Ref WD-REF-0012' );
  } );

  it( 'announces the date as the name on a degraded row, the same ladder', async () => {
    await renderSignedIn( answer( 200, {
      orders: [ row( { orderNumber: '', referenceId: '' } ) ], profile: profile(),
    } ) );
    await waitFor( () => expect( screen.getAllByText( EXPECTED_DATE ).length )
      .toBeGreaterThan( 0 ) );
    expect( screen.getByRole( 'rowheader', { name: EXPECTED_DATE } ) ).toBeTruthy();
  } );

  it( 'opens one full-width detail row and leaves the header equality intact', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    const trigger = container.querySelector( 'th[scope="row"] button[aria-expanded]' )!;
    expect( trigger ).toHaveAttribute( 'aria-expanded', 'true' );
    const panels = container.querySelectorAll( 'tr.ord-detailrow' );
    expect( panels ).toHaveLength( 1 );
    const cell = panels[ 0 ].querySelector( 'td' )!;
    expect( cell.getAttribute( 'colspan' ) ).toBe( '5' );
    // A <td>, never a <th>, so the five-column equality is unaffected by an open panel.
    expect( panels[ 0 ].querySelectorAll( 'th' ) ).toHaveLength( 0 );
    expect( Array.from( container.querySelectorAll( 'th[scope="col"]' ) )
      .map( node => node.textContent ) )
      .toEqual( [ 'Order #', 'Date', 'Amount', 'Status', 'Invoice' ] );
  } );

  it( 'shows every fact on the wire in the panel, and no second formatter', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const amountCell = container.querySelector( 'td.ord-td-num' )!.textContent;
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    const panel = container.querySelector( 'tr.ord-detailrow' )!;
    const rung = ( name: string ) => Array.from( panel.querySelectorAll( 'dt' ) )
      .find( node => node.textContent === name )!.nextElementSibling!.textContent;
    expect( rung( 'Order number' ) ).toBe( 'WD-1042' );
    expect( rung( 'Reference' ) ).toBe( 'ref-1' );
    // The panel is where the TIME belongs; the column shows a short date.
    expect( rung( 'Placed' ) ).toContain( EXPECTED_DATE.split( ' ' )[ 0 ] );
    expect( rung( 'Placed' ) ).toMatch( /\d{1,2}[:.]\d{2}/ );
    // Asserted EQUAL to the cell's text, so the panel cannot grow a second formatter.
    expect( rung( 'Amount' ) ).toBe( amountCell );
    expect( rung( 'Status' ) ).toBe( 'Paid' );
    // Stated rather than omitted: the owner asked for items and a silent absence reads as a bug.
    expect( rung( 'Items' ) ).toBe( 'Item details are not available for this order.' );
    // R7-F2: with the flag OFF, row 1 of the panel's first-match-wins ladder matches on its
    // FLAG TERM - the same gate the column's first row uses, so the two cannot drift.
    expect( panel.textContent ).toContain(
      'No invoice for this order. Some paid orders never get one — '
      + 'contact us and we will check.' );
    expect( panel.querySelectorAll( 'button' ) ).toHaveLength( 0 );
  } );

  it( 'reads "Not assigned" and "Not available" when the identifiers are absent', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { orderNumber: '', referenceId: '' } ) ], profile: profile(),
    } ) );
    await waitFor( () => expect( screen.getAllByText( EXPECTED_DATE ).length )
      .toBeGreaterThan( 0 ) );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    const panel = container.querySelector( 'tr.ord-detailrow' )!;
    expect( panel.textContent ).toContain( 'Not assigned' );
    expect( panel.textContent ).toContain( 'Not available' );
  } );

  it( 'collapses again on a second click', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const open = () => container.querySelector( 'th[scope="row"] button[aria-expanded]' )!;
    fireEvent.click( open() );
    expect( container.querySelectorAll( 'tr.ord-detailrow' ) ).toHaveLength( 1 );
    fireEvent.click( open() );
    expect( open() ).toHaveAttribute( 'aria-expanded', 'false' );
    expect( container.querySelectorAll( 'tr.ord-detailrow' ) ).toHaveLength( 0 );
  } );

  it( 'opens two rows at once, because comparing two orders is the obvious reason to',
    async () => {
      const { container } = await renderSignedIn( answer( 200, {
        orders: [ row( { referenceId: 'a' } ),
          row( { referenceId: 'b', orderNumber: 'WD-2' } ) ],
        profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      const triggers = () => Array.from(
        container.querySelectorAll( 'th[scope="row"] button[aria-expanded]' ) );
      fireEvent.click( triggers()[ 0 ] );
      fireEvent.click( triggers()[ 1 ] );
      // A single-open accordion was rejected: collapsing the one being read in order to open
      // another is a worse default than a longer page.
      expect( container.querySelectorAll( 'tr.ord-detailrow' ) ).toHaveLength( 2 );
      expect( triggers().map( node => node.getAttribute( 'aria-expanded' ) ) )
        .toEqual( [ 'true', 'true' ] );
    } );

  it( 'tints both rows of an expanded pair, so the state reads as one unit', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    expect( container.querySelector( 'tr.ord-tr' )!.className ).toBe( 'ord-tr ord-tr-open' );
    expect( container.querySelector( 'tr.ord-detailrow' )!.className )
      .toContain( 'ord-tr-open' );
  } );
} );

describe( '/orders/ — the copy control', () => {
  withClipboard();

  it( 'names the control by the id it copies, and shows only the word Copy', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const copy = container.querySelector( 'button.ord-copy' )!;
    expect( copy ).toHaveAttribute( 'aria-label', 'Copy order ID WD-1042' );
    expect( copy.textContent ).toBe( 'Copy' );
  } );

  it( 'copies the order number, falling back to the reference', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: 'a' } ),
        row( { orderNumber: '', referenceId: 'REF-9' } ) ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const buttons = Array.from( container.querySelectorAll( 'button.ord-copy' ) );
    fireEvent.click( buttons[ 0 ] );
    // Asserted on the ARGUMENT, not on the DOM: what is copied comes from React state, because
    // SupportWidget rewrites text nodes and a DOM read could copy a translated string.
    await waitFor( () => expect( writeText() ).toHaveBeenCalledWith( 'WD-1042' ) );
    fireEvent.click( buttons[ 1 ] );
    await waitFor( () => expect( writeText() ).toHaveBeenCalledWith( 'REF-9' ) );
    expect( writeText() ).toHaveBeenCalledTimes( 2 );
  } );

  it( 'confirms a copy in the hint and in one page-level live region', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fireEvent.click( container.querySelector( 'button.ord-copy' )! );
    await waitFor( () => expect(
      container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Copied' ) );
    expect( container.querySelector( '.ord-tip' )!.className ).toContain( 'ord-tip-on' );
    // REACHED BY CLASS, then asserted ON. getByRole('status') would be ambiguous: this page
    // already has five role="status" sites and .ord-live is a sixth, so it would start failing
    // with "found multiple elements" in a copy test the moment moreFailed were also true.
    const live = container.querySelector( '.ord-live' )!;
    expect( live ).toHaveAttribute( 'role', 'status' );
    expect( live ).toHaveAttribute( 'aria-live', 'polite' );
    expect( live.textContent ).toBe( 'Order ID copied' );
    expect( live.textContent ).not.toContain( 'WD-1042' );
  } );

  it( 'clears the copied state after the timer, and on unmount sets no state', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    const { container, unmount } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fireEvent.click( container.querySelector( 'button.ord-copy' )! );
    await waitFor( () => expect(
      container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Copied' ) );
    await act( async () => { vi.advanceTimersByTime( 2_100 ); } );
    expect( container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Copy order ID' );
    expect( container.querySelector( '.ord-live' )!.textContent ).toBe( '' );
    // Unmounting mid-window must not leave a pending timeout calling setState on a dead tree.
    fireEvent.click( container.querySelector( 'button.ord-copy' )! );
    unmount();
    await act( async () => { vi.advanceTimersByTime( 5_000 ); } );
  } );

  it( 'selects the id instead when the clipboard refuses, and stays usable', async () => {
    writeText().mockRejectedValueOnce( new Error( 'denied' ) );
    // Installed and RESTORED in the same test: vitest.config.ts sets no restoreMocks and the
    // file-level afterEach reverses globals only, so an un-restored createRange spy would keep
    // throwing for every later test in this file.
    const spy = vi.spyOn( document, 'createRange' ).mockImplementation( () => {
      throw new Error( 'no Range' );
    } );
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const copy = container.querySelector( 'button.ord-copy' )! as HTMLButtonElement;
    fireEvent.click( copy );
    // The OBSERVABLE OUTCOME, never the Selection object: jsdom's createRange/getSelection
    // support is partial, so asserting on it would be a test of jsdom. What IS asserted about
    // selectText is that it cannot throw - it runs inside copyId's catch arm.
    await waitFor( () => expect(
      container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Press your copy key' ) );
    expect( container.querySelector( '.ord-live' )!.textContent )
      .toBe( 'Order ID selected. Copy it with your keyboard.' );
    expect( copy.disabled ).toBe( false );
    spy.mockRestore();
  } );

  it( 'does not let the failure hint come back after a later success', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    writeText().mockRejectedValueOnce( new Error( 'denied' ) );
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const copy = container.querySelector( 'button.ord-copy' )!;
    fireEvent.click( copy );
    await waitFor( () => expect(
      container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Press your copy key' ) );
    // The failure hint has NO TIMER of its own: it is an instruction about a selection that is
    // still on screen, so it must last as long as that selection does.
    await act( async () => { vi.advanceTimersByTime( 10_000 ); } );
    expect( container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Press your copy key' );
    // Then succeed. Both arms clear the other key, so the ternary cannot fall back through to
    // the failure wording when the 2s "Copied" expires - which is the compounding bug.
    fireEvent.click( copy );
    await waitFor( () => expect(
      container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Copied' ) );
    await act( async () => { vi.advanceTimersByTime( 2_100 ); } );
    expect( container.querySelector( '.ord-tip' )!.textContent ).toBe( 'Copy order ID' );
    expect( container.querySelector( '.ord-tip' )!.textContent )
      .not.toBe( 'Press your copy key' );
  } );

  it( 'renders a row with neither identifier without a control OR a hint', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [
        row( { orderNumber: '', referenceId: '' } ),
        row( { orderNumber: 'WD-2', referenceId: 'b' } ),
      ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-2' );
    // ONE render with a mixed table, so the condition is shown to be PER ROW. The hint is
    // asserted too, not just the button: visibility:hidden keeps the box, so an unconditional
    // hint would ship a permanently invisible 14px line on a row that can never reveal it.
    const rows = Array.from( container.querySelectorAll( 'tr.ord-tr' ) );
    expect( rows[ 0 ].querySelectorAll( 'button.ord-copy' ) ).toHaveLength( 0 );
    expect( rows[ 0 ].querySelectorAll( '.ord-tip' ) ).toHaveLength( 0 );
    expect( rows[ 1 ].querySelectorAll( 'button.ord-copy' ) ).toHaveLength( 1 );
    expect( rows[ 1 ].querySelectorAll( '.ord-tip' ) ).toHaveLength( 1 );
    // Neither row loses its trigger.
    expect( container.querySelectorAll( 'button[aria-expanded]' ) ).toHaveLength( 2 );
  } );

  it( 'keeps the hint redundant and reveals it with visibility, never opacity or display',
    () => {
      expect( CODE ).toContain( 'aria-hidden="true"' );
      // Declared hidden BEFORE any rule that makes it visible, and the reveals are the two
      // sibling selectors plus the state class - a conditional render would reintroduce the
      // layout shift visibility exists to avoid.
      const hidden = CODE.indexOf( '.ord-tip{' );
      const shown = CODE.indexOf( '.ord-tip-on{visibility:visible}' );
      expect( hidden ).toBeGreaterThan( -1 );
      expect( shown ).toBeGreaterThan( hidden );
      expect( CODE ).toContain(
        '.ord-copy:hover ~ .ord-tip,.ord-copy:focus-visible ~ .ord-tip,'
        + '.ord-tip-on{visibility:visible}' );
      expect( CODE ).not.toMatch( /\.ord-tip[^{]*\{[^}]*display\s*:\s*none/ );
    } );
} );

describe( '/orders/ — the copy control with no clipboard', () => {
  it( 'renders no control and no hint on any row, and keeps every trigger', async () => {
    // The single test that removes the clipboard, and it does so in its own body. This is also
    // the state of the static export, where nothing is signed in anyway.
    const realClipboard = Object.getOwnPropertyDescriptor( navigator, 'clipboard' );
    const realSecure = Object.getOwnPropertyDescriptor( window, 'isSecureContext' );
    delete ( navigator as unknown as Record<string, unknown> ).clipboard;
    Object.defineProperty( window, 'isSecureContext', { value: false, configurable: true } );
    try
    {
      const { container } = await renderSignedIn( answer( 200, {
        orders: [ row( { referenceId: 'a' } ),
          row( { referenceId: 'b', orderNumber: 'WD-2' } ) ],
        profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      expect( container.querySelectorAll( 'button.ord-copy' ) ).toHaveLength( 0 );
      // The table is UNIFORM in this state: every row loses the line together.
      expect( container.querySelectorAll( '.ord-tip' ) ).toHaveLength( 0 );
      expect( container.querySelectorAll( 'button[aria-expanded]' ) ).toHaveLength( 2 );
    }
    finally
    {
      if ( realClipboard ) Object.defineProperty( navigator, 'clipboard', realClipboard );
      if ( realSecure ) Object.defineProperty( window, 'isSecureContext', realSecure );
      else delete ( window as unknown as Record<string, unknown> ).isSecureContext;
    }
  } );
} );

describe( '/orders/ — the invoice control, with the flag off', () => {
  it( 'is silent in the shipped state: no control, and not one request', async () => {
    // flags.invoiceDownload is false here, which IS the shipped state. This is the test that
    // makes "the page is correct and shippable without the route" true as written.
    expect( flags.invoiceDownload ).toBe( false );
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const cells = Array.from( container.querySelectorAll( 'tr.ord-tr > td' ) );
    const invoice = cells[ cells.length - 1 ];
    expect( invoice.textContent ).toBe( 'No invoice yet' );
    expect( invoice.querySelectorAll( 'button' ) ).toHaveLength( 0 );
    // Clicking anywhere in the row issues nothing either.
    fireEvent.click( container.querySelector( 'tr.ord-tr' )! );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    const invoiceCalls = fetchMock.mock.calls
      .filter( ( [ url ] ) => String( url ).includes( '/ecommerce/my-invoice' ) );
    expect( invoiceCalls ).toHaveLength( 0 );
  } );
} );

describe( '/orders/ — the invoice control', () => {
  beforeEach( () => { flags.invoiceDownload = true; } );
  afterEach( () => { flags.invoiceDownload = false; } );

  const SIGNED = 'https://wecare-digital-get.s3.amazonaws.com/secure/stack/invoices/x.png'
    + '?X-Amz-Signature=abc123&X-Amz-Credential=cred';

  function invoiceButton ( container: HTMLElement ) {
    return container.querySelector( 'button.ord-inv' ) as HTMLButtonElement;
  }

  it( 'offers an enabled download on a settled order', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( invoiceButton( container ).textContent ).toBe( 'Download invoice' );
    expect( invoiceButton( container ).disabled ).toBe( false );
  } );

  it( 'disables it on every unsettled status', async () => {
    for ( const status of [ 'pending', 'failed', 'created', 'authorized' ] )
    {
      const { container, unmount } = await renderSignedIn( answer( 200, {
        orders: [ row( { status } ) ], profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      expect( invoiceButton( container ).disabled, `${ status } must not offer an invoice` )
        .toBe( true );
      unmount();
    }
  } );

  it( 'disables it with no reference to ask about', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: '' } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( invoiceButton( container ).disabled ).toBe( true );
  } );

  it( 'posts exactly the three allowlisted fields with the bearer token', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( answer( 200, { available: false } ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 2 ) );
    const [ url, init ] = fetchMock.mock.calls[ 1 ];
    expect( String( url ) ).toContain( '/ecommerce/my-invoice' );
    expect( init.method ).toBe( 'POST' );
    expect( init.headers.authorization ).toBe( 'Bearer tok' );
    // The server's allowlist is these three keys and nothing else; a fourth is a 400.
    expect( JSON.parse( init.body ) ).toEqual( {
      referenceId: 'ref-1', createdAt: 1759000000, format: 'png',
    } );
  } );

  it( 'disables THIS control while it is in flight and says it is preparing', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockImplementationOnce( () => new Promise( () => undefined ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect( invoiceButton( container ).textContent ).toBe( 'Preparing…' ) );
    expect( invoiceButton( container ).disabled ).toBe( true );
    expect( invoiceButton( container ) ).toHaveAttribute( 'aria-busy', 'true' );
  } );

  it( 'clicks exactly one synthetic anchor carrying the signed URL', async () => {
    const click = vi.spyOn( HTMLAnchorElement.prototype, 'click' )
      .mockImplementation( () => undefined );
    try
    {
      const { container } = await renderSignedIn( answer( 200, {
        orders: [ row() ], profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      fetchMock.mockResolvedValueOnce( answer( 200, { available: true, url: SIGNED } ) );
      fireEvent.click( invoiceButton( container ) );
      await waitFor( () => expect( click ).toHaveBeenCalledTimes( 1 ) );
      // Spied, not navigated. The href is read off the element the spy was called on.
      expect( ( click.mock.instances[ 0 ] as HTMLAnchorElement ).href ).toBe( SIGNED );
      expect( ( click.mock.instances[ 0 ] as HTMLAnchorElement ).rel ).toBe( 'noopener' );
      // NO `download` attribute: receipt_links bakes attachment;filename into the SIGNATURE,
      // and `download` is same-origin-only so a cross-origin S3 response ignores it anyway.
      expect( ( click.mock.instances[ 0 ] as HTMLAnchorElement )
        .hasAttribute( 'download' ) ).toBe( false );
      expect( CODE ).not.toMatch( /\.download\s*=/ );
      // The row returns to idle rather than sticking on busy.
      await waitFor( () => expect(
        invoiceButton( container ).textContent ).toBe( 'Download invoice' ) );
    }
    finally { click.mockRestore(); }
  } );

  it( 'treats available:false as terminal and does not re-ask', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( answer( 200, { available: false } ) );
    fireEvent.click( invoiceButton( container ) );
    const cells = () => Array.from( container.querySelectorAll( 'tr.ord-tr > td' ) );
    await waitFor( () => expect(
      cells()[ cells().length - 1 ].textContent ).toBe( 'No invoice yet' ) );
    expect( container.querySelectorAll( 'button.ord-inv' ) ).toHaveLength( 0 );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    expect( fetchMock ).toHaveBeenCalledTimes( 2 );
  } );

  it( 'runs the list expiry path on a 401 rather than showing an error', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( answer( 401, {} ) );
    fireEvent.click( invoiceButton( container ) );
    expect( await screen.findByText( /sign-in has expired/ ) ).toBeInTheDocument();
    expect( clearSession ).toHaveBeenCalledTimes( 1 );
    expect( screen.getByRole( 'link', { name: /Sign in on WhatsApp/ } ) ).toBeInTheDocument();
  } );

  it( 'names the rate limit and keeps the original label', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( answer( 429, {} ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect(
      screen.getByText( 'Too many requests. Wait a moment.' ) ).toBeInTheDocument() );
    // BOTH HALVES. This row was refused the CADENCE, not the invoice, so the action is
    // unchanged and the message carries the news. Relabelling it "Try again" would invite the
    // immediate second click the limiter just declined.
    expect( invoiceButton( container ).textContent ).toBe( 'Download invoice' );
    expect( invoiceButton( container ) ).not.toBeDisabled();
  } );

  it( 'offers a retry on a 5xx, and the retry re-issues the request', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( answer( 503, {} ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect( invoiceButton( container ).textContent ).toBe( 'Try again' ) );
    expect( screen.getByText( 'Could not fetch the invoice' ) ).toBeInTheDocument();
    fetchMock.mockResolvedValueOnce( answer( 200, { available: false } ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 3 ) );
  } );

  it( 'treats a network rejection as recoverable', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockRejectedValueOnce( new Error( 'offline' ) );
    fireEvent.click( invoiceButton( container ) );
    await waitFor( () => expect( invoiceButton( container ).textContent ).toBe( 'Try again' ) );
  } );

  it( 'refuses four url shapes rather than navigating to any of them', async () => {
    const refused: unknown[] = [
      // A bare CDN URL with no marker - a permanent public link that works forever.
      'https://wecare.digital/get/o/stack/invoices/x.png',
      // CARRIES A MARKER AND MUST STILL BE REFUSED. This is the one the server's
      // assert_not_permanent lets through: is_permanent_public_url returns False for anything
      // not starting with 'http', so a non-http string is passed through as "not permanent".
      // The value reaches a.href and is clicked, so it is an execution surface in this origin.
      'javascript:void(0)/*Expires=1700000000*/',
      // Signed but plaintext: the grant is handed to any observer.
      'http://wecare.digital/x.png?X-Amz-Signature=abc',
      // Not a string at all.
      null,
    ];
    const click = vi.spyOn( HTMLAnchorElement.prototype, 'click' )
      .mockImplementation( () => undefined );
    const created = vi.spyOn( document, 'createElement' );
    try
    {
      for ( const url of refused )
      {
        const { container, unmount } = await renderSignedIn( answer( 200, {
          orders: [ row() ], profile: profile(),
        } ) );
        await screen.findByText( 'WD-1042' );
        created.mockClear();
        fetchMock.mockResolvedValueOnce( answer( 200, { available: true, url } ) );
        fireEvent.click( invoiceButton( container ) );
        await waitFor( () => expect(
          invoiceButton( container ).textContent, `${ String( url ) } was accepted` )
          .toBe( 'Try again' ) );
        expect( click ).not.toHaveBeenCalled();
        // The guard runs BEFORE createElement, so no anchor ever exists carrying the value.
        expect( created.mock.calls.filter( ( [ tag ] ) => tag === 'a' ) ).toHaveLength( 0 );
        unmount();
      }
    }
    finally { click.mockRestore(); created.mockRestore(); }
  } );

  it( 'mirrors the signer own marker set exactly', () => {
    // The Python tuple is FUNCTION-LOCAL, not a module constant, so it is extracted rather than
    // imported. Reading a non-TS source from a vitest file is established practice here.
    const py = readFileSync(
      resolve( process.cwd(), 'amplify/functions/shared/lambda_utils/receipt_links.py' ),
      'utf8' );
    const markers = ( py.match( /signed_markers\s*=\s*\(([^)]*)\)/ )?.[ 1 ] ?? '' )
      .split( ',' ).map( part => part.trim().replace( /^["']|["']$/g, '' ) ).filter( Boolean );
    expect( markers.length ).toBe( 4 );
    const page = ( CODE.match( /const SIGNED_MARKERS = \[([^\]]*)\]/ )?.[ 1 ] ?? '' )
      .split( ',' ).map( part => part.trim().replace( /^["']|["']$/g, '' ) ).filter( Boolean );
    expect( page ).toEqual( markers );
  } );

  it( 'resolves two rows independently', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { referenceId: 'a' } ),
        row( { referenceId: 'b', orderNumber: 'WD-2' } ) ],
      profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    const buttons = () => Array.from(
      container.querySelectorAll( 'button.ord-inv' ) ) as HTMLButtonElement[];
    fetchMock.mockImplementationOnce( () => new Promise( () => undefined ) );
    fireEvent.click( buttons()[ 0 ] );
    await waitFor( () => expect( buttons()[ 0 ].textContent ).toBe( 'Preparing…' ) );
    // Each resolves into its own map entry, keyed on its own referenceId.
    expect( buttons()[ 1 ].textContent ).toBe( 'Download invoice' );
    expect( buttons()[ 1 ].disabled ).toBe( false );
  } );

  it( 'never hands the signed URL to a log', () => {
    // The URL is a bearer grant, so nothing on this path logs at all.
    expect( CODE ).not.toMatch( /console\s*\./ );
    expect( CODE ).not.toMatch( /logger/i );
    expect( CODE ).not.toMatch( /JSON\.stringify\([^)]*\burl\b/ );
  } );

  it( 'disables it on every unreadable createdAt, and issues no request', async () => {
    // A real wire value, not a hypothetical: customer-orders emits null when int(createdAt)
    // raises, and createdAt is an EXACT key condition on the ownership query - so leaving the
    // control enabled would POST createdAt:null for a deterministic 400 on every click.
    for ( const createdAt of [ null, 0, 1759000000.5 ] )
    {
      const { container, unmount } = await renderSignedIn( answer( 200, {
        orders: [ row( { createdAt } ) ], profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      const button = invoiceButton( container );
      expect( button.disabled, `createdAt ${ String( createdAt ) }` ).toBe( true );
      fireEvent.click( button );
      expect( fetchMock.mock.calls
        .filter( ( [ url ] ) => String( url ).includes( '/ecommerce/my-invoice' ) ) )
        .toHaveLength( 0 );
      unmount();
    }
  } );

  it( 'treats 400, 403 and 404 as terminal, with no retry and no second request', async () => {
    for ( const status of [ 400, 403, 404 ] )
    {
      const { container, unmount } = await renderSignedIn( answer( 200, {
        orders: [ row() ], profile: profile(),
      } ) );
      await screen.findByText( 'WD-1042' );
      fetchMock.mockResolvedValueOnce( answer( status, { error: 'X' } ) );
      fireEvent.click( invoiceButton( container ) );
      const cells = () => Array.from( container.querySelectorAll( 'tr.ord-tr > td' ) );
      await waitFor( () => expect(
        cells()[ cells().length - 1 ].textContent, `${ status } must be terminal` )
        .toBe( 'No invoice yet' ) );
      expect( screen.queryByRole( 'button', { name: 'Try again' } ) ).toBeNull();
      const before = fetchMock.mock.calls.length;
      fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
      expect( fetchMock.mock.calls.length ).toBe( before );
      unmount();
    }
  } );

  it( 'treats a 200 whose body is not JSON as terminal too', async () => {
    // NOT expressible as a status case, which is why it is written out separately: this is the
    // response.json() throw. A 200 with an HTML SPA body is exactly what an unmatched Amplify
    // /api/* rewrite could return, and re-asking cannot change that.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fetchMock.mockResolvedValueOnce( {
      status: 200, ok: true,
      json: async () => { throw new Error( 'Unexpected token <' ); },
    } );
    fireEvent.click( invoiceButton( container ) );
    const cells = () => Array.from( container.querySelectorAll( 'tr.ord-tr > td' ) );
    await waitFor( () => expect(
      cells()[ cells().length - 1 ].textContent ).toBe( 'No invoice yet' ) );
    expect( screen.queryByRole( 'button', { name: 'Try again' } ) ).toBeNull();
    const before = fetchMock.mock.calls.length;
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    expect( fetchMock.mock.calls.length ).toBe( before );
  } );

  it( 'never duplicates the invoice control into the detail panel', async () => {
    // Run with the column LIVE, because "not duplicated" is a claim about a control that
    // exists - asserting it in the state where the thing it guards against is possible is the
    // point. A row's controls stay: the trigger, the copy control, and the one in column 5.
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row() ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    expect( invoiceButton( container ) ).toBeTruthy();
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    const panel = container.querySelector( 'tr.ord-detailrow' )!;
    expect( panel.querySelectorAll( 'button' ) ).toHaveLength( 0 );
    expect( container.querySelectorAll( 'button.ord-inv' ) ).toHaveLength( 1 );
  } );

  it( 'shows one null createdAt in four places and Invalid Date in none', async () => {
    const { container } = await renderSignedIn( answer( 200, {
      orders: [ row( { createdAt: null } ) ], profile: profile(),
    } ) );
    await screen.findByText( 'WD-1042' );
    fireEvent.click( container.querySelector( 'th[scope="row"] button[aria-expanded]' )! );
    expect( container.querySelector( 'td.ord-col-date' )!.textContent ).toBe( '' );
    expect( container.querySelector( '.ord-subdate' )!.textContent ).toBe( '' );
    const panel = container.querySelector( 'tr.ord-detailrow' )!;
    const placed = Array.from( panel.querySelectorAll( 'dt' ) )
      .find( node => node.textContent === 'Placed' )!.nextElementSibling!;
    expect( placed.textContent ).toBe( '' );
    // The disabled half is only expressible with the column live, which is why this test is in
    // the flag-on block.
    expect( invoiceButton( container ).disabled ).toBe( true );
    expect( container.textContent ).not.toContain( 'Invalid Date' );
  } );
} );
