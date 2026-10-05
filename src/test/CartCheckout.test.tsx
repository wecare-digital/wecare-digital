import React from 'react';
import {
  afterEach, beforeEach, describe, expect, it, vi,
} from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import fs from 'fs';
import path from 'path';

import * as cart from '../lib/cart';
import { CONTRIBUTION_CHOICES } from '../config/contribution';
import { colors } from '../lib/design-tokens';
import { MEDIA_BASE } from '../config/share';
import type { ShopProduct } from '../content/shop';
import type { StoredAddress } from '../components/AddressFields';
import * as customerAuth from '../lib/customerAuth';

/**
 * The three contribution choices, by position, so a case can seed a basket without re-typing a
 * GUID. `MID` stands wherever the previous revision wrote `setContribution( 400 )`: the amount was
 * arbitrary there and still is, because those cases are about the checkout rail rather than the
 * figure. `LOW` stands where a SECOND, DIFFERENT amount is the point.
 */
const [ LOW, MID ] = CONTRIBUTION_CHOICES;

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

    // The CURRENT Kiosk product and its single variant, re-measured against the migrated site
    // c993128b on 2026-10-05. The previous site's ids were 00d4c72b-f694-441a-a192-e16f4b192440
    // and variant 2d072962-37c0-4821-9c02-2cc223448711; the migration re-minted both. The row in
    // storage above has NO product id at all, which is the point - it migrates by slug, so a cart
    // saved before the move resolves to whatever the catalogue holds now.
    const [ item ] = cart.readCart();
    expect( item.productId ).toBe( 'a12e9e74-e109-4136-a12e-ab49ea6f98c3' );
    expect( item.variantId ).toBe( '4d3e2b31-7888-4250-8f5a-0587344431db' );
    expect( item.ref ).toBe(
      'a12e9e74-e109-4136-a12e-ab49ea6f98c3:4d3e2b31-7888-4250-8f5a-0587344431db',
    );
    expect( cart.toLineItems() ).toEqual( [ {
      catalogReference: {
        appId: '215238eb-22a5-4c36-9e7b-e7c08025e04e',
        catalogItemId: 'a12e9e74-e109-4136-a12e-ab49ea6f98c3',
        options: { variantId: '4d3e2b31-7888-4250-8f5a-0587344431db' },
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

    // The stored `ref` is the RETIRED site's Merchandise id, which is exactly the legacy shape
    // this case exists for: the row is repaired to the current product (eca1540e..., re-minted by
    // the 2026-10-05 site migration) by slug, and no variant is guessed because ten of them
    // remain and only the customer can say which.
    const [ item ] = cart.readCart();
    expect( item.productId ).toBe( 'eca1540e-0a0e-478d-9aa7-e366be277617' );
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
      `eca1540e-0a0e-478d-9aa7-e366be277617:${target.id}`,
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

  it( 'sends the Wix Stores appId the SERVER validates against, byte for byte', () => {
    /*
     * `wix_ecom.resolved_catalog_lines` refuses any reference whose `appId` is not
     * `cart_v2.STORES_APP_ID`, as "invalid catalogue reference" -> `WixEcomError` -> 502
     * CATALOGUE_UNAVAILABLE. The two constants are separate declarations in two languages, so
     * drift between them is an outage with a misleading error code.
     *
     * Pinned here because during a live 502 investigation on 2026-10-04 this was a leading
     * suspect, and answering it needed a measurement rather than a reading. It matches.
     */
    cart.addItem( PRODUCT, 1 );
    const [ line ] = cart.toLineItems();
    // The value in amplify/functions/shared/lambda_utils/ecommerce/cart_v2.py:STORES_APP_ID.
    expect( line.catalogReference.appId ).toBe( '215238eb-22a5-4c36-9e7b-e7c08025e04e' );
    // And the id is the PRODUCT id, never the slug: a slug 404s at the V3 product GET.
    expect( line.catalogReference.catalogItemId ).toBe( PRODUCT.id );
    expect( line.catalogReference.catalogItemId ).not.toBe( PRODUCT.slug );
  } );

  it( 'omits `options` entirely for a line with no variant, which is the V3 shape', () => {
    // A no-option Catalog V3 product's reference carries no `options` key at all. An
    // `options: { variantId: undefined }` would serialise as `"options":{}` and is not the same
    // thing. `PRODUCT` has no `variants`, so this is the no-variant branch of `toLineItems`.
    cart.addItem( PRODUCT, 1 );
    const [ line ] = cart.toLineItems();
    expect( 'options' in line.catalogReference ).toBe( false );
    expect( JSON.stringify( line ) ).not.toContain( 'options' );
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

    // A variant that exists in the CURRENT catalogue (Merchandise "Men's / XL" on site
    // c993128b). The previous spelling, 00ebbae6-7025-4724-835e-37f4bffc2476, belonged to the
    // retired site and the repair would correctly refuse it now.
    const select = await screen.findByRole( 'combobox', { name: /Choose option for Merchandise/ } );
    fireEvent.change( select, {
      target: { value: '3788a657-9af2-4ecf-8c9b-f218669d753c' },
    } );
    expect( await screen.findByText(
      'Product option updated. Continue to secure payment.',
    ) ).toBeTruthy();
    expect( cart.readCart()[ 0 ].variantId ).toBe(
      '3788a657-9af2-4ecf-8c9b-f218669d753c',
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
    expect( receivedOptions.prefill.name ).toBe( 'Asha Sen' );
    expect( receivedOptions.prefill.email ).toBe( 'asha@example.com' );
    expect( receivedOptions.prefill.contact ).toBe( '+919330994400' );
    expect( receivedOptions ).not.toHaveProperty( 'key_secret' );

    /*
     * THE BRAND HALF OF THE MODAL. A real Razorpay modal cannot be opened here, so what is
     * assertable is the options object the SDK is handed - which is the whole of what this repo
     * controls about how that modal looks.
     *
     * theme.color IS COMPARED TO THE TOKEN, not to a hex literal. Restating '#1a3a2a' here would
     * let the token move while the test went on passing against the old value, which is the one
     * failure a colour test exists to catch. The literal below is asserted ONCE, against the
     * token itself, so the pay modal and the site cannot drift apart silently.
     *
     * The logo must be the OPAQUE square: Razorpay composites it onto its own surface, so this is
     * the external-renderer case BrandAssets.test.ts bans the 68%-transparent mark from.
     */
    expect( receivedOptions.name ).toBe( 'WECARE.DIGITAL' );
    expect( receivedOptions.theme.color ).toBe( colors.primary );
    expect( colors.primary ).toBe( '#1a3a2a' );
    expect( receivedOptions.image ).toBe( `${MEDIA_BASE}/wecare-digital.png` );
    expect( receivedOptions.image ).not.toContain( 'wecaredigital.png' );
    // One product, quantity one - so the descriptor says so and still names no amount.
    expect( receivedOptions.description ).toBe( 'Order payment - 1 item' );
    expect( receivedOptions.description ).not.toMatch( /\u20b9|\d{3,}/ );

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

  it( 'calls a contribution a contribution in the modal, not an order', async () => {
    /*
     * THE ONE BRANCH IN THE DESCRIPTOR, and it is a correctness assertion rather than a cosmetic
     * one. src/content/legal/terms.ts says a contribution "does not create an order, a product or
     * a shipment"; a modal headed "Order payment" over a contribution would have the payment
     * surface contradicting the agreement this same page links to.
     *
     * Nothing else about the rail changes - same name, same logo, same theme token, and still no
     * amount in the description, which is asserted here too because a contribution is the case
     * where naming a figure would be most tempting.
     */
    signedIn( 'fixture-session' );

    let receivedOptions: any = null;
    const open = vi.fn();
    class FakeRazorpay {
      constructor ( options: any ) { receivedOptions = options; }
      open = open;
      on = vi.fn();
    }
    Object.defineProperty( window, 'Razorpay', {
      configurable: true, writable: true, value: FakeRazorpay,
    } );

    stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { body: {
        status: 'CHECKOUT_OPTIONS_READY',
        paymentAttemptId: 'att-contrib-1',
        options: {
          keyId: 'fixture-publishable-id',
          orderId: 'order-contrib-1',
          amountPaise: 25000,
          currency: 'INR',
          prefill: { name: 'Asha Sen', email: 'asha@example.com', contact: '+919330994400' },
        },
      } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Pay securely|Proceed/ } ) );

    await waitFor( () => expect( open ).toHaveBeenCalledTimes( 1 ) );
    expect( receivedOptions.description ).toBe( 'Contribution to WECARE.DIGITAL' );
    expect( receivedOptions.description ).not.toMatch( /order/i );
    expect( receivedOptions.description ).not.toMatch( /\u20b9|\d/ );
    expect( receivedOptions.name ).toBe( 'WECARE.DIGITAL' );
    expect( receivedOptions.theme.color ).toBe( colors.primary );
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

  it( 'has exactly ONE INTENT_CHANGED rotation, bounded by there being no loop around it', () => {
    /*
     * REPLACES an assertion that there was NO rotation at all, and the replacement is narrower
     * rather than weaker.
     *
     * The original concern is still the right one: a refusal self-healing by minting a fresh
     * request key and opening a SECOND modal with no further click. What changed is that the
     * absence of a rotation turned out to be a dead end of its own. `intent_fingerprint` keeps
     * `cart_revision` AND `snapshot_hash`, and `checkout_pricing.basket_hash`'s docstring records
     * as measured that the website prepare path WRITES TO THE WIX CART on every call - so a second
     * prepare of an UNEDITED basket can present a different `snapshot_hash`, answer
     * 409 CHECKOUT_REJECTED, and latch `paymentBlocked` for the life of the tab for a refusal no
     * human caused.
     *
     * So the guard becomes the BOUND, asserted here as a source pin because no render can observe
     * it: the rotation is gated on the ONE reason a fresh key can clear, and it removes BOTH slots
     * - which is what makes a second `INTENT_CHANGED` impossible rather than merely unlikely,
     * because no reservation then holds the new key. It cannot open a second modal: the
     * one-live-payment guard is keyed on the CART and runs before the reservation, so the re-post
     * either prepares cleanly or is refused as CHECKOUT_AMBIGUOUS, which this page answers by
     * navigating.
     *
     * WHAT THIS NO LONGER CLAIMS. An earlier version of this pin asserted a `let rotated = false`
     * local and called it "the bound". That local was dead: with no loop around the block, `!rotated`
     * was unconditionally true at its single evaluation and the assignment was never read, so the
     * pin read stronger than it was. The real bound is STRUCTURAL - straight-line code reached once
     * per `proceed` - and what this pin can honestly hold is the number of `postPrepare` CALL SITES
     * reachable from one click. Three: the first post, the post-save retry, this rotation. A fourth
     * site, or a loop reusing one of them, breaks this. The observable bound ("a second
     * INTENT_CHANGED latches and issues no third post") is proved behaviourally below.
     */
    const source = fs.readFileSync(
      path.resolve( __dirname, '../pages/cart.tsx' ), 'utf8' );
    // No retry flag of any shape - unbounded, or vestigial and pretending to bound something.
    // Matched on DECLARATION and ASSIGNMENT rather than on the bare word, because the comment that
    // records why the flag went necessarily names it.
    expect( source ).not.toMatch( /retriedIntent/ );
    expect( source ).not.toMatch( /let rotated/ );
    expect( source ).not.toMatch( /rotated = true/ );
    expect( source ).not.toMatch( /rotatedRef/ );
    // Scoped to the one recoverable reason, and to nothing else.
    expect( source ).toMatch(
      /outcome\.kind === 'CHECKOUT_REJECTED' && outcome\.reason === 'INTENT_CHANGED'\s*\)/ );
    // Both slots removed, which is what makes the second post unable to refuse the same way.
    expect( source ).toMatch( /removeItem\( CHECKOUT_REQUEST_KEY \)/ );
    expect( source ).toMatch( /removeItem\( CHECKOUT_REQUEST_BASKET \)/ );
    // THE BOUND, as a count of call sites: first post, post-save retry, rotation. No loop.
    expect( source.match( /await postPrepare\(/g ) || [] ).toHaveLength( 3 );
    expect( source ).not.toMatch( /(for|while)\s*\([^)]*\)\s*\{[^}]*postPrepare/ );
  } );

  it( 'consumes the resetCart one-shot on ENTRY to the run, above every early return', () => {
    /*
     * A SOURCE PIN for the ordering, paired with the behavioural case in the CART_RESET_REQUIRED
     * describe that drives an actual early return.
     *
     * The read used to sit immediately above the first `postPrepare`, inside the `try`, with six
     * `return`s above it. Arm the flag with "Start a new cart", hit any of them, and the flag
     * survived into the NEXT click - which then posted `resetCart: true` and abandoned a saved cart
     * the customer never asked to discard. `setCartResetOffered(false)` was already at the top, so
     * the control disappeared while the flag it armed stayed armed.
     *
     * Pinned as source as well as behaviour because the defect is a PLACEMENT: a future edit could
     * keep every test in this file green while moving the read back down past one new guard.
     *
     * ANCHORED ON `runCheckout`, NOT ON `proceed`. The in-flight latch split the two: `proceed` is
     * now a latch wrapper and `runCheckout` is the body this ordering is about. Anchoring on
     * `proceed` would measure the wrapper and pass vacuously.
     */
    const source = fs.readFileSync(
      path.resolve( __dirname, '../pages/cart.tsx' ), 'utf8' );
    const runAt = source.indexOf( 'const runCheckout = useCallback(' );
    expect( runAt ).toBeGreaterThan( 0 );
    const clearAt = source.indexOf( 'resetCartRef.current = false;', runAt );
    const firstPostAt = source.indexOf( 'await postPrepare(', runAt );
    expect( clearAt ).toBeGreaterThan( 0 );
    expect( clearAt ).toBeLessThan( firstPostAt );

    // EVERY early return in the run sits below the clear, with exactly ONE exception: the
    // `railTerminalRef` guard, which is deliberately the very first statement and cannot leak -
    // nothing clears that ref, so once it is set every later run returns there and no
    // `postPrepare` can carry the flag again. Scan is bounded to the pre-post region, which is
    // where all the early returns live.
    const preamble = source.slice( runAt, firstPostAt );
    const returnsAboveClear = ( preamble.slice( 0, clearAt - runAt ).match( /return;/g ) || [] ).length;
    const returnsBelowClear = ( preamble.slice( clearAt - runAt ).match( /return;/g ) || [] ).length;
    expect( returnsAboveClear ).toBe( 1 );
    expect( preamble.slice( 0, clearAt - runAt ) ).toMatch( /railTerminalRef\.current \) return;/ );
    // The point of the move: there are several, and all of them are now below the clear.
    expect( returnsBelowClear ).toBeGreaterThanOrEqual( 4 );
    // Read into a local and cleared, never read twice inside the run.
    const run = source.slice( runAt, source.indexOf( 'const proceed = useCallback' ) );
    expect( run.match( /resetCartRef\.current = false;/g ) || [] ).toHaveLength( 1 );
    expect( run.match( /resetCartRef\.current;/g ) || [] ).toHaveLength( 1 );
    // EXACTLY TWO clears in the file, and the second one is load-bearing rather than a duplicate:
    // the latch disarms the one-shot when it turns a `startNewCart` call away, so a flag the
    // customer armed cannot survive into their next ordinary Checkout press. The behavioural case
    // for it is in the double-fire describe.
    expect( source.match( /resetCartRef\.current = false;/g ) || [] ).toHaveLength( 2 );
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
    // The branch now carries the BASKET condition too: a missing address blocks only a basket that
    // needs delivery, while a missing identity (`mode === 'create'`) blocks every basket. `mode`
    // and not `profile?.email`, because `profile` is a `useState` value captured in this closure
    // and is still undefined on a FIRST click - which would open the address editor for a
    // contribution-only cart belonging to a fully provisioned customer.
    expect( source ).toMatch(
      /if \( status === 'required' && \( needsDelivery \|\| mode === 'create' \) \)/ );
    expect( source ).toMatch( /const needsDelivery = cartRequiresDelivery\(\);/ );
    // NO ARGUMENT: the helper must read storage, not the `items` state the useCallback captured.
    expect( source ).not.toMatch( /cartRequiresDelivery\( items \)/ );
    // The branch must never test the state directly.
    expect( source ).not.toMatch( /if \( profileStatus === 'required' \)/ );
    // Three posts now, all keyed on the `lineItems` ARGUMENT rather than on a storage read: the
    // first (carrying the one-shot reset flag), the post-save retry, and the one rotation.
    expect( source.match( /postPrepare\( session, lineItems(, resetCart)? \)/g ) || [] )
      .toHaveLength( 3 );
  } );
} );

/**
 * THE CTA, WHATEVER IT CURRENTLY SAYS.
 *
 * `PillButton`'s accessible name is its ACTION segment alone, and that segment is state-dependent:
 * 'Proceed' with no identity, 'Pay securely' once ready, 'Try again' after a blocked attempt,
 * 'Preparing...' while busy. A test that pins one of them is really pinning the state it happened
 * to be in, which is not what any of the cases below are about.
 */
const CTA = /Pay securely|Proceed|Try again|Preparing/;

describe( 'a contribution basket skips the address gate, on the FIRST click', () => {
  /**
   * T13. The server skip is necessary but not sufficient.
   *
   * `deriveStatus('PROFILE_READY', addressComplete=false)` returns 'required', which opens the
   * address editor and returns -- so a contribution-only cart would never reach the server's
   * delivery skip at all. The gate now also asks whether the BASKET needs delivery.
   *
   * THE FIRST CLICK IS THE CASE THAT MATTERS, and that is why `profileStatus` starts 'unknown'
   * here. `profile` is a `useState` value captured in `proceed`'s closure and `setProfile` does
   * not change it for the remainder of the invocation, so a gate written as `!profile?.email`
   * would be true on a first click and would open the editor for a fully provisioned customer --
   * failing on click one and working on click two. The gate reads `mode`, which is reassigned
   * from the readiness reply inside the same invocation.
   */
  it( 'does not open the address editor and DOES call prepare', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: { ...PROFILE_READY, addressComplete: false, address: null } },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-c1' } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );

    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
    expect( screen.queryByTestId( 'checkout-profile' ) ).toBeNull();
  } );

  it( 'DOES open the address editor on the same first click for a physical line', async () => {
    // The control. A physical basket genuinely has a place of supply, and the gate must still
    // demand one -- the requirement became conditional, not optional.
    signedIn();
    stubFetch( {
      profile: { body: { ...PROFILE_READY, addressComplete: false, address: null } },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-c2' } },
    } );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    expect( await screen.findByTestId( 'checkout-profile' ) ).toBeInTheDocument();
  } );

  it( 'opens the editor for BOTH baskets when the identity itself is missing', async () => {
    // `mode === 'create'` is "there is no identity yet", and that blocks every basket. A
    // brand-new customer whose first action is a contribution is asked once for an address to
    // CREATE a checkout identity, not to deliver the contribution, and never asked again.
    for ( const seed of [ () => cart.setContribution( MID.variantId ), () => cart.addItem( PRODUCT, 1 ) ] )
    {
      window.localStorage.clear();
      signedIn();
      stubFetch( { profile: { body: PROFILE_REQUIRED } } );
      seed();
      const { unmount } = render( <Cart /> );
      fireEvent.click(
        await screen.findByRole( 'button', { name: CTA } ) );
      expect( await screen.findByTestId( 'checkout-profile' ) ).toBeInTheDocument();
      unmount();
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    }
  } );
} );

describe( 'a mixed basket is refused in the browser, before the auth gate', () => {
  it( 'shows the notice, disables Checkout and calls no prepare', async () => {
    signedIn();
    const fetchMock = stubFetch( { profile: { body: PROFILE_READY } } );
    cart.setContribution( MID.variantId );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    const button = await screen.findByRole(
      'button', { name: CTA } );
    expect( button ).toBeDisabled();
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 0 );
  } );

  it( 'removing the kiosk lets the SAME click through, with no re-render in between', async () => {
    /*
     * The stale-closure case, driven as the sequence that produces it.
     *
     * `proceed` is `useCallback(..., [profile, profileStatus])` and `items` is NOT a dependency,
     * so a mixed-basket check reading `items` would see the value captured at the last render --
     * stale after a row is removed with no intervening profile change. The helper is called with
     * NO ARGUMENT so it reads storage, which is the same thing `toLineItems()` does one line
     * below for the same reason.
     */
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-c3' } },
    } );
    cart.setContribution( MID.variantId );
    cart.addItem( PRODUCT, 1 );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: `Remove ${ PRODUCT.name }` } ) );
    fireEvent.click( await screen.findByRole(
      'button', { name: CTA } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
  } );

  it( 'the mirror: a kiosk added AFTER the render is still refused, because proceed reads storage',
    async () => {
      /*
       * This page does not subscribe to cart-changed events -- it reads `readCart()` on mount and
       * after its own mutations -- so a line added from elsewhere leaves the render stale and the
       * CTA enabled. That is exactly the case the no-argument storage read exists for, and
       * asserting it here is stronger than asserting the disabled button: it proves the guard
       * holds when the render has NOT caught up.
       *
       * In a real browser the kiosk is added on the shop page and the customer then navigates to
       * /cart/, which is a fresh mount and the case above. This is the same refusal reached the
       * other way.
       */
      signedIn();
      const fetchMock = stubFetch( { profile: { body: PROFILE_READY } } );
      cart.setContribution( MID.variantId );
      render( <Cart /> );
      const button = await screen.findByRole( 'button', { name: CTA } );
      expect( button ).not.toBeDisabled();

      // Storage changes under the render.
      cart.addItem( PRODUCT, 1 );
      fireEvent.click( button );

      await waitFor( () => expect(
        screen.getByText( /A contribution is paid on its own/ ) ).toBeInTheDocument() );
      expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 0 );
    } );
} );

describe( 'two clicks cannot post two prepares - the measured live blocker', () => {
  /**
   * THE BUG, from API Gateway and Lambda logs on checkout v11, not from reasoning.
   *
   * `prepare-checkout` was posted TWICE in rapid succession. The first answered 200 and reserved
   * the cart; the second, one to three seconds later, reached Wix on that already-reserved cart,
   * `wix_ecom` raised, and the handler's `except wix_ecom.WixEcomError` answered 502
   * `CATALOGUE_UNAVAILABLE` -- which this page renders as "We could not prepare this order."
   * EVERY payment attempt failed, and it was the customer's own first attempt that broke their
   * second.
   *
   * `disabled={ busy || ... }` did not stop it because `busy` is React STATE: `setBusy(true)` does
   * not disable the button until a render commits, so both clicks are already inside `proceed`
   * before the attribute changes. State cannot guard re-entry into the function that sets it.
   *
   * HOW THE CONCURRENCY IS REPRODUCED, AND WHY `fireEvent.click` TWICE IS NOT ENOUGH. `fireEvent`
   * wraps each event in `act()`, which commits the render before returning -- so by the second
   * call `busy` is already true, the button is already `disabled`, and jsdom swallows the click.
   * Two `fireEvent.click`s therefore PASS against the broken code and prove nothing. Measured:
   * they do.
   *
   * Dispatching inside ONE `act()` block is the faithful shape. React cannot commit between
   * events batched in a single act block, exactly as a browser cannot commit between two click
   * events delivered in the same task. Measured with the latch removed: three dispatches produce
   * THREE prepare posts. With the latch: one.
   */
  it( 'posts prepare ONCE for three clicks delivered before any render commits', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-d1' } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    const button = await screen.findByRole( 'button', { name: CTA } );
    await act( async () => {
      button.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      button.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      button.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      await new Promise( resolve => { setTimeout( resolve, 120 ); } );
    } );

    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
    // And it STAYS one: the extra clicks are dropped, not deferred.
    await new Promise( resolve => { setTimeout( resolve, 30 ); } );
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
  } );

  it( 'posts prepare ONCE even while the first post is still unresolved', async () => {
    // The production timing: the first prepare takes a second or two against Wix, and the extra
    // clicks arrive while it is in flight rather than after it settles.
    signedIn();
    let release: ( () => void ) | null = null;
    const held = new Promise<void>( resolve => { release = resolve; } );
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-d2' } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    const button = await screen.findByRole( 'button', { name: CTA } );
    await act( async () => {
      button.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      button.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      if ( release ) release();
      await held;
      await new Promise( resolve => { setTimeout( resolve, 120 ); } );
    } );

    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
  } );

  it( 'RELEASES the latch, so a second checkout is possible after the first finishes', async () => {
    /*
     * The other half, and the one that matters if the latch is ever written without a `finally`:
     * a latch that is set and never cleared turns one failed attempt into a page that can never
     * check out again, which is strictly worse than the double-post it replaced.
     *
     * The first run ends in a non-latching refusal (`CART_RECONCILIATION_REQUIRED` leaves
     * `paymentBlocked` alone and does not touch `railTerminalRef`), so the only thing that could
     * stop the second click is the in-flight ref.
     */
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    const button = await screen.findByRole( 'button', { name: CTA } );
    fireEvent.click( button );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );

    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
  } );

  it( 'DISARMS the reset one-shot when it turns a Start-a-new-cart click away', async () => {
    /*
     * `startNewCart` arms `resetCartRef` and then calls `proceed`. If the latch drops that call
     * with the flag still armed, the customer's NEXT ordinary Checkout press posts
     * `resetCart: true` and the server abandons a saved cart nobody asked to discard --
     * `resetCartRef`'s own docstring names that as the failure to avoid.
     *
     * Driven as the sequence that produces it: the reset is offered, the control is clicked
     * TWICE in one synchronous block so the second entry is the refused one, and the third post
     * (an ordinary click, after the run finishes) must not carry the flag.
     */
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: [
        { ok: false, status: 409, body: { error: 'CART_RESET_REQUIRED' } },
        { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
        { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
      ],
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    const control = await screen.findByRole( 'button', { name: 'Start a new cart' } );

    // Batched in ONE act block, so the second entry is genuinely the refused one rather than a
    // click jsdom swallowed against a committed `disabled`.
    await act( async () => {
      control.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      control.dispatchEvent( new MouseEvent( 'click', { bubbles: true } ) );
      await new Promise( resolve => { setTimeout( resolve, 120 ); } );
    } );
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 );

    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 3 ) );

    const posts = callsTo( fetchMock, PREPARE_URL, 'prepare' );
    expect( posts[ 0 ].body.resetCart ).toBeUndefined();
    expect( posts[ 1 ].body.resetCart ).toBe( true );
    // THE ASSERTION THIS CASE EXISTS FOR: the dropped click's flag did not survive into here.
    expect( posts[ 2 ].body.resetCart ).toBeUndefined();
  } );

  it( 'keeps the latch OUTSIDE the run, so no early return can skip it', () => {
    // A source pin, because the guarantee is structural rather than observable: `runCheckout` has
    // fourteen `return` statements, and a latch checked inside it would need every one of them to
    // clear the flag. Pinning the shape stops a later edit "simplifying" the wrapper away.
    const source = fs.readFileSync( path.resolve( __dirname, '../pages/cart.tsx' ), 'utf8' );
    const wrapper = source.slice( source.indexOf( 'const proceed = useCallback' ) );
    expect( wrapper ).toMatch( /if \( proceedInFlightRef\.current \)/ );
    expect( wrapper ).toMatch( /proceedInFlightRef\.current = true;/ );
    expect( wrapper ).toMatch( /finally\s*\{\s*proceedInFlightRef\.current = false;/ );
    // The run itself must not check the latch: two checks in two places is how one of them ends
    // up being the only one maintained.
    //
    // ASSERTED ON THE USE, NOT ON THE MENTION, for the reason the contribution-endpoint pin in
    // BlogContribution.test.tsx gives: the comment that explains why the latch is NOT here has to
    // be able to name it, and a text search cannot tell an explanation from a check. What must not
    // come back is an expression that reads or writes the ref -- `.current` is what every such
    // expression needs, and a bare mention cannot latch anything.
    const run = source.slice( source.indexOf( 'const runCheckout = useCallback' ),
      source.indexOf( 'const proceed = useCallback' ) );
    expect( run ).not.toMatch( /proceedInFlightRef\s*\.\s*current/ );
    // And `railTerminalRef` is untouched: this latch is additional, never a replacement.
    expect( run ).toMatch( /if \( railTerminalRef\.current \) return;/ );
  } );
} );

describe( 'the contribution row CHOOSES an amount, it does not count copies', () => {
  /**
   * WHAT THIS BLOCK STOPPED ASSERTING ON 2026-10-04. The row used to be a free-text number field
   * with a draft string, a commit on blur or Enter, ₹10–₹1,00,000 bounds and a help line on
   * refusal. There was an `it.each` over `''`, `'4'`, `'49.5'`, `'100001'` and `'-10'` proving
   * each left the stored amount alone, and a case proving a valid amount committed on both blur
   * and Enter.
   *
   * All of it tested a control that can no longer exist: the amount is the chosen variant's own
   * price, so the row offers the three amounts and there is no draft, no commit moment and no
   * invalid value to leave the cart alone for. The cases below assert what replaced it.
   */
  it( 'has an amount chooser and no Qty stepper', async () => {
    signedIn();
    stubFetch( { profile: { body: PROFILE_READY } } );
    cart.setContribution( MID.variantId );
    render( <Cart /> );

    const chooser = await screen.findByLabelText( 'Contribution amount' );
    expect( chooser ).toBeInTheDocument();
    // A stepper is the wrong control: two copies of a ₹250 contribution is not a ₹500
    // contribution, it is a basket the server refuses as two contributions.
    expect( screen.queryByLabelText( 'Qty' ) ).toBeNull();
    expect( ( chooser as HTMLSelectElement ).value ).toBe( MID.variantId );
    // Exactly the three choices, in config order, each labelled with its rupee figure.
    expect( Array.from( ( chooser as HTMLSelectElement ).options ).map( o => o.textContent ) )
      .toEqual( CONTRIBUTION_CHOICES.map( choice => `\u20B9${ choice.rupees }` ) );
  } );

  it( 'REPLACES the line when another amount is chosen, and keeps quantity 1', async () => {
    signedIn();
    stubFetch( { profile: { body: PROFILE_READY } } );
    cart.setContribution( MID.variantId );
    render( <Cart /> );

    const chooser = await screen.findByLabelText( 'Contribution amount' );
    fireEvent.change( chooser, { target: { value: LOW.variantId } } );

    expect( cart.readCart() ).toHaveLength( 1 );
    expect( cart.readCart()[ 0 ].variantId ).toBe( LOW.variantId );
    expect( cart.readCart()[ 0 ].quantity ).toBe( 1 );
    // And the row re-renders from the cart rather than from its own state.
    expect( ( await screen.findByLabelText( 'Contribution amount' ) as HTMLSelectElement ).value )
      .toBe( LOW.variantId );
  } );

  it( 'hides RedemptionPanel on a contribution cart and shows it otherwise', async () => {
    signedIn();
    stubFetch( { profile: { body: PROFILE_READY } } );
    cart.setContribution( MID.variantId );
    const { unmount } = render( <Cart /> );
    // A contribution takes neither a coupon nor a gift card: a coupon would make the recorded
    // amount differ from the amount contributed, and spending store credit is not a contribution.
    expect( screen.queryByLabelText( /Coupon code/i ) ).toBeNull();
    unmount();

    window.localStorage.clear();
    cart.addItem( PRODUCT, 1 );
    render( <Cart /> );
    expect( await screen.findByLabelText( /Coupon code/i ) ).toBeInTheDocument();
  } );
} );

describe( 'CONTRIBUTION_NOT_PAYABLE says what is true instead of naming an impossible action', () => {
  /**
   * Review pass 3, CR3-3. The server arm this covers fires when Wix will not price a
   * contribution-only cart - most likely because it wants a delivery destination for a PHYSICAL
   * product, which is what the live `Contribute` product is. It used to answer `CART_NOT_PAYABLE`,
   * whose copy is "Please review your cart and try again": the basket is one donation, so there is
   * nothing in it to review and no edit that changes the answer. The same dead end
   * `CART_RESET_REQUIRED` was given its own code to avoid.
   */
  it( 'renders the honest sentence, offers no cart-review instruction, and does not latch', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: [
        { ok: false, status: 409, body: {
          error: 'CONTRIBUTION_NOT_PAYABLE',
          message: 'Contributions cannot be taken right now. Nothing has been charged.' } },
        { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-cnp' } },
      ],
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );

    await waitFor( () => expect( screen.getByText(
      /Contributions cannot be taken right now\./ ) ).toBeInTheDocument() );
    // The two sentences the generic code would have produced, neither of which is true here.
    expect( screen.queryByText( /review your cart/i ) ).toBeNull();
    expect( screen.getByText( /Nothing has been charged\./ ) ).toBeInTheDocument();

    // NOT latched: no payment was attempted, and a dashboard setting can be fixed between two
    // presses, so a second click must still reach the server.
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
  } );

  it( 'is a DISTINCT outcome from CART_NOT_PAYABLE rather than a relabelling of it', async () => {
    // The control, and the reason the split is worth a code: the generic refusal must keep its
    // own words, so the two conditions stay distinguishable from the customer's side too.
    signedIn();
    stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: { error: 'CART_NOT_PAYABLE' } },
    } );
    cart.setContribution( MID.variantId );

    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );

    await waitFor( () => expect(
      screen.getByText( /Please review your cart and try again\./ ) ).toBeInTheDocument() );
    expect( screen.queryByText( /Contributions cannot be taken right now/ ) ).toBeNull();
  } );
} );

describe( 'CART_RESET_REQUIRED carries an action, not only words', () => {
  it( 'renders a control that re-posts the same prepare with resetCart and the same lineItems',
    async () => {
      signedIn();
      const fetchMock = stubFetch( {
        profile: { body: PROFILE_READY },
        prepare: [
          { ok: false, status: 409, body: { error: 'CART_RESET_REQUIRED' } },
          { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-r2' } },
        ],
      } );
      cart.setContribution( MID.variantId );
      render( <Cart /> );
      fireEvent.click( await screen.findByRole(
        'button', { name: CTA } ) );

      const control = await screen.findByRole( 'button', { name: 'Start a new cart' } );
      expect( screen.getByText( /too many items to update/ ) ).toBeInTheDocument();
      fireEvent.click( control );

      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
      const [ first, second ] = callsTo( fetchMock, PREPARE_URL, 'prepare' );
      expect( first.body.resetCart ).toBeUndefined();
      expect( second.body.resetCart ).toBe( true );
      expect( second.body.lineItems ).toEqual( first.body.lineItems );
      // The BROWSER cart is untouched: the reset abandons the SERVER pointer only, and the next
      // prepare rebuilds the Wix cart from this same localStorage basket.
      expect( cart.readCart() ).toHaveLength( 1 );
      expect( cart.readCart()[ 0 ].variantId ).toBe( MID.variantId );
    } );

  it( 'does NOT leak resetCart into a later click when the reset click is refused before posting',
    async () => {
      /*
       * THE ONE-SHOT, DRIVEN THROUGH AN EARLY RETURN. The case above covers the happy path only:
       * first post omits `resetCart`, second sends `true`. Nothing stopped the reset click short
       * of the post.
       *
       * Here it is stopped. The reset is offered, a /shop/ line arrives (the second tab, or a
       * `/shop/` add, that the mixed-basket refusal exists for), and "Start a new cart" is clicked
       * - which arms the flag and calls `proceed`, where the mixed-basket check refuses BEFORE the
       * auth gate and returns having posted nothing. The customer then removes the stray line and
       * checks out normally.
       *
       * That second post must NOT carry `resetCart`. The customer asked to discard a saved cart
       * once, was refused, and fixed their basket; discarding the server pointer on the ordinary
       * Checkout click that follows is a destructive write nobody requested. Bounded - no
       * reservation, attempt or gateway order is written, and the browser cart is untouched - but a
       * surprise rather than a recovery, which is exactly what `resetCartRef`'s docstring promises
       * it is not.
       */
      signedIn();
      const fetchMock = stubFetch( {
        profile: { body: PROFILE_READY },
        prepare: [
          { ok: false, status: 409, body: { error: 'CART_RESET_REQUIRED' } },
          { body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'att-r3' } },
        ],
      } );
      cart.setContribution( MID.variantId );
      render( <Cart /> );
      fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );

      const control = await screen.findByRole( 'button', { name: 'Start a new cart' } );
      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );

      // The basket turns mixed between the offer and the click.
      await act( async () => { cart.addItem( PRODUCT, 1 ); } );
      fireEvent.click( control );

      // Refused locally: still one post, and the refusal is the shared wording.
      await waitFor( () => expect(
        screen.getByText( /A contribution is paid on its own/ ) ).toBeInTheDocument() );
      expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );

      // Fix the basket, then check out the ordinary way.
      await act( async () => { cart.removeItem( PRODUCT.id ); } );
      fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );

      const [ first, second ] = callsTo( fetchMock, PREPARE_URL, 'prepare' );
      expect( first.body.resetCart ).toBeUndefined();
      expect( second.body.resetCart ).toBeUndefined();
      // And the saved cart the customer never asked to discard is still theirs to reset: the
      // control comes back with the next CART_RESET_REQUIRED, which is the recoverable direction.
      expect( cart.readCart() ).toHaveLength( 1 );
      expect( cart.readCart()[ 0 ].variantId ).toBe( MID.variantId );
    } );
} );

describe( 'the request key is scoped to the basket, and rotates once on INTENT_CHANGED', () => {
  /** The two slots the key lifecycle uses. Named here so a rename fails loudly. */
  const KEY_SLOT = 'wc_checkout_request_key';
  const BASKET_SLOT = 'wc_checkout_request_basket';

  async function clickCheckout (): Promise<void> {
    fireEvent.click( await screen.findByRole(
      'button', { name: CTA } ) );
  }

  it( 'sends the SAME key for two clicks on an unchanged basket', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      // A quiet, NON-LATCHING refusal: `PAYMENT_INITIATION_DISABLED` sets `paymentBlocked`, which
      // changes the CTA's action segment and the notice -- neither of which this case is about,
      // and both of which would make the second click measure the wrong thing.
      prepare: { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
    } );
    cart.addItem( PRODUCT, 1 );
    render( <Cart /> );

    await clickCheckout();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
    await clickCheckout();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );

    const keys = callsTo( fetchMock, PREPARE_URL, 'prepare' ).map( call => call.body.requestKey );
    expect( keys[ 0 ] ).toBe( keys[ 1 ] );
    // Two slots, FIXED. The previous shape minted a key once per tab and never cleared it; a
    // per-basket slot NAME would grow without bound.
    expect( Object.keys( window.sessionStorage ).sort() )
      .toEqual( [ BASKET_SLOT, KEY_SLOT ].sort() );
  } );

  it( 'sends DIFFERENT keys for kiosk then contribution, and never sets paymentBlocked',
    async () => {
      signedIn();
      const fetchMock = stubFetch( {
        profile: { body: PROFILE_READY },
        prepare: { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
      } );
      cart.addItem( PRODUCT, 1 );
      render( <Cart /> );
      await clickCheckout();
      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );

      // Dismiss, then replace the basket with a contribution.
      await act( async () => {
        cart.removeItem( cart.readCart()[ 0 ].ref );
        cart.setContribution( LOW.variantId );
      } );
      await clickCheckout();
      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );

      const keys = callsTo( fetchMock, PREPARE_URL, 'prepare' ).map( call => call.body.requestKey );
      expect( keys[ 0 ] ).not.toBe( keys[ 1 ] );
      expect( screen.queryByRole( 'button', { name: /Try again/ } ) ).toBeNull();
      // Two slots, still. A per-basket slot name would be three by now.
      expect( Object.keys( window.sessionStorage ) ).toHaveLength( 2 );
    } );

  it( 'A then B then back to A mints a THIRD key, never A\'s original', async () => {
    /*
     * Deliberate, and the reason the slot name is not the fingerprint. Getting back to A re-ran
     * the server-side reconcile, whose add/remove commands mint new `lineItemId`s and move
     * `cart.revision`, so A's original reservation CANNOT match any more. Resuming it would be a
     * guaranteed refusal rather than a resumption.
     */
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
    } );
    cart.setContribution( LOW.variantId );
    render( <Cart /> );
    await clickCheckout();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );

    await act( async () => { cart.setContribution( MID.variantId ); } );
    await clickCheckout();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );

    await act( async () => { cart.setContribution( LOW.variantId ); } );
    await clickCheckout();
    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 3 ) );

    const keys = callsTo( fetchMock, PREPARE_URL, 'prepare' ).map( call => call.body.requestKey );
    expect( new Set( keys ).size ).toBe( 3 );
  } );

  it( 'rotates ONCE on INTENT_CHANGED and reaches the second answer', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: [
        { ok: false, status: 409,
          body: { status: 'CHECKOUT_REJECTED', reason: 'INTENT_CHANGED' } },
        // Non-latching, so "not latched" is measurable: the second answer must not itself be the
        // thing that sets `paymentBlocked`.
        { ok: false, status: 409, body: { error: 'CART_RECONCILIATION_REQUIRED' } },
      ],
    } );
    cart.setContribution( MID.variantId );
    render( <Cart /> );
    await clickCheckout();

    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
    const keys = callsTo( fetchMock, PREPARE_URL, 'prepare' ).map( call => call.body.requestKey );
    expect( keys[ 0 ] ).not.toBe( keys[ 1 ] );
    // NOT LATCHED: the refusal no human caused did not end the tab's ability to pay. The CTA is
    // still the ordinary one rather than the post-block 'Try again'.
    expect( await screen.findByRole( 'button', { name: /Pay securely/ } ) ).toBeInTheDocument();
  } );

  it( 'is BOUNDED: a second INTENT_CHANGED latches and issues no third post', async () => {
    signedIn();
    const fetchMock = stubFetch( {
      profile: { body: PROFILE_READY },
      prepare: { ok: false, status: 409,
        body: { status: 'CHECKOUT_REJECTED', reason: 'INTENT_CHANGED' } },
    } );
    cart.setContribution( MID.variantId );
    render( <Cart /> );
    await clickCheckout();

    await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 ) );
    // Exactly two: the original and the one rotation. `rotated` is a local, so one per click.
    await new Promise( resolve => { setTimeout( resolve, 20 ); } );
    expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 2 );
  } );

  it( 'the asymmetry holds: another CHECKOUT_REJECTED reason latches on the FIRST refusal',
    async () => {
      // The rotation is scoped to the one reason a NEW KEY can clear. An ownership or snapshot
      // failure is not it, and a retry would only repeat it.
      signedIn();
      const fetchMock = stubFetch( {
        profile: { body: PROFILE_READY },
        prepare: { ok: false, status: 409,
          body: { status: 'CHECKOUT_REJECTED', reason: 'SNAPSHOT_MISMATCH' } },
      } );
      cart.setContribution( MID.variantId );
      render( <Cart /> );
      await clickCheckout();

      await waitFor( () => expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 ) );
      await new Promise( resolve => { setTimeout( resolve, 20 ); } );
      expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
    } );

  it( 'CART_PAYMENT_IN_FLIGHT navigates, sets no latch, rotates nothing and keeps both slots',
    async () => {
      /*
       * Asserted at the 409 DELIBERATELY. `CART_PAYMENT_IN_FLIGHT` is in the handler's
       * `_CART_BLOCKED` tuple, so the code is 409 rather than 200 -- and it changes nothing about
       * the behaviour, because `postPrepare` short-circuits on 401 only and branches on
       * `data.status` thereafter. Recorded so a reader who checks the code against the design
       * finds the discrepancy already resolved.
       *
       * This is the guard WORKING, not a regression: one cart, one payable modal. Dismissing the
       * Razorpay modal makes no server call, so the earlier attempt stays in flight and the cart
       * pointer still names it.
       */
      signedIn();
      const fetchMock = stubFetch( {
        profile: { body: PROFILE_READY },
        prepare: { ok: false, status: 409, body: {
          status: 'CHECKOUT_AMBIGUOUS', reason: 'CART_PAYMENT_IN_FLIGHT',
          paymentAttemptId: 'pa_x',
        } },
      } );
      cart.setContribution( MID.variantId );
      render( <Cart /> );
      await clickCheckout();

      await waitFor( () => expect( navigatedTo ).toContain( '/checkout/status/?a=pa_x' ) );
      expect( callsTo( fetchMock, PREPARE_URL, 'prepare' ) ).toHaveLength( 1 );
      expect( Object.keys( window.sessionStorage ) ).toHaveLength( 2 );
      // No latch: `paymentBlocked` would change the CTA's action segment to 'Try again'.
      expect( screen.queryByRole( 'button', { name: /Try again/ } ) ).toBeNull();
    } );
} );

