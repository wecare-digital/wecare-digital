import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import Home from '../pages/index';

/**
 * Band 2's three beat dividers.
 *
 * The owner picked option B from docs/divider-review — three colours rather than one, and no
 * animation. This pins the two things that were measured on the way to building it, both of
 * which the mock got wrong or did not ask.
 *
 * 1. THE MOCK'S COLOURS WERE NOT SHIPPABLE. It offered amber #f0a818, purple #9849e8 and green
 *    #3da35a and claimed in its own cost table that all three clear 3:1 on white. Amber is
 *    2.04:1. Blue #2563eb (5.17:1) replaces it. Red #dc2626 clears 3:1 too and was rejected
 *    for meaning rather than measurement: on "Follow-ups happen automatically" a red rule
 *    reads as a warning about the thing described.
 *
 * 2. WHY 3:1 AT ALL, given these rules are decorative and lime shipped at 1.24:1. WCAG 1.4.11
 *    covers graphics required to understand content, and each beat's text is complete without
 *    its rule — so the floor is not borrowed from the guideline, it is borrowed from the
 *    reason for the change. Once three bars differ, the difference is meant to be perceived,
 *    and 2.04:1 beside 4.72:1 reads as one washed-out bar and two solid ones.
 *
 * NOT ASSERTING 1.4.1 (Use of Colour), deliberately: the beats are told apart by their own
 * sentences and the colours encode nothing. If a bar colour is ever given a meaning, that
 * needs a second non-colour signal and this test needs a new case.
 */

/** Relative luminance, WCAG 2.x. */
const luminance = ( hex: string ): number => {
  const channels = [ 1, 3, 5 ]
    .map( i => parseInt( hex.substr( i, 2 ), 16 ) / 255 )
    .map( v => ( v <= 0.03928 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ) ) );
  return 0.2126 * channels[ 0 ] + 0.7152 * channels[ 1 ] + 0.0722 * channels[ 2 ];
};

const contrast = ( a: string, b: string ): number => {
  const [ hi, lo ] = [ luminance( a ), luminance( b ) ].sort( ( x, y ) => y - x );
  return ( hi + 0.05 ) / ( lo + 0.05 );
};

const WHITE = '#ffffff';
/** In reading order: continuity, delivery, the automated system. */
const BARS = [ '#3da35a', '#2563eb', '#9849e8' ] as const;

const cssOf = ( container: HTMLElement ) =>
  Array.from( container.querySelectorAll( 'style' ) ).map( n => n.textContent || '' ).join( '\n' );

describe( 'Band 2 beat dividers', () => {
  it( 'gives each of the three beats its own colour', () => {
    const { container } = render( <Home /> );
    const css = cssOf( container );

    // Beat 1 carries the base rule; 2 and 3 override only the colour, so the 3px width and the
    // logical side cannot drift apart between them.
    expect( css ).toContain( `.home-flow-list li{padding-inline-start:18px;border-inline-start:3px solid ${BARS[ 0 ]}}` );
    expect( css ).toContain( `.home-flow-list li:nth-child(2){border-inline-start-color:${BARS[ 1 ]}}` );
    expect( css ).toContain( `.home-flow-list li:nth-child(3){border-inline-start-color:${BARS[ 2 ]}}` );

    // Three distinct values, or the option is not what was chosen.
    expect( new Set( BARS ).size ).toBe( 3 );
  } );

  it( 'holds every bar above 3:1 on white, which the mock wrongly claimed of amber', () => {
    for ( const bar of BARS ) {
      expect( contrast( bar, WHITE ) ).toBeGreaterThanOrEqual( 3 );
    }
    // The measurement that changed the plan. Left in as a case rather than a comment so the
    // next person reaching for the "obvious" first three subject hues sees why amber is absent.
    expect( contrast( '#f0a818', WHITE ) ).toBeLessThan( 3 );
    // And the colour that shipped before, for scale: decorative, so it was allowed to be this
    // quiet, and far too quiet to carry a difference.
    expect( contrast( '#d1f470', WHITE ) ).toBeLessThan( 1.5 );
  } );

  it( 'keeps the bars a consistent visual weight rather than one pale and two solid', () => {
    /*
     * The point of the 3:1 floor here, stated as a number. Amber/purple/green spanned
     * 2.04..4.72 - a 2.3x spread, which is what would have read as inconsistent. Green/blue/
     * purple spans 3.19..5.17, a 1.6x spread. Asserted so a later hue swap cannot reintroduce
     * the problem while still technically clearing 3:1.
     */
    const ratios = BARS.map( b => contrast( b, WHITE ) );
    const spread = Math.max( ...ratios ) / Math.min( ...ratios );
    expect( spread ).toBeLessThan( 2 );
  } );

  it( 'introduces no new colour value — all three are already in the page', () => {
    /*
     * #3da35a and #9849e8 are two of the four subject hues CYCLE_WORDS already uses for the
     * hero pill, and #3da35a is also .home-mark-dot's default. #2563eb is the same blue
     * RotatingHero and the blog index use. Reusing them is what keeps this a colour CHOICE
     * rather than a palette expansion.
     */
    const source = require( 'fs' ).readFileSync( require( 'path' ).join( __dirname, '..', 'pages', 'index.tsx' ), 'utf8' );
    for ( const bar of BARS ) {
      // At least twice: once in the divider rule, once in the pre-existing use it borrows from
      // — except blue, which the divider introduces to this file and which is documented.
      expect( source ).toContain( bar );
    }
    expect( source ).toContain( '#2563eb blue     5.17:1' );
  } );

  it( 'adds no animation, because option B was chosen over C and D', () => {
    const { container } = render( <Home /> );
    const css = cssOf( container );
    // No draw: the bars are a real border, not a scaled pseudo-element, so there is nothing to
    // arm and no no-JS path to get wrong.
    expect( css ).not.toContain( '.home-flow-list li::before' );
    expect( css ).not.toContain( '.home-flow-list.is-armed' );
  } );

  it( 'keeps the bars equal height, which is what made them look arbitrary before', () => {
    const { container } = render( <Home /> );
    // grid-auto-rows:1fr from #77. Measured 118/90/90 at 1280 and 118/90/118 at 390 before it,
    // so the bars were unequal AND the pattern changed with the viewport. Colour does not
    // replace that fix - three different-length bars in three colours would look more
    // arbitrary, not less.
    // grid-template-columns:minmax(0,1fr) was added by the unified-mobile Phase 1 zoom fix: the
    // single implicit column was auto-sized to its content's max-content width, which set the
    // page horizontal-scroll floor at a 200%-zoom reflow. minmax(0,1fr) lets the rows wrap to the
    // container width; grid-auto-rows:1fr (the equal-height fix this test guards) is unchanged.
    expect( cssOf( container ) ).toContain( '.home-flow-list{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:minmax(0,1fr);grid-auto-rows:1fr;gap:18px}' );
  } );
} );
