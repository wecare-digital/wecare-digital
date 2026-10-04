import React from 'react';
import {
  afterEach, beforeEach, describe, expect, it, vi,
} from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import fs from 'fs';
import path from 'path';

import * as cart from '../lib/cart';
import type { ShopProduct } from '../content/shop';
import type { StoredAddress } from '../components/AddressFields';
import * as customerAuth from '../lib/customerAuth';

/**
 * THE SHARED CheckoutProfile DOUBLE.
 *
 * Three things changed here when the cart page became status-first, and each one is load-bearing:
 *
 *   1. `onReady` now hands back the WHOLE `CheckoutProfileValue` - `firstName`, `lastName`,
 *      `addressComplete` and a real `address`. The page derives the editor state from
 *      `deriveStatus('PROFILE_READY', next.addressComplete)`, so a payload missing
 *      `addressComplete` derives `'required'` and every flow in this file would stop at the
 *      editor instead of reaching `prepare`.
 *   2. It reports the MODE it was mounted in, as `data-mode`. The page mounts a fresh editor per
 *      affordance, and "the editor opened in address mode" is the assertion several cases below
 *      need. The real fields behind each mode are pinned in `CheckoutProfile.test.tsx` and
 *      `AddressFields` - this double only has to prove WHICH editor the page asked for.
 *   3. It offers a second save, `Save without an address`, which returns `addressComplete:false`.
 *      That is the save the page must answer by KEEPING an address form mounted, and there is no
 *      other way to reach it from a double whose only save is a complete one.
 *
 * The fixtures are referenced from inside the click handlers, never at factory-evaluation time:
 * `vi.mock` is hoisted above the module body, so a reference evaluated as the factory runs would
 * hit the temporal dead zone.
 */
vi.mock( '../components/CheckoutProfile', () => ( {
  default: ( { mode, onReady }: {
    mode?: string;
    onReady: ( value: Record<string, unknown> ) => void;
  } ) => (
    <div data-testid="checkout-profile" data-mode={ mode || 'create' }>
      <button type="button" onClick={ () => onReady( { ...SAVED_PROFILE } ) }>
        Complete checkout details
      </button>
      <button
        type="button"
        onClick={ () => onReady( { ...SAVED_PROFILE, addressComplete: false, address: null } ) }
      >
        Save without an address
      </button>
    </div>
  ),
} ) );

import Cart from '../pages/cart';
import CheckoutStatus, { viewFor } from '../pages/checkout/status';

/**
 * The /shop/ -> Cart V2 -> checkout wiring, tested the way ShopCatalogue.test.tsx tests the
 * catalogue: against mocked fetch and mocked storage, asserting logic and DOM presence only. jsdom
 * cannot read a computed style, so the design system (lime CTA, dark-green price, clearances) is
 * left to the browser harnesses; here we prove the CONTRACT.
 *
 * The four load-bearing properties, each its own describe:
 *   1. the cart store round-trips and is SSR-safe;
 *   2. toLineItems() emits references and quantities ONLY - no price-like key ever reaches the wire;
 *   3. a PAYMENT_INITIATION_DISABLED response reaches the honest outcome and renders no pay button;
 *   4. proceeding with no session routes to sign-in and never calls the create endpoint;
 *   plus a 409 readiness-blocked mapping to the "no charge was made" copy.
 *
 * ...and, since the page became status-first, a fifth: the readiness question is asked BEFORE
 * anything is rendered, and a failed answer never blocks a payable customer.
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

const OTHER: ShopProduct = {
  id: 'wix-def-456',
  name: 'Merchandise',
  slug: 'merchandise',
  formattedPrice: '₹599.00',
  price: '599.00',
  currency: 'INR',
  inStock: true,
  tagline: 'Wear it.',
  body: [ 'A shirt.' ],
};

/** A real nine-key StoredAddress, including the server-composed `fullAddress` the card renders. */
const ADDRESS_FIXTURE: StoredAddress = {
  addressLine1: '12 MG Road',
  addressLine2: 'Flat 3B',
  locality: '',
  city: 'Bengaluru',
  state: 'Karnataka',
  postalCode: '560001',
  country: 'India',
  countryCode: 'IN',
  fullAddress: '12 MG Road, Flat 3B, Bengaluru, Karnataka, 560001, India',
};

/** What a completed save hands back - the shape `CheckoutProfileValue` promises. */
const SAVED_PROFILE = {
  contactId: 'contact-1',
  name: 'Asha Sen',
  firstName: 'Asha',
  lastName: 'Sen',
  email: 'asha@example.com',
  phone: '+919330994400',
  addressComplete: true,
  address: ADDRESS_FIXTURE,
};

/** The `action:'profile'` reply for a customer who can pay right now: all ten keys. */
const PROFILE_READY = {
  status: 'PROFILE_READY',
  ...SAVED_PROFILE,
  emailVerified: true,
};

/** The whole of the no-usable-profile reply. One key, and nothing else is present. */
const PROFILE_REQUIRED = { status: 'PROFILE_REQUIRED' };

const PREPARE_URL = '/ecommerce/prepare-checkout';
const VERIFY_URL = '/ecommerce/verify-callback';

/** The page's own post-save retry wait. Kept in step with cart.tsx's POST_SAVE_RETRY_MS. */
const RETRY_WAIT_MS = 1200;

/** Capture where the page tries to navigate, without jsdom's "not implemented" throw. */
let navigatedTo: string;

beforeEach( () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
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
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
} );

function signedIn ( accessToken = 'tok-123' ): void {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( {
    accessToken, expiresAt: Date.now() + 3_600_000,
  } );
}

/** One scripted reply: a response spec, or an Error to reject with. */
type StubReply = { ok?: boolean; status?: number; body?: unknown } | Error;

function resolveReply ( spec: StubReply ): Promise<unknown> {
  if ( spec instanceof Error ) return Promise.reject( spec );
  return Promise.resolve( {
    ok: spec.ok === undefined ? true : spec.ok,
    status: spec.status === undefined ? 200 : spec.status,
    json: async () => ( spec.body === undefined ? {} : spec.body ),
  } );
}

/**
 * ONE fetch double, dispatching on the request URL **plus** `body.action`, never on ordering.
 *
 * WHY THIS REPLACED `mockResolvedValueOnce` CHAINS. The page now asks the readiness question on
 * mount, so a queue of positional replies hands the `action:'profile'` call whatever was meant for
 * `prepare`, and every subsequent reply lands one place late. Dispatching on what was ASKED is
 * order-independent: it survives the mount call, the post-save retry, and any call a later change
 * adds. A single spec is sticky (it answers every matching request); an array is a script, with
 * the last entry answering every request after it.
 *
 * `profile` defaults to PROFILE_REQUIRED - the first-time shopper every pre-existing case in this
 * file describes - so a case only names it when its own subject is the readiness answer.
 */
function stubFetch ( routes: {
  profile?: StubReply | StubReply[];
  prepare?: StubReply | StubReply[];
  verify?: StubReply | StubReply[];
} = {} ) {
  const queues: Record<string, StubReply[]> = {
    profile: toQueue( routes.profile, { body: PROFILE_REQUIRED } ),
    prepare: toQueue( routes.prepare, undefined ),
    verify: toQueue( routes.verify, undefined ),
  };

  function toQueue ( spec: StubReply | StubReply[] | undefined, fallback: StubReply | undefined ): StubReply[] {
    if ( spec === undefined ) return fallback === undefined ? [] : [ fallback ];
    return Array.isArray( spec ) ? [ ...spec ] : [ spec ];
  }

  function next ( name: string ): StubReply {
    const queue = queues[ name ];
    if ( !queue || queue.length === 0 )
    {
      throw new Error( `CartCheckout stub: no '${ name }' reply configured` );
    }
    return queue.length === 1 ? queue[ 0 ] : ( queue.shift() as StubReply );
  }

  const fetchMock = vi.fn( ( url: string, init?: { body?: string } ) => {
    const target = String( url );
    let action = '';
    try { action = String( JSON.parse( String( init?.body || '{}' ) ).action || '' ); }
    catch { action = ''; }
    if ( target.includes( VERIFY_URL ) ) return resolveReply( next( 'verify' ) );
    if ( target.includes( PREPARE_URL ) )
    {
      return resolveReply( next( action === 'profile' ? 'profile' : 'prepare' ) );
    }
    throw new Error( `CartCheckout stub: unexpected request to ${ target }` );
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

type RecordedCall = { url: string; init: any; body: any };

/**
 * The requests that went to one endpoint, optionally narrowed to one action, with their bodies
 * already parsed. Asserting on WHICH calls happened rather than on WHERE they sat is what lets the
 * mount-time readiness call and the post-save retry exist without rewriting every expectation.
 */
function callsTo ( fetchMock: any, fragment: string, action?: string ): RecordedCall[] {
  return ( fetchMock.mock.calls as any[][] )
    .map( ( call ) => {
      let body: any = {};
      try { body = JSON.parse( String( call[ 1 ]?.body || '{}' ) ); }
      catch { body = {}; }
      return { url: String( call[ 0 ] ), init: call[ 1 ], body };
    } )
    .filter( ( recorded ) => recorded.url.includes( fragment )
      && ( action === undefined || String( recorded.body.action || '' ) === action ) );
}

/**
 * Settle the promise chains a click sets off, without `waitFor`.
 *
 * Used ONLY by the fake-timer cases: `waitFor` and `findBy*` poll on the very timer those tests
 * control, so they cannot make progress. This is the flush `CheckoutProfileResend.test.tsx` and
 * `VayuLokLive.test.tsx` use for the same reason.
 */
async function flush ( rounds = 8 ): Promise<void> {
  for ( let i = 0; i < rounds; i += 1 )
  {
    // eslint-disable-next-line no-await-in-loop
    await act( async () => { await Promise.resolve(); } );
  }
}

async function proceedPastProfile (): Promise<void> {
  fireEvent.click( await screen.findByRole( 'button', { name: 'Proceed' } ) );
  fireEvent.click( await screen.findByRole( 'button', { name: 'Complete checkout details' } ) );
  fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );
}

describe( 'the cart store', () => {
  it( 'adds, increments the same reference, and reports a count', () => {
    cart.addItem( PRODUCT, 1 );
    cart.addItem( PRODUCT, 2 );
    const items = cart.readCart();
    expect( items ).toHaveLength( 1 );
    expect( items[ 0 ].ref ).toBe( 'wix-abc-123' );
    expect( items[ 0 ].quantity ).toBe( 3 );
    expect( cart.cartCount() ).toBe( 3 );
  } );

  it( 'keeps distinct products as distinct lines', () => {
    cart.addItem( PRODUCT, 1 );
    cart.addItem( OTHER, 1 );
    expect( cart.readCart().map( i => i.ref ) ).toEqual( [ 'wix-abc-123', 'wix-def-456' ] );
  } );

  it( 'sets an exact quantity and removes a line when it hits zero', () => {
    cart.addItem( PRODUCT, 1 );
    cart.setQuantity( 'wix-abc-123', 5 );
    expect( cart.readCart()[ 0 ].quantity ).toBe( 5 );
    cart.setQuantity( 'wix-abc-123', 0 );
    expect( cart.readCart() ).toHaveLength( 0 );
  } );

  it( 'removes a line and clears the whole cart', () => {
    cart.addItem( PRODUCT, 1 );
    cart.addItem( OTHER, 1 );
    cart.removeItem( 'wix-abc-123' );
    expect( cart.readCart().map( i => i.ref ) ).toEqual( [ 'wix-def-456' ] );
    cart.clearCart();
    expect( cart.readCart() ).toHaveLength( 0 );
  } );

  it( 'survives a round-trip through storage', () => {
    cart.addItem( PRODUCT, 2 );
    // A fresh read parses what is actually persisted, not in-memory state.
    const raw = window.localStorage.getItem( 'wecare.cart.v1' );
    expect( raw ).toBeTruthy();
    expect( cart.readCart()[ 0 ].quantity ).toBe( 2 );
  } );

  it( 'tolerates corrupt storage rather than throwing', () => {
    window.localStorage.setItem( 'wecare.cart.v1', 'not json' );
    expect( cart.readCart() ).toEqual( [] );
  } );


  it( 'migrates a pre-productId single-variant row to the current Wix product and variant', () => {
    window.localStorage.setItem( 'wecare.cart.v1', JSON.stringify( [ {
      ref: 'kiosk',
      slug: 'kiosk',
      name: 'Kiosk',
      formattedPrice: '₹24,999.00',
      quantity: 2,
    } ] ) );

    const [ item ] = cart.readCart();
    expect( item.productId ).toBe( '00d4c72b-f694-441a-a192-e16f4b192440' );
    expect( item.variantId ).toBe( '2d072962-37c0-4821-9c02-2cc223448711' );
    expect( item.ref ).toBe(
      '00d4c72b-f694-441a-a192-e16f4b192440:2d072962-37c0-4821-9c02-2cc223448711',
    );
    expect( cart.toLineItems() ).toEqual( [ {
      catalogReference: {
        appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e',
        catalogItemId: '00d4c72b-f694-441a-a192-e16f4b192440',
        options: { variantId: '2d072962-37c0-4821-9c02-2cc223448711' },
      },
      quantity: 2,
    } ] );
  } );

  it( 'does not guess a variant for a legacy multi-variant merchandise row', () => {
    window.localStorage.setItem( 'wecare.cart.v1', JSON.stringify( [ {
      ref: 'f05c3a28-0d2f-4cae-ab6c-c0b68635b951',
      slug: 'merchandise',
      name: 'Merchandise',
      formattedPrice: '₹1,199.00',
      quantity: 1,
    } ] ) );

    const [ item ] = cart.readCart();
    expect( item.productId ).toBe( 'f05c3a28-0d2f-4cae-ab6c-c0b68635b951' );
    expect( item.variantId ).toBeUndefined();
    expect( cart.needsVariantSelection( item ) ).toBe( true );
    expect( cart.availableVariantsForItem( item ) ).toHaveLength( 10 );
  } );

  it( 'repairs a legacy merchandise row when the customer chooses a current variant', () => {
    window.localStorage.setItem( 'wecare.cart.v1', JSON.stringify( [ {
      ref: 'f05c3a28-0d2f-4cae-ab6c-c0b68635b951',
      slug: 'merchandise',
      name: 'Merchandise',
      formattedPrice: '₹1,199.00',
      quantity: 1,
    } ] ) );
    const [ item ] = cart.readCart();
    const target = cart.availableVariantsForItem( item )[ 0 ];

    const repaired = cart.setVariant( item.ref, target.id );
    expect( repaired[ 0 ].variantId ).toBe( target.id );
    expect( repaired[ 0 ].ref ).toBe(
      `f05c3a28-0d2f-4cae-ab6c-c0b68635b951:${target.id}`,
    );
    expect( cart.needsVariantSelection( repaired[ 0 ] ) ).toBe( false );
  } );

  it( 'is SSR-safe: reads return empty and writes are no-ops when window is undefined', () => {
    const realWindow = globalThis.window;
    // Simulate the server: no window at all. The guards in cart.ts must not touch storage.
    // @ts-expect-error deliberately removing window to exercise the SSR guard
    delete globalThis.window;
    try
    {
      expect( cart.readCart() ).toEqual( [] );
      expect( cart.cartCount() ).toBe( 0 );
      expect( () => cart.clearCart() ).not.toThrow();
      expect( () => cart.addItem( PRODUCT, 1 ) ).not.toThrow();
    }
    finally
    {
      globalThis.window = realWindow;
    }
  } );
} );

describe( 'toLineItems emits references and quantities ONLY', () => {
  it( 'maps each line to { catalogReference, quantity } and nothing else', () => {
    cart.addItem( PRODUCT, 2 );
    cart.addItem( OTHER, 1 );
    const lineItems = cart.toLineItems();
    expect( lineItems ).toEqual( [
      { catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e', catalogItemId: 'wix-abc-123' }, quantity: 2 },
      { catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e', catalogItemId: 'wix-def-456' }, quantity: 1 },
    ] );
    for ( const item of lineItems )
    {
      expect( Object.keys( item ).sort() ).toEqual( [ 'catalogReference', 'quantity' ] );
    }
  } );

  it( 'serialises with no price-like key anywhere in the payload', () => {
    // THE RULE THE WHOLE ARCHITECTURE RESTS ON: the browser never sends a financial figure. Assert
    // on the serialised string the fetch body would carry, so a stray key cannot slip through.
    cart.addItem( PRODUCT, 3 );
    const serialised = JSON.stringify( { action: 'create', lineItems: cart.toLineItems() } );
    for ( const forbidden of [ 'price', 'amount', 'formattedPrice', 'currency', 'total', 'paise' ] )
    {
      expect( serialised.toLowerCase() ).not.toContain( forbidden.toLowerCase() );
    }
    // The display price the cart holds must not have leaked into the payload.
    expect( serialised ).not.toContain( '24,999' );
    expect( serialised ).not.toContain( '24999' );
  } );
} );

describe( 'legacy cart option recovery', () => {
  it( 'blocks prepare and asks for an option until a legacy merchandise row is repaired', async () => {
    signedIn();
    const fetchMock = stubFetch( { profile: { body: PROFILE_READY } } );
    window.localStorage.setItem( 'wecare.cart.v1', JSON.stringify( [ {
      ref: 'f05c3a28-0d2f-4cae-ab6c-c0b68635b951',
      slug: 'merchandise',
      name: 'Merchandise',
      formattedPrice: '₹1,199.00',
      quantity: 1,
    } ] ) );

    render( <Cart /> );
    expect( await screen.findByText( 'Ready to pay' ) ).toBeTruthy();
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );

    expect( await screen.findByText(
      'Choose a current product option below before secure payment.',
    ) ).toBeTruthy();
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 0 );

    const select = await screen.findByRole( 'combobox', { name: /Choose option for Merchandise/ } );
    fireEvent.change( select, {
      target: { value: '00ebbae6-7025-4724-835e-37f4bffc2476' },
    } );
    expect( await screen.findByText(
      'Product option updated. Continue to secure payment.',
    ) ).toBeTruthy();
    expect( cart.readCart()[ 0 ].variantId ).toBe(
      '00ebbae6-7025-4724-835e-37f4bffc2476',
    );
  } );
} );

describe( 'the cart page proceed flow', () => {
  it( 'routes an anonymous shopper to sign-in and never calls create', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const fetchMock = vi.fn();
    vi.stubGlobal( 'fetch', fetchMock );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Proceed' } ) );

    await waitFor( () => expect( navigatedTo ).toContain( '/account/sign-in' ) );
    expect( navigatedTo ).toContain( 'return=/cart/' );
    // The auth gate must short-circuit BEFORE any create request - and the mount-time readiness
    // call must not fire for a visitor who has no session to ask about.
    expect( fetchMock ).not.toHaveBeenCalled();
  } );

  it( 'sends { action:prepare, lineItems, requestKey } with a Bearer token and no money', async () => {
    signedIn( 'tok-123' );
    const fetchMock = stubFetch( {
      prepare: { body: {
        status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-1', currency: 'INR',
      } },
    } );
    cart.addItem( PRODUCT, 2 );

    render( <Cart /> );
    await proceedPastProfile();

    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
    const [ prepare ] = callsTo( fetchMock, PREPARE_URL, 'prepare' );
    expect( prepare.url ).toContain( PREPARE_URL );
    expect( ( prepare.init.headers as Record<string, string> ).Authorization ).toBe( 'Bearer tok-123' );
    expect( prepare.body.action ).toBe( 'prepare' );
    expect( typeof prepare.body.requestKey ).toBe( 'string' );
    expect( prepare.body.requestKey.length ).toBeGreaterThan( 8 );
    expect( prepare.body.lineItems ).toEqual( [ { catalogReference: { appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e', catalogItemId: 'wix-abc-123' }, quantity: 2 } ] );
    // No financial figure on the wire.
    expect( prepare.init.body as string ).not.toMatch( /price|amount|currency|formattedPrice/i );
    // And the readiness question carried no address, no phone and no body beyond the action.
    const [ status ] = callsTo( fetchMock, PREPARE_URL, 'profile' );
    expect( status.body ).toEqual( { action: 'profile' } );
  } );

  it( 'answers PAYMENT_INITIATION_DISABLED inline, keeps the cart, and offers no pay button', async () => {
    signedIn();
    stubFetch( {
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-9' } },
    } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();

    /*
     * TWO PINNED BEHAVIOURS CHANGED HERE, AND BOTH WERE WRONG BEFORE.
     *
     * 1. IT NO LONGER NAVIGATES to /checkout/status/?a=att-9. The approved sentence asserts that no
     *    charge was made, and this status - the server's own initiation gate being off - is one of
     *    the few responses that can support that claim. The status screen cannot carry it: its
     *    viewFor() folds this status in with "we cannot find this attempt" and anything
     *    unrecognised, states where the money may in fact have moved, and PublicPageTopBand.test
     *    pins that /checkout/status/ never says "no charge" in ANY state. So the sentence has to be
     *    shown by the page that received the response, where it stays pinned to its evidence.
     *
     * 2. THE CART IS NO LONGER CLEARED. It was, alongside the genuinely-in-flight case. That left a
     *    shopper nothing to come back to when the gate is simply off - and because the notice
     *    renders inside the items list, clearing the cart would have replaced the explanation with
     *    "Your cart is empty." The recorded attempt is not payable, so the cart is still theirs.
     *
     * What has NOT changed is the invariant the old test existed to protect: no pay-now affordance
     * and no charge claim in the wrong direction.
     */
    expect( await screen.findByText(
      'We could not prepare this order. No charge was made - please try again shortly.',
    ) ).toBeTruthy();
    expect( navigatedTo ).toBe( '' );
    expect( cart.readCart() ).toHaveLength( 1 );
    expect( screen.queryByRole( 'button', { name: /pay/i } ) ).toBeNull();
    expect( container.textContent || '' ).not.toMatch( /pay now|pay \u20b9|make payment/i );
  } );

  it( 'opens Razorpay with server options and verifies the returned callback before navigation', async () => {
    signedIn( 'fixture-session' );

    let receivedOptions: any = null;
    const open = vi.fn();
    class FakeRazorpay {
      constructor ( options: any ) { receivedOptions = options; }
      open = open;
      on = vi.fn();
    }
    Object.defineProperty( window, 'Razorpay', {
      configurable: true,
      writable: true,
      value: FakeRazorpay,
    } );

    const fetchMock = stubFetch( {
      prepare: { body: {
        status: 'CHECKOUT_OPTIONS_READY',
        paymentAttemptId: 'att-web-1',
        options: {
          keyId: 'fixture-publishable-id',
          orderId: 'order-fixture-1',
          amountPaise: 121481,
          currency: 'INR',
          prefill: {
            name: 'Asha Sen',
            email: 'asha@example.com',
            contact: '+919330994400',
          },
        },
      } },
      verify: { body: { status: 'VERIFIED_PAID', paymentAttemptId: 'att-web-1' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();

    await waitFor( () => expect( open ).toHaveBeenCalledTimes( 1 ) );
    expect( receivedOptions.order_id ).toBe( 'order-fixture-1' );
    expect( receivedOptions.amount ).toBe( 121481 );
    expect( receivedOptions.currency ).toBe( 'INR' );
    expect( receivedOptions.prefill.email ).toBe( 'asha@example.com' );
    expect( receivedOptions ).not.toHaveProperty( 'key_secret' );

    const [ prepare ] = callsTo( fetchMock, PREPARE_URL, 'prepare' );
    expect( prepare.body.action ).toBe( 'prepare' );
    expect( prepare.body ).not.toHaveProperty( 'amountPaise' );
    expect( prepare.body ).not.toHaveProperty( 'currency' );
    expect( typeof prepare.body.requestKey ).toBe( 'string' );

    await receivedOptions.handler( {
      razorpay_payment_id: 'payment-fixture-1',
      razorpay_order_id: 'order-fixture-1',
      razorpay_signature: 'signature-fixture',
    } );

    await waitFor( () => expect( callsTo( fetchMock, VERIFY_URL ) ).toHaveLength( 1 ) );
    const [ verify ] = callsTo( fetchMock, VERIFY_URL );
    expect( verify.body ).toEqual( {
      action: 'verify',
      razorpay_payment_id: 'payment-fixture-1',
      razorpay_order_id: 'order-fixture-1',
      razorpay_signature: 'signature-fixture',
    } );
    expect( navigatedTo ).toBe( '/checkout/status/?a=att-web-1' );
    expect( cart.readCart() ).toHaveLength( 1 );
  } );

  it( 'routes PAYMENT_REQUEST_SENT to the hosted status screen', async () => {
    signedIn();
    stubFetch( { prepare: { body: { status: 'PAYMENT_REQUEST_SENT', paymentAttemptId: 'att-5' } } } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( navigatedTo ).toBe( '/checkout/status/?a=att-5' ) );
    expect( cart.readCart() ).toHaveLength( 1 );
  } );

  it.each( [ 'network', 'server' ] )( 'preserves the cart and makes no charge claim after a %s failure', async failure => {
    signedIn();
    stubFetch( {
      prepare: failure === 'network'
        ? new TypeError( 'response lost' )
        : { ok: false, status: 500, body: {} },
    } );
    cart.addItem( PRODUCT, 1 );
    const { container } = render( <Cart /> );
    await proceedPastProfile();
    expect( await screen.findByText( 'We could not confirm checkout. Check your orders before trying again.' ) ).toBeTruthy();
    expect( container.textContent ).not.toMatch( /No charge was made/i );
    expect( cart.readCart() ).toHaveLength( 1 );
    expect( navigatedTo ).toBe( '' );
  } );

  it( 'shows "no charge was made" on a 409 readiness block, staying on the page', async () => {
    signedIn();
    stubFetch( {
      prepare: { ok: false, status: 409, body: {
        status: 'payment_unavailable', readiness: 'CONFIGURATION_UNVERIFIED',
        message: 'Payments are temporarily unavailable. No charge was made.',
      } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();

    expect( await screen.findByText( /No charge was made/ ) ).toBeTruthy();
    // THE EXACT APPROVED SENTENCE, not merely something containing "No charge was made". A readiness
    // refusal is the other response that genuinely never reached the payment rail, so it earns the
    // same words as the disabled gate rather than a near-miss paraphrase. Note the server's own
    // `message` field is deliberately NOT rendered: the copy on this page is ours to control.
    expect( await screen.findByText(
      'We could not prepare this order. No charge was made - please try again shortly.',
    ) ).toBeTruthy();
    // It did not pretend to succeed or navigate away.
    expect( navigatedTo ).toBe( '' );
    expect( screen.queryByRole( 'button', { name: /pay/i } ) ).toBeNull();
  } );

  it( 'offers a retry with no charge on a 502 SEND_FAILED', async () => {
    signedIn();
    stubFetch( {
      prepare: { ok: false, status: 502, body: { status: 'SEND_FAILED', paymentAttemptId: 'att-2' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();
    expect( await screen.findByText( /No charge was made - please try again/ ) ).toBeTruthy();
  } );

  it( 'sends a 401 back to sign-in', async () => {
    signedIn();
    stubFetch( { prepare: { ok: false, status: 401, body: {} } } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( navigatedTo ).toContain( '/account/sign-in' ) );
  } );

  it( 'shows an empty state and no proceed button when the cart is empty', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    render( <Cart /> );
    expect( await screen.findByText( 'Your cart is empty.' ) ).toBeTruthy();
    expect( screen.queryByRole( 'button', { name: 'Proceed' } ) ).toBeNull();
  } );
} );

/**
 * THE READINESS QUESTION, ASKED FIRST.
 *
 * The page used to decide whether to show the checkout form from `profile`, a piece of state that
 * is null on every arrival - so a customer who had already saved their details was shown the form
 * again, every time. It now asks the server (`action:'profile'`) on mount and again on the click,
 * and renders the form only when the answer says something is missing.
 *
 * The cases here are about the ANSWER, including the answers that never arrive. The one that
 * matters most is the failure: a readiness read that rejects or 500s must cost one wasted
 * `prepare` call and nothing else. The server's own 409 arms are the authority on readiness, and
 * handing a transient DynamoDB blip the power to stop a payable customer is the exact failure this
 * work removes.
 */
describe( 'the cart page asks the readiness question before rendering anything', () => {
  it( 'renders NO checkout form for a ready profile and goes straight to prepare', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-ready' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );

    // The identity card is the page's own signal that the answer landed and said "payable now".
    expect( await screen.findByText( 'Ready to pay' ) ).toBeTruthy();
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
    // The Deliver line is the server's composed string, verbatim.
    expect( screen.getByText( ADDRESS_FIXTURE.fullAddress ) ).toBeTruthy();

    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
    // Still no form: a returning customer never meets one.
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
  } );

  it.each( [
    [ 'rejects', new TypeError( 'readiness lost' ) as StubReply ],
    [ 'answers 500', { ok: false, status: 500, body: {} } as StubReply ],
    [ 'answers an unrecognised status', { body: { status: 'SOMETHING_NEW' } } as StubReply ],
  ] )( 'still issues the prepare POST and renders no editor when the status call %s', async ( _label, reply ) => {
    // THE HIGH-1 CASE. `deriveStatus` answers 'unknown' for all three, and 'unknown' falls THROUGH
    // to prepare. Blocking here would mean one failed read costs a sale.
    signedIn();
    const fetchMock = stubFetch( {
      profile: reply,
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-blip' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Proceed' } ) );

    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
    // Nor did it invent an error for the customer out of a failure that was ours.
    expect( screen.queryByText( /Add your delivery address to continue\./ ) ).toBeNull();
  } );

  it( 'renders the address FORM, not just a notice, for PROFILE_READY with no usable address', async () => {
    // THE TOKEN HOIST. The editor is gated on `showProfile && checkoutAccessToken`, and the token
    // starts empty - so before the hoist this arm asked for an address above no form at all.
    signedIn();
    stubFetch( {
      profile: { body: { ...PROFILE_READY, addressComplete: false, address: null } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );

    const editor = await screen.findByTestId( 'checkout-profile' );
    expect( editor.getAttribute( 'data-mode' ) ).toBe( 'address' );
    expect( await screen.findByText( 'Add your delivery address to continue.' ) ).toBeTruthy();
    // 'required' is not 'ready', so the identity card with an empty Deliver row never appears.
    expect( screen.queryByText( 'Ready to pay' ) ).toBeNull();
  } );

  it( 'leaves an address form mounted when a save comes back without a usable address', async () => {
    // THE onReady FIX. Closing the editor and then asking for an address is a dead end, and it is
    // reachable: a stored address that stopped mapping, or a backend that wrote one it cannot
    // re-validate. The assertion is on the FORM, not on the copy.
    signedIn();
    stubFetch();
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Proceed' } ) );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Save without an address' } ) );

    const editor = await screen.findByTestId( 'checkout-profile' );
    expect( editor.getAttribute( 'data-mode' ) ).toBe( 'address' );
  } );

  it( 'does not re-open the editor on a second click after a completed save', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-twice' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );

    fireEvent.click( await screen.findByRole( 'button', { name: /Try again/ } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
  } );

  it( 'retries prepare EXACTLY once when a readiness refusal lands right after a save', async () => {
    /*
     * `_checkout_profile` and `_load_owned_address` both read `phone-index`, a GLOBAL secondary
     * index, which cannot be read strongly consistent - so a prepare issued seconds after a save
     * can legitimately see the pre-save row. Without this, the customer most likely to be told
     * "confirm your delivery address" is the first-timer who just typed one in.
     *
     * Fake timers, and therefore no `waitFor`/`findBy`: those poll on the very timer this test
     * controls. `flush` settles the promise chains instead.
     */
    vi.useFakeTimers();
    signedIn();
    const fetchMock = stubFetch( {
      prepare: [
        { ok: false, status: 409, body: { error: 'DELIVERY_DETAILS_REQUIRED' } },
        { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-retry' } },
      ],
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: 'Proceed' } ) );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: 'Complete checkout details' } ) );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: /Pay securely/ } ) );
    await flush();

    // One refusal so far, and nothing has been asked of the customer.
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();

    await act( async () => { vi.advanceTimersByTime( RETRY_WAIT_MS ); } );
    await flush();

    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 );
    // The second answer was the good one, so the editor never opened.
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
  } );

  it( 'opens the address editor when the SECOND prepare refuses too, and stops retrying', async () => {
    vi.useFakeTimers();
    signedIn();
    const fetchMock = stubFetch( {
      prepare: { ok: false, status: 409, body: { error: 'DELIVERY_DETAILS_REQUIRED' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: 'Proceed' } ) );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: 'Complete checkout details' } ) );
    await flush();
    fireEvent.click( screen.getByRole( 'button', { name: /Pay securely/ } ) );
    await flush();

    await act( async () => { vi.advanceTimersByTime( RETRY_WAIT_MS ); } );
    await flush();

    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 );
    const editor = screen.getByTestId( 'checkout-profile' );
    expect( editor.getAttribute( 'data-mode' ) ).toBe( 'address' );

    // The ref was cleared BEFORE the retry, so a third prepare cannot be waiting on a timer.
    await act( async () => { vi.advanceTimersByTime( RETRY_WAIT_MS * 3 ); } );
    await flush();
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 );
  } );

  it( 'opens address mode immediately for DELIVERY_DETAILS_REQUIRED with no preceding save', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: { error: 'DELIVERY_DETAILS_REQUIRED' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    expect( await screen.findByText( 'Ready to pay' ) ).toBeTruthy();
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );

    const editor = await screen.findByTestId( 'checkout-profile' );
    expect( editor.getAttribute( 'data-mode' ) ).toBe( 'address' );
    expect( await screen.findByText( 'Confirm your delivery address to continue.' ) ).toBeTruthy();
    // Nothing was saved in this page's lifetime, so there is no stale read to wait out: ONE call.
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
  } );

  it( 'blocks payment and keeps the cart on DELIVERY_METHOD_UNAVAILABLE', async () => {
    // NOT THE CUSTOMER'S MISTAKE: the address is known-good and the store has no delivery method
    // for it. So no editor opens, the cart survives, and the copy says nothing was charged.
    signedIn();
    stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: { error: 'DELIVERY_METHOD_UNAVAILABLE' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    expect( await screen.findByText( 'Ready to pay' ) ).toBeTruthy();
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );

    expect( await screen.findByText(
      'We could not get a delivery option for this address. Nothing was charged.',
    ) ).toBeTruthy();
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
    expect( cart.readCart() ).toHaveLength( 1 );
    expect( navigatedTo ).toBe( '' );
    expect( await screen.findByRole( 'button', { name: /Try again/ } ) ).toBeTruthy();
  } );

  it( 'opens the creation flow, with the token set, when the server refuses with PROFILE_REQUIRED', async () => {
    signedIn();
    stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: {
        error: 'PROFILE_REQUIRED', message: 'Checkout profile is required.',
      } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    expect( await screen.findByText( 'Ready to pay' ) ).toBeTruthy();
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely/ } ) );

    const editor = await screen.findByTestId( 'checkout-profile' );
    expect( editor.getAttribute( 'data-mode' ) ).toBe( 'create' );
    expect( await screen.findByText( 'Verify and save your checkout details again.' ) ).toBeTruthy();
    // The server is later and better informed, so it also withdraws the identity card.
    expect( screen.queryByText( 'Ready to pay' ) ).toBeNull();
  } );

  it( 'wires the identity card affordances to the matching editor mode', async () => {
    signedIn();
    stubFetch( { profile: { body: PROFILE_READY } } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Edit address' } ) );
    expect( ( await screen.findByTestId( 'checkout-profile' ) ).getAttribute( 'data-mode' ) ).toBe( 'address' );
    // The card stays, with its buttons disabled, so a second affordance cannot swap the mode out
    // from under a half-typed edit.
    expect( screen.getByText( 'Ready to pay' ) ).toBeTruthy();
    expect( ( screen.getByRole( 'button', { name: 'Edit name' } ) as HTMLButtonElement ).disabled ).toBe( true );
  } );
} );

/**
 * WHERE THE APPROVED SENTENCE MAY AND MAY NOT APPEAR.
 *
 * "We could not prepare this order. No charge was made - please try again shortly." asserts a
 * financial fact. On an initiation refusal that fact is backed by the server's own response. On a
 * pending, unknown or captured-but-unfinalised attempt it is not knowable from the browser at all,
 * and offering a retry there risks a second charge for money that has already moved. So the sentence
 * is tested from both directions: present where the evidence exists, absent everywhere else.
 */
describe( 'the initiation-failure sentence is pinned to its evidence', () => {
  const SENTENCE = 'We could not prepare this order. No charge was made - please try again shortly.';

  it( 'is the exact wording on every initiation-refusal branch', async () => {
    // Four distinct refusals, all of which mean the request did not reach the payment rail. Each
    // must produce the sentence CHARACTER FOR CHARACTER - a paraphrase is a different promise, and
    // the hyphen in "made - please" is part of the approved string.
    const refusals: Array<{ ok: boolean; status: number; body: unknown }> = [
      { ok: true, status: 200, body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-d' } },
      { ok: false, status: 409, body: { status: 'payment_unavailable' } },
      { ok: false, status: 422, body: { status: 'UNSUPPORTED_CURRENCY' } },
      { ok: false, status: 503, body: { status: 'CATALOGUE_UNAVAILABLE' } },
    ];

    for ( const refusal of refusals )
    {
      window.localStorage.clear();
      navigatedTo = '';
      signedIn();
      stubFetch( { prepare: refusal } );
      cart.addItem( PRODUCT, 1 );

      const { unmount } = render( <Cart /> );
      await proceedPastProfile();
      expect( await screen.findByText( SENTENCE ), JSON.stringify( refusal.body ) ).toBeTruthy();
      // Nothing was handed off, so the claim stays attached to the response that justified it.
      expect( navigatedTo ).toBe( '' );
      unmount();
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    }
  } );

  it( 'is absent from the in-flight handoff, which claims nothing either way', async () => {
    signedIn();
    stubFetch( { prepare: { body: { status: 'PAYMENT_REQUEST_SENT', paymentAttemptId: 'att-5' } } } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();

    await waitFor( () => expect( navigatedTo ).toBe( '/checkout/status/?a=att-5' ) );
    expect( cart.readCart() ).toHaveLength( 1 );
    // ONCE A REQUEST HAS LEFT, the browser cannot rule out a capture, so neither the sentence nor
    // any part of its claim may be rendered on the way out.
    expect( container.textContent || '' ).not.toContain( SENTENCE );
    expect( container.textContent || '' ).not.toMatch( /no charge/i );
  } );

  it( 'is absent from the status screen in pending, paid-finalizing and unknown states', () => {
    /*
     * THE DIRECTION THAT MATTERS MOST. These are the states where money may already have moved:
     * PAYMENT_PENDING is in flight, PAYMENT_PAID without an order number is captured but not
     * finalised, and an empty or unrecognised status means we simply do not know. Telling any of
     * those three "no charge was made - please try again" invites a double charge.
     */
    for ( const [ status, orderNumber, expected ] of [
      [ 'PAYMENT_PENDING', null, 'confirming' ],
      [ 'PAYMENT_REQUEST_SENT', null, 'confirming' ],
      [ 'PAYMENT_PAID', null, 'finalizing' ],
      [ '', null, 'unavailable' ],
      [ 'SOMETHING_NEW_FROM_THE_BACKEND', null, 'unavailable' ],
      [ 'PAYMENT_INITIATION_DISABLED', null, 'unavailable' ],
    ] as [ string, string | null, string ][] )
    {
      // The mapping is asserted alongside the copy so a future view rename cannot quietly route a
      // pending attempt into a screen that does make the claim.
      expect( viewFor( status, orderNumber ) ).toBe( expected );
      const { container, unmount } = render( <CheckoutStatus /> );
      expect( container.textContent || '' ).not.toContain( SENTENCE );
      unmount();
    }

    // And the sentence is not in the file at all, in any state this test did not think to render.
    // PAYMENT_INITIATION_DISABLED lands on 'unavailable' here TOO, shared with "we cannot find
    // this attempt" - which is precisely why the sentence lives on /cart/ and not on this screen.
    const source = fs.readFileSync(
      path.join( process.cwd(), 'src/pages/checkout/status.tsx' ), 'utf8',
    ).replace( /\/\*[\s\S]*?\*\//g, '' ).replace( /^\s*\/\/.*$/gm, '' );
    expect( source ).not.toContain( SENTENCE );
    expect( source.toLowerCase() ).not.toContain( 'no charge' );
  } );
} );


/*
 * ── the terminal latch, and the full stubbed rail ─────────────────────────────
 *
 * The CTA sits underneath the Razorpay modal with `disabled={busy}` and `busy` goes false the
 * moment `razorpay.open()` returns, so before this latch the Proceed pill was live behind an open
 * payment modal and live again after a verify response that said "we are still verifying".
 *
 * Every assertion below is POSITIVE -- a call count, a URL, `pill === null || pill.disabled`.
 * A `queryBy*` returning `null` on its own asserts nothing, because a renamed element returns
 * null too. The CTA's accessible name is one of `Checkout Proceed`, `Checkout Pay securely` or
 * `Checkout Try again`, so it is found by ROLE AND POSITION inside the `cart-pill` region rather
 * than by a guessed name.
 *
 * The latch is DEFENCE IN DEPTH, not the guarantee: it dies with the page. The server-side
 * one-live-payment-per-basket guard is the guarantee, and it is tested in
 * `tests/test_graft_money_correctness.py`.
 */
describe( 'the payment rail latches once it has returned a result', () => {
  function pillButton ( container: HTMLElement ): HTMLButtonElement | null {
    const region = container.querySelector( '.cart-pill' );
    return region ? region.querySelector( 'button' ) : null;
  }

  function fakeRazorpay () {
    const state: { options: any; opens: number; events: string[] } = {
      options: null, opens: 0, events: [],
    };
    class FakeRazorpay {
      constructor ( options: any ) { state.options = options; }
      open = () => {
        // NEVER any network I/O: the SDK is stubbed precisely so no real charge is possible.
        state.opens += 1;
      };
      on = ( event: string ) => { state.events.push( event ); };
    }
    Object.defineProperty( window, 'Razorpay', {
      configurable: true, writable: true, value: FakeRazorpay,
    } );
    return state;
  }

  const READY_OPTIONS = {
    status: 'CHECKOUT_OPTIONS_READY',
    paymentAttemptId: 'att-latch-1',
    options: {
      keyId: 'fixture-publishable-id',
      orderId: 'order-latch-1',
      amountPaise: 2625123,
      currency: 'INR',
      prefill: { name: 'Asha Sen', email: 'asha@example.com', contact: '+919330994400' },
      paymentAttemptId: 'att-latch-1',
    },
  };

  it( 'the full stubbed rail: cart -> profile -> prepare -> modal -> verify -> one order', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    const fetchMock = stubFetch( {
      prepare: { body: READY_OPTIONS },
      verify: { body: {
        status: 'VERIFIED_PAID', paymentAttemptId: 'att-latch-1',
        orderNumber: 'WD-ORD-A1B2C3D4',
      } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();

    // The modal payload, asserted as an allow-list rather than a spot check.
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );
    expect( razorpay.options.order_id ).toBe( 'order-latch-1' );
    expect( Number.isInteger( razorpay.options.amount ) ).toBe( true );
    expect( razorpay.options.amount ).toBe( 2625123 );
    expect( razorpay.options.currency ).toBe( 'INR' );
    expect( razorpay.options.key ).toBe( 'fixture-publishable-id' );
    expect( String( razorpay.options.order_id ).length ).toBeGreaterThan( 0 );
    // No key whose name mentions a secret, anywhere in what the browser was handed.
    const handed = Object.keys( razorpay.options );
    expect( handed.filter( ( key ) => /secret/i.test( key ) ) ).toEqual( [] );
    expect( JSON.stringify( razorpay.options ) ).not.toMatch( /secret/i );

    // Exactly one verify POST, to the verify route.
    await razorpay.options.handler( {
      razorpay_payment_id: 'pay-latch-1',
      razorpay_order_id: 'order-latch-1',
      razorpay_signature: 'sig-latch-1',
    } );
    await waitFor( () => expect( callsTo( fetchMock, VERIFY_URL ) ).toHaveLength( 1 ) );
    const verifyBodies = callsTo( fetchMock, VERIFY_URL, 'verify' );
    expect( verifyBodies ).toHaveLength( 1 );

    // ...and one navigation to the status page for that one attempt.
    expect( navigatedTo ).toBe( '/checkout/status/?a=att-latch-1' );
  } );

  it( 'latches on a VERIFIED_PAID return, so the CTA cannot re-enter the rail', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    const fetchMock = stubFetch( {
      prepare: { body: READY_OPTIONS },
      verify: { body: { status: 'VERIFIED_PAID', paymentAttemptId: 'att-latch-1' } },
    } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );

    await razorpay.options.handler( {
      razorpay_payment_id: 'pay-latch-1',
      razorpay_order_id: 'order-latch-1',
      razorpay_signature: 'sig-latch-1',
    } );
    await waitFor( () => expect( callsTo( fetchMock, VERIFY_URL ) ).toHaveLength( 1 ) );

    // The pill is either gone (replaced by the orders link) or disabled. Asserted as the
    // DISJUNCTION, so it passes under both mechanisms and cannot be satisfied by a live button.
    const pill = pillButton( container );
    expect( pill === null || pill.disabled ).toBe( true );
    // And the way off the page is a LINK, whose words cannot read as "pay again".
    const away = container.querySelector( '.cart-pill a' ) as HTMLAnchorElement | null;
    expect( away ).toBeTruthy();
    expect( String( away?.textContent || '' ) ).toBe( 'Check your orders' );
    expect( String( away?.textContent || '' ) ).not.toMatch( /pay|again|retry/i );
  } );

  it( 'latches on a LOST verify response, which is the case money may have moved in', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    // The verify request THROWS. Nothing came back to read, so a live CTA here is the worst
    // possible affordance: the payment may well have succeeded.
    stubFetch( {
      prepare: { body: READY_OPTIONS },
      verify: new Error( 'network' ),
    } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );

    await razorpay.options.handler( {
      razorpay_payment_id: 'pay-latch-1',
      razorpay_order_id: 'order-latch-1',
      razorpay_signature: 'sig-latch-1',
    } );

    // `waitFor`, because the latch is set as the handler's FIRST statement -- before the fetch
    // that then throws -- so the state update has to be flushed before the render is read. That
    // ordering is the point of the row: the latch holds even though nothing came back.
    await waitFor( () => {
      const pill = pillButton( container );
      expect( pill === null || pill.disabled ).toBe( true );
    } );
    expect( navigatedTo ).toBe( '' );
    // The copy makes no claim about a charge in either direction.
    expect( container.textContent || '' ).not.toMatch( /no charge/i );
  } );

  it( 'latches on a non-VERIFIED_PAID verdict too, because the money is still unknown', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    const fetchMock = stubFetch( {
      prepare: { body: READY_OPTIONS },
      verify: { body: { status: 'NOT_CAPTURED', paymentAttemptId: 'att-latch-1' } },
    } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );
    await razorpay.options.handler( {
      razorpay_payment_id: 'pay-latch-1',
      razorpay_order_id: 'order-latch-1',
      razorpay_signature: 'sig-latch-1',
    } );
    await waitFor( () => expect( callsTo( fetchMock, VERIFY_URL ) ).toHaveLength( 1 ) );

    const pill = pillButton( container );
    expect( pill === null || pill.disabled ).toBe( true );
    expect( navigatedTo ).toBe( '' );
  } );

  it( 'does NOT latch on a dismissed modal, because nothing came back to verify', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    stubFetch( { prepare: { body: READY_OPTIONS } } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );

    // A dismissal means the provider took nothing, and the next click re-presents the SAME stored
    // request key onto the SAME gateway order. Latching it would strand a shopper who closed the
    // modal by accident.
    razorpay.options.modal.ondismiss();
    const pill = pillButton( container );
    expect( pill ).toBeTruthy();
    expect( pill?.disabled ).toBe( false );
  } );

  it( 'registers payment.failed and does not latch on it either', async () => {
    signedIn( 'fixture-session' );
    const razorpay = fakeRazorpay();
    stubFetch( { prepare: { body: READY_OPTIONS } } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( razorpay.opens ).toBe( 1 ) );
    // The provider is telling us no money moved, so the rail is re-enterable.
    expect( razorpay.events ).toContain( 'payment.failed' );
    const pill = pillButton( container );
    expect( pill ).toBeTruthy();
    expect( pill?.disabled ).toBe( false );
  } );

  it( 'an ambiguous refusal WITH an attempt id goes to the status page', async () => {
    signedIn( 'fixture-session' );
    stubFetch( {
      prepare: { ok: false, status: 409, body: {
        status: 'CHECKOUT_AMBIGUOUS', reason: 'CART_ALREADY_PAID',
        paymentAttemptId: 'att-blocked-1',
      } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    await proceedPastProfile();
    await waitFor( () => expect( navigatedTo ).toBe( '/checkout/status/?a=att-blocked-1' ) );
  } );

  it( 'an ambiguous refusal with NO attempt id claims nothing about a charge', async () => {
    signedIn( 'fixture-session' );
    stubFetch( {
      prepare: { ok: false, status: 409, body: {
        status: 'CHECKOUT_AMBIGUOUS', reason: 'CART_PAYMENT_IN_FLIGHT',
      } },
    } );
    cart.addItem( PRODUCT, 1 );

    const { container } = render( <Cart /> );
    await proceedPastProfile();

    // A step-4b loser deliberately carries no attempt id, because the holder's attempt may not
    // exist yet and an unresolvable id would point the status page at nothing. So this falls to
    // the charge-silent catch-all: no navigation, no claim either way, CTA still live for a retry
    // that will succeed once the winner's row is recorded.
    await waitFor( () => expect(
      ( container.textContent || '' ).length ).toBeGreaterThan( 0 ) );
    expect( navigatedTo ).toBe( '' );
    expect( container.textContent || '' ).not.toMatch( /no charge/i );
    const pill = pillButton( container );
    expect( pill ).toBeTruthy();
    expect( pill?.disabled ).toBe( false );
  } );

  it( 'has no INTENT_CHANGED auto-retry to leave unlatched', () => {
    // The dangerous shape a sibling branch had: a refusal self-healing by minting a fresh request
    // key and opening a SECOND modal with no further click. It does not exist here, and this row
    // is what keeps it from being introduced unlatched later.
    const source = fs.readFileSync(
      path.resolve( __dirname, '../pages/cart.tsx' ), 'utf8' );
    expect( source ).not.toMatch( /retriedIntent/ );
    expect( source.match( /INTENT_CHANGED/g ) || [] ).toHaveLength( 0 );
  } );

  it( 'branches the readiness decision on a local, never on the profileStatus state', () => {
    /*
     * A SOURCE PIN, because this is the one property no render can observe.
     *
     * `setProfileStatus` cannot change the `useState` value captured in `proceed`'s closure, so
     * branching on `profileStatus` after setting it means the 'ready' arm is never taken on a
     * first click. The fix is a local `let status` assigned from `deriveStatus`'s RETURN value,
     * and the status-failure cases above prove the behaviour - this proves the mechanism, so a
     * future edit cannot quietly reintroduce the stale read while the tests still pass.
     */
    const source = fs.readFileSync( path.resolve( __dirname, '../pages/cart.tsx' ), 'utf8' );
    expect( source ).toMatch( /let status = profileStatus;/ );
    expect( source ).toMatch( /if \( status === 'required' \)/ );
    // The branch must never test the state directly.
    expect( source ).not.toMatch( /if \( profileStatus === 'required' \)/ );
    expect( source.match( /postPrepare\( session, lineItems \)/g ) || [] ).toHaveLength( 2 );
  } );
} );
