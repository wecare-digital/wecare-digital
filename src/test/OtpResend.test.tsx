import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import OtpResend, { OTP_RESEND_COOLDOWN_MS } from '../components/OtpResend';

/**
 * THE SHARED RESEND CONTROL.
 *
 * WHAT THIS IS PINNING, which is a functional gap rather than a styling one. The Phase 4 audit
 * measured the four OTP surfaces and found /account/sign-in/ and /get/ had NO resend affordance
 * at all: a shopper whose WhatsApp code never arrived had nothing to press and had to leave the
 * page. BlogSubscribe had one with no cooldown; CheckoutProfile had one with a 60 s server
 * cooldown and a different wording. Four surfaces, three answers.
 *
 * THE ASSERTIONS ARE PROPERTIES, NOT TODAY'S PIXELS. Colour, radius and height are the browser
 * harness's job - vitest does not run the styled-jsx transform, so nothing here can observe a
 * computed style that depends on scoping. tools/browser/designsweep.js measures the geometry
 * against the home CTA. What IS observable in jsdom, and what actually broke, is behaviour:
 * the wording, the cooldown arithmetic, which deadline wins, and that the control is genuinely
 * disabled rather than merely dimmed.
 *
 * THE WORDING CASES ARE NOT DECORATION. "Resend OTP on WhatsApp" is a standing owner decision -
 * OTP is a WhatsApp-only channel on this site - and the component takes a closed `channel` union
 * rather than a free-text label precisely so no caller can introduce a third wording or imply an
 * email sign-in exists. The test for `channel="email"` asserts it says "code" and never "OTP",
 * which is the distinction that keeps the one-time email VERIFICATION from reading as a sign-in
 * channel.
 *
 * Fake timers throughout, so the cooldown is asserted rather than waited for.
 */

const control = () => screen.getByRole( 'button' );
const tick = ( ms: number ) => act( async () => { await vi.advanceTimersByTimeAsync( ms ); } );

afterEach( () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
} );

describe( 'the wording, which is a closed set', () => {
  it( 'names WhatsApp by default, because OTP is a WhatsApp-only channel here', () => {
    render( <OtpResend onResend={ vi.fn() } /> );
    expect( control() ).toHaveAccessibleName( 'Resend OTP on WhatsApp' );
  } );

  it( 'says "code" and never "OTP" on the email verification path', () => {
    render( <OtpResend onResend={ vi.fn() } channel="email" /> );
    expect( control() ).toHaveAccessibleName( 'Resend email code' );
    // The load-bearing half: an email OTP would contradict the standing WhatsApp-only rule.
    expect( control().textContent || '' ).not.toMatch( /OTP/i );
  } );

  it( 'is a type="button", so it never submits the form it sits inside', () => {
    render( <OtpResend onResend={ vi.fn() } /> );
    expect( control() ).toHaveAttribute( 'type', 'button' );
  } );
} );

describe( 'the cooldown', () => {
  it( 'runs its own 30s from the press, which is what the two sign-in surfaces need', async () => {
    vi.useFakeTimers();
    const onResend = vi.fn();
    render( <OtpResend onResend={ onResend } /> );

    fireEvent.click( control() );
    expect( onResend ).toHaveBeenCalledTimes( 1 );
    expect( control() ).toBeDisabled();
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 30s' );

    await tick( 1000 );
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 29s' );

    await tick( OTP_RESEND_COOLDOWN_MS - 1000 );
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp' );
    expect( control() ).toBeEnabled();
  } );

  it( 'is GENUINELY disabled while cooling, not merely dimmed', async () => {
    vi.useFakeTimers();
    const onResend = vi.fn();
    render( <OtpResend onResend={ onResend } /> );

    fireEvent.click( control() );
    fireEvent.click( control() );
    fireEvent.click( control() );
    // One send, not three. A dimmed-but-live control is how a shopper spends their hourly
    // budget on one impatient double-tap and then cannot resend at all.
    expect( onResend ).toHaveBeenCalledTimes( 1 );
    await tick( 500 );
    fireEvent.click( control() );
    expect( onResend ).toHaveBeenCalledTimes( 1 );
  } );

  it( 'takes the SERVER deadline when it is longer, so a 429 is never shortened', async () => {
    vi.useFakeTimers();
    const onResend = vi.fn();
    // 60s, the shape CheckoutProfile passes from retryAfterSeconds and the challenge store's
    // own window. The component's own floor is 30s and must not win.
    render( <OtpResend onResend={ onResend } cooldownUntil={ Date.now() + 60_000 } /> );

    expect( control() ).toBeDisabled();
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 60s' );

    await tick( 31_000 );
    expect( control() ).toBeDisabled();
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 29s' );

    await tick( 29_000 );
    expect( control() ).toBeEnabled();
  } );

  it( 'applies its own floor to the NEXT press after a shorter server deadline expires', async () => {
    vi.useFakeTimers();
    render( <OtpResend onResend={ vi.fn() } cooldownUntil={ Date.now() + 5_000 } /> );

    // The server hint is honoured as-is while it runs. The component does NOT pad it up to 30s:
    // the caller's deadline is the server speaking, and the floor exists to bound the shopper's
    // own repeat presses, not to lengthen a wait the server already quantified.
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 5s' );
    expect( control() ).toBeDisabled();

    await tick( 5_000 );
    expect( control() ).toBeEnabled();

    // Now the floor takes over, so an impatient second press is still bounded at 30s even though
    // the server only ever asked for 5.
    fireEvent.click( control() );
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp 30s' );
  } );

  it( 'clears its interval on unmount, so a finished page is not re-rendering every second', async () => {
    vi.useFakeTimers();
    const clear = vi.spyOn( globalThis, 'clearInterval' );
    const { unmount } = render( <OtpResend onResend={ vi.fn() } /> );
    fireEvent.click( control() );
    await tick( 1000 );
    unmount();
    expect( clear ).toHaveBeenCalled();
  } );
} );

describe( 'the states that are not a cooldown', () => {
  it( 'stops asking when blocked, with no countdown, because no wait helps', () => {
    render( <OtpResend onResend={ vi.fn() } blocked /> );
    expect( control() ).toBeDisabled();
    // The RESEND_LIMIT_REACHED shape: there is no number of seconds to show, so showing one
    // would be a promise the server will not keep.
    expect( control() ).toHaveTextContent( 'Resend OTP on WhatsApp' );
    expect( control().textContent || '' ).not.toMatch( /\ds/ );
  } );

  it( 'is disabled while the surface is busy', () => {
    render( <OtpResend onResend={ vi.fn() } busy /> );
    expect( control() ).toBeDisabled();
  } );
} );
