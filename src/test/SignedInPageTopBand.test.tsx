import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

import Cart from '../pages/cart';
import CheckoutStatus from '../pages/checkout/status';
import CheckoutSuccess from '../pages/checkout/success';
import { shopProductBySlug } from '../content/shop';
import type { ShopProduct } from '../content/shop';
import * as cartLib from '../lib/cart';
import * as customerAuth from '../lib/customerAuth';

/**
 * THE HERO IN THE SIGNED-IN RENDER, which nothing pinned for these three pages.
 *
 * The owner reported the top band missing from /cart/, /orders/ and the checkout screens AFTER
 * LOGIN. `src/test/PublicPageTopBand.test.tsx` already drives all three pages through the band
 * matrix, but every one of its cases renders the SIGNED-OUT branch and says so in code: the cart
 * cases open with `getSession().mockReturnValue(null)`, and the two checkout cases render with no
 * `?a=` in the URL, so neither ever reaches an authenticated read. `/orders/` is covered by
 * `OrdersPage.test.tsx`'s own signed-in pair and is deliberately not re-tested here.
 *
 * So this file is the other half, and it is a VERIFICATION rather than a fix: on each page
 * `PageTopBand` is the outermost element of the `return` and wraps the whole body, so the band
 * cannot be dropped by a state change - only by an edit that moves it or puts a condition on it.
 * That is exactly the regression these cases fail on. Each page is asserted in BOTH states in the
 * same case, so a band that survives only one of them cannot pass.
 *
 * WHY THIS IS NOT BROWSER-VERIFIED. These are session-bound pages: the static export ships an
 * empty `#__next` for them and the signed-in DOM is produced client-side after sign-in, so the
 * browser harnesses cannot load the authenticated render at all. jsdom also applies no CSS, so
 * clearance and the type rungs stay with `tools/browser/devicecheck.js` on the signed-out render.
 * What is decidable here is STRUCTURE - one `main`, one `h1`, one `.ptb-top`, and nothing
 * conversion-shaped inside it - and that is what is asserted.
 */

const KIOSK = (): ShopProduct => shopProductBySlug( 'kiosk' ) as ShopProduct;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/** A live customer session, the one thing that puts each of these pages on its signed-in path. */
const SESSION = { accessToken: 'tok-signed-in', expiresAt: Date.now() + 3_600_000 };

/**
 * The `action:'profile'` reply for a customer who can pay right now. `addressComplete` is what
 * takes `deriveStatus` to `'ready'`, which is the cart's richest signed-in body - the identity
 * card renders, so the case is not passing against a thin render that happens to keep the band.
 */
const PROFILE_READY = {
  status: 'PROFILE_READY',
  contactId: 'contact-1',
  name: 'Asha Sen',
  firstName: 'Asha',
  lastName: 'Sen',
  email: 'asha@example.com',
  phone: '+919330994400',
  emailVerified: true,
  addressComplete: true,
  address: {
    addressLine1: '12 MG Road',
    addressLine2: 'Flat 3B',
    locality: '',
    city: 'Bengaluru',
    state: 'Karnataka',
    postalCode: '560001',
    country: 'India',
    countryCode: 'IN',
    fullAddress: '12 MG Road, Flat 3B, Bengaluru, Karnataka, 560001, India',
  },
};

function signedIn (): void {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( SESSION );
  vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( SESSION );
}

function signedOut (): void {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
  vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( null );
}

/** One sticky answer for every request, which is all these cases ask of the network. */
function stubFetch ( body: unknown, ok = true ) {
  const fetchMock = vi.fn().mockResolvedValue( {
    ok, status: ok ? 200 : 500, json: async () => JSON.parse( JSON.stringify( body ) ),
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

/**
 * The band, asserted as STRUCTURE. `.ptb-top` holds the h1 and the sub-line and nothing else -
 * a consumer's children render outside it - so the button/link/rupee checks can only fail on
 * something passed through `heading` or `sub`.
 */
function expectBand ( container: HTMLElement, heading: string, where: string ): void {
  expect( container.querySelectorAll( 'main' ), where ).toHaveLength( 1 );
  expect( container.querySelector( 'main' )!.className, where ).toContain( 'ptb-shell' );
  const tops = container.querySelectorAll( '.ptb-top' );
  expect( tops, where ).toHaveLength( 1 );
  const h1s = container.querySelectorAll( 'h1' );
  expect( h1s, where ).toHaveLength( 1 );
  expect( h1s[ 0 ].textContent, where ).toBe( heading );
  // The one h1 is the BAND's, not a second heading the page grew beside it.
  expect( container.querySelector( '.ptb-top h1' ), where ).not.toBeNull();
  expect( tops[ 0 ].querySelectorAll( 'button, a' ), where ).toHaveLength( 0 );
  expect( tops[ 0 ].textContent || '', where ).not.toContain( '₹' );
}

beforeEach( () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState( {}, '', '/' );
} );

afterEach( () => {
  cleanup();
  cartLib.clearCart();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState( {}, '', '/' );
} );

describe( '/cart/ keeps the hero once a customer is signed in', () => {
  it( 'renders the band in the signed-in render as well as the signed-out one', async () => {
    cartLib.addItem( KIOSK(), 2 );

    signedOut();
    const out = render( <Cart /> );
    await screen.findByText( 'Kiosk' );
    expectBand( out.container, 'Your cart', 'signed out' );
    out.unmount();
    vi.restoreAllMocks();

    signedIn();
    const fetchMock = stubFetch( PROFILE_READY );
    const { container } = render( <Cart /> );
    // The mount effect's readiness read is what proves the signed-in path was actually taken.
    await waitFor( () => expect( fetchMock ).toHaveBeenCalled() );
    expect( JSON.parse( String( fetchMock.mock.calls[ 0 ][ 1 ].body ) ).action ).toBe( 'profile' );
    expect( String( fetchMock.mock.calls[ 0 ][ 0 ] ) )
      .toBe( `${ API_BASE }/ecommerce/prepare-checkout` );
    // The identity card only renders on 'ready', so reaching it means the richest signed-in body
    // is mounted rather than the loading or empty one.
    expect( await screen.findByText( 'asha@example.com' ) ).toBeInTheDocument();
    expectBand( container, 'Your cart', 'signed in' );
    expect( container.textContent )
      .toContain( 'Review what you have added before you check out.' );
  } );
} );

describe( '/checkout/success/ keeps the hero once a customer is signed in', () => {
  it( 'renders the band on the verified-paid render as well as the unverified one', async () => {
    signedOut();
    const out = render( <CheckoutSuccess /> );
    // No ?a=, so the honest answer is the holding heading - and the band is still the h1.
    expectBand( out.container, 'Order confirmation unavailable', 'signed out' );
    out.unmount();
    vi.restoreAllMocks();

    window.history.replaceState( {}, '', '/checkout/success/?a=attempt-1' );
    signedIn();
    stubFetch( { attempt: { status: 'PAYMENT_PAID', orderNumber: 'WD-ORD-VERIFIED' } } );
    const { container } = render( <CheckoutSuccess /> );
    expect( await screen.findByRole( 'heading', { name: 'Payment successful' } ) )
      .toBeInTheDocument();
    expect( screen.getByText( 'WD-ORD-VERIFIED' ) ).toBeInTheDocument();
    expectBand( container, 'Payment successful', 'signed in' );
  } );
} );

describe( '/checkout/status/ keeps the hero once a customer is signed in', () => {
  it( 'renders the band on the paid render as well as the holding one', async () => {
    signedOut();
    const out = render( <CheckoutStatus /> );
    expectBand( out.container, 'Nothing to show here', 'signed out' );
    out.unmount();
    vi.restoreAllMocks();

    window.history.replaceState( {}, '', '/checkout/status/?a=attempt-1' );
    signedIn();
    stubFetch( { attempt: {
      status: 'PAYMENT_PAID', orderNumber: 'WD-ORD-VERIFIED', amountPaise: 121481, currency: 'INR',
    } } );
    const { container } = render( <CheckoutStatus /> );
    expect( await screen.findByRole( 'heading', { name: 'Payment received' } ) )
      .toBeInTheDocument();
    expect( screen.getByText( 'WD-ORD-VERIFIED' ) ).toBeInTheDocument();
    // The paid view is the one that grows an actions row, so the band must still be the only h1
    // and must still carry no link - which is what expectBand decides.
    expectBand( container, 'Payment received', 'signed in' );
    expect( container.querySelectorAll( '.co-actions a' ).length ).toBeGreaterThan( 0 );
  } );
} );
