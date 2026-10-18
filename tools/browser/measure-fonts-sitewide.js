'use strict';

/**
 * Site-wide FONT AUDIT. For every page passed on argv (or a default public set),
 * measures every visible text element's computed font-family and font-size at 1440,
 * and reports:
 *   1. every distinct font-family stack in use (should be one Inter stack everywhere)
 *   2. every distinct font-size, with occupancy and a sample, per page and aggregated
 *   3. any element whose family is NOT the expected Inter stack (a "font bundle" leak)
 *
 * Reads computed style in real Chromium, so inherited rules, clamps and media queries
 * all resolve to the number that renders. Not a grep.
 *
 * Usage:
 *   node measure-fonts-sitewide.js                 # default public routes
 *   node measure-fonts-sitewide.js [retired public path] [retired public path]/inbox   # explicit routes
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );
const { PUBLIC_ROUTES } = require( './lib/public-routes' );

// The one stack the public pages declare (index.tsx / Pages). Anything else is a leak.
function normFamily( f ) {
  return f.replace( /["']/g, '' ).split( ',' ).map( s => s.trim() ).slice( 0, 2 ).join( ', ' );
}

async function measureRoute( page, base, route ) {
  await page.setViewportSize( { width: 1440, height: 1000 } );
  const res = await gotoStable( page, base + ( route.endsWith( '/' ) ? route : route + '/' ) );
  const status = res ? res.status() : 0;
  const data = await page.evaluate( () => {
    const walker = document.createTreeWalker( document.body, NodeFilter.SHOW_TEXT );
    const sizes = new Map();
    const families = new Map();
    let n;
    while ( ( n = walker.nextNode() ) ) {
      const txt = n.textContent.trim();
      if ( !txt ) continue;
      const el = n.parentElement;
      if ( !el ) continue;
      const r = el.getBoundingClientRect();
      if ( r.width === 0 || r.height === 0 ) continue;
      const cs = getComputedStyle( el );
      if ( cs.visibility === 'hidden' || cs.display === 'none' ) continue;
      const size = `${Math.round( parseFloat( cs.fontSize ) * 10 ) / 10}/${cs.fontWeight}`;
      if ( !sizes.has( size ) ) sizes.set( size, { count: 0, sample: txt.slice( 0, 32 ) } );
      sizes.get( size ).count++;
      const fam = cs.fontFamily;
      if ( !families.has( fam ) ) families.set( fam, { count: 0, sample: txt.slice( 0, 32 ) } );
      families.get( fam ).count++;
    }
    return {
      sizes: [ ...sizes.entries() ].map( ( [ k, v ] ) => ( { k, ...v } ) ),
      families: [ ...families.entries() ].map( ( [ k, v ] ) => ( { k, ...v } ) ),
    };
  } );
  return { status, ...data };
}

( async () => {
  const routes = process.argv.slice( 2 ).length ? process.argv.slice( 2 ) : PUBLIC_ROUTES;
  const t = await target();
  const browser = await launch();
  const page = await browser.newPage();
  const allFamilies = new Map();
  const allSizes = new Map();
  try {
    for ( const route of routes ) {
      let m;
      try { m = await measureRoute( page, t.base, route ); }
      catch ( e ) { console.log( `\n### ${route}  ERROR ${e.message}` ); continue; }
      const nonInter = m.families.filter( f => !/inter/i.test( f.k ) );
      const flag = nonInter.length ? '  <<< NON-INTER FAMILY' : '';
      console.log( `\n### ${route}  (${m.status})  families:${m.families.length} sizes:${m.sizes.length}${flag}` );
      for ( const f of m.families ) {
        const key = normFamily( f.k );
        allFamilies.set( key, ( allFamilies.get( key ) || 0 ) + f.count );
        if ( !/inter/i.test( f.k ) ) console.log( `   FAMILY ${key}  x${f.count}  e.g. "${f.sample}"` );
      }
      // largest 3 sizes per page, to catch "bigger than the rest of the site"
      const top = [ ...m.sizes ].sort( ( a, b ) => parseFloat( b.k ) - parseFloat( a.k ) ).slice( 0, 4 );
      console.log( '   top sizes: ' + top.map( s => `${s.k}(x${s.count})` ).join( '  ' ) );
      for ( const s of m.sizes ) allSizes.set( s.k, ( allSizes.get( s.k ) || 0 ) + s.count );
    }
    console.log( '\n======== AGGREGATE FONT FAMILIES (all audited routes) ========' );
    for ( const [ k, c ] of [ ...allFamilies.entries() ].sort( ( a, b ) => b[ 1 ] - a[ 1 ] ) ) {
      console.log( `  ${/inter/i.test( k ) ? 'ok ' : 'XX '} x${c}  ${k}` );
    }
    console.log( '\n======== AGGREGATE FONT SIZES (all audited routes, largest first) ========' );
    for ( const [ k, c ] of [ ...allSizes.entries() ].sort( ( a, b ) => parseFloat( b[ 0 ] ) - parseFloat( a[ 0 ] ) ) ) {
      console.log( `  ${k}  x${c}` );
    }
  } finally {
    await browser.close();
    await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
