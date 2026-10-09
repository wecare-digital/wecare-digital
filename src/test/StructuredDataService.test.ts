/**
 * The per-page Service entity: which routes declare what they are about, and which must not.
 *
 * A WebPage node says "this URL exists". It does not say what the page is ABOUT. Before this,
 * all 23 public routes emitted WebPage + BreadcrumbList and nothing else, so a crawler could
 * learn that a page called Dastavez exists without learning that Dastavez is business
 * documentation offered in India by this organisation. `serviceType` in PUBLIC_PAGE_META is what
 * closes that, and getPublicPageSchema turns it into a schema.org Service with the WebPage
 * pointing at it through mainEntity.
 *
 * THE ABSENCES ARE THE POINT OF THIS FILE. It would be easy, and wrong, to type every public
 * route as a Service to get a richer graph. /leave-review is not an offering; /terms is not a
 * product. Those are page kinds and ways to interact with us, and describing them as services
 * would be describing a site we do not have. A test that only checked the positives would let
 * that happen on the next edit, so the negatives are asserted just as hard.
 *
 * READ AS TEXT, like PublicAiSurface.test.ts and scripts/generate-public-pages.js do, and for the
 * same reason: _app.tsx runs Amplify.configure at module scope, so importing it here to read two
 * literals would boot the SDK.
 */
import { describe, expect, it } from 'vitest';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve( __dirname, '..', '..' );
const APP = fs.readFileSync( path.join( ROOT, 'src', 'pages', '_app.tsx' ), 'utf8' );

/** The PUBLIC_PAGE_META block, without the prose above it. */
const metaBlock = (): string => {
  const start = APP.indexOf( 'const PUBLIC_PAGE_META' );
  expect( start, 'PUBLIC_PAGE_META not found - this guard needs updating' ).toBeGreaterThan( -1 );
  const end = APP.indexOf( '\nconst ', start + 10 );
  return APP.slice( start, end === -1 ? undefined : end );
};

/** route -> serviceType for every entry that declares one. */
const declared = (): Map<string, string> => {
  const found = new Map<string, string>();
  const line = /^\s*'(\/[a-z0-9-]+)'\s*:\s*\{[^}]*?serviceType:\s*'((?:[^'\\]|\\.)*)'/gm;
  for ( const match of metaBlock().matchAll( line ) ) found.set( match[ 1 ], match[ 2 ] );
  return found;
};

/** Every route PUBLIC_PAGE_META lists, with or without a serviceType. */
const allRoutes = (): string[] => {
  const found: string[] = [];
  const line = /^\s*'(\/[a-z0-9-]+)'\s*:\s*\{\s*name:/gm;
  for ( const match of metaBlock().matchAll( line ) ) found.push( match[ 1 ] );
  return found;
};

/**
 * The eleven products and platform services, written out rather than derived.
 *
 * Deriving this from the file would make the test a tautology - it would agree with whatever
 * _app.tsx said, including a mistake. Written out, adding a twelfth is a deliberate decision
 * about whether the new page really is an offering.
 */
const OFFERINGS = [
  '/anew', '/bharat-rx', '/clear-closure', '/dastavez', '/elsewhere', '/expo-week',
  '/grahak-os', '/hunar', '/niji-setu', '/ritual-guru', '/vayulok',
];

/**
 * Ways to interact with us, and page kinds. Neither is a thing we sell.
 *
 * '/shop' WAS IN THIS LIST AND WAS REMOVED ON 2026-10-04. It was the interesting entry - the page
 * most obviously about things that are sold, classified here because it was a LIST of them rather
 * than one of them. The owner then withdrew the catalogue index entirely: it 301s to the home page
 * and its page file is deleted, so the route no longer exists and this is no longer a claim about
 * anything. Leaving it would not have failed - `covers every route` only requires
 * allRoutes() to be a subset of OFFERINGS plus NOT_OFFERINGS - which is exactly why it had to be
 * removed deliberately rather than being caught by a gate.
 *
 * The seven PRODUCT pages were never classified here and still are not: they are the dynamic route
 * '/shop/[slug]' and each emits its own schema.org Product with an Offer - price, currency and
 * availability - through components/ShopProductHead.tsx.
 */
const NOT_OFFERINGS = [
  '/submit-request', '/request-amendment', '/drop-docs', '/vault', '/leave-review',
  '/refer-and-earn',
  '/terms', '/privacy', '/contact', '/orders',
  // Shipments is a hub that signposts the request actions, and Perks is a quiet landing page for
  // the small thank-yous we send - neither is a thing we sell, and both render their non-backed
  // controls as non-transacting. A Service node would describe a site we do not have. (The former
  // gift-card / offers / rewards sections on Perks were removed on owner instruction, so Perks no
  // longer "gathers" anything; and the Shipments route moved from /zip/ on 2026-10-02.)
  '/shipments', '/perks',
  // Subscribe is a way to contact us (its CTA is /contact/), not something we sell.
  '/subscribe',
];

describe( 'per-page Service structured data', () => {
  it( 'declares a serviceType on exactly the eleven offerings', () => {
    expect( [ ...declared().keys() ].sort() ).toEqual( [ ...OFFERINGS ].sort() );
  } );

  it( 'declares none on the Requests pages or the page kinds', () => {
    const have = declared();
    for ( const route of NOT_OFFERINGS ) {
      expect( have.has( route ), `${route} must not be typed as a Service - it is not an offering` )
        .toBe( false );
    }
  } );

  it( 'covers every route in PUBLIC_PAGE_META by one list or the other', () => {
    // So a route added later cannot quietly avoid the decision this file exists to force.
    const known = new Set( [ ...OFFERINGS, ...NOT_OFFERINGS ] );
    const unclassified = allRoutes().filter( route => !known.has( route ) );
    expect( unclassified, 'new public route(s): decide whether each is an offering and add them '
      + 'to OFFERINGS or NOT_OFFERINGS in this file' ).toEqual( [] );
  } );

  it( 'gives every serviceType real prose rather than echoing the page name', () => {
    for ( const [ route, serviceType ] of declared() ) {
      expect( serviceType.length, `${route} serviceType is too short to say anything` )
        .toBeGreaterThan( 12 );
      // "Hunar" as a serviceType tells a crawler nothing it did not already have from `name`.
      const name = new RegExp( `'${route}':\\s*\\{\\s*name:\\s*'([^']+)'` ).exec( metaBlock() );
      if ( name ) expect( serviceType.toLowerCase() ).not.toBe( name[ 1 ].toLowerCase() );
    }
  } );

  it( 'builds the Service node by reference, not by restating the Organization', () => {
    /*
     * provider must be an @id reference. An inline copy of the company's name, logo and address
     * on eleven pages is eleven more places for it to drift from websiteSchema's one copy, and
     * Google resolves @id references within the same page - so the reference costs nothing.
     */
    const fn = APP.slice( APP.indexOf( 'const getPublicPageSchema' ) );
    const body = fn.slice( 0, fn.indexOf( '\n};' ) );
    expect( body ).toContain( "'@type': 'Service'" );
    expect( body ).toContain( "provider: { '@id': `${SITE}/#organization` }" );
    // Per-route @id, or two pages would define one node - the cross-route collision the
    // fallback branch above it already documents.
    expect( body ).toContain( "'@id': `${url}#service`" );
    expect( body ).toContain( "mainEntity: { '@id': `${url}#service` }" );
    // areaServed is where the service is offered. Elsewhere arranges travel abroad and is
    // still offered to people in India.
    expect( body ).toContain( "areaServed: { '@type': 'Country', name: 'India' }" );
  } );

  it( 'emits nothing extra on a route with no serviceType', () => {
    // The Service is appended by a filtered spread rather than pushed conditionally, so the
    // routes without one emit exactly the two nodes they emitted before, in the same order.
    const fn = APP.slice( APP.indexOf( 'const getPublicPageSchema' ) );
    const body = fn.slice( 0, fn.indexOf( '\n};' ) );
    expect( body ).toContain( '...( service ? [ service ] : [] )' );
    expect( body ).toContain( "...( service ? { mainEntity: { '@id': `${url}#service` } } : {} )" );
  } );
} );
