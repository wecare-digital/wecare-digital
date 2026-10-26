'use strict';

/**
 * homeprobe - the home hero's degradation gate: what the pill does when the happy path
 * does not hold.
 *
 * WHY THIS EXISTS SEPARATELY FROM animcheck.js. animcheck asserts the rotation's
 * geometry on the happy path - JS running, motion allowed, viewport fixed - and it
 * passes 18/18. Every defect below survived that suite, because each one lives in a
 * state animcheck never enters: no JavaScript, reduced motion, or a viewport that
 * CHANGES after first paint. The three are grouped here because they share one root
 * cause: the pill's visible state is produced by JavaScript and never reconciled.
 *
 * WHAT IT ASSERTS
 *
 * 1. NO-JS. The hero's entrance is opt-OUT: index.tsx ships the hidden start state
 *    (.home-mark::before at scaleX(1) covering the tint, .home-mark-dot at scale(0)) and
 *    lifts it with a .show class added by a 60ms timeout. .home-cycle gets no width at
 *    all until an effect measures one, and it is overflow:hidden with absolutely
 *    positioned children - so with no JS it computes to 0px wide and clips the word
 *    entirely. The headline renders as the fragment "Everyday AI, built for".
 *    The closing band on the same page argues the opposite arrangement at length - see
 *    the .is-armed note - on the grounds that an entrance effect must never be the
 *    reason content cannot be read. This asserts the hero honours that too.
 *
 * 2. RESIZE. cycleW comes from offsetWidth in an effect keyed on cycleIndex only; there
 *    is no resize listener. font-size is clamp(36px,4.3vw,60px), so a word's width is a
 *    function of the viewport. During normal rotation a stale width self-corrects within
 *    2400ms, but under prefers-reduced-motion the interval never starts, so nothing ever
 *    re-measures: the width measured at the old viewport is permanent. Narrow->wide is
 *    the damaging direction, because overflow:hidden then cuts the word.
 *
 * 3. REDUCED-MOTION RESTING STATE. The reduced-motion block sets
 *    .home-mark::before{transform:scaleX(1)} under a comment saying it "settles the pill
 *    into its resting state". scaleX(1) is the START state - the white shutter at full
 *    width, covering the tint. The resting state is scaleX(0), and the sibling rule for
 *    the dot correctly uses scale(1). The inversion is currently INERT because
 *    `.home-layout.show .home-mark::before` scores (0,2,1) against the media rule's
 *    (0,1,1), and a media query adds no specificity. This measures the computed value so
 *    that if anyone ever touches the .show rule, the masking is caught rather than
 *    discovered.
 *
 * 4. FOCUS ORDER. .home-close.is-armed .home-close-cta ships opacity:0 until the band
 *    scrolls into view, and an opacity:0 element is still focusable. This walks Tab from
 *    load and reports any stop that is invisible.
 *
 * 5. ACTION ABOVE THE FOLD. Counts interactive elements whose box starts above the fold,
 *    separating "matches a focusable selector" from "actually visible" from "inside
 *    <main>". The last number is the one that matters and it is currently 0.
 *
 * HISTORY VS CURRENT STATE. Sections 1-3 record the defects this probe was written against, in
 * the original home-* pill. They are not how the pill works now. Today the pill ships SETTLED:
 * index.tsx starts RotatingPill at phase 'final', so the exported HTML already has the shutter
 * at scaleX(0) and the dot at scale(1), and JavaScript only moves it to 'armed' then 'shown'
 * once motion is allowed. The no-JS assertions therefore pass because nothing has to be lifted.
 * The assertions themselves are unchanged.
 *
 * SELECTORS FOLLOW RotatingPill (rp-*), NOT THE OLD home-* PILL. #420 moved the pill into
 * src/components/RotatingPill.tsx and its classes became .rp-mark, .rp-mark-dot, .rp-cycle and
 * .rp-cyc-word. This probe kept querying the home-* names, found no pill, and so could not see
 * the regression #420 shipped: the export rendered phase 'armed', and with JavaScript off the
 * white shutter covered the tint and the dot sat at scale(0).
 *
 * Run: node tools/browser/homeprobe.js   (needs out/ - see tools/browser/README.md)
 */

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

let pass = 0;
let fail = 0;
const ok = ( name, detail ) => { pass++; console.log( `  ok   ${name}${detail ? ` - ${detail}` : ''}` ); };
const bad = ( name, detail ) => { fail++; console.log( `  FAIL ${name}${detail ? ` - ${detail}` : ''}` ); };
const check = ( cond, name, detail ) => ( cond ? ok( name, detail ) : bad( name, detail ) );

// scaleX is the `a` component of the computed matrix.
const scaleXOf = m => {
  const n = /matrix\(([^)]+)\)/.exec( m );
  return n ? parseFloat( n[ 1 ].split( ',' )[ 0 ] ) : NaN;
};
const scaleYOf = m => {
  const n = /matrix\(([^)]+)\)/.exec( m );
  return n ? parseFloat( n[ 1 ].split( ',' )[ 3 ] ) : NaN;
};

const pillState = () => {
  const mark = document.querySelector( '.rp-mark' );
  const dot = document.querySelector( '.rp-mark-dot' );
  const cycle = document.querySelector( '.rp-cycle' );
  const word = document.querySelector( '.rp-cyc-word.on' );
  const head = document.querySelector( '.home-head' );
  // head is read below for its font size, so a missing h1 must report rather than throw.
  if ( !mark || !cycle || !word || !head ) return { error: 'hero pill not found' };
  return {
    hasShow: !!document.querySelector( '.home-layout.show' ),
    shutter: getComputedStyle( mark, '::before' ).transform,
    dot: dot ? getComputedStyle( dot ).transform : null,
    setWidth: cycle.style.width || null,
    boxWidth: +cycle.getBoundingClientRect().width.toFixed( 1 ),
    needsWidth: word.scrollWidth,
    word: word.textContent,
    font: getComputedStyle( head ).fontSize,
  };
};

( async () => {
  const t = await target();
  const browser = await launch();
  const url = `${t.base}/`;

  try {
    console.log( `homeprobe - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}\n` );

    // ---------------- 1. baseline, so the later numbers mean something ----------------
    console.log( 'Baseline (JS on, motion allowed) @1280x900' );
    {
      const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
      const page = await ctx.newPage();
      await gotoStable( page, url );
      await page.waitForTimeout( 1800 );
      const s = await page.evaluate( pillState );
      console.log( `       word "${s.word}" pill ${s.setWidth} box ${s.boxWidth}px font ${s.font}` );
      check( scaleXOf( s.shutter ) === 0, 'shutter is lifted, so the tint shows', `scaleX ${scaleXOf( s.shutter )}` );
      check( scaleYOf( s.dot ) === 1, 'dot has popped', `scale ${scaleYOf( s.dot )}` );
      check( s.boxWidth > 0, 'pill has width', `${s.boxWidth}px` );
      await ctx.close();
    }

    // ---------------- 2. no JavaScript ----------------
    console.log( '\nJavaScript disabled @1280x900' );
    {
      const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 }, javaScriptEnabled: false } );
      const page = await ctx.newPage();
      await page.goto( url, { waitUntil: 'load' } );
      await page.waitForTimeout( 400 );
      const s = await page.evaluate( pillState );
      console.log( `       .show applied: ${s.hasShow} | pill set width: ${s.setWidth || '(none)'} | box ${s.boxWidth}px` );
      check( s.boxWidth > 0, 'the rotating word is not clipped away entirely',
        s.boxWidth === 0
          ? 'REGRESSION RISK: .home-cycle computes to 0px, so the h1 reads only "Everyday AI, built for"'
          : `${s.boxWidth}px` );
      check( scaleXOf( s.shutter ) === 0, 'the tint is visible without JS',
        scaleXOf( s.shutter ) === 1 ? 'white shutter still covers the pill at scaleX(1)' : 'lifted' );
      check( scaleYOf( s.dot ) === 1, 'the dot is visible without JS',
        scaleYOf( s.dot ) === 0 ? 'still at scale(0)' : 'popped' );
      await ctx.close();
    }

    // ---------------- 3. reduced motion, then a resize ----------------
    console.log( '\nprefers-reduced-motion: reduce' );
    {
      const ctx = await browser.newContext( { viewport: { width: 480, height: 900 }, reducedMotion: 'reduce' } );
      const page = await ctx.newPage();
      await gotoStable( page, url );
      await page.waitForTimeout( 900 );

      const atNarrow = await page.evaluate( pillState );
      // The explanation here described the OLD mechanism and had to be rewritten with it.
      // It read "the scaleX(1) rule must stay masked ... the media rule asks for 1 and is
      // out-specified by .home-layout.show", which was true when scaleX(1) was the CSS
      // DEFAULT and .show removed it. The entrance is now opt-in: scaleX(0) is the default,
      // .home-layout.is-armed applies the start state, and the reduced-motion block is scoped
      // to that same selector so it can win rather than winning by accident. The assertion is
      // unchanged - the tint must be visible - but the reason is the opposite one.
      check( scaleXOf( atNarrow.shutter ) === 0,
        'reduced motion leaves the tint visible, because the finished state is the default',
        `computed scaleX ${scaleXOf( atNarrow.shutter )}; JS never adds .is-armed under reduced motion, `
        + 'and the media block also overrides it at equal specificity if the preference changes later' );

      const first = atNarrow.word;
      await page.waitForTimeout( 3000 );
      const later = await page.evaluate( pillState );
      check( later.word === first, 'the rotation stays put under reduced motion', `${first} -> ${later.word}` );

      console.log( `       at 480 : pill ${atNarrow.setWidth} / word needs ${atNarrow.needsWidth}px / font ${atNarrow.font}` );
      await page.setViewportSize( { width: 1280, height: 900 } );
      await page.waitForTimeout( 900 );
      const atWide = await page.evaluate( pillState );
      console.log( `       at 1280: pill ${atWide.setWidth} / word needs ${atWide.needsWidth}px / font ${atWide.font}` );
      const lost = atWide.needsWidth - parseFloat( atWide.setWidth );
      check( lost <= 0.5, 'the pill re-measures after a resize',
        lost > 0.5
          ? `overflow:hidden cuts ${lost.toFixed( 0 )}px (${( 100 * lost / atWide.needsWidth ).toFixed( 0 )}%) off "${atWide.word}" `
            + '- nothing re-measures because the rotation interval never starts under reduced motion'
          : 'width tracks the word' );
      await ctx.close();
    }

    // ---------------- 3b. the empty pill is on the HAPPY path too ----------------
    // Independently found by commit 869760f7 (F2) while this audit was running, and worth
    // its own assertion because it changes who is affected: not just no-JS visitors.
    // cycleW starts null, so the first React render writes no inline width, and
    // .home-cycle is inline-block with absolutely positioned children - intrinsic width 0.
    // The measuring effect runs after mount, so there is a real window where every visitor
    // sees an empty pill. Sampled per animation frame from document start.
    console.log( '\nFirst paint, JS on - how long the pill is empty for everyone' );
    {
      const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
      await ctx.addInitScript( () => {
        window.__w = [];
        const tick = () => {
          const el = document.querySelector( '.rp-cycle' );
          if ( el ) window.__w.push( { t: +performance.now().toFixed( 1 ), w: +el.getBoundingClientRect().width.toFixed( 1 ) } );
          if ( window.__w.length < 240 ) requestAnimationFrame( tick );
        };
        requestAnimationFrame( tick );
      } );
      const page = await ctx.newPage();
      await page.goto( url, { waitUntil: 'load' } );
      await page.waitForTimeout( 2500 );
      const s = await page.evaluate( () => window.__w );
      const zero = s.filter( x => x.w === 0 );
      const firstPainted = s.find( x => x.w > 0 );
      const ms = firstPainted && s.length ? firstPainted.t - s[ 0 ].t : null;
      console.log( `       ${s.length} frames sampled; ${zero.length} with width 0` );
      check( zero.length === 0, 'the pill never paints empty on a normal load',
        zero.length
          ? `empty for ~${ms.toFixed( 0 )}ms across ${zero.length} frame(s) - cycleW starts null, `
            + 'so the first render has no width and the effect only runs after mount'
          : 'width present from the first sampled frame' );
      await ctx.close();
    }

    // ---------------- 4 & 5. focus order and action above the fold ----------------
    console.log( '\nFocus order and action above the fold @1280x900' );
    {
      const ctx = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
      const page = await ctx.newPage();
      await gotoStable( page, url );
      await page.waitForTimeout( 900 );

      const counts = await page.evaluate( () => {
        const vh = window.innerHeight;
        const sel = 'a[href],button,input,select,textarea,[role="button"],[tabindex]:not([tabindex="-1"])';
        const above = Array.from( document.querySelectorAll( sel ) ).filter( el => {
          const r = el.getBoundingClientRect();
          return r.top < vh && r.height > 0;
        } );
        const shown = above.filter( el => {
          for ( let n = el; n; n = n.parentElement ) {
            const cs = getComputedStyle( n );
            if ( cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0 ) return false;
          }
          return true;
        } );
        return {
          dom: above.length,
          visible: shown.length,
          inMain: shown.filter( el => el.closest( 'main' ) ).length,
          list: shown.map( el => {
            const cls = ( el.className || '' ).toString().split( /\s+/ ).filter( c => !c.startsWith( 'jsx-' ) ).join( '.' );
            return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''} "${( el.textContent || '' ).replace( /\s+/g, ' ' ).trim().slice( 0, 28 )}"`;
          } ),
        };
      } );
      console.log( `       focusable-selector matches with a box above the fold: ${counts.dom}` );
      console.log( `       of those, actually visible: ${counts.visible} -> ${counts.list.join( ' | ' )}` );
      // NOT AN ASSERTION ANY MORE, AND THAT IS AN OWNER DECISION RATHER THAN A CLIMBDOWN.
      // This used to fail on 0 actions above the fold. The brief is now explicit: the top
      // band says what the page is about and carries no call to action, no price and no
      // conversion furniture - the action lives in the closing band. So the count is
      // reported, and a change in it is what would be worth noticing.
      console.log( `       actions inside <main> above the fold: ${counts.inMain} `
        + `(0 is intended - this band states what the page is about; the CTA is in the closing band)` );

      const stops = [];
      for ( let i = 0; i < 8; i++ ) {
        await page.keyboard.press( 'Tab' );
        stops.push( await page.evaluate( () => {
          const el = document.activeElement;
          if ( !el || el === document.body ) return { name: '(body)', invisible: false };
          const cls = ( el.className || '' ).toString().split( /\s+/ ).filter( c => !c.startsWith( 'jsx-' ) ).join( '.' );
          const cs = getComputedStyle( el );
          const r = el.getBoundingClientRect();
          return {
            name: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''} "${( el.textContent || '' ).replace( /\s+/g, ' ' ).trim().slice( 0, 26 )}" top=${Math.round( r.top )}`,
            invisible: +cs.opacity === 0 || cs.visibility === 'hidden',
          };
        } ) );
      }
      console.log( '       Tab stops from load:' );
      stops.forEach( ( s, i ) => console.log( `         ${i + 1}. ${s.name}${s.invisible ? '   <-- INVISIBLE' : ''}` ) );
      const ghosts = stops.filter( s => s.invisible );
      check( ghosts.length === 0, 'no Tab stop lands on an invisible control',
        ghosts.length
          ? `${ghosts.length}: ${ghosts.map( g => g.name ).join( ', ' )} - .home-close.is-armed .home-close-cta ships opacity:0 and opacity does not remove an element from the tab order`
          : 'none' );

      await ctx.close();
    }

    console.log( `\n${pass}/${pass + fail} assertions passed` );
    process.exitCode = fail ? 1 : 0;
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
