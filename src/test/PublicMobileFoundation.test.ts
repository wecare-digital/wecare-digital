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

  it( 'records Grahak OS, VayuLok and shared ProductPage as explicit foundation adopters', () => {
    const grahak = read( 'src/pages/grahak-os/index.tsx' );
    const rotatingHero = read( 'src/components/RotatingHero.tsx' );
    const vayulok = read( 'src/pages/vayulok/index.tsx' );
    const vayulokLive = read( 'src/components/VayuLokLive.tsx' );
    const productPage = read( 'src/components/ProductPage.tsx' );

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

    expect( productPage ).toContain( 'mobileFoundation' );
    expect( productPage ).toContain( '--public-mobile-section-size' );
    expect( productPage ).toContain( '--public-mobile-card-size' );
    expect( productPage ).toContain( '--public-mobile-cta-font-size' );
    expect( productPage ).toContain( '--public-mobile-section-gap' );
  } );

  it( 'documents opt-in family-by-family adoption', () => {
    const steering = read( '.kiro/steering/25-public-mobile-foundation.md' );

    expect( steering ).toContain( 'Home is the locked reference implementation' );
    expect( steering ).toContain( 'Adopt the contract family-by-family' );
    expect( steering ).toContain( 'Grahak OS is migrated' );
    expect( steering ).toContain( 'VayuLok is migrated' );
    expect( steering ).toContain( 'Shared service/product pages are migrated' );
    expect( steering ).toContain( 'customer forms are next' );
    expect( steering ).toContain( 'A real physical' );
  } );
} );
