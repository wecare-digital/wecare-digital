import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import ShipmentsPage from '../pages/shipments';
import { SHIPMENTS } from '../content/shipments';
import { whatsappServiceLink } from '../config/whatsappServiceEntries';

/**
 * /shipments - the Shipments page, in the Request menu.
 *
 * THE PAGE WAS CALLED "ZIP"; the name is gone on owner instruction (2026-10-02). The route is
 * /shipments/, the badge carries the full house form "Shipments by WECARE.DIGITAL", and no
 * user-visible "Zip" survives. The retired-name assertion below guards that it cannot creep back.
 *
 * WHAT THIS GUARDS. Shipments now follows the SAME thin shape as every other request page
 * (/drop-docs/, /subscribe/): a route file that renders the shared ProductPage over a ProductDef,
 * so the hero is the shared RotatingHero and the page cannot drift from its siblings. The one
 * thing it adds is a SECOND CTA, so these assertions pin:
 *   - one <h1> and one <main>, both from the shared hero (htmlcheck's H1-MANY / MANY-MAIN);
 *   - the full "Shipments by WECARE.DIGITAL" badge and the owner's lead;
 *   - the cycle words the content file sets, in order;
 *   - BOTH CTAs render with their exact hrefs, and CTA 2 (pickup) does NOT resolve through the
 *     slug's WhatsApp entry — that entry is the TRACKING link, so routing pickup through it would
 *     open the wrong conversation;
 *   - exactly two wa.me anchors and no form / field / button, so nothing looks like an on-page
 *     booking;
 *   - the copy rules: no exclamation marks, no em or en dashes;
 *   - chrome (Header, Footer, SupportWidget) is mounted once in _app.tsx; a page must not import it.
 *
 * next/head is a no-op in jsdom, so PageMeta renders nothing observable here.
 */
describe( 'Shipments page', () => {
  it( 'owns a single h1 and a single main through the shared hero', () => {
    const { container } = render( <ShipmentsPage /> );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
  } );

  it( 'carries the Shipments identity and the owner lead on the animated hero', () => {
    const { container } = render( <ShipmentsPage /> );
    const h1 = container.querySelector( 'h1' );
    expect( h1?.textContent ).toContain( 'Everything about your' );
    // THE FULL HOUSE FORM in the brand badge, asserted whole rather than as a substring, because a
    // bare "Shipments" badge is exactly the bug the owner reported.
    expect( screen.getByText( 'Shipments by WECARE.DIGITAL' ) ).toBeInTheDocument();
    // The retired name must never come back on the page.
    expect( container.textContent ).not.toMatch( /\bZip\b/i );
    // The mandated lead.
    expect( screen.getByText( 'Track it. Arrange it. Keep it moving.' ) ).toBeInTheDocument();
    // The rotation words the content file sets, in order. The screen-reader copy lists them once;
    // the animated copies are aria-hidden.
    const words = Array.from( container.querySelectorAll( '.rh-cyc-word' ) ).map( w => w.textContent );
    expect( words ).toEqual( [ 'order', 'request', 'pickup', 'parcel' ] );
    for ( const word of words ) expect( ( word || '' ).length ).toBeLessThanOrEqual( 18 );
  } );

  it( 'renders the three points from the content file', () => {
    render( <ShipmentsPage /> );
    for ( const point of SHIPMENTS.points )
    {
      expect( screen.getByRole( 'heading', { name: point.heading } ) ).toBeInTheDocument();
    }
  } );

  it( 'sends both CTAs into WhatsApp via the owner Meta message links', () => {
    render( <ShipmentsPage /> );
    // CTA 1 - tracking.
    expect( SHIPMENTS.ctaLabel ).toBe( 'Shipments tracking' );
    expect( SHIPMENTS.ctaHref ).toBe( 'https://wa.me/message/WGN4NMFLFSJVB1' );
    expect( screen.getByRole( 'link', { name: SHIPMENTS.ctaLabel } ) )
      .toHaveAttribute( 'href', 'https://wa.me/message/WGN4NMFLFSJVB1' );
    // CTA 2 - pickup.
    expect( SHIPMENTS.ctaLabel2 ).toBe( 'Request pickup' );
    expect( SHIPMENTS.ctaHref2 ).toBe( 'https://wa.me/message/NRWQFXOPGL7OO1' );
    expect( screen.getByRole( 'link', { name: SHIPMENTS.ctaLabel2! } ) )
      .toHaveAttribute( 'href', 'https://wa.me/message/NRWQFXOPGL7OO1' );
  } );

  it( 'resolves CTA 1 through the slug WhatsApp entry but keeps CTA 2 literal', () => {
    // ProductPage renders CTA 1 as whatsappServiceLink( slug ) || ctaHref. The slug HAS an entry,
    // so the config link must equal the tracking href or the rendered button would silently
    // diverge. CTA 2 must NOT equal that entry: the entry is the tracking link, and routing the
    // pickup button through it would open the tracking conversation.
    expect( whatsappServiceLink( SHIPMENTS.slug ) ).toBe( SHIPMENTS.ctaHref );
    expect( SHIPMENTS.ctaHref2 ).not.toBe( whatsappServiceLink( SHIPMENTS.slug ) );
  } );

  it( 'carries exactly two wa.me anchors and no form, field or button', () => {
    const { container } = render( <ShipmentsPage /> );
    const waLinks = Array.from( container.querySelectorAll( 'a[href*="wa.me"]' ) );
    expect( waLinks ).toHaveLength( 2 );
    // In document order: tracking first, pickup second.
    expect( waLinks[ 0 ] ).toHaveAttribute( 'href', 'https://wa.me/message/WGN4NMFLFSJVB1' );
    expect( waLinks[ 1 ] ).toHaveAttribute( 'href', 'https://wa.me/message/NRWQFXOPGL7OO1' );
    // Shipments signposts and hands off to WhatsApp; it never transacts on the page.
    expect( container.querySelectorAll( 'form, input, textarea, select, button' ) ).toHaveLength( 0 );
    expect( container.querySelectorAll( 'a[href^="mailto:"]' ) ).toHaveLength( 0 );
  } );

  it( 'surfaces no transacting control or price', () => {
    const { container } = render( <ShipmentsPage /> );
    const text = ( container.textContent || '' ).toLowerCase();
    expect( text ).not.toContain( 'add to cart' );
    expect( text ).not.toContain( 'pay now' );
    expect( text ).not.toContain( '\u20b9' );
  } );

  it( 'keeps to the site tone: no exclamation marks, no em or en dashes', () => {
    const strings: string[] = [
      SHIPMENTS.title, SHIPMENTS.description, SHIPMENTS.blurb, SHIPMENTS.frame, SHIPMENTS.sub,
      SHIPMENTS.sectionHeading, SHIPMENTS.lead, SHIPMENTS.note || '',
      SHIPMENTS.ctaLabel, SHIPMENTS.ctaLabel2 || '',
      ...SHIPMENTS.words.map( w => w.word ),
      ...SHIPMENTS.points.flatMap( p => [ p.heading, p.body ] ),
    ];
    for ( const text of strings )
    {
      expect( text, text ).not.toContain( '!' );
      expect( text, text ).not.toContain( '\u2014' );
      expect( text, text ).not.toContain( '\u2013' );
    }
  } );

  it( 'owns the route without importing chrome, which _app.tsx mounts centrally', () => {
    const src = readFileSync( join( process.cwd(), 'src/pages/shipments.tsx' ), 'utf8' );
    expect( src ).not.toMatch( /components\/(Header|Footer|SupportWidget|Layout)'/ );
    expect( src ).toContain( "from '../components/ProductPage'" );
  } );

  it( 'keeps the PUBLIC_PAGE_META description in step with the content file', () => {
    // The /shipments description is written as a LITERAL in _app.tsx because
    // scripts/generate-public-pages.js parses that map statically and refuses a non-literal
    // value. That literal is config/public-pages.json's and the WebPage schema's source, while
    // SHIPMENTS.description is the page <head>'s source, so the two must say the same thing. This
    // assertion is what pins them - the same drift guard the CTA-1 href has above.
    const app = readFileSync( join( process.cwd(), 'src/pages/_app.tsx' ), 'utf8' );
    expect( app ).toContain( SHIPMENTS.description );
  } );
} );
