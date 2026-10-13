import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NotFound from '../pages/404';

const router = vi.hoisted( () => ( { replace: vi.fn() } ) );
vi.mock( 'next/router', () => ( { useRouter: () => router } ) );
vi.mock( 'next/head', () => ( { default: () => null } ) );

const retired = [ '/release-check-missing-page', '/release-check-missing-page/nested' ];
beforeEach( () => router.replace.mockClear() );
afterEach( () => { cleanup(); window.history.replaceState( {}, '', '/' ); } );

describe( 'retired URLs use the single missing-page home fallback', () => {
  it.each( retired )( '%s uses home fallback, including slash and descendant forms', prefix => {
    for ( const suffix of [ '', '/', '/nested/?next=https://example.com' ] ) {
      window.history.replaceState( {}, '', prefix + suffix );
      const view = render( <NotFound /> );
      // Redirects to home. The page is now a PURE redirect (owner 2026-10-13): no visible 404
      // screen, no "This page is unavailable" copy and no CTA link - the body renders nothing
      // (the meta-refresh + canonical live in <Head>, which is mocked to null here). So the only
      // observable is the home redirect and the absence of any rendered content.
      expect( router.replace ).toHaveBeenLastCalledWith( '/' );
      expect( screen.queryByText( 'This page is unavailable.' ) ).toBeNull();
      expect( screen.queryByRole( 'link' ) ).toBeNull();
      view.unmount();
    }
  } );
  it.each( [ '/RELEASE-CHECK-MISSING-PAGE/', '/%72elease-check-missing-page/', '/release-check-missing-page%2Fnested/' ] )( 'also retires %s', path => {
    window.history.replaceState( {}, '', path );
    render( <NotFound /> );
    expect( router.replace ).toHaveBeenLastCalledWith( '/' );
  } );
  it.each( [ '/definitely-not-a-page/', '/tracking-unknown/', '/contact-unknown/' ] )(
    'uses the same home fallback for %s', path => {
      window.history.replaceState( {}, '', path );
      render( <NotFound /> );
      expect( router.replace ).toHaveBeenLastCalledWith( '/' );
    }
  );
} );
