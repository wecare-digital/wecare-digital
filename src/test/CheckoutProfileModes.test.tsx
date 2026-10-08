import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CheckoutProfile from '../components/CheckoutProfile';
import type { StoredAddress } from '../components/AddressFields';

/**
 * THE FOUR MODES, AND THE TWO THINGS THAT GO WRONG IF THE SAVE PREDICATE IS SHARED.
 *
 * The component used to gate Save on `namesValid && proof`, which is correct for creation and
 * wrong for every edit: in `address` and `name` mode no email code is ever collected, so a single
 * shared predicate leaves Save PERMANENTLY DISABLED - a returning customer who opens the address
 * editor can never close it. That is the first thing these tests pin, and it is a dead end rather
 * than a cosmetic bug.
 *
 * The second is the posted body. The backend refuses an `emailProof` that arrives without an
 * `email` with a 400, on the grounds that a proof is a claim about a specific address, so binding
 * it to whatever is stored would let a proof minted for one address verify another. A mode that
 * posted a stale proof alongside no email would therefore fail every save, so the assertions here
 * are on the PARSED REQUEST BODY rather than on what the component looks like.
 */

const ADDRESS: StoredAddress = {
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

const INITIAL = {
  firstName: 'Asha',
  lastName: 'Sen',
  email: 'asha@example.com',
  address: ADDRESS,
};

const PROFILE_REPLY = {
  status: 'PROFILE_READY',
  contactId: 'contact-1',
  name: 'Asha Sen',
  firstName: 'Asha',
  lastName: 'Sen',
  email: 'asha@example.com',
  phone: '+918100640044',
  addressComplete: true,
  address: ADDRESS,
};

/**
 * Dispatches on the request URL plus the parsed `action`, rather than on call ORDER. Order-based
 * stubbing breaks the moment a mode issues one fewer request than another - which is the whole
 * point of the modes.
 */
function stubFetch ( replies: { request?: any; verify?: any; profile?: any } = {} ) {
  const fetchMock = vi.fn( async ( url: any, init: any ) => {
    const target = String( url );
    const body = init && init.body ? JSON.parse( init.body ) : {};
    if ( target.includes( '/auth/email-verification' ) ) {
      return body.action === 'verify'
        ? { ok: true, json: async () => replies.verify || { status: 'VERIFIED', proof: 'fixture-proof' } }
        : { ok: true, json: async () => replies.request || { status: 'sent' } };
    }
    if ( target.includes( '/customer/profile' ) ) {
      return { ok: true, json: async () => replies.profile || PROFILE_REPLY };
    }
    throw new Error( `unstubbed request to ${ target }` );
  } );
  vi.stubGlobal( 'fetch', fetchMock );
  return fetchMock;
}

const profileBodies = ( fetchMock: ReturnType<typeof stubFetch> ) => fetchMock.mock.calls
  .filter( call => String( call[ 0 ] ).includes( '/customer/profile' ) )
  .map( call => JSON.parse( ( call[ 1 ] as any ).body ) );

const saveButton = () => screen.getByRole( 'button', { name: /Save & continue/ } );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'CheckoutProfile address mode', () => {
  it( 'enables Save with no email proof anywhere in sight', () => {
    stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="address" initial={ INITIAL } onReady={ vi.fn() } /> );
    expect( saveButton() ).toBeEnabled();
    // No OTP surface at all: there is nothing to verify when only the address is changing.
    expect( screen.queryByLabelText( 'Email' ) ).toBeNull();
    expect( screen.queryByRole( 'button', { name: 'Send verification code by email' } ) ).toBeNull();
    expect( screen.queryByLabelText( 'Email verification code' ) ).toBeNull();
  } );

  it( 'disables Save until the address itself is complete', () => {
    stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="address"
      initial={ { ...INITIAL, address: null } } onReady={ vi.fn() } /> );
    expect( saveButton() ).toBeDisabled();

    fireEvent.change( screen.getByLabelText( 'Address line 1' ), { target: { value: '12 MG Road' } } );
    fireEvent.change( screen.getByLabelText( 'City' ), { target: { value: 'Bengaluru' } } );
    // Open-then-click: the state field is our own combobox since batch 2f. Same user action,
    // same emitted value, and every assertion about the Save gate below is untouched.
    fireEvent.click( screen.getByRole( 'combobox', { name: 'State' } ) );
    fireEvent.click( screen.getByRole( 'option', { name: 'Karnataka' } ) );
    expect( saveButton() ).toBeDisabled();

    // A PIN starting with zero is the one the server refuses as INVALID_PIN, so the mirror has
    // to refuse it too or the customer learns about it from a 400.
    fireEvent.change( screen.getByLabelText( 'PIN code' ), { target: { value: '060001' } } );
    expect( saveButton() ).toBeDisabled();

    fireEvent.change( screen.getByLabelText( 'PIN code' ), { target: { value: '560001' } } );
    expect( saveButton() ).toBeEnabled();
  } );

  it( 'posts only the address, and no countryCode the server is about to default', async () => {
    const fetchMock = stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="address" initial={ INITIAL } onReady={ vi.fn() } /> );
    fireEvent.click( saveButton() );
    await waitFor( () => expect( profileBodies( fetchMock ) ).toHaveLength( 1 ) );

    const [ body ] = profileBodies( fetchMock );
    expect( Object.keys( body ) ).toEqual( [ 'address' ] );
    expect( body.address ).toEqual( {
      addressLine1: '12 MG Road',
      addressLine2: 'Flat 3B',
      city: 'Bengaluru',
      state: 'Karnataka',
      postalCode: '560001',
    } );
  } );

  it( 'hands the saved profile back with the stored name and email merged in', async () => {
    stubFetch();
    const onReady = vi.fn();
    render( <CheckoutProfile accessToken="fixture-session" mode="address" initial={ INITIAL } onReady={ onReady } /> );
    fireEvent.click( saveButton() );
    await waitFor( () => expect( onReady ).toHaveBeenCalledTimes( 1 ) );
    expect( onReady.mock.calls[ 0 ][ 0 ] ).toEqual( {
      contactId: 'contact-1',
      name: 'Asha Sen',
      firstName: 'Asha',
      lastName: 'Sen',
      email: 'asha@example.com',
      phone: '+918100640044',
      addressComplete: true,
      address: ADDRESS,
    } );
  } );
} );

describe( 'CheckoutProfile name mode', () => {
  it( 'enables Save on the names alone and posts only the two parts', async () => {
    const fetchMock = stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="name" initial={ INITIAL } onReady={ vi.fn() } /> );
    expect( saveButton() ).toBeEnabled();
    expect( screen.queryByLabelText( 'Email' ) ).toBeNull();
    expect( screen.queryByLabelText( 'Address line 1' ) ).toBeNull();

    fireEvent.change( screen.getByLabelText( 'First name' ), { target: { value: 'Asha R' } } );
    fireEvent.click( saveButton() );
    await waitFor( () => expect( profileBodies( fetchMock ) ).toHaveLength( 1 ) );

    const [ body ] = profileBodies( fetchMock );
    expect( Object.keys( body ).sort() ).toEqual( [ 'firstName', 'lastName' ] );
    expect( body ).toEqual( { firstName: 'Asha R', lastName: 'Sen' } );
  } );

  it( 'refuses half a name, which the backend reads as a mistake and not an edit', () => {
    stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="name" initial={ INITIAL } onReady={ vi.fn() } /> );
    fireEvent.change( screen.getByLabelText( 'Last name' ), { target: { value: '' } } );
    expect( saveButton() ).toBeDisabled();
  } );
} );

describe( 'CheckoutProfile email mode', () => {
  it( 'saves an unchanged email with no proof at all', async () => {
    const fetchMock = stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="email" initial={ INITIAL } onReady={ vi.fn() } /> );
    expect( saveButton() ).toBeEnabled();

    fireEvent.click( saveButton() );
    await waitFor( () => expect( profileBodies( fetchMock ) ).toHaveLength( 1 ) );
    expect( profileBodies( fetchMock )[ 0 ] ).toEqual( { email: 'asha@example.com' } );
  } );

  it( 'treats a respaced or recased email as unchanged, the way normalize_email does', () => {
    stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="email" initial={ INITIAL } onReady={ vi.fn() } /> );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: '  ASHA@Example.com ' } } );
    expect( saveButton() ).toBeEnabled();
  } );

  it( 'disables Save for a changed email until a proof exists, then posts both', async () => {
    const fetchMock = stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="email" initial={ INITIAL } onReady={ vi.fn() } /> );

    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'new@example.com' } } );
    expect( saveButton() ).toBeDisabled();

    fireEvent.click( screen.getByRole( 'button', { name: 'Send verification code by email' } ) );
    fireEvent.change( await screen.findByLabelText( 'Email verification code' ), { target: { value: '123456' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Confirm email code' } ) );
    await screen.findByText( '✓ Email verified' );
    expect( saveButton() ).toBeEnabled();

    fireEvent.click( saveButton() );
    await waitFor( () => expect( profileBodies( fetchMock ) ).toHaveLength( 1 ) );
    expect( profileBodies( fetchMock )[ 0 ] ).toEqual( {
      email: 'new@example.com',
      emailProof: 'fixture-proof',
    } );
  } );

  it( 'greets the stored first name, because email mode renders no name input', async () => {
    const fetchMock = stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="email" initial={ INITIAL } onReady={ vi.fn() } /> );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'new@example.com' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send verification code by email' } ) );

    await waitFor( () => expect( fetchMock ).toHaveBeenCalledTimes( 1 ) );
    const request = JSON.parse( ( fetchMock.mock.calls[ 0 ][ 1 ] as any ).body );
    expect( request ).toEqual( { action: 'request', email: 'new@example.com', firstName: 'Asha' } );
  } );

  it( 'drops the proof again when the email changes after verifying', async () => {
    stubFetch();
    render( <CheckoutProfile accessToken="fixture-session" mode="email" initial={ INITIAL } onReady={ vi.fn() } /> );
    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'new@example.com' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send verification code by email' } ) );
    fireEvent.change( await screen.findByLabelText( 'Email verification code' ), { target: { value: '123456' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Confirm email code' } ) );
    await screen.findByText( '✓ Email verified' );

    fireEvent.change( screen.getByLabelText( 'Email' ), { target: { value: 'third@example.com' } } );
    expect( screen.queryByText( '✓ Email verified' ) ).toBeNull();
    expect( saveButton() ).toBeDisabled();
  } );
} );

describe( 'the emailProof invariant, across every mode', () => {
  it( 'never posts an emailProof without an email', async () => {
    const fetchMock = stubFetch();
    const modes = [ 'address', 'name', 'email' ] as const;

    for ( const mode of modes ) {
      const view = render( <CheckoutProfile accessToken="fixture-session" mode={ mode }
        initial={ INITIAL } onReady={ vi.fn() } /> );
      fireEvent.click( saveButton() );
      await waitFor( () => expect( profileBodies( fetchMock ).length ).toBeGreaterThan( 0 ) );
      view.unmount();
    }

    const bodies = profileBodies( fetchMock );
    expect( bodies ).toHaveLength( 3 );
    for ( const body of bodies ) {
      if ( 'emailProof' in body ) {
        expect( String( body.email || '' ) ).not.toBe( '' );
      }
    }
  } );
} );
