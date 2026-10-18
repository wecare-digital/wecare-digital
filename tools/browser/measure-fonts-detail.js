'use strict';

/**
 * Given a size/weight of interest, report WHICH routes carry it, with a class/tag
 * sample — so an off-ladder rung can be located rather than just counted.
 * Usage: node measure-fonts-detail.js "19/700" "20/600" "16/700" ...
 */

const { launch, gotoStable } = require( './lib/browser' );
const { target } = require( './lib/serve' );
const { PUBLIC_ROUTES } = require( './lib/public-routes' );

( async () => {
  const wanted = process.argv.slice( 2 );
  const t = await target();
  const browser = await launch();
  const page = await browser.newPage();
  try {
    await page.setViewportSize( { width: 1440, height: 1000 } );
    for ( const route of PUBLIC_ROUTES ) {
      await gotoStable( page, route.endsWith( '/' ) ? t.base + route : t.base + route + '/' );
      const hits = await page.evaluate( ( wanted ) => {
        const walker = document.createTreeWalker( document.body, NodeFilter.SHOW_TEXT );
        const found = {};
        let n;
        while ( ( n = walker.nextNode() ) ) {
          const txt = n.textContent.trim();
          if ( !txt ) continue;
          const el = n.parentElement; if ( !el ) continue;
          const r = el.getBoundingClientRect();
          if ( r.width === 0 || r.height === 0 ) continue;
          const cs = getComputedStyle( el );
          if ( cs.visibility === 'hidden' || cs.display === 'none' ) continue;
          const key = `${Math.round( parseFloat( cs.fontSize ) * 10 ) / 10}/${cs.fontWeight}`;
          if ( !wanted.includes( key ) ) continue;
          const sel = el.className && typeof el.className === 'string'
            ? '.' + el.className.trim().split( /\s+/ ).join( '.' ) : el.tagName.toLowerCase();
          if ( !found[ key ] ) found[ key ] = {};
          const label = `${sel}`;
          if ( !found[ key ][ label ] ) found[ key ][ label ] = txt.slice( 0, 34 );
        }
        return found;
      }, wanted );
      const keys = Object.keys( hits );
      if ( !keys.length ) continue;
      console.log( `\n### ${route}` );
      for ( const k of keys ) {
        for ( const [ sel, sample ] of Object.entries( hits[ k ] ) ) {
          console.log( `   ${k.padEnd( 9 )} ${sel.slice( 0, 40 ).padEnd( 40 )} "${sample}"` );
        }
      }
    }
  } finally {
    await browser.close();
    await t.close();
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
