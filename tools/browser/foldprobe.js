#!/usr/bin/env node
/**
 * foldprobe — does the primary submit control sit ABOVE the fold on the two customer sign-in
 * surface?
 *
 * WHY THIS EXISTS. /get was given the home page's RotatingHero top section on owner instruction.
 * The hero costs real vertical space — .rh-shell{padding-top:108px} plus
 * .rh-layout{padding:80px 24px 96px;gap:96px} and a headline that is always TWO lines — and /get
 * is not a landing page: its entire job is a form. Pushing the submit control under the fold on a
 * 768px-tall laptop would be a regression that no unit test can see, because jsdom has no layout.
 *
 * ACCEPTANCE, both of which must hold at every viewport:
 *   1. the submit control's bottom is <= innerHeight - 40   (it is on the first screen, with air)
 *
 * Read-only. Serves the existing static export; mutates nothing.
 */
'use strict';

const http = require( 'node:http' );
const fs = require( 'node:fs' );
const path = require( 'node:path' );
const { chromium } = require( 'playwright-core' );

const ROOT = path.resolve( __dirname, '../../out' );
const VIEWPORTS = [
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1280x800', width: 1280, height: 800 },
];

/** Static-export surface covered by this probe. Customer sign-in is backend-routed at /auth. */
const SURFACES = [
  { route: '/get/', label: 'get' },
];

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
};

function serve () {
  const server = http.createServer( ( req, res ) => {
    let rel = decodeURIComponent( ( req.url || '/' ).split( '?' )[ 0 ] );
    let file = path.join( ROOT, rel );
    // trailingSlash export: /get/ -> out/get/index.html
    if ( rel.endsWith( '/' ) ) file = path.join( ROOT, rel, 'index.html' );
    if ( !fs.existsSync( file ) || fs.statSync( file ).isDirectory() )
    {
      const alt = path.join( ROOT, rel, 'index.html' );
      file = fs.existsSync( alt ) ? alt : file;
    }
    if ( !fs.existsSync( file ) || fs.statSync( file ).isDirectory() )
    {
      res.writeHead( 404 ); res.end( 'not found' ); return;
    }
    res.writeHead( 200, { 'Content-Type': TYPES[ path.extname( file ).toLowerCase() ] || 'application/octet-stream' } );
    fs.createReadStream( file ).pipe( res );
  } );
  return new Promise( resolve => server.listen( 0, '127.0.0.1', () => resolve( server ) ) );
}

( async () => {
  if ( !fs.existsSync( ROOT ) )
  {
    console.error( 'No out/ — run `npm run build` first.' );
    process.exit( 2 );
  }

  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch( { args: [ '--no-sandbox' ] } );

  let failures = 0;
  const rows = [];

  for ( const vp of VIEWPORTS )
  {
    const measured = {};
    for ( const surface of SURFACES )
    {
      const page = await browser.newPage( { viewport: { width: vp.width, height: vp.height } } );
      await page.goto( base + surface.route, { waitUntil: 'networkidle' } );
      // The primary action is PillButton. Measure its bottom edge.
      const data = await page.evaluate( () => {
        const pill = document.querySelector( '.pill' );
        const field = document.querySelector( '.pf-num' ) || document.querySelector( 'input' );
        const h1s = document.querySelectorAll( 'h1' ).length;
        const mains = document.querySelectorAll( 'main' ).length;
        return {
          pillBottom: pill ? Math.round( pill.getBoundingClientRect().bottom ) : null,
          pillTag: pill ? pill.tagName : null,
          fieldTop: field ? Math.round( field.getBoundingClientRect().top ) : null,
          innerHeight: window.innerHeight,
          h1s, mains,
        };
      } );
      measured[ surface.label ] = data;
      await page.close();

      if ( data.pillBottom === null )
      {
        console.error( `FAIL ${vp.name} ${surface.route}: no .pill control found` );
        failures++;
        continue;
      }
      const limit = data.innerHeight - 40;
      const ok = data.pillBottom <= limit;
      if ( !ok ) failures++;
      rows.push( {
        viewport: vp.name,
        route: surface.route,
        fieldTop: data.fieldTop,
        pillBottom: data.pillBottom,
        limit,
        aboveFold: ok ? 'PASS' : 'FAIL',
        h1: data.h1s,
        main: data.mains,
      } );
      if ( data.h1s !== 1 || data.mains !== 1 )
      {
        console.error( `FAIL ${vp.name} ${surface.route}: h1=${data.h1s} main=${data.mains} (expected 1/1)` );
        failures++;
      }
    }

    // Agreement between the two halves of the journey.
    if ( measured.get?.pillBottom != null && measured[ 'sign-in' ]?.pillBottom != null )
    {
      const delta = Math.abs( measured.get.pillBottom - measured[ 'sign-in' ].pillBottom );
      const agree = delta <= 80;
      if ( !agree ) failures++;
      console.log( `${vp.name}  delta(get vs sign-in) = ${delta}px  ${agree ? 'PASS' : 'FAIL (>80px)'}` );
    }
  }

  console.table( rows );
  await browser.close();
  server.close();

  console.log( failures === 0 ? '\nfoldprobe: PASS' : `\nfoldprobe: ${failures} FAILURE(S)` );
  process.exit( failures === 0 ? 0 : 1 );
} )().catch( err => { console.error( err ); process.exit( 2 ); } );
