import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fs from 'fs';
import path from 'path';
import * as customerAuth from '../lib/customerAuth';
import * as cart from '../lib/cart';
import { SERVICE_CHOICES, serviceByKind } from '../config/services';
import { SERVICE_PRICES_URL } from '../lib/servicePricing';
import ServiceRequestPurchase from '../components/ServiceRequestPurchase';

const pushed: string[] = [];
vi.mock( 'next/router', () => ( {
  useRouter: () => ( { push: async ( url: string ) => { pushed.push( String( url ) ); } } ),
} ) );

/**
 * THE LIVE PRICE PAYLOAD used by every case below. Four DIFFERENT figures, and none of them the
 * prices live today (99/99/350/49), so a passing assertion cannot be a leaked constant — and the
 * two services that share ₹99 in production are deliberately given different figures here,
 * because "each is a different item" is the regression this file has to catch.
 */
const LIVE = {
  currency: 'INR',
  prices: {
    'submit-request': { available: true, paise: 14900 },
    'request-amendment': { available: true, paise: 20100 },
    'drop-docs': { available: true, paise: 45050 },
    'vault': { available: true, paise: 7700 },
  },
};
const FACE: Record<string, string> = {
  SUBMIT_REQUEST: '₹149', REQUEST_AMENDMENT: '₹201', DROP_DOCS: '₹450.50', VAULT: '₹77',
};

/**
 * The buy box, shared by all four service pages. jsdom render only: the pages are public and
 * statically exported, but this box's signed-in states are client-only, so no browser rendering
 * claim is made.
 *
 * The three target-taking services (amendment, Drop Docs, Vault) are driven through ONE code path
 * keyed on `service.needsTarget`, so each is exercised rather than assumed to behave like the
 * amendment it was copied from.
 */
const [ SUBMIT, AMEND ] = SERVICE_CHOICES;
const INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f';
let navigatedTo = '';
let calls: Array<{ url: string; body: Record<string, unknown> }> = [];

/**
 * The price endpoint is stubbed for EVERY case, with the live payload by default, because the
 * card now refuses to offer a pay CTA without a resolved price — so a case that did not stub it
 * would be testing the unavailable state by accident. Pass `prices` to override it.
 */
function stub (
  routes: Record<string, { status: number; body: unknown }>,
  prices: { status: number; body: unknown } = { status: 200, body: LIVE },
) {
  vi.stubGlobal( 'fetch', vi.fn( async ( url: string, init?: { body?: string } ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    calls.push( { url: String( url ), body } );
    if ( String( url ).includes( '/ecommerce/service-prices' ) )
    {
      return { ok: prices.status < 400, status: prices.status, json: async () => prices.body };
    }
    const key = Object.keys( routes ).find( fragment => String( url ).includes( fragment ) );
    const reply = key ? routes[ key ] : { status: 500, body: {} };
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
  } ) );
}

function signedIn () {
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( {
    accessToken: 'tok', expiresAt: Date.now() + 3_600_000,
  } );
}

beforeEach( () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  navigatedTo = '';
  pushed.length = 0;
  calls = [];
  Object.defineProperty( window, 'location', {
    configurable: true,
    value: { ...window.location, assign: ( url: string ) => { navigatedTo = String( url ); } },
  } );
} );
afterEach( () => { vi.restoreAllMocks(); vi.unstubAllGlobals(); } );

describe( 'ServiceRequestPurchase', () => {
  it( 'signed out: a sign-in link that returns here', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( null );
    stub( {} );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    const link = await screen.findByRole( 'link', { name: /Sign in on WhatsApp/ } );
    expect( link.getAttribute( 'href' ) ).toBe( '/account/sign-in/?return=%2Fsubmit-request%2F' );
  } );

  it( 'signed out: the CTA routes through the ONE serviceEntry gate, not a hand-built URL',
    async () => {
      vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
      vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( null );
      stub( {} );
      render( <ServiceRequestPurchase kind="VAULT" /> );
      fireEvent.click( await screen.findByRole( 'link', { name: /Sign in on WhatsApp/ } ) );
      // The gate decides, and it returns to THIS page rather than to /cart/.
      await waitFor( () => expect( pushed ).toEqual(
        [ '/account/sign-in/?return=%2Fvault%2F' ] ) );
      // And the pending action is stashed out of band, never on the query string.
      expect( JSON.parse( window.sessionStorage.getItem( 'wecare.pendingServiceAction' )! ) )
        .toEqual( {
          kind: 'vault', productId: 'df976a0a-f582-4535-b2e1-d532f348bd27',
          variantId: serviceByKind( 'VAULT' )!.variantId, label: 'Vault',
        } );
      expect( pushed[ 0 ] ).not.toContain( 'variantId' );
    } );

  it( 'signed out: offers no way in when the live price is unavailable', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( null );
    stub( {}, { status: 503, body: { error: 'SERVICE_PRICES_UNAVAILABLE' } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( 'This service may be temporarily unavailable.' ) )
      .toBeInTheDocument();
    expect( screen.queryByRole( 'link', { name: /Sign in on WhatsApp/ } ) ).toBeNull();
    expect( screen.queryByRole( 'button' ) ).toBeNull();
  } );

  it( 'submit: asks for an intent, sets the cart line, goes to /cart/', async () => {
    signedIn();
    stub( { '/services/request-intent': { status: 200, body: {
      intentId: INTENT, kind: 'SUBMIT_REQUEST', variantId: SUBMIT.variantId, amountPaise: 9900,
      currency: 'INR', targetRequestId: null } } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Continue to pay for Submit Request/ } ) );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    // Selected by route, not by position: `calls[0]` is the price GET now.
    expect( calls.find( c => c.url.includes( 'request-intent' ) )!.body )
      .toEqual( { kind: 'SUBMIT_REQUEST' } );
    expect( cart.readCart()[ 0 ].variantId ).toBe( SUBMIT.variantId );
    expect( cart.serviceIntentFor( cart.toLineItems() ) ).toBe( INTENT );
  } );

  it( 'amendment: requires a choice and sends targetRequestId', async () => {
    signedIn();
    stub( {
      '/services/my-requests': { status: 200, body: { requests: [
        { requestId: 'WD-REQ-7K2M9QXA', kind: 'SUBMIT_REQUEST', status: 'SUBMITTED',
          createdAt: 1, orderNumber: 'WD-ORD-ABCDEFGH', targetRequestId: null },
        { requestId: 'WD-REQ-AMENDED2', kind: 'REQUEST_AMENDMENT', status: 'SUBMITTED',
          createdAt: 2, orderNumber: 'WD-ORD-BBBBBBBB', targetRequestId: 'WD-REQ-7K2M9QXA' },
      ] } },
      '/services/request-intent': { status: 200, body: {
        intentId: INTENT, kind: 'REQUEST_AMENDMENT', variantId: AMEND.variantId,
        amountPaise: 9900, currency: 'INR', targetRequestId: 'WD-REQ-7K2M9QXA' } },
    } );
    render( <ServiceRequestPurchase kind="REQUEST_AMENDMENT" /> );
    const button = await screen.findByRole( 'button', { name: /Continue to pay for Request Amendment/ } );
    // Only SUBMIT_REQUEST rows are amendable.
    expect( screen.getAllByRole( 'radio' ) ).toHaveLength( 1 );
    fireEvent.click( button );
    expect( await screen.findByText( 'Choose the request this Request Amendment is for.' ) )
      .toBeInTheDocument();
    expect( calls.filter( c => c.url.includes( 'request-intent' ) ) ).toHaveLength( 0 );
    fireEvent.click( screen.getByRole( 'radio' ) );
    fireEvent.click( button );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    expect( calls.find( c => c.url.includes( 'request-intent' ) )!.body )
      .toEqual( { kind: 'REQUEST_AMENDMENT', targetRequestId: 'WD-REQ-7K2M9QXA' } );
  } );

  it.each( [ 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT' ] as const )(
    '%s with nothing to work on links to Submit Request', async kind => {
      signedIn();
      stub( { '/services/my-requests': { status: 200, body: { requests: [] } } } );
      render( <ServiceRequestPurchase kind={ kind } /> );
      const label = serviceByKind( kind )!.label;
      expect( await screen.findByText(
        new RegExp( `${ label } works on a request you have already submitted` ) ) )
        .toBeInTheDocument();
      expect( screen.getByRole( 'link', { name: 'Submit a request' } ).getAttribute( 'href' ) )
        .toBe( '/submit-request/' );
      expect( screen.queryByRole( 'button' ) ).toBeNull();
    } );

  it.each( [
    [ 'DROP_DOCS', 'Drop Docs' ],
    [ 'VAULT', 'Vault' ],
  ] as const )( '%s asks which request it is for and sends targetRequestId', async ( kind, label ) => {
    signedIn();
    const choice = serviceByKind( kind )!;
    stub( {
      '/services/my-requests': { status: 200, body: { requests: [
        { requestId: 'WD-REQ-7K2M9QXA', kind: 'SUBMIT_REQUEST', status: 'SUBMITTED',
          createdAt: 1, orderNumber: 'WD-ORD-ABCDEFGH', targetRequestId: null } ] } },
      '/services/request-intent': { status: 200, body: {
        // `null`: an intent is pre-payment and Wix prices the line at checkout.
        intentId: INTENT, kind, variantId: choice.variantId, amountPaise: null,
        currency: 'INR', targetRequestId: 'WD-REQ-7K2M9QXA' } },
    } );
    render( <ServiceRequestPurchase kind={ kind } /> );
    const button = await screen.findByRole( 'button',
      { name: new RegExp( `Continue to pay for ${ label }` ) } );
    expect( screen.getByText( `Which request is this ${ label } for?` ) ).toBeInTheDocument();
    fireEvent.click( button );
    expect( await screen.findByText( `Choose the request this ${ label } is for.` ) )
      .toBeInTheDocument();
    expect( calls.filter( c => c.url.includes( 'request-intent' ) ) ).toHaveLength( 0 );
    fireEvent.click( screen.getByRole( 'radio' ) );
    fireEvent.click( button );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    expect( calls.find( c => c.url.includes( 'request-intent' ) )!.body )
      .toEqual( { kind, targetRequestId: 'WD-REQ-7K2M9QXA' } );
    expect( cart.readCart()[ 0 ].variantId ).toBe( choice.variantId );
  } );

  it( 'a not-found target says so in one sentence and stays usable', async () => {
    signedIn();
    stub( {
      '/services/my-requests': { status: 200, body: { requests: [
        { requestId: 'WD-REQ-7K2M9QXA', kind: 'SUBMIT_REQUEST', status: 'SUBMITTED',
          createdAt: 1, orderNumber: '', targetRequestId: null } ] } },
      '/services/request-intent': { status: 404, body: { error: 'REQUEST_NOT_FOUND' } },
    } );
    render( <ServiceRequestPurchase kind="REQUEST_AMENDMENT" /> );
    fireEvent.click( await screen.findByRole( 'radio' ) );
    fireEvent.click( screen.getByRole( 'button', { name: /Continue to pay/ } ) );
    expect( await screen.findByText( 'We could not find that request on your account.' ) )
      .toBeInTheDocument();
    expect( screen.getByRole( 'button', { name: /Continue to pay/ } ) ).not.toBeDisabled();
    expect( navigatedTo ).toBe( '' );
  } );

  // ── the live price ─────────────────────────────────────────────────────────

  it.each( [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT' ] as const )(
    '%s renders ITS OWN slug price, not another page\'s', async kind => {
      signedIn();
      stub( { '/services/my-requests': { status: 200, body: { requests: [] } } } );
      render( <ServiceRequestPurchase kind={ kind } /> );
      expect( await screen.findByText( FACE[ kind ] ) ).toBeInTheDocument();
      // The other three faces must be absent from this card. This is the "each is a different
      // item" regression: with four distinct prices in one payload, a card reading the wrong
      // slug shows a figure that belongs to another page.
      for ( const [ other, face ] of Object.entries( FACE ) )
      {
        if ( other !== kind ) expect( screen.queryByText( face ) ).toBeNull();
      }
      // The endpoint is asked for once, with no input.
      const priceCalls = calls.filter( c => c.url.includes( '/ecommerce/service-prices' ) );
      expect( priceCalls ).toHaveLength( 1 );
      expect( priceCalls[ 0 ].url ).toBe( SERVICE_PRICES_URL );
      expect( priceCalls[ 0 ].body ).toEqual( {} );
    } );

  it( 'follows a price change with no other edit', async () => {
    signedIn();
    stub( {}, { status: 200, body: { currency: 'INR', prices: {
      ...LIVE.prices, 'submit-request': { available: true, paise: 99900 } } } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( '₹999' ) ).toBeInTheDocument();
    expect( screen.queryByText( '₹149' ) ).toBeNull();
  } );

  it( 'shows a neutral placeholder while loading, never a number', async () => {
    signedIn();
    stub( {} );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    // Synchronous first paint: the price call has not answered yet.
    expect( screen.getByText( '\u2014' ) ).toBeInTheDocument();
    expect( await screen.findByText( '₹149' ) ).toBeInTheDocument();
  } );

  it( 'shows the unavailable sentence and NO way to pay when the price call fails', async () => {
    signedIn();
    stub( { '/services/my-requests': { status: 200, body: { requests: [] } } },
      { status: 503, body: { error: 'SERVICE_PRICES_UNAVAILABLE' } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( 'This service may be temporarily unavailable.' ) )
      .toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: /Continue to pay/ } ) ).toBeNull();
    expect( screen.queryByRole( 'link', { name: /Sign in on WhatsApp/ } ) ).toBeNull();
    expect( calls.filter( c => c.url.includes( 'request-intent' ) ) ).toHaveLength( 0 );
  } );

  it( 'shows the unavailable state for a slug the server could not price', async () => {
    signedIn();
    stub( {}, { status: 200, body: { currency: 'INR', prices: {
      ...LIVE.prices, 'submit-request': { available: false } } } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( 'This service may be temporarily unavailable.' ) )
      .toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: /Continue to pay/ } ) ).toBeNull();
  } );

  it( 'keeps the convenience-fee wording, which is still truthful', async () => {
    signedIn();
    stub( {} );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( '₹149' ) ).toBeInTheDocument();
    expect( screen.getByText( /\+ a convenience fee, added at checkout/ ) )
      .toBeInTheDocument();
  } );

  it( 'puts WIXS figure on the cart row', async () => {
    signedIn();
    stub( { '/services/request-intent': { status: 200, body: {
      intentId: INTENT, kind: 'SUBMIT_REQUEST', variantId: SUBMIT.variantId, amountPaise: null,
      currency: 'INR', targetRequestId: null } } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Continue to pay/ } ) );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    expect( cart.readCart()[ 0 ].formattedPrice ).toBe( '₹149.00' );
  } );

  it( 'hardcodes no amount in the component source', () => {
    const source = fs.readFileSync(
      path.join( __dirname, '../components/ServiceRequestPurchase.tsx' ), 'utf8' );
    // The four live figures, in rupees and in paise, must not appear. `\b` on each so a GUID or a
    // token containing the digits does not read as a price.
    for ( const figure of [ '99', '350', '49', '9900', '35000', '4900' ] )
    {
      expect( source ).not.toMatch( new RegExp( `\\b${ figure }\\b` ) );
    }
  } );
} );
