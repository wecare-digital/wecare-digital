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
    expect( steering ).toContain( 'Shared service/product' );
    expect( steering ).toContain( 'pages are next' );
    expect( steering ).toContain( 'A real physical' );
  } );
} );
