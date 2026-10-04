import React from 'react';
import {
  afterEach, beforeEach, describe, expect, it, vi,
} from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import * as customerAuth from '../lib/customerAuth';
import * as api from '../api/client';
import GetPage from '../pages/get';

/**
 * /get — the customer file collection point (verify on WhatsApp, pay, download).
 *
 * WHY THIS FILE EXISTS. The owner reported that /get and /account/sign-in looked like two
 * different websites: "i am seeing sign and otp pages differ in phone button + phone fields".
 * They were right, and the cause was that /account/sign-in had been migrated to the shared
 * PhoneField + PillButton components while /get kept a bespoke `.sf-input` / `.sf-cta` pair —
 * a 2px rgba(26,58,42,.18) border on a 12px radius, and a CTA bordered in the same lime as its
 * own panel fill. /get was also the last surface still carrying the single-lime CTA the owner
 * had already replaced with the dark-green + mint pill, and the last one using red for errors.
 *
 * WHAT THIS GUARDS:
 *   - the page renders the SHARED controls (PhoneField for the number, PillButton for the
 *     primary action) rather than page-local lookalikes, on BOTH the 'mobile' and 'otp' stages,
 *     so the two steps cannot drift apart from each other or from /account/sign-in again;
 *   - the home-page top section is the shared RotatingHero, mounted after the header, and the
 *     page still owns exactly ONE <h1> and ONE <main> (htmlcheck guards H1-MANY / MANY-MAIN,
 *     and the hero provides both — the page's former <main className="sf-shell"> and
 *     <h1 className="sf-title"> had to go, with the stage heading demoted to <h2>);
 *   - no bespoke `.sf-cta` control comes back;
 *   - the auth LOGIC is untouched: an unregistered number still stops before the code screen
 *     instead of showing a box no code can satisfy.
 *
 * jsdom cannot read computed styles, so "do the two pages LOOK the same" is proved in the build
 * instead: both emit the identical styled-jsx class hashes (jsx-69f2e5793ae0f718 for .pill,
 * jsx-3616f696677abbf2 for .pf-num/.pf-code), which is only possible if they share one
 * stylesheet. What is asserted here is that the shared components are the ones being rendered.
 */

beforeEach( () => {
  // Keep the page on its first stage: restoreSession resolving falsy means no session to resume,
  // so the mount effect does not jump to the 'files' stage.
  vi.spyOn( customerAuth, 'restoreSession' ).mockResolvedValue( null as never );
  vi.spyOn( customerAuth, 'getSession' ).mockReturnValue( null as never );
} );

afterEach( () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
} );

describe( 'Get page', () => {
  it( 'owns a single h1 and a single main, both provided by the shared hero', async () => {
    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( 'main' ) ).toBeTruthy() );

    // The hero provides exactly one of each; the page must not add a second (htmlcheck's
    // H1-MANY and MANY-MAIN).
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );

    // The top section is the SHARED RotatingHero, not a bespoke lookalike: these are its own
    // class names, so a hand-rolled hero would not produce them.
    expect( container.querySelector( '.rh-head-line' ) ).toBeTruthy();
    expect( container.querySelectorAll( '.rh-cyc-word' ).length ).toBeGreaterThan( 0 );
  } );

  it( 'renders the hero frame line and words that are true of this page', async () => {
    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( 'h1' ) ).toBeTruthy() );

    const h1 = container.querySelector( 'h1' );
    expect( h1?.textContent ).toContain( 'Collect your' );

    // The rotation names what arrives here, rather than borrowing the home page's marketing
    // audiences. The screen-reader copy lists the words once; the animated copies are aria-hidden.
    const words = Array.from( container.querySelectorAll( '.rh-cyc-word' ) ).map( w => w.textContent );
    expect( words ).toEqual( [ 'files', 'documents', 'records', 'papers' ] );
  } );

  it( 'uses the shared PhoneField and PillButton on the number stage, not a bespoke pair', async () => {
    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( 'main' ) ).toBeTruthy() );

    // PhoneField's two segments — the divided field /account/sign-in uses.
    expect( container.querySelector( '.pf-code' ) ).toBeTruthy();
    expect( container.querySelector( '.pf-num' ) ).toBeTruthy();

    // PillButton's two segments, and it is the block (full-width) variant the forms want.
    const pill = container.querySelector( '.pill' );
    expect( pill ).toBeTruthy();
    expect( pill?.classList.contains( 'pill-block' ) ).toBe( true );
    // ONE LIME SURFACE, ONE LABEL. The pill was a two-tone control with a dark "Collect" half and
    // a mint action half; the owner retired that on 2026-10-02 ("old multi colour out of date")
    // in favour of a single lime pill, so only the action text is rendered now.
    expect( container.querySelector( '.pill-action' )?.textContent ).toBe( 'Send OTP on WhatsApp' );
    expect( container.querySelector( '.pill-label' ) ).toBeNull();

    // THE RETIRED BESPOKE CONTROL MUST NOT COME BACK. .sf-cta was a lime-on-lime CTA that could
    // not clear WCAG 1.4.11's 3:1 for a control boundary against its own panel fill.
    expect( container.querySelector( '.sf-cta' ) ).toBeNull();
  } );

  it( 'keeps the same pill on the code stage, so the two steps do not look different', async () => {
    vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 'session-1', destination: '+91••••••0044', registered: true,
    } as never );

    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( '.pf-num' ) ).toBeTruthy() );

    // Advance to the code stage through the real control.
    const number = container.querySelector( '.pf-num' ) as HTMLInputElement;
    const { fireEvent } = await import( '@testing-library/react' );
    fireEvent.change( number, { target: { value: '9876543210' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );

    await waitFor( () => expect( container.querySelector( '#code' ) ).toBeTruthy() );

    // THE POINT OF THE WHOLE CHANGE: the code stage renders the SAME pill component, so the only
    // thing that differs between the two steps is the words in it.
    const pill = container.querySelector( '.pill' );
    expect( pill ).toBeTruthy();
    expect( pill?.classList.contains( 'pill-block' ) ).toBe( true );
    expect( container.querySelector( '.pill-action' )?.textContent ).toBe( 'Verify WhatsApp OTP' );
    expect( container.querySelector( '.pill-label' ) ).toBeNull();
    expect( container.querySelector( '.sf-cta' ) ).toBeNull();
  } );

  it( 'offers a resend on the code stage, which this page did not have at all', async () => {
    /*
     * THE GAP. The Phase 4 audit measured the four OTP surfaces and found this stage had no way
     * to ask for another code. "Use a different number" is a way to START OVER, not a way to try
     * the same number again, so a customer whose code did not arrive - a delayed Meta send, a
     * phone that was off - had to abandon the page.
     *
     * handleRequestOtp is reused verbatim rather than a second send path being written: it
     * already re-issues the challenge and re-enters this stage, so the resend cannot drift from
     * the first send. What is asserted is that the control is present, that it calls the same
     * send, and that the shared cooldown then stops a double-tap from spending two more of the
     * customer's hourly budget.
     */
    vi.useFakeTimers();
    const requestOtp = vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: 'session-1', destination: '+91••••••0044', registered: true,
    } as never );
    const { container } = render( <GetPage /> );
    const { act, fireEvent } = await import( '@testing-library/react' );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );

    const number = container.querySelector( '.pf-num' ) as HTMLInputElement;
    fireEvent.change( number, { target: { value: '9876543210' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );
    expect( container.querySelector( '#code' ) ).toBeTruthy();

    const resend = screen.getByRole( 'button', { name: /^Resend OTP on WhatsApp/ } );
    fireEvent.click( resend );
    await act( async () => { await Promise.resolve(); await Promise.resolve(); } );
    expect( requestOtp ).toHaveBeenCalledTimes( 2 );

    // The shared 30s cooldown, so an impatient second tap is not a second send.
    const cooling = screen.getByRole( 'button', { name: /^Resend OTP on WhatsApp/ } );
    expect( cooling ).toBeDisabled();
    fireEvent.click( cooling );
    expect( requestOtp ).toHaveBeenCalledTimes( 2 );

    await act( async () => { await vi.advanceTimersByTimeAsync( 30_000 ); } );
    expect( screen.getByRole( 'button', { name: 'Resend OTP on WhatsApp' } ) ).toBeEnabled();
    vi.useRealTimers();
  } );
  it( 'still refuses to show a code box for an unregistered number (auth logic unchanged)', async () => {
    // The guard that must survive a styling change: Cognito issues a challenge for an unknown
    // number too, so without this the person waits forever for a message never sent.
    vi.spyOn( customerAuth, 'requestOtp' ).mockResolvedValue( {
      session: '', destination: '', registered: false,
    } as never );

    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( '.pf-num' ) ).toBeTruthy() );

    const number = container.querySelector( '.pf-num' ) as HTMLInputElement;
    const { fireEvent } = await import( '@testing-library/react' );
    fireEvent.change( number, { target: { value: '9876543210' } } );
    fireEvent.click( screen.getByRole( 'button', { name: 'Send OTP on WhatsApp' } ) );

    await waitFor( () => expect( screen.getByRole( 'alert' ) ).toBeTruthy() );
    expect( screen.getByRole( 'alert' ).textContent ).toMatch( /No files are registered/i );
    // No code field appeared.
    expect( container.querySelector( '#code' ) ).toBeNull();
  } );

  it( 'surfaces no red: the error banner uses the lime state tint, as /account/sign-in does', async () => {
    const { container } = render( <GetPage /> );
    await waitFor( () => expect( container.querySelector( 'main' ) ).toBeTruthy() );

    // The page's own <style jsx> must not reintroduce the three red values that were removed on
    // owner instruction (#fee2e2 / #ef4444 / #7f1d1d). Read the source rather than computed
    // styles, which jsdom does not provide.
    const fs = require( 'node:fs' );
    const path = require( 'node:path' );
    const src = fs.readFileSync( path.join( process.cwd(), 'src/pages/get.tsx' ), 'utf8' );
    // CSS COMMENTS ARE STRIPPED FIRST, deliberately. The rule that replaced the red one documents
    // the three values it removed, so asserting against the raw block would match that comment and
    // fail — punishing the explanation rather than the defect. What must be absent is a red
    // DECLARATION.
    const styleBlock = src.slice( src.indexOf( '<style jsx>' ) ).replace( /\/\*[\s\S]*?\*\//g, '' );
    expect( styleBlock ).not.toMatch( /#fee2e2|#ef4444|#7f1d1d/ );
    // And the shared components are imported rather than reimplemented.
    expect( src ).toContain( "from '../components/PhoneField'" );
    expect( src ).toContain( "from '../components/PillButton'" );
    expect( src ).toContain( "from '../components/RotatingHero'" );
    // Chrome is mounted centrally in _app.tsx; a page must never import it.
    expect( src ).not.toMatch( /components\/(Header|Footer|SupportWidget|Layout)'/ );
  } );
} );

// Referenced so the api namespace import is not flagged unused; the page's file-listing call is
// only reached on the 'files' stage, which these tests deliberately do not enter.
void api;
