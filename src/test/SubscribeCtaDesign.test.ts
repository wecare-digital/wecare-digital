import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = ( relative: string ) =>
  fs.readFileSync( path.resolve( process.cwd(), relative ), 'utf8' );

const ruleFor = ( source: string, selector: string ) => {
  const start = source.indexOf( selector );
  expect( start ).toBeGreaterThanOrEqual( 0 );
  const open = source.indexOf( '{', start );
  const close = source.indexOf( '}', open );
  expect( open ).toBeGreaterThan( start );
  expect( close ).toBeGreaterThan( open );
  return source.slice( start, close + 1 ).replace( /\s+/g, '' );
};

describe( 'WhatsApp subscribe CTA design', () => {
  /**
   * THE POST PAGE NO LONGER OWNS A SUBSCRIBE PILL - the owner unified every public surface onto
   * the ONE global PublicShare block. So the old inline `.blog-wa-subscribe` anchor and its CSS
   * are gone from src/pages/post/[slug].tsx, and the page renders <PublicShare> instead. This
   * case therefore asserts the removal on the page AND holds the home-page button contract on the
   * component that now carries the Subscribe pill (PublicShare's `.ps-subscribe`).
   */
  it( 'removes the post page own Subscribe pill and keeps the contract on the global PublicShare', () => {
    const page = read( 'src/pages/post/[slug].tsx' );

    // The old inline Subscribe pill is gone, markup and CSS both.
    expect( page ).not.toContain( 'className="blog-wa-subscribe"' );
    expect( page ).not.toContain( '.blog-wa-subscribe{' );
    expect( page ).not.toContain( '<span>Subscribe</span>' );
    // The page renders the global block instead.
    expect( page ).toContain( '<PublicShare' );

    // Subscribe now shares the compact 48px circular action contract with Contribute and Share.
    const share = read( 'src/components/PublicShare.tsx' );
    const action = ruleFor( share, '.ps-action{' );
    const subscribe = ruleFor( share, '.ps-subscribe{' );
    expect( share ).toContain( 'aria-label="Subscribe on WhatsApp"' );

    expect( action ).toContain( 'width:48px' );
    expect( action ).toContain( 'height:48px' );
    expect( action ).toContain( 'border-radius:50%' );
    expect( action ).toContain( 'display:inline-flex' );
    expect( action ).toContain( 'align-items:center' );
    expect( action ).toContain( 'justify-content:center' );

    expect( subscribe ).toContain( 'background:#d1f470' );
    expect( subscribe ).toContain( 'border-color:#1a3a2a' );
    expect( share ).toContain( '.ps-subscribe:hover{background:#fff}' );
    expect( share ).toContain(
      '.ps-action:focus-visible,.ps-menu-item:focus-visible{'
    );
  } );


  it( 'keeps Subscribe, Contribute and Share out of the VayuLok Air card', () => {
    const source = read( 'src/components/VayuLokLive.tsx' );

    expect( source ).not.toContain( 'vl-live-air-subscribe' );
    expect( source ).not.toContain( 'SUBSCRIBE_CTA_HREF' );
    expect( source ).not.toContain( '<BlogContribution' );
    expect( source ).not.toContain( '<ShareLinks' );
    expect( source ).not.toContain( 'vl-live-air-extras' );
  } );

} );
