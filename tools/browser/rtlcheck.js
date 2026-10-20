'use strict';

/**
 * rtlcheck - does the site survive being mirrored, and does it declare its direction.
 *
 * WHY THIS IS A SEPARATE GATE. Every other harness here loads a page in its shipped
 * direction, which is left-to-right on all 761 routes. The catalogue served to visitors
 * includes Arabic, Persian, Hebrew, Urdu, Pashto and Sindhi, so right-to-left is a state
 * a real reader reaches by pressing one button - and it was a state no suite entered.
 * pageaudit and devicecheck both pass at every width while the footer renders its full
 * stops at the wrong end of the line.
 *
 * WHAT IT ASSERTS, per route:
 *   1. The served HTML DECLARES dir. An undeclared direction is decided by the user agent,
 *      which is the same class of defect as an undeclared color-scheme.
 *   2. Under dir=rtl there is no horizontal overflow. This is the measurement that catches
 *      a physical margin, padding or inset that did not become logical: a left-anchored
 *      absolute box in a mirrored document pushes the page wider than the viewport.
 *   3. Under dir=rtl the fixed chrome stays on screen - the header bar spans the viewport
 *      and the language widget is fully inside it. The widget was pinned with right:20px,
 *      which in Arabic left it on the side a reader's eye ENDS on, over the text.
 *   4. The body's computed direction actually changes. A guard on the mechanism itself:
 *      if setting the attribute stopped taking effect, every other assertion here would
 *      still pass while proving nothing.
 *
 * HOW RTL IS ENTERED, AND WHY BOTH ATTRIBUTES ARE SET. This sets `lang` AND `dir` together,
 * which is what SupportWidget does in production. Setting only `dir` tests a state no
 * visitor can reach, and the first version of this gate did exactly that - it reported the
 * language widget pinned to the right under rtl and blamed the CSS.
 *
 * THE REASON IS NOT OBVIOUS AND IS WORTH STATING. The build does not ship the logical
 * properties this code is written with. Lightning CSS, which Next uses to minify, downlevels
 * `inset-inline-end:20px` for the configured browser targets into a PAIR OF :lang() RULES:
 *
 *   .wc-langbar:not(:is(:lang(ar),:lang(he), ... )){left:auto;right:20px}
 *   .wc-langbar:is(:lang(ar),:lang(he), ... )){left:20px;right:auto}
 *
 * `inset-inline` appears ZERO times in out/. So in the shipped stylesheet, mirroring is
 * keyed on the LANGUAGE attribute, not on `dir` - and `dir="rtl"` alone flips the bidi
 * algorithm while leaving every box physically where it was. The two attributes are not
 * independent here, and anything that sets one without the other gets half a mirror.
 *
 * Run:  node tools/browser/rtlcheck.js
 *       node tools/browser/rtlcheck.js / /contact/
 */

const { target, OUT_DIR } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );
const fs = require( 'fs' );
const path = require( 'path' );

/**
 * ENGINE SELECTION, matching devicecheck.js. Chromium is the default; --firefox runs the same
 * sweep on Gecko. Bidi is implemented per engine, and the specificity behaviour this gate
 * depends on comes from Lightning CSS output rather than from the browser, so a second engine
 * is a real check rather than a formality.
 *
 * --webkit is accepted and CANNOT RUN on this host: Amazon Linux 2023 ships ICU 67 while the
 * Playwright WebKit build links ICU 74. That leaves iOS unverified, because WebKit is the
 * engine behind every browser on iOS. Same blocker as devicecheck.js; closing it needs an
 * Ubuntu-based image.
 */
const ENGINE = process.argv.includes( '--firefox' ) ? 'firefox'
  : process.argv.includes( '--webkit' ) ? 'webkit' : 'chromium';
const launchEngine = async () => {
  if ( ENGINE === 'chromium' ) return launch();
  return require( 'playwright-core' )[ ENGINE ].launch();
};

/**
 * EVERY EXPORTED ROUTE, discovered rather than listed - public pages, inner pages and the
 * authenticated dashboard shells alike. An earlier version of this gate hardcoded the 18
 * public routes, which let "the dashboard is unmirrored" be asserted without being measured.
 * The dashboard renders Layout.tsx's own chrome, so it is a different surface, not a
 * variation on the public one.
 *
 * Blog posts are SAMPLED, not swept: 638 of them share one template, so they would multiply
 * runtime by forty and tell us the same thing once. pageaudit owns the full census.
 */
function discoverRoutes () {
  const out = [];
  const posts = [];
  ( function walk ( dir ) {
    for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
      const p = path.join( dir, entry.name );
      if ( entry.isDirectory() ) {
        if ( entry.name === '_next' ) continue;
        walk( p );
      } else if ( entry.name === 'index.html' ) {
        let r = '/' + path.relative( OUT_DIR, p ).replace( /\\/g, '/' );
        r = r.replace( /index\.html$/, '' );
        ( /^\/post\//.test( r ) ? posts : out ).push( r === '/' ? '/' : r );
      }
    }
  } )( OUT_DIR );
  return out.sort().concat( posts.sort().slice( 0, 2 ) );
}

/**
 * VIEWPORTS INCLUDING THE FOLDABLE POSTURES, because "wide and short" is where a mirrored
 * absolute inset is most visible and it was the one shape this gate originally skipped -
 * devicecheck covers those postures but only left-to-right, so the combination of mirrored
 * AND short was untested by anything.
 */
const VIEWPORTS = [
  { n: 'desktop', w: 1280, h: 900 },
  { n: 'phone', w: 390, h: 844 },
  { n: 'fold-folded', w: 280, h: 653 },
  { n: 'fold-land', w: 653, h: 280 },   // wide AND short
  { n: 'zflip-land', w: 880, h: 360 },  // wide AND short
  { n: 'zfold-cover-land', w: 882, h: 344 },
];

const PROBE = () => {
  const de = document.documentElement;
  const body = document.body;

  // Overflow is measured against documentElement, matching pageaudit, so a number here is
  // comparable with the ltr number that harness reports.
  const overflow = Math.max( 0, de.scrollWidth - de.clientWidth );

  const vw = de.clientWidth;
  const rect = el => {
    if ( !el ) return null;
    const r = el.getBoundingClientRect();
    return { l: Math.round( r.left ), r: Math.round( r.right ), w: Math.round( r.width ), h: Math.round( r.height ) };
  };

  const header = document.querySelector( 'header.hdr' ) || document.querySelector( 'header' );
  const widget = document.querySelector( '.wc-langbar' );

  // Anything sticking out past either edge. Reported with a selector so a failure names the
  // element rather than only the number.
  const strays = [];
  for ( const el of document.querySelectorAll( 'header, footer, main, .wc-langbar, .nav-menu, section, .home-mark, .home-cycle' ) ) {
    const cs = getComputedStyle( el );
    // Hidden menus still have geometry in Firefox/WebKit. They are not paintable or
    // interactive and must not count as viewport strays until opened.
    if ( cs.display === 'none' || cs.visibility === 'hidden' ) continue;
    const r = el.getBoundingClientRect();
    if ( r.width === 0 && r.height === 0 ) continue;
    if ( r.right > vw + 1 || r.left < -1 ) {
      strays.push( {
        sel: el.tagName.toLowerCase() + '.' + ( el.className || '' ).split( /\s+/ ).filter( c => !/^jsx-/.test( c ) ).join( '.' ),
        l: Math.round( r.left ), r: Math.round( r.right ),
      } );
    }
  }

  /**
   * MIRROR SYMMETRY, which is the measurement that answers "is it actually mirrored" rather
   * than only "does it overflow". For a correctly mirrored element, its distance from the
   * inline-START edge is the same in both directions: left in ltr equals (viewport - right)
   * in rtl. A physical padding-left, margin-left or border-left that was never made logical
   * shows up as a difference, and nothing else does.
   *
   * THREE CLASSES ARE EXCLUDED, each for a real reason rather than to flatter the number.
   *   - EVERY INLINE-LEVEL BOX, including inline-block and inline-flex. A mirrored paragraph
   *     reflows, and an inline-level box is placed by line layout rather than against its
   *     container's edge, so it legitimately lands somewhere else - measuring it reports the
   *     bidi algorithm working as a fault. inline-block and inline-flex were allowed through
   *     at first, on the theory that a "box" should hold its place; the rotating hero pill and
   *     the brand badge then reported 79-555px of asymmetry for reflowing exactly as they
   *     should. Only block, flex and grid containers have a position defined relative to their
   *     container, which is what this assertion is about.
   *   - Subtrees under an explicit dir attribute. A terminal panel or a code sample is
   *     left-to-right by SYNTAX and is locked with dir="ltr" on purpose; it is supposed to be
   *     asymmetric, and a gate that failed on it would be arguing with the fix.
   *   - Class names that appear MORE THAN ONCE on the page. A mirrored flex row reverses its
   *     children, which is correct mirroring and moves every item's offset - so a row of
   *     cards reports a large difference for doing exactly the right thing. Restricting the
   *     assertion to singletons keeps it on page landmarks, where reordering is not a factor.
   *
   * OFFSETS ARE MEASURED AGAINST document.body, NOT THE VIEWPORT. The vertical scrollbar
   * changes side under rtl, which shifts every viewport-relative coordinate by its width and
   * reported a uniform ~16px asymmetry on every element of every page. Normalising against
   * the body box cancels it, because the scrollbar moves the body too.
   */
  const bodyRect = body.getBoundingClientRect();
  const seen = new Map();
  const rows = [];
  for ( const el of document.querySelectorAll( 'main *, header *, footer *' ) ) {
    const cs = getComputedStyle( el );
    if ( cs.display === 'none' || cs.visibility === 'hidden' ) continue;
    if ( cs.display.startsWith( 'inline' ) ) continue;
    // ...and anything INSIDE an inline-level box, because the whole subtree reflows with its
    // ancestor. The brand mark is a block-level <svg> inside an inline-flex badge: excluding
    // the badge but measuring its icon reported the icon as moving 553px when all that
    // happened was the badge finding a different place on a mirrored line.
    let inlineAncestor = false;
    for ( let a = el.parentElement; a && a !== body; a = a.parentElement ) {
      if ( getComputedStyle( a ).display.startsWith( 'inline' ) ) { inlineAncestor = true; break; }
    }
    if ( inlineAncestor ) continue;
    const locked = el.closest( '[dir]' );
    if ( locked && locked !== document.documentElement ) continue;
    const r = el.getBoundingClientRect();
    if ( r.width < 8 || r.height < 8 ) continue;
    // getAttribute, NOT el.className: on an SVG element className is an SVGAnimatedString, and
    // stringifying it yields the literal "[object SVGAnimatedString]" for every SVG on the
    // page. They then share one key, the singleton filter no longer separates them, and the
    // comparison comes out as hundreds of pixels of nonsense - which is how this first
    // reported 553px of asymmetry on an icon that had not moved.
    const cls = ( el.getAttribute( 'class' ) || '' ).split( /\s+/ ).filter( c => c && !/^jsx-/.test( c ) ).join( '.' );
    if ( !cls ) continue;
    const k = el.tagName.toLowerCase() + '.' + cls;
    seen.set( k, ( seen.get( k ) || 0 ) + 1 );
    rows.push( {
      k,
      start: Math.round( r.left - bodyRect.left ),
      end: Math.round( bodyRect.right - r.right ),
    } );
  }
  const symmetry = rows.filter( row => seen.get( row.k ) === 1 );

  return {
    dirAttr: de.getAttribute( 'dir' ) || '(unset)',
    computedDir: getComputedStyle( body ).direction,
    overflow,
    vw,
    header: rect( header ),
    widget: rect( widget ),
    shareChevronTransform: ( () => {
      // Measure a PAINTED chevron, not the first chevron in DOM order. PublicShare keeps its
      // menus mounted with [hidden]; Chromium/WebKit report transform:none for descendants of
      // that non-rendered subtree even when the matching RTL rule is correct.
      const chevron = [ ...document.querySelectorAll( '.public-share .ps-chevron' ) ]
        .find( el => el.getClientRects().length > 0 && getComputedStyle( el ).visibility !== 'hidden' );
      return chevron ? getComputedStyle( chevron ).transform : null;
    } )(),
    strays: strays.slice( 0, 6 ),
    symmetry,
  };
};

/**
 * KNOWN ASYMMETRIES, if any ever need naming. Currently EMPTY, and deliberately so.
 *
 * It briefly held div.contact-info and its two text children, 10px out on /grahak-os/. The
 * cause was measured rather than guessed: .phone-header is a flex row with gap:10px, and its
 * first child was an EMPTY span - no content, no size - which still claimed a gap that
 * Chromium resolves differently by direction. Measured child offsets were
 *   ltr: avatar @24 | contact-info @84      rtl: avatar @24 | contact-info @74
 * and 74 is the arithmetically correct one, so ltr was carrying a phantom 10px.
 *
 * The right response was to delete the dead element, not to excuse it here - an allowlist
 * entry would have preserved 10px of unintended space forever and taught the next reader that
 * a browser quirk was involved. Anything added to this set needs the same standard: a measured
 * cause, and a reason the cause cannot be removed.
 */
const KNOWN_ASYMMETRIC = new Set( [
  /* THE TERMINAL'S PAUSE CONTROL, and it meets the standard above: the cause is measured and
   * removing it would create the defect rather than fix one.
   *
   * MEASURED CAUSE. .wt-play is position:absolute;right:0 over the panel's title bar. `right` is
   * a physical property, so its distance from the inline-start edge cannot survive mirroring and
   * this assertion must fail by construction - it reported 726px at 1280, which is simply the
   * width it sits inside.
   *
   * WHY IT CANNOT BE MIRRORED. .wt-window carries dir="ltr" deliberately: it draws literal
   * machine output - a shell prompt, an API call, a single-table comment - and mirroring it
   * produced code that no longer parsed. That lock is the reason this gate passes on the panel
   * at all, and it means the title bar reserves its 108px of space on the PHYSICAL right in both
   * directions. The control is a sibling of that window rather than a child because the window is
   * aria-hidden, and a focusable element inside an aria-hidden subtree is keyboard-reachable
   * while absent from the accessibility tree. So it must sit outside the window and align with
   * space the window reserves physically. Mirroring it to the inline-start would move it off that
   * reserved space and onto the three window lights: satisfying this assertion is what would
   * break the layout.
   *
   * NOT TAKEN ON TRUST. tools/browser/rtlplayprobe.js measures the thing that actually matters -
   * whether the control overlaps the lights or the state text, and whether it stays within the
   * bar - in both directions. At 1280 it sits at 750..832 inside a bar of 25..831 under ltr and
   * at 1174..1256 inside 449..1255 under rtl, overlapping nothing either way. Re-run that probe
   * before changing this entry; if it ever reports an overlap, this exemption is wrong.
   */
  'button.wt-play',
  'span.wt-play-mark',
] );

/** Elements whose inline-start offset did not survive mirroring, worst first. */
function asymmetries ( ltr, rtl, tolerance ) {
  const byKey = new Map( rtl.symmetry.map( s => [ s.k, s ] ) );
  const out = [];
  for ( const a of ltr.symmetry ) {
    const b = byKey.get( a.k );
    if ( !b ) continue;
    if ( KNOWN_ASYMMETRIC.has( a.k ) ) continue;
    const d = Math.abs( a.start - b.end );
    if ( d > tolerance ) out.push( { k: a.k, d, ltrStart: a.start, rtlEnd: b.end } );
  }
  return out.sort( ( x, y ) => y.d - x.d );
}

( async () => {
  const routes = process.argv.filter( a => !a.startsWith( '--' ) ).slice( 2 ).length
    ? process.argv.filter( a => !a.startsWith( '--' ) ).slice( 2 )
    : discoverRoutes();
  const t = await target();
  const browser = await launchEngine();

  console.log( `rtlcheck - ${ENGINE} - ${t.mode} on ${t.base}` );
  console.log( `${routes.length} routes × ${VIEWPORTS.length} viewports\n` );

  let pass = 0, fail = 0;
  const failures = [];
  const ok = ( cond, label ) => {
    if ( cond ) { pass++; return true; }
    fail++; failures.push( label ); return false;
  };

  /**
   * WHAT THIS GATE DOES NOT MEASURE, reported up front so a pass cannot be misread.
   *
   * Every sweep below mirrors the document and leaves the CONTENT in English. That is the
   * right scope - direction is a property of boxes and of the bidi algorithm, and both are
   * exercised by setting lang and dir - but it means nothing here is evidence about how
   * Arabic TEXT lays out: line breaking, the width a translated string grows to, or whether
   * a JS-measured box clips it.
   *
   * It cannot be evidence, on this host. fontconfig reports ZERO families with Arabic or
   * Devanagari coverage against 82 with Latin, so Arabic and Hindi render as .notdef boxes and
   * every glyph measures the same width. A run that reported Arabic metrics from this
   * container would be reporting the width of tofu.
   *
   * Chromium's CDP is actively misleading here: CSS.getPlatformFontsForNode answers "Inter"
   * for an Arabic string, because it names the family that was ASKED for rather than the one
   * that supplied the glyphs. Checked with fc-list rather than believed.
   *
   * Closing it needs fonts in the image - Noto Sans Arabic and Noto Sans Devanagari - not more
   * assertions here.
   */
  const fontNote = ( () => {
    try {
      const { execSync } = require( 'child_process' );
      const count = lang => execSync( `fc-list :lang=${lang} 2>/dev/null | wc -l`, { encoding: 'utf8' } ).trim();
      return { ar: count( 'ar' ), hi: count( 'hi' ), en: count( 'en' ) };
    } catch { return null; }
  } )();
  if ( fontNote ) {
    console.log( `  note  script coverage on this host - latin:${fontNote.en} arabic:${fontNote.ar} devanagari:${fontNote.hi}` );
    if ( fontNote.ar === '0' ) {
      console.log( '  note  Arabic renders as .notdef here, so this run proves MIRRORING, not Arabic text metrics' );
    }
  }

  // --- 1. the served HTML must declare dir, before any script runs -------------------
  const declared = fs.readFileSync( path.join( OUT_DIR, 'index.html' ), 'utf8' );
  const hasDir = /<html[^>]*\sdir=("|')(ltr|rtl)\1/i.test( declared );
  ok( hasDir, 'the exported HTML declares dir on <html> (found: '
    + ( ( /<html[^>]*>/i.exec( declared ) || [ '' ] )[ 0 ].slice( 0, 90 ) ) + ')' );
  console.log( ( hasDir ? '  ok   ' : '  FAIL ' ) + 'exported <html> declares dir' );

  for ( const v of VIEWPORTS ) {
    const page = await browser.newPage( { viewport: { width: v.w, height: v.h } } );
    console.log( `\n--- ${v.n} ${v.w}×${v.h} ---` );

    for ( const r of routes ) {
      await gotoStable( page, t.base + r );

      // PublicShare's chevrons live inside menus that stay mounted with [hidden]. Open the
      // Contribute menu before measuring so the transform assertion observes a real painted box
      // in both directions, not a descendant of display:none. Routes without PublicShare simply
      // skip this probe as before.
      const contributeTrigger = await page.$( '.public-share .ps-contribute' );
      if ( contributeTrigger ) {
        await contributeTrigger.click();
        await page.waitForTimeout( 40 );
      }

      // The shipped LTR state, for comparison. Nothing below is meaningful without it: a
      // mirrored page that overflows tells you nothing if the unmirrored one does too.
      const ltr = await page.evaluate( PROBE );

      // Mirror the document exactly as SupportWidget does - lang AND dir - then let layout
      // settle. 'ar' is the reported language and is in Lightning CSS's RTL :lang() set.
      await page.evaluate( () => {
        document.documentElement.lang = 'ar';
        document.documentElement.dir = 'rtl';
      } );
      await page.waitForTimeout( 120 );
      const rtl = await page.evaluate( PROBE );
      const policyTranslatedFit = await page.evaluate( () => {
        const summary = document.querySelector( '.wc-policy summary' );
        if ( !summary ) return null;
        const original = summary.textContent;
        summary.textContent = 'تفاصيل سياسة الشحن والإرجاع والاسترداد والإلغاء';
        const box = summary.getBoundingClientRect();
        const parent = summary.parentElement?.getBoundingClientRect();
        const overflow = Math.max( 0, document.documentElement.scrollWidth - document.documentElement.clientWidth );
        summary.textContent = original;
        return {
          fits: !!parent && box.width <= parent.width + 1 && box.left >= -1
            && box.right <= document.documentElement.clientWidth + 1,
          width: Math.round( box.width ),
          parent: parent ? Math.round( parent.width ) : null,
          overflow,
        };
      } );

      const a = ok( rtl.computedDir === 'rtl', `${r} @${v.n}: dir=rtl changes computed direction (got ${rtl.computedDir})` );
      const b = ok( rtl.overflow === 0, `${r} @${v.n}: no horizontal overflow under rtl (got ${rtl.overflow}px, ltr was ${ltr.overflow}px)` );
      const c = ok( !rtl.strays.length, `${r} @${v.n}: nothing crosses the viewport edge under rtl (${rtl.strays.map( s => s.sel + ' l=' + s.l + ' r=' + s.r ).join( ' | ' )})` );
      const d = ok( !rtl.widget || ( rtl.widget.l >= -1 && rtl.widget.r <= rtl.vw + 1 ),
        `${r} @${v.n}: the language widget is fully on screen under rtl (l=${rtl.widget && rtl.widget.l} r=${rtl.widget && rtl.widget.r} vw=${rtl.vw})` );
      const d2 = rtl.shareChevronTransform === null
        ? ( pass++, true )
        : ok( rtl.shareChevronTransform === 'matrix(-1, 0, 0, 1, 0, 0)',
          `${r} @${v.n}: shared action chevron mirrors under rtl (transform ${rtl.shareChevronTransform})` );
      const d3 = policyTranslatedFit === null
        ? ( pass++, true )
        : ok( policyTranslatedFit.fits && policyTranslatedFit.overflow === 0,
          `${r} @${v.n}: long translated Policy trigger stays contained under rtl (${policyTranslatedFit.width}px in ${policyTranslatedFit.parent}px parent, overflow ${policyTranslatedFit.overflow}px)` );
      // THE MIRROR MUST ACTUALLY HAPPEN. Without this the gate passes on a page that ignored
      // the direction entirely, which is the state it was written to detect. The widget is
      // the cleanest witness: fixed to the viewport, so its inset has nowhere to hide.
      const e = !ltr.widget || !rtl.widget
        ? ( pass++, true )
        : ok( Math.abs( rtl.widget.l - ltr.widget.l ) > 1,
          `${r} @${v.n}: the widget moved when the page mirrored (ltr l=${ltr.widget.l}, rtl l=${rtl.widget.l}) - logical insets compile to :lang() rules, so this fails if lang was not set` );

      // 6px absorbs sub-pixel rounding and scrollbar reservation without hiding a real
      // physical property - the ones this found measured 36px to 726px, not 7px.
      const asym = asymmetries( ltr, rtl, 6 );
      const f = ok( !asym.length,
        `${r} @${v.n}: every block element keeps its inline-start offset when mirrored (${asym.slice( 0, 3 ).map( x => `${x.k} off by ${x.d}px` ).join( ' | ' )})` );

      const line = ( a && b && c && d && d2 && d3 && e && f ) ? 'ok  ' : 'FAIL';
      console.log( `  ${line} ${r.padEnd( 18 )} dir:${rtl.computedDir} ovf:${String( rtl.overflow ).padStart( 3 )}`
        + ` widget ltr:${ltr.widget ? ltr.widget.l : 'n/a'}->rtl:${rtl.widget ? rtl.widget.l : 'n/a'}`
        + ` asym:${String( asym.length ).padStart( 2 )}`
        + ( rtl.strays.length ? '  strays: ' + rtl.strays.map( s => s.sel ).join( ',' ) : '' )
        + ( asym.length ? '  worst: ' + asym[ 0 ].k + ' ' + asym[ 0 ].d + 'px' : '' ) );
    }
    await page.close();
  }

  /**
   * PRINT AND ZOOM, on a representative subset rather than all 125 routes - these are media
   * states, not per-route layouts, so a public page, an inner page and a dashboard shell cover
   * the three shapes of chrome the site has.
   *
   * ZOOM IS APPROXIMATED, and the approximation is stated because it is not exact. Chromium's
   * real zoom is a browser-level control Playwright does not expose. Halving the viewport at a
   * doubled deviceScaleFactor reproduces what matters here - the CSS pixel count a 200% zoom
   * leaves for layout - which is also how WCAG 1.4.10 reflow is normally tested. It does NOT
   * reproduce zoom's effect on fixed-position elements relative to the visual viewport.
   */
  {
    console.log( '\n--- print and zoom (mirrored) ---' );
    const subset = [ '/', '/grahak-os/', '/vayulok/', '/admin/' ].filter( r => routes.includes( r ) );

    for ( const r of subset ) {
      // PRINT. A print stylesheet that hides the widget must still not leave the page
      // overflowing, and print is the one medium where a mirrored document is rendered by a
      // different code path in every engine.
      const pp = await browser.newPage( { viewport: { width: 1280, height: 900 } } );
      await gotoStable( pp, t.base + r );
      await pp.evaluate( () => { document.documentElement.lang = 'ar'; document.documentElement.dir = 'rtl'; } );
      await pp.emulateMedia( { media: 'print' } );
      await pp.waitForTimeout( 120 );
      const printed = await pp.evaluate( PROBE );
      const pOk = ok( printed.overflow === 0, `${r} @print rtl: no horizontal overflow (got ${printed.overflow}px)` );
      console.log( `  ${pOk ? 'ok  ' : 'FAIL'} ${r.padEnd( 14 )} print  ovf:${printed.overflow}` );
      await pp.close();

      // ZOOM 200%, as halved CSS pixels at double scale.
      const zp = await browser.newPage( { viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 } );
      await gotoStable( zp, t.base + r );
      await zp.evaluate( () => { document.documentElement.lang = 'ar'; document.documentElement.dir = 'rtl'; } );
      await zp.waitForTimeout( 120 );
      const zoomed = await zp.evaluate( PROBE );
      const zOk = ok( zoomed.overflow === 0, `${r} @zoom200 rtl: no horizontal overflow (got ${zoomed.overflow}px)` );
      const zStray = ok( !zoomed.strays.length, `${r} @zoom200 rtl: nothing crosses the viewport edge (${zoomed.strays.map( s => s.sel ).join( ',' )})` );
      console.log( `  ${zOk && zStray ? 'ok  ' : 'FAIL'} ${r.padEnd( 14 )} zoom200  ovf:${zoomed.overflow}` );
      await zp.close();
    }
  }

  await browser.close();
  await t.close();

  console.log( `\n${pass}/${pass + fail} assertions passed` );
  if ( failures.length ) {
    console.log( '\nfailures:' );
    for ( const f of failures ) console.log( '  - ' + f );
  }
  process.exit( fail ? 1 : 0 );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
