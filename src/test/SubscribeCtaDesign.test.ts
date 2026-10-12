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

    // The Subscribe pill contract now lives on PublicShare's `.ps-subscribe`.
    const share = read( 'src/components/PublicShare.tsx' );
    const rule = ruleFor( share, '.ps-subscribe{' );
    expect( share ).toContain( 'aria-label="Subscribe on WhatsApp"' );

    expect( rule ).toContain( 'min-height:52px' );
    expect( rule ).toContain( 'padding:028px' );
    expect( rule ).toContain( 'border:2pxsolid#1a3a2a' );
    expect( rule ).toContain( 'border-radius:50px' );
    expect( rule ).toContain( 'background:#d1f470' );
    expect( rule ).toContain( 'color:#1a3a2a' );
    expect( rule ).toContain( 'font-size:17px' );
    expect( rule ).toContain( 'font-weight:600' );

    expect( share ).toContain(
      '.ps-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}'
    );
    expect( share ).toContain(
      '.ps-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}'
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
