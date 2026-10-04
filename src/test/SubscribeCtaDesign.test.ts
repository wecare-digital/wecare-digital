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
  it( 'keeps the blog-post WhatsApp CTA on the home-page button contract', () => {
    const source = read( 'src/pages/post/[slug].tsx' );
    const rule = ruleFor( source, '.blog-wa-subscribe{' );

    expect( source ).toContain( 'aria-label="Subscribe on WhatsApp"' );
    expect( source ).toContain( '<span>Subscribe</span>' );
    expect( source ).not.toContain( '<span>Subscribe on WhatsApp</span>' );

    expect( rule ).toContain( 'min-height:52px' );
    expect( rule ).toContain( 'padding:028px' );
    expect( rule ).toContain( 'border:2pxsolid#1a3a2a' );
    expect( rule ).toContain( 'border-radius:50px' );
    expect( rule ).toContain( 'background:#d1f470' );
    expect( rule ).toContain( 'color:#1a3a2a' );
    expect( rule ).toContain( 'font-size:17px' );
    expect( rule ).toContain( 'font-weight:600' );

    expect( source ).toContain(
      '.blog-wa-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}'
    );
    expect( source ).toContain(
      '.blog-wa-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}'
    );
  } );

  it( 'keeps the VayuLok WhatsApp CTA on the same home-page button contract', () => {
    const source = read( 'src/components/VayuLokLive.tsx' );
    const rule = ruleFor( source, '.vl-live-wa-subscribe{' );

    expect( source ).toContain( 'aria-label="Subscribe on WhatsApp"' );
    expect( source ).toContain( '<span>Subscribe</span>' );
    expect( source ).not.toContain( '<span>Subscribe on WhatsApp</span>' );

    expect( rule ).toContain( 'min-height:52px' );
    expect( rule ).toContain( 'padding:028px' );
    expect( rule ).toContain( 'border:2pxsolidvar(--green)' );
    expect( rule ).toContain( 'border-radius:50px' );
    expect( rule ).toContain( 'background:var(--lime)' );
    expect( rule ).toContain( 'color:var(--green)' );
    expect( rule ).toContain( 'font-size:17px' );
    expect( rule ).toContain( 'font-weight:600' );

    expect( source ).toContain(
      '.vl-live-wa-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}'
    );
    expect( source ).toContain(
      '.vl-live-wa-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}'
    );
  } );
} );
