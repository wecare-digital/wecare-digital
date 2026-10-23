import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const globe = readFileSync( resolve( process.cwd(), 'public/vayulok-globe.html' ), 'utf8' );

describe( 'VayuLok iframe globe public-app foundation', () => {
  it( 'keeps the standalone iframe on the public font, safe-area and 44px touch contract', () => {
    expect( globe ).toContain( "--font-sans:'Inter',-apple-system" );
    expect( globe ).toContain( '--tap-min:44px' );
    expect( globe ).toContain( '--safe-top:env(safe-area-inset-top,0px)' );
    expect( globe ).toContain( 'font-family:var(--font-sans)' );
    expect( globe ).toContain( 'width:var(--tap-min);height:var(--tap-min)' );
    expect( globe ).toContain( 'min-width:var(--tap-min);min-height:var(--tap-min)' );
    expect( globe ).toContain( 'width:176px;height:var(--tap-min)' );
  } );

  it( 'enlarges city hit areas without enlarging the geographic dot', () => {
    expect( globe ).toContain( '.city-pin {' );
    expect( globe ).toContain( 'background:transparent;box-shadow:none' );
    expect( globe ).toContain( '.city-pin::before{' );
    expect( globe ).toContain( 'width:12px;height:12px' );
    expect( globe ).toContain( '.city-marker.is-active .city-pin::before{' );
    expect( globe ).toContain( 'width:14px;height:14px' );
    expect( globe ).not.toContain( '.city-marker.is-active .city-pin{\n    width:14px;height:14px' );
  } );

  it( 'keeps reduced-motion behavior on the visual dot animation', () => {
    expect( globe ).toContain( '.city-marker.is-visible .city-pin::before{animation:cityPulse' );
    expect( globe ).toContain( '.city-marker.is-visible .city-pin::before{animation:none}' );
  } );
} );
