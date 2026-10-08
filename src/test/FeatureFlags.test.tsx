/**
 * Phase 7.3 — the flags, and the two module homes they gate.
 *
 * The property that matters most is the DEFAULT. A flag that defaults ON means a missing
 * env var in a new environment silently enables the thing the flag was protecting, which
 * is the opposite of what a safety switch is for. This project already has the inverse
 * lesson written down for `WA_LIVE_SMOKE_TEST`, where switching the flag ON *narrows*
 * sending — absence should fail toward the safe state too.
 *
 * The second property: a flagged-off page must explain itself rather than render a shell
 * of empty panels. An empty chart is indistinguishable from a chart showing zero, and
 * that ambiguity is the defect this whole phase has been removing.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';

vi.mock( 'next/router', () => ( {
  useRouter: () => ( { pathname: '/workspace/commerce', query: {}, push: vi.fn(), isReady: true } ),
} ) );

import { featureFlags, allFlags } from '../config/featureFlags';
import CommercePage from '../pages/workspace/commerce/index';
import inventory from '../content/integration-registry.json';
import { moduleHomes, getAllNavItems } from '../config/navigation';

const FLAGS_SRC = fs.readFileSync(
  path.resolve( __dirname, '../config/featureFlags.ts' ), 'utf8' );

describe( 'flags default OFF', () => {
  it( 'every flag is false with no env var set', () => {
    for ( const { name, enabled } of allFlags() ) {
      expect( enabled, `${name} must default to false` ).toBe( false );
    }
  } );

  it( 'only an explicit truthy string turns one on', () => {
    // Not a value test on the live flags — a test on the parser, so a future flag
    // cannot be added with looser semantics.
    expect( FLAGS_SRC ).toContain( "[ '1', 'true', 'yes', 'on' ].includes" );
  } );

  it( 'no flag here could be mistaken for a send flag', () => {
    const names = allFlags().map( ( f ) => f.name.toLowerCase() ).join( ' ' );
    for ( const banned of [ 'send', 'live', 'smoke', 'apply', 'routing' ] ) {
      expect( names ).not.toContain( banned );
    }
  } );

  it( 'says plainly that these gate a read-only surface', () => {
    expect( FLAGS_SRC ).toContain( 'read-only UI surface' );
    expect( FLAGS_SRC ).toContain( 'governance.py' );
  } );
} );

// The three 'Growth home with the flag off' tests that sat here were removed on
// 2026-09-25 with /growth/index.tsx and the `growthModule` flag, on owner instruction.
// They asserted that the page explained why it was off, that it still showed real
// three-state connection data, and that provider names stayed out of the page name and
// tab labels. Every one of those properties is still asserted below against Commerce,
// which is the same shape and is still shipped — so the behaviour these tests protected
// is not now unguarded. What is gone is the page, not the rule.

describe( 'the Commerce home with the flag off', () => {
  it( 'explains why it is off instead of showing empty panels', () => {
    expect( featureFlags.commerceModule ).toBe( false );
    render( <CommercePage embedded /> );
    expect( screen.getByText( /Commerce module is switched off/i ) ).toBeTruthy();
    // Off because the storefront is LIVE, not because it is unfinished.
    expect( screen.getByText( /Not because it is unfinished/i ) ).toBeTruthy();
  } );

  // Moved here from the deleted Growth block rather than dropped with it. Both module
  // homes render the same shell over the same IntegrationAccessTable, so these two
  // properties were never really about Growth — they are about how a flagged-off module
  // home is allowed to behave, and that rule outlived the page.
  it( 'still shows the real connection state, which is the useful part', () => {
    render( <CommercePage embedded /> );
    // Three-state, from the generated registry snapshot — not a tick.
    expect( screen.getAllByText( /Not verified|Not connected/ ).length ).toBeGreaterThan( 0 );
  } );

  it( 'keeps provider names out of the page name and the tab labels', () => {
    render( <CommercePage embedded /> );
    // The master prompt: "Use provider-neutral page names and confine exact provider
    // labels/IDs to authorized connection details." So the page is "Commerce" and the
    // tabs are neutral — while "Wix" DOES appear inside the connection table, which is
    // the authorised place for it.
    expect( screen.getByText( 'Commerce' ) ).toBeTruthy();
    for ( const tab of [ 'Connections', 'Catalog & orders', 'Payments' ] ) {
      expect( screen.getByText( tab ) ).toBeTruthy();
    }
    for ( const provider of [ 'Wix', 'Razorpay', 'Google Ads', 'Meta' ] ) {
      expect( screen.queryByRole( 'tab', { name: new RegExp( provider, 'i' ) } ) ).toBeNull();
    }
  } );
} );

describe( 'the registry snapshot is real and honest', () => {
  it( 'has all eight providers', () => {
    expect( inventory.providers ).toHaveLength( 8 );
  } );

  it( 'claims nothing as VERIFIED, because nothing has been', () => {
    const verified = inventory.providers.filter(
      ( p: any ) => p.access === 'VERIFIED' );
    expect( verified ).toHaveLength( 0 );
  } );

  it( 'distinguishes a missing credential from an unverified scope', () => {
    const states = new Set( inventory.providers.map( ( p: any ) => p.access ) );
    expect( states.has( 'SCOPE_UNVERIFIED' ) ).toBe( true );
    expect( states.has( 'CREDENTIAL_ABSENT' ) ).toBe( true );
  } );

  it( 'carries an unblock for every provider that is not connected', () => {
    for ( const p of inventory.providers as any[] ) {
      if ( p.access === 'VERIFIED' ) continue;
      expect( p.unblock, `${p.key} has no unblock` ).toBeTruthy();
    }
  } );

  it( 'is timestamped, so a stale snapshot is visible', () => {
    expect( inventory.generatedAt ).toMatch( /^\d{4}-\d{2}-\d{2}T/ );
  } );
} );

describe( 'the Commerce home is reachable', () => {
  // Was 'both homes are reachable' and asserted on Growth alongside Commerce. /growth was
  // deleted 2026-09-25 on owner instruction, so the assertions that named it are gone.
  it( 'is declared as a module home at its own route', () => {
    const commerce = moduleHomes.find( ( m ) => m.id === 'commerce' );
    expect( commerce?.path ).toBe( '/workspace/commerce' );
  } );

  it( 'appears in the navigation the command palette is built from', () => {
    const paths = getAllNavItems().map( ( i ) => i.path );
    // A flagged-off page that explains itself beats a 404, so it stays findable.
    expect( paths ).toContain( '/workspace/commerce' );
  } );

  // The other half of the same property, and the reason this file did not just lose a
  // test: a route that no longer exists must not still be advertised in the nav, or the
  // command palette offers an entry that lands on the home-page fallback.
  it( 'no longer advertises the routes whose pages were deleted', () => {
    const paths = getAllNavItems().map( ( i ) => i.path );
    const gonePaths = [
      '/growth', '/carbon', '/nocode', '/workspace/forms/create', '/workspace/link/create',
      // The eight SEO screens retired on 2026-10-07 under owner decision B1 = CUT. Every
      // one of them read from the `wecare-seo-platform` FastAPI service through
      // `seoFetch`, which threw because `NEXT_PUBLIC_SEO_API_URL` is unset on `stack`.
      // Listed here because this assertion is the one that catches the specific mistake
      // of removing a page file while leaving its nav entry or hub tile pointing at it.
      '/workspace/seo/page', '/workspace/seo/pages', '/workspace/seo/issues',
      '/workspace/seo/analytics', '/workspace/seo/tracking', '/workspace/seo/schema',
      '/workspace/seo/properties', '/workspace/seo/sitemaps',
    ];
    for ( const gone of gonePaths ) {
      expect( paths, `${gone} was deleted but is still in the nav` ).not.toContain( gone );
    }
  } );
} );
