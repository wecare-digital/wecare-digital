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


  /**
   * VAYULOK NOW CARRIES THE BLOG POST'S COMPACT SUBSCRIBE PILL, SIZED TO THE CARD, and that is a
   * DELIBERATE owner decision - not the page-specific CTA this test used to forbid.
   *
   * The guard previously asserted VayuLokLive.tsx contained NO WhatsApp subscribe CTA at all,
   * because the embedded block rendered the old in-page BlogSubscribe signup FORM and a
   * page-local pill would have been a one-off divergence from the shared blog furniture. The
   * owner then reported the embedded block looked like the OLD style and the button was too big
   * for the narrow floating card, and asked for it to MATCH the live blog post - which carries a
   * compact lime Subscribe pill (.blog-wa-subscribe), the twin of the Contribute pill, instead of
   * the form. VayuLok now renders that same pill inline (.vl-live-air-subscribe) at the shared
   * SUBSCRIBE_CTA_HREF, SIZED to the card via rules scoped under .vl-live-air-extras.
   *
   * So the intent is inverted: the pill is REQUIRED here now, carrying the same lime object and
   * the same accessible name as the blog twin. What must NOT come back is the old full form.
   */
  it( 'renders the blog post subscribe pill, sized to the card, instead of the old in-page form', () => {
    const source = read( 'src/components/VayuLokLive.tsx' );

    // The compact blog-matching pill is present, as a static anchor at the shared deep link with
    // the blog twin's accessible name and visible word.
    expect( source ).toContain( 'className="vl-live-air-subscribe"' );
    expect( source ).toContain( 'href={ SUBSCRIBE_CTA_HREF }' );
    expect( source ).toContain( 'aria-label="Subscribe on WhatsApp"' );
    expect( source ).toContain( '<span>Subscribe</span>' );

    // The OLD in-page BlogSubscribe signup form is gone - it is neither imported nor rendered.
    expect( source ).not.toContain( "import BlogSubscribe" );
    expect( source ).not.toContain( '<BlogSubscribe' );

    // The pill carries the home-page button contract (the blog twin's lime object) and is SIZED
    // TO THE CARD: full-width block with reduced inline padding, so it no longer overflows the
    // narrow column. 48px min-height stays above the 44px tap target.
    const rule = ruleFor( source, '.vl-live-air-subscribe{' );
    expect( rule ).toContain( 'width:100%' );
    expect( rule ).toContain( 'min-height:48px' );
    expect( rule ).toContain( 'padding:020px' );
    expect( rule ).toContain( 'border:2pxsolid#1a3a2a' );
    expect( rule ).toContain( 'border-radius:50px' );
    expect( rule ).toContain( 'background:#d1f470' );
    expect( rule ).toContain( 'color:#1a3a2a' );
    expect( rule ).toContain( 'font-size:17px' );
    expect( rule ).toContain( 'font-weight:600' );

    // The house hover (lime -> white inversion with the one allowed lift and shadow), the twin's.
    expect( source ).toContain(
      '.vl-live-air-extras .vl-live-air-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}'
    );
    expect( source ).toContain(
      '.vl-live-air-extras .vl-live-air-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}'
    );

    // The embedded Contribute pill is sized to the card the same way, reached only via :global()
    // nested under .vl-live-air-extras so the shared blog component's base rule is unchanged.
    expect( source ).toContain( '.vl-live-air-extras :global(.bc-cta){' );
  } );
} );
