import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import RequestsPanel from '../components/orders/RequestsPanel';

/**
 * "Your requests" on /orders (Phase O-1). jsdom render only. /orders is auth-gated client-side,
 * so its static export ships the signed-out shell and no browser rendering claim is made here.
 * The panel's placement inside the profile aside is pinned in OrdersPage.test.tsx's h2 ladder and
 * below by rendering the page itself.
 */
const ROW = { requestId: 'WD-REQ-7K2M9QXA', kind: 'SUBMIT_REQUEST', status: 'SUBMITTED',
  createdAt: 1_759_000_000, orderNumber: 'WD-ORD-ABCDEFGH', targetRequestId: null };
const AMENDMENT = { requestId: 'WD-REQ-AMENDED2', kind: 'REQUEST_AMENDMENT', status: 'SUBMITTED',
  createdAt: 1_759_100_000, orderNumber: 'WD-ORD-BBBBBBBB', targetRequestId: 'WD-REQ-7K2M9QXA' };

let fetchMock: ReturnType<typeof vi.fn>;
let writeText: ReturnType<typeof vi.fn>;

function answer ( status: number, body: unknown ) {
  return { ok: status < 400, status, json: async () => body };
}

beforeEach( () => {
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
  writeText = vi.fn().mockResolvedValue( undefined );
  Object.defineProperty( navigator, 'clipboard', { value: { writeText }, configurable: true } );
  Object.defineProperty( window, 'isSecureContext', { value: true, configurable: true } );
} );
afterEach( () => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); } );

describe( 'RequestsPanel', () => {
  it( 'sends the paid reference ids and lists the requests with order and amendment links', async () => {
    fetchMock.mockResolvedValueOnce( answer( 200, { requests: [ AMENDMENT, ROW ] } ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [ 'WD-PAY-A', 'WD-PAY-B' ] }
      onExpired={ () => undefined } /> );
    expect( await screen.findByText( 'WD-REQ-AMENDED2' ) ).toBeInTheDocument();
    const [ url, init ] = fetchMock.mock.calls[ 0 ];
    expect( String( url ) ).toContain( '/services/my-requests' );
    expect( JSON.parse( init.body ) ).toEqual( { referenceIds: [ 'WD-PAY-A', 'WD-PAY-B' ] } );
    expect( init.headers.Authorization ).toBe( 'Bearer tok' );
    expect( screen.getByRole( 'heading', { level: 2, name: 'Your requests' } ) ).toBeInTheDocument();
    expect( screen.getByText( 'WD-ORD-ABCDEFGH' ) ).toBeInTheDocument();
    expect( screen.getAllByText( 'WD-REQ-7K2M9QXA' ) ).toHaveLength( 2 );     // its own + "Amends"
    expect( screen.getByText( /Amends/ ) ).toBeInTheDocument();
  } );

  it( 'copies the public id from state, reads Copied, then reverts', async () => {
    vi.useFakeTimers( { shouldAdvanceTime: true } );
    fetchMock.mockResolvedValueOnce( answer( 200, { requests: [ ROW ] } ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] } onExpired={ () => undefined } /> );
    const button = await screen.findByRole( 'button', { name: 'Copy request ID WD-REQ-7K2M9QXA' } );
    expect( button.textContent ).toBe( 'Copy' );
    expect( screen.getByText( 'Copy request ID' ) ).toBeInTheDocument();
    await act( async () => { fireEvent.click( button ); } );
    expect( writeText ).toHaveBeenCalledWith( 'WD-REQ-7K2M9QXA' );
    expect( screen.getByText( 'Copied' ) ).toBeInTheDocument();
    await act( async () => { vi.advanceTimersByTime( 2100 ); } );
    expect( screen.getByText( 'Copy request ID' ) ).toBeInTheDocument();
  } );

  it( 'a refused clipboard says press your copy key', async () => {
    writeText.mockRejectedValueOnce( new Error( 'denied' ) );
    fetchMock.mockResolvedValueOnce( answer( 200, { requests: [ ROW ] } ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] } onExpired={ () => undefined } /> );
    fireEvent.click( await screen.findByRole( 'button', { name: /Copy request ID/ } ) );
    expect( await screen.findByText( 'Press your copy key' ) ).toBeInTheDocument();
  } );

  it( 'shows no copy control outside a secure context', async () => {
    Object.defineProperty( window, 'isSecureContext', { value: false, configurable: true } );
    fetchMock.mockResolvedValueOnce( answer( 200, { requests: [ ROW ] } ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] } onExpired={ () => undefined } /> );
    await screen.findByText( 'WD-REQ-7K2M9QXA' );
    expect( screen.queryByRole( 'button' ) ).toBeNull();
  } );

  it( 'empty: links to both service pages', async () => {
    fetchMock.mockResolvedValueOnce( answer( 200, { requests: [] } ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] } onExpired={ () => undefined } /> );
    expect( await screen.findByText( /No requests yet/ ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Submit a request' } ).getAttribute( 'href' ) )
      .toBe( '/submit-request/' );
    expect( screen.getByRole( 'link', { name: 'request an amendment' } ).getAttribute( 'href' ) )
      .toBe( '/request-amendment/' );
  } );

  it( 'failure is quiet; 401 calls onExpired', async () => {
    fetchMock.mockResolvedValueOnce( answer( 503, {} ) );
    const { unmount } = render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] }
      onExpired={ () => undefined } /> );
    expect( await screen.findByText( 'Requests are unavailable right now.' ) ).toBeInTheDocument();
    unmount();
    const onExpired = vi.fn();
    fetchMock.mockResolvedValueOnce( answer( 401, {} ) );
    render( <RequestsPanel accessToken="tok" paidReferenceIds={ [] } onExpired={ onExpired } /> );
    await waitFor( () => expect( onExpired ).toHaveBeenCalledTimes( 1 ) );
  } );
} );

describe( '/orders places the panel inside the profile aside, after the identity card', () => {
  it( 'renders the real page with the real panel', async () => {
    const customerAuth = await import( '../lib/customerAuth' );
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( {
      accessToken: 'tok', expiresAt: Date.now() + 3_600_000 } );
    const profile = { name: 'Asha Sen', firstName: 'Asha', lastName: 'Sen', email: 'a@example.com',
      emailVerified: true, phone: '+919330994400', addressComplete: false, address: null };
    fetchMock.mockImplementation( async ( url: string ) => ( String( url ).includes( 'my-requests' )
      ? answer( 200, { requests: [ ROW ] } )
      : answer( 200, { orders: [ { orderNumber: 'WD-ORD-ABCDEFGH', referenceId: 'WD-PAY-PAID',
        createdAt: 1, amountPaise: 10193, currency: 'INR', currencyUnexpected: false,
        status: 'captured', statusRank: 3 } ], profile } ) ) );
    const { default: OrdersPage } = await import( '../pages/orders' );
    const { container } = render( <OrdersPage /> );
    await screen.findByText( 'WD-REQ-7K2M9QXA' );
    const aside = container.querySelector( 'aside.ord-panel' )!;
    const headings = Array.from( aside.querySelectorAll( 'h2' ) ).map( h => h.textContent );
    expect( headings ).toEqual( [ 'What we have on file', 'Your requests' ] );
    const requestsCall = fetchMock.mock.calls.find( c => String( c[ 0 ] ).includes( 'my-requests' ) )!;
    expect( JSON.parse( requestsCall[ 1 ].body ) ).toEqual( { referenceIds: [ 'WD-PAY-PAID' ] } );
    expect( container.querySelector( 'table.ord-table' ) ).not.toBeNull();
  } );
} );
