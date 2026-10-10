import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

/**
 * Phase R — the website "Leave a review" door.
 *
 * WHAT THIS FILE IS FOR
 * ---------------------
 * The spec asks for one specific proof: "the website button links to the correct `wa.me` URL
 * with the reference". That is the first describe. The rest guards the two ways this door can
 * be wrong in a way nobody notices:
 *
 *   1. IT POINTS AT THE WRONG WABA. `DEFAULT_FLOW_TRIGGERS['leave_review']` declares a
 *      `flowId` and NO `flowId2`, so only WABA 1 can deliver the review Flow — on WABA 2
 *      `_send_generic_flow` falls back to a CTA URL button. A link to the wrong number
 *      therefore "works" (WhatsApp opens, a message sends) and the customer never reaches the
 *      form. Asserted as a PROPERTY against all three business numbers, not as today's
 *      string, so a future edit cannot repoint it.
 *   2. IT CARRIES A REFERENCE THAT MATCHES NO ORDER. Order numbers have three live shapes and
 *      one of them — the legacy spaced Wix form `WD-ORD - A1B2C3D4 - …` — cannot survive in a
 *      URL keyword. `reviewWaLink` drops it rather than stripping it to something that looks
 *      like a reference and resolves to nothing.
 *
 * NOTHING HERE SENDS ANYTHING. A `wa.me` link makes the CUSTOMER message US, which is also
 * what opens the 24-hour window a Flow needs.
 *
 * TWO DOORS, AND ONLY ONE IS FLAG-GATED NOW. The /leave-review/ page CTA is the owner's own
 * `wa.me/message/ZM74K2H2BIFOA1` short link, unconditional, because WD_Leave_Review_v2
 * (1578178897413815) is published - the room behind that door exists. `featureFlags.reviewCta`
 * still governs the ATTRIBUTED per-order row in /orders/, which is the only place an order
 * number exists, so the flag seam below is still load-bearing for those describes.
 *
 * THE FLAG SEAM follows `src/test/OrdersPage.test.tsx`: `vi.mock` is hoisted above the
 * imports, so the factory closes over a `vi.hoisted()` object — a plain `const` would still be
 * in TDZ when the factory runs. It deliberately does not spread the real module, because
 * controlling the value is the whole point.
 */
const flags = vi.hoisted( () => ( { invoiceDownload: false, reviewCta: false } ) );
vi.mock( '../config/featureFlags', () => ( { featureFlags: flags } ) );

const getSession = vi.fn();
const restoreSession = vi.fn();
const clearSession = vi.fn();
vi.mock( '../lib/customerAuth', () => ( {
  getSession: () => getSession(),
  restoreSession: () => restoreSession(),
  clearSession: () => clearSession(),
} ) );

vi.mock( '../components/CheckoutProfile', () => ( {
  __esModule: true,
  default: () => <div data-testid="profile-stub" />,
} ) );

import OrdersPage from '../pages/orders';
import { CUSTOMERSERVICE } from '../content/customerservice';
import {
  REVIEW_WA_NUMBER, isCarriableReference, reviewWaLink,
} from '../lib/reviewLink';

/** The three business numbers. This door must never point at one of them. */
const BUSINESS_NUMBERS = [ '918031830030', '919330994400', '919903300044' ] as const;

function row ( over: Record<string, unknown> = {} ) {
  return {
    orderNumber: 'WD-ORD-A7K2M9PQ',
    referenceId: 'WD-PAY-REF0001',
    createdAt: 1759000000,
    amountPaise: 121481,
    currency: 'INR',
    currencyUnexpected: false,
    status: 'captured',
    statusRank: 40,
    ...over,
  };
}

function answer ( status: number, body: unknown ) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => JSON.parse( JSON.stringify( body ) ),
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach( () => {
  flags.reviewCta = false;
  flags.invoiceDownload = false;
  getSession.mockReset().mockReturnValue( null );
  restoreSession.mockReset().mockResolvedValue( null );
  clearSession.mockReset();
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
} );

afterEach( () => {
  vi.unstubAllGlobals();
} );

async function renderOrders ( ...answers: ReturnType<typeof answer>[] ) {
  getSession.mockReturnValue( { accessToken: 'tok', expiresAt: Date.now() + 3_600_000 } );
  answers.forEach( a => fetchMock.mockResolvedValueOnce( a ) );
  const view = render( <OrdersPage /> );
  await waitFor( () => expect( fetchMock ).toHaveBeenCalled() );
  return view;
}

/**
 * Open the first row's detail panel, the way a customer does.
 *
 * AWAITS THE ROW, and that is not belt-and-braces. `renderOrders` only waits for `fetch` to
 * have been CALLED; the rows appear one state update later, after the response promise
 * settles. Querying synchronously passed consistently in isolation and failed under full-suite
 * load, which is the signature of exactly this race — so the wait is the fix, not a retry.
 */
async function openFirstRow ( container: HTMLElement ) {
  const trigger = await waitFor( () => {
    const found = container.querySelector( 'th[scope="row"] button[aria-expanded]' );
    expect( found, 'no expandable order row rendered' ).toBeTruthy();
    return found!;
  } );
  fireEvent.click( trigger );
}

// ─────────────────────────────── the URL itself ───────────────────────────────

describe( 'reviewWaLink builds the wa.me URL', () => {
  it( 'carries the reference when there is one', () => {
    expect( reviewWaLink( 'WD-ORD-A7K2M9PQ' ) )
      .toBe( 'https://wa.me/919330994400?text=review%20WD-ORD-A7K2M9PQ' );
  } );

  it( 'falls back to the bare keyword with no reference', () => {
    expect( reviewWaLink() ).toBe( 'https://wa.me/919330994400?text=review' );
    expect( reviewWaLink( '' ) ).toBe( 'https://wa.me/919330994400?text=review' );
    expect( reviewWaLink( null ) ).toBe( 'https://wa.me/919330994400?text=review' );
  } );

  it( 'upper-cases the reference, which is lossless for an order number', () => {
    // `order_keys.PUBLIC_ORDER_NUMBER_ALPHABET` is upper-case and digits, and the inbound
    // handler upper-cases its own lowercased match — so both ends land on one string.
    expect( reviewWaLink( 'wd-ord-a7k2m9pq' ) )
      .toBe( 'https://wa.me/919330994400?text=review%20WD-ORD-A7K2M9PQ' );
  } );

  it( 'accepts all three live order-identifier shapes that can survive a URL keyword', () => {
    expect( isCarriableReference( 'WD-ORD-A7K2M9PQ' ) ).toBe( true );  // current minted form
    expect( isCarriableReference( 'A7K2M9PQ3WXY' ) ).toBe( true );     // legacy bare 12-char
    expect( isCarriableReference( 'WD-PAY-REF0001' ) ).toBe( true );   // payment reference
  } );

  it( 'DROPS a reference it cannot vouch for rather than mangling it', () => {
    /*
     * The decision this test exists for. Stripping the legacy spaced Wix number to
     * `[A-Z0-9-]` would mint `WD-ORD-A1B2C3D4-20260101` — a string matching NO order in the
     * table. Attribution would then look successful and point at nothing, which is worse for
     * the staff member reading the queue than an honest absence.
     */
    for ( const junk of [
      'WD-ORD - A1B2C3D4 - 20260101',   // the legacy spaced form
      'ab',                              // under the 4-character floor
      '-WD-ORD-1234',                    // must start alphanumeric
      'WD ORD A7K2M9PQ',                 // spaces are not part of a reference
      'review me',
      'A'.repeat( 64 ),                  // over the 40-character ceiling
      'WD-ORD-A7K2M9PQ?x=1',             // anything that could alter the query string
    ] ) {
      expect( isCarriableReference( junk ), junk ).toBe( false );
      expect( reviewWaLink( junk ), junk ).toBe( 'https://wa.me/919330994400?text=review' );
    }
  } );

  it( 'never produces a URL that could carry a second query parameter', () => {
    // `encodeURIComponent` plus the bound above. Belt and braces, because the prefilled text
    // is the only thing the inbound handler parses.
    const url = reviewWaLink( 'WD-ORD-A7K2M9PQ' );
    expect( url.split( '?' ) ).toHaveLength( 2 );
    expect( url.split( '&' ) ).toHaveLength( 1 );
  } );
} );

describe( 'the door points at the WABA that has the review Flow', () => {
  it( 'is WABA 1', () => {
    expect( REVIEW_WA_NUMBER ).toBe( '919330994400' );
  } );

  it( 'is never any other business number, asserted as a property', () => {
    /*
     * `leave_review` has a `flowId` and no `flowId2`, so WABA 2 cannot deliver this Flow —
     * it falls back to a CTA URL button. A link to the wrong number still "works", which is
     * exactly why this needs pinning rather than reviewing.
     */
    const wrong = BUSINESS_NUMBERS.filter( n => n !== REVIEW_WA_NUMBER );
    for ( const number of wrong ) {
      expect( reviewWaLink( 'WD-ORD-A7K2M9PQ' ) ).not.toContain( number );
      expect( reviewWaLink() ).not.toContain( number );
    }
  } );
} );

// ──────────────────────────── /orders/ , the attributed door ────────────────────────────

describe( '/orders/ review button with the flag OFF', () => {
  it( 'renders no review row at all', async () => {
    const { container } = await renderOrders( answer( 200, { orders: [ row() ] } ) );
    await openFirstRow( container );
    expect( screen.queryByText( 'Review' ) ).toBeNull();
    expect( container.querySelector( 'a[href*="wa.me"]' ) ).toBeNull();
  } );
} );

describe( '/orders/ review button with the flag ON', () => {
  beforeEach( () => { flags.reviewCta = true; } );

  it( 'carries that order\'s own order number', async () => {
    const { container } = await renderOrders( answer( 200, { orders: [ row() ] } ) );
    await openFirstRow( container );

    const link = container.querySelector( 'a[href*="wa.me"]' ) as HTMLAnchorElement;
    expect( link ).toBeTruthy();
    expect( link.getAttribute( 'href' ) )
      .toBe( 'https://wa.me/919330994400?text=review%20WD-ORD-A7K2M9PQ' );
  } );

  it( 'falls back to the reference when there is no order number', async () => {
    // The same ladder `copyValue` uses: the two REAL identifiers and never the date, because
    // a date is not something staff can resolve back to an order.
    const { container } = await renderOrders(
      answer( 200, { orders: [ row( { orderNumber: '' } ) ] } ) );
    await openFirstRow( container );

    const link = container.querySelector( 'a[href*="wa.me"]' ) as HTMLAnchorElement;
    expect( link.getAttribute( 'href' ) )
      .toBe( 'https://wa.me/919330994400?text=review%20WD-PAY-REF0001' );
  } );

  it( 'omits the row entirely when the order carries no usable identifier', async () => {
    /*
     * Rather than rendering an unattributed button. A review door inside a per-order panel
     * that carries no order would attribute nothing while looking like it does, and
     * /leave-review/ already is the unattributed door for anyone who wants one.
     */
    const { container } = await renderOrders(
      answer( 200, { orders: [ row( { orderNumber: '', referenceId: '' } ) ] } ) );
    await openFirstRow( container );
    expect( screen.queryByText( 'Review' ) ).toBeNull();
    expect( container.querySelector( 'a[href*="wa.me"]' ) ).toBeNull();
  } );

  it( 'omits the row for a legacy spaced order number instead of mangling it', async () => {
    const { container } = await renderOrders( answer( 200, {
      orders: [ row( { orderNumber: 'WD-ORD - A1B2C3D4 - 20260101', referenceId: '' } ) ],
    } ) );
    await openFirstRow( container );
    expect( container.querySelector( 'a[href*="wa.me"]' ) ).toBeNull();
  } );

  it( 'reuses the shared pill, and its accessible name is its visible text', async () => {
    /*
     * WCAG 2.5.3 Label in Name. `PillButton` has no `ariaLabel` prop by design, so the
     * platform's own concatenation of the visible text IS the name and the two cannot drift.
     * Asserted here so a future edit cannot reintroduce an override on this call site.
     */
    const { container } = await renderOrders( answer( 200, { orders: [ row() ] } ) );
    await openFirstRow( container );

    const link = container.querySelector( 'a.pill' ) as HTMLAnchorElement;
    expect( link, 'the review CTA must reuse the shared pill' ).toBeTruthy();
    expect( link.textContent ).toContain( 'Leave a review' );
    expect( link.getAttribute( 'aria-label' ) ).toBeNull();
    const name = ( link.getAttribute( 'aria-label' ) || link.textContent || '' ).trim();
    expect( name ).toContain( 'Leave a review' );
  } );

  it( 'renders one review link per opened order, not one per order', async () => {
    const { container } = await renderOrders( answer( 200, {
      orders: [ row(), row( { orderNumber: 'WD-ORD-B8L3N4RS', referenceId: 'WD-PAY-REF0002' } ) ],
    } ) );
    // Nothing open yet.
    expect( container.querySelectorAll( 'a[href*="wa.me"]' ) ).toHaveLength( 0 );
    await openFirstRow( container );
    expect( container.querySelectorAll( 'a[href*="wa.me"]' ) ).toHaveLength( 1 );
  } );
} );

// ──────────────────────── /leave-review/ , the unattributed door ────────────────────────

describe( '/leave-review/ page CTA', () => {
  const entry = () => CUSTOMERSERVICE.find( p => p.slug === 'leave-review' )!;

  it( 'exists and says where the button goes', () => {
    expect( entry() ).toBeTruthy();
    expect( entry().ctaLabel ).toBe( 'Leave a review' );
  } );

  it( 'is the owner\'s wa.me short link, which is the shipped state', () => {
    expect( entry().ctaHref ).toBe( 'https://wa.me/message/ZM74K2H2BIFOA1' );
  } );

  /*
   * The shared identity every review surface reads. Asserted here as well as in
   * tests/test_leave_review_wiring.py, because `reviewEntry.ts` is now the single source the
   * page CTA and all four workspace tables import - so a wrong value here is a wrong value
   * in five places at once.
   */
  it( 'shares the published Flow identity and ordered aliases with the workspace displays', async () => {
    const { REVIEW_FLOW_ID, REVIEW_ENTRY_URL, REVIEW_ENTRY_KEYWORDS } =
      await import( '../lib/reviewEntry' );
    // WD_Leave_Review_v2, the published review Flow on WABA 1. The source is the source
    // of truth and is
    // used in five places at once; this assertion tracks it.
    expect( REVIEW_FLOW_ID ).toBe( '1578178897413815' );
    expect( REVIEW_ENTRY_URL ).toBe( 'https://wa.me/message/ZM74K2H2BIFOA1' );
    // The page CTA reads this same constant, so these must be the same string.
    expect( entry().ctaHref ).toBe( REVIEW_ENTRY_URL );
    // Ordered, not a set: the FIRST keyword is the short link's Meta-side prefill, so the
    // page button only lands on an exact keyword match while `leave review` leads.
    expect( REVIEW_ENTRY_KEYWORDS[ 0 ] ).toBe( 'leave review' );
    expect( REVIEW_ENTRY_KEYWORDS ).toHaveLength( 19 );
  } );

  /*
   * The value is now FLAG-FREE, so it must read the same with `reviewCta` either way. The
   * module reads nothing from `featureFlags` at evaluation any more, so flipping `flags`
   * after import proves the absence of a read rather than being defeated by it - which is
   * the opposite of the problem the superseded version of this test had to work around.
   */
  it( 'does not depend on featureFlags.reviewCta in either position', () => {
    flags.reviewCta = true;
    expect( entry().ctaHref ).toBe( 'https://wa.me/message/ZM74K2H2BIFOA1' );
    flags.reviewCta = false;
    expect( entry().ctaHref ).toBe( 'https://wa.me/message/ZM74K2H2BIFOA1' );
  } );

  it( 'carries no reference and no second query parameter', async () => {
    /*
     * A visitor reading this page has no order in context, so the door is deliberately
     * unattributed. Asserted on the source too, so a future edit cannot reintroduce a
     * generated per-order link on the one page that has no order.
     */
    const href = entry().ctaHref!;
    expect( href.split( '?' ) ).toHaveLength( 1 );
    const { readFileSync } = await import( 'node:fs' );
    const { resolve } = await import( 'node:path' );
    const source = readFileSync(
      resolve( __dirname, '../content/customerservice.ts' ), 'utf8' );
    // The import and the CALL, not the bare identifier - the module's own comment names
    // `reviewWaLink` to record that it is intentionally absent, and that mention is fine.
    expect( source ).not.toContain( "from '../lib/reviewLink'" );
    expect( source ).not.toContain( 'reviewWaLink(' );
    expect( source ).not.toContain( 'featureFlags.reviewCta ?' );
  } );

  it( 'no other customer-service CTA was repointed', () => {
    const others = CUSTOMERSERVICE.filter( p => p.slug !== 'leave-review' );
    expect( others.length ).toBeGreaterThan( 0 );
    for ( const page of others ) {
      expect( page.ctaHref, page.slug ).toBe( 'https://wecare.digital/contact/' );
    }
  } );
} );
