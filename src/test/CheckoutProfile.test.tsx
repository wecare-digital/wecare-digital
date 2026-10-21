import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CheckoutProfile, { CheckoutProfileMode } from '../components/CheckoutProfile';

const ADDRESS = { addressLine1: '12 Test Road', addressLine2: 'Flat 2', locality: 'Indiranagar', city: 'Bengaluru', state: 'Karnataka', postalCode: '560001', country: 'India', countryCode: 'IN', fullAddress: '12 Test Road, Flat 2, Indiranagar, Bengaluru' };
const INITIAL = { firstName: 'Asha', lastName: 'Sen', companyName: 'WECARE QA', designation: 'Tester', email: 'asha@example.com', address: ADDRESS };
const REPLY = { status: 'PROFILE_READY', contactId: 'contact-1', name: 'Asha Sen', ...INITIAL, phone: '+918100640044', emailVerified: false, addressComplete: true };
afterEach( () => { vi.unstubAllGlobals(); vi.restoreAllMocks(); } );

function setup ( mode: CheckoutProfileMode = 'create', reply = REPLY ) {
  const fetchMock = vi.fn().mockResolvedValue( { ok: true, json: async () => reply } );
  vi.stubGlobal( 'fetch', fetchMock );
  const onReady = vi.fn();
  render( <CheckoutProfile accessToken="qa-session" mode={ mode } initial={ INITIAL } onReady={ onReady } /> );
  return { fetchMock, onReady };
}

describe( 'WhatsApp-owned customer profile', () => {
  it.each( [ 'create', 'name', 'address', 'email' ] as CheckoutProfileMode[] )( '%s has no email OTP controls', mode => {
    const { fetchMock } = setup( mode );
    expect( screen.getByText( '✓ WhatsApp verified by sign-in' ) ).toBeInTheDocument();
    expect( screen.queryByRole( 'button', { name: /code|verify|resend/i } ) ).toBeNull();
    expect( screen.queryByLabelText( /verification code/i ) ).toBeNull();
    expect( fetchMock ).not.toHaveBeenCalled();
  } );

  it.each( [
    [ 'create', { firstName: 'Asha', lastName: 'Sen', companyName: 'WECARE QA', designation: 'Tester', email: 'asha@example.com', address: { addressLine1: '12 Test Road', addressLine2: 'Flat 2', locality: 'Indiranagar', city: 'Bengaluru', state: 'Karnataka', postalCode: '560001' } } ],
    [ 'name', { firstName: 'Asha', lastName: 'Sen', companyName: 'WECARE QA', designation: 'Tester' } ],
    [ 'email', { email: 'asha@example.com' } ],
    [ 'address', { address: { addressLine1: '12 Test Road', addressLine2: 'Flat 2', locality: 'Indiranagar', city: 'Bengaluru', state: 'Karnataka', postalCode: '560001' } } ],
  ] as const )( '%s saves only its editable fields using the WhatsApp session', async ( mode, expected ) => {
    const { fetchMock, onReady } = setup( mode );
    fireEvent.click( screen.getByRole( 'button', { name: /Save/ } ) );
    await waitFor( () => expect( onReady ).toHaveBeenCalledTimes( 1 ) );
    expect( fetchMock ).toHaveBeenCalledTimes( 1 );
    const [ url, request ] = fetchMock.mock.calls[ 0 ];
    expect( url ).toContain( '/customer/profile' );
    expect( request.headers.Authorization ).toBe( 'Bearer qa-session' );
    expect( JSON.parse( request.body ) ).toEqual( expected );
    expect( request.body ).not.toMatch( /emailProof|phone|optIn|allowlist|tags/ );
    expect( onReady.mock.calls[ 0 ][ 0 ].emailVerified ).toBe( false );
  } );

  it( 'changes contact email without making an OTP request', async () => {
    const { fetchMock, onReady } = setup( 'email' );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'new@example.com' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
    await waitFor( () => expect( onReady ).toHaveBeenCalled() );
    expect( JSON.parse( fetchMock.mock.calls[ 0 ][ 1 ].body ) ).toEqual( { email: 'new@example.com' } );
  } );

  it( 'still validates the email format', () => {
    setup( 'email' );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'invalid' } } );
    expect( screen.getByRole( 'button', { name: 'Save changes' } ) ).toBeDisabled();
  } );

  it( 'leaves the editor available after a network failure', async () => {
    const { fetchMock } = setup( 'name' ); fetchMock.mockRejectedValueOnce( new Error( 'offline' ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
    await screen.findByText( 'We could not reach the server. Please try again.' );
    expect( screen.getByRole( 'button', { name: 'Save changes' } ) ).toBeEnabled();
  } );
} );
