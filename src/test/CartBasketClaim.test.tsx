import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Cart from '../pages/cart';
import * as cart from '../lib/cart';
import * as customerAuth from '../lib/customerAuth';
import { safeLocalReturnPath } from '../lib/safeReturnPath';
import { SHOP_PRODUCTS } from '../content/shop';
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
 *   5. NO SESSION ROUTES TO SIGN-IN AND THE CLAIM STILL HAPPENS AFTERWARDS. This is the normal
 *      case for a link opened in WhatsApp's in-app browser, and it is the one that used to fail
 *      silently: `safeLocalReturnPath` strips the query from the `return` value, so the token
 *      cannot ride back in the URL and is stashed out of band instead. The round trip is walked
 *      through the real validator rather than asserted on the outgoing URL alone.
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

/**
 * A REAL product from the committed catalogue snapshot, which the claim tests need and `PRODUCT`
 * above cannot be.
 *
 * `mergeClaimedLines` resolves a claimed line through `SHOP_PRODUCTS` - the claim carries a
 * catalogue reference and a quantity and no name or price, so the name on screen has to come from
 * the snapshot. A hand-written fixture is absent from `SHOP_PRODUCTS` and would therefore be
 * skipped, which would make the journey test pass against a page that merged nothing.
 *
 * Chosen with EXACTLY ONE in-stock variant, so the cart line's rendered name is the product's own
 * name (`addItem` appends a variant label only for a multi-variant product), and with a different
 * name from `PRODUCT` so `getByText` cannot match the seeded line instead of the claimed one.
 */
const CATALOGUE_PRODUCT: ShopProduct = SHOP_PRODUCTS.find(
  product => product.name !== PRODUCT.name
    && ( product.variants || [] ).filter( variant => variant.inStock ).length === 1 )!;
const CATALOGUE_VARIANT = ( CATALOGUE_PRODUCT.variants || [] )
  .find( variant => variant.inStock )!;

/** The Wix Stores app id `toLineItems()` sends. Repeated here for the same reason it is there. */
const WIX_STORES_APP_ID = '215238eb-22a5-4c36-9e7b-e7c08025e04e';

const PREPARE_URL = '/ecommerce/prepare-checkout';

/** The `action:'profile'` reply for a customer who can pay right now, so no editor intervenes. */
const PROFILE_READY = {
  status: 'PROFILE_READY',
  contactId: 'contact-1',
  name: 'Asha Sen',
  firstName: 'Asha',
  lastName: 'Sen',
  email: 'asha@example.com',
  phone: '+918100640044',
  emailVerified: true,
  addressComplete: true,
  address: {
    addressLine1: '12 Dalhousie Square',
    addressLine2: '',
    locality: '',
    city: 'Kolkata',
    state: 'West Bengal',
    postalCode: '700001',
    country: 'India',
    countryCode: 'IN',
    fullAddress: '12 Dalhousie Square, Kolkata, West Bengal, 700001, India',
  },
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

/**
 * A fetch stub that answers the FIRST claim one way and the second another.
 *
 * For the stale-saved-cart retry: the server reports `BASKET_CART_IN_USE`, the page retries once
 * with `resetCart: true`, and that attempt claims. Keyed on call order rather than on the body, so
 * a retry that forgot to send `resetCart` would still be answered - and the assertion on the
 * recorded body is what catches that, rather than the stub quietly refusing.
 */
function stubFetchSequence ( answers: Array<Record<string, unknown>> ) {
  let claimed = 0;
  const fetchMock = vi.fn( async ( _url: string, init?: RequestInit ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    if ( body.action === 'claim-basket' )
    {
      const answer = answers[ Math.min( claimed, answers.length - 1 ) ];
      claimed += 1;
      return { ok: true, status: 200, json: async () => answer };
    }
    return { ok: true, status: 200, json: async () => ( { status: 'PROFILE_REQUIRED' } ) };
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

/**
 * Just enough of a `vi.fn()` to read its recorded calls.
 *
 * Deliberately NOT `ReturnType<typeof stubFetch>`: the three stubs in this file return mocks with
 * different reply types, and keying the readers to one of them makes passing another a type error
 * about `json()` rather than about anything that matters.
 */
type RecordedFetch = { mock: { calls: ReadonlyArray<ReadonlyArray<unknown>> } };

/** The request body of a recorded call. */
const bodyOf = ( call: ReadonlyArray<unknown> ): Record<string, unknown> =>
  JSON.parse( String( ( call[ 1 ] as RequestInit | undefined )?.body || '{}' ) );

const claims = ( fetchMock: RecordedFetch ) =>
  fetchMock.mock.calls.filter( call => bodyOf( call ).action === 'claim-basket' );

/** The claim's reply for a basket holding the one catalogue product this suite knows about. */
const claimedLinesFor = ( quantity = 1 ) => [ {
  productId: CATALOGUE_PRODUCT.id,
  variantId: CATALOGUE_VARIANT.id,
  quantity,
} ];

/**
 * A stub for the WHOLE journey: the claim, the readiness probe, and the prepare that follows.
 *
 * Dispatched on the request's `action` rather than on call order, because the mount probe and the
 * claim race and a positional queue would answer one of them with the other's reply.
 */
function stubJourney ( claim: Record<string, unknown> ) {
  const fetchMock = vi.fn( async ( _url: string, init?: RequestInit ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    if ( body.action === 'claim-basket' )
    {
      return { ok: true, status: 200, json: async () => claim };
    }
    if ( body.action === 'profile' )
    {
      return { ok: true, status: 200, json: async () => PROFILE_READY };
    }
    // The prepare. Answered with the one terminal status that asserts nothing about money and
    // leaves the cart alone, so this file never has to model a payment rail.
    return { ok: true, status: 200, json: async () => ( {
      status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-claim-1', currency: 'INR',
    } ) };
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

const prepares = ( fetchMock: RecordedFetch ) =>
  fetchMock.mock.calls.map( bodyOf ).filter( body => body.action === 'prepare' );

beforeEach( () => {
  window.localStorage.clear();
  // The sign-in stash lives here. Cleared between tests so a round-trip test cannot leave a token
  // behind for the next one - which is the same single-use property the page relies on.
  window.sessionStorage.clear();
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
    stubFetch( 'BASKET_CLAIMED',
      { mergedLines: 1, lines: claimedLinesFor( 1 ) } );

    const { container } = render( <Cart /> );

    // The CLAIMED item, not the seeded one - which is what makes "the items are the message" an
    // honest claim rather than an assertion about a line the test put there itself.
    await waitFor( () => expect(
      screen.getByText( CATALOGUE_PRODUCT.name ) ).toBeInTheDocument() );
    expect( container.querySelector( '[data-wc-basket-claim]' ) ).toBeNull();
  } );

  it( 'puts the claimed lines in a cart that did not hold them, and in the next checkout POST',
    async () => {
      /*
       * THE WHOLE JOURNEY, end to end, and the one assertion the previous version of this file
       * could not make.
       *
       * The claim merges the lines into the SERVER-side Wix cart. The cart this page renders and
       * the basket `prepare` is given both come from localStorage, so a reply carrying only
       * `mergedLines` left the customer looking at an unchanged cart - and the following checkout
       * reconciled the claimed lines back OUT of the Wix cart, because `_reconcile_saved_cart`
       * makes the Wix cart match the REQUEST.
       *
       * Started from an EMPTY cart deliberately: a seeded line would let a page that merged
       * nothing still show something and still post something.
       */
      window.localStorage.clear();
      setLocation( `?basket=${ TOKEN }` );
      signedIn();
      const fetchMock = stubJourney( {
        status: 'BASKET_CLAIMED', channel: 'whatsapp', mergedLines: 1,
        lines: claimedLinesFor( 2 ),
      } );

      render( <Cart /> );

      await waitFor( () => expect(
        screen.getByText( CATALOGUE_PRODUCT.name ) ).toBeInTheDocument() );

      fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );
      await waitFor( () => expect( prepares( fetchMock ) ).toHaveLength( 1 ) );

      expect( prepares( fetchMock )[ 0 ].lineItems ).toEqual( [ {
        catalogReference: {
          appId: WIX_STORES_APP_ID,
          catalogItemId: CATALOGUE_PRODUCT.id,
          options: { variantId: CATALOGUE_VARIANT.id },
        },
        quantity: 2,
      } ] );
    } );

  it( 'merges into the cart rather than replacing it, through the ordinary cart writer',
    async () => {
      // The seeded line survives, because a claim adds to the cart and does not take it over.
      // `CART_CHANGED_EVENT` is the header badge's signal, and it fires because the merge goes
      // through `addItem` -> `writeCart` like every other line.
      setLocation( `?basket=${ TOKEN }` );
      signedIn();
      const changes: unknown[] = [];
      window.addEventListener( cart.CART_CHANGED_EVENT, event => changes.push( event ) );
      stubFetch( 'BASKET_CLAIMED', { mergedLines: 1, lines: claimedLinesFor( 1 ) } );

      render( <Cart /> );

      await waitFor( () => expect(
        screen.getByText( CATALOGUE_PRODUCT.name ) ).toBeInTheDocument() );
      expect( screen.getByText( PRODUCT.name ) ).toBeInTheDocument();
      expect( cart.readCart() ).toHaveLength( 2 );
      expect( changes.length ).toBeGreaterThan( 0 );
    } );

  it( 'says so when it could place none of the claimed lines, instead of looking unchanged',
    async () => {
      /*
       * A product in the live Wix catalogue - and therefore in the WhatsApp catalogue projected
       * from it - but absent from the snapshot committed with this build. Added in Wix since the
       * last catalogue sync is exactly that case.
       *
       * Saying nothing here would reproduce the defect the returned lines exist to fix: a
       * successful claim that is indistinguishable from a refusal.
       */
      window.localStorage.clear();
      setLocation( `?basket=${ TOKEN }` );
      signedIn();
      stubFetch( 'BASKET_CLAIMED', { mergedLines: 1, lines: [ {
        productId: '00000000-0000-4000-8000-000000000000',
        variantId: '00000000-0000-4000-8000-000000000001',
        quantity: 1,
      } ] } );

      render( <Cart /> );

      await waitFor( () => expect(
        screen.getByText( /cannot show those items yet/i ) ).toBeInTheDocument() );
      expect( cart.readCart() ).toHaveLength( 0 );
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

  it( 'tells the customer their website cart is in the way, when it really is', async () => {
    // The seeded `PRODUCT` line is what makes the sentence true: the browser cart is NOT empty,
    // so "empty it and open the link again" names something the customer can do.
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    const fetchMock = stubFetch( 'BASKET_CART_IN_USE', { handoffLines: 2 } );

    render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( /already has items in it/i ) ).toBeInTheDocument() );
    // ONE claim. With items on screen there is nothing to release, so no retry is attempted.
    expect( claims( fetchMock ).length ).toBe( 1 );
    expect( bodyOf( claims( fetchMock )[ 0 ] ).resetCart ).toBeUndefined();
  } );

  it( 'releases a stale saved cart and retries once when this cart is already empty', async () => {
    /*
     * `BASKET_CART_IN_USE` WAS A DEAD END FOR ANYONE WHO HAD PAID ONCE.
     *
     * The server condition is the `CUSTOMERCART#<phone>` pointer, which lives thirty days and
     * survives the payment that consumed its cart - nothing releases it at payment, and
     * `clearCart()` only empties localStorage. So the instruction "empty your website cart" named
     * an action with no way to perform it, and the link kept returning the same answer.
     *
     * With an empty cart here there is nothing of the customer's to lose, so the page retries once
     * with `resetCart: true` - the same release the existing "Start a new cart" control performs.
     */
    window.localStorage.clear();
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    const fetchMock = stubFetchSequence( [
      { status: 'BASKET_CART_IN_USE', handoffLines: 1 },
      { status: 'BASKET_CLAIMED', mergedLines: 1, lines: claimedLinesFor( 1 ) },
    ] );

    const { container } = render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( CATALOGUE_PRODUCT.name ) ).toBeInTheDocument() );
    const posted = claims( fetchMock ).map( bodyOf );
    expect( posted ).toHaveLength( 2 );
    expect( posted[ 0 ].resetCart ).toBeUndefined();
    expect( posted[ 1 ].resetCart ).toBe( true );
    expect( posted[ 1 ].basket ).toBe( TOKEN );
    // The retry succeeded, so there is no sentence to show and no token left in the URL.
    expect( container.querySelector( '[data-wc-basket-claim]' ) ).toBeNull();
  } );

  it( 'retries at most once, so a second refusal is reported rather than looped', async () => {
    window.localStorage.clear();
    setLocation( `?basket=${ TOKEN }` );
    signedIn();
    const fetchMock = stubFetchSequence( [
      { status: 'BASKET_CART_IN_USE', handoffLines: 1 },
      { status: 'BASKET_CART_IN_USE', handoffLines: 1 },
    ] );

    render( <Cart /> );

    await waitFor( () => expect(
      screen.getByText( /already has items in it/i ) ).toBeInTheDocument() );
    expect( claims( fetchMock ).length ).toBe( 2 );
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
  it( 'routes to the existing sign-in flow and posts no claim', async () => {
    const { assign } = setLocation( `?basket=${ TOKEN }` );
    signedOut();
    const fetchMock = stubFetch( 'BASKET_CLAIMED' );

    render( <Cart /> );

    await waitFor( () => expect( assign ).toHaveBeenCalled() );
    expect( String( assign.mock.calls[ 0 ][ 0 ] ) ).toContain( '/account/sign-in/' );
    expect( claims( fetchMock ).length ).toBe( 0 );
  } );

  it( 'claims after an unauthenticated sign-in round trip, with the token the URL could not carry',
    async () => {
      /*
       * THE ROUND TRIP ITSELF, because asserting the token is in the OUTGOING url proves nothing:
       * the half that used to lose it is the validator on the way back.
       *
       * `src/pages/account/sign-in.tsx::returnPathFromUrl` reads `?return=` with
       * `URLSearchParams.get` -- which DECODES it -- and hands the result to `safeLocalReturnPath`.
       * That function lists `?` in `FORBIDDEN_CHARS` and re-emits the normalised allowlist member
       * rather than the input, so `%2Fcart%2F%3Fbasket%3D<token>` arrives back as a bare `/cart/`.
       * This test walks that exact pipeline with the exact string `cart.tsx` constructs, asserts
       * the token really is gone from the surviving path, and then proves the claim still happens
       * from the stash. That is the normal case, not an edge: a link opened in WhatsApp's in-app
       * browser usually has no session.
       */
      const { assign } = setLocation( `?basket=${ TOKEN }` );
      signedOut();
      const outbound = render( <Cart /> );
      await waitFor( () => expect( assign ).toHaveBeenCalled() );
      const signInUrl = String( assign.mock.calls[ 0 ][ 0 ] );
      outbound.unmount();

      // Exactly what sign-in.tsx does with the value, and nothing this test invented.
      const raw = String( new URLSearchParams(
        new URL( signInUrl, 'https://wecare.digital' ).search ).get( 'return' ) || '' ).trim();
      expect( raw ).toBe( `/cart/?basket=${ TOKEN }` );
      const surviving = safeLocalReturnPath( raw );
      expect( surviving ).toBe( '/cart/' );
      expect( surviving ).not.toContain( 'basket' );
      expect( surviving ).not.toContain( TOKEN );

      // Back at the bare path the allowlist allowed, now signed in. An empty cart deliberately:
      // a seeded line would let a page that merged nothing still show something.
      window.localStorage.clear();
      setLocation( '' );
      signedIn();
      const fetchMock = stubFetch( 'BASKET_CLAIMED',
        { mergedLines: 1, lines: claimedLinesFor( 2 ) } );

      render( <Cart /> );

      await waitFor( () => expect( claims( fetchMock ).length ).toBe( 1 ) );
      expect( bodyOf( claims( fetchMock )[ 0 ] ) )
        .toEqual( { action: 'claim-basket', basket: TOKEN } );
      await waitFor( () => expect(
        screen.getByText( CATALOGUE_PRODUCT.name ) ).toBeInTheDocument() );
      expect( cart.readCart() ).toHaveLength( 1 );
      expect( cart.readCart()[ 0 ].quantity ).toBe( 2 );
    } );

  it( 'spends the stash once, so a later visit to /cart/ claims nothing', async () => {
    // The claim is a single-use server-side write, so a token left behind could only be refused --
    // and a refusal for a basket already in the cart is the confusing outcome the effect exists to
    // avoid. `basketTokenFromUrl()` clears the key as it reads it.
    const { assign } = setLocation( `?basket=${ TOKEN }` );
    signedOut();
    const outbound = render( <Cart /> );
    await waitFor( () => expect( assign ).toHaveBeenCalled() );
    outbound.unmount();

    setLocation( '' );
    signedIn();
    const spent = stubFetch( 'BASKET_CLAIMED', { mergedLines: 1, lines: claimedLinesFor( 1 ) } );
    const first = render( <Cart /> );
    await waitFor( () => expect( claims( spent ).length ).toBe( 1 ) );
    first.unmount();

    const later = stubFetch( 'BASKET_CLAIMED', { mergedLines: 1, lines: claimedLinesFor( 1 ) } );
    render( <Cart /> );

    await waitFor( () => expect( screen.getByText( PRODUCT.name ) ).toBeInTheDocument() );
    expect( claims( later ).length ).toBe( 0 );
  } );

  it( 'leaves safeLocalReturnPath strict: a query string is still refused', () => {
    /*
     * THE FIX MUST NOT BE A LOOSENING. `safeLocalReturnPath` refuses `?` and re-emits the
     * allowlist member precisely so an accepted path cannot carry attacker-chosen state, and the
     * stash exists because that refusal is correct. Pinned here so a future "simplification" that
     * carries the token in the URL after all fails this file rather than reopening the hole.
     */
    expect( safeLocalReturnPath( `/cart/?basket=${ TOKEN }` ) ).toBe( '/cart/' );
    expect( safeLocalReturnPath( '/orders/?next=//evil' ) ).toBe( '/cart/' );
    expect( safeLocalReturnPath( '//evil' ) ).toBe( '/cart/' );
    expect( safeLocalReturnPath( '/workspace/access' ) ).toBe( '/cart/' );
    // Unchanged in the accepting direction too, so this is a pin and not half of one.
    expect( safeLocalReturnPath( '/orders/' ) ).toBe( '/orders/' );
  } );
} );
