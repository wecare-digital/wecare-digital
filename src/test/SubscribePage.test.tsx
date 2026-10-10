import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import SubscribePage from '../pages/subscribe';
import { SUBSCRIBE, SUBSCRIBE_CTA_HREF, SUBSCRIBE_CTA_LABEL } from '../content/subscribe';
import { whatsappServiceLink } from '../config/whatsappServiceEntries';

/**
 * /subscribe - the Subscribe page, directly after Leave Review in the Request menu.
 *
 * WHAT THIS GUARDS.
 *   - One <h1> and one <main>, both from the shared RotatingHero (htmlcheck's H1-MANY and
 *     MANY-MAIN guard against a second of either), with the page's own badge and headline.
 *   - THE CTA OPENS WHATSAPP, on owner instruction (the official Meta message link
 *     wa.me/message/WUDPTMYSO6XII1), replacing the earlier contact-page destination now that
 *     Subscribe is a direct WhatsApp door. The pin on SUBSCRIBE_CTA_LABEL / SUBSCRIBE_CTA_HREF
 *     below is deliberate: if the destination changes again, update those two constants, the
 *     copy lines in src/content/subscribe.ts and this test together, on purpose.
 *   - THE PAGE STORES NOTHING AND SAYS SO: no form, no field and no button, so nothing on it can
 *     look like a working sign-up. The one anchor it does carry is the WhatsApp CTA.
 *   - The copy rules: no exclamation marks, no em or en dashes.
 *   - Chrome (Header, Footer, SupportWidget) is mounted once in _app.tsx; a page must not import it.
 *
 * next/head is a no-op in jsdom, so PageMeta renders nothing observable here.
 */
describe( 'Subscribe page', () => {
  it( 'owns a single h1 and a single main through the shared hero', () => {
    const { container } = render( <SubscribePage /> );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
  } );

  it( 'carries the Subscribe identity on the animated hero', () => {
    const { container } = render( <SubscribePage /> );
    expect( screen.getByText( 'Subscribe by WECARE.DIGITAL' ) ).toBeInTheDocument();
    expect( container.querySelector( 'h1' )?.textContent ).toContain( 'Get our' );

    const words = Array.from( container.querySelectorAll( '.rh-cyc-word' ) ).map( w => w.textContent );
    expect( words ).toEqual( [ 'updates', 'news', 'posts', 'notices' ] );
    // The pill animates to each word's measured width, so keep every word short.
    for ( const word of words ) expect( ( word || '' ).length ).toBeLessThanOrEqual( 18 );
  } );

  it( 'sends the primary CTA into WhatsApp via the official Meta message link', () => {
    render( <SubscribePage /> );
    expect( SUBSCRIBE_CTA_LABEL ).toBe( 'Open WhatsApp' );
    expect( SUBSCRIBE_CTA_HREF ).toBe( 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( screen.getByRole( 'link', { name: SUBSCRIBE_CTA_LABEL } ) )
      .toHaveAttribute( 'href', 'https://wa.me/message/WUDPTMYSO6XII1' );
  } );

  it( 'resolves its WhatsApp service entry to the same Meta message link the CTA uses', () => {
    // ProductPage uses whatsappServiceLink( slug ) || ctaHref. Subscribe now HAS an entry, so the
    // config link must match the content href or the rendered CTA would silently diverge.
    expect( whatsappServiceLink( SUBSCRIBE.slug ) ).toBe( SUBSCRIBE_CTA_HREF );
  } );

  it( 'has no form, field or button, so nothing looks like an on-page sign-up', () => {
    const { container } = render( <SubscribePage /> );
    expect( container.querySelectorAll( 'form, input, textarea, select, button' ) ).toHaveLength( 0 );
    // The ONE anchor the page carries is the WhatsApp CTA, and it points at the Meta message link.
    const waLinks = container.querySelectorAll( 'a[href*="wa.me"]' );
    expect( waLinks ).toHaveLength( 1 );
    expect( waLinks[ 0 ] ).toHaveAttribute( 'href', 'https://wa.me/message/WUDPTMYSO6XII1' );
    expect( container.querySelectorAll( 'a[href^="mailto:"]' ) ).toHaveLength( 0 );
  } );

  it( 'says plainly to open WhatsApp to subscribe and that nothing on the page is stored', () => {
    const { container } = render( <SubscribePage /> );
    expect( container.textContent ).toMatch( /whatsapp/i );
    expect( container.textContent ).toMatch( /nothing you do on this page is stored/i );
  } );

  it( 'keeps to the site tone: no exclamation marks, no em or en dashes', () => {
    const strings: string[] = [
      SUBSCRIBE.title, SUBSCRIBE.description, SUBSCRIBE.blurb, SUBSCRIBE.frame, SUBSCRIBE.sub,
      SUBSCRIBE.sectionHeading, SUBSCRIBE.lead, SUBSCRIBE.note || '', SUBSCRIBE.ctaLabel,
      ...SUBSCRIBE.words.map( w => w.word ),
      ...SUBSCRIBE.points.flatMap( p => [ p.heading, p.body ] ),
    ];
    for ( const text of strings )
    {
      expect( text, text ).not.toContain( '!' );
      expect( text, text ).not.toContain( '\u2014' );
      expect( text, text ).not.toContain( '\u2013' );
    }
  } );

  it( 'owns the route without importing chrome, which _app.tsx mounts centrally', () => {
    const src = readFileSync( join( process.cwd(), 'src/pages/subscribe.tsx' ), 'utf8' );
    expect( src ).not.toMatch( /components\/(Header|Footer|SupportWidget|Layout)'/ );
    expect( src ).toContain( "from '../components/ProductPage'" );
  } );
} );
