import fs from 'fs';
import path from 'path';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Toast, { type ToastMessage } from '../components/Toast';
import { scrollToEnd } from '../lib/scroll-to-end';

/**
 * MOTION IS DECLARED IN CSS, AND TIME IS NOT MOTION.
 *
 * Two changes are pinned here, both of the same shape: a script had hardcoded something the
 * stylesheet should own, and in both cases the hardcoded value was already wrong or unreachable
 * by `prefers-reduced-motion`.
 *
 *  - The toast unmounted on `setTimeout(..., 300)`, a guess at a CSS animation that actually runs
 *    for 0.2s. Removal is driven by `animationend` now.
 *  - Five `scrollIntoView({ behavior: 'smooth' })` calls across four files animated regardless of
 *    the reader's reduced-motion preference, because a JS argument cannot read a media query.
 *
 * The CSS assertions here read the real stylesheet rather than a rendered tree, because these are
 * global stylesheets that jsdom never applies - there is no computed style to inspect, so the file
 * is the only available source of truth.
 */

const ROOT = path.join( __dirname, '..', '..' );
const INNER_UX = fs.readFileSync( path.join( ROOT, 'src', 'styles', 'inner-ux.css' ), 'utf8' );

afterEach( () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
} );

const toast: ToastMessage = { id: 't1', type: 'success', message: 'Saved' };

describe( 'Toast dismissal is driven by the CSS animation, not a JS guess', () => {
  /**
   * WHAT THIS CAN AND CANNOT OBSERVE, stated because the gap matters.
   *
   * jsdom does not implement AnimationEvent, and React therefore never delivers `animationend`
   * there at all - probed directly with a bare onAnimationEnd handler, a plain bubbling Event and
   * testing-library's fireEvent.animationEnd, and none of the three reach the handler. So the
   * primary removal path cannot be exercised here, and an assertion pretending to exercise it
   * would pass for the wrong reason.
   *
   * What IS observable is the contract around it: the hold is a timer, the exit class is applied
   * when the hold ends, the component does not unmount itself on a guessed delay, and the backstop
   * guarantees removal when no animation event ever arrives - which in this environment is always.
   */
  it( 'waits out the hold, marks the toast exiting, and does not unmount on a guessed delay', () => {
    vi.useFakeTimers();
    const onRemove = vi.fn();
    const { container } = render( <Toast toasts={ [ toast ] } onRemove={ onRemove } /> );

    act( () => { vi.advanceTimersByTime( 3999 ); } );
    expect( container.querySelector( '.toast' )?.className ).not.toContain( 'toast-exit' );
    expect( onRemove ).not.toHaveBeenCalled();

    act( () => { vi.advanceTimersByTime( 1 ); } );
    expect( container.querySelector( '.toast' )?.className ).toContain( 'toast-exit' );

    // The old code removed the node 300ms after this point, a guess at a 0.2s animation. Nothing
    // may remove it on that schedule now - the stylesheet decides, via animationend.
    act( () => { vi.advanceTimersByTime( 300 ); } );
    expect( onRemove ).not.toHaveBeenCalled();
  } );

  it( 'removes the toast anyway if no animation event ever arrives', () => {
    vi.useFakeTimers();
    const onRemove = vi.fn();
    render( <Toast toasts={ [ toast ] } onRemove={ onRemove } /> );

    act( () => { vi.advanceTimersByTime( 4000 ); } );
    expect( onRemove ).not.toHaveBeenCalled();
    // The backstop is an upper bound, not a matched duration, so it fires well after any real exit.
    act( () => { vi.advanceTimersByTime( 1000 ); } );
    expect( onRemove ).toHaveBeenCalledWith( 't1' );
  } );

  it( 'honours an explicit duration for the hold', () => {
    vi.useFakeTimers();
    const onRemove = vi.fn();
    const { container } = render(
      <Toast toasts={ [ { ...toast, duration: 1000 } ] } onRemove={ onRemove } />
    );
    act( () => { vi.advanceTimersByTime( 1000 ); } );
    expect( container.querySelector( '.toast' )?.className ).toContain( 'toast-exit' );
  } );

  it( 'dismisses immediately when the reader asks, without waiting for an animation', () => {
    const onRemove = vi.fn();
    render( <Toast toasts={ [ toast ] } onRemove={ onRemove } /> );
    fireEvent.click( screen.getByRole( 'button', { name: 'Dismiss notification' } ) );
    expect( onRemove ).toHaveBeenCalledWith( 't1' );
  } );

  /**
   * THE TRAP THIS GUARDS. The reduced-motion block used to say `animation: none` for `.toast` and
   * `.toast-exit`. That reads as the correct way to honour the preference and, now that removal
   * listens for `animationend`, would stop the event firing at all - a reduced-motion reader's
   * toasts would stack in the corner and never leave. 0.01ms is the standard reset precisely
   * because it keeps the event.
   */
  it( 'never suppresses the toast animation outright under reduced motion', () => {
    const block = INNER_UX.slice( INNER_UX.indexOf( 'prefers-reduced-motion' ) );
    const toastRules = block.slice( block.indexOf( '.toast' ), block.indexOf( '.toast' ) + 400 );
    expect( toastRules ).toContain( 'animation-duration: 0.01ms' );
    expect( toastRules ).not.toContain( 'animation: none' );
  } );
} );

describe( 'Scrolling asks the stylesheet, not the device', () => {
  it( 'scrolls to the end without specifying a behavior, so CSS decides', () => {
    const spy = vi.fn();
    const el = { scrollIntoView: spy } as unknown as HTMLElement;
    scrollToEnd( el );

    expect( spy ).toHaveBeenCalledTimes( 1 );
    const arg = spy.mock.calls[ 0 ][ 0 ];
    // block:'end' is stated - the default 'start' pins the newest message under the header.
    expect( arg ).toEqual( { block: 'end' } );
    // The whole point: no behavior key, so the container's computed scroll-behavior governs and
    // the reduced-motion media query is able to reach it.
    expect( arg ).not.toHaveProperty( 'behavior' );
  } );

  it( 'is safe to call with nothing, because every caller holds an optional ref', () => {
    expect( () => scrollToEnd( null ) ).not.toThrow();
    expect( () => scrollToEnd( undefined ) ).not.toThrow();
  } );

  it( 'turns smooth scrolling off for everything under reduced motion', () => {
    const block = INNER_UX.slice( INNER_UX.indexOf( 'prefers-reduced-motion' ) );
    // !important and the universal selector are both required: one of the four scroll containers
    // is styled inline, and an inline declaration outranks a plain stylesheet rule.
    expect( block ).toContain( 'scroll-behavior: auto !important' );
  } );

  it( 'declares smooth scrolling on the containers the scripts scroll', () => {
    const declares = ( file: string, selector: string ) => {
      const css = fs.readFileSync( path.join( ROOT, file ), 'utf8' );
      const at = css.indexOf( selector );
      expect( at, `${selector} not found in ${file}` ).toBeGreaterThan( -1 );
      return css.slice( at, at + 600 );
    };
    expect( declares( 'src/styles/Layout.css', '.agent-messages {' ) ).toContain( 'scroll-behavior: smooth' );
    expect( declares( 'src/pages/workspace/engage/inbox/index.tsx', '.ui-thread-body {' ) ).toContain( 'scroll-behavior: smooth' );
    expect( declares( 'src/components/dashboard/tabs/InternalChatTab.tsx', "overflowY: 'auto'" ) ).toContain( "scrollBehavior: 'smooth'" );
  } );

  it( 'leaves no hardcoded smooth behavior in any component', () => {
    const files = [
      'src/components/FloatingAgent.tsx',
      'src/components/dashboard/tabs/InternalChatTab.tsx',
      'src/pages/workspace/engage/inbox/index.tsx',
      'src/components/workspace/whatsapp/inbox.tsx',
    ];
    for ( const file of files ) {
      const source = fs.readFileSync( path.join( ROOT, file ), 'utf8' );
      expect( source, `${file} still passes behavior:'smooth'` ).not.toMatch( /behavior:\s*'smooth'/ );
    }
    /*
     * The ONE surviving behavior argument is deliberate and stays: opening a thread jumps to the
     * newest message with behavior:'auto', which is an instant positioning rather than a
     * transition. Animating it would scroll the reader through the whole history they just opened.
     */
    const inbox = fs.readFileSync( path.join( ROOT, 'src/pages/workspace/engage/inbox/index.tsx' ), 'utf8' );
    expect( inbox ).toMatch( /behavior:\s*'auto'/ );
  } );
} );
