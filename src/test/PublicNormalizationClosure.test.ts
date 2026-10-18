import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { EMBEDDED_POLICY_ROUTES, publicPolicyDetailsForRoute } from '../content/publicPolicyDetails';

const ROOT = process.cwd();
const APP = path.join( ROOT, 'src/pages/_app.tsx' );
const PAGES = path.join( ROOT, 'src/pages' );
const read = ( relative: string ): string =>
  fs.readFileSync( path.join( ROOT, relative ), 'utf8' );

const CANONICAL_PUBLIC = [
  '/', '/contact', '/blog', '/shop', '/orders', '/grahak-os', '/vayulok', '/bharat-rx',
  '/elsewhere/visa', '/elsewhere/trip', '/elsewhere/activities',
  '/dastavez/drafting', '/dastavez/registration', '/dastavez/legal-reference',
  '/ritual-guru/ritva', '/ritual-guru/puja-guidance', '/ritual-guru/diy-puja-kit',
  '/hunar/kaushal', '/hunar/prastuti', '/shipments/track', '/expo-week', '/anew',
  '/niji-setu', '/submit-request', '/request-amendment', '/drop-docs', '/vault',
  '/request-pickup', '/leave-review', '/privacy', '/terms',
] as const;

const SHARED_PUBLIC_FAMILIES = [
  '/post/[slug]',
  '/blog/page/[page]',
  '/blog/topic/[topic]',
  '/blog/topic/[topic]/page/[page]',
  '/shop/page/[page]',
  '/shop/[slug]',
  '/account/sign-in',
  '/cart',
  '/checkout/status',
  '/checkout/success',
  '/get',
] as const;

const app = fs.readFileSync( APP, 'utf8' );

const readPublicAllowlist = (): string[] => {
  const metaStart = app.indexOf( 'const PUBLIC_PAGE_META' );
  const metaEnd = app.indexOf( '\nconst ', metaStart + 10 );
  expect( metaStart ).toBeGreaterThan( -1 );
  expect( metaEnd ).toBeGreaterThan( metaStart );
  const metaRoutes = Array.from(
    app.slice( metaStart, metaEnd )
      .matchAll( /^\s*'(\/[a-z0-9-]+(?:\/[a-z0-9-]+)*)'\s*:/gm )
  ).map( match => match[ 1 ] );

  const contentStart = app.indexOf( 'const isContentPublic' );
  const contentEnd = app.indexOf( 'const isPublic', contentStart );
  expect( contentStart ).toBeGreaterThan( -1 );
  expect( contentEnd ).toBeGreaterThan( contentStart );
  const contentRoutes = Array.from(
    app.slice( contentStart, contentEnd ).matchAll( /router\.pathname === '([^']+)'/g )
  ).map( match => match[ 1 ] );

  const publicStart = app.indexOf( 'const isPublic', contentEnd );
  const publicEnd = app.indexOf( 'const canonicalUrl', publicStart );
  expect( publicStart ).toBeGreaterThan( -1 );
  expect( publicEnd ).toBeGreaterThan( publicStart );
  const literalRoutes = Array.from(
    app.slice( publicStart, publicEnd ).matchAll( /router\.pathname === '([^']+)'/g )
  ).map( match => match[ 1 ] );

  return [ ...new Set( [ ...metaRoutes, ...contentRoutes, ...literalRoutes ] ) ].sort();
};

const walkTsx = ( dir: string ): string[] => {
  const found: string[] = [];
  for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
    const full = path.join( dir, entry.name );
    if ( entry.isDirectory() ) found.push( ...walkTsx( full ) );
    else if ( entry.name.endsWith( '.tsx' ) ) found.push( full );
  }
  return found;
};

describe( 'Step 7 public normalization closure', () => {
  it( 'pins the 31 canonical public routes', () => {
    expect( CANONICAL_PUBLIC ).toHaveLength( 31 );
    expect( new Set( CANONICAL_PUBLIC ).size ).toBe( 31 );
  } );

  it( 'pins the exact public HTML allowlist, including shared families and customer-session surfaces', () => {
    const expected = [
      ...CANONICAL_PUBLIC,
      ...SHARED_PUBLIC_FAMILIES,
      '/404',
    ].sort();

    expect( readPublicAllowlist() ).toEqual( expected );
  } );

  it( 'keeps machine, secure-delivery and protected namespaces outside the public HTML shell', () => {
    const allowlist = readPublicAllowlist();

    for ( const route of allowlist ) {
      expect( route, route ).not.toMatch( /^\/api(?:\/|$)/ );
      expect( route, route ).not.toMatch( /^\/workspace(?:\/|$)/ );
      expect( route, route ).not.toMatch( /^\/r(?:\/|$)/ );
      expect( route, route ).not.toMatch( /^\/get\// );
      expect( route, route ).not.toBe( '/mcp' );
      expect( route, route ).not.toMatch( /^\/llms.*\.txt$/ );
      expect( route, route ).not.toMatch( /(?:rss|feed).*\.xml$/ );
    }
  } );

  it( 'keeps Home as the only normal canonical route without Policy Details', () => {
    for ( const route of CANONICAL_PUBLIC ) {
      const policy = publicPolicyDetailsForRoute( route );
      if ( route === '/' || EMBEDDED_POLICY_ROUTES.has( route ) ) {
        expect( policy, route ).toBeNull();
      } else {
        expect( policy, route ).not.toBeNull();
      }
    }

    expect( EMBEDDED_POLICY_ROUTES.size ).toBe( 20 );
  } );

  it( 'covers every shared public family with fallback or embedded policy as intended', () => {
    const fallback = [
      '/post/[slug]',
      '/blog/page/[page]',
      '/blog/topic/[topic]',
      '/blog/topic/[topic]/page/[page]',
      '/shop/page/[page]',
      '/account/sign-in',
      '/cart',
      '/checkout/status',
      '/checkout/success',
      '/get',
    ];

    for ( const route of fallback ) {
      expect( publicPolicyDetailsForRoute( route ), route ).not.toBeNull();
    }
    expect( publicPolicyDetailsForRoute( '/shop/[slug]' ) ).toBeNull();
    expect( publicPolicyDetailsForRoute( '/404' ) ).toBeNull();
  } );

  it( 'mounts the final public shell in the required order exactly once', () => {
    const branchStart = app.indexOf( 'if ( isPublic )' );
    const branchEnd = app.indexOf( '// Protected pages', branchStart );
    expect( branchStart ).toBeGreaterThan( -1 );
    expect( branchEnd ).toBeGreaterThan( branchStart );
    const branch = app.slice( branchStart, branchEnd );

    for ( const marker of [
      '<Header />',
      '<Component { ...pageProps } />',
      '<PublicPolicyDetails />',
      '<PublicShare />',
      '<Footer />',
    ] ) {
      expect( ( branch.split( marker ).length - 1 ), marker ).toBe( 1 );
    }

    const header = branch.indexOf( '<Header />' );
    const page = branch.indexOf( '<Component { ...pageProps } />' );
    const policy = branch.indexOf( '<PublicPolicyDetails />' );
    const actions = branch.indexOf( '<PublicShare />' );
    const footer = branch.indexOf( '<Footer />' );

    expect( page ).toBeGreaterThan( header );
    expect( policy ).toBeGreaterThan( page );
    expect( actions ).toBeGreaterThan( policy );
    expect( footer ).toBeGreaterThan( actions );
  } );

  it( 'keeps the combined Contribute + Subscribe + Share dock app-owned on every public page', () => {
    const dock = read( 'src/components/PublicShare.tsx' );
    expect( dock ).toContain( 'aria-label="Contribute, subscribe and share"' );
    expect( dock ).toContain( 'ps-contribute' );
    expect( dock ).toContain( 'ps-subscribe' );
    expect( dock ).toContain( 'ps-share-trigger' );

    const offenders = walkTsx( PAGES )
      .filter( file => file !== APP )
      .filter( file => {
        const source = fs.readFileSync( file, 'utf8' );
        return /import\s+PublicShare\b/.test( source ) || /<PublicShare\b/.test( source );
      } )
      .map( file => path.relative( ROOT, file ) );

    expect( offenders ).toEqual( [] );
  } );

  it( 'keeps direct embedded PolicyDetails mounts limited to the two bespoke pages and dynamic shop', () => {
    const directPageOwners = walkTsx( PAGES )
      .filter( file => fs.readFileSync( file, 'utf8' ).includes( '<PolicyDetails' ) )
      .map( file => path.relative( ROOT, file ) )
      .sort();

    expect( directPageOwners ).toEqual( [
      'src/pages/bharat-rx.tsx',
      'src/pages/grahak-os/index.tsx',
      'src/pages/shop/[slug].tsx',
    ] );

    expect( ( read( 'src/components/ProductPage.tsx' ).match( /<PolicyDetails\b/g ) || [] ) ).toHaveLength( 1 );
    expect( ( read( 'src/components/public/PublicPolicyDetails.tsx' ).match( /<PolicyDetails\b/g ) || [] ) ).toHaveLength( 1 );
  } );

  it( 'keeps the design-drift gate wired to the public hierarchy consumers', () => {
    const drift = read( 'scripts/check_design_drift.py' );
    for ( const file of [
      'src/components/RotatingHero.tsx',
      'src/components/ProductPage.tsx',
      'src/components/LegalDocument.tsx',
      'src/components/BlogIndexView.tsx',
      'src/components/ShopListingView.tsx',
      'src/components/ProductBuyBox.tsx',
      'src/components/ServiceBuyBox.tsx',
      'src/pages/shop/[slug].tsx',
    ] ) {
      // check_design_drift.py roots these entries at SRC and stores only the
      // path relative to src/, e.g. SRC / "components/RotatingHero.tsx".
      // Requiring a literal "src/..." string would reject the correct pathlib form.
      expect( drift, file ).toContain( file.replace( /^src\//, '' ) );
    }
  } );
} );
