import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import CheckoutSuccess from '../pages/checkout/success';
import * as auth from '../lib/customerAuth';

/**
 * THE HEADING IS NOW THE HERO'S FRAME, NOT THE WHOLE H1. This screen renders the shared
 * RotatingHero: the status (`heading`) is the fixed first line `.rh-head-line`, and a static lime
 * pill "your order" follows it. The h1's accessible name is therefore the frame plus the pill word
 * (twice - RotatingHero keeps an sr-only copy beside the visible pill), so
 * `getByRole('heading', { name })` no longer matches the bare status line. These helpers locate
 * the heading by its frame line - the SAME copy, from the element that carries it - so every
 * payment-safety assertion below is unchanged; only the lookup moved.
 */
function headingText (): string {
  return document.querySelector( '.rh-head-line' )?.textContent || '';
}
async function findHeading ( frame: string ): Promise<void> {
  await waitFor( () => expect( headingText() ).toBe( frame ) );
}

beforeEach( () => {
  window.history.replaceState( {}, '', '/checkout/success/?a=qa-attempt&o=WD-ORD-FORGED' );
  vi.spyOn( auth, 'getSession' ).mockReturnValue( { accessToken: 'qa-access', expiresAt: Date.now() + 60000 } );
} );
afterEach( () => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState( {}, '', '/' ); } );

it( 'does not accept an order number in the URL as payment evidence', async () => {
  window.history.replaceState( {}, '', '/checkout/success/?o=WD-ORD-FORGED' );
  const fetchMock = vi.fn(); vi.stubGlobal( 'fetch', fetchMock );
  render( <CheckoutSuccess /> );
  expect( headingText() ).toBe( 'Order confirmation unavailable' );
  expect( fetchMock ).not.toHaveBeenCalled();
  expect( screen.queryByText( 'WD-ORD-FORGED' ) ).toBeNull();
  expect( screen.queryByLabelText( 'Payment successful' ) ).toBeNull();
} );

it( 'shows only the paid order returned by the authenticated ownership check', async () => {
  const fetchMock = vi.fn().mockResolvedValue( { ok: true,
    json: async () => ( { attempt: { status: 'PAYMENT_PAID', orderNumber: 'WD-ORD-VERIFIED' } } ),
  } ); vi.stubGlobal( 'fetch', fetchMock );
  render( <CheckoutSuccess /> );
  await findHeading( 'Payment successful' );
  expect( screen.getByText( 'WD-ORD-VERIFIED' ) ).toBeTruthy();
  expect( screen.queryByText( 'WD-ORD-FORGED' ) ).toBeNull();
  expect( fetchMock.mock.calls[0][1].headers.Authorization ).toBe( 'Bearer qa-access' );
  expect( JSON.parse( fetchMock.mock.calls[0][1].body ) ).toEqual( { action: 'status', paymentAttemptId: 'qa-attempt' } );
} );

it.each( [
  { status: 'PAYMENT_PENDING', orderNumber: 'WD-ORD-UNPROVEN' },
  { status: 'PAYMENT_PAID' },
] )( 'does not show success before a paid order exists: %j', async attempt => {
  vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: true, json: async () => ( { attempt } ) } ) );
  render( <CheckoutSuccess /> );
  await findHeading( 'Order confirmation unavailable' );
  expect( screen.queryByText( 'Payment successful' ) ).toBeNull();
} );

it( 'does not show success for a rejected ownership check', async () => {
  vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 401 } ) );
  render( <CheckoutSuccess /> );
  await findHeading( 'Order confirmation unavailable' );
} );
