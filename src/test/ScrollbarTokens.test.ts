import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * THE SCROLLBAR TOKEN *VALUES*. Invariant 2, and it is deliberately separate from invariant 1.
 *
 * "Which declaration wins at runtime" is a measurement that needs a browser, and
 * tools/browser/designsweep.js owns it - it harvests --scrollbar-thumb and --scrollbar-track
 * from the page and asserts every surface agrees with them. That harvest is strictly better
 * than the three pasted constants it replaced, but it bought one thing at the price of
 * another: a harness that reads the token can no longer tell you the token is WRONG. Set
 * --scrollbar-thumb to lime and designsweep stays green, because every surface still agrees.
 *
 * So WHICH colour is a policy, and a policy is judged from a diff. That is this file.
 *
 * WHY THE TRACK IS ASSERTED AS AN INDIRECTION AND THE CONTRAST AGAINST ITS RESOLVED VALUE.
 * --scrollbar-track reads `var(--lime-tint)` so that the house lime state tint has exactly one
 * declaration and a change to it cannot move the scrollbar and not .btn-ghost:hover. A test
 * that grepped tokens.css for `--scrollbar-track: rgba(209, 244, 112, 0.22)` would have failed
 * on the day the indirection landed with nothing regressed - which is the failure mode that
 * gets a test deleted rather than fixed. The literal is asserted once, on --lime-tint, and the
 * arithmetic runs on the resolved value.
 */

const TOKENS_PATH = path.join( __dirname, '..', 'styles', 'tokens.css' );
const RAW = fs.readFileSync( TOKENS_PATH, 'utf8' );

/**
 * COMMENT-STRIPPING IS LOAD-BEARING AND MUST COME FIRST. The SCROLLBAR block's comment names
 * every value this file asserts on, plus the four deleted declarations and the rejected lime
 * thumb - so a scan of the raw text finds `--scrollbar-thumb`, `#d1f470` and
 * `rgba(26,58,42,.15)` in prose that exists precisely to explain why they are not the answer.
 */
const stripComments = ( src: string ): string => src.replace( /\/\*[\s\S]*?\*\//g, ' ' );

const CSS = stripComments( RAW );

/** Every declaration of a custom property, in source order, comments already gone. */
const declarationsOf = ( name: string ): string[] => {
  const pattern = new RegExp( `${name.replace( /[-]/g, '\\-' )}\\s*:\\s*([^;}]+)`, 'g' );
  return Array.from( CSS.matchAll( pattern ) ).map( m => m[ 1 ].trim() );
};

const valueOf = ( name: string ): string => {
  const all = declarationsOf( name );
  expect( all.length, `expected exactly one declaration of ${name} in tokens.css` ).toBe( 1 );
  return all[ 0 ];
};

/* ── colour arithmetic: the sRGB relative-luminance formula of WCAG 2.x ──────────────────── */

type Colour = { r: number; g: number; b: number; a: number };

const parse = ( value: string ): Colour | null => {
  const hex = /^#([0-9a-f]{6})$/i.exec( value.trim() );
  if ( hex ) {
    const p = hex[ 1 ].match( /.{2}/g ) as string[];
    return { r: parseInt( p[ 0 ], 16 ), g: parseInt( p[ 1 ], 16 ), b: parseInt( p[ 2 ], 16 ), a: 1 };
  }
  const m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.]+))?\s*\)$/i
    .exec( value.trim() );
  if ( !m ) return null;
  return { r: +m[ 1 ], g: +m[ 2 ], b: +m[ 3 ], a: m[ 4 ] === undefined ? 1 : +m[ 4 ] };
};

const WHITE: Colour = { r: 255, g: 255, b: 255, a: 1 };

/** Composite a possibly-transparent colour over an opaque backdrop. */
const over = ( fg: Colour, bg: Colour ): Colour => ( fg.a >= 1 ? fg : {
  r: fg.r * fg.a + bg.r * ( 1 - fg.a ),
  g: fg.g * fg.a + bg.g * ( 1 - fg.a ),
  b: fg.b * fg.a + bg.b * ( 1 - fg.a ),
  a: 1,
} );

const luminance = ( c: Colour ): number => {
  const ch = ( v: number ): number => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow( ( s + 0.055 ) / 1.055, 2.4 );
  };
  return 0.2126 * ch( c.r ) + 0.7152 * ch( c.g ) + 0.0722 * ch( c.b );
};

const contrast = ( a: Colour, b: Colour ): number => {
  const la = luminance( a ), lb = luminance( b );
  return ( Math.max( la, lb ) + 0.05 ) / ( Math.min( la, lb ) + 0.05 );
};

describe( 'scrollbar token values', () => {
  it( 'strips the comment that names every value asserted below', () => {
    // Anti-vacuous guard, and it is not theoretical here: the block comment mentions the
    // rejected lime thumb and the four deleted declarations by value. If stripping ever broke,
    // the "no longer var(--accent)" and single-declaration assertions would start reading prose.
    expect( RAW ).toContain( 'THE BRAND SHOWS IN THE TRACK' );
    expect( CSS ).not.toContain( 'THE BRAND SHOWS IN THE TRACK' );
    expect( CSS ).toContain( '--scrollbar-thumb:' );
  } );

  it( 'declares the house lime state tint exactly once, as the literal', () => {
    expect( valueOf( '--lime-tint' ) ).toBe( 'rgba(209, 244, 112, 0.22)' );
  } );

  it( 'reads the track from that one declaration rather than copying it', () => {
    // The point of the indirection: --scrollbar-track and --control-tint cannot drift apart.
    expect( valueOf( '--scrollbar-track' ) ).toBe( 'var(--lime-tint)' );
  } );

  it( 'gives the thumb its own value instead of aliasing a heading colour', () => {
    const thumb = valueOf( '--scrollbar-thumb' );
    expect( thumb ).toBe( '#4a9e73' );
    // Stated as its own assertion because the alias is the specific thing that was wrong:
    // --accent is #1a3a2a, the home CTA's border and heading colour, which measures 11.85:1 on
    // this track and reads as the near-black the owner's instruction was about.
    expect( thumb ).not.toBe( 'var(--accent)' );
    expect( thumb ).not.toContain( 'var(' );
  } );

  it( 'darkens on hover, so hover raises contrast rather than lowering it', () => {
    const hover = valueOf( '--scrollbar-thumb-hover' );
    expect( hover ).toBe( '#3a7d5a' );
    expect( hover ).not.toBe( 'var(--accent-hover)' );

    const track = over( parse( valueOf( '--lime-tint' ) ) as Colour, WHITE );
    const rest = contrast( over( parse( valueOf( '--scrollbar-thumb' ) ) as Colour, WHITE ), track );
    const onHover = contrast( over( parse( hover ) as Colour, WHITE ), track );
    expect( onHover ).toBeGreaterThan( rest );
  } );

  it( 'keeps the thumb findable against its own track - WCAG 1.4.11, 3:1', () => {
    const thumb = parse( valueOf( '--scrollbar-thumb' ) );
    const tint = parse( valueOf( '--lime-tint' ) );
    // Loudly rather than silently: an unparseable token must fail here, not be composited away.
    expect( thumb, `unparseable --scrollbar-thumb: ${valueOf( '--scrollbar-thumb' )}` ).not.toBeNull();
    expect( tint, `unparseable --lime-tint: ${valueOf( '--lime-tint' )}` ).not.toBeNull();

    // The RESOLVED track, not the literal text of the --scrollbar-track line. The tint is
    // semi-transparent, so the colour a customer actually sees is it composited over the page:
    // rgba(209, 244, 112, 0.22) over white is #f5fde0.
    const track = over( tint as Colour, WHITE );
    expect( Math.round( track.r ) ).toBe( 245 );
    expect( Math.round( track.g ) ).toBe( 253 );
    expect( Math.round( track.b ) ).toBe( 224 );

    const ratio = contrast( over( thumb as Colour, WHITE ), track );
    expect(
      ratio,
      `the thumb measures ${ratio.toFixed( 2 )}:1 on its own track, under the 3:1 WCAG 1.4.11 `
      + 'asks of a non-text control boundary. #4a9e73 clears it by 0.10 - about 3% - so there '
      + 'is almost no headroom: a lighter thumb has to be re-measured here before it lands.',
    ).toBeGreaterThanOrEqual( 3 );
  } );

  it( 'agrees with the measured figures the comment quotes', () => {
    // The comment states 3.10:1 for the thumb and 4.68:1 for hover. A comment that quotes a
    // number nobody checks is how the previous one came to claim the thumb was 12.48:1 long
    // after that stopped being the design.
    const track = over( parse( valueOf( '--lime-tint' ) ) as Colour, WHITE );
    const at = ( v: string ): number => contrast( over( parse( v ) as Colour, WHITE ), track );
    expect( at( valueOf( '--scrollbar-thumb' ) ) ).toBeCloseTo( 3.10, 2 );
    expect( at( valueOf( '--scrollbar-thumb-hover' ) ) ).toBeCloseTo( 4.68, 2 );
    // And the rejected candidates, so the rejection stays a measurement rather than a memory.
    expect( at( '#d1f470' ) ).toBeLessThan( 1.3 );
    expect( at( '#1a3a2a' ) ).toBeGreaterThan( 11 );
  } );

  it( 'leaves the two size tokens alone', () => {
    expect( valueOf( '--scrollbar-size' ) ).toBe( '10px' );
    expect( valueOf( '--scrollbar-size-compact' ) ).toBe( '7px' );
  } );

  it( 'finds a planted token and loses a commented one', () => {
    // PLANTED SAMPLE. Every assertion above is of the shape "the scan returns exactly this",
    // and a scan that silently stopped matching would satisfy none of them loudly - valueOf
    // would throw, but stripComments eating too much would quietly turn a real declaration
    // into prose. So the two halves are exercised on text whose answer is known here.
    const planted = `
      :root {
        /* --scrollbar-thumb: #d1f470;  rejected, see the real block */
        --scrollbar-thumb: #4a9e73;
      }`;
    const stripped = stripComments( planted );
    const found = Array.from( stripped.matchAll( /--scrollbar-thumb\s*:\s*([^;}]+)/g ) )
      .map( m => m[ 1 ].trim() );
    expect( found ).toEqual( [ '#4a9e73' ] );

    // And the arithmetic, on a value whose ratio is known independently: pure white on white.
    expect( contrast( WHITE, WHITE ) ).toBeCloseTo( 1, 5 );
    expect( contrast( { r: 0, g: 0, b: 0, a: 1 }, WHITE ) ).toBeCloseTo( 21, 1 );
    expect( parse( 'var(--lime-tint)' ) ).toBeNull();
  } );
} );
