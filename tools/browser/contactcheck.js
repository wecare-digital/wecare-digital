'use strict';

/**
 * contactcheck - geometry and controls on /contact/.
 *
 * Two things here have to be measured rather than reasoned about, because both live
 * in places CSS cannot see:
 *
 * 1. THE CARD VS THE FIXED HEADER. .cl-card is absolutely positioned 16px inside the
 *    map frame at z-index 1. The site header is position:fixed at z-index 1001 and is
 *    108px tall (96px below 768px). So whenever the map's top edge is near the top of
 *    the viewport, the header paints over the card. That is not hypothetical: anything
 *    that scrolls the section to the top of the viewport - an in-page anchor, a
 *    scrollIntoView, a browser restoring a scroll position, a focus jump - lands the
 *    card underneath the header. This measures exactly how much is covered, so the fix
 *    can be verified rather than eyeballed.
 *
 * 2. GOOGLE'S OWN CONTROLS. On the keyless path the map is a cross-origin iframe, so
 *    the page cannot query, style or count what is inside it - which is precisely why
 *    the claim "three always-on controls" needs a tool that CAN. Playwright drives the
 *    browser rather than the page, so it can enter the frame and report what is
 *    actually painted there, and whether the interaction lock leaves it inert.
 *
 * Both sections print measurements unconditionally. Assertions are only made about
 * things the repo controls.
 *
 *   node tools/browser/contactcheck.js
 *   BASE=http://localhost:3000 node tools/browser/contactcheck.js
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );

const VIEWPORTS = [
  { width: 1440, height: 900, label: 'desktop 1440' },
  { width: 1024, height: 800, label: 'tablet 1024' },
  { width: 768, height: 900, label: 'tablet 768' },
  { width: 390, height: 844, label: 'phone 390' },
];

const results = [];
let failures = 0;

function record( ok, name, detail ) {
  results.push( { ok, name } );
  if ( !ok ) failures++;
  console.log( `  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` - ${detail}` : ''}` );
}

/**
 * Overlap between the card and the fixed header after scrolling the map section to the
 * top of the viewport, which is what an anchor or scrollIntoView does.
 *
 * Rects, not elements. Comparing DOM nodes tells you nothing about what a visitor can
 * see; comparing getBoundingClientRect tells you everything. Both mistakes have
 * produced false results in this repo before.
 */
async function measureOverlap( page ) {
  return page.evaluate( () => {
    const header = document.querySelector( '.hdr' );
    const card = document.querySelector( '.cl-card' );
    const map = document.querySelector( '.cl-map' );
    if ( !header || !card || !map ) {
      return { error: `missing nodes (header=${!!header} card=${!!card} map=${!!map})` };
    }

    // Scroll the map to the top of the viewport - the anchor / scrollIntoView case.
    map.scrollIntoView( { block: 'start', behavior: 'instant' } );

    const h = header.getBoundingClientRect();
    const c = card.getBoundingClientRect();
    const m = map.getBoundingClientRect();

    // Vertical intersection of the two rects. They overlap horizontally by
    // construction (both start at the left of the measure), so height is the story.
    const covered = Math.max( 0, Math.min( h.bottom, c.bottom ) - Math.max( h.top, c.top ) );

    return {
      headerHeight: Math.round( h.height ),
      headerBottom: Math.round( h.bottom ),
      headerPosition: getComputedStyle( header ).position,
      headerZ: getComputedStyle( header ).zIndex,
      cardZ: getComputedStyle( card ).zIndex,
      cardTop: Math.round( c.top ),
      cardBottom: Math.round( c.bottom ),
      cardHeight: Math.round( c.height ),
      mapTop: Math.round( m.top ),
      covered: Math.round( covered ),
      fullyHidden: covered >= c.height - 0.5,
      scrollMarginTop: getComputedStyle( map ).scrollMarginTop,
    };
  } );
}

/** What Google paints inside the cross-origin iframe, and whether our lock covers it. */
async function inspectMapFrame( page ) {
  const iframe = await page.$( 'iframe.cl-frame' );
  if ( !iframe ) {
    /**
     * KEYED PATH. NEXT_PUBLIC_GOOGLE_BROWSER_KEY is set, so ContactLocation renders a plain
     * div that the Maps JS API draws into - there is no iframe and nothing cross-origin.
     *
     * This branch exists so the harness does NOT go quiet the moment the map changes
     * shape. Returning early with just a note would silently drop every map assertion and
     * leave contactcheck reporting all-green about a surface it had stopped looking at,
     * which is the "warning that looked like a success" failure this repo keeps hitting.
     *
     * The keyed path deliberately enables Map/Satellite. Count visible controls only:
     * Google retains hidden default buttons in the DOM even with disableDefaultUI.
     */
    const host = await page.evaluate( () => {
      const el = document.querySelector( '.cl-frame' );
      if ( !el ) return null;
      const r = el.getBoundingClientRect();
      return {
        w: Math.round( r.width ), h: Math.round( r.height ),
        // The API injects tiles and its attribution into the div. An empty div means the
        // key was rejected, the referrer restriction blocked us, or billing is off - all
        // of which render a blank grey panel rather than throwing.
        children: el.children.length,
        tiles: el.querySelectorAll( 'img' ).length,
        controls: Array.from( el.querySelectorAll( 'button,[role="button"]' ) )
          .filter( button => {
            const rect = button.getBoundingClientRect();
            const style = getComputedStyle( button );
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          } )
          .map( button => ( {
            role: button.getAttribute( 'role' ),
            label: button.getAttribute( 'aria-label' ) || button.getAttribute( 'title' ) || button.textContent.trim(),
          } ) ),
        role: el.getAttribute( 'role' ),
        ariaLabel: el.getAttribute( 'aria-label' ),
      };
    } );
    return { keyed: true, host };
  }

  // The frame is cross-origin. Playwright reaches it anyway; the PAGE cannot, which is
  // the whole reason these controls cannot be removed with CSS.
  const frame = await iframe.contentFrame();
  if ( !frame ) return { error: 'iframe present but no content frame' };

  try {
    await frame.waitForLoadState( 'domcontentloaded', { timeout: 20000 } );
  } catch { /* report whatever did load */ }

  /**
   * THE CANARY for the undocumented keyless endpoint. maps?q=...&output=embed is
   * long-lived and widely used but carries no compatibility promise, so if Google ever
   * withdraws it the frame goes blank and the only signal is a visitor noticing. This
   * asserts the frame actually painted map imagery AND that it resolved to the right
   * city, which is what distinguishes "working" from "rendered the whole planet" - the
   * failure mode a place_id query silently produced.
   */
  let canary = null;
  try {
    const tileUrls = await frame.evaluate( () =>
      Array.from( document.querySelectorAll( 'img' ) )
        .filter( i => i.naturalWidth > 0 )
        .map( i => i.src ) );

    // What WE asked for, read off our own iframe src rather than duplicated here, so
    // this cannot drift from the component.
    const src = await page.$eval( 'iframe.cl-frame', el => el.getAttribute( 'src' ) );
    const q = /[?&]q=(-?[\d.]+),(-?[\d.]+)/.exec( src );
    const z = /[?&]z=(\d+)/.exec( src );

    /**
     * NOT A TEXT MATCH. The obvious canary - look for "Kolkata" in the frame - does not
     * work: place labels are rasterised INTO the tile images, so the frame carries only
     * ~65 characters of text and the check fails while the map is perfectly correct.
     * That is a false failure, and the sort this file exists to avoid.
     *
     * Google's tile URLs carry the coordinates instead, as !1i<zoom>!2i<x>!3i<y> in the
     * pb parameter. Converting our own lat/lng to a Web Mercator tile index and comparing
     * proves the stronger thing anyway: not merely that something rendered, but that
     * Google resolved OUR query rather than defaulting to the whole planet - which is the
     * exact failure a place_id query produced silently.
     */
    let expected = null;
    let matched = 0;
    if ( q && z ) {
      const lat = Number( q[ 1 ] ), lng = Number( q[ 2 ] ), zoom = Number( z[ 1 ] );
      const n = 2 ** zoom;
      const latRad = lat * Math.PI / 180;
      expected = {
        zoom,
        x: Math.floor( ( lng + 180 ) / 360 * n ),
        y: Math.floor( ( 1 - Math.asinh( Math.tan( latRad ) ) / Math.PI ) / 2 * n ),
      };
      for ( const u of tileUrls ) {
        const m = /!1i(\d+)!2i(\d+)!3i(\d+)/.exec( u );
        if ( !m ) continue;
        const [ , tz, tx, ty ] = m.map( Number );
        // A 668x500 viewport spans a handful of 256px tiles either side of centre, so
        // allow a small window rather than demanding the exact centre tile.
        if ( tz === expected.zoom && Math.abs( tx - expected.x ) <= 4 && Math.abs( ty - expected.y ) <= 4 ) matched++;
      }
    }

    canary = { tiles: tileUrls.length, expected, matched, requested: q ? `${q[ 1 ]},${q[ 2 ]}` : null };
  } catch { /* reported as null below */ }

  let controls;
  try {
    controls = await frame.evaluate( () => {
      // Google's embed paints controls as buttons / [role=button] / anchors. Collect
      // anything interactive that is actually visible and has a box.
      const nodes = Array.from( document.querySelectorAll( 'button,[role="button"],a[href]' ) );
      return nodes.map( n => {
        const r = n.getBoundingClientRect();
        const cs = getComputedStyle( n );
        return {
          tag: n.tagName.toLowerCase(),
          label: ( n.getAttribute( 'aria-label' ) || n.getAttribute( 'title' ) || n.textContent || '' ).trim().slice( 0, 60 ),
          x: Math.round( r.x ), y: Math.round( r.y ),
          w: Math.round( r.width ), h: Math.round( r.height ),
          // INLINE ON PURPOSE - window.__visible cannot reach here. This evaluate runs
          // inside Google's CROSS-ORIGIN iframe, and lib/visible.js installs its predicate
          // with addInitScript, which does not define it in that frame's context. Converted
          // to the shared helper this threw "window.__visible is not a function" inside
          // frame.evaluate, and the surrounding try/catch swallowed it into
          // "could not inspect" - so the suite reported 8/8 instead of 12/13 and the five
          // in-frame control assertions silently stopped running. A conversion that makes a
          // suite pass by measuring less is worse than the inconsistency it tidied.
          visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0',
        };
      } ).filter( n => n.visible );
    } );
  } catch ( e ) {
    return { error: `could not read frame contents: ${e.message}` };
  }

  const lock = await page.evaluate( () => {
    const l = document.querySelector( '.cl-lock' );
    const f = document.querySelector( '.cl-frame' );
    if ( !l || !f ) return null;
    const lr = l.getBoundingClientRect();
    const fr = f.getBoundingClientRect();
    return {
      // Distance from the frame's bottom edge that the lock deliberately leaves
      // uncovered, so Google's attribution stays clickable.
      uncoveredBottomPx: Math.round( fr.bottom - lr.bottom ),
      coversTop: lr.top <= fr.top + 0.5,
      zIndex: getComputedStyle( l ).zIndex,
      frameHeight: Math.round( fr.height ),
      frameWidth: Math.round( fr.width ),
      // How far down the frame the lock stops. Control coordinates are relative to
      // the frame's own viewport, so this is directly comparable to them.
      lockBottomWithinFrame: Math.round( lr.bottom - fr.top ),
    };
  } );

  /**
   * PER-CONTROL COVERAGE. The lock deliberately stops short of the frame's bottom edge
   * to leave Google's attribution clickable - so "the lock covers the top" does NOT
   * establish that every control is inert. Any control whose box extends past the
   * lock's bottom edge is still reachable by a real pointer. Comparing each control's
   * rect against the lock's bottom is the only way to know which.
   */
  if ( lock ) {
    for ( const c of controls ) {
      const controlBottom = c.y + c.h;
      c.coveredByLock = controlBottom <= lock.lockBottomWithinFrame;
      c.exposedPx = Math.max( 0, controlBottom - lock.lockBottomWithinFrame );
    }
  }

  /**
   * HIT TEST, because rect arithmetic can still be wrong. A control's box extending
   * past the lock only SUGGESTS a pointer can reach it; what settles it is asking the
   * document which element actually receives a click at that point. If the answer is
   * the iframe, the event goes to Google. If it is .cl-lock, the control is genuinely
   * inert. This converts the claim into an observation.
   */
  if ( lock ) {
    const probes = controls
      .filter( c => !c.coveredByLock )
      .map( c => ( {
        label: c.label,
        // Frame-relative coords -> page coords, aiming at the middle of the strip of
        // the control that sits below the lock.
        px: c.x + Math.round( c.w / 2 ),
        py: lock.lockBottomWithinFrame + Math.max( 1, Math.round( c.exposedPx / 2 ) ),
      } ) );

    const hits = await page.evaluate( probeList => {
      const f = document.querySelector( '.cl-frame' );

      // SCROLL IT INTO VIEW FIRST. elementFromPoint takes VIEWPORT coordinates and
      // returns null for any point outside the viewport. The map sits below the fold,
      // so probing without scrolling returns null for every control - which read as
      // "the click was blocked" and made this whole check pass vacuously. A null hit is
      // now reported as inconclusive rather than as a pass.
      f.scrollIntoView( { block: 'center', behavior: 'instant' } );

      const fr = f.getBoundingClientRect();
      return probeList.map( p => {
        const x = fr.x + p.px;
        const y = fr.y + p.py;
        const inViewport = x >= 0 && y >= 0 && x <= window.innerWidth && y <= window.innerHeight;
        const el = inViewport ? document.elementFromPoint( x, y ) : null;
        return {
          label: p.label,
          inViewport,
          hit: el ? ( ( typeof el.className === 'string' && el.className.trim() ) || el.tagName.toLowerCase() ) : '(null)',
          tag: el ? el.tagName.toLowerCase() : null,
        };
      } );
    }, probes );

    for ( const h of hits ) {
      const c = controls.find( x => x.label === h.label );
      if ( !c ) continue;
      c.hitElement = h.hit;
      c.reachesGoogle = h.tag === 'iframe';
      // Inconclusive is NOT the same as blocked, and conflating them is how this
      // check silently passed while three controls were reachable.
      c.inconclusive = h.tag === null;
    }
  }

  return { keyed: false, controls, lock, canary };
}

async function main() {
  const t = await target();
  const browser = await launch();
  console.log( `contactcheck - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}\n` );

  try {
    console.log( 'Card vs fixed header, with the map section scrolled to the top of the viewport' );
    for ( const vp of VIEWPORTS ) {
      const context = await browser.newContext( { viewport: { width: vp.width, height: vp.height } } );
      const page = await context.newPage();
      await gotoStable( page, `${t.base}/contact/` );
      await page.waitForSelector( '.cl-card', { timeout: 15000 } );
      // The live row (IST + weather) changes the card's height once it arrives, and it
      // is the TALLER state that matters, so give it a moment to land.
      await page.waitForTimeout( 1200 );

      const m = await measureOverlap( page );
      if ( m.error ) { record( false, `${vp.label}`, m.error ); await context.close(); continue; }

      console.log(
        `  ${vp.label.padEnd( 13 )} header ${String( m.headerHeight ).padStart( 3 )}px (z${m.headerZ})` +
        `  card ${m.cardHeight}px @top ${String( m.cardTop ).padStart( 3 )}px (z${m.cardZ})` +
        `  scroll-margin-top ${m.scrollMarginTop}` +
        `  ->  COVERED ${m.covered}px${m.fullyHidden ? ' (card entirely hidden)' : ''}`
      );

      record( m.covered === 0, `${vp.label}: card clear of the fixed header when scrolled into view`,
        m.covered === 0 ? 'no overlap' : `${m.covered}px of a ${m.cardHeight}px card is behind the header` );

      await context.close();
    }

    // The heading carries id="cl-title", so /contact/#cl-title is a real URL someone can
    // link to. Following it must not park the heading behind the fixed header.
    console.log( '\nAnchor navigation to /contact/#cl-title' );
    for ( const vp of VIEWPORTS ) {
      const context = await browser.newContext( { viewport: { width: vp.width, height: vp.height } } );
      const page = await context.newPage();
      await gotoStable( page, `${t.base}/contact/#cl-title` );
      await page.waitForSelector( '.cl-h2', { timeout: 15000 } );
      await page.waitForTimeout( 400 );

      const m = await page.evaluate( () => {
        const header = document.querySelector( '.hdr' );
        const h2 = document.querySelector( '.cl-h2' );
        const hr = header.getBoundingClientRect();
        const tr = h2.getBoundingClientRect();
        return {
          covered: Math.round( Math.max( 0, Math.min( hr.bottom, tr.bottom ) - Math.max( hr.top, tr.top ) ) ),
          h2Height: Math.round( tr.height ),
          h2Top: Math.round( tr.top ),
          smt: getComputedStyle( h2 ).scrollMarginTop,
        };
      } );

      console.log( `  ${vp.label.padEnd( 13 )} h2 ${m.h2Height}px @top ${String( m.h2Top ).padStart( 3 )}px  scroll-margin-top ${m.smt}  ->  COVERED ${m.covered}px` );
      record( m.covered === 0, `${vp.label}: #cl-title heading clear of the header`,
        m.covered === 0 ? 'no overlap' : `${m.covered}px of a ${m.h2Height}px heading hidden` );
      await context.close();
    }

    console.log( '\nGoogle controls inside the map frame' );
    const context = await browser.newContext( { viewport: { width: 1440, height: 900 } } );
    const page = await context.newPage();
    await gotoStable( page, `${t.base}/contact/` );
    // Google's embed pulls its own tiles and chrome after load; measuring too early
    // reports zero controls and would look like a clean result.
    await page.waitForTimeout( 2500 );
    const frameInfo = await inspectMapFrame( page );

    if ( frameInfo.keyed ) {
      const h = frameInfo.host;
      console.log( '  keyed Maps JS path is active (no iframe)' );
      if ( !h ) {
        record( false, 'keyed map host element present', '.cl-frame not found' );
      } else {
        console.log( `  map div ${h.w}x${h.h}, ${h.children} child node(s), ${h.tiles} img tile(s), ${h.controls.length} visible control(s), role=${h.role}` );
        record( h.w > 0 && h.h > 0, 'keyed map div has a box', `${h.w}x${h.h}` );
        record( h.children > 0 || h.tiles > 0,
          'Maps JS actually painted into the div (key accepted, referrer allowed, billing on)',
          `${h.children} children / ${h.tiles} tiles - zero means a blank grey panel, not an exception` );
        const mapTypes = h.controls.filter( control => control.role === 'menuitemradio'
          && /^(Show street map|Show satellite imagery)$/.test( control.label ) );
        const unexpected = h.controls.filter( control => !mapTypes.includes( control )
          && !/^(Map Data|Keyboard shortcuts)$/.test( control.label ) );
        record( mapTypes.length === 2, 'approved Map/Satellite choice remains available',
          mapTypes.map( control => control.label ).join( ', ' ) );
        record( unexpected.length === 0, 'no unexpected visible map controls',
          unexpected.map( control => control.label ).join( ', ' ) || 'none' );
      }
    } else if ( frameInfo.error ) {
      console.log( `  (could not inspect: ${frameInfo.error})` );
    } else {
      const cy = frameInfo.canary;
      if ( cy ) {
        console.log( `  canary: ${cy.tiles} tile(s) loaded; requested ${cy.requested}` +
          ( cy.expected ? ` -> expected tile z${cy.expected.zoom} x${cy.expected.x} y${cy.expected.y}; ${cy.matched} tile(s) within 4 of it` : '' ) );
        record( cy.tiles > 0,
          'keyless embed still paints map imagery (endpoint not withdrawn)',
          `${cy.tiles} tiles loaded` );
        record( cy.matched > 0,
          'served tiles match the coordinates we asked for (not the whole planet)',
          cy.expected ? `${cy.matched}/${cy.tiles} tiles at z${cy.expected.zoom} near x${cy.expected.x} y${cy.expected.y}` : 'could not parse our own iframe src' );
      } else {
        record( false, 'keyless embed canary readable', 'could not read frame contents' );
      }

      const L = frameInfo.lock;
      console.log( `  frame ${L?.frameWidth}x${L?.frameHeight}px; lock covers y 0..${L?.lockBottomWithinFrame}, leaving the bottom ${L?.uncoveredBottomPx}px uncovered for attribution (z${L?.zIndex})` );
      console.log( `  ${frameInfo.controls.length} visible interactive element(s) painted by Google:` );
      for ( const c of frameInfo.controls ) {
        const verdict = c.inconclusive ? 'INCONCLUSIVE (no element at that point)'
          : c.reachesGoogle ? '-> REACHES GOOGLE' : '(blocked by our overlay)';
        const state = c.coveredByLock
          ? 'inert (under lock)'
          : `${c.exposedPx}px below the lock; click lands on <${c.hitElement}> ${verdict}`;
        console.log( `    - ${c.tag.padEnd( 6 )} "${c.label}" ${c.w}x${c.h} at (${c.x},${c.y})  ${state}` );
      }

      // Attribution MUST stay reachable - that is a licence condition, not a control.
      // Everything else being reachable is a defect, because the map is meant to be a
      // fixed illustration.
      const isAttribution = c => /terms|report a map error|open this area/i.test( c.label );
      const exposedControls = frameInfo.controls.filter( c => !c.coveredByLock && !isAttribution( c ) && c.reachesGoogle );
      const attribution = frameInfo.controls.filter( isAttribution );

      record( attribution.length > 0 && attribution.every( c => !c.coveredByLock ),
        'Google attribution links remain reachable (licence condition)',
        attribution.map( c => `"${c.label}"` ).join( ', ' ) || 'none found' );

      // Any inconclusive probe fails too. A check that cannot tell must not report ok.
      const inconclusive = frameInfo.controls.filter( c => !c.coveredByLock && c.inconclusive );
      record( inconclusive.length === 0, 'hit test conclusive for every exposed element',
        inconclusive.length ? `${inconclusive.length} probe(s) hit no element` : 'all probes resolved' );

      record( exposedControls.length === 0,
        'every Google CONTROL is actually inert',
        exposedControls.length
          ? `${exposedControls.length} still reachable: ` + exposedControls.map( c => `"${c.label}" (+${c.exposedPx}px)` ).join( ', ' )
          : 'all controls sit under the lock' );
    }
    await context.close();
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `\n${results.length - failures}/${results.length} assertions passed` );
  if ( failures ) { console.log( `${failures} FAILED` ); process.exit( 1 ); }
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
