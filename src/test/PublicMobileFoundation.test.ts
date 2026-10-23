import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = ( path: string ) => readFileSync( resolve( process.cwd(), path ), 'utf8' );

describe( 'public mobile foundation', () => {
  it( 'locks the canonical phone deltas in shared public tokens', () => {
    const tokens = read( 'src/styles/tokens.css' );

    expect( tokens ).toContain( '--public-mobile-hero-size: 40px' );
    expect( tokens ).toContain( '--public-mobile-section-size: 32px' );
    expect( tokens ).toContain( '--public-mobile-card-size: 24px' );
    expect( tokens ).toContain( '--public-mobile-cta-font-size: 18px' );
    expect( tokens ).toContain( '--public-mobile-page-gutter: 16px' );
    expect( tokens ).toContain( '--public-mobile-section-gap: 64px' );
    expect( tokens ).toContain( '--public-mobile-hero-top: 48px' );
    expect( tokens ).toContain( '--public-mobile-form-font-size: 16px' );

    expect( tokens.match( /font-size: var\(--public-mobile-form-font-size\) !important;/g )?.length ).toBe( 2 );
    expect( tokens ).toContain( 'min-height: var(--tap-min)' );
    expect( tokens ).toContain( 'min-width: var(--tap-min)' );
  } );

  it( 'keeps Home as the first explicit consumer of the mobile foundation', () => {
    const home = read( 'src/pages/index.tsx' );

    for ( const token of [
      '--public-mobile-hero-size',
      '--public-mobile-section-size',
      '--public-mobile-card-size',
      '--public-mobile-cta-font-size',
      '--public-mobile-page-gutter',
      '--public-mobile-section-gap',
      '--public-mobile-hero-top',
    ] ) {
      expect( home ).toContain( `var(${ token })` );
    }
  } );

  it( 'records Grahak OS and VayuLok as explicit foundation adopters', () => {
    const grahak = read( 'src/pages/grahak-os/index.tsx' );
    const rotatingHero = read( 'src/components/RotatingHero.tsx' );
    const vayulok = read( 'src/pages/vayulok/index.tsx' );
    const vayulokLive = read( 'src/components/VayuLokLive.tsx' );

    expect( grahak ).toContain( 'mobileFoundation' );
    expect( grahak ).toContain( '--public-mobile-section-size' );
    expect( grahak ).toContain( '--public-mobile-card-size' );
    expect( grahak ).toContain( '--public-mobile-page-gutter' );
    expect( rotatingHero ).toContain( '--public-mobile-hero-size' );
    expect( rotatingHero ).toContain( '--public-mobile-hero-top' );
    expect( rotatingHero ).toContain( '--public-mobile-section-gap' );

    expect( vayulok ).toContain( 'mobileFoundation' );
    expect( vayulok ).toContain( '--public-mobile-hero-size' );
    expect( vayulokLive ).toContain( '--public-mobile-card-size' );
    expect( vayulokLive ).toContain( '--public-mobile-page-gutter' );
    expect( vayulokLive ).toContain( '--public-mobile-section-gap' );
    expect( vayulokLive ).toContain( '--vl-action-size:var(--tap-min)' );
    expect( vayulokLive ).toContain( 'font-family:var(--font-sans)' );
  } );

  it( 'keeps VayuLok Weather history on the public typography and touch contract', () => {
    const insights = read( 'src/components/VayuLokWeatherInsights.tsx' );
    const primitives = read( 'src/components/VayuLokUiPrimitives.tsx' );

    expect( insights ).toContain( '<VayuLokSectionHeading>Weather history</VayuLokSectionHeading>' );
    expect( insights ).toContain( 'Past weather for' );
    expect( insights ).not.toContain( 'Google Weather historical aggregates for' );
    expect( insights ).not.toContain( 'Google Weather Insights' );
    expect( insights ).toContain( 'font-size:var(--vl-panel-heading-size,var(--public-data-size))' );
    expect( insights ).toContain( '.vl-wi-head p{margin:6px 0 0;color:var(--public-muted);font-size:var(--vl-subtext-size,var(--public-supporting-size))' );
    expect( insights ).toContain( '.vl-wi-head p{font-size:var(--vl-subtext-size,var(--public-supporting-size))' );
    expect( insights ).not.toContain( 'font-size:var(--vl-card-heading-size,var(--public-card-size))' );
    expect( insights ).not.toContain( 'font-size:var(--text-' );
    expect( insights ).toContain( '<VayuLokCompactPill' );
    expect( primitives ).toContain( '.vl-ui-compact-pill:hover{' );
    expect( primitives ).toContain( '.vl-ui-compact-pill.is-active{' );
    expect( insights ).not.toContain( 'background:rgba(17,21,18,.07)' );
    expect( primitives ).toContain( '.vl-ui-icon-action{' );
    expect( primitives ).toContain( 'min-height:var(--tap-min,44px)' );
    expect( insights ).toContain( '<VayuLokFreshnessStamp' );
    expect( insights ).not.toContain( 'Loading history…' );
    expect( insights ).toContain( 'className="vl-wi-sr"' );
    expect( insights ).not.toContain( 'className="vl-wi-source"' );
    expect( insights ).toContain( 'font-family:var(--font-sans)' );
  } );

  it( 'records the public blog listing and post reader as mobile-foundation adopters', () => {
    const listing = read( 'src/components/BlogIndexView.tsx' );
    const post = read( 'src/pages/post/[slug].tsx' );

    expect( listing ).toContain( 'mobileFoundation' );
    expect( listing ).toContain( '--public-mobile-card-size' );
    expect( listing ).toContain( '--public-mobile-form-font-size' );

    expect( post ).toContain( 'mobileFoundation' );
    expect( post ).toContain( '--public-mobile-hero-size' );
    expect( post ).toContain( '--public-mobile-section-size' );
    expect( post ).toContain( '--public-mobile-card-size' );
    expect( post ).toContain( '--public-mobile-form-font-size' );
    expect( post ).toContain( 'font-size:var(--public-body-size);line-height:1.55' );
    expect( post ).not.toContain( 'font-size:18px;line-height:1.6' );
  } );

  it( 'records Terms and Privacy as explicit long-form mobile-foundation adopters', () => {
    const terms = read( 'src/pages/terms.tsx' );
    const privacy = read( 'src/pages/privacy.tsx' );
    const legal = read( 'src/components/LegalDocument.tsx' );

    expect( terms ).toContain( 'mobileFoundation' );
    expect( privacy ).toContain( 'mobileFoundation' );
    expect( legal ).toContain( 'font-family:var(--font-sans)' );
    expect( legal ).toContain( 'font-size:var(--public-mobile-section-size)' );
    expect( legal ).toContain( 'font-size:var(--public-mobile-card-size)' );
    expect( legal ).toContain( 'min-height:var(--tap-min)' );
    expect( legal ).toContain( 'border-inline-start' );
    expect( legal ).toContain( 'padding-inline-start' );
    expect( legal ).toContain( 'margin-inline-end' );
  } );

  it( 'records shared service/product ProductPage routes as explicit mobile-foundation adopters', () => {
    const productPage = read( 'src/components/ProductPage.tsx' );
    const productBlogPanel = read( 'src/components/ProductBlogPanel.tsx' );
    const adopted = [
      'src/pages/anew.tsx',
      'src/pages/expo-week.tsx',
      'src/pages/niji-setu.tsx',
      'src/pages/hunar/kaushal.tsx',
      'src/pages/hunar/prastuti.tsx',
      'src/pages/shipments/track.tsx',
      'src/pages/elsewhere/visa.tsx',
      'src/pages/elsewhere/trip.tsx',
      'src/pages/dastavez/drafting.tsx',
      'src/pages/dastavez/registration.tsx',
      'src/pages/dastavez/legal-reference.tsx',
      'src/pages/ritual-guru/ritva.tsx',
      'src/pages/ritual-guru/puja-guidance.tsx',
      'src/pages/ritual-guru/diy-puja-kit.tsx',
    ];
    const deferredCustomerForms = [
      'src/pages/submit-request.tsx',
      'src/pages/request-amendment.tsx',
      'src/pages/drop-docs.tsx',
      'src/pages/vault.tsx',
      'src/pages/request-pickup.tsx',
    ];

    expect( productPage ).toContain( "mobileFoundation ? 'pdp uses-mobile-foundation' : 'pdp'" );
    expect( productPage ).toContain( '.pdp.uses-mobile-foundation .pdp-h2{font-size:var(--public-mobile-section-size)}' );
    expect( productPage ).toContain( '.pdp.uses-mobile-foundation .pdp-point-t{font-size:var(--public-mobile-card-size)}' );
    expect( productPage ).toContain( '.pdp.uses-mobile-foundation .pdp-cta{font-size:var(--public-mobile-cta-font-size)}' );
    expect( productPage ).toContain( '.pdp.uses-mobile-foundation :global(.checkout-action){font-size:var(--public-mobile-cta-font-size)}' );
    expect( productBlogPanel ).toContain( 'margin-inline-start:-10px' );
    expect( productBlogPanel ).not.toContain( 'margin-left:-10px' );

    for ( const path of adopted ) expect( read( path ), path ).toContain( 'mobileFoundation' );
    for ( const path of deferredCustomerForms ) expect( read( path ), path ).not.toContain( 'mobileFoundation' );
  } );

  it( 'keeps the bespoke Activities experience explicitly on the Home-aligned mobile foundation', () => {
    const productPage = read( 'src/components/ProductPage.tsx' );
    const activities = read( 'src/pages/elsewhere/activities.tsx' );
    const assistant = read( 'src/components/ElsewhereTravelAssistant.tsx' );

    expect( productPage ).toContain( 'mobileFoundation?: boolean' );
    expect( productPage ).toContain( 'mobileFoundation={ mobileFoundation }' );
    expect( activities ).toContain( 'mobileFoundation' );
    expect( assistant ).toContain( 'var(--public-mobile-page-gutter)' );
    expect( assistant ).toContain( 'font-size:var(--public-body-size)' );
    expect( assistant ).toContain( 'font-family:var(--font-sans)' );
    expect( assistant ).toContain( 'font-size:var(--public-mobile-cta-font-size)' );
    expect( assistant ).toContain( 'touch-action:pan-x' );
    expect( assistant ).toContain( 'min-height:var(--tap-min)' );
    expect( assistant ).toContain( 'padding-inline:var(--public-mobile-page-gutter)' );
    expect( assistant ).toContain( 'new MutationObserver( centreActiveTab )' );
    expect( assistant ).toContain( "attributeFilter: [ 'dir', 'lang' ]" );
  } );

  it( 'documents opt-in family-by-family adoption', () => {
    const steering = read( '.kiro/steering/25-public-mobile-foundation.md' );

    expect( steering ).toContain( 'Home is the locked reference implementation' );
    expect( steering ).toContain( 'Adopt the contract family-by-family' );
    expect( steering ).toContain( 'Grahak OS is migrated' );
    expect( steering ).toContain( 'VayuLok is migrated' );
    expect( steering ).toContain( 'Terms/Privacy long-form legal family is' );
    expect( steering ).toContain( 'migrated as well' );
    expect( steering ).toContain( 'Shared service/product pages' );
    expect( steering ).toContain( 'A real physical' );
  } );
} );
