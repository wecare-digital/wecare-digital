import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Cart from '../pages/cart';
import * as cart from '../lib/cart';
import * as customerAuth from '../lib/customerAuth';
import type { ShopProduct } from '../content/shop';

/**
 * THE `?basket=` CLAIM EFFECT on /cart/.
 *
 * A customer sends their cart in the WhatsApp catalogue and gets a link to
 * `/cart/?basket=<token>`. Opening it while signed in merges the lines into their own Wix cart.
 *
 * What these pin, and why each one would regress silently:
 *   1. IT FIRES ONCE. The claim is a server-side SINGLE-USE write, so a double invoke renders a
 *      refusal for a claim that actually succeeded. React 19 StrictMode double-invokes effects in
 *      development, which makes this a real failure mode rather than a hypothetical.
 *   2. IT STRIPS THE PARAMETER ON SUCCESS. Leaving the token in the address bar means a refresh
 *      re-posts a claim that can only fail.
 *   3. IT RENDERS ONE HONEST LINE ON A REFUSAL - and leaves the parameter alone, so a reload shows
 *      the same answer rather than a silently different page.
 *   4. IT DOES NOT FETCH WITHOUT THE PARAMETER. Most visits have no `?basket=`, and the static
 *      export's no-fetch-at-render property has to survive this feature.
 *   5. NO SESSION ROUTES TO SIGN-IN, reusing the existing flow and reimplementing none of it.
 *   6. NO AMOUNT IS SENT OR SHOWN. The claim is not a quote.
 */

const PRODUCT: ShopProduct = {
  id: 'wix-abc-123',
  name: 'Kiosk',
  slug: 'kiosk',
  formattedPrice: '₹24,999.00',
  price: '24999.00',
  currency: 'INR',
  inStock: true,
  tagline: 'Put your location to work.',
  body: [ 'You already have the place.' ],
};

const TOKEN = 'wa-basket-token-abcdefghijklmnop';

/** Point `window.location` at a URL with (or without) `?basket=`, and record `assign` calls. */
function setLocation ( search: string ) {
  const assign = vi.fn();
  const replaceState = vi.fn();
  Object.defineProperty( window, 'location', {
    configurable: true,
    writable: true,
    value: {
      href: `https://wecare.digital/cart/${ search }`,
      origin: 'https://wecare.digital',
      pathname: '/cart/',
      search,
      hash: '',
      assign,
    },
  } );
  Object.defineProperty( window, 'history', {
    configurable: true,
    writable: true,
    value: { replaceState },
  } );
  return { assign, replaceState };
}

function signedIn () {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( {
    accessToken: 'fixture-access-token',
    idToken: 'fixture-id-token',
    expiresAt: Date.now() + 3_600_000,
    phone: '+918100640044',
  } as unknown as ReturnType<typeof customerAuth.getSession> );
}

function signedOut () {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
}

/** A fetch stub that answers the claim with `status`, and every other POST with a benign reply. */
function stubFetch ( status: string, extra: Record<string, unknown> = {} ) {
  const fetchMock = vi.fn( async ( _url: string, init?: RequestInit ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    if ( body.action === 'claim-basket' )
    {
      return { ok: true, status: 200, json: async () => ( { status, ...extra } ) };
    }
    // The mount's readiness probe. Answering PROFILE_REQUIRED keeps it out of the way.
    return { ok: true, status: 200, json: async () => ( { status: 'PROFILE_REQUIRED' } ) };
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

const claims = ( fetchMock: ReturnType<typeof stubFetch> ) =>
  fetchMock.mock.calls.filter(
    ( [ , init ] ) => JSON.parse( String( ( init as RequestInit )?.body || '{}' ) )
      .action === 'claim-basket' );

beforeEach( () => {
  window.localStorage.clear();
  cart.addItem( PRODUCT, 1 );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'the claim fires once, on arrival, only with a token', () => {
  it( 'posts exactly one claim-basket for one ?basket= parameter', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    const fetchMock = stubFetch( 'BASKET_CLAIMED', { mergedLines: 2 } );

    render( <Cart /> );

    await waitFor( () => expect( claims( fetchMock ).length ).toBe( 1 ) );
    // Settle any follow-up renders, then confirm it stayed at one.
    await new Promise( resolve => setTimeout( resolve, 0 ) );
    expect( claims( fetchMock ).length ).toBe( 1 );
  } );

  it( 'sends the token and the action and no amount of any kind', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    const fetchMock = stubFetch( 'BASKET_CLAIMED', { mergedLines: 1 } );

    render( <Cart /> );

    await waitFor( () => expect( claims( fetchMock ).length ).toBe( 1 ) );
    const [ url, init ] = claims( fetchMock )[ 0 ];
    expect( String( url ) ).toContain( '/ecommerce/prepare-checkout' );
    const body = JSON.parse( String( ( init as RequestInit ).body ) );
    expect( body ).toEqual( { action: 'claim-basket', basket: TOKEN } );
    // The authority is the session, not the payload.
    expect( ( init as RequestInit ).headers ).toMatchObject( {
      Authorization: 'Bearer fixture-access-token',
    } );
    const serialised = JSON.stringify( body ).toLowerCase();
    for ( const forbidden of [ 'paise', 'amount', 'price', 'total', 'currency', 'phone' ] )
    {
      expect( serialised ).not.toContain( forbidden );
    }
  } );

  it( 'posts no claim at all when there is no ?basket= parameter', async () => {
    setLocation( '' );
    signedIn();
    const fetchMock = stubFetch( 'BASKET_CLAIMED' );

    render( <Cart /> );

    await waitFor( () => expect( screen.getByText( 'Kiosk' ) ).toBeInTheDocument() );
    expect( claims( fetchMock ).length ).toBe( 0 );
  } );
} );

describe( 'success', () => {
  it( 'strips the ?basket= parameter from the URL', async () => {
    const { replaceState } = setLocation( `?basket=${ TOKEN }` );
    signedIn();
    stubFetch( 'BASKET_CLAIMED', { mergedLines: 2 } );

    render( <Cart /> );

    await waitFor( () => expect( replaceState ).toHaveBeenCalled() );
    const target = String( replaceState.mock.calls[ 0 ][ 2 ] );
    expect( target ).toBe( '/cart/' );
    expect( target ).not.toContain( 'basket' );
  } );

  it( 'says nothing on success - the items on screen are the message', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    stubFetch( 'BASKET_CLAIMED', { mergedLines: 2 } );

    const { container } = render( <Cart /> );

    await waitFor( () => expect( screen.getByText( 'Kiosk' ) ).toBeInTheDocument() );
    expect( container.querySelector( '[data-wc-basket-claim]' ) ).toBeNull();
  } );
} );

describe( 'refusal', () => {
  it( 'renders one honest line and does not strip the parameter', async () => {
    const { replaceState } = setLocation( `?basket=${ TOKEN }` );
    signedIn();
    stubFetch( 'BASKET_UNAVAILABLE' );

    render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( /This cart link is no longer available/i ) ).toBeInTheDocument() );
    expect( replaceState ).not.toHaveBeenCalled();
  } );

  it( 'tells the customer their website cart is in the way, when it is', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    stubFetch( 'BASKET_CART_IN_USE', { handoffLines: 2 } );

    render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( /already has items in it/i ) ).toBeInTheDocument() );
  } );

  it( 'reports a lost request as lost rather than as a refusal', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    vi.stubGlobal( 'fetch', vi.fn().mockRejectedValue( new Error( 'offline' ) ) );

    render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( /could not open your WhatsApp cart/i ) ).toBeInTheDocument() );
  } );

  it( 'shows no amount in any claim message', async () => {
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    stubFetch( 'BASKET_UNAVAILABLE' );

    const { container } = render( <Cart /> );

    await waitFor( () => expect(
      container.querySelector( '[data-wc-basket-claim]' ) ).not.toBeNull() );
    const line = container.querySelector( '[data-wc-basket-claim]' )?.textContent || '';
    expect( line ).not.toMatch( /₹|\d{2,}/ );
  } );
} );

describe( 'no session', () => {
  it( 'routes to the existing sign-in flow and returns to this URL', async () => {
    const { assign } = setLocation( `?basket=${ TOKEN }` );
    signedOut();
    const fetchMock = stubFetch( 'BASKET_CLAIMED' );

    render( <Cart /> );

    await waitFor( () => expect( assign ).toHaveBeenCalled() );
    const target = String( assign.mock.calls[ 0 ][ 0 ] );
    expect( target ).toContain( '/account/sign-in/' );
    // The token survives the round trip, so the claim happens after sign-in rather than being lost.
    expect( decodeURIComponent( target ) ).toContain( `basket=${ TOKEN }` );
    expect( claims( fetchMock ).length ).toBe( 0 );
  } );
} );
