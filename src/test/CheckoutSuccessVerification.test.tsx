import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import CheckoutSuccess from '../pages/checkout/success';
import * as auth from '../lib/customerAuth';

beforeEach( () => {
  window.history.replaceState( {}, '', '/checkout/success/?a=qa-attempt&o=WD-ORD-FORGED' );
  vi.spyOn( auth, 'getSession' ).mockReturnValue( { accessToken: 'qa-access', expiresAt: Date.now() + 60000 } );
} );
afterEach( () => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState( {}, '', '/' ); } );

it( 'does not accept an order number in the URL as payment evidence', async () => {
  window.history.replaceState( {}, '', '/checkout/success/?o=WD-ORD-FORGED' );
  const fetchMock = vi.fn(); vi.stubGlobal( 'fetch', fetchMock );
  render( <CheckoutSuccess /> );
  // The shared RotatingHero's h1 is the dynamic heading (its frame) followed by a static pill
  // word, so the accessible name opens with the heading rather than equalling it. Match the
  // heading prefix; every payment-safety assertion below is unchanged.
  expect( screen.getByRole( 'heading', { name: /^Order confirmation unavailable/ } ) ).toBeTruthy();
  expect( fetchMock ).not.toHaveBeenCalled();
  expect( screen.queryByText( 'WD-ORD-FORGED' ) ).toBeNull();
  expect( screen.queryByLabelText( 'Payment successful' ) ).toBeNull();
} );

it( 'shows only the paid order returned by the authenticated ownership check', async () => {
  const fetchMock = vi.fn().mockResolvedValue( { ok: true,
    json: async () => ( { attempt: { status: 'PAYMENT_PAID', orderNumber: 'WD-ORD-VERIFIED' } } ),
  } ); vi.stubGlobal( 'fetch', fetchMock );
  render( <CheckoutSuccess /> );
  // Heading prefix: the h1 is the "Payment successful" frame plus the static pill word.
  expect( await screen.findByRole( 'heading', { name: /^Payment successful/ } ) ).toBeTruthy();
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
  await waitFor( () => expect( screen.getByRole( 'heading', { name: /^Order confirmation unavailable/ } ) ).toBeTruthy() );
  expect( screen.queryByText( 'Payment successful' ) ).toBeNull();
} );

it( 'does not show success for a rejected ownership check', async () => {
  vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 401 } ) );
  render( <CheckoutSuccess /> );
  expect( await screen.findByRole( 'heading', { name: /^Order confirmation unavailable/ } ) ).toBeTruthy();
} );
