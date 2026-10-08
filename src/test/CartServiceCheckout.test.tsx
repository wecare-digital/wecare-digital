import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as cart from '../lib/cart';
import * as customerAuth from '../lib/customerAuth';
import { SERVICE_CHOICES } from '../config/services';
import { SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

/**
 * Phase O-1 on /cart/: the prepare body carries `serviceIntentId` for a services basket ONLY, and
 * every service refusal renders its one sentence without latching the Checkout button.
 * jsdom render only - no layout or browser claim is made here.
 */
vi.mock( '../components/CheckoutProfile', () => ( {
  default: () => <div data-testid="checkout-profile" />,
} ) );
import Cart from '../pages/cart';

const [ SUBMIT ] = SERVICE_CHOICES;
const INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f';
/**
 * The LIVE Wix price, injected. `setServiceLine` takes the line paise explicitly since
 * 2026-10-08: `src/config/services.ts` no longer declares a price (owner decision — a price is
 * editable in Wix with no deploy), so the cart row's displayed amount has to come from the live
 * figure the buy box resolved. One constant here rather than a number per call, and deliberately
 * NOT 9900: a figure that happens to match the old constant could pass for the wrong reason.
 */
const LIVE_PAISE = 14900;

const CTA = /Pay securely|Proceed|Try again|Preparing/;
const ADDRESS = {
  addressLine1: '12 MG Road', addressLine2: '', locality: '', city: 'Bengaluru',
  state: 'Karnataka', postalCode: '560001', country: 'India', countryCode: 'IN',
  fullAddress: '12 MG Road, Bengaluru, Karnataka, 560001, India',
};
const PROFILE_READY = {
  status: 'PROFILE_READY', contactId: 'c1', name: 'Asha Sen', firstName: 'Asha',
  lastName: 'Sen', email: 'asha@example.com', phone: '+919330994400', addressComplete: true,
  address: ADDRESS, emailVerified: true,
};

let prepareBodies: Record<string, unknown>[] = [];

function stub ( prepare: Array<{ status: number; body: unknown }> ) {
  const queue = [ ...prepare ];
  vi.stubGlobal( 'fetch', vi.fn( async ( _url: string, init?: { body?: string } ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    if ( body.action === 'profile' )
    {
      return { ok: true, status: 200, json: async () => PROFILE_READY };
    }
    prepareBodies.push( body );
    const next = queue.length > 1 ? queue.shift()! : queue[ 0 ];
    return { ok: next.status < 400, status: next.status, json: async () => next.body };
  } ) );
}

beforeEach( () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  prepareBodies = [];
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( {
    accessToken: 'tok', expiresAt: Date.now() + 3_600_000,
  } );
  Object.defineProperty( window, 'location', {
    configurable: true,
    value: { ...window.location, search: '', assign: () => undefined, replace: () => undefined },
  } );
} );
afterEach( () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
} );

describe( 'the prepare body', () => {
  it( 'carries serviceIntentId for a services basket', async () => {
    stub( [ { status: 200, body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'a' } } ] );
    cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( prepareBodies ).toHaveLength( 1 ) );
    expect( prepareBodies[ 0 ].serviceIntentId ).toBe( INTENT );
    expect( JSON.stringify( prepareBodies[ 0 ] ) ).not.toMatch( /amount|price|9900/i );
  } );

  it( 'is unchanged for an ordinary basket', async () => {
    stub( [ { status: 200, body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'a' } } ] );
    cart.addItem( { id: 'wix-abc-123', name: 'Kiosk', slug: 'kiosk', formattedPrice: '₹1.00',
      price: '1.00', currency: 'INR', inStock: true, tagline: 't', body: [] }, 1 );
    render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( prepareBodies ).toHaveLength( 1 ) );
    expect( Object.keys( prepareBodies[ 0 ] ).sort() ).toEqual( [ 'action', 'lineItems', 'requestKey' ] );
  } );
} );

describe( 'the request key keys on the service intent (review AMEND-INTENT-RESUME)', () => {
  const AMEND = SERVICE_CHOICES[ 1 ];
  const INTENT_B = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e60';
  const DISABLED = { status: 200, body: { status: 'PAYMENT_INITIATION_DISABLED', paymentAttemptId: 'a' } };

  async function prepareOnce () {
    const before = prepareBodies.length;
    const view = render( <Cart /> );
    fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
    await waitFor( () => expect( prepareBodies ).toHaveLength( before + 1 ) );
    view.unmount();
    return prepareBodies[ prepareBodies.length - 1 ];
  }

  it( 'keeps the same key for the same lines and the same intent', async () => {
    stub( [ DISABLED ] );
    cart.setServiceLine( AMEND.variantId, INTENT, LIVE_PAISE );
    const first = await prepareOnce();
    const second = await prepareOnce();
    expect( prepareBodies ).toHaveLength( 2 );
    expect( second.requestKey ).toBe( first.requestKey );
  } );

  it( 'mints a fresh key when the amendment target changes the intent, lines unchanged', async () => {
    stub( [ DISABLED ] );
    cart.setServiceLine( AMEND.variantId, INTENT, LIVE_PAISE );
    const first = await prepareOnce();
    cart.setServiceLine( AMEND.variantId, INTENT_B, LIVE_PAISE );
    const second = await prepareOnce();
    expect( prepareBodies ).toHaveLength( 2 );
    expect( second.serviceIntentId ).toBe( INTENT_B );
    expect( second.lineItems ).toEqual( first.lineItems );
    expect( second.requestKey ).not.toBe( first.requestKey );
  } );
} );

describe( 'service refusals', () => {
  for ( const [ code, message ] of Object.entries( SERVICE_REFUSAL_MESSAGES ) )
  {
    it( `${ code } renders its sentence and does not latch`, async () => {
      stub( [ { status: 409, body: { error: code, message } } ] );
      cart.setServiceLine( SUBMIT.variantId, INTENT, LIVE_PAISE );
      render( <Cart /> );
      fireEvent.click( await screen.findByRole( 'button', { name: CTA } ) );
      await waitFor( () => expect( screen.getByText( message ) ).toBeInTheDocument() );
      const again = await screen.findByRole( 'button', { name: CTA } );
      expect( again ).not.toBeDisabled();
      fireEvent.click( again );
      await waitFor( () => expect( prepareBodies ).toHaveLength( 2 ) );
    } );
  }
} );
