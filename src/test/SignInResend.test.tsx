import React from 'react';
import {
  afterEach, beforeEach, describe, expect, it, vi,
} from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import * as customerAuth from '../lib/customerAuth';
import SignIn from '../pages/account/sign-in';

/**
 * ASKING FOR ANOTHER CODE ON /account/sign-in/.
 *
 * THE GAP THIS CLOSES. The Phase 4 audit measured the four OTP surfaces and found this page had
 * NO resend affordance at all. A shopper whose WhatsApp code did not arrive - a delayed Meta
 * send, a phone that was off, a message in an archived thread - had nothing on the page to press.
 * The only route forward was to leave and start again, which on the register path means answering
 * the front-door code a second time. "OTP + OTP-resend buttons inconsistent or missing" is the
 * owner's wording, and this page was the "missing" half.
 *
 * THE PROPERTY THAT MATTERS MOST IS THE SESSION. requestOtp issues a NEW Cognito challenge and
 * returns a new session token; answering the new code against the OLD session is a guaranteed
 * rejection. So a resend that does not store the new session produces a page where the resend
 * APPEARS to work and then refuses every code the shopper enters - worse than having no resend,
 * because it looks like the shopper's fault. That is asserted directly below by sending, resending
 * and then checking which session submitOtp was handed.
 *
 * THE THREE PHASES DO NOT SHARE ONE SEND, which is the other thing worth pinning:
 *   'register-code' is the registration front door (a fetch), which issues its own WhatsApp OTP
 *   'code' and 'signin-code' are the Cognito CUSTOM_AUTH challenge, via requestOtp
 * A resend that called the wrong one would send a code the current phase cannot verify.
 *
 * jsdom cannot read computed styles, so the control's appearance - the derived secondary, white
 * fill with lime on hover, 52px pill - is tools/browser/designsweep.js's job. These are the
 * behaviours.
 */

let navigatedTo: string;

beforeEach( () => {
  navigatedTo = '';
  Object.defineProperty( window, 'location', {
    configurable: true,
    value: {
      ...window.location,
      search: '',
      assign: ( url: string ) => { navigatedTo = String( url ); },
      replace: ( url: string ) => { navigatedTo = String( url ); },
    },
  } );
} );

afterEach( () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
} );

const resend = () => screen.getByRole( 'button', { name: /^Resend OTP on WhatsApp/ } );

async function enterPhone ( value = '+919876543210' ): Promise<void> {
  fireEvent.change( screen.getByLabelText( 'WhatsApp number' ), { target: { value } } );
  fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );
}

describe( 'the registered path', () => {
  it( 'offers a resend on the code step, which this page did not have at all', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 'sess-A', destination: '********3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );

    render( <SignIn /> );
    // The phone step must NOT carry one: there is no code outstanding to resend.
    expect( screen.queryByRole( 'button', { name: /Resend/ } ) ).toBeNull();

    await enterPhone();
    await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toBeInTheDocument() );
    expect( resend() ).toBeInTheDocument();
  } );

  it( 'stores the NEW session, so the code the shopper then types can actually be verified',
    async () => {
      vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
      const requestOtp = vi.spyOn( customerAuth, 'requestOtp' )
        .mockResolvedValueOnce( {
          session: 'sess-FIRST', destination: '********3210', expiresInSeconds: 600, registered: true,
        } )
        .mockResolvedValueOnce( {
          session: 'sess-SECOND', destination: '********3210', expiresInSeconds: 600, registered: true,
        } );
      const submitOtp = vi.spyOn( customerAuth, 'submitOtp' ).mockResolvedValue( {
        accessToken: 'tok-1', expiresAt: Date.now() + 3_600_000,
      } );
      vi.stubGlobal( 'fetch', vi.fn() );

      render( <SignIn /> );
      await enterPhone();
      await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toBeInTheDocument() );

      fireEvent.click( resend() );
      await waitFor( () => expect( requestOtp ).toHaveBeenCalledTimes( 2 ) );

      fireEvent.change( screen.getByLabelText( 'WhatsApp code' ), { target: { value: '222222' } } );
      fireEvent.click( screen.getByRole( 'button', { name: 'Confirm WhatsApp code' } ) );
      await waitFor( () => expect( submitOtp ).toHaveBeenCalled() );

      // THE ASSERTION THIS FILE EXISTS FOR. The third argument is the session, and it must be the
      // one the RESEND issued. Handing back sess-FIRST would make every code wrong.
      expect( submitOtp.mock.calls[ 0 ][ 2 ] ).toBe( 'sess-SECOND' );
    } );

  it( 'clears the stale code, so Confirm cannot be pressed on a superseded one', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 'sess-A', destination: '********3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );

    render( <SignIn /> );
    await enterPhone();
    await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toBeInTheDocument() );
    fireEvent.change( screen.getByLabelText( 'WhatsApp code' ), { target: { value: '111111' } } );

    fireEvent.click( resend() );
    await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toHaveValue( '' ) );
  } );

  it( 'reports a resend failure in the page\'s own error region, not a new wording', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    vi.spyOn( customerAuth, 'requestOtp' )
      .mockResolvedValueOnce( {
        session: 'sess-A', destination: '********3210', expiresInSeconds: 600, registered: true,
      } )
      .mockRejectedValueOnce( Object.assign( new Error( 'TooManyRequestsException' ),
        { name: 'TooManyRequestsException' } ) );
    vi.stubGlobal( 'fetch', vi.fn() );

    render( <SignIn /> );
    await enterPhone();
    await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toBeInTheDocument() );

    fireEvent.click( resend() );
    // role=alert, the region the page already uses for a failed send. A resend fails for the
    // same reasons a first send fails, so it must not invent a third message table.
    await waitFor( () => expect( screen.getByRole( 'alert' ) ).toBeInTheDocument() );
  } );
} );

describe( 'the register path, whose resend is a different send', () => {
  it( 'repeats the registration front door rather than the Cognito challenge', async () => {
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: '', destination: '', expiresInSeconds: 600, registered: false,
    } );
    const fetchMock = vi.fn( async () => ( {
      ok: true, status: 200, json: async () => ( {} ),
    } ) );
    vi.stubGlobal( 'fetch', fetchMock );

    render( <SignIn /> );
    await enterPhone();
    await waitFor( () => expect( screen.getByLabelText( 'WhatsApp code' ) ).toBeInTheDocument() );

    const before = fetchMock.mock.calls.length;
    const otpCalls = requestOtp.mock.calls.length;
    fireEvent.click( resend() );
    await waitFor( () => expect( fetchMock.mock.calls.length ).toBe( before + 1 ) );

    // The front door, with action:'request' - NOT a second requestOtp, which would send a Cognito
    // code this phase has no session for and cannot verify.
    const body = JSON.parse( String( ( fetchMock.mock.calls.at( -1 ) as any )[ 1 ].body ) );
    expect( body.action ).toBe( 'request' );
    expect( body.phone ).toBe( '+919876543210' );
    expect( requestOtp.mock.calls.length ).toBe( otpCalls );
  } );
} );

describe( 'the cooldown, which is the shared control\'s', () => {
  it( 'disables itself for 30s after a press, so one impatient tap is not three sends', async () => {
    vi.useFakeTimers();
    vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null );
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 'sess-A', destination: '********3210', expiresInSeconds: 600, registered: true,
    } );
    vi.stubGlobal( 'fetch', vi.fn() );

    render( <SignIn /> );
    fireEvent.change( screen.getByLabelText( 'WhatsApp number' ),
      { target: { value: '+919876543210' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );

    fireEvent.click( resend() );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );
    expect( resend() ).toBeDisabled();

    fireEvent.click( resend() );
    fireEvent.click( resend() );
    // Two sends total: the first from the phone step, one from the resend.
    expect( requestOtp ).toHaveBeenCalledTimes( 2 );

    await act( async () => { await vi.advanceTimersByTimeAsync( 30_000 ); } );
    expect( resend() ).toBeEnabled();
  } );
} );
