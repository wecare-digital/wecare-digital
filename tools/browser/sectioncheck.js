'use strict';

/**
 * sectioncheck - how many BANDS each public page is made of, measured in a real browser.
 *
 * WHY NOT grep FOR <section>. That was the first attempt and it is wrong in both
 * directions. The home page counts 2 `<section>` elements in source while rendering 3
 * bands, because the hero is a `<div class="home-hero">`; /vayulok/ and /contact/ count 0
 * while rendering several; and /workspace/dashboard/design-reference counts 40, none of
 * which is a page band. A band is a LAID-OUT thing, so it has to be measured after layout.
 *
 * WHAT COUNTS AS A BAND, and why the walk descends before it counts. The home page nests
 * main > .home-layout > [ hero, flow, close ]: counting main's children would report 1.
 * So the walk steps through any wrapper that is a lone element child, which is the shape a
 * layout container has, and counts the children of the first node that actually branches.
 * Each band is then reported with its own heading, height and offset so the number can be
 * checked against the page rather than trusted.
 *
 * HEADER AND FOOTER ARE EXCLUDED because they are chrome mounted once in _app.tsx for every
 * public route; they are not part of any page's own composition. They are counted once, at
 * the end, so the total is still accounted for.
 *
 * MEASURED AT 1280 ONLY. Band COUNT is not viewport-dependent on these pages - the
 * responsive rules change columns and gaps, not the number of blocks - and the harnesses
 * that do care about width (animcheck at 21 viewports, typecheck at 2) already exist.
 *
 * Run: node tools/browser/sectioncheck.js          (needs out/ - see README.md)
 *      node tools/browser/sectioncheck.js --json
 */

const { target } = require( './lib/serve' );
const { launch, gotoStable } = require( './lib/browser' );
const { installVisible } = require( './lib/visible' );

/**
 * The public routes, matching seocheck.js's list so the two cannot disagree about what
 * "public" means, plus the three index routes seocheck deliberately skips because they are
 * generated rather than authored: /blog/, /store/ and /get/. One /post/ page stands in for
 * all 746 - they share a single template.
 */
const ROUTES = [
  '/', '/grahak-os/', '/vayulok/', '/contact/', '/terms/', '/privacy/',
  '/orders/', '/bharat-rx/',
  '/elsewhere/', '/expo-week/', '/dastavez/', '/clear-closure/',
  '/ritual-guru/', '/anew/', '/niji-setu/', '/hunar/',
  // '/store/' was in this list and has moved to /workspace/commerce/catalog - it was a
  // staff page behind the Authenticator, so it never had a band structure to measure.
  '/blog/', '/get/',
  // The Requests pages, added when the header's six labels stopped all resolving to
  // /contact/. Same shape as the product pages: rotating hero plus one content section.
  '/submit-request/', '/request-amendment/', '/drop-docs/', '/vault/', '/leave-review/',
  '/refer-and-earn/',
  // The catalogue. '/shop/' WAS HERE and was described as "a hero plus a card grid, like /blog/
  // above it". THAT DESCRIPTION IS NO LONGER TRUE: the owner withdrew the index on 2026-10-04, so
  // the route 301s to the home page and there is no hero and no grid to inspect. Removed rather
  // than re-described, because a harness that loads a redirect audits home twice or fails.
  //
  // /shop/kiosk/ STAYS and is the whole catalogue coverage now. It is a slug rendered by
  // src/pages/shop/[slug].tsx and it is the one public page that does NOT wrap itself in
  // RotatingHero, so its band structure and header clearance are its own file's work rather than
  // the shared shell's. That is exactly the case this harness exists for.
  '/shop/kiosk/',
];

const inventory = async () => {
  const t = await target();
  const browser = await launch();
  const page = await browser.newPage( { viewport: { width: 1280, height: 900 } } );
  await installVisible( page );

  const rows = [];

  for ( const route of ROUTES ) {
    await gotoStable( page, t.base + route );

    const data = await page.evaluate( () => {
      // Shared predicate - lib/visible.js. This checked height, display and visibility,
      // but not width, not opacity, and not an ancestor at opacity:0 - which is the state
      // an unrevealed scroll-reveal section sits in.
      const vis = el => window.__visible( el );

      const main = document.querySelector( 'main' ) || document.body;

      // Descend through lone-child wrappers - that is what a layout container looks like -
      // and stop at the first node that actually branches into siblings.
      let node = main;
      for ( let depth = 0; depth < 6; depth++ ) {
        const kids = [ ...node.children ].filter( vis );
        if ( kids.length !== 1 ) break;
        node = kids[ 0 ];
      }

      const bands = [ ...node.children ].filter( vis ).map( el => {
        const r = el.getBoundingClientRect();
        const heading = el.querySelector( 'h1,h2,h3' );
        return {
          tag: el.tagName.toLowerCase(),
          cls: ( el.className || '' ).toString()
            .split( /\s+/ ).filter( c => c && !c.startsWith( 'jsx-' ) ).join( '.' ),
          heading: heading ? heading.textContent.trim().replace( /\s+/g, ' ' ).slice( 0, 58 ) : '',
          h: Math.round( r.height ),
          top: Math.round( r.top + window.scrollY ),
        };
      } );

      return {
        container: ( node.className || node.tagName ).toString()
          .split( /\s+/ ).filter( c => c && !c.startsWith( 'jsx-' ) ).join( '.' ),
        bands,
        h1: [ ...document.querySelectorAll( 'h1' ) ].map( e => e.textContent.trim().replace( /\s+/g, ' ' ) ),
        h2Count: document.querySelectorAll( 'h2' ).length,
        hasHeader: !!document.querySelector( 'header' ),
        hasFooter: !!document.querySelector( 'footer' ),
        docHeight: Math.round( document.documentElement.scrollHeight ),
      };
    } );

    rows.push( { route, ...data } );
  }

  await browser.close();
  await t.close();
  return rows;
};

inventory().then( rows => {
  if ( process.argv.includes( '--json' ) ) {
    console.log( JSON.stringify( rows, null, 2 ) );
    return;
  }

  console.log( '\nBANDS PER PUBLIC PAGE - measured at 1280x900, header/footer excluded\n' );
  console.log( 'bands  h1  h2  page height  route' );
  console.log( '-----  --  --  -----------  -----' );
  let total = 0;
  for ( const r of rows ) {
    total += r.bands.length;
    console.log(
      `${String( r.bands.length ).padStart( 5 )}  ${String( r.h1.length ).padStart( 2 )}` +
      `  ${String( r.h2Count ).padStart( 2 )}  ${String( r.docHeight ).padStart( 11 )}  ${r.route}`
    );
  }
  console.log( `-----\n${String( total ).padStart( 5 )}  bands across ${rows.length} public pages` );

  for ( const r of rows ) {
    console.log( `\n=== ${r.route}   (${r.bands.length} bands, container ${r.container}) ===` );
    if ( r.h1.length !== 1 ) console.log( `  !! ${r.h1.length} h1 elements` );
    r.bands.forEach( ( b, i ) => {
      console.log(
        `  ${String( i + 1 ).padStart( 2 )}. ${b.tag}.${b.cls || '(no class)'}`.padEnd( 52 ) +
        `h ${String( b.h ).padStart( 5 )}  top ${String( b.top ).padStart( 5 )}` +
        ( b.heading ? `  "${b.heading}"` : '  (no heading)' )
      );
    } );
  }

  const noHeader = rows.filter( r => !r.hasHeader ).map( r => r.route );
  const noFooter = rows.filter( r => !r.hasFooter ).map( r => r.route );
  console.log( '\n=== CHROME ===' );
  console.log( `  pages missing <header>: ${noHeader.join( ', ' ) || 'none'}` );
  console.log( `  pages missing <footer>: ${noFooter.join( ', ' ) || 'none'}` );
  const badH1 = rows.filter( r => r.h1.length !== 1 ).map( r => `${r.route} (${r.h1.length})` );
  console.log( `  pages without exactly one h1: ${badH1.join( ', ' ) || 'none'}` );
} ).catch( e => { console.error( e ); process.exit( 1 ); } );
