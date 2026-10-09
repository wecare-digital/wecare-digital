import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';

/**
 * THE /vayulok PAGE MUST RENDER THE LIVE SECTION, AND MUST CARRY ONE main LANDMARK.
 *
 * src/components/VayuLokLive.tsx has been dropped from this page twice: d9e365ce replaced it
 * with the "Filling the Gap" globe, and the revert b1669cde removed the globe without restoring
 * the live section. That left the page's own doc comment and the .vl-shell CSS note describing
 * markup that was no longer rendered, and the component imported nowhere outside its own test.
 * Nothing in the suite noticed, because no test imported the page. This is that assertion.
 *
 * It runs on the KEYLESS path - NEXT_PUBLIC_GOOGLE_MAPS_KEY stubbed empty, which is also CI's
 * natural state - so no Maps JS is injected and no air/weather fetch is issued, and the test
 * needs neither a google stub nor a network stub. The keyless path still renders a
 * maps.google.com embed iframe where the interactive canvas would be; that is the component's
 * documented behaviour, asserted in VayuLokLive.test.tsx, and not what this file is about.
 */

// A fresh module graph AFTER the env stub: VayuLokLive and VayuLokApprovedGlobe both read the
// Maps key at module scope, so an instance cached by another test would hold the old value.
async function loadPage() {
  vi.resetModules();
  const mod = await import( '../pages/vayulok/index' );
  return mod.default;
}

beforeEach( () => {
  vi.stubEnv( 'NEXT_PUBLIC_GOOGLE_MAPS_KEY', '' );
} );

afterEach( () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
} );

describe( 'the /vayulok page keeps the live VayuLok section wired in', () => {
  it( 'renders VayuLokLive as a sibling below the hero', async () => {
    const VayuLokPage = await loadPage();
    const { container } = render( <VayuLokPage /> );
    await act( async () => { await Promise.resolve(); } );

    // The component's own root and the shell inside it. Both disappear together if the
    // import or the element is dropped again.
    const live = container.querySelector( 'section.vl-live' );
    expect( live ).not.toBeNull();
    expect( live?.querySelector( 'main.vl-live-shell' ) ).not.toBeNull();

    // BELOW the hero, not inside it. Nesting would put the component's main inside the
    // hero, which is the arrangement the page comment rules out.
    const hero = container.querySelector( '.vl-shell' ) as HTMLElement | null;
    expect( hero ).not.toBeNull();
    expect( hero?.contains( live as Node ) ).toBe( false );
    expect(
      ( hero as HTMLElement ).compareDocumentPosition( live as Node )
        & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  } );

  it( 'carries exactly one main landmark, the live one', async () => {
    const VayuLokPage = await loadPage();
    const { container } = render( <VayuLokPage /> );
    await act( async () => { await Promise.resolve(); } );

    // The hero is a section precisely so this stays at one: HTML permits a single
    // non-hidden main per document, and VayuLokLive owns it on this page.
    const mains = container.querySelectorAll( 'main' );
    expect( mains ).toHaveLength( 1 );
    expect( mains[ 0 ].className ).toContain( 'vl-live-shell' );
  } );
} );
