/**
 * The command palette must not drift from the sidebar again.
 *
 * It had its own hardcoded list of 14 entries against 88 real destinations, and
 * 8 of the 14 were WhatsApp sub-pages - so Ctrl+K could not find the unified
 * inbox, SMS, RCS, email, channel settings or the operator's own MFA page. That
 * matters more than it looks: the owner wants the sidebar reduced to Inbox and
 * Contacts, which DELETES the sidebar search box that currently does this job. The
 * palette has to be able to reach everything before that happens, not after.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';

const push = vi.fn();
vi.mock( 'next/router', () => ( {
  useRouter: () => ( { push, pathname: '/workspace/dashboard' } ),
} ) );

import SearchModal from '../components/SearchModal';
import { getAllNavItems } from '../config/navigation';

describe( 'SearchModal is derived from navigation.ts', () => {
  const src = fs.readFileSync(
    path.resolve( __dirname, '../components/SearchModal.tsx' ), 'utf8' );

  it( 'builds its page list from getAllNavItems, not a hand-written array', () => {
    expect( src ).toContain( 'getAllNavItems' );
    // The old hardcoded entries must be gone, or the two lists drift again.
    expect( src ).not.toContain( "id: 'nav-dashboard'" );
    expect( src ).not.toContain( "id: 'nav-cost-controls'" );
  } );

  it( 'knows about far more than the 14 it used to', () => {
    expect( getAllNavItems().length ).toBeGreaterThan( 80 );
  } );

  it( 'uses stable empty defaults, so typing cannot loop the renderer', () => {
    // `contacts = []` inline built a new array every render, and both arrays are
    // in the search effect's dep list - so the deps never compared equal, the
    // effect re-ran on every render, setResults re-rendered, and typing one
    // character span forever. The test that types into the palette HUNG until
    // this was fixed; this assertion exists so the next regression fails with a
    // readable message instead of a timeout.
    expect( src ).toContain( 'NO_CONTACTS' );
    expect( src ).toContain( 'NO_MESSAGES' );
    // Comments stripped first. The block above explaining the fix contains the
    // very pattern being banned, and reporting the record of a fix as the defect
    // is a mistake check_design_drift.py already had to be taught to avoid - it
    // caught this test out on its first run too.
    const code = src
      .replace( /\/\*[\s\S]*?\*\//g, '' )
      .replace( /^\s*\/\/.*$/gm, '' );
    expect( code ).not.toMatch( /contacts\s*=\s*\[\s*\]/ );
    expect( code ).not.toMatch( /messages\s*=\s*\[\s*\]/ );
  } );

  it( 'does not promise search it cannot perform', () => {
    // Layout renders this with neither `contacts` nor `messages`, so the old
    // "Search contacts, messages, pages..." placeholder advertised two
    // capabilities that could never fire.
    expect( src ).toContain( 'Search pages' );
    expect( src ).not.toContain( 'Search contacts, messages, pages' );
  } );

  it( 'can find the destinations the old list could not', () => {
    const paths = getAllNavItems().map( ( i ) => i.path );
    // '/workspace/seo/sitemaps' was the seventh entry here until 2026-10-07. It went
    // because the DESTINATION went, not because the palette regressed: that page reads
    // through seoFetch, which throws when NEXT_PUBLIC_SEO_API_URL is unset, and the
    // variable is absent from the stack environment — so the nav entry led to a thrown
    // error. The other six are unchanged and the assertion is still an exact
    // `toContain` per path rather than a substring match, because the whole point of
    // this test is that a specific destination is reachable by name.
    for ( const p of [ '/workspace/engage/inbox', '/workspace/engage/sms', '/workspace/engage/rcs', '/workspace/engage/ses',
      '/workspace/engage/settings', '/workspace/access/security' ] )
    {
      expect( paths ).toContain( p );
    }
  } );
} );

describe( 'SearchModal behaviour', () => {
  it( 'renders nothing when closed', () => {
    const { container } = render(
      <SearchModal isOpen={ false } onClose={ () => undefined } /> );
    expect( container.firstChild ).toBeNull();
  } );

  it( 'offers the inbox before anything is typed', () => {
    render( <SearchModal isOpen onClose={ () => undefined } /> );
    // Label is 'Inbox' since the nav restructure; it was 'Unified Inbox' when the
    // sidebar still had a separate page per channel to be unified against.
    expect( screen.getAllByText( /Inbox/ ).length ).toBeGreaterThan( 0 );
  } );

  it( 'finds a page the hardcoded list had no entry for', () => {
    // The example was 'sitemap' -> /Sitemaps/ until 2026-10-07, when that gear entry
    // was removed because its page throws without NEXT_PUBLIC_SEO_API_URL. The test's
    // intent is unchanged and so is its strength: /workspace/dashboard/cors-settings
    // was ALSO absent from the old hardcoded 14 — Navigation.test.tsx names it under
    // 'picked up routes that were orphaned before the restructure' — so it is the same
    // claim about the same kind of destination. SearchModal matches on the nav label
    // (SearchModal.tsx:105), and the label is 'CORS Settings'.
    render( <SearchModal isOpen onClose={ () => undefined } /> );
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'cors' } } );
    expect( screen.getByText( /CORS Settings/i ) ).toBeInTheDocument();
  } );

  it( 'disambiguates same-named pages by their parent section', () => {
    // More than one entry is called "Inbox" - the sidebar stream and the WhatsApp
    // settings page. Without the parent as a subtitle they are indistinguishable in
    // a flat result list, which is why getAllNavItems carries `parent`.
    const inboxes = getAllNavItems().filter( ( i ) => /inbox/i.test( i.label ) );
    expect( inboxes.length ).toBeGreaterThan( 1 );
    expect( inboxes.some( ( i ) => !!i.parent ) ).toBe( true );
    render( <SearchModal isOpen onClose={ () => undefined } /> );
    fireEvent.change( screen.getByRole( 'combobox' ), { target: { value: 'inbox' } } );
    expect( screen.getAllByText( /Inbox/ ).length ).toBeGreaterThan( 0 );
  } );
} );
