/**
 * Mobile workspace navigation contract.
 *
 * The permanent phone bar is intentionally independent of business-module count:
 * Home | Search | Tasks | Me. Modules are discovered from Workspace Home and search.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';

let pathname = '/workspace';
const push = vi.fn();

vi.mock( 'next/router', () => ( {
  useRouter: () => ( { pathname, push, query: {}, isReady: true } ),
} ) );

import BottomNav from '../components/BottomNav';

const SRC = fs.readFileSync(
  path.resolve( __dirname, '../components/BottomNav.tsx' ), 'utf8' );
const CSS = fs.readFileSync(
  path.resolve( __dirname, '../styles/Layout.css' ), 'utf8' );

beforeEach( () => {
  pathname = '/workspace';
  push.mockClear();
} );

describe( 'stable phone navigation', () => {
  it( 'shows exactly Home, Search, Tasks and Me', () => {
    render( <BottomNav onSearch={ () => {} } onProfile={ () => {} } /> );
    expect( screen.getAllByRole( 'button' ) ).toHaveLength( 4 );
    for ( const label of [ 'Home', 'Search', 'Tasks', 'Me' ] ) {
      expect( screen.getByText( label ) ).toBeTruthy();
    }
  } );

  it( 'does not rebuild the module menu in the bottom bar', () => {
    expect( SRC ).not.toContain( 'navigationConfig' );
    expect( SRC ).not.toContain( 'More navigation' );
  } );

  it( 'navigates Home and Tasks to their real routes', () => {
    render( <BottomNav onSearch={ () => {} } onProfile={ () => {} } /> );
    fireEvent.click( screen.getByText( 'Tasks' ) );
    expect( push ).toHaveBeenCalledWith( '/workspace/task' );
    push.mockClear();
    fireEvent.click( screen.getByText( 'Home' ) );
    expect( push ).toHaveBeenCalledWith( '/workspace' );
  } );

  it( 'delegates Search and Me to the shell', () => {
    const onSearch = vi.fn();
    const onProfile = vi.fn();
    render( <BottomNav onSearch={ onSearch } onProfile={ onProfile } /> );
    fireEvent.click( screen.getByText( 'Search' ) );
    fireEvent.click( screen.getByText( 'Me' ) );
    expect( onSearch ).toHaveBeenCalledTimes( 1 );
    expect( onProfile ).toHaveBeenCalledTimes( 1 );
    expect( push ).not.toHaveBeenCalled();
  } );

  it( 'marks Home and Tasks using aria-current rather than colour alone', () => {
    pathname = '/workspace';
    const { unmount } = render( <BottomNav onSearch={ () => {} } onProfile={ () => {} } /> );
    expect( screen.getByText( 'Home' ).closest( 'button' )?.getAttribute( 'aria-current' ) ).toBe( 'page' );
    unmount();

    pathname = '/workspace/task';
    render( <BottomNav onSearch={ () => {} } onProfile={ () => {} } /> );
    expect( screen.getByText( 'Tasks' ).closest( 'button' )?.getAttribute( 'aria-current' ) ).toBe( 'page' );
  } );

  it( 'reflects the profile popover state on Me', () => {
    render( <BottomNav onSearch={ () => {} } onProfile={ () => {} } profileOpen /> );
    expect( screen.getByLabelText( /Open profile/i ).getAttribute( 'aria-expanded' ) ).toBe( 'true' );
  } );
} );

describe( 'mobile CSS contract', () => {
  it( 'is hidden by default and shown in the phone breakpoint', () => {
    expect( CSS ).toMatch( /\.bottom-nav\s*\{\s*display:\s*none/ );
    expect( CSS ).toContain( '@media (max-width: 768px)' );
  } );

  it( 'keeps content above the fixed bar', () => {
    expect( CSS ).toMatch( /padding-bottom:\s*calc\(68px \+ env\(safe-area-inset-bottom/ );
  } );

  it( 'respects the iOS home-indicator safe area', () => {
    expect( CSS ).toContain( 'env(safe-area-inset-bottom' );
    expect( CSS ).toMatch( /height:\s*calc\(60px \+ env\(safe-area-inset-bottom/ );
  } );

  it( 'keeps every item above the touch-target floor', () => {
    expect( CSS ).toMatch( /\.bn-item[\s\S]*?min-height:\s*44px/ );
  } );
} );
