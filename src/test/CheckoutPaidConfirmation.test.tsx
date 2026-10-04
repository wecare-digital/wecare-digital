/**
 * A captured payment must be confirmed on screen, even while the Wix writeback is pending.
 *
 * The defect this pins
 * --------------------
 * A real payment was captured and the internal order recorded — WD-ORD-7ZTSG8X7, paymentStatus
 * PAYMENT_PAID — and the customer was never told. Two things combined:
 *
 * 1. `_status` read the order number only inside the `_finalize_from_claim` arm, which runs only
 *    while `finalizationStage` is unset. The webhook had already finalized this attempt, so the
 *    endpoint returned `orderNumber: null` for an order that definitely existed.
 * 2. With no order number, /checkout/status rendered its "we are creating your order now" screen,
 *    and the redirect to /checkout/success it depended on could therefore never fire.
 *
 * So the screen was permanently stuck one step short of a confirmation, carrying no order number
 * and no amount, for a payment that had completed. Nothing on the page was wrong exactly — it was
 * simply never finished, which is the harder failure to notice.
 *
 * What is asserted, and why in this order
 * ---------------------------------------
 * The money is the first assertion, because the one unrecoverable error on this screen is telling
 * someone who paid that something went wrong. Then the two facts they need to act on — the order
 * number they would quote to us, and the amount actually captured. Then the absence of the
 * internal vocabulary: NEEDS_RECONCILIATION and WIX_WRITE_CONTRACT_REQUIRED describe our
 * bookkeeping against the store, and a customer reading either on a confirmation screen learns
 * only that something might be wrong.
 *
 * The honest states are re-asserted here too. A fix that turned an unknown or failed attempt into
 * a confirmation would pass every assertion about the paid state and be far worse than the defect.
 */

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

import CheckoutStatus, { viewFor } from '../pages/checkout/status';
import { amountLabel, rupeesFromPaise } from '../lib/paymentVocabulary';
import * as auth from '../lib/customerAuth';

/** The live shape: captured, order committed, Wix writeback still gated off. */
const PAID_UNRECONCILED = {
  status: 'PAYMENT_PAID',
  orderNumber: 'WD-ORD-7ZTSG8X7',
  amountPaise: 59900,
  currency: 'INR',
  canRetry: false,
};

function respondWith ( attempt: unknown ): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue( {
    ok: true,
    json: async () => ( { attempt } ),
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

beforeEach( () => {
  window.history.replaceState( {}, '', '/checkout/status/?a=qa-attempt' );
  vi.spyOn( auth, 'getSession' ).mockReturnValue(
    { accessToken: 'qa-access', expiresAt: Date.now() + 60000 } );
} );

afterEach( () => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState( {}, '', '/' );
} );

describe( 'a captured payment awaiting the Wix writeback', () => {
  it( 'confirms the payment rather than claiming anything failed', async () => {
    respondWith( PAID_UNRECONCILED );
    render( <CheckoutStatus /> );

    expect( await screen.findByRole( 'heading', { name: 'Payment received' } ) ).toBeTruthy();
    // Nothing on the page may read as a failure or as doubt about the money.
    expect( screen.queryByText( /wasn't completed/i ) ).toBeNull();
    expect( screen.queryByText( /Nothing to show here/i ) ).toBeNull();
    expect( screen.queryByText( /no order was created/i ) ).toBeNull();
    // No action that would start a second payment for a basket already paid for.
    expect( screen.queryByRole( 'link', { name: 'Start again' } ) ).toBeNull();
  } );

  it( 'shows the order number and the amount captured', async () => {
    respondWith( PAID_UNRECONCILED );
    render( <CheckoutStatus /> );

    expect( await screen.findByText( 'WD-ORD-7ZTSG8X7' ) ).toBeTruthy();
    expect( screen.getByText( 'Order number' ) ).toBeTruthy();
    // ₹599.00 from 59900 integer paise. Rendered by integer division and a modulo, never by
    // dividing and calling toFixed: a one-paise drift between the charge and the confirmation is
    // the kind of error nobody can be talked out of.
    expect( screen.getByText( '\u20b9599.00' ) ).toBeTruthy();
    expect( screen.getByText( 'Amount paid' ) ).toBeTruthy();
  } );

  it( 'never shows the reconciliation stage to the customer', async () => {
    respondWith( {
      ...PAID_UNRECONCILED,
      // Even if the endpoint one day leaked these, the screen must not print them. It does not
      // read them at all, which is the structural version of this assertion.
      finalizationStage: 'NEEDS_RECONCILIATION',
      finalizationReason: 'WIX_WRITE_CONTRACT_REQUIRED',
    } );
    render( <CheckoutStatus /> );

    await screen.findByText( 'WD-ORD-7ZTSG8X7' );
    expect( document.body.textContent ).not.toContain( 'NEEDS_RECONCILIATION' );
    expect( document.body.textContent ).not.toContain( 'WIX_WRITE_CONTRACT_REQUIRED' );
    expect( document.body.textContent ).not.toContain( 'reconcil' );
    expect( document.body.textContent ).not.toContain( 'Wix' );
  } );

  it( 'stops asking once the payment is confirmed', async () => {
    const fetchMock = respondWith( PAID_UNRECONCILED );
    render( <CheckoutStatus /> );
    await screen.findByText( 'WD-ORD-7ZTSG8X7' );
    // A settled outcome is not going to change from here. One read, then the screen rests.
    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 1 ) );
    expect( JSON.parse( fetchMock.mock.calls[ 0 ][ 1 ].body ) )
      .toEqual( { action: 'status', paymentAttemptId: 'qa-attempt' } );
    expect( fetchMock.mock.calls[ 0 ][ 1 ].headers.Authorization ).toBe( 'Bearer qa-access' );
  } );
} );

describe( 'the states that are not a confirmation', () => {
  it( 'still says the order is being created when paid with no order number yet', async () => {
    respondWith( { status: 'PAYMENT_PAID', amountPaise: 59900, currency: 'INR' } );
    render( <CheckoutStatus /> );
    // "Payment received" is correct — the money arrived — but there is no order number to show
    // and "do not pay again" is the sentence that prevents a second charge.
    expect( await screen.findByRole( 'heading', { name: 'Payment received' } ) ).toBeTruthy();
    expect( screen.getByText( /Do not pay again/ ) ).toBeTruthy();
    expect( screen.queryByText( 'Order number' ) ).toBeNull();
  } );

  it( 'does not treat an order number alone as payment evidence', async () => {
    // A pending attempt with a number on it. The backend strips this, and the page would refuse
    // it anyway: the state decides, not the presence of an identifier.
    respondWith( { status: 'PAYMENT_PENDING', orderNumber: 'WD-ORD-7ZTSG8X7', amountPaise: 59900 } );
    render( <CheckoutStatus /> );
    await waitFor( () => expect(
      screen.getByRole( 'heading', { name: 'Confirming your payment' } ) ).toBeTruthy() );
    expect( screen.queryByText( 'WD-ORD-7ZTSG8X7' ) ).toBeNull();
  } );

  it( 'keeps the honest failure screen for a definite failure', async () => {
    respondWith( { status: 'PAYMENT_FAILED', canRetry: true } );
    render( <CheckoutStatus /> );
    expect( await screen.findByRole( 'heading', { name: "Payment wasn't completed" } ) ).toBeTruthy();
    expect( screen.getByRole( 'link', { name: 'Start again' } ) ).toBeTruthy();
    expect( screen.queryByText( 'Payment received' ) ).toBeNull();
  } );

  it( 'keeps the neutral screen for an unknown state, and claims nothing either way', async () => {
    respondWith( { status: 'PAYMENT_INITIATION_DISABLED' } );
    render( <CheckoutStatus /> );
    expect( await screen.findByRole( 'heading', { name: 'Nothing to show here' } ) ).toBeTruthy();
    // It must not claim success, and it must not claim no charge was made: the browser cannot
    // know, and "no charge" is the reassurance that cannot be taken back.
    expect( document.body.textContent ).not.toContain( 'Payment received' );
    expect( document.body.textContent ).not.toMatch( /no charge/i );
  } );
} );

describe( 'the view mapping and the money helper', () => {
  it( 'routes a paid attempt with a server order number to the confirmation', () => {
    expect( viewFor( 'PAYMENT_PAID', 'WD-ORD-7ZTSG8X7' ) ).toBe( 'paid' );
    expect( viewFor( 'PAYMENT_PAID', null ) ).toBe( 'finalizing' );
    // Not a server order number shape, so not a confirmation.
    expect( viewFor( 'PAYMENT_PAID', 'wd-ord' ) ).toBe( 'finalizing' );
    expect( viewFor( 'PAYMENT_FAILED', null ) ).toBe( 'failed' );
    expect( viewFor( 'PAYMENT_PENDING', 'WD-ORD-7ZTSG8X7' ) ).toBe( 'confirming' );
    expect( viewFor( 'SOMETHING_NEW', 'WD-ORD-7ZTSG8X7' ) ).toBe( 'unavailable' );
  } );

  it( 'renders paise as rupees without floating-point arithmetic', () => {
    // 1, 10 and 99 paise are where a divide-and-toFixed implementation loses or gains a paise.
    expect( rupeesFromPaise( 1 ) ).toBe( '0.01' );
    expect( rupeesFromPaise( 10 ) ).toBe( '0.10' );
    expect( rupeesFromPaise( 99 ) ).toBe( '0.99' );
    expect( rupeesFromPaise( 100 ) ).toBe( '1.00' );
    expect( rupeesFromPaise( 59900 ) ).toBe( '599.00' );
    expect( rupeesFromPaise( 12345678 ) ).toBe( '1,23,456.78' );
    // Nothing usable renders nothing, rather than a zero the screen cannot stand behind.
    expect( rupeesFromPaise( 59.9 ) ).toBe( '' );
    expect( rupeesFromPaise( '59900' ) ).toBe( '' );
    expect( rupeesFromPaise( -1 ) ).toBe( '' );
    expect( rupeesFromPaise( null ) ).toBe( '' );
  } );

  it( 'compares the currency explicitly and never infers it from the amount', () => {
    expect( amountLabel( 59900, 'INR' ) ).toBe( '\u20b9599.00' );
    expect( amountLabel( 59900, undefined ) ).toBe( '\u20b9599.00' );
    expect( amountLabel( 59900, 'USD' ) ).toBe( '' );
    expect( amountLabel( undefined, 'INR' ) ).toBe( '' );
  } );
} );
