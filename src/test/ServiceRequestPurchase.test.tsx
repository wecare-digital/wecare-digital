import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fs from 'fs';
import path from 'path';
import * as customerAuth from '../lib/customerAuth';
import * as cart from '../lib/cart';
import { SERVICE_CHOICES } from '../config/services';
import ServiceRequestPurchase from '../components/ServiceRequestPurchase';

/**
 * The Phase O-1 buy box. jsdom render only: the two service pages are public and statically
 * exported, but this box's signed-in states are client-only, so no browser rendering claim is made.
 */
const [ SUBMIT, AMEND ] = SERVICE_CHOICES;
const INTENT = '01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f';
let navigatedTo = '';
let calls: Array<{ url: string; body: Record<string, unknown> }> = [];

function stub ( routes: Record<string, { status: number; body: unknown }> ) {
  vi.stubGlobal( 'fetch', vi.fn( async ( url: string, init?: { body?: string } ) => {
    const body = JSON.parse( String( init?.body || '{}' ) );
    calls.push( { url: String( url ), body } );
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
  navigatedTo = '';
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
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    const link = await screen.findByRole( 'link', { name: /Sign in on WhatsApp/ } );
    expect( link.getAttribute( 'href' ) ).toBe( '/account/sign-in/?return=/submit-request/' );
  } );

  it( 'submit: asks for an intent, sets the cart line, goes to /cart/', async () => {
    signedIn();
    stub( { '/services/request-intent': { status: 200, body: {
      intentId: INTENT, kind: 'SUBMIT_REQUEST', variantId: SUBMIT.variantId, amountPaise: 9900,
      currency: 'INR', targetRequestId: null } } } );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Continue to pay for Submit Request/ } ) );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    expect( calls[ 0 ].body ).toEqual( { kind: 'SUBMIT_REQUEST' } );
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
    expect( await screen.findByText( 'Choose the request you want to amend.' ) ).toBeInTheDocument();
    expect( calls.filter( c => c.url.includes( 'request-intent' ) ) ).toHaveLength( 0 );
    fireEvent.click( screen.getByRole( 'radio' ) );
    fireEvent.click( button );
    await waitFor( () => expect( navigatedTo ).toBe( '/cart/' ) );
    expect( calls.find( c => c.url.includes( 'request-intent' ) )!.body )
      .toEqual( { kind: 'REQUEST_AMENDMENT', targetRequestId: 'WD-REQ-7K2M9QXA' } );
  } );

  it( 'amendment with nothing to amend links to Submit Request', async () => {
    signedIn();
    stub( { '/services/my-requests': { status: 200, body: { requests: [] } } } );
    render( <ServiceRequestPurchase kind="REQUEST_AMENDMENT" /> );
    expect( await screen.findByText( /You have no request to amend yet/ ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Submit a request' } ).getAttribute( 'href' ) )
      .toBe( '/submit-request/' );
    expect( screen.queryByRole( 'button' ) ).toBeNull();
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

  it( 'renders the price from config, and the component hardcodes no amount', async () => {
    signedIn();
    stub( {} );
    render( <ServiceRequestPurchase kind="SUBMIT_REQUEST" /> );
    expect( await screen.findByText( `₹${ SUBMIT.rupees }` ) ).toBeInTheDocument();
    const source = fs.readFileSync(
      path.join( __dirname, '../components/ServiceRequestPurchase.tsx' ), 'utf8' );
    expect( source ).not.toMatch( /\b99\b|9900/ );
  } );
} );
