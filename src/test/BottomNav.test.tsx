/**
 * Phase 8.3 — the phone bottom bar.
 *
 * The properties worth holding, each because its absence has a specific consequence:
 *
 *  - It is derived from `navigationConfig`, not a second hardcoded list. The command
 *    palette already drifted from the sidebar once (14 hardcoded entries against 88 real
 *    destinations) and that is the defect this whole navigation phase exists to remove.
 *  - Four streams plus More, never eight. Eight targets on a 360px phone is 45px each,
 *    below the 44px touch minimum once padding is off, and the labels truncate to
 *    nonsense.
 *  - "More" opens the EXISTING drawer. A bar with its own navigation state would be a
 *    second surface to keep in step.
 *  - The active item is marked with `aria-current`, not colour alone.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';

let pathname = '/workspace/engage/inbox';
const push = vi.fn();

vi.mock( 'next/router', () => ( {
  useRouter: () => ( { pathname, push, query: {}, isReady: true } ),
} ) );

import BottomNav from '../components/BottomNav';
import { navigationConfig } from '../config/navigation';

const SRC = fs.readFileSync(
  path.resolve( __dirname, '../components/BottomNav.tsx' ), 'utf8' );
const CSS = fs.readFileSync(
  path.resolve( __dirname, '../styles/Layout.css' ), 'utf8' );

beforeEach( () => {
  pathname = '/workspace/engage/inbox';
  push.mockClear();
} );

describe( 'the bar is derived, not hardcoded', () => {
  it( 'takes its items from navigationConfig', () => {
    expect( SRC ).toContain( 'navigationConfig' );
    render( <BottomNav onMore={ () => {} } /> );
    // The first four sidebar streams, whatever they currently are.
    for ( const item of navigationConfig.slice( 0, 4 ) ) {
      expect( screen.getByText( item.label ) ).toBeTruthy();
    }
  } );

  it( 'shows exactly five targets — four streams and More', () => {
    render( <BottomNav onMore={ () => {} } /> );
    expect( screen.getAllByRole( 'button' ) ).toHaveLength( 5 );
  } );

  it( 'does not try to show all nine streams', () => {
    render( <BottomNav onMore={ () => {} } /> );
    // The fifth stream must NOT be on the bar; it lives in the drawer.
    const fifth = navigationConfig[ 4 ];
    expect( fifth ).toBeTruthy();
    expect( screen.queryByText( fifth.label ) ).toBeNull();
  } );
} );

describe( 'behaviour', () => {
  it( 'navigates to the stream you tap', () => {
    render( <BottomNav onMore={ () => {} } /> );
    fireEvent.click( screen.getByText( navigationConfig[ 1 ].label ) );
    expect( push ).toHaveBeenCalledWith( navigationConfig[ 1 ].path );
  } );

  it( 'delegates More to the existing drawer rather than owning state', () => {
    const onMore = vi.fn();
    render( <BottomNav onMore={ onMore } /> );
    fireEvent.click( screen.getByLabelText( /More navigation/i ) );
    expect( onMore ).toHaveBeenCalledTimes( 1 );
    // It must not navigate — More is not a destination.
    expect( push ).not.toHaveBeenCalled();
  } );

  it( 'marks the current stream with aria-current, not colour alone', () => {
    pathname = '/workspace/engage/inbox';
    render( <BottomNav onMore={ () => {} } /> );
    const current = screen.getAllByRole( 'button' )
      .filter( ( b ) => b.getAttribute( 'aria-current' ) === 'page' );
    expect( current ).toHaveLength( 1 );
    expect( current[ 0 ].textContent ).toContain( 'Inbox' );
  } );

  it( 'reflects the drawer being open on the More button', () => {
    render( <BottomNav onMore={ () => {} } moreOpen /> );
    expect( screen.getByLabelText( /More navigation/i ).getAttribute( 'aria-expanded' ) )
      .toBe( 'true' );
  } );

  it( 'marks nothing current on a page outside the four', () => {
    pathname = '/workspace/seo/schema';
    render( <BottomNav onMore={ () => {} } /> );
    const current = screen.getAllByRole( 'button' )
      .filter( ( b ) => b.getAttribute( 'aria-current' ) === 'page' );
    expect( current ).toHaveLength( 0 );
  } );
} );

describe( 'the CSS contract the bar depends on', () => {
  it( 'is hidden by default and only shown on a phone', () => {
    // Rendered unconditionally and hidden by CSS, because a JS width read is wrong on
    // the first paint of a static export.
    expect( CSS ).toMatch( /\.bottom-nav\s*\{\s*display:\s*none/ );
    expect( CSS ).toContain( '@media (max-width: 768px)' );
  } );

  it( 'insets the content so the bar cannot cover the last row', () => {
    expect( CSS ).toMatch( /padding-bottom:\s*calc\(68px \+ env\(safe-area-inset-bottom/ );
  } );

  it( 'respects the safe area, for WKWebView readiness', () => {
    expect( CSS ).toContain( 'env(safe-area-inset-bottom' );
  } );

  it( 'stays short enough to clear the floating widget geometrically', () => {
    // #wecarewa-widget is 64x64 at bottom:120px with z-index 2147483647, so nothing can
    // be stacked above it. 60px of bar clears 120px of offset; growing it past ~120px
    // would put a green circle through the bar.
    expect( CSS ).toMatch( /height:\s*calc\(60px \+ env\(safe-area-inset-bottom/ );
  } );

  it( 'gives the tablet a permanent rail instead of a hidden drawer', () => {
    expect( CSS ).toContain( '@media (max-width: 1024px) and (min-width: 769px)' );
    expect( CSS ).toMatch( /width:\s*76px/ );
    // margin-INLINE-START, not margin-left. The rail is in flow and the content has to clear
    // it, which is an inline-start relationship rather than a left one: under rtl the rail is
    // on the other side and a physical margin would push the content away from it into the
    // rail. It also HAD to change here in step with the base .main-content rule - Lightning CSS
    // compiles a logical property into a :lang() pair, which carries a specificity class, so a
    // physical override in this media query would have lost to the converted base rule and let
    // the rail overlap the first 76px of every page.
    expect( CSS ).toMatch( /margin-inline-start:\s*76px/ );
    expect( CSS ).not.toMatch( /margin-left:\s*76px/ );
  } );

  it( 'recomposes for a foldable rather than guessing from width alone', () => {
    // Short-and-wide: a bottom bar plus a header eats the vertical space, so
    // navigation moves to the side.
    expect( CSS ).toContain( 'orientation: landscape' );
    // The real posture signal where a browser reports it.
    expect( CSS ).toContain( 'vertical-viewport-segments: 2' );
  } );
} );
