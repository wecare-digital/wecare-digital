'use strict';

/**
 * animcheck - the rotating-headline gate.
 *
 * WHY IT LIVES IN THE REPO. Four places in src/ and docs/ cited this file while it
 * existed nowhere on disk, because every harness lived in /projects/pwtest, outside
 * the repo, and a sandbox reset deletes that whole directory. The comments citing it
 * survived in git; the file it named did not. Keeping the harness under version
 * control with the code that cites it is the only arrangement where "re-run
 * animcheck.js" stays a true instruction. Playwright itself stays out of the app's
 * package.json - see tools/browser/README.md.
 *
 * WHAT IT ASSERTS
 *
 * 1. NO REFLOW. The pill animates to each word's MEASURED width. If the h1 grows to a
 *    second line on the longest word only, every section below it shifts every 2400ms.
 *    This measures the h1's height for EVERY word at 21 viewports from 320 to 1920 and
 *    fails if it is not constant within a surface. This is the real gate; the character
 *    -band check in HomePage.test.tsx is only a proxy and a unit test cannot see reflow.
 *
 * 2. ONE ANIMATION FAMILY. There are FOUR implementations of this hero, not three:
 *    three inline copies (home-, hero- on /grahak-os/, vl- on /vayulok/) plus the
 *    shared RotatingHero component (rh-, used by /contact/, /terms/, /privacy/,
 *    /bharat-rx/, /orders/). They are meant to animate identically, so this compares
 *    the COMPUTED transition of the pill, the word, the tint and the dot across all of
 *    them and fails on drift. Four copies of a constant cannot be kept in step by
 *    intention alone.
 *
 * 3. TAIL TRAVEL. Reports each word's rendered width and the shortest-to-longest
 *    spread, which is how far the headline's tail moves each tick. Not a failure -
 *    it is a movement-feel judgement - but it must be MEASURED rather than guessed,
 *    and stale numbers in comments are how this drifts.
 *
 * 4. NO CONSOLE ERRORS, with exactly two dev-only exemptions (see DEV_ALLOWED). The
 *    allowlist is kept deliberately narrow: a broad /error/i filter here would mask
 *    the very thing this exists to catch.
 *
 * HOW THE MEASUREMENT WORKS, and why it does not wait 2400ms per word.
 *
 * Waiting out the live rotation at 21 viewports would take roughly 21 x 5 x 2.4s per
 * surface. Instead this drives the mechanism directly: the only thing the rotation
 * does to layout is set an inline px width on the .*-cycle element, so the harness
 * sets that same width to each word's own offsetWidth and reads the h1's height. That
 * reproduces the exact layout state of every tick, deterministically.
 *
 * Transitions are suppressed on the element while doing so. Without that, the width
 * glides over 520ms and every reading lands mid-transition - the h1 height would be
 * measured against a pill that is still moving, which is how a harness reports a
 * confident wrong number.
 *
 * One surface is ALSO sampled through a real, unmodified rotation as a cross-check,
 * so the fast path cannot quietly diverge from what a visitor sees.
 *
 *   node tools/browser/animcheck.js
 *   BASE=http://localhost:3000 node tools/browser/animcheck.js
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );

/**
 * The four rotating surfaces. `prefix` is the class stem; they differ because three
 * pages carry inline copies whose own tests pin their class names.
 */
const SURFACES = [
  { route: '/', prefix: 'home', label: 'Home' },
  { route: '/grahak-os/', prefix: 'hero', label: 'Grahak OS' },
  { route: '/vayulok/', prefix: 'vl', label: 'VayuLok' },
  { route: '/contact/', prefix: 'rh', label: 'Contact (RotatingHero)' },
];

/**
 * 21 viewports, 320 to 1920. Includes the four named breakpoints the design notes
 * call out (390 / 768 / 1024 / 1440) plus the clamp() inflection points either side
 * of them, because a font-size clamp changes where a line breaks and the interesting
 * widths are the ones next to a breakpoint rather than the round numbers.
 */
const VIEWPORTS = [
  320, 360, 390, 414, 480, 540, 600, 668, 720, 768, 834,
  900, 960, 1024, 1120, 1200, 1280, 1366, 1440, 1680, 1920,
];

/** The viewport whose live rotation is sampled as a cross-check on the fast path. */
const LIVE_SAMPLE_VIEWPORT = 1280;

/**
 * THE CONSOLE ALLOWLIST. Every entry is an artifact of how the harness runs, never a
 * page defect, and each is matched as narrowly as it can be. A broad /error/i filter
 * here would mask exactly what this check exists to catch - which already happened
 * once: the X-Frame-Options meta error sat in this channel on every page load until it
 * was deleted from _document.tsx, and a loose filter would have hidden it for good.
 *
 * Two are dev-server infrastructure. Chromium refuses the MIME type Next serves
 * _clientMiddlewareManifest.js with, and the HMR websocket cannot complete a handshake
 * through this sandbox's networking. Neither can occur against the static export.
 *
 * One is a LOCAL-ORIGIN artifact and applies to both modes: LanguageBar fetches
 * api.wecare.digital, which sends no Access-Control-Allow-Origin for 127.0.0.1 or
 * localhost, so the request is refused by CORS. On the deployed site the page origin IS
 * wecare.digital and the call succeeds. It is scoped to that one host, and the generic
 * "Failed to load resource" line it also produces is matched by the REQUEST URL rather
 * than by its text - otherwise the exemption would swallow every failed request on the
 * page, which is far too much to give away for one known-good call.
 *
 * One is THIRD-PARTY AND CROSS-ORIGIN, and it is the reason this list grew on
 * 2026-09-25. /contact/ failed the gate on `stack` with:
 *
 *   Access to XMLHttpRequest at 'https://maps.googleapis.com/$rpc/google.internal.
 *   maps.mapsjs.v1.MapsJsInternalService/GetViewportInfo' from origin
 *   'https://www.google.com' has been blocked by CORS policy
 *
 * Read the origin: `https://www.google.com`, not our page. NEXT_PUBLIC_GOOGLE_MAPS_KEY
 * is unset in CI, so ContactLocation ships the KEYLESS path - a google.com/maps/embed
 * iframe - and this is Google's own bundle calling its own private RPC from inside that
 * iframe and being refused by Google's own CORS policy. No markup, style or script of
 * ours participates, and nothing we can change makes it stop; it also appears only
 * sometimes, which is why the same assertion passed on PR #46. Chromium surfaces
 * subframe console messages on the parent page, so it lands in this channel.
 *
 * Scoped to that one internal RPC path, NOT to maps.googleapis.com generally: a real
 * failure of the keyed Maps JS API (maps/api/js, which our own code loads) must still
 * fail this gate. The companion net::ERR_FAILED line carries no identifying text, so it
 * is matched on the REQUEST URL for the same reason as the site-language entry above.
 */
const ALLOWED = [
  { why: 'dev: Next serves this with a MIME type Chromium refuses', test: ( text ) => /_clientMiddlewareManifest\.js/.test( text ) },
  { why: 'dev: HMR websocket cannot handshake through this sandbox', test: ( text ) => /_next\/hmr/.test( text ) },
  {
    // MATCHED ON THE PATH, NOT THE HOST, for the reason uicheck.js's stub now is: this read
    // /api\.wecare\.digital\/site-language/ and stopped matching when the frontend moved to
    // wecare.digital/api, so a CORS failure that is expected on a 127.0.0.1 origin started
    // failing this gate on four routes. The host is not the contract; the path is.
    why: 'local origin: the site-language API sends no CORS header for 127.0.0.1',
    test: ( text, url ) =>
      /\/site-language/.test( text )
      || ( /Failed to load resource/.test( text ) && /\/site-language/.test( url || '' ) ),
  },
  {
    why: "third party: Google's keyless maps/embed iframe calls its own private "
      + 'MapsJsInternalService RPC and Google refuses it by CORS - origin is google.com, not ours',
    test: ( text, url ) =>
      /MapsJsInternalService/.test( text )
      || ( /Failed to load resource/.test( text ) && /MapsJsInternalService/.test( url || '' ) ),
  },
  {
    // KEYLESS-CI ARTIFACT, scoped exactly like the two entries above. /vayulok/'s
    // VayuLokLive reads NEXT_PUBLIC_GOOGLE_MAPS_KEY, which CI leaves unset (build-test.yml
    // documents the key as owner-only, which is why contactcheck's keyed assertion is
    // reported-not-enforced). With an empty key its Air Quality and Weather calls to
    // *.googleapis.com are rejected 403, producing the generic "Failed to load resource"
    // line with no identifying text - so, like the site-language and Maps RPC entries, it
    // is matched on the REQUEST URL, not the message. Scoped to these two Google service
    // hosts only: on the deployed site the key is present and these calls succeed, so a
    // real failure there still fails this gate, and any OTHER host's 403 is untouched.
    why: 'keyless CI: /vayulok/ Air Quality + Weather calls 403 without a Maps key - '
      + 'the key is owner-only and unset in CI, exactly as contactcheck documents',
    test: ( text, url ) =>
      /Failed to load resource/.test( text )
      && /\b(airquality|weather)\.googleapis\.com\//.test( url || '' ),
  },
];

function isAllowed( text, url ) {
  return ALLOWED.some( a => a.test( text, url ) );
}

const results = [];
let failures = 0;

function record( ok, name, detail ) {
  results.push( { ok, name, detail } );
  if ( !ok ) failures++;
  const mark = ok ? 'ok  ' : 'FAIL';
  console.log( `  ${mark} ${name}${detail ? ` - ${detail}` : ''}` );
}

/**
 * Read the computed transitions that define the animation family, plus each word's
 * rendered width, plus the h1 height for every word width.
 */
async function measureSurface( page, prefix ) {
  return page.evaluate( p => {
    const q = s => document.querySelector( s );
    const head = q( `.${p}-head` ) || q( 'h1' );
    const cycle = q( `.${p}-cycle` );
    const words = Array.from( document.querySelectorAll( `.${p}-cyc-word` ) );
    const mark = q( `.${p}-mark` );
    const dot = q( `.${p}-mark-dot` );

    if ( !head || !cycle || !words.length ) {
      return { error: `missing nodes for prefix "${p}" (head=${!!head} cycle=${!!cycle} words=${words.length})` };
    }

    const cs = el => ( el ? getComputedStyle( el ) : null );

    // Each word's own rendered width. offsetWidth is an integer; the pill's inline
    // width is set from exactly this value, so integers are the right resolution.
    const widths = words.map( w => ( { word: w.textContent || '', width: w.offsetWidth } ) );

    // Suppress the glide so nothing is read mid-transition, then restore.
    const priorTransition = cycle.style.transition;
    const priorWidth = cycle.style.width;
    cycle.style.transition = 'none';

    const heights = widths.map( ( { word, width } ) => {
      cycle.style.width = `${width}px`;
      // Reading offsetHeight forces synchronous layout, so this is the settled height
      // for this width rather than a stale one.
      return { word, width, h1: head.offsetHeight };
    } );

    cycle.style.width = priorWidth;
    cycle.style.transition = priorTransition;

    const markCs = cs( mark );
    const dotCs = cs( dot );
    const cycleCs = cs( cycle );
    const wordCs = cs( words[ 0 ] );

    return {
      widths,
      heights,
      // The h1's own line-height and font-size, useful when a height does vary and
      // you need to know whether it varied by a whole line.
      headFont: `${cs( head ).fontSize}/${cs( head ).lineHeight}`,
      transitions: {
        cycle: cycleCs.transition,
        word: wordCs.transition,
        mark: markCs ? markCs.transition : '(no mark)',
        dot: dotCs ? dotCs.transition : '(no dot)',
      },
    };
  }, prefix );
}

/** Sample the h1 height through a real rotation, untouched, for N ticks. */
async function sampleLiveRotation( page, prefix, ticks ) {
  const samples = [];
  for ( let i = 0; i < ticks; i++ ) {
    const s = await page.evaluate( p => {
      const head = document.querySelector( `.${p}-head` ) || document.querySelector( 'h1' );
      const on = document.querySelector( `.${p}-cyc-word.on` );
      return { h1: head.offsetHeight, word: on ? on.textContent : null };
    }, prefix );
    samples.push( s );
    // Slightly longer than the 2400ms interval so each sample lands on a settled
    // pill rather than during the 520ms width glide.
    await page.waitForTimeout( 2600 );
  }
  return samples;
}

async function main() {
  const t = await target();
  const browser = await launch();
  console.log( `animcheck - ${t.mode === 'BASE' ? `BASE ${t.base}` : `static export (out/) on ${t.base}`}\n` );

  const familyTransitions = [];

  try {
    for ( const surface of SURFACES ) {
      console.log( `${surface.label}  ${surface.route}` );
      const context = await browser.newContext( { viewport: { width: 1280, height: 900 } } );
      const page = await context.newPage();

      const consoleErrors = [];
      page.on( 'console', msg => {
        if ( msg.type() !== 'error' ) return;
        const text = msg.text();
        // location().url is the request that failed, which is the only way to scope
        // the generic "Failed to load resource" line to a known-good endpoint.
        const url = ( msg.location() || {} ).url || '';
        if ( isAllowed( text, url ) ) return;
        consoleErrors.push( text );
      } );
      page.on( 'pageerror', err => consoleErrors.push( `pageerror: ${err.message}` ) );

      const url = t.base + surface.route;
      const res = await gotoStable( page, url );
      record( res.status() === 200, `${surface.route} responds 200`, `got ${res.status()}` );

      // The pill is client-rendered on some surfaces, so wait for it rather than
      // assuming it is in the served HTML.
      try {
        await page.waitForSelector( `.${surface.prefix}-cyc-word`, { timeout: 15000 } );
      } catch {
        record( false, `${surface.route} renders a rotating pill`, `no .${surface.prefix}-cyc-word appeared` );
        await context.close();
        continue;
      }

      let allConstant = true;
      const perViewport = [];

      for ( const width of VIEWPORTS ) {
        await page.setViewportSize( { width, height: 900 } );
        const m = await measureSurface( page, surface.prefix );
        if ( m.error ) { record( false, `${surface.route} @${width}`, m.error ); allConstant = false; continue; }

        const uniq = [ ...new Set( m.heights.map( h => h.h1 ) ) ];
        if ( uniq.length !== 1 ) {
          allConstant = false;
          const detail = m.heights.map( h => `"${h.word}"@${h.width}px->${h.h1}px` ).join( ' ' );
          record( false, `${surface.route} h1 height constant @${width}px`,
            `${uniq.length} distinct heights (${uniq.join( ', ' )}) : ${detail}` );
        }
        perViewport.push( { width, h1: m.heights[ 0 ].h1 } );

        if ( width === 1280 ) {
          const sorted = [ ...m.widths ].sort( ( a, b ) => a.width - b.width );
          const spread = sorted[ sorted.length - 1 ].width - sorted[ 0 ].width;
          console.log( `       widths @1280: ${sorted.map( s => `${s.word} ${s.width}` ).join( ', ' )}` );
          console.log( `       tail travel (spread shortest->longest): ${spread}px` );
          familyTransitions.push( { label: surface.label, ...m.transitions } );
        }
      }

      if ( allConstant ) {
        const hs = [ ...new Set( perViewport.map( p => p.h1 ) ) ].sort( ( a, b ) => a - b );
        record( true, `${surface.route} h1 height constant across every word at all ${VIEWPORTS.length} viewports`,
          `per-viewport h1 heights: ${hs.join( '/' )}px` );
      }

      if ( surface.route === '/' ) {
        await page.setViewportSize( { width: LIVE_SAMPLE_VIEWPORT, height: 900 } );
        // 'load', not 'networkidle'. The waitForSelector on the next line is the real
        // readiness signal - it waits for the pill to exist and be active - so networkidle
        // added nothing here except one more place for a CI run to time out. See the note
        // on gotoStable in lib/browser.js.
        await page.reload( { waitUntil: 'load', timeout: 60000 } );
        await page.waitForSelector( `.${surface.prefix}-cyc-word.on`, { timeout: 15000 } );
        const live = await sampleLiveRotation( page, surface.prefix, 6 );
        const liveH = [ ...new Set( live.map( s => s.h1 ) ) ];
        record( liveH.length === 1,
          `/ h1 height constant through a live rotation @${LIVE_SAMPLE_VIEWPORT}px`,
          `${live.length} samples, words [${live.map( s => s.word ).join( ' > ' )}], heights ${liveH.join( '/' )}px` );
        // A rotation that never advanced would also report one constant height, so
        // confirm the words actually changed - otherwise this check passes vacuously.
        const distinctWords = [ ...new Set( live.map( s => s.word ) ) ];
        record( distinctWords.length > 1, '/ rotation actually advances while sampled',
          `${distinctWords.length} distinct words seen` );
      }

      record( consoleErrors.length === 0, `${surface.route} no unexpected console errors`,
        consoleErrors.length ? consoleErrors.slice( 0, 4 ).join( ' | ' ) : 'none' );

      await context.close();
      console.log( '' );
    }

    // One family, four implementations.
    console.log( 'Animation family (computed transitions @1280)' );
    for ( const key of [ 'cycle', 'word', 'mark', 'dot' ] ) {
      const values = familyTransitions.map( f => `${f.label}: ${f[ key ]}` );
      const distinct = [ ...new Set( familyTransitions.map( f => f[ key ] ) ) ];
      record( distinct.length === 1, `.*-${key} transition identical across all ${familyTransitions.length} surfaces`,
        distinct.length === 1 ? distinct[ 0 ] : values.join( ' || ' ) );
    }
  } finally {
    await browser.close();
    await t.close();
  }

  console.log( `\n${results.length - failures}/${results.length} assertions passed` );
  if ( failures ) { console.log( `${failures} FAILED` ); process.exit( 1 ); }
}

main().catch( err => { console.error( err ); process.exit( 1 ); } );
