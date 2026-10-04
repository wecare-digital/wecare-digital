'use strict';

/**
 * devicecheck - every public route against the full device matrix, including the foldable
 * postures that width-only testing cannot reach.
 *
 * WHY THIS EXISTS SEPARATELY FROM pageaudit.js. pageaudit sweeps all 124 routes at three
 * widths, which is the right trade for a census. It cannot see the failure mode that only
 * appears when a viewport is WIDE AND SHORT - rare on a phone or a laptop, and the normal
 * shape of a folded-landscape device. That case produced a menu with a computed max-height of
 * ZERO at 653x280 and 40px at 880x360, on a page where every other check was green.
 *
 * WHAT IT ASSERTS, per route per posture:
 *   - no horizontal overflow
 *   - the top section's h1 is present and inside the viewport
 *   - with the menu open: it is at least 120px tall and does not run off the bottom
 *   - every tap target in the header is at least 44px
 *
 * Run:  node tools/browser/devicecheck.js
 *       node tools/browser/devicecheck.js /contact/ /terms/
 */

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );
const { installVisible } = require( './lib/visible' );

/**
 * ENGINE SELECTION. Chromium is the default; `--firefox` and `--webkit` run the same matrix on
 * Gecko and WebKit.
 *
 * WEBKIT DOES NOT RUN IN THIS SANDBOX, and the reason is worth recording because it is not
 * something more installing fixes. The host is Amazon Linux 2023, which ships ICU 67; the
 * Playwright WebKit build links libicudata.so.74 / libicui18n.so.74 / libicuuc.so.74, and also
 * wants GTK4, a full GStreamer stack, libgraphene, libxslt, libopus and flite. `playwright
 * install-deps` only knows apt-get, and AL2023 has no flite package at all. WebKit needs an
 * Ubuntu-based image - mcr.microsoft.com/playwright - not a longer dnf line.
 *
 * That gap matters more than the other two: WebKit is Safari's engine AND the engine behind
 * every browser and WebView on iOS. Until it runs, iOS is unverified. Named here so it is a
 * task with a known answer rather than a vague caveat.
 */
const ENGINE = process.argv.includes( '--firefox' ) ? 'firefox'
  : process.argv.includes( '--webkit' ) ? 'webkit' : 'chromium';
const launchEngine = async () => {
  if ( ENGINE === 'chromium' ) return launch();
  return require( 'playwright-core' )[ ENGINE ].launch();
};

// A POST PAGE IS IN THIS LIST NOW, AND ITS ABSENCE COST A REAL DEFECT. The list held every
// hand-written public route and no /post/<slug>/, on the reasonable-sounding grounds that one
// template serves all of them. But a template with 939 instances is where the LONGEST content
// lives, and length is exactly what breaks at 280px: the breadcrumb's current-page crumb was
// capped by a character count rather than by the space left for it, and ran 38px past the
// viewport on the folded Fold posture. rtlcheck caught it only incidentally, while checking
// something else. One representative slug is enough - the template is shared - and it must be a
// LONG-titled one, because a short title fits and would prove nothing.
const ROUTES = [ '/', '/grahak-os/', '/vayulok/', '/bharat-rx/', '/contact/', '/orders/',
  '/terms/', '/privacy/', '/anew/', '/clear-closure/', '/dastavez/', '/elsewhere/',
  '/expo-week/', '/niji-setu/', '/ritual-guru/', '/hunar/', '/vault/', '/404/', '/blog/', '/get/',
  // The catalogue. '/shop/' WAS HERE for the grid's three-to-two-to-one reflow and was removed on
  // 2026-10-04: the owner withdrew the index, so it 301s to the home page, and a harness that
  // loads a redirect either follows it and audits home a second time or reports a failure -
  // neither is information. There is no grid left to reflow.
  //
  // /shop/kiosk/ STAYS, and now carries the coverage alone. It is a catalogue slug rendered by
  // src/pages/shop/[slug].tsx - the component this change edits - and it is the one catalogue
  // route whose band is not RotatingHero's: it uses components/PageTopBand, so that component's
  // 108px/96px clearance and its h1 clamp are proved here across every device posture.
  '/shop/kiosk/',
  // THE TRANSACTIONAL ROUTES, AND THEIR ABSENCE WAS THE DEFECT. All four are public (registered in
  // the isPublic chain in _app.tsx) and all four were invisible to this harness, which carries a
  // hardcoded list. Two of them - /checkout/status/ and /checkout/success/ - shipped with NO header
  // clearance at all: they centred a card inside min-height:100vh, so the heading painted under the
  // 108px fixed header, and nothing here could see it. They share components/PageTopBand now, and
  // this is where that is measured.
  // The Shopping Bag is in the header on EVERY one of these routes, so the 44px tap-target
  // assertion below now covers it at 280px, where the header has the least room.
  '/cart/', '/account/sign-in/', '/checkout/status/', '/checkout/success/',
  '/post/a-bad-event-and-a-catastrophic-forecast-are-not-the-same/' ];

// CSS pixels. DevTools presets where one exists, marked approx where modelled.
const DEVICES = [
  { n: 'Fold folded',        w: 280,  h: 653 },
  { n: 'Fold folded land',   w: 653,  h: 280 },   // wide AND short
  { n: 'ZFold cover',        w: 344,  h: 882 },
  { n: 'ZFold cover land',   w: 882,  h: 344 },   // wide AND short
  { n: 'ZFold unfolded',     w: 904,  h: 1084 },
  { n: 'ZFlip',              w: 360,  h: 880 },
  { n: 'ZFlip land',         w: 880,  h: 360 },   // wide AND short
  { n: 'Pixel Fold inner',   w: 841,  h: 1010 },
  { n: 'Surface Duo',        w: 540,  h: 720 },
  { n: 'Surface Duo land',   w: 720,  h: 540 },
  { n: 'Zenbook Fold',       w: 853,  h: 1280 },
  { n: 'phone 320',          w: 320,  h: 844 },
  { n: 'phone 390',          w: 390,  h: 844 },
  { n: 'desktop 1280',       w: 1280, h: 900 },
  { n: 'desktop 1920',       w: 1920, h: 1080 },
];

const PROBE = () => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const h1 = document.querySelector( 'h1' );
  const menu = document.querySelector( '.nav-menu' );
  const r = el => el.getBoundingClientRect();
  const targets = Array.from( document.querySelectorAll( 'header a[href], header button' ) )
    .map( el => ( { el, b: r( el ) } ) )
    // Shared predicate - lib/visible.js. This checked visibility and opacity but not
    // display, nor an ancestor at opacity:0, nor offsetParent - so a header control inside
    // a closed menu counted as a touch target and was measured for its 44px floor.
    .filter( x => window.__visible( x.el ) );
  const small = targets.filter( x => x.b.height < 44 ).map( x => {
    const cls = ( x.el.className || '' ).toString().split( /\s+/ ).filter( c => c && !c.startsWith( 'jsx-' ) )[ 0 ] || x.el.tagName;
    return `${cls}:${Math.round( x.b.height )}px`;
  } );
  return {
    overflow: document.documentElement.scrollWidth - vw,
    h1: h1 ? { w: Math.round( r( h1 ).width ), right: Math.round( r( h1 ).right ), top: Math.round( r( h1 ).top ) } : null,
    h1Fits: h1 ? r( h1 ).right <= vw + 1 : null,
    menu: menu ? {
      h: Math.round( r( menu ).height ),
      offBottom: Math.max( 0, Math.round( r( menu ).bottom - vh ) ),
      content: menu.scrollHeight,
    } : null,
    smallTargets: small,
  };
};

( async () => {
  const args = process.argv.slice( 2 ).filter( a => a.startsWith( '/' ) );
  const routes = args.length ? args : ROUTES;
  const t = await target();
  const browser = await launchEngine();
  let fail = 0, checks = 0;
  const failures = [];

  try {
    console.log( `devicecheck [${ENGINE}] - ${routes.length} routes × ${DEVICES.length} postures = ${routes.length * DEVICES.length} combinations\n` );
    for ( const d of DEVICES ) {
      const ctx = await browser.newContext( { viewport: { width: d.w, height: d.h } } );
      const page = await ctx.newPage();
      await installVisible( page );
      const bad = [];
      for ( const route of routes ) {
        try {
          await gotoStable( page, `${t.base}${route}`, { settle: 120 } );
          // open the menu where there is one - the wide-and-short failure needs it open
          await page.click( '.nav-trigger', { timeout: 1200 } ).catch( () => {} );
          await page.waitForTimeout( 160 );
          const x = await page.evaluate( PROBE );
          checks++;
          const problems = [];
          if ( x.overflow > 0 ) problems.push( `overflow ${x.overflow}px` );
          if ( x.h1Fits === false ) problems.push( `h1 ${x.h1.right}>${d.w}` );
          if ( x.menu && x.menu.h > 0 && x.menu.h < 120 ) problems.push( `menu ${x.menu.h}px for ${x.menu.content}px` );
          if ( x.menu && x.menu.offBottom > 0 ) problems.push( `menu +${x.menu.offBottom}px off-bottom` );
          if ( x.smallTargets.length ) problems.push( `tap<44: ${x.smallTargets.join( ',' )}` );
          if ( problems.length ) { bad.push( `${route} — ${problems.join( ' · ' )}` ); fail++; }
        } catch ( e ) {
          bad.push( `${route} — ERROR ${e.message.slice( 0, 50 )}` ); fail++;
        }
      }
      const label = `${d.n} ${d.w}×${d.h}`.padEnd( 28 );
      if ( bad.length ) {
        console.log( `  FAIL ${label} ${bad.length}/${routes.length}` );
        bad.forEach( b => console.log( `         ${b}` ) );
        failures.push( ...bad.map( b => `${d.n} ${d.w}×${d.h}: ${b}` ) );
      } else {
        console.log( `  ok   ${label} ${routes.length}/${routes.length}` );
      }
      await ctx.close();
    }
    console.log( `\n${checks - fail}/${checks} route×posture combinations clean` );
    if ( failures.length ) { console.log( '\nfailures:' ); failures.forEach( f => console.log( '  ' + f ) ); }
    process.exitCode = fail ? 1 : 0;
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
