import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import HomePage from '../pages/index';

vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );

const cssOf = ( container: HTMLElement ) =>
  Array.from( container.querySelectorAll( 'style' ) ).map( node => node.textContent || '' ).join( '\n' );

describe( 'WECARE.DIGITAL Home', () => {
  // Replaces an assertion that the body stays blank "until the Home design is
  // decided". The rotating headline is that decision, so the old test would have
  // passed while describing the opposite of what ships.
  it( 'renders the rotating headline around a stable frame', () => {
    render( <HomePage /> );
    const heading = screen.getByRole( 'heading', { level: 1 } );

    // Only the pill rotates; the frame does not.
    expect( heading.textContent ).toMatch( /^Everyday AI, built for/ );
  } );

  it( 'carries the cost and complexity half of the positioning in the body line', () => {
    const { container } = render( <HomePage /> );

    // The headline enacts breadth via the rotation, so this line has to carry the
    // rest of the claim. One sentence, one body level.
    const sub = container.querySelector( '.home-sub' );
    expect( sub ).toBeInTheDocument();
    expect( sub?.textContent?.replace( /\s+/g, ' ' ).trim() )
      .toBe( 'Transparent pricing, guided journeys, and dependable support — on one shared foundation.' );
    expect( container.querySelectorAll( '.home-sub' ) ).toHaveLength( 1 );
  } );

  it( 'keeps the rotating words within a narrow length band', () => {
    const { container } = render( <HomePage /> );
    const words = Array.from( container.querySelectorAll( '.rp-cyc-word' ) )
      .map( w => ( w.textContent || '' ) );

    // The pill animates to each word's measured width, so the spread between the
    // shortest and longest word is how far the headline's tail travels each tick.
    // Two characters is the band. This is a margin-of-safety bound, not a fix for an
    // observed snap - measured sampling shows wider sets still glide. The defect it
    // guards against is the headline reflowing on the longest word only; the browser
    // harness measures h1 height across a rotation for that.
    // The character band is GONE as an assertion, and that is deliberate rather than
    // a loosening. It was a proxy for "the headline must not reflow", and the owner's
    // four added words take the spread to 9 characters (travel -> ai applications),
    // which no proxy bound can usefully cover.
    //
    // What replaced it is the actual constraint, measured in a browser: the pill sits
    // on its own line, so the h1's line count is independent of word width, and
    // tools/browser/animcheck.js asserts the h1's height is identical for every word at
    // all 21 viewports from 320 to 1920. Re-run `node tools/browser/animcheck.js` after
    // any word change - a unit test cannot see reflow.
    //
    // The one thing still worth pinning here is that no word is so long it cannot fit
    // the pill's own line at the narrowest breakpoint.
    const lengths = words.map( w => w.length );
    expect( Math.max( ...lengths ) ).toBeLessThanOrEqual( 18 );
  } );

  it( 'exposes the word list to screen readers once, and hides every animated copy', () => {
    const { container } = render( <HomePage /> );

    // One readable copy of the full list...
    const srOnly = container.querySelector( '.rp-sr-only' );
    expect( srOnly ).toBeInTheDocument();
    expect( srOnly?.textContent ).toBe( 'consumers, enterprises, climate tech, frontier tech' );

    // ...and every visually-rotating copy hidden, so the headline is not read out
    // once per word. Each animated word must carry aria-hidden.
    //
    // The count is DERIVED from the screen-reader list rather than hardcoded. It was
    // hardcoded to 9, which meant a word-list change failed this test for the wrong
    // reason - the number, not the behaviour - twice over. Deriving it also pins
    // something the old assertion could not: that the visible rotation and the list
    // read aloud cannot drift apart. If a word is added to one and not the other,
    // this fails, which is the actual accessibility bug worth catching.
    const expectedWords = ( srOnly?.textContent || '' ).split( ', ' ).length;
    const words = Array.from( container.querySelectorAll( '.rp-cyc-word' ) );
    expect( words ).toHaveLength( expectedWords );
    expect( words.map( w => w.textContent ) ).toEqual( ( srOnly?.textContent || '' ).split( ', ' ) );
    words.forEach( word => expect( word ).toHaveAttribute( 'aria-hidden', 'true' ) );

    // Exactly one is active at a time.
    expect( container.querySelectorAll( '.rp-cyc-word.on' ) ).toHaveLength( 1 );
  } );

  it( 'keeps the eyebrow 20px from the headline, not on the 96px section gap', () => {
    const { container } = render( <HomePage /> );

    const hero = container.querySelector( 'main > .home-layout > .home-hero' );
    expect( hero ).toBeInTheDocument();
    expect( hero?.querySelector( '.home-head' ) ).toBeInTheDocument();
    expect( hero?.querySelector( '.home-sub' ) ).toBeInTheDocument();

    /**
     * THE BRAND BADGE IS GONE, AND ITS ABSENCE IS ASSERTED.
     *
     * This test used to require `.home-eyebrow` and the 20px gap under it. The eyebrow held
     * a lime BrandBadge reading WECARE.DIGITAL - the same bag mark at 18px and the same words
     * at 14px that the header renders at 60px and 23px, measured 109px above it on desktop
     * and 73px on a phone. Two lockups saying the same thing, and because the badge came
     * first in the hero it was the first thing anyone read on the site.
     *
     * Re-labelling it was the plan and was dropped: a candidate copy naming the service
     * count is accurate - WorkflowTerminal now runs a 21-step trace, STEPS.length is 21 -
     * but that panel already reports "21/21 services" on this same page, so a service-count
     * eyebrow would have traded a brand duplication for a copy duplication.
     *
     * Asserted as an absence rather than just deleted, so that re-adding a second brand
     * lockup above the fold has to be a decision rather than a reflex.
     */
    expect(
      hero?.querySelector( '.home-eyebrow, .brand-badge' ),
      'the hero must not carry a second brand lockup - the header already states the brand '
      + '109px above it'
    ).toBeNull();
  } );

  it( 'animates on the same constants as the Grahak OS and VayuLok pills', () => {
    const css = cssOf( render( <HomePage /> ).container );

    // These three pages are meant to animate as one family. If one is retuned and
    // the others are not, this fails - which is the point. The 2400ms interval
    // itself lives in JS, so it is not assertable here.
    expect( css ).toContain( 'transition:background-color .52s cubic-bezier(.16,1,.3,1)' );
    expect( css ).toContain( 'transition:transform .78s cubic-bezier(.16,1,.3,1) .18s' );
    expect( css ).toContain( 'transition:transform .5s cubic-bezier(.34,1.56,.64,1) .72s' );
    expect( css ).toContain( 'transition:width .52s cubic-bezier(.16,1,.3,1)' );

    // The dot geometry is measured, not eyeballed - .33em with a .18em gap.
    expect( css ).toContain( 'width:.33em;height:.33em' );
    // margin-INLINE-end, not margin-right. The dot precedes the rotating word, so the gap
    // belongs on whichever side the word is on: under rtl, margin-right put the gap behind
    // the dot and let it touch the glyph it exists to separate. Asserting the logical
    // property keeps the physical one from coming back.
    expect( css ).toContain( 'margin-inline-end:.18em' );
    expect( css ).not.toContain( 'margin-right:.18em' );

    // Reduced motion settles the pill rather than leaving it mid-transition.
    expect( css ).toContain( '@media(prefers-reduced-motion:reduce)' );
  } );

  it( 'holds the headline on the hero h1 rung, which is lighter than section h2', () => {
    const css = cssOf( render( <HomePage /> ).container );

    // 600, not 700. The contract's weight inversion is deliberate and two other
    // pages carry the same guard.
    expect( css ).toContain( 'font-size:var(--public-hero-size)' );
    expect( css ).toContain( 'font-weight:var(--public-hero-weight)' );

    /**
     * TRACKING IS IN em, AND THAT IS THE ASSERTION.
     *
     * It was -2.2px here, with media-query overrides to -1.2px under 768px and -.8px under
     * 480px. A fixed pixel value against a fluid clamp(36px,4.3vw,60px) font means the
     * OPTICAL tightness changes with the viewport: measured across the breakpoints it ran
     * from -2.22% to -6.11% of the font size, a 2.75x spread, worst at 768-820px where the
     * font is still on the 36px clamp floor while the tracking was the value chosen for
     * 60px.
     *
     * -0.04em is -4% at every size. The px form is asserted ABSENT as well, because the
     * failure mode is not deleting this line - it is someone adding a px override back in a
     * media query, which is what produced the spread in the first place.
     */
    expect( css ).toContain( 'letter-spacing:var(--public-hero-tracking)' );

    // SCOPED TO THE .home-head RULE, not searched for across the page. The first version of
    // this assertion scanned the whole stylesheet and failed on .home-flow-title and
    // .home-close-title, which legitimately use -1.2px - they are fixed-size headings, so a
    // px value is correct for them. Only the fluid hero headline must avoid it. The selector
    // `.home-head{` cannot match `.home-head-line{`, because the brace must follow directly.
    const headRule = /\.home-head\{([^}]*)\}/.exec( css );
    expect( headRule, '.home-head rule not found' ).not.toBeNull();
    expect(
      /letter-spacing:-?[\d.]+px/.test( headRule![ 1 ] ),
      'the hero headline must not set letter-spacing in px. Its font size is fluid, so a '
      + 'fixed px value makes optical tracking swing with the viewport - it measured -2.22% '
      + 'to -6.11% of the font size before this became a single em value.'
    ).toBe( false );

    /**
     * And no media query may put a px override back on it - that is what produced the
     * spread, not the base declaration.
     *
     * The bodies are extracted by COUNTING BRACES, not by splitting on '@media'. The split
     * version failed against correct CSS: this stylesheet has media queries for .home-flow
     * and .home-close that appear BEFORE .home-head, so a split chunk ran from one of those
     * queries all the way to the next one and swallowed the hero's own base rule, which the
     * loop then reported as a media override. A brace walk gives each block's real extent.
     */
    const mediaBodies: string[] = [];
    for ( let at = css.indexOf( '@media' ); at !== -1; at = css.indexOf( '@media', at + 1 ) ) {
      const open = css.indexOf( '{', at );
      if ( open === -1 ) break;
      let depth = 0;
      let end = open;
      for ( ; end < css.length; end++ ) {
        if ( css[ end ] === '{' ) depth++;
        else if ( css[ end ] === '}' && --depth === 0 ) break;
      }
      mediaBodies.push( css.slice( open + 1, end ) );
    }
    expect( mediaBodies.length, 'no @media blocks parsed - the brace walk is broken' ).toBeGreaterThan( 0 );

    for ( const body of mediaBodies ) {
      const override = /\.home-head\{([^}]*)\}/.exec( body );
      if ( !override ) continue;
      expect(
        /letter-spacing/.test( override[ 1 ] ),
        'a media query re-declares letter-spacing on .home-head. The em value already scales '
        + 'with the font, so restating it per breakpoint is what caused the 2.75x optical '
        + 'swing this replaced.'
      ).toBe( false );
    }
  } );

  it( 'sizes the first screen in units a phone browser agrees with', () => {
    const css = cssOf( render( <HomePage /> ).container );

    // It was calc(100vh - 69px), with calc(100vh - 85px) under 768px. Neither subtrahend
    // matched anything in the layout - the header is 108/96 and the footer 179/192 - so
    // they could not be maintained against a real height. And 100vh on a phone means the
    // viewport with the browser chrome hidden, so an element sized to it is taller than
    // what can be seen; dvh tracks the visible viewport.
    expect( css ).toContain( 'min-height:100dvh' );
    // vh is kept as the fallback for browsers without dvh, so it must still be there -
    // but never with an arbitrary subtraction.
    expect( css ).toContain( 'min-height:100vh' );
    expect(
      /min-height:calc\(100vh\s*-/.test( css ),
      'min-height must not subtract a magic number from 100vh - the two that were here, '
      + '69px and 85px, corresponded to no element in the layout.'
    ).toBe( false );
  } );

  it( 'gives the pill a resting width in CSS, so it never ships empty', () => {
    const css = cssOf( render( <HomePage /> ).container );

    /**
     * THE PILL USED TO RENDER EMPTY, and a unit test can see the cause even though it
     * cannot see the result.
     *
     * cycleW starts null, so the first render writes no inline width. Every .home-cyc-word
     * was position:absolute, so .home-cycle had NO intrinsic width - it computed to 0px and
     * overflow:hidden clipped the word away completely. The headline read "Everyday AI,
     * built for" with nothing after it: ~200ms on every load (4 painted frames, measured in
     * tools/browser/homeprobe.js) and permanently with JavaScript disabled.
     *
     * Two declarations fix it and both are asserted, because removing either brings the
     * defect back in a different disguise.
     */
    expect( css ).toContain( 'width:max-content' );
    expect(
      css,
      'the active word must return to flow, or .home-cycle has no intrinsic width to rest at'
    ).toContain( 'position:static' );
    expect(
      css,
      'display:inline-block is load-bearing: position:static alone makes this a non-replaced '
      + 'inline box, whose offsetWidth is 0 - the measuring effect would then write width:0px '
      + 'over max-content and the pill would collapse on every load WITH JavaScript'
    ).toContain( 'display:inline-block' );
  } );

  it( 'settles the reduced-motion shutter open, not closed', () => {
    const css = cssOf( render( <HomePage /> ).container );

    /**
     * This block used to set the shutter to scaleX(1) - the START state, a white panel over
     * the tint - under a comment saying it settled the pill. It never bit only because
     * `.home-layout.show .home-mark::before` scores (0,2,1) against the media rule's
     * (0,1,1), so the correct value won by accident. Any edit to the .show rule would have
     * handed every reduced-motion visitor a blank white pill.
     *
     * The older assertion here only checked that the media block EXISTED, which passed
     * either way - so it is the value that is pinned now, scoped to the block.
     */
    /**
     * SELECTED BY CONTENT, NOT BY POSITION. The first version of this took the first
     * `@media(prefers-reduced-motion:reduce)` block on the page - which belongs to
     * WorkflowTerminal, since this page renders it too. The assertion then failed against the
     * wrong component's CSS. A brace walk collects every block and the one carrying
     * `.rp-mark` is the shared pill's (RotatingPill, which the home hero now renders instead
     * of its own inline .home-mark). The pill's own <style jsx> is in the rendered DOM, so
     * its CSS is part of cssOf(container).
     */
    const blocks: string[] = [];
    for ( let at = css.indexOf( '@media(prefers-reduced-motion:reduce)' ); at !== -1;
      at = css.indexOf( '@media(prefers-reduced-motion:reduce)', at + 1 ) ) {
      const open = css.indexOf( '{', at );
      if ( open === -1 ) break;
      let depth = 0, end = open;
      for ( ; end < css.length; end++ ) {
        if ( css[ end ] === '{' ) depth++;
        else if ( css[ end ] === '}' && --depth === 0 ) break;
      }
      blocks.push( css.slice( open + 1, end ) );
    }
    expect( blocks.length, 'no reduced-motion blocks parsed' ).toBeGreaterThan( 0 );
    const body = blocks.find( b => b.includes( '.rp-mark' ) );
    expect( body, 'no reduced-motion block mentions .rp-mark' ).toBeDefined();
    // RotatingPill scopes the settle to .is-armed so it wins over the armed start state.
    expect( body! ).toContain( '.rp-mark.is-armed::before{transform:scaleX(0)}' );
    expect(
      /\.rp-mark(\.is-armed)?::before\{transform:scaleX\(1\)\}/.test( body! ),
      'scaleX(1) is the start state - a white shutter covering the tint - not the resting one'
    ).toBe( false );
  } );

  it( 'declares the Inter stack rather than inheriting it from Amplify', () => {
    const css = cssOf( render( <HomePage /> ).container );

    expect( css ).toContain( 'font-family:var(--font-sans)' );
    const tokens = readFileSync( resolve( process.cwd(), 'src/styles/tokens.css' ), 'utf8' );
    expect( tokens ).toContain( "--font-sans: 'Inter'," );
  } );

  it( 'keeps homepage content below the public header at every breakpoint', () => {
    const { container } = render( <HomePage /> );
    const css = cssOf( container );

    expect( css ).toContain( 'padding-top:108px' );
    expect( css ).toContain( 'padding-top:96px' );
  } );

  it( 'provides a centered responsive canvas with consistent section spacing', () => {
    const { container } = render( <HomePage /> );
    const layout = container.querySelector( 'main > .home-layout' );
    const css = cssOf( container );

    expect( layout ).toBeInTheDocument();
    expect( css ).toContain( 'max-width:var(--public-content-max)' );
    // Bottom padding reduced 96->48 (and 64->40 on mobile) when the Subscribe+Share block
    // became the last child of .home-layout, so the air below the row is a balanced ~48px
    // rather than the full section rhythm. The top padding and gaps are unchanged.
    expect( css ).toContain( 'padding:80px 24px 48px' );
    expect( css ).toContain( 'gap:96px' );
    expect( css ).toContain( 'padding:var(--public-mobile-hero-top) var(--public-mobile-page-gutter) 40px' );
    expect( css ).toContain( 'gap:var(--public-mobile-section-gap)' );
  } );

  it( 'contains the hero so 200%-zoom reflow cannot give the page horizontal scroll', () => {
    const { container } = render( <HomePage /> );
    const css = cssOf( container );

    /**
     * REGRESSION GUARD for the unified-mobile Phase 1 zoom fix.
     *
     * At 200% zoom a <=375px phone reflows to a ~160-188 CSS-px layout viewport. The rotating
     * pill is a nowrap lozenge whose active word returns to flow (position:static), so its
     * measured intrinsic width could not shrink and made .home-head set a ~234px page floor -
     * measured 74px of horizontal overflow at a 160px viewport, 46px at 188px.
     *
     * The fix is containment, not a width change: .home-hero gets min-width:0 (so the flex item
     * may shrink below its content) plus overflow-x:clip (so the pill overflows its OWN box, not
     * the page), and .home-head keeps its 900px cap as min(900px,100%) with min-width:0. Removing
     * any of these brings back the horizontal scroll a unit test cannot see directly, so the
     * declarations are pinned here. overflow-x:hidden is the clip fallback and must stay too.
     */
    const heroRule = /\.home-hero\{([^}]*)\}/.exec( css );
    expect( heroRule, '.home-hero rule not found' ).not.toBeNull();
    expect( heroRule![ 1 ] ).toContain( 'min-width:0' );
    expect( heroRule![ 1 ] ).toContain( 'overflow-x:hidden' );
    expect( heroRule![ 1 ] ).toContain( 'overflow-x:clip' );

    const headRule = /\.home-head\{([^}]*)\}/.exec( css );
    expect( headRule, '.home-head rule not found' ).not.toBeNull();
    expect( headRule![ 1 ] ).toContain( 'max-width:min(900px, 100%)' );
    expect( headRule![ 1 ] ).toContain( 'min-width:0' );

    // The shared pill caps its own box so it cannot exceed the (now shrinkable) hero.
    expect( css ).toContain( 'max-width:100%' );
  } );

  it( 'declares the unified-mobile shared primitives in tokens.css', () => {
    const tokens = readFileSync( resolve( process.cwd(), 'src/styles/tokens.css' ), 'utf8' );

    /**
     * UNIFIED-MOBILE PHASE 1 PRIMITIVES.
     *
     * --tap-min is the canonical 44px tap-target name the pass standardises on; --tap-target
     * stays as an alias that reads it, so existing consumers (form-controls.css) and the
     * pinning tests keep resolving to 44px and the two cannot drift. The safe-area insets are
     * centralised into named --safe-* tokens as the single referenced contract.
     */
    expect( tokens ).toContain( '--tap-min: 44px' );
    expect( tokens ).toContain( '--tap-target: var(--tap-min)' );
    expect( tokens ).toContain( '--safe-top: env(safe-area-inset-top)' );
    expect( tokens ).toContain( '--safe-right: env(safe-area-inset-right)' );
    expect( tokens ).toContain( '--safe-bottom: env(safe-area-inset-bottom)' );
    expect( tokens ).toContain( '--safe-left: env(safe-area-inset-left)' );
    expect( tokens ).toContain( '--public-mobile-hero-size: 40px' );
    expect( tokens ).toContain( '--public-mobile-section-size: 32px' );
    expect( tokens ).toContain( '--public-mobile-card-size: 24px' );
    expect( tokens ).toContain( '--public-mobile-cta-font-size: 18px' );
    expect( tokens ).toContain( '--public-mobile-page-gutter: 16px' );
    expect( tokens ).toContain( '--public-mobile-section-gap: 64px' );
    expect( tokens ).toContain( '--public-mobile-hero-top: 48px' );
    expect( tokens ).toContain( '--public-mobile-form-font-size: 16px' );
    expect( tokens ).toContain( 'font-size: var(--public-mobile-form-font-size) !important' );
    expect( tokens ).toContain( 'min-height: var(--tap-min)' );
  } );

  it( 'uses the approved app-first Home type scale on phones without changing desktop rungs', () => {
    const css = cssOf( render( <HomePage /> ).container );

    expect( css ).toContain( '.home-head{font-size:var(--public-mobile-hero-size);line-height:1.1}' );
    expect( css ).toContain( '.home-flow-title{font-size:var(--public-mobile-section-size)}' );
    expect( css ).toContain( '.home-flow-list strong{font-size:var(--public-mobile-card-size)}' );
    expect( css ).toContain( ':global(.home-close-title){font-size:var(--public-mobile-section-size)}' );
    expect( css ).toContain( ':global(.home-close-cta){font-size:var(--public-mobile-cta-font-size)}' );
    expect( css ).toContain( ':global(.public-share .ps-menu-sub)' );
    expect( css ).toContain( ':global(.public-share .ps-menu-note){font-size:15px}' );

    // The base/desktop rules still consume the shared public tokens. The approved change is a
    // phone reference treatment, not an unreviewed desktop redesign.
    expect( css ).toContain( 'font-size:var(--public-hero-size)' );
    expect( css ).toContain( 'font-size:var(--public-section-size)' );
    expect( css ).toContain( '.home-flow-list strong{display:block;margin:0 0 6px;font-size:max(var(--public-card-size),24px)' );
  } );

  it( 'pins final Home app-hardening and foldable-hinge contracts', () => {
    const css = cssOf( render( <HomePage /> ).container );
    const footer = readFileSync( resolve( process.cwd(), 'src/components/Footer.tsx' ), 'utf8' );
    const closing = readFileSync( resolve( process.cwd(), 'src/components/public/ClosingBand.tsx' ), 'utf8' );
    const layout = readFileSync( resolve( process.cwd(), 'src/styles/Layout.css' ), 'utf8' );
    const document = readFileSync( resolve( process.cwd(), 'src/pages/_document.tsx' ), 'utf8' );
    const steering = readFileSync( resolve( process.cwd(), '.kiro/steering/20-device-compat.md' ), 'utf8' );
    const capacitor = readFileSync( resolve( process.cwd(), 'src/lib/capacitor.ts' ), 'utf8' );
    const app = readFileSync( resolve( process.cwd(), 'src/pages/_app.tsx' ), 'utf8' );

    expect( footer ).toContain( '.ft-tagline{font-size:16px}' );
    expect( footer ).not.toContain( '.ft-tagline{font-size:14px}' );
    expect( closing ).toContain( 'font-size:14px;font-weight:700' );

    expect( layout ).toContain( 'color-scheme: light' );
    expect( layout ).toContain( 'min-height: 100vh' );
    expect( layout ).toContain( 'min-height: 100dvh' );
    expect( document ).toContain( '<meta name="color-scheme" content="light" />' );

    expect( steering ).toContain( 'intentionally light-only' );
    expect( steering ).not.toContain( 'prefers-color-scheme' );
    expect( steering ).toContain( 'width-only emulator does not count as' );
    expect( steering ).toContain( 'true hinge verification' );

    expect( css ).toContain( '@media(horizontal-viewport-segments:2)' );
    expect( css ).toContain( 'width:env(viewport-segment-width 0 0)' );
    expect( css ).toContain( 'width:env(viewport-segment-width 1 0)' );

    expect( capacitor ).toContain( "backgroundColor = '#1a3a2a'" );
    expect( capacitor ).toContain( 'statusBarBackground?: string' );
    expect( app ).toContain( "statusBarBackground: isPublic ? '#ffffff' : '#1a3a2a'" );
    expect( app ).toContain( '<meta name="theme-color" content="#ffffff" />' );
    expect( app ).toContain( '<meta name="apple-mobile-web-app-status-bar-style" content="default" />' );
  } );

  it( 'keeps meaningful terminal text large on phones while reserving 14px for metadata', () => {
    const terminal = readFileSync( resolve( process.cwd(), 'src/components/WorkflowTerminal.tsx' ), 'utf8' );

    expect( terminal ).toContain( '.wt-request{font-size:18px}' );
    expect( terminal ).toContain( '.wt-call-text{font-size:17px}' );
    expect( terminal ).toContain( '.wt-return .wt-line-text{font-size:16px}' );
    expect( terminal ).toContain( '.wt-note .wt-line-text,.wt-sub .wt-line-text{font-size:15px}' );
    expect( terminal ).toContain( '.wt-ai-text{font-size:16px}' );
    expect( terminal ).toContain( '.wt-lane-name{font-size:16px}' );
    expect( terminal ).toContain( '.wt-lane-detail{font-size:15px}' );
    expect( terminal ).toContain( '.wt-foot{font-size:15px}' );
    expect( terminal ).toContain( '.wt-time{font-size:14px}' );
    expect( terminal ).toContain( '.wt-ai-tag{font-size:14px}' );

    // Keep the terminal internally scrollable instead of shrinking meaningful copy to fit.
    expect( terminal ).toContain( 'overflow-y:auto' );
    expect( terminal ).toContain( 'height:min(560px,100dvh)' );
  } );

} );
