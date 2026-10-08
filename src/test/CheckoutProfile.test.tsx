import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CheckoutProfile from '../components/CheckoutProfile';

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'CheckoutProfile', () => {
  it( 'treats WhatsApp as already verified by sign-in', () => {
    render( <CheckoutProfile accessToken="fixture-session" onReady={ vi.fn() } /> );
    expect( screen.getByText( '✓ WhatsApp verified by sign-in' ) ).toBeInTheDocument();
    expect( screen.getByLabelText( 'First name' ) ).toBeInTheDocument();
    expect( screen.getByLabelText( 'Last name' ) ).toBeInTheDocument();
    expect( screen.getByLabelText( 'Email' ) ).toBeInTheDocument();
    expect( screen.queryByLabelText( /WhatsApp number/i ) ).toBeNull();
  } );

  /*
   * CORRECTED FOR FEAT-001's ADDRESS_REQUIRED RULE, and the rename is part of the correction.
   *
   * This case used to be called "saves only the narrow profile body" and saved with no address at
   * all. That is no longer a body the server accepts: creating a contact row now REQUIRES an
   * address, and `auth/customer-profile/handler.py:422` answers
   * `400 INVALID_ADDRESS / code:"ADDRESS_REQUIRED"` without one. So the old assertion pinned a
   * request that is guaranteed to fail for every first-time customer - the exact dead end this
   * phase exists to remove - rather than pinning a narrow body.
   *
   * What it pins now: Save stays DISABLED until the address is complete, and the create-mode body
   * is the five fields and nothing more. The "narrow" half of the original intent is kept by the
   * `toEqual` and by the phone/tags/optIn/allowlist assertion below, which are what actually
   * guarded against the form posting marketing state.
   *
   * The other three cases in this file are untouched. They pass neither `mode` nor `initial` and
   * so remain the regression guard on the 'create' default.
   */
  it( 'verifies email, holds Save until the address is complete, then saves the create body', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce( { ok: true, json: async () => ( { status: 'sent' } ) } )
      .mockResolvedValueOnce( {
        ok: true,
        json: async () => ( { status: 'VERIFIED', proof: 'fixture-proof' } ),
      } )
      .mockResolvedValueOnce( {
        ok: true,
        json: async () => ( {
          status: 'PROFILE_READY',
          contactId: 'contact-1',
          name: 'Asha Sen',
          email: 'asha@example.com',
          phone: '+919330994400',
        } ),
      } );
    vi.stubGlobal( 'fetch', fetchMock );
    const onReady = vi.fn();

    render( <CheckoutProfile accessToken="fixture-session" onReady={ onReady } /> );
    fireEvent.change( screen.getByLabelText( 'First name' ), { target: { value: 'Asha' } } );
    fireEvent.change( screen.getByLabelText( 'Last name' ), { target: { value: 'Sen' } } );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'asha@example.com' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send verification code by email' } ) );

    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 1 ) );
    expect( String( fetchMock.mock.calls[ 0 ][ 0 ] ) ).toContain( '/auth/email-verification' );

    fireEvent.change( await screen.findByLabelText( 'Email verification code' ), {
      target: { value: '123456' },
    } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Confirm email code' } ) );
    await screen.findByText( '✓ Email verified' );

    // A verified email is not enough on creation: the row cannot be written without an address.
    expect( screen.getByRole( 'button', { name: /Save & continue/ } ) ).toBeDisabled();

    fireEvent.change( screen.getByLabelText( 'Address line 1' ), { target: { value: '12 MG Road' } } );
    fireEvent.change( screen.getByLabelText( 'City' ), { target: { value: 'Bengaluru' } } );
    // The state field is our own combobox since batch 2f, so this is open-then-click rather
    // than fireEvent.change, which does nothing to a button. The SAME user action and the same
    // emitted value - every assertion about the saved body below is untouched.
    fireEvent.click( screen.getByRole( 'combobox', { name: 'State' } ) );
    fireEvent.click( screen.getByRole( 'option', { name: 'Karnataka' } ) );
    fireEvent.change( screen.getByLabelText( 'PIN code' ), { target: { value: '560001' } } );
    expect( screen.getByRole( 'button', { name: /Save & continue/ } ) ).toBeEnabled();

    fireEvent.click( screen.getByRole( 'button', { name: /Save & continue/ } ) );
    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 3 ) );

    const [ url, init ] = fetchMock.mock.calls[ 2 ];
    expect( String( url ) ).toContain( '/customer/profile' );
    const body = JSON.parse( init.body );
    expect( body ).toEqual( {
      firstName: 'Asha',
      lastName: 'Sen',
      email: 'asha@example.com',
      emailProof: 'fixture-proof',
      address: {
        addressLine1: '12 MG Road',
        addressLine2: '',
        city: 'Bengaluru',
        state: 'Karnataka',
        postalCode: '560001',
      },
    } );
    expect( init.body ).not.toMatch( /phone|tags|optIn|allowlist/ );
    expect( onReady ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'changing email invalidates a completed verification', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce( { ok: true, json: async () => ( { status: 'sent' } ) } )
      .mockResolvedValueOnce( {
        ok: true,
        json: async () => ( { status: 'VERIFIED', proof: 'fixture-proof' } ),
      } );
    vi.stubGlobal( 'fetch', fetchMock );

    render( <CheckoutProfile accessToken="fixture-session" onReady={ vi.fn() } /> );
    fireEvent.change( screen.getByLabelText( 'First name' ), { target: { value: 'Asha' } } );
    fireEvent.change( screen.getByLabelText( 'Last name' ), { target: { value: 'Sen' } } );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'asha@example.com' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send verification code by email' } ) );
    fireEvent.change( await screen.findByLabelText( 'Email verification code' ), {
      target: { value: '123456' },
    } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Confirm email code' } ) );
    await screen.findByText( '✓ Email verified' );

    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'new@example.com' } } );
    expect( screen.queryByText( '✓ Email verified' ) ).toBeNull();
    expect( screen.getByRole( 'button', { name: /Save & continue/ } ) ).toBeDisabled();
  } );

  it( 'does not treat purchase identity as marketing consent', () => {
    render( <CheckoutProfile accessToken="fixture-session" onReady={ vi.fn() } /> );
    expect( screen.getByText( /does not automatically opt you into marketing/i ) ).toBeInTheDocument();
  } );
} );
