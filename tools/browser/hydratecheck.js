'use strict';

/**
 * hydratecheck - does the page React hydrated match the page the build exported?
 *
 * WHY THIS EXISTS, AND WHY NOTHING ELSE HERE COULD HAVE FOUND IT
 * -------------------------------------------------------------
 * On 2026-10-05 https://wecare.digital/workspace/engage/ rendered BLANK, and so did every
 * other /workspace/* route. Nothing reported it: HTTP 200, 159 KB of HTML, the page's own
 * copy present in that HTML, no console error, no uncaught exception, no failed request.
 * Eight browser suites in this directory passed throughout, because every one of them
 * measures ONE settled state and asserts things about the elements it finds. None of them
 * asks whether the elements it found are the only ones there.
 *
 * The defect was a hydration failure at a `next/dynamic` boundary. `_app.tsx` loaded the
 * authenticated shell lazily with SSR left on; a Turbopack pages-router build writes no
 * react-loadable manifest, so `__NEXT_DATA__` carries no `dynamicIds`, so Next had nothing
 * to await in `__NEXT_PRELOADREADY` and called `hydrateRoot` while the chunk was still in
 * flight. The client's first render produced null where the exported HTML held the whole
 * Amplify subtree. React recovered by client-rendering the boundary and LEFT THE BUILD-TIME
 * NODES IN PLACE, so `#__next` ended up holding two copies of the app: the dead one first,
 * carrying an empty sign-in area, and the live one appended below it at y=900 - just past
 * the bottom of the viewport. The visible page was a header, 592px of white, and a footer.
 *
 * So the measurable symptom is DUPLICATION, not absence, and that is what this asserts:
 *
 *   1. #__next has exactly one element subtree per top-level landmark - no route may ship
 *      two <header>, two <footer>, or two [data-amplify-theme] wrappers.
 *   2. No two top-level children of #__next share a SIGNATURE - tag name plus the set of
 *      attribute names. React appending a second copy of the app makes the signature repeat
 *      exactly, because it is the same component rendering the same element. On the broken
 *      export the children were DIV[data-amplify-theme,dir], STYLE[id], DIV[data-amplify-
 *      theme,dir], STYLE[id]; on a healthy public page they are HEADER, MAIN, FOOTER and a
 *      widget DIV, all distinct.
 *
 *      This started out as "no top-level child begins below the fold", which is what the
 *      failure LOOKS like - the second copy landed at y=900 - and it is the wrong rule: a
 *      <footer> is a top-level child of #__next and sits below the fold on every long public
 *      page, so / and /grahak-os/ and /contact/ all failed it while rendering perfectly. The
 *      signature is the cause; the fold position is a consequence, so it is reported with a
 *      duplicate rather than asserted on its own.
 *   3. Something is actually painted at the centre of the first viewport. A blank first
 *      screen is the user-visible failure, and elementFromPoint is the cheapest check for it
 *      from the outside.
 *
 *      ON ITS OWN IT IS NOT ENOUGH, AND THAT IS WORTH KNOWING RATHER THAN ASSUMING. Run
 *      against the broken deployment it PASSES, reporting DIV.ag-centre: the dead copy's
 *      centring box is 1280x592 and sits exactly where the sign-in card should be, so
 *      something is painted at that point - it is just empty. Only assertion 2 distinguishes
 *      that from a working page, which is why the duplication check is the load-bearing one
 *      and this is the corroborating one.
 *
 * VERIFIED AGAINST THE DEFECT, NOT ONLY AGAINST THE FIX. A gate that has never seen the bug
 * is a gate that proves nothing. With the fix built locally and the broken build still live,
 * both states were measurable at once:
 *
 *   node tools/browser/hydratecheck.js                                  48 ok, 0 failed
 *   BASE=https://wecare.digital node ... /workspace/engage/              4 FAILs per route
 *
 * Re-run the BASE form after the deploy; it must then agree with the local one.
 *
 * IT MUST COVER AUTHENTICATED ROUTES. The bug lived only on /workspace/*, which no suite in
 * this directory visited - the route list of every other harness is public-only, because
 * public pages are the ones with a design contract. A signed-out visitor to a workspace
 * route gets the sign-in card, and that card rendering in the viewport is a real, checkable
 * state that does not need a session.
 *
 * Run: node tools/browser/hydratecheck.js
 *      BASE=https://wecare.digital node tools/browser/hydratecheck.js
 */

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );

const ARGS = process.argv.slice( 2 );

/**
 * Public routes plus the authenticated ones. The three workspace entries are the point of
 * the file: /workspace/engage/ is the route that was reported blank, /workspace/dashboard/
 * is the app's front door, and /workspace/engage/inbox/ is a nested route, because the
 * defect was in _app.tsx and therefore depth-independent - a sanity check that it is.
 */
const ROUTES = ARGS.length ? ARGS : [
  '/',
  '/grahak-os/',
  '/contact/',
  '/workspace/engage/',
  '/workspace/engage/inbox/',
  '/workspace/dashboard/',
];

const VIEWPORT = { width: 1280, height: 900 };

let pass = 0;
let fail = 0;
const ok = ( name, detail ) => { pass++; console.log( `  ok   ${name}${detail ? ` - ${detail}` : ''}` ); };
const bad = ( name, detail ) => { fail++; console.log( `  FAIL ${name}${detail ? ` - ${detail}` : ''}` ); };

async function measure ( page ) {
  return page.evaluate( () => {
    const root = document.getElementById( '__next' );
    const fold = window.innerHeight;

    /* Element children only. A styled-jsx or Amplify theme <style> is an element and is
       counted deliberately: the duplication showed up as a second <style> too, and a
       harness that filtered styles out would have seen half the evidence. */
    const kids = Array.from( root ? root.children : [] ).map( el => {
      const r = el.getBoundingClientRect();
      return {
        tag: el.tagName,
        // Attribute NAMES, not values. A duplicated subtree repeats both, but names alone
        // are stable against anything React writes per-instance.
        sig: el.tagName + '[' + Array.from( el.attributes ).map( a => a.name ).sort().join( ',' ) + ']',
        top: Math.round( r.top + window.scrollY ),
        h: Math.round( r.height ),
      };
    } );

    const centre = document.elementFromPoint(
      Math.round( window.innerWidth / 2 ), Math.round( fold / 2 )
    );

    return {
      hasRoot: !!root,
      kids,
      fold,
      headers: document.querySelectorAll( 'header' ).length,
      footers: document.querySelectorAll( 'footer' ).length,
      themes: document.querySelectorAll( '[data-amplify-theme]' ).length,
      roots: document.querySelectorAll( '#__next' ).length,
      centreEl: centre
        ? centre.tagName + ( typeof centre.className === 'string' && centre.className
          ? '.' + centre.className.split( /\s+/ ).filter( Boolean ).slice( 0, 2 ).join( '.' )
          : '' )
        : null,
      // Text of the first viewport, so "painted but empty" is distinguishable from "painted".
      firstScreenText: ( () => {
        const el = document.body;
        return ( el.innerText || '' ).trim().slice( 0, 400 ).replace( /\s+/g, ' ' );
      } )(),
    };
  } );
}

( async () => {
  const t = await target();
  console.log( `hydratecheck - ${ROUTES.length} routes against ${t.base} (${t.mode})` );
  console.log( 'engine: Chromium. WebKit and Firefox cannot launch on this host.' );

  const browser = await launch();
  const ctx = await browser.newContext( { viewport: VIEWPORT } );

  for ( const route of ROUTES ) {
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on( 'pageerror', e => pageErrors.push( `${e.name}: ${e.message}` ) );

    let status = null;
    try {
      const res = await gotoStable( page, t.base + route, { settle: 2500 } );
      status = res ? res.status() : null;
    } catch ( e ) {
      bad( `${route} navigates`, e.message );
      await page.close();
      continue;
    }

    console.log( `\n${route} (HTTP ${status})` );

    const m = await measure( page );

    if ( !m.hasRoot ) { bad( 'has a React root', '#__next missing' ); await page.close(); continue; }

    // 1. ONE COPY OF THE APP.
    if ( m.roots === 1 ) ok( 'one #__next' ); else bad( 'one #__next', `found ${m.roots}` );
    if ( m.headers <= 1 ) ok( 'at most one <header>', `${m.headers}` );
    else bad( 'at most one <header>', `${m.headers} - the tree is duplicated, which is what a hydration failure leaves behind` );
    if ( m.footers <= 1 ) ok( 'at most one <footer>', `${m.footers}` );
    else bad( 'at most one <footer>', `${m.footers} - the tree is duplicated` );
    if ( m.themes <= 1 ) ok( 'at most one Amplify theme wrapper', `${m.themes}` );
    else bad( 'at most one Amplify theme wrapper', `${m.themes} - AuthShell rendered twice, so hydration failed at its next/dynamic boundary` );

    // 2. NO TOP-LEVEL CHILD OF #__next IS RENDERED TWICE.
    const seen = new Map();
    for ( const k of m.kids ) seen.set( k.sig, ( seen.get( k.sig ) || [] ).concat( k.top ) );
    const dupes = Array.from( seen.entries() ).filter( ( [ , tops ] ) => tops.length > 1 );
    if ( !dupes.length ) ok( 'no duplicated top-level subtree', `${m.kids.length} children, all distinct` );
    else {
      bad(
        'no duplicated top-level subtree',
        dupes.map( ( [ sig, tops ] ) =>
          `${sig} x${tops.length} at y=${tops.join( '/' )} (fold ${m.fold})` ).join( '; ' )
        + ' - React left the build-time render in place and appended a live copy, so the'
        + ' working page is below the fold'
      );
    }

    // 3. SOMETHING IS PAINTED IN THE MIDDLE OF THE FIRST SCREEN.
    const emptyCentre = !m.centreEl || /^(BODY|HTML)$/.test( m.centreEl.split( '.' )[ 0 ] );
    if ( !emptyCentre ) ok( 'the centre of the first viewport is painted', m.centreEl );
    else bad( 'the centre of the first viewport is painted', `elementFromPoint -> ${m.centreEl}` );

    if ( m.firstScreenText.length >= 20 ) ok( 'the page has readable text', `${m.firstScreenText.length} chars` );
    else bad( 'the page has readable text', `only ${m.firstScreenText.length} chars: "${m.firstScreenText}"` );

    if ( pageErrors.length ) bad( 'no uncaught exception', pageErrors.slice( 0, 3 ).join( ' | ' ) );
    else ok( 'no uncaught exception' );

    await page.close();
  }

  await browser.close();
  await t.close();

  console.log( `\nhydratecheck: ${pass} ok, ${fail} failed` );
  process.exit( fail ? 1 : 0 );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
